"""MATCH-06: gap clean-through a resting STOP — pessimistic gap fill.

A standalone STOP order rests at trigger ``T``; the next bar GAPS clean past
``T`` so the OPEN (worse than the trigger) is the fill. This is the gap-through
case of the pessimistic STOP formula (``matching_engine._evaluate``):

    BUY  STOP: ``high >= trigger`` -> fill ``max(open, trigger)``  (gap-up)
    SELL STOP: ``low  <= trigger`` -> fill ``min(open, trigger)``  (gap-down)

A *clean* gap makes the OPEN the fill (open is the worse value), proving the
engine does NOT optimistically fill at the trigger when price gapped past it.

This leaf uses a BUY-STOP gap-up ENTRY (open > T) to stay LONG_ONLY (D-02 /
RESEARCH Pitfall 3 — the entry order_type is per-INSTANCE STOP), then closes the
long with a SELL-STOP gap-down EXIT (open < T). Both legs are STANDALONE (no
bracket) so the opt-in ``golden/orders.csv`` snapshot records role STANDALONE,
status FILLED on each (D-08/D-09; GAP #1 — statuses are PENDING/FILLED, never
ACTIVE). Zero-fee / zero-slippage (``exchange=None``, D-14).

Sizing note: ``FractionOfCash(0.5)`` (not the 0.95 golden default) leaves cash
headroom so the gap-UP entry fill (130 > the 120 reservation trigger) clears the
debit-side funds invariant — a 0.95 entry reserved at 120 would fill at 130 and
exceed the 10_000 balance. 0.5 keeps the fill cost well under cash.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-06 / D-13): the frozen ``golden/{trades.csv,
summary.json,orders.csv}`` MATCH the derivation below. Re-freeze ONLY via
``--freeze`` after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     120    <- BUY decision, close = T_entry = 120
    2    2020-01-03   130    135    128    130    <- ENTRY fill bar (gap-UP clean past 120)
    3    2020-01-04   130    135    128    115    <- SELL decision, close = T_exit = 115
    4    2020-01-05   108    112    105    108    <- EXIT fill bar (gap-DOWN clean past 115)
    5    2020-01-06   108    112    105    108    <- trailing bar (Pitfall 6: last bar never fills)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None,
strategy = ``ScriptedEmitter(order_type=STOP, sizing=FractionOfCash(0.5))`` with
a DATE-keyed script: BUY on 2020-01-02, full SELL on 2020-01-04.

Entry (BUY STOP decided on bar1 / 2020-01-02, trigger = decision close = 120):
  * Order rests as a BUY STOP @120 (entry price = decision-bar close, D-02).
  * Fill bar = bar2 (next-bar, Pitfall 6). BUY STOP rule: ``high >= trigger``
    -> 135 >= 120 -> fill = ``max(open, trigger)`` = max(130, 120) = 130.
    The bar GAPPED UP clean past 120 (open 130 > T 120), so the OPEN is the
    pessimistic fill — NOT the 120 trigger.
  * Sizing on the DECISION close (120) with FractionOfCash(0.5):
    qty = (0.5 * 10_000) / 120 = 5_000 / 120 = 125/3 = 41.6666... units.
  * total_bought = (125/3) * 130 = 16_250/3 = 5_416.6666...; avg_bought = 130.

Exit (SELL STOP decided on bar3 / 2020-01-04, trigger = decision close = 115):
  * Order rests as a SELL STOP @115 (closes the long).
  * Fill bar = bar4 (next-bar). SELL STOP rule: ``low <= trigger`` -> 105 <= 115
    -> fill = ``min(open, trigger)`` = min(108, 115) = 108. The bar GAPPED DOWN
    clean past 115 (open 108 < T 115), so the OPEN is the pessimistic fill.
  * total_sold = (125/3) * 108 = 13_500/3 = 4_500.0; avg_sold = 108.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 130
  * exit_date  = 2020-01-05, avg_sold  = 108
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 4_500 - 5_416.6666...
                 = -916.6666... = (108 - 130) * 125/3  (a LOSS — both gaps hurt
                   the long: bought high, sold low; correctness, not profit).

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 - 916.6666... = 9_083.3333...
  * final_equity = final_cash = 9_083.3333...
  * trade_count = 1, total_realised_pnl = -916.6666...

Slippage columns (D-17 — fill price - decision-bar close):
  * slippage_entry = bar2 fill (130) - bar1 close (120) = 10.0
  * slippage_exit  = bar4 fill (108) - bar3 close (115) = -7.0

Order-mirror snapshot (``golden/orders.csv`` — opt-in, D-09): two STANDALONE
orders, both FILLED (the gapped BUY-STOP entry + the gapped SELL-STOP exit). No
ACTIVE (GAP #1), no UUIDs.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType
from itrader.core.sizing import FractionOfCash
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

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    # order_type=STOP makes the entry a resting STOP (Pitfall 3); a smaller
    # 0.5 fraction leaves headroom for the gap-UP entry fill (see module note).
    strategies=[ScriptedEmitter(
        _TIMEFRAME, [_TICKER], script=_SCRIPT,
        order_type=OrderType.STOP,
        sizing_policy=FractionOfCash(Decimal("0.5")))],
    portfolios=[PortfolioSpec(user_id=1, name="gap_stop_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
