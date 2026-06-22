---
phase: 02-margin-accounting-leverage
plan: 00
subsystem: testing
tags: [pytest, nyquist, wave0, tdd-stubs, e2e, margin, leverage]

# Dependency graph
requires:
  - phase: 01-instrument-value-object
    provides: Instrument value object + margin params the Phase-2 accounting tests will exercise
provides:
  - 13 collectible pytest.skip Wave 0 stubs covering every Phase-2 (Plans 02-06) -k/-m verify target
  - new tests/e2e/levered_long/ scenario directory + skipped e2e stub (Plan 06 converts to a real scenario)
  - Nyquist "test exists before code" gate is now satisfiable for every downstream RED step
affects: [02-01, 02-02, 02-03, 02-04, 02-05, 02-06, margin, leverage, shorts, liquidation, pair-trading]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 0 collectible-but-skipped stub: pytest.skip(\"Wave 0 stub — implemented in Phase 2 plan NN\") naming the converting plan"
    - "Folder-derived markers only — no decorator added (--strict-markers safe); -k targets embed the keyword in the function name"

key-files:
  created:
    - tests/e2e/levered_long/__init__.py
    - tests/e2e/levered_long/test_levered_long_scenario.py
  modified:
    - tests/unit/order/test_sizing_resolver.py
    - tests/unit/order/test_admission_rules.py
    - tests/unit/portfolio/test_cash_manager.py
    - tests/unit/portfolio/test_position_manager.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - tests/unit/portfolio/test_update_config.py

key-decisions:
  - "tests/e2e/levered_long/__init__.py created EMPTY (0 bytes) to mirror the existing tests/e2e/cash/__init__.py convention"
  - "Every stub function name embeds the required -k keyword verbatim so the downstream filter selects it (e.g. test_levered_fraction_wave0_stub for -k levered_fraction)"

patterns-established:
  - "Wave 0 contract: each downstream TDD/e2e plan converts its named skip stub into a real RED assertion, then GREEN"

requirements-completed: [MARGIN-01, MARGIN-02, MARGIN-03, LEV-01, LEV-02]

# Metrics
duration: 3min
completed: 2026-06-15
---

# Phase 2 Plan 00: Nyquist Wave 0 Stubs Summary

**13 collectible `pytest.skip` Wave 0 stubs (6 unit files + a new `tests/e2e/levered_long/` e2e stub) make every Phase-2 (Plans 02-06) `-k`/`-m` verify target select ≥1 test before any RED→GREEN cycle.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-15T11:06:17Z
- **Completed:** 2026-06-15T11:08:36Z
- **Tasks:** 1
- **Files modified:** 8 (6 modified, 2 created)

## Accomplishments
- Appended 12 skipped stub functions across 6 existing unit test files, each named so the downstream `-k` keyword selects it (`levered_fraction`, `leverage_cap`/`leverage_forced_one`/`over_margin`/`margin_reservation`/`levered_fraction_gate`, `locked_margin`, `scale_in_margin`/`one_leverage`/`partial_close_margin`, `maintenance_margin`/`margin_ratio`, `max_leverage`).
- Created the new `tests/e2e/levered_long/` directory with an empty `__init__.py` (mirroring `tests/e2e/cash/`) and a single skipped e2e stub `test_levered_long_scenario_wave0_stub` collectible under `-m e2e`.
- All 7 plan `--collect-only` verify commands exit 0 and each selects ≥1 test; no production code touched; no marker decorator added.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 skipped-stub test functions for every Phase-2 -k target** - `8b4b766` (test)

**Plan metadata:** committed with this SUMMARY (docs)

## Files Created/Modified
- `tests/unit/order/test_sizing_resolver.py` - +1 stub: `test_levered_fraction_wave0_stub` (→ Plan 02)
- `tests/unit/order/test_admission_rules.py` - +5 stubs: leverage_cap / leverage_forced_one / over_margin / margin_reservation / levered_fraction_gate (→ Plan 03)
- `tests/unit/portfolio/test_cash_manager.py` - +1 stub: `test_locked_margin_wave0_stub` (→ Plan 04)
- `tests/unit/portfolio/test_position_manager.py` - +3 stubs: scale_in_margin / one_leverage / partial_close_margin (→ Plan 04)
- `tests/unit/portfolio/test_portfolio_handler.py` - +2 stubs: maintenance_margin / margin_ratio (→ Plan 05)
- `tests/unit/portfolio/test_update_config.py` - +1 stub: `test_max_leverage_wave0_stub` (→ Plan 05)
- `tests/e2e/levered_long/__init__.py` - new empty package marker (mirrors `tests/e2e/cash/__init__.py`)
- `tests/e2e/levered_long/test_levered_long_scenario.py` - new file: 1 skipped e2e stub (→ Plan 06)

## Decisions Made
- `tests/e2e/levered_long/__init__.py` created EMPTY (0 bytes), matching the existing `tests/e2e/cash/__init__.py` which is also 0 bytes — no one-line docstring needed.
- All six unit files already `import pytest`, so no import additions were required.
- No marker decorator added anywhere — markers stay folder-derived (`tests/unit/<domain>/` → `unit`, `tests/e2e/` → `e2e`), preserving `--strict-markers`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. The plan's hint about adding `import pytest` "if absent" was inapplicable — all six unit files already imported it.

## Verification
- All 7 per-file `--collect-only` commands (the plan's `<automated>` verify) exit 0 and select ≥1 test (1 + 5 + 1 + 3 + 2 + 1 unit + 1 e2e = 13).
- `poetry run pytest tests/unit/order tests/unit/portfolio -q` → 378 passed, 13 skipped (existing tests unaffected; stubs SKIP).
- Full-suite `--collect-only` → 1037 tests collected, no `--strict-markers` error (no new marker introduced).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 0 complete: Plans 02-01/02-02 (Wave 1) and every downstream RED→GREEN cycle now have collectible `-k`/`-m` targets.
- Each converting plan (02 / 03 / 04 / 05 / 06) replaces its named `pytest.skip` body with the real RED assertion, then GREEN.
- No blockers. Test-only plan — re-baselines nothing; the BTCUSD oracle is untouched.

## Self-Check: PASSED
- All 8 files verified present on disk.
- Task commit `8b4b766` verified in git log.

---
*Phase: 02-margin-accounting-leverage*
*Completed: 2026-06-15*
