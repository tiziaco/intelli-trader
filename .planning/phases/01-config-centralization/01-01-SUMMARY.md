---
phase: 01-config-centralization
plan: 01
subsystem: infra
tags: [pydantic, config, cached_property, import-inertness, sqlsettings]

# Dependency graph
requires:
  - phase: v1.7 (config Pydantic migration, M2-06)
    provides: SystemConfig / Settings / SqlSettings Pydantic models
provides:
  - "SystemConfig aggregates cardinality-1 singletons: performance/monitoring/runtime(eager)/sql(lazy)"
  - "Import-safe lazy sql accessor (functools.cached_property) — no SqlSettings built at import"
  - "extra='forbid' policy on SystemConfig (config typos raise loudly)"
  - "Register-vs-build inertness assertion in test_okx_inertness _PROBE"
affects: [event-bus, engine-context, storage-schema, venue-registry, live-runner]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy config arm via functools.cached_property (register-on-class, build-on-first-access) keeps Postgres SqlSettings off the import graph"
    - "extra='forbid' on aggregation config models to catch mass-assignment / typos"

key-files:
  created:
    - tests/unit/config/test_system_config.py
  modified:
    - itrader/config/system.py
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "sql is a cached_property, NOT a pydantic field — invisible to model_validate/serialization, built only on first access (D-05/D-06)"
  - "runtime kept eager (Settings default_factory) — reads ITRADER_* env but builds no SqlSettings (D-07)"
  - "extra flipped ignore->forbid; orphaned domain YAML confirmed dead (zero loaders) before the flip (D-09/D-12)"
  - "order stays OUT of SystemConfig (reclassified cardinality-N, D-03/D-04); model stays mutable (D-01)"

patterns-established:
  - "Lazy-arm inertness lever: heavy/credentialed config (Postgres) resolves via cached_property on first access, never at import — proven by 'sql' not in config.__dict__ post-import"
  - "Dead-config audit is conservative: prove zero references (grep -rn 'settings/domains' itrader/ empty) before removing an override"

requirements-completed: [CFG-01, CFG-02, CFG-04]

coverage:
  - id: D1
    description: "SystemConfig exposes eager runtime (Settings) field"
    requirement: CFG-01
    verification:
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_runtime_is_eager_settings_field"
        status: pass
    human_judgment: false
  - id: D2
    description: "sql is a cached_property (register-vs-build), not a pydantic field, unbuilt at import"
    requirement: CFG-02
    verification:
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_sql_is_cached_property_not_a_field"
        status: pass
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_sql_is_unbuilt_at_import"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py#test_backtest_path_imports_no_okx_stack (extended: 'sql' not in config.__dict__)"
        status: pass
    human_judgment: false
  - id: D3
    description: "order excluded from SystemConfig (D-03/D-04 cardinality-N)"
    requirement: CFG-01
    verification:
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_order_is_not_a_system_config_field"
        status: pass
    human_judgment: false
  - id: D4
    description: "extra='forbid' raises pydantic.ValidationError on unknown keys"
    requirement: CFG-02
    verification:
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_unknown_key_raises_validation_error"
        status: pass
    human_judgment: false
  - id: D5
    description: "Conservative dead-config audit: zero YAML loaders, orphaned domain overrides removed, __pycache__ clean"
    requirement: CFG-04
    verification:
      - kind: other
        ref: "grep -rn 'settings/domains' itrader/ (empty) ; git ls-files | grep -c '__pycache__|.pyc$' == 0"
        status: pass
    human_judgment: false
  - id: D6
    description: "SMA_MACD oracle byte-exact + OKX inertness gate stay green"
    requirement: CFG-02
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (134 / 46189.87730727451)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (INERTNESS_OK)"
        status: pass
    human_judgment: false

# Metrics
duration: ~12min
completed: 2026-07-09
status: complete
---

# Phase 01 Plan 01: Config Centralization Summary

**SystemConfig now aggregates performance/monitoring/runtime(eager)/sql(lazy) with a functools.cached_property `sql` arm that keeps Postgres SqlSettings off the import graph, plus an extra='forbid' flip — oracle byte-exact and OKX inertness both green.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-09 (execution start)
- **Completed:** 2026-07-09
- **Tasks:** 3
- **Files modified:** 3 tracked (1 created, 2 modified) + 2 untracked/gitignored YAML deletions

