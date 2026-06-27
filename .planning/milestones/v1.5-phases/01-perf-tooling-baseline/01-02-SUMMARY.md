---
phase: 01-perf-tooling-baseline
plan: 02
subsystem: infra
tags: [perf-baseline, w1-benchmark, json-freeze, soft-regression-guard, tool-04, gate-b]

# Dependency graph
requires:
  - phase: 01-01
    provides: "run_w1_benchmark --baseline-out / --check flags + perf-baseline / perf-w1 Makefile targets + D-01 baseline schema + soft regression guard (_check_regression)"
provides:
  - "perf/results/W1-BASELINE.json — the committed locked W1 reference (247.5s / 167.3MB) every later v1.5 phase's gate (b) diffs against (TOOL-04)"
  - "proven soft regression guard: prints Δ + exits 0 within ±5% noise; exits non-zero with PERF REGRESSION on a >+5% slowdown"
affects: [phase-02 order-storage-indexing, phase-03 pnl-accumulator, phase-04 hot-path, phase-05 incremental-indicators, phase-06 bar-feed]

# Tech tracking
tech-stack:
  added: []  # no new deps — exercises the 01-01 harness only
  patterns:
    - "single timed run freeze (D-03), not best-of-N"
    - "non-invasive guard proof: tamper the committed baseline ~20% lower, re-run --check, then git checkout to restore (no runner edit, no engine edit)"

key-files:
  created:
    - perf/results/W1-BASELINE.json
  modified: []

key-decisions:
  - "D-03 single-run freeze: W1-BASELINE.json frozen from one clean make perf-baseline run (247.5s / 167.3MB), not best-of-N"
  - "OQ-1/A1: oracle_provenance.final_equity committed as the STRING constant 46189.87730727451 (provenance stamp the engine was on-contract at freeze, never a W1-derived value)"
  - "Negative-test variant: lowered the COMMITTED baseline wall_clock_s ~20% (247.5->198.0) so the already-measured ~248s run reads as a >+5% slowdown — avoids a permanent runner change AND a needless extra ~240s run; reverted via git checkout"

patterns-established:
  - "gate (b) freeze ritual: confirm gate (a) green -> make perf-baseline (clean, no profiler) -> assert D-01 fields + trackability -> commit only the JSON"
  - "guard-proof ritual: positive make perf-w1 (Δ printed, exit 0) + injected-slowdown negative (tamper baseline, exit non-zero + PERF REGRESSION, git checkout restore, git diff --quiet)"

requirements-completed: [TOOL-04]

# Metrics
duration: ~18min (3 full ~240s benchmark runs dominate wall-clock)
completed: 2026-06-23
---

# Phase 01 Plan 02: W1 Baseline Freeze & Soft-Guard Proof Summary

**Re-froze the locked W1 reference `perf/results/W1-BASELINE.json` (247.5s / 167.3MB, 1578 fills / 659 closed) from a clean profiler-free `make perf-baseline` run with gate (a) green at freeze, then proved the soft regression guard both passes within noise and fails non-zero on an injected >+5% slowdown (TOOL-04 / gate (b)).**

## Performance

- **Duration:** ~18 min (dominated by three real ~240s timed W1 benchmark runs: the freeze, the positive guard run, the negative guard run)
- **Started:** 2026-06-23T17:51:29Z
- **Completed:** 2026-06-23T18:09:42Z
- **Tasks:** 2 (both auto, both passed)
- **Files created:** 1 (`perf/results/W1-BASELINE.json`)

## Accomplishments

- **Task 1 — Freeze + commit (TOOL-04 / D-01):** confirmed gate (a) green (134 / 46189.87730727451) BEFORE the freeze so the baseline is provably on-contract, then ran `make perf-baseline` (a single clean ~248s run, no profiler — D-03) to write `perf/results/W1-BASELINE.json`. The JSON carries all D-01 fields: `metric.wall_clock_s=247.5` (>0, real measured), `metric.peak_mem_mb=167.3`, `window.start_date="2026-04-23"` / `window.end_date="2026-06-23"`, `frozen_at="2026-06-23"`, `workload` (W1 / 5m / seed 42 / 1578 fills / 659 closed), and `oracle_provenance.final_equity="46189.87730727451"` as a STRING. Verified `git check-ignore` returns nothing (trackable; Pitfall 4) and committed ONLY the JSON (no scalene artifact).
- **Task 2 — Soft-guard proof (TOOL-04 / D-02 / D-04):**
  - **Positive path:** `make perf-w1` against the true baseline printed both deltas (`W1 wall_clock 248.0s Δ +0.2%` and `W1 peak_mem 167.3MB Δ +0.0% (watched)`) and exited 0 — a fresh same-machine run is within the ±5% noise band.
  - **Negative path:** lowered the committed baseline `wall_clock_s` ~20% (247.5→198.0), re-ran `--check` — the ~248–253s run read as `Δ +27.7%`, printed `PERF REGRESSION: +27.7% > band 5.0% — gate (b) guard FAILED`, and exited 1 (`make: *** [perf-w1] Error 1`). The guard catches a >+5% slowdown.
  - **Restore:** `git checkout -- perf/results/W1-BASELINE.json` → `git diff --quiet` passes; committed value back to 247.5, working tree clean — no tamper left behind (T-01-03 mitigated).
