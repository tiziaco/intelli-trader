---
phase: 01-sql-spine-security-hardening
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - poetry.lock
  - tests/integration/storage/conftest.py
  - tests/integration/storage/__init__.py
autonomous: false
requirements: [GATE-02]
user_setup: []

must_haves:
  truths:
    - "alembic ^1.18.5 and testcontainers[postgresql] ^4.14.2 are installed as dev-deps, legitimacy-verified at a blocking-human checkpoint BEFORE install (D-10, supply-chain gate T-01-SC)"
    - "A session-scoped testcontainers Postgres fixture (pg_engine) is available to the storage test suite — the GATE-02 substrate is bound here, reused by Phase 3 (D-10)"
    - "PG-backed tests skip/xfail cleanly when Docker is absent so a Dockerless `poetry run pytest tests` stays green, never hard-fails (D-11)"
  artifacts:
    - path: "tests/integration/storage/conftest.py"
      provides: "session-scoped pg_engine testcontainers fixture + Docker-absent skip"
      contains: "pg_engine"
    - path: "pyproject.toml"
      provides: "alembic + testcontainers in the dev dependency group"
      contains: "testcontainers"
  key_links:
    - from: "tests/integration/storage/conftest.py"
      to: "testcontainers.postgres.PostgresContainer"
      via: "deferred import inside the fixture body; pytest.skip on DockerException / absent daemon"
      pattern: "PostgresContainer"
---

<objective>
Install the two dev-dependencies Phase 1 needs (alembic, testcontainers) behind a package-legitimacy
checkpoint, and stand up the cross-backend test substrate: a session-scoped testcontainers Postgres
`pg_engine` fixture that skips gracefully when Docker is absent.

Purpose: GATE-02 is *bound* to Phase 1 — the DB test harness/substrate is established here, and Phase 3
reuses the same Postgres fixture. SPINE-03 (next wave) needs its round-trip proven on real Postgres, not
just SQLite.
Output: `pyproject.toml`/`poetry.lock` updated with `alembic` + `testcontainers[postgresql]`; a
`tests/integration/storage/` package with a `pg_engine` fixture and Docker-absent skip (D-11).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/01-sql-spine-security-hardening/01-CONTEXT.md
@.planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md
@.planning/phases/01-sql-spine-security-hardening/01-VALIDATION.md
@tests/integration/conftest.py

<interfaces>
<!-- Established deferred-import fixture idiom the pg_engine fixture must mirror -->
<!-- From tests/integration/conftest.py:45-72 — the heavy import lives INSIDE the inner fn so --collect-only succeeds without the dependency present -->
```python
@pytest.fixture
def backtest_engine():
    def _make(...):
        from itrader.trading_system.backtest_trading_system import BacktestTradingSystem  # deferred
        return BacktestTradingSystem(...)
    return _make
```

