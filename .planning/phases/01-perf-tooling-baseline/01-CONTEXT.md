# Phase 1: Perf Tooling & Baseline - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 delivers a **repeatable measurement harness** so every later v1.5 optimization phase has
an honest, gated way to prove its W1 improvement — and **re-freezes the W1 baseline** as the locked
reference before any optimization touches engine code.

In scope:
- Root-Makefile `perf-*` command surface (inheriting `include .env` / `.EXPORT_ALL_VARIABLES`):
  `perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile` (TOOL-01).
- The two-mode split: a clean **benchmark** (profiler-free, the gated timing run that produces the
  frozen number) vs a **separate** Scalene `--cpu-only --html --program-path` **profile** command
  that writes a gitignored HTML artifact and NEVER wraps the timed/gated run (TOOL-02).
- Re-freeze the W1 baseline (clean run, ≈ 240.8 s / 167.3 MB) as the locked reference every later
  phase is judged against (TOOL-04).

**Tooling + measurement ONLY — no engine code changes.** Held to gate (a) (byte-exact SMA_MACD
oracle green: 134 trades / `final_equity 46189.87730727451`) alone; there is no gate (b) for this
phase because it builds gate (b)'s instrument.

Out of scope (decided this discussion):
- **TOOL-03 cross-validation (backtesting.py + backtrader) is DROPPED from v1.5** — see D-05. No
  `perf-crossval` target.

</domain>

<decisions>
## Implementation Decisions

### Baseline freeze artifact + regression guard
- **D-01:** `perf-baseline` writes a **committed machine-readable** baseline file (e.g.
  `perf/results/W1-BASELINE.json`) carrying at minimum: `wall_clock_s`, `peak_mem_mb`, the W1
  window, the oracle `final_equity` (provenance that the run was on-contract), and the freeze date.
  This file IS "the locked reference" every later phase's gate (b) diffs against.
- **D-02:** `perf-w1` prints the **delta vs the frozen baseline**, and a **soft regression guard**
  flags (fails) a slowdown beyond tolerance. "Soft" = the guard protects the gate; it is a tooling
  assert, not a CI wiring of the oracle (the byte-exact oracle remains the separate correctness lock,
  D-10 evidence-not-oracle discipline preserved).

### Gate (b) measurement rigor (defines "measurable improvement" for Phases 2-6)
- **D-03:** **Single timed run** per check (not best-of-N) — cheaper, and each phase targets a large
  named CPU chunk (37% / 13% / 24%) so genuine wins clear noise easily.
- **D-04:** **"Measurable" = ≥5% wall-clock improvement** vs the frozen baseline. Noise on a ~240 s
  run is typically 1–2%, so ≥5% is a confident real win. Peak memory tracked alongside (no separate
  threshold — reported and watched for regression). This threshold is the gate-(b) pass bar inherited
  by every optimization phase.

### Cross-validation scope (TOOL-03)
- **D-05:** **TOOL-03 is DROPPED entirely from v1.5.** Rationale: v1.5 is behavior-preserving and
  gated on the **byte-exact oracle staying green** — if the oracle is green the numbers *cannot* have
  changed, so correctness is proven by **invariance**, not by external **agreement**. Cross-validation
  against other engines was the tool for *result-changing* milestones (v1.0/v1.4) that needed external
  proof the *new* numbers were right; v1.5 produces no new numbers. The v1.0 `CROSS-VALIDATION.md`
  evidence remains valid precisely because nothing moves. Separately, comparing a **vectorized**
  framework (backtesting.py/backtrader) to event-driven iTrader on **speed** is apples-to-oranges and
  meaningless — gate (b) is iTrader-vs-its-own-baseline, never iTrader-vs-other-frameworks.
- **Ripple (authorized this discussion):** `REQUIREMENTS.md`, `ROADMAP.md`, and
  `milestones/v1.5-ROADMAP.md` updated to remove TOOL-03 + Phase 1 success-criterion #3 and the
  `perf-crossval` target. **Phase 1 now carries 3 requirements: TOOL-01, TOOL-02, TOOL-04.**

### Runner output / invocation contract
- **D-06:** The existing iTrader-only runners (`perf/runners/run_w1_benchmark.py`,
  `run_w2_sweep.py`) gain a **`--json` structured-emit flag** (feeds `W1-BASELINE.json` + the
  soft-guard delta) while keeping the human-readable stdout summary as the default.
- **D-07:** **Pin the 2-month frozen-baseline window (`2026-04-23`→`2026-06-23`) as the
  `perf-w1` / `perf-baseline` default** so the gated number is reproducible with no env vars to
  remember. `W1_START_DATE` / `W1_END_DATE` env overrides still work for ad-hoc slices.

### Claude's Discretion
- Exact JSON schema/field names of `W1-BASELINE.json`, the precise wording of the soft-guard failure
  message, and how `perf-w2` surfaces its scaling table (left to planning) — within D-01/D-02/D-06.
- Whether the soft-guard lives inside the runner (`--json` compare mode) or a thin `perf-check`
  wrapper — planner's call; the contract (D-02) is what matters.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of truth (the spike IS the research)
