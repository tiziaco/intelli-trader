# Phase 4: Retention + Live Write-Through (#2 — live path) - Pattern Map

**Mapped:** 2026-06-30
**Files analyzed:** 6 (3 new wrappers + 3 edited factories)
**Analogs found:** 6 / 6 (every file has an exact in-tree analog — this is a "new sibling in an established triple" phase)

> **Indentation (DO NOT normalize):** all three `*/storage/` packages are **4-space**. Copy the
> leading whitespace of the existing `sql_storage.py` sibling. `portfolio_handler/base.py` has a
> TAB-import / 4-space-class mix (tabs at the `TYPE_CHECKING` import block lines 10-11, 4-space class
> body) — match surrounding lines exactly. The *handler* modules (`order_handler/`, `portfolio_handler/`)
> are tab-indented but their `storage/` sub-packages are 4-space — do not be misled. A mixed-indent file
> raises `TabError` on import (Pitfall 12).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/order_handler/storage/cached_sql_storage.py` → `CachedSqlOrderStorage` | storage decorator (store) | CRUD + event-driven (purge-on-terminalize) | `order_handler/storage/sql_storage.py` (ABC + txn) + `in_memory_storage.py` (working set) + `order_handler/base.py` (ABC) | exact (composes both) |
| `itrader/portfolio_handler/storage/cached_sql_storage.py` → `CachedSqlPortfolioStateStorage` | storage decorator (store) | CRUD + transform (accumulator snapshot) | `portfolio_handler/storage/sql_storage.py` + `in_memory_storage.py` + `portfolio_handler/base.py` (ABC) | exact (composes both) |
| `itrader/strategy_handler/storage/cached_sql_storage.py` → `CachedSqlSignalStorage` | storage decorator (store) | append-only mirror (no purge/read-through) | `strategy_handler/storage/sql_storage.py` + `in_memory_storage.py` + `storage/base.py` (ABC) | exact (composes both) |
| `itrader/order_handler/storage/storage_factory.py` (EDIT `'live'` arm) | factory / config | request-response | the existing `'live'` arm in the same file (L53-61) | exact (same file) |
| `itrader/portfolio_handler/storage/storage_factory.py` (EDIT `'live'` arm) | factory / config | request-response | the existing `'live'` arm in the same file (L77-93) | exact (same file) |
| `itrader/strategy_handler/storage/storage_factory.py` (EDIT `'live'` arm) | factory / config | request-response | the existing `'live'` arm in the same file (L69-79) | exact (same file) |

**Not edited (D-01):** `portfolio_handler/portfolio.py:93`, `trading_system/live_trading_system.py:113` —
the live-composition-root hardcodes stay until N+4. The three `Sql<Concern>Storage` classes stay
**UNTOUCHED** (D-04 — the wrapper composes them, never modifies them).

---

## Pattern Assignments

### `CachedSqlOrderStorage` (storage decorator, CRUD + event-driven)

**Implements:** `OrderStorage` ABC (14 methods) — `order_handler/base.py`.
**Composes:** `self._store = SqlOrderStorage(backend)` (system of record) + `self._cache = InMemoryOrderStorage()` (working set) + `self._lock = threading.RLock()`.

**ABC surface to implement** (`order_handler/base.py:14-273`) — the 14 abstract methods the wrapper must
forward: `add_order`, `remove_order`, `remove_orders_by_ticker`, `get_pending_orders`, `get_order_by_id`,
`update_order`, `get_orders_by_ticker`, `clear_portfolio_orders`, `get_orders_by_status`,
`get_active_orders`, `get_orders_by_time_range`, `get_order_history`, `search_orders`,
`count_orders_by_status`. Note the `IdLike = Union[str, int, uuid.UUID]` alias is exported from
`order_handler/base.py:7`.

**Imports pattern** — copy the `sql_storage.py` header style (4-space, lazy-quarantined). Do NOT
re-export from `__init__.py` (importing it pulls SQLAlchemy — GATE-01). The `sql_storage.py` imports to
mirror (`sql_storage.py:26-55`):
```python
import uuid
import threading
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

from itrader.core.enums import OrderStatus
from itrader.logger import get_itrader_logger
from ..base import IdLike, OrderStorage
from .in_memory_storage import InMemoryOrderStorage
if TYPE_CHECKING:
    from .sql_storage import SqlOrderStorage   # type-only — keep the module SQL-import-light
    from ..order import Order
```

**Logger bind pattern** (mirrors every store) — `sql_storage.py:50` uses
`get_itrader_logger()`; bind a component:
```python
self.logger = get_itrader_logger().bind(component="CachedSqlOrderStorage")
```

**Write-through (store-first) core pattern** — Pitfall 8 persist-then-acknowledge. The store method
already opens one `engine.begin()` txn (`sql_storage.py:257-268` `add_order`,
`sql_storage.py:270-297` `update_order`); the wrapper only orders + mirrors + gates:
```python
def add_order(self, order: "Order") -> None:
    self._store.add_order(order)            # one txn (orders row + state_changes) — sql_storage.py:265
    with self._lock:
        self._cache.add_order(order)        # mirror into working set (in_memory_storage.py:132)

