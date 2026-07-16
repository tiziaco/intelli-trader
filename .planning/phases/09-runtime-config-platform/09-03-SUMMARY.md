---
phase: 09-runtime-config-platform
plan: 03
subsystem: runtime-config
tags: [runtime-config, durable-config, save-config, config-json, restart-layering, add-event-ingress, default-deny, d-21, d-22, d-23, d-25]

# Dependency graph
requires:
  - phase: 09-runtime-config-platform
    plan: 01
    provides: "ITraderConfig frozen root + mutable sub-models (system/universe/order) + validate_assignment"
  - phase: 09-runtime-config-platform
    plan: 02
    provides: "ConfigUpdateEvent CONTROL event + ConfigRouter (validate->persist->apply->push) + LiveRouteRegistrar optional config_router kwarg + CONFIG_UPDATE route slot"
provides:
  - "OrderStorage.save_config/load_config — order-scope GLOBAL singleton config on a NEW cardinality-1 order_config table (build_order_config_table registrar; SQL + cached-delegate + in-memory dict impls)"
  - "PortfolioStateStorage.save_config/load_config — portfolio-scope config on a NEW nullable config_json column on the EXISTING portfolio_account_state (UPDATE-first / zero-sentinel INSERT-if-absent; carry-forward clobber-safety across save_account_state)"
  - "add_event admits CONFIG_UPDATE (third external type, default-deny preserved) with synchronous ingress 400-validation (_validate_config_ingress)"
  - "build_live_system: VenueStore + ConfigRouter construction over the OWNING module stores + SessionInitializer->LiveRouteRegistrar config_router injection"
  - "_layer_persisted_overrides — boot restart-layering reading each scope from its OWN store (defaults <- YAML <- env <- persisted), degrade-clean on unprovisioned schema"
