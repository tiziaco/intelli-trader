"""05.3-08 Task 1 (D-20 / WR-01) — a durably-HALTED start() refuses BEFORE any venue I/O.

Phase 05.2-06 (D-10) landed a DURABLE halt latch: ``start()`` refuses RUNNING while an
unresolved durable record exists. But the refusal gate was sequenced LATE — after the full
OKX handshake (``connect`` + ``load_markets``), the feed warmup + ``start_stream``, the
order-arm stream spawn, the ``VenueAccount.snapshot()``, AND the state-mutating
``VenueReconciler.reconcile()``. A durably-HALTED engine that should stay inert therefore
performed real venue I/O and a state-mutating reconcile before finally refusing (WR-01).

D-20 moves the durable-halt refusal to the TOP of ``start()`` — right after
``update_status(STARTING)`` and BEFORE any ``connect``/``snapshot``/stream spawn/reconcile.
A durably-HALTED engine then stays inert: it re-latches HALTED and returns False with ZERO
venue I/O and no second durable record.

RED (current code): the gate is late, so a durably-halted ``start()`` calls
``_initialize_live_session`` + the connector connect + the venue snapshot before refusing —
the venue-I/O spies fire. GREEN (after the move): the refusal is at the top, so none of the
venue spies are ever called.

Fully offline: dummy OKX creds build the okx arm with NO network (connect is deferred to
``start()`` and here every network call is spied/stubbed). 4-space indentation
(``tests/integration/*`` convention); folder-derived ``integration`` marker; NO ``__init__.py``.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from itrader.core.enums import SystemStatus
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.live_okx import stub_data_session, stub_okx_session


class _UnresolvedHaltStore:
    """A durable halt store double whose record is ALWAYS unresolved (the restart latch).

    Only the surface ``start()``'s durable-refusal gate touches: ``has_unresolved`` /
    ``get_unresolved``. ``record_halt`` is a no-op — the gate re-latches in-process via
    ``update_status`` (NOT ``halt()``), so no second durable record is ever written.
    """

    def __init__(self, reason: str = "drift") -> None:
        self._reason = reason

    def has_unresolved(self) -> bool:
        return True

    def get_unresolved(self):
        return SimpleNamespace(reason=self._reason, created_at=datetime.now(UTC))

    def record_halt(self, reason, at) -> None:  # pragma: no cover - must never fire here
        raise AssertionError(
            "record_halt() must not run on a durably-halted refusal — the gate re-latches "
            "via update_status, never a second durable write (D-20).")

    def resolve_all(self) -> None:
        pass

    def dispose(self) -> None:
        pass


def test_durably_halted_start_refuses_before_any_venue_io(provisioned_okx) -> None:
    """A durably-halted ``start()`` refuses at the TOP with zero venue I/O (D-20/WR-01)."""
    system = LiveTradingSystem.for_exchange("okx")
    # P7 (§11b): the durable halt store + check_durable_halt_on_start live on the injected
    # SafetyController now — inject the always-unresolved double there.
    system._safety._halt_record_store = _UnresolvedHaltStore("drift")

    # Spy/stub EVERY call start() could make before the refusal. On the fixed (top-gate)
    # code none of these run; on the pre-fix (late-gate) code they all run before refusing.
    system._initialize_live_session = MagicMock(name="_initialize_live_session")
    # The venue arm is reached through the account's own session: bring-up is what opens
    # it, and bring-up is a step of start(). Pre-building it here (over stubbed I/O) is
    # what makes "zero venue I/O" observable — the connect spy belongs to the object the
    # bring-up would have used.
    connector = stub_okx_session(system)
    # The DATA adapter holds a session of its own, and start() opens it — so it is stubbed
    # too, and its connect spy is a second, independent witness that no venue I/O ran.
    data_connector = stub_data_session(system)
    system.feed.warmup = MagicMock(name="feed.warmup")
    # WR-01/WR-03: the venue-link + baseline-guard logic no longer lives on the facade —
    # production reconciles exclusively via _build_reconciliation_coordinator()
    # .run_startup_reconcile() (the coordinator owns the link + guard copies). Spy the
    # builder so we can assert the durable-halt top-gate short-circuits reconcile BEFORE
    # the coordinator is ever constructed (a meaningful check; the old
    # _link_venue_account_to_portfolios/_run_session_baseline_guard asserts were vacuous —
    # production never called those dead facade methods).
    system._build_reconciliation_coordinator = MagicMock(
        name="_build_reconciliation_coordinator")

    try:
        started = system.start()

        # Refused — and re-latched HALTED from the durable record (in-process, no re-halt).
        assert started is False
        assert system.get_status()["status"] == SystemStatus.HALTED.value

        # D-20: the refusal is at the TOP — ZERO session init and ZERO venue I/O ran.
        system._initialize_live_session.assert_not_called()
        connector.connect.assert_not_called()
        system.feed.warmup.assert_not_called()
        # Nothing was brought online, so nothing is routable — and the feed's own
        # (account-independent) session was never opened either.
        assert system._venue_manager.online_records() == []
        data_connector.connect.assert_not_called()
        # The top-gate refuses BEFORE reconcile: the coordinator is never even built, so
        # its run_startup_reconcile (venue link + baseline guard) never runs (WR-03).
        system._build_reconciliation_coordinator.assert_not_called()
    finally:
        system.stop()


def test_healthy_start_still_runs_session_init_when_no_durable_halt(provisioned_okx) -> None:
    """The top-gate is a no-op with NO durable halt — session init + venue I/O still run.

    Control arm: with no unresolved durable record the moved gate falls through, so a normal
    start() proceeds through ``_initialize_live_session`` and the venue handshake exactly as
    before. Proves the D-20 move did not accidentally short-circuit a healthy start.
    """
    system = LiveTradingSystem.for_exchange("okx")
    # No durable store -> the gate is skipped entirely.
    system._safety._halt_record_store = None

    # The account's session is pre-built and stubbed, so start() runs the REAL bring-up
    # over it: the real recipe, the real identity guard, the real routing write. The data
    # adapter's own session is stubbed the same way — start() opens it for the candle arm.
    connector = stub_okx_session(system)
    stub_data_session(system)
    system.feed.warmup = MagicMock(name="feed.warmup")
    # The venue-account snapshot is now per PORTFOLIO. This system has no portfolios, so
    # the reconcile is a clean skip — spy the coordinator to prove it still RAN (the
    # top-gate did not short-circuit it) rather than asserting on a facade account field
    # that no longer exists.
    reconcile_spy = MagicMock(name="run_startup_reconcile")
    system._build_reconciliation_coordinator = MagicMock(
        return_value=SimpleNamespace(run_startup_reconcile=reconcile_spy))

    try:
        started = system.start()
        assert started is True
        assert system.get_status()["status"] == SystemStatus.RUNNING.value
        # The venue handshake ran (the top-gate did not short-circuit a healthy start):
        # the session opened, the adapter came up connected, and the pair is routable.
        connector.connect.assert_called_once()
        record = system._venue_manager.online_records()[0]
        assert record.adapter.is_connected() is True
        assert system.execution_handler.exchanges[("okx", record.spec.account_id)] \
            is record.adapter
        reconcile_spy.assert_called_once()
    finally:
        system.stop()
