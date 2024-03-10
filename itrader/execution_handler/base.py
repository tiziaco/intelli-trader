from abc import ABCMeta, abstractmethod
from itrader.events_handler.event import OrderEvent

class AbstractExecutionHandler(object):
	"""
	The ExecutionHandler abstract class handles the interaction
	between a set of order objects generated by a PortfolioHandler
	and the set of Fill objects that actually occur in the
	market.

	The handlers can be used to subclass simulated brokerages
	or live brokerages, with identical interfaces. This allows
	strategies to be backtested in a very similar manner to the
	live trading engine.

	ExecutionHandler can link to an optional Compliance component
	for simple record-keeping, which will keep track of all executed
	orders.
	"""

	__metaclass__ = ABCMeta

	@abstractmethod
	def on_order(self, event: OrderEvent):
		"""
		Takes an OrderEvent and executes it, producing
		a FillEvent that gets placed onto the events queue.

		Parameters:
		event - Contains an Event object with order information.
		"""
		raise NotImplementedError("Should implement on_order()")
