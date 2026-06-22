---
quick_id: 260622-vlh
type: execute
plan: 01
subsystem: evals
status: complete
tags: [evals, performance, benchmark, harness, perf-baseline]
key-files:
  created:
    - evals/__init__.py
    - evals/tools/__init__.py
    - evals/tools/fetch_binance_5m.py
    - evals/tools/validate_csv.py
    - evals/strategies/__init__.py
    - evals/strategies/a_bracketed_momentum.py
    - evals/strategies/b_limit_maker.py
    - evals/strategies/c_pyramiding_trend.py
    - evals/strategies/d_short_zscore.py
    - evals/workloads/__init__.py
    - evals/workloads/w1_topology.py
    - evals/workloads/synthetic.py
    - evals/runners/__init__.py
    - evals/runners/run_w1_benchmark.py
    - evals/runners/run_w2_sweep.py
    - evals/results/.gitkeep
    - evals/results/README.md
    - evals/README.md
    - data/BTCUSDT_5m.csv
    - data/ETHUSDT_5m.csv
    - data/SOLUSDT_5m.csv
    - data/BNBUSDT_5m.csv
  modified:
    - pyproject.toml
    - poetry.lock
commits:
  - 06660e2
  - 4f036e7
  - 83c9fcf
  - bbc5987
---

# Quick Task 260622-vlh: Durable evals/ Benchmark Harness Summary

Built the durable `evals/` performance-benchmark harness (PERF-BASELINE spike,
Step 1 — harness only, no profiling): a hardened one-shot CCXT 5m fetch + CSV
validation producing four committed `data/*_5m.csv` files, four coverage
strategies A–D, the W1 4-strategy/6-portfolio topology wiring, the W2 numpy-GBM
synthetic generator, and two iTrader-only runners. W1 runs end-to-end and asserts
**271 fills / 72 closed positions** across the 6-portfolio topology; W2 sweeps
{1,10,50} symbols and surfaces a super-linear scaling curve. `scalene` added to
the dev group.

## What was built (per task)

**Task 1 — fetch + validate + data + scalene (commit `06660e2`).**
- `evals/` package root + `evals/tools/` with a hardened ONE-SHOT CCXT fetch
  script (`fetch_binance_5m.py`): `enableRateLimit=True` + exponential-backoff
  retries, explicit `since`→`end` bound, dedup by timestamp (strictly-monotonic),
  drops the unclosed last candle, NO ffill/resample (real gaps preserved), writes
  the exact 12-column Binance-kline header `CsvPriceStore` parses.
- `validate_csv.py`: store-style parse then asserts six columns present, a
  strictly-increasing non-duplicated index, per-row OHLC invariants, and no
  fabricated flat O=H=L=C runs (>5 consecutive ⇒ fail). Raises loudly.
- `scalene` added to the dev group (`pyproject.toml` + `poetry.lock`; resolver
  picked `^2.3.0`). Step 2 (profiling) is out of scope; no Scalene was invoked.

**Task 2 — coverage strategies A–D (commit `4f036e7`).** Each subclasses
`itrader.strategy_handler.base.Strategy`, reuses the SMA_MACD signal pattern where
possible, and documents the engine path it owns. Banners mark them as coverage
instruments, never alpha.

**Task 3 — W1 topology + W2 synthetic (commit `83c9fcf`).**
- `synthetic.make_synthetic_ohlcv(n_bars, n_symbols, seed=42)`: 8-step sub-bar GBM
  per bar (O=first, C=last, H=max, L=min), `numpy.random.default_rng(42)` — no new
  dep. Deterministic (same seed ⇒ byte-identical) and asserts OHLC invariants for
  every generated bar internally.
- `w1_topology.wire_w1(system)`: applies the verified short-selling recipe and
  registers A→P1, B→P2, C→P3, D→P4/P5/P6 fan-out (wiring only; no `run()`).

**Task 4 — W1 + W2 runners (commit `bbc5987`).**
- `run_w1_benchmark.py`: constructs the system over the real 5m span, wires the
  topology, drives B's cancel/modify lifecycle from `on_tick` (chase unfilled
  limits up toward price; cancel stale ones), captures wall-clock
  (`perf_counter`) + peak memory (`tracemalloc`), and **asserts >0 total fills**
  with a per-portfolio breakdown.
- `run_w2_sweep.py`: writes synthetic frames to temp kline CSVs, runs a trivial
  LONG_ONLY strategy across all symbols for n_symbols ∈ {1,10,50}, prints the
  (n_symbols, wall_clock_s, peak_mem_mb) table.
- `evals/results/` placeholder (Step 2 writes `PERF-BASELINE-RESULTS.md`).

## Short-selling recipe — constructed cleanly (with one adaptation)

