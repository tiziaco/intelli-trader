# Coding Conventions

**Analysis Date:** 2026-06-07

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions in the codebase
- Handler modules: `<domain>_handler.py` — e.g., `itrader/order_handler/order_handler.py`, `itrader/execution_handler/execution_handler.py`
- Manager modules: `<domain>_manager.py` — e.g., `itrader/order_handler/order_manager.py`, `itrader/portfolio_handler/cash_manager.py`
- Storage modules: `<backend>_storage.py` — e.g., `itrader/order_handler/storage/in_memory_storage.py`
- Test files: `test_<module>.py`, mirroring source paths under `tests/`

**Classes:**
- `PascalCase` for all classes: `OrderHandler`, `PortfolioHandler`, `SimulatedExchange`, `MatchingEngine`
- Handler classes: `<Domain>Handler` — thin interface delegating to `<Domain>Manager`
- Manager classes: `<Domain>Manager` — owns business logic
- Abstract bases: `Abstract<Name>` — e.g., `AbstractExchange`, `AbstractExecutionHandler`
- Config classes: `<Domain>Config` — e.g., `PortfolioConfig`, `ExchangeConfig`
- Exception classes: `<Specific><Category>Error` — e.g., `PortfolioNotFoundError`, `InsufficientFundsError`
- Enum classes: `PascalCase` — e.g., `OrderType`, `OrderStatus`, `FillStatus`

**Functions and Methods:**
- `snake_case` throughout
- Event handler callbacks: `on_<event_type>()` — e.g., `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`
- Factory class methods: `new_<object>()` — e.g., `Order.new_order()`, `FillEvent.new_fill()`, `OrderEvent.new_order_event()`
- Boolean-returning properties: `is_<state>` — e.g., `is_active`, `is_fully_filled`, `is_partially_filled`
- Getter methods: `get_<thing>()` — e.g., `get_portfolio()`, `get_latest_state_change()`
- Private attributes/methods: `_<name>` with single underscore

**Variables:**
- `snake_case` throughout
- Queue variable: always `global_queue` or `events_queue` in constructors
- Logger: always `self.logger = get_itrader_logger().bind(component="ClassName")`
- Config: always `self.config`

**Enum Members:**
- `UPPER_CASE` — e.g., `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `EventType.FILL`

**String-to-enum maps:**
- `<domain>_<type>_map` — e.g., `order_type_map`, `order_status_map`, `fill_status_map`

## Code Style

**Formatting:**
- No formatter enforced (no Ruff, Black, or Prettier config found)
- Mixed indentation in the codebase — **tabs** vs **4 spaces** both in use

**Indentation rule (critical):**
- **Tabs:** Most handler modules under `itrader/` — e.g., `itrader/order_handler/order_handler.py`, `itrader/execution_handler/matching_engine.py` use spaces; older handlers still use tabs. Match the file you edit.
- **4 spaces:** Newer refactored modules: `itrader/config/`, `itrader/core/`, `itrader/events_handler/events/`, `itrader/portfolio_handler/portfolio_handler.py`, all test files.
- **Rule:** Read the file first. Use the indentation style already present.

**Linting:**
- `mypy --strict` with `files = ["itrader"]` declared in `pyproject.toml`
- Several mypy `[[tool.mypy.overrides]]` blocks with `ignore_errors = true` for deferred subsystems (live trading, SQL, screeners, reporting)
- No flake8, ruff, or pylint config detected

**Type annotations:**
- Used throughout newer modules; constructor parameters annotated
- `Optional[X]` from `typing` used in older modules; newer code uses `X | None`
- `TYPE_CHECKING` guards used to avoid heavy runtime imports (e.g., `itrader/events_handler/full_event_handler.py:16`)
- `# type: ignore[assignment]` used sparingly for known mypy gaps (e.g., `itrader/order_handler/order.py:63`)

## Import Organization

**Order within files:**
1. Standard library (`import queue`, `from decimal import Decimal`, `from datetime import datetime`)
2. Third-party libraries (`import pytest`, `import pandas as pd`, `from pydantic import BaseModel`)
3. Internal imports — absolute for cross-domain, relative for same-package

**Path conventions:**
- Absolute imports: `from itrader.core.enums import OrderType` (preferred for cross-domain)
- Relative imports: `from .base import OrderBase` (acceptable within same package)
- Both patterns coexist: `from .order import Order` alongside `from itrader.logger import get_itrader_logger`
- No path alias configuration detected

**Module-level singletons (initialized on `import itrader`):**
- `config` — `SystemConfig` instance, accessed via `from itrader import config`
- `logger` — `ITraderStructLogger` instance, accessed via `from itrader import logger`
- `idgen` — `IDGenerator` instance, accessed via `from itrader import idgen`
- Source: `itrader/__init__.py`

## Money / Decimal Policy

This is a **hard correctness constraint**, not a style preference.

