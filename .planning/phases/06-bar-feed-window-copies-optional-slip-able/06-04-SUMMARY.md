---
phase: 06-bar-feed-window-copies-optional-slip-able
plan: 04
subsystem: infra
tags: [pandas, numpy, bar-feed, cursor, searchsorted, asi8, look-ahead, perf, backtest]

# Dependency graph
requires:
  - phase: 06-01
    provides: read-only single-block non-writeable master frames + window() iloc view (D-09/D-12) the cursor returns on top of
  - phase: 06-03
    provides: cleaned engine denominator (TIME EVENT log removed, run_w2_sweep de-timed) so the cursor's W2 win is measurable
provides:
  - "Per-(ticker, alias) monotonic int64 forward cursor in BacktestBarFeed.window() replacing the per-tick searchsorted (13.2% W2 hotspot), byte-identical to searchsorted(side=right)"
  - "Safe searchsorted rebuild guard (cold key OR cutoff_i8 < last_cut) that never leaks a future bar"
  - "Extended D-08 drift suite (D-16): cursor==searchsorted equivalence + no-future-bar + backwards-asof/cold/gap/re-entry reset-safety tests"
affects: [06-05, "gate-b W2 re-freeze", "Phase 5 incremental indicators"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Monotonic forward cursor over frame.index.asi8 (int64 ns) compared against pd.Timestamp(cutoff).value — int64 path is load-bearing (0.14 µs/step vs 4.3 µs searchsorted)"
    - "Fast-path-with-correct-fallback: trust the cached cursor only on a monotonic-forward step; silently rebuild via searchsorted on any cold/non-monotonic step (never trust stale state, never leak)"
    - "Audit-the-invariant + dedicated drift test, zero hot-loop runtime guard (Phase 3 D-03 / Phase 4 D-06/07 / this phase D-08/D-09/D-16)"

key-files:
  created: []
  modified:
    - "itrader/price_handler/feed/bar_feed.py — cursor state dicts in __init__; monotonic int64 forward cursor + searchsorted rebuild guard in window()"
    - "tests/unit/price/test_bar_feed.py — 4 D-16 cursor-equivalence + reset-safety tests extending the D-08 suite"

key-decisions:
  - "D-10: replace per-tick searchsorted with a per-(ticker,alias) forward int64 cursor; cutoff stays exclusive-right (<= reproduces side=right byte-for-byte)"
  - "D-10 reset-safety: cold key OR cutoff_i8 < last_cut -> silent safe searchsorted rebuild (a non-monotonic cutoff is legitimate — screener re-entry/resampled cutoffs — not a crash)"
  - "D-11: iloc[start:pos] KEPT cursor-only — every cheaper-slice candidate measured slower than iloc on this single-block frame; recorded as investigated + empirically infeasible (D-15 absorbs the 7.9%)"
  - "D-12: built on top of 06-01's read-only view — 9168cae not reverted or modified"
  - "D-16: cursor==searchsorted proven in the test only; NO hot-loop runtime assert (would re-pay the searchsorted the cursor removes)"
  - "cutoff_i8 = pd.Timestamp(cutoff).value (not cutoff.value) — no-op box keeps mypy --strict happy since asof is typed datetime, no per-tick datetime64 convert"

patterns-established:
  - "Monotonic int64 forward cursor with a searchsorted rebuild guard for a look-ahead-safe window slice"
  - "Cursor keyed (ticker, alias) mirroring self._frames exactly (Pitfall 5 — never key on ticker alone)"

requirements-completed: [PERF-06]

# Metrics
duration: 5min
completed: 2026-06-24
---

# Phase 6 Plan 04: D-10 Monotonic Incremental Cursor Summary

**BacktestBarFeed.window() now resolves its cutoff via a per-(ticker,alias) monotonic int64 forward cursor over `frame.index.asi8` — byte-identical to `searchsorted(side="right")`, removing the 13.2%-of-W2 per-tick searchsorted hotspot — with a cold/non-monotonic searchsorted rebuild guard that can never leak a future bar.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-24T15:00:58Z
- **Completed:** 2026-06-24T15:05:28Z
- **Tasks:** 2 (both TDD/auto)
- **Files modified:** 2

## Accomplishments
- Replaced the per-tick `frame.index.searchsorted(cutoff, side="right")` in `window()` with a per-(ticker, alias) monotonic forward cursor over `frame.index.asi8` (int64 ns), comparing `iv_i8[pos] <= cutoff_i8` (0.14 µs/step vs searchsorted's 4.3 µs). The `<=` reproduces `searchsorted(side="right")` byte-for-byte (exclusive-right, contract rule 4).
- Added the reset-safety guard: on a COLD key (`last_pos is None`) OR a NON-MONOTONIC step (`cutoff_i8 < last_cut`), `window()` falls back to a silent safe `searchsorted` rebuild — never trusting stale state, never leaking a bar stamped `> cutoff`. Threat T-06-04-01 mitigated.
- Kept the 06-01 read-only `iloc[start:pos]` view and the D-06 empty short-circuit (`iloc[pos:pos]`) unchanged (D-11 cursor-only, D-12 built-on-top). The cheaper-slice idea (D-11) is recorded in-code as investigated + empirically infeasible (every candidate slower than iloc; D-07 forbids reconstruction), the 7.9% accepted via D-15.
- Extended the D-08 drift suite with 4 D-16 tests: cursor==searchsorted across monotonic ticks + no-future-bar, backwards-asof rebuild, cold cursor + gap frame, universe re-entry. Co-located with the kept 06-01 D-08 tests, opened with decision-tag docstrings stating no hot-path runtime guard is added.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend the D-08 drift suite with D-16 cursor-equivalence + reset-safety tests** - `d034ea3` (test)
2. **Task 2: Add the monotonic int64 forward cursor to window() with a searchsorted rebuild guard** - `00c5480` (feat)

_TDD note: the Task-1 tests encode the look-ahead INVARIANT (byte-identical to searchsorted), so they pass against both the pre-cursor (searchsorted) and post-cursor `window()` — a deliberate invariant-lock rather than an implementation-coupled RED. They were committed before the implementation per the plan's TDD framing._

## Files Created/Modified
- `itrader/price_handler/feed/bar_feed.py` — added `self._cursor` / `self._cursor_cut` typed `dict[tuple[str, str], int]` state in `__init__` (after the `_prebuilt` loop); replaced the single `searchsorted` line in `window()` with the forward int64 cursor + rebuild guard; updated the window() docstring (rule-4 cursor note) and the D-01/D-06/D-07/D-09 comment block to cite D-10/D-11/D-12. The 7-rule contract docstring (:9-55) is byte-unchanged.
- `tests/unit/price/test_bar_feed.py` — 4 new tests (`test_cursor_equals_fresh_searchsorted_across_ticks`, `test_cursor_safe_rebuild_on_backwards_asof`, `test_cursor_cold_and_gap`, `test_cursor_universe_reentry`) extending the D-08 section; the kept 06-01 D-08 tests (`test_window_view_content_equals_old_copy`, `test_window_view_is_read_only_and_cannot_leak`) and the 7-rule contract suite stay green verbatim.

## Decisions Made
- **`cutoff_i8 = pd.Timestamp(cutoff).value`** (not `cutoff.value`): `asof` is typed `datetime` in the `window()` signature, so the derived `cutoff` is statically `datetime`, which has no `.value` (mypy --strict error). Wrapping in `pd.Timestamp(...)` is a no-op box at run time (the value already arrives as a tz-aware `pd.Timestamp`), keeps the O(1) int64 attribute access (no per-tick `np.datetime64` conversion), and is mypy-clean. Documented in-code.
- Silent safe-rebuild (not fail-loud) on a non-monotonic cutoff, per RESEARCH A3 — a backwards cutoff is legitimate (screener re-entry, resampled cutoffs); the rebuild is exactly today's behavior and never leaks.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mypy --strict rejected `cutoff.value`**
- **Found during:** Task 2 (cursor implementation)
- **Issue:** `cutoff = asof - timeframe + self._base_timeframe` is statically typed `datetime` (the `window()` signature types `asof: datetime`), and `datetime` has no `.value` attribute → `mypy itrader` reported `"datetime" has no attribute "value"`. The plan's interface snippet used `cutoff.value` directly. Gate (a) requires `mypy --strict` clean.
- **Fix:** Used `pd.Timestamp(cutoff).value` — a no-op box (the run-time value is already a tz-aware `pd.Timestamp`) that is statically `pd.Timestamp` (which has `.value -> int`). Preserves the O(1) int64-ns semantics the plan/research mandate (NOT a per-tick `np.datetime64` conversion — Pitfall anti-pattern avoided) and added a comment explaining the box.
- **Files modified:** itrader/price_handler/feed/bar_feed.py (part of the Task 2 commit)
- **Verification:** `poetry run mypy itrader` → "Success: no issues found in 187 source files"; bar_feed cursor tests + oracle still green; the int64 fast path is unchanged.
- **Committed in:** `00c5480` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix is a mypy-driven type adjustment required by gate (a); it preserves the exact int64-ns mechanism the research verified (no perf regression — `.value` is O(1) on an already-boxed Timestamp). No scope creep.

## Issues Encountered
None beyond the mypy type fix documented above.

## Verification Evidence

- **Gate (a) — byte-exact oracle:** `tests/integration/test_backtest_oracle.py` → 3 passed (134 trades / final_equity 46189.87730727451, frozen golden CSVs byte-equal).
- **Determinism double-run byte-identical:** two consecutive full SMA_MACD backtest runs hashed identical (`dc937b59…039e91` == `dc937b59…039e91`, SHA-256 over trade+equity frames).
- **mypy --strict:** Success, no issues in 187 source files.
- **D-16 / D-08 drift suite:** `-k cursor` selects 4, all pass; `-k "view_content or read_only"` selects the 2 kept D-08 tests, both pass; full `test_bar_feed.py` 26 tests green (7-rule contract = D-08 assertion c).
- **No hot-loop runtime assert:** `grep -E 'assert.*searchsorted' bar_feed.py` returns nothing (D-16).
- **Cursor wiring present:** `asi8`, `_cursor`, `cutoff.value` all grep-confirmed in `bar_feed.py`; `iloc[start:pos]` + `iloc[pos:pos]` unchanged.
- **Full suite:** `poetry run pytest tests` → 1262 passed.

## Known Stubs
None.

## Next Phase Readiness
- The cursor is shipped on top of the cleaned engine (06-03) and the kept 06-01 view. 06-05 (gate b) can now re-freeze BOTH `W1-BASELINE.json` and `W2-BASELINE.json` on the cleaned + cursored engine on a cool machine, then gate the cursor alone at ≥10% W2 / W1 non-regress (D-14), with the D-15 ship-and-reframe fallback if <10% honestly.
- **Gate (b) is human-gated (cool machine):** the W2 re-freeze + verdict measurement is deferred to 06-05 per the thermal-drift lesson and the pending-todo W1 re-freeze. This plan does not run the perf gate; it lands the correctness-locked cursor.

## Self-Check: PASSED

- FOUND: `.planning/phases/06-bar-feed-window-copies-optional-slip-able/06-04-SUMMARY.md`
- FOUND commit: `d034ea3` (Task 1, test)
- FOUND commit: `00c5480` (Task 2, feat)

---
*Phase: 06-bar-feed-window-copies-optional-slip-able*
*Completed: 2026-06-24*
