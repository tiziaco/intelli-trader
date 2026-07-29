"""P7 (SAFE-03 / §11c) — the durable halt write runs OFF the connector loop thread.

``OkxExchange._supervisor._escalate_halt`` runs on the connector asyncio loop thread (it is
reached from ``_run_stream_supervisor`` on a fatal error / exhausted retry ceiling / the
unclassified catch-all). It invokes the injected halt signal =
``LiveTradingSystem._request_connector_halt``, which now only ``bus.put``s a
``ConnectorFatalEvent`` CONTROL event (a fixed reason literal, V7 secret-scrub) — it does NOT
run the blocking ``HaltRecordStore.record_halt`` SQL write on the loop.

The engine-thread ``CONNECTOR_FATAL`` route actuates ``SafetyController.halt(event.reason)``,
which performs the blocking durable write + status flip + CRITICAL alert on the ENGINE thread.
Winner-only single-write + D-10 latch ordering + the V7 secret scrub are all preserved.

RED (pre-P7): the connector-fatal signal drove ``halt()`` synchronously on the loop thread, so
``record_halt`` ran on THAT loop thread. GREEN (after the CONTROL-event handoff): the loop
thread only puts an event; ``SafetyController.halt`` on the engine thread does the durable write.

11.2-07 (D-20): the OKX account set is now STORE-DERIVED, so an OKX arm assembles only
against a durable ``venue_accounts`` row. This test therefore uses the ``provisioned_okx``
Postgres spine (it moved from ``tests/unit/execution/`` to ``tests/integration/`` for that
reason) and reads the single assembled OKX lifecycle rather than the deleted
``_primary_lifecycle``. 4-space indentation; folder-derived ``integration`` marker.
"""

import threading

from itrader.events_handler.events import ConnectorFatalEvent
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.live_okx import bring_okx_online


class _CapturingHaltStore:
    """A durable halt store double that records the THREAD each ``record_halt`` ran on."""

    def __init__(self) -> None:
        self.record_threads: list[int] = []

    def record_halt(self, reason, at) -> None:
        self.record_threads.append(threading.get_ident())

    def has_unresolved(self) -> bool:
        return bool(self.record_threads)

    def get_unresolved(self):
        return None

    def resolve_all(self) -> None:
        pass

    def dispose(self) -> None:
        pass


def _drain_connector_fatal(system: LiveTradingSystem) -> None:
    """Engine-thread actuation of the queued CONNECTOR_FATAL event (the route target).

    Mirrors what the ``CONNECTOR_FATAL`` route does on the engine thread —
    ``SafetyController.halt(event.reason)`` — off the connector loop. Drains every queued
    ConnectorFatalEvent, halting once (halt() is winner-only/idempotent).
    """
    drained = []
    while not system.global_queue.empty():
        drained.append(system.global_queue.get_nowait())
    for ev in drained:
        if isinstance(ev, ConnectorFatalEvent):
            system._safety.halt(ev.reason)


def test_connector_fatal_durable_write_runs_off_the_loop_thread(provisioned_okx) -> None:
    """A connector-fatal escalation writes the durable halt OFF the loop thread (SAFE-03/§11c)."""
    system = LiveTradingSystem.for_exchange("okx")
    store = _CapturingHaltStore()
    system._safety._halt_record_store = store
    try:
        # The PRODUCTION-wired connector-fatal signal: bring-up arms it before the
        # account is routable, so an online account always has one.
        exchange = bring_okx_online(system).adapter
        assert exchange._halt_signal is not None

        # Drive the escalation on a dedicated "connector asyncio loop" thread — exactly the
        # thread the fatal/ceiling/catch-all supervisor arms escalate from.
        loop_ident: dict[str, int] = {}

        def loop() -> None:
            loop_ident["id"] = threading.get_ident()
            exchange._supervisor._escalate_halt(
                "fills", RuntimeError("secret-bearing venue error"), "fatal auth/permission error")

        t = threading.Thread(target=loop, name="connector-loop")
        t.start()
        t.join()

        # SAFE-03/§11c: the blocking durable write must NOT have run on the loop thread —
        # the callback only put a CONNECTOR_FATAL CONTROL event there.
        assert store.record_threads == [], (
            "record_halt ran on the connector asyncio loop thread — a blocking SQL write on "
            "the loop stalls every stream sharing it (Pitfall 9)")

        # The engine thread actuates the queued CONNECTOR_FATAL event -> the blocking
        # record_halt runs HERE, off the loop.
        _drain_connector_fatal(system)
        assert len(store.record_threads) == 1
        assert store.record_threads[0] == threading.get_ident()   # engine (this) thread
        assert store.record_threads[0] != loop_ident["id"]        # never the loop thread
    finally:
        system.stop()


def test_connector_fatal_winner_only_single_durable_write(provisioned_okx) -> None:
    """Two connector-fatal escalations still write the durable halt exactly ONCE (winner-only)."""
    system = LiveTradingSystem.for_exchange("okx")
    store = _CapturingHaltStore()
    system._safety._halt_record_store = store
    try:
        signal = bring_okx_online(system).adapter._halt_signal

        def loop() -> None:
            # Two escalations from the loop (e.g. both stream arms fail) only put events.
            signal("connector-fatal")
            signal("connector-fatal")

        t = threading.Thread(target=loop, name="connector-loop")
        t.start()
        t.join()
        assert store.record_threads == []

        # Actuating both queued events halts once (halt() winner-only + D-10 latch).
        _drain_connector_fatal(system)
        assert len(store.record_threads) == 1, (
            "winner-only single-write violated: a second connector-fatal escalation "
            "double-wrote the durable halt record (D-10 latch)")
    finally:
        system.stop()
