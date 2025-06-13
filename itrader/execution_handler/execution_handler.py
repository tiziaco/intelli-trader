from queue import Queue
from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.event import FillEvent, OrderEvent
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.logger import get_itrader_logger

class ExecutionHandler(AbstractExecutionHandler):
	"""
	The simulated execution handler converts all order 
	objects into their equivalent fill objects automatically
	without latency, slippage or fill-ratio issues. 
	
	It allows to cqlculqte the fees with different models.

	This allows a straightforward "first go" test of any strategy,
	before implementation with a more sophisticated execution
	handler.
	"""

	def __init__(self,
		global_queue: Queue, 
		fee_model = 'no_fee', 
		commission_pct = 0.007, slippage_pct = 0.0):
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		"""
		self.global_queue = global_queue
		self.fee_model = fee_model
		self.commission_pct = commission_pct
		self.slippage_pct = slippage_pct
		self.exchanges: dict[str, AbstractExchange] = self.init_exchanges()

		self.logger = get_itrader_logger().bind(component="ExecutionHandler")
		self.logger.info('Execution Handler initialized with fee model: %s, commission: %.4f%%, slippage: %.4f%%',
			self.fee_model,
			self.commission_pct * 100,
			self.slippage_pct * 100
		)


	def on_order(self, event: OrderEvent):
		"""
		Converts OrderEvents into FillEvents "naively",
		i.e. without any latency, slippage or fill ratio problems.

		Parameters:
		event - An Event object with order information.
		"""

		# Set the exchange
		exchange = self.exchanges.get(event.exchange)
		# Create the FillEvent and place it in the events queue
		exchange.execute_order(event)

	
	def init_exchanges(self):
		exchanges = {
			'simulated': SimulatedExchange(
				self.global_queue, 
				self.fee_model, self.commission_pct, self.slippage_pct),
			'ccxt' : None
		}
		return exchanges