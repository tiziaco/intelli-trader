---
phase: 02-order-storage-indexing
plan: 01
subsystem: database
tags: [in-memory-storage, secondary-index, order-handler, performance, shadow-registry, decimal]

# Dependency graph
requires:
  - phase: 01-perf-tooling-baseline
    provides: "W1 benchmark harness + frozen W1-BASELINE.json (247.5s) that gate (b) diffs against"
provides:
  - "Two derived secondary indexes (_active_by_portfolio, active-only _by_status) + a _last_indexed_status shadow registry over the flat _by_id dict in InMemoryOrderStorage"
  - "Shared _index_apply (diff-on-write) / _index_remove maintenance helpers wired into the 5 write seams"
  - "Active-set queries + scanners (get_active_orders/get_pending_orders/get_orders_by_status(active)/remove_orders_by_ticker/clear_portfolio_orders) rerouted off the O(all-orders-ever) flat scan"
  - "D-09 order-equivalence regression test + maintenance-matrix coverage"
affects: [03-running-pnl-accumulator, persistence, postgresql-order-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Derived-cache-over-source-of-truth: parallel index dicts maintained at every write seam (mirrors MatchingEngine _resting/_trails), flat _by_id stays the sole source of truth (D-20)"
    - "Diff-on-write via shadow registry: status mutates in place, so storage diffs registry old -> order.status new (D-03), not the object"
    - "Insertion-ordered membership via dict[oid, None] (never plain set) for byte-identical query order (D-06/D-08)"

key-files:
  created: []
  modified:
    - "itrader/order_handler/storage/in_memory_storage.py"
    - "tests/unit/order/test_order_storage.py"

key-decisions:
  - "Active queries resolve via the indexes; None path uses a _by_id scan-fallback (Pitfall 1) to keep GLOBAL insertion order byte-identical — no production hot caller passes None"
  - "by_status is active-only (D-10): terminal-status queries still scan the flat dict; OrderStorage ABC stays UNCHANGED (D-05) with the D-05a SQL-expressibility audit recorded in-code"
  - "Two existing storage tests updated to pair the in-place fill with update_order (the D-04 write-seam reconcile contract supersedes the old query-time-predicate semantics)"

patterns-established:
  - "Pattern 1: diff-on-write index maintenance via shadow registry (one shared _index_apply for add_order + update_order)"
  - "Pattern 2: index-backed query preserving insertion order (per-portfolio = single bucket lookup; None = scan-fallback)"

requirements-completed: [PERF-01]

# Metrics
duration: 4min
completed: 2026-06-23
---

# Phase 2 Plan 01: Order-Storage Indexing Summary

**Two derived secondary indexes (active-by-portfolio + active-only by-status) plus a shadow-key registry over the flat `{id: order}` dict, maintained diff-on-write at the 5 write seams, removing W1 hotspot #1's O(all-orders-ever) active-path scan while keeping query output byte-identical and the oracle byte-exact.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-23T21:02:03Z
- **Completed:** 2026-06-23T21:06:39Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Added `_active_by_portfolio` (`{pid: {oid: None}}`), active-only `_by_status` (`{status: {oid: None}}`), and `_last_indexed_status` (`{oid: status}`) caches alongside the unchanged flat `_by_id` source of truth (D-20), with a shared `_index_apply`/`_index_remove` maintenance pair.
- Wired maintenance into all 5 write seams (`add_order`, `update_order`, `remove_order`, `remove_orders_by_ticker`, `clear_portfolio_orders`); handled the add-of-already-terminal (Pitfall 2), re-add idempotence (Pitfall 4), new-id same-status (Pitfall 3), and registry-leak (Pitfall 5) edge cases.
- Rerouted every active-set query/scanner off the flat scan: `get_active_orders` (per-portfolio = single bucket lookup, None = global-order scan-fallback per Pitfall 1), `get_pending_orders`, `get_orders_by_status` (active branch via index, terminal scans per D-10), `remove_orders_by_ticker`, `clear_portfolio_orders`.
- Kept the `OrderStorage` ABC UNCHANGED (D-05) and recorded the D-05a SQL-expressibility seam audit as an in-code comment.
- Landed the D-09 order-equivalence regression test (per-portfolio AND None paths) + maintenance-matrix tests; proved gate (a): oracle byte-exact (134 / 46189.87730727451), determinism 9/9 byte-identical, mypy --strict clean (187 files).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the indexes, runtime OrderStatus import, and diff-on-write maintenance at the 5 write seams** - `4d737e7` (feat)
2. **Task 2: Reroute the active queries + the two remaining scanners through the indexes** - `e4c5eb7` (feat)
3. **Task 3: Add the D-09 order-equivalence + maintenance-matrix regression tests; prove gate (a)** - `0b8dd78` (test)

_Note: Tasks 1 & 2 are TDD-flavored (existing suite is the regression lock); the dedicated equivalence/matrix tests landed in Task 3._

## Files Created/Modified
- `itrader/order_handler/storage/in_memory_storage.py` - Runtime `OrderStatus` import + module-level `_ACTIVE_STATUSES` frozenset; three derived caches in `__init__`; `_index_apply`/`_index_remove` helpers; maintenance wired into the 5 write seams; active queries/scanners rerouted; D-05a seam-audit comment.
- `tests/unit/order/test_order_storage.py` - D-09 equivalence test (`-k equivalence`) + maintenance-matrix tests (terminal-drop, remove-by-ticker/clear consistency, re-add idempotence); two existing fill tests updated to pair the in-place transition with `update_order`.

## Decisions Made
- **None new beyond the plan's locked D-decisions.** Followed D-01..D-11 and D-20 as specified. The `None`-path scan-fallback (Pitfall 1 option a), active-only `by_status` (D-10), and unchanged ABC (D-05) were all pre-decided.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated two existing storage tests that asserted now-obsolete query-time-predicate semantics**
- **Found during:** Task 2 (rerouting active queries through the indexes)
- **Issue:** `test_filled_order_leaves_active_queries_via_predicate` and `test_history_queries_return_filled_orders` mutated an order's status in place (`add_fill`) and asserted the active queries reflected it **without** calling `update_order`. That worked against the old query-time `is_active` scan, but is fundamentally incompatible with the index design (D-03/D-04): the cache only reconciles at a write seam. The first test's docstring even claimed "No update_order call is needed" — a contract the indexes deliberately supersede. The production path (`reconcile_manager.py` line 144 `add_fill` → line 267 `update_order`) already honors the pairing (D-04 audit), so this was a test encoding an obsolete assumption, not a code bug.
- **Fix:** Added the `update_order(order)` call after the in-place transition in both tests (mirroring the production reconcile pairing and PATTERNS.md lines 189-196) and updated the first test's name/docstring to reflect the write-seam reconcile contract. Assertion intent (a filled order leaves active queries; stays in the flat dict as history) preserved.
- **Files modified:** `tests/unit/order/test_order_storage.py`
- **Verification:** Both tests + the full 26-test storage file green; oracle byte-exact; mypy --strict clean.
- **Committed in:** `e4c5eb7` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — obsolete test assumption).
**Impact on plan:** Necessary for correctness — the tests asserted a semantic the index design intentionally changes (D-03/D-04). No production-behavior change; no scope creep. The plan's Task 1 acceptance line listing `test_filled_order_leaves...` as "still passing unchanged" was inconsistent with the index's own write-seam contract; resolved by aligning the test to that contract.

