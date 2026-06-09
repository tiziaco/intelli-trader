# Phase 4: M3 — Event & Dispatch Core - Pattern Map

**Mapped:** 2026-06-05
**Files analyzed:** 26 new/modified files
**Analogs found:** 24 / 26 (2 rely on RESEARCH.md verified patterns — noted below)

All line numbers verified at commit `7ce3491`. RESEARCH.md Patterns 1–5 are execution-verified
on Python 3.13.1 and are the primary source for the *new* mechanics; this document maps which
*existing codebase* conventions each file must copy (naming, docstring style, hierarchy shape,
re-export surface, indentation).

**Indentation rule (load-bearing):** new modules (`events_handler/events/`, `core/exceptions/order.py`,
`core/exceptions/data.py`, new enum code, all new tests) → **4 spaces**. Files edited in place that are
tab-indented (`full_event_handler.py`, `order_manager.py`, `order.py`, `simulated.py`, strategy modules)
→ **tabs**. `matching_engine.py`, `core/`, `config/`, `logger.py`, `portfolio_handler.py` → spaces (match file).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/events_handler/events/base.py` (NEW) | model (event dataclass) | event-driven | RESEARCH Pattern 1 (verified) + `itrader/events_handler/event.py:23-38` (PingEvent) | exact (pattern verified by execution) |
| `itrader/events_handler/events/market.py` (NEW) | model | event-driven | `itrader/events_handler/event.py:23-183` (Ping/Bar/PortfolioUpdate — already frozen) | exact |
| `itrader/events_handler/events/signal.py` (NEW) | model | event-driven | `itrader/events_handler/event.py:185-238` (SignalEvent) | exact (same class, redesigned) |
| `itrader/events_handler/events/order.py` (NEW) | model + factory | event-driven | `itrader/events_handler/event.py:278-339` (OrderEvent + `new_order_event`) | exact |
| `itrader/events_handler/events/fill.py` (NEW) | model + factory | event-driven | `itrader/events_handler/event.py:342-416` (FillEvent + `new_fill`) + RESEARCH Pattern 5 | exact |
| `itrader/events_handler/events/error.py` (NEW) | model (hierarchy) | event-driven | `itrader/events_handler/event.py:419-458` (PortfolioErrorEvent fields) + `core/exceptions/portfolio.py` (hierarchy shape) | role-match |
| `itrader/events_handler/events/__init__.py` (NEW) | config (re-exports) | — | `itrader/core/enums/__init__.py:1-66` | exact |
| `itrader/core/enums/` EventType + Side (NEW enum code) | model (enum) | — | `itrader/core/enums/execution.py:59-89` (FillStatus `_missing_`) | exact (canonical ref names it) |
| `itrader/core/enums/__init__.py` (MOD) | config (re-exports) | — | itself (`:8-38` import blocks, `:40-66` `__all__`) | exact |
| `itrader/core/exceptions/order.py` (NEW) | model (exceptions) | — | `itrader/core/exceptions/portfolio.py` (full file) | exact |
| `itrader/core/exceptions/data.py` (NEW) | model (exceptions) | — | `itrader/core/exceptions/portfolio.py` | exact |
| `itrader/core/exceptions/base.py` (MOD: rename) | model (exceptions) | — | itself (`:9-11`) | exact |
| `itrader/core/exceptions/portfolio.py` (MOD: KB24) | model (exceptions) | — | itself (`:40-45`, `:92-94`) | exact |
| `itrader/core/exceptions/__init__.py` (MOD: prune) | config (re-exports) | — | itself (`:33-47` execution block to delete) | exact |
| `itrader/core/ids.py` (MOD: FillId/EventId) | model (NewType aliases) | — | itself (`:17-31`) | exact |
| `itrader/events_handler/full_event_handler.py` (MOD: registry rewrite, TABS) | dispatcher | event-driven | itself (`:55-85` current chain — order extracted below) + RESEARCH Patterns 2/3 | exact |
| `itrader/trading_system/simulation/time_generator.py` (git mv) | utility (generator) | event-driven | `itrader/trading_system/simulation/ping_generator.py` (full file) | exact (rename) |
| `itrader/order_handler/order_manager.py` (MOD: D-11/D-13, TABS) | service/manager | request-response | itself (`:105-230` process_signal, `:292-457` _create_*) | exact |
| `itrader/order_handler/order_validator.py` (MOD: entity-based) | service (validator) | request-response | itself (`:118-150` verified-mutation sites to remove) | exact |
| `itrader/order_handler/order.py` (MOD: kw factories, TABS) | model (entity) | — | itself (`:280-316` `add_state_change` — the D-13 rejection route) | exact |
| `itrader/execution_handler/exchanges/simulated.py` (MOD: construct-complete fills, TABS) | service (exchange) | event-driven | itself (`:212-252` _emit_rejection/_emit_fill/on_market_data) + RESEARCH Pattern 5 | exact |
| `itrader/execution_handler/matching_engine.py` (MOD: replace-in-book, SPACES) | service (pure engine) | event-driven | itself (`:54-64` modify) | exact |
| `itrader/portfolio_handler/portfolio_handler.py` (MOD: ErrorEvent) | handler | event-driven | itself (`:102-116` _publish_error_event) | exact |
| `itrader/logger.py` (MOD: D-20 wiring) | config (logging) | — | itself (`:53,99-103,179-183`) + `config/settings.py:20-32` | exact |
| `itrader/strategy_handler/SMA_MACD_strategy.py` + `sltp_models.py` (MOD: logger swap) | strategy/utility | event-driven | `portfolio_handler.py:77` (bind pattern) | exact |
| `tests/unit/events/test_dispatch_registry.py`, `test_error_flow.py` (NEW), `test_event_immutability.py` (REWRITE) | test | — | `tests/integration/test_event_wiring.py` (fixture) + `tests/unit/events/test_event_immutability.py` (structure, inverted) | exact |

## Pattern Assignments

### `events_handler/events/base.py` + all concrete event modules (model, event-driven)

**Analog:** RESEARCH.md Pattern 1 (execution-verified — use verbatim as the starting point) for the
frozen/slots/kw_only mechanics. The *codebase conventions* to copy come from `itrader/events_handler/event.py`:

**Current frozen-event shape to preserve** (`event.py:23-38`, PingEvent → becomes TimeEvent):
```python
@dataclass(frozen=True, slots=True)
class PingEvent:
	"""..."""
	time: datetime
	type = EventType.PING          # ← today a bare class attr; becomes field(default=..., init=False)

	def __str__(self) -> str:
		return f"{self.type}, Time: {self.time}"

	def __repr__(self) -> str:
		return str(self)
