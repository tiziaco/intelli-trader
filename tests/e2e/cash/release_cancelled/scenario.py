"""CASH-02 CANCELLED: a reserved resting LIMIT BUY, operator-cancelled -> POSITIVE
release on the cash ledger (D-04 leaf 5, D-03).

The first of CASH-02's two POSITIVE-release leaves. A LIMIT BUY rests far below
market (it would never fill on its own — like the Phase 6 operator/cancel leaf),
so its admission RESERVATION is held the whole time it rests. An operator CANCEL
then removes it mid-run, and the load-bearing assertion is that the cancel fires a
POSITIVE ``RELEASE_RESERVATION`` op in the cash-ledger snapshot (the local-cancel
release at order_manager.py:1225-1227): the reservation that was held is given back,
``available_cash`` returns intact, and no orphan reservation lingers.

Why the cash-ledger LENS (D-02), not "available_cash returns to full": the latter
cannot distinguish a never-reserved order from a reserved-then-released one. The
snapshot shows the EXPLICIT ``RESERVATION`` -> ``RELEASE_RESERVATION`` pair on the
SAME derived order correlation, proving the release actually FIRED — the whole point
of CASH-02.

Operator round-trip (Phase 6 infra, reused verbatim from matching/operator/cancel):
``actions=(Action(bar_date=..., kind="cancel", ticker="BTCUSD"),)`` wires the harness
``on_tick`` hook, which resolves the SOLE PENDING BTCUSD order by predicate and calls
the REAL ``OrderHandler.cancel_order(order.id, portfolio_id)`` (GAP #2 — the resolved
UUIDv7, never an int).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   90     95     78     80     <- BUY decided here (close=80)
    2    2020-01-03   120    125    119    124    <- CANCEL scheduled (on_tick)
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage — cash is the only moving part), strategy = ``ScriptedEmitter`` with
``order_type=OrderType.LIMIT`` so the entry RESTS at the decision-bar close (D-02 —
strategies_handler stamps SignalEvent.price = bar.close), and the default
``allow_increase=False`` / ``max_positions=1``. ``sizing_policy =
FixedQuantity(qty=Decimal("40"))`` so the reserve math is exact:
reserve = decision-close 80 * 40 = 3_200.

Where the order rests and why it never fills naturally:
  * BUY decided on bar1 (2020-01-02). With order_type=LIMIT the entry rests at
    bar1's close = 80 (the decision-bar close, D-02).
  * A BUY LIMIT fills only when a LATER bar's open <= 80 (gap-through) OR low <= 80
    (in-bar touch). Every bar AFTER bar1 has open >= 120 and low >= 119, so the
    limit @ 80 is unreachable: absent the operator it would rest forever.

Cash + reservation trail (reserve cost = decision-close 80 * 40 = 3_200):
  * bar1 (01-02): BUY decided. Admission reserves 3_200 -> available_cash
    10_000 -> 6_800; the order RESTS (PENDING) in the matching book. RESERVATION
    records balance_before == balance_after == 10_000 (a reservation moves only
    available_balance, not the ledger balance — cash_manager.py:365-416).
  * bar2 (01-03): operator CANCEL scheduled at on_tick. The harness resolves the
    sole PENDING BTCUSD order and calls the REAL cancel_order round-trip. The CANCEL
    OrderEvent is drained at the START of bar3's process_events (FIFO), the local
    terminal transition fires the release (order_manager.py:1225-1227):
    RELEASE_RESERVATION 3_200 -> available_cash 6_800 -> 10_000 (intact again).
    RELEASE_RESERVATION likewise records balance_before == balance_after == 10_000
    (idempotent pop_reservation, cash_manager.py:418-448 — it gives back the held
    reservation; the ledger balance never moved because the order never filled).
  * bars 3-4: no signals; the order is gone from the book (CANCELLED); nothing fills.

Lifecycle: ZERO positions ever open (the limit never matched), ZERO trades close ->
``trades.csv`` is EMPTY, ``trade_count = 0``. final_cash = final_equity = 10_000.00
(the reservation was released, never committed to a fill).

Cash-ledger snapshot (``golden/cash_operations.csv`` — the CASH-02 CANCELLED lens,
D-02). The derived ``correlation`` collapses the raw UUIDv7 ``reference_id`` to a
stable ORDER-{n:03d} ordinal in first-appearance order so the RESERVATION matches its
RELEASE without leaking the id; ``operation_id`` / raw ``reference_id`` / wall-clock
``timestamp`` are EXCLUDED (determinism contract). The reservation and its release
are keyed by the SAME order id, so they share ONE correlation ordinal. The frozen
rows (sorted by correlation, operation_type, amount):

    correlation  operation_type        amount    balance_before  balance_after
    ORDER-001    RELEASE_RESERVATION    3200.00   10000.00        10000.00   <- operator cancel releases
    ORDER-001    RESERVATION            3200.00   10000.00        10000.00   <- admission reserves the resting limit

The LOAD-BEARING CASH-02 CANCELLED fact: the SAME ORDER-001 shows a RESERVATION
(3_200) that COMMITS at admission and is later RELEASED (RELEASE_RESERVATION 3_200,
matching amount, POSITIVE) by the operator cancel — proving the reservation was held
while the limit rested and the cancel actually FIRED its release. There is NO
TRANSACTION_DEBIT/CREDIT (the order never filled), and available_cash returns intact.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType
from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import Action, PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a single BUY decided on 2020-01-02. With order_type=LIMIT
# the entry rests at that bar's close (80) — far below every following bar's range,
# so it never fills on its own and the reservation is held until the operator cancels.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
}

# FixedQuantity so the reserve math is exact: 40 units @ decision-close 80 = 3_200.
_SIZING = FixedQuantity(qty=Decimal("40"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING, order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(user_id=1, name="release_cancelled_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the reserve/release is the only moving part.
    # Operator CANCEL (Phase 6 infra): resolve the sole PENDING BTCUSD order at bar2
    # and call the REAL cancel_order(order.id, ...) round-trip (UUID, GAP #2).
    actions=(Action(bar_date="2020-01-03", kind="cancel", ticker="BTCUSD"),),
)
