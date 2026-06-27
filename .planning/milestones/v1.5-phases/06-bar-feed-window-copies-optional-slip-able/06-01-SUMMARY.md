---
status: complete
phase: 06-bar-feed-window-copies-optional-slip-able
plan: 01
subsystem: price-handler / feed
tags: [perf, read-only-view, byte-identity, look-ahead-safety, behavior-preserving, PERF-06]
requires: []
provides:
  - "BacktestBarFeed.window() returns a read-only VIEW on the cached master frame instead of materializing a fresh wrapper every tick (D-01/D-07)"
  - "Master frames in self._frames are single-block + non-writeable at both build sites (D-09) — window views inherit read-only; an in-place mutation raises ValueError(read-only)"
  - "_offset_alias memoized with @functools.cache — per-call string compute fires once per timeframe (D-01)"
  - "D-08 three-assertion drift lock co-located with the 7-rule bar-timing contract suite"
affects:
  - itrader/price_handler/feed/bar_feed.py
  - tests/unit/price/test_bar_feed.py
tech-stack:
  added: []
  patterns:
    - "numpy read-only buffer enforcement at build (flags.writeable=False), not a per-tick runtime guard"
    - "byte-identity-preserving single-block consolidation via DataFrame.copy() before locking"
    - "@functools.cache memoize of a pure module fn (raise-on-unsupported preserved — cache does not store exceptions)"
key-files:
  created: []
  modified:
    - itrader/price_handler/feed/bar_feed.py
    - tests/unit/price/test_bar_feed.py
decisions:
  - "D-09 mechanism refined: the store's canonical OHLCV frame is MULTI-block (read_csv + astype(float) + .loc window slice leave it 4xN + 1xN), so to_numpy(copy=False) returns a fresh consolidated COPY and locking individual block buffers is unobservable through to_numpy. _readonly_master consolidates via a byte-identical DataFrame.copy() to a single block FIRST, then locks the single block's buffer — only then does the view inherit read-only and the D-08 (b) to_numpy(copy=False)[0,0] write raise. This is within the planned D-07 (byte-identity) + D-09 (read-only-at-build) envelope; the RESEARCH 'single homogeneous float64 block' premise held for the resampled frame but NOT the base store frame."
  - "Lock the BASE buffer, not the to_numpy view: to_numpy(copy=False) on a single-block frame returns a non-owning view whose .base IS the block buffer; setting flags.writeable=False on the returned view only flips the view's local flag. _readonly_master walks `arr if arr.flags.owndata else arr.base` and locks that, asserting np.shares_memory so a future copy-returning shape fails loud (D-09 fallback signal) rather than silently leaving the master writeable."
  - "window() returns the iloc view DIRECTLY with NO re-mark/re-copy: the view already inherits read-only from the locked single-block master, and an explicit _readonly_master(view) would re-copy and defeat the view return. _offset_alias body kept byte-unchanged (only the @functools.cache decorator added)."
metrics:
  duration: ~50min
  completed: 2026-06-24
  tasks: 3
  files: 2
  oracle: "134 trades / final_equity 46189.87730727451 (byte-exact, determinism double-run identical)"
  suite: "1258 passed; mypy --strict clean (165 files)"
---

# Phase 06 Plan 01: Bar-Feed Read-Only Window View Summary

