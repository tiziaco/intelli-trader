---
phase: 01-perf-tooling-baseline
plan: 01
subsystem: infra
tags: [scalene, makefile, argparse, tracemalloc, perf-harness, gitignore, json-baseline]

# Dependency graph
requires:
  - phase: quick-task 260622-vlh (perf harness build)
    provides: "perf/runners/run_w1_benchmark.py + run_w2_sweep.py (timing + tracemalloc runners), perf/workloads W1 topology / W2 synthetic, scalene dev dep"
provides:
  - "make perf-w1 / perf-w2 / perf-baseline / perf-profile / perf-view command surface (TOOL-01)"
  - "two-mode benchmark-vs-profile split: perf-w1 is profiler-free, perf-profile is the only Scalene path (TOOL-02)"
  - "run_w1_benchmark.py --json / --check / --baseline-out flags + D-01 baseline schema (_to_baseline_schema/_write_baseline) + soft regression guard (_check_regression)"
  - "run_w2_sweep.py --json flag"
  - "D-07 pinned default window 2026-04-23 → 2026-06-23 (env-overridable)"
  - "narrow .gitignore Scalene entries (W1-BASELINE.json stays trackable)"
affects: [01-02 baseline-freeze, phase-02 order-storage-indexing, phase-03 pnl-accumulator, phase-04 hot-path, phase-05 incremental-indicators, phase-06 bar-feed]

# Tech tracking
tech-stack:
  added: []  # no new deps — argparse/json/sys/datetime are stdlib; scalene already present
  patterns:
    - "argparse over the existing bare main() — no flag keeps the human stdout default (D-06)"
    - "soft regression guard: fail ONLY on >+5% wall-clock slowdown, never on improvement (no abs(), Pitfall 3)"
    - "money-as-string at the JSON edge (final_equity serialized as a quoted string, never a float)"
    - "two-step Scalene run→view split (the gated run never carries the profiler)"

key-files:
  created: []
  modified:
    - perf/runners/run_w1_benchmark.py
    - perf/runners/run_w2_sweep.py
    - Makefile
    - .gitignore

key-decisions:
  - "D-07: pinned _START_DATE default 2025-12-24 → 2026-04-23 so make perf-w1 reproduces ~240.8s with no env vars; os.environ.get override intact"
  - "OQ-1/A1: oracle final_equity stored as the STRING constant 46189.87730727451 — a provenance stamp the engine was on-contract at freeze, NOT a W1-derived value"
  - "perf-profile viewer changed by user from `scalene view --html` to native `scalene view` local-server viewer (deviation, TOOL-02 intent preserved) + new perf-view convenience target"

patterns-established:
  - "Pattern 1: argparse main() with no-flag human-stdout default (D-06) on both perf runners"
  - "Pattern 2: in-runner --check compare mode is the single home for the JSON load + soft guard (no second wrapper script)"
  - "Pattern 3: narrow gitignore (scalene-profile.html + perf/results/scalene-*.json) never a broad perf/results/*.json that would sweep the committed baseline (Pitfall 4)"

requirements-completed: [TOOL-01, TOOL-02]

