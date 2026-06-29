---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: N+3b Persistence Foundation
status: ready_to_plan
stopped_at: Phase 02 complete (4/4) — ready to discuss Phase 999.2
last_updated: 2026-06-29T11:45:58.564Z
last_activity: 2026-06-29 -- Phase 02 execution started
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 9
  completed_plans: 9
  percent: 14
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-27 — v1.6 N+3b Persistence Foundation ACTIVE; scope locked via owner clarification 2026-06-27)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers (oracle 134 / `46189.87730727451`; v1.5 W1 baseline 15.7 s / 152.8 MB). v1.6 adds the durable-storage + caching foundation **without disturbing that** — the backtest path stays byte-exact and N+4 Live inherits a persistent, restart-safe system of record.
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-29

Progress: [░░░░░░░░░░] 0%

## Milestone Gate (v1.6 — DB-gated; applies to EVERY phase)

This milestone is **NOT covered by the backtest oracle alone** — it is DB-gated. Each phase carries a
**two-part gate**:

1. **Gate (a) — hot-path inertness:** the SMA_MACD oracle stays **byte-exact** (134 /
   `46189.87730727451`) AND there is **no W1/W2 perf regression** vs the v1.5 frozen baseline
   (15.7 s / 152.8 MB). Persistence adds zero hot-path cost when write-through is off (backend-selection
   at wiring — the backtest backend contains NO serialization code; an end-of-run batch dump is off the
   loop). **GATE-01** is bound to Phase 4 (where live write-through lands) and recurs every phase.

