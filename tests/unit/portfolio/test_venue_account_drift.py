"""Engine-thread per-symbol drift compare + halt decision (D-15/D-01/D-04, RECON-01/03).

Locks the drift-compare decision policy the ``PortfolioHandler`` runs on the ENGINE
thread (on fill + on the per-closed-bar backstop sweep):

* within the precision-epsilon band → adopt venue truth silently, no halt (D-01);
* beyond band AND unexplained → freeze-in-place halt signalled (D-01/D-02);
* beyond band that reconciles to a KNOWN venue event (an external / hand-closed
  fill) → adopt-and-continue, no halt (D-04 — an external fill is NOT drift).

Venue truth reaches the policy through ONE injected seam,
``PortfolioHandler.set_snapshot_source``: a callable answering "what does the venue say
this portfolio holds?" with an ``AccountSnapshot``, or ``None`` when no venue stands
behind it. Backtest and paper leave it unwired, so every compare skips — the mechanism
that keeps the SMA_MACD oracle byte-exact.

Driving the seam directly is deliberate. These tests are about the DECISION (which skew
halts and which is forgiven), not about how any particular venue payload is parsed —
that derivation is the execution adapter's, pinned in
``tests/unit/execution/test_adapter_snapshot.py``. Feeding hand-built snapshots keeps a
policy regression from being masked by, or blamed on, a payload-shape change.

A lightweight fake portfolio carries the engine tally and a recording halt callback
captures the freeze-in-place signal.
"""

import queue
import uuid
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any, Optional

import pytest

from itrader import idgen
from itrader.core.ids import CorrelationId
from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from tests.support.venue_wiring import backtest_portfolio_handler

_BTC = "BTC/USDT"


def _snapshot(positions: dict[str, Decimal]) -> AccountSnapshot:
    """Venue truth reporting ``positions`` plus a settled quote balance.

    A FLAT symbol is an ABSENT key, never a zero entry — the contract both adapter
    channels honour, so ``{}`` here is what "the venue holds none of it" looks like.
    """
    return AccountSnapshot(
        balances={"USDT": Decimal("78999.79")}, positions=dict(positions))


class _FakePosition:
    def __init__(self, net_quantity: Decimal) -> None:
        self.net_quantity = net_quantity


class _FakePortfolio:
    """Minimal portfolio surface the drift compare reads (the engine position tally)."""

    def __init__(self, positions: dict[str, Decimal]) -> None:
        self.portfolio_id = uuid.uuid4()
        self._positions = positions

    def get_open_position(self, ticker: str) -> Any:
        qty = self._positions.get(ticker)
        return _FakePosition(qty) if qty is not None else None

    @property
    def positions(self) -> dict[str, Any]:
        return {t: _FakePosition(q) for t, q in self._positions.items()}


def _cid() -> CorrelationId:
    return CorrelationId(idgen.generate_correlation_id())


@pytest.fixture
def handler() -> PortfolioHandler:
    return backtest_portfolio_handler(queue.Queue())


@pytest.fixture
def venue_truth(handler: PortfolioHandler):
    """Wire the handler's snapshot source to a per-test venue position map."""

    def _wire(positions: Optional[dict[str, Decimal]]) -> None:
        snapshot = None if positions is None else _snapshot(positions)
        handler.set_snapshot_source(lambda portfolio: snapshot)

    return _wire


@pytest.fixture
def halt_calls(handler: PortfolioHandler) -> list[str]:
    calls: list[str] = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


# --- D-01: within the precision-epsilon band → adopt silently, no halt ---------


def test_within_band_drift_does_not_halt(handler, venue_truth, halt_calls):
    # 0.5 vs 0.500000005 → diff 5e-9 ≤ 1e-8 (precision 8) — last-digit dust, adopt.
    venue_truth({_BTC: Decimal("0.500000005")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


def test_exact_agreement_does_not_halt(handler, venue_truth, halt_calls):
    venue_truth({_BTC: Decimal("0.5")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- D-01/D-02: unexplained beyond-band drift → freeze-in-place halt signalled --


def test_beyond_band_unexplained_drift_halts(handler, venue_truth, halt_calls):
    venue_truth({_BTC: Decimal("0.9")})                          # venue truth
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})           # engine tally
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


def test_beyond_band_with_no_engine_position_halts(handler, venue_truth, halt_calls):
    # Venue reports a position the engine has never seen and no reconciler → halt.
    venue_truth({_BTC: Decimal("0.3")})
    portfolio = _FakePortfolio({})  # engine flat
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


def test_reconciler_returning_false_still_halts(handler, venue_truth, halt_calls):
    handler.set_drift_reconciler(lambda p, t, e, v: False)
    venue_truth({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


# --- D-04: beyond-band drift that maps to a known venue event → adopt, no halt --


def test_beyond_band_external_fill_is_adopted_no_halt(handler, venue_truth, halt_calls):
    # A reconciler that confirms the drift maps to a known venue event (external /
    # hand-closed fill) → adopt-and-continue; the engine keeps running (D-04).
    handler.set_drift_reconciler(lambda p, t, e, v: True)
    venue_truth({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- oracle inertness: a portfolio with no venue behind it never compares -------


def test_portfolio_without_venue_truth_skips_compare(handler, venue_truth, halt_calls):
    """A source answering ``None`` for this portfolio means no comparison is possible.

    Engine-computed cash and positions have nothing external to disagree with, so a
    compare here could only invent drift out of an empty venue answer and halt a
    healthy engine.
    """
    venue_truth(None)
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


def test_unwired_snapshot_source_skips_compare(handler, halt_calls):
    """The default with NO source wired must skip — this is the backtest arm.

    A handler that compared against absent truth would halt the SMA_MACD run on its
    first position, so "no seam wired" has to mean "nothing to reconcile".
    """
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- D-15: the per-closed-bar backstop sweep also compares + halts --------------


def test_bar_sweep_halts_on_unexplained_drift(handler, venue_truth, halt_calls,
                                              monkeypatch):
    venue_truth({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(datetime.now(UTC))
    assert halt_calls == ["drift"]


def test_bar_sweep_is_a_noop_within_band(handler, venue_truth, halt_calls, monkeypatch):
    venue_truth({_BTC: Decimal("0.5")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(datetime.now(UTC))
    assert halt_calls == []


def test_bar_sweep_skips_when_bar_time_none(handler, venue_truth, halt_calls,
                                            monkeypatch):
    venue_truth({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio({_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(None)
    assert halt_calls == []
