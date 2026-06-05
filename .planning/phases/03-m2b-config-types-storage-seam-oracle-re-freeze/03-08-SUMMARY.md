---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 08
subsystem: testing
tags: [pytest, unittest, test-restructure, git-mv, conftest, markers, golden-master]

# Dependency graph
requires:
  - phase: 03-01
    provides: M1 test skeleton (root conftest, DIR_MARKERS, golden/ + oracle), Wave-0 characterization stubs
  - phase: 03-05
    provides: config/ Pydantic collapse (ExchangeConfig/PortfolioConfig consumed by test imports)
  - phase: 03-06
    provides: portfolio_handler subdomain packages (position/transaction/cash/metrics) that unit tests import
provides:
  - "tests/ tree split by TYPE (unit/ mirrors the package; integration/ holds cascade + smoke + oracle)"
  - "Folder-derived TYPE-marker auto-marking (unit/integration+slow) in layered conftests, single registration home"
  - "All 29 remaining unittest.TestCase files converted to pytest functions/fixtures, one file per commit"
  - "tests/golden/ + oracle moved with the tree (history preserved); golden fixtures repointed"
  - "testpaths + 8 Makefile test-* targets pointed at tests/; tests/README.md documenting the D-15 boundary"
affects: [03-09, future test authoring, oracle re-freeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TYPE-axis test tree: tests/unit/<domain>/ + tests/integration/, marker derived from folder not domain"
    - "Layered conftests: root (cross-cutting global_queue + auto-marking), unit (anchor), integration (golden + backtest_engine)"
    - "unittest->pytest: TestCase->functions, setUp->fixture with yield teardown that drains/closes queues (strict filterwarnings stays intact)"
    - "Harness fixtures (SimpleNamespace or small _Harness class) replace shared setUp/helper methods"

key-files:
  created:
    - tests/conftest.py
    - tests/unit/conftest.py
    - tests/integration/conftest.py
    - tests/README.md
  modified:
    - pyproject.toml
    - Makefile
    - tests/integration/test_backtest_oracle.py

key-decisions:
  - "Marker registration home = pyproject.toml markers list (single home); conftest only APPLIES folder-derived markers, never registers"
  - "Markers reconciled to the TYPE axis only (unit/integration/slow); the M1 domain markers (portfolio/events/orders/execution/strategy) dropped"
  - "test_backtest_smoke + test_event_wiring + test_execution_handler_routing classified integration (cross-component); everything else unit"
  - "Oracle/D-16/D-17 numeric re-freeze left untouched (belongs to 03-09); this plan only repoints the oracle's test/golden path to tests/golden"

patterns-established:
  - "One file per conversion commit, asserting identical per-file AND whole-suite collected count (346) at every commit"
  - "Resource leaks fixed at the source via yield-teardown queue drains; filterwarnings=['error'] never widened"

requirements-completed: [M2-12]

# Metrics
duration: ~95min
completed: 2026-06-05
---

# Phase 03 Plan 08: Bulk pytest Restructure + Conversion Summary

**`test/` moved to `tests/{unit,integration}` by TYPE via history-preserving git mv, M1's domain DIR_MARKERS reworked to folder-derived TYPE markers in layered conftests, and all 29 remaining `unittest.TestCase` files converted to pytest one-file-per-commit at a constant 346 collected tests with the behavioral oracle byte-exact throughout.**

## Performance

- **Duration:** ~95 min
- **Completed:** 2026-06-05
- **Tasks:** 2 (Task 1 move/marker rework; Task 2 = 29 per-file conversions)
- **Files moved/modified:** 47 git-mv renames + 4 config/harness files (pyproject, Makefile, root + integration + unit conftests, README) + 29 converted test files

## Accomplishments
- Entire `test/` tree relocated to `tests/` via `git mv` (47 R100 renames; `git log --follow` history preserved), split on the TYPE axis: `tests/unit/<domain>/` mirrors the package, `tests/integration/` holds the full-cascade + run-path smoke + golden oracle.
- M1's path-segment **domain** `DIR_MARKERS` reworked to folder-derived **TYPE** auto-marking (`tests/unit/`→`unit`, `tests/integration/`→`integration`+`slow`) in layered root/unit/integration conftests; golden-path fixtures repointed to `tests/golden/`.
- `pyproject.toml` `testpaths` → `["tests"]`, `markers` reconciled to the TYPE axis (single registration home), and the 8 Makefile `test-*` targets repointed to `tests/...`.
- All 29 `unittest.TestCase` files converted to pytest functions + fixtures, ONE file per commit, with the per-file AND whole-suite `--collect-only` count held constant (346) and the file's tests green before each commit. `filterwarnings=["error"]` never widened — `setUp`/`tearDown` became `yield` fixtures that drain queues at teardown.

## Task Commits

**Task 1 — move + marker rework:**
1. `33c3281` test: git mv test/ -> tests/ split by TYPE, folder-derived markers (renames only — see Deviation 1)
2. `6a623ae` test: apply move content edits dropped by Task 1 staging (Rule 1 fix — pyproject/Makefile/conftest/oracle content)

**Task 2 — 29 per-file unittest->pytest conversions (one commit each):**
3. `4d89438` test_transaction_init (1/29)
4. `e102b02` test_strategy (2/29)
5. `db5c101` test_open_position (3/29)
6. `7f280fa` test_multiple_buy (4/29)
7. `8aaf8f8` test_multiple_sell (5/29)
8. `4e004da` test_events (6/29)
9. `554d06e` test_bar_event_ohlc (7/29)
10. `6aa3daa` test_fill_event_schema (8/29)
11. `4f8bd3c` test_order_event_schema (9/29)
12. `b308509` test_order_command_enum (10/29)
13. `c0bccd2` test_order_handler (11/29)
14. `2c7e7f4` test_stop_limit_orders (12/29)
15. `d81b046` test_on_signal (13/29)
16. `7fb09b3` test_order_manager (14/29)
17. `9893887` test_order_storage (15/29)
18. `d5299df` test_execution_handler (16/29)
19. `68b280a` test_matching_engine (17/29)
20. `72dc488` test_simulated_exchange routing class (18/29)
21. `40781fe` test_execution_handler_routing (19/29)
22. `ceba3f6` test_event_wiring (20/29)
23. `27c9e2e` test_on_fill_status_guard (21/29)
24. `4d63fa7` test_money_decimal (22/29)
25. `166a700` test_portfolio_update (23/29)
26. `c29bb20` test_portfolio (24/29)
27. `e144408` test_cash_manager (25/29)
28. `bea3c07` test_transaction_manager (26/29)
29. `95020c8` test_metrics_manager (27/29)
30. `c0d78a8` test_portfolio_handler (28/29)
31. `d86c092` test_position_manager (29/29)

## Files Created/Modified
- `tests/conftest.py` (moved + rewritten) — folder-derived TYPE-marker auto-marking + the cross-cutting `global_queue` fixture.
- `tests/unit/conftest.py` (new) — unit-layer anchor documenting the D-15 boundary.
- `tests/integration/conftest.py` (new) — golden-path fixtures repointed to `tests/golden/` + the `backtest_engine` factory.
- `tests/README.md` (new) — documents the unit/integration TYPE split and marker registration home.
- `pyproject.toml` — `testpaths=["tests"]`; markers reduced to `unit`/`integration`/`slow`.
- `Makefile` — 8 `test-*` targets repointed to `tests/...` (domain targets now point at `tests/unit/<domain>/`).
- `tests/integration/test_backtest_oracle.py` — golden path `test/golden` → `tests/golden`; docstring/comment references updated.
- 29 converted test files under `tests/unit/...` + `tests/integration/...`.

## Decisions Made
- **Single marker home = `pyproject.toml`.** The conftest only *applies* markers (folder-derived); registration (the `--strict-markers` source of truth) lives solely in the `markers` list. Never both.
- **Markers reduced to the TYPE axis.** M1's domain markers (portfolio/events/orders/execution/strategy) were no longer applied by the reworked conftest, so they were removed from the registry to keep `--strict-config`/`--strict-markers` clean.
- **Integration classification (D-15).** Moved `test_backtest_smoke` (M1 mislabel), `test_event_wiring`, and `test_execution_handler_routing` to `tests/integration/` (each drives more than one collaborating component); all other suites are unit.
- **Oracle re-freeze deferred.** D-16/D-17 numeric re-freeze (remove xfail/tolerance, byte-exact numeric assert) is plan 03-09's job. This plan only repoints the oracle's `test/golden` path to `tests/golden`; the existing `xfail` on `test_oracle_numeric_values` is preserved untouched.
- **Per-file harness fixtures.** Shared `setUp`/helper methods became fixtures returning a `SimpleNamespace` or a small underscore-prefixed `_Harness` class (uncollected) to preserve the exact construction behavior while adding `yield` teardown that drains queues.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 1 commit recorded renames but dropped all content edits**
- **Found during:** Task 2 wrap-up (final clean-state verification before SUMMARY).
- **Issue:** Task 1's staging command `git add -A tests test pyproject.toml Makefile` aborted on the nonexistent `test` pathspec after the tree was already moved. Commit `33c3281` therefore captured only the git-mv RENAMES (conftest + oracle committed with their OLD content via rename detection) and never staged the CONTENT edits: `pyproject.toml` kept `testpaths=["test"]`, the 8 Makefile targets kept `test/`, the root conftest kept the M1 domain `DIR_MARKERS` (referencing the now-deleted `test/golden`), and the oracle test kept the `test/golden` path. The working tree was correct throughout (pytest reads the working copy, so the suite stayed green at every commit), but a fresh checkout of `33c3281`..`d86c092` would have collected 0 items and the conftest golden fixtures would point at a deleted directory.
- **Fix:** Committed the intended Task 1 content as a dedicated corrective commit: `pyproject` testpaths→`tests` + TYPE-axis markers, 8 Makefile targets→`tests/`, root conftest reworked to folder-derived TYPE auto-marking + `global_queue` only, oracle golden path→`tests/golden`.
- **Files modified:** `pyproject.toml`, `Makefile`, `tests/conftest.py`, `tests/integration/test_backtest_oracle.py`.
- **Verification:** `git show HEAD:pyproject.toml` now shows `testpaths=["tests"]`; committed conftest has 0 `DIR_MARKERS`; clean-tree `poetry run pytest` collects 346 (345 passed + 1 xfailed); `make typecheck` clean; oracle behavioral identity byte-exact.
- **Committed in:** `6a623ae`.

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in own prior commit's staging).
**Impact on plan:** The fix restores the committed tree to the plan's intended Task 1 state with no scope change. Per-file conversion commits (Task 2) were unaffected (they staged individual files explicitly). No scope creep.

## Issues Encountered
- The `git mv` left empty source directories; removed the empty `test/**` dirs with `find -type d -empty -delete` after the moves (untracked, safe).
- Several files carried unused imports from earlier refactors (e.g. `FillDecision`/`CancelDecision` in `test_matching_engine`, `Portfolio`/`Position`/`PositionSide` in `test_portfolio_update`, the `OrderStorage` ABC in `test_order_storage`); dropped them during conversion. Collected counts and behavior unchanged.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `tests/` is fully pytest-native and TYPE-split; `make test`/`make test-unit`/`make test-integration` and the domain targets all run.
- Ready for plan 03-09 (oracle re-freeze): the oracle test already reads `tests/golden/` and stays byte-exact behaviorally; D-16/D-17 numeric re-freeze remains the only outstanding oracle work.
- No blockers.

---
*Phase: 03-m2b-config-types-storage-seam-oracle-re-freeze*
*Completed: 2026-06-05*

## Self-Check: PASSED
- All created files present (tests/conftest.py, tests/unit/conftest.py, tests/integration/conftest.py, tests/README.md, 03-08-SUMMARY.md).
- All sampled commit hashes resolve (33c3281, 6a623ae, 4d89438, d86c092, 95020c8).
- Clean-tree suite: 345 passed + 1 xfailed (346 collected, unchanged); make typecheck clean; oracle behavioral identity byte-exact.
