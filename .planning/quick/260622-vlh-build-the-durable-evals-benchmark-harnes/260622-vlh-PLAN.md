---
quick_id: 260622-vlh
type: execute
plan: 01
autonomous: true
files_modified:
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
  - pyproject.toml
  - poetry.lock

must_haves:
  truths:
    - "Four committed 5m USDT CSVs exist and pass CSV validation (monotonic non-dup index, OHLC invariants, no fabricated flat-bar runs)"
    - "evals/ imports cleanly from the installed itrader package (from itrader.strategy_handler.base import Strategy)"
    - "run_w1_benchmark.py runs end-to-end and asserts a NON-TRIVIAL trade log (>0 fills) across the 4-strategy / 6-portfolio topology"
    - "run_w2_sweep.py runs the synthetic scaling sweep over n_symbols in {1,10,50} and prints wall-clock + peak memory per point"
    - "scalene is present in the dev group of pyproject.toml / poetry.lock"
    - "tests/integration/test_backtest_oracle.py and golden BTCUSD data are untouched"
  artifacts:
    - path: "evals/tools/fetch_binance_5m.py"
      provides: "Hardened one-shot CCXT fetch writing Binance-kline-schema 5m CSVs"
    - path: "evals/tools/validate_csv.py"
      provides: "CSV validation gate (loud failure on bad data)"
    - path: "evals/strategies/a_bracketed_momentum.py"
      provides: "Coverage instrument A — bracketed momentum LONG_ONLY"
    - path: "evals/strategies/b_limit_maker.py"
      provides: "Coverage instrument B — limit-maker mean reversion LONG_ONLY"
    - path: "evals/strategies/c_pyramiding_trend.py"
      provides: "Coverage instrument C — pyramiding trend LONG_ONLY (allow_increase=True)"
    - path: "evals/strategies/d_short_zscore.py"
      provides: "Coverage instrument D — short-only z-score-of-ratio SHORT_ONLY"
    - path: "evals/workloads/synthetic.py"
      provides: "make_synthetic_ohlcv(n_bars, n_symbols, seed=42) GBM sub-bar generator"
    - path: "evals/workloads/w1_topology.py"
      provides: "W1 wiring: 4 strategies / 6 portfolios (P1=A, P2=B, P3=C, P4+P5+P6=D fan-out)"
    - path: "evals/runners/run_w1_benchmark.py"
      provides: "iTrader-only W1 benchmark runner with trade-density assertion"
    - path: "evals/runners/run_w2_sweep.py"
      provides: "W2 synthetic scaling sweep runner"
  key_links:
    - from: "evals/strategies/*"
      to: "itrader.strategy_handler.base.Strategy"
      via: "subclass + sugar factories (buy/sell/buy_limit/sell_stop)"
    - from: "evals/runners/run_w1_benchmark.py"
      to: "BacktestTradingSystem + short-selling wiring recipe"
      via: "csv_paths + post-construction short/margin flag wiring (Task 4 recipe)"
    - from: "evals/runners/run_w1_benchmark.py"
      to: "data/{BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT}_5m.csv"
      via: "csv_paths dict on BacktestTradingSystem"
---

<objective>
Build the durable `evals/` benchmark harness per PERF-BASELINE spike Step 1 — the
harness ONLY (no profiling; Scalene runs are Step 2, explicitly out of scope here).

Deliver: a hardened one-shot CCXT fetch script + CSV validation that produces four
real committed 5m USDT CSVs; the durable `evals/` tree (coverage strategies A–D,
W1 topology wiring, W2 numpy-GBM synthetic generator, and the two iTrader-only
runners); and `scalene` added to the dev group. The harness must import-and-run:
W1 produces a non-trivial trade log across 4 strategies / 6 portfolios; W2 sweeps
synthetic symbol counts.

Purpose: build the durable scoreboard before any optimization. These are long-lived
eval assets regression-tracked every milestone — NOT scratch.

Output: committed `evals/` scaffolding + four `data/*_5m.csv` files + scalene dev dep.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/spikes/PERF-BASELINE.md
@.planning/quick/260622-vlh-build-the-durable-evals-benchmark-harnes/260622-vlh-RECON.md
@./CLAUDE.md
@itrader/strategy_handler/strategies/SMA_MACD_strategy.py

