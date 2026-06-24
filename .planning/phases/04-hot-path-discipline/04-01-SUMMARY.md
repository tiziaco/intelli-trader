---
phase: 04-hot-path-discipline
plan: 01
subsystem: infra
tags: [logging, structlog, performance, pydantic-settings, isEnabledFor, perf-03]

# Dependency graph
requires:
  - phase: 01-perf-tooling-baseline
    provides: gate (a)/(b) definition + the W1 benchmark harness this phase's win is measured against
  - phase: 03-running-pnl-accumulator
    provides: the audit-the-invariant + dedicated drift-lock-test precedent (D-03) reused here as D-06
provides:
  - "Central isEnabledFor level-gate inside every ITraderStructLogger wrapper method (D-02) — below-level calls return before the 9-processor structlog pipeline (hotspot #4)"
  - "ITRADER_DISABLE_LOGS kill-switch (D-08) — cached bool checked first in each guard, declared as Settings.disable_logs, read via os.environ (no import-time Settings())"
  - "Per-bar admission-rejection log demoted error->warning + cached isEnabledFor(WARNING) guard (D-01) — gates out at the ITRADER_LOG_LEVEL=ERROR benchmark level"
  - "8 owner-signed-off internal-mechanics hot-path debug() calls deleted (D-04); 4 live-trading-visibility lines kept"
  - "04-LOGGING-AUDIT.md + tests/unit/core/test_logging_gate.py — the D-06 behavior-preservation drift lock (written + executable)"
