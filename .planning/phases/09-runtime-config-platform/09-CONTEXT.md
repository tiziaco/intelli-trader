# Phase 9: Runtime-Config Platform ★ - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

> **Phase-resolution note (for the planner/researcher):** GSD `init.phase-op` mis-resolves
> "Phase 9" to the **archived v1.1** dir (`milestones/v1.1-phases/09-multi-entity-...`) because
> its next-phase dir-scan collides with same-numbered archived phases. The correct target is this
> **v1.8 Phase 9 — Runtime-Config Platform**, working dir `.planning/phases/09-runtime-config-platform/`
> (created this session). Ignore any `has_context/has_plans/has_verification=true` flags from init —
> those read the archived v1.1 dir, not this phase.

<domain>
## Phase Boundary

Build a durable, restart-surviving runtime-config platform for the **live** engine (RTCFG-01..06):
a runtime-mutable config surface injected/imported into the live handlers, a scoped
`ConfigUpdateEvent(scope, key, value)` on the CONTROL plane validated + routed on the engine thread to
its owning store and handler, persisted, and layered back on restart — plus a UI read-model
(operational `state.*` + a thin `system_stats` series, with entity data read from the domain stores).

**Live-only, backtest-dark.** The backtest oracle stays byte-exact (`134 / 46189.87730727451`) and
`tests/integration/test_okx_inertness.py` stays green — held as per-phase gates.

**This phase grew a foundation:** the discussion converted "a runtime-config *platform*" into a
**config-hierarchy restructure** (new `ITraderConfig` aggregator) that the mutable surface is built on.
That restructure touches the config the **backtest** reads, so it is **oracle- + inertness-gated** and is
the load-bearing decision of the phase — see D-01..D-09. The architecture in the design spec §6c–6e (a
separate `RuntimeConfig` wrapper injected via `EngineContext.config`) was **deliberately superseded** by
the owner in favor of the aggregator model (D-05/D-06) — planners must NOT rebuild the spec's wrapper.

