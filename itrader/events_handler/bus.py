"""Two-tier event-bus substrate for the iTrader event system (D-09/D-10).

This module is a pure, import-inert transport substrate. It defines the
``EventBus`` structural interface plus two concrete implementations:

* ``FifoEventBus`` — a thin ``queue.Queue`` wrapper; the byte-exact backtest
  buffer (D-07). Its FIFO semantics are identical to the raw queue it replaces,
  so wiring it into the backtest path carries zero oracle risk.
* ``PriorityEventBus`` — a ``queue.PriorityQueue`` wrapper keyed by
  ``(tier, seq, event)`` so CONTROL-tier events (tier 0) preempt BUSINESS-tier
  events (tier 1) while preserving strict within-tier FIFO. Defined and
  unit-tested ONLY in Phase 2 (D-10/D-11): it is wired into no live path here.

Inertness discipline (D-09): this module imports only stdlib plus
``itrader.core.enums.event``. ``Event`` is a ``TYPE_CHECKING``-only import —
the events package pulls pandas at runtime, so it is kept off this substrate.
"""

import itertools
import queue
import threading
from collections import Counter
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from itrader.core.enums.event import EventType

if TYPE_CHECKING:
    # Annotation-only: the events package pulls pandas at runtime, so the
    # concrete Event never crosses this module's runtime import surface (D-09).
    from itrader.events_handler.events import Event


class EventTier(IntEnum):
    """Dequeue priority tier — int-comparable so it sorts as the first
    element of the ``(tier, seq, event)`` priority tuple.

    CONTROL (0) is dequeued before BUSINESS (1). BUSINESS is the default
    fall-through tier; only CONTROL is ever enumerated.
    """

    CONTROL = 0
    BUSINESS = 1


# BUSINESS is the default fall-through — only CONTROL is enumerated so the
# tiering stays robust to future EventType additions (never enumerate BUSINESS).
_CONTROL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.STREAM_STATE,
    EventType.CONNECTOR_FATAL,
    EventType.CONFIG_UPDATE,
    EventType.STRATEGY_COMMAND,
})


def _tier(event_type: EventType) -> EventTier:
    """Map an ``EventType`` to its dequeue tier (CONTROL if enumerated, else BUSINESS)."""
    return EventTier.CONTROL if event_type in _CONTROL_EVENT_TYPES else EventTier.BUSINESS


@runtime_checkable
class EventBus(Protocol):
    """Structural interface for the event transport substrate (D-09).

    A ``runtime_checkable`` ``Protocol`` (no ABC inheritance), mirroring the
    house read-model seam (``core.portfolio_read_model.PortfolioReadModel``).
    Both ``FifoEventBus`` and ``PriorityEventBus`` satisfy it structurally.
    """

    def put(self, event: "Event") -> None:
        ...

    def get(self, timeout: "float | None" = None) -> "Event":
        ...

    def get_nowait(self) -> "Event":
        ...

    def qsize(self) -> int:
        ...

    def empty(self) -> bool:
        ...

    def depth_by_tier(self) -> "dict[EventTier, int]":
        ...


class FifoEventBus:
    """Thin ``queue.Queue`` wrapper — the byte-exact backtest buffer (D-07).

    FIFO is tierless: every method delegates to the wrapped stdlib queue, so
    ``get_nowait`` raises ``queue.Empty`` unchanged. ``depth_by_tier`` reports
    a single BUSINESS bucket (monitoring-only — FIFO has no CONTROL tier).
    """

    def __init__(self) -> None:
        self._q: "queue.Queue[Event]" = queue.Queue()

    def put(self, event: "Event") -> None:
        self._q.put(event)

    def get(self, timeout: "float | None" = None) -> "Event":
        return self._q.get(timeout=timeout)

    def get_nowait(self) -> "Event":
        # Delegates to the stdlib queue — raises queue.Empty on empty (D-07).
        return self._q.get_nowait()

    def qsize(self) -> int:
        return self._q.qsize()

    def empty(self) -> bool:
        return self._q.empty()

    def depth_by_tier(self) -> "dict[EventTier, int]":
        # FIFO is tierless — single-bucket, documented monitoring-only.
        return {EventTier.BUSINESS: self._q.qsize()}


class PriorityEventBus:
    """``queue.PriorityQueue`` wrapper: CONTROL preempts BUSINESS, FIFO within tier.

    Keyed by ``(tier, seq, event)`` where ``seq`` comes from one per-instance
    ``itertools.count()``. Each ``next()`` is C-atomic (thread-safe, globally
    unique per bus), so the tuple's first two elements are always unique — the
    heap NEVER dereferences the non-orderable ``Event`` (D-10). ``get*()``
    unwrap the tuple and return the bare ``Event`` the drain expects.
    """

    def __init__(self) -> None:
        self._pq: "queue.PriorityQueue[tuple[EventTier, int, Event]]" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._depth: "Counter[EventTier]" = Counter()
        self._depth_lock = threading.Lock()

    def put(self, event: "Event") -> None:
        tier = _tier(event.type)
        self._pq.put((tier, next(self._seq), event))
        with self._depth_lock:
            self._depth[tier] += 1

    def get(self, timeout: "float | None" = None) -> "Event":
        item = self._pq.get(timeout=timeout)
        with self._depth_lock:
            self._depth[item[0]] -= 1
        return item[2]  # bare Event — never the (tier, seq, event) tuple

    def get_nowait(self) -> "Event":
        item = self._pq.get_nowait()  # raises queue.Empty on empty (inherited)
        with self._depth_lock:
            self._depth[item[0]] -= 1
        return item[2]  # bare Event — never the tuple

    def qsize(self) -> int:
        return self._pq.qsize()

    def empty(self) -> bool:
        return self._pq.empty()

    def depth_by_tier(self) -> "dict[EventTier, int]":
        with self._depth_lock:
            return {
                EventTier.CONTROL: self._depth[EventTier.CONTROL],
                EventTier.BUSINESS: self._depth[EventTier.BUSINESS],
            }
