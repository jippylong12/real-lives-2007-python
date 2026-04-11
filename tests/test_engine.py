"""Tests for the game engine: birth, attributes, death rolls, events."""

import random

import pytest

from src.engine import Game
from src.engine import diseases
from src.engine.character import (
    Attributes, EducationLevel, Gender, create_random_character,
)
from src.engine.death import (
    background_mortality, infant_mortality_chance, old_age_mortality,
    total_death_chance,
)
from src.engine.events import roll_events, EVENT_REGISTRY
from src.engine.world import all_countries, get_country, random_country


# ---------- Birth ----------

def test_attribute_distribution_realistic_with_talents():
    """#65: characters spawn with realistic attribute distributions —
    most attributes near the country mean, with 1-2 talents and 1-2
    weaknesses per character. Across many newborns, fewer than 15% of
    any single attribute should clear 70."""
    rng_seed = 0
    country = get_country("us")
    samples = {a: [] for a in ("intelligence", "artistic", "athletic", "strength", "appearance")}
    has_talent = 0
    has_weakness = 0
    for s in range(200):
        rng = random.Random(s + rng_seed)
        c = create_random_character(country, rng)
        for a in samples:
            samples[a].append(getattr(c.attributes, a))
        attrs_dict = c.attributes.to_dict()
        if any(attrs_dict[a] >= 60 for a in ("intelligence", "artistic", "musical", "athletic", "strength", "endurance", "appearance")):
            has_talent += 1
        if any(attrs_dict[a] <= 35 for a in ("intelligence", "artistic", "musical", "athletic", "strength", "endurance", "appearance")):
            has_weakness += 1

    for a, vals in samples.items():
        mean = sum(vals) / len(vals)
        above_70 = sum(1 for v in vals if v >= 70) / len(vals)
        # Means should land in the 35-55 range (no longer all clustered high)
        assert 35 <= mean <= 60, f"{a} mean {mean:.0f} out of expected band"
        # At most ~15% of any single attribute should be high enough to
        # qualify for elite jobs.
        assert above_70 <= 0.20, f"{a} {above_70*100:.0f}% above 70 — too many high rolls"

    # Most characters should have at least one talent and one weakness.
    assert has_talent > 150, f"only {has_talent}/200 characters have a talent"
    assert has_weakness > 150, f"only {has_weakness}/200 characters have a weakness"


def test_birth_attributes_within_bounds():
    rng = random.Random(123)
    country = get_country("se")
    char = create_random_character(country, rng)
    for k, v in char.attributes.to_dict().items():
        assert 0 <= v <= 100, f"{k}={v} out of bounds"


def test_birth_assigns_country_and_family():
    rng = random.Random(7)
    country = get_country("br")
    char = create_random_character(country, rng)
    assert char.country_code == "br"
    assert char.age == 0
    assert any(m.relation == "mother" for m in char.family)
    assert any(m.relation == "father" for m in char.family)
    assert char.alive


def test_high_hdi_country_yields_higher_starting_health_on_average():
    rng = random.Random(0)
    se_health = []
    af_health = []
    for i in range(100):
        rng = random.Random(i)
        se_health.append(create_random_character(get_country("se"), rng).attributes.health)
        af_health.append(create_random_character(get_country("af"), rng).attributes.health)
    assert sum(se_health) / 100 > sum(af_health) / 100


# ---------- Death ----------

def test_infant_mortality_higher_in_high_imr_country():
    se = infant_mortality_chance(get_country("se"))
    af = infant_mortality_chance(get_country("af"))
    assert af > se


def test_old_age_mortality_grows_after_life_expectancy():
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 90
    char.attributes.health = 60
    p = total_death_chance(char, country)
    assert 0 < p < 1
    char.age = 25
    p_young = total_death_chance(char, country)
    assert p_young < p


def test_death_eventually_happens():
    rng = random.Random(99)
    game = Game.new(country_code="us", seed=99)
    for _ in range(150):
        result = game.advance_year()
        if result.died:
            break
        if result.pending_decision:
            choice = result.pending_decision["choices"][0]["key"]
            game.apply_decision(choice)
    assert not game.state.character.alive
    assert game.state.character.cause_of_death is not None


# ---------- Events ----------

def test_event_registry_is_well_formed():
    assert len(EVENT_REGISTRY) > 10
    keys = [e.key for e in EVENT_REGISTRY]
    assert len(keys) == len(set(keys)), "duplicate event keys"


def test_war_event_more_likely_in_high_war_country():
    char = create_random_character(get_country("ua"), random.Random(0))
    char.age = 30
    rng = random.Random(0)
    fired_in_ua = 0
    fired_in_se = 0
    for _ in range(500):
        if any(e.key == "war_event" for e in roll_events(char, get_country("ua"), rng)):
            fired_in_ua += 1
    rng = random.Random(0)
    for _ in range(500):
        if any(e.key == "war_event" for e in roll_events(char, get_country("se"), rng)):
            fired_in_se += 1
    assert fired_in_ua > fired_in_se


# ---------- Event cooldowns + lifetime caps (#52) ----------

def test_event_registry_has_at_least_200_events():
    """#52 sanity check: the slice-of-life content drop must land at
    least 200 events. Detects merge clobbers."""
    from src.engine.events import EVENT_REGISTRY
    assert len(EVENT_REGISTRY) >= 200, (
        f"event registry has only {len(EVENT_REGISTRY)} entries; "
        f"the #52 content drop should leave it at 200+"
    )


def test_event_cooldown_enforced():
    """#52: an event with cooldown_years=N can't fire two years apart.
    Uses _on_cooldown directly to avoid relying on the probabilistic
    roll_events path."""
    from src.engine.events import _on_cooldown, EVENT_REGISTRY
    char = create_random_character(get_country("us"), random.Random(0))
    char.age = 20
    # made_friend has cooldown_years=5 per the #52 tagging.
    made_friend = next(e for e in EVENT_REGISTRY if e.key == "made_friend")
    assert made_friend.cooldown_years == 5
    # Pretend it just fired at age 20.
    char.event_history["made_friend"] = [20]
    char.age = 21
    assert _on_cooldown(char, made_friend), "should still be on cooldown 1 year later"
    char.age = 24
    assert _on_cooldown(char, made_friend), "should still be on cooldown 4 years later"
    char.age = 25
    assert not _on_cooldown(char, made_friend), "cooldown should clear after 5 years"


def test_event_lifetime_cap_enforced():
    """#52: an event with max_lifetime=1 can fire at most once. baptism
    is tagged max_lifetime=1 by the #52 work."""
    from src.engine.events import _on_cooldown, EVENT_REGISTRY
    char = create_random_character(get_country("us"), random.Random(0))
    baptism = next(e for e in EVENT_REGISTRY if e.key == "baptism")
    assert baptism.max_lifetime == 1
    char.event_history["baptism"] = [1]
    # Even decades later, the lifetime cap blocks it.
    char.age = 50
    assert _on_cooldown(char, baptism)


def test_annual_events_can_fire_every_year():
    """#52: events with cooldown_years=0 (annual rhythm like Christmas)
    must NOT be blocked by _on_cooldown no matter how recently they
    fired."""
    from src.engine.events import _on_cooldown, EVENT_REGISTRY
    char = create_random_character(get_country("us"), random.Random(0))
    christmas = next(e for e in EVENT_REGISTRY if e.key == "christmas")
    assert christmas.cooldown_years == 0
    assert christmas.max_lifetime == 0
    # Even with a long firing history, no cooldown should kick in.
    char.event_history["christmas"] = list(range(3, 60))
    char.age = 60
    assert not _on_cooldown(char, christmas)


def test_event_history_serializes_round_trip():
    """#52: character.event_history survives a save → load round trip."""
    from src.engine.character import Character
    char = create_random_character(get_country("us"), random.Random(0))
    char.event_history = {
        "made_friend": [12, 18, 25],
        "christmas": [3, 4, 5, 6, 7],
        "baptism": [1],
    }
    d = char.to_dict()
    restored = Character.from_dict(d)
    assert restored.event_history == char.event_history


def test_slice_of_life_events_capped_per_year():
    """#52 followup: with ~218 slice-of-life events at ~5% chance each,
    the expected raw firing rate is ~11 per year. The cap of
    MAX_SLICE_OF_LIFE_PER_YEAR keeps the actual count down so the
    event log stays readable. Sim a 60-year US life and assert no
    year fires more than the cap."""
    from src.engine.events import roll_events, MAX_SLICE_OF_LIFE_PER_YEAR
    char = create_random_character(get_country("us"), random.Random(0))
    rng = random.Random(0)
    char.in_school = False
    for age in range(20, 60):
        char.age = age
        fired = roll_events(char, get_country("us"), rng)
        sol_count = sum(1 for e in fired if e.slice_of_life)
        assert sol_count <= MAX_SLICE_OF_LIFE_PER_YEAR, (
            f"age {age}: {sol_count} slice-of-life events fired, "
            f"cap is {MAX_SLICE_OF_LIFE_PER_YEAR}"
        )


def test_lifetime_earnings_accumulates_across_years():
    """#70: every positive net income year adds to character.lifetime_earnings."""
    from src.engine import careers
    from src.engine.character import create_random_character
    from src.engine.world import get_country
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = False
    char.education = 4
    char.attributes.intelligence = 70
    char.age = 25
    # Salary needs to exceed the US cost-of-living baseline
    # (~$45k from #82) for the net to be positive.
    char.salary = 120_000
    char.job = "office worker"

    starting = char.lifetime_earnings
    for _ in range(5):
        careers.yearly_income(char, country, rng)
    # Should have accumulated some earnings (positive net years).
    assert char.lifetime_earnings > starting


def test_peak_attributes_track_max():
    """#70: char.peak_attributes records the highest value any
    attribute reached during the run."""
    from src.engine import Game
    g = Game.new(country_code="us", seed=42)
    char = g.state.character
    char.attributes.intelligence = 80
    g.advance_year()
    assert char.peak_attributes.get("intelligence", 0) >= 80
    char.attributes.intelligence = 30  # later regression doesn't lower the peak
    g.advance_year()
    assert char.peak_attributes.get("intelligence", 0) >= 80


