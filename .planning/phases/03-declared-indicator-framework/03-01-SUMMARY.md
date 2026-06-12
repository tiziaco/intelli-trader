---
phase: 03-declared-indicator-framework
plan: 01
subsystem: strategy_handler/indicators
tags: [indicators, primitives, byte-exact, IND-01]
requires:
  - "Phase 2 strategy authoring surface (base Strategy kwargs/init() seam) — consumed by Plan 02, not this plan"
provides:
  - "itrader.strategy_handler.indicators barrel: SMA/MACDHist/EMA/RSI typed adapters + IndicatorHandle + IndicatorAdapter Protocol"
  - "itrader.strategy_handler.primitives: crossover/crossunder/is_above/is_below free functions with D-02 semantics + scalar broadcast"
affects:
  - "Plan 02 (SMAMACDStrategy migration) imports these symbols; base.py auto-warmup derives from handle.min_period()"
tech-stack:
  added: []
  patterns:
    - "Singleton-instance typed-adapter catalog (RESEARCH Pattern 2 / core/sizing.py analog)"
    - "Folder-package indicator subsystem (fee_model/ analog) — amended D-05"
    - "Flat free-function primitives module (core/sizing.py analog)"
key-files:
  created:
    - itrader/strategy_handler/primitives.py
    - itrader/strategy_handler/indicators/__init__.py
    - itrader/strategy_handler/indicators/catalog.py
    - itrader/strategy_handler/indicators/handle.py
    - tests/unit/strategy/test_primitives.py
    - tests/unit/strategy/test_indicators.py
  modified: []
decisions:
  - "D-05 (amended): indicators/ is a folder package (catalog.py + handle.py + barrel); primitives.py stays a flat sibling"
  - "D-03: IndicatorHandle lives in indicators/handle.py (NOT base.py); one-directional base -> indicators, no cycle"
  - "D-08: min_period is first-valid only (SMA/EMA/RSI -> w; MACDHist -> slow+signal == 15); reference max == 100"
metrics:
  duration: ~15 min
  tasks: 2
  files: 6
  completed: 2026-06-12
---

# Phase 3 Plan 01: Declared-Indicator Framework (Catalog + Handle + Primitives) Summary

Built the standalone first-party `indicators/` package (typed SMA/MACDHist/EMA/RSI adapters + `IndicatorHandle` + `IndicatorAdapter` Protocol) and the flat `primitives.py` comparison module (crossover/crossunder/is_above/is_below with D-02 inclusive-on-current-bar semantics and scalar broadcast), with byte-exact `ta` compute paths (SMA sliced input, MACDHist full-window) and D-08 first-valid `min_period`. No run-path file touched — the byte-exact gate (oracle 134 trades / 46189.87730727451, e2e 58/58) holds.

## What Was Built

**Task 1 — `primitives.py` + tests (commit `c2b4e53`):**
- Four free functions modelled on `core/sizing.py`: `is_above`/`is_below` (inclusive `>=`/`<=` on current bar), `crossover`/`crossunder` (strict `<`/`>` on previous, inclusive on current).
- Module-private `_at(series_or_scalar, idx)` helper implements D-02 scalar broadcast (`crossover(macd_hist, 0)` reads `b[-1] == b[-2] == 0.0`).
- Byte-exact map of `SMA_MACD_strategy.py` lines 70/77/80 — NOT textbook-strict `>`.
- 22 tests: boundary cases, both crossover/crossunder branches, scalar broadcast, the macd-hist-vs-0 BUY/SELL trigger.

**Task 2 — `indicators/` package + tests (commit `7e51d22`):**
- `catalog.py`: four stateless singleton adapters (`_SMA()`/`_MACDHist()`/`_EMA()`/`_RSI()` exported as `SMA`/`MACDHist`/`EMA`/`RSI`) typed against an `IndicatorAdapter` Protocol.
  - `[BYTE-EXACT]` `_SMA.compute` slices `bars[start_dt:][input_col]`, `start_dt = now - timeframe*window`, `fillna=True` (Pitfall 1).
  - `[BYTE-EXACT]` `_MACDHist.compute` uses the full `bars[input_col]`, `fillna=False`, no slice.
  - `EMA`/`RSI` use `fillna=False` + `dropna()` (additive, oracle-dark, D-07).
  - D-08 `min_period`: SMA/EMA/RSI -> `window`; MACDHist -> `slow + signal` (==15); reference `max(50,100,15)==100`.
- `handle.py`: `IndicatorHandle` thin positional wrapper (`[-1]`/`[-2]` -> float via `.iloc`, `__len__==0` pre-repopulate, `repopulate` -> `adapter.compute`, `min_period()` delegates). Does NOT import `base.py` (one-directional, no cycle).
- `__init__.py`: barrel re-exporting all five symbols + the Protocol.
- 13 tests: min_period formulas (incl. max==100 anchor), EMA/RSI value-equality vs direct `ta`, SMA slice + MACDHist full-window equality, handle `__len__`/`[-1]`/`[-2]`/`min_period`/re-runnability.

## Verification

- `poetry run pytest tests/unit/strategy/test_primitives.py tests/unit/strategy/test_indicators.py` — 35 passed.
- `poetry run mypy itrader` — clean, 176 source files (the typed adapter singletons + Protocol + handle satisfy `--strict`).
- `poetry run pytest tests/integration` — 12 passed (byte-exact oracle untouched).
- `poetry run pytest tests/e2e -m e2e` — 58/58 (no leaf re-baselined).
- TAB indentation verified across all source + new test files (0 leading-4-space body lines).
- `indicators/handle.py` has no `base` import (only docstring text references it).
- No run-path file touched (no `base.py`, no strategy, no handler edits).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test stub used positional `[idx]` instead of pandas Series**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** The first draft of `test_primitives.py` backed the 1st arg with a RangeIndex `pd.Series`; `series[-1]` does a label lookup (KeyError), not a positional read — mismatching the `IndicatorHandle` contract the primitives target (`.iloc[idx]` positional).
- **Fix:** Replaced the test helper with a small list-backed `_Handle` stub whose `__getitem__` is positional (Python list semantics), mirroring the real handle's positional read. The plan explicitly permits "small list-backed stub objects or pandas Series."
- **Files modified:** tests/unit/strategy/test_primitives.py
- **Commit:** c2b4e53 (caught and fixed within the same task before commit)

Production `primitives.py` was unaffected — it is correct for the positional-`[idx]` (handle) contract; only the test harness's stub was corrected.

## Known Stubs

None. No placeholder values, empty returns, or unwired data sources. EMA/RSI are "oracle-dark" (no golden-run consumer) by design (D-07 additive) but are real, tested adapters — not stubs.

## Self-Check: PASSED

Files created (all confirmed present):
- itrader/strategy_handler/primitives.py — FOUND
- itrader/strategy_handler/indicators/__init__.py — FOUND
- itrader/strategy_handler/indicators/catalog.py — FOUND
- itrader/strategy_handler/indicators/handle.py — FOUND
- tests/unit/strategy/test_primitives.py — FOUND
- tests/unit/strategy/test_indicators.py — FOUND

Commits (confirmed in git log):
- c2b4e53 (Task 1 — primitives) — FOUND
- 7e51d22 (Task 2 — indicators package) — FOUND
