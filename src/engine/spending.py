"""
Discretionary spending: lifestyle purchases and recurring subscriptions (#66).

The career system gives the player a salary; the investment system lets
them park money; the loan system lets them borrow. Until v1.3 there was
no way to *spend* money on the actual life the character is living. This
module adds a small registry of meaningful purchases — houses, cars,
vacations, charity, gym memberships, therapy, hobbies — each with a
cost, an effect on attributes / happiness / family wealth, and an
optional recurring subscription.

Big-ticket purchases are one-time and added to ``character.purchases``
for the death retrospective. Subscriptions live in
``character.subscriptions`` and the yearly income tick in
:mod:`careers` deducts their costs.

Country-relative pricing
------------------------
A "house" in Norway costs vastly more than a "house" in rural Niger.
Each purchase declares a USD-baseline cost and is scaled by
``country.gdp_pc / 50000`` (the same scale the careers module uses for
salaries) so the relative affordability stays meaningful across the
193 countries the binary covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .character import Character
from .world import Country


@dataclass(frozen=True)
class Purchase:
    """One row in the discretionary-spending registry."""
    key: str                       # stable identifier (used by API + tests)
    name: str                      # display label
    category: str                  # 'big' | 'lifestyle' | 'subscription' | 'charity' | 'gift'
    description: str
    base_cost: int                 # USD baseline; scaled by country GDP
    deltas: dict[str, int] = field(default_factory=dict)
    happiness_delta: int = 0
    family_wealth_delta: int = 0
    one_time: bool = True          # if False, can be bought again
    monthly_cost: int = 0          # subscriptions only
    requires_no_existing: str | None = None  # block if character has this purchase key
    requires_min_age: int = 14
    min_health_services: int = 0   # gates premium services to good-healthcare countries


# Curated registry. Each purchase tries to feel like a real life
# decision a person in their 20s/30s/40s would make: housing, mobility,
# leisure, generosity, wellness.
PURCHASES: list[Purchase] = [
    # ---------- Big purchases (one-time, large) ----------
    Purchase(
        key="house_starter",
        name="Starter home",
        category="big",
        description="A modest place to call your own. Major commitment, lasting impact.",
        base_cost=80_000,
        family_wealth_delta=60_000,
        happiness_delta=10,
        deltas={"conscience": +2},
        requires_min_age=21,
        requires_no_existing="house_starter",
    ),
    Purchase(
        key="house_family",
        name="Family home",
        category="big",
        description="Bigger, nicer, in a better neighborhood. The kind of place a family grows up in.",
        base_cost=250_000,
        family_wealth_delta=200_000,
        happiness_delta=14,
        deltas={"conscience": +3, "appearance": +1},
        requires_min_age=25,
    ),
    Purchase(
        key="house_luxury",
        name="Luxury home",
        category="big",
        description="A statement of arrival. Marble floors, a view, and a sizable mortgage even if you pay cash.",
        base_cost=900_000,
        family_wealth_delta=750_000,
        happiness_delta=18,
        deltas={"appearance": +3, "happiness": +5},
        requires_min_age=30,
    ),
    Purchase(
        key="car_basic",
        name="Reliable car",
        category="big",
        description="Gets you around. A daily driver.",
        base_cost=14_000,
        happiness_delta=4,
        requires_min_age=18,
    ),
    Purchase(
        key="car_premium",
        name="Premium car",
        category="big",
        description="Comfortable, fast, and noticed. People look twice.",
        base_cost=45_000,
        happiness_delta=8,
        deltas={"appearance": +2},
        requires_min_age=22,
    ),
    Purchase(
        key="car_luxury",
        name="Luxury car",
        category="big",
        description="A symbol. The kind of vehicle that makes valets pay attention.",
        base_cost=120_000,
        happiness_delta=12,
        deltas={"appearance": +3},
        requires_min_age=28,
    ),

    # ---------- Lifestyle one-time purchases ----------
    Purchase(
        key="vacation_local",
        name="Domestic vacation",
        category="lifestyle",
        description="A week away. Familiar food, no jet lag.",
        base_cost=800,
        happiness_delta=6,
        deltas={"wisdom": +1, "health": -1},
        one_time=False,
        requires_min_age=16,
    ),
    Purchase(
        key="vacation_international",
        name="International vacation",
        category="lifestyle",
        description="A passport stamp and a sense of how big the world is.",
        base_cost=4_500,
        happiness_delta=12,
        deltas={"wisdom": +3, "health": -2},
        one_time=False,
        requires_min_age=18,
    ),
    Purchase(
        key="vacation_luxury",
        name="Luxury holiday",
        category="lifestyle",
        description="The kind of trip you'll talk about for years. Five-star everything.",
        base_cost=20_000,
        happiness_delta=18,
        deltas={"wisdom": +4, "appearance": +1, "health": -2},
        one_time=False,
        requires_min_age=22,
    ),

    # ---------- Subscriptions (recurring monthly cost) ----------
    Purchase(
        key="sub_gym",
        name="Gym membership",
        category="subscription",
        description="Stay strong. Slow physical decline.",
        base_cost=0,
        monthly_cost=50,
        one_time=True,
        requires_min_age=14,
        deltas={"strength": +2, "endurance": +1, "health": +1},
    ),
    Purchase(
        key="sub_therapy",
        name="Weekly therapy",
        category="subscription",
        description="Talk to someone. Sort yourself out.",
        base_cost=0,
        monthly_cost=200,
        requires_min_age=16,
        deltas={"happiness": +3, "wisdom": +1},
    ),
    Purchase(
        key="sub_premium_health",
        name="Premium healthcare plan",
        category="subscription",
        description="Concierge medicine — better doctors, faster appointments, premium drugs. Recovery happens faster.",
        base_cost=0,
        monthly_cost=500,
        requires_min_age=18,
        min_health_services=60,
        deltas={"health": +2},
    ),
    Purchase(
        key="sub_hobby",
        name="Hobby & streaming",
        category="subscription",
        description="A small monthly indulgence — books, music, streaming, the games you grew up with.",
        base_cost=0,
        monthly_cost=30,
        requires_min_age=10,
        deltas={"happiness": +1},
    ),

    # ---------- Charity / family ----------
    Purchase(
        key="charity_small",
        name="Donate to charity",
        category="charity",
        description="A meaningful gift to a cause you care about.",
        base_cost=500,
        happiness_delta=4,
        deltas={"conscience": +5, "wisdom": +1},
        one_time=False,
        requires_min_age=12,
    ),
    Purchase(
        key="charity_major",
        name="Major philanthropy",
        category="charity",
        description="The kind of donation that gets a wing named after you.",
        base_cost=50_000,
        happiness_delta=10,
        deltas={"conscience": +12, "wisdom": +3, "appearance": +1},
        one_time=False,
        requires_min_age=25,
    ),
    Purchase(
        key="gift_family",
        name="Family gift",
        category="gift",
        description="Something nice for the people who raised you.",
        base_cost=2_000,
        happiness_delta=5,
        deltas={"conscience": +3},
        one_time=False,
        requires_min_age=14,
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _scale_for_country(country: Country) -> float:
    """Same scale as careers module — keeps relative affordability sensible."""
    return max(0.05, country.gdp_pc / 50000)


def scaled_cost(purchase: Purchase, country: Country) -> int:
    if purchase.base_cost <= 0:
        return 0
    return max(1, int(purchase.base_cost * _scale_for_country(country)))


def get_purchase(key: str) -> Purchase | None:
    return next((p for p in PURCHASES if p.key == key), None)


def list_purchases(character: Character, country: Country) -> list[dict]:
    """Return every purchase annotated with the character's eligibility,
    affordability (#73), and ownership / subscription state. Used by the
    frontend's spend panel.

    Repeat purchases (vacations, charity, family gifts) are intentionally
    NOT marked as owned (#76) — buying one doesn't lock you out of the
    next. Only ``one_time`` items get the owned tag.
    """
    out = []
    scale = _scale_for_country(country)
    for p in PURCHASES:
        cost = scaled_cost(p, country)
        monthly = int(p.monthly_cost * scale) if p.monthly_cost else 0
        eligible, reason = _check_eligibility(p, character, country)
        # #76: only one-time purchases get the owned flag. Repeats can
        # always be re-bought.
        owned = p.one_time and any(rec.get("key") == p.key for rec in character.purchases)
        subscribed = p.category == "subscription" and p.key in character.subscriptions
        # #73: affordability is a separate gate from eligibility. The
        # listing returns it so the frontend can disable Buy when broke
        # without making a separate call only to get a 400.
        affordable = character.money >= cost
        # If not eligible AND no other reason, mention affordability.
        if eligible and not affordable:
            reason = f"need ${cost:,}, have ${character.money:,}"
        # Pretty-printed effect chips for the UI (#77)
        effects = []
        if p.deltas:
            for k, v in p.deltas.items():
                if v:
                    sign = "+" if v > 0 else ""
                    effects.append(f"{sign}{v} {k}")
        if p.happiness_delta:
            effects.append(f"+{p.happiness_delta} happiness")
        if p.family_wealth_delta:
            effects.append(f"+${int(p.family_wealth_delta * scale):,} family wealth")
        out.append({
            "key": p.key,
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "cost": cost,
            "monthly_cost": monthly,
            "happiness_delta": p.happiness_delta,
            "family_wealth_delta": int(p.family_wealth_delta * scale) if p.family_wealth_delta else 0,
            "one_time": p.one_time,
            "eligible": eligible and affordable,
            "affordable": affordable,
            "reason": reason,
            "owned": owned,
            "subscribed": subscribed,
            "effects": effects,
        })
    return out


def _check_eligibility(p: Purchase, character: Character, country: Country) -> tuple[bool, str | None]:
    if character.age < p.requires_min_age:
        return False, f"requires age {p.requires_min_age}+"
    if p.min_health_services and country.health_services_pct < p.min_health_services:
        return False, f"requires good local healthcare (≥{p.min_health_services}% services)"
    if p.requires_no_existing and any(rec.get("key") == p.requires_no_existing for rec in character.purchases):
        return False, "you already own one"
    if p.category == "subscription" and p.key in character.subscriptions:
        return False, "already subscribed"
    return True, None


@dataclass
class BuyResult:
    success: bool
    message: str
    cost: int = 0


def buy(character: Character, country: Country, purchase_key: str, year: int) -> BuyResult:
    """Apply a purchase to the character. Drains money, applies deltas,
    records the purchase / starts the subscription. Returns BuyResult.

    For one-time bigs (houses, cars), records into character.purchases.
    For subscriptions, adds to character.subscriptions and the yearly
    tick will deduct the recurring cost.
    """
    p = get_purchase(purchase_key)
    if p is None:
        return BuyResult(False, f"unknown purchase {purchase_key!r}")

    eligible, reason = _check_eligibility(p, character, country)
    if not eligible:
        return BuyResult(False, reason or "not eligible")

    cost = scaled_cost(p, country)
    if cost > 0 and character.money < cost:
        return BuyResult(False, f"not enough cash (need ${cost:,}, have ${character.money:,})")

    if cost > 0:
        character.money -= cost

    # Apply attribute deltas immediately for one-time purchases. For
    # subscriptions, the deltas are applied yearly by the yearly tick
    # so we don't double-credit them on the buy day.
    scaled_family_wealth = 0
    if p.category != "subscription":
        if p.deltas:
            character.attributes.adjust(**p.deltas)
        if p.happiness_delta:
            character.attributes.adjust(happiness=p.happiness_delta)
        if p.family_wealth_delta:
            scaled_family_wealth = int(p.family_wealth_delta * _scale_for_country(country))
            character.family_wealth += scaled_family_wealth
        character.purchases.append({
            "key": p.key,
            "name": p.name,
            "category": p.category,
            "year": year,
            "cost": cost,
        })
    else:
        character.subscriptions[p.key] = {
            "name": p.name,
            "monthly_cost": int(p.monthly_cost * _scale_for_country(country)),
            "started_year": year,
            "deltas": dict(p.deltas),
        }

    if p.category == "subscription":
        msg = f"You started a {p.name} subscription."
    elif cost > 0:
        msg = f"You bought a {p.name} for ${cost:,}."
    else:
        msg = f"You acquired a {p.name}."

    # #77: write a timeline entry for one-time purchases with the effect
    # summary, so gifts / charity / vacations don't vanish into a
    # transient toast. Subscriptions get yearly entries via
    # apply_subscription_effects, so we skip them here.
    if p.category != "subscription":
        effect_bits = []
        if p.deltas:
            for k, v in p.deltas.items():
                if not v:
                    continue
                sign = "+" if v > 0 else ""
                effect_bits.append(f"{sign}{v} {k}")
        if p.happiness_delta:
            sign = "+" if p.happiness_delta > 0 else ""
            effect_bits.append(f"{sign}{p.happiness_delta} happiness")
        if scaled_family_wealth:
            effect_bits.append(f"+${scaled_family_wealth:,} family wealth")
        suffix = f" ({', '.join(effect_bits)})" if effect_bits else ""
        if cost > 0:
            character.remember(f"Bought a {p.name} for ${cost:,}{suffix}.")
        else:
            character.remember(f"Acquired a {p.name}{suffix}.")

    return BuyResult(True, msg, cost=cost)


def cancel_subscription(character: Character, key: str) -> BuyResult:
    """Cancel a recurring subscription (#66)."""
    if key not in character.subscriptions:
        return BuyResult(False, f"you don't have a {key} subscription")
    name = character.subscriptions[key].get("name", key)
    del character.subscriptions[key]
    return BuyResult(True, f"You cancelled your {name}.")


def yearly_subscription_cost(character: Character) -> int:
    """Total cash drained by all active subscriptions this year."""
    return sum(int(s.get("monthly_cost", 0)) * 12 for s in character.subscriptions.values())


_SUBSCRIPTION_FLAVOR: dict[str, str] = {
    "sub_gym": "Another year at the gym kept you in shape.",
    "sub_therapy": "Therapy helped you process the year.",
    "sub_premium_health": "Your premium healthcare plan kept the doctors close.",
    "sub_hobby": "Your hobbies and streaming brought small joys.",
}


def apply_subscription_effects(character: Character) -> list[dict]:
    """Apply each active subscription's per-year attribute deltas. Called
    by the yearly tick AFTER the cash deduction. Returns a list of
    summary records the engine can surface in the event log so the
    player sees what their subscription is actually doing (#77).
    """
    out = []
    for key, sub in character.subscriptions.items():
        deltas = sub.get("deltas") or {}
        if deltas:
            character.attributes.adjust(**deltas)
        out.append({
            "key": key,
            "name": sub.get("name", key),
            "summary": _SUBSCRIPTION_FLAVOR.get(key, f"Your {sub.get('name', key)} kept paying off."),
            "deltas": deltas,
        })
    return out
