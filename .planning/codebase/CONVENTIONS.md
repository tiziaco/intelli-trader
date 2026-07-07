# Coding Conventions

**Analysis Date:** 2026-07-07

> **Authoritative home.** Per `CLAUDE.md`, this file is the single pinned home for
> the four "do-not-re-litigate" conventions (config-enum exception, broad-`except`
> run-mode policy, tab/space indentation hazard, dual-layer order-validator overlap).
> They are captured at the end of this document under **Pinned Decisions**.

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `itrader/execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Connectors: `<venue>_connector.py` (live-trading, v1.7) — e.g. `okx_connector.py`.
- Tests mirror source: `test_<module>.py` (e.g. `test_order_manager.py`).

**Functions:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`, `on_universe_update()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_orders_by_ticker()`.
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
- The ONLY static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).

**Indentation (correctness hazard — see Pinned Decisions):**
- **Tabs:** most handler/manager modules under `itrader/` — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
- **4 spaces:** newer refactored modules — `itrader/config/`, `itrader/core/`, `itrader/price_handler/feed/`, and the `events_handler/events/` package. Test files (`tests/conftest.py`, `tests/e2e/conftest.py`) also use 4 spaces.
- **Rule:** ALWAYS match the indentation of the file being edited. Do not normalize. A mixed-indentation diff in a tab file will break the file.

**Linting/Typing:**
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (`live_trading_system`, `trading_interface`, ccxt/oanda providers, `binance_stream`, `screeners_handler.*`, `my_strategies.*`). Do not rely on these being typed; **new code should be strict-clean**.
- Stubless third-party libs (`ta`, `pandas_ta`, `ccxt`, `pandas`, `scipy`, `plotly`, `sklearn`, `statsmodels`, …) are `ignore_missing_imports = true`.

## Import Organization

**Order (observed, not tool-enforced):**
1. Stdlib (`os`, `pathlib`, `queue`, `datetime`, `decimal`).
2. Third-party (`pytest`, `pandas`, `pydantic`).
3. First-party `itrader.*` / `tests.*`.

**Path styles:**
- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import config, logger`.
- **Deferred/lazy imports** are a deliberate pattern: heavy or side-effecting imports (`build_backtest_system`, `LiveTradingSystem`, `testcontainers`, `ccxt`, connector code) are moved INSIDE fixture/function bodies so `--collect-only` and offline collection stay fast and dependency-free. Preserve this when adding new heavy wiring.
- No `tsconfig`-style path aliases (Python packages only).

## Error Handling

- Root: `ITraderError` (`itrader/core/exceptions/base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `core/exceptions/order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `core/exceptions/data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False`.
- **Rejections flow as events, not exceptions:** `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles. Execution error codes live in `core/enums/execution.py::ExecutionErrorCode`.
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- **Run-mode error policy differs by design** (see Pinned Decisions): backtest is fail-fast (`EventHandler._on_handler_error` re-raises); live is publish-and-continue (emit `ErrorEvent`, keep draining).

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). NEVER call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live in `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` in `itrader/core/money.py`.
- `float()` appears only at the serialization/logging/CSV edge (e.g. `float(p.commission)` in the E2E harness).

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call.
- Non-deterministic values (UUIDv7 `PortfolioId`/`OrderId`) must NEVER become golden-file keys — key on stable business names (e.g. `PortfolioSpec.name`) instead.

## Logging

- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")`.
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True`; `debug` rarely used.
- Under `make test`, `ITRADER_DISABLE_LOGS=true` is exported — `caplog`-based warn-assertion tests fail there; run those through `poetry run pytest` (see `TESTING.md`).

## Comments & Docstrings

- Heavy, decision-anchored. Modules open with a triple-quoted docstring that frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`, `WR-NN`, `Pitfall N`) tying the code to the refactor plan. Preserve this style — these tags are load-bearing references to planning artifacts.
- Cross-module citations lead with the **symbol** (durable anchor), treating any trailing `:line` as an approximate hint that drifts.
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks.
- Comments explain WHY, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.
- User preference (auto-memory): favor negation + early-exit **guard clauses** over cascading/nested `if`.

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage).
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event instead. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel` Protocol, `BacktestBarFeed`).
- Events and value objects are `@dataclass`, events `frozen=True, slots=True, kw_only=True`, subclassing `Event`; `type` is pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain with comment headers).

## Pinned Decisions (do not re-litigate)

1. **Config-enum exception.** The seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `itrader/config/` NOT `core/enums/` by design — relocating them would invert the core→config dependency. Do not move them.
2. **Broad-`except` run-mode policy.** Backtest fail-fast (`EventHandler._on_handler_error` re-raises) vs live publish-and-continue (`_publish_and_continue` emits `ErrorEvent`, keeps draining) is INTENTIONAL, not an inconsistency. The live ERROR route is self-protected: a source guard in `_publish_and_continue` + consumer swallow in `_log_error_event` prevent an error→error livelock (WR-06).
3. **Tab/space indentation hazard.** Handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, events package, and test files use 4 spaces. ALWAYS match the file — never normalize.
4. **Dual-layer order-validator overlap.** The overlap between `order_validator.py` and `simulated.py` is justified-by-decision (defense-in-depth — the live `TradingInterface`/`OrderEvent` path bypasses the domain validator). It is documented and the code is NOT removed. Per D-03a / W4-09, the dead `create_order` second path was removed; the live-path bypass alone now justifies the overlap.

---

*Convention analysis: 2026-07-07*
