---
phase: 06-order-lifecycle-time-in-force
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - itrader/core/enums/execution.py
  - itrader/core/enums/order.py
  - itrader/core/portfolio_read_model.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/lifecycle/lifecycle_manager.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/trading_system/backtest_runner.py
  - tests/e2e/matching/never_fill/scenario.py
  - tests/integration/test_expire_non_cascade.py
  - tests/unit/core/test_enums_expire.py
  - tests/unit/core/test_portfolio_read_model.py
  - tests/unit/execution/test_simulated_expire.py
  - tests/unit/order/test_expire_all_resting.py
  - tests/unit/order/test_order_command_enum.py
  - tests/unit/order/test_reconcile_expired.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: clean
fix_status: all_fixed
fix_note: "2 INFO (doc drift from the WR-02 Protocol widening) resolved in commit 4b407d9; full fix record in 06-REVIEW-FIX.md"
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found (no BLOCKER/WARNING — 2 INFO documentation-drift items only)

## Summary

This is iteration 2 of the `--auto` fix loop for Phase 6 (Order Lifecycle & Time-in-Force,
LIFE-01). I verified all six prior findings (WR-01, WR-02, WR-03, IN-01, IN-02, IN-03) and
adversarially traced the EXPIRE lifecycle end-to-end (enum → exchange arm → run-end sweep →
reconcile → cash release) hunting for regressions introduced by the fixes.

**All six prior findings are correctly and completely fixed:**

- **WR-01** (b67ab0d): the EXPIRE arm in `simulated.py:294-312` now documents that the
  `FillEvent(EXPIRED)` deliberately omits `time=` and inherits the order's decision time,
  matching the CANCEL arm convention. Correct — an EXPIRE is a command acknowledgement, not a
  bar-produced match.
- **WR-02** (f4fe310, 91c01cb): `active_portfolio_ids()` is now a first-class
  `PortfolioReadModel` Protocol member (`portfolio_read_model.py:196-212`), implemented on the
  concrete `PortfolioHandler` (`portfolio_handler.py:230-232`), and consumed by the sweep
  (`lifecycle_manager.py:250`). The `# type: ignore[attr-defined]` concrete-handler coupling is
  gone; the contract test widened to 8 members and the missing-member negative test
  (`_MissingReserveFake`) still proves narrowness is enforced. `active_portfolio_ids()` and the
  test's `get_active_portfolios()` iterate `self._portfolios.values()` under the identical
  `is_active()` filter, so the deterministic D-10 sweep order is provably preserved.
- **WR-03** (f4fe310): the run-end sweep `except` now logs-then-`raise` (fail-fast), consistent
  with the documented backtest fail-fast policy (CLAUDE.md) and mirroring the reconcile path. I
  confirmed this does NOT half-sweep silently: a mid-sweep failure aborts the run loudly rather
  than returning a `failure_result` the facade never inspected. The dropped `failure_result`
  path was removed entirely; the facade's now-always-true `if result.success` guard is harmless
  dead-defensive code, not a bug.
- **IN-01/IN-02** (ce40208): `_UNREALISTIC_PRICE_THRESHOLD = Decimal("1000000")` is named and
  Decimal-typed (Decimal-vs-Decimal comparison preserved); the block-level independence comment
  on the `_classify` priority scan is clarified.
- **IN-03** (ef8b210): the dual-edit requirement (terminal `FillStatus` vocabulary encoded in
  both `_classify` and the `on_fill` dispatch arms) is documented at `reconcile_manager.py:107`,
  backed by the `else: raise NotImplementedError` loud-fail net.

**No new BLOCKER or WARNING defects were introduced.** I specifically verified:

- The EXPIRED reconcile arm's idempotency (D-09 LANDMINE): a run-end-swept order that is already
  locally EXPIRED, then reconciled by the returning `FillEvent(EXPIRED)`, hits
  `VALID_ORDER_TRANSITIONS[EXPIRED] == []` so `expire_order` returns False with no raise; the
  terminal release still runs and the second release is an idempotent no-op. Correct by design.
- The double-release on the sweep path (local `release` in `expire_all_resting` then the
  reconcile `finally` release) is idempotent — `CashManager.release_reservation` pops nothing on
  the second call. No buying-power corruption.
- The run-end drain is provably non-cascading (EXPIRE emits no SignalEvent / no OrderEvent(NEW));
  the integration test pins this end-to-end.
- WR-05 orphaned-child cancel correctly does NOT fire for EXPIRED parents — at run end every
  resting child is itself swept to EXPIRED via its own active-orders entry, so no orphan can
  exist.
- Money stays Decimal end-to-end across every changed money path; handler-module tab indentation
  and core/ 4-space indentation are respected on the new code.

The two remaining items are documentation drift only.

## Info

### IN-01: Stale "six members ONLY" comment after the Protocol grew to eight

**File:** `itrader/portfolio_handler/portfolio_handler.py:224`
**Issue:** The class-section comment reads "The order domain reads portfolio state through these
six members ONLY", but the `PortfolioReadModel` Protocol now has EIGHT members — the original six
plus `total_equity` (Plan 07-01) and `active_portfolio_ids` (added THIS phase, WR-02). The newly
added `active_portfolio_ids` method (lines 230-232) sits directly under this comment, making the
"six members ONLY" claim actively false for code introduced in this very phase. A future reader
relying on this comment would undercount the read boundary. (The sibling
`portfolio_read_model.py:32` "exactly SIX members" comment carries the same drift, predating this
phase via Plan 07-01.)
**Fix:** Update the count to reflect the current surface, e.g.:
```python
# The order domain reads portfolio state through these eight members ONLY
# (itrader/core/portfolio_read_model.py): the original six (D-13/OQ1) plus
# total_equity (Plan 07-01) and active_portfolio_ids (WR-02, LIFE-01 sweep).
```

### IN-02: Stale `get_active_portfolios()` reference in `expire_all_resting` docstring

**File:** `itrader/order_handler/lifecycle/lifecycle_manager.py:226`
**Issue:** The `expire_all_resting` docstring still says the sweep "Visits active portfolios in
``get_active_portfolios()`` order" — but the WR-02 fix changed the implementation to call
`active_portfolio_ids()` (line 250). Behavior is unchanged (both iterate the same `is_active()`
filter in identical order), so this is not a correctness defect, but the docstring now names a
method the code no longer calls, contradicting the inline WR-02 comment a few lines below it. The
same stale phrasing also appears in `tests/unit/order/test_expire_all_resting.py:6,15,78` (test
prose, harmless — the test legitimately uses `get_active_portfolios()` to build the expected
order, which is provably equivalent).
**Fix:** Update the docstring at line 226 to reference `active_portfolio_ids()`:
```python
The run-end time-in-force sweep — the peer of ``cancel_order`` (the body
below mirrors it near-verbatim). Visits active portfolios in
``active_portfolio_ids()`` order and, within each, orders sorted by ...
```

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
