---
phase: 08-admission-position-management-cash-edges
plan: 01
subsystem: testing
tags: [e2e, reporting, cash-ledger, scale-in, admission, determinism, pandas]

# Dependency graph
requires:
  - phase: 07-cost-sizing-sltp-scenarios
    provides: "opt-in orders.csv snapshot pattern (D-15), conftest _freeze/_diff exists() gate, over_cash_reject SIZE-03 leaf as the CASH-01 non-duplication reference"
provides:
  - "Determinism-safe CashOperation ledger snapshot serializer (itrader/reporting/cash_operations.py) following the orders-snapshot opt-in pattern"
  - "Opt-in cash_operations.csv wiring in the e2e harness (conftest _assemble/_freeze/_diff behind the exists() gate)"
  - "ScriptedEmitter allow_increase + max_positions ctor params (behavior-preserving defaults False / 1)"
  - "Frozen admission/scale_in canary covering ADMIT-01 (successful pyramiding) and CASH-01 (cash-ledger no-commit lens)"
affects: [08-02, 08-03, phase-09-scenario-waves]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cash-ledger snapshot serializer: duck-typed Any input, allowlist columns, derived stable correlation label instead of raw UUID, float-at-CSV-edge"
    - "Opt-in golden materialization via placeholder exists() gate (oracle-dark serializer)"

key-files:
  created:
    - itrader/reporting/cash_operations.py
    - tests/e2e/admission/scale_in/scenario.py
    - tests/e2e/admission/scale_in/test_scenario.py
    - tests/e2e/admission/scale_in/bars.csv
    - tests/e2e/admission/scale_in/golden/trades.csv
    - tests/e2e/admission/scale_in/golden/summary.json
    - tests/e2e/admission/scale_in/golden/cash_operations.csv
  modified:
    - tests/e2e/conftest.py
    - tests/e2e/strategies/scripted_emitter.py

key-decisions:
  - "D-02: cash_operations.csv serializer EXCLUDES the UUIDv7 operation_id, the raw reference_id, and the wall-clock RESERVATION/RELEASE timestamp; correlation is a derived per-reference ordinal label (ORDER-{n}) so a RESERVATION matches its RELEASE without exposing a non-deterministic id"
  - "D-04: scale_in is the one deliberate two-outcome fold (ADMIT-01 successful pyramiding + CASH-01 over-cash no-commit) authored as leaf 1"
  - "D-01: CASH-01 uses the scale-in-exhaustion trigger + cash-ledger no-commit lens — distinct from Phase 7 SIZE-03's order-mirror REJECTED lens (no duplication)"
  - "D-05: foundational-plan-first, oracle-dark — shared infra (serializer, conftest, emitter) + one hand-verified canary committed FIRST so parallel waves never edit shared files"

patterns-established:
  - "Cash-ledger snapshot serializer mirrors orders.py: COLUMNS allowlist + duck-typed builder + stable derived label + float-only-at-edge + non-empty sort/reset"
  - "Opt-in cash_operations.csv fires ONLY when its placeholder exists in a leaf's golden/ dir — keeps the BTCUSD oracle byte-exact"

requirements-completed: [ADMIT-01, CASH-01]

# Metrics
duration: 13min
completed: 2026-06-10
---

# Phase 8 Plan 1: Admission Foundation + scale_in Canary Summary

**Determinism-safe cash-ledger snapshot serializer wired opt-in into the e2e harness, ScriptedEmitter extended with allow_increase/max_positions, and the admission/scale_in canary frozen — proving successful pyramiding (ADMIT-01) and an over-cash add whose reservation never commits (CASH-01) while the BTCUSD oracle stays byte-exact.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-06-10T15:38:16+02:00
- **Completed:** 2026-06-10T15:51:44+02:00
- **Tasks:** 3 (1 TDD, 1 auto, 1 checkpoint:human-verify)
- **Files modified:** 9 (7 created, 2 modified)

## Accomplishments

