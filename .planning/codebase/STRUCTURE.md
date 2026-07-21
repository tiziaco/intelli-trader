# Codebase Structure

**Analysis Date:** 2026-07-21

## Directory Layout

```
intelli-trader/
├── itrader/                       # Application package
│   ├── config/                    # Pydantic config models (ITraderConfig root + domain sub-models)
│   ├── connectors/                # Live venue connectors (LiveConnector Protocol, OkxConnector)
│   ├── core/                      # Dependency-free primitives: enums/, exceptions/, ids, money, clock, sizing
│   ├── events_handler/            # Event bus, event definitions, dispatcher, error policy/handler
│   │   └── events/                # Frozen event structs, split by domain
│   ├── execution_handler/         # Order execution: exchanges/, fee_model/, slippage_model/, matching engine
│   ├── order_handler/             # Order lifecycle: admission/, brackets/, lifecycle/, reconcile/, storage/
│   ├── outils/                    # Small shared utility functions (dict_merge, time_parser, id_generator)
│   ├── portfolio_handler/         # Portfolio state: cash/, position/, transaction/, metrics/, account/, reconcile/, storage/
│   ├── price_handler/             # Data engine: store/, feed/, providers/
│   ├── reporting/                 # Pure report builders (frames.py, metrics.py, plots.py)
│   ├── results/                   # Run-results persistence and serialization
│   ├── screeners_handler/         # Dynamic market screening (deferred subsystem)
│   ├── storage/                   # Shared SQL spine (SqlEngine, halt/venue/system stores; Alembic chain at repo-root migrations/)
│   ├── strategy_handler/          # Strategies: registry/, lifecycle/, indicators/, storage/, strategies/, my_strategies/
│   ├── trading_system/            # Composition roots + run loops: compose.py, backtest_*.py, live_*.py, safety/, simulation/
│   ├── universe/                  # Dynamic universe membership (live-only)
│   ├── venues/                    # Live venue assembly/registry/lifecycle
│   └── __init__.py                # Process-wide singletons: config, logger, idgen
├── tests/                         # pytest root (NOT `test/`)
│   ├── unit/<domain>/              # Unit tests, mirrors itrader/<domain>/ structure
│   ├── integration/                # Integration tests (incl. test_okx_inertness.py, test_backtest_oracle.py)
│   ├── e2e/                        # End-to-end tests
│   ├── golden/                     # Golden-master artifacts (not a test dir — 0 tests collected)
│   └── support/                    # Shared test fixtures/helpers
├── migrations/                    # Alembic migration chain (versions/)
├── scripts/                       # Dev/ops scripts (run_backtest.py, crossval/)
├── settings/                      # YAML domain config; domains/*.default.yaml tracked, backups/ gitignored
├── data/                          # Golden OHLCV CSVs (raw/)
├── perf/                          # Performance benchmark harness (runners/, workloads/, strategies/, tools/, results/)
├── notebooks/                     # Jupyter notebooks
├── docs/                          # Hand-maintained docs (order_handler/, portfolio_handler/, superpowers/, tests/)
├── .planning/                     # GSD planning artifacts (codebase/, phases/, milestones/, ...)
├── output/                        # Generated run output (gitignored)
├── pyproject.toml                 # Dependencies, pytest config, mypy config
└── Makefile                       # All developer commands
```

## Directory Purposes

**`itrader/trading_system/`:**
- Purpose: Composition roots and run loops for both backtest and live modes.
- Contains: `compose.py` (shared mode-agnostic wiring seam), `engine_context.py` (post-compose context object), `backtest_trading_system.py`/`backtest_runner.py` (backtest composition root + fail-fast loop), `live_trading_system.py` (live facade + `build_live_system` factory), `live_runner.py` (owns the live drain loop), `session_initializer.py` (builds live collaborators), `route_registrar.py` (`LiveRouteRegistrar` — the single live route table), `worker_supervisor.py`, `config_router.py` (`ConfigRouter`, runtime config actuation), `alert_sink.py`, `system_spec.py`/`venue_spec.py` (typed spec objects), `universe_wiring.py`, `simulation/time_generator.py`, `safety/` (`safety_controller.py`, `stream_recovery_handler.py`, `pre_trade_throttle.py`).
- Key files: `itrader/trading_system/compose.py`, `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/route_registrar.py`.

**`itrader/events_handler/`:**
- Purpose: The event bus, event type definitions, dispatcher, and error handling for the queue.
- Contains: `bus.py` (`EventBus`/`PriorityEventBus`), `full_event_handler.py` (`EventHandler`, the single dispatch-order literal), `error_handler.py` (`ErrorHandler`, the ERROR-route consumer), `error_policy.py` (`FailFastPolicy`/`ErrorPolicy`), `events/` (per-domain event definitions).
- Key files: `itrader/events_handler/full_event_handler.py`, `itrader/events_handler/events/base.py`.