```
Every event in the codebase has `__str__` + `__repr__ = str(self)` — keep this convention on the new
frozen classes (RESEARCH verified `__str__` override works on frozen+slots).

**SignalEvent fields to carry over** (`event.py:219-232`) — note the changes per D-03/D-05/D-10:
```python
	time: datetime
	order_type: str          # → OrderType (D-05)
	ticker: str
	action: str              # → Side (D-05)
	price: float             # stays float (D-04)
	quantity: float          # → float | None = None (D-10)
	stop_loss: float
	take_profit: float
	strategy_id: StrategyId
	portfolio_id: int        # stays int (02-05 carry-over; M4 owns migration)
	strategy_setting: dict[str, Any]
	verified: bool = False   # DELETED (D-03)
```

**OrderEvent boundary-coercion factory to preserve byte-exact** (`event.py:313-339`):
```python
	@classmethod
	def new_order_event(cls, order: Any, command: 'OrderCommand' = OrderCommand.NEW) -> 'OrderEvent':
		# Boundary coercion (M2a): the Order entity carries Decimal money, but the
		# OrderEvent + execution/matching/fee layer remain float until M4. ...
		return cls(
			order.time,                    # → all become keyword args (kw_only)
			order.ticker,
			order.action,
			float(order.price),            # ← PRESERVE these float() coercions exactly (D-04)
			float(order.quantity),
			order.exchange,
			order.strategy_id,
			order.portfolio_id,
			order_type=getattr(order, 'type', OrderType.MARKET),
			stop_price=getattr(order, 'stop_price', None),
			order_id=getattr(order, 'id', None),        # → required, no getattr default (D-12)
			parent_order_id=getattr(order, 'parent_order_id', None),
			command=command,
		)
```
D-11 adds `child_order_ids: tuple[OrderId, ...] = ()` here (read from `order.child_order_ids`).

**FillEvent factory** (`event.py:387-416`) — replaced by RESEARCH Pattern 5 (construct-complete:
explicit `price`/`quantity`/`commission` kwargs + `fill_id=uuid_compat.uuid7()` + `strategy_id=order.strategy_id`).
Current `FillStatus(status)` parse at `event.py:405` already uses the enum `_missing_` — keep it.

**uuid7 generation pattern** (`itrader/outils/id_generator.py:1-24`):
```python
import uuid
import uuid_utils.compat as uuid_compat
...
	def _uuid7(self) -> uuid.UUID:
		"""Generate a single time-ordered UUIDv7 as a stdlib ``uuid.UUID``."""
		return uuid_compat.uuid7()
