import numpy as np
from datetime import datetime, UTC
from typing import Optional, Dict, List, Any
from decimal import Decimal

from itrader.portfolio_handler.transaction import Transaction
from itrader.portfolio_handler.position import Position
from itrader.events_handler.events import BarEvent
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.core.enums import PortfolioState, PositionSide, TransactionType

# Import the new managers
from itrader.portfolio_handler.transaction.transaction_manager import TransactionManager
from itrader.portfolio_handler.position.position_manager import PositionManager
from itrader.portfolio_handler.cash.cash_manager import CashManager
from itrader.portfolio_handler.metrics.metrics_manager import MetricsManager
from itrader.portfolio_handler.storage import (
	PortfolioStateStorage,
	PortfolioStateStorageFactory,
)
from itrader.core.ids import PortfolioId

from itrader import idgen

TOLERANCE = 1e-3


class Portfolio(object):
	"""
	Enhanced Portfolio with integrated state management and configuration.

	Each portfolio is now self-contained with its own:
	- State management (ACTIVE, INACTIVE, ARCHIVED)
	- Configuration (limits, validation settings) via a Pydantic PortfolioConfig
	- Health monitoring

	D-19 single-writer contract: ALL portfolio state mutations happen on the
	engine thread; queue.Queue is the thread boundary — other threads only put
	events. Composite reads are consistent because nothing mutates concurrently.
	Live cross-thread reads are a D-live design item.

	Maintains backward compatibility with existing interface.
	"""

	def __init__(self, user_id: int, name: str, exchange: str, cash: Decimal, time: datetime,
	             config: Optional[PortfolioConfig] = None) -> None:
		"""
		Initialize enhanced portfolio with integrated capabilities.
		"""
		# Core portfolio identity
		self.user_id = user_id
		self.portfolio_id: PortfolioId = PortfolioId(idgen.generate_portfolio_id())
		self.name = name
		self.exchange = exchange
		self.creation_time = time
		self.current_time = time
		
		# Portfolio-specific configuration
		self.config = config or get_portfolio_preset('default')
		
		# Portfolio state management
		self._state = PortfolioState.ACTIVE
		self._state_transitions = [(PortfolioState.ACTIVE, time)]
		self._last_activity = time
		
		# D-19: lock removed — single-writer contract, see class docstring.

		# Health monitoring
		self._health_metrics: Dict[str, Any] = {
			'last_health_check': time,
			'validation_errors': 0,
			'transaction_failures': 0,
			'state_changes': 1
		}
		
		# Initialize managers with self-reference
		self._init_managers(cash)
		
		# Validation
		self._validate_initial_state()
	
	def _init_managers(self, initial_cash: float | Decimal) -> None:
		"""Initialize portfolio managers.

		M2-08: a single ``PortfolioStateStorage`` seam is injected here and shared
		by all four managers (mirroring how ``OrderManager`` receives an
		``OrderStorage`` from ``OrderStorageFactory.create(environment)``). The
		managers no longer own their state containers — they read/write through
		this seam. The backtest path uses the in-memory backend; live persistence
		is a pure backend swap (deferred to D-sql).
		"""
		self.state_storage: PortfolioStateStorage = PortfolioStateStorageFactory.create("backtest")
		self.cash_manager = CashManager(self, initial_cash=initial_cash)
		self.transaction_manager = TransactionManager(self)
		self.position_manager = PositionManager(self)
		self.metrics_manager = MetricsManager(self)

	def _validate_initial_state(self) -> None:
		"""Validate initial portfolio state."""
		if self.cash_manager.balance < 0:
			raise ValueError("Portfolio cannot start with negative cash")
		if not self.name.strip():
			raise ValueError("Portfolio name cannot be empty")

	def __str__(self) -> str:
		return f"Portfolio-{self.portfolio_id}[{self._state.value}]"

	def __repr__(self) -> str:
		return str(self)

	# State Management Methods
	@property
	def state(self) -> PortfolioState:
		"""Get current portfolio state."""
		return self._state
	
	def set_state(self, new_state: PortfolioState, reason: str = "") -> bool:
		"""Change portfolio state with validation."""
		if self._state == new_state:
			return False
			
		# Validate state transition
		if not self._is_valid_state_transition(self._state, new_state):
			raise ValueError(f"Invalid state transition from {self._state} to {new_state}")
			
		old_state = self._state
		self._state = new_state
		self._state_transitions.append((new_state, datetime.now(UTC)))
		self._health_metrics['state_changes'] += 1
			
		return True
	
	def _is_valid_state_transition(self, from_state: PortfolioState, to_state: PortfolioState) -> bool:
		"""Validate if state transition is allowed."""
		# ACTIVE can go to INACTIVE or ARCHIVED
		if from_state == PortfolioState.ACTIVE:
			return to_state in [PortfolioState.INACTIVE, PortfolioState.ARCHIVED]
		
		# INACTIVE can go to ACTIVE or ARCHIVED
		if from_state == PortfolioState.INACTIVE:
			return to_state in [PortfolioState.ACTIVE, PortfolioState.ARCHIVED]
		
		# ARCHIVED is terminal state (no transitions allowed)
		if from_state == PortfolioState.ARCHIVED:
			return False
		
		return False
	
	def is_active(self) -> bool:
		"""Check if portfolio is in active state."""
		return self.state == PortfolioState.ACTIVE
	
	def can_trade(self) -> bool:
		"""Check if portfolio can execute trades."""
		return self.state == PortfolioState.ACTIVE

	# Configuration Management
	def update_config(self, **kwargs: Any) -> None:
		"""Update portfolio configuration."""
		# Mapping for backward compatibility - maps old flat keys to new nested structure
		config_mapping = {
			'max_positions': ('limits', 'max_positions'),
			'max_position_value': ('limits', 'max_position_value'),
			'max_concentration_pct': ('risk_management', 'max_concentration_pct'),
			'max_daily_loss_pct': ('risk_management', 'max_daily_loss_pct'),
			'max_drawdown_pct': ('risk_management', 'max_drawdown_pct'),
			'max_transactions_per_day': ('trading_rules', 'max_transactions_per_day'),
			'max_cash_withdrawal_pct': ('trading_rules', 'max_cash_withdrawal_pct'),
			'validate_transactions': ('validation', 'validate_transactions'),
			'require_sufficient_funds': ('validation', 'require_sufficient_funds'),
			'publish_update_events': ('events', 'publish_update_events'),
			'publish_error_events': ('events', 'publish_error_events'),
		}
			
		for key, value in kwargs.items():
			if key in config_mapping:
				section_name, attr_name = config_mapping[key]
				section = getattr(self.config, section_name)
				setattr(section, attr_name, value)
			elif hasattr(self.config, key):
				setattr(self.config, key, value)
			else:
				raise ValueError(f"Unknown configuration key: {key}")
	
	def get_config_dict(self) -> Dict[str, Any]:
		"""Get configuration as dictionary."""
		return {
			'max_positions': self.config.limits.max_positions,
			'max_position_value': float(self.config.limits.max_position_value),
			'max_concentration_pct': self.config.risk_management.max_concentration_pct,
			'max_daily_loss_pct': self.config.risk_management.max_daily_loss_pct,
			'max_drawdown_pct': self.config.risk_management.max_drawdown_pct,
			'max_transactions_per_day': self.config.trading_rules.max_transactions_per_day,
			'max_cash_withdrawal_pct': self.config.trading_rules.max_cash_withdrawal_pct,
			'publish_update_events': self.config.events.publish_update_events,
			'publish_error_events': self.config.events.publish_error_events,
			'validate_transactions': self.config.validation.validate_transactions,
			'require_sufficient_funds': self.config.validation.require_sufficient_funds
		}

	# Read Properties (backward compatible; D-19 single-writer — no locks)
	@property
	def cash(self) -> Decimal:
		"""Get current cash balance as Decimal.

		M2-02: money is Decimal end-to-end on the cash path — the former
		float() cast on the ledger balance is removed so reading cash no longer
		round-trips money back to float.
		"""
		return self.cash_manager.balance

	# D-05 (Plan 05-05): the cash SETTER is deleted — every cash mutation goes
	# through an audited CashManager primitive (deposit/withdraw/fill flow);
	# the trade path applies cash via apply_fill_cash_flow in
	# process_transaction. Assigning portfolio.cash raises AttributeError.

	@property
	def n_open_positions(self) -> int:
		"""Obtain the number of open positions."""
		return len(self.position_manager.get_all_positions())

	@property
	def total_market_value(self) -> float:
		"""Get total market value excluding cash.

		Returned as float for the float-based consumers (order validator,
		metrics, reporting). The cash *ledger* is Decimal end-to-end (M2-02);
		routing these aggregates through Decimal is M4 scope.
		"""
		return float(self.position_manager.get_total_market_value())

	@property
	def total_equity(self) -> float:
		"""Get total equity including cash.

		Float for consumer compatibility (order-validator exposure ratios,
		metrics, reporting). cash is Decimal on the ledger (M2-02); coerce it at
		this read boundary so total_equity stays float for downstream consumers.
		"""
		return self.total_market_value + float(self.cash)

	@property
	def total_unrealised_pnl(self) -> float:
		"""Calculate unrealised P&L."""
		return float(self.position_manager.get_total_unrealized_pnl())

	@property
	def total_realised_pnl(self) -> float:
		"""Calculate realised P&L."""
		return float(self.position_manager.get_total_realized_pnl())

	@property
	def total_pnl(self) -> float:
		"""
		Calculate the sum of all the positions' total P&Ls.
		"""
		return self.total_unrealised_pnl + self.total_realised_pnl
	
	@property
	def positions(self) -> dict[str, Position]:
		"""Get open positions as a dictionary."""
		return self.position_manager.get_all_positions()
	
	@property
	def closed_positions(self) -> list[Position]:
		"""Get closed positions as a list."""
		return self.position_manager.get_closed_positions()
	
	@property
	def transactions(self) -> list[Transaction]:
		"""Get all transactions as a list."""
		return self.transaction_manager.get_transaction_history()

	def process_transaction(self, transaction: Transaction) -> None:
		"""
		Settle a fill atomically: validate-first, then mutate (D-09/D-12).

		The Portfolio orchestrates the settlement sequence under its own
		roof — each manager does exactly one concern, never touching a
		sibling. NOTHING mutates until all checks pass, so no rollback
		machinery is needed (a fill is a FACT; solvency was enforced
		pre-trade by the reservation gate):

		1. validate          — pure checks (TransactionManager, raises typed)
		2. funds invariant   — debit-side guard against BALANCE, never the
		                       reservation-adjusted buying power (D-10,
		                       Pitfall 2); never fires in the golden run
		3. position mutate   — first mutation (PositionManager)
		4. cash apply        — full-precision fill flow, ONE ledger entry
		                       with fee + event time (CashManager, D-05/D-06)
		5. record            — seam history append (TransactionManager, D-11)

		Returns ``None`` on success; raises typed domain exceptions on
		failure (D-10 — no bool channel). Backtest: the exception propagates
		to the Phase 4 ``_on_handler_error`` re-raise seam and the run stops
		loudly rather than producing corrupted numbers.
		"""
		# Update transaction with portfolio information
		transaction.portfolio_id = self.portfolio_id

		# 1. Pure validation — raises InvalidTransactionError, nothing mutated.
		self.transaction_manager.validate(transaction)

		# 2. Funds invariant on the debit side (D-10). The actual net cost is
		#    the entity's own cash math (Transaction.net_cash_delta) — the
		#    EXACT delta the interim seam computed (value preservation).
		net_delta = transaction.net_cash_delta
		if net_delta < 0:
			self.cash_manager.assert_funds_invariant(-net_delta)

		# 3. Position mutation (all checks passed; handles shorts properly).
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id

		# 4. Cash apply — full-precision signed delta, one ledger entry with
		#    fee field and event-derived timestamp (D-05/D-06, Pitfalls 1/5).
		self.cash_manager.apply_fill_cash_flow(
			amount=net_delta,
			fee=transaction.commission,
			description=f"Transaction {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id),
			timestamp=transaction.time,
		)

		# 5. Record — the applied Transaction entity IS the audit record (D-11).
		self.transaction_manager.record(transaction)

	def update_market_value(self, bar_event: BarEvent) -> None:
		"""
		Updates the value of all positions that are currently open.
		"""
		tickers = bar_event.bars.keys()
		current_prices: Dict[str, Any] = {}
		
		for ticker in tickers:
			current_price = bar_event.get_last_close(ticker)
			current_prices[ticker] = current_price
		
		# Update all positions with new prices
		self.position_manager.update_position_market_values(current_prices, bar_event.time)

	def record_metrics(self, time: datetime) -> None:
		"""Record portfolio metrics using the metrics manager."""
		self.metrics_manager.record_snapshot(time)

	def get_open_position(self, ticker: str) -> Any:
		"""Get an open position by ticker."""
		return self.position_manager.get_position(ticker)

	# Health and Validation
	def validate_health(self) -> Dict[str, Any]:
		"""Perform comprehensive health check."""
		health_report: Dict[str, Any] = {
			'portfolio_id': self.portfolio_id,
			'state': self.state.value,
			'is_healthy': True,
			'issues': [],
			'metrics': self._health_metrics.copy(),
			'timestamp': datetime.now(UTC).isoformat()
		}
			
		# Check cash consistency
		if self.cash_manager.balance < 0:
			health_report['is_healthy'] = False
			health_report['issues'].append('Negative cash balance')
			
		# Check position limits
		if self.n_open_positions > self.config.limits.max_positions:
			health_report['is_healthy'] = False
			health_report['issues'].append(f'Too many positions: {self.n_open_positions} > {self.config.limits.max_positions}')
			
		# Check concentration limits
		if self.total_equity > 0:
			max_position_pct = self._get_max_position_percentage()
			if max_position_pct > self.config.risk_management.max_concentration_pct:
				health_report['is_healthy'] = False
				health_report['issues'].append(f'Position concentration too high: {max_position_pct:.2%} > {self.config.risk_management.max_concentration_pct:.2%}')
			
		# Update health check timestamp
		self._health_metrics['last_health_check'] = datetime.now(UTC)
			
		return health_report
	
	def _get_max_position_percentage(self) -> float:
		"""Get the percentage of the largest position."""
		if self.total_equity <= 0:
			return 0.0
		
		positions = self.position_manager.get_all_positions()
		if not positions:
			return 0.0
		
		# pos.market_value is Decimal (M2a entity money); total_equity is float —
		# coerce to float for this reporting ratio.
		max_position_value = max(abs(float(pos.market_value)) for pos in positions.values())
		return max_position_value / self.total_equity
	
	# Enhanced Transaction Processing
	def transact_shares(self, transaction: Transaction) -> None:
		"""Execute transaction with state and config validation.

		D-10 contract: returns ``None`` on success, raises typed exceptions
		on failure — no bool channel (propagated from process_transaction).
		"""
		# Validate portfolio can trade
		if not self.can_trade():
			raise ValueError(f"Portfolio {self.portfolio_id} cannot trade in state {self.state}")

		# Validate against configuration
		if self.config.validation.validate_transactions:
			self._validate_transaction(transaction)

		# Update activity timestamp
		self._last_activity = datetime.now(UTC)

		# Delegate to the validate-first settlement sequence (D-12)
		try:
			self.process_transaction(transaction)
		except Exception:
			self._health_metrics['transaction_failures'] += 1
			raise
	
	def _validate_transaction(self, transaction: Transaction) -> None:
		"""Validate transaction against portfolio configuration."""
		# Check position limits
		if transaction.quantity > 0:  # Buy transaction
			if self.n_open_positions >= self.config.limits.max_positions:
				raise ValueError(f"Maximum positions limit reached: {self.config.limits.max_positions}")
			
			# Check position value limits
			transaction_value = abs(transaction.quantity * transaction.price)
			if transaction_value > self.config.limits.max_position_value:
				raise ValueError(f"Transaction value {transaction_value} exceeds limit {self.config.limits.max_position_value}")
	
	# Enhanced Market Value Update
	def update_market_value_of_portfolio(self, prices: Dict[str, float]) -> None:
		"""Update portfolio market values."""
		if not self.can_trade():
			return  # Skip updates for inactive portfolios
			
		self.position_manager.update_position_market_values(prices, datetime.now(UTC))
		self._last_activity = datetime.now(UTC)
	
	# Enhanced to_dict with new information
	def to_dict(self) -> Dict[str, Any]:
		"""Convert portfolio to dictionary."""
		base_dict = {
			'portfolio_id': self.portfolio_id,
			'id': self.portfolio_id,  # Keep backward compatibility
			'user_id': self.user_id,
			'name': self.name,
			'exchange': self.exchange,
			'creation_time': self.creation_time.isoformat(),
			'current_time': self.current_time.isoformat(),
			'state': self.state.value,
			'cash': self.cash,
			'available_cash': self.cash,  # Keep backward compatibility
			'total_market_value': self.total_market_value,
			'total_equity': self.total_equity,
			'n_open_positions': self.n_open_positions,
			'total_unrealised_pnl': self.total_unrealised_pnl,
			'total_realised_pnl': self.total_realised_pnl,
			'total_pnl': self.total_pnl,
			'config': self.get_config_dict(),
			'health_metrics': self._health_metrics.copy(),
			'last_activity': self._last_activity.isoformat()
		}
		return base_dict
