---
phase: quick-260623-gao
verified: 2026-06-23T00:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  note: initial verification
---

# Quick Task quick-260623-gao Verification Report

**Task Goal:** Implement engine over-sell protection A (spot settlement over-close
guard mirroring CR-02) + B (cancel orphaned bracket children on flatten), via TDD,
WITHOUT drifting the SMA_MACD oracle (134 trades / final_equity 46189.87730727451).
**Verified:** 2026-06-23
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Spot over-close SELL (sell > held) raises InvalidTransactionError before mutation | ✓ VERIFIED | `portfolio.py:338-343` raises before `net_delta` step; `test_spot_over_close_fill_fails_loud` asserts `pytest.raises(InvalidTransactionError)` and passes |
| 2 | Exact full-close (sell == held) still settles to flat | ✓ VERIFIED | `test_spot_exact_full_close_still_succeeds` passes (positions==0, closed==1) |
| 3 | Partial close (sell < held) keeps position open | ✓ VERIFIED | `test_spot_partial_close_still_succeeds` passes (net_quantity==Decimal("3")) |
| 4 | EXECUTED flatten cancels that portfolio+ticker resting bracket children | ✓ VERIFIED | `reconcile_manager.py:315-330` (get_position is None → cancel); `test_flatten_by_fill_cancels_resting_bracket_children` passes |
| 5 | Other tickers / portfolios / non-bracket orders never cancelled by a flatten | ✓ VERIFIED | scope guard `active.ticker == fill.ticker AND parent_order_id is not None AND active.id != order.id`; `test_flatten_does_not_cancel_other_ticker_children`, `test_flatten_does_not_cancel_when_position_still_open`, `test_non_executed_fill_does_not_trigger_flatten_cancel` all pass |
| 6 | SMA_MACD oracle byte-exact: 134 / 46189.87730727451 | ✓ VERIFIED | I ran `pytest tests/integration/test_backtest_oracle.py` → 3 passed; frozen golden `summary.json` holds `trade_count: 134`, `final_equity: 46189.87730727451`; `tests/golden/` untouched by this task |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/portfolio.py` | CR-02 guard mirrored into `_process_transaction_spot` before net_delta/funds/mutation/cash | ✓ VERIFIED | Lines 316-343: `is_increase` + `transaction.quantity > prior_qty` → raise, BEFORE `net_delta = transaction.net_cash_delta` (line 348). TAB-indented, Decimal, no new imports |
| `itrader/order_handler/reconcile/reconcile_manager.py` | Orphaned-bracket cancel on flatten in EXECUTED arm | ✓ VERIFIED | Lines 301-330: `get_position(...) is None` → iterate `get_active_orders` → `_cancel_order` per scoped child. Read-model only; coordinator callback only |
| `tests/unit/portfolio/test_spot_oversell_guard.py` | Fix A regression (4 tests) | ✓ VERIFIED | 4 tests, all pass; over-close asserts the raise |
| `tests/unit/order/test_reconcile_orphan_flatten.py` | Fix B regression + negative scope (4 tests) | ✓ VERIFIED | 4 tests incl. 3 negative-scope, all pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `portfolio.py::_process_transaction_spot` | InvalidTransactionError | `if not is_increase and transaction.quantity > prior_qty: raise` | ✓ WIRED | Pattern present at portfolio.py:338 |
| `reconcile_manager.py::on_fill` | `self._cancel_order` | `get_position(...) is None` → cancel scoped children | ✓ WIRED | reconcile_manager.py:316-328 |

### Behavioral Spot-Checks (run by verifier)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed in 5.36s | ✓ PASS |
| New + modified test files | `pytest test_spot_oversell_guard.py test_reconcile_orphan_flatten.py test_reconcile_manager.py test_order_manager.py -q` | 40 passed | ✓ PASS |
| Strict type check | `mypy itrader` | Success: no issues found in 187 source files | ✓ PASS |
| Golden baseline values | `grep trade_count/final_equity tests/golden/summary.json` | 134 / 46189.87730727451 | ✓ PASS |
| Golden untouched | `git diff --stat 98cbdcc..HEAD -- tests/golden/` | empty | ✓ PASS |

### Out-of-Scope Confirmation (Fix C NOT implemented)

| Check | Result | Status |
|-------|--------|--------|
| `git diff 98cbdcc..HEAD -- itrader/portfolio_handler/position/position.py` | empty | ✓ Fix C surface (net_quantity / market_value / avg_price) untouched |
| Full changed-file set | reconcile_manager.py, portfolio.py, + 4 test files only | ✓ No sizing/admission/matching changes |

## Verdict on Deviation #3 (modified `test_filled_parent_keeps_bracket_children_active`)

**LEGITIMATE — test-only artifact, mirrors production. No masking of a real risk.**

The executor reordered the test to call `harness.ptf_handler.on_fill(fill)` BEFORE
`harness.handler.on_fill(fill)`. I verified the claim against the real route rather
than trusting the SUMMARY:

- **Production route confirmed** (`full_event_handler.py:80-83`): `_routes[EventType.FILL]`
  is `[self.portfolio_handler.on_fill, self.order_handler.on_fill]` — portfolio settles
  positions/cash FIRST (comment "1) positions/cash"), order-mirror reconcile SECOND
  ("2) order-mirror reconciliation"). List order IS execution order in this engine.
- **Why Fix B is safe at the route level**: by the time `on_fill` reconcile reads
  `get_position`, the portfolio has already established the opening position, so
  `get_position` is non-None and the flatten-cancel correctly does NOT fire on a
  just-opened bracket. The pre-fix test bypassed `ptf_handler.on_fill`, so it presented
  a *phantom-flat* read-model that the new Fix B logic (correctly, given that input)
  treated as a flatten. The test was wrong, not the guard.
- **Harness uses a REAL PortfolioHandler** (`test_order_manager.py:70-72`): `ptf_handler`
  is a live `PortfolioHandler`, and `OrderHandler` is wired with that same instance as
  its read-model. The reordered call therefore exercises real position state, faithfully
  reproducing production — not a stubbed always-non-None fake.
- **Fragility assessment**: Fix B's correctness does depend on the portfolio-first FILL
  route ordering. This is the engine's documented, load-bearing dispatch contract
  (CLAUDE.md: "list order IS execution order"; the route comments encode it explicitly),
  and the same ordering is already relied on by `_apply_executed` (WR-02 comment:
  "FILL dispatches portfolio-first"). The dependency is pre-existing and architecturally
  pinned, not newly introduced fragility. The full oracle + e2e + 1231-test suite run the
  real route and stayed green, which is the integration-level guard against a future
  reorder. **Acceptable.**

## Anti-Patterns Found

None. Source edits are TAB-indented (match the files), Decimal end-to-end, no debt
markers (TBD/FIXME/XXX) introduced, no stubs, no clamp shortcut (fail-fast raise as
specified). Comments are decision-anchored (CR-02 / OVERSELL-A / OVERSELL-B / D-04 /
D-08) in the established style.

## Gaps Summary

None. All six must-have truths are verified against the actual codebase (not SUMMARY
claims): both source guards exist, are correctly placed and scoped, are regression-
tested (RED→GREEN per the commit trail), and the SMA_MACD oracle is byte-exact at
134 / 46189.87730727451 — verified by running the oracle myself and confirming the
frozen golden baseline was untouched. Fix C is confirmed out of scope. The one
behavioral deviation (#3) is a legitimate test-only correction that mirrors the
production FILL route.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
