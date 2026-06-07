# Codebase Structure

**Analysis Date:** 2026-06-07

## Directory Layout

```
intelli-trader/                     # Repo root
├── itrader/                        # Main Python package (all production code)
│   ├── __init__.py                 # Process-wide singletons: config, logger, idgen
│   ├── logger.py                   # structlog initialization + get_itrader_logger()
│   ├── config/                     # Pydantic v2 domain config models
│   │   ├── __init__.py             # Re-exports all config + TIMEZONE constant
│   │   ├── settings.py             # pydantic-settings Settings (env vars)
│   │   ├── portfolio.py            # PortfolioConfig, get_portfolio_preset()
│   │   ├── trading.py              # TradingConfig, OrderDefaults, RiskControls
│   │   ├── data.py                 # DataConfig, DataFeedConfig, StorageConfig
│   │   ├── system.py               # SystemConfig, PerformanceSettings (rng_seed)
│   │   └── exchange.py             # ExchangeConfig, FeeModelConfig, get_exchange_preset()
│   ├── core/                       # Cross-cutting: enums, exceptions, money, ids
│   │   ├── enums/                  # All system enums
│   │   │   ├── __init__.py         # Re-exports all enums
│   │   │   ├── event.py            # EventType, Side
│   │   │   ├── order.py            # OrderType, OrderStatus, VALID_ORDER_TRANSITIONS, OrderCommand
│   │   │   ├── portfolio.py        # PortfolioState, TransactionType, PositionSide, MetricsPeriod
│   │   │   └── execution.py        # FillStatus, ExecutionStatus, ExchangeConnectionStatus
│   │   ├── exceptions/             # Domain exception hierarchy
│   │   │   ├── base.py             # ITraderError, ValidationError, ConfigurationError, StateError
│   │   │   ├── portfolio.py        # PortfolioError, InsufficientFundsError, PortfolioNotFoundError
│   │   │   ├── order.py            # Order-domain exceptions
│   │   │   └── data.py             # MissingPriceDataError, MalformedDataError
│   │   ├── ids.py                  # NewType aliases (OrderId, PortfolioId, etc.)
│   │   ├── money.py                # to_money(), quantize() — Decimal entry/rounding policy
│   │   ├── clock.py                # BacktestClock, WallClock, Clock Protocol
│   │   ├── bar.py                  # Bar dataclass (single OHLCV bar)
│   │   ├── constants.py            # FORBIDDEN_SYMBOLS, SUPPORTED_CURRENCIES, SUPPORTED_EXCHANGES
│   │   └── portfolio_read_model.py # PortfolioReadModel Protocol + PositionView DTO
│   ├── events_handler/             # Event base, all event dataclasses, EventHandler
│   │   ├── full_event_handler.py   # EventHandler: _routes registry, process_events(), _dispatch()
│   │   └── events/                 # Frozen event dataclasses by domain
│   │       ├── __init__.py         # Re-exports all events + EventType
│   │       ├── base.py             # Event base (frozen, slots, UUIDv7 event_id)
│   │       ├── market.py           # TimeEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent
│   │       ├── signal.py           # SignalEvent
│   │       ├── order.py            # OrderEvent (new_order_event factory)
│   │       ├── fill.py             # FillEvent (new_fill factory)
│   │       └── error.py            # ErrorEvent, PortfolioErrorEvent
│   ├── trading_system/             # Composition roots and run modes
│   │   ├── backtest_trading_system.py  # TradingSystem — sync for-loop backtest
│   │   ├── live_trading_system.py      # LiveTradingSystem — threaded daemon + SystemStatus
│   │   ├── trading_interface.py        # TradingInterface — API bridge for live
│   │   └── simulation/
│   │       ├── base.py             # SimulationEngine abstract base
│   │       └── time_generator.py   # TimeGenerator — iterates bar timestamps
│   ├── strategy_handler/           # Strategy base, handler, concrete strategies
│   │   ├── base.py                 # Strategy ABC: calculate_signal(), _generate_signal()
│   │   ├── strategies_handler.py   # StrategiesHandler: iterates strategies per BAR
│   │   ├── SMA_MACD_strategy.py    # Reference golden strategy (SMA + MACD)
│   │   ├── empty_strategy.py       # Stub / no-op strategy
│   │   ├── position_sizer/         # FixedSizer, VariableSizer — position sizing
│   │   ├── risk_manager/           # AdvancedRiskManager — signal-level risk filter
│   │   ├── sltp_models/            # Stop-loss / take-profit model implementations
│   │   └── my_strategies/          # User concrete strategies (gitignored at top level)
│   │       ├── trend_following/    # SuperSmoothing, SuperTrend strategies
│   │       ├── mean_reversion/     # PriceD_BB, zscore_pairs strategies
│   │       ├── momentum/           # ATR_Hawkes_Momentum strategy
│   │       ├── scalping/           # RSI, Stoch_RSI, VWAP_BB_RSI strategies
│   │       ├── filters/            # trend/momentum/volatility/noise filter modules
│   │       └── custom_indicators/  # custom_ind.py, ehlers_indicators.py
│   ├── order_handler/              # Order lifecycle management
│   │   ├── order_handler.py        # OrderHandler: on_signal(), on_fill(), API methods
│   │   ├── order_manager.py        # OrderManager: all order business logic
│   │   ├── order_validator.py      # EnhancedOrderValidator — admission validation
│   │   ├── order.py                # Order entity dataclass
│   │   ├── base.py                 # OrderBase ABC, OrderStorage Protocol
│   │   ├── operation_result.py     # OperationResult dataclass
│   │   └── storage/                # Pluggable order persistence
│   │       ├── storage_factory.py  # OrderStorageFactory.create('backtest'|'live')
│   │       ├── in_memory_storage.py    # InMemoryOrderStorage (backtest)
│   │       └── postgresql_storage.py   # PostgreSQLOrderStorage (live, deferred)
│   ├── execution_handler/          # Exchange routing and order matching
│   │   ├── execution_handler.py    # ExecutionHandler: on_order(), on_market_data()
│   │   ├── matching_engine.py      # MatchingEngine: pure resting-order book
│   │   ├── result_objects.py       # ConnectionResult, HealthStatus, OrderPreflightResult
│   │   ├── base.py                 # AbstractExecutionHandler
│   │   ├── exchanges/
│   │   │   ├── base.py             # AbstractExchange
│   │   │   └── simulated.py        # SimulatedExchange (fee+slippage+MatchingEngine)
│   │   ├── fee_model/              # ZeroFeeModel, PercentFeeModel, MakerTakerFeeModel
│   │   └── slippage_model/         # ZeroSlippageModel, FixedSlippageModel, LinearSlippageModel
│   ├── portfolio_handler/          # Portfolio lifecycle and position management
│   │   ├── portfolio_handler.py    # PortfolioHandler: lifecycle, on_fill(), satisfies PortfolioReadModel
│   │   ├── portfolio.py            # Portfolio: per-portfolio state, delegates to four managers
│   │   ├── validators.py           # Portfolio-level validators
│   │   ├── base.py                 # AbstractPortfolioHandler
│   │   ├── cash/
│   │   │   └── cash_manager.py     # CashManager: ledger, reserve/release
│   │   ├── position/
│   │   │   ├── position_manager.py # PositionManager: open/close positions
│   │   │   └── position.py         # Position entity
│   │   ├── transaction/
│   │   │   ├── transaction_manager.py  # TransactionManager: audit log
│   │   │   └── transaction.py      # Transaction entity
│   │   ├── metrics/
│   │   │   └── metrics_manager.py  # MetricsManager: equity curve, performance
│   │   └── storage/
│   │       ├── storage_factory.py  # PortfolioStateStorageFactory
│   │       └── in_memory_storage.py    # In-memory portfolio state storage
│   ├── price_handler/              # Data ingestion, storage, and feed abstraction
│   │   ├── feed/
│   │   │   ├── base.py             # BarFeed Protocol
│   │   │   └── bar_feed.py         # BacktestBarFeed: look-ahead-safe window provider
│   │   ├── store/
│   │   │   ├── base.py             # PriceStore ABC
│   │   │   ├── csv_store.py        # CsvPriceStore: read-only golden-dataset store
│   │   │   └── sql_store.py        # SqlPriceStore: PostgreSQL via SQLAlchemy
│   │   ├── providers/              # External data providers
│   │   │   ├── base.py             # Base provider
│   │   │   ├── ccxt_provider.py    # CCXT (100+ crypto exchanges)
│   │   │   ├── oanda_provider.py   # OANDA REST API
│   │   │   ├── binance_stream.py   # Binance WebSocket live streaming
│   │   │   └── exchange_base.py    # Exchange provider base
│   │   └── ingestion.py            # Ingestion orchestration
│   ├── screeners_handler/          # Dynamic market screening (deferred subsystem)
│   │   ├── screeners_handler.py    # ScreenersHandler: on TIME events
│   │   └── screeners/
│   │       ├── base.py             # AbstractScreener
│   │       ├── BestScreener.py     # Best-performing symbols screener
│   │       ├── most_performing.py  # Most-performing screener
│   │       ├── volume_spyke.py     # Volume spike screener
│   │       └── cointegrated_pairs.py  # Pairs cointegration screener
│   ├── universe/                   # Tradable symbol universe
│   │   ├── universe.py             # Universe base
│   │   ├── dynamic.py              # DynamicUniverse: manages symbols; generates BarEvents
│   │   └── static.py               # StaticUniverse
│   ├── reporting/                  # Post-run statistics and charting
│   │   ├── statistics.py           # StatisticsReporting: equity/trade summary
│   │   ├── performance.py          # CAGR, Sharpe, drawdown, linregress metrics
│   │   ├── plots.py                # Plotly interactive charts
│   │   ├── engine_logger.py        # EngineLogger (legacy, SQL-backed)
│   │   └── base.py                 # AbstractStatistics
│   └── outils/                     # Shared utilities
│       ├── id_generator.py         # IDGenerator (UUIDv7 via uuid-utils)
│       └── time_parser.py          # to_timedelta(), check_timeframe()
├── tests/                          # All automated tests
│   ├── conftest.py                 # Root conftest
│   ├── unit/                       # Unit tests by domain
│   │   ├── conftest.py
│   │   ├── config/                 # test_config_models.py
│   │   ├── core/                   # test_bar, test_clock, test_enums, test_money, test_exceptions, ...
│   │   ├── events/                 # test_events, test_event_immutability, test_dispatch_registry, ...
│   │   ├── execution/              # test_matching_engine, test_fee_models, test_simulated_exchange, ...
│   │   ├── order/                  # test_order, test_order_manager, test_order_handler, test_on_signal, ...
│   │   ├── outils/                 # test_id_generator, test_time_parser
│   │   ├── portfolio/              # test_portfolio, test_portfolio_handler, test_cash_manager, ...
│   │   ├── price/                  # test_bar_feed, test_csv_store
│   │   └── strategy/               # test_strategy
│   ├── integration/                # Integration tests
│   │   ├── conftest.py
│   │   ├── test_backtest_oracle.py     # Golden-master numerical oracle
│   │   ├── test_backtest_smoke.py      # End-to-end smoke run
│   │   ├── test_event_wiring.py        # Full event-dispatch wiring test
│   │   ├── test_execution_handler_routing.py
│   │   └── test_reservation_inertness.py
│   └── golden/                     # Golden-master reference snapshots (oracle data)
├── data/                           # Committed golden datasets
│   └── BTCUSD_1d_ohlcv_2018_2026.csv  # Reference OHLCV (2018-01-01 to 2026-06-03)
├── settings/                       # YAML domain configs (some gitignored in prod)
│   ├── domains/                    # Default YAML presets
│   ├── portfolio.yaml              # Active portfolio config
│   ├── system.default.yaml         # Default system config
│   └── trading.default.yaml        # Default trading config
├── output/                         # Backtest run outputs
│   ├── equity.csv                  # Equity curve output
│   ├── trades.csv                  # Trade log output
│   └── summary.json                # Run summary metrics
├── docs/                           # Developer documentation
│   ├── order_handler/              # Order handler design docs
│   ├── portfolio_handler/          # Portfolio handler design docs
│   └── superpowers/                # Architecture specs, plans, fixes
├── scripts/                        # Runner scripts
│   └── run_backtest.py             # Standalone backtest runner
├── notebooks/                      # Jupyter notebooks for exploration
├── .planning/                      # GSD planning artifacts (not committed to main)
│   ├── codebase/                   # Codebase map documents (this directory)
│   └── phases/                     # Phase plans
├── pyproject.toml                  # Single source of truth: deps, test config, metadata
├── Makefile                        # All developer commands (test, lint, coverage)
├── CLAUDE.md                       # Project instructions for Claude
└── poetry.lock                     # Locked dependency versions
```

