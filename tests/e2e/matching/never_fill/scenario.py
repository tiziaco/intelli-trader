"""MATCH-08 never-fill — a far-from-market BUY LIMIT that ends PENDING.

The as-is run-end edge (D-10): a LIMIT far from EVERY authored bar's range never
triggers; the run completes CLEANLY; the order ends ``OrderStatus.PENDING`` —
NOT ``ACTIVE`` (GAP #1: there is no ``OrderStatus.ACTIVE`` and no run-end expiry on
the backtest path), with filled_quantity 0 and zero trades. There are NO actions:
this is the as-is assertion (D-10), not an operator scenario.

The assertion is the final ORDER-MIRROR state, so this leaf freezes the opt-in
``golden/orders.csv`` (exactly one row, status PENDING) plus an EMPTY ``trades.csv``
(zero trades) and ``summary.json`` (a no-trade run produces valid scalar fields).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): the frozen ``golden/orders.csv`` shows
EXACTLY ONE row — role STANDALONE, BTCUSD, LIMIT, BUY, status PENDING (NOT ACTIVE,
GAP #1/D-10), price 80.0, filled_quantity 0.0 — and ``golden/trades.csv`` is EMPTY.
Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   90     95     78     80     <- BUY decided here (LIMIT @ 80)
    2    2020-01-03   120    125    119    124
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with ``order_type=LIMIT`` (D-03,
Pitfall 3): the entry rests at the DECISION-bar close (D-02). NO actions.

Why the limit NEVER triggers (the BUY-LIMIT formula):
  * BUY decided on bar1 (2020-01-02). The LIMIT rests at bar1's close = 80.
  * A BUY LIMIT fills on a LATER bar only when ``open <= 80`` (gap-through) OR
    ``low <= 80`` (in-bar touch) — matching_engine ``_evaluate`` BUY-LIMIT branch.
    For every bar AFTER bar1: open is 120 / 130 / 140 (all > 80) AND low is
    119 / 129 / 139 (all > 80). BOTH conditions are false on EVERY bar, so the
    limit @ 80 can never fill. (bar1's own low of 78 is irrelevant — the limit
    does not exist until the bar1 decision, and only LATER bars are matched.)

Run-end behavior (D-10 / GAP #1):
  * The run completes cleanly over all five bars — no crash. The never-triggered
    limit simply remains resting in the matching book at run end; there is no
    run-end expiry on the backtest path.
  * The order mirror status is therefore PENDING (NOT ACTIVE — the enum has no
    ACTIVE member; ``o.status.name`` serializes ``PENDING``), filled_quantity 0.
  * ZERO trades land (nothing opened) — ``trades.csv`` is EMPTY.

============================== END VERIFY =============================
"""

import pathlib

from itrader.core.enums.order import OrderType

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a single BUY (LIMIT) decided on 2020-01-02. Its resting
# price (the decision-bar close = 80) is below every following bar's open AND low,
# so it never fills. No SELL, no actions — the order stays PENDING to run end.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
}

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(user_id=1, name="never_fill_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
    # NO actions: this is the as-is never-fill assertion (D-10), not an operator
    # scenario. An empty actions tuple keeps the run oracle-dark (no on_tick hook).
)
