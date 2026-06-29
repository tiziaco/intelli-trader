# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- ✅ **v1.5 — Backtest Performance Optimization** — Phases 1-8 (shipped 2026-06-26; numbering reset; performance half of Backlog 999.2, split out from Persistence; Phases 7-8 added 2026-06-25 from post-phase re-profiles)
- 🚧 **v1.6 — N+3b Persistence Foundation** — Phases 1-5 (active from 2026-06-27; numbering reset; promotes the **persistence half** of Backlog 999.2)
- 📋 **N+4 — Live Trading Readiness** — Backlog (planned)

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
[`v1.5-MILESTONE-AUDIT.md`](./milestones/v1.5-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`; v1.4 under `milestones/v1.4-phases/`; v1.5 under `milestones/v1.5-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **Backlog 999.2 is
> SPLIT:** its **performance half** shipped as **v1.5 — Backtest Performance Optimization**
> (2026-06-26); its **persistence half** is promoted as **v1.6 — N+3b Persistence Foundation**
> (active from 2026-06-27; Backlog 999.2 marked PROMOTED-TO-v1.6, design intent retained as the
> historical seed). The remaining `999.x` entry (999.3 = N+4 live) is a future milestone, left intact.

## Phases

### 🚧 v1.6 — N+3b Persistence Foundation (Phases 1-5) — ACTIVE

Phase numbering reset to Phase 1 (matching v1.1–v1.5). v1.6 builds the durable-storage + caching
foundation: one swappable SQL spine (SQLite research store + Postgres operational store, Turso-ready
but driver NOT added — Owner Decision), an all-SQL results store (#1), concrete SQL backends for the
three live operational seams (order mirror, portfolio state, strategy/signal — #2), a two-knob
write-through + retention model with restart rehydration, and a classified cache (#3). This is a
**DB-gated** milestone, NOT covered by the backtest oracle alone, so EVERY phase carries a **two-part
gate**: (a) the SMA_MACD backtest oracle stays byte-exact (134 / `46189.87730727451`) with no W1/W2
perf regression vs the v1.5 frozen baseline (15.7 s / 152.8 MB) — proving the persistence layer is
inert on the hot path — AND (b) the phase's own DB round-trip / rehydration / cross-backend-parity
tests on the right substrate (in-process SQLite for #1, testcontainers Postgres for #2). Standing
constraints carried throughout: Decimal money on the live path (Postgres-native `Numeric`, no
float-for-money), single UUIDv7, determinism, `mypy --strict` clean, `filterwarnings=["error"]` green,
and the tabs/spaces indentation hazard. Owner Decisions (locked 2026-06-27) supersede the research
where they differ: SQLite-default research + Postgres-only operational + Turso-opt-in-LATER; results
store all-`Float` (no `DecimalAsText`); frames as JSON/gzip'd-text (no Parquet/`pyarrow`); optimization
sweep loop OUT (substrate only). Full requirements: [`REQUIREMENTS.md`](./REQUIREMENTS.md); research:
[`research/SUMMARY.md`](./research/SUMMARY.md).

- [x] **Phase 1: SQL Spine + Security Hardening** - Config-selected `SqlBackend`/`SqlSettings` (SQLite + Postgres, Turso-ready), composition layering (3 existing ABCs + new `ResultsStore` ABC), lossless UUIDv7/timestamp round-trip, FL-06 `SqlHandler` hardening, Alembic skeleton + `create_all()` strategy — completed 2026-06-27 (5/5 plans)
- [x] **Phase 2: Results Store (#1)** - Every backtest/optimization run persisted on ephemeral SQLite (`runs` Float + JSON settings, `run_artifacts` JSON/gzip text frame, cross-run query, Optuna-FK-ready); validates the spine oracle-dark — completed 2026-06-29 (4/4 plans)
- [ ] **Phase 3: Operational SQL Backends (#2)** - One Postgres SQL backend per existing seam (order mirror, portfolio state, signal), money as native `Numeric`, testcontainers round-trip; backtest in-memory backends unchanged
- [ ] **Phase 4: Retention + Live Write-Through (#2 live path)** - Two-knob model (write-through OFF in backtest = zero hot-path cost; live = write-through + working-set cache + purge-on-terminalize + read-through + restart rehydration); built + integration-tested on testcontainers (NEEDS plan-time research)
- [ ] **Phase 5: Cache Classification (#3)** - Inventory + classify (a/b/c) every cache/`lru_cache`; leave the v1.5 hot path alone; classify, do not rewrite or unify

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

## Phase Details

> v1.6 — N+3b Persistence Foundation. Execution order: 1 → 2 → 3 → 4 (Phase 5 is largely independent
> and may run in parallel with Phases 2-3; it is listed last). Every phase's Success Criteria carry the
> two-part DB-gate (oracle byte-exact + no W1/W2 regression AND the phase's own DB verification on the
> right substrate). GATE-01 is *bound* to Phase 4 (where live write-through lands) and GATE-02 to
> Phase 1 (where the test harness/substrate is established); both *recur* as success criteria in every
> phase.

### Phase 1: SQL Spine + Security Hardening
**Goal**: One config-selected SQL backend (SQLite research store + Postgres operational store) exists as
the shared spine that every store composes, credentials are sourced from secrets, and UUIDv7 ids +
business-time timestamps round-trip losslessly across both dialects — the hard dependency root nothing
else compiles without.
**Depends on**: Nothing (first phase)
**Requirements**: SPINE-01, SPINE-02, SPINE-03, SEC-01, MIG-01, GATE-02
**Success Criteria** (what must be TRUE):
  1. A developer selects the SQL backend (SQLite or Postgres) by changing `SqlSettings`/config alone — no storage code changes — and a single shared `SqlBackend` is composed (never inherited) by all four storage concerns: the three existing domain ABCs (`OrderStorage`, `PortfolioStateStorage`, `SignalStore`) plus the new `ResultsStore` ABC, one `Sql<Concern>Storage` per concern, no cross-concern god base. The interface is shaped Turso-ready, but the `sqlalchemy-libsql` driver is NOT added (Owner Decision).
  2. A UUIDv7 id and a business-time timestamp written through the SQL layer read back losslessly and equal on both SQLite and Postgres — single UUIDv7 scheme (one canonical encoding), no wall-clock writes, no DB autoincrement / second-ID-scheme creeping in (cross-backend `run_id` equality round-trip passes).
  3. `SqlHandler` (`price_handler/store/sql_store.py`) sources credentials from `Settings.database_url` (SecretStr) and uses SQLAlchemy Core / parameterized queries + safe quoted identifiers — no hardcoded creds (L17), no f-string `DROP TABLE` injection (L35), no symbol-as-table-name (L56/58/69) (FL-06 closed; grep finds no `user:pass@` and no f-string inside `text()`).
  4. The live Postgres store has an Alembic migration skeleton (one chain, `render_as_batch=True` for portable ALTER) while the ephemeral research store uses `create_all()` — the results DB has no `alembic_version` table.
  5. (GATE-02 bound here + recurring) The new spine code is `mypy --strict` clean and the full suite is green under `filterwarnings=["error"]` with no new broad ignore; (GATE-01 recurring) the SMA_MACD backtest oracle holds byte-exact 134 / `46189.87730727451` with no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB) — the spine is inert on the hot path.
**Plans**: 5 plans across 2 waves (wave 1: 01-01, 01-02 — parallel; wave 2: 01-03, 01-04, 01-05)
- [x] 01-01-deps-pg-harness-PLAN.md — Dev-deps (alembic, testcontainers) behind a package-legitimacy gate + the session-scoped testcontainers Postgres test harness (D-10/D-11; GATE-02 substrate)
- [x] 01-02-spine-core-PLAN.md — The SQL spine: storage/types.py (Uuid/UtcIsoText/json_variant, no DecimalAsText) + storage/backend.py (SqlBackend) + config/sql.py (SqlSettings, libsql slot) — composition not inheritance (SPINE-01/02/03, GATE-02)
- [x] 01-03-spine03-roundtrip-PLAN.md — SPINE-03 cross-backend UUIDv7 + business-time round-trip (SQLite + testcontainers Postgres + determinism) + ResultsStore ABC seam (SPINE-02/03)
- [x] 01-04-alembic-skeleton-PLAN.md — Alembic skeleton (render_as_batch=True, empty versions/) for live Postgres; create_all() for the research store, no alembic_version (MIG-01)
- [x] 01-05-fl06-hardening-PLAN.md — FL-06: rework SqlHandler onto the spine — single `prices` table, SecretStr creds, parameterized; mypy-strict (SEC-01, GATE-02)

### Phase 2: Results Store (#1)
**Goal**: Every backtest/optimization run persists end-to-end on an ephemeral SQLite database — a `runs`
summary row plus a `run_artifacts` frame blob — validating the spine oracle-dark before any live path
depends on it.
**Depends on**: Phase 1
**Requirements**: RESULT-01, RESULT-02, RESULT-03, RESULT-04
**Success Criteria** (what must be TRUE):
  1. After a backtest run, a `runs` row (summary metrics as `Float` columns + a JSON settings column; Optuna-FK-ready nullable study/trial ids) and a `run_artifacts` row (the equity-curve / trade-log frame as a JSON/gzip'd-text column — NO Parquet, NO `pyarrow`) are persisted, and the artifact round-trips back to an equal pandas DataFrame.
  2. A user can query the cross-run surface — e.g. top-N runs by a summary metric — against the `runs` table, and the schema carries the nullable Optuna study/trial FK columns without the sweep loop being built (substrate only).
  3. The results store runs on SQLite by default with schema via `create_all()` (ephemeral; no `alembic_version` table), and a DB round-trip test (write → read → assert equality) on an in-process SQLite database passes deterministically — the same frame encodes to identical bytes across two runs (`sort_keys`, business-time not wall-clock, stable `ORDER BY`).
  4. (recurring gates) Oracle byte-exact 134 / `46189.87730727451` with no W1/W2 regression vs the v1.5 baseline — the end-of-run batch dump is post-loop, off the hot path (the backtest hot loop touches no SQL); `mypy --strict` clean and `filterwarnings=["error"]` green.
**Plans**: 4 plans across 3 waves (wave 1: 02-01; wave 2: 02-02, 02-03 — parallel; wave 3: 02-04)
- [x] 02-01-PLAN.md — Contracts + schema: ResultsNotFound, SqlSettings strict_persist/on-disk path, RunMetrics/PortfolioRecord/RunRecord DTOs, runs/run_portfolios/run_artifacts Core tables, widened 5-method ResultsStore ABC (RESULT-01/02/03)
- [x] 02-02-PLAN.md — Pure serializers: curated runs.settings + run_portfolios.params envelopes, RunMetrics builder (derived total_return/calmar), mixed-timeframe aggregate equity curve + annualization basis (RESULT-01)
- [x] 02-03-PLAN.md — Concrete SqlResultsStore: composition + create_all, gzip byte-deterministic codec, atomic save_run/save_artifact, keyed get_artifact + ResultsNotFound, injection-safe top_runs/top_portfolios, in-process SQLite round-trip tests (RESULT-02/03/04)
- [x] 02-04-PLAN.md — Composition wiring + run(persist=) post-loop dump (direct store construction, D-03 guard, D-17 policy, UUIDv7 run_id) + oracle/import inertness integration test (RESULT-01/04)

### Phase 3: Operational SQL Backends (#2 — store layer)
**Goal**: Each of the three existing operational seams (order mirror, portfolio state, strategy/signal)
gets one concrete Postgres SQL backend on the shared spine, money persisted as native `Numeric`,
validated on testcontainers Postgres — with the backtest in-memory backends unchanged.
**Depends on**: Phase 2
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04
**Success Criteria** (what must be TRUE):
  1. `SqlOrderStorage` implements the `OrderStorage` ABC on Postgres (filling the `PostgreSQLOrderStorage` `NotImplementedError` stub; the v1.5 secondary indexes become SQL `WHERE` + indexes), `SqlPortfolioStateStorage` implements `PortfolioStateStorage` (cash/position/transaction/metrics), and `SqlSignalStorage` implements the `SignalStore` ABC — each selectable via its factory's `postgresql`/`live` arm.
  2. Each factory returns the in-memory backend for `backtest` (UNCHANGED, importing no SQLAlchemy/serialization symbol) and the SQL backend for `live`/`postgresql` — the no-serialization-in-backtest-backend rule holds structurally (backend-selection at wiring, not a hot-path `write_through` flag).
  3. Operational money persists as Postgres-native `Numeric` (Decimal end-to-end on the real-money path — no float-for-money, no `DecimalAsText` needed) and round-trips as an exact `Decimal` — validated by DB round-trip tests on a testcontainers Postgres.
  4. (recurring gates) Oracle byte-exact 134 / `46189.87730727451` with no W1/W2 regression vs the v1.5 baseline (the backtest path still routes through the in-memory backends); each new handler-storage file imports clean with indentation matched to its sibling (tabs in `order_handler`/`portfolio_handler` storage; 4 spaces in `strategy_handler` storage); `mypy --strict` clean and `filterwarnings=["error"]` green.
**Plans**: TBD

### Phase 4: Retention + Live Write-Through (#2 — live path)
**Goal**: The two-knob retention model — write-through OFF in backtest (zero hot-path serialization),
write-through ON to Postgres in live with a bounded working-set cache, purge-on-terminalize,
read-through, and restart rehydration — fully specified and built, integration-tested on testcontainers
Postgres (driven by a real live feed only in N+4).
**Depends on**: Phase 3
**Requirements**: RETAIN-01, RETAIN-02, RETAIN-03, GATE-01
**Success Criteria** (what must be TRUE):
  1. The write-through toggle is mode-aware backend-selection, NOT a hot-path flag: backtest = retain-all in-memory + optional end-of-run batch dump (the backtest backend contains no per-tick serialization code); live = synchronous write-through to the Postgres system of record (store commits before the engine acknowledges the state change).
  2. The live working-set cache keeps only the active set resident (open positions, working orders + brackets, current snapshot, running accumulators); terminal records are purged on terminalize with a bounded read-through fallback, and a bracket parent stays resident until its children terminalize — proven by an evict-then-read-through test and a flat-RSS long-run test.
  3. Restart rehydration reconstructs the live working set (open positions + working orders + brackets) from the store deterministically, without replaying terminal history — proven by an open-only rehydration test and a crash-after-emit/restart test (rehydrated working set equals pre-crash state), on testcontainers Postgres.
  4. (GATE-01 bound here) With write-through OFF, the SMA_MACD oracle stays byte-exact 134 / `46189.87730727451` with no W1/W2 perf regression vs the v1.5 baseline (15.7 s / 152.8 MB) — proving the persistence layer is inert on the hot path; (GATE-02 recurring) the new live persistence code is covered by round-trip + rehydration tests on testcontainers Postgres, `mypy --strict` clean, `filterwarnings=["error"]` green.
**Plans**: TBD
**Research flag**: NEEDS DEEPER PLAN-TIME RESEARCH (`/gsd:plan-phase --research-phase`). The live retention design is the most architecturally novel work of the milestone and the least-validated surface (the live path is unbuilt). Nail down the write-through transaction-boundary design (create/terminalize sync vs append-heavy), the bracket-parent safety invariant, the read-through scope, the rehydration query surface, and the `LiveTradingSystem` single-daemon-thread vs `TradingInterface` API-thread interaction before implementation (research SUMMARY §Research Flags; PITFALLS 7/8).

### Phase 5: Cache Classification (#3)
**Goal**: Every ad-hoc cache / `lru_cache` across `itrader/` is inventoried and classified (a/b/c) with
routing decisions documented and the v1.5 hot path left unchanged — classify, do not rewrite or unify.
**Depends on**: Phase 1 (largely independent — may run in parallel with Phases 2-3; listed last)
**Requirements**: CACHE-01, CACHE-02
**Success Criteria** (what must be TRUE):
  1. An authoritative cache-classification map is committed: every ad-hoc cache / `lru_cache` / scattered in-memory lookup across `itrader/` is inventoried and tagged (a) hot-path data cache, (b) storage-index lookup already solved by v1.5 secondary indexes, or (c) legitimate pure-function memoization — a documented classification + routing, NOT a rewrite or a unification.
  2. The v1.5 hot path (stateful indicators / shared recent-bars feed) is left unchanged — the "do NOT unify into one Arrow-backed object" decision is recorded and cross-referenced, and grepping `itrader/` for `lru_cache`/`functools.cache`/ad-hoc `_cache` fields matches the inventory exactly (the only genuinely new cache is the live working-set cache built in Phase 4).
  3. (recurring gates) Oracle byte-exact 134 / `46189.87730727451` with no W1/W2 regression vs the v1.5 baseline (classification is documentation + routing decisions, no hot-path edit); `mypy --strict` clean and `filterwarnings=["error"]` green.
**Plans**: TBD

## Progress

**Shipped milestones** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |
| v1.4 — Margin, Leverage, Shorts & Trailing Stops | 1-6 + 5.1 | 35 | ✅ Shipped | 2026-06-22 |
| v1.5 — Backtest Performance Optimization | 1-8 | 26 | ✅ Shipped | 2026-06-26 |

**Active milestone — v1.6 — N+3b Persistence Foundation** (Execution order: 1 → 2 → 3 → 4; Phase 5 listed last, parallel-capable):

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. SQL Spine + Security Hardening | 5/5 | Complete   | 2026-06-27 |
| 2. Results Store (#1) | 4/4 | Complete   | 2026-06-29 |
| 3. Operational SQL Backends (#2) | 0/TBD | Not started | - |
| 4. Retention + Live Write-Through (#2 live path) | 0/TBD | Not started | - |
| 5. Cache Classification (#3) | 0/TBD | Not started | - |

**Next:** plan Phase 1 with `/gsd:plan-phase 1`.

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+4 (after v1.6)**
> (the `N+x` labels carry the dependency order; the `999.x` decimals are just stable IDs
> and need not match the order). Promote one at a time with `/gsd:review-backlog` (or
> start it via `/gsd:new-milestone`); defer detailed planning until promotion so each
> milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) shipped as v1.1 (2026-06-10).** **v1.2 —
> Consolidation** (cleanup, Phases 1-6) shipped 2026-06-12. Engine Surface Completion (former
> Backlog Phase 999.5) shipped as **v1.3** (2026-06-14). **N+2 — Margin, Leverage, Shorts &
> Trailing Stops (former Backlog Phase 999.4) shipped as v1.4 (2026-06-22).** **Backlog 999.2 is
> SPLIT:** its performance half **shipped as v1.5 — Backtest Performance Optimization (2026-06-26)**;
> its persistence half is **promoted as v1.6 — N+3b Persistence Foundation (active from 2026-06-27;
> marked PROMOTED-TO-v1.6 below).** The remaining `999.x` entry (999.3 = N+4 live) is a future milestone.

### Phase 999.2: N+3b — Persistence (PROMOTED-TO-v1.6 — both halves now shipped/active)

> **PROMOTED-TO-v1.6 (2026-06-27).** This backlog entry is **consumed**: its **performance half**
> shipped as **v1.5** (2026-06-26) and its **persistence half** is promoted as the active milestone
> **v1.6 — N+3b Persistence Foundation** (5 phases, 20 requirements — see `## Phases` above +
> [`REQUIREMENTS.md`](./REQUIREMENTS.md)). The design intent below is retained as the historical seed
> (like 999.4 → v1.4). Do not re-plan from here — plan from the v1.6 phases.

**Goal:** Durable PostgreSQL state — the infra prerequisite for live trading. The performance half
of this backlog entry was **split out and shipped as v1.5** (Backtest Performance Optimization,
2026-06-26); the **persistence half is promoted as v1.6** (active 2026-06-27). Sequenced AFTER the
performance work so we are not persisting unvalidated behavior.
**Requirements:** Delivered as the v1.6 SPINE / RESULT / OPS / RETAIN / CACHE / MIG / SEC / GATE set
(20 reqs) — see `REQUIREMENTS.md`.
**Plans:** promoted to v1.6 (see `## Phase Details`)

> **SPLIT (2026-06-23):** the **#5 profiler-guided performance pass** was promoted to **v1.5**
> (`perf/results/PERF-BASELINE-RESULTS.md` is the spike research; 10 reqs TOOL-01..04 + PERF-01..06).
> Persistence is a live-path, DB-gated concern not covered by the backtest oracle (a different North
> Star), so it follows v1.5 as its own milestone (**v1.6**, promoted 2026-06-27) rather than bundling
> with the perf gate.

Scope (intent only, persistence half — now realized in v1.6):

- **#4 permanent PostgreSQL storage** (orders, signals, fills, equity).
  `PostgreSQLOrderStorage` is currently a `NotImplementedError` placeholder. The v1.5
  order-storage indexing (PERF-01) designs its interface for extension so this backend satisfies
  the same contract. → **v1.6 OPS-01/02/03/04** (concrete SQL backends for all three operational seams).

- **#1 continued** — structural cleanup that the live-mode transition specifically demands.
  → **v1.6 SPINE-01/02/03** (the swappable SQL spine via composition).
- **FL-06** — SQL injection + hardcoded creds in `SqlHandler` (deferred out of v1.3; module
  is quarantined, belongs with persistence/SQL work). → **v1.6 SEC-01**.

Rationale: persistence is cross-cutting live-path infra; sequenced after v1.5 perf so the engine it
persists is both fast and validated.

### Phase 999.3: N+4 — Live Trading Readiness (capstone) (BACKLOG)

**Goal:** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence v1.6), and a streaming data engine.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):

- **#6 real-time data engine** ready for live.
- **#2 live execution engine.**
- **#7 production-ready universe / screener.**
- **Dynamic universe membership** — a lean `UniverseSelectionModel` poll seam for mid-run
  adds/removes (distinct from, and a prerequisite step toward, the full production screener
  above; grows in `universe/membership.py` per its documented D-20 growth target). Engine
  integration edges: warmup-on-add and open-position-handling-on-remove. Orthogonal to N+2
  (its pair-trading validation uses a fixed pair); sequenced here because it pairs with the
  real-time data engine (#6).
- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage (deferred out of v1.3; the
  live surface, not the backtest engine surface).
- **Perp realism — "Phase B" (FUND-01..04, deferred out of v1.4)** — funding-rate accrual at
  funding-timestamp boundaries, mark-price liquidation trigger (resolves phantom-wick risk),
  funding-data pipeline (ccxt `fetchFundingRateHistory` → per-symbol CSV; per-symbol interval, no
  hardcoded 8h), and `freqtrade` as a fourth cross-validation oracle. Purely additive on the v1.4
  Phase A core — only the carry model + liquidation trigger-price change. May land as its own
  milestone or fold into N+3/N+4 data work (see `notes/margin-leverage-shorts-999.4.md` §8).
- **Account abstraction (born here, with the connector)** — introduce a first-class `Account`
  domain object as the **reconciled local mirror of the venue's balance/margin state**. The
  **connector is the exchange adapter** (API keys, order I/O, fill/balance/funding streams — the
  `AbstractExchange`/provider boundary); the adapter *writes into* the `Account`, the `Account`
  does NOT talk to the venue. It is born here, not earlier, because in live the **source of truth
  flips**: backtest computes cash/positions locally (Portfolio = account), but live treats the
  **venue as truth**, so the engine needs a mirror to **reconcile** against (detect/repair drift
  from partial fills, fees, funding, liquidations, manual/other-bot trades). Reconciliation has
  no backtest analogue — which is exactly why the Account is a live concern, not an N+2 one.
  - **Shape:** `CashAccount` vs `MarginAccount` typing (nautilus pattern); one `Account` per
    `(venue, login)`; **Binance spot vs futures = two separate accounts** (cash vs margin);
    **IBKR subaccounts = N accounts under one connection**. Leverage/maintenance-margin/liq-price
    are **venue-controlled** live (set on the venue, cached in the `Account`) — distinct from the
    N+2 backtest model that *computes* them.
  - **Distinct driver from cross-margin.** Cross-margin (deferred beyond N+2 Phase B) needs an
    account *collateral pool* for account-wide liquidation math — a **backtest-accounting** driver.
    The live `Account` here is a **reconciliation** driver. Related, separately motivated; do not
    conflate.
  - **`user_id` is app-layer, strip from the engine.** Multi-tenancy ownership does NOT belong in
    the trading-domain `Portfolio` (current smell: `Portfolio.user_id`) and must NOT be relocated
    onto `Account`. The FastAPI-wrap layer owns the `user_id → portfolio_id/account_id` mapping
    externally; the engine stays owner-agnostic, keyed by its own domain IDs. Removing
    `Portfolio.user_id` is an independent cleanup (constructor-signature ripple) — kept OUT of v1.4
    to avoid muddying that milestone's golden-master re-baseline.
- **Live-start indicator backfill through the same `update(bar)` path** (deferred out of v1.5
  Phase 5 — stateful indicators; surfaced 2026-06-24). When `LiveBarFeed` is built, historical
  warmup at live-start MUST replay bars through the **identical `update(bar)` path** the backtest
  uses (Nautilus `request_bars()` analog) — no separate bulk `warmup_from(series)` fast-path, which
  would be a second state-building path that diverges and re-opens the look-ahead/parity audit the
  single-code-path stateful design closes. See `.planning/todos/live-backfill-through-update.md` +
  `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` §10.D-3.
- **Persistence live-drive + venue reconciliation** (the v1.6 operational store is built + tested
  on testcontainers Postgres here, but only **driven by a real live feed in N+4**). Cache↔broker
  reconciliation on restart needs a live broker adapter (research SUMMARY: deferred to N+4); the
  async/buffered write-through path is keep-only-measured (build only if the live loop profiles a stall).

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

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
