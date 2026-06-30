"""ADMIT-02: partial scale-out via ``exit_fraction < 1`` across multiple sells (D-04 leaf 2).

A long is opened with a single BUY, then UNWOUND over THREE sells: two partial
exits (``exit_fraction = 0.5``) that each close HALF of the CURRENT net quantity
and KEEP THE POSITION OPEN, then a final full-close sell (``exit_fraction``
defaults to 1) that zeroes the position. This exercises the partial-close arm of
``resolve_exit`` (sizing_resolver.py:165-172 — ``net_quantity * exit_fraction``;
the golden policy carries ``step_size = None`` so the dust guard is inert and the
sized exit is byte-exact) and the partial-sell branch of ``update_position``
(position.py:218-230 — a SELL accumulates ``sell_quantity`` and the position
stays ``is_open`` until ``net_quantity`` hits 0, then ``close_position`` fires,
position.py:233-239).

Lens (D-04): this is a CLOSED-TRADE assertion. The trade log records ONE
aggregated round-trip per ``Position`` (build_trade_log iterates
``closed_positions``, frames.py:59) — the three partial sells aggregate into the
single closed position's ``avg_sold`` / ``total_sold`` / ``sell_quantity``. The
load-bearing proof that the partials each sized to ``net_quantity * exit_fraction``
is the price-WEIGHTED ``avg_sold``: with each leg filling at a DISTINCT price it
equals 135 ONLY if the per-leg quantities are exactly 40 / 20 / 20. This leaf
therefore freezes ``trades.csv`` + ``summary.json`` ONLY (no orders / cash
snapshot — the closed-trade aggregate is the whole assertion).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time; prices RISE so each
partial sell fills at a distinct price and the weighted ``avg_sold`` is the
load-bearing proof of the per-leg quantities):

    bar  date         open   close   event
    0    2020-01-01   100    100     warmup
    1    2020-01-02   100    100     BUY decided (close=100)
    2    2020-01-03   100    120     BUY fills @ open 100 (80 units); SELL #1 decided
    3    2020-01-04   120    140     SELL #1 fills @ open 120 (40 units); SELL #2 decided
    4    2020-01-05   140    160     SELL #2 fills @ open 140 (20 units); SELL #3 decided
    5    2020-01-06   160    160     SELL #3 fills @ open 160 (20 units) -> CLOSE

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage — the only moving part is the partial-exit quantity math). strategy =
``ScriptedEmitter`` with a DATE-keyed script (D-04), default
``allow_increase=False`` / ``max_positions=1`` (a single position, scaled OUT).
``sizing_policy = FixedQuantity(qty=Decimal("80"))`` — the entry buys a hand-round
80 units so the 0.5 partials are integer (40, then 20).

Within-tick order (events_handler routes BAR -> [mark, match-resting, signals]):
on each bar the order resting from the PRIOR bar FILLS FIRST (updating the
position's net_quantity), THEN the new SELL signal is decided and sized against the
UPDATED net_quantity. So the scale-out is cleanly sequential and hand-derivable.

Partial-exit sizing (resolve_exit: net_quantity * exit_fraction, step_size=None):
  * bar1 (01-02): BUY decided. FixedQuantity(80) -> reserve 80 * decision-close 100
    = 8_000 against the 10_000 cash (available 10_000 -> 2_000).
  * bar2 (01-03): BUY FILLS @ next-open 100 (release 8_000, debit 8_000). Position
    OPEN: net_quantity = 80 @ avg_bought 100. THEN SELL #1 decided with
    exit_fraction 0.5 -> resolve_exit(80, 0.5) = 40 units. (SELLs do NOT reserve.)
  * bar3 (01-04): SELL #1 FILLS @ next-open 120 -> sells 40 units; the position
    STAYS OPEN at net_quantity 80 - 40 = 40. THEN SELL #2 decided exit_fraction 0.5
    -> resolve_exit(40, 0.5) = 20 units.
  * bar4 (01-05): SELL #2 FILLS @ next-open 140 -> sells 20 units; STAYS OPEN at
    net_quantity 40 - 20 = 20. THEN SELL #3 decided (exit_fraction defaults to 1 ->
    full) -> resolve_exit(20, 1) = 20 units (the D-07 structural no-op).
  * bar5 (01-06): SELL #3 FILLS @ next-open 160 -> sells the final 20 units;
    net_quantity 20 - 20 = 0 -> close_position fires, the position closes.

Resulting SINGLE closed round-trip (the three partial sells aggregate into ONE
closed Position — the LOAD-BEARING proof of per-leg sizing is the WEIGHTED avg_sold):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03 (BUY's fill bar), exit_date = 2020-01-06 (last sell fill)
  * buy_quantity = 80, avg_bought = 100, total_bought = 80 * 100 = 8_000
  * sell_quantity = 40 + 20 + 20 = 80 (fully closed), net_quantity = 0
  * avg_sold = (40*120 + 20*140 + 20*160) / 80 = (4_800 + 2_800 + 3_200) / 80
            = 10_800 / 80 = 135  <- only 135 if the partials were exactly 40/20/20
  * total_sold = 135 * 80 = 10_800
  * avg_price = (avg_bought * buy_quantity + buy_commission) / buy_quantity
             = (100 * 80 + 0) / 80 = 100
  * realised_pnl = (avg_sold - avg_bought) * sell_quantity = (135 - 100) * 80 = 2_800

Final portfolio: final_cash = 10_000 - 8_000 + 10_800 = 12_800; final_equity =
12_800 (no open position); trade_count = 1; total_realised_pnl = 2_800.

Slippage columns (attach_slippage: fill price - decision-bar close; D-17):
  * slippage_entry = avg_bought 100 - decision_close(entry_date 01-03) = 100 -
    bar1 close (100) = 0.0
  * slippage_exit  = avg_sold 135 - decision_close(exit_date 01-06) = 135 -
    bar4 close (160) = -25.0  (the AGGREGATE weighted avg_sold vs the LAST sell's
    decision-bar close — a post-hoc attribution artifact, hand-derived here so the
    frozen number is explained).

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

# Date-keyed script (D-04): BUY (open), two HALF partial sells (exit_fraction 0.5)
# that keep the position open between them, then a full-close sell.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},                                # opens 80 units
    "2020-01-03": {"side": "SELL", "exit_fraction": Decimal("0.5")},  # 0.5 * 80 = 40
    "2020-01-04": {"side": "SELL", "exit_fraction": Decimal("0.5")},  # 0.5 * 40 = 20
    "2020-01-05": {"side": "SELL"},                               # full close (0.5*... -> default 1)
}

# FixedQuantity so the partial-exit quantities are exact integers (80 -> 40 -> 20).
_SIZING = FixedQuantity(qty=Decimal("80"))

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
    portfolios=[PortfolioSpec(name="scale_out_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the exit-quantity math is the only moving part.
)