<!-- Pytest config invariants (pyproject.toml:54-78) the fixture must respect -->
<!-- markers folder-derived in tests/conftest.py: tests/integration/* auto-marks `integration` (no decorator) -->
<!-- filterwarnings=["error","ignore::UserWarning","ignore::DeprecationWarning"] — a testcontainers warning that is not UserWarning/DeprecationWarning will FAIL the suite -->
</interfaces>
</context>

<tasks>

<task type="checkpoint:human-verify" gate="blocking-human">
  <name>Task 1: Package legitimacy gate — verify alembic + testcontainers before install</name>
  <read_first>
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Package Legitimacy Audit" (slopcheck was unavailable; both packages tagged [ASSUMED], planner must gate the install)
  </read_first>
  <action>
    Halt before any `poetry add`. Present the two NEW packages (alembic ^1.18.5, testcontainers[postgresql] ^4.14.2) for human legitimacy verification against their authoritative PyPI pages + source repos, and BLOCK the install until a human approves. This gate is never auto-approvable (workflow.auto_advance is ignored); both packages stay [ASSUMED] until verified.
  </action>
  <what-built>
    Nothing installed yet. This is the mandatory supply-chain gate (T-01-SC): the two NEW packages were
    tagged [ASSUMED] in research because slopcheck was not installable. Both are canonical (alembic is by
    the SQLAlchemy maintainers; testcontainers-python is the official Testcontainers org), but the install
    is gated per protocol — this checkpoint is NEVER auto-approvable.
  </what-built>
  <how-to-verify>
    1. Open https://pypi.org/project/alembic/ — confirm source repo github.com/sqlalchemy/alembic, current release 1.18.x, maintained by the SQLAlchemy authors.
    2. Open https://pypi.org/project/testcontainers/ — confirm source repo github.com/testcontainers/testcontainers-python (official org), current release 4.14.x.
    3. Confirm neither is a recently-published typosquat (release history spans years, download counts are high).
  </how-to-verify>
  <verify>
    <automated>MISSING — manual blocking-human checkpoint; verification is human PyPI/source-repo confirmation (no automated command)</automated>
  </verify>
  <acceptance_criteria>
    - Human confirms both PyPI pages resolve to the authoritative source repos named above and approves the install.
    - This gate is blocking-human and is NOT skippable via auto_advance.
  </acceptance_criteria>
  <resume-signal>Type "approved" to proceed with the install, or name an alternative package/version.</resume-signal>
  <done>Human has verified both packages are legitimate and approved the install.</done>
</task>

<task type="auto">
  <name>Task 2: Add alembic + testcontainers as dev-dependencies</name>
  <files>pyproject.toml, poetry.lock</files>
  <read_first>
    - pyproject.toml (the `[tool.poetry.group.dev.dependencies]` / dev group section — match the existing dependency-declaration style; 4-space TOML)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Standard Stack → Supporting (ADD as dev-dependencies)" + the Installation block
  </read_first>
  <action>
    Run `poetry add --group dev alembic@^1.18.5` then `poetry add --group dev "testcontainers[postgresql]@^4.14.2"` (these update `pyproject.toml` and `poetry.lock` and run `poetry install`). Do NOT add `pyarrow`, `sqlalchemy-libsql`, or `optuna` (all locked OUT / deferred — D-13/D-15). Confirm `alembic` and `testcontainers` import cleanly afterward. Keep both in the `dev` group (alembic is operational tooling, testcontainers is test-only — neither is on the runtime/backtest import path, preserving GATE-01 inertness).
  </action>
  <verify>
    <automated>poetry run python -c "import alembic, testcontainers.postgres; print(alembic.__version__)"</automated>
  </verify>
  <acceptance_criteria>
    - `pyproject.toml` dev group lists `alembic` (^1.18.5) and `testcontainers` with the `postgresql` extra (^4.14.2).
    - `poetry.lock` is updated and committed-consistent (`poetry lock --check` passes or `poetry install` is clean).
    - `poetry run python -c "import alembic, testcontainers.postgres"` exits 0.
    - No `pyarrow` / `sqlalchemy-libsql` / `optuna` added.
  </acceptance_criteria>
  <done>Both packages installed in the dev group, importable, lockfile consistent.</done>
</task>

<task type="auto">
  <name>Task 3: Wave-0 substrate — tests/integration/storage/ pg_engine fixture (D-10/D-11)</name>
  <files>tests/integration/storage/conftest.py, tests/integration/storage/__init__.py</files>
  <read_first>
    - tests/integration/conftest.py:45-72 (the deferred-import factory-fixture idiom to mirror; 4-space)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "Test files" + "pg_engine specifics (D-10/D-11)" (session-scoped PostgresContainer; import testcontainers INSIDE the fixture; pytest.skip on DockerException; tests/integration/storage/ → folder-derived `integration` marker, no decorator)
    - INDENTATION: tests/integration/* = 4 SPACES (verified). New package files = 4 spaces.
  </read_first>
  <action>
    Create `tests/integration/storage/__init__.py` (empty package marker) and `tests/integration/storage/conftest.py`. In conftest, define a SESSION-scoped `pg_engine` fixture: import `testcontainers.postgres.PostgresContainer` and the testcontainers/docker-raised exceptions INSIDE the fixture body (deferred — so `--collect-only` succeeds without Docker), start a `PostgresContainer("postgres:16")`, yield a SQLAlchemy `Engine` built from `container.get_connection_url()` via `sqlalchemy.create_engine`, and tear the container down on teardown. Wrap the container startup in a try/except that calls `pytest.skip("Docker unavailable — PG arm skipped (D-11)")` on any Docker-absent / `DockerException` / connection failure, so a Dockerless run skips rather than hard-fails. Also provide an `indirect`-parametrizable `engine` fixture that returns an in-process `sqlite+pysqlite:///:memory:` Engine for the `"sqlite"` param and the `pg_engine` for the `"postgres"` param (the SPINE-03 round-trip test in 01-03 consumes this). Do NOT emit any non-`UserWarning`/`DeprecationWarning` warning (filterwarnings=["error"]).
  </action>
  <verify>
    <automated>poetry run pytest tests/integration/storage --collect-only -q && poetry run pytest tests/integration/storage -q</automated>
  </verify>
  <acceptance_criteria>
    - `poetry run pytest tests/integration/storage --collect-only` succeeds WITHOUT a running Docker daemon (deferred import proven).
    - With Docker absent, `poetry run pytest tests/integration/storage -q` reports the PG arm as skipped (D-11), exit code 0 — never an error/fail.
    - `pg_engine` is `scope="session"`; the `engine` fixture parametrizes `"sqlite"` and `"postgres"` via `indirect`.
    - tests/integration/storage/conftest.py is 4-space indented; no marker decorator (folder-derived `integration`).
  </acceptance_criteria>
  <done>The storage test package + pg_engine/engine fixtures exist; collect-only and a Dockerless run are both green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| PyPI registry → dev environment | Third-party packages enter the build; supply-chain risk |
| Docker daemon → test process | testcontainers spins an ephemeral local Postgres |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-SC | Tampering | alembic/testcontainers `poetry add` | mitigate | Blocking-human legitimacy checkpoint (Task 1) before install; both [ASSUMED] until human-verified against the authoritative source repos; never auto-approvable |
| T-01-01 | Denial of Service | Dockerless test run | mitigate | PG fixture skips on Docker-absent (D-11) — a missing daemon must not hard-fail `poetry run pytest tests`; SQLite arm still runs |
| T-01-02 | Information Disclosure | testcontainers connection URL | accept | Ephemeral local container, random port, torn down at session end; URL is local-only and never logged |
</threat_model>

<verification>
- `poetry run pytest tests/integration/storage --collect-only -q` succeeds with Docker absent.
- `poetry run pytest tests/integration/storage -q` exits 0 (PG arm skipped when Dockerless).
- `poetry run python -c "import alembic, testcontainers.postgres"` exits 0.
- GATE-01 (recurring, inert): this plan adds zero per-tick code; the SMA_MACD oracle is unaffected — confirm `poetry run pytest tests/integration/test_backtest_oracle.py -x` still byte-exact 134 / `46189.87730727451`.
</verification>

<success_criteria>
- alembic + testcontainers installed in the dev group, legitimacy-gated, lockfile consistent.
- The `tests/integration/storage/` package exists with a session-scoped `pg_engine` fixture and a parametrizable `engine` fixture (sqlite + postgres).
- A Dockerless `poetry run pytest tests` stays green (PG arm skips) — GATE-02 substrate established (D-10/D-11).
</success_criteria>

<output>
Create `.planning/phases/01-sql-spine-security-hardening/01-01-SUMMARY.md` when done.
</output>
