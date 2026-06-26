---
phase: 07-per-bar-metrics-timestamp-polish
plan: 01
subsystem: testing
tags: [functools, lru_cache, memoization, timestamp-alignment, perf, PERF-07]

# Dependency graph
requires:
  - phase: 06-perf-barfeed-cursor
    provides: "bar_feed.py _offset_alias @functools.cache memo precedent (D-01/PERF-06)"
provides:
  - "Bounded lru_cache(maxsize=32) memoization of _aligned timestamp-alignment math (D-01/PERF-07)"
  - "Three extension tests proving _aligned output equivalence, memo activity, and bounded memory"
affects: [07-02, 07-03, per-bar-metrics, oracle-byte-exactness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bounded hot-path memoization via @functools.lru_cache(maxsize=N) when the key space is unbounded (vs bare @functools.cache for bounded keys)"

key-files:
  created: []
  modified:
    - itrader/outils/time_parser.py
    - tests/unit/outils/test_time_parser.py

key-decisions:
  - "Used bounded @functools.lru_cache(maxsize=32) instead of bare @functools.cache because the `ts` key space is unbounded (~17.3k distinct per-bar timestamps) — a bare cache violates the SPEC bounded-memory constraint (D-01)"
  - "_aligned function body left byte-identical — only decorator + decision-tag comment + import added, preserving oracle byte-exactness (D-01)"

patterns-established:
  - "Bounded lru_cache for unbounded-key hot-path functions: cite the unbounded-key rationale, body-byte-unchanged, exception-not-cached, thread-safety, and deterministic-business-keys in the decision-tag comment"

requirements-completed: [PERF-07]

# Metrics
duration: 8min
completed: 2026-06-25
---

# Phase 7 Plan 01: _aligned Bounded-Memo Summary

**Memoized the per-bar `_aligned` timestamp-alignment math with a bounded `@functools.lru_cache(maxsize=32)` (body byte-unchanged), eliminating the intra-tick recompute of `astimezone`/`replace`/`total_seconds`/modulo that fired once per registered strategy per TIME event.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-25
- **Completed:** 2026-06-25
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `_aligned` is now decorated with bounded `@functools.lru_cache(maxsize=32)`; `import functools` added to `time_parser.py` (TABS file, indentation preserved).
- The 4-line `_aligned` body and its ~28-line docstring are byte-identical to the pre-edit version — `git diff` shows ONLY added decorator/comment/import lines (no deletions).
- Decision-tag comment cites all required points: D-01 (PERF-07), the unbounded-`ts`-key rationale for the bounded variant, body-byte-unchanged, exception-not-cached, thread-safe (locks internally) for live mode, deterministic business-value keys (no wall-clock).
- Three extension tests added inside the existing `tests/unit/outils/test_time_parser.py` (4-SPACE indentation, no new file):
  - T1 `test_aligned_equivalence_sampled_grid` — parametrized daily/intraday/weekly/7h-non-divisor alignment grid.
  - T2 `test_aligned_memo_active_and_bounded` — `maxsize == 32`, repeat call yields `hits >= 1`.
  - T3 `test_aligned_memo_bounded_currsize` — 150 distinct timestamps keep `currsize <= 32`.
- Full `test_time_parser.py` green (26 passed, 0 warnings under `filterwarnings=["error"]`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Memoize _aligned with bounded lru_cache(maxsize=32)** - `5ee4117` (perf)
2. **Task 2: Extend test_time_parser.py with equivalence + bounded-memo tests (T1-T3)** - `bad77ae` (test)

_Note: although both tasks carry `tdd="true"`, this plan splits the source change (Task 1) and its tests (Task 2) into separate tasks; the source memoization is a behavior-preserving decorator over a function already covered by `test_aligned_seam_midnight_relative`, and the new T1-T3 tests assert the memo behavior introduced by Task 1._

## Files Created/Modified

- `itrader/outils/time_parser.py` - Added `import functools`; decorated `_aligned` with `@functools.lru_cache(maxsize=32)` + decision-tag comment block (body byte-unchanged).
- `tests/unit/outils/test_time_parser.py` - Added T1/T2/T3 tests asserting alignment equivalence, memo activity (`hits >= 1`), and bounded memory (`maxsize == 32`, `currsize <= 32`).

## Decisions Made

- Bounded `lru_cache(maxsize=32)` over bare `cache`: the `ts` key space is unbounded (per-bar timestamps, ~17.3k distinct over a run), so an unbounded cache would violate the SPEC bounded-memory constraint. maxsize=32 gives >30x headroom over the distinct registered timeframes while staying few-KB bounded (D-01 / RESEARCH Gap A).
- Body left byte-identical to preserve oracle byte-exactness (Gate (a)), verified by Task 1 acceptance.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The worktree's `poetry` env was a fresh empty `.venv` (pydantic et al. not installed); ran `poetry install` once to populate it before running the verification/test gates. No code impact.

## Threat Flags

None - pure internal byte-exact hot-path memoization; no new trust boundary, no external-input surface, no new dependency (stdlib `functools`). Matches the plan's `<threat_model>` (T-07-01 accepted).

## Known Stubs

None.

## Next Phase Readiness

- `_aligned` memo is in place and proven bounded/active; Gate (a) oracle byte-exactness is validated downstream in Plan 03 (full-suite + oracle), not here.
- No blockers.

## Self-Check: PASSED

- FOUND: itrader/outils/time_parser.py (modified, `@functools.lru_cache(maxsize=32)` present)
- FOUND: tests/unit/outils/test_time_parser.py (T1/T2/T3 present, 26 tests green)
- FOUND: commit 5ee4117 (Task 1, perf)
- FOUND: commit bad77ae (Task 2, test)

---
*Phase: 07-per-bar-metrics-timestamp-polish*
*Completed: 2026-06-25*
