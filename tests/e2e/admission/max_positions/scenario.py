"""ADMIT-03: max_positions reached -> audited new-entry REJECTED (D-04 leaf 3).

The audited concurrent-position-cap rejection. With ``max_positions = 1`` a long is
opened on a FIRST ticker (ETHUSDT); while that position is open
(``open_position_count == 1``) a BUY on a SECOND ticker (BTCUSD) is REJECTED at the
admission gate's NEW-POSITION arm (order_manager.py:934-947 —
``open_position_count(portfolio) >= signal.max_positions``): the entry is
transitioned PENDING->REJECTED through the audited ``add_state_change`` path
(``triggered_by="admission_max_positions"``) and PERSISTED; NOTHING is emitted to
the exchange, so the cap is enforced per-PORTFOLIO across tickers (the gate counts
open positions, not orders).

GATE-FIRES-BEFORE-SIZING (load-bearing, distinct from SIZE-03): the max_positions
gate runs in step 0 of ``process_signal`` BEFORE ``_resolve_signal_quantity``
(order_manager.py:335 admission gate, then :347 sizing). So the audited reject is
built UNSIZED via ``_reject_unsized_signal`` -> ``_build_primary_order(..., qty=0)``
(order_manager.py:1055/1071) and the frozen REJECTED row carries ``quantity = 0``
(NOT the FixedQuantity 40). This is the genuine semantic difference from Phase 7's
SIZE-03 cash-reservation reject, which fires AFTER sizing and therefore freezes the
sized quantity (1000). Here the cap is policed before any quantity is resolved.

Multi-ticker shape (first multi-CSV E2E leaf): the cap is a NEW-ticker gate, so the
leaf needs a second occupied ticker. Two ``ScriptedEmitter`` instances subscribe to
the ONE portfolio — an ETHUSDT emitter opens (and HOLDS) the single allowed
position, and a BTCUSD emitter fires the over-cap BUY. ``spec.ticker = "BTCUSD"``,
so the harness's orders-snapshot query (``get_orders_by_ticker(spec.ticker, ...)``,
conftest.py:320-321) returns the BTCUSD mirror — exactly the one REJECTED order. The
ETHUSDT occupier is NEVER sold, so it stays open: ``closed_positions`` is empty ->
``trades.csv`` is EMPTY -> ``trade_count = 0``. (Single-portfolio throughout — D-04;
multi-portfolio cash isolation is Phase 9.)

The ASSERTION is the final order-mirror state (the REJECTED BTCUSD entry), so this
leaf freezes the OPT-IN ``golden/orders.csv`` (the SAME opt-in orders-snapshot
vehicle SIZE-03 / Phase 6 no-trade leaves used) plus an EMPTY ``trades.csv`` and a
``summary.json``. The BTCUSD REJECTED row serializes via ``o.status.name`` (GAP #1 —
never ACTIVE).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (both ``bars.csv`` (BTCUSD) and ``bars_eth.csv`` (ETHUSDT) — daily,
tz-aware Open time, ALL prices FLAT 100 so the only moving part is the position
COUNT vs the cap):

    bar  date         open   close   event
    0    2020-01-01   100    100     warmup
    1    2020-01-02   100    100     ETH BUY decided (close=100); count still 0 -> ADMITTED
    2    2020-01-03   100    100     ETH BUY fills @ open 100 (40 units) -> count = 1
    3    2020-01-04   100    100     BTC BUY decided; count 1 >= max_positions 1 -> REJECTED
    4    2020-01-05   100    100     (no further signals; ETH position stays OPEN)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage). TWO ``ScriptedEmitter`` instances, EACH ``max_positions=1`` /
default ``allow_increase=False``, both subscribed to the ONE portfolio:
  * ETH emitter (tickers=["ETHUSDT"]): script BUY on 2020-01-02 only (no sell).
  * BTC emitter (tickers=["BTCUSD"]):  script BUY on 2020-01-04 only.
``sizing_policy = FixedQuantity(qty=Decimal("40"))`` on EACH so the cash/quantity
math is exact and hand-derivable.

Within-tick order (events_handler routes BAR -> [mark, match-resting, signals]):
the ETH BUY decided 2020-01-02 fills at the next-open 2020-01-03, OPENING the ETH
position (count -> 1) BEFORE the BTC BUY is even decided (2020-01-04). So when the
BTC BUY reaches admission the portfolio already holds 1 open position == the cap.

Admission trail:
  * bar1 (01-02): ETH BUY decided. NEW-POSITION arm: open_position_count == 0 <
    max_positions 1 -> ADMITTED. reserve 40 * decision-close 100 = 4_000
    (available 10_000 -> 6_000).
  * bar2 (01-03): ETH BUY FILLS @ next-open 100 (release the 4_000 reservation,
    debit 4_000: balance 10_000 -> 6_000). ETH position OPEN: 40 units @ 100;
    open_position_count -> 1.
  * bar3 (01-04): BTC BUY decided. get_position(BTCUSD) is None -> NEW-POSITION arm;
    open_position_count == 1 >= max_positions 1 -> the entry is transitioned
    PENDING->REJECTED (triggered_by="admission_max_positions") and PERSISTED. The
    gate fires in step 0 BEFORE sizing, so the audited order is UNSIZED (quantity 0,
    _reject_unsized_signal -> _build_primary_order qty=0). NOTHING is emitted; NO
    reservation is taken for the BTC order (the gate fires BEFORE reserve), so
    available_cash is INTACT at 6_000 (no orphan reservation).
  * bar4 (01-05): no signals; the ETH position remains OPEN and unsold.

Lifecycle: ZERO positions CLOSE (the ETH occupier is never sold; the BTC entry never
fills). The order mirror for BTCUSD holds exactly ONE order at status REJECTED.

Final BTCUSD order-mirror snapshot (``golden/orders.csv`` — the ADMIT-03 assertion;
the harness queries ONLY spec.ticker=BTCUSD, so the ETH order is not in this frame):

    role        order_type  action  status     price  quantity  filled_quantity
    STANDALONE  MARKET      BUY     REJECTED   100    0         0

(role STANDALONE — no sl/tp declared; status REJECTED via ``o.status.name``, GAP #1
— never ACTIVE. quantity == 0: the max_positions gate rejects UNSIZED, before the
FixedQuantity 40 is ever resolved — the GATE-FIRES-BEFORE-SIZING note above. price
100 is the decision-bar close stamped on the signal, frozen even on the unsized
reject.)

Final portfolio (portfolio-WIDE — the open ETH position is held to end of run):
  * final_cash = 10_000 - 4_000 (ETH buy debit) = 6_000.00 (the BTC rejection took
    NO cash — no orphan reservation).
  * final_equity = final_cash 6_000 + ETH market value (40 units @ flat 100 =
    4_000) = 10_000.00.
  * trade_count = 0, total_realised_pnl = 0.00, trades.csv EMPTY (no CLOSED position;
    the ETH position is still open, the BTC entry never opened).

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: spec.ticker is the orders-snapshot query key; the
# REJECTED entry must be on BTCUSD so the snapshot captures it.
_ETH = "ETHUSDT"    # present in the default ExchangeConfig.limits.supported_symbols
# (plus BTCUSD added on the simulated instance), so the occupier order is admitted.
_TIMEFRAME = "1d"
_CASH = 10_000

# Per-ticker date-keyed scripts (D-04): the ETH emitter opens (and holds) the single
# allowed position; the BTC emitter fires the over-cap BUY two bars later.
_ETH_SCRIPT = {
    "2020-01-02": {"side": "BUY"},   # opens ETH position (count 0 -> 1), never sold
}
_BTC_SCRIPT = {
    "2020-01-04": {"side": "BUY"},   # over-cap entry: count 1 >= max_positions 1 -> REJECTED
}

# FixedQuantity so the cash/quantity math is exact and hand-derivable.
_SIZING = FixedQuantity(qty=Decimal("40"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``). TWO
# emitters subscribe to the ONE portfolio so the portfolio-wide open-position count
# reaches the cap before the BTC entry is decided.
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv", _ETH: HERE / "bars_eth.csv"},
    strategies=[
        ScriptedEmitter(_TIMEFRAME, [_ETH], script=_ETH_SCRIPT, name="emitter_eth",
                        sizing_policy=_SIZING, max_positions=1),
        ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_BTC_SCRIPT, name="emitter_btc",
                        sizing_policy=_SIZING, max_positions=1),
    ],
    portfolios=[PortfolioSpec(name="max_positions_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the position-count cap is the only moving part.
)
