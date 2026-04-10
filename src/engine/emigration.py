"""
Emigration: move a character from their current country to a target
country mid-life (#49).

Eligibility is gated by visa-style routes that mirror real-world
immigration paths:

  - skilled_worker  — university + IQ 60+ → high-HDI countries
  - refugee         — source country at war → target accepts (HDI ≥ 0.7)
  - investor        — family wealth ≥ 50× target gdp_pc
  - marriage        — spouse from the target country (cross-border)
  - language_match  — shared primary language → easier route via diaspora
  - descent         — previously lived in the target country (citizenship by descent)

The actual move clears country-specific state (job, salary,
years_in_role), re-rolls city + is_urban in the target country, moves
the spouse along, deducts a relocation cost, and writes a timeline
entry. The next yearly tick automatically uses the new country for
cost-of-living, event rolls, and disease frequencies.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .character import Character, EducationLevel
from .world import Country, all_countries, cities_for, get_country

if TYPE_CHECKING:
    pass


# #98: Minimum number of years between emigrations regardless of route.
# Real visas take time to process and migrant lives take time to settle —
# without this gate a player could bounce between countries every year
# via the descent route once they had any travel history.
EMIGRATION_COOLDOWN_YEARS = 5


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmigrationResult:
    outcome: str                    # 'emigrated' | 'not_eligible'
    message: str
    new_city: str | None = None
    new_country_code: str | None = None
    cost: int = 0
    routes: tuple[str, ...] = ()


# Visa route metadata for the picker UI.
ROUTE_LABELS: dict[str, str] = {
    "skilled_worker": "Skilled worker",
    "refugee":        "Refugee",
    "investor":       "Investor",
    "marriage":       "Marriage",
    "language_match": "Language / diaspora",
    "descent":        "Citizenship by descent",
}


# ---------------------------------------------------------------------------
# Visa qualifiers
# ---------------------------------------------------------------------------

def _qualifies_skilled_worker(char: Character, src: Country, tgt: Country) -> bool:
    """High-HDI countries accept skilled workers with university +
    decent intelligence."""
    return (
        int(char.education) >= int(EducationLevel.UNIVERSITY)
        and char.attributes.intelligence >= 60
        and tgt.hdi >= 0.75
    )


def _qualifies_refugee(char: Character, src: Country, tgt: Country) -> bool:
    """Source country at war + target country accepts refugees
    (HDI ≥ 0.7 as a stand-in for 'has the infrastructure to take
    refugees')."""
    return src.at_war == 1 and tgt.hdi >= 0.7


def _qualifies_investor(char: Character, src: Country, tgt: Country) -> bool:
    """Wealthy enough to buy in: family wealth ≥ 50× target gdp_pc."""
    return char.family_wealth >= tgt.gdp_pc * 50


def _qualifies_marriage(char: Character, src: Country, tgt: Country) -> bool:
    """Spouse already lives in the target country (cross-border
    marriage). At marriage time the spouse inherits the player's
    country, so this route only fires for previously-emigrated
    characters whose pre-emigration spouse is still attached."""
    return (
        char.spouse is not None
        and char.spouse.alive
        and char.spouse.country_code == tgt.code
    )


def _qualifies_language_match(char: Character, src: Country, tgt: Country) -> bool:
    """Shared primary language + reasonably accessible target. Acts
    as a 'diaspora / community' route since shared language usually
    implies community ties."""
    return (
        src.primary_language == tgt.primary_language
        and tgt.hdi >= 0.6
        and src.code != tgt.code
    )


def _qualifies_descent(char: Character, src: Country, tgt: Country) -> bool:
    """Citizenship by descent: target appears in previous_countries.
    Lets a player who emigrated US → DE → JP move back to US or DE
    without re-qualifying for skilled worker / refugee."""
    return tgt.code in (char.previous_countries or [])


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------

def is_eligible_to_emigrate(
    char: Character, src: Country, tgt: Country
) -> tuple[bool, list[str], str | None]:
    """Returns (eligible, matched_route_keys, blocked_reason)."""
    if src.code == tgt.code:
        return False, [], "you already live there"
    if char.age < 16:
        return False, [], "too young to emigrate independently"

    # #98: cooldown gate. A character who recently emigrated can't move
    # again until at least EMIGRATION_COOLDOWN_YEARS have passed.
    if char.last_emigration_age is not None:
        years_since = char.age - char.last_emigration_age
        if years_since < EMIGRATION_COOLDOWN_YEARS:
            wait = EMIGRATION_COOLDOWN_YEARS - years_since
            return False, [], (
                f"you only just settled — wait {wait} more year(s) before moving again"
            )

    routes: list[str] = []
    if _qualifies_skilled_worker(char, src, tgt):
        routes.append("skilled_worker")
    if _qualifies_refugee(char, src, tgt):
        routes.append("refugee")
    if _qualifies_investor(char, src, tgt):
        routes.append("investor")
    if _qualifies_marriage(char, src, tgt):
        routes.append("marriage")
    if _qualifies_language_match(char, src, tgt):
        routes.append("language_match")
    if _qualifies_descent(char, src, tgt):
        routes.append("descent")

    if not routes:
        # Build a tailored block reason listing the easiest unmet path.
        if tgt.hdi >= 0.75:
            return False, [], (
                f"requires university + IQ 60+ (skilled worker) "
                f"or family wealth ≥ ${tgt.gdp_pc * 50:,} (investor)"
            )
        return False, [], f"no qualifying visa route to {tgt.name}"
    return True, routes, None


# ---------------------------------------------------------------------------
# The move
# ---------------------------------------------------------------------------

def emigration_cost(char: Character) -> int:
    """Visa fees + relocation. ~20% of family wealth, minimum $500."""
    return max(500, int(max(0, char.family_wealth) * 0.20))


def pick_emigration_city(target: Country, rng: random.Random) -> tuple[str, bool]:
    """Pick an arrival city for an emigrant (#100).

    Migrants cluster in 'magnet cities' — well-known immigrant hubs —
    at much higher rates than the general population. The curated
    ``MIGRATION_MAGNETS`` table in seed.py lists those hubs per
    target country.

    The pick is heavily weighted toward magnet cities (10× the base
    rank weight) but still allows the occasional non-magnet landing
    so a player isn't always handed the same destination. Migrants
    also land urban much more often than the country's general
    population because the visa logistics + jobs that anchor
    migration are concentrated in cities.
    """
    from ..data.seed import MIGRATION_MAGNETS

    cities = cities_for(target.code)
    if not cities:
        return target.capital, True

    magnets_lower = {n.lower() for n in MIGRATION_MAGNETS.get(target.code, ())}
    if magnets_lower:
        weights = [
            (10.0 / c.rank if c.name.lower() in magnets_lower else 0.4 / c.rank)
            for c in cities
        ]
    else:
        # No curated list for this country — fall back to the same
        # rank-weighting that pick_birth_city uses.
        weights = [1.0 / c.rank for c in cities]

    chosen = rng.choices(cities, weights=weights, k=1)[0]
    # Migrants land in actual cities ~90% of the time regardless of the
    # target country's overall urban_pct — visa sponsors and jobs are
    # almost never in remote villages.
    is_urban = rng.random() < 0.90
    if is_urban:
        return chosen.name, True
    return f"a village near {chosen.name}", False


def emigrate(
    char: Character, target_country: Country, year: int, rng: random.Random
) -> EmigrationResult:
    """Move the character from their current country to ``target_country``.
    Validates the visa gate, deducts relocation cost, clears
    country-specific state, picks a new city, and moves the spouse."""
    src = get_country(char.country_code)
    if src is None:
        return EmigrationResult("not_eligible", "current country unknown")

    eligible, routes, reason = is_eligible_to_emigrate(char, src, target_country)
    if not eligible:
        return EmigrationResult("not_eligible", reason or "not eligible")

    cost = emigration_cost(char)
    if char.family_wealth < cost:
        return EmigrationResult(
            "not_eligible",
            f"can't afford the move (~${cost:,} needed, you have ${char.family_wealth:,})",
        )

    char.family_wealth -= cost

    # Track the previous country before switching.
    if char.country_code not in char.previous_countries:
        char.previous_countries.append(char.country_code)

    # Pick a new city in the target country, weighted toward known
    # diaspora hubs for that country (#100).
    new_city, new_is_urban = pick_emigration_city(target_country, rng)

    # Update character state.
    char.country_code = target_country.code
    char.city = new_city
    char.is_urban = new_is_urban
    # Country-specific job state cleared. Promotion count preserved
    # (inherent talent follows you across borders).
    char.job = None
    char.salary = 0
    char.years_in_role = 0
    # #98: stamp the cooldown.
    char.last_emigration_age = char.age

    # Spouse (if any) moves with you. Their country is updated and
    # their job/salary cleared so they re-roll their working life in
    # the new country. is_urban is re-synced from the player so the
    # disease engine's urban_skew applies symmetrically (#94).
    if char.spouse and char.spouse.alive:
        char.spouse.country_code = target_country.code
        char.spouse.job = None
        char.spouse.salary = 0
        char.spouse.is_urban = char.is_urban

    # Cultural displacement happiness hit, tempered by language match.
    happiness_hit = -10
    if src.primary_language == target_country.primary_language:
        happiness_hit = -4   # easier transition
    char.attributes.adjust(happiness=happiness_hit, wisdom=+2)

    route_label = ROUTE_LABELS.get(routes[0], routes[0])
    msg = (
        f"Emigrated from {src.name} to {target_country.name} "
        f"on a {route_label} visa. Settled in {new_city}."
    )

    # #101: skilled-worker route auto-assigns a starter job in the
    # player's existing vocation field. Skilled migrants were admitted
    # *because* of their skills — making them re-roll Find Work after
    # arrival breaks the fiction. Refugee/family/marriage routes still
    # start from scratch (their visa wasn't conditional on a job offer).
    if "skilled_worker" in routes and char.vocation_field:
        # Local import — careers.py imports from world.py so we keep
        # the symbol lazily-loaded to avoid an import cycle.
        from .careers import assign_job
        job_msg = assign_job(char, target_country, rng)
        if job_msg and char.job:
            msg += f" Started fresh as a {char.job} on the skilled-worker visa."

    char.remember(msg)

    return EmigrationResult(
        outcome="emigrated",
        message=msg,
        new_city=new_city,
        new_country_code=target_country.code,
        cost=cost,
        routes=tuple(routes),
    )


# ---------------------------------------------------------------------------
# Picker helper
# ---------------------------------------------------------------------------

def list_emigration_options(char: Character) -> list[dict]:
    """Return one entry per country with the player's eligibility +
    blocking reason. Used by the picker UI to show green/grey tiles."""
    src = get_country(char.country_code)
    if src is None:
        return []
    cost_estimate = emigration_cost(char)
    out: list[dict] = []
    for tgt in all_countries():
        if tgt.code == src.code:
            continue
        eligible, routes, reason = is_eligible_to_emigrate(char, src, tgt)
        out.append({
            "code": tgt.code,
            "name": tgt.name,
            "region": tgt.region,
            "hdi": tgt.hdi,
            "gdp_pc": tgt.gdp_pc,
            "primary_language": tgt.primary_language,
            "eligible": eligible,
            "routes": routes,
            "blocked_reason": reason,
            "estimated_cost": cost_estimate,
        })
    return out
