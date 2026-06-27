# Feature Research

**Domain:** Persistence + caching layer for an event-driven algo-trading backtest/live engine (v1.6 — N+3b Persistence Foundation)
**Researched:** 2026-06-27
**Confidence:** HIGH (reference frameworks surveyed against current docs; design grounded in the converged seed)

> Scope reminder (locked): three concerns IN — (#1) all-SQL results store, (#2) live operational
> store across three seams, (#3) cache inventory + classify. The optimization/parameter-sweep **LOOP
> is OUT** — this milestone builds the **substrate** only. Two retention models (cache ≠ store):
> backtest = retain-all + end-of-run dump; live = working-set cache + purge-on-terminalize +
> read-through + restart rehydration (Nautilus model).

---

## Reference-Framework Survey (current behavior)

The three pro-framework reference points named in the seed, surveyed against current docs. Each row
distills what is **table-stakes** (we must match) vs **differentiator** (worth borrowing) for us.

### NautilusTrader — `Cache` (bounded working set) + DB as system of record  `[HIGH]`

This is the closest analogue to our concern #2 and the model the seed explicitly adopts.

- **Cache = bounded working set, DB = system of record.** The `Cache` holds all trading-related data
  in memory but is *not* unbounded: market data is capped (default ~10,000 bars per bar type, ~10,000
  ticks per instrument; oldest evicted on overflow). The database backend is the durable system of
  record.
- **Persistent backends:** `RedisCacheConfig` and `PostgresCacheConfig` (via `CacheConfig.database`).
  Persistence is a **write-through** pattern with batched flushes (`buffer_interval_ms`, e.g. 100ms) —
  serialization is kept off the synchronous critical path.
- **Targeted purge APIs:** `cache.purge_order(client_order_id)`, `cache.purge_position(position_id)`,
  `cache.purge_instrument(instrument_id)` — each removes the record **and its index entries**, and
  **skips open orders/positions**.
- **Bulk age-swept purge APIs:** `cache.purge_closed_orders(ts_now, buffer_secs)`,
  `cache.purge_closed_positions(ts_now, buffer_secs)`, `cache.purge_account_events(ts_now,
  lookback_secs)`.
- **Automatic live purging:** `LiveExecEngineConfig` schedules the bulk sweeps —
  `purge_closed_orders_interval_mins` (sweep cadence, e.g. 15), `purge_closed_orders_buffer_mins`
  (min age before eligible, e.g. 60), and the analogous `purge_closed_positions_*` /
  `purge_account_events_*_mins`. `None` = never auto-purge.
- **Safety invariants (load-bearing for brackets):** open orders/positions are **never** purged (logs
  a warning, leaves intact); **linked/contingent orders keep the parent resident until all children
  close** — directly mirrors our bracket/OCO `parent_order_id`/`child_order_ids` contract.
- **Restart rehydration:** `flush_on_start` (default `False`) optionally clears the DB on boot;
  otherwise the cache **loads orders and positions from the cache database** on startup, then
  reconciliation generates any missing events to align cache↔venue (`position_check_interval_secs`
  ~30–60). Cache is rebuildable; DB is truth.
- **Backtest vs live:** backtest runs the cache **in-memory only**, synchronous (cache written before
  publish, no delay); live applies updates asynchronously (brief event→cache delay). Same
  `CacheConfig` surface in both modes — the *behavior* differs, not the API.

**Verdict:** Nautilus is the template for concern #2. We adopt purge-on-terminalize + age/buffer
sweep, the open-record and bracket-parent safety invariants, and restart-rehydration-from-store. We
do **not** need its Redis backend (single-process live engine) at this milestone.

### QuantConnect LEAN — `ObjectStore` (key-value research-artifact persistence)  `[HIGH]`

- A **key-value / file-system** store for `string`, JSON, XML, and `bytes` blobs; organization-scoped;
  readable from backtest, research, and live. ~50 MB free tier.
- Primary use: **transport artifacts between environments** (backtest → research → live) and persist
  trained ML models / serialized results.

**Verdict:** LEAN's ObjectStore validates our `run_artifacts` **blob-per-run** design (store a
serialized frame as bytes, not exploded rows) and the "results are artifacts you carry across
environments" framing. But it is a *key-value file store*, not a queryable metrics table — which is
exactly why our `runs` (queryable summary metrics + JSONB settings) is a **richer** design. We take
the blob-artifact idea; we reject key-value-only (we need cross-run SQL on metrics).

### Optuna — RDB trial storage (params + objective per trial)  `[HIGH]`

- `RDBStorage` is a **SQLAlchemy** layer over SQLite / Postgres / MySQL. Its schema is its own:
  `studies`, `trials` (FK `study_id`, `state`, timestamps), `trial_params` (FK `trial_id`,
  `param_name`, `param_value` **float**, `distribution_json`), `trial_values` (FK `trial_id`,
  `objective`, `value` **float**), plus `*_user_attributes`, `study_directions`, `version_info`.
- **Storage is decoupled from the sampler.** The **ask-and-tell** interface (`study.ask()` /
  `study.tell()`) and `add_trial()`/`add_trials()` let an *external* loop own trial lifecycle while
  Optuna only suggests params and records the scalar objective. `storage=None` → non-persistent
  `InMemoryStorage`.
- Optuna's value model is **float params + float objective(s)** only. Rich artifacts (a DataFrame
  equity curve, a trade log, heterogeneous module settings) do not fit its tables — you'd abuse
  `user_attrs` blobs.

