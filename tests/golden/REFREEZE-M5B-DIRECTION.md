# M5b Golden Re-freeze 1 — LONG_ONLY Direction Enforcement (D-08/D-11, D-21/D-23)

**Plan:** 07-07 — RESULT-CHANGING re-freeze 1 of 2.
**Status:** APPROVED by the owner (D-23 blocking checkpoint, 2026-06-07).
The guard, the re-frozen goldens, the extended oracle assertions and this
note land as ONE commit (D-21).

## WHAT changed

The OrderManager now enforces the strategy's declared `TradingDirection` at
admission, as step 0 of `process_signal` — BEFORE sizing. An unsized
`LONG_ONLY` SELL with no open long (no position, or `net_quantity <= 0`) is
an **audited REJECTED order** (`triggered_by="admission_direction"`, reason
naming the violation, event-derived timestamp) instead of falling through to
entry sizing and opening a short. `SHORT_ONLY` + BUY with no open short is
rejected symmetrically (oracle-dark). `LONG_SHORT` signals and
explicit-quantity signals pass the gate untouched.

This kills the exact RESEARCH Pitfall-4 mechanism that produced the 2
blessed golden SHORT trades (DEF-01-C, dead structurally): SMA_MACD's short
block is commented out, yet exit-SELL triggers firing while flat were being
fraction-of-cash sized as short entries.

Consequences visible in the reference output:

- **Both golden SHORT rows disappear** — exactly the 2 rows with
  `side == SHORT` in the old `tests/golden/trades.csv`, including the very
  first golden trade (the 9-month 2018-06-10 → 2019-03-12 short, −2176.39
  PnL) and the 2023-10-29 → 2023-11-14 short (−3548.26 PnL).
- **The run produced exactly 3 `admission_direction` REJECTED orders**
  (audited, in order storage): decision bars 2018-06-09 and 2018-09-05
  (the first short's opening SELL, plus the SELL that previously added to
  the open short and now — with the June SELL rejected and the book flat —
  is itself a short-opening attempt), and 2023-10-28 (the second short's
  opening SELL). 3 rejections → 2 removed shorts: the first short absorbed
  two SELL signals.
- **2 NEW LONG trades appear inside the removed-short windows.** The BUY
  signals that previously *covered* the shorts now open longs, which close
  on the old cover dates: 2018-09-13 → 2019-03-12 (bought 6338.62 — the
  same fill that covered the old short — sold 3871.61, −3697.43 PnL across
  the 2018 bear) and 2023-11-10 → 2023-11-14 (bought 36701.10, sold
  36462.93, −224.72 PnL). Trade count is therefore **unchanged at 134**:
  −2 SHORT, +2 LONG.
- **All 132 surviving trades keep their identity (entry/exit dates, side,
  pair) but EVERY one shifts numerically.** See the compounding note below.
- The equity curve keeps its full 3076-point timestamp grid; only the
  values move.

## COMPOUNDING — the diff is NOT just 2 rows

Fraction-of-cash sizing compounds: the first removed short spans 9 months
(2018-06 → 2019-03) during which the cash/equity trajectory differs
materially between old and new runs, so the entry quantity of **every
subsequent trade** is re-sized from a different cash base. All 132 shared
trades show shifted quantities and realised PnL (e.g. trade 2019-03-28 →
2019-04-10: old PnL 2071.74 → new 1668.96; final trade 2026-06-02 →
2026-06-03: old −3403.84 → new −2957.05). There is **no unexplained
residual**: the only mechanisms are (a) the 2 shorts → 2 longs swap and
(b) fraction-of-cash re-compounding downstream of it.

Why final equity DROPS despite removing two losing shorts (−5724.64 PnL
combined): the replacement first LONG enters at 6338.62 in September 2018
and rides the bear market down to its 3871.61 exit (−3697.43 — worse than
the −2176.39 short it replaces), and the smaller 2019 cash base then
compounds through all subsequent fraction-of-cash entries.

## Old vs new — headline numbers

| Metric | Old golden (M5a re-freeze) | New reference | Delta |
|---|---|---|---|
| Trade count | 134 | 134 | 0 (−2 SHORT, +2 LONG) |
| SHORT trades | 2 | 0 | −2 |
| Final equity | 53103.01549885479 | 46132.76684866844 | −6970.24865018635 (−13.13 %) |
| Final cash | 53103.01549885479 | 46132.76684866844 | −6970.24865018635 |
| Total realised PnL | 43103.01549885479 | 36132.76684866844 | −6970.24865018635 |
| Starting cash | 10000.0 | 10000.0 | — |
| Equity points | 3076 | 3076 | 0 |