# Metrics
duration: ~5min hands-on (46min wall incl. the human's slow manual Scalene profile run at the checkpoint)
completed: 2026-06-23
---

# Phase 01 Plan 01: Perf Tooling & Baseline Instruments Summary

**The v1.5 perf-measurement surface: `--json`/`--check`/`--baseline-out` on the W1 runner, `--json` on the W2 sweep, the four `perf-*` Makefile targets, the D-07 pinned window, and narrow Scalene `.gitignore` lines — the harness every later v1.5 phase's gate (b) consumes.**

## Performance

- **Duration:** ~5 min hands-on (46 min wall-clock, dominated by the human's manual Scalene profile run during the blocking checkpoint)
- **Started:** 2026-06-23T17:00:10Z
- **Completed:** 2026-06-23T17:46:33Z
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint, approved)
- **Files modified:** 4

## Accomplishments

- `run_w1_benchmark.py` gained the `--json` / `--check` / `--baseline-out` argparse surface (D-06: no-flag keeps the human stdout default), plus three module-level helpers: `_to_baseline_schema` (D-01 payload), `_write_baseline` (freeze), and `_check_regression` (soft guard that fails ONLY on a >+5% slowdown).
- D-07: the `_START_DATE` default pinned `2025-12-24` → `2026-04-23` so `make perf-w1` reproduces the ~240.8 s gated number with no env vars, while `make perf-w1 W1_START_DATE=…` still overrides.
- `run_w2_sweep.py` gained a single `--json` flag (no `--check`/`--baseline-out` — W2 is neither baseline-frozen nor guard-gated).
- Four `perf-*` Makefile targets (`perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile`) matching the `backtest:` idiom, TAB-indented recipes, `-m perf.runners.…` module invocation; `perf-w1` is profiler-free and `perf-profile` is the only Scalene path (TOOL-02 structural split, two-step `run`→`view`, Pitfall 1 respected).
- Narrow `.gitignore` Scalene entries (`scalene-profile.html`, `perf/results/scalene-*.json`) — the committed `W1-BASELINE.json` is verified NOT swept (Pitfall 4).
- Gate (a) held: `tests/integration/test_backtest_oracle.py` green (3 passed, 134 / 46189.87730727451). No `itrader/` engine code touched.

## Task Commits

Each task was committed atomically:

1. **Task 1: W1 `--json`/`--check`/`--baseline-out` + D-07 window; W2 `--json`** — `6f1eab5` (feat)
2. **Task 2: four `perf-*` Makefile targets + narrow `.gitignore` Scalene entries** — `25e97a1` (feat)
3. **Task 3: human-verify Scalene `perf-profile` artifact** — APPROVED (manual-only checkpoint; no code commit of its own — the user's two viewer-deviation commits below carry the only Task-3-adjacent changes)

**User deviation commits (made by the user on the branch during the checkpoint):**

- `4fa61d1` — chore(perf): use native `scalene view` instead of `--html` standalone
- `4d50996` — chore(perf): add `perf-view` target (reopen the existing profile JSON in the native viewer)

## Files Created/Modified

- `perf/runners/run_w1_benchmark.py` — argparse main() + `_to_baseline_schema`/`_write_baseline`/`_check_regression` helpers; D-07 pinned `_START_DATE`; stdlib imports extended (argparse/json/sys/datetime)
- `perf/runners/run_w2_sweep.py` — argparse main() with a single `--json` flag
- `Makefile` — `perf-w1`/`perf-w2`/`perf-baseline`/`perf-profile` (+ user-added `perf-view`) targets; `.PHONY` extended
- `.gitignore` — narrow `scalene-profile.html` + `perf/results/scalene-*.json` Scalene-artifact lines

## Decisions Made

- **D-07 window pin:** changed ONLY the runner's `_START_DATE` default literal (not the env mechanism, not `_END_DATE`), keeping `make perf-w1 W1_START_DATE=…` overridable via the Makefile's `.EXPORT_ALL_VARIABLES`.
- **OQ-1/A1 final_equity:** serialized the byte-exact SMA_MACD oracle constant `46189.87730727451` as a STRING (money discipline) — a "the engine was on-contract at freeze" provenance stamp, never a W1-coverage-derived value.
- **Soft guard semantics (D-04, Pitfall 3):** `_check_regression` always prints both deltas and fails (returns 1) ONLY when `wall_d > band_pct` — a faster-or-within-±5% run returns 0; no `abs()` gate, so an optimization never trips it.

## Deviations from Plan

### User-introduced deviation (approved at the Task 3 checkpoint)

**1. [User deviation] `perf-profile` viewer switched from `scalene view --html` to native `scalene view`**
- **Found during:** Task 3 (human-verify checkpoint — the user ran `make perf-profile` and adjusted the viewer themselves)
- **Issue / rationale:** The user opens the profile via a local server in the VS Code browser rather than as a standalone HTML file; the native `scalene view` (local-server viewer) fits that workflow better than `--html`.
- **Change:** `perf-profile`'s second step is now `poetry run python -m scalene view perf/results/scalene-w1.json` (native viewer). A new `perf-view` convenience target reopens the existing `perf/results/scalene-w1.json` without re-running the ~240 s + profiler workload.
- **TOOL-02 intent preserved:** `perf-profile` is still the ONLY Scalene path, structurally split from the profiler-free gated `perf-w1` (verified: `make -n perf-w1` carries no scalene). The two-step `run`→`view` split is intact and Pitfall 1 (`--html` is not a `scalene run` flag) is still respected.
- **Acceptance-criterion supersession:** the plan's literal Task-2 criterion "`make -n perf-profile` contains `scalene view --html`" is SUPERSEDED by this approved deviation. The structural intent (`scalene run` + a separate `scalene view` render step) is what holds, and it does.
- **Files modified:** `Makefile`
- **Verification:** `make -n perf-profile` shows `scalene run` + `scalene view`; `make -n perf-w1` has no scalene; `make -n perf-view` parses; `W1-BASELINE.json` not gitignored. Human confirmed a healthy per-line CPU attribution (48.4% `in_memory_storage.py`, 17.8% `indicators/catalog.py`, 17.1% `position_manager.py`) with no `Thread.run` bucket — `--profile-all` did not leak in.
- **Committed in:** `4fa61d1`, `4d50996` (by the user)

---

**Total deviations:** 1 (user-introduced viewer change, approved at the checkpoint; no executor auto-fixes)
**Impact on plan:** No scope creep. TOOL-01 and TOOL-02 are fully satisfied; only the literal `--html` acceptance wording is superseded by an equivalent approved viewer choice. Hotspot ranking from the profile (in_memory_storage 48% → Phase 2; position_manager 17% → Phase 3; indicators 18% → Phase 5) corroborates the ROADMAP sequencing.

## Issues Encountered

None — both auto tasks executed exactly as written; the only adjustment was the user's approved viewer deviation at the checkpoint.

## Known Stubs

None.

## Threat Flags

None — this phase adds build targets + stdlib measurement to an out-of-package eval harness with no auth/session/access-control/crypto/network/untrusted-input surface. T-01-01 (gitignore tampering) was mitigated via the narrow Scalene lines, verified by the `git check-ignore` asserts.

## User Setup Required

None — no external service configuration required. All tooling (scalene 2.3.0, stdlib, Make, Poetry) was already present.

## Next Phase Readiness

- The perf instruments are built and committed. Plan 01-02 (TOOL-04) can now run `make perf-baseline` to write the committed `perf/results/W1-BASELINE.json`, then `make perf-w1` to confirm the delta-print + soft guard against it.
- Gate (a) is green and no engine code was touched — the phase remains held to gate (a) only.
- No blockers.

## Self-Check: PASSED

- `perf/runners/run_w1_benchmark.py` — FOUND (modified)
- `perf/runners/run_w2_sweep.py` — FOUND (modified)
- `Makefile` — FOUND (modified)
- `.gitignore` — FOUND (modified)
- Commit `6f1eab5` — FOUND
- Commit `25e97a1` — FOUND
- Commit `4fa61d1` — FOUND
- Commit `4d50996` — FOUND

---
*Phase: 01-perf-tooling-baseline*
*Completed: 2026-06-23*
