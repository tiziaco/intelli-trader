# Phase 6: Order Lifecycle & Time-in-Force - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

**LIFE-01 — wire run-end resting-order disposition on the backtest path and gate the
`create_order` second path (W4-09), under an owner-gated re-baseline.**

At run end, every order still resting transitions to `OrderStatus.EXPIRED` via
`Order.expire_order()` (which exists but is unwired) so **nothing lingers PENDING** after the
backtest for-loop completes. The unvalidated `create_order` → `create_orders_from_signal`
second path — confirmed to have **zero callers** anywhere — is **removed**. Result-changing
(owner-gated): the new golden disposition is frozen ONLY after explicit owner sign-off with
full attribution.

**KEY SCOUTING FINDINGS:**
- `Order.expire_order()` (`order.py:435`) + `OrderStatus.EXPIRED` + `VALID_ORDER_TRANSITIONS`
  (`enums/order.py:78,83`, EXPIRED is terminal: `[]`) all EXIST; nothing calls `expire_order()`.
- Resting orders live in `MatchingEngine._resting` (one per `SimulatedExchange`); the order
  mirror sits PENDING in `OrderManager` storage. The run-end seam is immediately AFTER the
  `_run_backtest` for-loop completes (`backtest_runner.py:95-108`).
- `OrderHandler.create_order` → `AdmissionManager.create_orders_from_signal` has **NO callers**
  in `itrader/`, `tests/`, or `scripts/`. Live `TradingInterface` builds `OrderEvent`s directly;
  the run loop uses only `on_signal`. The "second path" is dead code.
- **No `time_in_force` field exists anywhere today** — this phase introduces run-end disposition
  semantics ONLY, not a per-order TIF model.
- The **cancel path is the proven template**: `LifecycleManager.cancel_order` does a local
  mirror transition + local idempotent reservation `release()` (WR-04) **and** emits
  `OrderEvent(CANCEL)`; the exchange removes the resting order and emits `FillEvent(CANCELLED)`,
  which reconcile treats as an idempotent re-release no-op.

**What "time-in-force" means HERE:** a single implicit *GTC-until-run-end* semantic, enacted as
a run-end sweep. NOT a per-order TIF field/enum, NOT DAY/GTD/IOC/FOK.

**Explicitly NOT in this phase:**
- **Per-order TIF field/enum** (GTC/DAY/GTD/IOC/FOK) → deferred to live-readiness (N+4).
- **Liquidating / force-closing open POSITIONS at run end** → positions stay open and
  marked-to-last-close (existing behavior, unchanged). Only resting ORDERS are disposed.
- **New external backtesting.py/backtrader cross-validation** → not required (oracles don't
  model EXPIRED; see D-07).

</domain>

<decisions>
## Implementation Decisions

### TIF scope (Area 1)
- **D-01 — Run-end sweep only.** Wire ONLY run-end disposition: at run end every resting order
  → `EXPIRED` via `expire_order()`. **No** per-order `time_in_force` field, **no** GTC/DAY/GTD
  enum, **no** session/calendar concepts. One implicit "GTC-until-run-end" semantic. Matches the
  four ROADMAP success criteria exactly; a real TIF model is deferred to N+4. Framework-aligned:
  simple engines (backtesting.py/backtrader) silently drop unfilled orders; lifecycle-modeling
  engines (Lean/nautilus) give them a terminal EXPIRED — we do the honest-terminal version.
- **D-02 — Expire ALL resting orders.** Every order still resting → EXPIRED: unfilled standalone
  entry limit/stop orders AND the protective SL/TP brackets on still-open positions (they can
  never trigger — no more data — so EXPIRED is honest). Uniform, satisfies criterion 1 literally
  ("no order stuck PENDING"). **Positions are NOT liquidated** — they stay open and are
  marked-to-last-close for final equity exactly as today (matches backtrader/Lean/nautilus).

### create_order gating — W4-09 (Area 2)
- **D-03 — Remove the dead second path.** Delete `OrderHandler.create_order` +
  `AdmissionManager.create_orders_from_signal` (and the now-unused `CREATE_ORDERS_FROM_SIGNAL`
  enum / result-type plumbing). Rationale: zero callers; `on_signal` → `process_signal` is the
  single validated path; removing the unvalidated path eliminates the risk surface entirely.
