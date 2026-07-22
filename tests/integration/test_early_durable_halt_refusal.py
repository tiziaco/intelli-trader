"""05.3-08 Task 1 (D-20 / WR-01) — a durably-HALTED start() refuses BEFORE any venue I/O.

Phase 05.2-06 (D-10) landed a DURABLE halt latch: ``start()`` refuses RUNNING while an
unresolved durable record exists. But the refusal gate was sequenced LATE — after the full
OKX handshake (``connect`` + ``load_markets``), the feed warmup + ``start_stream``, the
order-arm stream spawn, the ``VenueAccount.snapshot()``, AND the state-mutating
``VenueReconciler.reconcile()``. A durably-HALTED engine that should stay inert therefore
performed real venue I/O and a state-mutating reconcile before finally refusing (WR-01).

D-20 moves the durable-halt refusal to the TOP of ``start()`` — right after
``_update_status(STARTING)`` and BEFORE any ``connect``/``snapshot``/stream spawn/reconcile.
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


def _set_okx_env(monkeypatch) -> None:
    """Dummy OKX credential triple so the okx arm's ``OkxSettings()`` constructs offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


class _UnresolvedHaltStore:
    """A durable halt store double whose record is ALWAYS unresolved (the restart latch).

    Only the surface ``start()``'s durable-refusal gate touches: ``has_unresolved`` /
    ``get_unresolved``. ``record_halt`` is a no-op — the gate re-latches in-process via
    ``_update_status`` (NOT ``halt()``), so no second durable record is ever written.
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
            "via _update_status, never a second durable write (D-20).")

    def resolve_all(self) -> None:
        pass

    def dispose(self) -> None:
        pass


def test_durably_halted_start_refuses_before_any_venue_io(monkeypatch) -> None:
    """A durably-halted ``start()`` refuses at the TOP with zero venue I/O (D-20/WR-01)."""
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    # P7 (§11b): the durable halt store + check_durable_halt_on_start live on the injected
    # SafetyController now — inject the always-unresolved double there.
    system._safety._halt_record_store = _UnresolvedHaltStore("drift")

    # Spy/stub EVERY call start() could make before the refusal. On the fixed (top-gate)
    # code none of these run; on the pre-fix (late-gate) code they all run before refusing.
    system._initialize_live_session = MagicMock(name="_initialize_live_session")
    # 11-09: the venue arms are reached through the PRIMARY account's lifecycle now (the
    # six facade scalars are gone). The venue ACCOUNT is no longer a facade field at all
    # — accounts live on portfolios — so the snapshot/start_streaming assertions below
    # are made against the coordinator that would have driven them.
    lifecycle = system._primary_lifecycle
    lifecycle.bundle.connector.connect = MagicMock(name="connector.connect")
    system.feed.warmup = MagicMock(name="feed.warmup")
    lifecycle.provider.start_stream = MagicMock(name="provider.start_stream")
    lifecycle.bundle.exchange.connect = MagicMock(
        name="exchange.connect", return_value=SimpleNamespace(success=True))
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
        lifecycle.bundle.connector.connect.assert_not_called()
        system.feed.warmup.assert_not_called()
        lifecycle.provider.start_stream.assert_not_called()
        lifecycle.bundle.exchange.connect.assert_not_called()
        # The top-gate refuses BEFORE reconcile: the coordinator is never even built, so
        # its run_startup_reconcile (venue link + baseline guard) never runs (WR-03).
        system._build_reconciliation_coordinator.assert_not_called()
    finally:
        system.stop()


def test_healthy_start_still_runs_session_init_when_no_durable_halt(monkeypatch) -> None:
    """The top-gate is a no-op with NO durable halt — session init + venue I/O still run.

    Control arm: with no unresolved durable record the moved gate falls through, so a normal
    start() proceeds through ``_initialize_live_session`` and the venue handshake exactly as
    before. Proves the D-20 move did not accidentally short-circuit a healthy start.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    # No durable store -> the gate is skipped entirely (in-memory fallback).
    system._safety._halt_record_store = None

    # 11-09: reached through the primary lifecycle (the facade scalars are deleted).
    lifecycle = system._primary_lifecycle
    lifecycle.bundle.connector.connect = MagicMock(name="connector.connect")
    system.feed.warmup = MagicMock(name="feed.warmup")
    lifecycle.provider.start_stream = MagicMock(name="provider.start_stream")
    lifecycle.bundle.exchange.connect = MagicMock(
        name="exchange.connect", return_value=SimpleNamespace(success=True))
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
        # The venue handshake ran (the top-gate did not short-circuit a healthy start).
        lifecycle.bundle.connector.connect.assert_called_once()
        lifecycle.bundle.exchange.connect.assert_called_once()
        reconcile_spy.assert_called_once()
    finally:
        system.stop()
