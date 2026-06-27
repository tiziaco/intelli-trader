# Codebase Structure

**Analysis Date:** 2026-06-27

## Directory Layout

```text
intelli-trader/
├── itrader/                       # The framework package (all application code)
│   ├── __init__.py                # Import-side-effect singletons: config, logger, idgen
│   ├── config/                    # Pydantic config models (SystemConfig, ExchangeConfig, presets, Settings)
│   ├── core/                      # Dependency-free cross-cutting primitives
│   │   ├── enums/                 # EventType, OrderType/Status, Side, execution/portfolio/system enums
│   │   ├── exceptions/            # base/order/portfolio/data/strategy exception hierarchy
│   │   ├── bar.py money.py ids.py clock.py sizing.py instrument.py
│   │   ├── commission_estimator.py constants.py portfolio_read_model.py
│   ├── events_handler/            # Queue dispatch + event definitions
│   │   ├── full_event_handler.py  # EventHandler.routes — THE dispatch table
│   │   └── events/                # base/market/signal/order/fill/error frozen msgspec Structs
│   ├── trading_system/            # Composition roots + run loop
│   │   ├── compose.py             # compose_engine — shared mode-agnostic wiring seam
│   │   ├── backtest_trading_system.py  # build_backtest_system factory + thin holder
│   │   ├── backtest_runner.py     # per-tick synchronous run loop
│   │   ├── system_spec.py         # SystemSpec / PortfolioSpec declarative value objects
│   │   ├── live_trading_system.py trading_interface.py
│   │   └── simulation/            # TimeGenerator (TimeEvent grid)
│   ├── strategy_handler/          # Strategies + stateful indicators
│   │   ├── strategies_handler.py base.py pair_base.py primitives.py signal_record.py
│   │   ├── strategies/            # SMA_MACD_strategy, eth_btc_pair_strategy, empty_strategy
│   │   ├── indicators/            # catalog.py + handle.py (Model B streaming indicators)
│   │   ├── my_strategies/         # User strategies (deferred from strict mypy)
│   │   └── storage/               # Signal store backends
│   ├── order_handler/             # Thin handler + decomposed managers (D-07)
│   │   ├── order_handler.py order_manager.py order.py order_validator.py
│   │   ├── sizing_resolver.py operation_result.py base.py
│   │   ├── admission/             # AdmissionManager (signal->order, sizing, reservation)
│   │   ├── brackets/              # BracketManager, BracketBook, levels (OCO)
│   │   ├── lifecycle/             # LifecycleManager (modify/cancel/TIF sweep)
│   │   ├── reconcile/             # ReconcileManager (mirror reconciliation)
│   │   └── storage/               # in_memory / postgresql order storage + factory
│   ├── execution_handler/         # Execution + matching + cost models
│   │   ├── execution_handler.py matching_engine.py result_objects.py base.py
│   │   ├── exchanges/             # base.py + simulated.py (SimulatedExchange)
│   │   ├── fee_model/             # zero / percent / maker_taker
│   │   └── slippage_model/        # zero / fixed / linear
│   ├── portfolio_handler/         # Portfolio lifecycle + per-portfolio managers
│   │   ├── portfolio_handler.py portfolio.py base.py validators.py
│   │   ├── cash/ position/ transaction/ metrics/   # the four delegated managers
│   │   └── storage/
│   ├── price_handler/             # Data engine
│   │   ├── store/                 # CsvPriceStore, SqlHandler (read-only on run path)
│   │   ├── feed/                  # BacktestBarFeed + bar-timing contract + cache_registration
│   │   ├── providers/             # ccxt, oanda, binance_stream, exchange_base
│   │   ├── exchange/              # (empty placeholder)
│   │   └── ingestion.py
│   ├── screeners_handler/         # Dynamic market screening (deferred)
│   ├── universe/                  # Membership / instrument derivation
│   ├── reporting/                 # frames.py, metrics.py, summary.py, plots.py
│   └── outils/                    # id_generator, time_parser utilities
├── tests/                         # Test root (NOT test/)
│   ├── unit/<domain>/             # type marker auto-applied from folder (conftest.py)
│   ├── integration/               # incl. test_backtest_oracle.py (the byte-exact oracle)
│   ├── e2e/<scenario>/            # scenario-spec-driven harness
│   └── golden/                    # frozen reference artifacts (0 collected tests)
├── scripts/                       # run_backtest.py, cross_validate*.py, crossval/
├── settings/                      # YAML config (gitignored prod; domains/*.default.yaml tracked)
├── data/                          # OHLCV CSVs incl. golden BTCUSD_1d_ohlcv_2018_2026.csv
├── docs/                          # design docs + docs/superpowers/specs
├── perf/ output/ notebooks/       # benchmarks, run artifacts, exploratory notebooks
├── pyproject.toml                 # deps + pytest + mypy config (single source of truth)
├── Makefile                       # all developer commands
└── poetry.lock .python-version .env
```

