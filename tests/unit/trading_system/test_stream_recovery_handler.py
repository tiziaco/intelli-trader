"""StreamRecoveryHandler.on_reconnect — engine-thread resume I/O (SAFE-04 / D-12 / D-28).

Unit coverage for the byte-moved reconnect-resume orchestration extracted from
``LiveTradingSystem._maybe_resume_after_reconnect`` (607-666) +
``_all_venue_streams_healthy`` (668-684) into ``StreamRecoveryHandler`` (Plan 04).

Locks the contract with fakes (no socket, no live stack):

- happy path — every wired arm healthy → catch-up BEFORE snapshot BEFORE
  ``safety.resume_submission`` (the D-25 ordering + the D-28 gate clear);
- a still-down arm leaves the pause in place — NO resume (D-28/WR-03);
- a snapshot / catch-up ``Exception`` STAYS PAUSED and does NOT resume (D-12 —
  no failure-counter / halt-escalation);
- guard-clausing on ``None`` arms (a non-OKX wiring resumes cleanly);
- not-paused → an early return before any venue I/O.

CF-2 is asserted here too at the source level: ``on_reconnect`` never calls
``backfill_on_resume`` (that ring backfill is loop-native, not this engine-thread
path).
"""

import inspect

import pytest

from itrader.trading_system.safety.stream_recovery_handler import (
    StreamRecoveryHandler,
)


class _FakeSafety:
    """Minimal SafetyController stand-in — pause flag + resume recorder."""

    def __init__(self, *, paused: bool) -> None:
        self._paused = paused
        self.resume_calls = 0

    def is_submission_paused(self) -> bool:
        return self._paused

    def resume_submission(self) -> None:
        self.resume_calls += 1
        self._paused = False


class _FakeExchange:
    """OKX exchange arm stand-in — records catch-up ordering + reports health."""

    def __init__(self, *, healthy: bool, order_log: list[str],
                 raises: bool = False) -> None:
        self._healthy = healthy
        self._order_log = order_log
        self._raises = raises

    def catch_up_missed_fills(self) -> None:
        self._order_log.append("catch_up")
        if self._raises:
            raise RuntimeError("simulated catch-up failure")

    def is_streaming_healthy(self) -> bool:
        return self._healthy


class _FakeAccount:
    """Venue-account stand-in — records snapshot ordering."""

    def __init__(self, *, order_log: list[str], raises: bool = False) -> None:
        self._order_log = order_log
        self._raises = raises

    def snapshot(self) -> None:
        self._order_log.append("snapshot")
        if self._raises:
            raise RuntimeError("simulated snapshot failure")


class _FakeProvider:
    """OKX data-provider arm stand-in — reports candle-stream health."""

    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    def is_streaming_healthy(self) -> bool:
        return self._healthy


def test_resume_happy_path_catchup_then_snapshot_then_resume() -> None:
    """All arms healthy → catch-up BEFORE snapshot BEFORE resume (D-25 + D-28 gate)."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=True, order_log=order_log),
        venue_account=_FakeAccount(order_log=order_log),
        okx_data_provider=_FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 1
    assert safety.is_submission_paused() is False


def test_resume_stays_paused_while_exchange_arm_down() -> None:
    """A still-down exchange arm keeps the pause in place — NO resume (D-28/WR-03)."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=False, order_log=order_log),
        venue_account=_FakeAccount(order_log=order_log),
        okx_data_provider=_FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # The blocking I/O still ran (recovering fills while paused is correct), but the
    # gate refused resume because one arm is unhealthy.
    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_while_data_arm_down() -> None:
    """Symmetric: a still-down candle arm keeps the pause in place — NO resume."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=True, order_log=order_log),
        venue_account=_FakeAccount(order_log=order_log),
        okx_data_provider=_FakeProvider(healthy=False),
    )

    handler.on_reconnect()

    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_on_snapshot_exception_d12() -> None:
    """D-12: a snapshot Exception stays paused and does NOT resume (no escalation)."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=True, order_log=order_log),
        venue_account=_FakeAccount(order_log=order_log, raises=True),
        okx_data_provider=_FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # Catch-up ran, snapshot raised → caught, stay paused, never resume.
    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_on_catchup_exception_d12() -> None:
    """D-12: a catch-up Exception stays paused, does NOT resume, and skips snapshot."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=True, order_log=order_log, raises=True),
        venue_account=_FakeAccount(order_log=order_log),
        okx_data_provider=_FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # Catch-up raised first → snapshot never reached, stay paused.
    assert order_log == ["catch_up"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_guard_clauses_none_arms() -> None:
    """A non-OKX wiring (all venue arms None) resumes cleanly — absent ⇒ healthy."""
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(safety=safety)

    handler.on_reconnect()

    assert safety.resume_calls == 1
    assert safety.is_submission_paused() is False


def test_on_reconnect_noop_when_not_paused() -> None:
    """Not paused → early return before any venue I/O (no catch-up, no snapshot, no resume)."""
    order_log: list[str] = []
    safety = _FakeSafety(paused=False)
    handler = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=_FakeExchange(healthy=True, order_log=order_log),
        venue_account=_FakeAccount(order_log=order_log),
        okx_data_provider=_FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    assert order_log == []
    assert safety.resume_calls == 0


def test_on_reconnect_never_calls_backfill_on_resume_cf2() -> None:
    """CF-2 (source-level): on_reconnect body contains NO ring backfill call.

    The REST ring backfill is loop-native (connector loop via spawn_gap_backfill),
    never this engine-thread path — so the handler must never reference
    ``backfill_on_resume``.
    """
    src = inspect.getsource(StreamRecoveryHandler.on_reconnect)
    assert "backfill_on_resume" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x"]))
