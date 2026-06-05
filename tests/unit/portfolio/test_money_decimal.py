"""M2-02 regression lock: money is Decimal end-to-end on the cash path.

This is the tight regression test for the float→Decimal money retype (Plan 02-04):

- A constructed ``Portfolio.cash`` is a ``Decimal`` (not float).
- After a transaction processes, ``portfolio.cash`` is STILL a ``Decimal`` —
  proving the ``transaction_manager.py`` float round-trip (#17) is gone.
- A ``Transaction``'s ``price``/``quantity``/``commission`` and its ``cost``
  property are ``Decimal``.

Auto-marked ``unit`` by the root conftest (folder-derived: this file lives under
``tests/unit/``). Test function names contain ``decimal`` so ``-k decimal`` selects
them (VALIDATION.md M2-02 command: ``pytest tests/unit/portfolio -k decimal -x``).
"""

from decimal import Decimal
from datetime import datetime

import pytest

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def portfolio():
    return Portfolio(
        user_id=1,
        name="decimal_pf",
        exchange="simulated",
        cash=150000,
        time=datetime.now(),
    )


def test_constructed_cash_is_decimal(portfolio):
    """A freshly constructed Portfolio exposes cash as a Decimal."""
    assert isinstance(portfolio.cash, Decimal)
    assert portfolio.cash == Decimal("150000")


def test_cash_stays_decimal_after_transaction_no_float_roundtrip(portfolio):
    """Processing a transaction keeps cash a Decimal (no float round-trip).

    Buy 1 BTC @ 40000, then sell 1 BTC @ 42000 — cash must land at exactly
    152000 as a Decimal, never having round-tripped through float.
    """
    buy = Transaction(
        datetime.now(), TransactionType.BUY, "BTCUSDT",
        40000, 1, 0, None, idgen.generate_transaction_id(),
    )
    portfolio.process_transaction(buy)
    # Cash is still Decimal mid-flight (the BUY debit went through the
    # Decimal cash path, not a float += cast).
    assert isinstance(portfolio.cash, Decimal)

    sell = Transaction(
        datetime.now(), TransactionType.SELL, "BTCUSDT",
        42000, 1, 0, None, idgen.generate_transaction_id(),
    )
    portfolio.process_transaction(sell)

    assert isinstance(portfolio.cash, Decimal)
    # Exact Decimal equality — proves no float-rounding corruption on the path.
    assert portfolio.cash == Decimal("152000")


def test_transaction_money_fields_are_decimal():
    """Transaction money fields and the cost property are Decimal."""
    txn = Transaction(
        datetime.now(), TransactionType.BUY, "BTCUSDT",
        42350.72, 1, 1.5, None, idgen.generate_transaction_id(),
    )
    assert isinstance(txn.price, Decimal)
    assert isinstance(txn.quantity, Decimal)
    assert isinstance(txn.commission, Decimal)
    assert isinstance(txn.cost, Decimal)
    # Entered via to_money(str(x)) — exact Decimal, no binary-float artifact.
    assert txn.price == Decimal("42350.72")
    assert txn.cost == Decimal("42350.72")
