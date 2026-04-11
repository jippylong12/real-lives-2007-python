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

import math
import random
from dataclasses import dataclass
from functools import lru_cache

from .character import Character, EducationLevel
from .world import Country
from . import finances
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
    promotion_years: int | None = None      # per-job years-in-role override
    is_seniority_step: bool = False          # step/tier advance, not a role change


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
            promotion_years=r["promotion_years"],
            is_seniority_step=bool(r["is_seniority_step"]),
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


@dataclass(frozen=True)
class RetireResult:
    """Return value of :func:`retire` (#82)."""
    outcome: str           # 'retired' | 'not_eligible'
    message: str
    former_job: str | None = None


# Cooldown after any raise request — denied OR granted, since granted
# requests reset years_in_role to 0 which already enforces a much longer
# wait before the next eligibility window.
_RAISE_COOLDOWN_YEARS = 2


# #82: per-category minimum retirement age. Players can retire at or
# above this threshold regardless of savings; below it, the wealth
# override kicks in. Buckets are well below the matching
# MAX_AGE_BY_CATEGORY caps from #84 so there's a meaningful
# early-retirement window — athletics retire at 30 (cap 40), military
# at 40 (cap 55), most office work at 55 (cap 65-75).
MIN_RETIREMENT_AGE_BY_CATEGORY: dict[str, int] = {
    "athletics":   30,   # most pros retire by their early 30s
    "military":    40,   # 20-yr service pension common
    "police":      45,
    "maritime":    50,
    "industrial":  55,
    "trades":      55,
    "agriculture": 55,
    "service":     55,
    "stem":        55,
    "education":   55,
    "business":    55,
    "government":  55,
    "medical":     55,
    "arts":        55,
}
DEFAULT_MIN_RETIREMENT_AGE = 55

# Wealth override: a player below the age threshold can still retire
# if (cash + portfolio) covers ~20 years of their current annual
# expenses. Lines up with the FIRE community's "25x rule" but a touch
# more lenient since lives in this sim run short.
RETIREMENT_WEALTH_MULTIPLIER = 20


def _years_required_for_promo(character: Character, current: Job) -> int:
    """Skill-adjusted years_in_role threshold for the next promotion (#60).

    If the current job has ``promotion_years`` set, that value is used
    as the base (per-job pacing). Otherwise falls back to the global
    formula based on ``promotion_count``.
    """
    if current.promotion_years is not None:
        base = current.promotion_years
    else:
        promo_count = character.promotion_count or 0
        if promo_count == 0:
            base = 5
        elif promo_count == 1:
            base = 7
        else:
            base = 10
    skill = _skill_factor(character, current.category)
    return max(3, int(round(base / skill)))


def can_request_salary_raise(character: Character) -> tuple[bool, str | None]:
    """Whether the player can ask for a salary raise (#63). Available
    even at the top of the ladder — there's no rung gate, just years
    in role + cooldown."""
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


def can_request_promotion(character: Character) -> tuple[bool, str | None]:
    """Whether the player can ask for a promotion (#63). Requires:
    a job with a next-rung in the ladder, the character meets that
    rung's requirements, plus the standard years_in_role + cooldown
    gates. At the top of the ladder this is always False — there's
    nothing to promote to."""
    if character.job is None:
        return False, "you don't have a job"
    current = get_job(character.job)
    if current is None:
        return False, "unknown job"
    if not current.promotes_to:
        return False, "top of the ladder"
    next_job = get_job(current.promotes_to)
    if next_job is None:
        return False, "no next rung"
    if not _meets_requirements(next_job, character):
        # The next rung exists but the character doesn't qualify yet —
        # surface a hint about what's missing.
        missing = _missing_requirements(next_job, character)
        if missing:
            return False, f"need {missing[0]} for the next rung"
        return False, "not yet qualified for the next rung"
    years_required = _years_required_for_promo(character, current)
    if character.years_in_role < years_required:
        return False, f"need {years_required - character.years_in_role} more year(s) in role"
    if character.last_raise_request_age is not None:
        gap = character.age - character.last_raise_request_age
        if gap < _RAISE_COOLDOWN_YEARS:
            return False, f"asked recently, wait {_RAISE_COOLDOWN_YEARS - gap} year(s)"
    return True, None


# Backwards-compat alias used by the existing /api/game/{id}/request_raise
# endpoint and the older career payload field. Maps to the salary-raise
# variant since the original button was labeled 'Ask for raise'.
def can_request_raise(character: Character) -> tuple[bool, str | None]:
    return can_request_salary_raise(character)


