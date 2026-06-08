# SMA_MACD Cross-Validation Report

Committed **evidence** that iTrader's SMA_MACD backtest numbers are trustworthy across independent backtest engines (M5-10). This file is **evidence, NOT the oracle** (D-11) and is **NOT wired into `make test` or CI** (D-10) — the frozen `tests/golden/*` artifacts remain authoritative.

## Force-Match Configuration (D-01)

- **Dataset:** `data/BTCUSD_1d_ohlcv_2018_2026.csv`
- **Window:** 2018-01-01 -> 2026-06-03
- **Strategy:** SMA_MACD (short=50, long=100, MACD fast=6 slow=12 sign=3); the SMA filter gates BOTH entry AND exit (the verbatim quirk).
- **Capital:** $10,000 starting cash; fees 0; slippage 0; next-bar-open fills.
- **Shared indicators (D-03):** SMA/MACD precomputed ONCE via iTrader's exact `ta` calls and injected into every engine, so indicator-library divergence is zero by construction and only fill/sizing semantics can diverge.
- **Apples-to-apples metrics (D-04 / RESEARCH risk #5):** every engine's headline metrics are recomputed through `itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR is ever read.

### Engines

- iTrader (frozen golden oracle) — authoritative baseline
- backtesting.py 0.6.5 (gating)
- backtrader 1.9.78.123 (gating)
- Nautilus: reconciled (nautilus-trader 1.227.0) (non-gating)

## Trade-Level Reconciliation (D-02 — PRIMARY)

The primary gate: each engine's trade log aligned by trade index against iTrader's frozen trade log. `OK` = entry/exit dates match; `SHIFT` = timing differs; `MISSING` = the engine has no trade at this index. (Table truncated to the first 20 rows plus every divergent row.)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | nautilus entry | nautilus exit | backtesting.py flag | backtrader flag | nautilus flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2018-09-13 | 2019-03-12 | 2018-09-13 | 2019-03-12 | 2018-09-13 | 2019-03-12 | 2018-09-13 | 2019-03-12 | OK | OK | OK |
| 1 | 2019-03-16 | 2019-03-22 | 2019-03-16 | 2019-03-22 | 2019-03-16 | 2019-03-22 | 2019-03-16 | 2019-03-22 | OK | OK | OK |
| 2 | 2019-03-28 | 2019-04-10 | 2019-03-28 | 2019-04-10 | 2019-03-28 | 2019-04-10 | 2019-03-28 | 2019-04-10 | OK | OK | OK |
| 3 | 2019-04-24 | 2019-04-26 | 2019-04-24 | 2019-04-26 | 2019-04-24 | 2019-04-26 | 2019-04-24 | 2019-04-26 | OK | OK | OK |
| 4 | 2019-05-02 | 2019-05-18 | 2019-05-02 | 2019-05-18 | 2019-05-02 | 2019-05-18 | 2019-05-02 | 2019-05-18 | OK | OK | OK |
| 5 | 2019-05-27 | 2019-05-31 | 2019-05-27 | 2019-05-31 | 2019-05-27 | 2019-05-31 | 2019-05-27 | 2019-05-31 | OK | OK | OK |
| 6 | 2019-06-11 | 2019-06-28 | 2019-06-11 | 2019-06-28 | 2019-06-11 | 2019-06-28 | 2019-06-11 | 2019-06-28 | OK | OK | OK |
| 7 | 2019-06-29 | 2019-06-30 | 2019-06-29 | 2019-06-30 | 2019-06-29 | 2019-06-30 | 2019-06-29 | 2019-06-30 | OK | OK | OK |
| 8 | 2019-07-09 | 2019-07-12 | 2019-07-09 | 2019-07-12 | 2019-07-09 | 2019-07-12 | 2019-07-09 | 2019-07-12 | OK | OK | OK |
| 9 | 2019-07-20 | 2019-07-24 | 2019-07-20 | 2019-07-24 | 2019-07-20 | 2019-07-24 | 2019-07-20 | 2019-07-24 | OK | OK | OK |
| 10 | 2019-07-30 | 2019-08-11 | 2019-07-30 | 2019-08-11 | 2019-07-30 | 2019-08-11 | 2019-07-30 | 2019-08-11 | OK | OK | OK |
| 11 | 2019-08-20 | 2019-08-22 | 2019-08-20 | 2019-08-22 | 2019-08-20 | 2019-08-22 | 2019-08-20 | 2019-08-22 | OK | OK | OK |
| 12 | 2019-08-24 | 2019-08-25 | 2019-08-24 | 2019-08-25 | 2019-08-24 | 2019-08-25 | 2019-08-24 | 2019-08-25 | OK | OK | OK |
| 13 | 2019-08-27 | 2019-08-29 | 2019-08-27 | 2019-08-29 | 2019-08-27 | 2019-08-29 | 2019-08-27 | 2019-08-29 | OK | OK | OK |
| 14 | 2019-09-02 | 2019-09-09 | 2019-09-02 | 2019-09-09 | 2019-09-02 | 2019-09-09 | 2019-09-02 | 2019-09-09 | OK | OK | OK |
| 15 | 2019-09-13 | 2019-09-16 | 2019-09-13 | 2019-09-16 | 2019-09-13 | 2019-09-16 | 2019-09-13 | 2019-09-16 | OK | OK | OK |
| 16 | 2020-02-07 | 2020-02-11 | 2020-02-07 | 2020-02-11 | 2020-02-07 | 2020-02-11 | 2020-02-07 | 2020-02-11 | OK | OK | OK |
| 17 | 2020-02-12 | 2020-02-14 | 2020-02-12 | 2020-02-14 | 2020-02-12 | 2020-02-14 | 2020-02-12 | 2020-02-14 | OK | OK | OK |
| 18 | 2020-02-24 | 2020-02-25 | 2020-02-24 | 2020-02-25 | 2020-02-24 | 2020-02-25 | 2020-02-24 | 2020-02-25 | OK | OK | OK |
| 19 | 2020-03-03 | 2020-03-09 | 2020-03-03 | 2020-03-09 | 2020-03-03 | 2020-03-09 | 2020-03-03 | 2020-03-09 | OK | OK | OK |
| ... | _114 aligned rows omitted_ |

## Metric-Level Reconciliation (D-04 — SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader frozen column. `PASS`/`DIVERGE` flag uses a relative tolerance of 1% vs the iTrader baseline.

| Metric | iTrader (frozen) | backtesting.py | backtrader | nautilus |
| --- | --- | --- | --- | --- |
| final_equity | 46189.877307 | 46027.303135 (PASS) | 46189.877307 (PASS) | 46287.240000 (PASS) |
| trade_count | 134.000000 | 134.000000 (PASS) | 134.000000 (PASS) | 134.000000 (PASS) |
| cagr | 0.199100 | 0.198599 (PASS) | 0.199100 (PASS) | 0.199400 (PASS) |
| max_drawdown | -0.538257 | -0.538253 (PASS) | -0.538257 (PASS) | -0.538347 (PASS) |
| profit_factor | 1.291150 | 1.289743 (PASS) | 1.291150 (PASS) | 1.280498 (PASS) |
| sharpe | 0.658361 | 0.656809 (PASS) | 0.657868 (PASS) | 0.657985 (PASS) |
| sortino | 1.038504 | 1.025097 (DIVERGE) | 1.026906 (DIVERGE) | 1.025410 (DIVERGE) |
| win_rate | 0.365672 | 0.365672 (PASS) | 0.365672 (PASS) | 0.358209 (DIVERGE) |

## Per-Divergence Root-Cause (filled by 08-08)

4 divergence(s) flagged. Each stub below is for 08-08 (D-05) to complete with a root-cause analysis — this plan (08-07) does NOT root-cause or re-freeze.

### Divergence 1: [metric] backtesting.py

- **Observation:** sortino: backtesting.py=1.025097 vs iTrader=1.038504
- **Cause:** _(to be filled by 08-08)_
- **Disposition:** _(to be filled by 08-08)_
- **Re-freeze:** _(to be filled by 08-08)_

### Divergence 2: [metric] backtrader

- **Observation:** sortino: backtrader=1.026906 vs iTrader=1.038504
- **Cause:** _(to be filled by 08-08)_
- **Disposition:** _(to be filled by 08-08)_
- **Re-freeze:** _(to be filled by 08-08)_

### Divergence 3: [metric] nautilus

- **Observation:** sortino: nautilus=1.025410 vs iTrader=1.038504
- **Cause:** _(to be filled by 08-08)_
- **Disposition:** _(to be filled by 08-08)_
- **Re-freeze:** _(to be filled by 08-08)_

### Divergence 4: [metric] nautilus

- **Observation:** win_rate: nautilus=0.358209 vs iTrader=0.365672
- **Cause:** _(to be filled by 08-08)_
- **Disposition:** _(to be filled by 08-08)_
- **Re-freeze:** _(to be filled by 08-08)_
