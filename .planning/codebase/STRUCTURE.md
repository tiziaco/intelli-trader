# Codebase Structure

**Analysis Date:** 2026-06-12

## Directory Layout

```
intelli-trader/                     # repo root
├── itrader/                        # Main Python package (installable via Poetry)
│   ├── __init__.py                 # Singletons: config, logger, idgen — initialized on import
│   ├── logger.py                   # structlog setup, get_itrader_logger()
│   ├── config/                     # Pydantic domain config models (4 spaces, not tabs)
│   │   ├── system.py               # SystemConfig, PerformanceSettings, MonitoringSettings
│   │   ├── portfolio.py            # PortfolioConfig
│   │   ├── exchange.py             # ExchangeConfig
│   │   ├── strategy.py             # BaseStrategyConfig
│   │   ├── models.py               # Shared config model utilities
│   │   └── settings.py             # pydantic-settings Settings (env_prefix="ITRADER_")
│   ├── core/                       # Dependency root — no imports from itrader internals
│   │   ├── enums/                  # All domain enums (barrel re-export in __init__.py)
│   │   │   ├── event.py            # EventType, Side
│   │   │   ├── order.py            # OrderType, OrderStatus, VALID_ORDER_TRANSITIONS, maps
│   │   │   ├── execution.py        # FillStatus, ExecutionStatus, ExecutionErrorCode
│   │   │   ├── portfolio.py        # PortfolioState, PositionSide, TransactionType
│   │   │   ├── trading.py          # TradingDirection, Timeframe
│   │   │   ├── system.py           # SystemStatus
│   │   │   └── severity.py         # ErrorSeverity
│   │   ├── exceptions/             # Typed exception hierarchy (barrel in __init__.py)
│   │   │   ├── base.py             # ITraderError, ValidationError, ConfigurationError, StateError
│   │   │   ├── order.py            # OrderError, UnsizedSignalError, SizingPolicyViolation
│   │   │   ├── portfolio.py        # PortfolioError, InsufficientFundsError, PortfolioNotFoundError
│   │   │   └── data.py             # DataError, MalformedDataError, MissingPriceDataError
│   │   ├── ids.py                  # Ten NewType UUIDv7 aliases (OrderId, PortfolioId, …)
│   │   ├── money.py                # to_money(), quantize() — Decimal entry points
│   │   ├── clock.py                # BacktestClock — injected determinism seam
│   │   ├── bar.py                  # Bar frozen dataclass (OHLCV)
│   │   ├── sizing.py               # SizingPolicy types (FractionOfCash, FixedQuantity, RiskPercent)
│   │   ├── portfolio_read_model.py # PortfolioReadModel Protocol + PositionView DTO
│   │   └── constants.py            # Shared constants
│   ├── events_handler/             # Event dispatch + event dataclasses
│   │   ├── full_event_handler.py   # EventHandler — queue drain + _routes dict
│   │   └── events/                 # Frozen event dataclasses (4 spaces)
│   │       ├── base.py             # Event base (frozen, slots, UUIDv7 event_id)
│   │       ├── market.py           # TimeEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent
│   │       ├── signal.py           # SignalEvent
│   │       ├── order.py            # OrderEvent
│   │       ├── fill.py             # FillEvent
│   │       └── error.py            # ErrorEvent, PortfolioErrorEvent
│   ├── strategy_handler/           # Strategy execution domain (tabs)
│   │   ├── strategies_handler.py   # StrategiesHandler — fan-out per BAR
│   │   ├── base.py                 # Strategy ABC — implement generate_signal()
│   │   ├── signal_record.py        # SignalRecord capture DTO
│   │   ├── strategies/             # Reference + empty strategies
│   │   │   ├── SMA_MACD_strategy.py  # Golden reference strategy
│   │   │   └── empty_strategy.py
│   │   ├── my_strategies/          # User-supplied strategies (mypy ignore_errors)
│   │   │   ├── trend_following/
│   │   │   ├── mean_reversion/
│   │   │   ├── momentum/
│   │   │   ├── scalping/
│   │   │   ├── filters/            # Trend, momentum, noise, volatility filters
│   │   │   └── custom_indicators/  # Ehlers indicators, custom
│   │   └── storage/                # Signal store (in-memory backend)
│   │       ├── base.py
│   │       ├── in_memory_storage.py
│   │       └── storage_factory.py
│   ├── order_handler/              # Order domain (tabs)
│   │   ├── order_handler.py        # Thin interface: on_signal, on_fill, API surface
│   │   ├── order_manager.py        # Business logic orchestrator (no queue access)
│   │   ├── order.py                # Order dataclass + factory methods
│   │   ├── order_validator.py      # EnhancedOrderValidator (create_order/live path)
│   │   ├── sizing_resolver.py      # SizingPolicy → Decimal quantity resolver
│   │   ├── operation_result.py     # OperationResult DTO (success + order_events)
│   │   ├── base.py                 # OrderStorage abstract base
│   │   ├── admission/              # Cash-reservation + position-limit gate
│   │   │   └── admission_manager.py
│   │   ├── brackets/               # SL/TP declaration + OCO sibling tracking
│   │   │   ├── bracket_manager.py
│   │   │   ├── bracket_book.py
│   │   │   └── levels.py
│   │   ├── lifecycle/              # Order state-machine transitions
│   │   │   └── lifecycle_manager.py
│   │   ├── reconcile/              # Mirror reconciliation against FillEvents
│   │   │   └── reconcile_manager.py
│   │   └── storage/                # Pluggable order persistence
│   │       ├── in_memory_storage.py
│   │       ├── postgresql_storage.py  # NotImplementedError placeholder (live, deferred)
│   │       └── storage_factory.py
│   ├── execution_handler/          # Execution domain (tabs)
│   │   ├── execution_handler.py    # Routes orders to exchanges; drives on_market_data
│   │   ├── base.py                 # AbstractExecutionHandler
│   │   ├── matching_engine.py      # Pure resting-order book (no queue/fee/log deps)
│   │   ├── result_objects.py       # ExecutionResult DTO
│   │   ├── exchanges/
│   │   │   ├── base.py             # AbstractExchange interface
│   │   │   └── simulated.py        # SimulatedExchange (fee+slippage+MatchingEngine)
│   │   ├── fee_model/              # Pluggable fee: zero, percent, maker_taker
│   │   │   ├── base.py
│   │   │   ├── zero_fee_model.py
│   │   │   ├── percent_fee_model.py
│   │   │   └── maker_taker_fee_model.py
│   │   └── slippage_model/         # Pluggable slippage: zero, fixed, linear
│   │       ├── base.py
│   │       ├── zero_slippage_model.py
│   │       ├── fixed_slippage_model.py
│   │       └── linear_slippage_model.py
│   ├── portfolio_handler/          # Portfolio domain (4 spaces — newer module)
│   │   ├── portfolio_handler.py    # PortfolioHandler — lifecycle, on_fill, PortfolioReadModel
│   │   ├── portfolio.py            # Portfolio — delegates to four sub-managers
│   │   ├── base.py                 # AbstractPortfolioHandler
│   │   ├── validators.py           # Portfolio-level validation helpers
│   │   ├── cash/
│   │   │   └── cash_manager.py     # Cash balance, reservations, ledger
│   │   ├── position/
│   │   │   ├── position_manager.py # Open/close positions, P&L
│   │   │   └── position.py         # Position dataclass
│   │   ├── transaction/
│   │   │   ├── transaction_manager.py
│   │   │   └── transaction.py      # Transaction dataclass
│   │   ├── metrics/
│   │   │   └── metrics_manager.py  # Equity snapshots (PortfolioSnapshot per tick)
│   │   └── storage/                # Portfolio persistence (in-memory only currently)
│   │       ├── in_memory_storage.py
│   │       └── storage_factory.py
│   ├── price_handler/              # Data engine (4 spaces in feed/)
│   │   ├── ingestion.py            # Data ingestion utilities
│   │   ├── feed/                   # Look-ahead-safe bar feed (4 spaces)
│   │   │   ├── bar_feed.py         # BacktestBarFeed — bar-timing contract enforcement
│   │   │   └── base.py             # BarFeed abstract base
│   │   ├── store/                  # Read-only price stores
│   │   │   ├── base.py             # PriceStore abstract base
│   │   │   ├── csv_store.py        # CsvPriceStore — eager-load committed CSV(s)
│   │   │   └── sql_store.py        # SqlHandler — PostgreSQL (read-only run path)
│   │   ├── providers/              # Live data providers (mypy ignore_errors)
│   │   │   ├── base.py
│   │   │   ├── exchange_base.py
│   │   │   ├── ccxt_provider.py    # CCXT unified interface
│   │   │   ├── oanda_provider.py   # OANDA via tpqoa
│   │   │   └── binance_stream.py   # Binance WebSocket live kline streaming
│   │   └── exchange/               # Empty placeholder dir (exchange-specific adapters)
│   ├── screeners_handler/          # Market screening (deferred subsystem, mypy ignore)
│   │   ├── screeners_handler.py
│   │   └── screeners/
│   │       ├── base.py
│   │       ├── BestScreener.py
│   │       ├── cointegrated_pairs.py
│   │       ├── most_performing.py
│   │       └── volume_spyke.py
│   ├── trading_system/             # Composition roots and run loops (mixed indentation)
│   │   ├── backtest_trading_system.py   # TradingSystem — backtest for-loop
│   │   ├── live_trading_system.py       # LiveTradingSystem — threaded daemon
│   │   ├── trading_interface.py         # TradingInterface — external API bridge
│   │   └── simulation/
│   │       └── time_generator.py        # TimeGenerator — yields TimeEvents
│   ├── universe/                   # Membership derivation
│   │   └── membership.py           # derive_membership(), is_active(), active_membership()
│   ├── reporting/                  # Pure post-run builders (no handler imports)
│   │   ├── frames.py               # build_trade_log(), build_equity_curve()
│   │   ├── metrics.py              # cagr(), sharpe(), sortino(), max_drawdown(), etc.
│   │   ├── plots.py                # Plotly charts
│   │   ├── summary.py              # Summary formatter
│   │   ├── orders.py               # Order-log builder
│   │   └── cash_operations.py      # Cash-operation log builder
│   └── outils/                     # Shared utilities
│       ├── id_generator.py         # IDGenerator — uuid-utils backed UUIDv7
│       └── time_parser.py          # to_timedelta(), check_timeframe()
│
├── tests/                          # Test suite (testpaths = ["tests"] in pyproject.toml)
│   ├── conftest.py                 # Root conftest — auto-marks unit/integration/e2e from folder
│   ├── unit/                       # Unit tests — domain-grouped
│   │   ├── config/                 # Config model tests
│   │   ├── core/                   # bar, clock, enums, exceptions, money, sizing tests
│   │   ├── events/                 # Event immutability, dispatch registry, fill/order schema
│   │   ├── execution/              # Fee/slippage models, matching engine, simulated exchange
│   │   │   └── exchanges/
│   │   ├── order/                  # Order, order_manager, validator, brackets, sizing, admission
│   │   ├── portfolio/              # Cash, positions, transactions, metrics, portfolio handler
│   │   │   ├── positions/
│   │   │   └── transaction/
│   │   ├── price/                  # Bar feed tests
│   │   ├── reporting/              # Metrics and frames tests
│   │   ├── strategy/               # Strategy handler tests
│   │   ├── universe/               # Membership derivation tests
│   │   └── outils/                 # ID generator, time parser tests
│   ├── integration/                # Cross-component integration tests
│   │   ├── test_backtest_smoke.py  # Full pipeline smoke test
│   │   ├── test_backtest_oracle.py # Behavioral oracle gate
│   │   ├── test_event_wiring.py    # EventHandler routing
│   │   ├── test_execution_handler_routing.py
│   │   ├── test_reservation_inertness.py
│   │   └── test_universe_spans.py
│   ├── e2e/                        # Scenario-based end-to-end tests (golden master)
│   │   ├── conftest.py             # E2E harness fixtures (TradingSystem wiring)
│   │   ├── scenario_spec.py        # ScenarioSpec dataclass (bars, actions, assertions)
│   │   ├── strategies/             # Test-only scripted strategy emitters
│   │   │   ├── scripted_emitter.py
│   │   │   └── single_market_buy.py
│   │   ├── smoke/                  # single_market_buy golden
│   │   ├── matching/               # entries/, gaps/, brackets/, operator/ scenarios
│   │   ├── cost/                   # fee+slippage scenarios
│   │   ├── sizing/                 # fixed_quantity, risk_percent, over_cash_reject
│   │   ├── sltp/                   # from_decision_* and from_fill_* SL/TP scenarios
│   │   ├── admission/              # max_positions, re_entry, scale_in, scale_out
│   │   ├── cash/                   # cash release on cancel/refuse/reject
│   │   ├── multi/                  # two_strategies, two_tickers, fanout_portfolios, contended_cash
│   │   └── robust/                 # determinism, metrics_finite, flat/losing/no_trade/sparse_bar
│   └── golden/                     # Golden-master oracle artifacts
│       ├── CROSS-VALIDATION.md     # Cross-validation instructions
│       ├── FINAL-ORACLE.md         # Frozen oracle documentation
│       ├── equity.csv              # Frozen equity curve (byte-exact oracle)
│       ├── trades.csv              # Frozen trade log (byte-exact oracle)
│       └── summary.json            # Frozen summary metrics
│
├── scripts/                        # Developer CLI scripts
│   ├── run_backtest.py             # Golden-run entry point (serializes output/ artifacts)
│   ├── normalize_data.py           # Data normalization / ingestion
│   ├── cross_validate.py           # Cross-validation runner (backtesting.py + backtrader)
│   └── crossval/                   # Cross-validation helpers
│       ├── backtesting_py_run.py
│       ├── backtrader_run.py
│       ├── nautilus_run.py
│       ├── indicators.py
│       └── reconcile.py
│
├── data/                           # Price data files
│   └── raw/                        # Raw OHLCV CSVs
│       ├── BTCUSD_1d_ohlcv_*.csv   # Golden dataset (referenced by TradingSystem)
│       ├── ETHUSD_1d.csv
│       └── SOLUSD_1d.csv, AAVEUSD_1d.csv
│
├── settings/                       # Domain config YAML files (gitignored in prod)
│   ├── domains/                    # Committed defaults
│   │   ├── portfolio.default.yaml
│   │   ├── system.default.yaml
│   │   └── trading.default.yaml
│   ├── portfolio_handler.yaml      # Active portfolio config (local override)
│   └── portfolio_handler.default.yaml
│
├── output/                         # Backtest run artifacts (generated, not committed)
│   ├── equity.csv
│   ├── trades.csv
│   └── summary.json
│
├── notebooks/                      # Jupyter exploration notebooks
│   ├── iTrader_backtester.ipynb    # Main backtester notebook
│   └── test_price_handler.ipynb
│
├── docs/                           # Architecture and design documents
│   ├── order_handler/
│   ├── portfolio_handler/
│   └── superpowers/
│
├── .planning/                      # GSD planning artifacts
│   ├── codebase/                   # Codebase map documents (this dir)
│   ├── milestones/                 # Completed milestone phase archives
│   │   ├── v1.0-phases/
│   │   ├── v1.1-phases/
│   │   └── v1.2-phases/
│   ├── phases/                     # Active future phase plans
│   └── todos/                      # GSD todo tracking
│
├── pyproject.toml                  # Dependencies, pytest config, mypy config (single source of truth)
├── Makefile                        # Developer commands (loads .env via include)
├── poetry.lock                     # Committed lockfile (~492 KB)
├── CLAUDE.md                       # Project instructions for Claude Code
└── README.md
```