## Directory Purposes

**`itrader/`:**
- Purpose: Entire production package
- Key rule: All cross-component communication via `global_queue` — no direct handler-to-handler calls

**`itrader/core/`:**
- Purpose: Zero-dependency cross-cutting types (enums, exceptions, money, ids, clock)
- Rule: No imports from any handler package. Never add handler-level logic here.

**`itrader/events_handler/`:**
- Purpose: Event dataclasses (the messages on the queue) and the `EventHandler` dispatcher
- Key files: `full_event_handler.py` (routing), `events/` (all frozen event types)
- Rule: Adding a new event type requires changes in both `events/` and `_routes` in `full_event_handler.py`

**`itrader/trading_system/`:**
- Purpose: Composition roots only — wire components, drive run loops
- Rule: The only place where handlers are instantiated together and wired to a `global_queue`

**`itrader/config/`:**
- Purpose: Pydantic v2 domain config models; constructed directly (no registry/provider)
- Indentation: 4 spaces (unlike most handler modules which use tabs)
- Pattern: Call `DomainConfig.default()` or `get_<domain>_preset(name)` — never instantiate `Settings` unless explicitly testing env-var loading

**`itrader/price_handler/`:**
- Purpose: All data concerns — storage, fetching, and look-ahead-safe feed
- Key rule: `BacktestBarFeed.window()` is the ONLY allowed data access method on the hot path; direct store access from strategies is forbidden

