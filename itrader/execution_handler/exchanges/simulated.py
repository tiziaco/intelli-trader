from queue import Queue
from .base import AbstractExchange
from ..fee_model.zero_fee_model import ZeroFeeModel
from ..fee_model.percent_fee_model import PercentFeeModel
from itrader.events_handler.event import FillEvent, OrderEvent

from itrader import logger

class SimulatedExchange(AbstractExchange):
	"""
	The simulated execution handler converts all order 
	objects into their equivalent fill objects automatically
	without latency, slippage or fill-ratio issues. 
	
	It allows to cqlculqte the fees with different models.

	This allows a straightforward "first go" test of any strategy,
	before implementation with a more sophisticated execution
	handler.
	"""

	def __init__(self, global_queue: Queue, 
		fee_model = 'no_fee', 
		commission_pct = 0.007, slippage_pct = 0.0):
		"""
		Initialises the handler, setting the event queue
		as well as access to local pricing.

		Parameters:
		events_queue - The Queue of Event objects.
		"""
		self.global_queue = global_queue
		self.fee_model = self._initialize_fee_model(fee_model)
		self.commission_pct = commission_pct
		self.slippage_pct = slippage_pct

		logger.info('EXECUTION HANDLER: Simulated exchange => OK')


	def execute_order(self, event: OrderEvent):
		"""
		Converts OrderEvents into FillEvents "naively",
		i.e. without any latency, slippage or fill ratio problems.

		Parameters:
		event - An Event object with order information.
		"""

		# Set the exchange and calculate the trade commission
		commission = self.fee_model.calc_total_commission(event.quantity, event.price)

		# Create the FillEvent and place it in the events queue
		fill_event = FillEvent.new_fill('EXECUTED', commission, event)
		self.global_queue.put(fill_event)

		logger.info('EXECUTION HANDLER: Order executed: %s %s %s %s$', 
			fill_event.action, fill_event.ticker, fill_event.quantity, fill_event.price)

	def _initialize_fee_model(self, fee_model: str):
		if fee_model == 'percent':
			return PercentFeeModel(self.commission_pct, self.slippage_pct)
		elif fee_model == 'no_fee':
			return ZeroFeeModel()
		else:
			logger.warning('EXECUTION HANDLER: fee model %s not supported', fee_model)
			return