**Scopes wired in P9:** `{system, order, venue, portfolio}` (success criterion #2). Strategy config is
**out of scope** — it is STRAT-03 / Phase 10 via `STRATEGY_COMMAND` (D-24). P9 is large; it likely wants
**wave decomposition** (config restructure → mutation path → read-model) — planning's call (D-20).

</domain>

<decisions>
## Implementation Decisions

### Config hierarchy restructure (Area 1 — the load-bearing decision; oracle/inertness-gated)

- **D-01 (Overlay = push model, not a snapshot object):** A config change flows
  `ConfigUpdateEvent → mutate the config in place + call the owning handler's existing
  `update_config()` + persist`. Handlers observe changes via the **push** (`update_config`), not by
  re-reading a snapshot. The only live reader of the config object itself is the engine-thread router.
- **D-02 (DB is durable truth; the config object is the live view rebuilt at boot):** The stores
  (`SystemStore`/`VenueStore`/portfolio store) are the durable source of truth. On restart,
  `build_live_system` rebuilds the config by layering `defaults ← YAML ← env ← persisted overrides`.
  The config object is never persisted as one blob.
- **D-03 (No copy-on-write/atomic-swap "snapshot" machinery):** Because the **read-model is the store**
  (the UI reads the DB, not the in-memory config) and handlers read pushed caches, nothing reads the
  config object cross-thread. So it is a **plain engine-thread-owned mutable object** — single writer +
  single live reader, both on the engine thread. No locks, no immutable snapshots. (Reverses an earlier
  over-engineered recommendation.)
- **D-04 (Determinism protected by allowlist + placement, not object immutability):** Backtest stays
  byte-exact because (a) the immutable determinism fields (`rng_seed`, money precision, `environment`,
  IDs) live on the **frozen** aggregator base and can't be mutated, and (b) backtest never runs the
  `ConfigUpdateEvent` path. Both invariants must hold for the oracle to stay green.
- **D-05 (No separate `RuntimeConfig` class — it dissolves into the aggregator):** There is **no**
  distinct `RuntimeConfig` type and **no wrapper**. The single `config` aggregator singleton **is** the
  runtime config: its frozen base params are immutable, its non-frozen sub-models are the mutable
  overlay. **Deliberate deviation from design spec §6c/LR-14 ("two config objects") — owner override.**
- **D-06 (New top-level aggregator `ITraderConfig`, frozen; imported singleton):** Introduce
  `ITraderConfig` as the top-level **`frozen=True` `BaseModel`** aggregator, replacing `SystemConfig` as
  the root. The process singleton is created **once at import** (`config = ITraderConfig(...)`, import-inert,
  empty overrides) and **mutated in place, never reassigned** — so `from itrader import config` importers
  see every change (avoids the `from-import` late-binding trap). The live factory layers persisted
  overrides **into** the same instance at boot. `EngineContext.config` stays vestigial/`Any` (NOT threaded
  as the config seam — owner override of spec §7a). Access is by **import**, not injection.
- **D-07 (Frozen aggregator + non-frozen sub-models):** The aggregator is `frozen=True` (can't reassign
  base params or swap a sub-model reference); each domain sub-model is a normal non-frozen `BaseModel`
  whose fields mutate in place. `config.rng_seed = x` is blocked by the type system; `config.stream.x = x`
  is allowed. Frozen base = structural determinism guard; the mutation-surface structure = the second layer.
- **D-08 (`Settings` demotes to env-leaf; `SystemConfig` demotes to a narrow lifecycle sub-model):**
  `config/settings.py::Settings` (a `pydantic-settings.BaseSettings`) stays the **env-var leaf** (a field
  on the aggregator = the `env` layer), NOT the aggregator itself (its `BaseSettings` env-parsing must not
  leak into every nested field). `SystemConfig` demotes to a mutable sub-model `system:` holding the
  system-lifecycle knobs (`enable_auto_restart`, `auto_restart_delay_seconds`, `enable_graceful_shutdown`,
  `shutdown_timeout_seconds`, + residual scattered `_VAR` globals folded in). Identity base params
  (`name`, `version`, `environment`, `debug_mode`, dirs) move up onto the frozen aggregator base.
- **D-09 (Config cleanups — verified unused, fold into the restructure):**
  - **Remove `PerformanceSettings` entirely; move `rng_seed` to the frozen aggregator base** (`config.rng_seed`).
    Its other 6 fields (`max_threads`/`max_processes`/`enable_multiprocessing`/`enable_async`/
    `connection_pool_size`/`timeout_seconds`) are **verified 0-ref** (safe to delete). **`rng_seed`'s path
    move `config.performance.rng_seed` → `config.rng_seed` is oracle-gated** (must resolve to 42 →
    byte-exact); `rng_seed` is also the concrete case of the layering-sequence risk (immutable-at-runtime
    but YAML-settable-at-boot — see D-10).
  - **Remove `MonitoringSettings` entirely; move its 2 used fields into a new `UniverseConfig` mutable
    sub-model** — `config.universe.poll_cadence_s` + `config.universe.remove_policy` (drop the redundant
    `universe_` prefix; the handler already calls the param `remove_policy`). Its other 7 fields
    (metrics/health/profiling/tracing ports+flags) are **verified 0-ref**. Live-only (universe poll timer +
    `UniverseHandler`), backtest-dark → **no oracle risk**. `remove_policy` is runtime-mutable → `UniverseConfig`
    is a mutable sub-model.
- **D-10 (KEY RESEARCH RISK — frozen-base + import-singleton + boot layering sequence):** The layering
  `defaults ← YAML ← env ← persisted` must reconcile with *when* the singleton is constructed: the frozen
  **base** params are fixed at construction, while the **mutable sub-models** are layered later by the live
  factory via in-place mutation. If a base param ever needs a YAML/persisted override (`rng_seed` is exactly
  such a field — env/YAML-settable at boot, immutable at runtime), the frozen-at-import timing fights it.
  **Researcher must resolve the construction/layering sequence** (likely: base params resolve
  defaults+YAML+env *at construction*, before freeze; persisted overrides apply only to mutable sub-models).

### Allowlist & validation (Area 2)

- **D-11 (No separate allowlist artifact — the structure IS the allowlist):** Do **not** build a
  standalone allowlist data structure (satisfies RTCFG-02's *intent*, not a thing named `ALLOWLIST` —
  recorded so the planner/verifier doesn't flag "missing allowlist"). The mutation boundary is expressed
  structurally three compounding ways: frozen base blocks immutable keys (RTCFG-04 by type), the router's
  scope→owner mapping is the routable-key set, and Pydantic validates. Default-deny holds (unknown/unrouted
  key → reject).
- **D-12 (Mutation surface = every field on a mutable sub-model):** No finer-than-sub-model granularity.
  The router applies `(scope, key)` by `setattr` on the owning mutable sub-model. **Field placement is the
  security decision** — any field that must NOT be caller-mutable goes on the frozen base, not in a mutable
  sub-model. The (future FastAPI) mutation surface derives from introspecting the mutable sub-models.
- **D-13 (Validation = Pydantic `validate_assignment`):** Enable `validate_assignment=True` on the mutable
  sub-models so every `setattr` re-runs the field's own type coercion + `Field(...)` constraints. No
  hand-rolled per-key validators; one source of truth for "what's a legal value."
- **D-14 (Venue-kind rule = router predicate, not a declaration):** RTCFG-05 (fee/slippage mutable only for
  **simulated** venues; reject for live) is a **state-dependent predicate in the venue-scope apply path** —
  the router checks the venue's kind at apply time and rejects for a live venue. Real-venue fees/slippage
  come from actual fills, not engine config.
- **D-15 (Apply/persist ordering = validate → persist → apply):** On the engine thread: coerce/validate
  the value, **persist to the owning store**, then `setattr` the live sub-model + `handler.update_config`.
  Persist failure → reject, nothing applied live (DB and config never diverge in the
  "applied-but-not-persisted" direction; no rollback needed). The rare persist-ok/apply-throws logs
  CRITICAL; DB is correct, restart heals.
- **D-16 (Rejection surfacing = ingress 400 + engine-thread WARNING `ErrorEvent`):** Ingress-side validation
  (bad type/range on a known field) returns synchronously (a 400 once FastAPI exists). Engine-thread
  rejections (venue-kind, persist failure) emit a **WARNING-severity `ErrorEvent`, deduped/rate-limited**
  exactly like P7 D-09's throttle-breach pattern, and update the read-model's `state.last_error`. No new
  event type.

### Stats/state read-model (Area 3 — RTCFG-06)

- **D-17 (Read-model = domain stores + `state.*` + thin `system_stats`; NO entity duplication):** The UI
  reads entity data **directly from its own store** — equity/positions from `portfolio_account_state` +
  `equity_snapshots` (both already persist marked `total_equity`, latest + history), orders from the order
  store, halts from `halt_records`. **Do NOT copy portfolio equity into a stats blob** (it's already
  persisted; duplication was caught and rejected). RTCFG-06 is satisfied by "these are all lock-free DB
  reads," not by an aggregation layer.
- **D-18 (`system_stats` = its own append-only table; engine-operational metrics only):** `stats` holds
  ONLY the engine-operational counters no domain store owns — P7 **throttle breach counter**, **error
  counts by severity**, event-queue depth / connector-&-stream health, uptime. It gets its **own
  append-only table** (a breach/error time-series, mirroring `equity_snapshots`) — one new table + migration
  chained after P4's `strategy_registry`. Written **event-driven** by a **thin engine-thread stats writer**
  that snapshots counters it already holds in memory (no read-model aggregation needed).
- **D-19 (`state.*` event-driven at source):** `state.status` on each SafetyController status transition,
  `state.halt_reason` on halt, `state.last_error` on `ErrorEvent`, `state.last_started_at` on start —
  written immediately at each event's own source into `SystemStore` (low-rate, discrete key-value). `config.*`
  + `state.*` stay in `SystemStore`; only `stats` splits out (D-18).

### P9 wiring scope (Area 4)

- **D-20 (P9 is large → wave decomposition expected):** Restructure `ITraderConfig` (gated) + construct
  stores in the live factory + wire the `ConfigUpdateEvent` router + restart layering + read-model writer &
  `system_stats` table. Likely 3 waves (config restructure → mutation path → read-model) — planning's call.
- **D-21 (Scopes locked to `{system, order, venue, portfolio}`):** All four wired in P9 (success criterion
  #2 — not a subset; RTCFG-05's sim-only venue fee/slippage is criterion #3). `system→SystemStore`,
  `order→SystemStore`, `venue:{name}→VenueStore`, `portfolio:{id}→Portfolio+portfolio store`.
- **D-22 (P9 owns store construction + restart layering — cashes P4 D-02):** P9 constructs
  `SystemStore`/`VenueStore` + the new `system_stats` table in the live factory and adds the
  `defaults ← YAML ← env ← persisted` layering to `build_live_system`. (P4 deferred construction + state
  application to consumers, naming P9.)
- **D-23 (External `CONFIG_UPDATE` ingress OPENS in P9 — owner override of the lean recommendation):**
  `add_event`'s D-10 fail-closed allowlist extends to a **third admitted external type** (`SIGNAL`,
  `STRATEGY_COMMAND`, **`CONFIG_UPDATE`**). Implications: (1) the **ingress 400-validation lives at the
  `add_event` admission boundary** for `CONFIG_UPDATE` (external events arrive there), with the
  engine-thread re-check behind it (defense-in-depth); (2) with **no FastAPI driver yet (LR-01)**, P9's own
  tests **must drive the external `CONFIG_UPDATE` path directly** so it isn't untested surface; (3)
  "external" = the trusted app-layer caller — **auth is the future FastAPI layer's job, not the engine's**;
  the engine's guard is the structural mutation-surface + type/range + venue-kind validation.
- **D-24 (Strategy config is OUT of `ConfigUpdateEvent`):** Strategy enable/disable + atomic param
  reconfiguration = STRAT-03 / Phase 10, driven by `STRATEGY_COMMAND` + `StrategyRegistryStore`. The
  RTCFG-02 allowlist mention of "strategy enable/disable + params" is a cross-reference to STRAT-03, not a
  P9 scope.
- **D-25 (Finalize P4 store method surface against the real consumer — cashes P4 D-09):** P9 adds the
  `SystemStore`/`VenueStore` methods the config-mutation path + read-model actually need (upsert/read
  `config.*` for restart layering, `state.*` upsert, append `system_stats`). Exact method names/signatures
  = planner discretion.

### Claude's Discretion
- Exact construction/layering sequence resolving D-10 (subject to the byte-exact + inertness gates).
- Precise `system_stats` table columns + the exact engine-operational counter set (D-18) — it's an
  extensible series; start minimal.
- Router internal structure (scope dispatch table, the frozen-target guard) and the exact dedup/rate-limit
  mechanism for D-16's WARNING `ErrorEvent`.
- Naming of the demoted `system:` lifecycle sub-model and the new `UniverseConfig` fields beyond the
  `remove_policy`/`poll_cadence_s` rename.
- Which residual `_VAR` module globals fold into the `system` sub-model (inventory pass).
- Wave/plan/commit granularity for D-20.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source (authoritative for the platform architecture — with the owner overrides above)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` **§6** (6a–6f — config
  centralization & the config platform: 6c two-config-objects [**superseded by D-05/D-06**], 6d
  `system_store`, 6e runtime-mutation flow + scope routing, 6f cleanup), **§7a** (`EngineContext` —
  `config` field [**owner override D-06: stays vestigial**]), **§7d** (cardinality-aligned stores), **§14**
  (deferred stats-history-table split — **cashed forward by D-18**), **§13c** (`LiveRouteRegistrar` —
  P9 registers the `CONFIG_UPDATE` CONTROL consumer).

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **RTCFG-01..06** (lines 240–266) + milestone-wide gates (§15).
- `.planning/ROADMAP.md` → "Phase 9 ★: Runtime-Config Platform" (goal + 5 success criteria, lines 365–378).

### Prior-phase context this phase depends on / cashes forward
- `.planning/phases/04-storage-schema-migrations-relocation-new-durable-stores/04-CONTEXT.md` — **D-02**
  (stores standalone, construction deferred to P9), **D-09** (store method surface finalized in P9 against
  the real consumer — cashed by D-25), the `HaltRecordStore` store template, the migration chain
  `d10_halt_records → system_store → venue_config → strategy_registry` (P9's `system_stats` chains after).
- `.planning/phases/07-safety-reconciliation-stream-recovery/07-CONTEXT.md` — **D-14** (P7 shaped the P9
  throttle-cap mutation seam; P9 wires it), **D-09** (breach counter → read-model, cashed by D-18),
  the WARNING-`ErrorEvent` dedup pattern (cashed by D-16).

### Existing code the restructure/wiring touches
- `itrader/config/system.py` — `SystemConfig` (aggregator → demote to `system:` sub-model, D-08);
  `PerformanceSettings` (remove, keep `rng_seed`, D-09); `MonitoringSettings` (remove → `UniverseConfig`,
  D-09); the mutable sub-model fields (`stream`/`feed_provider`/`safety`/`order`).
- `itrader/config/settings.py` — `Settings` (`BaseSettings`) stays the env-leaf (D-08).
- `itrader/config/` — `stream.py`, `order.py`, `safety.py`, `portfolio.py`, `exchange.py` (the mutable
  sub-models); `merge.py`/`models.py` (layering helpers).
- `itrader/__init__.py` — `config = SystemConfig.default()` → `config = ITraderConfig(...)` singleton
  (create-once, mutate-in-place, D-06); import-inertness constraint.
- `itrader/trading_system/engine_context.py` — `config: Any` stays vestigial (D-06; docstring's "narrows to
  SystemConfig in P9" note is superseded).
- `itrader/events_handler/events/control.py` + `core/enums/event.py::EventType.CONFIG_UPDATE` (route slot
  exists, empty) + `events_handler/bus.py` (`CONFIG_UPDATE` is a CONTROL-tier member) — the
  `ConfigUpdateEvent` home + CONTROL routing.
- `itrader/events_handler/full_event_handler.py` — `EventType.CONFIG_UPDATE: []` route (wire the consumer).
- `itrader/trading_system/live_trading_system.py` — `add_event` D-10 fail-closed allowlist (extend for
  `CONFIG_UPDATE`, D-23); the live factory / `build_live_system` (store construction + restart layering, D-22).
- `itrader/storage/system_store.py`, `venue_store.py` — finalize method surface (D-25); new `system_stats`
  store/table + registrar + migration (D-18).
- `itrader/portfolio_handler/storage/models.py` — `portfolio_account_state` (`total_equity`/`peak_equity`/
  `open_positions_count`) + `equity_snapshots` — the read-model's equity source (D-17, do NOT duplicate).
- Handlers' existing `update_config(...)` — `execution_handler.py`, `order_manager.py`/`order_handler.py`,
  `portfolio.py`/`portfolio_handler.py`, `strategies_handler.py`, `simulated.py`, `bar_feed.py` (the push
  targets, D-01).
- `itrader/execution_handler/execution_handler.py:70-82` — `_resolve_rng_seed` reads
  `config.performance.rng_seed` (oracle-gated path move to `config.rng_seed`, D-09).

### Gates (must stay green — restated, not re-decided)
- `tests/integration/test_backtest_oracle.py` — byte-exact `134 / 46189.87730727451` (per-plan gate on the
  config restructure + `rng_seed` path move).
- `tests/integration/test_okx_inertness.py` — import inertness (`ITraderConfig`/`config/` must stay
  SQL/ccxt-import-free; the restructure must not regress the register-vs-build assertion).

</code_context>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`SystemConfig` is already a mutable `BaseModel` aggregator** (`config/system.py`, `extra="forbid"`,
  not frozen) with the domain sub-models (`performance`/`monitoring`/`stream`/`feed_provider`/`safety`/
  `runtime`) — the restructure repurposes it (rename → `ITraderConfig`, add `frozen=True`, demote the
  lifecycle fields to a `system:` sub-model), not builds it from scratch.
- **Every handler already has `update_config(...)`** — the push targets for D-01 exist; no new interface.
- **`EventType.CONFIG_UPDATE` route slot + CONTROL bus tier already exist** (empty) — P9 wires the consumer
  onto an existing seam; `control.py` is the copyable event home.
- **P4 stores (`SystemStore`/`VenueStore`) + the `HaltRecordStore` template** — the persistence spine;
  `system_stats` clones the append-only `equity_snapshots` shape.
- **P7 breach counter + WARNING-`ErrorEvent` dedup** — the read-model counter (D-18) + rejection-surfacing
  pattern (D-16) already exist to reuse.

### Established Patterns
- **Singleton create-once at import, mutate-never-reassign** (`config`/`idgen` in `itrader/__init__.py`) —
  D-06 follows it; the mutate-in-place representation (D-03/D-07) is what keeps `from itrader import config`
  safe under a late-layering factory.
- **Import inertness (GATE-01):** `config/` imports only pydantic/stdlib; the restructure must keep
  `ITraderConfig` construction SQL/ccxt-free (persisted-override *loading* happens in the live factory).
- **Indentation:** `itrader/config/` is **4-space**; `trading_system/`/`storage/` files are split (measure
  bytes per file, never generalize — see the split-indentation memory). Match per file.
- **Registrar = single source of truth** (`build_*_table` feeds both `create_all` and Alembic
  `target_metadata`) — the new `system_stats` registrar follows it; extend the parity gate.
- **CONTROL events + `LiveRouteRegistrar`** — register the `CONFIG_UPDATE` consumer declaratively.

### Integration Points
- Live factory / `build_live_system`: constructs stores, builds the restart-layered `config`, wires the
  `ConfigUpdateEvent` router + read-model writer (D-22).
- `add_event` (D-10): admits external `CONFIG_UPDATE` + runs ingress 400-validation (D-23/D-16).
- Engine-thread router: the `CONFIG_UPDATE` CONTROL consumer — validate → persist → apply → push (D-15).
- Read-model: `state.*` written at each event source (D-19); thin stats writer → `system_stats` (D-18); UI
  reads domain stores + `state.*` + `system_stats` (D-17).

</code_context>

<specifics>
## Specific Ideas

- Owner's driving reframe: **"I don't want a new RuntimeConfig / an EngineContext.config param — the
  existing `SystemConfig` aggregator should BE the mutable config, imported like `config` today."** →
  drove the aggregator model (D-05/D-06) over the spec's wrapper.
- Owner's structural insight: **frozen base + mutable sub-models makes immutability a property of *where a
  field lives*, and the allowlist a property of the *structure*, not a separate artifact** (D-07/D-11/D-12).
- Owner caught two duplications/over-engineering: **the atomic-swap snapshot machinery** (unnecessary once
  the store is the read-model, D-03) and **portfolio equity in the stats blob** (already persisted by the
  portfolio store, D-17). Both removed.
- Owner's cleanup instinct verified against the code: `PerformanceSettings`/`MonitoringSettings` are mostly
  0-ref (D-09).

</specifics>

<deferred>
## Deferred Ideas

- **FastAPI application layer (LR-01, out of scope this milestone)** — P9 opens the external
  `CONFIG_UPDATE` ingress + a facade-shaped mutation seam, but the ASGI app, auth, and `POST /config/...`
  endpoints are the FastAPI phase's job. See [[fastapi-application-layer-plan]].
- **Strategy runtime reconfiguration (STRAT-03 / Phase 10)** — strategy enable/disable + atomic param
  reconfiguration via `STRATEGY_COMMAND` + `StrategyRegistryStore`; NOT a `ConfigUpdateEvent` scope (D-24).
- **`system_stats` history retention/rollup** — the append-only series (D-18) will eventually want a
  retention/rollup policy; start minimal, revisit if it grows.
- **`config.trading_system/` run-mode split** — the broader `trading_system/live` vs `backtest` reorg
  (P7 Deferred) is unrelated to P9 and stays its own inserted phase.
- **Migration baseline reset/squash** — still a milestone-level decision (P4 Deferred), not P9.

None else — discussion stayed within the runtime-config platform scope (with the config-hierarchy
restructure pulled in as its explicit foundation).

</deferred>

---

*Phase: 9-Runtime-Config Platform ★*
*Context gathered: 2026-07-16*
