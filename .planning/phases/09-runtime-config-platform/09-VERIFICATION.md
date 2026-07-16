---
phase: 09-runtime-config-platform
verified: 2026-07-16T11:29:35Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
deferred:
  - truth: "A formal 'config-restart gate' (TEST-03) proving persisted runtime overrides survive restart"
    addressed_in: "Phase 12 (Test Migration + Gates)"
    evidence: "REQUIREMENTS.md line 324: '[ ] TEST-03: A config-restart gate proves persisted runtime overrides survive a restart (RTCFG-03).' — explicitly scoped to P12 in REQUIREMENTS.md traceability table (line 429: TEST-03 | P12 | Pending). P9's own 09-03 plan already delivers a functionally-equivalent mandatory integration test (tests/integration/test_config_restart_layering.py), so RTCFG-03 itself is satisfied now; TEST-03 is a separate, more formal milestone-wide gate deferred to P12 by design, not a P9 gap."
---

# Phase 9: Runtime-Config Platform Verification Report

**Phase Goal:** Build a durable, restart-surviving runtime-config platform — a runtime config the live factory builds (defaults ← YAML ← env ← persisted overrides), a scoped ConfigUpdateEvent gated by an allowlist with venue-kind-aware validation, plus the SystemStore stats/state UI read-model. (★ feature-add; live-only / backtest-dark.)
**Verified:** 2026-07-16T11:29:35Z
**Status:** passed
**Re-verification:** No — initial verification

## Owner-Override Note (honored)

Per `09-CONTEXT.md` D-05/D-06/D-11 and the explanatory note appended under the Phase 9 goal in `ROADMAP.md`, the literal "`RuntimeConfig` overlay injected as `EngineContext.config`" and "standalone allowlist artifact" wording in ROADMAP Success Criteria #1/#2 and in REQUIREMENTS.md RTCFG-01/02 was **deliberately superseded** by the owner. This verification judges the **adopted** design:
- The frozen `ITraderConfig` aggregator singleton (imported via `from itrader import config`, confirmed NOT injected via `EngineContext.config`, which stays `Any`/vestigial) IS the runtime config.
- The frozen-base + mutable-sub-model + `validate_assignment=True` structure IS the default-deny allowlist (no separate `ALLOWLIST` artifact — confirmed absent, by design).
- Additionally, D-17/D-18 (also in the same locked `09-CONTEXT.md`) supersede ROADMAP Success Criterion #4's literal "`system_store` `stats.snapshot`" wording: the stats series was deliberately built as its OWN standalone `system_stats` table/store (never nested under `SystemStore`), to avoid entity duplication and keep `SystemStore` to `config.*`/`state.*` KV only. This is documented, consistently implemented across all four plans, and treated here as an in-scope adopted-design refinement, not a gap.

None of these were flagged as failures below.

## Goal Achievement