## Directory Purposes

**`itrader/`:**
- Purpose: The main installable Python package. All application code lives here.
- Key files: `__init__.py` (singletons), `logger.py` (structlog setup)

**`itrader/core/`:**
- Purpose: Dependency root — no imports from anywhere inside `itrader`. Holds cross-cutting primitives that everything else depends on.
- Contains: Enums, exceptions, IDs, money utilities, clock, sizing vocabulary, read-model Protocol.
- Key files: `ids.py`, `money.py`, `sizing.py`, `portfolio_read_model.py`, `enums/__init__.py` (barrel)

**`itrader/config/`:**
- Purpose: Pydantic-modelled configuration for all domains. No registry/provider pattern — use `SystemConfig.default()` or `PortfolioConfig.default()` directly.
- Indentation: 4 spaces (not tabs).
- Key files: `system.py`, `portfolio.py`, `exchange.py`, `strategy.py`

**`itrader/events_handler/`:**
- Purpose: Queue dispatch and all event dataclass definitions.
- Key files: `full_event_handler.py` (dispatch), `events/__init__.py` (barrel re-export)

**`itrader/order_handler/`:**
- Purpose: Order domain — signal-to-order translation, admission, bracket declaration, lifecycle, reconciliation, storage.
- Indentation: tabs.
- Structure: `order_handler.py` (interface) → `order_manager.py` (orchestrator) → `admission/`, `brackets/`, `lifecycle/`, `reconcile/` sub-managers → `storage/`.

