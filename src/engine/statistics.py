"""
Cross-life statistics archive (#70).

Every completed life writes a row into the ``life_archive`` SQLite table
on death. The dashboard aggregates across all rows for the player's
meta-history view: lives lived per country, average lifespan, top
careers, talent distributions, milestone "best of" cards.

Robustness layer
----------------
Every successful insert is *also* appended to a JSONL sidecar at
``<user_data_dir>/life_archive.jsonl``. The sidecar is append-only so
corruption can only ever lose the most recent line. ``restore_jsonl_into_db``
runs once at server startup and replays any rows from the sidecar that
aren't in the DB — meaning a wiped DB auto-recovers from the sidecar
file. Combined with ``export_archive`` / ``import_archive`` (manual
JSON backups), the archive is durable to:

  - DB rebuilds (``python -m src.data.build_db``)
  - Accidental file deletion (sidecar replays)
  - Machine migration (export → copy file → import)
  - Casual corruption (only the latest row is at risk)
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .. import runtime_paths
from ..data.build_db import get_connection

if TYPE_CHECKING:  # avoid circular import at runtime
    from .game import GameState


logger = logging.getLogger(__name__)


# The JSONL sidecar lives next to the SQLite DB in the per-user
# writable directory so it follows the same install / data layout.
def _sidecar_path() -> Path:
    return runtime_paths.user_data_dir() / "life_archive.jsonl"


# Attribute names that get peak-tracked. Skips health + happiness
# (those are state, not talents).
_PEAK_ATTRIBUTES = (
    "intelligence", "artistic", "musical", "athletic",
    "strength", "endurance", "appearance", "conscience",
    "wisdom", "resistance",
)


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def write_archive_row(state: "GameState") -> None:
    """Insert a row into life_archive for a freshly-deceased character.
    Called from game.advance_year right after the character.alive flag
    flips to False. Best-effort: logs and swallows on failure since the
    death screen shouldn't break if persistence fails."""
    try:
        row = _build_row(state)
    except Exception:
        logger.exception("life_archive: failed to build row for game %s", state.id)
        return
    try:
        _insert_row(row)
    except Exception:
        logger.exception("life_archive: failed to insert row for game %s", state.id)
        return
    try:
        _append_jsonl_sidecar(row)
    except Exception:
        # Sidecar is best-effort — DB write succeeded, durability layer
        # is "nice to have". Log and continue.
        logger.exception("life_archive: failed to append sidecar for game %s", state.id)


def _build_row(state: "GameState") -> dict:
    """Pull a flat dict of archive columns out of a finished GameState."""
    from . import finances
    from ..data.build_db import get_connection as _gc

    char = state.character
    snapshot = state.to_dict()
    portfolio = finances.portfolio_value(char)
    final_net_worth = char.money + portfolio - char.debt
    peak_net_worth = max(char.peak_net_worth, final_net_worth)

    # Country name lookup — fall back to the code if missing.
    country_name = char.country_code
    try:
        conn = _gc()
        try:
            cn = conn.execute(
                "SELECT name FROM countries WHERE code = ?", (char.country_code,)
            ).fetchone()
            if cn:
                country_name = cn["name"]
        finally:
            conn.close()
    except Exception:
        pass

    peaks = char.peak_attributes or {}
    diseases_count = len(char.diseases or {})
    children_count = len(char.children or [])
    born_year = state.year - char.age

    return {
        "id": state.id,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "name": char.name,
        "gender": int(char.gender),
        "country_code": char.country_code,
        "country_name": country_name,
        "born_year": born_year,
        "died_year": state.year,
        "age_at_death": char.age,
        "cause_of_death": char.cause_of_death,
        "final_job": char.job,
        "final_salary": char.salary or 0,
        "lifetime_earnings": char.lifetime_earnings or 0,
        "peak_net_worth": peak_net_worth,
        "education": int(char.education),
        "married": 1 if char.married else 0,
        "children_count": children_count,
        "diseases_count": diseases_count,
        "promotion_count": char.promotion_count or 0,
        "peak_intelligence": peaks.get("intelligence"),
        "peak_artistic": peaks.get("artistic"),
        "peak_musical": peaks.get("musical"),
        "peak_athletic": peaks.get("athletic"),
        "peak_strength": peaks.get("strength"),
        "peak_endurance": peaks.get("endurance"),
        "peak_appearance": peaks.get("appearance"),
        "peak_conscience": peaks.get("conscience"),
        "peak_wisdom": peaks.get("wisdom"),
        "peak_resistance": peaks.get("resistance"),
        "snapshot_json": json.dumps(snapshot),
    }