```
Use `uuid_utils.compat` (returns native `uuid.UUID`), never raw `uuid_utils` or stdlib `uuid4`.
NB: `portfolio_handler.py:98-100` `_generate_correlation_id` uses `uuid.uuid4().hex[:12]` — that is a
string correlation id, not an entity id; planner may leave it (RESEARCH project-constraints note).

**Import-cycle constraint:** event modules import only `core.*` + stdlib + `uuid_utils` + `pandas`
(BarEvent payload). Current `event.py:8-9` imports `from ..core.enums import OrderType, OrderCommand, FillStatus`
and `from ..core.ids import StrategyId` — same relative style works in the new package
(`from ...core.enums import ...` from `events/` depth, or absolute `from itrader.core.enums import ...`
matching `full_event_handler.py:6-14` absolute style; prefer absolute — newer modules use it).

---

### `events_handler/events/error.py` (model hierarchy, event-driven)

**Analog A — field set:** current `PortfolioErrorEvent` (`event.py:419-458`):
```python
@dataclass
class PortfolioErrorEvent:
	time: datetime
	error_type: str
	error_message: str
	portfolio_id: Optional[int] = None
	operation: Optional[str] = None
	correlation_id: Optional[str] = None
	severity: str = "ERROR"  # ERROR, CRITICAL, WARNING
	details: Optional[dict[str, Any]] = None
	type = EventType.UPDATE  # Reuse UPDATE type for now   ← the hack D-06 kills
```
These field names are constructed at `portfolio_handler.py:107-114` — keep the names so that call
site needs minimal change (it must also gain `source="portfolio"` or rely on the child's default).

**Analog B — hierarchy shape:** `core/exceptions/portfolio.py:15-45` (concrete base + children that
narrow/extend, child stores its specific id then delegates to super):
```python
class PortfolioError(ITradingSystemError):
    """Base exception for portfolio-related errors."""
    pass

class PortfolioNotFoundError(NotFoundError):
    def __init__(self, portfolio_id: PortfolioIdLike):
        self.portfolio_id = portfolio_id
        super().__init__("Portfolio", portfolio_id)
