---
phase: 04-hot-path-discipline
plan: 03
subsystem: perf
tags: [performance, gate-b, benchmark, ab-attribution, perf-03, perf-04, thermal-drift, re-freeze]

# Dependency graph
requires:
  - phase: 04-hot-path-discipline
    provides: "PERF-03 logging gate (Plan 01) + PERF-04 type-hint memoization (Plan 02) — the changes whose win this plan measures"
  - phase: 01-perf-tooling-baseline
    provides: "gate (b) definition (D-04, >=5% wall-clock single timed run) + the W1 benchmark harness (make perf-w1/perf-baseline/perf-profile)"
  - phase: 03-running-pnl-accumulator
    provides: "the same-machine A/B + Scalene CPU-share thermal-drift precedent; the W1-BASELINE.json re-freeze that was DEFERRED (baseline still Phase-2)"
provides:
  - "04-PERF-ATTRIBUTION.md — same-machine 2x2 A/B (old pre-PERF-03/04 vs new), mean -7.8% / best -9.8% wall-clock, peak mem -0.22%, attributed to PERF-03 + PERF-04"
  - "Gate (b) PASS verdict on substance (A/B), explicitly NOT the stale frozen-baseline compare (W1-BASELINE.json still holds Phase-2 199.4s)"
  - "PAUSED at the blocking owner sign-off checkpoint (Task 2) — W1-BASELINE.json re-freeze NOT yet executed"
affects: [phase-05-incremental-indicators, perf-gate-b-refreeze, n4-live-trading-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Same-machine 2x2 A/B (revert touched files to pre-change commit -> benchmark -> restore HEAD -> benchmark, back-to-back) as the drift-immune gate-(b) attribution when the frozen absolute baseline is stale/contended"
    - "Pass ITRADER_LOG_LEVEL=ERROR + PYTHONPATH=$PWD explicitly to the perf runner inside a worktree (no .env, no .venv there) instead of the make target"

key-files:
  created:
    - .planning/phases/04-hot-path-discipline/04-PERF-ATTRIBUTION.md
  modified: []
  deferred:
    - perf/results/W1-BASELINE.json   # re-freeze gated on blocking owner sign-off (Task 2)

key-decisions:
  - "Gate (b) judged on the same-machine A/B (mean -7.8%, best -9.8%), NOT the frozen compare — W1-BASELINE.json still holds the stale Phase-2 199.4s (Phase-3 re-freeze was deferred), so a frozen compare would over-credit by ~15%"
  - "No Scalene re-run: optional per the plan, and a fresh ~16-min --cpu-only profile would further heat an already-contended box; the 2x2 non-overlapping A/B + the visible OLD-tree error-log demotion are the drift-immune signals relied on"
  - "Re-freeze held for the blocking owner sign-off (T-04-06): the executor will NOT auto-freeze the locked perf reference; the machine is un-throttled but under foreground contention, so the owner decides freeze-now-vs-defer-to-quiet-machine"

patterns-established:
  - "When the committed perf baseline is known-stale (a prior re-freeze was deferred), attribute gate (b) by a same-machine old-vs-new A/B and treat the frozen-number compare as invalid — never silently trust the stale absolute"

requirements-completed: []  # PERF-03 (Plan 01) + PERF-04 (Plan 02) close at re-freeze; this plan PAUSED before the freeze — leave unmarked until owner sign-off

# Metrics
duration: ~22min (4x W1 runs A/B + oracle gate)
completed: 2026-06-24
---

# Phase 4 Plan 03: Gate (b) A/B Attribution + W1 Re-Freeze Summary

**Same-machine 2x2 A/B proves the PERF-03 + PERF-04 hot-path changes deliver a real, attributed
wall-clock win of -7.8% (mean) / -9.8% (best-of-2), well above the >=5% gate (b) bar, with peak
memory also down (-0.22%) and the oracle byte-exact — but the W1-BASELINE.json re-freeze is HELD
at the plan's blocking owner sign-off checkpoint (the committed baseline is still the stale
Phase-2 199.4s, and the box is un-throttled but under foreground contention).**

## Performance

- **Duration:** ~22 min active (4 full W1 runs for the 2x2 A/B + the oracle gate)
- **Completed:** 2026-06-24
- **Tasks:** 1 of 2 complete; Task 2 PAUSED at a blocking human-verify checkpoint
- **Files modified:** 0 source; 1 doc created (`04-PERF-ATTRIBUTION.md`)

## Accomplishments

- **Task 1 — same-machine A/B attribution (gate b PASS):** reverted the 6 PERF-03/04 files to the
  pre-change commit `1240617`, ran W1 on old vs new back-to-back (2x2), restored HEAD clean. NEW is
  faster in every pairing; mean **-7.8%**, best **-9.8%**, peak mem **-0.22%**, topology byte-identical
  (1578 fills / 659 closed). Recorded in `04-PERF-ATTRIBUTION.md`.
- **Baseline-provenance check:** confirmed `W1-BASELINE.json` still holds the **stale Phase-2 199.4s**
  (the Phase-3 re-freeze was deferred for thermal reasons), so the verdict comes from the A/B, never
  the frozen compare — avoiding the ~15% over-credit the plan's CRITICAL PRECONDITION warns about.
- **Machine state recorded honestly:** NOT thermally throttled (`pmset -g therm` clean, 81.8% idle at
  sample) but under foreground contention (load ~4; Safari/Slack/another Python live). The A/B is
  drift-immune to that contention because both legs run back-to-back in the same window.
