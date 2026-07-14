---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: — Live System Refactor & Live-Readiness Hardening
current_phase: 06.1
current_phase_name: seam-cleanup-make-build-live-system-consume-the-shared-compo
status: verifying
stopped_at: Completed 06.1-04-PLAN.md (final plan of phase 06.1)
last_updated: "2026-07-14T11:24:28.761Z"
last_activity: 2026-07-14
last_activity_desc: Phase 06.1 execution started
progress:
  total_phases: 9
  completed_phases: 6
  total_plans: 26
  completed_plans: 26
  percent: 67
---

# Project State

## Project Reference

See: .planning/PROJECT.md (Current Milestone: v1.8 — Live System Refactor & Live-Readiness Hardening)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle **134 / `46189.87730727451`**; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 shipped a live operating mode (paper-first on OKX) without disturbing that oracle.
**Current focus:** Phase 06.1 — seam-cleanup-make-build-live-system-consume-the-shared-compo
thin ~200-line facade over focused, venue-parametrized, FastAPI-ready collaborators — **without
disturbing the byte-exact oracle or the OKX import-inertness gate**. FastAPI itself is out of scope
(LR-01). Full scope: core refactor (P1–P8 + P12) + the three ★ feature-adds (P9–P11).

## Current Position

Phase: 06.1 (seam-cleanup-make-build-live-system-consume-the-shared-compo) — EXECUTING
Plan: 4 of 4
Status: Phase complete — ready for verification
Last activity: 2026-07-14 — Phase 06.1 execution started

Progress: [████░░░░░░] 44%

## Milestone Gate (v1.8 — applies to EVERY phase)

1. **Oracle byte-exact** — `SMA_MACD` stays **134 / `46189.87730727451`** (`check_exact=True`),
   determinism double-run identical. **Per-PLAN gate** on P1–P4, P5, and **P6's `UniverseWiring`
   extraction** (highest oracle risk). Any re-baseline (LR-02) is explicit + externally cross-validated
   (backtesting.py + backtrader), never silent. Live-only phases (P7–P11) stay byte-exact (backtest-dark).

2. **OKX import-inertness** — `tests/integration/test_okx_inertness.py` stays green, extended to assert
   **register-vs-build** on P1/P2/P4/P5 (registering a venue imports no `ccxt.pro` until built;
   `SystemConfig` never constructs Postgres `SqlSettings` at import). **Zero new dependency / no poetry
   change** anywhere in P1–P12.

3. **Held throughout** — Decimal money end-to-end; single UUIDv7; determinism (business `time`, seeded
   RNG, injected clock); `mypy --strict` clean on new code; `filterwarnings=["error"]` green; tabs/spaces
   indentation matched to the file (never normalized).

## Phase Map (v1.8 — Phases 1-12, numbering reset)

Dependency graph (not strict numeric order): `P1 · P2` (no deps) → `P3{P1,P2}` → `P4{P3}`; `P5{P2,P3}`;
`P6{P4,P5}` → `P7{P6}` · `P8{P6}`; `P9★{P4,P7}`; `P10★{P4,P6}`; `P11★{P5,P7}`; `P12{P6,P11}`.