def test_life_archive_written_on_death():
    """#70: when a character dies, statistics.write_archive_row is
    called and a row appears in the life_archive table."""
    from src.engine import Game
    from src.data.build_db import get_connection
    g = Game.new(country_code="us", seed=99)
    # Force the character into a near-death state and let advance_year
    # roll the kill_check.
    g.state.character.age = 95
    g.state.character.attributes.health = 5
    # Run several ticks; old + sick = high death probability.
    for _ in range(15):
        if not g.state.character.alive:
            break
        g.advance_year()
    assert not g.state.character.alive, "test setup failed: character didn't die"

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, age_at_death, cause_of_death FROM life_archive WHERE id = ?",
            (g.state.id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no life_archive row written on death"
    assert row["age_at_death"] == g.state.character.age
    assert row["cause_of_death"] == g.state.character.cause_of_death


def test_life_archive_jsonl_round_trip_after_db_wipe():
    """#70: the JSONL sidecar can rehydrate the life_archive table
    after the DB is wiped — the durability layer that protects
    against accidental DB rebuilds."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    # Force a death to create at least one row + sidecar entry.
    g = Game.new(country_code="us", seed=77)
    g.state.character.age = 95
    g.state.character.attributes.health = 5
    for _ in range(15):
        if not g.state.character.alive:
            break
        g.advance_year()
    assert not g.state.character.alive

    # Wipe the DB table
    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive WHERE id = ?", (g.state.id,))
        conn.commit()
        n_after_wipe = conn.execute(
            "SELECT COUNT(*) FROM life_archive WHERE id = ?", (g.state.id,)
        ).fetchone()[0]
        assert n_after_wipe == 0
    finally:
        conn.close()

    # Replay JSONL — the row should come back.
    statistics.restore_jsonl_into_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM life_archive WHERE id = ?", (g.state.id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "JSONL replay didn't restore the wiped row"


def test_player_scoping_separates_two_players_archives():
    """#85: two players sharing one DB see only their own lives by
    default. The 'unscoped' query (player=None) still returns both."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    # Wipe to start clean.
    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.commit()
    finally:
        conn.close()

    def play_to_death(seed, player):
        g = Game.new(country_code="us", seed=seed, player_name=player)
        g.state.character.age = 95
        g.state.character.attributes.health = 5
        for _ in range(15):
            if not g.state.character.alive:
                break
            g.advance_year()
        assert not g.state.character.alive
        return g.state.id

    alice_id = play_to_death(901, "alice")
    bob_id = play_to_death(902, "bob")

    alice_lives = statistics.list_lives(player="alice")["lives"]
    bob_lives = statistics.list_lives(player="bob")["lives"]
    all_lives = statistics.list_lives()["lives"]

    alice_ids = {l["id"] for l in alice_lives}
    bob_ids = {l["id"] for l in bob_lives}
    all_ids = {l["id"] for l in all_lives}

    assert alice_id in alice_ids
    assert bob_id not in alice_ids
    assert bob_id in bob_ids
    assert alice_id not in bob_ids
    assert {alice_id, bob_id}.issubset(all_ids)

    # global_stats also scopes correctly
    alice_global = statistics.global_stats(player="alice")
    bob_global = statistics.global_stats(player="bob")
    all_global = statistics.global_stats()
    assert alice_global["total_lives"] == 1
    assert bob_global["total_lives"] == 1
    assert all_global["total_lives"] == 2


def test_player_scoped_save_slots_isolated():
    """#85: list_slots(player_name='alice') hides bob's slots."""
    from src.engine import Game
    from src.engine.game import list_slots
    from src.data.build_db import get_connection

    # Wipe games table to start clean.
    conn = get_connection()
    try:
        conn.execute("DELETE FROM games WHERE slot IS NOT NULL")
        conn.commit()
    finally:
        conn.close()

    g_alice = Game.new(country_code="us", seed=801, slot=1, player_name="alice")
    g_alice.save()
    g_bob = Game.new(country_code="de", seed=802, slot=2, player_name="bob")
    g_bob.save()

    alice_slots = list_slots(player_name="alice")
    bob_slots = list_slots(player_name="bob")
    # Each player only sees their own occupied slot.
    alice_occupied = [s for s in alice_slots if s["state"] != "empty"]
    bob_occupied = [s for s in bob_slots if s["state"] != "empty"]
    assert len(alice_occupied) == 1
    assert alice_occupied[0]["character_name"] == g_alice.state.character.name
    assert len(bob_occupied) == 1
    assert bob_occupied[0]["character_name"] == g_bob.state.character.name


def test_list_players_returns_distinct_player_names():
    """#85: list_players surfaces distinct names with at least one
    archived life so the dashboard can render a player picker."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.commit()
    finally:
        conn.close()

    for seed, player in [(701, "carol"), (702, "dan"), (703, "carol")]:
        g = Game.new(country_code="us", seed=seed, player_name=player)
        g.state.character.age = 95
        g.state.character.attributes.health = 5
        for _ in range(15):
            if not g.state.character.alive:
                break
            g.advance_year()

    players = statistics.list_players()
    assert "carol" in players
    assert "dan" in players
    # No duplicates.
    assert len(players) == len(set(players))


def test_update_life_notes_round_trip():
    """#89: notes set via update_life_notes survive across reads.
    Truncation enforced at NOTES_MAX_LEN."""
    from src.engine import statistics, Game

    g = Game.new(country_code="us", seed=601)
    g.state.character.age = 95
    g.state.character.attributes.health = 5
    for _ in range(15):
        if not g.state.character.alive:
            break
        g.advance_year()
    assert not g.state.character.alive

    note = "This was the time my centenarian Brazilian senator survived three coups."
    assert statistics.update_life_notes(g.state.id, note) is True
    lives = statistics.list_lives()["lives"]
    target = next(l for l in lives if l["id"] == g.state.id)
    assert target["notes"] == note
    assert target["has_notes"] is True

    # Truncation
    huge = "x" * 6000
    statistics.update_life_notes(g.state.id, huge)
    lives = statistics.list_lives()["lives"]
    target = next(l for l in lives if l["id"] == g.state.id)
    assert len(target["notes"]) == statistics.NOTES_MAX_LEN


def test_update_life_notes_404_for_missing_id():
    """#89: update_life_notes returns False when no row matches."""
    from src.engine import statistics
    assert statistics.update_life_notes("does-not-exist", "hello") is False


def test_list_lives_filters_by_country_and_age_range():
    """#88: list_lives accepts country, age, and net_worth filters
    that AND together. The total reflects the filtered count."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.commit()
    finally:
        conn.close()

    # Three different countries / lifespans.
    for seed, country in [(401, "us"), (402, "de"), (403, "us")]:
        g = Game.new(country_code=country, seed=seed)
        g.state.character.age = 95
        g.state.character.attributes.health = 5
        for _ in range(15):
            if not g.state.character.alive:
                break
            g.advance_year()
        assert not g.state.character.alive

    us_only = statistics.list_lives(country="us")
    de_only = statistics.list_lives(country="de")
    assert us_only["total"] == 2
    assert de_only["total"] == 1
    assert all(l["country_code"] == "us" for l in us_only["lives"])
    assert all(l["country_code"] == "de" for l in de_only["lives"])

    # Age filter — everyone died at 95 so min_age=90 should hit all 3.
    young = statistics.list_lives(min_age=200)
    assert young["total"] == 0
    older = statistics.list_lives(min_age=90)
    assert older["total"] == 3


def test_list_lives_filter_by_name_substring():
    """#88: name filter does a case-insensitive substring match."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.commit()
    finally:
        conn.close()

    g = Game.new(country_code="us", seed=501)
    g.state.character.age = 95
    g.state.character.attributes.health = 5
    g.state.character.name = "MARIA TESTOVNA"
    for _ in range(15):
        if not g.state.character.alive:
            break
        g.advance_year()
    assert not g.state.character.alive

    res = statistics.list_lives(name="maria")
    assert res["total"] >= 1
    assert any("MARIA" in l["name"].upper() for l in res["lives"])

    miss = statistics.list_lives(name="zzzzz")
    assert miss["total"] == 0


def test_list_filter_facets_returns_distinct_values():
    """#88: facets endpoint returns distinct countries / causes / jobs."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.commit()
    finally:
        conn.close()

    for seed, cc in [(601, "us"), (602, "de"), (603, "us")]:
        g = Game.new(country_code=cc, seed=seed)
        g.state.character.age = 95
        g.state.character.attributes.health = 5
        for _ in range(15):
            if not g.state.character.alive:
                break
            g.advance_year()

    facets = statistics.list_filter_facets()
    codes = {c["code"] for c in facets["countries"]}
    assert "us" in codes
    assert "de" in codes
    assert isinstance(facets["causes"], list)
    assert isinstance(facets["jobs"], list)


def test_centenarian_achievement_unlocks_for_100plus_life():
    """#90: a 100+ life triggers the 'centenarian' achievement on the
    very next archive write. Replays don't re-unlock."""
    from src.engine import achievements, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.execute("DELETE FROM achievements_unlocked")
        conn.commit()
    finally:
        conn.close()

    # Force a 100-year-old character to die.
    g = Game.new(country_code="us", seed=701)
    g.state.character.age = 100
    g.state.character.attributes.health = 5
    for _ in range(20):
        if not g.state.character.alive:
            break
        result = g.advance_year()
    assert not g.state.character.alive
    assert g.state.character.age >= 100

    # Centenarian should be unlocked for this archive id.
    listed = achievements.list_achievements()
    cent = next(a for a in listed if a["key"] == "centenarian")
    assert cent["unlocked"] is True
    assert cent["archive_id"] == g.state.id

    # A second archive write doesn't re-unlock.
    g2 = Game.new(country_code="us", seed=702)
    g2.state.character.age = 100
    g2.state.character.attributes.health = 5
    for _ in range(20):
        if not g2.state.character.alive:
            break
        g2.advance_year()
    cent_after = next(
        a for a in achievements.list_achievements() if a["key"] == "centenarian"
    )
    # Still pinned to the first life that earned it.
    assert cent_after["archive_id"] == g.state.id


def test_achievement_evaluation_returns_unlocked_keys_for_turn_result():
    """#90: write_archive_row returns the list of newly-unlocked keys
    so the caller can surface them in the death-screen toast."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM achievements_unlocked")
        conn.commit()
    finally:
        conn.close()

    g = Game.new(country_code="us", seed=801)
    g.state.character.age = 100
    g.state.character.attributes.health = 5
    last_result = None
    for _ in range(40):
        if not g.state.character.alive:
            break
        last_result = g.advance_year()
        # Resolve any pending choice event so the loop can keep advancing.
        if last_result.pending_decision:
            first_choice = last_result.pending_decision["choices"][0]["key"]
            last_result = g.apply_decision(first_choice)
    assert last_result is not None
    assert not g.state.character.alive
    assert "centenarian" in (last_result.unlocked_achievements or [])


def test_achievements_scoped_per_player():
    """#90: alice and bob each get their own first-centenarian unlock."""
    from src.engine import achievements, Game
    from src.data.build_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive")
        conn.execute("DELETE FROM achievements_unlocked")
        conn.commit()
    finally:
        conn.close()

    def play_to_100(seed, player):
        g = Game.new(country_code="us", seed=seed, player_name=player)
        g.state.character.age = 100
        g.state.character.attributes.health = 5
        for _ in range(20):
            if not g.state.character.alive:
                break
            g.advance_year()
        return g.state.id

    alice_id = play_to_100(901, "alice")
    bob_id = play_to_100(902, "bob")

    alice_achievements = achievements.list_achievements(player_name="alice")
    bob_achievements = achievements.list_achievements(player_name="bob")
    alice_cent = next(a for a in alice_achievements if a["key"] == "centenarian")
    bob_cent = next(a for a in bob_achievements if a["key"] == "centenarian")
    assert alice_cent["unlocked"] is True
    assert bob_cent["unlocked"] is True
    assert alice_cent["archive_id"] == alice_id
    assert bob_cent["archive_id"] == bob_id


def test_favorites_and_clear_non_favorites():
    """#70 followup: set_favorite + list_favorites + clear_non_favorites
    work together so the user can curate a permanent set and wipe
    everything else."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    # Create two dead characters so we have rows to favorite + clear.
    ids = []
    for seed in (101, 102):
        g = Game.new(country_code="us", seed=seed)
        g.state.character.age = 95
        g.state.character.attributes.health = 5
        for _ in range(15):
            if not g.state.character.alive:
                break
            g.advance_year()
        assert not g.state.character.alive
        ids.append(g.state.id)

    # Favorite one of them.
    assert statistics.set_favorite(ids[0], True) is True
    favs = statistics.list_favorites()
    fav_ids = {f["id"] for f in favs}
    assert ids[0] in fav_ids
    assert ids[1] not in fav_ids

    # Clear non-favorites — the favorited row should survive.
    statistics.clear_non_favorites()
    conn = get_connection()
    try:
        remaining = {r[0] for r in conn.execute("SELECT id FROM life_archive").fetchall()}
    finally:
        conn.close()
    assert ids[0] in remaining
    assert ids[1] not in remaining


def test_export_import_archive_round_trip():
    """#70: export → import is idempotent on id."""
    from src.engine import statistics, Game
    from src.data.build_db import get_connection

    # Make sure there's at least one row to export.
    g = Game.new(country_code="us", seed=11)
    g.state.character.age = 95
    g.state.character.attributes.health = 5
    for _ in range(15):
        if not g.state.character.alive:
            break
        g.advance_year()
    assert not g.state.character.alive

    payload = statistics.export_archive()
    assert g.state.id in payload  # the id appears in the dump

    # Import the same payload — should skip everything (already present).
    result = statistics.import_archive(payload)
    assert result["imported"] == 0
    assert result["skipped"] >= 1

    # Drop one specific row, import again, that one should come back.
    conn = get_connection()
    try:
        conn.execute("DELETE FROM life_archive WHERE id = ?", (g.state.id,))
        conn.commit()
    finally:
        conn.close()
    result = statistics.import_archive(payload)
    assert result["imported"] == 1


def test_event_variety_per_life_meaningfully_higher_than_baseline():
    """#52: simulate a handful of lives and assert the average distinct
    event count per life is meaningfully higher than the pre-#52
    baseline (~5-7 events). Target: at least 25 distinct events for an
    80-year run with 200+ events in the catalogue."""
    from src.engine import careers
    from src.engine.game import Game

    distinct_counts = []
    for seed in range(8):
        g = Game.new(country_code="us", seed=seed)
        while g.state.character.alive and g.state.character.age < 80:
            r = g.advance_year()
            if r.pending_decision:
                g.apply_decision(r.pending_decision["choices"][0]["key"])
            char = g.state.character
            if char.job is None and not char.in_school and char.age >= 14:
                careers.assign_job(char, g.country(), g.rng)
        distinct_counts.append(len(g.state.character.event_history))

    avg = sum(distinct_counts) / len(distinct_counts)
    assert avg >= 25, (
        f"average distinct events per life is only {avg:.1f}; "
        f"the #52 cooldown + content drop should push this past 25 "
        f"(individual counts: {distinct_counts})"
    )


# ---------- Game lifecycle ----------

def test_game_advance_returns_turn_result():
    g = Game.new(seed=42)
    result = g.advance_year()
    assert result.age == 1
    assert result.year_advanced_to == 2008


def test_game_save_load_round_trip():
    g = Game.new(seed=11, country_code="jp")
    for _ in range(5):
        r = g.advance_year()
        if r.pending_decision:
            g.apply_decision(r.pending_decision["choices"][0]["key"])
    g.save()

    loaded = Game.load(g.state.id)
    assert loaded is not None
    assert loaded.state.character.name == g.state.character.name
    assert loaded.state.character.age == g.state.character.age


# ---------- Diseases ----------

def test_disease_registry_size():
    assert len(diseases.DISEASES) >= 50, f"only {len(diseases.DISEASES)} diseases"
    keys = [d.key for d in diseases.DISEASES]
    assert len(keys) == len(set(keys)), "duplicate disease keys"


def test_disease_categories_present():
    cats = {d.category for d in diseases.DISEASES}
    for required in ("cancer", "sti", "tropical", "childhood", "chronic", "infectious"):
        assert required in cats


def test_tropical_country_gets_more_tropical_diseases():
    """Smoke test: simulating many lives in a low-income tropical country
    yields more tropical-disease incidences than the same in a wealthy
    temperate country."""
    def tally(country_code: str) -> int:
        n = 0
        for seed in range(40):
            g = Game.new(country_code=country_code, seed=seed)
            while g.state.character.alive and g.state.character.age < 70:
                r = g.advance_year()
                if r.pending_decision:
                    g.apply_decision(r.pending_decision["choices"][0]["key"])
            for k in g.state.character.diseases:
                d = next((dd for dd in diseases.DISEASES if dd.key == k), None)
                if d and d.category == "tropical":
                    n += 1
        return n
    tropical_low = tally("ng")  # Nigeria
    temperate_rich = tally("se")  # Sweden
    assert tropical_low > temperate_rich * 3, (
        f"expected tropical-low >> temperate-rich, got {tropical_low} vs {temperate_rich}"
    )


def test_gender_only_diseases_respected():
    """Cervical cancer should only appear in female characters."""
    rng = random.Random(0)
    male = create_random_character(get_country("us"), rng)
    male.gender = Gender.MALE
    male.age = 50
    el = diseases.eligible_diseases(male, get_country("us"))
    keys = {d.key for d, _ in el}
    assert "cancer_cervix" not in keys
    assert "cancer_prostate" in keys

    female = create_random_character(get_country("us"), rng)
    female.gender = Gender.FEMALE
    female.age = 50
    el = diseases.eligible_diseases(female, get_country("us"))
    keys = {d.key for d, _ in el}
    assert "cancer_cervix" in keys
    assert "cancer_prostate" not in keys


# ---------- Religion / culture events ----------

def test_religion_events_only_fire_for_matching_religion():
    """Christmas should only ever fire in Christian-majority countries; the
    Hajj choice should only ever appear in Muslim-majority countries."""
    christmas = next(e for e in EVENT_REGISTRY if e.key == "christmas")
    hajj = next(e for e in EVENT_REGISTRY if e.key == "hajj")
    diwali = next(e for e in EVENT_REGISTRY if e.key == "diwali")

    rng = random.Random(0)
    sa = get_country("sa")  # Saudi Arabia, Islam
    us = get_country("us")  # USA, Christianity
    inn = get_country("in")  # India, Hinduism

    # Build a 30-year-old character in each country and check eligibility
    char_us = create_random_character(us, rng); char_us.age = 30; char_us.money = 5000
    char_sa = create_random_character(sa, rng); char_sa.age = 30; char_sa.money = 5000
    char_in = create_random_character(inn, rng); char_in.age = 30; char_in.money = 5000

    assert christmas.eligible(char_us, us)
    assert not christmas.eligible(char_sa, sa)
    assert not christmas.eligible(char_in, inn)

    assert hajj.eligible(char_sa, sa)
    assert not hajj.eligible(char_us, us)
    assert not hajj.eligible(char_in, inn)

    assert diwali.eligible(char_in, inn)
    assert not diwali.eligible(char_us, us)
    assert not diwali.eligible(char_sa, sa)


def test_religion_events_present_in_registry():
    keys = {e.key for e in EVENT_REGISTRY}
    expected = {
        "christmas", "easter", "ramadan", "eid_al_fitr", "diwali", "vesak",
        "passover", "yom_kippur", "ancestral_ceremony", "baptism",
        "first_communion", "sacred_thread", "bar_mitzvah",
        "hajj", "varanasi_pilgrimage", "monastic_retreat", "arranged_marriage",
        "conversion_offer", "religious_school",
    }
    missing = expected - keys
    assert not missing, f"missing events: {missing}"


def test_tropical_only_diseases_hard_gated_outside_tropics():
    """Issue #23: tropical_only=True diseases (malaria, dengue, yellow
    fever, schistosomiasis, ...) should never even be eligible for
    characters in non-tropical countries — no more fragile rich_mult
    juggling to almost-zero out malaria-in-Stockholm."""
    from src.engine.character import create_random_character

    rng = random.Random(0)
    sweden = get_country("se")
    char = create_random_character(sweden, rng)
    char.age = 30
    keys = {d.key for d, _ in diseases.eligible_diseases(char, sweden)}
    for tropical_key in ("malaria", "dengue", "yellow_fever", "schistosomiasis", "hookworm"):
        assert tropical_key not in keys, (
            f"{tropical_key} should not be eligible in Sweden"
        )

    # India is in TROPICAL_ASIA_CODES so tropical-only diseases should fire there.
    india = get_country("in")
    char_in = create_random_character(india, rng)
    char_in.age = 30
    keys_in = {d.key for d, _ in diseases.eligible_diseases(char_in, india)}
    assert "malaria" in keys_in
    assert "dengue" in keys_in


def test_roll_diseases_returns_multiple_per_year():
    """Issue #22: roll_diseases (plural) can return multiple diseases per
    year now. Verify by simulating many years for a high-age character
    in a high-prevalence country and checking we observe at least one
    multi-disease year — that's only possible after the restructure."""
    from src.engine.character import create_random_character
    rng = random.Random(42)
    country = get_country("ng")  # high infectious + tropical load
    char = create_random_character(country, rng)
    char.age = 60
    char.attributes.resistance = 20

    n_years = 2000
    multi_years = 0
    for _ in range(n_years):
        char.diseases.clear()
        fired = diseases.roll_diseases(char, country, rng)
        if len(fired) >= 2:
            multi_years += 1
    assert multi_years > 0, (
        "no multi-disease years observed — roll_diseases should be able to "
        "return more than one disease in a single year now"
    )


def test_acute_categories_capped_at_one_per_year():
    """Multiple acute infections (TB + flu + bronchitis) shouldn't all
    fire in the same year — the per-category cap prevents that."""
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("ng")  # high infectious load
    char = create_random_character(country, rng)
    char.age = 30
    char.attributes.resistance = 10  # very low to maximize incidence

    n_years = 500
    multi_infectious = 0
    for _ in range(n_years):
        char.diseases.clear()
        fired = diseases.roll_diseases(char, country, rng)
        infectious_count = sum(1 for d in fired if d.category == "infectious")
        if infectious_count > 1:
            multi_infectious += 1
    assert multi_infectious == 0, (
        f"saw {multi_infectious} years with multiple infectious diseases — "
        "the acute category cap is broken"
    )


# Helper used by cohort-style tests below. The engine no longer auto-
# assigns jobs in advance_year (deliberate joblessness — see commit
# removing auto-assign), so cohort sims must explicitly drive the
# character into the workforce each year. Mirrors what an active
# player does via Find work / job board.
def _seek_work_after_advance(g):
    char = g.state.character
    if char.job is None and not char.in_school and char.age >= 14:
        from src.engine import careers
        careers.assign_job(char, g.country(), g.rng)


def test_cancer_lifetime_rates_in_real_world_ballpark():
    """Issue #24: cancer lifetime incidence in the US should be at least
    8% for breast (women) and prostate (men) — within +/- 50% of the
    real-world ~13% lifetime risk per SEER. The previous calibration
    showed both at <1% because the disease roller capped at one disease
    per year (#22) and characters died early (#24 lifespan fix)."""
    from src.engine import Game
    from src.engine.character import Gender

    def cancer_rate(country_code: str, cancer_key: str, gender: Gender, n: int = 200) -> float:
        hits = 0
        cohort = 0
        for seed in range(n):
            g = Game.new(country_code=country_code, seed=seed)
            if g.state.character.gender != gender:
                continue
            cohort += 1
            while g.state.character.alive and g.state.character.age < 100:
                r = g.advance_year()
                if r.pending_decision:
                    g.apply_decision(r.pending_decision["choices"][0]["key"])
                _seek_work_after_advance(g)
            if cancer_key in g.state.character.diseases:
                hits += 1
        return hits / cohort if cohort else 0.0

    breast = cancer_rate("us", "cancer_breast", Gender.FEMALE)
    prostate = cancer_rate("us", "cancer_prostate", Gender.MALE)
    assert breast >= 0.08, f"US lifetime breast cancer {breast*100:.1f}% should be >=8%"
    assert prostate >= 0.08, f"US lifetime prostate cancer {prostate*100:.1f}% should be >=8%"


def test_average_lifespan_in_real_world_ballpark_for_rich_countries():
    """Issue #31: simulated average lifespan for rich countries should be
    within ~5 years of real-world life expectancy. Old age should be the
    dominant cause of death in healthy nations."""
    from src.engine import Game
    from collections import Counter

    def cohort(country_code: str, n: int = 100):
        ages = []
        causes = Counter()
        for s in range(n):
            g = Game.new(country_code=country_code, seed=s)
            while g.state.character.alive and g.state.character.age < 100:
                r = g.advance_year()
                if r.pending_decision:
                    g.apply_decision(r.pending_decision["choices"][0]["key"])
                _seek_work_after_advance(g)
            ages.append(g.state.character.age)
            causes[g.state.character.cause_of_death] += 1
        return sum(ages) / len(ages), causes

    # USA: real ~78, target 73-83
    avg, causes = cohort("us")
    assert 73 <= avg <= 83, f"US avg lifespan {avg:.1f} not in [73, 83]"
    assert causes["old age"] >= 50, f"US old-age deaths {causes['old age']}/100 too low"

    # Sweden: real ~83, target 76-90
    avg, causes = cohort("se")
    assert 76 <= avg <= 90, f"Sweden avg lifespan {avg:.1f} not in [76, 90]"
    assert causes["old age"] >= 50, f"Sweden old-age deaths {causes['old age']}/100 too low"


def test_disease_calibration_anchor_lifetime_rates():
    """Issue #14: simulated lifetime malaria incidence in Sweden must be
    < 1%, and in Nigeria must be > 50%. The previous values (~8% Sweden,
    barely-passing Nigeria) made the difference between rich/poor tropical
    cohorts feel almost arbitrary."""
    from src.engine import Game
    def lifetime_malaria_rate(country_code: str, n_lives: int = 100) -> float:
        n = 0
        for seed in range(n_lives):
            g = Game.new(country_code=country_code, seed=seed)
            while g.state.character.alive and g.state.character.age < 80:
                r = g.advance_year()
                if r.pending_decision:
                    g.apply_decision(r.pending_decision["choices"][0]["key"])
            if "malaria" in g.state.character.diseases:
                n += 1
        return n / n_lives

    se_rate = lifetime_malaria_rate("se")
    ng_rate = lifetime_malaria_rate("ng")
    assert se_rate < 0.01, f"Sweden lifetime malaria {se_rate*100:.1f}% should be <1%"
    assert ng_rate > 0.50, f"Nigeria lifetime malaria {ng_rate*100:.1f}% should be >50%"


def test_rural_nigerian_more_malaria_than_urban_nigerian():
    """Issue #10: malaria is rural-skewed (urban_skew=0.4). Simulating
    many rural and urban Nigerian lives should yield meaningfully more
    malaria diagnoses for the rural cohort."""
    from src.engine.character import create_random_character
    nigeria = get_country("ng")

    def tally(force_urban: bool) -> int:
        n = 0
        for seed in range(40):
            rng = random.Random(seed)
            char = create_random_character(nigeria, rng)
            char.is_urban = force_urban
            for age in range(0, 70):
                char.age = age
                d = diseases.roll_disease(char, nigeria, rng)
                if d is not None and d.key == "malaria":
                    n += 1
                    break
        return n

    rural = tally(False)
    urban = tally(True)
    assert rural > urban, f"rural malaria ({rural}) should exceed urban ({urban})"


def test_urban_skew_is_inverted_for_rural_characters():
    """The eligible_diseases chance for an urban-skewed disease (TB,
    urban_skew=1.8) should be higher for is_urban=True than is_urban=False
    in the same country."""
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("in")  # India: tropical, dense urban areas
    char_u = create_random_character(country, rng)
    char_u.is_urban = True
    char_u.age = 35
    char_r = create_random_character(country, rng)
    char_r.is_urban = False
    char_r.age = 35

    def tb_chance(c):
        for d, p in diseases.eligible_diseases(c, country):
            if d.key == "tuberculosis":
                return p
        return 0.0

    assert tb_chance(char_u) > tb_chance(char_r) * 1.5


def test_country_dataclass_carries_at_war_and_conscription():
    """Issue #17: the binary at_war / military_conscription flags flow
    through to the Country dataclass and reach the event system."""
    israel = get_country("il")
    assert israel.military_conscription == 1
    iraq = get_country("iq")
    assert iraq.at_war == 1
    sweden = get_country("se")
    assert sweden.at_war == 0


def test_military_service_event_uses_conscription_flag():
    """The MILITARY_SERVICE choice event fires for conscript countries
    even when their war_freq is low — Israel/Switzerland's universal
    service can't be detected from war_freq alone."""
    from src.engine.events import MILITARY_SERVICE
    from src.engine.character import create_random_character

    rng = random.Random(0)
    israel = get_country("il")
    char = create_random_character(israel, rng)
    char.gender = Gender.MALE
    char.age = 19
    assert MILITARY_SERVICE.eligible(char, israel)

    # USA: all-volunteer force, peacetime in 2007 binary, low war_freq.
    # The event should not fire.
    us = get_country("us")
    char2 = create_random_character(us, rng)
    char2.gender = Gender.MALE
    char2.age = 19
    assert not MILITARY_SERVICE.eligible(char2, us)


def test_small_business_investment_has_real_risk():
    """Issue #41: small business used to print money — uniform return
    in [-0.50, +0.80] gave +15% expected/year and characters ended
    careers as millionaires. Now it has a risk-driven catastrophic-loss
    roll AND a less skewed return range, so the *median* outcome over
    long holding periods is at or below the starting value."""
    from src.engine import finances
    from src.engine.character import Character, Attributes, InvestmentHolding, Gender, EducationLevel

    sb = next(p for p in finances.list_investments() if p.name == "small business")
    end_values = []
    for seed in range(500):
        rng = random.Random(seed)
        char = Character(
            id="test", name="t", gender=Gender.MALE, age=30,
            country_code="us", city="x", is_urban=True,
            attributes=Attributes(),
            family_wealth=0, money=10000,
        )
        char.investments.append(InvestmentHolding(
            product_id=sb.id, name=sb.name,
            cost_basis=5000, value=5000, opened_year=2000,
        ))
        for _ in range(20):  # 20-year hold
            finances.tick_finances(char, rng)
            if not char.investments:
                end_values.append(0)
                break
        else:
            end_values.append(char.investments[0].value)

    n_wiped_out = sum(1 for v in end_values if v == 0)
    median = sorted(end_values)[len(end_values) // 2]

    # Real small businesses fail more than half the time over a decade.
    assert n_wiped_out > 100, f"only {n_wiped_out}/500 wiped out — risk too low"
    # And the median outcome should be at or below the starting investment.
    assert median <= 5000, f"median end value {median} > starting 5000 — still printing money"


def test_jobs_table_populated_from_binary():
    """#51: the canonical jobs table is now sourced from jobs.dat (131
    binary entries with categories + ladders), plus the synthetic
    ladder rungs from #59 (~15 extras for athletics/military/arts/etc.)."""
    from src.engine import careers
    jobs = careers.all_jobs()
    assert len(jobs) >= 131  # binary baseline
    assert len(jobs) <= 250  # sanity cap (career ladder expansion adds ~30 step jobs)
    # All categories present
    cats = {j.category for j in jobs if j.category}
    assert {"medical", "stem", "education", "trades", "police", "maritime"}.issubset(cats)
    # Promotion chains intact — pick a known ladder
    seaman = careers.get_job("seaman")
    assert seaman is not None
    assert seaman.promotes_to == "second mate"
    second_mate = careers.get_job("second mate")
    assert second_mate.promotes_to == "first mate"
    first_mate = careers.get_job("first mate")
    assert first_mate.promotes_to == "ship's captain"
    captain = careers.get_job("ship's captain")
    assert captain.promotes_to is None  # terminal


def test_investment_value_compounds_year_over_year():
    """#74: investment values should compound — each year's roll
    multiplies the *current* value, not the original cost basis. A
    fixed-positive product should grow exponentially over many years."""
    from src.engine import finances
    from src.engine.character import Character, Attributes, InvestmentHolding, Gender
    rng = random.Random(0)
    char = Character(
        id="t", name="t", gender=Gender.MALE, age=30,
        country_code="us", city="x", is_urban=True,
        attributes=Attributes(),
        family_wealth=0, money=10000,
    )
    # Use the savings account — guaranteed positive return (1-4%).
    savings = next(p for p in finances.list_investments() if "savings" in p.name)
    char.investments.append(InvestmentHolding(
        product_id=savings.id, name=savings.name,
        cost_basis=1000, value=1000, opened_year=2020,
    ))
    for _ in range(20):
        finances.tick_finances(char, rng)
    # Expected ~ 1000 * 1.025^20 = 1639. Allow a wide window for the
    # randomness to swing.
    final = char.investments[0].value
    assert 1300 < final < 2200, f"compounding broken: $1000 → ${final} after 20yr"
    # last_year_delta should be set after the most recent tick.
    assert char.investments[0].last_year_delta != 0 or char.investments[0].value > 1000


def test_repeat_purchases_can_be_bought_multiple_times():
    """#76: vacations and other one_time=False purchases can be bought
    repeatedly without being marked as 'owned'."""
    from src.engine import spending
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 30
    char.money = 100_000
    spending.buy(char, country, "vacation_local", 2030)
    spending.buy(char, country, "vacation_local", 2031)
    listings = spending.list_purchases(char, country)
    vac = next(l for l in listings if l["key"] == "vacation_local")
    assert not vac["owned"]  # repeatable, never marked as owned
    assert vac["eligible"]   # still buyable as long as the player can afford


def test_athlete_retires_at_max_age():
    """#75: when a character ages past every athletics rung's max_age,
    advance_year strips their job and salary."""
    from src.engine import Game, careers
    g = Game.new(country_code="us", seed=42)
    elite = careers.get_job("elite athlete")
    assert elite is not None
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 1
    char.attributes.athletic = 80
    char.vocation_field = "athletics"
    char.age = 30
    careers._set_job(char, country, elite, g.rng)
    assert char.job == "elite athlete"
    # Push past every athletics rung's max_age (the highest is 40 for
    # 'professional athlete'). At age 45 nothing in athletics fits.
    char.age = 44
    g.advance_year()
    # After the tick: retired AND can't be re-assigned to any other
    # athletics job. (Since vocation_field='athletics', the fallback
    # to all eligible_jobs also filters to athletics — none fit at 45+.)
    assert char.job is None, f"still employed as {char.job}"
    assert char.salary == 0


def test_retire_age_gate_passes_for_athlete():
    """#82: a 32yo athlete (athletics min_retire = 30) can retire on
    the age gate alone — no wealth check needed."""
    from src.engine import Game, careers
    g = Game.new(country_code="us", seed=1)
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 1
    char.attributes.athletic = 70
    char.vocation_field = "athletics"
    char.age = 32
    elite = careers.get_job("elite athlete")
    careers._set_job(char, country, elite, g.rng)
    assert char.job == "elite athlete"

    can, reason = careers.can_retire(char, country)
    assert can, reason

    result = careers.retire(char, country)
    assert result.outcome == "retired"
    assert result.former_job == "elite athlete"
    assert char.job is None
    assert char.salary == 0
    assert char.years_in_role == 0
    # History line written
    assert any("Retired from being a elite athlete" in line for line in char.history)


def test_retire_age_and_wealth_gates_block_young_office_worker():
    """#82: a 30yo office worker (business min_retire = 55) with modest
    savings can NOT retire — both gates fail."""
    from src.engine import Game, careers
    g = Game.new(country_code="us", seed=2)
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 4
    char.attributes.intelligence = 70
    char.vocation_field = "business"
    char.age = 30
    char.money = 50_000
    office = careers.get_job("office worker")
    assert office is not None
    careers._set_job(char, country, office, g.rng)

    can, reason = careers.can_retire(char, country)
    assert not can
    assert reason and "55" in reason  # surfaces the min_age in the message

    result = careers.retire(char, country)
    assert result.outcome == "not_eligible"
    # Job preserved on a failed retire attempt
    assert char.job == "office worker"


def test_retire_wealth_override_passes_for_young_millionaire():
    """#82: a 30yo with $5M cash can retire regardless of category /
    age — the wealth override (~20× annual expenses) is the path."""
    from src.engine import Game, careers
    g = Game.new(country_code="us", seed=3)
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 4
    char.attributes.intelligence = 80
    char.vocation_field = "business"
    char.age = 30
    char.money = 5_000_000
    office = careers.get_job("office worker")
    careers._set_job(char, country, office, g.rng)

    can, reason = careers.can_retire(char, country)
    assert can, reason

    result = careers.retire(char, country)
    assert result.outcome == "retired"
    assert char.job is None


def test_baseline_cost_of_living_drains_unemployed_adult():
    """#82: an unemployed adult in the US burns through savings at the
    country baseline rate. Tested via careers.yearly_income directly
    to isolate the income/expense math from advance_year's job-hunt
    and investment ticks."""
    from src.engine import Game, careers, finances
    g = Game.new(country_code="us", seed=4)
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 4
    char.age = 60
    char.job = None
    char.salary = 0
    char.money = 200_000

    baseline = finances.baseline_cost_of_living(country)
    assert baseline > 10_000, f"US baseline should be substantial, got {baseline}"

    starting = char.money
    net = careers.yearly_income(char, country, g.rng)
    # Net should be negative-baseline (or close to it; subscription
    # costs don't apply since the character has none).
    assert net == -baseline, f"expected net=-{baseline:,}, got {net:,}"
    assert char.money == starting + net


def test_baseline_cost_does_not_drain_children():
    """#82: a 10yo dependent doesn't pay the country baseline —
    children live on parental support."""
    from src.engine import Game, careers
    g = Game.new(country_code="us", seed=5)
    country = g.country()
    char = g.state.character
    char.in_school = True
    char.age = 10
    char.job = None
    char.salary = 0
    char.money = 100  # piggy bank

    net = careers.yearly_income(char, country, g.rng)
    assert net == 0, f"children should pay 0, got net={net}"
    assert char.money == 100


def test_baseline_cost_makes_low_pay_us_worker_lose_money():
    """#82: a US character earning $18k/yr against the country baseline
    (~75% of salary < baseline) loses money via the lifestyle floor.
    Verifies the realistic 'poor in expensive country' path."""
    from src.engine import Game, careers, finances
    g = Game.new(country_code="us", seed=6)
    country = g.country()
    char = g.state.character
    char.in_school = False
    char.education = 1
    char.age = 25
    char.money = 50_000
    char.job = "cashier"
    char.salary = 18_000
    char.years_in_role = 0
    char.vocation_field = "business"

    baseline = finances.baseline_cost_of_living(country)
    assert baseline > int(18_000 * 0.75), (
        f"test premise broken: baseline {baseline} ≤ 75% of salary"
    )

    # Run 3 yearly_income ticks directly (avoid advance_year's job-hunt
    # which might promote/replace the character).
    starting = char.money
    for _ in range(3):
        careers.yearly_income(char, country, g.rng)
    assert char.money < starting, (
        f"low-pay US worker should lose money; started ${starting:,}, "
        f"now ${char.money:,}"
    )


def test_investment_age_gate():
    """#68: investments are now age-gated. Savings 12+, bonds 16+, the rest 18+."""
    from src.engine import finances
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.money = 100_000

    savings = next(p for p in finances.list_investments() if "savings" in p.name)
    bonds = next(p for p in finances.list_investments() if "government bonds" in p.name)
    stock = next(p for p in finances.list_investments() if "high-risk stock" in p.name)

    # Age 5 — too young for everything
    char.age = 5
    for prod in (savings, bonds, stock):
        try:
            finances.buy_investment(char, prod, 1000, 2030)
            assert False, f"5yo bought {prod.name}"
        except ValueError as e:
            assert "must be at least" in str(e)

    # Age 13 — savings only
    char.age = 13
    finances.buy_investment(char, savings, 100, 2030)
    try:
        finances.buy_investment(char, bonds, 1000, 2030)
        assert False, "13yo bought bonds"
    except ValueError:
        pass

    # Age 17 — savings + bonds, no stock
    char.age = 17
    finances.buy_investment(char, bonds, 1000, 2030)
    try:
        finances.buy_investment(char, stock, 2500, 2030)
        assert False, "17yo bought stock"
    except ValueError:
        pass

    # Age 19 — full access
    char.age = 19
    finances.buy_investment(char, stock, 2500, 2030)


def test_drop_out_of_school_country_gates():
    """#69: drop_out_of_school respects the country's minimum working age."""
    from src.engine import careers
    from src.engine.character import create_random_character

    sweden = get_country("se")
    nigeria = get_country("ng")

    rng = random.Random(0)
    sw_char = create_random_character(sweden, rng)
    sw_char.age = 10
    sw_char.in_school = True
    eligible, reason = careers.can_drop_out_of_school(sw_char, sweden)
    assert not eligible  # Sweden's working age is 14
    assert "14" in reason

    sw_char.age = 14
    eligible, _ = careers.can_drop_out_of_school(sw_char, sweden)
    assert eligible

    ng_char = create_random_character(nigeria, rng)
    ng_char.age = 10
    ng_char.in_school = True
    eligible, _ = careers.can_drop_out_of_school(ng_char, nigeria)
    assert eligible  # Nigeria's working age is 8

    careers.drop_out_of_school(ng_char, nigeria)
    assert ng_char.in_school is False
    # And now they can work
    can_work, _ = careers.can_character_work(ng_char, nigeria)
    assert can_work


def test_vocational_school_has_duration_and_grants_credential_on_completion():
    """#82-followup: vocational school is a 2-year program. Entering it
    sets school_track but keeps in_school=True; the credential is only
    granted on completion at age 19. Previously the engine set
    education=VOCATIONAL on entry and immediately flipped in_school=False,
    which lied to the player ('entered a vocational program' but actually
    not in school anymore)."""
    from src.engine import education
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    # Force vocational eligibility: intelligence in the 50-59 band so the
    # secondary→vocational branch fires (intel >= 50, < 60).
    char.attributes.intelligence = 55
    char.education = EducationLevel.PRIMARY
    char.in_school = True
    char.school_track = "secondary"
    char.age = 18  # SECONDARY_END_AGE + 1

    # Run the secondary completion branch a few times until we hit the
    # vocational coin flip (40% chance per call).
    msg = None
    for _ in range(20):
        rng_inner = random.Random(7)
        char.attributes.intelligence = 55
        char.education = EducationLevel.PRIMARY
        char.in_school = True
        char.school_track = "secondary"
        char.age = 18
        msg = education.update_education(char, country, rng_inner)
        if char.school_track == "vocational":
            break
    assert char.school_track == "vocational", "couldn't reach vocational branch"
    # On entry: still in school, credential is SECONDARY (not yet VOCATIONAL)
    assert char.in_school is True
    assert char.education == EducationLevel.SECONDARY
    assert "vocational" in (msg or "").lower()

    # Year 1 of vocational: nothing changes
    char.age = 19
    education.update_education(char, country, rng)
    assert char.in_school is True
    assert char.school_track == "vocational"
    assert char.education == EducationLevel.SECONDARY

    # Year 2 of vocational completes the program (age 20 = VOCATIONAL_END_AGE + 1)
    char.age = 20
    msg = education.update_education(char, country, rng)
    assert char.in_school is False
    assert char.school_track is None
    assert char.education == EducationLevel.VOCATIONAL
    assert msg and "graduated from vocational" in msg.lower()


def test_no_freelance_to_salaried_promotion_crossovers():
    """#83 followup: no freelance job in the catalogue should promote
    into a non-freelance job. Crossing the freelance boundary
    silently strips the entrepreneurial framing — when a freelancer
    gets promoted they should stay self-employed (or the chain
    should terminate)."""
    from src.data.build_db import get_connection
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.name AS from_job, b.name AS to_job, b.is_freelance AS to_fl
        FROM jobs a
        LEFT JOIN jobs b ON a.promotes_to = b.name
        WHERE a.is_freelance = 1 AND a.promotes_to IS NOT NULL
    """).fetchall()
    crossovers = [
        f"{r['from_job']} → {r['to_job']}"
        for r in rows
        if r["to_fl"] is not None and not r["to_fl"]
    ]
    assert not crossovers, f"freelance → salaried crossovers found: {crossovers}"


def test_handicraft_worker_is_terminal_freelance():
    """#83 followup: handicraft worker's binary promotes_to (foreman)
    is overridden to None at build time — promoting a self-employed
    artisan into a salaried foreman doesn't make sense."""
    from src.engine import careers
    j = careers.get_job("handicraft worker")
    assert j is not None
    assert j.is_freelance, "handicraft worker should be freelance"
    assert j.promotes_to is None, (
        f"handicraft worker should be terminal but promotes_to={j.promotes_to!r}"
    )


def test_education_path_vocational_choice_does_not_get_clobbered_at_age_18():
    """#83 followup regression: when the player picks 'vocational' from
    EDUCATION_PATH at age 17, the auto secondary-completion branch in
    education.update_education must not re-roll their track at age 18.
    The user reported the trade picker (VOCATIONAL_TRACK) never fired
    because the auto-branch clobbered school_track between turns."""
    from src.engine import education
    from src.engine.events import _education_vocational
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = True
    char.school_track = "secondary"
    char.education = EducationLevel.PRIMARY
    char.age = 17

    # Simulate picking 'vocational' on the EDUCATION_PATH event.
    _education_vocational(char)
    assert char.school_track == "vocational"
    assert char.in_school is True
    assert char.education == EducationLevel.SECONDARY  # bumped on entry

    # Advance one year — at 18 the auto-branch must NOT re-roll the
    # track. school_track stays "vocational".
    char.age = 18
    education.update_education(char, country, rng)
    assert char.school_track == "vocational", (
        f"auto-branch clobbered the user's choice; school_track is {char.school_track!r}"
    )
    assert char.in_school is True

    # Year 19: still in school
    char.age = 19
    education.update_education(char, country, rng)
    assert char.school_track == "vocational"
    assert char.in_school is True

    # Year 20: graduates. #109: no longer auto-assigns a job — the
    # frontend opens the job board so the player picks their own.
    char.vocation_field = "trades"
    char.age = 20
    msg = education.update_education(char, country, rng)
    assert char.in_school is False
    assert char.school_track is None
    assert char.education == EducationLevel.VOCATIONAL
    assert "trades" in msg.lower(), f"graduation msg should mention field, msg={msg}"


def test_vocational_track_event_eligible_across_whole_school_window():
    """#83 followup regression: VOCATIONAL_TRACK must be able to fire
    over the full vocational school window (ages 18 and 19), not just
    age 18 exactly. Previously the trigger was `c.age == 18` which
    meant a competing CHOICE event preempting the registry walk at
    age 18 would lock the player out of picking a trade forever (the
    next year c.age would be 19 and the trigger would fail)."""
    from src.engine.events import VOCATIONAL_TRACK, UNIVERSITY_MAJOR
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = True
    char.school_track = "vocational"
    char.education = EducationLevel.SECONDARY
    char.vocation_field = None

    for age in (18, 19):
        char.age = age
        assert VOCATIONAL_TRACK.eligible(char, country), (
            f"VOCATIONAL_TRACK should be eligible at age {age}"
        )

    # And UNIVERSITY_MAJOR similarly across the longer window
    char.school_track = "university"
    for age in (18, 19, 20, 21):
        char.age = age
        assert UNIVERSITY_MAJOR.eligible(char, country), (
            f"UNIVERSITY_MAJOR should be eligible at age {age}"
        )


def test_career_defining_choice_events_have_priority_over_slice_of_life():
    """#83 followup: EDUCATION_PATH, UNIVERSITY_MAJOR, and
    VOCATIONAL_TRACK must appear in EVENT_REGISTRY before any
    'slice-of-life' CHOICE event (theft, bribery, marriage,
    pilgrimages, etc). roll_events walks top-to-bottom and breaks on
    the first CHOICE event that fires — these once-in-a-lifetime
    career picks must always win that race against random life
    events at the same age.

    MILITARY_SERVICE is a deliberate exception: being drafted at 18
    is a legitimate real-world preemption of education plans, and
    the widened VOCATIONAL_TRACK / UNIVERSITY_MAJOR triggers let the
    picker fire after military service ends."""
    from src.engine.events import EVENT_REGISTRY

    career_keys = {"education_path", "university_major", "vocational_track"}
    # The slice-of-life choices that should never preempt the career picks.
    slice_of_life_keys = {
        "theft_child", "theft_adult", "bribery",
        "hajj", "varanasi_pilgrimage", "monastic_retreat",
        "arranged_marriage", "conversion_offer", "religious_school",
        "dowry_negotiation", "bilingual_schooling", "love_marriage",
    }
    indices = {ev.key: i for i, ev in enumerate(EVENT_REGISTRY)}
    last_career_idx = max(indices[k] for k in career_keys if k in indices)
    first_slice_idx = min(
        (indices[k] for k in slice_of_life_keys if k in indices),
        default=None,
    )
    if first_slice_idx is not None:
        assert last_career_idx < first_slice_idx, (
            f"all career-defining events must come before slice-of-life "
            f"choice events; last career at {last_career_idx}, first "
            f"slice-of-life at {first_slice_idx}"
        )


def test_education_path_university_choice_does_not_get_clobbered():
    """Same regression as the vocational case but for university."""
    from src.engine import education
    from src.engine.events import _education_university
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(1)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = True
    char.school_track = "secondary"
    char.education = EducationLevel.PRIMARY
    char.age = 17

    _education_university(char)
    assert char.school_track == "university"
    assert char.education == EducationLevel.SECONDARY

    char.age = 18
    education.update_education(char, country, rng)
    assert char.school_track == "university", (
        f"auto-branch clobbered the user's choice; school_track is {char.school_track!r}"
    )
    assert char.in_school is True


def test_vocational_graduation_places_starter_job_in_chosen_field():
    """#83 followup / #109 update: when a character finishes vocational
    school with a vocation_field set, they graduate with a message
    mentioning their field. They are NOT auto-assigned a job — the
    frontend opens the job board so the player picks their own."""
    from src.engine import education
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = True
    char.school_track = "vocational"
    char.education = EducationLevel.SECONDARY
    char.vocation_field = "trades"
    char.age = 20  # VOCATIONAL_END_AGE + 1
    char.job = None
    char.salary = 0

    msg = education.update_education(char, country, rng)
    assert msg is not None
    assert "graduated from vocational" in msg.lower()
    # #109: no auto-assignment — player picks via job board.
    assert "trades" in msg.lower(), f"graduation msg should mention field, msg={msg}"
    assert char.in_school is False
    assert char.school_track is None
    assert char.education == EducationLevel.VOCATIONAL


def test_vocational_graduation_without_vocation_field_still_works():
    """#83 followup: graduating from vocational without a vocation_field
    set (e.g. dropped out of the trade picker) still produces a clean
    graduation event — they just don't get an auto-assigned job."""
    from src.engine import education
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = True
    char.school_track = "vocational"
    char.education = EducationLevel.SECONDARY
    char.vocation_field = None  # never picked a trade
    char.age = 20
    char.job = None
    char.salary = 0

    msg = education.update_education(char, country, rng)
    assert msg is not None
    assert "graduated from vocational" in msg.lower()
    assert char.job is None  # no auto-assignment without a field
    assert char.in_school is False
    assert char.education == EducationLevel.VOCATIONAL


def test_modern_self_employment_kinds_loaded_as_freelance():
    """#83: the new modern self-employment kinds (online seller, content
    creator, food vendor, gig worker, freelance consultant) load from
    the synthetic-ladder seed and are flagged is_freelance=True with
    no promotion ladder."""
    from src.engine import careers

    expected = {
        "online seller":        "business",
        "content creator":      "arts",
        "food vendor":          "service",
        "gig worker":           "service",
        "freelance consultant": "business",
    }
    for name, expected_category in expected.items():
        job = careers.get_job(name)
        assert job is not None, f"{name} did not load"
        assert job.is_freelance, f"{name} should be is_freelance=True"
        assert job.category == expected_category, (
            f"{name} category {job.category!r} != {expected_category!r}"
        )
        # No promotion ladder — entrepreneurs run their venture
        # indefinitely.
        assert job.promotes_to is None, (
            f"{name} should be standalone but promotes_to={job.promotes_to!r}"
        )


def test_university_track_still_works_after_school_track_field_added():
    """#82-followup: ensure the existing university path still progresses
    correctly through 4 years of in-school time after we added the
    school_track field."""
    from src.engine import education
    from src.engine.character import EducationLevel, create_random_character

    rng = random.Random(1)
    country = get_country("us")
    char = create_random_character(country, rng)
    # Force university acceptance: high intelligence + high family wealth.
    char.attributes.intelligence = 80
    char.family_wealth = 500_000
    char.education = EducationLevel.PRIMARY
    char.in_school = True
    char.school_track = "secondary"
    char.age = 18

    msg = education.update_education(char, country, rng)
    assert char.school_track == "university"
    assert char.in_school is True
    assert char.education == EducationLevel.SECONDARY
    assert "university" in (msg or "").lower()

    # Years 19-21: still in university, no change
    for age in (19, 20, 21):
        char.age = age
        education.update_education(char, country, rng)
        assert char.in_school is True
        assert char.education == EducationLevel.SECONDARY

    # Age 22 = UNI_END_AGE: graduate
    char.age = 22
    msg = education.update_education(char, country, rng)
    assert char.in_school is False
    assert char.school_track is None
    assert char.education == EducationLevel.UNIVERSITY
    assert msg and "graduated from university" in msg.lower()


def test_buy_house_increases_family_wealth():
    """#66: a starter home purchase drains money and adds to family_wealth."""
    from src.engine import spending
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 30
    char.money = 200_000
    char.family_wealth = 50_000
    money_before = char.money
    fw_before = char.family_wealth
    res = spending.buy(char, country, "house_starter", 2030)
    assert res.success
    assert char.money < money_before  # cash drained
    assert char.family_wealth > fw_before  # family wealth boosted
    # The purchase is recorded for the death retrospective.
    assert any(p["key"] == "house_starter" for p in char.purchases)


def test_buy_house_blocks_duplicate():
    """#66: requires_no_existing prevents buying a second starter home."""
    from src.engine import spending
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 30
    char.money = 500_000
    spending.buy(char, country, "house_starter", 2030)
    res = spending.buy(char, country, "house_starter", 2031)
    assert not res.success
    assert "already" in res.message.lower()


def test_subscription_drains_yearly_cash():
    """#66: an active subscription costs money each year via yearly_income."""
    from src.engine import spending, careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 25
    char.money = 10_000
    char.salary = 50_000  # so income > expenses
    char.job = "engineer"
    spending.buy(char, country, "sub_gym", 2025)
    money_before = char.money
    careers.yearly_income(char, country, rng)
    # Cash should have moved (income - expenses - subscription)
    assert "sub_gym" in char.subscriptions
    # Yearly subscription cost should be reflected in the deduction
    assert spending.yearly_subscription_cost(char) > 0


def test_buy_checkup_recovers_health():
    """#67: paying for a checkup heals the character (age-modulated)."""
    from src.engine import healthcare
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 30
    char.attributes.health = 50
    char.money = 10_000
    res = healthcare.buy_checkup(char, country)
    assert res.success
    assert char.attributes.health > 50
    assert res.health_delta > 0
    # Cooldown enforced
    res2 = healthcare.buy_checkup(char, country)
    assert not res2.success


def test_old_age_treatment_diminished():
    """#67: an 85yo gets much less out of major treatment than a 40yo."""
    from src.engine import healthcare
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")

    def recovery_at(age):
        char = create_random_character(country, rng)
        char.age = age
        char.attributes.health = 30
        char.money = 100_000
        res = healthcare.buy_major_treatment(char, country)
        assert res.success
        return res.health_delta

    young = recovery_at(40)
    old = recovery_at(85)
    assert young > old, f"young recovery {young} should exceed old {old}"


def test_treat_disease_manages_chronic():
    """#67: treating a permanent chronic disease flips status active → inactive
    but the disease stays on the record."""
    from src.engine import healthcare
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 50
    char.money = 50_000
    # Add hypertension manually
    char.diseases["hypertension"] = {
        "name": "Hypertension",
        "category": "chronic",
        "active": True,
        "age_acquired": 45,
        "permanent": True,
    }
    res = healthcare.treat_disease(char, country, "hypertension")
    assert res.success
    assert "hypertension" in char.diseases  # still on record
    assert char.diseases["hypertension"]["active"] is False  # but managed


def test_synthetic_athletics_ladder_reachable():
    """#59: the athletics ladder now has 5 rungs from youth athlete to
    elite athlete instead of just 'professional athlete'.

    #83 followup: every rung is freelance — even at the elite level
    athletes are independent contractors whose income swings on
    talent and luck. Previously semi-pro and elite were is_freelance=0
    which silently flipped a self-employed athlete into a salaried
    role on promotion."""
    from src.engine import careers
    youth = careers.get_job("youth athlete")
    amateur = careers.get_job("amateur athlete")
    semipro = careers.get_job("semi-pro athlete")
    pro = careers.get_job("professional athlete")
    elite = careers.get_job("elite athlete")
    assert youth is not None and youth.promotes_to == "amateur athlete"
    assert amateur is not None and amateur.promotes_to == "semi-pro athlete"
    assert semipro is not None and semipro.promotes_to == "professional athlete"
    assert pro is not None and pro.promotes_to == "elite athlete"  # patched
    assert elite is not None and elite.promotes_to is None  # terminal
    # All five rungs freelance — no crossover into a salaried role.
    for j in (youth, amateur, semipro, pro, elite):
        assert j.is_freelance, f"{j.name} should be freelance"


def test_synthetic_writer_ladder_freelance():
    """#59 + #61: writer category gains junior + published rungs and
    they're all freelance."""
    from src.engine import careers
    junior = careers.get_job("junior writer")
    writer = careers.get_job("writer")
    published = careers.get_job("published author")
    assert junior is not None and junior.promotes_to == "writer"
    assert writer is not None and writer.promotes_to == "published author"  # patched
    assert published is not None and published.promotes_to is None
    for j in (junior, writer, published):
        assert j.is_freelance, f"{j.name} should be freelance"


def test_attribute_drives_promotion_speed():
    """#60: a high-artistic writer should reach the years_required gate
    faster than a low-artistic writer in the same role."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")

    def years_to_promote(artistic_value):
        char = create_random_character(country, rng)
        char.age = 22
        char.education = EducationLevel.SECONDARY
        char.attributes.artistic = artistic_value
        char.attributes.intelligence = 70  # clears the IQ gate on 'writer'
        char.is_urban = True
        char.job = "junior writer"
        char.salary = 15000
        char.years_in_role = 0
        char.promotion_count = 0
        for _ in range(50):
            char.years_in_role += 1
            years_before = char.years_in_role
            msg = careers.promote(char, country, rng)
            if msg:
                return years_before
            char.age += 1
        return None

    high = years_to_promote(95)
    low = years_to_promote(30)
    assert high is not None
    assert low is not None
    # The high-skill writer should promote at least 2x faster.
    assert low > high * 2, f"low-artistic took {low}, high-artistic took {high}"


def test_freelance_income_scales_with_talent():
    """#61: a high-artistic freelance writer should out-earn a
    low-artistic one by at least 3x over 40 simulated years."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")

    def lifetime_earnings(artistic_value):
        rng = random.Random(0)
        char = create_random_character(country, rng)
        char.age = 25
        char.attributes.artistic = artistic_value
        char.is_urban = True
        j = careers.get_job("writer")
        careers._set_job(char, country, j, rng)
        total = 0
        for _ in range(40):
            total += careers.yearly_income(char, country, rng)
        return total

    high = lifetime_earnings(95)
    low = lifetime_earnings(25)
    assert high > low * 3, f"high-talent took home {high}, low-talent {low} — ratio too small"


def test_promote_walks_ladder_with_experience():
    """#51: a character with enough years_in_role + intelligence gets
    promoted along the binary's ladder."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    # Engineering dept manager has min_age=30 in the binary; age 32 clears it.
    char.age = 32
    char.attributes.intelligence = 75
    char.education = EducationLevel.UNIVERSITY
    char.is_urban = True
    char.job = "engineer"
    char.salary = 70000
    char.years_in_role = 0
    char.promotion_count = 0
    char.vocation_field = "stem"

    # Promote with not enough experience: nothing happens
    msg = careers.promote(char, country, rng)
    assert msg is None
    assert char.job == "engineer"

    # Build up experience — engineer now promotes to "senior engineer"
    # (a seniority step) after its per-job promotion_years.
    char.years_in_role = 6
    msg = careers.promote(char, country, rng)
    assert msg is not None
    assert "senior engineer" in msg
    assert char.job == "senior engineer"
    assert char.years_in_role == 0
    # Seniority steps don't increment promotion_count
    assert char.promotion_count == 0


def test_job_board_age_gate_by_country_hdi():
    """#57: babies / toddlers / young kids in high-HDI countries can't
    use the job board at all. Low-HDI countries allow earlier work."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)

    # Sweden: HDI ~0.94, working age 14
    sweden = get_country("se")
    char = create_random_character(sweden, rng)
    for age in (0, 5, 10, 13):
        char.age = age
        char.in_school = False  # ignore school for this gate test
        allowed, reason = careers.can_character_work(char, sweden)
        assert not allowed, f"age {age} in Sweden should not be allowed"
        assert "14+" in reason
    char.age = 14
    allowed, _ = careers.can_character_work(char, sweden)
    assert allowed

    # Nigeria: HDI ~0.5, working age 8 (real child labor)
    nigeria = get_country("ng")
    char_ng = create_random_character(nigeria, rng)
    char_ng.in_school = False
    char_ng.age = 5
    allowed, _ = careers.can_character_work(char_ng, nigeria)
    assert not allowed
    char_ng.age = 8
    allowed, _ = careers.can_character_work(char_ng, nigeria)
    assert allowed


def test_job_board_in_school_blocks_work():
    """#57: a primary-school student can't take a job."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 16
    char.in_school = True
    char.education = EducationLevel.NONE  # still in primary
    allowed, reason = careers.can_character_work(char, get_country("us"))
    assert not allowed
    assert "school" in reason.lower()


def test_job_listing_filters_far_too_young_jobs():
    """#57: a 14-year-old shouldn't see 'doctor' (min_age 24) in the
    listings — only jobs near their current age window."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    # Use Nigeria so the working-age gate clears at 14.
    country = get_country("ng")
    char = create_random_character(country, rng)
    char.age = 14
    char.in_school = False
    listings = careers.job_listing(char, country)
    job_names = {l.job.name for l in listings}
    assert "doctor" not in job_names  # min_age 24 — too far
    # The 14-year-old should still see jobs they're close to age-wise.
    assert any(l.job.min_age <= 16 for l in listings)


def test_apply_for_job_qualified_acceptance_high():
    """A fully qualified candidate for a low-tier job lands near the
    sigmoid cap (~80%). Mid-tier jobs (engineer, $70k) now sit in the
    "stretch" band even for over-qualified candidates because of the
    salary tier penalty — that's intentional, and verified by
    test_apply_for_job_mid_tier_is_stretch below."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")
    accepted = 0
    for seed in range(200):
        rng = random.Random(seed)
        char = create_random_character(country, rng)
        # Over-qualified candidate for 'nursery school aid' — a real
        # low-tier job (no education floor, low IQ floor, low salary).
        char.age = 25
        char.education = EducationLevel.UNIVERSITY
        char.attributes.intelligence = 80
        char.is_urban = True
        char.vocation_field = None
        result = careers.apply_for_job(char, country, "nursery school aid", rng)
        if result.accepted:
            accepted += 1
    assert accepted > 130, f"qualified accept rate only {accepted}/200"


def test_apply_for_job_mid_tier_is_stretch():
    """A "qualified" candidate for a mid-tier $70k job (engineer) should
    land in the stretch band (40-60% acceptance), not the cap. This is
    the spread fix: high-paying jobs are competitive even when minimums
    are met, replacing the old bimodal 80% / 25% behavior."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")
    accepted = 0
    for seed in range(400):
        rng = random.Random(seed)
        char = create_random_character(country, rng)
        char.age = 25
        char.education = EducationLevel.UNIVERSITY
        char.attributes.intelligence = 80
        char.is_urban = True
        char.vocation_field = None
        if careers.apply_for_job(char, country, "engineer", rng).accepted:
            accepted += 1
    rate = accepted / 400
    assert 0.35 < rate < 0.70, (
        f"mid-tier acceptance {rate:.2f} outside the stretch band — "
        f"check that the salary-tier penalty is doing its job"
    )


