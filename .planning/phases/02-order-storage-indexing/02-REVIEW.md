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
  warning: 1
  info: 2
  total: 3
status: resolved
resolved_at: 2026-06-23T00:00:00Z
resolution:
  - "WR-01 FIXED (commit 95520de): added isinstance(portfolio_id, uuid.UUID) fail-closed guards at the four _active_by_portfolio lookup sites (get_active_orders, get_pending_orders, remove_orders_by_ticker, clear_portfolio_orders); the four # type: ignore[arg-type] suppressions are removed (isinstance narrows IdLike to uuid.UUID for mypy)."
  - "IN-01 FIXED (commit 95520de): corrected the _last_indexed_status docstrings — the registry is one-entry-per-live-order (active OR terminal), not active-only."
  - "IN-02 FIXED (commit 95520de): get_active_orders(None) now routes the flat scan through the centralized _orders() helper; get_pending_orders left as-is (nested shape) by design."
  - "Verified after fix: mypy --strict clean (187 files); oracle byte-exact (134 / 46189.87730727451); determinism 9/9; storage 27/27; order+execution 416."
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** resolved (all 3 findings fixed in 95520de via --fix --all)

## Summary

Reviewed the two derived secondary indexes (`_active_by_portfolio`, active-only
`_by_status`) plus the `_last_indexed_status` shadow registry added over the flat
`_by_id` source of truth in `InMemoryOrderStorage`, with focus on the primary risk
class T-02-01 (cache-coherency / stale-index drift).

**Cache-coherency verdict: clean.** I traced every one of the five write seams and
the `_index_apply` / `_index_remove` diff logic:

- `_index_apply` correctly handles all four boundary cases — brand-new id (`old=None`),
  active->active (PENDING->PARTIALLY_FILLED, no bucket move), active->terminal (drop
  from both caches), and REJECTED-at-add (never enters the active book). The `old_status
  is not None and old_status in _ACTIVE_STATUSES` guard at L97 cannot dereference a
  missing `_by_status` bucket, because the bucket is always `setdefault`-created (L100)
  on the prior active write that registered `old_status`.
- The active-only branches (`get_active_orders(pid)`, `get_pending_orders(pid)`,
  `get_orders_by_status` active branch, `remove_orders_by_ticker`, `clear_portfolio_orders`)
  all depend on the D-04 invariant (in-place status mutation paired with a storage write).
  I verified in production that every terminal arm in `reconcile_manager.on_fill`
  (`_apply_cancelled` / `_apply_refused` / `_apply_expired`, L247-251) leaves `applied=True`
  (initialized L229) and reaches `update_order` (L266-267), so the index always reconciles.
  `lifecycle_manager` (L116/179/260) and `bracket_manager` likewise pair mutation with a write.
- The `None`-path queries (`get_active_orders(None)`, `get_pending_orders(None)`,
  terminal-status branch of `get_orders_by_status`) read `order.status` live off `_by_id`,
  so they are correct by construction regardless of index state.

**Prior-finding confirmations:**

- **WR-01 (FIXED — do NOT re-report):** `get_orders_by_status` active branch (L258-261)
  now resolves membership via `_by_status` but yields via `_orders()` in `_by_id` add-order.
  Confirmed byte-equivalent to the flat-scan oracle for PARTIALLY_FILLED; the regression
  test `test_partially_filled_status_query_preserves_add_order_equivalence` (L356-399)
  correctly drives order2-before-order1 transition order and locks add-order output. Correct.

Three findings remain, carried from the prior review and re-assessed against current code:
one WARNING (latent type-divergence, prior WR-02) and two INFO (prior IN-01 overstated
docstrings, prior IN-02 scattered portfolio predicate).

## Warnings

### WR-01: Index lookups assume native-UUID `portfolio_id`, silently miss on the ABC's permitted str/int