affects: [09-04, fastapi-config-ingress, alembic-config-migration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Each module owns its config persistence (D-21/D-25): order-scope -> ORDER store's order_config table; portfolio-scope -> config_json on the account-state carrier; config is NEVER centralized into SystemStore"
    - "UPDATE-first / zero-sentinel INSERT-if-absent (portfolio save_config): the first config write can precede the first fill, so an UPDATE-only contract would drop it (RTCFG-03 fail); zero-sentinel accumulators are the no-activity baseline the first real save_account_state overwrites"
    - "Config-preserving carry-forward: save_account_state SELECTs config_json BEFORE the delete-then-insert and carries it into the re-INSERT so a fill never drops the persisted config"
    - "Default-deny allowlist extended to {SIGNAL, STRATEGY_COMMAND, CONFIG_UPDATE} (D-23); ingress 400-validation dry-validates known system/order fields on a model_copy (structure IS the allowlist, D-11/D-12), venue/portfolio get a structural shape check (state-dependent predicates are engine-thread)"
    - "Restart layering reads each scope from its OWN store; frozen base params (rng_seed/environment) resolved at construction, never persisted-overridden (RTCFG-04); degrade-clean try/except SQLAlchemyError when the durable config schema is not yet provisioned (migration = Plan 04)"

key-files:
  created:
    - tests/integration/test_config_restart_layering.py
    - tests/integration/test_config_ingress.py
  modified:
    - itrader/order_handler/base.py
    - itrader/order_handler/storage/sql_storage.py
    - itrader/order_handler/storage/in_memory_storage.py
    - itrader/order_handler/storage/cached_sql_storage.py
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/storage/models.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - itrader/portfolio_handler/storage/in_memory_storage.py
    - itrader/portfolio_handler/storage/cached_sql_storage.py
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/session_initializer.py
    - tests/unit/trading_system/test_add_event_admission_guard.py

key-decisions:
  - "order_config is a DEDICATED cardinality-1 table (constant single-row String PK) not a column on an order row — order config is a global singleton today but the standalone table leaves room to expand to a per-portfolio/account key later without touching the account-state carrier (D-25 forward-extensibility)"
  - "portfolio config rides a nullable config_json COLUMN on the EXISTING portfolio_account_state (no new portfolio_config table); nullable so an account-state row can exist with no config AND a config row can exist before any fill"
  - "Making the account-state accumulator columns nullable was rejected (weakens crash-consistency); instead save_config seeds zero-sentinel accumulators on INSERT-if-absent, and save_account_state carries config_json forward"
  - "Ingress 400-validation dry-validates system/order scopes fully (known singleton sub-models) but only structurally checks venue/portfolio scopes — venue-kind (D-14) and portfolio-existence + section resolution (D-21) are state-dependent engine-thread predicates the router re-checks (defense-in-depth D-16)"
  - "Restart layering degrades clean (try/except SQLAlchemyError) when the durable config schema is not yet provisioned — the order_config/config_json Alembic migration is Plan 04's; a boot over an un-migrated PG must not crash (best-effort restore)"

requirements-completed: [RTCFG-01, RTCFG-02, RTCFG-03, RTCFG-04]

coverage:
  - id: D1
    description: "Both store ABCs + all three impls each expose save_config/load_config (order=order_config table, portfolio=config_json column, cached-delegate, in-memory dict); order=global singleton, portfolio=bound-portfolio_id-scoped"
    requirement: RTCFG-03
    verification:
      - kind: integration
        ref: "tests/integration/test_config_restart_layering.py#test_restart_layering_reapplies_every_scope_from_its_own_store"
        status: pass
    human_judgment: false
  - id: D2
    description: "Portfolio config survives a subsequent fill (carry-forward clobber-safety) + zero-sentinel INSERT-if-absent arm (config saved before any account-state row)"
    requirement: RTCFG-03
    verification:
      - kind: integration
        ref: "tests/integration/test_config_restart_layering.py#test_portfolio_config_survives_a_subsequent_fill_carry_forward"
        status: pass
    human_judgment: false
  - id: D3
    description: "Restart layering re-applies each scope from its OWN store into the mutable sub-models; frozen base rng_seed is never persisted-overridden (RTCFG-04)"
    requirement: RTCFG-03
    verification:
      - kind: integration
        ref: "tests/integration/test_config_restart_layering.py#test_restart_layering_reapplies_every_scope_from_its_own_store, test_layering_is_a_noop_with_no_persisted_overrides"
        status: pass
    human_judgment: false
  - id: D4
    description: "add_event admits a valid CONFIG_UPDATE -> drained -> applied + persisted into its OWNING store (ORDER store, NOT SystemStore)"
    requirement: RTCFG-02
    verification:
      - kind: integration
        ref: "tests/integration/test_config_ingress.py#test_valid_config_update_admitted_applied_and_persisted_to_owning_store"
        status: pass
    human_judgment: false
  - id: D5
    description: "Ingress 400-validation: a bad type/range on a known field, and a malformed/unrouted scope/key, are rejected synchronously at add_event (returns False, never enqueued)"
    requirement: RTCFG-02
    verification:
      - kind: integration
        ref: "tests/integration/test_config_ingress.py#test_invalid_config_update_rejected_synchronously_at_ingress, test_malformed_scope_or_key_rejected_at_ingress"
        status: pass
    human_judgment: false
  - id: D6
    description: "Default-deny preserved: a non-allowlisted event type (raw OrderEvent / FILL) is rejected; allowlist is EXACTLY {SIGNAL, STRATEGY_COMMAND, CONFIG_UPDATE}"
    requirement: RTCFG-02
    verification:
      - kind: integration
        ref: "tests/integration/test_config_ingress.py#test_non_allowlisted_event_type_rejected"
        status: pass
      - kind: unit
        ref: "tests/unit/trading_system/test_add_event_admission_guard.py#test_externally_admissible_is_exactly_signal_strategy_command_and_config_update"
        status: pass
    human_judgment: false
  - id: D7
    description: "Live-only/backtest-dark: the SQL-store additions + build_live_system wiring stay off the backtest path — oracle byte-exact 134 / 46189.87730727451"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false
  - id: D8
    description: "Import inertness: config-store additions + build_live_system stay SQL/ccxt-import-lazy — okx inertness gate green"
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 21min
completed: 2026-07-16
status: complete
---

# Phase 9 Plan 03: Durable Module-Config Surface + Restart-Layering & Ingress Summary

**Gave each module's OWN store a `save_config`/`load_config` surface (order-scope global singleton on a new `order_config` table; portfolio-scope on a new nullable `config_json` column on `portfolio_account_state`), opened `add_event` to `CONFIG_UPDATE` as the third default-deny external type with synchronous ingress 400-validation, and wired the `ConfigRouter` + boot restart-layering into `build_live_system` so persisted overrides survive restart from their OWN store — backtest byte-exact, inertness green, closing the D-25 storage seam.**

## Performance
- **Duration:** ~21 min
- **Tasks:** 3 (+ 1 degrade-clean fix)
- **Files:** 14 (2 created, 12 modified)

## Accomplishments
- **Task 1 (D-25 durable config surface).** `OrderStorage`/`PortfolioStateStorage` ABCs + all three impls each gained `save_config`/`load_config`. Order-scope is a GLOBAL singleton on a NEW cardinality-1 `order_config` table (`build_order_config_table` registrar mirroring `build_venue_store_table`, schema-pure). Portfolio-scope rides a NEW nullable `config_json` column added to the EXISTING `portfolio_account_state` via extended `build_portfolio_tables` (no new table). The SQL portfolio impl uses UPDATE-first / zero-sentinel INSERT-if-absent (the first config write can precede the first fill), and `_upsert_account_state_on` was made config-preserving (SELECT `config_json` before the delete-then-insert, carry it forward) so a fill never drops the persisted config. Cached wrappers delegate; in-memory dicts.
- **Task 2 (ingress + wiring).** `_EXTERNALLY_ADMISSIBLE` extended to the third type `CONFIG_UPDATE` (default-deny preserved). `add_event` runs `_validate_config_ingress` (a synchronous 400-style dry-validate on a `model_copy` for known system/order fields; structural shape check for venue/portfolio) BEFORE the queue. `build_live_system` constructs `VenueStore` + the `ConfigRouter` over the OWNING module stores per D-21 (`order`->`order_handler.storage`, `portfolio`->each Portfolio's `state_storage`, NOT SystemStore), attaches it to the facade, and `SessionInitializer` threads it into `LiveRouteRegistrar`. `_layer_persisted_overrides` applies each scope's persisted config from its OWN store on boot (frozen base never touched).
- **Task 3 (mandatory tests).** `test_config_restart_layering.py` (RTCFG-03) proves every scope re-applies from its OWN store, the frozen `rng_seed` is untouched, the carry-forward clobber-safety holds, and the zero-sentinel INSERT-if-absent arm works. `test_config_ingress.py` (D-23) drives the external `add_event(ConfigUpdateEvent)` path end-to-end: admit valid -> drain -> applied+persisted in the ORDER store (not SystemStore); reject invalid (400), malformed scope/key, and non-allowlisted types.

## Task Commits
1. **Task 1: durable module-config surface (D-25)** — `41f3af51` (feat)
2. **Task 2: CONFIG_UPDATE ingress + ConfigRouter wiring + restart layering (D-23/D-22/D-10)** — `5f56635b` (feat)
3. **Task 3: restart-layering + ingress integration tests** — `dd0028f6` (test)
4. **Fix: degrade restart-layering clean on unprovisioned schema** — `2873cef8` (fix)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Restart-layering boot read broke 4 PG live-wiring tests**
- **Found during:** Task 3 full-suite gate.
- **Issue:** `_layer_persisted_overrides` performs a real `system_store.read_all()` (+ order/portfolio `load_config`) at build time. Four existing PG-backed live-wiring tests (`test_store_live_drive.py`, `test_live_portfolio_durable_wiring.py`, `test_shared_pg_fixture.py`) build a live system over an UN-provisioned Postgres (they assert wiring types only, never provision `system_store`), so the boot read hit `UndefinedTable`.
- **Fix:** Wrapped the layering body in `try/except SQLAlchemyError` — a boot against a not-yet-migrated durable config schema (the `order_config`/`config_json` Alembic migration lands in Plan 04) logs a warning and skips layering instead of crashing. This mirrors the plan's None-backend degrade-clean intent and keeps the store schema-pure (never `create_all`). RTCFG-03 restore is best-effort; a fresh/un-migrated DB simply has no persisted overrides.
- **Files modified:** `itrader/trading_system/live_trading_system.py`
- **Commit:** `2873cef8`

**2. [Rule 1 - Test invariant] Updated the D-10 admission-guard allowlist test**
- **Found during:** Task 2 trading_system unit run.
- **Issue:** `test_externally_admissible_is_exactly_signal_and_strategy_command` asserted the allowlist is EXACTLY `{SIGNAL, STRATEGY_COMMAND}` — the pre-D-23 invariant.
- **Fix:** Updated to the D-23 three-type allowlist `{SIGNAL, STRATEGY_COMMAND, CONFIG_UPDATE}` (directly caused by the in-scope allowlist extension).
- **Files modified:** `tests/unit/trading_system/test_add_event_admission_guard.py`
- **Commit:** `5f56635b`

## Plan-snippet note (non-issue)
The plan's Task-1 `<read_first>` note "order ABC is TABS" is inaccurate — `itrader/order_handler/base.py` is 4-space (verified with `grep -P '^\t'`); only the `TYPE_CHECKING` block in the portfolio ABC uses tabs. All storage edits matched each file's actual indentation.

## Known Stubs
None. Every ABC method is fully implemented across all three impls. The Alembic migration (`CREATE TABLE order_config` + `ALTER portfolio_account_state ADD config_json`) + single-head/parity finalization is a documented cross-plan dependency owned by **Plan 04** (the migration-owner) — NOT a stub: `provision_schema`/`create_all` fully covers THIS plan's tests, and the boot layering degrades clean until the migration lands.

## Cross-plan dependency (for Plan 04)
- Author the Alembic migration for the two schema changes (`order_config` table create + `portfolio_account_state.config_json` column add) and extend the migration-parity gate to cover them. The metadata registrars (`build_order_config_table`, extended `build_portfolio_tables`) are the single source of truth to autogenerate from.

## Gates
- Backtest oracle byte-exact `134 / 46189.87730727451` (3 passed) — backtest-dark confirmed.
- OKX import-inertness green (4 passed) — config-store additions + build_live_system stay import-lazy.
- `mypy --strict` clean (260 files).
- Full suite: `2292 passed / 6 skipped` (skips are OKX-credential-gated live suites).

## Self-Check: PASSED
- Created files verified present: `tests/integration/test_config_restart_layering.py`, `tests/integration/test_config_ingress.py`, `09-03-SUMMARY.md`
- Task commits verified in git log: `41f3af51`, `5f56635b`, `dd0028f6`, `2873cef8`

---
*Phase: 09-runtime-config-platform*
*Completed: 2026-07-16*
