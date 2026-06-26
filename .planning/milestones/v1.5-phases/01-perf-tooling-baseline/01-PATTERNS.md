# Phase 1: Perf Tooling & Baseline - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 5 (2 modified runners, 1 modified Makefile, 1 modified .gitignore, 1 new JSON artifact)
**Analogs found:** 5 / 5 (all exact — this is a brownfield extension of an existing harness)

> Brownfield note: every file in this phase already exists or sits beside an exact sibling.
> There are no green-field files and no "no analog" rows. The analog for each new behavior is the
> file's OWN existing code (the runners), the same-Makefile `backtest:` target, or the existing
> `perf/results/` + `htmlcov/` conventions.

> **Indentation hazard (two distinct rules in play):**
> - Root `Makefile` recipe lines MUST use **literal tabs** — this is a GNU Make syntax requirement,
>   not the project tab/space-by-file convention. Spaces in a recipe line break the target.
> - `perf/` Python uses **4 spaces** (perf/ lives OUTSIDE shipped `itrader/`; confirmed in both
>   runners). Do NOT use the handler-module tab convention here.

## File Classification

| File | New/Modified | Role | Data Flow | Closest Analog | Match Quality |
|------|--------------|------|-----------|----------------|---------------|
| `Makefile` (`perf-w1/w2/baseline/profile` targets) | modified | config / build-orchestration | request-response (shell-out) | `Makefile::backtest:` (same file) | exact |
| `perf/runners/run_w1_benchmark.py` (`--json`/`--check`/`--baseline-out`) | modified | utility / runner | transform + file-I/O | its own existing `run_w1()` / `main()` | exact (self) |
| `perf/runners/run_w2_sweep.py` (`--json`) | modified | utility / runner | transform | its own existing `run_w2()` / `main()` + `run_w1` argparse | exact (self) |
| `perf/results/W1-BASELINE.json` | new (committed) | config / data artifact | file-I/O (write-once, read-many) | `perf/results/PERF-BASELINE-RESULTS.md` (location/convention) | exact (sibling) |
| `.gitignore` (Scalene HTML/JSON entries) | modified | config | n/a | `.gitignore` `htmlcov/` line 45 | exact (sibling line) |

## Pattern Assignments

### `Makefile` — `perf-w1` / `perf-w2` / `perf-baseline` / `perf-profile` (config, request-response)

**Analog:** `Makefile::backtest:` (lines 78-86, same file). Env idiom already present at lines 1-3.

**Env inheritance pattern** (lines 1-3) — already in file, perf targets inherit it for free, NO work:
```make
# Load .env file contents
include .env
.EXPORT_ALL_VARIABLES:
```
This is why D-07's `W1_START_DATE`/`W1_END_DATE` overrides flow through automatically: `make perf-w1 W1_START_DATE=2026-05-01` exports the var into the `poetry run` subprocess via `.EXPORT_ALL_VARIABLES`. The targets therefore do NOT set the window themselves — they rely on the runner's pinned default (see runner section).

**`.PHONY` pattern** (line 6) — append the four new names, or add a grouped `.PHONY` block:
```make
.PHONY: init-env clean test test-unit test-integration test-e2e test-cov backtest normalize-data precommit typecheck
```

**Target body idiom** (lines 78-81, the `backtest:` target — copy this exact shape: comment + `@echo "<emoji> <banner>..."` + tab-indented `poetry run python ...`):
```make
# Generate the deterministic backtest oracle (output/{trades,equity}.csv + summary.json)
backtest:
	@echo "🚀 Running backtest oracle generator..."
	poetry run python scripts/run_backtest.py
```

**Apply to the four perf targets** (recipe lines are LITERAL TABS; module invocation `-m perf.runners.…` keeps imports absolute, matching the §1 reproduce command):
```make
# Performance harness (v1.5). perf/ lives outside shipped itrader/.
.PHONY: perf-w1 perf-w2 perf-baseline perf-profile

perf-w1:
	@echo "⏱️  W1 benchmark + regression guard (vs frozen baseline)..."
	poetry run python -m perf.runners.run_w1_benchmark --check

perf-w2:
	@echo "📈 W2 scaling sweep {1,10,50} symbols..."
	poetry run python -m perf.runners.run_w2_sweep

perf-baseline:
	@echo "🧊 Freezing W1 baseline → perf/results/W1-BASELINE.json..."
	poetry run python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json

perf-profile:
	@echo "🔬 Scalene CPU profile (HTML, gitignored) — NOT the gated run..."
	poetry run python -m scalene run --cpu-only --program-path $(CURDIR) \
		-o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
	poetry run python -m scalene view --html perf/results/scalene-w1.json
	@echo "   → wrote scalene-profile.html (gitignored)"
```
Note: `$(CURDIR)` is Make's built-in for the repo root, satisfying `--program-path <repo>`. The Scalene command is TWO steps (`run` writes JSON, `view --html` renders) — the single-command `scalene run --html` does NOT parse in Scalene 2.3.0 (RESEARCH "Scalene Invocation"). `perf-profile` carries Scalene; `perf-w1` MUST NOT (TOOL-02 structural separation).

