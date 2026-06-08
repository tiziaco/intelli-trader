# M5b Golden Re-freeze 2 — allow_increase Enforcement (D-10/D-11, D-21/D-23)

**Plan:** 07-08 — RESULT-CHANGING re-freeze 2 of 2.
**Status:** APPROVED — owner typed "approved" at the D-23 blocking checkpoint.
The guards, the re-frozen goldens and this note land as ONE commit (D-21).

## WHAT changed

The OrderManager now enforces the strategy's declared `allow_increase` flag
at admission, completing step 0 of `process_signal` (after the 07-07
direction gate, BEFORE sizing). An unsized BUY for a ticker with an open
long, when the strategy declares `allow_increase=False`, is an **audited
REJECTED order** (`triggered_by="admission_increase"`, reason "position
increase not allowed by strategy", event-derived timestamp) instead of
being fraction-of-cash sized as a position increase. SMA_MACD's
declared-but-ignored `allow_increase=False` is finally honest (D-10).

`allow_increase=True` (oracle-dark — the golden strategy declares False)
sizes the increase by policy on CURRENT remaining available cash and flows
through the existing Phase 5 check-and-reserve gate — the literal M5-06
check_cash-covers-increases requirement; insufficient funds still produces
the audited `cash_reservation` rejection (unit-locked, T-07-21).

A sibling `max_positions` gate joins in the same step 0 (discretion
exercised: sibling strategy field, NEW-position entries only): an unsized
BUY opening a NEW ticker when `open_position_count >= max_positions` is an
audited REJECTED order (`triggered_by="admission_max_positions"`). A BUY
for the already-open ticker is the increase case, never this one (no
double-gating). **Oracle-dark as predicted: the gate tripped ZERO times in
the golden run** (single-ticker, max_positions=1, at most one open
position).

## N — the count of rejected increases (RESEARCH A1 resolved)

**N = 3.** The golden run contains exactly 3 unsized BUY-while-long signals,
all now REJECTED at admission (audited entities verified in order storage):

| # | Rejected signal (decision bar) | Would-have-filled | Cash it deployed (old run) | Inside trade |
|---|---|---|---|---|
| 1 | 2022-04-15 | 2022-04-16 open | 2063.39 (95 % of 2171.99 remaining) | 2021-12-19 → 2022-04-23 LONG |
| 2 | 2024-10-28 | 2024-10-29 open | 2341.39 (95 % of 2464.62 remaining) | 2024-07-10 → 2024-11-02 LONG |
| 3 | 2025-05-20 | 2025-05-21 open | 3027.70 (95 % of 3187.05 remaining) | 2025-03-03 → 2025-05-24 LONG |

The 3 direction-gate rejections from re-freeze 1 are unchanged (2018-06-09,
2018-09-05, 2023-10-28) — total audited admission rejections in the run: 6.

Consequences visible in the reference output:

- **Trade count unchanged at 134; every trade keeps its identity** (entry
  date, exit date, side, pair all byte-identical — the behavioral oracle
  passes WITHOUT regeneration). Increases never opened or closed trades;
  they only resized open positions, so rejecting them moves numbers, not
  rows. **0 SHORT rows, exactly as re-freeze 1 left it.**
- **The 3 increase-containing trades lose their second fill**: their entry
  composition collapses to the single first fill, so `avg_price`/
  `avg_bought` revert to the pure entry price and their D-17
  `slippage_entry` collapses from the multi-fill-average artifact to the
  plain next-open gap (−343.00 → −0.01; +474.51 → 0.00; +531.49 → −0.01).
- **All downstream numbers re-compound** from the first rejection's fill
  date: the equity curve keeps its full 3076-point grid and is
  byte-identical up to 2022-04-15, then 1510 of 3076 rows shift.

## COMPOUNDING — the knock-on, fully attributed

Fraction-of-cash sizing compounds: from trade 70 (entry 2021-12-19) onward,
every subsequent entry is re-sized from a slightly different cash base.
Three mechanisms, no unexplained residual:

1. **The 3 removed increases themselves** (table above) — each had deployed
   95 % of the then-remaining cash into an already-open position.
2. **Fraction-of-cash re-compounding** of all 64 downstream trades'
   quantities/PnL (trades 1–69, before the first rejection, are
   byte-identical).
3. **±1-ULP Decimal representation artifacts** on 9 single-fill trades
   between 2024-11-22 and 2026-05-11 (e.g. `98317.12000…001` →
   `98317.11999…999`): `avg_price` is a 28-digit Decimal division whose
   last digit depends on the re-compounded quantity operand. Relative
   magnitude ≤ 1e-23 — pure repr knock-on of mechanism 2.

Net effect is small and slightly positive (+57.11 final equity, +0.124 %):
increase #1 averaged DOWN into a losing trade (old avg 46491.48 vs new
single-fill 46834.47, PnL −6321.23 → −6278.35), increase #2 averaged UP
late in a winning trade (58524.51 → 58050.00, PnL +9217.64 → +9243.91),
increase #3 nearly neutral (94801.49 → 94269.99, PnL +8394.77 → +8393.42).

