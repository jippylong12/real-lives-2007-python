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
class Character:
    id: str
    name: str
    gender: Gender
    age: int
    country_code: str
    city: str
    attributes: Attributes
    family_wealth: int                 # starting household wealth in USD-equivalent
    money: int = 0                     # current personal savings
    debt: int = 0
    education: EducationLevel = EducationLevel.NONE
    in_school: bool = False
    job: str | None = None
    salary: int = 0
    married: bool = False
    spouse_name: str | None = None
    children: list[FamilyMember] = field(default_factory=list)
    family: list[FamilyMember] = field(default_factory=list)
    alive: bool = True
    cause_of_death: str | None = None
    moral_ledger: dict[str, int] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    pending_decision: dict | None = None  # event awaiting player choice

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
            "attributes": self.attributes.to_dict(),
            "family_wealth": self.family_wealth,
            "money": self.money,
            "debt": self.debt,
            "education": int(self.education),
            "in_school": self.in_school,
            "job": self.job,
            "salary": self.salary,
            "married": self.married,
            "spouse_name": self.spouse_name,
            "children": [asdict(c) for c in self.children],
            "family": [asdict(f) for f in self.family],
            "alive": self.alive,
            "cause_of_death": self.cause_of_death,
            "moral_ledger": dict(self.moral_ledger),
            "history": list(self.history),
            "pending_decision": self.pending_decision,
            "life_stage": int(self.life_stage),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        attrs = Attributes(**d["attributes"])
        children = [FamilyMember(**c) for c in d.get("children", [])]
        family = [FamilyMember(**f) for f in d.get("family", [])]
        return cls(
            id=d["id"],
            name=d["name"],
            gender=Gender(d["gender"]),
            age=d["age"],
            country_code=d["country_code"],
            city=d["city"],
            attributes=attrs,
            family_wealth=d["family_wealth"],
            money=d.get("money", 0),
            debt=d.get("debt", 0),
            education=EducationLevel(d.get("education", 0)),
            in_school=d.get("in_school", False),
            job=d.get("job"),
            salary=d.get("salary", 0),
            married=d.get("married", False),
            spouse_name=d.get("spouse_name"),
            children=children,
            family=family,
            alive=d.get("alive", True),
            cause_of_death=d.get("cause_of_death"),
            moral_ledger=d.get("moral_ledger", {}),
            history=d.get("history", []),
            pending_decision=d.get("pending_decision"),
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


def _starting_attributes(country: "Country", rng: random.Random) -> Attributes:
    """Initial 12-attribute roll, modulated by country development level."""
    hdi_bonus = (country.hdi - 0.5) * 30   # +/- 15 points
    health_bonus = (country.health_services_pct - 70) * 0.3
    literacy_bonus = (country.literacy - 70) * 0.2

    def roll(base: int, jitter: int) -> int:
        return base + rng.randint(-jitter, jitter)

    return Attributes(
        health=int(75 + health_bonus + rng.randint(-10, 10)),
        happiness=int(72 + hdi_bonus * 0.3 + rng.randint(-12, 12)),
        intelligence=int(50 + literacy_bonus + rng.randint(-15, 15)),
        artistic=roll(50, 25),
        musical=roll(50, 25),
        athletic=roll(50, 20),
        strength=roll(50, 20),
        endurance=roll(50, 20),
        appearance=roll(55, 25),
        conscience=roll(60, 20),
        wisdom=roll(15, 10),
        resistance=int(50 + (country.safe_water_pct - 80) * 0.25 + rng.randint(-15, 15)),
    )


def create_random_character(country: "Country", rng: random.Random | None = None) -> Character:
    """Generate a newborn character in `country`."""
    rng = rng or random.Random()
    gender = Gender(rng.randint(0, 1))
    name = _random_name(gender, rng)
    attrs = _starting_attributes(country, rng)
    attrs.clamp()

    family_wealth = _wealth_for_country(country, rng)

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
        city=country.capital,
        attributes=attrs,
        family_wealth=family_wealth,
        money=0,
        family=family,
        history=[],
    )
