---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
plan: 04
subsystem: storage-spine
tags: [storage, sql, alembic, sqlite, foreign-keys, determinism, gap-remediation]
dependency_graph:
  requires: [04-01, 04-02, 04-03]
  provides:
    - "tests.support.schema.provision_schema — shared test-side schema-provisioning seam"
    - "SqlEngine dialect-guarded SQLite FK enforcement (PRAGMA foreign_keys=ON connect-hook)"
    - "StrategyRegistryStore.read_all deterministic ORDER BY (record + subscription-list order)"
    - "7 schema-pure durable stores (no runtime create_all; Alembic-owned in production)"
  affects:
    - "every durable-store test (unit + integration) now provisions schema explicitly"
tech_stack:
  added: []
  patterns:
    - "engine correctness semantics (FK enforcement) at the backend (SqlEngine); provisioning at the fixture"
    - "schema-pure durable stores: build_* registrar registers tables, provisioning is a separate concern"
key_files:
  created:
    - tests/support/schema.py
  modified:
    - itrader/storage/engine.py
    - itrader/storage/system_store.py
    - itrader/storage/venue_store.py
    - itrader/storage/strategy_registry_store.py
    - itrader/storage/halt_record_store.py
    - itrader/order_handler/storage/sql_storage.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - itrader/strategy_handler/storage/sql_storage.py
    - tests/unit/storage/test_system_store.py
    - tests/unit/storage/test_venue_store.py
    - tests/unit/storage/test_strategy_registry_store.py
    - tests/integration/storage/test_sql_order_storage.py
    - tests/integration/storage/test_sql_portfolio_storage.py
    - tests/integration/storage/test_sql_signal_storage.py
    - tests/integration/storage/test_cached_sql_portfolio_storage.py
    - tests/integration/test_durable_halt.py
decisions:
  - "WR-02: SQLite FK enforcement lives on SqlEngine (dialect-guarded PRAGMA connect-hook), not a fixture — engine correctness semantics must be identical on every dialect the engine runs (test-SQLite, results store, Turso slot)"
  - "IN-01: read_all ordered by strategy_name ASC then (venue, symbol, timeframe) ASC — deterministic record order AND subscription-list order"
  - "WR-03/D-14: 7 durable stores are schema-pure (no runtime create_all); production Alembic-owned, tests provision via tests.support.schema.provision_schema; ephemeral results store keeps create_all"
metrics:
  duration: ~20m
  completed_date: 2026-07-10
status: complete
---

# Phase 4 Plan 4: Storage Gap Remediation (WR-02 / IN-01 / WR-03) Summary

Closed the three build-scope Phase-4 code-review findings as one plan appended to the
already-shipped Phase 4: backend-level SQLite foreign-key enforcement, a deterministic
strategy-registry rehydrate order, and a schema-pure durable-store spine (runtime
`create_all` removed from all 7 durable constructors, moved to a shared `provision_schema`
test fixture) — without disturbing the byte-exact oracle, the OKX import-inertness gate, or
the create_all-vs-migration parity gate.

## What Was Built

### Task 1 — WR-02: SQLite FK enforcement at the SqlEngine backend
- Added a dialect-guarded `event.listens_for(engine, "connect")` hook in
  `itrader/storage/engine.py` that runs `PRAGMA foreign_keys=ON` on the raw DBAPI connection
  (explicit cursor open/execute/close — no ResourceWarning under `filterwarnings=["error"]`).
- Guarded on `self.engine.dialect.name == "sqlite"`, so it is a dead no-op on Postgres and
  lives once on the shared spine — every composing store inherits enforcement (test-SQLite,
  the file-backed results store, and the Turso/libSQL slot).
- Added `test_set_subscriptions_on_unregistered_strategy_raises_integrity_error`: an orphan
  subscription (no parent registry row) now raises `IntegrityError` on SQLite, matching
  Postgres. Before the fix SQLite silently inserted the orphan.
- Commit: `52c3a1e7`

### Task 2 — IN-01: deterministic ORDER BY on read_all
- Added `.order_by(strategy_name ASC, venue ASC, symbol ASC, timeframe ASC)` to
  `StrategyRegistryStore.read_all` — makes both the returned record order and each record's
  subscription-list order reproducible (records dict populates in row order). No change to the
  return schema, grouping, or the outer-join shape.
- Added `test_read_all_is_deterministically_ordered` asserting list-order (not set) under
  non-sorted insertion.
- Commit: `9935a184`

### Task 3 — WR-03/D-14: schema-pure durable stores + shared provisioning
- Created `tests/support/schema.py::provision_schema(sql_engine)` — the light D-14 variant
  (`metadata.create_all(checkfirst=True)`, not `alembic upgrade head`). Import-light
  (SqlEngine annotation under `TYPE_CHECKING`).