```
ErrorEvent mirrors this: concrete `ErrorEvent(Event)` base with `type=EventType.ERROR` (init=False
default), child `PortfolioErrorEvent(ErrorEvent)` narrowing `source: str = "portfolio"` and adding
`portfolio_id`/`operation`. RESEARCH verified deep frozen hierarchy + child default-narrowing works.
`to_dict` (`event.py:447-458`) survival is Claude's discretion — its only consumer is logging.

---

### `core/enums/` — EventType relocation + new `Side` enum

**Analog:** `itrader/core/enums/execution.py:59-89` — FillStatus is the canonical Phase 3 D-04
class-enum, named by CONTEXT.md as the pattern to mirror exactly:
```python
class FillStatus(Enum):
    """Execution-truth fill status emitted by the exchange.

    Kept DISTINCT from ``OrderStatus`` (the order mirror) and ... (D-04) ...
    Member values are explicit uppercase strings, preserving the exact member
    names of the prior functional ``Enum(...)`` definition. ...
    """
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"

    @classmethod
    def _missing_(cls, value: object) -> "FillStatus":
        """Case-insensitive string parse; raise a clear f-string error. ..."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown FillStatus: {value!r}")
```
Copy this shape for `EventType` (TIME/BAR/UPDATE/SIGNAL/ORDER/FILL/SCREENER/ERROR — see RESEARCH
Pattern 4) and `Side` (BUY/SELL). Docstring convention: explain what the enum is, what it stays
distinct from, and why values are explicit strings. `Side` docstring should record the
Side→TransactionType boundary mapping precedent (D-05), like FillStatus's records FillStatus→OrderStatus.

**Placement:** either a new `core/enums/event.py` module (cleanest — mirrors per-domain module naming
`portfolio.py`/`execution.py`/`order.py`) or appended to an existing module; planner discretion.
The current functional enum + map to delete: `event.py:12-21` (`event_type_map` has zero external
importers — verified in RESEARCH).

---

### `core/enums/__init__.py` and `events_handler/events/__init__.py` (re-export surface)

**Analog:** `itrader/core/enums/__init__.py:1-66` — the house re-export pattern:
```python
"""
Core enums for the iTrader system.
...organized by domain for better maintainability.
"""

# Portfolio enums
from .portfolio import (
    PortfolioState,
    PositionSide,
    ...
)
...
__all__ = [
    # Portfolio enums
    'PortfolioState',
    ...
]
```
Grouped imports with domain comments + explicit `__all__` with matching comment groups.
`events/__init__.py` re-exports: `Event, TimeEvent, BarEvent, SignalEvent, OrderEvent, FillEvent,
PortfolioUpdateEvent, ScreenerEvent, ErrorEvent, PortfolioErrorEvent` (+ `EventType` for convenience,
re-exported from `core.enums`).

---

### `core/exceptions/order.py` + `core/exceptions/data.py` (NEW exception modules)

**Analog:** `itrader/core/exceptions/portfolio.py` (full file, 4-space) — copy its structure exactly:

**Module header + imports** (`portfolio.py:1-12`):
```python
"""
Portfolio-specific exceptions for the iTrader system.
"""

from typing import Any, Optional, Union

from .base import ITradingSystemError, ValidationError, ConfigurationError, StateError, ConcurrencyError, NotFoundError
from ..ids import PortfolioId, TransactionId
```
(New modules import `ITraderError` post-rename, and `OrderId` from `..ids` for order.py.)

**Domain base + specific children** (`portfolio.py:15-37`):
```python
class PortfolioError(ITradingSystemError):
    """Base exception for portfolio-related errors."""
    pass


class InsufficientFundsError(PortfolioError):
    """Raised when attempting to execute a transaction with insufficient funds."""

    def __init__(self, required_cash: float, available_cash: float, transaction_id: "Optional[TransactionId | int]" = None):
        self.required_cash = required_cash
        self.available_cash = available_cash
        self.transaction_id = transaction_id
        super().__init__(
            f"Insufficient funds: Required ${required_cash:.2f}, Available ${available_cash:.2f}"
        )
```
Convention: store every constructor arg as an attribute, build a human message, delegate to super.
Naming: `<Specific><Category>Error` (e.g. `OrderError`, `OrderTransitionError`, `DataError`).
For NotFound-style errors, subclass the cross-cutting base (`portfolio.py:40-45` PortfolioNotFoundError
subclasses `NotFoundError`, not `PortfolioError`).

**KB24 fix targets in `portfolio.py`:** `PortfolioNotFoundError.__init__` (`:43-45` —
`super().__init__("Portfolio", portfolio_id)` maps to `NotFoundError(entity_type, entity_id)`,
`base.py:80`) and `PortfolioConfigurationError` (`:92-94` — bare `pass` inheriting
`ConfigurationError(config_key, config_value, reason)`, `base.py:31`). Wrong-arg *call sites* are the
KB24 bug — constructions must match these signatures.

---

### `core/exceptions/base.py` (rename) + `core/exceptions/__init__.py` (prune)

**Rename target** (`base.py:9-11`):
```python
class ITradingSystemError(Exception):
    """Base exception for all iTrader system errors."""
    pass
```
→ `ITraderError` (D-19). All five subclass declarations in `base.py` (`:14,28,45,62,77`) plus
`portfolio.py:7,15` reference the old name. D-18 also deletes `ConcurrencyError` (`base.py:62-74`)
and its child `PortfolioConcurrencyError` (`portfolio.py:56-60`) — verify zero importers first
(D-13 mechanical-delete precedent).

**Prune target** (`__init__.py:33-47` + `:71-83`): the entire `from .execution import (...)` block
and its 12 names in `__all__` — delete with `execution.py` in the same commit (Pitfall 10).

---

### `core/ids.py` — `FillId` / `EventId` aliases

**Analog:** itself (`ids.py:17-31`):
```python
OrderId = NewType("OrderId", uuid.UUID)
PortfolioId = NewType("PortfolioId", uuid.UUID)
...
__all__ = [
    "OrderId",
    ...
]
```
Append `FillId = NewType("FillId", uuid.UUID)` (and `EventId` if used) + extend `__all__`. Keep the
module docstring's no-discriminator rule intact.

---

### `events_handler/full_event_handler.py` — dispatch rewrite (TABS)

**Analog:** itself. The load-bearing routing order to encode as the registry literal
(`full_event_handler.py:62-85` — current chain, TAB-indented):
```python
		while not self.global_queue.empty() :          # ← TOCTOU, replaced by Pattern 2
			try:
				event = self.global_queue.get(False)
			except queue.Empty:
				continue                                # ← becomes break
			if event.type == EventType.PING:
				self.logger.info(f"PING EVENT: {event.time}")   # ← demote to DEBUG (D-21)
				self.screeners_handler.screen_markets(event)
				self.universe.generate_bar_event(event)
			elif event.type == EventType.BAR:
				self.portfolio_handler.update_portfolios_market_value(event)   # 1
				self.execution_handler.on_market_data(event)                   # 2
				self.strategies_handler.calculate_signals(event)               # 3 ← ORDER IS LAW
			elif event.type == EventType.SIGNAL:
				self.order_handler.on_signal(event)
			elif event.type == EventType.ORDER:
				self.execution_handler.on_order(event)
			elif event.type == EventType.FILL:
				self.portfolio_handler.on_fill(event)        # 1
				self.order_handler.on_fill(event)            # 2 ← ORDER IS LAW
			elif event.type == EventType.SCREENER:
				continue                                     # → explicit empty route
			else:
				raise NotImplementedError('EVENT HANDLER: Unsupported event type %s' % event.type)
```
Replace with RESEARCH Patterns 2 (drain) + 3 (registry literal in `__init__`, `_dispatch`,
`_on_handler_error` seam) — preserving exactly the BAR and FILL handler order above. Constructor
signature + collaborator attribute names (`:34-53`) stay as-is (both TradingSystems wire positionally).
Logger init convention already present (`:52-53`): `get_itrader_logger().bind(component="FullEventHandler")`.
UPDATE gets `[]` (latent-crash fix, D-17); ERROR gets `[self._log_error_event]`.

---

### `trading_system/simulation/time_generator.py` (git mv of `ping_generator.py`)

**Analog:** `ping_generator.py` (full, 56 lines, 4-space). Rename class `PingGenerator` → `TimeGenerator`,
`PingEvent` → `TimeEvent`, fix the factually-wrong docstring ("produces a ping event" → "the clock
advanced to T", pairing with `core/clock.py`'s Clock family). Core yield site (`:43-45`):
```python
        for time in np.nditer(self.dates, flags=["refs_ok"]):
            # nditer yields 0-d array scalars; .item(0) extracts the python value.
            yield PingEvent(cast(Any, time).item(0))   # → TimeEvent(time=...)  (kw_only!)
```
Note the positional `PingEvent(...)` construction — must become keyword form (Pitfall 3). Delete the
dead commented block at `:51-54` while touching. Consumers to repoint: both TradingSystems import
`PingGenerator`.

---

### `order_handler/order_manager.py` — D-11 create-all-then-emit + D-13 entity-as-state (TABS)

**Analog:** itself.

**The in-flight signal mutations to kill** (`order_manager.py:275-289`, inside `_resolve_signal_quantity`):
```python
				sized_qty: Decimal = open_position.net_quantity
				signal_event.quantity = float(sized_qty)        # ← mutation dies (D-13)
			else:
				raw_qty: Decimal = (Decimal("0.95") * portfolio.cash) / to_money(price)
				signal_event.quantity = float(raw_qty)          # ← mutation dies (D-13)
```
The resolved quantity becomes a local Decimal threaded into Order construction (Decimal-native on
the entity — the WR-05 float coercion dies). The sizing-failure short-circuit (`:261-267`, invalid
price → `OperationResult.failure_result` BEFORE entity creation) is preserved exactly.

**Current emit-per-creation flow to restructure** (`order_manager.py:201-217`):
```python
			# 1. Create primary order based on order_type
			primary_order_result = self._create_primary_order(signal_event, exchange)
			results.append(primary_order_result)
			primary_order_ids = primary_order_result.affected_order_ids
			parent_id = primary_order_ids[0] if primary_order_ids else None
			# 2. Create stop-loss order if specified
			if signal_event.stop_loss > 0:
				sl_result = self._create_stop_loss_order(signal_event, exchange, parent_id)
			...
```
D-11: build all three Order entities first, populate `parent.child_order_ids` (declared
`order.py:74`, never populated), THEN emit OrderEvents parent-first — queue arrival sequence unchanged.

**The _create_* shape to refactor from** (`order_manager.py:388-401`, `_create_stop_loss_order` core):
```python
			sl_order = Order.new_stop_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action='BUY' if signal_event.action == 'SELL' else 'SELL',
				price=signal_event.stop_loss,
				quantity=signal_event.quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
			sl_order.parent_order_id = parent_id
			self.order_storage.add_order(sl_order)
			order_event = OrderEvent.new_order_event(sl_order)
```
Note storage-then-event sequencing and `OperationResult.success_result(..., order_events=[...],
affected_order_ids=[...])` return shape (`:403-408`) — keep both.

**D-13 rejection route** — the audited transition path is `order.py:280-316` `add_state_change`:
```python
		# Event-derived transition time (D-12): default to the order's event time,
		# never the wall clock.
		event_time = time if time is not None else self.time
		state_change = OrderStateChange(
			from_status=self.status,
			to_status=new_status,
			timestamp=event_time,
			reason=reason,
			triggered_by=triggered_by,
			additional_data=additional_data
		)
		self.status = new_status
		self.updated_at = event_time
		self.state_changes.append(state_change)
```
Rejection: validator fails → `order.add_state_change(OrderStatus.REJECTED, reason, "validator")`
(transition validity via `VALID_ORDER_TRANSITIONS`, `order.py:318-321`) → store. `Order.reject_order`
(`order.py:392+`) already exists as a convenience wrapper.

**Stale string-map call to replace while touching** (`order.py:158-160` in `Order.new_order`):
```python
		order_type = order_type_map.get(signal.order_type.upper())
		if order_type is None:
			raise ValueError(f'OrderType {signal.order_type} not supported')
```
With `SignalEvent.order_type: OrderType` (D-05) this lookup collapses; the bare `ValueError`
becomes the new order-domain exception (D-18).

---

### `order_handler/order_validator.py` — entity-based validation (SPACES)

**Analog:** itself. The `signal.verified` writes to remove (`order_validator.py:118-150`, five sites):
```python
        if self._has_critical_errors(critical_messages):
            signal.verified = False                # ← dies (D-03); verdict = ValidationResult only
            return ValidationResult(False, all_messages, "Critical field validation failed")
        ...
        # All phases passed
        signal.verified = True                     # ← dies
        return ValidationResult(True, all_messages, "All validations passed", has_warnings)
```
The `ValidationResult(success, messages, summary, has_warnings)` return type is already the typed
outcome — keep it; D-13 changes the *input* to the Order entity (signature change is Claude's
discretion). Same removal applies at `advanced_risk_manager.py:34-64` and `variable_sizer.py:32`.

---

### `execution_handler/exchanges/simulated.py` — construct-complete fills (TABS)

**Analog:** itself + RESEARCH Pattern 5.

**The post-construction mutation to kill** (`simulated.py:232-237`, inside `_emit_fill`):
```python
		fill_event = FillEvent.new_fill('EXECUTED', float(commission), event)
		fill_event.price = executed_price       # ← dies; passed into the factory
		# Override the matched fill quantity ...
		fill_event.quantity = fill_quantity     # ← dies; passed into the factory
		self.global_queue.put(fill_event)
```
The Decimal→float commission coercion comment (`:220-223`) documents the boundary D-04 preserves —
keep `float(commission)` exactly.

**The other three `new_fill` sites — byte-identical values, just keyword form** (per Pattern 5):
```python
	def _emit_rejection(self, event: OrderEvent, reason: str) -> None:        # :212-215
		self.global_queue.put(FillEvent.new_fill('REFUSED', 0.0, event))
	...
	def on_market_data(self, bar: "BarEvent") -> None:                        # :246-252
		fills, cancels = self.matching_engine.on_bar(bar)
		for decision in fills:
			self._emit_fill(decision.order_event, decision.fill_price, decision.fill_quantity)
		for cancel in cancels:
			self.global_queue.put(FillEvent.new_fill('CANCELLED', 0.0, cancel.order_event))
	...
	# on_order CANCEL branch :266-267
			if event.order_id is not None and self.matching_engine.cancel(event.order_id):
				self.global_queue.put(FillEvent.new_fill('CANCELLED', 0.0, event))
```
REFUSED/CANCELLED pass the order's own price/quantity with commission 0.0 — no numeric drift.

---

### `execution_handler/matching_engine.py` — replace-in-book (SPACES)

**Analog:** itself. The mutation to replace (`matching_engine.py:54-64`):
```python
    def modify(self, order_id: int, new_price: Optional[float] = None,
               new_quantity: Optional[float] = None) -> bool:
        """Mutate a resting order's price/quantity. Returns True if present."""
        order = self._resting.get(order_id)
        if order is None:
            return False
        if new_price is not None:
            order.price = new_price            # ← dies
        if new_quantity is not None:
            order.quantity = new_quantity      # ← dies
        return True
