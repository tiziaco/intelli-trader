---
phase: 06-bar-feed-window-copies-optional-slip-able
plan: 02
subsystem: testing
tags: [perf, benchmark, w2-sweep, gate-b, makefile]

# Dependency graph
requires:
  - phase: 06-01
    provides: read-only view + alias memo in BacktestBarFeed.window() (the engine change the W2 after-measurement is meant to certify)
provides:
  - "W2 gate-(b) mechanization: run_w2_sweep.py --baseline-out/--check (50-symbol >=10% inverted guard + WR-02 zero-baseline soft guard)"
  - "Makefile perf-w2 --check wiring + perf-w2-baseline freeze target"
affects: [06-03, 06-04, 06-05]

# Tech tracking
tech-stack:
  added: []
  patterns: ["W1-mirrored baseline-out/--check runner pattern, guard sense INVERTED for a win-required gate"]

key-files:
  created: []
  modified:
    - perf/runners/run_w2_sweep.py
    - Makefile

key-decisions:
  - "Task 1 (W2 gate harness) complete and committed (f51d7c6); reusable as-is per CONTEXT D-05"
  - "Tasks 2/3 (before/after measurement + W2/W1 re-freeze) SUPERSEDED by 06-05 (D-14/D-15) after the 2026-06-24 cursor pivot"

patterns-established:
  - "Inverted-guard perf gate: _check_w2 returns 0 iff 50-symbol improvement >= min_improvement_pct (10.0), mirroring run_w1_benchmark but requiring a win"

requirements-completed: []  # PERF-06 verdict is owned by 06-05 (the gate-(b) re-freeze + verdict plan); this plan only built the harness

# Metrics
duration: ~5min (Task 1 only; Tasks 2/3 superseded, not executed)
completed: 2026-06-24
---

# Phase 06 Plan 02: W2 Gate-(b) Harness Summary

**W2 gate-(b) mechanization (`run_w2_sweep --baseline-out/--check`, 50-symbol ≥10% inverted guard) landed as Task 1; the measurement + re-freeze tasks were superseded by 06-05 in the 2026-06-24 cursor pivot.**

## Closeout Status

This plan is closed out as **partially executed + superseded**, not re-run:

- **Task 1 — DONE (committed):** Added `--baseline-out PATH` / `--check` to `run_w2_sweep.py`
  (`_to_w2_baseline_schema`, `_write_w2_baseline`, `_check_w2` with `min_improvement_pct=10.0`, the
  WR-02 non-positive-baseline soft guard returning 1, and the combined-flag warning), plus the
  Makefile `perf-w2 --check` wiring and the `perf-w2-baseline` freeze target on `.PHONY`. Committed in
  `f51d7c6` (`feat(06-02): mechanize W2 gate (b) — run_w2_sweep --baseline-out/--check + Makefile
  wiring`).
- **Task 2 (blocking human-verify) + Task 3 (commit baselines) — SUPERSEDED.** When this plan paused
  at its checkpoint (`f5ac6c2`), the Gate (b) A/B + Scalene profile showed 06-01's view/alias gave
  **~0% W2** — there was no ≥10% win to certify. The phase then **pivoted** (06-CONTEXT.md, D-10–D-16):
  the real lever became the monotonic incremental cursor (06-04), with a denominator cleanup prep
  (06-03) and a single gate-(b) **re-freeze + verdict** step (06-05, D-14/D-15). Per **D-05 (amended)**:
  *"The 06-02 harness (`run_w2_sweep --baseline-out/--check`, commit `f51d7c6`) is reusable as-is — it
  simply has no ≥10% win to certify until the cursor lands."* The before/after measurement and the
  W1/W2 re-freeze that were Tasks 2/3 are now owned by **06-05** on the cleaned engine.

## Task Commits

1. **Task 1: Add --baseline-out/--check to run_w2_sweep.py + Makefile wiring** — `f51d7c6` (feat)
   **Plan partial-progress marker:** `f5ac6c2` (docs)

## Files Created/Modified
- `perf/runners/run_w2_sweep.py` — `--baseline-out`/`--check` W2 gate-(b) flags (50-symbol ≥10%
  inverted guard + WR-02 soft guard)
- `Makefile` — `perf-w2 --check` wiring + `perf-w2-baseline` freeze target

## Decisions Made
- Closed out as superseded rather than re-executed: re-running would duplicate the committed harness
  and re-enter a blocking checkpoint with nothing to certify (the cursor lands in 06-04; the verdict
  is 06-05). Confirmed with the owner before writing this SUMMARY.

## Deviations from Plan
The plan's own Tasks 2/3 were not executed under this plan — they were re-scoped into 06-05 by the
post-profile pivot (D-13/D-14/D-15). This is a planning-level re-scope, not an in-plan deviation.

## Issues Encountered
None — the pivot is documented in 06-CONTEXT.md and 06-PROFILE-FINDINGS.md.

## Next Phase Readiness
- The W2 `--check`/`--baseline-out` harness is in place and reusable by 06-03 (cleanup) and 06-05
  (gate verdict). PERF-06's gate-(b) certification proceeds through 06-03 → 06-04 → 06-05.

---
*Phase: 06-bar-feed-window-copies-optional-slip-able*
*Completed: 2026-06-24 (closed out as superseded)*
