"""SIG-03 (D-03) — the admission Position snapshot is threaded ONCE.

`process_signal` captures the per-ticker position snapshot a single time at the
top (before the step-0 direction gate) and threads it into
`_enforce_direction_admission`, `_enforce_position_admission`, and
`_resolve_signal_quantity`. The three per-method `get_position()` calls
(previously at lines 404 / 484 / 583) collapse to that one read.

Byte-exact under the single-writer backtest contract: nothing mutates the
position between those sites within one `process_signal` (the reserve touches
cash only), so one snapshot is value-identical to three re-fetches. This test
pins the call count (one), and the existing admission-rules suite + the oracle
pin the unchanged behavior.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import SignalEvent
from itrader.core.enums import OrderType, Side
from itrader.core.sizing import FractionOfCash, TradingDirection


def _unsized_buy_signal(portfolio_id):
    """An unsized LONG_ONLY BUY first-entry — it traverses all three admission
    sites (direction gate, position gate, sizing resolution), so the
    snapshot-threading collapse is observable as a get_position call count."""
    return SignalEvent(
        time=datetime(2024, 1, 1),
        order_type=OrderType.MARKET,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=40.0,
        quantity=None,
        stop_loss=0.0,
        take_profit=0.0,
        strategy_id=1,
        portfolio_id=portfolio_id,
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
        max_positions=1,
    )


def test_position_snapshot_captured_once_per_process_signal():
    queue = Queue()
    ptf_handler = PortfolioHandler(queue)
    storage = OrderStorageFactory.create("test")
    order_handler = OrderHandler(queue, ptf_handler, storage)
    portfolio_id = ptf_handler.add_portfolio("test_ptf", "default", 10000)

    admission = order_handler.order_manager.admission_manager
    # Scope the count to the admission gates/sizing only — the validator runs its
    # own (out-of-scope) get_position reads at order_validator.py:398/457. Disable
    # it so this test isolates the admission_manager's three sites (404/484/583).
    admission.order_validator = None

    # Spy on the read-model get_position: count the crossings within one signal.
    calls = {"n": 0}
    real_get_position = admission.portfolio_handler.get_position

    def _counting_get_position(*args, **kwargs):
        calls["n"] += 1
        return real_get_position(*args, **kwargs)

    admission.portfolio_handler.get_position = _counting_get_position  # type: ignore[method-assign]

    admission.process_signal(_unsized_buy_signal(portfolio_id))

    # SIG-03: ONE crossing — the triple admission get_position() is a single
    # threaded snapshot (direction gate / position gate / sizing resolution).
    assert calls["n"] == 1