- Gate (a) green throughout — re-confirmed after Task 2 (3 passed, 134 / 46189.87730727451). No `itrader/` engine code touched anywhere in the plan.

## Task Commits

1. **Task 1: freeze W1-BASELINE.json locked reference** — `b56afdd` (feat)
2. **Task 2: soft-guard proof** — no code/file commit. The deliverable is the VERIFICATION (positive run exits 0, negative run exits non-zero + PERF REGRESSION, baseline restored clean). The injected-slowdown tamper was reverted via `git checkout`, so there is no net file change for Task 2 — by design (the task explicitly requires the baseline be left as the true frozen number).

## Files Created/Modified

- `perf/results/W1-BASELINE.json` — **created**; the committed locked W1 reference (schema_version 1, 247.5s / 167.3MB, pinned 2-month window, oracle provenance stamp). This is the artifact every later v1.5 optimization phase's gate (b) diffs against.

## Decisions Made

- **D-03 single-run freeze:** the baseline is one clean `make perf-baseline` run (247.5s rounded from a measured 247.525s), not a best-of-N — the runner's `_to_baseline_schema` rounds `wall_clock_s` to 1 dp.
- **OQ-1/A1 provenance:** `final_equity` is the byte-exact SMA_MACD oracle CONSTANT `46189.87730727451` serialized as a STRING (money discipline) — a "the engine was on-contract at freeze" stamp, NOT a W1-coverage-derived value (the W1 workload is not the SMA_MACD oracle).
- **Non-invasive negative-test variant:** chose to tamper the COMMITTED baseline JSON (lower wall_clock_s ~20%) rather than edit the runner or inject an artificial slowdown into the engine — this proves the guard's fail arm with no permanent runner change and reuses the already-measured current run as the "slowed" reading. Restored immediately via `git checkout`.

## Deviations from Plan

None — both tasks executed exactly as written. The freeze produced 247.5s vs the PERF-BASELINE-RESULTS.md reference 240.8s; this is expected same-machine timing variance (~3%), and the plan is explicit that "the actual machine value is authoritative" — the committed number is the live measured freeze, not the doc's reference literal. No auto-fixes, no architectural decisions.

## Issues Encountered

None. The per-bar `Signal validation failed: Quantity ... below minimum 0.001` log lines emitted during the W1 runs are EXPECTED benchmark behavior (coverage strategies C/D deliberately over-extend, producing per-bar admission-rejection warnings — documented in PERF-BASELINE-RESULTS.md §2 #4 / §4.4), not errors in this plan's work.

## Known Stubs

None.

## Threat Flags

None new. T-01-03 (tampering of the locked baseline) was the one in-scope threat and it was mitigated exactly as the threat register specifies: the freeze ran CLEAN (no profiler overhead corrupting the number) only after gate (a) was green, and the negative test's temporary tamper was reverted and verified by `git diff --quiet`.

## User Setup Required

None — all tooling (Make, Poetry, stdlib) already present; `.env` exists on the main working tree so `make` targets ran fine.

## Next Phase Readiness

- `perf/results/W1-BASELINE.json` is committed and locked. Phase 2 (Order-Storage Indexing, PERF-01) can now run `make perf-w1` to diff its optimization against this frozen 247.5s / 167.3MB reference — gate (b) "measurable ≥5% wall-clock improvement" (D-04) is the bar, and the guard is proven to enforce it.
- Gate (a) green; no engine code touched — Phase 1 stays held to gate (a) only.
- No blockers.

## Self-Check: PASSED

- `perf/results/W1-BASELINE.json` — FOUND (created, committed)
- Commit `b56afdd` — FOUND
- Gate (a) green — CONFIRMED (3 passed, 134 / 46189.87730727451)
- Baseline restored clean — CONFIRMED (`git diff --quiet` passes, value 247.5)

---
*Phase: 01-perf-tooling-baseline*
*Completed: 2026-06-23*
