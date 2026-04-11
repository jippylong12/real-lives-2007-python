"""
Education progression: primary → secondary → vocational/university.

The original game's education system is gated by the player's country
(literacy %, school enrollment) and intelligence. We replicate the same shape:

  - At age 6, characters in countries with reasonable primary enrollment
    automatically start school.
  - Secondary enrollment depends on intelligence + literacy.
  - University admission requires high intelligence + family wealth or loans.

Each school year is processed by an event in events.py; this module just
decides level progressions and bookkeeping.
"""

from __future__ import annotations

import random

from .character import Character, EducationLevel
from .world import Country


PRIMARY_START_AGE = 6
PRIMARY_END_AGE = 11
SECONDARY_END_AGE = 17
VOCATIONAL_END_AGE = 19   # 2-year program after secondary
UNI_END_AGE = 22          # 4-year program after secondary


def update_education(character: Character, country: Country, rng: random.Random) -> str | None:
    """Advance the character's education state by one year. Returns a summary if anything changed."""
    a = character.age

    # Primary entry
    if a == PRIMARY_START_AGE and character.education == EducationLevel.NONE:
        if country.literacy > 30 or rng.random() < 0.5:
            character.in_school = True
            character.school_track = "primary"
            return f"You started primary school in {character.city}."

    # Primary completion
    if a == PRIMARY_END_AGE + 1 and character.education == EducationLevel.NONE and character.in_school:
        character.education = EducationLevel.PRIMARY
        # Continue to secondary?
        gate = country.literacy / 200 + character.attributes.intelligence / 200
        if rng.random() < gate:
            character.school_track = "secondary"
            return "You completed primary school and continued to secondary school."
        character.in_school = False
        character.school_track = None
        return "You completed primary school. You did not continue your education."

    # Secondary completion — branch into university, vocational, or workforce.
    # Important: vocational and university are multi-year programs, so we
    # KEEP in_school=True and only flip school_track. The credential
    # (VOCATIONAL / UNIVERSITY) is granted on completion, NOT on entry —
    # mirrors how university already works.
    #
    # This is a fallback path. The normal flow goes through the
    # EDUCATION_PATH choice event in events.py which fires at age 17,
    # bumps education to SECONDARY immediately, and sets school_track
    # to "vocational" or "university" — which makes the education
    # gate here false so this branch is a no-op for those characters.
    # The school_track guard is belt-and-suspenders: even if some
    # other path leaves the character at education=PRIMARY but
    # already-tracked, don't clobber the user's choice.
    if (a == SECONDARY_END_AGE + 1
            and character.education == EducationLevel.PRIMARY
            and character.in_school
            and character.school_track not in ("vocational", "university")):
        character.education = EducationLevel.SECONDARY
        intel = character.attributes.intelligence
        wealth = character.money + character.family_wealth
        if intel >= 60 and (wealth > country.gdp_pc * 1.5 or country.hdi > 0.85):
            character.school_track = "university"
            return "You graduated from secondary school and were accepted to university!"
        if intel >= 50 and rng.random() < 0.4:
            character.school_track = "vocational"
            return "You finished secondary school and entered a 2-year vocational program."
        character.in_school = False
        character.school_track = None
        return "You finished secondary school and joined the workforce."

    # Vocational completion (#82-followup, #83-followup). Two paths
    # land here: the events.py EDUCATION_PATH "vocational" choice
    # (most common — fires at age 17) and the automatic age-18
    # secondary completion branch above. Both set school_track and
    # leave education at PRIMARY/SECONDARY; this branch grants the
    # credential AND places the player in a starter trade job in
    # their chosen vocation_field — the actual payoff for completing
    # vocational school. Without this, picking 'vocational → trades →
    # electrician' was a no-op the player had to follow up with
    # manual job hunting.
    if (a == VOCATIONAL_END_AGE + 1
            and character.in_school
            and character.school_track == "vocational"):
        character.education = EducationLevel.VOCATIONAL
        character.in_school = False
        character.school_track = None
        return _graduate_into_starter_job(
            character, country, rng,
            base="You graduated from vocational school",
        )

    # University completion. Backwards-compat: pre-fix saves don't have
    # school_track set, so treat None as "in university" since the old
    # secondary-completion branch only set in_school for the university
    # path (vocational immediately set in_school=False in the buggy code).
    # Same payoff path as vocational — graduate into a starter job in
    # the chosen field.
    #
    # #107: late enrollees have a _uni_graduation_age that overrides
    # the standard UNI_END_AGE (22). This lets adults who enroll later
    # graduate after 4 years from their enrollment age.
    grad_age = character.uni_graduation_age or UNI_END_AGE
    if (a == grad_age
            and character.in_school
            and character.school_track in ("university", None)
            and character.education in (EducationLevel.SECONDARY, EducationLevel.VOCATIONAL)):
        character.education = EducationLevel.UNIVERSITY
        character.in_school = False
        character.school_track = None
        # Clean up the late-enrollment marker.
        character.uni_graduation_age = None
        return _graduate_into_starter_job(
            character, country, rng,
            base="You graduated from university",
        )

    return None


