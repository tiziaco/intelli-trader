---
phase: 01-perf-tooling-baseline
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - perf/runners/run_w1_benchmark.py
  - perf/runners/run_w2_sweep.py
  - Makefile
  - .gitignore
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Tooling-only phase: a performance-measurement harness plus build/ignore wiring. No
`itrader/` engine code was touched, so the review is scoped to the perf-harness diff
vs base `12355c1`.

The phase's load-bearing requirements all verified clean:

- **`_check_regression` soft-guard is correct.** The fail condition is `wall_d > band_pct`
  with no `abs()` — an improvement (negative delta) returns 0, only a real `>+5%` slowdown
  returns 1. Peak memory is reported but never fails the gate. Matches the D-02/D-04 contract.
- **`_to_baseline_schema` money discipline holds.** `final_equity` is the string constant
  `"46189.87730727451"`, never a JSON float. The other numeric metrics are correctly rounded
  perf measurements, not money.
- **`perf-w1` is profiler-free.** The gated target runs `run_w1_benchmark --check` with no
  scalene wrapping; profiling is isolated in `perf-profile` (two-step run→view).
- **`.gitignore` ignore lines are narrow.** `perf/results/scalene-*.json` ignores the profile
  artifact but does NOT sweep the committed `W1-BASELINE.json` (confirmed via `git check-ignore`
  and `git ls-files`: baseline is tracked, scalene json is not).
- **`--json` argparse wiring** in both runners is correct.

Two WARNING-level build/robustness defects remain (a missing `.PHONY` entry and an
unguarded division in the soft guard), plus two INFO items.

## Warnings

### WR-01: `perf-view` target is missing from `.PHONY`

**File:** `Makefile:6` (declaration) / `Makefile:129` (target)
**Issue:** The `.PHONY` line declares `perf-w1 perf-w2 perf-baseline perf-profile` but the
phase also added a fifth perf target, `perf-view` (line 129), which is NOT listed. `perf-view`
produces no file named `perf-view`, so it is a phony recipe. If a file or directory named
`perf-view` ever appears at the repo root, `make perf-view` will report "Nothing to be done"
and silently skip the viewer — the exact class of footgun `.PHONY` exists to prevent. Every
other recipe in this file that produces no same-named file is declared phony; this one breaks
that invariant.
**Fix:**
```makefile
.PHONY: init-env clean test test-unit test-integration test-e2e test-cov backtest normalize-data precommit typecheck perf-w1 perf-w2 perf-baseline perf-profile perf-view
```

### WR-02: `_check_regression` divides by the baseline with no zero-guard — crashes instead of soft-failing

**File:** `perf/runners/run_w1_benchmark.py:203-204`
**Issue:** The deltas are computed as `(wall - base_wall) / base_wall * 100.0` and
`(mem - base_mem) / base_mem * 100.0`. If `base_wall` or `base_mem` read from the baseline
JSON is `0` (a hand-edited, truncated, or freshly-stubbed `W1-BASELINE.json`), this raises an
uncaught `ZeroDivisionError` and aborts the run with a traceback. The function is documented
as a *soft* guard whose worst case is `return 1`; a crash on a malformed baseline violates that
contract and is harder to diagnose than a clear message. A current well-formed baseline rounds
to `247.5` / `167.3` so this does not fire today, but the guard should degrade gracefully.
**Fix:**
```python
    base_wall = base["metric"]["wall_clock_s"]
    base_mem = base["metric"]["peak_mem_mb"]
    if base_wall <= 0:
        print(f"PERF GUARD: baseline wall_clock_s is {base_wall} — refusing to "
              "compute a delta against a zero/invalid baseline")
        return 1
    ...
    mem_d = (mem - base_mem) / base_mem * 100.0 if base_mem else float("nan")
```

## Info

### IN-01: `--baseline-out` and `--check` together compare a run against itself

**File:** `perf/runners/run_w1_benchmark.py:225-228`
**Issue:** In `main()`, when both `--baseline-out perf/results/W1-BASELINE.json` and `--check`
are passed, the baseline is written first (line 226), then `_check_regression` re-reads that
same path (line 228). The delta is therefore always ~0% and the guard can never fail — a
silently meaningless self-comparison. The Makefile never combines the two flags, so this is
latent, not active. Consider making the two flags mutually exclusive (an argparse mutually
exclusive group) or skipping the `--check` step when `--baseline-out` targets the same path.
**Fix:** Add `parser.add_mutually_exclusive_group()` for `--check` vs `--baseline-out`, or
emit a warning when both are supplied.

### IN-02: `perf-profile` runs the viewer unconditionally even if the scalene profiling run failed

**File:** `Makefile:121-126`
**Issue:** The two commands in `perf-profile` sit on separate recipe lines, so `make` will
abort the recipe if `scalene run` exits non-zero — that part is fine. But if `scalene run`
exits `0` while writing an empty/partial `perf/results/scalene-w1.json` (e.g. interrupted
mid-write), the immediately-following `scalene view` is invoked on a stale/garbage file with no
freshness check. This is a manual-review convenience target, not a gate, so impact is low.
Optionally gate the view step on a non-empty output, e.g. `[ -s perf/results/scalene-w1.json ]`.
**Fix:** Prefix the view step with a size check:
```makefile
	@test -s perf/results/scalene-w1.json || { echo "scalene-w1.json missing/empty — profile run failed"; exit 1; }
```

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
