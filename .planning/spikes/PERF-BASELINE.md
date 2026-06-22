# Spike: PERF-BASELINE — Performance Profiling of the Backtest Engine

**Status:** spec (pre-milestone investigation)
**Type:** evals-first — build the durable benchmark, then profile it. No engine code changes.
**Feeds:** `/gsd:new-milestone` (performance milestone roadmap)
**Date:** 2026-06-22

---

## 1. Purpose

Produce a **frozen performance baseline** and a **ranked hotspot map** of the iTrader
backtest engine, so the upcoming performance milestone can be planned as surgical,
*measured* phases rather than ad-hoc profile-then-fix.

Guiding principle: **build the scoreboard before optimizing.** Nothing in the
performance milestone gets touched until there is (a) a locked baseline and (b) a
hotspot map that says where the time and memory actually go.

**Approach A (evals-first).** The benchmark *workload* — the coverage strategies, the
workload wiring, the synthetic generator — is a **durable eval asset**, not throwaway. It
is built **first**, as committed code under `evals/` (through GSD), and the scoreboard is
built before profiling. Profiling then runs *on top of* that durable harness; only the
one-off Scalene invocation and exploratory pokes are throwaway. This spike does **not**
change engine code.

---

## 2. Scope & non-goals

**In scope**
- A durable `evals/` harness: coverage strategies, workload wiring (W1), synthetic generator (W2) — committed through GSD.
- Scalene CPU + memory profiling of both workloads, run against that harness.
- A `PERF-BASELINE-RESULTS.md` hotspot map + frozen baseline numbers.

**Out of scope (explicit)**
- **No optimization.** Findings only.
- **No change to the byte-exact correctness oracle** (`tests/integration/test_backtest_oracle.py`).
  That stays the deterministic regression lock. Performance is a *separate* concern with
  different requirements (noisy wall-clock, trend-tracked, not a pass/fail gate). Do not
  conflate them.
- **No three-engine comparison yet.** The `evals/` harness is built here with the *iTrader*
  runner only (enough to profile + freeze a baseline). Adding the backtesting.py / backtrader
  comparison runners is a later milestone phase, not this spike.

**Sequencing (evals-first).** The `evals/` skeleton — `strategies/`, `workloads/`, the
iTrader `runners/` — is built **first**, as committed code through GSD. Profiling runs on top
of it. The only throwaway parts are the one-off Scalene command and exploratory pokes
(e.g. confirming cancel/modify reachability). See §9.

---

## 3. Two workloads, two jobs

These answer two *different* questions and must not be merged:

| | **W1 — Realistic benchmark** | **W2 — Scaling sweep** |
|---|---|---|
| Question | "Where does time/memory go at realistic load?" | "What's the complexity curve in symbol count?" |
| Data | Real **5m** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT | Synthetic, seeded-RNG OHLCV |
| Symbols | ~4 (capped by liquid crypto) | swept: 1 → 10 → 50 |
| Strategies | 4 (roster below) | 1 trivial strategy across all symbols |
| Role | Primary benchmark; baseline frozen here | Profiling-only; finds super-linear hotspots |
| Home | `evals/workloads/` (durable) | `evals/workloads/` synthetic generator (durable) |

Real crypto data is capped at a handful of liquid symbols — it answers "is this line
hot" but **cannot** answer "does this scale to 50 symbols." That's W2's whole job.

---

## 4. Strategy roster (W1)

These are **coverage instruments, not alpha.** Tune for trade density and to *trip each
engine path*, even at a loss. Reuse the `SMA_MACD` signal where possible and change only
the order plumbing around it.

Grounded in the real API (`strategy_handler/base.py`): strategies return a `SignalIntent`
via sugar factories `buy()/sell()`, `buy_limit(price=…)/sell_limit(price=…)`,
`buy_stop(price=…)/sell_stop(price=…)`, each accepting `sl=` / `tp=` to declare a bracket.
`direction` ∈ {LONG_ONLY, LONG_SHORT, SHORT_ONLY}; sizing via FractionOfCash / FixedQuantity
/ RiskPercent / LeveredFraction. One strategy fans out to N portfolios via
`strategy.subscribe_portfolio(pid)` (confirmed buildable as-is).