### Observable Truths (RTCFG-01..06, cross-referenced against REQUIREMENTS.md lines 240-266)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | RTCFG-01: A runtime-mutable config surface (`defaults ← YAML ← env ← persisted`) is built by the live factory; handlers read it and see runtime changes | ✓ VERIFIED | `itrader/config/itrader_config.py` (`ITraderConfig` frozen aggregator, mutable sub-models); `itrader/__init__.py` singleton create-once-mutate-in-place; `_layer_persisted_overrides` in `live_trading_system.py:1118-1210` layers persisted overrides on boot; `tests/integration/test_config_restart_layering.py` (3 tests, independently re-run, PASS) proves the full layering + handler push |
| 2 | RTCFG-02: A scoped `ConfigUpdateEvent(scope,key,value)` on CONTROL is validated (allowlist+type/range), routed on the engine thread to the owning store, applied to config+`handler.update_config`, and persisted | ✓ VERIFIED | `itrader/events_handler/events/control.py::ConfigUpdateEvent`; `itrader/trading_system/config_router.py::ConfigRouter.apply` (validate→persist→apply→push, D-15); `LiveRouteRegistrar._on_config_update` wired (`route_registrar.py:134,161-170`); `tests/unit/trading_system/test_config_router.py` (25 tests, independently re-run, PASS) covering happy-path, default-deny, idempotency, ordering; `tests/integration/test_config_ingress.py` (5 tests, PASS) proves the external `add_event(ConfigUpdateEvent)` path end-to-end |
| 3 | RTCFG-02 scope→owner dispatch: all four D-21 scopes (`system`, `order`, `venue:{name}`, `portfolio:{id}`) route to their OWN module store — never centralized into `SystemStore` | ✓ VERIFIED | `config_router.py:216-354` (`_apply_system`→SystemStore, `_apply_order`→`order_handler.storage.save_config`, `_apply_venue`→VenueStore, `_apply_portfolio`→resolved `Portfolio.state_storage.save_config`); `test_scope_owner_table_each_scope_persists_to_its_own_store` + `test_scope_owner_table_order_and_venue_never_touch_system_store` (PASS) — negative assertion confirms order/portfolio never write to the SystemStore double |
| 4 | RTCFG-03: Persisted overrides survive restart — `build_live_system` layers them over defaults on boot | ✓ VERIFIED | `_layer_persisted_overrides` (`live_trading_system.py:1118`) reads each scope from its OWN store (system/order/venue/portfolio) and re-applies via setattr/`update_config`; `tests/integration/test_config_restart_layering.py::test_restart_layering_reapplies_every_scope_from_its_own_store` uses REAL SQL-backed stores (SqlOrderStorage/SystemStore/VenueStore/SqlPortfolioStateStorage over an in-memory SQLite engine, `provision_schema`) — round-trips real persisted rows through a fresh `ITraderConfig()`, independently re-run, PASS; also proves the frozen `rng_seed` base field is never persisted-overridden |
| 5 | RTCFG-04: Immutable-at-runtime keys (`rng_seed`, money precision, SQL/venue credentials, `environment`, IDs) are rejected | ✓ VERIFIED | `ITraderConfig` places `rng_seed`/`environment`/`name`/`version`/`debug_mode`/dirs DIRECTLY on the `frozen=True` base (`itrader_config.py:66-75`) — a runtime `setattr` raises `pydantic.ValidationError` structurally; SQL credentials (`config.sql`) are not even a `ConfigRouter`-routable scope (no `sql` scope exists in the dispatch table — default-deny by absence); `tests/unit/config/test_itrader_config.py` (frozen-base rejection incl. thread-agnostic) + `test_config_router.py::test_immutable_base_key_has_no_routable_scope` (parametrized over rng_seed/environment/name/debug_mode), independently re-run, PASS |
| 6 | RTCFG-05: Fee/slippage config keys are runtime-mutable only for simulated venues; a live venue's fee/slippage `ConfigUpdateEvent` is rejected | ✓ VERIFIED | `config_router.py:275-309` (`_apply_venue` — `_VENUE_FEE_SLIPPAGE_KEYS` gated by `self._venue_kind(venue_name)`); `live_trading_system.py:1480-1484` (`_venue_kind` resolver — `isinstance(execution_handler.exchanges.get(venue_name), SimulatedExchange)`); `test_venue_kind_live_venue_fee_slippage_rejected` + `test_venue_kind_simulated_venue_fee_slippage_applies` + `test_venue_kind_enabled_flag_allowed_regardless_of_kind`, independently re-run, PASS |
| 7 | RTCFG-06: `system_stats` append-only series + `state.*` KV serve as the UI read-model — lock-free reads, no hot-path lock, no entity duplication | ✓ VERIFIED | `itrader/storage/system_stats_store.py` (`SystemStatsStore.append/read_recent/read_all` — plain `engine.connect()` reads, no lock); `state.status`/`state.halt_reason` upserted at `SafetyController` transition/halt source (`safety_controller.py:494-518`); `state.last_started_at` at facade `start()` (`live_trading_system.py:646-657`); `state.last_error` pre-existing (`error_handler.py:151`); `_snapshot_system_stats` (`live_trading_system.py:443-487`) snapshots only engine-operational counters (throttle/error-by-severity/queue-depth/uptime/connector+stream health) — no portfolio equity or domain-entity data anywhere in the table schema; `tests/unit/storage/test_system_stats_store.py` (5 tests, PASS) |

