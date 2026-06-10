"""MULTI-04: two strategies CONTEND for one portfolio's cash on the SAME bar (D-02).

The adversarial counterpart to MULTI-02. Two ``ScriptedEmitter`` instances both
BUY on the SAME decision bar, subscribed to the ONE portfolio, but the portfolio
cannot fund BOTH. The outcome is FULLY DETERMINISTIC by registration order (D-02,
NON-NEGOTIABLE):

  * The WINNER is ``spec.strategies[0]`` — its BUY is dispatched FIRST and reserves
    essentially all the portfolio's cash, then fills and round-trips.
  * The LOSER is ``spec.strategies[1]`` — its BUY reaches the synchronous
    check-and-reserve admission gate SECOND, finds insufficient available cash, and
    is transitioned PENDING->REJECTED (``triggered_by="cash_reservation"``) and
    PERSISTED. Crucially it leaves NO orphan reservation: ``reserve_cash`` raises
    ``InsufficientFundsError`` BEFORE recording any RESERVATION op (cash_manager.py
    :393-410), so the cash ledger holds the winner's lifecycle and NOTHING for the
    loser.

Determinism source (D-02): ``StrategiesHandler`` emits per-strategy signals in
``spec.strategies`` registration order; ``OrderManager`` processes the queue FIFO.
So the first-registered strategy's BUY always reserves first. There is no RNG, no
wall-clock, no dict-iteration nondeterminism on this path — the winner/loser split
is hand-verifiable and the no-tolerance golden diff + the Plan-01 double-run test
lock reproducibility (T-09-03).

Vehicles (per D-02 and the harness query mechanics):
  * ``spec.ticker = "BTCUSD"`` is the LOSER's ticker. The orders-snapshot query is
    ``get_orders_by_ticker(spec.ticker, portfolio_id)`` (conftest.py:364-365), so
    ``golden/orders.csv`` captures EXACTLY the one BTCUSD order — the loser's
    REJECTED row, carrying the SIZED quantity (cash_reservation fires AFTER sizing).
  * The WINNER trades ETHUSDT (a DIFFERENT ticker), so it is absent from the
    BTCUSD-scoped orders snapshot, but its round-trip lands in the portfolio-wide
    ``trades.csv`` and its reserve/release/transaction lifecycle lands in the
    portfolio-wide ``cash_operations.csv``. ``cash_operations`` therefore shows the
    WINNER's RESERVATION (and the rest of its lifecycle) and NO orphan for the loser.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars — daily, tz-aware Open time. Two CSVs:

    BTCUSD (``bars.csv``, the LOSER — flat 100)
    bar date         open  close   event
    0   2020-01-01   100   100     warmup
    1   2020-01-02   100   100     LOSER BUY decided (close 100) -> REJECTED (no cash)
    2..4 ...flat 100...            (loser never opens; no further BTC signal)

    ETHUSDT (``bars_eth.csv``, the WINNER)
    bar date         open  close   event
    0   2020-01-01   100   100     warmup
    1   2020-01-02   100   100     WINNER BUY decided (close 100) -> reserves 9_500
    2   2020-01-03   100   100     WINNER BUY fills @ open 100 (95 units)
    3   2020-01-04   120   120     WINNER SELL decided (close 120)
    4   2020-01-05   120   120     WINNER SELL fills @ open 120 (full exit)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage — the cash contention is the only moving part). TWO emitters on the
ONE portfolio, in this registration order (D-02):
  * ``spec.strategies[0]`` = WINNER: ScriptedEmitter("1d", ["ETHUSDT"], ...),
    FixedQuantity(95). BUY 2020-01-02, SELL 2020-01-04.
  * ``spec.strategies[1]`` = LOSER:  ScriptedEmitter("1d", ["BTCUSD"], ...),
    FixedQuantity(50). BUY 2020-01-02 only.

The WINNER's reserve (95 * decision-close 100 = 9_500) is sized to consume
essentially all the 10_000 cash, so only 500 remains — far less than the LOSER's
50 * 100 = 5_000 reserve. The split is therefore unambiguous AND hand-derivable.

Contended-bar admission trail (bar1 / 2020-01-02 — both BUYs decided here; the
WINNER's signal is emitted FIRST by registration order, drained FIRST by FIFO):
  1. WINNER ETHUSDT BUY: direction/max_positions admit; FixedQuantity(95) sizes 95
     @ decision-close 100; cost 95 * 100 + 0 = 9_500 <= 10_000 available -> RESERVE
     SUCCEEDS. available_cash 10_000 -> 500. (RESERVATION op: balance_before ==
     balance_after == 10_000 — a reservation moves only available_balance.)
  2. LOSER BTCUSD BUY: direction/max_positions admit; FixedQuantity(50) sizes 50 @
     decision-close 100; cost 50 * 100 + 0 = 5_000 > 500 available -> ``reserve_cash``
     raises ``InsufficientFundsError`` at cash_manager.py:393-397, BEFORE
     ``add_reservation`` / ``_create_operation``. The primary is transitioned
     PENDING->REJECTED (``triggered_by="cash_reservation"``) and stored; NOTHING is
     emitted; NO RESERVATION row is recorded for the loser (no orphan).

WINNER round-trip (ETHUSDT, fees 0):
  * bar2 (01-03): BUY fills @ next-open 100 (95 units). Release the 9_500
    reservation; TRANSACTION_DEBIT -9_500 (balance 10_000 -> 500).
  * bar4 (01-05): SELL fills @ next-open 120 (full 95 units). TRANSACTION_CREDIT
    +11_400 (balance 500 -> 11_900).
  * entry_date 2020-01-03, avg_bought 100 ; exit_date 2020-01-05, avg_sold 120.
  * total_bought 9_500 ; total_sold 11_400 ; realised_pnl = (120 − 100) * 95 = 1_900.

Final order-mirror snapshot (``golden/orders.csv`` — BTCUSD only = the loser):
    role        order_type  action  status     price  quantity  filled_quantity
    STANDALONE  MARKET      BUY     REJECTED   100    50        0
(role STANDALONE — no sl/tp; status REJECTED via ``o.status.name``, GAP #1; quantity
50 — the SIZED loser quantity, because cash_reservation fires AFTER sizing, contrast
ADMIT-03's gate-before-sizing quantity=0.)

Final cash-ledger snapshot (``golden/cash_operations.csv`` — portfolio-wide, the
WINNER's lifecycle; the LOSER contributes NO row). The TRANSACTION ops are keyed by
the transaction id (distinct ordinals) and the RESERVATION/RELEASE by the order id:
    correlation  operation_type        amount     balance_before  balance_after
    ORDER-001    RELEASE_RESERVATION    9500.00      500.00          500.00
    ORDER-001    RESERVATION            9500.00    10000.00        10000.00
    ORDER-002    TRANSACTION_DEBIT     -9500.00    10000.00          500.00
    ORDER-003    TRANSACTION_CREDIT    11400.00      500.00        11900.00
The LOAD-BEARING MULTI-04 facts: the WINNER's RESERVATION (9_500) is present and the
LOSER has NO RESERVATION row at all (no orphan) — the deterministic split proved on
the cash ledger.

Final portfolio (winner round-trip closed, loser never opened):
  * final_cash = 10_000 + 1_900 = 11_900.00 ; final_equity = 11_900.00 (flat).
  * trade_count = 1 (the winner's ETHUSDT round-trip; the loser never opens a
    position), total_realised_pnl = 1_900.00.

summary.json ``ticker`` = spec.ticker = BTCUSD (the label only). The metrics block is
machine-computed and frozen as-written; the load-bearing hand-checked facts are the
winner fill/PnL, the loser REJECTED row (sized 50), and the no-orphan cash ledger.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_BTC = "BTCUSD"   # spec.ticker = the LOSER's ticker, so the orders snapshot captures
# EXACTLY the one REJECTED loser order. Added on the simulated instance.
_ETH = "ETHUSDT"  # the WINNER's ticker; present in the default supported-symbol set.
_TIMEFRAME = "1d"
_CASH = 10_000

# WINNER script (spec.strategies[0]): buy then sell a round-trip on ETHUSDT.
_ETH_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}
# LOSER script (spec.strategies[1]): a single over-contended BUY on BTCUSD.
_BTC_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# Sized so the WINNER's reserve (95 * 100 = 9_500) consumes nearly all the 10_000
# cash, leaving only 500 — far below the LOSER's 50 * 100 = 5_000 reserve, so the
# second BUY cannot reserve. Both quantities are exact / hand-derivable.
_WINNER_SIZING = FixedQuantity(qty=Decimal("95"))
_LOSER_SIZING = FixedQuantity(qty=Decimal("50"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``). The
# registration ORDER is the D-02 determinism contract: strategies[0] WINS,
# strategies[1] LOSES.
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_BTC,  # the LOSER's ticker -> orders.csv = the one REJECTED row.
    starting_cash=_CASH,
    data={_BTC: HERE / "bars.csv", _ETH: HERE / "bars_eth.csv"},
    strategies=[
        # [0] WINNER — dispatched first by registration order, reserves all cash.
        ScriptedEmitter(_TIMEFRAME, [_ETH], script=_ETH_SCRIPT,
                        sizing_policy=_WINNER_SIZING),
        # [1] LOSER — dispatched second, cash_reservation gate REJECTS it.
        ScriptedEmitter(_TIMEFRAME, [_BTC], script=_BTC_SCRIPT,
                        sizing_policy=_LOSER_SIZING),
    ],
    portfolios=[PortfolioSpec(user_id=1, name="contended_cash_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the cash contention is the only moving part.
)