def can_retire(character: Character, country: Country) -> tuple[bool, str | None]:
    """Whether the player can choose to retire early (#82). Eligible
    when the character is at or above the per-category min retirement
    age, OR when their (cash + portfolio) covers ~20 years of current
    annual expenses (the FIRE wealth override). Always blocked when
    the character has no job to retire from."""
    if character.job is None:
        return False, "you don't have a job"
    current = get_job(character.job)
    if current is None:
        return False, "unknown job"
    min_age = MIN_RETIREMENT_AGE_BY_CATEGORY.get(
        current.category, DEFAULT_MIN_RETIREMENT_AGE
    )
    if character.age >= min_age:
        return True, None
    # Wealth override: enough saved to cover ~20 years of expenses.
    baseline = finances.baseline_cost_of_living(country)
    annual_expense = max(baseline, int(character.salary * 0.75))
    threshold = RETIREMENT_WEALTH_MULTIPLIER * annual_expense
    total_wealth = character.money + finances.portfolio_value(character)
    if total_wealth >= threshold:
        return True, None
    return False, (
        f"need to be {min_age}+ or have ~${threshold:,} saved "
        f"(have ${total_wealth:,})"
    )


def retire(character: Character, country: Country) -> RetireResult:
    """Player-initiated early retirement (#82). Validates the
    :func:`can_retire` gate, then clears the character's job, salary,
    and years_in_role while preserving promotion_count. Writes a
    timeline entry. Returns a RetireResult."""
    eligible, reason = can_retire(character, country)
    if not eligible:
        return RetireResult("not_eligible", reason or "not eligible")
    former = character.job or "your job"
    character.job = None
    character.salary = 0
    character.years_in_role = 0
    # promotion_count preserved — they earned those promotions
    character.remember(f"Retired from being a {former}.")
    return RetireResult(
        outcome="retired",
        message=f"You retired from being a {former}.",
        former_job=former,
    )


def _performance_score(character: Character, current: Job) -> float:
    """Normalized 0..1 performance score: heavily weights the
    category-relevant attribute (#60), with wisdom + endurance as
    secondary contributors. Used by both raise and promotion rolls."""
    relevant = _relevant_attribute(current.category)
    relevant_value = getattr(character.attributes, relevant, 60)
    return (relevant_value * 2
            + character.attributes.wisdom
            + character.attributes.endurance) / 400.0


def request_salary_raise(
    character: Character,
    country: Country,
    rng: random.Random,
) -> RaiseResult:
    """Player-initiated salary raise request (#63 split). Outcomes:
    raise / denied / fired. NO promotion path — that's
    :func:`request_promotion`.

    Salary bumps 8-25% on success. years_in_role resets to 0 (raise
    resets the seniority clock).
    """
    eligible, reason = can_request_salary_raise(character)
    if not eligible:
        return RaiseResult(
            outcome="not_eligible" if reason and "year" not in reason else "cooldown",
            message=reason or "not eligible right now",
        )

    current = get_job(character.job)
    years_required = _years_required_for_promo(character, current)
    years_past = character.years_in_role - years_required
    perf = _performance_score(character, current)
    boldness_penalty = 0.10 if character.attributes.conscience > 70 else 0.0

    raise_p = 0.55 + perf * 0.25 + years_past * 0.04 - boldness_penalty
    fire_p = max(0.01, 0.06 - perf * 0.05)

    character.last_raise_request_age = character.age
    roll = rng.random()

    if roll < raise_p:
        old_salary = character.salary
        bump_pct = rng.uniform(0.08, 0.25)
        character.salary = int(character.salary * (1 + bump_pct))
        character.years_in_role = 0
        return RaiseResult(
            outcome="raise",
            message=f"You asked for a raise. They agreed — {int(bump_pct * 100)}% bump.",
            salary_delta=character.salary - old_salary,
        )

    if roll > 1.0 - fire_p:
        character.job = None
        character.salary = 0
        character.years_in_role = 0
        character.promotion_count = 0
        return RaiseResult(
            outcome="fired",
            message="You demanded too aggressively. You were let go.",
        )

    return RaiseResult(
        outcome="denied",
        message="You asked for a raise. They turned you down.",
    )


