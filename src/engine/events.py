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
    # Optional callback that runs after deltas/money/moral are applied,
    # for choices that need to mutate character state directly (e.g.,
    # education path choice changing in_school / education level).
    side_effect: Callable[["Character"], None] | None = None


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
    cooldown_years: int = 0     # 0 = no cooldown (annual rhythm allowed)
    max_lifetime: int = 0       # 0 = unlimited; 1 = once per character; etc.
    # #52 followup: slice-of-life events (the ~200 new content-drop
    # entries created via _simple_passive) are sampled down to
    # MAX_SLICE_OF_LIFE_PER_YEAR per year so the event log stays
    # readable. Structural events (disease, disaster, war, school year,
    # holidays, choice events) always fire when eligible regardless.
    slice_of_life: bool = False


# #52 followup: cap on the number of slice-of-life events that can
# fire in a single year. Without this, with ~218 slice-of-life entries
# at ~5% chance each, the expected per-year firing rate is ~11 events
# which floods the event log. Combined with the always-on structural
# events (income tick, holidays, school year, disease, financial
# stress) a cap of 2 keeps a typical year at ~4-5 total entries.
MAX_SLICE_OF_LIFE_PER_YEAR = 2


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
    cooldown_years: int = 0,
    max_lifetime: int = 0,
) -> Event:
    return Event(key=key, title=title, category=category, description=description,
                 eligible=when, probability=chance, apply=apply,
                 cooldown_years=cooldown_years, max_lifetime=max_lifetime)


def _choice(
    key: str,
    title: str,
    category: str,
    description: str,
    *,
    when: Callable[[Character, Country], bool],
    chance: Callable[[Character, Country], float],
    choices: list[EventChoice],
    cooldown_years: int = 0,
    max_lifetime: int = 0,
) -> Event:
    def stub_apply(c, co, rng):  # never invoked: choice events resolve via apply_decision
        return EventOutcome(summary=description)
    return Event(
        key=key, title=title, category=category, description=description,
        eligible=when, probability=chance, apply=stub_apply, choices=choices,
        cooldown_years=cooldown_years, max_lifetime=max_lifetime,
    )


def _simple_passive(
    key: str,
    title: str,
    summary: str,
    *,
    when: Callable[[Character, Country], bool],
    chance: Callable[[Character, Country], float],
    cooldown_years: int = 0,
    max_lifetime: int = 0,
    deltas: Optional[dict[str, int]] = None,
    money_delta: int = 0,
    history: Optional[str] = None,
    category: str = "life",
) -> Event:
    """Compact constructor for slice-of-life passive events that just
    nudge a few attributes and append a history line. Used by the
    ~200-event content drop in #52 — keeps each event entry to ~3-4
    lines instead of bespoke apply functions for every one.

    Events created here are flagged ``slice_of_life=True`` so
    ``roll_events`` can cap them to MAX_SLICE_OF_LIFE_PER_YEAR per
    year and keep the event log readable."""
    _deltas = dict(deltas) if deltas else {}
    _money = money_delta
    _history = history if history is not None else summary
    def apply(c, co, rng):
        if _deltas:
            c.attributes.adjust(**_deltas)
        c.remember(_history)
        return EventOutcome(summary=summary, deltas=_deltas, money_delta=_money)
    ev = _passive(
        key=key, title=title, category=category, description=summary,
        when=when, chance=chance, apply=apply,
        cooldown_years=cooldown_years, max_lifetime=max_lifetime,
    )
    ev.slice_of_life = True
    return ev


# ---------------------------------------------------------------------------
# Event applies
# ---------------------------------------------------------------------------

