# Coding Conventions

**Analysis Date:** 2026-06-10

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `itrader/execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py` (`itrader/order_handler/storage/`).
- Pluggable model variants are one file per strategy: `itrader/execution_handler/fee_model/` (`zero`/`percent`/`maker_taker`), `slippage_model/` (`zero`/`fixed`/`linear`).
- Event domains split by file under `itrader/events_handler/events/` — `base.py`, `market.py`, `signal.py`, `order.py`, `fill.py`, `error.py`.

**Functions:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()` (`itrader/execution_handler/execution_handler.py`).
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_orders_by_ticker()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Money-domain helpers: `to_money()`, `quantize()` (`itrader/core/money.py`).

**Variables:**
- `snake_case` always.
- The shared event queue is always named `global_queue` (constructor parameter); inside handlers it is stored as `self.global_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed config object such as `SystemConfig`).
- Module-private module-level constants: leading underscore — `_DEFAULT_SCALES`, `_INSTRUMENT_SCALES` (`itrader/core/money.py`).

**Types:**
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map` (`itrader/core/enums/`).

## Code Style

**Formatting:**
- No autoformatter configured. No `black`, `ruff`, `prettier`, or `.editorconfig` present. Match the surrounding file by hand.
- **Indentation is file-dependent — ALWAYS match the file being edited; do not normalize:**
  - **Tabs:** most handler/manager modules under `itrader/` — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
  - **4 spaces:** newer refactored modules — `itrader/config/`, `itrader/core/` (`money.py`, `bar.py`, `ids.py`, `clock.py`), `itrader/price_handler/feed/`, the `itrader/events_handler/events/` package, and ALL test files under `tests/`.
- A mixed-indentation diff in a tab file will break the file.

**Linting:**
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml`, `setup.cfg` all absent).
- The only static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`). Run with `make typecheck`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (live trading, sql stores, ccxt/oanda/binance providers, screeners, `my_strategies`, `postgresql_storage`). Do not rely on these being typed; new code should be strict-clean.

## Type Hints

- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `dict[str, Optional[AbstractExchange]]`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `cast`, `assert_never`.
- Queue parameters are annotated `"Queue[Any]"` (string form) in handler constructors.
- Python target is 3.13 (`python_version = "3.13"`).

## Import Organization

**Order (observed):**
1. Standard library (`import random`, `from queue import Queue`, `from decimal import Decimal`).
2. Third-party (`import pytest`, `import pandas as pd`, `import pandas.testing as pdt`).
3. First-party `itrader.*` and intra-package relative imports.

**Path Aliases:**
- None — Python package imports only. No alias system.

**Conventions:**
- Both relative (`from .base import AbstractExecutionHandler`) and absolute (`from itrader.events_handler.events import ...`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Process-wide singletons are imported directly from the package root: `from itrader import config, idgen`, `from itrader import logger`.
- Importing anything from `itrader` triggers singleton init in `itrader/__init__.py` (`config = SystemConfig.default()`, `logger`, `idgen = IDGenerator()`). Do not import `itrader` in fixtures without understanding this side effect.

## Error Handling

**Hierarchy:**
- Root: `ITraderError` (`itrader/core/exceptions/base.py`).
- Base categories in `base.py`: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific files: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`, `InvalidTransactionError`), `itrader/core/exceptions/order.py`, `itrader/core/exceptions/data.py`.

**Patterns:**
- Raise typed exceptions, not bare `Exception` or boolean returns. Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).
- Validation/fee models raise `ValidationError` rather than returning `False`.
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order` / `on_market_data` wrap the body in `try/except Exception as e` and `self.logger.error(...)` to prevent queue stalls (`itrader/execution_handler/execution_handler.py`).
- Rejections flow as events, not exceptions: `SimulatedExchange.execute_order()` returns an `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Backtest error policy is **fail-fast** (`EventHandler._on_handler_error` re-raises); live mode overrides this with publish-and-continue (emit `ErrorEvent`, keep draining).

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision). `float()` appears ONLY at the serialization/logging edge.
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). NEVER call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live in `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` in `itrader/core/money.py`.

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call.

## Logging

**Framework:** `structlog` via `get_itrader_logger()` (`itrader/logger.py`).

**Patterns:**
- Bind a component context in `__init__`: `self.logger = get_itrader_logger().bind(component="ClassName")`.
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions (often with `exc_info=True`); `debug` rarely used.
- Logger is initialized first in handler constructors, before other state.
- Uses old-style `%s` lazy formatting in log calls: `self.logger.error('Unknown exchange specified: %s ...', event.exchange, ...)`.

## Comments & Docstrings

- Heavy, decision-anchored. Modules open with a triple-quoted docstring that frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `WR-NN`, `Pitfall N`) tying the code to the refactor plan. **Preserve this style — these tags are load-bearing references to planning artifacts.**
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (see `ExecutionHandler.__init__`).
- Inline comments explain WHY, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.
- Cross-module citations lead with the durable SYMBOL name; trailing `:line` numbers are approximate hints that drift (see `tests/e2e/conftest.py` IN-04 note).

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage).
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel` Protocol in `itrader/core/portfolio_read_model.py`).
- Events and value objects are `@dataclass` — events are `@dataclass(frozen=True, slots=True, kw_only=True)` subclasses of `Event` with `type` pinned via `field(default=EventType.X, init=False)`.
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain).

---

*Convention analysis: 2026-06-10*
