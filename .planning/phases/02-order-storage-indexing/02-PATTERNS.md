# Phase 2: Order-Storage Indexing - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 2 (1 modified, 1 modified/extended)
**Analogs found:** 2 / 2 (both exact in-repo analogs)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/order_handler/storage/in_memory_storage.py` (MODIFIED) | storage / in-memory store | CRUD + derived-cache maintenance | `itrader/execution_handler/matching_engine.py` (`_resting` + `_trails` parallel side-table) | exact — same "source-of-truth dict + parallel derived dict kept consistent at every write/pop site" idiom |
| `tests/unit/order/test_order_storage.py` (MODIFIED/EXTENDED) | test (unit) | request-response (query assertions) | the same file's existing fixture + tests (`store` SimpleNamespace, `test_filled_order_leaves_active_queries_via_predicate`, `test_add_rejected_order_persists_without_entering_active_book`) | exact — extend in-house style |

**Key context:** No new files are created. The ABC `itrader/order_handler/base.py` stays **unchanged** (D-05) — included below only as a read-only contract reference, never edited.

---

## Pattern Assignments

### `itrader/order_handler/storage/in_memory_storage.py` (storage, CRUD + derived-cache maintenance)

**Primary analog:** `itrader/execution_handler/matching_engine.py` — the only place in the codebase that keeps a **parallel derived dict consistent with a source-of-truth dict by maintaining both at every mutation site**. The indexes here mirror its `_resting` / `_trails` discipline exactly.

**Self-analog (the file being edited):** the existing `add_order`/`update_order`/`remove_order`/`_orders` methods are the write/read seams the index logic hooks into. Match them precisely.

#### Indentation hazard (Pitfall 6 — load-bearing)

`in_memory_storage.py` uses **4 spaces** (verified: lines 34-184 are space-indented; it imports `from ..base` which is also 4-space). MOST `order_handler/` sibling modules (`order_manager.py`, `reconcile/`, `lifecycle/`) use **tabs**. A tab-indented edit in this file produces a `TabError` or a mixed-indent file that breaks the module. The test file `tests/unit/order/test_order_storage.py` is also **4-space**. Match each file; never normalize.

#### Imports pattern — current file head (lines 1-8), and the required runtime-import change

```python
import uuid
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..base import OrderStorage, IdLike

if TYPE_CHECKING:
    from ..order import Order
    from ...core.enums import OrderStatus
```

`OrderStatus` is **`TYPE_CHECKING`-only today (line 8)**. The shadow registry needs `OrderStatus` at **runtime** (as a dict key and for the module-level `_ACTIVE_STATUSES` frozenset). A `TYPE_CHECKING`-only import will `NameError` at runtime — move it to a real runtime import (e.g. `from ...core.enums import OrderStatus` at module top, alongside the `uuid` import) or import locally. Keep `from __future__` absent (the file uses string-literal forward refs like `'Order'`).

#### The "active" predicate — single source (do NOT re-derive)

`order.is_active` already encodes the active set. From `itrader/order_handler/order.py` lines 144-146:

```python
@property
def is_active(self) -> bool:
    return self.status in [OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED]
