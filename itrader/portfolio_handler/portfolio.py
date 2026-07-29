from datetime import datetime, UTC
from typing import Optional, Dict, Any, Mapping, TYPE_CHECKING
from decimal import Decimal

from itrader.portfolio_handler.transaction import Transaction
from itrader.portfolio_handler.position import Position
from itrader.events_handler.events import BarEvent
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.config.portfolio import IMMUTABLE_PORTFOLIO_CONFIG_KEYS
from itrader.outils.dict_merge import recursive_merge

import pydantic
from itrader.core.enums import PortfolioState, PositionSide, TransactionType

from itrader.portfolio_handler.transaction.transaction_manager import TransactionManager
from itrader.portfolio_handler.position.position_manager import PositionManager
# ``SimulatedMarginAccount`` is a NARROWING type only, for the isinstance guard in
# ``_require_margin_account`` — this module mints no account.
from itrader.portfolio_handler.account import Account, SimulatedMarginAccount
from itrader.portfolio_handler.metrics.metrics_manager import MetricsManager
from itrader.portfolio_handler.storage import (
	PortfolioStateStorage,
	PortfolioStateStorageFactory,
)
from itrader.core.ids import PortfolioId
from itrader.core.exceptions.base import ValidationError, StateError, ConfigurationError
from itrader.core.exceptions.portfolio import (
	PortfolioError,
	InvalidTransactionError,
	ImmutableConfigKeyError,
)

from itrader import idgen

if TYPE_CHECKING:
	# Annotation-only: a runtime import would pull SQLAlchemy onto the backtest path.
	from itrader.storage import SqlEngine


def _reject_immutable_config_keys(node: Any) -> None:
	"""Refuse an update payload naming an immutable config key at ANY depth.

	Walks the payload rather than checking top-level keys because ``recursive_merge``
	accepts nested blobs — a top-level-only check is bypassable by nesting the key
	inside its section.

	Raises ``ImmutableConfigKeyError``; returns ``None`` when the payload is clean.
	"""
	if isinstance(node, list):
		for item in node:
			_reject_immutable_config_keys(item)
		return

	if not isinstance(node, dict):
		return

	for key, value in node.items():
		if key in IMMUTABLE_PORTFOLIO_CONFIG_KEYS:
			raise ImmutableConfigKeyError(key=str(key))
		_reject_immutable_config_keys(value)


