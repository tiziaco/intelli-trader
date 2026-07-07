---
phase: 04-paper-path-milestone-dod
plan: 04
subsystem: testing
tags: [paper-path, parity-gate, dod, milestone-gate, inertness, tz-normalization]

# Dependency graph
requires:
  - phase: 04-paper-path-milestone-dod (plan 02)
    provides: "run_paper_replay() synchronous offline paper driver + the 'paper' venue arm in LiveTradingSystem"
  - phase: 04-paper-path-milestone-dod (plan 03)
    provides: "scripts/run_live_paper.py worker + start/stop/status lifecycle coverage"
provides:
  - "tests/integration/test_paper_parity.py — the DoD paper-parity gate (PAPER-04/COV-01): drives the live-paper path AND a fresh backtest on the same golden dataset in one test and asserts trades + equity are EXACTLY equal (frame-equal, no tolerance), tz-normalized to UTC"
  - "inertness-gate extension: _FORBIDDEN now includes itrader.price_handler.providers.replay_provider so the backtest hot path can never pull the paper replay machinery (D-12)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Parity gate re-anchored to 'paper == a FRESH in-test backtest' (D-01 option b): construct BOTH systems in-test, diff post-run reporting.frames — NO output/ round-trip, NOT pinned to the frozen equity artifact, survives a backtest-loop rework"
    - "tz-normalize the tz-sensitive datetime columns (entry_date/exit_date/timestamp) to UTC via pd.to_datetime(col, utc=True) before the exact diff — paper stamps UTC (live-feed contract), backtest stamps Europe/Paris (config.TIMEZONE); same instant, normalized"
    - "Vacuous-pass guard (T-04-08): assert paper trade count > 0 so a zero-trade parity cannot pass silently"

key-files:
  created:
    - tests/integration/test_paper_parity.py
  modified:
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "Parity gate anchored to the fresh backtest, NOT the frozen equity number (D-01) — grep-clean of the frozen artifact tokens; the transitive lock stays held by the separate unchanged oracle test"
  - "tz-normalization is load-bearing: without UTC-normalizing entry_date/exit_date/timestamp the exact diff FALSELY fails on the Europe/Paris-vs-UTC label for the same instant"
  - "_FORBIDDEN extended to replay_provider (D-12); test_backtest_oracle.py left UNTOUCHED (byte-exact 134 / 46189.87730727451 stays the separate transitive anchor)"

requirements-completed: [PAPER-04, COV-01]

# Metrics
duration: 5min
completed: 2026-07-02
---

# Phase 4 Plan 04: Paper-Parity DoD Gate Summary

**Ships the milestone Definition of Done — the paper-parity gate: ONE integration test drives the live-paper path (`run_paper_replay()`) AND a fresh backtest over the same golden dataset, then asserts their trade logs and equity curves are EXACTLY equal (frame-equal, no tolerance), tz-normalized to UTC; plus an inertness-gate extension forbidding the replay provider on the backtest hot path.**

## Performance
- **Duration:** ~5 min
- **Completed:** 2026-07-02
- **Tasks:** 2
- **Files created:** 1, modified: 1

