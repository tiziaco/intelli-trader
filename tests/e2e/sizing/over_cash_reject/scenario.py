"""SIZE-03: over-cash sizing -> audited insufficient-funds REJECTED (D-15).

The audited no-trade outcome for over-cash sizing. A BUY declaring a
``FixedQuantity`` whose notional EXCEEDS available cash is REJECTED at the
synchronous admission cash-reservation gate (``OrderManager`` admission path,
D-15 — anchored to the decision tag, not a drift-prone line range): the
BUY's ``reserve()`` raises ``InsufficientFundsError``, the primary order is
transitioned PENDING->REJECTED through the audited ``add_state_change`` path
(``triggered_by="cash_reservation"``) and PERSISTED — rejected orders never vanish
silently — and NOTHING is emitted to the exchange. No fill, no closed trade.

The ASSERTION is the final order-mirror state (REJECTED), so this leaf freezes the
OPT-IN ``golden/orders.csv`` (D-15 — the SAME opt-in orders-snapshot vehicle Phase 6
used for no-trade outcomes, e.g. ``matching/never_fill``) plus an EMPTY
``trades.csv`` and a ``summary.json`` with ``trade_count = 0``. The harness only
freezes ``orders.csv`` when a golden file is already present, so an EMPTY
``golden/orders.csv`` placeholder opts this leaf into the snapshot.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-15): the frozen ``golden/orders.csv`` shows EXACTLY ONE
row — role STANDALONE, BTCUSD, MARKET, BUY, status REJECTED, quantity 1000,
filled_quantity 0 — and ``golden/trades.csv`` is EMPTY (``trade_count = 0``).
Re-freeze ONLY via ``--freeze`` after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100)
    2    2020-01-03   100    105    99     100
    3    2020-01-04   100    105    99     100

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04):
a single MARKET BUY on the 2020-01-02 decision bar. NO SELL.
``sizing_policy = FixedQuantity(qty=Decimal("1000"))`` — a deliberately OVER-CASH
fixed quantity.

Sizing + the cash-reservation rejection (D-15 — the ``OrderManager`` admission
cash-reservation gate; anchored to the decision tag, not a drift-prone line range):
  * decision price = bar1 close = 100 (strategies_handler.py:141 stamps the price).
  * FixedQuantity is a pass-through (sizing_resolver.py:113-114): qty = 1000 — the
    sizing itself SUCCEEDS (FixedQuantity has no cash check; that is the admission
    gate's job, D-15).
  * the primary BUY is built sized at 1000 @ price 100; the admission gate computes
    cost = price * quantity + estimated_commission = 100 * 1000 + 0 = 100_000.00
    (zero estimated commission with exchange = None).
  * 100_000 > 10_000 available cash -> ``portfolio_handler.reserve(...)`` raises
    ``InsufficientFundsError`` -> the primary is transitioned PENDING->REJECTED
    (``triggered_by="cash_reservation"``) and stored; NOTHING is emitted (D-02).

Lifecycle: there is NO next-bar fill — the order never reaches the exchange. The
run completes cleanly over all four bars. The order mirror holds exactly ONE order
at status REJECTED; ZERO positions open; ZERO trades close.

Final order-mirror snapshot (``golden/orders.csv`` — the D-15 assertion). The
illustrative table below abbreviates to the load-bearing columns; the real golden
also pins the leading ``ticker`` (BTCUSD) and the trailing deterministic ``time``
identity column per ``ORDER_SNAPSHOT_COLUMNS`` (reporting/orders.py:39-49):

    role        order_type  action  status     price  quantity  filled_quantity
    STANDALONE  MARKET      BUY     REJECTED   100    1000      0

(role STANDALONE — no sl/tp declared, so the rejected primary has no bracket
children; status REJECTED via ``o.status.name``, GAP #1 — never ACTIVE.)

Final portfolio: final_cash = final_equity = 10_000.00 (untouched — the reserve
that would have debited cash RAISED instead), trade_count = 0, trades.csv EMPTY.

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
# over-cash quantity is rejected at the admission gate, so nothing ever fills.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
}

# SIZE-03 (D-15): an OVER-CASH FixedQuantity (Pitfall 1 string-path Decimal). 1000
# units @ the decision price 100 = 100_000 notional, 10x the 10_000 cash -> the
# admission cash-reservation gate raises InsufficientFundsError -> audited REJECTED.
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
    portfolios=[PortfolioSpec(user_id=1, name="size03_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage — sizing is the only moving part.
)
