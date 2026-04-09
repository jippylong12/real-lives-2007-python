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

from ..engine import careers, finances, healthcare, spending
from ..engine.game import Game, NUM_SLOTS, list_games, list_slots, load_game
from ..engine.world import (
    all_countries, binary_facts_for, cities_for, description_for, get_country,
)
from .. import runtime_paths


DATA_DIR = runtime_paths.data_dir()
FRONTEND_DIR = runtime_paths.frontend_dir()
FLAGS_DIR = DATA_DIR / "flags"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class NewGameRequest(BaseModel):
    country_code: Optional[str] = Field(default=None, description="ISO alpha-2 country code; random if omitted")
    seed: Optional[int] = Field(default=None, description="RNG seed for reproducible runs")
    slot: Optional[int] = Field(default=None, description="Save slot 1-5 (#79); omit for unslotted save")


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


class PayLoanRequest(BaseModel):
    index: int
    amount: int


class ApplyJobRequest(BaseModel):
    job_name: str


class BuyRequest(BaseModel):
    purchase_key: str


class CancelSubscriptionRequest(BaseModel):
    key: str


class TreatDiseaseRequest(BaseModel):
    disease_key: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_game(game: Game) -> dict:
    state = game.state
    country = get_country(state.character.country_code)
    country_dict = None
    if country:
        country_dict = _country_dict(country)
        country_dict["binary_facts"] = _binary_facts_summary(country.code)

    char_dict = state.character.to_dict()
    # Surface the work-eligibility gate (#57) so the frontend can hide
    # the 'Find work' button without making a separate API call.
    if country is not None:
        can_work, blocked_reason = careers.can_character_work(state.character, country)
        char_dict["can_work"] = can_work
        char_dict["work_blocked_reason"] = blocked_reason
        # Also surface the drop-out gate (#69)
        can_drop, drop_reason = careers.can_drop_out_of_school(state.character, country)
        char_dict["can_drop_out"] = can_drop
        char_dict["drop_out_blocked_reason"] = drop_reason
    else:
        char_dict["can_work"] = False
        char_dict["work_blocked_reason"] = "no country"
        char_dict["can_drop_out"] = False
        char_dict["drop_out_blocked_reason"] = "no country"

    return {
        "id": state.id,
        "slot": state.slot,
        "year": state.year,
        "started_at": state.started_at,
        "character": char_dict,
        "country": country_dict,
        "pending_event": state.pending_event,
        "portfolio_value": finances.portfolio_value(state.character),
        "career": _career_summary(state.character),
    }


def _career_summary(character) -> dict | None:
    """Return the character's current career snapshot for the sidebar
    (#51): vocation field, current job's category, the next rung in the
    binary's promotion ladder (if any), and how close they are to it.
    Also includes the raise-request eligibility (#55)."""
    if not character.job:
        return None
    job = careers.get_job(character.job)
    if job is None:
        return None
    next_rung = careers.get_job(job.promotes_to) if job.promotes_to else None
    promo_count = character.promotion_count or 0
    years_required = careers._years_required_for_promo(character, job)
    can_raise, raise_reason = careers.can_request_salary_raise(character)
    can_promote, promote_reason = careers.can_request_promotion(character)
    # Surface the full list of gates the player is failing for the
    # next rung, plus its education requirement, so the career card
    # can show them up-front instead of forcing the player to click to
    # discover them.
    next_missing: list[str] = []
    next_min_education_label: str | None = None
    if next_rung is not None:
        next_missing = careers._missing_requirements(next_rung, character)
        edu_labels = ["none", "primary", "secondary", "vocational", "university"]
        if 0 <= next_rung.min_education < len(edu_labels):
            next_min_education_label = edu_labels[next_rung.min_education]
    return {
        "vocation_field": character.vocation_field,
        "category": job.category,
        "current_job": job.name,
        "years_in_role": character.years_in_role,
        "promotion_count": promo_count,
        "years_to_promote": years_required,
        "next_job": next_rung.name if next_rung else None,
        "next_min_age": next_rung.min_age if next_rung else None,
        "next_min_intelligence": next_rung.min_intelligence if next_rung else None,
        "next_min_education": next_rung.min_education if next_rung else None,
        "next_min_education_label": next_min_education_label,
        "next_missing_requirements": next_missing,
        # #63: split raise vs promotion
        "can_request_raise": can_raise,
        "raise_blocked_reason": raise_reason,
        "can_request_promotion": can_promote,
        "promotion_blocked_reason": promote_reason,
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
        "at_war": bool(c.at_war),
        "military_conscription": bool(c.military_conscription),
        "flag_url": f"/flags/{c.code}.bmp",
        "description": description_for(c.code),
    }


