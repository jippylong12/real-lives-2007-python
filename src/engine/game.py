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

from . import careers, death, diseases, education, events, finances, relationships, statistics
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
    # #90: list of achievement keys newly unlocked by this turn (only
    # populated when the character died and the archive write evaluated
    # the registry). Frontend uses this to fire unlock toasts.
    unlocked_achievements: list = field(default_factory=list)


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
    # #85: per-player scoping. NULL means "unscoped" (the legacy
    # default that anonymous players still see). When set, save slots
    # and statistics filter to lives created by this player.
    player_name: Optional[str] = None

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
            "player_name": self.player_name,
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
            player_name=d.get("player_name"),
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
        player_name: str | None = None,
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
            player_name=player_name or None,
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
        # #96: tick relationship strain. Low-compat marriages accumulate
        # strain faster; once it crosses the threshold the
        # DIVORCE_CONSIDERATION choice event becomes eligible.
        relationships.update_strain(char)
        # #50: age_family now accepts country + rng so it can run the
        # spouse death roll. Notes are spouse-death markers we fan out
        # into TurnEvents below.
        notes = relationships.age_family(char, country, self.rng)
        for note in notes:
            if note.startswith("spouse_died:"):
                _, name, cause = note.split(":", 2)
                msg = f"{name} died of {cause}. The house feels different."
                log.append(TurnEvent(
                    "spouse_died", "Your spouse died", "life", msg,
                    deltas={"happiness": -15, "wisdom": +3},
                ))
                char.attributes.adjust(happiness=-15, wisdom=+3)
                char.remember(f"Your spouse {name} died of {cause}.")

        # #50: divorce check. Yearly chance scaled by compatibility +
        # country divorce_rate (#92, falls back to HDI when unset).
        # Silent automatic for v1; CHOICE-event variant is filed as #96.
        if relationships.divorce_check(char, country, self.rng):
            former = char.spouse
            split = max(0, char.family_wealth // 2)
            char.family_wealth -= split
            # #95: archive the former spouse with end metadata so the
            # death retrospective can render the full marriage history.
            if former is not None:
                former.ended_year = char.age
                former.end_state = "divorced"
                char.previous_spouses.append(former)
            char.spouse = None
            # Mirror to the family list — the spouse FamilyMember
            # entry should reflect the breakup.
            char.family = [fm for fm in char.family
                           if not (fm.relation == "spouse" and fm.name == (former.name if former else None))]
            log.append(TurnEvent(
                "divorce", "Divorce", "life",
                f"You and {former.name if former else 'your spouse'} divorced. "
                f"Your family wealth was split.",
                deltas={"happiness": -10, "wisdom": +2},
            ))
            char.attributes.adjust(happiness=-10, wisdom=+2)
            char.remember(f"Divorced {former.name if former else 'your spouse'}.")

        # 7. Random life events
        for ev in events.roll_events(char, country, self.rng):
            if ev.choices:
                # Pause for player choice — serialize the event into pending.
                # NOTE: cooldown/lifetime recording for choice events happens
                # in apply_decision once the player resolves it (#52).
                pending: dict = {
                    "key": ev.key,
                    "title": ev.title,
                    "category": ev.category,
                    "description": ev.description,
                    "choices": [
                        {"key": ch.key, "label": ch.label} for ch in ev.choices
                    ],
                }
                # #91: events with a dynamic_payload (e.g., MEET_CANDIDATES
                # rolling N candidate spouses) merge extra fields into
                # pending_event so the frontend can render a custom
                # picker UI.
                if ev.dynamic_payload is not None:
                    extra = ev.dynamic_payload(char, country, self.rng)
                    if extra:
                        pending.update(extra)
                self.state.pending_event = pending
                self._checkpoint_rng()
                return TurnResult(
                    self.state.year, char.age, log, self.state.pending_event,
                    False, None,
                )
            # #52: record passive event firings so cooldowns + lifetime
            # caps work. Done before apply so a side-effect that
            # advances the character's age (rare) still records under
            # the correct year.
            events.record_event_fired(char, ev.key)
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

        # 10. Cross-life statistics tracking (#70). Update peak net
        # worth and peak attributes once per year. Done before the
        # death roll so a character who dies this year still has
        # their final-year peaks recorded.
        portfolio = finances.portfolio_value(char)
        net_worth_now = char.money + portfolio - char.debt
        if net_worth_now > char.peak_net_worth:
            char.peak_net_worth = net_worth_now
        for _attr in ("intelligence", "artistic", "musical", "athletic",
                      "strength", "endurance", "appearance", "conscience",
                      "wisdom", "resistance"):
            _val = getattr(char.attributes, _attr, 0)
            if _val > char.peak_attributes.get(_attr, 0):
                char.peak_attributes[_attr] = _val

        # 11. Death roll — first from active high-lethality diseases, then
        # from the generic age/health curve.
        disease_cause = diseases.disease_kill_check(char, country, self.rng)
        if disease_cause:
            char.alive = False
            char.cause_of_death = disease_cause
            char.remember(f"Died of {disease_cause}.")
            log.append(TurnEvent("death", "Death", "life",
                                 f"You died at age {char.age}. Cause: {disease_cause}."))
            unlocked = statistics.write_archive_row(self.state) or []
            self._checkpoint_rng()
            return TurnResult(self.state.year, char.age, log,
                              self.state.pending_event, True, disease_cause,
                              unlocked_achievements=unlocked)
        died, cause = death.kill_check(char, country, self.rng)
        unlocked: list = []
        if died:
            char.alive = False
            char.cause_of_death = cause
            char.remember(f"Died of {cause}.")
            log.append(TurnEvent("death", "Death", "life",
                                 f"You died at age {char.age}. Cause: {cause}."))
            unlocked = statistics.write_archive_row(self.state) or []
        char.attributes.clamp()
        self._checkpoint_rng()
        return TurnResult(self.state.year, char.age, log,
                          self.state.pending_event, died, cause,
                          unlocked_achievements=unlocked)

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
            # #50: side effects that need year/country/rng (e.g.,
            # _accept_proposal, which rolls a full Spouse) accept an
            # optional ctx kwarg. Existing side effects ignore it via
            # the try/except below.
            # #91: ctx now also exposes the pending_event payload + the
            # chosen choice_key so dynamic-payload events (the swipe
            # picker) can read the candidate the player picked.
            ctx = {
                "year": self.state.year,
                "country": country,
                "rng": self.rng,
                "pending_event": dict(self.state.pending_event),
                "choice_key": choice_key,
            }
            try:
                choice.side_effect(char, ctx)
            except TypeError:
                choice.side_effect(char)
        # #52: record the choice event firing for cooldown / lifetime
        # tracking. Done after the side_effect since some side effects
        # mutate state we want reflected in the recorded age.
        events.record_event_fired(char, ev.key)
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
            INSERT INTO games (id, created_at, updated_at, state_json, slot, player_name)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET updated_at  = excluded.updated_at,
                                          state_json  = excluded.state_json,
                                          slot        = excluded.slot,
                                          player_name = excluded.player_name
            """,
            (game.state.id, now, now, state_json, game.state.slot, game.state.player_name),
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


def list_games(player_name: str | None = None) -> list[dict]:
    """List saved games. When ``player_name`` is provided, only games
    stamped with that player are returned (#85). Pass None for the
    legacy unscoped behavior — returns everything regardless of player.
    """
    conn = get_connection()
    try:
        if player_name is None:
            rows = conn.execute(
                "SELECT id, created_at, updated_at, state_json, player_name "
                "FROM games ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, created_at, updated_at, state_json, player_name "
                "FROM games "
                "WHERE player_name IS ? OR player_name = ? "
                "ORDER BY updated_at DESC",
                (None, player_name),  # also surface unscoped legacy rows
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
            "player_name": r["player_name"],
        })
    return out


# Number of save slots the player picks from on the start screen (#79).
NUM_SLOTS = 5


def list_slots(player_name: str | None = None) -> list[dict]:
    """Return one descriptor per save slot (1..NUM_SLOTS).

    For each slot, the "current" game is the most recently updated row
    with that slot number. Slots with no rows return state="empty".
    Otherwise the slot reports the character's name / country / age and
    whether they're still alive.

    #85: when ``player_name`` is set, the slot lookup is scoped to
    games tagged with that player (and unscoped legacy rows). Pass
    None for the legacy global view that surfaces every player's
    slots indiscriminately.
    """
    conn = get_connection()
    try:
        if player_name is None:
            rows = conn.execute(
                """
                SELECT g.id, g.slot, g.created_at, g.updated_at, g.state_json,
                       g.player_name
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
        else:
            rows = conn.execute(
                """
                SELECT g.id, g.slot, g.created_at, g.updated_at, g.state_json,
                       g.player_name
                FROM games g
                JOIN (
                    SELECT slot, MAX(updated_at) AS m
                    FROM games
                    WHERE slot IS NOT NULL
                      AND (player_name IS NULL OR player_name = ?)
                    GROUP BY slot
                ) latest ON latest.slot = g.slot AND latest.m = g.updated_at
                WHERE g.player_name IS NULL OR g.player_name = ?
                ORDER BY g.slot
                """,
                (player_name, player_name),
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
