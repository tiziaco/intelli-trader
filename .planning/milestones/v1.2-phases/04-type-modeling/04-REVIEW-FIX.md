---
phase: 04-type-modeling
fixed_at: 2026-06-11T00:00:00Z
review_path: .planning/phases/04-type-modeling/04-REVIEW.md
iteration: 2
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-06-11
**Source review:** .planning/phases/04-type-modeling/04-REVIEW.md
**Iteration:** 2

**Summary (iteration 2):**
- Findings in scope: 1 (WR-06 — Warning)
- Fixed: 1
- Skipped: 0
- Out of scope (not touched): IN-05, IN-06 (Info severity)

## Fixed Issues (iteration 2)

### WR-06: `_classify` maps a non-positive quantity ("must be positive") to `ORDER_SIZE_TOO_LARGE`

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`, `tests/unit/execution/exchanges/test_simulated_exchange.py`
**Commit:** 1ed6cb1
**Applied fix:** Added an explicit branch in the `_classify` closure in
`validate_order` so a `"Order quantity must be positive"` check (emitted for
`quantity <= 0`) returns `ExecutionErrorCode.INVALID_ORDER` instead of falling
through to `ORDER_SIZE_TOO_LARGE`. `INVALID_ORDER` is already present in the
`_priority` list, so no priority-order change was needed. Also hardened the
`"below minimum"` sub-check to compare against the already-lowercased `lowered`
string (was comparing the raw `check`) for consistency. Added a dedicated
regression test `test_non_positive_quantity_classified_invalid_order` (covers
both zero and negative quantities) and a `result.error_code ==
ExecutionErrorCode.INVALID_ORDER` assertion to the existing
`test_invalid_quantity_validation`.

**Verification:** Python `ast.parse` OK on both files; 53/53 tests pass in
`test_simulated_exchange.py`; `mypy --strict` clean on `simulated.py`. Kept tab
indentation (handler-module convention). No money/Decimal surface touched.

## Fixed Issues (iteration 1 — prior, for completeness)

Iteration 1 addressed 6 findings (CR-01 + WR-01..WR-05) across commits
`38f96b7..15d4e7a`. The iteration-2 re-review (04-REVIEW.md) verified each is
genuinely resolved. Summary preserved here so this report is complete:

### CR-01: Matching engine `decimal.InvalidOperation` could propagate / be misread

**File:** `itrader/execution_handler/matching_engine.py` (resting-order passes ~:219, :249)
**Applied fix:** Added `InvalidOperation` to the `except` tuple on both
resting-order passes and imported it (`from decimal import Decimal,
InvalidOperation`). A NaN/sNaN Decimal trigger now falls into the
"skip malformed order" branch instead of propagating or being silently misread.
Programming-error contract preserved (`AttributeError` etc. still propagate).

### WR-01: `Side`-from-`str` boundary lacked order context

**File:** `itrader/events_handler/events/order.py` (~:91-105, `new_order_event`)
**Applied fix:** Wrapped `Side(order.action)` in `try/except ValueError`,
re-raising with `ticker`/`order_id`/`action` context, chained via `from exc`.

### WR-02: `error_code` first-wins lossiness in `validate_order`

**File:** `itrader/execution_handler/exchanges/simulated.py` (~:412-447)
**Applied fix:** Replaced `failed_checks[0]` derivation with a priority-ordered
scan (symbol > price > size-small > size-large > network > generic) over the
full `failed_checks` list via a `_classify` closure and `_priority` list.
(WR-06 above is a residual classification quirk this fix surfaced.)

### WR-03: Release-failure masking in `finally`

**File:** `itrader/order_handler/order_manager.py` (~:260, :274-286)
**Applied fix:** Added a `body_raised` flag set in the `except` block before the
body re-raise; the `finally` release handler re-raises a release failure ONLY
when `not body_raised`, so a release failure after a successful body still
reaches the fail-fast seam, while a release failure during body-failure is
logged without masking the original cause.

### WR-04: Non-Decimal money in `InsufficientFundsError`

**File:** `itrader/core/exceptions/portfolio.py` (~:21-49); `itrader/portfolio_handler/validators.py` (~:94-101)
**Applied fix:** Store `required_cash`/`available_cash` as `Decimal` (entered via
`Decimal(str(x))`, never `Decimal(float)`); `float()` only at the message
(logging) edge. Constructor accepts `Decimal | float | int`; all callers and
tests still pass.

### WR-05: Naive `datetime.now()` on live path

**File:** `itrader/trading_system/live_trading_system.py` (7 call sites, uptime subtraction ~:434)
**Applied fix:** Converted all 7 `datetime.now()` calls to `datetime.now(UTC)`
and added the `UTC` import, making the `get_status` uptime subtraction tz-aware
on both operands.

---

_Fixed: 2026-06-11_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