**Verdict:** Optuna is a **sampler + scalar-objective bookkeeper**, not a results warehouse. This is
the crux of Q6 (resolved below): keep our richer schema, treat Optuna as the sampler, link by FK.

---

## Feature Landscape

### Table Stakes (a persistence layer is incomplete without these)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Swappable SQL interface (the spine)** | One interface, drivers selected by `SqlSettings` (config-not-code). Everything else hangs off it. | HIGH | THE win of the milestone (Q1/Q2). All stores share it. Must precede every concrete backend. |
| **Durable system-of-record store that survives restart** | A live trading engine that loses state on restart is unusable. | MEDIUM | Store holds *everything* incl. terminal history; cache is rebuildable from it. |
| **Order-mirror SQL backend** | `OrderStorageFactory` already has the seam; `PostgreSQLOrderStorage` is a `NotImplementedError` stub. | MEDIUM | Fill the existing stub on the shared interface. v1.5 secondary indexes carry over. |
| **Portfolio-state SQL backend** | `PortfolioStateStorageFactory` has no SQL backend; cash/position/transaction/metrics must persist. | MEDIUM | New `SqlPortfolioStateStorage`. Four manager domains. |
| **Strategy/signal SQL backend** | `SignalStorageFactory` has no SQL backend today. | LOW-MEDIUM | New `SqlSignalStorage`. Append-heavy. |
| **Results store: every run persisted** | A parameter sweep must never live only in memory; runs must be queryable later. | MEDIUM | `runs` (lean indexed metrics + JSONB settings) + `run_artifacts` (one frame blob/run). |
| **Migration / schema-versioning story** | Live Postgres store evolves; schema drift breaks restart. | MEDIUM | Dual embedded (SQLite/Turso) + server (Postgres) target (Q4). Maybe not needed for the ephemeral backtest DB. |
| **Restart rehydration of the working set** | Live boot must reconstruct open positions + working orders from the store. | MEDIUM | Nautilus model; load open/working only, rebuild snapshot + accumulators. |
| **Decimal fidelity at the persistence boundary** | Money is Decimal end-to-end (locked); float round-trip is a correctness defect. | MEDIUM | Turso native DECIMAL; verify SQLite/Postgres column types preserve it; never `Decimal(float)`. |
| **Zero hot-path cost when write-through is off (backtest)** | The byte-exact oracle + v1.5 perf baseline (15.7s/152.8MB) are the gate. | MEDIUM | Hot path must never synchronously serialize in backtest; dump is one end-of-run batch write. |
| **SQL-injection / hardcoded-creds hardening (FL-06)** | `SqlHandler` had a string-concat injection path (historically a `DROP TABLE` route was killed in M5b). | LOW | Parameterized queries only; creds from env/`SecretStr`, never hardcoded. |

