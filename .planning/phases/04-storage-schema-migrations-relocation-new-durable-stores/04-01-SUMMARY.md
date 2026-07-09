---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
plan: 01
subsystem: storage
tags: [alembic, migrations, relocation, wheel-exclusion, SQL-01, D-10]
requires: []
provides:
  - "migrations/ at project root (relocated Alembic tree, 5 revision IDs preserved)"
  - "alembic.ini script_location = migrations"
  - "test_migrations.py::test_migrations_relocated_out_of_wheel (structural SQL-01 gate)"
affects:
  - "Plan 04-03 chains its 3 new revisions onto d10_halt_records in the relocated tree"
tech-stack:
  added: []
  patterns:
    - "git mv preserves revision-file history (rename-detected, not delete+add)"
    - "stdlib tomllib for build-free pyproject wheel-exclusion assertion"
key-files:
  created: []
  modified:
    - migrations/ (moved from itrader/storage/migrations/ — env.py, script.py.mako, versions/*)
    - alembic.ini
    - tests/integration/storage/test_migrations.py
    - itrader/storage/engine.py
decisions:
  - "D-10: 5 revisions moved via git mv UNCHANGED — IDs preserved, chain not squashed/re-stamped"
  - "SQL-01 wheel-exclusion made samplable via fast tomllib assertion (no poetry build in fast gate)"
metrics:
  duration: 1min
  completed: 2026-07-09
status: complete
---

# Phase 4 Plan 01: Migrations Relocation Summary

Mechanically relocated the Alembic migrations tree from the shipped package
`itrader/storage/migrations/` to project-root `migrations/` (SQL-01) via `git mv`, preserving
all 5 existing revision IDs unchanged (D-10), and added a fast structural gate proving the tree
now sits out of the shipped `itrader` wheel.

## What Was Built

**Task 1 — Relocation (commit `d8a9fc46`)**
- `git mv itrader/storage/migrations migrations` — all 8 tracked files (env.py, script.py.mako,
  versions/.gitkeep, and the 5 revision files) moved as git-detected renames; `git log --follow`
  on `migrations/versions/d10_halt_records.py` confirms history is preserved (move, not
  delete+add). `__pycache__` compiled artifacts were removed before the move (never staged).
- Revision chain unchanged and single-head: `2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id →
  hl5_transaction_venue_trade_id → d10_halt_records`. `alembic heads` prints exactly
  `d10_halt_records`.
- `alembic.ini` line 8: `script_location = itrader/storage/migrations` → `migrations`
  (`prepend_sys_path = .` and the intentionally-blank `sqlalchemy.url` left untouched — SEC-01 /
  T-04-03).
- `tests/integration/storage/test_migrations.py:31` `_MIGRATIONS_DIR` → `_REPO_ROOT / "migrations"`.
- `itrader/storage/engine.py` NAMING_CONVENTION path comment updated to `migrations/env.py`
  (cosmetic; convention body unchanged). `migrations/env.py` content NOT touched (owned by Plan
  04-03).

**Task 2 — Wheel-exclusion gate (commit `ae7bb100`)**
- Added `test_migrations_relocated_out_of_wheel` to `test_migrations.py`: asserts
  `migrations/env.py` exists at root, `itrader/storage/migrations` is absent, and (via stdlib
  `tomllib`) `tool.poetry.packages == [{"include": "itrader"}]`. Fast, build-free; fails loud if
  a future edit re-nests migrations or adds a second `packages` include. Kept in the package-LESS
  tests dir (no new `__init__.py` — collection-collision hazard), 4-space indentation.

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/integration/storage/test_migrations.py -q` | 4 passed |
| `pytest tests/integration/test_backtest_oracle.py` (byte-exact `46189.87730727451`) | 3 passed |
| `pytest tests/integration/test_okx_inertness.py` | 2 passed |
| `alembic heads` | `d10_halt_records` (single head) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Recovered Task-1 edits dropped by an aborted multi-pathspec `git add`**
- **Found during:** Post-plan tree check (after all tests green).
- **Issue:** The Task-1 staging command listed a stale pathspec (`itrader/storage/migrations`,
  already removed by `git mv`). `git add` aborted on the bad pathspec and staged nothing from
  that invocation, so the `alembic.ini` and `engine.py` edits never entered commit `d8a9fc46`
  (which holds only the renames). `test_migrations.py`'s Task-1 edit was salvaged because Task 2
  re-staged that file. The dropped edits were present in the working tree for every test run
  (all gates green), just uncommitted.
- **Fix:** Committed the two edits in follow-up `35693c1c`; re-ran the full gate set (9 passed)
  from the committed state to confirm.
- **Files modified:** `alembic.ini`, `itrader/storage/engine.py`
- **Commit:** `35693c1c`

No other deviations. Rules 1/2/4 not triggered; no auth gates.

## Threat Flags

None — no new security surface. `sqlalchemy.url` remains blank (T-04-03 mitigated); revision
lineage preserved byte-unchanged (T-04-01b mitigated); no install step (T-04-SC — nothing to
verify).

## Known Stubs

None.

## Self-Check: PASSED

- `migrations/env.py`, `migrations/versions/d10_halt_records.py`, `test_migrations.py`, `04-01-SUMMARY.md` all present.
- `itrader/storage/migrations/` confirmed gone.
- Commits `d8a9fc46`, `ae7bb100` present in history.