- **D-03a — Soften the validator-overlap doc.** The W4-04 dual-layer-validator justification in
  `CLAUDE.md` / `.planning/codebase/CONVENTIONS.md` cites "`create_order`/live paths bypass the
  domain validator." Drop the `create_order` clause; KEEP the justification — the live
  `TradingInterface` → `OrderEvent` → exchange path still bypasses the domain validator, so the
  defense-in-depth (W4-04 justified-by-decision) rationale survives intact. Do NOT remove the
  validator code.

### Re-baseline posture — owner-gated (Area 3)
- **D-04 — Measure-first posture (do NOT pre-commit byte-exact vs re-baseline).** Research/
  execution MUST first produce an attribution: which orders in the SMAMACD oracle run get
  expired, and whether that moves `trade_count` (134) or `final_equity` (46189.87730727451) or
  any reservation/equity figure. THEN the posture is chosen:
  - **Expected outcome (state as the working hypothesis, not a guarantee):** metric-neutral —
    an expired never-filled entry isn't a trade; expiring SL/TP brackets on an open position
    moves neither cash nor the marked position; the status-log change (PENDING→EXPIRED) is
    oracle-dark (the oracle asserts trades + equity, not order statuses). If so, SMAMACD stays
    **byte-exact** (mirrors Phase 5 D-B) and any drift is an unambiguous bug.
  - **Fallback:** if measurement shows real movement (e.g. reservation-release feeds
    `total_equity`), re-baseline SMAMACD with full attribution.
  - **VERIFY during research:** reservation semantics — does `release()` change the cash that
    `total_equity` reads, or only `available_cash`? This determines D-04's outcome.
  - The owner-gate applies to whichever outcome lands (owner signs off on the attribution).
- **D-05 — Crafted run-end-resting proof scenario.** Regardless of D-04's outcome for SMAMACD,
  prove the EXPIRED mechanic with a **crafted minimal deterministic scenario that provably
  leaves an order resting at run end** (e.g. a far-from-market buy-limit placed near the last
  bar that never fills). This is the positive-coverage proof; it doubles as the new dedicated
  e2e leaf (ties to D-09).
- **D-06 — Determinism still binds.** Determinism double-run byte-identical and `mypy --strict`
  clean hold regardless of posture.

### Cross-validation depth (Area 3 cont.)
- **D-07 — Internal attribution + owner sign-off; NO new external cross-val.** No new
  backtesting.py/backtrader run. Rationale: those engines don't model an EXPIRED state (they
  silently drop unfilled orders), so they can only confirm equity/trade neutrality — which the
  byte-exact measurement against our OWN oracle (D-04) already proves. Cross-val would add
  nothing. Lighter than Phase 5 (which needed cross-val because LIMIT-fill PRICES were genuinely
  new economics; EXPIRED disposition is not). Owner signs off on the attribution report.

### Wiring mechanism (Area 4) — **LOCKED Option A**
- **D-08 — `expire_all_resting()` as a peer to `cancel_order`.** New business-logic method in
  `OrderManager`/`LifecycleManager` (mirrors `cancel_order`): sweep `get_active_orders`, for each
  do a **local** EXPIRED transition + **local idempotent reservation release** (reuse the proven
  WR-04 release code), and emit an `OrderEvent` to clear the exchange book. Business logic lives
  in the manager; the **runner invokes it at the orchestration boundary** after the for-loop
  (same precedent as the existing direct `portfolio.record_metrics()` call), then runs **ONE
  final `event_handler.process_events()` drain** so the exchange clears `_resting` and the
  returning fills reconcile (idempotent). Architectural rationale (full reasoning in
  DISCUSSION-LOG):
  - EXPIRED is a *peer of CANCELLED* — same kind of terminal transition of a resting order with
    a reservation to release → use the SAME machinery so there is ONE retire-a-resting-order
    pattern, not two.
  - Clearing `MatchingEngine._resting` is a cross-domain WRITE → it goes through the queue (the
    project's core law), keeping the order mirror and the exchange book in agreement at every
    observable point (not just the ones we currently inspect).
  - The final drain is the symmetric bookend of the per-tick `put(); process_events()` cycle and
    is **provably non-cascading**: expiry emits only `OrderEvent(EXPIRE) → FillEvent`, routing to
    reconcile + `on_fill` — it generates NO signals and NO new orders.
- **D-09 — First-class EXPIRE seam.** Add `OrderCommand.EXPIRE` + `FillStatus.EXPIRED`; the
  exchange clears `_resting` and emits `FillEvent(EXPIRED)`; reconcile gets an **EXPIRED terminal
  arm** (peer to the CANCELLED arm — terminal, releases) that is **idempotent against the
  already-locally-EXPIRED mirror**. Honest audit trail (exchange seam shows EXPIRED, not a
  misleading CANCELLED), symmetric with cancel, completes the lifecycle. **This means Phase 6
  DOES touch the FRAGILE `reconcile/` path** — a small, well-scoped add that fits Phase 5's
  per-status-arm structure, under the owner-gate.
  - **LANDMINE (research/plan MUST address):** the mirror must end `EXPIRED` (criterion 1) and
    the returning `FillEvent(EXPIRED)` must NOT attempt an `EXPIRED → EXPIRED`/`EXPIRED →
    CANCELLED` transition — `VALID_ORDER_TRANSITIONS[EXPIRED] == []` (terminal). Reconcile's
    EXPIRED arm must be idempotent on an already-terminal order (no-op the status write, no-op
    the re-release), exactly as the cancel path handles "the later exchange CANCELLED fill
    re-releasing is a silent no-op" (`lifecycle_manager.py:189-194`).

### Sweep determinism (Area 5)
- **D-10 — Ordering contract: portfolio order, then `order_id`.** Iterate active portfolios in
  the engine's existing deterministic portfolio order (the same order `get_active_portfolios()`
  already yields for `record_metrics` each tick); within each portfolio, expire orders sorted by
  `order_id` (UUIDv7 — monotonic, creation-ordered → stable sort). Reuses an ordering the run
  already trusts; guarantees determinism double-run byte-identical (D-06). **VERIFY in research:**
  that a per-portfolio active-order query + a well-defined `order_id` sort are available on the
  in-memory store.