**D-04 — String entry rule:** Always enter `Decimal` via `Decimal(str(x))` or `core.money.to_money(x)`. Never call `Decimal(some_float)`.
```python
# CORRECT
from itrader.core.money import to_money
price = to_money(42.5)              # Decimal("42.5")
price = Decimal(str(42.5))          # Decimal("42.5")

# WRONG — carries binary float artifact
price = Decimal(42.5)               # Decimal("42.4999999...")
```

**D-01 — No mid-computation quantization:** Carry full 28-digit Decimal precision through all intermediate arithmetic. Call `core.money.quantize()` ONLY at cash ledger writes, reported PnL, and serialization.

**D-03 — ROUND_HALF_UP at boundaries:** `quantize(value, instrument, kind)` applies per-instrument scale (BTC 8dp, USD cash 2dp) using `ROUND_HALF_UP`. Source: `itrader/core/money.py`.

## Error Handling

**Exception hierarchy:**
- `itrader/core/exceptions/base.py` — `ITraderError`, `ValidationError`, `ConfigurationError`, `StateError`, `NotFoundError`
- `itrader/core/exceptions/portfolio.py` — `PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`, etc.
- `itrader/core/exceptions/order.py` — order-specific typed exceptions
- `itrader/core/exceptions/data.py` — data-related exceptions

**Raise-contract (not boolean-return):**
```python
# CORRECT — raise typed exceptions, return None on success
def validate_inputs(self, quantity: Decimal, price: Decimal) -> None:
    if quantity <= 0:
        raise ValidationError("quantity", str(quantity), "must be positive")

# WRONG — boolean returns mask error details
def validate_inputs(...) -> bool:
    ...
```

**Handler error policy:**
- `ExecutionHandler.on_order()` and `on_market_data()` catch exceptions per-exchange and log; they do not re-raise (prevents queue stalls)
- `PortfolioHandler` uses `_operation_context()` context manager that publishes `PortfolioErrorEvent` on failure
- `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` on rejection and emits `FillEvent(REFUSED)`
- **Backtest fail-fast policy:** `EventHandler._on_handler_error()` re-raises — handler failures abort the run; see `itrader/events_handler/full_event_handler.py:141`

**Logging patterns:**
- Use `self.logger = get_itrader_logger().bind(component="ClassName")` — always bound with component name
- `info` — successful operations, initialization messages
- `warning` — non-fatal issues (unknown exchange, skipped event)
- `error` — caught exceptions: `self.logger.error("msg", exc_info=True)`
- `debug` — fine-grained tracing (queue dispatch messages, order events)

## Docstrings

**Module-level docstrings:** Present in newer modules; describe constraints and design decisions referenced by labels like `D-01`, `D-12`, `M5-02` (milestone/decision codes used throughout the codebase). Example: `itrader/execution_handler/matching_engine.py`.

**Class docstrings:** `"""One-line summary.\n\nLonger description."""` format. Parameters often listed under `Parameters ----------`.

**Function/method docstrings:** NumPy-style with `Parameters`, `Returns` sections in public API methods. Event callbacks and internal methods use shorter single-line docstrings or inline comments.

**Inline comments:** Reference design decisions as label codes (e.g., `# D-12: Decimal end-to-end`, `# D-18: manager owns storage`). These are mandatory for non-obvious architectural choices.

## Dataclass Conventions

**Event dataclasses (frozen, immutable facts):**
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class FillEvent(Event):
    type: EventType = field(default=EventType.FILL, init=False)
    status: FillStatus
    ...
```
- All event classes: `frozen=True`, `slots=True`, `kw_only=True`
- `type` field: always `init=False`, set via `field(default=EventType.X, init=False)`
- Factory class methods `new_<event>()` for safe construction

**Value objects (frozen, no event machinery):**
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    time: datetime
    open: Decimal
    ...
```
- `Bar` (`itrader/core/bar.py`) is the canonical example — not an `Event` subclass

## Handler-Manager Split Pattern

**Handler (interface layer):**
- Receives events from the queue, delegates all logic to manager, emits events back to queue
- No storage reference retained (facade → manager → storage)
- Public API: `on_<event>()`, `<verb>_order()`, `get_<thing>()` methods

**Manager (logic layer):**
- Owns business logic and storage
- Has no direct queue access — returns operation results/events to the handler
- The handler enqueues returned events; the manager never does

Example: `itrader/order_handler/order_handler.py` (handler) delegates to `itrader/order_handler/order_manager.py` (manager).

## Queue Usage

**Cross-domain communication rule:** Handlers NEVER call other handler methods directly. All cross-domain interaction uses `self.events_queue.put(event)`.

```python
# CORRECT
self.events_queue.put(order_event)

# WRONG — direct cross-domain call
self.execution_handler.on_order(order_event)
```

---

*Convention analysis: 2026-06-07*
