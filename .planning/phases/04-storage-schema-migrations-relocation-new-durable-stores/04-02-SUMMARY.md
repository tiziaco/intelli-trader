---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
plan: 02
subsystem: storage
tags: [storage, sql-spine, durable-stores, live-only, secret-scrub]
requires:
  - "itrader/storage/SqlEngine (shared spine)"
  - "itrader/storage/types.py (UtcIsoText, json_variant)"
  - "itrader/storage/halt_record_store.py (the clone template — D-01)"
  - "itrader/core/exceptions.ValidationError"
provides:
  - "SystemStore (cardinality-1 KV durable store)"
  - "VenueStore (per-venue config + enabled, secret-denylist guarded)"
  - "StrategyRegistryStore (two-table registry + normalized subscriptions)"
  - "build_system_store_table / build_venue_store_table / build_strategy_registry_tables registrars"
affects:
  - "Plan 04-03 (migrations/env.py target_metadata consumes the three registrars)"
  - "P9 RuntimeConfig (SystemStore/VenueStore consumers)"
  - "P10 StrategiesRegistry (StrategyRegistryStore consumer)"
tech-stack:
  added: []
  patterns:
    - "HaltRecordStore-template clone: compose SqlEngine by reference, own build_*_table registrar, idempotent create_all(checkfirst=True), dispose delegates to backend"
    - "portable delete-then-insert upsert in one engine.begin() transaction (parameterized Core)"
    - "recursive secret-key denylist guard over config_json (dicts + lists, any depth)"
    - "two-table registrar returning dict[str, Table] with per-table idempotency guards + ForeignKey"
key-files:
  created:
    - itrader/storage/system_store.py
    - itrader/storage/venue_store.py
    - itrader/storage/strategy_registry_store.py
    - tests/unit/storage/test_system_store.py
    - tests/unit/storage/test_venue_store.py
    - tests/unit/storage/test_strategy_registry_store.py
  modified: []
decisions:
  - "D-06: natural NAME PKs (key / venue_name / strategy_name) — idgen never imported, no surrogate/autoincrement"
  - "D-05: VenueStore secret-denylist guard fires BEFORE the write (recursive, any depth — Pitfall 6)"
  - "set_subscriptions touches the parent registry updated_at with the caller-supplied at (gives at a UtcIsoText home without adding an updated_at column to the child)"
  - "restart-survival test is file-backed sqlite (Pitfall 4), not :memory:"
metrics:
  duration: 6min
  completed: 2026-07-09
  tasks: 3
  files: 6
status: complete
---

# Phase 4 Plan 02: New Durable SQL Stores Summary

Landed the three new live-only durable SQL stores (`SystemStore`, `VenueStore`,
`StrategyRegistryStore`) as tested standalone units — each a disciplined clone of the
`HaltRecordStore` template composing the shared `SqlEngine` spine, with natural NAME PKs,
parameterized Core, and a `None`-degrade-free `create_all(checkfirst=True)` schema path.

## What was built

- **`SystemStore`** (`itrader/storage/system_store.py`) — cardinality-1 KV store. `system_store`
  table with a natural `key` String PK (D-06 — no `idgen`, no surrogate), `value_json`
  (`json_variant`, D-08), `updated_at` (`UtcIsoText`, D-07). Surface: `upsert` (portable
  delete-then-insert, one transaction → one row per key), `get`, `delete`, `read_all`
  rehydrate.
- **`VenueStore`** (`itrader/storage/venue_store.py`) — per-venue config + typed `enabled`
  Boolean. `venue_name` PK. Surface adds `list_enabled()` (typed-column query). **D-05
  defense-in-depth:** module-level `_SECRET_KEY_DENYLIST` frozenset + recursive
  `_assert_no_secret_keys` that walks dicts AND lists-of-dicts at any depth (Pitfall 6),
  raising `ValidationError` at the TOP of `upsert` before the delete-then-insert — a rejected
  write persists nothing. Structural arm noted in the docstring: credentials are
  connector/`OkxSettings`-owned and never passed to the store.
- **`StrategyRegistryStore`** (`itrader/storage/strategy_registry_store.py`) — TWO tables via
  a `dict[str, Table]` registrar (the `build_order_tables` precedent): `strategy_registry`
  (`strategy_name` PK) + `strategy_subscriptions` (FK to `strategy_registry.strategy_name`,
  natural composite PK `(strategy_name, venue, symbol, timeframe)` — no surrogate UUID).
  Surface: `upsert`, `get`, `delete` (child-first FK order), `set_subscriptions` (replace-all
  + touches parent `updated_at`), `list_active`, `strategies_subscribed_to(symbol)`, and a
  `read_all` FK-join rehydrate (LEFT OUTER JOIN, grouped per strategy). Durable key is the
  strategy NAME, never the ephemeral runtime `strategy_id` UUID.

Each registrar is the single source of truth feeding both the store's `create_all` and Plan
04-03's `migrations/env.py` `target_metadata`.

## How it was verified

- `poetry run pytest tests/unit/storage -q` → **44 passed** (17 new across the three suites +
  existing spine tests).
- `poetry run mypy itrader/storage/system_store.py itrader/storage/venue_store.py itrader/storage/strategy_registry_store.py`
  → **no issues** (strict-clean).
- Per-PLAN oracle gate: `poetry run pytest tests/integration/test_backtest_oracle.py` →
  **3 passed**, byte-exact `46189.87730727451` (new stores are live-only, off the backtest
  import path).
- `poetry run pytest tests/integration/test_okx_inertness.py` → **2 passed** (inertness held).
- Restart survival is a real file-backed sqlite `tmp_path` round-trip (write → `dispose()` →
  NEW store over the same file → read-back identical) — NOT `:memory:` (Pitfall 4).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `RowMapping` vs `Mapping[str, Any]` mypy mismatch (VenueStore)**
- **Found during:** Task 2 mypy gate.
- **Issue:** `mypy --strict` rejected passing SQLAlchemy's `RowMapping` (from
  `.mappings().first()/.all()`) to a `_row_to_dict(row: Mapping[str, Any])` helper.
- **Fix:** imported `RowMapping` from `sqlalchemy.engine` and typed the helper parameter as
  `RowMapping`.
- **Files modified:** `itrader/storage/venue_store.py`
- **Commit:** fa72fffd

### Design notes (in-plan, worth recording)

- **`set_subscriptions(strategy_name, subscriptions, at)`** — the plan specified the `at`
  parameter but the `strategy_subscriptions` table has no timestamp column. Resolved by having
  `set_subscriptions` bump the parent `strategy_registry.updated_at` to the caller-supplied
  `at` (so `at` has a `UtcIsoText` home) rather than adding an `updated_at` column to the
  child — keeping the child schema exactly as the registrar spec (04-03 migration derives from
  it). The registry `updated_at` therefore reflects the latest mutation (config or
  subscriptions), which is the intended rehydrate semantic.

## Known Stubs

None — all three stores are fully functional; no placeholder values or unwired data paths.

## Self-Check: PASSED

Files verified present:
- FOUND: itrader/storage/system_store.py
- FOUND: itrader/storage/venue_store.py
- FOUND: itrader/storage/strategy_registry_store.py
- FOUND: tests/unit/storage/test_system_store.py
- FOUND: tests/unit/storage/test_venue_store.py
- FOUND: tests/unit/storage/test_strategy_registry_store.py

Commits verified in git log:
- FOUND: 55735fb3 (Task 1 — SystemStore)
- FOUND: fa72fffd (Task 2 — VenueStore)
- FOUND: fcbdf69f (Task 3 — StrategyRegistryStore)
