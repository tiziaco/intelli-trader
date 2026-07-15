"""WR-02 — a pre-submit-throttle-REFUSED ORDER is counted as processed, NOT executed.

``LiveRunner._run_loop`` meters the pre-submit throttle AHEAD of the dispatch gate: an
ORDER the throttle REFUSES (``pre_submit`` returns ``False``) emitted only a
``FillEvent(REFUSED)`` and NEVER executed, so the loop SKIPS the dispatch gate for it.
The bug (WR-02): the loop still called ``_update_stats('ORDER')`` unconditionally, which
bumps ``orders_executed`` — over-reporting executions in ``get_status()['statistics']``.

The fix routes a rejected ORDER to a dedicated ``on_order_throttle_rejected`` hook
(``_stats['orders_throttle_rejected'] += 1`` + ``events_processed``) instead of
``_update_stats`` (which would bump ``orders_executed``). These tests drive the REAL loop
with the REAL facade accounting methods (re-bound onto a light host) and lock:

* a rejected ORDER leaves ``orders_executed`` at 0 and lands on
  ``orders_throttle_rejected`` (counted as processed, never executed); the dispatch gate
  is never reached;
* a non-rejected ORDER still bumps ``orders_executed`` via ``_update_stats`` and never
  touches the throttle-rejected counter (no regression on the healthy path).

Fully synchronous (no thread, no network): a one-shot bus serves a single event then
stops the loop. 4-space indentation (``tests/unit/*``); NO ``__init__.py`` in this dir
(auto-memory: same-named-package collision hazard).
"""

import queue
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from itrader.core.enums import EventType
from itrader.trading_system.live_runner import LiveRunner
from itrader.trading_system.live_trading_system import LiveTradingSystem


class _StatsHost:
    """A light host carrying the REAL facade stats dict + accounting methods.

    Re-binds ``LiveTradingSystem._update_stats`` / ``_on_order_throttle_rejected`` onto a
    minimal object so the tests exercise the ACTUAL accounting logic (not a re-implementation)
    without constructing the full live facade / venue arms.
    """

    _update_stats = LiveTradingSystem._update_stats
    _on_order_throttle_rejected = LiveTradingSystem._on_order_throttle_rejected

    def __init__(self) -> None:
        self._stats = {
            'events_processed': 0,
            'orders_executed': 0,
            'orders_throttle_rejected': 0,
            'last_event_time': None,
        }
        self._stats_lock = threading.Lock()


class _OneShotBus:
    """A bus double serving a single event, then stopping the loop and going empty."""

    def __init__(self, event, stop_event: threading.Event) -> None:
        self._event = event
        self._stop_event = stop_event
        self._served = False

    def get(self, timeout=None):
        if not self._served:
            self._served = True
            return self._event
        # Second poll: latch the loop stop and report an empty queue so the loop exits.
        self._stop_event.set()
        raise queue.Empty


def _build_runner(*, event, pre_submit, host, dispatch_gate):
    stop_event = threading.Event()
    return LiveRunner(
        bus=_OneShotBus(event, stop_event),
        stop_event=stop_event,
        worker_supervisor=MagicMock(name='worker_supervisor'),
        dispatch_gate=dispatch_gate,
        update_stats=host._update_stats,
        record_bar_metrics=lambda _event: None,
        pre_submit=pre_submit,
        queue_timeout=0.01,
        max_idle_time=999.0,
        on_order_throttle_rejected=host._on_order_throttle_rejected,
    )


def test_throttle_rejected_order_is_processed_not_executed() -> None:
    """A throttle-REFUSED ORDER bumps orders_throttle_rejected, never orders_executed (WR-02)."""
    host = _StatsHost()
    order = SimpleNamespace(type=EventType.ORDER)
    dispatch_gate = MagicMock(name='dispatch_gate')
    # pre_submit returns False -> the throttle REFUSED this ORDER.
    runner = _build_runner(
        event=order, pre_submit=lambda _e: False, host=host, dispatch_gate=dispatch_gate)

    runner._run_loop()

    # The rejected order NEVER reached the dispatch gate...
    dispatch_gate.assert_not_called()
    # ...and NEVER counted as executed — it is processed + throttle-rejected only.
    assert host._stats['orders_executed'] == 0
    assert host._stats['orders_throttle_rejected'] == 1
    assert host._stats['events_processed'] == 1


def test_non_rejected_order_still_counts_as_executed() -> None:
    """A throttle-ALLOWED ORDER bumps orders_executed and leaves the reject counter at 0."""
    host = _StatsHost()
    order = SimpleNamespace(type=EventType.ORDER)
    dispatch_gate = MagicMock(name='dispatch_gate')
    # pre_submit returns True -> the throttle ALLOWED this ORDER.
    runner = _build_runner(
        event=order, pre_submit=lambda _e: True, host=host, dispatch_gate=dispatch_gate)

    runner._run_loop()

    dispatch_gate.assert_called_once_with(order)
    assert host._stats['orders_executed'] == 1
    assert host._stats['orders_throttle_rejected'] == 0
    assert host._stats['events_processed'] == 1
