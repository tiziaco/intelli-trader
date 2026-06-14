# Coding Conventions

**Analysis Date:** 2026-06-14

> This file is the **authoritative home** for the four pinned project conventions
> (config-enum exception, broad-`except` run-mode policy, tab/space indentation
> hazard, dual-layer order-validator overlap). They are documented here so they are
> not re-litigated. See **Documented Conventions (Pinned)** at the end.

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `itrader/execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Tests mirror source: `test_<module>.py` (e.g. `tests/unit/order/test_order_manager.py`).

**Functions:**
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
- **No autoformatter configured** (no `black`/`ruff`/`prettier` config present). Match the surrounding file by hand.
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml`, `setup.cfg` all absent).

**Linting / static analysis:**
- The **only** static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`). Run via `make typecheck` → `poetry run mypy itrader`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`, `postgresql_storage`). Do NOT rely on these being typed; new code should be strict-clean.
- Third-party stubless libs (`ta.*`, `pandas_ta.*`, `ccxt.*`, `pandas.*`, `scipy.*`, `plotly.*`, `sklearn.*`, `statsmodels.*`, etc.) are `ignore_missing_imports = true`.

**Indentation (correctness hazard — see Pinned):**
- **Tabs:** most handler/manager modules under `itrader/` use tab indentation — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
- **4 spaces:** newer refactored modules use spaces — `itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`, `itrader/price_handler/feed/`, `itrader/events_handler/events/`.
- **Rule:** ALWAYS match the indentation of the file being edited. Do NOT normalize. A mixed-indentation diff in a tab file will break the file.

**Type hints:**
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.

## Import Organization

**Order (observed, not enforced by tooling):**
1. Standard library (`pathlib`, `queue`, `datetime`, `decimal`).
2. Third-party (`pytest`, `pandas`, `pydantic`).
3. First-party `itrader.*`.

**Relative vs absolute:**
- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. **Match the file.**
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`, `from itrader import config`.

**Path Aliases:**
- None — Python package imports only. No `tsconfig`-style aliases.

**Import side effects (constraint):**
- Importing anything from `itrader` triggers singleton init in `itrader/__init__.py` (`config`, `logger`, `idgen`). Do not import `itrader` in fixtures without understanding this.

## Error Handling

**Exception hierarchy** (`itrader/core/exceptions/`):
- Root: `ITraderError` (`base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).

**Patterns:**
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False`.
- Rejections flow as **events, not exceptions**: `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles. Execution error codes live in `itrader/core/enums/execution.py::ExecutionErrorCode`.
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order` / `on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `EventHandler._log_error_event` is the real `ERROR`-route consumer (structured log sink, severity-mapped).

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). **NEVER** call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live in `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` in `itrader/core/money.py`.
- `float()` appears ONLY at the serialization/logging edge.

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do NOT introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call. An injected `BacktestClock` (`itrader/core/clock.py`) is staged on the determinism seam.

## Logging

**Framework:** `structlog` (`itrader/logger.py`).

**Patterns:**
- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")` (21 occurrences across handlers).
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True` (12 occurrences); `debug` rarely used.

## Comments & Docstrings

**When to comment:**
- Comments explain **WHY**, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.

**Module / class / function docstrings:**
- Heavy, decision-anchored. Modules open with a triple-quoted docstring that frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`) tying the code to the refactor plan. **Preserve this style** — these tags are load-bearing references to planning artifacts.
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (see `ExecutionHandler.__init__`).

## Function & Module Design

**Handler/Manager split:**
- `<Domain>Handler` is a **thin interface**: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage; see `OrderManager` D-18 note).

**Cross-domain communication:**
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel` Protocol, `BacktestBarFeed`).

**Value objects / events:**
- Events and value objects are `@dataclass` (often `frozen=True` — e.g. events, `_PendingBracket`, `Bar`). Events are `@dataclass(frozen=True, slots=True, kw_only=True)` subclasses of `Event`; `type` pinned via `field(default=EventType.X, init=False)`.

**Exports / barrels:**
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain with comment headers).

## Documented Conventions (Pinned — do NOT re-litigate)

These four are intentional design decisions, pinned so reviewers stop flagging them:

1. **Config-enum exception (D-NN).** The seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `itrader/config/` NOT `itrader/core/enums/` **by design** — relocating them would invert the core→config dependency (`core/` depends on nothing inside `itrader`).

2. **Broad-`except` run-mode policy.** Backtest **fail-fast** (`EventHandler._on_handler_error` re-raises) vs live **publish-and-continue** (`LiveTradingSystem` emits `ErrorEvent` and keeps draining) is **intentional**, not an inconsistency.

3. **Tab/space indentation hazard.** Handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, `events_handler/events/` use 4 spaces. Match the file you edit; never normalize.

4. **Dual-layer order-validator overlap (D-03a, W4-09).** The overlap between `order_handler/order_validator.py` and `execution_handler/exchanges/simulated.py` is **justified-by-decision** (defense-in-depth — the live `TradingInterface`/`OrderEvent` path bypasses the domain validator). The dead `create_order` second path was removed (W4-09); the live-path bypass alone now justifies keeping the overlap. The code is NOT removed.

---

*Convention analysis: 2026-06-14*
