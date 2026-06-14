# Phase 6: Order Lifecycle & Time-in-Force - Research

**Researched:** 2026-06-13
**Domain:** Backtest order-lifecycle wiring — run-end resting-order disposition (implicit GTC-until-run-end), dead-path removal, owner-gated re-baseline
**Confidence:** HIGH (all 8 deferred empirical questions resolved by direct code tracing in this session)

## Summary

This phase is a wiring + removal task on a code surface that already exists in full. `OrderStatus.EXPIRED`,
`VALID_ORDER_TRANSITIONS[EXPIRED] == []`, `Order.expire_order()`, `Order.is_terminal` (EXPIRED-aware), and
the order-store query APIs (`get_active_orders`/`get_orders_by_status`/`count_orders_by_status`) are all
present and unwired. The locked design (CONTEXT.md Option A) — `expire_all_resting()` as a peer of
`cancel_order`, a first-class `OrderCommand.EXPIRE` + `FillStatus.EXPIRED` reconcile arm, runner-invoked at
the post-loop orchestration boundary, followed by ONE final `process_events()` drain — maps cleanly onto
existing templates. Nothing in the design needs to be re-litigated; this research verifies the empirical
unknowns the design was conditioned on.

**The two headline empirical results:**
1. **D-04 is provably equity-neutral.** `total_equity = total_market_value + cash`, and `cash` reads the
   FULL ledger balance (`cash_manager.balance`), NEVER `available_balance`. `release()` only pops a reservation
   (`_storage.pop_reservation`) and leaves `_balance` untouched. Reservations move `available_cash` only — a
   figure `total_equity` never reads and the metric snapshots never record. Therefore expiring resting orders
   and releasing their reservations CANNOT move `final_equity 46189.87730727451` or `trade_count 134`. The
   SMA_MACD oracle stays **byte-exact** (D-04's working hypothesis confirmed); any drift is an unambiguous bug.
2. **D-11 blast radius is exactly 3 e2e leaves.** Only 3 of 15 committed `golden/orders.csv` files contain a
   PENDING row that flips to EXPIRED: `matching/never_fill` (a standalone unfilled BUY-LIMIT) and
   `sltp/from_decision_held` + `sltp/from_fill_held` (SL+TP brackets on a still-open MARKET-BUY position).
   The other 12 are all-terminal and stay green unchanged.

**Primary recommendation:** Implement Option A exactly as locked. Add `OrderCommand.EXPIRE` + `FillStatus.EXPIRED`;
write `expire_all_resting()` mirroring `cancel_order` (local EXPIRED transition + idempotent `release()` + emit
`OrderEvent(EXPIRE)`); add the parallel EXPIRE arm in `SimulatedExchange.on_order` and the EXPIRED arm in
`ReconcileManager` (`_classify` + `_apply_expired`, idempotent against the already-terminal mirror); invoke the
sweep in `BacktestRunner._run_backtest` after the for-loop then run one final `process_events()`. Remove the dead
`create_order` path — but DO NOT delete `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` (a live path still uses it,
see Pitfall 1). Re-baseline only the 3 affected e2e leaves under owner sign-off; SMA_MACD oracle stays byte-exact.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Run-end sweep only.** Wire ONLY run-end disposition: at run end every resting order → `EXPIRED` via
  `expire_order()`. No per-order `time_in_force` field, no GTC/DAY/GTD enum, no session/calendar concepts. One
  implicit "GTC-until-run-end" semantic. A real TIF model is deferred to N+4.
- **D-02 — Expire ALL resting orders.** Every order still resting → EXPIRED: unfilled standalone entry limit/stop
  orders AND the protective SL/TP brackets on still-open positions. **Positions are NOT liquidated** — they stay
  open and are marked-to-last-close for final equity exactly as today.
- **D-03 — Remove the dead second path.** Delete `OrderHandler.create_order` +
  `AdmissionManager.create_orders_from_signal` (and the now-unused `CREATE_ORDERS_FROM_SIGNAL` plumbing).
  *(Research caveat: the enum member is NOT fully unused — see Pitfall 1.)*
- **D-03a — Soften the validator-overlap doc.** Drop the `create_order` clause from the W4-04 dual-layer-validator
  justification in `CLAUDE.md` / `.planning/codebase/CONVENTIONS.md`; KEEP the live-path justification. Do NOT
  remove the validator code.
- **D-04 — Measure-first posture.** Produce attribution of which orders expire and whether that moves
  `trade_count`/`final_equity`/any reservation-equity figure. Expected: metric-neutral → byte-exact. Fallback:
  re-baseline with full attribution if real movement is shown. VERIFY reservation→equity semantics. Owner-gate
  applies to whichever outcome lands.
- **D-05 — Crafted run-end-resting proof scenario.** Prove the EXPIRED mechanic with a crafted minimal
  deterministic scenario that provably leaves an order resting at run end. Doubles as a new dedicated e2e leaf.
- **D-06 — Determinism still binds.** Determinism double-run byte-identical and `mypy --strict` clean hold
  regardless of posture.
- **D-07 — Internal attribution + owner sign-off; NO new external cross-val.** No new backtesting.py/backtrader run.
- **D-08 — `expire_all_resting()` as a peer to `cancel_order`.** New business-logic method (local EXPIRED transition
  + local idempotent reservation release + emit `OrderEvent`). Business logic in the manager; the **runner invokes
  it at the orchestration boundary** after the for-loop, then runs ONE final `process_events()` drain. Provably
  non-cascading (emits only `OrderEvent(EXPIRE) → FillEvent`, no signals/orders).
- **D-09 — First-class EXPIRE seam.** Add `OrderCommand.EXPIRE` + `FillStatus.EXPIRED`; exchange clears `_resting`
  + emits `FillEvent(EXPIRED)`; reconcile gets an EXPIRED terminal arm (peer to CANCELLED — terminal, releases),
  idempotent against the already-locally-EXPIRED mirror. **Phase 6 DOES touch the FRAGILE `reconcile/` path.**
  - **LANDMINE:** the mirror must end EXPIRED and the returning `FillEvent(EXPIRED)` must NOT attempt
    `EXPIRED → EXPIRED`/`EXPIRED → CANCELLED` (terminal `[]`). The arm must be idempotent on an already-terminal
    order, mirroring the cancel path's "later CANCELLED fill re-release is a silent no-op" handling.
- **D-10 — Ordering contract: portfolio order, then `order_id`.** Iterate active portfolios in the engine's
  existing `get_active_portfolios()` order; within each, expire orders sorted by `order_id` (UUIDv7 — monotonic,
  creation-ordered → stable sort). VERIFY a per-portfolio active-order query + well-defined `order_id` sort exist.
- **D-11 — Measure → attribute → re-baseline only affected leaves.** Run the full e2e suite; identify which leaves
  now end with EXPIRED orders; attribute WHY; re-baseline ONLY those leaves' resting-order-disposition assertions
  under the owner-gate. Untouched leaves stay green unchanged.
- **D-12 — Internal status only; no new reporting surface.** EXPIRED flows through generic status queries for free
  (`count_orders_by_status` buckets by status name). Add NO new reporting artifact/summary line/metric.

### Claude's Discretion
- Exact method placement/names for `expire_all_resting()` and its manager/lifecycle split (D-08), subject to "peer
  of `cancel_order`."
- Exact shape of the reconcile EXPIRED arm + the idempotency guard for already-terminal orders (D-09), subject to
  the LANDMINE.
- Exact crafted-scenario parameters (offset, cadence, which bar) for D-05, subject to "provably leaves an order
  resting at run end."
- Where the runner invokes `expire_all_resting()` + the final drain (inside `_run_backtest` after the loop vs
  `BacktestTradingSystem.run` after `runner.run()`), subject to D-08.

### Deferred Ideas (OUT OF SCOPE)
- **Per-order time-in-force model (GTC/DAY/GTD/IOC/FOK) → N+4 Live Trading Readiness.**
- **Liquidating/force-closing open positions at run end** — out of scope; mark-to-close like backtrader/Lean/nautilus.
- **Per-venue order validation ("stop would trigger immediately") → N+4.**
- **N+2 (margin/shorts/leverage/trailing)** builds on this completed lifecycle surface.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LIFE-01 | Wire run-end resting-order disposition on the backtest path (`expire_order()` + `EXPIRED`) and gate/remove the `create_order` second path (W4-09), under an owner-gated re-baseline. | Full lifecycle surface exists and is traced below: `Order.expire_order()` (order.py:435), EXPIRED enum slots all present (enums/order.py:47,78-83), cancel-path template (lifecycle_manager.py:147-219), reconcile arm structure (reconcile_manager.py:87-112), exchange CANCEL arm to mirror (simulated.py:274-283), store query APIs (in_memory_storage.py:130-136), non-cascade proof (full_event_handler.py:68-87), dead-path zero-caller confirmation (grep: 0 `.create_order(` callsites), D-04 equity-neutrality proof (portfolio.py:199-235 + cash_manager.py:418-448), D-11 3-leaf blast radius (3 PENDING golden orders.csv). |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect resting orders at run end | Order mirror (`OrderManager` storage) | Matching engine (`_resting` book) | The mirror's `get_active_orders` predicate is the authoritative "still resting" query; the exchange book is the parallel truth cleared via the queue. |
| Local EXPIRED mirror transition + reservation release | Order lifecycle (`LifecycleManager`/`OrderManager`) | Portfolio read-model (`release()`) | Peer of `cancel_order`: the order layer owns the terminal transition; the reservation release goes through the injected `PortfolioReadModel` seam (same as cancel). |
| Clear the exchange resting book | Execution (`SimulatedExchange` / `MatchingEngine`) | — | Cross-domain WRITE → must go through the queue via `OrderEvent(EXPIRE)`; only the exchange owns `_resting`. |
| Reconcile the returning EXPIRED fill | Order reconcile (`ReconcileManager`) | Portfolio (`on_fill`) | FILL routes portfolio-first then order-mirror; the EXPIRED arm is idempotent against the already-locally-EXPIRED mirror. |
| Orchestrate the sweep + final drain | Run driver (`BacktestRunner`) | — | Run-end is an orchestration concern, not a per-handler one — same precedent as the direct `record_metrics` call. |
| Report EXPIRED status | Reporting (`reporting/orders.py` + `count_orders_by_status`) | — | EXPIRED is a status string that buckets for free; no new surface (D-12). |

## Standard Stack

This is a brownfield wiring task — no new external packages. The "stack" is the existing iTrader internal surface.
**No `pip install` required; no Package Legitimacy Audit needed (zero external dependencies added).**

| Internal surface | Location | Purpose | State |
|------------------|----------|---------|-------|
| `OrderStatus.EXPIRED` | `core/enums/order.py:47` | Terminal expired status | EXISTS, in `order_status_map`, `VALID_ORDER_TRANSITIONS` |
| `VALID_ORDER_TRANSITIONS` | `core/enums/order.py:76-84` | PENDING→EXPIRED allowed (line 78); PARTIALLY_FILLED→EXPIRED allowed (line 79); EXPIRED terminal `[]` (line 83) | EXISTS |
| `Order.expire_order()` | `order.py:435-449` | `add_state_change(OrderStatus.EXPIRED, reason, OrderTriggerSource.SYSTEM)` | EXISTS, unwired |
| `Order.is_terminal` (property) | `order.py:131-133` | Includes EXPIRED | EXISTS (note: property, not method — CONTEXT.md said `is_terminal()`) |
| `OrderCommand` | `core/enums/order.py:87-111` | NEW/CANCEL/MODIFY + `order_command_map` | ADD `EXPIRE` member + map entry (D-09) |
| `FillStatus` | `core/enums/execution.py:59-89` | EXECUTED/REFUSED/CANCELLED | ADD `EXPIRED` member (D-09) |
| `get_active_orders(portfolio_id)` | `order_manager.py:232` → `in_memory_storage.py:134-136` | `order.is_active` predicate filter | EXISTS (D-10) |
| `get_orders_by_status(status, portfolio_id)` | `order_manager.py:228` → `in_memory_storage.py:130-132` | status filter | EXISTS (D-10) |
| `count_orders_by_status(portfolio_id)` | `order_manager.py:248` → `in_memory_storage.py:177-183` | status-name → count dict | EXISTS — EXPIRED buckets for free (D-12) |
| `get_active_portfolios()` | `portfolio_handler.py:210` | deterministic portfolio iteration order | EXISTS (D-10) |
| `LifecycleManager.cancel_order` | `lifecycle_manager.py:147-219` | The exact template for `expire_all_resting()` | EXISTS — mirror it |
| `PortfolioReadModel.release()` | `portfolio_handler.py:252-254` | idempotent reservation pop (WR-04) | EXISTS — reuse |
| `MatchingEngine.cancel(order_id)` | `matching_engine.py:99` | removes a resting order, returns bool | EXISTS — reuse for EXPIRE |
| `FillEvent.new_fill(status: str, ...)` | `fill.py:77-136` | `FillStatus(status)` parse → frozen fill | EXISTS — `new_fill('EXPIRED', ...)` works ONCE `FillStatus.EXPIRED` is added |
| `build_orders_snapshot` | `itrader/reporting/orders.py` (imported `tests/e2e/conftest.py:85-87`) | role/status orders frame for `golden/orders.csv` | EXISTS — emits `o.status.name` |

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages — it is an internal wiring + removal task using
existing iTrader modules and stdlib. No registry verification, slopcheck, or postinstall audit required.

## Architecture Patterns

### System Architecture Diagram

```
                       PER-TICK LOOP (unchanged)                         RUN-END SWEEP (new, D-08)
  ┌──────────────────────────────────────────────────┐    ┌──────────────────────────────────────────────┐
  │  TimeGenerator ─► queue.put(TimeEvent)            │    │  for-loop EXITS (no more bars)                │
  │       │                                           │    │       │                                        │
  │       ▼                                           │    │       ▼                                        │
  │  process_events()                                 │    │  OrderManager.expire_all_resting()             │
  │   TIME ─► BAR ─► (mark / match / signals)         │    │   for pf in get_active_portfolios():           │
  │   SIGNAL ─► on_signal ─► OrderEvent(NEW)          │    │     for o in sorted(get_active_orders(pf),     │
  │   ORDER ─► on_order ─► rest in MatchingEngine     │    │                     key=lambda o: o.id):       │
  │   FILL ─► portfolio.on_fill + reconcile.on_fill   │    │       o.expire_order()        # local EXPIRED  │
  │       │                                           │    │       portfolio.release(pf, o.id)  # WR-04     │
  │       ▼                                           │    │       emit OrderEvent(o, command=EXPIRE)       │
  │  record_metrics(time)  (DIRECT call, oracle-dark) │    │       │                                        │
  └──────────────────────────────────────────────────┘    │       ▼                                        │
                                                           │  ONE final process_events() drain:             │
                                                           │   ORDER ─► on_order(EXPIRE)                     │
                                                           │     ─► MatchingEngine.cancel(order_id)         │
                                                           │     ─► emit FillEvent(EXPIRED)                  │
                                                           │   FILL ─► portfolio.on_fill (no-op: never      │
                                                           │            settled, $0 commission)             │
                                                           │       ─► reconcile.on_fill (EXPIRED arm,        │
                                                           │            idempotent — mirror already EXPIRED) │
                                                           │  ── provably NON-CASCADING: emits no SIGNAL,    │
                                                           │     no new ORDER ──                             │
                                                           └────────────────────────────────────────────────┘
```

### Pattern 1: Cancel = local-transition + idempotent-release + emit (the EXPIRE template)
**What:** `LifecycleManager.cancel_order` does THREE things on a resting order: a local mirror transition
(`order.cancel_order(reason)` → status), a local idempotent `portfolio_handler.release(portfolio_id, order_id)`
(WR-04 — belt-and-suspenders so a never-acknowledged cancel doesn't hold the BUY reservation forever), and emits
`OrderEvent(order, command=OrderCommand.CANCEL)` to clear the exchange book. The later exchange `FillEvent(CANCELLED)`
re-release is a silent no-op (idempotent).
**When to use:** EXPIRE mirrors this EXACTLY — the only differences are `order.expire_order()` instead of
`order.cancel_order()` and `OrderCommand.EXPIRE` instead of `CANCEL`. Note `cancel_order` also calls
`self._brackets.consume(order.id)` (WR-03 part 1) to disarm a PercentFromFill pending entry; `expire_all_resting`
should decide whether to consume too (a run-end sweep over already-emitted resting orders likely has no live pending
PercentFromFill entry, but mirroring the consume is the safe, symmetric choice).
**Source:** `itrader/order_handler/lifecycle/lifecycle_manager.py:166-208`
```python
# cancel_order body (TABS — order_handler/ convention):
success = order.cancel_order(reason)        # EXPIRE: order.expire_order(reason)
if success:
    self.order_storage.update_order(order)
    self._brackets.consume(order.id)        # WR-03 part 1 (consider mirroring)
    if self.portfolio_handler is not None:  # WR-04 idempotent release
        self.portfolio_handler.release(order.portfolio_id, order.id)
    order_event = OrderEvent.new_order_event(order, command=OrderCommand.CANCEL)  # EXPIRE: command=EXPIRE
    return OperationResult.success_result(..., order_events=[order_event], ...)
```

### Pattern 2: SimulatedExchange CANCEL arm (the EXPIRE arm template)
**What:** `on_order` routes by command. The CANCEL arm: `if event.command == OrderCommand.CANCEL: if
self.matching_engine.cancel(event.order_id): queue.put(FillEvent.new_fill('CANCELLED', event, price=..., quantity=...,
commission=Decimal("0")))`. The cancel is only acknowledged when the order WAS actually resting (the `cancel()`
bool guard), so a cancel for an unknown/already-filled order emits no spurious fill.
**When to use:** Add a parallel `elif event.command == OrderCommand.EXPIRE:` arm that does the same:
`matching_engine.cancel(order_id)` (removes resting) then `new_fill('EXPIRED', event, price=event.price,
quantity=event.quantity, commission=Decimal("0"))`.
**Source:** `itrader/execution_handler/exchanges/simulated.py:274-283`

### Pattern 3: Reconcile `_classify` + per-status arm (the EXPIRED arm)
**What:** `ReconcileManager._classify(status)` maps `FillStatus → (terminal, OrderStatus)` for READABILITY; the
named arms (`_apply_executed`/`_apply_cancelled`/`_apply_refused`) drive the actual mirror transition. The
`should_release` flag is armed AFTER the terminal status and BEFORE further work so a later raise still releases
(WR-04); the release runs in `_release_reservation` (the `finally`). There is a DEFENSIVE `else: raise
NotImplementedError(...)` that fires when `_classify` marks a status terminal but no arm dispatches it.
**When to use (D-09 + LANDMINE):** Add `FillStatus.EXPIRED → (True, OrderStatus.EXPIRED)` to `_classify` (line ~112,
peer to the CANCELLED line 108-109), an `_apply_expired(order)` arm, AND an `elif fill_event.status ==
FillStatus.EXPIRED:` dispatch (else the defensive `NotImplementedError` fires). The arm must be IDEMPOTENT against
the already-locally-EXPIRED mirror (the sweep already set EXPIRED locally). The cancel path's `_apply_cancelled`
calls `order.cancel_order("exchange cancellation")` unconditionally — but `Order.cancel_order`/`reject_order`/
`expire_order` all route through `add_state_change`, which is gated by `VALID_ORDER_TRANSITIONS`: an
`EXPIRED → EXPIRED` transition is NOT in `VALID_ORDER_TRANSITIONS[EXPIRED] == []`, so `add_state_change` returns
`False` (no-op) on the already-terminal order. **CONFIRMED (order.py:307-309):** `add_state_change` returns `False`
on an invalid transition — it does NOT raise (`if not self._is_valid_transition(...): return False`). So the EXPIRED
arm needs NO explicit terminal guard: `EXPIRED → EXPIRED` is a silent no-op (status stays EXPIRED). The release is
independently idempotent (a second `release()` pops nothing → no-op).
**Source:** `itrader/order_handler/reconcile/reconcile_manager.py:87-112, 143-151, 200-231`

### Anti-Patterns to Avoid
- **Clearing `MatchingEngine._resting` directly from the order layer.** That is a cross-domain WRITE; it MUST go
  through the queue via `OrderEvent(EXPIRE)` (the project's core law). Reaching into the exchange book from the
  sweep breaks the "mirror and book agree at every observable point" invariant D-08 cites.
- **Liquidating open positions at run end.** D-02 / Deferred — positions stay open and mark-to-last-close. Only
  resting ORDERS are disposed.
- **Rewriting the reconcile `try`/`finally`/`should_release` skeleton.** The EXPIRED arm SLOTS INTO the existing
  per-status shape (Phase 5 D-06 discipline). Keep the exception-safety skeleton byte-identical — a sequential
  `apply(); release()` rewrite reintroduces the WR-04 skip-release-on-raise bug.
- **Deleting `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` blindly** (see Pitfall 1).
- **Sorting the sweep by dict-insertion order.** D-10 requires an explicit `sorted(..., key=lambda o: o.id)` —
  do not rely on `_orders()` dict iteration order even though it happens to coincide.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Terminal transition of a resting order + reservation release | A new EXPIRE-specific transition/release path | The `cancel_order` template (local transition + idempotent `release()` + emit) | EXPIRED is a peer of CANCELLED — one retire-a-resting-order pattern, not two (D-08). |
| Clearing the exchange resting book | Direct `_resting` mutation | `OrderEvent(EXPIRE)` → `on_order` → `matching_engine.cancel()` | Cross-domain write must go through the queue. |
| Run-end resting detection | A custom "scan everything" loop | `get_active_orders(portfolio_id)` (is_active predicate) | The store already classifies active orders by predicate (D-20). |
| Returning-fill idempotency | A bespoke "already expired?" flag store | `VALID_ORDER_TRANSITIONS[EXPIRED] == []` + idempotent `release()` | The transition table + idempotent pop already give idempotency for free. |
| Reporting EXPIRED counts | A new summary line/metric | `count_orders_by_status` (status-name bucket) + `build_orders_snapshot` | EXPIRED is a status string that buckets automatically (D-12). |

**Key insight:** Every mechanic this phase needs already exists for the CANCELLED lifecycle. The work is to add a
parallel EXPIRED arm at each of the four seams (enum, sweep method, exchange arm, reconcile arm) — not to invent
new machinery.

## Runtime State Inventory

> This is a wiring/result-changing phase, not a rename — but it changes a committed run-end disposition, so the
> "what persists past the code change" question is the e2e golden artifacts.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — backtest uses in-memory order storage (`InMemoryOrderStorage`, flat dict); no DB persistence on the run path. Verified: `OrderStorageFactory` selects `in_memory` for backtest. | None |
| Live service config | None — this is the backtest path only; no external service. | None |
| OS-registered state | None. | None |
| Secrets/env vars | None. | None |
| Build artifacts / committed golden artifacts | **3 committed `golden/orders.csv` files carry a PENDING row that flips to EXPIRED**: `tests/e2e/matching/never_fill/golden/orders.csv`, `tests/e2e/sltp/from_decision_held/golden/orders.csv`, `tests/e2e/sltp/from_fill_held/golden/orders.csv`. Plus the docstring in `never_fill/scenario.py` explicitly asserts "there is no run-end expiry" (GAP #1) — it must be rewritten. The SMA_MACD integration oracle (`134/46189.87730727451`) does NOT change (equity-neutral, D-04). | Re-baseline the 3 golden orders.csv (PENDING→EXPIRED rows) under owner sign-off (D-11) via the harness `--freeze` discipline; rewrite the `never_fill` docstring; SMA_MACD oracle stays byte-exact (no re-freeze). |

## Common Pitfalls

### Pitfall 1: `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` is NOT fully unused after the dead-path removal
**What goes wrong:** D-03 / canonical-refs imply the `CREATE_ORDERS_FROM_SIGNAL` operation-type enum becomes unused
and can be removed "if unused after." It does NOT become unused. There are TWO distinct uses today, and only ONE is
on the dead path.
**Why it happens:** The grep surface conflates the dead `create_orders_from_signal` METHOD chain with the live
`_assemble_bracket_and_emit` error branch which independently tags its failure `OperationResult` with the SAME enum.
- DEAD (removed by D-03): `admission_manager.py:335` — the `create_orders_from_signal` method's exception handler.
- **LIVE (survives D-03):** `bracket_manager.py:220` — `_assemble_bracket_and_emit`'s exception handler. This method
  is called by BOTH the dead `create_orders_from_signal` (admission_manager.py:328) AND the live, validated
  `process_signal` path (admission_manager.py:249). So the enum is still referenced by the production signal→order path.
**How to avoid:** After removing the dead path, the plan must either (a) KEEP the `CREATE_ORDERS_FROM_SIGNAL` enum
member (simplest, value-inert, byte-safe — the live `bracket_manager.py:220` failure result keeps using it), OR
(b) retag the `bracket_manager.py:220` error result with a more accurate operation type (e.g. a new/existing bracket
operation type) — but that changes an `OperationResult.operation_type` value and must be checked against any test/audit
asserting on it. **Recommended: KEEP the enum member.** The CONTEXT.md "REMOVE if unused after" is conditional — and
research shows the condition is FALSE.
**Warning signs:** `grep -rn CREATE_ORDERS_FROM_SIGNAL itrader/` after removal still shows `bracket_manager.py` +
`core/enums/order.py`. mypy/import error if the enum member is deleted while `bracket_manager.py:220` still references it.

### Pitfall 2: `FillEvent.new_fill('EXPIRED', ...)` raises ValueError until `FillStatus.EXPIRED` exists
**What goes wrong:** `FillEvent.new_fill` does `FillStatus(status)` (fill.py:129). Emitting an EXPIRED fill before
adding the `FillStatus.EXPIRED` member raises `ValueError: Unknown FillStatus: 'EXPIRED'` via the enum `_missing_`.
**How to avoid:** Add `EXPIRED = "EXPIRED"` to `FillStatus` (core/enums/execution.py) BEFORE wiring the exchange
EXPIRE arm. Ordering within the phase matters: enums first, then the sweep/exchange/reconcile arms.
**Warning signs:** ValueError at the final-drain `on_order(EXPIRE)` step.

### Pitfall 3: The reconcile DEFENSIVE `else` raises `NotImplementedError` if `_classify` is updated without a matching arm
**What goes wrong:** `reconcile_manager.py:222-228` has a defensive `else: raise NotImplementedError('terminal fill
status ... has no reconcile arm')`. If you add `FillStatus.EXPIRED` to `_classify` (marking it terminal) but forget
the `elif fill_event.status == FillStatus.EXPIRED:` dispatch arm, this raises at run end — and because it raises
BEFORE `should_release` is armed, the reservation stays held (correct fail-loud behavior, but it aborts the run).
**How to avoid:** Add `_classify` mapping AND the matching `elif` dispatch arm in the SAME change.
**Warning signs:** `NotImplementedError: terminal fill status FillStatus.EXPIRED has no reconcile arm` at the final drain.

### Pitfall 4: Tab/space indentation across the touched files
**What goes wrong:** This phase touches BOTH tab files (`order_handler/`, `execution_handler/`, `trading_system/`)
AND space files (`core/enums/order.py`, `core/enums/execution.py` use 4 spaces). A mixed-indentation diff in a tab
file breaks it.
**How to avoid:** Match the file being edited. `lifecycle_manager.py`/`simulated.py`/`reconcile_manager.py`/
`backtest_runner.py` = TABS; `enums/order.py`/`enums/execution.py`/`fill.py` (events package) = 4 SPACES.
**Warning signs:** `mypy --strict` or pytest tokenizer errors; a visually-correct diff that fails to parse.

### Pitfall 5: The `never_fill` leaf docstring is now actively wrong
**What goes wrong:** `tests/e2e/matching/never_fill/scenario.py` docstring repeatedly states "there is no
``OrderStatus.ACTIVE`` and no run-end expiry on the backtest path" (GAP #1, lines 4-7, 42-47) and the VERIFY block
locks `status PENDING`. After this phase that order ends EXPIRED. Leaving the docstring asserts a now-false invariant.
**How to avoid:** Rewrite the docstring + VERIFY block AND re-freeze `golden/orders.csv` (PENDING→EXPIRED) under
owner sign-off. This leaf is a natural candidate to BECOME the D-05 positive-proof leaf (it already builds the exact
"far-from-market BUY-LIMIT that never fills" scenario D-05 describes) — or D-05 adds a dedicated new leaf and this
one is simply re-baselined.
**Warning signs:** e2e diff failure on `never_fill/golden/orders.csv` after wiring (expected — re-baseline it).

## Code Examples

### `expire_all_resting()` — peer of `cancel_order` (D-08, TABS)
```python
# Source: mirrors itrader/order_handler/lifecycle/lifecycle_manager.py:147-219
# Placement (Claude's discretion): OrderManager business method delegating to a
# LifecycleManager.expire_all_resting, OR an OrderManager method directly. Either
# returns OperationResults carrying OrderEvent(EXPIRE) — the HANDLER does the queue puts.
def expire_all_resting(self) -> list[OperationResult]:
    results: list[OperationResult] = []
    for portfolio in self.portfolio_handler.get_active_portfolios():        # deterministic order (D-10)
        for order in sorted(self.get_active_orders(portfolio.id),
                            key=lambda o: o.id):                            # UUIDv7 stable sort (D-10)
            if order.expire_order("run end (time-in-force)"):              # local -> EXPIRED
                self.order_storage.update_order(order)
                self._brackets.consume(order.id)                          # WR-03 symmetry (consider)
                self.portfolio_handler.release(portfolio.id, order.id)     # WR-04 idempotent
                order_event = OrderEvent.new_order_event(order, command=OrderCommand.EXPIRE)
                results.append(OperationResult.success_result(
                    f"Order {order.id} expired at run end",
                    order_events=[order_event], affected_order_ids=[order.id]))
    return results
```

### Runner invocation + final drain (D-08, TABS)
```python
# Source: itrader/trading_system/backtest_runner.py:95-108 — after the for-loop EXITS.
# (Exact placement is Claude's discretion: inside _run_backtest after the loop, or in
#  BacktestTradingSystem.run after runner.run(). The handler enqueues the OrderEvents,
#  then ONE final process_events() drains EXPIRE -> FillEvent(EXPIRED) -> reconcile.)
for time_event in engine.time_generator:
    ...  # unchanged per-tick loop
# run-end seam (after the loop):
results = engine.order_handler.expire_all_resting()   # handler delegates to manager + enqueues OrderEvent(EXPIRE)
engine.event_handler.process_events()                 # ONE final drain — provably non-cascading
```

### Reconcile EXPIRED arm (D-09, TABS, LANDMINE-safe)
```python
# Source: itrader/order_handler/reconcile/reconcile_manager.py — add to _classify + a named arm + dispatch.
@staticmethod
def _classify(status: FillStatus) -> "tuple[bool, Optional[OrderStatus]]":
    if status == FillStatus.EXECUTED:  return True, OrderStatus.FILLED
    if status == FillStatus.CANCELLED: return True, OrderStatus.CANCELLED
    if status == FillStatus.REFUSED:   return True, OrderStatus.REJECTED
    if status == FillStatus.EXPIRED:   return True, OrderStatus.EXPIRED   # ADD (peer to CANCELLED)
    return False, None

@staticmethod
def _apply_expired(order: "Order") -> None:
    """EXPIRED arm: mark the order EXPIRED. Idempotent on an already-EXPIRED mirror —
    expire_order routes through add_state_change, gated by VALID_ORDER_TRANSITIONS[EXPIRED] == []
    (an EXPIRED->EXPIRED transition is invalid -> add_state_change is a no-op, status stays EXPIRED)."""
    order.expire_order("exchange expiration")

# in on_fill dispatch (peer to the CANCELLED elif at line 218):
elif fill_event.status == FillStatus.EXPIRED:
    self._apply_expired(order)
```
**CONFIRMED (order.py:307-309):** `Order.add_state_change` returns `False` (does NOT raise) on a transition not in
`VALID_ORDER_TRANSITIONS`, so `_apply_expired` is idempotent on an already-EXPIRED order with NO explicit guard
needed. (The release in `_release_reservation` is independently idempotent — a second `release()` pops nothing.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Resting orders linger PENDING at run end (GAP #1) | Run-end sweep → EXPIRED (this phase) | Phase 6 (v1.3) | Honest terminal status; matches Lean/nautilus lifecycle modeling (vs backtesting.py/backtrader which silently drop). |
| Two signal→order paths (`on_signal`/`process_signal` validated + `create_order`/`create_orders_from_signal` unvalidated) | ONE validated path | Phase 6 D-03 | Removes the unvalidated risk surface; live `TradingInterface` builds `OrderEvent` directly (unaffected). |

**Deprecated/outdated by this phase:**
- The `never_fill` leaf's "no run-end expiry / GAP #1" docstring assertion — becomes false.
- `OrderHandler.create_order` + `AdmissionManager.create_orders_from_signal` + the unvalidated branch in
  `OrderManager` — removed (D-03). `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` enum member is KEPT (Pitfall 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ~~`Order.add_state_change` returns `False` (not raises) on an invalid transition~~ **RESOLVED — CONFIRMED in-code (order.py:307-309): returns `False`, no raise.** The reconcile EXPIRED arm is idempotent with no guard. | Pitfall 3 / Code Examples | None — verified this session. Moved off the assumptions list. |
| A2 | In the SMA_MACD oracle run, the orders left resting at run end are SL/TP brackets on still-open positions (D-02 bracket case) and/or unfilled standalone entries — all equity-neutral. | D-04 attribution | The equity-neutrality proof (A-confirmed via cash/equity tracing) holds REGARDLESS of WHICH orders expire, so the byte-exact conclusion is robust. The exact COUNT/identity of expired orders should still be MEASURED during execution (add a `count_orders_by_status` readout before/after the sweep) for the owner attribution report. LOW risk. |
| A3 | The 3 PENDING golden orders.csv leaves are the COMPLETE D-11 blast radius (no leaf asserts a PENDING order via a non-orders.csv golden). | D-11 / Summary | grep over `golden/` confirmed only 3 files carry `,PENDING,`; other goldens (trades/equity/summary) are status-blind. The full e2e run during execution is the authoritative confirmation (D-11 measure step). LOW risk. |

## Open Questions

1. **~~Does `Order.add_state_change` raise or return-False on an invalid transition?~~ RESOLVED.**
   - CONFIRMED in-code (order.py:307-309): `if not self._is_valid_transition(self.status, new_status): return False`.
     It returns `False`, never raises. The reconcile EXPIRED arm (`_apply_expired`) is idempotent on an already-EXPIRED
     mirror with NO explicit terminal guard. No action needed.

2. **Should `expire_all_resting` mirror `cancel_order`'s `self._brackets.consume(order.id)`?**
   - What we know: cancel does it (WR-03 part 1) to disarm a PercentFromFill pending entry that hasn't fired.
   - What's unclear: whether any resting order at run-end still has a live (unconsumed) PercentFromFill pending
     entry — by run end, primaries that were going to fill have filled and consumed their pending.
   - Recommendation: Mirror the `consume` for symmetry/safety (it no-ops when nothing is pending). Claude's discretion (D-08).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python / Poetry `.venv` | All execution | ✓ (project standard) | 3.13.1 | — |
| `pytest` | unit + e2e + integration suites | ✓ | ^8.4.2 | — |
| `mypy --strict` | gate | ✓ | ^2.1.0 | — |
| backtesting.py / backtrader | NOT needed this phase (D-07) | ✓ (installed) | — | N/A — no new external cross-val |

**Missing dependencies with no fallback:** None — entirely internal wiring.
**Missing dependencies with fallback:** None.

## Validation Architecture

> nyquist_validation: treated as ENABLED (config key absent — default enabled).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/order tests/unit/execution -x` |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| LIFE-01 (disposition) | Run-end resting order → EXPIRED, nothing stuck PENDING | e2e | `poetry run pytest tests/e2e/matching/never_fill -m e2e` (re-baselined to EXPIRED) + a NEW D-05 crafted leaf | ⚠️ never_fill EXISTS (re-baseline); D-05 leaf ❌ Wave 0 |
| LIFE-01 (bracket disposition, D-02) | SL+TP brackets on still-open position → EXPIRED, position stays open | e2e | `poetry run pytest tests/e2e/sltp/from_decision_held tests/e2e/sltp/from_fill_held -m e2e` (re-baselined) | ⚠️ EXIST (re-baseline goldens) |
| LIFE-01 (sweep logic) | `expire_all_resting` local transition + idempotent release + emit, deterministic order (D-10) | unit | `poetry run pytest tests/unit/order/ -k "expire" -x` | ❌ Wave 0 (new `test_expire_all_resting`) |
| LIFE-01 (reconcile EXPIRED arm + idempotency, D-09 LANDMINE) | `FillEvent(EXPIRED)` reconciles to EXPIRED mirror; returning fill on already-EXPIRED order is a no-op (no transition, no double-release) | unit | `poetry run pytest tests/unit/order/ -k "reconcile and expir" -x` | ❌ Wave 0 (extend reconcile branch-coverage tests) |
| LIFE-01 (exchange EXPIRE arm) | `OrderCommand.EXPIRE` removes resting + emits `FillEvent(EXPIRED)`; no spurious fill for non-resting order | unit | `poetry run pytest tests/unit/execution/ -k "expire" -x` | ❌ Wave 0 |
| LIFE-01 (non-cascade, D-08) | Final drain after sweep emits no SIGNAL/new ORDER | unit/integration | assert queue has no SignalEvent/new OrderEvent(NEW) after drain | ❌ Wave 0 |
| LIFE-01 (equity-neutrality, D-04) | SMA_MACD oracle `134 / 46189.87730727451` byte-exact after wiring | integration | `make test-integration` (oracle test) | ✅ EXISTS — must stay byte-exact |
| LIFE-01 (determinism, D-06) | Double-run byte-identical | integration | existing determinism double-run gate | ✅ EXISTS |
| LIFE-01 (dead-path removal, D-03) | `create_order`/`create_orders_from_signal` gone; `mypy --strict` clean; enum still resolves (Pitfall 1) | static + unit | `poetry run mypy itrader` + full suite | ✅ gate EXISTS |
| LIFE-01 (D-12 reporting) | EXPIRED appears in `count_orders_by_status` / `build_orders_snapshot` for free | unit | `poetry run pytest tests/unit/order/ -k "count_orders_by_status" -x` | ⚠️ extend existing |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/order tests/unit/execution -x` (sweep, exchange, reconcile arms)
- **Per wave merge:** `make test` (full unit + integration + e2e)
- **Phase gate:** SMA_MACD oracle byte-exact (`134/46189.87730727451`) + e2e all green (3 leaves re-baselined,
  rest unchanged) + `mypy --strict` clean + determinism double-run identical + owner sign-off on the attribution report.

### Wave 0 Gaps
- [ ] `tests/unit/order/test_expire_all_resting.py` (or extend `test_lifecycle_manager.py`) — sweep order (D-10),
      local transition, idempotent release, OrderEvent(EXPIRE) emission — covers LIFE-01 sweep.
- [ ] Extend `tests/unit/order/` reconcile branch-coverage with the EXPIRED arm + the idempotent-already-EXPIRED
      case (D-09 LANDMINE) — covers LIFE-01 reconcile.
- [ ] `tests/unit/execution/` EXPIRE-command arm test (remove resting + emit EXPIRED; no spurious fill) — covers exchange arm.
- [ ] NEW e2e leaf for D-05 (crafted far-from-market resting order ending EXPIRED) — OR re-purpose `never_fill`.
      *(`never_fill` already builds the exact scenario; it is the cheapest D-05 vehicle.)*
- [ ] Non-cascade assertion (D-08) — verify the post-sweep drain emits no SIGNAL/new ORDER.
- [ ] Re-baseline goldens (3 e2e leaves) — execution-time, under owner sign-off, via `--freeze` discipline.

## Security Domain

> `security_enforcement`: not configured for this project; this is a backtest-only, no-network, no-input-boundary
> internal wiring change with no auth/session/crypto/external-input surface. No ASVS category applies.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | no | No new external input; EXPIRE is engine-internal. The dead-path removal NARROWS the unvalidated surface (D-03). |
| V6 Cryptography | no | UUIDv7 IDs unchanged (single existing scheme). |

**Threat-model note (non-ASVS, project-internal):** the only "integrity" surface is the FRAGILE reconcile path
(D-09). The mitigation is the byte-exact oracle gate + determinism double-run + the idempotent-release invariant
holding for the new EXPIRED arm exactly as it does for CANCELLED/REFUSED — verified by the Validation Architecture above.

## Sources

### Primary (HIGH confidence — direct code reads this session)
- `itrader/core/enums/order.py:33-111` — `OrderStatus.EXPIRED`, `VALID_ORDER_TRANSITIONS` (EXPIRED terminal `[]`),
  `OrderCommand` (NEW/CANCEL/MODIFY — add EXPIRE), `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL`.
- `itrader/core/enums/execution.py:59-89` — `FillStatus` (EXECUTED/REFUSED/CANCELLED — add EXPIRED).
- `itrader/order_handler/order.py:120-149, 435-449` — `is_active`/`is_terminal` properties, `expire_order()`, `id=OrderId(uuid7)`.
- `itrader/order_handler/lifecycle/lifecycle_manager.py:147-219` — `cancel_order` template.
- `itrader/order_handler/reconcile/reconcile_manager.py:87-231` — `_classify` + per-status arms + try/finally release.
- `itrader/execution_handler/exchanges/simulated.py:259-294` — `on_order` CANCEL/MODIFY/NEW arms.
- `itrader/execution_handler/matching_engine.py:92-129` — `submit`/`cancel`/`has_order`.
- `itrader/events_handler/full_event_handler.py:68-87` — `routes` (ORDER→on_order only; FILL→portfolio+reconcile only) = NON-CASCADE PROOF.
- `itrader/events_handler/events/fill.py:77-136` — `new_fill(status: str)` → `FillStatus(status)`.
- `itrader/portfolio_handler/portfolio.py:199-235` — `cash` = `cash_manager.balance`; `total_equity = total_market_value + cash`.
- `itrader/portfolio_handler/portfolio_handler.py:230-281` — `available_cash` (balance−reserved), `release()` (pop only), `total_equity` (full balance) = EQUITY-NEUTRALITY PROOF.
- `itrader/portfolio_handler/cash/cash_manager.py:101-114, 418-448` — `available_balance = balance − reserved`; `release_reservation` pops reservation, leaves `_balance` untouched.
- `itrader/portfolio_handler/metrics/metrics_manager.py:128-200, 495-499` — snapshots read `portfolio.total_equity`/`cash` (balance-based, reservation-blind).
- `itrader/order_handler/storage/in_memory_storage.py:42-183` — `get_active_orders`/`get_orders_by_status`/`count_orders_by_status` (D-10/D-12).
- `itrader/order_handler/order_handler.py:215-245` + `admission/admission_manager.py:286-335` + `brackets/bracket_manager.py:205-221` — dead `create_order` path + the LIVE enum re-use (Pitfall 1).
- `itrader/trading_system/backtest_runner.py:83-117` — `_run_backtest` for-loop + post-loop seam + `on_tick` precedent.
- `tests/e2e/conftest.py:1-60, 85-87, 140-366` — harness build→run→assemble→diff, `build_orders_snapshot`, `--freeze`.
- `tests/e2e/matching/never_fill/scenario.py` + `golden/orders.csv`; `tests/e2e/sltp/from_decision_held` + `from_fill_held` goldens — D-11 blast radius.
- grep (this session): `0` `.create_order(` callsites; `0` test references to the dead path; `3` `,PENDING,` golden orders.csv.

### Secondary (MEDIUM)
- `.planning/STATE.md` §Milestone Gate (v1.3) — owner-gated re-baseline discipline.
- `.planning/ROADMAP.md` §Phase 6 — 4 success criteria.

### Tertiary (LOW)
- None — all claims traced to code or planning artifacts.

## Metadata

**Confidence breakdown:**
- Standard stack (existing surface): HIGH — every member/method read in-file this session.
- Architecture (Option A mapping): HIGH — all four seams have an existing CANCELLED-lifecycle template traced.
- D-04 equity-neutrality: HIGH — proven by the cash→equity read-path trace (release pops reservation, equity reads full balance).
- D-08 non-cascade: HIGH — proven by the `routes` literal (ORDER→on_order only, FILL→reconcile only).
- D-11 blast radius: HIGH — exact 3-leaf grep; full e2e run at execution is the authoritative confirmation.
- Pitfalls 1-3: HIGH — all grep/code-confirmed.
- A1 (add_state_change return-False on invalid transition): HIGH — CONFIRMED in-code this session (order.py:307-309).

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (stable internal surface; no fast-moving external dependency)