def _apply_specific_disease(c, co, rng):
    """Apply every disease that fires this year (#22) and return ONE
    ``EventOutcome`` per disease (#36). Returning a list lets the engine
    log each diagnosis as its own line in the event feed instead of
    joining them into one wall-of-text entry."""
    fired = diseases.roll_diseases(c, co, rng)
    if not fired:
        return EventOutcome(summary="")
    outcomes: list[EventOutcome] = []
    for d in fired:
        payload = diseases.contract_disease(c, co, d, rng)
        outcomes.append(EventOutcome(
            summary=payload["summary"],
            deltas=payload["deltas"],
            money_delta=payload["money_delta"],
        ))
    if len(outcomes) == 1:
        return outcomes[0]
    return outcomes


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
    """Add a new child to character.children (#39 — was previously
    decoration only, the kids stat stayed at 0 forever)."""
    from .character import FamilyMember, Gender, _random_name
    gender = Gender(rng.randint(0, 1))
    child = FamilyMember(
        relation="child",
        name=_random_name(gender, rng),
        age=0,
        alive=True,
        gender=gender,
    )
    c.children.append(child)
    return EventOutcome(
        summary=f"You and your spouse welcomed a {'son' if gender == Gender.MALE else 'daughter'}, {child.name}.",
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


def _apply_village_harvest(c, co, rng):
    return EventOutcome(
        summary=(
            "You spent the season helping with the harvest in your village. "
            "The work was hard but you grew stronger and felt connected to your community."
        ),
        deltas={"strength": +3, "endurance": +2, "happiness": +3, "wisdom": +1},
    )


# ---------------------------------------------------------------------------
# Religion- and culture-specific events
# ---------------------------------------------------------------------------

def _apply_christmas(c, co, rng):
    return EventOutcome(
        summary="You celebrated Christmas with your family. Gifts, carols, and a long meal.",
        deltas={"happiness": +6},
    )


def _apply_easter(c, co, rng):
    return EventOutcome(
        summary="You attended Easter services and shared a feast with relatives.",
        deltas={"happiness": +4, "conscience": +1},
    )


def _apply_ramadan(c, co, rng):
    return EventOutcome(
        summary="You observed Ramadan, fasting from dawn to sunset for a month.",
        deltas={"happiness": +5, "conscience": +3, "wisdom": +2, "endurance": +2, "health": -1},
    )


def _apply_eid(c, co, rng):
    return EventOutcome(
        summary="You celebrated Eid al-Fitr with family and a great feast.",
        deltas={"happiness": +7},
    )


def _apply_diwali(c, co, rng):
    return EventOutcome(
        summary="You celebrated Diwali, lighting lamps and sharing sweets with neighbors.",
        deltas={"happiness": +6, "appearance": +1},
    )


def _apply_vesak(c, co, rng):
    return EventOutcome(
        summary="You attended Vesak observances at the local temple.",
        deltas={"happiness": +4, "wisdom": +2, "conscience": +1},
    )


def _apply_passover(c, co, rng):
    return EventOutcome(
        summary="You hosted a Passover Seder for family and friends.",
        deltas={"happiness": +5, "wisdom": +1},
    )


def _apply_yom_kippur(c, co, rng):
    return EventOutcome(
        summary="You observed Yom Kippur, fasting and reflecting on the past year.",
        deltas={"happiness": +2, "conscience": +5, "wisdom": +2},
    )


def _apply_ancestral_ceremony(c, co, rng):
    return EventOutcome(
        summary="The community gathered for an ancestral ceremony. You felt connected to those who came before.",
        deltas={"happiness": +5, "wisdom": +3, "conscience": +2},
    )


def _apply_baptism(c, co, rng):
    return EventOutcome(
        summary="You were baptized in a Christian ceremony surrounded by family.",
        deltas={"happiness": +3, "conscience": +2},
    )


def _apply_first_communion(c, co, rng):
    return EventOutcome(
        summary="You received your First Communion. Your family was very proud.",
        deltas={"happiness": +5, "conscience": +2, "wisdom": +1},
    )


def _apply_sacred_thread(c, co, rng):
    return EventOutcome(
        summary="You went through the Upanayana sacred-thread ceremony, marking your initiation into adult religious study.",
        deltas={"happiness": +4, "wisdom": +3, "conscience": +2},
    )


def _apply_bar_mitzvah(c, co, rng):
    return EventOutcome(
        summary="You celebrated your Bar/Bat Mitzvah, reading from the Torah for the first time before your community.",
        deltas={"happiness": +6, "wisdom": +3, "conscience": +2},
    )


# ---------------------------------------------------------------------------
# Language- and region-gated events (#16)
# ---------------------------------------------------------------------------

# Languages spoken in former British colonies where cricket is the dominant
# sport (the binary's primary_language doesn't capture "Commonwealth" so we
# enumerate the languages that imply cricket-playing heritage).
_CRICKET_LANGUAGES = {"English", "Hindi", "Urdu", "Bengali", "Sinhala"}

# Languages whose speakers play baseball as a major youth sport.
_BASEBALL_REGIONS = {"Caribbean", "Central America", "South America"}


def _apply_cricket_match(c, co, rng):
    return EventOutcome(
        summary="You spent the weekend playing cricket on a dusty pitch with friends. The match ran into the evening.",
        deltas={"athletic": +3, "endurance": +2, "happiness": +4},
    )


def _apply_baseball_youth(c, co, rng):
    return EventOutcome(
        summary="You played baseball with the neighborhood kids — pickup games every weekend.",
        deltas={"athletic": +3, "strength": +1, "happiness": +4},
    )


def _apply_quinceanera(c, co, rng):
    return EventOutcome(
        summary=(
            "Your quinceañera. Your family threw a big party for your 15th birthday — "
            "white dress, dancing, and a Mass before the celebration."
        ),
        deltas={"happiness": +10, "appearance": +2, "conscience": +2},
    )


def _apply_seijin_shiki(c, co, rng):
    return EventOutcome(
        summary=(
            "You attended Seijin no Hi, the Coming of Age ceremony, in your local town hall. "
            "Wearing formal kimono or a suit, you officially became an adult."
        ),
        deltas={"happiness": +6, "wisdom": +3, "conscience": +2},
    )


def _apply_tea_ceremony(c, co, rng):
    return EventOutcome(
        summary="You learned the etiquette of the tea ceremony from an older relative — patience, precision, and respect.",
        deltas={"wisdom": +3, "artistic": +2, "happiness": +2},
    )


def _apply_vegetarian_household(c, co, rng):
    return EventOutcome(
        summary="Your family follows a vegetarian diet — pulses, vegetables, dairy. You've never eaten meat.",
        deltas={"health": +2, "conscience": +1},
    )


def _apply_fish_heavy_diet(c, co, rng):
    return EventOutcome(
        summary="A coastal year of fresh seafood: fish for breakfast, fish for dinner, fish at every festival.",
        deltas={"health": +2, "happiness": +2},
    )


DOWRY_NEGOTIATION = _choice(
    key="dowry_negotiation",
    title="Dowry negotiation",
    category="life",
    description=(
        "Your family is negotiating a dowry as part of your wedding arrangement. "
        "The custom is expected, but the size of the demand has caused tension."
    ),
    when=lambda c, co: (
        18 <= c.age <= 30
        and not c.married
        and co.primary_language in {"Hindi", "Bengali", "Urdu", "Tamil"}
    ),
    chance=lambda c, co: 0.06,
    choices=[
        EventChoice(
            key="agree",
            label="Pay the dowry",
            deltas={"happiness": -2, "conscience": -1, "wisdom": +1},
            money_delta=-1500,
            summary="The dowry was paid. The wedding is on.",
        ),
        EventChoice(
            key="negotiate",
            label="Negotiate it down",
            deltas={"wisdom": +3},
            money_delta=-500,
            summary="You negotiated the dowry down to a smaller sum. Both families accepted the compromise.",
        ),
        EventChoice(
            key="refuse",
            label="Refuse on principle",
            deltas={"conscience": +5, "happiness": -5, "wisdom": +2},
            summary="You refused. The match was called off and your family was disappointed.",
        ),
    ],
    max_lifetime=1,  # #52
)


BILINGUAL_SCHOOLING = _choice(
    key="bilingual_schooling",
    title="Bilingual schooling",
    category="education",
    description=(
        "Your parents have a choice: enroll you in the local-language primary school, "
        "or pay for the English-medium school where you'd learn the international "
        "lingua franca alongside the standard subjects."
    ),
    when=lambda c, co: (
        c.age == 6
        and co.primary_language not in {"English"}
        and co.region in {"Africa", "Asia"}
    ),
    chance=lambda c, co: 0.10,
    choices=[
        EventChoice(
            key="english",
            label="Choose the English-medium school",
            deltas={"intelligence": +2, "wisdom": +1},
            money_delta=-200,
            summary="You enrolled in the English-medium school. Years of bilingual study lie ahead.",
        ),
        EventChoice(
            key="local",
            label="Stay in the local-language school",
            deltas={"happiness": +2, "wisdom": +1},
            summary="You stayed at the local school. Your home language remained your strongest tongue.",
        ),
    ],
    max_lifetime=1,  # #52: a one-time enrollment decision
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
    max_lifetime=2,  # #52
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
    max_lifetime=3,  # #52
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
    cooldown_years=8,  # #52
)

HAJJ = _choice(
    key="hajj",
    title="Hajj pilgrimage",
    category="moral",
    description=(
        "You are old enough and able to undertake the Hajj — the pilgrimage to Mecca that "
        "every able Muslim is expected to make once in their life. The journey is expensive "
        "and physically demanding, but it carries profound religious meaning."
    ),
    when=lambda c, co: 25 <= c.age <= 60 and co.primary_religion == "Islam" and c.money >= 3000,
    chance=lambda c, co: 0.05,
    choices=[
        EventChoice(key="go", label="Make the pilgrimage",
                    deltas={"happiness": +12, "wisdom": +6, "conscience": +5, "endurance": -2, "health": -2},
                    money_delta=-3000,
                    summary="You completed the Hajj. The experience changed you."),
        EventChoice(key="defer", label="Defer for another year",
                    deltas={"happiness": -1},
                    summary="You decided to wait. There is always next year."),
    ],
    max_lifetime=1,  # #52: once-in-a-lifetime pilgrimage
)


VARANASI_PILGRIMAGE = _choice(
    key="varanasi_pilgrimage",
    title="Pilgrimage to Varanasi",
    category="moral",
    description=(
        "An elder in the family suggests a pilgrimage to Varanasi to bathe in the Ganges. "
        "Many Hindus believe a visit cleanses the soul and prepares one for moksha."
    ),
    when=lambda c, co: c.age >= 30 and co.primary_religion == "Hinduism",
    chance=lambda c, co: 0.04,
    choices=[
        EventChoice(key="go", label="Make the pilgrimage",
                    deltas={"happiness": +8, "wisdom": +4, "conscience": +3},
                    money_delta=-200,
                    summary="You bathed in the Ganges at Varanasi. You feel renewed."),
        EventChoice(key="decline", label="Stay home",
                    deltas={"happiness": -1},
                    summary="You did not make the trip this year."),
    ],
    max_lifetime=1,  # #52
)


MONASTIC_RETREAT = _choice(
    key="monastic_retreat",
    title="Temporary ordination",
    category="moral",
    description=(
        "Friends invite you to ordain temporarily as a monk and spend several months at a "
        "forest monastery — a tradition many young Buddhist men in your country observe at "
        "least once."
    ),
    when=lambda c, co: 18 <= c.age <= 30 and co.primary_religion == "Buddhism" and c.gender == Gender.MALE,
    chance=lambda c, co: 0.06,
    choices=[
        EventChoice(key="ordain", label="Take robes",
                    deltas={"happiness": +6, "wisdom": +8, "conscience": +5, "intelligence": +2},
                    summary="You spent the rains retreat at the monastery. You return calmer and more disciplined."),
        EventChoice(key="decline", label="Stay in the world",
                    deltas={"happiness": -1},
                    summary="You did not ordain this time."),
    ],
    max_lifetime=2,  # #52
)


def _accept_proposal(c, ctx=None):
    """#50: roll a full Spouse via relationships.roll_spouse, mark
    them as married this year, and apply joined wealth. Used by both
    LOVE_MARRIAGE and ARRANGED_MARRIAGE side_effects.

    Accepts an optional ctx dict with 'year', 'country', 'rng' so the
    roll is deterministic + country-aware. Falls back to a fresh
    unseeded Random if called without ctx (legacy callers / tests)."""
    from . import relationships
    if ctx is None:
        from . import world
        import random as _random
        country = world.get_country(c.country_code)
        rng = _random.Random()
        year = 0
    else:
        country = ctx["country"]
        rng = ctx["rng"]
        year = ctx["year"]
    spouse = relationships.roll_spouse(c, country, year, rng)
    relationships.marry(c, spouse, year)


ARRANGED_MARRIAGE = _choice(
    key="arranged_marriage",
    title="An arranged match",
    category="life",
    description=(
        "Your family has identified a suitable partner and would like to arrange the match. "
        "This is the customary path in your community, but the choice is still yours."
    ),
    when=lambda c, co: 18 <= c.age <= 28 and not c.married and co.primary_religion in ("Hinduism", "Islam") and co.gdp_pc < 25000,
    chance=lambda c, co: 0.20,
    choices=[
        EventChoice(key="accept", label="Accept the match",
                    deltas={"happiness": +4, "conscience": +2},
                    summary="You agreed to the arranged marriage. The wedding will be next year.",
                    side_effect=_accept_proposal),  # #50: was missing — latent bug
        EventChoice(key="defer", label="Ask for more time",
                    deltas={"happiness": -2, "wisdom": +1},
                    summary="You asked your family to wait. They were disappointed but understood."),
        EventChoice(key="refuse", label="Refuse the match",
                    deltas={"happiness": +1, "conscience": -3, "wisdom": +2},
                    summary="You refused. There was a long argument, but you held firm."),
    ],
    max_lifetime=1,  # #52: belt-and-suspenders; gated by `not married` anyway
)


CONVERSION_OFFER = _choice(
    key="conversion_offer",
    title="An offer of a different faith",
    category="moral",
    description=(
        "A friend invites you to convert to their religion. They speak warmly about it and "
        "promise to introduce you to their community."
    ),
    when=lambda c, co: c.age >= 16,
    chance=lambda c, co: 0.02,
    choices=[
        EventChoice(key="convert", label="Convert",
                    deltas={"happiness": +3, "wisdom": +2, "conscience": +1},
                    summary="You converted. Your old community was sad but you found new friends."),
        EventChoice(key="decline_polite", label="Politely decline",
                    deltas={"conscience": +1},
                    summary="You thanked your friend but kept your own faith."),
        EventChoice(key="reject", label="Reject angrily",
                    deltas={"happiness": -3, "conscience": -2, "appearance": -1},
                    summary="You snapped at your friend. The friendship is strained."),
    ],
    cooldown_years=10,  # #52
)


def _education_university(c):
    # Stay in school. Bump education to SECONDARY immediately — the
    # event fires at age 17 as the "finish secondary + decide next
    # step" moment, so the player has *just* completed secondary by
    # picking this. Bumping here also disarms the age-18 auto-branch
    # in education.update_education which would otherwise re-roll
    # the track and clobber the player's choice.
    c.in_school = True
    c.school_track = "university"
    c.education = EducationLevel.SECONDARY


def _education_vocational(c):
    # Enter a 2-year vocational program. Mirror university entry:
    # stay in school, set school_track, bump to SECONDARY (the
    # credential earned by reaching this branching moment). The
    # VOCATIONAL credential is granted at age 20 by the
    # vocational-completion branch in education.update_education.
    # Previously this set in_school=False and education=VOCATIONAL
    # immediately, lying to the player about being in school.
    c.in_school = True
    c.school_track = "vocational"
    c.education = EducationLevel.SECONDARY


def _education_dropout(c):
    # Leave school after secondary, having earned the secondary
    # credential. Same education bump as the university/vocational
    # paths since this fires at the same end-of-secondary moment.
    c.in_school = False
    c.school_track = None
    c.education = EducationLevel.SECONDARY


def _set_vocation(field):
    """Build a side-effect that sets character.vocation_field. Used by
    the UNIVERSITY_MAJOR / VOCATIONAL_TRACK choices below to constrain
    careers.assign_job to the chosen category (#51)."""
    def _do(c):
        c.vocation_field = field
    return _do


LOVE_MARRIAGE = _choice(
    key="love_marriage",
    title="A proposal",
    category="life",
    description=(
        "You and someone you've been seeing have grown serious. They want to know "
        "if you see a future together. The choice is yours — and the answer "
        "matters."
    ),
    when=lambda c, co: (
        24 <= c.age <= 38
        and not c.married
        # Skip in countries where the arranged-marriage choice already
        # offers this same decision in a different cultural frame.
        and not (co.primary_religion in ("Hinduism", "Islam") and co.gdp_pc < 25000)
    ),
    chance=lambda c, co: 0.10 + c.attributes.appearance * 0.001,
    choices=[
        EventChoice(
            key="accept",
            label="Say yes",
            deltas={"happiness": +12, "wisdom": +1},
            summary="You said yes. The wedding will be soon.",
            side_effect=_accept_proposal,
        ),
        EventChoice(
            key="decline",
            label="Decline",
            deltas={"happiness": -3, "wisdom": +1},
            summary="You declined. It was hard but it didn't feel right.",
        ),
        EventChoice(
            key="postpone",
            label="Ask for more time",
            deltas={"happiness": -1, "wisdom": +2},
            summary="You asked for more time. They agreed but you both felt the weight of it.",
        ),
    ],
    max_lifetime=1,  # #52
)


UNIVERSITY_MAJOR = _choice(
    key="university_major",
    title="Pick your major",
    category="education",
    description=(
        "You're heading into university. Time to choose what to study — your "
        "major will shape the kind of work you can do for the rest of your "
        "life. Pick a field that fits your strengths. When you graduate "
        "you'll start your career in this field."
    ),
    # Eligible across the whole university window (~age 18-21) so a
    # competing choice event preempting at age 18 doesn't permanently
    # lock the player out of picking a major.
    when=lambda c, co: (
        c.school_track == "university"
        and c.in_school
        and c.vocation_field is None
    ),
    chance=lambda c, co: 1.0,
    choices=[
        EventChoice(
            key="medical",
            label="Medicine — doctor, nurse, lab tech",
            deltas={"intelligence": +2, "wisdom": +1},
            summary="You enrolled in pre-med. The next 6+ years will be intensive.",
            side_effect=_set_vocation("medical"),
        ),
        EventChoice(
            key="stem",
            label="Science & Engineering",
            deltas={"intelligence": +2, "wisdom": +1},
            summary="You picked an engineering / science track.",
            side_effect=_set_vocation("stem"),
        ),
        EventChoice(
            key="education",
            label="Education — teacher, professor",
            deltas={"wisdom": +2, "conscience": +1},
            summary="You're going to study education and become a teacher.",
            side_effect=_set_vocation("education"),
        ),
        EventChoice(
            key="government",
            label="Law & Public Service",
            deltas={"intelligence": +1, "conscience": +2},
            summary="You declared a pre-law / public administration major.",
            side_effect=_set_vocation("government"),
        ),
        EventChoice(
            key="business",
            label="Business & Management",
            deltas={"intelligence": +1, "wisdom": +1},
            summary="You picked business as your major.",
            side_effect=_set_vocation("business"),
        ),
        EventChoice(
            key="arts",
            label="Arts & Humanities",
            deltas={"artistic": +3, "wisdom": +2},
            summary="You picked an arts and humanities major.",
            side_effect=_set_vocation("arts"),
        ),
    ],
)


VOCATIONAL_TRACK = _choice(
    key="vocational_track",
    title="Pick your trade",
    category="education",
    description=(
        "You're starting vocational training. Time to pick a trade — your "
        "specialization decides which kind of skilled work you'll do for "
        "the rest of your career. When you graduate you'll begin work as "
        "an apprentice in this field."
    ),
    # Eligible across the whole vocational window (~age 18-19) so a
    # competing choice event preempting at age 18 doesn't permanently
    # lock the player out of picking a trade.
    when=lambda c, co: (
        c.school_track == "vocational"
        and c.in_school
        and c.vocation_field is None
    ),
    chance=lambda c, co: 1.0,
    choices=[
        EventChoice(
            key="trades",
            label="Skilled Trades — electrician, carpenter, mechanic",
            deltas={"strength": +2, "endurance": +1},
            summary="You started apprenticing in a skilled trade.",
            side_effect=_set_vocation("trades"),
        ),
        EventChoice(
            key="industrial",
            label="Industrial — plant operator",
            deltas={"strength": +1, "endurance": +2},
            summary="You enrolled in industrial operations training.",
            side_effect=_set_vocation("industrial"),
        ),
        EventChoice(
            key="medical",
            label="Healthcare — nursing, lab tech",
            deltas={"intelligence": +1, "conscience": +2},
            summary="You enrolled in a healthcare technician program.",
            side_effect=_set_vocation("medical"),
        ),
        EventChoice(
            key="police",
            label="Police & Security",
            deltas={"strength": +2, "conscience": +1},
            summary="You enrolled at the police academy.",
            side_effect=_set_vocation("police"),
        ),
        EventChoice(
            key="business",
            label="Business — sales, clerical",
            deltas={"intelligence": +1, "wisdom": +1},
            summary="You enrolled in a business / clerical training program.",
            side_effect=_set_vocation("business"),
        ),
        EventChoice(
            key="maritime",
            label="Maritime — sailor, ship's officer",
            deltas={"strength": +2, "endurance": +2},
            summary="You signed on as a deckhand to learn the trade.",
            side_effect=_set_vocation("maritime"),
        ),
    ],
)


EDUCATION_PATH = _choice(
    key="education_path",
    title="What's next after school?",
    category="education",
    description=(
        "You're nearing the end of secondary school. Your options for what comes "
        "next depend on your intelligence, your family's resources, and how much "
        "more time you want to spend in a classroom. The choice will shape your "
        "career — and what salary range you can reach."
    ),
    when=lambda c, co: (
        c.age == 17
        and c.in_school
        and c.education == EducationLevel.PRIMARY
    ),
    chance=lambda c, co: 1.0,  # always offer when eligible
    choices=[
        EventChoice(
            key="university",
            label="Apply to university",
            deltas={"intelligence": +1, "wisdom": +1},
            summary=(
                "You decided to aim for university. The next several years will "
                "be intensive but the doors it opens are wide."
            ),
            side_effect=_education_university,
        ),
        EventChoice(
            key="vocational",
            label="Vocational training",
            deltas={"wisdom": +2, "strength": +1},
            summary=(
                "You enrolled in a vocational program — a faster path to a paying "
                "trade than university."
            ),
            side_effect=_education_vocational,
        ),
        EventChoice(
            key="dropout",
            label="Drop out and start working",
            deltas={"wisdom": +1, "happiness": +2},
            summary=(
                "You left school to enter the workforce immediately. Less debt, "
                "fewer doors — but ready to earn now."
            ),
            side_effect=_education_dropout,
        ),
    ],
)


RELIGIOUS_SCHOOL = _choice(
    key="religious_school",
    title="A place at religious school",
    category="education",
    description=(
        "Your family is offered a place for you at a respected religious school. The "
        "instruction is rigorous and centers on scripture and tradition."
    ),
    when=lambda c, co: 8 <= c.age <= 14 and co.primary_religion in ("Islam", "Christianity", "Hinduism", "Buddhism", "Judaism"),
    chance=lambda c, co: 0.08,
    choices=[
        EventChoice(key="attend", label="Attend the religious school",
                    deltas={"intelligence": +3, "wisdom": +5, "conscience": +4, "happiness": +2},
                    summary="You spent the year studying scripture. You feel grounded."),
        EventChoice(key="decline", label="Stay at the regular school",
                    deltas={"happiness": +1},
                    summary="You stuck with the regular school."),
    ],
    max_lifetime=1,  # #52
)


MILITARY_SERVICE = _choice(
    key="military_service",
    title="Military conscription",
    category="war",
    description="You have been called up for military service. Will you serve, or seek an exemption?",
    # Eligible if the country has formal conscription on the books OR is at
    # war OR has elevated war frequency. The conscription flag comes from
    # world.dat (#17) and supersedes the war_freq heuristic for countries
    # like Israel/Switzerland that conscript in peacetime.
    when=lambda c, co: (
        18 <= c.age <= 22
        and c.gender == Gender.MALE
        and (co.military_conscription or co.at_war or co.war_freq > 0.01)
    ),
    chance=lambda c, co: 0.6 if co.military_conscription else 0.4,
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
    cooldown_years=4,  # #52: a draft tour, then potential recall
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
        # Active wars (binary AtWar flag, #17) lift the per-year war event
        # probability to a minimum of 15% so countries flagged at war by the
        # 2007 binary feel materially different from peacetime ones.
        chance=lambda c, co: max(co.war_freq, 0.15) if co.at_war else co.war_freq,
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
        cooldown_years=4,  # #52
    ),
    _passive(
        "artistic_growth", "Artistic interest", "life",
        "You explored your creativity.",
        when=lambda c, co: 5 <= c.age <= 30,
        chance=lambda c, co: 0.15,
        apply=_apply_artistic_growth,
        cooldown_years=4,  # #52
    ),
    _passive(
        "musical_growth", "Musical interest", "life",
        "You picked up an instrument.",
        when=lambda c, co: 6 <= c.age <= 35,
        chance=lambda c, co: 0.12,
        apply=_apply_musical_growth,
        cooldown_years=4,  # #52
    ),

    # --- Social ---
    _passive(
        "made_friend", "New friendship", "life",
        "A new friendship blossoms.",
        when=lambda c, co: c.age >= 4,
        chance=lambda c, co: 0.18 + c.attributes.appearance * 0.001,
        apply=_apply_friendship,
        cooldown_years=5,  # #52: a new close friend every ~5 years
    ),
    _passive(
        "lonely_year", "A lonely year", "life",
        "You felt very alone.",
        when=lambda c, co: c.age >= 10,
        chance=lambda c, co: 0.10,
        apply=_apply_lonely,
        cooldown_years=3,  # #52
    ),

    # --- Finance / career ---
    _passive(
        "inheritance", "Inheritance", "finance",
        "You receive an inheritance.",
        when=lambda c, co: c.age >= 25,
        chance=lambda c, co: 0.015,
        apply=_apply_inheritance,
        cooldown_years=10,  # #52: rare windfall
    ),
    _passive(
        "promotion", "Career promotion", "finance",
        "You are promoted at work.",
        when=lambda c, co: c.job is not None and c.age >= 22,
        chance=lambda c, co: 0.12 + c.attributes.intelligence * 0.001,
        apply=_apply_promotion,
        cooldown_years=5,  # #52
    ),

    # --- Family ---
    _passive(
        "had_child", "A new child", "life",
        "You and your spouse had a child.",
        when=lambda c, co: c.married and c.age <= 45 and len(c.children) < 5,
        chance=lambda c, co: 0.18,
        apply=_apply_pregnancy,
        cooldown_years=2,  # #52: not biologically every year
    ),

    # --- Civic ---
    _passive(
        "civic_engagement", "Civic engagement", "moral",
        "You participated in your community.",
        when=lambda c, co: c.age >= 16,
        chance=lambda c, co: 0.08 + c.attributes.conscience * 0.001,
        apply=_apply_civic_engagement,
        cooldown_years=4,  # #52
    ),
    _passive(
        "village_harvest", "Village harvest", "life",
        "You helped bring in the harvest.",
        when=lambda c, co: not c.is_urban and 8 <= c.age <= 60,
        chance=lambda c, co: 0.20,
        apply=_apply_village_harvest,
        # cooldown=0: annual rural rhythm
    ),
    _passive(
        "witnessed_corruption", "Witnessed corruption", "moral",
        "You witnessed local corruption.",
        when=lambda c, co: c.age >= 16 and co.corruption > 40,
        # Urban characters interact with bureaucracy more frequently and
        # see corruption first-hand at much higher rates than rural villagers.
        chance=lambda c, co: (co.corruption / 1500) * (1.8 if c.is_urban else 0.5),
        apply=_apply_corruption_witnessed,
        cooldown_years=6,  # #52
    ),

    # --- Religion- and culture-specific passive events ---
    _passive(
        "christmas", "Christmas", "life",
        "A Christmas celebration with the family.",
        when=lambda c, co: c.age >= 3 and co.primary_religion == "Christianity",
        chance=lambda c, co: 0.85,
        apply=_apply_christmas,
    ),
    _passive(
        "easter", "Easter", "life",
        "Easter Sunday observances and family meal.",
        when=lambda c, co: c.age >= 5 and co.primary_religion == "Christianity",
        chance=lambda c, co: 0.65,
        apply=_apply_easter,
    ),
    _passive(
        "ramadan", "Ramadan", "life",
        "A month of fasting from dawn to sunset.",
        when=lambda c, co: c.age >= 10 and co.primary_religion == "Islam",
        chance=lambda c, co: 0.90,
        apply=_apply_ramadan,
    ),
    _passive(
        "eid_al_fitr", "Eid al-Fitr", "life",
        "Celebrating the end of Ramadan.",
        when=lambda c, co: c.age >= 5 and co.primary_religion == "Islam",
        chance=lambda c, co: 0.85,
        apply=_apply_eid,
    ),
    _passive(
        "diwali", "Diwali", "life",
        "The festival of lights.",
        when=lambda c, co: c.age >= 4 and co.primary_religion == "Hinduism",
        chance=lambda c, co: 0.85,
        apply=_apply_diwali,
    ),
    _passive(
        "vesak", "Vesak Day", "life",
        "Buddha's birthday observance at the temple.",
        when=lambda c, co: c.age >= 6 and co.primary_religion == "Buddhism",
        chance=lambda c, co: 0.70,
        apply=_apply_vesak,
    ),
    _passive(
        "passover", "Passover", "life",
        "A Passover Seder with family and friends.",
        when=lambda c, co: c.age >= 6 and co.primary_religion == "Judaism",
        chance=lambda c, co: 0.85,
        apply=_apply_passover,
    ),
    _passive(
        "yom_kippur", "Yom Kippur", "life",
        "A day of fasting and reflection.",
        when=lambda c, co: c.age >= 13 and co.primary_religion == "Judaism",
        chance=lambda c, co: 0.85,
        apply=_apply_yom_kippur,
    ),
    _passive(
        "ancestral_ceremony", "Ancestral ceremony", "life",
        "A community ancestral observance.",
        when=lambda c, co: c.age >= 6 and co.primary_religion in ("None", "Indigenous beliefs", "Shinto"),
        chance=lambda c, co: 0.40,
        apply=_apply_ancestral_ceremony,
    ),
    _passive(
        "baptism", "Baptism", "life",
        "Christian baptism ceremony.",
        when=lambda c, co: c.age == 1 and co.primary_religion == "Christianity",
        chance=lambda c, co: 0.70,
        apply=_apply_baptism,
        max_lifetime=1,  # #52
    ),
    _passive(
        "first_communion", "First Communion", "life",
        "Catholic First Communion.",
        when=lambda c, co: c.age == 8 and co.primary_religion == "Christianity",
        chance=lambda c, co: 0.50,
        apply=_apply_first_communion,
        max_lifetime=1,  # #52
    ),
    _passive(
        "sacred_thread", "Sacred thread ceremony", "life",
        "Hindu Upanayana ceremony.",
        when=lambda c, co: c.age in (8, 9, 10, 11, 12) and co.primary_religion == "Hinduism" and c.gender == Gender.MALE,
        chance=lambda c, co: 0.30,
        apply=_apply_sacred_thread,
        max_lifetime=1,  # #52
    ),
    _passive(
        "bar_mitzvah", "Bar/Bat Mitzvah", "life",
        "Coming-of-age in the Jewish tradition.",
        when=lambda c, co: c.age in (12, 13) and co.primary_religion == "Judaism",
        chance=lambda c, co: 0.85,
        apply=_apply_bar_mitzvah,
        max_lifetime=1,  # #52
    ),

    # --- Language- and region-gated cultural events (#16) ---
    _passive(
        "cricket_match", "Cricket match", "life",
        "A weekend cricket match.",
        # Cricket is dominant where any cricket-playing language is the primary
        # tongue (English in former British colonies, Hindi/Urdu in South Asia,
        # Bengali in Bangladesh, Sinhala in Sri Lanka).
        when=lambda c, co: 8 <= c.age <= 35 and co.primary_language in _CRICKET_LANGUAGES,
        chance=lambda c, co: 0.18,
        apply=_apply_cricket_match,
    ),
    _passive(
        "baseball_youth", "Baseball pickup game", "life",
        "Pickup baseball with neighborhood kids.",
        when=lambda c, co: 6 <= c.age <= 22 and (
            co.primary_language == "Japanese"
            or co.primary_language == "Korean"
            or co.region in _BASEBALL_REGIONS
        ),
        chance=lambda c, co: 0.18,
        apply=_apply_baseball_youth,
    ),
    _passive(
        "quinceanera", "Quinceañera", "life",
        "A 15th-birthday quinceañera celebration.",
        when=lambda c, co: c.age == 15 and c.gender == Gender.FEMALE and co.primary_language == "Spanish",
        chance=lambda c, co: 0.55,
        apply=_apply_quinceanera,
        max_lifetime=1,  # #52
    ),
    _passive(
        "seijin_shiki", "Seijin no Hi", "life",
        "Coming of Age Day ceremony in Japan.",
        when=lambda c, co: c.age == 20 and co.primary_language == "Japanese",
        chance=lambda c, co: 0.85,
        apply=_apply_seijin_shiki,
        max_lifetime=1,  # #52
    ),
    _passive(
        "tea_ceremony", "Tea ceremony lesson", "life",
        "An introduction to the etiquette of the tea ceremony.",
        when=lambda c, co: 10 <= c.age <= 25 and co.primary_language in {"Japanese", "Mandarin", "Cantonese"},
        chance=lambda c, co: 0.10,
        apply=_apply_tea_ceremony,
    ),
    _passive(
        "vegetarian_household", "Vegetarian household", "life",
        "Your family follows a vegetarian diet.",
        when=lambda c, co: c.age == 5 and co.primary_language == "Hindi",
        chance=lambda c, co: 0.40,
        apply=_apply_vegetarian_household,
        max_lifetime=1,  # #52
    ),
    _passive(
        "fish_heavy_diet", "Coastal fish diet", "life",
        "A coastal year of fresh seafood.",
        when=lambda c, co: 8 <= c.age <= 60 and (
            co.primary_language in {"Japanese", "Norwegian", "Icelandic", "Portuguese"}
        ),
        chance=lambda c, co: 0.20,
        apply=_apply_fish_heavy_diet,
    ),

    # ====================================================================
    # Slice-of-life content drop (#52). Each year of a simulated life
    # should surface something new — these ~200 events fill the long
    # tail so a 60-year run isn't dominated by the same handful of
    # firings. Most use the _simple_passive helper which handles the
    # boilerplate of attribute deltas + history line + optional money.
    # All have cooldowns sized so they don't dominate either.
    # ====================================================================

    # --- Hobbies (cooldown 8) ------------------------------------------
    _simple_passive(
        "hobby_gardening", "Picked up gardening",
        "You started a small garden — tomatoes, herbs, the basics.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.06,
        cooldown_years=8, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_cooking", "Learned to cook",
        "You spent the year teaching yourself to cook properly.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.07,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_writing_novel", "Started writing a novel",
        "You started writing a novel in your spare hours.",
        when=lambda c, co: c.age >= 20, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"artistic": +3, "wisdom": +2, "happiness": +1},
    ),
    _simple_passive(
        "hobby_photography", "Took up photography",
        "You bought a camera and started photographing everything in sight.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"artistic": +2, "happiness": +2},
    ),
    _simple_passive(
        "hobby_band", "Joined a band",
        "You joined a band and started rehearsing on weekends.",
        when=lambda c, co: 14 <= c.age <= 35 and c.is_urban,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"musical": +3, "happiness": +3},
    ),
    _simple_passive(
        "hobby_painting", "Started painting",
        "You started painting and the canvases piled up in your spare room.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"artistic": +3, "happiness": +2},
    ),
    _simple_passive(
        "hobby_woodworking", "Took up woodworking",
        "You set up a small workshop and started building furniture.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"strength": +1, "wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "hobby_knitting", "Took up knitting",
        "You learned to knit. Scarves and sweaters became your meditation.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_baking_bread", "Started baking bread",
        "You became the household bread baker — sourdough, rye, focaccia.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_brewing_beer", "Started home-brewing",
        "You set up a home-brewing kit. The first batch was dreadful.",
        when=lambda c, co: c.age >= 21, chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_model_building", "Started building models",
        "You took up scale-model building — kits, paint, tiny brushes.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +2, "intelligence": +1},
    ),
    _simple_passive(
        "hobby_board_games", "Joined a board game group",
        "You started attending a weekly board game group at the local cafe.",
        when=lambda c, co: c.age >= 14 and c.is_urban,
        chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +3, "intelligence": +1},
    ),
    _simple_passive(
        "hobby_tabletop_rpg", "Joined a tabletop RPG group",
        "You started running characters in a long-form tabletop RPG campaign.",
        when=lambda c, co: 14 <= c.age <= 50 and c.is_urban,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +3, "intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_hiking", "Took up hiking",
        "You started hiking on weekends and explored every trail you could find.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.06,
        cooldown_years=8, deltas={"endurance": +3, "health": +2, "happiness": +2},
    ),
    _simple_passive(
        "hobby_fishing", "Took up fishing",
        "You started fishing on quiet weekends. Mostly catch and release.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_hunting", "Took up hunting",
        "You learned to hunt with a relative who'd been at it for years.",
        when=lambda c, co: c.age >= 16 and not c.is_urban,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"strength": +2, "endurance": +2, "happiness": +1},
    ),
    _simple_passive(
        "hobby_birdwatching", "Took up birdwatching",
        "You bought a pair of binoculars and started keeping a bird life list.",
        when=lambda c, co: c.age >= 20, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_cycling", "Took up cycling",
        "You bought a road bike and started riding long routes on weekends.",
        when=lambda c, co: 14 <= c.age <= 70, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"endurance": +3, "health": +2, "happiness": +2},
    ),
    _simple_passive(
        "hobby_climbing", "Took up climbing",
        "You started climbing — first the local gym, then real rock.",
        when=lambda c, co: 16 <= c.age <= 45 and c.is_urban,
        chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"strength": +3, "endurance": +2, "happiness": +2},
    ),
    _simple_passive(
        "hobby_podcast", "Started a podcast",
        "You bought a microphone and started recording episodes about your interests.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "hobby_furniture_restoration", "Restored old furniture",
        "You started rescuing old furniture and refinishing it in the garage.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1, "strength": +1},
    ),
    _simple_passive(
        "hobby_beekeeping", "Started keeping bees",
        "You set up a beehive in the back garden and learned the rhythms of the colony.",
        when=lambda c, co: c.age >= 30 and not c.is_urban,
        chance=lambda c, co: 0.02,
        cooldown_years=8, deltas={"happiness": +3, "wisdom": +2},
    ),
    _simple_passive(
        "hobby_bonsai", "Took up bonsai",
        "You started cultivating bonsai trees. Patience as a craft.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.02,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +3},
    ),
    _simple_passive(
        "hobby_calligraphy", "Took up calligraphy",
        "You started practicing calligraphy in the evenings.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"artistic": +2, "wisdom": +2},
    ),
    _simple_passive(
        "hobby_blogging", "Started a blog",
        "You started a personal blog and updated it most weekends.",
        when=lambda c, co: c.age >= 16 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"wisdom": +2, "happiness": +1},
    ),

    # --- Travel (cooldown 6, varied gates) -----------------------------
    _simple_passive(
        "travel_domestic_vacation", "Took a domestic vacation",
        "You took a vacation to another part of the country.",
        when=lambda c, co: c.age >= 18 and (c.money + c.family_wealth) > 5000,
        chance=lambda c, co: 0.10,
        cooldown_years=6, deltas={"happiness": +5, "wisdom": +1},
        money_delta=-800,
    ),
    _simple_passive(
        "travel_first_flight", "Took your first flight",
        "You took your first ever airplane flight. The window seat was unforgettable.",
        when=lambda c, co: c.age >= 14 and (c.money + c.family_wealth) > 1500,
        chance=lambda c, co: 0.10,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +6, "wisdom": +2},
    ),
    _simple_passive(
        "travel_business_trip", "Took a business trip",
        "Work sent you on a business trip to a city you'd never visited.",
        when=lambda c, co: c.age >= 25 and c.job is not None,
        chance=lambda c, co: 0.08,
        cooldown_years=5, deltas={"happiness": +2, "wisdom": +2},
    ),
    _simple_passive(
        "travel_road_trip", "Took a road trip",
        "You took a long road trip — windows down, music up.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 8000,
        chance=lambda c, co: 0.07,
        cooldown_years=6, deltas={"happiness": +5, "wisdom": +1},
        money_delta=-400,
    ),
    _simple_passive(
        "travel_beach_holiday", "Took a beach holiday",
        "You spent a week at the beach. Sun, sand, the works.",
        when=lambda c, co: c.age >= 18 and (c.money + c.family_wealth) > 3000,
        chance=lambda c, co: 0.08,
        cooldown_years=6, deltas={"happiness": +6, "health": +1},
        money_delta=-1200,
    ),
    _simple_passive(
        "travel_mountain_trip", "Took a mountain trip",
        "You spent a week up in the mountains, hiking and breathing thin air.",
        when=lambda c, co: c.age >= 16 and (c.money + c.family_wealth) > 2000,
        chance=lambda c, co: 0.06,
        cooldown_years=6, deltas={"happiness": +4, "endurance": +2},
        money_delta=-700,
    ),
    _simple_passive(
        "travel_weekend_away", "Took a weekend away",
        "You took a quick weekend trip just to clear your head.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"happiness": +3},
        money_delta=-300,
    ),
    _simple_passive(
        "travel_visited_family_abroad", "Visited family abroad",
        "You traveled to visit relatives in another country.",
        when=lambda c, co: c.age >= 14 and (c.money + c.family_wealth) > 2500,
        chance=lambda c, co: 0.05,
        cooldown_years=6, deltas={"happiness": +5, "wisdom": +2},
        money_delta=-1500,
    ),
    _simple_passive(
        "travel_pilgrimage_capital", "Pilgrimage to the capital",
        "You traveled to the country's capital for a religious gathering.",
        when=lambda c, co: c.age >= 20 and co.primary_religion != "None",
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +4, "conscience": +2, "wisdom": +2},
    ),
    _simple_passive(
        "travel_train_journey", "Took a long train journey",
        "You took an overnight train across the country. The landscape rolled past for hours.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.06,
        cooldown_years=6, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "travel_camping_trip", "Went camping",
        "You spent a long weekend camping in the woods.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.07,
        cooldown_years=5, deltas={"happiness": +3, "endurance": +1},
    ),
    _simple_passive(
        "travel_cruise", "Took a cruise",
        "You went on a cruise — buffets, decks, port stops.",
        when=lambda c, co: c.age >= 30 and (c.money + c.family_wealth) > 5000,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +5},
        money_delta=-2500,
    ),
    _simple_passive(
        "travel_backpacking", "Went backpacking",
        "You spent weeks backpacking through unfamiliar countries.",
        when=lambda c, co: 18 <= c.age <= 35 and (c.money + c.family_wealth) > 2000,
        chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +6, "wisdom": +4, "endurance": +2},
        money_delta=-2000,
    ),
    _simple_passive(
        "travel_day_trip", "Took a day trip",
        "You spent a Saturday on a day trip to a neighboring town.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +2},
    ),
    _simple_passive(
        "travel_conference", "Attended a conference abroad",
        "Your work sent you to an international conference.",
        when=lambda c, co: c.age >= 28 and c.job is not None and (c.salary or 0) > 30000,
        chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"happiness": +3, "wisdom": +3, "intelligence": +1},
    ),
    _simple_passive(
        "travel_destination_wedding", "Attended a destination wedding",
        "You traveled for a friend's destination wedding.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": +4},
        money_delta=-800,
    ),
    _simple_passive(
        "travel_honeymoon", "Went on your honeymoon",
        "You and your spouse took a honeymoon — your first big trip together.",
        when=lambda c, co: c.married and c.age >= 18,
        chance=lambda c, co: 0.40,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +8, "wisdom": +2},
        money_delta=-2000,
    ),
    _simple_passive(
        "travel_eco_tourism", "Took an eco-tourism trip",
        "You took an eco-tourism trip — rainforests, reefs, distant national parks.",
        when=lambda c, co: c.age >= 25 and (c.money + c.family_wealth) > 4000,
        chance=lambda c, co: 0.03,
        cooldown_years=8, deltas={"happiness": +5, "wisdom": +3, "conscience": +2},
        money_delta=-2200,
    ),
    _simple_passive(
        "travel_solo_trip", "Took a solo trip",
        "You took a solo trip — just you, a backpack, and an open itinerary.",
        when=lambda c, co: 20 <= c.age <= 50, chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": +4, "wisdom": +3},
    ),
    _simple_passive(
        "travel_visited_birthplace", "Visited your birthplace",
        "You traveled back to where you were born and walked old streets.",
        when=lambda c, co: c.age >= 35, chance=lambda c, co: 0.03,
        cooldown_years=10, deltas={"happiness": +3, "wisdom": +3},
    ),

    # --- Learning (cooldown 6) -----------------------------------------
    _simple_passive(
        "learn_transformative_book", "Read a transformative book",
        "You read a book that changed how you see the world.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"wisdom": +3, "intelligence": +1, "happiness": +1},
    ),
    _simple_passive(
        "learn_online_course", "Took an online course",
        "You signed up for an online course and actually finished it.",
        when=lambda c, co: c.age >= 14 and co.gdp_pc > 3000,
        chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"intelligence": +2, "wisdom": +1},
    ),
    _simple_passive(
        "learn_new_language", "Learned a new language",
        "You spent the year learning a new language. Slow but steady.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.05,
        cooldown_years=10, deltas={"intelligence": +3, "wisdom": +1, "happiness": +1},
    ),
    _simple_passive(
        "learn_instrument", "Learned an instrument",
        "You picked up an instrument and started practicing every day.",
        when=lambda c, co: c.age >= 8, chance=lambda c, co: 0.06,
        cooldown_years=8, deltas={"musical": +3, "happiness": +1},
    ),
    _simple_passive(
        "learn_workshop", "Attended a workshop",
        "You attended a weekend workshop on something you'd been curious about.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "learn_lecture", "Attended a public lecture",
        "You went to a public lecture by a visiting expert.",
        when=lambda c, co: c.age >= 16 and c.is_urban,
        chance=lambda c, co: 0.06,
        cooldown_years=4, deltas={"intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "learn_book_club", "Joined a book club",
        "You joined a monthly book club and rediscovered reading widely.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.05,
        cooldown_years=6, deltas={"wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "learn_documentary", "Watched a documentary series",
        "You binged a documentary series and couldn't stop talking about it.",
        when=lambda c, co: c.age >= 12 and co.gdp_pc > 3000,
        chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"wisdom": +1, "happiness": +1},
    ),
    _simple_passive(
        "learn_study_group", "Joined a study group",
        "You joined a study group focused on a topic you wanted to master.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"intelligence": +2, "wisdom": +1},
    ),
    _simple_passive(
        "learn_certification", "Earned a certification",
        "You studied for and earned a professional certification.",
        when=lambda c, co: c.age >= 22 and c.job is not None,
        chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"intelligence": +2, "wisdom": +1, "happiness": +2},
    ),
    _simple_passive(
        "learn_library_habit", "Got into the habit of the library",
        "You started visiting the public library every week.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.07,
        cooldown_years=8, deltas={"wisdom": +2, "intelligence": +1},
    ),
    _simple_passive(
        "learn_museum", "Got a museum membership",
        "You bought a museum membership and made it a monthly habit.",
        when=lambda c, co: c.age >= 18 and c.is_urban,
        chance=lambda c, co: 0.05,
        cooldown_years=6, deltas={"wisdom": +2, "happiness": +1},
    ),
    _simple_passive(
        "learn_tutored_kid", "Tutored a child",
        "You volunteered as a tutor for a kid who needed help with school.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"conscience": +3, "wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "learn_to_code", "Learned to code",
        "You spent the year teaching yourself to program.",
        when=lambda c, co: c.age >= 14 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.04,
        cooldown_years=10, deltas={"intelligence": +3, "wisdom": +1},
    ),
    _simple_passive(
        "learn_mentored", "Mentored someone younger",
        "You took a younger colleague under your wing and showed them the ropes.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"conscience": +2, "wisdom": +2, "happiness": +2},
    ),

    # --- Family (cooldown 4-10) ----------------------------------------
    _simple_passive(
        "family_reunion", "Family reunion",
        "Your extended family gathered for a reunion. Old jokes and new babies.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "family_sibling_visit", "Sibling visited",
        "A sibling came to stay for a few days. You stayed up too late catching up.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +3},
    ),
    _simple_passive(
        "family_parent_moves_in", "Parent moved in",
        "An aging parent moved in with you for a while.",
        when=lambda c, co: 35 <= c.age <= 65, chance=lambda c, co: 0.04,
        cooldown_years=10, deltas={"happiness": -1, "conscience": +3, "wisdom": +1},
    ),
    _simple_passive(
        "family_grandparent_visited", "Grandparent visited",
        "A grandparent visited for a long weekend. The stories were the best part.",
        when=lambda c, co: c.age <= 30, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": +3, "wisdom": +2},
    ),
    _simple_passive(
        "family_vacation", "Family vacation",
        "The whole family took a trip together. Some parts were great, some were chaos.",
        when=lambda c, co: c.age >= 6 and (c.money + c.family_wealth) > 1500,
        chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"happiness": +4},
        money_delta=-600,
    ),
    _simple_passive(
        "family_business_inherit", "Inherited a small family business",
        "You inherited a small family business — and the headaches that came with it.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.01,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +2, "wisdom": +2},
        money_delta=15000,
    ),
    _simple_passive(
        "family_parents_birthday", "Parent's birthday celebration",
        "You hosted a milestone birthday party for one of your parents.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"happiness": +3, "conscience": +1},
    ),
    _simple_passive(
        "family_first_nephew_niece", "First nephew or niece",
        "Your sibling had a baby — your first nephew or niece. You held the kid for an hour.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.04,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +5, "conscience": +1},
    ),
    _simple_passive(
        "family_argument", "Family argument",
        "You had a serious argument with a family member. It took weeks to recover.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.08,
        cooldown_years=5, deltas={"happiness": -3, "wisdom": +1},
    ),
    _simple_passive(
        "family_forgiveness", "Made amends with family",
        "You finally patched things up with a family member you'd been distant from.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +4, "wisdom": +2, "conscience": +2},
    ),
    _simple_passive(
        "family_ancestral_home", "Visited the ancestral home",
        "You traveled to the village your family came from generations ago.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.03,
        cooldown_years=10, deltas={"happiness": +3, "wisdom": +3},
    ),
    _simple_passive(
        "family_sibling_wedding", "Attended a sibling's wedding",
        "Your sibling got married. You gave a speech that mostly landed.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.04,
        cooldown_years=0, max_lifetime=2,
        deltas={"happiness": +4},
    ),
    _simple_passive(
        "family_sunday_dinner", "Started a Sunday dinner tradition",
        "You started hosting Sunday dinners for the family. It became a fixture.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.04,
        cooldown_years=10, deltas={"happiness": +3, "conscience": +1},
    ),
    _simple_passive(
        "family_lost_touch_sibling", "Lost touch with a sibling",
        "You and a sibling drifted apart. The calls just stopped.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.04,
        cooldown_years=10, deltas={"happiness": -3, "wisdom": +1},
    ),
    _simple_passive(
        "family_reconnected_cousin", "Reconnected with a cousin",
        "You reconnected with a cousin you hadn't spoken to in years.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +3},
    ),
    _simple_passive(
        "family_secret_revealed", "Family secret revealed",
        "An old family secret came out. It changed how you saw a few people.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.02,
        cooldown_years=10, deltas={"wisdom": +3, "happiness": -1},
    ),
    _simple_passive(
        "family_parent_retired", "A parent retired",
        "One of your parents retired. The next time you visited they seemed lighter.",
        when=lambda c, co: 25 <= c.age <= 60, chance=lambda c, co: 0.06,
        cooldown_years=0, max_lifetime=2,
        deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "family_inherited_keepsake", "Inherited a keepsake",
        "You inherited a small keepsake from a relative — nothing valuable, but precious.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "family_photo_album", "Made a family photo album",
        "You spent a weekend assembling a family photo album. The memories piled up.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +3, "wisdom": +1},
    ),

    # --- Health behavior (cooldown 5) ----------------------------------
    _simple_passive(
        "health_started_exercising", "Started exercising regularly",
        "You started a real exercise routine and stuck with it for a year.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.10,
        cooldown_years=5, deltas={"endurance": +3, "health": +3, "happiness": +2},
    ),
    _simple_passive(
        "health_quit_smoking", "Quit smoking",
        "You quit smoking. The first month was hell.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.04,
        cooldown_years=0, max_lifetime=1,
        deltas={"health": +5, "happiness": +3, "wisdom": +2},
    ),
    _simple_passive(
        "health_joined_gym", "Joined a gym",
        "You signed up at a gym and actually went.",
        when=lambda c, co: c.age >= 16 and c.is_urban,
        chance=lambda c, co: 0.08,
        cooldown_years=5, deltas={"strength": +2, "endurance": +2, "health": +1},
        money_delta=-300,
    ),
    _simple_passive(
        "health_meditation", "Learned to meditate",
        "You took up meditation. It quieted things down.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"wisdom": +2, "happiness": +3},
    ),
    _simple_passive(
        "health_diet", "Started a new diet",
        "You overhauled your diet and stuck to it.",
        when=lambda c, co: c.age >= 20, chance=lambda c, co: 0.07,
        cooldown_years=5, deltas={"health": +2, "happiness": +1},
    ),
    _simple_passive(
        "health_yoga", "Took up yoga",
        "You took up yoga and found a class that didn't intimidate you.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"endurance": +2, "happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "health_walking_habit", "Built a walking habit",
        "You started walking 5 km every morning. The neighborhood opened up.",
        when=lambda c, co: c.age >= 30, chance=lambda c, co: 0.07,
        cooldown_years=5, deltas={"endurance": +2, "health": +2, "happiness": +2},
    ),
    _simple_passive(
        "health_bike_commute", "Started bike commuting",
        "You started biking to work instead of driving or taking the bus.",
        when=lambda c, co: c.age >= 22 and c.job is not None and c.is_urban,
        chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"endurance": +2, "health": +2, "happiness": +1},
    ),
    _simple_passive(
        "health_dental_work", "Had major dental work",
        "You had a stretch of expensive dental work. Worth it but rough.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"health": +2, "happiness": +1},
        money_delta=-1500,
    ),
    _simple_passive(
        "health_doctor_visits", "Got serious about doctor visits",
        "You started actually going to your annual checkups.",
        when=lambda c, co: c.age >= 35, chance=lambda c, co: 0.07,
        cooldown_years=6, deltas={"health": +2, "wisdom": +1},
    ),
    _simple_passive(
        "health_therapy", "Started therapy",
        "You started seeing a therapist. It took a while to feel like progress.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"happiness": +3, "wisdom": +3},
    ),
    _simple_passive(
        "health_wellness_retreat", "Went on a wellness retreat",
        "You spent a long weekend at a wellness retreat. You came back centered.",
        when=lambda c, co: c.age >= 25 and (c.money + c.family_wealth) > 5000,
        chance=lambda c, co: 0.03,
        cooldown_years=5, deltas={"happiness": +4, "wisdom": +2},
        money_delta=-1000,
    ),
    _simple_passive(
        "health_5k", "Ran a 5k",
        "You trained for and finished your first 5k race.",
        when=lambda c, co: 14 <= c.age <= 65, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"endurance": +3, "health": +2, "happiness": +3},
    ),
    _simple_passive(
        "health_marathon", "Ran a marathon",
        "You trained for months and finished a marathon. You couldn't walk for days.",
        when=lambda c, co: 18 <= c.age <= 50, chance=lambda c, co: 0.02,
        cooldown_years=0, max_lifetime=1,
        deltas={"endurance": +6, "health": +3, "happiness": +5, "wisdom": +2},
    ),
    _simple_passive(
        "health_dental_emergency", "Dental emergency",
        "You had a dental emergency that ate a paycheck.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.03,
        cooldown_years=4, deltas={"happiness": -2},
        money_delta=-500,
    ),

    # --- Friendship / social (cooldown 4) ------------------------------
    _simple_passive(
        "social_hosted_dinner", "Hosted a dinner party",
        "You hosted a dinner for friends. It went later than planned.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.07,
        cooldown_years=3, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_dinner_with_old_friends", "Dinner with old friends",
        "You met up with friends you'd known since you were kids.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "social_joined_club", "Joined a club",
        "You joined a local club for something you'd been meaning to try.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_neighbor_friendship", "Befriended a neighbor",
        "You and a neighbor became real friends. Coffee on weekends.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.06,
        cooldown_years=6, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "social_work_friendship", "Made a friend at work",
        "A coworker became a real friend, not just a work-friend.",
        when=lambda c, co: c.age >= 18 and c.job is not None,
        chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_school_reunion", "Attended a school reunion",
        "You went to your school reunion. Everyone looked older than you remembered.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.04,
        cooldown_years=10, deltas={"happiness": +3, "wisdom": +2},
    ),
    _simple_passive(
        "social_online_friendship", "Made a friend online",
        "You befriended someone online and the friendship lasted.",
        when=lambda c, co: c.age >= 14 and co.gdp_pc > 3000,
        chance=lambda c, co: 0.06,
        cooldown_years=4, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "social_friend_married", "A friend got married",
        "A close friend got married. You were genuinely happy for them.",
        when=lambda c, co: 22 <= c.age <= 50, chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_friend_baby", "A friend had a baby",
        "A close friend had a baby. You held the kid and felt strange in a good way.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_friend_moved_away", "A friend moved away",
        "A close friend moved to another city. The group chat got quieter.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": -2, "wisdom": +1},
    ),
    _simple_passive(
        "social_lost_touch_friend", "Lost touch with a friend",
        "A friendship faded. Neither of you really meant for it to happen.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"happiness": -2, "wisdom": +1},
    ),
    _simple_passive(
        "social_made_amends", "Made amends with an old friend",
        "You reached out to a friend you'd had a falling out with. It worked.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +4, "conscience": +2, "wisdom": +2},
    ),
    _simple_passive(
        "social_friend_milestone_birthday", "Celebrated a friend's milestone birthday",
        "You helped throw a friend's milestone birthday party.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.07,
        cooldown_years=3, deltas={"happiness": +3},
    ),
    _simple_passive(
        "social_mentored_by_older", "Mentored by an older friend",
        "An older friend took you under their wing. The advice mattered.",
        when=lambda c, co: 18 <= c.age <= 35, chance=lambda c, co: 0.05,
        cooldown_years=8, deltas={"wisdom": +3, "happiness": +2},
    ),
    _simple_passive(
        "social_group_chat", "Started a group chat",
        "You started a group chat with friends and it actually stayed alive.",
        when=lambda c, co: c.age >= 14 and co.gdp_pc > 3000,
        chance=lambda c, co: 0.07,
        cooldown_years=5, deltas={"happiness": +2},
    ),

    # --- Work life (job required, cooldown 3-5) ------------------------
    _simple_passive(
        "work_project_win", "Big project win at work",
        "A big project at work landed exactly the way you'd hoped.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "work_project_failure", "Big project failed",
        "A big project at work flopped. You took the blame.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": -3, "wisdom": +2},
    ),
    _simple_passive(
        "work_difficult_client", "Difficult client at work",
        "You spent the year wrestling with one impossible client.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": -2, "wisdom": +2},
    ),
    _simple_passive(
        "work_long_hours", "Brutal stretch of long hours",
        "You worked a brutal stretch of long hours and it cost you.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": -3, "health": -2, "wisdom": +1},
    ),
    _simple_passive(
        "work_mentored_junior", "Mentored a junior colleague",
        "You took a junior colleague under your wing.",
        when=lambda c, co: c.job is not None and c.age >= 30,
        chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"conscience": +2, "wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "work_tech_change", "Tech change at work",
        "Your workplace adopted a new system and the year was a learning curve.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "work_office_relocation", "Office relocated",
        "Your office moved to a new location. Half the team grumbled, half loved it.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.05,
        cooldown_years=6, deltas={"happiness": -1, "wisdom": +1},
    ),
    _simple_passive(
        "work_conference", "Attended a work conference",
        "You attended a big industry conference. Met some interesting people.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"intelligence": +1, "wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "work_award", "Won a work award",
        "You won an award at work. The plaque was nicer than expected.",
        when=lambda c, co: c.job is not None and c.age >= 25,
        chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "work_networking", "Networking event",
        "You went to a networking event and actually exchanged contacts.",
        when=lambda c, co: c.job is not None and c.age >= 22,
        chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +1, "wisdom": +1},
    ),
    _simple_passive(
        "work_office_party", "Office holiday party",
        "You went to the office holiday party. It was awkward but not bad.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.40,
        cooldown_years=0, deltas={"happiness": +1},
    ),
    _simple_passive(
        "work_bff", "Made a workplace BFF",
        "You found a real friend at work. The day-to-day got easier.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.07,
        cooldown_years=6, deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "work_conflict_boss", "Conflict with the boss",
        "You and your boss clashed about something fundamental.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.08,
        cooldown_years=4, deltas={"happiness": -3, "wisdom": +2},
    ),
    _simple_passive(
        "work_difficult_colleague", "Difficult colleague",
        "You spent the year working alongside someone who made every meeting harder.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": -2, "wisdom": +2},
    ),
    _simple_passive(
        "work_extra_responsibility", "Took on extra responsibility",
        "You volunteered for extra responsibility at work.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"wisdom": +2, "happiness": +1},
    ),
    _simple_passive(
        "work_side_project", "Side project at work",
        "You shipped a side project at work that nobody had asked for.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"happiness": +3, "intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "work_internal_transfer", "Internal transfer at work",
        "You transferred to a different team at the same company.",
        when=lambda c, co: c.job is not None and c.age >= 25,
        chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": +2, "wisdom": +2},
    ),
    _simple_passive(
        "work_new_tool", "Learned a new tool at work",
        "You picked up a new tool at work that became part of your daily flow.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"intelligence": +1, "wisdom": +1},
    ),
    _simple_passive(
        "work_presentation", "Gave a big presentation",
        "You gave a big presentation. Your hands shook but you nailed it.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.08,
        cooldown_years=3, deltas={"wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "work_anniversary_milestone", "Work anniversary milestone",
        "You hit a milestone work anniversary. They gave you a small thing.",
        when=lambda c, co: c.job is not None and (c.years_in_role or 0) >= 5,
        chance=lambda c, co: 0.10,
        cooldown_years=5, deltas={"happiness": +2, "wisdom": +1},
    ),

    # --- Romance (cooldown 4, age 14+) ---------------------------------
    _simple_passive(
        "romance_first_crush", "Had your first crush",
        "You had your first real crush. You barely managed eye contact.",
        when=lambda c, co: 12 <= c.age <= 18, chance=lambda c, co: 0.30,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "romance_first_kiss", "Your first kiss",
        "You had your first kiss. It was nothing like the movies.",
        when=lambda c, co: 14 <= c.age <= 22, chance=lambda c, co: 0.20,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +5, "wisdom": +1},
    ),
    _simple_passive(
        "romance_brief_relationship", "Brief relationship",
        "You dated someone for a few months. It didn't work out, but it was worth it.",
        when=lambda c, co: 16 <= c.age <= 35 and not c.married,
        chance=lambda c, co: 0.12,
        cooldown_years=2, deltas={"happiness": +2, "wisdom": +2},
    ),
    _simple_passive(
        "romance_breakup", "Painful breakup",
        "You went through a painful breakup. It hurt for longer than you expected.",
        when=lambda c, co: 16 <= c.age <= 45 and not c.married,
        chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": -5, "wisdom": +3},
    ),
    _simple_passive(
        "romance_dating_app", "Joined a dating app",
        "You signed up for a dating app and went on a few dates.",
        when=lambda c, co: 18 <= c.age <= 45 and not c.married and co.gdp_pc > 5000,
        chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +1, "wisdom": +1},
    ),
    _simple_passive(
        "romance_anniversary", "Celebrated an anniversary",
        "You and your spouse marked another year together.",
        when=lambda c, co: c.married, chance=lambda c, co: 0.50,
        cooldown_years=0, deltas={"happiness": +2},
    ),
    _simple_passive(
        "romance_getaway", "Romantic getaway",
        "You and your spouse took a romantic getaway just for the two of you.",
        when=lambda c, co: c.married and (c.money + c.family_wealth) > 2000,
        chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"happiness": +5},
        money_delta=-800,
    ),
    _simple_passive(
        "romance_met_partner_family", "Met your partner's family",
        "You met your partner's family for the first time. The dinner was tense.",
        when=lambda c, co: 18 <= c.age <= 35 and not c.married,
        chance=lambda c, co: 0.06,
        cooldown_years=5, deltas={"happiness": +1, "wisdom": +2},
    ),
    _simple_passive(
        "romance_partner_moved_in", "Partner moved in",
        "You and your partner moved in together. The first month was an adjustment.",
        when=lambda c, co: 20 <= c.age <= 40 and not c.married,
        chance=lambda c, co: 0.07,
        cooldown_years=5, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "romance_big_argument", "Big argument with partner",
        "You and your partner had a major fight and made up.",
        when=lambda c, co: c.married, chance=lambda c, co: 0.15,
        cooldown_years=2, deltas={"happiness": -2, "wisdom": +2},
    ),
    _simple_passive(
        "romance_blind_date", "Went on a blind date",
        "A friend set you up on a blind date. It was strange and somehow lovely.",
        when=lambda c, co: 18 <= c.age <= 50 and not c.married,
        chance=lambda c, co: 0.07,
        cooldown_years=3, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "romance_partner_disapproved", "Partner's family disapproved",
        "Your partner's family didn't approve. It put pressure on the relationship.",
        when=lambda c, co: 18 <= c.age <= 35 and not c.married,
        chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": -3, "wisdom": +2},
    ),

    # --- Misc life (~25) -----------------------------------------------
    _simple_passive(
        "misc_first_car", "Bought your first car",
        "You bought your first car. The freedom was real.",
        when=lambda c, co: c.age >= 18 and (c.money + c.family_wealth) > 3000,
        chance=lambda c, co: 0.10,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +5, "wisdom": +1},
        money_delta=-3000,
    ),
    _simple_passive(
        "misc_moved_apartments", "Moved apartments",
        "You moved to a new apartment. The packing took weeks.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"happiness": +1, "wisdom": +1},
        money_delta=-300,
    ),
    _simple_passive(
        "misc_adopted_pet", "Adopted a pet",
        "You adopted a pet. Your routines reorganized around it.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.07,
        cooldown_years=8, deltas={"happiness": +5, "conscience": +1},
    ),
    _simple_passive(
        "misc_pet_died", "A pet died",
        "Your pet died after years together. The house felt different.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": -4, "wisdom": +2},
    ),
    _simple_passive(
        "misc_lost_treasured_item", "Lost a treasured item",
        "You lost something irreplaceable that had been in the family.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": -3, "wisdom": +1},
    ),
    _simple_passive(
        "misc_found_heirloom", "Found a forgotten heirloom",
        "You found a forgotten heirloom in a closet. The story behind it surprised you.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"happiness": +3, "wisdom": +2},
    ),
    _simple_passive(
        "misc_neighborhood_changed", "Neighborhood changed",
        "Your neighborhood changed dramatically — new buildings, new people, new prices.",
        when=lambda c, co: c.age >= 25 and c.is_urban,
        chance=lambda c, co: 0.05,
        cooldown_years=10, deltas={"wisdom": +1},
    ),
    _simple_passive(
        "misc_voted", "Voted in an election",
        "You voted in a major election. You stood in line for two hours.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.20,
        cooldown_years=2, deltas={"conscience": +1, "wisdom": +1},
    ),
    _simple_passive(
        "misc_won_lottery_small", "Won a small lottery prize",
        "You won a small lottery prize. Enough for a nice dinner.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.02,
        cooldown_years=8, deltas={"happiness": +2},
        money_delta=200,
    ),
    _simple_passive(
        "misc_traffic_accident_minor", "Minor traffic accident",
        "You were in a minor traffic accident. Nobody got hurt but the paperwork dragged on.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"happiness": -2, "wisdom": +1},
        money_delta=-300,
    ),
    _simple_passive(
        "misc_helped_stranger", "Helped a stranger",
        "You helped a stranger in trouble. The thanks stayed with you.",
        when=lambda c, co: c.age >= 12, chance=lambda c, co: 0.08,
        cooldown_years=3, deltas={"happiness": +2, "conscience": +2},
    ),
    _simple_passive(
        "misc_witnessed_accident", "Witnessed an accident",
        "You witnessed an accident on the street. You were the one who called for help.",
        when=lambda c, co: c.age >= 14, chance=lambda c, co: 0.04,
        cooldown_years=5, deltas={"wisdom": +2, "conscience": +1, "happiness": -1},
    ),
    _simple_passive(
        "misc_jury_duty", "Served on a jury",
        "You were called for jury duty and ended up on a serious case.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 8000,
        chance=lambda c, co: 0.04,
        cooldown_years=8, deltas={"wisdom": +2, "conscience": +1},
    ),
    _simple_passive(
        "misc_passport", "Got your first passport",
        "You got your first passport. The photo was unflattering.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.05,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +2},
    ),
    _simple_passive(
        "misc_lost_wallet", "Lost your wallet",
        "You lost your wallet and spent the day cancelling cards.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.04,
        cooldown_years=5, deltas={"happiness": -2, "wisdom": +1},
        money_delta=-100,
    ),
    _simple_passive(
        "misc_locked_out", "Locked yourself out",
        "You locked yourself out of your home. The locksmith arrived eventually.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.04,
        cooldown_years=4, deltas={"happiness": -1, "wisdom": +1},
        money_delta=-150,
    ),
    _simple_passive(
        "misc_bad_weather", "Bad weather event",
        "A bad weather event hit your area — power out for days.",
        when=lambda c, co: c.age >= 6, chance=lambda c, co: 0.06,
        cooldown_years=3, deltas={"wisdom": +1},
    ),
    _simple_passive(
        "misc_power_outage", "Long power outage",
        "Your area lost power for days. You learned to live by candlelight.",
        when=lambda c, co: c.age >= 8, chance=lambda c, co: 0.05,
        cooldown_years=3, deltas={"wisdom": +1},
    ),
    _simple_passive(
        "misc_neighbor_feud", "Neighbor feud",
        "You and a neighbor had a long-running feud about something petty.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": -2, "wisdom": +1},
    ),
    _simple_passive(
        "misc_robbed", "Got robbed",
        "Someone broke into your home or mugged you on the street.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.02,
        cooldown_years=8, deltas={"happiness": -4, "health": -2, "wisdom": +2},
        money_delta=-500,
    ),
    _simple_passive(
        "misc_good_samaritan", "Good Samaritan moment",
        "You stopped to help someone in trouble and made it their day.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.06,
        cooldown_years=3, deltas={"conscience": +2, "happiness": +2},
    ),
    _simple_passive(
        "misc_purchase_regret", "Big purchase regret",
        "You bought something expensive and immediately regretted it.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.04,
        cooldown_years=5, deltas={"happiness": -2, "wisdom": +2},
    ),
    _simple_passive(
        "misc_repaired_something", "Repaired something yourself",
        "You fixed something yourself instead of calling a pro. It even held.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.07,
        cooldown_years=3, deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "misc_meteor_shower", "Watched a meteor shower",
        "You stayed up late and watched a meteor shower from somewhere dark.",
        when=lambda c, co: c.age >= 10, chance=lambda c, co: 0.04,
        cooldown_years=6, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "misc_local_hero_moment", "Local hero moment",
        "You did something small that the local paper picked up.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.02,
        cooldown_years=10, deltas={"happiness": +4, "conscience": +1},
    ),

    # --- Cultural / community (cooldown 4) -----------------------------
    _simple_passive(
        "culture_concert", "Went to a concert",
        "You went to see a band you'd loved for years. Worth every ticket dollar.",
        when=lambda c, co: c.age >= 14 and c.is_urban,
        chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +3},
        money_delta=-100,
    ),
    _simple_passive(
        "culture_museum", "Visited a museum",
        "You spent a Saturday at a museum and lost track of time.",
        when=lambda c, co: c.age >= 8, chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"wisdom": +1, "happiness": +1},
    ),
    _simple_passive(
        "culture_sports_game", "Went to a live sports game",
        "You went to a live sports game and lost your voice cheering.",
        when=lambda c, co: c.age >= 10, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"happiness": +3},
    ),
    _simple_passive(
        "culture_theater", "Saw a theater play",
        "You went to see a play and were pulled in by the second act.",
        when=lambda c, co: c.age >= 14 and c.is_urban,
        chance=lambda c, co: 0.06,
        cooldown_years=3, deltas={"wisdom": +1, "happiness": +2},
    ),
    _simple_passive(
        "culture_volunteered", "Volunteered locally",
        "You volunteered for a local cause and stuck with it for the year.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.08,
        cooldown_years=3, deltas={"conscience": +3, "wisdom": +1, "happiness": +2},
    ),
    _simple_passive(
        "culture_committee", "Joined a community committee",
        "You joined a neighborhood committee and got into the meetings.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"conscience": +2, "wisdom": +2},
    ),
    _simple_passive(
        "culture_religious_revival", "Attended a religious revival",
        "You went to a religious revival event that left you energized.",
        when=lambda c, co: c.age >= 16 and co.primary_religion != "None",
        chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"happiness": +3, "conscience": +2},
    ),
    _simple_passive(
        "culture_festival", "Attended a community festival",
        "You went to a local festival. The food alone was worth it.",
        when=lambda c, co: c.age >= 6, chance=lambda c, co: 0.15,
        cooldown_years=2, deltas={"happiness": +3},
    ),
    _simple_passive(
        "culture_art_exhibit", "Visited an art exhibit",
        "You spent an afternoon at an art exhibit and bought a print of one piece.",
        when=lambda c, co: c.age >= 16 and c.is_urban,
        chance=lambda c, co: 0.06,
        cooldown_years=3, deltas={"artistic": +1, "wisdom": +1, "happiness": +1},
    ),
    _simple_passive(
        "culture_poetry_reading", "Attended a poetry reading",
        "You went to a poetry reading. Some of the poems stayed with you.",
        when=lambda c, co: c.age >= 16 and c.is_urban,
        chance=lambda c, co: 0.04,
        cooldown_years=4, deltas={"artistic": +1, "wisdom": +2},
    ),
    _simple_passive(
        "culture_opera", "Saw an opera",
        "You went to the opera. You weren't sure you'd like it but you did.",
        when=lambda c, co: c.age >= 25 and c.is_urban and (c.money + c.family_wealth) > 3000,
        chance=lambda c, co: 0.03,
        cooldown_years=6, deltas={"wisdom": +1, "happiness": +2},
    ),
    _simple_passive(
        "culture_comedy_show", "Saw a comedy show",
        "You went to a stand-up show and laughed until your face hurt.",
        when=lambda c, co: c.age >= 16 and c.is_urban,
        chance=lambda c, co: 0.08,
        cooldown_years=3, deltas={"happiness": +3},
    ),
    _simple_passive(
        "culture_film_festival", "Attended a film festival",
        "You spent a few days at a local film festival, watching everything you could.",
        when=lambda c, co: c.age >= 18 and c.is_urban,
        chance=lambda c, co: 0.04,
        cooldown_years=4, deltas={"wisdom": +2, "happiness": +2},
    ),
    _simple_passive(
        "culture_charity_5k", "Ran a charity 5k",
        "You ran a charity 5k. The cause was good, the t-shirt was scratchy.",
        when=lambda c, co: 14 <= c.age <= 65, chance=lambda c, co: 0.05,
        cooldown_years=3, deltas={"endurance": +1, "conscience": +2, "happiness": +2},
    ),
    _simple_passive(
        "culture_attended_protest", "Attended a protest",
        "You went to a protest about something you believed in.",
        when=lambda c, co: c.age >= 16, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"conscience": +3, "wisdom": +2},
    ),

    # --- Aging milestones (age-gated) ----------------------------------
    _simple_passive(
        "aging_first_grey_hair", "First grey hair",
        "You spotted your first grey hair. It was a moment.",
        when=lambda c, co: 30 <= c.age <= 50, chance=lambda c, co: 0.20,
        cooldown_years=0, max_lifetime=1,
        deltas={"wisdom": +1},
    ),
    _simple_passive(
        "aging_joint_pain", "Joint pain",
        "Your knees started complaining about every flight of stairs.",
        when=lambda c, co: c.age >= 45, chance=lambda c, co: 0.15,
        cooldown_years=5, deltas={"health": -2, "wisdom": +1},
    ),
    _simple_passive(
        "aging_milestone_birthday", "Milestone birthday celebration",
        "You celebrated a milestone birthday with people you love.",
        when=lambda c, co: c.age in (30, 40, 50, 60, 70, 80),
        chance=lambda c, co: 0.70,
        cooldown_years=0, deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "aging_midlife_reflection", "Midlife reflection",
        "You spent a quiet stretch of the year really thinking about your life so far.",
        when=lambda c, co: 40 <= c.age <= 50, chance=lambda c, co: 0.15,
        cooldown_years=0, max_lifetime=1,
        deltas={"wisdom": +5, "happiness": -1},
    ),
    _simple_passive(
        "aging_retirement_planning", "Started retirement planning",
        "You started seriously planning for retirement.",
        when=lambda c, co: 50 <= c.age <= 65, chance=lambda c, co: 0.20,
        cooldown_years=0, max_lifetime=1,
        deltas={"wisdom": +2, "happiness": +1},
    ),
    _simple_passive(
        "aging_nostalgia_youth", "Nostalgia for youth",
        "You spent a stretch of the year missing the way things used to be.",
        when=lambda c, co: c.age >= 50, chance=lambda c, co: 0.15,
        cooldown_years=8, deltas={"wisdom": +2, "happiness": -1},
    ),
    _simple_passive(
        "aging_grandchild", "First grandchild",
        "You met your first grandchild. The world reorganized itself.",
        when=lambda c, co: c.age >= 50 and len(c.children) > 0,
        chance=lambda c, co: 0.08,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +8, "wisdom": +2},
    ),
    _simple_passive(
        "aging_reading_glasses", "First reading glasses",
        "You finally accepted the reading glasses your eyes had been begging for.",
        when=lambda c, co: 40 <= c.age <= 55, chance=lambda c, co: 0.30,
        cooldown_years=0, max_lifetime=1,
        deltas={"wisdom": +1},
    ),
    _simple_passive(
        "aging_old_photos", "Looked through old photos",
        "You spent an evening looking through old photos. Some of them stopped you cold.",
        when=lambda c, co: c.age >= 40, chance=lambda c, co: 0.10,
        cooldown_years=4, deltas={"happiness": +2, "wisdom": +2},
    ),
    _simple_passive(
        "aging_wrote_memoir", "Started writing a memoir",
        "You started writing a memoir for the family.",
        when=lambda c, co: c.age >= 60, chance=lambda c, co: 0.08,
        cooldown_years=0, max_lifetime=1,
        deltas={"wisdom": +3, "happiness": +3, "artistic": +1},
    ),

    # --- Childhood / adolescence (age-gated) ---------------------------
    _simple_passive(
        "child_sleepover", "Hosted a sleepover",
        "You hosted a sleepover with friends. There was no sleeping involved.",
        when=lambda c, co: 7 <= c.age <= 14, chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": +3},
    ),
    _simple_passive(
        "child_summer_camp", "Went to summer camp",
        "You spent a summer at camp and made unexpected friendships.",
        when=lambda c, co: 8 <= c.age <= 16 and (c.money + c.family_wealth) > 1000,
        chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": +4, "endurance": +1, "wisdom": +1},
    ),
    _simple_passive(
        "child_scouts", "Joined a scouts troop",
        "You joined a scouts troop and earned a few badges.",
        when=lambda c, co: 7 <= c.age <= 16, chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"happiness": +2, "wisdom": +2, "endurance": +1},
    ),
    _simple_passive(
        "child_school_play", "Was in the school play",
        "You had a small part in the school play and didn't forget your line.",
        when=lambda c, co: 8 <= c.age <= 17 and c.in_school,
        chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": +3, "artistic": +1},
    ),
    _simple_passive(
        "child_school_trip", "Went on a school trip",
        "Your class took an overnight trip somewhere you'd never been.",
        when=lambda c, co: 8 <= c.age <= 17 and c.in_school,
        chance=lambda c, co: 0.15,
        cooldown_years=2, deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "child_science_fair", "Entered the science fair",
        "You entered the science fair with a project you actually cared about.",
        when=lambda c, co: 9 <= c.age <= 16 and c.in_school,
        chance=lambda c, co: 0.07,
        cooldown_years=3, deltas={"intelligence": +2, "happiness": +2},
    ),
    _simple_passive(
        "child_sports_team", "Joined a sports team",
        "You joined a sports team and went to practice three times a week.",
        when=lambda c, co: 8 <= c.age <= 17, chance=lambda c, co: 0.10,
        cooldown_years=3, deltas={"endurance": +2, "athletic": +2, "happiness": +2},
    ),
    _simple_passive(
        "child_school_dance", "Went to a school dance",
        "You went to a school dance. The slow songs were the worst part.",
        when=lambda c, co: 12 <= c.age <= 17 and c.in_school,
        chance=lambda c, co: 0.20,
        cooldown_years=2, deltas={"happiness": +2},
    ),
    _simple_passive(
        "child_prom", "Went to prom",
        "You went to prom. The photos still exist somewhere.",
        when=lambda c, co: 16 <= c.age <= 18 and c.in_school,
        chance=lambda c, co: 0.40,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +4, "wisdom": +1},
    ),
    _simple_passive(
        "child_grounded", "Got grounded",
        "Your parents grounded you for a long stretch over something stupid.",
        when=lambda c, co: 12 <= c.age <= 17, chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": -2, "wisdom": +1},
    ),
    _simple_passive(
        "child_sneaked_out", "Sneaked out at night",
        "You sneaked out at night with friends and barely made it home before dawn.",
        when=lambda c, co: 13 <= c.age <= 17, chance=lambda c, co: 0.10,
        cooldown_years=0, max_lifetime=2,
        deltas={"happiness": +3, "wisdom": +1},
    ),
    _simple_passive(
        "child_first_allowance", "Got your first allowance",
        "You started getting an allowance and immediately blew the first one.",
        when=lambda c, co: 6 <= c.age <= 10, chance=lambda c, co: 0.30,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +2, "wisdom": +1},
    ),
    _simple_passive(
        "child_lost_tooth", "Lost a tooth",
        "You lost a tooth and put it under your pillow.",
        when=lambda c, co: 5 <= c.age <= 12, chance=lambda c, co: 0.50,
        cooldown_years=1, deltas={"happiness": +1},
    ),
    _simple_passive(
        "child_learned_to_ride", "Learned to ride a bike",
        "You learned to ride a bike. The first time you went without help, you screamed.",
        when=lambda c, co: 5 <= c.age <= 9, chance=lambda c, co: 0.40,
        cooldown_years=0, max_lifetime=1,
        deltas={"endurance": +1, "happiness": +3},
    ),
    _simple_passive(
        "child_treehouse", "Built a treehouse",
        "You and your friends built a treehouse — wobbly, dangerous, perfect.",
        when=lambda c, co: 7 <= c.age <= 13 and not c.is_urban,
        chance=lambda c, co: 0.07,
        cooldown_years=0, max_lifetime=1,
        deltas={"happiness": +4, "strength": +1},
    ),

    # --- Stressors / minor disasters (cooldown 4-8) --------------------
    _simple_passive(
        "stressor_house_fire", "Small house fire",
        "A small house fire broke out. You got it under control before things got worse.",
        when=lambda c, co: c.age >= 18, chance=lambda c, co: 0.02,
        cooldown_years=10, max_lifetime=2,
        deltas={"happiness": -3, "wisdom": +2},
        money_delta=-2000,
    ),
    _simple_passive(
        "stressor_plumbing", "Plumbing emergency",
        "A pipe burst. The repair bill ate a paycheck.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"happiness": -2, "wisdom": +1},
        money_delta=-700,
    ),
    _simple_passive(
        "stressor_car_breakdown", "Car broke down",
        "Your car broke down at the worst possible time.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.06,
        cooldown_years=4, deltas={"happiness": -2},
        money_delta=-600,
    ),
    _simple_passive(
        "stressor_identity_theft", "Identity theft",
        "Someone stole your identity. The cleanup took months.",
        when=lambda c, co: c.age >= 22 and co.gdp_pc > 8000,
        chance=lambda c, co: 0.03,
        cooldown_years=10, deltas={"happiness": -3, "wisdom": +2},
        money_delta=-500,
    ),
    _simple_passive(
        "stressor_missed_meeting", "Missed an important meeting",
        "You missed a meeting that you really shouldn't have.",
        when=lambda c, co: c.job is not None, chance=lambda c, co: 0.05,
        cooldown_years=4, deltas={"happiness": -2, "wisdom": +1},
    ),
    _simple_passive(
        "stressor_lost_data", "Lost important computer data",
        "Your computer crashed and you lost work you'd been doing for months.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 5000,
        chance=lambda c, co: 0.04,
        cooldown_years=5, deltas={"happiness": -3, "wisdom": +2},
    ),
    _simple_passive(
        "stressor_bad_investment", "Bad investment moment",
        "You watched an investment lose value at the worst possible moment.",
        when=lambda c, co: c.age >= 25, chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"happiness": -2, "wisdom": +2},
    ),
    _simple_passive(
        "stressor_neighbor_dispute", "Neighbor dispute",
        "You had a long-running dispute with a neighbor about something annoying.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.05,
        cooldown_years=5, deltas={"happiness": -2},
    ),
    _simple_passive(
        "stressor_parking_ticket", "Got a big parking ticket",
        "You got a parking ticket that cost more than the dinner you'd parked for.",
        when=lambda c, co: c.age >= 18 and co.gdp_pc > 5000 and c.is_urban,
        chance=lambda c, co: 0.10,
        cooldown_years=2, deltas={"happiness": -1},
        money_delta=-100,
    ),
    _simple_passive(
        "stressor_appliance_died", "An appliance died",
        "Your fridge or washing machine died and the replacement was expensive.",
        when=lambda c, co: c.age >= 22, chance=lambda c, co: 0.07,
        cooldown_years=4, deltas={"happiness": -1},
        money_delta=-600,
    ),

    # --- Choice events ---
    # Career-defining events go FIRST so a slice-of-life choice event
    # (theft, bribery, marriage, etc) doesn't preempt them. roll_events
    # walks the registry top-to-bottom and breaks on the first CHOICE
    # event that fires — once-in-a-lifetime education and vocation
    # picks must always win that race.
    EDUCATION_PATH,
    UNIVERSITY_MAJOR,
    VOCATIONAL_TRACK,
    THEFT_CHILD,
    THEFT_ADULT,
    BRIBERY,
    HAJJ,
    VARANASI_PILGRIMAGE,
    MONASTIC_RETREAT,
    ARRANGED_MARRIAGE,
    CONVERSION_OFFER,
    RELIGIOUS_SCHOOL,
    DOWRY_NEGOTIATION,
    BILINGUAL_SCHOOLING,
    LOVE_MARRIAGE,
]