| Phase | Name | Requirements | Notes |
|-------|------|--------------|-------|
| 1 | Config Centralization | CFG-01..06 | oracle-gated; lazy `sql` inertness lever; `HaltReason` (CF-8); CF-6 doc |
| 2 | Event Bus | BUS-01..04 | oracle-gated; +CONTROL EventTypes + minimal `EngineContext` skeleton (refinements 2/3) |
| 3 | EngineContext + Storage-in-Handler | CTX-01..04 | oracle-gated; `SqlBackend→SqlEngine` folded in (refinement 4) |
| 4 | Storage Schema: Migrations Relocation + New Durable Stores | SQL-01..02, STORE-01..05 | merged (old P4+P5); oracle-gated relocation FIRST, then live-only stores; single-head + parity Alembic gate over the FULL chain + rehydrate |
| 5 | Venue Registry + Bundle | VENUE-01..07 | oracle-gated; **highest inertness risk**; CF-3/4/9 |
| 6 | LiveRunner + Factory + Facade Shrink | RUN-01..07 | **highest oracle risk** (`UniverseWiring`); CF-10 |
| 7 | Safety + Reconciliation + Stream Recovery | SAFE-01..06 | CF-2 loop-native; CF-7; SAFE-06 pre-trade throttle |
| 8 | Error Subsystem | ERR-01..04 | **CF-1 aggregate breaker MUST trip** (hard criterion); CF-5 |
| 9 ★ | Runtime-Config Platform | RTCFG-01..06 | feature-add; allowlist + venue-kind-aware fee/slippage gate |
| 10 ★ | Strategies Registry | STRAT-01..03 | feature-add; STRAT-03 atomic re-config folds pair-strategy TODO |
| 11 ★ | Multi-Portfolio-Live | MPORT-01..06 | LR-03 (never trim); distinct-`account_id` fails loud |
| 12 | Test Migration + Gates | TEST-01..04 | lands last; production replay-free; attribution gate |

**Coverage: 64/64 mapped, 0 orphans.** ★ = trimmable feature-add (in scope — owner chose full scope; the
trim boundary P1–P8+P12 core vs P9–P11 ★ is noted, not taken). Research flags (plan-time research): P6
(`UniverseWiring` byte-exact discipline), P8 (CF-1 route-classification + livelock test), P11
(`client_order_id`/`portfolio_id` two-key attribution). Skip research-phase: P2/P4/P5 (specified/mechanical).

## Performance Metrics

**Velocity (program cumulative through v1.7):**

- Total plans completed: 381 (v1.0 62 + v1.1 28 + v1.2 23 + v1.3 20 + v1.4 35 + v1.5 26 + v1.6 21 + v1.7 75)
- v1.8 plans completed: 0

*Updated after each plan completion. Per-milestone velocity is archived in the respective MILESTONE-AUDIT.md.*

## Accumulated Context

### Roadmap Evolution

