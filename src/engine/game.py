"""
Game session: yearly turn loop, save / load, decision handling.

Turn order (mirrors the original game's `events_life_major_handler` flow):

  1. Increment age
  2. Update education (school entry, graduation)
  3. Try to assign a job if eligible
  4. Process yearly income / expenses / debt interest
  5. Update relationships (marriage, partners)
  6. Roll random life events
     - Passive events apply immediately and append to the year's log
     - The first CHOICE event halts the year and waits for the player
  7. Death roll
  8. End-of-year stat clamp + recovery drift

`advance_year()` returns a TurnResult that the API serializes for the frontend.
"""

from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from . import careers, death, diseases, education, events, finances, relationships
from .character import Character, EducationLevel, create_random_character
from .world import Country, all_countries, get_country, random_country
from ..data.build_db import get_connection


@dataclass
class TurnEvent:
    key: str
    title: str
    category: str
    summary: str
    money_delta: int = 0
    deltas: dict[str, int] = field(default_factory=dict)


@dataclass
class TurnResult:
    year_advanced_to: int
    age: int
    events: list[TurnEvent]
    pending_decision: Optional[dict]
    died: bool
    cause_of_death: Optional[str]


@dataclass
class GameState:
    id: str
    seed: int
    rng_state: list  # for reproducibility
    character: Character
    year: int                              # in-game calendar year
    started_at: str                        # ISO timestamp
    pending_event: Optional[dict] = None   # full event awaiting decision
    slot: Optional[int] = None             # save slot 1-5 (#79)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "seed": self.seed,
            "rng_state": self.rng_state,
            "character": self.character.to_dict(),
            "year": self.year,
            "started_at": self.started_at,
            "pending_event": self.pending_event,
            "slot": self.slot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        return cls(
            id=d["id"],
            seed=d["seed"],
            rng_state=d["rng_state"],
            character=Character.from_dict(d["character"]),
            year=d["year"],
            started_at=d["started_at"],
            pending_event=d.get("pending_event"),
            slot=d.get("slot"),
        )


# ---------------------------------------------------------------------------
# Game lifecycle
# ---------------------------------------------------------------------------

