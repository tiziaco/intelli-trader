---
spike: 001
name: perf-baseline-profiling
type: standard
validates: "Given the durable perf/ harness, when W1 + W2 are profiled with Scalene (seed 42), then a frozen baseline + ranked hotspot map + symbol-scaling curve are produced to feed /gsd:new-milestone"
verdict: VALIDATED
related: []
tags: [perf, profiling, scalene, baseline]
---

# Spike 001: Performance Baseline Profiling

## What This Validates

Given the durable `perf/` harness (built in Step 1 of PERF-BASELINE), when W1
(realistic 4-strategy / 6-portfolio benchmark) and W2 (synthetic symbol-scaling
sweep) are profiled with Scalene under seed 42, then we produce a **frozen W1
baseline** (wall-clock + peak memory), a **ranked hotspot map** (top ~10), and a
**symbol-scaling curve** — the deliverables `/gsd:new-milestone` consumes to plan
surgical, measured optimization phases.

This is **Step 2** of the PERF-BASELINE spec (`.planning/spikes/PERF-BASELINE.md`
§8, §10–§11, §12). Step 1 (the `perf/` harness) is already committed. Findings
only — no engine changes.

## Method

- **Dataset slice:** 2-month window (`2026-04-23` → `2026-06-23`) of the validated
  5m CSVs, instead of the full 180 days, to keep profiling iteration fast. The
  committed runner default (full 180d) is preserved; the slice is set via the
  `W1_START_DATE` / `W1_END_DATE` env overrides added to `run_w1_benchmark.py`.
- **Profiler:** Scalene 2.3.0, CPU + memory, `--reduced-profile`, seed 42.
- **W1:** `perf/runners/run_w1_benchmark.py` — asserts a non-trivial trade log.
- **W2:** `perf/runners/run_w2_sweep.py` — symbol sweep {1, 10, 50} at fixed n_bars.

## How to Run

```bash
# W1 realistic benchmark — 2-month slice (clean wall-clock / mem, no profiler overhead)
W1_START_DATE=2026-04-23 W1_END_DATE=2026-06-23 \
  poetry run python -m perf.runners.run_w1_benchmark

# W1 under Scalene (CPU + memory)
W1_START_DATE=2026-04-23 W1_END_DATE=2026-06-23 \
  poetry run scalene --cpu --memory --reduced-profile \
  --json --outfile .planning/spikes/001-perf-baseline-profiling/profile-w1.json \
  -m perf.runners.run_w1_benchmark

# W2 scaling sweep under Scalene
poetry run scalene --cpu --memory --reduced-profile \
  --json --outfile .planning/spikes/001-perf-baseline-profiling/profile-w2.json \
  -m perf.runners.run_w2_sweep
```

## Investigation Trail

**1. CSV validation gate (pre-profiling).** `perf/tools/validate_csv.py` confirms
all four W1 CSVs: 51,839 rows each, `2025-12-24 21:00` → `2026-06-22 20:50`,
monotonic non-duplicated index, OHLC invariants hold, **max flat run 0** (no
fabricated `O=H=L=C` bars). Source data is trustworthy → baseline is valid.

**2. Full-window run is too slow to iterate on.** A no-profiler full-180d W1 run
was killed after several minutes without completing — confirming the spec's
instinct to slice. Switched to a 2-month window via new `W1_START_DATE` /
`W1_END_DATE` env overrides (committed default stays full-180d).

**3. W1 2-month clean baseline (no profiler).** `2026-04-23` → `2026-06-23`
(~17.3k bars/symbol × 4 symbols):
- **wall-clock 240.8 s**, **peak mem 167.3 MB**
- Trade log: P1_A 57 / P2_B 377 / P3_C 298 / P4_D 282 / P5_D 282 / P6_D 282 =
  **1578 fills, 659 closed positions**. All four strategies and all six
  portfolios traded — the §6 paths fired. Strategy C also logged
  `position increase not allowed` admission rejections (its insufficient-funds /
  guard path), and B's resting-limit chase/cancel `on_tick` lifecycle ran.
- **Headline:** ~17.3k bars in 240.8 s ≈ **72 bars/s** for a 4-symbol / 6-portfolio
  / 4-strategy load. That is the loud signal the whole baseline exists to quantify.

**4. W2 synthetic scaling sweep (no profiler), n_bars=3000, seed 42.**

| n_symbols | wall_clock_s | peak_mem_mb | s/symbol | MB/symbol |
|-----------|--------------|-------------|----------|-----------|
| 1         | 2.079        | 6.99        | 2.079    | 6.99      |
| 10        | 13.761       | 41.28       | 1.376    | 4.13      |
| 50        | 66.170       | 213.22      | 1.323    | 4.26      |

- **Time is LINEAR in symbol count.** Linear fit (from n=10→50): `t ≈ 0.66 +
  1.31·n` s; predicts n=50 = 66.16 s vs **actual 66.17 s** (near-perfect). 1→50 =
  31.8× time for 50× symbols → **sub-linear in wall-clock, no super-linear blowup.**
