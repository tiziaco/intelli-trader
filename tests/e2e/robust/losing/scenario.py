"""ROBUST-03c losing: a net-NEGATIVE round-trip -> all-finite metrics (D-05).

The net-loss degenerate case for the derived metrics. A single LONG round-trip
entered ABOVE its exit (buy high, sell low) so realised PnL < 0. With no winning
trade, ``profit_factor`` takes the all-LOSS branch -> 0.0 (metrics.py:96-97,
``gross_loss > 0`` and ``gross_profit == 0`` -> 0.0), which is FINITE -- the all-WIN
``inf`` branch is structurally unreachable here. Every other metric is a finite real
number over a curve that ends below its start.

Analog: ``tests/e2e/smoke/single_market_buy`` (round-trip with engineered PnL), here
inverted to a LOSS. ``FixedQuantity(1)`` keeps the PnL exactly hand-derivable.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-05): a human confirmed the frozen ``golden/trades.csv``
carries ONE LONG BTCUSD round-trip with realised_pnl -10 (net negative) and the
``golden/summary.json`` ``metrics`` block is all-finite -- ``profit_factor = 0.0``
(all-loss branch, NOT inf). Re-freeze ONLY via ``--freeze`` after re-verifying this
derivation.

Contrived bars (``bars.csv`` -- daily, tz-aware Open time; wide 95..115 band so the
MARKET next-bar-open fills clear cleanly):

    bar  date         open   high   low    close
    0    2020-01-01   110    115    95     110    <- BUY decided (close 110)
    1    2020-01-02   110    115    95     110    <- SELL decided; BUY fills @110
    2    2020-01-03   100    115    95     100    <- SELL fills @100  (-10 LOSS)
    3    2020-01-04   100    115    95     100

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), ONE portfolio, ONE ``ScriptedEmitter`` over BTCUSD,
``sizing_policy = FixedQuantity(1)``, default ``max_positions = 1`` / full exit.
MARKET entries (next-bar-open fills).

The single LOSING round-trip, 1 unit:
  * BUY decided 2020-01-01 (close 110) -> fills the NEXT bar open = bar1 open
    (2020-01-02) = 110. entry_date 2020-01-02, total_bought = 1 * 110 = 110.
  * SELL decided 2020-01-02 -> fills bar2 open (2020-01-03) = 100. exit_date
    2020-01-03, total_sold = 1 * 100 = 100.
  * realised_pnl = 100 - 110 = -10.00  (a LOSS).

trade_count = 1. final_cash = final_equity = 10_000 - 10 = 9_990.00 (no open
position at run end).

Derived metrics (the ROBUST-03c contract -- profit_factor FINITE 0.0, not inf):
  * ``profit_factor`` = 0.0  -- the only trade lost, so gross_profit = 0 and
    gross_loss = 10 -> the all-loss branch returns 0.0 (metrics.py:96-97). FINITE;
    the all-WIN ``inf`` branch is unreachable.
  * ``win_rate``     = 0 wins / 1 trade = 0.0  -- finite.
  * ``max_drawdown`` < 0  -- the equity dips below its start and ends below it; a
    finite NEGATIVE drawdown (the D-16 negative sign convention).
  * ``sharpe`` / ``sortino`` / ``cagr`` are machine-computed over the equity curve;
    all finite real numbers. The LOAD-BEARING hand-checked facts are the fills and
    the -10 PnL; the curve-derived ratios freeze as machine-written and are guarded
    finite by ``test_metrics_finite.py``.

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

# A single net-NEGATIVE round-trip: buy @110, sell @100 -> PnL -10. With no winning
# trade, profit_factor takes the all-LOSS branch -> 0.0 (finite); the all-win inf
# branch is structurally unreachable.
_SCRIPT = {
    "2020-01-01": {"side": "BUY"},   # entry -> fills @110
    "2020-01-02": {"side": "SELL"},  # exit  -> fills @100 (-10)
}

# FixedQuantity(1): one unit so PnL = 1 * (100 - 110) = -10, integer-exact.
_SIZING = FixedQuantity(qty=Decimal("1"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-04",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(name="losing_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage -- degenerate metrics only.
)
