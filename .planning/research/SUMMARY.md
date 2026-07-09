# Project Research Summary

**Project:** iTrader — v1.8 Live System Refactor & Live-Readiness Hardening
**Domain:** Event-driven algorithmic-trading engine (brownfield structural refactor)
**Researched:** 2026-07-09
**Confidence:** HIGH (MEDIUM only on the P10–P12 trim-boundary judgment calls)

> Synthesized from `STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md`. The research
> **validates the already-locked design** (`docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md`,
> decisions LR-00..LR-22, folded TODOs CF-1..CF-10) against mature frameworks (Nautilus Trader, LEAN),
> Python stdlib, and refactor-pitfall knowledge — it does not re-open the design.

## Executive Summary

v1.8 decomposes the 2,171-line `LiveTradingSystem` God object (~17 concerns) into a factory + shared
`compose_engine` + `LiveRunner` + focused controllers, adding a two-tier priority event bus, a venue
registry/plugin system, three new SQL stores, a runtime-config platform, and multi-portfolio-live —
**without disturbing the byte-exact backtest oracle (`134 / 46189.87730727451`) or the OKX
import-inertness gate.** Research against Nautilus Trader and QuantConnect LEAN confirms the locked
design is the proven shape of a mature live kernel: the shared-kernel + mode-factory split (LR-10)
mirrors Nautilus's `NautilusKernel`/`TradingNode`; the two-registry split (execution venue vs data
provider, LR-17) is exactly Nautilus's `add_exec_client_factory`/`add_data_client_factory` and LEAN's
`IBrokerageFactory`/`IDataQueueHandler`. The 2,171-line God object is the precise anti-pattern both
frameworks avoid.

**Zero new third-party dependencies are needed.** Every mechanic resolves to Python stdlib
(`queue.PriorityQueue`, `itertools.count`, `typing.Protocol`, `functools.cached_property`) plus
already-pinned deps (SQLAlchemy 2.0.50, Alembic 1.18.5, pydantic 2.13). Adding any library would
regress the inertness gate — so **"no new dependency, no poetry change"** is a milestone-wide
constraint. The priority-bus tuple-ordering is provably safe via a single process-wide monotonic
`seq` (comparison terminates at `seq`, never dereferencing the non-orderable frozen event).

Residual risk concentrates in three places: (1) **P9's CF-1 aggregate circuit breaker** — the one fold
that adds a real acceptance criterion (must actually trip on a money route failing every event; must
preserve the WR-06 two-guard terminal safety and leave backtest fail-fast byte-for-byte unchanged);
(2) a **genuine table-stakes GAP** — a pre-trade order-submit-rate / max-notional throttle that
Nautilus's `RiskEngine` enforces but iTrader lacks (it has only post-hoc CF-1 + per-order
`EnhancedOrderValidator` — nothing caps submission velocity from a runaway strategy emitting *valid*
orders); needs an owner decision, candidate fold into P8/P9; (3) the **★ P10–P12 feature-adds**, where
P10's runtime-config *mutation* path is the highest over-engineering risk.

## Key Findings

### Recommended Stack

**Zero new dependencies.** All five evaluated mechanics resolve to stdlib or already-validated deps;
adding a library would regress the OKX inertness gate. (Full detail: `STACK.md`.)

**Core technologies (all already present):**
- **`queue.PriorityQueue` + `itertools.count()`** — the two-tier `PriorityEventBus` substrate; the
  `(tier, seq, event)` tuple is ordered by a globally-unique monotonic `seq` so comparison never
  reaches the non-orderable frozen event. Stdlib, no new dep.
- **`typing.Protocol` + a dict registry** — the venue/data-provider registries and `VenuePlugin`.
  Entry-points/pluggy/stevedore are **disqualified** (eager discovery import breaks lazy-import
  inertness — registering `'okx'` must pull no `ccxt.pro`).
- **SQLAlchemy 2.0.50 Core + Alembic 1.18.5** — the three new stores follow the existing
  `HaltRecordStore` template; migration chain `d10_halt_records → system_store → venue_config →
  strategy_registry` (verified head = `d10_halt_records`). `migrations/` relocation is a one-line
  `script_location` edit (ini already uses `%(here)s`; `down_revision` chains by id, path-independent).
- **pydantic 2.13 + pydantic-settings** — the `SystemConfig` eager/lazy split and `RuntimeConfig`
  overlay; no dynaconf/hydra (they fight the single-writer snapshot-read contract).

