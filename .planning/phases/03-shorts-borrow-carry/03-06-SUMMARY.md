---
phase: 03-shorts-borrow-carry
plan: 06
subsystem: testing
tags: [shorts, borrow-carry, margin, decimal, parked-scenario, phase-gate, owner-gated, e2e, WR-residuals]

# Dependency graph
requires:
  - phase: 03-shorts-borrow-carry
    provides: "Plan 03 two-flag short registration + first-class short PnL (SHORT-01/03); Plan 04 side-agnostic cover-arm + clamp-to-flat + WR-04 (SHORT-02); Plan 05 per-bar BORROW_INTEREST carry accrual (CARRY-01)"
  - phase: 02-margin-accounting-leverage
    provides: "Plan 04 lock-and-settle position-keyed locked margin + _process_transaction_margin seam (the FRAGILE seam WR-01/03/05 harden); Plan 05 maintenance_margin read-model (the WR-02 universe-unwired site); Plan 08 deferred-items WR-01..05 residuals routed to Phase 3 (D-09)"
provides:
  - "The FRAGILE margin/settlement seam hardened ONCE (D-09): WR-01 settlement-side solvency assertion, WR-03 lock/release symmetry, WR-05 per-lock open-commission accumulator, WR-02 universe-unwired StateError — CR-02-residual over-close guard KEPT"
  - "Three PARKED, hand-computed e2e short scenarios (pure short round-trip, short-with-carry, partial cover) proving the short side end-to-end on the real run path — NOT frozen goldens (D-10)"
  - "Owner sign-off (blocking human-verify checkpoint APPROVED) that Phase 3 freezes NO new golden — the accounting-core re-baseline stays the single owner-gated freeze at Phase 4 / XVAL-01"