```

Define the index's active set ONCE at module level to stay in lockstep with `is_active` (Don't-Hand-Roll table, RESEARCH):

```python
_ACTIVE_STATUSES: frozenset['OrderStatus'] = frozenset(
    {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED}
)
```

#### Index state — add to `__init__` ALONGSIDE the source-of-truth dict

The current `__init__` (lines 34-40) holds only `self._by_id`. The new caches sit next to it, never replacing it (D-20). This mirrors `MatchingEngine.__init__` (matching_engine.py lines 106-113), which declares `self._resting` (truth) then `self._trails` (parallel cache) with a comment that the side-table is popped at every `_resting.pop` site so no entry leaks:

```python
# matching_engine.py lines 109-113 — the analog idiom to copy:
self._resting: dict[OrderId, OrderEvent] = {}
self._trails: dict[OrderId, TrailState] = {}
```

Add to `InMemoryOrderStorage.__init__` (strict-typed per mypy notes, RESEARCH "mypy --strict Typing Notes"):

```python
self._by_id: Dict[uuid.UUID, 'Order'] = {}                          # SOURCE OF TRUTH (D-20, unchanged)
self._active_by_portfolio: Dict[uuid.UUID, Dict[uuid.UUID, None]] = {}   # derived cache (D-02)
self._by_status: Dict['OrderStatus', Dict[uuid.UUID, None]] = {}         # derived cache, active-only (D-02/D-10)
self._last_indexed_status: Dict[uuid.UUID, 'OrderStatus'] = {}           # shadow registry (D-03)
```

> Bucket value type is `None` (insertion-ordered membership set via `dict[oid, None]`, D-06/D-08) — NOT a plain `set` (hash-ordered, breaks byte-exact oracle). Assign `bucket[oid] = None`.

#### Core pattern 1 — diff-on-write maintenance via shadow registry (D-03)

The matching engine pops `_trails` at **every** `_resting.pop` site (matching_engine.py lines 144-145, 377-378, 448-449, 452-453) so the parallel dict never drifts. Replicate that discipline: one private `_index_apply(order)` called by both `add_order` and `update_order`, plus an `_index_remove(order_id)` for the delete paths (RESEARCH Open Question 2 recommendation). Shape (4-space, derived from RESEARCH Pattern 1):

```python
def _index_apply(self, order: 'Order') -> None:
    """Reconcile both caches + shadow registry for one order (idempotent)."""
    oid = order.id
    pid = order.portfolio_id                       # immutable per order (D-03)
    old_status = self._last_indexed_status.get(oid)   # None for a brand-new id (Pitfall 3)
    new_status = order.status
    if old_status == new_status:
        return                                     # PENDING->PENDING modify / EXPIRED no-op: no bucket move
    was_active = old_status in _ACTIVE_STATUSES    # None => was absent
    is_active = new_status in _ACTIVE_STATUSES
    if is_active and not was_active:
        self._active_by_portfolio.setdefault(pid, {})[oid] = None   # insertion-ordered append
    elif was_active and not is_active:
        bucket = self._active_by_portfolio.get(pid)
        if bucket is not None:
            bucket.pop(oid, None)
            if not bucket:
                del self._active_by_portfolio[pid]   # keep get_active_orders(None) clean
    if was_active:
        self._by_status[old_status].pop(oid, None)
    if is_active:
        self._by_status.setdefault(new_status, {})[oid] = None
    self._last_indexed_status[oid] = new_status
```

Critical edge cases this must handle (from the D-04 audit / Maintenance Matrix):
- **Add-of-already-terminal** (REJECTED added by admission, #8-10): `add_order` reads `order.status` → not active → never enters active book. Guard test: `test_add_rejected_order_persists_without_entering_active_book` (test_order_storage.py:252) must stay green.
- **Re-add of existing id** (`test_update_order`): route `add_order` through the SAME diff logic — idempotent by construction (Pitfall 4).
- **New id, same-status record** (forced liquidation, portfolio_handler.py:524 PENDING→PENDING then add): registry has no entry → `old_status` is `None` → `None != PENDING` correctly triggers the add. Never pre-seed the registry (Pitfall 3).
- **`remove_order` / clear / by_ticker must pop the registry too** or it leaks and could diff against a stale status (Pitfall 5).

#### Core pattern 2 — index-backed query preserving insertion order (D-06/D-08)

Read ids out of the insertion-ordered bucket and materialize from `_by_id`. Current `get_active_orders` (lines 134-136) is the scan being replaced:

```python
# BEFORE (lines 134-136):
def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
    return [order for order in self._orders(portfolio_id) if order.is_active]
```

After (per-portfolio = single lookup; `None` = scan-fallback for byte-identical global order, Pitfall 1 option a):

```python
def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
    if portfolio_id is not None:
        bucket = self._active_by_portfolio.get(portfolio_id, {})   # type: ignore[arg-type]
        return [self._by_id[oid] for oid in bucket]
    # None path: NO hot caller (verified — reconcile/lifecycle pass concrete pids).
    # Scan _by_id filtered by active-index membership to keep GLOBAL insertion order
    # byte-identical to today's flat scan (D-08). Pitfall 1 option (a).
    return [o for o in self._by_id.values() if o.id in self._last_indexed_status
            and o.status in _ACTIVE_STATUSES]