- Built `itrader/reporting/cash_operations.py` — the one new artifact of the phase: a determinism-safe `CashOperation` ledger snapshot serializer (`CASH_OPERATION_COLUMNS` + `build_cash_operations`), a structural clone of `orders.py`, excluding the UUIDv7 `operation_id`, raw `reference_id`, and wall-clock `timestamp`; correlation derived as a stable per-reference ordinal (`ORDER-{n}`).
- Wired the serializer opt-in into the e2e harness (`conftest._assemble/_freeze/_diff` behind the `cash_operations.csv` `exists()` gate) so it materializes only for leaves that commit the placeholder — keeping the serializer oracle-dark.
- Extended `ScriptedEmitter` with keyword-only `allow_increase: bool = False` and `max_positions: int = 1` (defaults preserve every existing leaf, D-06).
- Authored, hand-verified, and froze the `admission/scale_in` canary: an initial BUY + a successful scale-in add (ADMIT-01, rides the `allow_increase=True` fall-through) + an over-cash add whose RESERVATION never commits (CASH-01, cash-ledger no-commit lens), then a closing SELL. Cash trail hand-derived: 10000 → reserve 4000/release → debit 4000 (6000) → reserve 4000/release → debit 4000 (2000) → credit 8000 on exit (10000). available_cash left intact through the rejected add; no orphan reservation.
- Re-proved the BTCUSD oracle byte-exact (134 trades / final_equity 46189.87730727451 unchanged): the serializer is out of `frames.py::TRADE_COLUMNS` and only fires opt-in.

## Task Commits

Each task was committed atomically:

1. **Task 1: Cash-ledger snapshot serializer (TDD)** - `902af6c` (test, RED) → `af570d3` (feat, GREEN)
2. **Task 2: Opt-in conftest wiring + ScriptedEmitter allow_increase/max_positions** - `fa0d858` (feat)
3. **Task 3: Author + hand-verify + freeze the scale_in canary** - `4f12a48` (feat) — committed after the human reviewer typed "approved" at the blocking checkpoint

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified

- `itrader/reporting/cash_operations.py` - Determinism-safe CashOperation ledger snapshot serializer (CASH_OPERATION_COLUMNS + build_cash_operations)
- `tests/e2e/conftest.py` - Opt-in cash_operations.csv wiring (_assemble builds cash_ops, _freeze/_diff gate on exists())
- `tests/e2e/strategies/scripted_emitter.py` - allow_increase + max_positions ctor params threaded to BaseStrategyConfig
- `tests/e2e/admission/scale_in/scenario.py` - The ADMIT-01 + CASH-01 fold canary with the ===== VERIFY ===== hand-derivation
- `tests/e2e/admission/scale_in/test_scenario.py` - One-line run_scenario(parent)
- `tests/e2e/admission/scale_in/bars.csv` - Contrived daily BTCUSD bars (round prices, tz-aware)
- `tests/e2e/admission/scale_in/golden/trades.csv` - Frozen filled adds (LONG round-trip, realised_pnl 0)
- `tests/e2e/admission/scale_in/golden/summary.json` - Frozen summary (trade_count 1, final_equity 10000.0)
- `tests/e2e/admission/scale_in/golden/cash_operations.csv` - Frozen cash-ledger snapshot (RESERVATION/RELEASE/DEBIT/CREDIT trail, opt-in placeholder)

## Decisions Made

None beyond the plan's locked decisions (D-01, D-02, D-04, D-05, D-06). All were followed as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The checkpoint at Task 3 was a planned blocking `checkpoint:human-verify` gate (not a failure): the canary was authored, frozen, and automation-verified, then deliberately left uncommitted pending human review of the VERIFY hand-derivation. The reviewer typed "approved", and this continuation executor re-confirmed both the leaf (diff mode) and the BTCUSD oracle green before committing the freeze.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Shared infra (cash-ledger serializer, conftest opt-in wiring, emitter admission params) is committed and proven — later admission/position-management/cash-edge leaves (08-02, 08-03) can now fan out in parallel worktrees without editing these shared files.
- BTCUSD oracle byte-exact; existing smoke/sizing leaves remain green.
- `tests/e2e/admission/scale_in` is the copy-template for sibling admission leaves.

## Self-Check: PASSED

All 8 created files verified present on disk; all 4 task commits (902af6c, af570d3, fa0d858, 4f12a48) verified in git history.

---
*Phase: 08-admission-position-management-cash-edges*
*Completed: 2026-06-10*
