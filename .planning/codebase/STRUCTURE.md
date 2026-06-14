# Codebase Structure

**Analysis Date:** 2026-06-14

## Directory Layout

```
intelli-trader/
├── itrader/                      # Application package (single source root)
│   ├── __init__.py               # Singleton bootstrap: config, logger, idgen
│   ├── config/                   # Pydantic config models + env settings (4-space)
│   ├── core/                     # Cross-cutting primitives; depends on nothing in itrader (4-space)
│   │   ├── enums/                # OrderType/OrderStatus/EventType/Side/... (barrel __init__)
│   │   └── exceptions/           # base/order/portfolio/data/strategy exceptions
│   ├── events_handler/           # The dispatcher + frozen event dataclasses
│   │   ├── full_event_handler.py # EventHandler.routes — the single dispatch table
│   │   └── events/               # base/market/signal/order/fill/error (4-space)
│   ├── trading_system/           # Composition roots + run drivers (TABS)
│   │   ├── compose.py            # compose_engine() shared wiring seam + Engine holder
│   │   ├── backtest_trading_system.py  # BacktestTradingSystem holder + build_backtest_system factory
│   │   ├── backtest_runner.py    # BacktestRunner sync fail-fast for-loop
│   │   ├── system_spec.py        # SystemSpec / PortfolioSpec / Action value objects
│   │   ├── live_trading_system.py
│   │   ├── trading_interface.py  # web/API bridge to the live system
│   │   └── simulation/           # TimeGenerator (TimeEvent grid)
│   ├── strategy_handler/         # StrategiesHandler + strategies (TABS)
│   │   ├── strategies/           # SMA_MACD_strategy.py (reference), empty_strategy.py
│   │   ├── my_strategies/        # user strategies (deferred mypy override)
│   │   ├── indicators/           # indicator catalog + handle
│   │   └── storage/              # SignalStore backends + factory
│   ├── order_handler/            # Facade → coordinator → 4 collaborators (TABS)
│   │   ├── order_handler.py      # OrderHandler facade (on_signal/on_fill)
│   │   ├── order_manager.py      # OrderManager coordinator (owns storage)
│   │   ├── admission/            # AdmissionManager (signal→order gates + sizing)
│   │   ├── brackets/             # BracketManager + BracketBook + levels
│   │   ├── lifecycle/            # LifecycleManager (modify/cancel)
│   │   ├── reconcile/            # ReconcileManager (fill mirror reconcile)
│   │   ├── order.py, order_validator.py, sizing_resolver.py
│   │   └── storage/              # in_memory / postgresql + storage_factory
│   ├── execution_handler/        # ExecutionHandler + matching + exchanges (TABS)
│   │   ├── matching_engine.py    # pure resting-order book
│   │   ├── exchanges/            # base.py + simulated.py
│   │   ├── fee_model/            # zero / percent / maker_taker
│   │   └── slippage_model/       # zero / fixed / linear
│   ├── portfolio_handler/        # PortfolioHandler + Portfolio (TABS)
│   │   ├── cash/  position/  transaction/  metrics/   # per-concern managers
│   │   └── storage/
│   ├── price_handler/            # Data engine
│   │   ├── store/                # CsvPriceStore, SqlHandler (read-only on run path)
│   │   ├── feed/                 # BacktestBarFeed — bar-timing contract (4-space)
│   │   └── providers/            # CCXT / OANDA / Binance stream
│   ├── screeners_handler/        # Dynamic screening (deferred subsystem)
│   ├── universe/                 # membership.py (derive_membership)
│   ├── reporting/                # frames/metrics/summary/plots/orders/cash_operations
│   └── outils/                   # id_generator, time_parser helpers
├── tests/                        # Test root (NOT test/) — type-grouped
│   ├── unit/<domain>/            # auto-marked `unit`
│   ├── integration/              # auto-marked `integration`
│   ├── e2e/<group>/<case>/golden/  # scenario specs + frozen golden artifacts
│   └── golden/                   # cross-validation oracles + CROSS-VALIDATION.md
├── scripts/                      # run_backtest.py (oracle generator), cross_validate*.py
├── settings/                     # YAML overrides; *.default.yaml tracked, prod gitignored
├── data/                         # Golden CSV (BTCUSD_1d_ohlcv_2018_2026.csv)
├── docs/  notebooks/  output/    # docs, exploratory notebooks, run artifacts
├── pyproject.toml                # deps + pytest + mypy config (single source)
├── Makefile                      # all developer commands; includes .env
└── poetry.lock                   # committed lockfile
```

