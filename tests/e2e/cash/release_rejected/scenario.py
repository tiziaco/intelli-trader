"""CASH-02 REJECTED: an over-cash BUY rejected AT the cash-reservation gate ->
the HONEST NEGATIVE no-orphan assertion on the cash ledger (D-04 leaf 7, D-03).

The asymmetric NEGATIVE leaf that completes CASH-02. REJECTED structurally NEVER
holds a reservation: every REJECTED path fires AT or BEFORE ``reserve()``. This leaf
picks the cleanest hand-derivable trigger — the synchronous admission
cash-reservation gate (order_manager.py:393-414): a ``FixedQuantity`` whose notional
EXCEEDS available cash makes ``portfolio_handler.reserve(...)`` raise
``InsufficientFundsError``, and the failure goes through the audited
``add_state_change`` path (PENDING->REJECTED, ``triggered_by="cash_reservation"``)
and is PERSISTED; NOTHING is emitted to the exchange.

The load-bearing fact is that ``reserve_cash`` (cash_manager.py:393-410) raises the
``InsufficientFundsError`` BEFORE ``add_reservation`` / ``_create_operation`` — so
when the over-cash reserve fails, NO ``RESERVATION`` op is ever recorded and NO
reservation is held. The cash ledger for this order is EMPTY: the negative
no-orphan assertion.

Why a DISTINCT framing from SIZE-03 (which uses the SAME cash-reservation trigger):
SIZE-03's lens is the ORDER-MIRROR — its frozen ``orders.csv`` REJECTED row (the
sized quantity, ``triggered_by``). THIS leaf's lens is the CASH-LEDGER no-orphan:
the load-bearing golden is ``cash_operations.csv``, asserting the ABSENCE of any
``RESERVATION`` row for the rejected order (D-02). The ``orders.csv`` REJECTED row is
frozen here too, but only for completeness — the negative cash assertion is the point.

Why the cash-ledger LENS (D-02): "available_cash returns to full" cannot distinguish
a never-reserved order from a reserved-then-released one. The two POSITIVE CASH-02
leaves (release_cancelled, release_refused) show the explicit RESERVATION ->
RELEASE_RESERVATION pair; this NEGATIVE leaf shows the explicit ABSENCE — an EMPTY
cash ledger — proving the rejection took no cash at all (T-08-06).

Do NOT fabricate a reserve-then-REJECTED path — none exists (the cash_reservation
reject IS the reserve failing atomically; max_positions / direction / sizing rejects
fire before reserve; the owner-gated reserve-then-reject is deferred).

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   100    105    99     100
    3    2020-01-04   100    105    99     100

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage — the reservation is the only moving part), strategy =
``ScriptedEmitter`` (default ``order_type=MARKET``, ``allow_increase=False`` /
``max_positions=1``) with a single MARKET BUY decided 2020-01-02. NO SELL.
``sizing_policy = FixedQuantity(qty=Decimal("1000"))`` — a deliberately OVER-CASH
fixed quantity (mirrors SIZE-03's magnitude so the math is identically derivable).

Sizing + the cash-reservation rejection (order_manager.py:393-414):
  * decision price = bar1 close = 100 (strategies_handler stamps SignalEvent.price).
  * gates in step 0 do NOT trip: direction admits (a fresh-ticker LONG BUY),
    max_positions admits (open_position_count == 0 < 1), so the signal reaches sizing.
  * FixedQuantity is a pass-through: qty = 1000 — sizing SUCCEEDS (no cash check
    there; that is the admission gate's job, D-15). The primary is built SIZED at
    1000 @ price 100.
  * validation (step 3) passes (a positive-quantity MARKET BUY is valid).
  * the admission cash-reservation gate (step 3b) computes
    cost = price * quantity + estimated_commission = 100 * 1000 + 0 = 100_000.00
    (zero estimated commission with exchange = None).
  * ``portfolio_handler.reserve(...)`` -> ``reserve_cash`` checks
    ``available_balance (10_000) < amount (100_000)`` -> raises ``InsufficientFundsError``
    at cash_manager.py:393-397, BEFORE ``add_reservation`` (L399) and BEFORE
    ``_create_operation(RESERVATION)`` (L402-410). So NOTHING is reserved and NO
    RESERVATION op is recorded. The primary is transitioned PENDING->REJECTED
    (``triggered_by="cash_reservation"``) and stored; NOTHING is emitted (D-02).

Lifecycle: there is NO next-bar fill — the order never reaches the exchange. The run
completes cleanly over all four bars. The order mirror holds exactly ONE order at
status REJECTED; ZERO positions open; ZERO trades close.

Cash-ledger snapshot (``golden/cash_operations.csv`` — the CASH-02 REJECTED NEGATIVE
lens, D-02). Because the reserve raised BEFORE recording any op, the rejected order
contributes NOTHING to the ledger; the initial cash is set directly on the balance
(CashManager.__init__ — NO seed DEPOSIT op, cash_manager.py:64), so the WHOLE ledger
is empty. The frozen ``cash_operations.csv`` is the HEADER ONLY (no rows):

    correlation,operation_type,amount,balance_before,balance_after
    (no rows)

The LOAD-BEARING CASH-02 REJECTED fact: the ABSENCE of any RESERVATION row for the
rejected order — there is NO orphan reservation, because the over-cash reserve raised
atomically before recording anything. available_cash is INTACT at 10_000 (no cash
was ever moved or held). This is the honest asymmetric counterpart to the two
POSITIVE leaves: REJECTED structurally never reserves, so there is nothing to release.

Order-mirror snapshot (``golden/orders.csv`` — frozen for COMPLETENESS, NOT the
load-bearing assertion; the same opt-in vehicle SIZE-03 uses). Exactly ONE row, role
STANDALONE, BTCUSD, MARKET, BUY, status REJECTED (``o.status.name``, GAP #1 — never
ACTIVE), price 100, quantity 1000 (the cash_reservation reject fires AFTER sizing, so
the SIZED quantity is frozen — contrast ADMIT-03's gate-before-sizing quantity=0),
filled_quantity 0:

    role        order_type  action  status     price  quantity  filled_quantity
    STANDALONE  MARKET      BUY     REJECTED   100    1000      0

Final portfolio: final_cash = final_equity = 10_000.00 (untouched — the reserve that
would have debited cash RAISED instead and recorded nothing), trade_count = 0,
trades.csv EMPTY.

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

# Date-keyed script (D-04): a single MARKET BUY decided 2020-01-02, NO SELL. The
# over-cash quantity is REJECTED at the admission cash-reservation gate BEFORE any
# reservation is recorded, so the cash ledger stays empty (the no-orphan negative).
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# CASH-02 REJECTED (D-03): an OVER-CASH FixedQuantity. 1000 units @ the decision
# price 100 = 100_000 notional, 10x the 10_000 cash -> the admission cash-reservation
# gate raises InsufficientFundsError BEFORE recording a RESERVATION op -> no orphan.
_SIZING = FixedQuantity(qty=Decimal("1000"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-04",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(name="release_rejected_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the rejected reservation is the only moving part.
)
