"""MATCH-07 operator CANCEL — a resting BUY LIMIT cancelled via the real round-trip.

Operator leaf (D-05/D-06/D-07): the ONLY new seam Phase 6 adds is
``ScenarioSpec.actions`` -> the harness ``on_tick`` -> the REAL
``OrderHandler.cancel_order`` round-trip. This leaf scripts a far-from-market BUY
LIMIT that would rest forever (like MATCH-08), then an operator CANCEL removes it
mid-run. The assertion is the final ORDER-MIRROR state (D-08/D-09), so this leaf
freezes the opt-in ``golden/orders.csv`` (status CANCELLED, filled_quantity 0) plus
an empty ``trades.csv`` (zero trades) and ``summary.json``.

GAP #2 (load-bearing): the harness resolves the target by PREDICATE (ticker +
the sole PENDING order, conftest ``_make_on_tick``) and calls
``cancel_order(order.id, portfolio_id)`` with the resolved ``order.id`` — a UUIDv7,
NEVER a literal int (``InMemoryOrderStorage`` is UUID-keyed). The leaf names the
target by ticker only; the harness owns the UUID resolution.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): the frozen ``golden/orders.csv`` shows ONE
row — role STANDALONE, BTCUSD, LIMIT, BUY, status CANCELLED, price 80.0,
filled_quantity 0.0 — and ``golden/trades.csv`` is EMPTY (zero trades). Re-freeze
ONLY via ``--freeze`` after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   90     95     78     80     <- BUY decided here
    2    2020-01-03   120    125    119    124    <- CANCEL scheduled (on_tick)
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with ``order_type=LIMIT`` (D-03,
Pitfall 3): the entry rests at the DECISION-bar close (D-02), not a scripted price.

Where the order rests and why it never fills naturally:
  * BUY decided on bar1 (2020-01-02). The LIMIT rests at bar1's close = 80
    (the decision-bar close, D-02 / strategies_handler stamps SignalEvent.price =
    bar.close).
  * A BUY LIMIT fills only when a LATER bar's open <= 80 (gap-through) OR its
    low <= 80 (in-bar touch) — matching_engine ``_evaluate`` BUY-LIMIT branch.
    Every bar AFTER bar1 has open >= 120 and low >= 119, so the limit @ 80 is
    unreachable: absent the operator it would rest forever (like MATCH-08).

The operator CANCEL (the new seam):
  * ``actions=[Action(bar_date="2020-01-03", kind="cancel", ticker="BTCUSD")]``.
  * At bar2's post-bar ``on_tick`` (2020-01-03) the harness resolves the SOLE
    PENDING BTCUSD order (the resting limit) and calls the REAL
    ``order_handler.cancel_order(order.id, portfolio_id)`` — passing the resolved
    UUIDv7 ``order.id`` (GAP #2), never an int.
  * The CANCEL ``OrderEvent`` enqueued by ``on_tick`` is drained at the START of
    bar3's ``process_events`` (FIFO, before the bar3 TIME event), so the resting
    limit leaves the matching book and the mirror reconciles to CANCELLED.

Final state (the assertion):
  * The order ends status CANCELLED, filled_quantity 0 (it never matched).
  * ZERO trades land (the round-trip never opened) — ``trades.csv`` is EMPTY.

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

# Date-keyed script (D-04): a single BUY decided on the 2020-01-02 bar. With
# order_type=LIMIT the entry rests at that bar's close (80) — far below every
# following bar's range, so it never fills on its own.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(name="cancel_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
    # The operator CANCEL (D-05/D-06/D-07): resolve the sole PENDING BTCUSD order
    # at bar2 and call the REAL cancel_order(order.id, ...) round-trip (UUID, GAP #2).
    actions=(Action(bar_date="2020-01-03", kind="cancel", ticker="BTCUSD"),),
)