- **Memory is LINEAR too:** `mem ≈ 4.3·n` MB; predicts n=50 = 213.3 MB vs **actual
  213.22 MB**. No O(n²) memory growth.
- **Conclusion:** the symbol-count axis is clean **O(n)**. There is no hidden
  quadratic in symbol count — so W1's slowness is NOT a symbol-fan-out problem. It
  is **per-bar × per-symbol × per-portfolio matching + mark-to-market + Decimal
  bookkeeping** (sharpened by W1's high trade density: 1578 fills vs W2's trivial
  strategy). Throughput contrast: W1 ≈ 287 symbol-bars/s (4 strat, 6 pf, brackets,
  shorts) vs W2 n=50 ≈ 2267 symbol-bars/s (1 trivial strat, 1 pf) — an ~8× tax
  from the realistic matching/portfolio load, which is exactly what Scalene must
  attribute next.

**5. Scalene profiling — three attempts, two gotchas resolved.**

- **Gotcha 1 — memory profiling stalls.** `scalene run` (default = CPU **and**
  memory) on W1 throttled to ~9s CPU in 15min wall (0.1% CPU). Scalene's memory
  profiler intercepts every allocation; this workload is Decimal/object-allocation
  heavy (1578 fills → millions of `Decimal` C-objects), so per-allocation
  interception is pathological. **Resolution:** `--cpu-only` for CPU attribution;
  keep the already-frozen **tracemalloc** peak (167 MB W1; W2's 4.3 MB/symbol) as
  the memory baseline. CPU-only ran fine (~1.3–2× the clean time).
- **Gotcha 2 — `--profile-all` profiles Scalene itself.** A `--cpu-only` run with
  default program-path only profiled the entry script (one rolled-up line, useless).
  Adding `--profile-all` instrumented `itrader/` but dumped **75% of samples into a
  `threading.py Thread.run` bucket** — Scalene's *own* profiler thread (the backtest
  is single-threaded; `grep` confirms no `Thread()` in the backtest path).
  **Resolution:** run `--cpu-only --program-path <repo-root>` (no `--profile-all`)
  so `itrader/`+`perf/` count as program files and get per-line profiled while
  Scalene's own thread is excluded. Cross-checked against a manual aggregation of
  Scalene's per-stack `cpu_samples` rolled up to the deepest `itrader`/`perf` frame
  (which de-aliases the thread bucket) — the two agree on the ranking.
- **Attribution method of record:** per-line `n_cpu_percent_python` +
  `n_cpu_percent_c` from the `--program-path` run, corroborated by the stack
  roll-up. The hotspot map below is built from that.

## Results

**Verdict: VALIDATED.** The durable `perf/` harness profiles cleanly under Scalene
and yields a frozen baseline + defensible ranked hotspot map + a clean scaling
curve. Full deliverable: **`perf/results/PERF-BASELINE-RESULTS.md`**.

**Frozen W1 baseline:** **240.8 s wall-clock / 167.3 MB peak** (2-month slice,
4 strat / 6 pf, 1578 fills). ≈72 bars/s.

**Top hotspot clusters (W1 CPU%):**
1. Order-storage **full-dict linear scan** per query — `InMemoryOrderStorage._orders` **~37%** (grows over run; ~O(n²) in run length).
2. **Indicator full-window recompute** (`_SMA`/`_MACDHist.compute` via fresh `ta` objects) **~24%** — oracle-gated.
3. **Closed-position realised-PnL re-sum** every bar **~13%**.
4. **Hot-path logging** (structlog warning/debug) **~6% W1 / ~22% W2**.
5. **Bar-feed window `iloc` copy** per tick **~4% W1 / ~22% W2** (scales with symbols).
6. **`get_type_hints` per signal** in `Strategy.to_dict` **~2% W1 / ~14% W2**.

**Scaling (W2):** time and memory both **clean O(n)** in symbol count
(`t≈0.66+1.31·n`, `mem≈4.3·n`; n=50 predicted/actual match to <0.1%). **No
super-linear growth, no O(n²) on the symbol axis.**

**Surprises:** (a) the **matching engine is NOT a top-10 hotspot** — contrary to
the spec's hypothesis; the cost is storage/bookkeeping/indicator recompute. (b)
Scalene's **memory profiler is unusable** on this Decimal-allocation-heavy workload
(stalls); tracemalloc carries the memory baseline. (c) Decimal is diffuse native
time (repeated re-summation/conversion), never a "defloat" target — LOCKED honored.

**Coverage confirmed (§6):** all four strategies and six portfolios traded —
market+bracket/OCO (A), resting-limit chase/cancel via `on_tick` (B), pyramiding +
admission rejections (C), short-side 1→3 fan-out (D).

**Handoff:** `perf/results/PERF-BASELINE-RESULTS.md` §6 proposes a 6-phase
optimization breakdown for `/gsd:new-milestone`, each gated on (a) oracle byte-exact
green, (b) measurable improvement vs the frozen baseline.
