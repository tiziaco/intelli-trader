# Spike Manifest

## Idea

Produce a **frozen performance baseline** and a **ranked hotspot map** of the iTrader
backtest engine so the upcoming performance milestone can be planned as surgical,
*measured* phases rather than ad-hoc profile-then-fix. Full spec:
`.planning/spikes/PERF-BASELINE.md`. The spec runs as two GSD vehicles — Step 1
(build the durable `perf/` harness, via `/gsd:quick`) is **done**; this spike is
**Step 2** (profile + freeze the baseline).

## Requirements

Non-negotiable constraints carried from the spec into the real build:

- **Money is Decimal end-to-end (LOCKED).** Frame Decimal hotspots as *redundant work /
  over-quantization / repeated conversion* — never *"switch to float."*
- **Findings only — no engine code changes in this spike.** Optimization is the
  follow-on milestone, gated on (a) oracle stays byte-exact green, (b) benchmark shows
  measurable improvement.
- **Determinism: seed 42 throughout.** Every profiling run is reproducible.
- **Framework-CPU hotspots are expected from the matching engine + bar feed**, not from
  strategy compute (D's signal is deliberately cheap).
- **The byte-exact correctness oracle (`tests/integration/test_backtest_oracle.py`)
  stays untouched.** Performance is a separate, trend-tracked concern, not a pass/fail gate.

## Spikes

| #   | Name | Type | Validates | Verdict | Tags |
|-----|------|------|-----------|---------|------|
| 001 | perf-baseline-profiling | standard | Given the durable `perf/` harness, when W1 + W2 are profiled with Scalene (seed 42), then a frozen baseline + ranked hotspot map + symbol-scaling curve are produced to feed `/gsd:new-milestone` | **VALIDATED** ✓ | perf, profiling, scalene, baseline |

## Findings (Spike 001)

- **Frozen W1 baseline:** 240.8 s / 167.3 MB (2-month slice, 4 strat / 6 pf, 1578 fills). Deliverable: `perf/results/PERF-BASELINE-RESULTS.md`.
- **Top hotspots:** order-storage linear scan (~37%), indicator full-window recompute (~24%, oracle-gated), closed-position PnL re-sum (~13%), hot-path logging (~6–22%), bar-feed window copy (~4–22%), `get_type_hints`/signal (~2–14%).
- **Scaling:** clean **O(n)** in symbol count — **no super-linear / O(n²)**.
- **Surprise:** the **matching engine is not a top-10 hotspot** (spec hypothesized it would be); cost is storage/bookkeeping/indicator recompute.
- **Tooling:** Scalene memory profiler unusable on this Decimal-allocation-heavy workload → tracemalloc for the memory baseline; `--program-path` (not `--profile-all`) to avoid Scalene self-profiling its own thread.
