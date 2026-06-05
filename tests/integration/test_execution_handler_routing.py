import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.event import OrderEvent, BarEvent, FillStatus
from itrader.core.enums import OrderType, OrderCommand


class TestExecutionHandlerRouting(unittest.TestCase):
	def setUp(self):
		self.queue = Queue()
		self.handler = ExecutionHandler(self.queue)
		exchange = self.handler.exchanges['simulated']
		exchange.connect()
		exchange.update_config(supported_symbols={'BTCUSDT'})

	def _oe(self, order_type, action='BUY', price=40.0, order_id=1):
		return OrderEvent(
			time=datetime(2024, 1, 1), ticker='BTCUSDT', action=action, price=price,
			quantity=1.0, exchange='simulated', strategy_id=1, portfolio_id=1,
			order_type=order_type, order_id=order_id, command=OrderCommand.NEW)

	def test_market_order_routed_and_filled(self):
		self.handler.on_order(self._oe(OrderType.MARKET))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, FillStatus.EXECUTED)

	def test_market_data_routed_to_exchange(self):
		self.handler.on_order(self._oe(OrderType.STOP, action='SELL', price=30.0, order_id=2))
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [35], 'high': [36], 'low': [20], 'close': [25], 'volume': [1]})}
		self.handler.on_market_data(BarEvent(time=datetime(2024, 1, 1), bars=bars))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_id, 2)
