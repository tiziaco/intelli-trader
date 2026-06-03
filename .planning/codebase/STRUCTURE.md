# Codebase Structure

**Analysis Date:** 2026-06-03

## Directory Layout

```
intelli-trader/
├── itrader/                        # Main package
│   ├── __init__.py                 # Singletons: config, logger, idgen
│   ├── config/                     # Domain-based configuration system
│   │   ├── core/                   # ConfigRegistry, ConfigProvider, validators
│   │   ├── portfolio/              # PortfolioConfig, presets
│   │   ├── trading/                # TradingConfig, OrderType, ExecutionSettings
│   │   ├── data/                   # DataConfig, DataSource, StorageConfig
│   │   ├── system/                 # SystemConfig, LoggingConfig
│   │   └── exchange/               # ExchangeConfig, FeeModelConfig, SlippageModelConfig
│   ├── core/                       # Shared enums and exceptions
│   │   ├── enums/                  # OrderType, OrderStatus, OrderCommand, PortfolioState, execution enums
│   │   └── exceptions/             # Domain-specific exception classes
│   ├── events_handler/             # Event definitions and dispatch
│   │   ├── event.py                # All EventType enum + event dataclasses
│   │   └── full_event_handler.py   # EventHandler.process_events() dispatcher
│   ├── trading_system/             # Entry points (run modes)
│   │   ├── backtest_trading_system.py   # TradingSystem — synchronous for-loop backtest
│   │   ├── live_trading_system.py       # LiveTradingSystem — threaded live trading
│   │   ├── trading_interface.py         # TradingInterface — web/API bridge
│   │   └── simulation/
│   │       └── ping_generator.py        # PingGenerator — backtest tick iterator
│   ├── order_handler/              # Order domain
│   │   ├── order_handler.py        # OrderHandler — event interface layer
│   │   ├── order_manager.py        # OrderManager — all order business logic
│   │   ├── order_validator.py      # EnhancedOrderValidator
│   │   ├── order.py                # Order entity
│   │   ├── base.py                 # OrderBase, OrderStorage abstract classes
│   │   ├── operation_result.py     # OperationResult return type
│   │   └── storage/
│   │       ├── in_memory_storage.py     # InMemoryOrderStorage (backtest)
│   │       ├── postgresql_storage.py    # PostgreSQLOrderStorage (live — stub)
│   │       └── storage_factory.py      # OrderStorageFactory.create()
│   ├── execution_handler/          # Execution domain
│   │   ├── execution_handler.py    # ExecutionHandler — exchange router
│   │   ├── matching_engine.py      # MatchingEngine — pure resting-order book
│   │   ├── result_objects.py       # ExecutionResult, ConnectionResult, HealthStatus, ValidationResult
│   │   ├── base.py                 # AbstractExecutionHandler
│   │   ├── exchanges/
│   │   │   ├── base.py             # AbstractExchange interface
│   │   │   └── simulated.py        # SimulatedExchange
│   │   ├── fee_model/
│   │   │   ├── base.py             # AbstractFeeModel
│   │   │   ├── zero_fee_model.py
│   │   │   ├── percent_fee_model.py
│   │   │   ├── maker_taker_fee_model.py
│   │   │   └── tiered_fee_model.py
│   │   └── slippage_model/
│   │       ├── base.py             # AbstractSlippageModel
│   │       ├── zero_slippage_model.py
│   │       ├── linear_slippage_model.py
│   │       └── fixed_slippage_model.py
│   ├── portfolio_handler/          # Portfolio domain
│   │   ├── portfolio_handler.py    # PortfolioHandler — lifecycle and event routing
│   │   ├── portfolio.py            # Portfolio — per-portfolio state
│   │   ├── cash_manager.py         # CashManager
│   │   ├── position_manager.py     # PositionManager
│   │   ├── transaction_manager.py  # TransactionManager
│   │   ├── metrics_manager.py      # MetricsManager
│   │   ├── position.py             # Position entity
│   │   ├── transaction.py          # Transaction entity
│   │   └── validators.py           # Portfolio-level validators
│   ├── strategy_handler/           # Strategy domain
│   │   ├── strategies_handler.py   # StrategiesHandler — runs all strategies per bar
│   │   ├── base.py                 # Strategy abstract base class
│   │   ├── empty_strategy.py       # No-op strategy template
│   │   ├── SMA_MACD_strategy.py    # Example built-in strategy
│   │   ├── my_strategies/          # User-defined strategies (gitignored at top level)
│   │   │   ├── mean_reversion/
│   │   │   ├── momentum/
│   │   │   ├── trend_following/
│   │   │   ├── scalping/
│   │   │   ├── filters/
│   │   │   └── custom_indicators/
│   │   ├── position_sizer/
│   │   │   ├── base.py
│   │   │   ├── fixed_sizer.py
│   │   │   └── variable_sizer.py
│   │   ├── risk_manager/
│   │   │   └── advanced_risk_manager.py
│   │   └── sltp_models/
│   │       └── sltp_models.py
│   ├── screeners_handler/          # Screener domain
│   │   ├── screeners_handler.py    # ScreenersHandler
│   │   └── screeners/              # Concrete screener implementations
│   ├── universe/                   # Symbol universe management
│   │   ├── universe.py             # Universe base
│   │   ├── dynamic.py              # DynamicUniverse — generates BarEvents
│   │   └── static.py               # StaticUniverse
│   ├── price_handler/              # Market data access
│   │   ├── data_provider.py        # PriceHandler — download, cache, resample
│   │   ├── sql_handler.py          # SQL-backed storage (SQLAlchemy)
│   │   ├── exchange/
│   │   │   ├── CCXT.py             # CCXT exchange adapter
│   │   │   └── OANDA.py            # OANDA adapter
│   │   └── live_streaming/         # Binance live data streaming
│   ├── reporting/                  # Post-run statistics and plots
│   │   ├── statistics.py           # StatisticsReporting
│   │   ├── performance.py
│   │   ├── plots.py
│   │   └── engine_logger.py
│   ├── outils/                     # Shared utility helpers
│   │   ├── id_generator.py         # IDGenerator (singleton: idgen)
│   │   ├── time_parser.py          # to_timedelta(), check_timeframe()
│   │   ├── data_outils.py
│   │   ├── strategy.py
│   │   └── profiling.py
│   └── logger.py                   # get_itrader_logger(), init_logger()
├── test/                           # Test suite (mirrors itrader structure)
│   ├── test_events/                # Event schema and wiring tests
│   ├── test_order_handler/         # Order handler + manager + storage tests
│   ├── test_execution_handler/     # Execution handler, exchanges, matching engine
│   │   ├── test_exchanges/
│   │   ├── test_fee_models/
│   │   └── test_slippage_models/
│   ├── test_portfolio_handler/     # Portfolio handler + sub-managers
│   ├── test_positions/             # Position-level unit tests
│   ├── test_transaction/           # Transaction unit tests
│   └── test_strategy/              # Strategy tests
├── settings/                       # YAML configuration (gitignored in production)
│   ├── domains/                    # Active domain YAML files
│   └── backups/                    # Config backups
├── docs/                           # Design docs and specs
│   ├── order_handler/
│   ├── portfolio_handler/
│   └── superpowers/                # Feature plans and fix notes
├── notebooks/                      # Jupyter research notebooks
├── Makefile                        # Developer commands (test, init-env, coverage)
├── pyproject.toml                  # Project metadata, dependencies, pytest config
└── poetry.lock                     # Locked dependency tree
```

