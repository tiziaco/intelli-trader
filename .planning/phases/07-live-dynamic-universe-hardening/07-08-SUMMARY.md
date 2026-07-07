---
phase: 07-live-dynamic-universe-hardening
plan: 08
subsystem: order-admission
tags: [admission, readiness, WR-02, universe, live-trading, gate]

# Dependency graph
requires:
  - phase: 07-02 (v1.7)
    provides: Universe.is_ready per-symbol readiness surface (construction members READY, apply-added PENDING)
  - phase: 06-04 (v1.7)
    provides: AdmissionManager._enforce_leaving_symbol_admission (the shape mirrored) + self._universe seam + set_universe wiring
provides:
  - _enforce_readiness_admission — the PRIMARY WR-02 admission readiness gate (D-01)
  - OrderTriggerSource.ADMISSION_READINESS trigger source
  - Direct-injection rejection proof (a strategy-loop-bypassing signal for a PENDING symbol is REJECTED at admission)
affects: [live-warmup, per-symbol-readiness-gate, external-signal-ingress]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Admission gate mirrors the leaving-gate guard-clause shape verbatim (explicit bypass -> None no-op -> ready no-op -> sanctioned-exit pass -> audited reject)"

key-files:
  created:
    - tests/unit/order/test_admission_readiness_gate.py
  modified:
    - itrader/order_handler/admission/admission_manager.py
    - itrader/core/enums/order.py

key-decisions:
  - "Readiness gate wired SECOND (after leaving, before direction): leaving-first so stale readiness never mis-triggers on a sanctioned exit the leaving gate already allowed; readiness-before-direction so a PENDING symbol is intercepted with the correct reason before direction sizing"
  - "Gate is oracle-inert by construction: None-guarded no-op (backtest wires no universe) + construction members default READY (Plan 02) -> is_ready always true on the golden path"
  - "Sanctioned exit passes (SELL-on-LONG / BUY-on-SHORT) so a winding-down orphan whose readiness may be stale (D-15 force-close) can still go flat"

patterns-established:
  - "The PRIMARY (admission) + SECONDARY (strategy-loop, Plan 07-04) readiness-gate pair (D-01) is now complete"

requirements-completed: [WR-02]

# Metrics
duration: 4min
completed: 2026-07-06
---

# Phase 7 Plan 08: PRIMARY WR-02 Readiness Admission Gate (D-01) Summary

**`AdmissionManager._enforce_readiness_admission` is the PRIMARY WR-02 gate (D-01) — wired SECOND in `process_signal` (after the leaving gate, before direction), it rejects a non-READY (PENDING/FAILED) symbol's unsized signal at admission even when the signal BYPASSES the strategy-loop SECONDARY check, closing the confirmed threat that an externally-injected signal sizes a live order for an unwarmed symbol; oracle-inert by construction (None-guarded no-op + construction members READY).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-06T18:54:38Z
- **Completed:** 2026-07-06T18:58:xx Z
- **Tasks:** 1
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `OrderTriggerSource.ADMISSION_READINESS = "admission_readiness"` added after `ADMISSION_LEAVING` (D-01) — the closed-vocabulary member the audited rejection carries.
- `_enforce_readiness_admission(signal_event, snap)` added to `admission_manager.py`, mirroring `_enforce_leaving_symbol_admission`'s guard-clause shape EXACTLY: explicit-quantity bypass → `self._universe is None` no-op → `is_ready(ticker)` no-op → sanctioned-exit pass (SELL-on-LONG / BUY-on-SHORT) → else `_reject_unsized_signal(..., triggered_by=ADMISSION_READINESS, operation_type=SIGNAL_ADMISSION)` (audited PENDING→REJECTED persist, NO emit).
- Wired as the SECOND admission gate in `process_signal`, immediately after the leaving gate and before the direction gate, with the leaving-first / readiness-before-direction ordering rationale in a comment.
- New `test_admission_readiness_gate.py` (4-space, 6 tests) mirrors the leaving harness: a REAL `Universe` (BTCUSDT construction READY + ETHUSDT `apply`-added PENDING) injected via `OrderHandler.set_universe`. Proves: enum parse; a PENDING symbol's signal injected DIRECTLY into `on_signal` is audited-REJECTED (ADMISSION_READINESS) with ZERO OrderEvents; after `mark_ready` the identical signal is admitted; a READY construction member is admitted; no-universe is a no-op; explicit-quantity skips the gate.

## Task Commits

Each task was committed atomically:

1. **Task 1: ADMISSION_READINESS trigger source + _enforce_readiness_admission primary gate + test** - `e19ce331` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `itrader/core/enums/order.py` (modified, TABS) - `ADMISSION_READINESS` trigger source
- `itrader/order_handler/admission/admission_manager.py` (modified, TABS) - `_enforce_readiness_admission` gate + `process_signal` wiring (second gate)
- `tests/unit/order/test_admission_readiness_gate.py` (created, 4-space) - 6 tests: enum, direct-injection rejection, mark_ready admit, READY-member admit, no-universe no-op, explicit-qty bypass

## Decisions Made
- Followed the plan exactly. Gate wired SECOND (leaving → readiness → direction). Matched per-file indentation: TABS in `admission_manager.py` and `core/enums/order.py`, 4-space in the new test (matching `test_leaving_symbol_admission.py`).

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface

Threat register mitigations from the plan are all satisfied and asserted:
- **T-07-08-UNWARMED** (Tampering): the PRIMARY admission gate rejects a non-READY symbol's unsized signal at admission (audited REJECTED, no emit); proven via a direct `on_signal` injection test (bypasses the strategy loop).
- **T-07-08-ORACLE** (DoS): None-guarded no-op (backtest wires no universe) + construction members default READY; oracle byte-exact re-confirmed (134 / `46189.87730727451`).
- **T-07-08-TRAP** (DoS): sanctioned-exit pass (SELL-on-LONG / BUY-on-SHORT) mirrors the leaving gate; leaving-first ordering so stale readiness never traps a sanctioned exit.

No NEW security-relevant surface introduced (no endpoints, auth paths, file/schema access).

## Known Stubs
None — the gate is real and wired. The SECONDARY strategy-loop defensive check is Plan 07-04 Task 1 (already delivered per STATE.md 07-04); with this plan the D-01 PRIMARY+SECONDARY readiness-gate pair is complete.

## Issues Encountered
None.

## User Setup Required
None.

## Verification
- `poetry run pytest tests/unit/order/test_admission_readiness_gate.py -q` → **6 passed**.
- `poetry run pytest tests/unit/order -q` → **277 passed** (no regression).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → **3 passed** (oracle byte-exact 134 / `46189.87730727451`, determinism double-run).
- `poetry run mypy itrader/order_handler/admission/admission_manager.py itrader/core/enums/order.py` → clean (2 source files).
- `grep -n "def _enforce_readiness_admission"` matches and it is invoked in `process_signal` between the leaving gate and the direction gate; `grep -n "ADMISSION_READINESS" itrader/core/enums/order.py` matches.

## Self-Check: PASSED

- FOUND: itrader/order_handler/admission/admission_manager.py
- FOUND: itrader/core/enums/order.py
- FOUND: tests/unit/order/test_admission_readiness_gate.py
- FOUND commit: e19ce331

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*