| # | Strategy | Instruments | Order plumbing | Direction | Portfolio(s) |
|---|---|---|---|---|---|
| **A** | Bracketed momentum | BTCUSDT | `buy()`/`sell()` MARKET entry, **every entry with `sl=` + `tp=`** (bracket/OCO children) | LONG_ONLY | **P1** |
| **B** | Limit-maker mean reversion | ETHUSDT, SOLUSDT, BNBUSDT | `buy_limit(price=…)` resting below price; limit `tp=`; re-price unfilled each bar | LONG_ONLY | **P2** |
| **C** | Pyramiding trend | BTCUSDT (+SOLUSDT) | repeated `buy()` adds on continuation, aggregate `sl=`, **no cash headroom cap** | LONG_ONLY | **P3** |
| **D** | Short-only (cheap signal) | ETHUSDT (or ETHUSDT/SOLUSDT ratio) | `sell()` / `sell_stop(price=…)`; **z-score of a price ratio** (cheap), NOT cointegration | SHORT_ONLY | **P4 + P5 + P6** (fan-out) |

**Why each exists** (path it owns):
- **A** — market fill + **bracket/OCO same-bar priority** + stop & limit trigger + gap-aware
  fills. On gappy 5m bars you get same-bar double-triggers — the nastiest matching corner.
- **B** — **resting-limit book at scale** + multi-symbol fan-out + (intended) **cancel/modify**
  lifecycle. ⚠️ *Verify during spike:* confirm strategy-driven re-price/cancel of an unfilled
  resting limit is reachable from the strategy layer; if not, this path needs an explicit
  cancel route or the coverage claim is dropped. (See §9 risks.)
- **C** — repeated admission + **position averaging** + **insufficient-funds rejections**
  (`FillEvent(REFUSED)` → mirror reconcile). Let it over-extend so rejections fire for free.
- **D** — **short-side admission** (unfunded-short path, the P05.1 WR-03 area just audited),
  2-leg coordination, and **one-strategy→3-portfolios fan-out**. Deliberately cheap signal so
  it adds *no artificial CPU* — strategy-internal compute is not framework overhead.

**Short-selling prerequisite:** Strategy D is `SHORT_ONLY`, so per SHORT-01/D-07 the system
must be wired with **both** `allow_short_selling=True` **and** `enable_margin=True` or
`add_strategy` raises. Configure this in the harness.

---

## 5. Portfolio topology (W1)

Six portfolios — three isolation, one three-way fan-out:

| Portfolio | Fed by | Topology covered |
|---|---|---|
| P1 | A | 1 strategy : 1 portfolio (isolation) |
| P2 | B | 1 strategy : 1 portfolio (isolation) |
| P3 | C | 1 strategy : 1 portfolio (isolation) |
| P4, P5, P6 | D | **1 strategy : 3 portfolios (fan-out)** — each sizes/admits the same signal against its own cash, independently |

6 portfolios marked-to-market every bar → strong `PortfolioHandler` stress, plus the fan-out
path (D's signal multiplies into P4/P5/P6 each tick, exercising independent per-portfolio
admission with no cross-portfolio bleed — sharpened by the short side).

---

## 6. Coverage matrix (what gets exercised)

| Engine path | Owner(s) |
|---|---|
| Market-order fill | A, C |
| Resting **limit** book | B |
| Resting **stop** (SL children, breakout stops) | A, C |
| **Bracket / parent-child OCO + same-bar priority** | A |
| Gap-aware intrabar fills | A, B (5m gappy series) |
| Order **cancel / modify** + mirror reconcile | B *(verify reachability)* |
| Pyramiding / position averaging | C |
| **Rejections** (`FillEvent(REFUSED)`) — insufficient funds | C, D |
| **Short-side admission** (unfunded short) | D |
| Multi-symbol per-bar fan-out | B (, D if 2-leg) |
| Multi-portfolio mark-to-market | all (6 portfolios) |
| **1 strategy → N portfolios fan-out** | D |
| Framework **CPU** hotspots (matching trigger eval, bar-feed slicing) | A, B |
| **Decimal / bookkeeping** hotspots (cash, position, quantize) | A, C (high fill density) |

Note: framework-CPU hotspots come from the **matching engine and bar feed** (A/B), not from
strategy compute — which is exactly why D's signal is kept cheap.

---

## 7. Data requirements

**W1 (real):** **5m** OHLCV for **BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT** (pinned).
- Format: the CSV store (`price_handler/store/csv_store.py`) expects **Binance-kline
  columns** but reads only `open/high/low/close/volume`. Multi-symbol via the
  `csv_paths={'BTCUSDT': 'data/BTCUSDT_5m.csv', 'ETHUSDT': …, 'SOLUSDT': …, 'BNBUSDT': …}`
  dict on `BacktestTradingSystem`. (USDT tickers throughout — distinct from the golden
  `BTCUSD` oracle set, which stays untouched.)