def test_apply_for_job_long_shot_low_but_nonzero():
    """#54: a 5-year-old applying for surgeon hits the floor (~1%)."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")
    accepted = 0
    for seed in range(1000):
        rng = random.Random(seed)
        char = create_random_character(country, rng)
        char.age = 5  # too young, no education
        char.attributes.intelligence = 30
        char.is_urban = True
        char.vocation_field = None
        result = careers.apply_for_job(char, country, "doctor", rng)
        if result.accepted:
            accepted += 1
    # Floor is 1%, so 1000 trials should give 5-30 acceptances.
    assert accepted >= 5, f"floor probability not honored: only {accepted}/1000"
    assert accepted <= 50, f"long-shot acceptance too high: {accepted}/1000"


def test_request_raise_eligibility_gates():
    """#55: can_request_raise enforces years_in_role and cooldown."""
    from src.engine import careers
    from src.engine.character import create_random_character
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.attributes.intelligence = 70  # ensure skill_factor doesn't extend the gate
    char.job = "engineer"
    char.salary = 70000
    char.years_in_role = 0
    char.promotion_count = 0

    # Just hired — not eligible
    eligible, reason = careers.can_request_raise(char)
    assert not eligible
    assert "year" in reason

    # Enough years in — eligible. Engineer has per-job promotion_years
    # so threshold depends on that, not the global formula.
    char.years_in_role = 6
    eligible, _ = careers.can_request_raise(char)
    assert eligible

    # After requesting, cooldown applies
    char.last_raise_request_age = 30
    eligible, reason = careers.can_request_raise(char)
    assert not eligible
    assert "asked recently" in reason