def _on_cooldown(character: Character, ev: Event) -> bool:
    """#52: enforce cooldown_years and max_lifetime against the
    character's event_history. Returns True when the event should be
    skipped this year."""
    fired_at = character.event_history.get(ev.key)
    if not fired_at:
        return False
    if ev.max_lifetime > 0 and len(fired_at) >= ev.max_lifetime:
        return True
    if ev.cooldown_years > 0 and (character.age - fired_at[-1]) < ev.cooldown_years:
        return True
    return False


def record_event_fired(character: Character, event_key: str) -> None:
    """#52: append the current age to character.event_history for
    the given event key. Called by game.advance_year after each
    passive event applies, and by game.apply_decision after a choice
    event resolves."""
    character.event_history.setdefault(event_key, []).append(character.age)


def roll_events(character: Character, country: Country, rng: random.Random) -> list[Event]:
    """Decide which events fire this year. The first CHOICE event seen halts
    the rest of the year so the player can make their decision.

    #52 followup: slice-of-life events (the ~200 content-drop entries)
    are collected separately and sampled down to
    MAX_SLICE_OF_LIFE_PER_YEAR per year. Without this cap the event
    log would routinely fire 10+ entries in a single year and become
    noise. Structural events (disease, disaster, war, school year,
    holidays, choice events) always fire when eligible — they're the
    spine of the year."""
    fired: list[Event] = []
    sol_candidates: list[Event] = []
    for ev in EVENT_REGISTRY:
        if not ev.eligible(character, country):
            continue
        # #52: cooldown + lifetime cap. Skip the event if it's still
        # within its cooldown window or has already fired its
        # lifetime allowance.
        if _on_cooldown(character, ev):
            continue
        p = max(0.0, min(1.0, ev.probability(character, country)))
        if rng.random() < p:
            if ev.slice_of_life:
                # Defer — sampled at the end so all slice-of-life
                # categories get fair representation regardless of
                # their position in the registry.
                sol_candidates.append(ev)
                continue
            fired.append(ev)
            if ev.choices:
                # CHOICE event halts the year. Drop any slice-of-life
                # events we collected so far — the player should focus
                # on their decision, not on a wall of trivia.
                return fired
    # Sample slice-of-life candidates down to the per-year cap. Use a
    # SEPARATE rng seeded from the character's id and age so the
    # sampling is deterministic per (character, year) but doesn't
    # consume the main game rng — otherwise downstream randomness
    # (income variance, disease rolls, finance ticks, tests) would
    # shift every time we added or removed a slice-of-life event.
    if len(sol_candidates) > MAX_SLICE_OF_LIFE_PER_YEAR:
        sol_rng = random.Random(hash((character.id, character.age, "sol")) & 0xffffffff)
        sol_candidates = sol_rng.sample(sol_candidates, MAX_SLICE_OF_LIFE_PER_YEAR)
    fired.extend(sol_candidates)
    return fired