```

> **Pitfall 1 (CRITICAL ordering):** today's `None` path yields **global `add_order` order** (one flat scan, portfolios interleaved). A naive `for bucket in active_by_portfolio.values()` union yields **grouped-by-portfolio** order — same set, different sequence — which can break the byte-exact oracle / D-09 test. Use the scan-fallback for `None`; it costs nothing because no production hot caller passes `None` (`reconcile_manager.py:319` passes `fill_event.portfolio_id`; `lifecycle_manager.py:253` iterates per concrete `portfolio_id`).

#### Rerouting the three active-set scanners (D-07)

| Method | Current scan (line) | Reroute to |
|--------|---------------------|------------|
| `get_pending_orders` | lines 75-91 (`self._orders(...)` + `is_active` filter, builds nested `{pid:{id:order}}`) | source ids from `active_by_portfolio`; build the same nested-dict shape |
| `remove_orders_by_ticker` | lines 65-73 (`self._orders(portfolio_id)` + `is_active and ticker==`) | source candidate ids from `active_by_portfolio[pid]`, filter `order.ticker==ticker`, pop each from `_by_id` + both caches + registry |
| `clear_portfolio_orders` | lines 116-126 (`self._orders(portfolio_id)` + `is_active`) | source from `active_by_portfolio[pid]`; clear bucket + caches + registry |

All three already filter on `is_active` today, so sourcing from the active index is **exactly equivalent** (terminal orders stay in `_by_id` as history — they were never in the active index).

#### Cold queries — leave UNCHANGED (D-01/D-10)

Keep scanning `_by_id` (do NOT touch): `get_orders_by_time_range` (138-144), `search_orders` (164-175), `get_order_history` (146-162), `get_orders_by_ticker` (112-114), `count_orders_by_status` (177-183), `get_order_by_id` (93-103, O(1)), and `get_orders_by_status(terminal)`. For `get_orders_by_status`, only the **active-status** branch reads `by_status`; terminal statuses fall back to scanning (D-10).

#### Error handling pattern

There is no try/except in this storage class today, and none is added — D-04 explicitly rejects a hot-path runtime consistency guard (it would burn the cycles the phase saves). Correctness is held by audit + the oracle + the D-09 test, not runtime guards. (Contrast: the matching engine's `try/except (TypeError, ValueError, KeyError, InvalidOperation)` at matching_engine.py:359-368 exists because it processes externally-shaped resting orders per bar — not applicable to this internal index maintenance.)

---

### `tests/unit/order/test_order_storage.py` (test, unit)

**Analog:** the existing tests in the SAME file — match the house fixture and assertion style exactly.

#### Fixture pattern (lines 19-57) — reuse this `store` fixture verbatim

```python
@pytest.fixture
def store():
    storage = InMemoryOrderStorage()
    pid1 = uuid.uuid4(); pid2 = uuid.uuid4()
    oid1 = uuid.uuid4(); oid2 = uuid.uuid4(); oid3 = uuid.uuid4()
    order1 = Order(time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
                   ticker="BTCUSDT", action=Side.BUY, price=40000.0, quantity=0.1,
                   exchange="binance", strategy_id=1, portfolio_id=pid1, id=oid1)
    # order2: pid1 ETHUSDT PENDING; order3: pid2 BTCUSDT PENDING
    return SimpleNamespace(storage=storage, pid1=pid1, pid2=pid2,
                           oid1=oid1, oid2=oid2, oid3=oid3,
                           order1=order1, order2=order2, order3=order3)
