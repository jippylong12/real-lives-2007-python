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
        # After #9: alias coverage + hand-bundled fallbacks for tail-of-pool
        # entries and microstates means every country has at least one extra
        # city beyond its capital.
        assert n_with_extras == n_countries, (
            f"only {n_with_extras}/{n_countries} countries got >1 city"
        )

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


def test_decode_country_record_for_known_countries():
    """Verify the binary decoder produces realistic 2007-era values for
    countries we can hand-validate against the CIA World Factbook."""
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    rows = parse_dat.decode_all_countries(parsed)
    assert len(rows) == 193, f"expected 193 country rows, got {len(rows)}"

    by_name = {r["Country"]: r for r in rows}

    afghan = by_name["Afghanistan"]
    assert afghan["Population"] == 31889000
    assert afghan["InfantMortality"] == 165.0
    assert afghan["MaleLifeExpectancy"] == 43.0
    assert afghan["AtWar"] == 1

    us = by_name["the United States"]
    assert us["Population"] == 301139000
    assert us["MaleLifeExpectancy"] == 75.0
    assert us["FemaleLifeExpectancy"] == 81.0
    assert us["InfantMortality"] == 6.0

    japan = by_name["Japan"]
    assert japan["Population"] == 127467000
    assert japan["FemaleLifeExpectancy"] == 85.0


def test_schema_carries_type_size_offset():
    """The schema parser should now extract type_code, slot_size, and
    record_offset for every field — those are what unblock the data decoder."""
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    population = next(f for f in parsed.schema if f.name == "Population")
    assert population.type_code == 6      # uint32
    assert population.slot_size == 4
    assert population.record_offset == 0x3e

    male_life = next(f for f in parsed.schema if f.name == "MaleLifeExpectancy")
    assert male_life.type_code == 7        # double
    assert male_life.slot_size == 8


def test_country_original_stats_table_populated():
    """The build_db pipeline persists the binary-decoded values into a
    country_original_stats table that the engine can cross-check against."""
    report = build_db.build()
    assert report.get("original_stats", 0) >= 190
    conn = build_db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM country_original_stats WHERE country_code='us'"
        ).fetchone()
        assert row is not None
        assert row["population"] == 301139000
        assert row["male_life_expectancy"] == 75.0
    finally:
        conn.close()


def test_type_4_decodes_as_bool_type_5_as_uint16():
    """Issue #20: type 4 fields are boolean flags, type 5 fields are uint16
    counts/percentages. Verify the decoder honors that distinction."""
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    rows = parse_dat.decode_all_countries(parsed)

    # Every type-4 field across every country should decode as a bool.
    type4_fields = [f for f in parsed.schema if f.type_code == 4]
    assert len(type4_fields) > 0
    for f in type4_fields:
        for r in rows:
            v = r.get(f.name)
            if v is None:
                continue
            assert isinstance(v, bool), f"{f.name} = {v!r} should be bool"

    # Spot-check semantic correctness against hand-validated 2007 facts.
    by_name = {r["Country"]: r for r in rows}
    assert by_name["Afghanistan"]["AtWar"] is True
    assert by_name["Iraq"]["AtWar"] is True
    assert by_name["Sweden"]["AtWar"] is False
    assert by_name["the United States"]["AtWar"] is False
    # USA: all-volunteer force, no conscription. Israel: universal service.
    assert by_name["the United States"]["MilitaryConscription"] is False
    assert by_name["Israel"]["MilitaryConscription"] is True
    # Most type-5 fields are 0..100 percentages
    sweden = by_name["Sweden"]
    assert isinstance(sweden["MaleLiteracy"], int)
    assert sweden["MaleLiteracy"] == 99
    assert sweden["FemaleLiteracy"] == 99


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


def test_long_strings_stitch_across_record_boundaries():
    """Issue #12: encyclopedia prose that crossed a 0x300 record boundary
    used to be split into two halves ('hot summe' / 'rs.'). The continuous
    walker stitches it back together."""
    from src.data.seed import COUNTRIES
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    descs = parse_dat.extract_descriptions_per_country(
        parsed, [c["name"] for c in COUNTRIES]
    )
    # Afghanistan: previously ended in 'hot summe'.
    assert "hot summers" in descs["Afghanistan"]
    assert "hot summe " not in descs["Afghanistan"]
    # Bangladesh: previously began with 'ia, at the head' instead of 'South Asia'.
    assert descs["Bangladesh"].startswith("South Asia")
