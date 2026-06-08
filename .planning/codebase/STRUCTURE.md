# Codebase Structure

**Analysis Date:** 2026-06-08

## Directory Layout

```
intelli-trader/
├── itrader/                      # Application package
│   ├── __init__.py               # Process singletons: config, logger, idgen
│   ├── logger.py                 # structlog setup (init_logger, get_itrader_logger)
│   ├── trading_system/           # Composition roots + run loops
│   │   ├── backtest_trading_system.py   # TradingSystem (backtest for-loop)
│   │   ├── live_trading_system.py       # LiveTradingSystem (threaded)
│   │   ├── trading_interface.py         # API bridge
│   │   └── simulation/                  # SimulationEngine base + TimeGenerator
│   ├── events_handler/           # Queue dispatch + event facts
│   │   ├── full_event_handler.py        # EventHandler._routes dispatch
│   │   └── events/                      # Frozen event dataclasses by domain
│   │       ├── base.py, market.py, signal.py, order.py, fill.py, error.py
│   ├── order_handler/            # Order domain (thin handler + fat manager)
│   │   ├── order_handler.py, order_manager.py, order.py, base.py
│   │   ├── order_validator.py, sizing_resolver.py, operation_result.py
│   │   └── storage/                     # in_memory / postgresql + factory
│   ├── execution_handler/        # Execution + matching
│   │   ├── execution_handler.py, matching_engine.py, result_objects.py, base.py
│   │   ├── exchanges/                   # base.py, simulated.py
│   │   ├── fee_model/                   # zero / percent / maker_taker
│   │   └── slippage_model/              # zero / fixed / linear
│   ├── portfolio_handler/        # Portfolio + sub-managers
│   │   ├── portfolio_handler.py, portfolio.py, base.py, validators.py
│   │   ├── cash/, position/, transaction/, metrics/   # one manager each
│   │   └── storage/                     # in_memory + factory
│   ├── strategy_handler/         # Strategies + sizing/risk
│   │   ├── strategies_handler.py, base.py, SMA_MACD_strategy.py, empty_strategy.py
│   │   ├── position_sizer/, risk_manager/
│   │   └── my_strategies/               # concrete strategies (trend/momentum/...)
│   ├── screeners_handler/        # Market screening (deferred subsystem)
│   │   └── screeners/                   # BestScreener, cointegrated_pairs, ...
│   ├── price_handler/            # Data engine
│   │   ├── ingestion.py
│   │   ├── store/                       # CsvPriceStore, SqlPriceStore + base
│   │   ├── feed/                        # BacktestBarFeed + base (bar-timing contract)
│   │   └── providers/                   # CCXT, OANDA, Binance stream
│   ├── universe/                 # membership.py (derive_membership)
│   ├── reporting/                # frames.py, metrics.py, plots.py
│   ├── config/                   # Pydantic config models (SystemConfig.default())
│   ├── core/                     # Shared cross-cutting types
│   │   ├── enums/ (event, order, execution, portfolio)
│   │   ├── exceptions/ (base, order, portfolio, data)
│   │   ├── clock.py, ids.py, money.py, bar.py, sizing.py
│   │   ├── constants.py, portfolio_read_model.py
│   └── outils/                   # id_generator.py, time_parser.py
├── tests/                        # unit/, integration/, golden/, conftest.py
├── scripts/                      # run_backtest.py, cross_validate.py, crossval/
├── settings/                     # YAML config (gitignored in prod) + domains/
├── data/                         # Golden CSV dataset (BTCUSD_1d_ohlcv_2018_2026.csv)
├── output/                       # Backtest artifacts (trades/equity/summary)
├── notebooks/                    # Exploratory notebooks
├── docs/                         # Documentation
├── pyproject.toml                # Deps, test config, package metadata
├── poetry.lock                   # Committed lockfile
├── Makefile                      # Developer commands (loads .env)
└── CLAUDE.md                     # Project instructions
```

## Directory Purposes

**`itrader/trading_system/`:**
- Purpose: Composition roots that wire the component graph around one `global_queue`, plus run loops.
- Key files: `backtest_trading_system.py`, `live_trading_system.py`, `trading_interface.py`, `simulation/time_generator.py`.

**`itrader/events_handler/`:**
- Purpose: Queue dispatch and the frozen event-fact dataclasses.
- Key files: `full_event_handler.py`; `events/base.py` (frozen `Event` base) and per-domain event modules.

**`itrader/<domain>_handler/`:**
- Purpose: One domain each (order, execution, portfolio, strategy, screeners, price). Thin `<Domain>Handler` interface + fat `<Domain>Manager` / sub-components.
- Pattern: handler receives `global_queue`, delegates logic, emits events.

**`itrader/core/`:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols. Depends on nothing inside `itrader`.

**`itrader/config/`:**
- Purpose: Pydantic config models; `SystemConfig.default()` is constructed directly (registry/provider getters removed).

**`itrader/reporting/`:**
- Purpose: Pure builders for run artifacts (`frames.py`) and derived metrics (`metrics.py`); plotting in `plots.py`.