```
→ `dataclasses.replace(order, ...)` (None-guarded per arg) and store back into `self._resting[order_id]`.
`replace` preserves `order_id`/`event_id` (RESEARCH Pitfall 2 — document in the docstring). The stale
`Dict[int, OrderEvent]` / `order_id: int` annotations (`:40,50,54`) are wrong since M2 (IDs are UUID) —
fix while touching. The book pop/insert pattern to mirror: `cancel` (`:50-52`).

---

### `portfolio_handler/portfolio_handler.py` — ErrorEvent emission (SPACES)

**Analog:** itself (`portfolio_handler.py:102-116`):
```python
    def _publish_error_event(self, error: Exception, operation: str, correlation_id: str, portfolio_id: Optional[Any] = None) -> None:
        """Publish error event if enabled."""
        if not self.publish_error_events:
            return

        error_event = PortfolioErrorEvent(
            time=datetime.now(UTC),          # wall-clock carve-out OK — error path never fires in a green run
            error_type=type(error).__name__,
            error_message=str(error),
            operation=operation,
            correlation_id=correlation_id,
            portfolio_id=portfolio_id
        )
        self.global_queue.put(error_event)
```
Already keyword-form — survives kw_only with only the new-import + new-field changes (the rebuilt
frozen `PortfolioErrorEvent` carries `type=EventType.ERROR`). RESEARCH Open Question 4: keep wall
clock here or thread event time — planner discretion, document the carve-out.

---

### `logger.py` — D-20 wiring (SPACES)

**Analog:** itself. The three fix sites:

**Hardcoded json_logs + dead LOG_LEVEL read** (`logger.py:179-183`):
```python
    # Determine log level from config
    log_level = getattr(config, "LOG_LEVEL", "INFO")    # SystemConfig has no LOG_LEVEL → always "INFO"
    # Setup structured logging
    setup_logging(json_logs=False, log_level=log_level) # json_logs hardcoded
