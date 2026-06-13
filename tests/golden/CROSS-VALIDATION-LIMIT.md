# LIMIT-Entry Cross-Validation Report (D-07)

Committed **evidence** that iTrader's NEW crafted LIMIT-entry golden reproduces across independent backtest engines (Phase 5, D-07). This file is **evidence, NOT the oracle** and is **NOT wired into `make test` or CI** — the frozen e2e leaf `tests/e2e/matching/entries/limit_entry_crossval/golden/` is the regression lock (frozen ONLY after owner sign-off — see the sign-off block appended below).

## Force-Match Configuration

- **Dataset:** `data/BTCUSD_1d_ohlcv_2018_2026.csv` (the REAL BTCUSD golden CSV)
- **Window:** 2018-09-01 -> 2018-09-20 (pinned, hand-derivable)
- **Strategy:** crafted minimal `LimitEntryStrategy` — a date-keyed `buy_limit` (NOT SMA_MACD): a RESTING limit at `close * 0.98` (decision 2018-09-02, fills 2018-09-05 — a LATER bar) and a MARKETABLE limit at `close * 1.05` (decision 2018-09-13, fills at the bar OPEN 2018-09-14), each anchoring a percent SL/TP bracket (SL = trigger * 0.95, TP = trigger * 1.15).
- **Capital:** $10,000 starting cash; fees 0; slippage 0; 0.95-of-cash fractional sizing on the limit TRIGGER; long-only single position; next-bar fills.
- **Apples-to-apples metrics:** every engine's headline metrics are recomputed through `itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR is ever read.

### Engines

- iTrader (final Phase-5 engine state) — authoritative baseline
- backtesting.py 0.6.5 (gating)
- backtrader 1.9.78.123 (gating)
- Nautilus: not reconciled — no LIMIT runner wired (No module named 'scripts.crossval.nautilus_limit_run') (non-gating)

## Fill-Algebra Agreement (the D-07 anchor)

A BUY limit fills at `min(open, limit)` (limit-or-better) across all three engines BY CONSTRUCTION — iTrader's `MatchingEngine._evaluate` == backtesting.py `_process_orders` == backtrader bracket Limit. So:

- **Resting limit (2018-09-02 decision):** the limit rests through 09-03 / 09-04 (their lows stay above the trigger) and fills on 2018-09-05 — a LATER bar, AT the trigger 7155.9698 (in-bar touch). Entry dates agree on all engines.
- **Marketable limit (2018-09-13 decision):** the trigger 6811.749 sits ABOVE the next bar's open (6487.39), so the limit GAPS THROUGH and fills at the better OPEN 6487.39 — open-vs-limit pinned. Entry dates agree on all engines.

## Trade-Level Reconciliation (PRIMARY)

Each engine's trade log aligned by trade index against iTrader's. `OK` = entry/exit dates match; `SHIFT` = timing differs; `MISSING` = no trade at this index.

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2018-09-05 | 2018-09-05 | 2018-09-05 | 2018-09-06 | 2018-09-05 | 2018-09-06 | SHIFT | SHIFT |
| 1 | 2018-09-14 | 2018-09-14 | 2018-09-14 | 2018-09-15 | 2018-09-14 | 2018-09-15 | SHIFT | SHIFT |

## Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader baseline at a 1% relative tolerance.

| Metric | iTrader (frozen) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| final_equity | 9503.442073 | 9368.730131 (DIVERGE) | 9369.792413 (DIVERGE) |
| trade_count | 2.000000 | 2.000000 (PASS) | 2.000000 (PASS) |
| cagr | -0.605246 | -0.695790 (DIVERGE) | -0.695160 (DIVERGE) |
| max_drawdown | -0.049656 | -0.063127 (DIVERGE) | -0.063021 (DIVERGE) |
| profit_factor | 0.000000 | 0.000000 (PASS) | 0.000000 (PASS) |
| sharpe | -4.481712 | -4.475935 (PASS) | -4.467650 (PASS) |
| sortino | -4.470484 | -4.465036 (PASS) | -4.457222 (PASS) |
| win_rate | 0.000000 | 0.000000 (PASS) | 0.000000 (PASS) |

## Divergence Disposition