- **Attribution to PERF-03 + PERF-04 (not noise):** the OLD tree visibly emitted the per-bar
  admission-rejection lines at `error` (the D-01 demotion target — gated out on NEW at the ERROR
  benchmark level); benchmark confirmed at `ITRADER_LOG_LEVEL=ERROR`.
- **Gate (a) green at measurement:** `tests/integration/test_backtest_oracle.py` 3 passed
  (134 / 46189.87730727451).

## A/B Numbers (same machine, back-to-back, ERROR level)

| Tree | Run 1 | Run 2 | Mean | peak_mem | fills/closed |
|------|------:|------:|-----:|---------:|:------------:|
| OLD (pre-PERF-03/04, `1240617`) | 269.4s | 264.4s | 266.9s | 163.04 MB | 1578 / 659 |
| NEW (PERF-03 + PERF-04, HEAD)   | 253.8s | 238.6s | 246.2s | 162.68 MB | 1578 / 659 |

mean Δ **-7.8%** · best-vs-best **-9.8%** · conservative floor (worst-NEW/best-OLD) -4.0% · peak mem -0.22%.

## Task Commits

1. **Task 1: same-machine A/B attribution (gate b)** - `e35dfd9` (docs)
2. **Task 2: re-freeze W1-BASELINE.json** - NOT EXECUTED (blocking owner sign-off checkpoint)

## Files Created/Modified

- `.planning/phases/04-hot-path-discipline/04-PERF-ATTRIBUTION.md` - machine-state + baseline-provenance
  check, the 2x2 A/B numbers + deltas, attribution to PERF-03/PERF-04, gate (a) green, re-freeze-gate note.

## Decisions Made

- **Gate (b) on the A/B, not the frozen compare** — the committed baseline is the stale Phase-2 199.4s
  (Phase-3 re-freeze deferred), so the frozen compare is invalid and would over-credit by ~15%.
- **No Scalene re-run** — optional per the plan; a fresh profile would heat the contended box, and the
  non-overlapping 2x2 A/B + visible error-log demotion are sufficient drift-immune evidence.
- **Re-freeze held for blocking owner sign-off** — re-freezing the locked perf reference is
  tampering-sensitive (T-04-06) and the box is contended; the owner decides freeze-now vs defer-to-quiet.

## Deviations from Plan

None - plan executed as written through Task 1. Task 2 is a planned blocking checkpoint and is correctly
paused for owner sign-off (the plan's `resume-signal` requires "approved"). One mechanical adaptation,
not a deviation: the worktree has no `.env`/`.venv`, so the perf runner was invoked directly with
`ITRADER_LOG_LEVEL=ERROR PYTHONPATH="$PWD" poetry run python -m perf.runners.run_w1_benchmark` instead of
`make perf-w1`/`make perf-baseline` (the make targets `include .env` and abort in a worktree). This
reproduces the exact gated invocation (same module, same ERROR level, same pinned window).

## Issues Encountered

- **Worktree has no `.env` and no `.venv`** — `make perf-*` aborts on missing `.env`, and python/pytest
  resolve against the main checkout's editable install. Resolved per the known gotchas: pass
  `ITRADER_LOG_LEVEL=ERROR` explicitly and prepend `PYTHONPATH="$PWD"` to every invocation.
- **Foreground contention (not thermal throttle)** — absolute W1 runs hot (~240-270s) vs the cool-night
  199.4s frozen number because of live foreground apps; handled by the drift-immune same-machine A/B
  rather than trusting absolutes.

## User Setup Required

**Blocking owner action — re-freeze sign-off (Task 2).** See the checkpoint below / `04-PERF-ATTRIBUTION.md`.
The owner must either approve the re-freeze (executor then runs one clean `make perf-baseline`, writes the
new `wall_clock_s`+`peak_mem_mb` into `W1-BASELINE.json` preserving schema and the STRING
`oracle_provenance.final_equity` 46189.87730727451, confirms `make perf-w1` soft guard exits 0, commits)
or defer the freeze to a confirmed-quiet machine to avoid baking contention noise into the Phase-5 reference.

## Next Phase Readiness

- **Gate (b) substance is proven** (A/B mean -7.8% / best -9.8%, peak mem -0.22%, attributed to
  PERF-03 + PERF-04, oracle byte-exact). Phase 5 can plan against the Phase-3 hotspot map
  (indicators/catalog 16.28% is the PERF-05 target).
- **BLOCKER (hard):** `W1-BASELINE.json` is NOT yet re-frozen — it still holds the stale Phase-2 199.4s.
  The re-freeze is the milestone moment the locked reference advances; it requires owner sign-off (Task 2).
  Until then PERF-03/PERF-04 are NOT marked requirements-complete and Phase 4 gate (b) is not closed.
- **STATE.md / ROADMAP.md NOT modified** (worktree mode — orchestrator owns those writes).

## Self-Check: PASSED

- `04-PERF-ATTRIBUTION.md` exists on disk and contains "delta"/Δ rows; Task 1 commit `e35dfd9` present in git log.
- Working tree restored clean after the A/B (isEnabledFor=7, _declared_hints=6, `git status` empty);
  no source files modified.

---
*Phase: 04-hot-path-discipline*
*Completed (Task 1; Task 2 paused at blocking checkpoint): 2026-06-24*
