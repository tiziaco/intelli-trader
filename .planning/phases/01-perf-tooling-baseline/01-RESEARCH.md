# Phase 1: Perf Tooling & Baseline - Research

**Researched:** 2026-06-23
**Domain:** Performance measurement tooling (Makefile harness, Scalene profiling, JSON baseline freeze + regression guard) over an existing iTrader perf harness
**Confidence:** HIGH (everything is on-disk and tool-verified; the spike IS the research)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `perf-baseline` writes a **committed machine-readable** baseline file (`perf/results/W1-BASELINE.json`) carrying at minimum: `wall_clock_s`, `peak_mem_mb`, the W1 window, the oracle `final_equity` (provenance that the run was on-contract), and the freeze date. This file IS "the locked reference" every later phase's gate (b) diffs against.
- **D-02:** `perf-w1` prints the **delta vs the frozen baseline**, and a **soft regression guard** flags (fails) a slowdown beyond tolerance. "Soft" = the guard protects the gate; it is a tooling assert, not a CI wiring of the oracle (the byte-exact oracle remains the separate correctness lock, D-10 evidence-not-oracle discipline preserved).
- **D-03:** **Single timed run** per check (not best-of-N) — cheaper, and each phase targets a large named CPU chunk (37% / 13% / 24%) so genuine wins clear noise easily.
- **D-04:** **"Measurable" = ≥5% wall-clock improvement** vs the frozen baseline. Noise on a ~240 s run is typically 1–2%, so ≥5% is a confident real win. Peak memory tracked alongside (no separate threshold — reported and watched for regression). This threshold is the gate-(b) pass bar inherited by every optimization phase.
- **D-05:** **TOOL-03 is DROPPED entirely from v1.5.** Correctness is proven by **invariance** (the byte-exact oracle staying green), not external **agreement**. No `perf-crossval` target. No backtesting.py / backtrader comparison runners.
- **D-06:** The existing iTrader-only runners (`perf/runners/run_w1_benchmark.py`, `run_w2_sweep.py`) gain a **`--json` structured-emit flag** (feeds `W1-BASELINE.json` + the soft-guard delta) while keeping the human-readable stdout summary as the default.
- **D-07:** **Pin the 2-month frozen-baseline window (`2026-04-23`→`2026-06-23`) as the `perf-w1` / `perf-baseline` default** so the gated number is reproducible with no env vars to remember. `W1_START_DATE` / `W1_END_DATE` env overrides still work for ad-hoc slices.

### Claude's Discretion
- Exact JSON schema/field names of `W1-BASELINE.json`, the precise wording of the soft-guard failure message, and how `perf-w2` surfaces its scaling table (left to planning) — within D-01/D-02/D-06.
- Whether the soft-guard lives inside the runner (`--json` compare mode) or a thin `perf-check` wrapper — planner's call; the contract (D-02) is what matters.

### Deferred Ideas (OUT OF SCOPE)
- **Cross-validation against external frameworks** — dropped from v1.5 (D-05). Revive the v1.0 `CROSS-VALIDATION.md` force-match methodology only if a future *result-changing* milestone re-baselines numbers.
- **Best-of-N / median timing** (rejected in favor of single-run D-03) — revisit only if observed run-to-run variance exceeds the ≥5% band and starts producing ambiguous gate verdicts.
- **100/200-symbol W2 scaling point** (PERF-BASELINE-RESULTS.md §3 caveat) — only if large universes become a target. Tracked as PERF-08 (v2/deferred).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **TOOL-01** | A `make perf-*` command surface lives in the **root** Makefile (inherits `include .env` / `.EXPORT_ALL_VARIABLES`): at minimum `perf-w1`, `perf-w2`, `perf-baseline`, `perf-profile`. | §"Makefile Target Bodies" gives exact target bodies matching the existing `backtest:` idiom; root Makefile already has `include .env` / `.EXPORT_ALL_VARIABLES` at lines 2–3 (no work to inherit it — just add targets + `.PHONY`). |
| **TOOL-02** | W1 runner has two modes — a clean profiler-free **benchmark** (gated timing run) and a **separate** Scalene CPU/HTML/repo-scoped **profile** command writing a gitignored HTML; profiling NEVER wraps the timed/gated run. | §"Scalene Invocation (Critical Correction)" — the benchmark already exists (`run_w1_benchmark.py`, no profiler). The profile is a **two-step `scalene run` then `scalene view --html`** (the single-command `--cpu-only --html --program-path` does NOT exist in the installed Scalene 2.3.0); §".gitignore Entry" gives the ignore line. |
| **TOOL-04** | W1 baseline re-frozen (clean run) after TOOL-01..02, BEFORE any optimization → committed `perf/results/W1-BASELINE.json`; `perf-w1` prints delta vs it with a soft regression guard; gate (b) = ≥5% wall-clock. | §"W1-BASELINE.json Schema" (proposed exact fields), §"Soft Regression Guard" (location + tolerance logic + failure-message contract), §"Runner CLI/Arg Surface" (where `--json` and the baseline window pin land). |
</phase_requirements>

## Summary

This is a **brownfield tooling extension**, not a build. The durable perf harness already exists on disk and works: `perf/runners/run_w1_benchmark.py` and `run_w2_sweep.py` are complete iTrader-only timing+tracemalloc runners that print human-readable breakdowns; `perf/workloads/w1_topology.py` wires the 4-strategy / 6-portfolio W1 topology; the frozen baseline (240.8 s / 167.3 MB over `2026-04-23`→`2026-06-23`) and the ranked hotspot map are already documented in `perf/results/PERF-BASELINE-RESULTS.md`. Phase 1 wraps these runners in root-Makefile `perf-*` targets, adds a `--json` emit flag, writes a committed `W1-BASELINE.json`, and adds a soft regression guard. No engine code changes — held only to gate (a) (the byte-exact oracle staying green).

