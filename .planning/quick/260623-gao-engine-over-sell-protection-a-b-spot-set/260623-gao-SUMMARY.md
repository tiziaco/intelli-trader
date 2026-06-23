---
phase: quick-260623-gao
plan: 01
subsystem: portfolio-handler, order-handler
tags: [oversell, spot-settlement, bracket-cancel, oracle-dark, tdd]
requires: [".planning/debug/spot-long-only-oversell.md"]
provides:
  - "Fix A: CR-02 over-close guard on the spot settlement path (fail-loud, no clamp)"
  - "Fix B: orphaned-bracket cancel on flatten-by-fill in ReconcileManager.on_fill"
affects:
  - itrader/portfolio_handler/portfolio.py
  - itrader/order_handler/reconcile/reconcile_manager.py
tech-stack:
  added: []
  patterns: ["fail-fast settlement guard (mirror CR-02)", "read-model-gated flatten-cancel via injected coordinator callback"]
key-files:
  created:
    - tests/unit/portfolio/test_spot_oversell_guard.py
    - tests/unit/order/test_reconcile_orphan_flatten.py
  modified:
    - itrader/portfolio_handler/portfolio.py
    - itrader/order_handler/reconcile/reconcile_manager.py
    - tests/unit/order/test_reconcile_manager.py
    - tests/unit/order/test_order_manager.py
decisions:
  - "OVERSELL-A: spot over-close fails loud (InvalidTransactionError) before any mutation; no clamp — matches margin path fail-fast"
  - "OVERSELL-B: flatten-cancel gated on read-model get_position == None and the production FILL route order (portfolio first, then order reconcile)"
metrics:
  duration: ~7m
  completed: 2026-06-23
requirements: [OVERSELL-A, OVERSELL-B]
---

# Phase quick-260623-gao Plan 01: Engine Over-Sell Protection (A + B, Spot Settlement) Summary

Two oracle-dark engine guards for the spot LONG_ONLY over-sell / phantom-equity bug:
**Fix A** mirrors the CR-02 margin over-close guard into the spot settlement path so a
reducing SELL exceeding held quantity raises `InvalidTransactionError` before any mutation;
**Fix B** cancels a portfolio+ticker's orphaned resting bracket children when an EXECUTED
fill flattens that position, removing the seed channel that bypassed admission. The SMA_MACD
spot oracle stays byte-exact (134 trades / final_equity 46189.87730727451).

## What Was Built

- **Fix A (portfolio.py `_process_transaction_spot`):** inserted the CR-02 over-close guard
  BEFORE the `net_delta` / funds-invariant / position-mutation / cash-apply steps. A reducing
  fill (`not is_increase`) whose `transaction.quantity > prior_qty` raises
  `InvalidTransactionError`. No clamp; fail-fast, exactly like the margin path. TAB-indented;
  no new imports (all already present).
- **Fix B (reconcile_manager.py `on_fill`, EXECUTED arm):** after the mirror update and the
  existing WR-05 / PercentFromFill blocks, when `fill_event.status == EXECUTED` and the
  injected read-model reports `get_position(portfolio_id, ticker) is None` (now FLAT), iterate
  `get_active_orders(portfolio_id)` and cancel only orders where `ticker == fill_event.ticker`
  AND `parent_order_id is not None` AND `id != order.id`, via the injected `_cancel_order`
  coordinator callback, collecting returned CANCEL events into `out_events`. Stays in the order
  domain; reads the portfolio only through the read-model; queue-only respected. TAB-indented.

## TDD: RED -> GREEN Evidence

**Fix A (`tests/unit/portfolio/test_spot_oversell_guard.py`)**
- RED (commit `15f0b45`): `test_spot_over_close_fill_fails_loud` FAILED with
  `Failed: DID NOT RAISE InvalidTransactionError` — the SELL 5 of held 1 settled silently
  (a second "Transaction recorded" log proved the over-sell committed). The 3 non-regression
  tests (exact-close / partial-close / scale-in) PASSED. `1 failed, 3 passed`.
- GREEN (commit `046b958`): after porting the guard, all 4 oversell tests + the full
  `test_portfolio.py` (27 tests incl. CR-02 margin analogs) PASS — `31 passed`.

**Fix B (`tests/unit/order/test_reconcile_orphan_flatten.py`)**
- RED (commit `419d1fa`): `test_flatten_by_fill_cancels_resting_bracket_children` FAILED with
  `AssertionError: assert 'C-BTC' in []` — `cancel_order` was never called. The 3 negative-scope
  tests (other-ticker / still-open / non-EXECUTED) PASSED (they assert nothing is cancelled, which
  matched pre-fix behavior). `1 failed, 3 passed`.
