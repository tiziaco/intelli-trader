# Phase 6: Order Lifecycle & Time-in-Force - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 9 (5 modified-add, 2 modified-remove, 1 doc, 1 new-test/leaf)
**Analogs found:** 9 / 9 (every new EXPIRED surface has a proven CANCELLED-path template)

## Orienting Principle

This phase is **wiring an existing-but-unwired EXPIRED lifecycle by adding a parallel arm at each
of four seams**, plus removing a dead second path. The CANCELLED lifecycle is the proven template
for **every** new surface — there is one retire-a-resting-order pattern (local transition +
idempotent release + emit `OrderEvent` → exchange clears book → reconcile idempotently). Do NOT
invent machinery. Each new EXPIRED arm is a near-verbatim copy of the CANCELLED arm sitting beside
it, swapping `cancel`→`expire` / `CANCEL`→`EXPIRE` / `CANCELLED`→`EXPIRED`.

**Indentation hazard (Pitfall 4 — match the file, never normalize):**
- **TABS:** `order_handler/` (lifecycle_manager, reconcile_manager, order_manager, order_handler, admission_manager), `execution_handler/` (simulated, matching_engine), `trading_system/` (backtest_runner).
- **4 SPACES:** `core/enums/order.py`, `core/enums/execution.py`, and the events package (`events/fill.py`).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/enums/order.py` (add `OrderCommand.EXPIRE` + map) | config-enum | n/a | existing `CANCEL` member + `order_command_map` (same file, lines 94/109) | exact |
| `core/enums/execution.py` (add `FillStatus.EXPIRED`) | config-enum | n/a | existing `CANCELLED` member (same file, line 75) | exact |
| `order_handler/lifecycle/lifecycle_manager.py` (add `expire_all_resting`) | manager (business logic) | event-driven / batch sweep | `cancel_order` (same file, lines 147-219) | exact |
| `order_handler/order_manager.py` (delegate `expire_all_resting`) | manager (facade delegation) | request-response | `cancel_order` delegation (same file, lines 215-218) | exact |
| `order_handler/order_handler.py` (add EXPIRE handler + enqueue) | handler (thin interface) | event-driven | `cancel_order` handler (same file, lines 183-213) | exact |
| `order_handler/reconcile/reconcile_manager.py` (add EXPIRED arm) | manager (FRAGILE) | event-driven | `_apply_cancelled` + CANCELLED dispatch (same file, lines 144-146, 218-219) | exact |
| `execution_handler/exchanges/simulated.py` (add EXPIRE arm) | service (exchange) | event-driven | `on_order` CANCEL arm (same file, lines 274-283) | exact |
| `trading_system/backtest_runner.py` (invoke sweep + final drain) | run driver (orchestration) | batch | direct `record_metrics` call (same file, line 102) | role-match (orchestration precedent) |
| `tests/e2e/.../never_fill` (re-purpose as D-05 proof leaf) | e2e test | e2e | existing `never_fill/scenario.py` + 2 sltp leaves | exact (re-baseline) |

**Removals (D-03):** `order_handler.py:215-245` (`create_order`), `order_manager.py:206-208`
(`create_orders_from_signal` delegation), `admission_manager.py:286-335`
(`create_orders_from_signal` method). **KEEP** `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL`
(`core/enums/order.py:124`) — see Shared Pattern "Dead-Path Removal" / Pitfall 1.

---

## Pattern Assignments

### `core/enums/order.py` — add `OrderCommand.EXPIRE` (config-enum, 4 SPACES)

**Analog:** existing `OrderCommand.CANCEL` member + `order_command_map`, same file.

Add a member to the `OrderCommand` Enum (currently `NEW`/`CANCEL`/`MODIFY`, lines 93-95) and a
matching `order_command_map` entry (lines 107-111). `EXPIRED` already exists in `OrderStatus`
(line 47), `order_status_map` (line 72), and `VALID_ORDER_TRANSITIONS` (PENDING→EXPIRED at line 78,
PARTIALLY_FILLED→EXPIRED at line 79, EXPIRED terminal `[]` at line 83) — **no change needed there.**

Existing CANCEL member + map to mirror (lines 93-95, 107-111):
```python
    NEW = "NEW"
    CANCEL = "CANCEL"
    MODIFY = "MODIFY"