## Directory Purposes

**`itrader/trading_system/`:**
- Purpose: Composition roots and run drivers.
- Contains: shared wiring seam, backtest holder+factory+runner, declarative spec, live system, web bridge, time generator.
- Key files: `compose.py`, `backtest_trading_system.py`, `backtest_runner.py`, `system_spec.py`, `live_trading_system.py`.

**`itrader/order_handler/`:**
- Purpose: Order management — facade → coordinator → four single-responsibility collaborators.
- Contains: `OrderHandler` (facade), `OrderManager` (coordinator owning storage), `admission/`, `brackets/`, `lifecycle/`, `reconcile/`, plus `order.py`, validator, sizing resolver, storage backends.
- Key files: `order_handler.py`, `order_manager.py`, `admission/admission_manager.py`, `reconcile/reconcile_manager.py`.

**`itrader/execution_handler/`:**
- Purpose: Turn `OrderEvent`/`BarEvent` into `FillEvent`s via a pluggable exchange + matching engine.
- Contains: `ExecutionHandler`, `MatchingEngine`, `exchanges/` (`base`, `simulated`), `fee_model/`, `slippage_model/`.
- Key files: `execution_handler.py`, `matching_engine.py`, `exchanges/simulated.py`.

**`itrader/portfolio_handler/`:**
- Purpose: Portfolio lifecycle and per-portfolio state.
- Contains: `PortfolioHandler` (satisfies `PortfolioReadModel`), `Portfolio`, and per-concern subdirs `cash/`, `position/`, `transaction/`, `metrics/`.
- Key files: `portfolio_handler.py`, `portfolio.py`.

**`itrader/price_handler/`:**
- Purpose: Look-ahead-safe data engine.
- Contains: `store/` (CSV/SQL), `feed/` (`BacktestBarFeed`, the bar-timing contract), `providers/` (CCXT/OANDA/Binance), `ingestion.py`.
- Key files: `feed/bar_feed.py`, `store/csv_store.py`.

**`itrader/core/`:**
- Purpose: Cross-cutting primitives that depend on nothing else inside `itrader`.
- Contains: `enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `portfolio_read_model.py`, `commission_estimator.py`, `constants.py`.

**`tests/`:**
- Purpose: Test root (NOT `test/`). `conftest.py` auto-applies the type marker from the folder.
- Contains: `unit/<domain>/`, `integration/`, `e2e/<group>/<case>/golden/`, `golden/` (cross-validation oracles).

## Key File Locations

**Entry Points:**
- `scripts/run_backtest.py`: Pinned oracle generator (`make backtest`).
- `itrader/trading_system/backtest_trading_system.py`: `BacktestTradingSystem.run()` / `build_backtest_system(spec)`.
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()`.
- `itrader/trading_system/trading_interface.py`: external/web order API bridge.

**Configuration:**
- `pyproject.toml`: deps, pytest (`filterwarnings=["error"]`, `--strict-markers`), mypy (`strict`, `files=["itrader"]`).
- `itrader/config/system.py`: `SystemConfig.default()`.
- `itrader/__init__.py`: singleton bootstrap (`config`, `logger`, `idgen`).
- `settings/domains/*.default.yaml`: tracked YAML defaults.
- `Makefile`: developer commands; `.env` included at top.

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: the single dispatch table (`EventHandler.routes`).
- `itrader/trading_system/compose.py`: the shared wiring seam (`compose_engine`).
- `itrader/trading_system/backtest_runner.py`: the per-tick run loop.
- `itrader/execution_handler/matching_engine.py`: resting-order matching.

