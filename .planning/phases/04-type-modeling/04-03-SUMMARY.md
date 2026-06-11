---
phase: 04-type-modeling
plan: 03
subsystem: config
tags: [pydantic, strategy-config, code-motion, refactor, type-modeling]

# Dependency graph
requires:
  - phase: 03-config-collapse (M2b)
    provides: "Pydantic config/ package with grouped re-export pattern (ExchangeConfig/PortfolioConfig/SystemConfig)"
provides:
  - "BaseStrategyConfig relocated to itrader/config/strategy.py, re-exported via config/__init__.py"
  - "SMA_MACDConfig co-located in strategies/SMA_MACD_strategy.py (tab-indented)"
  - "EmptyStrategyConfig co-located in strategies/empty_strategy.py (tab-indented)"
  - "strategy_handler/config.py removed; all D-16 importers updated"
affects: [strategy-config-system-refactor, engine-surface-completion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Strategy config base lives in config/ alongside other domain configs (TYPE-05/SYN-02)"
    - "Concrete strategy configs co-located in their strategy modules (D-14)"

key-files:
  created:
    - itrader/config/strategy.py
  modified:
    - itrader/config/__init__.py
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/empty_strategy.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/signal_record.py
    - scripts/run_backtest.py
    - tests/unit/strategy/test_strategy_config.py
    - tests/unit/strategy/test_strategy.py
    - tests/unit/strategy/test_signal_store.py
    - tests/integration/test_universe_spans.py
    - tests/integration/test_backtest_oracle.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_reservation_inertness.py
    - tests/e2e/strategies/single_market_buy.py
    - tests/e2e/strategies/scripted_emitter.py

key-decisions:
  - "Folded SMA_MACDConfig imports into the existing same-module SMA_MACD_strategy import lines (no duplicate import statements)"
  - "config.py deletion landed in the Task 2 commit (it was git-rm staged before the strategy-file commit); importer updates committed separately as Task 3"

patterns-established:
  - "BaseStrategyConfig is sourced from itrader.config (D-16); concrete configs from their strategy modules"

requirements-completed: [TYPE-05]

# Metrics
duration: 12min
completed: 2026-06-11
---

# Phase 04 Plan 03: Strategy Config Relocation Summary

**Relocated `BaseStrategyConfig` to `itrader/config/strategy.py` (re-exported via `config/__init__.py`), co-located the concrete `SMA_MACDConfig`/`EmptyStrategyConfig` into their tab-indented strategy modules, removed `strategy_handler/config.py`, and updated all 14 D-16 importers — oracle byte-exact, mypy --strict clean, e2e 58/58.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-11T16:00:00Z (approx)
- **Completed:** 2026-06-11T16:10:00Z (approx)
- **Tasks:** 3
- **Files modified:** 1 created + 15 modified (config.py removed)

## Accomplishments
- `BaseStrategyConfig` now lives in `itrader/config/strategy.py` (4-space house) and is re-exported via `config/__init__.py` + `__all__`, consistent with `ExchangeConfig`/`PortfolioConfig`/`SystemConfig`.
- `SMA_MACDConfig` (incl. the `_short_lt_long` HARD-02 validator) and `EmptyStrategyConfig` co-located into their strategy files, re-indented to TABS to match the destination tab-house (D-15) — fields/defaults/validator preserved verbatim.
- `strategy_handler/config.py` removed; every importer in the D-16 list (handlers, 5 unit/integration tests, 2 e2e strategy files, run_backtest.py) updated to source from the new homes. Zero remaining `strategy_handler.config` references.
- Oracle held byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict itrader` clean across 139 source files; `pytest tests/e2e -m e2e` 58/58, `tests/unit/strategy tests/integration` 33/33 green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create config/strategy.py with BaseStrategyConfig; re-export via config/__init__.py** - `f4600ec` (refactor)
2. **Task 2: Co-locate concrete configs into strategy files (re-indent to TABS)** - `9650b4a` (refactor; also carried the `git rm` of config.py)
3. **Task 3: Update all D-16 importers of the old strategy_handler.config** - `1553b62` (refactor)

## Files Created/Modified
- `itrader/config/strategy.py` - New 4-space pydantic module holding the relocated `BaseStrategyConfig` base contract.
- `itrader/config/__init__.py` - Added `from .strategy import BaseStrategyConfig` re-export + `__all__` entry.
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` - Co-located tab-indented `SMA_MACDConfig` (validator preserved); import sourced from `itrader.config`.
- `itrader/strategy_handler/strategies/empty_strategy.py` - Co-located tab-indented `EmptyStrategyConfig`; import sourced from `itrader.config`.
- `itrader/strategy_handler/base.py`, `signal_record.py` - `BaseStrategyConfig` import retargeted to `itrader.config`.
- `scripts/run_backtest.py` + 8 test files - importer updates (BaseStrategyConfig → `itrader.config`; concrete configs → strategy modules).
- `itrader/strategy_handler/config.py` - Removed (no remaining importers).

## Decisions Made
- Where a file already imported `SMA_MACD_strategy` from the same strategy module, `SMA_MACDConfig` was folded into that existing import line rather than adding a second statement (cleaner diff, no semantic change).
- The `config.py` deletion was `git rm`-staged before the Task 2 commit, so it landed in `9650b4a` rather than the Task 3 commit. Tree consistency is preserved because the same Task-2 working set still imported from it only transiently; the full importer cleanup (Task 3, `1553b62`) leaves zero stale references. Verified post-commit: no `strategy_handler.config` references, config.py removed.

## Deviations from Plan

None - plan executed exactly as written. (The only ordering nuance — config.py removal landing in the Task 2 commit instead of Task 3 — is a commit-grouping detail, not a behavioral or content deviation; the end state matches the plan's acceptance criteria exactly.)

## Issues Encountered
- A compound `git add` in the intended Task 3 commit referenced the already-removed `config.py` path and aborted that commit (pathspec mismatch). Resolved by re-running the commit without the stale path — config.py was already deleted/committed in Task 2. Final tree clean, all three task commits present.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The strategy-config base now sits with the other domain configs, ready for the next-milestone strategy-setting system refactor (this plan was deliberately minimal co-location, NOT a config-system redesign).
- No blockers. Oracle byte-exact, mypy --strict clean, full strategy/integration/e2e coverage green.

## Self-Check: PASSED
- `itrader/config/strategy.py` — FOUND
- `itrader/strategy_handler/config.py` — REMOVED (confirmed absent)
- Commits `f4600ec`, `9650b4a`, `1553b62` — FOUND in git log
- mypy --strict: 0 issues (139 files); oracle 134 trades / 46189.87730727451; e2e 58/58; unit-strategy+integration 33/33

---
*Phase: 04-type-modeling*
*Completed: 2026-06-11*
