---
phase: 01-sql-spine-security-hardening
verified: 2026-06-27T00:00:00Z
status: passed
score: 5/5
overrides_applied: 0
---

# Phase 01: SQL Spine + Security Hardening — Verification Report

**Phase Goal:** One config-selected SQL backend (SQLite research store + Postgres operational store)
exists as the shared spine that every store composes, credentials are sourced from secrets, and UUIDv7
ids + business-time timestamps round-trip losslessly across both dialects — the hard dependency root
nothing else compiles without.
**Verified:** 2026-06-27
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Config-selected `SqlBackend`/`SqlSettings`; single SqlBackend composed not inherited; no cross-concern god base; ResultsStore ABC as 4th concern; Turso slot present, libsql driver NOT installed (SPINE-01/02 Phase-1 substrate) | VERIFIED | `itrader/config/sql.py` SqlDriver has 3 members incl. `SQLITE_LIBSQL = "sqlite+libsql"`; `itrader/storage/backend.py` SqlBackend is pure Engine+MetaData; `test_concrete_store_composes_backend_without_god_base` asserts has-a not is-a; `itrader/results/base.py` ResultsStore ABC exists; no SqlStorageBase anywhere in itrader/storage/; no sqlalchemy-libsql in pyproject.toml |
| 2 | UUIDv7 id + business-time timestamp round-trip lossless and equal on both SQLite AND Postgres; deterministic bytes; single scheme; no wall-clock; no DB autoincrement (SPINE-03) | VERIFIED | `test_uuid_and_business_time_lossless_and_equal[sqlite]` PASSED; `test_uuid_and_business_time_lossless_and_equal[postgres]` PASSED (Docker available, testcontainers PG ran); `test_business_time_encoding_determinism` PASSED; all 3 via `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -v` |
| 3 | `SqlHandler` sources creds from `Settings.database_url` (SecretStr); single `prices` table with parameterized queries; no hardcoded creds; no f-string DDL; no symbol-as-table-name (SEC-01 / FL-06) | VERIFIED | `grep -rIn "user:pass@\|:1234@" itrader/` → 0 matches; `grep -rIn "text(f'" itrader/` → 0 matches; `bindparam` used on all symbol reads/writes/deletes; `SqlBackend` composed; 7 unit tests in `test_sql_handler.py` pass incl. FL-06 grep-gate tests |
| 4 | Live Postgres store has Alembic skeleton (`render_as_batch=True` in both paths, empty `versions/`); research store uses `create_all()` with no `alembic_version` table (MIG-01) | VERIFIED | `alembic.ini` `script_location = itrader/storage/migrations`; `sqlalchemy.url =` blank (no cred); `render_as_batch=True` on lines 71 and 92 of `env.py`; `versions/` contains only `.gitkeep`; `test_research_store_create_all_has_no_alembic_version` PASSED; `test_alembic_chain_creates_alembic_version_sqlite` PASSED; `test_alembic_chain_creates_alembic_version_postgres` PASSED |
| 5 | New spine code `mypy --strict` clean; full suite green under `filterwarnings=["error"]`; no new broad ignore; SMA_MACD oracle byte-exact 134 / `46189.87730727451` (GATE-02 Phase-1 substrate + GATE-01 recurring) | VERIFIED | `poetry run mypy itrader/storage itrader/config/sql.py itrader/results itrader/price_handler/store/sql_store.py` → "Success: no issues found in 8 source files"; `itrader.price_handler.store.sql_store` removed from D-sql `ignore_errors` override in `pyproject.toml`; `poetry run pytest tests -q` → 1373 passed; oracle 3/3 PASSED |

**Score:** 5/5 truths verified

---

## Scope Note: SPINE-02 and GATE-02 as Multi-Phase Gates

SPINE-02 and GATE-02 are recurring milestone-wide gates. Phase 1 delivers their binding substrate:

- **SPINE-02**: The composition architecture is established (no god base, SqlBackend composable, ResultsStore ABC as the 4th seam). The concrete `Sql<Concern>Storage` implementations for `OrderStorage`, `PortfolioStateStorage`, and `SignalStore` are Phase-3 deliverables; `SqlResultsStore` is Phase-2. REQUIREMENTS.md explicitly marks SPINE-02 "Pending" for Phase 1 while SPINE-01/03/SEC-01/MIG-01 are "Complete." This is a documented multi-phase gate, not an omission.

- **GATE-02**: Phase 1 establishes the DB round-trip substrate (in-process SQLite + testcontainers Postgres engine fixtures) and proves mypy --strict + filterwarnings clean for all new Phase-1 code. Restart-rehydration tests (the other half of GATE-02) are a Phase-3/4 deliverable. The Pending status is consistent and defensible.