### E2E leaf impact (Area 6)
- **D-11 — Measure → attribute → re-baseline only affected leaves.** Run the full e2e suite
  (58 leaves) after wiring; identify exactly which leaves now end with EXPIRED orders / shifted
  assertions. For each affected leaf, attribute WHY (which resting orders expired) in the phase
  summary, and re-baseline ONLY those leaves' resting-order-disposition assertions under the
  owner-gate. Untouched leaves MUST stay green unchanged. Same measure-first discipline as D-04.
  The new crafted leaf (D-05) is the positive proof; this is the regression-attribution pass.

### Reporting surface (Area 7)
- **D-12 — Internal status only; no new reporting surface.** EXPIRED is a first-class order
  status in the mirror + reconcile and flows through generic status queries for free
  (`count_orders_by_status` already buckets by status name → EXPIRED appears automatically). Add
  NO new reporting artifact, summary line, or metric. Reporting frames are oracle-dark anyway.
  EXPIRED is observable via existing order-status APIs without widening the phase.

### Claude's Discretion
- Exact method placement/names for `expire_all_resting()` and its manager/lifecycle split
  (D-08), subject to "peer of `cancel_order`."
- Exact shape of the reconcile EXPIRED arm + the idempotency guard for already-terminal orders
  (D-09), subject to the LANDMINE.
- Exact crafted-scenario parameters (offset, cadence, which bar) for D-05, subject to "provably
  leaves an order resting at run end."
- Where the runner invokes `expire_all_resting()` + the final drain (inside `_run_backtest`
  after the loop vs `BacktestTradingSystem.run` after `runner.run()`), subject to D-08.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source / requirements / discipline
- `.planning/ROADMAP.md` §"Phase 6: Order Lifecycle & Time-in-Force" — goal + 4 success criteria
  (the pass/fail contract); §"Backlog 999.3 (N+4)" for the deferred per-order TIF / per-venue
  validation boundary; §"Backlog 999.4 (N+2)" for the surface this completes the lifecycle for.
- `.planning/REQUIREMENTS.md` §"Order Lifecycle (LIFE)" — LIFE-01 (authoritative); the
  owner-gated (result-changing) tag; the `create_order` second-path gating clause [999.5-(d),
  W4-09].
- `.planning/STATE.md` §"Milestone Gate (v1.3)" — the owner-gated re-baseline discipline (owner
  sign-off + attribution), `mypy --strict` + determinism double-run still bind; the
  byte-exact-vs-owner-gated separation rationale.
- `.planning/notes/v1.3-concerns-triage.md` — W4-09 (`create_order` gating → (d)),
  the `expire_order()`-never-called concern, 999.5-(d) scope.
