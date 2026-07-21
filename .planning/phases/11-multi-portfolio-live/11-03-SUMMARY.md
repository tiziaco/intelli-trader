---
phase: 11-multi-portfolio-live
plan: 03
subsystem: storage
tags: [storage, migration, alembic, schema, multi-portfolio, config, sqlalchemy]
requires:
  - venue_accounts table + build_venue_accounts_table registrar (11-01)
  - portfolios table + build_portfolio_definition_tables registrar (11-01)
provides:
  - Alembic revision p11_venue_accounts_portfolios (creates both W1 tables)
  - Alembic revision p11_b2_uuid_fk_config_move (B2 retype + CASCADE FK + D-09 data move)
  - save_config/load_config backed by portfolios.config_json
  - strategy_portfolio_subscriptions.portfolio_id as Uuid with a CASCADE FK
  - tests/support/schema.py::seed_portfolio_definitions
affects:
  - migrations
  - itrader/storage
  - itrader/portfolio_handler/storage
  - itrader/strategy_handler
tech-stack:
  added: []
  patterns:
    - guard-before-destructive-op as the FIRST statement of upgrade()
    - data movement in a migration via parameterized Core with typed throwaway Tables
    - negative control proving a by-value migration assertion is non-vacuous
    - central MetaData registration in a store __init__ instead of N create_all call sites
key-files:
  created:
    - migrations/versions/p11_venue_accounts_portfolios.py
    - migrations/versions/p11_b2_uuid_fk_config_move.py
    - tests/integration/test_p11_migration_chain.py
  modified:
    - migrations/env.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - itrader/portfolio_handler/storage/models.py
    - itrader/portfolio_handler/storage/cached_sql_storage.py
    - itrader/storage/strategy_registry_store.py
    - itrader/strategy_handler/lifecycle/manager.py
    - itrader/strategy_handler/registry/rehydrate.py
    - tests/support/schema.py
    - tests/support/strategy_catalog.py
    - tests/integration/storage/test_migrations.py
    - tests/integration/storage/test_cached_sql_portfolio_storage.py
    - tests/integration/test_strategy_add_warmup.py
    - tests/integration/test_strategy_external_add_lifecycle.py
    - tests/integration/test_strategy_registry_restart.py
    - tests/unit/storage/test_strategy_registry_store.py
    - tests/unit/strategy/test_rehydrate.py
    - tests/unit/strategy/test_strategy_command_verbs.py
decisions:
  - "Revision 2 uses DROP + CREATE, not batch_alter_table — the plan's two constraints were mutually unsatisfiable on Postgres (see Plan drift 1)"
  - "load_config falls back to the legacy column when the definition row is absent OR its config_json is NULL — strictly lossless, cannot shadow a legacy blob"
  - "StrategyRegistryStore.__init__ registers the portfolio-definition tables (one edit, not ten); module-top import per the owner's no-lazy-imports rule, verified against the inertness gate"
  - "_resolve_portfolio_id keeps its string arm (plan option a) and the negative-path test exercises it directly"
metrics:
  duration: ~2h
  completed: 2026-07-21
requirements: [MPORT-02]
status: complete
---

# Phase 11 Plan 03: D-29 Migration Chain + D-09 Config Rehome Summary

Two chained Alembic revisions complete the W1 schema boundary: revision 1 creates
`venue_accounts` then `portfolios` (FK direction forces the order), revision 2 guards, retypes
the B2 subscription column to `Uuid` with an `ON DELETE CASCADE` FK, and performs the first
genuine data movement in this migration chain's history — relocating the per-portfolio config
blob from a STATE row onto a DEFINITION row. The B2 fold-in lands at the ORM layer in the same
plan so migration and registrar agree.

## What Was Built

**Task 1 — Revision 1** (commit `2b00f4c8`)

`p11_venue_accounts_portfolios` off the measured head `p10_strategy_portfolio_subs`. Pure DDL,
so no guard. `venue_accounts` is created first because `portfolios` carries the composite FK;
`downgrade()` drops the child first.

Critically, this task also closed the **silent-failure trap 11-01's executor handed off**:
`migrations/env.py` now registers both registrars on `target_metadata`. Before this, the
create_all-vs-migration parity gate passed only because *neither* side knew the tables existed
— a green result that would have let the tables live in tests and never in production.

**Task 2 — Revision 2** (commit `282ac0d6`)

`_refuse_if_subscriptions_hold_data()` is the first statement of `upgrade()`. Probed directly:

```
GUARD FIRED: REFUSING to retype 'strategy_portfolio_subscriptions.portfolio_id':
             the table holds 1 row(s). ...
rows preserved: 1          stamped at: p11_venue_accounts_portfolios
portfolio_id type (still String): VARCHAR
```

