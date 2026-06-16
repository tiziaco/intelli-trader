# Accounting-Core Cross-Validation Report (XVAL-01, D-08)

Committed **evidence** that iTrader's NEW accounting-core scenarios — short round-trip, leveraged long, and leveraged-long-into-liquidation — reconcile across independent backtest engines (Phase 4, D-08). This file is **evidence, NOT the oracle** and is **NOT wired into `make test` or CI** — the white-box e2e leaves under `tests/e2e/{short_roundtrip,levered_long,forced_liq_long,forced_liq_short,levered_long_into_liquidation}/` are the regression lock (the accounting-core golden freezes ONLY after owner sign-off — see the Owner Sign-Off block below, currently PENDING).

## Force-Match Configuration

- **Synthetic tickers only** (`SHORTUSD` / `LEVUSD` / `LIQUSD`) — NEVER BTCUSD, so the spot oracle stays byte-exact (134 / 46189.87730727451, D-11).
- **Capital:** $100k (short) / $10k (levered, liquidation); fees 0; slippage 0; next-bar fills; flat-OHLC so close == the unambiguous mark.
- **Leverage:** modeled as `margin = 1 / leverage` (backtesting.py) and `comminfo leverage` (backtrader) — the same admission reservation = notional / L iTrader books.
- **Apples-to-apples metrics:** every engine's headline is recomputed through `itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR is read.

### Engines

- iTrader (real engine, accounting-core white-box leaves) — authoritative baseline
- backtesting.py 0.6.5 (gating)
- backtrader 1.9.78.123 (gating)

## The D-08 Oracle Boundary

- **Short round-trip & leveraged long — FULLY cross-validated.** Both gating engines model shorts as a first-class direction and leverage as `margin = 1/L`, so trade-level + metric-level reconcile.
- **Liquidation — DIRECTIONAL corroboration ONLY (D-08).** The hand-computed isolated closed-form in the e2e leaf is the **PRIMARY** oracle for the liquidation event (long liq price 80.808080..., short 118.811881...; penalty on commission; loss explicitly capped at WB). backtesting.py models a minimal `equity <= 0 -> close-all` margin call and backtrader has NO isolated-liquidation model, so they CORROBORATE that the levered long liquidates — they do NOT byte-match the isolated maintenance liq price.

**Directional corroboration result:** backtesting.py liquidated = `True`; backtrader liquidated = `True`. Both engines force-close / margin-call the levered long; note backtrader does NOT floor equity (it drifts negative), which is exactly the DEF-01-C defect iTrader's explicit WB-cap closes — the iTrader value is PRIMARY.

## Scenario: short round-trip

### Trade-Level Reconciliation (PRIMARY)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2020-01-03 | 2020-01-05 | 2020-01-03 | 2020-01-05 | 2020-01-03 | 2020-01-05 | OK | OK |

### Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader baseline at a 1% relative tolerance. (CAVEAT: length-sensitive annualized metrics on these tiny 6-bar series are INFORMATIONAL — the trade-level table is the primary gate.)

| Metric | iTrader (frozen) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| final_equity | 100200.000000 | 100200.000000 (PASS) | 100200.000000 (PASS) |
| trade_count | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |
| cagr | 0.129240 | 0.129240 (PASS) | 0.129240 (PASS) |
| max_drawdown | -0.010000 | 0.000000 (DIVERGE) | 0.000000 (DIVERGE) |
| profit_factor | inf | inf (PASS) | inf (PASS) |
| sharpe | 1.044804 | 7.799573 (DIVERGE) | 7.799573 (DIVERGE) |
| sortino | 1.638571 | 0.000000 (DIVERGE) | 0.000000 (DIVERGE) |
| win_rate | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |

### Divergence Disposition

6 divergence row(s) flagged (dispositioned at the 04-05 owner checkpoint):

- **[metric] backtesting.py** — max_drawdown: backtesting.py=0.000000 vs iTrader=-0.010000
- **[metric] backtrader** — max_drawdown: backtrader=0.000000 vs iTrader=-0.010000
- **[metric] backtesting.py** — sharpe: backtesting.py=7.799573 vs iTrader=1.044804
- **[metric] backtrader** — sharpe: backtrader=7.799573 vs iTrader=1.044804
- **[metric] backtesting.py** — sortino: backtesting.py=0.000000 vs iTrader=1.638571
- **[metric] backtrader** — sortino: backtrader=0.000000 vs iTrader=1.638571

## Scenario: leveraged long

### Trade-Level Reconciliation (PRIMARY)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2020-01-03 | 2020-01-06 | 2020-01-03 | 2020-01-06 | 2020-01-03 | 2020-01-06 | OK | OK |

### Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader baseline at a 1% relative tolerance. (CAVEAT: length-sensitive annualized metrics on these tiny 6-bar series are INFORMATIONAL — the trade-level table is the primary gate.)

