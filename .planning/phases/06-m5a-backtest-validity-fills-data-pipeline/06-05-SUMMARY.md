---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 05
subsystem: data-pipeline
tags: [store-feed-wiring, price-handler-deletion, look-ahead, hot-loop-perf, inert-refactor]
requires:
  - "06-01: itrader/core/bar.py immutable Decimal Bar (BarEvent payload)"
  - "06-02: itrader/price_handler/store/ (PriceStore ABC + CsvPriceStore)"
  - "06-03: itrader/price_handler/feed/ (BarFeed ABC + BacktestBarFeed)"
provides:
  - "Composition roots (backtest + live) wired on CsvPriceStore + BacktestBarFeed (D-18)"
  - "StrategiesHandler push-based windows via feed.window(asof=event.time) (D-20)"
  - "DynamicUniverse BarEvent payload via feed.current_bars (D-15)"
  - "PriceHandler/data_provider/base.py/data_outils.py deleted; package re-exports the seams"
affects:
  - "06-06: fill-timing flip is now the ONLY result-changing diff left in the phase"
tech-stack:
  added: []
  patterns:
    - "Construction-time read-model injection (Feed passed to handlers like the legacy price_handler arg; queue-only rule governs handlers, the Feed is a read-model)"
    - "Resample-once-at-run-init: feed.precompute(strategy.tickers, strategy.timeframe) per registered strategy (M5-03)"
key-files:
  created: []
  modified:
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/universe/dynamic.py
    - itrader/screeners_handler/screeners_handler.py
    - itrader/reporting/statistics.py
    - itrader/price_handler/__init__.py
    - itrader/price_handler/providers/binance_stream.py
    - itrader/events_handler/full_event_handler.py
    - itrader/strategy_handler/base.py
  deleted:
    - itrader/price_handler/data_provider.py
    - itrader/price_handler/base.py
    - itrader/outils/data_outils.py
decisions:
  - "TradingSystem grows a `timeframe: str = '1d'` constructor param (golden default) to size the Feed's base_timeframe — the legacy set_timeframe derivation died with the price handler"
  - "Legacy symbol methods (set_symbols/_init_symbols/get_tradable_symbols) deleted with no passthrough remnant: after both rewires zero callers remained; the store knows its symbols (store.symbols()); 'all'-branch redesign stays M5b #33"
  - "outils/data_outils.py deleted whole-file (not just resample_ohlcv): the function was the module's only content and data_provider was its only importer"
  - "binance_stream.py mechanically repointed off the deleted base Protocol (class made standalone, class-attr refs -> self.*) — exactly as runtime-broken as before, D-live owns rebuilding it"
metrics:
  duration: ~9 min
  completed: 2026-06-06
  tasks: 2
  commits: 2
---

# Phase 6 Plan 05: Trading-System Rewiring on Store+Feed + PriceHandler Deletion Summary

Composition roots wired directly on CsvPriceStore + BacktestBarFeed and the legacy PriceHandler monolith deleted, closing the M5-05 split and M5-03 (zero hot-loop resample) with the oracle byte-exact — the whole structural group is proven inert, leaving 06-06 as the only result-changing diff in the phase.

## What was done

### Task 1: Wire Store+Feed into the systems and repoint all consumers (87de34b)

- **backtest_trading_system.py**: `CsvPriceStore(start_date=..., end_date=end_date or None)` (golden defaults; existing date args passed through) + `BacktestBarFeed(store, to_timedelta(timeframe))` replace the `PriceHandler` construction. New `timeframe: str = '1d'` constructor param. Run-init derives the ping clock from `store.index(store.symbols()[0])` (T-06-16: same tick grid) and calls `feed.precompute(strategy.tickers, strategy.timeframe)` per registered strategy so the hot loop never resamples (M5-03). `StatisticsReporting` takes the Store. The legacy `set_symbols`/`set_timeframe`/`load_data` init calls are gone.
- **strategies_handler.py**: `__init__(global_queue, feed)`; the loop shape is unchanged; the data line is `self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)` — asof comes ONLY from the event (D-20/T-06-18). Two-arg `calculate_signal(ticker, window)` contract kept (M5b owns the richer contract).
- **universe/dynamic.py**: `generate_bar_event` is now `bars = self.feed.current_bars(time_event.time)`; the 06-01 per-ticker `get_bar`/`Bar.from_row` bridge and the `.prices.keys()` membership scan (PERF4) are dead. Missing-ticker warning (strategies_universe tickers absent from the dict), `last_bar` caching, and queue-put shape kept. Constructor takes `feed: BarFeed`.
- **live_trading_system.py** (Pitfall 8, minimal conformance): mirrors the backtest Store+Feed wiring shape; `_initialize_live_session` drops the dead `set_symbols`/`set_timeframe` calls. D-live owns making live mode actually work.
- **statistics.py** (mypy-deferred, dormant): takes `store: PriceStore`; date/bar-count/index/bars accesses served by `store.index`/`store.symbols`/`store.read_bars`. `print_summary` stays dormant on the golden path.
- **screeners_handler.py** (D-screener dormant): takes the feed; both megaframe call sites repointed to `feed.megaframe(...)` (D-24 working API). No logic rework.

