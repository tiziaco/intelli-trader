# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

iTrader is an event-driven algorithmic trading framework for backtesting and live execution. All components communicate through a shared FIFO event queue rather than direct calls. Python 3.13, managed with Poetry.

## Commands

Environment setup (uses pyenv + Poetry, installs `.venv` in-project):

```bash
make init-env
```

Tests (all run through Poetry):

```bash
make test              # full suite
make test-unit         # only -m "unit"
make test-integration  # only -m "integration"
make test-portfolio    # test/test_portfolio_handler/
make test-orders       # test/test_order_handler/
make test-execution    # test/test_execution_handler/
make test-events       # test/test_events/
make test-strategy     # test/test_strategy/
make test-cov          # coverage -> opens htmlcov/index.html
make test-watch        # pytest-watch
```

Run a single test file / case:

```bash
poetry run pytest test/test_order_handler/test_order.py -v
poetry run pytest test/test_order_handler/test_order.py -k "test_name" -v
```

`run_tests.py` is an alternative runner (`python run_tests.py unit -x`, etc.).

**Test gotcha:** `pyproject.toml` sets `filterwarnings = ["error", ...]` and `--strict-markers`/`--strict-config`. Any unexpected warning fails the test, and every marker used must be declared in the `markers` list (unit, integration, slow, portfolio, events, orders, execution, strategy).

## Architecture

### Event-driven core

Everything flows through a single `global_queue` (`queue.Queue`). `events_handler/full_event_handler.py::EventHandler.process_events()` drains the queue and dispatches each event through **`self._routes`** — a single `dict[EventType, list[Callable]]` literal where **list order IS execution order**. Dispatch is data-driven, not a branch chain. Events are **frozen dataclasses** (`@dataclass(frozen=True, slots=True, kw_only=True)`) defined under `events_handler/events/` (split by domain: `base.py`, `market.py`, `signal.py`, `order.py`, `fill.py`, `error.py`); each subclasses `Event`, pins its `type` via `field(default=EventType.X, init=False)`, and carries a UUIDv7 `event_id` plus a business `time` (never wall clock). The canonical flow:

```
TIME   -> screeners_handler.screen_markets + feed.generate_bar_event   (BacktestBarFeed produces BarEvents)
BAR    -> portfolio_handler.update_portfolios_market_value

        + execution_handler.on_market_data              (exchange matches resting stop/limit -> FillEvent)
        + strategies_handler.calculate_signals

SIGNAL -> order_handler.on_signal                       (validate + size -> OrderEvent)
ORDER  -> execution_handler.on_order                    (exchange fills/rests -> FillEvent)
FILL   -> portfolio_handler.on_fill                     (EXECUTED only: update positions/cash)

        + order_handler.on_fill                         (reconcile order mirror: FILLED/CANCELLED/REJECTED)

```

Matching lives in the **execution layer**, not the order handler: the exchange holds
the resting-order book and is the source of truth for fills. The order handler
translates signals into orders, declares brackets, and reconciles its mirror from
`FillEvent`s — it never matches orders itself.

Adding a new event type means: define the frozen dataclass under `events_handler/events/<domain>.py`, add the member to `core/enums/event.py::EventType`, and add a branch to `EventHandler._routes`. `_dispatch` raises `NotImplementedError` on an unrouted type (silent drops are a tampering risk).

**Read-model seams** sidestep the queue-only rule for *reads*: `OrderManager`/`OrderHandler` query portfolios through the injected `PortfolioReadModel` Protocol (`core/portfolio_read_model.py`) rather than importing the handler, and bar windows come from the injected `BacktestBarFeed`. The queue-only contract governs handler-to-handler *writes*, not injected read-models.

### Two run modes, same components

Both wire up the identical component graph around one shared queue in their `__init__`:

- `trading_system/backtest_trading_system.py::TradingSystem` — synchronous `for` loop over a `TimeGenerator` (`trading_system/simulation/time_generator.py`, yields `TimeEvent`s across a pinned bar-date grid), uses in-memory order storage. Backtest error policy is **fail-fast** (`EventHandler._on_handler_error` re-raises so a handler failure aborts the run rather than corrupting state).
- `trading_system/live_trading_system.py::LiveTradingSystem` — processes the queue on a background daemon thread with start/stop/status lifecycle; overrides `_on_handler_error` with publish-and-continue (emit `ErrorEvent`, keep draining). `trading_system/trading_interface.py::TradingInterface` is the bridge between an external/web API and the live system (order creation, validation, status).

### Handlers (each owns a domain, talks via the queue)

- **order_handler/** — `OrderHandler` is a thin interface layer; order *management* logic (signal-to-order, lifecycle, modify/cancel, bracket declaration) lives in `OrderManager`. It does **not** match orders: it declares brackets via `parent_order_id`/`child_order_ids` (the exchange enforces OCO) and reconciles the stored order mirror against exchange truth in `on_fill` (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED). Validation via `EnhancedOrderValidator`. Persistence is pluggable through `OrderStorageFactory` (`in_memory` for backtest, `postgresql` for live) under `order_handler/storage/`.
- **portfolio_handler/** — `PortfolioHandler` manages portfolio lifecycle and routes `on_fill`; it structurally satisfies the `PortfolioReadModel` Protocol. Each `Portfolio` delegates to four managers, each now in its own subdir: `cash/`, `position/`, `transaction/`, `metrics/`. In live mode individual portfolios use `threading.RLock`; the collection lock was removed in backtest (D-19 single-writer contract).
- **execution_handler/** — `ExecutionHandler` with pluggable `fee_model/` (`zero`/`percent`/`maker_taker`), `slippage_model/` (`zero`/`fixed`/`linear`), and `exchanges/` (e.g. `simulated`). Routes `on_order` and `on_market_data` to the exchange, turning `OrderEvent`/`BarEvent` into `FillEvent`s. The `SimulatedExchange` composes a pure `MatchingEngine` (`matching_engine.py`) that holds the resting-order book and evaluates stop/limit triggers against intrabar high/low with gap-aware fills and same-bar OCO priority; the exchange then applies fee/slippage and emits the fill.
- **strategy_handler/** — `StrategiesHandler` runs strategies; each combines a `position_sizer/` and `risk_manager/`. The reference strategy is `strategy_handler/SMA_MACD_strategy.py`; other concrete strategies live in `strategy_handler/my_strategies/`.
- **price_handler/** — the data engine, reorganized into `store/` (`CsvPriceStore`, `SqlPriceStore` — read-only on the run path), `feed/` (`BacktestBarFeed` + the look-ahead-safety **bar-timing contract** in `feed/bar_feed.py`), and `providers/` (CCXT, OANDA, Binance stream).
- **screeners_handler/** & **universe/** — dynamic market screening (deferred subsystem) and membership derivation (`universe/membership.py`).
- **reporting/** — pure builders for run artifacts (`frames.py`) and derived metrics (`metrics.py`); plotting in `plots.py`.

### Configuration system

`itrader/config/` is now a **Pydantic** config system. The old `ConfigRegistry` / `ConfigProvider` / convenience-getter layer was removed (M2-06); `SystemConfig.default()` is constructed directly. `SystemConfig` (`config/system.py`) carries `PerformanceSettings` (note `rng_seed`, default 42) and `MonitoringSettings`, alongside `PortfolioConfig`, `ExchangeConfig`, and other domain models. Optional YAML overrides still load from `settings/` (gitignored in prod; `*.default.yaml` defaults tracked under `settings/domains/`).

**Import side effects:** `itrader/__init__.py` initializes process-wide singletons on import — `config = SystemConfig.default()`, `logger` (structlog, via `init_logger`), and `idgen` (`IDGenerator`). Modules import these directly (`from itrader import config, idgen`). Get a bound logger with `get_itrader_logger().bind(component="...")`.

### Determinism & money

- **Money is `Decimal` end-to-end.** Float for money is a locked correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism:** one shared seeded `random.Random` is injected at wiring (`performance.rng_seed`, default 42), and an injected `BacktestClock` (`core/clock.py`) is staged on the determinism seam. Runs are reproducible.

### Shared core

`core/` depends on nothing inside `itrader`. It holds `enums/` (`OrderType`, `OrderStatus` + `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, portfolio/execution enums), `exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`), and the cross-cutting primitives `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `portfolio_read_model.py`. Use the enum maps (e.g. `order_type_map`) to convert string inputs to enums.

## Conventions

- **Indentation:** handler modules use **tabs**; `config/`, `core/`, `price_handler/feed/`, and the `events_handler/events/` package use **4 spaces** — match the file you edit.
- Components are constructed with the `global_queue` as a constructor argument and never call each other directly across domains — emit an event instead (read-only cross-domain access goes through an injected read-model).

<!-- GSD:project-start source:PROJECT.md -->

## Project

**iTrader — Backtest-Correctness Refactor**

iTrader is an event-driven algorithmic trading framework (Python 3.13, Poetry) for backtesting
and live execution, where all components communicate through a shared FIFO event queue. This
project is a **brownfield structural refactor** of that framework: make it run **correctly in
backtest mode** end-to-end on one reference strategy (`SMA_MACD`) over a fixed golden dataset,
fixing every structural issue surfaced in the architecture review, and leave behind an engine
whose results are trustworthy and regression-locked.

**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

### Constraints

- **Tech stack**: Python 3.13, Poetry, event-driven single-`global_queue` architecture — components
  emit events, never call across domains directly

- **Money**: Decimal end-to-end — float for money is a correctness defect (locked decision)
- **IDs**: single UUIDv7 scheme via the Rust-backed `uuid-utils` package (locked decision)
- **Determinism**: seeded RNG + injected clock — runs must be reproducible
- **Golden-master discipline**: M2–M4 are behavior-preserving against the M1 behavioral oracle;
  the numerical oracle re-baselines at exactly two points (after M2, after M5); M5 is the only
  milestone allowed to change results, validated by external cross-validation

- **Test strictness**: `pyproject.toml` sets `filterwarnings=["error"]`, `--strict-markers`,
  `--strict-config` — any unexpected warning fails the suite; every marker must be declared

- **Indentation**: tabs in handler modules; spaces in `config/` and newer modules — match the file
- **Import side effects**: `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons
  on import

- **Definition of done** (program-level, REFACTOR-BRIEF §1): `SMA_MACD` runs end-to-end producing a
  non-trivial trade log + equity curve; `mypy --strict` clean; no float money; single UUIDv7 scheme;
  deterministic; 274 component tests green (migrated to pytest) + a run-path integration test;
  metrics cross-validated against `backtesting.py` and `backtrader`; final numerical reference frozen
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.
- YAML - Configuration files under `settings/` (e.g. `settings/domains/portfolio.default.yaml`, `settings/portfolio_handler.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~492 KB)

## Frameworks

- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`
- pytest ^8.4.2 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-cov ^5.0.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-watch ^4.2.0 - File-watch mode (`make test-watch`)
- pytest-html ^4.2.0 - HTML test reports
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle
- mypy ^2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems and stubless third-party libs
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)

## Key Dependencies

- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library used in strategy filters and SLTP models
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` env-var layer with `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- tqdm ^4.67.3 - Progress bars during data download loops
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)
- readerwriterlock (transitive/used) - Reader-writer lock for thread-safe portfolio access (`itrader/portfolio_handler/portfolio_handler.py`)
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel

## Configuration

- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). Contains DB URLs and exchange API credentials — see INTEGRATIONS.md for key names.
- `pydantic-settings` `Settings` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`)
- Domain YAML configs loaded from `settings/` (gitignored in production); defaults shipped as `settings/domains/{domain}.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow` markers are declared (folder-derived in `tests/conftest.py`).

## Platform Requirements

- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` placeholder in `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Tests mirror source: `test_<module>.py` (e.g. `test_order_manager.py`).
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Module-private module-level constants: leading underscore — `_ONE = Decimal("1")`, `_DEFAULT_SCALES`.
- `snake_case` always.
- The shared event queue is always named `global_queue` (constructor parameter) or `events_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed config object such as `SystemConfig`).
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

- No autoformatter configured (no black/ruff/prettier config present). Match the surrounding file by hand.
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The only static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).
- **Tabs:** most handler/manager modules under `itrader/` use tab indentation — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`.
- **4 spaces:** newer refactored modules use spaces — `itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`.
- **Rule:** ALWAYS match the indentation of the file being edited. Do not normalize. A mixed-indentation diff in a tab file will break the file.
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`). Do not rely on these being typed; new code should be strict-clean.

## Import Organization

- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`.
- None — Python package imports only. No `tsconfig`-style aliases.

## Error Handling

- Root: `ITraderError` (`base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/execution.py` (`ExecutionError`, `ExchangeConnectionError`, `OrderExecutionError`).
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).
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

- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")` (21 occurrences across handlers).
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True` (12 occurrences); `debug` rarely used.

## Comments & Docstrings

- Heavy, decision-anchored. Modules open with a triple-quoted docstring that frequently cites locked decision tags (`D-01`, `D-13`, `M5-04`, `T-07-14`) tying the code to the refactor plan. Preserve this style — these tags are load-bearing references to planning artifacts.
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (see `ExecutionHandler.__init__`).
- Used to explain WHY, often referencing a decision tag or pitfall (e.g. `# D-04 — string entry`, `# RESEARCH Pitfall 5`). Avoid restating what the code does.

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage; see `OrderManager` D-18 note).
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead.
- Events and value objects are `@dataclass` (often `frozen=True` for immutability — e.g. `_PendingBracket`, `Bar`). Events carry a class-level `type = EventType.X`.
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain with comment headers).

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self._routes` (list order = execution order); fail-fast error seam | `itrader/events_handler/full_event_handler.py` |
| `TradingSystem` | Backtest composition root + synchronous run loop over `TimeGenerator` | `itrader/trading_system/backtest_trading_system.py` |
| `LiveTradingSystem` | Live composition root; background processing thread + start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per bar; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; admission/sizing; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol implementation | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler._routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Adding/changing routing happens only there.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol) and `BacktestBarFeed` are injected as read-models; the queue-only rule governs handlers, not read-models.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.

## Layers

- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers.
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes + fat managers/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlPriceStore`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, domain models. The registry/provider getters were removed (M2-06); `SystemConfig.default()` is constructed directly.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`.
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

### Live Trading Path

### Bracket / Resting-Order Flow

- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `LiveTradingSystem._status_lock` + `threading.Event`.

## Key Abstractions

- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent`.
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `itrader/strategy_handler/SMA_MACD_strategy.py`, `itrader/strategy_handler/my_strategies/`.
- Pattern: Subclass implements `calculate_signal(...)`; emits a `SignalEvent` onto `global_queue`.
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange`.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`.
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, `searchsorted` per tick — zero per-tick resample).
- Purpose: Pluggable order-mirror persistence.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `postgresql_storage.py`; built via `OrderStorageFactory`.
- Purpose: Pluggable execution cost.
- Examples: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`), `slippage_model/` (`zero`, `fixed`, `linear`).

## Entry Points

- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks.
- Responsibilities: Wire components, derive membership + ping grid, precompute resampled frames, drive the for-loop, print/record metrics.
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch processing thread, manage lifecycle.
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.
- Location: `itrader/strategy_handler/base.py` — strategy `calculate_signal` → `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Bar-timing contract:** the seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

### Adding a new event type without registering it

### Matching orders inside OrderHandler / OrderManager

### Float arithmetic on money

## Error Handling

- `EventHandler._log_error_event` is the real `ERROR`-route consumer (structured log sink, severity-mapped).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles.
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`).

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