## Old vs new — headline numbers

| Metric | Old golden (re-freeze 1) | New reference | Delta |
|---|---|---|---|
| Trade count | 134 | 134 | 0 (identical keys) |
| SHORT trades | 0 | 0 | 0 |
| Rejected increases (audited) | n/a (admitted) | 3 | N = 3 |
| max_positions rejections | n/a | 0 | gate oracle-dark, as designed |
| Final equity | 46132.76684866844 | 46189.87730727451 | +57.11045860607 (+0.124 %) |
| Final cash | 46132.76684866844 | 46189.87730727451 | +57.11045860607 |
| Total realised PnL | 36132.76684866844 | 36189.87730727451 | +57.11045860607 |
| Starting cash | 10000.0 | 10000.0 | — |
| Equity points | 3076 | 3076 | 0 (1510 values shift from 2022-04-16) |

## Frozen D-15 metrics block — old → new

```json
"metrics": {
  "cagr":          0.19892430587513799 -> 0.19910032815485068,
  "max_drawdown": -0.5387896159531851  -> -0.5382568231814071,
  "profit_factor": 1.2907804558478106  -> 1.291149869385797,
  "sharpe":        0.6578378566948362  -> 0.6583614133806533,
  "sortino":       1.03779678861673    -> 1.0385040387966196,
  "win_rate":      0.3656716417910448  -> 0.3656716417910448 (unchanged)
}
```

`win_rate` is exactly unchanged — 49 winners / 134 trades on identical
trade keys; the rejections changed magnitudes, not win/loss signs. All
ratio shifts are consistent in direction with the +0.124 % equity gain and
the slightly shallower drawdown.

## WHY

D-10/M5-06: every constraint a strategy DECLARES must be enforced where
portfolio state lives — the admission gate, per portfolio. SMA_MACD has
declared `allow_increase=False` since M1, but the engine ignored it: a BUY
signal firing while a position was open silently pyramided 95 % of
remaining cash into the position. Strategies stay portfolio-blind and keep
emitting duplicate signals; filtering them is the admission gate's job.
With this re-freeze, the reference run is exactly what the strategy
declares: long-only (re-freeze 1), no pyramiding (re-freeze 2) — what
Phase 8 cross-validates against `backtesting.py` and `backtrader` (whose
default brokers likewise do not pyramid without explicit opt-in).

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

This is M5b re-freeze 2 of 2 — the final numeric change of Phase 7. The
phase history now carries exactly two named, owner-approved numeric
changes (REFREEZE-M5B-DIRECTION.md, this note). Phase 8 owns the FINAL
sanctioned baseline, validated by external cross-validation; this is the
M5b working reference it starts from.