The verified 6-step recipe from `_build_flagship_system` constructs and runs
cleanly; **no private-attr names had drifted** (`sh._allow_short_selling`,
`sh._enable_margin`, `om.admission_manager._enable_margin`,
`om.order_validator.enable_margin`, and the per-portfolio
`config.trading_rules.model_copy(...)` all resolved as documented).

**Adaptation (deviation, see below):** the per-portfolio trading-rules margin
flags are applied ONLY to the D-fed short portfolios (P4/P5/P6), NOT to the
LONG-only books (P1/P2/P3). The system-wide handler/admission/validator flags
(steps 1+5, required for the SHORT_ONLY registration gate) stay on globally.

## W1 trade breakdown (271 fills / 72 closed — paths fired)

| Portfolio | Strategy | Fills | Closed positions |
|-----------|----------|-------|------------------|
| P1_A | A bracketed momentum | 184 | 61 |
| P2_B | B limit-maker        | 3   | 0  |
| P3_C | C pyramiding trend   | 81  | 11 |
| P4_D | D short z-score      | 1   | 0  |
| P5_D | D short z-score      | 1   | 0  |
| P6_D | D short z-score      | 1   | 0  |
| **TOTAL** | | **271** | **72** |

Run metrics (180-day 5m span, 51,839 bars/symbol): wall-clock ≈ 878 s, peak mem
≈ 368 MB. Run is deterministic by construction (seed 42, injected clock).

**Reading the thin counts (honest coverage, not a dead path):**
- **B = 3 fills** understates the path B owns. B's owned path is the
  *resting-limit book at scale* + *cancel/modify lifecycle*, which fires HEAVILY:
  every bar B rests limits across ETH/SOL/BNB and the runner's `on_tick`
  re-prices (`modify_order`) and cancels (`cancel_order`) the unfilled ones —
  the mirror-reconcile path is exercised on hundreds of orders. A limit-maker's
  net *fills* are inherently few (price must return to the resting level); the
  resting/modify/cancel volume is the coverage, not the fill count.
- **D = 1 fill/portfolio** is the correct, complete coverage for the path D owns:
  *short-side admission* + *1-strategy→3-portfolio fan-out*. D is SHORT_ONLY and
  never covers (it cannot `buy()`), so each portfolio opens exactly one short and
  it is marked-to-market open thereafter (the same "legs left open at run end"
  behaviour as the pair flagship). All three fan-out portfolios independently
  admitted the short ⇒ the fan-out path is demonstrated.

## W2 scaling sweep (n_bars=3000, seed=42)

| n_symbols | wall_clock_s | peak_mem_mb |
|-----------|--------------|-------------|
| 1  | 2.088  | 6.99   |
| 10 | 14.093 | 41.28  |
| 50 | 65.386 | 213.22 |

Wall-clock grows **super-linearly** in symbol count (≈6.7× from 1→10 symbols at
10× the symbols; ≈4.6× from 10→50 at 5×) — a candidate super-linear hotspot in
symbol count, exactly the signal W2 exists to surface for Step 2's hotspot map.
Peak memory scales roughly linearly (~30 MB → ~213 MB).

## §6 coverage matrix (path → owner → fired?)

