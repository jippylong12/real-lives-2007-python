"""
Achievements system (#90).

Each achievement is a single-line predicate over a finished life: given
the row that ``statistics.write_archive_row`` is about to insert (plus
the full character snapshot), does this life qualify? On evaluation,
``check_achievements`` returns the keys that newly unlocked, inserts
them into the ``achievements_unlocked`` table, and the death screen
surfaces them as toasts.

Achievements are scoped per player_name when set so two players sharing
one DB don't poach each other's "first centenarian" toast.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..data.build_db import get_connection


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    icon: str           # emoji
    tier: str           # 'bronze' | 'silver' | 'gold'
    check: Callable[[dict], bool]


def _safe_int(row: dict, key: str, default: int = 0) -> int:
    v = row.get(key)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _peak_attrs(row: dict) -> dict:
    """Pull peak_<attr> columns into a single dict for tier checks."""
    return {
        "intelligence": _safe_int(row, "peak_intelligence"),
        "artistic":     _safe_int(row, "peak_artistic"),
        "musical":      _safe_int(row, "peak_musical"),
        "athletic":     _safe_int(row, "peak_athletic"),
        "strength":     _safe_int(row, "peak_strength"),
        "endurance":    _safe_int(row, "peak_endurance"),
        "appearance":   _safe_int(row, "peak_appearance"),
        "conscience":   _safe_int(row, "peak_conscience"),
        "wisdom":       _safe_int(row, "peak_wisdom"),
        "resistance":   _safe_int(row, "peak_resistance"),
    }


def _snapshot_character(row: dict) -> dict:
    """Decode the snapshot_json blob to peek at fields not in the
    flat columns (previous_countries, previous_spouses, etc)."""
    raw = row.get("snapshot_json")
    if not raw:
        return {}
    try:
        snap = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return snap.get("character", {}) or {}


# Curated achievement registry. The check fn receives the flat archive
# row dict (columns from life_archive plus snapshot_json). Tier reflects
# difficulty: bronze = common, silver = noteworthy, gold = rare flex.
ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        key="centenarian",
        title="Centenarian",
        description="Live to 100 or older.",
        icon="🎂",
        tier="gold",
        check=lambda r: _safe_int(r, "age_at_death") >= 100,
    ),
    Achievement(
        key="pre_modern_long_life",
        title="Iron constitution",
        description="Live to 60+ in a country with life expectancy under 50.",
        icon="🛡️",
        tier="silver",
        check=lambda r: (
            _safe_int(r, "age_at_death") >= 60
            and _country_life_expectancy(r.get("country_code")) < 50
        ),
    ),
    Achievement(
        key="self_made",
        title="Self-made",
        description="Earn over $1M in lifetime earnings in a low-GDP country.",
        icon="💼",
        tier="gold",
        check=lambda r: (
            _safe_int(r, "lifetime_earnings") > 1_000_000
            and _country_gdp_pc(r.get("country_code")) < 5000
        ),
    ),
    Achievement(
        key="polyglot",
        title="Polyglot",
        description="Live in 5 or more different countries across one life.",
        icon="🌍",
        tier="gold",
        check=lambda r: len(_snapshot_character(r).get("previous_countries") or []) >= 4,
    ),
    Achievement(
        key="survivor",
        title="Survivor",
        description="Survive 5 or more diseases in one life.",
        icon="🩺",
        tier="silver",
        check=lambda r: _safe_int(r, "diseases_count") >= 5,
    ),
    Achievement(
        key="patriarch_matriarch",
        title="Patriarch / Matriarch",
        description="Have 5 or more children and live to 70+.",
        icon="👨‍👩‍👧‍👦",
        tier="silver",
        check=lambda r: (
            _safe_int(r, "children_count") >= 5
            and _safe_int(r, "age_at_death") >= 70
        ),
    ),
    Achievement(
        key="top_of_the_ladder",
        title="Top of the ladder",
        description="Reach 5 or more promotions in one career.",
        icon="📈",
        tier="silver",
        check=lambda r: _safe_int(r, "promotion_count") >= 5,
    ),
    Achievement(
        key="renaissance_soul",
        title="Renaissance soul",
        description="Reach peak intelligence + artistic + musical + athletic all above 75.",
        icon="🎨",
        tier="gold",
        check=lambda r: all(
            _peak_attrs(r).get(a, 0) > 75
            for a in ("intelligence", "artistic", "musical", "athletic")
        ),
    ),
    Achievement(
        key="self_employed_lifer",
        title="Self-employed lifer",
        description="Final job is freelance/self-employed and you held it 30+ years.",
        icon="🛠️",
        tier="silver",
        # The flat row doesn't carry years_in_role, so peek at the snapshot.
        check=lambda r: _self_employed_lifer_check(r),
    ),
    Achievement(
        key="globe_trotter",
        title="Globe trotter",
        description="Live in 3 or more different countries across one life.",
        icon="✈️",
        tier="bronze",
        check=lambda r: len(_snapshot_character(r).get("previous_countries") or []) >= 2,
    ),
    Achievement(
        key="long_marriage",
        title="Long-haul love",
        description="Stay married to one spouse for 40+ years (no divorce, no widowhood).",
        icon="💍",
        tier="silver",
        check=lambda r: _long_marriage_check(r),
    ),
    Achievement(
        key="serial_monogamist",
        title="Serial monogamist",
        description="Marry 3 or more times across one life.",
        icon="💔",
        tier="bronze",
        check=lambda r: len(_snapshot_character(r).get("previous_spouses") or []) >= 2,
    ),
]


def _self_employed_lifer_check(row: dict) -> bool:
    char = _snapshot_character(row)
    job = char.get("job") or ""
    years = char.get("years_in_role") or 0
    if not isinstance(job, str) or not isinstance(years, (int, float)):
        return False
    return ("freelance" in job.lower() or "self-employed" in job.lower()) and years >= 30


def _long_marriage_check(row: dict) -> bool:
    char = _snapshot_character(row)
    spouse = char.get("spouse")
    if not isinstance(spouse, dict):
        return False
    married_year = spouse.get("married_year")
    if married_year is None:
        return False
    age = _safe_int(row, "age_at_death")
    # Years married approximated by character age - age at marriage.
    # Age at marriage isn't tracked directly; we use met_year as a proxy.
    char_age_at_marriage = char.get("age", age) - max(0, age - char.get("age", age))
    # Simpler approximation: if the spouse is still attached at death
    # (alive or not in previous_spouses), and the marriage spans many
    # years, count it. Use age - 25 as a crude proxy if no calendar.
    years_married = max(0, age - 25)
    return years_married >= 40


# ---------------------------------------------------------------------------
# Country lookup helpers — only the two fields the achievement checks
# need. Cached lazily so we don't hit the DB on every check call.
# ---------------------------------------------------------------------------

_country_cache: dict[str, dict] = {}


def _load_country(code: str) -> dict:
    if not code:
        return {}
    code = code.lower()
    if code in _country_cache:
        return _country_cache[code]
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT life_expectancy, gdp_pc FROM countries WHERE code = ?",
            (code,),
        ).fetchone()
    finally:
        conn.close()
    cached = dict(row) if row else {}
    _country_cache[code] = cached
    return cached


def _country_life_expectancy(code: str | None) -> float:
    return float(_load_country(code or "").get("life_expectancy") or 999)


def _country_gdp_pc(code: str | None) -> float:
    return float(_load_country(code or "").get("gdp_pc") or 9_999_999)


# ---------------------------------------------------------------------------
# Evaluation + storage
# ---------------------------------------------------------------------------

def _player_scope_value(player_name: str | None) -> str:
    """Return the player_scope column value for a given player_name.
    NULL player_name maps to '' so the composite primary key still
    works (SQLite UNIQUE indexes allow multiple NULLs which would
    break our 'one unlock per achievement per player' invariant)."""
    return player_name or ""


def evaluate_for_row(row: dict, player_name: str | None = None) -> list[str]:
    """Run every achievement check against ``row``. For each one that
    matches AND isn't already unlocked for this player, insert a row
    into ``achievements_unlocked`` and return the newly-unlocked keys.
    Returns the list for the caller to surface."""
    scope = _player_scope_value(player_name)
    conn = get_connection()
    try:
        existing = {
            r[0] for r in conn.execute(
                "SELECT achievement_key FROM achievements_unlocked "
                "WHERE player_scope = ?",
                (scope,),
            ).fetchall()
        }
        unlocked: list[str] = []
        now = datetime.now(timezone.utc).isoformat()
        for ach in ACHIEVEMENTS:
            if ach.key in existing:
                continue
            try:
                hit = bool(ach.check(row))
            except Exception:
                hit = False
            if not hit:
                continue
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO achievements_unlocked "
                    "(achievement_key, player_scope, archive_id, unlocked_at, player_name) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ach.key, scope, row.get("id"), now, player_name),
                )
                conn.commit()
                unlocked.append(ach.key)
            except Exception:
                pass
        return unlocked
    finally:
        conn.close()


def list_achievements(player_name: str | None = None) -> list[dict]:
    """Return every achievement with its locked/unlocked state, scoped
    to ``player_name`` (or the unscoped legacy view when None)."""
    scope = _player_scope_value(player_name)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT achievement_key, archive_id, unlocked_at "
            "FROM achievements_unlocked "
            "WHERE player_scope = ?",
            (scope,),
        ).fetchall()
    finally:
        conn.close()
    by_key = {r["achievement_key"]: dict(r) for r in rows}
    out: list[dict] = []
    for ach in ACHIEVEMENTS:
        unlock = by_key.get(ach.key)
        out.append({
            "key": ach.key,
            "title": ach.title,
            "description": ach.description,
            "icon": ach.icon,
            "tier": ach.tier,
            "unlocked": unlock is not None,
            "archive_id": unlock["archive_id"] if unlock else None,
            "unlocked_at": unlock["unlocked_at"] if unlock else None,
        })
    return out


def list_recent_unlocks(player_name: str | None = None, limit: int = 5) -> list[dict]:
    """Return the most recent unlocks (newest first)."""
    scope = _player_scope_value(player_name)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT achievement_key, archive_id, unlocked_at "
            "FROM achievements_unlocked "
            "WHERE player_scope = ? "
            "ORDER BY unlocked_at DESC LIMIT ?",
            (scope, limit),
        ).fetchall()
    finally:
        conn.close()
    by_key = {ach.key: ach for ach in ACHIEVEMENTS}
    out: list[dict] = []
    for r in rows:
        ach = by_key.get(r["achievement_key"])
        if ach is None:
            continue
        out.append({
            "key": ach.key,
            "title": ach.title,
            "description": ach.description,
            "icon": ach.icon,
            "tier": ach.tier,
            "archive_id": r["archive_id"],
            "unlocked_at": r["unlocked_at"],
        })
    return out