**Testing:**
- `tests/conftest.py`: folder-derived marker application.
- `tests/golden/CROSS-VALIDATION.md`: cross-validation reference.
- `tests/e2e/<group>/<case>/golden/`: per-scenario frozen artifacts.

## Naming Conventions

**Files:**
- `snake_case.py` throughout.
- Handlers: `<domain>_handler.py` (`order_handler.py`).
- Managers: `<domain>_manager.py` (`admission_manager.py`, `reconcile_manager.py`).
- Abstract bases: `base.py` inside each domain package.
- Storage backends: `<backend>_storage.py` + `storage_factory.py`.
- Tests mirror source: `test_<module>.py`.

**Directories:**
- `<domain>_handler/` for top-level domains.
- Sub-concern subdirs are bare nouns/verbs (`admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `cash/`, `position/`).
- E2E scenarios: `tests/e2e/<group>/<case>/` each with a `golden/` artifact dir.

## Where to Add New Code

**New event type:**
- Dataclass: `itrader/events_handler/events/<domain>.py` (frozen, `slots=True`, `kw_only=True`).
- Enum member: `itrader/core/enums/event.py::EventType`.
- Route: add to `EventHandler.routes` in `itrader/events_handler/full_event_handler.py`.

**New strategy:**
- Reference/shared: `itrader/strategy_handler/strategies/`.
- User-supplied: `itrader/strategy_handler/my_strategies/<category>/`.
- Subclass `itrader/strategy_handler/base.py`; emit `SignalEvent`.

**New exchange / fee / slippage model:**
- Exchange: `itrader/execution_handler/exchanges/` (subclass `base.py::AbstractExchange`).
- Fee: `itrader/execution_handler/fee_model/`; Slippage: `itrader/execution_handler/slippage_model/`.

**New order-handling logic:**
- Pick the collaborator: admission gates → `order_handler/admission/`, bracket assembly → `brackets/`, modify/cancel → `lifecycle/`, fill reconcile → `reconcile/`. Wire it through `OrderManager` (no queue access in collaborators).

**New config domain:**
- Pydantic model under `itrader/config/`; tracked default under `settings/domains/<domain>.default.yaml`.

**New storage backend:**
- Order mirror: `itrader/order_handler/storage/` + register in `storage_factory.py`.
- Signals: `itrader/strategy_handler/storage/`.

**Utilities:**
- Cross-cutting, itrader-dependency-free: `itrader/core/`.
- Helper utilities (ids, time parsing): `itrader/outils/`.

**Tests:**
- Unit: `tests/unit/<domain>/test_<module>.py`.
- Integration: `tests/integration/`.
- E2E scenario: `tests/e2e/<group>/<case>/` with a `golden/` dir.

## Special Directories

**`tests/.../golden/` and `tests/golden/`:**
- Purpose: Frozen golden-master artifacts and cross-validation oracles.
- Generated: Yes (by `scripts/run_backtest.py` / e2e harness at named re-freeze points).
- Committed: Yes.

**`settings/`:**
- Purpose: YAML config overrides.
- Generated: No; `*.default.yaml` are authored defaults.
- Committed: `*.default.yaml` tracked; prod overrides gitignored. (`settings/backups/` holds dated portfolio backups.)

**`output/`:**
- Purpose: Run artifacts (`trades.csv`, `equity.csv`, `summary.json`).
- Generated: Yes.
- Committed: No (transient run output).

**`.venv/`:**
- Purpose: In-project Poetry virtualenv.
- Generated: Yes. Committed: No.

---

*Structure analysis: 2026-06-14*
