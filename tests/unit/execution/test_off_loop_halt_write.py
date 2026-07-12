"""05.3-08 Task 2 (D-21 / WR-02) — the durable halt write runs OFF the connector loop thread.

``OkxExchange._supervisor._escalate_halt`` runs on the connector asyncio loop thread (it is
reached from ``_run_stream_supervisor`` on a fatal error / exhausted retry ceiling / the
unclassified catch-all). Pre-fix it invoked the injected halt signal = ``LiveTradingSystem.halt``
SYNCHRONOUSLY, and ``halt()`` performs a BLOCKING ``HaltRecordStore.record_halt`` SQL write. A
blocking SQL round-trip on the asyncio loop stalls EVERY stream sharing that loop (WR-02 /
Pitfall 9).

D-21 makes the escalation a thread-safe FLAG handoff (mirroring the pause/resume flags): the
connector loop only flips a flag; the blocking durable write + status flip + CRITICAL alert run
on the ENGINE thread when it drains the flag. Winner-only single-write + D-10 latch ordering +
the V7 secret scrub are all preserved.

RED (current code): the production-wired connector-fatal signal is ``system.halt``, so driving
``_escalate_connector_halt`` on a loop thread runs ``record_halt`` on THAT loop thread. GREEN
(after the flag handoff): the loop thread records nothing; ``_maybe_halt_after_connector_fatal``
on the engine thread does the durable write.

Fully offline: dummy OKX creds build the okx arm with NO network. 4-space indentation
(``tests/unit/execution/*``); folder-derived ``unit`` marker.
"""

import threading

from itrader.trading_system.live_trading_system import LiveTradingSystem


def _set_okx_env(monkeypatch) -> None:
    """Dummy OKX credential triple so the okx arm constructs offline (no network)."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


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


def test_connector_fatal_durable_write_runs_off_the_loop_thread(monkeypatch) -> None:
    """A connector-fatal escalation writes the durable halt OFF the loop thread (D-21/WR-02)."""
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem(exchange="okx")
    store = _CapturingHaltStore()
    system._halt_record_store = store
    try:
        # The PRODUCTION-wired connector-fatal signal (wired at construction on the okx arm).
        assert system._okx_exchange._halt_signal is not None

        # Drive the escalation on a dedicated "connector asyncio loop" thread — exactly the
        # thread the fatal/ceiling/catch-all supervisor arms escalate from.
        loop_ident: dict[str, int] = {}

        def loop() -> None:
            loop_ident["id"] = threading.get_ident()
            system._okx_exchange._supervisor._escalate_halt(
                "fills", RuntimeError("secret-bearing venue error"), "fatal auth/permission error")

        t = threading.Thread(target=loop, name="connector-loop")
        t.start()
        t.join()

        # D-21/WR-02: the blocking durable write must NOT have run on the loop thread —
        # the escalation is flag-only there.
        assert store.record_threads == [], (
            "record_halt ran on the connector asyncio loop thread — a blocking SQL write on "
            "the loop stalls every stream sharing it (WR-02 / Pitfall 9)")

        # The engine thread drains the flag -> the blocking record_halt runs HERE, off the loop.
        system._maybe_halt_after_connector_fatal()
        assert len(store.record_threads) == 1
        assert store.record_threads[0] == threading.get_ident()   # engine (this) thread
        assert store.record_threads[0] != loop_ident["id"]        # never the loop thread
    finally:
        system.stop()


def test_connector_fatal_winner_only_single_durable_write(monkeypatch) -> None:
    """Two connector-fatal escalations still write the durable halt exactly ONCE (winner-only)."""
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem(exchange="okx")
    store = _CapturingHaltStore()
    system._halt_record_store = store
    try:
        signal = system._okx_exchange._halt_signal

        def loop() -> None:
            # Two escalations from the loop (e.g. both stream arms fail) only flip the flag.
            signal("connector-fatal")
            signal("connector-fatal")

        t = threading.Thread(target=loop, name="connector-loop")
        t.start()
        t.join()
        assert store.record_threads == []

        # First drain writes; a second drain is a no-op (flag cleared + halt() winner-only).
        system._maybe_halt_after_connector_fatal()
        system._maybe_halt_after_connector_fatal()
        assert len(store.record_threads) == 1, (
            "winner-only single-write violated: a second connector-fatal escalation "
            "double-wrote the durable halt record (D-10 latch)")
    finally:
        system.stop()
