# Phase 2: Event Bus - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 2-Event Bus
**Areas discussed:** compose_engine signature, EngineContext skeleton fields, Bus reach / blast radius, PriorityEventBus wiring boundary

---

## compose_engine signature (BUS-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Prepend ctx, keep kwargs | `compose_engine(ctx, *, <8 existing kwargs>)`; factory injects FifoEventBus + minimal ctx; smallest oracle-path diff; kwargs→spec fold deferred | |
| Go straight to `(ctx, spec)` | Fold the 8 kwargs into SystemSpec now → end-state two-arg signature; bigger backtest-wiring rewrite | ✓ |
| Defer ctx to P3 | compose_engine builds FifoEventBus() itself; no ctx param; signature edited twice (the trap BUS-04 names) | |

**User's choice:** Go straight to `(ctx, spec)` (Option B).
**Notes:** After seeing examples for all three and the recommendation (A), the owner deliberately chose the end-state signature to settle it once. Follow-up fork surfaced (storage placement) — see below.

### Sub-decision: storage placement under `(ctx, spec)`

| Option | Description | Selected |
|--------|-------------|----------|
| B1 — storage-in-handler now | Handlers own storage init from (environment, sql_engine); compose reads `.storage` back. Cleanest (ctx, spec); pulls CTX-02 into P2. | ✓ |
| B2 — storages onto SystemSpec | Backend instances become SystemSpec fields; pollutes the declarative spec | |
| B3 — hybrid (ctx, spec, *kwargs) | Storages stay injected kwargs; not the clean two-arg form; P3 double-edit returns | |
| Reconsider — back to Option A | Revert to prepend-ctx if the consequence changes the call | |

**User's choice:** B1 — handlers own their storage (the owner recognized this is exactly spec §7b / LR-13, and that `PortfolioHandler` already works this way).
**Notes:** Owner asked "can't they live in the class itself — isn't that what the spec defined?" Confirmed yes. Consequence accepted: **P2 absorbs CTX-01 + CTX-02** (scheduled P3), P3 shrinks to the SqlEngine rename + lazy-guard. Low-risk because the backtest slice is in-memory + PortfolioHandler is the template; heavy SQL/migrations stay in P3/P4. Traceability update flagged.

---

## EngineContext skeleton fields

| Option | Description | Selected |
|--------|-------------|----------|
| Include all 4 now (loose type) | bus + config + environment + sql_engine, placeholder types for RuntimeConfig/SqlEngine; P3/P4/P9 only tighten types | ✓ |
| Defer config (bus/env/sql_engine only) | Ship 3 fields; add config in P9; frozen dataclass gains a field later | |

**User's choice:** Include all 4 now, loose types.
**Notes:** Consistent with choosing B to settle the shape once. bus/environment/sql_engine are actively consumed in P2 (storage-in-handler); config is carried but unread until P9.

---

## Bus reach / blast radius

| Option | Description | Selected |
|--------|-------------|----------|
| Full swap now | Every handler ctor receives the FifoEventBus (retyped `global_queue`, no .put call-site changes); EventHandler drains via bus.get_nowait(); byte-identical FIFO → oracle safe | ✓ |
| Boundary-only | Handlers keep raw queue.Queue; bus wraps only at compose/drain edge; throwaway seam given the compose rewrite | |

**User's choice:** Full swap now.
**Notes:** Coherent with the committed `(ctx, spec)` + handler-owned-storage rewrite. Ctor param name stays `global_queue`/`events_queue` (CLAUDE.md convention), retyped to EventBus.

---

## PriorityEventBus wiring boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Define + unit-test only | Ship PriorityEventBus + (tier,seq,event) ordering test + 3 CONTROL EventTypes + _CONTROL_EVENT_TYPES; ZERO live wiring; live_trading_system.py untouched until P6/P7 | ✓ |
| Also wire live in P2 | Replace the live system's raw queue with PriorityEventBus now; pulls P6/P7 work into a foundation phase | |

**User's choice:** Define + unit-test only (Option 1).
**Notes:** Owner initially leaned Option 2, asked for a recommendation. Recommended Option 1: the 3 new CONTROL events have no producers/consumers until P6/P7/P8; the one existing CONTROL event (STRATEGY_COMMAND) would silently change validated v1.7 live ordering with no live-smoke gate until P12; the live drain loop is deleted/rewritten by LiveRunner in P6/P7 anyway, so Option 2 saves no work and creates a half-migrated intermediate. Owner accepted Option 1. Optional standalone integration test (no live touch) offered as the better integration-confidence buy.

---

## Claude's Discretion

- `EngineContext` class home/module (avoid an import cycle with `EventBus`).
- `FifoEventBus.depth_by_tier` exact shape (single-bucket, tierless).
- Whether to add the optional standalone PriorityEventBus CONTROL+BUSINESS interleaving integration test.
- `order_config` home under the kwargs→spec fold (leaned handler-owned per P1 D-03).

## Deferred Ideas

- REQUIREMENTS.md / ROADMAP.md traceability update — CTX-01/CTX-02 → P2; P3 shrinks to CTX-03/CTX-04.
- Wiring PriorityEventBus into live — P6/P7.
- RuntimeConfig overlay — P9 (EngineContext.config placeholder until then).
- SqlBackend→SqlEngine rename + migrations relocation — P3/P4 (EngineContext.sql_engine loose-typed until then).
- order_config onto SystemSpec — only if the planner rejects the handler-owned lean.
