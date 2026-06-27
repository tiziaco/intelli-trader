---
phase: 01-sql-spine-security-hardening
plan: 01
subsystem: testing
tags: [alembic, testcontainers, postgres, sqlite, sqlalchemy, pytest, supply-chain]

# Dependency graph
requires:
  - phase: none
    provides: greenfield wave-0 plan — no prior v1.6 phase dependency
provides:
  - "alembic ^1.18.5 + testcontainers[postgresql] ^4.14.2 installed in the dev group (legitimacy-gated, GATE-01-inert)"
  - "tests/integration/storage/ package with a session-scoped pg_engine testcontainers Postgres fixture (D-10)"
  - "indirect-parametrizable engine fixture (sqlite in-memory + postgres) — the SPINE-03 round-trip substrate"
  - "Docker-absent skip (D-11): a Dockerless `poetry run pytest tests` stays green, never hard-fails"
affects: [01-02-spine, 01-03-spine-roundtrip, phase-03-operational-sql-backends, GATE-02]

# Tech tracking
tech-stack:
  added: [alembic ^1.18.5, testcontainers[postgresql] ^4.14.2 (transitively docker, mako, wrapt, pywin32)]
  patterns: [deferred-import session-scoped container fixture, indirect-parametrized cross-backend engine fixture, Docker-absent pytest.skip]

key-files:
  created:
    - tests/integration/storage/__init__.py
    - tests/integration/storage/conftest.py
    - tests/integration/storage/test_engine_fixture.py
  modified:
    - pyproject.toml
    - poetry.lock

key-decisions:
  - "alembic + testcontainers installed ONLY after the blocking-human supply-chain gate (T-01-SC) was approved; both kept in the dev group so neither is on the runtime/backtest import path (GATE-01 inertness preserved)"
  - "pg_engine defers the testcontainers/docker imports AND the PostgresContainer construction into the fixture body — the constructor eagerly builds a DockerClient, so Docker-absent must be caught around construction, not just .start()"
  - "GATE-02 substrate (the testcontainers Postgres + in-memory SQLite engine fixtures) is established here as Phase 1's binding deliverable; GATE-02 itself is a recurring milestone-wide gate and is NOT marked complete by this single plan (no persistence code exists yet to round-trip)"

patterns-established:
  - "Pattern 1: session-scoped testcontainers fixture with deferred imports + Docker-absent pytest.skip (D-10/D-11) — reused by Phase 3 operational-store tests"
  - "Pattern 2: indirect-parametrized `engine` fixture selecting 'sqlite' (in-process :memory:) vs 'postgres' (pg_engine) — the cross-backend parity substrate consumed by SPINE-03"

requirements-completed: []  # GATE-02 substrate established (Phase 1 binding) but GATE-02 is a recurring gate — see ## Requirements

# Metrics
duration: 11min
completed: 2026-06-27
---

# Phase 01 Plan 01: Deps + PG Harness Summary

**alembic + testcontainers installed behind a blocking-human supply-chain gate, and the GATE-02 cross-backend test substrate stood up: a session-scoped testcontainers Postgres `pg_engine` fixture + an indirect-parametrized sqlite/postgres `engine` fixture that skips gracefully when Docker is absent (D-10/D-11).**

## Performance

- **Duration:** ~11 min (execution after checkpoint approval)
- **Started:** 2026-06-27T16:58:43Z (post-checkpoint resume)
- **Completed:** 2026-06-27T17:09:14Z
- **Tasks:** 3 (Task 1 human gate cleared, Tasks 2-3 executed)
- **Files modified:** 5 (2 modified, 3 created)

## Accomplishments
- Cleared the mandatory supply-chain package-legitimacy gate (T-01-SC) — both NEW packages human-verified against their authoritative PyPI/source repos before any `poetry add`.
- Added `alembic ^1.18.5` (operational migration tooling) and `testcontainers[postgresql] ^4.14.2` (test-only PG substrate) to the dev group; lockfile consistent (`poetry check --lock` exit 0), both importable.
- Stood up `tests/integration/storage/` with a session-scoped `pg_engine` testcontainers Postgres-16 fixture and an `indirect`-parametrizable `engine` fixture (sqlite in-memory + postgres) — the GATE-02 cross-backend substrate, reused by Phase 3.
- Proved D-11: collect-only needs no Docker (deferred import), a Docker-available run passes both arms, and a simulated Dockerless run reports the PG arm **skipped** (exit 0) — never a hard fail.
- Confirmed GATE-01 inertness: SMA_MACD oracle byte-exact (134 / `46189.87730727451`), zero per-tick code added.

## Task Commits

Each task was committed atomically:

1. **Task 1: Package legitimacy gate (blocking-human checkpoint)** — no commit (human verification step; approved by the operator before install)
2. **Task 2: Add alembic + testcontainers dev-dependencies** — `e9fa668` (chore)
3. **Task 3: pg_engine substrate + cross-backend engine fixture** — `d7ae858` (test)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified
- `pyproject.toml` - alembic + testcontainers[postgresql] declared in `[tool.poetry.group.dev.dependencies]`
- `poetry.lock` - resolved/locked: alembic, mako, testcontainers, docker, wrapt, pywin32 (Windows-only conditional)
- `tests/integration/storage/__init__.py` - empty package marker (mirrors the e2e subpackage convention)
- `tests/integration/storage/conftest.py` - session-scoped `pg_engine` (testcontainers Postgres-16, deferred imports, Docker-absent skip) + indirect `engine` fixture (sqlite/postgres)
- `tests/integration/storage/test_engine_fixture.py` - GATE-02 substrate self-test: parametrizes `engine` over both backends and asserts a live `SELECT 1`

