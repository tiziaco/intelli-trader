---
phase: 01-sql-spine-security-hardening
plan: 02
subsystem: database
tags: [sqlalchemy, sqlite, postgres, uuidv7, pydantic, secretstr, typedecorator, spine]

# Dependency graph
requires:
  - phase: 01-01
    provides: "GATE-02 cross-backend test substrate (session-scoped testcontainers pg_engine + indirect sqlite/postgres engine fixtures) — consumed by 01-03, not by this plan"
provides:
  - "itrader/storage/ spine package — SqlBackend (Engine + MetaData, no business logic, composed not inherited; no SqlStorageBase god base)"
  - "itrader/storage/types.py — UtcIsoText TypeDecorator (deterministic UTC-isoformat business-time), json_variant() (JSON/JSONB), Uuid(as_uuid=True) re-export; NO money TypeDecorator (D-13)"
  - "itrader/config/sql.py — SqlSettings driver-by-config selector (SqlDriver enum incl. unwired SQLITE_LIBSQL Turso slot) with lazy SecretStr cred resolution on the Postgres arm only"
  - "barrel storage/__init__ re-exporting the public spine surface, env-free and quarantining sql_store"
affects: [01-03-spine03-roundtrip, 01-04-alembic-skeleton, 01-05-fl06-hardening, phase-02-results-store, phase-03-operational-sql-backends, GATE-02]

# Tech tracking
tech-stack:
  added: []  # assembly of already-present SQLAlchemy 2.0.50 + pydantic primitives — no new dependency
  patterns: [composition-spine (has-a SqlBackend, no god base), cross-dialect TypeDecorator (UtcIsoText), driver-by-config SqlSettings with lazy SecretStr resolution, JSON().with_variant(JSONB) portable column]

key-files:
  created:
    - itrader/storage/__init__.py
    - itrader/storage/types.py
    - itrader/storage/backend.py
    - itrader/config/sql.py
    - tests/unit/storage/__init__.py
    - tests/unit/storage/test_types.py
    - tests/unit/storage/test_sql_settings.py
    - tests/unit/storage/test_sql_backend.py
  modified: []

key-decisions:
  - "Business-time encoded as ISO-8601 UTC TEXT via UtcIsoText (D-04/D-05) — instant-preserving, UTC-normalized, byte-identical across runs; verified instant-equal round-trip on in-process SQLite"
  - "Uuid(as_uuid=True) used directly at columns (re-exported from types.py) — CHAR(32) on SQLite, native UUID on PG, value-equal; no hand-rolled per-dialect switch (D-03), no second ID scheme"
  - "SqlSettings.engine_url() resolves Postgres creds lazily via Settings.database_url.get_secret_value() ONLY on the PG arm; Settings() is never instantiated at import (Pitfall 8 / T-01-04) so the SQLite/backtest path stays env-free"
  - "No DecimalAsText / money type and no sqlalchemy-libsql driver shipped (D-13/D-15); SQLITE_LIBSQL is an enum slot only — escape path is one URL change, zero code"
  - "Only SPINE-01 marked complete; SPINE-02 (all four Sql<Concern>Storage + ResultsStore ABC), SPINE-03 (cross-backend SQLite+Postgres round-trip) and GATE-02 (recurring) span later plans/phases — left Pending"

patterns-established:
  - "Composition spine: a concrete store holds a SqlBackend by reference (has-a) and registers Tables on backend.metadata; there is deliberately no SqlStorageBase to inherit (SPINE-02 / D-01)"
  - "Cross-dialect TypeDecorator (UtcIsoText) with cache_ok=True + typed process_* signatures — the strict-clean template for future spine types"
  - "Driver-by-config SqlSettings (BaseModel + ConfigDict(extra='forbid') + default()) with a (str, Enum) driver enum and lazy SecretStr resolution — the config-not-code backend switch consumed by Phases 2-3"
  - "Clean-env subprocess import probe to prove a module never instantiates Settings() at import (reusable lazy-resolution assertion)"

requirements-completed: [SPINE-01]  # SPINE-02/03 + GATE-02 span later plans/phases — see ## Requirements

# Metrics
duration: 8min
completed: 2026-06-27
---

# Phase 01 Plan 02: SQL Spine Core Summary