**`itrader/strategy_handler/`:**
- Purpose: Strategy execution, lifecycle, and registry.
- Contains: `strategies_handler.py` (`StrategiesHandler`), `base.py`/`pair_base.py` (Strategy ABCs), `lifecycle/manager.py` (`StrategyLifecycleManager` — owns the STRATEGY_COMMAND control plane), `registry/` (`catalog.py` — the injected strategy-type allowlist, `config_codec.py`, `rehydrate.py`), `managed_strategies.py` (instance roster), `signal_record.py`, `indicators/`, `storage/` (signal + registry storage backends), `strategies/` (built-in strategies incl. `SMA_MACD_strategy.py`), `my_strategies/` (user-supplied strategies + custom indicators/filters).
- Key files: `itrader/strategy_handler/strategies_handler.py`, `itrader/strategy_handler/lifecycle/manager.py`, `itrader/strategy_handler/registry/catalog.py`, `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`.

**`itrader/order_handler/`:**
- Purpose: Order lifecycle management (not matching — see `execution_handler/`).
- Contains: `order_handler.py` (thin interface), `order_manager.py` (business logic), `admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `storage/` (`OrderStorageFactory`, `in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`), `order_validator.py`, `sizing_resolver.py`.
- Key files: `itrader/order_handler/order_handler.py`, `itrader/order_handler/order_manager.py`.

**`itrader/execution_handler/`:**
- Purpose: Route orders to exchanges and drive resting-order matching.
- Contains: `execution_handler.py`, `matching_engine.py` (pure resting-order book), `exchanges/` (`base.py`, `simulated.py`, `okx.py`), `fee_model/` (`zero`/`percent`/`maker_taker`), `slippage_model/` (`zero`/`fixed`/`linear`), `result_objects.py`.
- Key files: `itrader/execution_handler/execution_handler.py`, `itrader/execution_handler/matching_engine.py`, `itrader/execution_handler/exchanges/simulated.py`.

**`itrader/portfolio_handler/`:**
- Purpose: Portfolio lifecycle and state.
- Contains: `portfolio_handler.py`, `portfolio.py`, `cash/`, `position/`, `transaction/`, `metrics/`, `account/` (`SimulatedCashAccount`/`SimulatedMarginAccount`/`VenueAccount`), `reconcile/` (`venue_reconciler.py`, `drift.py`), `storage/`, `validators.py`.
- Key files: `itrader/portfolio_handler/portfolio_handler.py`, `itrader/portfolio_handler/portfolio.py`.

**`itrader/price_handler/`:**
- Purpose: Look-ahead-safe price storage and bar feeds.
- Contains: `store/` (`csv_store.py`, `sql_store.py`), `feed/` (`bar_feed.py` — bar-timing contract, `live_bar_feed.py`), `providers/` (`ccxt_provider.py`, `oanda_provider.py`, `binance_stream.py`, `okx_provider.py`, `replay_provider.py`).
- Key files: `itrader/price_handler/feed/bar_feed.py`.

**`itrader/core/`:**
- Purpose: Cross-cutting primitives with zero internal dependencies.
- Contains: `enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `instrument.py`, `commission_estimator.py`, `portfolio_read_model.py`, `constants.py`, `policy_codec.py`.
- Key files: `itrader/core/money.py`, `itrader/core/enums/__init__.py`.

**`itrader/config/`:**
- Purpose: Pydantic-modelled configuration.
- Contains: `itrader_config.py` (`ITraderConfig` frozen root), `system.py`, `universe.py`, `stream.py`, `safety.py`, `order.py`, `portfolio.py`, `exchange.py`, `log.py`, `sql.py` (lazy, `SqlSettings`), `okx_settings.py`.
- Key files: `itrader/config/itrader_config.py`.

**`itrader/storage/`:**
- Purpose: Shared SQL spine used across live subsystems.
- Contains: `engine.py` (`SqlEngine`), `types.py`, `halt_record_store.py`, `venue_store.py`, `system_store.py`, `system_stats_store.py`, `strategy_registry_store.py`.

**`itrader/universe/`, `itrader/connectors/`, `itrader/venues/`:**
- Purpose: Live-only subsystems — dynamic universe polling/membership, venue connector protocol + OKX implementation, venue assembly/registry/lifecycle.
- Contains: `universe/universe_handler.py`, `universe/membership.py`; `connectors/base.py`, `connectors/okx.py`; `venues/assemble.py`, `venues/lifecycle.py`, `venues/registry.py`, `venues/okx_plugin.py`, `venues/paper_plugin.py`.

**`itrader/reporting/`, `itrader/results/`:**
- Purpose: Pure report-building (`reporting/frames.py`, `metrics.py`, `plots.py`) and run-results persistence (`results/models.py`, `sql_storage.py`, `serializers.py`).

**`tests/`:**
- Purpose: All test code, type-grouped.
- Contains: `unit/<domain>/` (mirrors `itrader/<domain>/`), `integration/`, `e2e/`, `golden/` (artifacts only, not tests), `support/` (fixtures/helpers).
- Note: `tests/unit/<domain>/` directories must stay package-less (no `__init__.py`) — a stray `__init__.py` colliding with `tests/integration/<domain>/` breaks full-suite collection while isolated runs still pass.

