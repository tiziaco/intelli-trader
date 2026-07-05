---
phase: 260705-m3m
plan: 01
subsystem: test-infra
tags: [test-fixtures, security, postgres, testcontainers, env-guard]
requires: []
provides:
  - "tests/conftest.py::_block_dev_database_env (session-autouse dev-DB env guard) + _DEV_DB_ENV_VARS"
  - "tests/integration/conftest.py::pg_container_url (single shared session Postgres) + pg_database_env companion"
  - "tests/integration/storage/conftest.py::pg_engine refactored onto the shared container"
affects:
  - "tests/integration/ tree (single suite-wide testcontainers Postgres)"
tech-stack:
  added: []
  patterns:
    - "session-autouse os.environ.pop guard (save + restore-in-finally), monkeypatch-overridable"
    - "one session-scoped testcontainers container consumed by downstream fixtures (no duplicate container)"
key-files:
  created:
    - tests/unit/test_dev_db_env_guard.py
    - tests/integration/test_shared_pg_fixture.py
  modified:
    - tests/conftest.py
    - tests/integration/conftest.py
    - tests/integration/storage/conftest.py
decisions:
  - "T-Q-01/02 mitigated: session guard pops the six ITRADER_DATABASE_* vars at session start so the LiveTradingSystem/SqlSettings env gate falls back to in-memory unless a test explicitly opts in"
  - "ONE session container: storage/pg_engine now consumes the suite-wide pg_container_url instead of spinning its own — proven max 1 concurrent postgres:16 from a clean baseline"
metrics:
  duration: ~10min
  tasks: 2
  files: 5
  completed: 2026-07-05
---

# Phase 260705-m3m Plan 01: Session-Autouse Dev-DB Env Guard + Shared Postgres Fixture Summary

Session-wide guarantee that no test reaches the developer's operational Postgres (six
`ITRADER_DATABASE_*` vars popped for the whole session, monkeypatch-overridable), plus ONE
shared testcontainers Postgres that live-path DB tests opt into via the `ITRADER_DATABASE_URL`
env gate — entirely in the test layer, zero `itrader/` source changes.

## What Was Built

### Task 1 — Session-autouse dev-DB env guard (`fa181dae`)
- `tests/conftest.py`: added `import os`, a module-level `_DEV_DB_ENV_VARS` tuple (the six
  `ITRADER_DATABASE_PASSWORD/URL/HOST/PORT/USER/NAME` — deliberately NOT the sqlite
  `ITRADER_DATABASE_DATABASE`), and a `@pytest.fixture(scope="session", autouse=True)`
  `_block_dev_database_env` that `os.environ.pop(name, None)`s each at session start, `yield`s,
  and restores only the non-`None` saved values in `finally`. Uses `os.environ.pop` directly (not
  the function-scoped `monkeypatch`, which cannot be session-scoped); the docstring records that a
  function-scoped `monkeypatch.setenv` inside a test wins over the earlier session pop and is undone
  at test teardown, so existing container tests keep passing.
- `tests/unit/test_dev_db_env_guard.py`: import-light proof (no `itrader` import) asserting all six
  vars are `None` during a test even when exported into the pytest process.

### Task 2 — One shared session Postgres + storage refactor + opt-in proof (`2f43faec`)
- `tests/integration/conftest.py`: `@pytest.fixture(scope="session") pg_container_url` — the SINGLE
  suite-wide testcontainers Postgres (lifecycle modeled exactly on the former `pg_engine`: deferred
  `testcontainers` import, container construct+start inside `try`, `pytest.skip` on any startup
  failure for D-11 Dockerless, `container.stop()` in `finally`). Companion
  `pg_database_env(pg_container_url, monkeypatch)` points `ITRADER_DATABASE_URL` at the shared
  container within test scope (overriding the session guard) and returns the URL.
- `tests/integration/storage/conftest.py`: `pg_engine` refactored to `def pg_engine(pg_container_url)`
  — dropped its own testcontainers/docker import + container start/skip block, now builds
  `create_engine(pg_container_url)` and disposes in `finally`. `engine` / `pg_backend` consume
  `pg_engine` by name, unchanged. D-11 skip now happens transitively via `pg_container_url`.
