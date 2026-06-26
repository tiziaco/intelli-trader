---
phase: 01-perf-tooling-baseline
verified: 2026-06-23T20:30:00Z
status: passed
resolved: 2026-06-26
score: 9/9
overrides_applied: 1
overrides:
  - must_have: "make -n perf-profile contains scalene view --html"
    reason: "User-approved deviation at Task 3 human-verify checkpoint: perf-profile uses native `scalene view` (local-server viewer) instead of --html standalone. TOOL-02 structural intent is preserved — perf-profile is the only Scalene path, structurally split from profiler-free perf-w1. Documented in 01-01-SUMMARY.md deviations section."
    accepted_by: "tiziaco"
    accepted_at: "2026-06-23T18:00:00Z"
human_verification:
  - test: "Run `make perf-profile` and inspect the native Scalene viewer output"
    expected: "Scalene viewer opens (local-server URL printed to stdout), renders per-line CPU attribution over itrader/ + perf/ — no Thread.run bucket dominating (which would indicate --profile-all leaked in). Hotspots visible: in_memory_storage ~48%, indicators/catalog ~18%, position_manager ~17%."
    why_human: "The profiler artifact is a running local server launched by `scalene view` — cannot be inspected programmatically in a read-only verification pass. The ~2-5x profiler overhead makes this a long manual run (~10min+). Confirmed approved in plan 01-01 Task 3 checkpoint but requires human to re-run and inspect if re-verifying."
    resolution: "CLOSED 2026-06-26 at milestone close — owner-approved deferred manual check (Task 3 checkpoint, tiziaco). All 9/9 automated checks pass; the profiler harness was exercised in practice across every subsequent phase's gate-(b) re-profile (Phases 5-8 all ran make perf-profile), so the harness is empirically validated. Non-blocking; closed per v1.5-MILESTONE-AUDIT.md tech_debt item 4."
---

# Phase 01: Perf Tooling & Baseline — Verification Report

**Phase Goal:** A repeatable measurement harness exists in the root Makefile so every later phase
has an honest, gated way to prove its W1 improvement — and the W1 baseline is re-frozen as the
locked reference before any optimization touches engine code.
**Verified:** 2026-06-23T20:30:00Z
**Status:** human_needed (all automated checks pass; one deferred manual check from the Task 3 human-verify checkpoint)
**Re-verification:** No — initial verification.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `make perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile` all parse as valid Makefile targets (TOOL-01) | VERIFIED | `make -n` for all four targets exits 0 and prints their recipes. `.PHONY` declaration confirmed on Makefile line 6. |
| 2 | `perf-w1` is profiler-free; `perf-profile` is the only Scalene path (TOOL-02 structural split) | VERIFIED | `make -n perf-w1` output contains no `scalene` substring. `make -n perf-profile` contains `scalene run` and `scalene view`. |
| 3 | `run_w1_benchmark.py` accepts `--json`, `--check`, `--baseline-out`; no flag keeps human stdout (D-06) | VERIFIED | `poetry run python -m perf.runners.run_w1_benchmark --help` lists all three flags. `result = run_w1()` is called unconditionally before flag branches. |
| 4 | `run_w2_sweep.py` accepts `--json` only; no `--check`/`--baseline-out` (D-06) | VERIFIED | `poetry run python -m perf.runners.run_w2_sweep --help` shows only `--json`. `--check`/`--baseline-out` absent from W2. |
| 5 | The `perf-w1` default window is the frozen 2-month slice 2026-04-23 to 2026-06-23 with no env vars (D-07) | VERIFIED | `grep -n '"2026-04-23"' perf/runners/run_w1_benchmark.py` matches line 32: `_START_DATE = os.environ.get("W1_START_DATE", "2026-04-23")`. Old `"2025-12-24"` default gone. |
| 6 | Scalene HTML/JSON profile artifacts are gitignored; committed `W1-BASELINE.json` is NOT swept (Pitfall 4) | VERIFIED | `git check-ignore scalene-profile.html` → ignored. `git check-ignore perf/results/scalene-w1.json` → ignored. `git check-ignore perf/results/W1-BASELINE.json` → not ignored (exits non-zero). `.gitignore` has no broad `perf/results/*.json` line. |
| 7 | `perf/results/W1-BASELINE.json` exists, is tracked, and carries all D-01 fields with oracle_provenance.final_equity as a quoted string (TOOL-04) | VERIFIED | File exists, `git ls-files` confirms tracked. Python assertion confirms: `wall_clock_s=247.5` (>0), `peak_mem_mb=167.3`, `window.start_date="2026-04-23"`, `window.end_date="2026-06-23"`, `frozen_at="2026-06-23"`, `final_equity="46189.87730727451"` (type `str`). |
| 8 | No `perf-crossval` target; no external-framework cross-validation runner (TOOL-03 dropped per D-05) | VERIFIED | `grep` for `perf-crossval`, `backtesting.py`, `backtrader` in Makefile returns nothing. No perf-crossval target exists. |
| 9 | Byte-exact SMA_MACD oracle green; no itrader/ engine code changed (gate a) | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (134 trades / 46189.87730727451). `git diff af60d4e v1.5/phase-1-baseline -- itrader/` → 0 lines diff. |