`BacktestBarFeed.window()` now returns a read-only VIEW on the cached master frame instead of
materializing a fresh `pd.DataFrame` wrapper every tick (PERF-06, hotspot #5 / W2 ~22%), with
`_offset_alias` memoized via `@functools.cache` and the master frames marked non-writeable at
their two build sites so the look-ahead invariant is hard-enforced at the feed source — a
consumer in-place mutation now raises `ValueError(read-only)` instead of silently poisoning a
future tick. Behavior-preserving: byte-identical window content, no caller changes, the 7-rule
bar-timing contract intact, SMA_MACD oracle byte-exact (134 / 46189.87730727451).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 0 | D-08 read-only-view drift lock (Nyquist Wave-0 test stub) | `41a2cf6` | tests/unit/price/test_bar_feed.py |
| 1 | View-returning window() + memoized alias + read-only master frames (TDD GREEN) | `9168cae` | itrader/price_handler/feed/bar_feed.py |
| 2 | Gate (a) lock — determinism double-run + full suite (verification-only) | (no commit — verification) | — |

## What Changed

### `itrader/price_handler/feed/bar_feed.py` (4-space — not normalized)

- **`@functools.cache` on `_offset_alias`** (D-01): the per-call offset-alias string compute now
  fires once per distinct `timeframe` across `__init__`/`precompute`/the per-tick `window()` path.
  Function BODY byte-unchanged (verified `diff` of the executable lines) — only the decorator and a
  4-line decision comment were added. `functools.cache` does not cache exceptions, so the
  raise-on-unsupported `ValueError` guard is preserved (RESEARCH Pitfall 4).
- **`_readonly_master(frame) -> pd.DataFrame`** new module helper (D-09): consolidates to a single
  float64 block via a byte-identical `DataFrame.copy()`, then locks the single block's numpy buffer
  `flags.writeable = False` (walking `arr if arr.flags.owndata else arr.base`, asserting
  `np.shares_memory`). `resample`/`searchsorted`/`iterrows`/`ta` reads all verified to work on the
  non-writeable frame — no D-09 per-view fallback triggered.
- **Two build sites** call `_readonly_master`: `__init__` base load (`frame = _readonly_master(store.read_bars(ticker))`)
  and `_resampled_frame` (`resampled = _readonly_master(resampled)`). The store frame is returned
  untouched — only our cached copy is locked.
- **`window()`**: D-06 `start >= pos` empty short-circuit returns `frame.iloc[pos:pos]` unchanged
  (bypassing the view path); otherwise returns `frame.iloc[start:pos]` DIRECTLY — a view aliasing the
  locked single-block master, inheriting `writeable=False` for free (D-07: no `pd.DataFrame(...)`
  reconstruction, no per-tick copy). Signature + `pd.DataFrame` return type unchanged.

### `tests/unit/price/test_bar_feed.py` (4-space)

- **`test_window_view_content_equals_old_copy`** (D-08 a): the returned view is byte-identical to the
  old `frame.iloc[start:pos].copy()` (oracle = the matching positional slice of `daily_base_frame`)
  across sampled ticks, via `pd.testing.assert_frame_equal(check_freq=False)`.
- **`test_window_view_is_read_only_and_cannot_leak`** (D-08 b): a DIRECT numpy write
  `view.to_numpy(copy=False)[0,0] = 999.0` raises `ValueError(match="read-only")`, and re-fetching the
  same window yields the unchanged values (no leak). Targets the numpy `ValueError`, NOT a pandas
  `view.iloc[...] = x` chained assignment (RESEARCH Pitfall 1 — that fires `SettingWithCopyWarning`
  under `filterwarnings=["error"]` BEFORE the buffer is touched: false confidence).
- `import numpy as np` added. The existing 7-rule contract suite is D-08 assertion (c) — stays green.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Store frame is MULTI-block; RESEARCH single-block premise did not hold for the base frame**
- **Found during:** Task 1 (the `_readonly_master` self-check assert fired in fixture setup).
- **Issue:** RESEARCH Pattern 1 / Pitfall 2 assumed the golden OHLCV frame is a homogeneous single
  float64 block, so `frame.to_numpy(copy=False)` aliases its buffer and locking it protects views.
  Empirically the `CsvPriceStore` frame is MULTI-block (a 4xN block + a 1xN block — `read_csv` parse +
  `astype(float)` + the `.loc` window slice leave it unconsolidated). On a multi-block frame
  `to_numpy(copy=False)` returns a fresh CONSOLIDATED COPY: locking individual block buffers is
  unobservable through `to_numpy`, and the D-08 (b) `view.to_numpy(copy=False)[0,0] = x` write would
  target a throwaway copy and NOT raise — the read-only guarantee would be real but unverifiable, and a
  consumer's `to_numpy(copy=False)` write would silently no-op. Additionally, setting `flags.writeable`
  on the array returned by `to_numpy(copy=False)` (a non-owning VIEW) only flips that view's local flag,
  leaving the master buffer writeable.
- **Fix:** `_readonly_master` consolidates to a single block via a byte-identity-preserving
  `DataFrame.copy()` (verified `assert_frame_equal` vs the store frame) BEFORE locking, and locks the
  buffer the frame actually owns (`arr if arr.flags.owndata else arr.base`), with an
  `np.shares_memory` assert so any future copy-returning shape fails loud rather than silently leaving
  the master writeable. This stays inside the planned D-07 (byte-identity) + D-09 (read-only-at-build)
  envelope — it pins the exact pandas-2.3.3 / numpy-2.2.6 API under Claude's-discretion (RESEARCH §22),
  it does not change the design.
- **Files modified:** itrader/price_handler/feed/bar_feed.py
- **Commit:** `9168cae`

**2. [Rule 3 - Blocking] mypy --strict: `np.ndarray` needs type arguments**
- **Found during:** Task 1 (mypy gate).
- **Issue:** the `buffer: np.ndarray` annotation failed `--strict` (`Missing type arguments for generic type "ndarray" [type-arg]`).
- **Fix:** annotated `buffer: "np.ndarray[Any, np.dtype[Any]]"` (`Any` already imported). `.base` is
  loosely typed in the numpy stubs, so `Any` dtype is the honest annotation.
- **Files modified:** itrader/price_handler/feed/bar_feed.py
- **Commit:** `9168cae`

## Out-of-Plan Scope Note (not done — by design)

This plan's `files_modified` frontmatter scopes it to `bar_feed.py` + `test_bar_feed.py` only. The
gate-(b) W2 perf harness work (`perf/runners/run_w2_sweep.py` `--check`/`--baseline-out`, the
`W2-BASELINE.json` artifact, the `W1-BASELINE.json` re-freeze, Makefile wiring) is described in
RESEARCH/PATTERNS but is NOT in this plan's task list — it belongs to a later plan/phase-gate step and
was deliberately left untouched.

## Verification (Gate a — held)

- `poetry run pytest tests/unit/price/test_bar_feed.py -q` → 22 passed (20 contract + 2 drift).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed, byte-exact
  **134 trades / final_equity 46189.87730727451**; determinism double-run produced identical output.
- `poetry run pytest tests -q` → **1258 passed** (full unit/integration/e2e suite).
- `poetry run mypy itrader` → Success, no issues in 165 source files (`--strict`).

## Self-Check: PASSED

- FOUND: `.planning/phases/06-bar-feed-window-copies-optional-slip-able/06-01-SUMMARY.md`
- FOUND commit `41a2cf6` (Task 0 — test), modifies `tests/unit/price/test_bar_feed.py`
- FOUND commit `9168cae` (Task 1 — feat), modifies `itrader/price_handler/feed/bar_feed.py`