**`itrader/execution_handler/`:**
- Purpose: Execution domain — order routing to exchanges, resting-order matching, fee/slippage application.
- Indentation: tabs.
- Key files: `matching_engine.py` (pure, no queue/log deps), `exchanges/simulated.py`, `fee_model/`, `slippage_model/`

**`itrader/portfolio_handler/`:**
- Purpose: Portfolio domain — lifecycle, mark-to-market, fill processing, equity snapshots.
- Indentation: 4 spaces (newer module).
- Structure: `portfolio_handler.py` (collection + PortfolioReadModel) → `portfolio.py` (per-portfolio) → `cash/`, `position/`, `transaction/`, `metrics/` sub-managers.

**`itrader/price_handler/`:**
- Purpose: Data engine — price storage (CSV/SQL), look-ahead-safe feed, live providers.
- Indentation: 4 spaces in `feed/` (newer); tabs elsewhere.
- Key files: `feed/bar_feed.py` (bar-timing contract), `store/csv_store.py` (golden run)

**`itrader/strategy_handler/`:**
- Purpose: Strategy execution — fan-out per BAR, signal recording, user strategies.
- Indentation: tabs.
- Key files: `strategies_handler.py` (fan-out), `base.py` (Strategy ABC), `strategies/SMA_MACD_strategy.py` (reference)