The refusal is non-destructive — the operator's row and the schema are untouched.

The D-09 move copies `config_json` verbatim via parameterized Core using throwaway `Table`
objects declared with their **real** types. That detail is load-bearing: a bare
`sa.table`/`sa.column` pair carries `NullType` and would move the blob as a raw string,
landing a double-encoded value that `load_config` returns as a `str` instead of a `dict`.
Orphaned rows are counted and logged, never fatal. The old column is deliberately not dropped.

**Task 3 — The D-09 rehome** (commit `c8854bf7`)

`save_config`/`load_config` now target `portfolios.config_json`, with names, signatures and the
verbatim `Optional[Dict[str, Any]]` return shape unchanged. Twelve new tests in
`tests/integration/test_p11_migration_chain.py`.

**Task 4 — The B2 ORM half** (commit `07074494`)

Registrar retyped to `Uuid` + CASCADE FK, all verbs retyped to `uuid.UUID`, all three `str()`
coercions dropped from `manager.py`, and both stale claims killed.

## Verification Evidence

| Gate | Result |
|---|---|
| `pytest tests -q` | **2661 passed, 6 skipped** (baseline 2645/6; +16 new tests) |
| `pytest tests/integration/test_p11_migration_chain.py -q` | 12 passed |
| `alembic heads` | `p11_b2_uuid_fk_config_move` — single head |
| upgrade → downgrade → upgrade (SQLite) | OK; `portfolio_id` CHAR(32), CASCADE FK intact |
| `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (oracle byte-exact) |
| `pytest tests/integration/test_okx_inertness.py -q` | 4 passed |
| `mypy` (strict) | Success, 253 source files |
| `git diff --stat` on `pyproject.toml` / `poetry.lock` | empty — zero-new-dependency gate holds |
| Tab-file added-line gates (`manager.py`, `rehydrate.py`) | 0 space-indented added lines |

**The Postgres arm genuinely runs here** (Docker present) — it is what caught the
`batch_alter_table` defect below, and a `DuplicateTable` leak during Task 3. Neither was
visible on SQLite.

**Every new gate was proven to fail before it passed.** The by-value config assertion, the
guard, and the CASCADE tests were all observed red first. The one exception is documented
under Plan drift 4 — a test that passed vacuously and had to be strengthened.

## Plan drift found

**1. `batch_alter_table` and "no USING cast" are mutually unsatisfiable on Postgres. (Critical)**

Plan claim (a `must_have`): the `String`→`Uuid` change "uses `batch_alter_table` … and NOT a
Postgres-only `USING ... ::uuid` cast."

Reality: `batch_alter_table` only does move-and-copy on **SQLite**. On Postgres it is a
passthrough emitting a plain `ALTER TABLE ... ALTER COLUMN portfolio_id TYPE UUID`, which
Postgres rejects:

```
(psycopg2.errors.DatatypeMismatch) column "portfolio_id" cannot be cast automatically to type uuid
HINT: You might need to specify "USING portfolio_id::uuid".
```

Observed against the testcontainers arm, not hypothesised. The only two ways to satisfy
`batch_alter_table` on Postgres are the forbidden cast or a recreate.

Action: **DROP + CREATE**, which honors the prohibition literally and its portability intent
more strongly than either alternative. This is safe *because of* the guard — the table is
proven empty before the recreate runs, so there is nothing for a cast to preserve. It also
makes the PK and both FKs explicit rather than depending on SQLite batch-mode reflection to
faithfully carry the existing `strategy_registry` FK across the rebuild. Full rationale is in
`_create_subscriptions`'s docstring.

**2. Owner decision 1 required a fallback arm, not just "keep the sentinel".**

The owner directed keeping `save_config`'s zero-sentinel INSERT arm. Retargeting the read/write
to `portfolios` while keeping that arm is only coherent as a **fallback**: the arm inserts into
`portfolio_account_state`, so `load_config` must also fall back there or
`test_config_restart_layering.py:175` (`save_config` then `load_config` on a portfolio with no
definition row) fails. Implemented as: definition row first, legacy column when the definition
row is absent **or** its `config_json` is NULL. The NULL clause is deliberate extra safety — it
cannot shadow a blob written through the legacy arm. Both pinning tests pass unmodified.

Consequently the plan's `<behavior>` bullet "*`save_config` … raises a loud, typed error*" was
**not** implemented — it is superseded by owner decision 1 and belongs to 11-08.

**3. Two acceptance greps count docstring prose, not code** (same class as 11-01's drift 1).

`grep -c 'batch_alter_table'` returns 2 and `grep -E '::uuid'` returns 3 on revision 2 — every
hit is prose explaining why those constructs are *not* used. Verified by inspection: zero code
usage of either. Flagging rather than silently passing, and rather than removing the
explanation to satisfy a token grep.

**4. One new test passed vacuously on first run and had to be strengthened.**

`test_load_config_returns_the_migrated_blob_through_the_store` was green before the storage
change existed — because revision 2 deliberately does *not* drop the old column, the store was
still reading the blob from `portfolio_account_state`. Fixed by NULLing the legacy column after
the upgrade, forcing the value to come from `portfolios`. This is exactly the failure mode the
audit warned about, caught only because the RED phase was actually inspected rather than
assumed.

**5. The negative control could not be built by monkeypatching.**

The plan-implied approach (stub `_move_config`) silently does nothing: Alembic re-imports each
revision module per `ScriptDirectory`, so the patched module object is not the one
`command.upgrade` executes. Observed — the log showed `1 blob(s) moved` with the stub in place.
Replaced with an A/B on the chain itself (stop at revision 1), which has no such failure mode.

**6. `test_migrations.py:494` does not cover B2 — confirmed** (audit correction 3 was right).

That registrar-vs-migration test compares column **names** only. Added an explicit column-TYPE
and FK assertion to `test_build_strategy_registry_tables_shape` instead, using
`target_fullname` rather than `.column` (the test builds only the registry tables on a bare
MetaData, so `.column` would raise `NoReferencedTableError`).

**7. Two hardcoded test lists silently outgrew their subjects.**

Registering `portfolios` in `SqlPortfolioStateStorage.__init__` made every consumer's
`create_all` build two more tables. `test_cached_sql_portfolio_storage.py::_PORTFOLIO_TABLES` —
a hardcoded PG drop list — did not know about them, so they leaked onto the shared session
container and reddened `test_migrations.py`'s Postgres arm with `DuplicateTable`. Same class as
`_NEW_TABLES`. Both lists extended by hand with a comment naming the maintenance obligation.

**8. Task 4's blast radius was larger than the plan's ten call sites.**

The plan's central fix (register in `__init__`) worked and kept the inertness gate green, as
predicted. But the retype broke ~29 tests, because the CASCADE FK means every test subscribing
a strategy to a portfolio now needs a real `portfolios` **row**, not just the table — and the
shared `seeded_registry_rows` helper was emitting `str(portfolio_id)`. Resolved with a new
shared `tests/support/schema.py::seed_portfolio_definitions` helper rather than duplicating the
row shape across six files.

**9. Owner preference applied over plan text.** The plan's preferred fix implied a local import
inside `__init__`. Per the owner's no-lazy-imports rule this is a module-top import; verified
against `test_okx_inertness.py`, which stays green (it asserts the registrar's *return dict*
and the bare-MetaData table set — neither changes).

## Deferred / handoff to 11-08

- Delete the `save_config`/`load_config` legacy arm once `PortfolioDefinitionStore` is wired and
  a definition row is genuinely guaranteed. Both arms are commented `removed by 11-08`.
- Retire `portfolio_account_state.config_json` and the cached carry-forward together. Both are
  marked VESTIGIAL POST-D-09 in place so a future reader does not restore writes to the
  abandoned column (audit correction 8).
- `A1` still stands: a manual `SELECT count(*) FROM strategy_portfolio_subscriptions` in the
  owner's deployed database before running revision 2 remains worthwhile. The guard makes a
  wrong assumption loud rather than destructive, but it does not verify the assumption.
- `A2` unchanged: whether P12's TEST-03 exercises config by method or by direct table read is
  still unverifiable (Phase 12 does not exist).

## Threat Flags

None beyond the register. The three mitigations assigned to this plan are implemented and
test-covered: **T-11-10** (config move asserted by value, with a negative control), **T-11-11**
(guard-before-mutation, proven non-destructive), **T-11-12** (dialect portability — resolved
more strongly than planned, since DROP + CREATE uses no dialect-specific SQL at all). T-11-13
holds: the moved blob is operator-authored config and carries no credential material.
T-11-SC holds: no packages installed, `pyproject.toml`/`poetry.lock` untouched.

## Self-Check: PASSED

- FOUND: migrations/versions/p11_venue_accounts_portfolios.py
- FOUND: migrations/versions/p11_b2_uuid_fk_config_move.py
- FOUND: tests/integration/test_p11_migration_chain.py
- FOUND: 2b00f4c8, 282ac0d6, c8854bf7, 07074494
