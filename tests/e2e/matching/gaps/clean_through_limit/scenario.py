"""MATCH-06: gap clean-through a resting LIMIT — better-than-limit gap fill.

A standalone LIMIT order rests at trigger ``T``; the next bar GAPS clean past
``T`` so the OPEN (BETTER than the trigger) is the fill. This is the gap-through
case of the limit-or-better formula (``matching_engine._evaluate``):

    BUY  LIMIT: ``open <= trigger`` -> fill OPEN (gap-through, better)
    SELL LIMIT: ``open >= trigger`` -> fill OPEN (gap-through, better)

A *clean* gap makes the OPEN the fill (open is the BETTER value), proving the
limit-or-better asymmetry: where a STOP fills pessimistically at the worse open,
a LIMIT fills favorably at the better open. Contrast with the in-bar touch case
(``low/high`` reaches T but open is on the wrong side -> fill at the trigger
exactly), which is MATCH-02; this leaf is the GAP-THROUGH (open already past T).

This leaf uses a BUY-LIMIT gap-down ENTRY (open < T, fill at the cheaper open) to
stay LONG_ONLY (D-02 / Pitfall 3 — entry order_type is per-INSTANCE LIMIT), then
closes the long with a SELL-LIMIT gap-up EXIT (open > T, fill at the richer
open). Both legs are STANDALONE (no bracket) so the opt-in ``golden/orders.csv``
records role STANDALONE, status FILLED on each (D-08/D-09; GAP #1 — never
ACTIVE). Zero-fee / zero-slippage (``exchange=None``, D-14). FractionOfCash(0.95)
is safe here because a BUY LIMIT fills at-or-below its reservation trigger.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-06 / D-13): the frozen ``golden/{trades.csv,
summary.json,orders.csv}`` MATCH the derivation below. Re-freeze ONLY via
``--freeze`` after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    125    99     120    <- BUY decision, close = T_entry = 120
    2    2020-01-03   108    112    106    110    <- ENTRY fill bar (gap-DOWN clean past 120)
    3    2020-01-04   130    135    128    140    <- SELL decision, close = T_exit = 140
    4    2020-01-05   150    155    148    150    <- EXIT fill bar (gap-UP clean past 140)
    5    2020-01-06   150    155    148    150    <- trailing bar (Pitfall 6: last bar never fills)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None,
strategy = ``ScriptedEmitter(order_type=LIMIT)`` (default FractionOfCash(0.95))
with a DATE-keyed script: BUY on 2020-01-02, full SELL on 2020-01-04.

Entry (BUY LIMIT decided on bar1 / 2020-01-02, trigger = decision close = 120):
  * Order rests as a BUY LIMIT @120 (entry price = decision-bar close, D-02).
  * Fill bar = bar2 (next-bar, Pitfall 6). BUY LIMIT rule: ``open <= trigger``
    -> 108 <= 120 -> fill = OPEN = 108. The bar GAPPED DOWN clean past 120
    (open 108 < T 120), so the OPEN is the BETTER fill (cheaper than the 120
    limit), NOT a 120 trigger fill.
  * Sizing on the DECISION close (120) with FractionOfCash(0.95):
    qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 79.1666... units.
  * total_bought = (9_500/120) * 108 = 8_550.0; avg_bought = 108.

Exit (SELL LIMIT decided on bar3 / 2020-01-04, trigger = decision close = 140):
  * Order rests as a SELL LIMIT @140 (closes the long).
  * Fill bar = bar4 (next-bar). SELL LIMIT rule: ``open >= trigger`` -> 150 >=
    140 -> fill = OPEN = 150. The bar GAPPED UP clean past 140 (open 150 > T
    140), so the OPEN is the BETTER fill (richer than the 140 limit).
  * total_sold = (9_500/120) * 150 = 11_875.0; avg_sold = 150.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 108
  * exit_date  = 2020-01-05, avg_sold  = 150
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_875 - 8_550 = 3_325.0
                 = (150 - 108) * 9_500/120  (a GAIN — both gaps favored the long:
                   bought cheap, sold rich — the limit-or-better path).

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 + 3_325 = 13_325.0
  * final_equity = final_cash = 13_325.0
  * trade_count = 1, total_realised_pnl = 3_325.0

Slippage columns (D-17 — fill price - decision-bar close):
  * slippage_entry = bar2 fill (108) - bar1 close (120) = -12.0
  * slippage_exit  = bar4 fill (150) - bar3 close (140) = 10.0

Order-mirror snapshot (``golden/orders.csv`` — opt-in, D-09): two STANDALONE
orders, both FILLED (the gapped BUY-LIMIT entry + the gapped SELL-LIMIT exit). No
ACTIVE (GAP #1), no UUIDs.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): BUY decided 2020-01-02, full SELL decided 2020-01-04.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-04": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    # order_type=LIMIT makes the entry a resting LIMIT (Pitfall 3). The default
    # FractionOfCash(0.95) is safe: a BUY LIMIT fills at-or-below its trigger.
    strategies=[ScriptedEmitter(
        _TIMEFRAME, [_TICKER], script=_SCRIPT, order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(name="gap_limit_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