def update_order(self, order: "Order") -> bool:
    ok = self._store.update_order(order)    # store-first, one txn — sql_storage.py:275
    if not ok:
        return False
    with self._lock:
        self._cache.update_order(order)     # in_memory_storage.py:214
        if self._can_evict(order):          # terminal-state gate (purge-on-terminalize, D-02)
            self._cache.remove_order(order.id)
            if order.parent_order_id is not None:
                self._maybe_evict_parent(order.parent_order_id)
    return True
```

**Terminal-state gate / bracket-parent-resident** — copy the active/terminal predicates verbatim from
`order.py:144-151` (`is_active` = PENDING/PARTIALLY_FILLED, `is_terminal` = FILLED/CANCELLED/REJECTED/EXPIRED).
The bracket attrs are `order.parent_order_id` / `order.child_order_ids` (`order.py:85-86`). Guard-clause /
early-exit style (auto-memory):
```python
def _can_evict(self, order: "Order") -> bool:
    if not order.is_terminal:
        return False                        # never evict an open order (Pitfall 7)
    if order.child_order_ids:               # bracket PARENT — resident until ALL children terminal
        return all(self._child_is_terminal(cid) for cid in order.child_order_ids)
    return True
```

**Bracket sibling-status lookup (store side)** — DON'T maintain a `child_ids` cache; reuse the Phase-3
self-referential `parent_order_id` index. `SqlOrderStorage._load_child_ids` (`sql_storage.py:228-238`)
is the exact query (stable `ORDER BY (created_at, id)`):
```python
# sql_storage.py:233 — the bracket-resident invariant's store-side source
select(self.orders.c.id).where(self.orders.c.parent_order_id == bindparam("pid"))
    .order_by(self.orders.c.created_at, self.orders.c.id)
```

**Read-through pattern** (off the hot path; the open set is always resident in `_cache`):
```python
def get_order_by_id(self, order_id, portfolio_id=None):
    with self._lock:
        hit = self._cache.get_order_by_id(order_id, portfolio_id)   # in_memory_storage.py:202
    if hit is not None:
        return hit                          # open/resident — no store touch
    return self._store.get_order_by_id(order_id, portfolio_id)      # read-through (terminal/purged)
```
Cache-only (no read-through): `get_active_orders`, `get_pending_orders`, `get_orders_by_status`
(active status). Read-through to store: `get_order_history`, `search_orders`,
`count_orders_by_status`, `get_orders_by_time_range`, `get_orders_by_ticker`, terminal-status queries.

**Rehydration (open-only)** — uses the Phase-3 indexed active query. `SqlOrderStorage.get_active_orders`
(`sql_storage.py:400-402`) filters on `_ACTIVE_STATUS_VALUES` (`sql_storage.py:59-62`); the in-memory
`add_order` rebuilds the derived indexes via `_index_apply` (`in_memory_storage.py:132-140`):
```python
def rehydrate(self) -> None:
    with self._lock:
        for order in self._store.get_active_orders(None):   # PENDING/PARTIALLY_FILLED, indexed (D-08)
            self._cache.add_order(order)
            if order.parent_order_id is not None and \
               self._cache.get_order_by_id(order.parent_order_id) is None:
                parent = self._store.get_order_by_id(order.parent_order_id)
                if parent is not None:
                    self._cache.add_order(parent)            # filled parent of live child stays resident