<verified_api_facts>
<!-- All extracted from the live codebase during planning. Treat as LOCKED; do NOT re-investigate the strategy/runner/config APIs. The ONLY thing the executor must re-confirm is that the short-selling recipe below still constructs cleanly (run it). -->

CSV schema `CsvPriceStore` parses (exact header of data/BTCUSD_1d_ohlcv_2018_2026.csv —
the fetch script MUST mirror this header; the store reads 6 of the columns and discards
the rest):
```
Open time,Open,High,Low,Close,Volume,Close time,Quote asset volume,Number of trades,Taker buy base asset volume,Taker buy quote asset volume,Ignore
```
Example data row format (note `Open time` is a parseable datetime string, NOT raw ms-epoch):
`2018-01-01 00:00:00.000000 UTC,13715.65,13818.55,12750.0,13380.0,8609.915844,2018-01-01 23:59:59.999000 UTC,114799747.44197056,105595,3961.938946,52809747.44038045,0`
The store renames `Open/High/Low/Close/Volume` -> `open/high/low/close/volume`, parses
`Open time` via `pd.to_datetime(..., utc=True)`, casts float64, slices `[start,end]`
inclusive. So the fetch script may write `Open time` as either an ISO/space datetime
string OR ms-epoch — both parse. Mirror the existing 12-column header for safety.

Strategy base API — `itrader/strategy_handler/base.py`:
- `class Strategy(ABC)`. Concrete subclasses implement
  `generate_signal(self, ticker: str) -> SignalIntent | None` (line ~422) and `init()` (~231).
- Class-attr authoring surface: `sizing_policy: SizingPolicy` (required), `direction:
  TradingDirection = LONG_ONLY` (line 104), `allow_increase: bool = False` (line 105 —
  set True to pyramid), `name`, window attrs.
- Sugar factories (all take `sl=`, `tp=`, `exit_fraction`):
  - `buy(ticker, sl=None, tp=None, ...)` / `sell(...)` — MARKET (lines 459/473)
  - `buy_limit(ticker, *, price, sl=None, tp=None, ...)` / `sell_limit(...)` — price keyword-only (487/515)
  - `buy_stop(ticker, *, price, ...)` / `sell_stop(...)` — price keyword-only (501/529)
  - `sl`/`tp` coerced via `to_money()`; declaring both -> bracket/OCO.
- `subscribe_portfolio(portfolio_id)` (line 543) — idempotent fan-out; one intent ->
  SignalEvent to every subscribed portfolio, sizing resolved per-portfolio.
- `from itrader.core.enums import TradingDirection` = {LONG_ONLY, LONG_SHORT, SHORT_ONLY}.
- `from itrader.core.sizing import FractionOfCash, FixedQuantity, RiskPercent,
  LeveredFraction, SignalIntent` (frozen dataclasses; Decimal fields).
- Indicators (reuse SMA_MACD pattern): `from itrader.strategy_handler.indicators import
  SMA, MACDHist`; primitives `from itrader.strategy_handler.primitives import crossover,
  crossunder, is_above`. Declare handles in `init()` via `self.indicator(SMA, "close", window)`.

Cancel/modify (Strategy B) — RESOLVED in RECON §3: NOT reachable from `generate_signal()`
(intent is order-ref-free). REACHABLE via the runner's `on_tick(system, time_event)` hook:
`system.order_handler.modify_order(order_id, new_price=...)` / `cancel_order(order_id)`.
B's strategy emits `buy_limit(price=...)`; the W1 runner tracks resting limit IDs and
re-prices/cancels unfilled limits each bar inside on_tick.

Pyramiding (Strategy C) — RESOLVED in RECON §4: set class attr `allow_increase = True`;
repeated same-direction `buy()` on an open long averages in (admission falls through to
sizing). Size with NO cash headroom cap so rejections come from CASH (`FillEvent(REFUSED)`
-> mirror reconcile), not a duplicate guard.

Runner wiring — `itrader/trading_system/backtest_trading_system.py`:
- `BacktestTradingSystem(exchange='binance', start_date=None, end_date='', to_sql=False,
  timeframe='1d', csv_paths: dict[str, str|Path] | None = None, *, engine=None,
  runner=None, signal_store=None)`. `csv_paths` maps TICKER -> CSV path.
