"""
Relationships: meeting partners, marriage, having children.

The original game distinguishes courtship, marriage, and parenthood as
separate event chains. We collapse them into a single state machine driven
by the player's age, attributes, and country (which dictates typical
marriage age + cultural defaults).

#50: marriage promoted from a flag to a full Spouse dataclass with
attributes, salary, family wealth, and a death roll. The yearly tick
ages the spouse + checks for divorce; the choice events
(LOVE_MARRIAGE, ARRANGED_MARRIAGE) create the spouse via roll_spouse.
"""

from __future__ import annotations

import random

from .character import (
    Attributes,
    Character,
    EducationLevel,
    FamilyMember,
    Gender,
    Spouse,
    _NAMES_F,
    _NAMES_M,
    _SURNAMES,
)
from .world import Country


def _typical_marriage_age(country: Country) -> int:
    if country.hdi >= 0.85:
        return 30
    if country.hdi >= 0.7:
        return 26
    return 22


# All twelve attribute names so roll_spouse can iterate without
# duplicating the list.
_ATTRIBUTE_NAMES = (
    "health", "happiness", "intelligence", "artistic", "musical",
    "athletic", "strength", "endurance", "appearance", "conscience",
    "wisdom", "resistance",
)


def roll_spouse(character: Character, country: Country, year: int, rng: random.Random) -> Spouse:
    """Roll a Spouse with attributes loosely correlated to the
    character's (homophily — people partner with similar people).
    Education and salary scaled to the character's home country (#50).
    """
    spouse_gender = Gender.MALE if character.gender == Gender.FEMALE else Gender.FEMALE
    pool = _NAMES_M if spouse_gender == Gender.MALE else _NAMES_F
    name = f"{rng.choice(pool)} {rng.choice(_SURNAMES)}"

    age = max(18, character.age + rng.randint(-5, 5))

    # Mild homophily: each attribute is the character's value ±15
    # clamped to a sensible range.
    attrs = Attributes()
    for field_name in _ATTRIBUTE_NAMES:
        char_val = getattr(character.attributes, field_name, 50)
        new_val = max(20, min(95, char_val + rng.randint(-15, 15)))
        setattr(attrs, field_name, new_val)

    # Education roughly mirrors the character's, with a 30% chance to
    # drift one level either way.
    education = character.education
    if rng.random() < 0.3:
        new_level = max(0, min(4, int(education) + rng.randint(-1, 1)))
        education = EducationLevel(new_level)

    # Salary scales with country GDP and education level.
    salary_base = int(country.gdp_pc * (0.5 + int(education) * 0.3))
    salary = max(0, int(salary_base * rng.uniform(0.5, 1.5)))
    job = "partner's job" if salary > 0 else None

    # Family wealth: ±50% of the character's current family wealth.
    family_wealth = int(max(0, character.family_wealth) * rng.uniform(0.5, 1.5))

    # Compatibility: weighted by appearance alignment + a small
    # random component. High-appearance pairs trend toward higher
    # compatibility (a deliberate simplification).
    appearance_match = 100 - abs(attrs.appearance - character.attributes.appearance)
    base_compat = 50 + (appearance_match - 50) // 2
    compatibility = max(20, min(95, base_compat + rng.randint(-10, 10)))

    return Spouse(
        name=name,
        gender=spouse_gender,
        age=age,
        attributes=attrs,
        education=education,
        job=job,
        salary=salary,
        family_wealth=family_wealth,
        country_code=character.country_code,
        met_year=year,
        married_year=None,
        compatibility=compatibility,
        alive=True,
    )


def marry(character: Character, spouse: Spouse, year: int) -> None:
    """Formally marry a partner. Sets married_year, applies joined
    wealth, and adds a FamilyMember entry mirroring the legacy
    representation so any code still iterating character.family
    sees the spouse."""
    spouse.married_year = year
    character.spouse = spouse
    character.family_wealth += spouse.family_wealth
    character.attributes.adjust(happiness=+10)
    character.family.append(FamilyMember(
        relation="spouse",
        name=spouse.name,
        age=spouse.age,
        alive=True,
        gender=spouse.gender,
    ))


def update_relationships(character: Character, country: Country, rng: random.Random) -> str | None:
    """Yearly relationship tick. #50: the marriage roll has been
    moved into the choice events (LOVE_MARRIAGE / ARRANGED_MARRIAGE)
    which now create full Spouse instances via roll_spouse. This
    function is kept as a hook for any future passive relationship
    updates."""
    return None


