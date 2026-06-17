# Short Scale-In Cross-Validation Report (SCALE-03 / criterion 5, D-08)

Committed **evidence** that iTrader's short **scale-in** accounting — a same-side SELL-add
that re-locks margin to the new `aggregate_notional / leverage`, then a partial BUY-cover that
releases the lock pro-rata and settles first-class short PnL — reconciles across independent
backtest engines (Phase 05.1, Plan 05.1-02, SCALE-03). This file is **evidence, NOT the oracle**
and is **NOT wired into `make test` or CI** — the two parked white-box e2e leaves under
`tests/e2e/short_scale_in/` and `tests/e2e/short_scale_in_partial_cover/` are the regression
lock (they freeze as the parked regression lock ONLY after owner sign-off — see the Owner
Sign-Off block below, currently **PENDING**).

This re-baseline is sequenced AFTER the Plan 05.1-01 admission gate-lift (which lifted the
unconditional short-increase rejection behind `allow_increase`, byte-symmetric to the long
INCREASE gate) — the admitted scale-in path is what is settled and cross-validated here. NO new
settlement branch and NO sizing change were introduced: the SELL-add settles through the EXISTING
side-agnostic margin SCALE-IN branch at `portfolio.py:423-441` (the `is_increase` derivation at
`:385-388` is True for SHORT+SELL), reusing the Phase-2/3/4 accounting core unchanged (D-02/D-03).

## Force-Match Configuration

- **Synthetic tickers only** (`SCALEUSD` / `SCALPCUSD`) — NEVER BTCUSD, so the spot oracle stays
  byte-exact (134 / 46189.87730727451, D-11). The short scale-in is short-dark relative to the
  LONG_ONLY oracle and MUST NOT drift it.
- **Capital:** $100k; fees 0; slippage 0; next-bar fills; flat-OHLC so close == the unambiguous mark.
- **Leverage:** the short is UNLEVERED (effective leverage 1 — the SignalIntent carries no leverage),
  modeled as `margin = 1 / leverage` (backtesting.py) and `comminfo leverage` (backtrader) — the same
  `locked_margin = aggregate_notional / L` basis iTrader re-locks on each add.
- **Scale-in modeling.** A scale-in is two sequential same-side SELL fills at the same price (100),
  which BOTH gating engines represent as a single averaged short position (averaged entry 100, total
  size 20). iTrader's distinguishing behavior — the per-add margin RE-LOCK to the new aggregate
  notional — is asserted by the parked e2e leaf (PRIMARY); the engines reconcile the round-trip
  trade-level entry/exit and the realised PnL on the covered fraction.
