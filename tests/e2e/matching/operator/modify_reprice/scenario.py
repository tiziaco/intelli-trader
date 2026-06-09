"""MATCH-07 operator MODIFY re-price — a resting BUY LIMIT re-priced so it fills.

Operator leaf (D-05/D-06/D-07): ``ScenarioSpec.actions`` -> the harness ``on_tick``
-> the REAL ``OrderHandler.modify_order`` round-trip. A far-from-market BUY LIMIT
rests at a price the following bars never reach; an operator MODIFY re-prices it to
a level the NEXT bar DOES reach, so it then FILLS at the new level (proving the
modify took effect). A closing MARKET SELL completes a clean LONG round-trip. The
leaf freezes the opt-in ``golden/orders.csv`` (the re-priced order FILLED at the NEW
price) plus ``trades.csv`` (the round-trip) and ``summary.json``.

GAP #2 (load-bearing): the harness resolves the target by PREDICATE (ticker + the
sole PENDING order) and calls ``modify_order(order.id, new_price=..., ...)`` with the
resolved UUIDv7 ``order.id`` — NEVER a literal int.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): the frozen goldens MATCH the derivation
below — the BUY LIMIT, originally resting at 120 (unreachable), is re-priced to 125
and FILLS at 125 on bar3; the SELL closes at 150; one LONG round-trip. Re-freeze
ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   123    126    118    120    <- BUY decided here (LIMIT @ 120)
    2    2020-01-03   130    135    127    132    <- MODIFY new_price=125 (on_tick)
    3    2020-01-04   130    135    124    132    <- re-priced LIMIT @ 125 FILLS here
    4    2020-01-05   140    145    139    144    <- SELL decided here (LIMIT @ 144)
    5    2020-01-06   150    155    149    154    <- SELL fills at open 150

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with ``order_type=LIMIT`` (D-03,
Pitfall 3): the entry rests at the DECISION-bar close (D-02).

Entry resting price + sizing (D-02):
  * BUY decided on bar1 (2020-01-02). The LIMIT rests at bar1's close = 120.
  * Sizing uses the decision-bar close (120) and 0.95 of cash:
    qty = 0.95 * 10_000 / 120 = 9_500 / 120 = 79.16666... units.

Why the ORIGINAL limit (120) never fills (proving the modify is load-bearing):
  * A BUY LIMIT fills only when a LATER bar's open <= 120 OR low <= 120
    (matching_engine BUY-LIMIT branch). Every bar after bar1 has open >= 130 and
    low >= 124 (>= 127 except bar3's 124), so @ 120 is unreachable forever.

The operator MODIFY re-price (the new seam):
  * ``actions=[Action(bar_date="2020-01-03", kind="modify", ticker="BTCUSD",
    new_price=Decimal("125"))]``.
  * At bar2's post-bar ``on_tick`` (2020-01-03) the harness resolves the SOLE
    PENDING BTCUSD order and calls the REAL
    ``modify_order(order.id, new_price=125, portfolio_id=...)`` — passing the
    resolved UUIDv7 ``order.id`` (GAP #2), never an int.
  * The MODIFY ``OrderEvent`` is drained at the START of bar3's ``process_events``
    (FIFO, before the bar3 TIME event), so the resting limit's price becomes 125
    BEFORE bar3 matches (Assumption A2 — the amendment lands before the next
    bar's matching).
  * bar3 (2020-01-04): BUY LIMIT @ 125 — open 130 > 125, but low 124 <= 125 -> the
    in-bar touch fills at the limit price = 125 (limit-or-better; the low only
    touches 124). entry_date 2020-01-04, avg_bought = 125.
    Entry cost = 125 * 79.16666... = 9_895.8333... (within the 10_000 cash, funded).

Exit (full SELL decided on bar4 / 2020-01-05 — also a LIMIT, since order_type is a
per-INSTANCE config field, D-03/Pitfall 3): the SELL LIMIT rests at bar4's close =
144. A SELL LIMIT (take-profit) fills when a later bar's open >= 144 (gap-through,
fills at the better open) or high >= 144. bar5 open = 150 >= 144 -> fills at the
open 150, exit_date 2020-01-06.
  * total_sold = 79.16666... * 150 = 11_875.0 -> avg_sold = 150.

Resulting SINGLE round-trip (fees 0, slippage attribution per D-17):
  * side LONG, pair BTCUSD; entry 2020-01-04 @ 125; exit 2020-01-06 @ 150.
  * realised_pnl = 11_875.0 - 9_895.8333... = 1_979.16666... = (150 - 125) * 79.16666...
  * final_equity = 10_000 + 1_979.16666... = 11_979.16666...

Order-mirror assertion (``golden/orders.csv``):
  * ONE row — role STANDALONE, BTCUSD, LIMIT, BUY, status FILLED, price = 125.0
    (the NEW re-priced level, NOT the original 120), filled_quantity = 79.16666...

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType

from tests.e2e.scenario_spec import Action, PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): BUY (LIMIT) decided 2020-01-02, full MARKET SELL decided
# 2020-01-05. The SELL is MARKET (its own per-bar action is MARKET regardless of the
# entry's LIMIT type — the entry type is the per-instance config, the SELL exits at
# the next-bar open).
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-05": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(user_id=1, name="modify_reprice_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
    # The operator MODIFY re-price (D-05/D-06/D-07): resolve the sole PENDING BTCUSD
    # order at bar2 and call the REAL modify_order(order.id, new_price=125, ...)
    # round-trip (UUID, GAP #2).
    actions=(Action(bar_date="2020-01-03", kind="modify", ticker="BTCUSD",
                    new_price=Decimal("125")),),
)
