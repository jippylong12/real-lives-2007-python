"""
Build the SQLite database used by the game engine.

Combines:
  1. Schema metadata extracted from the original .dat files (via parse_dat.py).
     This proves the rebuild's column set matches the original game's columns.
  2. Curated real-world country / job / loan / investment values from seed.py.

The result lives at <project>/data/reallives.db. The database also stores
runtime game state — saved games, characters, life events — in tables that
the API and engine read/write at runtime.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import parse_dat
from . import seed


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "reallives.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS countries (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    region              TEXT NOT NULL,
    population          INTEGER NOT NULL,
    gdp_pc              INTEGER NOT NULL,
    life_expectancy     REAL NOT NULL,
    infant_mortality    REAL NOT NULL,
    literacy            REAL NOT NULL,
    gini                REAL NOT NULL,
    hdi                 REAL NOT NULL,
    urban_pct           REAL NOT NULL,
    primary_religion    TEXT NOT NULL,
    primary_language    TEXT NOT NULL,
    capital             TEXT NOT NULL,
    currency            TEXT NOT NULL,
    war_freq            REAL NOT NULL,
    disaster_freq       REAL NOT NULL,
    crime_rate          REAL NOT NULL,
    corruption          REAL NOT NULL,
    safe_water_pct      REAL NOT NULL,
    health_services_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    min_education     INTEGER NOT NULL,
    min_intelligence  INTEGER NOT NULL,
    min_age           INTEGER NOT NULL,
    max_age           INTEGER NOT NULL,
    salary_low        INTEGER NOT NULL,
    salary_high       INTEGER NOT NULL,
    urban_only        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS investments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    annual_return_low   REAL NOT NULL,
    annual_return_high  REAL NOT NULL,
    risk                REAL NOT NULL,
    min_amount          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS loans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    max_amount      INTEGER NOT NULL,
    interest_rate   REAL NOT NULL,
    max_years       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS country_cities (
    country_code  TEXT NOT NULL,
    name          TEXT NOT NULL,
    rank          INTEGER NOT NULL,           -- 1 = largest, ascending
    is_capital    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (country_code, name),
    FOREIGN KEY (country_code) REFERENCES countries(code)
);
CREATE INDEX IF NOT EXISTS idx_country_cities_code ON country_cities(country_code);

-- Encyclopedia-style descriptions recovered from world.dat long-string runs.
CREATE TABLE IF NOT EXISTS country_descriptions (
    country_code  TEXT PRIMARY KEY,
    description   TEXT NOT NULL,
    FOREIGN KEY (country_code) REFERENCES countries(code)
);

-- Original-game stats decoded directly from world.dat (2007-era values).
-- This table is independent from the curated `countries` table and is used
-- for cross-checking the rebuild against the binary data.
CREATE TABLE IF NOT EXISTS country_original_stats (
    binary_name             TEXT PRIMARY KEY,
    country_code            TEXT,                  -- match in `countries`, if any
    population              INTEGER,
    birth_rate              REAL,
    death_rate              REAL,
    infant_mortality        REAL,
    male_life_expectancy    REAL,
    female_life_expectancy  REAL,
    inflation_rate          REAL,
    at_war                  INTEGER,
    aids_rate               REAL,
    male_literacy           INTEGER,
    female_literacy         INTEGER,
    hdi                     REAL
);
CREATE INDEX IF NOT EXISTS idx_original_stats_code ON country_original_stats(country_code);

-- Recovered original-game schema (for reference / validation).
CREATE TABLE IF NOT EXISTS dat_schema (
    table_name TEXT NOT NULL,
    field_id   INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    qualified  TEXT,
    PRIMARY KEY (table_name, field_id)
);

-- Persisted runtime state.
CREATE TABLE IF NOT EXISTS games (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    state_json  TEXT NOT NULL
);
"""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build(db_path: Path = DB_PATH, data_dir: Path = DATA_DIR, *, fresh: bool = True) -> dict:
    """Create / refresh the database. Returns a small build report."""

    if fresh and db_path.exists():
        db_path.unlink()

    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)

        # 1. Recovered schema from .dat files.
        parsed_files = parse_dat.parse_all(data_dir)
        for table_name, parsed in parsed_files.items():
            for f in parsed.schema:
                conn.execute(
                    "INSERT OR REPLACE INTO dat_schema (table_name, field_id, field_name, qualified) VALUES (?, ?, ?, ?)",
                    (table_name, f.field_id, f.name, f.qualified_name),
                )

        # 2. Countries.
        for c in seed.COUNTRIES:
            conn.execute(
                """
                INSERT OR REPLACE INTO countries (
                    code, name, region, population, gdp_pc, life_expectancy,
                    infant_mortality, literacy, gini, hdi, urban_pct,
                    primary_religion, primary_language, capital, currency,
                    war_freq, disaster_freq, crime_rate, corruption,
                    safe_water_pct, health_services_pct
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    c["code"], c["name"], c["region"], c["population"], c["gdp_pc"],
                    c["life_expectancy"], c["infant_mortality"], c["literacy"],
                    c["gini"], c["hdi"], c["urban_pct"],
                    c["primary_religion"], c["primary_language"], c["capital"], c["currency"],
                    c["war_freq"], c["disaster_freq"], c["crime_rate"], c["corruption"],
                    c["safe_water_pct"], c["health_services_pct"],
                ),
            )

        # 3. Jobs.
        for j in seed.JOBS:
            conn.execute(
                """
                INSERT INTO jobs (
                    name, min_education, min_intelligence, min_age, max_age,
                    salary_low, salary_high, urban_only
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    j["name"], j["min_education"], j["min_intelligence"],
                    j["min_age"], j["max_age"], j["salary_low"], j["salary_high"],
                    1 if j["urban_only"] else 0,
                ),
            )

        # 4. Investments.
        for inv in seed.INVESTMENTS:
            conn.execute(
                "INSERT INTO investments (name, annual_return_low, annual_return_high, risk, min_amount) VALUES (?,?,?,?,?)",
                (inv["name"], inv["annual_return_low"], inv["annual_return_high"], inv["risk"], inv["min_amount"]),
            )

        # 5. Loans.
        for ln in seed.LOANS:
            conn.execute(
                "INSERT INTO loans (name, max_amount, interest_rate, max_years) VALUES (?,?,?,?)",
                (ln["name"], ln["max_amount"], ln["interest_rate"], ln["max_years"]),
            )

        # 6. Cities — extracted from world.dat string pool, with capital
        # fallback for any country whose block didn't yield a usable run.
        world = parsed_files.get("world")
        names_by_code = {c["name"]: c["code"] for c in seed.COUNTRIES}
        cities_total = 0
        if world is not None:
            extracted = parse_dat.extract_cities_per_country(
                world.string_pool, list(names_by_code.keys())
            )
        else:
            extracted = {}
        for c in seed.COUNTRIES:
            code = c["code"]
            capital = c["capital"]
            cities = [s for s in extracted.get(c["name"], []) if s.lower() != capital.lower()]
            ordered = [capital] + cities
            for rank, name in enumerate(ordered, start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO country_cities (country_code, name, rank, is_capital) VALUES (?,?,?,?)",
                    (code, name, rank, 1 if rank == 1 else 0),
                )
                cities_total += 1

        # 7a. Original-game stats decoded directly from world.dat. The decoder
        # interprets the schema's type/size/offset metadata to pull every
        # field's value out of each fixed-size country row.
        original_total = 0
        if world is not None:
            decoded = parse_dat.decode_all_countries(world)
            # Build a name→code mapping. The binary uses 2007 spellings + a
            # few "the X" prefixes that we strip before lookup.
            def to_code(binary_name: str) -> str | None:
                cleaned = binary_name.strip()
                if cleaned.startswith("the "):
                    cleaned = cleaned[4:]
                # Special-case aliases for binary names that don't match seed.
                BIN_ALIASES = {
                    "Burma": "Myanmar",
                    "Cote d'Ivoire": "Ivory Coast",
                    "Macedonia": "North Macedonia",
                    "Swaziland": "Eswatini",
                    "Runion": "Reunion",
                    "Congo": "Republic of the Congo",
                    "Congo Democratic Republic": "DR Congo",
                }
                cleaned = BIN_ALIASES.get(cleaned, cleaned)
                for c in seed.COUNTRIES:
                    if c["name"] == cleaned:
                        return c["code"]
                return None

            for row in decoded:
                bname = row.get("Country")
                if not isinstance(bname, str) or not bname.strip():
                    continue
                code = to_code(bname)
                pop = row.get("Population")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO country_original_stats (
                        binary_name, country_code, population, birth_rate, death_rate,
                        infant_mortality, male_life_expectancy, female_life_expectancy,
                        inflation_rate, at_war, aids_rate, male_literacy,
                        female_literacy, hdi
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        bname.strip(), code, pop,
                        row.get("BirthRate"), row.get("DeathRate"),
                        row.get("InfantMortality"),
                        row.get("MaleLifeExpectancy"), row.get("FemaleLifeExpectancy"),
                        row.get("InflationRate"), row.get("AtWar"),
                        row.get("AIDS"),
                        row.get("MaleLiteracy"), row.get("FemaleLiteracy"),
                        row.get("HDI"),
                    ),
                )
                original_total += 1

        # 7b. Country encyclopedia descriptions — recovered from the long-string
        # pool of world.dat. Empty descriptions are skipped; the API just
        # returns null for those countries.
        descriptions_total = 0
        if world is not None:
            descriptions = parse_dat.extract_descriptions_per_country(
                world, list(names_by_code.keys())
            )
            for c in seed.COUNTRIES:
                desc = descriptions.get(c["name"], "")
                if desc:
                    conn.execute(
                        "INSERT OR REPLACE INTO country_descriptions (country_code, description) VALUES (?, ?)",
                        (c["code"], desc),
                    )
                    descriptions_total += 1

        conn.commit()

        return {
            "db_path": str(db_path),
            "countries": len(seed.COUNTRIES),
            "jobs": len(seed.JOBS),
            "investments": len(seed.INVESTMENTS),
            "loans": len(seed.LOANS),
            "cities": cities_total,
            "descriptions": descriptions_total,
            "original_stats": original_total,
            "dat_schemas": {name: len(p.schema) for name, p in parsed_files.items()},
            "recovered_strings": {name: len(p.string_pool) for name, p in parsed_files.items()},
        }
    finally:
        conn.close()


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the built database. Builds it on first access if missing."""
    if not db_path.exists():
        build(db_path)
    return _connect(db_path)


if __name__ == "__main__":
    report = build()
    print(json.dumps(report, indent=2))
