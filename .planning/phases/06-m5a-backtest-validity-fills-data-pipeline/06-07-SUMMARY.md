---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 07
subsystem: execution
tags: [matching-engine, bracket-orders, oco, backtest, tdd]

# Dependency graph
requires:
  - phase: 06-m5a-backtest-validity-fills-data-pipeline
    provides: "MatchingEngine single matching path (D-13), same-bar bracket rule, Decimal-native matching, frozen M5a oracle (134 trades, final_equity 53103.01549885479)"
provides:
  - "CR-01 parent-filled gate: two-pass MatchingEngine.on_bar — parents/standalone evaluated and popped first; bracket children dormant while their parent_order_id still keys the book"
  - "Four regression tests locking the gate (limit-entry defect lock, same-bar limit-parent unlock, multi-bar dormancy lifecycle, stop-entry defect lock)"
  - "Golden oracle proven byte-exact post-fix (behavior-inert on the market-order-only SMA_MACD path)"
affects: [07-m5b-risk-layer, execution_handler, matching_engine]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Two-pass on_bar: pass 1 parents/standalone (fill + pop), pass 2 children gated on parent absence from the book — fill ordering parents-before-children by construction"]

key-files:
  created: []
  modified:
    - itrader/execution_handler/matching_engine.py
    - tests/unit/execution/test_matching_engine.py

key-decisions:
  - "Removed the step-3b post-hoc stable sort: pass-1-before-pass-2 list construction guarantees parents-before-children ordering structurally"
  - "Added defensive `if bracket is None: continue` narrowing in pass-2 arbitration for mypy --strict (unreachable by construction)"

patterns-established:
  - "Parent-dormancy check: `order.parent_order_id in self._resting` inside on_bar pass 2 — a never-resting parent does not gate (children-only books remain evaluable)"

requirements-completed: [M5-01]

# Metrics
duration: 12min
completed: 2026-06-06
---

# Phase 6 Plan 07: CR-01 Parent-Filled Bracket Gate Summary

**Two-pass MatchingEngine.on_bar gating bracket children on parent fill — a resting LIMIT/STOP entry now shields its SL/TP children from filling or OCO-cancelling, with the golden oracle proven byte-exact (behavior-inert fix)**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-06T20:17:52Z
- **Completed:** 2026-06-06T20:29:30Z
- **Tasks:** 2 (1 TDD implementation + 1 verification-only)
- **Files modified:** 2

## Accomplishments
- Closed UAT Gap 2 (CR-01, Critical): a BUY-LIMIT entry at 95 with a TP SELL-LIMIT at 110 no longer sees the TP fill on a rally bar while the entry never triggered — pre-fix this silently opened a reverse position from flat and orphaned the unprotected parent
- `on_bar` restructured into two passes: pass 1 fills parents/standalone orders and pops them from the book; pass 2 evaluates children only when `parent_order_id not in self._resting`
- All accepted semantics preserved unchanged: same-bar market-parent unlock (`test_parent_market_fill_and_child_stop_trigger_same_bar` passes with original assertions), STOP-beats-LIMIT sibling priority, children-only-book evaluability (parent never rested)
- Golden oracle byte-exact: 2 passed (134 trades, final_equity 53103.01549885479); full suite 590 passed (586 baseline + 4 new); mypy --strict clean (139 files); `tests/golden/` untouched — no re-freeze

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): lock parent-filled gate for bracket children** - `7e63dd3` (test)
2. **Task 1 (GREEN): gate bracket children on parent fill — CR-01** - `fc65dd2` (fix)
3. **Task 2: oracle byte-exactness + full-suite + strict-typing gate** - verification only, no commit (no files modified)

## TDD Gate Compliance

- RED gate: `7e63dd3` (test commit) — the two defect-lock tests (`test_limit_parent_resting_shields_children`, `test_stop_parent_resting_shields_children`) confirmed failing against pre-fix code (children filled while the parent rested)
- GREEN gate: `fc65dd2` (fix commit) — all 41 matching-engine tests green
- REFACTOR: not needed (the GREEN restructure already removed the redundant step-3b sort)

