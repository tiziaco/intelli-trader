---
phase: 02-order-storage-indexing
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - itrader/order_handler/storage/in_memory_storage.py
  - tests/unit/order/test_order_storage.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the new secondary-index machinery in `InMemoryOrderStorage`
(`_active_by_portfolio`, active-only `_by_status`, and the `_last_indexed_status`
shadow registry) plus its test suite. The primary risk class for this phase was
cache-coherency / stale-index drift (T-02-01). I traced all five write seams,
confirmed each `_by_id` mutation is paired with an `_index_apply`/`_index_remove`
call (no bypass), verified `_index_remove` cannot leak a `_by_status` or registry
entry, and confirmed the per-portfolio and `None` active-query paths return
add-order-consistent sequences. I also dynamically reproduced the candidate
ordering bug.

Coherency is sound: there is no path where a `_by_id` entry exists without the
indexes being reconciled, and no KeyError risk in the query comprehensions
(`_by_id[oid]` is always populated for any `oid` present in an index). I found **no
BLOCKER**.

However, the phase's documented byte-equivalence contract (D-09: "index-backed
query order == prior full-scan order") is **violated for `get_orders_by_status`
on the `PARTIALLY_FILLED` status** — the index orders by status-transition order,
not by `_by_id` add order. This is masked by a test gap (the equivalence test only
exercises PENDING and a terminal transition, never PARTIALLY_FILLED). Two further
WARNING/INFO items concern an inaccurate memory-posture docstring and a
type-coherence assumption at the portfolio-keyed index lookups.

`in_memory_storage.py`/`test_order_storage.py` 4-space indentation is by design and
is not flagged. Money handling is unchanged in this diff.

## Warnings

### WR-01: `get_orders_by_status` reorders active-status results, breaking the D-09 byte-equivalence contract

**File:** `itrader/order_handler/storage/in_memory_storage.py:248-253`
**Issue:**
The active-status branch returns orders in `_by_status[status]` insertion order,
which is **status-transition order**, not the prior flat-scan's `_by_id`
**add order**. For `PENDING` this is harmless (every order enters `_by_status[PENDING]`
at `add_order`, so transition order == add order). But for `PARTIALLY_FILLED`,
an order is *popped* from `_by_status[PENDING]` and *appended* to
`_by_status[PARTIALLY_FILLED]` at transition time (lines 97-100), so the bucket
sequence is the order in which orders crossed into `PARTIALLY_FILLED` — which can
differ from add order.

The class docstrings and D-09 assert index output is byte-equal to the prior
`_orders()` flat scan. I reproduced the divergence dynamically: with orders A then
B added, B transitioned to `PARTIALLY_FILLED` before A, `get_orders_by_status(PARTIALLY_FILLED)`
returns `[B, A]` while the prior flat scan (and the test oracle) returns `[A, B]`.

This is not a coherency/correctness bug for membership (the right *set* is returned),
and no current internal caller depends on the order of `get_orders_by_status(PARTIALLY_FILLED)`
— so it is a WARNING, not a BLOCKER. But it silently contradicts a load-bearing
documented invariant and will surface the moment a caller (or a future golden-master
assertion) relies on it.

**Fix:** Either (a) re-sort the active-status branch to match `_by_id` order, or
(b) narrow the documented contract. Option (a):
```python
if status in _ACTIVE_STATUSES:
    bucket = self._by_status.get(status, {})
    # Restore prior flat-scan (add) order: _by_id is insertion-ordered.
    return [
        order for order in self._orders(portfolio_id)
        if order.id in bucket and order.status == status
    ]
```
If the O(all-orders) scan is unacceptable for this path, instead sort the bucket
ids by a stable add-order key. Whichever is chosen, also extend the equivalence
test (see WR-03).

### WR-02: `_active_by_portfolio` / `_by_status` lookups assume `portfolio_id` is the same hashable type as the stored key, diverging from the flat-scan `==` comparison

