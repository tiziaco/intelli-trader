---
phase: quick-260622-pmk
plan: 01
subsystem: order_handler/admission
tags: [admission, margin, short-scale-in, solvency, WR-03, P05.1]
requires: [admission_manager.process_signal, PortfolioReadModel.available_cash, PortfolioReadModel.get_position, _reject_unsized_signal, _effective_leverage]
provides: [admission-side short-add margin solvency check, audited CASH_RESERVATION rejection for unfunded short increase]
affects: [itrader/order_handler/admission/admission_manager.py]
tech-stack:
  added: []
  patterns: [symmetric admission-side solvency gate mirroring the long check-and-reserve arm, audited PENDING->REJECTED via _reject_unsized_signal, WR-01 own-prior-lock credit-back]
key-files:
  created: []
  modified:
    - itrader/order_handler/admission/admission_manager.py
    - tests/unit/order/test_admission_rules.py
decisions: [D-06, WR-01, WR-03, reuse OrderTriggerSource.CASH_RESERVATION (no new enum)]
metrics:
  duration: ~20m
  completed: 2026-06-22
---

# Phase quick-260622-pmk Plan 01: Audited Admission Rejection for Unfunded Short Increase Summary

Close P05.1 WR-03 by adding a symmetric admission-side margin solvency check for the admitted short SELL-add: an unfunded short increase now produces exactly ONE audited `CASH_RESERVATION` REJECTED order at admission (mirroring the long arm) instead of slipping past admission to settle silently or fail-fast abort the backtest.

## What Was Built

**Task 1 (RED, commit `5036591`)** — `tests/unit/order/test_admission_rules.py`:
- `test_unfunded_short_increase_is_rejected_via_audited_path`: open SHORT 100 @ 40 (lev 2) → buying_power 16000; explicit SELL-add 1000 @ 40 → prospective_lock 22000 > 16000 → must yield ONE audited `CASH_RESERVATION` REJECTED order, queue empty, free cash unchanged. Failed RED with `assert harness.queue.empty()` (the add was admitted+emitted on the current code — the exact buggy behavior).
- `test_funded_short_increase_still_admits`: explicit SELL-add 100 @ 40 → prospective_lock 4000 <= 16000 → admitted, emitted. Non-regression guard (passed both before and after).
- `_open_short_with_leverage` helper pins the position leverage so the admission prior-lock basis (`existing_notional / effective_leverage`) matches the settlement basis (`position.leverage`, WR-01).

**Task 2 (GREEN, commit `9270146`)** — `itrader/order_handler/admission/admission_manager.py`:
- New `process_signal` step 3c (after the BUY check-and-reserve gate, before bracket assembly): guarded to `primary.action is Side.SELL` with an OPEN SHORT for the ticker.
- Computes `prospective_lock = (existing_notional + add_notional) / effective_leverage` and `buying_power = available_cash + own_prior_lock`, crediting back the existing short's own prior lock (`existing_notional / effective_leverage`) — mirroring `cash_manager.assert_lock_fits_buying_power` (WR-01) so a fundable add is never over-rejected.
- On `prospective_lock > buying_power`: emits an audited rejection via `_reject_unsized_signal(..., triggered_by=OrderTriggerSource.CASH_RESERVATION, operation_type=OrderOperationType.CASH_RESERVATION)`. No reservation booked (D-06: a SELL credits cash), nothing emitted, queue empty.
- Spot/no-margin arm kept division-free via a real `if self._enable_margin` branch (Pitfall 4 — no forced `/1`).
- Updated the short fall-through docstring in `_enforce_position_admission` to note the new symmetric admission-side solvency check.

## Verification Results

| Gate | Command | Result |
|------|---------|--------|
| New + full admission suite | `pytest tests/unit/order/test_admission_rules.py -q` | **41 passed** (both new tests green) |
| Funded short e2e leaves (frozen) | `pytest tests/e2e/short_scale_in tests/e2e/short_scale_in_partial_cover -q` | **2 passed** (unchanged) |
| SMA_MACD oracle (byte-exact) | `pytest tests/integration/test_backtest_oracle.py -q` | **3 passed** (134 / 46189.87730727451 intact) |
| mypy strict | `poetry run mypy --strict itrader` | **Success: no issues found in 165 source files** |

## Deviations from Plan

None — plan executed exactly as written.

The RED reason observed in this harness was "admitted+emitted (queue not empty)" rather than a settlement-time `InvalidTransactionError`; the plan explicitly sanctioned either RED form ("by raising InvalidTransactionError at settlement OR by admitting+emitting"). The unfunded add does not settle in the RED test (it only calls `on_signal`), so no settlement abort occurs — the queue-not-empty assertion is the deterministic RED trigger.

## Notes

- No new `FillStatus`, no new `OrderTriggerSource` — reuses `CASH_RESERVATION` (the long-arm trigger), as required.
- The SELL books NO admission-side reservation — the new gate is a solvency CHECK that emits an audited rejection on failure only (D-06 unchanged; `available_cash` unchanged across both the funded admit and the unfunded reject).
- TABS preserved in `admission_manager.py`; 4-space in the test file. No `Decimal(float)` introduced.

## Self-Check: PASSED

- Created files: none expected.
- Modified files present: `itrader/order_handler/admission/admission_manager.py`, `tests/unit/order/test_admission_rules.py` — FOUND.
- Commits: `5036591` (RED test), `9270146` (GREEN impl) — FOUND in git log.
