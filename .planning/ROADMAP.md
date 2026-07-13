# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- ✅ **v1.5 — Backtest Performance Optimization** — Phases 1-8 (shipped 2026-06-26; numbering reset; performance half of Backlog 999.2, split out from Persistence; Phases 7-8 added 2026-06-25 from post-phase re-profiles)
- ✅ **v1.6 — N+3b Persistence Foundation** — Phases 1-5 (shipped 2026-06-30; numbering reset; promoted the **persistence half** of Backlog 999.2)
- ✅ **v1.7 — Live Trading Readiness (trimmed N+4 / Backlog 999.3)** — Phases 1-7 + 05.1/05.2/05.3 (shipped 2026-07-07; numbering reset; promoted Backlog 999.3; three remediation waves inserted after Phase 5; Phase 7 added 2026-07-06 from the Phase 6 code review)
- 🚧 **v1.8 — Live System Refactor & Live-Readiness Hardening** — Phases 1-12 (in progress; numbering reset; decomposes the 2,171-line `LiveTradingSystem` God object into a thin facade over focused collaborators — full scope incl. the three ★ feature-adds)

Full milestone detail (phase goals, success criteria, per-plan breakdown) is archived per milestone:
v1.0 — [`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md) ·
[`v1.0-REQUIREMENTS.md`](./milestones/v1.0-REQUIREMENTS.md) ·
[`v1.0-MILESTONE-AUDIT.md`](./milestones/v1.0-MILESTONE-AUDIT.md);
v1.1 — [`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md) ·
[`v1.1-REQUIREMENTS.md`](./milestones/v1.1-REQUIREMENTS.md) ·
[`v1.1-MILESTONE-AUDIT.md`](./milestones/v1.1-MILESTONE-AUDIT.md);
v1.2 — [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md) ·
[`v1.2-REQUIREMENTS.md`](./milestones/v1.2-REQUIREMENTS.md) ·
[`v1.2-MILESTONE-AUDIT.md`](./milestones/v1.2-MILESTONE-AUDIT.md);
v1.3 — [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md) ·
[`v1.3-REQUIREMENTS.md`](./milestones/v1.3-REQUIREMENTS.md) ·
[`v1.3-MILESTONE-AUDIT.md`](./milestones/v1.3-MILESTONE-AUDIT.md);
v1.4 — [`milestones/v1.4-ROADMAP.md`](./milestones/v1.4-ROADMAP.md) ·
[`v1.4-REQUIREMENTS.md`](./milestones/v1.4-REQUIREMENTS.md) ·
[`v1.4-MILESTONE-AUDIT.md`](./milestones/v1.4-MILESTONE-AUDIT.md);
v1.5 — [`milestones/v1.5-ROADMAP.md`](./milestones/v1.5-ROADMAP.md) ·
[`v1.5-REQUIREMENTS.md`](./milestones/v1.5-REQUIREMENTS.md) ·
[`v1.5-MILESTONE-AUDIT.md`](./milestones/v1.5-MILESTONE-AUDIT.md);
v1.6 — [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md) ·
[`v1.6-REQUIREMENTS.md`](./milestones/v1.6-REQUIREMENTS.md) ·
[`v1.6-MILESTONE-AUDIT.md`](./milestones/v1.6-MILESTONE-AUDIT.md);
v1.7 — [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md) ·
[`v1.7-REQUIREMENTS.md`](./milestones/v1.7-REQUIREMENTS.md) ·
[`v1.7-MILESTONE-AUDIT.md`](./milestones/v1.7-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`; v1.4 under `milestones/v1.4-phases/`; v1.5 under `milestones/v1.5-phases/`; v1.6 under `milestones/v1.6-phases/`; v1.7 under `milestones/v1.7-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **Backlog 999.2 was
> SPLIT:** its **performance half** shipped as **v1.5 — Backtest Performance Optimization**
> (2026-06-26); its **persistence half** shipped as **v1.6 — N+3b Persistence Foundation**
> (2026-06-30). **Backlog 999.3 (N+4 — Live) shipped as v1.7 — Live Trading Readiness**
> (2026-07-07; trimmed N+4 = the minimum surface to deploy live, paper-first). The whole 999.x backlog
> through N+4 is now consumed; **v1.8 — Live System Refactor & Live-Readiness Hardening** is the active
> milestone (owner's stated direction: `live_trading_system.py` God-object refactor + halt-vocabulary
> review, making the engine FastAPI-ready without building FastAPI itself).

## Active Milestone: v1.8 — Live System Refactor & Live-Readiness Hardening

**Milestone Goal:** Decompose the 2,171-line `LiveTradingSystem` God object (~17 concerns) into a thin
facade (~200 lines) over focused, independently-testable collaborators — venue-parametrized (zero
`if self.exchange == …`), config-centralized, and FastAPI-ready — **without disturbing the byte-exact
backtest oracle (`134 / 46189.87730727451`) or the OKX import-inertness gate**
(`tests/integration/test_okx_inertness.py`). Full scope: the core refactor (P1–P8 + P12) **plus** the
three ★ feature-adds (P9–P11; LR-03/LR-04). FastAPI itself is out of scope (LR-01) — this milestone
makes the engine *interfacable*, shipping no ASGI code.

**Design source:** `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` (LR-00..LR-22,
CF-1..CF-10). **Research:** `.planning/research/SUMMARY.md` (validates the design vs Nautilus/LEAN; zero
new third-party dependencies; 4 build-order refinements folded in). Requirements + traceability:
`.planning/REQUIREMENTS.md` (64 v1 requirements across 13 categories → 12 phases; the SQL + STORE
categories share the merged storage-schema phase P4).

**Milestone-wide gates (apply to EVERY phase — restated as success criteria):**

1. **Oracle byte-exact** — `SMA_MACD` stays `134 / 46189.87730727451` (`check_exact=True`), determinism
   double-run identical. This is a **per-PLAN gate** on the foundational + universe-wiring phases (P1–P4,
   P5, and **P6's `UniverseWiring` extraction** — the highest oracle-risk seam). Any re-baseline (LR-02)
   is explicit + externally cross-validated (backtesting.py + backtrader), never silent. Live-only phases
   (P7–P11) stay byte-exact because they are backtest-dark.

2. **OKX import-inertness** — `tests/integration/test_okx_inertness.py` stays green, extended to assert
   **register-vs-build** on P1/P2/P4/P5 (registering a venue imports no `ccxt.pro` until built;
   `SystemConfig` never constructs Postgres `SqlSettings` at import; `FifoEventBus`/
   `EngineContext(sql_engine=None)` pull nothing heavy). **Zero new third-party dependency / no poetry
   change** anywhere in P1–P12.

3. **Held throughout** — Decimal money end-to-end; single UUIDv7; determinism (business `time`, seeded
   RNG, injected clock); `mypy --strict` clean on new code; `filterwarnings=["error"]` green; tabs/spaces
   indentation matched to the file (never normalized).

**Trim boundary (noted, NOT taken this milestone):** P1–P8 + P12 = the core God-object refactor; **P9–P11
(★)** are the feature-adds (LR-03/LR-04) — deferrable at milestone-init without destabilizing the core.
Owner chose **full scope**, so all 12 phases are in. The ★ marker keeps the boundary visible. The ten
folded backlog TODOs (**CF-1..CF-10**) all land in core (non-★) phases (P1/P5/P6/P7/P8), so the trim
boundary is unaffected.

## Phases

**Phase Numbering:** Numbering reset to Phase 1 for v1.8 (every v1.1–v1.7 milestone reset the same way).
Integer phases are planned milestone work; decimal phases (e.g. 2.1) would be urgent insertions (marked
INSERTED). ★ = trimmable feature-add (in scope this milestone). Execution follows the dependency graph
below, not strict numeric order (P4 waits on P3; P5 on P2+P3; P6 on P4+P5; etc.).

- [x] **Phase 1: Config Centralization** - One import-safe `SystemConfig` (eager/lazy split), module-constant migration, dead-config audit, typed `HaltReason` (CFG-01..06) (completed 2026-07-09)
- [x] **Phase 2: Event Bus** - Two-tier `EventBus` Protocol (`FifoEventBus`/`PriorityEventBus`) + CONTROL EventTypes + minimal `EngineContext` skeleton (BUS-01..04) (completed 2026-07-09)
- [x] **Phase 3: EngineContext + Storage-in-Handler** - `EngineContext` threaded into `compose_engine(ctx, spec)`, handler-owns storage init, `SqlBackend→SqlEngine` rename (CTX-01..04) (completed 2026-07-09)
- [x] **Phase 4: Storage Schema: Migrations Relocation + New Durable Stores** - `migrations/` → project root FIRST, then `SystemStore`/`VenueStore`/`StrategyRegistryStore` chained on the `HaltRecordStore` template; single-head + parity Alembic gate over the FULL chain + rehydrate (SQL-01..02, STORE-01..05) (completed 2026-07-09)
- [x] **Phase 5: Venue Registry + Bundle** - Two registries, `VenuePlugin`/`VenueBundle`, precision/validate on the exchange, connector memoization, shared `StreamSupervisor` — kills every `if exchange==` (VENUE-01..07) (completed 2026-07-12)
- [x] **Phase 6: LiveRunner + Factory + Facade Shrink** - `build_live_system`, `LiveRunner`, shared `UniverseWiring` *(oracle-sensitive)*, `LiveRouteRegistrar`, ~200-line facade, replay-harness→`tests/` (`TestRunner`/`TestLiveDataProvider`; paper→OKX live feed) (RUN-01..07, TEST-01) (completed 2026-07-13)
- [ ] **Phase 7: Safety + Reconciliation + Stream Recovery** - `SafetyController`, `ReconciliationCoordinator`, `StreamRecoveryHandler`, CONTROL routes, pre-trade throttle — flag machinery deleted (SAFE-01..06)
- [ ] **Phase 8: Error Subsystem** - Injected `ErrorPolicy`, formalized `ErrorHandler`, two-guard terminal safety, CF-1 aggregate circuit breaker (ERR-01..04)
- [ ] **Phase 9 ★: Runtime-Config Platform** - `RuntimeConfig` overlay, scoped `ConfigUpdateEvent` + allowlist, restart layering, stats/state UI read-model (RTCFG-01..06)
- [ ] **Phase 10 ★: Strategies Registry** - Durable `StrategyRegistryStore` rehydrate, enable/disable via `STRATEGY_COMMAND`, atomic strategy-param reconfiguration (STRAT-01..03)
- [ ] **Phase 11 ★: Multi-Portfolio-Live** - Per-`account_id` account factory, distinct-`account_id` invariant (fail loud), per-portfolio reconcile, `clOrdId→client_order_id` (MPORT-01..06)
- [ ] **Phase 12: Test Migration + Gates** - live-smoke / config-restart / multi-portfolio-attribution gates (TEST-02..04; TEST-01 replay relocation pulled forward into P6)

## Phase Details

### Phase 1: Config Centralization

**Goal**: Centralize all system-wide configuration into one import-safe `SystemConfig` (eager fields vs a lazy `sql` accessor), fold scattered module constants into their domain config, retire dead config, and introduce a typed `HaltReason` — the backtest path reading base defaults unchanged.
**Depends on**: Nothing (first phase)
**Requirements**: CFG-01, CFG-02, CFG-03, CFG-04, CFG-05, CFG-06
**Success Criteria** (what must be TRUE):

  1. `from itrader import config` exposes immutable base defaults; the backtest reads them unchanged and the SMA_MACD oracle stays byte-exact `134 / 46189.87730727451` (per-PLAN gate, LR-02).
  2. `SystemConfig` aggregates `performance`/`monitoring`/`runtime`/`sql`/`order` with the Postgres `sql` arm resolved only on first access — importing it constructs no `SqlSettings`, so `test_okx_inertness.py` stays green (extended register-vs-build assertion).
  3. Scattered module constants fold into domain config (`_STREAM_RECONNECT_*` → `StreamSettings`/`ConnectionSettings`, `_WARMUP_MARGIN`/`_BACKFILL_PAGE` → feed/provider config); `_OKX_*`/`_PAPER_*` are gone (grep-clean) and the `extra` policy is normalized.
  4. A typed `HaltReason` enum in `core/enums/system.py` replaces free-string halt reasons and the off-vocabulary `'baseline-residual'` string is retired (CF-8).
  5. The dead-config audit removes unused settings + stale `__pycache__`, and the D-03a dual-validator paragraph is applied to `.planning/codebase/CONVENTIONS.md` (CF-6).

**Plans**: 4 plans
**Wave 1**

- [x] 01-01-PLAN.md — SystemConfig import-safety (eager `runtime` + lazy `sql`) + `extra=forbid` + dead-config audit (CFG-01/02/04)
- [x] 01-02-PLAN.md — Typed `HaltReason` enum + `baseline-residual` retirement (CFG-05)
- [x] 01-03-PLAN.md — CF-6 D-03a dual-validator paragraph → `CONVENTIONS.md` (CFG-06)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-04-PLAN.md — Constant fold: `StreamSettings`/`FeedProviderSettings` + rewire fold sites, grep-clean (CFG-03)

### Phase 2: Event Bus

**Goal**: Introduce a stdlib two-tier `EventBus` (CONTROL > BUSINESS) with FIFO and priority implementations behind one `.put()` surface, add the new CONTROL `EventType` members, and settle the `compose_engine` signature to its **end-state `(ctx, spec)` form** via a frozen `EngineContext` with **handler-owned storage** — backtest wiring `FifoEventBus` at zero oracle risk. *(Phase 2 D-03: the owner chose Option B — the end-state signature now — so **CTX-01/CTX-02/CTX-03 are pulled forward from P3 into P2**; only the `SqlBackend→SqlEngine` rename (CTX-04) stays in P3.)*
**Depends on**: Nothing
**Requirements**: BUS-01, BUS-02, BUS-03, BUS-04, CTX-01, CTX-02, CTX-03
**Success Criteria** (what must be TRUE):

  1. `FifoEventBus` (backtest) and `PriorityEventBus` (live) satisfy one `EventBus` Protocol (`put`/`get`/`get_nowait`/`qsize`/`empty`/`depth_by_tier`) sharing a single `.put(event)` surface with no handler call-site changes; backtest wires `FifoEventBus` and the oracle stays byte-exact (per-PLAN gate).
  2. A test proves `PriorityEventBus` orders `(tier, seq, event)` by a globally-unique monotonic `seq` (`itertools.count`) — the comparison never dereferences the non-orderable frozen event — and preserves strict within-tier FIFO.
  3. New CONTROL `EventType` members (`STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`) exist and are assigned CONTROL tier from a declarative `_CONTROL_EVENT_TYPES` frozenset; backtest uses `FifoEventBus` (zero priority-bus on the backtest path).
  4. A frozen `EngineContext` (`bus`/`config`/`environment`/`sql_engine`, loose types where P4/P9 tighten) settles `compose_engine(ctx, spec)` in its end-state form (CTX-01), with Order + Strategies handlers owning their storage init following `PortfolioHandler`'s shape (CTX-02) — backtest (`environment='backtest', sql_engine=None`) yields the same in-memory instances → oracle byte-exact (CTX-03, per-PLAN gate); `test_okx_inertness.py` stays green (`FifoEventBus`/`EngineContext(sql_engine=None)` pull nothing heavy; extended register-vs-build assertion).

**Plans**: 3 plans

**Wave 1** *(parallel — zero file overlap, no deps)*

- [x] 02-01-PLAN.md — Bus substrate: `EventBus` Protocol + `FifoEventBus`/`PriorityEventBus` + `_CONTROL_EVENT_TYPES` + 3 CONTROL `EventType`s + BUS-01/02/03 unit suite (BUS-01/02/03)
- [x] 02-02-PLAN.md — Handler-owned storage: `OrderHandler`/`StrategiesHandler` own storage init from `(environment, sql_engine)`, backtest slice = in-memory concretes (CTX-02)

**Wave 2** *(blocked on Wave 1 — depends on 02-01 + 02-02)*

- [x] 02-03-PLAN.md — Compose seam settle: `EngineContext` + retype-not-rename bus swap + `compose_engine(ctx, spec)` (internal queue deleted) + both backtest arms inject `EngineContext(FifoEventBus, backtest, sql_engine=None)` + extended inertness gate (BUS-01/BUS-04/CTX-01/CTX-03)

### Phase 3: EngineContext + Storage-in-Handler

**Goal**: Rename `SqlBackend` to `SqlEngine` (`storage/backend.py` → `storage/engine.py`; field/param `sql_engine`) and update all importers — `mypy --strict` clean. *(Phase 2 D-03: `EngineContext` + `compose_engine(ctx, spec)` + storage-in-handler (CTX-01/02/03) were pulled forward into P2, so P3 now carries only the mechanical `SqlBackend→SqlEngine` rename. Review at close whether this single-requirement phase folds into P2 or P4.)*
**Depends on**: Phase 1, Phase 2
**Requirements**: CTX-04
**Success Criteria** (what must be TRUE):

  1. `SqlBackend` is renamed to `SqlEngine` (`storage/backend.py` → `storage/engine.py`, field/param `sql_engine`); all importers are updated and `mypy --strict` is clean. *(EngineContext.sql_engine — loose-typed in P2 — tightens to the concrete `SqlEngine` type here.)*
  2. The backtest oracle stays byte-exact (per-PLAN gate) and factory SQL imports stay lazy, so `test_okx_inertness.py` stays green on the backtest path.

  *(CTX-01/CTX-02/CTX-03 — `compose_engine(ctx, spec)`, handler-owned storage, and the byte-exact/inertness gate — were delivered in Phase 2 per Phase 2 D-03; they are no longer P3 criteria.)*

**Plans**: 2 plans
**Wave 1**

- [x] 03-01-PLAN.md — `SqlBackend`→`SqlEngine` rename: class + module move (`storage/backend.py`→`storage/engine.py`) + `EngineContext.sql_engine` type-tighten + D-01 full `backend`→`sql_engine` vocabulary sweep across ~34 files (CTX-04, wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md — D-03 rider: collapse the redundant `signal_store` surfaces on `Engine`/`BacktestTradingSystem`; repoint accessors to read `engine.strategies_handler.signal_store` directly (wave 2)

### Phase 4: Storage Schema: Migrations Relocation + New Durable Stores

**Goal**: Land the full live storage schema as one cohesive unit — FIRST relocate the Alembic migrations tree from the shipped package to project root (staying out of the wheel), THEN add the three new durable SQL stores (`SystemStore`, `VenueStore`, `StrategyRegistryStore`) on the `HaltRecordStore` template, extending the chained migration sequence in the new location and rehydrating on restart. Live-only composition-root infrastructure that leaves the backtest path untouched. (Mechanical relocation; the `SqlBackend→SqlEngine` rename was folded into P3.)
**Depends on**: Phase 3
**Requirements**: SQL-01, SQL-02, STORE-01, STORE-02, STORE-03, STORE-04, STORE-05
**Success Criteria** (what must be TRUE):

  1. `itrader/storage/migrations/` relocates to project-root `migrations/` **first**; `alembic.ini` `script_location` is updated and `env.py` still imports the `build_*_table` registrars + `NAMING_CONVENTION` from `itrader.storage`; migrations stay out of the shipped wheel (SQL-01).
  2. `SystemStore` (cardinality 1 key-value `(key, value_json, updated_at)` namespaced upsert), `VenueStore` (per-venue config + which venues are enabled; never stores secrets), and `StrategyRegistryStore` (which strategies trade + per-strategy config + subscriptions) each compose `sql_engine` with their own `build_*_table` registrar and rehydrate their state on restart (STORE-01..04).
  3. The chained migration `d10_halt_records → system_store → venue_config → strategy_registry` is authored in the relocated `migrations/` tree, and the SQL-02 Alembic gate validates the FULL new chain — `alembic upgrade head` on a clean DB, `alembic heads == 1` (single head incl. the three new stores), and a `create_all`/migration parity test.
  4. An in-memory fallback keeps the backtest path untouched — the backtest oracle stays byte-exact (per-PLAN gate) and `test_okx_inertness.py` stays green (extended register-vs-build assertion; the relocated migrations + new stores pull nothing heavy at import).

**Plans**: 3 plans + 1 gap-remediation plan (04-04)

**Wave 1** *(parallel — zero file overlap; relocation ‖ standalone store classes)*

- [x] 04-01-PLAN.md — Migrations relocation: `git mv itrader/storage/migrations → migrations`, `alembic.ini script_location`, gate-path fix, structural wheel-exclusion assertion (SQL-01, D-10)
- [x] 04-02-PLAN.md — Three durable stores + registrars + unit tests: `SystemStore`/`VenueStore`(secret-guard)/`StrategyRegistryStore`(two-table+restart) over SQLite (STORE-01/02/03/05, D-01/03/04/05/06/07/08/09)

**Wave 2** *(blocked on 04-01 + 04-02)*

- [x] 04-03-PLAN.md — Chained migrations (`system_store → venue_config → strategy_registry`) + `env.py target_metadata` + SQL-02 single-head/upgrade/parity gate + inertness extension (SQL-02, STORE-04/05, D-02/11)

**Gap remediation** *(post-review, appended after Phase 4 close — addresses `04-REVIEW.md`; decisions in `04-GAP-DECISIONS.md`)*

- [x] 04-04-PLAN.md — WR-03: remove `create_all` from 7 durable-store constructors (results store excluded per D-14) + shared `provision_schema` test fixture; WR-02: dialect-guarded `PRAGMA foreign_keys=ON` on `SqlEngine` + FK-enforcement test; IN-01: deterministic `ORDER BY` on `StrategyRegistryStore.read_all` (SQL-02, STORE-01/02/03/04/05)

### Phase 5: Venue Registry + Bundle

**Goal**: Build two independent registries (execution venue + data provider) plus a `VenuePlugin`/`VenueBundle` system with lazy plugins that parametrize every venue — killing every `if exchange==` — with connector memoization by `(venue, account_id)`, precision/validate as exchange capabilities, a per-portfolio account factory, and a shared `StreamSupervisor`.
**Depends on**: Phase 2, Phase 3
**Requirements**: VENUE-01, VENUE-02, VENUE-03, VENUE-04, VENUE-05, VENUE-06, VENUE-07
**Success Criteria** (what must be TRUE):

  1. `ExecutionVenueRegistry` + `DataProviderRegistry` select execution venue and data provider independently via `SystemSpec`; registering `'okx'` lazy-imports its concretions only inside `build_bundle`, so `test_okx_inertness.py` (the P5 acceptance gate; register-vs-build) stays green.
  2. Precision + validation become `AbstractExchange` capabilities (`resolve_precision(symbol)`, `validate_symbol(symbol)`); `_OkxPrecisionResolver`/`_PrecisionResolver` are deleted and `_precision_to_scale` becomes a shared money util.
  3. A `LiveDataProvider` Protocol (+ `BaseLiveDataProvider` no-op defaults) wires every provider uniformly (no `hasattr` sprinkling), and a `VenueLifecycle` orchestrator None-guards absent members so every `if exchange=='okx'` / `elif =='paper'` is removed.
  4. A shared `StreamSupervisor` replaces the triplicated `_run_stream_supervisor` + `_STREAM_RECONNECT_*` (CF-4); connector-contract docstrings are added to `connectors/base.py` (CF-3); OKX markets-map freshness closes the fail-open-before-load window via the existing `validate_symbol` → removal path (CF-9).
  5. Connectors are memoized by `(venue, account_id)` with per-`account_id` env-sourced credentials never persisted; the backtest oracle stays byte-exact (per-PLAN gate).

**Plans**: 6 plans (4 waves)

**Wave 1** *(parallel — no shared files)*

- [x] 05-01-PLAN.md — VENUE-07: shared `StreamSupervisor` (parameterized, replaces 3 forks) + CF-3 connector docstrings + CF-9 fail-closed `validate_symbol` (VENUE-07)
- [x] 05-03-PLAN.md — VENUE-05: `LiveDataProvider` Protocol + `BaseLiveDataProvider` no-op defaults; `ReplayDataProvider` inherits it (VENUE-05)

**Wave 2** *(05-02 blocked on 05-01 via okx.py; 05-04 blocked on 05-03 via LiveDataProvider)*

- [x] 05-02-PLAN.md — VENUE-04: `resolve_precision` as an `AbstractExchange` capability + `precision_to_scale` money util + universe-handler resolver rewire (Drift 1) (VENUE-04)
- [x] 05-04-PLAN.md — VENUE-01/02/03: two registries + `VenueBundle`/plugin Protocols + `ConnectorProvider` `(venue, account_id)` memo + `SystemSpec` selectors (VENUE-01/02/03)

**Wave 3** *(blocked on 05-04 + 05-03)*

- [x] 05-05-PLAN.md — VENUE-02: OKX + paper venue/data/connector plugins (triple-deferral-lazy) + inertness register-vs-build extension (VENUE-02)

**Wave 4** *(blocked on 05-05 + 05-04 + 05-03 + 05-02)*

- [x] 05-06-PLAN.md — VENUE-06: `VenueLifecycle` + `assemble_venue` seam + delete every `if exchange==` branch in `LiveTradingSystem` (VENUE-06)

### Phase 6: LiveRunner + Factory + Facade Shrink

**Goal**: Make `build_live_system` the live composition root over a new `LiveRunner`, shrinking `LiveTradingSystem` to a ~200-line facade — with the shared `UniverseWiring` extracted byte-exact (the highest oracle-risk seam) and reused by both runners, and live routes composed declaratively.
**Depends on**: Phase 4, Phase 5
**Requirements**: RUN-01, RUN-02, RUN-03, RUN-04, RUN-05, RUN-06, RUN-07, TEST-01 *(TEST-01 pulled forward from P12 — same construction path P6 builds; kills the production-replay tax across P7–P11)*
**Success Criteria** (what must be TRUE):

  1. The shared `UniverseWiring` helper (`derive_membership → build Universe → inject exchange/order/portfolio/strategies → feed.bind`, incl. the WR-03 desync assert) is extracted as one intact unit and reused by both `BacktestRunner` and the live `SessionInitializer` — **BacktestRunner stays byte-exact `134 / 46189.87730727451`** (per-PLAN gate on the `UniverseWiring` extraction; the milestone's highest oracle risk).
  2. `build_live_system(spec)` assembles centralized config → one `sql_engine` → venue plugin(s) → `EngineContext` (wiring live onto the `PriorityEventBus`) → `compose_engine` → bundle(s) + `LiveRunner` + controllers; `LiveRunner` owns the drain loop + injected `ErrorPolicy` + worker supervision, replacing `_event_processing_loop`. CONTROL routes are NOT registered in P6 (their P7/P9 consumers don't exist yet); the `LiveRouteRegistrar` registers the BUSINESS/live routes and P7/P9 add CONTROL entries through it.
  3. `LiveTradingSystem` shrinks to a ~200-line facade (lifecycle, status/read-model, `add_event`); legacy `print_status`/`get_statistics` are dropped and `__init__` sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time`.
  4. `LiveRouteRegistrar` composes live + CONTROL routes declaratively (list order = execution order; no subclass, no runtime mutation) with backtest getting base routes only; `UniverseHandler` is a first-class handler with explicit deps and zero OKX coupling; `StrategyWarmupConsumer` is rehomed sized to `max(strategy.warmup)` with the CF-10 depth-hint seam shaped (K-computation deferred).
  5. `test_okx_inertness.py` stays green (live decomposition imports no `ccxt.pro` on the backtest path).
  6. **TEST-01 (pulled forward from P12):** the ENTIRE replay test-harness moves OUT of the `itrader` package into `tests/` — `run_paper_replay` → **`TestRunner`**, `ReplayDataProvider` → **`TestLiveDataProvider`**, `ReplayDataPlugin` → **`TestDataPlugin`** (test-fixture-registered-only), `PAPER_PARITY_*`/`_PAPER_*` → `tests/`; production is replay-free. The `paper` EXECUTION venue (`PaperVenuePlugin` + `SimulatedExchange` + `SimulatedAccount`) STAYS a **real live production mode, untouched** — its production data feed re-points from `replay` to the **OKX live feed** (`{'okx':'okx','paper':'okx'}`), so the `paper`↔replay pairing survives only in the test fixture. `TestRunner` is **fail-fast by default** (drives the EventHandler at its default fail-fast seam, never calls `start()`). `Test*`-named classes set `__test__ = False` (pytest-collection guard under `filterwarnings=["error"]`). Done as pure code-motion with `test_paper_parity` green continuously, sliced as its own plan AFTER the `UniverseWiring` extraction locks (per-PLAN oracle gate).

**Plans**: 7 plans

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — RUN-04: extract shared `wire_universe(engine)` (oracle-gated, isolated); repoint BacktestRunner (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-02-PLAN.md — RUN-02: `LiveRunner` + `WorkerSupervisor` + minimal `ErrorPolicy` (new standalone modules) (wave 2)
- [x] 06-03-PLAN.md — RUN-07: rehome `StrategyWarmupConsumer` + `register_strategy_warmup` + named `derive_warmup_depth` (CF-10 seam) (wave 2)
- [x] 06-04-PLAN.md — RUN-06: `UniverseHandler` first-class ctor `(bus, universe, feed, config)` + `set_venue_metadata`; caller migration (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 06-05-PLAN.md — RUN-05 + RUN-04(live): `LiveRouteRegistrar` + `SessionInitializer`; `_initialize_live_session` delegates (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 06-06-PLAN.md — RUN-01 + RUN-03: `build_live_system` factory + pure-injection facade + PriorityEventBus + `for_exchange` + ~45-site sweep (wave 4)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 06-07-PLAN.md — TEST-01: replay harness → `tests/support/` (`TestRunner`/`TestLiveDataProvider`/`TestDataPlugin`); production replay-free, paper→OKX (wave 5)

### Phase 7: Safety + Reconciliation + Stream Recovery

**Goal**: Extract a pure `SafetyController` state machine, a `ReconciliationCoordinator`, and a `StreamRecoveryHandler`; convert connector stream/fatal handoff into CONTROL events (flag side-channel deleted); and add a pre-trade submit-rate + max-notional throttle.
**Depends on**: Phase 6
**Requirements**: SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05, SAFE-06
**Success Criteria** (what must be TRUE):

  1. A pure `SafetyController` (no venue I/O) owns the status latch (`VALID_STATUS_TRANSITIONS`, single `update_status`, `force=` reserved for `reset_halt`), `halt(reason)` (winner-only → CRITICAL `ErrorEvent` → durable `HaltRecordStore.record_halt`), `pause_submission`/`resume_submission` + a bounded deferred-protective queue, and the dispatch gate; `check_durable_halt_on_start()` runs first (before any venue I/O) and refuses RUNNING on an unresolved durable halt.
  2. Connector stream up/down + fatal arrive as CONTROL events (`StreamStateEvent` → pause / `StreamRecoveryHandler.on_reconnect`; `ConnectorFatalEvent` → `halt`) on the engine thread; the `_pending_stream_resume`/`_pending_connector_halt` flag side-channel is deleted.
  3. `StreamRecoveryHandler` owns reconnect resume I/O (catch-up missed fills + account snapshot on the engine thread + all-streams-healthy gate → `resume_submission`), with CF-2 `backfill_on_resume` landing **loop-native** (connector loop via the reconnect callback) and an assertion no engine-thread path reaches the ring writer.
  4. A pre-trade submit-rate + max-notional-per-order throttle (SAFE-06) rejects order flow exceeding configured velocity/notional caps **before** submission; the `ReconciliationCoordinator` keys on account *kind* (not `exchange=='okx'`) and guards the bare `str(matched["id"])` with a typed fail-loud error (CF-7).
  5. The backtest oracle stays byte-exact (live-only, backtest-dark) and `test_okx_inertness.py` stays green.

**Plans**: TBD

### Phase 8: Error Subsystem

**Goal**: Inject an `ErrorPolicy` into `EventHandler` (removing the monkeypatch), formalize the `ErrorHandler` ERROR-route consumer with two-guard terminal safety, and ship the CF-1 aggregate circuit breaker that actually trips — all leaving backtest fail-fast byte-for-byte unchanged.
**Depends on**: Phase 6
**Requirements**: ERR-01, ERR-02, ERR-03, ERR-04
**Success Criteria** (what must be TRUE):

  1. An `ErrorPolicy` is injected into `EventHandler` at construction (backtest/replay → fail-fast re-raise; live → publish-and-continue) with per-handler granularity preserved and the WR-06 source guard; the backtest fail-fast path is byte-for-byte unchanged and the oracle stays byte-exact.
  2. The **CF-1 aggregate circuit breaker** (route-classified ring: SETTLEMENT halt-on-first, ORDER-IO N=3/60s, ADMISSION N=3/300s, LOOP-BACKSTOP N=5/60s) **actually trips** — proven by a "money route failing every event" test — while preserving the WR-06 terminal swallow (hard acceptance criterion).
  3. `ErrorHandler` formalizes the ERROR-route consumer (severity-mapped structured logging, CRITICAL → the pluggable alert-sink seam CF-5, persist latest error → `SystemStore state.last_error`, WR-06 consumer guard); handler failures, `halt()` (CRITICAL), `PortfolioErrorEvent`, and `ConnectorFatalEvent` all funnel through the one ERROR route.
  4. `test_okx_inertness.py` stays green.

**Plans**: TBD

### Phase 9 ★: Runtime-Config Platform

**Goal**: Build a durable, restart-surviving runtime-config platform — a `RuntimeConfig` overlay injected as `EngineContext.config`, a scoped `ConfigUpdateEvent` gated by an allowlist with venue-kind-aware validation — plus the SystemStore stats/state UI read-model. (★ trimmable feature-add; in scope this milestone.)
**Depends on**: Phase 4, Phase 7
**Requirements**: RTCFG-01, RTCFG-02, RTCFG-03, RTCFG-04, RTCFG-05, RTCFG-06
**Success Criteria** (what must be TRUE):

  1. A `RuntimeConfig` overlay (`defaults ← YAML ← env ← persisted runtime overrides`) is built by the live factory and injected as `EngineContext.config` (engine-thread-write, snapshot-read); handlers read it and see runtime changes.
  2. A scoped `ConfigUpdateEvent(scope, key, value)` on the CONTROL plane is validated against an allowlist + type/range, routed on the engine thread to the owning store (`system`→SystemStore, `portfolio:{id}`→Portfolio+portfolio store, `venue:{name}`→VenueStore, `order`→SystemStore), applied to the overlay + relevant `handler.update_config(...)`, and persisted; immutable-at-runtime keys (`rng_seed`, money precision, SQL + venue credentials, `environment`, IDs) are rejected.
  3. Fee/slippage config keys are runtime-mutable **only for simulated venues** — a `ConfigUpdateEvent` targeting a live venue's fee/slippage is rejected (venue-kind-aware validation, RTCFG-05).
  4. Persisted overrides survive restart (`build_live_system` layers them over defaults on boot), and the `system_store` `stats.snapshot` + `state.*` (status / halt_reason / last_error / last_started_at) serve as the UI read-model without touching hot-path locks (RTCFG-06).
  5. The backtest oracle stays byte-exact and `test_okx_inertness.py` stays green.

**Plans**: TBD

### Phase 10 ★: Strategies Registry

**Goal**: Make the strategy roster durable — a `StrategyRegistryStore` that survives restart, with runtime add/remove/enable/disable via `STRATEGY_COMMAND` and atomic strategy-parameter reconfiguration. (★ trimmable feature-add; in scope this milestone.)
**Depends on**: Phase 4, Phase 6
**Requirements**: STRAT-01, STRAT-02, STRAT-03
**Success Criteria** (what must be TRUE):

  1. `StrategyRegistryStore` persists which strategies are active + config + subscriptions; on restart `build_live_system` rehydrates it and re-registers the active strategies (survives restart).
  2. Runtime add / remove / enable / disable via `STRATEGY_COMMAND` (CONTROL) is applied by `StrategiesHandler` and persisted.
  3. A strategy's config parameters are mutable at runtime via **atomic reconfiguration** (quiesce → apply → re-warmup the affected strategy), persisted to `StrategyRegistryStore` (STRAT-03; folds `pair-strategy-live-reconfiguration.md`).
  4. The backtest oracle stays byte-exact (live-only, backtest-dark) and `test_okx_inertness.py` stays green.

**Plans**: TBD

### Phase 11 ★: Multi-Portfolio-Live

**Goal**: Let multiple portfolios trade live independently — a per-`account_id` account factory replacing the single-portfolio guard, a distinct-`account_id` invariant that fails loud, per-portfolio reconciliation, and two-key attribution (`client_order_id` vs `portfolio_id`). (★ feature-add — LR-03 mandate, never trim.)
**Depends on**: Phase 5, Phase 7
**Requirements**: MPORT-01, MPORT-02, MPORT-03, MPORT-04, MPORT-05, MPORT-06
**Success Criteria** (what must be TRUE):

  1. The venue plugin's `new_account(portfolio_ref, config)` mints a per-portfolio account (venue-truth → `VenueAccount` scoped to `portfolio.account_id`; compute → a fresh `SimulatedAccount`); `_link_venue_account_to_portfolios` + its `RuntimeError(>1)` guard are deleted, and `PortfolioSpec` gains `account_id`.
  2. A distinct-`account_id` invariant fails **loud** at composition time — multiple portfolios sharing one venue `account_id` is rejected (pooled buying power the venue can't split is deferred).
  3. A signal fans out to each subscribed portfolio, each sizing/ordering independently against its own account; `clOrdId` is renamed `client_order_id` (distinct from `portfolio_id`) and fills route via `client_order_id`/`venue_order_id` → engine order → `FillEvent(portfolio_id)` → the right `Portfolio.on_fill`.
  4. Connectors are keyed `(venue, account_id)` (VENUE-03) so multi-account portfolios share/decouple correctly, and the `ReconciliationCoordinator` iterates active portfolios reconciling each against its own `VenueAccount`/`account_id`.
  5. The backtest oracle stays byte-exact and `test_okx_inertness.py` stays green.

**Plans**: TBD

### Phase 12: Test Migration + Gates

**Goal**: Add the live-smoke, config-restart, and multi-portfolio-attribution gates that lock the decomposed live surface. Lands last (needs the whole surface incl. multi-portfolio). *(TEST-01 — the replay-driver relocation to `tests/` — was pulled forward into P6; P12 now inherits replay-free production and only adds the surface-dependent gates.)*
**Depends on**: Phase 6, Phase 11
**Requirements**: TEST-02, TEST-03, TEST-04 *(TEST-01 delivered in P6)*
**Success Criteria** (what must be TRUE):

  1. *(TEST-01 delivered in P6 — production is already replay-free: `run_paper_replay` → `tests/` `ReplayRunner`, `replay` plugin fixture-registered-only. P12 inherits this; no P12 action.)*
  2. A live-smoke gate exercises the decomposed live surface end-to-end (facade → factory → `LiveRunner` → controllers) on the replay fixture.
  3. A config-restart gate proves persisted runtime overrides survive a restart (RTCFG-03).
  4. A multi-portfolio attribution gate proves fills route to the correct portfolio and the distinct-`account_id` invariant fails loud (MPORT-02/MPORT-04).
  5. The backtest oracle stays byte-exact and `test_okx_inertness.py` stays green.

**Plans**: TBD

## Progress (v1.8 — active)

**Execution Order (dependency graph, not strict numeric):**
`P1 · P2 → P3 → P4` and `P3 → {P5}` with `P2 → P5`; `{P4,P5} → P6 → {P7, P8}`;
`{P4,P7} → P9 ★`; `{P4,P6} → P10 ★`; `{P5,P7} → P11 ★`; `{P6,P11} → P12`.
P1 and P2 have no dependencies and can start in parallel.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Config Centralization | v1.8 | 4/4 | Complete    | 2026-07-09 |
| 2. Event Bus | v1.8 | 3/3 | Complete    | 2026-07-09 |
| 3. EngineContext + Storage-in-Handler | v1.8 | 2/2 | Complete    | 2026-07-09 |
| 4. Storage Schema: Migrations Relocation + New Durable Stores | v1.8 | 4/4 | Complete    | 2026-07-10 |
| 5. Venue Registry + Bundle | v1.8 | 6/6 | Complete    | 2026-07-12 |
| 6. LiveRunner + Factory + Facade Shrink | v1.8 | 7/7 | Complete    | 2026-07-13 |
| 7. Safety + Reconciliation + Stream Recovery | v1.8 | 0/TBD | Not started | - |
| 8. Error Subsystem | v1.8 | 0/TBD | Not started | - |
| 9 ★. Runtime-Config Platform | v1.8 | 0/TBD | Not started | - |
| 10 ★. Strategies Registry | v1.8 | 0/TBD | Not started | - |
| 11 ★. Multi-Portfolio-Live | v1.8 | 0/TBD | Not started | - |
| 12. Test Migration + Gates | v1.8 | 0/TBD | Not started | - |

## Phases (shipped — archived detail)

<details>
<summary>✅ v1.7 — Live Trading Readiness (Phases 1-7 + 05.1/05.2/05.3) — SHIPPED 2026-07-07</summary>

Phase numbering reset to Phase 1 (matching v1.1–v1.6). Promoted Backlog 999.3 (N+4, trimmed). The
engine's first **live operating mode — paper-first on OKX** — landed **without disturbing the byte-exact
backtest oracle** (134 / `46189.87730727451`): an `Account` abstraction (oracle-gated extraction), an
`OkxConnector` (one session + data/trading/account adapters), a streaming `LiveBarFeed`, the paper path
(the DoD, gated on **paper-parity vs a fresh backtest** — frame-exact), a reconciled real/sandbox path
**human-observed GREEN on the OKX demo venue** (a real fill settling into position + cash) with a durable
restart-real ledger and three remediation waves (05.1 settlement / 05.2 restart-real / 05.3 resilience),
and a poll-driven dynamic universe hardened with async warmup + per-symbol readiness gating. The
live/connector machinery is provably inert on the backtest hot path (import-quarantine subprocess probe).
All 32 requirements satisfied; audit `passed` (0 blockers; one owner-gated oracle-dark defect deferred —
margin-equity WR-01). `mypy --strict` clean (234 files), non-live suite 1981 passed. Full detail in
[`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md).

- [x] Phase 1: Account Abstraction + Portfolio/Handler Refactor (7/7 plans) — completed 2026-06-30
- [x] Phase 2: OKX Connector (5/5 plans) — completed 2026-07-04
- [x] Phase 3: LiveBarFeed (4/4 plans) — completed 2026-07-01
- [x] Phase 4: Paper Path (milestone DoD) (4/4 plans) — completed 2026-07-02
- [x] Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive (13/13 plans) — completed 2026-07-04
- [x] Phase 05.1: Live-Path Remediation — CONF-A + Wave 1 (INSERTED) (9/9 plans) — completed 2026-07-05
- [x] Phase 05.2: Live-Path Remediation — Wave 2 / Restart Real (INSERTED) (6/6 plans) — completed 2026-07-06
- [x] Phase 05.3: Live-Path Remediation — Wave 3 / Resilience Hardening (INSERTED) (12/12 plans) — completed 2026-07-06
- [x] Phase 6: Dynamic Universe Membership (5/5 plans) — completed 2026-07-06
- [x] Phase 7: Live Dynamic-Universe Hardening (10/10 plans) — completed 2026-07-07

</details>

<details>
<summary>✅ v1.6 — N+3b Persistence Foundation (Phases 1-5) — SHIPPED 2026-06-30</summary>

Phase numbering reset to Phase 1 (matching v1.1–v1.5). Promoted the **persistence half** of Backlog
999.2 (its performance half shipped as v1.5). A **DB-gated** milestone — NOT covered by the backtest
oracle alone — that built the durable-storage + caching foundation N+4 will inherit, **without
disturbing the backtest path**: a swappable SQL spine (SQLite research + Postgres operational,
Turso-ready, driver NOT added per Owner Decision) composed (not inherited) by all four storage concerns;
an all-SQL results store (#1); concrete Postgres backends for the three operational seams (#2); a
two-knob write-through + retention model with restart rehydration; and a classified cache (#3). Every
phase carried a two-part gate: (a) SMA_MACD oracle byte-exact (134 / `46189.87730727451`) with no W1/W2
regression vs the v1.5 baseline (15.7 s / 152.8 MB) — proven inert by an import-quarantine subprocess
test, W1 measured −2.8% — AND (b) the phase's own DB round-trip / rehydration / parity tests on the right
substrate (in-process SQLite for #1, testcontainers Postgres for #2). Held throughout: Decimal money on
the live path (Postgres-native `Numeric`), single UUIDv7, determinism, `mypy --strict` clean (210 files),
`filterwarnings=["error"]` green (suite 1463). All 20 requirements satisfied; audit `tech_debt` (no
blockers; live composition-root wiring deferred to N+4 per RETAIN-03/D-01 — now promoted into v1.7 Phase 5).
Full detail in [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md).

- [x] Phase 1: SQL Spine + Security Hardening (5/5 plans) — completed 2026-06-27
- [x] Phase 2: Results Store (#1) (4/4 plans) — completed 2026-06-29
- [x] Phase 3: Operational SQL Backends (#2) (5/5 plans) — completed 2026-06-29
- [x] Phase 4: Retention + Live Write-Through (#2 live path) (4/4 plans) — completed 2026-06-30
- [x] Phase 5: Cache Classification (#3) (3/3 plans) — completed 2026-06-30

</details>

<details>
<summary>✅ v1.5 — Backtest Performance Optimization (Phases 1-8) — SHIPPED 2026-06-26</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3/v1.4). The performance analog of v1.2
Consolidation: a **behavior-preserving** milestone that cut the W1 hot path via profiler-ranked,
oracle-gated optimizations — **changing no numbers**. The byte-exact SMA_MACD oracle held at 134
trades / `final_equity 46189.87730727451` across all 8 phases (Phase 5 carried a deliberate
re-baseline carve-out that proved unnecessary — the oracle stayed byte-exact). Every optimization
phase was gated on BOTH (a) the oracle staying green AND (b) a measured same-machine-A/B W1
wall-clock improvement, re-frozen after the phase. Held throughout: `mypy --strict` clean; Decimal
end-to-end (every fix is *less repeated work*, never a float swap); single UUIDv7; determinism
double-run byte-identical; full suite 1340/1340 green. Final W1 baseline re-frozen at **15.7 s /
152.8 MB** (absolute pre/post numbers are not directly comparable across the milestone because the
Phase-1 benchmark-probe quadratic bug was fixed mid-milestone; per-phase wins were attributed by
same-machine A/B, not the frozen-baseline diff). Phases 7-8 were added 2026-06-25 from post-phase
re-profiles (PERF-07/PERF-08; the originally-deferred items under those IDs were renumbered
PERF-09/PERF-10 at close). Source: the v1.5 spike
[`perf/results/PERF-BASELINE-RESULTS.md`](../perf/results/PERF-BASELINE-RESULTS.md). Full detail in
[`milestones/v1.5-ROADMAP.md`](./milestones/v1.5-ROADMAP.md).

- [x] Phase 1: Perf Tooling & Baseline (2/2 plans) — completed 2026-06-23
- [x] Phase 2: Order-Storage Indexing (2/2 plans) — completed 2026-06-23
- [x] Phase 3: Running PnL Accumulator (2/2 plans) — completed 2026-06-24
- [x] Phase 4: Hot-Path Discipline (3/3 plans) — completed 2026-06-24
- [x] Phase 5: Stateful Indicators + Shared Bar Cache (FRAGILE, LAST) (3/3 plans) — completed 2026-06-25
- [x] Phase 6: Bar-Feed Window Copies (OPTIONAL) (5/5 plans) — completed 2026-06-24
- [x] Phase 7: Per-Bar Metrics & Timestamp Polish (BYTE-EXACT) (3/3 plans) — completed 2026-06-25
- [x] Phase 8: Hot-Path Fusion, Bar Prebuild & msgspec (BYTE-EXACT) (6/6 plans) — completed 2026-06-26

</details>
<details>
<summary>✅ v1.4 — Margin, Leverage, Shorts & Trailing Stops (Phases 1-6 + 5.1) — SHIPPED 2026-06-22</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3). The crypto-derivatives surface —
per-symbol instruments, reserved-margin leverage, first-class shorts + borrow carry, isolated-margin
liquidation, engine-native trailing stops, short scale-in, and a market-neutral pair flagship. An
**owner-gated, result-changing** milestone: the three result-changing re-baselines (accounting core
P4, trailing P5, scale-in P5.1) were each frozen ONLY under explicit owner sign-off (tiziaco) +
external cross-validation (`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123); the SMA_MACD spot oracle
held byte-exact (134 trades / `final_equity 46189.87730727451`) across all 7 phases; `mypy --strict`
clean, Decimal end-to-end, determinism double-run byte-identical. Full detail in
[`milestones/v1.4-ROADMAP.md`](./milestones/v1.4-ROADMAP.md).

- [x] Phase 1: Instrument Value Object (3/3 plans) — completed 2026-06-15
- [x] Phase 2: Margin Accounting & Leverage (9/9 plans) — completed 2026-06-15
- [x] Phase 3: Shorts & Borrow Carry (6/6 plans) — completed 2026-06-15
- [x] Phase 4: Liquidation & Cross-Validation Re-baseline (6/6 plans) — completed 2026-06-16
- [x] Phase 5: Engine-Native Trailing Stops (5/5 plans) — completed 2026-06-17
- [x] Phase 5.1: Short Position Scale-In (INSERTED) (2/2 plans) — completed 2026-06-17
- [x] Phase 6: Pair-Trading Flagship (4/4 plans) — completed 2026-06-22

</details>

<details>
<summary>✅ v1.3 — Engine Surface Completion (Phases 1-6) — SHIPPED 2026-06-14</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2). Completes the signal/order contracts, the
composition/config interface, and the declared-indicator + strategy-authoring surface — the
result-changing / new-framework items deferred out of v1.2 Consolidation (promoted Backlog 999.5).
Two re-baseline disciplines, both honored: byte-exact phases (1-4) held the v1.1 E2E golden suite +
BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) byte-for-byte; owner-gated phases
(5-6) re-baselined only under explicit owner sign-off (tiziaco, 2026-06-13) + external
cross-validation. Full detail in [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md).

- [x] Phase 1: Engine Hygiene (1/1 plan) — completed 2026-06-12
- [x] Phase 2: Strategy Authoring Surface (3/3 plans) — completed 2026-06-12
- [x] Phase 3: Declared-Indicator Framework (3/3 plans) — completed 2026-06-12
- [x] Phase 4: Composition & Config Interface (5/5 plans) — completed 2026-06-12
- [x] Phase 5: Signal Contract & Reconcile (FRAGILE) (4/4 plans) — completed 2026-06-13
- [x] Phase 6: Order Lifecycle & Time-in-Force (4/4 plans) — completed 2026-06-13

</details>

<details>
<summary>✅ v1.0 — Backtest-Correctness Refactor (Phases 1-8) — SHIPPED 2026-06-08</summary>

8 phases (M1 → M5c), 62 plans. `SMA_MACD` runs end-to-end producing correct, deterministic,
cross-validated numbers (134 trades / `final_equity 46189.87730727451`). Full detail in
[`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md).

</details>

<details>
<summary>✅ v1.1 — Backtest Trustworthiness: Breadth (Phases 1-9) — SHIPPED 2026-06-10</summary>

Phase numbering reset to Phase 1 for v1.1. Spine: codebase map → data → universe → E2E
framework → interface hardening → scenario waves. LONG-ONLY throughout; behavior-preserving
(v1.0 golden numbers NOT re-baselined). Full detail in
[`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md).

- [x] Phase 1: Codebase Map & Clarity Baseline (2/2 plans) — completed 2026-06-09
- [x] Phase 2: Data Ingestion (1/1 plan) — completed 2026-06-09
- [x] Phase 3: Minimal Real Universe (3/3 plans) — completed 2026-06-09
- [x] Phase 4: E2E Harness & Framework (3/3 plans) — completed 2026-06-09
- [x] Phase 5: Strategy Interface Hardening & Signal Storage (3/3 plans) — completed 2026-06-09
- [x] Phase 6: Order Matching Scenarios (5/5 plans) — completed 2026-06-09
- [x] Phase 7: Cost, Sizing & SLTP Scenarios (4/4 plans) — completed 2026-06-10
- [x] Phase 8: Admission, Position Management & Cash Edges (3/3 plans) — completed 2026-06-10
- [x] Phase 9: Multi-Entity, Robustness & Metrics Edges (4/4 plans) — completed 2026-06-10

</details>

<details>
<summary>✅ v1.2 — Consolidation (Phases 1-6) — SHIPPED 2026-06-12</summary>

Behavior-preserving cleanup milestone — cleared the v1.1 cleanup-review backlog
(`V1.2-CLEANUP-REVIEW.md`, 46 findings) + the `CONCERNS.md` dead/fragile/tangled debt, byte-exact
against the golden master (134 trades / `final_equity 46189.87730727451`); re-baselined nothing.
Headline: `order_manager.py` decomposed 1279 → 210-line coordinator as pure code-motion. Full detail
in [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md).

- [x] Phase 1: Dead Code & Doc Hygiene (2/2 plans) — completed 2026-06-11
- [x] Phase 2: Locked-Decision Conformance (3/3 plans) — completed 2026-06-11
- [x] Phase 3: Hot-Path Performance (4/4 plans) — completed 2026-06-11
- [x] Phase 4: Type Modeling (5/5 plans) — completed 2026-06-11
- [x] Phase 5: Naming & Encapsulation (4/4 plans) — completed 2026-06-11
- [x] Phase 6: Order-Manager Decomposition (5/5 plans) — completed 2026-06-11

</details>

## Progress

Milestones through v1.7 are shipped and archived under `milestones/`. **v1.8 — Live System Refactor &
Live-Readiness Hardening is the active milestone** (12 phases, 64 requirements; roadmap created
2026-07-09, revised to 12 phases 2026-07-09 — old P4 SqlEngine Migrations Relocation folded into old P5
New Durable Stores → merged storage-schema phase P4). Per-phase v1.8 status is tracked in the
**Progress (v1.8 — active)** table above.

**Milestone summary** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |
| v1.4 — Margin, Leverage, Shorts & Trailing Stops | 1-6 + 5.1 | 35 | ✅ Shipped | 2026-06-22 |
| v1.5 — Backtest Performance Optimization | 1-8 | 26 | ✅ Shipped | 2026-06-26 |
| v1.6 — N+3b Persistence Foundation | 1-5 | 21 | ✅ Shipped | 2026-06-30 |
| v1.7 — Live Trading Readiness | 1-7 + 05.1/05.2/05.3 | 75 | ✅ Shipped | 2026-07-07 |
| v1.8 — Live System Refactor & Live-Readiness Hardening | 1-12 | TBD | 🚧 In progress | - |

**Next:** `/gsd:plan-phase 1` (Config Centralization) — or plan P1 and P2 in parallel (both dependency-free).

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> Promote one at a time with `/gsd:review-backlog` (or start via `/gsd:new-milestone`); defer detailed
> planning until promotion so each milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **Backlog 999.2 is SPLIT and fully consumed** (performance half → v1.5 2026-06-26; persistence half →
> v1.6 2026-06-30). **Backlog 999.3 (N+4 — Live Trading Readiness) SHIPPED as v1.7** (2026-07-07,
> trimmed N+4). The historical 999.3 seed below is retained as the source intent (like 999.2 → v1.5/v1.6
> and 999.4 → v1.4). Do not re-plan from here — the shipped detail is in the **Phases (shipped — archived
> detail)** section above + [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md).

### Next up (post-v1.8): FastAPI application layer

> **The downstream consumer of v1.8.** v1.8 makes the engine *interfacable* (clean control/query seams,
> event ingress, centralized + runtime config, durable stores, stats/state read-model) but ships **no**
> FastAPI app / routes / ASGI code (LR-01). The FastAPI application-layer milestone consumes those stable
> seams. Design context: MEMORY `fastapi-application-layer-plan.md`. Do not fold into v1.8.

### v1.8 deferred platform seams (carried, not built — spec §14)

> Marked seams the v1.8 two-registry / multi-portfolio decoupling *enables* but does not build:
> multi-provider **feed-router** (`set_provider` → provider-router keyed by symbol/asset-class),
> **single-connector-multi-`account_id`** optimization (OKX master key + per-account routing on one
> session), **shared-`account_id` risk allocator** (portfolios pooling one venue account), config
> **audit-trail table** (`system_config_audit`), **errors-history table**, and a **stats-history table
> split**. See `.planning/REQUIREMENTS.md` → v2/Future.

### Phase 999.3: N+4 — Live Trading Readiness (SHIPPED-AS-v1.7 — historical seed)

> **SHIPPED as v1.7 (2026-07-07).** This backlog entry shipped as the **v1.7 — Live Trading Readiness
> (trimmed N+4)** milestone — 10 phases, 32 requirements (full detail in
> [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md)). The trimmed scope = the minimum surface to deploy
> live, paper-first on OKX. The locked design (`docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md`,
> LX-01..LX-15) supersedes the broad seed below where they differ (e.g. Perp realism Phase B / full
> production screener / multi-venue are explicitly DEFERRED out of v1.7 to v2). The seed is retained as
> the historical record.

**Goal (original seed):** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence v1.6), and a streaming data engine.

Scope (intent only — see [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md) for the trimmed, shipped scope):

- **#6 real-time data engine** ready for live. → v1.7 Phase 3 (`LiveBarFeed`).
- **#2 live execution engine.** → v1.7 Phases 2/4/5 (`OkxConnector` session + `OkxExchange` / paper `AbstractExchange` adapter / real path).
- **#7 production-ready universe / screener.** → DEFERRED to v2 (v1.7 ships only the lean poll seam, Phase 6).
- **Dynamic universe membership** — lean `UniverseSelectionModel` poll seam for mid-run adds/removes;
  warmup-on-add + open-position-handling-on-remove. → v1.7 Phase 6.

- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage. → v1.7 COV-01 (Phase 4, extends to 5).
- **Perp realism — "Phase B" (FUND-01..04, deferred out of v1.4)** — funding-rate accrual, mark-price
  liquidation trigger, funding-data pipeline, `freqtrade` 4th cross-validation oracle. → DEFERRED to v2
  (out of v1.7 trimmed scope; its own future milestone).

- **Account abstraction (born here, with the connector)** — first-class `Account` as the reconciled
  local mirror of venue balance/margin truth; `CashAccount` vs `MarginAccount`; 1 account : 1 portfolio;
  `user_id` stripped from the engine (app-layer concern). → v1.7 Phase 1 (`Account` abstraction,
  `Simulated*`/`Venue*` leaves, `user_id` strip) + Phase 5 (`VenueAccount` reconciliation).

- **Live-start indicator backfill through the same `update(bar)` path** (deferred out of v1.5 Phase 5).
  → v1.7 Phase 3 (FEED-03, LX-09 — no bulk `warmup_from` fast-path).

- **Persistence live-drive + venue reconciliation** (v1.6 operational store built + testcontainers-tested,
  driven by a real live feed only in N+4). → v1.7 Phase 5 (RECON-04/05).

> **Deferred: multi-asset (forex / equities / ETF).** Crypto-first (locked 2026-06-08)
> removes the near-term need. When revisited, this is itself ≥1 milestone and splits into:
> (a) an instrument/contract-spec abstraction (partly folded into N+1 config typing);
> (b) multi-currency accounting (quote→`base_currency` conversion) — needed for forex;
> (c) trading calendars/sessions + corporate actions (splits/dividends) — needed for
> equities/ETF, and a data-engine concern that pairs with N+4's #6.
>
> **Cross-cutting tooling note:** do NOT add third-party graphify / Understand-Anything
> tools — use the native `gsd-map-codebase` + `gsd-graphify`, which write artifacts into
> `.planning/` that integrate with the workflow and that Claude can read directly.
