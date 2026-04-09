"""
Career / job assignment.

Jobs come from the SQLite `jobs` table (seeded from data/seed.py and validated
against the original game's `jobs.dat` schema). Each job has minimum
education, intelligence, age range, salary band, and an urban-only flag.

Salary scales with country GDP per capita: a doctor in Switzerland earns
much more than a doctor in Bangladesh, mirroring the original game's PPP
adjustment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

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


def _scale_for_country(country: Country) -> float:
    """A normalized scalar that turns USD-baseline salaries into local-equivalent."""
    return max(0.05, country.gdp_pc / 50000)


def all_jobs() -> list[Job]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM jobs").fetchall()
    finally:
        conn.close()
    return [
        Job(
            id=r["id"], name=r["name"],
            min_education=r["min_education"], min_intelligence=r["min_intelligence"],
            min_age=r["min_age"], max_age=r["max_age"],
            salary_low=r["salary_low"], salary_high=r["salary_high"],
            urban_only=bool(r["urban_only"]),
        )
        for r in rows
    ]


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
        out.append(j)
    return out


def assign_job(character: Character, country: Country, rng: random.Random) -> str | None:
    """If the character has no job and is of working age, try to find one."""
    if character.job is not None:
        return None
    if character.age < 14:
        return None
    if character.in_school:
        return None
    options = eligible_jobs(character, country)
    if not options:
        return None
    chosen = rng.choice(options)
    scale = _scale_for_country(country)
    base = rng.randint(chosen.salary_low, chosen.salary_high)
    character.job = chosen.name
    character.salary = max(100, int(base * scale))
    return f"You started working as a {chosen.name} (salary ~${character.salary:,}/yr)."


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
