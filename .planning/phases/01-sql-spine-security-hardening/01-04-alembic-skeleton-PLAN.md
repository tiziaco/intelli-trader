---
phase: 01-sql-spine-security-hardening
plan: 04
type: execute
wave: 2
depends_on: [01-01, 01-02]
files_modified:
  - alembic.ini
  - itrader/storage/migrations/env.py
  - itrader/storage/migrations/script.py.mako
  - itrader/storage/migrations/versions/.gitkeep
  - tests/integration/storage/test_migrations.py
autonomous: true
requirements: [MIG-01]

must_haves:
  truths:
    - "The live Postgres operational store has an Alembic migration skeleton — one chain, env.py with render_as_batch=True for portable ALTER, and an EMPTY versions/ (no operational tables exist until Phase 3) (MIG-01, D-14)"
    - "The ephemeral research/results store is built by MetaData.create_all() and has NO alembic_version table (MIG-01, D-14)"
    - "alembic's target_metadata is the spine's SqlBackend MetaData, and the chain is scoped to live Postgres only (D-14)"
  artifacts:
    - path: "itrader/storage/migrations/env.py"
      provides: "Alembic env with render_as_batch=True and spine target_metadata"
      contains: "render_as_batch"
    - path: "alembic.ini"
      provides: "script_location -> itrader/storage/migrations"
      contains: "script_location"
    - path: "tests/integration/storage/test_migrations.py"
      provides: "create_all() (no alembic_version) vs alembic chain (alembic_version present) distinction"
      contains: "alembic_version"
  key_links:
    - from: "itrader/storage/migrations/env.py"
      to: "itrader.storage.SqlBackend metadata"
      via: "target_metadata = backend.metadata"
      pattern: "target_metadata"
---

<objective>
Stand up the Alembic migration skeleton for the live Postgres operational store (MIG-01): one chain,
`env.py` with `render_as_batch=True` (portable ALTER for SQLite/libSQL limits), and an EMPTY `versions/`
(no operational tables until Phase 3). Prove the split: the ephemeral research store uses
`MetaData.create_all()` and carries NO `alembic_version` table, while the Alembic chain — when applied —
creates one.

Purpose: MIG-01 — the durable system of record evolves under controlled migrations; the disposable
research DB does not. This is skeleton-only (no operational migrations exist yet; those land Phase 3).
Output: `alembic.ini`, `itrader/storage/migrations/{env.py, script.py.mako, versions/}`, and a test
asserting the create_all-vs-Alembic distinction.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md
@.planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md
@itrader/storage/backend.py

<interfaces>
<!-- D-14 shape (RESEARCH.md Pattern 5): one chain; env.py render_as_batch=True + portable types; EMPTY versions/; -->
<!-- research/results DB uses MetaData.create_all() -> NO alembic_version table. Live PG only. -->
<!-- alembic env.py wires target_metadata = <spine MetaData> so future autogen sees the spine tables. -->
<!-- Generate the skeleton with `alembic init` then relocate/point script_location at itrader/storage/migrations. -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Alembic skeleton — alembic.ini + env.py (render_as_batch=True) + empty versions/</name>
  <files>alembic.ini, itrader/storage/migrations/env.py, itrader/storage/migrations/script.py.mako, itrader/storage/migrations/versions/.gitkeep</files>
  <read_first>
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pattern 5: Alembic scoped to live Postgres" + the Recommended Project Structure (env.py render_as_batch=True, EMPTY versions/, live-PG only)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "No Analog Found" row for migrations (green-field; use RESEARCH Pattern 5)
    - itrader/storage/backend.py (the SqlBackend.metadata to wire as target_metadata)
    - INDENTATION: itrader/storage/ = 4 SPACES (env.py is Python; the .mako/.ini are not Python-indent-sensitive).
  </read_first>
  <action>
    Generate the Alembic skeleton (e.g. `poetry run alembic init itrader/storage/migrations` then prune to the skeleton). Set `alembic.ini` `script_location = itrader/storage/migrations` and leave `sqlalchemy.url` empty/placeholder (the URL is supplied at runtime from `SqlSettings.engine_url()` / `Settings.database_url`, NOT hardcoded — never write a `user:pass@` URL into alembic.ini). In `env.py` (4-space): set `target_metadata` to the spine's `MetaData` (import lazily — do NOT instantiate `Settings()` at import; resolve the URL inside `run_migrations_online()` only), and pass `render_as_batch=True` to `context.configure(...)` in BOTH the offline and online paths (portable ALTER). Keep `versions/` EMPTY except a `.gitkeep` (no operational tables until Phase 3 — D-14). Scope the chain to live Postgres only; the research/results DB never runs alembic.
  </action>
  <verify>
    <automated>poetry run alembic -c alembic.ini history && grep -n "render_as_batch" itrader/storage/migrations/env.py</automated>
  </verify>
  <acceptance_criteria>
    - `poetry run alembic -c alembic.ini history` exits 0 and shows an empty/zero-revision chain (versions/ empty).
    - `grep -n 'render_as_batch=True' itrader/storage/migrations/env.py` present in both offline and online configure calls.
    - `grep -n 'target_metadata' itrader/storage/migrations/env.py` is wired to the spine MetaData.
    - `! grep -rIn 'user:pass@\|:1234@\|sqlalchemy.url = postgresql' alembic.ini itrader/storage/migrations/` (no hardcoded creds — SEC-01 carry-over).
    - `ls itrader/storage/migrations/versions/` contains only `.gitkeep` (empty chain — D-14).
  </acceptance_criteria>
  <done>Alembic skeleton exists, render_as_batch=True, target_metadata wired to the spine, versions/ empty, no hardcoded URL.</done>
