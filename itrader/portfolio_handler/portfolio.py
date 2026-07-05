from datetime import datetime, UTC
from typing import Optional, Dict, List, Any, Mapping
from decimal import Decimal

from itrader.portfolio_handler.transaction import Transaction
from itrader.portfolio_handler.position import Position
from itrader.events_handler.events import BarEvent
from itrader.config import PortfolioConfig, get_portfolio_preset, deep_merge

import pydantic
from itrader.core.enums import PortfolioState, PositionSide, TransactionType

# Import the new managers
from itrader.portfolio_handler.transaction.transaction_manager import TransactionManager
from itrader.portfolio_handler.position.position_manager import PositionManager
from itrader.portfolio_handler.account import Account, SimulatedCashAccount, SimulatedMarginAccount
from itrader.portfolio_handler.metrics.metrics_manager import MetricsManager
from itrader.portfolio_handler.storage import (
	PortfolioStateStorage,
	PortfolioStateStorageFactory,
)
from itrader.core.ids import PortfolioId
from itrader.core.exceptions.base import ValidationError, StateError, ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioError, InvalidTransactionError

from itrader import idgen


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

	def __init__(self, name: str, exchange: str, cash: Decimal, time: datetime,
	             config: Optional[PortfolioConfig] = None) -> None:
		"""
		Initialize enhanced portfolio with integrated capabilities.

		ACCT-04: the owning-user identity is NOT a Portfolio concern — it is an
		app-layer (FastAPI) mapping (owner -> portfolio) and is deliberately
		absent here; it is NOT relocated onto the Account either.
		"""
		# Core portfolio identity
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
		# D-03: the runtime enable_margin branch becomes leaf selection at wiring —
		# construct the account leaf the same way the four managers are built
		# (ACCT-01). enable_margin=False -> the verbatim-critical spot cash leaf
		# (SimulatedCashAccount, the SMA_MACD byte-exact oracle path, D-04);
		# enable_margin=True -> the margin superset. D-02: declared as the Account
		# ABC (the field IS the settlement contract, not a concretion) so the live
		# VenueAccount leaf wires in cleanly; margin-only call sites narrow to
		# SimulatedMarginAccount via _require_margin_account (isinstance guard).
		self.account: Account = (
			SimulatedMarginAccount(self, initial_cash=initial_cash)
			if self.config.trading_rules.enable_margin
			else SimulatedCashAccount(self, initial_cash=initial_cash)
		)
		self.transaction_manager = TransactionManager(self)
		self.position_manager = PositionManager(self)
		self.metrics_manager = MetricsManager(self)

	def _validate_initial_state(self) -> None:
		"""Validate initial portfolio state."""
		if self.account.balance < 0:
			# FL-01: input validation on the cash field at construction (not a
			# transaction funds-shortfall — InsufficientFundsError's
			# (required, available) shape does not fit a negative starting balance).
			raise ValidationError("cash", str(self.account.balance), "Portfolio cannot start with negative cash")
		if not self.name.strip():
			# FL-01: input validation on the name field at construction.
			raise ValidationError("name", message="Portfolio name cannot be empty")

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
			# FL-01: state-machine transition violation. self.portfolio_id is a
			# PortfolioId (uuid.UUID) satisfying StateError's entity_id type.
			raise StateError(self.portfolio_id, self._state.value, required_state=new_state.value, operation="set_state")
			
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
	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update portfolio configuration at runtime (D-07/D-08/D-09).

		Canonical contract: deep_merge -> model_validate -> atomic-swap, wrapping
		pydantic ``ValidationError`` (which also rejects unknown keys via
		``extra="forbid"``) into ``ConfigurationError``. Returns ``None`` and
		RAISES on failure. WR-04: the deep-merge preserves sibling submodel
		fields a partial nested update did not intend to change.
		"""
		merged = deep_merge(self.config.model_dump(), updates)
		try:
			new_config = PortfolioConfig.model_validate(merged)
		except pydantic.ValidationError as e:
			raise ConfigurationError(reason=str(e)) from e
		self.config = new_config  # atomic GIL-safe reference swap (D-11)
	
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

		ACCT-01: cash truth is delegated to the account leaf (a receiver-only
		re-point of the former cash-manager call; no math change).
		"""
		return self.account.balance

	# D-05 (Plan 05-05): the cash SETTER is deleted — every cash mutation goes
	# through an audited CashManager primitive (deposit/withdraw/fill flow);
	# the trade path applies cash via apply_fill_cash_flow in
	# process_transaction. Assigning portfolio.cash raises AttributeError.

	@property
	def n_open_positions(self) -> int:
		"""Obtain the number of open positions."""
		return len(self.position_manager.get_all_positions())

	@property
	def total_market_value(self) -> Decimal:
		"""Get total market value excluding cash, as Decimal.

		M5-10 (D-06): Decimal end-to-end on the result-bearing path — the
		position_manager aggregate is already Decimal, so this returns it
		unchanged with no float() narrowing at the property boundary.
		"""
		return self.position_manager.get_total_market_value()

	@property
	def total_equity(self) -> Decimal:
		"""Get total equity including cash, as Decimal.

		M5-10 (D-06): Decimal-native aggregation — total_market_value (Decimal)
		plus cash (Decimal). No float() cast: money stays Decimal end-to-end.
		"""
		return self.total_market_value + self.cash

	@property
	def total_unrealised_pnl(self) -> Decimal:
		"""Calculate unrealised P&L as Decimal (M5-10, D-06)."""
		return self.position_manager.get_total_unrealized_pnl()

	@property
	def total_realised_pnl(self) -> Decimal:
		"""Calculate realised P&L as Decimal (M5-10, D-06)."""
		return self.position_manager.get_total_realized_pnl()

	@property
	def total_pnl(self) -> Decimal:
		"""Sum of all positions' total P&Ls, as Decimal.

		M5-10 (D-06): Decimal+Decimal aggregation of the two pnl read-properties.
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

		# enable_margin gate (D-09): branch the settlement on the portfolio's
		# trading rules. The spot arm (False) is byte-exact site #2 — operand-
		# for-operand identical to today; the margin arm is lock-and-settle.
		if self.config.trading_rules.enable_margin:
			self._process_transaction_margin(transaction)
		else:
			self._process_transaction_spot(transaction)

	def _process_transaction_spot(self, transaction: Transaction) -> None:
		"""Spot settlement (enable_margin=False) — UNCHANGED, byte-exact site #2.

		Full notional debit via Transaction.net_cash_delta; nothing locked.
		This arm is operand-for-operand identical to the pre-margin code and
		MUST stay so (the SMA_MACD golden oracle, 134 / 46189.87730727451,
		regression-locks it). NO `/ leverage` ever touches this path (Pitfall 4).
		"""
		# OVERSELL-A / CR-02 (spot): fail loud on an over-close SELL BEFORE any
		# mutation — mirror of the margin guard at _process_transaction_margin
		# (portfolio.py:399-404). Root cause:
		# .planning/debug/spot-long-only-oversell.md — the spot path applied any
		# reducing fill UNCONDITIONALLY, so a SELL exceeding the held long settled
		# silently into a net-short inventory mislabeled side=LONG with phantom
		# positive market_value (the dangerous part: fail-fast did NOT trip). This
		# is the documented "byte-exact site #2"; the guard is DARK on the SMA_MACD
		# golden path (exits are clamped to net_quantity, so it never over-sells),
		# so the oracle stays byte-exact (134 / 46189.87730727451). No clamp —
		# match the margin path's fail-fast semantics (raise, never truncate).
		ticker = transaction.ticker
		prior = self.position_manager.get_position(ticker)
		prior_qty = abs(prior.net_quantity) if prior is not None else Decimal("0")
		# PERF-02 (D-02): capture realised PnL BEFORE the mutation so the
		# accumulator can be fed the realised increment after settling — mirrors
		# the margin arm's pre/post capture (portfolio.py:406/529). The spot path
		# is the SMA_MACD oracle path and has no explicit increment today, so it is
		# added here (03-INVARIANT-AUDIT.md §5). Open/scale-in yield increment 0.
		prior_realised = prior.realised_pnl if prior is not None else Decimal("0")
		# is_increase: a fill that moves in the position's OWN side.
		if prior is None:
			is_increase = True
		else:
			is_increase = (
				(prior.side == PositionSide.LONG and transaction.type == TransactionType.BUY)
				or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
			)
		# Raise ONLY on a GROSS over-sell — a real logic error (the 64-BTC
		# phantom-equity case from .planning/debug/spot-long-only-oversell.md,
		# guard origin: quick task 260623-gao). A sub-close-tolerance excess
		# (e.g. 1E-27 per-add bracket-child requantization on a pyramided
		# position) is Decimal quantization noise, NOT an over-sell — absorb it
		# as a clean full close: it passes here and `_should_close_position`
		# (abs(net) <= tolerance) settles the residual to flat (260623-h6i debug
		# session). Reuse the existing PositionManager.tolerance (1e-5).
		if not is_increase and (transaction.quantity - prior_qty) > self.position_manager.tolerance:
			raise InvalidTransactionError(
				"Spot close fill exceeds held quantity (over-sell not allowed — "
				"cannot sell more than owned in a spot portfolio)",
				{"closed": str(transaction.quantity), "open": str(prior_qty)},
			)

		# 2. Funds invariant on the debit side (D-10). The actual net cost is
		#    the entity's own cash math (Transaction.net_cash_delta) — the
		#    EXACT delta the interim seam computed (value preservation).
		net_delta = transaction.net_cash_delta
		if net_delta < 0:
			self.account.assert_funds_invariant(-net_delta)

		# 3. Position mutation (all checks passed; handles shorts properly).
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id

		# PERF-02 (D-02): feed the running realised-PnL accumulator the increment
		# from THIS fill. Decimal('0') on pure-open/scale-in (realised_pnl
		# unchanged), the realised delta on partial/full closes — applied
		# unconditionally (byte-safe; never gated behind a branch that could skip a
		# partial close). Facade->manager call; the manager keeps no back-reference.
		realised_increment = position.realised_pnl - prior_realised
		self.position_manager.apply_realised_increment(realised_increment)

		# 4. Cash apply — full-precision signed delta, one ledger entry with
		#    fee field and event-derived timestamp (D-05/D-06, Pitfalls 1/5).
		self.account.apply_fill_cash_flow(
			amount=net_delta,
			# spot-base-fee-drift-halt: the QUOTE-cash commission portion included in
			# ``net_delta`` (0 for a base-denominated fee, which is netted out of the
			# position quantity instead). Identity to transaction.commission on the
			# default / oracle path (byte-exact).
			fee=transaction.quote_commission,
			description=f"Transaction {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id),
			timestamp=transaction.time,
		)

		# 5. Record — the applied Transaction entity IS the audit record (D-11).
		self.transaction_manager.record(transaction)

	def _require_margin_account(self, operation: str) -> SimulatedMarginAccount:
		"""D-02: narrow ``self.account`` to the margin superset, or fail LOUD.

		Replaces the two bare ``cast(...)`` margin narrowings on ``self.account``
		(V17-14). A ``cast`` is a type-level no-op, so a venue-linked or
		cash-linked portfolio driven through a margin operation used to reach a
		margin-only method (``lock_margin`` / ``accrue_borrow_interest``) on a leaf
		that does not implement it — an ``AttributeError`` MID-settlement, AFTER the
		position had already mutated (the partial-mutation-on-margin hazard). This
		guard raises a typed ``StateError`` BEFORE any mutation instead, so a wrong
		account-type configuration fails at the boundary and never corrupts money
		state. Returns the narrowed margin account on the happy path.
		"""
		if not isinstance(self.account, SimulatedMarginAccount):
			raise StateError(
				self.portfolio_id,
				type(self.account).__name__,
				required_state=SimulatedMarginAccount.__name__,
				operation=operation,
			)
		return self.account

	def _process_transaction_margin(self, transaction: Transaction) -> None:
		"""Lock-and-settle margin settlement (enable_margin=True, D-09/D-11).

		The position-keyed locked-margin lifecycle is driven HERE (this method
		holds the returned Position + the CashManager); PositionManager stays
		cash-agnostic (OQ2). Four observed transitions, dispatched by comparing
		the position state captured BEFORE the mutation against the result:

		* OPEN (no prior position): lock `aggregate_notional / L`, debit ONLY
		  the commission (D-08, Pitfall 3 — NEVER the full notional, T-02-11).
		* SCALE-IN (same-direction add): recompute the lock to the new
		  `aggregate_notional / L` (release old, lock new), debit ONLY commission.
		* PARTIAL CLOSE (opposite-direction reduce, still open): release the
		  closed fraction `p` of the lock (recompute to the remaining
		  `aggregate_notional / L`), settle `p × realized_PnL` + re-credit the
		  closed fraction's pre-debited open commission (D-11).
		* FULL CLOSE (position closed): release the whole lock, settle the
		  realized PnL (which already nets commissions, so re-credit the open
		  commission once → round-trip cash delta == realized PnL).

		Decimal end-to-end, full precision (no intermediate quantize). The lock
		basis `aggregate_notional / L` rides the margin arm ONLY — the spot arm
		never divides (Pitfall 4).
		"""
		# D-03/ACCT-02: this arm is reached ONLY when enable_margin=True, so the
		# account leaf is the margin superset — narrow to its margin surface
		# (lock_margin / release_margin / assert_lock_fits_buying_power). D-02: the
		# narrowing is a runtime isinstance guard (not a bare cast), raising a typed
		# StateError BEFORE any mutation if the account is not a margin leaf (closes
		# the V17-14 partial-mutation hazard). The spot byte-exact path
		# (_process_transaction_spot) never enters here, so this is dark on the
		# SMA_MACD oracle.
		account = self._require_margin_account("process_transaction_margin")
		ticker = transaction.ticker

		# Capture pre-mutation state for the transition classification.
		prior = self.position_manager.get_position(ticker)
		prior_qty = abs(prior.net_quantity) if prior is not None else Decimal("0")
		prior_realised = prior.realised_pnl if prior is not None else Decimal("0")
		# Entry-side commission already pre-debited at open (LONG -> buy side,
		# SHORT -> sell side); used to avoid double-counting it on close.
		if prior is not None:
			prior_entry_commission = (
				prior.buy_commission if prior.side == PositionSide.LONG
				else prior.sell_commission
			)
		else:
			prior_entry_commission = Decimal("0")

		# Is this fill increasing the position (open / scale-in) or reducing it
		# (partial / full close)? An increase moves in the position's own side.
		if prior is None:
			is_increase = True
		else:
			is_increase = (
				(prior.side == PositionSide.LONG and transaction.type == TransactionType.BUY)
				or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
			)

		# CR-02 (Phase-2 mitigation): fail loud on an over-close / flip fill.
		# A reducing fill (not an increase) whose quantity EXCEEDS the open
		# quantity would leave a residual flipped position; the close arm below
		# clamps closed_qty but reads realised_increment after the FULL
		# transaction.quantity mutated the position, re-locking margin on a
		# flipped position at the original side's leverage and settling a wrong
		# cash delta. Reject it BEFORE any mutation/settlement. The full
		# flip-settlement economics (split into full-close + fresh-open) are a
		# Phase-3 (shorts) concern, where flips become reachable.
		# Raise ONLY on a GROSS over-close — a real flip (the 64-BTC
		# phantom-equity logic error, .planning/debug/spot-long-only-oversell.md;
		# spot guard origin: quick task 260623-gao). A sub-close-tolerance excess
		# (1E-27 per-add bracket-child requantization on a pyramided position) is
		# Decimal quantization noise, NOT a flip — absorb it as a clean full
		# close: it passes here and `_should_close_position` (abs(net) <=
		# tolerance) settles the residual to flat (260623-h6i debug session).
		# Reuse the existing PositionManager.tolerance (1e-5).
		if not is_increase and (transaction.quantity - prior_qty) > self.position_manager.tolerance:
			raise InvalidTransactionError(
				"Margin close fill exceeds open quantity (flip not supported "
				"in Phase 2 — tracked for Phase 3 shorts)",
				{"closed": str(transaction.quantity), "open": str(prior_qty)},
			)

		# Funds invariant (D-10/OQ3): in margin mode the open/scale debit is
		# ONLY the commission, so feed the invariant the commission-only delta
		# (locked-margin sufficiency was enforced pre-trade by the admission
		# reservation gate, Plan 02-03). Commission is always non-negative.
		commission = transaction.commission
		if is_increase and commission > 0:
			account.assert_funds_invariant(commission)

		# Position mutation (all checks passed; handles shorts properly).
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id

		# D-06: the position carries the authoritative ONE effective leverage
		# (a scale-in's differing signal leverage was clamped). The lock basis
		# ALWAYS uses position.leverage, never the transaction's leverage.
		leverage = position.leverage

		if is_increase:
			# OPEN or SCALE-IN: recompute the lock to the (new) aggregate
			# notional / L; debit ONLY the commission.
			# WR-03 (T-03-16): release THEN re-lock is symmetric — release returns
			# the position's own prior lock (0 on a fresh open; the prior
			# aggregate lock on a scale-in), and lock_margin replaces it. No
			# un-paired lock can leak because the key is the same position id.
			new_lock = position.aggregate_notional / leverage
			# WR-01 (T-03-15): settlement-side solvency assertion — the lock must
			# fit buying power, which credits back the position's OWN prior lock.
			# WR-04 (Plan 04-02): assert BEFORE release so the assertion's add-back
			# (``get_locked_margin_for``) reads the TRUE prior lock, not ``0``.
			# Releasing first pops this position's lock, which the assertion is
			# documented to credit back — running the guard while the prior lock is
			# still present is the correct call order. Fail loud BEFORE applying the
			# new lock — never silently over-lock.
			account.assert_lock_fits_buying_power(new_lock, str(position.id))
			account.release_margin(str(position.id))
			account.lock_margin(str(position.id), new_lock)
			cash_delta = -commission
		else:
			# PARTIAL or FULL CLOSE. Closed fraction p of the prior position.
			closed_qty = transaction.quantity
			if closed_qty > prior_qty:
				closed_qty = prior_qty
			fraction = (closed_qty / prior_qty) if prior_qty > 0 else Decimal("0")

			# Re-lock the remaining (0 on a full close — position.is_open is
			# False and aggregate_notional is 0), then release the prior whole
			# lock. WR-03 (T-03-16): the release/re-lock pair stays symmetric on
			# the same position key — the remaining lock replaces the released one.
			if position.is_open:
				remaining_lock = position.aggregate_notional / leverage
				# WR-01 (T-03-15) / WR-04 (Plan 04-02): assert BEFORE release so
				# the recomputed remaining lock is checked against buying power
				# that still credits the position's TRUE prior whole lock (the
				# add-back reads ``get_locked_margin_for``, not ``0``).
				account.assert_lock_fits_buying_power(
					remaining_lock, str(position.id)
				)
				account.release_margin(str(position.id))
				account.lock_margin(str(position.id), remaining_lock)
			else:
				account.release_margin(str(position.id))

			# Settle the realized-PnL increment for the closed portion. The
			# position's realised_pnl already nets BOTH commissions; the open
			# commission for the closed fraction was already debited at open, so
			# re-credit it to avoid double-count — the round-trip cash delta then
			# equals the realized PnL exactly.
			#
			# WR-05 (T-03-16): re-credit the EXACT open commission the realised
			# increment charged for THIS closed portion, tracked as a per-lock
			# accumulator (``_open_commission_settled`` below). The prior
			# ``fraction × prior_entry_commission`` proxy (fraction = closed_qty /
			# net_qty) drifts from realised_pnl's own open-commission term
			# (charged as closed_qty / total_open_qty) after a non-uniform-
			# commission scale-in or a staged partial close, because the
			# denominators differ once net_qty < total open qty. The accumulator
			# settles against the actual realised-pnl open-commission term, so the
			# cumulative round-trip cash delta == realized PnL with NO drift.
			realised_increment = position.realised_pnl - prior_realised
			# PERF-02 (D-02): feed the running realised-PnL accumulator the SAME
			# realised increment already computed here for the cash settle. CLOSE
			# arm ONLY — the is_increase open/scale-in branch never changes
			# realised_pnl (03-INVARIANT-AUDIT.md §4). Facade->manager call.
			self.position_manager.apply_realised_increment(realised_increment)
			open_commission_credit = self._open_commission_credit_for_close(
				position, closed_qty
			)
			cash_delta = realised_increment + open_commission_credit

		# ONE ledger entry: signed cash delta + the commission fee field +
		# event-derived timestamp (D-06, Pitfalls 1/5).
		account.apply_fill_cash_flow(
			amount=cash_delta,
			fee=commission,
			description=f"Margin {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id),
			timestamp=transaction.time,
		)

		# Record — the applied Transaction entity IS the audit record (D-11).
		self.transaction_manager.record(transaction)

	def update_market_value(self, bar_event: BarEvent) -> None:
		"""
		Updates the value of all positions that are currently open.
		"""
		# Close-marked equity (D-05): the Bar struct's close is already
		# Decimal (D-14); a ticker with no bar at T is absent from the dict.
		current_prices: Dict[str, Any] = {}

		for ticker, bar in bar_event.bars.items():
			current_prices[ticker] = bar.close

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
		if self.account.balance < 0:
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

		# M5-10: total_equity is now Decimal end-to-end. pos.market_value is
		# Decimal (M2a entity money) — keep the ratio Decimal-native (no
		# float/Decimal mix), then coerce only the final reporting ratio to float.
		# IN-03: trust the Decimal source — no defensive Decimal(str(...)) wrap
		# (which would silently mask a stray-float type regression).
		max_position_value = max(abs(pos.market_value) for pos in positions.values())
		return float(max_position_value / self.total_equity)
	
	# Enhanced Transaction Processing
	def transact_shares(self, transaction: Transaction) -> None:
		"""Execute transaction with state and config validation.

		D-10 contract: returns ``None`` on success, raises typed exceptions
		on failure — no bool channel (propagated from process_transaction).
		"""
		# Validate portfolio can trade
		if not self.can_trade():
			# FL-01: cannot trade in the current state — state-machine guard.
			raise StateError(self.portfolio_id, self.state.value, required_state=PortfolioState.ACTIVE.value, operation="transact_shares")

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
		# Check position limits — gate the OPEN/GROW checks on the transaction
		# TYPE, not the magnitude (WR-01): quantity is always a positive magnitude
		# (direction rides transaction.type), so `quantity > 0` was ALWAYS true and
		# wrongly ran the buy-only limits for closing SELLs — blocking exits at the
		# position cap (and, in live, failing settlement into a drift-halt).
		if transaction.type == TransactionType.BUY:
			if self.n_open_positions >= self.config.limits.max_positions:
				# FL-01: domain limit breach (not state/field validation) — PortfolioError base.
				raise PortfolioError(f"Maximum positions limit reached: {self.config.limits.max_positions}")

			# Check position value limits
			transaction_value = abs(transaction.quantity * transaction.price)
			if transaction_value > self.config.limits.max_position_value:
				# FL-01: domain limit breach — PortfolioError base.
				raise PortfolioError(f"Transaction value {transaction_value} exceeds limit {self.config.limits.max_position_value}")
	
	# Enhanced Market Value Update
	def update_market_value_of_portfolio(self, prices: Mapping[str, float | Decimal],
			bar_time: Optional[datetime] = None, universe: Any = None) -> None:
		"""Update portfolio market values, then accrue per-bar short carry (CARRY-01).

		``bar_time`` is the bar's BUSINESS time threaded down from
		``PortfolioHandler.update_portfolios_market_value`` (D-04 — the carry
		days basis and the carry op timestamp derive from it, NEVER
		``datetime.now(UTC)``; a wall-clock stamp breaks the determinism
		double-run gate). It defaults to ``None`` for legacy callers that only
		mark; in that case the mark falls back to the wall clock and no carry
		accrues (no bar time, no days basis).

		``universe`` is the injected ``Universe`` read-model used to resolve each
		open short's ``Instrument.borrow_rate`` (D-01), mirroring the
		``maintenance_margin`` read pattern in ``PortfolioHandler``. With no
		``universe`` (or ``borrow_rate == 0`` / no open shorts) nothing accrues
		and SMA_MACD stays byte-exact under default-off.
		"""
		if not self.can_trade():
			return  # Skip updates for inactive portfolios

		# D-04: mark positions at the bar's business time, NOT the wall clock,
		# so the equity curve is deterministic. Legacy mark-only callers (no
		# bar_time) keep the prior wall-clock behaviour.
		mark_time = bar_time if bar_time is not None else datetime.now(UTC)
		self.position_manager.update_position_market_values(prices, mark_time)

		# CARRY-01: accrue per-bar borrow interest on every OPEN SHORT (D-02/D-03/
		# D-08). Skipped entirely when carry can't apply (no bar time / no
		# universe) — the default-off no-op that keeps the oracle byte-exact.
		# WR-02 (T-03-17): the carry borrow_rate read (``universe.instrument(...)``
		# inside ``_accrue_short_carry``) is reached ONLY when ``universe is not
		# None``, so it can never hit the bare ``AttributeError`` the
		# ``maintenance_margin`` site exposed — it is None-safe by construction.
		# A legacy mark-only caller (no universe) leaves carry as a silent no-op,
		# which is the correct default-off behaviour (SMA_MACD byte-exact). The
		# fail-loud universe-unwired guard lives at the ``maintenance_margin`` read
		# in ``PortfolioHandler`` (the actual deferred WR-02 site).
		if bar_time is not None and universe is not None:
			# CR-01: only shorts whose ticker was actually re-marked this tick
			# (price present in `prices`) may accrue carry — a short absent from
			# this tick's prices keeps a STALE current_price, so accruing on it
			# books financing against a wrong mark. The marked set IS the keys of
			# `prices` (position_manager updates `if ticker in price_data`).
			marked_tickers = set(prices.keys())
			self._accrue_short_carry(bar_time, universe, marked_tickers)

		self._last_activity = mark_time

	def _accrue_short_carry(self, bar_time: datetime, universe: Any,
			marked_tickers: set[str]) -> None:
		"""Accrue per-bar borrow interest on every open short (CARRY-01).

		For each OPEN SHORT, debit
		``days × close × |net_quantity| × borrow_rate / Decimal("365")``
		(Decimal end-to-end — ``borrow_rate`` is already Decimal; NEVER
		``Decimal(float)``) from realized cash via a ``BORROW_INTEREST``
		``CashOperation``. ``days`` = ``(bar_time − last_accrual)`` from the bar's
		BUSINESS time (D-04). The per-short ``last_accrual`` advances to
		``bar_time`` after debiting (it seeds from the position entry date). LONG
		positions and ``borrow_rate == 0`` accrue nothing. Carry NEVER folds into
		``Position.realised_pnl`` (D-08 — clean trade PnL; carry nets at cash).

		``marked_tickers`` is the set of tickers actually re-marked this tick (the
		keys of ``prices``). CR-01: a short whose ticker is absent from it carries a
		STALE ``current_price``, so its accrual is SKIPPED and its clock is NOT
		advanced — the next priced bar then accrues the full elapsed interval on a
		correct mark. WR-02: a ticker the Universe no longer carries an Instrument
		for fails LOUD with a ``StateError`` (mirroring ``maintenance_margin``).
		WR-03: a non-positive ``current_price`` is skipped (never a wrong debit).
		WR-05: the ``borrow_rate == 0`` branch is a plain ``continue`` — no
		clock-advance (the frozen-Instrument static-rate contract).
		"""
		positions = self.position_manager.get_all_positions()
		for ticker, position in positions.items():
			if position.side != PositionSide.SHORT or not position.is_open:
				continue

			# CR-01: no fresh mark this tick (ticker absent from `prices`) —
			# defer carry; do NOT advance the clock, so the next priced bar
			# accrues the full elapsed interval on a correct price.
			if ticker not in marked_tickers:
				continue

			# WR-03: defend the money operand. A zero/unset mark must never
			# silently produce a wrong financing debit — skip rather than book
			# carry on a non-positive price.
			if position.current_price <= Decimal("0"):
				continue

			# WR-02: resolve the Instrument via the injected Universe. A short on
			# a ticker the Universe no longer carries an Instrument for raises a
			# bare KeyError that would abort the run with an opaque message — fail
			# LOUD with a context-rich StateError instead, mirroring the
			# maintenance_margin universe guard in PortfolioHandler.
			try:
				borrow_rate = universe.instrument(ticker).borrow_rate
			except KeyError as exc:
				raise StateError(
					position.id,
					"instrument-missing",
					required_state=f"universe carries Instrument for {ticker}",
					operation="accrue_short_carry",
				) from exc
			if borrow_rate == Decimal("0"):
				# WR-05: no clock-advance. Instrument is frozen and borrow_rate is
				# static-over-time, so the rate can never transition 0 -> non-zero
				# within a run — advancing the clock here was dead rationale and
				# would suppress carry across a transition if the type ever changed.
				continue

			# D-04 days basis from the bar gap (seed from the position entry).
			last_accrual = position._last_accrual_time or position.entry_date
			elapsed_seconds = Decimal(str((bar_time - last_accrual).total_seconds()))
			days = elapsed_seconds / Decimal("86400")
			if days <= Decimal("0"):
				continue

			carry = (
				days
				* position.current_price
				* abs(position.net_quantity)
				* borrow_rate
				/ Decimal("365")
			)
			# ACCT-02: borrow carry is a margin-only surface. This loop body is
			# reached only for an OPEN SHORT with a non-zero borrow_rate (a margin
			# concept); the account is therefore the margin superset here. D-02: the
			# narrowing is a runtime isinstance guard raising a typed StateError
			# BEFORE the accrual mutation if the leaf is not a margin account — never
			# reached on the LONG-only spot oracle.
			self._require_margin_account("accrue_borrow_interest").accrue_borrow_interest(
				amount=carry,
				reference_id=str(position.id),
				description=f"Borrow interest {ticker}",
				timestamp=bar_time,
			)
			position._last_accrual_time = bar_time

	def _open_commission_credit_for_close(
		self, position: Position, closed_qty: Decimal
	) -> Decimal:
		"""WR-05 (T-03-16): the EXACT open commission to re-credit for a close.

		``realised_pnl`` deducts the entry-side commission proportionally to the
		closed fraction of the OPENING side's total quantity:

		* LONG  close: ``(sell_quantity / buy_quantity)  × buy_commission``
		* SHORT close: ``(buy_quantity  / sell_quantity) × sell_commission``

		Settling the realised increment therefore re-introduces the open
		commission for the closed portion as ``(closed_qty / open_side_qty) ×
		open_side_commission``. Re-crediting EXACTLY that term cancels the
		double-count so the round-trip cash delta equals realized PnL — even
		after a non-uniform-commission scale-in or staged partial close, where
		the legacy ``closed_qty / net_quantity`` proxy drifts (the denominators
		diverge once ``net_quantity < open_side_qty``). Decimal end-to-end.
		"""
		if position.side == PositionSide.LONG:
			open_side_qty = position.buy_quantity
			open_side_commission = position.buy_commission
		else:  # SHORT
			open_side_qty = position.sell_quantity
			open_side_commission = position.sell_commission
		if open_side_qty == Decimal("0"):
			return Decimal("0")
		return (closed_qty / open_side_qty) * open_side_commission


	# Enhanced to_dict with new information
	def to_dict(self) -> Dict[str, Any]:
		"""Convert portfolio to dictionary."""
		base_dict = {
			'portfolio_id': self.portfolio_id,
			'id': self.portfolio_id,  # Keep backward compatibility
			'name': self.name,
			'exchange': self.exchange,
			'creation_time': self.creation_time.isoformat(),
			'current_time': self.current_time.isoformat(),
			'state': self.state.value,
			'cash': self.cash,
			# WR-07: the reservation gate is live (Plan 05-06) — available is
			# a real, distinct figure (total - reserved), the D-14 single
			# trading-decision figure. Reporting total here would inflate
			# buying power by the sum of outstanding reservations.
			'available_cash': self.account.available_balance,
			'reserved_cash': self.account.reserved_balance,
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
