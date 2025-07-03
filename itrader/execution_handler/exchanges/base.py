from abc import ABCMeta, abstractmethod
from typing import Optional, Dict, Any, Tuple

from itrader.events_handler.event import OrderEvent
from ..result_objects import ExecutionResult, ConnectionResult, HealthStatus, ValidationResult

class AbstractExchange(object):
	"""
	Enhanced AbstractExchange provides a comprehensive interface for
	exchange operations including connection management, order execution,
	health monitoring, and error handling.
	
	This interface supports both simulated and live trading environments
	with consistent error handling and monitoring capabilities.
	"""

	__metaclass__ = ABCMeta

	# Core execution methods
	@abstractmethod
	def execute_order(self, event: OrderEvent) -> ExecutionResult:
		"""
		Execute an order and return detailed execution result.
		
		Parameters
		-----------
		event : OrderEvent
			The order event to execute
			
		Returns
		--------
		ExecutionResult
			Detailed result of the execution attempt including success status,
			execution details, error information, and metadata
		"""
		raise NotImplementedError("Should implement execute_order()")

	# Connection management
	@abstractmethod
	def connect(self) -> ConnectionResult:
		"""
		Establish connection to the exchange.
		
		Returns
		--------
		ConnectionResult
			Result of the connection attempt including success status,
			connection time, and any error information
		"""
		raise NotImplementedError("Should implement connect()")

	@abstractmethod
	def disconnect(self) -> ConnectionResult:
		"""
		Disconnect from the exchange.
		
		Returns
		--------
		ConnectionResult
			Result of the disconnection attempt
		"""
		raise NotImplementedError("Should implement disconnect()")

	@abstractmethod
	def is_connected(self) -> bool:
		"""
		Check if currently connected to exchange.
		
		Returns
		--------
		bool
			True if connected and ready to execute orders, False otherwise
		"""
		raise NotImplementedError("Should implement is_connected()")

	# Health and monitoring
	@abstractmethod
	def health_check(self) -> HealthStatus:
		"""
		Perform comprehensive health check of the exchange.
		
		Returns
		--------
		HealthStatus
			Current health status including connectivity, performance metrics,
			error rates, and activity statistics
		"""
		raise NotImplementedError("Should implement health_check()")

	# Configuration
	@abstractmethod
	def configure(self, config: Dict[str, Any]) -> bool:
		"""
		Configure exchange with settings and credentials.
		
		Parameters
		-----------
		config : Dict[str, Any]
			Configuration parameters including API credentials,
			rate limits, timeout settings, etc.
			
		Returns
		--------
		bool
			True if configuration was successful, False otherwise
		"""
		raise NotImplementedError("Should implement configure()")

	# Validation methods
	@abstractmethod
	def validate_order(self, event: OrderEvent) -> ValidationResult:
		"""
		Validate order before execution with comprehensive checks.
		
		Parameters
		-----------
		event : OrderEvent
			Order to validate
			
		Returns
		--------
		ValidationResult
			Validation result including validity status, error details,
			failed checks, and warnings
		"""
		raise NotImplementedError("Should implement validate_order()")

	@abstractmethod
	def validate_symbol(self, symbol: str) -> bool:
		"""
		Check if symbol is valid for trading on this exchange.
		
		Parameters
		-----------
		symbol : str
			Trading symbol to validate (e.g., 'BTCUSDT')
			
		Returns
		--------
		bool
			True if symbol is valid and tradable, False otherwise
		"""
		raise NotImplementedError("Should implement validate_symbol()")

	# Optional methods with default implementations
	def get_supported_symbols(self) -> set[str]:
		"""
		Get set of supported trading symbols.
		
		Returns
		--------
		set[str]
			Set of supported symbol strings
		"""
		return set()

	def get_exchange_info(self) -> Dict[str, Any]:
		"""
		Get exchange information and capabilities.
		
		Returns
		--------
		Dict[str, Any]
			Exchange information including name, type, capabilities, limits, etc.
		"""
		return {
			'name': self.__class__.__name__,
			'type': 'unknown',
			'capabilities': []
		}