- `.planning/phases/05-signal-contract-reconcile-fragile/05-CONTEXT.md` — the D-B re-baseline
  precedent (keep oracle byte-exact + prove the result-changing mechanic on a crafted owner-signed
  scenario) directly reused here as D-04/D-05; the RECON-01 reconcile streamline this phase extends.

### Run-end seam + lifecycle wiring (Option A surfaces)
- `itrader/trading_system/backtest_runner.py:83-116` — `_run_backtest` for-loop + `run`; the
  run-end seam (after the loop) where `expire_all_resting()` + the final `process_events()` drain
  are invoked (D-08). Note the existing direct `portfolio.record_metrics()` orchestration-layer
  precedent (line 102).
- `itrader/order_handler/lifecycle/lifecycle_manager.py:147-219` — `cancel_order` (the proven
  template for `expire_all_resting()`): local terminal transition + local idempotent
  `portfolio_handler.release()` (WR-04, lines 189-196) + `OrderEvent(CANCEL)` emit. Mirror this
  for EXPIRE (D-08).
- `itrader/order_handler/order_manager.py:215-234` — `cancel_order` delegation + `get_active_orders`
  / `get_orders_by_status` read APIs the sweep uses (D-08/D-10).
- `itrader/order_handler/order.py:435-449` — `Order.expire_order()` (exists, unwired) →
  `add_state_change(OrderStatus.EXPIRED, ...)`; `is_terminal()` (line 133) includes EXPIRED.
- `itrader/core/enums/order.py:47,72,76-83` — `OrderStatus.EXPIRED`, `order_status_map`,
  `VALID_ORDER_TRANSITIONS` (PENDING→EXPIRED allowed; EXPIRED terminal `[]`). `OrderCommand`
  (line ~90, NEW/CANCEL/MODIFY) → add `EXPIRE` (D-09).

### FRAGILE reconcile / exchange seam (touch once, owner-gated, D-09)
- `itrader/order_handler/reconcile/reconcile_manager.py:86-234` — `_classify` + per-status arms
  (EXECUTED/CANCELLED/REFUSED) + `try`/`finally` release-in-finally (WR-03/WR-04/T-05-17). Add the
  EXPIRED arm here (peer to CANCELLED, line 108-109); keep the exception-safety skeleton
  byte-identical (the Phase 5 D-06 discipline).
- `itrader/execution_handler/exchanges/simulated.py:252-282` — `on_order` CANCEL handling
  (remove resting, emit FILL(CANCELLED)); add the parallel EXPIRE arm (remove resting, emit
  FILL(EXPIRED), D-09).
- `itrader/execution_handler/matching_engine.py:88-133` — `_resting` book + `add`/`remove`/`has`
  accessors the EXPIRE command clears.
- `FillStatus` enum (execution enums) — add `EXPIRED` (D-09). Confirm home in
  `itrader/core/enums/execution.py`.

### Dead-path removal (D-03)
- `itrader/order_handler/order_handler.py:215-245` — `create_order` (REMOVE).
- `itrader/order_handler/order_manager.py:206-208` — `create_orders_from_signal` delegation (REMOVE).
- `itrader/order_handler/admission/admission_manager.py:286-336` — `create_orders_from_signal`
  (REMOVE); `core/enums/order.py:124` `CREATE_ORDERS_FROM_SIGNAL` operation-type (REMOVE if unused
  after).
- `CLAUDE.md` §Conventions + `.planning/codebase/CONVENTIONS.md` — W4-04 validator-overlap doc:
  drop the `create_order` clause, keep the live-path justification (D-03a).