**Score:** 6/6 RTCFG requirements verified (0 present-but-behavior-unverified)

### Requirements Coverage (RTCFG-01..06, cross-referenced against REQUIREMENTS.md and ROADMAP.md)

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| RTCFG-01 | 09-01, 09-03 | Runtime config overlay layering | ✓ SATISFIED | `ITraderConfig` + `_layer_persisted_overrides`; owner-override honored (no `RuntimeConfig`/`EngineContext.config` injection) |
| RTCFG-02 | 09-02, 09-03 | Scoped `ConfigUpdateEvent` + allowlist + routing + persist | ✓ SATISFIED | `ConfigUpdateEvent` + `ConfigRouter` + `add_event` ingress |
| RTCFG-03 | 09-03 | Restart survival | ✓ SATISFIED | `_layer_persisted_overrides` + SQL-backed integration test |
| RTCFG-04 | 09-01, 09-02, 09-03 | Immutable-at-runtime key rejection | ✓ SATISFIED | Frozen base + no routable scope for `sql`/money-precision |
| RTCFG-05 | 09-02 | Venue-kind-aware fee/slippage gating | ✓ SATISFIED | `_venue_kind` predicate + `_VENUE_FEE_SLIPPAGE_KEYS` gate |
| RTCFG-06 | 09-04 | `system_stats` + `state.*` read-model | ✓ SATISFIED | `SystemStatsStore` + `state.*` writers (D-17/D-18 own-table refinement) |

No orphaned requirements — all six RTCFG-01..06 IDs declared across the four plans' frontmatter map 1:1 onto REQUIREMENTS.md's Phase-9 block (lines 240-266) and its traceability table (lines 412-417, all "Complete").

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `itrader/config/itrader_config.py` | `ITraderConfig` frozen aggregator | ✓ VERIFIED | Frozen base + 6 mutable sub-models + lazy `sql` cached_property (inertness-safe) |
| `itrader/trading_system/config_router.py` | `ConfigRouter` (validate→persist→apply→push) | ✓ VERIFIED | Full D-21 scope→owner dispatch, D-14 venue-kind predicate, D-16 deduped WARNING |
| `itrader/events_handler/events/control.py::ConfigUpdateEvent` | CONTROL msgspec event | ✓ VERIFIED | Present, barrel-exported |
| `itrader/order_handler/base.py` + 3 impls `save_config`/`load_config` | Order-scope durable config surface | ✓ VERIFIED | `order_config` table (SQL) / delegate (cached) / dict (in-memory) |
| `itrader/portfolio_handler/base.py` + 3 impls `save_config`/`load_config` | Portfolio-scope durable config surface | ✓ VERIFIED | `config_json` column on `portfolio_account_state` + carry-forward clobber-safety |
| `itrader/storage/system_stats_store.py` | `system_stats` append-only store | ✓ VERIFIED | Lock-free reads, engine-written seq, no entity duplication |
| `migrations/versions/module_config.py`, `system_stats.py` | Migration chain finalization | ✓ VERIFIED | Single head confirmed via `alembic heads` → `system_stats (head)` |
| `tests/integration/test_config_restart_layering.py`, `test_config_ingress.py` | Mandatory integration tests | ✓ VERIFIED | Both present, independently re-run, all PASS |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `LiveRouteRegistrar.install()` | `ConfigRouter.apply` | `routes[EventType.CONFIG_UPDATE] = [self._on_config_update]` | ✓ WIRED | `route_registrar.py:134,161-170` |
| `build_live_system` | `ConfigRouter(...)` | Constructs with system_store/venue_store/order_handler/portfolio_handler/execution_handler/venue_kind/bus/clock | ✓ WIRED | `live_trading_system.py:1476-1496` |
| `build_live_system` | `_layer_persisted_overrides` | Called at boot after ConfigRouter construction | ✓ WIRED | `live_trading_system.py:1501-1508` |
| `add_event` | `ConfigRouter` (via queue) | `_EXTERNALLY_ADMISSIBLE` includes `CONFIG_UPDATE` + `_validate_config_ingress` pre-queue check | ✓ WIRED | `live_trading_system.py:56-58, 993-1107` |
| `SafetyController.update_status`/`halt` | `SystemStore.upsert` | `_persist_state("state.status"/"state.halt_reason", ...)` | ✓ WIRED | `safety_controller.py:494-518` |
| `build_live_system` | `SystemStatsStore` + `_snapshot_system_stats` | Constructed over shared SQL spine, appends on status transition | ✓ WIRED | `live_trading_system.py:441,1568-1573` |
| `EngineContext.config` | (intentionally NOT threaded) | Stays `Any`/vestigial per D-06 owner override | ✓ CONFIRMED VESTIGIAL | `engine_context.py:69,97` — no config-seam usage found |

