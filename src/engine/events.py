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
)


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
                    summary="You agreed to the arranged marriage. The wedding will be next year."),
        EventChoice(key="defer", label="Ask for more time",
                    deltas={"happiness": -2, "wisdom": +1},
                    summary="You asked your family to wait. They were disappointed but understood."),
        EventChoice(key="refuse", label="Refuse the match",
                    deltas={"happiness": +1, "conscience": -3, "wisdom": +2},
                    summary="You refused. There was a long argument, but you held firm."),
    ],
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
)


def _education_university(c):
    # Stay in school — education.update_education will auto-promote at 18
    # to SECONDARY, then to UNIVERSITY at 22. school_track lets the
    # vocational vs university completion branches and the UI tell
    # them apart while in school.
    c.in_school = True
    c.school_track = "university"


def _education_vocational(c):
    # Enter a 2-year vocational program. Mirror the university path:
    # stay in school, set school_track, DO NOT grant the credential
    # on entry (granted on graduation by education.update_education at
    # age 20). Previously this immediately set in_school=False and
    # granted education=VOCATIONAL, which made the player think they
    # were in school but the engine treated them as a graduated adult.
    c.in_school = True
    c.school_track = "vocational"


def _education_dropout(c):
    # Leave school. Education stays at whatever level was already
    # completed (primary or none).
    c.in_school = False
    c.school_track = None


def _set_vocation(field):
    """Build a side-effect that sets character.vocation_field. Used by
    the UNIVERSITY_MAJOR / VOCATIONAL_TRACK choices below to constrain
    careers.assign_job to the chosen category (#51)."""
    def _do(c):
        c.vocation_field = field
    return _do


def _accept_proposal(c):
    from .character import Gender, _random_name
    import random as _random
    rng = _random.Random()
    spouse_gender = Gender.MALE if c.gender == Gender.FEMALE else Gender.FEMALE
    c.spouse_name = _random_name(spouse_gender, rng)
    c.married = True


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
)


UNIVERSITY_MAJOR = _choice(
    key="university_major",
    title="Pick your major",
    category="education",
    description=(
        "You're heading into university. Time to choose what to study — your "
        "major will shape the kind of work you can do for the rest of your "
        "life. Pick a field that fits your strengths. When you graduate in "
        "four years you'll start your career in this field."
    ),
    when=lambda c, co: (
        c.age == 18
        and c.school_track == "university"
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
        "the rest of your career. When you graduate in two years you'll "
        "begin work as an apprentice in this field."
    ),
    when=lambda c, co: (
        c.age == 18
        and c.school_track == "vocational"
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
        "village_harvest", "Village harvest", "life",
        "You helped bring in the harvest.",
        when=lambda c, co: not c.is_urban and 8 <= c.age <= 60,
        chance=lambda c, co: 0.20,
        apply=_apply_village_harvest,
    ),
    _passive(
        "witnessed_corruption", "Witnessed corruption", "moral",
        "You witnessed local corruption.",
        when=lambda c, co: c.age >= 16 and co.corruption > 40,
        # Urban characters interact with bureaucracy more frequently and
        # see corruption first-hand at much higher rates than rural villagers.
        chance=lambda c, co: (co.corruption / 1500) * (1.8 if c.is_urban else 0.5),
        apply=_apply_corruption_witnessed,
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
    ),
    _passive(
        "first_communion", "First Communion", "life",
        "Catholic First Communion.",
        when=lambda c, co: c.age == 8 and co.primary_religion == "Christianity",
        chance=lambda c, co: 0.50,
        apply=_apply_first_communion,
    ),
    _passive(
        "sacred_thread", "Sacred thread ceremony", "life",
        "Hindu Upanayana ceremony.",
        when=lambda c, co: c.age in (8, 9, 10, 11, 12) and co.primary_religion == "Hinduism" and c.gender == Gender.MALE,
        chance=lambda c, co: 0.30,
        apply=_apply_sacred_thread,
    ),
    _passive(
        "bar_mitzvah", "Bar/Bat Mitzvah", "life",
        "Coming-of-age in the Jewish tradition.",
        when=lambda c, co: c.age in (12, 13) and co.primary_religion == "Judaism",
        chance=lambda c, co: 0.85,
        apply=_apply_bar_mitzvah,
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
    ),
    _passive(
        "seijin_shiki", "Seijin no Hi", "life",
        "Coming of Age Day ceremony in Japan.",
        when=lambda c, co: c.age == 20 and co.primary_language == "Japanese",
        chance=lambda c, co: 0.85,
        apply=_apply_seijin_shiki,
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

    # --- Choice events ---
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
    EDUCATION_PATH,
    UNIVERSITY_MAJOR,
    VOCATIONAL_TRACK,
    LOVE_MARRIAGE,
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
