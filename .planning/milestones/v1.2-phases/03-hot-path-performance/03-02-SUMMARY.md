---
phase: 03-hot-path-performance
plan: 02
subsystem: price_handler/feed
tags: [perf, de-pandas, bar-feed, PERF-03, D-07, D-08, D-09]
requires:
  - "BacktestBarFeed.__init__ per-symbol loop (the _frames/_spans precompute)"
  - "Bar.from_row (core/bar.py) — UNCHANGED Decimal-string path"
provides:
  - "Prebuilt {ticker:{time:Bar}} map built once in __init__"
  - "current_bars() as a pure dict lookup (no per-tick searchsorted/iloc/Bar.from_row)"
affects:
  - "current_bars() readers: portfolio mark-to-market, matching_engine, strategies_handler (values bit-identical)"
tech-stack:
  added: []
  patterns:
    - "Eager batch-at-init materialization mirroring the already-blessed _spans precompute"
    - "Pure dict lookup replacing pandas iloc/searchsorted on the hot path"
key-files:
  created: []
  modified:
    - itrader/price_handler/feed/bar_feed.py
    - tests/unit/price/test_bar_feed.py
decisions:
  - "D-07: eager-materialize all Bars once at construction"
  - "D-08: lazy memoization REJECTED — each (ticker,time) hit exactly once, a cache serves zero hits"
  - "D-09: honest bounded gap-discovery delta — structural hot-loop de-pandas, bit-identical; front-loads conversions, does NOT reduce their count"
metrics:
  duration: ~10m
  completed: 2026-06-11
---

# Phase 3 Plan 02: BacktestBarFeed Eager Bar Prebuild Summary

Eager-materialized all `Bar`s once at `BacktestBarFeed` construction (a per-ticker
`{time: Bar}` map alongside `_frames`/`_spans`) and turned `current_bars(time)` into a
pure dict lookup — removing pandas `iloc`/`searchsorted` and per-tick `Bar` object churn
from the hot loop (D-07/D-08), locked by a GREEN no-call `Bar.from_row` sentinel (D-01).

## What Was Built

- **Prebuild seam (`__init__`):** inside the existing per-symbol loop that fills
  `_frames`/`_spans`, a new `self._prebuilt: dict[str, dict[datetime, Bar]]` is built over
  the SAME loaded frame via the UNCHANGED `Bar.from_row(ts, row)` for every `frame.iterrows()`
  row. This mirrors the already-blessed `_spans` precompute exactly (batch transform at init,
  not a per-tick cost). No new pandas resample/offset path was introduced (warning-clean —
  Pitfall 4 / `filterwarnings=["error"]`).
- **`current_bars(time)` → dict lookup:** rewritten from per-symbol
  `searchsorted` + `iloc` + `Bar.from_row` to `self._prebuilt[ticker].get(time)`. The
  exact-stamp existence semantics are preserved: the old `index[pos] == time` guard becomes
  `time in prebuilt[ticker]` (same existence-and-equality contract; sparse universe — absent,
  not None).
- **`window()` UNTOUCHED:** the visibility slice (the seven-rule look-ahead contract) was not
  edited — `git diff` shows no change to its signature or body.
- **No-call sentinel test (regression-LOCK, GREEN):**
  `test_current_bars_serves_prebuilt_no_from_row_per_tick` patches `Bar.from_row` (a
  classmethod, patched as `classmethod(_boom)`) to raise if called, then calls
  `duo_feed.current_bars(ts('2020-01-03'))` and asserts `isinstance(bars['BTCUSD'], Bar)`.
  It PASSES against the landed prebuild (zero per-tick `from_row` calls) — this is a
  regression-LOCK, not a test-first RED (TDD_MODE OFF).

## D-09 Bounded Gap-Discovery Delta (honest rationale)

The owner-flagged honest framing, recorded in the code comment AND here per the plan's
explicit instruction:

> The win is **"structural hot-loop de-pandas, bit-identical"** — it removes pandas
> `iloc`/`searchsorted` and per-tick `Bar` object churn from the hot loop and front-loads
> `Bar.from_row` to init. It does **NOT** "eliminate per-tick Decimal conversions": each
> `(ticker, time)` row is already converted exactly once across the run, so eager prebuild
> **front-loads** the same conversions to construction — it does not reduce their count.

This is NOT the overstated "computed once" framing. D-08: lazy memoization is REJECTED —
each `(ticker, time)` is queried exactly once, so a cache would serve zero hits.

## Verification

- `PYTHONPATH="$PWD" poetry run pytest tests/unit/price/test_bar_feed.py tests/unit/core/test_bar.py tests/unit/price/ -x` — **32 passed** (the new no-call sentinel + all 7 look-ahead rule tests + Decimal-fields + Bar value tests green).
- `PYTHONPATH="$PWD" poetry run mypy itrader` — **Success: no issues found in 139 source files** (strict-clean).
- `grep "Bar.from_row" bar_feed.py` confirms the actual call now lives only in the `__init__`
  prebuild loop (line 186); all other occurrences are comments/docstrings. `current_bars` makes
  zero `from_row` calls.
- `window()` body unchanged (diff confirms).
- Byte-exact golden oracle (134 trades / final_equity 46189.87730727451) is a PHASE-gate run
  at phase completion (Plan 04), not this plan — values here are bit-identical by construction
  (same `Bar.from_row`, same rows).

## Deviations from Plan

None - plan executed exactly as written.

## Commits

- `eb43587` perf(03-02): eager-materialize Bars; current_bars() dict lookup (D-07/08/09)

## Self-Check: PASSED

- FOUND: itrader/price_handler/feed/bar_feed.py
- FOUND: tests/unit/price/test_bar_feed.py
- FOUND: commit eb43587