**Score:** 9/9 truths verified (1 override applied — `scalene view --html` wording superseded by approved `scalene view` deviation)

---

### Deferred Items

None — all items are verified or handled by override.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `perf/runners/run_w1_benchmark.py` | argparse surface + `_to_baseline_schema` / `_write_baseline` / `_check_regression` helpers; D-07 pinned default | VERIFIED | File at 233 lines. All three flag arguments present (`--json`, `--check`, `--baseline-out`). All three helpers implemented. `_START_DATE` pinned to `"2026-04-23"`. 4-space indent throughout (no tabs). |
| `perf/runners/run_w2_sweep.py` | `--json` argparse flag only | VERIFIED | File at 163 lines. `--json` flag present, no `--check`/`--baseline-out`. argparse `main()` replaces bare call. 4-space indent. |
| `Makefile` | `perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile` targets; `.PHONY` extended; TAB-indented recipes | VERIFIED | All four targets confirmed. `.PHONY` line 6 includes all four. Recipe lines are TAB-indented (grep for space-indented recipes returns 0 matches). `perf-view` bonus target added by user. |
| `.gitignore` | Narrow `scalene-profile.html` + `perf/results/scalene-*.json` lines | VERIFIED | Lines 48-49 of `.gitignore` carry exactly these two narrow entries. No broad `*.json` sweep. |
| `perf/results/W1-BASELINE.json` | Committed locked W1 reference with D-01 fields | VERIFIED | Committed in `b56afdd`. All D-01 fields present and correct. `final_equity` is string `"46189.87730727451"`. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `Makefile perf-w1` | `perf/runners/run_w1_benchmark.py --check` | `poetry run python -m perf.runners.run_w1_benchmark --check` | WIRED | Makefile line 101 matches exactly. |
| `Makefile perf-baseline` | `perf/results/W1-BASELINE.json` | `--baseline-out perf/results/W1-BASELINE.json` | WIRED | Makefile line 112 matches. `_write_baseline` calls `json.dump(_to_baseline_schema(result), fh, indent=2)`. |
| `Makefile perf-w1 --check` | `perf/results/W1-BASELINE.json` (reads it) | `_check_regression(result, "perf/results/W1-BASELINE.json")` | WIRED | `main()` calls `sys.exit(_check_regression(result, "perf/results/W1-BASELINE.json"))` on `--check`. |
| `Makefile perf-profile` | `scalene run` + `scalene view` (two-step) | `poetry run python -m scalene run ... && poetry run python -m scalene view ...` | WIRED | Lines 123-126. First step writes `perf/results/scalene-w1.json`; second step opens viewer. |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase produces no components rendering dynamic data. All artifacts are CLI runners and configuration files.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `run_w1_benchmark --help` lists all three flags | `poetry run python -m perf.runners.run_w1_benchmark --help` | All three flags (`--json`, `--check`, `--baseline-out`) present in output | PASS |
| `run_w2_sweep --help` lists `--json` only | `poetry run python -m perf.runners.run_w2_sweep --help` | `--json` listed; no `--check`/`--baseline-out` | PASS |
| `perf-w1` dry-run carries no `scalene` | `make -n perf-w1` | Output: `poetry run python -m perf.runners.run_w1_benchmark --check` — no scalene | PASS |
| `perf-profile` dry-run has `scalene run` and `scalene view` | `make -n perf-profile` | Both `scalene run` and `scalene view` present in output | PASS |
| `_START_DATE` default pinned to `2026-04-23` | `grep '"2026-04-23"' perf/runners/run_w1_benchmark.py` | Line 32 matches: `os.environ.get("W1_START_DATE", "2026-04-23")` | PASS |
| `final_equity` is a quoted string, not float | `grep '"46189.87730727451"' perf/runners/run_w1_benchmark.py` | Line 176: `"final_equity": "46189.87730727451"` (inside quotes) | PASS |
| `_check_regression` fails only on slowdown (no abs()) | Code inspection + grep | Line 207: `if wall_d > band_pct:` — directional only, no `abs()` | PASS |
| W1-BASELINE.json D-01 fields pass Python assertions | `python3 -c "import json; d=json.load(...); assert all fields..."` | All assertions pass; final_equity is type `str` | PASS |
| Gate (a) oracle green | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed — 134 trades / 46189.87730727451 | PASS |
| No itrader/ code changed | `git diff af60d4e v1.5/phase-1-baseline -- itrader/ \| wc -l` | 0 lines diff | PASS |