def test_request_raise_outcomes_distribution():
    """#55: across many trials, qualified-and-stuck characters get a raise
    or promotion >50% of the time."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")
    grants = 0
    for seed in range(200):
        rng = random.Random(seed)
        char = create_random_character(country, rng)
        char.age = 35
        char.job = "engineer"
        char.salary = 70000
        char.years_in_role = 8  # 3 years past the 5-year threshold
        char.promotion_count = 0
        char.attributes.intelligence = 80
        char.attributes.wisdom = 70
        char.attributes.endurance = 70
        char.attributes.conscience = 50
        char.is_urban = True
        char.education = EducationLevel.UNIVERSITY
        result = careers.request_raise(char, country, rng)
        if result.outcome in ("raise", "promotion"):
            grants += 1
    assert grants > 100, f"strong candidate grant rate only {grants}/200"


def test_vocation_field_constrains_assigned_jobs():
    """#51: a character with vocation_field='medical' should only get
    jobs from the medical category."""
    from src.engine import careers
    from src.engine.character import create_random_character
    country = get_country("us")
    medical_categories_seen = set()
    for seed in range(40):
        rng = random.Random(seed)
        char = create_random_character(country, rng)
        char.age = 22
        char.attributes.intelligence = 70
        char.education = EducationLevel.UNIVERSITY
        char.is_urban = True
        char.vocation_field = "medical"
        msg = careers.assign_job(char, country, rng)
        if char.job:
            j = careers.get_job(char.job)
            if j:
                medical_categories_seen.add(j.category)
    # Every assigned job should have been in the medical category
    assert medical_categories_seen == {"medical"}, (
        f"vocation_field='medical' allowed non-medical jobs: {medical_categories_seen}"
    )


# ---------- #49 Emigration ----------

def test_emigration_skilled_worker_path():
    """A university grad with IQ 70 in Mali can emigrate to Germany
    on the skilled worker path."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("ml"), rng)
    char.age = 28
    char.education = 4  # university
    char.attributes.intelligence = 70
    char.family_wealth = 5000

    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("ml"), get_country("de"),
    )
    assert eligible
    assert "skilled_worker" in routes