- **Span matters more than timeframe** (iteration count is the dominant cost). At 5m,
  ~6–12 months ≈ 52k–105k bars/symbol. Start at ~6 months; extend if the profile is too
  quick to sample.
- **Sourcing:** ⚠️ **Do NOT use `ccxt_provider.py::download_data` as-is** — reviewed 2026-06-22,
  it is not bug-safe for large clean pulls (it's a deferred, mypy-ignored subsystem). Confirmed
  defects: **`end_date` is ignored** (always fetches start→now); **`resample().ffill()`
  fabricates flat `O=H=L=C` bars over gaps** (pollutes the profile + baseline); **the unclosed
  last candle is included**; **no rate-limit handling and download exceptions are uncaught**
  (long pulls crash); **provider output schema ≠ `CsvPriceStore` input schema** (5-col datetime
  frame vs raw 12-col Binance-kline CSV); plus boundary-dup/infinite-loop fragility and a
  hardcoded 4-char-quote symbol split.
  - **Instead:** write a small **hardened one-shot fetch script** (throwaway) using `ccxt`
    directly: `enableRateLimit=True` + try/except backoff; explicit `since`→`end_date` bound;
    **dedup by timestamp**; **drop the last (unclosed) candle**; **no ffill-resample** (preserve
    real gaps); write CSVs in the **exact Binance-kline schema `CsvPriceStore` parses**.
  - Symbols are **USDT** pairs (the provider's symbol split assumes a 4-char quote): fetch
    `BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT` → store as `BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT`.
  - Validate the CSVs before profiling: monotonic non-duplicated index, OHLC invariants, no
    fabricated flat bars. Bad source data invalidates the whole baseline.

**W2 (synthetic):** seeded-RNG OHLCV generator
`make_synthetic_ohlcv(n_bars, n_symbols, seed=42)` (`evals/workloads/synthetic.py`) producing
in-memory frames fed through the same `CsvPriceStore`/feed path.
- **No new dependency** — use `numpy.random.default_rng(seed)` (numpy is already a dep; reuse
  the `performance.rng_seed=42` discipline). Libraries (`stochastic`, `TimeSynth`,
  `mockseries`, `arch`) only emit a *price path*, not OHLCV bars — not worth the dependency.
- **Generation:** per bar, draw an **M-step sub-bar GBM path**, then `O=first, C=last,
  H=max, L=min`, `V`=positive random draw. The sub-bar step is what **guarantees the OHLC
  invariants** (`L ≤ O,C ≤ H`); a naive close-only random walk produces invalid bars that
  can mislead — or crash — the matching engine.
- W2 is a **scaling** test, not a realism test, so GBM is sufficient (realism lives in W1).
  One trivial strategy subscribed across all N symbols. Sweep `n_symbols ∈ {1, 10, 50}` at
  fixed `n_bars`.

---

## 8. Scalene setup & invocation

Scalene is **not** currently a dependency. Add it to the dev group (it persists into `evals/`):

```bash
poetry add --group dev scalene
```

Profiling runs (CPU + memory; Scalene separates Python vs **native/C** time and gives
per-line memory — so heavy native calls are easy to mentally exclude) — run against the
durable `evals/` runners:

```bash
# W1 — realistic benchmark
poetry run scalene --html --outfile .planning/spikes/profile-w1.html \
  evals/runners/run_w1_benchmark.py

# W2 — scaling sweep (run per symbol count, or loop inside the script)
poetry run scalene --html --outfile .planning/spikes/profile-w2.html \
  evals/runners/run_w2_sweep.py
```

Notes:
- Use `--reduced-profile` to focus output on hot lines.
- **Determinism:** every run uses seed 42 so profiles are reproducible.
- `filterwarnings=["error"]` is a *pytest* setting — it does **not** affect standalone
  profiling scripts. Running outside pytest is fine.
- If run inside a git worktree, prepend `PYTHONPATH="$PWD"` to avoid the editable-install
  `.venv` shadowing the worktree's code (known repo gotcha).

---

## 9. Harness structure (durable — `evals/`)

Built **first**, committed through GSD. These are long-lived eval assets, regression-tracked
every milestone — **not** scratch. `evals/` is a top-level directory *outside* the shipped
`itrader/` package; it imports `from itrader.strategy_handler.base import Strategy`.

```
evals/
├── strategies/          # A, B, C, D — durable coverage instruments
├── workloads/           # W1 wiring (4 strat / 6 pf) + synthetic.py (W2 generator)
├── runners/             # run_w1_benchmark.py, run_w2_sweep.py (iTrader-only for now)
└── results/             # frozen baseline + hotspot artifacts
```

Each runner: wire system → `add_strategy` + `subscribe_portfolio` (per topology) → `run()`
→ capture wall-clock and peak memory. W1 also asserts a **non-trivial trade log** so we know
the paths actually fired (a benchmark that doesn't trade is measuring nothing).

**Why `evals/strategies/` (not `scripts/perf/` or `my_strategies/`):** these are durable
benchmark assets, and co-locating them with the harness enforces a clean separation —

| Location | What lives there |
|---|---|
| `strategy_handler/strategies/` | Reference *product* strategies (SMA_MACD) |
| `strategy_handler/my_strategies/` | The user's *real* trading strategies |
| `evals/strategies/` | **Coverage instruments — exist only to exercise engine paths** |

A coverage strategy that deliberately over-extends to trigger rejections must never be
mistaken for a real one; the `evals/` home makes that unambiguous by construction.

**Throwaway (not committed):** the one-off `scalene …` command (§8) and exploratory pokes
(e.g. the cancel/modify reachability check below).

**Risks / to-confirm before/while building:**
1. **Cancel/modify reachability (Strategy B).** Confirm a strategy can re-price/cancel an
   unfilled resting limit. If not reachable, either route it explicitly or drop the
   cancel/modify coverage claim — don't pretend it's covered.
2. **Pyramiding adds.** Confirm repeated same-direction `buy()` on an open position averages
   in rather than being rejected as a duplicate; tune sizing so rejections come from *cash*,
   not from a guard.
3. **Trade density.** If real 5m data yields too few fills, tighten strategy thresholds — the
   goal is to saturate the expensive paths.
4. **CCXT provider bug-safety — REVIEWED 2026-06-22 ✓.** `download_data` is *not* safe for
   large clean pulls (see §7 for the confirmed defect list). Resolution: write a hardened
   one-shot fetch script rather than use the provider. Still TODO: validate the fetched CSVs
   (monotonic index, OHLC invariants, no fabricated flat bars) before profiling.

---

## 10. Output artifact — `evals/results/PERF-BASELINE-RESULTS.md`

The deliverable that feeds `/gsd:new-milestone`:

1. **Frozen baseline (W1):** wall-clock and peak memory for the full 4-strategy / 6-portfolio
   run at the pinned span + seed. This is the number every later optimization phase is judged
   against (the perf analog of the M2/M5 numerical freeze).
2. **Ranked hotspot map (top ~10):**

   | Rank | Location (`file:func`) | % CPU (Python / native) | Peak mem | Driven by (bars / symbols / trade-density / portfolios) | Likely cause | Optimizable? |
   |---|---|---|---|---|---|---|

   - **"Optimizable?"** must respect locked decisions: **Money is Decimal end-to-end (locked).**
     Frame Decimal hotspots as *"redundant work / over-quantization / repeated conversion"* —
     never *"switch to float."*
3. **Scaling curve (W2):** wall-clock & memory vs symbol count {1,10,50}; flag any
   **super-linear** growth (candidate O(n²) in symbol count).
4. **Proposed milestone phase breakdown:** one phase per hotspot cluster, each gated on
   (a) oracle stays byte-exact green, (b) benchmark shows measurable, locked improvement.

---

## 11. Exit criteria

- [ ] W1 runs deterministically, produces a non-trivial trade log across all 4 strategies / 6 portfolios.
- [ ] All §6 paths confirmed exercised (or explicitly marked uncovered with reason).
- [ ] W2 sweep produces a scaling curve over {1,10,50} symbols.
- [ ] Scalene CPU+memory profiles captured for both workloads.
- [ ] `PERF-BASELINE-RESULTS.md` written: frozen baseline + ranked hotspot map + scaling curve + proposed phases.
- [ ] Findings handed to `/gsd:new-milestone`.

---

## 12. Handoff

On completion → `/gsd:new-milestone` consumes `evals/results/PERF-BASELINE-RESULTS.md`.

Because the durable `evals/` harness is built *here* (evals-first), the milestone no longer
needs a "build the harness" phase. Instead:
- **Milestone Phase 1** = add the **three-engine comparison** (backtesting.py + backtrader
  runners alongside iTrader; timing + memory + the result metrics already compared) on top of
  the existing `evals/` harness, and **freeze the baseline**.
- **Phases 2..N** = surgical optimization, one hotspot cluster each, gated on
  (a) oracle stays byte-exact green, (b) benchmark shows measurable, locked improvement.
