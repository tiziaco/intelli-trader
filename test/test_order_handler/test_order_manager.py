"""
Test suite for OrderManager - Internal order orchestration engine.

Tests the OrderManager's functionality including:
- Market-driven order processing
- Stop/Limit order trigger evaluation
- Market order execution timing
- Order fill processing
- State management and event generation
"""

import pytest
from datetime import datetime
from unittest.mock import Mock
import pandas as pd

from itrader.order_handler.order_manager import OrderManager
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.events_handler.event import BarEvent, OrderEvent


class TestOrderManager:
    """Test OrderManager functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.order_storage = InMemoryOrderStorage()
        self.logger = Mock()
        self.order_handler_ref = Mock()
        
        # Create OrderManager instances for different execution modes
        self.order_manager_immediate = OrderManager(
            self.order_storage, 
            self.logger, 
            self.order_handler_ref, 
            market_execution="immediate"
        )
        
        self.order_manager_next_bar = OrderManager(
            self.order_storage, 
            self.logger, 
            self.order_handler_ref, 
            market_execution="next_bar"
        )
        
        self.base_time = datetime.now()

    def create_test_order(self, **kwargs) -> Order:
        """Create a test order with default values."""
        defaults = {
            'time': self.base_time,
            'type': OrderType.MARKET,
            'status': OrderStatus.PENDING,
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'exchange': 'NYSE',
            'strategy_id': 1,
            'portfolio_id': 1
        }
        defaults.update(kwargs)
        return Order(**defaults)

    def create_test_bar_event(self, ticker='AAPL', **kwargs) -> BarEvent:
        """Create a test bar event."""
        defaults = {
            'open': 150.0,
            'high': 155.0,
            'low': 145.0,
            'close': 152.0,
            'volume': 1000000
        }
        defaults.update(kwargs)
        
        # Create DataFrame-like structure for bar data
        bar_data = {
            ticker: pd.DataFrame([defaults])
        }
        
        return BarEvent(
            time=self.base_time,
            bars=bar_data
        )

    def test_order_manager_initialization(self):
        """Test OrderManager initialization."""
        assert self.order_manager_immediate.market_execution == "immediate"
        assert self.order_manager_next_bar.market_execution == "next_bar"
        assert self.order_manager_immediate.order_storage == self.order_storage
        assert self.order_manager_immediate.logger == self.logger


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


import unittest

class TestOrderManagerBracketEmission(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		from itrader.events_handler.event import SignalEvent
		from itrader.core.enums import OrderType
		self.SignalEvent = SignalEvent
		self.OrderType = OrderType
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _signal(self, stop_loss=0.0, take_profit=0.0):
		import datetime as _dt
		return self.SignalEvent(
			time=_dt.datetime(2024, 1, 1), order_type='MARKET',
			ticker='BTCUSDT', action='BUY', price=40.0, quantity=1.0,
			stop_loss=stop_loss, take_profit=take_profit, strategy_id=1,
			portfolio_id=self.portfolio_id, strategy_setting={})

	def test_bracket_legs_emitted_and_linked(self):
		self.handler.on_signal(self._signal(stop_loss=30.0, take_profit=55.0))
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if getattr(e, 'order_type', None) is not None
		                and e.type.name == 'ORDER']
		types = sorted(e.order_type.name for e in order_events)
		self.assertEqual(types, ['LIMIT', 'MARKET', 'STOP'])
		primary = next(e for e in order_events if e.order_type == self.OrderType.MARKET)
		children = [e for e in order_events if e.order_type != self.OrderType.MARKET]
		for child in children:
			self.assertEqual(child.parent_order_id, primary.order_id)


class TestOrderManagerCommands(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _rest_a_stop(self):
		import datetime as _dt
		from itrader.order_handler.order import Order
		order = Order.new_stop_order(
			time=_dt.datetime(2024, 1, 1), ticker='BTCUSDT',
			action='SELL', price=30.0, quantity=1.0, exchange='default',
			strategy_id=1, portfolio_id=self.portfolio_id)
		self.storage.add_order(order)
		return order

	def test_cancel_emits_cancel_command(self):
		from itrader.core.enums import OrderCommand
		order = self._rest_a_stop()
		ok = self.handler.cancel_order(order.id, self.portfolio_id)
		self.assertTrue(ok)
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if e.type.name == 'ORDER']
		self.assertEqual(len(order_events), 1)
		self.assertIs(order_events[0].command, OrderCommand.CANCEL)
		self.assertEqual(order_events[0].order_id, order.id)

	def test_modify_emits_modify_command(self):
		from itrader.core.enums import OrderCommand
		order = self._rest_a_stop()
		ok = self.handler.modify_order(order.id, new_price=28.0, portfolio_id=self.portfolio_id)
		self.assertTrue(ok)
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if e.type.name == 'ORDER']
		self.assertEqual(len(order_events), 1)
		self.assertIs(order_events[0].command, OrderCommand.MODIFY)


class TestOrderManagerReconciliation(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _rest_a_stop(self):
		import datetime as _dt
		from itrader.order_handler.order import Order
		order = Order.new_stop_order(
			time=_dt.datetime(2024, 1, 1), ticker='BTCUSDT',
			action='SELL', price=30.0, quantity=1.0, exchange='default',
			strategy_id=1, portfolio_id=self.portfolio_id)
		self.storage.add_order(order)
		return order

	def _fill(self, order, status):
		import datetime as _dt
		from itrader.events_handler.event import OrderEvent, FillEvent
		from itrader.core.enums import OrderType
		oe = OrderEvent(
			time=_dt.datetime(2024, 1, 1), ticker=order.ticker, action=order.action,
			price=order.price, quantity=order.quantity, exchange=order.exchange,
			strategy_id=order.strategy_id, portfolio_id=order.portfolio_id,
			order_type=OrderType.STOP, order_id=order.id)
		return FillEvent.new_fill(status, 0.0, oe)

	def test_executed_fill_marks_order_filled(self):
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'EXECUTED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.FILLED)

	def test_cancelled_fill_marks_order_cancelled(self):
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'CANCELLED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.CANCELLED)

	def test_unknown_order_id_is_safe(self):
		# A fill for an order not in storage must not raise.
		order = self._rest_a_stop()
		fake = self._fill(order, 'EXECUTED')
		fake.order_id = 999999
		self.handler.on_fill(fake)  # should be a no-op, no exception
		self.assertIsNone(self.storage.get_order_by_id(999999, self.portfolio_id))
		# The real order remains untouched (still active/PENDING).
		from itrader.core.enums import OrderStatus
		self.assertEqual(self.storage.get_order_by_id(order.id, self.portfolio_id).status,
		                 OrderStatus.PENDING)

	def test_refused_fill_leaves_order_active(self):
		# A REFUSED fill must NOT deactivate or change the order — it stays pending.
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'REFUSED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.PENDING)
		active_ids = [o.id for o in self.storage.get_active_orders(self.portfolio_id)]
		self.assertIn(order.id, active_ids)
