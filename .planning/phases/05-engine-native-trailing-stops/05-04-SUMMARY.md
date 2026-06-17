---
phase: 05-engine-native-trailing-stops
plan: 04
subsystem: testing
tags: [cross-validation, trailing-stop, backtesting.py, backtrader, re-baseline, owner-sign-off, TRAIL-03, D-TRAIL-1]

# Dependency graph
requires:
  - phase: 05-engine-native-trailing-stops
    plan: 02
    provides: MatchingEngine TRAILING_STOP ratchet core (closed-bar-extreme HWM/LWM, gap-aware fill, OCO)
  - phase: 05-engine-native-trailing-stops
    plan: 03
    provides: end-to-end trailing-SL declaration (PercentFromFill trail descriptor, fill-anchored bracket, long+short e2e)
provides:
  - scripts/cross_validate_trailing.py — standalone sibling orchestrator (TOLERANCE=0.01, trade-primary/metric-secondary, reuses reconcile.py verbatim)
  - scripts/crossval/trailing_run.py — iTrader white-box trailing runner (synthetic TRAILUSD)
  - scripts/crossval/backtesting_py_trailing_run.py — backtesting.py TrailingStrategy oracle runner (SCRIPT-ONLY)
  - scripts/crossval/backtrader_trailing_run.py — backtrader StopTrail oracle runner (SCRIPT-ONLY)
  - tests/golden/CROSS-VALIDATION-TRAILING.md — evidence report (trade table, metric reconciliation, A1 resolution, LEGITIMATE-DIFFERENCE disposition, SIGNED owner sign-off)
  - Owner-signed freeze of this phase's OWN trailing golden re-baseline (TRAIL-03, separate from the Phase-4 accounting core)
