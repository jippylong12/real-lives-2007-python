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
UNI_END_AGE = 22


def update_education(character: Character, country: Country, rng: random.Random) -> str | None:
    """Advance the character's education state by one year. Returns a summary if anything changed."""
    a = character.age

    # Primary entry
    if a == PRIMARY_START_AGE and character.education == EducationLevel.NONE:
        if country.literacy > 30 or rng.random() < 0.5:
            character.in_school = True
            return f"You started primary school in {character.city}."

    # Primary completion
    if a == PRIMARY_END_AGE + 1 and character.education == EducationLevel.NONE and character.in_school:
        character.education = EducationLevel.PRIMARY
        # Continue to secondary?
        gate = country.literacy / 200 + character.attributes.intelligence / 200
        if rng.random() < gate:
            return "You completed primary school and continued to secondary school."
        character.in_school = False
        return "You completed primary school. You did not continue your education."

    # Secondary completion
    if a == SECONDARY_END_AGE + 1 and character.education == EducationLevel.PRIMARY and character.in_school:
        character.education = EducationLevel.SECONDARY
        intel = character.attributes.intelligence
        wealth = character.money + character.family_wealth
        if intel >= 60 and (wealth > country.gdp_pc * 1.5 or country.hdi > 0.85):
            return "You graduated from secondary school and were accepted to university!"
        if intel >= 50 and rng.random() < 0.4:
            character.education = EducationLevel.VOCATIONAL
            character.in_school = False
            return "You finished secondary school and entered a vocational program."
        character.in_school = False
        return "You finished secondary school and joined the workforce."

    # University completion
    if a == UNI_END_AGE and character.education == EducationLevel.SECONDARY and character.in_school:
        character.education = EducationLevel.UNIVERSITY
        character.in_school = False
        return "You graduated from university!"

    return None