## Directory Purposes

**`itrader/`:**
- Purpose: Main application package. All runtime code lives here.
- Contains: Eight domain handler packages + core + config + outils.
- Key files: `itrader/__init__.py` (singletons), `itrader/logger.py` (logger factory).

**`itrader/events_handler/`:**
- Purpose: Central event bus definitions and the queue-drain dispatcher.
- Contains: All event dataclasses, `EventType` enum, `EventHandler`.
- Key files: `event.py` (all event types), `full_event_handler.py` (dispatcher).

**`itrader/trading_system/`:**
- Purpose: System entry points — backtest and live run modes.
- Contains: `TradingSystem`, `LiveTradingSystem`, `TradingInterface`, `PingGenerator`.
- Key files: `backtest_trading_system.py`, `live_trading_system.py`.

**`itrader/core/`:**
- Purpose: Shared, dependency-free enums and exceptions used across all domains.
- Contains: `enums/order.py` (OrderType, OrderStatus, VALID_ORDER_TRANSITIONS, OrderCommand), `enums/portfolio.py`, `enums/execution.py`, `exceptions/`.
- Key files: `core/enums/order.py`, `core/exceptions/base.py`.

**`itrader/config/`:**
- Purpose: Domain-based configuration with YAML backing and runtime update support.
- Contains: Five domain sub-packages + `core/` (ConfigRegistry, ConfigProvider).
- Key files: `config/__init__.py` (all exports and convenience functions).

**`itrader/order_handler/storage/`:**
- Purpose: Pluggable order persistence — in-memory for backtest, PostgreSQL for live.
- Contains: `InMemoryOrderStorage`, `PostgreSQLOrderStorage` (stub), `OrderStorageFactory`.
- Key files: `storage_factory.py`.

**`itrader/execution_handler/exchanges/`:**
- Purpose: Pluggable exchange adapters.
- Contains: `AbstractExchange` base, `SimulatedExchange` (only fully implemented adapter).
- Key files: `simulated.py`, `base.py`.

**`itrader/strategy_handler/my_strategies/`:**
- Purpose: User-defined concrete strategies grouped by style.
- Contains: Subdirectories per style (mean_reversion, momentum, trend_following, scalping, filters, custom_indicators).
- Note: Gitignored at top level but present in-tree.

**`test/`:**
- Purpose: Full pytest test suite, mirroring `itrader/` structure.
- Contains: Separate subdirectory per domain.
- Key files: Each `test_*.py` file is independently runnable with `poetry run pytest`.