_INSERT_COLS = (
    "id", "archived_at", "name", "gender", "country_code", "country_name",
    "born_year", "died_year", "age_at_death", "cause_of_death",
    "final_job", "final_salary", "lifetime_earnings", "peak_net_worth",
    "education", "married", "children_count", "diseases_count",
    "promotion_count",
    "peak_intelligence", "peak_artistic", "peak_musical", "peak_athletic",
    "peak_strength", "peak_endurance", "peak_appearance", "peak_conscience",
    "peak_wisdom", "peak_resistance",
    "snapshot_json",
)
_INSERT_SQL = (
    f"INSERT OR REPLACE INTO life_archive ({', '.join(_INSERT_COLS)}) "
    f"VALUES ({', '.join('?' * len(_INSERT_COLS))})"
)


def _insert_row(row: dict) -> None:
    conn = get_connection()
    try:
        conn.execute(_INSERT_SQL, tuple(row[c] for c in _INSERT_COLS))
        conn.commit()
    finally:
        conn.close()


def _append_jsonl_sidecar(row: dict) -> None:
    """Append a single row as a JSON line to the sidecar file. Append-only
    so corruption can only ever damage the last line. Recovery via
    restore_jsonl_into_db()."""
    path = _sidecar_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def restore_jsonl_into_db() -> int:
    """Replay the JSONL sidecar into life_archive. Skips rows whose id
    is already present. Returns the number of rows restored. Called
    once at server startup so a wiped or rebuilt DB auto-recovers from
    the sidecar file."""
    path = _sidecar_path()
    if not path.exists():
        return 0
    conn = get_connection()
    try:
        existing_ids = {
            r[0] for r in conn.execute("SELECT id FROM life_archive").fetchall()
        }
        restored = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("life_archive: malformed sidecar line skipped")
                    continue
                rid = row.get("id")
                if not rid or rid in existing_ids:
                    continue
                # Defensive: ensure all expected columns are present.
                if not all(c in row for c in _INSERT_COLS):
                    logger.warning("life_archive: sidecar row missing columns, skipped (id=%s)", rid)
                    continue
                conn.execute(_INSERT_SQL, tuple(row[c] for c in _INSERT_COLS))
                existing_ids.add(rid)
                restored += 1
        conn.commit()
        if restored:
            logger.info("life_archive: restored %d row(s) from sidecar", restored)
        return restored
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Aggregation queries
# ---------------------------------------------------------------------------

def global_stats() -> dict:
    """Top-line aggregates across the whole archive."""
    conn = get_connection()
    try:
        n_lives = conn.execute("SELECT COUNT(*) FROM life_archive").fetchone()[0]
        if n_lives == 0:
            return {
                "total_lives": 0, "distinct_countries": 0,
                "avg_lifespan": 0, "longest_lifespan": 0,
                "total_lifetime_earnings": 0, "total_marriages": 0,
                "total_children": 0,
            }
        row = conn.execute("""
            SELECT
                COUNT(*) AS n_lives,
                COUNT(DISTINCT country_code) AS distinct_countries,
                AVG(age_at_death) AS avg_lifespan,
                MAX(age_at_death) AS longest_lifespan,
                SUM(lifetime_earnings) AS total_earnings,
                SUM(married) AS total_marriages,
                SUM(children_count) AS total_children
            FROM life_archive
        """).fetchone()
        return {
            "total_lives": int(row["n_lives"]),
            "distinct_countries": int(row["distinct_countries"]),
            "avg_lifespan": round(row["avg_lifespan"] or 0, 1),
            "longest_lifespan": int(row["longest_lifespan"] or 0),
            "total_lifetime_earnings": int(row["total_earnings"] or 0),
            "total_marriages": int(row["total_marriages"] or 0),
            "total_children": int(row["total_children"] or 0),
        }
    finally:
        conn.close()


