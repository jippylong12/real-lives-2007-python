"""
Active healthcare actions: spend money to recover from health issues (#67).

Before v1.3, the engine had no way for a wealthy character to use their
money to fix bad health. A character with $1M and health=20 had the
same recovery rate as a poor character — wait it out and hope. This
module adds player-initiated medical actions:

- **General checkup**: small one-shot recovery, low cost, yearly cooldown
- **Major treatment**: bigger recovery for severely impaired characters,
  high cost, multi-year cooldown
- **Disease treatment**: pay to cure (or manage) a specific named disease
  in ``character.diseases``

Restrictions
------------
The user explicitly called out the cases where money should NOT solve
the problem:

- **Old age decay**: characters past 75 see diminishing returns; past
  90 it barely works at all (a multiplier of ``min(1.0, max(0.2,
  (90 - age) / 30))``).
- **Terminal lethality**: a disease's :attr:`Disease.lethality` reflects
  per-year death roll. Treatment doesn't suppress that — if your
  pancreatic cancer kills you this year, no amount of money saves you.
- **Permanent conditions**: paralysis (polio), river blindness, and
  similar can be *managed* (status flips from active → inactive) but
  the disease record stays on the character forever.
- **Country gates**: in low-HDI countries with poor health services
  the treatments are still purchasable but a country effectiveness
  scalar reduces their impact.
"""

from __future__ import annotations

from dataclasses import dataclass

from .character import Character
from .diseases import DISEASES, Disease
from .world import Country


@dataclass
class TreatmentResult:
    success: bool
    message: str
    cost: int = 0
    health_delta: int = 0


# Cooldowns in years between repeat treatments of the same kind.
_COOLDOWN_CHECKUP = 1
_COOLDOWN_MAJOR = 3


def _country_scale(country: Country) -> float:
    """Cost scalar — same shape as the careers / spending modules."""
    return max(0.05, country.gdp_pc / 50000)


def _age_multiplier(age: int) -> float:
    """How effective treatment is at the character's age. Linear ramp:
    1.0 at age <= 60, falling to 0.2 by age 90, floored at 0.2."""
    if age <= 60:
        return 1.0
    if age >= 90:
        return 0.2
    return max(0.2, (90 - age) / 30)


def _country_effectiveness(country: Country) -> float:
    """How well the local healthcare system delivers the treatment.
    100% services → full effect; 30% services → 30% effect."""
    return max(0.3, country.health_services_pct / 100)


def _on_cooldown(character: Character, kind: str, cooldown_years: int) -> int | None:
    """Returns remaining years if on cooldown, None otherwise."""
    last = character.last_treatment.get(kind)
    if last is None:
        return None
    gap = character.age - last
    if gap >= cooldown_years:
        return None
    return cooldown_years - gap


# ---------------------------------------------------------------------------
# Eligibility helpers
# ---------------------------------------------------------------------------


def can_buy_checkup(character: Character) -> tuple[bool, str | None]:
    if character.attributes.health >= 90:
        return False, "you're already healthy enough to skip a checkup"
    remaining = _on_cooldown(character, "checkup", _COOLDOWN_CHECKUP)
    if remaining:
        return False, f"already had a checkup this year"
    return True, None


def can_buy_major_treatment(character: Character) -> tuple[bool, str | None]:
    if character.attributes.health >= 60:
        return False, "you're not impaired enough for major treatment"
    remaining = _on_cooldown(character, "major", _COOLDOWN_MAJOR)
    if remaining:
        return False, f"too soon — wait {remaining} year(s)"
    return True, None


def treatable_diseases(character: Character) -> list[Disease]:
    """Diseases on the character's record that can be paid to cure or
    manage. Skips diseases already inactive (already treated) and
    diseases that aren't medically treatable in the registry."""
    out = []
    for key, state in character.diseases.items():
        d = next((dd for dd in DISEASES if dd.key == key), None)
        if d is None or not d.treatable:
            continue
        if not state.get("active"):
            continue
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def buy_checkup(character: Character, country: Country) -> TreatmentResult:
    """Pay for a general checkup. Recovers some health based on age +
    country effectiveness. Yearly cooldown."""
    eligible, reason = can_buy_checkup(character)
    if not eligible:
        return TreatmentResult(False, reason or "not eligible")

    cost = max(50, int(2_000 * _country_scale(country)))
    if character.money < cost:
        return TreatmentResult(False, f"not enough cash (need ${cost:,})")

    age_mult = _age_multiplier(character.age)
    country_mult = _country_effectiveness(country)
    base_recovery = 8
    recovery = max(1, int(base_recovery * age_mult * country_mult))

    character.money -= cost
    character.attributes.adjust(health=recovery)
    character.last_treatment["checkup"] = character.age

    return TreatmentResult(
        True,
        f"You paid ${cost:,} for a checkup and recovered {recovery} health.",
        cost=cost,
        health_delta=recovery,
    )


def buy_major_treatment(character: Character, country: Country) -> TreatmentResult:
    """Pay for major treatment — only available when health < 60.
    Larger one-shot recovery; 3-year cooldown."""
    eligible, reason = can_buy_major_treatment(character)
    if not eligible:
        return TreatmentResult(False, reason or "not eligible")

    cost = max(500, int(15_000 * _country_scale(country)))
    if character.money < cost:
        return TreatmentResult(False, f"not enough cash (need ${cost:,})")

    age_mult = _age_multiplier(character.age)
    country_mult = _country_effectiveness(country)
    base_recovery = 22
    recovery = max(2, int(base_recovery * age_mult * country_mult))

    character.money -= cost
    character.attributes.adjust(health=recovery)
    character.last_treatment["major"] = character.age

    return TreatmentResult(
        True,
        f"You paid ${cost:,} for major treatment and recovered {recovery} health.",
        cost=cost,
        health_delta=recovery,
    )


def treat_disease(character: Character, country: Country, disease_key: str) -> TreatmentResult:
    """Pay to cure (or manage) a specific named disease. Permanent
    conditions get *managed* (active → inactive) but stay on the
    record. Non-permanent treatable diseases get cured outright."""
    state = character.diseases.get(disease_key)
    if state is None:
        return TreatmentResult(False, f"you don't have {disease_key}")
    if not state.get("active"):
        return TreatmentResult(False, "that condition is already managed")

    d = next((dd for dd in DISEASES if dd.key == disease_key), None)
    if d is None:
        return TreatmentResult(False, "unknown disease")
    if not d.treatable:
        return TreatmentResult(False, f"{d.name} can't be treated this way")

    cost = max(100, int(d.treatment_cost * _country_scale(country)))
    if character.money < cost:
        return TreatmentResult(False, f"not enough cash (need ${cost:,})")

    country_mult = _country_effectiveness(country)
    if country_mult < 0.5 and d.treatment_cost >= 5000:
        # Severe-disease, poor-healthcare double penalty: the procedure
        # exists but the local clinic can't deliver it.
        return TreatmentResult(
            False,
            f"local healthcare can't deliver advanced treatment for {d.name}",
        )

    character.money -= cost
    state["active"] = False
    state["age_managed"] = character.age
    state["treated"] = True

    if d.permanent:
        character.attributes.adjust(health=+5)
        msg = f"You paid ${cost:,} to manage your {d.name}. It's still on your record but it won't fight you anymore."
    else:
        character.attributes.adjust(health=+8)
        msg = f"You paid ${cost:,} for {d.name} treatment. Cured."

    return TreatmentResult(True, msg, cost=cost)