```

New tests take `store` and use `store.storage`, `store.pid1`, `store.order1`, etc. — same SimpleNamespace shape. Imports already present at the top of the file (lines 1-13): `uuid`, `datetime/UTC`, `pytest`, `InMemoryOrderStorage`, `Order`, `OrderType/OrderStatus/OrderTriggerSource/Side`.

#### In-place status transition pattern (lines 100-104) — for maintenance-matrix tests

```python
assert store.order1.add_fill(store.order1.quantity, store.order1.price, store.order1.time)
assert store.order1.status == OrderStatus.FILLED
```

This mutates status **in place** (the D-03 reason). After it, the D-09/maintenance test must call `store.storage.update_order(store.order1)` to drive index reconciliation, then assert the order left both `get_active_orders` and `get_orders_by_status(active)`.

#### Assertion-order pattern (lines 107-111, 278-282) — for the D-09 equivalence test

The existing tests already assert ordered id-lists out of active queries:

```python
active = store.storage.get_active_orders(store.pid1)
assert [o.id for o in active] == [store.oid2]
```

The D-09 order-equivalence test follows this: build an independent oracle list by scanning `_by_id` in insertion order filtered by `is_active`, then assert `get_active_orders` / `get_pending_orders` / `get_orders_by_status(active)` match it on BOTH the per-portfolio AND `None` paths (RESEARCH Wave 0 Gaps).

#### REJECTED-add guard to keep green (lines 252-282)

`test_add_rejected_order_persists_without_entering_active_book` constructs a PENDING order, calls `add_state_change(OrderStatus.REJECTED, ...)`, then `add_order`s it, and asserts it is absent from active queries but present in `get_orders_by_status(REJECTED)`. This is the Pitfall 2 guard — it must stay green unchanged.

---

## Shared Patterns

### Derived-cache-over-source-of-truth maintenance (the central pattern)

**Source:** `itrader/execution_handler/matching_engine.py` lines 106-113 (`__init__`: truth dict `_resting` + parallel cache `_trails`), lines 142-145 (`cancel`: pop both), lines 377-378 / 448-449 / 452-453 (every `_resting.pop` is mirrored by `_trails.pop`).
**Apply to:** every write method of `InMemoryOrderStorage` (`add_order`, `update_order`, `remove_order`, `remove_orders_by_ticker`, `clear_portfolio_orders`).
**Idiom to copy:** the truth dict is authoritative; the parallel cache is maintained at the SAME sites that touch the truth dict, and is popped wherever the truth dict is popped so it never leaks/drifts. Comment the invariant in code the way matching_engine.py does ("popped at every `_resting.pop` site so no entry leaks").

```python
# matching_engine.py:142-145 — the maintenance discipline:
def cancel(self, order_id: OrderId) -> bool:
    self._trails.pop(order_id, None)               # parallel cache
    return self._resting.pop(order_id, None) is not None   # source of truth
```

### Insertion-ordered membership set via `dict[key, None]`

**Source:** language guarantee (CPython 3.7+) — used throughout the repo (e.g. `get_pending_orders` builds `result.setdefault(pid, {})[id] = order` at in_memory_storage.py:90).
**Apply to:** both index buckets (`_active_by_portfolio[pid]`, `_by_status[status]`).
**Why:** preserves byte-identical output order (D-06/D-08); a plain `set` is hash-ordered and breaks the byte-exact oracle.

### Native-UUID keying guard (D-14)

**Source:** `in_memory_storage.py` lines 54-56 and 95-97.
```python
if not isinstance(order_id, uuid.UUID):
    return False   # a non-UUID id can never be a stored key
```
**Apply to:** unchanged — keep the existing guards in `remove_order` / `get_order_by_id`. The index dicts key on the runtime `uuid.UUID` values of `order.id` / `order.portfolio_id` (RESEARCH mypy notes: annotate `uuid.UUID`, widen to `IdLike` only if mypy complains about facade passthrough).

### ABC stays query-shaped and UNCHANGED (D-05)

**Source:** `itrader/order_handler/base.py` (full file — all 13 abstract methods are query-shaped, return `List['Order']` / `Optional['Order']` / `bool` / `int` / nested dict).
**Apply to:** confirm NO method signature changes. The indexes are an internal cache of `InMemoryOrderStorage` only; a future `PostgreSQLOrderStorage` satisfies the same contract via native SQL indexes. No `ensure_index`/`rebuild` hooks on the base class (rejected, D-05). The D-05a seam audit (RESEARCH) confirms every ABC method is SQL-expressible — documentation only, no Postgres code.

---

## No Analog Found

None. Both files have exact in-repo analogs (the matching engine's parallel-side-table maintenance idiom; the test file's own existing fixture/assertion style). No file needs to fall back to RESEARCH.md generic patterns.

---

## Metadata

**Analog search scope:** `itrader/order_handler/storage/`, `itrader/order_handler/base.py`, `itrader/order_handler/order.py` (predicate + mutation site), `itrader/execution_handler/matching_engine.py` (parallel-dict maintenance), `itrader/portfolio_handler/position/` (checked — no derived-index pattern), `tests/unit/order/test_order_storage.py`.
**Files scanned:** 6 read + 2 grep audits.
**Pattern extraction date:** 2026-06-23
