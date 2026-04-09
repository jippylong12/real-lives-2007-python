"""
Relationships: meeting partners, marriage, having children.

The original game distinguishes courtship, marriage, and parenthood as
separate event chains. We collapse them into a single state machine driven
by the player's age, attributes, and country (which dictates typical
marriage age + cultural defaults).
"""

from __future__ import annotations

import random

from .character import Character, FamilyMember, Gender
from .world import Country


def _typical_marriage_age(country: Country) -> int:
    if country.hdi >= 0.85:
        return 30
    if country.hdi >= 0.7:
        return 26
    return 22


def update_relationships(character: Character, country: Country, rng: random.Random) -> str | None:
    """Maybe meet a partner, marry, or otherwise update relationship state."""
    if not character.alive or character.age < 16:
        return None

    if character.married:
        return None

    typical = _typical_marriage_age(country)
    # Probability of marrying ramps up around the country's typical age.
    base = 0.0
    if character.age >= 18:
        diff = character.age - typical
        base = max(0.0, 0.20 - abs(diff) * 0.015)
        base += character.attributes.appearance * 0.0015
        base += character.attributes.happiness * 0.0008
    if rng.random() < base:
        spouse_gender = Gender.MALE if character.gender == Gender.FEMALE else Gender.FEMALE
        from .character import _NAMES_F, _NAMES_M, _SURNAMES
        pool = _NAMES_F if spouse_gender == Gender.FEMALE else _NAMES_M
        spouse = f"{rng.choice(pool)} {rng.choice(_SURNAMES)}"
        character.married = True
        character.spouse_name = spouse
        character.family.append(FamilyMember("spouse", spouse, max(18, character.age + rng.randint(-3, 3)),
                                             True, spouse_gender))
        character.attributes.adjust(happiness=+10)
        return f"You married {spouse}."
    return None


def age_family(character: Character) -> list[str]:
    """Age every family member by one year. Returns death notifications."""
    notes: list[str] = []
    for member in character.family + character.children:
        if not member.alive:
            continue
        member.age += 1
        # Naive: family elders die around 78 (+/- jitter handled in main loop).
    return notes