- `run(print_summary=True, on_tick: Callable[[system, time_event], None] | None = None)`.
  `on_tick` is the hook B's re-price logic uses.
- `system.strategies_handler.add_strategy(strategy)`.
- `system.portfolio_handler.add_portfolio(user_id=..., name=..., exchange='csv',
  cash=Decimal(...))` -> returns portfolio_id.
- Results after run(): `system.portfolio_handler.get_portfolio(pid)` ->
  `.available_cash()`, `.total_equity()`, positions/transactions; `system.get_signal_records()`.

SHORT-SELLING WIRING RECIPE (Strategy D) — VERIFIED from
`tests/integration/test_pair_flagship_snapshot.py::_build_flagship_system` (the working
short+margin construction path; RECON §6 must-verify is RESOLVED here). The exact 6-step
sequence the W1 runner MUST replicate (order matters — handler flags BEFORE add_strategy):
```
system = BacktestTradingSystem(exchange="csv", csv_paths={...}, start_date=..., end_date=..., timeframe="5m")

# 1. Strategy-handler flags BEFORE add_strategy (LONG_SHORT/SHORT_ONLY registration gate, strategies_handler:361)
sh = system.strategies_handler
sh._allow_short_selling = True
sh._enable_margin = True

# 2. add_strategy for D (after the flags)
sh.add_strategy(strategy_d)

# 3. add_portfolio + subscribe
pid = system.portfolio_handler.add_portfolio(user_id=..., name=..., exchange="csv", cash=Decimal(...))
strategy_d.subscribe_portfolio(pid)

# 4. Per-portfolio trading-rules margin + short flags (model_copy update)
portfolio = system.portfolio_handler.get_portfolio(pid)
portfolio.config = portfolio.config.model_copy(update={
    "trading_rules": portfolio.config.trading_rules.model_copy(update={
        "enable_margin": True, "allow_short_selling": True,
    })})

# 5. Admission + validator margin flags
om = system.order_handler.order_manager
om.admission_manager._enable_margin = True
om.order_validator.enable_margin = True
```
Apply steps 1, 4, 5 ONCE for the whole system; do steps 2-3 per strategy/portfolio.
The LONG_ONLY strategies (A, B, C) do not need the short flags but the system-wide
margin flags being on is harmless for them. Set the handler short flags (step 1) and the
admission/validator margin flags (step 5) before ANY add_strategy / run.
The executor MUST run the runner and confirm this recipe constructs and runs cleanly
before declaring done; if the private-attr names have drifted, re-read
`_build_flagship_system` and `strategies_handler.py` and adapt (do NOT guess).
</verified_api_facts>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Hardened fetch script + CSV validation + four committed 5m CSVs + scalene dev dep</name>
  <files>evals/__init__.py, evals/tools/__init__.py, evals/tools/fetch_binance_5m.py, evals/tools/validate_csv.py, evals/README.md, data/BTCUSDT_5m.csv, data/ETHUSDT_5m.csv, data/SOLUSDT_5m.csv, data/BNBUSDT_5m.csv, pyproject.toml, poetry.lock</files>
  <action>
  Create the `evals/` package root (`evals/__init__.py`, `evals/tools/__init__.py`,
  a short `evals/README.md` documenting the tree and the fetch script as a one-shot).
  Use 4-space indentation throughout `evals/` (new tree — match config/core newer-module
  convention, per CLAUDE.md). All `evals/` code imports from the installed `itrader`
  package via absolute imports.

  Add scalene to the dev group: run `poetry add --group dev scalene` (updates pyproject.toml
  + poetry.lock). Do NOT pin a version unless the resolver requires it.

  Write `evals/tools/fetch_binance_5m.py` — a hardened ONE-SHOT (documented as throwaway-but-kept).
  Do NOT reuse `ccxt_provider.download_data` (RECON §8 confirmed defects). Use `ccxt` directly:
  - `ccxt.binance({'enableRateLimit': True})`.
  - Parameterize the span: `--days` arg, default 180 (~6 months). Compute `since` = now - days,
    `end` = now (use ccxt `exchange.milliseconds()` / `parse8601`).
  - Page `fetch_ohlcv(symbol, '5m', since=cursor, limit=1000)` advancing `since` to last_ts+1
    each page; wrap each call in try/except with exponential backoff (a few retries) so a
    transient network error does not crash a long pull. Stop when a page returns empty or
    cursor passes `end`.
  - Symbols: fetch `BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT`; store as
    `data/{BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT}_5m.csv` (strip the slash).
  - DEDUP by timestamp (dedupe on the open-time column, keep first); ensure strictly
    monotonic increasing timestamps.
  - DROP the last (unclosed) candle (the final row whose close-time has not elapsed).
  - NO ffill / NO resample — preserve real gaps.
  - Write CSV in the EXACT Binance-kline 12-column header mirrored from
    `data/BTCUSD_1d_ohlcv_2018_2026.csv` (see verified CSV schema). `Open time` /
    `Close time` written as the same `... UTC` datetime-string format the existing file uses
    (so `pd.to_datetime(..., utc=True)` parses them). Columns the store ignores may be
    filled from the ccxt response where available, or with `0` / empty where ccxt does not
    supply them (the store discards them) — but the six load-bearing columns
    (`Open time, Open, High, Low, Close, Volume`) MUST be correct real values.

  Write `evals/tools/validate_csv.py` exposing `validate_csv(path) -> None` (raises loudly on
  any violation) plus a `__main__` that validates all four data files. Assertions per spec §7/§12:
  monotonic strictly-increasing non-duplicated datetime index after the store-style parse;
  OHLC invariants per row (low <= open, low <= close, high >= open, high >= close, high >= low);
  NO fabricated flat O=H=L=C runs beyond a sane consecutive threshold (e.g. >5 consecutive
  identical-OHLC bars => fail — real gaps are allowed as missing rows, NOT as fabricated flats);
  all six expected columns present after rename. Bad data must raise (not warn).

  Run the fetch on the MAIN tree (live network I/O — no worktree). After fetch, run the
  validator; it MUST pass on all four files before this task is done.
  </action>
  <verify>
    <automated>poetry run python evals/tools/fetch_binance_5m.py --days 180 && poetry run python evals/tools/validate_csv.py && test -s data/BTCUSDT_5m.csv && test -s data/ETHUSDT_5m.csv && test -s data/SOLUSDT_5m.csv && test -s data/BNBUSDT_5m.csv && poetry run python -c "import tomllib; t=tomllib.load(open('pyproject.toml','rb')); import sys; sys.exit(0 if any('scalene' in str(v).lower() for v in t.get('tool',{}).get('poetry',{}).get('group',{}).get('dev',{}).get('dependencies',{})) else 1)"</automated>
  </verify>
  <done>Four non-empty 5m USDT CSVs exist in data/ in the exact kline schema; validate_csv.py passes (monotonic/dedup/OHLC-invariant/no-fabricated-flats); scalene is in the dev group of pyproject.toml + poetry.lock; golden BTCUSD CSV untouched.</done>
