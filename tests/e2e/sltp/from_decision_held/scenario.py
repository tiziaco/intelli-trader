"""SLTP-01/03: PercentFromDecision held-to-end — scenario spec + VERIFY note.

A BUY declaring ``sltp_policy=PercentFromDecision(sl_pct, tp_pct)`` (NO explicit
script ``sl``/``tp``, so the policy is consulted — order_manager.py:613-622). The
SL/TP children are priced at the DECISION-bar close (anchor=100): SL=90, TP=120.
Then NO later bar reaches either level through run end → the position stays OPEN,
both children stay PENDING, and NO closed trade ever lands (SLTP-03 held-to-end).

The ASSERTION is the held outcome, so this leaf freezes the OPT-IN ``orders.csv``
snapshot (ENTRY FILLED + SL/TP children PENDING — mirrors ``matching/never_fill``
PENDING-not-ACTIVE, Pitfall 4) plus a ``summary.json`` with ``trade_count = 0`` and
a NON-FLAT ``final_equity`` (the open LONG marked at the final close). An EMPTY
``trades.csv`` alone would be no meaningful assertion (Pitfall 4) — the
orders-snapshot + summary are the real lock. An EMPTY ``golden/orders.csv``
placeholder opts the leaf into the snapshot freeze (same vehicle as never_fill).
Zero-fee / zero-slippage (``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-12/Pitfall 4): the frozen ``golden/orders.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   100    105    95     100    <- parent fills @ open 100; arms
    3    2020-01-04   102    108    96     105    <- 96 > SL 90, 108 < TP 120 (no trigger)
    4    2020-01-05   105    110    98     108    <- 98 > SL 90, 110 < TP 120 (no trigger)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), sizing = FractionOfCash(0.95) (the default), strategy =
``ScriptedEmitter`` with a DATE-keyed script (D-04): a MARKET BUY on the 2020-01-02
decision bar with NO explicit ``sl``/``tp`` and
``sltp_policy = PercentFromDecision(sl_pct=0.10, tp_pct=0.20)``.

SL/TP levels (PercentFromDecision, anchor = decision-bar close = 100):
    SL = 100 * (1 - 0.10) = 90.00  (STOP SELL child)
    TP = 100 * (1 + 0.20) = 120.00 (LIMIT SELL child)

Sizing: qty = (0.95 * 10_000) / 100 = 95 units (round). Children inherit qty=95.

Lifecycle (the held outcome):

    decision bar1 (2020-01-02): BUY -> MARKET parent + DORMANT STOP(SL@90) +
        DORMANT LIMIT(TP@120) rest.
    bar2 (2020-01-03): MARKET parent fills @ open 100, stamped 2020-01-03, arming
        the children. bar2 high=105 (< 120), low=95 (> 90): neither triggers.
    bar3 (2020-01-04): high=108 (< TP 120), low=96 (> SL 90): neither triggers.
    bar4 (2020-01-05): high=110 (< TP 120), low=98 (> SL 90): neither triggers.
    Run ends with the LONG position OPEN and BOTH children resting (PENDING) —
    there is no run-end expiry on the backtest path (D-10 / GAP #1).

NO closed trade: ``trades.csv`` is EMPTY, ``trade_count = 0``.

Final order-mirror snapshot (``golden/orders.csv`` — the SLTP-03 assertion; roles
from linkage flags, statuses PENDING/FILLED, NEVER ACTIVE):

    role   order_type  action  status   price  quantity  filled_quantity
    ENTRY  MARKET      BUY     FILLED   100    95        95
    SL     STOP        SELL    PENDING  90     95        0
    TP     LIMIT       SELL    PENDING  120    95        0

Final portfolio (open LONG marked at the final close = bar4 close = 108):
  * cash = 10_000 - (95 * 100) = 10_000 - 9_500 = 500.00 (the entry debit only).
  * position value = 95 * 108 = 10_260.00 (open mark at the last close).
  * final_equity = cash + position value = 500 + 10_260 = 10_760.00 (NON-FLAT —
    distinct from starting_cash, so the open mark is genuinely exercised).
  * trade_count = 0.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import PercentFromDecision
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

# SLTP-01 (D-13): PercentFromDecision — SL=90, TP=120 (anchor=100). The bars never
# reach either level, so the position is held to run end (SLTP-03).
_SLTP = PercentFromDecision(sl_pct=Decimal("0.10"), tp_pct=Decimal("0.20"))

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
    portfolios=[PortfolioSpec(name="sltp01_held_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