### Differentiators (Nautilus-grade design most hobby engines lack)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Two-knob mode-awareness on the SAME seam** | `write-through` × `retention` decoupled: backtest = off + retain-all; live = on + working-set+purge. The seed's central insight (cache ≠ store). | HIGH | Extends `OrderStorageFactory` to all three seams, made mode-aware on *both* knobs. |
| **Single serialized-frame-blob artifact schema** | No per-bar row explosion ⇒ the "how big are your sweeps" question dissolves; scales to any sweep size. | LOW | One row → one DataFrame on read. Postgres TOASTs / SQLite spills overflow — free. Format = Q5. |
| **Optuna-ready FK seam (sweep-compatible, no sweep)** | Build the substrate now so a future Optuna sweep writes a `study_id`/`trial_id` into `runs` with zero schema rework. | LOW | Cheap future-proofing — see Q6. |
| **Turso/libSQL embedded-replica as research default** | Dialect sibling of SQLite (free fallback), Decimal-native, better write throughput for batch dumps; config-swap to Postgres for live. | MEDIUM | Maturity = Q2 (STACK). The interface makes the swap config-not-code. |
| **Classified cache (3 homes, not 1)** | Preserves v1.5 perf wins by routing hot-path data, storage indexes, and pure-fn memoization to their correct homes. | MEDIUM | Inventory + classify is itself a deliverable (Q7/Q8). |
| **Cross-backend JSONB settings query** | Heterogeneous per-strategy params with no schema churn; portable storage; filter where it matters. | MEDIUM | PG JSONB vs SQLite/Turso JSON1 text (Q3); scalar-promote the few filterable params into real columns. |
| **Bracket-aware purge safety** | Never evict an open position/order; keep bracket parent resident until all children terminal. | LOW | Direct port of Nautilus's contingency rule onto our `parent_order_id`/`child_order_ids`. |

### Anti-Features (seem good, create problems — flagged explicitly)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Collapse all three caches into one Arrow-backed object** | "Unify the messy caching." | Conflates hot-path *data*, storage *indexes*, and pure-fn *memoization* — three different lifetimes/owners. Seed calls this explicitly wrong. | Inventory + classify; route each to its correct home (data cache / storage indexes / leave `lru_cache` alone). |
| **Per-bar synchronous write-through in backtest** | "Symmetry — persist everything always." | Serializing on the hot path regresses the v1.5 baseline and breaks the zero-cost-when-off constraint. | Write-through OFF in backtest; single end-of-run batch dump. Sync write-through only in live. |
| **Explode equity/trade frames into per-bar SQL rows** | "Then I can SQL across all curves." | 20M-row bloat at large sweeps; the objection that killed naive all-SQL. | One serialized blob column per run (`run_artifacts`); DuckDB over exported frames for the rare cross-run scan. |
| **Reuse Optuna's storage as our results warehouse** | "Optuna already persists to SQL — free." | Optuna's schema is float-param/float-objective only; can't hold JSONB settings or frame blobs; couples us to Optuna's internal models + migration schedule. | Keep our richer schema; Optuna = sampler; link by FK (Q6 option b). |
| **Pure age/count eviction with no terminal-state gate** | "Simplest bound." | Could evict a still-open position, or leak if a record never ages out of an active window. | Purge-**on-terminalize** (event-driven) as primary + age/count sweep as safety net; gate skips open records (Nautilus). |
| **Redis cache backend now** | "Nautilus has it." | A distributed cache is unwarranted for a single-process live engine; adds an ops dependency. | In-process working-set cache; revisit only if/when multi-process (N+4+). |
| **Build the optimization/sweep LOOP this milestone** | "Persistence is for sweeps — finish the job." | Scope blow-up; the LOOP is a separate milestone. | Substrate only — the `runs` store must be a clean target a future sweep *writes to*. |
| **Second ID scheme / float money at the persistence edge** | "DB autoincrement IDs are simpler." | Violates single-UUIDv7 + Decimal-end-to-end locked decisions. | UUIDv7 `run_id`/keys; Decimal columns (Turso DECIMAL; verified types on SQLite/PG). |