# ...
order_command_map = {
	"NEW": OrderCommand.NEW,
	"CANCEL": OrderCommand.CANCEL,
	"MODIFY": OrderCommand.MODIFY
}
```
Add `EXPIRE = "EXPIRE"` to the Enum and `"EXPIRE": OrderCommand.EXPIRE` to the map. The case-insensitive
`_missing_` (lines 97-104) needs no change. **Note:** this file uses TABS in the dict body but the
Enum members are space-indented — match each region exactly (the file is mixed by region).

---

### `core/enums/execution.py` — add `FillStatus.EXPIRED` (config-enum, 4 SPACES)

**Analog:** existing `FillStatus.CANCELLED` member, same file (line 75).

The Enum currently has `EXECUTED`/`REFUSED`/`CANCELLED` (lines 73-75). Add `EXPIRED = "EXPIRED"`.
`FillEvent.new_fill('EXPIRED', ...)` does `FillStatus(status)` (events/fill.py) and raises
`ValueError` until this member exists — **add this BEFORE wiring the exchange EXPIRE arm** (Pitfall 2,
enum-first ordering). The `_missing_` (lines 77-89) needs no change.

```python
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    # ADD: EXPIRED = "EXPIRED"
```

---

### `order_handler/lifecycle/lifecycle_manager.py` — add `expire_all_resting()` (manager, TABS)

**Analog:** `cancel_order` (same file, lines 147-219). This is THE template (D-08).

The sweep is a per-portfolio, `order_id`-sorted loop (D-10) where each iteration is the body of
`cancel_order` with `expire_order` swapped for `cancel_order` and `OrderCommand.EXPIRE` for `CANCEL`.

Core CANCELLED template body to mirror (lines 176-208):
```python
		success = order.cancel_order(reason)                  # EXPIRE: order.expire_order(reason)
		if success:
			self.order_storage.update_order(order)
			# WR-03 (part 1): disarm a PercentFromFill pending entry; children/non-PFF no-op.
			self._brackets.consume(order.id)                  # mirror for symmetry (Open Q2 — no-ops at run end)
			# WR-04: local terminal transition owns the release; idempotent —
			# a later exchange CANCELLED fill re-releasing is a silent no-op.
			if self.portfolio_handler is not None:
				self.portfolio_handler.release(order.portfolio_id, order.id)
			order_event = OrderEvent.new_order_event(order, command=OrderCommand.CANCEL)  # EXPIRE: command=OrderCommand.EXPIRE
			return OperationResult.success_result(
				f"Order {order_id} cancelled: {reason}",
				order_events=[order_event],
				operation_type=OrderOperationType.CANCEL_ORDER,         # EXPIRE: pick/keep an op-type (CANCEL_ORDER or a new EXPIRE_ORDER — Claude's discretion)
				affected_order_ids=[order_id])
```

**Sweep wrapper** (D-08/D-10 — the new outer structure cancel_order does not have): iterate
`self.portfolio_handler.get_active_portfolios()` (deterministic portfolio order), and within each
`sorted(self.get_active_orders(pf.id), key=lambda o: o.id)` (UUIDv7 monotonic → stable). Collect one
`OperationResult` per expired order, return `list[OperationResult]`. The manager NEVER touches the
queue (D-18) — it returns the `OrderEvent(EXPIRE)`-carrying results; the **handler** enqueues them.

Read APIs the sweep uses (verified present, `order_manager.py:228-234` → `in_memory_storage.py`):
`get_active_orders(portfolio_id)` (is_active predicate filter), `get_orders_by_status` (alt). The
`portfolio.id` / `order.id` sort keys exist (UUIDv7 `OrderId`).

`Order.expire_order()` already exists (`order.py:435-449`) — `add_state_change(OrderStatus.EXPIRED,
reason, OrderTriggerSource.SYSTEM)`; `is_terminal`/`is_active` are EXPIRED-aware. It returns `bool`
(success), like `cancel_order` — guard on the return exactly as the template does (line 177).

---

### `order_handler/order_manager.py` — delegate `expire_all_resting()` (facade, TABS)

**Analog:** `cancel_order` pass-through delegation (same file, lines 215-218).

```python
	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None,
	                reason: str = "user cancellation") -> OperationResult:
		"""Delegate order cancellation to LifecycleManager (D-07)."""
		return self.lifecycle_manager.cancel_order(order_id, portfolio_id, reason)
