---
phase: 06-bar-feed-window-copies-optional-slip-able
plan: 05
subsystem: testing
tags: [perf, benchmark, w2-sweep, gate-b, baseline, d-15, thermal-drift]

# Dependency graph
requires:
  - phase: 06-03
    provides: cleaned W2/W1 denominator (per-bar TIME EVENT log removed + harness de-timed)
  - phase: 06-04
    provides: monotonic int64 forward cursor in window() (the lever this plan certifies)
provides:
  - "Committed cleaned-engine cursor-on W2-BASELINE.json (13.61s @ 50 symbols) — the standing reference seeding Phase 5"
  - "Gate (b) verdict for PERF-06: +1.9% W2 at 50 symbols → D-15 ship-and-reframe (measurable W2 win + W1 non-regress), NOT the ≥10% bar"
affects: [phase-5-incremental-indicators]

# Tech tracking
tech-stack:
  added: []
  patterns: ["same-session cursorless→cursor A/B as the thermally-fair gate-(b) signal; absolute W1 wall-clock deferred when the box is warm"]

key-files:
  created:
    - perf/results/W2-BASELINE.json
  modified: []

key-decisions:
  - "D-15 invoked: cursor delivered +1.9% W2 at 50 symbols (< 10% honestly) → SHIP the cursor + cleanup anyway, record the actual %, reframe gate (b) → 'measurable W2 win + W1 non-regress'. No revert, no iterate."
  - "W1 absolute re-freeze DEFERRED: the re-freeze run read 259.1s vs prior 238.5s (+8.6%), but the same-session 1-symbol A/B is flat (cursorless 0.423s → cursor-on 0.425/0.445s) — the +8.6% is thermal drift (W1 ran last on the warmest box), not a cursor regression. Prior 238.5 W1 baseline kept; do NOT freeze the inflated number."

patterns-established:
  - "Gate-(b) thermal discipline: trust the same-session before/after A/B (back-to-back, same warmed box); distrust an absolute wall-clock vs a baseline frozen at a different time"

requirements-completed: [PERF-06]

# Metrics
duration: ~12min (cool-machine measurement: cursorless W2 baseline + cursor-on --check + W2 freeze + W1 run + oracle)
completed: 2026-06-24
---

# Phase 06 Plan 05: Gate (b) Re-Freeze + Verdict Summary

**PERF-06 cursor certified via D-15 ship-and-reframe: +1.9% W2 at 50 symbols on the cleaned engine (cursorless 14.31s → cursor-on 14.04s), gate (a) byte-exact green; W1 absolute re-freeze deferred (the +8.6% read is thermal drift, the 1-symbol A/B is flat).**

## Performance
- **Duration:** ~12 min (human-gated cool-machine measurement)
- **Completed:** 2026-06-24
- **Tasks:** 2 (Task 1 human-verify checkpoint; Task 2 commit + confirm)
- **Files modified:** 1 (perf/results/W2-BASELINE.json created)

## Gate (b) Verdict — D-15 ship-and-reframe

Measured on the **cleaned engine** (06-03 log-removal + harness de-time), cursor's win **isolated** from
the D-13 cleanup (BEFORE baseline captured on the cleaned-but-**cursorless** engine, AFTER `--check`
with the cursor on), same-session/same-machine on a cool box:

| n_symbols | cursorless (BEFORE) | cursor-on (AFTER, --check) | improvement |
|-----------|---------------------|----------------------------|-------------|
| 1         | 0.423 s             | 0.445 s                    | ~flat (sub-second noise) |
| 10        | 2.951 s             | 2.930 s                    | ~flat |
| **50**    | **14.310 s**        | **14.037 s**               | **+1.9%** |

- **Verdict:** `+1.9% < required 10.0%` → the `_check_w2` ≥10% bar (06-02 harness, `f51d7c6`) did **not**
  pass. Per **D-15** (locked fallback for the OPTIONAL/slip-able phase): **ship** the cursor + cleanup,
  **record +1.9%** as the locked result, **reframe gate (b) → "measurable W2 win + W1 non-regress."**
  No revert, no keep-iterating.
- **Why under the 13.2% the Scalene profile predicted:** line-level profilers over-attribute to
  `searchsorted`; in clean wall-clock the per-tick `searchsorted` over a ~3000-row index is nearly
  free. The cursor still removes that per-tick call and rides 06-01's read-only views — the +1.9% is a
  bonus on top of the look-ahead-safety value, exactly the D-15 framing.

