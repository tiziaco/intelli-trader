---
phase: 11-multi-portfolio-live
plan: 01
subsystem: storage
tags: [storage, schema, multi-portfolio, security, sqlalchemy]
requires: []
provides:
  - venue_accounts table + VenueAccountStore
  - portfolios table + PortfolioDefinitionStore
  - build_venue_accounts_table registrar
  - build_portfolio_definition_tables registrar
affects:
  - itrader/storage
tech-stack:
  added: []
  patterns:
    - composite natural-key store (no surrogate id)
    - table-level ForeignKeyConstraint for a two-column reference
    - reused denylist guard imported from venue_store (never rebuilt)
key-files:
  created:
    - itrader/storage/venue_account_store.py
    - itrader/storage/portfolio_definition_store.py
    - tests/unit/storage/test_venue_account_store.py
    - tests/unit/storage/test_portfolio_definition_store.py
  modified: []
decisions:
  - "build_portfolio_definition_tables delegates to build_venue_accounts_table so the composite FK always resolves on any consumer's MetaData"
  - "used to_money(x) rather than the plan's to_money(str(x)) — to_money already does Decimal(str(x)) internally"
  - "reworded docstring prose that tripped literal grep gates for 'idgen' / 'create_all'"
metrics:
  duration: ~30m
  completed: 2026-07-21
requirements: [MPORT-02]
status: complete
---

# Phase 11 Plan 01: W1 Schema Boundary — venue_accounts + portfolios Summary

Two schema-pure definition stores on the shared `SqlEngine` spine: `venue_accounts` keyed on
the composite natural `(venue_name, account_id)` pair with the D-05 three-lifecycle column
split, and `portfolios` — the definition row seven portfolio-scoped child tables never had —
carrying an unconditional composite FK to `venue_accounts` plus the PLAIN D-14 unique
constraint that makes a two-portfolios-on-one-account collision structurally impossible.

## What Was Built

**Task 1 — `itrader/storage/venue_account_store.py`** (commit `f6be1bd1`, tests `2072c6a6`)

- `venue_accounts` with the composite natural PK `(venue_name, account_id)` (D-01). No
  surrogate id column; no UUIDv7 generator imported.
- The D-05 three-lifecycle split: `secret_ref` (operator-rotated pointer, nullable),
  `venue_uid` (engine-written TOFU, nullable, written later by 11-04), `config_json`
  (operator-authored), plus typed `enabled` and `updated_at`.
- D-02: the credential column is a POINTER named `secret_ref`, never `credentials`. The
  recursive `_assert_no_secret_keys` guard is **imported and reused** from `venue_store.py`
  (not rebuilt as a second denylist that could drift) and fires as the first statement of
  `upsert`, before the transaction opens.
- D-06: a paper row (`venue_name='paper'`, `secret_ref=None`) round-trips.
- `read_all()` has an explicit `ORDER BY venue_name, account_id` (MPORT-03 stability).

**Task 2 — `itrader/storage/portfolio_definition_store.py`** (commit `6bbd7f96`, tests `69503f89`)

- `portfolios` with the exact D-07 column set (`portfolio_id` `Uuid` PK matching
  `orders.portfolio_id`, `name`, `venue_name`, `account_id` NOT NULL, `initial_cash`
  `Numeric`, `enabled`, nullable `config_json`, `updated_at`) and **no `exchange` column**.
- Table-level `ForeignKeyConstraint(['venue_name','account_id']) -> venue_accounts`,
  unconditional.
- PLAIN `UniqueConstraint('venue_name','account_id')` — the D-14 / T-11-02 DB half.
- Money enters the Decimal domain via `to_money`; `initial_cash` reads back as `Decimal`.
- `read_all()` orders by `portfolio_id` ASC so 11-08's rehydrate order is deterministic.

Task 3 (the B2 fold-in) was correctly absent per the plan-correction notice.
`itrader/storage/strategy_registry_store.py` was **read only** and not edited.

## Verification Evidence