```
Add a one-line `expire_all_resting(self) -> list[OperationResult]` that delegates to
`self.lifecycle_manager.expire_all_resting()`. (If placed directly on `OrderManager` instead, skip
this — Claude's discretion per D-08; but the cancel_order→LifecycleManager split is the established
shape.)

---

### `order_handler/order_handler.py` — EXPIRE handler that enqueues (thin interface, TABS)

**Analog:** the `cancel_order` handler (same file, lines 183-213).

The handler's job is "delegate to manager → enqueue the returned `OrderEvent`s". The cancel handler
shows the exact enqueue idiom (lines 204-211):
```python
		# Delegate to OrderManager
		result = self.order_manager.cancel_order(order_id, portfolio_id, reason)
		# Generate OrderEvent if cancellation was successful
		if result.success and result.order_events:
			for order_event in result.order_events:
				self.global_queue.put(order_event)
```
The new handler method (e.g. `expire_all_resting`) loops the `list[OperationResult]` from the
manager and `self.global_queue.put(order_event)` for each carried `OrderEvent(EXPIRE)`. The dead
`create_order` (lines 215-245) shows the multi-result enqueue loop shape — reuse that loop shape
while DELETING `create_order` itself (D-03).

---

### `order_handler/reconcile/reconcile_manager.py` — EXPIRED arm (FRAGILE manager, TABS)

**Analog:** `_apply_cancelled` + the CANCELLED dispatch branch (same file). **D-09 — this is the
one FRAGILE touch; slot into the existing per-status shape, keep the try/finally skeleton
byte-identical (Phase 5 D-06 discipline).** Three edits, all peers of the CANCELLED lines:

1. `_classify` (lines 106-112) — add EXPIRED beside CANCELLED (line 108-109):
```python
		if status == FillStatus.EXECUTED:
			return True, OrderStatus.FILLED
		if status == FillStatus.CANCELLED:
			return True, OrderStatus.CANCELLED
		if status == FillStatus.REFUSED:
			return True, OrderStatus.REJECTED
		# ADD: if status == FillStatus.EXPIRED: return True, OrderStatus.EXPIRED
		return False, None
```

2. Named arm beside `_apply_cancelled` (lines 144-146):
```python
	@staticmethod
	def _apply_cancelled(order: "Order") -> None:
		"""CANCELLED arm: mark the order CANCELLED (exchange cancellation)."""
		order.cancel_order("exchange cancellation")
	# ADD _apply_expired: order.expire_order("exchange expiration")
```

3. Dispatch `elif` beside the CANCELLED branch (lines 216-228):
```python
			if fill_event.status == FillStatus.EXECUTED:
				applied = self._apply_executed(order, fill_event, order_id)
			elif fill_event.status == FillStatus.CANCELLED:
				self._apply_cancelled(order)
			elif fill_event.status == FillStatus.REFUSED:
				self._apply_refused(order)
			# ADD: elif fill_event.status == FillStatus.EXPIRED: self._apply_expired(order)
			else:
				# Defensive: _classify marked terminal but no arm dispatches it.
				raise NotImplementedError(
					f'terminal fill status {fill_event.status!r} has no reconcile arm')