**`itrader/trading_system/`:**
- Purpose: Composition roots. Wire all components around the shared queue and drive the run loop.
- Key files: `backtest_trading_system.py` (TradingSystem.run()), `live_trading_system.py`, `trading_interface.py`

**`itrader/reporting/`:**
- Purpose: Pure post-run frame builders and metrics calculators. Zero handler imports.
- Key files: `frames.py` (trade log + equity curve — shared between engine and `run_backtest.py`), `metrics.py`

**`tests/e2e/<scenario>/golden/`:**
- Purpose: Frozen golden artifacts for each E2E scenario (CSV/JSON byte-exact comparison).
- Generated: Yes (by running with `--update-golden`)
- Committed: Yes (regression lock)

**`tests/golden/`:**
- Purpose: Full-pipeline oracle artifacts from `SMA_MACD` golden run.
- Key files: `equity.csv`, `trades.csv`, `summary.json` (all byte-exact oracle gates)

**`settings/domains/`:**
- Purpose: Committed YAML defaults loaded by the Pydantic config system.
- Generated: No (committed defaults)
- Active overrides: `settings/portfolio_handler.yaml` (local, may be gitignored in prod)

## Key File Locations

**Entry Points:**
- `itrader/trading_system/backtest_trading_system.py`: `TradingSystem.run()` — primary backtest entry
- `scripts/run_backtest.py`: CLI script; wires and runs a `TradingSystem`; serializes `output/` artifacts
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()` — live entry

**Configuration:**
- `pyproject.toml`: Dependencies, pytest options (`filterwarnings`, `--strict-markers`), mypy config
- `itrader/__init__.py`: Process-level singleton initialization
- `itrader/config/system.py`: `SystemConfig.default()` — the canonical config constructor
- `settings/domains/`: Committed YAML defaults

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: The dispatch table (`_routes`)
- `itrader/execution_handler/matching_engine.py`: Pure order-book trigger evaluation
- `itrader/price_handler/feed/bar_feed.py`: Bar-timing contract (seven rules, single enforcement point)
- `itrader/core/money.py`: `to_money()` and `quantize()` — the only correct Decimal entry points
- `itrader/core/portfolio_read_model.py`: `PortfolioReadModel` Protocol definition

**Reference Strategy:**
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`

