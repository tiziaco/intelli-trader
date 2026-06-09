---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 03
subsystem: price-pipeline
tags: [feed, look-ahead, resample, precompute, megaframe, bar-timing-contract]
requires:
  - phase: 06-m5a-backtest-validity-fills-data-pipeline
    plan: 01
    provides: "itrader/core/bar.py — immutable Decimal Bar value object (Bar.from_row)"
  - phase: 06-m5a-backtest-validity-fills-data-pipeline
    plan: 02
    provides: "itrader/price_handler/store/ — PriceStore ABC + CsvPriceStore (read_bars/symbols)"
provides:
  - "BarFeed ABC (current_bars/window/megaframe) — the M5-05 feed seam 06-05 wires against"
  - "BacktestBarFeed — precompute once per (ticker, timeframe), per-tick searchsorted slice under the completed-bars cutoff (M5-01/M5-03)"
  - "Bar-timing contract rules 1-7 as the bar_feed module docstring (D-24, single written home)"
  - "Fixed megaframe: keys == actually-included symbols, tz-aware index (D-19, FR8)"
  - "tests/unit/price/test_bar_feed.py — the phase's core look-ahead/precompute/megaframe regression locks"
affects: [06-05-rewiring, 06-04-matching, strategy_handler-push-path, screeners-megaframe]
tech-stack:
  added: []
  patterns:
    - "precompute-then-slice: resample(label='left', closed='left') once per (ticker, timeframe); per-tick window = searchsorted positional slice"
    - "feed-owned offset-alias map (minutes->'min', hours->'h', days/weeks->'{n}D') — month-end 'm' alias banned"
    - "pure read-model: no queue, no network, no store writes; logger bound at construction only"
key-files:
  created:
    - itrader/price_handler/feed/__init__.py
    - itrader/price_handler/feed/base.py
    - itrader/price_handler/feed/bar_feed.py
    - tests/unit/price/test_bar_feed.py
  modified: []
decisions:
  - "Visibility cutoff implemented as asof - timeframe + base_timeframe with searchsorted(side='right') — degenerates to asof when timeframe == base (D-02 both-branches-agree by construction)"
  - "Lazy compute-and-memoize for undeclared timeframes (RESEARCH Open Question 3) — same cache dict as precompute, serves screener/megaframe timeframes without hot-loop resample"
  - "Megaframe columns are per-symbol close Series (named by symbol) per plan spec — flat symbol-keyed columns, not 2-level OHLCV MultiIndex"
  - "current_bars uses searchsorted exact-stamp lookup (O(log n)) — absent ticker omitted from dict, never None (D-15 sparse contract)"
metrics:
  duration: 9 min
  tasks: 2
  files: 4
  completed: 2026-06-06
---

# Phase 6 Plan 03: Look-Ahead-Safe BarFeed Summary

**One-liner:** Look-ahead-safe BacktestBarFeed — resampled frames precomputed once per (ticker, timeframe) with label='left'/closed='left' and sliced per tick under the completed-bars cutoff B + TF <= T + tf_base, with the bar-timing contract (rules 1-7) transcribed as the module docstring and regression-locked by 12 unit tests.

## What Was Built

### Task 1 — Feed seam (commit b0e3611)

- `itrader/price_handler/feed/base.py`: `BarFeed` ABC with the exact interface block from the plan — `current_bars(time) -> dict[str, Bar]` (sparse, D-15), `window(ticker, timeframe, max_window, asof) -> pd.DataFrame` (float64, tz-aware, completed bars only, raises `MissingPriceDataError`), `megaframe(asof, timeframe, max_window)` (D-19).
- `itrader/price_handler/feed/bar_feed.py`: `BacktestBarFeed(store, base_timeframe)`:
  - Module docstring IS the bar-timing contract — rules 1-7 transcribed in substance (open-time stamping D-04; tick-T-means-bar-T-closed; visibility `<= T`; resampled bucket visible iff `B + TF <= T + tf_base`; next-open fills D-01; close-marked equity D-05; last-bar orders never fill), plus the "replaces `data_provider.get_resampled_bars` whose `time + timeframe` upper bound was the #21 look-ahead" note.
  - Constructor seeds the `(ticker, alias)` frame cache from `store.read_bars` for `store.symbols()`.
  - Feed-owned `_offset_alias` map: whole days -> `'{n}D'` (weeks resolve through this branch as `'{n*7}D'`, data-anchored — never `'W'`), hours -> `'h'`, minutes -> `'min'`; `ValueError` on anything else (Pitfall 2 — the legacy time_parser helper is never imported).
  - `precompute(tickers, timeframe)` resamples once per pair via `resample(alias, label="left", closed="left").agg(...)` and memoizes; `window()` on an un-cached pair lazily computes-and-memoizes through the same path.
  - `window()`: `cutoff = asof - timeframe + base_timeframe`, `searchsorted(cutoff, side="right")`, `iloc[max(0, pos - max_window):pos]` — zero resample calls on the per-tick path.
  - `current_bars(time)`: O(log n) exact-stamp lookup per symbol; present -> `Bar.from_row(time, row)` (Decimal string path); absent -> omitted.
  - `megaframe()`: per-symbol `window()` close columns concatenated with `keys=` the actually-included symbols (FR8 key fix); empty-window symbols excluded with their key and logged loudly; the legacy tz-naive drop condition is gone (store normalizes tz-aware at load).

