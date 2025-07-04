from queue import Queue
from datetime import datetime
from typing import Dict, Any, Optional
import random
import time
import threading

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
from itrader.config import ExchangeConfig, get_exchange_preset, FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation

class SimulatedExchange(AbstractExchange):
	"""
	Modern simulated exchange with config-driven architecture.
	
	Features:
	- Minimal initialization
	- Configuration-driven behavior
	- Thread-safe configuration updates
	- Production-ready design
	"""

	def __init__(self, global_queue: Queue, config: Optional[ExchangeConfig] = None):
		"""
		Initialize the simulated exchange with minimal setup.
		
		Parameters
		-----------
		global_queue : Queue
			Event queue for the trading system
		config : ExchangeConfig, optional
			Complete exchange configuration object. If not provided, defaults to 'default' preset
		"""
		# Initialize logger early
		self.logger = get_itrader_logger().bind(component="SimulatedExchange")

		# Core exchange identity
		self.global_queue = global_queue
		
		# Exchange configuration
		self.config = config or get_exchange_preset('default')
		
		# Initialize models
		self.fee_model = self._init_fee_model()
		self.slippage_model = self._init_slippage_model()
		
		# Operational parameters
		self.simulate_failures = self.config.failure_simulation.simulate_failures
		self.failure_rate = float(self.config.failure_simulation.failure_rate)
		
		# Thread safety
		self._lock = threading.RLock()
		
		# Connection state
		self._connected = False
		self._connection_time = None
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED
		
		# Performance tracking
		self._orders_executed = 0
		self._orders_failed = 0
		self._last_error = None
		self._last_error_time = None
		self._total_volume = 0.0
		self._startup_time = datetime.now()
		self._last_ping = None
		
		# Exchange limits and settings
		self._supported_symbols = self.config.limits.supported_symbols
		self._min_order_size = float(self.config.limits.min_order_size)
		self._max_order_size = float(self.config.limits.max_order_size)
		self._exchange_name = self.config.exchange_name
		
		self.logger.info('Simulated Exchange initialized: %s', self.config.exchange_name)

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
					(ExecutionErrorCode.EXCHANGE_MAINTENANCE, "Simulated execution timeout")
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
			'configuration': {
				'exchange_type': self.config.exchange_type.value,
				'fee_model_type': self.config.fee_model.model_type.value,
				'slippage_model_type': self.config.slippage_model.model_type.value,
				'simulate_failures': self.config.failure_simulation.simulate_failures,
				'failure_rate': float(self.config.failure_simulation.failure_rate)
			},
			'statistics': {
				'orders_executed': self._orders_executed,
				'orders_failed': self._orders_failed,
				'total_volume': self._total_volume,
				'uptime_seconds': (datetime.now() - self._startup_time).total_seconds()
			}
		}

	def _init_fee_model(self):
		"""Create fee model from configuration."""
		config = self.config.fee_model
		
		if config.model_type.value in ['no_fee', 'zero']:
			return ZeroFeeModel()
		elif config.model_type.value == 'percent':
			return PercentFeeModel(fee_rate=config.fee_rate or 0.001)
		elif config.model_type.value == 'maker_taker':
			return MakerTakerFeeModel(
				maker_rate=config.maker_rate or 0.001,
				taker_rate=config.taker_rate or 0.001
			)
		elif config.model_type.value == 'tiered':
			default_tiers = [
				{'min_volume': 0, 'max_volume': 100000, 'fee_rate': 0.001},
				{'min_volume': 100000, 'max_volume': float('inf'), 'fee_rate': 0.0008}
			]
			return TieredFeeModel(tiers=config.tiers or default_tiers)
		else:
			self.logger.warning('Unknown fee model %s, defaulting to no_fee', config.model_type.value)
			return ZeroFeeModel()

	def _init_slippage_model(self):
		"""Create slippage model from configuration."""
		config = self.config.slippage_model
		
		if config.model_type.value in ['none', 'zero']:
			return ZeroSlippageModel()
		elif config.model_type.value == 'linear':
			return LinearSlippageModel(
				base_slippage_pct=config.base_slippage_pct or 0.01,
				size_impact_factor=config.size_impact_factor or 0.00001,
				max_slippage_pct=config.max_slippage_pct or 0.1
			)
		elif config.model_type.value == 'fixed':
			return FixedSlippageModel(
				slippage_pct=config.slippage_pct or 0.01,
				random_variation=config.random_variation if config.random_variation is not None else True
			)
		else:
			self.logger.warning('Unknown slippage model %s, defaulting to none', config.model_type.value)
			return ZeroSlippageModel()

	# Configuration Management (following Portfolio pattern)
	def update_config(self, **kwargs) -> None:
		"""Update exchange configuration."""
		with self._lock:
			# Direct config attribute updates
			config_mapping = {
				'exchange_name': 'exchange_name',
				'exchange_type': 'exchange_type',
				'simulate_failures': ('failure_simulation', 'simulate_failures'),
				'failure_rate': ('failure_simulation', 'failure_rate'),
				'supported_symbols': ('limits', 'supported_symbols'),
				'min_order_size': ('limits', 'min_order_size'),
				'max_order_size': ('limits', 'max_order_size'),
				'fee_model_type': ('fee_model', 'model_type'),
				'fee_rate': ('fee_model', 'fee_rate'),
				'maker_rate': ('fee_model', 'maker_rate'),
				'taker_rate': ('fee_model', 'taker_rate'),
				'slippage_model_type': ('slippage_model', 'model_type'),
				'base_slippage_pct': ('slippage_model', 'base_slippage_pct'),
				'slippage_pct': ('slippage_model', 'slippage_pct'),
			}
			
			for key, value in kwargs.items():
				if isinstance(config_mapping.get(key), tuple):
					section_name, attr_name = config_mapping[key]
					section = getattr(self.config, section_name)
					setattr(section, attr_name, value)
				elif key in config_mapping:
					setattr(self.config, config_mapping[key], value)
				elif hasattr(self.config, key):
					setattr(self.config, key, value)
				else:
					raise ValueError(f"Unknown configuration key: {key}")
			
			# Re-initialize components affected by config changes
			if any(k.startswith('fee_') for k in kwargs) or 'fee_model_type' in kwargs:
				self.fee_model = self._init_fee_model()
			if any(k.startswith('slippage_') for k in kwargs) or 'slippage_model_type' in kwargs:
				self.slippage_model = self._init_slippage_model()
			if 'simulate_failures' in kwargs or 'failure_rate' in kwargs:
				self.simulate_failures = self.config.failure_simulation.simulate_failures
				self.failure_rate = float(self.config.failure_simulation.failure_rate)
			
			# Update internal state for limits
			if any(k in ['supported_symbols', 'min_order_size', 'max_order_size'] for k in kwargs):
				self._supported_symbols = self.config.limits.supported_symbols
				self._min_order_size = float(self.config.limits.min_order_size)
				self._max_order_size = float(self.config.limits.max_order_size)
			
			# Update exchange name if changed
			if 'exchange_name' in kwargs:
				self._exchange_name = self.config.exchange_name

	def get_config_dict(self) -> Dict[str, Any]:
		"""Get configuration as dictionary."""
		with self._lock:
			return {
				'exchange_name': self.config.exchange_name,
				'exchange_type': self.config.exchange_type.value if hasattr(self.config.exchange_type, 'value') else str(self.config.exchange_type),
				'simulate_failures': self.config.failure_simulation.simulate_failures,
				'failure_rate': float(self.config.failure_simulation.failure_rate),
				'supported_symbols': list(self.config.limits.supported_symbols),
				'min_order_size': float(self.config.limits.min_order_size),
				'max_order_size': float(self.config.limits.max_order_size),
				'fee_model_type': self.config.fee_model.model_type.value,
				'fee_rate': self.config.fee_model.fee_rate,
				'maker_rate': self.config.fee_model.maker_rate,
				'taker_rate': self.config.fee_model.taker_rate,
				'slippage_model_type': self.config.slippage_model.model_type.value,
				'base_slippage_pct': self.config.slippage_model.base_slippage_pct,
				'slippage_pct': self.config.slippage_model.slippage_pct,
			}