# Phase 6: Order Lifecycle & Time-in-Force - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 6-order-lifecycle-time-in-force
**Areas discussed:** TIF scope, create_order gating, Re-baseline posture, Cross-validation depth, Wiring mechanism, Sweep determinism, EXPIRE vs CANCEL seam, E2E leaf impact, Reporting surface

---

## TIF scope — deliverable size

| Option | Description | Selected |
|--------|-------------|----------|
| Run-end sweep only | Wire ONLY run-end disposition; no per-order TIF field/enum; one implicit GTC-until-run-end semantic | ✓ |
| Run-end sweep + TIF field scaffold | Add a `time_in_force` enum/field (default GTC) even if only GTC exercised | |
| Full per-order TIF semantics | DAY/GTD/IOC/FOK with session/calendar concepts | |

**User's choice:** Run-end sweep only.
**Notes:** Matches the 4 success criteria exactly; real TIF model deferred to N+4. Framework-aligned (honest-terminal version of what backtesting.py/backtrader do by dropping unfilled orders).

## TIF scope — which orders expire

| Option | Description | Selected |
|--------|-------------|----------|
| All resting orders | Unfilled entries AND protective SL/TP brackets on open positions → EXPIRED | ✓ |
| Standalone entries only | Expire only never-filled entries; leave brackets resting | |

