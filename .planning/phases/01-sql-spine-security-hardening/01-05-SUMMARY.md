---
phase: 01-sql-spine-security-hardening
plan: 05
subsystem: database
tags: [sqlalchemy, sqlite, postgres, secretstr, security, sql-injection, fl-06, mypy-strict, spine]

# Dependency graph
requires:
  - phase: 01-01
    provides: "GATE-02 test substrate (testcontainers pg_engine + indirect engine fixtures) — available but not consumed by this plan (SQLite-only behavior tests)"
  - phase: 01-02
    provides: "itrader/storage spine — SqlBackend (Engine+MetaData), UtcIsoText, SqlSettings/SqlDriver; the composition target this plan reworks SqlHandler onto"
provides:
  - "Hardened SqlHandler (price_handler/store/sql_store.py) — composes SqlBackend (5th consumer), single parameterized `prices` table, creds from Settings.database_url SecretStr, all three FL-06 vulns closed (SEC-01)"
  - "FL-06 grep gates wired as automated pytest tests (no hardcoded cred, no f-string-in-text()) over a pathlib scan of itrader/"
  - "sql_store.py lifted into mypy --strict (D-sql override removed) with zero narrow/broad ignores"
affects: [phase-03-operational-sql-backends, phase-02-results-store]

# Tech tracking
tech-stack:
  added: []  # assembly of already-present SQLAlchemy 2.0.50 + the 01-02 spine — no new dependency
  patterns: [single-table-with-value-column (symbol as VALUE, not identifier), bindparam parameterization on a constant table name, composition onto SqlBackend, fragment-built grep-gate test (no literal anti-pattern in the asserting test)]

key-files:
  created:
    - tests/unit/price_handler/test_sql_handler.py
  modified:
    - itrader/price_handler/store/sql_store.py
    - pyproject.toml

key-decisions:
  - "Symbol is a VALUE column on one constant `prices` table, never a dynamic SQL identifier (D-07) — reads/writes/deletes filter by bindparam(symbol)"
  - "SQLAlchemy Core insert/select/delete (not pandas to_sql with a dynamic name) for full bind-param + UtcIsoText control on writes; OHLCV stays Float (D-13), date via UtcIsoText"
  - "No narrow `# type: ignore` needed — pandas is ignore_missing_imports (Any); the SQLAlchemy Core code is fully typed, so the D-sql override removal lands strict-clean with zero ignores"
  - "No tests/unit/price_handler/__init__.py created (deviation from plan files_modified) — the dir is package-less and adding it would risk the full-suite collection collision fixed in 30c0f61"
  - "SEC-01 marked COMPLETE; GATE-02 left Pending (recurring milestone-wide gate, consistent with 01-01/01-02/01-03)"

patterns-established:
  - "Single-table-with-value-column: collapse a table-per-key schema into one constant-named table + a key VALUE column, filtered by bound params — the injection-safe replacement for dynamic identifiers"
  - "Fragment-built grep-gate test: assemble forbidden anti-pattern strings from concatenated fragments at runtime so the asserting test never self-trips the gate it enforces"
  - "Override-removal-as-strict-lift: removing a module from the mypy ignore_errors override is the GATE-02 proof that the reworked file is strict-clean (no compensating ignore)"

requirements-completed: [SEC-01]  # GATE-02 is a recurring gate — left Pending (see ## Requirements)

# Metrics
duration: 7min
completed: 2026-06-27
---

# Phase 01 Plan 05: FL-06 Hardening Summary

