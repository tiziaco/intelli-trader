"""Declarative system spec value objects.

A frozen ``SystemSpec`` (strategies, portfolios, single exchange config,
data/dates/timeframe) describes WHAT to run — identical for backtest or live. The
run-mode lives in the FACTORY name (``build_backtest_system`` / ``build_live_system``),
never in the spec; hence ``SystemSpec``, not ``BacktestSpec``.

``tests/e2e/scenario_spec.py::ScenarioSpec`` is an alias of ``SystemSpec``, so the e2e
leaves read these fields BY NAME.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PortfolioSpec:
	"""Minimal portfolio spec the factory reads.

	``account_id`` is the spec-side half of the account reference: a
	composition-supplied portfolio names its venue account HERE, and ``add_portfolio``
	threads it onto the ``Portfolio``.
	"""

	name: str
	cash: int
	account_id: str | None = None


@dataclass(frozen=True)
class Action:
	"""A scheduled MODIFY/CANCEL the operator hook plays.

	Predicate-resolved: the target is named by ``ticker`` + the sole resting (PENDING)
	order at ``bar_date``, never by a literal ``Order.id`` — UUIDv7 ids are not
	reproducible across runs.

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
	"""The declarative system spec the factory reads.

	Run-mode-agnostic: describes WHAT to run, identical for backtest or live.
	``data`` maps ticker -> CSV path; ``exchange=None`` means zero-fee /
	no-slippage defaults; an empty ``actions`` timeline wires no operator hook.

	``results_store`` is the OPTIONAL results sink the factory forwards into the engine.
	``execution_venue`` / ``data_provider`` name catalogue entries and ``account_id``
	names the venue account whose session an order reaches; all three are LIVE-ONLY. The
	``account_id`` default is applied at READ time in the venue-account manager, not
	stored here.

	These four are typed ``Any`` deliberately so the spec NEVER imports the SQL surface
	or the venue substrate — a concrete annotation would put both on the backtest import
	path. The concrete ``ResultsStore`` annotation lives on the ``build_handler_graph``
	seam instead.
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
	results_store: Any = None
	execution_venue: Any = None
	data_provider: Any = None
	account_id: Any = None
