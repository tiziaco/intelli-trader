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
    system._halt_record_store = _UnresolvedHaltStore("drift")

    # Spy/stub EVERY call start() could make before the refusal. On the fixed (top-gate)
    # code none of these run; on the pre-fix (late-gate) code they all run before refusing.
    system._initialize_live_session = MagicMock(name="_initialize_live_session")
    system._okx_connector.connect = MagicMock(name="connector.connect")
    system.feed.warmup = MagicMock(name="feed.warmup")
    system._okx_data_provider.start_stream = MagicMock(name="provider.start_stream")
    system._okx_exchange.connect = MagicMock(
        name="exchange.connect", return_value=SimpleNamespace(success=True))
    system._venue_account = MagicMock(name="venue_account")
    system._link_venue_account_to_portfolios = MagicMock(name="_link_venue_account")
    system._run_session_baseline_guard = MagicMock(name="_run_session_baseline_guard")

    try:
        started = system.start()

        # Refused — and re-latched HALTED from the durable record (in-process, no re-halt).
        assert started is False
        assert system.get_status()["status"] == SystemStatus.HALTED.value

        # D-20: the refusal is at the TOP — ZERO session init and ZERO venue I/O ran.
        system._initialize_live_session.assert_not_called()
        system._okx_connector.connect.assert_not_called()
        system.feed.warmup.assert_not_called()
        system._okx_data_provider.start_stream.assert_not_called()
        system._okx_exchange.connect.assert_not_called()
        system._venue_account.snapshot.assert_not_called()
        system._venue_account.start_streaming.assert_not_called()
        system._link_venue_account_to_portfolios.assert_not_called()
        system._run_session_baseline_guard.assert_not_called()
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
    system._halt_record_store = None

    system._okx_connector.connect = MagicMock(name="connector.connect")
    system.feed.warmup = MagicMock(name="feed.warmup")
    system._okx_data_provider.start_stream = MagicMock(name="provider.start_stream")
    system._okx_exchange.connect = MagicMock(
        name="exchange.connect", return_value=SimpleNamespace(success=True))
    system._venue_account = MagicMock(name="venue_account")
    system._link_venue_account_to_portfolios = MagicMock(name="_link_venue_account")
    system._run_session_baseline_guard = MagicMock(name="_run_session_baseline_guard")

    try:
        started = system.start()
        assert started is True
        assert system.get_status()["status"] == SystemStatus.RUNNING.value
        # The venue handshake ran (the top-gate did not short-circuit a healthy start).
        system._okx_connector.connect.assert_called_once()
        system._okx_exchange.connect.assert_called_once()
        system._venue_account.snapshot.assert_called_once()
    finally:
        system.stop()
