# Phase 2: Order-Storage Indexing - Research

**Researched:** 2026-06-23
**Domain:** In-memory data-structure indexing for an event-driven order store (Python 3.13, behavior-preserving perf refactor)
**Confidence:** HIGH (everything verified against the actual codebase; no external library introduced)

## Summary

This phase replaces the linear `{id: order}` scan in `InMemoryOrderStorage` (W1 hotspot #1, ~37% CPU `[CITED: perf/results/PERF-BASELINE-RESULTS.md §2]`) with two derived secondary indexes — `active_by_portfolio` and an active-only `by_status` — kept consistent over the flat dict via a private shadow-key registry. The flat dict stays the sole source of truth (D-20). It is a pure data-structure change contained to **one file** (`itrader/order_handler/storage/in_memory_storage.py`); no `Order` entity change, no caller change, no `OrderStorage` ABC change.

The single highest-risk thing in this phase is **index staleness**: an `order.status` mutation that is not followed by a `storage.update_order(order)` would leave the index disagreeing with the flat dict, silently corrupting query results and breaking the byte-exact oracle. I completed the D-04 audit (below) by tracing every status-mutation site to its storage write. **Result: every production mutation site is correctly paired with a storage write. No staleness bug exists in the current code.** Two non-obvious edge cases were found that the maintenance logic must handle: (1) `add_order` can receive an order that is **already terminal** (REJECTED), and (2) `add_state_change` is called with `allow_same_status=True` for a `PENDING→PENDING` record before `add_order` (forced-liquidation path) — neither changes a bucket but both must not corrupt the registry.

**Primary recommendation:** Implement the two indexes as `dict[portfolio_id, dict[order_id, None]]` and `dict[OrderStatus, dict[order_id, None]]` (insertion-ordered buckets, D-06/D-08) plus a `dict[order_id, OrderStatus]` shadow registry, all private to `InMemoryOrderStorage`. Hook maintenance into exactly the five write methods (`add_order`, `update_order`, `remove_order`, `remove_orders_by_ticker`, `clear_portfolio_orders`). Reroute the three active-set scanners (`get_active_orders`, `get_pending_orders`, `remove_orders_by_ticker`, `clear_portfolio_orders`) through `active_by_portfolio`. Keep all cold/audit queries scanning. Gate on `make perf-w1` (≥5% wall-clock) + the byte-exact oracle + a new order-equivalence regression test.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (index scope = hot queries only):** Index only active-orders-by-portfolio and active-status. Cold/audit queries (`get_orders_by_time_range`, `search_orders`, `get_order_history`) keep scanning the flat dict.
- **D-02 (index shape = "Option A", nested-by-portfolio):**
  - `active_by_portfolio: {portfolio_id: <ordered set of order_id>}` — serves the dominant `get_active_orders(portfolio_id)` as a single direct lookup. `get_active_orders(None)` = union of all portfolios' active sets.
  - `by_status: {status: <ordered set of order_id>}` — serves `get_orders_by_status`.
  - Composite `(portfolio_id, status)` (Option B) was considered and **rejected**.
- **D-03 (shadow-key registry):** `InMemoryOrderStorage` keeps a private `{order_id: last_indexed_status}` registry (portfolio_id immutable, read off the order). `add_order`/`update_order`/`remove_order` diff old→new and patch the affected buckets, then refresh the registry. No `Order` entity change, no caller change. A transition-aware write API was **rejected**.
- **D-04 (invariant by audit + test, not runtime guard):** Index correctness depends on "every `order.status` mutation is followed by `storage.update_order(order)`". Research audits every mutation site, locks the invariant in writing, relies on the oracle + determinism double-run to catch drift. **No hot-path runtime consistency guard.**
- **D-05 (indexes private to InMemory; ABC unchanged):** `OrderStorage` (ABC) stays query-shaped and unchanged. Indexes are an internal cache of `InMemoryOrderStorage` only. **No interface change.** `ensure_index`/`rebuild` hooks on the base class were **rejected**.
- **D-05a (no-leak via audit + document):** Audit each interface method (return types, the `get_pending_orders` nested-dict shape, the `IdLike` union, ordering guarantees) and confirm it is expressible by a SQL backend — document anything that isn't. **No Postgres code this phase.** Drafting a Postgres conformance test now was **rejected**.
- **D-06 / D-08 (insertion-ordered buckets):** Back each index bucket with an insertion-ordered structure (e.g. `dict[order_id, None]`), NOT a plain `set`. Query results come out in the same order as today's flat-dict scan — byte-identical by construction. Plain sets + sort-at-query and plain sets accepting hash order were both **rejected**.
- **D-09 (order-equivalence regression test):** Add a targeted test asserting index-backed query order == prior full-scan order.
- **D-10 (active statuses only):** `by_status` indexes only `PENDING`/`PARTIALLY_FILLED`; an order is dropped from `by_status` on terminal transition. Terminal-status queries fall back to scanning the flat dict.
- **D-07 (reroute all three active-set scanners):** `get_pending_orders`, `remove_orders_by_ticker`, and `clear_portfolio_orders` all reroute to derive their working set from `active_by_portfolio`.
- **D-11 (accept added memory; gate is wall-clock):** Pass on ≥5% wall-clock improvement; peak memory tracked alongside, watched, no hard ceiling.

### Claude's Discretion
- Exact names/types of the index attributes and the shadow registry; the precise ordered-set representation (`dict[id, None]` vs an ordered-dict wrapper); how `get_active_orders(None)` unions the per-portfolio sets — all left to planning, within D-02/D-06/D-08.
- Whether the D-04 audit yields any defensive assert in non-hot paths (e.g. test-only helpers) — planner's call; the contract (audited + tested) is what matters.

### Deferred Ideas (OUT OF SCOPE)
- **Composite `(portfolio_id, status)` index (Option B)** — rejected for this phase (D-02). Revisit only if a future hot consumer of terminal-status or arbitrary (portfolio, status) queries appears.
- **Indexing terminal statuses / cold queries** (time-range, search, history) — deferred (D-01, D-10).
- **Actual PostgreSQL order storage (PERSIST-01)** — built in the N+3b Persistence milestone, not here.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-01 | Order-storage queries stop linear-scanning the full flat `{id: order}` dict, removing the largest W1 hotspot (~37% CPU), with the flat dict still the source of truth (D-20) and the interface designed so a future Postgres backend satisfies the same contract. | The Maintenance Matrix (below) specifies how the two indexes + shadow registry replace the `_orders()` scan in the four active-query methods; the D-04 audit confirms the invariant the indexes depend on holds; the D-05a seam audit confirms no in-memory-only assumption leaks into the ABC. Gate (b) (`make perf-w1`, ≥5% wall-clock) measures the removal of hotspot #1. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

| Directive | Application to this phase |
|-----------|---------------------------|
| **Indentation:** `in_memory_storage.py` uses **4 spaces**; most `order_handler/` modules use **tabs** — match each file, never normalize. | `in_memory_storage.py` (the edited file) is **4-space**. Confirmed by reading the file (lines 34-184 are 4-space). Any new method/index code in it must be 4-space. The test file `tests/unit/order/test_order_storage.py` is also 4-space. |
| **Money is Decimal end-to-end.** | This phase touches NO money. Indexes key on `order_id`/`portfolio_id`/`status` only. No Decimal surface. |
| **Single UUIDv7 scheme via `idgen`.** | No new ID scheme. Indexes key on the existing native `uuid.UUID` order ids and `PortfolioId`. |
| **`mypy --strict` over `itrader`.** | `in_memory_storage.py` is **in strict scope** — it is NOT in the `[[tool.mypy.overrides]] ignore_errors` list (only `postgresql_storage` and `sql_handler` are deferred). New index/registry types must be strict-clean. See Typing section. |
| **Test strictness:** `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; only `unit`/`integration`/`slow`/`e2e` markers declared. | The new D-09 test lands under `tests/unit/order/` (auto-tagged `unit` by `tests/conftest.py`). No new marker needed. Any warning fails the suite. |
| **Components emit events, never call across domains.** | Not relevant — this phase is contained to one storage class behind the already-injected `OrderStorage` seam. No queue, no cross-domain calls. |
| **Read-model seams.** | `OrderManager` reaches storage via the injected storage object; behavior preserved. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Active-orders-by-portfolio query | Storage layer (`InMemoryOrderStorage`) | — | Owns the flat dict; the index is its private cache. D-05 keeps it off the ABC. |
| Active-status query | Storage layer | — | Same — `by_status` is internal cache. |
| Index consistency on write | Storage layer (write methods) | Order entity (status mutation) | The order mutates status in place; the storage write seam is where the index reconciles old→new (D-03 shadow registry). |
| Status mutation correctness | Order entity (`add_state_change`) | — | The single `self.status = new_status` site (order.py:441). Callers must pair it with a storage write — proven by the D-04 audit, not enforced at runtime. |
| Hot-path query consumers | Order-handler managers (`reconcile`, `lifecycle`) | — | Unchanged — they call the same `get_active_orders` signature; only its internal implementation gets faster. |

## Standard Stack

**No new dependencies.** This phase uses only the Python 3.13 stdlib already in use. The "ordered set" is a built-in `dict` (insertion-ordered since CPython 3.7, guaranteed by the language spec).

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dict` (stdlib) | Python 3.13 | Insertion-ordered bucket (`dict[order_id, None]`) + the two index maps + the shadow registry | `dict` preserves insertion order by language guarantee (CPython 3.7+, PEP-cemented). A plain `set` is hash-ordered and would break byte-identical output (D-06/D-08). No third-party ordered-set package is needed or wanted. |
| `uuid` (stdlib) | Python 3.13 | Native `uuid.UUID` order/portfolio keys (D-14) | Already the storage key scheme. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `dict[order_id, None]` bucket | `collections.OrderedDict` | OrderedDict adds nothing over a plain `dict` on 3.13 (order is already guaranteed) and carries a heavier per-node footprint. Avoid. |
| `dict[order_id, None]` bucket | A third-party ordered-set (`sortedcontainers`, `orderedset`) | New dependency, slower membership for our access pattern, and we don't need sorting — we need insertion order. Rejected (D-06). |
| `dict[order_id, None]` bucket | `set[order_id]` + sort at query | Hash-ordered; sorting at query reintroduces O(n log n) per query AND changes the order vs today's flat-dict scan → breaks the oracle. Explicitly rejected by D-08. |

**Installation:** none.

## Package Legitimacy Audit

> Not applicable — this phase installs **no external packages**. It uses only the Python 3.13 standard library (`dict`, `uuid`), already present. No registry verification needed.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────────────────────────┐
   status mutation        │  Order entity (order.py)                     │
   (the ONLY site:        │  add_state_change()  →  self.status = X      │
    order.py:441)         │  wrappers: add_fill / cancel / reject /      │
                          │            expire / modify                   │
                          └───────────────────┬─────────────────────────┘
                                              │  (mutates in place)
   D-04 INVARIANT: ───────────────────────────┤  caller MUST then call ↓
   "mutation is followed                      │
    by a storage write"                       ▼
                          ┌─────────────────────────────────────────────┐
   write callers:         │  InMemoryOrderStorage  (THE edited file)     │
   admission / bracket /  │                                              │
   lifecycle / reconcile /│  WRITE SEAM (5 methods)                      │
   portfolio_handler      │   add_order ──┐                              │
        │                 │   update_order├─► diff old→new via SHADOW    │
        ▼                 │   remove_order│   REGISTRY, patch buckets,    │
   add_order /            │   remove_orders_by_ticker                    │
   update_order /         │   clear_portfolio_orders                     │
   remove_*               │                                              │
                          │  ┌──────────────────────────────────────┐   │
                          │  │ SOURCE OF TRUTH (D-20, unchanged)     │   │
                          │  │   _by_id: {uuid: Order}               │   │
                          │  └──────────────────────────────────────┘   │
                          │  ┌──────────────────────────────────────┐   │
                          │  │ PRIVATE CACHES (new, D-02/D-03)       │   │
                          │  │   active_by_portfolio:                │   │
                          │  │     {pid: {oid: None}}                │   │
                          │  │   by_status: {status: {oid: None}}    │   │
                          │  │     (PENDING/PARTIALLY_FILLED only)   │   │
                          │  │   _last_indexed_status: {oid: status} │   │
                          │  └──────────────────────────────────────┘   │
                          │                                              │
   READ SEAM (queries):   │  HOT (index-backed, D-01/D-02/D-07):         │
        ▲                 │   get_active_orders ◄─ active_by_portfolio   │
        │                 │   get_pending_orders ◄─ active_by_portfolio  │
   reconcile.on_fill,     │   get_orders_by_status(active) ◄─ by_status  │
   lifecycle.expire_all,  │   remove_orders_by_ticker ◄─ active_by_pf    │
   order_manager facade   │   clear_portfolio_orders ◄─ active_by_pf     │
                          │                                              │
                          │  COLD (still scan _by_id, D-01/D-10):        │
                          │   get_orders_by_status(terminal),            │
                          │   get_orders_by_time_range, search_orders,   │
                          │   get_order_history, get_orders_by_ticker,   │
                          │   count_orders_by_status, get_order_by_id    │
                          └──────────────────────────────────────────────┘
```

### Recommended structure
No new files. Edit only:
```
itrader/order_handler/storage/in_memory_storage.py   # the indexes + maintenance + rerouted queries
tests/unit/order/test_order_storage.py               # the D-09 order-equivalence test + maintenance-matrix tests
```

### Pattern 1: Diff-on-write index maintenance via shadow registry (D-03)
**What:** Because the order mutates status **in place** and `update_order(order)` is called *after* the mutation, the stored object already shows the new status when the write seam runs. The storage cannot see the old status from the object — so it keeps `_last_indexed_status: {order_id: OrderStatus}` and diffs `old (registry) → new (order.status)`.

**When to use:** In every one of the five write methods.

**Example (shape, 4-space to match the file):**
```python
# Source: derived from D-03 + the existing add_order/update_order in in_memory_storage.py
def _index_apply(self, order: 'Order') -> None:
    """Reconcile both indexes + the shadow registry for one order (idempotent)."""
    oid = order.id
    pid = order.portfolio_id            # immutable per order (D-03)
    old_status = self._last_indexed_status.get(oid)
    new_status = order.status
    if old_status == new_status:
        return                          # PENDING→PENDING modify record: no bucket move
    # active_by_portfolio membership keyed on is_active, derived from status
    was_active = old_status in _ACTIVE_STATUSES   # old_status None => was absent
    is_active = new_status in _ACTIVE_STATUSES
    bucket = self._active_by_portfolio.setdefault(pid, {})
    if is_active and not was_active:
        bucket[oid] = None              # insertion-ordered append
    elif was_active and not is_active:
        bucket.pop(oid, None)
        if not bucket:
            del self._active_by_portfolio[pid]   # keep get_active_orders(None) clean
    # by_status: active-only (D-10) — drop on terminal
    if old_status in _ACTIVE_STATUSES:
        self._by_status[old_status].pop(oid, None)
    if new_status in _ACTIVE_STATUSES:
        self._by_status.setdefault(new_status, {})[oid] = None
    self._last_indexed_status[oid] = new_status
```

### Pattern 2: Index-backed query that preserves insertion order (D-06/D-08)
**What:** Read order ids out of the bucket (insertion-ordered) and materialize `Order` objects from `_by_id`.
```python
def get_active_orders(self, portfolio_id=None):
    if portfolio_id is not None:
        bucket = self._active_by_portfolio.get(portfolio_id, {})
        return [self._by_id[oid] for oid in bucket]
    # None => union across portfolios, preserving per-portfolio then insertion order
    return [self._by_id[oid]
            for bucket in self._active_by_portfolio.values()
            for oid in bucket]
```
> **CRITICAL ordering caveat (see Pitfall 1):** the `None` (all-portfolios) path above iterates *per-portfolio then within-portfolio*, which is **NOT** the same as today's single flat-dict scan order. This must be reconciled — see Pitfall 1 for the exact today-order and the fix.

### Anti-Patterns to Avoid
- **Plain `set` buckets:** hash-ordered → non-deterministic iteration → breaks the byte-exact oracle. Use `dict[oid, None]` (D-06/D-08).
- **A second source of truth:** the indexes are caches; never let a query read membership without `_by_id` being authoritative. D-20.
- **Rebuilding the index on every query:** that's just the scan with extra steps. Maintain incrementally on write.
- **A runtime "is the index consistent?" guard on the hot path:** burns the cycles this phase saves (D-04 explicitly rejects it).
- **Putting `ensure_index`/`rebuild` on the `OrderStorage` ABC:** leaks an in-memory caching concern onto a SQL backend that manages its own indexes (D-05 rejected).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Insertion-ordered membership set | A custom ordered-set class | `dict[key, None]` | CPython dict order is a language guarantee; a custom class is bug surface for zero gain. |
| "Active" predicate | A new status-set literal scattered per call site | `order.is_active` (already PENDING/PARTIALLY_FILLED) + one module-level `_ACTIVE_STATUSES = frozenset({PENDING, PARTIALLY_FILLED})` | The predicate already exists on the entity; the active index just caches membership. Define the status frozenset once to keep the index logic and `is_active` in lockstep. |
| Union of per-portfolio active sets for `get_active_orders(None)` | Re-scanning the flat dict when `portfolio_id is None` | Iterate `_active_by_portfolio` values | But mind the ordering caveat (Pitfall 1). |

**Key insight:** Nothing here warrants a library. The only real engineering is the **diff-on-write maintenance** and **preserving today's exact iteration order** — both are codebase-specific, not solvable by a dependency.

## D-04 Audit — Every Order-Status Mutation Site → Storage Write

> **This is the most important deliverable.** Index correctness depends on the invariant: *every `order.status` mutation is followed by a `storage.add_order`/`update_order`*. I traced all mutation sites.

**The single mutation primitive:** `self.status = new_status` occurs in exactly **one place** — `order.py:441`, inside `Order.add_state_change()` `[VERIFIED: grep \.status\s*= across itrader/]`. Every status change funnels through it. Its wrappers are `add_fill` (→FILLED), `cancel_order` (→CANCELLED), `reject_order` (→REJECTED), `expire_order` (→EXPIRED), and `modify_order` (same-status record). So the audit reduces to: *for every caller of those wrappers / of `add_state_change`, is a storage write called afterward on the same order?*

| # | Mutation site | Transition | Followed by storage write? | Verdict |
|---|---------------|-----------|----------------------------|---------|
| 1 | `reconcile_manager.py:144` `order.add_fill(...)` (EXECUTED arm `_apply_executed`) | PENDING/PARTIALLY_FILLED → FILLED | **Yes** — `update_order(order)` at `reconcile_manager.py:267` (`if applied:`) | ✅ SAFE |
| 2 | `reconcile_manager.py:159` `order.cancel_order(...)` (`_apply_cancelled`) | active → CANCELLED | **Yes** — `update_order(order)` at :267 (`applied` defaults True for non-EXECUTED arms) | ✅ SAFE |
| 3 | `reconcile_manager.py:164` `order.reject_order(...)` (`_apply_refused`) | active → REJECTED | **Yes** — `update_order(order)` at :267 | ✅ SAFE |
| 4 | `reconcile_manager.py:177` `order.expire_order(...)` (`_apply_expired`) | active → EXPIRED (or no-op if already EXPIRED) | **Yes** — `update_order(order)` at :267 | ✅ SAFE (no-op transition leaves status unchanged; index diff is a no-op) |
| 5 | `lifecycle_manager.py:110` `order.modify_order(...)` | same status (PENDING→PENDING modify record) | **Yes** — `update_order(order)` at :116 (`if success:`) | ✅ SAFE — same-status, no bucket move |
| 6 | `lifecycle_manager.py:176` `order.cancel_order(...)` | active → CANCELLED | **Yes** — `update_order(order)` at :179 (`if success:`) | ✅ SAFE |
| 7 | `lifecycle_manager.py:258` `order.expire_order(...)` (run-end sweep) | active → EXPIRED | **Yes** — `update_order(order)` at :260 | ✅ SAFE |
| 8 | `admission_manager.py:240` `primary.add_state_change(REJECTED, ...)` (validation reject) | **construction PENDING → REJECTED, then ADDED** | **Yes** — `add_order(primary)` at :245 (order is already REJECTED at add time) | ✅ SAFE — **EDGE CASE: add-of-already-terminal** (see Pitfall 2) |
| 9 | `admission_manager.py:293` `primary.add_state_change(REJECTED, ...)` (cash-reservation reject) | construction PENDING → REJECTED, then ADDED | **Yes** — `add_order(primary)` at :298 | ✅ SAFE — same add-of-already-terminal edge case |
| 10 | `admission_manager.py:918` `rejected.add_state_change(REJECTED, ...)` (unsized/gate reject) | construction PENDING → REJECTED, then ADDED | **Yes** — `add_order(rejected)` at :923 | ✅ SAFE — same edge case |
| 11 | `order.py:227/273/335/381` `order.add_state_change(PENDING, ...)` (factory initial state) | None → PENDING (initial record) | **Yes** — the factory-built order is then `add_order`'d by bracket/admission/portfolio_handler | ✅ SAFE — order is PENDING (active) at add time |
| 12 | `portfolio_handler.py:524` `order.add_state_change(PENDING, ..., allow_same_status=True)` (forced-liquidation record) | PENDING → PENDING (same-status record) | **Yes** — `add_order(order)` at :532 | ✅ SAFE — **EDGE CASE: same-status record before add** (see Pitfall 3) |

**Audit conclusion: NO staleness bug exists.** Every mutation site is paired with a storage write on the same object. There is **no mutation path that bypasses the storage write seam.** The plan does not need to fix any caller — it only needs to make the five write methods maintain the indexes, and handle the two edge cases (Pitfalls 2 & 3) inside the maintenance logic.

**Two structural facts that make this airtight (lock these in the plan as the written D-04 invariant):**
1. `self.status = new_status` exists in exactly one place (`add_state_change`, order.py:441). There is no other way to change status.
2. `add_state_change` *cannot* transition out of a terminal status — `VALID_ORDER_TRANSITIONS[FILLED/CANCELLED/REJECTED/EXPIRED] == []` (`core/enums/order.py:85-88`). So a terminal order is frozen; an index entry dropped on terminal transition can never need re-adding. This is what makes `by_status` active-only (D-10) sound.

## Maintenance Matrix — How Each Write Method Touches the Indexes

> `_ACTIVE = {PENDING, PARTIALLY_FILLED}`. "registry" = `_last_indexed_status`.

| Method | What it does to `_by_id` | `active_by_portfolio` | `by_status` (active-only) | registry | Edge cases |
|--------|--------------------------|------------------------|---------------------------|----------|------------|
| `add_order(order)` | `_by_id[id] = order` | If `order.status ∈ _ACTIVE`: append `id` to `bucket[pid]`. **If terminal (REJECTED): do nothing** (never enters active). | If `∈ _ACTIVE`: append to `by_status[status]`. If terminal: nothing. | set `registry[id] = order.status` | **Add-of-already-terminal** (#8-10): order is REJECTED at add → index untouched, registry records REJECTED. **Re-add same id** (test `test_update_order` re-adds): treat as overwrite — diff old registry→new. |
| `update_order(order)` | `if id in _by_id: _by_id[id]=order` | diff `registry[id]` → `order.status`: add/remove from `bucket[pid]` on active-boundary crossing. | drop from `by_status[old]` if old active; add to `by_status[new]` if new active. | refresh to `order.status` | Same-status (modify record / EXPIRED no-op): old==new → no-op. Order not in `_by_id` (returns False): **do not touch indexes**. |
| `remove_order(id, pid?)` | `del _by_id[id]` | `bucket[pid].pop(id, None)`; del empty bucket | `by_status[s].pop(id, None)` for the registered status if active | `registry.pop(id, None)` | Non-UUID id / not found / pid mismatch → returns False, **no index change**. |
| `remove_orders_by_ticker(ticker, pid)` | `del` each matched id | **Source the candidate ids from `active_by_portfolio[pid]`** (D-07), filter `order.ticker==ticker`; pop each from bucket | pop each from its `by_status` bucket | pop each from registry | Only active orders are removed today (the method filters `is_active`) — sourcing from the active index is exactly equivalent. |
| `clear_portfolio_orders(pid)` | `del` each active id | **Source from `active_by_portfolio[pid]`** (D-07); clear/del the bucket | pop each from `by_status` | pop each from registry | Terminal orders stay in `_by_id` (history) — correct, they were never in the active index. |

**Query rerouting (read side):**
| Query | Today | After (D-01/D-02/D-07) |
|-------|-------|------------------------|
| `get_active_orders(pid)` | scan `_orders(pid)` filter `is_active` | `[_by_id[oid] for oid in active_by_portfolio.get(pid, {})]` |
| `get_active_orders(None)` | scan all filter `is_active` | union over `active_by_portfolio.values()` — **see Pitfall 1 for order** |
| `get_pending_orders(pid)` | scan filter `is_active`, build `{pid:{id:order}}` | build the nested dict from `active_by_portfolio` |
| `get_orders_by_status(s, pid)` where `s ∈ _ACTIVE` | scan filter `status==s` | from `by_status[s]`, filter `portfolio_id==pid` if pid given |
| `get_orders_by_status(s, pid)` where `s` terminal | scan filter `status==s` | **keep scanning `_by_id`** (D-10) |
| `remove_orders_by_ticker`, `clear_portfolio_orders` | scan | source from `active_by_portfolio` (D-07) |
| `get_orders_by_time_range`, `search_orders`, `get_order_history`, `get_orders_by_ticker`, `count_orders_by_status`, `get_order_by_id` | scan / O(1) | **unchanged — keep scanning / O(1)** (D-01) |

## Insertion-Order Semantics (D-06/D-08/D-09 — byte-identical lock)

**Today's exact order:** every active query iterates `self._by_id.values()` (insertion order = `add_order` call order) and filters. So:
- `get_active_orders(pid)` returns active orders **in the order they were `add_order`'d**, filtered to that portfolio.
- `get_active_orders(None)` returns **all** active orders in global `add_order` order (interleaved across portfolios).
- `get_orders_by_status(s)` returns matching orders in global `add_order` order.
- `get_pending_orders(None)` builds `result.setdefault(pid, {})[id] = order` while scanning in `add_order` order → first-seen portfolio ordering, within-portfolio `add_order` order.

**The index preserves this for the per-portfolio path trivially** (a bucket is appended to in `add_order`/transition order, which for an order entering active = its `add_order` order; an order can only become active at add time since terminal→active is impossible — see D-04 fact #2). **The all-portfolios (`None`) path is the trap** — see Pitfall 1. The D-09 test must assert equivalence on **both** the per-portfolio and `None` paths, against a captured pre-refactor scan order.

## Common Pitfalls

### Pitfall 1: `get_active_orders(None)` / `get_orders_by_status(s)` global-order divergence
**What goes wrong:** Today the all-portfolios path yields orders in **global `add_order` insertion order** (one flat-dict scan, portfolios interleaved). A naive index union (`for bucket in active_by_portfolio.values(): for oid in bucket`) yields **grouped-by-portfolio** order — same set, different sequence. This silently changes query output order and can break the byte-exact oracle / D-09 test if any consumer depends on it.
**Why it happens:** the index is partitioned by portfolio; the scan is not.
**How to avoid:** Either (a) for the `None` path, fall back to a single `_by_id` scan filtered by membership in the active index (still O(active) materialization but global order — simplest correctness), or (b) keep a global insertion-ordered active set in addition. **Recommended: option (a)** — the hot caller is always `get_active_orders(pid)` with a concrete portfolio (reconcile passes `fill_event.portfolio_id`, lifecycle iterates per `portfolio_id`); the `None` path has no hot caller, so a scan there is acceptable and guarantees byte-identical order. Verify against the actual consumers below.
**Warning signs:** D-09 test fails only on the `None`/global path; oracle trade order shifts.

> **Consumer check (verified):** `reconcile_manager.py:319` calls `get_active_orders(fill_event.portfolio_id)` (concrete pid). `lifecycle_manager.py:253` calls `get_active_orders(portfolio_id)` inside a per-portfolio loop (concrete pid). `order_manager.get_active_orders` (facade) passes through whatever the caller gives. **No production hot caller passes `None`** — so the `None`-path scan-fallback costs nothing on the measured path.

### Pitfall 2: Add-of-already-terminal (REJECTED orders persisted by admission)
**What goes wrong:** `admission_manager.py:245/298/923` call `add_order(primary)` *after* transitioning the order to REJECTED (audit trail — rejected orders must persist, test `test_add_rejected_order_persists_without_entering_active_book`). If `add_order` blindly appends to the active index assuming "new order = PENDING", a REJECTED order wrongly enters the active book.
**Why it happens:** the "new order is active" assumption is false for the reject-then-add path.
**How to avoid:** `add_order` must read `order.status` and only index if active. The Maintenance Matrix above does this. The existing test at `test_order_storage.py:252` already asserts a REJECTED-added order is absent from `get_active_orders`/`get_pending_orders` and present in `get_orders_by_status(REJECTED)` — **this test is your guard; it must stay green.**
**Warning signs:** `test_add_rejected_order_persists_without_entering_active_book` fails.

### Pitfall 3: Same-status `add_state_change` before add (forced liquidation)
**What goes wrong:** `portfolio_handler.py:524` records a `PENDING→PENDING` state change (`allow_same_status=True`) then `add_order`s. The order is PENDING (active) at add — fine — but the maintenance logic's `old==new` short-circuit must not mistakenly skip indexing a *brand-new* order whose registry entry doesn't exist yet.
**Why it happens:** the registry has no entry for a new id, so `old_status` is `None`; `None != PENDING` correctly triggers the add. Only a bug where you initialize the registry before diffing would break this.
**How to avoid:** In `add_order`, diff against `registry.get(id)` (returns `None` for new ids) so a first add always indexes; never pre-seed the registry.
**Warning signs:** new PENDING orders missing from `get_active_orders`.

### Pitfall 4: Re-`add_order` of an existing id (overwrite)
**What goes wrong:** `test_update_order` and general usage may call `add_order` on an id already present. Today it overwrites `_by_id[id]`. The index must reconcile, not double-append (a `dict[oid,None]` append is idempotent, but the registry diff must run so a status change carried by the overwrite is reflected).
**How to avoid:** Route `add_order` through the same diff-on-write logic as `update_order` (diff registry→order.status). Idempotent by construction.

### Pitfall 5: `remove_order` must drop from the registry too
**What goes wrong:** removing an order from `_by_id` but leaving its `_last_indexed_status` entry leaks memory and, worse, a later id reuse (won't happen with UUIDv7, but defensively) would diff against a stale status.
**How to avoid:** every remove pops the registry entry. (UUIDv7 ids are unique so reuse is impossible, but registry growth without cleanup defeats the active-only memory posture — D-11.)

### Pitfall 6: Indentation — 4 spaces in `in_memory_storage.py`
**What goes wrong:** most `order_handler/` modules are tabs; a tab-indented edit in this 4-space file produces a `TabError` or a mixed-indent file.
**How to avoid:** `in_memory_storage.py` and `tests/unit/order/test_order_storage.py` are **4-space**. Confirmed by reading both files. Match them. `[VERIFIED: read of in_memory_storage.py lines 34-184]`

## D-05a Seam Audit — Is Each `OrderStorage` ABC Method SQL-Expressible?

> Confirms no in-memory-only assumption leaks into the contract, satisfying success-criterion #3. **No Postgres code written.**

| ABC method | Return / shape | SQL-expressible? | Note for future PostgreSQLOrderStorage |
|------------|----------------|------------------|----------------------------------------|
| `add_order(order)` | `None` | ✅ | `INSERT`. |
| `remove_order(id, pid?)` → `bool` | bool found+removed | ✅ | `DELETE ... RETURNING`; bool = rowcount>0. Note the **`isinstance(order_id, uuid.UUID)` guard** is an in-memory keying detail (D-14) — SQL would parameter-bind; not a leak, just don't replicate the guard literally. |
| `remove_orders_by_ticker(ticker, pid)` → `int` | count | ✅ | `DELETE WHERE ticker=? AND portfolio_id=? AND status IN (active)`; today filters `is_active` — encode the active-status set in the WHERE. |
| `get_pending_orders(pid?)` → `Dict[Any, Dict[Any, Order]]` | **nested `{pid: {oid: order}}`** | ✅ but ⚠️ | The nested-dict *shape* is a return-shape convenience built in Python. A SQL backend would `SELECT ... WHERE status IN (active)` and **build the same nesting in Python from the rows**. The shape is fine; the ordering guarantee (insertion order) maps to an explicit `ORDER BY created_at, id` in SQL. **Document: ordering is contractual.** |
| `get_order_by_id(id, pid?)` → `Optional[Order]` | one or None | ✅ | `SELECT ... WHERE id=? [AND portfolio_id=?]`. |
| `update_order(order)` → `bool` | bool found+updated | ✅ | `UPDATE ... RETURNING`; bool = rowcount>0. |
| `get_orders_by_ticker(ticker, pid?)` → `List[Order]` | list | ✅ | `WHERE ticker=?`, `ORDER BY` insertion. |
| `clear_portfolio_orders(pid)` → `int` | count | ✅ | `DELETE WHERE portfolio_id=? AND status IN (active)`. |
| `get_orders_by_status(status, pid?)` → `List[Order]` | list | ✅ | `WHERE status=?`. (In-memory splits active vs terminal for caching — SQL does not need to; one `WHERE status=?` covers both. No leak.) |
| `get_active_orders(pid?)` → `List[Order]` | list | ✅ | `WHERE status IN ('PENDING','PARTIALLY_FILLED')`, `ORDER BY` insertion. |
| `get_orders_by_time_range(start, end, pid?)` → `List[Order]` | list | ✅ | `WHERE created_at BETWEEN ? AND ?`. |
| `get_order_history(id)` → `List[Dict]` | state-change dicts | ✅ but ⚠️ | Reads `order.state_changes`. A SQL backend needs a **child table** (order_state_changes) or a JSON column. **Document: state-change history is a per-order collection — the schema must persist it.** Not a leak in the *interface* (return type is plain dicts), but a schema note. |
| `search_orders(criteria, pid?)` → `List[Order]` | list | ✅ but ⚠️ | Uses `getattr(order, key)` reflection over arbitrary criteria. SQL needs a whitelisted column map, not arbitrary attribute access. **Document: criteria keys must map to real columns.** Interface is fine (dict in, list out). |
| `count_orders_by_status(pid?)` → `Dict[str, int]` | name→count | ✅ | `SELECT status, COUNT(*) GROUP BY status`. |

**Conclusion:** every method is SQL-expressible. The only things to **document** for PERSIST-01 (no code now): (1) insertion-order is a *contractual* ordering guarantee → SQL needs explicit `ORDER BY created_at, id`; (2) `get_order_history` implies a state-change child table/JSON column; (3) `search_orders` reflection needs a column whitelist; (4) the `isinstance(uuid.UUID)` guard in `remove_order`/`get_order_by_id` is an in-memory keying detail, not a contract. **No in-memory-only assumption leaks into the ABC method signatures** — D-05 holds.

## Validation Architecture

> nyquist_validation: `.planning/config.json` not checked for an explicit `false`; treating as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (Poetry) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, strict markers/config) |
| Quick run command | `poetry run pytest tests/unit/order/test_order_storage.py -v` |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-01 | Index-backed query order == prior full-scan order (D-09) | unit | `poetry run pytest tests/unit/order/test_order_storage.py -k equivalence -x` | ❌ Wave 0 (new test) |
| PERF-01 | REJECTED add stays out of active book (Pitfall 2 guard) | unit | `poetry run pytest tests/unit/order/test_order_storage.py -k rejected -x` | ✅ exists (`test_add_rejected_order_persists_without_entering_active_book`) |
| PERF-01 | FILLED order leaves active queries (terminal drop, D-10) | unit | `poetry run pytest tests/unit/order/test_order_storage.py -k "filled_order_leaves" -x` | ✅ exists |
| PERF-01 | Maintenance matrix: remove/clear/by_ticker keep indexes consistent | unit | `poetry run pytest tests/unit/order/test_order_storage.py -x` | ⚠️ partial — extend |
| PERF-01 (gate a) | Byte-exact oracle (134 / 46189.87730727451) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | ✅ exists |
| PERF-01 (gate a) | Determinism double-run byte-identical | e2e | `poetry run pytest tests/e2e/robust/test_determinism.py -v` | ✅ exists |
| PERF-01 (gate b) | ≥5% wall-clock improvement vs frozen baseline | manual/perf | `make perf-w1` | ✅ harness exists |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/order/test_order_storage.py -x` (use `poetry run pytest`, not `make test`, in worktrees — `make test` aborts on missing `.env`)
- **Per wave merge:** `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e/robust/test_determinism.py tests/unit/order -x`
- **Phase gate:** `make test` green (in main checkout) + `make perf-w1` ≥5% + oracle green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/order/test_order_storage.py` — add the **D-09 order-equivalence test**: snapshot pre-refactor scan order (or build an oracle list by scanning `_by_id` independently) and assert `get_active_orders` / `get_pending_orders` / `get_orders_by_status(active)` match it on both the per-portfolio AND `None` paths.
- [ ] `tests/unit/order/test_order_storage.py` — add maintenance-matrix coverage: transition PENDING→FILLED via `update_order` drops from active index AND `by_status`; `remove_orders_by_ticker` / `clear_portfolio_orders` clean both indexes + registry; re-`add_order` of an existing id is idempotent.
- [ ] No framework install needed (pytest present).

## Gate (b) — How to Measure & Re-Freeze

`[VERIFIED: read of Makefile + perf/runners/run_w1_benchmark.py + perf/results/W1-BASELINE.json]`

- **Frozen baseline (current locked reference):** `perf/results/W1-BASELINE.json` — `wall_clock_s: 247.5`, `peak_mem_mb: 167.3`, window `2026-04-23`→`2026-06-23`, oracle `46189.87730727451` / 134 trades. **This is the number this phase must beat by ≥5%** (≤ ~235.1 s).
  > Note: `W1-BASELINE.json` records **247.5 s**; `PERF-BASELINE-RESULTS.md §1` cites **240.8 s** (the spike-era clean run). The JSON is the Phase-1 re-frozen authority for the guard — measure against **247.5 s**.
- **Measure + check the gate:** `make perf-w1` → runs `python -m perf.runners.run_w1_benchmark --check` → single timed run (D-03), prints `Δ` vs baseline, **fails (exit 1) only on a wall-clock SLOWDOWN >+5%** (`_check_regression`, band_pct=5.0, run_w1_benchmark.py:189-221). **Important:** the soft guard only catches *regressions*; it does **not** assert the ≥5% *improvement*. The improvement is the human gate — read the printed `Δ` and confirm it is ≤ −5%.
- **Re-freeze after the phase:** `make perf-baseline` → `python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json` → overwrites the committed baseline with the new (faster) run. Commit it as the new locked reference for Phase 3. Do **not** combine `--baseline-out` with `--check` (self-comparison warning, run_w1_benchmark.py:239-242).
- Default window is pinned (D-07 Phase 1) — no env vars needed. `W1_START_DATE`/`W1_END_DATE` overrides still work for ad-hoc slices.
- **Memory:** peak mem is reported in the same run (tracemalloc), watched per D-11, never fails the gate.

## Gate (a) — Correctness Lock

- **Byte-exact oracle:** `poetry run pytest tests/integration/test_backtest_oracle.py -v` — asserts 134 trades / `final_equity 46189.87730727451` (and `final_cash`/`total_realised_pnl`) with **no float tolerance** (`test_oracle_numeric_values`, `_SUMMARY_NUMERIC_KEYS`). Must stay green.
- **Determinism double-run:** `poetry run pytest tests/e2e/robust/test_determinism.py -v` — the dedicated suite-level byte-identical double-run check. (Other targeted double-run tests exist, e.g. `tests/integration/test_pair_flagship_snapshot.py::test_pair_flagship_determinism_double_run`, `tests/unit/portfolio/test_carry.py::...double_run_identical`.)
- **mypy:** `make typecheck` (`mypy --strict` over `itrader`) — `in_memory_storage.py` is in strict scope. Must be clean.

## mypy --strict Typing Notes

`in_memory_storage.py` is **NOT** in the `[[tool.mypy.overrides]] ignore_errors` list (`pyproject.toml`: only `postgresql_storage` and `sql_handler` are deferred) — so it is **fully strict**. `[VERIFIED: read of pyproject.toml mypy section]`

Type the new state precisely:
```python
import uuid
from typing import Dict, Optional
# ...
self._active_by_portfolio: Dict[uuid.UUID, Dict[uuid.UUID, None]] = {}
self._by_status: Dict['OrderStatus', Dict[uuid.UUID, None]] = {}
self._last_indexed_status: Dict[uuid.UUID, 'OrderStatus'] = {}
_ACTIVE_STATUSES: frozenset['OrderStatus'] = ...   # module-level, after the enum import
```
Notes:
- `OrderStatus` is under `TYPE_CHECKING` in this file today (line 8). The shadow registry needs `OrderStatus` at **runtime** (as a dict key and for the `_ACTIVE_STATUSES` frozenset) — move it to a real runtime import (`from ...core.enums import OrderStatus`) or import locally. A `TYPE_CHECKING`-only import will `NameError` at runtime.
- `portfolio_id` arrives typed as `PortfolioId` on `Order` (a UUIDv7-backed type), but the ABC's `IdLike = Union[str, int, uuid.UUID]` and the test fixtures use raw `uuid.uuid4()`. Key the index dicts on the **runtime value** of `order.portfolio_id` — keep the annotation `uuid.UUID` (or widen to `IdLike` if mypy complains about the facade passing `IdLike`). Confirm `get_active_orders`/`get_orders_by_status` query params keep the existing `Optional[IdLike]` signature (D-05 — no signature change).
- The `dict[..., None]` value type: mypy is happy with `Dict[uuid.UUID, None]`; assign `bucket[oid] = None`.
- Keep `from __future__` absent (file uses string-literal forward refs already, e.g. `'Order'`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Nested per-portfolio dicts (active/all/archived classes) | Flat `{id: order}` + predicate-filter queries (D-20/PERF3/M4-06) | v1.x consolidation | The flat dict is now the sole container; this phase re-adds **derived caches** over it (not the old dual-write nested dicts — caches that never become a second source of truth). |

**Not deprecated, deliberately retained:** the flat-dict source of truth (D-20). The indexes do not replace it.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `get_active_orders(None)` has no production hot caller, so a scan-fallback there costs nothing on the measured path. | Pitfall 1 | LOW — verified reconcile/lifecycle pass concrete pids; only risk is a future or test caller passing `None` (correctness preserved either way, only perf). |
| A2 | The ≥5% improvement is confirmed by reading the printed `Δ`, not by the soft guard (which only catches regressions). | Gate (b) | LOW — confirmed by reading `_check_regression`; the planner must make the human-read of `Δ` an explicit gate step. |
| A3 | `tests/e2e/robust/test_determinism.py` is the canonical suite-level determinism double-run. | Gate (a) | LOW — file exists and greps for "determin"; planner should open it to confirm it covers the W1/oracle topology (it may be a smaller scenario). The oracle test itself is the harder lock. |

**Note:** All structural claims (mutation sites, write pairings, indentation, mypy scope, transition table, baseline numbers, CLI flags) are `[VERIFIED]` against the codebase this session. The three items above are the only judgement calls.

## Open Questions

1. **Does any test or external/API caller invoke `get_active_orders(None)` or `get_orders_by_status` on the global path where order matters?**
   - What we know: no *production hot* caller passes `None` (reconcile/lifecycle use concrete pids).
   - What's unclear: unit tests / reporting may. The D-09 test must cover the `None` path regardless.
   - Recommendation: implement the `None` path as a `_by_id`-scan-by-membership (Pitfall 1 option a) to guarantee global insertion order, sidestepping the question entirely.

2. **Should `add_order` and `update_order` share one private `_index_apply(order)` helper?**
   - What we know: both do the same diff-on-write; sharing avoids divergence (Pitfall 4).
   - Recommendation: yes — one `_index_apply` called by both, plus `_index_remove(order_id, order)` for the delete paths. Planner's discretion (within D-03).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Poetry / `.venv` | all tests + perf runner | ✓ (assumed — project standard) | 3.13 | — |
| `make perf-w1` harness | gate (b) | ✓ | — | `poetry run python -m perf.runners.run_w1_benchmark --check` |
| `perf/results/W1-BASELINE.json` | gate (b) baseline | ✓ (committed, 247.5 s) | schema v1 | — |
| PostgreSQL | NOT required this phase | n/a | — | n/a (no Postgres code) |

**Missing dependencies with no fallback:** none.
**Worktree note (from project memory):** `make test` aborts in worktrees on missing `.env`; use `poetry run pytest tests` in the worktree and re-run `make test` / `make perf-w1` in the main checkout. Also prepend `PYTHONPATH="$PWD"` if the editable `.venv` install shadows worktree edits.

## Security Domain

> Not applicable. This is an internal in-memory data-structure refactor with no external input, no auth, no network, no crypto, no persistence boundary added this phase. ASVS categories V2–V6 do not apply. No `security_enforcement` surface is introduced.

## Sources

### Primary (HIGH confidence)
- Codebase (read this session): `itrader/order_handler/storage/in_memory_storage.py`, `base.py`, `order.py`, `reconcile/reconcile_manager.py`, `lifecycle/lifecycle_manager.py`, `admission/admission_manager.py`, `brackets/bracket_manager.py`, `order_manager.py`, `portfolio_handler/portfolio_handler.py`, `core/enums/order.py`, `tests/unit/order/test_order_storage.py`, `tests/integration/test_backtest_oracle.py`, `pyproject.toml`, `Makefile`, `perf/runners/run_w1_benchmark.py`, `perf/results/W1-BASELINE.json`.
- `perf/results/PERF-BASELINE-RESULTS.md` §1/§2 — frozen baseline + hotspot #1.
- `.planning/phases/02-order-storage-indexing/02-CONTEXT.md` — D-01…D-11.
- `.planning/phases/01-perf-tooling-baseline/01-CONTEXT.md` — D-04 gate-(b) definition.
- Grep audits: `\.status\s*=` (one site), `add_state_change`/wrappers callers, `update_order`/`add_order`/`remove_*` callers, query callers.

### Secondary (MEDIUM confidence)
- None — no external sources needed (no new library; stdlib `dict` ordering is a language guarantee).

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- D-04 audit (mutation→write pairings): HIGH — exhaustive grep + read of every site; single mutation primitive makes it provably complete.
- Maintenance matrix / index design: HIGH — derived directly from the read code + D-02/D-03/D-06/D-08/D-10.
- Insertion-order equivalence: HIGH on the per-portfolio path, MEDIUM on the `None`/global path (Pitfall 1 — recommended scan-fallback resolves it).
- Gate (b) commands + baseline: HIGH — read Makefile + runner + JSON.
- D-05a seam audit: HIGH — read every ABC method.
- mypy/typing: HIGH — confirmed `in_memory_storage` is in strict scope.

**Research date:** 2026-06-23
**Valid until:** stable (internal refactor, no fast-moving externals) — re-verify line numbers before editing (they drift).
