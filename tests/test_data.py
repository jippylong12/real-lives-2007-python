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


def test_country_binary_field_catch_all_populated():
    """Issue #17: every binary field decoded from world.dat should land in
    country_binary_field, not just the curated handful in
    country_original_stats. ~150 long-tail fields should be present."""
    report = build_db.build()
    assert report.get("binary_fields", 0) > 20000

    conn = build_db.get_connection()
    try:
        # All 168 schema fields should be persisted across the binary's
        # 189 mappable countries.
        n_fields = conn.execute(
            "SELECT COUNT(DISTINCT field_name) FROM country_binary_field"
        ).fetchone()[0]
        assert n_fields >= 150

        # Spot-check long-tail fields the curated columns don't cover.
        row = conn.execute(
            "SELECT value_num FROM country_binary_field "
            "WHERE country_code='af' AND field_name='EarthquakeAffected'"
        ).fetchone()
        assert row is not None
        assert row["value_num"] > 0  # Afghanistan has earthquakes

        # Iraq human rights flag (binary type-4 bool stored as 0/1).
        row = conn.execute(
            "SELECT value_num FROM country_binary_field "
            "WHERE country_code='iq' AND field_name='Torture'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_binary_overlay_replaces_curated_country_stats():
    """Issue #18: countries that match a row in world.dat get their
    population/life_expectancy/infant_mortality/literacy/HDI overlaid with
    the 2007 binary's values, while countries that don't match (the 6
    territory additions from #7) keep their curated seed.py values."""
    report = build_db.build()
    assert report.get("binary_overlays", 0) >= 180

    conn = build_db.get_connection()
    try:
        # Afghanistan: countries.population must equal country_original_stats.population.
        af = conn.execute(
            "SELECT population, infant_mortality, hdi FROM countries WHERE code='af'"
        ).fetchone()
        af_orig = conn.execute(
            "SELECT population, infant_mortality, hdi FROM country_original_stats WHERE country_code='af'"
        ).fetchone()
        assert af["population"] == af_orig["population"] == 31889000
        assert af["infant_mortality"] == af_orig["infant_mortality"] == 165.0
        assert af["hdi"] == af_orig["hdi"]

        # USA: same overlay holds.
        us = conn.execute(
            "SELECT population FROM countries WHERE code='us'"
        ).fetchone()
        us_orig = conn.execute(
            "SELECT population FROM country_original_stats WHERE country_code='us'"
        ).fetchone()
        assert us["population"] == us_orig["population"] == 301139000

        # Bermuda is a #7 territory addition that isn't in world.dat —
        # its curated seed value should still be in place.
        bm = conn.execute(
            "SELECT population FROM countries WHERE code='bm'"
        ).fetchone()
        # The curated seed value for Bermuda is 64000.
        assert bm["population"] == 64000
    finally:
        conn.close()


def test_at_war_and_conscription_promoted_to_countries_table():
    """Issue #17: AtWar and MilitaryConscription from world.dat get promoted
    into the canonical countries table so the engine can read them via the
    Country dataclass without going through country_binary_field."""
    build_db.build()
    conn = build_db.get_connection()
    try:
        # Iraq and Afghanistan both flagged at_war=1 in 2007.
        for code in ("af", "iq"):
            row = conn.execute(
                "SELECT at_war FROM countries WHERE code=?", (code,)
            ).fetchone()
            assert row["at_war"] == 1, f"{code} should be at_war=1"

        # USA all-volunteer force, no conscription.
        row = conn.execute(
            "SELECT at_war, military_conscription FROM countries WHERE code='us'"
        ).fetchone()
        assert row["at_war"] == 0
        assert row["military_conscription"] == 0

        # Israel: universal conscription.
        row = conn.execute(
            "SELECT military_conscription FROM countries WHERE code='il'"
        ).fetchone()
        assert row["military_conscription"] == 1
    finally:
        conn.close()


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


def test_strings_decode_cp437_not_latin1():
    """Issue #27: the binary stores strings in CP437 (the IBM PC code page
    Borland Delphi 7 used by default on Windows 9x), not Latin-1. The only
    practically-affected entry is Réunion (byte 0x82 = é in CP437)."""
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    rows = parse_dat.decode_all_rows(parsed)
    names = {r["Country"] for r in rows}
    assert "Réunion" in names
    # The legacy mojibake form should be gone.
    assert "R\x82union" not in names

    # And the build_db pipeline should map the cp437-decoded name to ISO 're'.
    build_db.build()
    conn = build_db.get_connection()
    try:
        row = conn.execute(
            "SELECT binary_name, country_code FROM country_original_stats WHERE country_code='re'"
        ).fetchone()
        assert row is not None
        assert row["binary_name"] == "Réunion"
    finally:
        conn.close()


def test_index_field_sanitized_to_uint32():
    """Issue #26: the first schema record in jobs.dat / Investments.dat /
    Loans.dat is an 'IndexField' Delphi row counter and the parser used
    to recover a junk type code (7430). _sanitize_field overrides it to
    type 6 (uint32). The decoded row counter should be 1-indexed and
    monotonically increasing."""
    parsed = parse_dat.parse_dat(DATA_DIR / "jobs.dat")
    idx = next(f for f in parsed.schema if f.name == "IndexField")
    assert idx.type_code == 6
    assert idx.python_type == "uint32"

    rows = parse_dat.decode_all_rows(parsed)
    counters = [r["IndexField"] for r in rows]
    assert counters[:5] == [1, 2, 3, 4, 5]
    assert counters == list(range(1, len(rows) + 1))


def test_every_schema_field_has_recognized_type():
    """Issue #26: after sanitization, every schema field should have a
    recognized type code (no more 'unknown' fields silently dropping data)."""
    for name in ("world.dat", "jobs.dat", "Investments.dat", "Loans.dat"):
        parsed = parse_dat.parse_dat(DATA_DIR / name)
        unknown = [f.name for f in parsed.schema if f.python_type == "unknown"]
        assert not unknown, f"{name}: schema fields with unknown type: {unknown}"


def test_decode_jobs_dat_with_generic_row_decoder():
    """Issue #19: the generic decoder generalizes from world.dat to any
    .dat file with a fixed-row data section. jobs.dat decodes into 131
    rows × 384 bytes."""
    parsed = parse_dat.parse_dat(DATA_DIR / "jobs.dat")
    assert parse_dat._row_size_for(parsed) == 384

    rows = parse_dat.decode_all_rows(parsed)
    assert len(rows) == 131

    # Spot-check the first few jobs against the binary's known content.
    assert rows[0]["JobName"] == "senior government official"
    assert rows[0]["Salary"] == 300000.0
    assert rows[0]["UrbanRural"] == "U"
    assert rows[1]["JobName"] == "community leader"

    # Sanity: every row's JobName decodes as a non-empty string.
    for r in rows:
        assert isinstance(r["JobName"], str) and r["JobName"]


def test_job_original_stats_table_populated():
    """Issue #19: build_db persists the binary-decoded jobs into a
    job_original_stats table that the engine can cross-reference."""
    report = build_db.build()
    assert report.get("jobs_original_stats", 0) == 131

    conn = build_db.get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) FROM job_original_stats").fetchone()[0]
        assert n == 131
        row = conn.execute(
            "SELECT * FROM job_original_stats WHERE binary_index = 0"
        ).fetchone()
        assert row["job_name"] == "senior government official"
        assert row["salary"] == 300000.0
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
    # Coverage: the binary extractor alone reaches at least 175 of 199
    # countries; the build_db pipeline tops it up to 199 with hand-bundled
    # FALLBACK_DESCRIPTIONS for the tail-of-pool entries (issue #11).
    non_empty = sum(1 for d in descs.values() if d)
    assert non_empty >= 175, f"only {non_empty} descriptions extracted from binary"


