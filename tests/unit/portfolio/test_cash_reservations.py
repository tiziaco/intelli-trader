"""Pitfall 6 (Plan 06-06): reservation vs gap-up next-open settlement.

The admission gate reserves ``decision_close x quantity + est. commission``
at signal time (Phase 5 D-04). Under the next-bar-open fill convention
(D-01/D-13) the actual fill can settle HIGHER on a gap-up — the settlement
debit then EXCEEDS the reservation. That must succeed:

* ``OrderEvent.price`` is a decision-price ESTIMATE (a pre-trade gate,
  not a fill ceiling);
* the settlement funds invariant checks the ledger BALANCE, never the
  reservation-adjusted buying power (Pitfall 2 — FILL dispatches
  portfolio-first, so the order's own un-released reservation would
  false-positive otherwise);
* the terminal release frees the exact reserved amount (idempotent).

If the cash manager ever rejects the over-reservation debit, that is a
Phase 5 behavior change to surface to the owner — these tests lock the
current (correct) semantics.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import uuid_utils.compat as uuid_compat

from itrader.core.enums import FillStatus, Side
from itrader.events_handler.events import FillEvent
from tests.support.venue_wiring import backtest_portfolio_handler


def _gap_up_fill(portfolio_id, order_id, *, price, quantity,
                 time=datetime(2024, 1, 2)):
    """An EXECUTED BUY fill at the (gapped-up) next bar's open."""
    return FillEvent(
        time=time,
        status=FillStatus.EXECUTED,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=price,
        quantity=quantity,
        commission=Decimal("0"),
        portfolio_id=portfolio_id,
        fill_id=uuid_compat.uuid7(),
        order_id=order_id,
        strategy_id=1,
    )


def test_gap_up_settlement_above_reservation_succeeds_and_releases():
    """A BUY reserved at decision-close settles at a HIGHER next-open:
    the debit succeeds (invariant checks balance, not available) and the
    terminal release frees the exact reserved amount."""
    handler = backtest_portfolio_handler(Queue())
    pid = handler.add_portfolio("p", "paper", 10000)
    portfolio = handler.get_portfolio(pid)
    cash = portfolio.account
    order_id = uuid_compat.uuid7()

    # Admission gate: decision-bar close 100 x qty 10 -> reserve 1000.
    handler.reserve(pid, order_id, Decimal("1000"))
    assert cash.reserved_balance == Decimal("1000")
    assert cash.available_balance == Decimal("9000")

    # Next bar gaps up: fill at open 110 -> debit 1100 > the 1000 reserved.
    # Must NOT raise: solvency is balance-based (10000 >= 1100).
    handler.on_fill(_gap_up_fill(pid, order_id,
                                 price=Decimal("110"), quantity=Decimal("10")))
    assert cash.balance == Decimal("8900")

    # The reservation is still held until terminal reconciliation —
    # available reflects both the debit and the (stale) reservation,
    # and the invariant never consulted it.
    assert cash.reserved_balance == Decimal("1000")

    # Terminal reconciliation: the reserver releases the EXACT reserved
    # amount; buying power returns to the full post-settle balance.
    handler.release(pid, order_id)
    assert cash.reserved_balance == Decimal("0")
    assert cash.available_balance == cash.balance == Decimal("8900")


def test_release_after_gap_up_settle_is_idempotent():
    """A second release for the same order id is a silent no-op — the
    uniform terminal release in on_fill reconciliation can never double-free."""
    handler = backtest_portfolio_handler(Queue())
    pid = handler.add_portfolio("p", "paper", 10000)
    cash = handler.get_portfolio(pid).account
    order_id = uuid_compat.uuid7()

    handler.reserve(pid, order_id, Decimal("1000"))
    handler.on_fill(_gap_up_fill(pid, order_id,
                                 price=Decimal("105"), quantity=Decimal("10")))
    handler.release(pid, order_id)
    handler.release(pid, order_id)  # idempotent no-op
    assert cash.reserved_balance == Decimal("0")
    assert cash.balance == Decimal("8950")
    assert cash.available_balance == Decimal("8950")