### Behavioral Spot-Checks (independently re-run, not trusting SUMMARY claims)

| Behavior | Command | Result | Status |
|---|---|---|---|
| ConfigRouter unit suite (25 tests: happy-path, default-deny, venue-kind, validation, persist-failure, idempotency, immutable-key, portfolio blocker, scope-owner table) | `pytest tests/unit/trading_system/test_config_router.py -q` | 25 passed | ✓ PASS |
| Restart-layering + ingress integration (SQL-backed, real stores) | `pytest tests/integration/test_config_restart_layering.py tests/integration/test_config_ingress.py -q` | 8 passed | ✓ PASS |
| ITraderConfig frozen-base + validate_assignment unit suite | `pytest tests/unit/config/test_itrader_config.py -q` | 11 passed | ✓ PASS |
| system_stats store unit suite | `pytest tests/unit/storage/test_system_stats_store.py -q` | 5 passed | ✓ PASS |
| Backtest oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed (134/46189.87730727451) | ✓ PASS |
| OKX import-inertness | `pytest tests/integration/test_okx_inertness.py -q` | 4 passed | ✓ PASS |
| Migration parity + single-head | `pytest tests/integration/storage/test_migrations.py -q` | 7 passed | ✓ PASS |
| Alembic single-head confirmation | `alembic heads` | `system_stats (head)` | ✓ PASS |
| mypy --strict | `mypy itrader` | Success: no issues found in 261 source files | ✓ PASS |
| Debt-marker scan (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER) across all 17 phase-modified core files | `grep -nE ...` | 0 matches | ✓ PASS |

### Anti-Patterns Found

None. No debt markers (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER) in any phase-modified source file. No stub returns, no hardcoded-empty data flowing to a read path, no orphaned artifacts — every artifact created by the four plans is imported and exercised by a test that was independently re-run in this verification pass.

### Human Verification Required

None. This phase is entirely backend/infrastructure (config platform, event routing, durable storage, migrations) with no UI surface to visually inspect — every observable truth is verifiable by code inspection + automated test execution, all of which were independently re-run (not just trusted from SUMMARY.md).

### Gaps Summary

No gaps. All six RTCFG requirements (RTCFG-01..06) are implemented, wired, and independently verified against the actual codebase (not SUMMARY.md claims). The owner-override design (D-05/D-06/D-11 for the config-object model + allowlist, D-17/D-18 for the standalone `system_stats` table) was honored per the critical override instructions — none of the literal pre-override ROADMAP/REQUIREMENTS wording ("`RuntimeConfig` overlay injected as `EngineContext.config`", "`system_store` `stats.snapshot`") was flagged as a gap, since `09-CONTEXT.md` documents these as deliberate, owner-approved supersessions that were consistently implemented across all four plans.

One item — TEST-03 ("a config-restart gate") — is explicitly scoped to Phase 12 in REQUIREMENTS.md's own traceability table and is listed under Deferred Items above; it is not a Phase 9 requirement, and RTCFG-03 itself (which TEST-03 will eventually formalize into a milestone-wide gate) is already fully satisfied by Phase 9's own `tests/integration/test_config_restart_layering.py`.

---

_Verified: 2026-07-16T11:29:35Z_
_Verifier: Claude (gsd-verifier)_