The Phase 1 goal is "the spine + hardening foundation, not the full multi-store persistence" — the deliverables above fully satisfy that scope.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/storage/types.py` | UtcIsoText + json_variant + Uuid; NO DecimalAsText | VERIFIED | 63 lines; `class UtcIsoText(TypeDecorator[datetime])`; `cache_ok = True`; `json_variant()` returns `JSON().with_variant(JSONB(), "postgresql")`; no DecimalAsText |
| `itrader/config/sql.py` | SqlSettings (SqlDriver enum incl. libsql slot + engine_url, lazy Settings) | VERIFIED | `class SqlDriver(str, Enum)` with SQLITE_PYSQLITE / POSTGRESQL_PSYCOPG2 / SQLITE_LIBSQL; `class SqlSettings(BaseModel)` with `engine_url()` resolving PG creds lazily; no Settings() at import |
| `itrader/storage/backend.py` | SqlBackend = Engine + MetaData, no business logic | VERIFIED | `class SqlBackend`: `__init__` sets `self.engine` + `self.metadata`; no query methods; no god base |
| `itrader/storage/__init__.py` | Barrel re-exporting SqlBackend + type helpers; env-free import | VERIFIED | Re-exports SqlBackend, UtcIsoText, Uuid, UuidType, json_variant; `__all__` set; deferred quarantine note preserved |
| `itrader/results/base.py` | ResultsStore(ABC) seam — 4th composable concern | VERIFIED | `class ResultsStore(ABC)` with 4 abstractmethods: `save_run`, `save_artifact`, `get_artifact`, `top_runs` — mapped 1:1 to RESULT-01/02/03 |
| `itrader/price_handler/store/sql_store.py` | Hardened SqlHandler on spine — single prices table, SecretStr creds, parameterized | VERIFIED | 205 lines; composes `SqlBackend`; `prices` Table with `symbol` value column; `bindparam` on all reads/writes/deletes; no `to_sql(symbol)`/`read_sql(symbol)`; `get_secret_value` in docstring (creds via injected backend); quarantine preserved |
| `alembic.ini` | script_location → itrader/storage/migrations; no hardcoded creds | VERIFIED | `script_location = itrader/storage/migrations`; `sqlalchemy.url =` (blank); no `user:pass@` anywhere |
| `itrader/storage/migrations/env.py` | render_as_batch=True in both paths; lazy URL; target_metadata wired | VERIFIED | `render_as_batch=True` on lines 71 and 92 (offline and online); `target_metadata = SqlBackend(SqlSettings.default()).metadata`; `_resolve_url()` resolves lazily inside run functions |
| `itrader/storage/migrations/versions/.gitkeep` | Empty chain — no operational tables yet | VERIFIED | `ls versions/` → empty (no files other than .gitkeep) |
| `tests/integration/storage/conftest.py` | session-scoped pg_engine + Docker-absent skip + indirect engine fixture | VERIFIED | `@pytest.fixture(scope="session") def pg_engine()` with deferred imports inside body; `pytest.skip` on any container failure; `engine` fixture parametrizes "sqlite"/"postgres" |
| `tests/integration/storage/test_spine_roundtrip.py` | SPINE-03 cross-backend round-trip | VERIFIED | 3 tests: `[sqlite]` PASSED, `[postgres]` PASSED (Docker available), determinism PASSED |
| `tests/integration/storage/test_migrations.py` | create_all() vs Alembic distinction | VERIFIED | 3 tests: no alembic_version on create_all(), empty alembic_version on upgrade-head (SQLite), same on Postgres — all PASSED |
| `tests/unit/storage/test_sql_backend.py` | Composition + barrel tests | VERIFIED | 4 tests: engine/metadata exposed, no god base, barrel reexports, env-free import — all PASSED |
| `tests/unit/storage/test_sql_settings.py` | Driver-by-config, lazy creds, libsql slot, extra forbidden | VERIFIED | 6 tests — all PASSED |
| `tests/unit/storage/test_types.py` | UtcIsoText determinism, round-trip, json_variant, Uuid | VERIFIED | 6 tests — all PASSED |
| `tests/unit/results/test_results_store_abc.py` | ResultsStore is ABC; minimal concrete subclass works | VERIFIED | 2 tests — all PASSED |
| `tests/unit/price_handler/test_sql_handler.py` | SEC-01 behavior + FL-06 grep gates | VERIFIED | 7 tests (OHLCV round-trip, single-prices-table, multi-symbol, replace/delete, grep gates) — all PASSED |
| `pyproject.toml` | alembic + testcontainers in dev group; sql_store override removed | VERIFIED | `alembic = "^1.18.5"` on line 43; `testcontainers = {version = "^4.14.2", extras = ["postgresql"]}` on line 44; `itrader.price_handler.store.sql_store` absent from all [[tool.mypy.overrides]] blocks |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/config/sql.py::SqlSettings.engine_url` | `itrader.config.settings.Settings.database_url.get_secret_value()` | lazy resolution on POSTGRESQL_PSYCOPG2 arm only | WIRED | Line 75: `return resolved.database_url.get_secret_value()`; no Settings() at import |
| `itrader/storage/backend.py::SqlBackend.__init__` | `sqlalchemy.create_engine` | `create_engine(settings.engine_url())` | WIRED | Line 29: `self.engine: Engine = create_engine(settings.engine_url())` |
| `itrader/price_handler/store/sql_store.py::SqlHandler` | `itrader.storage.SqlBackend` | constructor injection; backend.engine / backend.metadata | WIRED | Line 50: `from itrader.storage import SqlBackend, UtcIsoText`; line 69: `def __init__(self, backend: SqlBackend)` |
| `itrader/storage/migrations/env.py` | `itrader.storage.SqlBackend` metadata | `target_metadata = SqlBackend(SqlSettings.default()).metadata` | WIRED | Line 47: `target_metadata = SqlBackend(SqlSettings.default()).metadata` |
| `tests/integration/storage/test_spine_roundtrip.py` | `tests/integration/storage/conftest.py::engine` fixture | indirect parametrize over `["sqlite","postgres"]` | WIRED | Line 56: `@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)` |
| `sql_store.py` NOT exported from `price_handler/store/__init__.py` | quarantine preserved | design intent | WIRED | `__init__.py` only mentions quarantine in comment; `SqlHandler` not importable from the package barrel (GATE-01 inertness) |