- v1.8 ROADMAP.md created 2026-07-09 from the LOCKED design spec
  (`docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §16, LR-00..LR-22, CF-1..CF-10)

  + research SUMMARY's 4 build-order refinements. Phases derived 1:1 from the REQUIREMENTS.md
  category→phase mapping (authoritative); all 64 v1 requirements mapped (0 orphans). Numbering reset to
  Phase 1 (matching v1.1–v1.7). The milestone gate (oracle byte-exact + inertness) is a success criterion
  in every phase; per-PLAN oracle gating on P1–P4/P5/P6-UniverseWiring.

- **2026-07-09 revision (13→12 phases):** old P4 (SqlEngine Migrations Relocation, SQL-01/02) folded into
  old P5 (New Durable Stores, STORE-01..05) → a single merged storage-schema phase P4 ("Storage Schema:
  Migrations Relocation + New Durable Stores"). Both are live-only / off the oracle hot path, and
  "relocate the migrations dir, then extend the Alembic chain with 3 new stores" is one cohesive unit of
  work; the SQL-02 single-head + parity gate now validates the FULL chain incl. the 3 new stores. All
  downstream phases renumbered −1 (old P6→P5 … old P13→P12). Owner-approved.

- 4 research refinements folded into the spec §16 graph: (1) P3 depends on {P1,P2}; (2) minimal
  `EngineContext` skeleton lands in P2; (3) P2 adds the CONTROL EventTypes; (4) `SqlBackend→SqlEngine`
  rename folded into P3 (only migrations *relocation* stays in the merged P4).

### Decisions

Active program constraints live in PROJECT.md. v1.8 locks (design LR-00..LR-22): two-tier priority
`EventBus` CONTROL>BUSINESS (LR-11); single-writer engine-thread contract (LR-12); handler-owns storage
init (LR-13); `EngineContext` infra-only (LR-14); two registries execution-venue + data-provider (LR-17);
connectors memoized `(venue, account_id)` (LR-17/LR-20); `SqlBackend→SqlEngine`, migrations→root (LR-18);
`clOrdId→client_order_id` (LR-19); config at its owner's cardinality (LR-21); one `system_store` KV +
`VenueStore` + `StrategyRegistryStore` (LR-22). Ten backlog TODOs fold in as CF-1..CF-10 across
P1/P5/P6/P7/P8 (all live-only / backtest-dark).

- [Phase ?]: P1-01: SystemConfig.sql is a functools.cached_property (not a pydantic field) — built on first access only, keeping SqlSettings/Postgres off the import graph; extra flipped to forbid (D-05/D-06/D-09)
- [Phase ?]: P1-02: HaltReason(Enum) in core/enums/system.py — 4 minimal members (D-10), .value wire strings preserved for durable-record compat (T-02-01); baseline-residual free string retired at live_trading_system.py:810; halt(reason: str) signature migration deferred to P8 (D-11/CF-8)
- [Phase ?]: P1-03: CF-6 D-03a reconcile — folded §6d nuance (exchange-side layer real only where called = SimulatedExchange) into item 4 without regressing the post-V17-16 D-10 framing; CFG-06 closed (doc-only)
- [Phase ?]: P1-04: live-only supervisor/feed constants folded into pure-pydantic StreamSettings + FeedProviderSettings (config/stream.py); reconnect fields float/int not Decimal; P1 seam = default-constructed instance, shared StreamSupervisor deferred to P5 (CFG-03/D-08)
- [Phase ?]: P1-04: live_trading_system.py is 4-space not tabs (od-verified); _OKX_*/_PAPER_* retired, PAPER_PARITY_* anchor preserved byte-identical (Pitfall 4)
- [Phase 02]: D-09/D-10: event-bus substrate (EventBus Protocol + FifoEventBus + PriorityEventBus) landed in itrader/events_handler/bus.py, import-inert (Event TYPE_CHECKING-only), wired into nothing — Plan 02-01: pure substrate, oracle-dark
- [Phase 02]: Typed bus internal queues concretely (queue.Queue[Event] / PriorityQueue[tuple]) not [Any] to satisfy mypy --strict verification gate (byte-identical at runtime) — Rule 3 blocking fix during 02-01 Task 2
- [Phase 02]: D-02/CTX-02: OrderHandler + StrategiesHandler own storage init from keyword-only (environment=backtest, sql_engine=None), exposing the concrete on .storage/.signal_store for the plan-02-03 compose back-read; purely additive, backtest slice = same in-memory concretes, oracle byte-exact (Plan 02-02)
- [Phase ?]: 02-03: compose_engine folded to two-arg (ctx, spec) end-state; internal queue deleted, ctx.bus owns transport (D-01/CTX-01)
- [Phase 02]: 02-03: EngineContext = 4 loose fields (bus/config/environment/sql_engine); downstream only tightens types, never adds fields (D-05/BUS-04)
- [Phase 02]: 02-03: global_queue retyped to EventBus (name unchanged) across 5 handlers + SimulatedExchange + BacktestBarFeed.bind; no call-site changes (D-07/D-08)
- [Phase ?]: CTX-04: SqlBackend renamed to SqlEngine; module moved to storage/engine.py; no alias (D-02)
- [Phase ?]: D-01: backend/_backend vocabulary unified to sql_engine/_sql_engine across storage factories, PortfolioHandler, and Portfolio
- [Phase 03]: D-03: collapsed redundant signal_store surfaces; accessors read through engine.strategies_handler.signal_store, no @property added
- [Phase ?]: [Phase 04]: 04-01: migrations/ relocated to project root via git mv (D-10, 5 revision IDs preserved unchanged, single head d10_halt_records); alembic.ini script_location=migrations; SQL-01 wheel-exclusion samplable via tomllib assertion; oracle byte-exact + inertness green
- [Phase ?]: [Phase 04]: 04-02: three new live-only durable stores landed (SystemStore KV / VenueStore / StrategyRegistryStore), each a HaltRecordStore-template clone composing SqlEngine; natural NAME PKs (D-06, no idgen/surrogate); VenueStore recursive secret-denylist guard fires before the write (D-05, Pitfall 6); StrategyRegistryStore two-table registry+subscriptions with FK-join rehydrate + file-backed restart survival; oracle byte-exact + inertness green
- [Phase ?]: [Phase 04]: 04-03: 3 hand-authored Alembic revisions off d10_halt_records (system_store → venue_config[builds venue_store table, slug!=name] → strategy_registry[registry+FK'd subscriptions, child-first downgrade]); new single head strategy_registry; env.py target_metadata registers all 4 new tables (D-02, import-inert Table-only); SQL-02 gate = single-head + upgrade-head + create_all/migration parity; inertness _FORBIDDEN + register-vs-build extended; oracle byte-exact
- [Phase ?]: WR-02: SQLite FK enforcement lives on SqlEngine (dialect-guarded PRAGMA connect-hook), not a fixture — engine correctness semantics must be identical on every dialect the engine runs
- [Phase ?]: WR-03/D-14: 7 durable stores schema-pure (no runtime create_all); production Alembic-owned, tests provision via tests.support.schema.provision_schema; ephemeral results store keeps create_all
- [Phase ?]: [Phase 05]: 05-01 (VENUE-07/D-08/CF-4): one parameterized StreamSupervisor (connectors/stream_supervisor.py, 4-space, ccxt-free) owns the reconnect ladder + _reconnect_attempts/_streams_down; the 3 donor arms (okx_provider/venue/okx) HAS-A supervisor and delegate. Parameterized over transient/fatal tuples + reconnect_on_clean_return so each donor's behavior is preserved exactly; venue's reduced surface PRESERVED not normalized. ccxt+supervisor lazy-imported in __init__ so venue stays inert (connectors barrel eagerly pulls ccxt.pro). ~9 coupled test files retargeted to arm._supervisor
- [Phase ?]: [Phase 05]: 05-01 (CF-9/D-11/T-05-04): OkxExchange.validate_symbol fail-CLOSES (False) on a non-dict markets cache; reuses the single validate_symbol->delta.removed removal path. Seeded loaded markets in 4 submit fixtures + added cold-cache unit test. CF-3 additive LiveConnector docstrings (no signature change)
- [Phase ?]: 05-03: set_bar_sink NOT defaulted on BaseLiveDataProvider (fail-loud — a no-op default would silently drop bars); a bare base is intentionally not a conforming LiveDataProvider
- [Phase ?]: 05-03: OkxDataProvider left unedited — conforms to LiveDataProvider structurally; avoids conflict with 05-01 StreamSupervisor delegation
- [Phase 05]: VENUE-04/D-09: precision is an AbstractExchange.resolve_precision capability; precision_to_scale is a shared core/money util; LTS resolvers deleted
- [Phase ?]: 05-04: VenueBundle.lifecycle typed Any until 05-06 VenueLifecycle lands (mypy --strict forward-ref)
- [Phase ?]: 05-05: OKX/paper venue plugins triple-deferral-lazy (D-04); register != build proven by extended inertness gate + module-scope AST scans
- [Phase ?]: 05-05: register-vs-build assertion excludes ConnectorProvider (connectors barrel eagerly re-exports OkxConnector, pre-existing 05-04 decision); proves venue-plugin surface inertness instead
- [Phase ?]: 05-06 (VENUE-06/SC3/D-06): LiveTradingSystem.__init__ delegates venue assembly to assemble_venue; every if exchange==okx/elif==paper branch removed (grep=0); venue-string init/start guards became structural None-guards; start/stop delegate connector connect/disconnect to VenueLifecycle
- [Phase ?]: 05-06 (D-10): VenueLifecycle is a small class encoding the fixed connector start/stop order, None-guarding paper's absent connector (start no-ops when bundle.connector is None; stop prefers ConnectorProvider.close_all, falls back to connector.disconnect)
- [Phase ?]: 05-06: plugin/ConnectorProvider imports stay LAZY inside LTS.__init__ not module top — trading_system/__init__.py imports LiveTradingSystem, so a module-top okx_plugin/paper_plugin/ConnectorProvider import would pull them onto the backtest import graph (inertness _FORBIDDEN) and redden test_okx_inertness
- [Phase ?]: 05-06: VenueBundle.lifecycle retyped Any -> VenueLifecycle | None (05-04 forward-seam closed); TYPE_CHECKING forward-ref keeps the substrate import-inert
- [Phase ?]: [Phase 06]: 06-01 (RUN-04/D-01/D-02): wire_universe(engine)->Universe extracted as ONE intact TABS free function in trading_system/universe_wiring.py; backtest_runner delegates to it, keeps ping-grid+precompute post-step; ADDS strategies_handler.set_universe (inert by construction) PROVEN byte-exact 134/46189.87730727451 on determinism double-run; inertness green
- [Phase ?]: RUN-02: LiveRunner/WorkerSupervisor/ErrorPolicy authored as standalone import-inert 4-space modules; unwired here, build_live_system wires them in 06-05
- [Phase ?]: D-04 held: live_trading_system.py facade byte-untouched this plan; LiveRunner reaches facade side-effects via injected callbacks
- [Phase 06]: 06-03 (RUN-07/D-17): _LiveWarmupConsumer rehomed to price_handler/feed/cache_registration.py as frozen StrategyWarmupConsumer (ONE global ring); derive_warmup_depth(strategies) is the NAMED CF-10 depth boundary (global max(warmup) today, per-concerned-strategy later — body-only change); register_strategy_warmup(feed, strategies) is the reusable entry point for SessionInitializer (06-04). Named distinctly from derive() raw-history ladder (Landmine 4); import-inert, 4-space, mypy clean; old consumer stays in LTS until 06-04; oracle byte-exact 134/46189.87730727451
- [Phase ?]: 06-04/RUN-06: UniverseHandler ctor is (bus, universe, feed, config); timeframe+remove_policy read from a flat UniverseHandlerConfig value object; set_venue_metadata(exchange) collapses the two former OKX-guarded venue setters (zero OKX coupling); 4 read-model setters + set_freeze_gate retained (D-11)
- [Phase 06]: 06-05 (RUN-05/RUN-04-live/D-12): LiveRouteRegistrar (central declarative BUSINESS/live route table, list order = execution order, FILL appended, NO CONTROL route per D-23/LR-16) + SessionInitializer (composes wire_universe + register_strategy_warmup + first-class UniverseHandler + LiveRouteRegistrar); _initialize_live_session is a thin delegator; _LiveWarmupConsumer + inline route mutation removed; live GAINS the WR-03 assert; set_venue_metadata unconditional over resolved venue exchange (zero OKX coupling); interim Engine holder + 2 casts, 06-06 flips to build_live_system/compose_engine; oracle byte-exact 134/46189.87730727451, paper-parity + inertness green, mypy clean, 2125 passed
- [Phase ?]: 06-06: build_live_system(spec) is the live composition root (RUN-01/D-09); facade __init__ is pure injection; live wires PriorityEventBus (D-23); LiveRunner owns the drain loop; D-12 construction-time session-init flip deferred to 06-07 — RUN-03 lands structurally
- [Phase ?]: 06-07/TEST-01/D-18: relocated the whole replay harness to tests/support/replay_harness.py; production is replay-free (paper->OKX feed, D-21); paper EXECUTION venue untouched (D-20)
- [Phase ?]: 06-07/D-16: TestRunner is behavior-preserving (calls _initialize_live_session before its per-bar drive); the D-12 construction-time flip stays DEFERRED per 06-06
- [Phase ?]: 06.1-01 (SEAM-01/D-04): compose_engine spec-free; store/feed on EngineContext (D-01/D-02, LR-14 amended); bind+generate_bar_event lifted to base BarFeed ABC; precompute narrowed at backtest-only runner; oracle byte-exact 134/46189.87730727451 + inertness green
- [Phase ?]: 06.1-02 (SEAM-01/SEAM-02/D-05/D-10): build_live_system consumes compose_engine (hand-rolled 4-handler graph + commission closure deleted, FeeModelCommissionEstimator reused); credential-probe arm selects only environment('live'/'backtest')+shared SqlEngine so compose's handler-owned storage lands the identical durable path on both arms; LiveSystemComponents deleted, facade __init__ = pure injection over Engine+VenueLifecycle+separate SQL/halt handles (D-07/D-09); interim Engine reconstruction removed (reads self._engine); oracle byte-exact + inertness green, mypy clean, bodies untouched (D-08)
- [Phase 06.1]: 06.1-03 (SEAM-03/D-11): typed frozen VenueSpec (execution_venue/data_provider/account_id) + shared build_venue_spec builder replace the twice-written SimpleNamespace fake-spec; build_venue_spec is the SOLE home of the {okx,paper}->okx default-provider map, called by BOTH for_exchange and build_live_system (inline specs+maps at :274-283/:1605-1613 deleted, SimpleNamespace import dropped); feeds assemble_venue only, never compose_engine (spec-free since D-04); spec-equality unit test proves the two entry points cannot drift; oracle byte-exact 134/46189.87730727451 + inertness green, mypy clean
- [Phase ?]: D-12: trading_system barrel drops the live surface entirely (backtest-only); live consumers import from the live submodule directly
- [Phase ?]: D-13: pure imports (SessionInitializer/EngineContext/UniverseHandlerConfig) hoisted to live_trading_system module top; heavy ccxt.pro/SQL/venue imports stay lazy inside build_live_system

### Pending Todos

Ten v1.7-carryforward TODOs are **folded into v1.8** as CF-1..CF-10 (set `resolves_phase` at milestone
init; migrate to `todos/completed/` when the owning phase verifies): CF-1→P8 (aggregate breaker, HIGH,
the one with teeth), CF-2/7→P7, CF-3/4/9→P5, CF-5→P8, CF-6/8→P1 (CF-8 also P7), CF-10→P6. Deliberately
**not** folded (kept separate): `livebarfeed-depandas-time-model-datetime`, `mutable-instrument-refactor`,
`margin-equity-double-counts-notional-wr01` (owner-gated), `unify-backtest-direct-bar-generation`
(oracle-risky). `pair-strategy-live-reconfiguration` is folded into P10 (STRAT-03).

### Blockers/Concerns

- **P6 `UniverseWiring` = the highest oracle-risk seam** (analogous to v1.2 MOD-01): move as one intact
  unit incl. the WR-03 desync assert; byte-exact oracle + determinism double-run as a per-PLAN gate.

- **Inertness regression** is the recurring failure mode: no eager import via a barrel re-export, no
  non-lazy `SqlSettings`, no registry importing concretions at registration. `test_okx_inertness.py` is
  the P5 acceptance gate (extended register-vs-build for P1/P2/P4/P5).

- **CF-1 must ACTUALLY TRIP** (P8 hard acceptance criterion): a breaker "green with zero settlements" or
  one reintroducing the WR-06 error→error livelock is a false-green failure.

- **CF-2 threading contract** (P7): `backfill_on_resume` must be loop-native (connector loop), never a
  second concurrent engine-thread ring writer — assert no engine-thread path reaches it.

- **Alembic chain divergence** (P4): relocation + 3-store chain must stay single-head with a
  create_all/migration parity test (the merged storage-schema phase owns the full-chain gate).

- **Indentation hazard:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`,
  `itrader/storage/`, events package use 4 spaces. Match the sibling file — never normalize.

- **Zero new dependency / no poetry change** anywhere in P1–P12 (adding a lib regresses inertness).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not
  silently folded into a running phase.

- ✓ RESOLVED (fix `f86fe5d2`, orchestrator post-merge gate): GATE-01 quarantine regression from 01-01 — `config/system.py` module-level `SqlSettings` import pulled sqlalchemy onto the backtest graph. Fixed by moving the import under `TYPE_CHECKING` + a lazy in-body import; `test_import_quarantine.py` + `test_okx_inertness.py` + byte-exact oracle all green. See phase deferred-items.md.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260713-cvb | Fix WR-02: ConnectorProvider.close_all isolates each disconnect + always clears memo (bound logger) | 2026-07-13 | 5045db99 | [260713-cvb-fix-connector-close-all-teardown](./quick/260713-cvb-fix-connector-close-all-teardown/) |
| 260713-dbw | Consolidate live-provider surface to one symbol: drop BaseLiveDataProvider, keep the LiveDataProvider Protocol, inline the 7 no-op seams into ReplayDataProvider | 2026-07-13 | d3dec871 | [260713-dbw-consolidate-the-two-live-provider-symbol](./quick/260713-dbw-consolidate-the-two-live-provider-symbol/) |
| 260713-ncq | Centralize live stream/feed/DB settings under SystemConfig — inject StreamSettings/FeedProviderSettings (kill 10 inline default-constructions + _STREAM_SETTINGS global); DB gate via lazy SqlSettings() probe instead of os.getenv | 2026-07-13 | 33390772 | [260713-ncq-centralize-live-stream-feed-db-settings-](./quick/260713-ncq-centralize-live-stream-feed-db-settings-/) |
| 260713-wr1 | Delete vacuous WR-01 subscription/membership guard in session_initializer.py (unreachable dead code — membership is the sole subscription source since 06-02/D-05); replace with a TODO for the real future-feature guard condition | 2026-07-13 | dc1f5cb8 | (fast — no dir) |
| 260713-phm | Fix Phase 06 review WR-02 (typed StateError guard above start() try-block so an un-wired LiveTradingSystem fails loudly, not masked as generic ERROR) + IN-02 (LiveRunner.stop() warns when the drain thread outlives the join timeout) | 2026-07-13 | a9f3b5ac | [260713-phm-fix-phase-06-review-findings-wr-02-typed](./quick/260713-phm-fix-phase-06-review-findings-wr-02-typed/) |
| Phase 06 P01 | 4 min | 2 tasks | 2 files |
| Phase 06 P02 | 12 min | 3 tasks | 3 files |
| Phase 06 P03 | 6min | 1 tasks | 1 files |
| Phase 06 P04 | 13min | 2 tasks | 7 files |
| Phase 06 P05 | 9min | 3 tasks | 3 files |
| Phase 06 P06 | 50min | 3 tasks | 26 files |
| Phase 06 P07 | 70min | 3 tasks | 21 files |
| Phase 06.1 P01 | 22min | 3 tasks | 7 files |
| Phase 06.1 P02 | 18 | 3 tasks | 1 files |
| Phase 06.1 P03 | 4 | 3 tasks | 4 files |
| Phase 06.1 P04 | 6 | 3 tasks | 3 files |

## Deferred Items

Program-level items carried across milestones (v1.7-close carry-forward + v2 platform seams). The
substantive owner-gated item is `margin-equity-double-counts-notional-wr01`.

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Owner-gated defect | `margin-equity-double-counts-notional-wr01` — dark on the all-spot golden; a fix moves 6 owner-frozen goldens → needs external cross-validation before any live margin/leverage consumer reads margin equity | ⚠ Owner-gated | next milestone (pre-margin/live) |
| v1.8 deferred seam | Multi-provider feed-router; single-connector-multi-`account_id`; shared-`account_id` risk allocator; config audit table; errors-history table; stats-history split | Marked (spec §14) | v2 / FastAPI-era |
| Downstream consumer | FastAPI application layer / routes / ASGI (LR-01) — v1.8 makes the engine *interfacable* only | Deferred | post-v1.8 milestone |
| Separate refactors | `livebarfeed-depandas-time-model-datetime`, `mutable-instrument-refactor`, `unify-backtest-direct-bar-generation` | Deferred (not folded) | future milestones |
| D-screener | Production screener / ranking / rebalance loop | Deferred | v2 |
| Perp realism (Phase B) | FUND-01..04 (funding accrual, mark-price liq, funding pipeline, freqtrade oracle) | Deferred | v2 |
| Optimization | Optuna sampler + sweep loop (OPT-01) — v1.6 shipped the FK-ready substrate only | Deferred | v2 |
| Turso/libSQL | `sqlalchemy-libsql` opt-in backend — interface stays Turso-ready | Deferred | v2 (post-beta) |
| Perf (v1.5) | Single-pass per-bar portfolio valuation (profile-first gated); PERF-09/PERF-10; advisory Nyquist VALIDATION gaps | Deferred | future perf phase |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions | Deferred | indefinite (crypto-first) |
| Phase 01 P01 | 12 | 3 tasks | 3 files |
| Phase 01 P02 | 12 | 2 tasks | 4 files |
| Phase 01 P03 | 4m | 1 tasks | 1 files |
| Phase 01 P04 | 25min | 3 tasks | 15 files |
| Phase 02 P01 | 3min | 3 tasks | 3 files |
| Phase 02 P02 | 6min | 3 tasks | 4 files |
| Phase 02 P03 | 18min | 3 tasks | 10 files |
| Phase 03 P01 | 11min | 2 tasks | 41 files |
| Phase 03 P02 | 2min | 1 tasks | 2 files |
| Phase 04 P01 | 1min | 2 tasks | 4 files |
| Phase 04 P02 | 6min | 3 tasks | 6 files |
| Phase 04 P03 | 12min | 3 tasks | 6 files |
| Phase 04 P04 | 20m | 3 tasks | 16 files |
| Phase 05 P01 | 29min | 3 tasks | 17 files |
| Phase 05 P03 | 4min | 2 tasks | 4 files |
| Phase 05 P02 | 6m | 3 tasks | 9 files |
| Phase 05 P04 | 5min | 3 tasks | 7 files |
| Phase 05 P05 | 7min | 3 tasks | 5 files |
| Phase 05 P06 | 11min | 3 tasks | 6 files |

## Bookkeeping

- **At v1.7 close (done 2026-07-07):** all v1.7 phase dirs `git mv`'d to `milestones/v1.7-phases/`;
  ROADMAP/REQUIREMENTS/MILESTONE-AUDIT archived as `milestones/v1.7-*`; `.planning/phases/` is empty
  (no `999.3` seed dir remained). The new v1.8 `01-*..12-*` dirs will not collide (`phase_dir_count=0`).

- Git tag `v1.7` NOT created (owner deferred tagging to a manual step).

## Session Continuity

Last session: 2026-07-14T11:24:28.753Z
Stopped at: Completed 06.1-04-PLAN.md (final plan of phase 06.1)
success criteria + dependencies + 64/64 coverage); STATE.md refreshed for 12 phases; REQUIREMENTS.md
traceability + category tags + gates renumbered.
Resume file: .planning/phases/06.1-seam-cleanup-make-build-live-system-consume-the-shared-compo/06.1-CONTEXT.md
Carried todo: 14 pending todos in `todos/pending/` (10 fold into v1.8 as CF-1..CF-10; `v17-residual-carryforward.md`
is the index; the substantive open item is `margin-equity-double-counts-notional-wr01`, owner-gated).

## Operator Next Steps

- `/gsd:plan-phase 1` (Config Centralization) — or plan **P1 and P2 in parallel** (both dependency-free).
- At milestone init, set each folded TODO's front-matter `resolves_phase: P#` + `status: scheduled` so it
  is not double-tracked against the live backlog (CF-1..CF-10; see spec §18).

- Before any live margin/leverage consumer: adjudicate `margin-equity-double-counts-notional-wr01`
  (owner-gated, oracle-dark) with external cross-validation.