## Directory Purposes

**`itrader/core/`:**
- Purpose: cross-cutting primitives that depend on nothing inside `itrader`.
- Contains: `enums/`, `exceptions/`, money/ids/clock/bar/sizing/instrument primitives, `portfolio_read_model.py` Protocol.
- Key files: `core/money.py` (Decimal policy), `core/enums/event.py` (`EventType`), `core/clock.py` (`BacktestClock`), `core/bar.py` (msgspec `Bar`).

**`itrader/events_handler/`:**
- Purpose: the queue dispatch table and all event definitions.
- Key files: `full_event_handler.py` (`EventHandler.routes` — the single routing literal), `events/base.py` (`Event` msgspec base), `events/{market,signal,order,fill,error}.py`.

**`itrader/trading_system/`:**
- Purpose: composition roots and the run loop.
- Key files: `compose.py` (shared `compose_engine` seam), `backtest_trading_system.py` (`build_backtest_system` factory), `backtest_runner.py` (loop), `system_spec.py` (declarative spec), `live_trading_system.py`, `trading_interface.py`.

**`itrader/order_handler/`:**
- Purpose: signal->order translation, bracket declaration, mirror reconciliation. Thin handler over a coordinator (`OrderManager`) that delegates to four sub-managers.
- Key files: `order_handler.py` (facade), `order_manager.py` (coordinator), `admission/admission_manager.py`, `brackets/bracket_book.py`, `lifecycle/lifecycle_manager.py`, `reconcile/reconcile_manager.py`.

**`itrader/execution_handler/`:**
- Purpose: route orders to exchanges; match resting orders; apply cost models.
- Key files: `execution_handler.py`, `matching_engine.py` (pure resting book), `exchanges/simulated.py`, `fee_model/`, `slippage_model/`.

**`itrader/portfolio_handler/`:**
- Purpose: portfolio lifecycle + per-portfolio state via four delegated managers.
- Key files: `portfolio_handler.py` (satisfies `PortfolioReadModel`), `portfolio.py`, `cash/`, `position/`, `transaction/`, `metrics/`.

**`itrader/price_handler/`:**
- Purpose: look-ahead-safe price data and bar windows.
- Key files: `store/csv_store.py`, `feed/bar_feed.py` (bar-timing contract), `feed/cache_registration.py`, `providers/`.

**`tests/`:**
- Purpose: type-grouped test tree; `conftest.py` auto-applies the `unit`/`integration`/`e2e` marker from folder location.
- Key files: `tests/integration/test_backtest_oracle.py` (byte-exact SMA_MACD oracle), `tests/conftest.py`.

## Key File Locations