</task>

<task type="auto">
  <name>Task 2: test_migrations.py — create_all() (no alembic_version) vs Alembic chain (MIG-01)</name>
  <files>tests/integration/storage/test_migrations.py</files>
  <read_first>
    - tests/integration/storage/conftest.py (from 01-01 — the optional pg_engine; the in-process SQLite path needs no Docker)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → MIG-01 row in "Phase Requirements → Test Map"
    - INDENTATION: tests/integration/* = 4 SPACES.
  </read_first>
  <action>
    Create `tests/integration/storage/test_migrations.py` (4-space). Test A (research/results store): build an in-process `sqlite+pysqlite:///:memory:` engine, run `SqlBackend.metadata.create_all(engine)` (or a sample table's create), inspect the engine, and assert `"alembic_version" NOT in inspector.get_table_names()` — the ephemeral store carries no migration bookkeeping (D-14). Test B (migration chain applies): point Alembic's `Config` at `alembic.ini` with a fresh in-process SQLite URL, run `alembic upgrade head` (the empty chain creates the `alembic_version` table via batch mode), and assert `"alembic_version" in get_table_names()` with zero applied revisions. Optionally add a PG arm using the `pg_engine` fixture, guarded so it SKIPS when Docker is absent (D-11). Use `command.upgrade(...)` from `alembic` programmatically; emit no non-ignored warning.
  </action>
  <verify>
    <automated>poetry run pytest tests/integration/storage/test_migrations.py -k "not postgres" -x</automated>
  </verify>
  <acceptance_criteria>
    - Test A passes: a create_all()-built SQLite DB has NO `alembic_version` table (MIG-01).
    - Test B passes: after `alembic upgrade head` on a fresh DB, `alembic_version` exists with zero applied revisions (empty chain).
    - The PG arm (if present) skips cleanly when Docker is absent (D-11).
    - `poetry run pytest tests/integration/storage/test_migrations.py -k "not postgres"` exits 0 without Docker.
  </acceptance_criteria>
  <done>The create_all-vs-Alembic distinction is asserted; MIG-01 proven on SQLite (and PG when available).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| migration tooling → schema | Alembic emits DDL against the durable store |
| alembic.ini → credentials | a hardcoded URL in config would re-introduce the FL-06 leak |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-09 | Information Disclosure | alembic.ini sqlalchemy.url | mitigate | Leave the URL empty in alembic.ini; resolve at runtime from Settings.database_url / SqlSettings — never write a `user:pass@` URL into config |
| T-01-10 | Tampering | accidental destructive migration on research DB | mitigate | The research/results store uses create_all() only and never runs alembic (no alembic_version); the chain is scoped to live Postgres |
| T-01-11 | Denial of Service | env.py import-time Settings() | mitigate | Resolve the DB URL lazily inside run_migrations_online(); no Settings() at import (Pitfall 8) |
</threat_model>

<verification>
- `poetry run pytest tests/integration/storage/test_migrations.py -k "not postgres" -x` green (no Docker needed).
- `poetry run alembic -c alembic.ini history` exits 0 (empty chain).
- `! grep -rIn 'user:pass@\|:1234@' alembic.ini itrader/storage/migrations/` (no hardcoded creds).
- `poetry run mypy itrader/storage` clean (env.py is in the storage package — keep it strict-clean or note the alembic-template carve-out).
- GATE-01 (recurring, inert): oracle byte-exact 134 / `46189.87730727451`.
</verification>

<success_criteria>
- The live Postgres store has a one-chain Alembic skeleton (render_as_batch=True, empty versions/) — MIG-01.
- The research/results store uses create_all() and has no alembic_version table — MIG-01.
</success_criteria>

<output>
Create `.planning/phases/01-sql-spine-security-hardening/01-04-SUMMARY.md` when done.
</output>
