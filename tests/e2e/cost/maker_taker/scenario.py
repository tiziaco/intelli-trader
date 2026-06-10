"""COST-02: maker vs taker fee contrast in ONE leaf — scenario + VERIFY note.

Two SEQUENTIAL round-trips on the SAME ticker, one portfolio, with a single
MAKER_TAKER fee model (maker_rate < taker_rate). D-11: the maker leg is a LIMIT
entry that rests-then-fills (``is_maker = order_type is OrderType.LIMIT``,
simulated.py:202) and the taker leg is a MARKET entry that fills next-bar-open. The
frozen ``commission`` column shows the TWO distinct rates side by side — the maker
position pays ``notional * maker_rate`` on each leg, the taker position pays
``notional * taker_rate``.

Because ``order_type`` is a per-INSTANCE config field (Pitfall 3), the two legs use
TWO ``ScriptedEmitter`` instances on the same ticker/portfolio: one
``order_type=LIMIT`` (maker, both its BUY and SELL are LIMIT) firing on the early
date window, one ``order_type=MARKET`` (taker) firing on the later window. The date
windows are NON-OVERLAPPING so the maker round-trip fully closes (position flat)
before the taker round-trip opens — ``allow_increase=False`` would otherwise refuse
a second BUY while a position is open.

Zero slippage (NONE) so the ONLY cost under test is the maker-vs-taker fee. Pure-fill
(D-09): golden = ``trades.csv`` (TWO closed-position rows) + ``summary.json``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (COST-02 / D-11): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close   role
    0    2020-01-01   100    105    99     104     warmup
    1    2020-01-02   118    122    116    120     MAKER BUY decision (close 120 = LIMIT trigger)
    2    2020-01-03   124    128    118    126     maker entry FILL (open 124 > 120, low 118 <= 120: in-bar touch @120)
    3    2020-01-04   135    142    134    140     MAKER SELL decision (close 140 = SELL-LIMIT trigger)
    4    2020-01-05   150    155    149    150     maker exit FILL (open 150 >= 140: gap-through @150)
    5    2020-01-06   100    105    99     100     TAKER BUY decision (MARKET, decision close 100)
    6    2020-01-07   100    105    99     100     taker entry FILL (MARKET @ open 100)
    7    2020-01-08   200    205    199    200     TAKER SELL decision (MARKET)
    8    2020-01-09   200    205    199    205     taker exit FILL (MARKET @ open 200)

Engine knobs: starting_cash = 10_000, timeframe = 1d, sizing = FractionOfCash(0.95),
TWO ``ScriptedEmitter`` instances (maker=LIMIT / taker=MARKET). ``exchange`` carries a
MAKER_TAKER fee model maker_rate=0.001 (0.1%) / taker_rate=0.002 (0.2%) and NO
slippage (NONE).

--- MAKER round-trip (LIMIT, maker_rate = 0.001) ---
Sizing (decision-bar close bar1 = 120, full cash 10_000):
    qty_m = (0.95 * 10_000) / 120 = 9_500 / 120 = 475/6 = 79.16666... units.
Entry: BUY LIMIT rests @120 (bar1 close), fills bar2 in-bar touch @120, stamped
    2020-01-03. total_bought = (475/6) * 120 = 9_500.00; avg_bought = 120.
Exit: SELL LIMIT rests @140 (bar3 close), fills bar4 gap-through @150, stamped
    2020-01-05. total_sold = (475/6) * 150 = 11_875.00; avg_sold = 150.
Commission (maker on BOTH legs):
    buy_commission  = 9_500  * 0.001 = 9.500
    sell_commission = 11_875 * 0.001 = 11.875
    maker commission = 9.500 + 11.875 = 21.375  (frozen ``commission`` for this row)
realised_pnl (LONG) = (150 - 120) * (475/6) - (475/6)/(475/6) * 9.500 - 11.875
    = 2_375 - 9.500 - 11.875 = 2_353.625
Cash after maker leg = 10_000 + 11_875 - 9_500 - 21.375 = 12_353.625.

--- TAKER round-trip (MARKET, taker_rate = 0.002) ---
Sizing (decision-bar close bar5 = 100, available cash now 12_353.625):
    qty_t = (0.95 * 12_353.625) / 100 = 11_735.94375 / 100 = 117.3594375 units.
Entry: MARKET BUY decided bar5, fills bar6 @ open 100, stamped 2020-01-07.
    total_bought = 117.3594375 * 100 = 11_735.94375; avg_bought = 100.
Exit: MARKET SELL decided bar7, fills bar8 @ open 200, stamped 2020-01-09.
    total_sold = 117.3594375 * 200 = 23_471.8875; avg_sold = 200.
Commission (taker on BOTH legs):
    buy_commission  = 11_735.94375 * 0.002 = 23.4718875
    sell_commission = 23_471.8875  * 0.002 = 46.943775
    taker commission = 23.4718875 + 46.943775 = 70.4156625  (frozen ``commission``)
realised_pnl (LONG) = (200 - 100) * 117.3594375 - 23.4718875 - 46.943775
    = 11_735.94375 - 70.4156625 = 11_665.5280875

The TWO frozen ``commission`` values — 21.375 (maker, rate 0.001) vs 70.4156625
(taker, rate 0.002) — are the COST-02 maker-vs-taker contrast (the taker leg also
trades a larger notional, but the per-leg RATE difference is the point and is
verified by the per-leg arithmetic above).

Final cash = starting + sum(realised_pnl) = 10_000 + 2_353.625 + 11_665.5280875
    = 24_019.1530875. trade_count = 2.

Slippage columns (NONE model; attach_slippage indexes the STORE close series — fill
price minus the STORE bar IMMEDIATELY BEFORE the fill bar, NOT the decision bar, D-17):
  maker row:
    slippage_entry = bar2 fill (120) - bar1 close (120) = 0.0
    slippage_exit  = bar4 fill (150) - bar3 close (140) = 10.0
  taker row:
    slippage_entry = bar6 fill (100) - bar5 close (100) = 0.0
    slippage_exit  = bar8 fill (200) - bar7 close (200) = 0.0
      (the store bar before the 2020-01-09 exit fill is bar7 2020-01-08 close 200,
       so the store-indexed attribution is 200 - 200 = 0.0 — NOT bar6's 100.)

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType
from itrader.config.exchange import (
    ExchangeConfig,
    FeeModelConfig,
    FeeModelType,
    SlippageModelConfig,
    SlippageModelType,
)
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Maker leg (LIMIT): a BUY->SELL round-trip on the EARLY window. order_type=LIMIT
# makes BOTH legs maker (is_maker = order_type is LIMIT, simulated.py:202).
_MAKER_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-04": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}
# Taker leg (MARKET): a BUY->SELL round-trip on the LATER window (non-overlapping so
# the maker position is flat first). MARKET => taker on both legs.
_TAKER_SCRIPT = {
    "2020-01-06": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-08": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

# D-11: MAKER_TAKER fee model, maker_rate < taker_rate (Decimal string-path, Pitfall
# 6). NO slippage so the only cost contrast is maker-vs-taker fee.
_EXCHANGE = ExchangeConfig(
    exchange_name="cost02_mt",
    fee_model=FeeModelConfig(
        model_type=FeeModelType.MAKER_TAKER,
        maker_rate=Decimal("0.001"),
        taker_rate=Decimal("0.002"),
    ),
    slippage_model=SlippageModelConfig(model_type=SlippageModelType.NONE),
)

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-09",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[
        ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_MAKER_SCRIPT,
                        order_type=OrderType.LIMIT),
        ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_TAKER_SCRIPT,
                        order_type=OrderType.MARKET),
    ],
    portfolios=[PortfolioSpec(user_id=1, name="cost02_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: MAKER_TAKER fee model applied to the run.
)
