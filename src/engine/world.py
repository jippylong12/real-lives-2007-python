"""
Country lookup helper backed by the SQLite database.

The original game (and the decompiled `world/` folder) treats country choice
as the foundation of the entire simulation: it dictates death probability,
event frequencies, salary scales, and starting wealth. This module exposes a
small read-only interface so the rest of the engine doesn't need to know
about SQLite.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from ..data.build_db import get_connection


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    region: str
    population: int
    gdp_pc: int
    life_expectancy: float
    infant_mortality: float
    literacy: float
    gini: float
    hdi: float
    urban_pct: float
    primary_religion: str
    primary_language: str
    capital: str
    currency: str
    war_freq: float
    disaster_freq: float
    crime_rate: float
    corruption: float
    safe_water_pct: float
    health_services_pct: float
    at_war: int = 0                    # binary AtWar flag (#17)
    military_conscription: int = 0     # binary MilitaryConscription flag (#17)
    divorce_rate: float | None = None  # #92, lifetime probability per marriage

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Country":
        # Filter to fields the dataclass actually accepts so older
        # databases that don't have a column yet (or newer ones with
        # extra columns we haven't surfaced) don't blow up.
        accepted = set(cls.__dataclass_fields__.keys())
        return cls(**{k: row[k] for k in row.keys() if k in accepted})

    @property
    def flag_filename(self) -> str:
        return f"{self.code}.bmp"


@dataclass(frozen=True)
class City:
    country_code: str
    name: str
    rank: int           # 1 = capital / largest city
    is_capital: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "City":
        return cls(
            country_code=row["country_code"],
            name=row["name"],
            rank=row["rank"],
            is_capital=bool(row["is_capital"]),
        )


@lru_cache(maxsize=1)
def _all_countries() -> tuple[Country, ...]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM countries").fetchall()
    finally:
        conn.close()
    return tuple(Country.from_row(r) for r in rows)


@lru_cache(maxsize=1)
def _cities_by_country() -> dict[str, tuple[City, ...]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT country_code, name, rank, is_capital FROM country_cities ORDER BY country_code, rank"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[City]] = {}
    for r in rows:
        out.setdefault(r["country_code"], []).append(City.from_row(r))
    return {k: tuple(v) for k, v in out.items()}


def cities_for(country_code: str) -> tuple[City, ...]:
    """All known cities for `country_code` in rank order (capital first)."""
    return _cities_by_country().get(country_code.lower(), ())


@lru_cache(maxsize=1)
def _descriptions() -> dict[str, str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT country_code, description FROM country_descriptions").fetchall()
    finally:
        conn.close()
    return {r["country_code"]: r["description"] for r in rows}


def description_for(country_code: str) -> str | None:
    """Encyclopedia text recovered from world.dat for ``country_code``, or None
    if no description was extractable for that country."""
    return _descriptions().get(country_code.lower())


# Type-4 (bool) fields in world.dat — re-coerced from value_num=0.0/1.0
# back to Python bool when surfaced through binary_facts_for(). Tracked
# explicitly because we can't tell a stored 1.0 in country_binary_field
# from a count-of-1 without consulting the schema.
_BOOL_BINARY_FIELDS: frozenset[str] = frozenset({
    "AtWar", "ExtrajudicialExecutions", "PoliticalPrisoners", "Torture",
    "HumanRightsDefenders", "Journalists", "CruelPunishment", "Impunity",
    "PrisonConditions", "UnfairTrials", "WomensRights", "ForcibleReturn",
    "MilitaryConscription", "AlternativeService", "MarketEconomy",
})


def binary_facts_for(country_code: str) -> dict:
    """Return the country's full binary fact sheet (#30): every field
    decoded from world.dat as a name → value mapping. Numeric fields come
    back as float, type-4 boolean flags as Python bool, string fields as
    strings.

    Returns an empty dict if the country isn't in the binary (the 6
    territory additions from #7 — Bermuda, Anguilla, French Guiana, etc.).
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT field_name, value_text, value_num "
            "FROM country_binary_field WHERE country_code = ?",
            (country_code.lower(),),
        ).fetchall()
    finally:
        conn.close()
    out: dict = {}
    for r in rows:
        name = r["field_name"]
        if r["value_text"] is not None:
            out[name] = r["value_text"]
        elif r["value_num"] is not None:
            v = r["value_num"]
            if name in _BOOL_BINARY_FIELDS:
                out[name] = bool(v)
            else:
                out[name] = v
    return out


def pick_birth_city(country: "Country", rng: random.Random) -> tuple[str, bool]:
    """Choose a (city_name, is_urban) pair for a newborn in `country`.

    Cities are weighted by inverse rank (largest city most likely). With
    probability ``1 - urban_pct/100`` the character is instead born in a
    rural village near a randomly chosen city — those characters get
    ``is_urban = False`` and miss out on urban-only jobs.
    """
    cities = cities_for(country.code)
    if not cities:
        return country.capital, country.urban_pct >= 50
    weights = [1.0 / c.rank for c in cities]
    chosen = rng.choices(cities, weights=weights, k=1)[0]
    urban_roll = rng.random() * 100
    if urban_roll < country.urban_pct:
        return chosen.name, True
    return f"a village near {chosen.name}", False


def all_countries() -> list[Country]:
    return list(_all_countries())


def get_country(code: str) -> Country | None:
    code = code.lower()
    for c in _all_countries():
        if c.code == code:
            return c
    return None


def random_country(rng: random.Random | None = None) -> Country:
    """Pick a country weighted by population.

    Real Lives 2007 weights birth-country randomization roughly by population:
    being born in India is much more likely than being born in Iceland. We
    take the square root of the population to slightly compress the curve so
    rare countries still come up frequently enough to be discoverable.
    """
    rng = rng or random.Random()
    countries = list(_all_countries())
    weights = [max(1.0, c.population) ** 0.5 for c in countries]
    return rng.choices(countries, weights=weights, k=1)[0]


def search_countries(query: str) -> list[Country]:
    q = query.strip().lower()
    return [c for c in _all_countries() if q in c.name.lower() or q == c.code]
