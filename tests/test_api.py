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
