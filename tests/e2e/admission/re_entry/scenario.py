"""ADMIT-04: full exit followed by re-entry on the SAME ticker (D-04 leaf 4).

A clean two-round-trip story on ONE ticker: BUY #1 opens a long, SELL #1 fully
exits it (``close_position`` sets ``is_open = False``, position.py:233-239), then
BUY #2 RE-ENTERS the same ticker. There is NO special engine handling — once the
first position is closed, ``get_position()`` returns ``None``
(portfolio_read_model.py:107-125), so the second BUY takes the FRESH-position
admission branch (order_manager.py:934 — no open position for the ticker), passes
the ``max_positions`` cap (the closed position is no longer counted), is sized as a
brand-new entry and fills. SELL #2 then closes the second position.

Lens (D-04): a CLOSED-TRADE assertion. ``build_trade_log`` records ONE row per
closed ``Position`` (frames.py:59) and each round-trip is its OWN ``Position``
object (the first closed BEFORE the second opens), so ``trades.csv`` shows TWO
clean round-trips on BTCUSD with DISTINCT (entry_date, exit_date) keys (the
commission key-merge requires one-to-one, conftest.py:360-363). This leaf freezes
``trades.csv`` + ``summary.json`` ONLY (no orders / cash snapshot — two closed
round-trips are the whole assertion). Defaults ``allow_increase=False`` /
``max_positions=1`` are correct: this is NOT a scale-in (the first position is
fully closed before the re-entry) — it is a sequential re-entry within the cap.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time; prices chosen so each
round-trip is +10/unit and every slippage column is a clean 0.0):

    bar  date         open   close   event
    0    2020-01-01   100    100     warmup
    1    2020-01-02   100    100     BUY #1 decided (close=100)
    2    2020-01-03   100    110     BUY #1 fills @ open 100 (40 units, pos1 OPEN); SELL #1 decided
    3    2020-01-04   110    120     SELL #1 fills @ open 110 (closes pos1); BUY #2 decided
    4    2020-01-05   120    130     BUY #2 fills @ open 120 (40 units, pos2 OPEN); SELL #2 decided
    5    2020-01-06   130    130     SELL #2 fills @ open 130 (closes pos2)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage). strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04),
default ``allow_increase=False`` / ``max_positions=1``.
``sizing_policy = FixedQuantity(qty=Decimal("40"))`` — each entry buys a hand-round
40 units; the decision-close reservation equals the next-open fill notional
(reservation never under-funds the fill).

Within-tick order (events_handler routes BAR -> [mark, match-resting, signals]):
on each bar the order resting from the PRIOR bar FILLS FIRST, THEN the new signal
is decided against the UPDATED position state — so SELL #1's fill CLOSES pos1
BEFORE BUY #2 is decided on the same bar, and the re-entry sees a clean book.

Lifecycle + cash trail (cost per entry = decision-close * 40):
  * bar1 (01-02): BUY #1 decided. reserve 40 * 100 = 4_000 (available 10_000 -> 6_000).
  * bar2 (01-03): BUY #1 FILLS @ next-open 100 (release 4_000, debit 4_000:
    balance 10_000 -> 6_000). pos1 OPEN: 40 units @ 100. THEN SELL #1 decided
    (exit_fraction defaults to 1 -> full exit of the 40 units).
  * bar3 (01-04): SELL #1 FILLS @ next-open 110 -> sells 40 units; net_quantity
    0 -> close_position fires, pos1 CLOSED (credit 40 * 110 = 4_400: balance
    6_000 -> 10_400). THEN BUY #2 decided -> get_position() is now None ->
    FRESH entry; open_position_count is 0 so the max_positions=1 cap passes.
    reserve 40 * decision-close 120 = 4_800 (available 10_400 -> 5_600).
  * bar4 (01-05): BUY #2 FILLS @ next-open 120 (release 4_800, debit 4_800:
    balance 10_400 -> 5_600). pos2 OPEN: 40 units @ 120. THEN SELL #2 decided
    (full exit).
  * bar5 (01-06): SELL #2 FILLS @ next-open 130 -> sells 40 units; net_quantity
    0 -> pos2 CLOSED (credit 40 * 130 = 5_200: balance 5_600 -> 10_800).

Resulting TWO closed round-trips on BTCUSD (each its OWN Position, distinct keys):
  Round-trip 1:
    * entry_date = 2020-01-03, exit_date = 2020-01-04, side = LONG
    * avg_bought = 100, avg_sold = 110, net_quantity = 0
    * total_bought = 4_000, total_sold = 4_400, avg_price = 100
    * realised_pnl = (110 - 100) * 40 = 400
  Round-trip 2:
    * entry_date = 2020-01-05, exit_date = 2020-01-06, side = LONG
    * avg_bought = 120, avg_sold = 130, net_quantity = 0
    * total_bought = 4_800, total_sold = 5_200, avg_price = 120
    * realised_pnl = (130 - 120) * 40 = 400

Final portfolio: final_cash = 10_800; final_equity = 10_800 (no open position);
trade_count = 2; total_realised_pnl = 400 + 400 = 800.

Slippage columns (attach_slippage: fill price - decision-bar close; all 0.0 here
because every entry open == the prior bar's close and every exit open == the prior
bar's close):
  * RT1: slippage_entry = 100 - bar1 close (100) = 0.0; slippage_exit = 110 -
    bar2 close (110) = 0.0
  * RT2: slippage_entry = 120 - bar3 close (120) = 0.0; slippage_exit = 130 -
    bar4 close (130) = 0.0

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): BUY #1 -> full SELL (close) -> BUY #2 (re-entry, same
# ticker) -> full SELL (close). Two clean sequential round-trips within max_positions=1.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},   # BUY #1 — opens pos1
    "2020-01-03": {"side": "SELL"},  # full exit of pos1 (exit_fraction defaults to 1)
    "2020-01-04": {"side": "BUY"},   # BUY #2 — RE-ENTRY on the same ticker (fresh position)
    "2020-01-05": {"side": "SELL"},  # full exit of pos2
}

# FixedQuantity so each entry is exactly 40 units and the cash math is hand-derivable.
_SIZING = FixedQuantity(qty=Decimal("40"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(name="re_entry_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the re-entry lifecycle is the only moving part.
)
