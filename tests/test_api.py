"""End-to-end tests for the FastAPI app."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


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
    service, disaster history)."""
    r = client.get("/api/countries/iq")
    assert r.status_code == 200
    body = r.json()
    assert body["at_war"] is True  # Iraq, 2007 binary
    facts = body["binary_facts"]
    assert facts is not None
    assert facts["at_war"] is True
    assert "Torture" in facts["human_rights"]
    assert facts["military_service"]["MilitaryConscription"] is True
    assert facts["disaster_history"]  # Iraq has earthquake history


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
    # New game with deterministic seed; advance to give player some money to invest.
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 7}).json()
    gid = g["id"]
    # Hand the character some money via loan, then invest it.
    loans = client.get("/api/loans").json()
    personal = next(p for p in loans if p["name"] == "personal loan")
    r = client.post(f"/api/game/{gid}/loan", json={"product_id": personal["id"], "amount": 5000})
    assert r.status_code == 200
    g = r.json()
    assert g["character"]["money"] >= 5000
    assert g["character"]["debt"] == 5000
    assert len(g["character"]["loans"]) == 1

    invs = client.get("/api/investments").json()
    bonds = next(p for p in invs if "bonds" in p["name"])
    r = client.post(f"/api/game/{gid}/invest", json={"product_id": bonds["id"], "amount": 2000})
    assert r.status_code == 200
    g = r.json()
    assert g["portfolio_value"] == 2000
    assert len(g["character"]["investments"]) == 1
    assert g["character"]["money"] >= 3000  # 5000 - 2000 invested

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


def test_invest_validation_insufficient_funds(client):
    g = client.post("/api/game/new", json={"country_code": "us", "seed": 17}).json()
    gid = g["id"]
    invs = client.get("/api/investments").json()
    realestate = next(p for p in invs if "real estate" in p["name"])
    r = client.post(f"/api/game/{gid}/invest", json={"product_id": realestate["id"], "amount": 100000})
    assert r.status_code == 400
