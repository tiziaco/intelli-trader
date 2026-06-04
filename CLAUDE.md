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

Everything flows through a single `global_queue` (`queue.Queue`). `events_handler/full_event_handler.py::EventHandler.process_events()` drains the queue and dispatches each event by `EventType`. Events are dataclasses in `events_handler/event.py`, each carrying a class-level `type` attribute. The canonical flow:

```
PING   -> screeners_handler.screen_markets + universe.generate_bar_event
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

Adding a new event type means: define the dataclass in `event.py`, add it to the `EventType` enum, and add a branch in `process_events()`.

### Two run modes, same components

Both wire up the identical component graph around one shared queue in their `__init__`:
- `trading_system/backtest_trading_system.py::TradingSystem` — synchronous `for` loop over a `PingGenerator`, uses in-memory order storage.
- `trading_system/live_trading_system.py::LiveTradingSystem` — processes the queue on a background thread with start/stop/status lifecycle. `trading_system/trading_interface.py::TradingInterface` is the bridge between an external/web API and the live system (order creation, validation, status).

### Handlers (each owns a domain, talks via the queue)

- **order_handler/** — `OrderHandler` is a thin interface layer; order *management* logic (signal-to-order, lifecycle, modify/cancel, bracket declaration) lives in `OrderManager`. It does **not** match orders: it declares brackets via `parent_order_id`/`child_order_ids` (the exchange enforces OCO) and reconciles the stored order mirror against exchange truth in `on_fill` (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED). Validation via `EnhancedOrderValidator`. Persistence is pluggable through `OrderStorageFactory` (`in_memory` for backtest, `postgresql` for live) under `order_handler/storage/`.
- **portfolio_handler/** — `PortfolioHandler` manages portfolio lifecycle; each `Portfolio` delegates to four managers: `CashManager`, `PositionManager`, `TransactionManager`, `MetricsManager`. Thread-safe via `readerwriterlock`.
- **execution_handler/** — `ExecutionHandler` with pluggable `fee_model/`, `slippage_model/`, and `exchanges/` (e.g. `simulated`). Routes `on_order` and `on_market_data` to the exchange, turning `OrderEvent`/`BarEvent` into `FillEvent`s. The `SimulatedExchange` composes a pure `MatchingEngine` (`matching_engine.py`) that holds the resting-order book and evaluates stop/limit triggers against intrabar high/low with gap-aware fills and same-bar OCO priority; the exchange then applies fee/slippage and emits the fill.
- **strategy_handler/** — `StrategiesHandler` runs strategies; each combines a `position_sizer/`, `risk_manager/`, and `sltp_models/`. Concrete strategies live in `strategy_handler/my_strategies/` (gitignored at the top level but present in-tree).
- **screeners_handler/** & **universe/** — dynamic market screening and the tradable symbol universe.
- **price_handler/** — data download/storage (CCXT, OANDA exchanges; Binance live streaming; SQL via SQLAlchemy).

### Configuration system

`itrader/config/` is a domain-based config system: `core/` provides `ConfigRegistry` / `ConfigProvider` / validators; domains are `portfolio`, `trading`, `data`, `system`, `exchange`. Access via the convenience getters in `config/__init__.py` (`get_config_registry`, `get_portfolio_config_provider`, etc.). YAML config is loaded from the `settings/` directory (gitignored).

**Import side effects:** `itrader/__init__.py` initializes process-wide singletons on import — `config`, `logger` (structlog, via `init_logger`), and `idgen` (`IDGenerator`). Modules import these directly (`from itrader import config, idgen`). Get a bound logger with `get_itrader_logger().bind(component="...")`.

### Shared core

`core/enums/` (OrderType, OrderStatus + `VALID_ORDER_TRANSITIONS`, portfolio/execution enums) and `core/exceptions/` hold the cross-cutting types used by all handlers. Use the enum maps (e.g. `order_type_map`) to convert string inputs to enums.

## Conventions

- Source uses **tab indentation** in most handler modules (config/ and some newer modules use spaces — match the file you edit).
- Components are constructed with the `global_queue` as a constructor argument and never call each other directly across domains — emit an event instead.

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
- Python 3.13.1 (CPython) - All application and test code
- YAML - Configuration files under `settings/`
## Runtime
- CPython 3.13.1 (managed via pyenv, `.python-version` pins to `3.13`)
- Poetry (virtualenvs installed in-project as `.venv/`)
- Lockfile: `poetry.lock` present and committed
## Frameworks
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib)
- Entry point: `itrader/events_handler/full_event_handler.py`
- pytest 8.3.5 — test runner
- pytest-cov 5.0.0 — coverage reports (HTML at `htmlcov/`)
- pytest-watch 4.2.0 — file-watch mode
- pytest-html 4.1.1 — HTML test reports
- `make` — task runner (`Makefile` at repo root)
- pyenv — Python version management
## Key Dependencies
- pandas 2.2.3 — primary data structure for OHLCV price series; used throughout all handlers
- numpy 2.2.3 — numerical operations, array computing
- ta 0.11.0 — technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.3.14b — extended TA library with 130+ indicators; used in strategy filters and SLTP models (`itrader/strategy_handler/sltp_models/`, `itrader/strategy_handler/my_strategies/filters/`)
- scipy 1.15.2 — `linregress` for performance metrics (`itrader/reporting/performance.py`)
- scikit-learn 1.6.1 — `LinearRegression`, `PolynomialFeatures` for custom indicators (`itrader/strategy_handler/my_strategies/custom_indicators/`)
- statsmodels 0.14.4 — cointegration tests (`coint`, `OLS`) for pairs trading (`itrader/screeners_handler/screeners/cointegrated_pairs.py`, `itrader/strategy_handler/my_strategies/mean_reversion/`)
- sqlalchemy 2.0.38 — ORM and engine for PostgreSQL price database (`itrader/price_handler/sql_handler.py`)
- sqlalchemy-utils 0.41.2 — `database_exists`, `create_database` helpers (`itrader/price_handler/sql_handler.py`)
- psycopg2-binary 2.9.10 — PostgreSQL adapter; required by SQLAlchemy engine URL `postgresql+psycopg2://`
- ccxt 4.4.65 — unified interface to 100+ crypto exchanges; used in `itrader/price_handler/exchange/CCXT.py`
- websocket (from `websocket-client`) — Binance live data streaming via `wss://stream.binance.com:9443`; used in `itrader/price_handler/live_streaming/BINANCE_Live.py`
- pyyaml 6.0.2 — YAML parsing for domain config files (`itrader/config/core/provider.py`)
- structlog 24.4.0 — structured logging with context binding; configured in `itrader/logger.py`; outputs to console with color support and optionally JSON
- readerwriterlock 1.0.9 — reader-writer lock for thread-safe portfolio access (`itrader/portfolio_handler/portfolio_handler.py`)
- tqdm 4.67.1 — progress bars during data download loops (`itrader/price_handler/data_provider.py`)
- plotly 6.0.0 — interactive charts for performance reporting (`itrader/reporting/plots.py`)
- ipython 9.0.1 — interactive REPL
- ipykernel 6.29.5 — Jupyter kernel support
## Configuration
- `.env` file at repo root (loaded by `Makefile` via `include .env` / `.EXPORT_ALL_VARIABLES`)
- Domain-based YAML configs loaded from `settings/` directory (gitignored)
- Config system initialized as a process-wide singleton in `itrader/__init__.py` on package import
- YAML files follow per-domain naming: `settings/{domain}.yaml` (e.g., `settings/portfolio.yaml`)
- Defaults shipped as `settings/domains/{domain}.default.yaml`
- `FileConfigProvider` auto-detects file changes and refreshes from disk; thread-safe via `threading.RLock`
- `pyproject.toml` — single source of truth for dependencies, test config, and package metadata
- `Makefile` — all developer commands; loads `.env` at top level
## Platform Requirements
- macOS or Linux (pyenv for Python version management)
- pyenv with Python 3.13 installed
- Poetry (for dependency management and virtual environment)
- PostgreSQL running locally on port 5432 (for price storage via `SqlHandler`)
- PostgreSQL database for price history (`trading_system_prices` database)
- PostgreSQL for order storage (live mode — `PostgreSQLOrderStorage` not yet implemented)
- OANDA API credentials in `oanda.cfg` file if using OANDA exchange
- Binance WebSocket access if using live streaming (`BINANCELiveStreamer`)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Indentation
- **Tabs:** Most handler modules under `itrader/` use tab indentation.
- **4 spaces:** Newer refactored modules use 4-space indentation.
## Naming Patterns
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` (e.g., `order_handler.py`, `execution_handler.py`)
- Manager classes: `<domain>_manager.py` (e.g., `order_manager.py`, `cash_manager.py`)
- Storage: `<backend>_storage.py` (e.g., `in_memory_storage.py`)
- Tests mirror source: `test_<module>.py`
- `PascalCase` for all classes: `OrderHandler`, `PortfolioHandler`, `SimulatedExchange`, `MatchingEngine`
- Handler classes named `<Domain>Handler` — a thin interface delegating to `<Domain>Manager`
- Manager classes named `<Domain>Manager` — owns the business logic
- Abstract bases named `Abstract<Name>` (e.g., `AbstractExchange`, `AbstractExecutionHandler`)
- Config classes named `<Domain>Config` (e.g., `PortfolioConfig`, `ExchangeConfig`)
- Exception classes named `<Specific><Category>Error` (e.g., `PortfolioNotFoundError`, `InsufficientFundsError`)
- `snake_case` throughout
- Event handler callbacks: `on_<event_type>()` — e.g., `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`
- Factory class methods: `new_<object>()` — e.g., `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`
- Boolean-returning properties: `is_<state>` — e.g., `is_active`, `is_fully_filled`, `is_partially_filled`
- Getter methods: `get_<thing>()` — e.g., `get_portfolio()`, `get_latest_state_change()`
- Private methods and attributes: `_<name>` with single underscore
- `snake_case` always
- Queue variable: always named `global_queue` or `events_queue` in constructors
- Logger: always `self.logger` bound from `get_itrader_logger().bind(component="ClassName")`
- Config: always `self.config`
- Enum names: `PascalCase` (e.g., `OrderType`, `OrderStatus`, `FillStatus`)
- Enum members: `UPPER_CASE` (e.g., `OrderStatus.PENDING`, `FillStatus.EXECUTED`)
- String-to-enum maps: `<domain>_<type>_map` (e.g., `order_type_map`, `order_status_map`, `fill_status_map`)
## Import Organization
## Dataclasses and Type Hints
## Module-level Singletons
- `config` — system configuration object
- `logger` — `ITraderStructLogger` instance
- `idgen` — `IDGenerator` instance
## Logging
- `info` — successful operations, initialization messages
- `warning` / `warn` — non-fatal issues (unknown exchange, skipped event)
- `error` — caught exceptions, routing failures: `self.logger.error("msg", exc_info=True)`
- `debug` — fine-grained tracing (not common in current code)
## Error Handling
- `itrader/core/exceptions/base.py` — `ITradingSystemError`, `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`
- `itrader/core/exceptions/portfolio.py` — `PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`, etc.
- `itrader/core/exceptions/execution.py` — `ExecutionError`, `ExchangeConnectionError`, `OrderExecutionError`, etc.
## Docstrings
## Handler-Manager Split
- `OrderHandler` / `PortfolioHandler` / `ExecutionHandler` — thin interface, receives events from queue, delegates logic, emits events back to queue
- `OrderManager` / `CashManager` / `PositionManager` etc. — owns business logic, has no direct queue access
## Configuration
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
```
## Component Responsibilities
| Component | Responsibility | Primary File |
|-----------|----------------|--------------|
| `EventHandler` | Queue drain; event dispatch by type | `itrader/events_handler/full_event_handler.py` |
| `StrategiesHandler` | Run all strategies per bar; emit SignalEvents | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening; update symbol universe | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: signal→orders, fill reconciliation | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route OrderEvents to exchanges; drive resting-order matching | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders immediately; rest stop/limit in MatchingEngine | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; thread-safe collection; on_fill routing | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to four sub-managers | `itrader/portfolio_handler/portfolio.py` |
| `Universe` | Tracks full tradable symbol set; generates BarEvents | `itrader/universe/dynamic.py` |
| `PriceHandler` | Data download/storage; resampled bar access | `itrader/price_handler/data_provider.py` |
| `TradingInterface` | Bridge between external/web API and LiveTradingSystem | `itrader/trading_system/trading_interface.py` |
## Pattern Overview
- All inter-component communication flows through a single `queue.Queue` (`global_queue`); direct cross-domain calls are forbidden.
- Each handler receives the `global_queue` as a constructor argument and puts events onto it — never calls other handlers.
- Stateless event dataclasses carry all context; handlers are stateful (they own storage, positions, etc.).
- The matching/execution layer is the sole source of truth for fills; the order handler only reconciles its mirror.
## Layers
- Purpose: Wires all components together; drives the run loop.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface` (API bridge), `PingGenerator`.
- Depends on: All handlers, `EventHandler`, `PriceHandler`, `Universe`.
- Used by: External callers, notebooks, web APIs.
- Purpose: Drain the queue and route events to the correct handler methods.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`.
- Depends on: All handlers.
- Used by: Both trading system run loops.
- Purpose: Encapsulate domain logic (strategy signals, orders, execution, portfolios).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Public handler classes and their sub-managers/sub-components.
- Depends on: `events_handler/event.py`, `core/`, shared `global_queue`.
- Used by: `EventHandler`.
- Purpose: Cross-cutting enums, exceptions, and identifiers used by all handlers.
- Location: `itrader/core/enums/`, `itrader/core/exceptions/`, `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `OrderCommand`, `PortfolioState`, `IDGenerator`.
- Depends on: Nothing inside itrader.
- Used by: All handlers.
- Purpose: Domain-based configuration registry with YAML-backed presets.
- Location: `itrader/config/`
- Contains: `ConfigRegistry`, `ConfigProvider`, domain configs (`portfolio`, `trading`, `data`, `system`, `exchange`).
- Depends on: `settings/` YAML files (gitignored in production).
- Used by: `PortfolioHandler`, `SimulatedExchange`, and `itrader/__init__.py`.
- Location: `itrader/__init__.py`
- Initialised on first import: `config` (system config), `logger` (structlog), `idgen` (`IDGenerator`).
- Modules import them with: `from itrader import config, idgen` or `from itrader import logger`.
## Data Flow
### Primary Backtest Request Path
### Live Trading Path
### Bracket Order Flow
- Portfolio positions/cash: owned by each `Portfolio` instance, protected by a per-portfolio `threading.RLock` (`itrader/portfolio_handler/portfolio.py:59`).
- Portfolio collection: protected by a `readerwriterlock.RWLockFair` in `PortfolioHandler` (`itrader/portfolio_handler/portfolio_handler.py:66`).
- Order book (resting orders): `MatchingEngine._resting` dict, single-threaded in backtest, protected by `SimulatedExchange._lock` in live (`itrader/execution_handler/exchanges/simulated.py:75`).
- System run status: `LiveTradingSystem._status_lock` + `threading.Event` for stop signalling.
## Key Abstractions
- Purpose: All inter-component messages; carry full context.
- Examples: `itrader/events_handler/event.py` — `PingEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`.
- Pattern: Python `@dataclass` with a class-level `type = EventType.X` attribute. Factory class methods (`FillEvent.new_fill`, `OrderEvent.new_order_event`) for safe construction.
- Purpose: Abstract base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py` — `Strategy`.
- Pattern: Subclass implements `calculate_signal(ticker, data)`; calls `_generate_signal()` to emit `SignalEvent` onto `global_queue`.
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py` — `AbstractExchange`; concrete: `SimulatedExchange` (`itrader/execution_handler/exchanges/simulated.py`).
- Pattern: Must implement `on_order(event)`, `on_market_data(bar)`, `connect()`, `disconnect()`, `health_check()`, `validate_order(event)`.
- Purpose: Pluggable persistence for the order mirror.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `itrader/order_handler/storage/postgresql_storage.py`.
- Pattern: `OrderStorageFactory.create('backtest')` → `InMemoryOrderStorage`; `OrderStorageFactory.create('live', db_url)` → `PostgreSQLStorage` (not yet fully implemented).
- Purpose: Decompose `Portfolio` into four single-responsibility managers.
- Examples: `CashManager` (`itrader/portfolio_handler/cash_manager.py`), `PositionManager` (`itrader/portfolio_handler/position_manager.py`), `TransactionManager` (`itrader/portfolio_handler/transaction_manager.py`), `MetricsManager` (`itrader/portfolio_handler/metrics_manager.py`).
- Pattern: Each manager holds a reference to its parent `Portfolio` instance; called only from `Portfolio` methods, never from outside.
## Entry Points
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: Instantiate `TradingSystem`, add strategies/portfolios, call `.run()`.
- Responsibilities: Initialise universe + price data, iterate `PingGenerator`, drain queue per tick, record metrics.
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: Instantiate `LiveTradingSystem`, call `.start()`.
- Responsibilities: Initialise universe, launch background processing thread, manage lifecycle (start/stop/status).
- Location: `itrader/trading_system/trading_interface.py` — `TradingInterface.create_market_order()`
- Triggers: Web API or external caller.
- Responsibilities: Validate system is running; construct `OrderEvent`; put directly onto `global_queue`.
- Location: `itrader/strategy_handler/base.py` — `Strategy._generate_signal()`
- Triggers: Called inside `calculate_signal()` which is called by `StrategiesHandler.calculate_signals()` per bar.
- Responsibilities: Build `SignalEvent` for each subscribed portfolio; put onto `global_queue`.
## Architectural Constraints
- **Queue-only cross-domain communication:** Handlers must never call other handler methods directly. Cross-domain interaction happens exclusively by putting events onto `global_queue`.
- **Import side effects:** `itrader/__init__.py` initializes `config`, `logger`, and `idgen` singletons at import time. Any module that imports from `itrader` triggers this. Do not import `itrader` in test fixtures without understanding this.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`. `MatchingEngine._resting` is instance-level (one per `SimulatedExchange`).
- **Circular imports:** `OrderHandler` → `OrderManager` → `OrderHandler` (reference passed in constructor, not import). Avoid adding new module-level cross-imports between handlers.
- **Threading (live mode):** Event processing runs on one daemon thread. Portfolio collection uses `rwlock`; individual portfolios use `threading.RLock`. `SimulatedExchange` uses `threading.RLock` for config updates.
- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness, but `PortfolioHandler` still acquires locks for API compatibility.
- **Tab indentation:** Most handler modules use tabs. `config/` and some newer modules use spaces. Match the indentation of the file being edited.
## Anti-Patterns
### Calling handlers directly across domains
### Adding a new event type without registering it
### Matching orders inside OrderHandler
## Error Handling
- `PortfolioHandler._operation_context()` context manager tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` on rejection and emits `FillEvent(REFUSED)` so the order mirror can reconcile.
- `ExecutionHandler.on_order()` and `on_market_data()` catch exceptions per exchange and log; they do not re-raise (prevents queue stalls).
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
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