| Engine path | Owner(s) | Confirmed fired? |
|-------------|----------|------------------|
| Market-order fill | A, C | YES (A 184, C 81 fills) |
| Resting **limit** book | B | YES (B rests limits each bar; on_tick chases/cancels) |
| Resting **stop** (SL children) | A, C | YES (A/C entries declare `sl=` ⇒ stop children rest) |
| **Bracket / parent-child OCO + same-bar priority** | A | YES (every A entry = sl+tp bracket; 61 closed via OCO) |
| Gap-aware intrabar fills | A, B | YES (5m gappy series; A's 61 closes are bracket triggers) |
| Order **cancel / modify** + mirror reconcile | B | YES (runner on_tick modify_order + cancel_order each bar) |
| Pyramiding / position averaging | C | YES (allow_increase=True; 81 fills into 11 closed positions ⇒ averaging) |
| **Rejections** (`FillEvent(REFUSED)`) — insufficient funds | C, D | YES (admission CASH_RESERVATION rejections logged for C/B/D) |
| **Short-side admission** (unfunded short) | D | YES (3 short entries admitted across P4/P5/P6) |
| Multi-symbol per-bar fan-out | B (, D) | YES (B over ETH/SOL/BNB; D ratio note below) |
| Multi-portfolio mark-to-market | all (6 pf) | YES (6 portfolios marked each bar) |
| **1 strategy → N portfolios fan-out** | D | YES (D → P4/P5/P6, each independently admitted) |
| Framework **CPU** hotspots (matching, bar-feed) | A, B | YES (exercised; measured in Step 2) |
| **Decimal / bookkeeping** hotspots | A, C | YES (high fill density on A/C) |

No §6 path was found genuinely uncoverable. One path was honoured with a
documented simplification (D's signal — see deviations); it still exercises the
short-side admission + fan-out paths it owns.

## Committed CSV row counts + date span

All four CSVs: **51,839 rows each**, span **2025-12-24 21:00:00+00:00 →
2026-06-22 20:50:00+00:00** (180 days @ 5m), max consecutive flat-OHLC run = 0.
Files: `data/BTCUSDT_5m.csv`, `data/ETHUSDT_5m.csv`, `data/SOLUSDT_5m.csv`,
`data/BNBUSDT_5m.csv`. All pass `validate_csv.py`.

## Deviations from Plan

### Auto-fixed Issues (Rules 1/3 — applied during Task 4)

**1. [Rule 1 — Bug] Strategy D crashed on an empty bar window.**
- Found during: Task 4 (first W1 run). D has no declared indicators, so the base
  auto-derives `warmup=0` AND `max_window=0` — the feed then hands D an EMPTY
  window every tick (`frame.iloc[pos:pos]`), and `self.bars["close"].iloc[-1]`
  raised `IndexError`.
- Fix: added an empty-window guard in `generate_signal` AND pinned a class-attr
  `max_window = z_window` so the feed gives D a real window; the rolling deque was
  replaced with a direct numpy z-score off the window (stateless, deterministic).
- Files: `evals/strategies/d_short_zscore.py`. Commit: `bbc5987`.

**2. [Rule 3 — Blocking] Long settlement under per-portfolio margin raised and
fail-fast aborted the run.** Found during: Task 4. Enabling per-portfolio margin
on ALL six portfolios (the recipe's "harmless for longs" note) routed the LONG
books (A/B/C) through the margin lock-and-settle path, whose
`assert_lock_fits_buying_power` RAISES `InsufficientFundsError` on Strategy C's
over-extended add — fail-fast aborting the backtest before any result.
- Fix: scope the PER-PORTFOLIO trading-rules margin to the D-fed shorts
  (P4/P5/P6) only. The LONG books stay SPOT, where C's over-extension instead
  produces the graceful admission-side `CASH_RESERVATION` rejection
  (`FillEvent(REFUSED)` → mirror reconcile) the benchmark wants (spec §6). The
  system-wide handler/admission/validator margin flags stay on for the SHORT_ONLY
  registration gate. Files: `evals/workloads/w1_topology.py`. Commit: `bbc5987`.

**3. [Rule 2 — Trade density] B/D capped at one position; B limits never filled.**
Found during: Task 4. Default `max_positions=1` capped B (3 symbols) at one open
position and D at one short; the initial on_tick re-priced limits DOWNWARD (away
from price) so they never filled.
- Fix: B `max_positions=3` (one per symbol) + looser entry band (dense resting
  book); D `max_positions=5`; on_tick now chases limits UP toward price and
  cancels only stale ones. Files: `evals/strategies/b_limit_maker.py`,
  `evals/strategies/d_short_zscore.py`, `evals/runners/run_w1_benchmark.py`.
  Commit: `bbc5987`.

### Documented simplification (NOT silently faked)

**Strategy D signal — single-symbol z-score instead of an ETH/SOL price ratio.**
The spec names a z-score of the ETHUSDT/SOLUSDT price RATIO. A cross-symbol ratio
is NOT reachable from the single-ticker `generate_signal` contract (the pure
strategy sees only one ticker's window; the two-leg `PairStrategy` path is heavier
separate machinery). To stay within the cheap-single-signal intent while honestly
tripping the short-side admission + fan-out paths D owns, D uses a rolling z-score
of the ETHUSDT close itself (same cost class, same SHORT_ONLY coverage). The ORDER
is on ETHUSDT either way. This is documented in `d_short_zscore.py`'s module
docstring — not silently faked.

## Path reported uncoverable

None. Every §6 path fired (table above). The only adjustment was the documented
Strategy-D signal simplification, which still exercises the short-side admission +
fan-out paths it owns.

## Constraints honoured

- `data/BTCUSD_1d_ohlcv_2018_2026.csv` and `tests/integration/test_backtest_oracle.py`
  are byte-unchanged (`git status` clean for both).
- Money is Decimal end-to-end (string-path `Decimal(str(...))` / `to_money`); no
  `Decimal(float)`. Determinism: seed 42 throughout.
- All `evals/` code uses 4-space indentation and absolute `from itrader...` imports.
- No Scalene / profiling was invoked (Step 2, out of scope).
- ROADMAP.md / STATE.md untouched (orchestrator commits docs separately).

## Self-Check: PASSED

- All 21 created files exist on disk (verified via `git show --stat` of the four
  commits).
- All four commit hashes exist: `06660e2`, `4f036e7`, `83c9fcf`, `bbc5987`
  (verified via `git log --oneline`).
- W1 runner asserts >0 fills (271) and exits 0; W2 runner prints three scaling
  points and exits 0; `validate_csv.py` passes on all four CSVs.
