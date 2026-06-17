---
phase: 05-engine-native-trailing-stops
plan: 00
subsystem: testing
tags: [nyquist, pytest, trailing-stop, scaffolding, matching-engine, e2e]

# Dependency graph
requires:
  - phase: 04-liquidation-cross-validation-re-baseline
    provides: completed accounting core (margin/shorts/liquidation) the trailing subsystem builds on
provides:
  - 7 collectible (pytest.skip) Wave-0 test stubs covering every Phase-5 -k/-m verify selector
  - long AND short dedicated stubs for matching-engine ratchet, e2e scenarios
  - the compound `-k "trailing and bracket"` selector target used by 05-03 Task 1 (D-TRAIL-3/D-TRAIL-5)
affects: [05-01, 05-02, 05-03, trailing-stop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Nyquist Wave-0: collectible pytest.skip stubs so every later -k/-m selector collects >=1 before RED"
    - "Folder-derived markers only (no decorator) under --strict-markers"

key-files:
  created:
    - tests/unit/execution/test_matching_engine_trailing.py
    - tests/unit/order/test_trailing_validation.py
    - tests/unit/order/test_trailing_bracket.py
    - tests/e2e/trailing_long/__init__.py
    - tests/e2e/trailing_long/test_trailing_long_scenario.py
    - tests/e2e/trailing_short/__init__.py
    - tests/e2e/trailing_short/test_trailing_short_scenario.py
  modified: []

key-decisions:
  - "Trailing-long unit stub lives in the NEW test_matching_engine_trailing.py (per plan <files>), so the AC-line-109 selector is run directory-scoped like all other ACs"

patterns-established:
  - "Wave-0 stub bodies are a single pytest.skip with a per-plan provenance message (05-01/05-02/05-03)"
  - "Long and short each get a dedicated stub — Phase-3 short coverage does not transfer"

requirements-completed: [TRAIL-01, TRAIL-02, TRAIL-03]

# Metrics
duration: 6min
completed: 2026-06-17
---

# Phase 05 Plan 00: Wave-0 Nyquist Trailing Scaffolding Summary

**7 collectible pytest.skip stubs (6 unit + new tests/e2e/trailing_long & trailing_short e2e leaves) so every Phase-5 -k/-m verify selector — including the compound `-k "trailing and bracket"` 05-03 uses — collects >=1 test before any RED step; test-only, oracle byte-exact.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-17T06:49Z
- **Completed:** 2026-06-17
- **Tasks:** 2
- **Files modified:** 7 created

## Accomplishments
- Created `test_matching_engine_trailing.py` with 6 skip stubs: ratchet long/short, next_bar activation, gap-through long/short, OCO sl-vs-tp.
- Created `test_trailing_validation.py` (3 D-TRAIL-7 non-viable-trail reject stubs) and `test_trailing_bracket.py` (2 D-TRAIL-3/D-TRAIL-5 bracket stubs whose names match BOTH `trailing` and `bracket`).
- Created `tests/e2e/trailing_long/` and `tests/e2e/trailing_short/` e2e leaves with dedicated long/short stubs (Phase-3 short coverage does not transfer).
- Verified every RESEARCH Test Map selector collects >=1 (directory-scoped, as every AC is phrased): `trailing and long/short/next_bar/gap/oco`, `trailing and reject`, the compound `trailing and bracket` (collects 2 across the suite), and e2e `trailing_long`/`trailing_short`.

## Task Commits

1. **Task 1: Collectible unit stubs (matching/validation/bracket)** - `d1901b9` (test)
2. **Task 2: Collectible e2e leaves (trailing long + short)** - `3ab3ab9` (test)

## Files Created/Modified
- `tests/unit/execution/test_matching_engine_trailing.py` - 6 matching-engine ratchet/gap/oco skip stubs (4-space).
- `tests/unit/order/test_trailing_validation.py` - 3 D-TRAIL-7 reject skip stubs (4-space).
- `tests/unit/order/test_trailing_bracket.py` - 2 bracket-declaration skip stubs, names match `trailing and bracket` (4-space).
- `tests/e2e/trailing_long/{__init__.py,test_trailing_long_scenario.py}` - e2e long leaf + skip stub.
- `tests/e2e/trailing_short/{__init__.py,test_trailing_short_scenario.py}` - dedicated e2e short leaf + skip stub.

## Decisions Made
- Placed the trailing-long unit stub in the NEW `test_matching_engine_trailing.py` (the plan's own `<files>` list), not in the pre-existing `test_matching_engine.py`. See Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Plan inconsistency] AC line 109 pins the single file `test_matching_engine.py`; the stub belongs in the new file**
- **Found during:** Task 1 (unit stubs)
- **Issue:** Acceptance criterion line 109 reads `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and long" ... collects >=1`, but the plan's `<files>` and `<action>` create the trailing-long stub in the NEW `test_matching_engine_trailing.py`. Run against the single pre-existing file the selector collects 0; putting a trailing stub into the pre-existing file would contradict the plan's explicit file targets.
- **Fix:** Kept the stub in `test_matching_engine_trailing.py` (per the plan's `<files>`) and verified the selector directory-scoped — `poetry run pytest tests/unit/execution -k "trailing and long" --collect-only` collects 2 — which matches how every other AC (lines 110-114) is phrased and how the 05-02 selector will actually run.
- **Files modified:** tests/unit/execution/test_matching_engine_trailing.py
- **Verification:** `tests/unit/execution -k "trailing and long" --collect-only` → 2 collected; the AC intent ("the selector collects >=1") is satisfied.
- **Committed in:** d1901b9 (Task 1 commit)

---

**Total deviations:** 1 (plan-internal AC/file-path inconsistency, resolved in favor of the plan's `<files>`)
**Impact on plan:** No scope creep. The Nyquist contract (every Phase-5 selector collects >=1) is fully satisfied; the only adjustment is reading the trailing-long AC directory-scoped to match its sibling ACs and the plan's own file targets.

## Issues Encountered
- `tests/golden` contains only docs + CSV fixtures (no test functions) — the byte-exact oracle gate lives in `tests/integration` (16 passed). Verified there instead. No impact.

## Verification Results
- All 7 stub files collect; every Phase-5 verify selector collects >=1 (unit + e2e + compound `trailing and bracket`).
- Full suite: **1146 passed, 13 skipped** (the new stubs skip); integration oracle 16 passed (byte-exact held — test-only change).
- No undeclared-marker collection error; no `backtesting`/`backtrader` import under tests/ (filterwarnings=["error"] intact).

## Threat Surface
No new external/network/auth surface (per plan threat model T-05-01). Test scaffolding only; strict-marker contract preserved (folder-derived markers, no decorators).

## Self-Check: PASSED
- All 7 created files exist on disk.
- Both task commits present in git log (d1901b9, 3ab3ab9).

## Next Phase Readiness
- The Nyquist sampling net is in place: 05-01 (validation), 05-02 (matching ratchet), 05-03 (bracket + e2e) each have a collectible selector target before their RED step.
- No `<automated>MISSING ...>` gate is needed by any later Phase-5 task.

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