affects: [phase-04-plan-02-perf-04-type-hints, phase-04-gate-b-refreeze, n4-live-trading-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Central wrapper-level isEnabledFor short-circuit (cache stdlib logger in __init__, carry _stdlib through bind()'s __new__)"
    - "Env-var kill-switch resolved once at import into a module-level cached bool, mirroring _env_json_logs (never Settings() at import — Pitfall 8)"
    - "Demote-not-delete for expected-but-noteworthy conditions: warning gates out at the benchmark ERROR level while staying visible at INFO"

key-files:
  created:
    - tests/unit/core/test_logging_gate.py
    - .planning/phases/04-hot-path-discipline/04-LOGGING-AUDIT.md
  modified:
    - itrader/logger.py
    - itrader/config/settings.py
    - itrader/order_handler/admission/admission_manager.py
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/portfolio_handler/cash/cash_manager.py

key-decisions:
  - "D-02: one central isEnabledFor gate in the ITraderStructLogger wrapper covers all 21 components — no per-callsite guards"
  - "D-01: demote the admission rejection error->warning (not debug) so it gates out at the ERROR benchmark while keeping INFO out-of-cash visibility; audit trail is log-level-independent"
  - "D-03: leave the admission eager list-comp arg as-is, guarded only behind isEnabledFor (the central gate cannot skip eager args)"
  - "D-08: ITRADER_DISABLE_LOGS is a dedicated boolean; the logger reads it cache-once via os.environ, the Settings field is the documented knob surface"
  - "D-04: curated hot-path-only debug() removal under per-line owner sign-off — delete internal mechanics, keep live-trading lines, never touch info() or promote levels"

patterns-established:
  - "Logging behavior-preservation audit (D-06): every change is central-gate/demote/delete-debug, none alters emitted content at an enabled level; oracle/e2e don't observe logs so the unit-level gate test is the drift lock"

requirements-completed: [PERF-03]

# Metrics
duration: 17min
completed: 2026-06-24
---

# Phase 4 Plan 01: Hot-Path Logging Discipline (PERF-03) Summary

**Central `isEnabledFor` level-gate + `ITRADER_DISABLE_LOGS` kill-switch in `ITraderStructLogger`, admission-rejection log demoted `error`→`warning` with a cached `isEnabledFor(WARNING)` guard, 8 owner-signed-off internal-mechanics `debug()` deletes, and a written + executable D-06 behavior-preservation drift lock — oracle byte-exact throughout.**

## Performance

- **Duration:** ~17 min active (excludes the blocking human-verify checkpoint wait for Task 3 sign-off)
- **Started:** 2026-06-24T10:05Z (approx)
- **Completed:** 2026-06-24T10:22:37Z
- **Tasks:** 4 (Task 3 was a blocking human-verify checkpoint, owner-approved with no amendments)
- **Files modified:** 5 source + 2 docs/test created

## Accomplishments

- **D-02 central level-gate:** every `ITraderStructLogger` wrapper method (`debug`/`info`/`warning`/`error`/`critical` + `warn`) now short-circuits via `self._stdlib.isEnabledFor(<level>)` before the 9-processor structlog pipeline — the whole ~6% W1 / ~22% W2 logging win (hotspot #4). `__init__` caches `_stdlib`; `bind()` carries it through `__new__`. `exception()` stays always-emit.
- **D-08 kill-switch:** `ITRADER_DISABLE_LOGS` declared as `Settings.disable_logs` (pydantic native coercion), read cache-once into a module-level `_DISABLE_LOGS` via `os.environ` (no import-time `Settings()` — Pitfall 8), checked first in every guard.
- **D-01 demotion:** the per-bar admission-rejection log went `error`→`warning` + cached `isEnabledFor(WARNING)` guard around the eager f-string + list-comp; it now gates out at the `ITRADER_LOG_LEVEL=ERROR` benchmark level while still emitting at INFO. The audit trail (`add_state_change`/`add_order`) is untouched and log-level-independent.
- **D-04 curated deletes:** applied exactly the 8 owner-signed-off internal-mechanics `debug()` rows; kept the 4 live-trading-visibility lines; no `info()` touched, no level promoted, no mixed-indent.
- **D-06 drift lock:** `04-LOGGING-AUDIT.md` (written) + `tests/unit/core/test_logging_gate.py` (8 tests, executable) prove every change is content-preserving at an enabled level.

## Task Commits

1. **RED — failing logging gate tests** - `cfe392e` (test)
2. **Task 1: central level-gate + ITRADER_DISABLE_LOGS kill-switch (D-02, D-08)** - `25402ab` (feat)
3. **Task 2: demote admission log error→warning + guard (D-01, D-03, D-06)** - `3adfb27` (feat)
4. **Task 3: apply owner-signed-off hot-path debug() deletes (D-04)** - `1b0a712` (refactor)
5. **Task 4: write D-06 logging behavior-preservation audit** - `773378d` (docs)

_TDD note: Tasks 1-2 followed RED (`cfe392e`) → GREEN (`25402ab`, `3adfb27`). The admission-content + demotion-gating assertions for Task 2 were added in the Task 2 commit._

## Files Created/Modified

- `itrader/logger.py` - `_env_disable_logs` helper + module-level cached `_DISABLE_LOGS`; `_stdlib` cached in `__init__` and carried through `bind()`; `isEnabledFor` + kill-switch gate at the top of every wrapper method
- `itrader/config/settings.py` - `disable_logs: bool = False` field (`ITRADER_DISABLE_LOGS`)
- `itrader/order_handler/admission/admission_manager.py` - rejection log `error`→`warning` + `isEnabledFor(WARNING)` guard; `import logging`; deleted the `'Processed signal'` debug
- `itrader/portfolio_handler/position/position_manager.py` - deleted `'Position updated'` + `'Position market values updated'` debug
- `itrader/portfolio_handler/cash/cash_manager.py` - deleted `'Fill cash flow applied'`, `'Cash reserved'`, `'Cash reservation released'`, `'Margin locked'`, `'Margin released'` debug
- `tests/unit/core/test_logging_gate.py` - 8 gate-transparency / disable-logs / admission-content tests
- `.planning/phases/04-hot-path-discipline/04-LOGGING-AUDIT.md` - the D-06 written audit

## Decisions Made

None beyond the plan's locked decisions (D-01..D-08). The Task 3 checkpoint was approved with no amendments — exactly the proposed 8 DELETE rows were applied and the 4 KEEP rows preserved.

## Deviations from Plan

None - plan executed exactly as written. (Two test-only fixes were applied to my own RED test before GREEN, not to production code: `structlog.stdlib.PositionalArgumentsFormatter` instead of `structlog.processors.*`, and reaching the `itrader.logger` module through `sys.modules` because `itrader/__init__.py` shadows the submodule name with the logger instance. Both are test-harness corrections within Task 1, committed in `25402ab`.)

## Issues Encountered

- **Worktree `.venv` shadowing:** there is no `.venv` in the worktree, so pytest/mypy resolve against the main checkout's editable install and would not see worktree edits. Resolved by prepending `PYTHONPATH="$PWD"` to every `poetry run` invocation (per the known `worktree-venv-shadowing` gotcha).
- **`itrader.logger` name shadowing:** `itrader/__init__.py` binds `logger = init_logger(...)`, so `import itrader.logger as logmod` resolves to the logger *instance*, not the module. The disable-flag monkeypatch test reaches the real module via `sys.modules["itrader.logger"]`. Documented inline in the test.

## Verification

- Gate (a): `tests/integration/test_backtest_oracle.py` byte-exact — 134 trades / `final_equity 46189.87730727451` (held after every task).
- `tests/unit/core/test_logging_gate.py` — 8/8 green.
- `mypy --strict` clean on all 5 touched source files.
- Touched-domain suites green: `tests/unit/{portfolio,order,core}` 666 passed; `tests/unit/{execution,strategy}` + oracle + gate test 272 passed.
- Diff discipline verified: 8 `.debug(` deletions, 0 `.info(`/level edits; admission audit block (`add_state_change`/`add_order`) untouched; no mixed-indent introduced (4-space files stay 4-space, tab file stays tab).

## Notes for the Orchestrator / Next Phase

- **STATE.md / ROADMAP.md NOT modified** (worktree mode — orchestrator owns those writes).
- **Gate (b) is NOT measured here** (this plan is the behavior change; gate (b) re-freeze is Plan 04-02 per the plan's success criteria). Honor the pending todo: re-freeze `W1-BASELINE.json` on a cool machine before Phase 4's gate (b) is measured, else Phase 4 over-credits its own win by ~15% against the pre-Phase-3 baseline.
- **PERF-04 (`get_type_hints` memoization) is NOT in this plan** — Plan 04-01 scoped only PERF-03 (the 4 logging tasks). PERF-04 is a separate plan in this phase.

## Self-Check: PASSED

All 7 created/modified key files exist on disk; all 5 task commits (`cfe392e`, `25402ab`, `3adfb27`, `1b0a712`, `773378d`) present in `git log`.

---
*Phase: 04-hot-path-discipline*
*Completed: 2026-06-24*
