"""Tests for the .dat parser and SQLite build."""

from pathlib import Path

from src.data import build_db, parse_dat


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_parse_world_dat_extracts_known_field_names():
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    names = {f.name for f in parsed.schema}
    # Spot-check the original game's field set.
    assert "Country" in names
    assert "Population" in names
    assert "MaleLifeExpectancy" in names
    assert "InfantMortality" in names
    assert "GINI" in names
    assert len(parsed.schema) >= 100, f"only {len(parsed.schema)} fields parsed"


def test_parse_jobs_dat():
    parsed = parse_dat.parse_dat(DATA_DIR / "jobs.dat")
    names = {f.name for f in parsed.schema}
    assert "JobName" in names
    assert "Salary" in names
    assert "Intelligence" in names


def test_recovered_strings_include_country_names():
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    pool = set(parsed.string_pool)
    # Recovered strings should include real country names from the original game.
    assert "Afghanistan" in pool
    assert "Australia" in pool


def test_build_db_creates_expected_tables():
    report = build_db.build()
    assert report["countries"] > 30
    assert report["jobs"] > 10
    assert report["cities"] >= report["countries"]

    conn = build_db.get_connection()
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"countries", "jobs", "investments", "loans", "country_cities", "dat_schema", "games"}.issubset(tables)

        n_countries = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
        assert n_countries == report["countries"]

        # Cities: every country has at least its capital, and many have more.
        n_codes_with_cities = conn.execute(
            "SELECT COUNT(DISTINCT country_code) FROM country_cities"
        ).fetchone()[0]
        assert n_codes_with_cities == n_countries
        n_with_extras = conn.execute(
            "SELECT COUNT(DISTINCT country_code) FROM country_cities WHERE rank > 1"
        ).fetchone()[0]
        assert n_with_extras >= 100, f"only {n_with_extras} countries got >1 city"

        # Spot-check well-known cities
        rows = conn.execute(
            "SELECT name FROM country_cities WHERE country_code='us' ORDER BY rank"
        ).fetchall()
        names = [r["name"] for r in rows]
        assert "Washington" in names
        assert "New York" in names

        # The recovered original-game schema is also stored.
        n_world_fields = conn.execute(
            "SELECT COUNT(*) FROM dat_schema WHERE table_name='world'"
        ).fetchone()[0]
        assert n_world_fields >= 100
    finally:
        conn.close()


def test_extract_cities_per_country():
    """Block boundaries are formed by *neighboring* anchors in the seed list,
    so the function must be called with the full seed country set to give
    each country a tight, single-country window in the pool."""
    from src.data.seed import COUNTRIES
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    cities = parse_dat.extract_cities_per_country(
        parsed.string_pool,
        [c["name"] for c in COUNTRIES],
    )
    assert "New York" in cities["United States"]
    assert "Tokyo" in cities["Japan"]
    assert "Sao Paulo" in cities["Brazil"]
    assert "Lagos" in cities["Nigeria"]
    assert "Algiers" in cities["Algeria"]


def test_extract_descriptions_per_country():
    from src.data.seed import COUNTRIES
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    descs = parse_dat.extract_descriptions_per_country(
        parsed, [c["name"] for c in COUNTRIES]
    )
    # The recovered text is real factbook prose — spot-check that the
    # descriptive substrings show up in the right country.
    assert "Mediterranean" in descs["Algeria"]
    assert "tropical" in descs["Brazil"].lower()
    assert "Canada and Mexico" in descs["United States"]
    assert "Bay of Bengal" in descs["Bangladesh"]
    # Coverage: at least 150 of 199 countries got a usable description.
    non_empty = sum(1 for d in descs.values() if d)
    assert non_empty >= 150, f"only {non_empty} descriptions extracted"