</task>

<task type="auto">
  <name>Task 2: Coverage strategies A, B, C, D</name>
  <files>evals/strategies/__init__.py, evals/strategies/a_bracketed_momentum.py, evals/strategies/b_limit_maker.py, evals/strategies/c_pyramiding_trend.py, evals/strategies/d_short_zscore.py</files>
  <action>
  Create `evals/strategies/` (4-space indent, absolute itrader imports). Each strategy
  subclasses `itrader.strategy_handler.base.Strategy`. These are COVERAGE INSTRUMENTS, not
  alpha — reuse the SMA_MACD signal where possible (same SMA/MACDHist init pattern, same
  crossover trigger) and change ONLY the order plumbing. Tune for trade density even at a
  loss. Each carries a docstring naming the engine path it owns (spec §6) and a banner making
  clear it is a coverage instrument (never a real/product strategy).

  A — `a_bracketed_momentum.py` (spec §4 row A; owns: market fill + bracket/OCO same-bar
  priority + stop & limit trigger + gap-aware fills): `direction = LONG_ONLY`,
  `sizing_policy = FractionOfCash(Decimal("0.95"))`. Reuse the SMA_MACD entry/exit signal but
  EVERY entry returns `self.buy(ticker, sl=..., tp=...)` with BOTH sl and tp derived from the
  current close (e.g. sl a few % below, tp a few % above — compute from the latest bar/indicator
  state available in generate_signal) so each entry declares a bracket/OCO. Instrument: BTCUSDT.

  B — `b_limit_maker.py` (spec §4 row B; owns: resting-limit book at scale + multi-symbol
  fan-out; the cancel/modify lifecycle lives in the RUNNER on_tick, NOT here — RECON §3):
  `direction = LONG_ONLY`, mean-reversion. `generate_signal` returns
  `self.buy_limit(ticker, price=<resting price below current close>, tp=<above>)` on a
  mean-reversion condition (e.g. price below a moving average by some band). Do NOT attempt to
  cancel/re-price inside the strategy (not reachable from generate_signal). Instruments:
  ETHUSDT, SOLUSDT, BNBUSDT (multi-symbol). Add a brief docstring note that the runner's
  on_tick re-prices/cancels its unfilled limits.

  C — `c_pyramiding_trend.py` (spec §4 row C; owns: repeated admission + position averaging +
  insufficient-funds rejections): `direction = LONG_ONLY`, `allow_increase = True` (RECON §4 —
  this is what lets repeated same-direction buys average in instead of being rejected as a
  duplicate). On a trend-continuation condition return `self.buy(ticker, sl=...)` (aggregate
  stop) repeatedly; size with NO cash headroom cap (e.g. FractionOfCash with a large fraction,
  or FixedQuantity) so it over-extends and rejections fire from CASH for free. Instrument:
  BTCUSDT (optionally also SOLUSDT).

  D — `d_short_zscore.py` (spec §4 row D; owns: short-side admission/unfunded-short path +
  1-strategy->3-portfolio fan-out): `direction = SHORT_ONLY`. CHEAP signal — z-score of a
  PRICE RATIO (ETHUSDT/SOLUSDT), NOT cointegration (deliberately cheap so D adds no artificial
  CPU — strategy compute is not framework overhead). Compute a rolling mean/std of the ratio
  and emit `self.sell(ticker)` (and/or `self.sell_stop(ticker, price=...)`) when the z-score is
  extreme. Keep the math minimal. Instrument: ETHUSDT (the ratio uses ETHUSDT/SOLUSDT but the
  ORDER is on ETHUSDT). The short-selling wiring is the RUNNER's job (Task 4 recipe) — the
  strategy only declares `direction = SHORT_ONLY`.

  Export all four classes from `evals/strategies/__init__.py`.

  If any §6 path is found genuinely uncoverable while writing these (e.g. an API truly does
  not support what the spec claims), REPORT it in the SUMMARY — do NOT silently fake coverage.
  </action>
  <verify>
    <automated>poetry run python -c "from evals.strategies import a_bracketed_momentum, b_limit_maker, c_pyramiding_trend, d_short_zscore; from evals.strategies.a_bracketed_momentum import *; from evals.strategies.c_pyramiding_trend import *; from evals.strategies.d_short_zscore import *; print('strategies import OK')"</automated>
  </verify>
  <done>All four strategy modules import cleanly; A declares brackets (sl+tp), B emits buy_limit, C sets allow_increase=True with uncapped sizing, D is SHORT_ONLY with a cheap z-score-of-ratio signal; each module documents the engine path it owns.</done>