- Removed the runtime `create_all` line from all 7 durable store constructors (system, venue,
  strategy_registry, halt_record, order, portfolio-state, signal SQL storage); updated their
  docstrings/comments to state the durable schema is Alembic-owned in production and
  provisioned by the fixture in tests. The `build_*` registrars are unchanged (still the
  single source of truth feeding both the test-path create_all and Alembic autogenerate).
- Threaded `provision_schema` through the unit store helpers and integration tests that
  construct-then-query.
- Commit: `0d86109c`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Provisioned a reference-only sibling test surfaced red by Step D**
- **Found during:** Task 3, Step D (full-suite drive)
- **Issue:** `tests/integration/storage/test_cached_sql_portfolio_storage.py::test_cross_portfolio_isolation`
  builds two `SqlPortfolioStateStorage` directly (not through its provisioning `wrapper`
  fixture) and previously relied on the constructor's `create_all`. Removing it surfaced
  `UndefinedTable: relation "positions" does not exist`.
- **Fix:** Applied the same fix the plan prescribes in Step D — imported `provision_schema`
  and provisioned once after construction, before the first query. Did NOT weaken the test or
  touch the FK PRAGMA.
- **Files modified:** `tests/integration/storage/test_cached_sql_portfolio_storage.py`
- **Commit:** `0d86109c`

The plan directed adding `provision_schema` to
`test_live_portfolio_durable_wiring.py::test_portfolio_rehydrate_runs_before_reconcile_on_live_start`.
That test constructs `LiveTradingSystem(exchange="paper")` with no Postgres env, so
`_system_db_backend is None` (backtest arm, in-memory) and the rehydrate loop never queries a
durable ledger — the test stays green untouched, and adding `provision_schema(None)` would
have crashed it. Per Step D ("do NOT add provisioning to tests that never query"), the file
was left unmodified. Confirmed green.

## Verification

- `poetry run pytest tests` — **2048 passed, 6 skipped** (skips are OKX-credential-gated
  live/e2e suites). `filterwarnings=["error"]` clean (no ResourceWarning).
- Backtest oracle byte-exact: **134 / 46189.87730727451** (`test_backtest_oracle.py` green).
- OKX import-inertness green (`test_okx_inertness.py`).
- create_all-vs-migration parity + single-head + full-chain upgrade green (`test_migrations.py`).
- `poetry run mypy itrader` — clean (`--strict`, 234 source files).
- Line-start executable `create_all` grep: zero matches across the 7 durable stores; exactly 1
  in `itrader/results/sql_storage.py` (D-14 exclusion preserved).
- Indentation: all edited storage-spine + SQL storage modules stayed 4-space (no tab introduced).
- Prohibitions honored: `results/sql_storage.py` untouched; `_SECRET_KEY_DENYLIST` untouched;
  `VenueStore._row_to_dict` / store clones not refactored; zero new dependency; FK PRAGMA never
  disabled (no FK-ordering bug surfaced — existing delete paths already order child-before-parent).

## Requirements Satisfied

SQL-02, STORE-01, STORE-02, STORE-03, STORE-04, STORE-05.

## Self-Check: PASSED

- FOUND: tests/support/schema.py
- FOUND commit 52c3a1e7 (Task 1)
- FOUND commit 9935a184 (Task 2)
- FOUND commit 0d86109c (Task 3)

## Post-Review Remediation (2026-07-10, phase-04 code-review gate)

The code-review gate that ran after this plan surfaced one **BLOCKER** the green suite missed —
because WR-02 turned on FK enforcement but no test exercised the re-upsert-of-a-subscribed-strategy
path (the original Self-Check only checked *delete* ordering, not the *upsert* parent-delete):

- ✅ **CR-01 (BLOCKER) — FIXED** (`53a90b07`): `StrategyRegistryStore.upsert` delete-then-inserted
  the FK-parent `strategy_registry` row, which now violates the `strategy_subscriptions` FK once a
  strategy has subscriptions (the live re-config path `upsert → set_subscriptions → upsert`). This
  already failed on Postgres; WR-02 made SQLite consistent and the review caught it. Switched to
  update-in-place-or-insert (parent never deleted); added regression test
  `test_upsert_of_subscribed_strategy_preserves_children`. Reproduced before / confirmed fixed after.
- ✅ **IN-01 / IN-02 — FIXED** (`6b623549`): removed dead `import uuid`; aligned the `Decimal("0")`
  sum seed. No behavioral change.
- ⏭ **WR-01 / WR-02 / WR-03 — DEFERRED** (owner-approved) to
  `.planning/todos/pending/04-storage-review-warnings.md`: parity-test constraint coverage,
  cross-file Postgres-cleanup ordering, durable-store naive-datetime guard.

Post-remediation gates: `poetry run pytest tests` **2049 passed, 6 skipped**; oracle byte-exact
(134 / 46189.87730727451); OKX inertness + migration parity green; `mypy --strict` clean. See
`04-REVIEW.md` for the full findings and remediation record.