### Task 2 — Regression suite (commit a25df94)

`tests/unit/price/test_bar_feed.py` (12 tests, rule-number comments tying each to the contract), built on `CsvPriceStore` over tmp_path Binance-kline CSVs with TIMEZONE-aligned stamps:

1. **Look-ahead (M5-01/D-02)**: forming 7d bucket invisible at asof=2020-01-06 AND visible at asof=2020-01-07 with close == base close of Jan 7 (both boundary directions); Pitfall-1 test proves pandas retains the trailing partial bucket in the resampled frame while the Feed slice hides it.
2. **Both branches agree (D-02)**: same-timeframe window's last row is the bar stamped T and equals the base-frame tail slice exactly.
3. **Precompute equality (M5-03)**: 2d feed windows equal a hand-built `resample('2D', label='left', closed='left')` reference sliced by the visibility rule across four ticks.
4. **Zero resample per tick (M5-03)**: monkeypatch-counted `pd.DataFrame.resample` — 0 calls on precomputed pairs, exactly 1 lazy memoize for a new timeframe, then 0.
5. **current_bars (D-15)**: Decimal fields == `Decimal(str(csv value))`, `Bar.time == T`, symbol with no bar at T absent.
6. **FR7**: unknown ticker -> `MissingPriceDataError`; sub-minute timeframe -> `ValueError`.
7. **Megaframe (D-19/FR8)**: three-symbol fixture — keys == actually-included symbols (June-only symbol excluded with its key at a January tick), per-key value identity vs per-symbol windows (distinct price seeds), tz-aware index.
8. **Offset-alias safety (Pitfall 2)**: '30min' precompute on a minutes fixture under `filterwarnings=["error"]` plus a rule-4 sanity assertion on the minutes grid.
9. **Equity close-mark (D-05/rule 6)**: `current_bars(T)[ticker].close` equals the base bar T close.

## Verification

- `poetry run pytest tests/unit/price/test_bar_feed.py -x -q` — 12 passed
- `poetry run pytest tests/unit/price/ -x -q` — 18 passed
- `make test` — 531 passed (full suite)
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` — 2 passed (feed not yet wired — trivially byte-exact, inert workstream per D-21)
- `make typecheck` — `Success: no issues found in 143 source files` (no new mypy override)
- Acceptance greps: `label="left"`, `closed="left"`, `searchsorted` present; "stamped by open time" and "never fill" in the module docstring; no `timedelta_to_str` import, no `get_resampled_bars` call.

## Deviations from Plan

None — plan executed as written. (One cosmetic adjustment: the Pitfall-2 docstring references the legacy helper descriptively instead of by its exact symbol name, so the T-06-09 acceptance grep for the banned token stays clean.)

## Threat Register Outcome

- T-06-08 (look-ahead): mitigated — completed-bars cutoff at the single slice point, boundary-tested in both directions.
- T-06-09 (month-end resample): mitigated — feed-owned alias map, banned-symbol grep clean, minutes fixture under filterwarnings=error.
- T-06-10 (megaframe key misalignment): mitigated — keys == included, per-key value-identity test.
- T-06-11 (silent missing data): mitigated — `MissingPriceDataError` on unknown ticker; absent-at-T is the documented sparse contract.

## Known Stubs

None. The Feed is intentionally **inert** this wave (nothing consumes it yet — wiring is 06-05's job per the plan objective); that is the planned D-22 structural-first sequencing, not a stub.

## Notes for 06-05

- `BacktestBarFeed(store, base_timeframe)` + `precompute(tickers, timeframe)` match the interfaces block exactly; the golden run's same-timeframe branch already conforms to the visibility rule, so the swap should stay byte-exact.
- Requirements M5-01/M5-03/M5-05 are partially delivered here (Feed half); REQUIREMENTS.md checkoffs left to the orchestrator after the wave merges (worktree mode — shared-file writes are orchestrator-owned, and 06-04/06-05 carry the remaining halves).

## Self-Check: PASSED

- itrader/price_handler/feed/base.py — FOUND
- itrader/price_handler/feed/bar_feed.py — FOUND
- itrader/price_handler/feed/__init__.py — FOUND
- tests/unit/price/test_bar_feed.py — FOUND
- Commit b0e3611 (Task 1) — FOUND
- Commit a25df94 (Task 2) — FOUND