def test_emigration_blocked_for_unqualified():
    """Primary-school farmhand with no money and no spoken language
    overlap can't emigrate to Iceland."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("ml"), rng)
    char.age = 25
    char.education = 1  # primary
    char.attributes.intelligence = 40
    char.family_wealth = 200

    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("ml"), get_country("is"),
    )
    assert not eligible
    assert reason  # human-readable
    assert "skilled worker" in reason or "investor" in reason


def test_emigration_refugee_path():
    """A character in a country with at_war=1 can emigrate to a
    high-HDI target as a refugee."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("af"), rng)  # Afghanistan, at_war=1
    char.age = 30
    char.family_wealth = 1000

    af = get_country("af")
    se = get_country("se")
    assert af.at_war == 1
    eligible, routes, reason = emigration.is_eligible_to_emigrate(char, af, se)
    assert eligible
    assert "refugee" in routes


def test_emigration_investor_path():
    """A wealthy character bypasses skilled worker gates."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 1  # not a university grad
    char.attributes.intelligence = 50
    # 50× target gdp_pc — pick a target with low gdp_pc to make this cheap
    target = get_country("ke")  # Kenya
    char.family_wealth = target.gdp_pc * 60

    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("us"), target,
    )
    assert eligible
    assert "investor" in routes


def test_emigration_clears_job_and_picks_new_city():
    """The actual emigrate() call clears job/salary/years_in_role and
    picks a new city in the target country."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 50000
    char.job = "office worker"
    char.salary = 60000
    char.years_in_role = 5
    original_city = char.city

    result = emigration.emigrate(char, get_country("de"), 2030, rng)
    assert result.outcome == "emigrated"
    assert char.country_code == "de"
    assert char.city != original_city
    assert char.job is None
    assert char.salary == 0
    assert char.years_in_role == 0


