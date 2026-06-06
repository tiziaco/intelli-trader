---
phase: 05-m4-money-transaction-correctness
plan: 01
subsystem: order_handler
tags: [D-18, D-20, M4-03, M4-06, PERF3, flat-dict, layering, tdd]
dependency_graph:
  requires: []
  provides:
    - "Flat-dict-only InMemoryOrderStorage (D-20): O(1) {order_id: order} index is the sole container"
    - "One-directional order-handler layering (D-18): facade -> manager -> storage"
    - "OrderManager read interface (get_*/search_*/get_orders_summary pass-throughs)"
  affects:
    - "05-02+ plans touching order_handler/order_manager (constructor signature changed: order_handler_ref removed)"
tech_stack:
  added: []
  patterns:
    - "Predicate-filter storage queries (order.is_active / portfolio_id / ticker / status) over a single flat dict"
    - "Manager returns OperationResults carrying events; handler owns ALL queue puts"
key_files:
  created: []
  modified:
    - itrader/order_handler/storage/in_memory_storage.py
    - itrader/order_handler/base.py
    - itrader/order_handler/storage/postgresql_storage.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - tests/unit/order/test_order_storage.py
    - tests/unit/order/test_order_manager.py
    - tests/unit/order/test_on_signal.py
decisions:
  - "deactivate_order deleted from storage + ABC + postgresql stub; sole production caller (order_manager.on_fill) removed — terminal status alone exits active queries (Pitfall 6)"
  - "archive_orders deleted from ABC + postgresql stub: zero callers anywhere (production or tests); archived_orders container died with it"
  - "remove_orders_by_ticker / clear_portfolio_orders kept (ABC surface) but now fully DELETE active orders from the flat dict instead of the old remove-from-active-book-keep-PENDING-in-history incoherence; terminal orders preserved for audit (T-05-02)"
  - "get_pending_orders keeps its nested {portfolio: {order_id: order}} RETURN shape as a derived on-the-fly view — return-shape convenience, not a stored structure"
  - "Worktree test invocation: poetry run python -m pytest (NOT bare pytest) — shared .venv itrader.pth points at the main repo; the pytest console script omits cwd from sys.path and silently tests main-repo code"
metrics:
  duration: "~12 min"
  completed: "2026-06-06"
  tasks: 2
  commits: 3
---

# Phase 5 Plan 01: Order Storage Flat-Dict + Facade/Manager Layering Summary

Flat `{order_id: order}` dict is now the sole order container (D-20, closes PERF3/M4-06) and order-handler layering is one-directional facade→manager→storage (D-18, M4-03) — suite, mypy --strict, and both byte-exact oracle layers green at every commit.

## What Was Built

### Task 1 — Flat-dict-only InMemoryOrderStorage (TDD: RED 993de97, GREEN 926261f)

- `self._by_id: Dict[uuid.UUID, 'Order']` is the ONLY instance container; the nested
  `active_orders` / `all_orders` / `archived_orders` per-portfolio dicts and every
  dual-write/dual-delete are deleted.
- `add_order` is a single flat-dict write; `get_order_by_id` / `remove_order` are O(1)
  with native-UUID key narrowing (non-UUID ids return None/False — D-14).
- All queries are predicate filters over `self._by_id.values()`: `order.is_active`,
  `order.portfolio_id == ...`, `order.ticker == ...`, `order.status == ...`. A status
  change alone moves an order across query classes.
- New tests lock the semantics: flat dict as sole container, status-change-only active
  exit (no deactivate call), filled-order history queryability (T-05-02 mitigation).

### Task 2 — One-directional layering (beb5550)

- Deleted deprecated facade methods `add_pending_order` / `remove_orders` / `remove_order`
  (tests updated in the same commit — bisectable).
- Deleted `order_handler_ref` constructor param and `self.order_handler` back-ref from
  `OrderManager` (grep-verified unused in method bodies).
- Storage ownership moved to the manager: `OrderHandler.__init__` forwards the injected
  storage to `OrderManager` and retains NO reference ("D-18: manager owns storage" comment).
- All seven handler read methods (`get_order_by_id`, `get_orders_by_status`,
  `get_active_orders`, `get_order_history`, `get_orders_by_ticker`, `search_orders`,
  `get_orders_summary`) delegate through new same-name/same-signature manager pass-throughs.
- Verified: manager performs zero `events_queue.put` calls — `on_signal`/`modify_order`/
  `cancel_order`/`create_order` all follow the manager-returns-events, handler-puts shape.

## Caller Findings (recorded per plan output spec)

| Method | Callers found | Action |
|--------|---------------|--------|
| `deactivate_order` | Production: `order_manager.on_fill:100` only. Tests: none. | Deleted from impl + ABC + postgresql stub; on_fill call site removed |
| `archive_orders` | NONE (no production, no test callers) | Deleted from ABC + postgresql stub (impl rewritten without it) |
| `remove_orders_by_ticker` | Production: deprecated `OrderHandler.remove_orders` (deleted Task 2). Tests: `test_remove_orders_by_ticker` | Kept on storage (legit cancel-all-for-ticker surface); now deletes active orders from flat dict |
| `clear_portfolio_orders` | Tests only | Kept (ABC surface); deletes active orders, preserves terminal history |
| `get_active_orders_dict` | Internal only (not in ABC) | Deleted; `get_pending_orders` builds the nested view directly |

