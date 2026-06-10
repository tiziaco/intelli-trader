from queue import Queue
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional
import random

from .base import AbstractExchange
from ..fee_model.base import FeeModel
from ..fee_model.zero_fee_model import ZeroFeeModel
from ..fee_model.percent_fee_model import PercentFeeModel
from ..fee_model.maker_taker_fee_model import MakerTakerFeeModel
from ..slippage_model.base import SlippageModel
from ..slippage_model.zero_slippage_model import ZeroSlippageModel
from ..slippage_model.linear_slippage_model import LinearSlippageModel
from ..slippage_model.fixed_slippage_model import FixedSlippageModel
from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from ..matching_engine import MatchingEngine
from itrader.core.enums.execution import ExecutionErrorCode, ExchangeConnectionStatus, ExchangeType
from itrader.core.enums import OrderType, OrderCommand
from itrader.core.money import to_money
from itrader.events_handler.events import BarEvent, FillEvent, OrderEvent
from itrader.logger import get_itrader_logger
from itrader.config import ExchangeConfig, get_exchange_preset, FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation

class SimulatedExchange(AbstractExchange):
	"""
	Modern simulated exchange with config-driven architecture.
	
	Features:
	- Minimal initialization
	- Configuration-driven behavior
	- Production-ready design

	D-19 single-writer contract: configuration updates happen on the engine
	thread; queue.Queue is the thread boundary — other threads only put events.
	"""

	def __init__(self, global_queue: "Queue[Any]", config: Optional[ExchangeConfig] = None,
				rng: Optional[random.Random] = None) -> None:
		"""
		Initialize the simulated exchange with minimal setup.

		Parameters
		-----------
		global_queue : Queue
			Event queue for the trading system
		config : ExchangeConfig, optional
			Complete exchange configuration object. If not provided, defaults to 'default' preset
		rng : random.Random, optional
			Injected seeded RNG for deterministic failure-simulation + latency/slippage
			jitter (D-11). When None a fresh ``random.Random()`` is used; the engine
			wiring (ExecutionHandler) passes one seeded instance shared across the
			exchange and its slippage model so backtests are reproducible (#5/PERF2).
		"""
		# Initialize logger early
		self.logger = get_itrader_logger().bind(component="SimulatedExchange")

		# Core exchange identity
		self.global_queue = global_queue

		# Seeded RNG seam (D-11): shared with the slippage model constructed below.
		self._rng: random.Random = rng or random.Random()

		# Resting-order book / matching engine — the SINGLE matching path
		# (D-13): every admitted NEW order rests here, market orders
		# included, and fills at the next bar (next-bar-open convention).
		self.matching_engine = MatchingEngine()

		# Exchange configuration
		self.config = config or get_exchange_preset('default')

		# Initialize models
		self.fee_model = self._init_fee_model()
		self.slippage_model = self._init_slippage_model()
		
		# Operational parameters
		self.simulate_failures = self.config.failure_simulation.simulate_failures
		self.failure_rate = float(self.config.failure_simulation.failure_rate)
		
		# D-19: config lock removed — single-writer contract, see class docstring.

		# Connection state
		self._connected = False
		self._connection_time: Optional[datetime] = None
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED

		# Performance tracking
		self._orders_executed = 0
		self._orders_failed = 0
		self._last_error: Optional[str] = None
		self._last_error_time: Optional[datetime] = None
		# Money-denominated telemetry: Decimal end-to-end (D-12).
		self._total_volume = Decimal("0")
		self._startup_time = datetime.now()
		self._last_ping: Optional[datetime] = None
		
		# Exchange limits and settings
		self._supported_symbols = self.config.limits.supported_symbols
		self._min_order_size = float(self.config.limits.min_order_size)
		self._max_order_size = float(self.config.limits.max_order_size)
		self._exchange_name = self.config.exchange_name
		
		self.logger.info('Simulated Exchange initialized: %s', self.config.exchange_name)

	def _admit_order(self, event: OrderEvent) -> bool:
		"""
		Pre-trade admission gate for NEW orders (D-21/D-13).

		Runs at on_order time — validation, connection check and failure
		simulation — BEFORE the order rests in the matching engine. Every
		rejected outcome is emitted as a FillEvent(REFUSED) so the order
		mirror reconciles; there is no synchronous result object. Returns
		True when the order may rest in the book. Fills NEVER happen here:
		the MatchingEngine decides them on subsequent bars (next-bar-open
		convention, D-01/D-13).
		"""
		admission_time = datetime.now()

		try:
			# Pre-trade validation
			validation_result = self.validate_order(event)
			if not validation_result.is_valid:
				self._orders_failed += 1
				self._last_error = validation_result.error_message
				self._last_error_time = admission_time
				self._emit_rejection(event, validation_result.error_message or "validation failed")
				return False

			# Check connection status
			if not self.is_connected():
				self._orders_failed += 1
				error_msg = "Exchange not connected"
				self._last_error = error_msg
				self._last_error_time = admission_time
				self._emit_rejection(event, "exchange not connected")
				return False

			# Simulate random failures if enabled
			if self.simulate_failures and self._rng.random() < self.failure_rate:
				self._orders_failed += 1
				error_scenarios = [
					(ExecutionErrorCode.NETWORK_ERROR, "Simulated network timeout"),
					(ExecutionErrorCode.EXCHANGE_ERROR, "Simulated exchange maintenance"),
					(ExecutionErrorCode.RATE_LIMIT_EXCEEDED, "Simulated rate limit"),
					(ExecutionErrorCode.EXCHANGE_MAINTENANCE, "Simulated execution timeout")
				]
				_error_code, error_msg = self._rng.choice(error_scenarios)
				self._last_error = error_msg
				self._last_error_time = admission_time
				self._emit_rejection(event, error_msg)
				return False

			return True

		except Exception as e:
			self._orders_failed += 1
			self._last_error = str(e)
			self._last_error_time = admission_time
			self.logger.error('Unexpected error admitting order: %s', str(e), exc_info=True)
			# T-05-08: even unexpected failures must surface as an auditable
			# FillEvent(REFUSED) so the order mirror reconciles — no outcome
			# may be lost now that the sync result channel is gone (D-21).
			self._emit_rejection(event, f"Unexpected error: {str(e)}")
			return False

	def _emit_rejection(self, event: OrderEvent, reason: str) -> None:
		"""Enqueue a FillEvent(REFUSED) so the order mirror can reconcile a rejected order."""
		self.logger.debug('Emitting REFUSED fill for %s %s: %s', event.action, event.ticker, reason)
		# REFUSED carries the order's own (Decimal, D-22) price/quantity,
		# commission Decimal("0") — never settled, so no float round-trip needed.
		self.global_queue.put(FillEvent.new_fill(
			'REFUSED', event, price=event.price, quantity=event.quantity,
			commission=Decimal("0")))

	def _emit_fill(self, event: OrderEvent, fill_price: Decimal,
	               fill_quantity: Decimal, fill_time: datetime) -> None:
		"""Apply fee + slippage to a matched fill and enqueue a FillEvent(EXECUTED).

		Fill time (D-01/D-13): ``fill_time`` is the MATCHING BAR's event
		time — fill truth is stamped at the bar that produced it, never at
		the order's decision tick. An order decided at tick T fills with
		FillEvent.time = T+1tf.

		Money (D-12): Decimal end-to-end — the old price_f/quantity_f float
		casts are gone. ``to_money`` is an identity normalization at this
		domain entry (the engine and event money are already Decimal).

		Real order context (D-11): order_type and maker/taker classification
		derive from the OrderEvent the caller already holds — a resting LIMIT
		is a maker; MARKET and triggered STOP fills are takers.

		Slippage gating (D-03): slippage applies ONLY to MARKET and STOP
		fills. LIMIT fills take fill_price unmodified — limit-or-better means
		a limit fill can never be slipped past its limit price.
		"""
		price = to_money(fill_price)
		quantity = to_money(fill_quantity)
		# D-05: the event carries a Side member; the fee/slippage models keep
		# their lowercase-string contract — convert via .value at this boundary.
		side = event.action.value.lower()
		order_type = event.order_type.value
		is_maker = event.order_type is OrderType.LIMIT
		commission = self.fee_model.calculate_fee(
			quantity=quantity, price=price,
			side=side, order_type=order_type, is_maker=is_maker)
		if event.order_type is OrderType.LIMIT:
			# D-03: limit fills are never slipped — limit-or-better.
			slippage_factor = Decimal("1")
		else:
			slippage_factor = self.slippage_model.calculate_slippage_factor(
				quantity=quantity, price=price,
				side=side, order_type=order_type)
		executed_price = price * slippage_factor

		# Construct-complete (D-12): the slippage-adjusted price and the fill
		# quantity (the order's full quantity — D-06 full-quantity contract)
		# are explicit constructor inputs — the fill is never mutated after
		# construction. new_fill's to_money is an identity normalization here.
		fill_event = FillEvent.new_fill(
			'EXECUTED', event,
			price=executed_price, quantity=quantity, commission=commission,
			time=fill_time)
		self.global_queue.put(fill_event)

		self._orders_executed += 1
		self._total_volume += executed_price * quantity
		self.logger.debug('Order executed: %s %s %.4f @ $%.4f (slippage: %.4f%%)',
						event.action, event.ticker, quantity, executed_price,
						(slippage_factor - Decimal("1")) * 100)

	def on_market_data(self, bar: "BarEvent") -> None:
		"""Match resting orders against a new bar; emit EXECUTED fills and OCO cancels.

		Every outcome decided by this bar — fills AND OCO cancellations —
		is stamped with the bar's event time (D-01/D-13): the truth lives
		at the bar that produced it, not at the order's decision tick.
		"""
		fills, cancels = self.matching_engine.on_bar(bar)
		for decision in fills:
			# Full-quantity contract (D-06): FillDecision carries no quantity —
			# the fill covers the order's entire quantity.
			self._emit_fill(decision.order_event, decision.fill_price,
			                decision.order_event.quantity, bar.time)
		for cancel in cancels:
			# CANCELLED carries the order's own (Decimal) price/quantity,
			# commission Decimal("0") — never settled (D-22).
			self.global_queue.put(FillEvent.new_fill(
				'CANCELLED', cancel.order_event,
				price=cancel.order_event.price, quantity=cancel.order_event.quantity,
				commission=Decimal("0"), time=bar.time))

	def on_order(self, event: OrderEvent) -> None:
		"""
		Route an order event by command (D-13: ONE matching path).

		- CANCEL: remove the resting order, emit FILL(CANCELLED).
		- MODIFY: mutate the resting order.
		- NEW (every order type, MARKET included): run the pre-trade
		  admission gate (validation, connection, failure simulation —
		  rejections emit FillEvent(REFUSED) for mirror reconciliation),
		  then rest the order in the matching engine. Fills happen ONLY
		  on subsequent bars: a market order decided at tick T fills at
		  the open of the bar stamped T+1tf (next-bar-open, D-01/D-13).
		  An order decided on the FINAL dataset bar never fills — no next
		  bar exists (bar-timing contract rule 7).
		"""
		if event.command == OrderCommand.CANCEL:
			# Only acknowledge a cancel for an order that was actually resting;
			# a cancel for an unknown/already-filled order emits no spurious fill.
			if event.order_id is not None and self.matching_engine.cancel(event.order_id):
				# CANCELLED carries the order's own (Decimal) price/quantity,
				# commission Decimal("0") — never settled (D-22).
				self.global_queue.put(FillEvent.new_fill(
					'CANCELLED', event, price=event.price, quantity=event.quantity,
					commission=Decimal("0")))
			return

		if event.command == OrderCommand.MODIFY:
			if event.order_id is not None:
				self.matching_engine.modify(event.order_id, event.price, event.quantity)
			return

		# NEW — single matching path (D-13): every admitted order rests in
		# the book; the MatchingEngine decides fills on subsequent bars.
		if not self._admit_order(event):
			return
		self.matching_engine.submit(event)

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
			
			# PERF1 (plan 06-04): the simulated connection is instantaneous —
			# the artificial connect-latency sleep is gone from the backtest path.
			self._connection_status = ExchangeConnectionStatus.CONNECTING
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

		# total_volume is Decimal end-to-end (D-12) — no boundary coercion needed.
		return HealthStatus(
			exchange_name=self._exchange_name,
			connected=self._connected,
			status=self._connection_status,
			last_ping_time=self._last_ping,
			latency_ms=self._rng.uniform(10, 50),  # Simulate realistic latency
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

	def validate_order(self, event: OrderEvent) -> OrderPreflightResult:
		"""Comprehensive pre-trade order checks with detailed feedback (OQ3)."""
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
		
		return OrderPreflightResult(
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

	def _init_fee_model(self) -> FeeModel:
		"""Create fee model from configuration."""
		config = self.config.fee_model

		# T-07-06 (07-02): use ``is not None`` not ``or`` so a LEGITIMATE zero
		# config value (e.g. a zeroed determinism knob) is honored verbatim
		# instead of being silently overridden by the default. ``Decimal("0")``
		# is falsy, so ``config.x or <default>`` swallows an intentional 0 and
		# makes the configured cost non-hand-derivable. Oracle-safe: the oracle
		# runs ZeroFeeModel/ZeroSlippageModel (exchange="csv", fees/slippage 0)
		# and never reaches these percent/maker_taker/fixed/linear branches.
		if config.model_type.value in ['no_fee', 'zero']:
			return ZeroFeeModel()
		elif config.model_type.value == 'percent':
			# T-07-06 (07-02, WR-02): pass the configured Decimal through unchanged.
			# PercentFeeModel accepts ``float | Decimal`` and enters the Decimal
			# domain once via ``to_money``; routing through ``float()`` would risk a
			# binary-float repr artifact (CLAUDE.md money policy: never Decimal(float)).
			return PercentFeeModel(
				fee_rate=config.fee_rate if config.fee_rate is not None else Decimal("0.001"))
		elif config.model_type.value == 'maker_taker':
			return MakerTakerFeeModel(
				maker_rate=config.maker_rate if config.maker_rate is not None else Decimal("0.001"),
				taker_rate=config.taker_rate if config.taker_rate is not None else Decimal("0.001")
			)
		else:
			self.logger.warning('Unknown fee model %s, defaulting to no_fee', config.model_type.value)
			return ZeroFeeModel()

	def _init_slippage_model(self) -> SlippageModel:
		"""Create slippage model from configuration."""
		config = self.config.slippage_model

		# T-07-06 (07-02): ``is not None`` not ``or`` — a configured 0 (e.g.
		# base_slippage_pct=Decimal("0") to zero the RNG base-noise so the fill
		# is hand-derivable to the cent) must be honored, not overridden by the
		# default. Oracle-safe (the oracle never reaches the linear/fixed branch).
		if config.model_type.value in ['none', 'zero']:
			return ZeroSlippageModel()
		elif config.model_type.value == 'linear':
			# WR-02: pass configured Decimal rates through unchanged; the model
			# accepts ``float | Decimal`` and enters Decimal once via ``to_money``.
			return LinearSlippageModel(
				base_slippage_pct=(
					config.base_slippage_pct if config.base_slippage_pct is not None else Decimal("0.01")),
				size_impact_factor=(
					config.size_impact_factor if config.size_impact_factor is not None else Decimal("0.00001")),
				max_slippage_pct=(
					config.max_slippage_pct if config.max_slippage_pct is not None else Decimal("0.1")),
				rng=self._rng
			)
		elif config.model_type.value == 'fixed':
			return FixedSlippageModel(
				slippage_pct=(
					config.slippage_pct if config.slippage_pct is not None else Decimal("0.01")),
				random_variation=config.random_variation if config.random_variation is not None else True,
				rng=self._rng
			)
		else:
			self.logger.warning('Unknown slippage model %s, defaulting to none', config.model_type.value)
			return ZeroSlippageModel()

	# Configuration Management (following Portfolio pattern)
	def configure(self, config: Dict[str, Any]) -> bool:
		"""
		Conform to the AbstractExchange Protocol (D-08, Pitfall 3).

		`update_config` already applies settings but is not the Protocol method
		name; `configure` delegates to it so SimulatedExchange structurally
		satisfies AbstractExchange. Returns True on success, False on a rejected
		(unknown) configuration key.
		"""
		try:
			self.update_config(**config)
		except ValueError as exc:
			self.logger.warning('Exchange configure rejected: %s', exc)
			return False
		return True

	def update_config(self, **kwargs: Any) -> None:
		"""Update exchange configuration."""
		# Direct config attribute updates
		config_mapping: Dict[str, Any] = {
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