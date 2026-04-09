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
    entries with categories + ladders), not the curated 30-job seed."""
    from src.engine import careers
    jobs = careers.all_jobs()
    assert len(jobs) == 131
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

    # Build up experience
    char.years_in_role = 6
    msg = careers.promote(char, country, rng)
    assert msg is not None
    assert "engineering department manager" in msg
    assert char.job == "engineering department manager"
    assert char.years_in_role == 0
    assert char.promotion_count == 1


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


def test_pregnancy_event_actually_adds_child():
    """Issue #39: the had_child event used to apply happiness deltas but
    forget to append a FamilyMember to character.children, leaving the
    sidebar 'children' counter at 0 for the entire game."""
    from src.engine.character import create_random_character
    from src.engine.events import EVENT_REGISTRY

    rng = random.Random(0)
    char = create_random_character(get_country("us"), rng)
    char.age = 30
    char.married = True
    char.spouse_name = "Test Spouse"
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