```
**Unguarded root-handler clear** (`logger.py:99-103`):
```python
    # Clear any existing handlers and add our structured logging handler
    root_logger = logging.getLogger()
    root_logger.handlers.clear()        # ← guard this (D-20): don't clobber embedder/pytest handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())
```
**Pitfall 8 (critical):** do NOT instantiate `Settings()` inside `init_logger` — `Settings.database_url`
is a required-no-default `SecretStr` (`config/settings.py:32`) and would `ValidationError` every
`import itrader`. Read `os.environ.get("ITRADER_LOG_LEVEL", "INFO")` / `ITRADER_JSON_LOGS` directly
(env names match `SettingsConfigDict(env_prefix="ITRADER_")`, `settings.py:23`; defaults `settings.py:26-28`).

---

### Strategy logging swap — `SMA_MACD_strategy.py:8-9`, `sltp_models.py:6-7` (TABS)

**Pattern to remove** (identical in both):
```python
import logging
logger = logging.getLogger('TradingSystem')
```
**Pattern to copy** (`portfolio_handler/portfolio_handler.py:77`, and `full_event_handler.py:52`):
```python
self.logger = get_itrader_logger().bind(component="PortfolioHandler")
```
For module-level loggers (these files use a module-level `logger`, not `self.logger`):
`logger = get_itrader_logger().bind(component="SMA_MACD_strategy")` with
`from itrader.logger import get_itrader_logger`.

---

### `strategy_handler/base.py` — SignalEvent construction site (TABS)

**Analog:** itself (`base.py:78-91`, `_generate_signal`) — already keyword-form, needs only field changes:
```python
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = self.order_type,    # str → OrderType (D-05)
							ticker = ticker,
							action = action,                 # str → Side (D-05)
							price = last_close,
							quantity = 0,                    # → quantity=None (D-10) or omit (default)
							stop_loss = sl,
							take_profit = tp,
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id,
							strategy_setting=self.setting_to_dict()
						)
