# Coding Conventions

**Analysis Date:** 2026-06-03

## Indentation

The codebase has a split-indentation situation — match the file you are editing:

- **Tabs:** Most handler modules under `itrader/` use tab indentation.
  - `itrader/order_handler/order.py` (tabs)
  - `itrader/order_handler/order_handler.py` (tabs)
  - `itrader/order_handler/order_manager.py` (tabs)
  - `itrader/portfolio_handler/portfolio.py` (tabs)
  - `itrader/execution_handler/execution_handler.py` (tabs)
  - `itrader/events_handler/event.py` (tabs)

- **4 spaces:** Newer refactored modules use 4-space indentation.
  - `itrader/portfolio_handler/portfolio_handler.py` (spaces)
  - `itrader/portfolio_handler/cash_manager.py` (spaces)
  - `itrader/portfolio_handler/position_manager.py` (spaces)
  - `itrader/portfolio_handler/transaction_manager.py` (spaces)
  - `itrader/config/` (spaces throughout)
  - `itrader/core/exceptions/` (spaces throughout)

**Rule:** Open the file before writing. Use whatever character the existing lines use. Do not mix within a file.

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` (e.g., `order_handler.py`, `execution_handler.py`)
- Manager classes: `<domain>_manager.py` (e.g., `order_manager.py`, `cash_manager.py`)
- Storage: `<backend>_storage.py` (e.g., `in_memory_storage.py`)
- Tests mirror source: `test_<module>.py`

**Classes:**
- `PascalCase` for all classes: `OrderHandler`, `PortfolioHandler`, `SimulatedExchange`, `MatchingEngine`
- Handler classes named `<Domain>Handler` — a thin interface delegating to `<Domain>Manager`
- Manager classes named `<Domain>Manager` — owns the business logic
- Abstract bases named `Abstract<Name>` (e.g., `AbstractExchange`, `AbstractExecutionHandler`)
- Config classes named `<Domain>Config` (e.g., `PortfolioConfig`, `ExchangeConfig`)
- Exception classes named `<Specific><Category>Error` (e.g., `PortfolioNotFoundError`, `InsufficientFundsError`)

**Functions/Methods:**
- `snake_case` throughout
- Event handler callbacks: `on_<event_type>()` — e.g., `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`
- Factory class methods: `new_<object>()` — e.g., `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`
- Boolean-returning properties: `is_<state>` — e.g., `is_active`, `is_fully_filled`, `is_partially_filled`
- Getter methods: `get_<thing>()` — e.g., `get_portfolio()`, `get_latest_state_change()`
- Private methods and attributes: `_<name>` with single underscore

**Variables:**
- `snake_case` always
- Queue variable: always named `global_queue` or `events_queue` in constructors
- Logger: always `self.logger` bound from `get_itrader_logger().bind(component="ClassName")`
- Config: always `self.config`

**Enums:**
- Enum names: `PascalCase` (e.g., `OrderType`, `OrderStatus`, `FillStatus`)
- Enum members: `UPPER_CASE` (e.g., `OrderStatus.PENDING`, `FillStatus.EXECUTED`)
- String-to-enum maps: `<domain>_<type>_map` (e.g., `order_type_map`, `order_status_map`, `fill_status_map`)

## Import Organization

**Order (within each file):**
1. Standard library (`queue`, `threading`, `datetime`, `typing`, `dataclasses`)
2. Third-party (`pandas`, `numpy`, `readerwriterlock`, `structlog`)
3. Internal absolute imports from `itrader.*` — used for cross-domain imports
4. Internal relative imports (`from .module import X`, `from ..domain import Y`) — used within a package

**Cross-domain rule:** When importing from a sibling handler package, use absolute `itrader.*` paths:
```python
from itrader.core.enums import OrderType, OrderStatus
from itrader.core.exceptions import PortfolioNotFoundError
from itrader.events_handler.event import FillEvent, OrderEvent
from itrader.logger import get_itrader_logger
from itrader import config, idgen
```

**Intra-package rule:** Use relative imports within the same handler package:
```python
from .order import Order
from .base import OrderBase, OrderStorage
from ..core.enums import OrderStatus
```

**No path aliases** — the project does not use import aliases or `__init__.py` re-exports beyond what is shown in `itrader/__init__.py`.

## Dataclasses and Type Hints

Events and core data objects are Python `dataclasses`:
```python
@dataclass
class OrderStateChange:
    from_status: Optional[OrderStatus]
    to_status: OrderStatus
    timestamp: datetime
    reason: str
    triggered_by: str = "system"
    additional_data: Optional[dict] = None
