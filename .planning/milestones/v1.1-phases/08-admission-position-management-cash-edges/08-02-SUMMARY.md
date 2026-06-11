---
phase: 08-admission-position-management-cash-edges
plan: 02
subsystem: testing
tags: [e2e, golden-master, admission, max-positions, scale-out, re-entry, scripted-emitter, regression-lock]

# Dependency graph
requires:
  - phase: 08-admission-position-management-cash-edges (Plan 01)
    provides: "shared admission infra — ScriptedEmitter max_positions/exit_fraction knobs, cash_operations ledger serializer, scale_in canary copy-template"
  - phase: 07-cost-sizing-sltp-scenarios
    provides: "over_cash_reject opt-in orders.csv REJECTED-snapshot vehicle (D-15), single_market_buy round-trip copy-template"
provides:
  - "ADMIT-02 frozen E2E leaf: partial scale-out via exit_fraction < 1 (position stays open between partial sells, full close at end)"
  - "ADMIT-03 frozen E2E leaf: max_positions cap REJECTED new-ticker entry (gate-before-sizing, quantity=0 audited reject)"
  - "ADMIT-04 frozen E2E leaf: full-exit-then-re-entry on the same ticker (two clean round-trips)"
  - "first multi-ticker (multi-CSV) E2E leaf — ETHUSDT occupier + BTCUSD over-cap entry on one portfolio"
