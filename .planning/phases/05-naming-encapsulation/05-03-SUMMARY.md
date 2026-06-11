---
phase: 05-naming-encapsulation
plan: 03
subsystem: strategy
tags: [naming, pascalcase, pydantic, strategy-config, macd, golden-master, mypy]

# Dependency graph
requires:
  - phase: 05-naming-encapsulation
    provides: NAME-01 (events_queue→global_queue) + NAME-03 (routes/register_symbol) renames; same behavior-preserving rename discipline
provides:
  - PascalCase strategy classes (SMAMACDStrategy, EmptyStrategy)
  - Self-describing SMA_MACDConfig window Fields (fast_window/slow_window/signal_window, defaults 6/12/3)
  - All run-path importers (tests + run_backtest.py) updated with no back-compat alias
affects: [naming-encapsulation, order-manager-decomposition, engine-surface-completion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PascalCase strategy class naming (SMAMACDStrategy / EmptyStrategy) matching the codebase PascalCase class convention"
    - "Self-describing *_window config Fields replace cryptic FAST/SLOW/WIN abbreviations (D-03)"
    - "Same-change importer rename, no back-compat alias (D-04) — breaking symbol updated atomically across all run-path sites"

key-files:
  created: []
  modified:
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/empty_strategy.py
    - tests/unit/strategy/test_strategy.py
    - tests/unit/strategy/test_strategy_config.py
    - tests/integration/test_backtest_oracle.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_reservation_inertness.py
    - scripts/run_backtest.py

key-decisions:
  - "D-03: rename strategy classes to PascalCase and config Fields to *_window; defaults stay value-equal 6/12/3 (the MACD window values, load-bearing)"
  - "D-04: no back-compat alias — every run-path importer updated in the same change"
  - "Module FILENAMES kept (SMA_MACD_strategy.py / empty_strategy.py) — renaming files adds import churn for no naming gain"
  - "SMA_MACDConfig class name kept (only Field names renamed) — importing SMA_MACDConfig keeps working"
  - "String literals left unchanged: logger component='SMA_MACD_strategy' (:13), super().__init__('SMA_MACD') (:51) — name literals, not class refs"
  - "_short_lt_long validator references only short_window/long_window in live code (no FAST/SLOW refs) — plan note was over-cautious; nothing to change there"

patterns-established:
  - "Golden re-run is the proof for value-bearing config renames: window values drive the MACD indicator and thus the 134 trades; new defaults must stay byte-exact"
  - "CRLF-tolerant TAB editing: SMA_MACD_strategy.py uses CRLF; edits preserve CRLF + TAB indentation, never normalizing line endings"

requirements-completed: [NAME-02]

# Metrics
duration: 6min
completed: 2026-06-11
---

# Phase 5 Plan 03: Strategy PascalCase + *_window Config Rename (NAME-02) Summary

**Renamed SMA_MACD_strategy→SMAMACDStrategy / Empty_strategy→EmptyStrategy and the SMA_MACDConfig window Fields FAST/SLOW/WIN→fast_window/slow_window/signal_window (defaults 6/12/3), updating every run-path importer with no alias — golden master byte-exact (134 trades / final_equity 46189.87730727451), e2e 58/58, mypy --strict clean.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-11T18:31Z
- **Completed:** 2026-06-11T18:37Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments
- PascalCase strategy classes: `SMA_MACD_strategy` → `SMAMACDStrategy`, `Empty_strategy` → `EmptyStrategy` (zero legacy class names remain)
- Self-describing config: `SMA_MACDConfig` Fields `FAST/SLOW/WIN` → `fast_window/slow_window/signal_window`, defaults value-equal `6/12/3`, `gt=0` preserved; instance attrs + MACD indicator call rewired
- All run-path importers updated in the same change (D-04, no alias): unit strategy tests, integration oracle/smoke/reservation tests, `scripts/run_backtest.py`
- Load-bearing golden re-run proven byte-exact (the window values drive the MACD → 134 trades / `final_equity 46189.87730727451`); e2e 58/58; `mypy --strict` clean (162 files)
- TAB indentation + CRLF line endings preserved in the strategy files; `SMA_MACDConfig` class name and the `"SMA_MACD"`/`"SMA_MACD_strategy"` string literals left unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): expect SMAMACDStrategy + *_window config** - `395d6f6` (test) — updated unit tests to the new names so they fail against the old source
2. **Task 1 (GREEN): rename strategy classes + config Fields** - `12f0b1f` (feat) — implemented the rename in `SMA_MACD_strategy.py` + `empty_strategy.py`
3. **Task 2: update run-path importers** - `ce13e98` (refactor) — integration tests + `run_backtest.py` to `SMAMACDStrategy`
4. **Task 3: verify golden byte-exact + e2e + mypy** - no commit (verification-only, no file changes)