</task>

<task type="auto">
  <name>Task 3: W1 topology wiring helper + W2 numpy-GBM synthetic generator</name>
  <files>evals/workloads/__init__.py, evals/workloads/w1_topology.py, evals/workloads/synthetic.py</files>
  <action>
  Create `evals/workloads/` (4-space indent, absolute itrader imports).

  `synthetic.py` — `make_synthetic_ohlcv(n_bars: int, n_symbols: int, seed: int = 42) ->
  dict[str, pd.DataFrame]` (spec §7 W2). NO new dependency — use `numpy.random.default_rng(seed)`
  (numpy already a dep; reuse the performance.rng_seed=42 discipline). Per bar, draw an M-step
  sub-bar GBM path (M a small constant, e.g. 8), then set O=first sub-step, C=last sub-step,
  H=max over sub-steps, L=min over sub-steps, V=positive random draw. The sub-bar step is what
  GUARANTEES the OHLC invariants (L <= O,C <= H) — a naive close-only walk produces invalid bars
  that mislead/crash the matching engine. Return frames keyed by synthetic ticker name
  (e.g. SYN000..SYNnnn), each frame in the SAME column shape `CsvPriceStore`/the feed path
  consumes downstream (so it can flow through the same store/feed). Determinism: same seed =>
  byte-identical frames. Internally assert OHLC invariants hold for every generated bar.

  `w1_topology.py` — a small declarative helper describing the W1 topology so the runner stays
  thin. Export the strategy-to-portfolio map per spec §5: P1=A, P2=B, P3=C, and D fans out to
  P4+P5+P6. Provide the csv_paths dict
  ({'BTCUSDT': 'data/BTCUSDT_5m.csv', 'ETHUSDT': ..., 'SOLUSDT': ..., 'BNBUSDT': ...}) and a
  helper that, given a constructed `BacktestTradingSystem`, applies the short-selling wiring
  recipe (verified facts above) and registers all four strategies + six portfolios with the
  correct subscriptions (A->P1, B->P2, C->P3, D->P4/P5/P6 fan-out via subscribe_portfolio).
  Keep the resting-limit-id tracking state OUT of here (that is the runner's on_tick concern).
  Do NOT call `run()` here — this module only wires.
  </action>
  <verify>
    <automated>poetry run python -c "from evals.workloads.synthetic import make_synthetic_ohlcv; import numpy as np; f=make_synthetic_ohlcv(200, 3, seed=42); g=make_synthetic_ohlcv(200, 3, seed=42); assert set(f.keys()), 'no frames'; [assert_ohlc(df) for df in f.values()] if False else None; import pandas as pd; [print(k, df.shape) for k,df in f.items()]; assert all((f[k].values==g[k].values).all() for k in f), 'non-deterministic'; assert all(((df['low']<=df['open'])&(df['low']<=df['close'])&(df['high']>=df['open'])&(df['high']>=df['close'])&(df['high']>=df['low'])).all() for df in f.values()), 'OHLC invariant violated'; print('synthetic OK, deterministic, invariants hold')"; poetry run python -c "from evals.workloads import w1_topology; print('w1_topology import OK')"</automated>
  </verify>
  <done>make_synthetic_ohlcv produces deterministic (seed=42 reproducible) OHLCV frames whose OHLC invariants hold for every bar; w1_topology imports and exposes the P1=A/P2=B/P3=C/P4+P5+P6=D map + csv_paths + a wiring helper that applies the short-selling recipe.</done>
</task>

<task type="auto">
  <name>Task 4: W1 + W2 runners with smoke-run proving non-trivial trade density</name>
  <files>evals/runners/__init__.py, evals/runners/run_w1_benchmark.py, evals/runners/run_w2_sweep.py, evals/results/.gitkeep, evals/results/README.md</files>
  <action>
  Create `evals/runners/` (4-space indent, absolute itrader imports) and the
  `evals/results/` placeholder (`.gitkeep` + a short README noting that
  PERF-BASELINE-RESULTS.md is written in Step 2, not now).

  `run_w1_benchmark.py` — iTrader-only W1 benchmark (spec §5/§11):
  - Construct `BacktestTradingSystem(exchange="csv", csv_paths=<from w1_topology>,
    start_date=..., end_date=..., timeframe="5m")` over the full 5m span. Pick a start/end
    that covers the fetched data (read the CSVs' first/last timestamps, or pass the full range).
  - BEFORE add_strategy: apply the short-selling recipe (verified facts above) — set
    `sh._allow_short_selling = True`, `sh._enable_margin = True`, and the admission/validator
    margin flags. The executor MUST run this and confirm the recipe still constructs cleanly;
    if private-attr names drifted, re-read `_build_flagship_system` + `strategies_handler.py`
    and adapt (do NOT guess).
  - Register the topology via the w1_topology helper: A->P1, B->P2, C->P3, D->P4/P5/P6 fan-out,
    each portfolio with its own cash (Decimal). Apply per-portfolio trading_rules margin/short
    flags (recipe step 4) for the portfolios D feeds (P4/P5/P6) at minimum.
  - Implement the `on_tick(system, time_event)` hook that owns Strategy B's cancel/modify
    lifecycle (RECON §3): track B's resting limit order IDs each bar and re-price/cancel
    unfilled limits via `system.order_handler.modify_order(order_id, new_price=...)` /
    `cancel_order(order_id)`. This is what makes the cancel/modify coverage claim honest.
  - Capture wall-clock (`time.perf_counter`) around `system.run(print_summary=False,
    on_tick=on_tick)` and PEAK MEMORY via `tracemalloc` (stdlib — start before run, read
    `get_traced_memory()` peak after; no new dep). Print both.
  - ASSERT a NON-TRIVIAL trade log: after run, sum fills/closed-positions/transactions across
    all six portfolios (via get_portfolio(pid) state) and assert the total is > 0 (a benchmark
    that does not trade measures nothing — spec §11). If it is 0, the assertion FAILS loudly so
    the executor tightens strategy thresholds (spec §9 risk 3) rather than shipping a dead
    benchmark. Print a per-portfolio trade-count breakdown so it is clear which §6 paths fired.

  `run_w2_sweep.py` — synthetic scaling sweep (spec §7 W2):
  - Sweep `n_symbols in {1, 10, 50}` at a fixed `n_bars` (e.g. a few thousand). For each point:
    generate frames via `make_synthetic_ohlcv(n_bars, n_symbols, seed=42)`, feed them through
    the same store/feed path (write to temp CSVs in the kline schema OR feed the in-memory
    frames if the path supports it — use whatever the feed path accepts; temp CSVs in the
    kline schema reusing the validated writer is the safe route), wire ONE trivial LONG_ONLY
    strategy subscribed across ALL n_symbols (a single trivial buy-on-condition strategy is
    fine — it is a scaling test, not a realism test), run, and capture wall-clock + peak memory
    (perf_counter + tracemalloc). Print a table of (n_symbols, wall_clock_s, peak_mem_mb).
  - Determinism: seed 42 throughout.
  - This runner does NOT run scalene (that is Step 2). It only produces the timing/memory points.

  Both runners are importable AND runnable as `__main__`. Run BOTH end-to-end as the
  definition of done (spec §11 exit criteria minus profiling): W1 must assert >0 trades; W2
  must print three scaling points.
  </action>
  <verify>
    <automated>poetry run python evals/runners/run_w1_benchmark.py && poetry run python evals/runners/run_w2_sweep.py && poetry run python -c "import evals.runners.run_w1_benchmark, evals.runners.run_w2_sweep; print('runners import OK')"</automated>
  </verify>
  <done>run_w1_benchmark.py runs end-to-end over the real 5m CSVs, applies the short-selling recipe, drives B's on_tick cancel/modify, prints wall-clock + peak memory, and ASSERTS >0 total trades across the 6 portfolios (with a per-portfolio breakdown); run_w2_sweep.py runs the {1,10,50}-symbol synthetic sweep and prints a wall-clock+memory point per symbol count; evals/results/ placeholder exists.</done>
</task>

</tasks>

<verification>
- `poetry run python evals/tools/validate_csv.py` passes on all four committed CSVs.
- `poetry run python evals/runners/run_w1_benchmark.py` runs and asserts >0 trades across the 4-strategy / 6-portfolio topology.
- `poetry run python evals/runners/run_w2_sweep.py` prints a scaling point for n_symbols in {1,10,50}.
- `scalene` is present in the dev group (`pyproject.toml` + `poetry.lock`).
- `tests/integration/test_backtest_oracle.py` and `data/BTCUSD_1d_ohlcv_2018_2026.csv` are byte-unchanged (`git status` shows them unmodified).
- All `evals/` code uses 4-space indentation and absolute `from itrader...` imports.
- NO profiling / Scalene invocation was run (that is Step 2, out of scope).
</verification>

<success_criteria>
- Durable `evals/` tree committed: strategies A-D, workloads (W1 topology + W2 synthetic), runners, results placeholder.
- Four real 5m USDT CSVs committed under `data/`, validated, in the exact CsvPriceStore kline schema.
- W1 import-and-runs with a non-trivial trade log; W2 import-and-runs producing a scaling curve over {1,10,50}.
- scalene added to dev group.
- Golden BTCUSD oracle + data untouched.
- Any genuinely-uncoverable §6 path reported (not silently faked).
</success_criteria>

<output>
Create `.planning/quick/260622-vlh-build-the-durable-evals-benchmark-harnes/260622-vlh-SUMMARY.md` when done.
</output>
