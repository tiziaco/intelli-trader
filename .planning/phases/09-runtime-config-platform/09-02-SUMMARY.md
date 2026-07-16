---
phase: 09-runtime-config-platform
plan: 02
subsystem: runtime-config
tags: [runtime-config, config-router, msgspec-event, control-plane, default-deny, validate-assignment, venue-kind, d-15, d-21]

# Dependency graph
requires:
  - phase: 09-runtime-config-platform
    plan: 01
    provides: "ITraderConfig frozen root + mutable sub-models (system/universe/order + validate_assignment) — the router's apply target"
  - phase: 07-safety-reconciliation-stream-recovery
    provides: "control.py CONTROL msgspec events + LiveRouteRegistrar CONTROL routes + PreTradeThrottle warn_min_interval_s WARNING-ErrorEvent dedup pattern"
provides:
  - "ConfigUpdateEvent(scope, key, value) — CONTROL msgspec.Struct event (events/control.py)"
  - "ConfigRouter — engine-thread validate->persist->apply->push router (trading_system/config_router.py); default-deny scope->owner dispatch over all 4 D-21 scopes to each module's OWN store"
  - "CONFIG_UPDATE CONTROL route wired via LiveRouteRegistrar (pre-declared empty slot -> _on_config_update -> config_router.apply)"
  - "LiveRouteRegistrar accepts an injected config_router (optional kwarg; Wave 3 constructs the real router)"
affects: [09-03, build_live_system, config-restart-layering, fastapi-config-ingress]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "The structure IS the allowlist (D-11/D-12): routable keys resolved by LIVE model_fields introspection (SystemSettings/UniverseConfig/OrderConfig/PortfolioConfig sections) — the allowlist can never drift from the model"
    - "validate -> persist -> apply -> push ordering (D-15): dry-validate on a model_copy()/model_validate candidate, persist to the owning store, then setattr live + handler.update_config push; persist failure applies NOTHING"
    - "Default-deny scope dispatch (D-11): EXACT-string scope match; venue:{name}/portfolio:{id} prefix-parsed; unknown/unrouted -> reject"
    - "Deduped WARNING-ErrorEvent rejection surfacing (D-16): reuses the P7 warn_min_interval_s min-interval dedup; only FIXED literals + non-secret scope/key bound (V7 — value never stringified)"
    - "Venue-kind predicate (D-14/RTCFG-05): fee/slippage runtime-mutable only when the venue's execution arm is simulated"

key-files:
  created:
    - itrader/trading_system/config_router.py
    - tests/unit/trading_system/test_config_router.py
  modified:
    - itrader/events_handler/events/control.py
    - itrader/events_handler/events/__init__.py
    - itrader/trading_system/route_registrar.py

key-decisions:
  - "system idle/timeout knobs AND universe poll_cadence/remove_policy both route under the single `system` scope (scopes locked to {system, order, venue, portfolio}, D-21); the owning sub-model (config.system vs config.universe) is resolved by model_fields introspection"
  - "order scope routes to OrderConfig.market_execution ONLY (the sole real field today); trail/TIF are NOT fabricated and the scope is NOT dropped — default-deny rejects non-fields (WARNING-2 / D-12)"
  - "collaborators (order/portfolio stores via save_config, handlers, venue-kind resolver, bus) injected + typed Any where their config surface is finalized in Wave 3 (save_config lands in Plan 03); config typed as the real inert ITraderConfig"
  - "LiveRouteRegistrar.config_router is an OPTIONAL kwarg (default None) so the existing session_initializer wiring is non-breaking; Wave 3 constructs + injects the real router"

requirements-completed: [RTCFG-02, RTCFG-04, RTCFG-05]

