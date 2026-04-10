"""End-to-end tests for the FastAPI app."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


def _seek_work_via_engine(gid):
    """Mirror what an active player does after each advance: if the
    character is jobless and old enough to work, find them a job. The
    engine no longer auto-assigns in advance_year (deliberate
    joblessness — see commit removing auto-assign), so API tests that
    simulate cohort play need to drive employment explicitly. Bypasses
    the API surface because no /find_work endpoint exists; the real
    frontend uses the job board flow which is awkward to script."""
    from src.engine import careers
    from src.engine.game import load_game
    from src.engine.world import get_country
    g = load_game(gid)
    if g is None:
        return
    char = g.state.character
    if char.job is None and not char.in_school and char.age >= 14:
        country = get_country(char.country_code)
        if country is not None:
            careers.assign_job(char, country, g.rng)
            g.save()


def _force_solvent_adult(gid, age=25, money=10000):
    """Bypass the cohort sim entirely and put the character in a known
    state for endpoint-specific tests. Loan / invest tests don't need
    to simulate 20 years of cost-of-living drain — they just need an
    adult character with cash. Using this avoids brittle seed-sensitive
    failures whenever any rng-touching change shifts downstream
    determinism."""
    from src.engine import careers
    from src.engine.character import EducationLevel
    from src.engine.game import load_game
    from src.engine.world import get_country
    g = load_game(gid)
    if g is None:
        return
    char = g.state.character
    char.age = age
    char.in_school = False
    char.school_track = None
    char.education = EducationLevel.SECONDARY
    char.money = money
    if char.job is None:
        country = get_country(char.country_code)
        if country is not None:
            careers.assign_job(char, country, g.rng)
    g.save()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_countries(client):
    r = client.get("/api/countries")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 30
    codes = {c["code"] for c in body}
    assert "us" in codes
    assert "in" in codes
    assert "ng" in codes


def test_country_detail_404(client):
    assert client.get("/api/countries/zz").status_code == 404


def test_country_detail_includes_binary_facts(client):
    """Issue #30: country detail surfaces at_war / military_conscription
    flags plus a structured binary_facts payload (human rights, military
    service, disaster history). Issue #34: disaster history is structured
    as a list of per-event records."""
    r = client.get("/api/countries/iq")
    assert r.status_code == 200
    body = r.json()
    assert body["at_war"] is True  # Iraq, 2007 binary
    facts = body["binary_facts"]
    assert facts is not None
    assert facts["at_war"] is True
    assert "Torture" in facts["human_rights"]
    assert facts["military_service"]["MilitaryConscription"] is True
    # Disaster history shape (#34): list of {kind, events, killed_per_event,
    # affected_per_event} records.
    assert isinstance(facts["disaster_history"], list)
    assert facts["disaster_history"]  # Iraq has earthquake history
    quake = next(d for d in facts["disaster_history"] if d["kind"] == "earthquake")
    assert quake["events"] > 0
    assert "killed_per_event" in quake
    assert "affected_per_event" in quake


def test_binary_facts_endpoint(client):
    """The /api/countries/<code>/binary_facts endpoint returns the full
    raw fact sheet for binary-mappable countries."""
    r = client.get("/api/countries/us/binary_facts")
    assert r.status_code == 200
    body = r.json()
    assert body["AtWar"] is False
    assert body["MilitaryConscription"] is False
    assert "Population" in body

    # Bermuda is a #7 territory addition not in the binary.
    r = client.get("/api/countries/bm/binary_facts")
    assert r.status_code == 404


def test_full_game_flow(client):
    # 1. New game
    r = client.post("/api/game/new", json={"country_code": "br", "seed": 13})
    assert r.status_code == 200
    g = r.json()
    assert g["country"]["code"] == "br"
    assert g["character"]["age"] == 0
    gid = g["id"]

    # 2. Advance some years.
    for _ in range(20):
        rr = client.post(f"/api/game/{gid}/advance").json()
        if rr["turn"]["pending_decision"]:
            ck = rr["turn"]["pending_decision"]["choices"][0]["key"]
            dr = client.post(
                f"/api/game/{gid}/decision",
                json={"choice_key": ck},
            )
            assert dr.status_code == 200
        if rr["turn"]["died"]:
            break

    # 3. Final state should be retrievable.
    r = client.get(f"/api/game/{gid}")
    assert r.status_code == 200
    g = r.json()
    assert g["character"]["age"] >= 1


def test_game_not_found(client):
    assert client.get("/api/game/does-not-exist").status_code == 404


def test_list_finance_products(client):
    inv = client.get("/api/investments").json()
    ln = client.get("/api/loans").json()
    assert len(inv) >= 5
    assert len(ln) >= 5
    # Schema sanity
    assert {"id", "name", "annual_return_low", "min_amount"}.issubset(inv[0].keys())
    assert {"id", "name", "max_amount", "interest_rate", "max_years"}.issubset(ln[0].keys())


def test_invest_and_sell_round_trip(client):
    # New game then force the character into a known solvent adult
    # state. This test verifies the loan + invest endpoints, not the
    # cost-of-living simulation; cohort-walking it is brittle.
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 7}).json()
    gid = g["id"]
    _force_solvent_adult(gid, age=25, money=10000)
    g = client.get(f"/api/game/{gid}").json()

    # Hand the character some money via loan, then invest it.
    money_before = g["character"]["money"]
    loans = client.get("/api/loans").json()
    personal = next(p for p in loans if p["name"] == "personal loan")
    r = client.post(f"/api/game/{gid}/loan", json={"product_id": personal["id"], "amount": 5000})
    assert r.status_code == 200
    g = r.json()
    assert g["character"]["money"] == money_before + 5000
    assert g["character"]["debt"] == 5000
    assert len(g["character"]["loans"]) == 1

    invs = client.get("/api/investments").json()
    bonds = next(p for p in invs if "bonds" in p["name"])
    money_before_invest = g["character"]["money"]
    r = client.post(f"/api/game/{gid}/invest", json={"product_id": bonds["id"], "amount": 2000})
    assert r.status_code == 200
    g = r.json()
    assert g["portfolio_value"] == 2000
    assert len(g["character"]["investments"]) == 1
    assert g["character"]["money"] == money_before_invest - 2000

    # Sell the investment back
    r = client.post(f"/api/game/{gid}/sell_investment", json={"index": 0})
    assert r.status_code == 200
    g = r.json()
    assert g["portfolio_value"] == 0
    assert len(g["character"]["investments"]) == 0


def test_loan_validation(client):
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 11}).json()
    gid = g["id"]
    loans = client.get("/api/loans").json()
    family = next(p for p in loans if p["name"] == "family loan")
    # Over the cap
    r = client.post(f"/api/game/{gid}/loan", json={"product_id": family["id"], "amount": 10**9})
    assert r.status_code == 400


def test_quit_job_clears_employment(client):
    """Issue #38: a player should be able to quit a job and roll for
    a new one next year."""
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 7}).json()
    gid = g["id"]
    # Advance until they get a job (driving find-work via the engine
    # since the engine no longer auto-assigns).
    for _ in range(40):
        rr = client.post(f"/api/game/{gid}/advance").json()
        if rr["turn"]["pending_decision"]:
            client.post(f"/api/game/{gid}/decision", json={"choice_key": rr["turn"]["pending_decision"]["choices"][0]["key"]})
        g = rr["game"]
        if rr["turn"]["died"]:
            pytest.skip("character died before getting a job")
        _seek_work_via_engine(gid)
        g = client.get(f"/api/game/{gid}").json()
        if g["character"]["job"]:
            break
    if not g["character"]["job"]:
        pytest.skip("character never got a job in 40 years")

    # Quit
    g = client.post(f"/api/game/{gid}/quit_job").json()
    assert g["character"]["job"] is None
    assert g["character"]["salary"] == 0

    # Quitting again should 400
    r = client.post(f"/api/game/{gid}/quit_job")
    assert r.status_code == 400


def test_pay_loan_endpoint_clears_balance(client):
    """Issue #40: a player should be able to pay extra against an open
    loan to clear it early."""
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 7}).json()
    gid = g["id"]
    _force_solvent_adult(gid, age=25, money=10000)
    g = client.get(f"/api/game/{gid}").json()

    # Take a personal loan
    loans = client.get("/api/loans").json()
    personal = next(p for p in loans if p["name"] == "personal loan")
    g = client.post(f"/api/game/{gid}/loan", json={"product_id": personal["id"], "amount": 5000}).json()
    assert len(g["character"]["loans"]) == 1
    initial_balance = g["character"]["loans"][0]["balance"]

    # Pay 1000 extra against it
    g = client.post(f"/api/game/{gid}/pay_loan", json={"index": 0, "amount": 1000}).json()
    assert g["character"]["loans"][0]["balance"] == initial_balance - 1000

    # Pay the exact remaining balance — should clear the loan entirely.
    remaining = g["character"]["loans"][0]["balance"]
    available_cash = g["character"]["money"]
    if available_cash >= remaining:
        g = client.post(f"/api/game/{gid}/pay_loan", json={"index": 0, "amount": remaining}).json()
        assert len(g["character"]["loans"]) == 0
        assert g["character"]["debt"] == 0


def test_loan_age_gate(client):
    """Issue #37: a 0-year-old shouldn't be able to take out a mortgage."""
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 99}).json()
    gid = g["id"]
    loans = client.get("/api/loans").json()
    mortgage = next(p for p in loans if p["name"] == "mortgage")
    family = next(p for p in loans if p["name"] == "family loan")

    # Newborn → no loans at all.
    r = client.post(f"/api/game/{gid}/loan", json={"product_id": mortgage["id"], "amount": 1000})
    assert r.status_code == 400
    assert "18" in r.json()["detail"]
    r = client.post(f"/api/game/{gid}/loan", json={"product_id": family["id"], "amount": 100})
    assert r.status_code == 400
    assert "14" in r.json()["detail"]


