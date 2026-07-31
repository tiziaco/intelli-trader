"""The frozen ``EngineContext`` mode-injection bundle threaded into ``build_handler_graph``.

``EngineContext`` is the small, mode-agnostic bundle the composition root hands to
``build_handler_graph(ctx, ...)``. It carries the shared event-bus transport, the
run-mode infra knobs (``config`` / ``environment``), and the per-mode BACKENDS the
mode-specific factory selects and injects (``feed`` / ``store`` / ``sql_engine``). The
WHAT-to-run description stays root-local — backtest keeps its ``SystemSpec``, live keeps
its builder arguments — and never crosses this seam.

* **Field order — required before defaulted.** ``bus`` / ``config`` / ``environment`` /
  ``feed`` / ``rng`` precede ``store`` / ``sql_engine`` so the frozen dataclass does not
  raise "non-default argument follows default argument".
* **Import-inert.** Only stdlib + the ``EventBus`` Protocol from ``events_handler.bus``
  are pulled at runtime; every other annotation resolves under ``TYPE_CHECKING`` only.
"""

import random
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from itrader.events_handler.bus import EventBus

if TYPE_CHECKING:
	# ``SqlEngine`` eagerly imports SQLAlchemy; a real (non-guarded) import here would
	# pull it onto the backtest import path and break import inertness. The feed/store
	# annotations are the BASE types for the same reason. Guarded + string forward-refs
	# keep every one unevaluated at runtime while narrowing the type for mypy.
	from itrader.storage.engine import SqlEngine
	from itrader.price_handler.feed.base import BarFeed
	from itrader.price_handler.store.base import PriceStore


@dataclass(frozen=True)
class EngineContext:
	"""Frozen mode-injection bundle handed to ``build_handler_graph(ctx, ...)``.

	Parameters
	----------
	bus : EventBus
		The shared event transport — ``FifoEventBus`` in backtest (byte-exact FIFO),
		``PriorityEventBus`` in live.
	config : Any
		The process ``ITraderConfig`` carried through composition. Loose-typed ``Any``
		deliberately: it is CARRIED but UNREAD on the backtest path.
	environment : str
		The run-mode selector the handlers use to pick their own storage backends.
	feed : BarFeed
		The per-mode market-data read-model the factory injects (``BacktestBarFeed`` in
		backtest, ``LiveBarFeed`` in live). The graph builder reads ``ctx.feed``
		uniformly rather than constructing a feed itself, so the seam stays
		store/feed-agnostic.
	rng : random.Random
		The ONE shared seeded ``random.Random`` for the run, built by the mode factory
		from ``config.rng_seed`` so every component the wiring seam builds draws from a
		SINGLE instance. Never defaulted: two ``random.Random(42)`` objects look
		identical and diverge the moment either is drawn from, so a default would turn a
		wiring omission into a silently non-reproducible run rather than an error.
	store : Optional[PriceStore]
		The canonical price store — REAL in backtest (``CsvPriceStore``), ``None`` in
		live (``LiveBarFeed`` reads no store).
	sql_engine : Optional[SqlEngine]
		The durable SQL engine handle, ``None`` for backtest — keeps the backtest path
		SQL-import-inert.
	"""

	bus: EventBus
	config: Any
	environment: str
	feed: "BarFeed"
	rng: random.Random
	store: Optional["PriceStore"] = None
	sql_engine: Optional["SqlEngine"] = None