## ABC Signature Changes

- `OrderStorage.deactivate_order` — removed (abstractmethod)
- `OrderStorage.archive_orders` — removed (abstractmethod)
- `PostgreSQLOrderStorage` (D-sql stub): both overrides removed, mechanical parity only

## Test Deletions / Rewrites

- `test_backward_compatibility_pending_orders` — deleted (exercised deprecated `add_pending_order`)
- `test_order_handler_initialization_with/without_storage` — rewritten to assert manager
  storage ownership (`not hasattr(handler, "order_storage")`)
- `test_order_manager_initialization` — `order_handler_ref` arg removed; asserts no back-ref
- New: `test_flat_dict_is_sole_container`, `test_filled_order_leaves_active_queries_via_predicate`,
  `test_history_queries_return_filled_orders`, `test_handler_reads_delegate_through_manager`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree venv shadowing: `poetry run pytest` tested main-repo code**
- **Found during:** Task 1 GREEN verification (tests stayed red after correct implementation)
- **Issue:** the shared in-project `.venv` lives in the MAIN repo and its `itrader.pth`
  (editable install) puts the main repo on `sys.path`. The `pytest` console script does not
  prepend cwd, so `poetry run pytest` imported the main repo's `itrader`, not the worktree's.
- **Fix:** all verification run via `poetry run python -m pytest ...` (cwd-first import) and
  `poetry run mypy itrader` (cwd-relative). No code/config change committed.
- **Files modified:** none

**2. [Rule 3 - Blocking] `tests/unit/order/test_on_signal.py` updated (not in plan's files_modified)**
- **Found during:** Task 2
- **Issue:** four call sites read `harness.order_handler.order_storage`, which no longer
  exists after storage ownership moved to the manager (mechanical fallout, RESEARCH Pitfall 7).
- **Fix:** repointed to the harness-owned `harness.order_storage` (same instance the harness
  injects into the handler).
- **Files modified:** tests/unit/order/test_on_signal.py
- **Commit:** beb5550

### Acceptance-criterion notes (not code deviations)

- The Task 1 criterion `grep -c "active_orders|all_orders|archived_orders" ... returns 0` is
  literally unsatisfiable: the ABC-mandated method name `get_active_orders` (required by the
  plan's own key_links) contains the substring. The intended check passes:
  `grep -c "self\.active_orders\|self\.all_orders\|self\.archived_orders"` returns 0 and the
  only literal match in the file is the `def get_active_orders` method line.
- `itrader/trading_system/{backtest,live}_trading_system.py` are listed in `files_modified`
  but required NO changes — plan action item 3 explicitly keeps the wiring unchanged (handler
  still receives `order_storage` and forwards it). `tests/unit/order/test_order_handler.py`
  also needed no changes (no deprecated-method usage).
- `make test` / `make typecheck` were run as their direct worktree-safe equivalents
  (`poetry run python -m pytest tests/` / `poetry run mypy itrader`) due to deviation #1.

## Verification Results

- `poetry run python -m pytest tests/unit/order -q` — 79 passed
- `poetry run python -m pytest tests/ -q` — **432 passed** (429+ required), 0 failed
- `poetry run mypy itrader` — Success: no issues found in 134 source files (strict)
- `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` — 2 passed,
  byte-exact, assertions unmodified (both behavioral + numerical layers)
- `git diff --stat tests/golden/` — empty
- All Task 2 greps return 0: deprecated defs, `order_handler_ref`/`self.order_handler` in
  manager, `self.order_storage` in handler, `events_queue.put` in manager

## Known Stubs

None — no placeholder values, no unwired data paths introduced. (`PostgreSQLOrderStorage`
remains the pre-existing D-sql NotImplementedError stub, untouched except for the two
removed overrides.)

## Threat Flags

None — no new network endpoints, auth paths, file access, or trust-boundary schema changes.
T-05-01 mitigated by the rewritten predicate-semantics tests + byte-exact oracle gate;
T-05-02 mitigated by `test_history_queries_return_filled_orders` (filled orders never deleted).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (RED) | 993de97 | test(05-01): failing flat-dict predicate-semantics tests |
| 1 (GREEN) | 926261f | feat(05-01): flat-dict-only InMemoryOrderStorage (D-20, M4-06) |
| 2 | beb5550 | feat(05-01): one-directional facade->manager->storage layering (D-18, M4-03) |

## Self-Check: PASSED

- All modified files exist on disk
- All 3 task commits present (993de97, 926261f, beb5550)
- Full suite 432 passed; mypy strict clean; oracle byte-exact; tests/golden/ untouched
