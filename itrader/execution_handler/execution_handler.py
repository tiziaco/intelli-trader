from typing import TYPE_CHECKING, Any, Dict, Optional

from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import BarEvent, FillEvent, OrderEvent
# Still needed by update_config / validate_config, which isinstance-NARROW against
# the simulated exchange. Nothing in this module constructs one any more (D-06).
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.config import ExchangeConfig
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.logger import get_itrader_logger
from itrader.venues.bundles import VenueBundles
# 11.1-09 — RE-EXPORTED from the import-inert venue substrate.
# ``DEFAULT_ACCOUNT_ID`` (the single-account key half, D-27/MPORT-07) and
# ``COMPUTE_VENUE`` (``'paper'``, D-05) are venue-domain facts that BOTH handlers
# need: this one resolves its exchange under them, and ``PortfolioHandler`` mints
# every portfolio's construction-time compute leaf under them. They are declared
# ONCE in ``venues/registry.py`` — which imports nothing at runtime, so this pulls
# no concretion — and re-exported here so every existing
# ``from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID``
# keeps working. Their full rationale lives at the declaration.
from itrader.venues.registry import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
	# Read-model seam only (D-27): the Protocol is imported for TYPING ONLY so
	# nothing from the portfolio domain lands on this module's import graph.
	# The execution handler must NEVER import PortfolioHandler — the queue-only
	# cross-domain contract governs handler-to-handler access and the injected
	# read-model is the sanctioned exception for READS.
	from itrader.core.portfolio_read_model import PortfolioReadModel


# mypy --strict disables implicit re-export, so the two venue constants above are
# named explicitly here to stay importable from this module (their historical home).
__all__ = ['COMPUTE_VENUE', 'DEFAULT_ACCOUNT_ID', 'ExecutionHandler', 'default_exchange_config']


