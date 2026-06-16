"""Liquidation forced-close mirror reconcile (LIQ-03) — 04-03.

The forced-close engine mints a REAL ``Order`` tagged
``OrderTriggerSource.LIQUIDATION``, registers it in the INJECTED ``order_storage``
(the ``set_order_storage`` write-seam), and emits a ``FillEvent(EXECUTED)`` on the
BAR route. ``ReconcileManager.on_fill`` then reconciles EXECUTED → FILLED through
the EXISTING path — NO new ``FillStatus`` (reuse ``EXECUTED``). Pitfall 4: if the
order is NOT in storage the reconcile early-returns and the mirror silently no-ops,
so registering the order is what makes LIQ-03 literally true.

Folder-derived ``unit`` marker (no decorator). No reference-engine import.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue
from typing import Any, List

import uuid_utils.compat as uuid_compat

from itrader.core.enums import FillStatus, OrderStatus, OrderTriggerSource
from itrader.events_handler.events import FillEvent
from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager
from itrader.order_handler.storage import InMemoryOrderStorage
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.position import Position
from itrader.portfolio_handler.transaction import Transaction, TransactionType


_TICKER = "LIQUSD"
_ENTRY = Decimal("100")
_SIZE = Decimal("200")
_LEVERAGE = Decimal("5")
_WB = _ENTRY * _SIZE / _LEVERAGE
_MMR = Decimal("0.01")
_LONG_LIQ = (_ENTRY - _WB / _SIZE) / (Decimal("1") - _MMR)


class _StubInstrument:
    def __init__(self, mmr: Decimal, fee_rate: Decimal) -> None:
        self.maintenance_margin_rate = mmr
        self.liquidation_fee_rate = fee_rate


class _StubUniverse:
    def __init__(self, instrument: _StubInstrument) -> None:
        self._instrument = instrument

    def instrument(self, symbol: str) -> _StubInstrument:
        return self._instrument


class _NullBrackets:
    def consume(self, order_id: Any) -> Any:
        return None


def _build() -> tuple[PortfolioHandler, InMemoryOrderStorage, ReconcileManager]:
    """A handler wired with a real order_storage + a ReconcileManager over it."""
    h = PortfolioHandler(Queue())
    h.set_universe(_StubUniverse(_StubInstrument(_MMR, Decimal("0.001"))))
    storage = InMemoryOrderStorage()
    h.set_order_storage(storage)
    reconcile = ReconcileManager(
        order_storage=storage,
        logger=h.logger,
        portfolio_handler=None,   # release() not needed — liquidation never reserves
        brackets=_NullBrackets(),
        bracket_manager=None,
        cancel_order=lambda *a, **k: None,
    )
    return h, storage, reconcile


def _open_long(h: PortfolioHandler) -> tuple[Any, Position]:
    pid = h.add_portfolio(user_id=1, name="liq", exchange="simulated", cash=1000000.0)
    portfolio: Portfolio = h.get_portfolio(pid)
    txn = Transaction(
        datetime(2024, 1, 1), TransactionType.BUY, _TICKER, _ENTRY, _SIZE, 0,
        portfolio.portfolio_id, id=1, fill_id=uuid_compat.uuid7(),
    )
    position = Position.open_position(txn)
    portfolio.position_manager._storage.set_position(_TICKER, position)
    portfolio.cash_manager.lock_margin(str(position.id), _WB)
    return pid, position


def _force_breach(h: PortfolioHandler, close: Decimal, bar_time: datetime) -> List[FillEvent]:
    from itrader.core.bar import Bar
    from itrader.events_handler.events import BarEvent

    bar = Bar(time=bar_time, open=close, high=close, low=close, close=close,
              volume=Decimal("1"))
    h.update_portfolios_market_value(BarEvent(time=bar_time, bars={_TICKER: bar}))
    fills: List[FillEvent] = []
    while True:
        try:
            ev = h.global_queue.get_nowait()
        except Exception:
            break
        if isinstance(ev, FillEvent):
            fills.append(ev)
    return fills


def test_set_order_storage_seam_shares_the_mirror():
    """LIQ-03: PortfolioHandler.set_order_storage exists and after injection the
    portfolio side writes the forced-close Order into the SAME store the
    ReconcileManager queries."""
    h, storage, _ = _build()
    _open_long(h)

    fills = _force_breach(h, Decimal("70"), datetime(2024, 2, 1))
    assert len(fills) == 1
    fill = fills[0]
    # The forced-close order is in the SAME store keyed by fill.order_id.
    order = storage.get_order_by_id(fill.order_id, fill.portfolio_id)
    assert order is not None
    assert order.action.name == "SELL"           # opposite side to close a long
    assert order.quantity == _SIZE
    # Tagged LIQUIDATION (audit-distinct from a strategy-driven close).
    sources = [sc.triggered_by for sc in order.state_changes]
    assert OrderTriggerSource.LIQUIDATION in sources


def test_liquidation_reconcile_executed_to_filled():
    """LIQ-03: the forced-close fill reconciles EXECUTED → FILLED in order_storage."""
    h, storage, reconcile = _build()
    _open_long(h)

    fills = _force_breach(h, Decimal("70"), datetime(2024, 2, 1))
    fill = fills[0]

    # Before reconcile: registered, still PENDING.
    pre = storage.get_order_by_id(fill.order_id, fill.portfolio_id)
    assert pre.status == OrderStatus.PENDING

    reconcile.on_fill(fill)

    # AFTER the fill is consumed: the mirror REACHED FILLED (not merely emitted).
    post = storage.get_order_by_id(fill.order_id, fill.portfolio_id)
    assert post.status == OrderStatus.FILLED


def test_liquidation_trigger_source():
    """LIQ-03: the minted order carries OrderTriggerSource.LIQUIDATION."""
    h, storage, _ = _build()
    _open_long(h)
    fills = _force_breach(h, Decimal("70"), datetime(2024, 2, 1))
    order = storage.get_order_by_id(fills[0].order_id, fills[0].portfolio_id)
    assert any(sc.triggered_by == OrderTriggerSource.LIQUIDATION
               for sc in order.state_changes)


def test_no_new_fill_status():
    """LIQ-03 (LOCKED): liquidation introduces NO new FillStatus — rides EXECUTED."""
    members = {m.name for m in FillStatus}
    # The canonical set before liquidation — no LIQUIDATION/FORCED member.
    assert "LIQUIDATION" not in members
    assert "FORCED_CLOSE" not in members
    h, storage, _ = _build()
    _open_long(h)
    fill = _force_breach(h, Decimal("70"), datetime(2024, 2, 1))[0]
    assert fill.status == FillStatus.EXECUTED


def test_unregistered_order_no_ops_mirror():
    """LIQ-03 (Pitfall 4 guard): a fill for an order NOT in storage silently
    no-ops the reconcile (does not raise / corrupt state)."""
    h, storage, reconcile = _build()
    _, position = _open_long(h)

    # Build a fill referencing an order_id that was never registered.
    from itrader.core.ids import OrderId, StrategyId
    from itrader.events_handler.events import OrderEvent
    from itrader.order_handler.order import Order

    portfolio = h.get_portfolio(h.active_portfolio_ids()[0])
    phantom = Order(
        time=datetime(2024, 2, 1),
        type=__import__("itrader.core.enums", fromlist=["OrderType"]).OrderType.MARKET,
        status=OrderStatus.PENDING,
        ticker=_TICKER,
        action=__import__("itrader.core.enums", fromlist=["Side"]).Side.SELL,
        price=_ENTRY,
        quantity=_SIZE,
        exchange="simulated",
        strategy_id=StrategyId(uuid_compat.uuid7()),
        portfolio_id=portfolio.portfolio_id,
    )
    # Deliberately do NOT add to storage.
    order_event = OrderEvent.new_order_event(phantom)
    fill = FillEvent.new_fill(
        "EXECUTED", order_event, price=_LONG_LIQ, quantity=_SIZE,
        commission=Decimal("0"), time=datetime(2024, 2, 1))

    out = reconcile.on_fill(fill)   # must not raise
    assert out == []
    assert storage.get_order_by_id(fill.order_id, fill.portfolio_id) is None