**`tests/unit/`:**
- Purpose: Fast isolated component tests; mirror the `itrader/` package structure
- Rule: One subdirectory per handler domain (same name as the source module)

**`tests/integration/`:**
- Purpose: Multi-component wiring tests and the golden-master oracle
- Key files: `test_backtest_oracle.py` (numerical reference frozen after M2/M5), `test_backtest_smoke.py` (end-to-end run)

**`tests/golden/`:**
- Purpose: Frozen oracle snapshots (equity curves, trade logs)
- Rule: Never edit manually; oracle is re-baselined only at designated milestones (M2, M5)

**`data/`:**
- Purpose: Committed golden dataset for offline backtest
- Key file: `BTCUSD_1d_ohlcv_2018_2026.csv` — the single reference dataset; path referenced in `CsvPriceStore.CSV_DEFAULT_PATH`

**`settings/`:**
- Purpose: YAML domain configs loaded by `FileConfigProvider` (or directly by Pydantic)
- Naming: `{domain}.yaml` (active), `{domain}.default.yaml` (shipped defaults)
- Secrets: Never commit secrets here; YAML files are gitignored in production environments

**`output/`:**
- Purpose: Backtest run artifacts — equity curves, trade logs, run summaries
- Not committed to main (gitignored)

## Key File Locations

