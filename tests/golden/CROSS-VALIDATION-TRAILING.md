# Trailing-Stop Cross-Validation Report (TRAIL-03, D-TRAIL-1)

Committed **evidence** that iTrader's engine-native trailing stop — the `MatchingEngine` resting-order ratchet subsystem (a DIFFERENT subsystem from the Phase-4 portfolio/cash accounting core) — reconciles across independent backtest engines (Phase 5, TRAIL-03). This file is **evidence, NOT the oracle** and is **NOT wired into `make test` or CI** — the white-box e2e leaves under `tests/e2e/{trailing_long,trailing_short}/` are the regression lock (this phase's OWN result-changing trailing golden re-baseline freezes ONLY after owner sign-off — see the Owner Sign-Off block below, currently UNSIGNED).

## Force-Match Configuration

- **Synthetic ticker only** (`TRAILUSD`) — NEVER BTCUSD, so the SMA_MACD spot oracle stays byte-exact (134 / 46189.87730727451, D-11). Trailing is oracle-dark on the spot path.
- **Scenario:** a LONG strategy declares a 10% PERCENT trailing-SL bracket (`PercentFromFill` carrying a trail descriptor). A single MARKET BUY fills at the next bar's open (100); the trailing SL rests as an engine-native `TRAILING_STOP` seeded from the entry fill (D-TRAIL-3), ratchets UP across rising closed-bar highs, then a single sharp drop bar triggers the RATCHETED level (112 high-water-mark × 0.90 = 100.8).
- **Capital:** $100k; fees 0; slippage 0; FixedQuantity(10); next-bar fills; long-only single position.
- **Apples-to-apples metrics:** every engine's headline is recomputed through `itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR is read.

### Engines

- iTrader (real engine, trailing white-box runner `trailing_run.run_itrader`) — authoritative baseline
- backtesting.py 0.6.5 (gating)
- backtrader 1.9.78.123 (gating)

## Oracle Trailing API — A1 Resolution (verified this run)

[ASSUMED A1] (both oracles expose a trailing-stop API trailing off the CLOSE, active next bar) was VERIFIED against the installed versions at runner-implementation time:

- **backtesting.py 0.6.5** — `backtesting.lib.TrailingStrategy` EXISTS with `set_trailing_sl(n_atr=6)` and `set_trailing_pct(pct)`. Read from the installed source: `TrailingStrategy.next()` ratchets `trade.sl = max(trade.sl, Close[i] - atr[i]*n_atr)` — confirming a **CLOSE-basis** trail. The percent helper `set_trailing_pct` is documented INEXACT (converts pct to ATR units via `mean(Close*pct/atr)`), so the runner force-matches an EXACT percent-of-close ratchet directly (`trade.sl = max(trade.sl, Close*(1-pct))`), the same close-basis convention with an exact distance.
- **backtrader 1.9.78.123** — `bt.Order.StopTrail` (enum 5) and `StopTrailLimit` (enum 6) EXIST; `sell(exectype=StopTrail, trailpercent=...)` is supported (the `trailamount`/`trailpercent` params are present). Native `StopTrail` ratchets off the LATEST price each bar — a **CLOSE-basis** trail. The runner force-matches an exact percent-of-close ratchet via manual stop-order management, the same close-basis convention with an exact distance.

**A1 verdict: CONFIRMED.** Both oracles trail off the CLOSE; iTrader trails off the closed-bar HIGH (D-TRAIL-1). The crafted scenario neutralizes the basis difference (see the disposition below).

## Trade-Level Reconciliation (PRIMARY)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2020-01-03 | 2020-01-07 | 2020-01-03 | 2020-01-07 | 2020-01-03 | 2020-01-07 | OK | OK |

## Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader baseline at a 1% relative tolerance. (CAVEAT: length-sensitive annualized metrics on this tiny ~7-bar series are INFORMATIONAL — the trade-level table is the primary gate.)

| Metric | iTrader (frozen) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| final_equity | 100008.000000 | 100008.000000 (PASS) | 100008.000000 (PASS) |
| trade_count | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |
| cagr | 0.003657 | 0.003657 (PASS) | 0.003657 (PASS) |
| max_drawdown | -0.001119 | -0.001119 (PASS) | -0.001119 (PASS) |
| profit_factor | inf | inf (PASS) | inf (PASS) |
| sharpe | 0.381996 | 0.381996 (PASS) | 0.381996 (PASS) |
| sortino | 0.488443 | 0.488443 (PASS) | 0.488443 (PASS) |
| win_rate | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |

## Divergence Disposition

### Known LEGITIMATE-DIFFERENCE — high-vs-close trail basis (D-TRAIL-1)

**Root cause (NOT a bug):** iTrader ratchets the trailing stop off the CLOSED bar's HIGH (long) / LOW (short) and the level is live for the NEXT bar (D-TRAIL-1 / D-TRAIL-2 — the level on bar N is derived from bars <= N-1, the look-ahead-safety rule mandated by TRAIL-02's "closed-bar extremes"). Both gating oracles trail off the CLOSE. On a bar whose HIGH exceeds its CLOSE, iTrader's water-mark advances further, so iTrader's stop is marginally tighter and could exit a borderline trade ONE bar earlier. This is a documented systematic convention difference, not an arithmetic defect — iTrader's closed-bar-extreme behavior is the CORRECT one per TRAIL-02.

**Why the trade-level table reconciles exactly here:** the crafted scenario uses `high == close` on every ratcheting bar, so the HIGH-based (iTrader) and CLOSE-based (oracle) water-marks COINCIDE; the 10% trail distance is large relative to the gentle intrabar range on the rising leg; and the single drop bar opens above the ratcheted stop while its low pierces far below it, so all three engines gap-fill at the SAME ratcheted stop (100.8) on the SAME bar. The residual high-vs-close gap therefore contributes ZERO trade-timing divergence on this scenario and would only surface (as a <=1-bar SHIFT, within tolerance) on a series where a ratcheting bar's HIGH strictly exceeds its CLOSE.

No divergences flagged by the reconcile helpers — trade-level PRIMARY reconciliation is exact across both gating engines and every headline metric is within the 1% tolerance.

## Owner Sign-Off

**Status: UNSIGNED — PENDING owner review.** This evidence is produced for owner review at the BLOCKING human-verify checkpoint in Plan 05-04 (Task 2). This phase's OWN result-changing trailing golden re-baseline (a SEPARATE re-baseline from the Phase-4 accounting core — a different subsystem) freezes ONLY after the owner reviews the trade-level reconciliation + the high-vs-close disposition above and signs this block with attribution (name + date). The freeze is manual (`workflow.auto_advance` is false — this checkpoint is never auto-approvable). Until then the `tests/e2e/{trailing_long,trailing_short}/` white-box e2e leaves are the regression lock.

> _Approved-by:_ (unsigned)
>
> _Date:_ (unsigned)