---

### Probe Execution

Not applicable — no conventional `scripts/*/tests/probe-*.sh` probes defined for this phase (tooling-only phase; validated via `make -n` dry-runs and `--help` CLI checks above).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TOOL-01 | 01-01-PLAN.md | `make perf-*` command surface in root Makefile | SATISFIED | All four targets (`perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile`) present, `.PHONY` extended, TAB-indented recipes, inherit `include .env` / `.EXPORT_ALL_VARIABLES` |
| TOOL-02 | 01-01-PLAN.md | Two-mode split: clean benchmark vs separate Scalene profile | SATISFIED | `perf-w1` carries no scalene; `perf-profile` is the only scalene path (two-step run→view) |
| TOOL-03 | DROPPED | Cross-validation runners (backtesting.py + backtrader) | DROPPED (owner decision 2026-06-23, D-05) | Absence is correct; no `perf-crossval` target exists |
| TOOL-04 | 01-02-PLAN.md | W1 baseline re-frozen to committed `perf/results/W1-BASELINE.json` with soft regression guard | SATISFIED | File committed in `b56afdd`; all D-01 fields present; `--check` guard fails only on `wall_d > band_pct`; negative-test proof performed (injected ~20% lower baseline → guard exited non-zero with `PERF REGRESSION`, then restored) |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No anti-patterns found in phase-modified files (`run_w1_benchmark.py`, `run_w2_sweep.py`, `Makefile`, `.gitignore`). No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers. No stubs or empty implementations. |

---

### Human Verification Required

### 1. Scalene perf-profile artifact inspection

**Test:** Run `make perf-profile` from the repo root. Wait for the Scalene profiler to complete (~10+ minutes, 2-5x W1 overhead). Open the localhost URL printed by `scalene view` in a browser.

**Expected:** Native Scalene viewer renders a per-line CPU attribution over `itrader/` + `perf/` code. Hotspots visible: `in_memory_storage.py` ~48%, `indicators/catalog.py` ~18%, `position_manager.py` ~17%. No `Thread.run` bucket dominates (which would mean `--profile-all` leaked in). After the run, `git status` must NOT show `scalene-profile.html` or `perf/results/scalene-w1.json` as untracked-to-be-committed (gitignored). `make -n perf-w1` must show no `scalene` (profiler-free gated run).

**Why human:** The profile artifact is a live local-server process launched by `scalene view` — the localhost URL cannot be inspected programmatically. The run is slow (~10-15 minutes). This was approved at the 01-01 Task 3 blocking checkpoint during plan execution (the user ran it manually on 2026-06-23 and approved the per-line profile output). Re-verification only requires this if the Makefile `perf-profile` recipe changed since then. It has not changed (commits `4fa61d1` and `4d50996` are the final state). If re-verification is expedient, treat the Task-3 checkpoint approval documented in `01-01-SUMMARY.md` as the standing proof.

---

### Gaps Summary

No gaps found. All 9 observable truths are VERIFIED. All 5 required artifacts pass all three verification levels (exists, substantive, wired). All key links are wired. All requirements covered. No anti-patterns. Gate (a) oracle green. No itrader/ engine code touched.

The single `human_needed` item is the Scalene artifact inspection from the Task 3 blocking checkpoint. It was approved during plan execution on 2026-06-23 (documented in `01-01-SUMMARY.md`). The `scalene view` invocation produces a local-server viewer (approved user deviation from `--html`) — structurally equivalent for the TOOL-02 intent.

---

## Key Evidence Summary

- **Gate (a):** `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (134 / 46189.87730727451)
- **TOOL-01:** All four `make perf-*` targets dry-run cleanly with TAB-indented recipes
- **TOOL-02:** `make -n perf-w1` has no `scalene`; `make -n perf-profile` has `scalene run` + `scalene view`
- **D-06:** Both runners' `--help` show their flags; no-flag keeps human stdout
- **D-07:** `_START_DATE` pinned to `"2026-04-23"` on line 32 of `run_w1_benchmark.py`
- **TOOL-04:** `perf/results/W1-BASELINE.json` committed in `b56afdd`; all D-01 fields pass; `final_equity` is `str`, not float
- **Pitfall 3:** `_check_regression` uses `wall_d > band_pct` (no `abs()`); only slowdown fails
- **Pitfall 4:** `git check-ignore perf/results/W1-BASELINE.json` exits non-zero (trackable); no broad `*.json` gitignore line
- **No engine code changed:** `git diff af60d4e v1.5/phase-1-baseline -- itrader/` → 0 lines

---

_Verified: 2026-06-23T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