## Files Created/Modified
- `itrader/execution_handler/matching_engine.py` - `on_bar` two-pass restructure with the CR-01 parent-dormancy check; module-level "Same-bar bracket rule" docstring updated to document the parent-filled gate
- `tests/unit/execution/test_matching_engine.py` - new "CR-01 parent-filled gate" section with 4 regression tests (limit-entry defect lock, same-bar limit-parent unlock, multi-bar dormancy lifecycle, stop-entry defect lock)

## Decisions Made
- Removed the step-3b post-hoc stable sort rather than keeping it as a no-op guard: pass-1 fills precede pass-2 fills in the returned list by construction, so the parents-before-children contract is structural
- Added a defensive `if bracket is None: continue` in pass-2 bracket arbitration — unreachable by construction (pass-2 candidates are all children) but required for mypy --strict type narrowing of `Optional[OrderId]`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest resolved `itrader` to the main repo instead of the worktree**
- **Found during:** Task 1 (GREEN verification)
- **Issue:** The shared `.venv` (main repo, in-project) has `itrader` installed in editable mode pointing at the main repo path. Plain `python` imports resolved to the worktree (cwd first on sys.path), but `pytest` imports resolved to `/Users/tizianoiacovelli/Desktop/projects/intelli-trader/itrader/...` — tests silently ran against the unfixed main-repo source, masking the GREEN fix
- **Fix:** Prepended the worktree root to `PYTHONPATH` (`PYTHONPATH="$PWD" poetry run pytest ...`) for all test runs; no repo files modified
- **Verification:** In-pytest module-path probe confirmed the worktree file loads with the gate present; all 41 tests then green
- **Committed in:** n/a (environment workaround, no file change)

**2. [Rule 3 - Blocking] `make typecheck` fails in the worktree (missing gitignored `.env`)**
- **Found during:** Task 2 (strict-typing gate)
- **Issue:** The Makefile does `include .env` at the top; `.env` is gitignored and therefore absent from the worktree, so every make target aborts with "No rule to make target `.env`"
- **Fix:** Ran the target's underlying command directly: `poetry run mypy itrader` (relative path resolves to the worktree source)
- **Verification:** "Success: no issues found in 139 source files"
- **Committed in:** n/a (environment workaround, no file change)

### Observations (not deviations)

- The plan predicted Test 3's bar-A leg would fail RED; in fact bar A's geometry (high 108 < TP 110, low 96 > SL 90) triggers no child even pre-fix, so only Tests 1 and 4 failed RED. The defect is fully locked by those two tests; Tests 2 and 3 are regression locks for the unlock semantics. Tests written exactly as specified in the plan.

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking, environment-only, zero repo changes)
**Impact on plan:** None on scope — both were worktree-environment issues. Without deviation 1 the GREEN gate would have been falsely red (or worse, a broken fix falsely green).

## Issues Encountered
None beyond the two environment deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CR-01 closed: the matching engine's bracket semantics are now safe for non-MARKET primaries, unblocking Phase 7 (M5b risk layer) which builds on the matching engine
- Worktree gotcha worth knowing for future parallel executors in this repo: the shared editable install shadows worktree sources under pytest (use `PYTHONPATH="$PWD"`), and `make` targets need `.env` (gitignored) to exist

## Self-Check: PASSED

- SUMMARY.md exists and committed
- Commits verified: 7e63dd3 (RED), fc65dd2 (GREEN), 2d97b3c (docs)
- No file deletions vs base a525f3d; STATE.md/ROADMAP.md untouched; tree clean
- Final run: 43 passed (41 matching-engine + 2 oracle byte-exact)

---
*Phase: 06-m5a-backtest-validity-fills-data-pipeline*
*Completed: 2026-06-06*