---

## Feature Dependencies

```
Swappable SQL interface (the spine)            <-- gates EVERYTHING
    ├──required by──> PostgreSQLOrderStorage (order mirror)
    ├──required by──> SqlPortfolioStateStorage (cash/position/transaction/metrics)
    ├──required by──> SqlSignalStorage (strategy/signal)
    ├──required by──> Results store (runs + run_artifacts)
    └──required by──> Migration / schema-versioning story

Frame-blob serialization decision (Q5)
    └──required by──> run_artifacts writer

runs schema (incl. Optuna FK + objective_value columns)
    └──required by──> end-of-run dump writer
    └──enables──────> future Optuna sweep (writes study_id/trial_id) — NOT this milestone

Two-knob retention model (write-through × retention)
    └──required by──> live write-through wiring on all three seams
    └──required by──> purge-on-terminalize + read-through + restart rehydration

Cache inventory + classification (Q7/Q8)
    └──required by──> hot-path data-cache home decision
    └──enhances─────> preserving v1.5 perf wins (oracle-gated)

Bracket-parent purge safety  ──enhances──> purge-on-terminalize
```

### Dependency Notes

- **The spine precedes the per-seam backends.** All three concrete SQL classes and both stores are
  implementations of the one interface — the interface (and its dialect-portability decisions: JSON,
  Decimal types, parameter binding) must land first. This is the single most important ordering
  constraint for phase sequencing.
- **The retention model precedes live write-through.** You cannot wire purge-on-terminalize,
  read-through, or restart rehydration until the two-knob model (what stays vs evicts; cache ≠ store)
  is specified. Backtest's retain-all + write-through-off must be the default that costs nothing.
- **The frame-blob format (Q5) gates the `run_artifacts` writer**, but not the `runs` metrics table —
  the two can be sequenced independently.
- **The `runs` schema must include the Optuna FK + objective columns from day one** (cheap), so the
  later sweep loop needs no migration. Defining the schema is a prerequisite for the dump writer.
- **Cache classification is largely independent** of the SQL stores and can run in parallel; it only
  *converges* with the storage work where concern #3(b) — "order/position lookups" — turns out to be
  already solved by the v1.5 secondary indexes (so those entries route to the storage interface, not a
  new cache).

---

## MVP Definition

### Launch With (v1.6 — substrate only, ruthless)

- [ ] **Swappable SQL interface (the spine)** — one interface; backend selected by `SqlSettings`. The
      milestone's central deliverable; everything hangs off it.
- [ ] **At least the SQLite driver behind it**, plus the Turso and Postgres drivers wired to the same
      interface (driver/dialect details = STACK Q1/Q2; the *interface* is the MVP feature here).
- [ ] **Results store** — `runs` (indexed summary metrics + JSONB module settings + **Optuna FK +
      `objective_value` columns**) and `run_artifacts` (one serialized frame blob per run). End-of-run
      **batch dump** writer. Substrate only — no sweep loop.
- [ ] **Three concrete operational SQL backends** on the shared interface: fill `PostgreSQLOrderStorage`
      (currently `NotImplementedError`), new `SqlPortfolioStateStorage`, new `SqlSignalStorage`.
- [ ] **Two-knob mode-awareness** on all three seams: backtest = retain-all + write-through **off**
      (zero hot-path cost — oracle/perf-gated); live = working-set cache + write-through **on** +
      purge-on-terminalize + read-through + restart rehydration.
- [ ] **Migration / schema-versioning** for the live store (embedded + server target; Q4).
- [ ] **Cache inventory + classification** — enumerate every `lru_cache` / ad-hoc cache, tag (a)/(b)/(c),
      route each to its correct home; do **not** unify (Q7/Q8). Deliverable = the classification + the routing.
