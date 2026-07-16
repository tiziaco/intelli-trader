# Phase 9: Runtime-Config Platform ★ - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 9-Runtime-Config Platform
**Areas discussed:** Overlay mechanics (+ config-hierarchy restructure), Allowlist & validation, Stats/state read-model, P9 wiring scope

---

## Area 1 — Overlay mechanics → config-hierarchy restructure

The single deepest area. Started on "how does the overlay work," converged (via owner steering) into a
full config-hierarchy restructure.

| Decision | Options considered | Selected |
|---|---|---|
| Authority model | Push + snapshot mirror / Snapshot-read only / Push only | **Push** (mutate + `handler.update_config` + persist) |
| Snapshot machinery | Immutable atomic-swap / Mutable in-place / key-value dict | **Mutable in-place** (no snapshot machinery — store is the read-model) |
| Source of truth | DB durable / overlay primary | **DB durable; config object = live view rebuilt at boot** |
| Access | Imported singleton / Injected via `ctx.config` / hybrid | **Imported singleton** (owner override of spec §7a injection) |
| `RuntimeConfig` class | Dissolves into aggregator / distinct class | **Dissolves — no separate class** |
| Immutability enforcement | Frozen aggregator + non-frozen sub-models / all non-frozen allowlist-only | **Frozen aggregator + non-frozen sub-models** |
| Aggregator name | `ITraderConfig` / `AppConfig` / `TradingConfig` / new | **`ITraderConfig`** |
| Field grouping | Stay in domain blocks / nested sub-model | **Nested sub-model** (owner) → generalized to full restructure |

**User's choice / rationale:** Owner rejected the design spec's separate-`RuntimeConfig`-wrapper +
`EngineContext.config`-injection model. Preferred: the existing `SystemConfig` aggregator (repurposed as a
new frozen `ITraderConfig`) IS the mutable config, imported like `config` today, with a nested-sub-model
structure. Demote `Settings` → env-leaf and `SystemConfig` → a narrow lifecycle sub-model. Key owner
catches: the atomic-swap snapshot machinery is unnecessary once the store is the read-model; the FastAPI
mutation path works fine with a global singleton (mutation crosses via the event bus, not injection).
**Notes:** Config cleanups folded in and verified against the code — remove `PerformanceSettings`
(keep `rng_seed`, move to frozen base, oracle-gated) and `MonitoringSettings` (→ new `UniverseConfig`);
both mostly 0-ref. Layering-sequence for frozen-base + import-singleton flagged as a key research risk.

---

## Area 2 — Allowlist & validation

| Decision | Options considered | Selected |
|---|---|---|
| Allowlist representation | Central registry / field-metadata / hand dict | **None — structural** (owner: don't over-engineer) |
| Mutation-surface granularity | Sub-model membership / router-routed keys / field marker | **Sub-model membership = mutable** |
| Apply/persist ordering | validate→persist→apply / apply→persist→rollback / no-rollback | **validate → persist → apply** |
| Rejection surfacing | Ingress 400 + WARNING ErrorEvent / dedicated Ack event | **Ingress 400 + engine-thread WARNING ErrorEvent** |

**User's choice / rationale:** Owner: "I wouldn't introduce any allowlist — immutability is dictated by
what events exist to mutate + Pydantic validation; if no event mutates a class, it can't be mutated, and
I'm in full control of the events." Accepted: the structure IS the allowlist (frozen base + scoped router
+ `validate_assignment`); field placement becomes the security decision. Venue-kind (RTCFG-05) = router
predicate.
**Notes:** Recorded that RTCFG-02/04 name an "allowlist" but the intent is met structurally — flagged so
the verifier doesn't ding "missing allowlist."

---

## Area 3 — Stats/state read-model (RTCFG-06)

| Decision | Options considered | Selected |
|---|---|---|
| Cadence | Hybrid / all event-driven / all periodic | **Event-driven** (state at source; stats event-driven) |
| Table layout | Stats own table / three tables / all in SystemStore | **Stats own append-only table; config+state in SystemStore** |
| Read-model shape | Domain stores + state.* + thin stats / aggregate everything | **Domain stores + state.* + thin `system_stats`** |
| Stats content | (fat: incl. equity) / (thin: engine-operational only) | **Thin — engine-operational counters only** |

**User's choice / rationale:** Owner questioned why portfolio equity would be in stats — caught that
`portfolio_account_state` + `equity_snapshots` already persist marked `total_equity` (latest + history).
Result: no equity duplication; stats holds only engine-operational counters (breach/error/queue/uptime) in
its own append-only table; entity data reads from the domain stores. Owner preferred all-event-driven; the
contention objection dissolved once stats got its own table and became thin.
**Notes:** Claude's earlier "DB reader can't recompute equity" claim was wrong (equity is already
persisted marked) — corrected.

---

## Area 4 — P9 wiring scope

| Decision | Options considered | Selected |
|---|---|---|
| External `CONFIG_UPDATE` ingress | Internal-only + facade / open `add_event` now | **Open `add_event` now** (owner override of lean rec) |
| Strategy config path | STRATEGY_COMMAND/P10 / add strategy scope to ConfigUpdateEvent | **STRATEGY_COMMAND / P10 — out of P9** |

**User's choice / rationale:** Owner chose to open external `CONFIG_UPDATE` ingress in P9 despite FastAPI
being out of scope — implication captured: ingress 400-validation lives at `add_event`, P9 tests must
drive it directly, auth is the future app-layer's job. Strategy confirmed out of `ConfigUpdateEvent`.
**Notes:** Scopes locked to `{system, order, venue, portfolio}` by success criterion #2 (not open). P9
owns store construction + restart layering (cashes P4 D-02) and finalizes the P4 store method surface
(cashes P4 D-09). Flagged P9 as large → likely wave decomposition.

---

## Claude's Discretion

- Construction/layering sequence resolving the frozen-base + import-singleton risk (D-10).
- `system_stats` columns + exact counter set; router internal structure; WARNING-`ErrorEvent` dedup
  mechanism; sub-model/field naming beyond the locked renames; `_VAR`-global fold inventory; wave/plan
  granularity.

## Deferred Ideas

- FastAPI application layer (LR-01) — endpoints/auth/ASGI deferred; P9 opens the ingress + shapes the seam.
- Strategy runtime reconfiguration (STRAT-03 / Phase 10).
- `system_stats` history retention/rollup.
- `trading_system/` run-mode split (P7 Deferred) — unrelated to P9.
- Migration baseline reset/squash (P4 Deferred) — milestone-level.
