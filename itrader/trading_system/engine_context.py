"""The frozen ``EngineContext`` mode-injection bundle threaded into ``compose_engine`` (BUS-04/D-05, D-01).

``EngineContext`` is the small, mode-agnostic bundle the composition root hands to
``compose_engine(ctx)`` (CTX-01/D-01). It carries the shared event-bus transport,
the run-mode infra knobs (``config`` / ``environment``), AND the per-mode BACKENDS
the mode-specific factory selects and injects (``feed`` / ``store`` / ``sql_engine``).
The WHAT-to-run description stays factory-local — backtest keeps its ``SystemSpec``,
live keeps a tiny venue spec — and never crosses this seam (D-02/D-04). ``ctx`` is the
one place the mode factory differentiates and injects components per trading-system mode.

Design invariants (D-05, LR-14 — **consciously amended by D-01**):

* **LR-14 amendment (D-01).** The original invariant pinned ``EngineContext`` to
  "exactly four fields (``bus`` / ``config`` / ``environment`` / ``sql_engine``) …
  NEVER add a field. The shape is frozen here." Phase 06.1 (D-01) deliberately amends
  that: ``feed`` (required) and ``store`` (Optional) are added because ``ctx`` IS the
  mode-injection seam — ``sql_engine`` already rides here real-in-live / ``None``-in-
  backtest, and ``store`` follows the IDENTICAL idiom real-in-backtest / ``None``-in-live
  (D-02). Field types still only TIGHTEN downstream (``config: Any`` narrows to the
  concrete ``ITraderConfig`` in P9), never widen.
* **Field order — required before defaulted.** ``bus`` / ``config`` / ``environment`` /
  ``feed`` / ``rng`` (all required) precede ``store`` / ``sql_engine`` (both default
  ``None``) so the frozen dataclass does not raise "non-default argument follows
  default argument".
* **The determinism RNG rides here (D-07).** ``rng`` is a REQUIRED field, inserted
  before the defaulted ones per the ordering rule above. It is deliberately NOT
  defaulted: a default would mint a SECOND ``random.Random`` on a wiring omission, and
  a second instance is not an error state — it is a silently different, unreproducible
  run that no existing test names. ``random`` is stdlib, so the field costs the import
  graph nothing (GATE-01 unaffected) and needs no ``TYPE_CHECKING`` guard.
* **Mode-injected backends.** ``feed`` is the required per-mode read-model
  (``BacktestBarFeed`` in backtest, ``LiveBarFeed`` in live). ``store`` is the canonical
  price store — REAL in backtest (``CsvPriceStore``), ``None`` in live (``LiveBarFeed``
  reads no store, D-02) — the identical real/None idiom as ``sql_engine`` (``None`` for
  backtest, keeps the path SQL-import-inert, GATE-01).
* **Import-inert.** Only stdlib + the ``EventBus`` Protocol from ``events_handler.bus``
  are pulled at runtime. The ``feed`` / ``store`` / ``sql_engine`` annotations are BASE
  types resolved under ``TYPE_CHECKING`` only (D-03) — a real import of ``SqlEngine`` /
  the concrete feed/store would pull SQLAlchemy or the concretions onto the backtest
  import path and break GATE-01. Guarded string forward-refs keep them unevaluated at
  runtime. If a cycle ever appears for ``EventBus`` too, fall back to a
  ``TYPE_CHECKING``-only import and annotate the field ``"EventBus"``.

Indentation: TABS (``trading_system/`` package convention).
"""

import random
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from itrader.events_handler.bus import EventBus

if TYPE_CHECKING:
	# P3 (CTX-04): concrete-type import for the ``sql_engine`` annotation ONLY.
	# ``SqlEngine`` (storage/engine.py) eagerly imports SQLAlchemy, so a real
	# (non-guarded) import here would pull SQLAlchemy onto the backtest import
	# path and break GATE-01 inertness. Guarded + string forward-ref keeps the
	# annotation unevaluated at runtime while narrowing the type for mypy.
	from itrader.storage.engine import SqlEngine
	# D-01/D-03: the new ``feed`` / ``store`` annotations forward-ref the BASE
	# feed/store types under the SAME TYPE_CHECKING guard — the base modules are
	# pure (no ccxt/SQL), and the CONCRETE ``LiveBarFeed`` is lazy-imported only
	# inside the live factory. Guarded so ``engine_context`` stays import-inert.
	from itrader.price_handler.feed.base import BarFeed
	from itrader.price_handler.store.base import PriceStore


@dataclass(frozen=True)
class EngineContext:
	"""Frozen mode-injection bundle handed to ``compose_engine(ctx)`` (D-05, D-01).

	Parameters
	----------
	bus : EventBus
		The shared event transport (``FifoEventBus`` for backtest, byte-exact;
		``PriorityEventBus`` is a live-only fast-follow — never wired here, D-11).
	config : Any
		The process ``ITraderConfig`` carried through composition. Loose-typed
		``Any`` deliberately (D-05): it is CARRIED but UNREAD on the backtest path
		until P9 tightens it to the concrete ``ITraderConfig``.
	environment : str
		The run-mode selector (``"backtest"`` here) the handlers use to pick their
		own storage backends (CTX-02 handler-owned storage).
	feed : BarFeed
		The REQUIRED per-mode market-data read-model the factory injects
		(``BacktestBarFeed`` in backtest, ``LiveBarFeed`` in live). D-01: ``compose_engine``
		reads ``ctx.feed`` uniformly rather than constructing a ``BacktestBarFeed`` itself,
		so the seam is store/feed-agnostic. Annotated against the BASE ``BarFeed`` via a
		TYPE_CHECKING forward-ref (D-03) — no concretion is pulled onto the import graph.
	rng : random.Random
		The ONE shared seeded ``random.Random`` for the run (D-07). Constructed ONCE by
		the mode factory from ``config.rng_seed`` (default 42) and injected here so every
		component the wiring seam builds — the ``SimulatedExchange``, its slippage model,
		and from D-06 the venue plugin that builds them — draws from a SINGLE instance.
		REQUIRED and never defaulted: two ``random.Random(42)`` objects look identical and
		diverge the moment either is drawn from, so a defaulted field would turn a wiring
		omission into a silently non-reproducible run. ``random`` is stdlib — annotated
		concretely (no TYPE_CHECKING guard) at zero import-graph cost (GATE-01).
	store : Optional[PriceStore]
		The canonical price store — REAL in backtest (``CsvPriceStore``), ``None`` in
		live (``LiveBarFeed`` reads no store, D-02). The IDENTICAL real/None idiom as
		``sql_engine`` (real-in-live / None-in-backtest): ``ctx`` is where the mode
		factory selects per-mode backends. Base-typed ``Optional["PriceStore"]`` via a
		TYPE_CHECKING forward-ref (D-03), default ``None`` so live omits it.
	sql_engine : Optional[SqlEngine]
		The durable SQL engine handle, ``None`` for backtest — keeps the backtest
		path SQL-import-inert (GATE-01). P3 (CTX-04) narrows this from the former
		loose ``Optional[Any]`` to the concrete ``Optional[SqlEngine]`` via a
		TYPE_CHECKING forward-ref (a real import would pull SQLAlchemy onto the
		backtest path — the annotation stays a string so it is unevaluated at runtime).
	"""

	bus: EventBus
	config: Any
	environment: str
	feed: "BarFeed"
	rng: random.Random
	store: Optional["PriceStore"] = None
	sql_engine: Optional["SqlEngine"] = None
