---
phase: 02-margin-accounting-leverage
plan: 06
subsystem: testing
tags: [leverage, margin, e2e, decimal, parked-scenario, phase-gate, owner-gated]

# Dependency graph
requires:
  - phase: 02-margin-accounting-leverage
    provides: "Plan 03 admission leverage cap + margin reservation/reject (LEV-01/02, MARGIN-01/02); Plan 04 lock-and-settle position-keyed locked margin (MARGIN-01); Plan 05 maintenance_margin/margin_ratio read-model (MARGIN-03); Plan 01/02 SignalEvent.leverage + LeveredFraction sizing"
provides:
  - "A PARKED, hand-computed leveraged-long e2e scenario exercising the full margin core end-to-end (enable_margin=True, leverage > 1) — NOT a frozen golden (D-17)"
  - "The Phase-2 gate proof: SMA_MACD spot oracle byte-exact (134 / 46189.87730727451), margin-mode determinism byte-identical, mypy --strict clean, full suite green"
  - "Owner sign-off (blocking human-verify checkpoint APPROVED) that Phase 2 freezes NO new golden — the accounting-core re-baseline stays the single owner-gated freeze at Phase 4 / XVAL-01 (D-16/D-17)"
affects: [phase-04-liquidation-xval, margin, leverage, cross-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Parked-scenario discipline: assert HAND-COMPUTED literals with inline arithmetic, marked PARKED — freezes as a golden only at Phase 4 / XVAL-01 under owner sign-off (D-17)"
    - "Phase gate as an explicit blocking human-verify checkpoint: Claude runs the byte-exact oracle + determinism + mypy + suite automatically, owner confirms the parked-not-frozen decision"

key-files:
  created:
    - tests/e2e/levered_long/__init__.py
    - tests/e2e/levered_long/bars.csv
    - tests/e2e/levered_long/test_levered_long_scenario.py
  modified: []

key-decisions:
  - "Phase 2 freezes NO new leveraged golden — the leveraged-long e2e asserts hand-computed numbers and is PARKED for the owner-gated Phase 4 / XVAL-01 re-baseline (D-16/D-17); confirmed by the owner via the blocking human-verify checkpoint"
  - "The two integration findings this e2e SURFACED (A: StrategiesHandler dropped SignalIntent.leverage at fan-out; B: leverage not carried order->fill->transaction so Position.leverage defaulted to 1) were tracked as a new requirement LEV-03 and CLOSED by follow-on plan 02-07 — they are NOT open"

patterns-established:
  - "Hand-computed parked e2e: every expected number (initial_margin = notional/L, position size, effective leverage = min(...), maintenance_margin, margin_ratio honest-when-breached, realized PnL, locked-margin release) is a literal with the arithmetic shown inline — not a captured/regenerated golden"
  - "Findings surfaced by a parked scenario are routed to REQUIREMENTS.md (LEV-03) with traceability, never silently folded — preserves the owner-gated re-baseline attribution"

requirements-completed: [MARGIN-01, MARGIN-02, MARGIN-03, LEV-01, LEV-02]

# Metrics
duration: ~continuation (finalization only)
completed: 2026-06-15
---

# Phase 2 Plan 06: Parked Leveraged-Long E2E + Phase Gate Summary

**A hand-computed, PARKED leveraged-long e2e drives the full margin core end-to-end (enable_margin=True, leverage > 1) and the Phase-2 gate held byte-exact — owner-approved to close Phase 2 with the leveraged scenario parked, NOT frozen as a golden (D-16/D-17).**

## Performance

- **Duration:** continuation / finalization only (Task 1 was built in a prior session, committed `da0ec41`; this session is post-approval bookkeeping)
- **Completed:** 2026-06-15
- **Tasks:** 2 (1 auto + 1 blocking human-verify checkpoint)
- **Files modified:** 3 created (e2e scenario, bars fixture, package init)

## Accomplishments

- **Task 1 — the parked leveraged-long e2e (D-17).** A `tests/e2e/levered_long/` scenario runs a leveraged long through the full run path on a portfolio with `enable_margin=True` and a documented `max_leverage`, exercising all five Phase-2 requirements end-to-end:
  - `initial_margin = notional / leverage` reservation (MARGIN-01)
  - over-free-margin reject / no silent over-leverage (MARGIN-02)
  - maintenance_margin / margin_ratio query per open position, reading honestly below 1 on an adverse mark with NO force-close and NO clamp (MARGIN-03, D-16)
  - the leverage cap clamping an over-cap request to `min(signal, instr.max_leverage, pf.max_leverage)` (LEV-01)
  - `LeveredFraction` resolving `notional = f × equity` (LEV-02)

  Every assertion is a HAND-COMPUTED literal with the arithmetic shown inline. The scenario is explicitly marked **PARKED — NOT a frozen golden**; it freezes only at Phase 4 / XVAL-01 under owner sign-off + external cross-validation (D-17).

- **Task 2 — blocking human-verify checkpoint: APPROVED by the owner ("approved").** Before the checkpoint, the full phase gate was run and reported; the owner confirmed (a) the byte-exact spot oracle held and (b) the leveraged-long numbers are hand-verified and correctly PARKED (Phase 2 freezes NO new golden — the accounting-core re-baseline is the single owner-gated freeze at Phase 4 / XVAL-01, D-16/D-17).

- **Phase-2 gate GREEN** (re-run after the follow-on 02-07 rework):
  - SMA_MACD spot oracle byte-exact: **134 trades / final_equity 46189.87730727451** (the master constraint, T-02-20)
  - margin-mode determinism double-run byte-identical (no new nondeterminism; reuse the seeded RNG + injected `BacktestClock`, T-02-21)
  - `mypy --strict` clean across `itrader` (185 files)
  - `make test` — full suite **1079 passed** (filterwarnings=["error"], strict markers)
  - `poetry run pytest tests/e2e/levered_long -m e2e` passes

## Task Commits

1. **Task 1: parked leveraged-long e2e (hand-computed, D-17)** — `da0ec41` (test) — built and committed by a prior executor
2. **Task 2: blocking human-verify phase-gate checkpoint** — APPROVED by the owner ("approved"); no code commit (checkpoint, not a build step)

**Plan metadata:** this finalization commit (docs: SUMMARY + STATE + ROADMAP)

_Note: the parked e2e was subsequently REWORKED by plan 02-07 (commit `4e9ca05`) to drive leverage through the normal production fan-out and assert the corrected self-consistent numbers — see Cross-Reference below._

## Files Created/Modified

- `tests/e2e/levered_long/__init__.py` — e2e package marker (folder-derived `e2e` marker)
- `tests/e2e/levered_long/bars.csv` — the small fixed deterministic price series for the scenario
- `tests/e2e/levered_long/test_levered_long_scenario.py` — the parked leveraged-long e2e with hand-computed assertions (D-17). NOTE: now in its 02-07-reworked state (production fan-out, corrected numbers), still PARKED.

## Decisions Made

- **Phase 2 freezes NO new leveraged golden (D-16/D-17).** The leveraged-long e2e asserts hand-computed numbers and is PARKED for the owner-gated Phase 4 / XVAL-01 re-baseline. The owner confirmed this via the blocking human-verify checkpoint ("approved"). This protects the owner-gated re-baseline attribution (threat T-02-19): a leveraged golden frozen in Phase 2 would corrupt the single owner-gated freeze at Phase 4.
- **BTCUSD `Instrument` margin params for the scenario are planner/Claude discretion** (oracle-dark, RESEARCH A5: realistic crypto defaults). The chosen values and the hand-computation are documented inline in the test.

## Cross-Reference: Findings A/B were CLOSED by plan 02-07 / LEV-03

This e2e SURFACED two run-path integration findings. **They are NOT open — they were closed by follow-on plan 02-07 (requirement LEV-03):**

- **Finding A:** `StrategiesHandler.calculate_signals` dropped `SignalIntent.leverage` at the fan-out, so the leveraged signal lost its declared leverage. **Closed** in 02-07 (`81f85ec`): the fan-out `SignalEvent` now carries `intent.leverage`.
- **Finding B:** leverage was not carried `Order → OrderEvent → FillEvent → Transaction`, so `Position.leverage` defaulted to 1 and the position locked the full notional (not `notional / L`). **Closed** in 02-07 (`df8c2a0` + run-path `PortfolioHandler.on_fill` thread in `4e9ca05`): the admission-clamped EFFECTIVE leverage now flows end-to-end, so position-life locked margin (`aggregate_notional / leverage`) EQUALS the admission reservation (`notional / effective_leverage`).

Plan 02-07 also REWORKED this e2e (`4e9ca05`) to drive leverage through the normal production fan-out (no injected `SignalEvent`) and assert the corrected self-consistent numbers (`position.leverage = 5`, `locked_margin = aggregate_notional / 5 = 4000` = the admission reservation). The scenario remains PARKED (D-17). See `.planning/phases/02-margin-accounting-leverage/02-07-SUMMARY.md` and REQUIREMENTS.md LEV-03.

> A reader should NOT treat Findings A/B as open issues — they are closed, with the e2e now in its 02-07-reworked, self-consistent state.

## Deviations from Plan

None - plan executed as written. Task 1 built the parked e2e exactly to spec (hand-computed, PARKED, all five requirements + honest-when-breached margin_ratio); Task 2 was the blocking owner checkpoint, which was APPROVED. The two findings this plan surfaced were correctly routed to a new requirement (LEV-03) and a follow-on plan (02-07) rather than silently folded into this plan — preserving the owner-gated re-baseline attribution.

## Issues Encountered

- The plan's hand-computed numbers initially assumed leverage flowed end-to-end through the run path; the e2e instead SURFACED that it did not (Findings A/B above). This is the expected value of an adversarial parked scenario — it caught a real run-path gap. The gap was closed by plan 02-07 (LEV-03) and the e2e reworked to the corrected numbers. No issue remains open.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 2 (Margin Accounting & Leverage) is complete: MARGIN-01/02/03, LEV-01/02 closed by Plans 02-03/04/05, LEV-03 by 02-07; the parked leveraged-long e2e proves the margin core end-to-end with self-consistent numbers.
- The leveraged-long scenario is PARKED for the single owner-gated accounting-core re-baseline at Phase 4 / XVAL-01 (cross-validated against `backtesting.py` / `backtrader` + owner sign-off, D-16/D-17). NO Phase-2 golden was frozen.
- Phase 3 (Shorts & Borrow Carry) and Phase 4 (Liquidation & Cross-Validation) consume `Position.leverage` / locked margin — both now see the effective leverage on every position opened through the run path.

---
*Phase: 02-margin-accounting-leverage*
*Completed: 2026-06-15*

## Self-Check: PASSED

- `tests/e2e/levered_long/test_levered_long_scenario.py` exists on disk (FOUND).
- `tests/e2e/levered_long/__init__.py` and `tests/e2e/levered_long/bars.csv` exist on disk (FOUND).
- Task 1 commit `da0ec41` present in git log (FOUND).
- 02-07 cross-reference commits `81f85ec`, `df8c2a0`, `4e9ca05` present in git log (FOUND).
- Phase-2 requirements MARGIN-01/02/03, LEV-01/02/03 verified Complete in REQUIREMENTS.md (FOUND).
