"""CR-01 — cross-emitter fill dedup at the portfolio settlement chokepoint.

The live OKX trade stream and the restart ``VenueReconciler`` can both book the SAME
economic venue trade (they share no other idempotency key — ``fill_id`` is a fresh uuid7
per emit). ``PortfolioHandler.on_fill`` now dedups on the venue trade id so the same
economic trade settles into position/cash EXACTLY once, regardless of which emitter
produced the ``FillEvent``.

These tests exercise the settlement chokepoint directly (the emitter is irrelevant — a
stream fill and a reconciler-adopted fill carrying the SAME ``venue_trade_id`` are
byte-identical at ``on_fill``):

* SAME venue_trade_id, two deliveries → settled ONCE (the CR-01 double-count is closed).
* DISTINCT venue_trade_ids → both settle (two real partial fills).
* ``venue_trade_id=None`` (backtest/simulated) → the guard is skipped entirely, so two
  such fills BOTH settle — the SMA_MACD oracle takes no new branch (oracle-dark).
* the venue_trade_id is threaded onto the durable ``Transaction`` record.
* the bounded FIFO ledger evicts the oldest id past its cap.

Folder-derived ``unit`` marker (no decorator).
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue
from types import SimpleNamespace

import pytest
import uuid_utils.compat as uuid_compat

from itrader.core.enums import FillStatus, Side
from itrader.events_handler.events import FillEvent
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from tests.support.venue_wiring import backtest_portfolio_handler


@pytest.fixture
def env():
    queue: "Queue" = Queue()
    ptf = backtest_portfolio_handler(queue)
    pid = ptf.add_portfolio("p", "default", 100000)

    def fill(*, venue_trade_id=None, quantity=0.5, price=40000.0):
        return FillEvent(
            time=datetime(2024, 1, 1),
            status=FillStatus.EXECUTED,
            ticker="BTCUSDT",
            action=Side.BUY,
            price=price,
            quantity=quantity,
            commission=0.0,
            portfolio_id=pid,
            fill_id=uuid_compat.uuid7(),   # fresh per fill — NOT a cross-emitter key
            order_id=uuid_compat.uuid7(),
            strategy_id=1,
            venue_trade_id=venue_trade_id,
        )

    yield SimpleNamespace(queue=queue, ptf=ptf, pid=pid, fill=fill)
    while not queue.empty():
        queue.get_nowait()


def test_same_venue_trade_id_settles_once(env):
    """Two fills for the SAME venue trade id settle EXACTLY once (CR-01 double-count closed).

    Models the stream emit + reconciler adopt of one economic venue trade: distinct
    ``fill_id``s but the SAME ``venue_trade_id``. The second is rejected BEFORE it mutates
    position/cash.
    """
    first = env.fill(venue_trade_id="T-42", quantity=0.5)
    second = env.fill(venue_trade_id="T-42", quantity=0.5)  # same venue trade, re-delivered
    assert first.fill_id != second.fill_id                  # fill_id is NOT the dedup key

    assert env.ptf.on_fill(first) is None
    assert env.ptf.on_fill(second) is None                  # rejected as a duplicate

    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.transactions) == 1                 # booked once, not twice
    assert portfolio.positions["BTCUSDT"].net_quantity == Decimal("0.5")
    # D-08 Layer 2 (V17-12): the ledger key is symbol-scoped f"{ticker}:{venue_trade_id}"
    # so the same numeric id on a different symbol still settles (collision-safe).
    assert "BTCUSDT:T-42" in env.ptf._settled_venue_trade_ids


def test_distinct_venue_trade_ids_both_settle(env):
    """Two DISTINCT venue trade ids are two real partial fills — both settle."""
    env.ptf.on_fill(env.fill(venue_trade_id="T-1", quantity=0.2))
    env.ptf.on_fill(env.fill(venue_trade_id="T-2", quantity=0.3))

    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.transactions) == 2
    assert portfolio.positions["BTCUSDT"].net_quantity == Decimal("0.5")


def test_none_venue_trade_id_skips_dedup_guard(env):
    """Backtest/simulated fills (venue_trade_id=None) skip the guard — both settle.

    This is the oracle-dark invariant: a None-keyed fill NEVER touches the dedup ledger,
    so the byte-exact SMA_MACD backtest takes no new branch. Two None-keyed fills settle
    independently (no spurious dedup).
    """
    env.ptf.on_fill(env.fill(venue_trade_id=None, quantity=0.5))
    env.ptf.on_fill(env.fill(venue_trade_id=None, quantity=0.5))

    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.transactions) == 2                 # neither deduped
    assert portfolio.positions["BTCUSDT"].net_quantity == Decimal("1.0")
    assert len(env.ptf._settled_venue_trade_ids) == 0       # ledger never touched


def test_venue_trade_id_threaded_onto_transaction(env):
    """The venue trade id is carried onto the durable Transaction settlement record."""
    env.ptf.on_fill(env.fill(venue_trade_id="T-99", quantity=0.5))

    portfolio = env.ptf.get_portfolio(env.pid)
    transaction = portfolio.transactions[0]
    assert transaction.venue_trade_id == "T-99"


def test_settled_ledger_is_bounded_fifo(env):
    """The settled-id ledger evicts the oldest id once it exceeds its cap (no unbounded growth)."""
    env.ptf._max_settled_venue_trade_ids = 3
    for i in range(5):
        env.ptf._mark_venue_trade_settled(f"T-{i}")

    ledger = env.ptf._settled_venue_trade_ids
    assert len(ledger) == 3
    assert list(ledger.keys()) == ["T-2", "T-3", "T-4"]     # oldest two evicted
