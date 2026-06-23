# PERF-BASELINE-RESULTS — Frozen Baseline & Hotspot Map

**Status:** findings (spike Step 2 — profile & baseline). No engine code changed.
**Date:** 2026-06-23
**Spike:** `.planning/spikes/001-perf-baseline-profiling/` (vehicle); spec
`.planning/spikes/PERF-BASELINE.md`.
**Feeds:** `/gsd:new-milestone` (performance milestone roadmap).

> **Guardrails honored.** Money is **Decimal end-to-end (LOCKED)** — every Decimal
> finding below is framed as *redundant work / repeated re-summation / repeated
> conversion*, never "switch to float." Findings only — no optimization performed.
> The byte-exact correctness oracle (`tests/integration/test_backtest_oracle.py`)
> is untouched and stays the deterministic regression lock.

---

## 0. How this was measured

| Item | Value |
|---|---|
| Profiler | Scalene 2.3.0 (`scalene run`), CPU attribution; `--program-path <repo>` so `itrader/`+`perf/` are per-line profiled, **no** `--profile-all` |
| Determinism | seed 42 throughout (`performance.rng_seed`) |
| W1 data | validated 5m CSVs — BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT (`perf/tools/validate_csv.py`: 51,839 rows each, monotonic, OHLC-invariant, **max flat run 0**) |
| W1 frozen-baseline window | **2-month slice** `2026-04-23`→`2026-06-23` (~17.3k bars/symbol) via `W1_START_DATE`/`W1_END_DATE` env overrides |
| W1 profiling window | 1-month sub-slice `2026-05-23`→`2026-06-23` (CPU **proportions** are slice-invariant; absolute baseline is the clean 2-month run) |
| Memory baseline | **tracemalloc** peak (Scalene's allocation-intercepting memory profiler stalled on this Decimal/object-heavy workload — see §5) |

**Two Scalene gotchas resolved** (full trail in the spike README §5):
1. **Memory profiling stalls** on this allocation-heavy workload (millions of
   `Decimal` C-objects); used `--cpu-only` + tracemalloc for memory.
2. **`--profile-all` profiles Scalene's own thread** (dumped 75% of samples into a
   `threading.py Thread.run` bucket — the backtest is single-threaded, `grep`
   confirmed no `Thread()` in the backtest path). Fixed with `--program-path`
   instead; cross-checked against a manual roll-up of per-stack `cpu_samples` to
   the deepest `itrader`/`perf` frame (rankings agree).

---

## 1. Frozen baseline (W1)

**The number every later optimization phase is judged against** (perf analog of the
M2/M5 numerical freeze). Clean run, no profiler attached:

| Metric | Value |
|---|---|
| **Wall-clock** | **240.8 s** |
| **Peak memory (tracemalloc)** | **167.3 MB** |
| Window | `2026-04-23`→`2026-06-23` (2 months, ~17.3k bars/symbol × 4 symbols) |
| Topology | 4 strategies / 6 portfolios (3 isolation + D's 3-way fan-out) |
| Trade log | **1578 fills, 659 closed positions** (P1_A 57 / P2_B 377 / P3_C 298 / P4_D 282 / P5_D 282 / P6_D 282) |
| Throughput | **≈ 72 bars/s** (≈ 287 symbol-bars/s) |

The trade log is non-trivial across **all** four strategies and six portfolios —
the §6 coverage paths fired (market + bracket/OCO, resting-limit chase/cancel,
pyramiding + admission rejections, short-side fan-out). The benchmark measures real
engine work, not a dead run.

> **Reproduce:**
> ```bash
> W1_START_DATE=2026-04-23 W1_END_DATE=2026-06-23 \
>   poetry run python -m perf.runners.run_w1_benchmark
> ```

---

## 2. Ranked hotspot map (W1, top 10)

CPU% is whole-run share from the `--program-path` profile (Python / native split).
Per-line **peak memory was not separable** (Scalene memory profiler unusable here,
§5); the memory column reasons qualitatively about allocation drivers against the
167 MB whole-run peak.

| # | Location (`file::func`) | %CPU (Py / native) | Mem driver | Driven by | Likely cause | Optimizable? |
|---|---|---|---|---|---|---|
| 1 | `order_handler/storage/in_memory_storage.py::InMemoryOrderStorage._orders` (+`get_orders_by_status`) | **~37%** (≈22 Py / ≈15 C) | low (no alloc; iterates existing dict) | order count × queries/bar (grows over run) | **Full linear scan of the flat `{id: order}` dict on every query**, filtered in Python. D-20 keeps *all* orders (incl. closed/filled) for audit history → scan is O(all-orders-ever). Per-bar `on_tick` + admission + reconcile all pay it. UUID `__eq__` on the portfolio predicate adds native cost. | **Yes.** Maintain derived secondary indexes (by portfolio, by status, by active-flag) as caches over the flat dict — keep D-20's flat dict as source of truth, stop the O(n) rescan. No money/oracle impact. |
| 2 | `strategy_handler/indicators/catalog.py::_SMA.compute` | **~19%** (≈8 Py / ≈11 C) | high (new `ta` objects + Series/`dropna` copies per call) | bars × symbols × strategies (A/B/C share SMA_MACD) | **Full-window SMA recompute every bar**: constructs a fresh `ta.trend.SMAIndicator`, re-slices, `.sma_indicator().dropna()` each call. O(window)/bar. | **Yes, but oracle-gated.** Marked `[BYTE-EXACT]`. Incremental/rolling indicator or memoized window — must stay byte-exact (`test_backtest_oracle.py`). Highest-care item. |
| 3 | `portfolio_handler/position/position_manager.py::get_total_realized_pnl` | **~13%** (≈8 Py / ≈5 C) | low | closed-position count × calls/bar (grows over run) | **Re-sums realised PnL over ALL open+closed positions on every call** (per-bar metrics/equity). O(positions)/bar; the `+=` is Decimal (C). | **Yes.** Maintain a running realised-PnL accumulator updated on position close; never re-sum. Decimal stays — this is *redundant re-summation*, not a float swap. |
| 4 | `logger.py::ITraderStructLogger.{warning,debug,info}` | **~6%** (0 Py / ≈6 C) | moderate (event-dict construction) | every bar (C's admission rejections + debug calls) | **Structlog pipeline runs on hot-path log calls**; `debug()` pays call+processing overhead even when not emitted. Warning volume partly a benchmark artifact (C/D deliberately over-extend → rejection warning each bar). | **Yes.** Level-gate hot-loop logs (`isEnabledFor`/cached bool), demote per-bar admission rejections to debug or sampled, drop debug calls from the per-bar path. |
| 5 | `price_handler/feed/bar_feed.py::BacktestBarFeed.window` | **~4% W1 / ~22% W2** (mixed) | high (each `iloc` slice copies a frame) | bars × symbols (scales with symbol count) | **Per-tick window materialization**: `index.searchsorted(cutoff)` (C) + `frame.iloc[start:pos]` **copy** every tick. In W2 (trivial strat, no orders/indicators) this is the #1 framework cost (22%). | **Partial, contract-gated.** searchsorted is already the right primitive; the `iloc` copy per tick is the cost. A reusable view / cached slice bounds could cut copies — must preserve the look-ahead bar-timing contract (`feed/bar_feed.py` 7 rules). |
| 6 | `strategy_handler/base.py::Strategy.to_dict` (`get_type_hints`) | **~2% W1 / ~14% W2** | moderate | every signal | **`get_type_hints(type(self))` re-resolved on every signal snapshot** — walks MRO + evaluates annotations each call though it's constant per class. | **Yes, cheap & safe.** Cache per class (`lru_cache`/compute-once). No money/oracle impact. Big win in signal-dense runs (14% in W2). |
| 7 | `strategy_handler/indicators/catalog.py::_MACDHist.compute` | **~4%** (0 Py / ≈4 C) | high (fresh `ta.MACD` + copies) | bars × symbols × strategies | **Full-window MACD recompute every bar** (`bars[input_col]` whole window, no slice). Same anti-pattern as #2. | **Yes, oracle-gated** (same byte-exact constraint as #2). |
| 8 | `strategy_handler/base.py::Strategy.evaluate` (`self.now = window.index[-1]`) | **~3% (W2) / <1% (W1)** | low | every bar per subscribed strategy | Per-bar pandas index tail access + bookkeeping in the evaluate loop. | Minor; folds into the bar-feed/window work (#5). Low priority. |
| 9 | `outils/time_parser.py::_aligned` | **~1%** (0 Py / ≈1 C) | low | every bar (timestamp alignment) | Per-tick `astimezone`/`replace`/midnight-delta timestamp alignment. | **Yes, minor.** Memoize alignment per timestamp/timeframe; low payoff. |
| 10 | `portfolio_handler/metrics/metrics_manager.py::record_snapshot` (`timestamp.isoformat()`) | **~1%** | moderate (snapshot objects accumulate; `max_snapshots=10000`) | every bar × portfolios | Per-bar snapshot record + ISO-format string. Snapshot retention is the main per-portfolio memory driver. | **Yes, minor.** Defer/skip isoformat until export; bound snapshot retention. |

**Diffuse (not a single line):** `core/money.py::to_money` (`Decimal(str(x))`, ~1%
in W2) and scattered Decimal arithmetic show up as native C time spread across
callers — *repeated conversion at boundaries*, not a hotspot to "defloat." The
**matching engine barely registers** (see §4 surprise).

---

## 3. Scaling curve (W2 — synthetic, seed 42, n_bars=3000)

One trivial LONG_ONLY strategy across N synthetic symbols, swept {1, 10, 50}:

| n_symbols | wall-clock (s) | peak mem (MB) | s/symbol | MB/symbol |
|---|---|---|---|---|
| 1  | 2.079  | 6.99   | 2.079 | 6.99 |
| 10 | 13.761 | 41.28  | 1.376 | 4.13 |
| 50 | 66.170 | 213.22 | 1.323 | 4.26 |

- **Time scales LINEARLY in symbol count.** Fit (n=10→50): `t ≈ 0.66 + 1.31·n` s →
  predicts n=50 = 66.16 s vs **actual 66.17 s**. 1→50 = 31.8× time for 50× symbols.
- **Memory scales LINEARLY:** `mem ≈ 4.3·n` MB → predicts n=50 = 213.3 MB vs
  **actual 213.22 MB**.
- **✅ No super-linear growth.** **No O(n²) in symbol count.** The symbol axis is
  clean O(n); cost is per-bar × per-symbol work repeated N times (bar-feed window,
  logging, signal `to_dict`), confirmed by the W2 profile (§2 #5/#6).

> Caveat: the {1,10,50} sweep would still mask an O(n²) that only bites at
> n≫50. The fit is near-perfect through n=50, so this is low-risk, but a 100/200
> point could be added in the milestone if large universes become a target.

---

## 4. Findings & surprises

1. **The dominant cost is repeated work over growing collections, not the matching
   engine.** The two biggest W1 hotspots (#1 order-storage scan, #3 closed-position
   PnL re-sum) are O(n)-per-bar scans whose n grows over the run — i.e. ~O(n²) in
   run length. This is the single most important structural finding.
2. **The matching engine is NOT a hotspot at this load.** The spec hypothesized
   framework CPU would come from the matching engine + bar feed. Bar feed shows up
   (#5); **the matching engine does not crack the top 10.** Good news — it also
   means optimization effort should target storage/bookkeeping/indicators first.
3. **Indicator recompute is ~24% of W1 CPU** (#2 + #7) — full-window `ta` rebuilds
   per bar. The spec kept D's signal cheap to avoid measuring "strategy compute,"
   but the *shared SMA_MACD indicator engine* (A/B/C) is genuine framework-level
   recomputation overhead, oracle-gated.
4. **Hot-path logging is a real, cross-workload sink** (~6% W1, ~22% W2). Partly a
   coverage-strategy artifact (deliberate over-extension → per-bar rejection
   warnings), but `debug()` overhead on the hot path is structural waste.
5. **`get_type_hints` per signal** (#6) is a cheap, safe, high-leverage win —
   trivial in W1 but 14% in signal-dense W2.
6. **Decimal is not a standalone hotspot.** It appears as diffuse native C time
   (re-summation in #3, boundary conversion in `to_money`). Honors the LOCKED
   decision: the fix is *less repeated work*, never float.
7. **Symbol scaling is clean O(n)** — no quadratic to chase on the symbol axis.

---

## 5. Memory baseline caveat

Scalene's memory profiler intercepts every allocation; on this workload (1578 fills
→ millions of short-lived `Decimal` C-objects) it throttled the run to ~0.1% CPU
and never completed. **Per-line memory attribution is therefore not available.** The
**peak-memory baseline is tracemalloc** (167.3 MB W1; 4.3 MB/symbol W2), which is
sufficient to freeze the baseline and track regressions. Qualitative allocation
drivers are noted in the §2 "Mem driver" column (indicator `ta` objects + Series
copies, bar-feed `iloc` slice copies, metrics snapshots). If per-line memory becomes
necessary in the milestone, run Scalene memory on a **much smaller slice** (≤1 week)
or use `tracemalloc` snapshot diffing around the suspect call sites.

---

## 6. Proposed milestone phase breakdown

Each optimization phase is **gated on (a) the byte-exact oracle staying green and
(b) the W1 benchmark showing a measurable, locked improvement** vs the §1 frozen
baseline (240.8 s / 167.3 MB). Ordered by expected payoff × safety.

| Phase | Target hotspot(s) | Approach | Est. CPU share | Risk / gate |
|---|---|---|---|---|
| **P1 — Order-storage indexing** | #1 (~37%) | Derived secondary indexes (portfolio / status / active) over the flat dict; flat dict stays source of truth (D-20). | Highest | Low. No money/oracle surface. Pure data-structure. |
| **P2 — Running PnL accumulator** | #3 (~13%) | Maintain realised-PnL running total updated on close; stop per-bar re-sum. | High | Low. Decimal preserved (less re-summation). Verify equity/metrics unchanged. |
| **P3 — Hot-path logging discipline** | #4 (~6% W1 / 22% W2) | Level-gate hot-loop logs; demote/sample per-bar admission rejections; remove debug from per-bar path. | High (esp. multi-symbol) | Low. Behavior-only; no numeric impact. |
| **P4 — Cache `get_type_hints` in `to_dict`** | #6 (~2% W1 / 14% W2) | Per-class memoization of the type-hint snapshot. | Med (signal-dense) | Very low. No money/oracle surface. |
| **P5 — Incremental indicators** | #2 + #7 (~24%) | Rolling/memoized SMA & MACD replacing per-bar full-window `ta` rebuild. | Highest, hardest | **High — oracle-gated.** Must reproduce `[BYTE-EXACT]` output. Do last, with the oracle as the lock. |
| **P6 — Bar-feed window copies (optional)** | #5 (~4% W1 / 22% W2) | Reduce per-tick `iloc` frame copies (reusable view / cached bounds). | Med (scales w/ symbols) | Med — must preserve the look-ahead bar-timing contract. |

**Sequencing rationale:** P1–P4 are low-risk, high-return data-structure / discipline
fixes with no numeric surface — bank them first and re-freeze. P5 (indicators) is the
largest single chunk but the most dangerous (oracle byte-exactness) — isolate it last.
Milestone Phase 1 (per spec §13) remains: add the backtesting.py + backtrader
comparison runners and re-freeze the baseline before any of the above.

---

## 7. Exit criteria (spec §11)

- [x] W1 runs deterministically; non-trivial trade log across all 4 strategies / 6 portfolios (1578 fills).
- [x] §6 paths confirmed exercised (market+bracket, resting-limit chase/cancel, pyramiding+rejections, short fan-out).
- [x] W2 sweep produces a scaling curve over {1,10,50}; **no super-linear growth** (clean O(n)).
- [x] Scalene CPU profiles captured for both workloads. **Memory: tracemalloc** (Scalene memory profiler unusable here — §5).
- [x] `PERF-BASELINE-RESULTS.md` written: frozen baseline + ranked hotspot map + scaling curve + proposed phases.
- [ ] Findings handed to `/gsd:new-milestone` (next action).