def request_promotion(
    character: Character,
    country: Country,
    rng: random.Random,
) -> RaiseResult:
    """Player-initiated promotion request (#63 split). Outcomes:
    promotion / denied / fired. NO salary-bump path — that's
    :func:`request_salary_raise`.

    Only fires when the character meets the next-rung requirements
    (gated by :func:`can_request_promotion`). On success the character
    actually moves up the ladder.
    """
    eligible, reason = can_request_promotion(character)
    if not eligible:
        return RaiseResult(
            outcome="not_eligible",
            message=reason or "not eligible right now",
        )

    current = get_job(character.job)
    next_job = get_job(current.promotes_to)
    years_required = _years_required_for_promo(character, current)
    years_past = character.years_in_role - years_required
    perf = _performance_score(character, current)
    boldness_penalty = 0.10 if character.attributes.conscience > 70 else 0.0

    promote_p = 0.40 + perf * 0.30 + years_past * 0.05 - boldness_penalty
    fire_p = max(0.01, 0.08 - perf * 0.06)

    character.last_raise_request_age = character.age
    roll = rng.random()

    if roll < promote_p:
        old_salary = character.salary
        promo_count = character.promotion_count or 0
        _set_job(character, country, next_job, rng)
        character.years_in_role = 0
        character.promotion_count = promo_count + 1
        return RaiseResult(
            outcome="promotion",
            message=f"You asked for the role and they gave it to you — you're now a {next_job.name}!",
            salary_delta=character.salary - old_salary,
            new_job=next_job.name,
        )

    if roll > 1.0 - fire_p:
        character.job = None
        character.salary = 0
        character.years_in_role = 0
        character.promotion_count = 0
        return RaiseResult(
            outcome="fired",
            message="You overreached. They let you go instead.",
        )

    return RaiseResult(
        outcome="denied",
        message="You asked for the promotion. They turned you down.",
    )


# Backwards-compat alias used by the existing endpoint name.
def request_raise(
    character: Character,
    country: Country,
    rng: random.Random,
) -> RaiseResult:
    return request_salary_raise(character, country, rng)


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


def _accept_logit(job: Job, character: Character) -> float:
    """Continuous per-requirement logit. Designed to produce a wide
    spread of acceptance probabilities across the catalogue rather than
    the bimodal 80%/30% pattern the old curve produced.

    Each requirement contributes to a logit (log-odds), squashed via a
    sigmoid in :func:`_logit_to_probability` and clamped to [0.03, 0.85]
    so neither end is a sure thing.

    Major contributors:
      - Age in window: +0.4. Out of window: -0.3 per year of slip.
      - Education at floor: +0.5, plus +0.15 per level above (cap +0.45).
        Below floor: -1.0 per level missing — softer than the old -1.8
        so a one-level miss leaves the character in the "stretch" band
        instead of dropping to long_shot.
      - Intelligence above floor: +0.012 per point (cap +0.30). Below:
        -0.04 per point capped at -1.5 — capped so a low-IQ candidate
        applying to an IQ-90 job stays a long shot, not zero.
      - Urban / rural mismatch: -1.6 (down from -2.5). Still steep.
      - Vocation field mismatch: -1.0 (down from -1.5).
      - Salary tier difficulty: -log(salary_mid / 15_000) * 0.65 for
        any job paying more than $15k. High-paying jobs are competitive
        even when the candidate meets every minimum — without this the
        graduate-level character would land in "qualified" for every
        job in the catalogue, including company president.
    """
    logit = -0.2  # baseline ~45% before any modifiers

    # Age
    if character.age < job.min_age:
        logit -= (job.min_age - character.age) * 0.3
    elif character.age > job.max_age:
        logit -= (character.age - job.max_age) * 0.3
    else:
        logit += 0.4

    # Education
    edu_diff = int(character.education) - job.min_education
    if edu_diff < 0:
        logit -= abs(edu_diff) * 1.0
    else:
        logit += 0.5 + min(edu_diff * 0.15, 0.45)

    # Intelligence
    iq_diff = character.attributes.intelligence - job.min_intelligence
    if iq_diff < 0:
        logit -= min(abs(iq_diff) * 0.04, 1.5)
    else:
        logit += min(iq_diff * 0.012, 0.30)

    # Urban / rural mismatch
    if job.urban_only and not character.is_urban:
        logit -= 1.6
    if job.rural_only and character.is_urban:
        logit -= 1.6

    # Vocation field mismatch — career switching is hard but possible
    if character.vocation_field and job.category and job.category != character.vocation_field:
        logit -= 1.0

    # Salary tier — high-paying jobs are competitive even when minimums
    # are met. Without this, the high-skill character lands in
    # "qualified" for everything from beggar to senior gov official.
    salary_mid = (job.salary_low + job.salary_high) / 2.0
    if salary_mid > 15_000:
        logit -= math.log(salary_mid / 15_000) * 0.65

    return logit


def _logit_to_probability(logit: float) -> float:
    """Sigmoid + clamp to [0.03, 0.85]. The cap is intentional — there
    is no such thing as a guaranteed offer, and a 95% ceiling collapsed
    too many "perfect candidate" rows onto the same number."""
    try:
        p = 1.0 / (1.0 + math.exp(-logit))
    except OverflowError:
        p = 0.0 if logit < 0 else 1.0
    return max(0.03, min(0.85, p))


