# Phase 4: Retention + Live Write-Through (#2 — live path) - Research

**Researched:** 2026-06-30
**Domain:** Live working-set cache + write-through + purge-on-terminalize + read-through + restart rehydration, composed over the Phase-3 `Sql<Concern>Storage` backends on testcontainers Postgres
**Confidence:** HIGH on the existing seams (read directly from the tree — every write call-site, the InMemory working-set structures, the Sql* txn boundaries, the threading model, the accumulator sources are cited by file:line below). MEDIUM-HIGH on the cross-method atomicity recommendation (the live loop is unbuilt; the recommendation is grounded in the ABC surface + FK ordering, but unvalidated against a running live loop — which D-01 defers to N+4).

This is a HOW-within-a-locked-shape research. The topology (D-04 wrapper-per-concern), the policy (D-02 immediate purge + read-through), the rehydration model (D-03 load-open-only + snapshot accumulators), and the scope line (D-01 build+component-test, don't rewire the composition root) are **locked by the owner**. This document resolves the five flagged surfaces: the per-call-site transaction boundary, the bracket-parent-resident enforcement mechanism, the read-through scope + thread-safety, the rehydration boot sequence + accumulator split, and the GATE-01/GATE-02 verification set.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (scope line):** Build the full retention machinery + integration-test on testcontainers; wire each factory's `'live'` arm to the wrapper; **do NOT rewire the live composition root.** The order seam is exercised end-to-end for free (`LiveTradingSystem` already routes orders to `OrderStorageFactory.create('live', backend=…)`). The portfolio-state and signal wrappers are **built + component-tested** but their hardcoded-`"backtest"` seams (`portfolio.py:93`, `live_trading_system.py:113`) **stay untouched** (N+4).
- **D-02 (retention policy):** **Immediate purge-on-terminalize + read-through.** Evict a record from the working-set cache as soon as its terminalize txn commits; serve later terminal-record queries via read-through to Postgres, off the hot path. **No Nautilus buffer window, no age/count sweep timer.** The terminal-state gate is mandatory: never evict an open order/position, and a **bracket parent stays resident until ALL its children terminalize**.
- **D-03 (rehydration):** **Periodic snapshot row + load-latest, accumulator scalars ride the synchronous write-through txn.** Rehydration is two reads: (1) load the working set (open positions + working orders + brackets) from the Phase-3 indexed queries; (2) restore the account aggregate + running accumulators (cash, equity, realised-PnL, peak equity) from the latest persisted snapshot row. The accumulator scalars needed for an exact restart are persisted synchronously in the same txn as the terminalize/fill that changed them. **Never replay terminal history; load open-only.**
- **D-04 (topology):** **Wrapper-per-concern decorator** — three new live-only classes `CachedSqlOrderStorage` / `CachedSqlPortfolioStateStorage` / `CachedSqlSignalStorage`, each implements its existing ABC and composes an in-memory working set + the Phase-3 `Sql<Concern>Storage`. The Phase-3 SQL classes stay UNTOUCHED. Composition-not-inheritance.
- **Carried (locked):** Write-through durability (Pitfall 8) — create/terminalize synchronous-in-txn, persist-then-acknowledge, cache never ahead of store. No premature async (append-heavy writes all-synchronous now). Backend-selection at wiring, not a hot-path flag. Money = Postgres-native `Numeric`; single UUIDv7; determinism (business `time`, `sort_keys`, stable `ORDER BY`).

### Claude's Discretion (this research settles each)

- The exact in-memory working-set structure the wrapper holds → **§ Pattern 1** (reuse `InMemory<Concern>Storage` as the composed working set).
- The precise rehydration query surface / boot sequence + the accumulator-scalar split → **§ Rehydration Boot Sequence** + **§ Accumulator Split**.
- The transaction-boundary mechanics per write point + one-txn-vs-store-first for multi-row → **§ Write-Through Transaction Boundaries**.
- Daemon-thread vs API-thread read-through / status-query interaction → **§ Read-Through Scope & Thread-Safety**.
- Whether `CachedSql*Storage` enter `mypy --strict` now → **§ Project Constraints** (yes — keep strict, matches the Sql* siblings).

### Deferred Ideas (OUT OF SCOPE — N+4)

- Rewiring the live composition root (`portfolio.py:93`, `live_trading_system.py:113`).
- Synthetic end-to-end event driver pushing events through the live daemon loop.
- Real live feed + venue reconciliation.
- Reconciliation buffer window for terminal records (the Nautilus `*_buffer_mins` / sweep timer).
- Async batch write-through for append-heavy writes (keep-only-measured; not pre-built).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RETAIN-01 | Mode-aware write-through toggle (backtest OFF = no per-tick serialization; live ON to Postgres). | § Architectural Responsibility Map + § Pattern 2 (backend-selection at wiring — the wrapper is only returned by the `'live'` factory arm; the backtest backend stays `InMemory*Storage` and imports no SQL symbol; GATE-01 inertness verified by the import-quarantine test). |
| RETAIN-02 | Bounded live working-set cache; terminal records purged on terminalize with read-through fallback. | § Write-Through Transaction Boundaries + § Purge-on-Terminalize & Bracket-Parent-Resident + § Read-Through Scope. Verified by evict-then-read-through + flat-RSS long-run + bracket-parent-resident tests. |
| RETAIN-03 | Restart rehydration reconstructs the working set deterministically, open-only, bracket-parent resident. | § Rehydration Boot Sequence + § Accumulator Split. Verified by open-only rehydration + crash-after-emit/restart tests. |
| GATE-01 (bound here) | Write-through OFF → SMA_MACD oracle byte-exact (134 / `46189.87730727451`), no W1/W2 regression vs v1.5 baseline (15.7 s / 152.8 MB). | § GATE-01 Inertness Verification (import-quarantine static check + oracle + A/B perf gate). |
| GATE-02 (recurring) | New code covered by round-trip + rehydration tests on testcontainers Postgres; `mypy --strict` clean; `filterwarnings=["error"]` green. | § Validation Architecture + § Project Constraints (mypy-strict scope decision). |
</phase_requirements>

## Summary

Phase 4 builds three live-only decorator wrappers — `CachedSqlOrderStorage`, `CachedSqlPortfolioStateStorage`, `CachedSqlSignalStorage` — each implementing its existing domain ABC and **composing** (a) an in-memory working set and (b) the untouched Phase-3 `Sql<Concern>Storage`. The wrapper is what each factory's `'live'` arm returns; the order seam is exercised end-to-end (`LiveTradingSystem` already calls `OrderStorageFactory.create('live', backend=…)`), the other two are built + component-tested only (D-01). All validation is component-level against testcontainers Postgres — no live feed, no full daemon-loop run is needed for any success criterion.

The two load-bearing pitfalls are **Pitfall 8** (write-through durability: persist-then-acknowledge; cache never ahead of store for create/terminalize) and **Pitfall 7** (live-retention bugs: evict-then-need, unbounded growth, rehydration loading terminal history, bracket-parent eviction). The single hardest design tension is multi-row atomicity: a bracket (parent + 2 children) is three separate `add_order` calls and a fill is several independent state-storage writes across four managers — and the unchanged ABC (D-04) exposes no cross-method transaction boundary. The resolution below is **store-first, one txn per ABC write, FK-ordered (parent before children)**, with within-method atomicity (already provided by Phase-3 `engine.begin()`) as the Pitfall-8 verification target, and cross-method bracket/fill atomicity documented as N+4 reconciliation's job (consistent with "reconciliation is N+4").

**Primary recommendation:** Each `CachedSql*Storage` holds `self._cache = InMemory<Concern>Storage()` (the proven working-set indexes) and `self._store = Sql<Concern>Storage(backend)`. Writes go **store-first then cache** (cache can always be rebuilt from the store; the inverse cannot). Purge-on-terminalize evicts only when a terminal-state gate (`_can_evict`) passes — never an open record, never a bracket parent with a live child. Reads serve the **open/active set purely from cache** (the hot path never read-throughs) and **terminal/history queries** read-through to the store under a wrapper-level `RLock` (API-thread-safe by construction for the imminent FastAPI layer; uncontended in the Phase-4 as-wired system where the daemon is the sole toucher). Rehydration loads open-only via the Phase-3 indexed queries and restores the two purge-derived accumulators — `CashManager._balance` and `PositionManager._realised_pnl_accumulator` — from the latest persisted snapshot row; everything else is recomputable from the loaded working set.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Working-set cache (open orders/positions, reservations, current account scalars) | In-memory wrapper layer (`CachedSql*` + composed `InMemory*Storage`) | — | The cache is rebuildable; it is NOT the system of record. Lives only on the `'live'` factory arm. |
| Durable system of record (orders, positions, transactions, snapshots, signals) | Phase-3 `Sql<Concern>Storage` (Postgres) | — | Untouched, gate-passed in Phase 3. A cache bug cannot compromise it (D-04 rationale). |
| Write-through ordering / durability | `CachedSql*` wrapper (store-first, sync-in-txn) | Phase-3 Sql `engine.begin()` | Persist-then-acknowledge (Pitfall 8); the Sql method already wraps one txn. |
| Purge gate + bracket-parent-resident invariant | `CachedSql*` wrapper (`_can_evict`) | Phase-3 `parent_order_id` index (`_load_child_ids`) | Eviction is a cache-policy concern; the store's self-referential FK backs the sibling-status query (Phase-3 D-02). |
| Read-through for terminal/cold records | `CachedSql*` wrapper (miss → store) | Phase-3 Sql read methods | Off the hot path — open records are always resident. |
| Restart rehydration (load open-only) | `CachedSql*` wrapper (`rehydrate()`) | Phase-3 indexed open/active queries (D-08) | Cache rebuildable from store; never replays terminal history. |
| Restoring accumulators INTO the managers (`_balance`, `_realised_pnl_accumulator`) | **N+4 composition root** | latest snapshot row (built here) | D-01 defers wiring the portfolio wrapper into the live loop; Phase 4 builds + tests the wrapper's ability to persist/return the scalars. |
| Event dispatch / mutation threading | `LiveTradingSystem` daemon thread (single writer) | — | All storage mutation runs on `LiveTradingSystem-EventProcessor`; the API thread only enqueues + reads `_stats` (its own lock). |

## Standard Stack

**No new dependencies.** Everything Phase 4 needs is already in `pyproject.toml` and proven by Phases 1–3.

### Core (already present, verified in tree)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | ^2.0.50 `[CITED: pyproject.toml]` | Core constructs (`insert`/`update`/`delete`/`select`, `engine.begin()`) — the wrapper composes the existing `Sql*Storage`, it writes no new SQL of its own except the rehydration row-reads | The Phase-1/3 spine is Core-only (no ORM); `SqlBackend` is `Engine + MetaData` |
| psycopg2-binary | ^2.9.12 `[CITED: pyproject.toml]` | Postgres driver for the `'live'` arm | Operational store is Postgres-only (OPS-04) |
| testcontainers[postgresql] | ^4.14.2 (dev) `[CITED: STATE 01-01]` | Real-Postgres substrate for every Phase-4 integration test | GATE-02 gate-(b) substrate; session-scoped `pg_engine` / `pg_backend` fixtures already exist (`tests/integration/storage/conftest.py`) |
| pytest / pytest-cov | ^8.4.2 / ^7.1.0 `[CITED: pyproject.toml]` | Test runner; folder-derived `integration`/`slow` markers | `tests/integration/storage/` is the established home |
| Decimal (stdlib) | — | Money end-to-end; `Numeric` ↔ `Decimal` round-trip (no quantize on reservations/locked-margin) | Locked money policy |
| `threading` (stdlib) | — | `RLock` guarding the read-through / cache-lookup path | Single-writer daemon; lock is a read-through concern only |

### Supporting (existing patterns the wrapper reuses)
| Asset | File | Purpose |
|-------|------|---------|
| `InMemoryOrderStorage` | `itrader/order_handler/storage/in_memory_storage.py` | The working-set structure for the order wrapper (`_by_id` truth + `_active_by_portfolio` + `_by_status` derived caches) |
| `InMemoryPortfolioStateStorage` | `itrader/portfolio_handler/storage/in_memory_storage.py` | Working set for the portfolio wrapper (`_positions` by ticker, `_reservations`, `_locked_margin`, bounded `_snapshots` deque) |
| `InMemorySignalStore` | `itrader/strategy_handler/storage/in_memory_storage.py` | Working set for the signal wrapper (insertion-order list) |
| `SqlOrderStorage._load_child_ids` | `itrader/order_handler/storage/sql_storage.py:228` | Self-referential `parent_order_id` query backing the bracket-resident invariant |
| `pg_backend` fixture | `tests/integration/storage/conftest.py:106` | Function-scoped `SqlBackend` over the session Postgres container (reuses one container; disposes in `finally`) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reuse `InMemory*Storage` as the composed working set | A purpose-built resident-set dataclass | Rejected — `InMemory*Storage` already has the exact secondary indexes (active-by-portfolio, by-status, positions-by-ticker) and is round-trip-proven; a new structure re-implements proven index code for no benefit. D-04 fixes the topology, not the internal structure — reuse is the lowest-risk fill. |
| `threading.RLock` for read-through guard | `readerwriterlock.RWLockFair` (already a transitive dep, used by `PortfolioHandler`) | Start with `RLock` (simplest, single-writer makes it uncontended). Promote to RW-lock only if API-thread read contention is **measured** (keep-only-measured). |
| Reuse `equity_snapshots` for the sync accumulator row | A dedicated single-row `portfolio_account_state` upsert table | See § Accumulator Split — both viable; the dedicated table is cleaner (no curve pollution, O(1) latest) but needs a small Phase-4 migration. Flagged `[ASSUMED]` for the planner. |

**Installation:** None. (Confirm no drift: `poetry run python -c "import sqlalchemy, testcontainers; print(sqlalchemy.__version__)"`.)

## Package Legitimacy Audit

**Not applicable — Phase 4 installs no external packages.** Every dependency (SQLAlchemy, psycopg2-binary, testcontainers, pytest) is already present and gate-passed in Phases 1–3. No `pip install` / `poetry add` occurs in this phase. (slopcheck/registry verification is moot — there is nothing new to verify.)

## Architecture Patterns

### System Architecture Diagram

```
                        ┌─────────────────────────────────────────────┐
   API thread           │  LiveTradingSystem  (daemon thread = SOLE    │
   (TradingInterface)   │  storage writer; _event_processing_loop)     │
        │               │                                              │
        │ create_*_order │   TIME→BAR→SIGNAL→ORDER→FILL dispatch        │
        ▼               │        │                                     │
   global_queue.put ───────────► │  OrderHandler / PortfolioHandler /   │
   (thread-safe handoff)│        │  StrategiesHandler                   │
                        └────────┼─────────────────────────────────────┘
                                 │ (mutation, single-threaded)
            ┌────────────────────┼────────────────────────────────────┐
            ▼                    ▼                    ▼
   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │ CachedSqlOrder   │ │ CachedSqlPortf.. │ │ CachedSqlSignal  │   ← live-only wrappers
   │   Storage        │ │   StateStorage   │ │   Storage        │     (D-04; this phase)
   │ ┌──────────────┐ │ │ ┌──────────────┐ │ │ ┌──────────────┐ │
   │ │ InMemory*    │◄┼─┼─┤ working set  │ │ │ │ working set  │ │   write: STORE-FIRST→cache
   │ │ (working set)│ │ │ │ (open only)  │ │ │ │              │ │   purge: terminal-gate evict
   │ └──────┬───────┘ │ │ └──────┬───────┘ │ │ └──────┬───────┘ │   read:  open→cache;
   │   RLock│(reads)  │ │   RLock│         │ │        │         │         terminal→read-through
   │ ┌──────▼───────┐ │ │ ┌──────▼───────┐ │ │ ┌──────▼───────┐ │
   │ │ SqlOrder     │ │ │ │ SqlPortfolio │ │ │ │ SqlSignal    │ │   ← Phase-3 stores
   │ │ Storage      │ │ │ │ StateStorage │ │ │ │ Storage      │ │     (UNTOUCHED; D-04)
   │ └──────┬───────┘ │ │ └──────┬───────┘ │ │ └──────┬───────┘ │
   └────────┼─────────┘ └────────┼─────────┘ └────────┼─────────┘
            └────────────────────┼────────────────────┘
                                 ▼
                      Postgres (system of record)
                   orders / positions / transactions /
                   equity_snapshots / signals  (testcontainers in tests)
```

Trace the primary path: an order arrives → `add_order` writes the Postgres row in one txn (store-first) → then mirrors into the in-memory working set. On terminalize → `update_order` writes the terminal row → `_can_evict` gate → purge from cache (parent stays if a child is live). A later status query for that terminal order misses the cache → read-through SELECT (under `RLock`). On restart → `rehydrate()` loads open-only from the indexed queries + restores the two purge-derived accumulators from the latest snapshot row.

### Recommended Project Structure
```
itrader/order_handler/storage/
├── cached_sql_storage.py        # NEW — CachedSqlOrderStorage (4-space)
├── sql_storage.py               # UNTOUCHED
├── in_memory_storage.py         # composed as the working set
└── storage_factory.py           # EDIT — 'live' arm → CachedSqlOrderStorage(SqlOrderStorage(backend))
itrader/portfolio_handler/storage/
├── cached_sql_storage.py        # NEW — CachedSqlPortfolioStateStorage (4-space)
└── storage_factory.py           # EDIT — 'live' arm → wrap (built + component-tested; NOT wired by portfolio.py:93)
itrader/strategy_handler/storage/
├── cached_sql_storage.py        # NEW — CachedSqlSignalStorage (4-space)
└── storage_factory.py           # EDIT — 'live' arm → wrap (built + component-tested; NOT wired by L113)
tests/integration/storage/
├── test_cached_sql_order_storage.py        # NEW — evict/read-through/bracket/rehydration/crash
├── test_cached_sql_portfolio_storage.py    # NEW
└── test_cached_sql_signal_storage.py       # NEW
```
**Indentation: all three `storage/` packages are 4-space** (CONTEXT indentation map; STATE Blockers). Copy the leading whitespace of the existing `sql_storage.py` sibling. A mixed-indent file fails to import.

### Pattern 1: Wrapper composes `InMemory<Concern>Storage` as the working set
**What:** The wrapper holds two collaborators and delegates, not inherits.
**When to use:** All three concerns.
**Example:**
```python
# itrader/order_handler/storage/cached_sql_storage.py  (4-space)
# Source: composition pattern from Phase-1 D-01; structures from in_memory_storage.py / sql_storage.py
class CachedSqlOrderStorage(OrderStorage):
    def __init__(self, store: "SqlOrderStorage") -> None:
        self._store = store                       # system of record (Phase-3, untouched)
        self._cache = InMemoryOrderStorage()      # working set: _by_id + active indexes
        self._lock = threading.RLock()            # read-through / cache-lookup guard
        self.logger = get_itrader_logger().bind(component="CachedSqlOrderStorage")

    def add_order(self, order: "Order") -> None:
        # store-first (persist-then-acknowledge, Pitfall 8): if the store raises,
        # the cache is never ahead of it.
        self._store.add_order(order)              # one txn (order row + state_changes)
        with self._lock:
            self._cache.add_order(order)
```
**Why store-first:** The cache is always rebuildable from the store (rehydration proves it). The store is the durable truth and must commit before the in-memory state the engine reads is updated. Cache-first would let a store failure leave the engine believing in a fill the store never recorded — the exact Pitfall-8 failure.

### Pattern 2: Backend-selection at wiring (GATE-01 inertness)
**What:** The wrapper is constructed ONLY inside each factory's `'live'` arm, behind lazy SQL imports — exactly like the Phase-3 `Sql*Storage`. The backtest/`test` arm returns `InMemory*Storage` and the wrapper module imports `sqlalchemy`/`SqlBackend` only when `'live'` is selected.
**Example:**
```python
# storage_factory.py 'live' arm (EDIT)
from .sql_storage import SqlOrderStorage
from .cached_sql_storage import CachedSqlOrderStorage   # lazy — inside the 'live' branch
resolved = backend if backend is not None else SqlBackend(SqlSettings.default())
return CachedSqlOrderStorage(SqlOrderStorage(resolved))
```
**Quarantine rule:** Do NOT re-export `CachedSql*Storage` from any package `__init__.py` (importing it pulls SQLAlchemy). The backtest import path must stay SQL-free — verified by the GATE-01 import-quarantine test.

### Anti-Patterns to Avoid
- **A `write_through` flag inside `add_order`/`update_order`:** rejected (Pitfall 3 / D-04). The wrapper IS the write-through; the backtest backend has none.
- **Folding cache/purge/read-through into `Sql*Storage`:** rejected (D-04) — re-opens gate-passed code, blurs store↔cache.
- **Cache-first writes for create/terminalize:** rejected (Pitfall 8) — store-first only.
- **Evicting on age/count without the terminal gate:** rejected (Pitfall 7) — can evict an open position. Purge is event-driven on terminalize, gated.
- **Read-through on the hot path:** an open record is ALWAYS resident; if a hot-path read misses, that is a bug (a still-open order was wrongly evicted), not a read-through trigger.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Working-set secondary indexes (active-by-portfolio, by-status, positions-by-ticker) | A fresh resident-set with hand-rolled indexes | Compose `InMemory<Concern>Storage` | Already built, index-correct, round-trip-proven; D-04 fixes topology not structure |
| Bracket sibling-status lookup | A `child_ids` array maintained in the cache | `parent.child_order_ids` + the Phase-3 `parent_order_id` index (`_load_child_ids`) | Phase-3 D-02 chose the self-referential FK precisely for this; FK prevents orphans |
| Per-txn SQL (insert/update/delete) | New SQL in the wrapper | Delegate to the composed `Sql*Storage` methods (each already one `engine.begin()`) | The store is untouched + gate-passed; the wrapper only orchestrates |
| Postgres round-trip / decimal fidelity | Re-test money fidelity | It is proven in Phase-3 D-10 (Numeric ↔ exact Decimal) | The wrapper adds no new money columns |
| Testcontainers lifecycle | A new container per test | `pg_backend` fixture (reuses the session container, disposes in `finally`) | Avoids ResourceWarning under `filterwarnings=["error"]` |

**Key insight:** the wrapper writes almost no SQL of its own. Its job is orchestration — ordering (store-first), gating (purge), guarding (RLock), and sequencing (rehydration). The two exceptions where the wrapper reads the store directly are the rehydration repopulation reads (reservations/locked-margin rows → cache dicts; bracket parents of active children).

## Write-Through Transaction Boundaries

The exact existing write call-sites and the recommended boundary for each. **Rule: store-first, one txn per ABC write (the Sql method already opens `engine.begin()`), FK-ordered.** The cache is mutated only after the store commit returns.

### Order concern — call-sites (all on the daemon thread)
| Call-site (file:line) | ABC method | Phase-3 store txn | Wrapper action |
|---|---|---|---|
| `admission/admission_manager.py:257,310` (admit primary) | `add_order` | `insert orders` + `insert order_state_changes` in one `engine.begin()` (`sql_storage.py:257`) | store.add_order → cache.add_order |
| `admission/admission_manager.py:932` (rejected-at-add) | `add_order` | same | store-first; REJECTED is terminal → `_can_evict` may purge immediately (no children) |
| `brackets/bracket_manager.py:183,185,187` (assemble bracket: primary + SL + TP) | `add_order` ×3 | three SEPARATE txns | **parent first** (FK), then children. See multi-row note below. |
| `brackets/bracket_manager.py:318,319,320` (attach SL/TP, update parent) | `add_order` ×2 + `update_order` | three txns | children inserted, then parent updated (declares `child_order_ids`) |
| `lifecycle/lifecycle_manager.py:116,179,260` (modify / cancel / expire) | `update_order` | `update orders` + replace `order_state_changes` in one txn (`sql_storage.py:270`) | store.update_order → cache.update_order → `_can_evict` gate (terminalize) |
| `reconcile/reconcile_manager.py:267` (terminalize from FillEvent: FILLED/CANCELLED/REJECTED) | `update_order` | same | **the terminalize seam** — store.update_order → cache.update_order → purge gate |

### Portfolio-state concern — call-sites (reached via `portfolio.state_storage`, one instance per Portfolio)
| Call-site (file:line) | ABC method | Phase-3 store txn |
|---|---|---|
| `position/position_manager.py:154` (open/scale-in) | `set_position` | delete-open + insert in one txn (`sql_storage.py:142`) — **already atomic** |
| `position/position_manager.py:215,216` (close) | `remove_position` + `add_closed_position` | two txns (remove open row; insert closed row) |
| `transaction/transaction_manager.py:151` (record fill) | `add_transaction` | one insert txn |
| `cash/cash_manager.py:521,545` (reserve/release) | `add_reservation` / `pop_reservation` | upsert / select-then-delete, one txn each |
| `cash/cash_manager.py:694` (cash op) | `add_cash_operation` | one insert txn |
| `metrics/metrics_manager.py:195` (per-bar snapshot via `record_snapshot`) | `add_snapshot` | MAX(seq)+1 then insert, one txn |
| position-life margin lock (`add_locked_margin`/`pop_locked_margin`) | per Plan 02-04 | upsert / select-then-delete, one txn each |

### Signal concern
| Call-site | ABC method | Phase-3 store txn |
|---|---|---|
| `StrategiesHandler.add(record)` (one per non-None intent) | `add` | one insert txn |
| (no update/delete/terminalize — signals are append-only; **never purged**, never read-through; the cache is a pure mirror) | — | — |

### Multi-row atomicity — the resolution (the hardest surface)

Two multi-row writes exist; the unchanged ABC (D-04) exposes **no cross-method transaction boundary**, so true single-txn atomicity across calls is not reachable without a composition-root change that D-01 defers.

1. **Bracket (parent + 2 children) = 3 `add_order` calls.** The Phase-3 self-referential FK (`child.parent_order_id → parent.id`) **forces parent-first ordering** anyway. Recommendation: **store-first, per-call, parent before children** (the natural order in `bracket_manager.py:183-187`). A crash strictly between the parent insert and a child insert leaves a *parent-without-children* partial bracket. This is bounded and recoverable: (a) the bracket-parent-resident invariant keeps the parent in the cache; (b) on rehydration the parent loads with `child_order_ids` rebuilt from the FK index — a mismatch (declared children absent) is detectable; (c) full atomic completion is **N+4 venue reconciliation's** job (the order seam reconciles against the venue, not just the store). Do NOT add an `add_bracket` ABC method this phase — it changes the ABC and the in-memory backend, which D-04 forbids.

2. **Fill (transaction + position + reservation-release + cash-op + snapshot) = independent writes across four managers.** Each is its own `engine.begin()` txn today. The same logic applies: per-write store-first durability; cross-method atomicity is N+4. Crucially, **the portfolio wrapper is NOT wired into the live loop this phase (D-01)** — so the fill-spanning atomicity question is moot for the as-built system; the component test exercises each wrapper method directly.

3. **Pitfall-8 "atomic multi-row" verification target = within-method atomicity** (already provided by Phase 3): kill mid-`set_position` → the row is all-or-nothing (delete+insert in one `engine.begin()`); kill mid-`add_order` → order row + state-change rows are all-or-nothing. The test asserts these. The cross-method bracket/fill atomicity is documented as a known, N+4-closed limitation — NOT a Phase-4 failure.

**This is the #1 decision to confirm with the planner.** The recommendation (per-write store-first + N+4 reconciliation for cross-method) is the only path that honors both D-04 (unchanged ABC) and D-01 (don't rewire the composition root). The alternative — a fill-scoped unit-of-work / `add_bracket` — requires touching the ABC and the live composition root, both explicitly deferred. Tagged `[ASSUMED]` (A1).

## Purge-on-Terminalize & Bracket-Parent-Resident

The terminal-state gate (D-02). Lives in the order wrapper (positions have no bracket structure — a position purges on close via `remove_position` + `add_closed_position`; the open `_positions` dict is the working set, closed rows are store-only).

`OrderStatus` terminal set = `{FILLED, CANCELLED, REJECTED, EXPIRED}` (`core/enums/order.py:85-88`, `VALID_ORDER_TRANSITIONS` terminal = empty list; `Order.is_terminal` `order.py:149`). Active = `{PENDING, PARTIALLY_FILLED}` (`Order.is_active` `order.py:144`).

```python
# Source: Nautilus contingency rule ported onto parent_order_id / child_order_ids
def _can_evict(self, order: "Order") -> bool:
    if not order.is_terminal:
        return False                       # never evict an open order (Pitfall 7)
    if order.child_order_ids:              # this is a bracket PARENT
        # resident until ALL children terminal — look up each child (cache then store)
        return all(self._child_is_terminal(cid) for cid in order.child_order_ids)
    return True                            # standalone or child → evict on terminalize

def _on_update(self, order):               # called by update_order AFTER store+cache write
    if self._can_evict(order):
        self._cache.remove_order(order.id)         # purge from working set
        if order.parent_order_id is not None:      # a child just terminalized —
            self._maybe_evict_parent(order.parent_order_id)  # re-check the parent
```
- `_child_is_terminal(cid)`: cache lookup first; on miss (already purged) read-through to the store — a purged child is terminal by definition, so a store hit (or even a cache miss with no store row, which can't happen) resolves to terminal.
- `_maybe_evict_parent`: when a child terminalizes, the parent may have been terminal-but-resident; re-evaluate `_can_evict(parent)` and purge it if now all children are done. The Phase-3 `parent_order_id` index (`_load_child_ids`, `sql_storage.py:228`) is the store-side source if the parent isn't in cache.

**Why the parent must stay resident:** the OCO contract — when one child fills, the sibling must be cancelled (the exchange enforces OCO, the order mirror reconciles). Evicting the parent while a child is live would break the rehydration-side bracket linkage and the resident set the reconcile path reads. This is exactly Pitfall 7(d).

## Read-Through Scope & Thread-Safety

### Which methods serve cache-only vs read-through

| ABC method | Source | Read-through? |
|---|---|---|
| `get_active_orders`, `get_pending_orders` | cache only | **No** — open set is always resident (hot path) |
| `get_order_by_id` (open order) | cache | No |
| `get_order_by_id` (terminal/purged) | cache miss → store | **Yes** (off hot path) |
| `get_orders_by_status` (active status) | cache | No |
| `get_orders_by_status` (terminal status) | store | **Yes** |
| `get_order_history`, `search_orders`, `count_orders_by_status`, `get_orders_by_time_range`, `get_orders_by_ticker` | store (may span terminal) | **Yes** (recon/reporting — off hot path) |
| Portfolio: `get_positions`, `get_position`, `get_reserved_cash`, `get_locked_margin`, `snapshot_count`/`get_latest_snapshot` (current) | cache | No (open/current state) |
| Portfolio: `get_closed_positions`, `get_transaction_history`, `get_cash_operations`, `get_snapshots` (history) | store | **Yes** |
| Signal: `get_all`, `by_strategy`, `by_ticker` | cache (full mirror — signals never purged) | No |

**The hot path never read-throughs** — verified by the evict-then-read-through test (a purged terminal order reads back from the store) AND the flat-RSS test (open-set queries don't touch the store).

### Thread-safety — the definitive answer to the research flag

- **All storage mutation is single-threaded.** In live mode every storage write happens on the one `LiveTradingSystem-EventProcessor` daemon thread inside `_event_processing_loop` (`live_trading_system.py:337-396`, dispatch at L365). The API thread (`TradingInterface.create_market_order`/`create_limit_order`, `trading_interface.py:75,128`) only **enqueues** `OrderEvent`s via `global_queue.put` (`live_trading_system.py:543-566`) and reads system stats from `_stats` under its own `_stats_lock`. **The API thread never calls a storage method in the as-built Phase-4 system.**
- **Therefore, for the Phase-4 as-wired order seam, the working set has exactly one toucher (the daemon) — no storage lock is required for correctness today.**
- **But build it API-thread-safe anyway** (cheap insurance for the imminent FastAPI layer, which WILL serve status/recon reads on an API thread, and for N+4): the wrapper holds a single `threading.RLock`. The daemon takes it briefly around **cache mutation** (add/update/evict); any future API-thread **read-through / cache lookup** takes it around the lookup. The SQLAlchemy engine is already connection-per-operation thread-safe, so the store needs no lock — **the lock guards only the in-memory dict from a concurrent purge mutation during an iteration/lookup.**
- **Locking is a read-through concern, not a write-ordering concern** (the single writer makes write-ordering free). Start with `RLock`; promote to a readers-writer lock (`readerwriterlock`, already a dep) only if API-thread read contention is **measured** (keep-only-measured).

**Net recommendation:** read-through is **daemon-only in the Phase-4 as-wired system**, but the wrapper is **built API-thread-safe** (one `RLock`, uncontended today). This closes the flagged question without speculative complexity.

## Rehydration Boot Sequence

`rehydrate()` on the wrapper (called by N+4's live composition root; **built + component-tested here**). Loads **open-only**, never terminal history (Pitfall 7c).

### Order wrapper `rehydrate()`
1. `actives = self._store.get_active_orders(None)` → PENDING/PARTIALLY_FILLED (uses the Phase-3 `(portfolio_id, status)` index, D-08). Stable `ORDER BY (created_at, id)` (`sql_storage.py:247`).
2. For each active order with a `parent_order_id`, ensure the **parent is loaded even if the parent is itself terminal** (a filled parent with live children must stay resident — the bracket-parent-resident invariant's rehydration side). Query parents by id; add to the load set.
3. For each active parent, its `child_order_ids` are rebuilt from the FK index on read (`_load_child_ids`) — load any child rows referenced.
4. Populate the cache: `for o in load_set: self._cache.add_order(o)` (the in-memory `_index_apply` rebuilds the active-by-portfolio + by-status indexes deterministically).
5. **Never** load FILLED/CANCELLED/REJECTED/EXPIRED standalone orders.

### Portfolio wrapper `rehydrate()`
1. `positions = self._store.get_positions()` → `WHERE is_open = true` (Phase-3 `(portfolio_id, is_open)` index, D-08). Each `Position` carries its own `avg_bought`/`avg_sold`/`realised_pnl`-so-far → into `_cache._positions`.
2. Repopulate working cash state: read the `cash_reservations` and `locked_margin` rows for this `portfolio_id` directly (the wrapper composes the Sql store, which exposes the tables) → rebuild `_cache._reservations` / `_cache._locked_margin` dicts. (The ABC's `get_reserved_cash` returns only the SUM; rehydration needs the per-reference rows, so the wrapper reads the table rows it owns.)
3. `latest = self._store.get_latest_snapshot()` → the account aggregate + accumulator scalars (see § Accumulator Split).
4. **Never** load `get_closed_positions` / `get_transaction_history` / `get_cash_operations` / full `get_snapshots` into the working set — those stay store-only, served by read-through.

### Signal wrapper `rehydrate()`
- Optional (signals are advisory, not engine state). If desired, `self._store.get_all()` → cache mirror. Not required for any success criterion.

### Crash-after-emit determinism
Because writes are **store-first + synchronous-in-txn** (Pitfall 8), the store is never behind the engine. A crash after a fill is emitted but with the terminalize committed leaves the store at the post-fill state; `rehydrate()` over the same DB reconstructs a working set **byte-identical** to the pre-crash working set (the crash-after-emit/restart test). The stable `ORDER BY` on every load query (Pitfall 10) makes the reconstruction deterministic.

## Accumulator Split (D-03 — the open scalar question, resolved)

The crux: after immediate-purge, which running scalars **cannot** be recomputed from the loaded open-only working set, and therefore **must** ride the synchronous write-through txn (persisted on every fill/terminalize, restored from the latest snapshot row)?

| Scalar | In-memory source | Recomputable from loaded working set? | Verdict |
|---|---|---|---|
| **Cash balance** | `CashManager._balance` (`cash_manager.py:64`) — `balance = initial + Σ cash-ops` | **No** — cash operations are purged (append-only history, store-only) | **MUST persist** (snapshot `cash_balance`) |
| **Realised PnL** | `PositionManager._realised_pnl_accumulator` (`position_manager.py:328`) — fed on every close; `assert_accumulator_consistent` re-sums open+**closed** positions (`position_manager.py:349-352`) | **No** — closed positions are purged; the re-sum would be incomplete | **MUST persist** (snapshot `realized_pnl`) |
| **Unrealised PnL** | `position_manager.get_total_unrealized_pnl()` | **Yes** — from resident open positions × current price | Recompute (no sync persistence) |
| **Positions value** | `position_manager.get_total_market_value()` | **Yes** — open positions × price | Recompute |
| **Open-position count** | `len(open positions)` | **Yes** — count of resident open positions | Recompute |
| **Total equity** | `market_value + cash` (`portfolio.py:121`) | **Partly** — needs the restored cash (above) + current prices | Derive from restored cash + recomputed market value; the snapshot's `total_equity` is a cross-check |
| **Peak equity / max drawdown** | `get_drawdown_analysis` scans snapshots (`metrics_manager.py:301`) | **Yes** — from the non-purged `equity_snapshots` curve (append-only, store-only, NOT purged — D-03) | Recompute from the curve; persisting a `peak_equity` scalar is an O(1)-boot optimization (avoids a full-curve scan) — optional |

**Each open position carries its own per-position `realised_pnl`-so-far** (from partial closes) on its row → it rides on the resident open position, no separate persistence.

### The synchronous-snapshot mechanism (which write carries the scalars)
The two MUST-persist scalars (`cash_balance`, `realized_pnl`) live in the `PortfolioSnapshot` row already (`equity_snapshots` columns: `total_equity, cash_balance, ..., realized_pnl, ...` — `sql_storage.py:426-441`). D-03 requires they be **never behind the working set after a crash**, so they must be written **in the same logical txn as the fill/terminalize that changed them** — not only on the per-TIME-bar `record_snapshot`.

Two viable carriers (planner decides):

- **(Recommended, primary) Dedicated single-row `portfolio_account_state` table, upserted synchronously on each fill/terminalize.** One row per `portfolio_id`: `{cash_balance, realized_pnl, total_equity, peak_equity, open_positions_count, updated_time}`. O(1) upsert, O(1) latest read on boot, no pollution of the per-bar equity curve, matches RETAIN-02's "current account/portfolio snapshot ... stay resident" as a distinct entity. **Cost:** a small Phase-4 Alembic migration on the framework chain (Phase-3 D-09 — the framework owns the operational chain, so this is in-bounds). `[ASSUMED]` A2 — confirm the new table with the planner.
- **(Zero-migration fallback) Reuse `equity_snapshots`:** write a synchronous snapshot row on fill (carrying the post-fill scalars) in addition to the per-bar snapshot, so `get_latest_snapshot()` always reflects post-fill state. **Cost:** intra-bar rows pollute the historical equity curve (extra sample points — harmless for drawdown/peak, but the curve is no longer strictly per-bar). Literally matches D-03's "latest persisted snapshot row" wording.

**Critical scope note:** the **wiring** that calls this synchronous write on every fill, and that restores `_balance` / `_realised_pnl_accumulator` INTO the managers on boot, is **N+4** (it requires the portfolio wrapper to be live in the composition root, which D-01 defers — `portfolio.py:93` stays `"backtest"`). **Phase 4 builds + component-tests the wrapper's *ability* to:** (a) persist the scalars synchronously, (b) return them via `get_latest_snapshot()` / the account-state read, (c) rehydrate open positions. The component test asserts: write fills → construct a fresh wrapper over the same DB → `get_positions()` equals the pre-crash open set AND the latest account-state scalars equal the post-fill values. The restoration into `CashManager`/`PositionManager` is N+4.

## Runtime State Inventory

This phase ADDS a persistent system of record; it does not rename existing runtime state. The "runtime state" lens here is the cache↔store relationship (what survives a restart vs what is rebuilt).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (survives restart, store-only) | Postgres operational tables (Phase-3): `orders` + `order_state_changes`, `positions` (open+closed via `is_open`), `transactions`, `cash_reservations`, `locked_margin`, `cash_operations`, `equity_snapshots`, `signals`. | The wrapper composes the Phase-3 stores — no schema change EXCEPT the optional `portfolio_account_state` table (A2). |
| Live in-memory state (rebuilt on restart) | Working-set cache: open orders + brackets, open positions, reservations, locked margin, current account scalars, signal mirror. | Rebuilt by `rehydrate()` from the open-only indexed queries + latest snapshot. NOT durable by itself. |
| Running accumulators (purge-derived, must persist) | `CashManager._balance` (`cash_manager.py:64`), `PositionManager._realised_pnl_accumulator` (`position_manager.py:328`). | Persist in the synchronous snapshot/account-state row; restore from latest on boot (restoration-into-managers = N+4). |
| OS-registered state | None — no OS/scheduler/service registration in this phase. | None — verified (the daemon is an in-process `threading.Thread`, `live_trading_system.py:416`). |
| Secrets/env vars | DB URL via `SqlSettings` (`env_prefix="ITRADER_DATABASE_"`, default Postgres port 5544) / the `SYSTEM_DB_URL` interim escape hatch (`live_trading_system.py:33`). No new secret introduced; no rename. | None — the wrapper sources its backend from the injected `SqlBackend`, never re-resolves creds. |
| Build artifacts | None — pure new modules + factory edits; no package rename, no egg-info, no compiled artifact. | None — verified. |

## Common Pitfalls

### Pitfall 7 (LOAD-BEARING): Live retention bugs
**What goes wrong:** (a) evict-then-need with no read-through → `None`/`KeyError` for a real terminal record; (b) unbounded growth — terminal records kept "for status" → memory tracks uptime not active trading; (c) rehydration loads terminal history → boot bloat; (d) rehydration breaks bracket safety — a bracket parent evicted while a child is open.
**How to avoid:** purge-on-terminalize gated by `_can_evict` (never an open record; parent resident until all children terminal); read-through for terminal/cold records off the hot path; rehydrate open-only.
**Warning signs:** a terminal-record query returns `None` after purge; live RSS grows monotonically with uptime; restart loads thousands of closed positions; a bracket child fires after its parent was evicted.
**Verification:** evict-then-read-through test; flat-RSS long-run test; open-only rehydration test; bracket-parent-resident test (see § Validation Architecture).

### Pitfall 8 (LOAD-BEARING): Write-through durability/ordering
**What goes wrong:** cache mutated + event emitted before the store commits → restart rehydrates state the store never recorded; a non-atomic multi-row write leaves a partial bracket/fill after a crash.
**How to avoid:** synchronous write-through inside a txn for create/terminalize; **store-first** so the cache is never ahead; within-method atomicity via the Phase-3 `engine.begin()`. Cross-method (bracket/fill) atomicity is N+4 reconciliation (see § Multi-row atomicity).
**Warning signs:** restart finds an order the store never recorded; a partial bracket persisted after a crash; reconcile reports a cache↔store mismatch; the wrapper mutates the cache before the store commit returns.
**Verification:** crash-after-emit/restart test (rehydrated working set equals pre-crash); within-method atomic test (kill mid-`set_position` / mid-`add_order` → all-or-nothing).

### Pitfall 10: Nondeterminism at the persistence edge
**What goes wrong:** rehydration query with no `ORDER BY`; a wall-clock `created_at`; unordered dict iteration.
**How to avoid:** every load query has a stable `ORDER BY` (Phase-3 already does — `(created_at, id)` for orders, `seq` for snapshots, `(time, id)` for transactions/signals). Persisted timestamps use business `time`, never wall clock. The wrapper introduces no new timestamp.
**Verification:** double-run determinism — two rehydrations over the same DB yield byte-identical working sets.

### Pitfall 12: Tabs-vs-spaces breakage
**What goes wrong:** pasting 4-space code into a tab file → `TabError` on import.
**How to avoid:** **all three `storage/` packages are 4-space** — copy the existing `sql_storage.py` sibling's leading whitespace exactly. (Note: the *handler* modules `order_handler/` and `portfolio_handler/` are tab-indented, but their `storage/` sub-packages are 4-space — do not be misled.)
**Verification:** each new module imports clean (a mixed-indent file fails import).

### Pitfall 3 / GATE-01: A serialize/SQL import on the backtest hot path
**What goes wrong:** the new wrapper module gets re-exported from a package `__init__`, or the factory imports it eagerly → SQLAlchemy on the backtest import path → W1/W2 risk.
**How to avoid:** lazy-import the wrapper INSIDE the `'live'` factory arm only; never re-export from `__init__`; the backtest/`test` arm returns `InMemory*Storage`.
**Verification:** import the backtest path, assert no `sqlalchemy` and no `cached_sql_storage` in `sys.modules`; oracle byte-exact; W1/W2 within the v1.5 ±5% gate.

## Code Examples

### Purge-on-terminalize with the bracket gate (order wrapper)
```python
# Source: Nautilus contingency rule + Phase-3 parent_order_id index (sql_storage.py:228)
def update_order(self, order: "Order") -> bool:
    ok = self._store.update_order(order)           # store-first, one txn (Pitfall 8)
    if not ok:
        return False
    with self._lock:
        self._cache.update_order(order)            # mirror
        if self._can_evict(order):                 # terminal-state gate (Pitfall 7)
            self._cache.remove_order(order.id)
            if order.parent_order_id is not None:  # a child terminalized
                self._maybe_evict_parent(order.parent_order_id)
    return True
```

### Read-through for a terminal/cold record (off hot path)
```python
def get_order_by_id(self, order_id, portfolio_id=None):
    with self._lock:
        hit = self._cache.get_order_by_id(order_id, portfolio_id)
    if hit is not None:
        return hit                                 # open/resident — hot path, no store touch
    return self._store.get_order_by_id(order_id, portfolio_id)  # read-through (terminal)
```

### Rehydration (open-only) — order wrapper
```python
def rehydrate(self) -> None:
    with self._lock:
        for order in self._store.get_active_orders(None):      # PENDING/PARTIALLY_FILLED
            self._cache.add_order(order)
            # ensure the bracket parent of an active child is resident even if filled
            if order.parent_order_id is not None and \
               self._cache.get_order_by_id(order.parent_order_id) is None:
                parent = self._store.get_order_by_id(order.parent_order_id)
                if parent is not None:
                    self._cache.add_order(parent)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `'live'` order arm → bare `SqlOrderStorage` (no cache, no purge) | `'live'` arm → `CachedSqlOrderStorage(SqlOrderStorage)` wrapper | Phase 4 | Adds the working-set cache + retention without touching the gate-passed store |
| Portfolio/signal `'live'` arm → bare `Sql*Storage` | Wrapped (built + component-tested; NOT wired into the live loop) | Phase 4 / N+4 | Order seam wired now; portfolio/signal wiring is N+4 (D-01) |
| Reconciliation buffer window default (FEATURES Q10) | Immediate purge + read-through (D-02) | Owner decision 2026-06-30 | Tightest memory bound, zero tuning knobs; buffer is N+4 when recon needs it |
| `DecimalAsText` / `write_through:bool` on `SqlSettings` (ARCHITECTURE Q9, predates owner) | Postgres-native `Numeric`; backend-selection at wiring | Owner Decisions | RESEARCH Pattern 2/Q9 framing retracted — apply the pattern, drop the flag |

**Deprecated/outdated for this phase:**
- ARCHITECTURE.md Pattern 2's `SqlSettings.write_through` flag and `DecimalAsText` — both retracted by Owner Decisions (money native `Numeric`; selection at wiring). Use the patterns, not the framing.
- FEATURES.md Q10's `*_buffer_mins` / `*_interval_mins` sweep — dropped (D-02 immediate purge). Keep Q10's *gate* + *rehydration sequence* only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Cross-method atomicity (bracket parent+children; fill transaction+position+snapshot) is **store-first per-write + N+4 reconciliation**, NOT a single txn — because the unchanged ABC (D-04) + un-rewired composition root (D-01) expose no cross-method boundary. Pitfall-8 atomicity test targets within-method atomicity. | Write-Through Transaction Boundaries | If the planner wants true cross-method atomicity now, it requires an ABC/composition-root change that D-01/D-04 defer — a scope conflict the owner must resolve. |
| A2 | The two purge-derived accumulators ride a **dedicated single-row `portfolio_account_state` upsert table** (recommended) requiring a small Phase-4 Alembic migration; the zero-migration fallback reuses `equity_snapshots` with a synchronous fill-time row. | Accumulator Split | Wrong carrier → either an unnecessary migration or a polluted equity curve. Either works; this is a clean-vs-cheap tradeoff for the planner. |
| A3 | Restoration of `_balance` / `_realised_pnl_accumulator` INTO `CashManager`/`PositionManager` on boot is **N+4** (needs the portfolio wrapper live in the composition root, which `portfolio.py:93` hardcodes to `"backtest"`). Phase 4 builds+tests the wrapper's persist/return/rehydrate *ability* only. | Accumulator Split / Rehydration | If the planner expects manager-restoration wired this phase, that contradicts D-01's deferral of the portfolio composition-root rewire. |
| A4 | Read-through is **daemon-only in the as-wired Phase-4 system** (the API thread never calls storage today) but built API-thread-safe with one `RLock` for the imminent FastAPI layer. | Read-Through Scope & Thread-Safety | Over-locking would add (uncontended) cost; under-locking would break the future FastAPI read path. RLock is the safe middle. |
| A5 | `CachedSql*Storage` modules enter `mypy --strict` now (the Phase-3 `Sql*Storage` siblings already are — not in any `pyproject.toml` override). | Project Constraints | If deferred, GATE-02's "mypy --strict clean" would need an override entry; keeping strict matches the siblings and is the lower-debt path. |

## Open Questions

1. **Cross-method atomicity vs the locked scope (A1).**
   - What we know: bracket = 3 `add_order` calls, fill = independent manager writes; the FK forces parent-first; the ABC has no cross-method txn.
   - What's unclear: whether the owner accepts per-write store-first + N+4 reconciliation, or wants an atomic boundary now (which breaks D-01/D-04).
   - Recommendation: accept per-write store-first; document the partial-bracket-on-crash window as N+4-closed. Confirm with the planner before building the atomicity test (it must target within-method atomicity).

2. **Account-state carrier: new table vs reuse `equity_snapshots` (A2).**
   - Recommendation: dedicated `portfolio_account_state` upsert table (cleaner, O(1) latest, matches RETAIN-02). Accept the small framework-chain migration.

3. **Does the Phase-4 portfolio/signal wrapper need a `rehydrate()` entry-point at all, given it isn't wired (D-01)?**
   - Recommendation: yes — build `rehydrate()` and component-test it (it IS a success criterion: open-only rehydration on testcontainers Postgres). The *caller* is N+4; the *method* is Phase 4.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker / testcontainers Postgres | Every Phase-4 integration test (gate-b) | ✓ (assumed dev/CI) | `postgres:16` image | The `pg_engine` fixture `pytest.skip`s gracefully when Docker is absent (D-11) — the suite stays green, the PG arm is simply skipped |
| Postgres driver (psycopg2-binary) | `'live'` arm backend | ✓ | ^2.9.12 | — |
| SQLAlchemy 2.0 Core | Wrapper orchestration + composed stores | ✓ | ^2.0.50 | — |
| `pg_backend` / `pg_engine` fixtures | Test substrate | ✓ | `tests/integration/storage/conftest.py` | — |

**Missing dependencies with no fallback:** none — the Postgres substrate is the one external need, and it degrades to a skip (never a hard fail) when Docker is absent.
**Missing dependencies with fallback:** Docker → tests skip the PG arm (D-11); a Dockerless `poetry run pytest tests` stays green but does NOT prove gate-(b) — gate-(b) requires a Docker-enabled run.

> ⚠️ **Worktree test gotcha (from auto-memory):** `make test` aborts in a worktree on a missing `.env`, and `make test` exports `ITRADER_DISABLE_LOGS=true` (failing `caplog` warn-assertion tests). In a worktree run `poetry run pytest tests/integration/storage -m integration`; re-run `make test` in the main checkout for the full gate. Also prepend `PYTHONPATH="$PWD"` in a worktree (editable-install shadowing). The byte-exact oracle is `tests/integration/test_backtest_oracle.py` (`tests/golden` collects 0 tests).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion=8.0`, `testpaths=["tests"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `filterwarnings=["error", …]`, `--strict-markers`, `--strict-config` |
| Quick run command | `poetry run pytest tests/integration/storage/test_cached_sql_order_storage.py -x` |
| Full suite command | `make test` (main checkout) / `poetry run pytest tests` |
| Substrate | testcontainers Postgres via the existing `pg_backend` fixture (session container reused) |
| Markers | folder-derived `integration` (+`slow`) under `tests/integration/storage/` — no decorator needed; do NOT add a `tests/integration/storage/__init__.py` or a new package-collision `__init__.py` under `tests/unit/<x>` (auto-memory: package collision breaks full-suite collection) |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|-------------|
| RETAIN-02 | **Evict-then-read-through:** add order → terminalize → assert purged from cache → assert `get_order_by_id` reads through from the store | integration | `pytest tests/integration/storage/test_cached_sql_order_storage.py -k evict_read_through -x` | ❌ Wave 0 |
| RETAIN-02 | **Flat-RSS long-run:** open+terminalize N orders/positions in a loop → assert working-set size (cache len) stays bounded by the active count, not N (and store row count grows) | integration | `... -k flat_rss -x` | ❌ Wave 0 |
| RETAIN-02 | **Bracket-parent-resident:** open a bracket (parent+SL+TP) → terminalize one child → assert parent + other child stay resident → terminalize all children → assert parent now purged | integration | `... -k bracket_parent_resident -x` | ❌ Wave 0 |
| RETAIN-03 | **Open-only rehydration:** write a mix of open + terminal orders/closed positions → fresh wrapper over same DB → `rehydrate()` → assert only the open working set loaded (no terminal/closed) | integration | `... -k rehydrate_open_only -x` | ❌ Wave 0 |
| RETAIN-03 | **Crash-after-emit/restart:** write fills (store committed) → drop the wrapper → fresh wrapper → `rehydrate()` → assert working set byte-identical to pre-crash; assert latest account-state scalars == post-fill values | integration | `... -k crash_restart -x` | ❌ Wave 0 |
| RETAIN-01/Pitfall 8 | **Within-method atomicity:** kill mid-`set_position`/mid-`add_order` (or simulate via a forced txn rollback) → assert the row is all-or-nothing | integration | `... -k atomic_within_method -x` | ❌ Wave 0 |
| GATE-01 | **Import quarantine:** import the backtest path → assert `sqlalchemy`/`cached_sql_storage` absent from `sys.modules` | unit | `pytest tests/unit/... -k import_quarantine -x` | ❌ Wave 0 |
| GATE-01 | **Oracle byte-exact:** `134 / 46189.87730727451` | integration | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| GATE-01 | **W1/W2 no regression** vs 15.7 s / 152.8 MB (±5% A/B) | perf gate | (existing v1.5 perf-gate harness) | ✅ exists |
| GATE-02 | mypy + warnings | gate | `poetry run mypy itrader && make test` | ✅ config exists |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/integration/storage/test_cached_sql_<concern>_storage.py -x` (the concern just touched).
- **Per wave merge:** `poetry run pytest tests/integration/storage -m integration` + `poetry run mypy itrader`.
- **Phase gate:** full `make test` green (main checkout) + oracle byte-exact + W1/W2 A/B + mypy --strict + `filterwarnings=["error"]` clean, before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/integration/storage/test_cached_sql_order_storage.py` — RETAIN-02/03 + Pitfall 7/8 (order seam; the one wired end-to-end)
- [ ] `tests/integration/storage/test_cached_sql_portfolio_storage.py` — RETAIN-02/03 (positions/reservations/snapshot-accumulators; component-level)
- [ ] `tests/integration/storage/test_cached_sql_signal_storage.py` — append-only mirror (no purge/read-through; minimal)
- [ ] An `import_quarantine` unit test (GATE-01) — assert the backtest import path pulls no SQL/wrapper symbol
- [ ] Reuse the existing `pg_backend` fixture — no new fixture needed
- [ ] (If A2 = dedicated table) a Phase-4 Alembic baseline migration for `portfolio_account_state`

## Security Domain

`security_enforcement` is not explicitly `false` → included. The surface is small: the wrapper composes the already-hardened Phase-3 stores (parameterized Core, no f-string SQL, creds from `SqlSettings`/`SecretStr` — SEC-01 closed in Phase 1) and writes almost no SQL of its own.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface in the storage layer (FastAPI app layer is N+4) |
| V3 Session Management | no | — |
| V4 Access Control | partial | Cross-portfolio isolation: `SqlPortfolioStateStorage` scopes every query to its bound `portfolio_id` (Pitfall 1, Phase-3 `sql_storage.py:65`) — the wrapper must NOT leak across portfolio boundaries (preserve the bound-id scoping) |
| V5 Input Validation | yes | Enum text validated on read via `order_*_map` (Phase-3 D-07); the wrapper adds no new input parsing |
| V6 Cryptography | no | No new crypto; money is `Numeric`, ids are UUIDv7 from `idgen` |

### Known Threat Patterns for {Postgres + SQLAlchemy Core}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via the wrapper's rehydration row-reads (reservations/locked-margin) | Tampering | Parameterized Core (`select(...).where(col == bindparam(...))`) — never f-string; reuse the Phase-3 `Table` objects |
| Credential leak in logs | Information disclosure | Never log the resolved DB URL; the wrapper sources an injected `SqlBackend`, never re-resolves creds (SEC-01 discipline) |
| Cross-portfolio data bleed on rehydration | Tampering / Info disclosure | Preserve the Phase-3 bound-`portfolio_id` scoping on every wrapper read |

## Project Constraints (from CLAUDE.md)

- **Event-driven, single `global_queue`:** the wrapper is an injected read/write store, NOT a handler — write-through happens *inside* the handler's own injected store, off the queue (the queue-only contract governs handler↔handler, not a handler's own store; PITFALLS Integration Gotchas). Do NOT emit a "persist" event.
- **Money = Decimal end-to-end:** `Numeric` ↔ `Decimal`, no `float()` except at the serialization/logging edge; no quantize on reservations/locked-margin (full precision). The wrapper adds no money column.
- **Single UUIDv7 (`idgen`):** no DB autoincrement, no second ID scheme; the optional account-state row's key is the `portfolio_id` UUID (no surrogate).
- **Determinism:** persisted timestamps use business `time` (never wall clock); every load query has a stable `ORDER BY` (Phase-3 already compliant); `sort_keys` on any JSON.
- **Indentation: all three `storage/` packages are 4-space** — match the `sql_storage.py` sibling exactly; do NOT normalize.
- **Test strictness:** `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` — only `unit`/`integration`/`slow`/`e2e` markers; dispose every engine/backend in a `finally` (an undisposed engine trips `ResourceWarning` → hard failure). Reuse the `pg_backend` fixture (disposes in `finally`).
- **mypy --strict:** the new `CachedSql*Storage` modules enter strict scope now (the Phase-3 `Sql*Storage` siblings already are — not in any `pyproject.toml` override). `live_trading_system.py` / `trading_interface.py` stay `ignore_errors` (D-live) — and D-01 leaves them untouched, so no strict-clean work lands on them this phase.
- **Guard-clause / early-exit style (auto-memory):** prefer negation + fast-exit guards over nested ifs (e.g. `_can_evict` returns `False` early on non-terminal).
- **GSD decision-coverage gate (auto-memory):** cite the D-NN tags in the plan's `must_haves`/`truths`/`objective`, not just body prose, or the blocking gate fails.

## Sources

### Primary (HIGH confidence — read directly from the tree)
- `itrader/order_handler/storage/{base,in_memory_storage,sql_storage,storage_factory}.py` — OrderStorage ABC (14 methods), working-set indexes, Sql txn boundaries (`add_order` L257, `update_order` L270, `_load_child_ids` L228), `'live'` arm
- `itrader/order_handler/order.py:85,86,144,149` — `parent_order_id`/`child_order_ids`, `is_active`/`is_terminal`
- `itrader/core/enums/order.py:46-88` — `OrderStatus` + `VALID_ORDER_TRANSITIONS` (terminal set)
- `itrader/order_handler/{admission,lifecycle,reconcile,brackets}/*.py` — all order write call-sites (grepped; lines in § Write-Through)
- `itrader/portfolio_handler/storage/{base,in_memory_storage,sql_storage,storage_factory}.py` — PortfolioStateStorage ABC (21 methods), bound-`portfolio_id` scoping, snapshot columns, `get_latest_snapshot`
- `itrader/portfolio_handler/{cash,position,transaction,metrics}/*_manager.py` — `_balance` (cash L64), `_realised_pnl_accumulator` (position L328) + `assert_accumulator_consistent` (L349-352), snapshot derivation, all state_storage write call-sites
- `itrader/portfolio_handler/portfolio.py:93,121,229,243` — `state_storage` hardcode, equity/realised derivation; `on_fill` (`portfolio_handler.py:654`)
- `itrader/strategy_handler/storage/{base,sql_storage,storage_factory}.py` — SignalStore ABC (4 methods), append-only
- `itrader/trading_system/live_trading_system.py` — daemon loop (L337-396), `'live'` order wiring (L125-150), signal hardcode (L113), `_publish_and_continue` (L217), `add_event` (L543)
- `itrader/trading_system/trading_interface.py:41,94` — API-thread `create_*_order` → `add_event` → `global_queue.put`
- `tests/integration/storage/conftest.py` — `pg_engine`/`engine`/`pg_backend` fixtures (the Phase-4 substrate)
- `pyproject.toml [tool.mypy]/[tool.pytest.ini_options]` — strict scope (Sql* not overridden), test strictness

### Secondary (HIGH — planning artifacts)
- `.planning/phases/04-retention-live-write-through-2-live-path/04-CONTEXT.md` — D-01..D-04, locked scope, discretion list
- `.planning/research/PITFALLS.md` — Pitfall 7 (live retention) + Pitfall 8 (write-through durability) in full
- `.planning/research/FEATURES.md` Q10 — purge/read-through/rehydration sequence (buffer-window dropped per D-02)
- `.planning/research/ARCHITECTURE.md` Pattern 2/3/4, Q9 (apply pattern; `DecimalAsText`/`write_through`-flag framing retracted)
- `.planning/phases/03-operational-sql-backends-2-store-layer/03-CONTEXT.md` — D-02 bracket FK, D-08 indexes, D-06 `'live'`-only arm
- `.planning/ROADMAP.md` → Phase 4 (four Success Criteria + research flag); `.planning/STATE.md` → Milestone Gate (two-part a/b)

### Tertiary (LOW — external precedent, not re-verified this session)
- NautilusTrader Cache concepts (purge APIs, bracket-parent contingency, restart rehydration) — via FEATURES survey; the contingency rule is ported onto `parent_order_id`/`child_order_ids`, not used directly

## Metadata

**Confidence breakdown:**
- Standard stack / no-new-deps: HIGH — verified against `pyproject.toml` + Phase-1/3 STATE entries.
- Write-through boundaries + call-site map: HIGH — every call-site grepped and cited by file:line; the Sql txn boundaries read directly.
- Bracket-parent-resident + read-through scope: HIGH — grounded in `is_terminal`/`child_order_ids` + the Phase-3 FK index.
- Thread-safety: HIGH — the daemon-sole-writer fact is read directly from `live_trading_system.py` + `trading_interface.py`.
- Accumulator split: HIGH on which scalars are purge-derived (read from `cash_manager.py`/`position_manager.py`); MEDIUM on the carrier choice (A2 — clean-vs-cheap tradeoff for the planner).
- Multi-row atomicity: MEDIUM-HIGH — the recommendation is sound given the locked ABC + scope, but the cross-method limitation is a real tension the owner should confirm (A1).

**Research date:** 2026-06-30
**Valid until:** ~2026-07-30 (stable — internal codebase + locked owner decisions; no fast-moving external dependency). Re-verify only if the live composition-root scope (D-01) changes or the Phase-3 schema is revised.
