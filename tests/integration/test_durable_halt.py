"""05.2-06 (D-10 / ARCH-4 Layer 2) — the HALTED latch survives a process restart.

Phase 05.1 D-05 landed an IN-PROCESS HALTED latch, but a supervised auto-restart builds a
FRESH ``LiveTradingSystem`` whose in-process ``_status`` is ``STOPPED`` — so a breaker-class
halt whose cause is not re-detectable at start would be silently cleared. This plan adds a
DURABLE halt record on the shared ``SqlBackend`` spine: ``halt()`` persists it, ``start()``
refuses RUNNING while an unresolved record exists (the DURABLE record is what latches across a
restart), and ``reset_halt()`` resolves it.

Security (V7 secret-scrub, T-05.2-18): the durable record persists ONLY the machine-readable
reason literal + timestamp — never ``str(exc)`` or a connector payload. The schema deliberately
has NO free-form exception/payload column.

Two arms:

* **Store round-trip (Task 1).** ``HaltRecordStore`` over an in-memory ``SqlBackend`` double:
  record → ``has_unresolved()`` True → ``resolve_all()`` → False.
* **Fresh-instance refuse-RUNNING (Task 2).** A FRESH ``LiveTradingSystem`` sharing the SAME
  store (in-process ``_status`` STOPPED) refuses RUNNING while the durable record is unresolved;
  ``reset_halt()`` resolves it so a subsequent ``start()`` is no longer refused. Asserting on the
  SAME object would only re-test the D-05 in-process latch — the observable MUST be a fresh
  instance (RESEARCH Pitfall 7).

4-space indentation (``tests/integration/*`` convention); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker. The in-memory
``:memory:`` SQLite double keeps this fully OFFLINE — no Docker, no Postgres, no credentials.
"""

from datetime import UTC, datetime
from decimal import Decimal

from itrader.config.sql import SqlSettings
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.storage import SqlBackend
from itrader.storage.halt_record_store import HaltRecordStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.live_trading_system import LiveTradingSystem


def _make_store() -> HaltRecordStore:
    """An in-memory durable double — the shared ``SqlBackend`` on ``:memory:`` SQLite.

    ``SqlSettings.default()`` pins the in-process SQLite arm; the ``SingletonThreadPool``
    that pysqlite uses for ``:memory:`` keeps the same in-memory DB alive across
    ``engine.begin()`` calls on the test thread, so a single store instance persists its
    rows for the life of the test (the fresh-instance arm shares ONE store).
    """
    return HaltRecordStore(SqlBackend(SqlSettings.default()))


def test_halt_record_round_trip() -> None:
    """record → has_unresolved True → get_unresolved returns the literal → resolve → False.

    RED before ``halt_record_store`` existed (ImportError); GREEN once the store + its
    chained migration land. Proves ONLY the reason literal + timestamp are stored.
    """
    store = _make_store()
    try:
        assert store.has_unresolved() is False
        assert store.get_unresolved() is None

        at = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)
        store.record_halt("drift", at)

        assert store.has_unresolved() is True
        record = store.get_unresolved()
        assert record is not None
        # The machine-readable literal + timestamp round-trip — nothing else is persisted.
        assert record.reason == "drift"
        assert record.created_at == at

        store.resolve_all()
        assert store.has_unresolved() is False
        assert store.get_unresolved() is None
    finally:
        # Dispose the in-memory engine so no unclosed-sqlite ResourceWarning leaks
        # into the strict suite (filterwarnings=["error"]).
        store.dispose()


def _build_paper_system(store: HaltRecordStore) -> LiveTradingSystem:
    """A fully offline paper-venue system sharing ``store`` as its durable halt latch.

    Mirrors ``test_halt_latch.py::_build_paper_system`` (strategy + portfolio subscribed so
    ``start()`` can reach RUNNING), but injects the shared in-memory ``HaltRecordStore`` double
    via attribute assignment so a FRESH instance on the SAME store observes a prior halt (the
    restart model — RESEARCH Pitfall 7). No OKX network / credentials.
    """
    system = LiveTradingSystem(exchange="paper")
    system._halt_record_store = store
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="durable_halt_pf",
        exchange="simulated",
        cash=10_000,
    )
    strategy.subscribe_portfolio(portfolio_id)
    return system


def test_fresh_instance_refuses_running_on_unresolved_durable_halt() -> None:
    """A FRESH system on the same store refuses RUNNING while a durable halt is unresolved.

    RED before wiring: ``halt()`` persists nothing and ``start()`` runs no durable check, so the
    fresh instance STARTS (``start()`` returns True) despite the prior halt. GREEN after: the
    durable record persisted by the first system's ``halt('drift')`` makes the fresh system's
    ``start()`` return False. Asserting on the SAME object would only re-test the D-05 in-process
    latch — the observable MUST be a fresh instance.
    """
    store = _make_store()
    try:
        # First process: halt on a breaker-class reason. The durable record must persist.
        first = _build_paper_system(store)
        try:
            first.halt("drift")
            # The persisted reason is the machine-readable literal — never str(exc) (V7 scrub).
            persisted = store.get_unresolved()
            assert persisted is not None
            assert persisted.reason == "drift"
        finally:
            first.stop(timeout=5.0)

        # Supervised auto-restart: a FRESH system on the SAME store (in-process _status STOPPED).
        fresh = _build_paper_system(store)
        try:
            started = fresh.start()
            # The DURABLE record latches across the restart: RUNNING is refused.
            assert started is False, (
                "D-10 durable latch missing: a fresh instance started RUNNING despite an "
                "unresolved durable halt record — a supervised restart silently cleared the "
                "breaker halt (T-05.2-17)"
            )
        finally:
            fresh.stop(timeout=5.0)
    finally:
        store.dispose()


def test_reset_halt_resolves_durable_record_and_permits_restart() -> None:
    """``reset_halt()`` resolves the durable record so a subsequent ``start()`` is not refused.

    The fresh instance re-latches in-process HALTED from the durable record on the refused
    ``start()``, so ``reset_halt()`` (which requires in-process HALTED) clears BOTH the
    in-process latch and the durable record (F/U-9 verify-then-trust). A subsequent ``start()``
    then passes the durable check and reaches RUNNING.
    """
    store = _make_store()
    try:
        first = _build_paper_system(store)
        try:
            first.halt("drift")
        finally:
            first.stop(timeout=5.0)

        fresh = _build_paper_system(store)
        try:
            assert fresh.start() is False  # refused by the unresolved durable record

            # Operator clears the latch: reset_halt resolves the durable record.
            assert fresh.reset_halt() is True
            assert store.has_unresolved() is False

            # A subsequent start() is no longer refused by the durable check — reaches RUNNING.
            assert fresh.start() is True
        finally:
            fresh.stop(timeout=5.0)
    finally:
        store.dispose()
