"""SIZE-01: FixedQuantity sizing — scenario spec + VERIFY hand-derivation.

The first hand-verified fill for the ``FixedQuantity`` sizing policy (D-02). A BUY
declaring ``sizing_policy=FixedQuantity(qty=Decimal("10"))`` fills EXACTLY 10 units —
independent of available cash and of any cash fraction. The resolver's FixedQuantity
arm is a pass-through (``sizing_resolver.py:113-114`` — ``qty = policy.qty``), so the
frozen trade row carries the declared quantity verbatim.

A single MARKET BUY -> MARKET SELL round-trip on contrived BTCUSD bars with
``exchange=None`` (zero fee / zero slippage) — sizing is the ONLY moving part, so
every number traces straight to the declared qty + the bar prices.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-10): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100
    2    2020-01-03   100    155    99     150
    3    2020-01-04   180    205    175    200
    4    2020-01-05   200    210    199    205
    5    2020-01-06   205    210    204    208

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04):
a MARKET BUY on the 2020-01-02 decision bar and a MARKET SELL on the 2020-01-04
decision bar. ``sizing_policy = FixedQuantity(qty=Decimal("10"))``.

Sizing (FixedQuantity arm — sizing_resolver.py:113-114, ``qty = policy.qty``):
    qty = 10 units, FLAT (independent of cash / decision price). 10 units @ the
    bar2 fill price (100) is a 1_000 notional — well within the 10_000 cash, so the
    BUY is admitted (no over-cash rejection — that is SIZE-03).

Lifecycle (decision bar -> fill bar; the next-bar-open rule):

    decision bar1 (2020-01-02): script hits BUY -> MARKET parent rests.
    bar2 (2020-01-03): the MARKET parent fills at bar2 OPEN = 100, stamped
        2020-01-03. Position opens LONG 10 @ 100.
    decision bar3 (2020-01-04): script hits SELL -> MARKET exit parent rests
        (position is open, so this is a flatten; exit_fraction defaults to 1 ->
        the resolver returns net_quantity = 10 UNCHANGED, D-07 no-op).
    bar4 (2020-01-05): the MARKET exit fills at bar4 OPEN = 200, stamped
        2020-01-05. Position closes.
    bar5 (2020-01-06): trailing bar — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @100):
  * total_bought = 10 * 100 = 1_000.00; avg_bought = 100.
Exit (MARKET SELL, filled bar4 @200):
  * total_sold = 10 * 200 = 2_000.00; avg_sold = 200.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 100
  * exit_date  = 2020-01-05, avg_sold  = 200
  * net_quantity = 0 (fully closed)
  * realised_pnl = (avg_sold - avg_bought) * qty = (200 - 100) * 10 = 1_000.00
  * commission = 0.00 (exchange = None).

Final cash (ledger): start - buy_notional + sell_notional
    = 10_000 - 1_000 + 2_000 = 11_000.00
    cross-check: starting_cash + realised_pnl = 10_000 + 1_000 = 11_000.00. OK.

Slippage columns (slippage model = NONE, so fill = open; slippage = fill price -
the STORE bar immediately before the fill bar — attach_slippage indexes the store
close series, NOT the run/decision grid):
  * slippage_entry = bar2 open (100) - bar1 close (100) = 0.0
  * slippage_exit  = bar4 open (200) - bar3 close (200) = 0.0

Final portfolio: final_cash = final_equity = 11_000.00, trade_count = 1.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a MARKET BUY decided 2020-01-02 (fills bar2 @100) and a
# MARKET SELL decided 2020-01-04 (fills bar4 @200) — a clean round-trip.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# SIZE-01 (D-02): FixedQuantity sizes a FLAT 10 units (Pitfall 1 string-path Decimal),
# independent of cash. The resolver FixedQuantity arm is a pass-through.
_SIZING = FixedQuantity(qty=Decimal("10"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(name="size01_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage — sizing is the only moving part.
)
