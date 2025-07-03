from queue import Queue
from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.event import FillEvent, OrderEvent
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.logger import get_itrader_logger

class ExecutionHandler(AbstractExecutionHandler):
	"""
	Enhanced execution handler with comprehensive error handling and monitoring.
	
	Manages order execution across multiple exchanges with features including:
	- Detailed execution result tracking
	- Exchange health monitoring
	- Comprehensive error handling and logging
	- Support for both simulated and live exchanges
	- Connection management and validation
	
	This implementation provides a production-ready foundation for order execution
	while maintaining backward compatibility with existing systems.
	"""

	def __init__(self,
		global_queue: Queue, 
		fee_model='no_fee', 
		slippage_model='none',
		**model_kwargs):
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		fee_model: str
			Fee model to use ('no_fee', 'percent', 'maker_taker', 'tiered')
		slippage_model: str
			Slippage model to use ('none', 'linear', 'fixed')
		**model_kwargs
			Additional parameters for fee and slippage model initialization
		"""
		self.global_queue = global_queue
		self.fee_model = fee_model
		self.slippage_model = slippage_model
		self.model_kwargs = model_kwargs
		
		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="ExecutionHandler")
		
		# Initialize exchanges (requires logger)
		self.exchanges: dict[str, AbstractExchange] = self.init_exchanges()

		self.logger.info('Execution Handler initialized with fee model: %s, slippage model: %s',
			self.fee_model, self.slippage_model)


	def on_order(self, event: OrderEvent):
		"""
		Enhanced order execution with comprehensive error handling and monitoring.
		
		Executes orders through configured exchanges and handles results properly,
		including error logging and potential retry logic.

		Parameters
		----------
		event : OrderEvent
			Order event containing order details to execute
		"""
		try:
			# Get the configured exchange
			exchange = self.exchanges.get(event.exchange)
			if not exchange:
				self.logger.error('Unknown exchange specified: %s for order %s %s', 
								event.exchange, event.ticker, event.action)
				return
			
			# Execute order and get detailed result
			execution_result = exchange.execute_order(event)
			
			# Log execution outcome
			if execution_result.success:
				self.logger.info('Order executed successfully: %s %s %.4f @ $%.4f (ID: %s)',
								event.action, event.ticker, 
								execution_result.executed_quantity or event.quantity,
								execution_result.executed_price or event.price,
								execution_result.order_id or 'N/A')
				
				# Log additional execution details if available
				if execution_result.metadata:
					slippage = execution_result.metadata.get('slippage_applied', 0)
					if abs(slippage) > 0.01:  # Log significant slippage
						self.logger.info('Slippage applied: %.4f%% for %s', slippage, event.ticker)
			else:
				self.logger.warning('Order execution failed: %s %s - %s (%s)', 
								   event.ticker, event.action,
								   execution_result.error_message or 'Unknown error',
								   execution_result.error_code.value if execution_result.error_code else 'UNKNOWN')
				
				# Could implement retry logic here for certain error types
				# Could send error notifications or events to other system components
				
		except Exception as e:
			self.logger.error('Unexpected error in order execution for %s %s: %s', 
							 event.ticker, event.action, str(e), exc_info=True)

	
	def init_exchanges(self):
		"""
		Initialize configured exchanges with enhanced parameters.
		
		Creates exchange instances with proper configuration including
		fee models, slippage simulation, and failure testing capabilities.
		"""
		exchanges = {
			'simulated': SimulatedExchange(
				self.global_queue, 
				fee_model=self.fee_model,
				slippage_model=self.slippage_model,
				simulate_failures=False,  # Can be configured via environment
				failure_rate=0.01,
				**self.model_kwargs
			),
			'ccxt': None  # Placeholder for live exchange implementation
		}
		
		# Connect to exchanges that support it
		for exchange_name, exchange in exchanges.items():
			if exchange is not None:
				try:
					connection_result = exchange.connect()
					if connection_result.success:
						self.logger.info('Successfully connected to %s exchange', exchange_name)
					else:
						self.logger.warning('Failed to connect to %s exchange: %s', 
										   exchange_name, connection_result.error_message)
				except AttributeError:
					# Exchange doesn't support connection management (backward compatibility)
					self.logger.debug('Exchange %s does not support connection management', exchange_name)
		
		return exchanges

	def get_exchange_health(self, exchange_name: str = None) -> dict:
		"""
		Get health status for one or all exchanges.
		
		Parameters
		----------
		exchange_name : str, optional
			Name of specific exchange to check. If None, checks all exchanges.
			
		Returns
		-------
		dict
			Health status information for requested exchange(s)
		"""
		health_data = {}
		
		exchanges_to_check = [exchange_name] if exchange_name else self.exchanges.keys()
		
		for name in exchanges_to_check:
			exchange = self.exchanges.get(name)
			if exchange is not None:
				try:
					health_status = exchange.health_check()
					health_data[name] = {
						'connected': health_status.connected,
						'status': health_status.status.value,
						'orders_executed': health_status.orders_executed_today,
						'orders_failed': health_status.orders_failed_today,
						'error_rate': health_status.error_rate,
						'latency_ms': health_status.latency_ms,
						'last_error': health_status.last_error,
						'is_healthy': health_status.is_healthy
					}
				except AttributeError:
					# Exchange doesn't support health checks
					health_data[name] = {
						'connected': True,  # Assume connected if no health check
						'status': 'unknown',
						'message': 'Health monitoring not supported'
					}
			else:
				health_data[name] = {
					'connected': False,
					'status': 'not_configured',
					'message': 'Exchange not configured'
				}
		
		return health_data

	def validate_exchange_order(self, exchange_name: str, event: OrderEvent) -> dict:
		"""
		Validate an order against a specific exchange without executing it.
		
		Parameters
		----------
		exchange_name : str
			Name of the exchange to validate against
		event : OrderEvent
			Order event to validate
			
		Returns
		-------
		dict
			Validation result with details about any issues found
		"""
		exchange = self.exchanges.get(exchange_name)
		if not exchange:
			return {
				'valid': False,
				'error': f'Exchange {exchange_name} not found',
				'error_code': 'EXCHANGE_NOT_FOUND'
			}
		
		try:
			validation_result = exchange.validate_order(event)
			return {
				'valid': validation_result.is_valid,
				'error': validation_result.error_message,
				'error_code': validation_result.error_code.value if validation_result.error_code else None,
				'warnings': validation_result.warnings,
				'failed_checks': validation_result.failed_checks
			}
		except AttributeError:
			# Exchange doesn't support validation
			return {
				'valid': True,
				'message': 'Validation not supported, assuming valid'
			}