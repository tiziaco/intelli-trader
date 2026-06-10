# Codebase Structure

**Analysis Date:** 2026-06-10

## Directory Layout

```
intelli-trader/
├── itrader/                  # Application package (event-driven trading framework)
│   ├── __init__.py          # Singleton init on import: config, logger, idgen
│   ├── logger.py            # structlog init + get_itrader_logger()
│   ├── config/              # Pydantic config system (SystemConfig.default())
│   ├── core/                # Shared primitives — depends on nothing in itrader
│   │   ├── enums/           # OrderType, OrderStatus, EventType, Side, ...
│   │   └── exceptions/      # ITraderError hierarchy by domain
│   ├── events_handler/      # Dispatcher + event dataclasses
│   │   └── events/          # Frozen event dataclasses (split by domain)
│   ├── trading_system/      # Composition roots + run loops
│   │   └── simulation/      # TimeGenerator (TimeEvent grid)
│   ├── strategy_handler/    # Strategies + sizing/risk; signal store
│   │   ├── strategies/      # SMA_MACD (reference), empty_strategy
│   │   ├── my_strategies/   # Concrete strategy library + indicators/filters
│   │   └── storage/         # Signal store backends
│   ├── order_handler/       # OrderHandler (thin) + OrderManager (logic)
│   │   └── storage/         # Order-mirror persistence (in_memory/postgresql)
│   ├── execution_handler/   # ExecutionHandler + matching + cost models
│   │   ├── exchanges/       # AbstractExchange + SimulatedExchange
│   │   ├── fee_model/       # zero / percent / maker_taker
│   │   └── slippage_model/  # zero / fixed / linear
│   ├── portfolio_handler/   # PortfolioHandler + Portfolio + 4 managers
│   │   ├── cash/            # CashManager
│   │   ├── position/        # PositionManager + Position
│   │   ├── transaction/     # TransactionManager + Transaction
│   │   ├── metrics/         # MetricsManager
│   │   └── storage/         # Portfolio state storage
│   ├── price_handler/       # Data engine
│   │   ├── store/           # CsvPriceStore, SqlPriceStore (read-only on run path)
│   │   ├── feed/            # BacktestBarFeed + bar-timing contract
│   │   └── providers/       # CCXT, OANDA, Binance stream
│   ├── screeners_handler/   # Dynamic market screening (deferred subsystem)
│   │   └── screeners/       # Concrete screeners
│   ├── universe/            # Membership derivation
│   ├── reporting/           # Pure run-artifact builders + metrics + plots
│   └── outils/              # IDGenerator, time_parser
├── scripts/                 # run_backtest.py (oracle), cross_validate.py, crossval/
├── tests/                   # pytest suite (unit / integration / e2e / golden)
│   ├── unit/                # Per-module tests, mirror source layout
│   ├── integration/         # Run-path wiring + oracle smoke
│   ├── e2e/                 # Scenario-based golden-master harness
│   └── golden/              # Frozen oracle artifacts + cross-validation docs
├── settings/                # YAML config overrides (defaults under domains/)
├── data/                    # Golden OHLCV CSVs (+ raw/)
├── docs/                    # Handler docs + planning notes
├── notebooks/               # Jupyter exploration
├── output/                  # Generated run artifacts (gitignored)
├── pyproject.toml           # Deps, pytest config, mypy config (single source)
├── Makefile                 # All developer commands
├── poetry.lock              # Committed lockfile
└── CLAUDE.md                # Project instructions
```

## Directory Purposes

**`itrader/core/`:**
- Purpose: Cross-cutting primitives; depends on nothing else inside `itrader`.
- Contains: enums, exceptions, money/ids/clock/bar/sizing primitives, read-model Protocol.
- Key files: `core/money.py`, `core/ids.py`, `core/clock.py`, `core/portfolio_read_model.py`, `core/sizing.py`, `core/enums/__init__.py`.

**`itrader/events_handler/`:**
- Purpose: The dispatcher and the event vocabulary.
- Contains: `full_event_handler.py` (the `EventHandler` + `_routes` literal) and the `events/` package.
- Key files: `events_handler/full_event_handler.py`, `events_handler/events/base.py`, `events/market.py`, `events/signal.py`, `events/order.py`, `events/fill.py`, `events/error.py`.

**`itrader/trading_system/`:**
- Purpose: Composition roots that wire the component graph and drive runs.
- Contains: `backtest_trading_system.py`, `live_trading_system.py`, `trading_interface.py`, `simulation/time_generator.py`.

**`itrader/<domain>_handler/`:**
- Purpose: One domain each; thin `<Domain>Handler` (queue interface) + fat `<Domain>Manager` (logic).
- Contains: handler, manager, validators, pluggable sub-models, `storage/` backends.

**`itrader/price_handler/`:**
- Purpose: Look-ahead-safe data access and `BarEvent` production.
- Key files: `price_handler/feed/bar_feed.py` (bar-timing contract), `price_handler/store/csv_store.py`, `price_handler/store/sql_store.py`.

**`itrader/reporting/`:**
- Purpose: Pure builders for run artifacts and derived metrics (no queue access).
- Key files: `reporting/frames.py`, `reporting/metrics.py`, `reporting/summary.py`, `reporting/plots.py`.

## Key File Locations

