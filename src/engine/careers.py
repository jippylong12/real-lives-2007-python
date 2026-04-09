"""
Career / job assignment.

Jobs come from the SQLite `jobs` table, populated directly from the
original game's `jobs.dat` (#51) — 131 occupations across 14 categories
with explicit promotion ladders pulled from the binary's PromotesTo
field.

Each job has: education floor, intelligence floor, age range, salary
band, urban_only / rural_only restrictions, a vocation `category`, and
a `promotes_to` job name pointing at the next rung of its ladder.

Salary scales with country GDP per capita: a doctor in Switzerland earns
much more than a doctor in Bangladesh, mirroring the original game's PPP
adjustment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from .character import Character, EducationLevel
from .world import Country
from ..data.build_db import get_connection


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    min_education: int
    min_intelligence: int
    min_age: int
    max_age: int
    salary_low: int
    salary_high: int
    urban_only: bool
    rural_only: bool
    category: str | None
    promotes_to: str | None


def _scale_for_country(country: Country) -> float:
    """A normalized scalar that turns USD-baseline salaries into local-equivalent."""
    return max(0.05, country.gdp_pc / 50000)


@lru_cache(maxsize=1)
def all_jobs() -> tuple[Job, ...]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM jobs").fetchall()
    finally:
        conn.close()
    return tuple(
        Job(
            id=r["id"], name=r["name"],
            min_education=r["min_education"], min_intelligence=r["min_intelligence"],
            min_age=r["min_age"], max_age=r["max_age"],
            salary_low=r["salary_low"], salary_high=r["salary_high"],
            urban_only=bool(r["urban_only"]),
            rural_only=bool(r["rural_only"]),
            category=r["category"],
            promotes_to=r["promotes_to"],
        )
        for r in rows
    )


def get_job(name: str) -> Job | None:
    """Look up a job by name. Returns None if no such job exists."""
    return next((j for j in all_jobs() if j.name == name), None)


def jobs_in_category(category: str) -> list[Job]:
    return [j for j in all_jobs() if j.category == category]


def _entry_jobs_in_category(category: str) -> list[Job]:
    """Jobs in `category` that are NOT the destination of any other job's
    promotes_to chain — i.e., the bottom rungs of the category's ladders.
    Used by assign_job to start a fresh career at the entry level.
    """
    cat_jobs = jobs_in_category(category)
    upstream_targets = {j.promotes_to for j in cat_jobs if j.promotes_to}
    return [j for j in cat_jobs if j.name not in upstream_targets]


def eligible_jobs(character: Character, country: Country) -> list[Job]:
    out: list[Job] = []
    for j in all_jobs():
        if character.age < j.min_age or character.age > j.max_age:
            continue
        if int(character.education) < j.min_education:
            continue
        if character.attributes.intelligence < j.min_intelligence:
            continue
        # Urban-only jobs require the character to actually live in a city,
        # not just a country with a high urban percentage.
        if j.urban_only and not character.is_urban:
            continue
        if j.rural_only and character.is_urban:
            continue
        # If the character has chosen a vocation field, restrict jobs to
        # that category. (vocation_field defaults to None for unspecialized
        # characters — they're eligible for any job in any category.)
        if character.vocation_field and j.category != character.vocation_field:
            continue
        out.append(j)
    return out


def assign_job(character: Character, country: Country, rng: random.Random) -> str | None:
    """If the character has no job and is of working age, try to find one.

    Career start (#51): if the character has chosen a vocation field
    (via the EDUCATION_PATH choice from #42 or its #48 follow-up), they
    start at an *entry-level* job in that field — the bottom rung of one
    of the field's ladders, not a random eligible job. Without a field
    they pick from any eligible job (the unspecialized path).
    """
    if character.job is not None:
        return None
    if character.age < 14:
        return None
    if character.in_school:
        return None

    options: list[Job] = []
    if character.vocation_field:
        # Constrained: pick from entry-level jobs in the chosen field
        # that the character also meets requirements for.
        entry = _entry_jobs_in_category(character.vocation_field)
        options = [j for j in entry if _meets_requirements(j, character)]
    if not options:
        # Either no vocation field, or the field's entry rungs don't fit
        # this character's age/education/etc. Fall back to all eligible.
        options = eligible_jobs(character, country)
    if not options:
        return None

    chosen = rng.choice(options)
    _set_job(character, country, chosen, rng)
    character.years_in_role = 0
    return f"You started working as a {chosen.name} (salary ~${character.salary:,}/yr)."


def _meets_requirements(job: Job, character: Character) -> bool:
    if character.age < job.min_age or character.age > job.max_age:
        return False
    if int(character.education) < job.min_education:
        return False
    if character.attributes.intelligence < job.min_intelligence:
        return False
    if job.urban_only and not character.is_urban:
        return False
    if job.rural_only and character.is_urban:
        return False
    return True


def _set_job(character: Character, country: Country, job: Job, rng: random.Random) -> None:
    """Common path for both assign_job and promote — sets job + salary
    scaled to the country's GDP per capita."""
    scale = _scale_for_country(country)
    base = rng.randint(job.salary_low, job.salary_high)
    character.job = job.name
    character.salary = max(100, int(base * scale))


def promote(character: Character, country: Country, rng: random.Random) -> str | None:
    """Per-year promotion check (#51). Walks the binary's PromotesTo
    chain when:
      - The character has been in their current role long enough
        (`years_in_role >= years_to_promote`)
      - They meet the next rung's intelligence + age requirements
      - The next rung exists (terminal jobs return None)

    Years required for promotion scale with the rank: 5 years for the
    first hop, 7 for the second, 10 thereafter — so a junior accountant
    can become an accountant fairly quickly but climbing to general
    manager + company president takes a full career.
    """
    if character.job is None:
        return None
    current = get_job(character.job)
    if current is None or not current.promotes_to:
        return None
    next_job = get_job(current.promotes_to)
    if next_job is None:
        return None

    # How many promotions has the character already taken? Use the gap
    # between the entry tier and current as a proxy via promotion_count.
    promo_count = character.promotion_count or 0
    if promo_count == 0:
        years_required = 5
    elif promo_count == 1:
        years_required = 7
    else:
        years_required = 10

    if character.years_in_role < years_required:
        return None
    if not _meets_requirements(next_job, character):
        return None

    _set_job(character, country, next_job, rng)
    character.years_in_role = 0
    character.promotion_count = promo_count + 1
    return f"You were promoted to {next_job.name} (salary ~${character.salary:,}/yr)."


def quit_job(character: Character) -> None:
    """Manually quit the current job (#38). Resets job + salary so the
    next yearly tick re-runs ``assign_job`` and assigns a fresh role.

    Raises ValueError if the character isn't currently employed.
    """
    if character.job is None:
        raise ValueError("you don't have a job to quit")
    character.job = None
    character.salary = 0


def yearly_income(character: Character, country: Country, rng: random.Random) -> int:
    """Apply income, expenses, and possibly a small variance for the year."""
    if character.salary <= 0:
        return 0
    variance = 1.0 + rng.uniform(-0.05, 0.10)
    income = int(character.salary * variance)
    expenses = int(income * 0.75)  # rent, food, transport, etc.
    net = income - expenses
    character.money += net
    return net
