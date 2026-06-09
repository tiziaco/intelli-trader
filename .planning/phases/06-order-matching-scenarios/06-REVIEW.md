---
phase: 06-order-matching-scenarios
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 33
files_reviewed_list:
  - itrader/reporting/orders.py
  - itrader/trading_system/backtest_trading_system.py
  - tests/e2e/conftest.py
  - tests/e2e/scenario_spec.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/matching/entries/market_next_open/scenario.py
  - tests/e2e/matching/entries/market_next_open/test_scenario.py
  - tests/e2e/matching/entries/limit_touch/scenario.py
  - tests/e2e/matching/entries/limit_touch/test_scenario.py
  - tests/e2e/matching/entries/limit_gap_through/scenario.py
  - tests/e2e/matching/entries/limit_gap_through/test_scenario.py
  - tests/e2e/matching/entries/stop_gap_down/scenario.py
  - tests/e2e/matching/entries/stop_gap_down/test_scenario.py
  - tests/e2e/matching/entries/stop_gap_up/scenario.py
  - tests/e2e/matching/entries/stop_gap_up/test_scenario.py
  - tests/e2e/matching/brackets/oco_lifecycle/scenario.py
  - tests/e2e/matching/brackets/oco_lifecycle/test_scenario.py
  - tests/e2e/matching/brackets/stop_beats_limit/scenario.py
  - tests/e2e/matching/brackets/stop_beats_limit/test_scenario.py
  - tests/e2e/matching/gaps/clean_through_stop/scenario.py
  - tests/e2e/matching/gaps/clean_through_stop/test_scenario.py
  - tests/e2e/matching/gaps/clean_through_limit/scenario.py
  - tests/e2e/matching/gaps/clean_through_limit/test_scenario.py
  - tests/e2e/matching/gaps/gap_past_both_legs/scenario.py
  - tests/e2e/matching/gaps/gap_past_both_legs/test_scenario.py
  - tests/e2e/matching/operator/cancel/scenario.py
  - tests/e2e/matching/operator/cancel/test_scenario.py
  - tests/e2e/matching/operator/modify_reprice/scenario.py
  - tests/e2e/matching/operator/modify_reprice/test_scenario.py
  - tests/e2e/matching/operator/modify_resize/scenario.py
  - tests/e2e/matching/operator/modify_resize/test_scenario.py
  - tests/e2e/matching/never_fill/scenario.py
  - tests/e2e/matching/never_fill/test_scenario.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 33
**Status:** issues_found

## Summary

Reviewed the Phase 6 E2E order-matching scenario harness: two shared production
files (`reporting/orders.py` order-snapshot serializer, `backtest_trading_system.py`
`on_tick` hook), three shared test-infra modules (`conftest.py`, `scenario_spec.py`,
`scripted_emitter.py`), and 14 frozen scenario/test leaf pairs.

**The two production-code changes are correct and well-scoped.** The `on_tick` hook
is genuinely oracle-inert: it is additive-only, defaults to `None`, and
`scripts/run_backtest.py` calls `system.run()` without it (verified) — the BTCUSD
oracle path is byte-exact. The git diff confirms the existing run-loop body is
unchanged; the hook is appended after `process_events` + `record_metrics`, matching
the documented A2 ordering. `reporting/orders.py` is `mypy --strict` clean,
Decimal-internal with `float()` only at the serialization edge, and its duck-typed
`Order` assumptions (`parent_order_id`, `child_order_ids`, `filled_quantity`, `type`,
`status`) all match the real `Order` dataclass.

All 14 scenarios pass under the strict `filterwarnings=["error"]` suite (verified:
`14 passed in 0.30s`). I disproved an initial timezone-determinism hypothesis: the
golden `time` column renders at `+01:00` because `csv_store` does
`tz_convert("Europe/Paris")` against the **pinned config default**
(`Settings.timezone = "Europe/Paris"`), NOT the machine's local `TZ` — so the goldens
are reproducible across machines.

No blockers. The findings below are robustness/maintainability concerns concentrated
in the shared test infra (`conftest._make_on_tick`) plus a couple of latent-coupling
notes that future scenario phases (7-9) could trip over.

## Warnings

### WR-01: Operator hook silently no-ops when the predicate resolves nothing or the round-trip fails

**File:** `tests/e2e/conftest.py:178-190`
**Issue:** `_make_on_tick` resolves the target order, then on `if not resting:
continue` it silently skips the scheduled action, and it discards the boolean return
value of `cancel_order` / `modify_order`. Both `OrderHandler.cancel_order` (returns
`result.success`) and `modify_order` (returns `result.success`) can return `False`
(order not found, validation failure, bad transition) without raising. A scenario
author who mistypes `bar_date`, names the wrong `ticker`, or schedules an action
against an already-filled order gets a **green test** — the operator action never
ran, but the diff still compares against whatever golden was frozen (which, if
frozen under the same broken hook, also reflects "no operator action"). This defeats
the purpose of the operator leaves: a regression that breaks `modify_order`/
`cancel_order` would not necessarily fail these tests, because the harness treats a
silently-failed round-trip identically to a successfully-applied one.
**Fix:** Make the harness assert the operator round-trip actually fired and succeeded
(this is test infra, so a hard failure is correct):
```python
resting = [o for o in candidates if o.status == OrderStatus.PENDING]
assert resting, (
    f"operator action {action.kind} on {action.ticker} @ {key}: "
    f"no PENDING order to target (check bar_date/ticker)")
order = resting[0]
if action.kind == "cancel":
    ok = system.order_handler.cancel_order(order.id, portfolio_id)
elif action.kind == "modify":
    ok = system.order_handler.modify_order(
        order.id, new_price=action.new_price,
        new_quantity=action.new_quantity, portfolio_id=portfolio_id)
else:
    raise ValueError(f"unknown action.kind: {action.kind!r}")
assert ok, f"operator {action.kind} round-trip failed for {order.id}"
```