coverage:
  - id: D1
    description: "A known (scope,key) routes validate->persist->apply->push in order; the owning store received the write, the live sub-model mutated, and the owning handler.update_config was pushed"
    requirement: RTCFG-02
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_happy_path_order_scope_persist_then_apply_then_push, test_happy_path_system_scope_persists_to_system_store, test_happy_path_universe_key_routes_under_system_scope"
        status: pass
    human_judgment: false
  - id: D2
    description: "Default-deny: unknown/unrouted scope + non-field key + mis-cased (exact-string) scope reject with no persist and a deduped WARNING ErrorEvent"
    requirement: RTCFG-02
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_default_deny_unknown_scope_rejects_with_warning_and_no_persist, test_default_deny_unknown_key_rejects_with_warning_and_no_persist, test_mis_cased_scope_is_unrouted_exact_string_match"
        status: pass
    human_judgment: false
  - id: D3
    description: "Immutable-at-runtime base keys (rng_seed/environment/name/debug_mode) have no routable (scope,key) — default-deny rejected structurally"
    requirement: RTCFG-04
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_immutable_base_key_has_no_routable_scope"
        status: pass
    human_judgment: false
  - id: D4
    description: "Venue-kind predicate: live-venue fee/slippage rejected, simulated-venue applies (+ pushes execution_handler.update_config); enabled allowed regardless of kind"
    requirement: RTCFG-05
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_venue_kind_live_venue_fee_slippage_rejected, test_venue_kind_simulated_venue_fee_slippage_applies, test_venue_kind_enabled_flag_allowed_regardless_of_kind"
        status: pass
    human_judgment: false
  - id: D5
    description: "validate->persist->apply ordering holds: validation failure + persist failure each reject and apply NOTHING live; idempotent same-value re-apply leaves ONE row"
    requirement: RTCFG-02
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_validation_failure_rejects_before_persist, test_persist_failure_rejects_and_applies_nothing, test_idempotency_same_event_twice_one_row_same_value"
        status: pass
    human_judgment: false
  - id: D6
    description: "portfolio:{id} scope (D-21/D-25 blocker): known id persists to the resolved Portfolio's OWN bound store (NOT SystemStore) + pushes portfolio.update_config; unknown id (PortfolioNotFoundError) default-deny rejected"
    requirement: RTCFG-02
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_portfolio_scope_known_id_persists_to_own_store_and_pushes, test_portfolio_scope_unknown_id_default_deny_rejected, test_portfolio_scope_risk_and_sizing_sections_resolve"
        status: pass
    human_judgment: false
  - id: D7
    description: "All four D-21 scopes are collectively routable to their OWN module store (system->SystemStore, order->order store, venue->VenueStore, portfolio->Portfolio's bound store); order/portfolio NEVER centralize into SystemStore"
    requirement: RTCFG-02
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_scope_owner_table_each_scope_persists_to_its_own_store, test_scope_owner_table_order_and_venue_never_touch_system_store"
        status: pass
    human_judgment: false
  - id: D8
    description: "A credential-carrying venue value is rejected by the VenueStore recursive secret denylist before any write (V7); the router surfaces it as a persist-failed rejection with no apply"
    requirement: RTCFG-05
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_config_router.py#test_venue_secret_value_rejected_by_store_no_apply"
        status: pass
    human_judgment: false
  - id: D9
    description: "ConfigUpdateEvent is a CONTROL msgspec event wired to ConfigRouter via LiveRouteRegistrar; control.py stays msgspec-only (backtest import inertness green)"
    requirement: RTCFG-02
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false
  - id: D10
    description: "Live-only/CONTROL-plane additions are backtest-dark — oracle stays byte-exact 134 / 46189.87730727451"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false

# Metrics
duration: 11min
completed: 2026-07-16
status: complete
---

# Phase 9 Plan 02: Runtime-Mutation Core (ConfigUpdateEvent + ConfigRouter) Summary

**Built the live-only runtime-mutation core: a scoped `ConfigUpdateEvent(scope, key, value)` CONTROL msgspec event and an engine-thread `ConfigRouter` running validate → persist → apply → push (D-15) with default-deny scope→owner dispatch over all four D-21 scopes to each module's OWN store, Pydantic `validate_assignment` validation, a venue-kind predicate, and deduped WARNING-`ErrorEvent` rejection surfacing — backtest-dark (oracle byte-exact, inertness green).**

## Performance
- **Duration:** ~11 min
- **Tasks:** 3 (all atomic-committed)
- **Files:** 5 (2 created, 3 modified)

