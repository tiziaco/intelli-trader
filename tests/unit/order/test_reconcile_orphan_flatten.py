"""Fix B regression tests (OVERSELL-B): an EXECUTED fill that FLATTENS a
portfolio+ticker position must cancel that portfolio+ticker's resting bracket
children (the orphaned SL/TP the matching engine's OCO only cancels for its own
sibling).

Root cause: `.planning/debug/spot-long-only-oversell.md` — a bracketed
LONG_ONLY strategy has TWO exit channels (a resting OCO bracket SL/TP + a
discretionary market SELL). The discretionary SELL flattens the long but does
NOT cancel the orphaned resting children (OCO only cancels a bracket's own
sibling). The orphaned child fires later as a SELL fill against a flat
portfolio, bypassing admission and seeding the silent over-sell.

This is the SEED fix, distinct from the existing WR-05 parent-terminal-without-
fill case (a SEPARATE order's EXECUTED fill flattens the position here). It is
oracle-dark (SMA_MACD declares no brackets).

The fakes mirror tests/unit/order/test_reconcile_manager.py, EXTENDED with
.ticker, get_position, and get_active_orders. Folder-derived ``unit`` marker.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager
from itrader.core.enums import FillStatus, PositionSide
from itrader.core.portfolio_read_model import PositionView


# --- fakes ------------------------------------------------------------------


class _FakeOrder:
    """Minimal order mirror exposing only what on_fill touches."""

    def __init__(self, order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT"):
        self.id = order_id
        self.portfolio_id = portfolio_id
        self.ticker = ticker
        self.child_order_ids = []
        self.filled_quantity = Decimal("0")

    def add_fill(self, quantity, price, time, reason="exchange fill"):
        self.filled_quantity += quantity
        return True

    def cancel_order(self, reason="exchange cancellation"):
        return True

    def reject_order(self, reason):
        return True


class _FakeChild:
    """A resting bracket child (or non-bracket order) as get_active_orders sees it."""

    def __init__(self, child_id, portfolio_id, ticker, parent_order_id):
        self.id = child_id
        self.portfolio_id = portfolio_id
        self.ticker = ticker
        self.parent_order_id = parent_order_id
        self.child_order_ids = []
        self.filled_quantity = Decimal("0")

    def is_active(self):
        return True


class _FakeStorage:
    """Returns the just-filled order plus a fixed active-orders list."""

    def __init__(self, order, active_orders=None):
        self._order = order
        self._active_orders = active_orders or []
        self.update_calls = 0

    def get_order_by_id(self, order_id, portfolio_id=None):
        return self._order

    def update_order(self, order):
        self.update_calls += 1
        return True

    def get_active_orders(self, portfolio_id):
        return list(self._active_orders)


class _FakeBrackets:
    """consume() returns None — no fill-anchored children for the filled order."""

    def consume(self, order_id):
        return None


class _ReadModelPortfolio:
    """Records release() and answers get_position with a fixed view (flat=None)."""

    def __init__(self, position_view=None):
        self.release_calls = []
        self._position_view = position_view

    def release(self, portfolio_id, order_id):
        self.release_calls.append((portfolio_id, order_id))

    def get_position(self, portfolio_id, ticker):
        return self._position_view


class _FakeFill:
    """Minimal fill carrying only the attributes on_fill reads (+ ticker)."""

    def __init__(self, status, order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT"):
        self.status = status
        self.order_id = order_id
        self.portfolio_id = portfolio_id
        self.ticker = ticker
        self.quantity = Decimal("1")
        self.price = Decimal("100")
        self.time = None


def _ok_cancel_result():
    """A cancel_order return with .success=True and a sentinel CANCEL event list."""
    result = Mock()
    result.success = True
    result.order_events = ["CANCEL-EVENT"]
    return result


def _make_manager(order, portfolio, storage, cancel_order):
    return ReconcileManager(
        order_storage=storage,
        logger=Mock(),
        portfolio_handler=portfolio,
        brackets=_FakeBrackets(),
        bracket_manager=Mock(),
        cancel_order=cancel_order,
    )


# --- positive: flatten cancels this portfolio+ticker bracket children --------


def test_flatten_by_fill_cancels_resting_bracket_children():
    """An EXECUTED fill that leaves (P-1, BTCUSDT) FLAT (get_position -> None)
    cancels each resting BTCUSDT bracket child of P-1 (parent_order_id is not
    None, id != the filled order). The returned CANCEL events join on_fill's
    output. RED today (no flatten-cancel), GREEN after Task 4."""
    order = _FakeOrder(order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT")
    btc_child = _FakeChild("C-BTC", "P-1", "BTCUSDT", parent_order_id="PARENT-1")
    eth_child = _FakeChild("C-ETH", "P-1", "ETHUSDT", parent_order_id="PARENT-2")
    non_bracket = _FakeChild("O-NB", "P-1", "BTCUSDT", parent_order_id=None)
    storage = _FakeStorage(order, active_orders=[btc_child, eth_child, non_bracket])
    portfolio = _ReadModelPortfolio(position_view=None)  # FLAT
    cancel_order = Mock(return_value=_ok_cancel_result())
    manager = _make_manager(order, portfolio, storage, cancel_order)

    out = manager.on_fill(_FakeFill(FillStatus.EXECUTED, order_id="O-1",
                                    portfolio_id="P-1", ticker="BTCUSDT"))

    # The BTCUSDT bracket child was cancelled.
    cancelled_ids = [c.args[0] for c in cancel_order.call_args_list]
    assert "C-BTC" in cancelled_ids
    # Scope: ETHUSDT child and the non-bracket order are NOT cancelled.
    assert "C-ETH" not in cancelled_ids
    assert "O-NB" not in cancelled_ids
    # The filled order itself is never cancelled.
    assert "O-1" not in cancelled_ids
    # The CANCEL events were collected into on_fill's return.
    assert "CANCEL-EVENT" in out


def test_flatten_does_not_cancel_other_ticker_children():
    """A resting bracket child for a DIFFERENT ticker (ETHUSDT) in the same
    portfolio is NOT cancelled by a BTCUSDT flatten (scope precise)."""
    order = _FakeOrder(order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT")
    eth_child = _FakeChild("C-ETH", "P-1", "ETHUSDT", parent_order_id="PARENT-2")
    storage = _FakeStorage(order, active_orders=[eth_child])
    portfolio = _ReadModelPortfolio(position_view=None)  # BTCUSDT flat
    cancel_order = Mock(return_value=_ok_cancel_result())
    manager = _make_manager(order, portfolio, storage, cancel_order)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, ticker="BTCUSDT"))

    cancel_order.assert_not_called()


def test_flatten_does_not_cancel_when_position_still_open():
    """An EXECUTED fill where get_position returns a non-None view (still open /
    partial) cancels NOTHING."""
    order = _FakeOrder(order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT")
    btc_child = _FakeChild("C-BTC", "P-1", "BTCUSDT", parent_order_id="PARENT-1")
    storage = _FakeStorage(order, active_orders=[btc_child])
    open_view = PositionView(
        ticker="BTCUSDT", side=PositionSide.LONG,
        net_quantity=Decimal("1"), avg_price=Decimal("100"),
    )
    portfolio = _ReadModelPortfolio(position_view=open_view)  # still OPEN
    cancel_order = Mock(return_value=_ok_cancel_result())
    manager = _make_manager(order, portfolio, storage, cancel_order)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, ticker="BTCUSDT"))

    cancel_order.assert_not_called()


def test_non_executed_fill_does_not_trigger_flatten_cancel():
    """A CANCELLED fill does NOT invoke the flatten-cancel path (it is the
    existing WR-05 case, kept distinct). The filled order here has no children,
    so WR-05 cancels nothing either — proving flatten-cancel is EXECUTED-only."""
    order = _FakeOrder(order_id="O-1", portfolio_id="P-1", ticker="BTCUSDT")
    btc_child = _FakeChild("C-BTC", "P-1", "BTCUSDT", parent_order_id="PARENT-1")
    storage = _FakeStorage(order, active_orders=[btc_child])
    portfolio = _ReadModelPortfolio(position_view=None)  # flat, but fill not EXECUTED
    cancel_order = Mock(return_value=_ok_cancel_result())
    manager = _make_manager(order, portfolio, storage, cancel_order)

    manager.on_fill(_FakeFill(FillStatus.CANCELLED, ticker="BTCUSDT"))

    cancel_order.assert_not_called()