def per_country_stats() -> list[dict]:
    """One row per country with at least one archived life. Sorted by
    n_lives desc."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                country_code,
                country_name,
                COUNT(*) AS n_lives,
                AVG(age_at_death) AS avg_lifespan,
                MAX(age_at_death) AS longest_lived,
                MAX(lifetime_earnings) AS highest_earning
            FROM life_archive
            GROUP BY country_code
            ORDER BY n_lives DESC, country_name ASC
        """).fetchall()
        out = []
        for r in rows:
            # Most common job + cause of death require a sub-aggregate.
            top_job_row = conn.execute(
                """
                SELECT final_job, COUNT(*) AS n
                FROM life_archive
                WHERE country_code = ? AND final_job IS NOT NULL
                GROUP BY final_job ORDER BY n DESC LIMIT 1
                """,
                (r["country_code"],),
            ).fetchone()
            top_cause_row = conn.execute(
                """
                SELECT cause_of_death, COUNT(*) AS n
                FROM life_archive
                WHERE country_code = ? AND cause_of_death IS NOT NULL
                GROUP BY cause_of_death ORDER BY n DESC LIMIT 1
                """,
                (r["country_code"],),
            ).fetchone()
            out.append({
                "country_code": r["country_code"],
                "country_name": r["country_name"],
                "n_lives": int(r["n_lives"]),
                "avg_lifespan": round(r["avg_lifespan"] or 0, 1),
                "longest_lived": int(r["longest_lived"] or 0),
                "highest_earning": int(r["highest_earning"] or 0),
                "top_job": top_job_row["final_job"] if top_job_row else None,
                "top_cause": top_cause_row["cause_of_death"] if top_cause_row else None,
            })
        return out
    finally:
        conn.close()


def career_stats() -> list[dict]:
    """Top 10 final jobs by occurrence with avg lifespan + earnings."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                final_job,
                COUNT(*) AS n_lives,
                AVG(age_at_death) AS avg_lifespan,
                AVG(lifetime_earnings) AS avg_earnings,
                MAX(lifetime_earnings) AS max_earnings
            FROM life_archive
            WHERE final_job IS NOT NULL
            GROUP BY final_job
            ORDER BY n_lives DESC
            LIMIT 10
        """).fetchall()
        return [{
            "job": r["final_job"],
            "n_lives": int(r["n_lives"]),
            "avg_lifespan": round(r["avg_lifespan"] or 0, 1),
            "avg_earnings": int(r["avg_earnings"] or 0),
            "max_earnings": int(r["max_earnings"] or 0),
        } for r in rows]
    finally:
        conn.close()


def talent_stats() -> dict:
    """For each peak attribute, count how many lives reached >= 75."""
    conn = get_connection()
    try:
        out: dict[str, dict] = {}
        for attr in _PEAK_ATTRIBUTES:
            col = f"peak_{attr}"
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM life_archive WHERE {col} >= 75"
            ).fetchone()
            avg_row = conn.execute(
                f"SELECT AVG({col}) AS a FROM life_archive WHERE {col} IS NOT NULL"
            ).fetchone()
            out[attr] = {
                "talented_count": int(row["n"] or 0),
                "average_peak": round(avg_row["a"] or 0, 1),
            }
        return out
    finally:
        conn.close()


def milestones() -> dict:
    """One winner per category — small dict with name, country, value, id."""
    conn = get_connection()
    try:
        def _fetch(order_by: str) -> dict | None:
            r = conn.execute(
                f"""
                SELECT id, name, country_name, age_at_death,
                       lifetime_earnings, promotion_count,
                       diseases_count, children_count
                FROM life_archive
                ORDER BY {order_by} LIMIT 1
                """
            ).fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "name": r["name"],
                "country_name": r["country_name"],
                "age_at_death": int(r["age_at_death"]),
                "lifetime_earnings": int(r["lifetime_earnings"]),
                "promotion_count": int(r["promotion_count"]),
                "diseases_count": int(r["diseases_count"]),
                "children_count": int(r["children_count"]),
            }
        return {
            "oldest": _fetch("age_at_death DESC"),
            "wealthiest": _fetch("lifetime_earnings DESC"),
            "most_decorated": _fetch("promotion_count DESC"),
            "most_diseases_survived": _fetch("diseases_count DESC"),
            "most_children": _fetch("children_count DESC"),
        }
    finally:
        conn.close()


def list_lives(limit: int = 10, offset: int = 0) -> dict:
    """Paginated archive list (most recent first). Default limit is 10
    — the dashboard's 'Recent lives' section is intentionally short
    to keep the screen scannable. Use list_favorites() for the
    permanent set the player has explicitly bookmarked."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM life_archive").fetchone()[0]
        rows = conn.execute(
            """
            SELECT id, name, country_code, country_name, gender,
                   born_year, died_year, age_at_death, cause_of_death,
                   final_job, lifetime_earnings, peak_net_worth,
                   married, children_count, is_favorite
            FROM life_archive
            ORDER BY archived_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return {
            "total": int(total),
            "lives": [_row_to_summary(r) for r in rows],
        }
    finally:
        conn.close()


