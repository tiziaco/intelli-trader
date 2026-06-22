# evals/ — durable performance-evals harness

This tree is the **durable benchmark scoreboard** for the iTrader backtest
engine, built per the `PERF-BASELINE` spike (Step 1 — the harness only; Scalene
profiling is Step 2 and lives in a separate spike). These are long-lived eval
assets, regression-tracked every milestone — **not** scratch.

`evals/` lives OUTSIDE the shipped `itrader/` package and imports the engine via
absolute imports (`from itrader.strategy_handler.base import Strategy`).
Convention: **4-space indentation** throughout (newer-module convention).

## Layout

```
evals/
├── tools/        # one-shot CCXT fetch + CSV validation gate
├── strategies/   # coverage instruments A–D (exercise engine paths, NOT alpha)
├── workloads/    # W1 topology wiring + W2 numpy-GBM synthetic generator
├── runners/      # iTrader-only W1 + W2 benchmark runners
└── results/      # frozen baseline + hotspot artifacts (written in Step 2)
```

## Two workloads

- **W1 — realistic benchmark.** Real 5m OHLCV for BTCUSDT / ETHUSDT / SOLUSDT /
  BNBUSDT, 4 coverage strategies across 6 portfolios (3 isolation + a 3-way
  fan-out). Answers "where does time/memory go at realistic load?". Asserts a
  non-trivial trade log so the measured paths actually fired.
- **W2 — scaling sweep.** Synthetic seeded-RNG GBM OHLCV swept over
  `n_symbols ∈ {1, 10, 50}` with one trivial strategy. Answers "what's the
  complexity curve in symbol count?".

## Coverage strategies (NOT alpha)

| # | Strategy | Direction | Owns (engine path) |
|---|----------|-----------|--------------------|
| A | Bracketed momentum | LONG_ONLY | market fill + bracket/OCO same-bar priority + stop/limit trigger + gap fills |
| B | Limit-maker mean reversion | LONG_ONLY | resting-limit book + multi-symbol fan-out + cancel/modify (runner `on_tick`) |
| C | Pyramiding trend | LONG_ONLY | repeated admission + position averaging + insufficient-funds rejections |
| D | Short z-score-of-ratio | SHORT_ONLY | short-side admission + 1-strategy→3-portfolio fan-out |

These deliberately over-extend / trade at a loss to saturate engine paths. They
must never be mistaken for real strategies — the `evals/` home makes that
unambiguous.

## One-shot data fetch

`tools/fetch_binance_5m.py` is a hardened one-shot (kept in-repo, re-runnable,
NOT on the engine run path). Its OUTPUT — the committed `data/*_5m.csv` files in
the exact Binance-kline schema `CsvPriceStore` parses — is the durable artifact.

```bash
poetry run python evals/tools/fetch_binance_5m.py --days 180   # refetch
poetry run python evals/tools/validate_csv.py                  # validate
```

## Runners

```bash
poetry run python evals/runners/run_w1_benchmark.py   # W1: asserts >0 trades, prints breakdown + timing/mem
poetry run python evals/runners/run_w2_sweep.py       # W2: {1,10,50} symbol scaling points
```

Both capture wall-clock (`time.perf_counter`) and peak memory (`tracemalloc`).
Determinism: seed 42 throughout (the engine's `performance.rng_seed`).