def default_exchange_config() -> ExchangeConfig:
	"""Build the DEFAULT-PRESET exchange config (D-13, Trap 1; D-17).

	Reproduces the historical direct-construction symbol set byte-exactly: the
	default preset symbols UNION ``{BTCUSD}`` (the union the removed hardcoded
	BTCUSD registration used to produce). Seeded at construction so it is
	replacement-safe — a later ``update_config`` that re-derives
	``_supported_symbols`` from ``config.limits`` can never wipe BTCUSD.

	D-17: this is the FALLBACK for callers that have NO run-derived config — the
	live root and the direct-construction test sites — and it is NEVER the
	preferred source. The preferred source is the factory's run-derived config,
	which folds THIS run's complete ticker set into ``limits.supported_symbols``;
	a default preset silently narrows the tradeable symbol set and the failure
	surfaces as refused orders far from its cause.

	Promoted from the private ``ExecutionHandler._default_backcompat_config``
	static in plan 11.1-07: the handler no longer builds an exchange, so its only
	internal caller is gone, while the live root and the shared test-wiring helper
	both need it.
	"""
	config = ExchangeConfig.default()
	config.limits.supported_symbols = set(config.limits.supported_symbols) | {'BTCUSD'}
	return config


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

	def __init__(self, global_queue: "EventBus", *,
				venue_bundles: "VenueBundles",
				portfolio_read_model: Optional["PortfolioReadModel"] = None) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		venue_bundles: `VenueBundles`
			The REQUIRED shared ``(venue, account_id)`` bundle memo (D-08). The
			handler no longer MINTS an exchange — it ASKS for one, and the venue
			plugin behind the memo is what builds it (D-06). The same instance is
			held by the portfolio arm, so both arms see ONE exchange and ONE
			account factory per venue+account; two independent ``build_bundle``
			calls would double-spawn a live venue's fill/order streams.

			It is REQUIRED, not ``Optional[...] = None``: a nullable seam here
			would let a caller silently fall back to a hand-minted exchange, and
			the two paths would then diverge without anything turning red.
		portfolio_read_model: `PortfolioReadModel`, optional
			The injected read-model used to resolve an order's VENUE ACCOUNT
			from its portfolio (D-27/MPORT-07). The injection is ASYMMETRIC by
			design, and the asymmetry is the point:

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
			natural-looking repair and it reintroduces exactly the MPORT-07
			vulnerability, routing a live portfolio that names no account
			through whatever session is registered as the default. Plan 11-08
			owns the composition-time invariant that makes ``account_id``
			mandatory in live; until then this refusal IS the guard.

		Notes
		-----
		D-07: the handler holds NO determinism seam any more. The ONE shared
		seeded ``random.Random`` rides on ``EngineContext.rng`` and reaches the
		exchange through ``PaperVenuePlugin.build_bundle`` — the component that
		now BUILDS it (D-06). The former ``rng`` parameter (plus ``_rng`` /
		``_rng_seed`` / ``_resolve_rng_seed``) lost its only reader when the mint
		moved out and was removed rather than left accepted-and-ignored: a
		vestigial seam here would let a caller believe determinism was wired
		through this handler when it no longer is.
		"""
		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="ExecutionHandler")

		self.global_queue = global_queue
		self._venue_bundles = venue_bundles
		self._portfolio_read_model = portfolio_read_model

		# Initialize exchanges (requires logger + the bundle memo). Keyed on the
		# (venue, account_id) PAIR — see DEFAULT_ACCOUNT_ID (D-27/MPORT-07).
		self.exchanges: dict[tuple[str, str], Optional[AbstractExchange]] = self.init_exchanges()

		self.logger.info('Execution Handler initialized (exchanges resolved via VenueBundles)')

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update execution configuration at runtime (D-07/D-08/D-09).

		The handler owns no Pydantic config model of its own; the execution
		config lives on the exchange. So the uniform ``update_config`` routes the
		partial update to the simulated exchange's canonical ``update_config``
		(recursive_merge -> model_validate -> atomic-swap -> ConfigurationError),
		keeping the single web-catchable raise contract. Returns ``None``; raises
		``ConfigurationError`` on failure (including when no exchange is wired).
		"""
		# D-27/D-05: the paper venue is single-account, so it lives under the
		# default-account half of the pair key. ``'paper'`` is the ONE name for
		# the simulated fill engine across backtest and live-paper (D-05) — the
		# retired ``'simulated'``/``'csv'`` synonyms no longer resolve anything,
		# so this lookup must never be written against them again.
		exchange = self.exchanges.get((COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key=COMPUTE_VENUE,
				reason='no paper exchange wired to update')
		exchange.update_config(updates)

	def validate_config(self, updates: Dict[str, Any]) -> None:
		"""Dry-validate a partial config update WITHOUT applying it (CR-02/D-15).

		Mirrors ``update_config`` but runs the exchange's dry twin
		(``SimulatedExchange.validate_config``): recursive_merge -> model_validate on a
		THROWAWAY copy, discarding the result — no atomic swap, no cache
		re-derivation. The ``ConfigRouter`` calls this BEFORE persisting a venue
		fee/slippage value so an invalid value never lands in ``VenueStore`` (a
		poisoned row would otherwise brick the next boot's restart-layering).
		Returns ``None``; RAISES ``ConfigurationError`` on failure (including when
		no exchange is wired) — the SAME contract shape as ``update_config``.
		"""
		# D-27/D-05: single-account paper venue -> default-account key half.
		exchange = self.exchanges.get((COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key=COMPUTE_VENUE,
				reason='no paper exchange wired to update')
		exchange.validate_config(updates)


	def on_order(self, event: OrderEvent) -> None:
		"""Route an order to the exchange holding its account's session (D-27).

		The routing target is the ``(venue, account_id)`` PAIR, never the bare
		venue name. The venue half is the order's own ``exchange`` string; the
		account half is resolved from the order's PORTFOLIO through the
		injected read-model. Without this, two portfolios trading one venue
		under different accounts both resolve to one exchange object and
		account B's orders are submitted through account A's authenticated
		session — the exact failure MPORT-07 exists to close.

		Every failure path here is FAIL-CLOSED: an unknown portfolio, an
		unnamed account, or an unregistered pair logs and returns. There is
		deliberately NO fallback to a bare-venue-name lookup — submitting
		through a guessed session is strictly worse than not submitting.
		"""
		# Unknown-portfolio gets its OWN branch: account_for routes through
		# get_portfolio (11-05), so a bad portfolio_id raises. Letting the
		# broad handler below catch it would log the misleading "Unexpected
		# error routing order" and make a caller error look like an internal
		# fault.
		try:
			account_id = self._resolve_account_id(event)
		except PortfolioNotFoundError:
			self.logger.error(
				'Unknown portfolio %s on order %s %s — order NOT submitted',
				event.portfolio_id, event.ticker, event.action)
			return

		if account_id is None:
			# LOUD REFUSAL (D-27). A live portfolio naming no account has no
			# session to route through; falling back to the default account
			# would submit through some other account's credentials. Plan
			# 11-08 makes account_id mandatory at composition time.
			self.logger.error(
				'Portfolio %s names no venue account — order %s %s NOT submitted '
				'(no default-account fallback: that would route through another '
				'account\'s session)',
				event.portfolio_id, event.ticker, event.action)
			return

		try:
			exchange = self.exchanges.get((event.exchange, account_id))
			if not exchange:
				self.logger.error(
					'No exchange registered for venue/account (%s, %s) — order %s %s '
					'NOT submitted', event.exchange, account_id,
					event.ticker, event.action)
				return
			exchange.on_order(event)
		except Exception as e:
			self.logger.error('Unexpected error routing order for %s %s: %s',
							 event.ticker, event.action, str(e), exc_info=True)

	def _resolve_account_id(self, event: OrderEvent) -> Optional[str]:
		"""Resolve the venue account half of the routing key (D-27).

		With NO read-model injected there is exactly one account — the
		backtest path — so the default constant is correct and unconditional.
		With one injected, the portfolio's own account is authoritative and a
		``None`` answer is propagated as a refusal, never coerced.
		"""
		if self._portfolio_read_model is None:
			return DEFAULT_ACCOUNT_ID
		return self._portfolio_read_model.account_for(event.portfolio_id)

	def on_market_data(self, bar: BarEvent) -> None:
		"""Drive resting-order matching on each exchange with a new bar."""
		# Dedup by instance identity: two registry keys may resolve to ONE
		# exchange object; driving it once per bar avoids double-matching the
		# resting-order book.
		#
		# D-05: VENUE ALIASES no longer exist — one venue name, one key, one
		# object. What remains is the ACCOUNT case: a caller may register the
		# same exchange object under two ACCOUNTS of one venue, and that object
		# must still be driven exactly once per bar. That is the only case this
		# dedup now collapses.
		#
		# D-27: it stays IDENTITY-based — do NOT "clean it up" into a key- or
		# name-based dedup. Two accounts holding DISTINCT exchange objects are
		# correctly driven separately: each owns its own resting-order book and
		# correlation index and must see every bar. A key-based rewrite would
		# drive a shared exchange twice per bar and silently change every
		# backtest number.
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

	
	def init_exchanges(self) -> dict[tuple[str, str], Optional[AbstractExchange]]:
		"""
		RESOLVE the wired exchanges through ``VenueBundles`` (D-06/D-08).

		The handler MINTS NOTHING. The venue plugin behind the memo builds the
		exchange from its own run-derived ``ExchangeConfig`` and the shared seeded
		RNG (D-17/D-07), exactly as the OKX plugin builds its ``OkxExchange``.
		Each exchange still manages its own fee/slippage models.
		"""
		# D-08: ASK the shared memo. ``spec=None`` because ``PaperVenuePlugin.build_bundle``
		# reads no spec field at all (unlike the OKX arm, which reads spec.account_id) —
		# passing a synthesized stand-in spec would invent a value nothing consumes.
		#
		# Only the PAPER arm is resolved here. The OKX arm is registered by the live
		# root's per-account loop (``assemble_venues`` + the registration loop in
		# ``build_live_system``), which knows the account set; this seam has no way to
		# enumerate accounts and must not guess one.
		bundle = self._venue_bundles.get(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID, None)
		simulated = bundle.exchange
		# D-05: ONE venue name for the simulated fill engine — ``'paper'``.
		# Backtest and live-paper are the SAME behaviour (a simulated fill
		# engine over computed accounts), so they carry one name, not a
		# synonym. The former ``('simulated', ...)``/``('csv', ...)`` alias pair
		# (two keys, one object) and the dead ``('ccxt', ...): None`` placeholder
		# are both RETIRED IN FULL — no transitional alias. A portfolio's
		# ``exchange``/``venue_name`` is ``'paper'`` (D-19), so its orders land
		# on this single key.
		#
		# D-27: keyed on the (venue, account_id) PAIR. The paper venue is
		# single-account, so it pairs with DEFAULT_ACCOUNT_ID. Only the venue
		# half changed here; the key SHAPE is untouched.
		exchanges: dict[tuple[str, str], Optional[AbstractExchange]] = {
			(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID): simulated,
		}

		# Connect to exchanges that support it. Dedup by instance identity: two
		# keys may resolve to one exchange object (post-D-05 that means two
		# ACCOUNTS on one venue, never two venue names), and connecting it once
		# avoids a misleading second "Successfully connected" log for the
		# idempotent no-op call (IN-03).
		# D-27: identity-based for the same reason as the on_market_data dedup —
		# it collapses shared objects, never distinct per-account exchanges.
		seen_connect: set[int] = set()
		for exchange_key, exchange in exchanges.items():
			if exchange is None or id(exchange) in seen_connect:
				continue
			seen_connect.add(id(exchange))
			exchange_name = exchange_key[0]
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

	def get_exchange_health(self, exchange_name: Optional[str] = None) -> dict[str, Any]:
		"""
		Get health status for one or all exchanges.
		
		Parameters
		----------
		exchange_name : str, optional
			VENUE name to check. If None, checks all registered exchanges.

			D-27: the registry is keyed on ``(venue, account_id)`` but this
			parameter stays a plain VENUE string and matches every pair whose
			venue half equals it — tuple-keyed health input/output is
			operator-hostile and no caller needs it. The returned dict is
			keyed by venue name for the single-account (default) case and by
			``"venue:account"`` only when a venue has a non-default account,
			so multi-account output stays lossless. That display key is NEVER
			persisted — ``Order.exchange`` keeps the bare venue name.

		Returns
		-------
		dict
			Health status information for requested exchange(s)
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
