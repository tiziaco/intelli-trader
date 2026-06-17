"""
Bracket state primitive — the single owner of the pending-bracket map (D-04/D-05).

`_PendingBracket` is moved VERBATIM from `order_manager.py` (D-03, T-07-15): the
frozen context for a `PercentFromFill` bracket awaiting its parent's fill. The
children do not exist until the parent EXECUTES, so a placeholder-priced child
can never trigger before its parent fills (T-07-14, structurally unreachable;
RESEARCH Pattern 5 Option B).

`BracketBook` is the genuinely-new primitive (D-05): a thin owner-class around
`Dict[OrderId, _PendingBracket]` whose methods are byte-equal to the raw dict ops
at the 8 verified `order_manager.py` sites. It exposes dict-compat dunders
(`__eq__`/`__contains__`/`__len__`) so the internal-attribute-coupled
`test_sltp_policy.py` survives untouched (RESEARCH Pitfall 2, option a).

`action` is `Side`-typed on `_PendingBracket` (SIG-03 / D-03): the persisted
action boundary is narrowed from `str` to `Side` across order_handler so side
handling is mypy-checked end-to-end (closes W2-02).
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Dict, Optional
from ...core.enums import Side
from ...core.ids import OrderId, PortfolioId, StrategyId
from ...core.sizing import PercentFromFill

if TYPE_CHECKING:
	# Config-enum exception (CONVENTIONS.md): TrailType lives in config/order.py.
	# Imported under TYPE_CHECKING only so this order-domain module carries the
	# trail annotation without a runtime config import.
	from ...config import TrailType


@dataclass(frozen=True, slots=True, kw_only=True)
class _PendingBracket:
	"""Context for a PercentFromFill bracket awaiting its parent's fill (D-13).

	RESEARCH Pattern 5 Option B: the manager holds a map keyed by the
	parent order id carrying the policy plus everything needed to build
	the children at fill time — the children do not exist until the
	parent EXECUTES, so a placeholder-priced child can never trigger
	before its parent fills (T-07-14, structurally unreachable).
	"""

	policy: PercentFromFill
	ticker: str
	action: Side
	quantity: Decimal
	exchange: str
	strategy_id: StrategyId
	portfolio_id: PortfolioId
	# TRAIL-01/TRAIL-02 (D-TRAIL-3/D-TRAIL-5): the trail descriptor survives the
	# arm->fill round-trip so the fill-anchored SL child can be declared as a
	# TRAILING_STOP seeded from the entry fill. Both default None — a non-trailing
	# bracket carries neither and builds a fixed STOP SL leg (byte-exact).
	trail_type: "TrailType | None" = None
	trail_value: Optional[Decimal] = None


class BracketBook:
	"""Single owner of the pending-bracket map (D-05).

	Wraps `Dict[OrderId, _PendingBracket]` with named methods that are 1:1
	byte-equal to the raw dict ops they replace at the 8 verified
	`order_manager.py` sites. Dict-compat dunders keep the
	internal-attribute-coupled `test_sltp_policy.py` green untouched
	(Pitfall 2 option a).
	"""

	def __init__(self) -> None:
		self._pending: Dict[OrderId, _PendingBracket] = {}

	def arm(self, order_id: OrderId, bracket: _PendingBracket) -> None:
		"""Record a pending bracket — `dict[order_id] = bracket`."""
		self._pending[order_id] = bracket

	def get(self, order_id: OrderId) -> Optional[_PendingBracket]:
		"""Read without removing — `dict.get(order_id)` (None on miss)."""
		return self._pending.get(order_id)

	def consume(self, order_id: OrderId) -> Optional[_PendingBracket]:
		"""Read-and-remove — `dict.pop(order_id, None)` (idempotent, None on miss)."""
		return self._pending.pop(order_id, None)

	def refresh_quantity(self, order_id: OrderId, quantity: Decimal) -> None:
		"""Get→replace(quantity=…)→set — the modify path (`:1164-1167`).

		No-op when the entry is absent (guard mirrors the original
		`if pending is not None` at the call site).
		"""
		pending = self._pending.get(order_id)
		if pending is not None:
			self._pending[order_id] = replace(pending, quantity=quantity)

	def __eq__(self, other: object) -> bool:
		"""Compare the wrapped dict so `book == {}` / `book == other_book` work."""
		if isinstance(other, dict):
			return self._pending == other
		if isinstance(other, BracketBook):
			return self._pending == other._pending
		return NotImplemented

	# IN-01: defining __eq__ implicitly sets __hash__ = None already; make it
	# explicit so a future caller who tries to put a BracketBook in a set/dict
	# gets an obvious, intentional contract rather than a surprising TypeError.
	# IN-01: pin the unhashable contract explicitly. `object.__hash__` is typed
	# `Callable[[], int]`, so assigning None is a deliberate declared-type
	# override (the same dunder-vs-None reconciliation the codebase resolves with
	# a targeted ignore) — the runtime effect is exactly what `__eq__` already
	# implies (`__hash__ = None`), now stated for the next reader.
	__hash__: ClassVar[None] = None  # type: ignore[assignment]  # mutable owner — intentionally unhashable

	def __contains__(self, order_id: object) -> bool:
		return order_id in self._pending

	def __len__(self) -> int:
		return len(self._pending)