### Conventions (must match)
- `CLAUDE.md` + `.planning/codebase/CONVENTIONS.md` — **tabs** in `order_handler/`,
  `execution_handler/`, `trading_system/` (this phase's modules); **4 spaces** in `core/`
  (`enums/`); Decimal money via `to_money` (never `Decimal(float)`); the broad-`except` run-mode
  policy; the W4-04 dual-layer validator justified-by-decision.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`LifecycleManager.cancel_order`** (`lifecycle_manager.py:147-219`) — the exact template for
  `expire_all_resting()`: local transition + local idempotent `release()` + `OrderEvent` emit.
- **`Order.expire_order()`** (`order.py:435`) — already implemented; the sweep just needs to call
  it. `OrderStatus.EXPIRED` + `VALID_ORDER_TRANSITIONS` + `is_terminal()` already EXPIRED-aware.
- **`get_active_orders` / `get_orders_by_status`** (`order_manager.py:228-234`) — the read APIs
  the sweep iterates (D-10).
- **`SimulatedExchange.on_order` CANCEL arm** (`simulated.py:274-282`) — parallel template for the
  EXPIRE arm (remove resting + emit fill).
- **Reconcile per-status arm structure** (Phase 5 D-06, `reconcile_manager.py`) — the EXPIRED arm
  slots into the existing `_classify` + named-arm shape.
- **`record_metrics` orchestration-layer call** (`backtest_runner.py:102`) — precedent for the
  runner directly invoking domain work at the run boundary (D-08).

### Established Patterns
- **Cancel = local-transition-+-release-+-emit hybrid** — local mirror/release is the WR-04
  belt-and-suspenders; the `OrderEvent` clears the exchange book; the returning fill is an
  idempotent no-op. EXPIRE mirrors this exactly (D-08/D-09).
- **Terminal release in `finally`, idempotent** (WR-03/WR-04/T-05-17) — the invariant the EXPIRED
  reconcile arm must preserve.
- **Per-tick `put(); process_events()`** — the run loop's core cycle; the final drain is its
  shutdown bookend (D-08).
- **SignalRecord / reporting frames are oracle-dark** — status changes don't affect the oracle
  number (grounds D-04's neutrality hypothesis and D-12).
- **Single-writer backtest contract** — no concurrent mutation; the sweep runs once, after the
  loop, single-threaded.

### Integration Points
- Run-end seam: `_run_backtest` loop end → `OrderManager.expire_all_resting()` →
  `OrderEvent(EXPIRE)` → `ExecutionHandler.on_order` → `SimulatedExchange` clears `_resting` +
  `FillEvent(EXPIRED)` → `ReconcileManager.on_fill` (EXPIRED arm, idempotent) → final
  `process_events()` drain.
- Reservation release: `LifecycleManager`/`expire_all_resting` → `portfolio_handler.release()`
  (read-model seam) — same path cancel uses.

</code_context>

<specifics>
## Specific Ideas

- `expire_all_resting()` target shape (D-08), mirroring `cancel_order`:
  ```python
  def expire_all_resting(self) -> list[OperationResult]:
      results = []
      for portfolio in self.portfolio_handler.get_active_portfolios():     # deterministic order
          for order in sorted(self.get_active_orders(portfolio.id),
                              key=lambda o: o.id):                          # UUIDv7 stable sort
              order.expire_order(reason="run end (time-in-force)")          # local -> EXPIRED
              self.portfolio_handler.release(portfolio.id, order.id)        # idempotent WR-04
              results.append(... OrderEvent(order, command=OrderCommand.EXPIRE) ...)
      return results
  # runner: after the for-loop -> handler puts the events -> ONE final process_events() drain
  ```
- Crafted proof scenario (D-05), illustrative: place a far-below-market `buy_limit` (e.g.
  `close * 0.50`) on the penultimate/last bar so it provably never fills; assert it ends EXPIRED
  (not PENDING) and the position/cash are untouched.
- Reconcile EXPIRED arm (D-09), peer to the CANCELLED arm:
  ```python
  if status == FillStatus.EXPIRED:
      return True, OrderStatus.EXPIRED   # terminal, arms should_release
  # ...and guard: if order.is_terminal() already EXPIRED -> idempotent no-op (no transition, no re-release)
  ```

</specifics>

<deferred>
## Deferred Ideas

- **Per-order time-in-force model (GTC/DAY/GTD/IOC/FOK) → N+4 Live Trading Readiness.** Needs a
  TIF field + a TIF clock; DAY/GTD need session/calendar concepts crypto-first deliberately
  defers. This phase ships only the implicit GTC-until-run-end run-end sweep.
- **Liquidating/force-closing open positions at run end** — out of scope; we mark-to-close like
  backtrader/Lean/nautilus. A force-close-at-last-bar option (backtesting.py-style trade-log
  realization) could be a future reporting nicety but is result-shaping and not wanted now.
- **Per-venue order validation (Binance "stop would trigger immediately") → N+4** — carried from
  Phase 5; per-venue LIVE concern.
- **N+2 (margin/shorts/leverage/trailing) builds on this completed lifecycle surface** — the
  run-end EXPIRED disposition is part of the order-lifecycle contract N+2's stateful resting-order
  changes extend.

### Reviewed Todos (not folded)
None — no pending todos matched this phase (`todo.match-phase 6` → 0 matches).

</deferred>

---

*Phase: 6-order-lifecycle-time-in-force*
*Context gathered: 2026-06-13*