**User's choice:** All resting orders.
**Notes:** User first asked what other frameworks do with open orders vs positions at backtest end. Established the orders-vs-positions split: frameworks mark open POSITIONS to market (don't liquidate); unfilled ORDERS are dropped (simple engines) or given a terminal EXPIRED/Cancelled (Lean/nautilus). We dispose only ORDERS; positions stay open + marked-to-last-close. Within orders, expire ALL (brackets can never trigger — no more data — so EXPIRED is honest; satisfies criterion 1 literally).

---

## create_order gating (W4-09)

| Option | Description | Selected |
|--------|-------------|----------|
| Remove it | Delete create_order + create_orders_from_signal (zero callers) | ✓ |
| Route through validation | Keep create_order but delegate to the validated process_signal path | |
| Document and keep as-is | Leave both paths; document the unvalidated entry point (W4-04 precedent) | |

**User's choice:** Remove it.
**Notes:** Scouting confirmed zero callers anywhere (live TradingInterface builds OrderEvents directly; run loop uses only on_signal). Soften the W4-04 validator-overlap doc to drop the `create_order` clause while keeping the live-path justification (defense-in-depth survives via the live OrderEvent path).

---

## Re-baseline posture

| Option | Description | Selected |
|--------|-------------|----------|
| Hold byte-exact + crafted scenario | Keep SMAMACD oracle byte-exact (Phase 5 D-B); prove EXPIRED on a crafted scenario | |
| Re-baseline SMAMACD itself | Accept that wiring EXPIRED may shift SMAMACD and freeze a new golden | |
| Decide after measurement | Measure whether SMAMACD's end-of-run resting orders move any metric, then pick | ✓ |

**User's choice:** Decide after measurement.
**Notes:** Captured as measure-first: research/execution attributes which orders expire + any trade_count/final_equity/reservation delta BEFORE fixing posture. Working hypothesis (not guaranteed): metric-neutral / oracle-dark → SMAMACD stays byte-exact. Fallback: re-baseline with attribution if it moves. Must verify reservation semantics (does release() feed total_equity or only available_cash). Crafted run-end-resting proof scenario still required regardless. Owner-gate applies to the outcome.

---

## Cross-validation depth

| Option | Description | Selected |
|--------|-------------|----------|
| Internal attribution + owner sign-off | No new backtesting.py/backtrader run; owner signs off on the attribution | ✓ |
| Full cross-val pass (Phase 5 D-07 style) | 3-engine cross-val of the EXPIRED scenario | |
| Reuse Phase 5 limit-entry golden | Lean on the prior cross-validated scenario + add the run-end EXPIRED assertion | |

**User's choice:** Internal attribution + owner sign-off.
**Notes:** Oracles don't model EXPIRED (they silently drop unfilled orders) — they can only confirm equity/trade neutrality the internal oracle already proves. Lighter than Phase 5 (which needed cross-val because LIMIT-fill PRICES were new economics; EXPIRED disposition is not).

---

## Wiring mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror the cancel path + final drain (Option A) | expire_all_resting() peer to cancel_order: local EXPIRED + WR-04 release + emit OrderEvent; runner invokes after loop + one final process_events() drain | ✓ |
| Direct finalization sweep (Option B) | Local EXPIRED + release only; skip the exchange round-trip and final drain | |

**User's choice:** Option A (locked after a dedicated confirm question).
**Notes:** User asked "architecturally, what's the most correct, cleanest, clearest option?" Reasoning given for A: (1) EXPIRED is a peer of CANCELLED → use the same machinery so there's ONE retire-a-resting-order pattern; (2) clearing `_resting` is a cross-domain write → goes through the queue (core law), keeping mirror + exchange book in agreement at every observable point; (3) "book is discarded anyway" doesn't preserve the invariant; (4) the final drain is the symmetric bookend of the per-tick cycle and is provably non-cascading (emits only OrderEvent→FillEvent, no signals/new orders); (5) clean layering — logic in OrderManager/LifecycleManager, orchestration in the runner (record_metrics precedent). Option B's only win is simplicity, bought by accepting a mirror-vs-exchange inconsistency + a duplicate retire pattern.

---

## Sweep determinism

| Option | Description | Selected |
|--------|-------------|----------|
| Portfolio order, then order_id | Existing deterministic portfolio order; within each, sort by order_id (UUIDv7) | ✓ |
| Global order_id only | Flatten all active orders, single global order_id sort | |
| Match existing storage iteration | Lean on get_active_orders' existing dict/insertion order | |

**User's choice:** Portfolio order, then order_id.
**Notes:** Reuses the same portfolio order get_active_portfolios() already yields for record_metrics; UUIDv7 gives a stable creation-time sort. Guarantees the owner-gate's determinism double-run byte-identical. Verify a per-portfolio active-order query + order_id sort exist on the in-memory store.

---

## EXPIRE vs CANCEL seam

| Option | Description | Selected |
|--------|-------------|----------|
| First-class EXPIRE end-to-end | OrderCommand.EXPIRE + FillStatus.EXPIRED + reconcile EXPIRED arm; exchange emits FillEvent(EXPIRED) | ✓ |
| EXPIRE command, no return fill | Add OrderCommand.EXPIRE but exchange clears _resting with no fill back | |
| Reuse CANCEL command | Send CANCEL; exchange emits CANCELLED; rely on idempotent terminal no-op | |

**User's choice:** First-class EXPIRE end-to-end.
**Notes:** Honest audit trail (exchange seam shows EXPIRED, not CANCELLED), symmetric with cancel, completes the lifecycle. Means Phase 6 DOES touch the FRAGILE reconcile path (small, well-scoped add fitting Phase 5's per-status-arm structure, under the owner-gate). LANDMINE flagged: the EXPIRED reconcile arm must be idempotent against the already-locally-EXPIRED mirror — must NOT attempt EXPIRED→EXPIRED/CANCELLED (VALID_ORDER_TRANSITIONS[EXPIRED]==[]).

---

## E2E leaf impact

| Option | Description | Selected |
|--------|-------------|----------|
| Measure, attribute, re-baseline only affected leaves | Run suite, identify drifted leaves, attribute + re-baseline only those | ✓ |
| Add explicit EXPIRED assertions to existing leaves | Proactively update resting-order leaves | |
| New dedicated TIF e2e leaf only | Leave existing leaves untouched; add one new TIF leaf | |

**User's choice:** Measure, attribute, re-baseline only affected leaves.
**Notes:** Same measure-first discipline as the SMAMACD posture. Untouched leaves stay green unchanged; affected leaves get a WHY-attribution in the phase summary. The crafted run-end-resting scenario (D-05) provides the positive proof leaf.

---

## Reporting surface

| Option | Description | Selected |
|--------|-------------|----------|
| Internal status only | EXPIRED flows through generic count_orders_by_status for free; no new artifact | ✓ |
| Add EXPIRED to run summary/order-log frames | Explicit "N orders expired" count in summary/frames | |
| You decide | Defer to research/planner | |

**User's choice:** Internal status only.
**Notes:** EXPIRED is observable via existing order-status APIs without new surface; reporting frames are oracle-dark. Keeps the phase tight.

---

## Claude's Discretion

- Exact method placement/names for `expire_all_resting()` and its manager/lifecycle split (peer of cancel_order).
- Exact shape of the reconcile EXPIRED arm + the already-terminal idempotency guard (subject to the LANDMINE).
- Exact crafted-scenario parameters (offset, cadence, bar) for the run-end-resting proof.
- Where the runner invokes expire_all_resting() + the final drain (inside _run_backtest vs BacktestTradingSystem.run).

## Deferred Ideas

- Per-order time-in-force model (GTC/DAY/GTD/IOC/FOK) → N+4 Live Trading Readiness.
- Liquidating/force-closing open positions at run end (we mark-to-close instead) — possible future reporting nicety, result-shaping, not wanted now.
- Per-venue order validation (Binance "stop would trigger immediately") → N+4 (carried from Phase 5).
- N+2 (margin/shorts/leverage/trailing) builds on this completed lifecycle surface.
