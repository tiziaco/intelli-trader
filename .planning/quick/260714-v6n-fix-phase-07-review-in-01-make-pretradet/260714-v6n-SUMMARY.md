---
phase: quick-260714-v6n
plan: 01
subsystem: trading_system/safety
tags: [safety, live-only, code-review-fix, IN-01]
status: complete
requires: []
provides:
  - "PreTradeThrottle.allow() self-guards: meters ORDER events only"
affects:
  - itrader/trading_system/safety/pre_trade_throttle.py
tech-stack:
  added: []
  patterns:
    - "getattr(event, 'type', None) is not EventType.ORDER top-gate (mirrors classify())"
key-files:
  created: []
  modified:
    - itrader/trading_system/safety/pre_trade_throttle.py
decisions:
  - "Dropped the 3-arg getattr None-defaults to 2-arg getattr so mypy --strict stays clean (Rule 3 blocking fix — the plan's stated premise that getattr(x,'price',None) types as Any was wrong; the 3-arg-with-None form types Any | None)"
metrics:
  duration: 6min
  completed: 2026-07-14
  tasks: 1
  files: 1
---

# Phase quick-260714-v6n Plan 01: Self-guard PreTradeThrottle (IN-01) Summary

Made `PreTradeThrottle.allow()` self-guarding by adding an ORDER-only top-gate above the `classify(event)` call, so the throttle meters ORDER events only and no longer depends on `live_runner`'s call-site type gate for safety; removed the now-provably-dead `None`-guard in `_exceeds_notional`.

## What Was Built

Four scoped edits to `itrader/trading_system/safety/pre_trade_throttle.py` (4-space module, no tabs introduced):

1. **Import** — added `EventType` to the existing `from itrader.core.enums import ErrorSeverity, OrderRiskRole` line (alphabetical: `ErrorSeverity, EventType, OrderRiskRole`). No new import line.
2. **Option B — self-guard `allow()`** — added an ORDER-only top-gate as the first statement of the body, before the classify-based CANCEL/PROTECTIVE bypass: `if getattr(event, 'type', None) is not EventType.ORDER: return True`. Any non-ORDER event bypasses cleanly (allows submission, meters nothing). Past this gate the ENTRY branch provably implies an OrderEvent. The existing classify bypass block stays exactly as-is directly below.
3. **Option A — drop the dead None-guard** in `_exceeds_notional`. The `if price is None or quantity is None: return False` guard was removed; the method now flows straight from the attribute reads into `notional = abs(price * quantity)`.
4. **Docstrings** — `allow()` documents the new step-0 ORDER-only top-gate as the load-bearing first step; `_exceeds_notional` drops the obsolete "if either field is absent the check is skipped" sentence and states that any event reaching it is a guaranteed OrderEvent with non-optional Decimal price/quantity.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `_exceeds_notional` attribute reads changed from 3-arg to 2-arg getattr**
- **Found during:** Task 1, mypy verification gate.
- **Issue:** The plan (truth item + action step 3) instructed keeping the reads as `price = getattr(event, "price", None)` / `quantity = getattr(event, "quantity", None)` unchanged, on the stated premise that "getattr returns Any so mypy --strict stays clean". That premise is factually wrong: the 3-argument `getattr(obj, name, None)` overload types as `Any | None`, not `Any`. With the `None`-guard removed (Option A), mypy `--strict` then failed on line 204: `error: Unsupported left operand type for * ("None")` — it could no longer prove `None * ...` was unreachable.
- **Fix:** Dropped the `, None` defaults, using the 2-arg `getattr(event, "price")` / `getattr(event, "quantity")` form, which the stubs type as `Any`. `abs(Any * Any)` is mypy-clean. This is faithful to the plan's INTENT ("getattr returning Any") and to the new contract — the 2-arg form raising `AttributeError` on an absent attr is unreachable because the top-gate guarantees an OrderEvent (price/quantity always present, `events/order.py:53-54`).
- **Files modified:** itrader/trading_system/safety/pre_trade_throttle.py
- **Commit:** baa125f8

No other deviations — the LOCKED scope (no new event types, no route changes, no cross-domain calls, `live_runner.py` untouched, no new tests) was held.

## Verification Gates (actual output)

**1. `poetry run mypy itrader/trading_system/safety/pre_trade_throttle.py`**
```
Success: no issues found in 1 source file
```

**2. `poetry run pytest tests/unit/trading_system/test_pre_trade_throttle.py -v`**
```
test_eleventh_entry_in_window_is_refused PASSED                     [ 20%]
test_window_prunes_left_off_injected_clock PASSED                   [ 40%]
test_entry_over_max_notional_is_refused PASSED                      [ 60%]
test_cancel_and_protective_bypass_uncounted_even_over_cap PASSED    [ 80%]
test_breach_warning_is_deduped_off_injected_clock PASSED            [100%]
============================== 5 passed in 0.60s ===============================
```

**3. `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py`**
```
test_oracle_behavioral_identity PASSED                                    [ 14%]
test_oracle_numeric_values PASSED                                         [ 28%]
test_golden_run_signal_store_is_non_empty_and_queryable PASSED            [ 42%]
test_backtest_path_imports_no_okx_stack PASSED                            [ 57%]
test_backtest_event_handler_phase7_routes_are_inert_empty PASSED          [ 71%]
test_new_store_registrars_are_register_vs_build PASSED                    [ 85%]
test_production_build_live_system_registers_no_replay_data_provider PASSED [100%]
============================== 7 passed in 1.76s ===============================
```

Oracle byte-exact (`test_oracle_numeric_values` green → 134 / 46189.87730727451 unchanged) and OKX import-inertness green — confirmed the change is live-path-only / oracle-dark.

## Behavior Invariant

ZERO behavior change on all reachable paths: every existing throttle test feeds a real `OrderEvent` (type==ORDER), so each passes the new top-gate to `classify()` and behaves identically (CANCEL bypass, PROTECTIVE bypass, ENTRY rate-cap, notional-cap, WARNING-dedup all green). The only changed behavior is a hypothetical non-ORDER event reaching `allow()` — it now bypasses cleanly instead of risking AttributeError; none reach it today (live_runner gates the call at :161-163).

## Self-Check: PASSED

- FOUND: itrader/trading_system/safety/pre_trade_throttle.py (modified)
- FOUND: commit baa125f8 in git log
