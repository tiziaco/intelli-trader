"""SLTP-02/03: PercentFromFill held-to-end — scenario spec + VERIFY note.

A BUY declaring ``sltp_policy=PercentFromFill(sl_pct, tp_pct)`` (NO explicit script
``sl``/``tp``, so the policy is consulted — order_manager.py:613/623-636). NO
children at assembly: a ``_PendingBracket`` is armed (order_manager.py:628) and the
SL/TP children are created in ``on_fill`` (``_create_fill_anchored_children``,
order_manager.py:743-761), priced from the ACTUAL next-bar-open FILL price (90):
SL=81, TP=108. Then NO later bar reaches either level through run end → the
position stays OPEN, both children stay PENDING, and NO closed trade ever lands
(SLTP-03 held-to-end).

The ASSERTION is the held outcome, so this leaf freezes the OPT-IN ``orders.csv``
snapshot (ENTRY FILLED + SL/TP children PENDING — mirrors ``matching/never_fill``
PENDING-not-ACTIVE, Pitfall 4) plus a ``summary.json`` with ``trade_count = 0`` and
a NON-FLAT ``final_equity`` (the open LONG marked at the final close). An EMPTY
``trades.csv`` alone would be no meaningful assertion (Pitfall 4). An EMPTY
``golden/orders.csv`` placeholder opts the leaf into the snapshot freeze (same
vehicle as never_fill). Zero-fee / zero-slippage (``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-12/Pitfall 4): the frozen ``golden/orders.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round). The
decision close (bar1 = 100) and the next-bar OPEN (bar2 = 90) DIFFER, so the FILL
anchor (90) is distinct from a hypothetical DECISION anchor (100). (The fill is
BELOW the decision close so the entry notional 95*90 = 8_550 stays within the
9_500 reserved at the decision price.)

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   90     95     88     92     <- parent fills @ OPEN 90 == fill anchor
    3    2020-01-04   93     100    85     96     <- 85 > SL 81, 100 < TP 108 (no trigger)
    4    2020-01-05   96     105    87     98     <- 87 > SL 81, 105 < TP 108 (no trigger)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), sizing = FractionOfCash(0.95) (the default), strategy =
``ScriptedEmitter`` with a DATE-keyed script (D-04): a MARKET BUY on the 2020-01-02
decision bar with NO explicit ``sl``/``tp`` and
``sltp_policy = PercentFromFill(sl_pct=0.10, tp_pct=0.20)``.

FILL anchor + SL/TP levels (PercentFromFill, anchor = the ACTUAL fill price = the
next-bar-open = bar2 open = 90):
    SL = 90 * (1 - 0.10) = 81.00   (STOP SELL child)
    TP = 90 * (1 + 0.20) = 108.00  (LIMIT SELL child)
  CONTRAST: a DECISION anchor (100) would give SL=90 / TP=120 — DIFFERENT levels.

Sizing: qty = (0.95 * 10_000) / 100 = 95 units (round). Children inherit qty=95.

Lifecycle (the held outcome):

    decision bar1 (2020-01-02): BUY (PercentFromFill) -> a MARKET parent rests; NO
        children yet (a _PendingBracket is armed).
    bar2 (2020-01-03): MARKET parent fills @ open 90, stamped 2020-01-03; on_fill
        anchors STOP(SL@81) + LIMIT(TP@108) off the fill. bar2 high=95 (< 108),
        low=88 (> 81): neither triggers.
    bar3 (2020-01-04): high=100 (< TP 108), low=85 (> SL 81): neither triggers.
    bar4 (2020-01-05): high=105 (< TP 108), low=87 (> SL 81): neither triggers.
    Run ends with the LONG position OPEN and BOTH children resting (PENDING) —
    no run-end expiry on the backtest path (D-10 / GAP #1).

NO closed trade: ``trades.csv`` is EMPTY, ``trade_count = 0``.

Final order-mirror snapshot (``golden/orders.csv`` — the SLTP-03 assertion; roles
from linkage flags, statuses PENDING/FILLED, NEVER ACTIVE). NOTE: the ENTRY order's
``price`` column is the DECISION price (100 — the price stamped on the MARKET parent
at assembly), NOT the bar2-open fill price (90). The fill price (90) is what anchors
the fill-anchored CHILDREN (SL=81, TP=108) — see the trade ``avg_bought`` in the
SL/TP-hit siblings. The children prices (81, 108) ARE the visible SLTP-02 evidence.
The illustrative table below abbreviates to the load-bearing columns; the real
golden also pins the leading ``ticker`` (BTCUSD) and the trailing deterministic
``time`` identity column per ``ORDER_SNAPSHOT_COLUMNS`` (reporting/orders.py:39-49):

    role   order_type  action  status   price  quantity  filled_quantity
    ENTRY  MARKET      BUY     FILLED   100    95        95     (price = decision price)
    SL     STOP        SELL    PENDING  81     95        0      (= fill 90 * 0.90)
    TP     LIMIT       SELL    PENDING  108    95        0      (= fill 90 * 1.20)

Final portfolio (open LONG marked at the final close = bar4 close = 98):
  * cash = 10_000 - (95 * 90) = 10_000 - 8_550 = 1_450.00 (the entry debit only).
  * position value = 95 * 98 = 9_310.00 (open mark at the last close).
  * final_equity = cash + position value = 1_450 + 9_310 = 10_760.00 (NON-FLAT —
    distinct from starting_cash, so the open mark is genuinely exercised).
  * trade_count = 0.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import PercentFromFill
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a single MARKET BUY decided 2020-01-02, NO explicit
# sl/tp — so the sltp_policy below is consulted. No SELL — the position is held.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# SLTP-02 (D-13): PercentFromFill — SL=81, TP=108 (fill anchor=90). The bars never
# reach either level, so the position is held to run end (SLTP-03).
_SLTP = PercentFromFill(sl_pct=Decimal("0.10"), tp_pct=Decimal("0.20"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sltp_policy=_SLTP)],
    portfolios=[PortfolioSpec(name="sltp02_held_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