- `tests/integration/test_shared_pg_fixture.py`: proof that `pg_database_env` reaches the
  `LiveTradingSystem` env gate — constructs `LiveTradingSystem(exchange="binance")`, asserts
  `CachedSqlSignalStorage` / `CachedSqlOrderStorage`, drops the six operational tables in `finally`
  (mirrors `test_store_live_drive.py`'s drop helper) to leave the shared DB pristine.

Module-scoped `pg_url` fixtures in `test_store_live_drive.py` / `test_two_sided_restart.py` left
UNTOUCHED per plan (foundation drop, not a migration).

## Verification (actual command output)

**1. Guard proof — exported dummy vars pointing at the real dev-DB port removed for the session:**
```
$ ITRADER_DATABASE_PASSWORD=dummy ITRADER_DATABASE_URL=postgresql://x@localhost:5544/y \
    poetry run pytest tests/unit/test_dev_db_env_guard.py -q
tests/unit/test_dev_db_env_guard.py .                                    [100%]
============================== 1 passed in 0.01s ===============================
```
(Plan-verify variant with `PASSWORD=leaked URL=postgresql://leak@localhost/x` also → `1 passed`.)

**2. Storage suite green against the shared container (Docker up — container used, not skipped):**
```
$ poetry run pytest tests/integration/storage -q
============================== 55 passed in 4.07s ===============================
```

**3. Existing container/monkeypatch tests unaffected:**
```
$ poetry run pytest tests/integration/test_store_live_drive.py tests/integration/test_two_sided_restart.py -q
============================== 8 passed in 4.51s ===============================
```

**4. New shared-fixture proof green (part of combined run):**
```
$ poetry run pytest tests/integration/test_store_live_drive.py tests/integration/test_two_sided_restart.py tests/integration/test_shared_pg_fixture.py -q
============================== 9 passed in 5.89s ===============================
```

**Single-container invariant (the plan's whole point) — from a cleaned baseline of 0
`postgres:16` containers, sampling every 1s while running storage suite + shared fixture:**
```
$ poetry run pytest tests/integration/storage tests/integration/test_shared_pg_fixture.py -q
============================== 56 passed in 4.46s ===============================
---max concurrent postgres:16 (clean baseline=0)---
1
```
Exactly ONE container backs the storage suite + opt-in fixture (no second competing container).

**5. No-regression sweep:**
```
$ poetry run pytest tests -q -m "not live"
=========== 8 failed, 1714 passed, 1 skipped, 5 deselected in 29.87s ===========
```
The 8 failures are PRE-EXISTING Phase 05.1 RED conformance tests (A2/A5 → GREEN in Phase 05.2;
A6/A7/A8 → GREEN in Phase 05.3, per STATE.md decisions), NOT caused by this change — proven by
running the identical 8 test IDs at `HEAD~2` (before this plan's two commits) in a throwaway
worktree: `8 failed, 2 passed`, byte-identical failure set. My commits touch zero `itrader/`
source and zero of those 8 test files; the session guard is a provable no-op here (no
`ITRADER_DATABASE_*` vars set in the `poetry run pytest` shell — confirmed via `env`).

Failing set (all documented RED): `test_submit_timeout_inflight` (A7), `test_supervisor_catchall`
×3 (A6), `test_venue_order_id_persist` (A2), `test_redeliver_dedup` (A5), `test_pause_defer_replay`
×2 (A8).

**6. mypy clean (no `itrader/` change; fixtures are out of mypy's `files=["itrader"]` scope):**
```
$ poetry run mypy
Success: no issues found in 228 source files
```

## Deviations from Plan

None — plan executed exactly as written.

## Notes

- A `ResourceWarning: Exception ignored in: <socket.socket ...>` prints AFTER the pass line on the
  container-backed runs. It is a docker-client socket teardown emitted by Python's unraisable hook
  at interpreter shutdown (post-session), NOT a `filterwarnings=["error"]` failure — every session
  reports its full pass count. It originates from the docker/testcontainers client socket (untouched
  module container path shows it too), not from the fixtures added here (which only build/dispose
  SQLAlchemy Engines in `finally`).
- No new package installs (T-Q-SC accept): `testcontainers`/`docker`/`sqlalchemy` are pre-existing
  deps already used by the storage fixtures.

## Self-Check: PASSED
- FOUND: tests/conftest.py (guard + `_DEV_DB_ENV_VARS`)
- FOUND: tests/unit/test_dev_db_env_guard.py
- FOUND: tests/integration/conftest.py (`pg_container_url` + `pg_database_env`)
- FOUND: tests/integration/storage/conftest.py (`pg_engine(pg_container_url)`)
- FOUND: tests/integration/test_shared_pg_fixture.py
- FOUND commit: fa181dae (Task 1)
- FOUND commit: 2f43faec (Task 2)
