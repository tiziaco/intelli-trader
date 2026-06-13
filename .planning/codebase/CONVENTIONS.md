# Coding Conventions

**Analysis Date:** 2026-06-12

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package — `execution_handler/exchanges/base.py`, `order_handler/base.py`.
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Test files mirror source: `test_<module>.py` — `test_order_manager.py`, `test_matching_engine.py`.

**Functions/Methods:**
- `snake_case` always.
- Event handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Module-private module-level constants: leading underscore — `_ONE = Decimal("1")`, `_DEFAULT_SCALES`.

**Classes:**
- `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.

**Variables:**
- `snake_case` always.
- Shared event queue: always named `global_queue` (constructor parameter) or `events_queue`.
- Bound logger: always `self.logger`.
- Config: always `self.config` (or a typed config object such as `SystemConfig`).

**Enums:**
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

**Formatting:**
- No autoformatter configured (no black/ruff/prettier). Match surrounding file indentation by hand.
- **Tabs:** handler/manager modules under `itrader/order_handler/`, `itrader/portfolio_handler/`, `itrader/execution_handler/`, `itrader/strategy_handler/` use tab indentation.
- **4 spaces:** newer/refactored modules use spaces — `itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`, `itrader/core/clock.py`, `itrader/events_handler/events/`, all test files.
- **Rule:** ALWAYS match the indentation of the file being edited. Do NOT normalize. A mixed-indentation diff breaks a tab file.

**Static Analysis:**
- **mypy** is the only gate (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).
- `--strict-markers` and `--strict-config` enforced in pytest.
- `filterwarnings = ["error", ...]` — unexpected warnings fail tests.
- No `.flake8`, `.pylintrc`, `ruff.toml`, or `.pre-commit-config.yaml`.

**Type Annotations:**
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (live trading, SQL stores, ccxt/oanda providers, screeners, `my_strategies`).

## Import Organization

- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`.
- No path aliases (`tsconfig`-style aliases do not exist in this Python project).
- Standard library imports come before third-party, before local — standard Python convention, not enforced by tooling.

## Error Handling

**Exception Hierarchy (`itrader/core/exceptions/`):**
- Root: `ITraderError` (`base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `itrader/core/exceptions/data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- Execution failures flow as `FillEvent(REFUSED)` events, not exceptions; execution error codes live in `core/enums/execution.py::ExecutionErrorCode`.

**Patterns:**
- Exceptions carry structured fields and build their message in `__init__` — e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`.
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False`.
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- Rejections flow as events: `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits `FillEvent(REFUSED)`.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` in `itrader/core/money.py`. NEVER call `Decimal(float)` directly.
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization).
- `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- `float()` appears only at the serialization/logging edge.

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils` (`uuid_utils.compat.uuid7()`). Do not introduce a second ID scheme.
- Determinism: one seeded `random.Random` constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call.

## Logging

- Bind a component context at construction: `self.logger = get_itrader_logger().bind(component="ClassName")`.
- Import: `from itrader.logger import get_itrader_logger`.
- Levels:
  - `info` — successful ops/initialization.
  - `warning` — non-fatal issues (unknown exchange, skipped event).
  - `error` — caught exceptions with `exc_info=True`.
  - `debug` — rarely used.
- Framework: `structlog` (`itrader/logger.py`); console (color) or JSON renderer via `ITRADER_JSON_LOGS` env var.

## Comments & Docstrings

**Module docstrings:**
- Triple-quoted docstring opening each module. Frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`) tying code to refactor planning artifacts. Preserve this style — these tags are load-bearing references.

**Class docstrings:**
- Summary describing responsibilities, often a bulleted list of what the class owns.

**Function docstrings:**
- One-line or NumPy-style `Parameters`/`Returns` blocks (see `itrader/execution_handler/execution_handler.py`).

**Inline comments:**
- Used to explain WHY, often referencing a decision tag or pitfall — e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`. Avoid restating what the code does.

## Handler/Manager Design Pattern

- `<Domain>Handler` — thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. No business logic.
- `<Domain>Manager` — owns the business logic and has NO queue access and NO back-reference to its handler. Layering is one-directional: `facade → manager → storage`.
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — emit an event onto the queue instead.
- Read-only cross-domain access goes through an injected read-model (e.g. `PortfolioReadModel` Protocol in `itrader/core/portfolio_read_model.py`).
- Events are `@dataclass(frozen=True, slots=True, kw_only=True)` subclasses of `Event`; value objects use `@dataclass` (often `frozen=True`).

## Module Exports (Barrels)

- `__init__.py` files act as barrels re-exporting the domain's public surface.
- Example: `itrader/core/enums/__init__.py` re-exports all enums grouped by domain with comment headers.
- `itrader/__init__.py` initializes process-wide singletons on import: `config = SystemConfig.default()`, `logger`, `idgen`. Import these via `from itrader import config, idgen`.

## Config-Enum Convention (Pinned)

- Seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `itrader/config/`, NOT `itrader/core/enums/`. Relocating would invert the `core→config` dependency direction. Do NOT move them.

## Tab/Space Hazard (Pinned)

- Handler modules use tabs; `config/`, `core/`, and `events_handler/events/` use 4 spaces. A mixed-indentation diff in a tab file breaks the file. Match the file you edit.

## Dual-Layer Order-Validator Overlap (W4-04, Pinned)

- The order domain runs TWO validation layers by design (defense-in-depth): the
  domain `EnhancedOrderValidator` (`itrader/order_handler/order_validator.py`) on
  the `process_signal` admission path, and the exchange-side checks in
  `itrader/execution_handler/exchanges/simulated.py`. The overlap is
  justified-by-decision — the live `TradingInterface` / `OrderEvent` path
  bypasses the domain validator, so the exchange layer is the only gate there.
  The duplicated action check is **NOT** removed.
  *(D-03a, Phase 6 / W4-09: the dead, unvalidated `OrderHandler.create_order`
  second path was removed — it no longer justifies the overlap; the live-path
  bypass alone does. The validator code stays.)*
- **SIG-03 / D-03 update (Phase 5):** `Order.action` (and `_PendingBracket.action`)
  are now `Side`-typed (narrowed from `str`). The domain validator's action check
  was `order.action not in ["BUY", "SELL"]` (string membership) and is now
  `order.action not in (Side.BUY, Side.SELL)` (Side-member identity); the
  `_is_closing_position` compares are `order.action is Side.SELL/is Side.BUY`.
  The former string-membership literal at `order_validator.py:193` is **dead**
  after the retype — a non-Side action can no longer reach the validator from the
  factories (mypy --strict checks side handling end-to-end inside `order_handler`).
  The dual-layer structure itself is unchanged; only the action comparison was
  narrowed.

---

*Convention analysis: 2026-06-12*
