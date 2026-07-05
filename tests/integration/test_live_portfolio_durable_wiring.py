"""05.2-05 (D-07) — durable portfolio-ledger wiring at the live composition root.

Two observable guarantees the composition-root wiring must hold:

* **Rehydrate BEFORE reconcile (T-05.2-14 mitigation).** On the live ``start()`` path the
  engine's OWN durable portfolio ledger must be restored (``PortfolioHandler.rehydrate()``)
  BEFORE the venue reconcile (``VenueReconciler.reconcile()``) so venue adoption diffs
  against RESTORED engine state — a rehydrate AFTER reconcile would adopt against an
  un-restored (empty) engine belief and corrupt the diff. Asserted with a call-order spy,
  fully OFFLINE (no OKX network, no credentials) by coercing the ``start()`` OKX branch with
  no-op venue/reconciler stubs, modelled on ``test_halt_latch.py``.

* **Durable-store presence selects the 'live' arm; absence degrades to 'backtest'.** With a
  Postgres spine present the live ``PortfolioHandler`` is constructed on the durable 'live'
  arm threading the SHARED ``SqlBackend`` (so each portfolio persists to the durable ledger);
  with no ``ITRADER_DATABASE_*`` env it falls back cleanly to the in-memory 'backtest' arm.
  The 'live' arm is proven against the shared testcontainers Postgres (SKIPS Dockerless, D-11);
  the fallback is proven fully offline.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""

from typing import Any, List

import pytest

from itrader.portfolio_handler.reconcile import venue_reconciler as venue_reconciler_module
from itrader.trading_system.live_trading_system import LiveTradingSystem


class _StubVenueAccount:
    """Minimal venue-account stand-in so the OKX venue block is entered offline."""

    def snapshot(self) -> None:  # noqa: D401 - no-op stub
        pass

    def start_streaming(self) -> None:
        pass


class _RecordingReconciler:
    """Fake VenueReconciler recording that ``reconcile()`` ran (accepts any kwargs)."""

    def __init__(self, calls: List[str], **_kwargs: Any) -> None:
        self._calls = calls

    def reconcile(self) -> None:
        self._calls.append("reconcile")


def test_no_durable_store_falls_back_to_backtest(monkeypatch) -> None:
    """With no ``ITRADER_DATABASE_*`` env the live PortfolioHandler is 'backtest' (degrades cleanly)."""
    # Belt-and-suspenders over the session-autouse dev-DB guard: guarantee no PG env leaks in.
    for var in ("ITRADER_DATABASE_PASSWORD", "ITRADER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)

    system = LiveTradingSystem(exchange="paper")
    try:
        assert system._system_db_backend is None
        # The durable arm was not taken — the portfolio ledger stays in-memory (oracle-dark).
        assert system.portfolio_handler._environment == "backtest"
        assert system.portfolio_handler._backend is None
    finally:
        system.stop(timeout=5.0)


def test_durable_store_constructs_live_portfolio_handler(pg_database_env) -> None:
    """With the Postgres spine present the PortfolioHandler is 'live' + shares the SqlBackend.

    Uses the shared session testcontainers Postgres via ``pg_database_env`` (sets
    ``ITRADER_DATABASE_URL``); SKIPS Dockerless (D-11).
    """
    system = LiveTradingSystem(exchange="paper")
    try:
        # The durable arm was taken — one shared SqlBackend spine built.
        assert system._system_db_backend is not None
        # The PortfolioHandler is wired on the durable 'live' arm with the SAME shared backend,
        # so every portfolio it creates persists to the durable SQL ledger (D-07).
        assert system.portfolio_handler._environment == "live"
        assert system.portfolio_handler._backend is system._system_db_backend
    finally:
        system.stop(timeout=5.0)


def test_portfolio_rehydrate_runs_before_reconcile_on_live_start(monkeypatch) -> None:
    """The live ``start()`` path rehydrates the portfolio ledger BEFORE venue reconcile (T-05.2-14).

    Fully offline: coerce the OKX venue block with no-op venue/reconciler stubs, record the
    call order of ``PortfolioHandler.rehydrate()`` vs ``VenueReconciler.reconcile()``, and halt
    in the post-reconcile baseline guard so no live thread is ever spawned.
    """
    system = LiveTradingSystem(exchange="paper")
    calls: List[str] = []

    try:
        # Record when the REAL portfolio rehydrate runs (wrap, don't replace — the real
        # per-portfolio getattr-guarded loop still executes, a no-op with no portfolios).
        original_rehydrate = system.portfolio_handler.rehydrate

        def _spy_rehydrate() -> None:
            calls.append("rehydrate")
            original_rehydrate()

        monkeypatch.setattr(system.portfolio_handler, "rehydrate", _spy_rehydrate)

        # Patch the lazily-imported VenueReconciler so reconcile() records the order.
        monkeypatch.setattr(
            venue_reconciler_module,
            "VenueReconciler",
            lambda **kwargs: _RecordingReconciler(calls, **kwargs),
        )

        # Coerce the OKX venue branch OFFLINE: skip _initialize_live_session (paper/universe
        # wiring irrelevant to the ordering), enter the venue block with a stub account, and
        # ensure the store exposes rehydrate() so the reconcile sub-block runs. No connector /
        # data-provider / exchange -> the earlier OKX network sub-blocks all skip.
        monkeypatch.setattr(system, "_initialize_live_session", lambda: None)
        monkeypatch.setattr(system, "_link_venue_account_to_portfolios", lambda: None)
        system.exchange = "okx"
        system._okx_connector = None
        system._okx_data_provider = None
        system._okx_exchange = None
        system._venue_account = _StubVenueAccount()
        monkeypatch.setattr(system._order_storage, "rehydrate", lambda: None, raising=False)
        # Halt in the post-reconcile baseline guard so start() refuses RUNNING and spawns no
        # thread — the rehydrate/reconcile ordering is already captured by then.
        monkeypatch.setattr(
            system, "_run_session_baseline_guard",
            lambda: system.halt("test-stop-after-reconcile"),
        )

        started = system.start()

        # start() refused RUNNING (halted in the baseline guard) — no thread spawned.
        assert started is False
        # The load-bearing ordering: rehydrate strictly BEFORE reconcile (T-05.2-14).
        assert calls == ["rehydrate", "reconcile"], (
            "portfolio rehydrate must run BEFORE venue reconcile so adoption diffs against "
            f"restored engine state — observed call order {calls!r}"
        )
    finally:
        system.stop(timeout=5.0)
