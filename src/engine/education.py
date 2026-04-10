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
    if a == SECONDARY_END_AGE + 1 and character.education == EducationLevel.PRIMARY and character.in_school:
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

    # Vocational completion (#82-followup): 2 years after secondary ends.
    if (a == VOCATIONAL_END_AGE + 1
            and character.education == EducationLevel.SECONDARY
            and character.in_school
            and character.school_track == "vocational"):
        character.education = EducationLevel.VOCATIONAL
        character.in_school = False
        character.school_track = None
        return "You graduated from vocational school and joined the workforce."

    # University completion. Backwards-compat: pre-fix saves don't have
    # school_track set, so treat None as "in university" since the old
    # secondary-completion branch only set in_school for the university
    # path (vocational immediately set in_school=False in the buggy code).
    if (a == UNI_END_AGE
            and character.education == EducationLevel.SECONDARY
            and character.in_school
            and character.school_track in ("university", None)):
        character.education = EducationLevel.UNIVERSITY
        character.in_school = False
        character.school_track = None
        return "You graduated from university!"

    return None
