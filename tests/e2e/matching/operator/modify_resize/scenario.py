"""MATCH-07 operator MODIFY re-size — a resting BUY LIMIT re-sized before it fills.

Operator leaf (D-05/D-06/D-07): ``ScenarioSpec.actions`` -> the harness ``on_tick``
-> the REAL ``OrderHandler.modify_order`` round-trip. A BUY LIMIT rests reachable by
a LATER bar; BEFORE it fills, an operator MODIFY re-sizes its quantity, so the order
then fills the NEW quantity. A closing SELL completes a LONG round-trip using the
resized quantity. The leaf freezes the opt-in ``golden/orders.csv`` (the resized
order FILLED, quantity == filled_quantity == new_quantity) plus ``trades.csv`` and
``summary.json``.

GAP #2 (load-bearing): the harness resolves the target by PREDICATE (ticker + the
sole PENDING order) and calls ``modify_order(order.id, new_quantity=..., ...)`` with
the resolved UUIDv7 ``order.id`` — NEVER a literal int.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): the frozen goldens MATCH the derivation
below — the BUY LIMIT, originally sized 79.16666... at 120, is RE-SIZED to 50 BEFORE
it fills, then fills 50 units at 120 on bar3; the SELL closes 50 at 150; one LONG
round-trip with the resized quantity. Re-freeze ONLY via ``--freeze`` after
re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   123    126    118    120    <- BUY decided here (LIMIT @ 120)
    2    2020-01-03   130    135    128    132    <- MODIFY new_quantity=50 (on_tick)
    3    2020-01-04   130    135    118    132    <- resized LIMIT FILLS 50 units here
    4    2020-01-05   140    145    139    144    <- SELL decided here (LIMIT @ 144)
    5    2020-01-06   150    155    149    154    <- SELL fills at open 150

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with ``order_type=LIMIT`` (D-03,
Pitfall 3): the entry rests at the DECISION-bar close (D-02).

Entry resting price + ORIGINAL sizing (D-02):
  * BUY decided on bar1 (2020-01-02). The LIMIT rests at bar1's close = 120.
  * ORIGINAL sizing uses the decision-bar close (120) and 0.95 of cash:
    qty = 0.95 * 10_000 / 120 = 9_500 / 120 = 79.16666... units. This is the
    quantity the order rests with BEFORE the operator re-sizes it.

Why the limit does NOT fill on bar2 (so the resize lands first):
  * bar2 (2020-01-03): BUY LIMIT @ 120 — open 130 > 120 and low 128 > 120, so the
    limit is NOT reached; it stays resting. The operator can re-size it cleanly.

The operator MODIFY re-size (the new seam):
  * ``actions=[Action(bar_date="2020-01-03", kind="modify", ticker="BTCUSD",
    new_quantity=Decimal("50"))]``.
  * At bar2's post-bar ``on_tick`` (2020-01-03) the harness resolves the SOLE
    PENDING BTCUSD order and calls the REAL
    ``modify_order(order.id, new_quantity=50, portfolio_id=...)`` — passing the
    resolved UUIDv7 ``order.id`` (GAP #2), never an int. Re-sizing DOWN (50 <
    79.16666...) keeps the fill fully funded (50 * 120 = 6_000 << 10_000 cash).
  * The MODIFY ``OrderEvent`` is drained at the START of bar3's ``process_events``
    (FIFO, before the bar3 TIME event), so the resting limit's quantity becomes 50
    BEFORE bar3 matches (Assumption A2).

The resized fill (bar3 / 2020-01-04):
  * BUY LIMIT @ 120, quantity now 50 — open 130 > 120, low 118 <= 120 -> the in-bar
    touch fills at the limit price 120 for the RESIZED 50 units. entry_date
    2020-01-04, avg_bought = 120, total_bought = 50 * 120 = 6_000.

Exit (full SELL decided on bar4 / 2020-01-05 — also a LIMIT, per-INSTANCE config):
  * the SELL LIMIT rests at bar4's close = 144; bar5 open 150 >= 144 -> fills at the
    open 150, exit_date 2020-01-06. It sells the entire resized 50-unit position.
  * total_sold = 50 * 150 = 7_500 -> avg_sold = 150.

Resulting SINGLE round-trip (fees 0, slippage attribution per D-17):
  * side LONG, pair BTCUSD; entry 2020-01-04 @ 120 (qty 50); exit 2020-01-06 @ 150.
  * realised_pnl = 7_500 - 6_000 = 1_500.0 = (150 - 120) * 50.
  * final_equity = 10_000 + 1_500.0 = 11_500.0.

Order-mirror assertion (``golden/orders.csv``):
  * the BUY row — role STANDALONE, BTCUSD, LIMIT, BUY, status FILLED, price 120.0,
    quantity == filled_quantity == 50.0 (proving the RE-SIZE took effect: the order
    no longer carries its original 79.16666... quantity).

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

# Date-keyed script (D-04): BUY (LIMIT) decided 2020-01-02, full SELL decided
# 2020-01-05 (exit_fraction 1 closes the whole resized 50-unit position).
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
    portfolios=[PortfolioSpec(user_id=1, name="modify_resize_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
    # The operator MODIFY re-size (D-05/D-06/D-07): resolve the sole PENDING BTCUSD
    # order at bar2 and call the REAL modify_order(order.id, new_quantity=50, ...)
    # round-trip (UUID, GAP #2).
    actions=(Action(bar_date="2020-01-03", kind="modify", ticker="BTCUSD",
                    new_quantity=Decimal("50")),),
)