**Shipped the `itrader/storage/` composition spine — a `SqlBackend` (Engine + MetaData, no god base), cross-dialect `types.py` helpers (deterministic `UtcIsoText` business-time, `json_variant()`, direct `Uuid(as_uuid=True)`, no money type), and a `config/sql.py` `SqlSettings` driver-by-config selector with lazy `SecretStr` cred resolution and a Turso-ready libSQL slot — all mypy --strict clean and oracle-inert.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-27T17:12:30Z
- **Completed:** 2026-06-27T17:20:59Z
- **Tasks:** 3 (all TDD: RED test commit → GREEN feat commit)
- **Files modified:** 8 (all created)

## Accomplishments
- Built `storage/types.py`: a `UtcIsoText` TypeDecorator that normalizes any aware datetime to UTC and emits `datetime.isoformat()` — deterministic byte-identical bind, instant-equal round-trip through in-process SQLite (incl. a `+01:00` input normalized to `+00:00`); plus `json_variant()` (JSON on sqlite, JSONB on postgresql) and a direct `Uuid(as_uuid=True)` re-export (CHAR(32)/native-UUID, value-equal). NO money/Decimal-as-text type (D-13).
- Built `config/sql.py`: a `SqlDriver(str, Enum)` with exactly three members (SQLITE_PYSQLITE default, POSTGRESQL_PSYCOPG2, the unwired SQLITE_LIBSQL Turso slot) and a `SqlSettings(BaseModel, extra='forbid')` whose `engine_url()` builds a local URL env-free on the SQLite arm and resolves Postgres creds lazily via `Settings.database_url.get_secret_value()` — `Settings()` is never constructed at import (Pitfall 8).
- Built `storage/backend.py` + barrel: `SqlBackend` is a pure Engine+MetaData holder with no public methods and no `SqlStorageBase` god base; a throwaway `_DemoStore` composes it (has-a) and round-trips a UUIDv7. The barrel re-exports the public surface, imports env-free, and quarantines `sql_store`.
- 16 new unit tests green under `filterwarnings=["error"]`; `mypy --strict` clean over `itrader/storage` + `itrader/config/sql.py`; GATE-01 oracle byte-exact (3 oracle tests pass — the spine adds zero per-tick code).

## Task Commits

Each task followed the TDD RED→GREEN cycle (two commits per task):

1. **Task 1: storage/types.py cross-dialect helpers** — `7180881` (test, RED) → `a89632d` (feat, GREEN)
2. **Task 2: config/sql.py SqlSettings** — `2ad6a91` (test, RED) → `63e99ff` (feat, GREEN)
3. **Task 3: storage/backend.py SqlBackend + barrel** — `ff0ad45` (test, RED) → `f78884c` (feat, GREEN)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified
- `itrader/storage/types.py` - `UtcIsoText` TypeDecorator (deterministic UTC-isoformat business-time), `json_variant()`, `Uuid`/`UuidType` re-export; no money type (D-13)
- `itrader/storage/backend.py` - `SqlBackend` = `create_engine(SqlSettings.engine_url())` + fresh `MetaData`; no business logic, no god base
- `itrader/storage/__init__.py` - spine barrel re-exporting `SqlBackend` + the type helpers; quarantines `sql_store`
- `itrader/config/sql.py` - `SqlDriver` enum + `SqlSettings` driver-by-config selector; lazy `SecretStr` Postgres cred resolution
- `tests/unit/storage/__init__.py` - package marker
- `tests/unit/storage/test_types.py` - 6 tests: UtcIsoText determinism + instant-equal round-trip, json_variant/Uuid compile, no money type
- `tests/unit/storage/test_sql_settings.py` - 6 tests: default arm env-free, three-member enum incl. libsql slot, PG-arm unmasked-secret resolution, lazy import probe, extra-forbid
- `tests/unit/storage/test_sql_backend.py` - 4 tests: engine+metadata/no-business-logic, composition-no-god-base round-trip, barrel re-export, env-free quarantined import

