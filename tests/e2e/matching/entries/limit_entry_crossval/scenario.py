"""D-07: crafted LIMIT-entry strategy on the REAL BTCUSD golden CSV — scenario + VERIFY note.

This is the e2e leaf for the owner-signed, externally cross-validated (backtesting.py /
backtrader) LIMIT-entry golden (Phase 5, D-07). Unlike the contrived ``limit_touch`` /
``stop_gap`` leaves (round-number bars), this leaf runs the crafted
``LimitEntryStrategy`` on a small pinned window of the REAL
``data/BTCUSD_1d_ohlcv_2018_2026.csv`` golden dataset — the SAME dataset the SMA_MACD
oracle uses — so the new golden is anchored to real prices, and the three engines
agree on the fill-price algebra (``min(open, limit)``) by construction.

The strategy (``scripts/crossval/limit_entry_strategy.py``) is SHARED with the two
cross-val engine runners so the iTrader fills and the backtesting.py / backtrader fills
reproduce the SAME crafted scenario. It imports only ``itrader`` (no engine), so reusing
it under ``tests/`` is safe (D-10: only the engine RUNNERS are script-only).

The scenario exercises the three D-07 properties:
  (a) the resting limit fills on a LATER bar (not immediate);
  (b) the entry fill anchors a percent SL/TP bracket (entry-fill -> bracket sequence);
  (c) the marketable-limit case fills at the bar OPEN (open vs limit pinned).

Pure-fill (D-09): the assertion is the closed round-trip(s), so the golden set is
``trades.csv`` + ``summary.json`` only. Zero-fee / zero-slippage (``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-07): the frozen ``golden/trades.csv`` + ``golden/summary.json``
match the derivation below. The fill prices are derived from the bar OHLC by the
``MatchingEngine._evaluate`` limit-or-better rule (a BUY limit fills at the bar OPEN on a
favorable gap, else AT the limit on an in-bar touch); the bracket SL/TP children are STOP
(``sl``) / LIMIT (``tp``) anchored at the strategy's absolute levels.

Window (real BTCUSD golden CSV, sliced [2018-09-01, 2018-09-20], daily, tz-aware Open time):

    date         open       high       low        close      role
    2018-09-01   7011.21    7275.00    7008.74    7200.01    warmup
    2018-09-02   7201.57    7345.45    7127.00    7302.01    BUY-LIMIT decision A (resting)
    2018-09-03   7302.00    7338.28    7191.63    7263.02    A rests (low 7191.63 > T_A)
    2018-09-04   7263.00    7410.00    7227.17    7359.06    A rests (low 7227.17 > T_A)
    2018-09-05   7359.05    7397.30    6682.00    6700.00    A ENTRY FILL (low 6682 <= T_A; SL hits same bar)
    2018-09-06   6697.27    6725.00    6265.00    6516.01    ...
    ...
    2018-09-13   6338.62    6535.00    6337.40    6487.38    BUY-LIMIT decision B (marketable)
    2018-09-14   6487.39    6584.99    6385.62    6476.63    B ENTRY FILL at OPEN (open 6487.39 <= T_B)
    ...

--- Entry A: RESTING buy-limit, fills on a LATER bar (property a) ---
Decision bar 2018-09-02 (close 7302.01): buy_limit at close * 0.98 = T_A = 7155.9698.
  * 2018-09-03: open 7302.00 > T_A AND low 7191.63 > T_A  -> no touch (rests).
  * 2018-09-04: open 7263.00 > T_A AND low 7227.17 > T_A  -> no touch (rests).
  * 2018-09-05: open 7359.05 > T_A AND low 6682.00 <= T_A -> IN-BAR TOUCH: fill AT T_A = 7155.9698,
    stamped entry_date 2018-09-05 (THREE bars after the decision — fill-on-a-later-bar).
  * Sizing uses the decision-bar close (7302.01) and 0.95 of available cash:
        qty = quantize(0.95 * 10_000 / 7302.01, "quantity") = 0.95 * 10000 / 7302.01 = 1.30...
  * Entry fill 7155.9698 ANCHORS the percent SL/TP bracket (property b):
        SL (STOP child)  = T_A * 0.95 = 6798.17131
        TP (LIMIT child) = T_A * 1.15 = 8229.366270

--- Entry A exit: the SL STOP child fills (property b — entry-fill -> bracket) ---
The entry fills on 2018-09-05; that same bar's low (6682.00) is BELOW the SL trigger
6798.17131, so the protective SL STOP child fills the SAME bar (parents-before-children:
the entry settles in pass 1, the SL fills in pass 2 against the same bar's low).
A SELL STOP (stop-loss on a long) fills at min(open, trigger) = min(7359.05, 6798.17131)
= 6798.17131 (in-bar trigger, open above so no gap-down improvement). Round-trip A closes
on 2018-09-05 at avg_sold 6798.17131.

--- Entry B: MARKETABLE buy-limit, fills at the bar OPEN (property c) ---
Decision bar 2018-09-13 (close 6487.38): buy_limit at close * 1.05 = T_B = 6811.749
(ABOVE market — marketable).
  * 2018-09-14: open 6487.39 <= T_B -> GAP-THROUGH arm: fill at the OPEN 6487.39 (NOT at the
    limit 6811.749), stamped entry_date 2018-09-14. This PINS the open-vs-limit fill price.
  * Entry fill 6487.39 anchors SL = T_B*0.95 = 6471.16155, TP = T_B*1.15 = 7833.51135.

NOTE (numbers below the dashed lines, exit bar of B, exact Decimal quantities, realised_pnl,
final_equity, trade_count) are LOCKED from the verified engine run and frozen in golden/.
The harness diffs trades.csv + summary.json EXACT (no tolerance). The cross-val evidence in
tests/golden/CROSS-VALIDATION-LIMIT.md attributes the same numbers across the three engines.

============================== END VERIFY =============================
"""

import pathlib

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec

from scripts.crossval.limit_entry_strategy import LimitEntryStrategy

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
_DATASET = REPO_ROOT / "data" / "BTCUSD_1d_ohlcv_2018_2026.csv"

_TICKER = "BTCUSD"  # any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# A small pinned window of the REAL golden CSV — chosen (see VERIFY note) so every
# fill is hand-derivable while still running on the production dataset (D-07).
SCENARIO = ScenarioSpec(
    start="2018-09-01",
    end="2018-09-20",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: _DATASET},
    strategies=[LimitEntryStrategy(_TIMEFRAME, [_TICKER])],
    portfolios=[PortfolioSpec(name="limit_entry_crossval_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