### Expected Features

Validated against Nautilus + LEAN. 12 table-stakes capabilities (all AGREE with the spec), 6
differentiators, 8 correctly-deferred anti-features. (Full detail: `FEATURES.md`.)

**Must have (table stakes — the core refactor, P1–P9 + P13):**
- Shared-kernel + mode-factory decomposition (LR-10) — the God-object teardown itself
- Two-registry venue system (LR-17) — the exact Nautilus/LEAN separation
- Venue bundles + connector memoization; precision/validate as exchange capabilities
- Safety subsystem: halt/pause state machine + durable halt record + startup refusal + reconciliation
- Handler-owns-storage-init; centralized `SystemConfig`; `SqlEngine` rename + migrations relocation

**Should have (differentiators):**
- Two-tier priority bus (CONTROL > BUSINESS) — genuinely *exceeds* Nautilus's single-tier FIFO;
  solves "kill-switch queued behind a market-data backlog" (caveat: `SIGNAL` stays BUSINESS)
- ★ Runtime-config platform (P10), ★ strategies registry (P11) — durable, survive restart

**GAP (table-stakes, owner decision):**
- **Pre-trade submit-rate / max-notional throttle** — Nautilus `RiskEngine` has it; iTrader has no
  runaway-valid-orders guard. Candidate fold into P8/P9, or explicit defer.

**Defer (correctly cut by the spec — do NOT build):**
- Shared-`account_id` risk allocator, config audit table, errors-history table, multi-provider
  feed-router, single-connector-multi-account optimization.

### Architecture Approach

Every integration point traced against real existing files (`compose.py`, `full_event_handler.py`,
`backtest_runner.py`). The `.put()` non-change is load-bearing: the bus is injected into the *same
constructor slot* handlers use for `global_queue` today; `FifoEventBus`/`PriorityEventBus` are
`queue.Queue`-API-compatible; tier assignment happens *inside* `PriorityEventBus.put` via a
`_CONTROL_EVENT_TYPES` frozenset — **zero call-site edits**. Backtest's `process_events()` drain stays
literally unchanged. (Full detail: `ARCHITECTURE.md`.)

**Major components (new vs modified):**
1. `EventBus` Protocol + `FifoEventBus`/`PriorityEventBus` — NEW; injected into `compose_engine`
2. `EngineContext` (frozen: bus/config/environment/sql_engine) — NEW; threaded once into `compose_engine`
3. `LiveRunner` + `build_live_system` factory + focused controllers (`SafetyController`,
   `ReconciliationCoordinator`, `StreamRecoveryHandler`, `WorkerSupervisor`, `SessionInitializer`) — NEW
4. `ExecutionVenueRegistry` + `DataProviderRegistry` + `VenuePlugin`/`VenueBundle` — NEW
5. `LiveRouteRegistrar` — NEW; merges live routes into the SINGLE `EventHandler` (no subclass)
6. `compose_engine`, `LiveTradingSystem` (→ ~200-line facade), Order/Strategies handler storage-init,
   shared `UniverseWiring` — MODIFIED

**4 build-order refinements to the spec's §16 dependency table:**
1. **P3 depends on P2** (the table omits this) — `EngineContext.bus` needs the `EventBus` from P2.
2. **Introduce a minimal `EngineContext` skeleton in P2** so `compose_engine`'s signature settles once
   rather than being double-edited across P2 and P3.
3. **P2 must add the new CONTROL `EventType` members** (`STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`)
   — the bus tier frozenset references them, even though consumers land in P8/P10.
4. **Fold the `SqlBackend→SqlEngine` rename into P3** (it collides with `EngineContext.sql_engine:
   Optional[SqlEngine]` typing); only the migrations *relocation* stays a P4-standalone.

### Critical Pitfalls

Top items from `PITFALLS.md` (8 refactor-specific pitfalls, each with warning signs + prevention +
owning phase):

1. **Behavior-drift during "pure code-motion"** — the `UniverseWiring` extraction (P7) is the single
   highest oracle-risk seam (analogous to v1.2 MOD-01). Prevention: move as one intact unit incl. the
   WR-03 desync assert; **byte-exact oracle + determinism double-run as a per-PLAN gate on P1–P6 +
   P7-UniverseWiring**, not per-phase.
2. **Inertness regression** — an eager import sneaking in via a barrel re-export, a non-lazy
   `SqlSettings`, or a registry importing concretions at registration. Prevention: lazy-import-inside-
   `build_bundle` IS the contract; make `test_okx_inertness.py` the P6 acceptance gate (extended to
   assert register-vs-build for P1/P2/P5/P6).
