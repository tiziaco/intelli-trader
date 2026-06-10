---
phase: 06-order-matching-scenarios
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/06-order-matching-scenarios/06-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 6: Code Review Fix Report

**Fixed at:** 2026-06-10T00:00:00Z
**Source review:** .planning/phases/06-order-matching-scenarios/06-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (3 Warning + 3 Info; fix_scope=all)
- Fixed: 6
- Skipped: 0

All fixes verified by re-read, `ast.parse` syntax check, `mypy` (for the
in-scope `itrader/` module), and the full E2E suite (`15 passed`). The E2E
goldens are unchanged — every scenario still diffs clean under the strict
`filterwarnings=["error"]` suite, confirming the robustness fixes did not alter
any frozen behavior.

## Fixed Issues

### WR-03: Date-key matching couples the operator/emitter to the Europe/Paris config default

**Files modified:** `tests/e2e/conftest.py`, `tests/e2e/strategies/scripted_emitter.py`
**Commit:** 1200cc0
**Applied fix:** Anchored both date-key derivations to a fixed UTC frame
(`tz_convert("UTC").strftime("%Y-%m-%d")`) in `_make_on_tick` (the operator hook)
and `ScriptedEmitter.generate_signal`, independent of the `Settings.timezone`
default. Chose option (b) from the review (timezone-explicit comparison) over
mere documentation. For the current daily-midnight-UTC fixtures the localized
Paris date and the UTC date strftime identically, so all goldens still pass
(15 passed); the change removes the latent day-boundary coupling for future
scenarios.

### WR-01 / WR-02: Operator hook silently no-ops on miss/round-trip-failure; "sole resting order" picks first of many

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 43e7f47
**Applied fix:** In `_make_on_tick`'s `on_tick`, replaced the silent
`if not resting: continue` + discarded boolean return with hard test-infra
assertions: (WR-02) `pytest.fail` unless exactly ONE PENDING order matches the
predicate (D-07), and (WR-01) `assert resting` plus `assert ok` on the captured
`cancel_order`/`modify_order` return value, with an explicit `raise ValueError`
on an unknown `action.kind`. A broken or non-firing operator round-trip now fails
the test instead of passing green. Verified the operator leaves still pass
(cancel/modify_reprice/modify_resize all green), proving the round-trips actually
fire and succeed.

### IN-01: `_order_role` defaults any non-STOP child to "TP"

**Files modified:** `itrader/reporting/orders.py`
**Commit:** f9d574f
**Applied fix:** Replaced the `"SL" if STOP else "TP"` fallthrough with explicit
STOP→SL / LIMIT→TP mapping and a `raise ValueError` (carrying the order id) on any
other child type. Added an `OrderRole = Literal["ENTRY","STANDALONE","SL","TP"]`
return annotation so mypy verifies every branch yields a valid label without
inventing a domain enum. `mypy itrader/reporting/orders.py` is clean
(`Success: no issues found`). The `raise` is unreachable today (children are only
STOP/LIMIT) and only fires when a new bracket leg type is added — surfacing a
located failure instead of freezing a mislabeled golden row.

### IN-02: `time` is a golden identity column but excluded from the orders sort keys

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 96ff91b
**Applied fix:** Appended `"time"` as a trailing key to `_ORDERS_SORT_KEYS`, so
row alignment in `_diff_frame` is fully determined even when
role/order_type/action/price collide on the same ticker. `time` is present in
both the round-tripped fresh frame and the frozen golden (it is in
`ORDER_SNAPSHOT_COLUMNS`), so the diff stays apples-to-apples; all orders goldens
still pass.

### IN-03: Docstring/comment drift — "short entry" / stale gate line numbers

**Files modified:** `tests/e2e/matching/entries/stop_gap_down/test_scenario.py`
**Commit:** 443c3b7
**Applied fix:** Corrected the `stop_gap_down` test docstring from "SELL STOP
pessimistic gap-down short entry" to "stop-loss exit leg of a long", matching the
scenario module's own accurate explanation under the LONG_ONLY v1.1 guard. The
pinned source line-number citations (`strategies_handler.py:225`,
`order_manager.py:641`, `simulated.py:539`) were left in place per the review's
guidance to treat them as decision-tag references only — the durable `D-`/`MATCH-`
anchors they accompany are already present, and mechanically rewriting every
citation across the scenario corpus is an authoring convention rather than a
defect. The narrow, actionable docstring contradiction is resolved.

---

_Fixed: 2026-06-10T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
