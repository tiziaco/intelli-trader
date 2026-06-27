# Architecture Research

**Domain:** Persistence + caching substrate bolted onto an event-driven backtest/live trading engine (one swappable SQL spine, four stores, classified cache)
**Researched:** 2026-06-27
**Confidence:** HIGH on the existing seams (read + cited by path below); HIGH on the spine layering (the three ABCs + the `OrderStorageFactory` template are real and consistent); HIGH on Q7/Q8 (grounded in v1.5 code); MEDIUM-HIGH on Q9 live write-through (the live path is deferred/unbuilt — the design is sound but unvalidated against a running live loop).

> **Scope note.** This is a SUBSEQUENT milestone on a converged design. The backend set (libSQL/Turso + SQLite + Postgres), all-SQL results store, and cache≠store split are locked. This doc designs *how those compose on the existing engine* — grounded in the storage seams actually in the tree — and answers Q1-arch, Q7, Q8, Q9. It threads the STACK researcher's load-bearing correction: **money on SQLite/libSQL MUST use a `DecimalAsText` `TypeDecorator`, never `Numeric`**, or `filterwarnings=["error"]` turns the SAWarning into a hard test failure and silently breaks the Decimal money policy.

## Standard Architecture

### System Overview — the spine, four stores, two retention models, one cache family

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  DOMAIN ABCs (UNCHANGED — the contracts the handlers/managers already depend   │
│  on; queue-only contract preserved, stores are injected read-models/sinks)     │
│  ┌───────────────┐ ┌──────────────────────┐ ┌─────────────┐ ┌───────────────┐  │
│  │ OrderStorage  │ │ PortfolioStateStorage│ │ SignalStore │ │ ResultsStore  │  │
│  │ order_handler/│ │ portfolio_handler/   │ │ strategy_   │ │  (NEW ABC —    │  │
│  │ base.py       │ │ base.py              │ │ handler/    │ │  #1 store)    │  │
│  │ (14 methods)  │ │ (~20 methods)        │ │ storage/    │ │               │  │
│  │               │ │                      │ │ base.py (4) │ │               │  │
│  └──────┬────────┘ └──────────┬───────────┘ └──────┬──────┘ └───────┬───────┘  │
├─────────┼─────────────────────┼────────────────────┼────────────────┼──────────┤
│  CONCRETE BACKENDS — exactly ONE class per concern (seed rule). Backtest = in-  │
│  memory retain-all (exists). Live/results = NEW SQL class, composes the spine.  │
│  ┌──────────────┐ ┌──────────────────────┐ ┌─────────────┐ ┌───────────────┐   │
│  │InMemoryOrder │ │InMemoryPortfolioState│ │InMemorySig- │ │ (no in-mem    │   │
│  │Storage  ✓    │ │Storage  ✓            │ │nalStore  ✓  │ │  results)     │   │
│  ├──────────────┤ ├──────────────────────┤ ├─────────────┤ ├───────────────┤   │
│  │SqlOrder      │ │SqlPortfolioState     │ │SqlSignal    │ │ SqlResults    │   │
│  │Storage  ★NEW │ │Storage  ★NEW         │ │Storage ★NEW │ │ Store  ★NEW   │   │
│  │(fills the    │ │(factory has NO sql   │ │(factory has │ │(runs +        │   │
│  │ PostgreSQL   │ │ backend today)       │ │ NO sql      │ │ run_artifacts)│   │
│  │ stub)        │ │                      │ │ backend)    │ │               │   │
│  └──────┬───────┘ └──────────┬───────────┘ └──────┬──────┘ └───────┬───────┘   │
│         └────────────────────┴───────┬────────────┴────────────────┘           │
├───────────────────────────────────────┼────────────────────────────────────────┤
│  THE SPINE — shared via COMPOSITION (has-a), never a cross-concern base class    │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  SqlBackend  (NEW — core/storage/ or itrader/storage/)                     │  │
│  │   • Engine + MetaData + connection/transaction management                  │  │
│  │   • DecimalAsText TypeDecorator  ← THE money-fidelity primitive (STACK)    │  │
│  │   • JSON().with_variant(JSONB,'postgresql')  ← portable settings column    │  │
│  │   • UUIDv7 column type (native uuid on PG / TEXT or 16-byte BLOB on SQLite) │  │
│  │   • Core insert/select/on_conflict constructs (NO raw dialect SQL strings) │  │
│  └────────────────────────────────────┬─────────────────────────────────────┘  │
│  ┌────────────────────────────────────┴─────────────────────────────────────┐  │
│  │  SqlSettings  (NEW — config/, 4-space)  → builds the engine URL            │  │
│  │   driver ∈ {sqlite+pysqlite, sqlite+libsql, postgresql+psycopg2}           │  │
│  │   + write_through:bool  + retention knobs  + creds via Settings.database_  │  │
│  │     url.get_secret_value() (SecretStr, already present — FL-06)            │  │
│  └────────────────────────────────────┬─────────────────────────────────────┘  │
├───────────────────────────────────────┼────────────────────────────────────────┤
│  DRIVERS (config, not code — one create_engine() call)                          │
│   sqlite+pysqlite://  (default/backtest, results)   sqlite+libsql://  (Turso,    │
│   opt-in extra)        postgresql+psycopg2://  (live system of record)          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Domain ABCs (`OrderStorage`, `PortfolioStateStorage`, `SignalStore`) | The query/write contract handlers depend on — **unchanged this milestone** | Already in tree: `order_handler/base.py`, `portfolio_handler/base.py`, `strategy_handler/storage/base.py` |
| `ResultsStore` (NEW ABC) | Write-once-read-later contract for `runs` + `run_artifacts` (#1) | New `abc.ABC`; only `add_run`/`add_artifact`/query methods — no retention model |
| In-memory backends (×3) | Backtest retain-all working store; the v1.5 secondary indexes live here | Already in tree; flat-dict + derived indexes |
| `Sql{Order,PortfolioState,Signal}Storage` + `SqlResultsStore` (NEW ×4) | One SQL class **per concern**, each implements its ABC, each **composes** `SqlBackend` | SQLAlchemy Core `Table` defs + the shared backend; one module per concern under each domain's `storage/` |
| `SqlBackend` (NEW) | The shared spine: Engine, MetaData, `DecimalAsText`, JSON variant, UUIDv7 type, Core SQL | Composition target injected into all four SQL classes; SQLAlchemy 2.0 Core (already a dep) |
| `SqlSettings` (NEW) | Backend selection (driver/URL), write-through toggle, retention knobs | Pydantic model in `config/` reading `Settings.database_url` (SecretStr) |
| Factories (`OrderStorageFactory` + 2 siblings) | `environment` → backend class; **the seam to extend** to SQL | Already in tree; today `'live'` → NotImplementedError stub |
| Live write-through cache (NEW, Q9/Q10) | Working-set cache + write-through + purge-on-terminalize + read-through + rehydrate | A live-only wrapper composing an in-memory working set + `SqlBackend`; **not built on backtest path** |

## Recommended Project Structure

```
itrader/
├── storage/                          # NEW — the shared spine (one home, imported by all four concerns)
│   ├── __init__.py                   #   re-export SqlBackend, DecimalAsText
│   ├── backend.py                    #   SqlBackend: Engine/MetaData/session, create_engine(SqlSettings.url())
│   ├── types.py                      #   DecimalAsText TypeDecorator, UUIDv7 type, JSON-variant helper  ← STACK money fix
│   └── migrations/                   #   Alembic chain (live Postgres ONLY; results DB uses create_all())
│       ├── env.py                    #   render_as_batch=True (SQLite/libSQL ALTER limits, Q4)
│       └── versions/
├── config/
│   ├── settings.py                   # EXISTS — Settings.database_url: SecretStr (FL-06 creds source)
│   └── sql.py                        # NEW (4-space) — SqlSettings(driver, url parts, write_through, retention)
├── order_handler/
│   ├── base.py                       # EXISTS — OrderStorage ABC (UNCHANGED)
│   └── storage/
│       ├── in_memory_storage.py      # EXISTS — retain-all + v1.5 derived indexes
│       ├── postgresql_storage.py     # EXISTS stub → REPLACE with sql_storage.py
│       ├── sql_storage.py            # NEW — SqlOrderStorage(OrderStorage), composes SqlBackend
│       └── storage_factory.py        # EXTEND — 'live'/'sql' → SqlOrderStorage(backend)
├── portfolio_handler/
│   ├── base.py                       # EXISTS — PortfolioStateStorage ABC (UNCHANGED)
│   └── storage/
│       ├── in_memory_storage.py      # EXISTS — retain-all
│       ├── sql_storage.py            # NEW — SqlPortfolioStateStorage(PortfolioStateStorage)
│       └── storage_factory.py        # EXTEND — 'live' arm (today raises NotImplementedError)
├── strategy_handler/
│   └── storage/
│       ├── base.py                   # EXISTS — SignalStore ABC (UNCHANGED)
│       ├── in_memory_storage.py      # EXISTS
│       ├── sql_storage.py            # NEW — SqlSignalStorage(SignalStore)
│       └── storage_factory.py        # EXTEND — 'live' arm (today raises NotImplementedError)
├── results/                          # NEW — the #1 results store (its own concern, shares the spine)
│   ├── base.py                       #   ResultsStore ABC
│   ├── sql_storage.py                #   SqlResultsStore(ResultsStore) — runs + run_artifacts
│   └── frame_codec.py                #   pyarrow Parquet-bytes encode/decode w/ EXPLICIT decimal128 schema (Q5/STACK)
└── price_handler/store/
    └── sql_store.py                  # EXISTS — SqlHandler; FL-06 rework onto the spine (creds + parameterized SQL)
```

### Structure Rationale

- **`itrader/storage/` is a NEW shared home, NOT a new base ABC.** The spine is `SqlBackend` (an engine/type/SQL helper) that the four SQL classes *hold a reference to*. There is deliberately no `SqlStorageBase` that all four inherit — that would re-introduce a cross-concern god class the seed explicitly rejects ("one unified class PER concern, never one class spanning all three"). `core/` cannot host this (it imports nothing inside `itrader`, but `SqlBackend` pulls `config/SqlSettings`), so a sibling `itrader/storage/` package is the right layer.
- **Each concrete SQL class lives beside its existing in-memory sibling** (`order_handler/storage/sql_storage.py` next to `in_memory_storage.py`). This keeps the per-domain `storage/` package the single home for that concern's backends and lets the existing factory pick between siblings — exactly the established `OrderStorageFactory` shape.
- **`results/` is its own top-level package**, not folded into a handler. It is a write-once analytical store with no event-loop caller and no domain handler — it does not belong under `order_handler`/`portfolio_handler`. It shares the spine (the win) but is a distinct store (locked).
- **`DecimalAsText` lives in `storage/types.py`, applied uniformly** across all four SQL classes' money columns. One decorator, every dialect, byte-exact money + no SAWarning (STACK Q1/Q5).
- **Indentation:** `config/sql.py`, `storage/`, `results/` use **4 spaces** (config/core/newer-module convention). The handler `storage/sql_storage.py` files match their existing in-memory sibling's indentation — `order_handler`/`portfolio_handler` storage use **tabs**; `strategy_handler/storage/` uses **4 spaces** (its files declare it). Match the file, never normalize.

## Architectural Patterns

### Pattern 1: The spine via composition — domain ABC ← concrete SQL class ← shared `SqlBackend` (Q1-arch)

**What:** Each concern keeps its existing narrow domain ABC. A new concrete `Sql<Concern>Storage` *implements that ABC* and *composes* the shared `SqlBackend` (which owns the Engine, `DecimalAsText`, the JSON-variant settings type, the UUIDv7 type, and dialect-aware Core SQL). The backend is built from `SqlSettings`, so the SQLite ⇄ libSQL ⇄ Postgres swap is one engine-URL change.

**When to use:** All four stores. The sharing is the engine/type/dialect layer; the contract stays per-concern.

**Trade-offs:** Composition (not inheritance) means each SQL class writes its own `Table` definitions and CRUD — slightly more code than a god base class, but it honors the 3-ABC boundary, keeps mypy-strict types per concern, and prevents one concern's schema change from rippling across the others. This is the correct trade for a money-correctness engine.

**Example:**
```python
# itrader/storage/backend.py
class SqlBackend:
    def __init__(self, settings: SqlSettings) -> None:
        self.engine = create_engine(settings.url())      # driver from config, not code
        self.metadata = MetaData()
    # money columns use DecimalAsText (storage/types.py), NOT Numeric — see STACK

# itrader/order_handler/storage/sql_storage.py
class SqlOrderStorage(OrderStorage):                      # implements the UNCHANGED ABC
    def __init__(self, backend: SqlBackend) -> None:
        self._backend = backend                           # COMPOSE the spine, don't inherit
        self._orders = Table("orders", backend.metadata, ...)  # own table, own schema
    def get_active_orders(self, portfolio_id=None):       # the v1.5 _active_by_portfolio index
        # becomes  WHERE status IN ('PENDING','PARTIALLY_FILLED') AND portfolio_id=?
        ...
```

### Pattern 2: Backend-selection write-through — zero hot-path cost when off (Q9)

**What:** Write-through is **not a runtime flag checked inside hot-path write methods**. It is a *backend choice at wiring*: the backtest factory returns the in-memory retain-all backend, which contains **no serialization code at all**; the live factory returns the SQL-backed working-set cache, which write-throughs on every mutate. The toggle lives in `SqlSettings.write_through`, consumed by the factory — not by the per-tick path.

**When to use:** All three operational seams. This is the existing `OrderStorageFactory.create(environment)` pattern made two-knob-aware (write-through AND retention).

**Trade-offs:** No per-write branch means no W1/W2 regression and no risk of an accidental serialize on the hot path — the cost is provably zero because the code path doesn't exist in the backtest backend. The trade is two backend classes per concern instead of one flagged class; that is exactly what the engine already does (in-memory vs SQL) and is the right shape.

**Example:**
```python
# backtest:  environment='backtest' → InMemoryOrderStorage (no .serialize anywhere)
# live:      environment='live'      → SqlWorkingSetOrderStorage(in_mem_workingset, SqlBackend)
#   on add_order():   self._cache.add(order); self._backend.upsert(order)   # write-through
#   on terminalize(): self._backend.upsert(order); self._cache.evict(order.id)  # purge (Q10)
```

### Pattern 3: End-of-run batch dump for backtest (Q9) — one transaction, off the loop

**What:** Backtest keeps retain-all in memory for the whole finite run (correct — the run is finite). Persistence is an OPTIONAL single batch write *after* the for-loop, in `BacktestRunner` alongside the existing run-end EXPIRE sweep (`trading_system/backtest_runner.py`). The in-memory backend exposes the data; a dumper bulk-inserts it in one `SqlBackend` transaction. The results store (#1) writes its `runs` summary row + `run_artifacts` Parquet blob at the same post-loop point.

**When to use:** Backtest result persistence (#1) and any optional backtest operational dump. Never per-tick.

**Trade-offs:** Defers all serialization to one bulk write → zero hot-path cost (the hard constraint) and the cheapest possible DB pattern (single transaction). The cost: a crash mid-backtest loses the run — acceptable, because a backtest is re-runnable (the results DB is ephemeral, Q4).

### Pattern 4: Two retention models, not one (Q10) — cache ≠ store

**What:** `SqlSettings` carries the retention knob independently of write-through. Backtest = retain-all (finite run, no eviction). Live = working-set cache (open positions, working orders + brackets, account snapshot, running accumulators) + purge-on-terminalize → final state to store then evict from cache; read-through to store for cold/terminal records; restart → rehydrate working set from store. The store is the system of record; the cache is rebuildable.

**When to use:** The live operational store only. Backtest stays retain-all (the current in-memory backend IS this — correct because finite).

**Trade-offs:** Bounds live memory by active-trading size, not run length (the memory rule). The cost is read-through complexity for terminal records — acceptable and Nautilus-precedented.

## Data Flow

### Backtest flow (write-through OFF) — the byte-exact path, persistence is post-loop

```
for time in TimeGenerator:                         # backtest_runner.py loop (UNCHANGED, hot)
    TIME → BAR → SIGNAL → ORDER → FILL             # in-memory retain-all stores, NO serialization
        ↓
[run-end EXPIRE sweep]  +  [OPTIONAL batch dump]    # post-loop, ONE transaction
        ↓                          ↓
   (existing)            SqlResultsStore.add_run(summary)        → runs table
                         SqlResultsStore.add_artifact(frame)     → run_artifacts (Parquet-bytes blob)
                         [optional] dump order/portfolio/signal  → SQL (single bulk insert)
```

The hot loop never touches SQL. The oracle stays byte-exact (134 / `46189.87730727451`); W1/W2 hold against the frozen 15.7 s / 152.8 MB baseline because no serialize call exists on the per-tick path.

### Live flow (write-through ON) — durability before the engine moves on

```
FILL event (daemon thread)
    ↓
PortfolioHandler.on_fill → Portfolio mutates → state_storage.add_transaction(...)
    ↓                                                  ↓ (SQL backend)
working-set cache update                        write-through INSERT (sync, in txn)
    ↓
order terminalizes (FILLED/CANCELLED/REJECTED/EXPIRED)
    ↓
SqlBackend.upsert(final state)  →  cache.evict(order_id)        # purge-on-terminalize (Q10)
    ↓
later status/recon read of a terminal order  →  read-through SELECT (off hot path)
    ↓
restart  →  cache empty  →  rehydrate working set: SELECT open positions + active orders
```

### Restart rehydration (Q10)

```
LiveTradingSystem.start()
   → SqlOrderStorage.get_active_orders()      (WHERE status IN active)   → rebuild working orders
   → SqlPortfolioStateStorage.get_positions() (WHERE closed_at IS NULL)  → rebuild open positions
   → reconstruct running accumulators from the rehydrated working set
   (cache is rebuildable; store is truth)
```

## Scaling Considerations

| Scale | Architecture adjustments |
|-------|--------------------------|
| Small sweep (10s–100s of runs) | SQLite results DB, `create_all()`, end-of-run dump. `runs` lean + `run_artifacts` Parquet blob. No tuning needed. |
| Large sweep (10k+ runs) | Same all-SQL schema scales — one blob row per run, no per-bar explosion (the seed's bloat objection dissolves). Scalar-promote sweepable params to indexed columns (Q3) so `ORDER BY sharpe LIMIT 10` stays fast. Optionally libSQL/Turso for shared cross-machine sweep storage (operational, not perf — Q2). |
| Live, single account, long-running | Working-set cache bounded by open positions + working orders (Q10). Postgres system of record. Sync write-through fine — fills are not sub-ms latency-critical here. |
| Live, high event rate | If profiling shows sync DB write stalls the queue drain, move append-heavy writes (transactions, snapshots) to a batched async writer thread; keep create/terminalize sync for durability. Do **not** pre-build this — measure first. |

### Scaling priorities

1. **First bottleneck (live):** synchronous write-through on the single daemon event thread. Fix order: batch the append-only writes (transactions/snapshots) behind an async queue *only if measured*; keep terminal/create sync.
2. **Second bottleneck (sweeps):** `runs` table query surface. Fix: scalar-promote filter params to indexed columns (already the Q3 recommendation) — not JSON filtering.

## Anti-Patterns

### Anti-Pattern 1: `Numeric`/`DECIMAL` money column on SQLite/libSQL

**What people do:** Use SQLAlchemy `Numeric(asdecimal=True)` for money columns because Postgres NUMERIC is lossless.
**Why it's wrong:** SQLite/libSQL have **no lossless DECIMAL** — `Numeric` float-coerces and emits `SAWarning`, which under this project's `filterwarnings=["error"]` is a **hard test failure**, and silently violates the Decimal-end-to-end money policy.
**Do this instead:** A single `DecimalAsText` `TypeDecorator` (store Decimal as TEXT) in `storage/types.py`, applied uniformly to every money column on all three dialects. `Numeric` is acceptable ONLY on the Postgres-only live path, but use the decorator everywhere for byte-exact cross-backend parity (STACK Q1/Q5).

### Anti-Pattern 2: One god `SqlStorage` class spanning all concerns

**What people do:** Build a single `SqlStorage` base (or one class) that handles orders, portfolio state, signals, and results "to share the engine."
**Why it's wrong:** Violates the seed's one-class-per-concern rule and collapses the existing three-ABC boundary; one concern's schema change ripples across all; mypy-strict types blur.
**Do this instead:** Share via **composition** — a `SqlBackend` the four `Sql<Concern>Storage` classes hold a reference to. Each implements its own unchanged domain ABC.

### Anti-Pattern 3: A `write_through` flag checked on the hot path

**What people do:** Put `if self.write_through: self._serialize(order)` inside `add_order`/`update_order`.
**Why it's wrong:** Adds a per-write branch (and the temptation to serialize) on the byte-exact hot loop → W1/W2 regression risk, and the backtest path now *contains* serialize code that could fire.
**Do this instead:** Backend selection at wiring (Pattern 2). The backtest backend has **no serialization code at all**; write-through is a different class chosen by the factory from `SqlSettings`. Zero cost when off, structurally.

### Anti-Pattern 4: Routing the backtest hot loop through SQL

**What people do:** Once SQL backends exist, point the backtest at them "for consistency."
**Why it's wrong:** SQL per-tick reads/writes obliterate the v1.5 wins (the in-memory derived indexes, stateful indicators, prebuilt bars). The SQL backends are for **live** (write-through) and **results** (end-of-run dump) only.
**Do this instead:** Backtest stays in-memory retain-all; SQL is the live system of record + the ephemeral results DB.

### Anti-Pattern 5: Arrow/pyarrow on the per-tick path

**What people do:** Adopt Arrow's zero-copy columnar layout for the bar-window / indicator hot path "because columnar is fast."
**Why it's wrong:** The hot path is **single-bar incremental** (O(1) stateful recurrence), not bulk-columnar. Arrow forces per-tick array↔scalar conversion = overhead, re-introducing the columnar-slice-per-tick cost v1.5 deliberately removed (PERF-05/06), and risks float/Decimal drift against the byte-exact oracle.
**Do this instead:** pyarrow only at the **serialization boundary** — the once-per-run `run_artifacts` Parquet blob (Q7). It never touches the hot loop.

### Anti-Pattern 6: Persisting via the event queue

**What people do:** Emit a "persist" event so the store writes off an event.
**Why it's wrong:** The stores are injected read-models/sinks, not domain handlers; routing persistence through `global_queue` would add an event type, ordering coupling, and a queue stall risk on the daemon thread.
**Do this instead:** Write-through happens *inside* the storage backend the handler already holds (the same way `InMemoryOrderStorage` is called today) — off the queue, preserving the queue-only cross-domain-*write* contract (which governs handler-to-handler writes, not a handler's own injected store).

### Anti-Pattern 7: f-string SQL / symbol-as-table-name (the FL-06 defect, live)

**What people do:** What `price_handler/store/sql_store.py` does today — `text(f'DROP TABLE IF EXISTS {sym}')` (L35), `to_sql(symbol, ...)` / `read_sql(symbol, ...)` (L56/L69), and a hardcoded `tizianoiacovelli:1234@localhost` URL (L17).
**Why it's wrong:** SQL injection via symbol names + hardcoded credentials in source.
**Do this instead:** SQLAlchemy Core constructs + bound params + quoted identifiers (or one table with a `symbol` column); creds from `Settings.database_url.get_secret_value()` (SecretStr, already present). Rework `SqlHandler` onto the spine.

### Anti-Pattern 8: Unbounded live working-set cache

**What people do:** Let the live cache keep terminal orders/closed positions resident "for status queries."
**Why it's wrong:** Memory grows with run length, not active trading — a leak in a long-running live process.
**Do this instead:** Purge-on-terminalize + read-through to the store for cold records; optional bounded recent-N window for recon (Q10).

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| SQLite (backtest/results) | `sqlite+pysqlite://` via `SqlBackend`; `create_all()` schema | stdlib, zero new deps; the dialect-sibling fallback for libSQL |
| libSQL/Turso (opt-in) | `sqlite+libsql://` via `sqlalchemy-libsql` (optional extra) | Beta/stale driver; escape = revert one URL to `sqlite+pysqlite` (STACK Q2) |
| Postgres (live) | `postgresql+psycopg2://` from `Settings.database_url` (SecretStr) | system of record; `Numeric` money safe here but use `DecimalAsText` for parity |
| Alembic | live Postgres migration chain only; `render_as_batch=True` | results DB is ephemeral → `create_all()`, not migrated (Q4) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Handler ↔ its storage backend | direct method call on the injected store | NOT cross-domain — the handler owns its store (queue-only governs handler↔handler) |
| Four SQL classes ↔ `SqlBackend` | composition (constructor injection) | the spine; one backend instance per process, shared |
| `SqlSettings` ↔ factories | factory reads settings to pick backend + URL | extends the existing `environment` arg with the two knobs |
| Composition root ↔ factories | `compose.py`/`backtest_runner.py` (backtest), `live_trading_system.py` (live) wire `environment` + `SqlSettings` | live wiring already calls `OrderStorageFactory.create('live', _SYSTEM_DB_URL)` and falls back on NotImplementedError (L136) — the seam to fill |
| `Settings.database_url` ↔ `SqlSettings` | SecretStr → live engine URL | FL-06: replaces the hardcoded `SqlHandler` creds |

## Build-Order Dependencies

```
1. THE SPINE FIRST  (nothing else compiles without it)
   storage/types.py  (DecimalAsText, UUIDv7, JSON-variant)  →  storage/backend.py (SqlBackend)
   →  config/sql.py (SqlSettings + engine-URL selection)  →  FL-06 SqlHandler rework onto the spine
        │
2. RESULTS STORE (#1) SECOND  — simplest consumer, validates the spine end-to-end, oracle-dark
   results/base.py (ResultsStore ABC)  →  results/frame_codec.py (pyarrow, explicit decimal128)
   →  results/sql_storage.py (runs + run_artifacts)  →  backtest end-of-run dump (Pattern 3)
   (exercises DecimalAsText + Parquet-blob + Q3 scalar-promotion on an ephemeral SQLite DB,
    with ZERO hot-loop risk — proves the spine before any live path touches it)
        │
3. THREE OPERATIONAL SQL BACKENDS THIRD  (each implements its existing ABC on the spine)
   order_handler/storage/sql_storage.py  (the v1.5 indexes show the exact WHERE clauses)
   →  portfolio_handler/storage/sql_storage.py  →  strategy_handler/storage/sql_storage.py
   (retain-all-capable; extend each factory's 'live'/'sql' arm)
        │
4. RETENTION MODEL + LIVE WRITE-THROUGH FOURTH  (only after the SQL backends exist)
   design the two-knob retention (Pattern 4) BEFORE wiring live write-through
   →  working-set cache + write-through + purge-on-terminalize + read-through + rehydration
```

**Hard ordering rules:** spine before backends; the results store validates the spine before any live code; the retention model is designed before live write-through is wired.

---

## Open-Question Resolutions (Q1-arch, Q7, Q8, Q9)

### Q1-arch — Interface architecture: the spine layering

**Recommendation: Keep all three existing domain ABCs unchanged. Add a fourth (`ResultsStore`). Build ONE concrete `Sql<Concern>Storage` per concern, each implementing its ABC and *composing* a shared `SqlBackend`. The spine is the `SqlBackend` engine/type/dialect layer + `DecimalAsText` + driver-select via `SqlSettings` — shared by composition, never by a cross-concern base class.**

The three ABCs are genuinely different shapes and must stay separate:
- `OrderStorage` (`order_handler/base.py`, 14 methods) — UUID-keyed CRUD + status/ticker/time queries. Its v1.5 in-memory derived indexes (`_active_by_portfolio`, `_by_status`, `_last_indexed_status` in `in_memory_storage.py`) map 1:1 to SQL `WHERE`/indexes — the ABC's own docstring (L244-253) already audited this: "every ABC method is SQL-expressible by a future PostgreSQLOrderStorage." The seam was designed for this.
- `PortfolioStateStorage` (`portfolio_handler/base.py`, ~20 methods) — positions (open/closed), transactions, reserved cash, locked margin, cash operations, metrics snapshots. Far wider than orders; full-precision Decimal money throughout (reservations, locked margin) — every one of those is a `DecimalAsText` column.
- `SignalStore` (`strategy_handler/storage/base.py`, 4 methods) — `add`/`get_all`/`by_strategy`/`by_ticker` over the `SignalRecord` msgspec.Struct (which carries Decimal stop/take/qty/entry + a JSON `config` dict — maps to `DecimalAsText` columns + the JSON-variant settings column).

The layering, concrete:
```
OrderStorage (ABC, unchanged)        ← SqlOrderStorage          ─┐
PortfolioStateStorage (ABC, unchanged) ← SqlPortfolioStateStorage ┤
SignalStore (ABC, unchanged)         ← SqlSignalStorage         ─┼─→ SqlBackend
ResultsStore (NEW ABC)               ← SqlResultsStore          ─┘   (Engine/MetaData/Core SQL
                                                                       + DecimalAsText
                                                                       + JSON.with_variant(JSONB,'pg')
                                                                       + UUIDv7 type)
                                                                  ←── SqlSettings → create_engine(url)
```
The "one unified class per concern" rule is honored: four concerns, four SQL classes, each owning its `Table` definitions. The *only* thing shared is the backend (engine + money/JSON/UUID types + dialect-aware Core constructs). What breaks the zero-friction swap and the mitigations (all from STACK Q1, threaded here): (1) **money** → `DecimalAsText` uniformly, the #1 issue; (2) **JSON** → `JSON().with_variant(JSONB,'postgresql')` for storage, scalar-promote for filtering (Q3); (3) **dialect DDL/SQL** → stay on Core constructs (`insert().on_conflict_*`), never raw dialect strings (the FL-06 f-string DDL is the exact anti-pattern to delete).

### Q7 — Arrow vs hand-rolled for the hot-path columnar data cache: LEAVE THE v1.5 HOT PATH ALONE

**Recommendation: Do NOT put Arrow on the per-tick path. The v1.5 stateful-recurrence + shared-bar-feed design beats Arrow for this workload. pyarrow enters the system ONLY at the serialization boundary (the `run_artifacts` Parquet blob, Q5).**

What the v1.5 hot-path cache actually is (grounded in code):
- `price_handler/feed/bar_feed.py`: `_prebuilt` (`dict[ticker, dict[datetime, Bar]]`, L241), `_newest_bars` (L326), and the monotonic int64 `_cursor`/`_cursor_cut` window (L305-316, PERF-06) — prebuilt scalar `Bar` structs served by dict lookup, zero per-tick `searchsorted`/`iloc`.
- `strategy_handler/indicators/catalog.py` + `handle.py`: stateful O(1) recurrences (`_SMAState._ring`/`_sum`, `_EMAState`, `_MACDHistState`, `_RSIState`) self-buffering in a bounded `deque(maxlen=depth)` (PERF-05, Model B). `feed/cache_registration.py` derives the shared-cache capacity at wiring.

Why Arrow loses here: the access pattern is **single-bar incremental update** (one `state.update(x)` per tick, O(1)), not bulk-columnar scan. Arrow's zero-copy columnar layout wins when you slice/scan many rows at once; on a one-value-at-a-time recurrence it adds array↔Python-scalar conversion overhead every tick — precisely the columnar-slice-per-tick cost v1.5 *removed* by going stateful. Worse, routing money/indicator values through Arrow arrays risks float/Decimal representation drift against the byte-exact oracle. The v1.5 design is the SOTA pattern (Nautilus/LEAN "Model B" stateful indicators, cited in the v1.5 spec) for exactly this reason.

Where Arrow *does* belong: the once-per-run `run_artifacts` frame (equity curve, trade log) → Parquet-bytes via pyarrow with an explicit `decimal128(p,s)` schema (STACK Q5). That is bulk-columnar, off the hot path, and Arrow's actual sweet spot. **Net: pyarrow is added, but it never touches a per-tick code path** — honoring the no-W1/W2-regression hard constraint structurally.

### Q8 — Cache inventory + classification (concrete grep results)

Every real cache/memo hit across `itrader/`, classified into (a) hot-path columnar data cache, (b) order/position lookup already solved by v1.5 secondary indexes, (c) legitimate pure-function/explicitly-invalidated memoization to LEAVE ALONE.

| # | Site (path:line) | What it caches | Class | Routing recommendation |
|---|------------------|----------------|-------|------------------------|
| 1 | `price_handler/feed/bar_feed.py:91` `@functools.cache _offset_alias` | timeframe→pandas alias string (pure) | **(c)** | LEAVE — pure, bounded key space, doesn't cache exceptions (raise preserved) |
| 2 | `outils/time_parser.py:139` `@lru_cache(maxsize=32) _aligned` | epoch alignment `(ts,tf)` (pure, v1.5 PERF-07) | **(c)** | LEAVE — bounded maxsize, body byte-unchanged, thread-safe |
| 3 | `strategy_handler/base.py:124` `@cache _declared_hints(cls)` | `get_type_hints` per Strategy subclass (v1.5 PERF-04) | **(c)** | LEAVE — constant after import, the seed's named example of correct memo |
| 4 | `strategy_handler/base.py:197` `self._to_dict_static_cache` | static slice of `to_dict` snapshot (v1.5 PERF-08) | **(c)** | LEAVE — explicitly invalidated via `_invalidate_to_dict_cache` on reconfigure; correct domain-state memo |
| 5 | `portfolio_handler/position/position.py:88-89` `_net_quantity_cache` / `_avg_price_cache` | two fill-derived Decimal properties (v1.5 PERF-08) | **(c)** | LEAVE — fill-invalidated in `update_position` (L288-289); correct, NOT `cached_property` (mutable input) |
| 6 | `price_handler/feed/bar_feed.py` `_prebuilt` (L241) / `_newest_bars` (L326) / `_cursor`,`_cursor_cut` (L305) / `_frames` (L213) | prebuilt Bars + newest-bar + window cursor + resampled frames (v1.5 PERF-05/06) | **(a)** | LEAVE — this IS the hot-path data cache; Q7 says no Arrow here |
| 7 | `strategy_handler/indicators/handle.py:66` `_buffer: deque(maxlen)` + `catalog.py` `_SMAState`/`_EMAState`/`_MACDHistState`/`_RSIState` | stateful indicator recurrence state (v1.5 PERF-05, Model B self-buffer) | **(a)** | LEAVE — hot-path indicator state; the v1.5 win Q7 protects |
| 8 | `price_handler/feed/cache_registration.py` `derive()` | shared-bar-cache capacity (pure derive-once at wiring) | **(a)-infra** | LEAVE — the wiring-time extension point for the deferred deep buffer, not a runtime cache |
| 9 | `order_handler/storage/in_memory_storage.py:62-64` `_active_by_portfolio` / `_by_status` / `_last_indexed_status` | derived secondary indexes over flat `{id:order}` (v1.5 PERF-01) | **(b)** | ALREADY SOLVED — in live, the SQL backend re-expresses these as `WHERE`+indexes, NOT a Python cache. No backtest change. |
| 10 | `execution_handler/matching_engine.py:106-110` `_resting` (truth) + `_trails` (parallel cache) | resting-order book + trail state | **(a)-engine** | LEAVE — execution working state; in live it joins the working set to rehydrate (Q10), not a persistence cache to consolidate |
| 11 | `execution_handler/exchanges/simulated.py:114-124` `_min/_max_order_size`, `_supported_symbols` | config snapshot fields | **(c)-config** | LEAVE — refreshed via `update_config` seam, not domain state |
| 12 | `portfolio_handler/metrics/metrics_manager.py:125` (the removed `_metrics_cache`) | the old wall-clock-TTL metrics cache | **— (negative)** | ALREADY DELETED in v1.5 (D-04); live metrics will be Postgres-backed. No action — confirms the direction. |
| 13 | `price_handler/store/sql_store.py:83` `inspector.clear_cache()` | SQLAlchemy reflection cache (library) | **— (FL-06)** | Not a classification target; the surrounding `SqlHandler` is the FL-06 rework |
| 14 | `config/system.py:45` `PerformanceSettings.enable_caching` / `cache_size_mb` | dead config knobs (no consumer) | **— (vestigial)** | Cleanup candidate; not load-bearing, optional opportunistic removal |

**Q8 verdict — the deliverable is the classification, not a rewrite.** v1.5 already did the heavy lifting: class (b) is fully solved by the order-storage indexes (#9), and the SQL backend simply re-expresses those as queries — no new Python cache. Class (c) (#1-5, #11) is correct memoization to leave alone. Class (a) (#6-8, #10) is the v1.5 hot-path data cache Q7 explicitly protects from Arrow. **There is essentially no cache-consolidation code to write.** The one genuinely NEW cache is the live working-set cache (Q9/Q10) — a *separate construct*, not a unification of the above. The milestone's #3 work is: (1) write down this classification as the authoritative map, (2) document the "do NOT unify into one Arrow object" decision, (3) optionally remove the two vestigial config knobs (#14).

### Q9 — Write-through pattern: zero hot-path cost when off, durable when on

**Recommendation: Backend-selection write-through (Pattern 2), toggle in `SqlSettings.write_through`, consumed by the mode-aware factory — NOT a runtime flag on the hot path. Synchronous write-through for create/terminalize (durability before the engine moves on); defer async batching for append-heavy writes until profiling justifies it. Backtest = retain-all in-memory with an OPTIONAL single end-of-run batch dump.**

Where the toggle lives: `SqlSettings` (new, `config/sql.py`) carries `write_through: bool` alongside the driver/URL and the retention knob. The factory reads it and returns the matching backend class. This extends the existing `OrderStorageFactory.create(environment, db_url)` seam — which today already branches `'backtest'`→in-memory vs `'live'`→(stub) — to be two-knob-aware. The live wiring in `live_trading_system.py:136` already calls `OrderStorageFactory.create('live', _SYSTEM_DB_URL)` and falls back to in-memory on `NotImplementedError`; filling the SQL backend completes that path.

Keeping serialization off the hot path (the hard constraint): the backtest backend (`InMemoryOrderStorage` et al.) contains **no serialization code at all** — so when write-through is off there is no branch, no call, provably zero cost. This is why it must be backend-selection, not `if self.write_through:` inside `add_order`. The v1.5 W1/W2 baseline (15.7 s / 152.8 MB) and the byte-exact oracle are protected structurally, not by discipline.

Sync vs async write-through (live): start **synchronous**. The live loop is a single daemon thread (`LiveTradingSystem`); a synchronous INSERT on create/terminalize guarantees durability before the engine acknowledges the state change, which is what restart-safety needs, and a trading fill is not sub-millisecond latency-critical in this engine. Synchronous is simplest and correct. **Add async only if measured:** if the DB write stalls the queue drain under live event rates, move the append-only writes (transactions, snapshots — the high-frequency, non-blocking-critical ones) behind a batched writer thread, keeping create/terminalize synchronous. Do not build the async path speculatively (keep-only-measured, the v1.5 discipline). Nautilus uses a separate process / optional Redis for its cache write path; this engine does not need that yet.

End-of-run batch dump (backtest, Pattern 3): the retain-all in-memory backend holds everything for the finite run; after the for-loop in `backtest_runner.py` (the same post-loop point as the existing run-end EXPIRE sweep), a dumper bulk-inserts the run in one `SqlBackend` transaction — and the results store (#1) writes its `runs` summary row + `run_artifacts` Parquet blob there too. One transaction, off the loop, crash-tolerant because backtests are re-runnable. This is the cheapest possible DB pattern and adds zero per-tick cost.

---
*Architecture research for: v1.6 N+3b Persistence Foundation (swappable SQL spine + four stores + classified cache, bolted onto the event-driven engine)*
*Researched: 2026-06-27*
