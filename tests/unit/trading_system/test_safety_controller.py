"""SafetyController pure-state-machine tests (SAFE-01/02, Plan 07-03).

Constructs ``SafetyController`` with fakes (a fake bus, an in-memory halt store,
a recording dispatch fn) and pins the byte-moved safety latch:

  1. ``update_status`` rejects an illegal transition (STOPPED -> RUNNING) and
     leaves the status unchanged (D-05 latch).
  2. ``halt`` is winner-only — a second halt does NOT re-alert or re-record and
     the first reason wins (WR-01 idempotent check-and-set).
  3. ``reset_halt`` is the sole off-table HALTED exit (force=True + resolve_all).
  4. pause -> deferred-protective append -> ``resume_submission`` replays the
     batch through the injected dispatch fn (D-14).
  5. ``check_durable_halt_on_start`` with an unresolved record re-latches HALTED
     via ``update_status`` and writes NO second durable record (D-10/SAFE-02).

Fully offline: no ``LiveTradingSystem``, no venue, no network. New test dir is
package-less (no ``__init__.py``) to avoid the full-suite package-collision.
Folder-derived ``unit`` marker.
"""

from datetime import datetime, UTC
from types import SimpleNamespace
from typing import Any, List, NamedTuple, Optional

import pytest

from itrader.core.enums import (
    ErrorSeverity,
    EventType,
    OrderCommand,
    SystemStatus,
)
from itrader.events_handler.events import ErrorEvent
from itrader.trading_system.safety.safety_controller import (
    SafetyController,
    _DEFERRED_PROTECTIVE_OVERFLOW_REASON,
    _DEFERRED_PROTECTIVE_REPLAY_MAX,
)

pytestmark = pytest.mark.unit


class _FakeBus:
    """A minimal bus recording every ``put`` (the CRITICAL ErrorEvent egress)."""

    def __init__(self) -> None:
        self.events: List[Any] = []

    def put(self, event: Any) -> None:
        self.events.append(event)


class _HaltRecord(NamedTuple):
    reason: str
    created_at: datetime


class _FakeHaltStore:
    """An in-memory durable-halt store recording record/resolve calls."""

    def __init__(self, unresolved: Optional[_HaltRecord] = None) -> None:
        self.record_calls: List[Any] = []
        self.resolve_calls = 0
        self._unresolved = unresolved

    def record_halt(self, reason: str, at: datetime) -> None:
        self.record_calls.append((reason, at))
        self._unresolved = _HaltRecord(reason=reason, created_at=at)

    def has_unresolved(self) -> bool:
        return self._unresolved is not None

    def get_unresolved(self) -> Optional[_HaltRecord]:
        return self._unresolved

    def resolve_all(self) -> None:
        self.resolve_calls += 1
        self._unresolved = None


def _controller(
    *,
    halt_store: Optional[_FakeHaltStore] = None,
    dispatched: Optional[List[Any]] = None,
    deferred_maxlen: int = _DEFERRED_PROTECTIVE_REPLAY_MAX,
) -> SafetyController:
    """A SafetyController wired to fakes; ``dispatched`` records replayed orders."""
    bus = _FakeBus()
    controller = SafetyController(
        bus=bus,
        halt_record_store=halt_store,
        dispatch_fn=(dispatched.append if dispatched is not None else None),
        deferred_maxlen=deferred_maxlen,
    )
    # Expose the fake bus so tests can assert the CRITICAL egress.
    controller._test_bus = bus  # type: ignore[attr-defined]
    return controller


def _critical_halt_events(controller: SafetyController) -> List[Any]:
    """The CRITICAL EngineHalted ErrorEvents the controller put on the fake bus."""
    bus = controller._test_bus  # type: ignore[attr-defined]
    return [
        e for e in bus.events
        if isinstance(e, ErrorEvent) and e.severity == ErrorSeverity.CRITICAL
    ]


