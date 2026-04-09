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

    conn = build_db.get_connection()
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"countries", "jobs", "investments", "loans", "dat_schema", "games"}.issubset(tables)

        n_countries = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
        assert n_countries == report["countries"]

        # The recovered original-game schema is also stored.
        n_world_fields = conn.execute(
            "SELECT COUNT(*) FROM dat_schema WHERE table_name='world'"
        ).fetchone()[0]
        assert n_world_fields >= 100
    finally:
        conn.close()
