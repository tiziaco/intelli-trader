from .base import AbstractExchange
from itrader.events_handler.event import FillEvent, OrderEvent

from itrader import logger

class CcxtExchange(AbstractExchange):
	"""
	The CCXT exechange handler execute real order all order 
	objects into their equivalent fill objects automatically
	without latency, slippage or fill-ratio issues. 
	
	It allows to cqlculqte the fees with different models.
	"""

	def __init__(self, global_queue):
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		"""
		self.global_queue = global_queue


	def execute_order(self, event: OrderEvent):
		"""
		Converts OrderEvents into FillEvents "naively",
		i.e. without any latency, slippage or fill ratio problems.

		Parameters:
		event - An Event object with order information.
		"""
		return