---
phase: 03-operational-sql-backends-2-store-layer
plan: 01
subsystem: database
tags: [sqlalchemy, postgres, testcontainers, alembic, naming-convention, pytest-fixtures]

# Dependency graph
requires:
  - phase: 01-sql-spine-security-hardening
    provides: SqlBackend (Engine + MetaData spine), SqlSettings (driver-by-config + verbatim-URL escape hatch), session-scoped pg_engine testcontainers fixture
provides:
  - "NAMING_CONVENTION module constant on itrader/storage/backend.py — single source of truth for deterministic constraint/index names (test-path create_all == deploy-path Alembic autogenerate)"
  - "SqlBackend.metadata now constructed with MetaData(naming_convention=NAMING_CONVENTION)"
  - "pg_backend test fixture — function-scoped SqlBackend bound to the session pg_engine Postgres DB (Wave-2 operational round-trip substrate)"
affects: [03-02-order-mirror, 03-03-portfolio-state, 03-04-signal-storage, 03-05-alembic-autogenerate-migration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQLAlchemy naming_convention applied to the spine MetaData so autogenerate is deterministic (research Pitfall 5 / A5)"
    - "Container-reuse test fixture: wrap the session pg_engine container URL via the SqlSettings verbatim-URL escape hatch instead of spinning a second container"

key-files:
  created: []
  modified:
    - itrader/storage/backend.py
    - tests/integration/storage/conftest.py

key-decisions:
  - "pg_backend reuses the session-scoped pg_engine container (renders its URL with hide_password=False, wraps in SecretStr) rather than spinning a second container — one container per session, a fresh Engine per test bound to the same DB."
  - "Imports (pydantic SecretStr, SqlSettings/SqlDriver, SqlBackend) deferred into the pg_backend body, mirroring pg_engine, so --collect-only stays import-light and Dockerless runs skip transitively via pg_engine (D-11)."

patterns-established:
  - "NAMING_CONVENTION as the single importable source of truth: Plan-05 env.py imports it for the autogen MetaData."
  - "pg_backend disposes its backend in a finally (WR-03 / Pitfall 4) so an undisposed engine never trips a ResourceWarning under filterwarnings=[error]."

requirements-completed: [GATE-02]

# Metrics
duration: 6min
completed: 2026-06-29
---

# Phase 3 Plan 01: Wave-2 Foundations (pg_backend fixture + spine NAMING_CONVENTION) Summary

**Stable SQLAlchemy NAMING_CONVENTION on the spine MetaData (deterministic autogenerate) plus a container-reusing `pg_backend` fixture that hands each Wave-2 operational round-trip test a Postgres-bound `SqlBackend`.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-29
- **Completed:** 2026-06-29
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added module-level `NAMING_CONVENTION: dict[str, str]` (SQLAlchemy-standard `ix`/`uq`/`ck`/`fk`/`pk`) to `itrader/storage/backend.py` and applied it via `MetaData(naming_convention=NAMING_CONVENTION)` — constraint/index names are now explicit and deterministic for every `create_all` consumer AND Plan-05 Alembic `--autogenerate` (research Pitfall 5 / A5).
- Added a function-scoped `pg_backend` fixture to `tests/integration/storage/conftest.py` yielding a `SqlBackend` bound to the SAME database as the session-scoped `pg_engine` container, via the `SqlSettings` verbatim-URL escape hatch — the GATE-02 substrate the three Phase-3 operational round-trip files build on.
- Verified GATE-01 inertness held: SMA_MACD backtest oracle byte-exact, `mypy --strict` clean, storage suite green (PG arm ran).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add NAMING_CONVENTION to the spine MetaData** - `83c159b` (feat)
2. **Task 2: Add the pg_backend fixture to the storage conftest** - `4eaccc6` (test)

## Files Created/Modified
- `itrader/storage/backend.py` - Added the `NAMING_CONVENTION` constant; `SqlBackend.metadata` now `MetaData(naming_convention=NAMING_CONVENTION)`.
- `tests/integration/storage/conftest.py` - Added the `pg_backend` fixture (and documented it in the module docstring).

## Decisions Made
- **Container reuse over a second container:** `pg_backend` resolves `pg_engine`, renders its URL with `hide_password=False`, wraps it in `SecretStr`, and constructs `SqlSettings(driver=POSTGRESQL_PSYCOPG2, url=...)` so the verbatim-URL escape hatch binds a fresh Engine to the SAME database — no second container is spun (research Open Q2, option 1).
- **Deferred imports in the fixture body** mirror `pg_engine` so `--collect-only` stays import-light and a Dockerless run skips transitively through `pg_engine` (D-11). The backend is disposed in a `finally` (WR-03 / Pitfall 4).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `pg_backend` is available to the Wave-2 operational round-trip test files (order mirror, portfolio state, signal storage).
- `NAMING_CONVENTION` is exported and importable for Plan-05's Alembic `env.py` autogen MetaData.
- GATE-02 remains a recurring (substrate-only) gate; the operational round-trips that flip it land in subsequent Wave-2 plans.

## Self-Check: PASSED

- FOUND: itrader/storage/backend.py
- FOUND: tests/integration/storage/conftest.py
- FOUND: .planning/phases/03-operational-sql-backends-2-store-layer/03-01-SUMMARY.md
- FOUND: commit 83c159b (Task 1)
- FOUND: commit 4eaccc6 (Task 2)

---
*Phase: 03-operational-sql-backends-2-store-layer*
*Completed: 2026-06-29*
