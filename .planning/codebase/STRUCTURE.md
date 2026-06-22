# Codebase Structure

**Analysis Date:** 2026-06-22

## Directory Layout

```
intelli-trader/
├── itrader/                         # Main package
│   ├── __init__.py                  # Process-wide singletons: config, logger, idgen
│   ├── logger.py                    # structlog init + get_itrader_logger()
│   ├── config/                      # Pydantic config models (4-space indent)
│   │   ├── system.py                # SystemConfig, PerformanceSettings, MonitoringSettings
│   │   ├── portfolio.py             # PortfolioConfig, TradingRules, PortfolioLimits
│   │   ├── exchange.py              # ExchangeConfig, FeeModelType, SlippageModelType
│   │   ├── order.py                 # OrderConfig, TrailType
│   │   ├── models.py                # Shared config utilities
│   │   ├── merge.py                 # deep_merge helper
│   │   └── settings.py             # pydantic-settings Settings (env vars, ITRADER_ prefix)
│   ├── core/                        # Depends on nothing inside itrader (4-space indent)
│   │   ├── enums/                   # All domain enums
│   │   │   ├── event.py             # EventType
│   │   │   ├── order.py             # OrderType, OrderStatus, VALID_ORDER_TRANSITIONS, maps
│   │   │   ├── portfolio.py         # PositionSide, PortfolioState, TransactionType, etc.
│   │   │   ├── execution.py         # ExecutionErrorCode, FillStatus, ExchangeConnectionStatus
│   │   │   ├── trading.py           # Side, Timeframe, TradingDirection, MarketExecution, etc.
│   │   │   ├── severity.py          # ErrorSeverity
│   │   │   └── system.py            # SystemStatus
│   │   ├── exceptions/
│   │   │   ├── base.py              # ITraderError, ValidationError, ConfigurationError, StateError
│   │   │   ├── order.py             # OrderError, UnsizedSignalError, SizingPolicyViolation
│   │   │   ├── portfolio.py         # PortfolioError, InsufficientFundsError, PortfolioNotFoundError
│   │   │   ├── data.py              # DataError, MalformedDataError, MissingPriceDataError
│   │   │   └── strategy.py          # UnknownParamError, MissingParamError
│   │   ├── instrument.py            # Instrument frozen value object (v1.4 INST-01)
│   │   ├── portfolio_read_model.py  # PortfolioReadModel Protocol + PositionView DTO
│   │   ├── money.py                 # to_money(), quantize(), Decimal discipline
│   │   ├── clock.py                 # BacktestClock (determinism seam)
│   │   ├── bar.py                   # Bar named tuple (OHLCV, Decimal-typed)
│   │   ├── sizing.py                # SignalIntent, SizingPolicy, SLTPPolicy, TradingDirection
│   │   ├── ids.py                   # Typed ID aliases (OrderId, PortfolioId, etc.)
│   │   ├── constants.py             # Shared constants
│   │   └── commission_estimator.py  # CommissionEstimator Protocol
│   ├── events_handler/
│   │   ├── full_event_handler.py    # EventHandler: _routes dict, process_events, _dispatch
│   │   └── events/                  # Frozen event dataclasses (4-space indent)
│   │       ├── base.py              # Event base + TimeEvent
│   │       ├── market.py            # BarEvent, ScreenerEvent
│   │       ├── signal.py            # SignalEvent
│   │       ├── order.py             # OrderEvent (carries leverage, trail_type, trail_value)
│   │       ├── fill.py              # FillEvent
│   │       └── error.py             # ErrorEvent, PortfolioErrorEvent, PortfolioUpdateEvent
│   ├── trading_system/              # Composition root + run drivers (tabs indent)
│   │   ├── compose.py               # compose_engine(), Engine dataclass, FeeModelCommissionEstimator
│   │   ├── system_spec.py           # SystemSpec, PortfolioSpec, Action (frozen dataclasses)
│   │   ├── backtest_trading_system.py  # BacktestTradingSystem, build_backtest_system(spec)
│   │   ├── backtest_runner.py       # BacktestRunner: session init + for-loop
│   │   ├── live_trading_system.py   # LiveTradingSystem: daemon thread + lifecycle
│   │   ├── trading_interface.py     # TradingInterface: web-API → live system bridge
│   │   └── simulation/
│   │       └── time_generator.py    # TimeGenerator: yields TimeEvents over ping-grid
│   ├── order_handler/               # tabs indent
│   │   ├── order.py                 # Order entity (business object, NOT an event)
│   │   ├── order_handler.py         # OrderHandler (thin interface)
│   │   ├── order_manager.py         # OrderManager (coordinator, delegates to sub-managers)
│   │   ├── order_validator.py       # EnhancedOrderValidator
│   │   ├── sizing_resolver.py       # SizingResolver (one resolver, D-01/M5-06)
│   │   ├── operation_result.py      # OperationResult value object
│   │   ├── base.py                  # OrderStorage Protocol
│   │   ├── admission/
│   │   │   └── admission_manager.py # Signal→order pipeline (gates + sizing + reservation)
│   │   ├── brackets/
│   │   │   ├── bracket_book.py      # BracketBook + _PendingBracket
│   │   │   ├── bracket_manager.py   # BracketManager (assembly seam)
│   │   │   └── levels.py            # Bracket level helpers
│   │   ├── lifecycle/
│   │   │   └── lifecycle_manager.py # Modify / cancel / expire operations
│   │   ├── reconcile/
│   │   │   └── reconcile_manager.py # FillEvent → order mirror reconciliation
│   │   └── storage/
│   │       ├── in_memory_storage.py
│   │       ├── postgresql_storage.py  # NotImplementedError placeholder
│   │       └── storage_factory.py
│   ├── portfolio_handler/           # tabs indent (managers use 4-space)
│   │   ├── portfolio_handler.py     # PortfolioHandler: lifecycle + PortfolioReadModel + liquidation engine
│   │   ├── portfolio.py             # Portfolio: self-contained state + four sub-managers
│   │   ├── base.py                  # PortfolioStateStorage Protocol
│   │   ├── validators.py
│   │   ├── cash/
│   │   │   └── cash_manager.py      # CashManager: balance + reservations + locked margin + audit trail
│   │   ├── position/
│   │   │   ├── position.py          # Position: leverage, _last_accrual_time (borrow carry)
│   │   │   └── position_manager.py  # PositionManager: open/close/scale/mark/carry
│   │   ├── transaction/
│   │   │   ├── transaction.py       # Transaction record
│   │   │   └── transaction_manager.py
│   │   ├── metrics/
│   │   │   └── metrics_manager.py   # MetricsManager: equity snapshots, drawdown, etc.
│   │   └── storage/
│   │       ├── in_memory_storage.py
│   │       └── storage_factory.py
│   ├── execution_handler/           # tabs indent
│   │   ├── execution_handler.py     # ExecutionHandler: on_order / on_market_data routing
│   │   ├── base.py                  # AbstractExecutionHandler
│   │   ├── matching_engine.py       # MatchingEngine: resting book + trailing ratchet (TrailState)
│   │   ├── result_objects.py        # ConnectionResult, HealthStatus, OrderPreflightResult
│   │   ├── exchanges/
│   │   │   ├── base.py              # AbstractExchange
│   │   │   └── simulated.py         # SimulatedExchange: fee/slippage + MatchingEngine compose
│   │   ├── fee_model/
│   │   │   ├── base.py
│   │   │   ├── zero_fee_model.py
│   │   │   ├── percent_fee_model.py
│   │   │   └── maker_taker_fee_model.py
│   │   └── slippage_model/
│   │       ├── base.py
│   │       ├── zero_slippage_model.py
│   │       ├── fixed_slippage_model.py
│   │       └── linear_slippage_model.py
│   ├── strategy_handler/            # tabs indent
│   │   ├── strategies_handler.py    # StrategiesHandler: per-bar dispatch (single + pair)
│   │   ├── base.py                  # Strategy ABC: _apply_params, validate, generate_signal
│   │   ├── pair_base.py             # PairStrategy ABC: evaluate_pair, beta/z knobs (v1.4)
│   │   ├── primitives.py            # Shared strategy primitives
│   │   ├── signal_record.py         # SignalRecord (post-run read-model)
│   │   ├── indicators/
│   │   │   ├── catalog.py           # Built-in indicator catalog
│   │   │   └── handle.py            # IndicatorHandle + IndicatorAdapter Protocol
│   │   ├── strategies/              # Reference / built-in strategies
│   │   │   ├── SMA_MACD_strategy.py # Reference golden strategy (LONG_ONLY)
│   │   │   ├── eth_btc_pair_strategy.py  # Reference pair strategy (v1.4)
│   │   │   └── empty_strategy.py
│   │   ├── my_strategies/           # User-supplied strategies (deferred from mypy strict)
│   │   │   ├── mean_reversion/      # zscore_pairs_strategy, PriceD_BB, PriceD_BB_2
│   │   │   ├── momentum/            # ATR_Hawkes_Momentum
│   │   │   ├── scalping/            # RSI, Stoch_RSI_Keltner, VWAP_BB_RSI
│   │   │   ├── trend_following/     # SuperSmoothing, SuperTrend_DD
│   │   │   ├── filters/             # momentum_filters, noise_filters, trend_filters, volatility_filters
│   │   │   └── custom_indicators/   # custom_ind, ehlers_indicators
│   │   └── storage/
│   │       ├── base.py
│   │       ├── in_memory_storage.py
│   │       └── storage_factory.py
│   ├── price_handler/
│   │   ├── store/
│   │   │   ├── base.py              # PriceStore Protocol
│   │   │   ├── csv_store.py         # CsvPriceStore (eager-load; multi-ticker via csv_paths dict)
│   │   │   └── sql_store.py         # SqlHandler (PostgreSQL, read-only on run path; deferred from mypy strict)
│   │   ├── feed/                    # 4-space indent
│   │   │   ├── base.py              # BarFeed Protocol
│   │   │   └── bar_feed.py          # BacktestBarFeed: bar-timing contract (7 rules), precompute, generate_bar_event
│   │   ├── providers/               # deferred from mypy strict
│   │   │   ├── base.py
│   │   │   ├── ccxt_provider.py
│   │   │   ├── oanda_provider.py
│   │   │   ├── binance_stream.py
│   │   │   └── exchange_base.py
│   │   └── ingestion.py             # Data ingestion utilities
│   ├── universe/
│   │   ├── universe.py              # Universe: members list + Instrument map facade
│   │   ├── membership.py            # derive_membership(), is_active()
│   │   └── instruments.py           # derive_instruments()
│   ├── screeners_handler/           # deferred subsystem
│   │   ├── screeners_handler.py
│   │   └── screeners/
│   │       ├── base.py
│   │       ├── BestScreener.py
│   │       ├── cointegrated_pairs.py
│   │       ├── most_performing.py
│   │       └── volume_spyke.py
│   ├── reporting/
│   │   ├── frames.py                # build_trade_log(), build_equity_curve() — byte-exact oracle builders
│   │   ├── metrics.py               # Performance metric derivation (scipy linregress)
│   │   ├── plots.py                 # plotly interactive charts
│   │   ├── orders.py                # Order report builder
│   │   ├── cash_operations.py       # Cash-operation report
│   │   └── summary.py               # print_metrics_summary()
│   └── outils/
│       ├── id_generator.py          # IDGenerator (uuid-utils UUIDv7 wrapper)
│       └── time_parser.py           # to_timedelta(), check_timeframe(), etc.
├── tests/
│   ├── conftest.py                  # Top-level: folder-derived type markers (unit/integration/e2e)
│   ├── unit/                        # Fast component tests (-m unit)
│   │   ├── conftest.py
│   │   ├── config/                  # test_config_models, test_order_config
│   │   ├── core/                    # test_bar, test_clock, test_money, test_instrument, test_sizing, ...
│   │   ├── events/                  # test_events, test_dispatch_registry, test_error_flow, ...
│   │   ├── execution/               # test_matching_engine, test_matching_engine_trailing, test_fee_models, ...
│   │   ├── order/                   # test_admission_rules, test_leverage_plumbing, test_on_signal, ...
│   │   ├── portfolio/               # positions/, transaction/, test_cash_manager, ...
│   │   ├── price_handler/           # test_bar_feed, test_bar_feed_timing
│   │   ├── price/                   # Additional price tests
│   │   ├── reporting/               # test_frames, test_metrics
│   │   ├── strategy/                # test_strategy_base, test_pair_strategy, ...
│   │   └── universe/                # test_universe, test_instruments
│   ├── integration/                 # Cross-component tests (-m integration)
│   │   ├── test_backtest_oracle.py  # Byte-exact SMA_MACD oracle (the golden master)
│   │   └── pair_exit_safety/        # Pair strategy exit safety tests
│   ├── e2e/                         # Full-stack scenario tests (-m e2e)
│   │   ├── smoke/                   # single_market_buy
│   │   ├── matching/                # entries/, gaps/, brackets/, never_fill/, operator/
│   │   ├── sltp/                    # from_decision_*/from_fill_* SL/TP scenarios
│   │   ├── sizing/                  # fixed_quantity/, risk_percent/, over_cash_reject/
│   │   ├── cost/                    # percent_fee/, maker_taker/, fixed_slippage/, linear_slippage/, ...
│   │   ├── admission/               # max_positions/, re_entry/, scale_in/, scale_out/
│   │   ├── cash/                    # release_cancelled/, release_refused/, release_rejected/
│   │   ├── multi/                   # two_strategies/, two_tickers/, fanout_portfolios/, contended_cash/
│   │   ├── robust/                  # flat/, losing/, no_trade/, sparse_bar/, union_window/
│   │   ├── strategies/              # SMA_MACD e2e strategy tests
│   │   ├── levered_long/            # v1.4: levered long position scenario
│   │   ├── levered_long_into_liquidation/  # v1.4: levered long → liquidation trigger
│   │   ├── forced_liq_long/         # v1.4: forced liquidation long
│   │   ├── forced_liq_short/        # v1.4: forced liquidation short
│   │   ├── short_roundtrip/         # v1.4: short open → close
│   │   ├── short_carry/             # v1.4: borrow-carry accrual over bars
│   │   ├── short_scale_in/          # v1.4: scale-in on a short position
│   │   ├── short_scale_in_partial_cover/  # v1.4: partial cover on short scale-in
│   │   ├── partial_cover/           # v1.4: partial position cover
│   │   ├── trailing_long/           # v1.4: trailing stop on long position
│   │   └── trailing_short/          # v1.4: trailing stop on short position
│   └── golden/                      # Oracle artifacts (0 tests collected by pytest)
│       ├── pair/                    # Pair strategy golden data
│       └── CROSS-VALIDATION.md
├── scripts/
│   ├── run_backtest.py              # CLI: build + run + print SMA_MACD backtest
│   ├── cross_validate.py            # backtesting.py oracle comparison
│   ├── cross_validate_accounting.py
│   ├── cross_validate_limit.py
│   ├── cross_validate_trailing.py
│   └── crossval/                    # Cross-validation utilities
├── data/
│   └── raw/                         # Golden CSV files (e.g. BTCUSD_1d_ohlcv_2018_2026.csv)
├── settings/                        # YAML config overrides (gitignored in prod)
│   └── domains/                     # *.default.yaml tracked as shipped defaults
├── docs/                            # Developer docs (order_handler/, portfolio_handler/, superpowers/)
├── notebooks/                       # Jupyter exploration
├── output/                          # Run artifacts (trade logs, equity curves)
├── .planning/                       # GSD planning artifacts
│   ├── codebase/                    # THIS directory (ARCHITECTURE.md, STRUCTURE.md, ...)
│   └── milestones/                  # v1.0 through v1.4 phase archives
├── pyproject.toml                   # Single source: deps, pytest config, mypy config
├── Makefile                         # Developer task runner (make test, make backtest, ...)
├── CLAUDE.md                        # Project-level Claude guidance
└── poetry.lock
```

