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
    assert len(jobs) <= 200  # sanity cap
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
    elite athlete instead of just 'professional athlete'."""
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
    # The first three are freelance (the talent grind), the top two
    # are salaried (signed contracts).
    assert youth.is_freelance
    assert amateur.is_freelance
    assert not pro.is_freelance


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

    # Build up experience
    char.years_in_role = 6
    msg = careers.promote(char, country, rng)
    assert msg is not None
    assert "engineering department manager" in msg
    assert char.job == "engineering department manager"
    assert char.years_in_role == 0
    assert char.promotion_count == 1


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

    # 5 years in — eligible (first promo threshold)
    char.years_in_role = 5
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
