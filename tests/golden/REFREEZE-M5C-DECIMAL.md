# M5c Golden Re-freeze — Golden-Path Decimal Cleanup (D-06/D-08, D-11, D-21/D-23)

**Plan:** 08-03 — the M5c Decimal re-freeze (branch a, SHIFT).
**Status:** APPROVED — owner typed "approved" at the D-08/D-11 blocking
checkpoint (2026-06-08). The re-frozen goldens, the updated oracle assertions
and this note land as ONE commit (D-21).

## WHAT changed

No matching, sizing, or trade-structure code changed in this plan. The result
shift is purely the **golden-path float→Decimal cleanup** that landed in
08-01/08-02 and is being re-frozen here:

- **08-01** — `Portfolio.total_market_value` / `total_equity` /
  `total_unrealised_pnl` / `total_realised_pnl` / `total_pnl` now return
  `Decimal` (they previously coerced to `float`). The float boundary moved out
  to the statistical-ratio metric *inputs* only; the result-bearing aggregate
  arithmetic is now Decimal end-to-end. `MetricsManager` money fields are
  Decimal end-to-end (ratio math stays float at the metric input). The
  `EnhancedOrderValidator` golden-path cash checks compare native Decimal
  instead of `float(order.price)` / `float(order.quantity)`.
- **08-02** — the `mypy --strict` fan-out sweep confirmed the 08-01 retype was
  type-inert at both cross-file consumers (151 files clean) and documented the
  single remaining `Decimal → float` serialization boundary in
  `scripts/run_backtest.py::build_summary` / `build_equity_curve` (`%.10f`
  CSV / `json.dump(..., sort_keys=True)`).

Because the aggregate equity is now summed in Decimal before the single
`float(Decimal(...))` serialization step — rather than accumulating float
rounding across thousands of bars — a handful of equity-curve points settle on
a different last binary bit, and the three ratio metrics derived from the
equity series move by ~1 ULP. Nothing else moves.

Consequences visible in the reference output:

- **`trades.csv` is BYTE-IDENTICAL to the prior golden** — all 134 trades keep
  their entry/exit dates, sides, pair, quantities, fills, realised PnL and
  slippage columns to the last serialized digit. No trade was added, dropped,
  or re-sized. (The 08-01 validator retype was admit/reject-inert — the
  identical trade set proves it.)
- **Headline money is byte-exact (delta = 0.0):** `final_equity` /
  `final_cash` = 46189.87730727451, `total_realised_pnl` = 36189.87730727451,
  `starting_cash` = 10000.0, `trade_count` = 134. The float coercion at the
  *summary* boundary was already presentational for these aggregates.
- **`equity.csv` shifts in 19 of 3076 rows** on `total_equity` (and the 8 of
  those rows whose `total_pnl` is derived from it). The timestamp grid is
  identical (3076 points). `cash_balance`, `positions_value`,
  `unrealized_pnl`, `realized_pnl`, `open_positions_count` and
  `portfolio_return` are byte-identical. Max abs delta on `total_equity` is
  **1.019e-10**, max relative delta **1.003e-14** — i.e. the 10th decimal of
  the `%.10f` serialization, the float round-off the Decimal sum eliminates.
- **`summary.json` metrics move ~1 ULP on three ratios** derived from the
  equity series; `cagr`, `profit_factor` and `win_rate` are unchanged.

## Old vs new — headline numbers

