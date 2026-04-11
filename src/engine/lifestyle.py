"""
Lifestyle tiers system (#113).

A character's lifestyle tier represents their overall standard of living,
computed from their spending patterns relative to their country's economy.
Tiers range from Destitute (0) to Luxurious (6) and affect happiness,
health recovery, and general life quality each year.

Tier computation
----------------
The tier is NOT a manual toggle — it's derived from how the character
actually spends money. The key inputs are:

- Annual spending rate: subscription costs + recent purchase spending
- Net worth: money + portfolio - debt + family_wealth
- Country GDP per capita as a baseline for "normal" spending

The system looks at what fraction of the country's GDP per capita the
character's lifestyle spending represents, combined with their overall
wealth position, to place them on the 0-6 scale.

Effects
-------
Each tier applies small yearly adjustments:
- **Happiness drift**: lower tiers pull happiness down, higher tiers
  push it up slightly. The effect is gentle — a poor character isn't
  automatically miserable, but money stress erodes happiness over time.
- **Health modifier**: extreme poverty reduces health (poor nutrition,
  worse housing); affluence provides a small health buffer.
- **The sweet spot**: Comfortable (3) is neutral. Below it, life is
  harder. Above it, returns diminish — going from Affluent to Luxurious
  barely moves the needle, matching real-world happiness research.
"""

from __future__ import annotations

from dataclasses import dataclass

from .character import Character
from .spending import yearly_subscription_cost
from .finances import portfolio_value
from .world import Country


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LifestyleTier:
    level: int
    name: str
    description: str
    happiness_drift: int    # yearly happiness adjustment
    health_drift: int       # yearly health adjustment


TIERS: list[LifestyleTier] = [
    LifestyleTier(0, "Destitute",
                  "Struggling to meet basic needs. Every day is survival.",
                  happiness_drift=-3, health_drift=-2),
    LifestyleTier(1, "Poor",
                  "Getting by, but barely. Constant financial stress.",
                  happiness_drift=-2, health_drift=-1),
    LifestyleTier(2, "Modest",
                  "Simple living. Bills get paid, but there's little room for extras.",
                  happiness_drift=-1, health_drift=0),
    LifestyleTier(3, "Comfortable",
                  "A solid middle. Enough for needs and some wants.",
                  happiness_drift=0, health_drift=0),
    LifestyleTier(4, "Affluent",
                  "Money isn't a worry. Choices are plentiful.",
                  happiness_drift=+1, health_drift=+1),
    LifestyleTier(5, "Wealthy",
                  "Significant means. Few material constraints.",
                  happiness_drift=+2, health_drift=+1),
    LifestyleTier(6, "Luxurious",
                  "Extreme abundance. A life most people only read about.",
                  happiness_drift=+2, health_drift=+1),
]

TIER_BY_LEVEL: dict[int, LifestyleTier] = {t.level: t for t in TIERS}


def get_tier(level: int) -> LifestyleTier:
    return TIER_BY_LEVEL.get(max(0, min(6, level)), TIERS[0])


# ---------------------------------------------------------------------------
# Budget costs — monthly living expenses per tier level
# ---------------------------------------------------------------------------
# These represent daily life costs (food, clothing, utilities,
# entertainment baseline) as a fraction of the country's GDP per
# capita. The player chooses a budget level; the game deducts the
# yearly cost and factors it into the tier calculation.

BUDGET_MONTHLY_FRACTION: dict[int, float] = {
    0: 0.005,   # Destitute — bare survival
    1: 0.015,   # Poor — ramen and thrift stores
    2: 0.03,    # Modest — comfortable basics
    3: 0.06,    # Comfortable — nice food, decent clothes
    4: 0.10,    # Affluent — organic everything, quality brands
    5: 0.18,    # Wealthy — premium everything, dining out often
    6: 0.35,    # Luxurious — Michelin stars and cashmere
}

BUDGET_LABELS: dict[int, str] = {
    0: "Survival",
    1: "Frugal",
    2: "Modest",
    3: "Comfortable",
    4: "Upscale",
    5: "Premium",
    6: "Lavish",
}


def budget_yearly_cost(character: Character, country: Country) -> int:
    """Annual cost of the player's chosen lifestyle budget."""
    frac = BUDGET_MONTHLY_FRACTION.get(character.lifestyle_budget, 0.03)
    return max(0, int(country.gdp_pc * frac * 12))


