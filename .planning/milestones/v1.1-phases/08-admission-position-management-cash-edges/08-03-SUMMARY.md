---
phase: 08-admission-position-management-cash-edges
plan: 03
subsystem: testing
tags: [e2e, cash-ledger, reservation, release, golden-master, CASH-02, regression-lock]

# Dependency graph
requires:
  - phase: 08-admission-position-management-cash-edges (08-01)
    provides: "cash_operations.py ledger serializer (D-02) + opt-in cash_operations.csv golden vehicle"
  - phase: 07-cost-sizing-sltp-scenarios (07-01)
    provides: "D-14 exchange re-init seam (conftest) + over_cash_reject leaf shape (SIZE-03)"
  - phase: 06 (matching/operator)
    provides: "operator-cancel actions timeline (Action + ScenarioSpec.actions)"
provides:
  - "CASH-02 reservation-release golden-locked on all three terminal states: CANCELLED (positive), REFUSED (positive, deterministic max_order_size), REJECTED (honest negative no-orphan)"
  - "release_cancelled leaf: resting LIMIT BUY operator-cancelled -> RESERVATION -> RELEASE_RESERVATION pair"
  - "release_refused leaf: over-max_order_size BUY -> validate_order REFUSED -> RESERVATION -> RELEASE_RESERVATION pair"
  - "release_rejected leaf: over-cash MARKET BUY -> cash_reservation reject AT reserve -> EMPTY ledger (no-orphan)"
  - "conftest max_order_size cache seam: re-derives _min/_max_order_size from applied spec.exchange"
affects: [phase-09-multi-portfolio-cash-isolation, future-cash-edge-scenarios]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Honest-asymmetric terminal-state coverage (D-03): two positive release leaves (explicit RESERVATION->RELEASE_RESERVATION pair) + one negative leaf (explicit no-orphan absence)"
    - "Cash-ledger lens (D-02): assert the explicit op trail, NOT the ambiguous 'available_cash returns to full'"
    - "REFUSED via deterministic spec.exchange max_order_size validate_order failure, NOT the RNG simulate_failures path (D-03)"

key-files:
  created:
    - tests/e2e/cash/release_cancelled/scenario.py
    - tests/e2e/cash/release_cancelled/golden/cash_operations.csv
    - tests/e2e/cash/release_refused/scenario.py
    - tests/e2e/cash/release_refused/golden/cash_operations.csv
    - tests/e2e/cash/release_rejected/scenario.py
    - tests/e2e/cash/release_rejected/golden/cash_operations.csv
    - tests/e2e/cash/release_rejected/golden/orders.csv
  modified:
    - tests/e2e/conftest.py

key-decisions:
  - "release_rejected reuses SIZE-03's cash_reservation trigger but a DISTINCT lens: cash-ledger no-orphan (cash_operations.csv) vs SIZE-03's order-mirror REJECTED row (orders.csv)"
  - "No-orphan contrast vs ADMIT-03: ADMIT-03 max_positions gate fires BEFORE sizing (REJECTED qty=0); CASH-02 cash_reservation reject fires AFTER sizing but AT reserve (REJECTED qty=1000, SIZED) — both leave NO orphan reservation"
  - "Conftest seam (Rule 3): re-derive cached _max_order_size from spec.exchange so validate_order honors the per-scenario REFUSED lever; _supported_symbols left untouched (PATTERNS A2)"
  - "No reserve-then-REJECTED path fabricated — none exists (owner-gated, deferred)"

patterns-established:
  - "Pattern 1: per-terminal-state cash-ledger canary — each terminal state (CANCELLED/REFUSED/REJECTED) is its own isolated parallel-safe leaf (D-04)"
  - "Pattern 2: empty-placeholder opt-in — committing a header-only golden/cash_operations.csv (and golden/orders.csv) opts a leaf into that snapshot; a header-only cash ledger IS the no-orphan assertion"

requirements-completed: [CASH-02]

# Metrics
duration: ~25min (spanning two human-verify checkpoints)
completed: 2026-06-10
---

# Phase 8 Plan 03: CASH-02 Reservation-Release Canaries Summary

**CASH-02 reservation release golden-locked across all three terminal states via the cash-ledger lens: CANCELLED + REFUSED show the explicit RESERVATION->RELEASE_RESERVATION pair (positive), REJECTED shows the explicit no-orphan empty ledger (honest negative).**

## Performance

- **Duration:** ~25 min (two blocking human-verify checkpoints)
- **Completed:** 2026-06-10
- **Tasks:** 2 (both checkpoint:human-verify, both approved)
- **Files modified:** 21 (3 leaf folders + conftest seam)

## Accomplishments
- **CASH-02 fully golden-locked** on every terminal state of a cash reservation: CANCELLED (positive release), REFUSED (positive release via deterministic max_order_size), REJECTED (honest negative no-orphan).
- **release_cancelled**: a resting LIMIT BUY reserves, an operator cancel at the scheduled bar fires the local-cancel release (order_manager.py:1225-1227) -> a POSITIVE RELEASE_RESERVATION op matching the reservation; available_cash intact.
- **release_refused**: an over-max_order_size BUY reserves, then simulated._admit_order's validate_order failure -> FillEvent(REFUSED) -> terminal release (should_release on REFUSED) -> a POSITIVE RELEASE_RESERVATION op. Deterministic D-03 lever (spec.exchange max_order_size), NOT the RNG path.
- **release_rejected**: an over-cash MARKET BUY (FixedQuantity qty=1000, 100k notional vs 10k cash) is REJECTED AT the cash-reservation gate — reserve_cash raises InsufficientFundsError BEFORE add_reservation/_create_operation, so NO RESERVATION op is ever recorded. The frozen cash_operations.csv is HEADER-ONLY (zero rows): the no-orphan negative assertion. available_cash + equity intact at 10000.0.

