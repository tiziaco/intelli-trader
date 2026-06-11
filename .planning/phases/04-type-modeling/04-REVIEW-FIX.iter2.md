---
phase: 04-type-modeling
fixed_at: 2026-06-11T00:00:00Z
review_path: .planning/phases/04-type-modeling/04-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-06-11
**Source review:** .planning/phases/04-type-modeling/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (1 Critical + 5 Warning; Info findings IN-01..IN-04 out of scope under `critical_warning`)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: MatchingEngine swallows `decimal.InvalidOperation` as a "malformed order"

**Files modified:** `itrader/execution_handler/matching_engine.py`
**Commit:** 38f96b7
**Applied fix:** Added `InvalidOperation` to the `from decimal import Decimal` import and extended BOTH resting-order matching filters (pass-1 at the parents/standalone loop and pass-2 at the bracket-children loop) from `except (TypeError, ValueError, KeyError)` to `except (TypeError, ValueError, KeyError, InvalidOperation)`. `decimal.InvalidOperation` is an `ArithmeticError`, not a `ValueError`, so a NaN/sNaN Decimal trigger previously either aborted the whole bar via the fail-fast seam or was silently misread as "no trigger" (dropped fill). Now a single malformed resting order is skipped as documented without dropping the bar. Verified: 133 execution unit tests pass; mypy clean.

### WR-01: `OrderEvent.new_order_event` reconstructs `Side` from a raw `str` with no error context

**Files modified:** `itrader/events_handler/events/order.py`
**Commit:** ebec4d6
**Applied fix:** Note — `Side` ALREADY carries a case-insensitive `_missing_` parser (the primary remedy the review suggested was implemented since the review snapshot), so casing drift in the hand-built bracket literals already resolves rather than crashing. The deeper structural remedy (retype `Order.action` to `Side` at construction) is an explicit M4 cutover and out of scope here. The remaining gap — a bare `ValueError` with no order context — is closed by wrapping `Side(order.action)` in a `try/except ValueError` that re-raises with `ticker`, `order_id`, and the offending `action` value, chained via `from exc`. Verified: 43 order unit tests pass; mypy clean.

### WR-02: `validate_order` short-circuits, hiding a price problem behind a quantity problem

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`
**Commit:** eec746f
**Applied fix:** Replaced the `failed_checks[0]`-driven (first-wins) `error_code` derivation with a priority-ordered scan of the FULL `failed_checks` list. A local `_classify` helper maps each failed check to its `ExecutionErrorCode`; a fixed priority list (symbol > price > quantity-too-small > quantity-too-large > connection > generic) then selects the single `error_code` deterministically regardless of append order. `error_message` still joins every failed check. Tab indentation preserved (handler module). Verified: 133 execution unit tests pass; mypy clean.

### WR-03: `release()` in the `finally` block masks a real reservation-release failure

**Files modified:** `itrader/order_handler/order_manager.py`
**Commit:** bb10bd6
**Applied fix:** Added a `body_raised` flag set to `True` in the `except Exception` clause before its `raise`. In the `finally`, when the `release()` call itself fails: the failure is logged as before, but is now ALSO re-raised when `not body_raised` — so a silently-unreleased reservation (buying-power corruption) reaches the fail-fast seam instead of being downgraded to a log line. If the body already raised, the original exception is left to propagate (the release failure is only logged, never masking the original). Tab indentation preserved. Verified: 145 order unit tests pass; mypy clean.

> NOTE — requires human verification: this is an error-handling control-flow change. Syntax/type checks and the existing tests pass, but no existing test exercises the "body succeeded, release raised" path. A reviewer should confirm the re-raise semantics match the intended fail-fast contract before the phase proceeds to verification.

### WR-04: `validate_sufficient_funds` casts `Decimal` money to `float` to build the exception

**Files modified:** `itrader/core/exceptions/portfolio.py`, `itrader/portfolio_handler/validators.py`
**Commit:** 9149e65
**Applied fix:** Retyped `InsufficientFundsError.required_cash`/`available_cash` to store `Decimal`. The constructor accepts `Decimal | float | int` (backward-compatible with the existing float callers in `cash_manager.py` and a test stub) and normalizes any non-Decimal input via `Decimal(str(x))` (never `Decimal(float)`, per money policy). `float()` formatting now happens ONLY inside the message f-string (a serialization/logging edge). Updated the `validators.py` call site to pass the Decimal money straight through, removing the `float()` round-trip that introduced a binary-float repr artifact. The existing `test_cash_manager.py` assertions (`required_cash == 150000.0`) still pass because `Decimal == float` compares equal. Verified: 36 cash-manager + 171 portfolio unit tests pass; mypy clean on the exception module. (The unrelated `test_position_manager.py` collection error — a missing `PositionEvent` import — is pre-existing on the committed source and not introduced by this fix.)

### WR-05: live-path timestamps use naive wall-clock `datetime.now()`

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 15d4e7a
**Applied fix:** Imported `UTC` and replaced every `datetime.now()` in the module with `datetime.now(UTC)` (the `ErrorEvent.time` fallback, status/stats timestamps, idle-tracking `last_event_time`/`current_time`, and the `get_status` uptime subtraction). This eliminates the naive-vs-aware subtraction hazard (`uptime_start` is stored tz-aware, so the comparand at uptime computation must match) and aligns the live path with the `datetime.now(UTC)` convention used by the portfolio handler. The `ErrorEvent.time` fallback continues to prefer the event's own business `time`. This module is mypy-deferred via override; verified by clean module import and `python ast.parse`.

## Skipped Issues

None — all 6 in-scope findings were fixed.

---

_Fixed: 2026-06-11_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