## Accomplishments
- `ConfigUpdateEvent` — CONTROL `msgspec.Struct` event (copies the `StreamStateEvent` shape; `type: ClassVar = EventType.CONFIG_UPDATE`; `scope`/`key`/`value: Any`; V7 secret-scrub docstring). Barrel-exported (inertness-safe).
- `CONFIG_UPDATE` route wired: `LiveRouteRegistrar` SETs the pre-declared empty slot to a thin `_on_config_update` that delegates to the injected `ConfigRouter.apply` (D-23/§13c). `config_router` is an optional injected kwarg (Wave 3 constructs the real one) — existing wiring non-breaking.
- `ConfigRouter` — the engine-thread single-writer router (D-15 ordering). Default-deny scope→owner dispatch over all four D-21 scopes, each to its OWN module store (`system`→SystemStore, `order`→order store `save_config`, `venue:{name}`→VenueStore, `portfolio:{id}`→resolved Portfolio's bound `state_storage.save_config`) — config is NEVER centralized into SystemStore. Routable keys resolved by **live `model_fields` introspection** (the structure IS the allowlist, D-11/D-12). Venue-kind predicate (D-14/RTCFG-05), `validate_assignment`/`model_validate` dry-validate before persist (D-13), deduped WARNING-`ErrorEvent` surfacing reusing the P7 `warn_min_interval_s` pattern (D-16, no value leak).
- 25-test `test_config_router.py` (package-less dir) covering all nine behavior groups incl. the `-k venue_kind`, `-k portfolio` (blocker), and `-k scope_owner_table` (all-four-scopes enumeration) selectors.

## Inventory pass (WARNING-2 / D-12 — key→field map, re-grep-confirmed)
- `system` scope → `SystemSettings.model_fields` (`enable_auto_restart`, `auto_restart_delay_seconds`, `enable_graceful_shutdown`, `shutdown_timeout_seconds`) **and** `UniverseConfig.model_fields` (`poll_cadence_s`, `remove_policy`) — both under the single `system` scope (D-21).
- `order` scope → `OrderConfig.model_fields` == `{market_execution}` ONLY. Trail/TIF are NOT `OrderConfig` fields and the D-08/D-09 restructure does not add them → routed to `market_execution`, default-deny for the rest (not fabricated, not dropped).
- `venue:{name}` → `{fee_model, slippage_model, enabled}`; fee/slippage gated by the venue-kind predicate.
- `portfolio:{id}` → the mutable `PortfolioConfig` sections `{limits, risk_management, trading_rules}` (risk limits + sizing defaults), section resolved by introspection.

## Task Commits
1. **Task 1: Add ConfigUpdateEvent + wire CONFIG_UPDATE route** — `4af43624` (feat)
2. **Task 2: Implement ConfigRouter** — `c686ace7` (feat)
3. **Task 3: Author test_config_router.py** — `a1fdab15` (test)

## Files Created/Modified
- `itrader/trading_system/config_router.py` — NEW `ConfigRouter` (validate→persist→apply→push, default-deny dispatch, venue-kind predicate, deduped WARNING surfacing). 4-space.
- `tests/unit/trading_system/test_config_router.py` — NEW (package-less, 25 tests).
- `itrader/events_handler/events/control.py` — added `ConfigUpdateEvent` msgspec struct + `Any` import.
- `itrader/events_handler/events/__init__.py` — barrel-export `ConfigUpdateEvent`.
- `itrader/trading_system/route_registrar.py` — optional `config_router` kwarg; `routes[CONFIG_UPDATE] = [_on_config_update]`; thin delegator method.

## Decisions Made
- **`system` scope covers both SystemSettings and UniverseConfig keys** — scopes are locked to `{system, order, venue, portfolio}` (D-21), so the universe knobs ride the `system` scope; the owning sub-model is resolved by `model_fields` introspection, keeping the allowlist == the live model.
- **Collaborators typed `Any` where their config surface is Wave-3** — `save_config` on the order/portfolio stores lands in Plan 03; the router is fully unit-testable now against injected doubles, and `mypy --strict` stays clean.
- **`config_router` optional on `LiveRouteRegistrar`** — non-breaking for the existing `session_initializer` construction; Wave 3 wires the real router in `build_live_system`.

## Deviations from Plan
None — plan executed as written. One documentation note: the Task-1 `<automated>` verify snippet constructed `ConfigUpdateEvent(scope=..., key=..., value=...)` without the required `time` field (every `Event` requires `time`); the event itself is correct (matches the `StreamStateEvent` shape, which also requires `time`). Verified construction with `time` supplied — the omission was a plan-snippet slip, not a code issue.

## Known Stubs
None. `ConfigRouter` is fully functional against injected collaborators. Its calls to `order_handler.storage.save_config` and `portfolio.state_storage.save_config` target a store method that **Plan 03 (Wave 3)** adds to the existing `OrderStorage` / `PortfolioStateStorage` (D-25) — a documented cross-wave dependency, not a stub: the router is proven end-to-end against store doubles, and Wave 3 injects the real stores + wires the router into `build_live_system`.

## Cross-wave dependency (for Wave 3)
- `OrderStorage.save_config(config, at)` and `PortfolioStateStorage.save_config(config, at)` must exist (D-25 — order config table + portfolio `config_json` column) before the real router is wired.
- `build_live_system` must construct the `ConfigRouter` (config + stores + handlers + venue-kind resolver + bus + clock) and pass it to `LiveRouteRegistrar(config_router=...)`.
- `add_event` must admit `EventType.CONFIG_UPDATE` (D-23 third external type) for the external ingress path.

## Gates
- Backtest oracle byte-exact `134 / 46189.87730727451` (3 passed) — backtest-dark confirmed.
- OKX import-inertness green (4 passed) — `control.py` stays msgspec-only.
- `mypy --strict` clean (260 files).
- Full suite: `2284 passed / 6 skipped` (skips are OKX-credential-gated live suites; +25 new router tests).

## Self-Check: PASSED
- Created files verified present: `itrader/trading_system/config_router.py`, `tests/unit/trading_system/test_config_router.py`, `09-02-SUMMARY.md`
- Task commits verified in git log: `4af43624`, `c686ace7`, `a1fdab15`

---
*Phase: 09-runtime-config-platform*
*Completed: 2026-07-16*