### Task 2: Delete PriceHandler + dead resample helper; final inert gate (614e1a5)

- Pre-deletion audit: zero remaining importers of `data_provider`/`PriceHandler`/`AbstractPriceHandler` (the only live import was the quarantined D-live `binance_stream.py`, mechanically repointed — see Deviations).
- `git rm itrader/price_handler/data_provider.py itrader/price_handler/base.py` (D-18).
- `git rm itrader/outils/data_outils.py`: `resample_ohlcv` (its `label='right'` was half the #21 look-ahead) had `data_provider` as its ONLY importer and was the module's only content — whole-file deletion instead of function-only.
- `price_handler/__init__.py` rewritten to re-export the seams (`PriceStore`, `CsvPriceStore`, `BarFeed`, `BacktestBarFeed`, `PriceProvider`) with `__all__`; quarantined modules (`sql_store`, provider adapters) NOT package-imported (T-06-17).
- `tests/integration/test_backtest_smoke.py` needed NO changes — it asserts run results, not PriceHandler-era wiring; no test in the tree imported `data_provider`.
- No pyproject mypy-override change (verified: deleted modules carried no override; statistics/live/binance_stream module paths unchanged).

## Verification evidence (final gates)

| Gate | Result |
|------|--------|
| `pytest tests/` (= make test) | 577 passed |
| `mypy itrader` --strict (= make typecheck) | Success: no issues in 139 source files |
| `pytest tests/integration/test_backtest_oracle.py` | 2 passed — **byte-exact** (whole-pipeline swap proven inert, D-21) |
| `scripts/run_backtest.py` (= make backtest) | end-to-end OK: output/trades.csv (134 trades), final_equity 53229.68512642489 == frozen golden |
| `grep -rn "PriceHandler" itrader/ scripts/` | 0 matches |
| resample_ohlcv importers | 0 (file deleted) |

All verification run with `PYTHONPATH` pinned to the worktree root against the shared main-checkout venv (worktree-environment equivalent of the make targets).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] binance_stream.py repointed off the deleted base Protocol**
- **Found during:** Task 2 (pre-deletion audit)
- **Issue:** Quarantined D-live `providers/binance_stream.py` was the one remaining importer (`from ..base import PriceHandler` — already broken: base.py exported `AbstractPriceHandler`, not `PriceHandler`) and would trip the strict-0 `PriceHandler` grep gate (6 matches).
- **Fix:** Mechanical rename only — class made standalone (base dropped), `PriceHandler.prices/symbols/timeframe` class-attr refs became `self.*` (matching the file's existing `self.symbols` usage). No redesign; exactly as runtime-broken as before; D-live owns rebuilding it on the new seams.
- **Files modified:** itrader/price_handler/providers/binance_stream.py
- **Commit:** 614e1a5

**2. [Rule 2 - Missing critical] Stale PriceHandler docstring mentions scrubbed**
- **Found during:** Task 2 (strict-0 grep gate)
- **Issue:** `full_event_handler.py` documented a `price_handler : PriceHandler` constructor param that does not exist; `strategy_handler/base.py` described signals as "generated from a PriceHandler (derived) object". Both tripped the acceptance grep and documented a deleted concept.
- **Fix:** Removed the phantom param doc; reworded the Strategy docstring to the feed push model (D-20).
- **Files modified:** itrader/events_handler/full_event_handler.py, itrader/strategy_handler/base.py
- **Commit:** 614e1a5

Everything else executed exactly as written. Historical `data_provider` lineage notes in store/feed docstrings were intentionally left (they are not importers; the audit criterion targets importers, the strict-0 criterion targets `PriceHandler`).

## Must-haves check

- "make backtest runs end-to-end wired on CsvPriceStore + BacktestBarFeed; PriceHandler no longer exists anywhere (D-18)" — DONE
- "Strategies receive their windows pushed from the Feed (D-20); no resample and no price_handler access on the hot loop (M5-03, PERF4)" — DONE (precompute at run-init; window is a pure searchsorted slice)
- "The run path is read-only and offline — no network/SqlHandler construction; missing data errors loudly (FR6/FR7)" — DONE (data_provider's module-level SqlHandler/CCXT imports deleted with it; quarantined modules not package-imported; store/feed accessors raise MissingPriceDataError)
- "Golden oracle reproduces byte-exact after the whole pipeline swap (inert per D-21)" — DONE

## Known Stubs

None introduced by this plan. Pre-existing dormant paths (unchanged status, documented owners): `StatisticsReporting.print_summary` (broken `_prepare_data`, D-reporting), `ingestion.ingest` raise-loudly stub (D-sql), `binance_stream.py` (D-live), screener wiring (D-screener).

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface. The plan *removed* network-capable code from the run path (T-06-17 mitigated: data_provider deleted, providers quarantined).

## Self-Check: PASSED

- itrader/price_handler/__init__.py exports verified; data_provider.py/base.py/data_outils.py confirmed deleted
- Commits 87de34b and 614e1a5 confirmed in git log
- Suite 577 green, typecheck clean, oracle byte-exact, backtest end-to-end at final HEAD
