---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: — Live System Refactor & Live-Readiness Hardening
current_phase: 05
current_phase_name: Venue Registry + Bundle
status: executing
stopped_at: Completed 05-03-PLAN.md
last_updated: "2026-07-12T22:33:59.279Z"
last_activity: 2026-07-12
last_activity_desc: Phase 05 execution started
progress:
  total_phases: 9
  completed_phases: 4
  total_plans: 19
  completed_plans: 16
  percent: 44
---

# Project State

## Project Reference

See: .planning/PROJECT.md (Current Milestone: v1.8 — Live System Refactor & Live-Readiness Hardening)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle **134 / `46189.87730727451`**; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 shipped a live operating mode (paper-first on OKX) without disturbing that oracle.
**Current focus:** Phase 05 — Venue Registry + Bundle
thin ~200-line facade over focused, venue-parametrized, FastAPI-ready collaborators — **without
disturbing the byte-exact oracle or the OKX import-inertness gate**. FastAPI itself is out of scope
(LR-01). Full scope: core refactor (P1–P8 + P12) + the three ★ feature-adds (P9–P11).

## Current Position

Phase: 05 (Venue Registry + Bundle) — EXECUTING
Plan: 4 of 6
Status: Ready to execute
Last activity: 2026-07-12 — Phase 05 execution started

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

## Bookkeeping

- **At v1.7 close (done 2026-07-07):** all v1.7 phase dirs `git mv`'d to `milestones/v1.7-phases/`;
  ROADMAP/REQUIREMENTS/MILESTONE-AUDIT archived as `milestones/v1.7-*`; `.planning/phases/` is empty
  (no `999.3` seed dir remained). The new v1.8 `01-*..12-*` dirs will not collide (`phase_dir_count=0`).

- Git tag `v1.7` NOT created (owner deferred tagging to a manual step).

## Session Continuity

Last session: 2026-07-12T22:33:26.454Z
Stopped at: Completed 05-03-PLAN.md
success criteria + dependencies + 64/64 coverage); STATE.md refreshed for 12 phases; REQUIREMENTS.md
traceability + category tags + gates renumbered.
Resume file: .planning/phases/05-venue-registry-bundle/05-CONTEXT.md
Carried todo: 14 pending todos in `todos/pending/` (10 fold into v1.8 as CF-1..CF-10; `v17-residual-carryforward.md`
is the index; the substantive open item is `margin-equity-double-counts-notional-wr01`, owner-gated).

## Operator Next Steps

- `/gsd:plan-phase 1` (Config Centralization) — or plan **P1 and P2 in parallel** (both dependency-free).
- At milestone init, set each folded TODO's front-matter `resolves_phase: P#` + `status: scheduled` so it
  is not double-tracked against the live backlog (CF-1..CF-10; see spec §18).

- Before any live margin/leverage consumer: adjudicate `margin-equity-double-counts-notional-wr01`
  (owner-gated, oracle-dark) with external cross-validation.
