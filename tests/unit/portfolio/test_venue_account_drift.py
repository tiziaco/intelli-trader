"""Engine-thread per-symbol drift compare + halt decision (05-04, D-15/D-01/D-04, RECON-01/03).

Locks the drift-compare decision policy the ``PortfolioHandler`` runs on the ENGINE
thread (on fill + on the per-closed-bar backstop sweep):

* within the precision-epsilon band → adopt venue truth silently, no halt (D-01);
* beyond band AND unexplained → freeze-in-place halt signalled (D-01/D-02);
* beyond band that reconciles to a KNOWN venue event (an external / hand-closed
  fill) → adopt-and-continue, no halt (D-04 — an external fill is NOT drift).

A backtest/paper ``SimulatedAccount`` portfolio has no venue truth, so the compare
skips cleanly — the mechanism that keeps the SMA_MACD oracle byte-exact.

The compare is unit-tested directly (the on_fill / BAR-sweep entry points delegate
to the same ``_compare_symbol_drift``): a real ``VenueAccount`` (cache seeded
without connecting) carries venue truth, a lightweight fake portfolio carries the
engine tally, and a recording halt callback captures the freeze-in-place signal.
"""

import queue
import uuid
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from itrader import idgen
from itrader.core.ids import CorrelationId
from itrader.portfolio_handler.account.simulated import SimulatedCashAccount
from itrader.portfolio_handler.account.venue import VenueAccount
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler

_BTC = "BTC/USDT"


def _venue_account(positions: dict[str, Decimal]) -> VenueAccount:
    """A ``VenueAccount`` with its cache seeded directly (no connect / no stream).

    ``VenueAccount.__init__`` only binds the connector; seeding the RLock-guarded
    cache fields directly mirrors ``test_venue_account_cache.py`` (which reads the
    same private fields) and lets a drift test drive controlled venue truth without
    a live connector loop.
    """
    account = VenueAccount(MagicMock(name="connector"))
    account._venue_positions = dict(positions)
    account._venue_balance = Decimal("78999.79")
    account._venue_available = Decimal("78999.79")
    return account


class _FakePosition:
    def __init__(self, net_quantity: Decimal) -> None:
        self.net_quantity = net_quantity


class _FakePortfolio:
    """Minimal portfolio surface the drift compare reads (account + position tally)."""

    def __init__(self, account: Any, positions: dict[str, Decimal]) -> None:
        self.account = account
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
    return PortfolioHandler(queue.Queue())


@pytest.fixture
def halt_calls(handler: PortfolioHandler) -> list[str]:
    calls: list[str] = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


# --- D-01: within the precision-epsilon band → adopt silently, no halt ---------


def test_within_band_drift_does_not_halt(handler, halt_calls):
    # 0.5 vs 0.500000005 → diff 5e-9 ≤ 1e-8 (precision 8) — last-digit dust, adopt.
    account = _venue_account({_BTC: Decimal("0.500000005")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


def test_exact_agreement_does_not_halt(handler, halt_calls):
    account = _venue_account({_BTC: Decimal("0.5")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- D-01/D-02: unexplained beyond-band drift → freeze-in-place halt signalled --


def test_beyond_band_unexplained_drift_halts(handler, halt_calls):
    account = _venue_account({_BTC: Decimal("0.9")})   # venue truth
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})  # engine tally
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


def test_beyond_band_with_no_engine_position_halts(handler, halt_calls):
    # Venue reports a position the engine has never seen and no reconciler → halt.
    account = _venue_account({_BTC: Decimal("0.3")})
    portfolio = _FakePortfolio(account, {})  # engine flat
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


def test_reconciler_returning_false_still_halts(handler, halt_calls):
    handler.set_drift_reconciler(lambda p, t, e, v: False)
    account = _venue_account({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == ["drift"]


# --- D-04: beyond-band drift that maps to a known venue event → adopt, no halt --


def test_beyond_band_external_fill_is_adopted_no_halt(handler, halt_calls):
    # A reconciler that confirms the drift maps to a known venue event (external /
    # hand-closed fill) → adopt-and-continue; the engine keeps running (D-04).
    handler.set_drift_reconciler(lambda p, t, e, v: True)
    account = _venue_account({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- oracle inertness: SimulatedAccount portfolios skip the compare ------------


def test_simulated_account_portfolio_skips_compare(handler, halt_calls):
    sim_account = MagicMock(spec=SimulatedCashAccount)
    portfolio = _FakePortfolio(sim_account, {_BTC: Decimal("0.5")})
    # Even with a wildly different "venue" would-be tally, a non-VenueAccount
    # portfolio never compares — no halt, byte-exact backtest path.
    handler._compare_symbol_drift(portfolio, _BTC, _cid())
    assert halt_calls == []


# --- D-15: the per-closed-bar backstop sweep also compares + halts --------------


def test_bar_sweep_halts_on_unexplained_drift(handler, halt_calls, monkeypatch):
    account = _venue_account({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(datetime.now(UTC))
    assert halt_calls == ["drift"]


def test_bar_sweep_is_a_noop_within_band(handler, halt_calls, monkeypatch):
    account = _venue_account({_BTC: Decimal("0.5")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(datetime.now(UTC))
    assert halt_calls == []


def test_bar_sweep_skips_when_bar_time_none(handler, halt_calls, monkeypatch):
    account = _venue_account({_BTC: Decimal("0.9")})
    portfolio = _FakePortfolio(account, {_BTC: Decimal("0.5")})
    monkeypatch.setattr(handler, "get_active_portfolios", lambda: [portfolio])
    handler._run_drift_sweep(None)
    assert halt_calls == []