## Issues Encountered
- One mypy `--strict` error in `_index_apply`: `_by_status[old_status]` where `old_status` was narrowed to `OrderStatus | None` (mypy cannot infer non-None from `frozenset` membership via the `was_active` bool). Fixed by testing `old_status is not None and old_status in _ACTIVE_STATUSES` directly so mypy narrows the type. No behavior change.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- **Gate (a) PASSED** — oracle byte-exact (134 / 46189.87730727451), determinism byte-identical, mypy --strict clean. Plan 02 (gate (b): `make perf-w1` ≥5% wall-clock improvement + re-freeze the baseline) is the remaining phase deliverable and is owned by the next plan.
- The flat `_by_id` dict remains the sole source of truth; the indexes are caches consistent at every write. The `OrderStorage` ABC is unchanged and SQL-expressible (D-05a audit recorded), ready for a future `PostgreSQLOrderStorage` (N+3b Persistence).

## Self-Check: PASSED

- FOUND: `.planning/phases/02-order-storage-indexing/02-01-SUMMARY.md`
- FOUND commit `4d737e7` (Task 1), `e4c5eb7` (Task 2), `0b8dd78` (Task 3)
- VERIFIED: `itrader/order_handler/base.py` (OrderStorage ABC) UNCHANGED (no diff)
- VERIFIED: gate (a) — oracle 3/3, determinism 9/9, mypy --strict clean (187 files), storage suite 26/26, `-k equivalence` selects 1

---
*Phase: 02-order-storage-indexing*
*Completed: 2026-06-23*
