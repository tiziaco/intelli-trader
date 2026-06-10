"""MATCH-03: SELL STOP pessimistic GAP-DOWN fill — scenario + VERIFY note.

Exercises the SELL STOP gap-down fill formula:

    SELL STOP, ``low <= trigger`` -> fill at ``MIN(open, trigger)`` (the pessimistic
    gap-down arm of ``MatchingEngine._evaluate``; a sell-stop sells DOWN through
    the trigger on a gap).

AUTHORING PATH (per the PLAN NOTE + Open Q1, v1.1 LONG-ONLY guard):
v1.1 gates shorting to the margin/liquidation milestone — the LONG_ONLY guard in
``StrategiesHandler.add_strategy`` (D-08/D-09) REJECTS any non-LONG_ONLY direction,
so a STANDALONE short SELL-STOP *entry* cannot be admitted. The PLAN's explicit
fallback is therefore used: the SELL STOP is the **stop-LOSS EXIT leg of an open
long**. A MARKET BUY entry opens a long with an attached stop-loss (``sl``); the
bracket assembler in ``OrderManager._assemble_bracket_and_emit`` (D-11) builds that
``sl`` as a SELL STOP child via ``Order.new_stop_order`` (action inverted to SELL). The following bars gap the price
DOWN through the stop so the SELL STOP fills PESSIMISTICALLY at its (lower) open —
the MATCH-03 ``MIN(open, trigger)`` formula, exercised within LONG-ONLY. The SL
child carries the entry quantity, so it nets the long to exactly zero and a LONG
round-trip lands.

This is the gap-down half of the MATCH-03 STOP pair (the gap-up half is the
sibling ``stop_gap_up`` leaf). Pure-fill (D-09): the golden set is ``trades.csv``
+ ``summary.json`` only — NO ``orders.csv``. Zero-fee / zero-slippage
(``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-03 / D-02): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below (single LONG BTCUSD trade:
buy @124 MARKET entry on 2020-01-03, SELL-STOP stop-out @104 pessimistic GAP-DOWN
on 2020-01-04, realised_pnl -1_583.3333..., final_equity 8_416.6666...,
trade_count 1).

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close   role
    0    2020-01-01   100    105    99     104     warmup
    1    2020-01-02   118    122    116    120     BUY decision (MARKET entry; sl=110 attached)
    2    2020-01-03   124    128    118    126     entry FILL bar (MARKET -> open 124; SL low 118 > 110 safe)
    3    2020-01-04   104    106    100    103     SL FILL bar (low 100 <= 110, open 104 < 110 -> gap-down stop-out)
    4    2020-01-05   102    107    101    105     post-stop (position already closed)
    5    2020-01-06   106    109    105    108     trailing (Pitfall 6)

A RESTING child (unlike a freshly-decided signal) fills on the bar it triggers —
there is NO extra next-bar delay — so the SL stop-out fill is stamped exit_date
2020-01-04 (bar3), the bar whose low gaps through the stop.

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter(order_type=OrderType.MARKET,
direction=LONG_ONLY)`` (both defaults) with a DATE-keyed script (D-04): a single
BUY with an attached ``sl=110`` on 2020-01-02. No scripted SELL — the SELL STOP
stop-loss child closes the long.

Decision bar -> fill bar:

    decision bar1 (2020-01-02, close 120): MARKET BUY rests; an sl=110 SELL STOP
        child is attached (parent_order_id = entry id), DORMANT while the parent rests.
        bar2 (2020-01-03): MARKET entry fills at the OPEN 124, stamped 2020-01-03.
            The parent leaves the book -> the SL child goes live, evaluated against
            bar2: low 118 > 110, so the SL does NOT trigger on the entry bar.
        bar3 (2020-01-04): SL SELL STOP, low 100 <= 110 AND open 104 < 110
            -> pessimistic gap-down arm: fill at MIN(104, 110) = 104,
               stamped exit_date 2020-01-04 (a resting child fills on its trigger
               bar — no next-bar delay).

Entry (MARKET BUY decided on bar1 / 2020-01-02):
  * Sizing uses the DECISION-bar close (bar1 close = 120) and full available cash:
    qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.16666... (475/6) units.
  * The MARKET order fills at bar2 open = 124, stamped 2020-01-03.
  * total_bought = (475/6) * 124 = 9_816.666...; avg_bought = 124.

Exit (SELL STOP stop-loss child, sl trigger = 110):
  * The SELL STOP fills at MIN(open 104, trigger 110) = 104, stamped 2020-01-04.
  * The child carries the entry quantity (475/6), so the long nets to 0.
  * total_sold = (475/6) * 104 = 8_233.333...; avg_sold = 104.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 124
  * exit_date  = 2020-01-04, avg_sold  = 104  (the gap-down SELL STOP fill)
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = total_sold - total_bought = 8_233.333... - 9_816.666... = -1_583.3333...
                 = (104 - 124) * 475/6 = -20 * 475/6.

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 - 1_583.3333... = 8_416.6666...
  * final_equity = 8_416.6666..., trade_count = 1.

Slippage columns (D-17 — fill price - decision-bar close, the bar before the fill):
  * slippage_entry = bar2 fill (124) - bar1 close (120) = 4.0
  * slippage_exit  = bar3 SL fill (104) - bar2 close (126) = -22.0 (gapped DOWN through the stop)

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a single MARKET BUY with an attached sl=110 SELL STOP
# stop-loss. No scripted SELL — the SELL STOP child closes the long when price
# gaps down through the stop (the MATCH-03 gap-down fill under test).
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": Decimal("110"), "tp": None},
}

# order_type defaults to MARKET, direction defaults to LONG_ONLY (the v1.1 guard
# permits ONLY LONG_ONLY — the LONG_ONLY check in StrategiesHandler.add_strategy,
# D-08/D-09). The SELL STOP stop-loss is exercised as the long's EXIT leg, not as a
# standalone short entry.
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="stop_gap_down_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
