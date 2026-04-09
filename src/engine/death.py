"""
Death probability calculations.

The original game (events/life/events_life_major_handler) computes mortality
in three buckets:

  1. Infant mortality (age < 1)  — flat probability from country.infant_mortality
  2. Background mortality        — small per-year roll, modulated by health
  3. Old age mortality           — exponential ramp once age > life expectancy

We also expose `kill_check()` which returns a (died, cause) tuple so the
event loop can record a cause-of-death string.
"""

from __future__ import annotations

import math
import random

from .character import Character
from .world import Country


def infant_mortality_chance(country: Country) -> float:
    """Probability of dying in the first year, normalized from per-1000 stat."""
    return min(0.5, country.infant_mortality / 1000.0)


def background_mortality(character: Character, country: Country) -> float:
    """Per-year background death roll for healthy adults.

    Calibrated so that a healthy adult in a high-HDI country has roughly
    real-world background mortality (~0.001/year for ages 20-50, with health
    impairment kicking in only when health drops below 50). Old age is
    handled by the separate exponential ramp in :func:`old_age_mortality`.
    """
    health = max(1, character.attributes.health)
    base = 0.0008
    # Health penalty only kicks in below 50 (severely impaired) and ramps
    # up steeply from there.
    if health < 50:
        base += (50 - health) * 0.0006
    if country.hdi < 0.6:
        base *= 1.4
    if country.health_services_pct < 70:
        base *= 1.3
    return base


def old_age_mortality(character: Character, country: Country) -> float:
    """Exponential ramp once age exceeds country life expectancy."""
    excess = character.age - country.life_expectancy
    if excess < -10:
        return 0.0
    if excess < 0:
        return 0.001
    # 0.5% at LE, ramps to ~50% at LE+15.
    return min(0.95, 0.005 * math.exp(excess * 0.28))


def total_death_chance(character: Character, country: Country) -> float:
    """Combined probability for the year (after the infant window)."""
    return min(0.99, background_mortality(character, country) + old_age_mortality(character, country))


def kill_check(character: Character, country: Country, rng: random.Random) -> tuple[bool, str | None]:
    """Roll for death this year. Returns (died, cause)."""
    if character.age == 0:
        if rng.random() < infant_mortality_chance(country):
            return True, "infant mortality"
    if character.attributes.health <= 0:
        return True, "poor health"
    if rng.random() < total_death_chance(character, country):
        if character.age > country.life_expectancy:
            return True, "old age"
        return True, "natural causes"
    return False, None