def test_update_status_refuses_illegal_transition() -> None:
    """STOPPED -> RUNNING is not in the table — refused, status unchanged (D-05)."""
    controller = _controller()
    assert controller._status == SystemStatus.STOPPED

    changed = controller.update_status(SystemStatus.RUNNING)

    assert changed is False
    assert controller._status == SystemStatus.STOPPED


def test_update_status_same_state_is_noop() -> None:
    """A same-state call is an idempotent no-op returning False."""
    controller = _controller()
    assert controller.update_status(SystemStatus.STOPPED) is False


def test_halt_is_winner_only() -> None:
    """A second halt does NOT re-alert or re-record; the first reason wins (WR-01)."""
    store = _FakeHaltStore()
    controller = _controller(halt_store=store)

    controller.halt('drift')
    assert controller.is_halted() is True
    assert controller._halt_reason == 'drift'
    assert len(_critical_halt_events(controller)) == 1
    assert store.record_calls == [store.record_calls[0]]
    assert len(store.record_calls) == 1

    # Re-entrant halt with a different reason — idempotent no-op.
    controller.halt('connector-fatal')
    assert controller._halt_reason == 'drift'  # first reason wins
    assert len(_critical_halt_events(controller)) == 1  # no second alert
    assert len(store.record_calls) == 1  # no second durable write


def test_halt_emits_one_critical_error_event() -> None:
    """halt() emits exactly one CRITICAL EngineHalted ErrorEvent (D-06)."""
    controller = _controller(halt_store=_FakeHaltStore())
    controller.halt('reconciliation-unresolved')
    events = _critical_halt_events(controller)
    assert len(events) == 1
    assert events[0].error_type == 'EngineHalted'
    assert events[0].operation == 'halt'


def test_reset_halt_is_the_sole_off_table_exit() -> None:
    """reset_halt() clears a latched HALTED and resolves the durable record (D-05)."""
    store = _FakeHaltStore()
    controller = _controller(halt_store=store)
    controller.halt('drift')

    # No lifecycle transition can leave HALTED (terminal in the table).
    assert controller.update_status(SystemStatus.RUNNING) is False
    assert controller.is_halted() is True

    cleared = controller.reset_halt()
    assert cleared is True
    assert controller._status == SystemStatus.STOPPED
    assert controller._halt_reason is None
    assert store.resolve_calls == 1

    # A second reset is a no-op (not HALTED).
    assert controller.reset_halt() is False


def test_pause_defer_resume_replays_batch() -> None:
    """pause -> deferred append -> resume replays the batch via dispatch_fn (D-14)."""
    dispatched: List[Any] = []
    controller = _controller(dispatched=dispatched)

    controller.pause_submission('paused-on-disconnect')
    assert controller.is_submission_paused() is True

    protective_a = object()
    protective_b = object()
    controller._deferred_protective.append(protective_a)
    controller._deferred_protective.append(protective_b)

    # Nothing dispatched while paused.
    assert dispatched == []

    controller.resume_submission()

    assert controller.is_submission_paused() is False
    assert dispatched == [protective_a, protective_b]
    assert len(controller._deferred_protective) == 0


def test_pause_is_noop_while_halted() -> None:
    """A terminal HALT supersedes a pause — pause_submission is a no-op while HALTED."""
    controller = _controller(halt_store=_FakeHaltStore())
    controller.halt('drift')
    controller.pause_submission('paused-on-disconnect')
    assert controller.is_submission_paused() is False


def test_check_durable_halt_relatches_without_second_record() -> None:
    """An unresolved durable record re-latches HALTED via update_status, no re-write (SAFE-02)."""
    store = _FakeHaltStore(
        unresolved=_HaltRecord(reason='connector-fatal', created_at=datetime.now(UTC)))
    controller = _controller(halt_store=store)

    refused = controller.check_durable_halt_on_start()

    assert refused is True
    assert controller.is_halted() is True
    assert controller._halt_reason == 'connector-fatal'
    # Re-latched via update_status — NOT halt() — so NO second durable record.
    assert store.record_calls == []
    # And no CRITICAL alert was emitted (update_status path, not halt()).
    assert _critical_halt_events(controller) == []