**Entry Points:**
- `scripts/run_backtest.py`: Reproducible oracle generator (`make backtest`).
- `itrader/trading_system/backtest_trading_system.py`: `TradingSystem.run()` (backtest composition root + loop).
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()` (live).
- `itrader/trading_system/trading_interface.py`: web/API order injection bridge.

**Configuration:**
- `pyproject.toml`: dependencies, pytest config (`filterwarnings=["error"]`, strict markers), mypy `--strict`.
- `itrader/config/system.py`: `SystemConfig.default()`.
- `itrader/config/settings.py`: `Settings(BaseSettings)`, env prefix `ITRADER_`.
- `settings/domains/*.default.yaml`: tracked default YAML overrides.
- `.env`: DB URLs and exchange credentials (present; never read contents).

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: dispatch registry `_routes`.
- `itrader/order_handler/order_manager.py`: order business logic.
- `itrader/execution_handler/matching_engine.py`: resting-order matching.
- `itrader/portfolio_handler/portfolio.py`: per-portfolio state + 4 managers.

**Testing:**
- `tests/unit/`: per-module unit tests (mirror source).
- `tests/integration/`: run-path wiring + oracle smoke.
- `tests/e2e/`: scenario-based golden-master harness (`scenario_spec.py`, `conftest.py`).
- `tests/golden/`: frozen oracle artifacts (`summary.json`, `trades.csv`, `equity.csv`) + cross-validation docs.

## Naming Conventions

**Files:**
- `snake_case.py` throughout — no exceptions.
- Handlers: `<domain>_handler.py` (`order_handler.py`, `execution_handler.py`).
- Managers: `<domain>_manager.py` (`order_manager.py`, `cash_manager.py`).
- Abstract bases: `base.py` inside each domain package.
- Storage backends: `<backend>_storage.py` (`in_memory_storage.py`, `postgresql_storage.py`).
- Cost models: `<kind>_<model>.py` (`zero_fee_model.py`, `linear_slippage_model.py`).
- Strategy classes use mixed-case filenames (`SMA_MACD_strategy.py`, `RSI_scalping_strategy.py`) under `strategies/` and `my_strategies/`.
- Tests mirror source: `test_<module>.py`.

**Directories:**
- `<domain>_handler/` for each handler domain.
- Sub-managers split into their own subdir: `cash/`, `position/`, `transaction/`, `metrics/`.
- E2E scenarios: one folder per scenario with `scenario.py`, `test_scenario.py`, `bars.csv`, `golden/`.

## Where to Add New Code

**New event type:**
- Dataclass: `itrader/events_handler/events/<domain>.py` (frozen, subclass `Event`).
- Enum member: `itrader/core/enums/event.py::EventType`.
- Route branch: `itrader/events_handler/full_event_handler.py::EventHandler._routes`.

**New strategy:**
- Reference-style strategy: `itrader/strategy_handler/strategies/`.
- Library/experimental strategy: `itrader/strategy_handler/my_strategies/<category>/`.
- Config: extend `itrader/strategy_handler/config.py`; register via `strategies_handler.add_strategy(...)`.

**New exchange / cost model:**
- Exchange: `itrader/execution_handler/exchanges/` (implement `exchanges/base.py`).
- Fee model: `itrader/execution_handler/fee_model/` (implement `fee_model/base.py`).
- Slippage model: `itrader/execution_handler/slippage_model/` (implement `slippage_model/base.py`).

**New order/portfolio storage backend:**
- Order: `itrader/order_handler/storage/<backend>_storage.py` + register in `storage_factory.py`.
- Portfolio: `itrader/portfolio_handler/storage/`.

**New reporting metric/frame:**
- Pure builders only: `itrader/reporting/metrics.py` or `itrader/reporting/frames.py` (no queue access).

**New tests:**
- Unit: `tests/unit/<domain>/test_<module>.py` (mirror source path).
- E2E scenario: new folder under `tests/e2e/<group>/<scenario>/` with `scenario.py`, `test_scenario.py`, `bars.csv`, `golden/`.

**Utilities:**
- Shared helpers: `itrader/outils/` (IDs, time parsing) or `itrader/core/` (primitives).

## Special Directories

**`output/`:**
- Purpose: Generated run artifacts (`trades.csv`, `equity.csv`, `summary.json`).
- Generated: Yes (by `scripts/run_backtest.py`).
- Committed: No (gitignored).

**`tests/golden/`:**
- Purpose: Frozen numerical oracle + cross-validation reference docs.
- Generated: Yes (re-frozen only at named D-11 re-freeze points).
- Committed: Yes.

**`settings/`:**
- Purpose: YAML config overrides. `*.default.yaml` (and `domains/*.default.yaml`) are tracked defaults; runtime overrides are gitignored in prod. `backups/` holds timestamped snapshots.
- Committed: defaults only.

**`data/`:**
- Purpose: Golden OHLCV CSVs (`BTCUSD_1d_ohlcv_2018_2026.csv` is the canonical golden dataset; `raw/` holds pre-normalized inputs).
- Committed: Yes.

**`htmlcov/`, `.mypy_cache/`, `.pytest_cache/`, `.venv/`:**
- Generated tooling caches/output; not source. `.venv/` is in-project (Poetry).

---

*Structure analysis: 2026-06-10*
