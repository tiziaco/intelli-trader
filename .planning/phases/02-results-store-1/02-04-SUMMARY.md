---
phase: 02-results-store-1
plan: 04
subsystem: database
tags: [results-store, persistence, sqlite, backtest, gate-01, uuidv7]

# Dependency graph
requires:
  - phase: 02-results-store-1 (02-01)
    provides: RunRecord / PortfolioRecord / RunMetrics frozen DTOs + METRIC_NAMES
  - phase: 02-results-store-1 (02-02)
    provides: curate_run_settings / curate_portfolio_params / build_run_metrics / build_aggregate_equity_curve / annual_periods serializers
  - phase: 02-results-store-1 (02-03)
    provides: SqlResultsStore(backend, *, strict_persist) concrete store
provides:
  - "TradingSystem.run(persist: bool = False) post-loop results dump (SQL-free hot loop)"
  - "results_store threaded SystemSpec -> compose_engine -> Engine (forwarded, never constructed at the seam)"
  - "IDGenerator.generate_run_id() -> uuid.UUID (runs PK + stable ORDER BY tiebreak)"
  - "RESULT-01 closed end-to-end on in-process SQLite; oracle stays byte-exact + SQL-import-inert (GATE-01)"
affects: [03-operational-sql-backends, 04-retention-live-write-through]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Post-loop persist hook: dump guarded by `if persist:` AFTER runner.run() — backtest backend has zero serialization on the hot path (D-01)"
    - "Store forwarded already-built through the composition seam; the factory selects backends, the seam never constructs one (D-02/D-14a)"
    - "SQL surface kept out of the backtest module import graph; persistence callers import SqlResultsStore on their path only (GATE-01 inertness)"

key-files:
  created:
    - tests/integration/test_results_persist.py
  modified:
    - itrader/trading_system/system_spec.py
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/outils/id_generator.py

key-decisions:
  - "results_store typed Any on SystemSpec / ResultsStore ABC on compose_engine+Engine — spec stays SQL-free, seam references the ABC only (no SqlResultsStore in the import graph)"
  - "D-03 guard raises ConfigurationError inside _persist_results when persist=True and engine.results_store is None"
  - "D-17 failure policy: write failures re-raise only when the store opts into strict_persist; otherwise logged-and-swallowed so a sweep keeps good in-memory runs"
  - "build_backtest_system reads spec.results_store via getattr to preserve the e2e ScenarioSpec duck-typing contract"

patterns-established:
  - "Post-loop dump assembles per-portfolio + aggregate RunMetrics via the 02-02 serializers, then writes runs+run_portfolios atomically and equity_curve/trade_log artifacts"
  - "run_id is a single-UUIDv7 idgen value (no DB autoincrement / second ID scheme)"

requirements-completed: [RESULT-01, RESULT-04]

# Metrics
duration: 30min
completed: 2026-06-29
---

# Phase 2 Plan 04: Engine Wiring + Post-Loop Persist Hook Summary

**`run(persist=True)` writes a complete RunRecord + equity/trade artifacts post-loop through an injected SqlResultsStore, while the default `persist=False` path keeps the SMA_MACD oracle byte-exact (134 / 46189.87730727451) and SQL-import-inert (RESULT-01 closed end-to-end).**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-29
- **Tasks:** 3
- **Files created/modified:** 1 created, 4 modified

## Accomplishments

- Threaded an optional `results_store` through `SystemSpec` → `compose_engine` → `Engine`, SQL-free (the spec uses `Any`; the seam references only the `ResultsStore` ABC).
- Added `TradingSystem.run(persist: bool = False)` with a POST-LOOP dump (`if persist:` after `runner.run()`): per-portfolio + aggregate `RunMetrics` via the 02-02 serializers, curated credential-free settings, atomic `runs` + `run_portfolios` write, and equity_curve/trade_log artifacts.
- Added `IDGenerator.generate_run_id()` (UUIDv7) as the `runs` primary key and stable `ORDER BY` tiebreak.
- Proved the default `persist=False` path is byte-exact and SQL-import-inert with a new integration test (in-process SQLite end-to-end, D-03 guard, oracle inertness, subprocess import-inertness).