affects: [trailing-stop, phase-5-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standalone sibling cross-val orchestrator mirroring scripts/cross_validate_accounting.py — does NOT modify the base cross_validate.py; reuses scripts/crossval/reconcile.py (align_trades / build_metric_table / recompute_headline / flag_divergences) verbatim"
    - "Oracle imports (backtesting / backtrader) are SCRIPT-ONLY under scripts/crossval/ — NEVER under tests/ (D-10 / T-05-09, keeps filterwarnings=['error'])"
    - "Owner-gated, manual re-baseline freeze: a result-changing subsystem golden freezes ONLY after explicit owner sign-off (name+date) in the evidence report's ## Owner Sign-Off block — never auto-approvable (workflow.auto_advance=false, T-05-10)"

key-files:
  created:
    - scripts/cross_validate_trailing.py
    - scripts/crossval/trailing_run.py
    - scripts/crossval/backtesting_py_trailing_run.py
    - scripts/crossval/backtrader_trailing_run.py
    - tests/golden/CROSS-VALIDATION-TRAILING.md
  modified:
    - .planning/phases/05-engine-native-trailing-stops/05-04-PLAN.md

key-decisions:
  - "A1 oracle trailing API CONFIRMED at runner-implementation time: backtesting.py 0.6.5 TrailingStrategy/set_trailing_sl/set_trailing_pct (CLOSE-basis) and backtrader 1.9.78.123 bt.Order.StopTrail/StopTrailLimit + trailpercent (CLOSE-basis); both runners force-match an EXACT percent-of-close ratchet"
  - "high-vs-close trail basis gap (D-TRAIL-1: iTrader trails off the closed-bar HIGH/LOW, both oracles off the CLOSE) dispositioned LEGITIMATE-DIFFERENCE — iTrader's closed-bar-extreme behavior is CORRECT per TRAIL-02; the scenario neutralizes the gap (high==close on every ratcheting bar) so trade-level reconciliation is EXACT"
  - "This phase's OWN result-changing trailing golden re-baseline freezes ONLY after explicit owner sign-off — APPROVED 2026-06-17 by tiziaco (tiziano.iaco@gmail.com), 0 BUG rows; the tests/e2e/{trailing_long,trailing_short}/ white-box leaves are the regression lock"

patterns-established:
  - "Sibling cross-val orchestrator + per-engine runners with verbatim reconcile.py reuse"
  - "Manual owner-gated re-baseline freeze via signed evidence-report sign-off block"

requirements-completed: [TRAIL-03]

# Metrics
duration: ~40min
completed: 2026-06-17
---

# Phase 05 Plan 04: Trailing-Stop Cross-Validation + Owner-Gated Re-Baseline Freeze Summary

**The engine-native trailing stop (TRAIL-03) is cross-validated against both gating oracles — a standalone sibling orchestrator (`scripts/cross_validate_trailing.py`, reusing `reconcile.py` verbatim) + per-engine runners (iTrader white-box on synthetic `TRAILUSD`; backtesting.py `TrailingStrategy` and backtrader `StopTrail`, both SCRIPT-ONLY) reconcile EXACTLY at the trade level (single trade, exit at the ratcheted 100.8 = 112 HWM × 0.90, PnL +8.0) with all 8 headline metrics within 1%; the high-vs-close trail-basis gap (D-TRAIL-1) is documented as a LEGITIMATE-DIFFERENCE (iTrader's closed-bar-extreme is correct per TRAIL-02), 0 BUG; A1 oracle API CONFIRMED at runner time; and this phase's OWN result-changing trailing golden re-baseline was FROZEN under explicit owner sign-off (tiziaco, 2026-06-17) — SMA_MACD spot oracle byte-exact (134 / 46189.87730727451), mypy --strict clean, determinism byte-identical.**

## Performance

- **Duration:** ~40 min (across Task 1 autonomous build + Task 2 blocking owner checkpoint + continuation freeze)
- **Completed:** 2026-06-17
- **Tasks:** 2 (Task 1 auto; Task 2 blocking human-verify checkpoint, owner-APPROVED)
- **Files:** 5 created (4 scripts + 1 evidence report), 1 modified (the plan, verify-command fix)

## Accomplishments

- **Standalone sibling cross-val orchestrator** (`scripts/cross_validate_trailing.py`) — mirrors `scripts/cross_validate_accounting.py` (`TOLERANCE = 0.01`, trade-level PRIMARY / metric-level SECONDARY), reuses `scripts/crossval/reconcile.py` (`align_trades` / `build_metric_table` / `recompute_headline` / `flag_divergences`) verbatim, and does NOT modify the base `cross_validate.py`.
- **iTrader white-box trailing runner** (`scripts/crossval/trailing_run.py`) — declares a LONG 10% PERCENT trailing-SL bracket on a SYNTHETIC ticker (`TRAILUSD`, NEVER BTCUSD), drives the real engine: market BUY fills at next-bar open (100), the engine-native `TRAILING_STOP` rests seeded from the entry fill (D-TRAIL-3), ratchets up across rising closed-bar highs, and a single sharp drop triggers the RATCHETED level (112 HWM × 0.90 = 100.8).
- **Two oracle runners (SCRIPT-ONLY)** — `backtesting_py_trailing_run.py` (backtesting.py `TrailingStrategy` / `set_trailing_sl` / exact percent-of-close ratchet) and `backtrader_trailing_run.py` (backtrader `StopTrail` / `trailpercent` / exact percent-of-close ratchet). Oracle imports appear ONLY under `scripts/`, never under `tests/` (D-10 / T-05-09).
- **A1 RESOLUTION (verified at runner time):** both oracles trail off the CLOSE and activate next bar — backtesting.py 0.6.5 `TrailingStrategy.next()` ratchets `trade.sl = max(trade.sl, Close - atr*n)`; backtrader 1.9.78.123 `StopTrail`/`StopTrailLimit` (enum 5/6) ratchet off the latest price. Both runners force-match an EXACT percent-of-close distance. iTrader trails off the closed-bar HIGH (D-TRAIL-1) — the gap is neutralized by the crafted scenario.
- **Evidence report** (`tests/golden/CROSS-VALIDATION-TRAILING.md`) — aligned trade table (1 trade, all 3 engines OK), metric reconciliation (8/8 within 1%), the A1 resolution section, and the high-vs-close LEGITIMATE-DIFFERENCE disposition with the D-TRAIL-1 root cause and the reason the trade-level table reconciles exactly here.
- **Owner-gated re-baseline FROZEN** — the `## Owner Sign-Off` block is SIGNED/APPROVED (tiziaco / tiziano.iaco@gmail.com / 2026-06-17), 0 BUG rows; freezes this phase's OWN trailing golden re-baseline (the `MatchingEngine` resting-order ratchet subsystem — a DIFFERENT subsystem from the Phase-4 accounting core).

## Trade-Level Reconciliation (PRIMARY)

| # | iTrader entry | iTrader exit | backtesting.py exit | backtrader exit | flag |
|---|---------------|--------------|---------------------|-----------------|------|
| 0 | 2020-01-03 | 2020-01-07 | 2020-01-07 | 2020-01-07 | OK / OK |

All three engines gap-fill at the SAME ratcheted stop (100.8) on the SAME bar; PnL +8.0; the 10% trail distance is large relative to the gentle rising-leg intrabar range, and `high == close` on every ratcheting bar so the HIGH-based (iTrader) and CLOSE-based (oracle) water-marks COINCIDE.

## Task Commits

1. **Task 1: trailing cross-val orchestrator + runners (A1 verified) + evidence report** - `f42c345` (feat)
2. **Task 1 follow-up: spot-oracle verify-command correction in 05-04-PLAN.md** - `d6f0de8` (docs)
3. **Task 2: owner sign-off freeze (TRAIL-03 APPROVED) signed in the evidence report** - `72b1fe3` (docs)

_Task 2 is the blocking human-verify checkpoint. The owner reviewed all verification evidence and APPROVED; the sign-off was recorded by this continuation executor._

## Decisions Made

- **A1 CONFIRMED (not just assumed):** the report records the verified actual oracle trailing API + trail-basis of the two installed versions, resolving the [ASSUMED A1] tag. Both trail off the CLOSE; iTrader off the closed-bar extreme (D-TRAIL-1). The scenario neutralizes the basis difference so the trade-level table reconciles exactly.
- **high-vs-close = LEGITIMATE-DIFFERENCE, NOT a bug:** iTrader's closed-bar-extreme ratchet is the look-ahead-safe behavior mandated by TRAIL-02; on a series where a ratcheting bar's HIGH strictly exceeds its CLOSE the gap surfaces only as a <=1-bar SHIFT, within tolerance.
- **Owner-gated freeze, manual:** the trailing re-baseline freeze is a manual owner sign-off (name+date in the evidence report), never an automated gate (`workflow.auto_advance` is false — T-05-10 repudiation mitigation). APPROVED 2026-06-17 by tiziaco.

## Deviations from Plan

**1. [Doc correction — wrong spot-oracle verify command in the plan] Fixed `tests/golden -x` -> `tests/integration/test_backtest_oracle.py`**
- **Found during:** Task 1 / Task 2 verification setup.
- **Issue:** The plan (and the original `<how-to-verify>` step 5) cited `pytest tests/golden -x` to confirm the SMA_MACD spot oracle stayed byte-exact. `tests/golden/` is an ARTIFACTS directory (CSV + markdown evidence), NOT a pytest tree — it collects 0 tests, so the gate would silently pass without actually exercising the oracle. The correct oracle test is `tests/integration/test_backtest_oracle.py` (16 passed, 134 trades / final_equity 46189.87730727451).
- **Fix:** Corrected the verify command in `05-04-PLAN.md` (and noted it in the evidence report's sign-off block).
- **Committed in:** `d6f0de8` (docs(05-04): fix spot-oracle verify command).

**Total deviations:** 1 (a verify-command documentation correction; no production/script behavior changed).

## Verification Results (owner-reviewed at the Task 2 checkpoint)

- `poetry run python scripts/cross_validate_trailing.py` -> runs to completion; trade-level reconciliation EXACT (exit 100.8, PnL +8.0); 8/8 metrics within 1%.
- Trade-level reconciliation EXACT across iTrader / backtesting.py / backtrader; high-vs-close gap dispositioned LEGITIMATE-DIFFERENCE — **APPROVED**.
- `make test` full suite GREEN — **APPROVED**.
- `poetry run mypy --strict itrader` clean — **APPROVED**.
- Determinism double-run byte-identical (`scripts/run_backtest.py` x2) — **APPROVED**.
- SMA_MACD spot oracle byte-exact: `poetry run pytest tests/integration/test_backtest_oracle.py` -> 16 passed (134 / 46189.87730727451) — **VERIFIED** (trailing is oracle-dark on the spot path; synthetic `TRAILUSD` only).
- No `import backtesting` / `import backtrader` under `tests/` (oracle imports SCRIPT-ONLY, D-10 / T-05-09).

## Threat Surface

- **T-05-09 (Tampering — strict-warning contract via oracle imports under tests/):** mitigated — backtesting/backtrader imports stay SCRIPT-ONLY under `scripts/crossval/`; never under `tests/` (keeps `filterwarnings=['error']`).
- **T-05-10 (Repudiation — result-changing re-baseline frozen without attribution):** mitigated — owner-gated blocking checkpoint; the `## Owner Sign-Off` block is SIGNED with name + date + email (tiziaco / 2026-06-17 / tiziano.iaco@gmail.com) BEFORE the freeze; manual, never auto-approvable.
- **T-05-SC (package installs):** N/A — zero package installs (backtesting.py 0.6.5 + backtrader 1.9.78.123 already in `pyproject.toml`).
- No new external/network/auth surface — offline cross-validation scripts + evidence only.

## Known Stubs

None.

## Self-Check: PASSED

- `scripts/cross_validate_trailing.py` exists; `scripts/crossval/trailing_run.py`, `backtesting_py_trailing_run.py`, `backtrader_trailing_run.py` exist (committed in f42c345).
- `tests/golden/CROSS-VALIDATION-TRAILING.md` exists and the `## Owner Sign-Off` block is SIGNED/APPROVED (tiziaco / 2026-06-17).
- Commits present in git log: f42c345 (Task 1), d6f0de8 (verify-command fix), 72b1fe3 (owner sign-off freeze).

## Next Phase Readiness

- **Phase 5 (Engine-Native Trailing Stops) is COMPLETE** — TRAIL-01 (config + carriage, 05-01), TRAIL-02 (MatchingEngine ratchet, 05-02), end-to-end declaration (05-03), and TRAIL-03 (cross-validation + owner-gated re-baseline freeze, this plan) are all closed. The trailing golden re-baseline is FROZEN under owner sign-off; the `tests/e2e/{trailing_long,trailing_short}/` white-box leaves are the regression lock.
- Next per the v1.4 Phase Map: Phase 6 (Pair-Trading Flagship) — additive capstone, slip-able, NOT a re-baseline. (Note: Phase 05.1 Short Position Scale-In was inserted after Phase 5 as an URGENT owner-gated item — see ROADMAP / STATE.)

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
