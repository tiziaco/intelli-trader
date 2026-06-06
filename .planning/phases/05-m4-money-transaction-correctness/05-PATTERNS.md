# Phase 5: M4 — Money & Transaction Correctness - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 23 (2 new, 21 modified)
**Analogs found:** 22 / 23 (one partial — per-reference reservation storage has no exact in-tree analog; closest is the seam's own aggregate API)

All analogs read at current HEAD (`implement-phase-5` branch, clean tree). This is a brownfield
refactor: most "analogs" are the files being modified themselves — the pattern to copy is the
*existing in-tree precedent shape* (Phase 2–4 conventions), extracted below per file.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/core/portfolio_read_model.py` (NEW) | core type module (Protocol + DTO) | request-response (sync read/reserve boundary) | `itrader/execution_handler/exchanges/base.py` (Protocol) + `itrader/core/ids.py` (core-module style) + `itrader/events_handler/events/order.py` (frozen DTO) | exact (composite) |
| `tests/unit/core/test_portfolio_read_model.py` (NEW) | test | — | `tests/unit/` existing core tests (see Validation map in RESEARCH) | role-match |
| `itrader/portfolio_handler/cash/cash_manager.py` | service (money ledger) | CRUD + audit append | itself — `apply_transaction_delta` (`:284-333`) is the precision pattern; `reserve_cash` (`:335-383`) the reservation shape | exact |
| `itrader/portfolio_handler/portfolio.py` | aggregate/orchestrator | transform (settlement sequence) | itself — `process_transaction` (`:289-308`) reordered per D-12 | exact |
| `itrader/portfolio_handler/transaction/transaction_manager.py` | manager (shrinks) | CRUD | `order_manager.py` manager shape (logic-only, no queue) | role-match |
| `itrader/portfolio_handler/transaction/transaction.py` | entity | — | `FillEvent` linkage fields (`events/fill.py:61-63`) | exact (field pattern) |
| `itrader/portfolio_handler/portfolio_handler.py` | handler + Protocol impl | event-driven (on_fill) | itself + structural-typing precedent (`SimulatedExchange` satisfies `AbstractExchange` Protocol with no inheritance) | exact |
| `itrader/portfolio_handler/base.py` (seam ABC) | storage interface | CRUD | itself — `PortfolioStateStorage` abstractmethod style (`:93-292`) | exact |
| `itrader/portfolio_handler/storage/` in-memory backend | storage backend | CRUD | itself (per-reference dict mirrors order storage `_by_id` dict, `order_handler/storage/in_memory_storage.py:41`) | exact |
| `itrader/order_handler/order_handler.py` | facade/controller | event-driven | itself — `on_signal` (`:73-97`) is the target shape; `:104-134` deleted | exact |
| `itrader/order_handler/order_manager.py` | manager | event-driven (signal→order) | itself — audited REJECTED path (`:152-168`) is the reserve-fail pattern | exact |
| `itrader/order_handler/order_validator.py` | validator | request-response | Protocol retype per `order_manager.py` constructor pattern | exact |
| `itrader/order_handler/storage/in_memory_storage.py` | storage backend | CRUD | itself — `_by_id` flat dict (`:41`) becomes sole structure | exact |
| `itrader/strategy_handler/position_sizer/variable_sizer.py` | utility (sizing) | request-response | Protocol retype (same as validator) | exact |
| `itrader/strategy_handler/risk_manager/advanced_risk_manager.py` | utility (risk) | request-response | Protocol retype (same as validator) | exact |
| `itrader/core/enums/portfolio.py` | enum module | — | itself — `CashOperationType` `_missing_` pattern (`:58-77`); `TransactionState` (`:126-138`) deleted | exact |
| `itrader/execution_handler/base.py` | ABC | event-driven | `portfolio_handler/base.py::PortfolioStateStorage` (real ABC w/ docstrings) | role-match |
| `itrader/execution_handler/result_objects.py` | DTOs | — | `events/order.py` frozen/slots style for survivors | exact |
| `itrader/execution_handler/exchanges/base.py` | Protocol | event-driven | itself — signatures retype (`execute_order -> None`) | exact |
| `itrader/execution_handler/exchanges/simulated.py` | exchange (service) | event-driven | itself + `to_money` boundary (`core/money.py:42`) | exact |
| `itrader/events_handler/events/{signal,order,fill}.py` | event dataclasses | event-driven | themselves — coercion-comment sites (`order.py:66-75`, `fill.py:104-117`) are the exact removal targets | exact |
| `itrader/trading_system/{backtest,live}_trading_system.py` | wiring/entry | — | themselves (constructor wiring, `backtest_trading_system.py:68-69`) | exact |
| Test files (mechanical fallout, see RESEARCH Pitfall 7) | tests | — | existing per-domain test files | exact |

## Pattern Assignments

### `itrader/core/portfolio_read_model.py` (NEW — core type module, sync boundary)

**Analogs:** `itrader/core/ids.py` (module shape), `itrader/execution_handler/exchanges/base.py` (Protocol shape), `itrader/events_handler/events/order.py` (frozen DTO shape). Indentation: **4 spaces** (core module, Phase 2/3 precedent).

**Module-header + `__all__` pattern** — copy from `itrader/core/ids.py` lines 1-15, 26-35:
```python
"""
Core identity types for the iTrader system.

Eight ``NewType`` aliases over the stdlib ``uuid.UUID`` (D-12). Each alias is a
distinct nominal type to ``mypy`` ...
"""

import uuid
from typing import NewType

OrderId = NewType("OrderId", uuid.UUID)
...
__all__ = ["OrderId", "PortfolioId", ...]
```
Note the docstring style: states WHAT the module is, cites the locked decision IDs (D-xx) that
shaped it, and documents the deliberate non-choices. New module should cite D-13..D-17 the same way.

**runtime_checkable Protocol pattern** — copy from `itrader/execution_handler/exchanges/base.py` lines 7-25:
```python
@runtime_checkable
class AbstractExchange(Protocol):
	"""
	Structural interface (D-07) for exchange operations ...

	This is a ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes
	the swap-a-fake structural seam that both simulated and live exchanges must
	satisfy ...
	"""

	def on_order(self, event: OrderEvent) -> None:
		"""Route an order event ..."""
		...
```
Method bodies are literal `...` (not `pass`, not `raise NotImplementedError`), each with a docstring.
The "Protocol rather than ABC because structural seam" justification sentence is the house style —
reproduce it for `PortfolioReadModel`.

**Frozen DTO pattern** — copy from `itrader/events_handler/events/order.py` lines 15-16, 28-45:
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OrderEvent(Event):
    ...
    ticker: str
    action: Side
    ...
```
For `PositionView` use `@dataclass(frozen=True, slots=True)` (kw_only optional — it's a 4-field
snapshot, not an event). Fields per D-15: `ticker: str`, `side: PositionSide`,
`net_quantity: Decimal`, `avg_price: Decimal`. Type IDs with `itrader/core/ids.py` NewTypes
(`PortfolioId`, `OrderId`) in the Protocol signatures. RESEARCH Pattern 3 gives the full target
sketch — it matches these analogs exactly.

---

### `itrader/portfolio_handler/cash/cash_manager.py` (service, money ledger) — **the central analog file**

**Indentation: 4 spaces** (this file already uses spaces). Locks (`self._lock = threading.RLock()`,
`:49`, and every `with self._lock:`) deleted per D-19.

**Precision-preserving fill-flow pattern** — the new `apply_fill_cash_flow(...)` (Pitfall 1) must copy
the semantics of `apply_transaction_delta`, lines 284-333. The load-bearing parts:
```python
def apply_transaction_delta(self, delta: Decimal, description: str = "...", reference_id: Optional[str] = None) -> bool:
    """Apply a signed, full-precision Decimal delta to the cash ledger.

    Precision-preserving transaction-path primitive (CR-03). Unlike
    ``deposit``/``withdraw``/``process_transaction_cash_flow`` this does NOT
    route through ``_validate_and_convert_amount`` (so it never quantizes the
    delta to 2dp) and does NOT enforce the deposit/withdraw min/max-balance
    policy gates ...
    """
    old_balance = self._balance
    new_balance = old_balance + delta
    self._balance = new_balance
    operation_type = (
        CashOperationType.TRANSACTION_DEBIT if delta < 0
        else CashOperationType.TRANSACTION_CREDIT
    )
    self._create_operation(operation_type, abs(delta), description, reference_id, old_balance, new_balance)
```
**Copy:** the skip-quantize/skip-policy-gates documentation pattern, signed-delta semantics, and
audit-record-per-mutation. **Change:** return `None` (D-10), add `fee: Decimal` to the recorded
entry (D-06), error contract raises typed. This method itself is then DELETED (D-05) — the new
method replaces it on the trade path.

**Anti-pattern in the same file (do NOT copy):** `_validate_and_convert_amount` lines 487-488
quantizes to 2dp — routing trade flows through it breaks the byte-exact oracle (Pitfall 1):
```python
amount_decimal = to_money(amount).quantize(self.precision, rounding=ROUND_HALF_UP)
```
This stays correct ONLY for `deposit`/`withdraw` (genuine external cash ops, D-05).

**Reservation method shape** — `reserve_cash` lines 335-383 shows check→mutate→audit→log:
```python
available = self.available_balance
if available < amount_decimal:
    raise InsufficientFundsError(
        required_cash=float(amount_decimal),
        available_cash=float(available)
    )
old_reserved = self._storage.get_reserved_cash()
new_reserved = old_reserved + amount_decimal
self._storage.set_reserved_cash(new_reserved)
self._create_operation(CashOperationType.RESERVATION, amount_decimal, description,
                       reference_id, self._balance, self._balance)  # balance unchanged
```
**Copy:** raise-typed-on-insufficient, audit entry with balance_before==balance_after for
reservations. **Change:** per-reference storage (see seam pattern below); skip the 2dp quantize
(RESEARCH OQ4 recommendation: full-precision reservations); bool return → None.

**Settlement invariant guard (D-10/Pitfall 2):** new method checks `self._balance`, NEVER
`self.available_balance` (the current debit path at `:247-252` checks available — that exact line
is the bug that would false-positive under portfolio-first FILL dispatch). RESEARCH "Code
Examples" gives the target shape; the exception construction pattern to copy is `cash_manager.py:357-360` above.

**Determinism fix (Pitfall 5)** — replace lines 503-510:
```python
# CURRENT (DO NOT KEEP): wall-clock id + timestamp
operation_id = f"cash_op_{self._operation_counter}_{int(datetime.now().timestamp() * 1000)}"
...
timestamp=datetime.now(),
```
Copy the ID pattern from `events/fill.py:114` (`fill_id=uuid_compat.uuid7()` via
`import uuid_utils.compat as uuid_compat`) or `idgen` (`from itrader import idgen` — see
`portfolio.py:50` `idgen.generate_portfolio_id()`); timestamp = transaction/fill event time
(M2-09 precedent: "the timestamp defaults to the order's own event-derived time — never wall
clock", `order_manager.py:158-159` comment).

---

### `itrader/portfolio_handler/portfolio.py` (aggregate, settlement orchestration)

**Indentation: tabs.** Lock (`self._lock`, `:65`) and every `with self._lock:` deleted (D-19);
document the single-writer contract in the class docstring where the "Thread safety" bullet lives
today (`:37`).

**The defect being fixed** — current `process_transaction` lines 289-308 (position mutates BEFORE
validation/cash):
```python
def process_transaction(self, transaction: Transaction) -> None:
	transaction.portfolio_id = self.portfolio_id
	try:
		# Process position changes first (this handles short positions properly)
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id
		# Process the transaction financially (cash flow) - this includes funds validation
		self.transaction_manager.process_transaction(transaction)
	except Exception as e:
		logger.error(f"Transaction processing failed: {e}")
		raise
```
Target reorder is RESEARCH Pattern 2 (validate → funds invariant → position mutate → cash apply →
record), each step one manager call, no sibling-touching. Keep the `transaction.portfolio_id` /
`transaction.position_id` assignment placement.

**Cash setter to DELETE** — lines 216-225 (D-05); `cash` property (`:205-214`) survives, lock-free.
**`transact_shares`** (`:382-402`) — its `return True` / bool contract follows `process_transaction`
to raise/None (RESEARCH Pattern 2 deletions note); `PortfolioHandler.on_fill`'s `return result`
follows.

---

### `itrader/order_handler/order_manager.py` (manager, admission path)

**Indentation: tabs.**

**The audited-REJECTED pattern to copy for reserve-failure (D-02)** — `process_signal` lines 152-168
is the EXACT shape a failed reservation reuses:
```python
if not validation_result.success:
	error_msg = f"Signal validation failed: {validation_result.summary}"
	self.logger.error('%s - %s', error_msg,
					[msg.message for msg in validation_result.errors])
	# Audited PENDING→REJECTED transition; the timestamp defaults to
	# the order's own event-derived time (M2-09 — never wall clock).
	primary.add_state_change(
		OrderStatus.REJECTED,
		validation_result.summary,
		triggered_by="validator",
	)
	self.order_storage.add_order(primary)
	return [OperationResult.failure_result(error_msg,
		error_details=str(validation_result.errors),
		operation_type="signal_validation")]
```
For check-and-reserve: same shape with `triggered_by="cash_reservation"`, catching
`InsufficientFundsError` from `protocol.reserve(...)` (RESEARCH "Code Examples" admission sketch).
Placement: after step 2 validation, before step 3 `_assemble_bracket_and_emit` (`:175-176`).
D-03 gate: only when the primary is a BUY (`signal_event.action is Side.BUY` — see Side dispatch
at `:325, 443`).

**Constructor retype (D-16/D-18)** — current constructor lines 41-68:
```python
def __init__(self, order_storage: OrderStorage, logger: Any, order_handler_ref: Any,
             market_execution: str = "immediate", portfolio_handler: Any = None) -> None:
	self.order_storage = order_storage
	self.logger = logger
	self.order_handler = order_handler_ref      # ← DELETE (never used, D-18)
	self.market_execution = market_execution
	self.portfolio_handler = portfolio_handler  # ← retype to PortfolioReadModel
	self.order_validator = EnhancedOrderValidator(portfolio_handler) if portfolio_handler else None
```
Storage ownership moves here (D-18 + discretion): either constructed in the manager via
`OrderStorageFactory.create_in_memory()` (current call shape at `order_handler.py:61`) or injected
— planner picks; the handler stops holding `self.order_storage`.

**Reservation amount math (D-04)** — must mirror the existing sizing/funds shapes:
`_resolve_signal_quantity` line 460 (`raw_qty = (Decimal("0.95") * portfolio.cash) / to_money(price)`)
shows the Decimal-native intermediate convention (full precision, quantize never on intermediates —
comment block `:450-459` is the house rule, copy its reasoning style). Reservation =
`primary.price * primary.quantity + estimated_commission` in Decimal (Order entity money is
already Decimal).

**Reservation release (RESEARCH OQ2 recommended)** — `on_fill` lines 70-102 is the reconciliation
seam; the idempotent `protocol.release(order_id)` call slots after the terminal-state branch,
before/alongside `self.order_storage.update_order(order)` + `deactivate_order` (`:99-100`). Note
`deactivate_order` dies with the nested dicts (Pitfall 6) — status change alone moves the order
out of active queries.

---

### `itrader/order_handler/order_handler.py` (facade, event-driven)

**Indentation: tabs.**

**The target facade shape already exists** — `on_signal` lines 73-97: delegate to manager, put
returned events on queue, nothing else:
```python
operation_results = self.order_manager.process_signal(signal_event)
for result in operation_results:
	if result.order_events:
		for order_event in result.order_events:
			self.events_queue.put(order_event)
```
**Copy this pattern to ALL paths** (D-18: handler owns ALL queue puts; manager returns events).

**Deletions:** `add_pending_order` / `remove_orders` / `remove_order` lines 104-134 (verbatim the
"Legacy method" blocks); concrete import line 4
(`from ..portfolio_handler.portfolio_handler import PortfolioHandler`) → replaced by
`from itrader.core.portfolio_read_model import PortfolioReadModel`; constructor annotation `:38`
retypes; `self.order_storage` (`:61`) moves into the manager; `get_*`/`search_*` reads (`:238-356`)
delegate through `self.order_manager`.

---

### `itrader/order_handler/storage/in_memory_storage.py` (storage backend, CRUD)

**Indentation: 4 spaces** (this file uses spaces).

**Keep ONLY the flat index** — lines 40-41 and the `_by_id` writes:
```python
# Flat global order index for O(1) cross-portfolio lookup (D-14, PERF2)
self._by_id: Dict[Any, 'Order'] = {}
```
**Delete:** `active_orders` / `all_orders` / `archived_orders` (`:31-38`) and every dual-write
(`add_order` `:43-56` shrinks to the `_by_id[order_key] = order` line). Queries become
scan-and-filter over `self._by_id.values()` using entity predicates (`order.is_active`,
`order.portfolio_id == ...`, `order.ticker == ...`) — Pitfall 6 maps the semantics
(`deactivate_order` → no-op/delete after caller check; `archive_orders` → verify callers, likely
delete). Type the dict `Dict[uuid.UUID, 'Order']` (keying already native UUID per `:21-23` docstring).

---

### `itrader/portfolio_handler/base.py` + storage backend (seam, per-reference reservations)

**Indentation: `PortfolioStateStorage` uses 4 spaces** (`:93+`; the legacy ABCs above it use tabs —
match the class you edit).

**abstractmethod + NumPy-docstring seam pattern** — copy from lines 250-270:
```python
    @abstractmethod
    def get_reserved_cash(self) -> Decimal:
        """Return the currently reserved cash amount.

        Returns
        -------
        Decimal
            The reserved cash balance.
        """
        pass

    @abstractmethod
    def set_reserved_cash(self, amount: Decimal) -> None:
        """Set the reserved cash amount.
        ...
        """
        pass
```
New per-reference methods (`add_reservation(reference_id, amount)`,
`pop_reservation(reference_id) -> Decimal | None` — RESEARCH Pattern 1) follow this exact shape;
`get_reserved_cash()` becomes the sum. The per-reference dict in the in-memory backend mirrors the
order storage's `_by_id` flat-dict pattern.
**Delete from the seam:** `set_pending_transaction` / `remove_pending_transaction` /
`get_pending_transactions` (`:191-224`) — the TransactionContext working-state container (D-11) —
in both the ABC and the in-memory backend.

---

### `itrader/portfolio_handler/portfolio_handler.py` (handler, Protocol implementer)

**Indentation: tabs.** Deletions per RESEARCH Pattern 4: `readerwriterlock` import (`:11`),
`_portfolios_lock` (`:70`), `_operations_lock` (`:74`) — but Pitfall 8: `_operation_context` also
carries correlation-id + `_publish_error_event` wiring; keep those.

**Protocol implementation (D-16 — structural, no inheritance):** add plain methods
`available_cash` / `get_position` / `reserve` / `release` delegating to the portfolio's
`cash_manager` / `position_manager`. Delegation precedent in-tree: `Portfolio.get_open_position`
(`portfolio.py:328-330`):
```python
	def get_open_position(self, ticker: str) -> Any:
		"""Get an open position by ticker."""
		return self.position_manager.get_position(ticker)
```
`get_position` builds the frozen `PositionView` from the live `Position` (live objects inside,
snapshots across the boundary — D-15); returns `None` when flat.

---

### `itrader/portfolio_handler/transaction/transaction.py` + `transaction_manager.py`

**Linkage-field pattern for `Transaction.fill_id`** — copy from `events/fill.py` lines 42-50, 61-63
(REQUIRED field, docstring states the audit-chain purpose):
```python
    fill_id: uuid.UUID
    order_id: OrderId
    strategy_id: StrategyId
```
with the docstring convention: "REQUIRED — ... carried ... for the full fill -> order -> strategy
audit chain (D-12)."

**TransactionManager shrink:** delete `TransactionContext` dataclass, `_handle_transaction_error`,
pending-dict calls (`transaction_manager.py:24-33, 90-142, 292-337` per RESEARCH), the
`_check_funds_availability`-after-mutation flow, and the `transaction_manager.py:237-256` interim
cash seam (it calls `apply_transaction_delta` — replaced by `Portfolio`-orchestrated
`cash_manager.apply_fill_cash_flow`). Survivors: validation (pure checks, raise
`InvalidTransactionError` — construction pattern at `cash_manager.py:135-138`), recording
(`self._storage.add_transaction(...)` via the seam), history queries. Its `_lock` and
sibling-reaches into `self.portfolio.cash_manager` (`:246`) die.

---

### `itrader/core/enums/portfolio.py` (enum module)

**Indentation: 4 spaces.** Delete `TransactionState` (`:126-138+`) and its map (D-11). If
`CashOperationType` members change (discretion), keep the existing `_missing_` pattern (`:71-77`):
```python
    @classmethod
    def _missing_(cls, value: object) -> "CashOperationType":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            ...
```

---

### `itrader/execution_handler/base.py` (real ABC) + `result_objects.py` + `exchanges/{base,simulated}.py`

**Real-ABC pattern** — model `AbstractExecutionHandler` on the in-tree real ABC,
`portfolio_handler/base.py::PortfolioStateStorage` (`:93-112`): class docstring explaining the
seam + decision refs, `@abstractmethod` per method, NumPy-style param docs. Current file
(`execution_handler/base.py:1-30`) declares only `on_order` and carries the stale Compliance
docstring (`:16-18`) — add `on_market_data` (signature precedent: `exchanges/base.py:27-33`),
drop the Compliance paragraph. **Indentation: tabs** (current file).

**`exchanges/base.py` Protocol retype** — `execute_order` signature at `:35-39` changes
`-> ExecutionResult` to `-> None`; the `ExecutionResult` import at `:4` dies. Surviving DTOs in
`result_objects.py` get the `@dataclass(frozen=True, slots=True)` + Decimal treatment per the
`events/order.py:15` pattern. `ValidationResult` collision: rename the execution-domain one
(RESEARCH OQ3 — e.g. `OrderPreflightResult`); the order-domain `order_validator.py:28` keeps the name.

**`simulated.py`:** `_lock` (`:81`) deleted (D-19); discarded `execute_order` return at `on_order`
(`:284` per RESEARCH) becomes a plain call; `commission=float(commission)` / `commission=0.0`
coercions (`:211,236,253,273`) become Decimal per D-22.

---

### `itrader/events_handler/events/{signal,order,fill}.py` (D-22 Decimal retype)

**The exact removal target** — `order.py` lines 66-75, the boundary-coercion block whose comment
explicitly says "remain float until M4":
```python
		# Boundary coercion (M2a): the Order entity carries Decimal money, but the
		# OrderEvent + execution/matching/fee layer remain float until M4. Coerce
		# here so the float execution layer stays consistent; ...
		return cls(
			...
			price=float(order.price),
			quantity=float(order.quantity),
```
Retype `price/quantity/stop_price` (order), `price/stop_loss/take_profit/quantity` (signal),
`price/quantity/commission` (fill) to `Decimal`; pass entity Decimals through. The construct-complete
factory shape (`fill.py:71-117` `new_fill` with keyword-only executed values) is preserved — only
the types change.

**Money-entry rule for every float→Decimal crossing** — `core/money.py` lines 42-49:
```python
def to_money(x: float | int | str | Decimal) -> Decimal:
    """Enter the Decimal domain via the string path (D-04).

    ``Decimal(str(x))`` avoids the binary float-repr artifact ...
    NEVER call ``Decimal(float)`` directly.
    """
    return Decimal(str(x))
```
Apply at: strategy float prices entering `SignalEvent`, bar-OHLC float entering fill prices in
`matching_engine`/`simulated.py` (Pitfall 4 — `Decimal * float` raises `TypeError`; the engineered
invariant is "the Decimal reaching the cash ledger equals `to_money(old_float_value)` for every fill").

---

### `itrader/strategy_handler/position_sizer/variable_sizer.py` + `risk_manager/advanced_risk_manager.py` + `order_validator.py` (Protocol retype, D-17)

Mechanical retype: kill `from itrader.portfolio_handler.portfolio_handler import PortfolioHandler`
(`variable_sizer.py:2`; same import in the other two), annotate constructors with
`PortfolioReadModel`, map reads per the RESEARCH consumer inventory
(`.cash` → `available_cash()`, `.get_open_position(t).net_quantity` →
`get_position(t).net_quantity`). The validator reads MORE than the locked surface (`exchange`,
`n_open_positions`, `positions`, `total_equity`) — RESEARCH OQ1 holds the reconciliation options;
planner must pick and document.

### `itrader/trading_system/{backtest,live}_trading_system.py` (wiring)

Order-storage construction moves per the manager-ownership decision
(`backtest_trading_system.py:68-69`, `live_trading_system.py:111-117` are the current injection
sites); fee-estimator injection into `OrderManager` per RESEARCH Pattern 1 (the `fee_model`
already returns Decimal — `fee_model/base.py:16-23`).

## Shared Patterns

### Logger binding
**Source:** `itrader/portfolio_handler/cash/cash_manager.py:50` (same in every handler/manager)
**Apply to:** any new class
```python
from itrader.logger import get_itrader_logger
self.logger = get_itrader_logger().bind(component="CashManager")
```

### Typed domain exception (raise-typed, return-None contract)
**Source:** `itrader/core/exceptions/portfolio.py:20-29`
**Apply to:** reserve failures, settlement invariant guard, transaction validation
```python
class InsufficientFundsError(PortfolioError):
    def __init__(self, required_cash: float, available_cash: float, transaction_id: "Optional[TransactionId | int]" = None):
        self.required_cash = required_cash
        self.available_cash = available_cash
        ...
        super().__init__(
            f"Insufficient funds: Required ${required_cash:.2f}, Available ${available_cash:.2f}"
        )
```
Construction call shape: `cash_manager.py:357-360` (`required_cash=float(...), available_cash=float(...)`).
The exception fields stay float (diagnostics, not money ledger).

### Decimal money entry
**Source:** `itrader/core/money.py:42-49` (`to_money` — D-04 string path)
**Apply to:** every float→Decimal crossing (strategy signals, bar OHLC at fill construction, modify args)
Quantize ONLY at money boundaries via `money.quantize(value, instrument, kind)` (`:52-65`) —
never on intermediates, and NEVER on trade-path cash deltas (Pitfall 1).

### Deterministic IDs + event-derived time
**Source:** `itrader/events_handler/events/fill.py:9,114` (`uuid_compat.uuid7()`) and
`itrader/portfolio_handler/portfolio.py:50` (`idgen.generate_portfolio_id()`)
**Apply to:** new `CashOperation` records, any new audit entries. Timestamps come from the
transaction/fill event time, never `datetime.now()` (M2-09; see `order_manager.py:158-159` comment).

### Decision-annotated docstrings/comments
**Source:** everywhere edited in Phases 2-4 (e.g. `order_manager.py:104-118`, `money.py:1-23`)
**Apply to:** all new/changed code — cite the D-xx decision ID at the point it shaped the code
("D-19: single-writer contract — ...", "D-10: returns None, raises typed").

### Indentation map (match the file)
| Tabs | Spaces (4) |
|------|------------|
| `portfolio.py`, `portfolio_handler.py`, `order_handler.py`, `order_manager.py`, `execution_handler/base.py`, legacy ABCs in `portfolio_handler/base.py` | `cash_manager.py`, `PortfolioStateStorage` class, `order_handler/storage/in_memory_storage.py`, `core/*`, `events_handler/events/*`, all NEW modules |

### Suite/oracle gate (every commit)
`poetry run pytest tests/unit -q -x` per task; `make test && make typecheck` +
`poetry run pytest tests/integration/test_backtest_oracle.py -q` per money-path/retype commit.
Oracle assertions in `tests/integration/test_backtest_oracle.py` MUST NOT be modified (M4-08).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| Per-reference reservation container (seam extension) | storage | CRUD | The seam holds reserved cash as a single aggregate today (`portfolio_handler/base.py:251-270`); no per-reference precedent exists. Closest pattern: order storage's flat `{id: entity}` dict (`order_handler/storage/in_memory_storage.py:41`) — use a `dict[OrderId, Decimal]` with the same flat-index shape. |

Everything else in the phase has an exact in-tree precedent — RESEARCH's "Don't Hand-Roll" table
confirms: building anything novel this phase is a smell.

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/portfolio_handler/`, `itrader/order_handler/`,
`itrader/execution_handler/`, `itrader/events_handler/events/`, `itrader/strategy_handler/{position_sizer,risk_manager}/`
**Files read in full:** 10 (exchanges/base.py, events/order.py, events/fill.py, core/ids.py,
core/money.py, cash_manager.py, order_manager.py, portfolio.py, portfolio_handler/base.py,
execution_handler/base.py) + targeted sections of order_handler.py, in_memory_storage.py, enums/portfolio.py
**Pattern extraction date:** 2026-06-06