**One material correction to the spec phrasing surfaced during research:** the installed Scalene (**2.3.0**, verified via Poetry) uses a `scalene run` / `scalene view` subcommand split. `--cpu-only`, `--program-path`, and `--profile-all` are `run` flags, but `--html` is a **`view`** flag. The single literal command `scalene run --cpu-only --html --program-path <repo>` from TOOL-02 / PERF-BASELINE-RESULTS.md §0 **will not parse** — `--html` is not a `run` option. The correct realization of the same *intent* (CPU-only, repo-scoped, HTML output, no profile-all) is two commands: `scalene run --cpu-only --program-path <repo> -o <json> -m perf.runners.run_w1_benchmark` then `scalene view --html <json>` (writes `scalene-profile.html`). The `perf-profile` target must chain both. This is the single highest-value planning input in this document.

**Primary recommendation:** Add four `perf-*` targets to the root Makefile mirroring the `backtest:` idiom; pin D-07's window as Makefile-level defaults passed through the existing `W1_START_DATE`/`W1_END_DATE` env mechanism; add `--json` to `run_w1_benchmark.py` that emits the schema below to stdout (and a `--baseline-out` to freeze it); put the soft guard inside the runner as a `--check` compare-mode against `W1-BASELINE.json` (single internal home, no second wrapper script); realize `perf-profile` as the two-step Scalene run+view; add one `.gitignore` line for the HTML artifact; re-freeze the baseline as the final task.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `make perf-*` command surface | Root build/orchestration (`Makefile`) | — | Targets inherit `include .env` / `.EXPORT_ALL_VARIABLES`; they only shell out to `poetry run`. No engine surface. |
| Timing + peak-memory measurement | `perf/runners/` (out-of-package eval harness) | — | Already implemented (`time.perf_counter` + `tracemalloc`); perf/ lives OUTSIDE shipped `itrader/`. Phase 1 adds emit, not measurement. |
| Structured JSON emit (`--json`) | `perf/runners/run_w1_benchmark.py` | `run_w2_sweep.py` | The runner owns the result dict; serializing it is a thin add to the existing `run_w1()`. |
| Baseline freeze artifact | `perf/results/W1-BASELINE.json` (committed) | — | Sits beside `PERF-BASELINE-RESULTS.md`; a pure data artifact, no code. |
| Soft regression guard | `perf/runners/run_w1_benchmark.py` (compare mode) | (alt: thin `perf-check` wrapper) | D-02 contract; reads the committed JSON, prints delta, exits non-zero on >tolerance slowdown. |
| Scalene profile | `perf/` invoked from `perf-profile` target | — | Separate command; NEVER wraps the gated run (2–5× wall-clock would destroy the gate). |
| Correctness lock (gate a) | `tests/integration/test_backtest_oracle.py` | — | Unchanged; Phase 1 only keeps it green. |

## Standard Stack

This phase uses **only already-installed, already-used** tooling. No new packages.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Scalene | 2.3.0 (2026.05.08) | CPU profiling → HTML artifact (`perf-profile`) | Already in `pyproject.toml` (`scalene = "^2.3.0"`); the spike used it; the only CPU profiler in the toolchain. **VERIFIED installed** via `poetry run scalene --version`. |
| `tracemalloc` (stdlib) | py3.13 | Peak-memory baseline (Scalene memory profiler is unusable here — §5 of results doc) | Already the memory instrument in both runners. |
| `time.perf_counter` (stdlib) | py3.13 | Wall-clock timing | Already used in both runners. |
| `json` (stdlib) | py3.13 | `--json` emit + `W1-BASELINE.json` read/write | Standard; no dependency. |
| `argparse` (stdlib) | py3.13 | `--json` / `--check` / window flags on the runners | Standard; the runners currently have no arg parser (they read env + `if __name__`). |
| GNU Make | system | `perf-*` targets | Root `Makefile` already exists with the `include .env` idiom. |
| Poetry | (project) | `poetry run python -m perf.runners.…` invocation in targets | Matches the `backtest:` target idiom. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `os.environ` (stdlib) | py3.13 | `W1_START_DATE` / `W1_END_DATE` overrides (already wired in `run_w1_benchmark.py` lines 27–28) | D-07 pins the default; env still overrides. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `argparse` on the runner for `--check` | A separate `perf-check.py` wrapper script | Both allowed (D-02 discretion). **Recommend in-runner `--check`** — single home, no second file to keep consistent with the JSON schema, no duplicated load logic. |
| `scalene view --html` (writes fixed `scalene-profile.html`) | `scalene view --standalone` (single self-contained HTML, implies `--html`) | `--standalone` embeds all JS/CSS into one file — better for a "manual review" artifact you might move/share. Recommend `--standalone`. Both write to the fixed name `scalene-profile.html`. |
| Pin window as Make variables | Hard-code window inside the runner default | D-07 wants the window pinned AND env-overridable. Cleanest: keep the runner's existing env-default mechanism, set the new default to the frozen window IN the runner, and let the Makefile target NOT set the env vars (so the pinned default applies) while `make perf-w1 W1_START_DATE=… ` still flows through. |

**Installation:** None. All tooling is present.

**Version verification (tool-run this session):**
```
poetry run scalene --version        → Scalene version 2.3.0 (2026.05.08)   [VERIFIED]
grep scalene pyproject.toml          → scalene = "^2.3.0"                   [VERIFIED]
```

## Package Legitimacy Audit

No external packages are installed in this phase. All tooling (`scalene`, stdlib `tracemalloc`/`time`/`json`/`argparse`, GNU Make, Poetry) is already present in the project. **Package Legitimacy Gate: N/A (no installs).**

## Runner CLI/Arg Surface (current state, exact)

Both runners currently have **no `argparse`** — they read env vars + run via `if __name__ == "__main__": main()`. This is the surface the `--json` / `--check` flags get added to.

### `perf/runners/run_w1_benchmark.py`
- **Entry:** `run_w1() -> dict[str, Any]`, called by `main()`.
- **Env overrides (already exist, lines 27–28):**
  - `W1_START_DATE` (default `"2025-12-24"` — **NOTE: this default is the full 180d range, NOT the frozen 2-month window**; D-07 requires changing this default to `"2026-04-23"`).
  - `W1_END_DATE` (default `"2026-06-23"` — already the frozen end).