### WR-02: "sole resting order" predicate silently picks the first of many

**File:** `tests/e2e/conftest.py:178-181`
**Issue:** The docstring and `scenario_spec.Action` both promise the target is "the
SOLE resting/PENDING order" (D-07), but the code does `resting[0]` with no check that
`len(resting) == 1`. If a future scenario (or a regression that fails to fill/cancel
a prior order) leaves more than one PENDING order on the ticker, the harness operates
on an arbitrary one — `InMemoryOrderStorage` insertion order is the only tiebreaker —
and the contract is silently violated. The current 14 leaves happen to schedule their
single action while exactly one order rests, so this is latent, not active; but the
shared infra is reused verbatim by Phases 7-9, where multi-order books are likely.
**Fix:** Enforce the documented predicate:
```python
if len(resting) != 1:
    pytest.fail(
        f"operator predicate expected exactly ONE PENDING {action.ticker} "
        f"order @ {key}, found {len(resting)} — the 'sole resting order' "
        f"contract (D-07) is violated")
order = resting[0]
```

### WR-03: Date-key matching couples the operator/emitter to the Europe/Paris config default

**File:** `tests/e2e/conftest.py:174` and `tests/e2e/strategies/scripted_emitter.py:104`
**Issue:** Both the operator hook (`time_event.time.strftime("%Y-%m-%d")`) and the
ScriptedEmitter (`bars.index[-1].strftime("%Y-%m-%d")`) key off the **localized**
timestamp date. `csv_store` converts the UTC bar index to `TIMEZONE` (currently
`"Europe/Paris"`, a pinned default), so a UTC bar at `2020-01-03 00:00:00+00:00` is
localized to `2020-01-03 01:00:00+01:00` and strftimes to `"2020-01-03"`. This holds
for the frozen daily-midnight-UTC fixtures, and both producers derive the date from
the *same* localized index so they agree internally. BUT the `Action.bar_date` strings
in each `scenario.py` are hand-written UTC-looking dates that only coincidentally
match the Paris-localized strftime. If `Settings.timezone` were ever changed, or a
future scenario uses bars near a day boundary (e.g. `23:00:00+00:00`), the
Paris-localized date would roll to the next day and the action would fire on the wrong
bar (or not at all — see WR-01, which would then mask it). This is a fragile,
undocumented coupling in shared infra.
**Fix:** Either (a) document explicitly in `_make_on_tick`/`ScriptedEmitter` that
`bar_date` is matched against the `TIMEZONE`-localized date and must be authored in
that frame, or (b) make the comparison timezone-explicit, e.g. compare against
`time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")` consistently in both the
emitter and the hook so the action dates are anchored to a fixed frame independent of
the `Settings.timezone` default.

## Info

### IN-01: `_order_role` defaults any non-STOP child to "TP"

**File:** `itrader/reporting/orders.py:54-56`
**Issue:** `_order_role` returns `"SL" if order.type is OrderType.STOP else "TP"` for
any child (parented) order. This is correct for the canonical SL=STOP / TP=LIMIT
bracket shape the assembler produces, but it silently mislabels any child whose type
is neither (e.g. a MARKET child, or a future trailing-stop variant) as `"TP"` rather
than failing or labelling it explicitly. Low risk given the current assembler, but
the role is a load-bearing identity column in the orders golden.
**Fix:** Consider being explicit about the LIMIT case and surfacing the unexpected:
`return "SL" if order.type is OrderType.STOP else "TP" if order.type is OrderType.LIMIT else "CHILD"` — or assert the child type is STOP/LIMIT.

### IN-02: `time` is a golden identity column but excluded from the orders identity/sort keys

**File:** `itrader/reporting/orders.py:43` and `tests/e2e/conftest.py:92,96`
**Issue:** The orders snapshot emits a `time` column (business decision time), and the
goldens freeze it (e.g. `2020-01-02 01:00:00+01:00`). But `_ORDERS_IDENTITY_COLUMNS`
and `_ORDERS_SORT_KEYS` omit `time`, so it falls into the "numeric remainder" bucket
and is diffed as an opaque string by `assert_frame_equal`. That works for the current
single-decision-bar fixtures, but if two orders on the same ticker share
role/order_type/action/price and differ only by `time`, the sort is non-deterministic
on that tiebreak and the row-aligned diff could spuriously fail. Not triggered by any
current leaf.
**Fix:** Add `time` as a trailing sort key in `_ORDERS_SORT_KEYS` so row alignment is
fully determined even when role/type/action/price collide.

### IN-03: Docstring/comment drift — "short entry" / stale gate line numbers

**File:** `tests/e2e/matching/entries/stop_gap_down/test_scenario.py:1` and
`tests/e2e/matching/entries/stop_gap_down/scenario.py:13,117`
**Issue:** The `stop_gap_down` test_scenario docstring says "SELL STOP pessimistic
gap-down **short entry**", but the scenario (correctly, per the LONG_ONLY v1.1 guard)
implements the SELL STOP as the stop-loss EXIT leg of a long, not a short entry — the
test docstring contradicts the scenario module's own (accurate) explanation. Several
scenarios also cite hard-coded source line numbers (`strategies_handler.py:225`,
`order_manager.py:641`, `simulated.py:539`) that will silently rot as those files
change.
**Fix:** Correct the `stop_gap_down` test docstring to "stop-loss exit leg of a long"
to match its scenario; treat the pinned line numbers as decision-tag references only
(the `D-`/`MATCH-` tags are the durable anchors, per CLAUDE.md).

---

_Reviewed: 2026-06-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