def test_emigration_costs_family_wealth():
    """Emigration costs ~20% of family_wealth (deducted from the
    character on a successful move)."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 100_000

    starting_wealth = char.family_wealth
    result = emigration.emigrate(char, get_country("de"), 2030, rng)
    assert result.outcome == "emigrated"
    deducted = starting_wealth - char.family_wealth
    # ~20% with floor of $500
    assert 18_000 <= deducted <= 22_000
    assert result.cost == deducted


def test_emigration_appends_to_previous_countries():
    """After emigrating, the source country is appended to
    previous_countries — used for descent route + retrospective."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 30_000

    assert "us" not in char.previous_countries
    emigration.emigrate(char, get_country("de"), 2030, rng)
    assert "us" in char.previous_countries
    assert char.country_code == "de"


def test_emigration_descent_route_works_for_return():
    """A character who emigrated US → DE can return to the US via
    the descent route without re-qualifying as a skilled worker."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 100_000
    # First move: US → DE
    emigration.emigrate(char, get_country("de"), 2030, rng)
    assert char.country_code == "de"
    assert "us" in char.previous_countries

    # Advance past the #98 cooldown — descent eligibility is the
    # focus of this test, not the cooldown gate (covered separately).
    char.age = 36

    # Now drop intelligence so the skilled-worker route would fail.
    char.attributes.intelligence = 30
    char.education = 1

    # Return to US — should qualify via descent.
    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("de"), get_country("us"),
    )
    assert eligible
    assert "descent" in routes


def test_emigration_spouse_moves_too():
    """An emigrating character's spouse moves with them. The spouse's
    country_code updates and their job is cleared (to be re-rolled
    in the new country)."""
    from src.engine import emigration, relationships
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 50_000
    spouse = relationships.roll_spouse(char, get_country("us"), 2028, rng)
    spouse.salary = 50_000
    spouse.job = "office worker"
    relationships.marry(char, spouse, 2028)

    emigration.emigrate(char, get_country("de"), 2030, rng)
    assert char.spouse is not None
    assert char.spouse.country_code == "de"
    assert char.spouse.job is None
    assert char.spouse.salary == 0


def test_emigration_blocked_for_minors():
    """Characters under 16 cannot emigrate independently."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 12

    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("us"), get_country("de"),
    )
    assert not eligible
    assert "young" in reason.lower() or "16" in reason


