---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: — Live System Refactor & Live-Readiness Hardening
current_phase: 0
current_phase_name: roadmap created, revised to 12 phases
status: planning
stopped_at: Phase 1 planned — 4 plans, verification passed
last_updated: "2026-07-09T08:58:46.594Z"
last_activity: 2026-07-09
last_activity_desc: Phase 1 (Config Centralization) planned — 4 plans in 2 waves; plan-checker VERIFICATION PASSED; requirements 6/6 and decisions 13/13 covered
progress:
  total_phases: 9
  completed_phases: 0
  total_plans: 4
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (Current Milestone: v1.8 — Live System Refactor & Live-Readiness Hardening)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle **134 / `46189.87730727451`**; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 shipped a live operating mode (paper-first on OKX) without disturbing that oracle.
**Current focus:** v1.8 decomposes the 2,171-line `LiveTradingSystem` God object (~17 concerns) into a
thin ~200-line facade over focused, venue-parametrized, FastAPI-ready collaborators — **without
disturbing the byte-exact oracle or the OKX import-inertness gate**. FastAPI itself is out of scope
(LR-01). Full scope: core refactor (P1–P8 + P12) + the three ★ feature-adds (P9–P11).

## Current Position

Phase: Phase 1 planned — 0 of 12 executed (P1 Config Centralization ready to execute)
Plan: P1 — 4 plans in 2 waves (01-01, 01-02, 01-03 · Wave 1 ∥; 01-04 · Wave 2)
Status: Ready to execute (P1) — plan-checker VERIFICATION PASSED; P2 still dependency-free (can plan in parallel)
Last activity: 2026-07-09 — planned Phase 1 (Config Centralization): 4 plans, 2 waves; research + pattern-map + validation strategy; requirements 6/6 & decisions 13/13 covered

Progress: [░░░░░░░░░░] 0%

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

## Bookkeeping

- **At v1.7 close (done 2026-07-07):** all v1.7 phase dirs `git mv`'d to `milestones/v1.7-phases/`;
  ROADMAP/REQUIREMENTS/MILESTONE-AUDIT archived as `milestones/v1.7-*`; `.planning/phases/` is empty
  (no `999.3` seed dir remained). The new v1.8 `01-*..12-*` dirs will not collide (`phase_dir_count=0`).

- Git tag `v1.7` NOT created (owner deferred tagging to a manual step).

## Session Continuity

Last session: 2026-07-09T08:58:46.586Z
Stopped at: Phase 1 planned — 4 plans, verification passed, ready to execute
success criteria + dependencies + 64/64 coverage); STATE.md refreshed for 12 phases; REQUIREMENTS.md
traceability + category tags + gates renumbered.
Resume file: .planning/phases/01-config-centralization/01-CONTEXT.md
Carried todo: 14 pending todos in `todos/pending/` (10 fold into v1.8 as CF-1..CF-10; `v17-residual-carryforward.md`
is the index; the substantive open item is `margin-equity-double-counts-notional-wr01`, owner-gated).

## Operator Next Steps

- `/gsd:plan-phase 1` (Config Centralization) — or plan **P1 and P2 in parallel** (both dependency-free).
- At milestone init, set each folded TODO's front-matter `resolves_phase: P#` + `status: scheduled` so it
  is not double-tracked against the live backlog (CF-1..CF-10; see spec §18).

- Before any live margin/leverage consumer: adjudicate `margin-equity-double-counts-notional-wr01`
  (owner-gated, oracle-dark) with external cross-validation.
