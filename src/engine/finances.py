"""
Finances: loans, investments, yearly money flow.

Most of the per-year income/expense flow lives in `careers.yearly_income`;
this module covers the discrete actions a player can take during a turn —
take out a loan, make an investment — and resolves loan interest and
investment returns each year.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .character import Character, InvestmentHolding, LoanHolding
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


def get_loan_product(product_id: int) -> LoanProduct | None:
    return next((p for p in list_loans() if p.id == product_id), None)


def get_investment_product(product_id: int) -> InvestmentProduct | None:
    return next((p for p in list_investments() if p.id == product_id), None)


# ---------------------------------------------------------------------------
# Player actions
# ---------------------------------------------------------------------------

# Minimum age for non-family loans (#37). Family loans are slightly more
# permissive — a parent can lend to a teenager — but the standard adult
# threshold is 18 for everything else.
LOAN_MIN_AGE = 18
FAMILY_LOAN_MIN_AGE = 14


# Minimum age for investments by product name (#68). Real-world banking:
# kids can have a savings account from ~12 with a parent co-signer; bonds
# usually need a brokerage account at 16+; the riskier instruments
# (stocks, real estate, small business) need an adult signing.
def investment_min_age(product_name: str) -> int:
    name = product_name.lower()
    if "savings" in name:
        return 12
    if "bond" in name:
        return 16
    return 18


def take_loan(character: Character, product: LoanProduct, amount: int, year: int) -> LoanHolding:
    """Open a new loan against `product`. Adds the principal to the player's
    cash and tracks the loan as a LoanHolding for per-year repayment.

    Raises ValueError on bad input (over the product's max, non-positive,
    too young to borrow, etc.)."""
    min_age = FAMILY_LOAN_MIN_AGE if product.name == "family loan" else LOAN_MIN_AGE
    if character.age < min_age:
        raise ValueError(
            f"you must be at least {min_age} to take out a {product.name}"
        )
    if amount <= 0:
        raise ValueError("loan amount must be positive")
    if amount > product.max_amount:
        raise ValueError(f"{product.name} caps out at ${product.max_amount:,}")
    holding = LoanHolding(
        product_id=product.id,
        name=product.name,
        principal=amount,
        balance=amount,
        interest_rate=product.interest_rate,
        years_remaining=product.max_years,
        opened_year=year,
    )
    character.loans.append(holding)
    character.money += amount
    character.debt += amount
    return holding


def buy_investment(character: Character, product: InvestmentProduct, amount: int, year: int) -> InvestmentHolding:
    """Open a new investment position. Deducts cash from the player.

    Raises ValueError on bad input (too young, under min, non-positive,
    insufficient cash)."""
    min_age = investment_min_age(product.name)
    if character.age < min_age:
        raise ValueError(
            f"you must be at least {min_age} to buy a {product.name}"
        )
    if amount <= 0:
        raise ValueError("investment amount must be positive")
    if amount < product.min_amount:
        raise ValueError(f"{product.name} requires at least ${product.min_amount:,}")
    if amount > character.money:
        raise ValueError("not enough cash on hand")
    holding = InvestmentHolding(
        product_id=product.id,
        name=product.name,
        cost_basis=amount,
        value=amount,
        opened_year=year,
    )
    character.investments.append(holding)
    character.money -= amount
    return holding


def sell_investment(character: Character, index: int) -> int:
    """Liquidate the investment at `index`. Returns cash credited."""
    if index < 0 or index >= len(character.investments):
        raise ValueError("invalid investment index")
    inv = character.investments.pop(index)
    proceeds = max(0, int(inv.value))
    character.money += proceeds
    return proceeds


def pay_loan(character: Character, index: int, amount: int) -> int:
    """Apply a manual extra payment to loan `index` (#40). Drains the
    requested amount from the character's cash and reduces the loan
    balance by the same amount. If the payment fully clears the loan,
    the holding is removed. Returns the actual amount applied."""
    if index < 0 or index >= len(character.loans):
        raise ValueError("invalid loan index")
    if amount <= 0:
        raise ValueError("payment amount must be positive")
    if amount > character.money:
        raise ValueError("not enough cash on hand")
    loan = character.loans[index]
    applied = min(amount, loan.balance)
    character.money -= applied
    loan.balance -= applied
    if loan.balance <= 0:
        character.loans.pop(index)
    character.debt = sum(l.balance for l in character.loans)
    return applied


# ---------------------------------------------------------------------------
# Yearly tick
# ---------------------------------------------------------------------------

@dataclass
class FinanceTick:
    """A summary of a single year's investment + loan activity."""
    investment_pl: int = 0          # net mark-to-market change this year
    loan_interest: int = 0          # interest accrued across all loans
    loan_payments: int = 0          # principal+interest paid out of cash this year
    closed_loans: list[str] = None  # names of loans paid off this year
    closed_investments: list[str] = None  # names of investments that bottomed out


def tick_finances(character: Character, rng: random.Random) -> FinanceTick:
    """Advance all open loans and investments by one year.

    Loans: balance grows by interest, then a fixed annual payment is deducted
    from the player's cash. If the player can't afford the payment, the unpaid
    portion is added back to debt (effectively rolling it over).

    Investments: value is multiplied by a uniform random in [1+low, 1+high].
    The player's `debt` field is kept in sync with the sum of loan balances
    so existing UI/financial-stress logic still works.
    """
    products = {p.id: p for p in list_investments()}
    tick = FinanceTick(closed_loans=[], closed_investments=[])

    # ---- Investments: update mark-to-market values ----
    for inv in list(character.investments):
        prod = products.get(inv.product_id)
        if prod is None:
            continue
        # Catastrophic-loss roll (#41): the position can go to zero with
        # probability risk * 0.10 per year. Real small businesses fail
        # >50% over 10 years; savings accounts never (risk=0). This makes
        # the `risk` field actually load-bearing instead of decorative.
        if prod.risk > 0 and rng.random() < prod.risk * 0.10:
            tick.investment_pl -= inv.value
            inv.value = 0
            tick.closed_investments.append(inv.name)
            continue
        roll = rng.uniform(prod.annual_return_low, prod.annual_return_high)
        delta = int(inv.value * roll)
        inv.value += delta
        tick.investment_pl += delta
        if inv.value <= 0:
            tick.closed_investments.append(inv.name)
    character.investments = [i for i in character.investments if i.value > 0]

    # ---- Loans: accrue interest, deduct annual payment ----
    for loan in list(character.loans):
        if loan.balance <= 0 or loan.years_remaining <= 0:
            continue
        interest = int(loan.balance * loan.interest_rate)
        loan.balance += interest
        tick.loan_interest += interest
        # Annual payment = even amortization across remaining years.
        payment = max(1, int(loan.balance / max(1, loan.years_remaining)))
        if character.money >= payment:
            character.money -= payment
            loan.balance -= payment
            tick.loan_payments += payment
        else:
            # Pay what we can; the rest stays on the balance and rolls forward.
            paid = max(0, character.money)
            character.money -= paid
            loan.balance -= paid
            tick.loan_payments += paid
        loan.years_remaining -= 1
        if loan.balance <= 0:
            loan.balance = 0
            tick.closed_loans.append(loan.name)

    character.loans = [l for l in character.loans if l.balance > 0]
    character.debt = sum(l.balance for l in character.loans)
    return tick


def portfolio_value(character: Character) -> int:
    return sum(i.value for i in character.investments)


def financial_stress(character: Character, country: Country) -> int:
    """Negative happiness delta if the player is broke or buried in debt."""
    if character.debt > character.salary * 5:
        return -8
    if character.money < 0 or character.salary == 0 and character.age >= 25:
        return -4
    return 0