---

## Data-Flow Trace (Level 4)

The phase delivers storage infrastructure, not rendering components. No dynamic data flows to verify at Level 4 — the artifacts are configuration, type definitions, and database access layer code. The SPINE-03 round-trip tests directly exercise the data path: write → persist → read → assert equal on both dialects.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| UUIDv7 round-trip SQLite | `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k sqlite` | 1 passed | PASS |
| UUIDv7 round-trip Postgres | `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k postgres` | 1 passed | PASS |
| Determinism bytes | `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k determinism` | 1 passed | PASS |
| MIG-01 create_all vs Alembic | `poetry run pytest tests/integration/storage/test_migrations.py -k "not postgres"` | 2 passed | PASS |
| SEC-01 FL-06 grep gates | `poetry run pytest tests/unit/price_handler/test_sql_handler.py` | 7 passed | PASS |
| oracle byte-exact (GATE-01) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | PASS |
| full suite under filterwarnings=error | `poetry run pytest tests -q` | 1373 passed | PASS |
| mypy --strict clean | `poetry run mypy itrader/storage itrader/config/sql.py itrader/results itrader/price_handler/store/sql_store.py` | 0 issues in 8 files | PASS |
| no hardcoded creds repo-wide | `grep -rIn "user:pass@\|:1234@" itrader/` | 0 matches | PASS |
| no f-string in text() | `grep -rIn "text(f'" itrader/` | 0 matches | PASS |
| sqlalchemy.url blank in alembic.ini | `grep "sqlalchemy.url" alembic.ini` | `sqlalchemy.url =` (blank) | PASS |
| sql_store override removed from pyproject.toml | `grep "store.sql_store" pyproject.toml` | 0 matches (only postgresql_storage remains) | PASS |

---

## Probe Execution

No probe scripts declared or applicable for this phase (no `scripts/*/tests/probe-*.sh` pattern). The verification commands in the PLAN were run directly in Step 7b behavioral spot-checks above.

---

## Requirements Coverage