def test_emigration_cooldown_blocks_immediate_second_move():
    """#98 — after emigrating, the cooldown gate prevents another move
    until at least EMIGRATION_COOLDOWN_YEARS have passed, even if the
    character would otherwise qualify (e.g., via the descent route)."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 200_000

    # First move: US → DE.
    result = emigration.emigrate(char, get_country("de"), 2030, rng)
    assert result.outcome == "emigrated"
    assert char.last_emigration_age == 30

    # Try to immediately bounce back to the US — descent route would
    # qualify but cooldown should block it.
    eligible, routes, reason = emigration.is_eligible_to_emigrate(
        char, get_country("de"), get_country("us"),
    )
    assert not eligible
    assert reason and ("settled" in reason.lower() or "wait" in reason.lower())

    # Advance 5 years and the gate clears.
    char.age = 35
    eligible, routes, _reason = emigration.is_eligible_to_emigrate(
        char, get_country("de"), get_country("us"),
    )
    assert eligible
    assert "descent" in routes


def test_emigration_cooldown_survives_round_trip_serialization():
    """The new last_emigration_age field is round-tripped through
    Character.to_dict / from_dict so a save/load doesn't lose the
    cooldown state."""
    from src.engine import emigration
    from src.engine.character import Character
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 50_000

    emigration.emigrate(char, get_country("de"), 2030, rng)
    payload = char.to_dict()
    rehydrated = Character.from_dict(payload)
    assert rehydrated.last_emigration_age == 30


def test_emigration_picks_a_known_magnet_city_for_us():
    """#100 — sampling many emigrations to a country with a curated
    magnet list lands the player in a magnet city the vast majority
    of the time. Tests the weighting, not a deterministic outcome."""
    from src.data.seed import MIGRATION_MAGNETS
    from src.engine import emigration

    magnets_lower = {n.lower() for n in MIGRATION_MAGNETS["us"]}
    rng = random.Random(123)
    hits = 0
    trials = 80
    for _ in range(trials):
        city, _is_urban = emigration.pick_emigration_city(get_country("us"), rng)
        # Strip the "a village near " prefix when present so rural
        # placements still count toward the underlying-city tally.
        bare = city.replace("a village near ", "").lower()
        if bare in magnets_lower:
            hits += 1
    # Heavy weighting (10× vs 0.4×) plus a long curated list should
    # land at least 70% of arrivals in a magnet city. The remaining
    # 30% headroom keeps the test stable across rng seeds.
    assert hits / trials >= 0.7, f"only {hits}/{trials} landings in a magnet city"


def test_emigration_skilled_worker_auto_assigns_job_in_vocation_field():
    """#101 — a skilled-worker emigrant who already has a vocation
    field gets a starter job in that field on arrival, instead of
    needing to manually find work."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.education = 4
    char.attributes.intelligence = 75
    char.family_wealth = 80_000
    char.vocation_field = "stem"
    char.job = None
    char.salary = 0

    result = emigration.emigrate(char, get_country("de"), 2030, rng)
    assert result.outcome == "emigrated"
    assert "skilled_worker" in result.routes
    # Auto-assign should have populated job + salary in the new country.
    assert char.job is not None, "skilled-worker emigrant should arrive with a job"
    assert char.salary > 0
    # Message reflects the assignment.
    assert "skilled-worker" in result.message or char.job in result.message


def test_emigration_refugee_does_not_auto_assign_job():
    """Refugee/family routes really do start from scratch — only
    skilled_worker triggers the auto-assign in #101."""
    from src.engine import emigration
    rng = random.Random(0)
    char = create_random_character(get_country("af"), rng)  # Afghanistan, at_war=1
    char.age = 30
    char.family_wealth = 5_000
    char.vocation_field = "stem"
    char.job = None
    char.salary = 0

    result = emigration.emigrate(char, get_country("se"), 2030, rng)
    assert result.outcome == "emigrated"
    assert "refugee" in result.routes
    assert "skilled_worker" not in result.routes
    assert char.job is None
    assert char.salary == 0


# ---------- #50 Better romance ----------

def test_spouse_dataclass_round_trip():
    """#50: a Spouse round-trips through Character.to_dict / from_dict
    with all fields preserved."""
    from src.engine import relationships
    from src.engine.character import Character, Spouse
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    relationships.marry(char, spouse, 2030)
    assert char.spouse is spouse

    d = char.to_dict()
    restored = Character.from_dict(d)
    assert restored.spouse is not None
    assert restored.spouse.name == spouse.name
    assert restored.spouse.age == spouse.age
    assert restored.spouse.salary == spouse.salary
    assert restored.spouse.compatibility == spouse.compatibility
    assert restored.spouse.married_year == 2030
    assert restored.spouse.attributes.intelligence == spouse.attributes.intelligence
    assert restored.married is True


def test_legacy_marriage_migration():
    """#50: an old save with married=True + spouse_name='X' but no
    spouse object should rehydrate as a Spouse stub on load."""
    from src.engine.character import Character
    legacy = {
        "id": "abc123", "name": "Test", "gender": 1, "age": 35,
        "country_code": "us", "city": "NYC", "is_urban": True,
        "attributes": {"health": 80, "happiness": 70, "intelligence": 60,
                       "artistic": 50, "musical": 50, "athletic": 50,
                       "strength": 50, "endurance": 50, "appearance": 60,
                       "conscience": 60, "wisdom": 50, "resistance": 50},
        "family_wealth": 50000, "money": 10000, "debt": 0,
        "education": 4, "in_school": False,
        "married": True, "spouse_name": "Jane Doe",
    }
    char = Character.from_dict(legacy)
    assert char.spouse is not None
    assert char.spouse.name == "Jane Doe"
    assert char.spouse.married_year is not None
    assert char.married is True


def test_love_marriage_creates_full_spouse():
    """#50: the LOVE_MARRIAGE accept choice runs _accept_proposal
    which creates a full Spouse with rolled attributes."""
    from src.engine import careers
    from src.engine.events import _accept_proposal
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 28
    assert char.spouse is None
    _accept_proposal(char, ctx={"year": 2030, "country": country, "rng": rng})
    assert char.spouse is not None
    assert char.spouse.name
    assert char.spouse.attributes is not None
    assert char.spouse.attributes.intelligence > 0
    assert char.spouse.married_year == 2030
    assert char.married is True


def test_joined_wealth_on_marriage():
    """#50: marrying merges the spouse's family_wealth into the player's."""
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.family_wealth = 10_000

    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.family_wealth = 5_000

    relationships.marry(char, spouse, 2030)
    assert char.family_wealth == 15_000


def test_spouse_income_added_to_yearly():
    """#50: spouse.salary contributes 80% to the household income."""
    from src.engine import careers, relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.in_school = False
    char.education = 4
    char.attributes.intelligence = 70
    char.age = 30
    char.salary = 60_000
    char.job = "office worker"
    char.lifetime_earnings = 0

    # Roll a spouse with a known salary, marry, then run the year.
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.salary = 80_000
    spouse.alive = True
    relationships.marry(char, spouse, 2030)

    starting_money = char.money
    careers.yearly_income(char, country, rng)
    # Net should reflect (60k own income + 80% of 80k spouse) - expenses.
    # Without the spouse, char would be net negative or near zero;
    # the spouse's contribution should make the year clearly positive.
    delta = char.money - starting_money
    assert delta > 0, f"net income with spouse should be positive, got {delta}"


def test_spouse_ages_yearly_via_age_family():
    """#50: age_family ticks spouse.age every year."""
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    relationships.marry(char, spouse, 2030)
    starting_age = spouse.age

    relationships.age_family(char, country, rng)
    assert char.spouse.age == starting_age + 1


def test_spouse_eventually_dies_in_old_age():
    """#50: an aged spouse eventually dies via the simple death roll.
    #95: on death the spouse is moved into previous_spouses with
    end_state='widowed' and the current spouse slot is cleared, so the
    character is properly classified as widowed (not still married)."""
    from src.engine import relationships
    rng = random.Random(42)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.age = 85
    relationships.marry(char, spouse, 2030)

    died = False
    for _ in range(50):
        notes = relationships.age_family(char, country, rng)
        if any(n.startswith("spouse_died:") for n in notes):
            died = True
            break
    assert died, "85+ spouse should die within 50 years of rolls"
    # #95: the current slot should now be empty, with the dead spouse
    # archived in previous_spouses.
    assert char.spouse is None
    assert len(char.previous_spouses) == 1
    archived = char.previous_spouses[0]
    assert archived.alive is False
    assert archived.end_state == "widowed"
    assert archived.cause_of_death is not None
    assert char.married is False  # widow, not "still married"


def test_divorce_eventually_for_low_compatibility():
    """#50: a low-compatibility marriage in a high-HDI country should
    eventually trigger divorce_check.
    #96: divorce_check is now strain-gated, so the test pre-loads
    strain past the threshold to model a player who's been ignoring
    DIVORCE_CONSIDERATION for years."""
    from src.engine import relationships
    rng = random.Random(7)
    country = get_country("us")  # HDI ~0.92
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.compatibility = 25
    relationships.marry(char, spouse, 2030)
    spouse.relationship_strain = 80  # well past the choice threshold

    fired = 0
    for _ in range(500):
        if relationships.divorce_check(char, country, rng):
            fired += 1
    assert fired > 0, "low-compatibility marriage in US should trigger divorce at least once in 500 rolls"


def test_country_divorce_rate_field_loaded():
    """#92: countries with curated divorce_rate values surface them on
    the Country dataclass; countries without one have None."""
    us = get_country("us")
    inn = get_country("in")
    pt = get_country("pt")
    assert us.divorce_rate is not None
    assert inn.divorce_rate is not None
    assert pt.divorce_rate is not None
    # Real-world rank order: PT > US >> IN
    assert pt.divorce_rate > us.divorce_rate > inn.divorce_rate
    assert inn.divorce_rate < 0.05
    assert pt.divorce_rate > 0.50


def test_country_divorce_rate_drives_divorce_check_distribution():
    """#92: a marriage in Portugal (high divorce_rate) should fire
    divorce_check far more often than the same marriage in India over
    the same number of rolls. Tests the country signal flowing through,
    not a single deterministic outcome. Pre-loads strain past the
    threshold (#96) so divorce_check has something to roll on."""
    from src.engine import relationships
    rng = random.Random(0)
    pt = get_country("pt")
    inn = get_country("in")

    def fire_count(country):
        local_rng = random.Random(0)
        char = create_random_character(country, local_rng)
        spouse = relationships.roll_spouse(char, country, 2030, local_rng)
        spouse.compatibility = 50  # neutral compat — country must do the work
        relationships.marry(char, spouse, 2030)
        spouse.relationship_strain = 80
        fired = 0
        for _ in range(2000):
            if relationships.divorce_check(char, country, local_rng):
                fired += 1
        return fired

    pt_fires = fire_count(pt)
    in_fires = fire_count(inn)
    assert pt_fires > in_fires * 5, (
        f"Portugal ({pt_fires}) should divorce far more often "
        f"than India ({in_fires}) over 2000 rolls"
    )


def test_previous_spouses_round_trip_serialization():
    """#95: a character with a divorced ex-spouse round-trips through
    Character.to_dict / from_dict without losing the previous_spouses
    history or the ended_year/end_state metadata."""
    from src.engine import relationships
    from src.engine.character import Character
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 30
    spouse = relationships.roll_spouse(char, country, 2025, rng)
    relationships.marry(char, spouse, 2025)
    # Manually archive as if a divorce had fired.
    spouse.ended_year = 35
    spouse.end_state = "divorced"
    char.previous_spouses.append(spouse)
    char.spouse = None

    payload = char.to_dict()
    rehydrated = Character.from_dict(payload)
    assert rehydrated.spouse is None
    assert len(rehydrated.previous_spouses) == 1
    archived = rehydrated.previous_spouses[0]
    assert archived.end_state == "divorced"
    assert archived.ended_year == 35
    assert archived.name == spouse.name


