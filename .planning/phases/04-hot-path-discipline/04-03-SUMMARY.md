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
    provides: "the same-machine A/B + Scalene CPU-share thermal-drift precedent; the W1-BASELINE.json re-freeze that was DEFERRED (baseline was stale Phase-2 until this plan)"
provides:
  - "04-PERF-ATTRIBUTION.md — same-machine 2x2 A/B (old pre-PERF-03/04 vs new), mean -7.8% / best -9.8% wall-clock, peak mem -0.22%, attributed to PERF-03 + PERF-04 + the re-freeze record"
  - "Gate (b) PASS on substance (A/B), not the (formerly stale) frozen compare"
  - "perf/results/W1-BASELINE.json RE-FROZEN as the Phase-4 reference: wall_clock_s 238.5, peak_mem_mb 162.7 (was Phase-2 199.4 / 169.8), frozen on a CONTENDED machine per owner sign-off"
affects: [phase-05-incremental-indicators, perf-gate-b-refreeze, n4-live-trading-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Same-machine 2x2 A/B (revert touched files to pre-change commit -> benchmark -> restore HEAD -> benchmark, back-to-back) as the drift-immune gate-(b) attribution when the frozen absolute baseline is stale/contended"
    - "Pass ITRADER_LOG_LEVEL=ERROR + PYTHONPATH=$PWD explicitly to the perf runner inside a worktree (no .env, no .venv there) instead of the make target — same module/flags/window"

key-files:
  created:
    - .planning/phases/04-hot-path-discipline/04-PERF-ATTRIBUTION.md
  modified:
    - perf/results/W1-BASELINE.json

key-decisions:
  - "Gate (b) judged on the same-machine A/B (mean -7.8%, best -9.8%), NOT the frozen compare — the committed baseline was stale Phase-2 199.4s (Phase-3 re-freeze deferred), so a frozen compare would over-credit by ~15%"
  - "No Scalene re-run: optional per the plan, and a fresh ~16-min profile would heat an already-contended box; the 2x2 non-overlapping A/B + the visible OLD-tree error-log demotion are the drift-immune signals relied on"
  - "Re-freeze EXECUTED under owner sign-off on a CONTENDED machine (238.5s, intentionally slower than the cool-night 199.4s) with the contention provenance recorded — the absolute is owner-accepted, the gate-(b) verdict rests on the A/B not this number"

patterns-established:
  - "When the committed perf baseline is known-stale (a prior re-freeze was deferred), attribute gate (b) by a same-machine old-vs-new A/B and treat the frozen-number compare as invalid — never silently trust the stale absolute"
  - "Record machine-state provenance directly in the re-frozen reference's audit trail when freezing on a non-ideal (contended) machine, so the inflated absolute is not later misread as a regression/win"

requirements-completed: [PERF-03, PERF-04]

# Metrics
duration: ~32min
completed: 2026-06-24
---

# Phase 4 Plan 03: Gate (b) A/B Attribution + W1 Re-Freeze Summary

**Same-machine 2x2 A/B proves the PERF-03 + PERF-04 hot-path changes deliver a real, attributed
wall-clock win of -7.8% (mean) / -9.8% (best-of-2), well above the >=5% gate (b) bar, with peak
memory also down; `W1-BASELINE.json` is RE-FROZEN under owner sign-off as the new Phase-4 reference
(238.5s / 162.7 MB, replacing the stale Phase-2 199.4s) — frozen on a contended machine by explicit
owner decision with that provenance on record, oracle byte-exact throughout.**

## Performance

- **Duration:** ~32 min active (4 full W1 runs for the 2x2 A/B + 1 freeze run + 1 guard run + oracle/mypy)
- **Completed:** 2026-06-24
- **Tasks:** 2/2 complete (Task 2 was a blocking human-verify checkpoint, owner-approved)
- **Files modified:** 1 doc created + 1 perf reference re-frozen; 0 source files

## Accomplishments

- **Task 1 — same-machine A/B attribution (gate b PASS):** reverted the 6 PERF-03/04 files to the
  pre-change commit `1240617`, ran W1 on old vs new back-to-back (2x2), restored HEAD clean. NEW is
  faster in every pairing; mean **-7.8%**, best **-9.8%**, peak mem **-0.22%**, topology byte-identical
  (1578 fills / 659 closed). Recorded in `04-PERF-ATTRIBUTION.md`.
- **Baseline-provenance check:** confirmed the committed `W1-BASELINE.json` was the **stale Phase-2 199.4s**
  (Phase-3 re-freeze had been deferred), so the verdict came from the A/B, never the frozen compare —
  avoiding the ~15% over-credit the plan's CRITICAL PRECONDITION warns about.
- **Attribution to PERF-03 + PERF-04 (not noise):** the OLD tree visibly emitted the per-bar
  admission-rejection lines at `error` (the D-01 demotion target — gated out on NEW at the ERROR
  benchmark level); benchmark confirmed at `ITRADER_LOG_LEVEL=ERROR`.
- **Task 2 — re-freeze under owner sign-off:** gate (a) re-confirmed green (oracle double-run byte-identical
  134 / 46189.87730727451, mypy --strict clean), ran one clean freeze (238.5s / 162.7 MB), wrote the new
  metric into `W1-BASELINE.json` preserving schema (frozen_at 2026-06-24; `oracle_provenance.final_equity`
  kept as the STRING constant 46189.87730727451), confirmed the soft guard `--check` exits 0 (234.9s,
  -1.5% vs the new baseline), kept the file trackable, committed.
- **Contended-machine provenance recorded:** the freeze (238.5s) is intentionally slower than the
  cool-night 199.4s; per owner decision the number reflects today's contended machine, documented in
  both the attribution doc and the commit so it is never misread as a regression or a fake Phase-5 win.

## A/B Numbers (same machine, back-to-back, ERROR level)

| Tree | Run 1 | Run 2 | Mean | peak_mem | fills/closed |
|------|------:|------:|-----:|---------:|:------------:|
| OLD (pre-PERF-03/04, `1240617`) | 269.4s | 264.4s | 266.9s | 163.04 MB | 1578 / 659 |
| NEW (PERF-03 + PERF-04, HEAD)   | 253.8s | 238.6s | 246.2s | 162.68 MB | 1578 / 659 |

mean Δ **-7.8%** · best-vs-best **-9.8%** · conservative floor (worst-NEW/best-OLD) -4.0% · peak mem -0.22%.

## Re-Freeze (W1-BASELINE.json)

| Field | Before (Phase-2) | After (Phase-4) |
|-------|------------------|-----------------|
| frozen_at | 2026-06-23 | 2026-06-24 |
| metric.wall_clock_s | 199.4 | **238.5** (contended machine, owner-accepted) |
| metric.peak_mem_mb | 169.8 | **162.7** |
| oracle_provenance.final_equity | "46189.87730727451" | "46189.87730727451" (UNCHANGED string) |

Soft guard `--check` after freeze: 234.9s, **Δ -1.5%**, exit 0.

## Task Commits

1. **Task 1: same-machine A/B attribution (gate b)** - `e35dfd9` (docs)
2. **Plan SUMMARY (paused-state checkpoint snapshot)** - `672f77a` (docs)
3. **Task 2: re-freeze W1-BASELINE.json as the Phase-4 reference** - `01cb764` (perf)

## Files Created/Modified

- `.planning/phases/04-hot-path-discipline/04-PERF-ATTRIBUTION.md` - machine-state + baseline-provenance
  check, the 2x2 A/B numbers + deltas, attribution to PERF-03/PERF-04, gate (a) green, and the §7 re-freeze
  record with the contended-machine provenance.
- `perf/results/W1-BASELINE.json` - re-frozen Phase-4 reference (238.5s / 162.7 MB); schema + window + seed +
  STRING oracle constant preserved.

## Decisions Made

- **Gate (b) on the A/B, not the frozen compare** — the committed baseline was the stale Phase-2 199.4s.
- **No Scalene re-run** — non-overlapping 2x2 A/B + visible error-log demotion are sufficient drift-immune evidence.
- **Re-freeze executed on a contended machine under owner sign-off**, with the inflated-absolute provenance recorded.

## Deviations from Plan

None - plan executed as written. One mechanical adaptation, not a deviation: the worktree has no
`.env`/`.venv`, so the perf runner was invoked directly with
`ITRADER_LOG_LEVEL=ERROR PYTHONPATH="$PWD" poetry run python -m perf.runners.run_w1_benchmark [--baseline-out|--check]`
instead of `make perf-baseline`/`make perf-w1` (the make targets `include .env` and abort in a worktree).
This reproduces the exact gated invocation (same module, same flags, same ERROR level, same pinned window).

## Issues Encountered

- **Worktree has no `.env` and no `.venv`** — `make perf-*` aborts on missing `.env`, and python/pytest
  resolve against the main checkout's editable install. Resolved per the known gotchas: pass
  `ITRADER_LOG_LEVEL=ERROR` explicitly and prepend `PYTHONPATH="$PWD"` to every invocation.
- **Foreground contention (not thermal throttle)** — absolute W1 runs hot (~238-270s) vs the cool-night
  199.4s because of live foreground apps; handled by the drift-immune same-machine A/B for the verdict,
  and the contended freeze absolute is owner-accepted with provenance recorded.

## User Setup Required

None outstanding for this plan — the blocking owner sign-off (Task 2) was provided and the re-freeze is
committed. NOTE for the milestone owner: the re-frozen 238.5s is a contended-machine number; if a cleaner
Phase-5 reference is wanted, run `make perf-baseline` on a confirmed-quiet machine and re-commit
(the gate-(b) A/B attribution stands regardless, being independent of the absolute).

## Next Phase Readiness

- **Gate (b) CLOSED** for Phase 4: A/B mean -7.8% / best -9.8%, peak mem -0.22%, attributed to
  PERF-03 + PERF-04, oracle byte-exact, and `W1-BASELINE.json` re-frozen as the new locked reference.
- **PERF-03 + PERF-04 requirements complete** (the freeze is the milestone moment they close).
- Phase 5 can plan against the Phase-3 hotspot map (indicators/catalog 16.28% is the PERF-05 target);
  the new baseline (238.5s contended) is the soft regression reference — read deltas as A/B, not absolutes.
- **STATE.md / ROADMAP.md NOT modified** (worktree mode — orchestrator owns those writes).

## Self-Check: PASSED

- `04-PERF-ATTRIBUTION.md` exists with the A/B deltas + the §7 re-freeze record; `04-03-SUMMARY.md` exists.
- `perf/results/W1-BASELINE.json` re-frozen: wall_clock_s 238.5, peak_mem_mb 162.7, final_equity string
  "46189.87730727451" intact, trackable (not gitignored).
- Commits present in git log: `e35dfd9` (Task 1), `672f77a` (paused snapshot), `01cb764` (re-freeze).
- Working tree restored clean after the A/B (isEnabledFor=7, _declared_hints=6); no source files modified.

---
*Phase: 04-hot-path-discipline*
*Completed: 2026-06-24*
