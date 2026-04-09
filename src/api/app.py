"""
FastAPI application: REST endpoints + static frontend serving.

Routes
------

  POST  /api/game/new                  -> create a new game (optional country code/seed)
  GET   /api/game/{id}                 -> fetch full game state
  POST  /api/game/{id}/advance         -> advance one year, return events
  POST  /api/game/{id}/decision        -> resolve a pending choice event
  GET   /api/games                     -> list saved games
  GET   /api/countries                 -> list all countries (basic stats)
  GET   /api/countries/{code}          -> single country detail
  GET   /flags/{code}.bmp              -> static flag asset (also under /static)
  GET   /                              -> serves the frontend SPA

The frontend lives at src/frontend/ as plain HTML/CSS/JS and is mounted as
static files. There is no build step.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..engine import finances
from ..engine.game import Game, list_games, load_game
from ..engine.world import all_countries, get_country


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "src" / "frontend"
FLAGS_DIR = DATA_DIR / "flags"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class NewGameRequest(BaseModel):
    country_code: Optional[str] = Field(default=None, description="ISO alpha-2 country code; random if omitted")
    seed: Optional[int] = Field(default=None, description="RNG seed for reproducible runs")


class DecisionRequest(BaseModel):
    choice_key: str


class InvestRequest(BaseModel):
    product_id: int
    amount: int


class LoanRequest(BaseModel):
    product_id: int
    amount: int


class SellInvestmentRequest(BaseModel):
    index: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_game(game: Game) -> dict:
    state = game.state
    country = get_country(state.character.country_code)
    return {
        "id": state.id,
        "year": state.year,
        "started_at": state.started_at,
        "character": state.character.to_dict(),
        "country": _country_dict(country) if country else None,
        "pending_event": state.pending_event,
        "portfolio_value": finances.portfolio_value(state.character),
    }


def _country_dict(c) -> dict:
    return {
        "code": c.code,
        "name": c.name,
        "region": c.region,
        "population": c.population,
        "gdp_pc": c.gdp_pc,
        "life_expectancy": c.life_expectancy,
        "infant_mortality": c.infant_mortality,
        "literacy": c.literacy,
        "gini": c.gini,
        "hdi": c.hdi,
        "urban_pct": c.urban_pct,
        "primary_religion": c.primary_religion,
        "primary_language": c.primary_language,
        "capital": c.capital,
        "currency": c.currency,
        "war_freq": c.war_freq,
        "disaster_freq": c.disaster_freq,
        "crime_rate": c.crime_rate,
        "corruption": c.corruption,
        "safe_water_pct": c.safe_water_pct,
        "health_services_pct": c.health_services_pct,
        "flag_url": f"/flags/{c.code}.bmp",
    }


def _turn_dict(result) -> dict:
    return {
        "year": result.year_advanced_to,
        "age": result.age,
        "events": [
            {
                "key": e.key,
                "title": e.title,
                "category": e.category,
                "summary": e.summary,
                "money_delta": e.money_delta,
                "deltas": e.deltas,
            }
            for e in result.events
        ],
        "pending_decision": result.pending_decision,
        "died": result.died,
        "cause_of_death": result.cause_of_death,
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Real Lives 2007 (Python)",
        description="A clean-room rebuild of Real Lives 2007 as a web app.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- API routes ----
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/countries")
    def countries():
        return [_country_dict(c) for c in all_countries()]

    @app.get("/api/countries/{code}")
    def country_detail(code: str):
        c = get_country(code)
        if c is None:
            raise HTTPException(status_code=404, detail="country not found")
        return _country_dict(c)

    @app.get("/api/games")
    def games():
        return list_games()

    @app.post("/api/game/new")
    def new_game(req: NewGameRequest):
        game = Game.new(country_code=req.country_code, seed=req.seed)
        game.save()
        return _serialize_game(game)

    @app.get("/api/game/{game_id}")
    def get_game(game_id: str):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        return _serialize_game(game)

    @app.post("/api/game/{game_id}/advance")
    def advance_game(game_id: str):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        result = game.advance_year()
        game.save()
        return {
            "turn": _turn_dict(result),
            "game": _serialize_game(game),
        }

    @app.get("/api/investments")
    def list_investment_products():
        return [
            {
                "id": p.id,
                "name": p.name,
                "annual_return_low": p.annual_return_low,
                "annual_return_high": p.annual_return_high,
                "risk": p.risk,
                "min_amount": p.min_amount,
            }
            for p in finances.list_investments()
        ]

    @app.get("/api/loans")
    def list_loan_products():
        return [
            {
                "id": p.id,
                "name": p.name,
                "max_amount": p.max_amount,
                "interest_rate": p.interest_rate,
                "max_years": p.max_years,
            }
            for p in finances.list_loans()
        ]

    @app.post("/api/game/{game_id}/invest")
    def invest(game_id: str, req: InvestRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        product = finances.get_investment_product(req.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="investment product not found")
        try:
            finances.buy_investment(game.state.character, product, req.amount, game.state.year)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    @app.post("/api/game/{game_id}/loan")
    def loan(game_id: str, req: LoanRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        product = finances.get_loan_product(req.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="loan product not found")
        try:
            finances.take_loan(game.state.character, product, req.amount, game.state.year)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    @app.post("/api/game/{game_id}/sell_investment")
    def sell_investment(game_id: str, req: SellInvestmentRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            finances.sell_investment(game.state.character, req.index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    @app.post("/api/game/{game_id}/decision")
    def decide(game_id: str, req: DecisionRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            result = game.apply_decision(req.choice_key)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return {
            "turn": _turn_dict(result),
            "game": _serialize_game(game),
        }

    # ---- Static assets ----
    if FLAGS_DIR.exists():
        app.mount("/flags", StaticFiles(directory=str(FLAGS_DIR)), name="flags")
    if FRONTEND_DIR.exists():
        # Mount frontend at /static so we can keep / as the SPA index.
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

        @app.get("/")
        def index():
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