**Entry Points:**
- `itrader/trading_system/backtest_trading_system.py`: `TradingSystem.run()` — backtest entry point
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()` — live entry point
- `scripts/run_backtest.py`: Standalone backtest runner script
- `itrader/__init__.py`: Package import — initializes `config`, `logger`, `idgen` singletons

**Configuration:**
- `pyproject.toml`: All dependencies, test markers, filterwarnings, coverage config
- `itrader/config/__init__.py`: All config re-exports and `TIMEZONE` constant
- `itrader/config/settings.py`: `Settings` pydantic-settings model (env-var layer)
- `settings/domains/`: Default YAML presets for each domain

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: Routing table — change dispatch order here
- `itrader/execution_handler/matching_engine.py`: Order matching — next-bar-open convention, OCO, bracket gates
- `itrader/core/money.py`: Decimal entry/rounding policy — `to_money()` and `quantize()`
- `itrader/core/portfolio_read_model.py`: The order/portfolio domain boundary Protocol
- `itrader/price_handler/feed/bar_feed.py`: Look-ahead safety enforcement — the bar-timing contract

**Testing:**
- `tests/integration/test_backtest_oracle.py`: Golden-master numerical regression test
- `tests/integration/test_backtest_smoke.py`: End-to-end SMA_MACD backtest smoke test
- `tests/unit/execution/test_matching_engine.py`: MatchingEngine unit tests
- `tests/conftest.py`, `tests/unit/conftest.py`: Shared fixtures

## Naming Conventions

**Files:**
- `snake_case.py` throughout — no exceptions
- Handler modules: `<domain>_handler.py` (e.g., `order_handler.py`, `execution_handler.py`)
- Manager modules: `<domain>_manager.py` (e.g., `order_manager.py`, `cash_manager.py`)
- Storage modules: `<backend>_storage.py` (e.g., `in_memory_storage.py`, `postgresql_storage.py`)
- Test files: `test_<module>.py` mirroring the source file name

**Classes:**
- `PascalCase` for all classes
- Handler: `<Domain>Handler` (thin facade)
- Manager: `<Domain>Manager` (business logic owner)
- Abstract bases: `Abstract<Name>` (e.g., `AbstractExchange`)
- Config: `<Domain>Config` (e.g., `PortfolioConfig`, `ExchangeConfig`)
- Exceptions: `<Specific><Category>Error` (e.g., `PortfolioNotFoundError`, `InsufficientFundsError`)

**Methods:**
- Event handler callbacks: `on_<event_type>()` (e.g., `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`)
- Factory class methods: `new_<object>()` (e.g., `Order.new_order()`, `FillEvent.new_fill()`)
- Boolean-returning properties: `is_<state>` (e.g., `is_active`, `is_fully_filled`)
- Getter methods: `get_<thing>()` (e.g., `get_portfolio()`, `get_active_orders()`)
- Private: `_<name>` with single underscore

**Variables:**
- `global_queue` or `events_queue` — the shared `queue.Queue` in constructors
- `self.logger` — bound structlog logger on every component
- `self.config` — config object on components that hold config
- Enum members: `UPPER_CASE` (e.g., `OrderStatus.PENDING`, `FillStatus.EXECUTED`)
- String-to-enum maps: `<domain>_<type>_map` (e.g., `order_type_map`, `fill_status_map`)

## Where to Add New Code

**New strategy:**
- Implementation: `itrader/strategy_handler/my_strategies/<category>/<StrategyName>.py`
- Subclass `Strategy` from `itrader/strategy_handler/base.py`
- Set `self.max_window` in `__init__`, implement `calculate_signal(ticker, data)`
- Call `self._generate_signal(ticker, action)` to emit — never touch `global_queue` directly
- Tests: `tests/unit/strategy/test_<strategy_name>.py`

**New event type:**
1. Add member to `EventType` enum in `itrader/core/enums/event.py`
2. Create frozen dataclass in `itrader/events_handler/events/<domain>.py`
3. Add re-export to `itrader/events_handler/events/__init__.py`
4. Add entry to `EventHandler._routes` in `itrader/events_handler/full_event_handler.py` (empty list if no immediate consumer)
- Tests: `tests/unit/events/test_<event_name>.py`

**New exchange (live):**
- Implementation: `itrader/execution_handler/exchanges/<name>.py` — subclass `AbstractExchange` from `itrader/execution_handler/exchanges/base.py`
- Register in `ExecutionHandler.init_exchanges()` in `itrader/execution_handler/execution_handler.py`
- Tests: `tests/unit/execution/exchanges/test_<name>_exchange.py`

**New fee model or slippage model:**
- Fee: `itrader/execution_handler/fee_model/<name>_fee_model.py`
- Slippage: `itrader/execution_handler/slippage_model/<name>_slippage_model.py`
- Wire via `ExchangeConfig.fee_model.type` / `ExchangeConfig.slippage_model.type` in `SimulatedExchange._init_fee_model()`

**New portfolio sub-manager:**
- Implementation: `itrader/portfolio_handler/<domain>/<domain>_manager.py`
- Instantiated inside `Portfolio._init_managers()` in `itrader/portfolio_handler/portfolio.py`
- Called only from `Portfolio` methods — never directly from `PortfolioHandler`

**New domain exception:**
- Add to the appropriate file in `itrader/core/exceptions/` (or create `<domain>.py`)
- Re-export from `itrader/core/exceptions/__init__.py`

**New config domain:**
- Create `itrader/config/<domain>.py` with Pydantic v2 model
- Add a `get_<domain>_preset()` function if presets are needed
- Re-export from `itrader/config/__init__.py`
- Default YAML: `settings/domains/<domain>.default.yaml`

**New utility:**
- Shared helpers: `itrader/outils/<name>.py`
- Time/date parsing: extend `itrader/outils/time_parser.py`
- Identity types: extend `itrader/core/ids.py`

**New test file:**
- Unit tests: `tests/unit/<domain>/test_<module>.py` — declare test marker in `pyproject.toml` if adding a new marker
- Integration tests: `tests/integration/test_<feature>.py`
- Fixture code shared across a domain: `tests/unit/<domain>/conftest.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning artifacts (phase plans, codebase maps, todos)
- Generated: Partially (by GSD commands)
- Committed: Yes (to track planning history)

**`.planning/codebase/`:**
- Purpose: Codebase map documents consumed by `/gsd:plan-phase` and `/gsd:execute-phase`
- Committed: Yes

**`tests/golden/`:**
- Purpose: Frozen numerical oracle snapshots
- Generated: Manually re-frozen at milestone boundaries (M2, M5)
- Committed: Yes — changing these files requires explicit oracle refreeze justification

**`output/`:**
- Purpose: Backtest run artifacts (equity CSV, trades CSV, summary JSON)
- Generated: Yes, by `TradingSystem.run()`
- Committed: No (gitignored for live runs; reference outputs under `output/REFREEZE-*.md`)

**`htmlcov/`:**
- Purpose: pytest-cov HTML coverage reports
- Generated: Yes, by `make test-cov`
- Committed: No

**`.venv/`:**
- Purpose: In-project Poetry virtualenv (Python 3.13)
- Generated: Yes, by `make init-env` / `poetry install`
- Committed: No

---

*Structure analysis: 2026-06-07*