**File:** `itrader/order_handler/storage/in_memory_storage.py:161, 179, 222, 273`
**Issue:** Four call sites look up `_active_by_portfolio.get(portfolio_id, {})` with a
`# type: ignore[arg-type]`. `_active_by_portfolio` is keyed exclusively by
`order.portfolio_id`, which is a native `uuid.UUID` at runtime (`PortfolioId = NewType(..., uuid.UUID)`).
But the `OrderStorage` ABC and these method signatures declare `portfolio_id: IdLike =
Union[str, int, uuid.UUID]` (`base.py:7`). If a legacy `str`/`int` portfolio_id ever
reaches `get_active_orders` / `get_pending_orders` / `remove_orders_by_ticker` /
`clear_portfolio_orders`, the index lookup returns `{}` (silent empty) — yet the
`None`-path and terminal-status fallbacks compare with `order.portfolio_id == portfolio_id`
and would behave differently. This is a latent stale-index-shaped correctness divergence:
the same logical query returns different results on the index path vs the scan path purely
on id type. Today all production callers (`reconcile_manager.py:319`,
`lifecycle_manager.py:253`) pass UUID-typed ids so it does not fire, but the four
`type: ignore` suppressions are the marker of an unguarded type assumption, and the ABC
contract explicitly permits the divergent input.
**Fix:** Make the assumption explicit and fail-closed rather than silent-miss. Add a
narrow guard mirroring the `remove_order`/`get_order_by_id` pattern (which already returns
`False`/`None` on non-UUID ids, L142/L194). At each of the four sites, short-circuit when
`portfolio_id` is not a `uuid.UUID`:
```python
# get_active_orders, get_pending_orders (per-portfolio branch):
if portfolio_id is not None and not isinstance(portfolio_id, uuid.UUID):
    return []          # (or {portfolio_id: {}} for get_pending_orders)
bucket = self._active_by_portfolio.get(portfolio_id, {})
# remove_orders_by_ticker / clear_portfolio_orders:
if not isinstance(portfolio_id, uuid.UUID):
    return 0
```
This removes the silent-miss divergence and lets the four `# type: ignore[arg-type]`
comments be deleted (the `isinstance` narrows `IdLike` to `uuid.UUID` for mypy).

## Info

### IN-01: Shadow-registry docstrings overstate an "active-only memory posture" that the code does not enforce

**File:** `itrader/order_handler/storage/in_memory_storage.py:64, 106-108`
**Issue:** The inline comment at L64 and `_index_remove`'s docstring (L106-108, "the
active-only memory posture, D-11, is preserved") describe `_last_indexed_status` as an
active-only structure. This is inaccurate: `_index_apply` writes
`self._last_indexed_status[oid] = new_status` unconditionally for every status change
(L101), including terminal ones. A REJECTED-at-add order (Pitfall 2) and every
PENDING->FILLED transition leave a terminal status in the registry; it is NOT active-only.
The registry's actual posture is "one entry per live `_by_id` order, dropped on remove"
— which is the correct behavior, but the docstring describes a different, narrower
invariant that a future maintainer could mistakenly try to "restore" by pruning terminal
entries. That would break the `old_status` diff for terminal orders: the diff at L79-83
relies on the registered terminal status to compute `was_active`/`old_status` correctly on
a subsequent re-add or update of the same id.
**Fix:** Correct the two comments to describe the real invariant. Replace the L106-108
docstring clause and the L64 inline comment so they read, in effect:
```python
# L106-108:
"""Drop one order from both caches + the registry (delete paths).

Pitfall 5: every remove pops the registry entry too, so the registry holds
exactly one entry per LIVE _by_id order (active OR terminal) and never leaks a
stale status after the order is deleted.
"""
```
and change the L64 inline `# shadow registry (D-03)` note to state it records the
last-indexed status for every live order (active or terminal), not active-only.

### IN-02: `_orders()` helper bypassed by the `get_active_orders` None scan, re-scattering the portfolio predicate it centralizes

**File:** `itrader/order_handler/storage/in_memory_storage.py:275` (and 186-188 for context)
**Issue:** `_orders(portfolio_id)` (L123-127) exists to centralize the
`portfolio_id is None or order.portfolio_id == portfolio_id` filter, and most query
methods route through it (`get_orders_by_ticker`, `get_orders_by_status` terminal branch,
`get_orders_by_time_range`, `search_orders`, `count_orders_by_status`). Two `None`-path
scans inline their own `_by_id.values()` walk instead: `get_active_orders` (L275) and
`get_pending_orders` (L186-188). The `get_pending_orders` case is justified — it builds a
*nested* `{pid: {oid: order}}` shape that genuinely cannot use the flat helper. But
`get_active_orders`'s None branch, `[o for o in self._by_id.values() if o.status in
_ACTIVE_STATUSES]`, duplicates an unfiltered walk that the helper already provides,
leaving the iteration source inconsistent with its sibling query methods. Low severity:
the walk is correct and add-order-equivalent today; this is a maintainability/consistency
note, not a bug.
**Fix:** Source the `get_active_orders` None branch through the helper:
```python
return [o for o in self._orders() if o.status in _ACTIVE_STATUSES]
```
Leave `get_pending_orders` as-is, but add a one-line comment there noting it does not use
`_orders()` because it constructs a nested shape, so the asymmetry is intentional-by-record
rather than an oversight.

---

_Reviewed: 2026-06-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