3. **CF-1 circuit-breaker false-green** — a breaker that "runs green with zero settlements," or that
   reintroduces the WR-06 error→error livelock. Prevention: P9 scoped as "ship the aggregate breaker"
   (hard acceptance criterion: it must actually trip; SETTLEMENT halt-on-first), not "refactor the
   error seam."
4. **Threading-contract violation** — CF-2 `backfill_on_resume` on the engine thread = a second
   concurrent ring writer. Prevention: it must land **loop-native** (connector loop via the reconnect
   callback, P8), with an assertion no engine-thread path reaches it.
5. **Alembic chain divergence** — relocation + 3-store chain multi-head/`create_all`-vs-migration
   drift. Prevention: explicit P4/P5 gate (`upgrade head` on clean DB + `alembic heads == 1` +
   create_all/migration parity test).

## Implications for Roadmap

Suggested structure: **13 phases (P1–P13)**, matching spec §16 with the 4 architecture refinements
folded in. Full scope chosen (incl. ★ P10–P12).

### Phase 1: Config centralization
**Rationale:** No dependencies; hosts the lazy `sql` accessor (a core inertness lever) + the CF-8
`HaltReason` enum that P8 consumes.
**Delivers:** `SystemConfig` aggregation (eager/lazy/templates), module-constant migration, dead-config
audit, `extra` normalization. **Avoids:** inertness regression (lazy `sql`).

### Phase 2: Event bus
**Rationale:** Foundational; P3's `EngineContext.bus` needs it.
**Delivers:** stdlib `EventBus` Protocol + `FifoEventBus`/`PriorityEventBus`, the new CONTROL
`EventType` members, and a minimal `EngineContext` skeleton (refinements 2+3). **Uses:**
`queue.PriorityQueue` + `itertools.count`. **Test:** tuple comparison never reaches the event.

### Phase 3: EngineContext + storage-in-handler + SqlEngine rename
**Rationale:** Depends on {P1, P2} (refinement 1). **Delivers:** full `EngineContext`, handler-owns
storage init (Order/Strategies), new `compose_engine(ctx, spec)` signature, and the `SqlBackend→SqlEngine`
rename folded in (refinement 4). **Implements:** the shared composition seam.

### Phase 4: Migrations relocation
**Rationale:** Mechanical, now standalone (rename moved to P3). **Delivers:** `itrader/storage/migrations/`
→ project-root `migrations/`; `alembic.ini` `script_location` edit. **Gate:** single-head + parity test.

### Phase 5: New durable stores
**Rationale:** Depends on P4 (chain relocated). **Delivers:** `SystemStore`/`VenueStore`/
`StrategyRegistryStore` via the `HaltRecordStore` template + single-head Alembic chain + rehydrate.

### Phase 6: Venue registry + bundle
**Rationale:** Depends on {P2, P3}; highest inertness risk. **Delivers:** two registries,
`VenuePlugin`/`VenueBundle`, `LiveDataProvider` Protocol, connector memoization by `(venue,
account_id)`, precision/validate on the exchange, per-portfolio account factory, shared
`StreamSupervisor` (CF-3/4/9). **Avoids:** inertness regression (`test_okx_inertness` = acceptance gate).

### Phase 7: LiveRunner + factory + facade shrink
**Rationale:** Depends on {P5, P6}; **highest oracle risk** (UniverseWiring). **Delivers:**
`build_live_system`, `LiveRunner`, `SessionInitializer` + shared `UniverseWiring` *(oracle-sensitive)*,
`LiveRouteRegistrar`, `UniverseHandler` proper init, `StrategyWarmupConsumer` rehome, drop legacy
`print_status`/`get_statistics`/`__init__` params (CF-10).

### Phase 8: Safety + reconciliation + stream recovery
**Rationale:** Depends on P7. **Delivers:** `SafetyController`, `ReconciliationCoordinator`,
`StreamRecoveryHandler`, CONTROL routes, flag machinery deleted (CF-2 loop-native, CF-7, CF-8).
**Candidate home** for the pre-trade throttle GAP (owner decision).

### Phase 9: Error subsystem
**Rationale:** Depends on P7. **Delivers:** `ErrorPolicy` injected (no monkeypatch), `ErrorHandler`
formalized, two-guard terminal safety, and **CF-1 aggregate circuit breaker (hard acceptance
criterion)** + CF-5 pluggable alert sink seam.

