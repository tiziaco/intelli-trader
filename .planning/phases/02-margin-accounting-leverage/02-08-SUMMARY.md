---
phase: 02-margin-accounting-leverage
plan: 08
subsystem: order
tags: [leverage, margin, order-factory, admission, portfolio-settlement, decimal]

# Dependency graph
requires:
  - phase: 02-margin-accounting-leverage (02-07)
    provides: "LEV-03 effective-leverage threading signal->order->fill->transaction->position (MARKET arm)"
provides:
  - "CR-01 closed: levered LIMIT/STOP entries carry the admission-clamped effective leverage onto the Order entity (LEV-03 complete for ALL order types)"
  - "CR-02 mitigated: margin over-close fill fails loud (InvalidTransactionError) before any re-lock/settlement"
  - "deferred-items.md tracks the residual review findings (CR-02-residual + WR-01..05 + IN-01..03) for Phase 3 / future"
affects: [03-shorts-borrow-carry, 04-liquidation-cross-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typed order factories (new_limit_order/new_stop_order) carry keyword-only leverage, mirroring new_order (order.py:215)"
    - "Margin close arm fails loud on an over-close/flip fill (fail-loud seam via the existing InvalidTransactionError family)"

key-files:
  created: []
  modified:
    - itrader/order_handler/order.py
    - itrader/order_handler/admission/admission_manager.py
    - itrader/portfolio_handler/portfolio.py
    - tests/unit/order/test_order.py
    - tests/unit/order/test_admission_rules.py
    - tests/unit/portfolio/test_portfolio.py
    - .planning/phases/02-margin-accounting-leverage/deferred-items.md

key-decisions:
  - "CR-02 scope = fail-loud GUARD only; full flip-settlement economics deferred to Phase 3 (shorts), where flips become reachable"
  - "Reused the existing InvalidTransactionError (core/exceptions/portfolio.py) for the over-close guard — no new exception class invented"
  - "Guard placed BEFORE process_position_update (the position-mutating call) so an over-close never mutates/re-locks/settles"

patterns-established:
  - "Effective leverage threads through ALL three order-build arms (MARKET/LIMIT/STOP) identically — no order-type-specific leverage gaps"

requirements-completed: [LEV-03]

# Metrics
duration: 12min
completed: 2026-06-15
---

# Phase 2 Plan 08: Code-Review Gap Closure (CR-01 / CR-02) Summary

**Levered LIMIT/STOP entries now carry the admission-clamped effective leverage end-to-end (LEV-03 complete for all order types), and a margin over-close fill fails loud instead of silently mis-settling a flipped position — both oracle-dark, SMA_MACD holds 134/46189.87730727451 byte-exact.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-15T13:50:00Z
- **Completed:** 2026-06-15T14:00:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- **CR-01 closed (LEV-03 complete for all order types):** `Order.new_limit_order` and `Order.new_stop_order` now accept a keyword-only `leverage: Decimal = Decimal("1")` and set it via `leverage=to_money(leverage)` on the entity, mirroring `new_order` (order.py:215). `AdmissionManager._build_primary_order` passes `leverage=effective_leverage` on the LIMIT and STOP arms (not just MARKET). Position-life locked margin (`aggregate_notional / leverage`) now equals the admission reservation (`notional / effective_leverage`) for every order type.
- **CR-02 mitigated:** the margin close arm in `Portfolio._process_transaction_margin` now raises `InvalidTransactionError` when a reducing fill's `transaction.quantity > prior_qty` (an over-close / flip attempt) — BEFORE any position mutation, re-lock, or settlement. An over-close can never silently re-lock a flipped position at the wrong leverage and settle a wrong cash delta.
- **Residual review findings tracked:** `deferred-items.md` now carries a "Code review residuals (02-REVIEW.md)" table with CR-02-residual + WR-01..05 + IN-01..03 (severity + target), and notes CR-01 and the CR-02 guard CLOSED.

## Task Commits

Each task committed atomically (TDD: RED then GREEN for tasks 1 and 2):

1. **Task 1 RED: failing tests for LIMIT/STOP leverage threading** - `fff0b3b` (test)
2. **Task 1 GREEN: thread effective leverage through LIMIT/STOP factories** - `a27e275` (feat)
3. **Task 2 RED: failing test for margin over-close fail-loud guard** - `bc35629` (test)
4. **Task 2 GREEN: fail loud on margin over-close fill** - `0448ad9` (feat)
5. **Task 3: track residual review findings** - `8b45ca3` (docs)

## Files Created/Modified

- `itrader/order_handler/order.py` - `new_limit_order`/`new_stop_order` accept keyword-only `leverage`, set on entity via `to_money` (TABS)
- `itrader/order_handler/admission/admission_manager.py` - LIMIT/STOP arms pass `leverage=effective_leverage` (TABS)
- `itrader/portfolio_handler/portfolio.py` - over-close guard raises `InvalidTransactionError` before mutation; imports `InvalidTransactionError` (TABS)
- `tests/unit/order/test_order.py` - `TestTypedFactoryLeverage` (4 factory leverage tests) + `Decimal` import
- `tests/unit/order/test_admission_rules.py` - MARKET baseline + LIMIT/STOP `_build_primary_order` clamped-leverage tests
- `tests/unit/portfolio/test_portfolio.py` - over-close fail-loud test + full-close/partial-close regression guards
- `.planning/phases/02-margin-accounting-leverage/deferred-items.md` - code-review residuals table

## Decisions Made

- **CR-02 = guard only, not full fix.** The plan and 02-REVIEW both scope the full flip-settlement economics (split a flip into full-close + fresh-open, or correct `realised_increment` to the clamped quantity) to Phase 3 where shorts/flips become reachable. This plan adds only the cheap fail-loud guard so a flip fill can never silently mis-settle in the interim. Tracked as CR-02-residual in deferred-items.md.
- **Reused `InvalidTransactionError`** (the existing fail-loud portfolio exception family) rather than inventing a new class — it is the established invalid-transaction seam in `core/exceptions/portfolio.py`.
- **Guard placement BEFORE `process_position_update`** so the over-close fails before any state mutation, re-lock, or cash settlement (rejecting cleanly, not mid-settlement).

## Deviations from Plan

None - plan executed exactly as written. (Test homes: Task 2's margin-settlement tests were added to `tests/unit/portfolio/test_portfolio.py` — the actual home of the `margin_portfolio` fixture and `_process_transaction_margin` settlement tests — rather than `test_portfolio_handler.py`; the plan's `files_modified` listed the latter, but the margin close arm is exercised only by the `test_portfolio.py` harness. This is the correct test home, not a behavioral deviation.)

## Issues Encountered

None. RED→GREEN clean for both TDD tasks; mypy `--strict` clean throughout.

## Verification

- `poetry run pytest tests/unit/order tests/unit/portfolio` — green (CR-01 factory + admission tests; CR-02 guard + regression tests).
- Byte-exact oracle: `poetry run pytest tests/integration/test_backtest_oracle.py` — 3 passed, SMA_MACD 134/46189.87730727451 byte-exact (leverage threading + over-close guard are oracle-dark with `enable_margin` off).
- `poetry run mypy itrader` — clean, 185 source files.
- `make test` — 1089 passed.
- `deferred-items.md` contains WR-04 (and the full residual table).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- LEV-03 is now complete for all order types — Phase 3 (shorts) inherits a leverage-correct order pipeline for LIMIT/STOP entries.
- Phase 3 inherits the tracked residuals: CR-02-residual (full flip settlement), WR-01 (settlement-side solvency assertion), WR-02 (maintenance_margin None-guard), WR-03 (margin-lock release symmetry), WR-04 (≥1 leverage floor / zero guard), WR-05 (per-open commission accumulator), and the IN-01..03 doc/style items.

## Self-Check: PASSED

- All modified files present on disk (order.py, admission_manager.py, portfolio.py, deferred-items.md, SUMMARY.md).
- All task commits present in git history: `fff0b3b`, `a27e275`, `bc35629`, `0448ad9`, `8b45ca3`.

---
*Phase: 02-margin-accounting-leverage*
*Completed: 2026-06-15*
