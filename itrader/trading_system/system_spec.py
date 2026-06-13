"""Declarative system spec value objects (COMP-01, D-01/D-02).

Promotes the ``tests/e2e/scenario_spec.py::ScenarioSpec`` / ``PortfolioSpec``
shape ~verbatim into the run path so the engine is composed declaratively via a
``build_backtest_system(spec)`` factory (Wave 2) instead of the imperative
``_build_and_run`` unpacking in the e2e harness.

Locked decisions for this spec:

* **D-01 — declarative spec + factory.** A frozen ``SystemSpec`` (strategies,
  portfolios, single exchange config, data/dates/timeframe) consumed by the
  factory. The e2e ``_build_and_run`` collapses onto ``build_backtest_system(spec)``
  in Wave 4 — so field names match ``ScenarioSpec`` EXACTLY (the harness reads
  attributes BY NAME): ``start``, ``end``, ``timeframe``, ``ticker``,
  ``starting_cash``, ``data``, ``strategies``, ``portfolios``, ``exchange``.
* **D-02 — run-mode-agnostic.** The spec describes WHAT to run (identical for
  backtest or live); the run-mode lives in the FACTORY name
  (``build_backtest_system`` now, ``build_live_system`` later reuses the same
  spec). Hence ``SystemSpec``, NOT ``BacktestSpec``.

``actions`` is kept (promoted with ``Action``) so the Wave-4 e2e collapse maps
onto a single spec type. An empty ``actions`` tuple is oracle-inert (the harness
wires no ``on_tick`` hook), so keeping it is byte-identical for the golden run.

This module is a value object only — it is NOT wired into any run path this
plan; the factory consumes it in Wave 2.

Indentation: TABS (``trading_system/`` package convention). The promoted source
``scenario_spec.py`` is 4-space; it is re-indented to tabs here — do NOT paste
4-space lines into this file.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PortfolioSpec:
	"""Minimal portfolio spec the factory reads (``user_id`` / ``name`` / ``cash``).

	Promoted field-for-field from ``scenario_spec.py::PortfolioSpec`` — the
	wiring trio the factory consumes via ``add_portfolio`` (D-01).
	"""

	user_id: int
	name: str
	cash: int


@dataclass(frozen=True)
class Action:
	"""A scheduled MODIFY/CANCEL the operator hook plays (D-05/D-07).

	Promoted from ``scenario_spec.py::Action`` so the ``SystemSpec.actions``
	timeline maps onto one spec type at the Wave-4 collapse. Predicate-resolved:
	the target is named by ``ticker`` + the sole resting (PENDING) order at
	``bar_date``, never by a literal ``Order.id`` (UUIDv7 is non-deterministic).

	Parameters
	----------
	bar_date : str
		``"YYYY-MM-DD"`` — matched against the scheduled bar's time.
	kind : str
		``"cancel"`` or ``"modify"``.
	ticker : str
		The predicate target — the resting order on this ticker is amended.
	new_price, new_quantity : Decimal | None
		New resting price / quantity for a ``"modify"`` (ignored for ``"cancel"``).
	"""

	bar_date: str
	kind: str
	ticker: str
	new_price: Decimal | None = None
	new_quantity: Decimal | None = None


@dataclass(frozen=True)
class SystemSpec:
	"""The declarative system spec the factory reads (D-01/D-02).

	Run-mode-agnostic (D-02): describes WHAT to run, identical for backtest or
	live. Field names match ``ScenarioSpec`` EXACTLY so the Wave-4 e2e collapse
	maps by name: ``start``, ``end``, ``timeframe``, ``ticker``,
	``starting_cash``, ``data`` (ticker -> CSV path), ``strategies``,
	``portfolios`` (each ``user_id`` / ``name`` / ``cash``), ``exchange``
	(``None`` = zero-fee / no-slippage defaults).

	``actions`` (default empty tuple) is oracle-inert — an empty timeline wires
	no operator hook, so the run stays byte-identical to today.
	"""

	start: str
	end: str
	timeframe: str
	ticker: str
	starting_cash: int
	data: dict[str, Any]
	strategies: list[Any]
	portfolios: list[PortfolioSpec]
	exchange: Any = None
	actions: tuple[Action, ...] = field(default_factory=tuple)
