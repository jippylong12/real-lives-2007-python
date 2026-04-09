"""
Random life event registry.

The original game has hundreds of distinct events organized in
`events/{crime,health,disaster,war,education,moral,life}/`. We model the same
shape — each event has eligibility (age range, country stat dependencies),
optional player choices, and outcomes that mutate character attributes.

Events fall into three categories:

  - PASSIVE  (no player choice): something happens, attributes change
  - CHOICE   (player decides): the engine pauses and the API returns the
             event so the frontend can present buttons; the engine resumes
             after `apply_decision`
  - MILESTONE: birth, marriage, retirement, death (handled by other modules)

Adding new events: drop another `Event(...)` into EVENT_REGISTRY. The yearly
loop in `game.py` walks the registry, evaluates `eligible(...)` for each, and
fires anything whose probability roll passes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import diseases
from .character import Character, EducationLevel, Gender
from .world import Country


@dataclass
class EventChoice:
    key: str
    label: str
    deltas: dict[str, int] = field(default_factory=dict)   # attribute deltas
    money_delta: int = 0
    moral_delta: dict[str, int] = field(default_factory=dict)
    summary: str = ""


@dataclass
class EventOutcome:
    summary: str
    deltas: dict[str, int] = field(default_factory=dict)
    money_delta: int = 0
    moral_delta: dict[str, int] = field(default_factory=dict)
    health_capped: bool = False


@dataclass
class Event:
    key: str
    title: str
    category: str          # 'health' | 'crime' | 'disaster' | 'war' | 'education' | 'moral' | 'life' | 'finance'
    description: str
    eligible: Callable[[Character, Country], bool]
    probability: Callable[[Character, Country], float]
    apply: Callable[[Character, Country, "random.Random"], EventOutcome]
    choices: Optional[list[EventChoice]] = None  # if set, this is a CHOICE event


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _passive(
    key: str,
    title: str,
    category: str,
    description: str,
    *,
    when: Callable[[Character, Country], bool],
    chance: Callable[[Character, Country], float],
    apply: Callable[[Character, Country, random.Random], EventOutcome],
) -> Event:
    return Event(key=key, title=title, category=category, description=description,
                 eligible=when, probability=chance, apply=apply)


def _choice(
    key: str,
    title: str,
    category: str,
    description: str,
    *,
    when: Callable[[Character, Country], bool],
    chance: Callable[[Character, Country], float],
    choices: list[EventChoice],
) -> Event:
    def stub_apply(c, co, rng):  # never invoked: choice events resolve via apply_decision
        return EventOutcome(summary=description)
    return Event(
        key=key, title=title, category=category, description=description,
        eligible=when, probability=chance, apply=stub_apply, choices=choices,
    )


# ---------------------------------------------------------------------------
# Event applies
# ---------------------------------------------------------------------------

def _apply_specific_disease(c, co, rng):
    disease = diseases.roll_disease(c, co, rng)
    if disease is None:
        return EventOutcome(summary="")  # nothing fired this year
    payload = diseases.contract_disease(c, co, disease, rng)
    return EventOutcome(
        summary=payload["summary"],
        deltas=payload["deltas"],
        money_delta=payload["money_delta"],
    )


def _apply_minor_injury(c, co, rng):
    sev = rng.randint(2, 8)
    return EventOutcome(summary=f"You had an accident and were briefly injured. (-{sev} health)",
                        deltas={"health": -sev})


def _apply_natural_disaster(c, co, rng):
    sev = rng.randint(8, 25)
    money_loss = int(min(c.money, c.money * rng.uniform(0.1, 0.6)))
    return EventOutcome(
        summary=f"A natural disaster struck {co.name}. You survived but lost belongings.",
        deltas={"health": -sev, "happiness": -10},
        money_delta=-money_loss,
    )


def _apply_war(c, co, rng):
    sev = rng.randint(10, 30)
    return EventOutcome(
        summary=f"Conflict broke out in {co.name}. You were affected by the violence.",
        deltas={"health": -sev, "happiness": -15, "wisdom": +3},
    )


def _apply_school_year(c, co, rng):
    if not c.in_school:
        return EventOutcome(summary="")
    intel_gain = rng.randint(2, 5)
    wisdom_gain = rng.randint(1, 3)
    return EventOutcome(
        summary="Another year of school: you learned a lot.",
        deltas={"intelligence": intel_gain, "wisdom": wisdom_gain},
    )


def _apply_athletic_growth(c, co, rng):
    g = rng.randint(2, 6)
    return EventOutcome(summary="You spent time playing sports and grew stronger.",
                        deltas={"athletic": g, "strength": g // 2, "endurance": g // 2, "happiness": +2})


def _apply_artistic_growth(c, co, rng):
    g = rng.randint(2, 5)
    return EventOutcome(summary="You discovered a love of art this year.",
                        deltas={"artistic": g, "happiness": +3})


def _apply_musical_growth(c, co, rng):
    g = rng.randint(2, 5)
    return EventOutcome(summary="You picked up an instrument and practiced often.",
                        deltas={"musical": g, "happiness": +3})


def _apply_friendship(c, co, rng):
    return EventOutcome(summary="You made a close friend.",
                        deltas={"happiness": +6, "appearance": +1})


def _apply_lonely(c, co, rng):
    return EventOutcome(summary="You felt isolated this year.",
                        deltas={"happiness": -7})


def _apply_inheritance(c, co, rng):
    amount = int(c.family_wealth * rng.uniform(0.2, 1.5))
    return EventOutcome(
        summary=f"A relative passed away and left you ${amount:,}.",
        deltas={"happiness": -8, "wisdom": +1},
        money_delta=amount,
    )


def _apply_promotion(c, co, rng):
    raise_pct = rng.uniform(0.10, 0.40)
    return EventOutcome(
        summary=f"You were promoted at work! Your salary rose by {int(raise_pct * 100)}%.",
        deltas={"happiness": +6, "wisdom": +1},
        money_delta=int(c.salary * raise_pct),
    )


def _apply_pregnancy(c, co, rng):
    return EventOutcome(
        summary="You and your spouse welcomed a new child.",
        deltas={"happiness": +12, "health": -3},
    )


def _apply_civic_engagement(c, co, rng):
    return EventOutcome(
        summary="You volunteered in your community.",
        deltas={"happiness": +5, "conscience": +3, "wisdom": +1},
    )


def _apply_corruption_witnessed(c, co, rng):
    return EventOutcome(
        summary="You witnessed corruption in local government.",
        deltas={"happiness": -3, "wisdom": +2},
    )


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

THEFT_CHILD = _choice(
    key="theft_child",
    title="A tempting opportunity",
    category="moral",
    description=(
        "You see an unattended toy at a market stall. The owner is distracted "
        "and no one is watching you. Property crimes are more frequent in "
        "countries with high inequality — the choice is yours."
    ),
    when=lambda c, co: 8 <= c.age <= 14,
    chance=lambda c, co: 0.05 + co.gini / 500,
    choices=[
        EventChoice(key="steal", label="Take the toy",
                    deltas={"happiness": +2, "conscience": -8},
                    moral_delta={"theft": 1},
                    summary="You took the toy. Your conscience nags you a little."),
        EventChoice(key="resist", label="Walk away",
                    deltas={"conscience": +3, "wisdom": +1},
                    summary="You walked away. You feel proud of yourself."),
    ],
)

THEFT_ADULT = _choice(
    key="theft_adult",
    title="A risky opportunity",
    category="crime",
    description=(
        "You spot a delivery van left unlocked with valuable merchandise inside. "
        "Stealing it could net you a lot of money — and a lot of trouble."
    ),
    when=lambda c, co: 18 <= c.age <= 50 and c.money < co.gdp_pc * 0.5,
    chance=lambda c, co: 0.04 + co.gini / 700 + (1 - c.attributes.conscience / 100) * 0.05,
    choices=[
        EventChoice(key="steal", label="Take the merchandise",
                    deltas={"conscience": -15, "happiness": +5},
                    money_delta=2500,
                    moral_delta={"theft": 1},
                    summary="You walked off with the goods. Sold them for cash."),
        EventChoice(key="walk", label="Walk away",
                    deltas={"conscience": +5, "wisdom": +2},
                    summary="You walked away. Your integrity intact."),
        EventChoice(key="report", label="Report it",
                    deltas={"conscience": +8, "happiness": +3, "wisdom": +1},
                    summary="You reported the unlocked van. The owner thanked you."),
    ],
)

BRIBERY = _choice(
    key="bribery",
    title="An offer of bribery",
    category="moral",
    description=(
        "A local official offers you faster paperwork in exchange for a small "
        "envelope of cash. It would save you months of waiting."
    ),
    when=lambda c, co: c.age >= 22 and co.corruption > 50,
    chance=lambda c, co: 0.03 + co.corruption / 1500,
    choices=[
        EventChoice(key="pay", label="Pay the bribe",
                    deltas={"conscience": -10, "happiness": +3},
                    money_delta=-300,
                    moral_delta={"bribery": 1},
                    summary="You paid. Things moved faster, but you feel uneasy."),
        EventChoice(key="refuse", label="Refuse",
                    deltas={"conscience": +5, "happiness": -2},
                    summary="You refused. The paperwork is delayed by months."),
    ],
)

MILITARY_SERVICE = _choice(
    key="military_service",
    title="Military conscription",
    category="war",
    description="You have been called up for military service. Will you serve, or seek an exemption?",
    when=lambda c, co: 18 <= c.age <= 22 and c.gender == Gender.MALE and co.war_freq > 0.01,
    chance=lambda c, co: 0.4,
    choices=[
        EventChoice(key="serve", label="Serve in the military",
                    deltas={"strength": +8, "endurance": +8, "wisdom": +5, "happiness": -5},
                    summary="You served your country. The experience hardened you."),
        EventChoice(key="exempt", label="Seek a medical exemption",
                    deltas={"happiness": +2, "conscience": -3},
                    summary="You secured an exemption and avoided service."),
        EventChoice(key="refuse", label="Refuse outright",
                    deltas={"conscience": +5, "happiness": -10, "wisdom": +3},
                    summary="You refused. There may be consequences..."),
    ],
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EVENT_REGISTRY: list[Event] = [
    # --- Health ---
    # The specific-disease event always rolls every year; the registry's
    # eligibility wrapper just gates by age and lets diseases.roll_disease
    # decide whether anything actually fires for this character.
    _passive(
        "specific_disease", "Disease", "health",
        "A specific health condition strikes.",
        when=lambda c, co: c.age >= 0,
        chance=lambda c, co: 1.0,
        apply=_apply_specific_disease,
    ),
    _passive(
        "minor_injury", "Minor injury", "health",
        "An accident leaves you bruised.",
        when=lambda c, co: c.age >= 2,
        chance=lambda c, co: 0.10,
        apply=_apply_minor_injury,
    ),

    # --- Disaster ---
    _passive(
        "natural_disaster", "Natural disaster", "disaster",
        "A natural disaster strikes the region.",
        when=lambda c, co: True,
        chance=lambda c, co: co.disaster_freq,
        apply=_apply_natural_disaster,
    ),

    # --- War ---
    _passive(
        "war_event", "Conflict in the region", "war",
        "Conflict touches your life.",
        when=lambda c, co: True,
        chance=lambda c, co: co.war_freq,
        apply=_apply_war,
    ),
    MILITARY_SERVICE,

    # --- Education / growth ---
    _passive(
        "school_year", "Schooling", "education",
        "Another year of school passes.",
        when=lambda c, co: c.in_school and c.age <= 25,
        chance=lambda c, co: 0.95,
        apply=_apply_school_year,
    ),
    _passive(
        "athletic_growth", "Athletic interest", "life",
        "You took up sports.",
        when=lambda c, co: 6 <= c.age <= 25,
        chance=lambda c, co: 0.20,
        apply=_apply_athletic_growth,
    ),
    _passive(
        "artistic_growth", "Artistic interest", "life",
        "You explored your creativity.",
        when=lambda c, co: 5 <= c.age <= 30,
        chance=lambda c, co: 0.15,
        apply=_apply_artistic_growth,
    ),
    _passive(
        "musical_growth", "Musical interest", "life",
        "You picked up an instrument.",
        when=lambda c, co: 6 <= c.age <= 35,
        chance=lambda c, co: 0.12,
        apply=_apply_musical_growth,
    ),

    # --- Social ---
    _passive(
        "made_friend", "New friendship", "life",
        "A new friendship blossoms.",
        when=lambda c, co: c.age >= 4,
        chance=lambda c, co: 0.18 + c.attributes.appearance * 0.001,
        apply=_apply_friendship,
    ),
    _passive(
        "lonely_year", "A lonely year", "life",
        "You felt very alone.",
        when=lambda c, co: c.age >= 10,
        chance=lambda c, co: 0.10,
        apply=_apply_lonely,
    ),

    # --- Finance / career ---
    _passive(
        "inheritance", "Inheritance", "finance",
        "You receive an inheritance.",
        when=lambda c, co: c.age >= 25,
        chance=lambda c, co: 0.015,
        apply=_apply_inheritance,
    ),
    _passive(
        "promotion", "Career promotion", "finance",
        "You are promoted at work.",
        when=lambda c, co: c.job is not None and c.age >= 22,
        chance=lambda c, co: 0.12 + c.attributes.intelligence * 0.001,
        apply=_apply_promotion,
    ),

    # --- Family ---
    _passive(
        "had_child", "A new child", "life",
        "You and your spouse had a child.",
        when=lambda c, co: c.married and c.age <= 45 and len(c.children) < 5,
        chance=lambda c, co: 0.18,
        apply=_apply_pregnancy,
    ),

    # --- Civic ---
    _passive(
        "civic_engagement", "Civic engagement", "moral",
        "You participated in your community.",
        when=lambda c, co: c.age >= 16,
        chance=lambda c, co: 0.08 + c.attributes.conscience * 0.001,
        apply=_apply_civic_engagement,
    ),
    _passive(
        "witnessed_corruption", "Witnessed corruption", "moral",
        "You witnessed local corruption.",
        when=lambda c, co: c.age >= 16 and co.corruption > 40,
        chance=lambda c, co: co.corruption / 1500,
        apply=_apply_corruption_witnessed,
    ),

    # --- Choice events ---
    THEFT_CHILD,
    THEFT_ADULT,
    BRIBERY,
]


def roll_events(character: Character, country: Country, rng: random.Random) -> list[Event]:
    """Decide which events fire this year. The first CHOICE event seen halts
    the rest of the year so the player can make their decision."""
    fired: list[Event] = []
    for ev in EVENT_REGISTRY:
        if not ev.eligible(character, country):
            continue
        p = max(0.0, min(1.0, ev.probability(character, country)))
        if rng.random() < p:
            fired.append(ev)
            if ev.choices:
                break
    return fired