**Testing:**
- `tests/conftest.py`: Root conftest with auto-marker from folder path
- `tests/e2e/conftest.py`: E2E harness fixtures (`TradingSystem` wiring)
- `tests/e2e/scenario_spec.py`: `ScenarioSpec` dataclass defining scenario structure
- `tests/golden/`: Byte-exact oracle artifacts

## Naming Conventions

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handler modules: `<domain>_handler.py` (e.g., `order_handler.py`, `execution_handler.py`).
- Manager modules: `<domain>_manager.py` (e.g., `order_manager.py`, `cash_manager.py`).
- Storage backends: `<backend>_storage.py` (e.g., `in_memory_storage.py`, `postgresql_storage.py`).
- Abstract bases: `base.py` inside each domain package.
- Tests mirror source: `test_<module>.py` (e.g., `test_order_manager.py`).

**Classes:**
- `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `CashManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `Side.BUY`.

**Functions / Methods:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_order()`, `get_active_orders()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.
- Module-private constants: leading underscore — `_ONE`, `_DEFAULT_SCALES`, `_AGG`.

**Variables:**
- `snake_case` always.
- The shared event queue: always `global_queue` (constructor parameter) or `events_queue`.
- Bound logger: always `self.logger`.
- Config object: always `self.config` or a typed config (e.g., `SystemConfig`).