**`settings/`:**
- Purpose: YAML configuration files for all domains (gitignored in production).
- Contains: `domains/` (active configs), `backups/`.
- Default YAML files also live alongside each domain config package: e.g., `itrader/config/core/portfolio.default.yaml`.

## Naming Conventions

**Files:**
- Handler entry points: `{domain}_handler.py` (e.g., `order_handler.py`, `portfolio_handler.py`).
- Sub-managers: `{role}_manager.py` (e.g., `cash_manager.py`, `order_manager.py`).
- Abstract bases: `base.py` in each package.
- Exchange adapters: `{exchange_name}.py` in `exchanges/` (e.g., `simulated.py`, `CCXT.py`).
- Model variants: `{type}_{model_name}.py` (e.g., `percent_fee_model.py`, `linear_slippage_model.py`).
- Test files: `test_{module_name}.py` mirroring the source structure.

**Directories:**
- Domain handler packages: `{domain}_handler/` (e.g., `order_handler/`, `portfolio_handler/`).
- All lowercase with underscores.

**Classes:**
- Handlers: `{Domain}Handler` (e.g., `OrderHandler`, `PortfolioHandler`).
- Managers: `{Role}Manager` (e.g., `OrderManager`, `CashManager`).
- Events: `{Type}Event` (e.g., `SignalEvent`, `FillEvent`).
- Abstract bases: `Abstract{Component}` (e.g., `AbstractExchange`, `AbstractExecutionHandler`).
- Enums: Created with `Enum("EnumName", "VAL1 VAL2 ...")` pattern.

**Variables/Functions:**
- `snake_case` throughout.
- Handler method names follow the pattern `on_{event_type}` (e.g., `on_signal`, `on_fill`, `on_order`, `on_market_data`).

## Where to Add New Code

**New event type:**
1. Define `@dataclass class NewEvent:` in `itrader/events_handler/event.py`.
2. Add `NEWTYPE` to `EventType = Enum("EventType", "... NEWTYPE")` in the same file.
3. Add `elif event.type == EventType.NEWTYPE:` branch in `itrader/events_handler/full_event_handler.py`.

**New strategy:**
- Implementation: `itrader/strategy_handler/my_strategies/{style}/my_strategy.py`
- Inherit from `itrader/strategy_handler/base.py::Strategy`.
- Implement `calculate_signal(ticker, data)`.
- Register by instantiating and appending to `StrategiesHandler.strategies`.

**New exchange adapter:**
- Implementation: `itrader/execution_handler/exchanges/{exchange_name}.py`
- Inherit from `itrader/execution_handler/exchanges/base.py::AbstractExchange`.
- Register in `ExecutionHandler.init_exchanges()` (`itrader/execution_handler/execution_handler.py:74`).

**New fee or slippage model:**
- Fee model: `itrader/execution_handler/fee_model/{type}_fee_model.py` — inherit from `base.py::AbstractFeeModel`.
- Slippage model: `itrader/execution_handler/slippage_model/{type}_slippage_model.py` — inherit from `base.py::AbstractSlippageModel`.
- Register in `SimulatedExchange._init_fee_model()` or `_init_slippage_model()`.

**New handler (new domain):**
- Implementation: `itrader/{domain}_handler/{domain}_handler.py`
- Accept `global_queue: queue.Queue` as constructor argument.
- Add to `EventHandler.__init__()` parameters and call site in `full_event_handler.py`.
- Add wiring in both `backtest_trading_system.py` and `live_trading_system.py`.

**New portfolio sub-manager:**
- Implementation: `itrader/portfolio_handler/{role}_manager.py`
- Accept `portfolio` (parent `Portfolio` instance) as constructor argument.
- Initialize in `Portfolio._init_managers()` (`itrader/portfolio_handler/portfolio.py:75`).

**New screener:**
- Implementation: `itrader/screeners_handler/screeners/{screener_name}.py`
- Register by instantiating and appending to `ScreenersHandler.screeners`.

**Tests:**
- Location: `test/test_{domain}/test_{module}.py`
- Use `pytest` markers declared in `pyproject.toml` (unit, integration, slow, portfolio, events, orders, execution, strategy).

## Special Directories

**`.planning/codebase/`:**
- Purpose: Codebase analysis documents for GSD tooling.
- Generated: Yes (by `/gsd:map-codebase`).
- Committed: Yes.

**`htmlcov/`:**
- Purpose: pytest coverage HTML report output.
- Generated: Yes (by `make test-cov`).
- Committed: No (`.gitignore`).

**`settings/`:**
- Purpose: YAML configuration files.
- Generated: No (hand-maintained).
- Committed: Partially (default YAMLs committed alongside config packages; environment-specific files gitignored).

**`notebooks/`:**
- Purpose: Jupyter research and analysis notebooks.
- Generated: No.
- Committed: Yes.

**`.venv/`:**
- Purpose: Poetry in-project virtual environment.
- Generated: Yes (by `make init-env`).
- Committed: No.

---

*Structure analysis: 2026-06-03*
