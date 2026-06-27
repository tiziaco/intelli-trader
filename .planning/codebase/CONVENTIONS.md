# Coding Conventions

**Analysis Date:** 2026-06-27

This file is the **authoritative home** for iTrader's documented conventions. Four
established conventions are pinned here (see "Pinned Decisions" below) so they are
not re-litigated. When this document and inline code disagree, treat this document
as canonical and reconcile the code.

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `itrader/execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Events split by domain under `itrader/events_handler/events/`: `base.py`, `market.py`, `signal.py`, `order.py`, `fill.py`, `error.py`.
- Tests mirror source: `test_<module>.py` (e.g. `tests/unit/order/test_order_manager.py`).

**Functions:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers: single leading underscore — `_resolve_rng_seed()`, `_dispatch()`, `_on_handler_error()`.

**Variables:**
- `snake_case` always.
- The shared event queue is always named `global_queue` (constructor parameter) or `events_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed object such as `SystemConfig`).
- Private attributes: single leading underscore — `self._rng`, `self._storage`, `self._routes`, `self._resting`.
- Module-private constants: leading underscore — `_ONE = Decimal("1")`, `_DEFAULT_SCALES`, `_INSTRUMENT_SCALES`.

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
- **Indentation is file-dependent and must NEVER be normalized** (see Pinned Decision 3):
  - **Tabs:** handler/manager modules under `itrader/` — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
  - **4 spaces:** newer refactored modules — `itrader/config/`, `itrader/core/` (`money.py`, `bar.py`, `ids.py`, `clock.py`), `itrader/price_handler/feed/`, the `itrader/events_handler/events/` package, and the entire `tests/` tree.
  - **Rule:** ALWAYS match the indentation of the file being edited. A mixed-indentation diff in a tab file silently breaks the file.

**Linting:**
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The ONLY static-analysis gate is **`mypy --strict`** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).
- New code must be strict-clean. Several subsystems are deferred via `[[tool.mypy.overrides]]` (`ignore_errors = true`): live trading (`live_trading_system`, `trading_interface`), SQL stores (`sql_store`, `postgresql_storage`), CCXT/OANDA/Binance providers, `screeners_handler.*`, `my_strategies.*`. Do NOT rely on these being typed; do NOT add new debt to the in-scope backtest path.
- Stubless third-party libs (`ta`, `pandas_ta`, `ccxt`, `pandas`, `scipy`, `plotly`, `sklearn`, `statsmodels`, …) are silenced via `ignore_missing_imports` only — never via blanket `# type: ignore` on our code.

## Typing

- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used as needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Read-model boundaries are `typing.Protocol` (e.g. `PortfolioReadModel` in `itrader/core/portfolio_read_model.py`), satisfied structurally — never via inheritance.

## Import Organization

**Order:**
1. Stdlib (`datetime`, `decimal`, `queue`, `pathlib`, `uuid`).
2. Third-party (`pandas`, `pytest`, `pydantic`).
3. First-party (`itrader....`).

**Path Aliases:**
- None — Python package imports only.

**Style:**
- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import config, idgen`, `from itrader import logger`.
- **Import side effect:** importing anything from `itrader` runs `itrader/__init__.py`, which initializes `config = SystemConfig.default()`, `logger`, and `idgen` singletons. Be deliberate about importing `itrader` in fixtures.

## Error Handling

**Hierarchy:**
- Root: `ITraderError` (`itrader/core/exceptions/base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific files: `portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).

**Patterns:**
- Raise typed exceptions, NOT bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False`.
- **Rejections flow as events, not exceptions:** `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles. Execution error codes live in `itrader/core/enums/execution.py::ExecutionErrorCode`.
- Handlers catch-and-log at the event boundary and do NOT re-raise on the live path (`ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls).
- **Run-mode error policy (Pinned Decision 2):** backtest is fail-fast (`EventHandler._on_handler_error` re-raises so a handler failure aborts the run); live is publish-and-continue (overridden to emit `ErrorEvent` and keep draining). This asymmetry is intentional, not an inconsistency.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain ONLY via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). NEVER call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live in `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` in `itrader/core/money.py`.
- `float()` appears ONLY at the serialization/logging edge.

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do NOT introduce a second ID scheme.
- One shared seeded `random.Random` constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from `performance.rng_seed`, default 42). NEVER seed per-call.
- An injected `BacktestClock` (`itrader/core/clock.py`) is staged on the determinism seam. Business `time` flows through events; never wall clock.

## Logging

**Framework:** `structlog` (`itrader/logger.py`), console (color) or JSON renderer.

**Patterns:**
- Bind component context once: `self.logger = get_itrader_logger().bind(component="ClassName")`.
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True`; `debug` rarely used.

## Comments & Docstrings

**When to Comment:**
- Comments explain WHY, often citing a locked decision tag (`# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.
- Decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`, `WR-NN`) are **load-bearing** references to planning artifacts — preserve them.

**Docstrings:**
- Modules open with a triple-quoted docstring frequently citing decision tags tying the code to the refactor plan.
- Classes carry a summary docstring (often a bulleted responsibility list).
- Functions use a one-line docstring or NumPy-style `Parameters`/`Returns` blocks.
- Cross-module citations should lead with the durable SYMBOL name; trailing `:line` numbers are approximate hints that drift.

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back. No business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage; `OrderManager` D-18).
- Components take `global_queue` as a constructor argument and NEVER call other handlers directly across domains — emit an event instead. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel` Protocol, `BacktestBarFeed`).
- Events and value objects are `@dataclass`; events are `@dataclass(frozen=True, slots=True, kw_only=True)` subclasses of `Event`, pinning `type` via `field(default=EventType.X, init=False)`.
- `__init__.py` files act as barrels re-exporting the domain's public surface (e.g. `core/enums/__init__.py`).

## Pinned Decisions (do not re-litigate)

1. **Config-enum exception** — the seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `itrader/config/`, NOT `core/enums/`, by design. Relocating them would invert the core→config dependency.
2. **Broad-`except` run-mode policy** — backtest fail-fast vs live publish-and-continue is intentional (see Error Handling above), not an inconsistency to "fix".
3. **Tab/space indentation hazard** — match the file, never normalize (see Code Style above).
4. **Dual-layer order-validator overlap** — `order_handler/order_validator.py` and `execution_handler/exchanges/simulated.py` both validate, justified by defense-in-depth: the live `TradingInterface`/`OrderEvent` path bypasses the domain validator. Documented and NOT removed (D-03a; Phase 6 / W4-09 removed the dead `create_order` second path, so the live-path bypass alone now justifies the overlap).

---

*Convention analysis: 2026-06-27*