```

Type hints are used consistently on function signatures in newer modules (portfolio managers, config, exceptions). Older handler modules (events_handler, strategy_handler) use type hints less consistently.

Use `Optional[T]` from `typing` for nullable fields, not `T | None` (Python 3.10+ syntax not yet adopted uniformly).

## Module-level Singletons

`itrader/__init__.py` initializes three process-wide singletons on import:
- `config` — system configuration object
- `logger` — `ITraderStructLogger` instance
- `idgen` — `IDGenerator` instance

Import these directly in handler classes:
```python
from itrader import config, idgen
from itrader.logger import get_itrader_logger
```

Do NOT re-initialize these in handler constructors. Use `get_itrader_logger()` to get a logger, then `.bind(component="ClassName")` immediately.

## Logging

**Framework:** structlog via `itrader/logger.py`

**Pattern for every class:**
```python
from itrader.logger import get_itrader_logger

class MyHandler:
    def __init__(self, ...):
        self.logger = get_itrader_logger().bind(component="MyHandler")
        # ...
        self.logger.info("MyHandler initialized", key=value)
```

**Log levels:**
- `info` — successful operations, initialization messages
- `warning` / `warn` — non-fatal issues (unknown exchange, skipped event)
- `error` — caught exceptions, routing failures: `self.logger.error("msg", exc_info=True)`
- `debug` — fine-grained tracing (not common in current code)

**Structured fields:** Pass extra context as keyword arguments, not f-strings:
```python
# Correct
self.logger.info("Order filled", order_id=order.id, ticker=order.ticker)

# Avoid
self.logger.info(f"Order {order.id} filled for {order.ticker}")
```

## Error Handling

**Exception hierarchy:** All custom exceptions inherit from `ITradingSystemError` in `itrader/core/exceptions/base.py`.

**Domain exception packages:**
- `itrader/core/exceptions/base.py` — `ITradingSystemError`, `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`
- `itrader/core/exceptions/portfolio.py` — `PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`, etc.
- `itrader/core/exceptions/execution.py` — `ExecutionError`, `ExchangeConnectionError`, `OrderExecutionError`, etc.

**Raise domain-specific exceptions** rather than raw `ValueError`/`RuntimeError` wherever possible.

**Catching pattern in handlers:**
```python
try:
    result = self.some_operation(event)
except SpecificError as e:
    self.logger.error("Operation failed", reason=str(e))
    return None  # or False
except Exception as e:
    self.logger.error("Unexpected error", exc_info=True)
    return None
```

**Event queue errors:** If an operation fails and there is a corresponding error event type (e.g., `PortfolioErrorEvent`), publish it to the queue rather than raising into the event loop.

## Docstrings

**Module-level:** Triple-quoted docstring at file top describing purpose and key responsibilities.

**Class-level:** Triple-quoted docstring describing class role, key methods, and architectural constraints.

**Method-level:** Triple-quoted docstring with summary line. Parameters documented with NumPy-style format in critical public methods:
```python
def __init__(self, events_queue: Queue, ...):
    """
    Parameters
    ----------
    events_queue : Queue
        The events queue of the trading system
    """
```

Short private/utility methods often have no docstring.

## Handler-Manager Split

Every domain uses a two-layer pattern — always follow it when adding behavior:

- `OrderHandler` / `PortfolioHandler` / `ExecutionHandler` — thin interface, receives events from queue, delegates logic, emits events back to queue
- `OrderManager` / `CashManager` / `PositionManager` etc. — owns business logic, has no direct queue access

This ensures the queue boundary is never bypassed. Handlers must never call each other directly across domains — emit an event instead.

## Configuration

Access configuration through the domain config providers, not by reading raw files:
```python
from itrader.config import get_portfolio_config_provider, get_exchange_preset, PortfolioConfig
```

Config objects are dataclasses (`PortfolioConfig`, `ExchangeConfig`) with typed fields. Default presets are loaded via `get_<domain>_preset('default')`.

---

*Convention analysis: 2026-06-03*