## Accomplishments
- Added `tests/integration/test_paper_parity.py` (4-space, `integration` auto-marked by folder): builds BOTH sides in one test — the paper side via `LiveTradingSystem(exchange='paper')` + `run_paper_replay()` (04-02), the comparand via a FRESH `BacktestTradingSystem(exchange='csv', start='2018-01-01', end='2026-06-03').run(print_summary=False)` (D-01 option b, no `output/` round-trip) — using the identical golden SMA_MACD literals (`FractionOfCash(Decimal("0.95"))`, `LONG_ONLY`, `allow_increase=False`). Builds trade/equity frames with the shared `reporting.frames` builders, tz-normalizes the datetime columns to UTC (the tz trap), sorts, then asserts trade count + equity point count equal AND `pdt.assert_frame_equal(check_exact=True, check_like=True)` over the FULL `TRADE_COLUMNS` and `EQUITY_COLUMNS`. Guards the vacuous-pass case with `assert len(paper_trades) > 0` (T-04-08).
- The gate is anchored to the fresh backtest, NOT the frozen `46189…` artifact (D-01): it survives a future backtest-loop rework with no re-freeze; the transitive lock to the frozen number stays held by the separate, unchanged `test_backtest_oracle.py`.
- Extended the `_FORBIDDEN` inertness tuple in `tests/integration/test_okx_inertness.py` with `itrader.price_handler.providers.replay_provider` (D-12) — the paper replay provider is lazy-imported inside the `exchange='paper'` arm only and must never touch the backtest import graph. `test_backtest_oracle.py` left UNTOUCHED (byte-exact 134 / 46189.87730727451 confirmed still green + `git diff --exit-code` clean).

## Task Commits
1. **Task 1: test_paper_parity.py — the DoD gate (paper == fresh backtest, exact)** — `729ff86b` (test)
2. **Task 2: Lock inertness + confirm the recurring milestone gate (D-12)** — `c38bb131` (test)

## Files Created/Modified
- `tests/integration/test_paper_parity.py` (created) — the PAPER-04/COV-01 DoD parity gate.
- `tests/integration/test_okx_inertness.py` (modified) — `_FORBIDDEN` extended with `replay_provider`.

## Decisions Made
- None beyond the plan's locked decisions (D-01/D-02/D-03/D-12). Gate anchored to the fresh backtest; tz-normalized; replay provider forbidden on the hot path; oracle untouched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded the parity-test docstring to clear a false-positive grep gate**
- **Found during:** Task 1 acceptance verification
- **Issue:** The docstring cited the frozen artifact by value (`46189…`) and `tests/golden/` in prose explaining the D-01 re-anchor rationale, which tripped the acceptance gate `grep -n "46189\|tests/golden\|golden_dir"` (expected to return nothing — the "not pinned to the frozen artifact" proof).
- **Fix:** Reworded the prose to "the committed frozen equity artifact" / "the frozen golden artifact directory" / "the frozen equity number" — same meaning, no forbidden tokens. No test-behavior change (identical to the 04-02/04-03 prose-token discipline).
- **Files modified:** tests/integration/test_paper_parity.py
- **Commit:** 729ff86b

## Issues Encountered
None.

## User Setup Required
None — the parity gate is fully offline, single process, in-thread (D-03); no network, no credentials.

## Next Phase Readiness
- The milestone DoD is met: the live-paper path reproduces a fresh backtest run on the golden dataset EXACTLY (trades + equity, no tolerance), the gate survives a future backtest-loop rework, and the backtest oracle + hot-path inertness remain untouched.
- **Non-blocking flag (per plan `<success_criteria>`):** ROADMAP.md + REQUIREMENTS.md still carry the STALE Phase-4 framing (PAPER-01/02/04 "byte-exact vs the oracle 46189…" + RUN-01 "Postgres LISTEN/NOTIFY in Phase 4"). Per D-01/D-04/D-05/D-08 these are revised (parity re-anchored to a fresh backtest, SimulatedExchange reused as-is, apply_costs dropped, channel deferred to Phase 5). Flag for a follow-up text update — this phase is not blocked on it.

## Self-Check: PASSED
- `tests/integration/test_paper_parity.py` — FOUND (created)
- `tests/integration/test_okx_inertness.py` — FOUND (modified)
- Commit `729ff86b` — FOUND
- Commit `c38bb131` — FOUND
- `poetry run pytest tests/integration/test_paper_parity.py tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py` — 5 passed — CONFIRMED
- `grep "46189\|tests/golden\|golden_dir" test_paper_parity.py` — CLEAN — CONFIRMED
- `git diff --exit-code tests/integration/test_backtest_oracle.py` — no changes — CONFIRMED

---
*Phase: 04-paper-path-milestone-dod*
*Completed: 2026-07-02*