def budget_options(country: Country) -> list[dict]:
    """Return the budget options with scaled costs for the frontend."""
    out = []
    for level in range(7):
        yearly = int(country.gdp_pc * BUDGET_MONTHLY_FRACTION[level] * 12)
        monthly = int(country.gdp_pc * BUDGET_MONTHLY_FRACTION[level])
        out.append({
            "level": level,
            "label": BUDGET_LABELS[level],
            "monthly_cost": monthly,
            "yearly_cost": yearly,
        })
    return out


# ---------------------------------------------------------------------------
# Tier computation
# ---------------------------------------------------------------------------

def compute_tier(character: Character, country: Country) -> int:
    """Compute the character's lifestyle tier (0-6) based on their
    financial position relative to the country's economy.

    The algorithm blends three signals:

    1. **Budget choice** — the player's chosen daily living spending
       level. This is the primary lever for player agency.

    2. **Spending rate** — subscription costs + purchase history as a
       fraction of GDP. Captures ongoing lifestyle decisions.

    3. **Wealth position** — net worth relative to GDP per capita.
       Captures accumulated assets.

    Budget choice weighs most heavily (40%) because it's the player's
    direct input. Wealth (35%) and spending (25%) provide reality
    checks — you can't live lavishly with no money.
    """
    gdp = max(1, country.gdp_pc)

    # --- Budget signal (player's direct choice) ---
    budget_score = max(0, min(6, character.lifestyle_budget))

    # --- Spending signal ---
    annual_subs = yearly_subscription_cost(character)
    total_purchase_spend = sum(p.get("cost", 0) for p in character.purchases)
    adult_years = max(1, character.age - 17)
    annual_purchase_avg = total_purchase_spend / adult_years
    # Include budget cost in spending calculation.
    budget_cost = budget_yearly_cost(character, country)
    annual_spending = annual_subs + annual_purchase_avg + budget_cost

    spend_ratio = annual_spending / gdp
    if spend_ratio < 0.02:
        spend_score = 0
    elif spend_ratio < 0.05:
        spend_score = 1
    elif spend_ratio < 0.10:
        spend_score = 2
    elif spend_ratio < 0.20:
        spend_score = 3
    elif spend_ratio < 0.40:
        spend_score = 4
    elif spend_ratio < 0.80:
        spend_score = 5
    else:
        spend_score = 6

    # --- Wealth signal ---
    portfolio = portfolio_value(character)
    net_worth = character.money + portfolio + character.family_wealth - character.debt
    wealth_ratio = net_worth / gdp
    if wealth_ratio < 0.1:
        wealth_score = 0
    elif wealth_ratio < 0.5:
        wealth_score = 1
    elif wealth_ratio < 1.5:
        wealth_score = 2
    elif wealth_ratio < 4.0:
        wealth_score = 3
    elif wealth_ratio < 10.0:
        wealth_score = 4
    elif wealth_ratio < 30.0:
        wealth_score = 5
    else:
        wealth_score = 6

    # Can't live above your means indefinitely — cap the tier at
    # wealth_score + 2 so a broke character can't sustain "Lavish."
    affordable_cap = wealth_score + 2

    blended = budget_score * 0.4 + spend_score * 0.25 + wealth_score * 0.35
    return max(0, min(6, min(affordable_cap, round(blended))))


# ---------------------------------------------------------------------------
# Yearly effects
# ---------------------------------------------------------------------------

def apply_yearly_effects(character: Character, country: Country) -> dict:
    """Compute the lifestyle tier and apply its yearly effects to the
    character. Returns a summary dict for the event log.

    Called from advance_year after income/expenses are settled so the
    tier reflects the current year's financial position.
    """
    tier_level = compute_tier(character, country)
    tier = get_tier(tier_level)

    # Store on character for serialization / frontend display.
    character.lifestyle_tier = tier_level
    character.lifestyle_tier_name = tier.name

    # Apply effects.
    deltas: dict[str, int] = {}
    if tier.happiness_drift:
        character.attributes.adjust(happiness=tier.happiness_drift)
        deltas["happiness"] = tier.happiness_drift
    if tier.health_drift:
        character.attributes.adjust(health=tier.health_drift)
        deltas["health"] = tier.health_drift

    return {
        "tier": tier_level,
        "tier_name": tier.name,
        "description": tier.description,
        "deltas": deltas,
    }
