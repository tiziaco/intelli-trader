"""ADMIT-01 + CASH-01: scale-in pyramiding until cash runs out (D-04 leaf 1, D-01).

The ONE deliberate two-outcome fold of Phase 8 (D-04): a coherent "pyramid until
cash runs out" story that proves BOTH requirements on one set of contrived bars.

* ADMIT-01 (pyramiding works) — with ``allow_increase=True`` a second BUY for an
  already-open long FALLS THROUGH the admission increase-gate to entry sizing
  (order_manager.py:916-930) and is reserved/filled as a scale-in add. v1.0 only
  ever validated the ``False``/reject direction; this leaf proves the True path.
* CASH-01 (over-cash no-commit) — a FURTHER scale-in add whose reservation cost
  EXCEEDS the remaining ``available_cash`` is REJECTED at the synchronous admission
  cash-reservation gate (order_manager.py:393-414): ``reserve()`` raises
  ``InsufficientFundsError``, the order is transitioned PENDING->REJECTED
  (``triggered_by="cash_reservation"``), and — the load-bearing assertion — the
  RESERVATION NEVER COMMITS to the cash ledger (no orphan RESERVATION row,
  ``available_cash`` left intact).

CASH-01 vs Phase-7 SIZE-03 (D-01 non-duplication): SIZE-03 already froze the exact
``triggered_by="cash_reservation"`` rejection via a SINGLE over-cash first entry
asserted on the ORDER-MIRROR (orders.csv REJECTED row). This leaf must NOT re-prove
that. It uses a DISTINCT trigger (a scale-in Nth add that exhausts remaining cash,
NOT an oversized first entry) AND a DISTINCT lens (the CASH-LEDGER snapshot's
no-commit trail, NOT the order mirror). Different bars, different lens → genuine
coverage, zero overlap. This leaf therefore freezes the opt-in
``golden/cash_operations.csv`` (the D-02 cash-ledger snapshot) plus ``trades.csv``
and ``summary.json`` — and does NOT freeze ``orders.csv``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices FLAT 100 so
the only moving part is the cash math):

    bar  date         open   high   low    close
    0    2020-01-01   100    100    100    100
    1    2020-01-02   100    100    100    100   <- BUY #1 decided (close=100)
    2    2020-01-03   100    100    100    100   <- BUY #1 fills; BUY #2 decided
    3    2020-01-04   100    100    100    100   <- BUY #2 fills; BUY #3 decided -> REJECTED
    4    2020-01-05   100    100    100    100   <- SELL decided (full exit)
    5    2020-01-06   100    100    100    100   <- SELL fills (closes 80 units)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage — cash is the only moving part), strategy = ``ScriptedEmitter`` with a
DATE-keyed script (D-04) and ``allow_increase=True`` (ADMIT-01), ``max_positions=1``
(scale-in stays within ONE position — adds, not new tickers).
``sizing_policy = FixedQuantity(qty=Decimal("40"))`` — each add costs a hand-round
40 units @ price 100 = 4_000 notional, so the third add deterministically exhausts
remaining cash.

Within-tick order (events_handler routes BAR -> [mark, match-resting, signals]):
on each bar the order resting from the PRIOR bar FILLS FIRST (releasing its
reservation + debiting cash via the EXECUTED fill), THEN the new signal is admitted
and reserves against the UPDATED available_cash. So the scale-in is cleanly
sequential and hand-derivable.

Cash + admission trail (cost per add = decision-close 100 * 40 = 4_000):
  * bar1 (01-02): BUY #1 decided. reserve 4_000 -> available_cash 10_000 -> 6_000.
  * bar2 (01-03): BUY #1 FILLS @ next-open 100 (release the 4_000 reservation,
    debit 4_000 from the balance: balance 10_000 -> 6_000, available 6_000).
    Position OPEN: 40 units @ 100. THEN BUY #2 decided (ADMIT-01 scale-in:
    allow_increase=True -> falls through to entry sizing). reserve 4_000 ->
    available 6_000 -> 2_000.
  * bar3 (01-04): BUY #2 FILLS @ 100 (release 4_000, debit 4_000: balance
    6_000 -> 2_000, available 2_000). Position OPEN: 80 units @ 100. THEN BUY #3
    decided -> the admission gate computes cost = 100 * 40 = 4_000 > 2_000
    available -> ``reserve()`` raises InsufficientFundsError -> the order is
    PENDING->REJECTED (triggered_by="cash_reservation") and PERSISTED; NOTHING is
    emitted and — CASH-01 — NO RESERVATION is committed to the ledger. available
    stays 2_000, balance stays 2_000.
  * bar4 (01-05): SELL decided (exit_fraction defaults to 1 -> full exit of the 80
    units). No reservation (SELLs don't reserve — D-03).
  * bar5 (01-06): SELL FILLS @ next-open 100 -> closes all 80 units. total_sold =
    80 * 100 = 8_000 credited: balance 2_000 -> 10_000.

Resulting SINGLE closed round-trip trade (the two adds aggregate into ONE position;
the over-cash add NEVER executed so it contributes NOTHING):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03 (BUY #1's fill bar — the position open)
  * exit_date  = 2020-01-06 (SELL's fill bar)
  * avg_bought = 100, avg_sold = 100, net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 8_000 - 8_000 = 0.00 (flat prices).

Final portfolio: final_cash = final_equity = 10_000.00 (round-trip at flat 100 is
PnL-neutral), trade_count = 1.

Cash-ledger snapshot (``golden/cash_operations.csv`` — the CASH-01 + ADMIT-01 lens,
D-02). The DERIVED ``correlation`` collapses each raw UUIDv7 ``reference_id`` to a
stable ORDER-{n} ordinal in FIRST-APPEARANCE order so a RESERVATION matches its
RELEASE without leaking the id; ``operation_id`` / raw ``reference_id`` / wall-clock
``timestamp`` are EXCLUDED (determinism contract). The reserve/release lifecycle and
the fill settlement use DIFFERENT reference ids (the reservation is keyed by the
order id; the TRANSACTION_DEBIT/CREDIT is keyed by the transaction id —
cash_manager.py:226-276), so each gets its OWN ordinal. The frozen rows (sorted by
correlation, operation_type, amount):

    correlation  operation_type        amount    balance_before  balance_after
    ORDER-1      RELEASE_RESERVATION    4000.00   6000.00         6000.00   <- BUY#1 reservation released on fill
    ORDER-1      RESERVATION            4000.00  10000.00        10000.00   <- BUY#1 reserve commits at admission
    ORDER-2      TRANSACTION_DEBIT     -4000.00  10000.00         6000.00   <- BUY#1 fill debits the principal
    ORDER-3      RELEASE_RESERVATION    4000.00   2000.00         2000.00   <- BUY#2 reservation released on fill
    ORDER-3      RESERVATION            4000.00   6000.00         6000.00   <- BUY#2 reserve commits at admission
    ORDER-4      TRANSACTION_DEBIT     -4000.00   6000.00         2000.00   <- BUY#2 fill debits the principal
    ORDER-5      TRANSACTION_CREDIT     8000.00   2000.00        10000.00   <- SELL fill credits the 80-unit close

The LOAD-BEARING CASH-01 + ADMIT-01 facts:
  * ADMIT-01 — the TWO filled adds each show a RESERVATION (4_000) that COMMITS and
    is later RELEASED (RELEASE_RESERVATION 4_000) on the fill, plus the fill's signed
    TRANSACTION_DEBIT (-4_000) — proving the scale-in reserve/release lifecycle FIRED
    twice (a pyramid of two adds into one position).
  * CASH-01 — the over-cash THIRD add has NO row at all (no ORDER-* RESERVATION for
    it): the admission reserve raised ``InsufficientFundsError`` BEFORE recording any
    ledger entry, so the reservation NEVER COMMITTED and ``available_cash`` was left
    intact (balance stays 2_000 across the rejection). This is the cash-ledger
    no-commit lens, DISTINCT from SIZE-03's orders-snapshot REJECTED row (D-01).
  * the closing SELL credits the full 8_000 (TRANSACTION_CREDIT, +signed) restoring
    balance to 10_000 — the round-trip is PnL-neutral at flat 100.

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

# Date-keyed script (D-04): BUY #1 (entry), BUY #2 (scale-in add, ADMIT-01), BUY #3
# (over-cash add -> rejected, CASH-01), then a full-exit SELL to close the position
# so the trade log records the aggregated round-trip.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},   # BUY #1 — opens the position
    "2020-01-03": {"side": "BUY"},   # BUY #2 — successful scale-in add (ADMIT-01)
    "2020-01-04": {"side": "BUY"},   # BUY #3 — exhausts remaining cash -> REJECTED (CASH-01)
    "2020-01-05": {"side": "SELL"},  # full exit (exit_fraction defaults to 1)
}

# FixedQuantity so the cash math is exact and hand-derivable: 40 units @ flat 100 =
# 4_000 per add; the third add deterministically exceeds the remaining 2_000.
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
                                sizing_policy=_SIZING, allow_increase=True)],
    portfolios=[PortfolioSpec(user_id=1, name="scale_in_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the cash math is the only moving part.
)
