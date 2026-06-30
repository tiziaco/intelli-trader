---
phase: 03-operational-sql-backends-2-store-layer
plan: 02
subsystem: order_handler/storage
tags: [persistence, sql, postgres, order-mirror, operational-store]
requires:
  - "SqlBackend spine + storage/types (Uuid/UtcIsoText/json_variant) — Phase 1 (01-02)"
  - "pg_backend testcontainers fixture — Phase 1 (01-01) / conftest"
  - "results store sql_storage/models pattern — Phase 2 (02-*)"
provides:
  - "SqlOrderStorage(OrderStorage) — order-mirror operational backend on Postgres (OPS-01, OPS-04)"
  - "build_order_tables(metadata) — orders + order_state_changes Core tables (self-ref bracket FK, D-08 index)"
  - "OrderStorageFactory 'live' arm routes to SqlOrderStorage(SqlBackend) (D-06)"
affects:
  - "Phase 4 (live write-through) wires a shared operational SqlBackend at the live composition root"
  - "Phase 3 Plan 05 Alembic autogenerate consumes build_order_tables in env.py target_metadata"
tech-stack:
  added: []
  patterns:
    - "Compose SqlBackend by reference (has-a); parameterized Core (constant Table/Column + bindparam), never f-string SQL"
    - "Field-wise dataclass round-trip: state_changes -> order_state_changes child table; child_order_ids rebuilt from parent_order_id index (D-02, Pitfall 6)"
    - "Money as native Numeric -> exact Decimal on Postgres (OPS-04); enums stored as .value, read via enum constructor (D-07)"
key-files:
  created:
    - itrader/order_handler/storage/models.py
    - itrader/order_handler/storage/sql_storage.py
    - tests/integration/storage/test_sql_order_storage.py
  modified:
    - itrader/order_handler/storage/storage_factory.py
    - pyproject.toml
    - itrader/trading_system/live_trading_system.py
    - tests/unit/order/test_order_storage.py
  deleted:
    - itrader/order_handler/storage/postgresql_storage.py
decisions:
  - "D-06: the 'live' arm routes to SqlOrderStorage; NO 'postgresql' arm added"
  - "Factory legacy db_url param replaced with backend: SqlBackend | None (default SqlBackend(SqlSettings.default()) until Phase 4 injects the shared operational backend)"
metrics:
  duration: ~20m
  completed: 2026-06-29
  tasks: 3
  files: 8
---

# Phase 3 Plan 02: Operational SQL Backends — Order Mirror Summary

`SqlOrderStorage` implements the full `OrderStorage` ABC on the shared `SqlBackend` spine via
parameterized SQLAlchemy Core, persisting an `Order` losslessly to Postgres (money as native
`Numeric` → exact `Decimal`) with brackets via a self-referential `parent_order_id` FK and the
audit trail in an `order_state_changes` child table — proven by a testcontainers round-trip
that asserts `obj2 == order` field-wise. The `PostgreSQLOrderStorage` `NotImplementedError`
stub is deleted and the factory `'live'` arm routes to the new backend (D-06).

## What Was Built

- **`models.py` — `build_order_tables(metadata)`** (Task 1): idempotent Core registrar (mirrors
  `results/models.py`) for two tables. `orders` maps every `Order` field except `child_order_ids`
  (D-02 — derived on read), with a nullable/indexed/self-referential `parent_order_id` FK and the
  `ix_orders_portfolio_status` composite index (D-08). `order_state_changes` is the audit child
  table, composite PK `(order_id, seq)`. Money columns are `sqlalchemy.Numeric` (no money
  TypeDecorator, D-13); ids `Uuid`, datetimes `UtcIsoText`, `additional_data` `json_variant()`.

- **`sql_storage.py` — `SqlOrderStorage(OrderStorage)`** (Task 2): composes a `SqlBackend`,
  `create_all(checkfirst=True)`, `dispose()` delegates to `backend.dispose()` (WR-03). All ~14
  ABC methods via parameterized Core (constant `Table`/`Column` + `bindparam`, `.mappings()`
  reads, `engine.begin()` writes — never f-string SQL, T-03-03). `to_row`/`from_row` map every
  field; `state_changes` persist as `seq`-ordered child rows (parent order row inserted first,
  Pitfall 6); `from_row` rebuilds `child_order_ids` from the `parent_order_id` index and reads
  enums back through their constructors (D-07). Every list query carries a stable
  `ORDER BY (created_at, id)` (Pitfall 7); `search_orders` resolves criteria through an
  allow-list of bound columns (T-03-03). Class is quarantined (not re-exported), so the backtest
  import path stays SQL-free (GATE-01 — verified: importing `order_handler` does not load
  `sqlalchemy`).