## Task Commits

1. **Task 1: release_cancelled + release_refused (CASH-02 positive releases) + conftest seam** - `645f20f` (feat)
2. **Task 2: release_rejected (CASH-02 REJECTED honest negative no-orphan)** - `9f36f29` (feat)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `tests/e2e/cash/release_cancelled/{scenario,test_scenario}.py, bars.csv, golden/{trades.csv,summary.json,cash_operations.csv}` - CANCELLED positive-release leaf
- `tests/e2e/cash/release_refused/{scenario,test_scenario}.py, bars.csv, golden/{trades.csv,summary.json,cash_operations.csv}` - REFUSED positive-release leaf
- `tests/e2e/cash/release_rejected/{scenario,test_scenario}.py, bars.csv, golden/{trades.csv,summary.json,orders.csv,cash_operations.csv}` - REJECTED no-orphan negative leaf
- `tests/e2e/conftest.py` - re-derive cached `_min/_max_order_size` from applied `spec.exchange` (the REFUSED lever seam)

## Decisions Made
- **No-orphan contrast (ADMIT-03 vs CASH-02):** Both leaves prove "REJECTED holds no orphan reservation," but at structurally different points. ADMIT-03 (Plan 02) rejects at the `max_positions` gate in step 0, BEFORE `_resolve_signal_quantity` — so its audited REJECTED row is UNSIZED (`quantity=0`) and never reaches sizing or reserve. CASH-02 REJECTED here rejects AFTER sizing (FixedQuantity is a pass-through: `quantity=1000` SIZED), but AT `reserve()` — `reserve_cash` raises `InsufficientFundsError` atomically before recording any op. Neither leaves an orphan RESERVATION; the difference is gate-before-sizing (qty=0) vs reserve-raises-before-recording (qty=1000).
- **Distinct framing from SIZE-03:** release_rejected reuses SIZE-03's cash_reservation trigger but asserts on the CASH-LEDGER (no-orphan, header-only cash_operations.csv), whereas SIZE-03's load-bearing golden is the ORDER-MIRROR REJECTED row (orders.csv). orders.csv is frozen here too, but only for completeness.
- **No fabricated reserve-then-REJECTED path:** none exists in the engine (the cash_reservation reject IS the reserve failing atomically; the owner-gated reserve-then-reject is deferred). The negative leaf is the truthful model.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest max_order_size cache seam (committed in Task 1)**
- **Found during:** Task 1 (release_refused authoring)
- **Issue:** `validate_order` reads the CACHED `_min_order_size` / `_max_order_size` floats (simulated.py:99-100), NOT `simulated.config`. A spec carrying a tiny `limits.max_order_size` (the deterministic REFUSED lever) would NOT bite — the cached float still held the default 1000000.0 after the D-14 re-init, so no REFUSED fill would fire and the CASH-02 REFUSED canary could not be authored.
- **Fix:** After applying `spec.exchange` in `_build_and_run`, re-derive `simulated._min_order_size` / `_max_order_size` from `simulated.config.limits`, exactly as `SimulatedExchange.update_config` does (simulated.py:603-606). `_supported_symbols` is left UNTOUCHED (PATTERNS A2) — re-deriving the symbol set would wipe the post-construction BTCUSD admission and silently REFUSE every order.
- **Files modified:** tests/e2e/conftest.py
- **Verification:** Full e2e suite (37) + oracle (3) byte-exact green; release_refused REFUSED fill fires deterministically.
- **Committed in:** 645f20f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking, test-harness seam only — no engine/run-path change)
**Impact on plan:** The seam is test-only and oracle-dark (BTCUSD oracle byte-exact). It enables the deterministic REFUSED lever D-03 prescribes. No scope creep.

## Issues Encountered
None - both leaf clusters hand-verified once and frozen; full e2e + oracle re-confirmed green before each commit. Two blocking human-verify checkpoints (Task 1 positive pair, Task 2 negative leaf) both approved by the reviewer.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CASH-02 reservation release is fully regression-locked across all terminal states. The cash-ledger no-orphan assertion vehicle (header-only cash_operations.csv) is established for future cash-edge scenarios.
- Multi-portfolio cash isolation remains deferred to Phase 9 (D-04).
- This is the last plan of Phase 8; phase-level verification + completion is the orchestrator's job (runs after this executor returns).

## Self-Check: PASSED

- Files verified: release_rejected/scenario.py, golden/cash_operations.csv, golden/orders.csv, 08-03-SUMMARY.md all present.
- Commits verified: 645f20f (Task 1), 9f36f29 (Task 2) both in git log.

---
*Phase: 08-admission-position-management-cash-edges*
*Completed: 2026-06-10*
