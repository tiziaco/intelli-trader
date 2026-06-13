---
phase: 06-order-lifecycle-time-in-force
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - itrader/core/enums/execution.py
  - itrader/core/enums/order.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/lifecycle/lifecycle_manager.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - itrader/trading_system/backtest_runner.py
  - tests/e2e/matching/never_fill/scenario.py
  - tests/integration/test_expire_non_cascade.py
  - tests/unit/core/test_enums_expire.py
  - tests/unit/execution/test_simulated_expire.py
  - tests/unit/order/test_expire_all_resting.py
  - tests/unit/order/test_order_command_enum.py
  - tests/unit/order/test_reconcile_expired.py
findings:
  critical: 0
  blocker: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 6 adds an `OrderCommand.EXPIRE` verb + `FillStatus.EXPIRED` status and wires a
run-end time-in-force sweep through five layers: the enums (`core/enums`), the
exchange EXPIRE arm (`simulated.py`), the `LifecycleManager.expire_all_resting`
sweep, the `ReconcileManager` EXPIRED arm, and the `BacktestRunner` run-end bookend.
It also removes the dead, unvalidated `create_orders_from_signal` second
signal→order path.

I traced the full EXPIRE lifecycle end-to-end. The core mechanism is sound and
internally consistent:

- The EXPIRE arm in `SimulatedExchange.on_order` is a faithful parallel peer of the
  CANCEL arm (`matching_engine.cancel` bool guard → `FillEvent(EXPIRED)`), and
  `matching_engine.cancel` is a pure `pop` that does NOT fire OCO, so expiring an SL
  does not spuriously CANCEL its TP sibling — both get their own EXPIRE event
  (matches the re-frozen `from_fill_held` / `from_decision_held` golden orders.csv).
- The idempotency contract (`VALID_ORDER_TRANSITIONS[EXPIRED] == []` making a second
  EXPIRED→EXPIRED transition a return-False no-op) is genuinely exploited — the
  reconcile `_apply_expired` arm needs no guard, as documented in the D-09 landmine.
- `PortfolioHandler.on_fill` no-ops on any non-EXECUTED status (line 298), so
  `FillEvent(EXPIRED)` correctly never touches cash/positions — no phantom trades.
- The reservation release path is idempotent on both the local-sweep release and the
  reconcile-finally release; double-release pops nothing.
- The removed `create_orders_from_signal` path has no remaining callers; the
  `CREATE_ORDERS_FROM_SIGNAL` enum member and `PositionView`/`OrderOperationType`
  imports are still live elsewhere, so the deletion left no dead imports.
- I checked the suspected iteration-during-mutation hazard in `expire_all_resting`
  (the loop transitions each order to EXPIRED, which removes it from
  `is_active`): `sorted(get_active_orders(...))` fully materializes a list before
  the loop runs, and `get_active_orders` is itself a list comprehension, so there is
  NO mutation of the iterated collection. Not a bug.

No BLOCKER-class defects (no incorrect behavior, security gap, or data-loss path)
were proven. The findings below are robustness / consistency / clarity concerns.

## Warnings

### WR-01: EXPIRED fill event is stamped with the original decision time, not run-end time

**File:** `itrader/execution_handler/exchanges/simulated.py:295-297`
**Issue:** The EXPIRE arm calls `FillEvent.new_fill('EXPIRED', event, ...)` without
passing `time=`. Per `FillEvent.new_fill` (fill.py:131), an omitted `time` defaults
to `order.time` — the order's *original decision* time (e.g. 2018-01-02 for an order
that rests for years). For the `on_bar` EXECUTED/OCO-CANCELLED paths the code is
careful to stamp the *matching bar's* time (`bar.time`, simulated.py:249-257) per the
D-01/D-13 fill-time contract ("fill truth is stamped at the bar that produced it").
A run-end expiry is logically an event that happens at run end, not at the original
decision tick. Stamping it with a years-stale decision time can produce a
`FillEvent(EXPIRED)` whose `time` is *earlier than the last processed bar*, which is
surprising for any time-ordered audit/event consumer and inconsistent with the
fill-time discipline applied elsewhere.

This is classified WARNING (not BLOCKER) because EXPIRED fills never reach the
portfolio (no cash/position effect) and the order-mirror reconcile keys off
`order_id`, not `fill.time`, so backtest *numbers* are unaffected. But the
audit-trail timestamp is misleading and the inconsistency with the CANCEL/OCO
time-stamping is a latent trap.

**Fix:** Decide and document the intended expiry timestamp. If run-end time is
intended, thread the final bar time (or `clock.now()`) from the sweep through to the
fill. If the decision-time default is intentional (matching the CANCEL *command*
acknowledgement convention, fill.py:96-98), add an explicit one-line comment in the
EXPIRE arm stating that the EXPIRED fill deliberately inherits the decision time like
the CANCEL command arm — the current code reads as an oversight against the bar-time
rule it sits next to.

### WR-02: `expire_all_resting` depends on a method (`get_active_portfolios`) outside the injected read-model Protocol

**File:** `itrader/order_handler/lifecycle/lifecycle_manager.py:249`
**Issue:** The sweep calls `self.portfolio_handler.get_active_portfolios()` with a
`# type: ignore[attr-defined]` because that method is NOT part of the
`PortfolioReadModel` Protocol — it only exists on the concrete `PortfolioHandler`.
The docstring acknowledges this ("the run-end portfolio enumeration is wider"), but
the constructor still types `portfolio_handler: Optional[PortfolioReadModel]`
(lifecycle_manager.py:53). This silently couples the lifecycle manager to the
concrete handler through a `type: ignore`, defeating the narrow read-boundary
abstraction. Any `PortfolioReadModel` implementation that is NOT the concrete
`PortfolioHandler` (e.g. a test double satisfying the Protocol, or a future live
read-model) will `AttributeError` at run-end sweep time — a latent crash hidden
behind the suppressed type error. The existing tests pass only because they inject
the real `PortfolioHandler`.

