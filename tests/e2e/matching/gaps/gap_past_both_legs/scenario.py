"""MATCH-06: a bar that GAPS past BOTH bracket legs still fills exactly ONE leg.

A MARKET-entry bracket arms an SL (SELL STOP) and TP (SELL LIMIT) child. After
the parent fills and the children arm, ONE bar GAPS such that BOTH legs are
candidates AND the OPEN itself is already past a leg. The engine's two-pass
``on_bar`` collects both candidates, ``_pick_bracket_winner`` prefers the STOP, so
exactly ONE leg (the SL) fills and the TP is OCO-cancelled. The point of this leaf
vs MATCH-05 (same-bar in-bar double trigger) is the GAP: the bar's OPEN is itself
below the SL (open 108 < SL 110), proving the gap path still resolves to one fill.

SL gapped fill = ``min(open, SL_trigger)`` = the pessimistic gapped open (108),
NOT the 110 trigger — a gap-down through the stop fills at the worse open.

The opt-in ``golden/orders.csv`` is the assertion: role ENTRY FILLED, role SL
FILLED, role TP CANCELLED (D-08/D-09; GAP #1 — PENDING/FILLED/CANCELLED, never
ACTIVE; no UUIDs). Explicit Decimal sl/tp levels (D-15). Zero-fee / zero-slippage
(``exchange=None``, D-14). MARKET entry, default FractionOfCash(0.95).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (MATCH-06 / D-13): the frozen ``golden/{trades.csv,
summary.json,orders.csv}`` MATCH the derivation below. Re-freeze ONLY via
``--freeze`` after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    125    99     120    <- BUY MARKET decision (close 120); sl=110, tp=130
    2    2020-01-03   120    122    118    120    <- ENTRY fill bar: MARKET fills at open=120; children ARM
    3    2020-01-04   108    135    105    120    <- GAP-PAST-BOTH bar (open 108 below SL 110; high 135 above TP 130)
    4    2020-01-05   108    112    105    108    <- trailing bar (Pitfall 6: last bar never fills)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None,
strategy = ``ScriptedEmitter`` (default MARKET entry, FractionOfCash(0.95)) with a
DATE-keyed script: BUY + explicit sl=110, tp=130 decided on 2020-01-02.

Entry (BUY MARKET decided on bar1 / 2020-01-02):
  * The MARKET parent rests and fills at the NEXT bar's open = bar2 open = 120
    (entry_date 2020-01-03). The bracket SL (SELL STOP @110) and TP (SELL LIMIT
    @130) children are linked to the parent (parent_order_id) and DORMANT while
    the parent rests (CR-01); they ARM the instant the parent leaves the book.
  * Sizing on the DECISION close (120): qty = (0.95 * 10_000) / 120 = 9_500/120
    = 79.1666... units. total_bought = (9_500/120) * 120 = 9_500.0; avg_bought
    = 120.
  * SAME bar (bar2) child evaluation against bar2 high/low: SL@110 needs
    ``low <= 110`` -> 118 <= 110 FALSE; TP@130 needs ``open >= 130`` (120>=130
    FALSE) or ``high >= 130`` (122>=130 FALSE). Neither fires -> both rest into
    bar3.

Gap-past-both (bar3 / 2020-01-04, open 108, high 135, low 105):
  * SL (SELL STOP @110): ``low <= trigger`` -> 105 <= 110 -> CANDIDATE.
  * TP (SELL LIMIT @130): ``open >= trigger`` (108>=130 FALSE), else
    ``high >= trigger`` -> 135 >= 130 -> CANDIDATE.
  * BOTH legs are candidates this bar; ``_pick_bracket_winner`` prefers the STOP
    -> SL wins. SL gapped fill = ``min(open, trigger)`` = min(108, 110) = 108
    (the bar GAPPED DOWN clean past the 110 stop, open 108 < 110, so the OPEN is
    the pessimistic fill). The TP is OCO-CANCELLED (sibling filled).
  * total_sold = (9_500/120) * 108 = 8_550.0; avg_sold = 108.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120
  * exit_date  = 2020-01-04, avg_sold  = 108  (SL exit, stamped at the bar3 fill)
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = total_sold - total_bought = 8_550 - 9_500 = -950.0
                 = (108 - 120) * 9_500/120  (a LOSS — the SL gapped past, the
                   stop filled at the worse open).

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 - 950 = 9_050.0
  * final_equity = final_cash = 9_050.0
  * trade_count = 1, total_realised_pnl = -950.0

Slippage columns (D-17 — fill price - decision-bar close):
  * slippage_entry = bar2 fill (120) - bar1 close (120) = 0.0
  * slippage_exit  = bar3 fill (108) - bar2 close (120) = -12.0

Order-mirror snapshot (``golden/orders.csv`` — opt-in, D-09): role ENTRY FILLED
(the MARKET parent), role SL FILLED (the gapped stop), role TP CANCELLED (OCO
sibling). Exactly ONE leg filled despite the gap past BOTH. No ACTIVE, no UUIDs.

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

# Date-keyed script (D-04): a single BUY MARKET with explicit Decimal sl/tp
# (D-15) decided 2020-01-02. The bracket children are assembled by the order
# manager regardless of the MARKET entry type (D-03). No SELL is scripted — the
# SL leg closes the position.
_SCRIPT = {
    "2020-01-02": {"side": "BUY",
                   "sl": Decimal("110"),
                   "tp": Decimal("130")},
}

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    # Default MARKET entry; the bracket assembler builds the SL/TP children.
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="gap_both_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
