from queue import Queue
from datetime import datetime
from typing import Dict, Any
import random
import time

from .base import AbstractExchange
from ..fee_model.zero_fee_model import ZeroFeeModel
from ..fee_model.percent_fee_model import PercentFeeModel
from ..fee_model.maker_taker_fee_model import MakerTakerFeeModel
from ..fee_model.tiered_fee_model import TieredFeeModel
from ..slippage_model.zero_slippage_model import ZeroSlippageModel
from ..slippage_model.linear_slippage_model import LinearSlippageModel
from ..slippage_model.fixed_slippage_model import FixedSlippageModel
from ..result_objects import ExecutionResult, ConnectionResult, HealthStatus, ValidationResult
from itrader.core.enums.execution import ExecutionStatus, ExecutionErrorCode, ExchangeConnectionStatus, ExchangeType
from itrader.core.exceptions.execution import (
    ExecutionError, 
    InvalidSymbolExecutionError, 
    InsufficientFundsExecutionError,
    ExchangeStateError
)
from itrader.events_handler.event import FillEvent, OrderEvent
from itrader.logger import get_itrader_logger

class SimulatedExchange(AbstractExchange):
	"""
	Enhanced simulated exchange with comprehensive error handling,
	validation, monitoring capabilities, and production-ready features.
	
	Provides realistic simulation of exchange behavior including:
	- Order validation and rejection
	- Slippage simulation
	- Connection management
	- Health monitoring
	- Configurable failure simulation
	"""

	def __init__(self, global_queue: Queue, 
		fee_model='no_fee', 
		slippage_model='none',
		simulate_failures=False,
		failure_rate=0.01,
		**kwargs):
		"""
		Initialize the enhanced simulated exchange.
		
		Parameters
		-----------
		global_queue : Queue
			Event queue for the trading system
		fee_model : str
			Fee model to use ('no_fee', 'percent', 'maker_taker', 'tiered')
		slippage_model : str
			Slippage model to use ('none', 'linear', 'fixed')
		simulate_failures : bool
			Whether to simulate random execution failures
		failure_rate : float
			Rate of simulated failures (0.0 to 1.0)
		**kwargs
			Additional parameters for fee and slippage model initialization
		"""
		self.global_queue = global_queue
		
		# Separate kwargs for fee and slippage models
		fee_kwargs = {k: v for k, v in kwargs.items() if k.startswith('fee_')}
		slippage_kwargs = {k: v for k, v in kwargs.items() if k.startswith('slippage_')}
		
		self.fee_model = self._initialize_fee_model(fee_model, **fee_kwargs)
		self.slippage_model = self._initialize_slippage_model(slippage_model, **slippage_kwargs)
		self.simulate_failures = simulate_failures
		self.failure_rate = failure_rate
		
		# Connection state management
		self._connected = False
		self._connection_time = None
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED
		
		# Health and performance monitoring
		self._last_ping = None
		self._orders_executed = 0
		self._orders_failed = 0
		self._last_error = None
		self._last_error_time = None
		self._total_volume = 0.0
		self._startup_time = datetime.now()
		
		# Exchange configuration
		self._supported_symbols = {'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'}
		self._min_order_size = 0.001
		self._max_order_size = 1000000.0
		self._exchange_name = "SimulatedExchange"
		
		self.logger = get_itrader_logger().bind(component="SimulatedExchange")
		self.logger.info('Enhanced Simulated Exchange initialized with %d supported symbols', 
						len(self._supported_symbols))

	def execute_order(self, event: OrderEvent) -> ExecutionResult:
		"""
		Execute order with comprehensive error handling and validation.
		
		Simulates realistic exchange behavior including validation,
		slippage, failures, and detailed execution results.
		"""
		execution_time = datetime.now()
		
		try:
			# Pre-execution validation
			validation_result = self.validate_order(event)
			if not validation_result.is_valid:
				self._orders_failed += 1
				self._last_error = validation_result.error_message
				self._last_error_time = execution_time
				
				return ExecutionResult(
					success=False,
					status=ExecutionStatus.REJECTED,
					error_code=validation_result.error_code or ExecutionErrorCode.INVALID_ORDER,
					error_message=validation_result.error_message,
					execution_time=execution_time
				)
			
			# Check connection status
			if not self.is_connected():
				self._orders_failed += 1
				error_msg = "Exchange not connected"
				self._last_error = error_msg
				self._last_error_time = execution_time
				
				return ExecutionResult(
					success=False,
					status=ExecutionStatus.FAILED,
					error_code=ExecutionErrorCode.NETWORK_ERROR,
					error_message=error_msg,
					execution_time=execution_time
				)
			
			# Simulate random failures if enabled
			if self.simulate_failures and random.random() < self.failure_rate:
				self._orders_failed += 1
				error_scenarios = [
					(ExecutionErrorCode.NETWORK_ERROR, "Simulated network timeout"),
					(ExecutionErrorCode.EXCHANGE_ERROR, "Simulated exchange maintenance"),
					(ExecutionErrorCode.RATE_LIMIT_EXCEEDED, "Simulated rate limit"),
					(ExecutionErrorCode.TIMEOUT, "Simulated execution timeout")
				]
				error_code, error_msg = random.choice(error_scenarios)
				self._last_error = error_msg
				self._last_error_time = execution_time
				
				return ExecutionResult(
					success=False,
					status=ExecutionStatus.FAILED,
					error_code=error_code,
					error_message=error_msg,
					execution_time=execution_time
				)
			
			# Calculate execution fee
			commission = self.fee_model.calculate_fee(
				quantity=event.quantity,
				price=event.price,
				side=event.action.lower(),  # Convert action to side
				order_type="market"  # Simulated exchange assumes market orders
			)
			
			# calculate slippage factor
			slippage_factor = self.slippage_model.calculate_slippage_factor(
				quantity=event.quantity,
				price=event.price,
				side=event.action.lower(),
				order_type="market"
			)
			
			executed_price = event.price * slippage_factor
			executed_quantity = event.quantity
			
			# Create and queue fill event (maintaining backward compatibility)
			fill_event = FillEvent.new_fill('EXECUTED', commission, event)
			fill_event.price = executed_price  # Update with slippage-adjusted price
			self.global_queue.put(fill_event)
			
			# Update metrics
			self._orders_executed += 1
			self._total_volume += executed_price * executed_quantity
			
			# Log successful execution
			self.logger.info('Order executed: %s %s %.4f @ $%.4f (slippage: %.4f%%)',
							event.action, event.ticker, executed_quantity, executed_price,
							(slippage_factor - 1.0) * 100)
			
			return ExecutionResult(
				success=True,
				status=ExecutionStatus.SUCCESS,
				order_id=f"SIM_{self._orders_executed}_{int(execution_time.timestamp())}",
				exchange_order_id=f"SIMEX_{self._orders_executed}",
				executed_price=executed_price,
				executed_quantity=executed_quantity,
				remaining_quantity=0.0,
				commission=commission,
				execution_time=execution_time,
				error_code=ExecutionErrorCode.NO_ERROR,
				metadata={
					'slippage_applied': (slippage_factor - 1.0) * 100,
					'original_price': event.price,
					'execution_latency_ms': random.uniform(5, 25),  # Simulate execution latency
					'exchange_name': self._exchange_name
				}
			)
			
		except Exception as e:
			self._orders_failed += 1
			self._last_error = str(e)
			self._last_error_time = execution_time
			self.logger.error('Unexpected error executing order: %s', str(e), exc_info=True)
			
			return ExecutionResult(
				success=False,
				status=ExecutionStatus.FAILED,
				error_code=ExecutionErrorCode.EXCHANGE_ERROR,
				error_message=f"Unexpected error: {str(e)}",
				execution_time=execution_time
			)

	def connect(self) -> ConnectionResult:
		"""Simulate connection to exchange with realistic behavior."""
		try:
			if self._connected:
				return ConnectionResult(
					success=True,
					status=ExchangeConnectionStatus.CONNECTED,
					exchange_name=self._exchange_name,
					connection_time=self._connection_time
				)
			
			# Simulate connection process
			self._connection_status = ExchangeConnectionStatus.CONNECTING
			time.sleep(0.1)  # Simulate connection delay
			
			self._connected = True
			self._connection_time = datetime.now()
			self._connection_status = ExchangeConnectionStatus.CONNECTED
			
			self.logger.info('Connected to simulated exchange successfully')
			
			return ConnectionResult(
				success=True,
				status=ExchangeConnectionStatus.CONNECTED,
				exchange_name=self._exchange_name,
				connection_time=self._connection_time
			)
			
		except Exception as e:
			self._connection_status = ExchangeConnectionStatus.ERROR
			self.logger.error('Failed to connect to simulated exchange: %s', str(e))
			
			return ConnectionResult(
				success=False,
				status=ExchangeConnectionStatus.ERROR,
				exchange_name=self._exchange_name,
				error_code=ExecutionErrorCode.NETWORK_ERROR,
				error_message=str(e)
			)

	def disconnect(self) -> ConnectionResult:
		"""Simulate disconnection from exchange."""
		self._connection_status = ExchangeConnectionStatus.DISCONNECTING
		self._connected = False
		self._connection_time = None
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED
		
		self.logger.info('Disconnected from simulated exchange')
		
		return ConnectionResult(
			success=True,
			status=ExchangeConnectionStatus.DISCONNECTED,
			exchange_name=self._exchange_name
		)

	def is_connected(self) -> bool:
		"""Check connection status."""
		return self._connected and self._connection_status == ExchangeConnectionStatus.CONNECTED

	def health_check(self) -> HealthStatus:
		"""Perform comprehensive health check and return status."""
		current_time = datetime.now()
		self._last_ping = current_time
		
		# Calculate metrics
		total_orders = self._orders_executed + self._orders_failed
		error_rate = (self._orders_failed / total_orders) if total_orders > 0 else 0.0
		uptime = (current_time - self._startup_time).total_seconds()
		
		return HealthStatus(
			exchange_name=self._exchange_name,
			connected=self._connected,
			status=self._connection_status,
			last_ping_time=self._last_ping,
			latency_ms=random.uniform(10, 50),  # Simulate realistic latency
			uptime_seconds=uptime,
			error_rate=error_rate,
			last_error=self._last_error,
			last_error_time=self._last_error_time,
			orders_executed_today=self._orders_executed,
			orders_failed_today=self._orders_failed,
			total_volume_today=self._total_volume,
			connection_established=self._connection_time,
			last_heartbeat=current_time
		)

	def configure(self, config: Dict[str, Any]) -> bool:
		"""Configure exchange settings."""
		try:
			if 'supported_symbols' in config:
				self._supported_symbols = set(config['supported_symbols'])
				self.logger.info('Updated supported symbols: %s', self._supported_symbols)
			
			if 'simulate_failures' in config:
				self.simulate_failures = bool(config['simulate_failures'])
				self.logger.info('Failure simulation: %s', self.simulate_failures)
			
			if 'failure_rate' in config:
				self.failure_rate = max(0.0, min(1.0, float(config['failure_rate'])))
				self.logger.info('Failure rate set to: %.2f%%', self.failure_rate * 100)
			
			if 'min_order_size' in config:
				self._min_order_size = float(config['min_order_size'])
			
			if 'max_order_size' in config:
				self._max_order_size = float(config['max_order_size'])
			
			self.logger.info('Exchange configuration updated successfully')
			return True
			
		except Exception as e:
			self.logger.error('Failed to configure exchange: %s', str(e))
			return False

	def validate_order(self, event: OrderEvent) -> ValidationResult:
		"""Comprehensive order validation with detailed feedback."""
		validation_time = datetime.now()
		failed_checks = []
		warnings = []
		
		# Symbol validation
		if not self.validate_symbol(event.ticker):
			failed_checks.append(f"Invalid symbol: {event.ticker}")
		
		# Quantity validation
		if event.quantity <= 0:
			failed_checks.append("Order quantity must be positive")
		elif event.quantity < self._min_order_size:
			failed_checks.append(f"Order quantity {event.quantity} below minimum {self._min_order_size}")
		elif event.quantity > self._max_order_size:
			failed_checks.append(f"Order quantity {event.quantity} exceeds maximum {self._max_order_size}")
		
		# Price validation
		if event.price <= 0:
			failed_checks.append("Order price must be positive")
		elif event.price > 1000000:  # Sanity check for unrealistic prices
			warnings.append(f"Order price {event.price} seems unusually high")
		
		# Connection validation
		if not self.is_connected():
			failed_checks.append("Exchange not connected")
		
		# Order value validation
		order_value = event.quantity * event.price
		if order_value < 1.0:  # Minimum order value
			warnings.append(f"Order value ${order_value:.2f} is very small")
		
		# Determine overall validation result
		is_valid = len(failed_checks) == 0
		error_code = None
		error_message = None
		
		if not is_valid:
			if "Invalid symbol" in failed_checks[0]:
				error_code = ExecutionErrorCode.SYMBOL_NOT_FOUND
			elif "quantity" in failed_checks[0].lower():
				error_code = ExecutionErrorCode.ORDER_SIZE_TOO_SMALL if "below minimum" in failed_checks[0] else ExecutionErrorCode.ORDER_SIZE_TOO_LARGE
			elif "price" in failed_checks[0].lower():
				error_code = ExecutionErrorCode.INVALID_PRICE
			elif "not connected" in failed_checks[0]:
				error_code = ExecutionErrorCode.NETWORK_ERROR
			else:
				error_code = ExecutionErrorCode.INVALID_ORDER
			
			error_message = "; ".join(failed_checks)
		
		return ValidationResult(
			is_valid=is_valid,
			error_code=error_code,
			error_message=error_message,
			failed_checks=failed_checks if failed_checks else None,
			warnings=warnings if warnings else None,
			validation_time=validation_time
		)

	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is supported for trading."""
		return symbol in self._supported_symbols

	def get_supported_symbols(self) -> set[str]:
		"""Get set of supported trading symbols."""
		return self._supported_symbols.copy()

	def get_exchange_info(self) -> Dict[str, Any]:
		"""Get comprehensive exchange information."""
		return {
			'name': self._exchange_name,
			'type': ExchangeType.SIMULATED.value,
			'connected': self._connected,
			'connection_status': self._connection_status.value,
			'supported_symbols': list(self._supported_symbols),
			'capabilities': [
				'order_execution',
				'slippage_simulation',
				'failure_simulation',
				'health_monitoring',
				'order_validation'
			],
			'limits': {
				'min_order_size': self._min_order_size,
				'max_order_size': self._max_order_size
			},
			'models': {
				'fee_model': self.fee_model.get_fee_info(),
				'slippage_model': self.slippage_model.get_slippage_info()
			},
			'statistics': {
				'orders_executed': self._orders_executed,
				'orders_failed': self._orders_failed,
				'total_volume': self._total_volume,
				'uptime_seconds': (datetime.now() - self._startup_time).total_seconds()
			}
		}

	def _initialize_fee_model(self, fee_model: str, **kwargs):
		"""Initialize fee model using dictionary-based factory pattern."""
		fee_models = {
			'no_fee': lambda: ZeroFeeModel(),
			'zero': lambda: ZeroFeeModel(),
			'percent': lambda: PercentFeeModel(
				fee_rate=kwargs.get('fee_rate', 0.001)
			),
			'maker_taker': lambda: MakerTakerFeeModel(
				maker_rate=kwargs.get('maker_rate', 0.001),
				taker_rate=kwargs.get('taker_rate', 0.001)
			),
			'tiered': lambda: TieredFeeModel(
				tiers=kwargs.get('tiers', [
					{'min_volume': 0, 'max_volume': 100000, 'fee_rate': 0.001},
					{'min_volume': 100000, 'max_volume': float('inf'), 'fee_rate': 0.0008}
				])
			)
		}
		
		factory = fee_models.get(fee_model.lower())
		if factory:
			return factory()
		else:
			self.logger.warning('Fee model %s not supported, defaulting to no_fee', fee_model)
			return ZeroFeeModel()

	def _initialize_slippage_model(self, slippage_model: str, **kwargs):
		"""Initialize slippage model using dictionary-based factory pattern."""
		slippage_models = {
			'none': lambda: ZeroSlippageModel(),
			'zero': lambda: ZeroSlippageModel(),
			'linear': lambda: LinearSlippageModel(
				base_slippage_pct=kwargs.get('slippage_base_slippage_pct', 0.01),
				size_impact_factor=kwargs.get('slippage_size_impact_factor', 0.00001),
				max_slippage_pct=kwargs.get('slippage_max_slippage_pct', 0.1)
			),
			'fixed': lambda: FixedSlippageModel(
				slippage_pct=kwargs.get('slippage_slippage_pct', 0.01),
				random_variation=kwargs.get('slippage_random_variation', True)
			)
		}
		
		factory = slippage_models.get(slippage_model.lower())
		if factory:
			return factory()
		else:
			self.logger.warning('Slippage model %s not supported, defaulting to none', slippage_model)
			return ZeroSlippageModel()