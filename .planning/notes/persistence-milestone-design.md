---
title: Persistence Foundation — N+3b Design Seed (999.2 persistence half)
date: 2026-06-27
context: gsd-explore session scoping N+3b before /gsd:new-milestone (framework survey + tech stack happen there)
status: designed — ready for /gsd:new-milestone research (open questions in .planning/research/questions.md)
---

# Design Seed: N+3b — Persistence Foundation

**Roadmap entry:** `.planning/ROADMAP.md` — 📋 N+3b — Persistence (persistence half of Backlog 999.2,
split out from v1.5; precedes N+4 Live Trading Readiness / 999.3).
**Scope of this doc:** the durable-storage + caching foundation that serves BOTH research/optimization
result persistence AND the live-trading operational store, plus consolidation of the ad-hoc caching
that accreted through v1.5. This is the *seed* — the framework survey and final tech-stack selection
are deferred to `/gsd:new-milestone`'s research step.

## Scope: three concerns, all IN, one unified class PER concern (never one class spanning all three)

1. **Research / optimization results store (#1)** — persist every backtest/optimization run so a full
   parameter sweep is never held in memory. Write-once-read-later, analytical.
2. **Live operational-state store (#2)** — fill the `PostgreSQLOrderStorage` `NotImplementedError`
   placeholder behind the existing `OrderStorageFactory` seam; extend the seam to portfolio/position
   state. Read-write, transactional, must survive restart.
3. **Unified in-memory cache (#3)** — formalize the caching that is "getting messy." **Finding: this is
   not one cache.** It is three things wearing one name (see Cache section); the work is *inventory +
   classify + route each to its correct home*, not collapse-into-one-class.

**The spine:** get the storage *interface* right so the **SQLite / Turso (libSQL) ↔ Postgres** swap is
**config, not code** — one interface, three drivers, selected by a different `SqlSettings`. SQLite/Turso
for backtest + optimization; Postgres for live. Everything else (write-through toggle, the cache,
migrations) hangs off this interface.

## Decided this session

### Results store (#1): ALL-SQL, not Parquet files

Rejected the hybrid (SQL-metrics + Parquet-frame-files) option **because Parquet was only ever a fit for
the backtest dump-at-end workload — never live.** Live trading appends incrementally (per fill, per bar);
Parquet is a write-once batch artifact you cannot cheaply append to. All-SQL maximizes backtest/live
symmetry: one interface, one migration story, one backend-swap. The two stores (#1 results, #2 live) stay
distinct stores but **share the one SQL interface** — that sharing IS the win.

**Schema shape (removes the only objection to all-SQL — 20M-equity-row bloat at large sweeps):**

| Table | Holds | Shape |
|---|---|---|
| `runs` | run_id, strategy, summary metrics (Sharpe, CAGR, maxDD, #trades), **module settings → JSONB** | one lean indexed row per run — the cross-sweep query surface ("top 10 by Sharpe where param_x > 5") |
| `run_artifacts` | run_id → **serialized frame** (equity curve, trade log) | one row per run; frame stored as a **single serialized blob/JSONB column**, NOT exploded into per-bar rows |

- One serialized frame column ⇒ no row-count explosion regardless of sweep size ⇒ the A-vs-B "how big
  are your sweeps" question **dissolves**; scales either way.
- Frames read back the way they're consumed: one row → one DataFrame (plot the winners).
- Side table keeps the hot `runs` metrics table lean: Postgres TOASTs large columns; SQLite/Turso spill
  to overflow pages — free.
- **Open option:** store the frame blob as **Parquet- or Arrow-encoded bytes inside the SQL column** —
  columnar compression inside SQL, no separate file lifecycle. (Research Q.)
- Cost accepted: cannot run SQL *across* all equity curves at once ("avg equity at bar 500 over all
  runs"). Rare; DuckDB over exported frames covers it if ever needed.
- **JSONB for module settings** — heterogeneous per-strategy params, no schema churn. Portable: PG native
  JSONB; SQLite/Turso JSON1. Caveat to verify: SQLite stores JSON as text (PG binary) → cross-backend
  JSON *query/filter* semantics need checking (storage is fine).

### Operational write-through cache (#2): mode-switched, free in backtest

Confirmed the NautilusTrader model (Cache + optional DB backend):

- **Backtest:** in-memory only, **no write-through**; optional single batch dump to SQL at end of run.
- **Live:** write-through to Postgres active.
- The operational cache and the storage backend are **one interface** — backtest binds it to the
  in-memory impl (the existing `InMemoryStorage` pattern → **zero I/O on the hot path → zero perf cost**);
  live binds it to in-memory + write-through. This is the existing `OrderStorageFactory` seam, extended
  to portfolio/position state and made mode-aware.
- **The one perf rule:** the hot path must never synchronously serialize when write-through is off. The
  end-of-run dump is a single batch write. If any design forces sync serialization on the hot path,
  reconsider — the no-perf-impact requirement is a hard constraint.

### Cache (#3): the "mess" is three different things — inventory + classify, don't unify into one class

| What | Example today | Right home |
|---|---|---|
| Columnar hot-path data | bar windows, indicator state (v1.5 stateful recurrences) | a real **data cache** — Arrow *could* fit (Research Q: Arrow vs hand-roll) |
| Order / position state lookups | scattered dict scans | the **storage interface's indexes** — v1.5 already added secondary indexes over the `{id: order}` dict; some may already be solved |
| Function memoization | scattered `lru_cache` | **mostly leave alone** — `lru_cache` on *pure* functions (e.g. v1.5 `get_type_hints` memo) is correct, not mess. Only `lru_cache` over *mutable domain state* is a bug to fix |

Collapsing all three into one Arrow-backed object would be wrong. The classification itself is a milestone
deliverable.

## Inherited hard constraints (carry into spec)

Decimal end-to-end (Parquet/Arrow have native DECIMAL — preserves money policy) · single UUIDv7 scheme ·
determinism (seeded RNG + injected clock) · queue-only cross-domain writes / read-model seams · tabs in
handler modules / 4-spaces in `config/`+`core/` · pytest `filterwarnings=["error"]` + `--strict-markers`.

## Pro-framework reference points (to be surveyed properly in /gsd:new-milestone)

Optuna (trial storage backend for optimization sweeps) · NautilusTrader (`ParquetDataCatalog` + `Cache`
component w/ optional Redis backend; backtest = in-mem cache only) · QuantConnect LEAN (`ObjectStore`).