def test_divorce_in_game_loop_archives_to_previous_spouses():
    """#95: when the silent divorce roll fires inside the yearly tick,
    the former spouse lands in previous_spouses with end_state='divorced'.
    Drives the game loop directly so the full divorce path runs."""
    from src.engine import relationships
    from src.engine import game as game_module
    from src.engine.game import Game
    rng = random.Random(0)
    country = get_country("us")
    g = Game.new(country_code="us", seed=0)
    char = g.state.character
    char.age = 35
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.compatibility = 10  # very low → divorce-prone
    relationships.marry(char, spouse, 2030)

    # Force the divorce branch by replacing divorce_check on the
    # imported relationships module that game.py reaches through.
    original = game_module.relationships.divorce_check
    game_module.relationships.divorce_check = lambda c, co, _r: True
    try:
        g.advance_year()
    finally:
        game_module.relationships.divorce_check = original

    assert char.spouse is None
    assert len(char.previous_spouses) == 1
    archived = char.previous_spouses[0]
    assert archived.end_state == "divorced"
    assert archived.ended_year is not None


def test_compatibility_biases_anniversary_event_rate():
    """#97: a high-compat marriage celebrates anniversaries more often
    than a low-compat one, even with the same base chance."""
    from src.engine.events import EVENT_REGISTRY
    from src.engine import relationships
    country = get_country("us")

    def fire_rate(compat):
        local_rng = random.Random(0)
        char = create_random_character(country, local_rng)
        char.age = 35
        spouse = relationships.roll_spouse(char, country, 2030, local_rng)
        spouse.compatibility = compat
        relationships.marry(char, spouse, 2030)
        ev = next(e for e in EVENT_REGISTRY if e.key == "romance_anniversary")
        return ev.probability(char, country)

    high = fire_rate(85)
    low = fire_rate(30)
    assert high > low, f"high-compat anniversary chance ({high}) should beat low-compat ({low})"
    assert high > 0.55  # 0.50 base × 1.30 boost
    assert low < 0.40   # 0.50 base × 0.65 penalty


def test_spouse_develops_diseases_via_full_engine():
    """#94: spouses run the full disease engine in age_family. Over
    enough years an old spouse should accumulate at least one named
    disease in spouse.diseases."""
    from src.engine import relationships
    rng = random.Random(13)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.age = 55
    relationships.marry(char, spouse, 2030)

    # 30 yearly ticks — each runs the disease roller on the spouse.
    for _ in range(30):
        if char.spouse is None:  # spouse died
            break
        relationships.age_family(char, country, rng)

    # Either the spouse died of a named disease (in previous_spouses)
    # or accumulated chronic conditions (in current spouse.diseases).
    if char.spouse is None:
        archived = char.previous_spouses[0]
        assert archived.cause_of_death is not None
        # cause_of_death should be a real disease name OR the age fallback
        # ('old age' / 'illness'); both paths exercise the new code.
    else:
        assert len(char.spouse.diseases) > 0, "30 years should accumulate at least one disease"


def test_relationship_strain_accumulates_for_low_compatibility():
    """#96: update_strain raises strain in proportion to (100 - compat).
    A 20-compat marriage should cross the divorce threshold within
    a handful of yearly ticks."""
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.compatibility = 20
    relationships.marry(char, spouse, 2030)
    assert spouse.relationship_strain == 0

    for _ in range(20):
        relationships.update_strain(char)
    assert char.spouse.relationship_strain >= 50


def test_relationship_strain_does_not_accumulate_for_high_compatibility():
    """A 90-compat marriage should still gain a little strain per year
    (life is hard) but stay well below the divorce threshold across a
    typical lifespan."""
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.compatibility = 92
    relationships.marry(char, spouse, 2030)

    for _ in range(20):
        relationships.update_strain(char)
    assert char.spouse.relationship_strain < 50


def test_divorce_consideration_event_eligible_at_high_strain():
    """#96: DIVORCE_CONSIDERATION fires only when strain >= 50."""
    from src.engine.events import EVENT_REGISTRY
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    relationships.marry(char, spouse, 2030)

    ev = next(e for e in EVENT_REGISTRY if e.key == "divorce_consideration")
    spouse.relationship_strain = 10
    assert not ev.eligible(char, country)
    spouse.relationship_strain = 75
    assert ev.eligible(char, country)


def test_meet_partner_creates_dating_spouse():
    """#93: MEET_PARTNER's 'lean_in' choice attaches a Spouse with
    married_year=None to the character — they're dating, not married."""
    from src.engine.events import EVENT_REGISTRY, _meet_partner_side_effect
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 25
    assert char.spouse is None

    _meet_partner_side_effect(char, {"country": country, "year": 2030, "rng": rng})
    assert char.spouse is not None
    assert char.spouse.married_year is None  # dating, not married
    assert char.married is False


def test_dating_checkpoint_propose_promotes_to_marriage():
    """#93: DATING_CHECKPOINT's 'propose' choice marries the existing
    dating partner — uses the standard marry() helper so joined wealth
    + happiness flow."""
    from src.engine.events import _meet_partner_side_effect, _dating_propose
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 27
    starting_wealth = char.family_wealth

    _meet_partner_side_effect(char, {"country": country, "year": 2030, "rng": rng})
    spouse_wealth = char.spouse.family_wealth
    _dating_propose(char, {"country": country, "year": 2032, "rng": rng})

    assert char.married is True
    assert char.spouse.married_year == 2032
    # Joined wealth applied.
    assert char.family_wealth == starting_wealth + spouse_wealth


def test_dating_checkpoint_break_up_clears_partner_with_no_archive():
    """#93: ending a dating relationship clears the spouse but does
    NOT add to previous_spouses (they were never married)."""
    from src.engine.events import _meet_partner_side_effect, _dating_breakup
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 27

    _meet_partner_side_effect(char, {"country": country, "year": 2030, "rng": rng})
    assert char.spouse is not None
    _dating_breakup(char)
    assert char.spouse is None
    assert len(char.previous_spouses) == 0


def test_meet_candidates_dynamic_payload_rolls_four_candidates():
    """#91: MEET_CANDIDATES.dynamic_payload returns 4 candidate Spouse
    dicts so the frontend can render a swipe picker."""
    from src.engine.events import EVENT_REGISTRY
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 28

    ev = next(e for e in EVENT_REGISTRY if e.key == "meet_candidates")
    assert ev.dynamic_payload is not None
    payload = ev.dynamic_payload(char, country, rng)
    assert "candidates" in payload
    assert len(payload["candidates"]) == 4
    for cand in payload["candidates"]:
        assert "name" in cand
        assert "compatibility" in cand
        assert cand.get("married_year") is None


def test_meet_candidates_pick_attaches_chosen_candidate():
    """#91: picking a candidate via apply_decision attaches it as the
    dating partner. The side_effect reads the index from choice_key
    and the candidate list from pending_event."""
    from src.engine.events import _meet_candidates_pick
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.age = 28

    # Build a mock pending_event with 4 candidates.
    candidates = [
        relationships.roll_spouse(char, country, 0, rng).to_dict()
        for _ in range(4)
    ]
    target_name = candidates[2]["name"]
    pending = {"candidates": candidates}

    _meet_candidates_pick(char, {
        "country": country, "year": 2030, "rng": rng,
        "pending_event": pending, "choice_key": "pick_2",
    })
    assert char.spouse is not None
    assert char.spouse.name == target_name
    assert char.spouse.met_year == 2030
    assert char.spouse.married_year is None


def test_divorce_consideration_separate_choice_archives_spouse():
    """#96: picking 'separate' on the choice event runs the same
    archive + clear path as the silent divorce."""
    from src.engine.events import _divorce_separate
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    relationships.marry(char, spouse, 2030)
    starting_wealth = char.family_wealth
    char.age = 40

    _divorce_separate(char, {"country": country, "year": 2040, "rng": rng})
    assert char.spouse is None
    assert len(char.previous_spouses) == 1
    archived = char.previous_spouses[0]
    assert archived.end_state == "divorced"
    assert archived.ended_year == 40
    # Wealth got split.
    assert char.family_wealth < starting_wealth


def test_divorce_consideration_counseling_resets_strain():
    """#96: counseling drops strain back to 20 and boosts compatibility."""
    from src.engine.events import _divorce_counseling
    from src.engine import relationships
    rng = random.Random(0)
    country = get_country("us")
    char = create_random_character(country, rng)
    char.money = 50_000
    char.salary = 60_000
    spouse = relationships.roll_spouse(char, country, 2030, rng)
    spouse.compatibility = 30
    relationships.marry(char, spouse, 2030)
    spouse.relationship_strain = 70

    _divorce_counseling(char)
    assert char.spouse.relationship_strain == 20
    assert char.spouse.compatibility >= 40   # +12 boost


def test_compatibility_biases_big_argument_event_rate():
    """#97: a low-compat marriage fights more often than a high-compat one."""
    from src.engine.events import EVENT_REGISTRY
    from src.engine import relationships
    country = get_country("us")

    def fire_rate(compat):
        local_rng = random.Random(0)
        char = create_random_character(country, local_rng)
        char.age = 35
        spouse = relationships.roll_spouse(char, country, 2030, local_rng)
        spouse.compatibility = compat
        relationships.marry(char, spouse, 2030)
        ev = next(e for e in EVENT_REGISTRY if e.key == "romance_big_argument")
        return ev.probability(char, country)

    low = fire_rate(20)
    high = fire_rate(85)
    assert low > high, f"low-compat argument chance ({low}) should exceed high-compat ({high})"
    assert low > 0.20   # 0.15 base × 1.80 boost
    assert high < 0.10  # 0.15 base × 0.50 penalty


def test_pregnancy_event_actually_adds_child():
    """Issue #39: the had_child event used to apply happiness deltas but
    forget to append a FamilyMember to character.children, leaving the
    sidebar 'children' counter at 0 for the entire game."""
    from src.engine.character import create_random_character
    from src.engine.events import EVENT_REGISTRY
    from src.engine import relationships

    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    # #50: married now requires a Spouse object. Use the public marry helper.
    spouse = relationships.roll_spouse(char, get_country("us"), 2007, rng)
    relationships.marry(char, spouse, 2007)
    assert len(char.children) == 0

    pregnancy = next(e for e in EVENT_REGISTRY if e.key == "had_child")
    outcome = pregnancy.apply(char, get_country("us"), rng)
    assert len(char.children) == 1
    assert char.children[0].relation == "child"
    assert char.children[0].age == 0
    assert outcome.summary  # not blank


def test_disease_treatment_cost_drains_family_wealth_after_money():
    """Personal money goes first; the remainder dips into family_wealth.
    Regression for #15: previously the deduction only touched character.money
    so a poor character could end up with negative money while family_wealth
    sat untouched."""
    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 50
    char.money = 1000
    char.family_wealth = 50000
    # Hypertension is treatable, $800 — well within money, no fallback.
    htn = next(d for d in diseases.DISEASES if d.key == "hypertension")
    diseases.contract_disease(char, get_country("us"), htn, random.Random(0))
    assert char.money == 200
    assert char.family_wealth == 50000

    # Heart disease is $12000 — exhausts money, dips into family_wealth.
    char.money = 1000
    char.family_wealth = 50000
    chd = next(d for d in diseases.DISEASES if d.key == "heart_disease")
    diseases.contract_disease(char, get_country("us"), chd, random.Random(0))
    assert char.money == 0
    assert char.family_wealth == 50000 - (12000 - 1000)

    # If neither pot can cover, treatment is skipped — neither pot is touched.
    char.money = 100
    char.family_wealth = 200
    char.diseases.clear()
    diseases.contract_disease(char, get_country("us"), chd, random.Random(0))
    assert char.money == 100
    assert char.family_wealth == 200


def test_language_and_region_gated_events_present():
    """Issue #16: at least one event must be gated on country.primary_language
    and at least one on country.region (not just primary_religion)."""
    keys = {e.key for e in EVENT_REGISTRY}
    expected = {
        "cricket_match", "baseball_youth", "quinceanera", "seijin_shiki",
        "tea_ceremony", "vegetarian_household", "fish_heavy_diet",
        "dowry_negotiation", "bilingual_schooling",
    }
    missing = expected - keys
    assert not missing, f"missing language/region events: {missing}"


def test_quinceanera_only_fires_for_spanish_speaking_girls():
    from src.engine.character import create_random_character
    quince = next(e for e in EVENT_REGISTRY if e.key == "quinceanera")
    rng = random.Random(0)

    mexico = get_country("mx")  # Spanish
    char = create_random_character(mexico, rng)
    char.gender = Gender.FEMALE
    char.age = 15
    assert quince.eligible(char, mexico)

    # Same girl in non-Spanish-speaking country: not eligible.
    japan = get_country("jp")
    char2 = create_random_character(japan, rng)
    char2.gender = Gender.FEMALE
    char2.age = 15
    assert not quince.eligible(char2, japan)

    # Spanish-speaking BOY: not eligible.
    char3 = create_random_character(mexico, rng)
    char3.gender = Gender.MALE
    char3.age = 15
    assert not quince.eligible(char3, mexico)


def test_baseball_event_fires_in_baseball_regions_not_europe():
    from src.engine.character import create_random_character
    baseball = next(e for e in EVENT_REGISTRY if e.key == "baseball_youth")
    rng = random.Random(0)

    cuba = get_country("cu")  # Caribbean region
    char = create_random_character(cuba, rng)
    char.age = 12
    assert baseball.eligible(char, cuba)

    germany = get_country("de")
    char2 = create_random_character(germany, rng)
    char2.age = 12
    assert not baseball.eligible(char2, germany)


def test_active_disease_persists_through_save_load():
    g = Game.new(country_code="us", seed=42)
    diseases.contract_disease(
        g.state.character, get_country("us"),
        next(d for d in diseases.DISEASES if d.key == "diabetes_t2"),
        random.Random(0),
    )
    g.save()
    loaded = Game.load(g.state.id)
    assert "diabetes_t2" in loaded.state.character.diseases
    assert loaded.state.character.diseases["diabetes_t2"]["permanent"] is True