- [ ] **FL-06 SQL-injection / hardcoded-creds hardening** in `SqlHandler`.

### Add After Validation (N+4 — Live Trading Readiness)

- [ ] **Venue reconciliation** (cache↔venue) on restart — Nautilus `position_check_interval_secs`
      analogue. Trigger: live broker adapter exists.
- [ ] **Async / buffered write-through** (Nautilus `buffer_interval_ms` analogue) — trigger: measured
      sync write-through latency too high under live event rates.
- [ ] **Bounded recent-N / recent-T terminal window** tuning for reconciliation reads — trigger: real
      live recon query patterns observed.

### Future Consideration (v2+)

- [ ] **The optimization / parameter-sweep LOOP** (Optuna sampler writing to the substrate) — deferred
      by design; the substrate is built ready for it.
- [ ] **Redis cache backend** — only if the live engine goes multi-process.
- [ ] **DuckDB cross-run analytical queries** over exported frames — only when "metric across all
      equity curves at bar N" is actually needed.
- [ ] **Cross-backend JSONB filtering** beyond scalar-promote — only if rich runtime filtering on
      arbitrary settings becomes a real query pattern.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Swappable SQL interface (spine) | HIGH | HIGH | P1 |
| Two-knob mode-awareness (write-through × retention) | HIGH | HIGH | P1 |
| Results store (`runs` + `run_artifacts` + Optuna FK cols) | HIGH | MEDIUM | P1 |
| Three per-seam SQL backends | HIGH | MEDIUM | P1 |
| Restart rehydration of working set | HIGH | MEDIUM | P1 |
| Zero hot-path cost when write-through off | HIGH (gate) | MEDIUM | P1 |
| FL-06 injection/creds hardening | HIGH (security) | LOW | P1 |
| Migration / schema-versioning | MEDIUM | MEDIUM | P1 |
| Cache inventory + classification | MEDIUM | MEDIUM | P1 |
| Purge-on-terminalize + read-through | HIGH (live mem) | MEDIUM | P1 |
| Bracket-aware purge safety | MEDIUM | LOW | P2 |
| Cross-backend JSONB settings query | MEDIUM | MEDIUM | P2 |
| Venue reconciliation on restart | HIGH (live) | HIGH | P3 (N+4) |
| Optimization sweep LOOP | HIGH | HIGH | P3 (v2+) |
| Redis cache backend | LOW | MEDIUM | P3 (v2+) |

**Priority key:** P1 = must have for this milestone · P2 = should have, add when possible · P3 = future.

## Competitor Feature Analysis

| Feature | NautilusTrader | LEAN | Optuna | Our Approach |
|---------|----------------|------|--------|--------------|
| Working-set cache vs system-of-record DB | `Cache` (bounded) + Redis/Postgres | n/a (research store) | n/a | Adopt: working-set cache + SQL store; two retention knobs. |
| Retention / purge | `purge_closed_*` interval+buffer; skips open; bracket-parent rule | n/a | n/a | Adopt: purge-on-terminalize + age sweep safety net + bracket-parent safety. |
| Results / artifact persistence | Parquet data catalog | `ObjectStore` (KV blobs) | RDB trials (float only) | Hybrid-of-best: `runs` (queryable metrics+JSONB) + `run_artifacts` (blob, LEAN-style). |
| Optimization storage | n/a | n/a | `RDBStorage` (SQLAlchemy, SQLite/PG) | Treat Optuna as sampler; FK-link into our richer `runs` (Q6). |
| Backend swappability | Config-driven (Redis/PG) | Cloud KV | SQLAlchemy URL | One interface, three drivers, config-not-code (the spine). |
| Restart rehydration | Load orders/positions from cache DB; `flush_on_start` | Carries artifacts across envs | Resume study from storage | Load open positions + working orders + brackets; rebuild snapshot/accumulators. |

---

## Open-Question Resolutions (Q6, Q10)

### Q6 — Optuna integration: schema-compatibility (not building the sweep now)