| Gate | Result |
|---|---|
| `pytest tests -q` | **2619 passed, 6 skipped** (baseline 2600/6; +19 = the new tests) |
| `pytest tests/unit/storage -q` | 77 passed |
| `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (oracle byte-exact) |
| `pytest tests/integration/test_okx_inertness.py -q` | 4 passed |
| `mypy` (strict) | Success, 253 source files |
| `git diff --stat` on `pyproject.toml` / `poetry.lock` | empty — zero-new-dependency gate holds |
| Tab-free (`grep -cP '^\t'`) both new modules | 0 |

**Constraint tests proven to fire for the intended reason.** Both modules were absent before
this plan, so no acceptance criterion was green before the change. A probe confirmed the two
`IntegrityError` assertions are raised by the declared constraints, not incidentally:

```
DUPLICATE PAIR -> UNIQUE constraint failed: portfolios.venue_name, portfolios.account_id
ORPHAN FK     -> FOREIGN KEY constraint failed
```

SQLite FK enforcement is genuinely active via the dialect-guarded `PRAGMA foreign_keys=ON`
connect-hook at `itrader/storage/engine.py:61-71`.

## Plan drift found

**1. Two acceptance grep gates counted docstring prose, not real usage.**
Claim: `grep -c 'idgen'` and `grep -c 'create_all'` on the new modules return 0.
Reality: both returned non-zero on first pass purely from explanatory docstring text
("`idgen` never imported", "no runtime `create_all`") — the exact prose the template file
`venue_store.py` uses verbatim, so the analog would fail the same gates. There was never any
real `idgen` import or `create_all` call.
Action: reworded the prose to equivalent wording ("no UUIDv7 id generator is imported",
"never creates its own schema at runtime") so the gates are unambiguous. Meaning and decision
citations preserved; zero behavior change. This is the known tab-gate-style false-failure
pattern applied to token greps — flagging rather than silently passing.

**2. `to_money(str(x))` is redundant.**
Plan action text specifies `to_money(str(...))`. `itrader/core/money.py:60-74` shows
`to_money` already does `Decimal(str(x))` internally and has a `type(x) is Decimal` fast path
that the extra `str()` would bypass. Used `to_money(x)`. Same D-04 guarantee, no
`Decimal(float)` anywhere.

**3. The registrar had to register the PARENT table too — not stated in the plan.**
The plan specifies `build_portfolio_definition_tables(metadata) -> dict[str, Table]` but does
not say the `venue_accounts` parent must be present on the same `MetaData`. A composite
`ForeignKeyConstraint` resolves by table name at DDL-emit time, so a consumer that registered
only `portfolios` raises `NoReferencedTableError`. The registrar now delegates to
`build_venue_accounts_table(metadata)` and returns
`{"venue_accounts": ..., "portfolios": ...}` — one definition of the parent, FK always
resolvable. This is what makes the plural `dict[str, Table]` return shape correct.

**4. Worktree `.venv` shadowing (environmental, not a plan defect).**
Bare `poetry run pytest` resolved `itrader` through the editable install pointing at the main
checkout, so new worktree modules were invisible (`ModuleNotFoundError`). All test runs used
`poetry run env PYTHONPATH=<worktree> pytest ...`.

## Handoff to plan 11-03

`migrations/env.py` does **not** import the two new registrars — deliberate, since D-28 scopes
Alembic revisions to 11-03. Consequence: the new tables are currently absent from the Alembic
`target_metadata`, so the create_all-vs-migration parity test passes only because neither side
knows about them. Plan 11-03 must add `build_venue_accounts_table` and
`build_portfolio_definition_tables` to `migrations/env.py` alongside the Revision 2 migration,
or the tables will exist in tests and never in production.

## Deviations from Plan

Items 1-3 above are the deviations; all are documented under "Plan drift found". No Rule 4
architectural decisions were required. No packages installed (T-11-SC gate holds).

## Threat Flags

None. No new security-relevant surface beyond the threat register: the two mitigations
assigned to this plan (T-11-01 secret-pointer discipline, T-11-02 DB-level unique constraint)
are both implemented and test-covered. T-11-03 (`ON DELETE CASCADE` FK) belongs to 11-03 as
planned; T-11-04 `venue_uid` is column-only here, written by 11-04, as accepted.

## Self-Check: PASSED

- FOUND: itrader/storage/venue_account_store.py
- FOUND: itrader/storage/portfolio_definition_store.py
- FOUND: tests/unit/storage/test_venue_account_store.py
- FOUND: tests/unit/storage/test_portfolio_definition_store.py
- FOUND: 2072c6a6, f6be1bd1, 69503f89, 6bbd7f96