def _status_for_probability(p: float) -> str:
    """Display label binned from the continuous probability.

    The job board hides long_shot + out_of_reach by default; the
    "Show long shots" toggle reveals them. The 40% line on stretch
    is intentional — anything under that is a long shot the player
    has to opt in to seeing.
    """
    if p >= 0.60:
        return "qualified"
    if p >= 0.40:
        return "stretch"
    if p >= 0.10:
        return "long_shot"
    return "out_of_reach"


def _accept_probability(job: Job, character: Character) -> tuple[float, str]:
    """Return (probability, status_label) for a hypothetical application.
    Status is derived from the probability band, not a hard categorical."""
    p = _logit_to_probability(_accept_logit(job, character))
    return p, _status_for_probability(p)


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

    years_required = _years_required_for_promo(character, current)
    if character.years_in_role < years_required:
        return None
    if not _meets_requirements(next_job, character):
        return None

    _set_job(character, country, next_job, rng)
    character.years_in_role = 0

    # Seniority steps don't count as promotions — they're pay/tier
    # bumps within the same role (Teacher II, Officer III, etc.).
    if next_job.is_seniority_step:
        return f"Your seniority advanced — you're now a {next_job.name} (salary ~${character.salary:,}/yr)."
    else:
        character.promotion_count = (character.promotion_count or 0) + 1
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


def can_drop_out_of_school(character: Character, country: Country) -> tuple[bool, str | None]:
    """Whether the player can leave school early to start working (#69).
    Eligible only when the character is currently in school AND has
    reached the country's minimum working age."""
    if not character.in_school:
        return False, "you're not in school"
    floor = minimum_working_age(country)
    if character.age < floor:
        return False, f"can't work yet — minimum working age in {country.name} is {floor}"
    return True, None


def drop_out_of_school(character: Character, country: Country) -> None:
    """Leave school to start working (#69). Sets in_school = False so
    the can_character_work gate clears. Education stays at whatever
    level was already completed.

    Raises ValueError if the character isn't eligible.
    """
    eligible, reason = can_drop_out_of_school(character, country)
    if not eligible:
        raise ValueError(reason or "not eligible")
    character.in_school = False


def yearly_income(character: Character, country: Country, rng: random.Random) -> int:
    """Apply income, expenses, subscription costs, and yearly variance.

    Salaried jobs have tight variance (-5% to +10%): a steady paycheck.
    Freelance jobs (#61) have a much wider luck roll AND scale heavily
    with the relevant attribute — a high-skill freelance artist thrives,
    a low-skill one starves.

    Subscription costs (#66) are deducted after income/expenses so the
    player can have negative net years if they over-subscribe.
    """
    job = get_job(character.job) if character.job else None
    if job is not None and job.is_freelance:
        attr = _relevant_attribute(job.category)
        talent = max(0.4, min(2.5, getattr(character.attributes, attr, 50) / 50.0))
        luck = rng.uniform(0.5, 2.0)
        income = int(character.salary * talent * luck)
    elif character.salary > 0:
        variance = 1.0 + rng.uniform(-0.05, 0.10)
        income = int(character.salary * variance)
    else:
        income = 0

    # #50: spouse income contributes 80% of their salary to the
    # household. The remaining 20% is the spouse's personal expenses.
    # Skipped when the spouse is deceased or has no salary.
    if character.spouse and character.spouse.alive and character.spouse.salary > 0:
        income += int(character.spouse.salary * 0.8)

    # #82: country-scaled baseline cost of living. Children and full-time
    # students live on parental support (engine doesn't model parents
    # explicitly), so they pay nothing. Every other adult — employed,
    # unemployed, retired — pays at least the country baseline. High
    # earners still spend 75% of income via lifestyle inflation; the
    # baseline acts as a floor so a US cashier earning $18k against a
    # $27k baseline genuinely loses money each year. Retirees with $0
    # income drain savings at the baseline rate.
    baseline = finances.baseline_cost_of_living(country)
    is_dependent = character.age < 18 or character.in_school
    if income > 0:
        expenses = max(baseline, int(income * 0.75))
    elif not is_dependent:
        expenses = baseline
    else:
        expenses = 0
    net = income - expenses

    # Subscription costs (#66) — applied even if the character has no
    # job. Living expenses still hit your savings. The per-subscription
    # records are stashed on the character so game.advance_year can
    # surface them as event log entries (#77).
    from . import spending
    sub_cost = spending.yearly_subscription_cost(character)
    if sub_cost:
        net -= sub_cost
        records = spending.apply_subscription_effects(character)
        # Stash for game.advance_year to consume and clear after rendering.
        character._pending_subscription_log = records  # type: ignore[attr-defined]

    character.money += net
    # #70: lifetime earnings tracker for the cross-life statistics
    # archive. Only positive net years count — "money brought in
    # across all working years", not "current net cash position".
    if net > 0:
        character.lifetime_earnings += net
    return net