## Directory Purposes

**`itrader/`:**
- Purpose: Main package. Import anything from `itrader` triggers singleton init in `__init__.py`.
- Key files: `__init__.py` (singletons), `logger.py` (structlog).

**`itrader/core/`:**
- Purpose: Cross-cutting primitives; depends on nothing inside `itrader`. The zeroth dependency layer.
- Contains: Enums, exceptions, `Instrument`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `ids.py`, `portfolio_read_model.py`.
- Key rule: Never import from any other `itrader.*` sub-package here.

**`itrader/config/`:**
- Purpose: Pydantic v2 config models. The seven `str, Enum` config-domain enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, `TrailType`, etc.) live HERE, not in `core/enums/` (config-enum exception — relocating inverts the core→config dependency).
- Uses 4-space indent (unlike handler modules).

**`itrader/events_handler/`:**
- Purpose: The queue dispatch engine and all event dataclasses.
- `full_event_handler.py`: the ONLY place routing is defined.
- `events/`: frozen event dataclasses, one file per domain.

**`itrader/trading_system/`:**
- Purpose: Composition root, run drivers, declarative spec. The top layer — wires everything.
- `compose.py`: `compose_engine` is the mode-agnostic wiring seam.
- `backtest_trading_system.py`: thin holder + `build_backtest_system(spec)` factory.
- `backtest_runner.py`: session setup + per-tick for-loop; owns Trap-4 Universe wiring.
- Uses tabs indent.

