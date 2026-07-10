---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
plan: 03
subsystem: storage / migrations
tags: [alembic, migrations, durable-stores, inertness, sql-02, store-05]
requires: [04-01, 04-02]
provides:
  - "alembic head strategy_registry (was d10_halt_records)"
  - "migration chain for system_store / venue_store / strategy_registry / strategy_subscriptions"
  - "env.py target_metadata registration of the 3 new registrars (D-02)"
  - "SQL-02 full-chain gate (single-head + upgrade + create_all/migration parity)"
  - "STORE-05 inertness gate extension (forbid 3 store modules + register-vs-build)"
affects:
  - migrations/versions/
  - migrations/env.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/test_okx_inertness.py
tech-stack:
  added: []
  patterns:
    - "hand-authored Alembic revisions derived from build_* registrars (D-11)"
    - "custom-type import (itrader.storage.types + postgresql) in every UtcIsoText revision (Pitfall 2)"
    - "op.f(...) constraint naming per NAMING_CONVENTION (Pitfall 3)"
    - "revision slug != table name (venue_config builds venue_store, Pitfall 5)"
    - "register-vs-build: env.py + tests build Table-only on a bare MetaData"
key-files:
  created:
    - migrations/versions/system_store.py
    - migrations/versions/venue_config.py
    - migrations/versions/strategy_registry.py
  modified:
    - migrations/env.py
    - tests/integration/storage/test_migrations.py
    - tests/integration/test_okx_inertness.py
decisions:
  - "D-11: three hand-authored chained revisions off d10_halt_records, each derived from its build_*_table registrar (no pure-autogenerate blob)"
  - "D-04: strategy_registry revision creates both tables; downgrade drops the FK child (strategy_subscriptions) first"
  - "D-02: the 3 new stores are migration-target-registered only in env.py target_metadata, NOT constructed in LiveTradingSystem (deferred to P6/P9/P10)"
  - "Pitfall 5: venue_config slug builds the venue_store table (slug != table name)"
metrics:
  tasks: 3
  files_changed: 6
  completed: 2026-07-09
status: complete
---

# Phase 4 Plan 3: Storage Schema Migrations — 3 New Durable Stores Summary

Authored the three chained Alembic revisions (`system_store` → `venue_config` →
`strategy_registry`) off `d10_halt_records`, wired the three new store registrars into
`migrations/env.py` `target_metadata` (D-02), and landed the SQL-02 full-chain gate plus the
STORE-05 inertness extension — single head `strategy_registry`, oracle byte-exact.

## What Was Built

**Task 1 — three hand-authored chained revisions** (`2995c5d5`)
- `migrations/versions/system_store.py` (`revision="system_store"`, `down_revision="d10_halt_records"`):
  creates `system_store` (`key` String PK via `op.f("pk_system_store")`, `value_json` JSON/JSONB
  variant, `updated_at` `UtcIsoText`).
- `migrations/versions/venue_config.py` (`revision="venue_config"`, `down_revision="system_store"`):
  builds the **`venue_store`** table (slug ≠ table name, Pitfall 5) — `venue_name` PK, `enabled`
  Boolean, `config_json` variant, `updated_at`.
- `migrations/versions/strategy_registry.py` (`revision="strategy_registry"`,
  `down_revision="venue_config"`): `op.create_table` TWICE — `strategy_registry` (name PK) then
  `strategy_subscriptions` with `sa.ForeignKeyConstraint` named
  `fk_strategy_subscriptions_strategy_name_strategy_registry` + composite PK
  `pk_strategy_subscriptions`; `downgrade()` drops the FK child first.
- Each revision hand-writes `import itrader.storage.types` + `from sqlalchemy.dialects import postgresql`
  (Pitfall 2) and wraps every PK/FK in `op.f(...)` per `NAMING_CONVENTION` (Pitfall 3).
- Column definitions reproduced exactly from the Plan 04-02 registrars (single source of truth).

**Task 2 — env.py wiring + SQL-02 gate** (`e8016834`)
- `migrations/env.py`: added the 3 registrar imports and calls (`build_system_store_table`,
  `build_venue_store_table`, `build_strategy_registry_tables`) on `target_metadata` after
  `build_halt_records_table` — import-inert, Table-only, no `SqlEngine`/`Settings()` (D-02).
- `tests/integration/storage/test_migrations.py`: single-head assertion
  (`tuple(get_heads()) == ("strategy_registry",)`); file-backed SQLite `upgrade head` test asserting
  the 4 new tables present + one `alembic_version` row stamped at `strategy_registry`; a
  create_all-vs-migration parity test comparing table sets and per-table column-name sets across
  the registrar `create_all` (engine A) and `upgrade head` (engine B) paths.

**Task 3 — inertness gate extension** (`1c93098a`)
- `tests/integration/test_okx_inertness.py`: added `itrader.storage.system_store`,
  `itrader.storage.venue_store`, `itrader.storage.strategy_registry_store` to `_FORBIDDEN`;
  new `test_new_store_registrars_are_register_vs_build` proving the 3 registrars register exactly
  the 4 expected table names on a bare `MetaData` with no Engine / no `SqlSettings` constructed.

## Verification

- `alembic heads` → `('strategy_registry',)` (single head). ✅
- `poetry run pytest tests/integration/storage/test_migrations.py -q` → 7 passed. ✅
- `poetry run pytest tests/integration/test_okx_inertness.py -q` → 3 passed. ✅
- `poetry run pytest tests/integration/test_backtest_oracle.py` → 3 passed (byte-exact
  `46189.87730727451`). ✅
- `poetry run pytest tests/unit/storage tests/integration/storage -q` → 103 passed. ✅

## Deviations from Plan

None — plan executed exactly as written.

Note: the plan mentioned fixing a "stale docstring path-comment" in `env.py`, but `env.py`
already references `migrations/env.py` correctly (Plan 04-01 relocated the tree and updated the
docstring), so no cosmetic change was needed.

## Requirements Satisfied

- **SQL-02** — single-head chain + clean `upgrade head` creating all 4 new tables + create_all/migration parity.
- **STORE-04 / D-04** — `strategy_registry` revision creates both tables with FK + composite PK; child-first downgrade.
- **STORE-05** — inertness gate forbids the 3 new store modules on the backtest path + asserts register-vs-build.

## Self-Check: PASSED

- Created files exist: `migrations/versions/system_store.py`, `venue_config.py`, `strategy_registry.py`. ✅
- Commits exist: `2995c5d5`, `e8016834`, `1c93098a`. ✅
