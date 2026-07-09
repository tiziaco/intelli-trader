"""The frozen ``EngineContext`` infra bundle threaded into ``compose_engine`` (BUS-04/D-05).

``EngineContext`` is the small, mode-agnostic INFRASTRUCTURE bundle the composition
root hands to ``compose_engine(ctx, spec)`` (CTX-01/D-01). It carries the shared
event-bus transport plus the run-mode infra knobs (``config`` / ``environment`` /
``sql_engine``) — the WHAT-to-run description lives on the separate ``SystemSpec``
(D-02). The two-object split keeps the seam honest: infra on ``ctx``, declarative
run description on ``spec``.

Design invariants (D-05, LR-14):

* **Exactly four fields, in order** — ``bus`` / ``config`` / ``environment`` /
  ``sql_engine``. P3/P4/P9 only TIGHTEN the loose types (``config: Any`` narrows to
  the concrete ``SystemConfig`` in P9, ``sql_engine: Optional[Any]`` narrows to the
  SQL engine type once the live seam lands) — they NEVER widen a type and NEVER add
  a field. The shape is frozen here.
* **Infra-only.** ``bus`` is the transport, ``config`` is carried but UNREAD on the
  backtest path until P9, ``environment`` selects handler-owned storage backends,
  ``sql_engine`` is ``None`` for backtest (keeps the path SQL-import-inert, GATE-01).
* **Import-inert.** Only stdlib + the ``EventBus`` Protocol from
  ``events_handler.bus`` are pulled (bus.py imports only stdlib + ``core.enums.event``,
  so there is no import cycle). If a cycle ever appears, fall back to a
  ``TYPE_CHECKING``-only import of ``EventBus`` and annotate the field ``"EventBus"``.

Indentation: TABS (``trading_system/`` package convention).
"""

from dataclasses import dataclass
from typing import Any, Optional

from itrader.events_handler.bus import EventBus


@dataclass(frozen=True)
class EngineContext:
	"""Frozen infra bundle handed to ``compose_engine(ctx, spec)`` (D-05).

	Parameters
	----------
	bus : EventBus
		The shared event transport (``FifoEventBus`` for backtest, byte-exact;
		``PriorityEventBus`` is a live-only fast-follow — never wired here, D-11).
	config : Any
		The process ``SystemConfig`` carried through composition. Loose-typed
		``Any`` deliberately (D-05): it is CARRIED but UNREAD on the backtest path
		until P9 tightens it to the concrete ``SystemConfig``.
	environment : str
		The run-mode selector (``"backtest"`` here) the handlers use to pick their
		own storage backends (CTX-02 handler-owned storage).
	sql_engine : Optional[Any]
		The durable SQL engine handle, ``None`` for backtest — keeps the backtest
		path SQL-import-inert (GATE-01). Loose ``Optional[Any]`` until the live seam
		narrows it (D-05).
	"""

	bus: EventBus
	config: Any
	environment: str
	sql_engine: Optional[Any] = None
