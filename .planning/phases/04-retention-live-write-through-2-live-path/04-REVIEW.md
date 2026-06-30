---
phase: 04-retention-live-write-through-2-live-path
reviewed: 2026-06-30T10:28:59Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - itrader/order_handler/storage/cached_sql_storage.py
  - itrader/order_handler/storage/storage_factory.py
  - itrader/portfolio_handler/storage/cached_sql_storage.py
  - itrader/portfolio_handler/storage/models.py
  - itrader/portfolio_handler/storage/storage_factory.py
  - itrader/storage/migrations/versions/47f2b41f3ffe_portfolio_account_state.py
  - itrader/strategy_handler/storage/cached_sql_storage.py
  - itrader/strategy_handler/storage/storage_factory.py
  - tests/integration/storage/test_cached_sql_order_storage.py
  - tests/integration/storage/test_cached_sql_portfolio_storage.py
  - tests/integration/storage/test_cached_sql_signal_storage.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/storage/test_import_quarantine.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: resolved
resolved: 2026-06-30T11:00:00Z
resolution: "All 4 findings fixed in commit 5a824da; mypy --strict clean, full suite 1459 passed under filterwarnings=[error], oracle byte-exact."
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-30T10:28:59Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** resolved (all 4 findings fixed in commit `5a824da`)

## Resolution (2026-06-30)

- **CR-01 (fixed):** `CachedSqlOrderStorage.add_order` now evicts a *childless* terminal order at add time (the audited REJECTED admission path persists via `add_order`), restoring the purge-on-terminalize / flat-RSS invariant. Gate restricted to childless terminals so a bracket parent added before its children (FK order) is not prematurely evicted. Regression test `test_terminal_add_order_not_resident`.
- **WR-01 (fixed):** `CachedSqlSignalStorage.add` runs dedup-check + store write + mirror under one lock (no partial-commit `IntegrityError`; no doomed row). Strengthened `test_duplicate_rejected`.
- **WR-02 (fixed):** `clear_portfolio_orders` / `remove_orders_by_ticker` re-evaluate the bracket parents of cleared children, evicting an orphaned resident terminal parent. Regression tests `test_clear_evicts_orphaned_terminal_parent`, `test_remove_by_ticker_evicts_orphaned_terminal_parent`.
- **IN-01 (fixed):** `models.py` docstring six → seven portfolio tables.

## Summary

Reviewed the v1.6 Phase-4 live write-through persistence layer: the three per-domain
`CachedSql*Storage` decorators, their factory `'live'` arms, the `portfolio_account_state`
table + Alembic migration, and the integration/unit suites. The store-first write-through
discipline, the bracket-parent-resident gate (pre- and post-rehydration), cross-portfolio
isolation, and the import-quarantine structure are all implemented soundly and well tested.
I traced the eviction/purge gates against the composed in-memory and SQL stores and against
the real upstream callers (`AdmissionManager`, `BracketManager`).

The decorators are sound for the *tested* mutation path (PENDING → update_order → terminalize),
but the **`add_order` write seam has no terminal-state eviction gate**. The upstream order
manager persists audited REJECTED (terminal) orders directly via `add_order` — on every
admission/sizing/direction-gate/validator rejection — and those terminal records are mirrored
into the cache working set and never purged. This defeats the central D-02 purge-on-terminalize
/ flat-RSS invariant for a routine live path and is the one blocker. Two warnings (a non-atomic
signal de-dup window; a clear/remove retention edge that orphans a resident terminal bracket
parent) and one doc inconsistency round out the findings.

## Critical Issues

### CR-01: `add_order` bypasses the terminal-state eviction gate — REJECTED orders leak into the cache unbounded

**File:** `itrader/order_handler/storage/cached_sql_storage.py:113-117`
**Issue:**
`add_order` persists store-first then unconditionally mirrors into the cache, with **no
`_can_evict` check**:

```python
def add_order(self, order: "Order") -> None:
    self._store.add_order(order)            # one txn (orders row + state_changes)
    with self._lock:
        self._cache.add_order(order)        # mirror into the working set  <-- no purge gate
```

`update_order` correctly purges a now-terminal order (lines 119-130), but `add_order` does not.
This matters because terminal orders enter storage through `add_order`, not only through
`update_order`. The order manager persists *audited REJECTED orders* directly:

- `itrader/order_handler/admission/admission_manager.py:932` (`add_state_change(REJECTED)` then `add_order(rejected)`)
- `itrader/order_handler/admission/admission_manager.py:257,310` (PENDING→REJECTED then `add_order(primary)`)