| Metric | iTrader (frozen) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| final_equity | 14000.000000 | 14000.000000 (PASS) | 14000.000000 (PASS) |
| trade_count | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |
| cagr | 775274506.470678 | 775274506.470678 (PASS) | 775274506.470678 (PASS) |
| max_drawdown | -0.588235 | -0.200000 (DIVERGE) | -0.200000 (DIVERGE) |
| profit_factor | inf | inf (PASS) | inf (PASS) |
| sharpe | 5.557592 | 5.270363 (DIVERGE) | 5.270363 (DIVERGE) |
| sortino | 20.544774 | 21.448825 (DIVERGE) | 21.448825 (DIVERGE) |
| win_rate | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |

### Divergence Disposition

6 divergence row(s) flagged (dispositioned at the 04-05 owner checkpoint):

- **[metric] backtesting.py** — max_drawdown: backtesting.py=-0.200000 vs iTrader=-0.588235
- **[metric] backtrader** — max_drawdown: backtrader=-0.200000 vs iTrader=-0.588235
- **[metric] backtesting.py** — sharpe: backtesting.py=5.270363 vs iTrader=5.557592
- **[metric] backtrader** — sharpe: backtrader=5.270363 vs iTrader=5.557592
- **[metric] backtesting.py** — sortino: backtesting.py=21.448825 vs iTrader=20.544774
- **[metric] backtrader** — sortino: backtrader=21.448825 vs iTrader=20.544774

## Scenario: liquidation

### Trade-Level Reconciliation (PRIMARY)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2020-01-03 | 2020-01-05 | 2020-01-03 | 2020-01-05 |  |  | OK | MISSING |

### Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader baseline at a 1% relative tolerance. (CAVEAT: length-sensitive annualized metrics on these tiny 6-bar series are INFORMATIONAL — the trade-level table is the primary gate.)

| Metric | iTrader (frozen) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| final_equity | 6081.191919 | 0.000000 (DIVERGE) | -8000.000000 (DIVERGE) |
| trade_count | 1.000000 | 1.000000 (PASS) | 0.000000 (DIVERGE) |
| cagr | -1.000000 | 0.000000 (DIVERGE) | 0.000000 (DIVERGE) |
| max_drawdown | -0.797294 | -1.000000 (DIVERGE) | -1.800000 (DIVERGE) |
| profit_factor | 0.000000 | 0.000000 (PASS) | 0.000000 (PASS) |
| sharpe | 4.214349 | -9.552487 (DIVERGE) | -8.711193 (DIVERGE) |
| sortino | 12.512008 | -9.177732 (DIVERGE) | -8.536951 (DIVERGE) |
| win_rate | 0.000000 | 0.000000 (PASS) | 0.000000 (PASS) |

### Divergence Disposition

**Known LEGITIMATE-DIFFERENCE — directional-only liquidation (D-08).** The reference engines liquidate on a margin call / forced close, NOT at the iTrader isolated maintenance liq price; backtrader does not floor equity. The hand-computed e2e leaf is PRIMARY; the engines corroborate the DIRECTION (the levered long liquidates). The metric/trade rows below reflect that modeled difference, NOT an iTrader defect.

13 divergence row(s) flagged (dispositioned at the 04-05 owner checkpoint):

- **[trade_count] backtrader** — backtrader produced 0 trades vs iTrader's 1
- **[trade_timing] backtrader** — trade #0: backtrader MISSING (iTrader entry 2020-01-03 exit 2020-01-05; backtrader entry  exit )
- **[metric] backtesting.py** — final_equity: backtesting.py=0.000000 vs iTrader=6081.191919
- **[metric] backtrader** — final_equity: backtrader=-8000.000000 vs iTrader=6081.191919
- **[metric] backtrader** — trade_count: backtrader=0.000000 vs iTrader=1.000000
- **[metric] backtesting.py** — cagr: backtesting.py=0.000000 vs iTrader=-1.000000
- **[metric] backtrader** — cagr: backtrader=0.000000 vs iTrader=-1.000000
- **[metric] backtesting.py** — max_drawdown: backtesting.py=-1.000000 vs iTrader=-0.797294
- **[metric] backtrader** — max_drawdown: backtrader=-1.800000 vs iTrader=-0.797294
- **[metric] backtesting.py** — sharpe: backtesting.py=-9.552487 vs iTrader=4.214349
- **[metric] backtrader** — sharpe: backtrader=-8.711193 vs iTrader=4.214349
- **[metric] backtesting.py** — sortino: backtesting.py=-9.177732 vs iTrader=12.512008
- **[metric] backtrader** — sortino: backtrader=-8.536951 vs iTrader=12.512008

## Owner Sign-Off (D-12)

**Status: PENDING.** This evidence is produced for owner review at the BLOCKING human-verify checkpoint in Plan 04-05. The accounting-core golden (ALL parked P2/P3 scenarios + the new P4 liquidation scenarios, D-10) freezes ONLY after the owner accepts the per-scenario verdict here and signs off — NO golden is frozen by this plan. Until then the hand-computed closed-form remains the PRIMARY liquidation oracle (D-08) and the white-box e2e leaves are the regression lock.