```

---

### `CachedSqlPortfolioStateStorage` (storage decorator, CRUD + transform)

**Implements:** `PortfolioStateStorage` ABC (21 methods) — `portfolio_handler/base.py`:
`set_position`, `get_position`, `get_positions`, `remove_position`, `add_closed_position`,
`get_closed_positions`, `add_transaction`, `get_transaction_history`, `get_reserved_cash`,
`add_reservation`, `pop_reservation`, `get_locked_margin`, `get_locked_margin_for`, `add_locked_margin`,
`pop_locked_margin`, `add_cash_operation`, `get_cash_operations`, `add_snapshot`, `get_snapshots`,
`set_snapshots`, `snapshot_count`, `get_latest_snapshot`.
**Composes:** `self._store = SqlPortfolioStateStorage(backend, portfolio_id)` + `self._cache = InMemoryPortfolioStateStorage(max_snapshots=...)` + `RLock`.

**Critical: bound `portfolio_id` (Pitfall 1).** The ABC has NO `portfolio_id` parameter — the backend is
one-instance-per-Portfolio. `SqlPortfolioStateStorage.__init__(self, backend, portfolio_id)`
(`sql_storage.py:65-68`) binds it and scopes EVERY query (`.where(table.c.portfolio_id == self._portfolio_id)`).
The wrapper must carry the same bound id and preserve cross-portfolio isolation (V4 access control) —
never leak across the boundary on rehydration reads.

**Working-set structures the cache mirrors** (`in_memory_storage.py:28-54`):
- `_positions: Dict[str, Position]` — open positions by ticker (working state)
- `_reservations: Dict[str, Decimal]` — per-reference reserved cash (full precision, NO quantize)
- `_locked_margin: Dict[str, Decimal]` — per-position margin lock (distinct container)
- `_snapshots: deque(maxlen=max_snapshots)` — bounded; `set_snapshots` MUST rebuild a bounded deque
  (`in_memory_storage.py:139-142`), never a plain list (Pitfall 2 — list reassignment drops `maxlen`).

**Write-through call-sites** — each Phase-3 store method already opens `engine.begin()` (e.g.
`set_position` delete-open+insert in one txn `sql_storage.py:142-162` — already atomic; `add_snapshot`
MAX(seq)+1 then insert `sql_storage.py:467-473`). Wrapper = store-first then cache mirror, same shape as
the order wrapper.

**Read-through split** — cache-only (open/current): `get_positions`, `get_position`, `get_reserved_cash`,
`get_locked_margin`, `snapshot_count`/`get_latest_snapshot`. Read-through to store (history):
`get_closed_positions`, `get_transaction_history`, `get_cash_operations`, `get_snapshots`.

**Rehydration (open-only)** — `get_positions()` is the indexed `WHERE is_open = true` query
(`sql_storage.py:168-171`, Phase-3 `(portfolio_id, is_open)` index, D-08). `Position.is_open` is the
predicate. `get_latest_snapshot()` (`sql_storage.py:508-517`, `ORDER BY seq DESC LIMIT 1`) restores the
account aggregate + the two purge-derived accumulators (`cash_balance`, `realized_pnl`). The reservations /
locked-margin dicts repopulate from the per-reference rows (the wrapper reads the tables it owns; the ABC
`get_reserved_cash` returns only the SUM). **Never** load closed positions / transaction history into the
working set. NOTE (D-01/A3): the *restoration into* `CashManager._balance` / `PositionManager._realised_pnl_accumulator`
is N+4 — Phase 4 builds + component-tests the wrapper's persist/return/rehydrate ability only.

---

### `CachedSqlSignalStorage` (storage decorator, append-only mirror)

**Implements:** `SignalStore` ABC (4 methods) — `strategy_handler/storage/base.py:17-79`:
`add(record)`, `get_all()`, `by_strategy(strategy_id)`, `by_ticker(ticker)`.
**Composes:** `self._store = SqlSignalStorage(backend)` + `self._cache = InMemorySignalStore()` + `RLock`.

**Simplest wrapper — no purge, no read-through, no terminal gate.** Signals are append-only and NEVER
purged; the cache is a pure full mirror. `add` is store-first then cache-mirror; `get_all`/`by_strategy`/
`by_ticker` serve from cache (full mirror). `rehydrate()` is optional (`self._store.get_all()` →
cache mirror) — not required by any success criterion.

**Imports / style** — mirror `strategy_handler/storage/in_memory_storage.py:11-16` (4-space, module
docstring notes "matches the order_handler/storage/ siblings"). Reject a duplicate `signal_id`
(`in_memory_storage.py:41-42`) — the in-memory backend already raises `ValueError` on dup; the cache
mirror inherits this.

---

## Factory `'live'` arm edits (3 files — exact in-file analog)

Each factory keeps the existing structure; the ONLY change is the `'live'` branch return value: wrap the
`Sql*Storage` in the new `CachedSql*Storage`. The lazy import (inside the `'live'` branch) is preserved —
GATE-01 quarantine. The wrapper import goes INSIDE the branch too (never at module top, never in
`__init__.py`).

### `order_handler/storage/storage_factory.py` (`'live'` arm, L53-61)
Existing:
```python
elif environment == 'live':
    from itrader.config.sql import SqlSettings
    from itrader.storage import SqlBackend
    from .sql_storage import SqlOrderStorage
    resolved = backend if backend is not None else SqlBackend(SqlSettings.default())
    return SqlOrderStorage(resolved)