**Known LEGITIMATE-DIFFERENCE — same-bar protective-SL timing (A1).** The crafted resting limit fills and its SL trigger is touched on the SAME bar. iTrader fills the protective SL intrabar (parents-before-children, MatchingEngine pass-1-then-pass-2 against the same bar's low), so the exit is stamped on the entry bar. BOTH gating engines defer the contingent SL to the NEXT bar (backtesting.py issue #119 — "can't assert the precise intra-candle price movement"; backtrader's bracket children evaluate from the next bar). The two gating engines AGREE with each other; the iTrader-vs-gating exit-date delta and the resulting realised_pnl/equity delta are this single, well-understood intrabar-SL semantics difference — NOT an entry-fill-algebra divergence. The ENTRY fills + entry dates (the D-07 claim) agree across all three engines.

10 divergence row(s) flagged by the reconcile helpers (the same-bar-SL difference above accounts for the trade-timing + the length-sensitive metric rows):

### Divergence 1: [trade_timing] backtesting.py

- **Observation:** trade #0: backtesting.py SHIFT (iTrader entry 2018-09-05 exit 2018-09-05; backtesting.py entry 2018-09-05 exit 2018-09-06)
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 2: [trade_timing] backtesting.py

- **Observation:** trade #1: backtesting.py SHIFT (iTrader entry 2018-09-14 exit 2018-09-14; backtesting.py entry 2018-09-14 exit 2018-09-15)
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 3: [trade_timing] backtrader

- **Observation:** trade #0: backtrader SHIFT (iTrader entry 2018-09-05 exit 2018-09-05; backtrader entry 2018-09-05 exit 2018-09-06)
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 4: [trade_timing] backtrader

- **Observation:** trade #1: backtrader SHIFT (iTrader entry 2018-09-14 exit 2018-09-14; backtrader entry 2018-09-14 exit 2018-09-15)
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 5: [metric] backtesting.py

- **Observation:** final_equity: backtesting.py=9368.730131 vs iTrader=9503.442073
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 6: [metric] backtrader

- **Observation:** final_equity: backtrader=9369.792413 vs iTrader=9503.442073
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 7: [metric] backtesting.py

- **Observation:** cagr: backtesting.py=-0.695790 vs iTrader=-0.605246
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 8: [metric] backtrader

- **Observation:** cagr: backtrader=-0.695160 vs iTrader=-0.605246
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 9: [metric] backtesting.py

- **Observation:** max_drawdown: backtesting.py=-0.063127 vs iTrader=-0.049656
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

### Divergence 10: [metric] backtrader

- **Observation:** max_drawdown: backtrader=-0.063021 vs iTrader=-0.049656
- **Disposition:** LEGITIMATE-DIFFERENCE (same-bar protective-SL timing — see above). Entry fills + entry dates agree.

## Owner Sign-Off (D-07 / Plan 05-04 Task 3)

**Status: APPROVED.**

- **Approved by:** tiziaco (Tiziano Iacovelli) <tiziano.iaco@gmail.com>
- **Date:** 2026-06-13

The project owner has signed off on the verified, externally cross-validated LIMIT-entry run. The owner **explicitly accepts the dispositioned same-bar protective-SL LEGITIMATE-DIFFERENCE (A1)**: iTrader fills the protective SL intrabar (parents-before-children, MatchingEngine pass-1-then-pass-2 against the same bar's low), so the exit is stamped on the entry bar; BOTH gating engines (backtesting.py 0.6.5, backtrader 1.9.78.123) defer the contingent SL to the NEXT bar and **agree with each other**. The iTrader-vs-gating exit-date delta and the resulting realised_pnl / final_equity delta are this single, well-understood intrabar-SL semantics difference — NOT an entry-fill-algebra divergence. The ENTRY fills + entry dates (the D-07 claim) agree across all three engines.

The 10 reconcile-flagged divergence rows above (the same-bar-SL trade-timing rows + the length-sensitive metric rows that follow from them) are ALL dispositioned LEGITIMATE-DIFFERENCE. **0 BUG; no iTrader defect; no re-freeze; iTrader's numbers are kept.**

This sign-off authorizes Plan 05-04 Task 3 to FREEZE the new LIMIT golden and remove the e2e leaf's `xfail` pending-golden marker. The frozen regression lock lives at `tests/e2e/matching/entries/limit_entry_crossval/golden/` (trades.csv + summary.json):

- **Entry A:** 2018-09-05 @ 7155.9698 (resting limit, fills a LATER bar) → SL exit same bar @ 6798.17131
- **Entry B:** 2018-09-14 @ 6487.39 (marketable limit, fills at the bar OPEN) → SL exit same bar @ 6471.16155
- **trade_count:** 2
- **final_equity:** 9503.442073 (total_realised_pnl −496.557927)

The existing SMA_MACD BTCUSD oracle (`tests/integration/test_backtest_oracle.py` — 134 trades / final_equity 46189.87730727451) is unaffected and remains byte-exact: this LIMIT leaf is a SEPARATE, additive regression lock and is NOT wired into the oracle.