**Recommendation: Option (b) — keep our own richer `runs` schema; treat Optuna purely as the
sampler/bookkeeper; FK-link the two.**  `[Confidence: HIGH]`

**Why (b) over (a) "reuse Optuna's storage" and (c) "fully independent":**

- **Against (a) reuse:** Optuna's `RDBStorage` schema is **float-param / float-objective only**
  (`trial_params.param_value` is a float, `trial_values.value` is a float; richer data is shoved into
  serialized `user_attrs`). Our `runs` needs **JSONB module settings** (heterogeneous per-strategy
  params), **multiple summary metrics** (Sharpe, CAGR, maxDD, #trades), and a **frame-blob artifact**
  (equity curve, trade log). None of that fits Optuna's tables cleanly. Reusing them also **couples our
  schema to Optuna's internal models**, which version and migrate on Optuna's schedule (the `version_info`
  table + schema-version checks) — a fragile coupling for our system of record.
- **Against (c) fully independent:** loses the cheap join "best trial → full run artifact" and risks
  the two stores duplicating sampler state.
- **For (b):** Optuna is **decoupled-storage by design** — the **ask-and-tell** interface
  (`study.ask()` / `study.tell()`) and `add_trial()` let our future sweep loop own trial lifecycle
  while Optuna only suggests params and records the scalar objective in *its* tables. Critically,
  **both schemas can live in the same database** (same SQLite file / same Postgres instance): Optuna
  namespaces its own tables (`studies`, `trials`, `trial_params`, `trial_values`, …) and ours stays
  `runs` / `run_artifacts` — **no table collision**. The link is a foreign key, not a shared row.

**What the `runs` schema needs TODAY to not paint us into a corner** (all cheap, all nullable for
ad-hoc backtest runs):

1. **`run_id`** — UUIDv7 primary key (single-ID-scheme; the stable handle a future sweep references).
2. **`study_id`** (TEXT, nullable) and **`trial_id`** (INTEGER/TEXT, nullable) — FK back to the Optuna
   trial that produced the run. NULL for ad-hoc/non-sweep runs.
3. **`objective_value`** (Decimal/REAL, nullable) — the single scalar a sampler optimizes
   (e.g. Sharpe). Even ad-hoc runs can populate it; the sweep just reads it back as the `tell()` value.
4. **`kind` / `source`** discriminator — e.g. `'backtest'` vs `'optimization_trial'` — so sweep rows
   are filterable without parsing FKs.
5. **Module settings in JSONB, keyed to match the param namespace** a sampler would suggest — so the
   sweep's `params` dict and our stored settings share names (clean join, no remapping later).

That is the entire seam: an FK pair + a scalar objective column + a discriminator. **No sampler, no
pruner, no optimize loop** — those are the deferred LOOP milestone. When the sweep arrives it adopts
Optuna purely as the sampler (ask → run our engine → write a full `runs` row → `tell()` the
`objective_value`), with both schemas coexisting in one DB.

### Q10 — Live retention / memory-bounding (the second knob: cache ≠ store)

**Recommendation: purge-on-terminalize (event-driven, primary) + an age/count sweep as a safety net,
modeled on Nautilus `purge_closed_*`; gated so open records are never evicted.**  `[Confidence: HIGH]`

**Eviction mechanism — both, not either/or (Nautilus uses both):**

- **Primary: purge-on-terminalize.** When an order reaches a terminal state
  (FILLED/CANCELLED/REJECTED/EXPIRED) or a position CLOSES, write its final state to the store and
  evict it from the working-set cache — after a small **buffer window** that keeps it briefly resident
  for reconciliation/status reads (Nautilus `*_buffer_mins`, default 60). Event-driven eviction
  respects trading-state semantics (you evict on *terminalization*, never on age of an open record).
- **Secondary: age/count sweep.** A periodic interval sweep (Nautilus `*_interval_mins`, default 15)
  catches anything a missed terminalize event left behind — a safety net against leaks, not the
  primary path.
- **Pure age/count alone is an anti-feature** (see table): without a terminal-state gate it can evict a
  still-open position. The gate is mandatory: **skip open orders/positions; keep a bracket parent
  resident until all children are terminal** (direct port of Nautilus's contingency rule onto our
  `parent_order_id`/`child_order_ids`).

**Resident vs evicted inventory:**

| STAYS RESIDENT (working set) | EVICTED (to store, after terminalize + buffer) |
|---|---|
| Open positions (+ current snapshot) | Closed positions (full) |
| Working/pending orders + their bracket linkage (parent + children) | Terminal orders (FILLED/CANCELLED/REJECTED/EXPIRED) past buffer |
| Current account/portfolio snapshot (cash, reserved margin, equity, `open_position_count`) | Full transaction history / cash-operation ledger |
| Running metric accumulators (v1.5 realised-PnL accumulator, peak equity, etc.) | Full per-bar metric history / account-event history |
| Recent-bars window + indicator state (v1.5 hot-path data cache — already bounded by `max_window`) | Bars/ticks beyond capacity (v1.5 `deque(maxlen)` already does this) |
| Bounded recent-N / recent-T terminal records (for in-flight reconciliation) | Everything older than that recon window |

**Read-through fallback for evicted records:** a query that needs a terminal/cold record (status query,
reconciliation, end-of-day reporting) checks the working-set cache first, misses, then reads from the
SQL store — **off the hot path, terminal records only** (an open position is *always* resident, so the
hot path never read-throughs). Optionally repopulate a short-lived LRU on read; do not promote cold
records back into the working set permanently.

**Restart rehydration of the working set (cache rebuildable; store = truth):**

1. Live boot → working-set cache empty (honor a `flush_on_start`-style toggle for clean-slate testing).
2. Load **only open positions + working orders (+ their brackets)** from the SQL store — not the full
   terminal history.
3. Rebuild the **account/portfolio snapshot** and the **running metric accumulators** from the persisted
   snapshot (read the last snapshot row; do **not** replay the entire transaction history).
4. (N+4, out of scope here) venue reconciliation aligns the rehydrated cache against the broker.

**Backtest stays retain-all (the other knob position):** finite run ⇒ no eviction, everything resident
for speed, write-through **off**, optional single end-of-run batch dump. The same seam, both knobs at
their backtest settings, costs the hot path nothing — which is what keeps the SMA_MACD oracle
byte-exact and the v1.5 perf baseline intact.

---

## Sources

- NautilusTrader — Cache concepts (purge APIs, bounded working set, backends, restart): https://nautilustrader.io/docs/latest/concepts/cache/  `[HIGH]`
- NautilusTrader — Live trading / reconciliation, `flush_on_start`, `position_check_interval_secs`: https://nautilustrader.io/docs/latest/concepts/live/  `[HIGH]`
- NautilusTrader — `LiveExecEngineConfig` purge scheduling params: https://nautilustrader.io/docs/nightly/api_reference/config/  `[HIGH]`
- NautilusTrader — restart/duplicate-order reconciliation behavior (real-world): https://github.com/nautechsystems/nautilus_trader/issues/3176  `[MEDIUM]`
- QuantConnect LEAN — Object Store (key-value blob persistence): https://www.quantconnect.com/docs/v2/writing-algorithms/object-store  `[HIGH]`
- Optuna — `RDBStorage` (SQLAlchemy, SQLite/Postgres): https://optuna.readthedocs.io/en/stable/reference/generated/optuna.storages.RDBStorage.html  `[HIGH]`
- Optuna — RDB schema models (studies/trials/trial_params/trial_values): https://github.com/optuna/optuna/blob/master/optuna/storages/_rdb/models.py  `[HIGH]`
- Optuna — Ask-and-Tell interface (sampler decoupled from loop): https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/009_ask_and_tell.html  `[HIGH]`
- Converged design seed: `.planning/notes/persistence-milestone-design.md`; open questions: `.planning/research/questions.md`  `[project]`

---
*Feature research for: trading-system persistence + caching layer (v1.6 — N+3b Persistence Foundation)*
*Researched: 2026-06-27*