## Task Commits

Each task was committed atomically:

1. **Task 1: Thread results_store through SystemSpec/compose_engine/Engine** - `ac9c5ff` (feat)
2. **Task 2: run(persist=) post-loop dump + build_backtest_system injection + generate_run_id** - `d84c22b` (feat)
3. **Task 3: persist integration test (end-to-end + oracle/import inertness)** - `639601e` (test)

**Deviation fix:** `6bee04d` (fix — getattr for ScenarioSpec duck-typing)

## Files Created/Modified

- `itrader/trading_system/system_spec.py` - Added defaulted `results_store: Any = None` field (SQL-free, kept last)
- `itrader/trading_system/compose.py` - Imported the `ResultsStore` ABC; added `results_store` to `Engine` + a `compose_engine` keyword param; forwarded into `Engine(...)`
- `itrader/trading_system/backtest_trading_system.py` - `run(persist=)` + `_persist_results` post-loop dump; `build_backtest_system` forwards `spec.results_store`
- `itrader/outils/id_generator.py` - Added `generate_run_id()` (UUIDv7)
- `tests/integration/test_results_persist.py` - End-to-end persist, D-03 guard, oracle byte-exactness under persist=False, subprocess SQL-import-inertness

## Decisions Made

- Kept the SQL surface (`SqlResultsStore`/`SqlBackend`/`SqlSettings`) out of the backtest module import graph entirely — the seam forwards an already-built store; persistence callers import the SQL surface on their own path. This makes GATE-01 inertness structural, not disciplined.
- The aggregate equity artifact is the `build_aggregate_equity_curve` Series reset to a `timestamp`+`total_equity` frame; round-trip value-equality is asserted through the store's own gzip/json codec.
- Per-portfolio metrics use the default annualization basis; the aggregate uses `annual_periods([timeframe aliases])` (D-14).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `spec.results_store` broke the e2e `ScenarioSpec` duck-typing**
- **Found during:** Task 2 verification (full e2e suite)
- **Issue:** `build_backtest_system` is duck-typed by the e2e harness, which passes its own `ScenarioSpec` (no `results_store` field). A hard `spec.results_store` read raised `AttributeError` on every e2e scenario.
- **Fix:** Read `getattr(spec, "results_store", None)` — absent → `None` → store-free / byte-exact, preserving the duck-typing contract noted in the plan's `<interfaces>`.
- **Files modified:** itrader/trading_system/backtest_trading_system.py
- **Verification:** `tests/e2e` 71→76 pass; `tests/integration` 37 pass; mypy --strict clean
- **Committed in:** 6bee04d

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for the e2e harness's documented duck-typing seam. No scope creep — the SystemSpec field is unchanged.

## Issues Encountered

- The worktree `.venv` was empty on spawn; ran `poetry install` once. All subsequent commands use `PYTHONPATH="$PWD" poetry run ...` per the worktree gate (make test aborts on a missing .env).

## Verification

- `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_results_persist.py tests/integration/test_backtest_oracle.py -q` → 7 passed
- Full `tests/integration` → 37 passed; `tests/e2e` → 76 passed; `tests/unit/results` → 29 passed
- `PYTHONPATH="$PWD" poetry run mypy --strict itrader` → Success, 178 files
- GATE-01: subprocess import of `itrader.trading_system.backtest_trading_system` pulls no SQLAlchemy; SMA_MACD oracle byte-exact (134 / 46189.87730727451) under `persist=False`

## Next Phase Readiness

- RESULT-01 is closed end-to-end on in-process SQLite. Phase 3 (operational SQL backends, testcontainers Postgres) can build on the same spine; the results store proves the composition seam before any live path touches it.
- No stubs; no threat flags (the curated settings credential-free path is owned + tested in 02-02; this plan only forwards the curated dict).

---
*Phase: 02-results-store-1*
*Completed: 2026-06-29*
