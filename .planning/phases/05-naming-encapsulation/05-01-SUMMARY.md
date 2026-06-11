---
phase: 05-naming-encapsulation
plan: 01
subsystem: order_handler
tags: [naming, encapsulation, refactor, behavior-preserving]
requires:
  - "OrderHandler / OrderManager / OrderStorage façade-manager-storage chain (M4)"
provides:
  - "OrderHandler.global_queue (param + attr) — project-wide queue-naming convention (D-02)"
  - "count_orders_by_status canonical name across façade, manager, storage Protocol, both backends (D-01)"
affects:
  - "Any future caller of the count-by-status operation must use count_orders_by_status (legacy names removed, no alias)"
tech-stack:
  added: []
  patterns:
    - "Pure identifier rename — value-/behavior-equal, oracle-dark (no serialized string carries a method/attr name)"
    - "Storage Protocol (base.py) as the mypy --strict conformance anchor — Protocol + both backends + façade renamed atomically"
key-files:
  created: []
  modified:
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/base.py
    - itrader/order_handler/storage/in_memory_storage.py
    - itrader/order_handler/storage/postgresql_storage.py
decisions:
  - "D-02: OrderHandler queue renamed events_queue → global_queue (param + attr + 5 put sites + docstring); no back-compat alias"
  - "D-01: divergent get_orders_summary (façade) / get_orders_count_by_status (storage) collapsed to one verb-first name count_orders_by_status; method returns a count, not a summary"
  - "D-04: no back-compat aliases for either rename"
metrics:
  duration: ~2 min
  completed: 2026-06-11
  tasks: 3
  files: 5
---

# Phase 05 Plan 01: Naming & Encapsulation (NAME-01) Summary

OrderHandler's event queue is now named `global_queue` (matching every other handler), and the
divergently-named count-by-status operation is the single canonical `count_orders_by_status` across
the façade, manager, storage Protocol, and both backends — both pure identifier swaps, golden master
byte-exact and `mypy --strict` clean.

## What Was Built

Two behavior-preserving identifier renames in `itrader/order_handler/`, executed and gated:

- **Task 1 (D-02):** `OrderHandler.__init__` parameter `events_queue` → `global_queue`, the
  `self.events_queue` attribute → `self.global_queue`, the docstring entry, and all five
  `self.events_queue.put(...)` call-sites → `self.global_queue.put(...)`. No wiring edit was needed
  because every `OrderHandler(...)` construction passes the queue positionally (verified in the plan
  interfaces note). The four `events_queue` refs under `strategy_handler/my_strategies/` are off-path
  and were left untouched. TAB indentation preserved.

- **Task 2 (D-01):** the count-by-status chain collapsed from `get_orders_summary` (façade) /
  `get_orders_count_by_status` (storage) to a single canonical `count_orders_by_status` across all
  five sites — façade `OrderHandler` (order_handler.py), façade `OrderManager` (order_manager.py),
  storage `OrderStorage` Protocol (base.py, `@abstractmethod` kept), in-memory backend
  (in_memory_storage.py), and the postgres stub (postgresql_storage.py, stays `NotImplementedError`).
  The rename was atomic in one task so the Protocol conformance anchor never broke mid-edit. The
  "summary" docstring wording was dropped (the method returns a `Dict[str, int]` count). `Dict[str, int]`
  return and all bodies unchanged. Mixed TAB (handler/manager) / 4-space (base/storage) indentation
  preserved per file.

- **Task 3 (gate):** ran the milestone behavior-preserving gate to prove both renames are byte-inert.

## Verification Evidence

| Gate | Result |
|------|--------|
| `grep -c 'events_queue' itrader/order_handler/order_handler.py` | 0 |
| `grep -c 'self.global_queue.put' itrader/order_handler/order_handler.py` | 5 |
| `grep -rn 'get_orders_summary\|get_orders_count_by_status' itrader/order_handler/` | 0 hits |
| `def count_orders_by_status` present | all 5 files |
| `pytest tests/integration -k oracle` | 3 passed (byte-exact: 134 trades / final_equity 46189.87730727451) |
| `pytest tests/e2e -m e2e` | 58 passed |
| `mypy --strict itrader` | Success: no issues found in 162 source files |
| `git diff --check` (all touched files) | clean — no tab/space normalization |
| `tests/golden/` re-baseline | none (no golden file edited) |

## Deviations from Plan

None - plan executed exactly as written.

## Commits

- `4a2d154` refactor(05-01): rename OrderHandler queue events_queue → global_queue (D-02)
- `a912ef9` refactor(05-01): canonical count_orders_by_status across all 5 sites (D-01)

## Known Stubs

`PostgreSQLOrderStorage.count_orders_by_status` remains a `raise NotImplementedError("To be
implemented in Phase 2")` stub. This is intentional and pre-existing — PostgreSQL order storage is
explicitly out of scope for v1.2 (PROJECT.md "Out of Scope" → `D-sql`). Only its signature was
renamed for Protocol conformance; the stub body is unchanged.

## Self-Check: PASSED

- itrader/order_handler/order_handler.py — modified, present
- itrader/order_handler/order_manager.py — modified, present
- itrader/order_handler/base.py — modified, present
- itrader/order_handler/storage/in_memory_storage.py — modified, present
- itrader/order_handler/storage/postgresql_storage.py — modified, present
- Commit 4a2d154 — present in git log
- Commit a912ef9 — present in git log
