from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import BarEvent, FillEvent, OrderEvent
from itrader.core.enums.execution import ExecutionErrorCode
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.config import ExchangeConfig
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.logger import get_itrader_logger
# Declared ONCE in ``venues/registry.py`` — which imports nothing at runtime, so
# this re-export pulls in no concretion — and re-exported here, the historical
# import path. Their full rationale lives at the declaration.
from itrader.venues.registry import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
	# TYPING-ONLY so no portfolio-domain module lands on this import graph: the
	# queue-only cross-domain contract forbids importing PortfolioHandler, and the
	# injected read-model is the sanctioned exception for READS.
	from itrader.core.portfolio_read_model import PortfolioReadModel


# mypy --strict disables implicit re-export, so the two venue constants above must
# be named explicitly to stay importable from this module.
__all__ = ['COMPUTE_VENUE', 'DEFAULT_ACCOUNT_ID', 'ExecutionHandler',
		   'default_exchange_config', 'seed_exchange_registry']


def default_exchange_config() -> ExchangeConfig:
	"""Build the DEFAULT-PRESET exchange config: preset symbols UNION ``{BTCUSD}``.

	This is the FALLBACK for callers that have NO run-derived config — the live
	root and the direct-construction test sites — and never the preferred source.
	The factory's run-derived config folds THIS run's complete ticker set into
	``limits.supported_symbols``; a default preset silently narrows the tradeable
	symbol set and the failure surfaces as refused orders far from its cause.
	"""
	config = ExchangeConfig.default()
	config.limits.supported_symbols = set(config.limits.supported_symbols) | {'BTCUSD'}
	return config


def seed_exchange_registry(
	exchange_registry: dict[tuple[str, str], Optional[AbstractExchange]],
	venue_bundles: Any,
) -> None:
	"""Seed the PAPER exchange into the shared registry and connect it.

	The composition root seeds the paper arm here and hands the SAME map to BOTH
	``ExecutionHandler`` (which READS it on order) and ``VenueAccountManager``
	(whose ``bring_online`` WRITES the OKX arm into it). One map held by reference
	by both arms is what makes a brought-online account immediately routable
	without the manager reaching through the handler to register an exchange.

	Only the PAPER arm is seeded. The OKX arm is registered by the live root's
	per-account ``bring_online`` loop, which knows the account set this seam has no
	way to enumerate.

	``venue_bundles`` is duck-typed ``Any`` (GATE-01): naming ``VenueBundles``
	concretely would drag the venue substrate back onto this module's import graph.
	"""
	logger = get_itrader_logger().bind(component="ExecutionHandler")
	# ASK the shared memo rather than minting one here; ``spec=None`` because
	# ``PaperVenuePlugin.build_bundle`` reads no spec field at all.
	bundle = venue_bundles.get(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID, None)
	exchange_registry[(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)] = bundle.exchange

	# Dedup by instance identity: two keys may resolve to one object (two ACCOUNTS
	# on one venue), and connecting it once avoids a misleading second "Successfully
	# connected" log for the idempotent no-op call.
	seen_connect: set[int] = set()
	for exchange_key, exchange in exchange_registry.items():
		if exchange is None or id(exchange) in seen_connect:
			continue
		seen_connect.add(id(exchange))
		exchange_name = exchange_key[0]
		try:
			connection_result = exchange.connect()
			if connection_result.success:
				logger.info('Successfully connected to %s exchange', exchange_name)
			else:
				logger.warning('Failed to connect to %s exchange: %s',
							   exchange_name, connection_result.error_message)
		except AttributeError:
			logger.debug('Exchange %s does not support connection management', exchange_name)