_Note: Task 1 is TDD (test→feat). Task 3 changed no files (pure verification gate)._

## Files Created/Modified
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` - `SMAMACDStrategy` class; `fast_window/slow_window/signal_window` Fields + instance attrs; MACD call rewired
- `itrader/strategy_handler/strategies/empty_strategy.py` - `EmptyStrategy` class (config `EmptyStrategyConfig` already PascalCase)
- `tests/unit/strategy/test_strategy.py` - import + 4 call-sites → `SMAMACDStrategy`
- `tests/unit/strategy/test_strategy_config.py` - assertions → `cfg.fast_window/slow_window/signal_window`
- `tests/integration/test_backtest_oracle.py` - import + call → `SMAMACDStrategy`
- `tests/integration/test_backtest_smoke.py` - import + call → `SMAMACDStrategy`
- `tests/integration/test_reservation_inertness.py` - import + call → `SMAMACDStrategy`
- `scripts/run_backtest.py` - import + call → `SMAMACDStrategy`; D-03 docstring → `*_window` wording

## Decisions Made
- Followed the plan's D-03/D-04 site table exactly. One clarification: the live `_short_lt_long` validator references only `short_window`/`long_window` (no `FAST`/`SLOW`), so the plan's note about updating FAST/SLOW refs in the validator was a no-op — nothing to change there.
- `run_backtest.py:8` docstring `FAST=6/SLOW=12/WIN=3` updated to `*_window` wording to satisfy the `FAST=`/`SLOW=`/`WIN=` → 0 acceptance grep (oracle-dark comment).

## Deviations from Plan

None - plan executed exactly as written. (All renames matched the verified site table; no Rule 1-4 deviations triggered.)

## Issues Encountered
- **`git diff --check` reports "trailing whitespace" on `SMA_MACD_strategy.py` edited lines.** Investigated: the file uses **CRLF** line endings (pre-existing in HEAD on untouched lines too); `git diff --check` flags the `\r` as trailing whitespace, but only on lines that are part of the diff. This is a pre-existing file property — NOT introduced by the edits and NOT a mixed-indentation defect (all edited lines start with TAB, verified). Per the deviation scope boundary, the pre-existing CRLF was left as-is (normalizing it would be churn outside this plan's scope). `empty_strategy.py` (LF) and all 4-space test/script files are `git diff --check` clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- NAME-02 complete; the strategy-naming surface is now PascalCase + self-describing config.
- Remaining Phase 5 plan: 05-04 (NAME-04 test-hygiene + any remaining encapsulation). Phase 6 (MOD-01, order_manager split) stays the isolated LAST phase.
- Milestone gate held: golden byte-exact (134 / 46189.87730727451), e2e 58/58, mypy --strict clean — no oracle re-baseline.

## Self-Check: PASSED

- Files verified present: `SMA_MACD_strategy.py` (SMAMACDStrategy), `empty_strategy.py` (EmptyStrategy), `05-03-SUMMARY.md`
- Commits verified in git log: `395d6f6` (RED), `12f0b1f` (GREEN), `ce13e98` (refactor), `6c3c622` (docs)

---
*Phase: 05-naming-encapsulation*
*Completed: 2026-06-11*
