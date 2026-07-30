"""StreamRecoveryHandler.on_reconnect — engine-thread resume I/O (SAFE-04 / D-12 / D-28).

Unit coverage for the reconnect-resume orchestration in
``StreamRecoveryHandler.on_reconnect`` and its ``_all_venue_streams_healthy`` gate.

Locks the contract with fakes (no socket, no live stack):

- happy path — every wired arm healthy → catch-up BEFORE snapshot BEFORE
  ``safety.resume_submission`` (the ordering + the health-gate clear);
- a still-down arm leaves the pause in place — NO resume;
- a snapshot / catch-up ``Exception`` STAYS PAUSED, raises a CRITICAL alert, and does NOT
  halt (no failure counter, no escalation);
- guard-clausing on absent arms (a non-OKX wiring resumes cleanly);
- not-paused → an early return before any venue I/O.

ONE enumeration drives all of it: the account manager's online records. Each record's
execution ADAPTER is what gets the missed-fill catch-up, the REST snapshot AND the health
check, so there is no second mirrored container that can be empty while accounts are
online.

CF-2 is asserted here too at the source level: ``on_reconnect`` never calls
``backfill_on_resume`` (that ring backfill is loop-native, not this engine-thread path).
"""

import inspect
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from itrader.core.enums import ErrorSeverity
from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.trading_system.safety.stream_recovery_handler import (
    StreamRecoveryHandler,
)


class _FakeSafety:
    """Minimal SafetyController stand-in — pause flag, resume recorder, halt tripwire.

    ``halt`` is present but must never be called: a failed resume snapshot is a
    reversible quiesce retried on the next stream-up, and a halt has no legal exit except
    an operator reset. Recording it here is what makes "does not escalate" falsifiable.
    """

    def __init__(self, *, paused: bool) -> None:
        self._paused = paused
        self.resume_calls = 0
        self.halt_calls: List[Any] = []

    def is_submission_paused(self) -> bool:
        return self._paused

    def resume_submission(self) -> None:
        self.resume_calls += 1
        self._paused = False

    def halt(self, reason: Any) -> None:
        self.halt_calls.append(reason)


class _FakeAdapter:
    """Execution-adapter stand-in — the ONE arm that recovers, snapshots and reports health.

    All three jobs live on the same object because the adapter owns the authenticated
    session, so it is the only thing that can read the venue. The shared ``order_log`` is
    what pins catch-up BEFORE snapshot: the snapshot's balance/position picture must
    already reflect a fill recovered from the downtime, so the reverse order would resume
    on a stale picture.
    """

    def __init__(self, *, order_log: List[str], healthy: bool = True,
                 catch_up_raises: bool = False,
                 snapshot_raises: bool = False) -> None:
        self._order_log = order_log
        self._healthy = healthy
        self._catch_up_raises = catch_up_raises
        self._snapshot_raises = snapshot_raises

    def catch_up_missed_fills(self) -> None:
        self._order_log.append("catch_up")
        if self._catch_up_raises:
            raise RuntimeError("simulated catch-up failure")

    def snapshot(self) -> AccountSnapshot:
        self._order_log.append("snapshot")
        if self._snapshot_raises:
            raise RuntimeError("simulated snapshot failure")
        return AccountSnapshot.empty()

    def is_streaming_healthy(self) -> bool:
        return self._healthy


class _FakeProvider:
    """Feed data-provider stand-in — reports candle-stream health."""

    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    def is_streaming_healthy(self) -> bool:
        return self._healthy


class _RecordingAlertSink:
    """CRITICAL-alert egress double — records every ``ErrorEvent`` handed to it."""

    def __init__(self) -> None:
        self.alerts: List[Any] = []

    def alert(self, event: Any) -> None:
        self.alerts.append(event)


def _records(*adapters: Any, connector: Optional[Any] = None) -> List[Any]:
    """Online-account records, one per adapter, each carrying a live connector.

    ``record.connector is not None`` is the streaming discriminator — a paper account has
    no streams to recover and no venue to snapshot — so a non-None placeholder is what
    marks a record as live. Passing the SAME adapter twice is legal here on purpose: the
    handler must de-duplicate rather than assume the composition invariant.
    """
    return [
        SimpleNamespace(
            spec=SimpleNamespace(venue_name="okx", account_id=f"acct-{index}"),
            connector=connector if connector is not None else object(),
            adapter=adapter,
        )
        for index, adapter in enumerate(adapters)
    ]