- **Factory + stub** (Task 2): `OrderStorageFactory.create` `'live'` arm now lazy-imports and
  returns `SqlOrderStorage(SqlBackend)` (D-06, no `'postgresql'` arm); `'backtest'`/`'test'`
  untouched. The `postgresql_storage.py` stub and its `pyproject.toml` mypy override are deleted.

- **`test_sql_order_storage.py`** (Task 3): 6 tests — full Order field-wise round-trip
  (`obj2 == order`, proving the state-change child table), bracket `child_order_ids` rebuilt from
  the FK (T-03-04), exact-`Decimal` money (OPS-04, pg arm only), value-equal UUIDv7, query-helper
  parity (status/active/ticker/history/count), and a backend-free `UtcIsoText` determinism check.
  Postgres arm ran live (Docker present); skips cleanly Dockerless (D-11).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Updated the obsolete `'live'`-arm factory contract test**
- **Found during:** Task 2
- **Issue:** `tests/unit/order/test_order_storage.py::test_create_live_storage_without_db_url`
  asserted the old stub-era behavior (`create("live")` raises `ConfigurationError "Database URL
  is required"`). The plan-mandated factory change makes `'live'` return a `SqlOrderStorage`, so
  the old assertion would fail the full suite.
- **Fix:** Renamed/rewrote the test to `test_create_live_storage_returns_sql_backend` — asserts
  `create("live")` returns a `SqlOrderStorage` and disposes it (WR-03 / Pitfall 4 to avoid a
  ResourceWarning under `filterwarnings=["error"]`).
- **Files modified:** `tests/unit/order/test_order_storage.py`
- **Commit:** 345a924

**2. [Rule 3 — Blocking] Fixed the live caller's stale positional `db_url` argument**
- **Found during:** Task 2
- **Issue:** `live_trading_system.py` called `OrderStorageFactory.create('live', _SYSTEM_DB_URL)`
  — passing a `str` where the new signature expects a `SqlBackend | None`. (Inert in tests:
  `SYSTEM_DB_URL` is unset, so the `'backtest'` branch is taken; module is under the mypy D-live
  override.) Left as-is it is a latent runtime bug if `SYSTEM_DB_URL` were set.
- **Fix:** Call `OrderStorageFactory.create('live')` (drop the stale URL arg — the spine is
  selected via `SqlSettings`, not a raw URL). Phase 4 wires the shared operational `SqlBackend`
  at the live composition root; the defensive `NotImplementedError` catch is retained but no
  longer triggers.
- **Files modified:** `itrader/trading_system/live_trading_system.py`
- **Commit:** 345a924

## Verification

- `poetry run pytest tests/integration/storage/test_sql_order_storage.py -x` — 6 passed (Postgres).
- `poetry run mypy itrader` — clean, 179 source files (new modules in strict scope; `postgresql_storage` override removed).
- GATE-01: `tests/integration/test_backtest_oracle.py` — 3 passed, byte-exact 134 / 46189.87730727451; backtest `order_handler` import does NOT load `sqlalchemy` (SQL-free hot path preserved).
- Full suite `poetry run pytest tests` — **1418 passed**, zero warnings under `filterwarnings=["error"]`.

## Notes for Downstream

- The factory `'live'` arm builds a default `SqlBackend(SqlSettings.default())` (in-process
  SQLite) when no backend is injected — a placeholder until **Phase 4** wires the shared
  operational Postgres `SqlBackend` at the live composition root (D-06 / research §Factory wiring).
- `state_changes.additional_data` is persisted as-is via `json_variant()`. Fill-generated
  changes (`Order.add_fill`) populate `additional_data` with `Decimal`/isoformat values; the
  round-trip tests use clean transitions (`additional_data=None`). Persisting `Decimal`-bearing
  `additional_data` would need JSON-safe coercion — out of scope here (no such path is exercised
  on the operational store yet).
- GATE-02 (cross-backend substrate) remains the recurring milestone gate; this plan exercises the
  Postgres arm of the established `pg_backend` fixture.

## Self-Check: PASSED

- Created files exist: `models.py`, `sql_storage.py`, `test_sql_order_storage.py`, `03-02-SUMMARY.md`.
- Stub deleted: `postgresql_storage.py` no longer exists.
- Commits exist: `5d52729` (Task 1), `345a924` (Task 2), `53366a8` (Task 3).
