---
phase: 06-bar-feed-window-copies-optional-slip-able
reviewed: 2026-06-24T18:21:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - itrader/price_handler/feed/bar_feed.py
  - itrader/events_handler/full_event_handler.py
  - perf/runners/run_w2_sweep.py
  - tests/unit/price/test_bar_feed.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: clean
---

# Phase 06: Code Review Report (iteration 2 — fix re-review)

**Reviewed:** 2026-06-24T18:21:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** clean

## Summary

This is a re-review of the four files touched by fix commits `accde2d` (WR-01
tz-naive guard in `bar_feed.window()`), `0c1f1b4` (IN-01 comment correction),
`f681a36` (WR-02 empty-frames guard in `run_w2_sweep.py`), and `6d7a254` (IN-03
regression test). The review focused adversarially on whether each fix is
correct and whether any of them introduced a regression on the behavior-preserving
PERF-06 golden-master path.

**Verdict: all four fixes are correct and behavior-preserving. No actionable
findings remain.** Verification performed:

- **WR-01 (tz-naive guard)** — verified the guard `getattr(cutoff, "tzinfo",
  None) is None` correctly detects tz-naive cutoffs for both `pd.Timestamp` and
  plain `datetime` (`cutoff` inherits tz from the `asof` arithmetic). The
  forward-step int64 compare (`cutoff_i8 = pd.Timestamp(cutoff).value` vs
  `index.asi8`) is instant-correct even across differing tz-aware timezones
  (both reduce to UTC-epoch ns — confirmed empirically). On the engine path the
  guard is a pure no-op (every caller passes tz-aware `TimeEvent.time`), so it
  is byte-identical to the prior behavior under golden-master discipline. The
  exception type for a tz-naive cold/rebuild call changes from `TypeError`
  (searchsorted) to `ValueError` (the guard), but no test or caller depends on
  the old type, so this is a benign, deliberate unification ("both branches fail
  loudly and identically").
- **WR-02 (empty-frames guard)** — `start`/`end` are assigned together inside
  the loop; the guard checks both and fires before either pass, and after the
  guard mypy narrows both `str | None` to `str` for the typed `_wire_system`
  call. Correctly catches the latent `None`-propagation defect (e.g. a future
  `n_symbols=0` point); currently unreachable, fails loudly.
- **IN-01 (comment)** — the reworded `asi8` comment ("fresh wrapper, shared
  buffer") is accurate; `frame.index.asi8` returns a new ndarray object aliasing
  the underlying buffer. Comment-only; no code change.
- **IN-03 (regression test)** — verified the new test genuinely exercises the
  `cutoff_i8 == last_cut` forward branch: a second identical-`asof` call leaves
  the cursor at the same position with a non-advancing `while` loop, and the
  second window is asserted byte-identical to the first. Meaningful lock, not a
  vacuous test.

Cross-checks: indentation is intact (bar_feed.py and run_w2_sweep.py remain
4-space with 0 leading tabs; test file 4-space; full_event_handler.py was NOT
touched by these commits and remains tab-indented — no normalization).
`full_event_handler.py` is in config scope but received no changes this
iteration and has no new defects (dispatch KeyError handling, fail-fast error
seam, and the defensive `getattr` on optional ErrorEvent fields are all sound).
`mypy --strict` clean on `bar_feed.py`; all 27 `test_bar_feed.py` tests pass.

## Info

### IN-01: `asi8` recomputed once per `window()` call (carried from prior IN-02 — out of scope)

**File:** `itrader/price_handler/feed/bar_feed.py:517`
**Issue:** `iv_i8 = frame.index.asi8` allocates a fresh ndarray wrapper on every
`window()` call (the comment now correctly says so). It could be cached per
`(ticker, alias)` alongside `_cursor`/`_cursor_cut` to avoid the per-call
wrapper allocation. This is the prior review's IN-02, explicitly deferred as
out-of-scope performance/consistency-only for this phase. Recorded here as Info
only per the iteration instructions — NOT an actionable warning. No correctness
impact: the buffer is shared and read-only, and the value is identical every
call.
**Fix:** Optional future micro-opt — memoize the `asi8` view keyed by
`(ticker, alias)` if a later profiling pass shows the wrapper allocation is
material. No change recommended for this phase.

---

_Reviewed: 2026-06-24T18:21:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