- **Constants:** imports `CSV_PATHS, TIMEFRAME, wire_w1, W1Topology` from `perf.workloads.w1_topology`.
- **Measurement:** `tracemalloc.start()` → `t0 = time.perf_counter()` → `system.run(print_summary=False, on_tick=on_tick)` → `wall_clock_s = perf_counter()-t0` → `tracemalloc.get_traced_memory()` peak → `peak_mem_mb = peak_bytes/(1024*1024)`.
- **Prints:** a `===== W1 BENCHMARK RESULT =====` block: `wall_clock_s` (`.3f`), `peak_mem_mb` (`.2f`), a per-portfolio `fills / closed_positions` breakdown over labels `["P1_A","P2_B","P3_C","P4_D","P5_D","P6_D"]`, and `TOTAL fills` / `TOTAL closed_positions`.
- **Asserts:** `total_fills > 0` (a dead benchmark measures nothing).
- **Returns dict keys:** `wall_clock_s`, `peak_mem_mb`, `breakdown` (`{label: {fills, closed_positions}}`), `total_fills`, `total_closed_positions`.
- **Reproduce command (from results doc §1):** `W1_START_DATE=2026-04-23 W1_END_DATE=2026-06-23 poetry run python -m perf.runners.run_w1_benchmark`

**Gap vs D-01:** the current return dict carries NO `final_equity`. D-01 requires the oracle `final_equity` as on-contract provenance in the baseline file. **Important:** the W1 benchmark is the 4-strategy/6-portfolio coverage workload — it does NOT produce the SMA_MACD oracle `final_equity` (46189.87730727451). See Open Question OQ-1: the `final_equity` provenance field almost certainly means "record that the byte-exact oracle was green at freeze time" (a correctness stamp), not a value computed by the W1 runner. The planner must resolve whether the field stores the oracle's final_equity constant (provenance the freeze was on a correct engine) vs a W1-derived equity sum.

### `perf/runners/run_w2_sweep.py`
- **Entry:** `run_w2() -> list[dict[str, Any]]`, called by `main()`.
- **Constants (module-level, no env):** `_N_BARS=3000`, `_N_SYMBOLS_SWEEP=[1,10,50]`, `_SEED=42`, `_TIMEFRAME="5m"`.
- **Per-point dict keys:** `n_symbols`, `wall_clock_s`, `peak_mem_mb`.
- **Prints:** `===== W2 SCALING SWEEP =====` table `(n_symbols, wall_clock_s, peak_mem_mb)`.
- **Uses:** `make_synthetic_ohlcv` from `perf.workloads.synthetic`; writes temp kline CSVs; trivial `_TrivialBuyStrategy`.
- **`--json` for W2 (D-06):** emit the `list[dict]` of points (the scaling table) as JSON. W2 is NOT baseline-frozen or guard-gated (it has no committed reference and no ≥5% gate) — `--json` there is purely for machine-readable scaling output.

## W1-BASELINE.json Schema (proposed — D-01 / Claude's discretion)

Location: `perf/results/W1-BASELINE.json` (committed; sits beside `PERF-BASELINE-RESULTS.md`). Proposed exact field names (D-01 minimum + useful provenance):

```json
{
  "schema_version": 1,
  "frozen_at": "2026-06-23",
  "metric": {
    "wall_clock_s": 240.8,
    "peak_mem_mb": 167.3
  },
  "window": {
    "start_date": "2026-04-23",
    "end_date": "2026-06-23"
  },
  "workload": {
    "name": "W1",
    "topology": "4-strategy/6-portfolio (3 isolation + D 3-way fan-out)",
    "timeframe": "5m",
    "total_fills": 1578,
    "total_closed_positions": 659,
    "seed": 42
  },
  "oracle_provenance": {
    "test": "tests/integration/test_backtest_oracle.py",
    "trade_count": 134,
    "final_equity": "46189.87730727451",
    "green_at_freeze": true
  },
  "tooling": {
    "python": "3.13",
    "measurement": "time.perf_counter + tracemalloc peak"
  }
}
```

