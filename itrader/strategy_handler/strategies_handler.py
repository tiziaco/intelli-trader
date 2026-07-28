from typing import Any, Optional, TYPE_CHECKING

from itrader.core.enums import OrderType
from itrader.core.exceptions import ConfigurationError
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent
from itrader.price_handler.feed.base import BarFeed
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.lifecycle import StrategyLifecycleManager
from itrader.strategy_handler.managed_strategies import ManagedStrategies
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage import (
	SignalStorageFactory,
	SignalStore,
	StrategyRegistryStorageFactory,
)
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import (
	BarEvent,
	BarsLoaded,
	SignalEvent,
	StrategyCommandEvent,
)
from itrader.outils.time_parser import check_timeframe
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# This handler is on the backtest hot path, so the live-only Universe seam is
	# never imported at runtime there. The annotation stays a string.
	from itrader.universe.universe import Universe



class StrategiesHandler(object):
	"""
	Manage all the strategies of the trading system.
	"""

	def __init__(
		self,
		global_queue: "EventBus",
		feed: BarFeed,
		signal_store: "Optional[SignalStore]" = None,
		allow_short_selling: bool = False,
		enable_margin: bool = False,
		*,
		environment: str = "backtest",
		sql_engine: "Optional[Any]" = None,
		registry_store: "Optional[Any]" = None,
		strategy_catalog: "Optional[Any]" = None,
		portfolio_read_model: "Optional[Any]" = None,
	) -> None:
		"""
		Parameters
		----------
		global_queue: `EventBus`
			The events queue of the trading system.
		feed: `BarFeed`
			The look-ahead-safe read model the strategy windows are served from.
		signal_store: `SignalStore`
			The signal-record sink, written once per non-None intent BEFORE the
			per-portfolio fan-out. A sink/read-model, NOT a cross-domain handler call,
			so the queue-only contract holds.
		allow_short_selling: `bool`
			Registration flag. With ``enable_margin`` it gates ``add_strategy``: a
			non-``LONG_ONLY`` strategy is admitted ONLY when BOTH are on.
		enable_margin: `bool`
			Registration flag, coupled with ``allow_short_selling`` because it turns on
			the lock-and-settle model — the only model that can represent a short, since
			a short has no notional to "spend" and spot debit-notional cannot express it.
			With the default ``max_leverage == 1`` this gives fully-collateralized
			shorts; levered shorts are a separate opt-in dial.
		environment: `str`
			Storage-selection key — ``'backtest'`` / ``'test'`` / ``'live'``. The handler
			derives BOTH stores from this plus ``sql_engine`` rather than having a caller
			assign them afterwards; an explicitly passed store still WINS.
		sql_engine: `SqlEngine | None`
			The shared SQL spine handed to those factories. ``None`` on backtest, where
			both return in-memory concretes. Typed ``Any`` so the SQL stack stays off this
			module's annotations.
		registry_store: `StrategyRegistryStore | None`
			The durable instance registry every mutating verb writes through. ``None`` is
			the backtest path, where every persist arm is a clean no-op. An explicit value
			WINS — the override seam tests inject through.
		strategy_catalog: `StrategyCatalog | None`
			The access-control ALLOWLIST through which ``add`` / ``reconfigure`` resolve an
			untrusted external ``strategy_type``. ``None`` LOUD-rejects both. This is the
			boundary that stops an external payload from naming an arbitrary class.
		portfolio_read_model: `PortfolioReadModel | None`
			The flat-detect read-model consulted on FILL to decide whether a pending
			removal completed. Passed by ``compose_engine`` on BOTH paths, so it is
			non-``None`` in backtest too — do NOT infer the run mode from it.
		"""
		self.global_queue: "EventBus" = global_queue
		self.feed: BarFeed = feed
		# Bound BEFORE the collaborator block — ManagedStrategies takes it by injection.
		self.logger = get_itrader_logger().bind(component="StrategiesHandler")
		self.signal_store: SignalStore = (
			signal_store or SignalStorageFactory.create(environment, sql_engine=sql_engine)
		)
		# Tested with `is not None` rather than `or`, because a store object's
		# truthiness is not part of its contract and an `or` would silently re-derive on
		# a falsy store. A LOCAL, not an attribute: the lifecycle manager OWNS the live
		# deps and the properties below read through to it.
		resolved_registry_store: "Optional[Any]" = (
			registry_store if registry_store is not None
			else StrategyRegistryStorageFactory.create(environment, sql_engine=sql_engine)
		)
		# The roster collaborator OWNS `strategies`, `_pending_removals` and the two
		# shorts-enabling flags; the handler holds none of that state itself.
		self._managed: ManagedStrategies = ManagedStrategies(
			allow_short_selling=allow_short_selling,
			enable_margin=enable_margin,
			logger=self.logger,
		)
		# The STRATEGY_COMMAND control plane, constructed unconditionally so it exists
		# before any set_universe call or verb dispatch can reach it. Shares the SINGLE
		# ManagedStrategies roster owner rather than holding roster state of its own.
		self._lifecycle: StrategyLifecycleManager = StrategyLifecycleManager(
			managed=self._managed,
			global_queue=global_queue,
			feed=feed,
			registry_store=resolved_registry_store,
			strategy_catalog=strategy_catalog,
			portfolio_read_model=portfolio_read_model,
			logger=self.logger,
		)
		self.logger.info('Strategies Handler initialized')

	# --- roster accessors --------------------------------------------------
	#
	# These hand back the collaborator's OWN objects — never a copy, never a
	# snapshot. The roster list is mutated IN PLACE by callers (`.append` /
	# `.extend`), so a defensive copy would silently turn every one of those into a
	# no-op. Read-only: both container assignments live on the collaborator.

	@property
	def strategies(self) -> list[Strategy]:
		"""The managed roster — the IDENTICAL list object the collaborator holds."""
		return self._managed.strategies

	@property
	def _pending_removals(self) -> set[str]:
		"""The pending-removal name set — the collaborator's OWN set object."""
		return self._managed.pending_removals

	# A CAPABILITY gate, so there must be exactly ONE copy. Callers flip these
	# privates AFTER construction and then register a non-LONG_ONLY strategy; a
	# handler-side shadow attribute would let the gate the caller thinks it opened
	# diverge from the gate `add_strategy` actually consults.

	@property
	def _allow_short_selling(self) -> bool:
		"""Shorts-enabling gate flag — single source of truth is the collaborator."""
		return self._managed.allow_short_selling

	@_allow_short_selling.setter
	def _allow_short_selling(self, value: bool) -> None:
		self._managed.allow_short_selling = value

	@property
	def _enable_margin(self) -> bool:
		"""Shorts-enabling gate flag — single source of truth is the collaborator."""
		return self._managed.enable_margin

	@_enable_margin.setter
	def _enable_margin(self, value: bool) -> None:
		self._managed.enable_margin = value

	# --- live-dep accessors (single owner) ---------------------------------
	#
	# Read-through properties over the lifecycle manager, not copies. Callers
	# construct the handler and THEN assign one of these; with a handler-side plain
	# attribute the manager would keep the value it captured at construction and
	# silently keep running on `None`. Worse than a failing test: `strategy_catalog`
	# is the access-control ALLOWLIST, so a caller could believe it swapped the
	# catalog while the enforcement path still read the stale one — a silent
	# authorization bypass. Reading and writing THROUGH the single owner makes that
	# unrepresentable.
	#
	# All three stay typed `Any` so the SQL/registry stack stays off this module's
	# annotations.

	@property
	def registry_store(self) -> "Optional[Any]":
		"""Durable instance registry — owned by the lifecycle manager."""
		return self._lifecycle.registry_store

	@registry_store.setter
	def registry_store(self, value: "Optional[Any]") -> None:
		self._lifecycle.registry_store = value

	@property
	def strategy_catalog(self) -> "Optional[Any]":
		"""Strategy-type ALLOWLIST — owned by the lifecycle manager."""
		return self._lifecycle.strategy_catalog

	@strategy_catalog.setter
	def strategy_catalog(self, value: "Optional[Any]") -> None:
		self._lifecycle.strategy_catalog = value

	@property
	def portfolio_read_model(self) -> "Optional[Any]":
		"""Flat-detect read-model — owned by the lifecycle manager."""
		return self._lifecycle.portfolio_read_model

	@portfolio_read_model.setter
	def portfolio_read_model(self, value: "Optional[Any]") -> None:
		self._lifecycle.portfolio_read_model = value

	# READ-ONLY (no setter): the sole write path is set_universe -> the manager, and
	# an absent setter makes a desync unrepresentable rather than merely unlikely. A
	# desync would silently short-circuit _request_rewarm, which would never re-warm.
	@property
	def _universe(self) -> "Universe | None":
		"""The injected dynamic universe — owned by the lifecycle manager."""
		return self._lifecycle.universe

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the dynamic universe for the readiness gate.

		Called on BOTH paths, so ``self._universe`` is NOT ``None`` in backtest. The
		oracle is unaffected by construction rather than by absence: ``Universe``
		marks every member READY and backtest membership derives FROM the strategy
		tickers, so the per-tick gate in ``on_bar`` never skips.

		The forward to the lifecycle manager is UNCONDITIONAL — an ``assert`` here
		would abort every backtest run, since the wiring reaches this method on the
		backtest path too.

		Parameters
		----------
		universe: `Universe`
			The dynamic universe read-model.
		"""
		self._lifecycle.set_universe(universe)

	def is_warm(self, symbol: str) -> bool:
		"""Aggregate per-symbol indicator warmth across concerned strategies.

		Warm = every strategy whose ``.tickers`` include ``symbol`` has its per-symbol
		indicators warm. Vacuously ``True`` when no strategy is concerned with it.

		The ``UniverseHandler`` re-verifies this before flipping a symbol READY and
		subscribing it, so a swallowed partial warmup cannot let a half-warmed symbol
		become tradeable. INDICATOR warmth only — a handle-free ``PairStrategy`` is
		always ``is_ready`` True, and its spread warmth is governed on the dispatch
		path by ``is_pair_ready``.
		"""
		return all(
			strategy.is_ready(symbol)
			for strategy in self.strategies
			if symbol in strategy.tickers
		)

	def on_bar(self, event: BarEvent) -> None:
		"""
		Calculate the signal for every strategy to be traded.

		The handler owns everything portfolio-shaped: it stamps time/price from the bar
		event, attaches the strategy's declared policy/direction, fans the intent out
		per subscribed portfolio, and enqueues. The strategy is a pure alpha function.

		Parameters
		----------
		event: `BarEvent`
			The bar event of the trading system.
		"""
		for strategy in self.strategies:
			# Placed FIRST so the skip is unconditional and covers the PairStrategy
			# branch below. A disabled strategy STAYS in self.strategies, but this guard
			# runs BEFORE strategy.update, so its indicator state FREEZES rather than
			# advancing.
			#
			# ⚠ That freeze is exactly why `enable` does NOT trade the next bar. The
			# frozen values were computed over a window that now has an N-bar HOLE
			# spanning the disabled period; firing from them would let SMA/MACD silently
			# produce wrong values across a discontinuity, and warmth is monotone so
			# nothing downstream would ever notice. Hence `enable` calls mark_unwarm()
			# and the strategy must RE-WARM before is_ready lets it signal again.
			#
			# Disable stops NEW entries only: open positions and resting brackets run to
			# natural exit via the execution layer, which never reads this flag.
			if not strategy.is_active:
				continue
			# Check if the strategy's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			# Dispatched ONCE per tick through a typed two-leg branch, NOT the
			# per-ticker loop below: both legs must be evaluated together.
			if isinstance(strategy, PairStrategy):
				self._dispatch_pair(strategy, event)
				continue
			# Calculate the signal for each ticker traded from the strategy
			for ticker in strategy.tickers:
				# Sparse-ticker guard: the BarEvent payload contract keeps a no-data
				# ticker ABSENT from the dict, and no price means no signal. It
				# precedes generate_signal because _emit_intent stamps price from
				# bar.close.
				bar = event.bars.get(ticker)
				if bar is None:
					# No indicator update either — the per-symbol O(1) state stays
					# frozen and its count does NOT advance.
					continue
				# Gate on per-INDICATOR readiness, NOT a window-width len-gate: a
				# zero-handle COUNT/DATE fixture is always ready and its own logic
				# gates the firing.
				strategy.update(ticker, bar)
				# Membership gate, kept AFTER strategy.update so a pending symbol
				# still warms while never being traded until its warmup backfill
				# leaves PENDING/FAILED.
				if self._universe is not None and not self._universe.is_ready(ticker):
					continue
				if not strategy.is_ready(ticker):
					continue
				intent = strategy.generate_signal(ticker)
				if intent is None:
					continue
				self._emit_intent(strategy, event, ticker, bar, intent)

	def _emit_intent(
		self,
		strategy: Strategy,
		event: BarEvent,
		ticker: str,
		bar: Any,
		intent: SignalIntent,
	) -> None:
		"""Record one intent and fan it out per subscribed portfolio.

		The single per-intent path shared by the single-leg per-ticker loop and the
		PairStrategy two-leg dispatch: EXACTLY ONE ``SignalRecord`` pre-fan-out, then
		one ``SignalEvent`` per subscribed portfolio.

		``bar`` is the leg's bar from ``event.bars``; its ``.close`` stamps a MARKET
		entry price — do NOT read ``intent.entry_price`` for MARKET.
		"""
		# A signal is a single strategy decision, not a per-portfolio order, so the
		# record is written pre-fan-out and carries NO portfolio_id. Side-effect-only:
		# it never influences fills or fan-out.
		self.signal_store.add(SignalRecord(
			strategy_id=strategy.strategy_id,
			ticker=ticker,
			time=event.time,
			action=intent.action,
			order_type=intent.order_type,
			stop_loss=intent.stop_loss,
			take_profit=intent.take_profit,
			exit_fraction=intent.exit_fraction,
			quantity=intent.quantity,
			entry_price=intent.entry_price,
			config=strategy.to_dict(),
		))
		# Money boundary: prices enter the Decimal domain HERE via to_money. The bar
		# close is ALREADY Decimal via the Bar struct and to_money(Decimal) is
		# value-identity; absent SL/TP gives Decimal("0").
		#
		# Byte-exact canary: a MARKET intent carries entry_price=None and MUST keep
		# price = to_money(bar.close).
		if intent.order_type is OrderType.MARKET:
			entry_price = to_money(bar.close)
		else:
			# The typed limit/stop factories make ``price`` required, so a non-MARKET
			# intent always carries one. An explicit raise survives ``-O``; a bare
			# ``assert`` is stripped under PYTHONOPTIMIZE and would silently build a
			# SignalEvent(price=None), poisoning the Decimal money domain downstream.
			if intent.entry_price is None:
				raise ValueError(
					f"non-MARKET intent for {ticker} missing entry_price "
					f"(order_type={intent.order_type})")
			entry_price = intent.entry_price
		for portfolio_id in strategy.subscribed_portfolios:
			signal = SignalEvent(
				time=event.time,
				order_type=intent.order_type,
				ticker=ticker,
				action=intent.action,
				price=entry_price,
				stop_loss=intent.stop_loss if intent.stop_loss is not None else to_money(0),
				take_profit=intent.take_profit if intent.take_profit is not None else to_money(0),
				strategy_id=strategy.strategy_id,
				portfolio_id=portfolio_id,
				sizing_policy=strategy.sizing_policy,
				direction=strategy.direction,
				allow_increase=strategy.allow_increase,
				max_positions=strategy.max_positions,
				exit_fraction=intent.exit_fraction,
				# The order/risk layer caps and applies it.
				leverage=intent.leverage,
				# Decimal | None on both sides, so no boundary parse. None means
				# "resolver decides".
				quantity=intent.quantity,
				sltp_policy=strategy.sltp_policy,
			)
			self.global_queue.put(signal)
		self.logger.debug('Strategy signal (%s - %s %s)',
					strategy.strategy_id, ticker, intent.action)

	def _dispatch_pair(self, strategy: PairStrategy, event: BarEvent) -> None:
		"""Two-leg pair dispatch: both legs, once per tick.

		Requires BOTH legs' bars present this tick, pushes both into the pair's own
		bounded buffers, gates on ``is_pair_ready()``, then fans EACH returned intent
		through the SAME ``_emit_intent`` path the single-leg loop uses.

		Readiness is the pair's buffer fill, NOT the handle-derived
		``strategy.warmup``, which is 0 for a handle-free pair.
		"""
		# Guarded with a clear message rather than relying on the tuple-unpack raising
		# a bare "not enough values to unpack" if a subclass ever overrides validate()
		# without calling super().validate().
		if len(strategy.tickers) != 2:
			raise ValueError(
				f"_dispatch_pair requires a two-ticker pair contract: "
				f"got {strategy.tickers!r} (PairStrategy.validate enforces len-2; a "
				f"subclass override must call super().validate())"
			)
		ticker_A, ticker_B = strategy.tickers
		# A missing leg means no spread this tick — skip silently and do NOT
		# forward-fill, because a stale price poisons the spread. The pair buffers and
		# count stay frozen.
		bar_A = event.bars.get(ticker_A)
		bar_B = event.bars.get(ticker_B)
		if bar_A is None or bar_B is None:
			return
		# Short-circuit the WHOLE dispatch when EITHER leg is not universe-ready — no
		# update_pair, no evaluate_pair. AdmissionManager is the primary backstop;
		# this is the cheap defensive strategy-loop layer.
		if self._universe is not None and (
			not self._universe.is_ready(ticker_A)
			or not self._universe.is_ready(ticker_B)
		):
			return
		# update_pair stamps self.now from leg A's bar. The buffers ARE the trailing
		# windows the β/z math reads.
		strategy.update_pair(bar_A, bar_B)
		if not strategy.is_pair_ready():
			return
		win_A, win_B = strategy._buffers_as_windows()
		intents = strategy.evaluate_pair(win_A, win_B)
		if intents is None:
			return
		# The MARKET price is stamped from the MATCHING leg's bar — _emit_intent reads
		# bar.close, so the wrong leg's bar would price the wrong instrument.
		bars_by_ticker = {ticker_A: bar_A, ticker_B: bar_B}
		for intent in intents:
			self._emit_intent(strategy, event, intent.ticker, bars_by_ticker[intent.ticker], intent)

	def on_bars_loaded(self, event: BarsLoaded) -> None:
		"""Warm the concerned strategies from a bulk warmup payload.

		Live-only; NEVER on the backtest path. Replays ``event.bars`` IN ORDER through
		the identical ``strategy.update`` path the per-tick loop uses, and NOTHING
		else: no ``is_ready`` / ``generate_signal`` / ``_emit_intent``, no signal store
		and no queue, so warmup produces no tradeable signal. The per-bar loop is
		intrinsic to the O(1) recurrence and is never vectorized.

		⚠ A live ``PairStrategy`` is NOT warmed by this path. Its spread bookkeeping
		fills ONLY via ``update_pair`` (both legs together), never via the inherited
		single-leg ``update()`` replayed here. An added or rehydrated pair therefore
		warms from LIVE bars via ``_dispatch_pair``, with ``is_pair_ready`` blocking
		any wrong trade meanwhile.

		Parameters
		----------
		event: `BarsLoaded`
			The bulk warmup payload for one ``(symbol, timeframe)`` — an immutable
			``tuple[Bar, ...]`` reused verbatim from the queue.
		"""
		for strategy in self.strategies:
			if event.symbol not in strategy.tickers:
				continue
			for bar in event.bars:
				strategy.update(event.symbol, bar)

	def on_fill(self, event: "Any") -> None:
		"""Completion hook: drop a pending-removal strategy once its positions are flat.

		The three lifecycle behaviours stay DISTINCT and are never conflated:
		``disable`` stops NEW entries and KEEPS open positions + brackets; ``remove``
		force-flats, waits flat, then drops; ``reconfigure`` applies live and KEEPS
		positions.

		Wired on the LIVE FILL route only, AFTER ``PortfolioHandler.on_fill`` so the
		read model already reflects the settled position. Not on the backtest FILL
		route at all.
		"""
		self._lifecycle.on_fill(event)

	def on_strategy_command(self, event: StrategyCommandEvent) -> None:
		"""Apply one control-plane verb to one strategy, live AND durably.

		The live-only dispatch surface. Locates the strategy whose ``.name`` matches
		``event.strategy_name`` — the durable per-instance identity — and applies the
		verb IDEMPOTENTLY.

		An unknown ``strategy_name``, an unknown verb, or a malformed payload is a LOUD
		no-op: warn and return, NEVER a raise into the queue.

		Parameters
		----------
		event: `StrategyCommandEvent`
			The control-plane command addressed to one strategy by name.
		"""
		self._lifecycle.on_strategy_command(event)


	def get_strategies_universe(self) -> list[str]:
		"""
		Return every symbol traded across all registered strategies.

		Returns
		-------
		traded_tickers: `list[str]`
			The union of the strategies' tickers.
		"""
		return self._managed.get_universe()

	def add_strategy(self, strategy: Strategy) -> None:
		"""
		Add a new strategy in the list of strategies to trade.
		
		Parameters
		----------
		strategy: `Strategy object`
			Strategy to be executed by the trading system

		Raises
		------
		ValueError
			If the strategy declares a direction other than
			``TradingDirection.LONG_ONLY`` while NOT both shorts-enabling flags are
			on. A non-``LONG_ONLY`` strategy is admitted ONLY when
			``allow_short_selling`` AND ``enable_margin`` are both set; otherwise
			registration rejects the capability loudly. See ``__init__`` for why
			``enable_margin`` is required rather than ``allow_short_selling`` alone.
		"""
		self._managed.add_strategy(strategy)

	def update_config(self, updates: dict[str, Any]) -> None:
		"""Re-validate -> re-run init() -> re-derive warmup, per strategy.

		This handler owns NO Pydantic model, and inventing one for it is out of bounds
		— the real work is re-running each strategy's idempotent ``reconfigure`` seam,
		after which auto-warmup re-derives ``warmup``/``max_window`` from the declared
		indicators. Applied BETWEEN event cycles, never mid-cycle.

		Keyed by ``strategy.name``, the human-stable key: the per-construction
		``strategy_id`` UUIDv7 is NOT stable across runs.

		Parameters
		----------
		updates: `dict[str, Any]`
			A mapping ``{strategy.name: {param: value, ...}}``; each inner dict is
			forwarded VERBATIM as ``reconfigure(**inner)`` to the named strategy.

		Raises
		------
		ConfigurationError
			When a key matches no managed strategy's ``.name``, or when ``reconfigure``
			itself fails — wrapped so the surface stays single-catch.
		"""
		by_name = self._managed.by_name()
		for name, kwargs in updates.items():
			strategy = by_name.get(name)
			if strategy is None:
				raise ConfigurationError(
					config_key=name,
					reason=f"no managed strategy named {name!r}",
				)
			try:
				strategy.reconfigure(**kwargs)
			except ConfigurationError:
				raise
			except Exception as exc:
				raise ConfigurationError(
					config_key=name,
					reason=str(exc),
				) from exc
