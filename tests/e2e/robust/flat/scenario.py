"""ROBUST-03b flat: two round-trips netting ~zero PnL -> all-finite metrics (D-05).

The ~breakeven degenerate case for the derived metrics. The LOAD-BEARING authoring
constraint (RESEARCH A3): ``profit_factor`` returns ``inf`` for an all-WIN frame
(metrics.py:96-97). To keep profit_factor FINITE we author TWO round-trips -- a
small WIN and a small LOSS of equal magnitude -- so gross_profit > 0 AND
gross_loss > 0 (PF = gross_profit / gross_loss is finite, NOT inf), and the net PnL
is ~zero (flat).

Analog: ``tests/e2e/smoke/single_market_buy`` (round-trip with engineered PnL), here
doubled into a win + an offsetting loss. ``FixedQuantity(1)`` keeps the per-trade
PnL exactly hand-derivable (1 unit * the open-to-open spread).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-05): a human confirmed the frozen ``golden/trades.csv``
carries TWO LONG BTCUSD round-trips (a +10 win then a -10 loss, net 0) and the
``golden/summary.json`` ``metrics`` block is all-finite -- crucially
``profit_factor = 1.0`` (NOT inf). Re-freeze ONLY via ``--freeze`` after
re-verifying this derivation.

Contrived bars (``bars.csv`` -- daily, tz-aware Open time; the WIDE high/low band
95..115 lets the next-bar-open fills clear without tripping any resting bracket --
there are none here, both legs are MARKET):

    bar  date         open   high   low    close
    0    2020-01-01   100    115    95     100    <- BUY-A decided (close 100)
    1    2020-01-02   100    115    95     100    <- SELL-A decided; BUY-A fills @100
    2    2020-01-03   110    115    95     110    <- SELL-A fills @110  (+10 WIN)
    3    2020-01-04   110    115    95     110    <- BUY-B decided (close 110)
    4    2020-01-05   110    115    95     110    <- SELL-B decided; BUY-B fills @110
    5    2020-01-06   100    115    95     100    <- SELL-B fills @100  (-10 LOSS)
    6    2020-01-07   100    115    95     100

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), ONE portfolio, ONE ``ScriptedEmitter`` over BTCUSD,
``sizing_policy = FixedQuantity(1)`` (one unit per entry -> exact integer PnL),
default ``max_positions = 1`` / full exit (each round-trip fully closes before the
next opens). MARKET entries (next-bar-open fills).

Round-trip A (the WIN), 1 unit:
  * BUY decided 2020-01-01 (close 100) -> fills the NEXT bar open = bar1 open
    (2020-01-02) = 100. entry_date 2020-01-02, total_bought = 1 * 100 = 100.
  * SELL decided 2020-01-02 -> fills bar2 open (2020-01-03) = 110. exit_date
    2020-01-03, total_sold = 1 * 110 = 110.
  * realised_pnl = 110 - 100 = +10.00  (a WIN).

Round-trip B (the LOSS), 1 unit:
  * BUY decided 2020-01-04 (close 110) -> fills bar4 open (2020-01-05) = 110.
    entry_date 2020-01-05, total_bought = 1 * 110 = 110.
  * SELL decided 2020-01-05 -> fills bar5 open (2020-01-06) = 100. exit_date
    2020-01-06, total_sold = 1 * 100 = 100.
  * realised_pnl = 100 - 110 = -10.00  (a LOSS).

Net realised PnL = +10 - 10 = 0.00 (flat). trade_count = 2. final_cash =
final_equity = 10_000.00 (the win and the loss exactly cancel; no open position at
run end).

Derived metrics (the ROBUST-03b contract -- profit_factor FINITE, not inf):
  * ``profit_factor`` = gross_profit / gross_loss = 10 / 10 = 1.0  -- FINITE. Both
    a positive and a negative trade exist, so the all-WIN ``inf`` branch
    (metrics.py:96-97) is NOT taken. THIS is the load-bearing fact this leaf proves.
  * ``win_rate``     = 1 win / 2 trades = 0.5  -- finite.
  * ``sharpe`` / ``sortino`` / ``cagr`` / ``max_drawdown`` are machine-computed over
    the equity curve (the curve dips on the open position then returns to ~10_000);
    all are finite real numbers. The LOAD-BEARING hand-checked facts are the two
    fills and the net-zero PnL above; the four curve-derived ratios freeze as
    machine-written and are guarded finite by ``test_metrics_finite.py``.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any non-registered ticker silently REFUSES orders.
_TIMEFRAME = "1d"
_CASH = 10_000

# Two round-trips: a +10 WIN (buy 100 / sell 110) then a -10 LOSS (buy 110 / sell
# 100). Net 0 -> flat. Both legs present -> profit_factor is FINITE (gross_loss > 0),
# NOT the all-win inf branch (the load-bearing A3 constraint).
_SCRIPT = {
    "2020-01-01": {"side": "BUY"},   # round-trip A entry  -> fills @100
    "2020-01-02": {"side": "SELL"},  # round-trip A exit   -> fills @110 (+10)
    "2020-01-04": {"side": "BUY"},   # round-trip B entry  -> fills @110
    "2020-01-05": {"side": "SELL"},  # round-trip B exit   -> fills @100 (-10)
}

# FixedQuantity(1): one unit per entry so each trade's PnL is exactly 1 * the
# open-to-open spread (+10 / -10) -- integer-exact, hand-derivable.
_SIZING = FixedQuantity(qty=Decimal("1"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-07",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(user_id=1, name="flat_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage -- degenerate metrics only.
)