- `perf/results/PERF-BASELINE-RESULTS.md` — frozen baseline §1 (240.8 s / 167.3 MB), ranked hotspot
  map §2, scaling curve §3, proposed phase breakdown §6, exit criteria §7. **Authoritative.**
- `.planning/spikes/PERF-BASELINE.md` §13 — handoff: Milestone Phase 1 = add comparison runners +
  freeze baseline on top of the existing harness. (NOTE: §13's three-engine comparison item is the
  TOOL-03 work now DROPPED — D-05; the freeze-baseline half stands.)

### Milestone scope + requirements
- `.planning/REQUIREMENTS.md` — TOOL-01/02/04 (TOOL-03 removed); the milestone gate definition.
- `.planning/milestones/v1.5-ROADMAP.md` — Phase 1 goal + success criteria, milestone gate, phase map.
- `.planning/ROADMAP.md` — Phase 1 entry + v1.5 milestone framing.

### Gate (a) — correctness lock (held, not changed)
- `tests/integration/test_backtest_oracle.py` — the byte-exact SMA_MACD oracle
  (134 trades / `final_equity 46189.87730727451`). Phase 1 must keep this green.
- `tests/golden/CROSS-VALIDATION.md` — v1.0 numerical cross-val evidence; **stays valid** under v1.5
  (no numbers change). Explains the dropped-TOOL-03 methodology (D-03 shared indicators, D-04
  metrics-recompute, ~1% tolerance) for the record.

### Existing harness (extend, don't rebuild)
- `perf/README.md` — harness layout + conventions (4-space indent, absolute imports, perf/ lives
  OUTSIDE shipped `itrader/`).
- `perf/runners/run_w1_benchmark.py` — existing iTrader-only W1 runner (gets `--json`, pinned window).
- `perf/runners/run_w2_sweep.py` — existing iTrader-only W2 scaling sweep (gets `--json`).
- `perf/workloads/w1_topology.py` — W1 wiring (4 strategies / 6 portfolios; `CSV_PATHS`, `TIMEFRAME`).
- `Makefile` — root Makefile where the `perf-*` targets land (inherits `include .env`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `perf/runners/run_w1_benchmark.py` / `run_w2_sweep.py`: complete iTrader-only timing+tracemalloc
  runners already exist and print per-portfolio breakdowns; Phase 1 wraps them in Makefile targets
  and adds `--json` + the baseline-freeze/compare path — it does NOT re-author the runners.
- The `W1_START_DATE` / `W1_END_DATE` env-override mechanism already exists in `run_w1_benchmark.py`
  — D-07 pins the default to the frozen 2-month window while preserving these overrides.
- `tracemalloc` is already the memory instrument (Scalene memory profiler is unusable here —
  PERF-BASELINE-RESULTS.md §5); peak-mem in the baseline file comes from it.

### Established Patterns
- The Makefile already follows a `make <target>:` pattern with `@echo` banners + `poetry run python`
  (see `backtest:` target) and top-level `include .env` / `.EXPORT_ALL_VARIABLES` — `perf-*` targets
  match this shape.
- Scalene invocation is fixed by TOOL-02 / PERF-BASELINE-RESULTS.md §0: `--cpu-only --html
  --program-path <repo>`, NO `--profile-all` (it profiles Scalene's own thread).
- `.gitignore` currently ignores `htmlcov/`; the gitignored Scalene HTML artifact (TOOL-02) needs a
  new ignore entry (e.g. `perf/results/*.html` or a `perf/results/profiles/` dir).

### Integration Points
- `perf-baseline` → writes `perf/results/W1-BASELINE.json` (new committed artifact).
- `perf-w1` → reads that JSON, prints delta, soft-guard asserts on slowdown beyond the D-04 band.
- `perf-profile` → separate Scalene run writing gitignored HTML; never wraps the gated run.

</code_context>

<specifics>
## Specific Ideas

- Baseline file location/name suggestion: `perf/results/W1-BASELINE.json` (sits alongside the existing
  `perf/results/PERF-BASELINE-RESULTS.md` source-of-truth doc).
- Gate-(b) pass bar (≥5% wall-clock, single run) is a **milestone-wide** decision made here in Phase 1
  — Phases 2-6 inherit it; planning for those phases should cite D-04 rather than re-deciding.

</specifics>

<deferred>
## Deferred Ideas

- **Cross-validation against external frameworks** — dropped from v1.5 (D-05). If a future
  *result-changing* milestone re-baselines numbers, the v1.0 `CROSS-VALIDATION.md` force-match
  methodology (D-03/D-04 in that doc) is the template to revive. Not a v1.5 concern.
- **Best-of-N / median timing** (rejected in favor of single-run D-03) — revisit only if observed
  run-to-run variance turns out to exceed the ≥5% band and starts producing ambiguous gate verdicts.
- **100/200-symbol W2 scaling point** (PERF-BASELINE-RESULTS.md §3 caveat) — only if large universes
  become a target; symbol axis is clean O(n) through n=50 today. Tracked as PERF-08 (v2/deferred).

</deferred>

---

*Phase: 1-perf-tooling-baseline*
*Context gathered: 2026-06-23*