2. **Gate (b) — DB verification on the right substrate:** the phase's own DB round-trip / rehydration /
   cross-backend-parity tests pass — **in-process SQLite** for the results store (#1), **testcontainers
   Postgres** for the operational store (#2). **GATE-02** is bound to Phase 1 (test harness/substrate
   established) and recurs every phase.

**Held throughout, all phases:** Decimal money on the live path (Postgres-native `Numeric`, no
float-for-money, no `DecimalAsText`); single UUIDv7 (no DB autoincrement / second ID scheme);
determinism (business `time` not wall-clock, `sort_keys`, stable `ORDER BY`); `mypy --strict` clean;
`filterwarnings=["error"]` green with no new broad ignore; tabs/spaces indentation matched to the file.

## Phase Map (v1.6 — Phases 1-5)

Execution order: 1 → 2 → 3 → 4 (Phase 5 is largely independent — may run parallel to Phases 2-3; listed
last). Hard build-order constraints (research ARCHITECTURE): spine before every backend; the results
store validates the spine before any live path touches it; the retention model is designed before live
write-through is wired. Numbering reset to Phase 1 (matching v1.1–v1.5); the only dirs in
`.planning/phases/` are the `999.2`/`999.3` backlog placeholders (999.x prefix — no collision with the
new `01-*..05-*` dirs).

| Phase | Name | Requirements | Substrate | Depends on |
|-------|------|--------------|-----------|------------|
| 1 | SQL Spine + Security Hardening | SPINE-01/02/03, SEC-01, MIG-01, GATE-02 | SQLite + Postgres | — |
| 2 | Results Store (#1) | RESULT-01/02/03/04 | in-process SQLite | 1 |
| 3 | Operational SQL Backends (#2) | OPS-01/02/03/04 | testcontainers Postgres | 2 |
| 4 | Retention + Live Write-Through (#2 live) | RETAIN-01/02/03, GATE-01 | testcontainers Postgres | 3 |
| 5 | Cache Classification (#3) | CACHE-01/02 | (doc + grep) | 1 |

**Research flag:** Phase 4 NEEDS DEEPER PLAN-TIME RESEARCH (`/gsd:plan-phase --research-phase`) — the
live retention design (write-through transaction boundary, bracket-parent safety, read-through scope,
rehydration query surface, single-daemon-thread vs API-thread interaction) is the most novel + least
validated surface. Phases 1/2/3/5 are standard patterns (plan-time research optional).

## Performance Metrics

**Velocity (program cumulative through v1.5):**

- Total plans completed: 203 (v1.0 62 + v1.1 28 + v1.2 23 + v1.3 20 + v1.4 35 + v1.5 26)
- v1.6 plans completed: 0

*Updated after each plan completion. Per-milestone velocity is archived in the respective MILESTONE-AUDIT.md.*

## Accumulated Context

### Roadmap Evolution

- v1.6 roadmap created 2026-06-27 (promotes the persistence half of Backlog 999.2): 5 phases derived
  from the 20 v1.6 requirements + the research 5-phase build order; all 20 mapped (100% coverage, no
  orphans). Backlog 999.2 marked PROMOTED-TO-v1.6 (design intent retained as the historical seed, like
  999.4 → v1.4); 999.3 (N+4 Live) kept intact. GATE-01 bound to Phase 4 + GATE-02 to Phase 1, both
  restated as recurring success criteria in every phase.

- Owner Decisions (locked 2026-06-27) supersede the research seed where they differ: SQLite-default
  research + Postgres-only operational + Turso-opt-in-LATER (no `sqlalchemy-libsql` driver this
  milestone); results store all-`Float` (no `DecimalAsText`); frames as JSON/gzip'd-text (no
  Parquet/`pyarrow`); money fidelity via Postgres-native `Numeric` (money never touches SQLite);
  optimization sweep loop OUT (substrate only, schema stays Optuna-FK-ready).

### Decisions

Active program constraints live in PROJECT.md. v1.6-specific load-bearing decisions:

- **Spine = composition, not inheritance (research Q1):** one shared `SqlBackend` held by reference by
  four `Sql<Concern>Storage` classes; the three existing domain ABCs stay UNCHANGED, a new `ResultsStore`
  ABC is added. NO cross-concern god base.

- **Backend-selection write-through, NOT a hot-path flag (research Q9, PITFALLS 3):** the backtest
  backend contains no serialization code at all — zero hot-path cost is structural, not disciplined.

- **No `DecimalAsText`, no `pyarrow`, no libSQL this milestone (Owner Decisions):** money on the
  operational path is Postgres-native `Numeric`; frames are JSON/gzip'd-text; the libSQL driver is
  deferred (interface stays Turso-ready via one engine-URL swap).

- **Money = Decimal end-to-end on the real-money path; determinism; single UUIDv7** — all carried
  unchanged onto the persistence layer (persisted timestamps use business `time`, never wall-clock).

- [Phase 01]: 01-01: GATE-02 cross-backend test substrate established — session-scoped testcontainers Postgres pg_engine + indirect-parametrized sqlite/postgres engine fixture under tests/integration/storage/ (D-10/D-11); Docker-absent skips, never hard-fails.
- [Phase 01]: 01-01: alembic ^1.18.5 + testcontainers[postgresql] ^4.14.2 added as dev-deps behind the blocking-human supply-chain gate (T-01-SC); kept off the runtime path to preserve GATE-01 inertness. GATE-02 left Pending (recurring gate, substrate-only).
- [Phase 01]: 01-02: SQL spine shipped — SqlBackend (Engine+MetaData, composed not inherited, no SqlStorageBase god base) + storage/types.py (UtcIsoText deterministic UTC-isoformat business-time, json_variant JSON/JSONB, direct Uuid(as_uuid=True); no money type per D-13) + config/sql.py SqlSettings (driver-by-config, lazy SecretStr Postgres creds, unwired SQLITE_LIBSQL Turso slot). mypy --strict clean, oracle byte-exact.
- [Phase 01]: 01-02: Only SPINE-01 marked complete; SPINE-02 (all four Sql<Concern>Storage + ResultsStore ABC), SPINE-03 (cross-backend SQLite+Postgres round-trip, plan 01-03) and GATE-02 (recurring) left Pending — structural/encoding halves established, full criteria span later plans/phases.
- [Phase 01]: 01-03: SPINE-03 proven — UUIDv7 id + business-time round-trip lossless and value-EQUAL on BOTH in-process SQLite and testcontainers Postgres (live PG arm ran), byte-identical encoded TEXT across runs (D-03/D-04/D-05, D-10/D-11); SPINE-03 marked complete in REQUIREMENTS.md.
- [Phase 01]: 01-03: ResultsStore(ABC) added as the spine's 4th composable concern — 4 @abstractmethods mapped 1:1 to RESULT-01/02/03, composes SqlBackend (no god base); impl deferred to Phase 2 so SPINE-02 stays Pending. No tests/unit/results/__init__.py created (package-less tests/unit convention, ref 30c0f61).
- [Phase 01]: 01-04: MIG-01 Alembic skeleton shipped — live-Postgres chain only (one chain, render_as_batch=True both paths, empty versions/), target_metadata = spine SqlBackend MetaData, alembic.ini sqlalchemy.url BLANK with the URL resolved lazily in env.py (no Settings() at import, no credential in config; T-01-09/T-01-11). Research store uses create_all() and carries NO alembic_version — split proven by test_migrations.py on SQLite + testcontainers Postgres. MIG-01 marked complete.
- [Phase 01]: 01-04: Fixed the stock Alembic env.py fileConfig footgun (disable_existing_loggers=False) so in-process Alembic does not disable iTrader structlog-backed stdlib loggers (caplog contamination); migration tooling kept off the runtime import graph (GATE-01 inert — import itrader.storage does not pull alembic).
- [Phase 01]: 01-05: FL-06/SEC-01 closed — SqlHandler reworked onto SqlBackend (5th consumer), single parameterized prices table (symbol VALUE column, D-07), creds from Settings.database_url SecretStr, f-string DROP TABLE removed; lifted into mypy --strict (D-sql override dropped, zero ignores). SEC-01 COMPLETE; GATE-02 left Pending (recurring). No tests/unit/price_handler/__init__.py (package-less dir, ref 30c0f61). Oracle byte-exact, suite 1373 green.

### Pending Todos

[From .planning/todos/pending/ — carried, not v1.6-blocking]

- Correct single-pass per-bar portfolio valuation (`single-pass-portfolio-valuation.md`) — deferred
  v1.5, profile-first gated (future perf phase, not v1.6).

- Live-start indicator backfill through the same `update(bar)` path (`live-backfill-through-update.md`)
  — N+4 when `LiveBarFeed` is built.

### Blockers/Concerns

- **Hot-path inertness is the load-bearing risk (Gate a):** a serialize/`write_through` call must never
  land on the per-tick backtest loop. Enforce via backend-selection (two classes, not one flagged class);
  the in-memory backend imports no SQLAlchemy/serialization symbol. W1/W2 within v1.5 ±5% is the proof.

- **Cross-backend divergence:** stay on SQLAlchemy Core constructs + portable types; scalar-promote
  filterable `runs` params to indexed columns (no JSON-path filtering in cross-sweep queries); run the
  persistence suite on BOTH SQLite and Postgres. UUIDv7 in one canonical encoding so a `run_id` written
  under SQLite reads equal under Postgres.

- **Phase 4 retention is novel + unvalidated** (live path unbuilt) — design before wiring; plan-time
  research recommended. Bracket-parent safety + crash-safe write ordering + open-only rehydration.

- **Indentation hazard:** `config/`, `core/`, `itrader/storage/`, `itrader/results/`,
  `strategy_handler/storage/` use 4 spaces; `order_handler/storage/` + `portfolio_handler/storage/` use
  tabs. New `Sql<Concern>Storage` files MUST match the existing sibling — a mixed-indent tab file fails
  to import.

- **FL-06 creds:** rotate/scrub the exposed `SqlHandler` credential when reworking onto `SecretStr`;
  never log the resolved secret URL.

- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not
  silently folded into a running phase.

## Deferred Items

Program-level items deferred across milestones, with their target milestone (v1.6-relevant rows
promoted INTO this milestone marked):

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Persistence/security | SQL injection + hardcoded creds in `SqlHandler` (FL-06) | **Promoted INTO v1.6** (SEC-01, Phase 1) | v1.6 |
| D-sql | SQL persistence backends (order/portfolio/signal/results) — v1.5 PERF-01 `OrderStorage` interface designed for this | **Promoted INTO v1.6** (SPINE/RESULT/OPS, Phases 1-3) | v1.6 |
| Optimization | Optuna sampler + sweep loop (OPT-01) — v1.6 ships the Optuna-FK-ready substrate only | Deferred | future (v2) |
| Turso/libSQL | `sqlalchemy-libsql` opt-in research backend (TURSO-01) — interface stays Turso-ready | Deferred | future (v2, post-beta + measured) |
| Live drive | Persistence driven by a real live feed + venue reconciliation (operational store built/tested on testcontainers in v1.6) | Deferred | N+4 (Backlog 999.3) |
| Perf (v1.5) | Correct single-pass per-bar portfolio valuation (profile-first gated) | Deferred | future perf phase |
| Perf (v1.5) | Nyquist VALIDATION.md gaps (advisory; oracle + A/B perf gate are the real lock) | Deferred | optional `/gsd:validate-phase` backfill |
| Deferred perf (v2) | PERF-09 / PERF-10 (strategy-level dedup, O(n²)-in-symbol guard) | Deferred | future (large universes only) |
| Perp realism (Phase B) | FUND-01..04 (funding accrual, mark-price liq, funding pipeline, freqtrade oracle) | Deferred | N+4 data work |
| Live account | `Account` reconciliation mirror (ACCT-01) | Deferred | N+4 (Backlog 999.3) |
| Live coverage | `LiveTradingSystem`/`TradingInterface` test coverage (FL-13) | Deferred | N+4 (Backlog 999.3) |
| Cleanup | `Portfolio.user_id` removal (app-layer multi-tenancy concern) | Deferred | N+4 (with the connector) |
| D-screener | Production screener / ranking / rebalance loop | Deferred | N+4 (Backlog 999.3) |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions | Deferred | indefinite (crypto-first) |

v1.0–v1.5 milestone-close acknowledgments are recorded in the respective MILESTONE-AUDIT.md files
under `milestones/`.
| Phase 01 P01 | 11m | 3 tasks | 5 files |
| Phase 01 P02 | 8min | 3 tasks | 8 files |
| Phase 01 P03 | 4min | 2 tasks | 4 files |
| Phase 01 P04 | 7min | 2 tasks | 5 files |
| Phase 01 P05 | 7min | 3 tasks | 3 files |

## Bookkeeping

- **v1.5 phase dirs archived (2026-06-26, at milestone close):** the v1.5 phase working directories
  were `git mv`'d to `.planning/milestones/v1.5-phases/`. Only the `999.x` backlog seed dirs
  (`999.2`/`999.3`) remain in `.planning/phases/`, so the new v1.6 `01-*..05-*` dirs will not collide.

- **At v1.6 close (reminder):** `git mv` the v1.6 phase dirs to `milestones/v1.6-phases/` and archive
  `ROADMAP`/`REQUIREMENTS`/`MILESTONE-AUDIT` as `milestones/v1.6-*`.

## Session Continuity

Last session: 2026-06-29T08:27:53.269Z
Stopped at: Phase 2 context gathered
Resume file: .planning/phases/02-results-store-1/02-CONTEXT.md
Carried todo: none v1.6-blocking; deferred single-pass valuation + live-backfill carried (see Deferred Items / Pending Todos)

## Operator Next Steps

- Plan Phase 1 (SQL Spine + Security Hardening) with `/gsd:plan-phase 1`
- Phase 4 (Retention + Live Write-Through) — plan with `/gsd:plan-phase --research-phase` when reached