**String-to-enum maps:** `<domain>_<type>_map` — `order_type_map`, `order_status_map`, `order_command_map`.

## Where to Add New Code

**New Strategy:**
- Implementation: `itrader/strategy_handler/my_strategies/<category>/<name>.py` (subclass `Strategy` from `itrader/strategy_handler/base.py`)
- Config: Add a `BaseStrategyConfig` subclass in `itrader/config/strategy.py`
- Tests: `tests/unit/strategy/test_<name>.py`
- Wire: Add to `TradingSystem.__init__` via `strategies_handler.add_strategy()`

**New Reference (built-in) Strategy:**
- Implementation: `itrader/strategy_handler/strategies/<name>.py`
- Same test and wiring path as above.

**New Event Type:**
1. Add frozen dataclass in `itrader/events_handler/events/<domain>.py`
2. Add `EventType.X` in `itrader/core/enums/event.py`
3. Re-export from `itrader/events_handler/events/__init__.py`
4. Add a branch to `EventHandler._routes` in `itrader/events_handler/full_event_handler.py`
5. Tests: `tests/unit/events/test_<event_type>.py`

**New Exchange Implementation:**
- Implementation: `itrader/execution_handler/exchanges/<name>.py` (subclass `AbstractExchange` from `base.py`)
- Register in `ExecutionHandler.init_exchanges()` in `itrader/execution_handler/execution_handler.py`
- Tests: `tests/unit/execution/exchanges/test_<name>.py`

