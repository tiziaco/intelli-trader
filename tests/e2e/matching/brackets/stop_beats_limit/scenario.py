"""MATCH-05: same-bar STOP-beats-LIMIT priority — scenario spec + VERIFY note.

Covers the same-bar double-trigger priority rule (CONTEXT D-03/D-08/D-09/D-11/D-15):
a MARKET BUY entry declares explicit Decimal SL/TP children; after the parent fills
and the children arm, a SINGLE bar is authored whose HIGH >= TP AND LOW <= SL so
BOTH the SL(stop) and TP(limit) legs are candidates on the same bar. The engine's
``_pick_bracket_winner`` returns the STOP leg (pessimistic same-bar priority): the
SL fills and the TP sibling is OCO-cancelled.

Order STATE is the assertion, so this leaf freezes the OPT-IN ``orders.csv``
snapshot (D-08/D-09) in addition to ``trades.csv`` + ``summary.json``: it proves
ENTRY FILLED, SL FILLED, TP CANCELLED (statuses PENDING/FILLED/CANCELLED, GAP #1:
never ``ACTIVE``, no UUIDs). Zero-fee / zero-slippage (``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-11/D-15): the frozen ``golden/{trades,orders}.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   110    115    109    114
    1    2020-01-02   118    122    117    120
    2    2020-01-03   120    125    119    124
    3    2020-01-04   120    132    108    118     <- the double-trigger bar
    4    2020-01-05   118    121    116    119

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04): a BUY
with explicit Decimal SL=110 / TP=130 scripted on the 2020-01-02 decision bar.
``order_type`` defaults to MARKET (D-03 — a MARKET-entry bracket); the SL child is a
STOP (action SELL @110), the TP child is a LIMIT (action SELL @130), both inverted
from the BUY parent and priced verbatim from the intent (D-15).

Sizing uses the DECISION-bar close (bar1 close = 120) and full available cash
(10_000): qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.1666… (475/6) units. The
SL/TP children inherit this same quantity from the assembler.

Lifecycle (decision bar -> fill bar; the next-bar-open rule, Pitfall 6):

    decision bar1 (2020-01-02): script hits BUY (sl=110, tp=130) -> a MARKET parent
        + DORMANT STOP(SL@110) + DORMANT LIMIT(TP@130) rest in the book.
    bar2 (2020-01-03): PASS 1 fills the MARKET parent at bar2 OPEN (120), stamped
        2020-01-03; it leaves the book, ARMING the children in PASS 2 against bar2's
        own high/low. bar2 high=125 (< TP 130) and low=119 (> SL 110), so NEITHER
        child triggers on the arming bar — both rest, now armed.
    bar3 (2020-01-04): the SINGLE double-trigger bar — open=120, HIGH=132 (>= TP 130)
        AND LOW=108 (<= SL 110): BOTH legs are candidates. ``_pick_bracket_winner``
        returns the STOP (SL) leg. The SL STOP(SELL @110) fills at MIN(open, trigger)
        = MIN(120, 110) = 110 (SELL-STOP pessimistic gap formula). The TP LIMIT
        sibling is OCO-cancelled (``CancelDecision`` -> ``FillEvent(CANCELLED)``),
        even though its trigger was also reached this bar.
    bar4 (2020-01-05): trailing bar (Pitfall 6) — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @120):
  * total_bought = (475/6) * 120 = 9_500.00; avg_bought = 120.
Exit (SL STOP, filled bar3 @110 — the pessimistic stop price):
  * total_sold = (475/6) * 110 = 8_708.333…; avg_sold = 110.

Resulting SINGLE round-trip trade (a LOSS — SL is below entry; fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120
  * exit_date  = 2020-01-04, avg_sold  = 110
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = total_sold - total_bought = 8_708.333… - 9_500
                 = -791.666… = (110 - 120) * 475/6.

Slippage columns (frozen in ``golden/trades.csv``):
slippage = fill price − decision-bar close (the bar immediately before the fill).
  * slippage_entry = bar2 open (120) − bar1 close (120) = 0.0
  * slippage_exit  = bar3 SL fill (110) − bar2 close (124) = -14.0

Final order-mirror snapshot (``golden/orders.csv`` — the D-08 assertion; STOP beats
LIMIT on the same bar; statuses PENDING/FILLED/CANCELLED, NEVER ACTIVE):

    role   order_type  action  status     price  quantity   filled_quantity
    ENTRY  MARKET      BUY     FILLED     120    475/6      475/6
    SL     STOP        SELL    FILLED     110    475/6      475/6
    TP     LIMIT       SELL    CANCELLED  130    475/6      0

Final portfolio: final_cash = final_equity = 10_000 - 791.666… = 9_208.333…,
trade_count = 1.

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

# Date-keyed script (D-04): a BUY with explicit Decimal SL=110 / TP=130 (D-15)
# decided on 2020-01-02. The MARKET parent fills bar2, arming the STOP/LIMIT
# children; bar3 reaches BOTH legs and the STOP wins (_pick_bracket_winner).
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": Decimal("110"), "tp": Decimal("130")},
}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="match05_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