```
Edit → add `from .cached_sql_storage import CachedSqlOrderStorage` inside the branch and
`return CachedSqlOrderStorage(SqlOrderStorage(resolved))`.

### `portfolio_handler/storage/storage_factory.py` (`'live'` arm, L77-93)
Existing returns `SqlPortfolioStateStorage(sql_backend, portfolio_id)` (note: `portfolio_id` is REQUIRED —
the factory raises `ConfigurationError` if None, L78-82). Edit → wrap:
`return CachedSqlPortfolioStateStorage(SqlPortfolioStateStorage(sql_backend, portfolio_id))`
(thread `max_snapshots` into the composed `InMemoryPortfolioStateStorage` working set).

### `strategy_handler/storage/storage_factory.py` (`'live'` arm, L69-79)
Existing returns `SqlSignalStorage(backend)`. Edit → wrap:
`return CachedSqlSignalStorage(SqlSignalStorage(backend))`.

**`ConfigurationError` is the convention** for the unknown-environment / missing-param branch (all three
factories use `itrader.core.exceptions.ConfigurationError`, not bare `Exception`).

---

## Shared Patterns

### Composition-not-inheritance (Phase 1 D-01)
**Source:** every `Sql*Storage.__init__` (`order/sql_storage.py:76`, `portfolio/sql_storage.py:65`) —
`self.backend = backend; self.engine = backend.engine` (has-a, never a cross-concern god base).
**Apply to:** all three wrappers — `self._store = Sql*Storage(...)`, `self._cache = InMemory*Storage()`.
The wrapper *has-a* store + *has-a* working set; it implements the ABC by forwarding.

### Store-first write-through (Pitfall 8)
**Apply to:** every mutating ABC method on all three wrappers. The store commit returns BEFORE the cache
is mutated (`with self._lock: self._cache.<mutate>(...)` after `self._store.<mutate>(...)`). The cache is
always rebuildable from the store; the inverse is not. Each `Sql*` method is already one `engine.begin()`
txn (within-method atomicity — the Pitfall-8 verification target). Cross-method atomicity (bracket =
3 `add_order`; fill = independent manager writes) is N+4 reconciliation (research A1).

### Backend-selection at wiring / GATE-01 quarantine (Pitfall 3)
**Source:** the lazy-import `'live'` arm in all three `storage_factory.py` (`order:54-58`).
**Apply to:** the factory edits — wrapper imports stay INSIDE the `'live'` branch; never re-export
`CachedSql*Storage` from any package `__init__.py`. The backtest/`test` arm stays `InMemory*Storage`
(imports no SQL). Verified by the import-quarantine test (`sqlalchemy` / `cached_sql_storage` absent
from `sys.modules` on the backtest path).

### Single-writer + RLock read-through guard (research A4)
**Source:** the daemon-sole-writer fact (`live_trading_system.py` `_event_processing_loop`; the API thread
only enqueues via `global_queue.put`). **Apply to:** all three wrappers — one `threading.RLock`, taken
briefly around cache mutation (add/update/evict) and around any read-through cache lookup. Uncontended in
the as-wired Phase-4 system (daemon-only); built API-thread-safe for the imminent FastAPI layer. Start
with `RLock`; promote to `readerwriterlock` only if contention is measured (keep-only-measured).

### Stable ORDER BY / determinism (Pitfall 10)
**Source:** every Phase-3 load query already has a stable `ORDER BY` — orders `(created_at, id)`
(`order/sql_storage.py:247-248`), snapshots `seq` (`portfolio/sql_storage.py:479`,
`get_latest_snapshot` `seq DESC LIMIT 1` `:512`). **Apply to:** the wrapper introduces NO new query
except rehydration row-reads — reuse the Phase-3 `Table` objects + parameterized Core (`bindparam`),
never f-string SQL. Persisted timestamps use business `time`, never wall clock.

### Logger bind
**Source:** `get_itrader_logger().bind(component="ClassName")` (CLAUDE.md convention, used in every store).
**Apply to:** each wrapper `__init__`.

---

## No Analog Found

None. Every new file is a new member of an existing per-concern triple (`InMemory` / `Sql` / `CachedSql`);
every edited file is an in-place `'live'`-arm change with the analog in the same file. The one genuinely
new structure — the optional `portfolio_account_state` accumulator-carrier table (research A2) — is a
planner decision (dedicated table vs reuse `equity_snapshots`); if the dedicated table is chosen, its
analog is `build_portfolio_tables` in `portfolio_handler/storage/models.py` + the existing
`equity_snapshots` row mapping (`portfolio/sql_storage.py:467-517`).

## Metadata

**Analog search scope:** `itrader/order_handler/storage/`, `itrader/portfolio_handler/storage/`,
`itrader/strategy_handler/storage/`, `itrader/order_handler/base.py`, `itrader/portfolio_handler/base.py`,
`itrader/order_handler/order.py`.
**Files scanned (read):** `order_handler/base.py`, `order_handler/storage/{in_memory_storage,sql_storage,storage_factory}.py`,
`order_handler/order.py`, `portfolio_handler/base.py`, `portfolio_handler/storage/{in_memory_storage,sql_storage,storage_factory}.py`,
`strategy_handler/storage/{base,in_memory_storage,storage_factory}.py`.
**Pattern extraction date:** 2026-06-30