def _spouse_death_check(spouse: Spouse, character: Character, country: Country, rng: random.Random) -> tuple[bool, str | None]:
    """Simple age-based death roll. The full disease engine for
    spouses is a follow-up (#94). For v1, spouses die of 'old age'
    or 'illness' once they push past late middle age."""
    if spouse.age < 60:
        return False, None
    excess = spouse.age - 60
    p = 0.005 + excess * 0.005   # ~30% by age 90
    if rng.random() < p:
        cause = "old age" if spouse.age >= 75 else "illness"
        return True, cause
    return False, None


# #50: baseline yearly chance the marriage ends in divorce. The country
# field (#92) lets the per-year roll match real-world rates: a marriage
# in Portugal (lifetime 0.65) is far more likely to dissolve than one in
# India (lifetime 0.02). Until #92 the rate was a flat HDI heuristic.
DIVORCE_BASE_RATE = 0.005

# A "typical" marriage runs ~30 years before death/divorce, so to map a
# lifetime divorce probability into a per-year roll we divide by an
# expected duration. This is intentionally crude — the goal is to make
# country differences visible, not to model survival curves.
_DIVORCE_EXPECTED_MARRIAGE_YEARS = 30


def divorce_check(character: Character, country: Country, rng: random.Random) -> bool:
    """Yearly probability that the current marriage ends in divorce.

    If the country has a curated `divorce_rate` (#92), the lifetime
    probability is converted into a per-year hazard and then biased by
    the spouse's compatibility — a 25-compat marriage is meaningfully
    more fragile than a 75-compat one even in the same country.

    Without a country value the function falls back to the original
    HDI-based heuristic so countries we haven't curated still divorce
    at a believable rate.
    """
    if not character.spouse or not character.spouse.alive:
        return False
    if character.spouse.married_year is None:
        return False

    incompat = max(0, 100 - character.spouse.compatibility) / 100

    if country.divorce_rate is not None:
        # Approximate per-year hazard from the lifetime probability.
        # 1 - (1 - p_year)^N = lifetime → p_year ≈ lifetime / N for
        # small lifetimes; we use a flat scale since incompat already
        # supplies most of the spread.
        per_year = country.divorce_rate / _DIVORCE_EXPECTED_MARRIAGE_YEARS
        # Compatibility shifts the rate by ±2× across the 0-100 range
        # (centered at 50). Very compatible marriages are roughly 1/3
        # the country baseline; very incompatible ones up to 3×.
        compat_factor = 0.4 + incompat * 2.6
        p = per_year * compat_factor
    else:
        hdi_factor = 0.3 + (country.hdi or 0.5) * 0.7
        p = DIVORCE_BASE_RATE * hdi_factor * (1 + incompat * 2)

    return rng.random() < p


def age_family(character: Character, country: Country | None = None, rng: random.Random | None = None) -> list[str]:
    """Age every family member by one year. Returns notification
    strings the caller can fan out into TurnEvents.

    #50: also ages the spouse and runs the spouse death check.
    Returns 'spouse_died:NAME:CAUSE' for the caller to render.

    #95: when the spouse dies, the marriage is closed out (ended_year
    + end_state='widowed') and the spouse object is moved into
    `character.previous_spouses`. The current `character.spouse` is
    cleared so the character is correctly classified as widowed
    (rather than 'still married to a corpse') and is free to remarry.
    """
    notes: list[str] = []
    for member in character.family + character.children:
        if not member.alive:
            continue
        member.age += 1

    if character.spouse and character.spouse.alive:
        character.spouse.age += 1
        if rng is not None and country is not None:
            died, cause = _spouse_death_check(character.spouse, character, country, rng)
            if died:
                spouse = character.spouse
                spouse.alive = False
                spouse.cause_of_death = cause
                # Use the character's current age as a proxy for the
                # ended_year — the death retrospective shows marriage
                # spans relative to the character's age, not calendar
                # years, so this is the easiest stable handle.
                spouse.ended_year = character.age
                spouse.end_state = "widowed"
                notes.append(f"spouse_died:{spouse.name}:{cause or 'illness'}")
                # Archive the spouse + clear the current slot so the
                # character is now classified as widowed.
                character.previous_spouses.append(spouse)
                character.spouse = None
                # Mirror into the family list so the FamilyMember
                # entry reflects the death too.
                for fm in character.family:
                    if fm.relation == "spouse" and fm.name == spouse.name:
                        fm.alive = False
                        break
    return notes
