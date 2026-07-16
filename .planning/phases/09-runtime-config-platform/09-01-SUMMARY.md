---
phase: 09-runtime-config-platform
plan: 01
subsystem: config
tags: [pydantic, config, frozen-model, validate_assignment, determinism, rng_seed, runtime-config]

# Dependency graph
requires:
  - phase: 07-safety-reconciliation-stream-recovery
    provides: eager config sub-models (StreamSettings/SafetySettings/OrderConfig) + SystemConfig aggregator to repurpose
provides:
  - "ITraderConfig frozen top-level aggregator (config/itrader_config.py) — the process config root"
  - "Immutable determinism/identity base params on the frozen base (rng_seed, environment, name, version, debug_mode, dirs) — RTCFG-04 by field placement"
  - "Mutable domain sub-models with validate_assignment=True (system, universe, stream, feed_provider, safety, order, runtime) — the Wave-2 mutation surface (RTCFG-01)"
  - "SystemSettings (demoted lifecycle knobs) + UniverseConfig (poll_cadence_s/remove_policy) sub-models"
  - "config = ITraderConfig() singleton (create-once, mutate-in-place, never reassign)"
  - "config.rng_seed / config.universe.* new read-site paths (moved off config.performance.* / config.monitoring.*)"
affects: [09-02, 09-03, runtime-config-router, build_live_system, config-restart-layering]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen aggregator base (immutable determinism/identity) + non-frozen mutable sub-models (mutation overlay) — the allowlist IS the structure (D-07/D-11)"
    - "validate_assignment=True on mutable sub-models — Pydantic re-runs coercion + Field() constraints on every setattr (D-13)"
    - "Immutable-at-runtime keys placed DIRECTLY on the frozen base (Pitfall 5); lazy sql @cached_property keeps SQL/ccxt off the import graph (GATE-01)"

key-files:
  created:
    - itrader/config/itrader_config.py
    - tests/unit/config/test_itrader_config.py
  modified:
    - itrader/config/system.py
    - itrader/config/stream.py
    - itrader/config/safety.py
    - itrader/config/order.py
    - itrader/config/__init__.py
    - itrader/config/models.py
    - itrader/__init__.py
    - itrader/execution_handler/execution_handler.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/worker_supervisor.py

key-decisions:
  - "ITraderConfig is the new frozen root; SystemConfig retained as a narrowed legacy aggregator (performance/monitoring + lifecycle fields stripped) so existing config tests stay green rather than deleting/rewriting them"
  - "SystemSettings + UniverseConfig live in config/system.py (not a new module) alongside the Environment/LogLevel enums"
  - "Lifecycle knobs (enable_auto_restart etc.) are 0-ref — removed from SystemConfig entirely and redefined on the new SystemSettings sub-model; live-runner tunables (_LIVE_QUEUE_TIMEOUT/_LIVE_MAX_IDLE_TIME) deliberately NOT folded (LiveRunner-local, not lifecycle config)"

patterns-established:
  - "Frozen-base + mutable-sub-model config: immutability is a property of WHERE a field lives, not object identity"
  - "Config singleton create-once/mutate-in-place/never-reassign so from-import readers see runtime changes"

requirements-completed: [RTCFG-01, RTCFG-04]

coverage:
  - id: D1
    description: "ITraderConfig frozen base rejects runtime setattr on immutable determinism/identity keys (rng_seed, environment) — thread-agnostic"
    requirement: RTCFG-04
    verification:
      - kind: unit
        ref: "tests/unit/config/test_itrader_config.py#test_frozen_base_rejects_rng_seed_setattr, test_frozen_base_rejects_environment_setattr, test_frozen_base_rejection_is_thread_agnostic"
        status: pass
    human_judgment: false
  - id: D2
    description: "Mutable sub-models mutate in place with validate_assignment coercion + Field() constraint enforcement (config.<sub>.<field> = X)"
    requirement: RTCFG-01
    verification:
      - kind: unit
        ref: "tests/unit/config/test_itrader_config.py#test_sub_model_field_mutates_in_place, test_validate_assignment_coerces_str_to_int, test_validate_assignment_enforces_field_constraint, test_validate_assignment_rejects_unknown_sub_model_key"
        status: pass
    human_judgment: false
  - id: D3
    description: "config = ITraderConfig() is import-inert (no SQL/ccxt) — okx inertness gate stays green"
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "rng_seed path move (config.performance.rng_seed -> config.rng_seed) keeps the backtest oracle byte-exact 134 / 46189.87730727451"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-16
status: complete
---

# Phase 9 Plan 01: Config Hierarchy Restructure Summary

**Introduced `ITraderConfig` — a frozen Pydantic root whose immutable determinism/identity base params (incl. `rng_seed`) reject runtime mutation while its `validate_assignment` domain sub-models form the runtime-config mutation surface — flipped the process singleton to it and kept the backtest oracle byte-exact.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-16T09:55:00Z (approx)
- **Completed:** 2026-07-16T10:20:09Z
- **Tasks:** 3
- **Files modified:** 11 (2 created, 9 modified)