```
Sizing gate moves with it: `order_manager.py:261` `if not signal_event.quantity or signal_event.quantity <= 0:`
becomes a `None` check (D-10 kills the `0` sentinel; `not quantity` already treats 0/None alike —
preserve `test_zero_quantity_signal` semantics).

---

### Test files (NEW + REWRITE)

**Fixture analog for dispatch/error-flow tests:** `tests/integration/test_event_wiring.py:37-65` —
the wired-EventHandler-with-MagicMock-collaborators fixture:
```python
@pytest.fixture
def wiring():
    """An EventHandler wired to mock collaborators + its queue and a put() helper."""
    q = queue.Queue()
    strategies = MagicMock()
    ...
    handler = EventHandler(
        strategies, screeners, portfolio, order, execution, universe, q
    )
    def put(event_type):
        ev = MagicMock()
        ev.type = event_type
        q.put(ev)
        return ev
    yield SimpleNamespace(q=q, handler=handler, put=put, ...)
    while not q.empty():
        q.get_nowait()
```
Note its module preamble (`:8-34`): pre-import of `EventType` + `patch.dict(sys.modules, _STUB_MODULES)`
around the `EventHandler` import to dodge the heavy handler-chain import — new unit tests for the
registry need the same stub trick (or the same `wiring` fixture extracted/shared). New
`test_dispatch_registry.py` asserts `handler._routes[EventType.BAR] == [...]` as data (RESEARCH D-23
group 1 snippet); `test_error_flow.py` covers ErrorEvent→log consumer, seam re-raise, and
`NotImplementedError` on unknown type.

**Rewrite target:** `tests/unit/events/test_event_immutability.py` — currently asserts mutability AS
the contract (`:43-67`, `:94-103` — `signal.verified = True  # must NOT raise`, `fill.price = 43.0`,
`order.price = 99.0`). Invert every "stays mutable" test to the frozen assertion shape already in the
same file (`:70-73`):
```python
def test_ping_event_is_frozen():
    ping = PingEvent(_TIME)
    with pytest.raises(FrozenInstanceError):
        ping.time = datetime(2025, 1, 1)
```
Its positional constructions (`:37-40`, `:59-62`) are also kw_only-breakage examples — every test file
in `tests/unit/events/`, `tests/unit/order/`, `tests/unit/execution/`, `tests/unit/portfolio/`,
`tests/integration/` with direct event constructors gets the keyword-form pass (Pitfall 3, ~79 sites).

