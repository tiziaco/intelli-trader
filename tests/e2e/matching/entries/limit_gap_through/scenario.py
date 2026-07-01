"""MATCH-02: BUY LIMIT favorable GAP-THROUGH entry fill — scenario + VERIFY note.

A BUY LIMIT entry rests at the DECISION-bar close (D-02 entry-price provenance:
``SignalEvent.price = to_money(decision_bar.close)``). The IMMEDIATELY-FOLLOWING
bar OPENS at-or-below the trigger, so the limit fills at the (better) OPEN:

    BUY LIMIT, ``open <= trigger`` -> fill at the OPEN (the favorable gap-through
    arm of ``MatchingEngine._evaluate``; a limit fill can never be WORSE than the
    limit, and a gap below the limit is strictly better, so it fills at the open).

This is the gap-through half of the MATCH-02 LIMIT pair (the in-bar-touch half
lives in the sibling ``limit_touch`` leaf). Pure-fill (D-09): the assertion is
the closed round-trip, so the golden set is ``trades.csv`` + ``summary.json``
only — NO ``orders.csv``. Zero-fee / zero-slippage (``exchange=None``, D-14).

The ``ScriptedEmitter`` applies ``order_type=OrderType.LIMIT`` to BOTH scripted
signals (Pitfall 3). So the closing SELL is also a SELL LIMIT (take-profit on the
long) whose fill bar opens at-or-above its trigger -> gap-through -> fills at that
(better) open, landing a clean round-trip.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-02 / D-02): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below (single LONG BTCUSD trade:
buy @116 favorable GAP-THROUGH on 2020-01-03, sell @150 gap-through on
2020-01-05, realised_pnl 2_691.6666..., final_equity 12_691.6666..., trade_count 1).

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close   role
    0    2020-01-01   100    105    99     104     warmup
    1    2020-01-02   118    122    116    120     BUY decision  (close 120 = entry trigger T)
    2    2020-01-03   116    128    114    126     entry FILL bar (open 116 <= T -> gap-through)
    3    2020-01-04   135    142    134    140     SELL decision (close 140 = exit trigger Te)
    4    2020-01-05   150    155    149    154     exit FILL bar  (open 150 >= Te)
    5    2020-01-06   158    162    157    160     trailing (Pitfall 6)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter(order_type=OrderType.LIMIT)`` with a
DATE-keyed script (D-04): a BUY on 2020-01-02, a full SELL on 2020-01-04.

Decision bar -> fill bar:

    decision bar1 (2020-01-02, close 120 = T): BUY LIMIT rests at T=120.
        bar2 (2020-01-03): open 116 <= 120
        -> favorable gap-through arm: fill at the OPEN 116 (better than the limit),
           stamped entry_date 2020-01-03.
    decision bar3 (2020-01-04, close 140 = Te): SELL LIMIT (long TP) rests at Te=140.
        bar4 (2020-01-05): open 150 >= 140
        -> gap-through arm: fill at the OPEN 150, stamped exit_date 2020-01-05.

Entry (BUY LIMIT decided on bar1 / 2020-01-02):
  * Sizing uses the DECISION-bar close (bar1 close = 120) and full available cash:
    qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.16666... (475/6) units.
    (Sizing anchors on the DECISION price, NOT the gapped fill — Pitfall 6: the
    quantity is fixed at decision time; the favorable fill just buys at 116.)
  * The LIMIT fills at the gapped OPEN 116, stamped 2020-01-03.
  * total_bought = (475/6) * 116 = 9_183.333...; avg_bought = 116.

Exit (full SELL LIMIT decided on bar3 / 2020-01-04, exit_fraction defaults to 1):
  * The SELL LIMIT fills at bar4 open = 150 (favorable gap-through), 2020-01-05.
  * total_sold = (475/6) * 150 = 11_875.00; avg_sold = 150.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 116
  * exit_date  = 2020-01-05, avg_sold  = 150
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_875 - 9_183.333... = 2_691.6666...
                 = (150 - 116) * 475/6 = 34 * 475/6.

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 + 2_691.6666... = 12_691.6666...
  * final_equity = 12_691.6666..., trade_count = 1.

Slippage columns (D-17 — fill price - decision-bar close, the bar before the fill):
  * slippage_entry = bar2 fill (116) - bar1 close (120) = -4.0  (filled BELOW decision)
  * slippage_exit  = bar4 fill (150) - bar3 close (140) = 10.0

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): BUY decided 2020-01-02, full SELL decided 2020-01-04.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-04": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

# Pitfall 3: order_type=LIMIT is the per-INSTANCE config field that selects a
# LIMIT entry (and, here, a LIMIT exit) — NOT scripted per bar.
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(name="limit_gap_through_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
