from datetime import timedelta
from queue import Queue
from typing import Any, TYPE_CHECKING, cast

from itrader.core.enums import OrderType
from itrader.core.exceptions import ConfigurationError
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, TradingDirection
from itrader.price_handler.feed.base import BarFeed
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage import SignalStore
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.outils.time_parser import check_timeframe
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# TYPE_CHECKING-guarded (D-01): StrategiesHandler is on the backtest hot
	# path, so the live-only Universe seam is never imported at runtime on the
	# backtest path — the readiness gate is a single `is None` short-circuit
	# when no universe is wired. The annotation stays a string ("Universe |
	# None") so no runtime import cost is added.
	from itrader.universe.universe import Universe


class StrategiesHandler(object):
	"""
	Manage all the strategies of the trading system.
	"""

	def __init__(
		self,
		global_queue: "Queue[Any]",
		feed: BarFeed,
		signal_store: SignalStore,
		allow_short_selling: bool = False,
		enable_margin: bool = False,
	) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		feed: `BarFeed`
			The look-ahead-safe market-data read model the strategy
			windows are served from (D-20).
		signal_store: `SignalStore`
			The injected signal-record sink (D-07/D-12). The handler captures
			one ``SignalRecord`` per non-None intent BEFORE the per-portfolio
			fan-out (D-09); the store is read post-run via the TradingSystem
			accessor. It is a sink/read-model — NOT a cross-domain handler call,
			so the queue-only contract is preserved.
		allow_short_selling: `bool`
			SHORT-01/D-07 registration flag. Together with ``enable_margin`` it
			gates ``add_strategy``: a non-``LONG_ONLY`` strategy is admitted ONLY
			when BOTH flags are on. Defaults off so the golden ``LONG_ONLY`` path
			(SMA_MACD) is unaffected and the oracle stays byte-exact.
		enable_margin: `bool`
			SHORT-01/D-07 registration flag. Coupled with ``allow_short_selling``
			because ``enable_margin`` turns on the lock-and-settle model (Phase 2
			D-09) — the only model that can represent a short (a short has no
			notional to "spend"; spot debit-notional cannot express it). With the
			default ``max_leverage == 1`` this gives fully-collateralized shorts
			(no leverage); levered shorts are a separate opt-in dial. Defaults off.
		"""
		self.global_queue: "Queue[Any]" = global_queue
		self.feed: BarFeed = feed
		self.signal_store: SignalStore = signal_store
		# SHORT-01/D-07 two-flag registration gate — read, never mutated here.
		self._allow_short_selling: bool = allow_short_selling
		self._enable_margin: bool = enable_margin
		# IN-06: initialize to None rather than a 100-week magic sentinel. A
		# downstream consumer reading min_timeframe before any strategy is
		# registered gets a clear "no strategies" signal (None) instead of
		# meaningless garbage. add_strategy computes the real min defensively.
		self.min_timeframe: timedelta | None = None
		#self.portfolios: dict = {}
		self.strategies: list[Strategy]= []
		# WR-02 (D-01) live-only readiness seam: the injected dynamic universe,
		# wired ONLY on the live path via set_universe. Defaults None so the
		# backtest wires no universe → the calculate_signals readiness gate is a
		# single `is None` short-circuit (oracle byte-exact, RESEARCH OQ8).
		self._universe: "Universe | None" = None

		self.logger = get_itrader_logger().bind(component="StrategiesHandler")
		self.logger.info('Strategies Handler initialized')

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the live dynamic universe for the WR-02 readiness gate (D-01).

		Live-only seam (mirrors the inert-by-default pattern): the backtest
		composition root never calls this, so ``self._universe`` stays ``None``
		and the per-tick gate in ``calculate_signals`` short-circuits — the
		SMA_MACD oracle path is untouched.
		"""
		self._universe = universe

	def calculate_signals(self, event: BarEvent) -> None:
		"""
		Calculate the signal for every strategy to be traded.

		Before generating the signal check if the actual time
		is a multiple of the strategy's timeframe.

		The handler owns everything portfolio-shaped (D-12): it stamps
		time/price from the bar event, attaches the strategy's declared
		policy/direction, fans the intent out per subscribed portfolio,
		and enqueues — the strategy is a pure alpha function.

		Parameters
		----------
		event: `BarEvent object`
			The bar event of the trading system
		"""
		for strategy in self.strategies:
			# Check if the strategy's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			# PAIR-01 (D-01): a PairStrategy is dispatched ONCE per tick through a
			# typed two-leg branch (NOT the per-ticker loop below) — both legs are
			# evaluated together and fanned out per portfolio. The single-leg
			# per-ticker path is structurally untouched (the branch `continue`s).
			if isinstance(strategy, PairStrategy):
				self._dispatch_pair(strategy, event)
				continue
			# Calculate the signal for each ticker traded from the strategy
			for ticker in strategy.tickers:
				# WR-12 sparse-ticker guard (relocated from the legacy
				# Strategy._generate_signal): the ticker is absent from the
				# bar event (sparse universe, data gap) — no price means no
				# signal. The BarEvent payload contract (M5-02) keeps a
				# no-data ticker ABSENT from the dict. The guard precedes
				# generate_signal because the handler stamps price from
				# event.bars[ticker].close below. D-05: the duplicate absence
				# warning was removed — the feed's generate_bar_event is the
				# single span-aware observability owner (D-04); the strategy
				# handler is a pure consumer (missing bar = nothing to do this
				# tick). The skip below is LOAD-BEARING (price is stamped from
				# bar.close).
				bar = event.bars.get(ticker)
				if bar is None:
					# P5-D10c/D14 gap skip (KEPT): a missing bar this tick means no
					# indicator update — the per-symbol O(1) state stays frozen
					# (count does NOT advance) and nothing fires. The feed owns bar
					# existence; a sparse universe / data gap drops the ticker from
					# event.bars (M5-02). LOAD-BEARING: price is stamped from
					# bar.close in _emit_intent below.
					continue
				# P5-D13/D14 restructured per-tick loop: push the latest completed
				# bar through the strategy's per-symbol stateful state, gate on the
				# per-INDICATOR readiness (NOT a window-width len-gate), then read
				# the handles in generate_signal. The removed feed.window() slice +
				# len(data) < warmup gate are now `update -> is_ready -> generate`:
				#   - update(ticker, bar) drives the O(1) recurrences (P5-D07) and
				#     stashes the count/latest-bar/now anchors (P5-D13a);
				#   - is_ready(ticker) = all declared handles warm (P5-D06/D10b) — a
				#     zero-handle COUNT/DATE fixture is always ready (its own logic
				#     gates the firing). This is byte-identical to the old warmup
				#     short-circuit: SMA_MACD's warmup==100 is now "all three handles
				#     ready at >=100 bars" (HARD-04, the firing tick is preserved).
				strategy.update(ticker, bar)
				# WR-02 (D-01/D-03c) defensive membership readiness gate, composed
				# BEFORE the indicator-warmth gate: warm the O(1) recurrence
				# (strategy.update above already advanced it) but do NOT trade a
				# symbol whose warmup backfill is still PENDING/FAILED. This is a
				# single None-check + one O(1) is_ready read, NO allocation — the
				# oracle hot path (RESEARCH OQ8). Default _universe is None →
				# backtest short-circuits on `is None` → byte-exact. Kept AFTER
				# strategy.update so a pending symbol still warms (D-03c: the
				# recurrence must advance while pending).
				if self._universe is not None and not self._universe.is_ready(ticker):
					continue
				if not strategy.is_ready(ticker):
					continue
				intent = strategy.generate_signal(ticker)
				if intent is None:
					continue
				# D-09/D-12: record + per-portfolio fan-out for this single-leg
				# intent. Factored into _emit_intent so the PairStrategy branch
				# reuses the EXACT same record + fan-out path per leg (the
				# single-leg behavior is byte-identical — same call, same args).
				self._emit_intent(strategy, event, ticker, bar, intent)

	def _emit_intent(
		self,
		strategy: Strategy,
		event: BarEvent,
		ticker: str,
		bar: Any,
		intent: SignalIntent,
	) -> None:
		"""Record one intent and fan it out per subscribed portfolio (D-09/D-12).

		The single per-intent path shared by the single-leg per-ticker loop and
		the PairStrategy two-leg dispatch — writing EXACTLY ONE ``SignalRecord``
		(pre-fan-out, no portfolio_id) then one ``SignalEvent`` per subscribed
		portfolio. Pure code-motion of the legacy inline block (oracle-dark for
		single-leg): same store call, same MARKET price stamp, same fan-out args.

		``bar`` is the leg's bar from ``event.bars`` (its ``.close`` stamps a
		MARKET entry price, Pitfall 1 — do NOT read ``intent.entry_price`` for
		MARKET).
		"""
		# D-09 per-intent, pre-fan-out capture: write EXACTLY ONE
		# SignalRecord per non-None intent, BEFORE the per-portfolio
		# fan-out below — a signal is a single strategy decision, not a
		# per-portfolio order, so the record carries NO portfolio_id. The
		# store is a sink/read-model (D-12): this is a local method call
		# on an injected dependency, NOT a cross-domain handler call, so
		# the queue-only contract holds. D-11: config is the strategy's
		# frozen config, snapshotted by reference. Side-effect-only — it
		# never influences fills or the fan-out (oracle-dark, HARD-04).
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
		# Relocated SignalEvent construction (D-12): one event per
		# subscribed portfolio. D-02 per-intent fan-out: order_type
		# now comes from the intent (the per-instance strategy attr is
		# retired, D-01). D-22 money boundary: prices enter the Decimal
		# domain HERE via to_money (the D-04 string path) — the bar
		# close is ALREADY Decimal via the Bar struct (D-14):
		# to_money(Decimal) is value-identity. Absent SL/TP preserves
		# the legacy default exactly: to_money(0) == Decimal("0").
		#
		# Pitfall 1 (byte-exact canary): a MARKET intent carries
		# entry_price=None and MUST keep price = to_money(bar.close) —
		# do NOT read intent.entry_price for MARKET. LIMIT/STOP intents
		# use their declared entry_price.
		if intent.order_type is OrderType.MARKET:
			entry_price = to_money(bar.close)
		else:
			# D-01: the typed limit/stop factories make ``price``
			# required, so a non-MARKET intent ALWAYS carries an
			# entry_price — narrow the Decimal | None for SignalEvent.
			# WR-02 (D-06 fail-loud): an explicit raise survives ``-O``
			# (a bare ``assert`` is stripped under PYTHONOPTIMIZE, which
			# would silently build a SignalEvent(price=None) — a None
			# poisoning the Decimal money domain in sizing/admission).
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
				# FL-02: subscribed_portfolios is the dual-handle
				# PortfolioId | int seam, but the runtime value is always a
				# UUIDv7-backed PortfolioId. SignalEvent.portfolio_id is now
				# typed PortfolioId (#10 carry-forward), so bridge the union
				# with cast(PortfolioId, ...) at this construction boundary.
				portfolio_id=cast(PortfolioId, portfolio_id),
				sizing_policy=strategy.sizing_policy,
				direction=strategy.direction,
				allow_increase=strategy.allow_increase,
				max_positions=strategy.max_positions,
				exit_fraction=intent.exit_fraction,
				# Finding A (LEV-03): carry the strategy-declared leverage
				# onto the fan-out SignalEvent (D-03). Default Decimal("1")
				# leaves the spot path byte-exact; the order/risk layer caps
				# and applies it (admission _effective_leverage).
				leverage=intent.leverage,
				# WR-01: honor an explicit caller-supplied quantity. The
				# field is already Decimal | None (D-22 money domain) on
				# both SignalIntent and SignalEvent — no boundary parse.
				# None means "resolver decides" (the golden path).
				quantity=intent.quantity,
				# WR-06: read the typed declaration directly — sltp_policy
				# is now a real Strategy attribute, not a getattr hole.
				sltp_policy=strategy.sltp_policy,
			)
			self.global_queue.put(signal)
		self.logger.debug('Strategy signal (%s - %s %s)',
					strategy.strategy_id, ticker, intent.action)

	def _dispatch_pair(self, strategy: PairStrategy, event: BarEvent) -> None:
		"""Two-leg pair dispatch (PAIR-01, D-01/D-02): both legs, once per tick.

		Routed from ``calculate_signals`` for any ``PairStrategy`` (a typed
		``isinstance`` branch). Reads the pair's two tickers, requires BOTH legs'
		bars present this tick (D-02 — skip silently, NO forward-fill so no
		stale/forward-filled price ever enters the spread, T-06-01), pushes BOTH
		legs into the pair's own bounded buffers via ``update_pair(bar_A, bar_B)``
		(P5-D09/D15 — the per-tick ``feed.window()`` slice is GONE), gates on the
		pair's own ``is_pair_ready()`` (β fittable + z tail = beta_warmup +
		z_lookback bars buffered), then calls ``evaluate_pair`` and fans EACH
		returned intent through the SAME ``_emit_intent`` path used by the single-leg
		loop.

		Readiness (P5-D15): the legacy window-length fit/z short-circuit is folded
		into the pair's buffer fill (``is_pair_ready`` — the buffer holds the full
		β-fit + z-tail bar count), NOT the handle-derived ``strategy.warmup`` (0 for
		a handle-free pair).
		"""
		# The pair contract is exactly two tickers (PairStrategy.validate asserts
		# it at construction) — leg A is tickers[0], leg B is tickers[1]. IN-04:
		# guard the len-2 contract here with a clear message rather than relying on
		# the tuple-unpack raising a bare "too many/not enough values to unpack" if
		# a subclass ever overrides validate() without calling super().validate().
		if len(strategy.tickers) != 2:
			raise ValueError(
				f"_dispatch_pair requires a two-ticker pair contract: "
				f"got {strategy.tickers!r} (PairStrategy.validate enforces len-2; a "
				f"subclass override must call super().validate())"
			)
		ticker_A, ticker_B = strategy.tickers
		# D-02 both-present guard (mirrors the single-leg :111-113 shape, requiring
		# BOTH legs). A missing leg means no spread this tick — skip silently, do
		# NOT forward-fill (T-06-01: a stale price would poison the spread).
		bar_A = event.bars.get(ticker_A)
		bar_B = event.bars.get(ticker_B)
		if bar_A is None or bar_B is None:
			# D-02/P5-D10c: a missing leg = no spread this tick — skip silently,
			# the pair buffers + count stay frozen (no update, no forward-fill).
			return
		# P5-D09/D15: push BOTH legs into the pair's own bounded per-leg buffers
		# (the feed.window() slice is removed). update_pair stamps self.now from
		# leg A's bar (a tz-aware Timestamp). The buffers ARE the trailing windows
		# the β/z math reads — byte-identical to the removed feed.window(280).
		strategy.update_pair(bar_A, bar_B)
		# P5-D15 readiness: gate on the pair's buffer fill (β fittable + z tail),
		# folding the removed window-length fit/z short-circuit.
		if not strategy.is_pair_ready():
			return
		win_A, win_B = strategy._buffers_as_windows()
		intents = strategy.evaluate_pair(win_A, win_B)
		if intents is None:
			return
		# Fan EACH leg's intent through the SAME record + fan-out path the
		# single-leg loop uses. Stamp the MARKET price from the matching leg's bar
		# (bar_A for ticker_A, bar_B for ticker_B) — _emit_intent reads bar.close
		# for a MARKET intent (Pitfall 1).
		bars_by_ticker = {ticker_A: bar_A, ticker_B: bar_B}
		for intent in intents:
			self._emit_intent(strategy, event, intent.ticker, bars_by_ticker[intent.ticker], intent)

	def get_strategies_universe(self) -> list[str]:
		"""
		Return a list with all the coins traded from the differents strategies.

		Returns
		-------
		traded_tickers: `list`
			List of strings with the traded symbols
		"""
		traded_tickers: list[str] = []
		for strategy in self.strategies:
			# IN-01: the declared config contract is `tickers: list[str]`, so
			# `tickers[0]` is always a `str` — the legacy pairs-trading branch
			# (`isinstance(tickers[0], tuple)`) was dead on every supported path
			# and has been removed. A typed pairs API will replace it if/when
			# pairs trading is reintroduced, rather than runtime isinstance
			# sniffing on the first element.
			traded_tickers += strategy.tickers

		return list(set(traded_tickers))

	
	def add_strategy(self, strategy: Strategy) -> None:
		"""
		Add a new strategy in the list of strategies to trade.
		At the same time, calculate the minimum timeframe among 
		the different strategies to be traded. 
		This timeframe will be used from the price handler to 
		download historical prices
		
		Parameters
		----------
		strategy: `Strategy object`
			Strategy to be executed by the trading system

		Raises
		------
		ValueError
			If the strategy declares a direction other than
			``TradingDirection.LONG_ONLY`` while NOT both shorts-enabling flags
			are on (SHORT-01/D-07). A non-``LONG_ONLY`` strategy (LONG_SHORT or
			SHORT_ONLY) is admitted ONLY when ``allow_short_selling`` AND
			``enable_margin`` are both set; otherwise registration rejects the
			capability loudly. ``enable_margin`` is required (not just
			``allow_short_selling``) because it turns on the lock-and-settle
			model (Phase 2 D-09) — the only model that can represent a short
			(spot debit-notional cannot). With the default ``max_leverage == 1``
			this gives fully-collateralized shorts (no leverage); levered shorts
			are a separate opt-in dial. Both flags default off → the golden
			``LONG_ONLY`` path (SMA_MACD) is unaffected, oracle byte-exact.
		"""
		# SHORT-01/D-07 two-flag registration gate: a non-LONG_ONLY direction is
		# admissible ONLY when BOTH allow_short_selling AND enable_margin are on.
		# enable_margin is coupled in because it enables the lock-and-settle model
		# that can actually represent a short. Both default off → the golden
		# LONG_ONLY path is unaffected (oracle byte-exact).
		if strategy.direction is not TradingDirection.LONG_ONLY:
			if not (self._allow_short_selling and self._enable_margin):
				raise ValueError(
					"Non-LONG_ONLY strategies (LONG_SHORT / SHORT_ONLY) require "
					"BOTH allow_short_selling AND enable_margin to be enabled "
					"(SHORT-01/D-07) — enable_margin turns on the lock-and-settle "
					"model that can represent a short. Both flags default off."
				)

		# Add the strategy in the strategies list
		self.strategies.append(strategy)

		# Find the minimum timeframe (IN-06: defensive against the None seed —
		# the first registered strategy establishes the baseline).
		if self.min_timeframe is None:
			self.min_timeframe = strategy.timeframe
		else:
			# IN-01: min_timeframe is guaranteed non-None here — the None seed
			# (IN-06) is handled by the branch above. This `else` arm is the
			# load-bearing non-None branch; moving min(...) out from under the
			# `is None` guard would feed min() a None and raise TypeError at
			# wiring time. Keep the guard and this arm coupled.
			self.min_timeframe = min(self.min_timeframe, strategy.timeframe)

		self.logger.info(f'New strategy added: {strategy.name}')

	def update_config(self, updates: dict[str, Any]) -> None:
		"""Re-validate -> re-run init() -> re-derive warmup, per strategy (D-09).

		COMP-02's uniform runtime config-update surface for the
		StrategiesHandler. Unlike the config-model handlers, the handler owns
		NO Pydantic model and D-09 explicitly forbids inventing a config model
		for it — the real work is re-running each
		strategy's idempotent ``reconfigure`` seam (Phase 2 D-12), which
		re-applies + re-validates the params and re-runs ``init()``, after
		which Phase 3's auto-warmup re-derives ``warmup``/``max_window`` from
		the declared indicators (Phase 3 D-08).

		PINNED dict shape (boundary contract — Wave-4/04-05 builds against this
		exact shape): ``updates`` is keyed by ``strategy.name``; each value is a
		kwargs dict forwarded VERBATIM as ``reconfigure(**value)`` to that one
		named strategy. ``strategy.name`` is the human-stable key (the
		per-construction ``strategy_id`` UUIDv7 is NOT stable across runs).

		Error contract (D-08, single web-catchable type): a key matching no
		managed strategy's ``.name`` raises ``ConfigurationError`` (config_key =
		the unknown name); any failure raised by ``reconfigure`` (e.g. an
		unknown/missing param from the base engine) is wrapped into
		``ConfigurationError`` so the surface stays single-catch.

		Applied BETWEEN event cycles, never mid-cycle (D-11).

		Parameters
		----------
		updates: `dict[str, Any]`
			A mapping ``{strategy.name: {param: value, ...}}``; each inner dict
			is forwarded as ``reconfigure(**inner)`` to the named strategy.
		"""
		by_name = {strategy.name: strategy for strategy in self.strategies}
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
				# Wrap any reconfigure failure (UnknownParamError /
				# MissingParamError / a validate() ValueError) into the single
				# web-catchable ConfigurationError (D-08).
				raise ConfigurationError(
					config_key=name,
					reason=str(exc),
				) from exc