def test_check_durable_halt_clean_store_is_noop() -> None:
    """A clean durable store is a no-op returning False."""
    controller = _controller(halt_store=_FakeHaltStore())
    assert controller.check_durable_halt_on_start() is False
    assert controller._status == SystemStatus.STOPPED


def test_check_durable_halt_without_store_is_noop() -> None:
    """No durable store (in-memory fallback) — a no-op returning False."""
    controller = _controller(halt_store=None)
    assert controller.check_durable_halt_on_start() is False
    assert controller._status == SystemStatus.STOPPED


# -- gate_and_dispatch + D-11 overflow (Task 2) ---------------------------------

def _order(*, command: OrderCommand = OrderCommand.NEW, parent: Any = None) -> Any:
    """An ORDER-typed event fake; ``parent`` set marks a protective bracket child."""
    return SimpleNamespace(
        type=EventType.ORDER, command=command, parent_order_id=parent)


def _signal() -> Any:
    """A raw SIGNAL-typed event fake (no command, no parent)."""
    return SimpleNamespace(type=EventType.SIGNAL)


def test_gate_passes_through_when_not_gated() -> None:
    """When neither halted nor paused, every event passes straight through."""
    dispatched: List[Any] = []
    controller = _controller(dispatched=dispatched)
    entry = _order()
    controller.gate_and_dispatch(entry)
    assert dispatched == [entry]


def test_gate_cancel_always_dispatched_during_pause() -> None:
    """A CANCEL role ALWAYS passes the gate mid-pause (risk-reducing, D-14)."""
    dispatched: List[Any] = []
    controller = _controller(dispatched=dispatched)
    controller.pause_submission('paused-on-disconnect')
    cancel = _order(command=OrderCommand.CANCEL)
    controller.gate_and_dispatch(cancel)
    assert dispatched == [cancel]


def test_gate_protective_deferred_during_pause() -> None:
    """A PROTECTIVE order is deferred (not dispatched) mid-pause (D-14)."""
    dispatched: List[Any] = []
    controller = _controller(dispatched=dispatched)
    controller.pause_submission('paused-on-disconnect')
    protective = _order(parent=object())
    controller.gate_and_dispatch(protective)
    assert dispatched == []
    assert list(controller._deferred_protective) == [protective]


def test_gate_entry_and_signal_suppressed_during_pause() -> None:
    """A fresh ENTRY order and a raw SIGNAL stay suppressed mid-pause (D-14)."""
    dispatched: List[Any] = []
    controller = _controller(dispatched=dispatched)
    controller.pause_submission('paused-on-disconnect')
    controller.gate_and_dispatch(_order(parent=None))
    controller.gate_and_dispatch(_signal())
    assert dispatched == []
    assert len(controller._deferred_protective) == 0


def test_deferred_protective_overflow_escalates_to_halt() -> None:
    """D-11: overflowing the deferred queue HALTs + CRITICAL, not silent drop-oldest."""
    dispatched: List[Any] = []
    controller = _controller(
        halt_store=_FakeHaltStore(), dispatched=dispatched, deferred_maxlen=3)
    controller.pause_submission('paused-on-disconnect')

    # Fill the bounded queue exactly to maxlen (all deferred, no halt).
    for _ in range(3):
        controller.gate_and_dispatch(_order(parent=object()))
    assert controller.is_halted() is False
    assert len(controller._deferred_protective) == 3

    # The maxlen+1-th protective order overflows → escalate to HALT + CRITICAL.
    controller.gate_and_dispatch(_order(parent=object()))

    assert controller.is_halted() is True
    assert controller._halt_reason == _DEFERRED_PROTECTIVE_OVERFLOW_REASON
    critical = [
        e for e in controller._test_bus.events  # type: ignore[attr-defined]
        if isinstance(e, ErrorEvent) and e.severity == ErrorSeverity.CRITICAL
    ]
    assert len(critical) == 1
