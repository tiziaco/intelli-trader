# Research Questions

Open questions awaiting investigation. Append new questions; resolved ones move to a findings doc or
get folded into the milestone's research output.

---

## N+3b — Persistence Foundation (seeded 2026-06-27 via gsd-explore)

Source: `.planning/notes/persistence-milestone-design.md`. These sharpen `/gsd:new-milestone`'s
ecosystem-research step — answer them with a proper framework survey + tech-stack decision, do not
start generic.

### Backend interchangeability (the spine)

- **Q1.** What is the single storage *interface* / abstraction that lets **SQLite, Turso (libSQL), and
  Postgres** be swapped by config alone (different `SqlSettings`)? Is **SQLAlchemy Core/ORM** the right
  unifier across all three drivers, or does Turso/libSQL need its own driver path? What breaks the
  "zero-friction swap" promise (dialect-specific SQL, JSON semantics, types)?
- **Q2.** **Turso / libSQL maturity** for our use: embedded-replica vs remote modes, Python driver
  status, Decimal/JSON support, transactional guarantees, and whether its perf advantage over plain
  SQLite is real for the backtest/optimization write pattern (batch dump + occasional read).
- **Q3.** Cross-backend **JSON/JSONB query semantics** — PG binary JSONB vs SQLite/Turso JSON-as-text
  (`json_extract`). Storage is portable; is *filtering on settings* (e.g. `WHERE settings->>'lookback' >
  20`) portable enough, or scalar-promote the few filterable params into real columns?

### Migrations

- **Q4.** **Alembic vs alternatives** for a dual embedded (SQLite/Turso) + server (Postgres) target. Does
  one migration chain cover all three dialects cleanly? Is migration tooling even warranted for the
  ephemeral backtest DB, or only for the live Postgres store? What's the lowest-friction setup?

### Results store (#1)

- **Q5.** Frame serialization format for the `run_artifacts` blob column: **Parquet-bytes vs Arrow IPC vs
  JSONB vs compressed pickle** — compression ratio, round-trip speed to a pandas DataFrame, Decimal
  fidelity, and cross-backend portability of the bytes.
- **Q6.** **Optuna integration** — if the optimization loop adopts Optuna, its trial storage already
  persists params+objective to SQLite/Postgres. Do we reuse Optuna's storage for the `runs` metadata
  (free) or keep our own schema and treat Optuna as just the sampler? How do the two DBs relate?

### Cache (#3)

- **Q7.** **Arrow vs hand-rolled** for the columnar hot-path data cache (bar windows / indicator state).
  Does Arrow's zero-copy columnar layout beat the v1.5 stateful-recurrence approach on the hot path, or
  add overhead? (Must not regress v1.5's perf wins — oracle-gated.)
- **Q8.** Inventory of existing ad-hoc caches to classify: enumerate every `lru_cache` and scattered
  in-memory lookup across modules; tag each as (a) hot-path data cache, (b) order/position lookup already
  covered by v1.5 secondary indexes, or (c) legitimate pure-function memoization to leave alone.

### Live write-through (#2)

- **Q9.** Write-through cache pattern (NautilusTrader-style) that guarantees **zero hot-path cost when
  off** (backtest) and correct durability when on (live). Async vs sync write-through; how to keep
  serialization off the hot path; end-of-run batch-dump mechanics.
- **Q10.** **Live retention / memory-bounding** (the second knob — cache ≠ store). How does the
  working-set cache stay bounded in a long-running live process: purge-on-terminalize vs age/count
  threshold (cf. Nautilus `purge_closed_orders` / `purge_closed_positions` / `purge_account_events`)?
  What stays resident (open positions, working orders, account snapshot, running accumulators) vs is
  evicted (closed positions, terminal orders, full transaction/metric history)? **Read-through**
  fallback for evicted records, and **restart rehydration** of the working set from the store
  (cache rebuildable; store = system of record). Backtest keeps retain-all (finite run).
