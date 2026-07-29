"""Spot drift guard: a spot base holding must be compared, not hidden (D-03/D-04).

On a SPOT account the venue reports no position rows, so per-symbol position truth is
DERIVED from the base-currency balance by the execution adapter and arrives here inside
an ``AccountSnapshot``. Two directions of that compare have to hold, and getting either
wrong is expensive:

* ``test_spot_no_drift_halt`` — the engine holds a real 0.5 BTC base position and venue
  truth agrees (0.5). It MUST NOT halt: a spurious halt on the first position-opening
  fill freezes a healthy engine and needs an operator to clear it.
* ``test_spot_unexplained_divergence_is_surfaced`` — the engine is FLAT while venue truth
  holds 0.9 BTC (a genuine unexplained holding). It MUST halt: an unnoticed position the
  engine does not know about is un-managed risk, sized and exited by nobody.

Venue truth is injected through ``PortfolioHandler.set_snapshot_source`` — the seam
answering "what does the venue say this portfolio holds?" — so these arms pin the drift
DECISION on a spot-shaped snapshot. How a venue payload becomes that snapshot is the
adapter's rule, pinned in ``tests/unit/execution/test_adapter_snapshot.py``.

Fully offline — no ``OKX_API_*`` credentials, no network, no connector.
"""

import queue
from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.core.ids import CorrelationId
from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from tests.support.venue_wiring import (
    backtest_portfolio_handler,
    compute_account,
)

_TICKER = "BTC/USDC"


def _cid() -> CorrelationId:
    return CorrelationId(idgen.generate_correlation_id())


def _buy(qty: str, price: str = "100") -> Transaction:
    """A BUY ``Transaction`` used only to seed the engine position belief."""
    return Transaction(
        datetime.now(), TransactionType.BUY, _TICKER, Decimal(price), Decimal(qty),
        Decimal("0"), None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


def _spot_snapshot(btc_total: str) -> AccountSnapshot:
    """Spot venue truth holding ``btc_total`` of the pair's base currency.

    A zero base total is FLAT, and flat is an ABSENT key — mirroring what the adapter
    derives, so the compare here sees exactly the shape live code hands it.
    """
    base = Decimal(btc_total)
    return AccountSnapshot(
        balances={"USDC": Decimal("150000"), "BTC": base},
        positions={_TICKER: base} if base != 0 else {},
    )


@pytest.fixture
def handler() -> PortfolioHandler:
    return backtest_portfolio_handler(queue.Queue())


@pytest.fixture
def halt_calls(handler: PortfolioHandler) -> list[str]:
    calls: list[str] = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


@pytest.fixture
def spot_venue_portfolio(handler: PortfolioHandler):
    """A live-shaped ``Portfolio`` whose venue truth reports ``btc_total`` base.

    The portfolio sits on a COMPUTE leaf, as every live portfolio does — its cash and
    positions are the engine's own tally, and the venue's answer arrives separately
    through the handler's snapshot source. That separation is what makes the two
    quantities comparable at all.
    """

    def _make(btc_total: str) -> Portfolio:
        portfolio = Portfolio("spot_venue_pf", "okx", Decimal("150000"), datetime.now(),
                              account=compute_account(Decimal("150000")))
        snapshot = _spot_snapshot(btc_total)
        handler.set_snapshot_source(lambda p: snapshot)
        return portfolio

    return _make


# --- ARM 1: an agreeing spot base holding must NOT halt (D-04 band) -----------


def test_spot_no_drift_halt(handler, halt_calls, spot_venue_portfolio):
    """A freshly-opened spot position that AGREES with venue base truth must not halt.

    Engine 0.5 vs venue 0.5 is exact agreement; a halt here would mean the compare is
    reading the wrong channel (spot ``fetch_positions`` is ``[]``, so a positions-row
    read would report FLAT against a live engine position).
    """
    portfolio = spot_venue_portfolio("0.5")
    portfolio.position_manager.process_position_update(_buy(qty="0.5"))

    handler._compare_symbol_drift(portfolio, _TICKER, _cid())

    assert halt_calls == []


# --- ARM 2: a genuine unexplained base-balance divergence MUST be surfaced ----


def test_spot_unexplained_divergence_is_surfaced(handler, halt_calls,
                                                 spot_venue_portfolio):
    """An unexplained venue base holding must be surfaced (halt), not hidden.

    The engine is FLAT while the venue holds 0.9 BTC. Nothing else in the engine will
    ever notice that position, so failing to halt leaves it un-managed indefinitely.
    """
    portfolio = spot_venue_portfolio("0.9")
    # Engine believes FLAT (no seeded position).

    handler._compare_symbol_drift(portfolio, _TICKER, _cid())

    assert halt_calls == ["drift"]