class ExecutionHandler(AbstractExecutionHandler):
	"""Route each ``OrderEvent`` to the exchange holding its account's session, and
	drive resting-order matching on every registered exchange with each new bar.
	"""

	def __init__(self, global_queue: "EventBus", *,
				exchange_registry: dict[tuple[str, str], Optional[AbstractExchange]],
				portfolio_read_model: Optional["PortfolioReadModel"] = None) -> None:
		"""
		Parameters
		----------
		global_queue: `EventBus`
			The events queue of the trading system
		exchange_registry: `dict[tuple[str, str], Optional[AbstractExchange]]`
			The composition-root-owned ``(venue, account_id) -> exchange`` map, held by
			reference: ``VenueAccountManager.bring_online`` writes the venue-truth (OKX)
			arm into the SAME object this handler reads on order.

			It is REQUIRED, not ``Optional[...] = None``: a nullable seam here would
			let a caller silently hold a private, empty map while the manager wrote a
			different one, and every live order would then fail closed on a lookup
			miss without anything turning red.
		portfolio_read_model: `PortfolioReadModel`, optional
			Resolves an order's VENUE ACCOUNT from its portfolio. The injection is
			ASYMMETRIC by design, and the asymmetry is the point:

			* the BACKTEST composition root passes NOTHING, so ``on_order``
			  resolves ``DEFAULT_ACCOUNT_ID`` unconditionally and the
			  byte-exact oracle route is untouched;
			* the LIVE composition root passes the portfolio handler (which
			  satisfies the Protocol structurally), so every live order is
			  routed to the exchange holding THAT account's authenticated
			  session.

			When it IS injected, ``account_for`` returning ``None`` is a LOUD
			REFUSAL — the order is not submitted. It must NEVER be written as
			``account_for(...) or DEFAULT_ACCOUNT_ID``: that is the most
			natural-looking repair and it routes a live portfolio that names no
			account through whatever session is registered as the default
			(MPORT-07). The guard against that state is upstream and
			composition-time — ``VenueAccountManager.assert_available`` refuses to
			bring a portfolio naming no account online — so this handler's only
			job is to fail closed and signal.
		"""
		self.logger = get_itrader_logger().bind(component="ExecutionHandler")

		self.global_queue = global_queue
		self._portfolio_read_model = portfolio_read_model

		self.exchanges: dict[tuple[str, str], Optional[AbstractExchange]] = exchange_registry

		self.logger.info('Execution Handler initialized (exchange registry injected)')

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update execution configuration at runtime.

		The handler owns no Pydantic config model of its own; the execution config
		lives on the exchange, so this routes the partial update to the simulated
		exchange's canonical ``update_config`` (recursive_merge -> model_validate ->
		atomic-swap), keeping the single web-catchable raise contract.

		Raises
		------
		ConfigurationError
			On any validation failure, and when no paper exchange is wired.
		"""
		exchange = self.exchanges.get((COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key=COMPUTE_VENUE,
				reason='no paper exchange wired to update')
		exchange.update_config(updates)

	def validate_config(self, updates: Dict[str, Any]) -> None:
		"""Dry-validate a partial config update WITHOUT applying it.

		Mirrors ``update_config`` but runs the exchange's dry twin
		(``SimulatedExchange.validate_config``): recursive_merge -> model_validate on a
		THROWAWAY copy — no atomic swap, no cache re-derivation. ``ConfigRouter`` calls
		this BEFORE persisting a venue fee/slippage value so an invalid value never
		lands in ``VenueStore``; a poisoned row would otherwise brick the next boot's
		restart-layering.

		Raises
		------
		ConfigurationError
			On any validation failure, and when no paper exchange is wired.
		"""
		exchange = self.exchanges.get((COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key=COMPUTE_VENUE,
				reason='no paper exchange wired to update')
		exchange.validate_config(updates)


	def on_order(self, event: OrderEvent) -> None:
		"""Route an order to the exchange holding its account's session.

		The routing target is the ``(venue, account_id)`` PAIR, never the bare venue
		name. Without the account half, two portfolios trading one venue under
		different accounts both resolve to one exchange object and account B's orders
		are submitted through account A's authenticated session (MPORT-07).

		Every failure path is FAIL-CLOSED — unknown portfolio, unnamed account or
		unregistered pair logs, emits a REFUSED fill and returns. There is
		deliberately NO fallback to a bare-venue-name lookup: submitting through a
		guessed session is strictly worse than not submitting.
		"""
		# Unknown-portfolio gets its OWN branch: account_for reads through
		# get_portfolio, so a bad portfolio_id raises. Letting the broad handler below
		# catch it would log the misleading "Unexpected error routing order" and make a
		# caller error look like an internal fault.
		try:
			account_id = self._resolve_account_id(event)
		except PortfolioNotFoundError:
			self.logger.error(
				'Unknown portfolio %s on order %s %s — order NOT submitted',
				event.portfolio_id, event.ticker, event.action)
			# FAIL CLOSED VISIBLY: the REFUSED fill makes the drop observable in the
			# event stream and reconciles the order mirror out of PENDING, instead of
			# vanishing while get_status() reports RUNNING / errors_count 0. The log and
			# the event serve different audiences; keep both.
			self.global_queue.put(FillEvent.new_fill(
				'REFUSED', event, price=event.price, quantity=event.quantity,
				commission=Decimal("0"),
				error_code=ExecutionErrorCode.UNKNOWN_PORTFOLIO))
			return

		try:
			# A None account_id (a portfolio naming no account) can never match a
			# (str, str) registry key, so it falls through to the pair-miss refusal
			# below rather than getting its own branch — and never a
			# DEFAULT_ACCOUNT_ID coercion, which is the MPORT-07 defect itself.
			exchange = (self.exchanges.get((event.exchange, account_id))
						if account_id is not None else None)
			if not exchange:
				self.logger.error(
					'No exchange registered for venue/account (%s, %s) — order %s %s '
					'NOT submitted', event.exchange, account_id,
					event.ticker, event.action)
				# FAIL CLOSED VISIBLY with a distinct error code. A bare-venue fallback
				# here would route through another account's session (MPORT-07). In a
				# correctly-composed LIVE system account_id is never None here —
				# VenueAccountManager.assert_available refuses to bring a portfolio
				# naming no account online.
				self.global_queue.put(FillEvent.new_fill(
					'REFUSED', event, price=event.price, quantity=event.quantity,
					commission=Decimal("0"),
					error_code=ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT))
				return
			exchange.on_order(event)
		except Exception as e:
			self.logger.error('Unexpected error routing order for %s %s: %s',
							 event.ticker, event.action, str(e), exc_info=True)

	def _resolve_account_id(self, event: OrderEvent) -> Optional[str]:
		"""Resolve the venue account half of the routing key.

		With NO read-model injected there is exactly one account — the backtest path
		— so the default constant is correct and unconditional. With one injected,
		the portfolio's own account is authoritative and a ``None`` answer is
		propagated as a refusal, never coerced.
		"""
		if self._portfolio_read_model is None:
			return DEFAULT_ACCOUNT_ID
		return self._portfolio_read_model.account_for(event.portfolio_id)

	def on_market_data(self, bar: BarEvent) -> None:
		"""Drive resting-order matching on each exchange with a new bar."""
		# Dedup by instance identity: the same exchange object may be registered under
		# two ACCOUNTS of one venue and must still be driven exactly once per bar, or
		# its resting-order book is matched twice.
		#
		# It stays IDENTITY-based — do NOT "clean it up" into a key- or name-based
		# dedup. Two accounts holding DISTINCT exchange objects are correctly driven
		# separately (each owns its own resting-order book and correlation index and
		# must see every bar); a key-based rewrite would drive a shared exchange twice
		# per bar and silently change every backtest number.
		seen: set[int] = set()
		for key, exchange in self.exchanges.items():
			if exchange is None or id(exchange) in seen:
				continue
			seen.add(id(exchange))
			try:
				exchange.on_market_data(bar)
			except Exception as e:
				self.logger.error('Error matching resting orders on venue/account %s: %s',
								 key, str(e), exc_info=True)

	def get_exchange_health(self, exchange_name: Optional[str] = None) -> dict[str, Any]:
		"""
		Get health status for one or all exchanges.

		Parameters
		----------
		exchange_name : str, optional
			VENUE name to check. If None, checks all registered exchanges. The
			registry is keyed on ``(venue, account_id)`` but this parameter stays a
			plain VENUE string and matches every pair whose venue half equals it —
			tuple-keyed health input/output is operator-hostile and no caller needs it.

		Returns
		-------
		dict
			Health status per exchange, keyed by venue name for the single-account
			(default) case and by ``"venue:account"`` only when a venue has a
			non-default account, so multi-account output stays lossless. That display
			key is NEVER persisted — ``Order.exchange`` keeps the bare venue name.
		"""
		health_data: dict[str, Any] = {}

		keys_to_check = [key for key in self.exchanges
						 if exchange_name is None or key[0] == exchange_name]

		for key in keys_to_check:
			venue, account_id = key
			name = venue if account_id == DEFAULT_ACCOUNT_ID else f'{venue}:{account_id}'
			exchange = self.exchanges.get(key)
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