class Game:
    def __init__(self, state: GameState):
        self.state = state
        self.rng = random.Random()
        self.rng.setstate(tuple_state(state.rng_state))

    # ----- creation -----
    @classmethod
    def new(
        cls,
        *,
        country_code: str | None = None,
        seed: int | None = None,
        slot: int | None = None,
    ) -> "Game":
        seed = seed if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
        rng = random.Random(seed)
        country = get_country(country_code) if country_code else None
        if country is None:
            country = random_country(rng)
        character = create_random_character(country, rng)
        state = GameState(
            id=uuid.uuid4().hex[:12],
            seed=seed,
            rng_state=list_state(rng.getstate()),
            character=character,
            year=2007,                # original game's release year as the in-game start
            started_at=datetime.now(timezone.utc).isoformat(),
            slot=slot,
        )
        character.remember(f"Born in {country.capital}, {country.name}.")
        return cls(state)

    # ----- save / load -----
    def save(self) -> None:
        save_game(self)

    @classmethod
    def load(cls, game_id: str) -> "Game | None":
        return load_game(game_id)

    # ----- helpers -----
    def country(self) -> Country:
        c = get_country(self.state.character.country_code)
        if c is None:
            raise RuntimeError(f"Unknown country {self.state.character.country_code!r}")
        return c

    def _checkpoint_rng(self) -> None:
        self.state.rng_state = list_state(self.rng.getstate())

    # ----- core turn -----
    def advance_year(self) -> TurnResult:
        """Run one full year of simulation (or stop early at a pending decision)."""
        char = self.state.character
        if not char.alive:
            return TurnResult(self.state.year, char.age, [], None, True, char.cause_of_death)
        if self.state.pending_event is not None:
            # Player must resolve decision first.
            return TurnResult(
                self.state.year, char.age, [], self.state.pending_event,
                False, None,
            )

        country = self.country()
        char.age += 1
        self.state.year += 1
        log: list[TurnEvent] = []

        # 1. Education changes
        ed_msg = education.update_education(char, country, self.rng)
        if ed_msg:
            log.append(TurnEvent("education", "Education", "education", ed_msg))
            char.remember(ed_msg)

        # 2. Promotion check + auto-retirement (#51, #75).
        # Tick years_in_role first so the promotion check sees the
        # accumulated experience for the year that just finished.
        # NOTE: jobless characters are NEVER auto-assigned a new job —
        # joblessness is a deliberate state. Players who graduate, quit,
        # retire, or get aged out of their career stay jobless until
        # they explicitly use Find work / job board to re-enter the
        # workforce. The Find work flow already handles intentional
        # entry into employment.
        if char.job is not None:
            char.years_in_role += 1
            # Forced retirement when the character ages past their job's
            # max_age. Athletes retire at 38-40, soldiers at 55, doctors
            # at 80, etc. promotion_count is preserved (you earned those
            # promotions); years_in_role resets so a re-entered career
            # starts fresh.
            current_job = careers.get_job(char.job)
            if current_job is not None and char.age > current_job.max_age:
                log.append(TurnEvent(
                    "retired", "Retired", "finance",
                    f"You aged out of your role as a {current_job.name}.",
                ))
                char.remember(f"Retired from being a {current_job.name}.")
                char.job = None
                char.salary = 0
                char.years_in_role = 0

        promo_msg = careers.promote(char, country, self.rng)
        if promo_msg:
            log.append(TurnEvent("promotion", "Promotion", "finance", promo_msg))
            char.remember(promo_msg)

        # 3. Income / expenses
        net = careers.yearly_income(char, country, self.rng)
        if net != 0:
            log.append(TurnEvent("income", "Income & expenses", "finance",
                                 f"Net change to savings this year: ${net:,}.",
                                 money_delta=net))
        # 3b. Subscription effect log entries (#77). The careers tick
        # stashes per-subscription records on the character; surface
        # them as event log lines so the player sees what their
        # gym / therapy / premium healthcare plan is actually doing.
        sub_records = getattr(char, "_pending_subscription_log", None)
        if sub_records:
            for rec in sub_records:
                log.append(TurnEvent(
                    f"sub_{rec['key']}", rec["name"], "life",
                    rec["summary"],
                    deltas=rec.get("deltas", {}),
                ))
            try:
                del char._pending_subscription_log
            except AttributeError:
                pass

        # 4. Loans + investments yearly tick
        tick = finances.tick_finances(char, self.rng)
        if tick.investment_pl:
            sign = "gained" if tick.investment_pl >= 0 else "lost"
            log.append(TurnEvent(
                "investment_return", "Investments", "finance",
                f"Your portfolio {sign} ${abs(tick.investment_pl):,} this year.",
                money_delta=0,
            ))
        if tick.loan_payments:
            log.append(TurnEvent(
                "loan_payment", "Loan payments", "finance",
                f"Paid ${tick.loan_payments:,} on loans (${tick.loan_interest:,} of it interest).",
                money_delta=-tick.loan_payments,
            ))
        for closed in tick.closed_loans:
            log.append(TurnEvent("loan_closed", "Loan paid off", "finance",
                                 f"You paid off your {closed}."))
        for closed in tick.closed_investments:
            log.append(TurnEvent("investment_lost", "Investment wiped out", "finance",
                                 f"Your {closed} position is now worthless."))

        # 5. Financial stress
        stress = finances.financial_stress(char, country)
        if stress:
            char.attributes.adjust(happiness=stress)
            log.append(TurnEvent("stress", "Financial stress", "finance",
                                 "Money worries weighed on you this year.",
                                 deltas={"happiness": stress}))

        # 6. Relationships
        rel_msg = relationships.update_relationships(char, country, self.rng)
        if rel_msg:
            log.append(TurnEvent("relationship", "Relationship", "life", rel_msg))
            char.remember(rel_msg)
        relationships.age_family(char)

        # 7. Random life events
        for ev in events.roll_events(char, country, self.rng):
            if ev.choices:
                # Pause for player choice — serialize the event into pending.
                self.state.pending_event = {
                    "key": ev.key,
                    "title": ev.title,
                    "category": ev.category,
                    "description": ev.description,
                    "choices": [
                        {"key": ch.key, "label": ch.label} for ch in ev.choices
                    ],
                }
                self._checkpoint_rng()
                return TurnResult(
                    self.state.year, char.age, log, self.state.pending_event,
                    False, None,
                )
            result = ev.apply(char, country, self.rng)
            # apply() can return either a single EventOutcome or a list of
            # them (#36 — multi-disease years split each diagnosis into its
            # own log line).
            outcomes = result if isinstance(result, list) else [result]
            for outcome in outcomes:
                if not outcome.summary:
                    continue
                if outcome.deltas:
                    char.attributes.adjust(**outcome.deltas)
                if outcome.money_delta:
                    char.money += outcome.money_delta
                for k, v in outcome.moral_delta.items():
                    char.moral_ledger[k] = char.moral_ledger.get(k, 0) + v
                log.append(TurnEvent(
                    ev.key, ev.title, ev.category, outcome.summary,
                    money_delta=outcome.money_delta,
                    deltas=outcome.deltas,
                ))
                char.remember(outcome.summary)

        # 8. Chronic disease wear: each active permanent condition costs a
        # bit of health every year on top of any acute event that fired.
        chronic_loss, chronic_lines = diseases.chronic_progression(char, country, self.rng)
        if chronic_loss:
            char.attributes.adjust(health=-chronic_loss)
            for line in chronic_lines:
                log.append(TurnEvent("chronic_disease", "Chronic illness", "health",
                                     line, deltas={"health": -chronic_loss}))

        # 9. Slight happiness and health drift toward baseline. Without the
        # health drift, every acute disease / minor injury hit accumulates
        # forever and characters die of cumulative attrition long before
        # old age (#24). Drift is stronger in countries with good
        # healthcare since recovery from injuries / acute illness is
        # faster, and stronger still when the character is severely
        # impaired (the body fights to recover from low-health states
        # — without this kick, low-HDI characters get stuck on the
        # quadratic mortality ramp, #32).
        if char.attributes.happiness < 60:
            char.attributes.adjust(happiness=+1)
        elif char.attributes.happiness > 80:
            char.attributes.adjust(happiness=-1)
        # Health regen target falls with age, regen rate declines too,
        # but never goes to zero — even in old age the body recovers some
        # of the previous year's hits if healthcare is available.
        heal_target = 60 + int(country.health_services_pct / 5)
        if char.age >= 70:
            heal_target = max(35, heal_target - (char.age - 70))
        if char.attributes.health < heal_target:
            if char.age < 70:
                regen = 3 if country.health_services_pct >= 80 else 2
            else:
                # Slow decline past 70: 2/yr in good healthcare, 1/yr otherwise.
                regen = 2 if country.health_services_pct >= 80 else 1
            if char.attributes.health < 25:
                regen += 3  # convalescent boost — body fights to recover
            # Premium healthcare subscription doubles regen (#67).
            if "sub_premium_health" in (char.subscriptions or {}):
                regen *= 2
            char.attributes.adjust(health=+regen)

        # 10. Death roll — first from active high-lethality diseases, then
        # from the generic age/health curve.
        disease_cause = diseases.disease_kill_check(char, country, self.rng)
        if disease_cause:
            char.alive = False
            char.cause_of_death = disease_cause
            char.remember(f"Died of {disease_cause}.")
            log.append(TurnEvent("death", "Death", "life",
                                 f"You died at age {char.age}. Cause: {disease_cause}."))
            self._checkpoint_rng()
            return TurnResult(self.state.year, char.age, log,
                              self.state.pending_event, True, disease_cause)
        died, cause = death.kill_check(char, country, self.rng)
        if died:
            char.alive = False
            char.cause_of_death = cause
            char.remember(f"Died of {cause}.")
            log.append(TurnEvent("death", "Death", "life",
                                 f"You died at age {char.age}. Cause: {cause}."))
        char.attributes.clamp()
        self._checkpoint_rng()
        return TurnResult(self.state.year, char.age, log,
                          self.state.pending_event, died, cause)

    # ----- decisions -----
    def apply_decision(self, choice_key: str) -> TurnResult:
        """Resolve a pending CHOICE event with the player's selection."""
        if self.state.pending_event is None:
            raise ValueError("No pending decision")
        char = self.state.character
        country = self.country()
        ev_key = self.state.pending_event["key"]
        ev = next((e for e in events.EVENT_REGISTRY if e.key == ev_key), None)
        if ev is None or ev.choices is None:
            raise RuntimeError(f"Unknown choice event {ev_key!r}")
        choice = next((c for c in ev.choices if c.key == choice_key), None)
        if choice is None:
            raise ValueError(f"Invalid choice {choice_key!r} for {ev_key!r}")

        char.attributes.adjust(**choice.deltas)
        if choice.money_delta:
            char.money += choice.money_delta
        for k, v in choice.moral_delta.items():
            char.moral_ledger[k] = char.moral_ledger.get(k, 0) + v
        if choice.side_effect is not None:
            choice.side_effect(char)
        line = f"{ev.title}: {choice.summary}"
        char.remember(line)

        log = [TurnEvent(
            ev.key, ev.title, ev.category, choice.summary,
            money_delta=choice.money_delta, deltas=choice.deltas,
        )]
        self.state.pending_event = None
        self._checkpoint_rng()
        return TurnResult(
            self.state.year, char.age, log, None,
            died=not char.alive, cause_of_death=char.cause_of_death,
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_game(game: Game) -> None:
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        state_json = json.dumps(game.state.to_dict())
        conn.execute(
            """
            INSERT INTO games (id, created_at, updated_at, state_json, slot)
            VALUES (?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at,
                                          state_json = excluded.state_json,
                                          slot       = excluded.slot
            """,
            (game.state.id, now, now, state_json, game.state.slot),
        )
        conn.commit()
    finally:
        conn.close()


def load_game(game_id: str) -> Game | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT state_json FROM games WHERE id = ?", (game_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    state = GameState.from_dict(json.loads(row["state_json"]))
    return Game(state)


def list_games() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, state_json FROM games ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        s = json.loads(r["state_json"])
        out.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "character_name": s["character"]["name"],
            "country_code": s["character"]["country_code"],
            "age": s["character"]["age"],
            "alive": s["character"]["alive"],
        })
    return out


