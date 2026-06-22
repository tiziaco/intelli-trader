# Coding Conventions

**Analysis Date:** 2026-06-22

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package — `execution_handler/exchanges/base.py`, `price_handler/feed/base.py`.
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Tests mirror source: `test_<module>.py` — `test_order_manager.py`, `test_cash_manager.py`.

**Functions:**
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Module-private constants: leading underscore — `_ONE = Decimal("1")`, `_DEFAULT_SCALES`.

**Variables:**
- `snake_case` always.
- The shared event queue: always `global_queue` (constructor parameter) or `events_queue`.
- Bound logger: always `self.logger`.
- Config object: always `self.config` (or a typed `SystemConfig`).

**Types/Classes:**
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.
- Enum names: `PascalCase`; members: `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

**Formatting:**
- No autoformatter configured (no black/ruff/prettier). Match the surrounding file by hand.
- **Critical indentation rule:** handler/manager modules under `itrader/` use **tabs** — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`. Newer refactored modules (`itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`, `itrader/events_handler/events/`) use **4 spaces**. Always match the file being edited. A mixed-indentation diff in a tab file breaks it.

**Linting:**
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The only static-analysis gate is `mypy --strict` (`pyproject.toml [tool.mypy]`, `files = ["itrader"]`), run via `make typecheck`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]`: live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`. Do not add new code to these subsystems without acknowledging the type debt.

**Type Annotations:**
- Required and enforced by `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.

## Import Organization

**Pattern:**
- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`.
- No path aliases — Python package imports only.

**Side-effect warning:**
- Importing anything from `itrader` triggers singleton init in `itrader/__init__.py` (`config`, `logger`, `idgen`). Do not import `itrader` in fixtures or test setup without understanding this.

## Error Handling

**Exception hierarchy (root: `itrader/core/exceptions/base.py`):**
- `ITraderError` — root base.
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `itrader/core/exceptions/data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- Execution failures flow as `FillEvent(REFUSED)` events, **not** exceptions; error codes live in `itrader/core/enums/execution.py::ExecutionErrorCode`.

**Patterns:**
- Raise typed exceptions, not bare `Exception` or boolean returns.
- `ValidationError(field, value, message)` and `StateError(entity_id, current_state, ...)` carry structured fields and build their message in `__init__`.
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- Rejections flow as events: `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Run-mode distinction: backtest uses fail-fast (`EventHandler._on_handler_error` re-raises); live trading uses publish-and-continue (emit `ErrorEvent`, keep draining). This is an intentional locked decision (not an inconsistency).

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision, `itrader/core/money.py`).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))`. NEVER call `Decimal(float)` directly.
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization).
- `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- `float()` appears only at the serialization/logging edge.
- Test data follows the same rule: `Decimal(str(price))` or `Decimal("literal")`, never `Decimal(0.95)`.

## IDs and Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config `performance.rng_seed`, default 42). Never seed per-call.
- `BacktestClock` (`itrader/core/clock.py`) is an injected deterministic clock; never use wall clock for business time.

## Logging

- Bind component context at construction: `self.logger = get_itrader_logger().bind(component="ClassName")`.
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues; `error` for caught exceptions with `exc_info=True`; `debug` rarely used.
- Configured via structlog (`itrader/logger.py`); console (color) or JSON renderer set in `SystemConfig`.

## Comments and Docstrings

**Docstrings:**
- Modules open with a triple-quoted docstring; frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`) tying the code to planning artifacts. Preserve these tags — they are load-bearing references.
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use a one-line docstring or NumPy-style `Parameters`/`Returns` blocks.

**Inline comments:**
- Used to explain WHY, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.
- Cross-module citations in comments name both the SYMBOL and a line hint (e.g. `# SimulatedExchange.update_config — simulated.py:~99`). The symbol is the durable anchor; line numbers drift.

## Function and Module Design

**Handler/Manager split (enforced pattern):**
- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler — layering is one-directional (facade → manager → storage).
- See: `itrader/order_handler/order_handler.py` (handler) + `itrader/order_handler/order_manager.py` (manager).

**Component construction:**
- Components take `global_queue` as a constructor argument. Never call other handlers directly across domains — emit an event instead.
- Read-only cross-domain access goes through an injected read-model Protocol (e.g. `PortfolioReadModel` in `itrader/core/portfolio_read_model.py`).

**Events and value objects:**
- Events are `@dataclass(frozen=True, slots=True, kw_only=True)` subclassing `Event`; `type` is pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.
- Non-event value objects use `@dataclass` (often `frozen=True`) — e.g. `_PendingBracket`, `Bar`.

**Module exports:**
- `__init__.py` files act as barrels re-exporting the domain's public surface with comment headers grouping enums by domain (e.g. `itrader/core/enums/__init__.py`).

## Pinned Convention Exceptions

Four established conventions are documented in this file as exceptions so they are not re-litigated:

1. **Config-enum exception:** the seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `itrader/config/` not `itrader/core/enums/` by design — relocating inverts the core→config dependency.
2. **Broad-except run-mode policy:** backtest fail-fast vs live publish-and-continue is intentional, not an inconsistency.
3. **Tab/space indentation hazard:** described above — match the file, never normalize.
4. **Dual-layer order-validator overlap:** `itrader/order_handler/order_validator.py` / `itrader/execution_handler/exchanges/simulated.py` validation duplication is justified-by-decision (defense-in-depth for the live-path bypass). Do not remove it.

---

*Convention analysis: 2026-06-22*