affects: [phase-04-liquidation-xval, margin, shorts, borrow-carry, cross-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-touch FRAGILE-seam hardening: WR-01/03/05 land in one edit to _process_transaction_margin so the margin/settlement path is touched ONCE under the single P4/XVAL-01 owner-gated re-baseline (D-09), not twice"
    - "Parked-scenario discipline continued for shorts: HAND-COMPUTED literals with inline arithmetic on the real SIGNAL→ORDER→FILL→PORTFOLIO path, synthetic instrument (NEVER BTCUSD), no golden-diff harness — frozen as golden only at P4/XVAL-01 under owner sign-off (D-10)"
    - "Owner-gated phase gate as a blocking human-verify checkpoint recorded in a dedicated VERIFY note (03-06-VERIFY-SIGNOFF.md)"

key-files:
  created:
    - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
    - tests/e2e/short_roundtrip/bars.csv
    - tests/e2e/short_carry/test_short_carry_scenario.py
    - tests/e2e/short_carry/bars.csv
    - tests/e2e/partial_cover/test_partial_cover_scenario.py
    - tests/e2e/partial_cover/bars.csv
    - .planning/phases/03-shorts-borrow-carry/03-06-VERIFY-SIGNOFF.md
  modified:
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/storage/in_memory_storage.py
    - itrader/order_handler/admission/admission_manager.py

key-decisions:
  - "The FRAGILE margin/settlement seam is hardened ONCE (D-09): WR-01 settlement-side solvency assertion, WR-03 lock/release symmetry, WR-05 per-lock open-commission accumulator, WR-02 universe-unwired StateError — bundling the WR residuals with the shorts work keeps the seam touched once under the single P4/XVAL-01 owner-gated re-baseline. The CR-02-residual over-close guard is KEPT (defense-in-depth)."
  - "Phase 3 freezes NO new golden — the three short scenarios assert hand-computed numbers and are PARKED for the owner-gated Phase 4 / XVAL-01 re-baseline (D-10); confirmed by the owner via the blocking human-verify checkpoint ('approved'). SMA_MACD spot oracle held byte-exact (134 / 46189.87730727451)."

patterns-established:
  - "WR-residual fold-in (D-09): margin-seam residuals deferred from Phase 2 (WR-01..05 in deferred-items.md) are closed in Phase 3 where shorts/levered entries newly exercise the lock paths — a single seam touch under one owner-gated re-baseline, not two"
  - "Hand-computed parked short e2e: realised short PnL (|size|×(entry−exit)−commissions), per-bar BORROW_INTEREST carry, partial-cover reduce-not-close, and a determinism double-run are every-number-a-literal with inline arithmetic — never a captured/regenerated golden; synthetic instrument only (SHORTUSD), NEVER BTCUSD"

requirements-completed: [SHORT-02, SHORT-03, CARRY-01]

# Metrics
duration: ~continuation (close-out only — Tasks 1-2 built in a prior session)
completed: 2026-06-15
---

# Phase 3 Plan 06: WR Margin-Seam Hardening + Parked Short E2E + Phase Gate Summary

**The FRAGILE margin/settlement seam was hardened in a single touch (WR-01/02/03/05, D-09) and three hand-computed PARKED e2e short scenarios prove the short side end-to-end — owner-approved to close Phase 3 with everything PARKED, NOT frozen as a golden (D-10); SMA_MACD held byte-exact (134 / 46189.87730727451).**

## Performance

- **Duration:** continuation / close-out only (Tasks 1-2 were built and committed in a prior session; this session records the post-approval sign-off + bookkeeping)
- **Completed:** 2026-06-15
- **Tasks:** 3 (2 auto + 1 blocking human-verify checkpoint)
- **Files modified:** 6 production/test files modified + 6 e2e files created + 1 VERIFY note created

## Accomplishments

- **Task 1 — WR-01/03/05 hardening on `_process_transaction_margin` + WR-02 universe-unwired `StateError` (D-09).** The FRAGILE margin/settlement seam — the WR residuals the Phase-2 review parked, now reachable because shorts/levered entries lock margin on the run path — was hardened in a single touch:
  - **WR-01** — a settlement-side solvency assertion that the locked margin (`aggregate_notional / leverage`) fits available buying power at lock time, failing loud before settling (`assert_funds_invariant` extended).
  - **WR-03** — lock/release symmetry asserted/commented at the assembly-failure release site (no fill yet → no position-keyed margin lock can exist).
  - **WR-05** — the `fraction × prior_entry_commission` proxy replaced by a per-lock open-commission accumulator, so a non-uniform-commission scale-in does not drift the round-trip cash delta from realized PnL.
  - **WR-02** — the `maintenance_margin` `_universe.instrument(...)` read AND the new carry read site now guard `_universe is None` with a context-rich `StateError` (universe-unwired) when open positions exist — never a bare `AttributeError`.
  - The **CR-02-residual over-close guard is KEPT** (defense-in-depth, NOT removed). All changes oracle-dark — margin off on the golden path. TDD: the `funds_invariant_lock` / `release_symmetry` / `open_commission_accumulator` / `universe_unwired` test stubs turned green; `mypy --strict` clean.

- **Task 2 — three PARKED e2e scenarios with hand-computed literals (D-10).** The three Plan-02 skipped stubs were replaced with full PARKED scenarios mirroring `levered_long`, each driving the REAL `SIGNAL → ORDER → FILL → PORTFOLIO` path with a SYNTHETIC instrument (`SHORTUSD` etc. — **never BTCUSD**) and hand-computed literals with inline arithmetic:
  - `short_roundtrip` — SELL-to-open → BUY-to-cover; realised short PnL = `|size| × (entry − exit) − commissions`, margin lock released (SHORT-02/03).
  - `short_carry` — multi-bar held short; per-bar `BORROW_INTEREST` debits, equity = PnL − Σ carry, plus a determinism double-run byte-identical (carry amounts + timestamps) (CARRY-01).
  - `partial_cover` — BUY-cover with `exit_fraction < 1` reduces (not closes) the short; the remaining short carries on (SHORT-02).

  No `--freeze` / golden-diff harness used (the scenarios are PARKED). This task also fixed the `SHORT_ONLY` cover gate in `admission_manager.py` (the CR-01 cover-arm hole surfaced at v1.0 Phase 7 / 07-REVIEW).

- **Task 3 — blocking human-verify phase-gate checkpoint: APPROVED by the owner ("approved").** Before the checkpoint, the full Phase-3 gate was run and reported; the owner confirmed the byte-exact oracle held, the three short scenarios are hand-verified and correctly PARKED, and that NOTHING was `--freeze`d. Recorded in `03-06-VERIFY-SIGNOFF.md`.

- **Phase-3 gate GREEN:**
  - SMA_MACD spot oracle byte-exact: **134 trades / final_equity 46189.87730727451** (shorts-off / carry-off defaults — all Phase-3 changes oracle-dark).
  - Determinism double-run on the carry scenario byte-identical (no new nondeterminism).
  - `mypy --strict` clean across the touched files / `itrader`.
  - Full suite green (filterwarnings=["error"], strict markers/config).
  - NOTHING `--freeze`d — no new golden artifact under `tests/golden/`.

## Task Commits

Each task was committed atomically:

1. **Task 1: WR-01/02/03/05 margin-seam hardening (D-09)** — `88af0c7` (feat)
2. **Task 2: three parked e2e short scenarios + SHORT_ONLY cover-gate fix (D-10)** — `d6ed565` (feat)
3. **Task 3: owner-gated parked-scenario sign-off (blocking human-verify checkpoint)** — APPROVED by the owner ("approved"); recorded in VERIFY note `d0fd97d` (docs)

**Plan metadata:** this close-out commit (docs: SUMMARY)

_Note: Tasks 1-2 were built and committed in a prior session; this continuation records the approved owner sign-off and writes the SUMMARY. STATE.md / ROADMAP.md are owned by the orchestrator and were NOT modified here._

## Files Created/Modified

**Production / test modified (Task 1):**
- `itrader/portfolio_handler/portfolio.py` — WR-01 funds invariant + WR-03 lock/release symmetry + WR-05 open-commission accumulator in `_process_transaction_margin` (TABS)
- `itrader/portfolio_handler/cash/cash_manager.py` — `assert_funds_invariant` extended for the settlement-side solvency assertion; lock/release symmetry support (4-space)
- `itrader/portfolio_handler/portfolio_handler.py` — WR-02 universe-unwired `StateError` guard at the `maintenance_margin` + carry read sites (4-space)
- `itrader/portfolio_handler/base.py`, `itrader/portfolio_handler/storage/in_memory_storage.py` — supporting changes for the WR-05 per-lock accumulator
- `tests/unit/portfolio/test_portfolio_margin.py`, `test_cash_manager.py`, `test_portfolio_handler.py` — the four WR test stubs turned green

**E2e created (Task 2):**
- `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py` + `bars.csv` — parked pure-short round-trip
- `tests/e2e/short_carry/test_short_carry_scenario.py` + `bars.csv` — parked multi-bar held-short carry (determinism double-run)
- `tests/e2e/partial_cover/test_partial_cover_scenario.py` + `bars.csv` — parked partial-cover reduce-not-close
- `itrader/order_handler/admission/admission_manager.py` — `SHORT_ONLY` cover-gate fix (CR-01 cover-arm hole)

**Sign-off artifact (Task 3):**
- `.planning/phases/03-shorts-borrow-carry/03-06-VERIFY-SIGNOFF.md` — the owner-gated parked-scenario sign-off VERIFY note

## Decisions Made

- **The FRAGILE margin/settlement seam is hardened ONCE (D-09).** WR-01/03/05 land in a single edit to `_process_transaction_margin` and WR-02 guards both universe-unwired read sites, so the seam is touched once under the single P4/XVAL-01 owner-gated re-baseline, not twice. The CR-02-residual over-close guard is KEPT as defense-in-depth — explicitly NOT removed.
- **Phase 3 freezes NO new golden (D-10).** The three short scenarios assert hand-computed numbers and are PARKED for the owner-gated Phase 4 / XVAL-01 re-baseline. The owner confirmed via the blocking human-verify checkpoint ("approved"). Freezing a Phase-3 short golden now would corrupt the single owner-gated re-baseline's attribution (threat T-03-18), so it is deferred. SMA_MACD spot oracle held byte-exact (134 / 46189.87730727451).
- **Synthetic instruments only — NEVER BTCUSD.** Each scenario declares a synthetic crypto ticker (e.g. `SHORTUSD`) with realistic oracle-dark borrow-rate / maintenance-margin defaults (planner/owner discretion, documented inline). The only `BTCUSD` tokens in the scenario files are "NEVER BTCUSD" docstring negations.

## Deviations from Plan

None - plan executed as written. Task 1 hardened the FRAGILE seam exactly to spec (WR-01/02/03/05 in a single touch, CR-02 guard intact, oracle-dark); Task 2 authored the three parked scenarios against hand-computed literals on the real run path (synthetic instruments, nothing frozen) and closed the CR-01 `SHORT_ONLY` cover-arm hole; Task 3 was the blocking owner checkpoint, which was APPROVED.

## Issues Encountered

None. The WR residuals were closed cleanly in a single seam touch and the three parked scenarios passed against their hand-computed literals.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 (Shorts & Borrow Carry) is complete: SHORT-01 (Plan 03), SHORT-02 (Plans 04/06), SHORT-03 (Plans 03/06), CARRY-01 (Plans 05/06) closed; the WR-01/02/03/05 margin-seam residuals (D-09) are folded in; the three parked short scenarios prove the short side end-to-end.
- All three short scenarios are PARKED for the single owner-gated accounting-core re-baseline at **Phase 4 / XVAL-01** (cross-validated against `backtesting.py` / `backtrader` + owner sign-off). NO Phase-3 golden was frozen.
- Phase 4 (Liquidation & Cross-Validation Re-baseline) now has all three crafted scenario types available (short — this phase; leveraged-long — Phase 2; forced liquidation — Phase 4) to perform the single owner-gated accounting-core re-baseline under XVAL-01.

---
*Phase: 03-shorts-borrow-carry*
*Completed: 2026-06-15*

## Self-Check: PASSED

- `.planning/phases/03-shorts-borrow-carry/03-06-VERIFY-SIGNOFF.md` exists on disk (FOUND).
- `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py`, `tests/e2e/short_carry/test_short_carry_scenario.py`, `tests/e2e/partial_cover/test_partial_cover_scenario.py` exist on disk (FOUND).
- Task 1 commit `88af0c7` present in git log (FOUND).
- Task 2 commit `d6ed565` present in git log (FOUND).
- Task 3 sign-off commit `d0fd97d` present in git log (FOUND).
- No new golden artifact written under `tests/golden/` (working tree clean of golden-writes); nothing `--freeze`d.
