---
phase: quick-260623-h6i
plan: 01
subsystem: portfolio_handler
tags: [over-close-guard, tolerance, decimal, oversell, margin-cr-02, tdd]
requires: [260623-gao]
provides: ["Tolerance-aware over-close guards (spot + margin CR-02)"]
affects: [itrader/portfolio_handler/portfolio.py]
tech-stack:
  added: []
  patterns: ["Reuse PositionManager.tolerance (1e-5) for sub-quantum over-close absorption"]
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/portfolio.py
    - tests/unit/portfolio/test_spot_oversell_guard.py
    - tests/unit/portfolio/test_portfolio.py
decisions:
  - "Reuse existing PositionManager.tolerance (Decimal('0.00001')); no new constant"
  - "Raise only on GROSS over-sell; absorb sub-close-tolerance Decimal dust as a clean close via _should_close_position"
metrics:
  completed: 2026-06-23
  tasks: 3
  files_modified: 3
---

# Phase quick-260623-h6i Plan 01: Refine Over-Close Guard With Tolerance Summary

Both over-close guards in `portfolio.py` (spot `_process_transaction_spot` ~:346 and
margin CR-02 `_process_transaction_margin` ~:444) now compare
`(transaction.quantity - prior_qty) > self.position_manager.tolerance` (reusing the
existing 1e-5 `PositionManager.tolerance`) instead of the strict `transaction.quantity > prior_qty`,
so sub-quantum Decimal requantization dust (the 1E-27 per-add bracket-child excess on a
pyramided position) is absorbed as a clean full close while a GROSS over-sell still aborts
loud — phantom-equity protection preserved, pyramiding/bracketed backtests unblocked.

## What Changed

- **Spot guard** (`_process_transaction_spot`): tolerance-aware condition + decision-anchored
  comment citing 260623-gao (guard origin) and the 260623-h6i debug session.
- **Margin CR-02 guard** (`_process_transaction_margin`): identical tolerance-aware condition
  + comment update. Side-agnostic (covers SHORT over-cover too).
- **Tests**: added `test_spot_sub_tolerance_over_close_absorbs_as_clean_close` (spot) and
  `test_margin_sub_tolerance_over_close_absorbs_as_clean_close` (margin). Both use Decimal-typed
  qty (`Decimal("1") + Decimal("1e-9")`) so the 1e-9 excess is exact, not a float artifact.
  Existing GROSS `*_fails_loud` tests unchanged.

## TDD RED -> GREEN Evidence

**RED (after Task 1, before fix):**
`pytest test_spot_oversell_guard.py test_portfolio.py -k "sub_tolerance or fails_loud"`
→ `2 failed, 3 passed`. The 2 new sub_tolerance tests FAILED (guard raised
`InvalidTransactionError` on the 1e-9 dust); the 3 GROSS `*_fails_loud` tests PASSED.

**GREEN (after Task 2 fix):**
`pytest test_spot_oversell_guard.py test_portfolio.py -v` → `33 passed`. Both new
sub_tolerance tests GREEN; both GROSS `*_fails_loud` (spot hold 1/sell 5; margin hold 2/sell 3)
+ `test_margin_short_over_cover_fill_fails_loud` STILL raise; all partial/exact non-regression
tests green.

## Validation Gate (Task 3)

| Gate | Command | Result |
| ---- | ------- | ------ |
| Oracle (byte-exact, hard stop) | `pytest tests/integration/test_backtest_oracle.py` | **3 passed** — `trade_count=134`, `final_equity=46189.87730727451`, `final_cash=46189.87730727451` (byte-exact, NO drift) |
| e2e | `pytest tests/e2e -m e2e` | **72 passed** |
| Full suite | `pytest tests` | **1233 passed** (margin CR-02 suite green) |
| mypy --strict | `mypy itrader` | **Success: no issues in 187 source files** |

All runs from the MAIN checkout with `PYTHONPATH="$PWD"` (edits resolve live; no editable-install shadowing). Oracle is byte-exact — guard is oracle-dark (SMA_MACD never pyramids brackets).

## Guard-Site Verification

`grep -c "position_manager.tolerance" itrader/portfolio_handler/portfolio.py` → **2** (spot :346, margin :444). Both use TABS, no new constant introduced. Money stays Decimal end-to-end (subtraction + comparison are Decimal).

## Deviations from Plan

None — plan executed exactly as written.

## Commits

- `69af7d0` test(quick-260623-h6i): RED sub-tolerance over-close absorbs as clean close
- `09d49b1` fix(quick-260623-h6i): tolerance-aware over-close guard at spot + margin sites

## Self-Check: PASSED

- itrader/portfolio_handler/portfolio.py — FOUND (2 tolerance guard sites, TABS)
- tests/unit/portfolio/test_spot_oversell_guard.py — FOUND (sub-tolerance test added)
- tests/unit/portfolio/test_portfolio.py — FOUND (margin sub-tolerance test added)
- Commit 69af7d0 — FOUND
- Commit 09d49b1 — FOUND
