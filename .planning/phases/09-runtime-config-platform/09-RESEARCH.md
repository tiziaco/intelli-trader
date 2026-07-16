# Phase 9: Runtime-Config Platform ★ - Research

**Researched:** 2026-07-16
**Domain:** Pydantic v2 config aggregation, event-driven runtime mutation, durable KV/append-only stores, Alembic migration chain
**Confidence:** HIGH (the central D-10 claims are empirically VERIFIED against the project's own pydantic 2.13.4; all wiring seams read from live code)

> **Scope note for the planner:** CONTEXT.md D-01..D-25 are LOCKED owner decisions. This research does
> NOT re-litigate them — it turns them into concrete, code-anchored recipes the planner can slice into
> tasks. Where the additional_context brief flagged a "central research question" (D-10) or a "verify the
> shape before sketching" (event base class), those are resolved below with runnable evidence.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (verbatim intent — see 09-CONTEXT.md for full text)
- **D-01** Overlay = push model: `ConfigUpdateEvent → mutate config in place + call owning handler's
  existing `update_config()` + persist`. Handlers observe via push, never re-read a snapshot. The only
  live reader of the config object is the engine-thread router.
- **D-02** DB is durable truth; the config object is the live view rebuilt at boot by layering
  `defaults ← YAML ← env ← persisted`. Never persisted as one blob.
- **D-03** NO copy-on-write / atomic-swap snapshot machinery. Plain engine-thread-owned mutable object,
  single writer + single live reader, both on the engine thread. No locks.
- **D-04** Determinism protected by allowlist + placement, not object immutability: immutable determinism
  fields (`rng_seed`, money precision, `environment`, IDs) live on the **frozen aggregator base**; backtest
  never runs the `ConfigUpdateEvent` path.
- **D-05** NO separate `RuntimeConfig` class/wrapper — the single `config` aggregator singleton IS the
  runtime config. **Owner override of design spec §6c/§7a — do NOT rebuild the wrapper.**
- **D-06** New top-level `ITraderConfig`, `frozen=True` `BaseModel`, replaces `SystemConfig` as root.
  Created once at import (`config = ITraderConfig(...)`, import-inert, empty overrides), **mutated in place,
  never reassigned**. `EngineContext.config` stays vestigial/`Any`. Access by import, not injection.
- **D-07** Frozen aggregator + non-frozen sub-models. `config.rng_seed = x` blocked by type system;
  `config.stream.x = x` allowed.
- **D-08** `Settings` demotes to env-leaf field; `SystemConfig` demotes to a narrow `system:` lifecycle
  sub-model. Identity base params (`name`, `version`, `environment`, `debug_mode`, dirs) move up onto the
  frozen aggregator base.
- **D-09** Remove `PerformanceSettings` (move `rng_seed` → `config.rng_seed`, oracle-gated; other 6 fields
  0-ref, delete). Remove `MonitoringSettings` (2 used fields → new `UniverseConfig`
  `poll_cadence_s`/`remove_policy`; other 7 fields 0-ref, delete).
- **D-10 (KEY RESEARCH RISK — RESOLVED below):** reconcile `defaults ← YAML ← env ← persisted` with WHEN
  the frozen singleton is constructed. Resolution: base params resolve defaults+YAML+env AT construction
  (before freeze); persisted overrides apply only to mutable sub-models via the live factory's in-place
  field-wise mutation on boot.
- **D-11** No standalone allowlist artifact — the structure IS the allowlist (frozen base + router
  scope→owner map + Pydantic validation; default-deny on unknown/unrouted key).
- **D-12** Mutation surface = every field on a mutable sub-model; router applies `(scope,key)` by `setattr`.
  Field placement is the security decision.
- **D-13** Validation = Pydantic `validate_assignment=True` on the mutable sub-models. No hand-rolled
  per-key validators.
- **D-14** Venue-kind rule = router predicate (fee/slippage runtime-mutable only for simulated venues;
  reject for live).
- **D-15** Apply/persist ordering = validate → **persist → apply** (`setattr` + `handler.update_config`).
  Persist failure → reject, nothing applied live.
- **D-16** Rejection surfacing = ingress 400 + engine-thread WARNING `ErrorEvent` (deduped/rate-limited,
  P7 D-09 pattern) + update `state.last_error`. No new event type.
- **D-17** Read-model = domain stores + `state.*` + thin `system_stats`; NO entity duplication (equity from
  `portfolio_account_state`/`equity_snapshots`).
- **D-18** `system_stats` = its own append-only table (clones `equity_snapshots` shape); engine-operational
  metrics only; written by a thin engine-thread stats writer; migration chains after P4 `strategy_registry`.
- **D-19** `state.*` written event-driven at source into `SystemStore` (`state.status`/`state.halt_reason`/
  `state.last_error`/`state.last_started_at`).
- **D-20** P9 is large → wave decomposition expected (config restructure → mutation path → read-model).
- **D-21** Scopes locked to `{system, order, venue, portfolio}` — all four wired.
  `system→SystemStore`, `order→SystemStore`, `venue:{name}→VenueStore`, `portfolio:{id}→Portfolio+store`.
- **D-22** P9 owns store construction + restart layering in `build_live_system` (cashes P4 D-02).
- **D-23** External `CONFIG_UPDATE` ingress OPENS in P9 — third admitted external type in `add_event`;
  ingress 400-validation at `add_event` + engine-thread re-check; P9 tests drive the external path directly.
- **D-24** Strategy config OUT of `ConfigUpdateEvent` (STRAT-03 / Phase 10).
- **D-25** Finalize P4 `SystemStore`/`VenueStore` method surface against the real consumer (cashes P4 D-09).

### Claude's Discretion
- Exact construction/layering sequence resolving D-10 (subject to byte-exact + inertness gates).
- Precise `system_stats` columns + engine-operational counter set (extensible; start minimal).
- Router internal structure (scope dispatch table, frozen-target guard) + dedup/rate-limit for D-16.
- Naming of the demoted `system:` sub-model + new `UniverseConfig` fields beyond the two renames.
- Which residual `_VAR` module globals fold into the `system` sub-model (inventory pass).
- Wave/plan/commit granularity for D-20.

### Deferred Ideas (OUT OF SCOPE)
- FastAPI application layer (LR-01) — P9 opens the ingress + facade-shaped seam only; ASGI/auth/endpoints
  are the FastAPI phase's job.
- Strategy runtime reconfiguration (STRAT-03 / Phase 10).
- `system_stats` history retention/rollup (start minimal).
- `config.trading_system/` run-mode split (separate inserted phase).
- Migration baseline reset/squash (milestone-level, P4 Deferred).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RTCFG-01 | Runtime-mutable config surface built by the live factory, read by handlers so they see runtime changes | The `ITraderConfig` frozen-base + mutable-sub-models aggregator (D-06/D-07 recipe below) + `build_live_system` boot layering. **Note: RTCFG-01's literal text ("`RuntimeConfig` overlay injected as `EngineContext.config`") is SUPERSEDED by D-05/D-06** — satisfy the intent (runtime-mutable, handler-observed), not the wording. |
| RTCFG-02 | Scoped `ConfigUpdateEvent(scope,key,value)` (CONTROL) validated against allowlist + type/range, routed on engine thread to owning store + handler, persisted | `ConfigUpdateEvent` in `events/control.py` (msgspec.Struct) + engine-thread router (validate→persist→apply→push) + scope→owner dispatch. Allowlist IS the structure (D-11). |
| RTCFG-03 | Persisted overrides survive restart — `build_live_system` layers them over defaults on boot | Store `read_all()`/`get()` → field-wise `setattr` into mutable sub-models at boot (D-22 layering recipe). |
| RTCFG-04 | Immutable-at-runtime keys rejected | Frozen aggregator base placement (D-04/D-07) — `setattr` on a base param raises `ValidationError` (verified). |
| RTCFG-05 | Fee/slippage runtime-mutable ONLY for simulated venues; reject for live | Router venue-kind predicate (D-14) checking venue kind at apply time. |
| RTCFG-06 | `system_store` `stats` + `state.*` double as UI read-model, lock-free DB reads | Domain-store reads (D-17) + `state.*` in `SystemStore` (D-19) + new `system_stats` append-only table (D-18). |
</phase_requirements>

## Summary

Phase 9 has two intertwined halves: (1) a **config-hierarchy restructure** that renames the existing
`SystemConfig` aggregator into a new `frozen=True` `ITraderConfig` root with immutable base params +
mutable domain sub-models — this is load-bearing because it touches the config the backtest reads, so it is
oracle-gated (`134 / 46189.87730727451`) and inertness-gated (`test_okx_inertness.py`); and (2) the
**runtime-mutation platform** on the LIVE engine — a `ConfigUpdateEvent` on the CONTROL bus, an
engine-thread router (validate→persist→apply→push), durable stores, restart layering, and a lock-free
UI read-model.

The central risk (D-10) is fully resolvable and I verified the mechanics against the project's own
`pydantic 2.13.4`: a `frozen=True` Pydantic v2 model CAN hold non-frozen sub-models whose fields mutate
in place; `config.stream.x = 9` works while `config.rng_seed = 1` raises `ValidationError`;
`validate_assignment=True` re-runs coercion + `Field(...)` constraints on every `setattr`. The construction
sequence that reconciles the frozen-at-import singleton with the `defaults ← YAML ← env ← persisted`
layering is: **base params resolve defaults+YAML+env into a dict AT construction time (before the object
exists / freezes); the singleton is created once at import with empty persisted overrides; the live factory
applies persisted overrides at boot by field-wise `setattr` into the (non-frozen) mutable sub-models only.**
Base params (`rng_seed`, `environment`) are never persisted-overridable at runtime — exactly the RTCFG-04
guarantee.

**Primary recommendation:** Restructure first (Wave 1, oracle+inertness-gated), then the mutation path
(Wave 2), then the read-model (Wave 3) — as D-20 anticipates. Reuse every existing seam verbatim
(`update_config()` push targets, `SystemStore`/`VenueStore` templates, the `HaltRecordStore` migration
pattern, the `LiveRouteRegistrar`, the P7 WARNING-`ErrorEvent` dedup). Build nothing new that already exists.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config aggregation + immutability guard | Config layer (`itrader/config/`) | — | Frozen base = structural determinism guard; sub-models = mutation surface (D-07). Pure pydantic/stdlib — inertness-critical. |
| External `CONFIG_UPDATE` admission | Live composition root (`LiveTradingSystem.add_event`) | — | The one public external surface; default-deny allowlist (D-23). Ingress 400-validation lives here. |
| `CONFIG_UPDATE` routing + apply | Engine thread (router, a CONTROL consumer) | Handlers (`update_config` push) | Single-writer engine-thread ownership (D-03); validate→persist→apply→push (D-15). |
| Durable persistence | Storage spine (`SystemStore`/`VenueStore`/`system_stats`) | Portfolio store | DB is durable truth (D-02); read-model is the store (D-17). |
| Restart layering | Live factory (`build_live_system`) | Stores | Boot rebuilds the live view from persisted overrides (D-22). |
| UI read-model | Domain stores + `state.*` + `system_stats` | — | Lock-free DB reads, no aggregation layer, no entity duplication (D-17). |

## Standard Stack

No new external packages. Everything is already in `pyproject.toml`. Verified present:

| Library | Version (installed) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| pydantic | 2.13.4 `[VERIFIED: poetry run python]` | Frozen aggregator + `validate_assignment` sub-models | Already the config system (M2-06); D-13 leans on its native assignment validation |
| pydantic-settings | ^2.14 `[CITED: pyproject.toml]` | `Settings` env-leaf (`ITRADER_*`) | Already the env layer (D-08 keeps it as a leaf field) |
| sqlalchemy | ^2.0.50 `[CITED: pyproject.toml]` | `SystemStore`/`VenueStore`/`system_stats` Core tables | Existing storage spine |
| alembic | (in migration chain) `[VERIFIED: migrations/versions/]` | `system_stats` migration chained after `strategy_registry` | Existing migration tooling |
| msgspec | (Event base) `[VERIFIED: events/base.py]` | `ConfigUpdateEvent` struct | The Event base IS `msgspec.Struct`, NOT a dataclass (see landmine below) |

**No `## Package Legitimacy Audit`** — this phase installs zero external packages.

## Architecture Patterns

### The D-10 Construction Recipe (CENTRAL — empirically verified)

The frozen-aggregator + mutable-sub-model model is real and works in pydantic 2.13.4. Verified behaviors
(run in the project venv):

```
sub-model field mutate OK           -> cfg.stream.reconnect_budget = 9      ✓
validate_assignment coerces str->int -> cfg.stream.x = '12' becomes int 12   ✓
validate_assignment enforces Field() -> cfg.stream.x = -1 raises ValidationError ✓
frozen base param blocked            -> cfg.rng_seed = 1 raises ValidationError  ✓ (RTCFG-04)
top-level sub-model reassign blocked -> cfg.stream = StreamSub() raises ValidationError ✓
nested-of-nested mutate OK           -> cfg.safety.throttle.max_orders = 99   ✓
alias/import sees in-place change    -> same object, importers see mutation   ✓
```

**Construction sequence (the D-10 resolution):**

```python
# itrader/config/itrader_config.py  (4-space indent — config/ is spaces)
from pydantic import BaseModel, ConfigDict, Field

class ITraderConfig(BaseModel):
    """Frozen top-level aggregator (D-06/D-07). Base params immutable; sub-models mutable."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- FROZEN BASE = the immutable determinism/identity guard (D-04/D-09) ---
    # RTCFG-04: these cannot be setattr'd at runtime (ValidationError). rng_seed moved
    # up from config.performance.rng_seed -> config.rng_seed (ORACLE-GATED, must -> 42).
    rng_seed: int = 42
    environment: Environment = Environment.DEVELOPMENT
    name: str = "iTrader System"
    version: str = "1.0.0"
    debug_mode: bool = True
    data_dir: str = "data"; log_dir: str = "logs"; config_dir: str = "settings"; cache_dir: str = "cache"

    # --- MUTABLE SUB-MODELS = the mutation overlay (D-07/D-12); each validate_assignment=True ---
    system: SystemSettings = Field(default_factory=SystemSettings)      # demoted SystemConfig (D-08)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)    # ex-MonitoringSettings 2 fields (D-09)
    stream: StreamSettings = Field(default_factory=StreamSettings)
    feed_provider: FeedProviderSettings = Field(default_factory=FeedProviderSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    order: OrderConfig = Field(default_factory=OrderConfig)

    # env-leaf (D-08): Settings(BaseSettings) stays a FIELD, not the root
    runtime: Settings = Field(default_factory=Settings)

    @cached_property
    def sql(self) -> "SqlSettings":            # KEEP the lazy accessor verbatim (inertness lever)
        from itrader.config.sql import SqlSettings
        return SqlSettings()
```

```python
# itrader/__init__.py — create ONCE at import, mutate in place, NEVER reassign (D-06)
# base params resolve defaults+YAML+env AT CONSTRUCTION; persisted overrides layered LATER by the factory.
config = ITraderConfig()          # import-inert, empty persisted overrides — no SQL/ccxt import
```

```python
# build_live_system (D-22) — boot layering applies persisted overrides into MUTABLE sub-models only.
# defaults<-YAML<-env already resolved at construction; persisted is the last layer, field-wise setattr.
def _layer_persisted(config, system_store, venue_store):
    for row in system_store.read_all():            # keys like "config.system.enable_auto_restart"
        scope, sub, field, value = _parse_config_key(row["key"], row["value"])
        target = _resolve_sub_model(config, scope)  # e.g. config.system / config.order
        setattr(target, field, value)               # validate_assignment re-coerces + re-validates
    # venue scope: config lives per-venue in VenueStore, applied to the venue's own sub-model/exchange
```

**Why base params can't be persisted-overridden at runtime, and why that's correct:** the frozen base is
fixed at construction. `rng_seed` IS env/YAML-settable **at boot** — because that resolution happens
*before* the object is constructed (merge defaults+YAML+env into the constructor dict). It is NOT
persisted-overridable at runtime, which is exactly RTCFG-04. So there is no timing conflict: boot-time
settability (construction dict) and runtime-immutability (frozen field) are different mechanisms.

### Pattern: `ConfigUpdateEvent` (copy `control.py` EXACTLY — msgspec, not dataclass)

**LANDMINE (flagged in brief, CONFIRMED):** the Event base is `msgspec.Struct`, NOT the frozen
`@dataclass` the CLAUDE.md overview describes. `events/base.py` line 21: `class Event(msgspec.Struct,
frozen=True, kw_only=True, gc=False)`. `type` is pinned via `ClassVar[EventType]`, NOT
`field(default=..., init=False)`. Copy the exact shape from `events/control.py`:

```python
# itrader/events_handler/events/control.py  (4-space indent — events package is spaces)
class ConfigUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
    """A scoped runtime config change on the CONTROL plane (RTCFG-02). Consumed on the engine thread."""
    type: ClassVar[EventType] = EventType.CONFIG_UPDATE     # slot already exists in core/enums/event.py
    scope: str          # one of {system, order, venue:{name}, portfolio:{id}}
    key: str
    value: Any
```

`EventType.CONFIG_UPDATE` already exists (`core/enums/event.py:38`) and is already a CONTROL-tier member
(`bus.py:_CONTROL_EVENT_TYPES:51`). The route slot `EventType.CONFIG_UPDATE: []` is pre-declared. The
`LiveRouteRegistrar` (`trading_system/route_registrar.py`) registers the consumer exactly like
`STREAM_STATE`/`CONNECTOR_FATAL` — its docstring already says *"The P9 `CONFIG_UPDATE` route populates the
same way when its consumer lands."* Add one line: `routes[EventType.CONFIG_UPDATE] = [self._on_config_update]`.

### Pattern: the engine-thread router (validate → persist → apply → push, D-15)

```python
def _on_config_update(self, event: ConfigUpdateEvent) -> None:
    # 1. Resolve (scope,key) -> owning mutable sub-model + owning store (D-21 dispatch table).
    #    Unknown/unrouted scope|key -> reject (default-deny, D-11). No standalone allowlist artifact.
    # 2. Venue-kind predicate (D-14/RTCFG-05): if scope is venue fee/slippage AND venue is live -> reject.
    # 3. Coerce/validate: assigning to the sub-model with validate_assignment=True IS the validation (D-13).
    #    (Dry-validate first, or catch ValidationError from the real setattr — see ordering note.)
    # 4. PERSIST to the owning store (D-15). Persist failure -> reject, nothing applied.
    # 5. APPLY: setattr on the mutable sub-model + handler.update_config(...) push (D-01).
    # 6. On any rejection: emit deduped WARNING ErrorEvent (P7 pattern) + update state.last_error (D-16/D-19).
```

**Ordering subtlety (D-15 says persist BEFORE apply, but validation must precede persist):** validate the
value first (so you don't persist garbage), then persist, then apply. Since the validation lives in
`validate_assignment`, the cleanest recipe is: validate against a throwaway copy of the sub-model field
(`sub.model_copy()` then `setattr` on the copy to trigger coercion/constraints) OR construct/validate the
scalar with the field's own validator, persist the coerced value, then `setattr` the real sub-model
(second setattr re-validates but that's cheap and idempotent). The "rare persist-ok/apply-throws logs
CRITICAL; DB correct, restart heals" case (D-15) is the only divergence window.

### Pattern: external ingress opening (D-23)

`live_trading_system.py:53`: `_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL,
EventType.STRATEGY_COMMAND})`. Extend to add `EventType.CONFIG_UPDATE` (the THIRD type). Update the
`add_event` docstring/warning strings that enumerate "only SIGNAL and STRATEGY_COMMAND". Add ingress-side
400-style validation (bad type/range on a known field → synchronous reject/`False`) at the `add_event`
boundary, with the engine-thread router re-checking behind it (defense-in-depth, D-16). With no FastAPI
(LR-01), **P9's own tests MUST drive `add_event(ConfigUpdateEvent(...))` directly** so the external path is
covered — this is a required test, not optional.

### Pattern: `system_stats` append-only table + migration + registrar (D-18)

Clone the `equity_snapshots` shape (`portfolio_handler/storage/models.py:178-196`) — composite PK
`(natural_key, seq)`, `autoincrement=False`, `UtcIsoText` timestamp, no UUID surrogate. Follow the
registrar single-source pattern (`build_*_table` feeds BOTH `create_all` and Alembic `target_metadata`).

```python
# itrader/storage/system_stats_store.py  (4-space — storage/ spine)
def build_system_stats_table(metadata: MetaData) -> Table:
    if "system_stats" in metadata.tables:
        return metadata.tables["system_stats"]
    return Table(
        "system_stats", metadata,
        Column("seq", Integer, primary_key=True, autoincrement=False),   # engine writes seq (no 2nd ID scheme)
        Column("timestamp", UtcIsoText, nullable=False),
        # minimal engine-operational counter set (D-18 — extensible, start minimal):
        Column("throttle_breach_count", Integer, nullable=False),        # P7 breach counter (D-14/D-09)
        Column("error_count_warning", Integer, nullable=False),
        Column("error_count_error", Integer, nullable=False),
        Column("error_count_critical", Integer, nullable=False),
        Column("queue_depth", Integer, nullable=False),                  # bus.depth_by_tier() sum
        Column("uptime_seconds", Numeric, nullable=False),
        Column("connector_up", Boolean, nullable=False),                 # connector/stream health
        Column("stream_up", Boolean, nullable=False),
    )
```

Migration `system_stats.py` chains after `strategy_registry` (copy
`migrations/versions/strategy_registry.py` verbatim structure): `revision="system_stats"`,
`down_revision="strategy_registry"`, hand-add `import itrader.storage.types` (autogenerate omits the
`UtcIsoText` import — Pitfall 2). Register in `migrations/env.py` after line 79
(`build_system_stats_table(target_metadata)`). The metadata-parity gate extends automatically since env.py
imports every registrar.

### Pattern: store method surface finalization (D-25)

`SystemStore` already has `upsert(key,value,at)` / `get(key)` / `delete(key)` / `read_all()` — these
already cover `config.*` upsert/read for restart layering AND `state.*` upsert (both are just namespaced
keys, e.g. `"state.status"`, `"config.system.enable_auto_restart"`). **`SystemStore` likely needs NO new
methods** — verify the key-naming convention is the only decision. `VenueStore` has
`upsert(venue_name,config,enabled,at)` / `get` / `list_enabled` / `read_all` — sufficient for venue-scope
config. The new `system_stats` store needs an `append(row, at)` + `read_recent(n)` / `read_all()`.

### System Architecture Diagram

```
                 external app-layer caller (future FastAPI, LR-01)
                          │  ConfigUpdateEvent(scope,key,value)
                          ▼
        LiveTradingSystem.add_event ──[D-10 allowlist +CONFIG_UPDATE]──► reject (False/400) on bad type/range
                          │ admitted
                          ▼
                   PriorityEventBus (CONTROL tier 0, preempts BUSINESS)
                          │ dequeued on engine thread
                          ▼
        _on_config_update router  ── validate ──► persist ──► apply ──► push
             │ (D-11 default-deny)      │(D-13)     │(store)   │        │handler.update_config
             │ scope→owner map          │           │          │setattr on mutable sub-model (config.X.y)
             ▼ reject                   │           ▼          ▼
        WARNING ErrorEvent (deduped,    │      SystemStore / VenueStore / portfolio store (durable truth)
        P7 pattern) + state.last_error  │           │
                                        └──venue-kind predicate (D-14): live venue fee/slippage → reject

  state.* written event-driven at source ─► SystemStore   ┐
  thin engine-thread stats writer ─► system_stats table   ├─► UI read-model (lock-free DB reads, D-17):
  equity/positions/orders/halts ─► own domain stores      ┘    domain stores + state.* + system_stats

  RESTART: build_live_system → construct stores → ITraderConfig() (defaults+YAML+env at construction)
           → _layer_persisted (field-wise setattr into mutable sub-models) → wire router → start
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-key value validation | A hand-rolled allowlist dict + per-key validators | `validate_assignment=True` on sub-models (D-13) | One source of truth; `Field(...)` constraints already declare legal ranges (verified re-runs on `setattr`) |
| Runtime immutability of `rng_seed`/`environment` | A guard function checking key names | Field placement on the frozen base (D-04/D-07) | `setattr` raises `ValidationError` structurally (verified); no key list to drift |
| Config change propagation | A pub/sub / observer bus for config | Existing `handler.update_config(...)` push (D-01) | Every handler already has it — no new interface |
| Durable KV / per-venue store | A new persistence layer | `SystemStore`/`VenueStore` (already built P4) | Method surface already covers config.*/state.* |
| Stats history table | A generic time-series abstraction | Clone `equity_snapshots` (composite PK, seq) | Established append-only pattern; migration + registrar templates exist |
| Config snapshot / atomic swap | Copy-on-write, immutable snapshots, RW-locks | Plain engine-thread-owned mutable object (D-03) | Single writer + single live reader on one thread — nothing reads cross-thread (D-17: UI reads DB) |
| A separate `RuntimeConfig` wrapper | The design spec §6c wrapper | The `ITraderConfig` aggregator itself (D-05) | Owner override — the aggregator IS the runtime config |

**Key insight:** almost every "component" P9 seems to need already exists as a seam waiting to be wired
(CONFIG_UPDATE enum/route/CONTROL-tier, `update_config` push, the two stores, the registrar, the P7 dedup).
P9 is mostly *wiring + one restructure*, not new machinery.

## Common Pitfalls / Landmines

### Pitfall 1: `ConfigUpdateEvent` written as a frozen `@dataclass`
**What goes wrong:** CLAUDE.md's architecture overview says events are frozen dataclasses. They are NOT —
they migrated to `msgspec.Struct` (`events/base.py:21`, confirmed by memory `events-are-msgspec-struct`).
**How to avoid:** copy `events/control.py`'s existing `StreamStateEvent`/`ConnectorFatalEvent` verbatim
(`class X(Event, frozen=True, kw_only=True, gc=False)`, `type: ClassVar[EventType]`).

### Pitfall 2: `rng_seed` path move breaks the oracle
**What goes wrong:** `execution_handler.py:82` reads `config.performance.rng_seed`. Moving to
`config.rng_seed` (D-09) must still resolve to 42 → byte-exact `134 / 46189.87730727451`.
**How to avoid:** update `_resolve_rng_seed` in the SAME plan as the restructure; run
`tests/integration/test_backtest_oracle.py` as the per-plan gate. Grep for `performance.rng_seed` and
`.performance.` / `.monitoring.` across the codebase before deleting those sub-models (D-09 claims 0-ref;
verify with grep, don't trust the claim).

### Pitfall 3: import-inertness regression (GATE-01)
**What goes wrong:** `ITraderConfig` construction pulling SQL/ccxt would break `test_okx_inertness.py` and
the perf/oracle gates. Persisted-override *loading* touches SQL — it must live in the live factory, NOT at
import.
**How to avoid:** keep `config = ITraderConfig()` at import with EMPTY persisted overrides; keep the
`sql` `@cached_property` lazy-import exactly as-is (`config/system.py:134-148`); `config/` imports only
pydantic/stdlib. Every new sub-model module (`UniverseConfig`, demoted `system`) must import pydantic/stdlib
ONLY. Run `test_okx_inertness.py` in the restructure plan.

### Pitfall 4: frozen aggregator is unhashable at runtime (GOTCHA — verified)
**What goes wrong:** `frozen=True` gives the model a `__hash__`, but `hash(config)` raises `TypeError:
unhashable type: 'StreamSub'` because it hashes field values and the mutable sub-models are unhashable
(verified). If any code puts `config` in a set/dict-key or a `@lru_cache` arg, it will crash.
**How to avoid:** never hash/use `config` as a dict key or cache key. It's a singleton accessed by import —
this shouldn't arise, but note it for reviewers. (This is intrinsic to frozen-base + mutable-sub-models.)

### Pitfall 5: nested sub-model REFERENCE reassignment is NOT blocked
**What goes wrong:** the frozen guard only blocks reassigning the TOP-LEVEL aggregator's own fields.
`config.safety = X` is blocked, but `config.safety.throttle = Throttle(...)` is ALLOWED (verified) because
`safety` is non-frozen. So the RTCFG-04 immutability guarantee ONLY holds for fields placed DIRECTLY on the
frozen aggregator base — a field nested inside a mutable sub-model is fully mutable including whole-object
swap.
**How to avoid:** every immutable-at-runtime key (`rng_seed`, `environment`, money precision, IDs) MUST be
a direct field on the `ITraderConfig` frozen base, never nested. The router applies `(scope,key)` by
field-level `setattr` on the owning sub-model, never by sub-model-reference swap.

### Pitfall 6: `from itrader import config` late-binding trap
**What goes wrong:** if the factory ever REASSIGNS `config` (`config = ITraderConfig(...)` a second time),
modules that did `from itrader import config` keep the old object and never see the layered overrides.
**How to avoid:** create ONCE at import, mutate in place (field-wise `setattr` on sub-models). Frozen base
enforces you can't reassign base params, but you must also never rebind the module-level `config` name in
the factory (D-06). The factory mutates `config.<sub>.<field>`, it does not build a new aggregator.

### Pitfall 7: split indentation
**What goes wrong:** a mixed tab/space diff breaks a file. `config/` and `events/` are 4-space; `storage/`
is 4-space; `route_registrar.py` and `live_trading_system.py` are 4-space; BUT `engine_context.py`,
`compose.py`, `backtest_trading_system.py` are TABS (memory `live-trading-system-is-space-indented`).
**How to avoid:** measure bytes per file before editing; never normalize.

### Pitfall 8: Alembic autogenerate omits the `UtcIsoText` import
**What goes wrong:** the `system_stats` migration's `updated_at`/`timestamp` uses the custom
`UtcIsoText` TypeDecorator; autogenerate won't import it → `NameError` on `upgrade head`.
**How to avoid:** hand-add `import itrader.storage.types` and reference
`itrader.storage.types.UtcIsoText()` (copy `strategy_registry.py:34,55`).

## Code Examples

Verified against project code (`itrader/config/system.py`, `events/control.py`, `storage/system_store.py`,
`storage/venue_store.py`, `migrations/versions/strategy_registry.py`, `migrations/env.py`,
`portfolio_handler/storage/models.py`) — see the Architecture Patterns section above for the concrete
sketches (all indentation-matched to their target files).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Design spec §6c: two config objects (`SystemConfig` + injected `RuntimeConfig`) | Single `ITraderConfig` frozen aggregator; access by import (D-05/D-06) | CONTEXT.md (owner override) | Do NOT build the wrapper or thread `EngineContext.config` |
| `config.performance.rng_seed` | `config.rng_seed` on frozen base (D-09) | P9 | Oracle-gated path move |
| Snapshot / atomic-swap config machinery (earlier over-eng rec) | Plain engine-thread mutable object (D-03) | CONTEXT.md | No locks, no snapshots |

**Deprecated/outdated:**
- `PerformanceSettings` (delete; keep only `rng_seed`), `MonitoringSettings` (delete; 2 fields →
  `UniverseConfig`) — verified mostly 0-ref by owner (D-09; re-grep before deleting).
- CLAUDE.md "frozen dataclass" event description — stale; events are `msgspec.Struct`.

## Validation Architecture

> nyquist_validation = true in `.planning/config.json` — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (Poetry-run) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/config tests/unit/storage -x` |
| Full suite command | `make test` (or in worktrees: `poetry run pytest tests` — `make test` aborts on missing `.env`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RTCFG-01 | Frozen base blocks base-param setattr; sub-model mutate + validate_assignment | unit | `poetry run pytest tests/unit/config/test_itrader_config.py -x` | ❌ Wave 0 |
| RTCFG-02 | Router validate→persist→apply→push; default-deny unknown scope/key | unit + integration | `poetry run pytest tests/unit/trading_system/test_config_router.py -x` | ❌ Wave 0 |
| RTCFG-03 | Persisted overrides re-layered at boot | integration | `poetry run pytest tests/integration/test_config_restart_layering.py -x` | ❌ Wave 0 |
| RTCFG-04 | Immutable keys (`rng_seed`/`environment`) rejected | unit | (part of test_itrader_config) | ❌ Wave 0 |
| RTCFG-05 | Live-venue fee/slippage rejected; sim allowed (venue-kind predicate) | unit | `poetry run pytest tests/unit/trading_system/test_config_router.py -k venue_kind` | ❌ Wave 0 |
| RTCFG-06 | `system_stats` append + `state.*` upsert; lock-free reads | unit + integration | `poetry run pytest tests/unit/storage/test_system_stats_store.py -x` | ❌ Wave 0 |
| GATE (oracle) | `rng_seed` path move stays byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| GATE (inertness) | `config/` restructure stays SQL/ccxt-free | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ exists |
| D-23 (ingress) | External `CONFIG_UPDATE` drives the path directly | integration | new test driving `add_event(ConfigUpdateEvent(...))` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run + the two GATE commands (oracle + inertness) on any restructure task.
- **Per wave merge:** `make test` (or `poetry run pytest tests`).
- **Phase gate:** full suite green + both GATE tests green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/config/test_itrader_config.py` — frozen base blocks, sub-model mutate, validate_assignment
  coercion/constraints, unhashable gotcha (RTCFG-01/04)
- [ ] `tests/unit/trading_system/test_config_router.py` — validate→persist→apply→push, default-deny,
  venue-kind predicate, persist-failure-rejects (RTCFG-02/05)
- [ ] `tests/integration/test_config_restart_layering.py` — persisted overrides survive restart (RTCFG-03)
- [ ] `tests/unit/storage/test_system_stats_store.py` — append + read (RTCFG-06/D-18)
- [ ] External-ingress integration test driving `add_event(ConfigUpdateEvent)` directly (D-23 — mandatory)
- [ ] Metadata-parity gate extension for `system_stats` (registrar single-source; likely auto-covered by
  env.py import — verify the existing parity test picks up the new registrar)
- [ ] `tests/unit/config/` may be package-less (avoid `__init__.py` collision — memory
  `test-dir-init-py-package-collision`)

## Security Domain

> `security_enforcement` absent in config → treated as enabled.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | yes | `add_event` fail-closed allowlist (default-deny); auth is the future FastAPI layer's job (D-23) — the engine's guard is the structural mutation-surface + type/range + venue-kind |
| V5 Input Validation | yes | `validate_assignment=True` (coercion + `Field(...)` range) on every `setattr` (D-13); ingress 400 at `add_event` + engine-thread re-check (D-16) |
| V6 Cryptography | no | — |
| V7 Secret handling | yes | `VenueStore._assert_no_secret_keys` recursive denylist already guards persisted venue config; credentials stay connector-owned (never persisted). `ConfigUpdateEvent.value` must never carry a secret to a store |

### Known Threat Patterns for the config-mutation surface
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mutating an immutable determinism key (`rng_seed`) at runtime | Tampering | Frozen-base placement (RTCFG-04) — `setattr` raises `ValidationError` |
| Injecting a raw internal event (e.g. `OrderEvent`) via the opened ingress | Elevation of Privilege | `add_event` default-deny allowlist admits only `{SIGNAL, STRATEGY_COMMAND, CONFIG_UPDATE}` |
| Setting live-venue fee/slippage to fake fills | Tampering | Venue-kind router predicate (RTCFG-05) rejects live-venue fee/slippage |
| Mass-assignment of unknown config keys | Tampering | `extra="forbid"` on sub-models + default-deny scope→owner map (D-11) |
| Persisting a credential into a config store | Info Disclosure | `VenueStore` secret-key denylist; credentials connector-owned |
| Error-message flood via rejected updates | DoS | Deduped/rate-limited WARNING `ErrorEvent` (P7 D-09 `warn_min_interval_s` pattern, reused) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `PerformanceSettings` (6 fields) + `MonitoringSettings` (7 fields) are 0-ref and safe to delete | Config restructure | Owner-verified (D-09) but planner MUST re-grep (`.performance.`, `.monitoring.`, field names) before deleting — a missed ref breaks import |
| A2 | `SystemStore.upsert/get/read_all` need NO new methods for `config.*`/`state.*` (only a key-naming convention) | D-25 store surface | LOW — they're namespaced KV; if a typed query is needed, add it. Confirm against the router's read pattern |
| A3 | The existing metadata-parity gate auto-covers `system_stats` once env.py imports its registrar | D-18 migration | LOW — env.py imports every registrar; verify the parity test enumerates dynamically, not a hard-coded table list |
| A4 | Money precision + "IDs" as immutable base fields don't currently exist as config fields to move (they're `core/money.py` scales + `idgen`) | RTCFG-04 | LOW — RTCFG-04 lists them as *rejected* keys; they aren't `config` fields today, so "rejection" = there's no routable key for them (default-deny covers it). Confirm no plan tries to add them as mutable |

**All other central claims (frozen + mutable sub-models, validate_assignment, frozen-base rejection,
nested-reassign gotcha, unhashable gotcha, msgspec event base) are `[VERIFIED]` — run in the project venv
or read directly from source.**

## Open Questions

1. **Where exactly does the "money precision" immutable key live, and does any plan try to route it?**
   - What we know: `core/money.py` `_INSTRUMENT_SCALES` are module constants, not `config` fields. RTCFG-04
     lists money precision as immutable-at-runtime.
   - What's unclear: whether P9 needs to surface it as a (rejected) config key at all.
   - Recommendation: treat RTCFG-04 as satisfied by absence — no routable key exists → default-deny rejects
     it structurally. Do NOT add a money-precision config field.

2. **Router validation-before-persist mechanic (dry-validate copy vs. catch-on-setattr).**
   - What we know: D-13 puts validation in `validate_assignment`; D-15 wants persist before apply.
   - Recommendation: dry-validate on `sub.model_copy()` (or the field's own validator) → persist coerced
     value → real `setattr`. Planner's call on the exact form; both are cheap. This is Claude's-discretion
     per CONTEXT.md.

## Environment Availability

No new external tools/services. SQLite (results/dev) + Postgres (live, `localhost:5432`) already required by
the storage spine; the config restructure + `system_stats` table use the existing SQLAlchemy spine. No
availability gate for P9 beyond what P4 already established. `[VERIFIED: pyproject.toml + CLAUDE.md]`

## Sources

### Primary (HIGH confidence)
- `poetry run python` against `pydantic 2.13.4` — empirical verification of the entire D-10 recipe (frozen
  base + mutable sub-models, validate_assignment, frozen rejection, nested-reassign gotcha, unhashable)
- `itrader/config/system.py`, `settings.py`, `safety.py`, `merge.py`, `__init__.py` — current config system
- `itrader/events_handler/events/base.py`, `control.py`, `error.py`; `core/enums/event.py`; `bus.py` — event
  substrate (msgspec base, CONFIG_UPDATE slot, CONTROL tier)
- `itrader/storage/system_store.py`, `venue_store.py`; `portfolio_handler/storage/models.py`
  (`equity_snapshots`); `migrations/versions/strategy_registry.py`; `migrations/env.py` — storage + migration
  templates
- `itrader/trading_system/live_trading_system.py` (`add_event`, `_EXTERNALLY_ADMISSIBLE`, `build_live_system`);
  `route_registrar.py` — wiring seams
- `itrader/execution_handler/execution_handler.py:70-99` — `_resolve_rng_seed` + `update_config` push
- `tests/integration/test_okx_inertness.py` — inertness gate shape
- `.planning/phases/09-runtime-config-platform/09-CONTEXT.md` — locked decisions D-01..D-25
- `.planning/REQUIREMENTS.md` RTCFG-01..06

### Secondary (MEDIUM confidence)
- MEMORY.md entries: `events-are-msgspec-struct`, `live-trading-system-is-space-indented`,
  `test-dir-init-py-package-collision`, `wr06-error-route-terminal-safety`, `make-test-env-disables-logs`

## Metadata

**Confidence breakdown:**
- D-10 construction recipe: HIGH — empirically verified against the project's own pydantic version
- Frozen + validate_assignment sub-model pattern: HIGH — verified, including two real gotchas
- Migration/registrar approach: HIGH — direct clone of existing verified templates
- Router + ingress design: HIGH — all seams read from live code (enum slot, CONTROL tier, allowlist, registrar)
- `system_stats` column set: MEDIUM — extensible starter set (Claude's discretion per D-18)

**Research date:** 2026-07-16
**Valid until:** ~30 days (stable brownfield; pydantic 2.x semantics are settled)
