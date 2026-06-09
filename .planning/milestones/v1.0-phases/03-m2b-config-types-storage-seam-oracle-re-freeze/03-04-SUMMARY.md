---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 04
subsystem: timing
tags: [time_parser, timeframe, epoch-alignment, timedelta, dst, oracle]

# Dependency graph
requires:
  - phase: 03-01
    provides: D-17 inertness reference + Wave-0 characterization stubs (M2-10 stub) the corrected behavior is asserted against
provides:
  - Single replaceable Unix-epoch alignment seam (_aligned) gating strategy/screener firing
  - Case-insensitive to_timedelta with week support, month-specific raise, None guard, raise-on-unknown
  - Dead-helper purge (format_timeframe, elapsed_time, round_timestamp_to_frequency)
affects: [03-09 oracle re-freeze, M5 stock-calendar anchor seam, screeners_handler, strategies_handler]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single replaceable alignment seam: callers gate on check_timeframe -> _aligned; never re-implement alignment"
    - "Epoch-anchor over market-tz-local anchor: DST-immune and oracle-inert for 00:00-UTC daily grid"

key-files:
  created: []
  modified:
    - itrader/outils/time_parser.py
    - test/test_outils/test_time_parser.py

key-decisions:
  - "D-06/D-07: epoch-anchor (int(ts.timestamp()) % int(tf.total_seconds()) == 0) isolated in a single _aligned seam; market-tz-local anchoring REJECTED (would shift 00:00-UTC bars and break the oracle)"
  - "D-08: month disambiguation by case — uppercase 'M' is month (raises, not a fixed timedelta), lowercase 'm' is minutes; resolved BEFORE case-folding"
  - "to_timedelta guards None up front and raises on any unknown unit — never returns a silent None"

patterns-established:
  - "Replaceable timing seam: _aligned is the one place a future session/exchange-calendar anchor (stocks) plugs in without touching firing logic"

requirements-completed: [M2-10]

# Metrics
duration: 9min
completed: 2026-06-05
---

# Phase 03 Plan 04: time_parser Finalization (M2-10) Summary

**check_timeframe now gates on a single Unix-epoch `_aligned` seam (DST-immune, oracle-inert) and `to_timedelta` is case-insensitive with week support, a month-specific raise, and a None guard — dead buggy helpers deleted, behavioral oracle byte-exact unchanged.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-05T11:03Z
- **Completed:** 2026-06-05T11:12Z
- **Tasks:** 1 (TDD)
- **Files modified:** 2

## Accomplishments
- Replaced the midnight-of-day-UTC anchor in `check_timeframe` with a single replaceable `_aligned(ts, tf)` epoch seam (D-06/D-07). For the golden daily bars at 00:00 UTC the epoch and midnight anchors coincide, so the behavioral oracle stays byte-exact; the seam isolates the anchor so a future stock-calendar anchor plugs in without rewriting firing logic.
- Corrected `to_timedelta` (D-08): case-insensitive (`1H`/`1D`/`1W` parse like lowercase), added `w` (week), raises a clear month-specific `ValueError` on `M`, raises on any unknown unit (no silent `None`), and guards `timeframe is None` up front.
- Deleted the three dead buggy helpers (`format_timeframe`, `elapsed_time`, `round_timestamp_to_frequency`) after re-grepping the tree for importers (zero, as planned).
- Ran the behavioral oracle identity test immediately after the anchor change — byte-exact green (D-18 law preserved).

## Task Commits

Each task was committed atomically (TDD test → feat):

1. **Task 1 (RED): failing tests for _aligned seam + corrected to_timedelta** - `6bafc33` (test)
2. **Task 1 (GREEN): epoch-align check_timeframe + correct to_timedelta + delete dead helpers** - `24bf594` (feat)

_No REFACTOR commit — the GREEN implementation was already clean._

## Files Created/Modified
- `itrader/outils/time_parser.py` - Added `_aligned` epoch seam; `check_timeframe` delegates to it; rewrote `to_timedelta` (case-insensitive, week, month-raise, unknown-raise, None-guard); deleted `format_timeframe`/`elapsed_time`/`round_timestamp_to_frequency`.
- `test/test_outils/test_time_parser.py` - Promoted the Wave-0 stub into a full test module (16 tests): to_timedelta week/case/month/unknown/None coverage, daily/hourly/DST-boundary firing, the `_aligned` epoch-modulo seam, and dead-helper-deletion assertions. Removed the three skip-pending markers.

## Month/Minutes Disambiguation Note

The plan asked for case-insensitivity AND a month-specific raise on `M`. These conflict only for the `m`/`M` pair: lowercase `m` is minutes, uppercase `M` is month. Resolved by detecting the literal uppercase `M` (and an `mo` token) BEFORE case-folding to minutes — so `to_timedelta("1m")` → 1 minute while `to_timedelta("1M")` raises a month-specific error. Documented inline in the source.

## Verification

- `poetry run pytest test/test_outils/test_time_parser.py -x` → 16 passed
- `make test` → 317 passed, 6 skipped, 1 xfailed (skips/xfail are pre-existing pending-plan markers: 03-05 config, M2-08 storage, M2-09 timestamps, DEF-02-08-A numeric oracle)
- `make typecheck` → mypy --strict clean, no issues in 153 source files
- `test_oracle_behavioral_identity` → byte-exact green (D-18 preserved after the anchor change)
- `grep -n '_aligned'` → single seam at :127, `check_timeframe` delegates at :162
- dead helpers no longer defined; zero importers (re-verified)

## Deviations from Plan

None - plan executed exactly as written. The month/minutes case-disambiguation (handle `M` before lowercasing) is an implementation detail required to satisfy both stated behaviors, not a deviation.

## Known Stubs

None. The two previously-skipped `to_timedelta` stub assertions and the case-insensitivity stub are now live tests.

## Self-Check: PASSED
- `itrader/outils/time_parser.py` — FOUND
- `test/test_outils/test_time_parser.py` — FOUND
- Commit `6bafc33` (test) — FOUND
- Commit `24bf594` (feat) — FOUND