def test_invest_validation_insufficient_funds(client):
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 17}).json()
    gid = g["id"]
    invs = client.get("/api/investments").json()
    realestate = next(p for p in invs if "real estate" in p["name"])
    r = client.post(f"/api/game/{gid}/invest", json={"product_id": realestate["id"], "amount": 100000})
    assert r.status_code == 400


def test_self_employment_kinds_in_job_board_and_career_payload(client):
    """#83: the new modern self-employment kinds appear on the job
    board with is_freelance=True, and an applied freelance job
    surfaces is_freelance in the /game career payload so the frontend
    can swap raise/promo buttons for entrepreneur UI."""
    from src.engine import careers
    from src.engine.game import load_game
    from src.engine.world import get_country

    g = client.post("/api/game/new", json={"country_code": "us", "seed": 23}).json()
    gid = g["id"]

    # Advance the character to age 25 so they can see all self-employment kinds.
    while g["character"]["age"] < 25:
        rr = client.post(f"/api/game/{gid}/advance").json()
        if rr["turn"]["pending_decision"]:
            client.post(f"/api/game/{gid}/decision", json={"choice_key": rr["turn"]["pending_decision"]["choices"][0]["key"]})
        g = rr["game"]
        if rr["turn"]["died"]:
            pytest.skip("character died young")

    # /job_board should include the new freelance kinds (with show_all
    # toggled on so out_of_reach + long_shot show too).
    listings = client.get(f"/api/game/{gid}/job_board").json()
    listing_names = {l["name"] for l in listings}
    for name in ("online seller", "content creator", "food vendor", "gig worker", "freelance consultant"):
        assert name in listing_names, f"{name} missing from job board"
    # Each new kind is flagged is_freelance.
    for l in listings:
        if l["name"] in ("online seller", "content creator", "food vendor", "gig worker", "freelance consultant"):
            assert l["is_freelance"] is True, f"{l['name']} should be is_freelance"

    # Manually park the character in a freelance job (bypassing the
    # accept-probability roll for test reliability).
    game = load_game(gid)
    food_vendor = careers.get_job("food vendor")
    assert food_vendor is not None
    careers._set_job(game.state.character, get_country("us"), food_vendor, game.rng)
    game.save()

    # The career payload exposes is_freelance.
    g = client.get(f"/api/game/{gid}").json()
    assert g["career"]["current_job"] == "food vendor"
    assert g["career"]["is_freelance"] is True