def test_encyclopedia_no_sentinel_persisted_as_null():
    """Issue #29: 'No' is the binary's 'no entry' sentinel for 7 small
    territories (Andorra, Brunei, Guam, French Polynesia, Guadeloupe,
    Micronesia, New Caledonia). Should persist as NULL, not as the
    literal string."""
    build_db.build()
    conn = build_db.get_connection()
    try:
        # No country in country_original_stats should have key 'No'.
        rows = conn.execute(
            "SELECT country_code FROM country_original_stats WHERE encyclopedia_key = 'No'"
        ).fetchall()
        assert not rows, f"'No' sentinel persisted: {[r['country_code'] for r in rows]}"

        # Andorra (and the other 6) should be NULL.
        for code in ("ad", "bn", "gu"):
            row = conn.execute(
                "SELECT encyclopedia_key FROM country_original_stats WHERE country_code = ?",
                (code,),
            ).fetchone()
            if row is not None:
                assert row["encyclopedia_key"] is None, (
                    f"{code} encyclopedia_key should be NULL, got {row['encyclopedia_key']!r}"
                )

        # And the catch-all country_binary_field shouldn't carry the 'No'
        # entries either.
        n = conn.execute(
            "SELECT COUNT(*) FROM country_binary_field "
            "WHERE field_name='EncyclopediaHistoryName' AND value_text='No'"
        ).fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_encyclopedia_history_name_is_short_basename_key():
    """Issue #13: investigation. Calling decode_value(buf, EncyclopediaHistoryName)
    directly returns a short identifier (8-10 char file-basename style key
    like 'Afghanis', 'BosniaNH'), not inline encyclopedia prose. The
    descriptive text the country sidebar shows is recovered from the
    long-string pool by extract_descriptions_per_country, not from this
    field. The key is persisted into country_original_stats.encyclopedia_key
    for completeness."""
    parsed = parse_dat.parse_dat(DATA_DIR / "world.dat")
    field = next(f for f in parsed.schema if f.name == "EncyclopediaHistoryName")
    # Schema says it's a 31-byte string field.
    assert field.type_code == 1
    assert field.slot_size == 31

    rows = parse_dat.decode_all_countries(parsed)
    by_name = {r["Country"]: r for r in rows}
    af_key = by_name["Afghanistan"]["EncyclopediaHistoryName"]
    us_key = by_name["the United States"]["EncyclopediaHistoryName"]
    br_key = by_name["Brazil"]["EncyclopediaHistoryName"]
    # All keys should be short ASCII identifiers, never paragraphs.
    for k in (af_key, us_key, br_key):
        assert isinstance(k, str)
        assert 0 < len(k) < 15
        assert " " not in k  # not free-form text
    assert af_key == "Afghanis"   # truncated form of Afghanistan
    assert us_key == "US"
    assert br_key == "Brazil"

    # Persisted as encyclopedia_key in country_original_stats.
    build_db.build()
    conn = build_db.get_connection()
    try:
        row = conn.execute(
            "SELECT encyclopedia_key FROM country_original_stats WHERE country_code = 'us'"
        ).fetchone()
        assert row["encyclopedia_key"] == "US"
    finally:
        conn.close()


def test_country_descriptions_cover_every_country():
    """Issue #11: every country in the curated set should land a description
    after the build_db pipeline runs (binary extraction + FALLBACK_DESCRIPTIONS
    for tail-of-pool microstates)."""
    build_db.build()
    conn = build_db.get_connection()
    try:
        n_countries = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
        n_descriptions = conn.execute("SELECT COUNT(*) FROM country_descriptions").fetchone()[0]
        assert n_descriptions == n_countries
        # Spot-check a fallback country.
        row = conn.execute(
            "SELECT description FROM country_descriptions WHERE country_code = 'mc'"
        ).fetchone()
        assert row is not None
        assert "Monaco" in row["description"] or "Mediterranean" in row["description"]
    finally:
        conn.close()


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
