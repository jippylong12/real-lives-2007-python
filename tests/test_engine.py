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