**Reworked `SqlHandler` onto the SQL spine — composes `SqlBackend`, collapses symbol-as-table-name into one parameterized `prices` table with `symbol` as a VALUE column, sources creds from `Settings.database_url` (SecretStr), removes the f-string `DROP TABLE` DDL, and lifts the file into `mypy --strict` — closing all three FL-06 / SEC-01 vulnerabilities with grep gates green as automated tests.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-27T17:56:57Z
- **Completed:** 2026-06-27T18:03:27Z
- **Tasks:** 3 (one commit each)
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- **All three FL-06 vulns closed (SEC-01):** hardcoded credential (L17) → creds from `Settings.database_url.get_secret_value()` via the injected `SqlBackend`; f-string `DROP TABLE` DDL (L35) → parameterized Core `DELETE` on the constant `prices` table; symbol-as-table-name (L56/58/69) → one `prices` table with a `symbol` VALUE column, every read/write/delete filtered by `bindparam("symbol")`.
- **Full migration onto the spine (D-06):** `SqlHandler.__init__(self, backend: SqlBackend)` is the 5th spine consumer — uses `backend.engine`/`backend.metadata`, registers a single `prices` `Table` (symbol/date PK, OHLCV `Float`, `UtcIsoText` date), no `create_engine`/`database_exists`. Full uniform 4-space rewrite (no surviving tab line).
- **Lifted into `mypy --strict` (GATE-02/D-09):** removed the `itrader.price_handler.store.sql_store` line from the D-sql `ignore_errors` override; `mypy itrader/price_handler/store/sql_store.py` and full `mypy itrader` (195 files) clean — **zero** narrow or broad ignores added (pandas is `ignore_missing_imports`).
- **SEC-01 behavior + grep gates as tests:** 7 unit tests over an in-process SQLite `SqlBackend` prove OHLCV round-trip, single-`prices`-table (no per-symbol table), two-symbol coexistence filtered by `symbol`, replace/delete scoping, plus a pathlib scan of `itrader/` asserting no hardcoded cred and no f-string-in-`text()`.
- **GATE-01 byte-exact + suite green:** oracle 3/3 (quarantine intact, zero hot-path code); full suite 1373 passed under `filterwarnings=["error"]`; full-suite collect-only 0 errors (package-less test dir preserved).

## Task Commits

Each task was committed atomically:

1. **Task 1: Rework SqlHandler onto the spine** — `a36773e` (feat)
2. **Task 2: Lift sql_store into mypy --strict + SYSTEM_DB_URL note** — `88abd03` (chore)
3. **Task 3: test_sql_handler.py — SEC-01 behavior + FL-06 grep gates** — `25a90a0` (test)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified
- `itrader/price_handler/store/sql_store.py` - Full 4-space rewrite: `SqlHandler` composes `SqlBackend`; single parameterized `prices` table; `to_database`/`read_prices`/`get_symbols`/`delete_prices` via `bindparam`/Core; SecretStr creds; SQLHandler logger + quarantine preserved; module docstring documents the three removed vulns and the single-canonical-credential-source / SYSTEM_DB_URL defer.
- `pyproject.toml` - Removed the `itrader.price_handler.store.sql_store  # D-sql` line from the first `[[tool.mypy.overrides]]` module list (the sole pyproject mypy edit in this phase); no new broad ignore.
- `tests/unit/price_handler/test_sql_handler.py` - 7 tests: single-table SEC-01 behavior (SQLite, no Docker) + FL-06 grep gates (fragment-built patterns, pathlib scan of `itrader/`).

## Decisions Made
- **SQLAlchemy Core insert (not `df.to_sql("prices", ...)`) on writes.** Both are injection-safe (literal table name), but building explicit row dicts and executing `insert(prices)` gives full control of the `bindparam` parameterization and the `UtcIsoText` date encoding, avoiding pandas type-inference surprises on append. Reads use `pd.read_sql(select(...).where(symbol == bindparam), params=...)`.
- **Deterministic reads:** `read_prices` adds `ORDER BY date`; `get_symbols` adds `ORDER BY symbol`. The fragile `df.index.freq = inferred_freq` parity line is guarded with `try/except ValueError` so irregular/short frames never raise.
- **No `__init__.py` in the price_handler test dir** (see Deviations) — preserves the package-less convention and avoids the collection collision.
- **SEC-01 COMPLETE / GATE-02 Pending** — SEC-01 is fully satisfied (all three vulns closed, gates green); GATE-02 is the recurring milestone-wide gate (this plan's `mypy --strict` + `filterwarnings` half is met for its code, but the cross-substrate round-trip/rehydration half spans later phases) — left Pending consistent with 01-01/01-02/01-03.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Did NOT create `tests/unit/price_handler/__init__.py` (listed in the plan's `files_modified` and Task 3 action)**
- **Found during:** Task 3 (test creation)
- **Issue:** The plan's `files_modified` and Task 3 `<action>` instruct creating `tests/unit/price_handler/__init__.py`. That directory already exists and is intentionally package-less (it holds `test_bar_feed_update_config.py` with no `__init__.py`). Adding `__init__.py` would create a top-level `price_handler` test package, change the existing test's import name, and risk the full-suite collection collision that commit `30c0f61` fixed.
- **Fix:** Added only `test_sql_handler.py` into the existing package-less dir (test basenames are unique, so no `__init__.py` is needed). The test computes the repo root via `Path(__file__).resolve().parents[3]` rather than relying on package context.
- **Files modified:** tests/unit/price_handler/test_sql_handler.py (created); `__init__.py` deliberately NOT created.
- **Verification:** `poetry run pytest tests --collect-only -q` → 1373 collected, 0 errors (no collision); the new test file's 7 tests pass.
- **Committed in:** `25a90a0` (Task 3 commit)