## Decisions Made
- **ISO-8601 UTC text for business-time (D-04/D-05).** `UtcIsoText` stores `value.astimezone(timezone.utc).isoformat()` — legible, sortable as TEXT, microsecond-lossless for the engine's tz-aware datetime; verified deterministic (identical bytes across two binds) and instant-equal on read.
- **`Uuid(as_uuid=True)` used directly, re-exported from `types.py`.** No custom per-dialect encoder; the built-in is value-equal across SQLite/PG (D-03) and preserves the single-UUIDv7 scheme (no Integer PK / autoincrement, T-01-06).
- **Lazy PG cred resolution, env-free SQLite arm (Pitfall 8 / T-01-04).** `engine_url()` only touches `Settings()` on the Postgres arm; the SQLite/backtest default never reads the env, so an unset `ITRADER_DATABASE_URL` cannot break import.
- **Composition, never inheritance (SPINE-02 / D-01).** `SqlBackend` defines no public methods; stores compose it. Tests assert no `SqlStorageBase` symbol exists.
- **No money type, no libSQL driver (D-13/D-15).** `types.py` carries no `DecimalAsText`/`Numeric`; `SQLITE_LIBSQL` is a slot only — the `sqlalchemy-libsql` package is not added.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created `itrader/storage/__init__.py` package marker in Task 1 (plan assigns the barrel to Task 3)**
- **Found during:** Task 1 (storage/types.py)
- **Issue:** Task 1's test imports `from itrader.storage import types`, which requires `itrader/storage/` to be an importable package. The full barrel (re-exporting `SqlBackend`) is Task 3's deliverable, but `SqlBackend` does not exist yet in Task 1 — so the barrel cannot be created in full up front, and relying on an implicit namespace package under the regular `itrader` package is fragile.
- **Fix:** Created a minimal docstring-only `storage/__init__.py` package marker in Task 1, then expanded it into the full re-exporting barrel in Task 3 (committed `f78884c`).
- **Files modified:** itrader/storage/__init__.py
- **Verification:** Task 1 tests import the package and pass; Task 3 barrel re-export test passes.
- **Committed in:** `a89632d` (Task 1 marker), `f78884c` (Task 3 barrel)

**2. [Rule 1 - Bug] Reworded `types.py`/`config/sql.py` docstrings off the literal D-13/D-15 grep tokens**
- **Found during:** Task 1 (D-13 gate) and Task 2 (D-15 gate)
- **Issue:** My explanatory docstrings literally contained the tokens `DecimalAsText`/`Numeric` (types.py) and `sqlalchemy-libsql` (config/sql.py) to explain *why those are absent*. That tripped the phase-wide acceptance gates `! grep -rn 'DecimalAsText' itrader/` and `! grep -rn 'sqlalchemy-libsql' itrader/`, which assert the literal strings appear nowhere.
- **Fix:** Reworded the docstrings to convey the same intent without the forbidden literals ("no money / Decimal-as-text TypeDecorator"; "the libSQL driver is NOT added").
- **Files modified:** itrader/storage/types.py, itrader/config/sql.py
- **Verification:** `grep -rn 'DecimalAsText' itrader/` and `grep -rn 'sqlalchemy_libsql\|sqlalchemy-libsql' itrader/` both return nothing.
- **Committed in:** `a89632d` (types.py), `63e99ff` (config/sql.py)

**3. [Rule 1 - Bug] Replaced a flaky `importlib.reload` lazy-import test with a clean-env subprocess probe**
- **Found during:** Task 2 (lazy-resolution test)
- **Issue:** The first draft proved "import does not instantiate Settings()" via `importlib.reload`, which failed with `ImportError: cannot import name 'sql' from '<unknown module name>'` — a known reload quirk for submodules, not a defect in the code under test.
- **Fix:** Swapped to a subprocess that imports `itrader.config.sql` in a fresh interpreter with `ITRADER_DATABASE_URL` stripped; a clean exit proves lazy, env-free import (a module-body `Settings()` would `ValidationError` → non-zero exit).
- **Files modified:** tests/unit/storage/test_sql_settings.py
- **Verification:** Test passes; the subprocess returns 0 and prints `imported-ok`.
- **Committed in:** `63e99ff` (Task 2 GREEN commit)