**`itrader/order_handler/`:**
- Purpose: Signal-to-order admission, bracket management, lifecycle, reconciliation, order mirror storage.
- `order_handler.py`: thin interface (queue-aware).
- `order_manager.py`: coordinator that delegates to four sub-manager collaborators.
- Sub-packages: `admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `storage/`.
- Uses tabs indent.

**`itrader/portfolio_handler/`:**
- Purpose: Portfolio lifecycle, mark-to-market, borrow-carry accrual, liquidation engine, `PortfolioReadModel` implementation.
- `portfolio_handler.py`: the `PortfolioReadModel` Protocol implementation + liquidation engine.
- Sub-packages: `cash/`, `position/`, `transaction/`, `metrics/`, `storage/`.
- Uses 4-space indent for managers; handler file uses tabs.

**`itrader/execution_handler/`:**
- Purpose: Exchange abstraction, resting-order matching, fee/slippage cost models.
- `matching_engine.py`: pure, queue-free; receives `OrderEvent` / `BarEvent`, returns `FillDecision`/`CancelDecision`.
- Uses tabs indent.

**`itrader/strategy_handler/`:**
- Purpose: Strategy base classes, handler, indicator framework, signal store.
- `base.py`: `Strategy` ABC (4-space; single-ticker).
- `pair_base.py`: `PairStrategy` ABC (tabs; two-leg, v1.4).
- `strategies/`: reference/built-in strategies (tabs).
- `my_strategies/`: user-supplied; deferred from mypy strict; 4-space.
- `indicators/`: declared indicator framework (catalog + handle).

**`itrader/price_handler/`:**
- Purpose: Data engine — store, look-ahead-safe feed, live providers.
- `feed/bar_feed.py`: single enforcement point of the seven bar-timing rules (4-space).
- `store/`: CSV (backtest) + SQL (live, deferred).
- `providers/`: CCXT, OANDA, Binance (deferred from mypy strict).

**`itrader/universe/`:**
- Purpose: `Universe` facade + `derive_membership` / `derive_instruments` pure functions; injected as a read-model.

**`itrader/reporting/`:**
- Purpose: Pure builders (no handler imports). `frames.py` is byte-exact oracle builder.

**`itrader/screeners_handler/`:**
- Purpose: Dynamic market screening (deferred subsystem; deferred from mypy strict).

**`itrader/outils/`:**
- Purpose: Utility helpers not fitting core. `id_generator.py` wraps `uuid-utils`; `time_parser.py` converts timeframe strings to `timedelta`.

**`tests/unit/`:**
- Purpose: Fast, isolated component tests. Each sub-directory mirrors an `itrader/` domain.
- Golden test: `tests/integration/test_backtest_oracle.py` (NOT under `tests/golden/`).

**`tests/e2e/`:**
- Purpose: Full-stack scenario tests. Each sub-directory is a scenario name with a `golden/` sub-directory for CSV snapshots. New v1.4 scenarios: `levered_long/`, `levered_long_into_liquidation/`, `forced_liq_long/`, `forced_liq_short/`, `short_*`, `trailing_long/`, `trailing_short/`.

**`tests/golden/`:**
- Purpose: Oracle artifacts only (0 tests collected). `pair/` holds pair strategy reference data.

**`data/raw/`:**
- Purpose: Golden OHLCV CSV files used by backtest and oracle. `BTCUSD_1d_ohlcv_2018_2026.csv` is the reference dataset.

**`settings/`:**
- Purpose: YAML config overrides; gitignored in production. `settings/domains/*.default.yaml` are tracked defaults.

**`.planning/`:**
- Purpose: GSD planning artifacts. `codebase/` = generated reference docs. `milestones/` = archived phase dirs (v1.0–v1.4). Never edit manually.

## Key File Locations

**Entry Points:**
- `itrader/trading_system/backtest_trading_system.py`: `build_backtest_system(spec)` factory + `BacktestTradingSystem.run()`
- `itrader/trading_system/backtest_runner.py`: `BacktestRunner._initialise_backtest_session` + `_run_backtest`
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start/stop`
- `scripts/run_backtest.py`: CLI entry point

**Routing / Dispatch:**
- `itrader/events_handler/full_event_handler.py`: `EventHandler._routes` — THE single routing registry

**Wiring:**
- `itrader/trading_system/compose.py`: `compose_engine()` — mode-agnostic graph wiring
- `itrader/__init__.py`: singletons (`config`, `logger`, `idgen`)

**Domain Config:**
- `pyproject.toml`: all deps, pytest settings, mypy settings
- `itrader/config/system.py`: `SystemConfig.default()`
- `itrader/config/portfolio.py`: `PortfolioConfig`, `TradingRules` (margin/leverage/short flags)
- `itrader/config/exchange.py`: `ExchangeConfig`, `get_exchange_preset()`
- `itrader/config/order.py`: `OrderConfig`, `TrailType`

**Money / IDs:**
- `itrader/core/money.py`: `to_money()`, `quantize()` — all financial arithmetic entry points
- `itrader/outils/id_generator.py`: `IDGenerator` (UUIDv7 via uuid-utils)

**Bar-timing contract:**
- `itrader/price_handler/feed/bar_feed.py`: the seven look-ahead-safety rules (module docstring)

**Golden oracle:**
- `tests/integration/test_backtest_oracle.py`: byte-exact SMA_MACD oracle test
- `data/raw/BTCUSD_1d_ohlcv_2018_2026.csv`: reference dataset

**v1.4 New Components:**
- `itrader/core/instrument.py`: `Instrument` value object (margin/borrow/liquidation fields)
- `itrader/universe/universe.py`: `Universe` facade
- `itrader/universe/instruments.py`: `derive_instruments()`
- `itrader/strategy_handler/pair_base.py`: `PairStrategy` ABC
- `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`: reference pair strategy
- `itrader/execution_handler/matching_engine.py`: `TrailState` (trailing stop ratchet)

## Naming Conventions

**Files:**
- `snake_case.py` throughout.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package.
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `postgresql_storage.py`.
- Test files: `test_<module>.py` mirroring the source.

**Directories:**
- `<domain>_handler/` — contains the handler + manager + sub-packages.
- Sub-packages named by responsibility: `admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `storage/`.
- Strategy subdirectories: `strategies/` (built-in), `my_strategies/` (user-supplied, not mypy-strict).

**Classes:**
- `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`.
- Handler/Manager split: `<Domain>Handler` + `<Domain>Manager`.
- Abstract bases: `Abstract<Name>` — `AbstractExchange`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`.
- Exception classes: `<Specific><Category>Error` — `InsufficientFundsError`, `SizingPolicyViolation`.

**Functions / Methods:**
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` or `create(...)` — `Order.new_order()`, `FillEvent.new_fill()`, `OrderStorageFactory.create(...)`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_order()`.
- Private helpers: single underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`.

**Attributes:**
- Shared queue: always `global_queue` (constructor parameter) or `events_queue`.
- Bound logger: always `self.logger`.
- Config: always `self.config` or a typed config object such as `SystemConfig`.

**Enums:**
- Names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Where to Add New Code

**New strategy (single-ticker):**
- Implementation: `itrader/strategy_handler/strategies/<name>_strategy.py` (built-in, mypy strict) or `itrader/strategy_handler/my_strategies/<category>/<name>_strategy.py` (user-supplied, relaxed typing).
- Pattern: Subclass `Strategy`; declare `name`, `tickers`, `sizing_policy`, `direction`; implement `generate_signal(ticker, bars) -> SignalIntent | None`. No queue or portfolio access.

**New pair strategy:**
- Implementation: `itrader/strategy_handler/strategies/<name>_pair_strategy.py`.
- Pattern: Subclass `PairStrategy`; declare two tickers; implement `evaluate_pair(win_A, win_B) -> tuple[SignalIntent|None, SignalIntent|None]`. Pin `direction = LONG_SHORT`.

**New event type:**
1. Define frozen dataclass in `itrader/events_handler/events/<domain>.py`.
2. Add member to `EventType` in `itrader/core/enums/event.py`.
3. Add branch to `EventHandler._routes` in `itrader/events_handler/full_event_handler.py`.

**New exchange:**
- Implementation: `itrader/execution_handler/exchanges/<name>.py`.
- Pattern: Subclass `AbstractExchange`; implement `on_order`, `on_market_data`, `connect`, `disconnect`, `health_check`, `validate_order`.
- Register in `ExecutionHandler.exchanges` dict.

**New fee model:**
- Implementation: `itrader/execution_handler/fee_model/<name>_fee_model.py`.
- Pattern: Subclass `FeeModel`; implement `calculate_fee(quantity, price, side, order_type) -> Decimal`.
- Add a `FeeModelType` enum member in `itrader/config/exchange.py`; wire in `SimulatedExchange._init_fee_model`.

**New slippage model:**
- Implementation: `itrader/execution_handler/slippage_model/<name>_slippage_model.py`.
- Wire: same pattern as fee model.

**New portfolio sub-manager:**
- Implementation: `itrader/portfolio_handler/<domain>/<domain>_manager.py`.
- Inject via `Portfolio._init_managers`; share `state_storage` seam.

**New config knob:**
- Add field to the relevant `BaseModel` in `itrader/config/`.
- If it is a `str, Enum` config-domain enum, place it IN `itrader/config/` (not `core/enums/`).
- Access via `portfolio_handler.config_data.trading_rules.<field>` or similar.

**New unit test:**
- Location: `tests/unit/<domain>/test_<module>.py`.
- The type marker (`unit`) is auto-applied from the folder by `tests/conftest.py`.

**New e2e scenario:**
- Location: `tests/e2e/<scenario_name>/test_<scenario_name>.py`.
- Add a `golden/` sub-directory for CSV snapshot fixtures.
- The type marker (`e2e`) is auto-applied from the folder.

## Special Directories

**`.planning/codebase/`:**
- Purpose: GSD-generated reference documents (ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, etc.).
- Generated: By `/gsd:map-codebase`.
- Committed: Yes.

**`.planning/milestones/`:**
- Purpose: Archived phase plan dirs from closed milestones (v1.0–v1.4).
- Committed: Yes (historical planning record).

**`htmlcov/`:**
- Purpose: Coverage HTML report generated by `make test-cov`.
- Generated: Yes.
- Committed: No (gitignored).

**`output/`:**
- Purpose: Run artifacts (trade logs, equity curves) from scripts.
- Generated: Yes.
- Committed: No.

**`data/raw/`:**
- Purpose: Committed golden OHLCV CSV datasets used in tests and scripts.
- Committed: Yes.

**`settings/`:**
- Purpose: YAML config overrides. `settings/domains/*.default.yaml` are committed defaults; production overrides are gitignored.
- Committed: Defaults only.

**`.venv/`:**
- Purpose: Poetry in-project virtualenv.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-06-22*