- **Apples-to-apples metrics:** every engine's headline is recomputed through
  `itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR/max-drawdown is read.

### Engines

- iTrader (real engine, parked scale-in white-box leaves) — authoritative baseline
- backtesting.py 0.6.5 (gating)
- backtrader 1.9.78.123 (gating)

## The D-08 Oracle Boundary

- **Short scale-in — FULLY cross-validated.** Both gating engines model shorts as a first-class
  direction and leverage as `margin = 1/L`, so the scale-in round-trip reconciles at trade level
  (averaged entry, partial-cover exit) and at the recomputed metric level.
- **The per-add margin RE-LOCK is iTrader-specific accounting (PRIMARY = the parked e2e leaf).**
  backtesting.py and backtrader hold a single averaged short position and do not expose a
  per-fill isolated-margin lock; they corroborate the aggregate notional and the realised PnL on
  the covered fraction. The hand-computed re-lock value (`aggregate_notional / L`: 1000 → 2000 on
  the second add; released pro-rata to 1000 on the half-cover) is asserted in the parked leaves and
  is the PRIMARY oracle for the lock itself — the engines CORROBORATE the position economics around it.

## Scenario: short scale-in then partial cover

Round-trip: SELL-to-open 10 @ 100 → SECOND SELL-add 10 @ 100 (scale to SHORT 20, averaged entry
100) → partial BUY-cover of 10 @ 80 (exit_fraction 0.5), leaving SHORT 10 open. Realised PnL on
the covered fraction = `|covered| × (entry − exit)` = `10 × (100 − 80)` = **200**.

### Trade-Level Reconciliation (PRIMARY)

| # | itrader entry | itrader exit | backtesting.py entry | backtesting.py exit | backtrader entry | backtrader exit | backtesting.py flag | backtrader flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2020-01-03 (avg 100) | 2020-01-07 (cover 80) | 2020-01-03 (avg 100) | 2020-01-07 (cover 80) | 2020-01-03 (avg 100) | 2020-01-07 (cover 80) | OK | OK |

The scaled short opens across 2020-01-03 (first fill) + 2020-01-05 (second add, both @ 100 → averaged
entry 100) and partial-covers at 2020-01-07 @ 80. Both gating engines match iTrader to the bar on the
averaged-entry open and the partial-cover exit, and agree the realised PnL on the covered 10 = 200.

### Metric-Level Reconciliation (SECONDARY)

Headline metrics recomputed via `itrader.reporting.metrics` for every engine, compared to the iTrader
baseline at a 1% relative tolerance. (CAVEAT: length-sensitive annualized metrics on these tiny
≤7-bar series are INFORMATIONAL — the trade-level table is the primary gate.)

| Metric | iTrader (parked) | backtesting.py | backtrader |
| --- | --- | --- | --- |
| realised_pnl_covered | 200.000000 | 200.000000 (PASS) | 200.000000 (PASS) |
| trade_count (partial exits) | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |
| aggregate_notional_at_peak | 2000.000000 | 2000.000000 (PASS) | 2000.000000 (PASS) |
| profit_factor | inf | inf (PASS) | inf (PASS) |
| win_rate | 1.000000 | 1.000000 (PASS) | 1.000000 (PASS) |
| max_drawdown | 0.000000 | 0.000000 (PASS) | 0.000000 (PASS) |
| sharpe | INFORMATIONAL | INFORMATIONAL | INFORMATIONAL |
| sortino | INFORMATIONAL | INFORMATIONAL | INFORMATIONAL |

### Divergence Disposition

No trade-level divergence: PRIMARY reconciliation is GREEN on BOTH gating engines (averaged-entry
open + partial-cover exit + realised PnL 200 all match to the bar). The length-sensitive annualized
Sharpe / Sortino rows on the tiny ≤7-bar series carry the documented CAVEAT and are INFORMATIONAL —
consistent with the disposition in `CROSS-VALIDATION-ACCOUNTING.md`. **0 BUG.**

The per-add margin re-lock (1000 → 2000 → pro-rata 1000) is the iTrader-specific isolated-margin
accounting the parked e2e leaf asserts as PRIMARY; the engines do not model a per-fill lock and so
CORROBORATE the surrounding economics rather than byte-matching the lock value.

## Determinism + Oracle Re-Confirmation

- **Determinism double-run — byte-identical.** Two runs of the `short_scale_in` scenario (seeded RNG
  `performance.rng_seed=42` + injected `BacktestClock`) produced byte-identical per-bar
  balance / available / locked / net_quantity / equity tuples:
  `[('100000.00','100000.00','0',None,'100000.00'), ('100000.00','100000.00','0',None,'100000.00'),
  ('100000.00','99000.00','1000.0','10','99000.00'), ('100000.00','99000.00','1000.0','10','99000.00'),
  ('100000.00','98000.00','2000.0','20','98000.00'), ('100000.00','98000.00','2000.0','20','98200.00')]`.
- **SMA_MACD spot oracle — byte-exact.** `poetry run pytest tests/integration/test_backtest_oracle.py`
  is 3/3 green: 134 trades / `final_equity 46189.87730727451` (D-11). The short scale-in is short-dark
  relative to the LONG_ONLY oracle and did NOT drift it (synthetic tickers only, never BTCUSD).
- **mypy --strict — clean.** `poetry run mypy --strict itrader` → `Success: no issues found in 185
  source files`.

## Discretion Parameters Used

- **Synthetic tickers:** `SCALEUSD` (scale-in re-lock leaf), `SCALPCUSD` (scale-in-then-partial-cover
  leaf) — planner discretion, NEVER BTCUSD.
- **Leverage:** UNLEVERED (effective leverage 1) — the lock equals the full aggregate notional, the
  cleanest hand-computable scale-in.
- **borrow_rate:** `Decimal("0")` (a no-carry scale-in path; held-carry is exercised by
  `tests/e2e/short_carry/`).
- **maintenance_margin_rate:** `Decimal("0.01")`; **max_leverage (instrument):** `Decimal("10")`;
  **portfolio max_leverage:** `Decimal("5")`.
- **Capital:** $100k; fees 0; slippage 0; next-bar fills; flat-OHLC.

## This file is EVIDENCE, NOT the oracle

This report is committed cross-validation **evidence**. It is **NOT wired into `make test` or CI**.
The two parked white-box e2e leaves (`tests/e2e/short_scale_in/`,
`tests/e2e/short_scale_in_partial_cover/`) are the regression lock; the hand-computed Decimal
literals in those leaves are the PRIMARY oracle for the per-add margin re-lock and the partial-cover
release. This file freezes the scale-in re-baseline ONLY after explicit owner sign-off (below).

## Owner Sign-Off (D-12)

**Status: PENDING** — awaiting the project owner's explicit sign-off at the Plan 05.1-02 Task 3
blocking human-verify checkpoint.

This is a RESULT-CHANGING, owner-gated re-baseline. The short scale-in scenarios freeze as the
parked regression lock ONLY on the owner's explicit "approved" with full attribution. `auto_advance`
is IGNORED for this gate.

The attribution to be reviewed at the checkpoint:

- **Plan 05.1-01 admission gate-lift** — the short-increase rejection lifted behind `allow_increase`
  (byte-symmetric mirror of the long INCREASE gate; long arm + `portfolio.py` + `sizing_resolver.py`
  untouched).
- **Two parked scale-in scenarios** — `short_scale_in` (aggregate-notional re-lock 1000 → 2000) and
  `short_scale_in_partial_cover` (scale-in then partial cover: pro-rata release to 1000 + realised
  PnL 200 on the covered fraction). Both drive the real SIGNAL → ORDER → FILL → PORTFOLIO path; both
  green.
- **Cross-validation reconciliation (this file)** — trade-level PRIMARY GREEN on backtesting.py 0.6.5
  + backtrader 1.9.78.123 (averaged-entry open, partial-cover exit, realised PnL 200); metric-level
  SECONDARY at 1% tolerance with the tiny-series caveat; 0 BUG.
- **Determinism + oracle** — determinism double-run byte-identical; SMA_MACD spot oracle byte-exact
  (134 / 46189.87730727451); mypy --strict clean (185 files).

On owner approval, this block is updated with the owner attribution (name, email, date) and the two
scale-in scenario leaves are frozen as the parked regression lock (a FROZEN freeze-provenance banner
citing the sign-off date is added to each leaf).

<!-- OWNER-ATTRIBUTION-PLACEHOLDER: replaced with "Approved-by: <name> (<email>), <date>" on sign-off -->
