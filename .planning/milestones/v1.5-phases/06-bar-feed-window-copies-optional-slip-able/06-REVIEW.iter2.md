---
phase: 06-bar-feed-window-copies-optional-slip-able
reviewed: 2026-06-24T15:40:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - itrader/price_handler/feed/bar_feed.py
  - itrader/events_handler/full_event_handler.py
  - perf/runners/run_w2_sweep.py
  - tests/unit/price/test_bar_feed.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-06-24T15:40:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

This is a behavior-preserving PERF-06 phase. The central change is the per-(ticker, alias)
monotonic int64 forward cursor that replaces the per-tick `frame.index.searchsorted(cutoff,
side="right")` inside `BacktestBarFeed.window()`. The review focused adversarially on the
LOOK-AHEAD INVARIANT (no bar with `time > cutoff` may leak) and on byte-identity with the old
`searchsorted` path.

**The core cursor logic is correct.** I brute-forced the forward-step walk against a fresh
`searchsorted(side="right")` oracle over a gappy tz-aware index across cold / monotonic-forward /
multi-bar-step / duplicate-cutoff / backwards-jump streams — every position matched byte-for-byte.
The `<=` comparison reproduces `side="right"` exactly; the `cutoff_i8 < last_cut` rebuild guard
fires on every backwards/jumped cutoff and never trusts stale state; the equal-consecutive-cutoff
case (`cutoff_i8 == last_cut`) correctly takes the forward branch and does not advance. The
read-only view, the empty-window short-circuit (`frame.iloc[pos:pos]`), and byte-identity
(dtype/tz-aware index/column set+order) are all preserved. All 26 unit tests pass; `mypy --strict`
is clean on the changed file. The 7-rule bar-timing contract docstring is intact.

The `full_event_handler.py` change is a clean removal of a single per-tick DEBUG log line; the
`EventType.TIME` dispatch route is byte-unchanged and indentation stays tabs (134 tab lines, 0
space lines). The `run_w2_sweep.py` split into a timed PASS 1 + un-timed tracemalloc PASS 2 is a
harness-only change; `bar_feed.py` and `run_w2_sweep.py` remain 4-space, no normalization.

Two WARNINGs below concern robustness regressions that are NOT reachable on the golden/live engine
path (so not BLOCKERs), plus three INFO items.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Forward-step branch silently miscomputes the cursor on a tz-naive `asof`

**File:** `itrader/price_handler/feed/bar_feed.py:510-524`
**Issue:** The forward-step branch compares `cutoff_i8 = pd.Timestamp(cutoff).value` (raw ns since
the UTC epoch) directly against `iv_i8 = frame.index.asi8`. The cold/rebuild branch still calls
`frame.index.searchsorted(cutoff, side="right")`, which **raises `TypeError` ("Cannot compare
tz-naive and tz-aware datetime-like objects")** when `cutoff` is tz-naive against the tz-aware
index. The two branches therefore DIVERGE for a tz-naive `asof`: the old code (and the cold/rebuild
path) fails loudly, but the forward-step path silently compares mismatched int64 values offset by
the tz offset — producing a WRONG cursor position that can leak or hide a bar. Confirmed empirically:
for a `Europe/Rome` index, a tz-naive `2020-01-03` yields `value=1578009600000000000` vs the
tz-aware `asi8[2]=1578006000000000000` (a 1-hour skew), while `searchsorted` raises.

This is NOT reachable on the engine path — `window()` is always called with `asof=event.time`, and
`TimeEvent.time` is tz-aware across the whole `TimeGenerator` grid — so it is a robustness
regression, not a live look-ahead leak. But it removes the loud-fail backstop the old path gave a
future caller/test that passes a tz-naive time, replacing a `TypeError` with silent miscomputation.
**Fix:** Add a one-time normalization or guard so the forward path matches the rebuild path's
loud-fail behavior, e.g. assert tz-awareness once at the top of `window()`:
```python
# guard tz-parity with the index so the forward branch cannot silently
# skew the int64 compare (the cold/rebuild searchsorted path raises here today)
if getattr(cutoff, "tzinfo", None) is None:
    raise ValueError(
        f"window() asof must be tz-aware to match the tz-aware index; got {asof!r}")
```
or convert via `pd.Timestamp(cutoff, tz="UTC")` semantics consistently. At minimum, add a unit test
asserting a tz-naive `asof` still raises (locking the old loud-fail contract).

### WR-02: `start`/`end` can reach `_wire_system` as `None` (typed `str`) if the frames dict is empty

**File:** `perf/runners/run_w2_sweep.py:131-150`
**Issue:** `start = None` / `end = None` are only assigned inside `if start is None:` within the
`for ticker, frame in frames.items()` loop. If `make_synthetic_ohlcv` ever returned an empty dict,
the loop body never runs and `_wire_system(csv_paths, None, None, [])` is called, passing `None`
where the signature declares `start: str, end: str` — a latent `TypeError`/silent-misbehavior. This
is currently unreachable (`_N_SYMBOLS_SWEEP = [1, 10, 50]` is always non-empty) and is a perf-harness
file, not engine code, so it is a WARNING not a BLOCKER. The two-pass refactor moved the wiring into
a helper but carried the latent `None`-init forward.
**Fix:** Guard explicitly before the passes, e.g.:
```python
if start is None or end is None:
    raise RuntimeError("W2 sweep produced no frames — cannot wire the system")
```

## Info

### IN-01: Comment claims `asi8` is a "cached" view; it returns a fresh wrapper each call

**File:** `itrader/price_handler/feed/bar_feed.py:505`
**Issue:** The inline comment reads `# zero-copy cached int64 ns view (UTC)`. `frame.index.asi8`
returns a NEW ndarray object on every call (verified: `a is b` is False) though it shares the
underlying buffer (`np.shares_memory` is True). The per-call O(1) wrapper construction is
negligible, so this is not a defect — but "cached" overstates it. Consider "zero-copy int64 ns
view (UTC; fresh wrapper, shared buffer)" to avoid implying object-level memoization.

### IN-02: `asi8` is re-derived every `window()` call rather than once per frame

**File:** `itrader/price_handler/feed/bar_feed.py:505`
**Issue:** Since each memoized master frame is immutable (read-only buffer) for the life of the feed,
`frame.index.asi8` is invariant per `(ticker, alias)` and could be cached alongside `self._frames`
(e.g. `self._index_i8[key]`) to drop the per-tick wrapper allocation entirely — the same compute-once
discipline already applied to `_spans`/`_prebuilt`. Out of strict v1 scope (performance), noted as a
consistency observation only; correctness is unaffected.

### IN-03: No dedicated test for the equal-consecutive-cutoff forward branch

**File:** `tests/unit/price/test_bar_feed.py:403-484`
**Issue:** The D-16 cursor suite covers cold, monotonic-forward (multi-step), backwards-rebuild,
cold+gap, and universe-reentry — strong coverage. The one untested branch is two consecutive calls
with an IDENTICAL `asof` (`cutoff_i8 == last_cut`), which takes the forward branch with `pos =
last_pos` and a non-advancing while loop. I verified it behaves correctly through the real feed
(both windows byte-identical), but it is not regression-locked. Consider adding an assertion that a
repeated identical `asof` returns an identical window to harden the equivalence proof.

---

_Reviewed: 2026-06-24T15:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