**`tests/`:**
- Purpose: `unit/` mirrors source tree; `integration/` holds run-path/wiring tests; `golden/` holds the frozen numerical oracle (`trades.csv`, `equity.csv`, `summary.json`) and re-freeze records.

## Key File Locations

**Entry Points:**
- `itrader/trading_system/backtest_trading_system.py`: `TradingSystem.run()` — backtest.
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()` — live.
- `scripts/run_backtest.py`: reproducible oracle generator (`make backtest`).

**Configuration:**
- `itrader/__init__.py`: process singletons (`config`, `logger`, `idgen`).
- `itrader/config/system.py`: `SystemConfig`, `PerformanceSettings` (`rng_seed` default 42).
- `pyproject.toml`: deps + pytest config (`filterwarnings=["error"]`, strict markers).
- `settings/`: YAML overrides (gitignored in prod), defaults under `settings/domains/`.

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: dispatch registry.
- `itrader/order_handler/order_manager.py`: order business logic.
- `itrader/execution_handler/matching_engine.py`: resting-order matching.
- `itrader/price_handler/feed/bar_feed.py`: bar-timing contract.
- `itrader/portfolio_handler/portfolio.py`: per-portfolio state.

**Testing:**
- `tests/conftest.py`, `tests/unit/conftest.py`, `tests/integration/conftest.py`: fixtures.
- `tests/golden/`: frozen oracle + cross-validation docs.

## Naming Conventions

**Files:**
- `snake_case.py` throughout. Handlers: `<domain>_handler.py`. Managers: `<domain>_manager.py`. Storage: `<backend>_storage.py`. Tests mirror source: `test_<module>.py`.
- A few legacy strategy/screener files use other casing (`SMA_MACD_strategy.py`, `BestScreener.py`).

**Directories:**
- Domains: `<domain>_handler/`. Pluggable families get their own subdir (`fee_model/`, `slippage_model/`, `exchanges/`, `storage/`, `providers/`, `store/`, `feed/`).
- Portfolio sub-managers each get a subdir: `cash/`, `position/`, `transaction/`, `metrics/`.

**Classes:**
- `PascalCase`. Handlers `<Domain>Handler`; managers `<Domain>Manager`; abstract bases `Abstract<Name>`; config `<Domain>Config`; exceptions `<Specific><Category>Error`.

**Methods / attributes:**
- `snake_case`. Event callbacks `on_<event>()`; factories `new_<object>()`; booleans `is_<state>`; getters `get_<thing>()`; private `_<name>`.
- Queue attr: `global_queue` (or `events_queue`); logger: `self.logger`; config: `self.config`.

**Enums:**
- `PascalCase` names, `UPPER_CASE` members; string-to-enum maps `<domain>_<type>_map`.

## Where to Add New Code

**New event type:**
- Define dataclass under `itrader/events_handler/events/<domain>.py` (subclass frozen `Event`).
- Add member to `itrader/core/enums/event.py::EventType`.
- Add a branch to `EventHandler._routes` in `itrader/events_handler/full_event_handler.py`.

**New strategy:**
- Implementation: `itrader/strategy_handler/my_strategies/<category>/` (subclass `strategy_handler/base.py::Strategy`).
- Tests: `tests/unit/strategy/`.

**New exchange / fee / slippage model:**
- Exchange: `itrader/execution_handler/exchanges/<name>.py` implementing `exchanges/base.py::AbstractExchange`.
- Fee/slippage: `itrader/execution_handler/fee_model/<name>_fee_model.py` / `slippage_model/<name>_slippage_model.py`.

**New order-storage backend:**
- `itrader/order_handler/storage/<backend>_storage.py`; register in `storage_factory.py`.

**New price provider / store:**
- Provider: `itrader/price_handler/providers/<name>_provider.py` (base in `providers/base.py`).
- Store: `itrader/price_handler/store/<name>_store.py` (base in `store/base.py`).

**Shared types / utilities:**
- Cross-cutting enums/exceptions/ids: `itrader/core/`.
- Small helpers: `itrader/outils/`.
- Reporting metrics/frames: `itrader/reporting/`.

**Tests:**
- Unit tests mirror the source tree under `tests/unit/<domain>/`.
- Run-path / wiring tests under `tests/integration/`.
- Every pytest marker must be declared in `pyproject.toml` (`--strict-markers`).

## Special Directories

**`tests/golden/`:**
- Purpose: Frozen numerical oracle (`trades.csv`, `equity.csv`, `summary.json`) + re-freeze/cross-validation records.
- Generated: Yes (by `scripts/run_backtest.py`). Committed: Yes — changed only at named re-freeze points.

**`settings/`:**
- Purpose: YAML config + `domains/` defaults. Committed: production YAML is gitignored; `*.default.yaml` defaults are tracked.

**`output/`:**
- Purpose: Backtest artifact output target. Generated: Yes. Committed: typically gitignored.

**`data/`:**
- Purpose: Golden OHLCV dataset (`BTCUSD_1d_ohlcv_2018_2026.csv`). Committed: Yes.

**`htmlcov/`, `.mypy_cache/`, `.pytest_cache/`, `__pycache__/`:**
- Purpose: Generated tooling artifacts. Committed: No.

---

*Structure analysis: 2026-06-08*