## Key File Locations

**Entry Points:**
- `itrader/trading_system/backtest_trading_system.py`: Backtest composition root (`TradingSystem.run()`)
- `itrader/trading_system/live_trading_system.py`: Live composition root (`LiveTradingSystem`, `build_live_system`)
- `scripts/run_backtest.py`: CLI entry point (`make backtest`)

**Configuration:**
- `itrader/config/itrader_config.py`: `ITraderConfig` frozen root
- `settings/domains/*.default.yaml`: Tracked default overrides
- `pyproject.toml`: Dependencies, pytest, mypy config
- `Makefile`: Developer commands

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: The single dispatch-order literal (`EventHandler.routes`)
- `itrader/trading_system/compose.py`: Shared component-graph wiring seam
- `itrader/execution_handler/matching_engine.py`: Order matching

**Testing:**
- `tests/integration/test_backtest_oracle.py`: SMA_MACD byte-exact golden-master oracle test
- `tests/integration/test_okx_inertness.py`: Proves the backtest import path is async/ccxt/SQL-free
- `tests/support/`: Shared fixtures

## Naming Conventions

**Files:**
- `snake_case.py` throughout, no exceptions.
- Handler modules: `<domain>_handler.py` (e.g. `order_handler.py`).
- Manager modules: `<domain>_manager.py` (e.g. `order_manager.py`, `cash_manager.py`).
- Abstract base modules: `base.py` inside each domain package.
- Test files: `test_<module>.py`, mirroring the source module name.

**Directories:**
- Domain package: `<domain>_handler/` (e.g. `order_handler/`, `portfolio_handler/`).
- Since v1.7/v1.8, large handlers are decomposed into collaborator subdirs named by RESPONSIBILITY, not by class: `admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `storage/`, `cash/`, `position/`, `transaction/`, `metrics/`, `account/`, `registry/`, `indicators/`.

## Where to Add New Code

**New event type:**
- Define the frozen struct in `itrader/events_handler/events/<domain>.py` (subclass `Event`, `msgspec.Struct`), add the `EventType` member in `itrader/core/enums/` (event enum module), and add an explicit key to `EventHandler.routes` in `itrader/events_handler/full_event_handler.py` (use `[]` if there is genuinely no consumer yet — never omit the key).

**New backtest strategy:**
- Reference implementation lives in `itrader/strategy_handler/strategies/`; user/experimental strategies go in `itrader/strategy_handler/my_strategies/<category>/`. Register the strategy TYPE in the injected `StrategyCatalog` allowlist (`itrader/strategy_handler/registry/catalog.py`) rather than importing it ad hoc — `itrader` never resolves a strategy class by an untrusted string outside that allowlist.
- Tests: `tests/unit/strategy/`.

**New exchange / execution backend:**
- Implement the `AbstractExchange` interface under `itrader/execution_handler/exchanges/`.
- Fee/slippage variants go in `itrader/execution_handler/fee_model/` / `itrader/execution_handler/slippage_model/`.
- Tests: `tests/unit/execution/`.

**New order-storage backend:**
- Implement alongside `itrader/order_handler/storage/in_memory_storage.py`, register in `OrderStorageFactory`.

**New live route / control-plane consumer:**
- Add the route entry inside `LiveRouteRegistrar.install()` (`itrader/trading_system/route_registrar.py`) — this is the ONLY place live routes are set/appended; do not mutate `EventHandler.routes` elsewhere.

**Utilities:**
- Small shared helpers go in `itrader/outils/` (e.g. `dict_merge.py`, `time_parser.py`).
- Cross-domain, dependency-free primitives go in `itrader/core/` — never add a dependency on any other `itrader` subpackage there.

## Special Directories

**`itrader/__pycache__/`, `**/__pycache__/`:**
- Purpose: Compiled bytecode cache.
- Generated: Yes. Committed: No.

**`.mypy_cache/`, `.pytest_cache/`:**
- Purpose: Tool caches.
- Generated: Yes. Committed: No.

**`output/`:**
- Purpose: Generated backtest run output (equity curves, trade logs).
- Generated: Yes. Committed: No.

**`htmlcov/`:**
- Purpose: `make test-cov` HTML coverage report.
- Generated: Yes. Committed: No.

**`settings/backups/`:**
- Purpose: Runtime config backups.
- Generated: Yes. Committed: No (gitignored in prod).

**`tests/golden/`:**
- Purpose: Golden-master reference artifacts (CROSS-VALIDATION.md etc.) — not a test suite; 0 tests collected here. The actual oracle test lives in `tests/integration/test_backtest_oracle.py`.
- Generated: Partially. Committed: Yes.

**`migrations/versions/`:**
- Purpose: Alembic migration chain for the SQL spine.
- Generated: Semi (via `alembic revision`). Committed: Yes.

---

*Structure analysis: 2026-07-21*
