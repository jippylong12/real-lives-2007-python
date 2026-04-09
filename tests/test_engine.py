"""Tests for the game engine: birth, attributes, death rolls, events."""

import random

import pytest

from src.engine import Game
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