affects: [09-multi-portfolio-cash-isolation, phase-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-ticker single-portfolio leaf: two ScriptedEmitter instances subscribed to one portfolio to drive a portfolio-wide open-position count to the cap"
    - "Gate-before-sizing REJECTED orders-snapshot: the max_positions gate audits an UNSIZED reject (quantity=0), distinct from Phase 7 SIZE-03 cash-reservation reject which freezes the sized quantity"

key-files:
  created:
    - tests/e2e/admission/scale_out/scenario.py
    - tests/e2e/admission/scale_out/test_scenario.py
    - tests/e2e/admission/scale_out/bars.csv
    - tests/e2e/admission/scale_out/golden/trades.csv
    - tests/e2e/admission/scale_out/golden/summary.json
    - tests/e2e/admission/re_entry/scenario.py
    - tests/e2e/admission/re_entry/test_scenario.py
    - tests/e2e/admission/re_entry/bars.csv
    - tests/e2e/admission/re_entry/golden/trades.csv
    - tests/e2e/admission/re_entry/golden/summary.json
    - tests/e2e/admission/max_positions/scenario.py
    - tests/e2e/admission/max_positions/test_scenario.py
    - tests/e2e/admission/max_positions/bars.csv
    - tests/e2e/admission/max_positions/bars_eth.csv
    - tests/e2e/admission/max_positions/golden/orders.csv
    - tests/e2e/admission/max_positions/golden/summary.json
    - tests/e2e/admission/max_positions/golden/trades.csv
  modified: []

key-decisions:
  - "ADMIT-03 gate-before-sizing: the max_positions gate runs in step 0 of process_signal BEFORE _resolve_signal_quantity, so the audited REJECTED row is built UNSIZED (quantity=0, NOT the FixedQuantity 40) via _reject_unsized_signal -> _build_primary_order(qty=0) — the genuine semantic difference from Phase 7 SIZE-03 (reject fires AFTER sizing, freezes the sized quantity)"
  - "ADMIT-03 cap is per-PORTFOLIO across tickers: the gate counts open positions, not orders; no reservation is taken for the rejected entry (gate fires before reserve), so available_cash stays intact at 6000 (no orphan reservation)"
  - "Multi-ticker shape kept single-portfolio (D-04); multi-portfolio cash isolation is Phase 9"

patterns-established:
  - "Multi-ticker single-portfolio leaf via two co-subscribed ScriptedEmitter instances"
  - "Gate-before-sizing UNSIZED REJECTED orders-snapshot (quantity=0) as the ADMIT-03 lens"

requirements-completed: [ADMIT-02, ADMIT-03, ADMIT-04]

# Metrics
duration: 6min
completed: 2026-06-10
---

# Phase 8 Plan 02: Admission scale/positions leaves (ADMIT-02/03/04) Summary

**Three hand-verified, regression-locked E2E golden leaves — partial scale-out (ADMIT-02), max_positions gate-before-sizing REJECTED (ADMIT-03, quantity=0), and full-exit-then-re-entry (ADMIT-04) — on the shared Plan 01 infra, BTCUSD oracle byte-exact.**

## Performance

- **Duration:** ~6 min (continuation session: lock + finalize)
- **Completed:** 2026-06-10
- **Tasks:** 2 (Task 1 in prior session, Task 2 in this continuation)
- **Files modified:** 17 created

## Accomplishments
- ADMIT-02 (scale_out): partial scale-out via `exit_fraction < 1` keeps the position open between partial sells and closes it at the end — frozen trade golden with multiple SELL rows.
- ADMIT-04 (re_entry): full exit then re-entry on the same ticker produces two clean round-trips (close_position -> get_position None -> fresh-position admission branch).
- ADMIT-03 (max_positions): a new-ticker (BTCUSD) entry while `open_position_count >= max_positions` is audited REJECTED with `triggered_by=admission_max_positions`. First multi-ticker (multi-CSV) E2E leaf: an ETHUSDT occupier holds the single allowed slot.
- All 4 admission leaves (incl. Plan 01 scale_in canary) green in diff mode; BTCUSD oracle byte-exact.

## Task Commits

1. **Task 1: scale_out (ADMIT-02) + re_entry (ADMIT-04) leaves** - `decfb19` (feat) — prior session
2. **Task 2: max_positions (ADMIT-03) gate-before-sizing REJECTED leaf** - `7e47a55` (feat) — this continuation

**Plan metadata:** (this SUMMARY + STATE/ROADMAP commit)

## Files Created/Modified
- `tests/e2e/admission/scale_out/` - ADMIT-02 partial scale-out leaf (scenario, test, bars, trades.csv, summary.json)
- `tests/e2e/admission/re_entry/` - ADMIT-04 two-round-trip leaf (scenario, test, bars, trades.csv, summary.json)
- `tests/e2e/admission/max_positions/` - ADMIT-03 max_positions REJECTED leaf (scenario, test, bars.csv (BTCUSD), bars_eth.csv (ETHUSDT), opt-in orders.csv, trades.csv (empty), summary.json)

## Decisions Made
- **Gate-before-sizing quantity=0 (ADMIT-03):** the max_positions admission gate fires in step 0 of `process_signal` BEFORE `_resolve_signal_quantity` (order_manager.py:335 gate, :347 sizing). The audited REJECTED order is therefore UNSIZED — `_reject_unsized_signal` -> `_build_primary_order(qty=0)` — and the frozen `orders.csv` row carries `quantity=0` (NOT the FixedQuantity 40). This is the genuine semantic difference from Phase 7's SIZE-03 cash-reservation reject, which fires AFTER sizing and freezes the sized quantity. The reject also takes NO cash reservation (gate fires before reserve), so `available_cash`/`final_cash` stays intact at 6000 (no orphan reservation), `final_equity=10000`, `trade_count=0`.
- **Multi-ticker single-portfolio shape (ADMIT-03):** two `ScriptedEmitter` instances (ETHUSDT occupier + BTCUSD over-cap entry) co-subscribe to one portfolio so the portfolio-wide open-position count reaches the cap before the BTC entry is decided. Kept single-portfolio (D-04); multi-portfolio cash isolation is deferred to Phase 9. `spec.ticker="BTCUSD"` so the orders-snapshot query captures exactly the one REJECTED BTCUSD mirror order.

## Deviations from Plan

None - plan executed exactly as written. Both leaf families were authored, hand-verified against their VERIFY derivations, and `--freeze` regression-locked; the human reviewer approved both blocking `checkpoint:human-verify` gates ("approved"). The gate-before-sizing quantity=0 finding is a confirmed engine truth documented in the scenario's VERIFY block and in Decisions above — not an engine change.

## Issues Encountered
None. Both verification suites (admission leaves in diff mode, BTCUSD oracle) re-confirmed green before the Task 2 freeze was locked.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ADMISSION cluster scale/positions side complete (ADMIT-01..04 frozen across Plans 01-02).
- Plan 08-03 still remains in Phase 8 — phase is NOT complete.
- The multi-ticker single-portfolio leaf and the over_cash_reject / max_positions REJECTED-snapshot idioms are copy-templates for Phase 9 multi-portfolio cash-isolation work.

## Self-Check: PASSED

- All created files verified present (max_positions scenario + goldens, scale_out/re_entry trade goldens, SUMMARY).
- Task 1 commit `decfb19` and Task 2 commit `7e47a55` verified in git history.

---
*Phase: 08-admission-position-management-cash-edges*
*Completed: 2026-06-10*
