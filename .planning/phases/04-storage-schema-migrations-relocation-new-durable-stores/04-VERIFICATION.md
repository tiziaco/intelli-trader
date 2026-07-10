---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
verified: 2026-07-10T00:00:00Z
status: passed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 8/8
  gaps_closed:
    - "CR-01 (post-review BLOCKER, found AFTER the prior 2026-07-09 verification): StrategyRegistryStore.upsert deleted the FK-parent row on overwrite, violating strategy_subscriptions FK once WR-02 turned on SQLite PRAGMA foreign_keys=ON — fixed to update-in-place-or-insert."
    - "WR-02 (04-04): SQLite connections now enforce declared foreign keys via a dialect-guarded SqlEngine connect-hook (PRAGMA foreign_keys=ON), matching Postgres."
    - "WR-03/D-14 (04-04): all 7 durable stores made schema-pure (create_all removed from __init__); shared tests/support/schema.py::provision_schema test seam added; ephemeral results store correctly retains its create_all."
    - "IN-01 (04-04 + post-review): StrategyRegistryStore.read_all now has a deterministic ORDER BY (strategy_name ASC, then venue/symbol/timeframe ASC)."
    - "IN-02 (post-review): Decimal(\"0\") zero-seed made consistent between get_reserved_cash and get_locked_margin."
  gaps_remaining: []
  regressions: []
gaps: []
---

# Phase 4: Storage Schema — Migrations Relocation + New Durable Stores Verification Report

**Phase Goal:** Land the full live storage schema as one cohesive unit — FIRST relocate the Alembic
migrations tree from the shipped package to project root (staying out of the wheel), THEN add the
three new durable SQL stores (`SystemStore`, `VenueStore`, `StrategyRegistryStore`) on the
`HaltRecordStore` template, extending the chained migration sequence in the new location and
rehydrating on restart. Live-only composition-root infrastructure that leaves the backtest path
untouched.

