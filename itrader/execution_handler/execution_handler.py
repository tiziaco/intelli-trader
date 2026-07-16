import random
from typing import Any, Dict, Optional

from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import BarEvent, FillEvent, OrderEvent
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.config import ExchangeConfig, get_exchange_preset
from itrader.core.exceptions.base import ConfigurationError
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

	def __init__(self, global_queue: "EventBus",
				exchange_config: Optional[ExchangeConfig] = None) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		exchange_config: `ExchangeConfig`, optional
			Construction-time exchange configuration threaded to the
			SimulatedExchange (D-13, COMP-01). When provided the FACTORY has
			already folded the COMPLETE supported_symbols set
			(default preset ∪ {BTCUSD} ∪ spec tickers) into
			``exchange_config.limits.supported_symbols`` — replacement-safe so a
			later ``update_config`` re-derivation never wipes a symbol
			(PATTERNS-A2 Trap 1). When None a TEMPORARY backward-compat default
			is built that unions ``{BTCUSD}`` into the preset, so the
			direct-construction oracle/integration sites (still calling
			``ExecutionHandler(global_queue)`` until Wave 4) keep BTCUSD
			admitted byte-exactly. Wave 4 (04-05) removes the None fallback once
			every site migrates to the spec-driven factory.
		"""
		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="ExecutionHandler")

		self.global_queue = global_queue
		self._exchange_config = exchange_config

		# Determinism seam (D-11): construct a SINGLE seeded random.Random at engine
		# wiring and inject it into every stochastic component (SimulatedExchange +
		# its slippage model). The seed comes from the documented system config key
		# `performance.rng_seed` (default 42); a YAML override in settings/system.yaml
		# wins when present. One shared Random — never seeded per-call or duplicated —
		# so a backtest run is reproducible (#5/PERF2).
		self._rng_seed: int = self._resolve_rng_seed()
		self._rng: random.Random = random.Random(self._rng_seed)

		# Initialize exchanges (requires logger + rng)
		self.exchanges: dict[str, Optional[AbstractExchange]] = self.init_exchanges()

		self.logger.info('Execution Handler initialized (rng_seed=%s)', self._rng_seed)

	def _resolve_rng_seed(self) -> int:
		"""Resolve the determinism seed from the process-wide config singleton (D-16/W4-06).

		Reads ``config.rng_seed`` off the single process-wide ``ITraderConfig``
		initialised in ``itrader/__init__.py`` — NOT a second duplicate config
		construction (the W4-06 duplication this fix removes). P9 D-09 moved the
		seed off the retired ``config.performance.rng_seed`` onto the frozen
		``ITraderConfig`` base (``config.rng_seed``), immutable at runtime
		(RTCFG-04). One run-wide determinism setting (default 42); a boot YAML/env
		override resolves before construction, making this read byte-identical or
		strictly more correct. Seed stays 42 → the single shared
		``random.Random(42)`` is unchanged → byte-exact.
		"""
		from itrader import config
		return int(config.rng_seed)

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update execution configuration at runtime (D-07/D-08/D-09).

		The handler owns no Pydantic config model of its own; the execution
		config lives on the exchange. So the uniform ``update_config`` routes the
		partial update to the simulated exchange's canonical ``update_config``
		(deep_merge -> model_validate -> atomic-swap -> ConfigurationError),
		keeping the single web-catchable raise contract. Returns ``None``; raises
		``ConfigurationError`` on failure (including when no exchange is wired).
		"""
		exchange = self.exchanges.get('simulated')
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key='simulated',
				reason='no simulated exchange wired to update')
		exchange.update_config(updates)


	def on_order(self, event: OrderEvent) -> None:
		"""Route an order event to the configured exchange's order router."""
		try:
			exchange = self.exchanges.get(event.exchange)
			if not exchange:
				self.logger.error('Unknown exchange specified: %s for order %s %s',
								event.exchange, event.ticker, event.action)
				return
			exchange.on_order(event)
		except Exception as e:
			self.logger.error('Unexpected error routing order for %s %s: %s',
							 event.ticker, event.action, str(e), exc_info=True)

	def on_market_data(self, bar: BarEvent) -> None:
		"""Drive resting-order matching on each exchange with a new bar."""
		# Dedup by instance identity: multiple venue aliases (e.g. 'simulated' and 'csv')
		# may point to the same exchange object; driving it once per bar avoids
		# double-matching the resting-order book (DEF-01-B alias, Plan 01-04).
		seen: set[int] = set()
		for name, exchange in self.exchanges.items():
			if exchange is None or id(exchange) in seen:
				continue
			seen.add(id(exchange))
			try:
				exchange.on_market_data(bar)
			except Exception as e:
				self.logger.error('Error matching resting orders on %s: %s',
								 name, str(e), exc_info=True)

	
	def init_exchanges(self) -> dict[str, Optional[AbstractExchange]]:
		"""
		Initialize configured exchanges.

		Creates exchange instances using their default configurations.
		Each exchange manages its own fee models, slippage simulation, etc.
		"""
		# D-13/Trap 1: thread the construction-time ExchangeConfig into the
		# SimulatedExchange so the COMPLETE supported_symbols set is seeded at
		# construction (replacement-safe) instead of an additive post-construction
		# register_symbol. When the factory supplies a config it has already folded
		# default preset ∪ {BTCUSD} ∪ spec tickers into limits.supported_symbols.
		#
		# TEMPORARY backward-compat (Wave 4 / 04-05 removes this): when no config is
		# supplied (direct-construction oracle/integration sites still calling
		# ExecutionHandler(global_queue)), build a default-preset config that UNIONS
		# {BTCUSD} so the golden ticker stays admitted byte-exactly — replacing the
		# removed hardcoded BTCUSD registration without an additive mutation.
		exchange_config = self._exchange_config or self._default_backcompat_config()
		# Inject the single seeded Random (D-11) so the exchange + its slippage
		# model share one deterministic RNG instance for the whole backtest run.
		simulated = SimulatedExchange(self.global_queue, config=exchange_config, rng=self._rng)
		exchanges: dict[str, Optional[AbstractExchange]] = {
			'simulated': simulated,
			# Backtest portfolios use exchange="csv" (offline golden feed). Orders carry the
			# portfolio's exchange string, so the 'csv' venue must resolve to the simulated
			# matching engine for the backtest fill path to work (DEF-01-B, Plan 01-04).
			'csv': simulated,
			'ccxt': None  # Placeholder for live exchange implementation
		}
		
		# Connect to exchanges that support it. Dedup by instance identity:
		# venue aliases (e.g. 'simulated' and 'csv') may point to the same
		# exchange object; connecting it once avoids a misleading second
		# "Successfully connected" log for the idempotent no-op call (IN-03).
		seen_connect: set[int] = set()
		for exchange_name, exchange in exchanges.items():
			if exchange is None or id(exchange) in seen_connect:
				continue
			seen_connect.add(id(exchange))
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

	@staticmethod
	def _default_backcompat_config() -> ExchangeConfig:
		"""Build the TEMPORARY no-config default exchange config (D-13, Trap 1).

		Reproduces today's direct-construction symbol set byte-exactly: the
		default preset symbols UNION ``{BTCUSD}`` (the union the removed
		hardcoded BTCUSD registration used to produce). Seeded at
		construction so it is replacement-safe — a later ``update_config`` that
		re-derives ``_supported_symbols`` from ``config.limits`` can never wipe
		BTCUSD. Wave 4 (04-05) removes this fallback once every construction site
		passes a spec-derived config through the factory.
		"""
		config = get_exchange_preset('default')
		config.limits.supported_symbols = set(config.limits.supported_symbols) | {'BTCUSD'}
		return config

	def get_exchange_health(self, exchange_name: Optional[str] = None) -> dict[str, Any]:
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
		health_data: dict[str, Any] = {}

		exchanges_to_check = [exchange_name] if exchange_name else list(self.exchanges.keys())
		
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
