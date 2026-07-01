"""SLTP-02: PercentFromFill SL-hit — scenario spec + VERIFY hand-derivation.

A BUY declaring ``sltp_policy=PercentFromFill(sl_pct, tp_pct)`` (NO explicit script
``sl``/``tp``, so the policy is consulted — order_manager.py:613/623-636). UNLIKE
PercentFromDecision, NO children are created at assembly: a ``_PendingBracket`` is
armed (order_manager.py:628) and the SL/TP children are created in ``on_fill`` via
``_create_fill_anchored_children`` (order_manager.py:743-761), priced from the
ACTUAL next-bar-open FILL price — NOT the decision-bar close. A later bar's low
reaches the fill-anchored SL → the STOP child triggers and the position closes at
the SL level.

Freezes ``trades.csv`` + ``summary.json``. Zero-fee / zero-slippage
(``exchange=None``, D-14).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-12/D-13): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round). NOTE
the decision close (bar1 = 100) and the next-bar OPEN (bar2 = 90) DIFFER on
purpose, so the FILL anchor (90) is visibly distinct from a hypothetical DECISION
anchor (100) — the SLTP-01/02 contrast. (The fill is BELOW the decision close so
the entry notional 95*90 = 8_550 stays within the 9_500 reserved at the decision
price — the reservation gate sizes off the decision close, the fill anchors lower.)

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   90     95     88     92     <- parent fills @ OPEN 90 == fill anchor
    3    2020-01-04   85     86     79     82     <- low 79 <= SL 81 -> STOP fills @ 81
    4    2020-01-05   82     83     81.5   82     <- trailing

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), sizing = FractionOfCash(0.95) (the default), strategy =
``ScriptedEmitter`` with a DATE-keyed script (D-04): a MARKET BUY on the 2020-01-02
decision bar with NO explicit ``sl``/``tp`` and
``sltp_policy = PercentFromFill(sl_pct=0.10, tp_pct=0.20)``.

FILL anchor + SL/TP levels (PercentFromFill, anchor = the ACTUAL fill price = the
next-bar-open = bar2 open = 90; BUY -> sl below, tp above, _bracket_levels
L739-741):
    SL = anchor * (1 - sl_pct) = 90 * (1 - 0.10) = 81.00   (STOP SELL child)
    TP = anchor * (1 + tp_pct) = 90 * (1 + 0.20) = 108.00  (LIMIT SELL child)
  CONTRAST: a DECISION anchor (bar1 close 100) would give SL=90 / TP=120 — the
  fill-anchored levels above are DIFFERENT (the point of SLTP-01 vs SLTP-02).

Sizing (FractionOfCash(0.95), priced off the BUY DECISION-bar close = 100, full
available cash, no prior position):
    qty = (0.95 * 10_000) / 100 = 95 units (round). Children inherit qty=95.

Lifecycle (decision bar -> fill bar; the next-bar-open rule):

    decision bar1 (2020-01-02): BUY (PercentFromFill) -> a MARKET parent rests; NO
        children yet (a _PendingBracket is armed, order_manager.py:628).
    bar2 (2020-01-03): the MARKET parent fills at bar2 OPEN = 90, stamped
        2020-01-03. on_fill anchors the children off this fill price: STOP(SL@81)
        + LIMIT(TP@108) are created and rest. bar2 low=88 (> SL 81) / high=95
        (< TP 108) — neither would trigger anyway.
    bar3 (2020-01-04): the SL STOP(SELL @81) triggers — low=79 (<= 81) -> fills at
        ``min(open, trigger) = min(85, 81) = 81`` (STOP-SELL pessimistic gap-down).
        high=86 (< TP 108): the TP is NOT reachable; exactly one leg fills, so the
        TP sibling is OCO-cancelled.
    bar4 (2020-01-05): trailing bar — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @90):
  * total_bought = 95 * 90 = 8_550.00; avg_bought = 90.
Exit (SL STOP, filled bar3 @81 — the trigger price):
  * total_sold = 95 * 81 = 7_695.00; avg_sold = 81.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 90
  * exit_date  = 2020-01-04, avg_sold  = 81
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = total_sold - total_bought = 7_695 - 8_550 = -855.00
                 = (81 - 90) * 95.
  * commission = 0.00 (exchange=None).

Slippage columns (slippage model = NONE; slippage = fill price - the STORE close
series bar immediately before the fill):
  * slippage_entry = bar2 open (90) - bar1 close (100) = -10.0
  * slippage_exit  = bar3 SL fill (81) - bar2 close (92) = -11.0

Final portfolio: final_cash = final_equity = 10_000 - 855 = 9_145.00,
trade_count = 1.

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
# sl/tp — so the sltp_policy below is consulted (order_manager.py:613).
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# SLTP-02 (D-13): PercentFromFill — children priced at the ACTUAL fill price (the
# next-bar open = 90): SL = 90*(1-0.10) = 81, TP = 90*(1+0.20) = 108. DIFFERENT
# from a decision-close anchor (which would give SL=90 / TP=120).
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
    portfolios=[PortfolioSpec(name="sltp02_sl_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage — the SL level is the only mover.
)