| Metric | Old golden (M5b re-freeze 2) | New reference (M5c Decimal) | Delta |
|---|---|---|---|
| Trade count | 134 | 134 | 0 |
| Final equity | 46189.87730727451 | 46189.87730727451 | 0.0 (byte-exact) |
| Final cash | 46189.87730727451 | 46189.87730727451 | 0.0 (byte-exact) |
| Total realised PnL | 36189.87730727451 | 36189.87730727451 | 0.0 (byte-exact) |
| Starting cash | 10000.0 | 10000.0 | — |
| Equity points | 3076 | 3076 | 0 |
| metrics.cagr | 0.19910032815485068 | 0.19910032815485068 | 0.0 |
| metrics.max_drawdown | -0.5382568231814071 | -0.538256823181407 | +1.110e-16 (1 ULP) |
| metrics.profit_factor | 1.291149869385797 | 1.291149869385797 | 0.0 |
| metrics.sharpe | 0.6583614133806533 | 0.6583614133806527 | -6.661e-16 (1 ULP) |
| metrics.sortino | 1.0385040387966196 | 1.038504038796619 | -6.661e-16 (1 ULP) |
| metrics.win_rate | 0.3656716417910448 | 0.3656716417910448 | 0.0 |

`trades.csv` carries no headline shift (byte-identical). The only moved values
are 19/3076 `total_equity` points (+8 derived `total_pnl`) in `equity.csv` and
the three equity-derived ratio metrics above.

## Expected-diff attribution (D-08 — one attributable mechanism, no residual)

The shift is **pure Decimal precision** with exactly one mechanism:

- The equity aggregate is now summed in `Decimal` and coerced to `float` once,
  at the `scripts/run_backtest.py` serialization boundary, instead of being
  carried as `float` through the `Portfolio.total_*` properties and
  accumulating IEEE-754 round-off across ~3076 bars. On the 19 affected bars
  the Decimal-clean value rounds to a different 10th decimal under `%.10f`.
- `max_drawdown`, `sharpe` and `sortino` are computed from the equity series,
  so a 1e-10 change in a few equity points moves each by ~1 ULP (1e-16).
  `cagr` (first/last equity ratio), `profit_factor` and `win_rate` (counts /
  PnL sums that are byte-exact) are unaffected.

There is **no trade-structure change** (trades.csv byte-identical, 134 trades,
same identities) and **no unexplained residual** — every moved number is a
last-bit float-vs-Decimal precision effect of the cleanup, nothing else.

Spot-check: the largest equity move is 1.019e-10 absolute on a ~10^4–10^5
equity level → ~1e-14 relative, i.e. one part in the 10th `%.10f` decimal —
consistent with eliminating accumulated float round-off, not with any change
in the underlying positions (cash_balance and positions_value are byte-exact).

## Run configuration (D-09)

Generated by the pinned oracle script `scripts/run_backtest.py`
(`poetry run python scripts/run_backtest.py`, a.k.a. `make backtest`): dataset
`data/BTCUSD_1d_ohlcv_2018_2026.csv`, window 2018-01-01 → 2026-06-03, $10,000
starting cash, zero fee / zero slippage (exchange defaults pinned by the
script — `final_cash == final_equity` and PnL reconciles with zero
commission). Serialization knobs unchanged: `FLOAT_FORMAT = "%.10f"`,
`json.dump(..., indent=2, sort_keys=True)`.

## Determinism

Verified at the re-freeze commit gate: two consecutive `make backtest` runs
produced **byte-identical** `trades.csv`, `equity.csv` and `summary.json`
(seeded RNG + injected clock hold under the Decimal cleanup). The shift is a
stable property of the new arithmetic, not run-to-run noise.

## Scope note

This is the **M5c Decimal re-freeze** — the post-M5 numeric re-baseline point
(PROJECT.md two-point rule). These clean Decimal numbers are the
cross-validation baseline that 08-04+ reconciles `backtesting.py` /
`backtrader` (and the optional non-gating `nautilus_trader`, D-12) against. A
further **conditional** bug-fix re-freeze (08-08) may follow ONLY if
cross-validation traces a genuine iTrader defect (D-05); the last frozen state
is the final authoritative oracle (D-11). The run-path integration test
(`tests/integration/test_backtest_oracle.py`) is re-locked EXACT against this
settled set in the same commit (Pitfall 6 — assertions and goldens move
together).
