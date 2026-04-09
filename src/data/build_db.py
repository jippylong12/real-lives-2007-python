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
from .. import runtime_paths


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = runtime_paths.data_dir()
DB_PATH = runtime_paths.db_path()


# Binary fields that represent a 0-100 percentage. The 2007 game's data has
# at least one known data-entry typo (Iran SanitationUrban=189 instead of 89,
# issue #28); clamp to 100 in the persist path so downstream consumers can
# trust the values. Counts and rates (PersonsPerTelevision, BirthRate, etc.)
# are NOT in this set — they can legitimately exceed 100.
_PERCENTAGE_FIELDS: frozenset[str] = frozenset({
    "MaleLiteracy", "FemaleLiteracy",
    "PercentUrban",
    "SafeWaterUrban", "SafeWaterRural",
    "SanitationUrban", "SanitationRural",
    "HealthServicesUrban", "HealthServicesRural",
    "PrimarySchool", "SecondarySchoolMale", "SecondarySchoolFemale",
    "TrainedBirth",
})


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS countries (
    code                    TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    region                  TEXT NOT NULL,
    population              INTEGER NOT NULL,
    gdp_pc                  INTEGER NOT NULL,
    life_expectancy         REAL NOT NULL,
    infant_mortality        REAL NOT NULL,
    literacy                REAL NOT NULL,
    gini                    REAL NOT NULL,
    hdi                     REAL NOT NULL,
    urban_pct               REAL NOT NULL,
    primary_religion        TEXT NOT NULL,
    primary_language        TEXT NOT NULL,
    capital                 TEXT NOT NULL,
    currency                TEXT NOT NULL,
    war_freq                REAL NOT NULL,
    disaster_freq           REAL NOT NULL,
    crime_rate              REAL NOT NULL,
    corruption              REAL NOT NULL,
    safe_water_pct          REAL NOT NULL,
    health_services_pct     REAL NOT NULL,
    at_war                  INTEGER NOT NULL DEFAULT 0,    -- #17, from binary
    military_conscription   INTEGER NOT NULL DEFAULT 0     -- #17, from binary
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

-- Catch-all long-format table for every binary field decoded from world.dat
-- (#17). The Population/HDI/MaleLifeExpectancy fields are *also* persisted
-- to country_original_stats and the canonical countries table; this table
-- captures the long tail (50+ disaster history fields, ethnic group
-- fractions, exchange rates, war province / war type, etc.) so callers can
-- query any decoded field by name without each new use case having to widen
-- a hand-curated schema.
CREATE TABLE IF NOT EXISTS country_binary_field (
    country_code  TEXT NOT NULL,
    field_name    TEXT NOT NULL,
    value_text    TEXT,
    value_num     REAL,
    PRIMARY KEY (country_code, field_name)
);
CREATE INDEX IF NOT EXISTS idx_country_binary_field_name
    ON country_binary_field(field_name);

-- Original-game job catalogue decoded directly from jobs.dat (#19). The
-- binary ships 131 jobs vs. the curated seed.JOBS list of ~30. This table
-- exposes every binary job for cross-reference; the engine still uses the
-- curated table for now (the binary's salaries / requirements use a
-- different scale).
CREATE TABLE IF NOT EXISTS job_original_stats (
    binary_index            INTEGER PRIMARY KEY,
    job_name                TEXT NOT NULL,
    minimum_age             INTEGER,
    max_age                 INTEGER,
    education               TEXT,
    urban_rural             TEXT,
    self_employed           INTEGER,
    intelligence            INTEGER,
    strength                INTEGER,
    endurance               INTEGER,
    artistic                INTEGER,
    musical                 INTEGER,
    athletic                INTEGER,
    salary                  REAL,
    seacoast_only           INTEGER,
    forest_only             INTEGER
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
    hdi                     REAL,
    encyclopedia_key        TEXT      -- short basename pointer (#13)
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

        # Pre-decode world.dat once and key it by ISO code so steps 2 (country
        # insert with binary at_war/military_conscription) and 7a/7c
        # (country_original_stats + country_binary_field) can share the same
        # decoded values without re-running the decoder.
        world = parsed_files.get("world")
        decoded_world: list[dict] = []
        decoded_by_code: dict[str, dict] = {}
        if world is not None:
            decoded_world = parse_dat.decode_all_rows(world)

            def _to_code(binary_name: str) -> str | None:
                cleaned = binary_name.strip()
                if cleaned.startswith("the "):
                    cleaned = cleaned[4:]
                BIN_ALIASES = {
                    "Burma": "Myanmar",
                    "Cote d'Ivoire": "Ivory Coast",
                    "Macedonia": "North Macedonia",
                    "Swaziland": "Eswatini",
                    "Réunion": "Reunion",   # CP437-decoded form (#27)
                    "Runion": "Reunion",    # legacy stripped form, just in case
                    "Congo": "Republic of the Congo",
                    "Congo Democratic Republic": "DR Congo",
                }
                cleaned = BIN_ALIASES.get(cleaned, cleaned)
                for cc in seed.COUNTRIES:
                    if cc["name"] == cleaned:
                        return cc["code"]
                return None

            for row in decoded_world:
                bname = row.get("Country")
                if not isinstance(bname, str) or not bname.strip():
                    continue
                code = _to_code(bname)
                if code:
                    decoded_by_code[code] = row

        # 2. Countries — curated values from seed, with binary overlays
        # (#18 hybrid path). For any country present in world.dat, we
        # override the population/life expectancy/infant mortality/literacy/
        # HDI with the 2007 binary's values; the curated extras seed.py
        # carries (war_freq, disaster_freq, crime_rate, urban_pct, region,
        # religion, language) stay as-is — none of those exist in the binary.
        # Countries not in the binary (the 6 territory additions from #7)
        # keep their curated values across the board.
        overlay_countries = 0
        for c in seed.COUNTRIES:
            bin_row = decoded_by_code.get(c["code"], {})

            population = c["population"]
            life_expectancy = c["life_expectancy"]
            infant_mortality = c["infant_mortality"]
            literacy = c["literacy"]
            hdi = c["hdi"]
            if bin_row:
                bp = bin_row.get("Population")
                if isinstance(bp, (int, float)) and bp > 0:
                    population = int(bp)
                male = bin_row.get("MaleLifeExpectancy")
                female = bin_row.get("FemaleLifeExpectancy")
                if isinstance(male, (int, float)) and isinstance(female, (int, float)) and male > 0 and female > 0:
                    life_expectancy = (male + female) / 2.0
                im = bin_row.get("InfantMortality")
                if isinstance(im, (int, float)) and im >= 0:
                    infant_mortality = float(im)
                ml = bin_row.get("MaleLiteracy")
                fl = bin_row.get("FemaleLiteracy")
                if isinstance(ml, (int, float)) and isinstance(fl, (int, float)) and ml > 0 and fl > 0:
                    literacy = (ml + fl) / 2.0
                bh = bin_row.get("HDI")
                if isinstance(bh, (int, float)) and bh > 0:
                    hdi = float(bh)
                overlay_countries += 1

            at_war = 1 if bin_row.get("AtWar") else 0
            conscription = 1 if bin_row.get("MilitaryConscription") else 0
            conn.execute(
                """
                INSERT OR REPLACE INTO countries (
                    code, name, region, population, gdp_pc, life_expectancy,
                    infant_mortality, literacy, gini, hdi, urban_pct,
                    primary_religion, primary_language, capital, currency,
                    war_freq, disaster_freq, crime_rate, corruption,
                    safe_water_pct, health_services_pct,
                    at_war, military_conscription
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    c["code"], c["name"], c["region"], population, c["gdp_pc"],
                    life_expectancy, infant_mortality, literacy,
                    c["gini"], hdi, c["urban_pct"],
                    c["primary_religion"], c["primary_language"], c["capital"], c["currency"],
                    c["war_freq"], c["disaster_freq"], c["crime_rate"], c["corruption"],
                    c["safe_water_pct"], c["health_services_pct"],
                    at_war, conscription,
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
            # Fall back to hand-bundled cities if the binary extractor didn't
            # find anything for this country (issue #9 — tail-of-pool entries
            # and microstates whose binary block is too tight to anchor on).
            if not cities and code in seed.FALLBACK_CITIES:
                cities = [s for s in seed.FALLBACK_CITIES[code] if s.lower() != capital.lower()]
            ordered = [capital] + cities
            for rank, name in enumerate(ordered, start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO country_cities (country_code, name, rank, is_capital) VALUES (?,?,?,?)",
                    (code, name, rank, 1 if rank == 1 else 0),
                )
                cities_total += 1

        # 6b. Original-game job catalogue decoded directly from jobs.dat (#19).
        # The generic row decoder works on any .dat file with a fixed-row
        # data section, not just world.dat.
        jobs_orig_total = 0
        jobs_parsed = parsed_files.get("jobs")
        if jobs_parsed is not None:
            for i, row in enumerate(parse_dat.decode_all_rows(jobs_parsed)):
                name = row.get("JobName")
                if not isinstance(name, str) or not name.strip():
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO job_original_stats (
                        binary_index, job_name, minimum_age, max_age, education,
                        urban_rural, self_employed, intelligence, strength, endurance,
                        artistic, musical, athletic, salary, seacoast_only, forest_only
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        i, name.strip(),
                        row.get("MinimumAge"), row.get("MaxAge"),
                        row.get("Education"), row.get("UrbanRural"),
                        1 if row.get("SelfEmployed") else 0,
                        row.get("Intelligence"), row.get("Strength"), row.get("Endurance"),
                        row.get("Artistic"), row.get("Musical"), row.get("Athletic"),
                        row.get("Salary"),
                        1 if row.get("Seacoast") else 0,
                        1 if row.get("Forest") else 0,
                    ),
                )
                jobs_orig_total += 1

        # 7a. Original-game stats decoded directly from world.dat. The decoder
        # interprets the schema's type/size/offset metadata to pull every
        # field's value out of each fixed-size country row.
        original_total = 0
        binary_field_total = 0
        for row in decoded_world:
            bname = row.get("Country")
            if not isinstance(bname, str) or not bname.strip():
                continue
            # Find the matching code by scanning decoded_by_code for this row.
            code = next((cc for cc, rr in decoded_by_code.items() if rr is row), None)
            pop = row.get("Population")
            conn.execute(
                """
                INSERT OR REPLACE INTO country_original_stats (
                    binary_name, country_code, population, birth_rate, death_rate,
                    infant_mortality, male_life_expectancy, female_life_expectancy,
                    inflation_rate, at_war, aids_rate, male_literacy,
                    female_literacy, hdi, encyclopedia_key
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    bname.strip(), code, pop,
                    row.get("BirthRate"), row.get("DeathRate"),
                    row.get("InfantMortality"),
                    row.get("MaleLifeExpectancy"), row.get("FemaleLifeExpectancy"),
                    row.get("InflationRate"),
                    1 if row.get("AtWar") else 0,
                    row.get("AIDS"),
                    row.get("MaleLiteracy"), row.get("FemaleLiteracy"),
                    row.get("HDI"),
                    # 'No' is the binary's "no encyclopedia entry" sentinel
                    # used by 7 small territories (Andorra, Brunei, Guam,
                    # French Polynesia, Guadeloupe, Micronesia, New
                    # Caledonia). Persist as NULL instead of the literal
                    # string (#29).
                    None if row.get("EncyclopediaHistoryName") == "No" else row.get("EncyclopediaHistoryName"),
                ),
            )
            original_total += 1

            # 7c. Long-format catch-all for every binary field (#17). This
            # captures the 150+ fields beyond the curated columns: disaster
            # history (Avalanche*, Famine*, Earthquake*, ...), human-rights
            # flags, military service rules, ethnic group fractions,
            # exchange rate, war province / war type, etc.
            if code is None:
                continue
            for fname, val in row.items():
                if val is None:
                    continue
                # Skip 'No' encyclopedia sentinel — it's not a real key (#29).
                if fname == "EncyclopediaHistoryName" and val == "No":
                    continue
                if isinstance(val, bool):
                    value_text = None
                    value_num = float(int(val))
                elif isinstance(val, (int, float)):
                    value_text = None
                    value_num = float(val)
                    # Clamp known-percentage fields against the 2007 binary's
                    # data-entry errors (Iran SanitationUrban=189, #28).
                    if fname in _PERCENTAGE_FIELDS and value_num > 100:
                        value_num = 100.0
                else:
                    s = str(val).strip("\x00").strip()
                    if not s:
                        continue
                    value_text = s
                    value_num = None
                conn.execute(
                    "INSERT OR REPLACE INTO country_binary_field "
                    "(country_code, field_name, value_text, value_num) "
                    "VALUES (?, ?, ?, ?)",
                    (code, fname, value_text, value_num),
                )
                binary_field_total += 1

        # 7b. Country encyclopedia descriptions — recovered from the long-string
        # pool of world.dat, with seed.FALLBACK_DESCRIPTIONS as a fallback for
        # countries the binary extractor can't anchor on (issue #11).
        descriptions_total = 0
        if world is not None:
            descriptions = parse_dat.extract_descriptions_per_country(
                world, list(names_by_code.keys())
            )
        else:
            descriptions = {}
        for c in seed.COUNTRIES:
            desc = descriptions.get(c["name"], "")
            if not desc and c["code"] in seed.FALLBACK_DESCRIPTIONS:
                desc = seed.FALLBACK_DESCRIPTIONS[c["code"]]
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
            "binary_fields": binary_field_total,
            "binary_overlays": overlay_countries,
            "jobs_original_stats": jobs_orig_total,
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