```

**LANDMINE (D-09) — idempotency is FREE, no explicit guard needed.** The sweep already set the
mirror to EXPIRED locally; the returning `FillEvent(EXPIRED)` re-runs `_apply_expired` →
`order.expire_order()` → `add_state_change(EXPIRED, ...)`. **CONFIRMED (order.py:307-309):**
`add_state_change` returns `False` (does NOT raise) on a transition absent from
`VALID_ORDER_TRANSITIONS` — and `VALID_ORDER_TRANSITIONS[EXPIRED] == []`, so EXPIRED→EXPIRED is a
silent no-op (status stays EXPIRED). The release in the `finally` (`_release_reservation`) is
independently idempotent (a second `release()` pops nothing). **Do NOT add a custom "already
expired?" flag** — the transition table + idempotent pop give idempotency for free.

**Pitfall 3:** if you add EXPIRED to `_classify` without the matching dispatch `elif`, the defensive
`else` raises `NotImplementedError` BEFORE `should_release` is armed → reservation stuck → run
aborts. Add all THREE edits in the same change.

---

### `execution_handler/exchanges/simulated.py` — EXPIRE arm in `on_order` (exchange, TABS)

**Analog:** the CANCEL arm in `on_order` (same file, lines 274-283).

```python
		if event.command == OrderCommand.CANCEL:
			# Only acknowledge a cancel for an order actually resting; a cancel
			# for an unknown/already-filled order emits no spurious fill.
			if event.order_id is not None and self.matching_engine.cancel(event.order_id):
				self.global_queue.put(FillEvent.new_fill(
					'CANCELLED', event, price=event.price, quantity=event.quantity,
					commission=Decimal("0")))
			return
```
Add a parallel `elif event.command == OrderCommand.EXPIRE:` arm: same `matching_engine.cancel(order_id)`
bool guard (removes the resting order; returns False → no spurious fill for a non-resting order),
then `new_fill('EXPIRED', event, price=event.price, quantity=event.quantity, commission=Decimal("0"))`.
`MatchingEngine.cancel(order_id)` (matching_engine.py:99-101) is the reused accessor — `pop` returning
present-bool. `Decimal("0")` commission: an EXPIRED order never settled (D-22).

---

### `trading_system/backtest_runner.py` — invoke sweep + final drain (run driver, TABS)

**Analog:** the direct `portfolio.record_metrics(time_event.time)` orchestration call (line 102) —
precedent for the runner invoking domain work directly at the run boundary (D-08).

The run-end seam is immediately AFTER the `for time_event in engine.time_generator:` loop exits
(`_run_backtest`, lines 95-108) — OR in `BacktestTradingSystem.run` after `runner.run()` (Claude's
discretion, D-08). Pattern:
```python
		for time_event in engine.time_generator:
			engine.clock.set_time(time_event.time)
			engine.global_queue.put(time_event)
			engine.event_handler.process_events()
			for portfolio in engine.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(time_event.time)   # <- direct orchestration precedent
			if on_tick is not None:
				on_tick(self, time_event)
		# RUN-END SEAM (after the loop):
		# engine.order_handler.expire_all_resting()   # handler enqueues OrderEvent(EXPIRE)
		# engine.event_handler.process_events()       # ONE final drain — provably NON-CASCADING