The long-only equity curve is free of the un-liquidated short liability
drag (DEF-01-C): no trade row carries `side == SHORT`, and the final equity
reconciles exactly with `starting_cash + total_realised_pnl` under zero
fees.

## Spot-checked trades

| Trade | Old | New | Mechanism |
|---|---|---|---|
| First golden trade | SHORT 2018-06-10 → 2019-03-12, avg_sold 5819.86, −2176.39 | LONG 2018-09-13 → 2019-03-12, bought 6338.62 / sold 3871.61, −3697.43 | Opening SELL rejected at admission; the old covering BUY (6338.62, identical fill price) now opens the long |
| Second short's window | SHORT 2023-10-29 → 2023-11-14, avg_sold 35147.53, −3548.26 | LONG 2023-11-10 → 2023-11-14, bought 36701.10 / sold 36462.93, −224.72 | Same swap; the old covering BUY (36701.10) opens the long |
| 2019-03-28 → 2019-04-10 LONG (shared) | PnL 2071.74 | PnL 1668.96 | Identity unchanged; quantity re-compounded from the post-2018 cash base |

## NEW FROZEN ARTIFACTS riding this named re-freeze

**1. `summary.json` derived-metrics block (D-15)** — produced by
`itrader.reporting.metrics` since plan 07-03, frozen now:

```json
"metrics": {
  "cagr": 0.19892430587513799,
  "max_drawdown": -0.5387896159531851,
  "profit_factor": 1.2907804558478106,
  "sharpe": 0.6578378566948362,
  "sortino": 1.03779678861673,
  "win_rate": 0.3656716417910448
}
```

Sanity: `max_drawdown` is negative (backtesting.py sign convention, Pitfall
10); `win_rate` 0.36567 == 49 winning / 134 trades (verified independently
from the trades frame); `profit_factor` > 1 consistent with positive total
PnL; `cagr` 19.9 %/yr consistent with 10k → 46.1k over ~8.4 years.

**2. `trades.csv` slippage columns (D-17)** — `slippage_entry` /
`slippage_exit`, post-hoc attribution `fill price − decision-bar close`. In
this zero-slippage run they measure the Phase 6 next-bar-open overnight gap:
72 entries / 83 exits show a nonzero gap; the largest is the documented
trade-122 gap-up entry (+4730.79, 2025-07-10 close → 2025-07-11 open,
REFREEZE-M5A spot check).

The oracle test is extended IN THE SAME COMMIT (Pitfall 6): a dict
comparison of `summary["metrics"]` against the golden's metrics object
(exact, D-16 byte-exact discipline), and the slippage columns auto-lock via
the golden-derived `_trade_numeric` column mechanic.

## WHY

D-08: a LONG_ONLY strategy must be structurally unable to open shorts. The
2 blessed shorts were accidental artifacts of the SELL-falls-through-to-
entry-sizing seam, not strategy intent — SMA_MACD's short block is
commented out. Killing the fall-through at admission (audited, never
silent) makes the reference a clean long-only run, which is what Phase 8
cross-validates against `backtesting.py` and `backtrader` (both of which
would run this strategy long-only).

## Run configuration (D-09)

Generated by the pinned oracle script `scripts/run_backtest.py`
(`poetry run python scripts/run_backtest.py`): dataset
`data/BTCUSD_1d_ohlcv_2018_2026.csv`, window 2018-01-01 → 2026-06-03,
$10,000 starting cash, zero fee / zero slippage (exchange defaults pinned
by the script — `final_cash == final_equity` and PnL reconciles with zero
commission).

## Determinism

Verified at the re-freeze commit gate: two consecutive
`poetry run python scripts/run_backtest.py` runs must produce
byte-identical `trades.csv`, `equity.csv` and `summary.json`.

## Scope note

This is M5b re-freeze 1 of 2 (re-freeze 2 is plan 07-08's admission rules:
allow_increase / max_positions). Phase 8 still owns the FINAL sanctioned
baseline, validated by external cross-validation.