- GREEN (commit `c004672`): after adding the flatten-cancel block, all 4 flatten tests + all 6
  existing `test_reconcile_manager.py` tests PASS — `10 passed`.

## Oracle Gate (observed numbers)

- `tests/integration/test_backtest_oracle.py`: **3 passed** — byte-exact, NO drift.
  Observed golden summary: **trade_count: 134 / final_equity: 46189.87730727451**.
  Both guards are oracle-dark exactly as designed: SMA_MACD never over-sells (exits clamp to
  net_quantity) and declares no brackets.
- `tests/e2e -m e2e`: **72 passed**.
- Full suite `tests`: **1231 passed** (no failures, no `filterwarnings=error` tripwires).
- `mypy itrader`: **Success: no issues found in 187 source files** (--strict).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Test isolation artifact] Routed portfolio fill before reconcile in `test_filled_parent_keeps_bracket_children_active`**
- **Found during:** Task 5 (full-suite gate).
- **Issue:** Fix B reads `get_position` to detect a flatten. The pre-existing
  `test_filled_parent_keeps_bracket_children_active` (test_order_manager.py) exercises ONLY the
  order domain — it never routes the parent's opening fill through `portfolio_handler.on_fill`,
  so the real `PortfolioHandler` read-model reported the just-opened position as FLAT (None).
  Fix B then wrongly cancelled the just-opened position's protective children. This is a test
  isolation artifact, NOT a production bug: the production FILL route
  (`EventHandler._routes[FILL]`) runs `portfolio_handler.on_fill` BEFORE `order_handler.on_fill`,
  so by reconcile time the opening fill has already established the position and `get_position`
  is non-None — flatten-cancel correctly does not fire. Confirmed by the oracle + e2e suites
  (which run the full route) staying green throughout.
- **Fix:** Updated the test to mirror the production route order (call `ptf_handler.on_fill(fill)`
  before `handler.on_fill(fill)`), with a comment documenting the OVERSELL-B interaction. No
  source change to the guard.
- **Files modified:** tests/unit/order/test_order_manager.py
- **Commit:** `895099b`

**2. [Rule 3 — Protocol completeness] Extended existing reconcile test fakes**
- **Found during:** Task 4 (Fix B GREEN).
- **Issue:** Fix B's EXECUTED arm now calls `get_position` / `get_active_orders` on the
  read-model+storage and reads `fill_event.ticker`. The existing `test_reconcile_manager.py`
  fakes (`_RecordingPortfolio`, `_FakeStorage`, `_FakeFill`) predated these reads.
- **Fix:** Added `get_position` (returns None) and `get_active_orders` (returns []) and a
  `.ticker` attribute to those fakes — their scenarios carry no resting children, so the
  flatten-cancel path is a clean no-op for them.
- **Files modified:** tests/unit/order/test_reconcile_manager.py
- **Commit:** `c004672`

**3. [Rule 1 — Test data] Repriced non-regression spot opens to fit cash**
- **Found during:** Task 1 (Fix A RED).
- **Issue:** Initial non-regression tests opened 4 units @ 89591 (358364) which exceeds the
  $150000 spot cash and tripped `assert_funds_invariant` (an unrelated InsufficientFundsError,
  not the guard under test).
- **Fix:** Repriced the partial-close / scale-in non-regression opens to @ 1000 so the notional
  fits the budget; the over-close repro stays @ 89591 (BUY 1 fits). Fixed in the same RED commit.
- **Files modified:** tests/unit/portfolio/test_spot_oversell_guard.py
- **Commit:** `15f0b45`

## Out of Scope (untouched, as planned)

- Fix C (sign-aware `net_quantity` / `market_value` / `avg_price`) — owner-gated, result-changing.
- No changes to sizing / admission / matching beyond the Fix-B bracket-cancel seam.

## Commits

- `15f0b45` test(quick-260623-gao): add RED spot over-close guard regression (Fix A)
- `046b958` fix(quick-260623-gao): port CR-02 over-close guard into spot settlement (Fix A)
- `419d1fa` test(quick-260623-gao): add RED flatten-cancel orphaned-bracket regression (Fix B)
- `c004672` fix(quick-260623-gao): cancel orphaned bracket children on flatten-by-fill (Fix B)
- `895099b` test(quick-260623-gao): route portfolio fill before reconcile in filled-parent test

## Self-Check: PASSED

- Created files exist: test_spot_oversell_guard.py, test_reconcile_orphan_flatten.py — FOUND.
- All 5 commits present in git log — FOUND.
- Oracle byte-exact; full suite (1231) + e2e (72) green; mypy clean.