```
The final `process_events()` is the symmetric shutdown bookend of the per-tick `put(); process_events()`
cycle. **Provably non-cascading** (D-08): the routes literal sends ORDER→`on_order` only and
FILL→portfolio+reconcile only; EXPIRE emits only `OrderEvent(EXPIRE) → FillEvent(EXPIRED)` — NO
signals, NO new orders.

---

### `tests/e2e/matching/never_fill/` — re-purpose as the D-05 proof leaf (e2e)

**Analog:** existing `never_fill/scenario.py` (already builds the exact "far-from-market BUY-LIMIT
that never fills" scenario D-05 describes) + the 2 sltp leaves' golden discipline.

This leaf's docstring currently asserts "no run-end expiry / GAP #1" (lines 4-7, 42-47) and the
VERIFY block locks `status PENDING` — **now actively wrong** (Pitfall 5). Rewrite the docstring +
VERIFY block to assert the order ends EXPIRED (not PENDING) and position/cash untouched; re-freeze
`golden/orders.csv` (PENDING→EXPIRED) under owner sign-off via the harness `--freeze` discipline.
This is the cheapest D-05 vehicle. The other 2 re-baseline leaves are the bracket-disposition case
(D-02): `tests/e2e/sltp/from_decision_held` and `tests/e2e/sltp/from_fill_held` (SL+TP brackets on a
still-open MARKET-BUY → both flip to EXPIRED). **These 3 leaves are the COMPLETE D-11 blast radius**
(only 3 committed `golden/orders.csv` carry a `,PENDING,` row); the other 12 stay green unchanged.

---

## Shared Patterns

### Retire-a-resting-order (the unifying EXPIRE = CANCEL hybrid)
**Source:** `order_handler/lifecycle/lifecycle_manager.py:176-208` (cancel_order body).
**Apply to:** the sweep method, AND it explains why the exchange arm + reconcile arm exist.
The pattern is THREE coordinated actions per resting order: (1) **local mirror transition**
(`order.expire_order()`), (2) **local idempotent reservation release** (`portfolio_handler.release()`,
WR-04 belt-and-suspenders), (3) **emit `OrderEvent(EXPIRE)`** so the exchange clears `_resting` and
emits the returning `FillEvent(EXPIRED)` (which reconcile treats as an idempotent no-op). EXPIRED is
a *peer of CANCELLED* — same machinery, ONE pattern, not two.

### Terminal release in `finally`, idempotent (WR-03/WR-04/T-05-17)
**Source:** `order_handler/reconcile/reconcile_manager.py:189-237` (the `should_release` /
`body_raised` / `try`/`finally` skeleton).
**Apply to:** the reconcile EXPIRED arm. **Keep this skeleton byte-identical** — the EXPIRED arm is
ONLY a new `elif` + `_classify` line + named arm. A sequential `apply(); release()` rewrite
reintroduces the WR-04 skip-release-on-raise bug (the REJECTED anti-pattern). `should_release` is
armed AFTER the terminal status and BEFORE further work so a later raise still releases.

### Cross-domain write goes through the queue
**Source:** project core law (CLAUDE.md) + the existing CANCEL→exchange→fill round-trip.
**Apply to:** the sweep MUST NOT reach into `MatchingEngine._resting` directly. Clearing the
exchange book is a cross-domain WRITE → it goes through `OrderEvent(EXPIRE)` → `on_order` →
`matching_engine.cancel()`. This keeps the order mirror and exchange book in agreement at every
observable point.

### Dead-Path Removal — KEEP the enum (D-03 / Pitfall 1)
**Source:** grep this session — `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` has TWO referencers.
**Apply to:** the removal change. **REMOVE:** `order_handler.py:215-245` (`create_order`),
`order_manager.py:206-208` (delegation), `admission_manager.py:286-335` (method). **KEEP:**
`core/enums/order.py:124` `CREATE_ORDERS_FROM_SIGNAL` — it is STILL referenced by the LIVE,
validated path `bracket_manager.py:220` (`_assemble_bracket_and_emit`'s error result), which
`process_signal` calls (`admission_manager.py:249`). The CONTEXT "REMOVE if unused after" condition
is FALSE. Deleting the enum member → mypy/import error. Also (D-03a) drop the `create_order` clause
from the W4-04 validator-overlap doc in `CLAUDE.md` + `.planning/codebase/CONVENTIONS.md` but KEEP
the live-path justification and the validator code.

### Decimal money at the edge
**Source:** CLAUDE.md money policy + the CANCEL arm's `commission=Decimal("0")`.
**Apply to:** the exchange EXPIRE fill — `commission=Decimal("0")`, price/quantity pass through the
order's own Decimal values (never settled). Never `Decimal(float)`.

## No Analog Found

None. Every new EXPIRED surface has a proven CANCELLED-lifecycle analog in the same file. The runner
seam's analog is a role-match (orchestration precedent, not a CANCELLED peer) but is concrete.

## Metadata

**Analog search scope:** `itrader/order_handler/{lifecycle,reconcile,admission,brackets}/`,
`itrader/order_handler/{order_handler,order_manager,order}.py`,
`itrader/execution_handler/{exchanges/simulated,matching_engine}.py`,
`itrader/core/enums/{order,execution}.py`, `itrader/trading_system/backtest_runner.py`,
`itrader/events_handler/events/fill.py`, `tests/e2e/{matching/never_fill,sltp/*}/`.
**Files scanned:** 11 source reads + 1 grep sweep.
**Pattern extraction date:** 2026-06-13
