"""SLTP-01: PercentFromDecision SL-hit — scenario spec + VERIFY hand-derivation.

A BUY declaring ``sltp_policy=PercentFromDecision(sl_pct, tp_pct)`` (NO explicit
script ``sl``/``tp``, so the policy is consulted — order_manager.py:613-622). The
SL/TP children are priced at the DECISION-bar close via ``_bracket_levels(policy,
to_money(signal.price), action)`` (order_manager.py:620-622, _bracket_levels
L727-741). A later bar's low reaches the decision-anchored SL → the STOP child
triggers and the position closes at the SL level.

Order STATE is implicit (closed trade), so this leaf freezes ``trades.csv`` +
``summary.json``. Zero-fee / zero-slippage (``exchange=None``, D-14), so the SL
level (and the exit price) is the only moving part — every number traces to the
PercentFromDecision anchor + the bar prices.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-12/D-13): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   100    105    95     100    <- parent fills @ open 100; arms
    3    2020-01-04   95     96     88     92     <- low 88 <= SL 90 -> STOP fills @ 90
    4    2020-01-05   92     93     91     92     <- trailing

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), sizing = FractionOfCash(0.95) (the default), strategy =
``ScriptedEmitter`` with a DATE-keyed script (D-04): a MARKET BUY on the 2020-01-02
decision bar with NO explicit ``sl``/``tp`` (the ``sltp_policy`` is consulted) and
``sltp_policy = PercentFromDecision(sl_pct=0.10, tp_pct=0.20)``.

SL/TP levels (PercentFromDecision, anchor = decision-bar close = bar1 close = 100;
BUY -> sl below, tp above, _bracket_levels L739-741):
    SL = anchor * (1 - sl_pct) = 100 * (1 - 0.10) = 90.00  (STOP SELL child)
    TP = anchor * (1 + tp_pct) = 100 * (1 + 0.20) = 120.00 (LIMIT SELL child)

Sizing (FractionOfCash(0.95), priced off the BUY DECISION-bar close = bar1
close = 100, full available cash, no prior position):
    qty = (0.95 * 10_000) / 100 = 9_500 / 100 = 95 units (round).
SL/TP children inherit this same quantity from the assembler.

Lifecycle (decision bar -> fill bar; the next-bar-open rule):

    decision bar1 (2020-01-02): script hits BUY (policy SL=90, TP=120) -> a MARKET
        parent + DORMANT STOP(SL@90) + DORMANT LIMIT(TP@120) rest in the book.
    bar2 (2020-01-03): the MARKET parent fills at bar2 OPEN = 100, stamped
        2020-01-03, and leaves the book, ARMING the children against bar2's own
        high/low: high=105 (< TP 120) and low=95 (> SL 90), so NEITHER child
        triggers on the arming bar — both rest, now armed.
    bar3 (2020-01-04): the SL STOP(SELL @90) triggers — low=88 (<= 90) -> fills at
        ``min(open, trigger) = min(95, 90) = 90`` (matching_engine STOP-SELL
        pessimistic gap-down). high=96 (< TP 120) so the TP is NOT reachable;
        exactly one leg fills, so the TP sibling is OCO-cancelled.
    bar4 (2020-01-05): trailing bar — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @100):
  * total_bought = 95 * 100 = 9_500.00; avg_bought = 100.
Exit (SL STOP, filled bar3 @90 — the trigger price):
  * total_sold = 95 * 90 = 8_550.00; avg_sold = 90.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 100
  * exit_date  = 2020-01-04, avg_sold  = 90
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = total_sold - total_bought = 8_550 - 9_500 = -950.00
                 = (90 - 100) * 95.
  * commission = 0.00 (exchange=None).

Slippage columns (slippage model = NONE; slippage = fill price - the STORE close
series bar immediately before the fill — attach_slippage indexes the store, NOT
the run/decision grid):
  * slippage_entry = bar2 open (100) - bar1 close (100) = 0.0
  * slippage_exit  = bar3 SL fill (90) - bar2 close (100) = -10.0

Final portfolio: final_cash = final_equity = 10_000 - 950 = 9_050.00,
trade_count = 1.

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
# sl/tp — so the sltp_policy below is consulted (order_manager.py:613).
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# SLTP-01 (D-13): PercentFromDecision — children priced at the DECISION-bar close
# (anchor=100): SL = 100*(1-0.10) = 90, TP = 100*(1+0.20) = 120. String-path
# Decimal literals (Pitfall 1).
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
    portfolios=[PortfolioSpec(user_id=1, name="sltp01_sl_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage — the SL level is the only mover.
)
