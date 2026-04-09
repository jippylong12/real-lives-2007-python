"""
Finances: loans, investments, yearly money flow.

Most of the per-year income/expense flow lives in `careers.yearly_income`;
this module covers the discrete actions a player can take during a turn —
take out a loan, make an investment — and resolves loan interest each year.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .character import Character
from .world import Country
from ..data.build_db import get_connection


@dataclass(frozen=True)
class LoanProduct:
    id: int
    name: str
    max_amount: int
    interest_rate: float
    max_years: int


@dataclass(frozen=True)
class InvestmentProduct:
    id: int
    name: str
    annual_return_low: float
    annual_return_high: float
    risk: float
    min_amount: int


def list_loans() -> list[LoanProduct]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM loans").fetchall()
    finally:
        conn.close()
    return [LoanProduct(**{k: r[k] for k in r.keys()}) for r in rows]


def list_investments() -> list[InvestmentProduct]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM investments").fetchall()
    finally:
        conn.close()
    return [InvestmentProduct(**{k: r[k] for k in r.keys()}) for r in rows]


def accrue_debt_interest(character: Character) -> int:
    """Apply 8% APR to outstanding debt each year."""
    if character.debt <= 0:
        return 0
    interest = int(character.debt * 0.08)
    character.debt += interest
    return interest


def financial_stress(character: Character, country: Country) -> int:
    """Negative happiness delta if the player is broke or buried in debt."""
    if character.debt > character.salary * 5:
        return -8
    if character.money < 0 or character.salary == 0 and character.age >= 25:
        return -4
    return 0
