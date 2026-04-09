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

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Country":
        return cls(**{k: row[k] for k in row.keys()})

    @property
    def flag_filename(self) -> str:
        return f"{self.code}.bmp"


@lru_cache(maxsize=1)
def _all_countries() -> tuple[Country, ...]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM countries").fetchall()
    finally:
        conn.close()
    return tuple(Country.from_row(r) for r in rows)


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
