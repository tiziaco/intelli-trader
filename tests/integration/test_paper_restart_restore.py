"""D-23 — a durable paper/simulated engine restart restores its persisted cash + realised PnL.

The gap this closes (D-23, owner-locked option (a) scalar-restore): on the live
``LiveTradingSystem.start()`` path ``PortfolioHandler.rehydrate()`` used to sit INSIDE the
``if self.exchange == 'okx' and self._venue_account is not None:`` arm — AFTER
``_link_venue_account_to_portfolios()`` had already swapped every portfolio onto the
``VenueAccount`` (whose ``restore_cash`` is a documented no-op). So on a NON-okx
(paper/simulated) engine ``rehydrate()`` NEVER fired: the already-built (and unit-tested)
``SimulatedCashAccount.restore_cash`` + ``PositionManager.restore_realised_pnl`` were DEAD,
and a durable paper account restarted with its construction-time initial cash instead of
its persisted balance.

The fix UNGATES ``rehydrate()`` from the okx arm — it now runs whenever the store exposes
``rehydrate()`` (the durable Postgres spine), REGARDLESS of exchange — while
``VenueAccount.snapshot()`` / ``_link_venue_account_to_portfolios()`` /
``VenueReconciler.reconcile()`` stay strictly inside the okx arm. Semantics on the paper
path are RESTORE (the ``SimulatedAccount`` ledger is sole truth), never venue reconcile.

Both tests drive the REAL ``LiveTradingSystem.start()`` fully OFFLINE (no OKX network, no
credentials, no Postgres) on ``exchange="paper"``: ``_initialize_live_session`` is coerced
to a no-op, the durable-store gate is opened by exposing a ``rehydrate`` attr on
``_order_storage``, and a rehydrate spy halts the engine right after the restore so
``start()`` refuses RUNNING and never spawns the processing thread.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.storage.in_memory_storage import (
    InMemoryPortfolioStateStorage,
)
from itrader.portfolio_handler.reconcile import venue_reconciler as venue_reconciler_module
from itrader.trading_system.live_trading_system import LiveTradingSystem

# A business time (never wall clock) so the persisted row's timestamp is deterministic.
_BT = datetime(2024, 1, 1, tzinfo=timezone.utc)


class _CashPnlDurableStoreDouble(InMemoryPortfolioStateStorage):
    """Durable-store stand-in carrying a persisted cash + realised-PnL scalar (D-23).

    Mirrors the ``CachedSqlPortfolioStateStorage.rehydrate`` -> ``account.restore_cash``
    contract the live restart drives on the SIMULATED path: a persisted account-state row
    exists, so ``rehydrate(account)`` pushes the persisted cash scalar into the account.
    ``load_account_state`` additionally exposes the persisted ``realized_pnl`` so
    ``PortfolioHandler.rehydrate`` can re-seed ``PositionManager.restore_realised_pnl``.
    """

    def __init__(
        self,
        *,
        durable_cash: Optional[Decimal] = None,
        durable_realized_pnl: Decimal = Decimal("0"),
    ) -> None:
        super().__init__()
        self._durable_cash: Optional[Decimal] = durable_cash
        self._durable_realized_pnl: Decimal = durable_realized_pnl

    def load_account_state(self) -> Optional[Dict[str, Any]]:
        """Return the persisted account-state row, or None if none was persisted."""
        if self._durable_cash is None:
            return None
        return {
            "cash_balance": self._durable_cash,
            "realized_pnl": self._durable_realized_pnl,
            "total_equity": self._durable_cash,
            "peak_equity": self._durable_cash,
            "open_positions_count": 0,
            "updated_time": _BT,
        }

    def rehydrate(self, account: Any = None) -> None:
        """Drive the restore contract: push the persisted cash scalar into the account."""
        state = self.load_account_state()
        if account is not None and state is not None:
            account.restore_cash(state["cash_balance"])


def _rebind_storage(portfolio: Portfolio, store: Any) -> None:
    """Point a fresh Portfolio's managers at the shared durable store (restart wiring)."""
    portfolio.state_storage = store
    portfolio.account._storage = store
    portfolio.position_manager._storage = store
    portfolio.transaction_manager._storage = store
    portfolio.metrics_manager._storage = store