**New Fee Model:**
- Implementation: `itrader/execution_handler/fee_model/<name>_fee_model.py` (subclass `base.py`)
- Add to `FeeModelType` config enum in `itrader/config/exchange.py`

**New Slippage Model:**
- Implementation: `itrader/execution_handler/slippage_model/<name>_slippage_model.py` (subclass `base.py`)
- Add to `SlippageModelType` config enum in `itrader/config/exchange.py`

**New Order Storage Backend:**
- Implementation: `itrader/order_handler/storage/<backend>_storage.py` (subclass `base.py::OrderStorage`)
- Register in `itrader/order_handler/storage/storage_factory.py`

**New Core Exception:**
- Add to appropriate file in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`)
- Re-export from `itrader/core/exceptions/__init__.py`

**New Screener:**
- Implementation: `itrader/screeners_handler/screeners/<name>.py` (subclass `base.py`)

**New Enum:**
- For order/execution/event/portfolio/trading domain: add to the appropriate `itrader/core/enums/<domain>.py` and re-export from `itrader/core/enums/__init__.py`
- For config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, etc.): add to `itrader/config/<domain>.py` — do NOT put these in `core/enums/` (that would invert the core→config dependency)

**New Unit Test:**
- Location: `tests/unit/<domain>/test_<module>.py`
- No test marker needed — auto-applied from folder location by `tests/conftest.py`
- Only `unit`, `integration`, `slow`, `e2e` markers are declared in `pyproject.toml`

**New E2E Scenario:**
- Directory: `tests/e2e/<category>/<scenario_name>/`
- Files: `test_<scenario>.py` + `golden/` subdirectory with frozen artifact CSVs/JSON
- Use `ScenarioSpec` from `tests/e2e/scenario_spec.py` + E2E harness fixtures from `tests/e2e/conftest.py`

**New Config Domain:**
- Model: `itrader/config/<domain>.py` (Pydantic `BaseModel` with `ConfigDict(extra="ignore")`)
- Re-export from `itrader/config/__init__.py`
- Wire into `SystemConfig` in `itrader/config/system.py`
- Add YAML default: `settings/domains/<domain>.default.yaml`

**New Utility:**
- Shared helpers: `itrader/outils/<name>.py`
- Cross-cutting primitives (no `itrader` imports): `itrader/core/<name>.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD workflow planning artifacts — phase plans, codebase maps, todos.
- Generated: Partially (by GSD commands).
- Committed: Yes.

**`tests/golden/`:**
- Purpose: Byte-exact oracle artifacts from the `SMA_MACD` golden run. Regenerated only at milestone-defined refreeze points.
- Generated: Yes (by `scripts/run_backtest.py`; refreeze via oracle procedure).
- Committed: Yes (regression lock — never modify without the documented refreeze procedure).

**`tests/e2e/<scenario>/golden/`:**
- Purpose: Per-scenario golden artifacts for E2E regression locks.
- Generated: Yes (by running with `--update-golden` flag).
- Committed: Yes.

**`output/`:**
- Purpose: Runtime backtest output artifacts (equity curve, trade log, summary).
- Generated: Yes (by `scripts/run_backtest.py`).
- Committed: No (gitignored in normal use; committed snapshots live in `tests/golden/`).

**`htmlcov/`:**
- Purpose: HTML coverage report generated by `make test-cov`.
- Generated: Yes.
- Committed: No.

**`.venv/`:**
- Purpose: In-project Poetry virtualenv.
- Generated: Yes (by `make init-env` / `poetry install`).
- Committed: No.

---

*Structure analysis: 2026-06-12*
