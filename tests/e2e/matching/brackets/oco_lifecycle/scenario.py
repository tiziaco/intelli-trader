"""MATCH-04: bracket OCO full lifecycle — scenario spec + VERIFY hand-derivation.

Covers the bracket OCO lifecycle (CONTEXT D-03/D-08/D-09/D-11/D-15): a MARKET BUY
entry declares explicit Decimal SL/TP children. While the parent rests the children
are DORMANT (CR-01 parent-filled gate); when the parent fills they arm against the
same/later bar; on a later bar exactly ONE leg (the TP) triggers, fills, and the
unfilled sibling (the SL) is OCO-cancelled.

Order STATE is the assertion here, so this leaf freezes the OPT-IN ``orders.csv``
snapshot (D-08/D-09) in addition to ``trades.csv`` + ``summary.json``: the snapshot
proves ENTRY FILLED, TP FILLED, SL CANCELLED with logical ENTRY/SL/TP roles and
PENDING/FILLED/CANCELLED statuses (GAP #1: never ``ACTIVE``), no UUIDs. Zero-fee /
zero-slippage (``exchange=None``, D-14), so every fill price is hand-derivable from
the engine trigger/gap formulas.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-11/D-15): the frozen ``golden/{trades,orders}.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   110    115    109    114
    1    2020-01-02   118    122    117    120
    2    2020-01-03   120    125    119    124
    3    2020-01-04   130    142    128    138
    4    2020-01-05   140    145    139    144

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04): a BUY
with explicit Decimal SL=100 / TP=140 scripted on the 2020-01-02 decision bar.
``order_type`` defaults to MARKET (D-03 — a MARKET-entry bracket); the SL child is a
STOP (action SELL @100), the TP child is a LIMIT (action SELL @140), both inverted
from the BUY parent and priced verbatim from the intent (D-15).

Sizing uses the DECISION-bar close (bar1 close = 120) and full available cash
(10_000, no prior position): qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.1666…
(475/6) units. SL/TP children inherit this same quantity from the assembler.

Lifecycle (decision bar -> fill bar; the next-bar-open rule, Pitfall 6):

    decision bar1 (2020-01-02): script hits BUY (sl=100, tp=140) -> a MARKET parent
        + DORMANT STOP(SL@100) + DORMANT LIMIT(TP@140) rest in the book.
    bar2 (2020-01-03): PASS 1 fills the MARKET parent at bar2 OPEN (120), stamped
        2020-01-03; it leaves the book, which ARMS the children in PASS 2 against
        bar2's own high/low. bar2 high=125 (< TP 140) and low=119 (> SL 100), so
        NEITHER child triggers on the arming bar — both rest, now armed.
    bar3 (2020-01-04): the TP LIMIT(SELL @140) triggers — open=130 (< 140, no
        gap-through) but high=142 (>= 140) -> in-bar TOUCH fill at the trigger 140
        (SELL-LIMIT formula: ``open >= trigger ? open : high >= trigger ? trigger``).
        The SL STOP(SELL @100) is NOT reachable (bar3 low=128 > 100). Exactly one
        leg fills, so the SL sibling is OCO-cancelled (``CancelDecision`` ->
        ``FillEvent(CANCELLED)``).
    bar4 (2020-01-05): trailing bar (Pitfall 6) — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @120):
  * total_bought = (475/6) * 120 = 9_500.00; avg_bought = 120.
Exit (TP LIMIT, filled bar3 @140 — the touch price):
  * total_sold = (475/6) * 140 = 11_083.333…; avg_sold = 140.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120
  * exit_date  = 2020-01-04, avg_sold  = 140
  * net_quantity = 0 (fully closed by the TP)
  * realised_pnl = total_sold - total_bought = 11_083.333… - 9_500
                 = 1_583.333… = (140 - 120) * 475/6.

Slippage columns (frozen in ``golden/trades.csv``):
slippage = fill price − decision-bar close (the bar immediately before the fill).
  * slippage_entry = bar2 open (120) − bar1 close (120) = 0.0
  * slippage_exit  = bar3 TP fill (140) − bar2 close (124) = 16.0

Final order-mirror snapshot (``golden/orders.csv`` — the D-08 assertion; roles
derived from linkage flags, statuses are PENDING/FILLED/CANCELLED, NEVER ACTIVE):

    role   order_type  action  status     price  quantity   filled_quantity
    ENTRY  MARKET      BUY     FILLED     120    475/6      475/6
    SL     STOP        SELL    CANCELLED  100    475/6      0
    TP     LIMIT       SELL    FILLED     140    475/6      475/6

Final portfolio: final_cash = final_equity = 10_000 + 1_583.333… = 11_583.333…,
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

# Date-keyed script (D-04): a BUY with explicit Decimal SL/TP levels (D-15) decided
# on 2020-01-02. The MARKET parent fills bar2, arming the STOP(SL@100)/LIMIT(TP@140)
# children; the TP touches on bar3 and the SL is OCO-cancelled.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": Decimal("100"), "tp": Decimal("140")},
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
    portfolios=[PortfolioSpec(name="match04_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
