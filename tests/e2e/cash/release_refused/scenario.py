"""CASH-02 REFUSED: a reserved BUY refused by the exchange -> POSITIVE release on
the cash ledger (D-04 leaf 6, D-03).

The second of CASH-02's two POSITIVE-release leaves. A MARKET BUY passes the
synchronous admission cash-reservation gate (it reserves successfully — enough cash)
and is emitted to the exchange, but the exchange's pre-trade ``validate_order`` then
REFUSES it because its quantity exceeds a tiny ``max_order_size`` configured via
``spec.exchange``. The refusal arrives as a ``FillEvent(REFUSED)``, and the terminal
release finalizer (order_manager.py:257-273, ``should_release`` on
EXECUTED/CANCELLED/REFUSED) gives the reservation back — a POSITIVE
``RELEASE_RESERVATION`` op in the cash-ledger snapshot.

DETERMINISTIC trigger (D-03): the ``limits.max_order_size`` lever, set on
``spec.exchange`` — NOT the seeded ``simulate_failures`` RNG path
(simulated.py:138-151), which is deliberately avoided. ``validate_order``
(simulated.py:386-391) fails the quantity check ``event.quantity > _max_order_size``,
so a BUY of 40 units against ``max_order_size = 10`` is refused every run.

Why the cash-ledger LENS (D-02): proving the reservation was HELD (admission
reserved it) and then RELEASED (the REFUSED fill gave it back) — the explicit
``RESERVATION`` -> ``RELEASE_RESERVATION`` pair on the same derived order, not the
ambiguous "available_cash returns to full".

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen goldens MATCH
the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, ALL prices FLAT 100 so
the only moving part is the reserve/release cash math):

    bar  date         open   high   low    close
    0    2020-01-01   100    100    100    100
    1    2020-01-02   100    100    100    100   <- BUY decided (close=100)
    2    2020-01-03   100    100    100    100   <- (BUY refused at on_order; nothing rests)
    3    2020-01-04   100    100    100    100

Engine knobs: starting_cash = 10_000, timeframe = 1d, strategy = ``ScriptedEmitter``
(default ``order_type=MARKET``, ``allow_increase=False`` / ``max_positions=1``) with a
single BUY on 2020-01-02. ``sizing_policy = FixedQuantity(qty=Decimal("40"))`` so the
order quantity (40) deterministically exceeds the configured ``max_order_size = 10``
AND the reserve math is exact (40 @ decision-close 100 = 4_000 < 10_000 cash, so the
reservation SUCCEEDS first — the refusal must happen at the EXCHANGE, after a held
reservation, to exercise the terminal release).

``spec.exchange`` (NOT None — the D-03 REFUSED lever): an ``ExchangeConfig`` with
``limits.max_order_size = Decimal("10")`` (and ``min_order_size`` left at its small
default). The harness applies it post-construction, pre-run, re-deriving the cached
``_max_order_size`` the exchange's ``validate_order`` reads. IN-03: the seam
re-derives BOTH ``_min_order_size`` AND ``_max_order_size`` from ``spec.exchange``
(conftest:290-291) — this leaf relies on the default min (0.001) and only moves
``max_order_size``, but a future min-driven REFUSED leaf can lean on the same live
min cache. Fee/slippage stay at the
zero defaults so the cash math is exactly the principal — the refusal, not costs, is
the only moving part. ``supported_symbols`` is left untouched by the harness seam, so
BTCUSD stays admitted (PATTERNS A2).

Cash + reservation trail (reserve cost = decision-close 100 * 40 = 4_000):
  * bar1 (01-02): BUY decided. Admission reserves 4_000 (available 10_000 -> 6_000)
    and EMITS the order to the exchange. RESERVATION records
    balance_before == balance_after == 10_000 (a reservation moves only
    available_balance, not the ledger balance — cash_manager.py:365-416).
  * bar2 (01-03): the exchange processes the order at on_order: ``validate_order``
    sees quantity 40 > max_order_size 10 -> ``_emit_rejection`` ->
    ``FillEvent(REFUSED)`` (simulated.py:122-127, 166-173). The order NEVER rests in
    the matching book and NEVER fills. on_fill reconciles the mirror to REJECTED and
    the terminal release fires (order_manager.py:257-273): RELEASE_RESERVATION 4_000
    -> available_cash 6_000 -> 10_000 (intact again). RELEASE_RESERVATION likewise
    records balance_before == balance_after == 10_000 (idempotent pop_reservation,
    cash_manager.py:418-448 — the ledger balance never moved because nothing filled).
  * bars 2-3: no further signals; nothing else happens.

Lifecycle: ZERO positions ever open (the BUY was refused), ZERO trades close ->
``trades.csv`` is EMPTY, ``trade_count = 0``. final_cash = final_equity = 10_000.00
(the reservation was released, never committed to a fill).

Cash-ledger snapshot (``golden/cash_operations.csv`` — the CASH-02 REFUSED lens,
D-02). The derived ``correlation`` collapses the raw UUIDv7 ``reference_id`` to a
stable ORDER-{n:03d} ordinal; the reservation and its release are keyed by the SAME order
id, so they share ONE correlation ordinal. The frozen rows (sorted by correlation,
operation_type, amount):

    correlation  operation_type        amount    balance_before  balance_after
    ORDER-001    RELEASE_RESERVATION    4000.00   10000.00        10000.00   <- REFUSED fill releases
    ORDER-001    RESERVATION            4000.00   10000.00        10000.00   <- admission reserves before emit

The LOAD-BEARING CASH-02 REFUSED fact: the SAME ORDER-001 shows a RESERVATION (4_000)
that COMMITS at admission and is later RELEASED (RELEASE_RESERVATION 4_000, matching
amount, POSITIVE) by the exchange's deterministic ``max_order_size`` refusal —
proving the reservation was held through emission and the REFUSED fill actually FIRED
its release. There is NO TRANSACTION_DEBIT/CREDIT (the order never filled), and
available_cash returns intact.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.config.exchange import ExchangeConfig, ExchangeLimits
from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a single MARKET BUY decided 2020-01-02. The BUY reserves
# successfully (40 @ 100 = 4_000 < 10_000) then is REFUSED by the exchange's tiny
# max_order_size, exercising the terminal-release on REFUSED.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# FixedQuantity so the reserve math is exact AND the quantity (40) deterministically
# exceeds the configured max_order_size (10): 40 @ decision-close 100 = 4_000 reserve.
_SIZING = FixedQuantity(qty=Decimal("40"))

# The D-03 REFUSED lever: a tiny max_order_size on spec.exchange. validate_order's
# quantity check (event.quantity > _max_order_size) fails deterministically -> REFUSED.
# Fee/slippage stay at zero defaults so the cash math is exactly the principal.
_EXCHANGE = ExchangeConfig(limits=ExchangeLimits(max_order_size=Decimal("10")))

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
    portfolios=[PortfolioSpec(user_id=1, name="release_refused_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # NOT None — the deterministic max_order_size REFUSED lever (D-03).
)