def test_resume_happy_path_catchup_then_snapshot_then_resume() -> None:
    """All arms healthy → catch-up BEFORE snapshot BEFORE resume."""
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(_FakeAdapter(order_log=order_log)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 1
    assert safety.is_submission_paused() is False


def test_resume_stays_paused_while_exchange_arm_down() -> None:
    """A still-down exchange arm keeps the pause in place — NO resume."""
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(
            _FakeAdapter(order_log=order_log, healthy=False)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # The blocking I/O still ran (recovering fills while paused is correct), but the
    # gate refused resume because one arm is unhealthy.
    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_while_data_arm_down() -> None:
    """Symmetric: a still-down candle arm keeps the pause in place — NO resume.

    The ONE data adapter is read through the injected ``feed_provider`` callable rather
    than off any account record — it owns its own session, so its health is an independent
    arm of the compound gate.
    """
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    down_provider = _FakeProvider(healthy=False)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(_FakeAdapter(order_log=order_log)),
        feed_provider=lambda: down_provider,
    )

    handler.on_reconnect()

    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_on_snapshot_exception() -> None:
    """A snapshot Exception stays paused and does NOT resume (no escalation)."""
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(
            _FakeAdapter(order_log=order_log, snapshot_raises=True)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # Catch-up ran, snapshot raised → caught, stay paused, never resume.
    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_resume_stays_paused_on_catchup_exception() -> None:
    """A catch-up Exception stays paused, does NOT resume, and skips the snapshot."""
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(
            _FakeAdapter(order_log=order_log, catch_up_raises=True)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # Catch-up raised first → snapshot never reached, stay paused.
    assert order_log == ["catch_up"]
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_failed_snapshot_raises_a_critical_alert_and_does_not_halt() -> None:
    """A failed resume snapshot is CRITICAL-alerted, stays PAUSED, and never halts.

    Both halves matter. Without the alert, a quiesced engine looks exactly like a quiet
    one — the operator sees no submissions and no reason. With a halt instead of a pause,
    a condition that routinely clears on the next stream-up would demand an operator
    reset, because a halt has no other legal exit.
    """
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    alert_sink = _RecordingAlertSink()
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(
            _FakeAdapter(order_log=order_log, snapshot_raises=True)),
        feed_provider=lambda: _FakeProvider(healthy=True),
        alert_sink=alert_sink,
    )

    handler.on_reconnect()

    assert len(alert_sink.alerts) == 1
    event = alert_sink.alerts[0]
    assert event.severity is ErrorSeverity.CRITICAL
    assert event.source == "stream_recovery"
    assert event.operation == "on_reconnect"
    # The failure type is named; the connector payload is not, so nothing from the venue
    # session can leak out through the alert egress.
    assert event.error_type == "RuntimeError"
    assert "simulated snapshot failure" not in event.error_message
    # Reversible quiesce, not a latched freeze.
    assert safety.halt_calls == []
    assert safety.resume_calls == 0
    assert safety.is_submission_paused() is True


def test_every_accounts_arm_is_caught_up_and_gates_the_resume() -> None:
    """Catch-up and the health gate cover EVERY online account, not just a primary.

    Two accounts; the SECOND one's fill stream is still down. Under a single scalar arm
    only the first was reached, so the second account's fills were never recovered and its
    down stream never blocked resume — submission would clear while the engine was blind
    to half the venue. A partially-recovered engine is worse than an unrecovered one
    because the surviving arm looks healthy.
    """
    order_log: List[str] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(
            _FakeAdapter(order_log=order_log),
            _FakeAdapter(order_log=order_log, healthy=False)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    # BOTH accounts were caught up before EITHER was snapshotted: the catch-up pass
    # completes across accounts first, so no snapshot reads a venue whose recovered fills
    # have not landed yet.
    assert order_log == ["catch_up", "catch_up", "snapshot", "snapshot"]
    # ...and the second account's down stream held the pause.
    assert safety.resume_calls == 0


def test_a_paper_record_is_never_recovered_or_snapshotted() -> None:
    """A record with NO connector has no streams to recover and no venue to read.

    It must also not block the resume: treating an absent venue session as an unhealthy
    arm would leave a mixed paper/live engine permanently paused.
    """
    order_log: List[str] = []
    paper_adapter = _FakeAdapter(order_log=order_log, healthy=False)
    paper_record = SimpleNamespace(
        spec=SimpleNamespace(venue_name="paper", account_id="acct-paper"),
        connector=None,
        adapter=paper_adapter,
    )
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(safety=safety, accounts=lambda: [paper_record])

    handler.on_reconnect()

    assert order_log == []
    assert safety.resume_calls == 1


def test_a_shared_adapter_is_recovered_once() -> None:
    """Dedupe by IDENTITY — one adapter reached through two records is used once.

    Adapters are not hashable-by-value, so identity is the only correct key; a duplicate
    would double-snapshot one real venue account on every reconnect.
    """
    order_log: List[str] = []
    shared = _FakeAdapter(order_log=order_log)
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(
        safety=safety, accounts=lambda: _records(shared, shared))

    handler.on_reconnect()

    assert order_log == ["catch_up", "snapshot"]


def test_resume_guard_clauses_absent_arms() -> None:
    """A non-OKX wiring (no records, no data arm) resumes cleanly — absent ⇒ healthy."""
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(safety=safety)

    handler.on_reconnect()

    assert safety.resume_calls == 1
    assert safety.is_submission_paused() is False


def test_on_reconnect_noop_when_not_paused() -> None:
    """Not paused → early return before any venue I/O (no catch-up, no snapshot, no resume)."""
    order_log: List[str] = []
    safety = _FakeSafety(paused=False)
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: _records(_FakeAdapter(order_log=order_log)),
        feed_provider=lambda: _FakeProvider(healthy=True),
    )

    handler.on_reconnect()

    assert order_log == []
    assert safety.resume_calls == 0


def test_accounts_are_read_at_use_time_not_captured() -> None:
    """An account brought online AFTER construction is still recovered.

    The callable is the point: a build-time container goes stale the moment an account
    comes online at runtime, and a stale-empty container makes this handler silently
    recover nothing while reporting every arm healthy.
    """
    order_log: List[str] = []
    live: List[Any] = []
    safety = _FakeSafety(paused=True)
    handler = StreamRecoveryHandler(safety=safety, accounts=lambda: live)

    live.extend(_records(_FakeAdapter(order_log=order_log)))
    handler.on_reconnect()

    assert order_log == ["catch_up", "snapshot"]
    assert safety.resume_calls == 1


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
