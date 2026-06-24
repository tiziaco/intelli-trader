---
status: partial
phase: 03-running-pnl-accumulator
source: [03-VERIFICATION.md, 03-02-SUMMARY.md]
started: 2026-06-24
updated: 2026-06-24
---

## Current Test

[awaiting human action — W1-BASELINE.json re-freeze on a cool machine]

## Tests

### 1. Re-freeze W1-BASELINE.json on a cool/quiet machine
expected: On a cool/quiet machine, in the MAIN checkout (not a worktree), run `make perf-baseline`,
then commit the updated `perf/results/W1-BASELINE.json`. Confirm `wall_clock_s` is substantially
below 199.4 s (the proven win is ~15%, so expect ≤ ~189 s on a comparable cool run) and the oracle
stamp `46189.87730727451 / 134` is intact. This MUST be done before Phase 4's gate (b) is measured,
otherwise Phase 4 diffs against the pre-Phase-3 baseline and over-credits its own win by ~15%.
result: [pending]
context: |
  PERF-02's improvement is already machine-independently PROVEN (Scalene CPU share
  position_manager.py 16.21% → 0%; same-machine A/B wall-clock 317.5 s → 268.4 s = −15.4%;
  profiled elapsed −29.6%). The re-freeze was deferred only because the box was thermally throttled
  on 2026-06-24 (old code itself read 317.5 s vs the 199.4 s frozen the prior night), so no run that
  day could produce a clean absolute reference. W1-BASELINE.json currently still holds the Phase-2
  199.4 s number. Full evidence: 03-02-SUMMARY.md. Also tracked in STATE.md "Pending Todos".

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