@pytest.fixture(autouse=True)
def _no_pg_env(monkeypatch):
    """Guarantee the in-memory fallback (no durable ``_order_storage`` rehydrate leaks in)."""
    for var in ("ITRADER_DATABASE_PASSWORD", "ITRADER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_paper_restart_rehydrate_ungate_runs_without_venue_reconcile(monkeypatch) -> None:
    """A NON-okx (paper) engine with a durable store rehydrates on start(); NO venue reconcile.

    RED (rehydrate trapped in the okx arm): the paper ``start()`` path never calls
    ``rehydrate`` — ``calls`` stays empty and the spy never halts, so the assertion fails.
    GREEN (ungated): ``rehydrate`` runs for the durable store REGARDLESS of exchange, and
    ``VenueReconciler.reconcile()`` / venue snapshot are NOT invoked on the paper path.
    """
    system = LiveTradingSystem.for_exchange("paper")
    calls: List[str] = []

    try:
        # Record when the REAL portfolio rehydrate runs (wrap, don't replace — the real
        # per-portfolio getattr-guarded loop still executes, a no-op with no portfolios),
        # then HALT so start() refuses RUNNING and spawns no thread.
        original_rehydrate = system.portfolio_handler.rehydrate

        def _spy_rehydrate(*args: Any, **kwargs: Any) -> None:
            calls.append("rehydrate")
            original_rehydrate(*args, **kwargs)
            system.halt("test-stop-after-rehydrate")

        monkeypatch.setattr(system.portfolio_handler, "rehydrate", _spy_rehydrate)

        # Any reconcile would record here — it must NOT run on the paper path.
        monkeypatch.setattr(
            venue_reconciler_module,
            "VenueReconciler",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("VenueReconciler must not run on the paper path")
            ),
        )

        # Drive start() OFFLINE: skip session wiring, open the durable-store gate by
        # exposing a rehydrate attr on _order_storage. exchange stays "paper" so the
        # okx venue block (snapshot/link/reconcile) is skipped entirely.
        monkeypatch.setattr(system, "_initialize_live_session", lambda: None)
        monkeypatch.setattr(
            system._order_storage, "rehydrate", lambda *a, **k: None, raising=False
        )

        started = system.start()

        # start() refused RUNNING (halted right after the ungated rehydrate) — no thread.
        assert started is False
        # The load-bearing behaviour: rehydrate ran on the paper path (ungated), and the
        # venue reconcile never fired (its stub would have raised).
        assert calls == ["rehydrate"], (
            "a durable paper/simulated engine must rehydrate on start() REGARDLESS of "
            f"exchange (D-23 ungate) — observed calls {calls!r}"
        )
    finally:
        system.stop(timeout=5.0)


def test_simulated_restore_cash_and_realised_pnl_on_paper_start(monkeypatch) -> None:
    """The ungate activates SimulatedAccount restart restore on the paper path (D-23).

    A durable paper portfolio persisted a cash scalar (99934.53) + realised-PnL
    accumulator (1234.56) before the restart. On the current (trapped) code the paper
    ``start()`` never rehydrates, so the fresh account keeps its construction-time initial
    cash (100000.00) and zero realised PnL. With the ungate the persisted scalars are
    restored — reaching ``SimulatedCashAccount.restore_cash`` +
    ``PositionManager.restore_realised_pnl`` (previously dead on this path).
    """
    system = LiveTradingSystem.for_exchange("paper")

    # A fresh durable paper portfolio at its construction-time initial cash, wired to a
    # durable store carrying the pre-restart cash + realised-PnL scalars.
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="paper_pf", exchange="simulated", cash=Decimal("100000.00")
    )
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    store = _CashPnlDurableStoreDouble(
        durable_cash=Decimal("99934.53"),
        durable_realized_pnl=Decimal("1234.56"),
    )
    _rebind_storage(portfolio, store)

    # Pre-start: the fresh account remembers nothing (construction-time cash, zero PnL).
    assert portfolio.account.balance == Decimal("100000.00")
    assert portfolio.total_realised_pnl == Decimal("0.00")

    try:
        # Halt right after the ungated rehydrate so start() refuses RUNNING (no thread);
        # the restore already ran by then.
        original_rehydrate = system.portfolio_handler.rehydrate

        def _spy_rehydrate(*args: Any, **kwargs: Any) -> None:
            original_rehydrate(*args, **kwargs)
            system.halt("test-stop-after-rehydrate")

        monkeypatch.setattr(system.portfolio_handler, "rehydrate", _spy_rehydrate)
        monkeypatch.setattr(system, "_initialize_live_session", lambda: None)
        monkeypatch.setattr(
            system._order_storage, "rehydrate", lambda *a, **k: None, raising=False
        )

        started = system.start()

        assert started is False
        # The ungate reached the previously-dead restore leaves: the persisted cash +
        # realised-PnL scalars are restored on the paper/simulated path.
        assert portfolio.account.balance == Decimal("99934.53")
        assert portfolio.total_realised_pnl == Decimal("1234.56")
    finally:
        system.stop(timeout=5.0)