These are routine live events (sizing-policy failures, the direction gate, validator
rejections — see `order_validator.py:224` "rejected-at-admission entities are stored REJECTED
before validation"). Each REJECTED order is `is_terminal` at the moment of `add_order`, so via
the live wrapper it is mirrored into `InMemoryOrderStorage._by_id` and **never evicted** (purge
only fires inside `update_order`, which is never called for a rejected-at-add order). Over a
long-running live process the working set grows by one resident terminal record per rejection,
directly violating the D-02 purge-on-terminalize / flat-RSS invariant that is this phase's core
deliverable. The `test_flat_rss` test only exercises PENDING→update_order→FILLED, so the
rejected-at-add path is untested.

**Fix:** mirror `update_order`'s gate in `add_order` — after the store commit and cache mirror,
purge a terminal-at-add order (a standalone REJECTED has no children, so it is immediately
evictable; re-evaluate a parent if one exists):

```python
def add_order(self, order: "Order") -> None:
    self._store.add_order(order)
    with self._lock:
        self._cache.add_order(order)
        if self._can_evict(order):
            self._cache.remove_order(order.id)
            if order.parent_order_id is not None:
                self._maybe_evict_parent(order.parent_order_id)
```

(The order stays served via read-through to the store, exactly as a terminalized order is.)

## Warnings

### WR-01: Signal-store duplicate check is not atomic with the write — overstated "no doomed row" / thread-safety guarantee

**File:** `itrader/strategy_handler/storage/cached_sql_storage.py:64-76`
**Issue:** `add` releases the lock between the duplicate-id check and the store/cache write:

```python
with self._lock:
    if any(r.signal_id == record.signal_id for r in self._cache.get_all()):
        raise ValueError(...)
self._store.add(record)      # <-- lock released here
with self._lock:
    self._cache.add(record)
```

The docstring claims the up-front check guarantees "no doomed row is written" and that the
wrapper is "API-thread-safe for the imminent FastAPI layer." Both claims fail under concurrent
same-`signal_id` adds: two callers can both pass the cache check, then both call
`self._store.add(...)`; the second hits the store's unique constraint and raises
`IntegrityError` (not the documented house `ValueError`) — *after* the first has already
committed a row. Benign under the current daemon-sole-writer wiring, but the comment advertises
safety the code does not provide. The up-front scan is also redundant with `InMemorySignalStore.add`'s
own duplicate contract.

**Fix:** hold `self._lock` across the entire `add` (check → store → cache) so the de-dup and the
write are one critical section, or drop the up-front scan and translate the store's unique-key
error into the house `ValueError`. Tighten the docstring to match whichever is chosen.

### WR-02: `clear_portfolio_orders` / `remove_orders_by_ticker` can orphan a resident terminal bracket parent in the cache

**File:** `itrader/order_handler/storage/cached_sql_storage.py:139-151`
**Issue:** Both methods only remove *active* orders (store and cache). A terminal bracket parent
kept resident under the bracket-parent-resident invariant (terminal but retained because its
children are live) is not active, so it is not removed. If its live children are then cleared by
`clear_portfolio_orders`/`remove_orders_by_ticker`, the parent's eviction is never re-evaluated
(purge only fires on child *terminalization* via `update_order`, not on child *removal*). The
terminal parent then leaks in the cache working set until process restart — a retention gap in
the same flat-RSS contract this phase targets. Edge-triggered (clearing a portfolio mid-bracket),
but currently untested.

**Fix:** after clearing/removing the active set, re-evaluate any resident terminal parents whose
children were just removed and purge those now-orphaned (no remaining live children) parents
(e.g., iterate the removed orders' `parent_order_id`s through `_maybe_evict_parent`, or sweep
resident terminal parents for the portfolio).

## Info

### IN-01: `models.py` module docstring says "six" tables but registers seven

**File:** `itrader/portfolio_handler/storage/models.py:8-9` (also `itrader/portfolio_handler/storage/sql_storage.py:4-7`)
**Issue:** The module docstring states `build_portfolio_tables` "registers six normalized tables",
but it registers seven (the seven-bullet list immediately below includes
`portfolio_account_state`, and the function docstring at line 54 correctly says "seven"). The
stale count is misleading for the next reader.
**Fix:** change "six normalized tables" → "seven", consistent with the function docstring and the
bullet list. (The `sql_storage.py` "registers the six portfolio tables" wording is defensible —
it assigns six and intentionally ignores `portfolio_account_state` per D-04 — but a one-word
clarification there would avoid the same confusion.)

---

_Reviewed: 2026-06-30T10:28:59Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
