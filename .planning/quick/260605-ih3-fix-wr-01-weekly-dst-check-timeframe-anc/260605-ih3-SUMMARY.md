---
phase: quick-260605-ih3
plan: 01
subsystem: outils/time_parser
tags: [WR-01, bugfix, timing, golden-oracle]
requires: []
provides:
  - "Midnight-relative (date-anchored, UTC) _aligned seam in time_parser"
  - "Weekly/7h/DST regression tests for check_timeframe"
affects:
  - itrader/outils/time_parser.py
  - tests/unit/outils/test_time_parser.py
tech-stack:
  added: []
  patterns:
    - "D-06 single replaceable alignment seam (_aligned), caller unchanged"
key-files:
  created: []
  modified:
    - itrader/outils/time_parser.py
    - tests/unit/outils/test_time_parser.py
  moved:
    - ".planning/todos/pending/weekly-anchor-time-parser.md -> .planning/todos/completed/weekly-anchor-time-parser.md"
decisions:
  - "WR-01 fixed via option (b): reproduce pre-refactor midnight-of-day anchor inside _aligned, not at the caller — preserves D-06 single-seam discipline"
  - "Daily 00:00 UTC golden path reduces to 0 % 86400 == 0 under the new anchor, so the numerical/behavioral oracle stays byte-exact"
metrics:
  duration: ~10 min
  completed: 2026-06-05
  tasks: 3
  files: 3
---

# Quick Task 260605-ih3: Fix WR-01 — Weekly/DST check_timeframe Anchor Summary

Restored the midnight-relative (date-anchored, UTC) alignment in the `_aligned` seam of
`itrader/outils/time_parser.py`, replacing the epoch-anchored
`int(ts.timestamp()) % int(tf.total_seconds()) == 0` that made weekly timeframes fire only on
Thursdays (epoch 1970-01-01 was a Thursday) and prevented `7h` from ever aligning to midnight.
The daily 00:00 UTC golden path stays byte-exact.

## What Was Built

- **`_aligned` rewritten (Task 1, TDD):** converts `ts` to UTC, zeroes sub-minute components,
  computes seconds-since-UTC-midnight, and fires when
  `seconds_since_midnight % int(tf.total_seconds()) == 0`. Anchor is midnight-of-day, so any unit
  fires on every midnight. `check_timeframe` body unchanged (`return _aligned(time, timeframe)`).
- **Docstring rewrite:** removed the Unix-epoch / epoch-Thursday CAVEAT; documents the
  midnight-relative behavior, that weekly/non-divisor units fire on every midnight, and that
  daily 00:00 UTC is preserved byte-exact.
- **New tests:** `test_check_timeframe_weekly_fires_on_any_midnight` (Monday/Wednesday midnight True,
  midday False), `test_check_timeframe_7h_aligns_to_midnight` (00:00 + 07:00 True, 06:00 False),
  `test_check_timeframe_dst_boundary_tz_aware` (Europe/Rome instants judged on the UTC grid).
- **Retargeted seam test:** `test_aligned_seam_epoch_modulo` → `test_aligned_seam_midnight_relative`,
  asserting midnight-relative arithmetic (daily True/midday False still hold).
- **Todo moved (Task 3):** `weekly-anchor-time-parser.md` git-mv'd from `pending/` to `completed/`.

## Verification

- `poetry run pytest tests/unit/outils/test_time_parser.py -q` — 19 passed.
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` — 2 passed
  (`test_oracle_behavioral_identity` AND `test_oracle_numeric_values` byte-exact).
- `poetry run pytest -q` — 349 passed (full suite green).
- `make typecheck` — mypy --strict clean, no issues in 148 source files.
- `git status` shows the todo renamed pending/ → completed/.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected DST tz-aware test assertion**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** The initially-written `test_check_timeframe_dst_boundary_tz_aware` asserted that
  `Europe/Rome` local `01:00` on 2020-03-29 should NOT fire daily. That instant is CET (UTC+1,
  before the 02:00→03:00 spring-forward) → 00:00 UTC, which IS on the midnight grid and correctly
  fires True. The assertion was wrong, not the implementation.
- **Fix:** Use local `03:00` CEST (UTC+2, after spring-forward) → 01:00 UTC as the genuinely
  off-grid non-firing instant, and local `01:00` CET → 00:00 UTC as an on-grid firing instant, each
  with a UTC-hour sanity assertion. This better expresses the test intent ("judged on the UTC grid").
- **Files modified:** tests/unit/outils/test_time_parser.py
- **Commit:** 243529f

## TDD Gate Compliance

- RED commit `79f7d6d` (`test(...)`): three behavior tests failing against the epoch seam.
- GREEN commit `243529f` (`fix(...)`): midnight-relative `_aligned`, all 19 tests pass.
- No REFACTOR commit needed.

## Commits

- `79f7d6d` test(quick-260605-ih3-01): add failing weekly/7h/DST midnight-anchor tests
- `243529f` fix(quick-260605-ih3-01): restore midnight-relative _aligned seam (WR-01)
- `85384c5` docs(quick-260605-ih3-01): mark weekly-anchor todo completed

## Self-Check: PASSED

- FOUND: itrader/outils/time_parser.py
- FOUND: tests/unit/outils/test_time_parser.py
- FOUND: .planning/todos/completed/weekly-anchor-time-parser.md
- ABSENT (expected): .planning/todos/pending/weekly-anchor-time-parser.md
- FOUND commit: 79f7d6d
- FOUND commit: 243529f
- FOUND commit: 85384c5