**File:** `itrader/order_handler/storage/in_memory_storage.py:161, 179, 222, 248-253, 266`
**Issue:**
The portfolio-keyed index paths resolve via `self._active_by_portfolio.get(portfolio_id, {})`
and `self._by_status.get(status, {})`, which is a **hash/`__eq__` dict lookup** keyed
on the native `uuid.UUID` (`order.portfolio_id`). The prior flat scan that these
paths replaced (and the retained terminal fallback at line 254, and
`get_orders_by_status`'s portfolio filter at line 252) compares with
`order.portfolio_id == portfolio_id`.

For native-UUID callers these agree. But `IdLike = str | int | uuid.UUID` per the
ABC, and the four index lookups carry a `# type: ignore[arg-type]` precisely because
`portfolio_id` is typed `IdLike`, not `uuid.UUID`. If any caller ever passes a
legacy `str`/`int` portfolio id (which the ABC signatures still permit), the index
path silently returns `{}` (empty) while the retained scan paths would still match
via `==` if `UUID.__eq__` accepted it — producing an inconsistent result *between
methods on the same storage*. Production callers go through `OrderManager`, which
types these as `PortfolioId` (UUID), so this is latent, not active — hence WARNING.

**Fix:** Make the type contract explicit so the divergence cannot arise. Either
tighten the public signatures to `PortfolioId`/`uuid.UUID` (drop `IdLike` for
portfolio params, mirroring `remove_order`'s `isinstance(order_id, uuid.UUID)`
guard), or normalize at entry. Minimal guard, mirroring the existing order-id guard:
```python
if portfolio_id is not None and not isinstance(portfolio_id, uuid.UUID):
    # non-UUID portfolio id can never key the index — match the scan's empty result
    return []   # or {} for get_pending_orders
```

### WR-03: Equivalence regression test never exercises `PARTIALLY_FILLED`, masking WR-01

**File:** `tests/unit/order/test_order_storage.py:310-353`
**Issue:**
`test_active_queries_match_full_scan_equivalence` is the D-09 oracle gate, but it
only transitions an order to **FILLED** (terminal) and asserts equivalence for the
**PENDING** active status. The one active status whose index order can diverge from
add order — `PARTIALLY_FILLED` — is never reached (the test seeds only PENDING and
FILLED). As a result the suite is fully green (26/26) while WR-01's reordering goes
undetected. The test gives false confidence that the index is byte-equal for *all*
active statuses.

**Fix:** Add a case that drives an order into `PARTIALLY_FILLED` out of add order
(via `add_state_change(OrderStatus.PARTIALLY_FILLED, ...)`, since the full-quantity
`add_fill` contract cannot produce it) and assert
`get_orders_by_status(OrderStatus.PARTIALLY_FILLED)` equals the `_by_id`-scan oracle:
```python
# B added after A, but B reaches PARTIALLY_FILLED first
store.order2.add_state_change(OrderStatus.PARTIALLY_FILLED, "pf", OrderTriggerSource.EXCHANGE)
s.update_order(store.order2)
store.order1.add_state_change(OrderStatus.PARTIALLY_FILLED, "pf", OrderTriggerSource.EXCHANGE)
s.update_order(store.order1)
oracle_pf = [o for o in s._by_id.values() if o.status == OrderStatus.PARTIALLY_FILLED]
assert ([o.id for o in s.get_orders_by_status(OrderStatus.PARTIALLY_FILLED)]
        == [o.id for o in oracle_pf])   # currently FAILS -> confirms WR-01
```

## Info

### IN-01: Shadow-registry docstrings overstate the "active-only memory posture"

**File:** `itrader/order_handler/storage/in_memory_storage.py:103-108, 64`
**Issue:**
`_index_apply` (line 101) writes `_last_indexed_status[oid] = new_status`
**unconditionally**, including for terminal statuses (REJECTED-at-add, and any
order that transitions to a terminal state but stays in `_by_id` as history,
T-05-02). Since terminal orders are intentionally never removed from `_by_id`,
their registry entries persist for the life of the run. The `_index_remove`
docstring ("the active-only memory posture, D-11, is preserved") and the
`_by_status` "active-only" framing therefore do not apply to the registry: I
confirmed dynamically that adding three REJECTED-at-add orders leaves
`_by_status` and `_active_by_portfolio` empty but `_last_indexed_status` holding 3
entries. This is **not a correctness defect** (the registry is bounded by `_by_id`
membership, same as the source of truth, and memory/perf is out of v1 scope) — but
the docstring will mislead a future maintainer reasoning about the memory contract
or a Postgres port. Recommend clarifying that only `_by_status` is active-only;
the registry mirrors `_by_id` membership.

### IN-02: `_orders()` helper bypassed by several methods, leaving two parallel iteration idioms

**File:** `itrader/order_handler/storage/in_memory_storage.py:186-188, 251-253, 268`
**Issue:**
`_orders(portfolio_id)` centralizes the "iterate flat dict, filter by portfolio"
predicate, but `get_pending_orders` (None path), `get_active_orders` (None path),
and `get_orders_by_status` (active path) each re-inline a bare
`self._by_id.values()` loop with their own portfolio filter rather than reusing it.
This is justified where the active-membership filter differs from the helper, but it
means the portfolio-equality predicate now lives in five places; a future change to
how portfolio matching works (see WR-02) must touch all of them. Minor maintainability
note — consider routing the scan-based paths through `_orders()` where the only extra
filter is active-membership.

---

_Reviewed: 2026-06-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