# #108: tuition rates as a fraction of the country's GDP per capita.
# Primary is free in most of the world. Secondary has modest fees.
# Vocational and university are the expensive ones.
TUITION_RATES: dict[str, float] = {
    "primary": 0.0,       # free
    "secondary": 0.03,    # ~3% of GDP/capita
    "vocational": 0.08,   # ~8% of GDP/capita
    "university": 0.20,   # ~20% of GDP/capita
}


def yearly_tuition(character: Character, country: Country) -> int:
    """Return the tuition cost for this year of school. Zero if not in school.
    Scaled by the country's GDP per capita so education costs are
    realistic relative to the local economy (#108)."""
    if not character.in_school or not character.school_track:
        return 0
    rate = TUITION_RATES.get(character.school_track, 0.0)
    return int(country.gdp_pc * rate)


# #107: late university enrollment constants.
LATE_ENROLL_MIN_AGE = 18
LATE_ENROLL_MAX_AGE = 55
LATE_UNI_DURATION = 4  # years


def can_enroll_university(character: Character, country: Country) -> tuple[bool, str]:
    """Check whether the character can enroll in university later in life.
    Returns (eligible, reason)."""
    if character.in_school:
        return False, "Already in school."
    if character.education >= EducationLevel.UNIVERSITY:
        return False, "Already have a university degree."
    if character.education < EducationLevel.SECONDARY:
        return False, "Need at least a secondary education."
    if character.age < LATE_ENROLL_MIN_AGE:
        return False, "Too young — must be at least 18."
    if character.age > LATE_ENROLL_MAX_AGE:
        return False, "Too old to enroll."
    tuition = int(country.gdp_pc * TUITION_RATES["university"])
    if character.money < tuition:
        return False, f"Can't afford tuition (${tuition:,})."
    return True, ""


def enroll_university(character: Character, country: Country) -> str:
    """Enroll the character in university later in life (#107).
    Deducts the first year of tuition and sets up the school state.
    The character will graduate after LATE_UNI_DURATION years via the
    normal graduation path, keyed off their enrollment age."""
    ok, reason = can_enroll_university(character, country)
    if not ok:
        raise ValueError(reason)
    tuition = int(country.gdp_pc * TUITION_RATES["university"])
    character.money -= tuition
    character.in_school = True
    character.school_track = "university"
    # Set education to SECONDARY so the graduation check at UNI_END_AGE
    # equivalent fires. We store the target graduation age on the
    # character so update_education can detect late enrollees.
    if character.education == EducationLevel.VOCATIONAL:
        # Keep vocational — university upgrades from it.
        pass
    character.uni_graduation_age = character.age + LATE_UNI_DURATION
    # Clear vocation field so the UNIVERSITY_MAJOR choice event fires
    # and the player can pick a new major for their university degree.
    character.vocation_field = None
    # If they already had a job, they keep it (part-time / night school).
    return (
        f"You enrolled in university! Tuition: ${tuition:,}/yr. "
        f"You'll graduate at age {character.uni_graduation_age}."
    )


def _graduate_into_starter_job(character: Character, country: Country, rng: random.Random, base: str) -> str:
    """Return graduation message. The character joins the workforce but
    does NOT get auto-assigned a job (#109). The frontend detects
    education_completed in the TurnResult and auto-opens the job board
    so the player can choose their own first job.
    """
    if character.vocation_field:
        return f"{base} with a focus in {character.vocation_field}. Time to find a job!"
    return f"{base}. Time to find a job!"