## Decisions Made
- **Both packages kept in the dev group, not runtime.** alembic is operational tooling and testcontainers is test-only; neither is on the backtest/runtime import path, preserving GATE-01 structural inertness.
- **Construction inside the try, broad catch for D-11.** The `PostgresContainer` constructor eagerly builds a `DockerClient`, so an absent/unreachable daemon raises a `DockerException` at construction (not `.start()`); the fixture wraps both and converts ANY startup failure to `pytest.skip`, refining the skip message via `isinstance(exc, DockerException)`.
- **GATE-02 not marked complete (recurring gate).** This plan delivers the substrate that GATE-02 is *bound* to in Phase 1, but GATE-02 ("the new persistence code is covered by DB round-trip + restart-rehydration tests") recurs every phase and has no persistence code to verify yet — see ## Requirements.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added a substrate self-test (`test_engine_fixture.py`) not in the plan's `<files>`**
- **Found during:** Task 3 (pg_engine substrate)
- **Issue:** The plan's verification command (`poetry run pytest tests/integration/storage -q`) and `done` criterion require a Dockerless run to "report the PG arm as **skipped** (D-11), exit code 0" and collect-only to "prove the deferred import." With only `conftest.py` + `__init__.py` (zero test files), pytest collects nothing → exit code 5 (not 0), and no fixture is ever exercised — the acceptance criteria are structurally unsatisfiable.
- **Fix:** Added a minimal parametrized self-test that consumes the `engine` fixture over `["sqlite", "postgres"]` (indirect) and asserts a live `SELECT 1`. Collect-only now yields 2 items (proving the deferred import); a Docker-available run passes both arms; a Dockerless run reports `1 passed, 1 skipped` exit 0.
- **Files modified:** tests/integration/storage/test_engine_fixture.py (created)
- **Verification:** collect-only exit 0 (2 collected); Docker-available `2 passed`; Dockerless (`DOCKER_HOST` → dead socket) `1 passed, 1 skipped` exit 0.
- **Committed in:** `d7ae858` (Task 3 commit)

**2. [Rule 1 - Bug] pg_engine errored instead of skipping when Docker was absent**
- **Found during:** Task 3 (D-11 skip verification)
- **Issue:** The initial fixture wrapped only `container.start()` in the try/except. The `PostgresContainer(...)` **constructor** eagerly builds a `DockerClient` and raises `DockerException` at construction — outside the try — so a simulated Dockerless run produced `1 passed, 1 error` instead of `1 passed, 1 skipped`, hard-failing the PG arm (violating D-11).
- **Fix:** Moved the `PostgresContainer` construction inside the try block, broadened the catch to any startup exception (with best-effort `container.stop()` cleanup), and refined the skip message via `isinstance(exc, DockerException)`.
- **Files modified:** tests/integration/storage/conftest.py
- **Verification:** Dockerless run now reports `1 passed, 1 skipped`, exit 0; the skip reason cites D-11.
- **Committed in:** `d7ae858` (Task 3 commit — fixed before the commit landed)

---

**Total deviations:** 2 ( 1 missing-critical, 1 bug)
**Impact on plan:** Both were necessary to satisfy the plan's own D-11 acceptance criteria. No scope creep — the added test file is the minimal consumer needed to verify the substrate it ships.

## Issues Encountered
- A pre-existing `pyarrow` entry exists in `poetry.lock` (transitive from `nautilus-trader`, present at HEAD). Verified my change did NOT add it — the diff added only alembic/mako/testcontainers/docker/wrapt/pywin32. The locked-out packages (`pyarrow`, `sqlalchemy-libsql`, `optuna`) were not added.

## Requirements

**GATE-02 (recurring, bound to Phase 1) — substrate established, gate NOT closed.**
The plan frontmatter lists `requirements: [GATE-02]`. GATE-02 is a **recurring milestone-wide gate** ("the new persistence code is covered by DB round-trip + restart-rehydration tests on the right substrate ... mypy --strict clean and filterwarnings=['error'] green") that is *restated in every phase*. This plan delivers the Phase-1 binding deliverable — the testcontainers Postgres + in-process SQLite test substrate — but there is **no persistence code yet** to round-trip, so GATE-02 is intentionally left **Pending** in REQUIREMENTS.md and `requirements-completed` is empty. Marking it complete after plan 1 of 5 would falsely close a gate the verifier tracks across the whole milestone. SPINE-03 (01-03) and Phase 3 will exercise this substrate as the actual persistence code lands.

## User Setup Required
None - no external service configuration required. (testcontainers spins an ephemeral local Postgres on demand; a Dockerless environment simply skips the PG arm.)

## Self-Check: PASSED
- FOUND: tests/integration/storage/__init__.py
- FOUND: tests/integration/storage/conftest.py
- FOUND: tests/integration/storage/test_engine_fixture.py
- FOUND commit: e9fa668 (Task 2)
- FOUND commit: d7ae858 (Task 3)
- pyproject.toml dev group lists alembic ^1.18.5 + testcontainers[postgresql] ^4.14.2
- No tracked-file deletions; no untracked leftovers

## Next Phase Readiness
- The `engine` / `pg_engine` fixtures are ready for the SPINE-03 round-trip (01-03) — consume via `@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)`.
- alembic is available for MIG-01 (live-Postgres migrations) later in Phase 1.
- No blockers. GATE-01 oracle byte-exact; GATE-02 substrate live and recurring.

---
*Phase: 01-sql-spine-security-hardening*
*Completed: 2026-06-27*
