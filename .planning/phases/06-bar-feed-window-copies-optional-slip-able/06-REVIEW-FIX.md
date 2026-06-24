---
phase: 06-bar-feed-window-copies-optional-slip-able
fixed_at: 2026-06-24T15:40:00Z
review_path: .planning/phases/06-bar-feed-window-copies-optional-slip-able/06-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 4
skipped: 1
status: partial
---

# Phase 06: Code Review Fix Report

**Fixed at:** 2026-06-24T15:40:00Z
**Source review:** .planning/phases/06-bar-feed-window-copies-optional-slip-able/06-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope=all — critical/warning/info)
- Fixed: 4
- Skipped: 1

## Fixed Issues

### WR-01: Forward-step branch silently miscomputes the cursor on a tz-naive `asof`

**Files modified:** `itrader/price_handler/feed/bar_feed.py`
**Commit:** accde2d
**Applied fix:** Added a one-time tz-awareness guard at the top of `window()` (right
after `cutoff` is computed, before the int64 forward-cursor logic). When
`cutoff.tzinfo is None` it raises `ValueError`, so the forward-step branch can no
longer silently skew the int64 compare against the tz-aware index `asi8`. This
restores the loud-fail backstop the cold/rebuild `searchsorted` path already gives
(it raises `TypeError` on a tz-naive↔tz-aware compare) and makes both branches fail
identically. Behavior-preserving on the engine path: `window()` is always called
with `asof=event.time`, which is tz-aware across the whole `TimeGenerator` grid, so
no reachable engine call is affected. Verified: `mypy --strict` clean on the file;
all 27 `test_bar_feed.py` tests pass.

### WR-02: `start`/`end` can reach `_wire_system` as `None` if the frames dict is empty

**Files modified:** `perf/runners/run_w2_sweep.py`
**Commit:** f681a36
**Applied fix:** Added an explicit `if start is None or end is None: raise
RuntimeError(...)` guard after the per-frame loop and before the timed passes, so an
empty `frames` dict fails loudly instead of passing `None` into `_wire_system`'s
typed `start: str, end: str` signature. Harness-only file; currently unreachable
(`_N_SYMBOLS_SWEEP` is always non-empty). Verified: file parses (`ast.parse` OK);
4-space indentation preserved (no normalization).

### IN-01: Comment claims `asi8` is a "cached" view; it returns a fresh wrapper each call

**Files modified:** `itrader/price_handler/feed/bar_feed.py`
**Commit:** 0c1f1b4
**Applied fix:** Reworded the inline comment from `# zero-copy cached int64 ns view
(UTC)` to `# zero-copy int64 ns view (UTC; fresh wrapper, shared buffer)` so it no
longer implies object-level memoization (`frame.index.asi8` returns a new ndarray
object per call but shares the underlying buffer). Comment-only; no code/behavior
change. Verified: `mypy --strict` clean; tests pass.

### IN-03: No dedicated test for the equal-consecutive-cutoff forward branch

**Files modified:** `tests/unit/price/test_bar_feed.py`
**Commit:** 6d7a254
**Applied fix:** Added `test_cursor_repeated_identical_asof_forward_branch`, which
calls `window()` twice with an identical `asof` (exercising the `cutoff_i8 ==
last_cut` case: forward branch, `pos == last_pos`, non-advancing while loop) and
asserts the two returned windows are byte-identical via
`pd.testing.assert_frame_equal`. Regression-locks the previously-untested branch.
Verified: new test passes (27 passed total in `test_bar_feed.py`).

## Skipped Issues

### IN-02: `asi8` is re-derived every `window()` call rather than once per frame

**File:** `itrader/price_handler/feed/bar_feed.py:505`
**Reason:** skipped — out of strict v1 scope (performance), reviewer flagged it as a
"consistency observation only; correctness is unaffected." This is a golden-locked,
behavior-preserving PERF-06 phase. Caching `frame.index.asi8` alongside `self._frames`
would touch the per-tick hot path; the reviewer notes the per-call O(1) wrapper
construction is negligible, so applying it risks a behavior/perf regression for no
correctness benefit. Per explicit guidance, prefer SKIP over altering the hot-path in
a golden-locked phase. The IN-01 comment fix (committed) already corrects the
misleading "cached" wording that IN-02 builds on.
**Original issue:** Since each memoized master frame is immutable for the life of the
feed, `frame.index.asi8` is invariant per `(ticker, alias)` and could be cached
(e.g. `self._index_i8[key]`) to drop the per-tick wrapper allocation — the
compute-once discipline already applied to `_spans`/`_prebuilt`.

---

_Fixed: 2026-06-24T15:40:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