---

### `perf/runners/run_w1_benchmark.py` — add `--json` / `--check` / `--baseline-out` (utility, transform + file-I/O)

**Analog:** the file's OWN existing code. 4-space indent throughout; absolute imports (`from itrader.…`, `from perf.workloads.…`); stdlib `import os/time/tracemalloc`.

**Import pattern** (lines 12-21) — extend with stdlib `argparse`, `json`, `sys`, `datetime as dt`; keep the existing absolute-import shape:
```python
import os
import time
import tracemalloc
from decimal import Decimal
from typing import Any

from itrader.core.enums import OrderStatus, OrderType
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

from perf.workloads.w1_topology import CSV_PATHS, TIMEFRAME, wire_w1, W1Topology
```

**Env-default pattern — D-07 change point** (lines 27-28). Change ONLY the `_START_DATE` default value from `"2025-12-24"` to `"2026-04-23"`; leave the `os.environ.get(...)` override mechanism intact (Pitfall 2):
```python
_START_DATE = os.environ.get("W1_START_DATE", "2025-12-24")   # → "2026-04-23"
_END_DATE = os.environ.get("W1_END_DATE", "2026-06-23")
```

**Measurement pattern** (lines 101-107) — already complete; the new flags consume `run_w1()`'s return dict, they do NOT re-author this block:
```python
    tracemalloc.start()
    t0 = time.perf_counter()
    system.run(print_summary=False, on_tick=on_tick)
    wall_clock_s = time.perf_counter() - t0
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = peak_bytes / (1024 * 1024)
```

**Return-dict pattern** (lines 136-142) — the surface the new code reads. Note it carries NO `final_equity` (OQ-1: the freeze stores the oracle CONSTANT as a string, not a W1-derived value):
```python
    return {
        "wall_clock_s": wall_clock_s,
        "peak_mem_mb": peak_mem_mb,
        "breakdown": breakdown,
        "total_fills": total_fills,
        "total_closed_positions": total_closed,
    }
```

**`main()` argparse pattern** (current `main()` is lines 145-150 — a bare `run_w1()`). Replace with argparse; default (no flag) keeps the human stdout from `run_w1()` (D-06). Match RESEARCH "Pattern 1":
```python
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

**Soft-guard helper** (NEW; D-02/D-04 — only a >+5% SLOWDOWN fails, faster always passes, memory printed-never-failed; Pitfall 3):
```python
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

**Baseline-freeze helper** (NEW; D-01 schema; `final_equity` is a STRING, never a float — money discipline):
```python
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

---

### `perf/runners/run_w2_sweep.py` — add `--json` (utility, transform)

**Analog:** the `run_w1_benchmark.py` argparse pattern above (same author, same conventions) + this file's own `run_w2()`. W2 is NOT baseline-frozen and NOT guard-gated — `--json` here is machine-readable scaling output only (no `--check`, no `--baseline-out`).

**Existing `main()`** (lines 149-150) — bare `run_w2()`; add argparse with a single `--json` flag:
```python
def main() -> None:
    run_w2()
```

**Return surface to serialize** (`run_w2()` returns `list[dict]`, lines 130-146; per-point keys at lines 123-127):
```python
    return {
        "n_symbols": n_symbols,
        "wall_clock_s": wall_clock_s,
        "peak_mem_mb": peak_mem_mb,
    }
