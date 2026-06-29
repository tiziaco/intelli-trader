---
phase: 03-operational-sql-backends-2-store-layer
plan: 04
subsystem: database
tags: [sqlalchemy, postgres, signal-store, numeric, testcontainers, msgspec]

# Dependency graph
requires:
  - phase: 01-sql-spine-security-hardening
    provides: SqlBackend + storage/types (Uuid, UtcIsoText, json_variant); SqlSettings
  - phase: 03 (03-01)
    provides: pg_backend testcontainers Postgres fixture (tests/integration/storage/conftest.py)
provides:
  - SqlSignalStorage — strategy/signal operational backend on the shared SQL spine (OPS-03)
  - build_signal_tables — the signals table (indexed strategy_id/ticker, money Numeric, config json_variant)
  - SignalStorageFactory 'live' arm routes to SqlSignalStorage (lazy import, D-06)
  - Postgres round-trip + filter-isolation + money-exactness + config-dict test suite
affects: [retention-live-write-through, live-trading]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sql<Concern>Storage composes SqlBackend (has-a, no god base); parameterized Core (bindparam, no f-string SQL)"
    - "Operational money = Postgres-native Numeric, exact Decimal round-trip (OPS-04); money never touches SQLite (Pitfall 2)"
    - "Factory 'live' arm SQL imports are lazy (inside the branch) — GATE-01 inertness on the backtest import path"
    - "Round-trip tests use unique strategy_id/ticker + indexed filter queries to stay isolated on a shared Postgres DB"

key-files:
  created:
    - itrader/strategy_handler/storage/models.py
    - itrader/strategy_handler/storage/sql_storage.py
    - tests/integration/storage/test_sql_signal_storage.py
  modified:
    - itrader/strategy_handler/storage/storage_factory.py

key-decisions:
  - "ORDER BY (time, signal_id) is the stable insertion key for get_all/by_strategy/by_ticker — UUIDv7 signal_id is monotonic in generation, deterministic across dialects"
  - "Factory live arm accepts an optional injected backend; falls back to SqlBackend(SqlSettings.default()) when none passed (real Postgres backend injected by the live composition root in a later phase)"
  - "config round-trips as a decoded dict (value equality), NOT JSON byte identity (Pitfall 8 / A6)"

patterns-established:
  - "Money codec: nullable Numeric columns coerced back via a _as_decimal(None|value) helper -> Decimal | None"
  - "Enum persistence: action/order_type stored as .value String, parsed back via Side(value) / order_type_map"

requirements-completed: [OPS-03, OPS-04, GATE-01, GATE-02]

# Metrics
duration: 12min
completed: 2026-06-29
---

# Phase 3 Plan 04: SqlSignalStorage (operational signal store) Summary

**SqlSignalStorage — the strategy/signal operational backend on the shared SQL spine: a single indexed `signals` table with Postgres-native `Numeric` money and a `config` json_variant, validated by a 6-test testcontainers Postgres round-trip with filter isolation and exact-Decimal money.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-29
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- `build_signal_tables(metadata)` registers the `signals` table on the shared spine — `signal_id` PK (Uuid), indexed `strategy_id`/`ticker` (the `by_strategy`/`by_ticker` filters), `time` as `UtcIsoText` business-time, money fields as Postgres-native `Numeric`, and the one allowed `config` json_variant column (mirrors `runs.settings`, D-01).
- `SqlSignalStorage(SignalStore)` implements all 4 ABC methods over parameterized SQLAlchemy Core (`bindparam` against constant `Table`/`Column` — no f-string SQL, SEC-01/T-03-13); composes `SqlBackend`, idempotent `create_all(checkfirst=True)`, `dispose()` delegates to the backend.
- `SignalStorageFactory` `'live'` arm rewritten to return `SqlSignalStorage` via lazy imports (D-06 quarantine); `'backtest'`/`'test'` untouched on `InMemorySignalStore`; no `'postgresql'` arm.
- 6 Postgres round-trip tests green on the live testcontainers arm: full field-equal round-trip (incl. config decoded-dict), `by_strategy`/`by_ticker` filter isolation, exact-Decimal money, nullable-money→None, stable insertion ORDER BY, value-equal UUID `signal_id`.

## Task Commits

1. **Task 1: build_signal_tables + SqlSignalStorage backend + factory 'live' arm** — `14a451c` (feat)
2. **Task 2: Postgres round-trip + filter + config-dict + money tests** — `5e7b7f6` (test)

## Files Created/Modified
- `itrader/strategy_handler/storage/models.py` - `build_signal_tables(metadata)` registering the `signals` table (idempotent, indexed strategy_id/ticker, money Numeric, config json_variant).
- `itrader/strategy_handler/storage/sql_storage.py` - `SqlSignalStorage(SignalStore)` — composition + create_all + to_row/from_row + parameterized Core with indexed WHERE filters.
- `itrader/strategy_handler/storage/storage_factory.py` - `'live'` arm routes to `SqlSignalStorage` (lazy import, optional injected backend); backtest/test arms unchanged.
- `tests/integration/storage/test_sql_signal_storage.py` - round-trip + filter-isolation + config-dict + money-exactness tests over the `pg_backend` fixture.

## Decisions Made
- **Stable ORDER BY (time, signal_id):** insertion-order contract is honored deterministically across dialects via the time column then the monotonic UUIDv7 signal_id tiebreak.
- **Factory backend injection:** the `'live'` arm takes an optional `backend` param and falls back to `SqlBackend(SqlSettings.default())` (per plan); the real Postgres backend is injected by the live composition root in a later phase. Lazy SQL imports keep the backtest factory import SQL-free (verified: `sqlalchemy` not in `sys.modules` after importing the factory).
- **Test isolation on a shared DB:** the function-scoped `pg_backend` binds to the same Postgres database across tests, so each test uses fresh unique `strategy_id`/`ticker` values and asserts through the indexed filter queries rather than a table-wide `get_all`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The shared (function-scoped) `pg_backend` binds to one persistent Postgres database, so a naive `get_all` assertion would see sibling tests' rows. Resolved by scoping every assertion to unique per-test `strategy_id`/`ticker` values through the `by_strategy`/`by_ticker` filters (which exercise the same ORDER BY as `get_all`).

## Verification
- `poetry run pytest tests/integration/storage/test_sql_signal_storage.py -x -q` → 6 passed (live Postgres arm, Docker present).
- `poetry run mypy itrader` → Success, no issues in 180 source files (SqlSignalStorage in strict scope).
- GATE-01: `tests/integration/test_backtest_oracle.py` → 3 passed (oracle byte-exact 134 / 46189.87730727451; backtest signal path still on InMemorySignalStore, no SQL import).
- Storage + strategy subsets (`tests/integration/storage/`, `tests/unit/strategy/`) → 141 passed under `filterwarnings=["error"]`.

## User Setup Required
None - no external service configuration required (tests use ephemeral testcontainers Postgres; skip cleanly when Docker is absent).

## Next Phase Readiness
- OPS-03 closed and OPS-04 (the cross-cutting money contract) proven on the third operational backend.
- Phase 4 (Retention + Live Write-Through) can compose `SqlSignalStorage` via the factory `'live'` arm or by injecting a Postgres `SqlBackend`.

## Self-Check: PASSED

All created files exist on disk; both task commits (`14a451c`, `5e7b7f6`) present in git history.

---
*Phase: 03-operational-sql-backends-2-store-layer*
*Completed: 2026-06-29*
