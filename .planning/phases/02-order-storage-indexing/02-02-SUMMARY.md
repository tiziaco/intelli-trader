---
phase: 02-order-storage-indexing
plan: 02
subsystem: performance
tags: [benchmark, gate-b, perf-baseline, W1, PERF-01, re-freeze]

# Dependency graph
requires:
  - phase: 02-order-storage-indexing
    provides: "Index-backed InMemoryOrderStorage (02-01) that removed W1 hotspot #1 (~37% CPU); gate (a) byte-exact"
  - phase: 01-perf-tooling-baseline
    provides: "W1 benchmark harness + frozen W1-BASELINE.json (247.5s) that gate (b) diffs against"
provides:
  - "Gate (b) measurement: index-backed storage delivers a -19.4%..-21.6% W1 wall-clock improvement vs the frozen 247.5s baseline (>= 5% threshold met)"
  - "Re-frozen perf/results/W1-BASELINE.json (199.4s) as Phase 3's new locked reference"
  - "Preserved Phase-1 reference as perf/results/W1-BASELINE-phase1.json (247.5s) for auditability"
affects: [03-running-pnl-accumulator]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Human-gated measurement checkpoint: --check run reads Delta (read-only), re-freeze via --baseline-out only after the >=5% win is confirmed"
    - "Baseline archival: rename the prior locked reference (git mv) before overwriting so the metric history stays trackable (Pitfall 4 — never gitignore)"

key-files:
  created:
    - "perf/results/W1-BASELINE-phase1.json"
  modified:
    - "perf/results/W1-BASELINE.json"

key-decisions:
  - "Gate (b) PASSED: two clean runs measured 194.0s (-21.6%) and 199.4s (-19.4%) vs the 247.5s baseline; the ~2.7% spread is normal wall-clock variance, both far above the 5% threshold"
  - "Re-froze at 199.4s (the --baseline-out run) as the new locked W1-BASELINE.json; oracle stamp unchanged (134 / 46189.87730727451)"
  - "User-requested deviation: preserved the prior 247.5s baseline as W1-BASELINE-phase1.json (git mv) before re-freezing, rather than discarding it, for auditability"

patterns-established:
  - "Re-freeze-with-archive: git mv the old baseline to a -phaseN suffix, then make perf-baseline writes the fresh locked reference; commit both"
---

## What was built

This plan is the human-gated second half of Phase 2: it **measures** whether the
index-backed `InMemoryOrderStorage` from Plan 02-01 turns the removed ~37% CPU hotspot
into a real wall-clock win (gate (b)), then **re-freezes** the new faster run as the
locked reference Phase 3 will diff against.

No engine code changed — this plan runs the existing W1 benchmark harness and overwrites
a committed metric file.

## Gate (b) — PASSED

| Metric | Frozen baseline (Phase 1) | New (index-backed) | Delta |
|--------|---------------------------|--------------------|-------|
| Wall-clock (`--check` run) | 247.5s | 194.0s | **−21.6%** ✓ |
| Wall-clock (re-freeze run) | 247.5s | 199.4s | **−19.4%** ✓ |
| Peak memory | 167.3 MB | 169.8 MB | +1.5% (watched, no ceiling — D-11) |
| Total fills / closed | 1578 / 659 | 1578 / 659 | identical workload |
| Oracle stamp | 134 / 46189.87730727451 | 134 / 46189.87730727451 | unchanged |

The ≥5% improvement threshold (target ≤ ~235.1s) is met with large margin on both runs.
`make perf-w1` exited non-error (no >+5% regression); the human-read Delta confirmed the
improvement. The `Signal validation failed` log lines during the run are the normal
below-minimum-quantity order rejections that occur on every W1 run, not failures.

## Re-freeze

- `git mv perf/results/W1-BASELINE.json perf/results/W1-BASELINE-phase1.json` — preserved
  the Phase-1 247.5s reference (user request; trackable, not gitignored).
- `make perf-baseline` (→ `run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json`)
  wrote the new locked reference at **199.4s** with the oracle stamp intact and
  `green_at_freeze: true`.
- Both files verified tracked (`git check-ignore` returns nothing for either).
- Committed as `6cac08b perf(02-02): re-freeze W1 baseline 247.5s -> 199.4s`.

## Deviations

- **User-requested (during checkpoint approval):** keep the current baseline stored under a
  renamed file rather than letting `make perf-baseline` silently overwrite it. Archived the
  prior 247.5s reference as `perf/results/W1-BASELINE-phase1.json` before re-freezing. This
  adds one tracked file beyond the plan's declared `files_modified` (which listed only
  `W1-BASELINE.json`); it is purely additive and improves auditability.

## Verification

- Gate (b): `make perf-w1` printed Delta −21.6% vs the 247.5s frozen baseline (human-read). ✓
- Re-freeze: `git diff` / `cat` confirm new `wall_clock_s: 199.4` + intact oracle stamp
  (46189.87730727451 / 134). ✓
- File trackable: `git check-ignore perf/results/W1-BASELINE.json` returns nothing. ✓
- Gate (a) (oracle / mypy / determinism) was proven green in Plan 02-01 and independently
  re-confirmed at this commit (oracle 3/3 byte-exact).

## Self-Check: PASSED

- [x] Gate (b) ≥5% wall-clock improvement confirmed (−19.4% / −21.6% vs 247.5s)
- [x] W1-BASELINE.json re-frozen at 199.4s as Phase 3's locked reference
- [x] Oracle stamp unchanged (134 / 46189.87730727451)
- [x] Peak memory tracked, no material regression (D-11)
- [x] Prior baseline preserved (W1-BASELINE-phase1.json), both files trackable
- [x] Committed atomically (6cac08b)