## Accomplishments
- Added eager `runtime: Settings` field to SystemConfig (D-07) — reads ITRADER_* env, builds no SqlSettings.
- Added lazy `sql` accessor as a `functools.cached_property` (D-05/D-06) — NOT a pydantic field; constructed only on first access, so nothing DB-related is built at import (the milestone's core inertness lever).
- Flipped `model_config` from `extra="ignore"` to `extra="forbid"` (D-09) and corrected the `from_dict` docstring accordingly.
- Extended the OKX inertness `_PROBE` with a register-vs-build assertion (`"sql" not in config.__dict__` after import), and authored a 5-assertion unit module.
- Ran the conservative dead-config audit: confirmed zero YAML loaders, removed the two orphaned gitignored domain overrides, verified `__pycache__` hygiene (0 tracked).

## Task Commits

Each task committed atomically:

1. **Task 1: Author failing SystemConfig unit tests + extend inertness probe** — `ab745222` (test)
2. **Task 2: Add eager runtime + lazy sql + flip extra=forbid** — `476df49a` (feat, TDD GREEN)
3. **Task 3: Conservative dead-config audit + __pycache__ verify-clean** — no code commit (see note)

**Plan metadata:** committed with this SUMMARY + STATE.md + ROADMAP.md.

_Note (Task 3): the two orphaned overrides (`settings/domains/system.default.yaml`, `trading.default.yaml`) live under the gitignored `settings/` tree and were untracked, so their deletion produces zero git diff — exactly as the plan anticipated. The committed, verifiable outcome of CFG-04 is the `extra="forbid"` flip (Task 2) plus the zero-loader confirmation here._

## Files Created/Modified
- `tests/unit/config/test_system_config.py` (created) — 5 assertions: runtime eager, sql cached_property register-vs-build, sql unbuilt-at-import, order excluded, extra=forbid raises.
- `itrader/config/system.py` (modified) — imports cached_property/Settings/SqlSettings; eager `runtime` field; lazy `sql` cached_property; `extra="forbid"`; corrected `from_dict` docstring.
- `tests/integration/test_okx_inertness.py` (modified) — `_PROBE` extended with `"sql" not in config.__dict__` register-vs-build assertion.
- `settings/domains/system.default.yaml`, `settings/domains/trading.default.yaml` (deleted; untracked/gitignored — no git diff).

## Decisions Made
None beyond the plan — all decisions (D-01..D-13) were pre-specified and followed as written.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. `functools.cached_property` composes cleanly with pydantic v2 BaseModel (as the RESEARCH doc pre-verified against pydantic 2.13.4); no `ignored_types` workaround needed.

## Verification Evidence
- `poetry run pytest tests/unit/config/test_system_config.py -q` → 5 passed.
- `poetry run pytest tests/integration/test_okx_inertness.py -q` → 2 passed (INERTNESS_OK; `"sql" not in config.__dict__` holds in fresh interpreter).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (SMA_MACD 134 / 46189.87730727451 unchanged).
- `poetry run mypy itrader/config/system.py` → Success: no issues found.
- `poetry run pytest tests/unit/config tests/unit/core ... -q` → 166 passed.
- `grep -rn "settings/domains" itrader/` → empty; `git ls-files | grep -c "__pycache__|.pyc$"` → 0.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `SystemConfig` is now the single import-safe config singleton; the lazy `sql` arm and `extra="forbid"` policy are the substrate the remaining Phase 01 plans (01-02..01-04) and downstream milestone phases build on.
- No blockers. Both frozen gates (oracle byte-exact, OKX inertness) remain green.

## Self-Check: PASSED

- Files verified: `tests/unit/config/test_system_config.py`, `itrader/config/system.py`, `01-01-SUMMARY.md` all present.
- Commits verified: `ab745222` (test), `476df49a` (feat) both in git log.

---
*Phase: 01-config-centralization*
*Completed: 2026-07-09*
