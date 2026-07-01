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
import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def portfolio():
    return Portfolio(
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
        40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    portfolio.process_transaction(buy)
    # Cash is still Decimal mid-flight (the BUY debit went through the
    # Decimal cash path, not a float += cast).
    assert isinstance(portfolio.cash, Decimal)

    sell = Transaction(
        datetime.now(), TransactionType.SELL, "BTCUSDT",
        42000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    portfolio.process_transaction(sell)

    assert isinstance(portfolio.cash, Decimal)
    # Exact Decimal equality — proves no float-rounding corruption on the path.
    assert portfolio.cash == Decimal("152000")


def test_transaction_money_fields_are_decimal():
    """Transaction money fields and the cost property are Decimal."""
    txn = Transaction(
        datetime.now(), TransactionType.BUY, "BTCUSDT",
        42350.72, 1, 1.5, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    assert isinstance(txn.price, Decimal)
    assert isinstance(txn.quantity, Decimal)
    assert isinstance(txn.commission, Decimal)
    assert isinstance(txn.cost, Decimal)
    # Entered via to_money(str(x)) — exact Decimal, no binary-float artifact.
    assert txn.price == Decimal("42350.72")
    assert txn.cost == Decimal("42350.72")


# M5-10 (Plan 08-01): result-bearing money properties on Portfolio are Decimal
# end-to-end — no float() narrowing at the property boundary (D-06, closes the
# "Float Leaks at Portfolio Property Boundary" concern on the golden path).

def test_total_market_value_is_decimal(portfolio):
    """total_market_value returns the position_manager Decimal aggregate unchanged."""
    assert isinstance(portfolio.total_market_value, Decimal)


def test_total_equity_is_decimal_and_equals_market_plus_cash(portfolio):
    """total_equity is Decimal and equals total_market_value + cash (Decimal+Decimal)."""
    assert isinstance(portfolio.total_equity, Decimal)
    assert portfolio.total_equity == portfolio.total_market_value + portfolio.cash
    # Empty portfolio: equity is exactly the starting cash.
    assert portfolio.total_equity == Decimal("150000")


def test_total_unrealised_and_realised_pnl_are_decimal(portfolio):
    """Both pnl read-properties return Decimal (no float narrowing)."""
    assert isinstance(portfolio.total_unrealised_pnl, Decimal)
    assert isinstance(portfolio.total_realised_pnl, Decimal)


def test_total_pnl_is_decimal_and_equals_unrealised_plus_realised(portfolio):
    """total_pnl is Decimal and equals total_unrealised_pnl + total_realised_pnl."""
    assert isinstance(portfolio.total_pnl, Decimal)
    assert portfolio.total_pnl == (
        portfolio.total_unrealised_pnl + portfolio.total_realised_pnl
    )


def test_total_properties_stay_decimal_after_transaction(portfolio):
    """After a round-trip trade, every total_* property is still Decimal."""
    buy = Transaction(
        datetime.now(), TransactionType.BUY, "BTCUSDT",
        40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    portfolio.process_transaction(buy)
    assert isinstance(portfolio.total_market_value, Decimal)
    assert isinstance(portfolio.total_equity, Decimal)
    assert isinstance(portfolio.total_unrealised_pnl, Decimal)
    assert isinstance(portfolio.total_realised_pnl, Decimal)
    assert isinstance(portfolio.total_pnl, Decimal)
