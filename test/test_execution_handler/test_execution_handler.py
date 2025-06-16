import unittest
from datetime import datetime, UTC
from queue import Queue

from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.event import FillEvent, OrderEvent

class TestExecutionHandlerUpdates(unittest.TestCase):
	"""
	Test the execution handler module.
	"""

	@classmethod
	def setUpClass(cls):
		"""
		Set up the execution handler instance.
		"""
		cls.queue = Queue()
		cls.execution_handler = ExecutionHandler(cls.queue)

	def setUp(self):
		"""
		Set up an order event that will be processed by the 
		execution handler.
		"""
		self.order_event = OrderEvent(
			datetime.now(UTC),
			'BTCUSDT',
			'BUY',
			100,
			1,
			'simulated',
			1, 1
		)

	def test_execution_handler_initialization(self):
		self.assertIsInstance(self.execution_handler, ExecutionHandler)
	
	def test_on_order(self):
		# Generate a portfolio update event and process it from the order handler
		self.execution_handler.on_order(self.order_event)
		# Retrive fill event from the queue
		fill_event: FillEvent = self.queue.get(False)
		# Retrive the updated portfolios dict
		self.assertIsInstance(fill_event, FillEvent)
		self.assertEqual(fill_event.action, 'BUY')


if __name__ == "__main__":
	unittest.main()