class Portfolio(object):
	"""Self-contained portfolio: state, config, positions, cash and health.

	Single-writer contract: ALL portfolio state mutations happen on the engine
	thread; queue.Queue is the thread boundary — other threads only put events.
	Composite reads are consistent because nothing mutates concurrently, which is
	why there is no lock here.
	"""

	def __init__(self, name: str, exchange: str, cash: Decimal, time: datetime,
	             config: Optional[PortfolioConfig] = None,
	             environment: str = "backtest",
	             sql_engine: "Optional[SqlEngine]" = None,
	             portfolio_id: Optional[PortfolioId] = None,
	             account_id: Optional[str] = None,
	             venue_name: Optional[str] = None,
	             *,
	             account: Account) -> None:
		"""Initialize the portfolio.

		The owning-user identity is NOT a Portfolio concern — it is an app-layer
		(FastAPI) owner -> portfolio mapping, deliberately absent here and not
		relocated onto the Account either.

		``environment`` + ``sql_engine`` select the state-storage backend built in
		``_init_managers``: "backtest" is the in-memory oracle path, "live" + the shared
		``SqlEngine`` persists to the durable SQL ledger keyed by ``portfolio_id``.

		Parameters
		----------
		portfolio_id : Optional[PortfolioId]
			An EXISTING id to reattach to on rehydrate; supplying it — rather than
			regenerating — is what makes durable state survive a process restart. A freshly
			minted id orphans the prior run's portfolio-scoped rows and dangles the
			persisted strategy-subscription rows. ``None`` mints a fresh UUIDv7 via the
			single ``idgen`` singleton.
		account_id : Optional[str]
			The venue account this portfolio's orders reach. It defaults ONLY so the
			byte-exact backtest call site stays untouched.
		venue_name : Optional[str]
			The venue half of the ``(venue_name, account_id)`` account reference and the
			SOURCE OF TRUTH for the portfolio's exchange: when supplied, ``self.exchange``
			is DERIVED from it, because storing the venue twice creates two sources of
			truth that can drift once orders are routed per-account. ``exchange`` is used
			as-is only when ``venue_name`` is absent, never alongside it.
		account : Account
			The BUILT settlement leaf, constructed by the venue plugin's ``new_account`` —
			the SOLE account factory — and supplied by ``PortfolioFactory.materialize``,
			which holds the ``PortfolioConfig`` the margin-vs-cash selection reads;
			``Portfolio`` selects no account kind.

			REQUIRED and keyword-only WITHOUT a default: a default would be a
			mint-on-omission path, and every construction site that forgot to pass one
			would silently receive the wrong account KIND instead of a ``TypeError``.
		"""
		self.portfolio_id: PortfolioId = (
			portfolio_id if portfolio_id is not None
			else PortfolioId(idgen.generate_portfolio_id())
		)
		self.name = name
		# ``account_id`` / ``venue_name`` are not stored here — they are read-only
		# properties over ``self.account``, the ONE storage site for the pair.
		self.exchange = venue_name if venue_name is not None else exchange
		self.creation_time = time
		self.current_time = time
		
		self.config = config or get_portfolio_preset('default')
		
		self._state = PortfolioState.ACTIVE
		self._state_transitions = [(PortfolioState.ACTIVE, time)]
		self._last_activity = time
		
		# No lock: single-writer contract, see class docstring.

		# Set BEFORE _init_managers, which builds self.state_storage from these.
		self._environment = environment
		self._sql_engine = sql_engine

		self._health_metrics: Dict[str, Any] = {
			'last_health_check': time,
			'validation_errors': 0,
			'transaction_failures': 0,
			'state_changes': 1
		}
		
		self._init_managers(account)
		self._validate_initial_state(cash)
	
	def _init_managers(self, account: Account) -> None:
		"""Bind the RECEIVED account and build the three portfolio managers.

		The account is RECEIVED, never minted: ``VenuePlugin.new_account`` is the sole
		owner of the margin-vs-cash selection rule. The field stays declared as the
		``Account`` ABC so any leaf wires cleanly; margin-only
		call sites narrow via ``_require_margin_account``.

		**The state-storage seam is ADOPTED from the account when it carries one, and
		that direction is load-bearing.** The account is built BEFORE the portfolio
		exists, so a portfolio that built its own backend here would leave the leaf on a
		private one. Nothing else in the tree reads the leaf's three containers (reserved
		cash, locked margin, the cash-operation audit trail), so the split is invisible
		in backtest and the oracle stays green — while in live the restart path
		(``state_storage.rehydrate(account)``) repopulates those caches on THIS object
		and every reservation is silently lost across a restart.

		The environment/sql_engine/portfolio_id factory is the FALLBACK, for a leaf that
		exposes no seam of its own (a venue-truth account, whose balance lives at the
		venue).
		"""
		account_seam = getattr(account, "state_storage", None)
		self.state_storage: PortfolioStateStorage = (
			account_seam if account_seam is not None
			else PortfolioStateStorageFactory.create(
				self._environment,
				sql_engine=self._sql_engine,
				portfolio_id=self.portfolio_id,
			)
		)
		self.account: Account = account
		self.transaction_manager = TransactionManager(self)
		self.position_manager = PositionManager(self)
		self.metrics_manager = MetricsManager(self)

	@property
	def venue_name(self) -> Optional[str]:
		"""The venue this portfolio's account belongs to.

		Read-only over ``self.account``, the ONE storage site for the
		``(venue_name, account_id)`` pair — two storage sites for one identity is how a
		portfolio's idea of its account drifts from the leaf's own. No setter.
		"""
		return self.account.venue_name

	@property
	def account_id(self) -> Optional[str]:
		"""The venue account this portfolio's orders reach.

		Read-only over ``self.account``; see ``venue_name`` for the drift rationale.
		"""
		return self.account.account_id

	def _validate_initial_state(self, cash: float | Decimal) -> None:
		"""Refuse a portfolio whose opening cash disagrees with its account's balance.

		``PortfolioFactory.materialize`` computes ``to_money(cash)`` once and passes it
		to both sides; without this check a caller that supplies one value to the
		portfolio and another to the account factory gets a portfolio whose reported
		opening cash and whose ledger disagree, with nothing red.

		The check is UNCONDITIONAL. It used to be skipped for accounts that declared
		themselves venue-truth, on the grounds that their balance came from the venue
		rather than from a wiring value — but every account a portfolio is constructed with
		reports a readable opening balance, so there is no longer a kind of account for
		which "the supplied cash and the account's balance need not agree" is true. An
		account whose balance is unreadable at construction cannot be a construction-time
		leaf at all, which is a separate and louder failure.

		The expected value ASKS the account how it rounds cash
		(``Account.quantize_cash``) rather than re-deriving the scale: both sides of
		this exact-equality check are built across a domain boundary, and when each
		spelled the scale out for itself a one-sided change made every portfolio
		construction raise — including the oracle path.
		"""
		account = self.account
		expected = account.quantize_cash(cash)
		if account.balance != expected:
			raise ValidationError(
				"account",
				str(account.balance),
				f"The supplied account opens at {account.balance} but the "
				f"portfolio was asked to open at {expected}; the account's "
				"initial_cash and the portfolio's cash must be the SAME value",
				)
		if self.account.balance < 0:
			# FL-01: input validation, not a transaction funds-shortfall —
			# InsufficientFundsError's (required, available) shape does not fit here.
			raise ValidationError("cash", str(self.account.balance), "Portfolio cannot start with negative cash")
		if not self.name.strip():
			# FL-01: input validation on the name field at construction.
			raise ValidationError("name", message="Portfolio name cannot be empty")

	def __str__(self) -> str:
		return f"Portfolio-{self.portfolio_id}[{self._state.value}]"

	def __repr__(self) -> str:
		return str(self)

	@property
	def state(self) -> PortfolioState:
		return self._state
	
	def set_state(self, new_state: PortfolioState, reason: str = "") -> bool:
		"""Change portfolio state, validating the transition.

		Returns ``False`` when the portfolio is already in ``new_state``; raises
		``StateError`` on an illegal transition.
		"""
		if self._state == new_state:
			return False
			
		if not self._is_valid_state_transition(self._state, new_state):
			# FL-01: state-machine transition violation.
			raise StateError(self.portfolio_id, self._state.value, required_state=new_state.value, operation="set_state")
			
		old_state = self._state
		self._state = new_state
		self._state_transitions.append((new_state, datetime.now(UTC)))
		self._health_metrics['state_changes'] += 1
			
		return True
	
	def _is_valid_state_transition(self, from_state: PortfolioState, to_state: PortfolioState) -> bool:
		if from_state == PortfolioState.ACTIVE:
			return to_state in [PortfolioState.INACTIVE, PortfolioState.ARCHIVED]
		
		if from_state == PortfolioState.INACTIVE:
			return to_state in [PortfolioState.ACTIVE, PortfolioState.ARCHIVED]
		
		if from_state == PortfolioState.ARCHIVED:
			return False
		
		return False
	
	def is_active(self) -> bool:
		return self.state == PortfolioState.ACTIVE
	
	def can_trade(self) -> bool:
		return self.state == PortfolioState.ACTIVE

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update portfolio configuration at runtime.

		recursive_merge -> model_validate -> atomic swap, wrapping pydantic
		``ValidationError`` (which also rejects unknown keys via ``extra="forbid"``)
		into ``ConfigurationError``. The deep-merge preserves sibling submodel fields a
		partial nested update did not intend to change.

		An immutable key is refused BEFORE the merge, so ``self.config`` is never
		partially mutated. This duplicates a refusal ``ConfigRouter`` already makes: the
		router is the QUEUE-FACING gate and cannot see a caller reaching this method
		directly. Both layers read ``IMMUTABLE_PORTFOLIO_CONFIG_KEYS``, so they cannot
		drift apart.
		"""
		_reject_immutable_config_keys(updates)
		merged = recursive_merge(self.config.model_dump(), updates)
		try:
			new_config = PortfolioConfig.model_validate(merged)
		except pydantic.ValidationError as e:
			raise ConfigurationError(reason=str(e)) from e
		self.config = new_config  # atomic GIL-safe reference swap
	
	def get_config_dict(self) -> Dict[str, Any]:
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

	@property
	def cash(self) -> Decimal:
		"""Current cash balance, delegated to the account leaf."""
		return self.account.balance

	# There is deliberately NO cash setter: every cash mutation goes through an
	# audited Account primitive (deposit / withdraw / apply_fill_cash_flow), so
	# assigning portfolio.cash raises AttributeError.

	@property
	def n_open_positions(self) -> int:
		return len(self.position_manager.get_all_positions())

	@property
	def total_market_value(self) -> Decimal:
		"""Total market value excluding cash."""
		return self.position_manager.get_total_market_value()

	@property
	def total_equity(self) -> Decimal:
		"""Total equity including cash."""
		return self.total_market_value + self.cash

	@property
	def total_unrealised_pnl(self) -> Decimal:
		return self.position_manager.get_total_unrealized_pnl()

	@property
	def total_realised_pnl(self) -> Decimal:
		return self.position_manager.get_total_realized_pnl()

	@property
	def total_pnl(self) -> Decimal:
		"""Unrealised plus realised P&L."""
		return self.total_unrealised_pnl + self.total_realised_pnl
	
	@property
	def positions(self) -> dict[str, Position]:
		return self.position_manager.get_all_positions()
	
	@property
	def closed_positions(self) -> list[Position]:
		return self.position_manager.get_closed_positions()
	
	@property
	def transactions(self) -> list[Transaction]:
		return self.transaction_manager.get_transaction_history()

	def process_transaction(self, transaction: Transaction) -> None:
		"""Settle a fill atomically: validate-first, then mutate.

		NOTHING mutates until all checks pass, so no rollback machinery is needed (a
		fill is a FACT; solvency was enforced pre-trade by the reservation gate). The
		ORDER is the invariant:

		1. validate        — pure checks (TransactionManager, raises typed)
		2. funds invariant — debit-side guard against BALANCE, never the
		                     reservation-adjusted buying power
		3. position mutate — first mutation (PositionManager)
		4. cash apply      — full-precision fill flow, ONE ledger entry with fee
		                     + event time
		5. record          — seam history append (TransactionManager)

		Raises typed domain exceptions on failure — no bool channel. In backtest the
		exception propagates to the ``FailFastPolicy`` re-raise seam and the run stops
		loudly rather than producing corrupted numbers.
		"""
		transaction.portfolio_id = self.portfolio_id

		# 1. Pure validation — nothing mutated.
		self.transaction_manager.validate(transaction)

		# The spot arm (enable_margin=False) is the byte-exact oracle path; the margin
		# arm is lock-and-settle.
		if self.config.trading_rules.enable_margin:
			self._process_transaction_margin(transaction)
		else:
			self._process_transaction_spot(transaction)

	def _process_transaction_spot(self, transaction: Transaction) -> None:
		"""Spot settlement (enable_margin=False) — the byte-exact oracle path.

		Full notional debit via ``Transaction.net_cash_delta``; nothing locked. The
		SMA_MACD golden oracle (134 / 46189.87730727451) regression-locks this arm
		operand-for-operand — NO ``/ leverage`` ever touches this path.
		"""
		# Fail loud on an over-close SELL BEFORE any mutation. Without it a SELL
		# exceeding the held long settles silently into a net-short inventory
		# mislabeled side=LONG with phantom positive market_value — and, the dangerous
		# part, fail-fast does NOT trip. DARK on the SMA_MACD golden path (exits are
		# clamped to net_quantity), so the oracle stays byte-exact. No clamp: raise,
		# never truncate.
		ticker = transaction.ticker
		prior = self.position_manager.get_position(ticker)
		prior_qty = abs(prior.net_quantity) if prior is not None else Decimal("0")
		# Capture realised PnL BEFORE the mutation so the accumulator can be fed the
		# increment after settling. Open/scale-in yield an increment of 0.
		prior_realised = prior.realised_pnl if prior is not None else Decimal("0")
		# is_increase: a fill that moves in the position's OWN side.
		if prior is None:
			is_increase = True
		else:
			is_increase = (
				(prior.side == PositionSide.LONG and transaction.type == TransactionType.BUY)
				or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
			)
		# Raise ONLY on a GROSS over-sell. A sub-tolerance excess (1E-27 per-add
		# bracket-child requantization on a pyramided position) is Decimal quantization
		# noise, NOT an over-sell: it passes here and `_should_close_position`
		# (abs(net) <= PositionManager.tolerance) settles the residual flat.
		if not is_increase and (transaction.quantity - prior_qty) > self.position_manager.tolerance:
			raise InvalidTransactionError(
				"Spot close fill exceeds held quantity (over-sell not allowed — "
				"cannot sell more than owned in a spot portfolio)",
				{"closed": str(transaction.quantity), "open": str(prior_qty)},
			)

		# 2. Funds invariant on the debit side (Transaction.net_cash_delta).
		net_delta = transaction.net_cash_delta
		if net_delta < 0:
			self.account.assert_funds_invariant(-net_delta)

		# 3. Position mutation — all checks passed.
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id

		# Feed the accumulator the increment from THIS fill. Applied unconditionally —
		# never gated behind a branch that could skip a partial close.
		realised_increment = position.realised_pnl - prior_realised
		self.position_manager.apply_realised_increment(realised_increment)

		# 4. Cash apply — full-precision signed delta, one ledger entry.
		self.account.apply_fill_cash_flow(
			amount=net_delta,
			# The QUOTE-cash commission portion already inside ``net_delta`` (0 for a
			# base-denominated fee, which is netted out of the position quantity
			# instead). Identical to transaction.commission on the oracle path.
			fee=transaction.quote_commission,
			description=f"Transaction {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id),
			timestamp=transaction.time,
		)

		# 5. Record — the applied Transaction entity IS the audit record.
		self.transaction_manager.record(transaction)

	def _require_margin_account(self, operation: str) -> SimulatedMarginAccount:
		"""Narrow ``self.account`` to the margin superset, or fail LOUD.

		A runtime guard, NOT a ``cast``: a ``cast`` is a type-level no-op, so a
		venue-linked or cash-linked portfolio driven through a margin operation would
		reach a margin-only method (``lock_margin`` / ``accrue_borrow_interest``) on a
		leaf that does not implement it — an ``AttributeError`` MID-settlement, AFTER
		the position had already mutated. This raises a typed ``StateError`` BEFORE any
		mutation instead, so a wrong account-type configuration never corrupts money
		state.
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
		"""Lock-and-settle margin settlement (enable_margin=True).

		The position-keyed locked-margin lifecycle is driven HERE (this method holds the
		returned Position + the margin ``Account``); PositionManager stays cash-agnostic.
		Four transitions, dispatched by comparing the position state captured BEFORE the
		mutation against the result:

		* OPEN (no prior position): lock `aggregate_notional / L`, debit ONLY the
		  commission — NEVER the full notional.
		* SCALE-IN (same-direction add): recompute the lock to the new
		  `aggregate_notional / L` (release old, lock new), debit ONLY commission.
		* PARTIAL CLOSE (opposite-direction reduce, still open): release the closed
		  fraction `p` of the lock, settle `p × realized_PnL` + re-credit the closed
		  fraction's pre-debited open commission.
		* FULL CLOSE: release the whole lock, settle the realized PnL (which already
		  nets commissions, so re-credit the open commission once → round-trip cash
		  delta == realized PnL).

		Decimal end-to-end, full precision (no intermediate quantize). The lock basis
		`aggregate_notional / L` rides the margin arm ONLY — the spot arm never divides.
		"""
		# enable_margin=True, so the leaf is the margin superset — narrow to it. Dark
		# on the SMA_MACD oracle, which never enters this arm.
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

		# An increase moves in the position's OWN side (open / scale-in).
		if prior is None:
			is_increase = True
		else:
			is_increase = (
				(prior.side == PositionSide.LONG and transaction.type == TransactionType.BUY)
				or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
			)

		# Fail loud on an over-close / flip fill BEFORE any mutation. A reducing fill
		# exceeding the open quantity would leave a residual flipped position: the close
		# arm clamps closed_qty but reads realised_increment after the FULL
		# transaction.quantity mutated the position, re-locking margin at the ORIGINAL
		# side's leverage and settling a wrong cash delta. Raise ONLY on a GROSS
		# over-close — a sub-tolerance excess is Decimal quantization noise, absorbed as
		# a clean full close by `_should_close_position`.
		if not is_increase and (transaction.quantity - prior_qty) > self.position_manager.tolerance:
			raise InvalidTransactionError(
				"Margin close fill exceeds open quantity (flip not supported "
				"in Phase 2 — tracked for Phase 3 shorts)",
				{"closed": str(transaction.quantity), "open": str(prior_qty)},
			)

		# In margin mode the open/scale debit is ONLY the commission — locked-margin
		# sufficiency was enforced pre-trade by the admission reservation gate.
		commission = transaction.commission
		if is_increase and commission > 0:
			account.assert_funds_invariant(commission)

		# Position mutation — all checks passed.
		position = self.position_manager.process_position_update(transaction)
		transaction.position_id = position.id

		# The lock basis ALWAYS uses position.leverage (the authoritative ONE effective
		# leverage — a scale-in's differing signal leverage was clamped), never the
		# transaction's.
		leverage = position.leverage

		if is_increase:
			# OPEN or SCALE-IN: recompute the lock to the (new) aggregate notional / L;
			# debit ONLY the commission. Release THEN re-lock is symmetric — no un-paired
			# lock can leak because the key is the same position id.
			new_lock = position.aggregate_notional / leverage
			# Assert BEFORE release so the add-back (``get_locked_margin_for``) reads the
			# TRUE prior lock, not ``0`` — releasing first pops the very lock the assertion
			# credits back. Fail loud before applying the new lock; never over-lock.
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

			# Re-lock the remaining, then release the prior whole lock. The pair stays
			# symmetric on the same position key.
			if position.is_open:
				remaining_lock = position.aggregate_notional / leverage
				# Assert BEFORE release — same ordering as the increase arm.
				account.assert_lock_fits_buying_power(
					remaining_lock, str(position.id)
				)
				account.release_margin(str(position.id))
				account.lock_margin(str(position.id), remaining_lock)
			else:
				account.release_margin(str(position.id))

			# Settle the realized-PnL increment for the closed portion. realised_pnl
			# already nets BOTH commissions and the open commission for the closed
			# fraction was debited at open, so re-crediting exactly that term makes the
			# round-trip cash delta equal the realized PnL.
			realised_increment = position.realised_pnl - prior_realised
			# CLOSE arm ONLY — the is_increase branch never changes realised_pnl.
			self.position_manager.apply_realised_increment(realised_increment)
			open_commission_credit = self._open_commission_credit_for_close(
				position, closed_qty
			)
			cash_delta = realised_increment + open_commission_credit

		# ONE ledger entry: signed cash delta + commission fee + event-derived time.
		account.apply_fill_cash_flow(
			amount=cash_delta,
			fee=commission,
			description=f"Margin {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id),
			timestamp=transaction.time,
		)

		# Record — the applied Transaction entity IS the audit record.
		self.transaction_manager.record(transaction)

	def update_market_value(self, bar_event: BarEvent) -> None:
		"""Mark every open position at this bar's close."""
		# The Bar struct's close is already Decimal; a ticker with no bar at T is absent.
		current_prices: Dict[str, Any] = {}

		for ticker, bar in bar_event.bars.items():
			current_prices[ticker] = bar.close

		self.position_manager.update_position_market_values(current_prices, bar_event.time)

	def record_metrics(self, time: datetime) -> None:
		self.metrics_manager.record_snapshot(time)

	def get_open_position(self, ticker: str) -> Any:
		return self.position_manager.get_position(ticker)

	def validate_health(self) -> Dict[str, Any]:
		"""Health check: negative cash, position count, concentration."""
		health_report: Dict[str, Any] = {
			'portfolio_id': self.portfolio_id,
			'state': self.state.value,
			'is_healthy': True,
			'issues': [],
			'metrics': self._health_metrics.copy(),
			'timestamp': datetime.now(UTC).isoformat()
		}
			
		if self.account.balance < 0:
			health_report['is_healthy'] = False
			health_report['issues'].append('Negative cash balance')
			
		if self.n_open_positions > self.config.limits.max_positions:
			health_report['is_healthy'] = False
			health_report['issues'].append(f'Too many positions: {self.n_open_positions} > {self.config.limits.max_positions}')
			
		if self.total_equity > 0:
			max_position_pct = self._get_max_position_percentage()
			if max_position_pct > self.config.risk_management.max_concentration_pct:
				health_report['is_healthy'] = False
				health_report['issues'].append(f'Position concentration too high: {max_position_pct:.2%} > {self.config.risk_management.max_concentration_pct:.2%}')
			
		self._health_metrics['last_health_check'] = datetime.now(UTC)
			
		return health_report
	
	def _get_max_position_percentage(self) -> float:
		if self.total_equity <= 0:
			return 0.0

		positions = self.position_manager.get_all_positions()
		if not positions:
			return 0.0

		# Decimal-native ratio, float only at the reporting edge. No defensive
		# Decimal(str(...)) wrap — it would silently mask a stray-float regression.
		max_position_value = max(abs(pos.market_value) for pos in positions.values())
		return float(max_position_value / self.total_equity)
	
	def transact_shares(self, transaction: Transaction) -> None:
		"""Execute a transaction after state + config validation; raises on failure."""
		if not self.can_trade():
			# FL-01: cannot trade in the current state — state-machine guard.
			raise StateError(self.portfolio_id, self.state.value, required_state=PortfolioState.ACTIVE.value, operation="transact_shares")

		if self.config.validation.validate_transactions:
			self._validate_transaction(transaction)

		self._last_activity = datetime.now(UTC)

		try:
			self.process_transaction(transaction)
		except Exception:
			self._health_metrics['transaction_failures'] += 1
			raise
	
	def _validate_transaction(self, transaction: Transaction) -> None:
		# Gate the OPEN/GROW checks on the transaction TYPE, not the magnitude: quantity
		# is always a positive magnitude (direction rides transaction.type), so a
		# `quantity > 0` gate is ALWAYS true and runs the buy-only limits for closing
		# SELLs too — blocking exits at the position cap.
		if transaction.type == TransactionType.BUY:
			if self.n_open_positions >= self.config.limits.max_positions:
				# FL-01: domain limit breach (not state/field validation) — PortfolioError base.
				raise PortfolioError(f"Maximum positions limit reached: {self.config.limits.max_positions}")

			transaction_value = abs(transaction.quantity * transaction.price)
			if transaction_value > self.config.limits.max_position_value:
				# FL-01: domain limit breach — PortfolioError base.
				raise PortfolioError(f"Transaction value {transaction_value} exceeds limit {self.config.limits.max_position_value}")
	
	def update_market_value_of_portfolio(self, prices: Mapping[str, float | Decimal],
			bar_time: Optional[datetime] = None, universe: Any = None) -> None:
		"""Update portfolio market values, then accrue per-bar short carry.

		``bar_time`` is the bar's BUSINESS time threaded down from
		``PortfolioHandler.update_portfolios_market_value``. The carry days basis and
		the carry op timestamp derive from it, NEVER ``datetime.now(UTC)`` — a
		wall-clock stamp breaks the determinism double-run gate. ``None`` (legacy
		mark-only callers) falls back to the wall clock and accrues no carry.

		``universe`` is the injected ``Universe`` read-model resolving each open short's
		``Instrument.borrow_rate``. With no ``universe`` (or ``borrow_rate == 0`` / no
		open shorts) nothing accrues and SMA_MACD stays byte-exact.
		"""
		if not self.can_trade():
			return  # Skip updates for inactive portfolios

		mark_time = bar_time if bar_time is not None else datetime.now(UTC)
		self.position_manager.update_position_market_values(prices, mark_time)

		# The borrow_rate read inside ``_accrue_short_carry`` is reached ONLY when
		# ``universe is not None``, so it is None-safe by construction.
		if bar_time is not None and universe is not None:
			# Only shorts re-marked this tick may accrue: a short absent from `prices`
			# keeps a STALE current_price, so carry would book against a wrong mark.
			marked_tickers = set(prices.keys())
			self._accrue_short_carry(bar_time, universe, marked_tickers)

		self._last_activity = mark_time

	def _accrue_short_carry(self, bar_time: datetime, universe: Any,
			marked_tickers: set[str]) -> None:
		"""Accrue per-bar borrow interest on every open short.

		For each OPEN SHORT, debit
		``days × close × |net_quantity| × borrow_rate / Decimal("365")``
		(Decimal end-to-end — ``borrow_rate`` is already Decimal; NEVER
		``Decimal(float)``) from realized cash via a ``BORROW_INTEREST``
		``CashOperation``. ``days`` = ``(bar_time − last_accrual)`` from the bar's
		BUSINESS time; the per-short ``last_accrual`` advances to ``bar_time`` after
		debiting (seeded from the position entry date). LONG positions and
		``borrow_rate == 0`` accrue nothing. Carry NEVER folds into
		``Position.realised_pnl`` — clean trade PnL; carry nets at cash.

		``marked_tickers`` is the set of tickers actually re-marked this tick. Four skip
		rules: a short absent from it carries a STALE ``current_price``, so its accrual
		is SKIPPED and its clock is NOT advanced (the next priced bar accrues the full
		elapsed interval on a correct mark); a ticker the Universe no longer carries an
		Instrument for fails LOUD with a ``StateError``; a non-positive
		``current_price`` is skipped; and ``borrow_rate == 0`` is a plain ``continue``
		with no clock-advance.
		"""
		positions = self.position_manager.get_all_positions()
		for ticker, position in positions.items():
			if position.side != PositionSide.SHORT or not position.is_open:
				continue

			# No fresh mark — defer carry and do NOT advance the clock.
			if ticker not in marked_tickers:
				continue

			# A zero/unset mark must never silently produce a wrong financing debit.
			if position.current_price <= Decimal("0"):
				continue

			# A bare KeyError here would abort the run with an opaque message — fail LOUD
			# with a context-rich StateError instead.
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
				# No clock-advance: Instrument is frozen so borrow_rate can never go
				# 0 -> non-zero within a run, but advancing here would suppress carry across
				# such a transition if the type ever stopped being frozen.
				continue

			# Days basis from the bar gap (seed from the position entry).
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
			# Borrow carry is a margin-only surface — never reached on the LONG-only spot
			# oracle. The narrowing raises BEFORE the accrual mutation.
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
		"""The EXACT open commission to re-credit for a close.

		``realised_pnl`` deducts the entry-side commission proportionally to the
		closed fraction of the OPENING side's total quantity:

		* LONG  close: ``(sell_quantity / buy_quantity)  × buy_commission``
		* SHORT close: ``(buy_quantity  / sell_quantity) × sell_commission``

		Settling the realised increment therefore re-introduces the open
		commission for the closed portion as ``(closed_qty / open_side_qty) ×
		open_side_commission``. Re-crediting EXACTLY that term cancels the
		double-count so the round-trip cash delta equals realized PnL — even after a
		non-uniform-commission scale-in or staged partial close, where a
		``closed_qty / net_quantity`` proxy drifts (the denominators diverge once
		``net_quantity < open_side_qty``). Decimal end-to-end.
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


	def to_dict(self) -> Dict[str, Any]:
		base_dict = {
			'portfolio_id': self.portfolio_id,
			'id': self.portfolio_id,  # Keep backward compatibility
			'name': self.name,
			'exchange': self.exchange,
			'creation_time': self.creation_time.isoformat(),
			'current_time': self.current_time.isoformat(),
			'state': self.state.value,
			'cash': self.cash,
			# `available` (total - reserved) is the trading-decision figure; reporting
			# total here would inflate buying power by outstanding reservations.
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
