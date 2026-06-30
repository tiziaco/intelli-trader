---
phase: 04-retention-live-write-through-2-live-path
plan: 01
subsystem: database
tags: [postgres, sqlalchemy, order-storage, write-through, cache, retention, testcontainers]

# Dependency graph
requires:
  - phase: 03 (operational SQL stores)
    provides: SqlOrderStorage (system of record), OrderStorage ABC, pg_backend testcontainers fixture
provides:
  - CachedSqlOrderStorage — live order-seam decorator (store-first write-through + purged working set)
  - terminal-state eviction gate with bracket-parent-resident invariant (D-02)
  - read-through split (open set cache-only, terminal/history to store)
  - open-only restart rehydration pulling live-child parents (D-03)
  - order factory 'live' arm wired to the wrapper (RETAIN-01)
affects: [04-02 portfolio-state wrapper, 04-03 signal wrapper, 04-04 cross-cutting quarantine gate, N+4 reconciliation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Storage decorator: CachedSql<Concern>Storage composes Sql<Concern>Storage (record) + InMemory<Concern>Storage (working set) + RLock"
    - "Store-first write-through (persist-then-acknowledge, Pitfall 8): store commit returns before cache mutation"
    - "Terminal-state eviction gate + bracket-parent-resident (D-02)"
    - "TYPE_CHECKING-only SQL imports keep the live wrapper SQL-import-light (GATE-01 quarantine)"

key-files:
  created:
    - itrader/order_handler/storage/cached_sql_storage.py
    - tests/integration/storage/test_cached_sql_order_storage.py
  modified:
    - itrader/order_handler/storage/storage_factory.py
    - .gitignore

key-decisions:
  - "D-04 wrapper topology: the live arm decorates the untouched Phase-3 SqlOrderStorage; a cache bug cannot compromise the store"
  - "D-02 immediate purge on terminalize behind a mandatory terminal-state gate; bracket parent resident until ALL children terminal"
  - "D-03 rehydrate open-only (PENDING/PARTIALLY_FILLED) + the parents of live children; never standalone terminal history"
  - "A1: per-write store-first FK-ordered; no add_bracket / cross-method txn — cross-method bracket atomicity is N+4 reconciliation, not a Phase-4 failure"
  - "A4: one threading.RLock around cache mutation + read-through lookup (daemon-only as-wired, API-thread-safe for FastAPI)"
  - "A5: the new module enters mypy --strict (no override)"

patterns-established:
  - "Store-first write-through decorator over a per-concern (InMemory/Sql/CachedSql) storage triple"
  - "Session-container hygiene: a create_all test that sorts before test_migrations drops its operational tables in teardown"

requirements-completed: [RETAIN-01, RETAIN-02, RETAIN-03]

# Metrics
duration: ~10min
completed: 2026-06-30
---

# Phase 4 Plan 01: Live Order-Seam Write-Through Wrapper Summary

**`CachedSqlOrderStorage` turns the Phase-3 order store into a long-running, restart-safe live system of record — store-first write-through, terminal-purge with bracket-parent-resident retention, read-through for cold records, and open-only rehydration — without touching the gate-passed `SqlOrderStorage`.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-30T11:55:48+02:00
- **Completed:** 2026-06-30T11:59:58+02:00
- **Tasks:** 3 / 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Built `CachedSqlOrderStorage` — the live-only `OrderStorage` decorator implementing all 14 ABC methods store-first over a purged in-memory working set, with the `_can_evict` terminal-state gate, bracket-parent-resident invariant (D-02), read-through split, and open-only `rehydrate()` (D-03).
- Wired the order `OrderStorageFactory` `'live'` arm to return `CachedSqlOrderStorage(SqlOrderStorage(resolved))` behind the lazy quarantined import (RETAIN-01); the backtest path stays SQL-free (verified by the local quarantine probe).
- Added the six-test testcontainers Postgres integration suite (evict-then-read-through, flat-RSS, bracket-parent-resident, open-only rehydration, crash-restart, within-method atomicity) — all green (GATE-02 gate-b).

## Task Commits

1. **Task 1: Failing order-wrapper integration suite (RED)** - `be3abcc` (test) — also fixed `.gitignore` (see Deviations)
2. **Task 2: Implement CachedSqlOrderStorage (GREEN)** - `456f5d9` (feat)
3. **Task 3: Wire order factory 'live' arm** - `33f34a8` (feat)

**Deviation fix (test isolation):** `18accab` (test) — see Deviations

## Files Created/Modified
- `itrader/order_handler/storage/cached_sql_storage.py` (created) - The live order-seam wrapper: store-first write-through, `_can_evict` gate + bracket-parent-resident, `_child_is_terminal`/`_maybe_evict_parent` helpers, read-through split, open-only `rehydrate()`. 4-space, no tabs, `mypy --strict` clean, TYPE_CHECKING-only SQL imports.
- `tests/integration/storage/test_cached_sql_order_storage.py` (created) - The six live-concern integration tests over the `pg_backend` substrate; autouse teardown drops the operational order tables for session-container hygiene.
- `itrader/order_handler/storage/storage_factory.py` (modified) - `'live'` arm now returns `CachedSqlOrderStorage(SqlOrderStorage(resolved))` behind the lazy in-branch import; backtest/test arm and `ConfigurationError` branch untouched.
- `.gitignore` (modified) - Added `!` negation overrides for the mandated `cached_sql_storage.py` + `test_cached_sql_order_storage.py` artifact names (the broad `**cache**` rule would otherwise ignore them).

## Verification
- `poetry run pytest tests/integration/storage/test_cached_sql_order_storage.py -x -q` → **6 passed** on testcontainers Postgres.
- `poetry run pytest tests/integration/storage/ -q` → **42 passed** (full storage suite green, no regression).
- `poetry run mypy --strict itrader/order_handler/storage/cached_sql_storage.py` → clean (and `mypy --strict itrader/order_handler/` → 24 files clean).
- Indentation: no tabs in `cached_sql_storage.py` (Pitfall 12).
- Quarantine probe: constructing the backtest backend pulls neither `sqlalchemy` nor `cached_sql_storage` → `quarantine ok`.
- No `tests/integration/storage/__init__.py`; no `CachedSqlOrderStorage` re-export in any `__init__.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.gitignore` `**cache**` ignored the mandated artifact filenames**
- **Found during:** Task 1 (commit)
- **Issue:** `git add` refused `test_cached_sql_order_storage.py` (and would refuse `cached_sql_storage.py`) because `.gitignore:32` `**cache**` matches the `cache` substring in the mandated filenames.
- **Fix:** Added `!`-negation overrides following the established convention already present for `cache_registration.py`, `test_bar_cache_registration.py`, and `test_position_cache.py`.
- **Files modified:** `.gitignore`
- **Commit:** `be3abcc`

**2. [Rule 1 - Regression] New test polluted the shared session Postgres container before `test_migrations`**
- **Found during:** post-Task-3 full-suite regression run
- **Issue:** `test_cached_sql_order_storage.py` sorts alphabetically before `test_migrations.py`; its `create_all` left the `orders`/`order_state_changes` tables in the shared session container, so the migration test's `alembic upgrade head` raised `ProgrammingError` (table already exists). In isolation both passed; the existing create_all tests avoid this only because they sort after `test_migrations`.
- **Fix:** Added an autouse teardown fixture in the new test file that drops `order_state_changes`/`orders` (FK order) after each test — the same pristine-container discipline `test_migrations` follows with its `downgrade base`. No other files touched.
- **Files modified:** `tests/integration/storage/test_cached_sql_order_storage.py`
- **Commit:** `18accab`

## Threat Coverage
- T-04-01 (Tampering — read-through/rehydration reads): the wrapper writes NO SQL of its own; it forwards to the parameterized-Core Phase-3 `SqlOrderStorage` methods.
- T-04-02 (Information disclosure — logger bind): sources an injected `SqlBackend`, never re-resolves creds; no DB URL logged.
- T-04-08 (Tampering — crash mid-write durability): store-first persist-then-acknowledge; within-method atomicity via the composed `engine.begin()` — verified by `test_atomic_within_method`. Cross-method bracket atomicity documented as N+4 (A1).

No new threat surface introduced beyond the plan's `<threat_model>`.

## Known Stubs
None. The wrapper is fully wired (factory `'live'` arm returns it) and exercised end-to-end on Postgres. The composition-root hardcodes and accumulator-restoration into `CashManager`/`PositionManager` remain N+4 by design (D-01/A3) — out of scope for this plan.

## Self-Check: PASSED
All created/modified files present; all task commits (`be3abcc`, `456f5d9`, `33f34a8`, `18accab`) verified in git history.