### Phase 10 ★: Runtime-config platform
**Rationale:** Depends on {P5, P8}. **Delivers:** SystemStore-backed overrides, scoped
`ConfigUpdateEvent`, allowlist (cap ~5–8 keys explicitly), restart layering, `RuntimeConfig` overlay,
stats snapshot. **Trim note:** first trim candidate if pressure hits (keep the read-model, cut the
mutation path).

### Phase 11 ★: Strategies registry
**Rationale:** Depends on {P5, P7}. **Delivers:** durable `StrategyRegistryStore` rehydrate,
enable/disable via `STRATEGY_COMMAND`, survives restart. **Trim note:** second trim candidate (keep
durable-resume, cut runtime toggle).

### Phase 12 ★: Multi-portfolio-live
**Rationale:** Depends on {P6, P8}; LR-03 mandate — **never trim**. **Delivers:** per-`account_id`
account factory, drop single-portfolio guard + distinct-`account_id` invariant (fail loud),
per-portfolio reconcile, connector keyed `(venue, account_id)`, `PortfolioSpec.account_id`,
`clOrdId→client_order_id`.

### Phase 13: Replay→fixture + gates
**Rationale:** Depends on {P7, P12}; lands last. **Delivers:** `run_paper_replay`→`ReplayRunner` in
`tests/`, `replay` plugin fixture-registered, production replay-free; live-smoke / config-restart /
multi-portfolio attribution gates.

### Phase Ordering Rationale
- Foundation (P1–P4) is oracle-gated and dependency-linear: config → bus → context/storage → migrations.
- Stores (P5) precede the venue/live decomposition that consumes them (P6–P9).
- The ★ feature-adds (P10–P12) depend on the decomposed core, so they land after P5–P9.
- Test migration (P13) lands last because it gates the whole live surface incl. multi-portfolio.

### Research Flags
Phases likely needing deeper (plan-time) research:
- **P7** — UniverseWiring byte-exact extraction discipline (the highest oracle-risk seam)
- **P9** — CF-1 route-classification + livelock-test design
- **P12** — `client_order_id`/`portfolio_id` two-key attribution discipline

Requirements-definition decisions (not research):
- **P10** allowlist scope (pin an explicit key cap)
- The **pre-trade throttle GAP** — fold into P8, P9, or defer (owner call)

Phases with standard patterns (skip research-phase):
- **P2** (bus pattern fully specified), **P4/P5** (mechanical Alembic + proven `HaltRecordStore`
  template), **P6** (house Protocol+dict idiom)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | stdlib semantics + tuple-ordering proof unambiguous; chain head + versions inspected in-repo |
| Features | HIGH | grounded in Nautilus/LEAN official docs; MEDIUM only on trim-boundary calls |
| Architecture | HIGH | every integration point traced against real existing files |
| Pitfalls | HIGH | grounded in the spec §4/§15/§18 + locked CLAUDE.md constraints |

**Overall confidence:** HIGH (MEDIUM only on the P10–P12 trim-boundary judgment calls)

### Gaps to Address
- **Pre-trade submit-rate / max-notional throttle (GAP)** — the only table-stakes item missing from the
  26 concerns + CF-list; needs an owner decision at requirements (fold P8/P9 or defer).
- **P10 runtime-mutable-key allowlist** — enumerate + cap explicitly during requirements, not left open.
- **Free-threaded CPython `itertools.count()` atomicity** — documentation-only note; not active for this
  milestone (assumes GIL build).

## Sources

### Primary (HIGH confidence)
- NautilusTrader — Architecture, Risk API, Live API (docs.nautilustrader.io) — kernel/factory split,
  RiskEngine throttle, exec/data client separation
- QuantConnect LEAN — Brokerages contribution guide — `IBrokerageFactory`/`IDataQueueHandler`
- SQLAlchemy · PyPI + GitHub Releases (2.0.50/2.0.51); Alembic Configuration docs + PyPI (1.18.5) —
  version currency, `script_location`/`down_revision` semantics
- In-repo inspection: `alembic.ini`, migration chain head, `storage/backend.py`, `compose.py`,
  `full_event_handler.py`, `backtest_runner.py`

### Secondary (MEDIUM confidence)
- The spec's own §16 phasing + trim boundary (validated, with 4 refinements)

---
*Research completed: 2026-07-09*
*Ready for roadmap: yes*
