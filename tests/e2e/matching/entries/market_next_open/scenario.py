"""MATCH-01: MARKET next-bar-open fill — scenario spec + VERIFY hand-derivation.

This is the D-13 PROOF leaf: the simplest matching scenario, authored end-to-end
through the Phase 6 shared infra (the promoted ``ScenarioSpec`` from
``tests/e2e/scenario_spec.py`` + the date-keyed ``ScriptedEmitter`` from
``tests/e2e/strategies/scripted_emitter.py``) to prove the wiring once before the
parallel scenario wave. It exercises MATCH-01: a MARKET BUY decided on a bar rests
in the book and fills at the NEXT bar's OPEN; a full MARKET SELL decided later fills
at its next bar's open — exactly ONE round-trip LONG trade.

Pure-fill scenario (D-09): the assertion is the closed trade, so the golden set is
``trades.csv`` + ``summary.json`` only — NO ``orders.csv`` (no resting/never-filled
order to snapshot). Zero-fee / zero-slippage (``exchange=None``, D-14), so fills are
clean and hand-derivable from the next-bar-open rule.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below (single LONG BTCUSD trade:
buy @120 on 2020-01-03, sell @140 on 2020-01-05, realised_pnl 1_666.666…,
final_equity 11_666.666…, trade_count 1). Re-freeze ONLY via ``--freeze`` after
re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   110    115    109    114
    2    2020-01-03   120    125    119    124
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144
    5    2020-01-06   150    155    149    154

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04):
a BUY scripted on the 2020-01-02 decision bar and a full SELL scripted on the
2020-01-04 decision bar. ``order_type`` defaults to MARKET (D-03).

Decision bar → fill bar (the next-bar-open rule; Pitfall 6 — the LAST dataset bar
can never fill, so the SELL is scripted on bar3, not bar5):

    decision bar1 (2020-01-02): script hit BUY  → MARKET order rests → fills at
                                bar2 OPEN (120) stamped 2020-01-03
    decision bar3 (2020-01-04): script hit SELL → MARKET order rests → fills at
                                bar4 OPEN (140) stamped 2020-01-05

Entry (BUY decided on bar1 / 2020-01-02):
  * Sizing uses the DECISION-bar close (bar1 close = 114) and full available cash
    (10_000, no prior position): qty = (0.95 * 10_000) / 114 = 9_500 / 114
    = 83.3333… (250/3) units.
  * The MARKET order fills at the NEXT bar's open = bar2 open = 120, stamped
    entry_date 2020-01-03.
  * total_bought = (250/3) * 120 = 10_000.00 (full cash deployed); avg_bought = 120.

Exit (full SELL decided on bar3 / 2020-01-04, exit_fraction defaults to 1):
  * The MARKET exit fills at the NEXT bar's open = bar4 open = 140, stamped
    exit_date 2020-01-05; it sells the entire 250/3 units.
  * total_sold = (250/3) * 140 = 11_666.666… → avg_sold = 140.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120
  * exit_date  = 2020-01-05, avg_sold  = 140
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_666.666… - 10_000 = 1_666.666…
                 = (140 - 120) * 250/3.

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 + 1_666.666… = 11_666.666…
  * final_equity = final_cash = 11_666.666…
  * trade_count = 1, total_realised_pnl = 1_666.666…

Slippage columns (D-17 — frozen in ``golden/trades.csv`` as 6.0 / 6.0):
slippage = fill price − decision-bar close (the bar immediately before the fill).
  * slippage_entry = bar2 open (120) − bar1 close (114) = 6.0
  * slippage_exit  = bar4 open (140) − bar3 close (134) = 6.0

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

# Date-keyed script (D-04): BUY decided 2020-01-02, full SELL decided 2020-01-04.
# The LAST bar (2020-01-06) is never a decision bar — its fill could not land
# (Pitfall 6), so the SELL is scripted on bar3 (2020-01-04), filling on bar4.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-04": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(name="match01_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
