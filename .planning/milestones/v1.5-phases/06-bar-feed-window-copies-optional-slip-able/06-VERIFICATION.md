---
phase: 06-bar-feed-window-copies-optional-slip-able
verified: 2026-06-24T18:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 06: Bar-Feed Window Copies — Verification Report

**Phase Goal:** PERF-06 — reduce the per-tick bar-feed window-construction cost in BacktestBarFeed.window() (hotspot #5, ~4% W1 / ~22% W2), behavior-preserving, contract-gated by the 7-rule look-ahead bar-timing invariant. Gate (a): byte-exact SMA_MACD oracle (134 trades / final_equity 46189.87730727451) + mypy --strict clean + determinism byte-identical. Gate (b): a measurable W2 win + W1 non-regress.
**Verified:** 2026-06-24T18:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Pivot Context

This phase pivoted mid-stream (D-10–D-16 in 06-CONTEXT.md). The original view/alias approach (06-01) profiled at ~0% W2 win. The real lever was identified as the per-tick `searchsorted` (13.2% of W2). The phase then added:
- 06-01 (kept): read-only view + alias memoization + non-writeable master frames — a real look-ahead-safety win, ~0% W2 perf.
- 06-02 (Task 1 only): W2 gate harness committed; Tasks 2/3 superseded/absorbed into 06-05.
- 06-03: Denominator cleanup — TIME EVENT debug log removed + W2 harness de-timed.
- 06-04: D-10 monotonic int64 forward cursor in window() — the primary perf lever.
- 06-05: D-15 ship-and-reframe — +1.9% W2 at 50 symbols honestly, gate (b) reframed per pre-agreed fallback.

Gate (b) target was reframed from >=10% to "measurable W2 win + W1 non-regress" via D-15 — the documented pre-agreed fallback for this OPTIONAL/slip-able phase.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Per-tick window materialization reduces frame copies (reusable view / cached searchsorted bounds) on the BacktestBarFeed.window path (SC-1) | VERIFIED | `window()` returns `frame.iloc[start:pos]` — a VIEW on the locked single-block non-writeable master (D-09/D-07). `_readonly_master()` helper at bar_feed.py:132. The per-tick searchsorted is replaced by a monotonic int64 cursor. |
| 2 | The look-ahead bar-timing contract is preserved — all 7 rules in feed/bar_feed.py hold; no future bar becomes visible and no window content changes (SC-2) | VERIFIED | 7-rule contract docstring intact at bar_feed.py:1-55 byte-for-byte. D-16 drift suite: 4 cursor tests pass (cursor==searchsorted, no-future-bar, backwards-asof rebuild, cold/gap, universe re-entry). `poetry run pytest tests/unit/price/test_bar_feed.py -k cursor -q` → 4 passed. |
| 3 | Gate (a): byte-exact SMA_MACD oracle (134 trades / final_equity 46189.87730727451) green, mypy --strict clean, determinism double-run byte-identical (SC-3) | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (confirmed live). `poetry run mypy itrader` → "Success: no issues found in 187 source files" (confirmed live). Determinism byte-identical per 06-04 SUMMARY. |
| 4 | Gate (b) — measurable W2 win + W1 non-regress: +1.9% W2 at 50 symbols (cursorless 14.31s → cursor-on 14.04s, same-session A/B); W1 flat (1-symbol A/B confirms thermal, not regression) (SC-4, reframed via D-15) | VERIFIED | perf/results/W2-BASELINE.json committed (13.61s @ 50 symbols, cursor-on). W1-BASELINE.json kept at prior 238.5s (not overwritten with thermally-inflated 259.1s). D-15 ship-and-reframe invoked per documented pre-agreed fallback for OPTIONAL phase. |
| 5 | D-10 monotonic int64 cursor in window() with cold/non-monotonic searchsorted rebuild guard, keyed (ticker, alias), never leaks a future bar | VERIFIED | bar_feed.py:503-526: `self._cursor / self._cursor_cut` dicts, `iv_i8 = frame.index.asi8`, `cutoff_i8 = pd.Timestamp(cutoff).value`, `if last_pos is None or last_cut is None or cutoff_i8 < last_cut: pos = int(frame.index.searchsorted(...))`. No unconditional searchsorted per tick. No hot-loop runtime assert (`grep 'assert.*searchsorted' bar_feed.py` → empty). |
| 6 | D-13 denominator cleanup: per-bar TIME EVENT debug log removed from event dispatcher; W2 sweep harness de-timed (two-pass: clean wall-clock + separate tracemalloc peak-mem) | VERIFIED | `grep 'TIME EVENT'` in full_event_handler.py → no output. EventType.TIME route entry still present (line 69: the dispatch route). run_w2_sweep.py:143-154: PASS 1 (perf_counter, no tracemalloc), PASS 2 (tracemalloc, fresh re-wired system). |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/price_handler/feed/bar_feed.py` | Monotonic int64 forward cursor in window() with searchsorted rebuild guard; _readonly_master helper; _cursor/_cursor_cut state dicts in __init__; @functools.cache on _offset_alias | VERIFIED | Lines 85-86 (@functools.cache), 132-176 (_readonly_master), 263-264 (_cursor/_cursor_cut dicts), 503-526 (cursor logic in window()). All key patterns confirmed: asi8 at :505, cutoff_i8 at :510, rebuild guard at :513, forward step at :523. |
| `tests/unit/price/test_bar_feed.py` | D-16 cursor==searchsorted + no-future-bar + reset/cold/gap/re-entry tests co-located with kept D-08 suite | VERIFIED | Lines 375-488: D-16 section header, 4 tests: test_cursor_equals_fresh_searchsorted_across_ticks (:403), test_cursor_safe_rebuild_on_backwards_asof (:426), test_cursor_cold_and_gap (:457), test_cursor_universe_reentry (:473). D-08 tests kept at :343/:359. All 26 tests pass. |
| `perf/results/W2-BASELINE.json` | Committed cursor-on 50-symbol W2 reference (seeds Phase 5); records actual W2 result | VERIFIED | File exists: 13.61s @ 50 symbols, peak 214.58 MB, frozen_at 2026-06-24. schema_version=1, sweep n_symbols=[1,10,50]. |
| `perf/results/W1-BASELINE.json` | Re-frozen W1 reference (or kept at prior value per thermal discipline) | VERIFIED | File exists: wall_clock_s=238.5 (prior value deliberately kept — 259.1s thermal run NOT committed per D-15 thermal discipline). oracle_provenance confirms 134 trades / 46189.87730727451 green_at_freeze. |
| `itrader/events_handler/full_event_handler.py` | Per-bar TIME EVENT debug log removed (D-13); EventType.TIME route intact | VERIFIED | No "TIME EVENT" string in file. EventType.TIME route at line 69 intact. |
| `perf/runners/run_w2_sweep.py` | Two-pass _run_point: clean timed PASS 1 (no tracemalloc) + peak-mem PASS 2; --check/--baseline-out flags; _wire_system helper | VERIFIED | _wire_system at :95, two-pass _run_point at :118-154. PASS 1 at :143-147 (perf_counter only), PASS 2 at :149-154 (tracemalloc). --check/:246, --baseline-out/:244, _check_w2/:211. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| BacktestBarFeed.window() | frame.index.asi8 / pd.Timestamp(cutoff).value | Forward int64-ns cursor step with cutoff_i8 < last_cut rebuild guard | VERIFIED | bar_feed.py:505 `iv_i8 = frame.index.asi8`, :510 `cutoff_i8 = pd.Timestamp(cutoff).value`, :513 rebuild condition, :523 forward step `while pos < n and iv_i8[pos] <= cutoff_i8` |
| tests/unit/price/test_bar_feed.py D-16 tests | frame.index.searchsorted(cutoff, side="right") | cursor (start,pos) == fresh searchsorted across sampled ticks | VERIFIED | test_cursor_equals_fresh_searchsorted_across_ticks at :403 asserts equivalence across advancing asof; test_cursor_safe_rebuild_on_backwards_asof at :426 asserts no-future-bar after backwards step |
| run_w2_sweep.py --check | perf/results/W2-BASELINE.json | 50-symbol wall_clock_s improvement gate (D-15 reframed) | VERIFIED | _check_w2 at :211 reads W2-BASELINE.json; W2-BASELINE.json exists with 50-symbol cursor-on reference |
| _readonly_master (build sites) | self._frames[(ticker, alias)] | Non-writeable single-block master → window() views inherit read-only | VERIFIED | :245 `frame = _readonly_master(store.read_bars(ticker))`, :352 `resampled = _readonly_master(resampled)`. D-08(b) test at :359 confirms in-place mutation raises ValueError. |

### Data-Flow Trace (Level 4)

Not applicable. This is a perf-optimization phase with no dynamic data rendering or new user-visible data paths. The changes are internal to the window-slice hot path (not a new component producing UI-visible data). The oracle test confirms data flow integrity end-to-end.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Cursor tests pass | `poetry run pytest tests/unit/price/test_bar_feed.py -k cursor -q` | 4 passed | PASS |
| Oracle (gate a) green | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (134 / 46189.87730727451) | PASS |
| mypy --strict clean | `poetry run mypy itrader` | Success: no issues found in 187 source files | PASS |
| Full bar feed suite | `poetry run pytest tests/unit/price/test_bar_feed.py -q` | 26 passed | PASS |
| No hot-loop runtime assert | `grep 'assert.*searchsorted' itrader/price_handler/feed/bar_feed.py` | (no output) | PASS |
| TIME EVENT log absent | `grep 'TIME EVENT' itrader/events_handler/full_event_handler.py` | (no output) | PASS |
| W2-BASELINE.json committed | file exists with cursor-on 50-symbol reference | 13.61s @ 50 symbols | PASS |

### Probe Execution

No probe scripts declared for this phase. Behavioral spot-checks substitute.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PERF-06 | 06-04-PLAN.md (requirements: [PERF-06]), 06-05-PLAN.md (requirements_completed: [PERF-06]) | Per-tick bar-feed window iloc frame copies are reduced (reusable view / cached slice bounds), preserving the look-ahead bar-timing contract | SATISFIED | window() returns read-only iloc view; searchsorted replaced by monotonic cursor; 7-rule contract intact; oracle byte-exact; +1.9% W2 win measured; W1 non-regressive. REQUIREMENTS.md marks PERF-06 as [x] Complete. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found in modified files | — | — |

No stub patterns detected. The implementation is substantive: real cursor logic in window(), real test coverage in test_bar_feed.py, real artifact in W2-BASELINE.json.

### Human Verification Required

None. All success criteria are verifiable programmatically:
- Gate (a): oracle test run live — 3 passed.
- Gate (b): W2 measurement documented in 06-05-SUMMARY.md with concrete before/after numbers (+1.9% at 50 symbols); D-15 ship-and-reframe is the documented pre-agreed fallback. W2-BASELINE.json committed. W1 thermal discipline documented and justified.
- Look-ahead correctness: proven by D-16 drift suite (4 tests, cursor==searchsorted + no-future-bar invariant across cold/backwards/gap/reentry scenarios).

### Gaps Summary

No gaps. All 6 must-haves are VERIFIED:

1. The read-only view return from window() is implemented (D-07/D-09, 06-01).
2. The 7-rule look-ahead bar-timing contract is intact and test-locked (D-08/D-16).
3. Gate (a) confirmed live: oracle 3 passed (134 / 46189.87730727451), mypy clean (187 files).
4. Gate (b) measured and documented: +1.9% W2 at 50 symbols; D-15 ship-and-reframe applied per pre-agreed fallback; W2-BASELINE.json committed.
5. D-10 monotonic cursor is implemented in window(), correctly keyed (ticker, alias), with cold/non-monotonic searchsorted rebuild guard that never leaks a future bar.
6. D-13 denominator cleanup is complete: TIME EVENT debug log removed; run_w2_sweep is two-pass (clean wall-clock + separate tracemalloc).

**One carried todo (not a gap):** W1-BASELINE.json absolute re-freeze on a verified-cool isolated run. The prior 238.5s reference is still valid (W1 non-regression confirmed by same-session 1-symbol A/B); the carried todo defers the cleaned-engine absolute re-freeze due to thermal contamination, consistent with the D-15 discipline and documented in 06-05-SUMMARY.md.

**Two code review WARNINGs from 06-REVIEW.md** (recorded for awareness, not blockers):
- WR-01: Forward-step branch silently miscomputes on a tz-naive `asof` (not reachable on the engine path — TimeEvent.time is always tz-aware). Robustness regression vs the old loud-fail searchsorted behavior.
- WR-02: `start`/`end` can reach `_wire_system` as None in run_w2_sweep.py if frames dict is empty (perf harness, not engine code; not reachable with the current sweep sizes).
Neither is reachable on the golden/live engine path.

---

_Verified: 2026-06-24T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