## W1 non-regression — confirmed (thermal caveat)

- The W1 re-freeze run read **259.1 s vs the prior frozen 238.5 s (+8.6%)** — surfaced as a "regression"
  only because W1 ran **last**, after a back-to-back battery of W2 sweeps warmed the box (the v1.5
  thermal-drift lesson; memory `v15-perf-gateb-thermal-drift`).
- The **same-session 1-symbol A/B is flat** (cursorless 0.423 s → cursor-on 0.425/0.445 s). The cursor
  adds per-(ticker, alias) state with ~no benefit at 1 symbol and 06-03 *removes* a per-bar log — there
  is no mechanism for a real +8.6% single-symbol regression. **Conclusion: cursor is W1-non-regressive;
  the +8.6% is thermal.**
- **Action:** prior **238.5 s** W1 baseline **kept** (the inflated 259.1 s was NOT frozen). The absolute
  W1 re-freeze on the cleaned engine is **DEFERRED to a verified-cool isolated run** (see Pending Todo
  below) — consistent with Phase 3's deferred re-freeze discipline.

## Gate (a) — re-confirmed
- Byte-exact SMA_MACD oracle: **3 passed** (134 trades / `final_equity 46189.87730727451`).
- `mypy --strict`: **clean** (187 source files) — this plan touched no `itrader/` engine code.

## Task Commits
1. **Task 1: Cool-machine re-freeze + cursor-alone verdict** (human-verify checkpoint) — owner ran the
   measurement; verdict +1.9% W2 → D-15. Measurement is procedural (no code commit).
2. **Task 2: Commit cleaned-engine W2-BASELINE.json; confirm Gate (a)** — see the docs commit for this SUMMARY.

## Files Created/Modified
- `perf/results/W2-BASELINE.json` — cleaned-engine cursor-on 50-symbol reference (13.61 s, peak 214.58 MB);
  trackable (not gitignored), seeds Phase 5. (The recorded gate verdict is the `--check` +1.9%; the frozen
  reference is a fresh cursor-on freeze run.)
- `perf/results/W1-BASELINE.json` — **unchanged** (kept at the prior 238.5 s; the thermally-inflated 259.1 s
  was deliberately NOT frozen).

## Decisions Made
- Invoked D-15 (ship-and-reframe) on the honest +1.9% < 10% result — the planned path for this OPTIONAL phase.
- Deferred the absolute W1 re-freeze rather than committing a thermally-drifted number (thermal discipline).

## Deviations from Plan
- The plan's W1 re-freeze step (Task 1 step 6: `make perf-baseline` → update W1-BASELINE.json) was
  **deferred**, not executed, because the run was thermally contaminated. The plan's own how-to-verify
  step 7 prescribes exactly this: "If the box was thermally throttled … do NOT commit — defer and re-run
  on a cool machine." This is following the plan's contingency, not a scope deviation.
- `--check` hardcodes the baseline path to `perf/results/W2-BASELINE.json` (06-02 harness `f51d7c6`),
  so the cursorless BEFORE baseline was written to that canonical path (not a `-pre.json` sidecar); the
  cursor-on AFTER freeze then overwrote it. No transient sidecar to remove.

## Issues Encountered
- W1 thermal drift (+8.6% absolute) — diagnosed via the same-session 1-symbol A/B and dispositioned as
  measurement artifact, not a regression. Resolved by deferring the W1 re-freeze.

## Pending Todo (carried)
- **Re-freeze `W1-BASELINE.json` on a verified-cool isolated run.** Run `make perf-baseline` alone on a
  cool/quiet box (no preceding W2 battery) so the W1 number isn't thermally inflated, then commit. The
  current 238.5 s reference is the prior (pre-phase-6) freeze; the cleaned+cursor engine's honest W1
  number should replace it before the next phase diffs W1 against it.

## Next Phase Readiness
- PERF-06 closed via D-15. The cursor + cleanup are shipped, gate (a) byte-exact, the W2 reference is
  frozen and seeds Phase 5 (Incremental Indicators, W2-relevant). 06-02's deferred freeze/verify is
  absorbed and closed.
- One carried todo: the cool-machine W1 absolute re-freeze.

---
*Phase: 06-bar-feed-window-copies-optional-slip-able*
*Completed: 2026-06-24 (D-15 ship-and-reframe)*
