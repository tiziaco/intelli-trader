# Coding Conventions

**Analysis Date:** 2026-06-08

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Tests mirror source: `test_<module>.py` (e.g. `test_order_manager.py`).

**Functions/Methods:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Module-private module-level constants: leading underscore — `_ONE = Decimal("1")`, `_DEFAULT_SCALES`.

**Variables:**
- `snake_case` always.
- The shared event queue is always named `global_queue` (constructor parameter) or `events_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed config object such as `SystemConfig`).

**Types:**
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

**Formatting:**
- No autoformatter configured (no black/ruff/prettier config present). Match the surrounding file by hand.
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The only static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).

**Indentation (CRITICAL — mixed by design):**
- **Tabs:** most handler/manager modules under `itrader/` use tab indentation — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
- **4 spaces:** newer refactored modules use spaces — `itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`.
- **Rule:** ALWAYS match the indentation of the file being edited. Do not normalize. A mixed-indentation diff in a tab file will break the file.

**Type hints:**
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`). Do not rely on these being typed; new code should be strict-clean.

## Import Organization

**Order (observed):**
1. Standard library (`from datetime import datetime`, `from decimal import Decimal`, `from queue import Queue`).
2. Third-party (`import pandas as pd`, `import pytest`).
3. Intra-package relative imports (`from .order import Order`, `from ..core.enums import OrderType`).
4. Absolute `itrader.` imports (`from itrader.events_handler.events import OrderEvent`, `from itrader.config import SystemConfig`).

- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`.

**Path aliases:**
- None — Python package imports only. No `tsconfig`-style aliases.

## Error Handling

**Exception hierarchy** (`itrader/core/exceptions/`):
- Root: `ITraderError` (`base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/execution.py` (`ExecutionError`, `ExchangeConnectionError`, `OrderExecutionError`).
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).

**Patterns:**
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False` (see `fee_model`).
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- Rejections flow as events, not exceptions: `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). NEVER call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live in `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` in `itrader/core/money.py`.

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call.

## Logging

**Framework:** `structlog`, configured in `itrader/logger.py`; the `logger` singleton is initialized in `itrader/__init__.py`.

**Patterns:**
- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")` (21 occurrences across handlers).
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True` (12 occurrences); `debug` rarely used.

## Comments & Docstrings

**Module docstrings:**
- Heavy, decision-anchored. Modules open with a triple-quoted docstring that frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`) tying the code to the refactor plan. Preserve this style — these tags are load-bearing references to planning artifacts.

**Class/function docstrings:**
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (see `ExecutionHandler.__init__`).

**Inline comments:**
- Used to explain WHY, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.

## Function & Module Design

**Handler–Manager split (core pattern):**
- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage; see `OrderManager` D-18 note).

**Construction convention:**
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead.

**Dataclasses:**
- Events and value objects are `@dataclass` (often `frozen=True` for immutability — e.g. `_PendingBracket`, `Bar`). Events carry a class-level `type = EventType.X`.

**Exports / barrel files:**
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain with comment headers).

---

*Convention analysis: 2026-06-08*
