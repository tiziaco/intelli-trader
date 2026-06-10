"""MULTI-01: ONE strategy trading TWO tickers -> trades.csv spans both via ``pair``.

The multi-ticker breadth proof. A SINGLE ``ScriptedEmitter`` declares BOTH tickers
(``["BTCUSD", "ETHUSDT"]``) and runs one date-keyed script over each. The emitter's
``generate_signal(ticker, bars)`` is invoked once PER ticker per bar, so the same
script fires the SAME action on BOTH tickers — opening and closing an independent
round-trip on EACH. Both closed round-trips land in the SAME ``trades.csv`` as
``pair`` rows (one ``BTCUSD`` row, one ``ETHUSDT`` row): that single frame spanning
two tickers IS the MULTI-01 assertion — ``build_trade_log`` already spans every
ticker the portfolio traded (no new vehicle, no production change).

This leaf rides the DEFAULT ``trades.csv`` + ``summary.json`` only — NO
``orders.csv`` / ``cash_operations.csv`` / ``portfolios.csv`` opt-in (a clean
multi-ticker round-trip, not a state-edge). ``spec.ticker = "BTCUSD"`` is only the
orders-snapshot query key (unused here) and the ``summary.json`` label ticker; the
``trades.csv`` itself is portfolio-wide and carries BOTH tickers. ``ETHUSDT`` is in
the default supported-symbol set; ``BTCUSD`` is added on the simulated instance.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen
``golden/trades.csv`` (one BTCUSD row + one ETHUSDT row) + ``golden/summary.json``
MATCH the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars — daily, tz-aware Open time. Two CSVs, SAME dates, DISTINCT price
levels per ticker (so the two round-trips have different fill prices and the
``pair`` rows are visibly independent):

    BTCUSD (``bars.csv``)               ETHUSDT (``bars_eth.csv``)
    bar date         open  close        open  close   event
    0   2020-01-01   100   100          200   200     warmup
    1   2020-01-02   100   100          200   200     BUY decided (close 100 / 200)
    2   2020-01-03   120   120          210   210     BUY fills @ open (120 / 210)
    3   2020-01-04   120   120          210   210     SELL decided (close 120 / 210)
    4   2020-01-05   140   140          230   230     SELL fills @ open (140 / 230)
    5   2020-01-06   140   140          230   230     (no signal)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage). ONE ``ScriptedEmitter("1d", ["BTCUSD", "ETHUSDT"], ...)`` over the
ONE portfolio. ``sizing_policy = FixedQuantity(qty=Decimal("10"))`` on the single
instance so BOTH tickers buy exactly 10 units and the cash math is hand-derivable.

Date-keyed script (fires identically on EACH ticker):
  * 2020-01-02: BUY  -> fills at the next-bar open (bar2: BTC 120 / ETH 210).
  * 2020-01-04: SELL -> fills at the next-bar open (bar4 open is bar index 4 =
    2020-01-05: BTC 140 / ETH 230), full exit (exit_fraction default 1).

Admission cash trail (reserve at the DECISION-bar close, bar1: BTC 100 / ETH 200):
  * BTC BUY decided 01-02: reserve 10 * 100 = 1_000.
  * ETH BUY decided 01-02: reserve 10 * 200 = 2_000.
  * combined reservation 3_000 < 10_000 available -> BOTH admitted. (Both fill at
    the next open, releasing each reservation and debiting the principal.)

Per-ticker round-trips (fees 0):
  BTCUSD:
    * entry_date 2020-01-03, avg_bought 120 ; exit_date 2020-01-05, avg_sold 140
    * total_bought = 10 * 120 = 1_200 ; total_sold = 10 * 140 = 1_400
    * realised_pnl = 1_400 − 1_200 = 200  = (140 − 120) * 10
  ETHUSDT:
    * entry_date 2020-01-03, avg_bought 210 ; exit_date 2020-01-05, avg_sold 230
    * total_bought = 10 * 210 = 2_100 ; total_sold = 10 * 230 = 2_300
    * realised_pnl = 2_300 − 2_100 = 200  = (230 − 210) * 10

Slippage attribution (the post-hoc ``attach_slippage`` lens, conftest.py:374):
slippage = fill_price − the DECISION-bar close. The harness reads ONE close series —
``spec.ticker`` = BTCUSD (bar1 close 100, bar3 close 120) — and attributes it to
EVERY trade row regardless of the row's own ticker. So BOTH rows are measured against
the BTCUSD close series (this is the existing single-close-series harness behavior,
not a per-ticker slippage):
  * BTCUSD slippage_entry = 120 − 100 = 20 ; slippage_exit = 140 − 120 = 20.
  * ETHUSDT slippage_entry = 210 − 100 = 110 ; slippage_exit = 230 − 120 = 110
    (ETH fill prices vs. the BTCUSD close series — frozen as 110/110).

Both round-trips appear as ``pair`` rows in the SAME ``trades.csv`` (the MULTI-01
proof). ``build_trade_log`` orders closed positions by close time; both close on the
same bar (2020-01-05), so within-tick the BTCUSD row precedes the ETHUSDT row
(position open order: BTCUSD created first — see the run log).

Final portfolio (BOTH round-trips closed, no open position at run end):
  * realised PnL = 200 (BTC) + 200 (ETH) = 400.
  * final_cash = 10_000 + 400 = 10_400.00 ; final_equity = 10_400.00 (flat — no
    open positions).
  * trade_count = 2, total_realised_pnl = 400.00.

summary.json ``ticker`` = spec.ticker = BTCUSD (the label only — the trades frame
spans both). The machine-computed metrics block is frozen as-written; the
LOAD-BEARING hand-checked facts are the per-ticker fills, quantities, PnL and the
two ``pair`` rows spanning both tickers.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_BTC = "BTCUSD"   # added on the simulated instance; spec.ticker (summary label /
# orders-snapshot key — unused here, this leaf rides the default trades.csv).
_ETH = "ETHUSDT"  # present in the default ExchangeConfig.limits.supported_symbols.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): ONE script driving BOTH tickers. generate_signal is
# called once per ticker per bar, so each date fires the SAME action on each ticker.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},    # opens a round-trip on EACH ticker
    "2020-01-04": {"side": "SELL"},   # closes each round-trip (full exit)
}

# FixedQuantity so each ticker buys exactly 10 units and the cash math is exact.
_SIZING = FixedQuantity(qty=Decimal("10"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``). ONE
# emitter declares BOTH tickers -> one strategy spanning two markets (MULTI-01).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_BTC,
    starting_cash=_CASH,
    data={_BTC: HERE / "bars.csv", _ETH: HERE / "bars_eth.csv"},
    strategies=[
        ScriptedEmitter(_TIMEFRAME, [_BTC, _ETH], script=_SCRIPT,
                        sizing_policy=_SIZING),
    ],
    portfolios=[PortfolioSpec(user_id=1, name="two_tickers_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the two round-trips are the only moving part.
)