**Verified:** 2026-07-10T00:00:00Z
**Status:** passed
**Re-verification:** Yes — this refreshes the 2026-07-09T18:16:34Z "passed" report to independently
re-check the codebase AFTER 04-04 (gap remediation: WR-02/IN-01/WR-03) and the post-review
remediation commits (CR-01 BLOCKER fix + IN-01/IN-02 nits, per `04-REVIEW.md`). SUMMARY.md and
04-REVIEW.md claims were NOT trusted — every fix below was independently located in source and
exercised by test.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SQL-01: `migrations/` relocated to project root, out of the wheel; `alembic.ini` `script_location` updated; `env.py` still imports `build_*_table` registrars + `NAMING_CONVENTION` from `itrader.storage` | ✓ VERIFIED | `itrader/storage/migrations/` absent (`ls` confirms `No such file or directory`); `migrations/versions/` holds all 8 revision files at repo root. `alembic.ini:8` = `script_location = migrations`. `pyproject.toml:8` `packages = [{include = "itrader"}]` — the relocated tree sits outside the shipped package. |
| 2 | D-10 / SQL-02: single-head chained migration `2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id → d10_halt_records → system_store → venue_config → strategy_registry`, `alembic heads == 1` | ✓ VERIFIED | Ran `ScriptDirectory.from_config(...).get_heads()` directly (not via SUMMARY claim): `['strategy_registry']`. Walked the full revision chain — matches the documented D-10/D-11 order exactly, no branch/orphan. |
| 3 | STORE-01: `SystemStore` cardinality-1 `(key, value_json, updated_at)` natural-PK KV, namespaced upsert overwrites same key | ✓ VERIFIED | `itrader/storage/system_store.py` — `key` is a natural `String` PK (no `idgen`/`Uuid`), `value_json` via `json_variant()`, `updated_at` via `UtcIsoText`. `upsert()` is delete-then-insert in one `engine.begin()`. `tests/unit/storage/test_system_store.py` (6 tests) passes. |
| 4 | STORE-02: `VenueStore` `(venue_name PK, enabled, config_json, updated_at)`, typed `enabled`/`list_enabled()`, never stores secrets (recursive denylist guard) | ✓ VERIFIED | `itrader/storage/venue_store.py` — `_SECRET_KEY_DENYLIST` frozenset (10 entries) checked via `_assert_no_secret_keys` BEFORE the write; `list_enabled()` filters `enabled.is_(True)`. Guard confirmed unmodified per 04-04's explicit prohibition. `tests/unit/storage/test_venue_store.py` (7 tests) passes. |
| 5 | STORE-03: `StrategyRegistryStore` two tables (`strategy_registry` + FK'd `strategy_subscriptions`), rehydrate JOINs both, durable key is strategy NAME | ✓ VERIFIED | `itrader/storage/strategy_registry_store.py` — `build_strategy_registry_tables` returns both tables; child FK'd on `strategy_registry.strategy_name`, natural composite PK. `read_all()` LEFT OUTER JOINs and groups per strategy. `tests/unit/storage/test_strategy_registry_store.py` now has **11 tests** (up from 8 at the prior verification), including the CR-01/WR-02/IN-01 regression tests below. |
| 6 | CR-01 (post-review BLOCKER, closed): `StrategyRegistryStore.upsert` no longer deletes the FK-parent row on overwrite — update-in-place-or-insert, so `upsert → set_subscriptions → upsert` (live re-config path) no longer raises `IntegrityError` under FK enforcement | ✓ VERIFIED | Read `upsert()` source directly: `update(...)` first, `insert(...)` only `if updated.rowcount == 0` — no `delete()` on the parent row anywhere in the method. Regression test `test_upsert_of_subscribed_strategy_preserves_children` (line 194) exists and passes. Commit `53a90b07` found in `git log`. |
| 7 | WR-02 (closed): SQLite connections enforce declared FKs via a dialect-guarded `SqlEngine` connect-hook (`PRAGMA foreign_keys=ON`), matching Postgres | ✓ VERIFIED | `itrader/storage/engine.py:61-71` — `if self.engine.dialect.name == "sqlite": @event.listens_for(self.engine, "connect") ... cursor.execute("PRAGMA foreign_keys=ON")`. Regression test `test_set_subscriptions_on_unregistered_strategy_raises_integrity_error` (line 177) passes — proves the PRAGMA actually enforces on SQLite now. |
| 8 | WR-03/D-14 (closed): the 7 durable stores are schema-pure (no `create_all` in `__init__`); a shared `tests/support/schema.py::provision_schema` test seam provisions explicitly; the ephemeral results store correctly RETAINS its own `create_all` (prohibition honored) | ✓ VERIFIED | `grep create_all` across all 7 durable-store modules shows zero executable `create_all(` calls (docstring mentions only) — construction only registers tables via `build_*_table`. `itrader/results/sql_storage.py:94` still has `sql_engine.metadata.create_all(self.engine, checkfirst=True)` — untouched per the 04-04 prohibition. `tests/support/schema.py::provision_schema` exists, is the single seam, called by every durable-store test after construction. |
| 9 | IN-01 (closed): `StrategyRegistryStore.read_all` returns strategies in `strategy_name` ASC order, each record's subscriptions in `(venue, symbol, timeframe)` ASC order | ✓ VERIFIED | `read_all()` `.order_by(strategy_registry.c.strategy_name.asc(), strategy_subscriptions.c.venue.asc(), .symbol.asc(), .timeframe.asc())` present in source. Regression test `test_read_all_is_deterministically_ordered` (line 220) passes. |
| 10 | SQL-02: `alembic upgrade head` on a clean DB applies the full 8-revision chain and creates the 4 new tables; a `create_all`-vs-migration parity test proves the registrars are the single source of truth for both paths (over the FULL chain, post-WR-03 caller change) | ✓ VERIFIED | `tests/integration/storage/test_migrations.py::test_full_chain_upgrade_creates_new_stores_sqlite` and `::test_create_all_vs_migration_parity` both independently re-run — pass. Parity test calls the 7 registrars directly on a bare `MetaData` (not via store construction) confirming the WR-03 "caller moved store→fixture" claim didn't silently break the parity gate. |
| 11 | Milestone gate: backtest oracle byte-exact (`134 / 46189.87730727451`); OKX import-inertness green; `mypy --strict` clean; `filterwarnings=["error"]` clean; full suite green | ✓ VERIFIED | Independently re-ran (not taken from SUMMARY): `tests/integration/test_backtest_oracle.py` → 3 passed, byte-exact. `tests/integration/test_okx_inertness.py` → 3 passed. `poetry run mypy itrader` → "Success: no issues found in 234 source files". Full suite `poetry run pytest tests -q` → **2049 passed, 6 skipped** (all 6 skips are the documented OKX-credential-gated e2e/integration tests) — matches the claimed count exactly, zero unexpected warnings (would hard-fail under `filterwarnings=["error"]`). |

**Score:** 11/11 truths verified (0 present-but-behavior-unverified). (The 7 ROADMAP/PLAN-frontmatter must-have truths for SQL-01/SQL-02/STORE-01..05 collapse into #1-5/10 above; #6-9/11 are the phase's remediation-closure truths, independently re-verified rather than inherited from the prior report.)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `migrations/env.py` | Relocated Alembic environment, imports all 7 registrars | ✓ VERIFIED | Present at repo root; registers `system_store`/`venue_store`/`strategy_registry` registrars on `target_metadata`. |
| `migrations/versions/{d10_halt_records,system_store,venue_config,strategy_registry}.py` (+ 4 earlier revisions) | Full chained lineage | ✓ VERIFIED | 8 revision files present; single head `strategy_registry` confirmed via live `get_heads()` call. |
| `alembic.ini` | `script_location = migrations` | ✓ VERIFIED | Confirmed via grep. |
| `itrader/storage/system_store.py` | `SystemStore` + `build_system_store_table`, schema-pure | ✓ VERIFIED | Present, substantive, wired, no `create_all`. |
| `itrader/storage/venue_store.py` | `VenueStore` + `build_venue_store_table` + secret guard, schema-pure | ✓ VERIFIED | Present, substantive, wired, guard intact, no `create_all`. |
| `itrader/storage/strategy_registry_store.py` | `StrategyRegistryStore` + `build_strategy_registry_tables`, schema-pure, CR-01/IN-01 fixed | ✓ VERIFIED | Present, substantive, wired; `upsert` is update-in-place-or-insert; `read_all` deterministically ordered. |
| `itrader/storage/engine.py` | `SqlEngine` with SQLite FK connect-hook (WR-02) | ✓ VERIFIED | Present; dialect-guarded `PRAGMA foreign_keys=ON` connect listener. |
| `tests/support/schema.py` | Shared `provision_schema` test seam | ✓ VERIFIED | Present; single `create_all(checkfirst=True)` helper, `TYPE_CHECKING`-guarded import. |
| `tests/integration/storage/test_migrations.py` | Gate tests incl. wheel-exclusion, single-head, full-chain upgrade, parity | ✓ VERIFIED | 7 tests, all pass against the FULL 8-revision chain including the 3 new stores. |
| `tests/unit/storage/{test_system_store,test_venue_store,test_strategy_registry_store}.py` | Unit coverage incl. CR-01/WR-02/IN-01 regressions | ✓ VERIFIED | 6 / 7 / 11 tests respectively (24 total), all pass. |
| `tests/integration/test_okx_inertness.py` | Extended `_FORBIDDEN` + register-vs-build for 3 new stores | ✓ VERIFIED | 3 tests pass. |
| `.planning/todos/pending/04-storage-review-warnings.md` | Deferred WR-01/WR-02(cleanup-order)/WR-03(datetime-guard) tracking | ✓ VERIFIED | Present, documents the 3 owner-approved deferrals distinct from the closed WR-02/WR-03 items above (naming overlap between the 04-GAP-DECISIONS WR-02/WR-03 and the later 04-REVIEW.md WR-01/02/03 — both sets independently confirmed against their respective closure/deferral status). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `alembic.ini` `script_location` | `migrations/env.py` | relative path + `prepend_sys_path = .` | ✓ WIRED | `get_heads()` resolves correctly from repo root. |
| `migrations/env.py` `target_metadata` | 3 new registrars | direct import + call on shared `MetaData` | ✓ WIRED | Confirmed via `test_create_all_vs_migration_parity` passing (would fail on spurious autogenerate drop). |
| `SqlEngine` connect-hook | every composing durable store | shared spine, registered once | ✓ WIRED | All 7 durable stores construct `self.engine = sql_engine.engine`; the PRAGMA fires per-connection at the engine level, inherited transitively. |
| `StrategyRegistryStore.upsert` | `strategy_subscriptions` FK | update-in-place (no parent delete) | ✓ WIRED | `test_upsert_of_subscribed_strategy_preserves_children` passes under FK enforcement. |
| `provision_schema` | 7 durable stores' `build_*_table` registrars | called after construction, before first query, in every test fixture | ✓ WIRED | All 106 storage tests (unit + integration) pass with this pattern. |
| `tests/integration/test_okx_inertness.py::_FORBIDDEN` | 3 new store modules | forbidden-import subprocess probe | ✓ WIRED | Test passes; probe still prints `INERTNESS_OK`. |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| SQL-01 | 04-01 | Migrations relocation + wheel exclusion | ✓ SATISFIED | Truth #1. |
| SQL-02 | 04-03, 04-04 | Alembic gate: single-head, upgrade head, create_all/migration parity over the FULL chain | ✓ SATISFIED | Truths #2, #10. |
| STORE-01 | 04-02, 04-04 | SystemStore cardinality-1 KV, schema-pure | ✓ SATISFIED | Truths #3, #8. |
| STORE-02 | 04-02, 04-04 | VenueStore, never stores secrets, schema-pure | ✓ SATISFIED | Truths #4, #8. |
| STORE-03 | 04-02, 04-04 | StrategyRegistryStore, which strategies + config + subscriptions, schema-pure, CR-01/IN-01 fixed | ✓ SATISFIED | Truths #5, #6, #8, #9. |
| STORE-04 | 04-02/04-03, 04-04 | HaltRecordStore-template clone + chained migration, schema-pure | ✓ SATISFIED | Truths #2, #8. |
| STORE-05 | 04-02/04-03, 04-04 | In-memory fallback / live-only, backtest path untouched | ✓ SATISFIED | Truth #11. |

No orphaned requirements — all 7 IDs (SQL-01, SQL-02, STORE-01..05) appear across the four plans'
`requirements` frontmatter (`04-01`: SQL-01; `04-02`: STORE-01/02/03/05; `04-03`: SQL-02,
STORE-04/05; `04-04`: SQL-02, STORE-01..05) and are marked "Complete" in `.planning/REQUIREMENTS.md`'s
P4 traceability table.

### Anti-Patterns Found

None. Scanned every file touched by this phase (3 durable stores, `engine.py`,
`halt_record_store.py`, the 3 operational-store `sql_storage.py` files, `tests/support/schema.py`,
`migrations/env.py`, the 3 new migration revisions) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/
`PLACEHOLDER` — zero matches. `_SECRET_KEY_DENYLIST` and `VenueStore._row_to_dict` confirmed
unmodified per the 04-04 explicit prohibitions.

### Gate Commands Run (this verification, independent of SUMMARY/REVIEW claims)

| Gate | Result |
|------|--------|
| `ScriptDirectory.from_config(...).get_heads()` (live Python call, not grep) | `['strategy_registry']` — single head |
| Full revision-chain walk (`walk_revisions()`) | 8 revisions, unbroken linear chain to `2cbf0bf6b0b6` |
| `poetry run pytest tests/integration/storage/test_migrations.py tests/unit/storage tests/integration/storage -q` | 106 passed |
| `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (byte-exact `46189.87730727451`) |
| `poetry run pytest tests/integration/test_okx_inertness.py -q` | 3 passed |
| `poetry run mypy itrader` | Success: no issues found in 234 source files |
| `poetry run pytest tests -q` (full suite, run once) | 2049 passed, 6 skipped (all 6 = documented OKX-credential-gated) |
| `poetry run pytest tests/integration/test_durable_halt.py tests/integration/test_live_portfolio_durable_wiring.py -q` | 6 passed |
| `git log` — CR-01/IN-01/IN-02/WR-02/WR-03 commit existence | `52c3a1e7`, `9935a184`, `0d86109c`, `53a90b07`, `6b623549`, `afe9a29a` all present |
| `git show --stat 53a90b07` / `6b623549` | Match the claimed fixes exactly (upsert update-in-place; import uuid removal + Decimal seed) |

### Human Verification Required

None. All must-haves resolve to observable, programmatically-verifiable code/test evidence; no
visual, real-time, or external-service behavior is in scope for this storage-schema phase.

### Context Notes (not gaps)

- The prior 2026-07-09T18:16:34Z verification report (score 8/8, status passed) covered only
  04-01/04-02/04-03 — it predates 04-04 and the post-review CR-01 fix. This report independently
  re-derives and re-checks the CURRENT (fully remediated) codebase state rather than trusting either
  the prior VERIFICATION.md or the 04-REVIEW.md remediation-status frontmatter.
- WR-01/WR-02(test-ordering)/WR-03(datetime-guard) from `04-REVIEW.md` are DEFERRED (not fixed) by
  explicit owner decision, tracked in `.planning/todos/pending/04-storage-review-warnings.md`. These
  are hardening improvements on top of an already-goal-achieving phase, not blockers to this phase's
  success criteria — confirmed this is a deliberate, documented deferral and not a silently-dropped
  gap.
- `ROADMAP.md`'s Phase 4 checklist still shows `04-04-PLAN.md` as `[ ]` (unchecked) even though
  `STATE.md` (`stopped_at: Completed 04-04-PLAN.md`) and `04-04-SUMMARY.md` (`status: complete`)
  both confirm completion, and the code/test evidence above independently confirms it. This is a
  cosmetic checkbox-staleness in ROADMAP.md, not a functional gap — flagged for the orchestrator to
  tidy on commit, not treated as a verification blocker.

### Gaps Summary

No gaps. All 11 derived observable truths — covering the 4 ROADMAP success criteria, all 7
requirement IDs (SQL-01, SQL-02, STORE-01..05), and the full post-review remediation closure
(CR-01 BLOCKER, WR-02, WR-03/D-14, IN-01, IN-02) — are independently VERIFIED against the CURRENT
codebase state: file existence, substantive implementation (no stubs/placeholders), wiring
(imports/calls/FK enforcement confirmed live), and behavior (every relevant test suite re-run fresh
in this session, not read from a prior report). The backtest oracle stays byte-exact, the OKX
inertness gate passes, `mypy --strict` is clean, and the full 2049-test suite is green with zero
unexpected warnings.

---

_Verified: 2026-07-10T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