**Field rationale:**
- `metric.wall_clock_s` / `metric.peak_mem_mb` — D-01 minimum; what gate (b) diffs against.
- `window.{start,end}_date` — D-01 minimum + reproducibility; pins D-07.
- `oracle_provenance.final_equity` + `green_at_freeze` — D-01 minimum (the run was on-contract). `final_equity` kept as a **string** (Decimal-exact, the project's money discipline; never a float in JSON). See OQ-1.
- `frozen_at` — D-01 minimum (freeze date).
- `schema_version` — lets a later phase's compare logic detect/upgrade the format without guessing.
- `workload.total_fills` / `total_closed_positions` — non-trivial-trade-log provenance (the §1 numbers), so a future reader can confirm the freeze was on a live (not dead) benchmark.

## Soft Regression Guard (D-02 / D-04 — exact shape)

**Recommended location:** inside `run_w1_benchmark.py` as a `--check` compare-mode (single home; the JSON read/schema and the runner live together). The `perf-w1` target invokes this mode. (The alternative thin `perf-check` wrapper is allowed by D-02 discretion but duplicates JSON-load + schema knowledge — not recommended.)

**Behavior contract:**
1. Run the W1 benchmark once (single timed run, D-03).
2. Load `perf/results/W1-BASELINE.json`.
3. Compute and PRINT the delta:
   - `wall_clock_delta_pct = (current - baseline) / baseline * 100` (positive = slower = regression; negative = faster = improvement).
   - `peak_mem_delta_pct` likewise (reported, watched — **no fail threshold**, D-04: "no separate threshold for memory").
4. **Soft guard (fail) condition (D-04):** the guard protects the frozen number against *regression*. Gate (b) "measurable improvement" = ≥5% **faster**. The guard's job is the inverse: fail if the run is *slower* beyond the noise band.
   - Use a symmetric tolerance band of **5%** (D-04: noise is 1–2%, 5% is a confident real move). Recommended rule:
     - `wall_clock_delta_pct > +5.0` → **FAIL** (real slowdown — a regression the gate must catch). Exit non-zero.
     - `-5.0 <= wall_clock_delta_pct <= +5.0` → **PASS (within noise)**. Exit 0.
     - `wall_clock_delta_pct < -5.0` → **PASS (improvement)**. Exit 0. (Improvement is never a failure; an optimization phase WANTS this and then re-freezes.)
   - Peak memory: print delta, never fail (D-04).
5. **Failure-message contract** (proposed wording, discretion):
   ```
   PERF REGRESSION: W1 wall-clock 261.4s is +8.6% vs frozen baseline 240.8s
   (band ±5.0%). Frozen 2026-06-23, window 2026-04-23→2026-06-23.
   Investigate before merging; this guard protects gate (b). (peak_mem 171.2MB, +2.3%)
   ```
6. The guard is a **tooling assert, NOT the oracle** (D-02 / D-10): it does not run or import the byte-exact oracle. Correctness stays the separate `make test-integration` / oracle lock.

**Important nuance for the planner:** `perf-w1` should *always print the delta* (informational) and *only fail* on the >+5% slowdown. Distinguish "print delta" (every run) from "guard fails" (regression only). Do not make a within-noise run fail.

## Makefile Target Bodies (TOOL-01 — exact shape, matches `backtest:` idiom)

The root `Makefile` already has `include .env` / `.EXPORT_ALL_VARIABLES` (lines 1–3) and a `.PHONY` line (line 6) — add the four target names to `.PHONY` and append the targets. Existing idiom (from `backtest:`): `@echo "<emoji> <banner>..."` then `poetry run python …`. **Makefile recipe lines MUST be tab-indented** (Make hard requirement — not the project tab/space convention, a Make syntax rule).

Proposed bodies (using module invocation `-m perf.runners.…` to match the §1 reproduce command and keep imports absolute):

```make
# Performance harness (v1.5). perf/ lives outside shipped itrader/.
.PHONY: perf-w1 perf-w2 perf-baseline perf-profile

# Clean W1 benchmark + delta vs frozen baseline + soft regression guard (gate b).
# Default window pinned to the frozen 2-month slice (D-07); override with
#   make perf-w1 W1_START_DATE=… W1_END_DATE=…
perf-w1:
	@echo "⏱️  W1 benchmark + regression guard (vs frozen baseline)..."
	poetry run python -m perf.runners.run_w1_benchmark --check

# W2 synthetic scaling sweep {1,10,50} symbols (machine-readable with --json).
perf-w2:
	@echo "📈 W2 scaling sweep {1,10,50} symbols..."
	poetry run python -m perf.runners.run_w2_sweep

# RE-FREEZE the W1 baseline: clean run, write committed perf/results/W1-BASELINE.json.
# Run ONLY after TOOL-01..02 land and BEFORE any optimization (TOOL-04).
perf-baseline:
	@echo "🧊 Freezing W1 baseline → perf/results/W1-BASELINE.json..."
	poetry run python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json

# Scalene CPU profile → gitignored HTML (manual review). NEVER wraps the gated run.
# Two steps: run (writes JSON) then view --html (renders scalene-profile.html).
perf-profile:
	@echo "🔬 Scalene CPU profile (HTML, gitignored) — NOT the gated run..."
	poetry run python -m scalene run --cpu-only --program-path $(CURDIR) \
		-o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
	poetry run python -m scalene view --html perf/results/scalene-w1.json
	@echo "   → wrote scalene-profile.html (gitignored)"
```

Notes:
- `$(CURDIR)` is Make's built-in for the repo root (where `make` runs) — satisfies `--program-path <repo>`.
- `perf-w1` uses `--check` (compare mode); `perf-baseline` uses `--baseline-out` (freeze mode). These are the two new `argparse` flags on `run_w1_benchmark.py` (plus `--json` for raw emit per D-06).
- Window pinning (D-07): do NOT set `W1_START_DATE`/`W1_END_DATE` in the targets — instead change the runner's *default* (line 27) to `"2026-04-23"` so the pinned window applies by default and `make perf-w1 W1_START_DATE=2026-05-01` still overrides via the inherited `.EXPORT_ALL_VARIABLES` env.
- The existing `.PHONY` at line 6 of the Makefile lists the current targets; either extend it or add the dedicated `.PHONY` block shown above (both work; one block keeps perf targets grouped).

## Scalene Invocation (Critical Correction — TOOL-02)

**The single-command form in the spec does not exist in Scalene 2.3.0.** Verified via `poetry run python -m scalene run --help` / `--help-advanced` / `view --help` this session:

| Flag | Subcommand it belongs to | Verified |
|------|--------------------------|----------|
| `--cpu-only` | `scalene run` | ✓ `run --help` |
| `--program-path PROGRAM_PATH` | `scalene run` (advanced) | ✓ `run --help-advanced` |
| `--profile-all` | `scalene run` (advanced) | ✓ (the gotcha to AVOID — profiles Scalene's own thread; results doc §0.2) |
| `-o / --outfile OUTFILE` | `scalene run` (default `scalene-profile.json`) | ✓ |
| `--html` | **`scalene view`** — NOT `run` | ✓ `view --help` |
| `--standalone` | `scalene view` (single self-contained HTML, implies `--html`) | ✓ |

`scalene view --html` writes to the **fixed filename `scalene-profile.html`** (no `-o` path option on `view`). The `run` step's `-o` controls only the intermediate JSON.

**Correct two-step invocation (the realization of TOOL-02's intent):**
```bash
poetry run python -m scalene run --cpu-only --program-path "$(repo-root)" \
    -o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
poetry run python -m scalene view --html perf/results/scalene-w1.json   # → scalene-profile.html
```
- `--cpu-only` — required (memory profiler stalls on the Decimal/object-heavy workload; results §5).
- `--program-path "$(repo-root)"` — per-line profile of `itrader/` + `perf/`; the documented fix for the `--profile-all` thread-bucket gotcha (results §0.2). **Do NOT pass `--profile-all`.**
- `-m perf.runners.run_w1_benchmark` — profile the W1 runner as a module (absolute imports work; matches the harness convention).
- The HTML (`scalene-profile.html`) is the gitignored manual-review artifact.

**Profiling NEVER wraps the gated run:** `perf-w1` (the gate) calls the runner directly with NO Scalene; `perf-profile` is the *only* Scalene path. They are different Makefile targets — the separation is structural, satisfying TOOL-02. (Scalene's 2–5× overhead would destroy the gate; results doc + TOOL-02 both call this out.)

**Memory note:** memory is `tracemalloc` (already in the runners), NOT Scalene `--memory` — the Scalene memory profiler is unusable here (results §5). Do not add `--memory`/`--gpu`.

## .gitignore Entry (TOOL-02)

Current `.gitignore` ignores `htmlcov/` (line 46) and `output/` (line 35) but has NO perf-profile entry. Add an entry for the Scalene HTML artifact (and the intermediate JSON, which is also a throwaway profile not a committed result):

```gitignore
# Scalene perf profiles (manual-review artifacts — committed results live in perf/results/*.md + W1-BASELINE.json)
scalene-profile.html
perf/results/scalene-*.json
```

Caveats for the planner:
- `scalene view --html` writes `scalene-profile.html` to the **current working directory** (repo root when run via `make`), so the un-pathed `scalene-profile.html` entry is correct.
- Do NOT use a blanket `perf/results/*.html` if you intend the JSON beside it — explicitly ignore `perf/results/scalene-*.json` so the committed `W1-BASELINE.json` and `*.md` are NOT swept up (they must stay tracked). The two narrow lines above are safer than a wildcard.
- `perf/results/.gitkeep` already exists — the directory is tracked; only the named profile artifacts are ignored.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────────────────────┐
   make perf-w1 ───▶│ run_w1_benchmark.py --check               │
   (gate b)         │  1. run W1 (perf_counter + tracemalloc)   │──▶ stdout delta
                    │  2. load W1-BASELINE.json                  │     + PASS/FAIL
                    │  3. compute Δ%; FAIL if wall > +5%         │──▶ exit 0/non-0
                    └──────────────────────────────────────────┘
                                      ▲ reads
                                      │
   make perf-baseline ──▶ run_w1_benchmark.py --baseline-out ──▶ perf/results/W1-BASELINE.json
   (TOOL-04, run once)        (clean run, no profiler)            (COMMITTED reference)

   make perf-w2 ──────▶ run_w2_sweep.py [--json] ──▶ stdout scaling table / JSON
                                                      (no baseline, no guard)

   make perf-profile ─▶ scalene run --cpu-only --program-path . -o scalene-w1.json
                              │                                      (gitignored)
                              ▼
                        scalene view --html ──▶ scalene-profile.html (gitignored)
                        [SEPARATE target — never wraps the gated run]

   make test-integration ─▶ test_backtest_oracle.py ──▶ 134 trades / 46189.87730727451
   (gate a — UNCHANGED; correctness lock, separate from the perf guard)
```

### Recommended Project Structure (no new files except the committed JSON)
```
perf/
├── runners/
│   ├── run_w1_benchmark.py   # +argparse: --json / --check / --baseline-out
│   └── run_w2_sweep.py       # +argparse: --json
└── results/
    ├── PERF-BASELINE-RESULTS.md   # existing (source of truth, tracked)
    ├── W1-BASELINE.json           # NEW committed reference (TOOL-04)
    └── scalene-w1.json / scalene-profile.html  # gitignored profile artifacts
Makefile                       # +perf-w1 / perf-w2 / perf-baseline / perf-profile
.gitignore                     # +scalene-profile.html, perf/results/scalene-*.json
```

### Pattern 1: argparse over the existing `main()` (D-06)
**What:** Add `argparse` to each runner's `main()`; default behavior (no flags) keeps the current human-readable stdout (D-06 requirement: human summary stays the default).
**When to use:** All three modes of `run_w1_benchmark.py`.
**Example:**
```python
# Source: pattern for perf/runners/run_w1_benchmark.py (4-space indent — perf/ convention)
def main() -> None:
    parser = argparse.ArgumentParser(description="W1 realistic benchmark")
    parser.add_argument("--json", action="store_true",
                        help="emit the result dict as JSON (machine-readable)")
    parser.add_argument("--check", action="store_true",
                        help="compare vs W1-BASELINE.json; soft regression guard (gate b)")
    parser.add_argument("--baseline-out", metavar="PATH",
                        help="freeze: write the run as the committed baseline JSON")
    args = parser.parse_args()
    result = run_w1()                       # human stdout prints by default
    if args.json:
        print(json.dumps(_to_baseline_schema(result), indent=2))
    if args.baseline_out:
        _write_baseline(result, args.baseline_out)
    if args.check:
        sys.exit(_check_regression(result, "perf/results/W1-BASELINE.json"))
```

### Anti-Patterns to Avoid
- **Wrapping the gated run in Scalene** — destroys the wall-clock gate (2–5×). Profiling is a separate target only.
- **`--profile-all`** — dumps ~75% of samples into Scalene's own `Thread.run` bucket (results §0.2); the backtest is single-threaded. Use `--program-path` instead.
- **`--memory`/Scalene memory profiler** — stalls on the Decimal-heavy workload (results §5). Memory is tracemalloc.
- **Failing `perf-w1` on a within-noise run** — the guard must only fail on >+5% slowdown; a ±5% band run PASSES (D-03/D-04). Always print the delta; only fail on regression.
- **Float `final_equity` in the JSON** — the project is Decimal end-to-end; serialize the oracle equity as a string.
- **Editing engine code** — Phase 1 is tooling/measurement ONLY (success criterion 4).
- **Spaces in Makefile recipe indentation** — Make requires literal tabs in recipe lines (independent of the project's tab/space-by-file convention).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CPU profiling / HTML report | A custom sampler/aggregator | `scalene run` + `scalene view --html` | Already installed, already used in the spike; per-line attribution + flamegraph for free. |
| Peak-memory measurement | Manual `resource.getrusage` parsing | `tracemalloc` (already in the runners) | Cross-platform, per-allocation peak; the documented instrument (results §5). |
| Wall-clock timing | `time.time()` (wall-clock, NTP-skewable) | `time.perf_counter()` (already used) | Monotonic high-resolution; the correct timer for benchmarks. |
| CLI arg parsing | hand-rolled `sys.argv` slicing | `argparse` (stdlib) | The runners need only 3 flags; argparse gives `--help` + validation free. |
| Env-var override of window | new config plumbing | the existing `os.environ.get("W1_START_DATE", …)` (lines 27–28) | Already implemented; D-07 only changes the default value. |

**Key insight:** Phase 1 builds **zero** new measurement primitives — every instrument already exists in the harness or the toolchain. The work is wiring (Makefile targets), emit (`--json`), a thin compare (`--check`), one committed JSON, and one `.gitignore` line.

## Common Pitfalls

### Pitfall 1: `scalene run --html` won't parse
**What goes wrong:** Copying TOOL-02's literal `--cpu-only --html --program-path` into a `scalene run` invocation fails — `--html` is a `view` flag in 2.3.0.
**Why it happens:** The spec phrasing predates (or abstracts over) the `run`/`view` subcommand split; PERF-BASELINE-RESULTS.md §0 also writes it as one phrase.
**How to avoid:** Two-step `run` (→ JSON) then `view --html` (→ `scalene-profile.html`). See §"Scalene Invocation".
**Warning signs:** `scalene run: error: unrecognized arguments: --html`.

### Pitfall 2: Stale `W1_START_DATE` default masks D-07
**What goes wrong:** `run_w1_benchmark.py` line 27 defaults `W1_START_DATE` to `"2025-12-24"` (the full 180d range, ~240s would NOT be reproduced — that number is the 2-month slice). `make perf-w1` with no env would run the wrong window.
**Why it happens:** The frozen baseline window (`2026-04-23`) was set via env at spike time, not as the runner default.
**How to avoid:** D-07 explicitly requires changing the default to `"2026-04-23"`. Verify the start default is updated, not just the Makefile.
**Warning signs:** `perf-w1` wall-clock far from ~240.8s; window in printed output ≠ `2026-04-23→2026-06-23`.

### Pitfall 3: Guard fails on improvement or on noise
**What goes wrong:** A naive `abs(delta) > 5% → fail` would fail a legitimate optimization (which is *supposed* to be ≥5% faster) and could fail a 5.5% noise blip.
**Why it happens:** Conflating "measurable improvement" (gate b, wants faster) with "regression guard" (wants to catch slower).
**How to avoid:** Only `wall_clock_delta_pct > +5%` fails. Faster = pass. See §"Soft Regression Guard".
**Warning signs:** An optimization phase's `perf-w1` exits non-zero after a real speedup.

### Pitfall 4: Committed JSON swept by a broad gitignore
**What goes wrong:** A `perf/results/*.json` ignore line would un-track `W1-BASELINE.json` (the whole point of TOOL-04 is that it's committed).
**Why it happens:** Over-broad wildcard when adding the profile-JSON ignore.
**How to avoid:** Ignore the narrow `perf/results/scalene-*.json` prefix, never `perf/results/*.json`. Confirm `git status` shows `W1-BASELINE.json` as tracked after `perf-baseline`.
**Warning signs:** `git status --ignored` lists `W1-BASELINE.json`.

### Pitfall 5: tracemalloc undercounts native peak
**What goes wrong:** `tracemalloc` only tracks Python-level allocations; the 167.3 MB is the Python-object peak, not RSS. Comparing it loosely to OS memory tools will mismatch.
**Why it happens:** tracemalloc by design ignores C-extension/native allocations.
**How to avoid:** Treat `peak_mem_mb` as a *relative regression signal* (its only D-04 job — "watched for regression"), not an absolute RSS budget. The baseline-vs-baseline delta is apples-to-apples (same instrument).
**Warning signs:** Comparing `peak_mem_mb` to `/usr/bin/time -l` max RSS and concluding a "bug."

## Code Examples

### Compute + emit the soft-guard delta (in-runner `--check`)
```python
# Source: pattern for run_w1_benchmark.py (4-space indent, perf/ convention)
def _check_regression(result: dict, baseline_path: str, band_pct: float = 5.0) -> int:
    with open(baseline_path) as fh:
        base = json.load(fh)
    base_wall = base["metric"]["wall_clock_s"]
    base_mem = base["metric"]["peak_mem_mb"]
    wall = result["wall_clock_s"]
    mem = result["peak_mem_mb"]
    wall_d = (wall - base_wall) / base_wall * 100.0
    mem_d = (mem - base_mem) / base_mem * 100.0
    print(f"W1 wall_clock {wall:.1f}s  Δ {wall_d:+.1f}%  (baseline {base_wall:.1f}s)")
    print(f"W1 peak_mem  {mem:.1f}MB  Δ {mem_d:+.1f}%  (baseline {base_mem:.1f}MB, watched)")
    if wall_d > band_pct:                       # only a real SLOWDOWN fails (D-04)
        print(f"PERF REGRESSION: +{wall_d:.1f}% > band {band_pct:.1f}% — gate (b) guard FAILED")
        return 1
    return 0
```

### Freeze the baseline (`--baseline-out`)
```python
# Source: pattern for run_w1_benchmark.py
def _write_baseline(result: dict, out_path: str) -> None:
    payload = {
        "schema_version": 1,
        "frozen_at": dt.date.today().isoformat(),
        "metric": {"wall_clock_s": round(result["wall_clock_s"], 1),
                   "peak_mem_mb": round(result["peak_mem_mb"], 1)},
        "window": {"start_date": _START_DATE, "end_date": _END_DATE},
        "workload": {"name": "W1", "timeframe": TIMEFRAME, "seed": 42,
                     "total_fills": result["total_fills"],
                     "total_closed_positions": result["total_closed_positions"]},
        "oracle_provenance": {"test": "tests/integration/test_backtest_oracle.py",
                              "trade_count": 134,
                              "final_equity": "46189.87730727451",
                              "green_at_freeze": True},
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
```

### Verified Scalene two-step (TOOL-02)
```bash
# Source: poetry run python -m scalene {run,view} --help (VERIFIED this session, Scalene 2.3.0)
poetry run python -m scalene run --cpu-only --program-path "$PWD" \
    -o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
poetry run python -m scalene view --html perf/results/scalene-w1.json   # → scalene-profile.html
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `scalene run --html …` (single command) | `scalene run` (→ JSON) + `scalene view --html` (→ HTML) | Scalene 2.x subcommand split | The spec's literal one-command form must become two commands in `perf-profile`. **VERIFIED** this session. |
| `W1_START_DATE` default = full 180d range | Default pinned to `2026-04-23` (frozen 2-month window) | D-07 (this phase) | `make perf-w1` reproduces ~240.8s with no env vars. |

**Deprecated/outdated:**
- The `perf-crossval` target / backtesting.py + backtrader comparison runners (spike §13's "three-engine comparison" handoff item): **DROPPED** (D-05). Do not plan or implement. The freeze-baseline half of §13 stands.

## Runtime State Inventory

This is a tooling-addition phase, not a rename/refactor/migration. **Runtime State Inventory: N/A** — no stored data, live-service config, OS-registered state, secrets, or build artifacts carry a string being renamed. The only new committed artifact is `perf/results/W1-BASELINE.json` (created, not migrated). Verified: no engine code or data keys change (success criterion 4).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Scalene | `perf-profile` (TOOL-02) | ✓ | 2.3.0 (2026.05.08) — VERIFIED `poetry run scalene --version` | — |
| Poetry | all `perf-*` targets | ✓ | project-managed `.venv` | — |
| GNU Make | `perf-*` surface | ✓ | system | — |
| Python 3.13 + stdlib (`tracemalloc`, `time`, `json`, `argparse`) | runners | ✓ | 3.13.1 | — |
| Committed 5m CSVs (`data/{BTC,ETH,SOL,BNB}USDT_5m.csv`) | W1 runner | ✓ (per results §0: validated, 51,839 rows each) | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

**nyquist_validation: true** (config.json) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/integration/test_backtest_oracle.py -x` (gate a; module-scoped, slow ~minutes) |
| Full suite command | `make test` (`poetry run pytest tests/ -v`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| Gate (a) | Byte-exact SMA_MACD oracle green (134 / 46189.87730727451); no engine code changed | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| TOOL-01 | `perf-w1/w2/baseline/profile` targets exist and are invocable | smoke (manual/make) | `make -n perf-w1 && make -n perf-w2 && make -n perf-baseline && make -n perf-profile` (dry-run parses recipe) | ❌ Wave 0 (targets are the deliverable) |
| TOOL-01 | Targets inherit `.env` / export env | smoke | grep `Makefile` for `include .env` + `.EXPORT_ALL_VARIABLES` (already present) + the 4 target names | ✅ env idiom exists |
| TOOL-02 | Two-mode split: clean benchmark vs separate Scalene profile; profiling never wraps the gated run | smoke | `make -n perf-w1` shows NO `scalene`; `make -n perf-profile` shows `scalene run` + `scalene view --html`; they are distinct targets | ❌ Wave 0 |
| TOOL-02 | Scalene profile writes a gitignored HTML | smoke | `make perf-profile` → `scalene-profile.html` exists AND `git check-ignore scalene-profile.html` returns it | ❌ Wave 0 |
| TOOL-02 | `--json` keeps human stdout as default | unit/smoke | `poetry run python -m perf.runners.run_w1_benchmark --json` emits valid JSON; no flag → human block | ❌ Wave 0 |
| TOOL-04 | `W1-BASELINE.json` exists, committed, with required D-01 fields | smoke | `make perf-baseline` → `python -c "import json;d=json.load(open('perf/results/W1-BASELINE.json'));assert d['metric']['wall_clock_s'] and d['window'] and d['oracle_provenance']['final_equity'] and d['frozen_at']"` AND `git check-ignore perf/results/W1-BASELINE.json` returns nothing (tracked) | ❌ Wave 0 |
| TOOL-04 | `perf-w1` prints a delta vs baseline | smoke | `make perf-w1` stdout contains `Δ` / `baseline` and a wall-clock pct | ❌ Wave 0 |
| TOOL-04 | Soft guard FAILS on injected slowdown (≥5%) | smoke (negative) | inject ~10% sleep into the runner OR temporarily lower the baseline `wall_clock_s` ~20%, run `make perf-w1`, assert non-zero exit + `PERF REGRESSION`; revert | ❌ Wave 0 |
| TOOL-04 | Soft guard PASSES within noise / on improvement | smoke (positive) | re-run `make perf-w1` against the true baseline → exit 0 | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/integration/test_backtest_oracle.py -x` (gate a — must stay green every commit that touches anything importable; cheap relative to the perf runs).
- **Per wave merge:** the relevant smoke checks above (`make -n perf-*`, JSON-field assert, injected-slowdown guard test) + gate (a).
- **Phase gate:** gate (a) green; all four `perf-*` targets invocable; `W1-BASELINE.json` committed with D-01 fields; injected-slowdown guard fails; profile writes a gitignored HTML and `perf-w1` carries no `scalene`.

### Wave 0 Gaps
- [ ] No automated test asserts Makefile-target existence — use `make -n perf-<t>` dry-run smoke checks (no new pytest file strictly required; a tiny `tests/integration/test_perf_harness.py` smoke could assert the four targets parse and `W1-BASELINE.json` has the required keys, if the planner wants it gated in CI).
- [ ] No test exercises the `--json` / `--check` / `--baseline-out` flag surface — add lightweight assertions (subprocess `make -n` or direct `argparse` import) if the planner wants regression protection on the tooling itself.
- [ ] The injected-slowdown guard verification is a **manual/scripted negative test** (inject delay → expect non-zero exit → revert) — document the exact procedure in the plan's verification steps; it is the proof that the guard actually guards.
- Framework install: none needed (pytest present).

*(Note: gate (a)'s oracle test already exists and is the dominant correctness check. The Wave 0 gaps are all about the new tooling surface, which is verifiable by smoke/dry-run rather than heavy unit tests — appropriate for a measurement harness.)*

## Security Domain

`security_enforcement` is **absent from config.json** (treated as enabled by default). However, this phase has **no security-relevant surface**: it adds Makefile targets and stdlib-based measurement to an out-of-package eval harness. No authentication, session, access control, cryptography, network input, untrusted data, or secrets handling is introduced or touched.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no (the only inputs are `argparse` flags + env dates the developer sets; no untrusted input) | argparse type/choice validation if dates are parsed |
| V6 Cryptography | no | — |

**Known threat patterns for this stack:** none materially applicable. The only adjacent note: the Scalene HTML/JSON profiles are gitignored so no profiling artifact (which can embed source-line snippets) is accidentally committed — handled by the `.gitignore` entry. No STRIDE category is opened by this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The D-01 `oracle final_equity` provenance field stores the **oracle's** constant (`46189.87730727451` as a correctness stamp), NOT a value the W1 coverage runner computes (W1 is the 4-strat/6-portfolio workload, not the SMA_MACD oracle). | W1-BASELINE.json Schema; OQ-1 | If the field is meant to be W1-derived, the schema's `oracle_provenance.final_equity` is mislabeled. Low risk — D-01 says "provenance that the run was on-contract," which reads as a correctness stamp. Planner should confirm with owner. |
| A2 | `$(CURDIR)` (Make built-in) is an acceptable `--program-path <repo>` value (the repo root where `make` runs). | Makefile Target Bodies | Low — `$(CURDIR)` is the standard Make idiom for the invocation directory; matches the spike's `<repo>` intent. |
| A3 | The soft-guard tolerance band is symmetric at 5% with only the +slowdown side failing. D-04 fixes ≥5% as the *improvement* bar; the *regression* band reusing the same 5% is the natural mirror but not explicitly stated. | Soft Regression Guard | Low-Medium — the band width is the one number the planner could tune; D-04's "noise 1–2%" justifies 5%. Owner could prefer a tighter regression band (e.g. +3%). Flag for plan-time confirmation. |
| A4 | `scalene view --html` writes `scalene-profile.html` to the CWD (repo root via make), so the un-pathed `.gitignore` line is correct. | .gitignore Entry; Scalene Invocation | Low — verified `view --help` shows the fixed filename; CWD behavior is the documented default. If a future Scalene version adds an output path, revisit. |

## Open Questions

1. **OQ-1: `final_equity` provenance — oracle constant vs W1-derived value?** (A1)
   - What we know: D-01 requires "the oracle `final_equity` (provenance that the run was on-contract)" in the baseline file. The W1 coverage runner does NOT run SMA_MACD and does not produce that number.
   - What's unclear: whether the field stores the fixed oracle constant `46189.87730727451` (a "the engine was correct when frozen" stamp) or some W1 equity quantity.
   - Recommendation: store the **oracle constant as a string** plus `green_at_freeze: true` (the freeze task runs `make test-integration` / the oracle and records that it passed). This satisfies "on-contract provenance" literally. Confirm with owner at plan time; low-risk either way.

2. **OQ-2: Optional `tests/integration/test_perf_harness.py` smoke test?**
   - What we know: TOOL-01/02/04 are verifiable by `make -n` dry-runs + JSON-field asserts; no pytest file is strictly required.
   - What's unclear: whether the planner wants the tooling surface itself regression-locked in CI (so a future edit can't silently break a `perf-*` target).
   - Recommendation: a tiny smoke test (4 targets parse via `make -n`; `W1-BASELINE.json` has the D-01 keys) is cheap insurance and would make gate verification automated rather than manual. Planner's call; not required by the success criteria.

3. **OQ-3: Run order of the freeze (TOOL-04) relative to the other tasks.**
   - What we know: TOOL-04 says re-freeze AFTER TOOL-01..02 land and BEFORE any optimization.
   - What's unclear: nothing material — but the plan must sequence `perf-baseline` (write `W1-BASELINE.json`) as the **last** task of this phase, after the Makefile + runner flags exist and gate (a) is confirmed green, since the guard mode (`perf-w1 --check`) needs the JSON to exist.
   - Recommendation: order = (1) runner flags `--json`/`--check`/`--baseline-out` + D-07 default; (2) Makefile targets; (3) `.gitignore`; (4) confirm gate (a) green; (5) `make perf-baseline` → commit `W1-BASELINE.json`; (6) verify `make perf-w1` prints delta + guard passes, and an injected slowdown fails.

## Sources

### Primary (HIGH confidence — on-disk + tool-verified this session)
- `perf/runners/run_w1_benchmark.py`, `perf/runners/run_w2_sweep.py`, `perf/workloads/w1_topology.py`, `perf/README.md` — exact current runner surface, env overrides, measurement, return dicts.
- `perf/results/PERF-BASELINE-RESULTS.md` — §0 (Scalene invocation + two gotchas), §1 (frozen 240.8s/167.3MB, window, 1578 fills/659 closed), §2 (hotspot map), §3 (scaling), §5 (tracemalloc-vs-Scalene-memory), §6 (phase breakdown).
- `tests/integration/test_backtest_oracle.py` — gate (a) mechanics (134 / 46189.87730727451; exact frame compare).
- `Makefile` (lines 1–6, `backtest:` target) — `include .env` / `.EXPORT_ALL_VARIABLES` idiom + `@echo`/`poetry run` target shape.
- `.gitignore` — current ignores (`htmlcov/`, `output/`); no perf-profile entry yet.
- `poetry run scalene --version` → **Scalene 2.3.0 (2026.05.08)** [VERIFIED]; `pyproject.toml` `scalene = "^2.3.0"` [VERIFIED].
- `poetry run python -m scalene run --help` / `--help-advanced` / `view --help` — **subcommand split: `--cpu-only`/`--program-path`/`--profile-all`/`-o` on `run`; `--html`/`--standalone` on `view`** [VERIFIED this session].
- `.planning/config.json` — `nyquist_validation: true`, `security_enforcement` absent, `brave_search`/`exa_search` false [VERIFIED].
- CONTEXT.md (D-01..D-07), REQUIREMENTS.md (TOOL-01/02/04, TOOL-03 dropped), ROADMAP.md Phase 1 success criteria, `.planning/spikes/PERF-BASELINE.md` §13 handoff.

### Secondary (MEDIUM confidence)
- (none — everything material was tool-verified or read on disk)

### Tertiary (LOW confidence)
- (none)

## Metadata

**Confidence breakdown:**
- Runner CLI surface + measurement: HIGH — read the files line by line.
- Makefile idiom + targets: HIGH — read the existing `backtest:` target and env idiom.
- Scalene invocation: HIGH — flags verified directly against the installed 2.3.0 CLI (and corrected the spec's literal single-command form).
- JSON schema / guard shape: MEDIUM-HIGH — D-01/D-02/D-04 fix the contract; exact field names + band are Claude's discretion (flagged in Assumptions A1/A3, OQ-1).
- Baseline numbers (240.8s/167.3MB/1578 fills): HIGH — from the committed results doc; the re-freeze will produce the authoritative committed value.

**Research date:** 2026-06-23
**Valid until:** ~30 days (stable; only Scalene's CLI could shift on a minor bump — re-verify `scalene run/view --help` if the version changes).
