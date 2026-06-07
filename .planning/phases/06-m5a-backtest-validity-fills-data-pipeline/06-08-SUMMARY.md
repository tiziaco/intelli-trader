---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 08
subsystem: portfolio
tags: [dead-code, bar-struct, portfolio-handler, wr-06, gap-closure]

# Dependency graph
requires:
  - phase: 06-m5a-backtest-validity-fills-data-pipeline (plans 01-06)
    provides: M5-02 Bar struct (dict[str, Bar] Decimal payload) and the frozen M5a oracle (134 trades, final_equity 53103.01549885479)
provides:
  - PortfolioHandler with the dead/broken update_portfolios_market method deleted (pre-M5 close_price payload shape eradicated)
  - test_update_portfolios_market_value — production market-value path coverage under its correct name
affects: [phase-06 verification, phase-07, phase-08-oracle-refreeze]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/portfolio/test_portfolio_update.py

key-decisions:
  - "Rename (not delete) test_update_portfolios_market → test_update_portfolios_market_value: the test body always exercised the production method; the rename IS the UAT-mandated rewrite, preserving real coverage"
  - "No import cleanup needed: Any/Dict remain used by 15+ other sites in portfolio_handler.py"

patterns-established: []

requirements-completed: [M5-02]

# Metrics
duration: 6min
completed: 2026-06-06
---

# Phase 06 Plan 08: WR-06 Dead-Code Delete Summary

**Deleted the dead, broken `update_portfolios_market` method (pre-M5 `close_price` payload shape) from PortfolioHandler and renamed its namesake test to match the production method it actually calls — proven behavior-inert against the byte-exact M5a oracle.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-06T20:25:30Z
- **Completed:** 2026-06-06T20:31:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- UAT Gap 1 (WR-06) closed: `update_portfolios_market` (portfolio_handler.py:355-377) deleted — the method read `getattr(bar, 'close_price', None)` against the M5-02 `Bar` struct (which has `close`), so it would silently feed None prices into portfolio updates if ever called. It had zero production callers.
- Zero-reference grep gate passes: `update_portfolios_market` survives nowhere (not as def, call, or test name); `close_price` count in portfolio_handler.py is 0.
- `test_update_portfolios_market` renamed to `test_update_portfolios_market_value` with body and assertions byte-identical (cash == 980, total_market_value == 10, total_equity == 990, total_pnl == -10) — production-path coverage retained.
- Deletion proven behavior-inert (D-21 inert): oracle integration test 2 passed byte-exact (134 trades, final_equity 53103.01549885479); full suite 586 passed under `filterwarnings=["error"]`; mypy --strict clean (139 source files); tests/golden/ untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete update_portfolios_market; rename its namesake test** - `dca839c` (fix)
2. **Task 2: Oracle byte-exactness + full-suite + strict-typing gate** - verification only, no files modified

## Files Created/Modified
- `itrader/portfolio_handler/portfolio_handler.py` - Dead `update_portfolios_market` method deleted (25 lines removed); live `update_portfolios_market_value` and `get_global_health_report` untouched
- `tests/unit/portfolio/test_portfolio_update.py` - Test function renamed to `test_update_portfolios_market_value`; assertions unchanged

## Decisions Made
- Kept the `Any`/`Dict` typing imports: both remain used at 15+ other sites in the file, so the dead method's `Dict[str, Any]` annotation stranded nothing.
- The rename satisfies the UAT "removed or rewritten" instruction without discarding genuine coverage of the live run path.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Worktree pitfalls (shared `.venv` shadowing, Makefile `.env` include) were pre-documented; worked around with `PYTHONPATH="$PWD"` on pytest runs and direct `poetry run mypy itrader` instead of `make typecheck` (output: "Success: no issues found in 139 source files", equivalent to the `make typecheck` gate).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- WR-06 closed as a structural, behavior-inert deletion; the pre-M5 pandas-Series/`close_price` payload shape no longer exists anywhere in the codebase.
- Oracle remains frozen and byte-exact — no re-freeze performed (forbidden for this plan).
- Phase 06 gap-closure: this plan (06-08) complete; pairs with 06-07 (CR-01 parent gate) for phase verification re-run.

## Self-Check: PASSED

- itrader/portfolio_handler/portfolio_handler.py — FOUND
- tests/unit/portfolio/test_portfolio_update.py — FOUND
- Task 1 commit dca839c — FOUND

---
*Phase: 06-m5a-backtest-validity-fills-data-pipeline*
*Completed: 2026-06-06*