**Fix:** Either (a) add `get_active_portfolios` (or a narrower
`active_portfolio_ids()`) to the `PortfolioReadModel` Protocol so the dependency is
type-checked and contract-guaranteed, or (b) drive the sweep off the order storage
alone — iterate active orders across all portfolios without enumerating portfolios at
all (the orders already carry `portfolio_id`). Option (b) removes the cross-domain
coupling entirely and is the cleaner fit for the order-domain read boundary.

### WR-03: Run-end sweep silently swallows broad `Exception` and continues to the next order

**File:** `itrader/order_handler/lifecycle/lifecycle_manager.py:278-283`
**Issue:** Inside the per-order sweep loop, any exception is caught, logged, appended
as a `failure_result`, and the loop *continues* to the next order. This is
publish-and-continue behavior on the *backtest* path, which is explicitly fail-fast
(CLAUDE.md: "Backtest error policy is fail-fast"). If one order's `expire_order` /
`release` / `update_order` raises mid-sweep, the run completes "successfully" with a
partially-swept book — some orders EXPIRED with released reservations, others left
PENDING with stuck reservations — and the failure is only visible in a logged
`failure_result` that `OrderHandler.expire_all_resting` (order_handler.py:224-228)
does NOT inspect (it only enqueues events from `result.success` results; failures are
dropped on the floor). The reconcile path, by contrast, was deliberately made
fail-fast (`reconcile_manager.py:291-302` re-raises) for exactly this
"partial state corrupts the run" reason. The sweep's broad-except-and-continue is
the opposite policy at a structurally similar correctness-critical site.

Classified WARNING because the golden run never triggers a sweep exception (the
happy path is well-tested), so it is not a proven live defect — but the divergence
from the documented backtest fail-fast contract is a real robustness gap that would
mask a corrupted run-end state.

**Fix:** Align with the backtest fail-fast policy: let the per-order exception
propagate (or re-raise after logging) so a sweep failure aborts the run rather than
producing a half-swept book. If continue-on-error is genuinely desired here, document
*why* the sweep deviates from fail-fast and ensure `OrderHandler.expire_all_resting`
surfaces the dropped failure results instead of silently discarding them.

## Info

### IN-01: `Decimal` price compared against bare int literal in `validate_order`

**File:** `itrader/execution_handler/exchanges/simulated.py:418`
**Issue:** `elif event.price > 1000000:` compares a `Decimal` price against an `int`
literal. This works (Decimal supports mixed comparison with int) and is only a
"seems unusually high" warning, so behavior is correct. But the bare magic number
`1000000` and the int-vs-Decimal mix is inconsistent with the file's otherwise strict
Decimal-end-to-end discipline and uses an undocumented sanity threshold.

**Fix:** Promote `1000000` to a named module constant (e.g.
`_UNREALISTIC_PRICE_THRESHOLD = Decimal("1000000")`) and compare Decimal-to-Decimal,
matching the surrounding money-policy convention. (Pre-existing; surfaced because the
EXPIRE work sits in this file.)

### IN-02: `validate_order` quantity-vs-size uses `elif` chain that masks the "below minimum AND above maximum" impossibility but also hides an ordering assumption

**File:** `itrader/execution_handler/exchanges/simulated.py:408-413`
**Issue:** The quantity block is an `if/elif/elif` chain (`<= 0` → `< min` → `> max`).
The WR-02/WR-06 priority-scan logic added below (lines 442-475) was specifically
introduced to handle *independent* failures across the quantity and price blocks, but
within the quantity block itself the `elif` chain still emits at most one
quantity-related `failed_check`. This is fine functionally (min < max so the
sub-conditions are mutually exclusive), but the comment at line 437-441 claims "the
quantity and price blocks above are independent `if`s" — the quantity sub-checks are
NOT independent `if`s, they are `elif`. The comment slightly overstates the
independence and could mislead a future maintainer into thinking a single order can
emit both "below minimum" and "exceeds maximum".

**Fix:** Tighten the comment to scope the independence claim to the *block* level
(quantity-block vs price-block vs connection-block), not the sub-checks. No code
change required.

### IN-03: `_classify` and the per-status dispatch in `on_fill` duplicate the status→terminal-ness knowledge

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:87-115, 232-246`
**Issue:** `_classify` maps each `FillStatus` to `(terminal, transition)` but the
docstring explicitly says it does NOT drive the transition — the `on_fill` body
re-dispatches the same four statuses through a separate `if/elif` chain (lines
232-239) plus a defensive `else: raise NotImplementedError`. The status set is thus
encoded twice: once in `_classify`, once in the dispatch chain. Adding a new terminal
`FillStatus` (as this phase did with EXPIRED) requires editing both places, and the
only thing protecting against a missed edit is the runtime `NotImplementedError`
fallthrough — which is good defense, but the duplication is a maintenance smell. The
phase correctly updated both sites for EXPIRED, so this is not a defect today.

**Fix:** Consider driving the per-status mirror transition from a single mapping
(e.g. `_classify` returns the bound apply-helper, or a dict from status →
apply-callable), so the status vocabulary lives in exactly one place. Low priority —
the current `NotImplementedError` guard already fails loud on a missed arm. Documented
only so the next status addition does not have to re-discover the dual-edit
requirement.

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