def list_favorites() -> list[dict]:
    """Return every favorited life — no limit, no pagination. The
    permanent curated set the player wants to keep visible across
    all their playtime."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, country_code, country_name, gender,
                   born_year, died_year, age_at_death, cause_of_death,
                   final_job, lifetime_earnings, peak_net_worth,
                   married, children_count, is_favorite
            FROM life_archive
            WHERE is_favorite = 1
            ORDER BY archived_at DESC
            """
        ).fetchall()
        return [_row_to_summary(r) for r in rows]
    finally:
        conn.close()


def _row_to_summary(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "country_code": r["country_code"],
        "country_name": r["country_name"],
        "gender": int(r["gender"]),
        "born_year": int(r["born_year"]),
        "died_year": int(r["died_year"]),
        "age_at_death": int(r["age_at_death"]),
        "cause_of_death": r["cause_of_death"],
        "final_job": r["final_job"],
        "lifetime_earnings": int(r["lifetime_earnings"]),
        "peak_net_worth": int(r["peak_net_worth"]),
        "married": bool(r["married"]),
        "children_count": int(r["children_count"]),
        "is_favorite": bool(r["is_favorite"]),
    }


def set_favorite(archive_id: str, is_favorite: bool) -> bool:
    """Toggle the is_favorite flag on an archived life. Returns True
    if the row was found, False otherwise."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE life_archive SET is_favorite = ? WHERE id = ?",
            (1 if is_favorite else 0, archive_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_non_favorites() -> int:
    """Delete every life from the archive that isn't favorited.
    Returns the number of rows deleted. Used by the 'Clear archive'
    button in the dashboard so the player can wipe test/cruft data
    while keeping their hand-curated favorites."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM life_archive WHERE is_favorite = 0")
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    # Rewrite the JSONL sidecar to match the new state so a future
    # replay doesn't resurrect the cleared lives.
    _rewrite_sidecar_from_db()
    return deleted


def _rewrite_sidecar_from_db() -> None:
    """Rebuild the JSONL sidecar from the current DB state. Called
    after clear_non_favorites so the durability layer doesn't undo
    the user's cleanup the next time the server restarts."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_INSERT_COLS)} FROM life_archive"
        ).fetchall()
    finally:
        conn.close()
    path = _sidecar_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r)) + "\n")


def get_life(archive_id: str) -> dict | None:
    """Return the full snapshot of an archived life so the past-life
    retrospective can rehydrate it through the same showDeathScreen
    rendering the active death screen uses."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT snapshot_json, country_name FROM life_archive WHERE id = ?",
            (archive_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        snapshot = json.loads(row["snapshot_json"])
    except json.JSONDecodeError:
        return None
    return snapshot


# ---------------------------------------------------------------------------
# Export / import for explicit backups
# ---------------------------------------------------------------------------

def export_archive() -> str:
    """Return the entire archive as a JSON string. Used by the
    /api/statistics/export endpoint to deliver a downloadable backup."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_INSERT_COLS)} FROM life_archive ORDER BY archived_at"
        ).fetchall()
    finally:
        conn.close()
    payload = {
        "format": "real_lives_2007.life_archive.v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "rows": [dict(r) for r in rows],
    }
    return json.dumps(payload, indent=2)


def import_archive(payload_str: str) -> dict:
    """Merge an exported archive JSON into the current DB. Idempotent
    on id — rows already present are skipped. Returns
    {imported, skipped, total}."""
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}")
    if not isinstance(payload, dict) or "rows" not in payload:
        raise ValueError("invalid archive payload — missing 'rows' field")
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("invalid archive payload — 'rows' must be a list")

    conn = get_connection()
    try:
        existing_ids = {
            r[0] for r in conn.execute("SELECT id FROM life_archive").fetchall()
        }
        imported = 0
        skipped = 0
        for row in rows:
            if not isinstance(row, dict):
                skipped += 1
                continue
            rid = row.get("id")
            if not rid or rid in existing_ids:
                skipped += 1
                continue
            if not all(c in row for c in _INSERT_COLS):
                skipped += 1
                continue
            conn.execute(_INSERT_SQL, tuple(row[c] for c in _INSERT_COLS))
            existing_ids.add(rid)
            imported += 1
            # Also append to the sidecar so the imported data has the
            # same durability as native writes.
            try:
                _append_jsonl_sidecar(row)
            except Exception:
                logger.exception("life_archive: failed to mirror imported row to sidecar")
        conn.commit()
        return {"imported": imported, "skipped": skipped, "total": len(rows)}
    finally:
        conn.close()
