"""MATCH-03: BUY STOP pessimistic GAP-UP entry fill — scenario + VERIFY note.

A BUY STOP entry rests at the DECISION-bar close (D-02 entry-price provenance:
``SignalEvent.price = to_money(decision_bar.close)``). The IMMEDIATELY-FOLLOWING
bar's high reaches the trigger AND it gaps so the OPEN is already ABOVE the
trigger — the stop fills PESSIMISTICALLY at the worse of (open, trigger):

    BUY STOP, ``high >= trigger`` -> fill at ``MAX(open, trigger)`` (the pessimistic
    gap-up arm of ``MatchingEngine._evaluate``; a stop pays UP through the trigger
    on a gap — asymmetric with the limit's better-fill semantics by design).

This is the gap-up half of the MATCH-03 STOP pair (the gap-down half is the
sibling ``stop_gap_down`` leaf). Standalone STOP entry (Open Q1 resolution: no
bracket parent). Pure-fill (D-09): the golden set is ``trades.csv`` +
``summary.json`` only — NO ``orders.csv``. Zero-fee / zero-slippage
(``exchange=None``, D-14).

The ``ScriptedEmitter`` applies ``order_type=OrderType.STOP`` to BOTH scripted
signals (Pitfall 3). So the closing SELL is a SELL STOP (the stop-LOSS leg of the
long): ``low <= trigger -> MIN(open, trigger)``. The exit fill bar gaps DOWN below
its trigger so the SELL STOP fills at its (lower) open — a clean, round exit that
lands the round-trip while exercising the SELL-STOP pessimistic-gap-down formula
on the EXIT.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-03 / D-02): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below (single LONG BTCUSD trade:
buy @126 pessimistic GAP-UP on 2020-01-03, sell @146 stop-out on 2020-01-05,
realised_pnl 1_583.3333..., final_equity 11_583.3333..., trade_count 1).

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close   role
    0    2020-01-01   100    105    99     104     warmup
    1    2020-01-02   112    121    111    120     BUY decision  (close 120 = entry trigger T)
    2    2020-01-03   126    130    125    128     entry FILL bar (high 130 >= T, open 126 > T -> gap-up)
    3    2020-01-04   148    152    147    150     SELL decision (close 150 = exit stop trigger Te)
    4    2020-01-05   146    148    144    145     exit FILL bar  (low 144 <= Te, open 146 < Te -> gap-down stop-out)
    5    2020-01-06   143    147    142    144     trailing (Pitfall 6)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter(order_type=OrderType.STOP)`` with a
DATE-keyed script (D-04): a BUY on 2020-01-02, a full SELL on 2020-01-04.

Decision bar -> fill bar:

    decision bar1 (2020-01-02, close 120 = T): BUY STOP rests at T=120.
        bar2 (2020-01-03): high 130 >= 120 AND open 126 > 120
        -> pessimistic gap-up arm: fill at MAX(126, 120) = 126,
           stamped entry_date 2020-01-03.
    decision bar3 (2020-01-04, close 150 = Te): SELL STOP (stop-loss) rests at Te=150.
        bar4 (2020-01-05): low 144 <= 150 AND open 146 < 150
        -> pessimistic gap-down arm: fill at MIN(146, 150) = 146,
           stamped exit_date 2020-01-05.

Entry (BUY STOP decided on bar1 / 2020-01-02):
  * Sizing uses the DECISION-bar close (bar1 close = 120) and full available cash:
    qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.16666... (475/6) units.
    (Sizing anchors on the DECISION price 120, NOT the worse gapped fill 126.)
  * The STOP fills at MAX(open 126, trigger 120) = 126, stamped 2020-01-03.
  * total_bought = (475/6) * 126 = 9_975.00; avg_bought = 126.

Exit (full SELL STOP decided on bar3 / 2020-01-04, exit_fraction defaults to 1):
  * The SELL STOP fills at MIN(open 146, trigger 150) = 146, 2020-01-05.
  * total_sold = (475/6) * 146 = 11_558.333...; avg_sold = 146.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 126
  * exit_date  = 2020-01-05, avg_sold  = 146
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_558.333... - 9_975 = 1_583.3333...
                 = (146 - 126) * 475/6 = 20 * 475/6.

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 + 1_583.3333... = 11_583.3333...
  * final_equity = 11_583.3333..., trade_count = 1.

Slippage columns (D-17 — fill price - decision-bar close, the bar before the fill):
  * slippage_entry = bar2 fill (126) - bar1 close (120) = 6.0  (paid UP through the stop)
  * slippage_exit  = bar4 fill (146) - bar3 close (150) = -4.0 (stopped out BELOW decision)

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

# Pitfall 3: order_type=STOP is the per-INSTANCE config field that selects a STOP
# entry (and, here, a STOP exit) — NOT scripted per bar. Standalone STOP entry
# (Open Q1: no bracket parent).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.STOP)],
    portfolios=[PortfolioSpec(name="stop_gap_up_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
