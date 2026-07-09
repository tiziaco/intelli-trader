---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
verified: 2026-07-09T18:16:34Z
status: passed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 4: Storage Schema — Migrations Relocation + New Durable Stores Verification Report

**Phase Goal:** Land the full live storage schema as one cohesive unit — FIRST relocate the Alembic
migrations tree from the shipped package to project root (staying out of the wheel), THEN add the
three new durable SQL stores (SystemStore, VenueStore, StrategyRegistryStore) on the HaltRecordStore
template, extending the chained migration sequence in the new location and rehydrating on restart.
Live-only composition-root infrastructure that leaves the backtest path untouched.

**Verified:** 2026-07-09T18:16:34Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SQL-01: `migrations/` relocated to project root, out of the wheel; `alembic.ini` `script_location` updated; `env.py` still imports `build_*_table` registrars + `NAMING_CONVENTION` from `itrader.storage` | ✓ VERIFIED | `migrations/env.py` exists at repo root; `itrader/storage/migrations/` confirmed absent. `alembic.ini:8` = `script_location = migrations`; `sqlalchemy.url` blank (line 90). `migrations/env.py:30-38` imports all 7 registrars + `NAMING_CONVENTION` from `itrader.storage`/`itrader.*`. `test_migrations_relocated_out_of_wheel` (tomllib-based `pyproject.toml` check) passes; `tool.poetry.packages == [{"include": "itrader"}]` confirmed directly via grep. |
| 2 | D-10: 5 existing revisions moved via `git mv` UNCHANGED — IDs preserved, chain not squashed | ✓ VERIFIED | `git show --stat d8a9fc46` shows pure renames (`{itrader/storage/migrations => migrations}/...`, `0 insertions(+), 0 deletions(-)` across all 8 tracked files). `git log --follow -- migrations/versions/d10_halt_records.py` shows unbroken history back through the pre-move commit `7566f7ee`. |
| 3 | SystemStore: `(key, value_json, updated_at)` natural-PK KV store, namespaced upsert overwrites same key (STORE-01) | ✓ VERIFIED | `itrader/storage/system_store.py` — `build_system_store_table` defines `key` (String PK, no `idgen`/`Uuid` import), `value_json` (`json_variant()`), `updated_at` (`UtcIsoText`). `upsert()` is delete-then-insert in one `engine.begin()` transaction. `tests/unit/storage/test_system_store.py` (6 tests) passes, including namespaced-upsert idempotency. `mypy --strict` clean. |
| 4 | VenueStore: `(venue_name PK, enabled, config_json, updated_at)`, typed `enabled`/`list_enabled()`; never stores secrets via write-time recursive denylist guard (STORE-02) | ✓ VERIFIED | `itrader/storage/venue_store.py` — typed `Boolean` `enabled` column; `list_enabled()` filters `enabled.is_(True)`. `_assert_no_secret_keys` recursively walks dicts/lists at any depth against a 10-entry `_SECRET_KEY_DENYLIST`, fires at top of `upsert()` before the delete-then-insert. `tests/unit/storage/test_venue_store.py` (7 tests) passes, including nested and top-level secret-key rejection leaving the store empty. `mypy --strict` clean. |
| 5 | StrategyRegistryStore: two tables (`strategy_registry` + FK'd `strategy_subscriptions`), rehydrate JOINs both, durable key is strategy NAME not runtime UUID (STORE-03) | ✓ VERIFIED | `itrader/storage/strategy_registry_store.py` — `build_strategy_registry_tables` returns `dict[str, Table]` with `strategy_registry` (name PK) and `strategy_subscriptions` (`ForeignKey("strategy_registry.strategy_name")`, natural composite PK `(strategy_name, venue, symbol, timeframe)`). `read_all()` does a LEFT OUTER JOIN grouping subscriptions per strategy. `tests/unit/storage/test_strategy_registry_store.py` (8 tests) passes, including `test_set_subscriptions_and_join_rehydrate` and a genuine file-backed dispose→reopen `test_restart_survival_file_backed` (not `:memory:` — Pitfall 4 correctly avoided). `mypy --strict` clean. |
| 6 | STORE-04: each store clones the `HaltRecordStore` template (composes `sql_engine`, own registrar, idempotent `create_all`, dispose delegation, parameterized Core); the chained migration `d10_halt_records → system_store → venue_config → strategy_registry` is authored in `migrations/` | ✓ VERIFIED | All 3 stores follow the identical `__init__(sql_engine)` / `self.backend`/`self.engine` / `create_all(checkfirst=True)` / `dispose()` delegating to `self.backend.dispose()` shape. All SQL uses `sqlalchemy.{delete,insert,select,update}` against constant `Table` objects — no f-strings. `migrations/versions/{system_store,venue_config,strategy_registry}.py` chain `down_revision` linearly off `d10_halt_records`; `strategy_registry.py` creates both tables in one `upgrade()`, `downgrade()` drops the FK child (`strategy_subscriptions`) first. |
| 7 | SQL-02: `alembic heads == 1` (`strategy_registry`); `alembic upgrade head` on a clean DB applies the full chain; create_all/migration parity holds | ✓ VERIFIED | `poetry run python -c "...get_heads()"` → `['strategy_registry']` (single head, matches D-11 chain). `tests/integration/storage/test_migrations.py` (7 tests, all pass): `test_migration_chain_is_single_head`, `test_full_chain_upgrade_creates_new_stores_sqlite` (file-backed, asserts the 4 new tables + single `alembic_version` row stamped at `strategy_registry`), `test_create_all_vs_migration_parity` (compares table + column sets between registrar-`create_all` engine A and `upgrade head` engine B — genuine two-engine comparison, not a stub). |
| 8 | STORE-05: an in-memory fallback / live-only design keeps the backtest path untouched — oracle byte-exact, `test_okx_inertness.py` green with extended register-vs-build assertion | ✓ VERIFIED | `tests/integration/test_okx_inertness.py` `_FORBIDDEN` tuple includes `itrader.storage.system_store`/`venue_store`/`strategy_registry_store` (verified via grep, lines 79-81); `test_new_store_registrars_are_register_vs_build` (lines 201-229) builds all 3 registrars on a bare `MetaData` and asserts no `Engine` is constructed and exactly the 4 expected table names register. `poetry run pytest tests/integration/test_okx_inertness.py -q` → 3 passed. `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed, byte-exact against the frozen golden `46189.87730727451` (`tests/golden/`). |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `migrations/env.py` | Relocated Alembic environment, imports all registrars | ✓ VERIFIED | Present, substantive, imports 7 registrars + `NAMING_CONVENTION`, import-inert (no Engine/Settings at module scope). |
| `migrations/versions/d10_halt_records.py` (+ 4 prior revisions) | Preserved unchanged at new location | ✓ VERIFIED | Present; `git show --stat` on the move commit confirms 0 line changes. |
| `alembic.ini` | `script_location = migrations` | ✓ VERIFIED | Confirmed via grep; `sqlalchemy.url` blank, `prepend_sys_path = .` untouched. |
| `tests/integration/storage/test_migrations.py` | Gate tests incl. wheel-exclusion, single-head, full-chain upgrade, parity | ✓ VERIFIED | 7 tests, all pass; each is a real assertion against live SQLite/tomllib state, not a placeholder. |
| `itrader/storage/system_store.py` | `SystemStore` + `build_system_store_table` | ✓ VERIFIED | Present, substantive, wired (imported by `migrations/env.py`, `test_migrations.py`, `test_okx_inertness.py`, own unit test). |
| `itrader/storage/venue_store.py` | `VenueStore` + `build_venue_store_table` + secret guard | ✓ VERIFIED | Present, substantive, wired. |
| `itrader/storage/strategy_registry_store.py` | `StrategyRegistryStore` + `build_strategy_registry_tables` | ✓ VERIFIED | Present, substantive, wired. |
| `tests/unit/storage/test_system_store.py` | Unit coverage | ✓ VERIFIED | 6 tests, all pass. |
| `tests/unit/storage/test_venue_store.py` | Unit coverage incl. secret-guard | ✓ VERIFIED | 7 tests, all pass. |
| `tests/unit/storage/test_strategy_registry_store.py` | Unit coverage incl. file-backed restart | ✓ VERIFIED | 8 tests, all pass. |
| `migrations/versions/system_store.py` | Revision `system_store` | ✓ VERIFIED | Present; `down_revision="d10_halt_records"`; hand-authored type imports + `op.f(...)` naming. |
| `migrations/versions/venue_config.py` | Revision `venue_config` (builds `venue_store` table) | ✓ VERIFIED | Present; slug ≠ table name confirmed (creates `venue_store`). |
| `migrations/versions/strategy_registry.py` | Revision `strategy_registry` (builds 2 tables) | ✓ VERIFIED | Present; creates both tables, FK-ordered downgrade. |
| `tests/integration/test_okx_inertness.py` | Extended `_FORBIDDEN` + register-vs-build test | ✓ VERIFIED | Present, extended correctly; 3 tests pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `alembic.ini` `script_location` | `migrations/env.py` | relative path + `prepend_sys_path = .` | ✓ WIRED | `alembic upgrade head` / `get_heads()` resolve correctly from repo root. |
| `migrations/env.py` `target_metadata` | 3 new registrars | direct import + call on shared `MetaData` | ✓ WIRED | `build_system_store_table(target_metadata)`, `build_venue_store_table(target_metadata)`, `build_strategy_registry_tables(target_metadata)` called after `build_halt_records_table` (lines 77-79). |
| `build_*_table` registrars | store `create_all` AND `migrations/env.py` | shared single-source-of-truth function | ✓ WIRED | `test_create_all_vs_migration_parity` proves both paths produce identical table/column sets. |
| `VenueStore.upsert` | `_assert_no_secret_keys` guard | call at top of method, before delete-then-insert | ✓ WIRED | Read directly in source; guard call precedes `with self.engine.begin()`. |
| `tests/integration/test_okx_inertness.py::_FORBIDDEN` | 3 new store modules | forbidden-import subprocess probe | ✓ WIRED | Modules listed; probe still prints `INERTNESS_OK` (test passes). |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SQL-01 | 04-01 | Migrations relocation + wheel exclusion | ✓ SATISFIED | Truths #1, #2; artifacts verified. |
| SQL-02 | 04-03 | Alembic gate: single-head, upgrade head, create_all/migration parity | ✓ SATISFIED | Truth #7; `test_migrations.py` gate green. |
| STORE-01 | 04-02 | SystemStore cardinality-1 KV | ✓ SATISFIED | Truth #3. |
| STORE-02 | 04-02 | VenueStore, never stores secrets | ✓ SATISFIED | Truth #4. |
| STORE-03 | 04-02 | StrategyRegistryStore, which strategies + config + subscriptions | ✓ SATISFIED | Truth #5. |
| STORE-04 | 04-02 / 04-03 | HaltRecordStore-template clone + chained migration | ✓ SATISFIED | Truth #6. |
| STORE-05 | 04-02 / 04-03 | In-memory fallback / live-only, backtest path untouched | ✓ SATISFIED | Truth #8. |

No orphaned requirements — REQUIREMENTS.md's P4 block (SQL-01, SQL-02, STORE-01..05) is fully covered by the three plans' `requirements` frontmatter; all 7 IDs also show `[x]` / "Complete" in REQUIREMENTS.md's tracking table.

### Anti-Patterns Found

None. Scanned all created/modified files (`itrader/storage/{system_store,venue_store,strategy_registry_store}.py`, the 3 new migration revisions, `migrations/env.py`, `alembic.ini`, `itrader/storage/engine.py`, and all 5 new/extended test files) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented"/"coming soon" — zero matches.

### Gate Commands Run (this verification, independent of SUMMARY claims)

| Gate | Result |
|------|--------|
| `alembic get_heads()` | `['strategy_registry']` — single head, matches D-11 |
| `poetry run pytest tests/integration/storage/test_migrations.py -q` | 7 passed |
| `poetry run pytest tests/unit/storage -q` | 44 passed |
| `poetry run pytest tests/integration/test_okx_inertness.py -q` | 3 passed |
| `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (byte-exact `46189.87730727451`) |
| `poetry run mypy itrader/storage/{system_store,venue_store,strategy_registry_store}.py` | Success: no issues found in 3 source files |
| `poetry run pytest tests/unit/storage tests/integration/storage -q` (full storage suite) | 103 passed |
| `git show --stat d8a9fc46` | Pure rename, 0 insertions/deletions across 8 files |
| `git log --follow -- migrations/versions/d10_halt_records.py` | History preserved through the move |
| Commit existence check (`d8a9fc46`, `ae7bb100`, `35693c1c`, `55735fb3`, `fa72fffd`, `fcbdf69f`, `2995c5d5`, `e8016834`, `1c93098a`) | All 9 commits found in git log |

### Human Verification Required

None. All must-haves resolve to observable, programmatically-verifiable code/test evidence; no visual, real-time, or external-service behavior is in scope for this phase.

### Context Notes (not gaps)

- D-01/D-02: the three stores are deliberately NOT constructed in `LiveTradingSystem` this phase. "Rehydrate on restart" is proven at the STORE level (file-backed dispose→reopen round-trip in `test_strategy_registry_store.py`), by design — live-system construction is deferred to P6/P9/P10. Confirmed this is the documented intent (D-02 in `migrations/env.py` docstring and 04-03 PLAN frontmatter) and not an omission.
- The advisory 04-REVIEW.md (0 blocker / 3 warning / 3 info) findings are pre-existing/latent design notes (exact-match secret denylist, unenforced SQLite FK, template-inherited create_all) — advisory, not phase-blocking must-haves; not re-litigated here.

### Gaps Summary

No gaps. All 8 derived observable truths (covering all 7 requirement IDs SQL-01, SQL-02, STORE-01..05 and the 4 ROADMAP success criteria) are VERIFIED against actual codebase state — file existence, substantive implementation (no stubs/placeholders), wiring (imports/calls confirmed), and behavior (all relevant test suites independently re-run and green, plus manual git-history/diff inspection of the migrations relocation). The backtest oracle stays byte-exact and the OKX inertness gate — extended for the 3 new store modules — passes.

---

_Verified: 2026-07-09T18:16:34Z_
_Verifier: Claude (gsd-verifier)_