**4. [Rule 3 - Blocking] Narrow `# type: ignore[call-arg]` at the pydantic-settings `Settings()` boundary**
- **Found during:** Task 2 (mypy --strict)
- **Issue:** `database_url` is a required-no-default field, so pydantic v2's `dataclass_transform` makes mypy treat `Settings()` as missing a required ctor arg — even though `BaseSettings` populates it from the env at runtime. `mypy --strict` (GATE-02) failed with `[call-arg]`.
- **Fix:** Added a narrow, documented `# type: ignore[call-arg]` at the single lazy `Settings()` construction (anticipated by RESEARCH.md A3 as a pydantic-settings boundary friction). No broad ignore, no override-block change.
- **Files modified:** itrader/config/sql.py
- **Verification:** `poetry run mypy itrader/config/sql.py` and `mypy itrader/storage` clean.
- **Committed in:** `63e99ff` (Task 2 GREEN commit)

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bugs, 2 Rule 3 blocking)
**Impact on plan:** All four were necessary to satisfy the plan's own acceptance gates (package importability, D-13/D-15 greps, lazy-import proof, GATE-02 mypy). No scope creep — every change stays within the three planned files plus their tests.

## Issues Encountered
- The in-process `sqlite+pysqlite:///:memory:` engine persists tables across `engine.begin()`/`engine.connect()` calls within a thread (SingletonThreadPool), so the composition round-trip test works without a shared connection — confirmed empirically before writing the tests.

## Requirements

**SPINE-01 — COMPLETE.** A single `SqlBackend` + `SqlSettings` selects the SQL driver by config, not code (SQLite default / Postgres operational arm), with a Turso-ready `SQLITE_LIBSQL` slot and the `sqlalchemy-libsql` driver NOT added — exactly the SPINE-01 surface. Marked complete in REQUIREMENTS.md.

**SPINE-02 — Pending (structural half established).** This plan ships the composable `SqlBackend` and proves "no cross-concern god base", but the requirement's full body ("the three existing ABCs plus a new `ResultsStore` ABC each implemented by exactly one `Sql<Concern>Storage` that composes the spine") requires the concrete storage classes + the `ResultsStore` ABC, which land in Phases 2-3. Left Pending.

**SPINE-03 — Pending (encoding half established).** `types.py` proves the UUIDv7 + business-time encoding round-trips losslessly + equal on in-process SQLite (unit tests). The requirement demands the round-trip "on both SQLite and Postgres" — the cross-backend parity test on the testcontainers Postgres substrate is plan 01-03's deliverable. Left Pending.

**GATE-02 — Pending (recurring, bound to Phase 1).** The "new persistence code is `mypy --strict` clean + suite green under `filterwarnings=['error']`" half is satisfied for this plan's code, but the "DB round-trip + restart-rehydration tests on the right substrate" half spans 01-03 and later phases. Consistent with the 01-01 decision, GATE-02 stays Pending until the milestone-wide criteria are met.

## User Setup Required
None - no external service configuration required. The spine defaults to in-process SQLite and reads no environment on the backtest path.

## Self-Check: PASSED
- FOUND: itrader/storage/__init__.py, itrader/storage/types.py, itrader/storage/backend.py, itrader/config/sql.py
- FOUND: tests/unit/storage/{__init__,test_types,test_sql_settings,test_sql_backend}.py
- FOUND commits: 7180881, a89632d (Task 1); 2ad6a91, 63e99ff (Task 2); ff0ad45, f78884c (Task 3)
- 16 storage unit tests pass; mypy --strict clean over itrader/storage + itrader/config/sql.py
- GATE-01 oracle byte-exact (3 oracle tests pass); D-13/D-15 phase-wide greps clean
- No tracked-file deletions; working tree clean

## Next Phase Readiness
- The spine is ready for 01-03 (SPINE-03 cross-backend round-trip): consume `SqlBackend` + `UtcIsoText` + `Uuid` against the `engine`/`pg_engine` fixtures from 01-01 (`@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)`).
- 01-04 (Alembic skeleton) can target `SqlBackend.metadata`; 01-05 (FL-06 `SqlHandler` rework) composes `SqlBackend` as the 5th consumer and reuses `UtcIsoText` for the `prices.date` column.
- No blockers. GATE-01 oracle byte-exact; spine is structurally inert on the hot path.

---
*Phase: 01-sql-spine-security-hardening*
*Completed: 2026-06-27*