**Entry Points:**
- `scripts/run_backtest.py`: reproducible oracle generator (`make backtest`).
- `itrader/trading_system/backtest_trading_system.py`: `build_backtest_system` factory + `run()`.
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()`.
- `itrader/trading_system/trading_interface.py`: external/web order injection.

**Configuration:**
- `pyproject.toml`: deps, pytest (`filterwarnings=["error"]`, strict markers), mypy (`strict`, `files=["itrader"]`).
- `itrader/config/`: Pydantic models; `SystemConfig.default()`.
- `itrader/__init__.py`: singleton init (`config`, `logger`, `idgen`).
- `settings/domains/*.default.yaml`: tracked YAML defaults; `.env` (root, gitignored).

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: dispatch table.
- `itrader/order_handler/order_manager.py` + sub-managers: order business logic.
- `itrader/execution_handler/matching_engine.py` + `exchanges/simulated.py`: matching/fills.
- `itrader/portfolio_handler/portfolio.py` + managers: portfolio state.

**Testing:**
- `tests/unit/<domain>/`, `tests/integration/`, `tests/e2e/<scenario>/`, `tests/golden/`.

## Naming Conventions

**Files:**
- `snake_case.py` throughout (no exceptions).
- Handlers: `<domain>_handler.py`. Managers: `<domain>_manager.py`. Abstract bases: `base.py` per package. Storage backends: `<backend>_storage.py`.
- Tests mirror source: `test_<module>.py`.

**Directories:**
- `<domain>_handler/` for each domain; nested sub-manager packages are bare nouns (`cash/`, `brackets/`, `admission/`, `reconcile/`).
- `__init__.py` acts as a barrel re-exporting the package's public surface.

**Classes / symbols:**
- Classes `PascalCase`; Handler/Manager split (`<Domain>Handler` facade + `<Domain>Manager` logic). Abstract bases `Abstract<Name>`. Config `<Domain>Config`. Exceptions `<Specific><Category>Error`.
- Event-callbacks `on_<event>()`; factories `new_<object>()`; getters `get_<thing>()`; private with leading underscore.
- The shared queue is always `global_queue`; bound logger always `self.logger`; config always `self.config`.

## Where to Add New Code

**New strategy:**
- Implementation: `itrader/strategy_handler/strategies/<name>_strategy.py` (or `my_strategies/` for user code). Subclass `strategy_handler/base.py` (or `pair_base.py` for pairs); implement `calculate_signal`.
- Register/wire via the `SystemSpec.strategies` passed to `build_backtest_system`.
- Tests: `tests/unit/strategy/`.

**New event type:**
- Enum member: `itrader/core/enums/event.py::EventType`.
- Dataclass: `itrader/events_handler/events/<domain>.py` (frozen `msgspec.Struct` subclass of `Event`), re-export from `events/__init__.py`.
- Route: add a branch in `itrader/events_handler/full_event_handler.py::EventHandler.routes`.
- Tests: `tests/unit/events/`.

**New indicator:**
- Implementation: add a typed adapter + recurrence `*State` in `itrader/strategy_handler/indicators/catalog.py` (stateless adapter, `new_state()`/`update()`/`is_ready`/`reset()`).
- Convergence oracle test: `tests/unit/strategy/test_indicator_convergence.py`.

**New fee/slippage/storage backend:**
- Fee: `itrader/execution_handler/fee_model/<name>.py`. Slippage: `slippage_model/<name>.py`. Order storage: `order_handler/storage/<name>_storage.py` (register in `OrderStorageFactory`).

**New exchange:**
- Implementation: `itrader/execution_handler/exchanges/<name>.py` subclassing `exchanges/base.py::AbstractExchange`.

**Shared primitives / helpers:**
- Cross-cutting (used by multiple domains, no `itrader` deps): `itrader/core/`. Generic utilities: `itrader/outils/`.

**Wiring a new component into the run:**
- Add construction to the shared seam `itrader/trading_system/compose.py::compose_engine` (mode-agnostic); select mode-specific backends in `build_backtest_system`.

## Special Directories

**`tests/golden/`:**
- Purpose: frozen reference artifacts (oracle CSV/JSON + cross-validation notes).
- Generated: yes (by `scripts/run_backtest.py` at named re-freeze points). Committed: yes. Collects 0 tests — the live oracle test is `tests/integration/test_backtest_oracle.py`.

**`settings/`:**
- Purpose: YAML config overrides. `settings/domains/*.default.yaml` are tracked defaults; production override files are gitignored. `settings/backups/` holds timestamped snapshots.

**`output/`, `perf/`, `htmlcov/`, `scalene-profile.html`:**
- Purpose: run artifacts (`output/`), benchmarks (`perf/`), coverage HTML (`htmlcov/`), profiling output. Generated; coverage/profile not source.

**`.venv/`:**
- In-project Poetry virtualenv. Generated, not committed.

**`itrader/price_handler/exchange/`:**
- Currently an empty placeholder package (no module files).

---

*Structure analysis: 2026-06-27*
