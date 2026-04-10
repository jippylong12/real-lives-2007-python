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
    sees the spouse.

    #94: also syncs ``is_urban`` from the host so the disease engine's
    urban_skew modifier works on the spouse the same as on the player.
    """
    spouse.married_year = year
    spouse.is_urban = character.is_urban
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
    """Age-based death roll for spouses. Used as a fallback after the
    full disease engine has had its chance — spouses still die of "old
    age" once they push past late middle age even when no terminal
    disease has caught up to them."""
    if spouse.age < 60:
        return False, None
    excess = spouse.age - 60
    p = 0.005 + excess * 0.005   # ~30% by age 90
    if rng.random() < p:
        cause = "old age" if spouse.age >= 75 else "illness"
        return True, cause
    return False, None


def _roll_spouse_diseases(spouse: Spouse, country: Country, rng: random.Random) -> str | None:
    """#94: run the full disease engine on the spouse and return the
    name of any terminal disease that fired this year (the caller
    surfaces it as the cause of death). Spouses get the same
    treatment gate as the player — good local services + family
    wealth covers the cost — so a wealthy widow doesn't lose her
    husband to easily-treatable hypertension.

    Returns the disease name if a terminal disease killed the spouse
    this year, or None if the spouse survived (or contracted nothing
    at all).
    """
    from . import diseases as diseases_mod
    new_diseases = diseases_mod.roll_diseases(spouse, country, rng)
    can_treat_baseline = country.health_services_pct >= 60
    for d in new_diseases:
        treatable = (
            d.treatable
            and can_treat_baseline
            and spouse.family_wealth + spouse.salary >= d.treatment_cost
        )
        spouse.diseases[d.key] = {
            "name": d.name,
            "category": d.category,
            "active": not (treatable and not d.permanent),
            "age_acquired": spouse.age,
            "permanent": d.permanent,
            "treated": treatable,
        }
        if treatable and d.treatment_cost > 0:
            # Drain shared family wealth — keeping it simple by going
            # straight to family_wealth instead of mirroring the
            # player's money/family_wealth split.
            spouse.family_wealth = max(0, spouse.family_wealth - d.treatment_cost)
    # Yearly mortality lottery against every active terminal disease.
    for key, data in spouse.diseases.items():
        if not data.get("active"):
            continue
        d = next((x for x in diseases_mod.DISEASES if x.key == key), None)
        if d is None:
            continue
        lethality = d.lethality
        if data.get("treated"):
            lethality *= 0.3   # treated chronic conditions are far less lethal
        if lethality > 0 and rng.random() < lethality:
            return d.name
    return None


# #96: relationship strain. The yearly tick adds a small amount of
# strain proportional to (100 - compatibility) so a low-compat marriage
# accumulates pressure faster than a high-compat one. Once strain
# crosses _STRAIN_DIVORCE_THRESHOLD the DIVORCE_CONSIDERATION choice
# event becomes eligible.
_STRAIN_BASE_PER_YEAR = 1
_STRAIN_INCOMPAT_MULTIPLIER = 0.20    # at compat=0 → +20/yr; at compat=100 → +1/yr
_STRAIN_DIVORCE_THRESHOLD = 50
_STRAIN_MAX = 100


def update_strain(character: Character) -> None:
    """Tick relationship strain by one year. Called from the yearly
    update loop. No-op when there's no current marriage."""
    if not character.spouse or not character.spouse.alive:
        return
    if character.spouse.married_year is None:
        return
    incompat = max(0, 100 - character.spouse.compatibility)
    delta = _STRAIN_BASE_PER_YEAR + int(incompat * _STRAIN_INCOMPAT_MULTIPLIER)
    character.spouse.relationship_strain = min(
        _STRAIN_MAX,
        character.spouse.relationship_strain + delta,
    )


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
    """Yearly probability that the current marriage ends in a silent
    automatic divorce.

    #96: divorce is now strain-gated. The player's main path to
    divorce is the DIVORCE_CONSIDERATION choice event which fires
    when relationship_strain crosses the threshold. This silent
    fallback only fires when strain has built up further (well past
    the choice threshold), modeling players who keep ignoring the
    DIVORCE_CONSIDERATION event letting the marriage decay until it
    falls apart on its own.

    Country `divorce_rate` (#92) and spouse compatibility still bias
    the per-year hazard; without a country value the function falls
    back to the HDI heuristic.
    """
    if not character.spouse or not character.spouse.alive:
        return False
    if character.spouse.married_year is None:
        return False

    # #96: strain gate. Healthy marriages with strain at 0 cannot
    # silently divorce; pressure must build first via update_strain
    # in the yearly tick OR via the DIVORCE_CONSIDERATION event being
    # ignored repeatedly.
    strain = character.spouse.relationship_strain
    if strain < _STRAIN_DIVORCE_THRESHOLD:
        return False

    incompat = max(0, 100 - character.spouse.compatibility) / 100
    strain_factor = (strain - _STRAIN_DIVORCE_THRESHOLD) / max(
        1, _STRAIN_MAX - _STRAIN_DIVORCE_THRESHOLD
    )

    if country.divorce_rate is not None:
        per_year = country.divorce_rate / _DIVORCE_EXPECTED_MARRIAGE_YEARS
        compat_factor = 0.4 + incompat * 2.6
        p = per_year * compat_factor * (0.5 + strain_factor * 1.5)
    else:
        hdi_factor = 0.3 + (country.hdi or 0.5) * 0.7
        p = DIVORCE_BASE_RATE * hdi_factor * (1 + incompat * 2) * (0.5 + strain_factor * 1.5)

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
            # #94: full disease engine roll on the spouse. Returns the
            # name of any terminal disease that fired this year.
            disease_cause = _roll_spouse_diseases(character.spouse, country, rng)
            if disease_cause is not None:
                died, cause = True, disease_cause
            else:
                # Fall back to age-based mortality.
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