## Accomplishments
- New `ITraderConfig` frozen aggregator (`config/itrader_config.py`): `rng_seed`/`environment`/identity/dirs on the frozen base (RTCFG-04 by placement, Pitfall 5), seven mutable domain sub-models as the runtime-config overlay (RTCFG-01).
- Added `SystemSettings` (demoted lifecycle knobs, D-08) + `UniverseConfig` (`poll_cadence_s`/`remove_policy`, ex-`MonitoringSettings`, D-09); added `validate_assignment=True` to `Stream`/`FeedProvider`/`Safety`/`Order` sub-models (D-13).
- Atomic cutover: `config = ITraderConfig()` singleton (create-once, mutate-in-place); moved both `rng_seed` reads to `config.rng_seed` and both universe reads to `config.universe.*`; deleted `PerformanceSettings`/`MonitoringSettings`.
- 11-test `test_itrader_config.py` covering frozen-base rejection (incl. thread-agnostic), sub-model mutate, validate_assignment coercion/constraint/extra-forbid, sub-model-reassign block (Pitfall 5), and the unhashable gotcha (Pitfall 4).

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ITraderConfig frozen aggregator + SystemSettings/UniverseConfig sub-models** - `a86ec283` (feat)
2. **Task 2: Author tests/unit/config/test_itrader_config.py (RTCFG-01/04)** - `d3cddcee` (test)
3. **Task 3: Atomic cutover — flip singleton, move rng_seed + universe read sites, delete PerformanceSettings/MonitoringSettings** - `4cddd845` (feat)

## Files Created/Modified
- `itrader/config/itrader_config.py` - NEW frozen `ITraderConfig` root (frozen base + mutable sub-models + lazy sql accessor)
- `itrader/config/system.py` - Added `SystemSettings`/`UniverseConfig`; deleted `PerformanceSettings`/`MonitoringSettings`; stripped `performance`/`monitoring` + lifecycle fields from the narrowed legacy `SystemConfig`
- `itrader/config/stream.py`, `safety.py`, `order.py` - Added `validate_assignment=True` to the mutable sub-models
- `itrader/config/__init__.py`, `models.py` - Export `ITraderConfig`/`SystemSettings`/`UniverseConfig`; drop deleted-symbol exports
- `itrader/__init__.py` - `config = SystemConfig.default()` → `config = ITraderConfig()` (D-06 create-once/mutate-in-place)
- `itrader/execution_handler/execution_handler.py`, `trading_system/backtest_trading_system.py` - `config.performance.rng_seed` → `config.rng_seed` (oracle-gated)
- `itrader/trading_system/live_trading_system.py` - `config.monitoring.universe_*` → `config.universe.*`
- `itrader/trading_system/worker_supervisor.py` - Doc reference updated to `config.universe.poll_cadence_s`
- `tests/unit/config/test_itrader_config.py` - NEW (package-less dir, no `__init__.py`)

## Decisions Made
- **Keep `SystemConfig` as a narrowed legacy aggregator** rather than deleting it: the plan directs stripping `performance`/`monitoring` + lifecycle fields (not deleting the class), and the existing `tests/unit/config/test_system_config.py` still exercises `SystemConfig` (`runtime`/`stream`/`feed_provider`/`sql`/`from_dict`). Keeping it stripped-but-present kept those tests green without out-of-scope test edits.
- **Sub-models in `system.py`** (D-09 allowed either `system.py` or a new module) — colocated with `Environment`/`LogLevel` for cohesion.
- **Lifecycle knobs are 0-ref** (verified by grep) — removed from `SystemConfig`, redefined on `SystemSettings`; live-runner module tunables NOT folded (not lifecycle config).

## Deviations from Plan

None - plan executed exactly as written. (One self-corrected authoring slip during Task 3: the lifecycle fields were briefly relocated after the `sql` accessor before being removed entirely, corrected before any commit — no functional impact.)

## Issues Encountered
- A `git`-uncommitted intermediate edit in Task 3 duplicated the lifecycle fields (added after `sql` while still present before it); caught and removed before staging/commit. No committed state ever carried the duplicate.

## User Setup Required
None - no external service configuration required. Zero new dependencies (STATE gate "no poetry change P1-P12" holds).

## Next Phase Readiness
- Wave 2 (mutation path) has its target structure: the frozen-base allowlist (immutable keys reject) + the seven `validate_assignment` mutable sub-models to `setattr`-route `(scope, key)` into, and the create-once/mutate-in-place singleton `build_live_system` will layer persisted overrides into.
- Per-plan gates green: backtest oracle byte-exact `134 / 46189.87730727451`, OKX inertness green, `mypy --strict` clean (259 files), full suite `2259 passed / 6 skipped`.

## Self-Check: PASSED

- Created files verified present: `itrader/config/itrader_config.py`, `tests/unit/config/test_itrader_config.py`, `09-01-SUMMARY.md`
- Task commits verified in git log: `a86ec283`, `d3cddcee`, `4cddd845` (+ SUMMARY `5b4683c9`)

---
*Phase: 09-runtime-config-platform*
*Completed: 2026-07-16*