| Requirement | Phase | Source Plans | Status | Evidence |
|-------------|-------|-------------|--------|----------|
| SPINE-01 | Phase 1 | 01-02, 01-05 | SATISFIED (Complete) | SqlSettings/SqlDriver selects backend by config; `engine_url()` returns dialect URL with no code change; 3 driver options incl. Turso slot |
| SPINE-02 | Phase 1 | 01-02, 01-03 | PARTIAL (Pending — multi-phase gate) | Phase 1 substrate: SqlBackend composition architecture (no god base); ResultsStore ABC as 4th seam. Full impls (Sql<Concern>Storage per concern) deferred to Phases 2-3 per roadmap. Pending status is documented and defensible. |
| SPINE-03 | Phase 1 | 01-03 | SATISFIED (Complete) | UUIDv7 + business-time round-trip lossless+equal on SQLite and testcontainers Postgres; determinism test passes; 3 integration tests green |
| SEC-01 | Phase 1 | 01-05 | SATISFIED (Complete) | No hardcoded creds, no f-string DDL, no symbol-as-table-name; FL-06 grep gates green as automated tests |
| MIG-01 | Phase 1 | 01-04 | SATISFIED (Complete) | Alembic skeleton with render_as_batch=True + empty versions/ for live Postgres; create_all() for research store; no alembic_version on research store |
| GATE-01 | Recurring (bound Phase 4) | All 5 plans | SATISFIED (recurring) | Oracle byte-exact 3/3; spine is quarantined (not on backtest import path); 1373 tests green |
| GATE-02 | Phase 1 (bound) + recurring | All 5 plans | PARTIAL (Pending — recurring gate) | Phase 1 binding deliverable: testcontainers Postgres + SQLite fixtures; mypy --strict clean; filterwarnings green. Restart-rehydration half deferred to Phases 3-4. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/price_handler/store/sql_store.py` | 150 | Hardcoded `"Europe/Paris"` timezone literal instead of `TIMEZONE` config constant | WARNING | Accidentally correct (both resolve to "Europe/Paris" under default config). If TIMEZONE becomes runtime-configurable, sql_store silently diverges from CsvPriceStore. Round-trip test does not check index timezone. |
| `itrader/storage/types.py` | 49–52 | `UtcIsoText.process_bind_param` silently coerces naive datetimes via local system time | WARNING | Data-hardening gap at a trust boundary. Convention requires tz-aware business datetimes; current usage is conformant. Not triggered by current tests. |
| `itrader/storage/backend.py` | 28–30 | No `dispose()` method on SqlBackend | WARNING | Lifecycle management gap: callers must reach `backend.engine.dispose()` directly or through SqlHandler.stop_engine(). Ownership hazard if two consumers share a backend. |
| `itrader/results/base.py` | 85 | `top_runs(self, metric: str)` accepts an unconstrained column-name string | WARNING | Pre-injection seam: Phase 2 concrete implementation must use an allow-list or enum for `metric` to avoid ORDER BY injection. The ABC surface is where this should be constrained. |
| `itrader/storage/migrations/env.py` | 47 | Module-level `SqlBackend(SqlSettings.default()).metadata` creates SQLite engine at import time; docstring claim "resolved LAZILY" is inaccurate for the SQLite default arm | WARNING | Inaccurate docstring. The discarded Engine is never disposed (potential ResourceWarning under PYTHONWARNINGFLAGS=d). The Postgres credential arm IS lazy as claimed. |
| `tests/unit/price_handler/test_sql_handler.py` | 137–145 | FL-06 grep gate patterns `["user:pass@", ":1234@"]` are too narrow | WARNING | Would miss credentials like `postgres:password@localhost` or `admin:secret@`. Existing codebase is clean; the gap is forward-looking (new creds could slip past the automated gate). |

**Classification:** All 6 findings are WARNINGs from the Phase 1 code review (01-REVIEW.md). Zero are CRITICALs. None prevent the Phase 1 goal from being achieved. Findings WR-01 and WR-04 should be addressed in Phase 2 (results store implementation); WR-02, WR-03 are low-risk hardening items; WR-05 and WR-06 are docstring/coverage improvements.

**Debt marker gate:** No `TBD`, `FIXME`, or `XXX` markers found in any Phase 1 modified files.

---

## Human Verification Required

None. All Phase 1 deliverables are backend infrastructure (configuration, type system, database access, migrations). Every observable behavior is covered by automated tests that were run and verified above. No visual appearance, user flows, real-time behavior, or external service integration is involved.

---

## Gaps Summary

No gaps. All 5 ROADMAP Success Criteria are satisfied by the codebase evidence. The SPINE-02 and GATE-02 Pending status in REQUIREMENTS.md reflects their documented multi-phase scope (Phase 1 delivers the binding substrate; Phases 2-4 complete the full gate criteria). This scoping is explicitly established in the roadmap traceability and the verifier context.

The 6 review warnings (01-REVIEW.md WR-01 through WR-06) are noted above. They are advisory: none block the Phase 1 goal, and none constitute a gap in the phase deliverable. They should inform planning for Phase 2 (ResultsStore concrete impl — address WR-04 in ABC surface) and future hardening tasks.

---

_Verified: 2026-06-27_
_Verifier: Claude (gsd-verifier)_
