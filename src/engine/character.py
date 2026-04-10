"""
Character model: attributes, birth, aging, death.

Mirrors the structure of the original Real Lives 2007 character object,
adapted for Python. The original game stored 12 attributes per character
(see `engine/engine_handler_21.txt` in the decompiled reference). They're
all in the 0..100 range and decay/improve based on yearly events.

Attribute meanings (from decompiled FUN_FACT.MD and engine_handler_21):
  - health        physical wellbeing; <=0 means death
  - happiness     emotional state; influences event reactions
  - intelligence  gates education and high-skill jobs
  - artistic      gates art / writing careers and creative events
  - musical       gates music careers
  - athletic      gates sport careers
  - strength      manual labor capability
  - endurance     disease resilience
  - appearance    influences relationships, social events
  - conscience    moral ledger; choosing crimes lowers it
  - wisdom        accumulates with age and reading
  - resistance    disease/infection resistance
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import Country


class Gender(IntEnum):
    FEMALE = 0
    MALE = 1


class EducationLevel(IntEnum):
    NONE = 0
    PRIMARY = 1
    SECONDARY = 2
    VOCATIONAL = 3
    UNIVERSITY = 4


class LifeStage(IntEnum):
    INFANT = 0       # 0-2
    CHILD = 1        # 3-12
    TEENAGER = 2     # 13-17
    YOUNG_ADULT = 3  # 18-29
    ADULT = 4        # 30-49
    MIDDLE_AGED = 5  # 50-64
    ELDERLY = 6      # 65+


# A handful of generic name pools used for procedural names. Real Lives 2007
# uses far larger ethnicity-tagged pools; this is intentionally simple.
_NAMES_F = [
    "Maria","Aisha","Yuki","Olga","Fatima","Sofia","Amara","Lucia","Mei",
    "Priya","Elena","Chiamaka","Nadia","Anya","Isabella","Khadija","Hana",
    "Esperanza","Wairimu","Zara","Lin","Saoirse","Greta","Naomi","Camila",
]
_NAMES_M = [
    "Mateo","Wei","Arjun","Ahmed","Jakub","Ravi","Liam","Yusuf","Hiroshi",
    "Ezekiel","Diego","Tomas","Kofi","Nikolai","Joaquin","Sanjay","Idris",
    "Anders","Pedro","Tariq","Kenji","Bilal","Emeka","Aleksei","Lucas",
]
_SURNAMES = [
    "Okonkwo","Singh","Tanaka","Nguyen","Sokolov","Hernandez","Martins",
    "Petrov","Khan","Kim","O'Connor","Andersen","Chen","Obi","da Silva",
    "Schmidt","Garcia","Adeyemi","Saito","Rodriguez","Patel","Larsson",
]


def _random_name(gender: Gender, rng: random.Random) -> str:
    pool = _NAMES_F if gender == Gender.FEMALE else _NAMES_M
    return f"{rng.choice(pool)} {rng.choice(_SURNAMES)}"


@dataclass
class Attributes:
    health: int = 75
    happiness: int = 70
    intelligence: int = 50
    artistic: int = 50
    musical: int = 50
    athletic: int = 50
    strength: int = 50
    endurance: int = 50
    appearance: int = 50
    conscience: int = 60
    wisdom: int = 20
    resistance: int = 50

    def clamp(self) -> None:
        for k, v in list(self.__dict__.items()):
            self.__dict__[k] = max(0, min(100, int(v)))

    def adjust(self, **deltas: int) -> None:
        for k, v in deltas.items():
            if k in self.__dict__:
                self.__dict__[k] = self.__dict__[k] + v
        self.clamp()

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class FamilyMember:
    relation: str           # 'father', 'mother', 'spouse', 'child', 'sibling'
    name: str
    age: int
    alive: bool = True
    gender: Gender = Gender.FEMALE


@dataclass
class LoanHolding:
    """A single open loan the player has taken out."""
    product_id: int
    name: str
    principal: int          # original amount borrowed
    balance: int            # current outstanding balance
    interest_rate: float    # annual rate (e.g., 0.08)
    years_remaining: int    # years left on the term
    opened_year: int        # in-game calendar year of origination


@dataclass
class InvestmentHolding:
    """A single open investment position the player owns."""
    product_id: int
    name: str
    cost_basis: int         # original cash invested
    value: int              # current mark-to-market value
    opened_year: int        # in-game calendar year purchased
    last_year_delta: int = 0  # change in `value` from the most recent yearly tick (#74)


@dataclass
class Character:
    id: str
    name: str
    gender: Gender
    age: int
    country_code: str
    city: str
    is_urban: bool
    attributes: Attributes
    family_wealth: int                 # starting household wealth in USD-equivalent
    money: int = 0                     # current personal savings
    debt: int = 0
    education: EducationLevel = EducationLevel.NONE
    in_school: bool = False
    # Which post-secondary school the character is currently enrolled in
    # (when ``in_school`` is True). One of "primary", "secondary",
    # "vocational", "university" or None when not enrolled. Lets the UI
    # show "secondary · in vocational school" instead of just the
    # credential level, and lets the engine distinguish vocational vs
    # university completion at age 19 vs 22.
    school_track: str | None = None
    job: str | None = None
    salary: int = 0
    # Vocation tracking (#51): the player's chosen field of work, the
    # number of years in the current job, and how many promotions they've
    # taken in their career so far. The field is set by the EDUCATION_PATH
    # / vocation-picker choices and constrains assign_job's pool.
    vocation_field: str | None = None
    years_in_role: int = 0
    promotion_count: int = 0
    last_raise_request_age: int | None = None  # cooldown gate (#55)
    married: bool = False
    spouse_name: str | None = None
    children: list[FamilyMember] = field(default_factory=list)
    family: list[FamilyMember] = field(default_factory=list)
    loans: list[LoanHolding] = field(default_factory=list)
    investments: list[InvestmentHolding] = field(default_factory=list)
    alive: bool = True
    cause_of_death: str | None = None
    moral_ledger: dict[str, int] = field(default_factory=dict)
    diseases: dict[str, dict] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    pending_decision: dict | None = None  # event awaiting player choice
    # Lifestyle subscriptions and recurring costs (#66). Each entry:
    #   {key: {"name": str, "monthly_cost": int, "started_year": int,
    #          "effects": dict}}
    # The yearly_income tick deducts (12 * monthly_cost) from money.
    subscriptions: dict[str, dict] = field(default_factory=dict)
    # One-time purchases the character has made (#66). Used to enforce
    # "you already own a house" gates and to render the death retrospective.
    purchases: list[dict] = field(default_factory=list)
    # Per-treatment cooldown trackers (#67). Maps treatment kind →
    # last age the character bought it.
    last_treatment: dict[str, int] = field(default_factory=dict)
    # Per-event firing record (#52). Maps event_key → list of ages at
    # which the event fired. events.roll_events reads this to enforce
    # cooldown_years and max_lifetime — without it, the same event
    # could fire 10 years in a row and milestone events like baptism
    # could fire twice.
    event_history: dict[str, list[int]] = field(default_factory=dict)

    @property
    def life_stage(self) -> LifeStage:
        a = self.age
        if a <= 2:   return LifeStage.INFANT
        if a <= 12:  return LifeStage.CHILD
        if a <= 17:  return LifeStage.TEENAGER
        if a <= 29:  return LifeStage.YOUNG_ADULT
        if a <= 49:  return LifeStage.ADULT
        if a <= 64:  return LifeStage.MIDDLE_AGED
        return LifeStage.ELDERLY

    def remember(self, line: str) -> None:
        self.history.append(f"Age {self.age}: {line}")

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "gender": int(self.gender),
            "age": self.age,
            "country_code": self.country_code,
            "city": self.city,
            "is_urban": self.is_urban,
            "attributes": self.attributes.to_dict(),
            "family_wealth": self.family_wealth,
            "money": self.money,
            "debt": self.debt,
            "education": int(self.education),
            "in_school": self.in_school,
            "school_track": self.school_track,
            "job": self.job,
            "salary": self.salary,
            "vocation_field": self.vocation_field,
            "years_in_role": self.years_in_role,
            "promotion_count": self.promotion_count,
            "last_raise_request_age": self.last_raise_request_age,
            "married": self.married,
            "spouse_name": self.spouse_name,
            "children": [asdict(c) for c in self.children],
            "family": [asdict(f) for f in self.family],
            "loans": [asdict(l) for l in self.loans],
            "investments": [asdict(i) for i in self.investments],
            "alive": self.alive,
            "cause_of_death": self.cause_of_death,
            "moral_ledger": dict(self.moral_ledger),
            "diseases": {k: dict(v) for k, v in self.diseases.items()},
            "history": list(self.history),
            "pending_decision": self.pending_decision,
            "life_stage": int(self.life_stage),
            "subscriptions": {k: dict(v) for k, v in self.subscriptions.items()},
            "purchases": [dict(p) for p in self.purchases],
            "last_treatment": dict(self.last_treatment),
            "event_history": {k: list(v) for k, v in self.event_history.items()},
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        attrs = Attributes(**d["attributes"])
        children = [FamilyMember(**c) for c in d.get("children", [])]
        family = [FamilyMember(**f) for f in d.get("family", [])]
        loans = [LoanHolding(**l) for l in d.get("loans", [])]
        investments = [InvestmentHolding(**i) for i in d.get("investments", [])]
        return cls(
            id=d["id"],
            name=d["name"],
            gender=Gender(d["gender"]),
            age=d["age"],
            country_code=d["country_code"],
            city=d["city"],
            is_urban=d.get("is_urban", True),
            attributes=attrs,
            family_wealth=d["family_wealth"],
            money=d.get("money", 0),
            debt=d.get("debt", 0),
            education=EducationLevel(d.get("education", 0)),
            in_school=d.get("in_school", False),
            school_track=d.get("school_track"),
            job=d.get("job"),
            salary=d.get("salary", 0),
            vocation_field=d.get("vocation_field"),
            years_in_role=d.get("years_in_role", 0),
            promotion_count=d.get("promotion_count", 0),
            last_raise_request_age=d.get("last_raise_request_age"),
            married=d.get("married", False),
            spouse_name=d.get("spouse_name"),
            children=children,
            family=family,
            loans=loans,
            investments=investments,
            alive=d.get("alive", True),
            cause_of_death=d.get("cause_of_death"),
            moral_ledger=d.get("moral_ledger", {}),
            diseases=d.get("diseases", {}),
            history=d.get("history", []),
            pending_decision=d.get("pending_decision"),
            subscriptions=d.get("subscriptions", {}),
            purchases=d.get("purchases", []),
            last_treatment=d.get("last_treatment", {}),
            event_history={k: list(v) for k, v in d.get("event_history", {}).items()},
        )


def _wealth_for_country(country: "Country", rng: random.Random) -> int:
    """Sample household starting wealth from a country's GDP curve.

    Most births land near 0.6x GDP per capita with a long upper tail; a small
    fraction sample from a wealthy elite (5x-20x GDP). The roll respects the
    country's GINI: more unequal countries see wider spreads.
    """
    base = country.gdp_pc * 0.6
    inequality = max(0.15, country.gini / 100)
    if rng.random() < inequality * 0.15:
        # elite roll
        return int(base * rng.uniform(5, 20))
    return int(base * rng.uniform(0.1, 2.5))


_TALENTABLE_ATTRS = (
    "intelligence", "artistic", "musical", "athletic",
    "strength", "endurance", "appearance",
)


def _starting_attributes(country: "Country", rng: random.Random) -> Attributes:
    """Initial 12-attribute roll (#65). Most attributes use a Gaussian
    distribution centered on the country's adjusted baseline so most
    characters cluster near the mean and outliers are rare. Then 1-2
    *talents* get a +15-25 boost and 1-2 *weaknesses* get a -10-15
    penalty — so every character has something they're noticeably
    good at and something they struggle with, instead of being
    average at everything.
    """
    hdi_bonus = (country.hdi - 0.5) * 20      # +/- 10 points
    health_bonus = (country.health_services_pct - 70) * 0.25
    literacy_bonus = (country.literacy - 70) * 0.15

    def roll(base: float, sigma: float) -> int:
        """Gaussian roll, clamped to 1..99."""
        return max(1, min(99, int(base + rng.gauss(0, sigma))))

    attrs = Attributes(
        health=roll(72 + health_bonus, 8),
        happiness=roll(68 + hdi_bonus * 0.3, 10),
        # Lower base (was 50, now 42) so most characters are average
        # rather than above-average. Country literacy still helps.
        intelligence=roll(42 + literacy_bonus, 11),
        artistic=roll(40, 13),
        musical=roll(40, 13),
        athletic=roll(45, 11),
        strength=roll(45, 11),
        endurance=roll(45, 11),
        appearance=roll(48, 12),
        conscience=roll(55, 12),
        wisdom=roll(12, 6),
        resistance=roll(50 + (country.safe_water_pct - 80) * 0.2, 11),
    )

    # Talents: 1-2 attributes get a noticeable boost so the character
    # has something they're recognizably *good* at.
    n_talents = rng.choice([1, 1, 2])  # mostly one talent, sometimes two
    talents = rng.sample(_TALENTABLE_ATTRS, n_talents)
    for attr in talents:
        boost = rng.randint(15, 25)
        current = getattr(attrs, attr)
        setattr(attrs, attr, min(99, current + boost))

    # Weaknesses: 1-2 attributes (different from talents) get a penalty
    # so the character also has clear soft spots.
    weakness_pool = [a for a in _TALENTABLE_ATTRS if a not in talents]
    n_weaknesses = rng.choice([1, 1, 2])
    weaknesses = rng.sample(weakness_pool, n_weaknesses)
    for attr in weaknesses:
        penalty = rng.randint(10, 18)
        current = getattr(attrs, attr)
        setattr(attrs, attr, max(1, current - penalty))

    return attrs


def create_random_character(country: "Country", rng: random.Random | None = None) -> Character:
    """Generate a newborn character in `country`."""
    # Local import to avoid the engine.character ↔ engine.world import cycle.
    from .world import pick_birth_city

    rng = rng or random.Random()
    gender = Gender(rng.randint(0, 1))
    name = _random_name(gender, rng)
    attrs = _starting_attributes(country, rng)
    attrs.clamp()

    family_wealth = _wealth_for_country(country, rng)
    city, is_urban = pick_birth_city(country, rng)

    # Family members — start with a mother, father, and 0-3 siblings.
    mother = FamilyMember("mother", _random_name(Gender.FEMALE, rng), rng.randint(20, 38), True, Gender.FEMALE)
    father = FamilyMember("father", _random_name(Gender.MALE, rng), rng.randint(22, 45), True, Gender.MALE)
    family = [mother, father]
    for _ in range(rng.randint(0, 3)):
        sg = Gender(rng.randint(0, 1))
        family.append(FamilyMember("sibling", _random_name(sg, rng), rng.randint(0, 18), True, sg))

    return Character(
        id=uuid.uuid4().hex[:12],
        name=name,
        gender=gender,
        age=0,
        country_code=country.code,
        city=city,
        is_urban=is_urban,
        attributes=attrs,
        family_wealth=family_wealth,
        money=0,
        family=family,
        history=[],
    )
