import random
from typing import TYPE_CHECKING, Any, Dict, Optional

from .base import AbstractExecutionHandler
from .exchanges.base import AbstractExchange
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import BarEvent, FillEvent, OrderEvent
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

from itrader.config import ExchangeConfig
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# Read-model seam only (D-27): the Protocol is imported for TYPING ONLY so
	# nothing from the portfolio domain lands on this module's import graph.
	# The execution handler must NEVER import PortfolioHandler — the queue-only
	# cross-domain contract governs handler-to-handler access and the injected
	# read-model is the sanctioned exception for READS.
	from itrader.core.portfolio_read_model import PortfolioReadModel


#: The logical venue account of a SINGLE-account venue (D-27/MPORT-07).
#:
#: The exchange registry is keyed on the ``(venue, account_id)`` PAIR, because
#: an order's real target is a specific AUTHENTICATED SESSION, not a venue.
#: Venues that have only ever had one account — the simulated/backtest path,
#: and any venue before per-account wiring — register under this constant.
#:
#: It is deliberately a separate KEY HALF and never spliced into the venue
#: name: ``Order.exchange`` is a persisted column, so a composed
#: ``"venue:account"`` string would leak account topology into durable data and
#: into every query over it. The key is a runtime tuple; the persisted column
#: keeps the bare venue name.
DEFAULT_ACCOUNT_ID = 'default'


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
				exchange_config: Optional[ExchangeConfig] = None,
				portfolio_read_model: Optional["PortfolioReadModel"] = None,
				rng: Optional[random.Random] = None) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
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
		rng: `random.Random`, optional
			The ONE shared seeded RNG for the run, taken off ``EngineContext.rng``
			by ``compose_engine`` (D-07). The exchange AND its slippage model draw
			from THIS object — supplying two different instances across a run (or
			letting a second one be minted downstream) breaks reproducibility
			silently, because two ``random.Random(42)`` objects look identical
			until either is drawn from and the call ORDER diverges. Every
			engine-wired run therefore injects it.

			When ``None``, the handler falls back to deriving its own from
			``_resolve_rng_seed()`` — the pre-D-07 behaviour. This is deliberate
			backward-compat for the direct-construction sites (a number of
			unit/integration tests build ``ExecutionHandler(global_queue)`` with no
			``ctx`` at all), mirroring the ``_default_backcompat_config`` fallback
			below. Removing it would turn this plan into a test-wide migration for
			no correctness gain: those sites have no second component sharing the
			RNG, so a locally-derived instance is observationally identical.
		"""
		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="ExecutionHandler")

		self.global_queue = global_queue
		self._exchange_config = exchange_config
		self._portfolio_read_model = portfolio_read_model

		# Determinism seam (D-11, moved to the wiring seam by D-07): ONE seeded
		# random.Random per run, shared by every stochastic component (SimulatedExchange
		# + its slippage model). Never seeded per-call, never duplicated — that is what
		# makes a run reproducible (#5/PERF2).
		#
		# D-07: the engine-wired path now INJECTS it off ``EngineContext.rng``, because
		# from plan 11.1-07 the venue plugin — not this handler — builds the stochastic
		# exchange and cannot reach a private attribute here. The ``None`` arm keeps the
		# pre-D-07 derivation for direct-construction sites (see the ``rng`` docstring).
		self._rng_seed: Optional[int]
		self._rng: random.Random
		if rng is not None:
			self._rng_seed = None
			self._rng = rng
		else:
			self._rng_seed = self._resolve_rng_seed()
			self._rng = random.Random(self._rng_seed)

		# Initialize exchanges (requires logger + rng). Keyed on the
		# (venue, account_id) PAIR — see DEFAULT_ACCOUNT_ID (D-27/MPORT-07).
		self.exchanges: dict[tuple[str, str], Optional[AbstractExchange]] = self.init_exchanges()

		# D-07/T-11.1-14: report the injected case DISTINCTLY. Logging `rng_seed=None`
		# after injection would read as "no seed / non-deterministic" when the opposite
		# is true — the run is seeded upstream at the wiring seam.
		if self._rng_seed is None:
			self.logger.info('Execution Handler initialized (rng=injected from EngineContext)')
		else:
			self.logger.info('Execution Handler initialized (rng=derived, rng_seed=%s)', self._rng_seed)

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
		(recursive_merge -> model_validate -> atomic-swap -> ConfigurationError),
		keeping the single web-catchable raise contract. Returns ``None``; raises
		``ConfigurationError`` on failure (including when no exchange is wired).
		"""
		# D-27: the simulated venue is single-account, so it lives under the
		# default-account half of the pair key. This preserves object identity
		# and the alias structure exactly — the oracle is unaffected.
		exchange = self.exchanges.get(('simulated', DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key='simulated',
				reason='no simulated exchange wired to update')
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
		# D-27: single-account simulated venue -> default-account key half.
		exchange = self.exchanges.get(('simulated', DEFAULT_ACCOUNT_ID))
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key='simulated',
				reason='no simulated exchange wired to update')
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
		# Dedup by instance identity: multiple venue aliases (e.g. 'simulated' and 'csv')
		# may point to the same exchange object; driving it once per bar avoids
		# double-matching the resting-order book (DEF-01-B alias, Plan 01-04).
		#
		# D-27: this dedup stays IDENTITY-based and is correct by construction
		# under the pair key — do NOT "clean it up" into a key- or name-based
		# dedup. It exists to collapse ALIASES (two keys deliberately pointing
		# at ONE object). Two ACCOUNTS on one venue are two DISTINCT objects
		# with distinct identity, so they are correctly driven separately: each
		# account owns its own resting-order book and correlation index and
		# must see every bar. A key-based rewrite would drive the shared
		# simulated exchange twice per bar and silently change every backtest
		# number.
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
		# D-27: keyed on the (venue, account_id) PAIR. All three built-in venues
		# are single-account, so each pairs with DEFAULT_ACCOUNT_ID — which is
		# precisely what preserves the alias structure (and therefore the
		# byte-exact oracle) across the keying change.
		exchanges: dict[tuple[str, str], Optional[AbstractExchange]] = {
			('simulated', DEFAULT_ACCOUNT_ID): simulated,
			# Backtest portfolios use exchange="csv" (offline golden feed). Orders carry the
			# portfolio's exchange string, so the 'csv' venue must resolve to the simulated
			# matching engine for the backtest fill path to work (DEF-01-B, Plan 01-04).
			# SAME OBJECT as 'simulated' above — the deliberate aliasing the
			# identity dedup below and in on_market_data exists to collapse.
			('csv', DEFAULT_ACCOUNT_ID): simulated,
			('ccxt', DEFAULT_ACCOUNT_ID): None  # Placeholder for live exchange implementation
		}

		# Connect to exchanges that support it. Dedup by instance identity:
		# venue aliases (e.g. 'simulated' and 'csv') may point to the same
		# exchange object; connecting it once avoids a misleading second
		# "Successfully connected" log for the idempotent no-op call (IN-03).
		# D-27: identity-based for the same reason as the on_market_data dedup —
		# it collapses aliases, never distinct per-account exchanges.
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
		config = ExchangeConfig.default()
		config.limits.supported_symbols = set(config.limits.supported_symbols) | {'BTCUSD'}
		return config

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