# Number of save slots the player picks from on the start screen (#79).
NUM_SLOTS = 5


def list_slots() -> list[dict]:
    """Return one descriptor per save slot (1..NUM_SLOTS).

    For each slot, the "current" game is the most recently updated row
    with that slot number. Slots with no rows return state="empty".
    Otherwise the slot reports the character's name / country / age and
    whether they're still alive."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT g.id, g.slot, g.created_at, g.updated_at, g.state_json
            FROM games g
            JOIN (
                SELECT slot, MAX(updated_at) AS m
                FROM games
                WHERE slot IS NOT NULL
                GROUP BY slot
            ) latest ON latest.slot = g.slot AND latest.m = g.updated_at
            ORDER BY g.slot
            """
        ).fetchall()
    finally:
        conn.close()
    by_slot: dict[int, dict] = {}
    for r in rows:
        s = json.loads(r["state_json"])
        c = s["character"]
        by_slot[int(r["slot"])] = {
            "slot": int(r["slot"]),
            "state": "alive" if c.get("alive", True) else "dead",
            "game_id": r["id"],
            "character_name": c["name"],
            "country_code": c["country_code"],
            "country_name": None,  # filled in by API layer if needed
            "age": c["age"],
            "year": s.get("year"),
            "alive": bool(c.get("alive", True)),
            "cause_of_death": c.get("cause_of_death"),
            "updated_at": r["updated_at"],
        }
    out: list[dict] = []
    for n in range(1, NUM_SLOTS + 1):
        if n in by_slot:
            out.append(by_slot[n])
        else:
            out.append({
                "slot": n,
                "state": "empty",
                "game_id": None,
                "character_name": None,
                "country_code": None,
                "country_name": None,
                "age": None,
                "year": None,
                "alive": False,
                "cause_of_death": None,
                "updated_at": None,
            })
    return out


# ---------------------------------------------------------------------------
# random.Random state helpers — JSON-safe.
# ---------------------------------------------------------------------------

def list_state(state: tuple) -> list:
    """Convert random.getstate() into a JSON-friendly nested list."""
    version, internal, gauss = state
    return [version, list(internal), gauss]


def tuple_state(state: list) -> tuple:
    """Inverse of list_state."""
    version, internal, gauss = state
    return (version, tuple(internal), gauss)
