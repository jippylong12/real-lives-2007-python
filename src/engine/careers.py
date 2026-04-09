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
    is_freelance: bool = False


def _scale_for_country(country: Country) -> float:
    """A normalized scalar that turns USD-baseline salaries into local-equivalent."""
    return max(0.05, country.gdp_pc / 50000)


# Attribute-driven progression (#60). Each category maps to a single
# character attribute that drives both promotion speed and salary
# within a role. This is loaded from seed.JOB_CATEGORY_META rather than
# duplicating the table here.
def _relevant_attribute(category: str | None) -> str:
    if category is None:
        return "intelligence"
    from ..data.seed import JOB_CATEGORY_META
    meta = JOB_CATEGORY_META.get(category, {})
    return meta.get("relevant_attribute", "intelligence")


def _skill_factor(character: Character, category: str | None) -> float:
    """Multiplier representing how the character's relevant attribute
    compares to a baseline of 60. Capped to [0.5, 2.0] so extreme
    attribute values don't break the simulation.

    A skill_factor > 1.0 means the character is above-average for the
    category — promotions come faster, salaries are higher within a
    role. A skill_factor < 1.0 means below-average — slower climb,
    lower pay.
    """
    attr = _relevant_attribute(category)
    value = getattr(character.attributes, attr, 60)
    return max(0.5, min(2.0, value / 60.0))


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
            is_freelance=bool(r["is_freelance"]),
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
    scaled to the country's GDP per capita and the character's
    category-relevant attribute (#60).

    A high-skill character earns 50-100% more in the same role; a
    low-skill character earns 25-50% less. The bonus / penalty is
    centered on attribute=60 (the design baseline)."""
    scale = _scale_for_country(country)
    base = rng.randint(job.salary_low, job.salary_high)
    skill = _skill_factor(character, job.category)
    # 0.5 + skill/2 → at skill 1.0, no change; at skill 2.0, +50%; at
    # skill 0.5, -25%.
    skill_pay = 0.5 + skill / 2.0
    character.job = job.name
    character.salary = max(100, int(base * scale * skill_pay))


# ---------------------------------------------------------------------------
# Ask for a raise / promotion (#55)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RaiseResult:
    """Return value of :func:`request_raise`."""
    outcome: str           # 'promotion' | 'raise' | 'denied' | 'fired' | 'cooldown' | 'not_eligible'
    message: str
    salary_delta: int = 0
    new_job: str | None = None


# Cooldown after any raise request — denied OR granted, since granted
# requests reset years_in_role to 0 which already enforces a much longer
# wait before the next eligibility window.
_RAISE_COOLDOWN_YEARS = 2


def _years_required_for_promo(character: Character, current: Job) -> int:
    """Skill-adjusted years_in_role threshold for the next promotion (#60)."""
    promo_count = character.promotion_count or 0
    base = 5 if promo_count == 0 else 7 if promo_count == 1 else 10
    skill = _skill_factor(character, current.category)
    return max(2, int(round(base / skill)))


def can_request_raise(character: Character) -> tuple[bool, str | None]:
    """Whether the player can press the 'ask for raise' button right now.
    Returns (eligible, reason). Used by the frontend to grey the button."""
    if character.job is None:
        return False, "you don't have a job"
    current = get_job(character.job)
    if current is None:
        return False, "unknown job"
    years_required = _years_required_for_promo(character, current)
    if character.years_in_role < years_required:
        return False, f"need {years_required - character.years_in_role} more year(s) in role"
    if character.last_raise_request_age is not None:
        gap = character.age - character.last_raise_request_age
        if gap < _RAISE_COOLDOWN_YEARS:
            return False, f"asked recently, wait {_RAISE_COOLDOWN_YEARS - gap} year(s)"
    return True, None


def request_raise(
    character: Character,
    country: Country,
    rng: random.Random,
) -> RaiseResult:
    """Player-initiated raise / promotion request (#55).

    Resolution sequence:
      1. **Promotion** — if the next-rung requirements are met, the
         character actually gets promoted (same as :func:`promote`).
         Probability boosted by performance.
      2. **Raise** — salary bumps 8-25% but the job stays the same.
         years_in_role resets to 0 (you've reset your seniority clock).
      3. **Denied** — small happiness hit, no change.
      4. **Fired** — rare (~5% baseline), penalized by performance.

    Performance is composed of intelligence + wisdom + endurance,
    normalized to 0..1. Each year past the years_to_promote threshold
    adds 5% to the favorable outcomes (you've earned a stronger ask).
    A high-conscience character is slightly less aggressive (-10%) so
    they sometimes hold back from demanding what they could.
    """
    eligible, reason = can_request_raise(character)
    if not eligible:
        return RaiseResult(outcome="not_eligible" if reason and "year" not in reason else "cooldown",
                           message=reason or "not eligible right now")

    current = get_job(character.job)  # already validated above
    promo_count = character.promotion_count or 0
    years_required = _years_required_for_promo(character, current)
    years_past = character.years_in_role - years_required

    # Performance: heavily weight the category-relevant attribute (#60)
    # so an artistic painter can argue for a raise on creative output,
    # while an engineer's case rests on intelligence.
    relevant = _relevant_attribute(current.category)
    relevant_value = getattr(character.attributes, relevant, 60)
    perf = (relevant_value * 2
            + character.attributes.wisdom
            + character.attributes.endurance) / 400.0
    boldness_penalty = 0.10 if character.attributes.conscience > 70 else 0.0

    promote_p = 0.10 + perf * 0.20 + years_past * 0.05 - boldness_penalty
    raise_p = 0.45 + perf * 0.20 + years_past * 0.03 - boldness_penalty
    fire_p = max(0.01, 0.08 - perf * 0.06)

    # Mark the request so the cooldown applies regardless of outcome.
    character.last_raise_request_age = character.age

    roll = rng.random()

    # Promotion path: only if the character actually meets the next rung
    # AND the promote_p check fires. Otherwise fall through to raise/deny.
    if current.promotes_to:
        next_job = get_job(current.promotes_to)
        if next_job and _meets_requirements(next_job, character) and roll < promote_p:
            old_salary = character.salary
            _set_job(character, country, next_job, rng)
            character.years_in_role = 0
            character.promotion_count = promo_count + 1
            return RaiseResult(
                outcome="promotion",
                message=f"You asked for more responsibility. They promoted you to {next_job.name}!",
                salary_delta=character.salary - old_salary,
                new_job=next_job.name,
            )

    # Raise path: salary bump in the same role.
    if roll < promote_p + raise_p:
        old_salary = character.salary
        bump_pct = rng.uniform(0.08, 0.25)
        character.salary = int(character.salary * (1 + bump_pct))
        character.years_in_role = 0
        return RaiseResult(
            outcome="raise",
            message=f"You asked for a raise. They agreed — {int(bump_pct * 100)}% bump.",
            salary_delta=character.salary - old_salary,
        )

    # Fire path: insubordination.
    if roll > 1.0 - fire_p:
        character.job = None
        character.salary = 0
        character.years_in_role = 0
        character.promotion_count = 0
        return RaiseResult(
            outcome="fired",
            message="You demanded too aggressively. You were let go.",
        )

    # Denied: nothing changes.
    return RaiseResult(
        outcome="denied",
        message="You asked for a raise. They turned you down.",
    )


# ---------------------------------------------------------------------------
# Job board: browse + apply (#54), with life-stage gates (#57)
# ---------------------------------------------------------------------------


def minimum_working_age(country: Country) -> int:
    """Country-aware minimum age at which a character can take ANY job (#57).

    High-HDI countries enforce school + child-labor laws strictly: 14.
    Mid-HDI countries: 12. Low-HDI countries (where the binary's
    'subsistence farmer' / 'scavenger' jobs ship with min_age 5-8):
    relaxed to 8 to match real-world child labor patterns the original
    game models.
    """
    if country.hdi >= 0.7:
        return 14
    if country.hdi >= 0.5:
        return 12
    return 8


def can_character_work(character: Character, country: Country) -> tuple[bool, str | None]:
    """Whether the character is currently allowed to look for work.
    Returns (allowed, reason). The frontend hides the 'Find work' button
    based on this and shows the reason in its place (#57)."""
    floor = minimum_working_age(country)
    if character.age < floor:
        return False, f"too young (work allowed at {floor}+ in {country.name})"
    # Characters in basic schooling shouldn't be working full-time. Once
    # they hit secondary / vocational / university the world opens up,
    # since the binary's professional jobs assume school overlap.
    if character.in_school and int(character.education) < int(EducationLevel.SECONDARY):
        return False, "still in primary school"
    return True, None


@dataclass(frozen=True)
class JobListing:
    """One row in the job board's listing — a job plus the character's
    eligibility for it. Returned by :func:`job_listing`."""
    job: Job
    status: str               # 'qualified' | 'stretch' | 'long_shot' | 'out_of_reach'
    accept_chance: float      # 0.0–1.0; never below 0.01 (the floor)
    missing: list[str]        # human-readable list of failed gates
    expected_salary: int      # PPP-scaled salary midpoint for this character


@dataclass(frozen=True)
class ApplyResult:
    """Return value of :func:`apply_for_job`."""
    accepted: bool
    message: str
    new_job: str | None = None
    new_salary: int = 0


def _missing_requirements(job: Job, character: Character) -> list[str]:
    """List the gates the character fails for `job`. Empty list = qualified."""
    out: list[str] = []
    if character.age < job.min_age:
        out.append(f"too young (need {job.min_age}+)")
    elif character.age > job.max_age:
        out.append(f"too old (cap {job.max_age})")
    if int(character.education) < job.min_education:
        edu_labels = ["none", "primary", "secondary", "vocational", "university"]
        out.append(f"need {edu_labels[job.min_education]} education")
    if character.attributes.intelligence < job.min_intelligence:
        out.append(f"need IQ {job.min_intelligence}+")
    if job.urban_only and not character.is_urban:
        out.append("urban residents only")
    if job.rural_only and character.is_urban:
        out.append("rural residents only")
    return out


def _accept_probability(job: Job, character: Character) -> tuple[float, str]:
    """Compute the acceptance probability for a hypothetical application
    and return (probability, status_label). The floor is 1% — even an
    extremely unqualified application has a non-zero chance, mirroring
    real-world luck."""
    missing = _missing_requirements(job, character)
    n_missing = len(missing)

    if n_missing == 0:
        base = 0.80
        status = "qualified"
    elif n_missing == 1:
        base = 0.30
        status = "stretch"
    elif n_missing == 2:
        base = 0.10
        status = "long_shot"
    else:
        base = 0.03
        status = "out_of_reach"

    # Vocation field mismatch makes career switching harder. The penalty
    # only applies if the character has already locked in a different
    # field (otherwise unspecialized characters can apply anywhere).
    if character.vocation_field and job.category and job.category != character.vocation_field:
        base *= 0.4

    return max(0.01, base), status


def job_listing(character: Character, country: Country) -> list[JobListing]:
    """Return every job in the catalogue annotated with the character's
    eligibility, predicted acceptance probability, and PPP-scaled salary
    estimate. Used by the frontend's job board (#54).

    Returns an empty list if the character isn't allowed to work yet
    (#57). Within the catalogue, jobs whose min_age is more than 2 years
    above the character's current age are filtered out — the player
    can't see "long shot" entries for jobs they're physically too young
    for, only ones they're close to being able to do.
    """
    allowed, _ = can_character_work(character, country)
    if not allowed:
        return []
    scale = _scale_for_country(country)
    out: list[JobListing] = []
    for job in all_jobs():
        if job.min_age > character.age + 2:
            continue
        chance, status = _accept_probability(job, character)
        midpoint = (job.salary_low + job.salary_high) // 2
        expected_salary = max(100, int(midpoint * scale))
        out.append(JobListing(
            job=job,
            status=status,
            accept_chance=chance,
            missing=_missing_requirements(job, character),
            expected_salary=expected_salary,
        ))
    return out


def apply_for_job(
    character: Character,
    country: Country,
    job_name: str,
    rng: random.Random,
) -> ApplyResult:
    """Roll for acceptance to ``job_name``. Always at least a 1% chance;
    fully qualified candidates land at 80%. Vocation field mismatches
    halve (×0.4) the base. On accept the character takes the new job and
    their years_in_role + promotion_count reset (career restart)."""
    job = get_job(job_name)
    if job is None:
        return ApplyResult(accepted=False, message=f"unknown job {job_name!r}")

    chance, status = _accept_probability(job, character)
    if rng.random() >= chance:
        return ApplyResult(
            accepted=False,
            message=f"You applied to be a {job.name} but didn't get the offer.",
        )

    # Got it. Switch jobs (this implicitly quits the previous role).
    _set_job(character, country, job, rng)
    character.years_in_role = 0
    character.promotion_count = 0
    return ApplyResult(
        accepted=True,
        message=f"You got the job — you're now a {job.name} (~${character.salary:,}/yr).",
        new_job=job.name,
        new_salary=character.salary,
    )


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

    # Attribute-driven progression speed (#60). A high-skill character
    # promotes ~half as fast; a low-skill character takes nearly twice
    # as long. Uses the character's CURRENT job category to pick the
    # relevant attribute.
    skill = _skill_factor(character, current.category)
    years_required = max(2, int(round(years_required / skill)))

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
    """Apply income, expenses, and yearly variance.

    Salaried jobs have tight variance (-5% to +10%): a steady paycheck.
    Freelance jobs (#61) have a much wider luck roll AND scale heavily
    with the relevant attribute — a high-skill freelance artist thrives,
    a low-skill one starves.
    """
    if character.salary <= 0:
        return 0

    job = get_job(character.job) if character.job else None
    if job is not None and job.is_freelance:
        # Freelance: salary is the *baseline* talent rate but each year
        # is a coin-flip on luck. Talent multiplier centered on 50 means
        # an artistic-90 freelance writer earns 1.8x baseline; an
        # artistic-25 one earns 0.5x.
        attr = _relevant_attribute(job.category)
        talent = max(0.4, min(2.5, getattr(character.attributes, attr, 50) / 50.0))
        luck = rng.uniform(0.5, 2.0)
        income = int(character.salary * talent * luck)
    else:
        variance = 1.0 + rng.uniform(-0.05, 0.10)
        income = int(character.salary * variance)

    expenses = int(income * 0.75) if income > 0 else 0
    net = income - expenses
    character.money += net
    return net