```
`--json` emits the `list[dict]` scaling table (e.g. `print(json.dumps(points, indent=2))`), keeping the human `===== W2 SCALING SWEEP =====` table (lines 139-145) as the default.

---

### `perf/results/W1-BASELINE.json` — new committed reference artifact (config, file-I/O)

**Analog:** `perf/results/PERF-BASELINE-RESULTS.md` — same directory, same "committed source-of-truth that sits in `perf/results/`" convention. `perf/results/.gitkeep` already tracks the dir. This file is WRITTEN by `perf-baseline` (`_write_baseline` above), never hand-authored. It is the only NEW file in the phase.

**Schema** (D-01 minimum + provenance) — produced by `_write_baseline`:
```json
{
  "schema_version": 1,
  "frozen_at": "2026-06-23",
  "metric": { "wall_clock_s": 240.8, "peak_mem_mb": 167.3 },
  "window": { "start_date": "2026-04-23", "end_date": "2026-06-23" },
  "workload": { "name": "W1", "timeframe": "5m", "seed": 42,
                "total_fills": 1578, "total_closed_positions": 659 },
  "oracle_provenance": { "test": "tests/integration/test_backtest_oracle.py",
                         "trade_count": 134,
                         "final_equity": "46189.87730727451",
                         "green_at_freeze": true }
}
```
MUST stay tracked: confirm `git check-ignore perf/results/W1-BASELINE.json` returns NOTHING after freeze (Pitfall 4).

---

### `.gitignore` — Scalene HTML/JSON entries (config)

**Analog:** the existing `htmlcov/` ignore (line 45, under the `#coverage report` header, lines 43-45) — a throwaway local-artifact ignore that keeps committed results tracked:
```gitignore
#coverage report
.coverage
htmlcov/
```

**Apply** (mirror the commented-header + narrow-entry shape; use NARROW lines, never `perf/results/*.json` which would sweep the committed `W1-BASELINE.json` — Pitfall 4):
```gitignore
# Scalene perf profiles (manual-review artifacts — committed results live in perf/results/*.md + W1-BASELINE.json)
scalene-profile.html
perf/results/scalene-*.json
```
`scalene view --html` writes `scalene-profile.html` to the CWD (repo root via `make`), so the un-pathed entry is correct. The intermediate `perf/results/scalene-w1.json` is also a throwaway — ignored via the narrow `scalene-*` prefix.

## Shared Patterns

### Tab vs space (cross-cutting — TWO separate rules)
**Source:** `Makefile` (recipe lines = literal tabs) vs `perf/runners/*.py` (4 spaces).
**Apply to:** Makefile target work = tabs (Make syntax); all perf/ Python = 4 spaces.
Never normalize. A space-indented Makefile recipe silently breaks the target; a tab in perf/ Python breaks the 4-space file.

### Stdlib-only measurement (no new deps)
**Source:** both runners — `tracemalloc` (peak mem), `time.perf_counter` (wall clock), plus new `json`/`argparse`/`sys`/`datetime`.
**Apply to:** both runner edits. Build ZERO new measurement primitives (RESEARCH "Don't Hand-Roll"). Scalene is already in `pyproject.toml` (`scalene = "^2.3.0"`).

### Money-as-string at the JSON edge
**Source:** project money discipline (CLAUDE.md) + RESEARCH anti-patterns.
**Apply to:** `_write_baseline` / `W1-BASELINE.json`. `final_equity` is serialized as a STRING (`"46189.87730727451"`), never a JSON float. Decimal-exact, no binary-float artifact.

### Absolute-import / module-invocation convention
**Source:** both runners (`from perf.workloads.… import …`) + the `-m perf.runners.…` Makefile invocation.
**Apply to:** all targets and runner edits. perf/ lives OUTSIDE shipped `itrader/`; absolute imports + `python -m` keep it importable as a package.

### Default-then-env-override (D-07)
**Source:** `run_w1_benchmark.py` lines 27-28 (`os.environ.get("W1_START_DATE", default)`) + Makefile `.EXPORT_ALL_VARIABLES` (line 3).
**Apply to:** the window pin. Change only the runner's `_START_DATE` default to `"2026-04-23"`; do NOT set the env vars in the Makefile targets, so the pinned default applies by default and `make perf-w1 W1_START_DATE=…` still overrides.

## No Analog Found

None. Every file is a modification of an existing file or a committed data artifact written into the existing `perf/results/` directory beside `PERF-BASELINE-RESULTS.md`. This is a pure brownfield tooling extension.

## Metadata

**Analog search scope:** `Makefile` (root), `perf/runners/`, `perf/results/`, `.gitignore`
**Files scanned:** 5 (Makefile, run_w1_benchmark.py, run_w2_sweep.py, .gitignore, perf/results/ dir listing)
**Pattern extraction date:** 2026-06-23