**Marker constraint:** markers are folder-derived via `tests/conftest.py` + declared in `pyproject.toml`
only — new test files under `tests/unit/events/` need no new marker registration.

## Shared Patterns

### Structlog component binding
**Source:** `itrader/logger.py:106-146` (ITraderStructLogger.bind docstring + impl); exemplar use
`portfolio_handler.py:77`, `full_event_handler.py:52-53`
**Apply to:** dispatcher rewrite (`_log_error_event` consumer), strategy logger swaps, any new module
```python
self.logger = get_itrader_logger().bind(component="ClassName")
self.logger.info("Operation completed", key=value)
```

### Log-level policy (D-21)
**Apply to:** dispatcher (per-ping INFO at `full_event_handler.py:68` → DEBUG), `order_manager.py:161,220`
(per-signal INFO → DEBUG), `simulated.py:241` (per-fill INFO → DEBUG). Lifecycle facts
(init messages like `full_event_handler.py:53`) stay INFO.

### UUIDv7 generation
**Source:** `itrader/outils/id_generator.py:1-24`
**Apply to:** `event_id` default_factory, `fill_id` at exchange construction
```python
import uuid_utils.compat as uuid_compat
uuid_compat.uuid7()   # returns native uuid.UUID
```

### Class-enum with `_missing_`
**Source:** `itrader/core/enums/execution.py:59-89` (FillStatus)
**Apply to:** new `EventType`, new `Side`

### NewType ID aliases
**Source:** `itrader/core/ids.py:17-31`
**Apply to:** `FillId`, `EventId`

### Domain-exception module shape
**Source:** `itrader/core/exceptions/portfolio.py` (args-as-attributes + message + super-delegation)
**Apply to:** new `order.py`, `data.py` exception modules; all D-18 bare-raise replacements

### Audited state transition (rejection route)
**Source:** `itrader/order_handler/order.py:280-321` (`add_state_change` + `_is_valid_transition` +
`VALID_ORDER_TRANSITIONS`)
**Apply to:** D-13 validator-rejection path (PENDING→REJECTED, event-derived timestamp, `triggered_by="validator"`)

### Decimal→float boundary coercion (preserve byte-exact, D-04)
**Sources:** `event.py:325-339` (`new_order_event` `float(order.price/quantity)`),
`simulated.py:220-232` (`float(commission)` at the `new_fill` boundary),
`order.py:81-90` (`to_money` re-entry at entity construction)
**Apply to:** every redesigned factory — coercions move position but values must be bit-identical.

### Package `__init__` re-export
**Source:** `itrader/core/enums/__init__.py` (grouped imports + commented `__all__`)
**Apply to:** `events/__init__.py` (new), `core/enums/__init__.py` (extend), `core/exceptions/__init__.py` (prune)

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `EventHandler._on_handler_error` seam + `_log_error_event` consumer | dispatcher policy hook | event-driven | No existing policy-seam-with-override in the dispatcher; RESEARCH Pattern 3 provides the verified shape (bare-`raise`-in-callee semantics noted in RESEARCH A1). Closest conceptual precedent: the Phase 3 D-06 replaceable storage seam (cited in CONTEXT, not a copyable code shape) |
| Frozen `Event` base with `__post_init__`/`object.__setattr__` `created_at` defaulting | model | event-driven | No frozen base-class-with-post-init exists in the codebase; RESEARCH Pattern 1 is execution-verified on the project venv — use it verbatim |

## Metadata

**Analog search scope:** `itrader/events_handler/`, `itrader/core/{enums,exceptions,ids,clock}`,
`itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`,
`itrader/strategy_handler/`, `itrader/trading_system/simulation/`, `itrader/logger.py`,
`itrader/config/settings.py`, `itrader/outils/id_generator.py`, `tests/unit/events/`, `tests/integration/`
**Files scanned:** 22 read (full or targeted ranges), all line refs verified at commit `7ce3491`
**Pattern extraction date:** 2026-06-05