def _binary_facts_summary(code: str) -> dict | None:
    """Build a small structured fact sheet from country_binary_field for
    the country panel (#30). Returns the most useful binary-only fields:
    human-rights flags, disaster history totals, military service rules.
    Returns None if the country isn't in the binary."""
    facts = binary_facts_for(code)
    if not facts:
        return None
    human_rights = {
        k: facts[k]
        for k in (
            "Torture", "PoliticalPrisoners", "ExtrajudicialExecutions",
            "CruelPunishment", "Impunity", "UnfairTrials", "WomensRights",
            "ForcibleReturn", "Journalists", "HumanRightsDefenders",
            "PrisonConditions",
        )
        if k in facts
    }
    military = {
        k: facts[k]
        for k in (
            "MilitaryConscription", "AlternativeService", "MilitaryVolunteerAge",
            "MonthsService",
        )
        if k in facts
    }
    # Disaster fields come in triples: <Type>Events / <Type>Killed /
    # <Type>Affected. Killed and Affected are *average per recorded event*
    # (not cumulative totals), based on cross-checking China earthquakes
    # (30 killed per event, not the 250k+ Tangshan total) and Bangladesh
    # floods (20M affected per event, matching typical Bangladeshi flooding).
    # Group them into structured records for the frontend (#34).
    disasters = []
    for kind in ("Earthquake", "Flood", "Famine", "Fire", "Avalanche"):
        events_n = facts.get(f"{kind}Events")
        killed_n = facts.get(f"{kind}Killed")
        affected_n = facts.get(f"{kind}Affected")
        if not isinstance(events_n, (int, float)) or events_n <= 0:
            continue
        disasters.append({
            "kind": kind.lower(),
            "events": int(events_n),
            "killed_per_event": int(killed_n) if isinstance(killed_n, (int, float)) else None,
            "affected_per_event": int(affected_n) if isinstance(affected_n, (int, float)) else None,
        })
    return {
        "at_war": facts.get("AtWar", False),
        "human_rights": human_rights,
        "military_service": military,
        "disaster_history": disasters,
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
        d = _country_dict(c)
        d["cities"] = [
            {"name": city.name, "rank": city.rank, "is_capital": city.is_capital}
            for city in cities_for(c.code)
        ]
        d["binary_facts"] = _binary_facts_summary(c.code)
        return d

    @app.get("/api/countries/{code}/binary_facts")
    def country_binary_facts(code: str):
        """Full raw binary fact sheet (#30): every world.dat field for the
        country, name → value. Returns 404 for countries not in the binary."""
        c = get_country(code)
        if c is None:
            raise HTTPException(status_code=404, detail="country not found")
        facts = binary_facts_for(c.code)
        if not facts:
            raise HTTPException(status_code=404, detail="country not in binary")
        return facts

    @app.get("/api/games")
    def games():
        return list_games()

    @app.get("/api/slots")
    def slots():
        """Return the 5 save slots (#79). Each slot is one of:
        empty / alive / dead. Frontend renders this as the start screen."""
        rows = list_slots()
        # Backfill country_name from the world catalog so the frontend
        # doesn't need a second lookup per slot.
        for row in rows:
            cc = row.get("country_code")
            if cc:
                country = get_country(cc)
                if country is not None:
                    row["country_name"] = country.name
        return rows

    @app.post("/api/game/new")
    def new_game(req: NewGameRequest):
        if req.slot is not None and not (1 <= req.slot <= NUM_SLOTS):
            raise HTTPException(
                status_code=400,
                detail=f"slot must be between 1 and {NUM_SLOTS}",
            )
        game = Game.new(
            country_code=req.country_code,
            seed=req.seed,
            slot=req.slot,
        )
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
                "min_age": finances.investment_min_age(p.name),  # #68
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
                "min_age": finances.FAMILY_LOAN_MIN_AGE if p.name == "family loan" else finances.LOAN_MIN_AGE,  # #68
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

    @app.post("/api/game/{game_id}/quit_job")
    def quit_job(game_id: str):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            careers.quit_job(game.state.character)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    @app.post("/api/game/{game_id}/drop_out_of_school")
    def drop_out_of_school(game_id: str):
        """Leave school early to start working (#69). Only allowed
        when the character has reached the country's minimum working
        age."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        try:
            careers.drop_out_of_school(game.state.character, country)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    @app.get("/api/game/{game_id}/job_board")
    def job_board(game_id: str):
        """Return every job in the catalogue annotated with the
        character's eligibility, predicted acceptance probability, and
        PPP-scaled expected salary (#54)."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        listings = careers.job_listing(game.state.character, country)
        return [
            {
                "name": l.job.name,
                "category": l.job.category,
                "salary_low": int(l.expected_salary * 0.85),
                "salary_high": int(l.expected_salary * 1.15),
                "expected_salary": l.expected_salary,
                "min_age": l.job.min_age,
                "max_age": l.job.max_age,
                "min_education": l.job.min_education,
                "min_intelligence": l.job.min_intelligence,
                "urban_only": l.job.urban_only,
                "rural_only": l.job.rural_only,
                "is_freelance": l.job.is_freelance,
                "status": l.status,
                "accept_chance": round(l.accept_chance, 3),
                "missing": l.missing,
                "promotes_to": l.job.promotes_to,
            }
            for l in listings
        ]

    @app.post("/api/game/{game_id}/request_raise")
    def request_raise(game_id: str):
        """Player-initiated salary raise request (#55, #63). Outcomes:
        raise / denied / fired / cooldown / not_eligible. Available
        even at the top of the ladder — separate from promotion."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = careers.request_salary_raise(
            game.state.character, country, game.rng
        )
        game.save()
        return {
            "outcome": result.outcome,
            "message": result.message,
            "salary_delta": result.salary_delta,
            "new_job": result.new_job,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/request_promotion")
    def request_promotion(game_id: str):
        """Player-initiated promotion request (#63). Outcomes:
        promotion / denied / fired / not_eligible. Only valid when
        there's a next rung in the ladder AND the character meets
        its requirements."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = careers.request_promotion(
            game.state.character, country, game.rng
        )
        game.save()
        return {
            "outcome": result.outcome,
            "message": result.message,
            "salary_delta": result.salary_delta,
            "new_job": result.new_job,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/apply_job")
    def apply_job(game_id: str, req: ApplyJobRequest):
        """Roll for acceptance to the named job. On success, the
        character switches roles. On failure, no state change."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = careers.apply_for_job(
            game.state.character, country, req.job_name, game.rng
        )
        game.save()
        return {
            "accepted": result.accepted,
            "message": result.message,
            "new_job": result.new_job,
            "new_salary": result.new_salary,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/pay_loan")
    def pay_loan(game_id: str, req: PayLoanRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        try:
            finances.pay_loan(game.state.character, req.index, req.amount)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        game.save()
        return _serialize_game(game)

    # ---------- Discretionary spending (#66) ----------
    @app.get("/api/game/{game_id}/purchases")
    def list_purchases(game_id: str):
        """List every purchase in the spending registry annotated with
        the character's eligibility, country-scaled price, and ownership
        / subscription state."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        return spending.list_purchases(game.state.character, country)

    @app.post("/api/game/{game_id}/buy")
    def buy(game_id: str, req: BuyRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = spending.buy(
            game.state.character, country, req.purchase_key, game.state.year
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        game.save()
        return {
            "success": True,
            "message": result.message,
            "cost": result.cost,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/cancel_subscription")
    def cancel_subscription(game_id: str, req: CancelSubscriptionRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        result = spending.cancel_subscription(game.state.character, req.key)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        game.save()
        return {
            "success": True,
            "message": result.message,
            "game": _serialize_game(game),
        }

    # ---------- Pay-for-healthcare (#67) ----------
    @app.get("/api/game/{game_id}/healthcare")
    def healthcare_options(game_id: str):
        """List available medical actions: checkup, major treatment,
        per-disease cures. Each entry includes scaled cost + eligibility."""
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        char = game.state.character
        country = get_country(char.country_code)
        scale = max(0.05, country.gdp_pc / 50000)

        checkup_eligible, checkup_reason = healthcare.can_buy_checkup(char)
        major_eligible, major_reason = healthcare.can_buy_major_treatment(char)

        treatable = []
        for d in healthcare.treatable_diseases(char):
            treatable.append({
                "disease_key": d.key,
                "name": d.name,
                "permanent": d.permanent,
                "cost": max(100, int(d.treatment_cost * scale)),
            })

        return {
            "checkup": {
                "cost": max(50, int(2_000 * scale)),
                "eligible": checkup_eligible,
                "reason": checkup_reason,
            },
            "major": {
                "cost": max(500, int(15_000 * scale)),
                "eligible": major_eligible,
                "reason": major_reason,
            },
            "diseases": treatable,
        }

    @app.post("/api/game/{game_id}/buy_checkup")
    def buy_checkup(game_id: str):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = healthcare.buy_checkup(game.state.character, country)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        game.save()
        return {
            "success": True,
            "message": result.message,
            "cost": result.cost,
            "health_delta": result.health_delta,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/buy_major_treatment")
    def buy_major_treatment(game_id: str):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = healthcare.buy_major_treatment(game.state.character, country)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        game.save()
        return {
            "success": True,
            "message": result.message,
            "cost": result.cost,
            "health_delta": result.health_delta,
            "game": _serialize_game(game),
        }

    @app.post("/api/game/{game_id}/treat_disease")
    def treat_disease(game_id: str, req: TreatDiseaseRequest):
        game = load_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        country = get_country(game.state.character.country_code)
        result = healthcare.treat_disease(
            game.state.character, country, req.disease_key
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        game.save()
        return {
            "success": True,
            "message": result.message,
            "cost": result.cost,
            "game": _serialize_game(game),
        }

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
