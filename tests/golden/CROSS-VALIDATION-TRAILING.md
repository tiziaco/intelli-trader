# Trailing-Stop Cross-Validation Report (TRAIL-03, D-TRAIL-1)

Committed **evidence** that iTrader's engine-native trailing stop — the `MatchingEngine` resting-order ratchet subsystem (a DIFFERENT subsystem from the Phase-4 portfolio/cash accounting core) — reconciles across independent backtest engines (Phase 5, TRAIL-03). This file is **evidence, NOT the oracle** and is **NOT wired into `make test` or CI** — the white-box e2e leaves under `tests/e2e/{trailing_long,trailing_short}/` are the regression lock (this phase's OWN result-changing trailing golden re-baseline freezes ONLY after owner sign-off — see the Owner Sign-Off block below, **APPROVED 2026-06-17**).

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

## Owner Sign-Off (TRAIL-03, D-TRAIL-1)

**Status: APPROVED** (2026-06-17, project owner — Approved-by: tiziaco (tiziano.iaco@gmail.com)).
The owner accepts the trailing cross-val verdict — **0 BUG; trade-level PRIMARY reconciliation EXACT
across iTrader / backtesting.py / backtrader (single trade, entry 2020-01-03, exit 2020-01-07 at the
ratcheted stop 100.8, PnL +8.0); all 8 headline metrics within the 1% tolerance; the high-vs-close
trail-basis gap dispositioned LEGITIMATE-DIFFERENCE (D-TRAIL-1 — iTrader trails off the closed-bar
HIGH/LOW per the look-ahead-safe TRAIL-02 convention; both oracles trail off the CLOSE), NOT a bug** —
as the basis for this phase's OWN result-changing trailing golden re-baseline freeze (a SEPARATE
re-baseline from the Phase-4 accounting core — the `MatchingEngine` resting-order ratchet is a
different subsystem). The blocking human-verify checkpoint in Plan 05-04 (Task 2) presented this
evidence; the owner explicitly approved the freeze. The freeze is manual (`workflow.auto_advance` is
false — this checkpoint is never auto-approvable).

During the blocking human-verify checkpoint the owner reviewed and APPROVED:
- **Trade-level reconciliation (PRIMARY) is EXACT** — all three engines fill at the SAME ratcheted
  stop (100.8 = 112 high-water-mark × 0.90) on the SAME bar; PnL +8.0; the crafted scenario neutralizes
  the high-vs-close basis difference (`high == close` on every ratcheting bar) so the residual gap
  contributes ZERO trade-timing divergence here.
- **A1 oracle trailing API CONFIRMED** at runner-implementation time — backtesting.py 0.6.5
  `TrailingStrategy.set_trailing_sl`/`set_trailing_pct` (CLOSE-basis ratchet) and backtrader
  1.9.78.123 `bt.Order.StopTrail`/`StopTrailLimit` (`trailpercent`, CLOSE-basis); both runners
  force-match an EXACT percent-of-close ratchet.
- **The high-vs-close gap is a documented LEGITIMATE-DIFFERENCE (D-TRAIL-1), not a defect** —
  iTrader's closed-bar-extreme behavior is the CORRECT one per TRAIL-02; on a series where a
  ratcheting bar's HIGH strictly exceeds its CLOSE it surfaces only as a <=1-bar SHIFT, within tolerance.
- **Full suite green** — `make test` (worktree: `poetry run pytest tests`) passes; no oracle import
  under `tests/` (backtesting/backtrader imports stay SCRIPT-ONLY under `scripts/crossval/`, D-10/T-05-09).
- **mypy --strict clean** across `itrader`.
- **Determinism double-run byte-identical** — `scripts/run_backtest.py` x2 produced identical output.
- **The SMA_MACD spot oracle stayed byte-exact** — `poetry run pytest tests/integration/test_backtest_oracle.py`
  (16 passed, 134 trades / final_equity 46189.87730727451, D-11) — trailing is oracle-dark on the spot
  path; synthetic ticker `TRAILUSD` only, never BTCUSD. (Verify-command correction: the plan originally
  cited `pytest tests/golden -x`, which is WRONG — `tests/golden/` is an artifacts directory and
  collects 0 tests; the correct oracle test is `tests/integration/test_backtest_oracle.py`. Fixed in
  05-04-PLAN.md, commit d6f0de8.)

No code change and no re-baseline of the SMA_MACD goldens were performed (zero BUG rows). This sign-off
authorizes the freeze of this phase's OWN trailing golden re-baseline. The
`tests/e2e/{trailing_long,trailing_short}/` white-box e2e leaves are the regression lock (this file is
EVIDENCE, NOT wired into `make test`/CI).

> _Approved-by:_ tiziaco (tiziano.iaco@gmail.com)
>
> _Date:_ 2026-06-17