**2. [Rule 1 - Bug] Disposed the engine in the test fixture teardown to avoid a `ResourceWarning`**
- **Found during:** Task 3 (smoke test surfaced it during Task 1)
- **Issue:** A `SqlHandler` over an in-memory SQLite engine that is never disposed leaks an unclosed SQLite connection, emitting a `ResourceWarning` at GC/shutdown — which would fail under `filterwarnings=["error"]` if raised inside a test.
- **Fix:** The `handler` fixture wraps `yield` in `try/finally` and calls `sql_handler.stop_engine()` (engine `dispose()`) on teardown.
- **Files modified:** tests/unit/price_handler/test_sql_handler.py
- **Verification:** `poetry run pytest tests/unit/price_handler/test_sql_handler.py -q` → 7 passed, no warnings; full suite green.
- **Committed in:** `25a90a0` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 blocking, 1 Rule 1 bug)
**Impact on plan:** Both protect the strict-suite/collection invariants the plan itself depends on (the no-`__init__.py` choice follows the explicit repo gotcha; the dispose avoids a `filterwarnings=["error"]` failure). No scope creep — work stays within the three planned files (minus the intentionally-omitted `__init__.py`).

## Issues Encountered
- None blocking. The in-memory SQLite engine persists the `prices` table across `engine.begin()`/`connect()` calls within a thread (SingletonThreadPool, confirmed in 01-02), so the single-test round-trip needs no shared connection.

## Threat Model Coverage
All five mitigatable threats from the plan's STRIDE register are closed in code:
- **T-01-12** (symbol-as-table-name tamper) → single `prices` table + `symbol` VALUE column + `bindparam`; literal table name only.
- **T-01-13** (f-string `DROP TABLE` DDL) → parameterized Core `DELETE`; no string-built identifier.
- **T-01-14** (hardcoded credential) → creds from `Settings.database_url.get_secret_value()`; grep gate proves no `user:pass@`/`:1234@` repo-wide. (Ops note: rotate/scrub the historical `:1234` credential from VCS history if it was ever real — out of code scope.)
- **T-01-04** (secret in logs) → SecretStr masks repr; the resolved URL is never passed into a log; SQLHandler logger preserved.
- **T-01-15** (second cred-source drift) → one canonical source documented; legacy `SYSTEM_DB_URL` D-live seam documented + deferred, not re-wired.

## Requirements

**SEC-01 — COMPLETE.** `SqlHandler` is parameterized + uses a constant safe identifier and sources credentials from settings/secrets — no hardcoded creds (L17), no f-string DDL (L35), no symbol-as-table-name (L56/58/69). The two grep gates are green repo-wide and wired as automated pytest tests. Marked complete in REQUIREMENTS.md.

**GATE-02 — Pending (recurring, bound to Phase 1).** This plan's code is `mypy --strict` clean (override removed, zero ignores) and the suite is green under `filterwarnings=["error"]` — but GATE-02's "DB round-trip + restart-rehydration tests on the right substrate (SQLite results store + testcontainers Postgres operational store)" half spans later plans/phases. Consistent with 01-01/01-02/01-03, GATE-02 stays Pending until the milestone-wide criteria are met.

## User Setup Required
None - no external service configuration required. The reworked handler stays quarantined (not on the backtest import path) and the tests run on in-process SQLite with no Docker.

## Next Phase Readiness
- FL-06 is closed: Phase 3 (Operational SQL Backends) inherits a clean, parameterized, spine-composed price store and the single-table-with-value-column pattern.
- The grep gates are now regression-locked as tests — any reintroduction of a hardcoded cred or f-string-in-`text()` anywhere in `itrader/` fails the suite.
- No blockers. GATE-01 oracle byte-exact; the rework adds zero hot-path code (quarantine intact).

## Self-Check: PASSED
- FOUND: itrader/price_handler/store/sql_store.py, tests/unit/price_handler/test_sql_handler.py, .planning/phases/01-sql-spine-security-hardening/01-05-SUMMARY.md
- FOUND commits: a36773e (Task 1 feat), 88abd03 (Task 2 chore), 25a90a0 (Task 3 test)
- CONFIRMED: no tests/unit/price_handler/__init__.py (package-less dir preserved; collect-only 1373 / 0 errors)
- FL-06 grep gates green repo-wide; mypy --strict clean (195 files, 0 ignores); GATE-01 oracle 3/3 byte-exact; full suite 1373 passed under filterwarnings=["error"]
- No tracked-file deletions

---
*Phase: 01-sql-spine-security-hardening*
*Completed: 2026-06-27*
