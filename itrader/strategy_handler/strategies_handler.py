import uuid
from datetime import timedelta
from typing import Any, Optional, TYPE_CHECKING, cast

from itrader.core.enums import OrderType
from itrader.core.exceptions import ConfigurationError
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, TradingDirection
from itrader.price_handler.feed.base import BarFeed
from itrader.strategy_handler.base import Strategy
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
	UniversePollEvent,
)
from itrader.outils.time_parser import check_timeframe
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# TYPE_CHECKING-guarded (D-01): StrategiesHandler is on the backtest hot
	# path, so the live-only Universe seam is never imported at runtime on the
	# backtest path — the readiness gate is a single `is None` short-circuit
	# when no universe is wired. The annotation stays a string ("Universe |
	# None") so no runtime import cost is added.
	from itrader.universe.universe import Universe


# D-16/D-17 verb-scoped pair guard. A PairStrategy refuses EXACTLY these verbs and
# accepts every other one — see the citation block in on_strategy_command. The v1.7
# guard refused ALL verbs, which is broader than D-16 permits.
_PAIR_REFUSED_VERBS = frozenset({"reconfigure", "add_ticker", "remove_ticker"})

# D-09/D-11: the verbs whose effect requires a UniversePollEvent follow-on. The two
# ticker verbs change universe MEMBERSHIP; `enable` needs it because WD-1 unwarms the
# strategy and the re-warm rides the CR-02 FAILED-retry, which only runs on a poll.
# disable/subscribe/unsubscribe change neither membership nor warmth -> no poll.
# `reconfigure` emits its OWN poll inline (like `remove`), so it is NOT listed here.
_POLL_FOLLOW_ON_VERBS = frozenset({"add_ticker", "remove_ticker", "enable"})

# D-15/F-2: the `reconfigure` mutability DENY-lists (audit 10-08 F2). `reconfigure` MUTATES
# the authoring surface, but two closed sets of keys are refused loudly BEFORE any throwaway
# is built — everything else is left to _apply_params' existing unknown-param rejection, so no
# second hand-maintained allowlist can drift from the class annotations.
#
# _RECONFIGURE_IMMUTABLE — IDENTITY + DERIVED, never a param:
#   - `strategy_type`: changing the class IS a different strategy (remove + add). It is an
#     ENVELOPE key, not a declared param, so _apply_params would also reject it — kept here as
#     defense-in-depth and to name the remove+add path in the operator-facing reject.
#   - `name`: the store PK (D-02). A rename would UPSERT a NEW row and ORPHAN the old one; the
#     codec omits `name` from the blob precisely so a PK-vs-blob disagreement is
#     unrepresentable (config_codec._SKIPPED_FIELDS). Identity is not a param — renaming is
#     remove + add (audit 10-08 F2).
#   - `warmup` / `max_window`: the codec's _DERIVED_FIELDS — `_run_init` UNCONDITIONALLY
#     overwrites both from the declared indicators, so a passed value is silently clobbered
#     (max_window ratchets via max()). Refuse loudly rather than accept-then-clobber.
# Hardcoded (NOT imported from config_codec) to keep the registry/codec off the BACKTEST
# import graph (GATE-01 inertness, test_okx_inertness); the authoritative derived set is
# config_codec._DERIVED_FIELDS == frozenset({"warmup", "max_window"}) and this MUST track it.
_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type", "name", "warmup", "max_window"})

# D-15: `tickers` is owned by add_ticker/remove_ticker — one path per concern.
_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})


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
		registry_store: `StrategyRegistryStore | None`
			D-09: the durable instance registry every mutating STRATEGY_COMMAND
			verb writes through. DECOMP-01a: the handler OWNS this — it is derived
			in ``__init__`` from ``(environment, sql_engine)`` via
			``StrategyRegistryStorageFactory``, not assigned by a caller after
			construction. ``None`` is the BACKTEST / in-memory path — every persist
			arm is then a clean no-op, exactly as the ``system_store is not None``
			gate degrades everywhere else, so the oracle path carries no store and
			no SQL. An explicitly passed ``registry_store`` still WINS: it is the
			override seam the tests inject through. Typed ``Any`` so the SQL stack
			stays off this module's import graph (GATE-01 inertness).
		"""
		self.global_queue: "EventBus" = global_queue
		self.feed: BarFeed = feed
		# CTX-02/D-02: the handler now OWNS its signal-store init from
		# (environment, sql_engine), mirroring the PortfolioHandler template
		# (LR-13). `SignalStorageFactory.create('backtest', sql_engine=None)` returns
		# the same `InMemorySignalStore` concrete the legacy path built, so the
		# backtest slice is byte-exact. An explicit `signal_store=` override still
		# wins (back-compat with the current positional compose call until 02-03).
		# `.signal_store` is the concrete `compose_engine` reads back onto the
		# Engine holder in plan 02-03.
		self.signal_store: SignalStore = (
			signal_store or SignalStorageFactory.create(environment, sql_engine=sql_engine)
		)
		# D-09 durable instance registry — DECOMP-01a: handler-OWNED, derived here
		# from (environment, sql_engine) exactly like signal_store above, so the
		# dep is REAL at construction rather than assigned by the live composition
		# root afterwards. `create('backtest', sql_engine=None)` returns None, so
		# the backtest path is unchanged and every persist arm short-circuits.
		# An explicit `registry_store=` override still wins — tested with `is not
		# None` rather than `or`, because a store object's truthiness is not part
		# of its contract and an `or` would silently re-derive on a falsy store.
		self.registry_store: "Optional[Any]" = (
			registry_store if registry_store is not None
			else StrategyRegistryStorageFactory.create(environment, sql_engine=sql_engine)
		)
		# D-10 injected strategy-type catalog — the access-control ALLOWLIST the `add`
		# verb resolves an untrusted external `strategy_type` through (catalog.py). None
		# is the backtest/in-memory path (`add` is never driven there); `add` LOUD-rejects
		# when it is None so no external payload can be instantiated. Typed `Any` so the
		# SQL/registry stack stays off this module's import graph (GATE-01 inertness).
		# DECOMP-01a: passed at CONSTRUCTION as a compose_engine kwarg (build_live_system
		# forwards its own `strategy_catalog`), not assigned afterwards.
		self.strategy_catalog: "Optional[Any]" = strategy_catalog
		# D-11 injected portfolio READ-model (PortfolioReadModel) — the flat-detect the
		# `remove` verb consults on FILL to know when a force-closed strategy is flat. A
		# READ through an injected read-model (the same seam the order domain uses), NOT a
		# cross-domain handler call, so the queue-only contract holds. Typed `Any` (GATE-01).
		# DECOMP-01a: compose_engine passes the `portfolio_handler` here on BOTH paths, so
		# this is NON-None in backtest too. Backtest stays unaffected because the
		# pending-removal machinery that reads it is never driven there: `on_fill` is not
		# on the backtest FILL route and STRATEGY_COMMAND routes to an empty list.
		self.portfolio_read_model: "Optional[Any]" = portfolio_read_model
		# D-11 pending-removal state. A `remove` force-flats FIRST and drops the object
		# only once the flat is OBSERVED on a later FILL cycle, so it is a PENDING state
		# (mirroring the pending-bracket / reconnect-resume precedents), not an inline
		# mutation. A name lives here from the `remove` command until `on_fill` sees its
		# positions flat; while pending, `get_strategies_universe` excludes its tickers so
		# the poll's REMOVE branch drives the P7 force-close, but its registry ROW is KEPT
		# until flat (crash-safety: restart rehydrates and resumes managing the positions).
		self._pending_removals: set[str] = set()
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
		"""Wire the dynamic universe for the WR-02 readiness gate (D-01).

		Called on BOTH paths — ``universe_wiring.wire_universe`` invokes it for
		backtest too (reached from ``backtest_runner._initialise_backtest_session``),
		so ``self._universe`` is NOT ``None`` in backtest. The oracle is nonetheless
		unaffected, and by construction rather than by absence: ``Universe.__init__``
		marks every member ``Readiness.READY`` and backtest membership derives FROM
		the strategy tickers, so ``is_ready(ticker)`` always holds at the per-tick
		gate in ``calculate_signals`` and the gate never skips — oracle-inert, proven
		by the byte-exact double-run.
		"""
		self._universe = universe

	def is_warm(self, symbol: str) -> bool:
		"""Aggregate per-symbol indicator warmth across concerned strategies (WR-02).

		Warm = for EVERY strategy CONCERNED with ``symbol`` (its ``.tickers``
		include it), that strategy's per-symbol indicators are warm
		(``strategy.is_ready(symbol)``). Vacuously ``True`` when NO strategy is
		concerned with the symbol (nothing to warm → nothing blocks readiness).

		This is the WR-02 read-model the ``UniverseHandler`` re-verifies before
		flipping a symbol READY + subscribing it: a swallowed partial strategy
		warmup can no longer let a half-warmed symbol become tradeable. Reflects
		INDICATOR warmth only — ``Strategy.is_ready`` is base handle-derived
		warmth (a handle-free ``PairStrategy`` is always ``is_ready`` True); the
		pair-specific spread warmth (``is_pair_ready``) is governed on the
		dispatch path, which is the WR-02 contract.
		"""
		return all(
			strategy.is_ready(symbol)
			for strategy in self.strategies
			if symbol in strategy.tickers
		)

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
			# D-07: the enable/disable gate — `is_active` (base.py:193) was an INERT
			# flag before P10 (flipped by activate/deactivate_strategy, read by
			# nothing); this wires it. Placed FIRST so the skip is unconditional and
			# covers the PairStrategy branch below (D-16: a pair uses the same gate).
			# A disabled strategy STAYS in self.strategies, but its indicator state
			# FREEZES at the current count rather than advancing (the same freeze the
			# P5-D10c/D14 gap skip relies on) — because this guard runs BEFORE
			# strategy.update below, that update never happens while disabled.
			#
			# ⚠ WD-1 — that freeze is exactly why `enable` does NOT trade the next bar.
			# The frozen values were computed over a window that now has an N-bar HOLE
			# spanning the disabled period; firing from them would let SMA/MACD silently
			# produce wrong values across a discontinuity, and warmth is monotone so
			# nothing downstream would ever notice. So `enable` calls
			# strategy.mark_unwarm() and the strategy must RE-WARM (~warmup bars) before
			# is_ready lets it signal again. WD-1 knowingly accepts that cost: never
			# compute a signal from a discontinuous window.
			#
			# Disable stops NEW entries only — open positions
			# and resting brackets run to natural exit via the execution layer, which
			# never reads this flag. Backtest-inert: is_active defaults True and no
			# backtest path deactivates, so the oracle stays byte-exact.
			if not strategy.is_active:
				continue
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
		# WR-01 (D-01): per-leg readiness gate mirroring the single-leg loop
		# (:179-180) for BOTH legs. Short-circuit the WHOLE pair dispatch (no
		# update_pair, no evaluate_pair) when EITHER leg is not universe-ready —
		# a pair must never burn cycles evaluating an unwarmed leg. Single None
		# check + two O(1) is_ready reads; default _universe is None → backtest
		# short-circuits on `is None` → byte-exact. AdmissionManager (07-08) is
		# the primary backstop; this is the cheap defensive strategy-loop layer.
		if self._universe is not None and (
			not self._universe.is_ready(ticker_A)
			or not self._universe.is_ready(ticker_B)
		):
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

	def on_bars_loaded(self, event: BarsLoaded) -> None:
		"""Warm the concerned strategies from a bulk warmup payload (D-03).

		Live-only consumer of the ``BarsLoaded`` bulk-transport event (wired in
		Plan 07; NEVER on the backtest path). For each strategy CONCERNED with
		``event.symbol`` (its ``.tickers`` include the symbol — the same
		predicate as the D-03 warmup targets), replay ``event.bars`` IN ORDER
		through the identical ``strategy.update(symbol, bar)`` path used by the
		per-tick loop — and NOTHING else. This is warmup, not trading (D-03):
		it does NOT call ``strategy.is_ready`` / ``generate_signal`` /
		``_emit_intent`` and never touches the signal store or the queue, so no
		tradeable signal is produced during warmup. The per-bar loop is
		intrinsic to the O(1) recurrence (D-03a — never vectorized); a strategy
		not concerned with the symbol is skipped.

		⚠ WR-02 — a live ``PairStrategy`` is NOT warmed by this ``BarsLoaded`` bulk
		path. Its spread bookkeeping (``_buf_A`` / ``_buf_B`` / ``_pair_bar_count``)
		fills ONLY via ``update_pair(bar_A, bar_B)`` (both legs together), never via
		the inherited single-leg ``update()`` this path replays. So an added or
		rehydrated pair warms from ~``beta_warmup`` + ``z_lookback`` LIVE bars via
		``_dispatch_pair`` instead — accepted P10 scope, and the ``is_pair_ready``
		gate already blocks any wrong trade in the meantime.

		Parameters
		----------
		event: `BarsLoaded`
			The bulk warmup payload for one ``(symbol, timeframe)`` — an
			immutable ``tuple[Bar, ...]`` reused verbatim from the queue (M5-02).
		"""
		for strategy in self.strategies:
			if event.symbol not in strategy.tickers:
				# Not concerned with this symbol — skip (no state churn).
				continue
			for bar in event.bars:
				# Warmup only (D-03): drive the O(1) recurrence, emit NOTHING.
				strategy.update(event.symbol, bar)

	def _persist_strategy(
		self, strategy: Strategy, event: StrategyCommandEvent
	) -> None:
		"""Write the strategy's post-mutation state to the durable registry (D-09).

		A clean no-op when no registry store is injected (the backtest/in-memory path).

		Writes the FULL post-mutation authoring set from ``encode_strategy_config``, never
		the incoming delta (T-10-37): a partial write would let the row drift from the
		live instance, and the row is what rehydrate reconstructs from at restart — a
		divergence there resurrects a strategy that never existed.

		``at`` comes from ``event.time`` — the event's BUSINESS time, never wall clock.
		The store is clock-free by contract (caller-supplied ``at``), so the audit trail
		stays reproducible (T-10-40).

		The codec import is LAZY (function-local) and MUST stay that way: the
		``strategy_handler/registry/`` collaborator reaches the store, so a module-top
		import here would pull SQL onto the BACKTEST import graph and break GATE-01
		inertness (T-10-38, gated by ``test_okx_inertness.py``).
		"""
		if self.registry_store is None:
			return
		from itrader.strategy_handler.registry.config_codec import (
			encode_strategy_config,
		)

		self.registry_store.upsert(
			strategy_name=strategy.name,
			strategy_type=type(strategy).__name__,
			config=encode_strategy_config(strategy),
			enabled=strategy.is_active,
			at=event.time,
		)

	def _request_rewarm(self, strategy: Strategy) -> None:
		"""Drive an unwarmed strategy's symbols back through the P7 warmup pipeline (WD-1).

		``mark_unwarm`` alone is already CORRECT — ``is_ready``/``is_pair_ready`` gate
		emission, so the strategy simply re-warms from live bars and cannot signal off a
		holed window either way. This method only makes it FAST: without it a re-enabled
		1d strategy would wait ~``warmup`` real bars (100 days for SMA_MACD) before
		trading again, which is a control-plane verb behaving like a decommission.

		There is no strategy-level warm API to call — the warmup pipeline is per-SYMBOL
		and owned by ``UniverseHandler`` behind the queue boundary. Its existing trigger
		is the CR-02 FAILED-retry: a still-desired member whose readiness is FAILED is
		re-warmed on the next poll (``on_poll`` flips it PENDING and folds it into
		``added`` -> ``_begin_warmup`` -> ``BarsLoaded`` -> ``on_bars_loaded`` replays the
		window through ``strategy.update``). So marking this strategy's symbols FAILED and
		letting the ``enable`` follow-on poll land IS the re-warm request — the same path
		Plan 07's ``add`` will reuse (WD-1: one warm path, not two). No new event type, no
		cross-domain call.

		``_universe`` is None on the backtest/in-memory path, where there is no warmup
		pipeline at all and the passive re-warm above is the whole story — hence the
		short-circuit (and the oracle stays byte-exact: no backtest path emits a verb).

		Two accepted consequences, both bounded and self-healing:
		  - a symbol shared with an already-warm sibling strategy goes dark for ONE poll
		    interval (readiness is per-symbol and aggregate by design, ``is_warm``);
		  - the replayed warmup bars are re-delivered to that warm sibling, which the
		    CR-01 monotonic guard in ``Strategy.update`` rejects before any state
		    mutation. That guard exists for exactly this re-warm case.
		"""
		if self._universe is None:
			return
		for ticker in strategy.tickers:
			# mark_failed (not mark_pending): only FAILED members are collected by the
			# CR-02 retry in on_poll, so PENDING would leave the symbol dark FOREVER —
			# the silent-permanent-no-warm failure mode. The re-warm streak counter is
			# incremented at the FAILURE sites, not here, so this raises no false alarm.
			self._universe.mark_failed(ticker)

	def _portfolio_id_from(
		self, event: StrategyCommandEvent
	) -> "Optional[PortfolioId | int]":
		"""Parse ``config["portfolio_id"]`` into the handle the fan-out expects, or None.

		The payload is operator/FastAPI-supplied and therefore untrusted (T-10-35): the
		light verbs read ONLY this one key, and it is validated + PARSED here so a
		malformed payload never reaches live strategy state or SQL. A miss returns None
		and the caller makes it a loud no-op — this path must never raise into the queue.

		⚠ The parse is a CORRECTNESS requirement, not a typing nit — the same defect
		10-05 hit on the rehydrate arm. ``subscribed_portfolios`` is typed
		``list[PortfolioId | int]``, and ``calculate_signals`` fans each intent out over
		it and casts each id STRAIGHT onto ``SignalEvent.portfolio_id`` (FL-02: "the
		runtime value is always a UUIDv7-backed PortfolioId"). A bare ``str`` sails
		through that cast unchallenged and reaches the portfolio lookup as an id matching
		NOTHING: the subscription would look perfectly healthy and then fan signals into
		the void. Value-equality assertions pass while the type is wrong, so this is
		pinned by a TYPE assertion.

		Mirrors ``registry/rehydrate.py::_resolve_portfolio_id`` (UUID first, then the
		legacy ``int`` arm the union still permits) but returns None instead of raising:
		rehydrate quarantines a bad instance at boot, whereas a bad runtime command is a
		loud no-op.
		"""
		config = event.config
		if not isinstance(config, dict):
			return None
		raw = config.get("portfolio_id")
		if not isinstance(raw, str) or not raw:
			return None
		try:
			return PortfolioId(uuid.UUID(raw))
		except (ValueError, AttributeError, TypeError):
			pass
		try:
			return int(raw)
		except (ValueError, TypeError):
			return None

	def _add_strategy_verb(self, event: StrategyCommandEvent) -> None:
		"""D-10 `add`: catalog-gate -> construct DARK -> persist -> warm via the P7 poll.

		The phase's highest-value trust boundary (T-10-41): an operator/FastAPI-supplied
		``strategy_type`` + config becomes a live Python object. Every rejection below is a
		LOUD no-op (``logger.warning`` + return) that registers and persists NOTHING — a
		half-built strategy never enters the roster.

		D-10 access control: the injected ``strategy_catalog`` IS the allowlist. Without it
		nothing may be instantiated from an external payload, and resolution goes ONLY
		through ``build_strategy`` -> ``decode_strategy_config`` -> ``resolve_strategy_class``
		(a closed dict lookup). This branch NEVER resolves a type by dynamic module import
		or by evaluating the payload as source text — either would turn the operator API
		into remote code execution.

		D-01 one reconstruction path: ``add`` builds through the IDENTICAL ``build_strategy``
		path rehydrate uses, so the two cannot drift. Construction runs the real
		``_apply_params`` -> ``validate()`` -> ``_run_init()``, so unknown/missing-param
		rejection and warmup re-derivation happen on the real path.

		D-10 warm-via-P7: a freshly constructed instance is DARK (its handles are reset at
		construction, so ``is_ready`` is False until bars feed it). The emitted
		``UniversePollEvent`` IS the whole warmup wiring: membership is derived FROM the
		registered strategies (``StrategyDerivedSelectionModel``), so the poll re-selects,
		the new symbol enters the universe, and the EXISTING P7 pipeline runs
		``spawn_warmup`` -> ``BarsLoaded`` -> ``on_bars_loaded`` (mark_ready) -> it trades;
		a ``BarsLoadFailed`` -> FAILED -> CR-02 retry next poll. This works on a COLD
		symbol, which is the COMMON case — add-only-if-already-warm was rejected precisely
		because it would refuse any genuinely new symbol. NO second warmup path is built:
		``live_bar_feed`` explicitly refuses a second state-building path (LX-09), and a
		parallel path would re-open the paper-replay parity gate.

		Queue-only: the poll is emitted on ``self.global_queue``; this NEVER calls
		``UniverseHandler`` or touches ``Universe``.
		"""
		# D-10 catalog gate — the access-control allowlist. Its absence is a LOUD reject:
		# without an injected catalog nothing may be instantiated from an external payload.
		# We resolve types ONLY through the injected allowlist (build_strategy below), never
		# by consulting the import system or interpreting the payload as source text — that
		# would convert the operator API into arbitrary code execution.
		if self.strategy_catalog is None:
			self.logger.warning(
				'add for strategy %s refused — no strategy_catalog injected; an external '
				'payload may only be instantiated through the injected allowlist (D-10)',
				event.strategy_name)
			return
		config = event.config
		if not isinstance(config, dict) or not isinstance(config.get("strategy_type"), str):
			# A malformed payload (no config, or no string strategy_type key) — loud no-op.
			self.logger.warning(
				'add for strategy %s carries no string strategy_type in its config '
				'payload — ignored', event.strategy_name)
			return
		strategy_type = config["strategy_type"]
		# D-02 duplicate-name loud reject BEFORE any construction — a collision would
		# silently shadow another instance and overwrite its persisted state. Pre-checked
		# by name (rather than catching add_strategy's raise) so nothing is constructed.
		if any(existing.name == event.strategy_name for existing in self.strategies):
			self.logger.warning(
				'add for strategy %s refused — a strategy with that name is already '
				'registered (D-02); the existing instance is left untouched',
				event.strategy_name)
			return
		# Lazy imports (GATE-01): the registry collaborators reach the store, so a
		# module-top import would pull SQL onto the BACKTEST import graph. required_base_depth
		# is pure feed logic but is imported here too so the whole add path stays local.
		from itrader.core.exceptions import MissingParamError, UnknownParamError
		from itrader.price_handler.feed.cache_registration import (
			UnwarmableTimeframeError,
			required_base_depth,
		)
		from itrader.strategy_handler.registry.catalog import UnknownStrategyTypeError
		from itrader.strategy_handler.registry.config_codec import StrategyConfigError
		from itrader.strategy_handler.registry.rehydrate import build_strategy

		# Build the row-shaped record from the payload. The config_json blob is the payload
		# MINUS portfolio_id (a subscription is a child-table concern, NOT a declared param —
		# leaving it in the blob would make build_strategy's _apply_params raise
		# UnknownParamError). strategy_type stays IN the blob (an envelope key decode reads)
		# AND is the top-level column; the two agree because the .add factory folds one value
		# into both. build_strategy is the IDENTICAL path rehydrate uses (D-01).
		blob = {key: value for key, value in config.items() if key != "portfolio_id"}
		rec = {
			"strategy_name": event.strategy_name,
			"strategy_type": strategy_type,
			"config_json": blob,
		}
		try:
			strategy = build_strategy(rec, catalog=self.strategy_catalog)
		except (
			UnknownStrategyTypeError,
			StrategyConfigError,
			UnknownParamError,
			MissingParamError,
		) as exc:
			# Every construction failure is a loud no-op naming the error KIND (not the
			# payload values — the P8 declared-fields-only precedent). Caught by SPECIFIC
			# type, never a bare except: a store/driver fault must not be silently eaten.
			self.logger.warning(
				'add for strategy %s rejected (%s) — nothing registered or persisted',
				event.strategy_name, type(exc).__name__)
			return
		# F-1 warmability gate. `cache_capacity()` re-derives lazily, but an existing ring is
		# a `deque(maxlen=...)` fixed at creation (live_bar_feed) and CANNOT resize, so
		# re-registering a deeper consumer does not deepen it — a strategy needing more base
		# bars than the ring holds would register, stay is_ready False FOREVER, and emit
		# nothing while raising nothing. That silent permanent no-trade is a correctness
		# defect, so reject loudly instead. Keyed on `base_timeframe`: only the LIVE feed
		# carries it (a property on LiveBarFeed), so the backtest/in-memory feed (which has
		# no base_timeframe) skips the gate cleanly — the plan's own degrade arm, keyed on
		# the attribute rather than a redundant injected handle (self.feed already exists,
		# audit 10-07 F1). Ring RESIZE is deferred to
		# .planning/todos/pending/strategy-timeframe-finer-than-base-resubscribe.md.
		base_timeframe = getattr(self.feed, "base_timeframe", None)
		if base_timeframe is not None:
			try:
				depth = required_base_depth(
					strategy.warmup, strategy.timeframe, base_timeframe)
			except UnwarmableTimeframeError as exc:
				# A finer-than-base (or non-multiple) timeframe can never warm from the ring.
				self.logger.warning(
					'add for strategy %s rejected (%s) — its timeframe cannot be served '
					'from the feed base cadence', event.strategy_name, type(exc).__name__)
				return
			capacity = self.feed.cache_capacity()
			if depth > capacity:
				self.logger.warning(
					'add for strategy %s rejected — needs %d base bars but the feed ring '
					'holds only %d (an existing deque maxlen is fixed at creation and '
					'cannot resize, so it would stay permanently dark)',
					event.strategy_name, depth, capacity)
				return
		# Register through add_strategy (its SHORT-01/D-07 direction gate + the IN-01/IN-06
		# min_timeframe block). D-02 duplicate is already pre-checked, so the only remaining
		# raise is the SHORT-01 system-config mismatch — convert THAT to a loud no-op so an
		# operator add never raises into the queue.
		try:
			self.add_strategy(strategy)
		except ValueError as exc:
			self.logger.warning(
				'add for strategy %s rejected — %s (a non-LONG_ONLY strategy needs the '
				'handler short-enabled, SHORT-01/D-07)', event.strategy_name, exc)
			return
		# Subscribe any portfolio_id carried alongside the config (parsed + type-checked at
		# the boundary, T-10-35; a bare str would fan signals at a portfolio matching
		# nothing). Absent -> the strategy computes but fans out to nobody (a legal state,
		# D-09), and the subscribe_portfolio verb can wire it later.
		portfolio_id = self._portfolio_id_from(event)
		if portfolio_id is not None:
			strategy.subscribe_portfolio(portfolio_id)
		# Persist parent-first (the child FK requires the registry row to exist first).
		self._persist_strategy(strategy, event)
		if portfolio_id is not None and self.registry_store is not None:
			self.registry_store.add_portfolio_subscription(
				strategy_name=strategy.name, portfolio_id=str(portfolio_id))
		# The poll IS the warmup wiring (D-10) — see the method docstring. Queue-only.
		self.global_queue.put(UniversePollEvent(time=event.time))

	def _remove_strategy_verb(
		self, event: StrategyCommandEvent, strategy: Strategy
	) -> None:
		"""D-11 `remove`: force-flat FIRST, hold PENDING across cycles, then drop.

		The three lifecycle behaviours stay DISTINCT and are never conflated:
		  - ``disable`` -> stop NEW entries, KEEP open positions + resting brackets (D-07);
		  - ``remove`` -> force-flat, WAIT flat, then drop the object + delete the rows;
		  - ``reconfigure`` -> apply live, KEEP positions (D-12, Plan 08).

		Orphaning positions on remove was REJECTED: a removed strategy's positions would
		become unmanaged (no exit logic owns them, and on a bracket-less instrument nothing
		closes them). So the sequence is deactivate -> pending -> persist ``enabled=False``
		-> poll (drive the P7 force-close) -> only drop once the flat is observed on a FILL.

		Because the flat is observed on a LATER event cycle, this is a PENDING state (the
		``_pending_removals`` set), mirroring the pending-bracket and reconnect-resume
		precedents — not an inline mutation.

		THE load-bearing design call (recorded in the SUMMARY): the force-close is driven by
		making the strategy's symbols LEAVE the derived membership. ``get_strategies_universe``
		excludes a pending-removal strategy's tickers, so the follow-on ``UniversePollEvent``
		re-derives membership WITHOUT them, the poll's REMOVE branch fires
		``_on_symbol_removed`` for its now-unmembered symbols, and the EXISTING P7 force-close
		-> detach-on-flat machinery manages the positions out — reusing the pipeline verbatim
		(D-11) rather than building a second force-close path. The instance STAYS in
		``self.strategies`` and its ROW is KEPT (persisted ``enabled=False``) until flat: a
		crash mid-force-close then rehydrates the strategy PRESENT-BUT-DEACTIVATED (CR-01 —
		``read_all`` loads the disabled row and ``deactivate_strategy()`` re-applies it) and
		it resumes managing its own positions rather than orphaning them. Queue-only: the
		poll is emitted here; ``UniverseHandler`` is never called and ``Universe`` is never
		touched.

		⚠ CAVEAT — no auto-resume. An interrupted ``remove`` does NOT re-drive the
		force-close on restart: the rehydrated strategy comes back merely deactivated
		(``_pending_removals`` is in-memory only and is NOT reconstructed), so the operator
		must RE-ISSUE ``remove`` to complete the drop. Auto-resume of an in-flight removal is
		deferred to the live-hardening milestone.

		⚠ FOOTGUN — after a restart a strategy mid-``remove`` is INDISTINGUISHABLE from a
		merely-``disable``d one: both come back present-and-dark (``enabled=False``,
		``is_active`` False), because the removing/disabled distinction lived only in the
		in-memory ``_pending_removals`` set. Re-issuing the intended verb after a restart is
		how the operator disambiguates.
		"""
		# Idempotency: a name already pending is a no-op — no second force-close, no second
		# poll (D-10 idempotency). The unknown-name case is the shared loud no-op upstream.
		if strategy.name in self._pending_removals:
			return
		# Deactivate FIRST — the D-07 `is_active` gate stops NEW entries while the
		# force-close plays out (this is why D-07 is a Plan 03 dependency).
		if strategy.is_active:
			strategy.deactivate_strategy()
		# Enter the pending state BEFORE emitting the poll, so get_strategies_universe
		# already excludes this strategy when the poll re-derives membership.
		self._pending_removals.add(strategy.name)
		# Persist enabled=False — the row must reflect "should not be trading" even if the
		# process dies mid-removal. Do NOT delete the row here: D-11's order is force-flat
		# -> wait flat -> THEN drop. Deleting first would leave a crash mid-force-close with
		# open positions and no row to rehydrate, so no owner: orphaned.
		self._persist_strategy(strategy, event)
		# The poll drives the P7 force-close (see the docstring). Queue-only.
		self.global_queue.put(UniversePollEvent(time=event.time))
		# Complete immediately when the flat condition already holds (the no-position case
		# completes on the same cycle, D-11).
		self._try_complete_removal(strategy)

	def _strategy_is_flat(self, strategy: Strategy) -> bool:
		"""True when NONE of ``strategy``'s tickers are held in any subscribed portfolio.

		A READ through the injected ``PortfolioReadModel`` (``get_position``), which the
		queue-only rule permits (reads go through injected read-models; only writes are
		queue-mediated). Checks the strategy's tickers across its subscribed portfolios, so
		a pair's BOTH legs must be flat (D-16).

		With no read model injected there is nothing to observe: return True. Since
		DECOMP-01a this arm is UNREACHABLE from either composition root — compose_engine
		passes the portfolio_handler on both paths — so it now guards only
		directly-constructed handlers (the unit tests) rather than the backtest path it
		was originally written for. Kept as a defensive default, not a live degrade arm.
		A strategy with no subscribed portfolios is likewise vacuously flat.
		"""
		read_model = self.portfolio_read_model
		if read_model is None:
			return True
		for portfolio_id in strategy.subscribed_portfolios:
			for ticker in strategy.tickers:
				if read_model.get_position(portfolio_id, ticker) is not None:
					return False
		return True

	def _try_complete_removal(self, strategy: Strategy) -> None:
		"""Drop + delete a pending-removal strategy IFF its positions are now flat (D-11).

		Only once flat: drop the object from ``self.strategies``, delete the rows (the store
		removes the portfolio-subscription CHILD rows BEFORE the ``strategy_registry`` parent
		— P-6; the FK forbids the reverse and the SQLite ``PRAGMA foreign_keys=ON`` hook
		enforces it on both dialects), discard the name from ``_pending_removals``, and
		recompute ``min_timeframe`` (it was derived at ``add_strategy`` time and dropping the
		only strategy at the minimum leaves it stale).
		"""
		if not self._strategy_is_flat(strategy):
			return
		if strategy in self.strategies:
			self.strategies.remove(strategy)
		if self.registry_store is not None:
			# Child-then-parent delete (P-6) — the store owns the FK ordering.
			self.registry_store.delete(strategy.name)
		self._pending_removals.discard(strategy.name)
		self._recompute_min_timeframe()

	def _recompute_min_timeframe(self) -> None:
		"""Re-derive ``min_timeframe`` from the current roster after a drop (IN-01/IN-06).

		``min_timeframe`` is derived only in ``add_strategy`` and never recomputed on
		removal, so dropping the strategy at the minimum would leave it stale. An EMPTY
		roster returns to the ``None`` seed — the legal "no strategies" state (IN-06),
		mirroring the None-seed handling in ``add_strategy``.
		"""
		if not self.strategies:
			self.min_timeframe = None
			return
		self.min_timeframe = min(strategy.timeframe for strategy in self.strategies)

	def on_fill(self, event: "Any") -> None:
		"""D-11 completion hook: drop a pending-removal strategy once its positions are flat.

		The three lifecycle behaviours stay DISTINCT (never conflated): ``disable`` stops
		NEW entries and KEEPS open positions + brackets; ``remove`` force-flats, waits flat,
		then drops; ``reconfigure`` applies live and KEEPS positions.

		The removal spans event cycles, so it is a PENDING state (like pending-bracket and
		reconnect-resume) — not an inline mutation. On each FILL this re-scans EVERY pending
		removal's flatness via the injected ``PortfolioReadModel`` (a READ through an
		injected read-model, which the queue-only rule permits — ``PortfolioHandler`` is
		never imported) and completes the ones that reached flat. It re-scans all pending
		removals rather than keying on ``event.ticker`` so a multi-leg strategy completes on
		whichever fill flattens its LAST open leg.

		Wired on the LIVE FILL route only (``route_registrar``), AFTER
		``PortfolioHandler.on_fill`` so the read model already reflects the settled (flat)
		position. It is NOT on the backtest ``_routes`` FILL list at all, so it never runs on
		the byte-exact oracle path (and ``_pending_removals`` is empty there regardless).
		"""
		if not self._pending_removals:
			return
		by_name = {strategy.name: strategy for strategy in self.strategies}
		for name in list(self._pending_removals):
			strategy = by_name.get(name)
			if strategy is None:
				# Already dropped — a stale pending entry; clear it defensively.
				self._pending_removals.discard(name)
				continue
			self._try_complete_removal(strategy)

	def _reconfigure_allowlist_check(self, config: dict[str, Any]) -> "Optional[str]":
		"""D-15 deny-list gate — returns a rejection reason or None (audit 10-08 F2).

		Deny ONLY the two closed sets (IMMUTABLE identity/derived, VERB-ONLY tickers) and
		let the existing ``_apply_params`` unknown-param rejection own the rest — a positive
		mutable-allowlist would be a second hand-maintained list that drifts from the class
		annotations. Called BEFORE the trial construction so a refused key never even builds a
		throwaway.
		"""
		for key in config:
			if key in _RECONFIGURE_IMMUTABLE:
				return (
					f"{key!r} is immutable via reconfigure — it is identity/derived state; "
					f"changing the class or renaming is remove + add (D-15)")
			if key in _RECONFIGURE_VERB_ONLY:
				return (
					f"{key!r} is owned by the add_ticker/remove_ticker verbs, not "
					f"reconfigure — one path per concern (D-15)")
		return None

	def _reconfigure_warmability_check(self, trial: Strategy) -> "Optional[str]":
		"""D-15/F-1 timeframe + capacity gate against the TRIAL — reason or None.

		Runs on the LIVE feed only (keyed on ``base_timeframe``: the backtest feed has none,
		so the whole arm skips cleanly — the same degrade the D-10 ``add`` gate uses, audit
		10-07 F1). ``required_base_depth`` raises ``UnwarmableTimeframeError`` for a
		finer-than-base timeframe (the ring holds base bars, and the WR-01 off-grid guard would
		actively DROP sub-base bars even if they arrived) and for a non-multiple. The capacity
		gate then rejects a depth the ring can never serve: ``cache_capacity()`` re-derives
		lazily, but an existing ring is a ``deque(maxlen=...)`` fixed at creation
		(``live_bar_feed``) and CANNOT resize, so a deeper consumer would leave the strategy
		``is_ready`` False FOREVER — registered, silent, error-free, never trading. Reject
		loudly (F-1) rather than accept-and-dark; ring RESIZE is deferred to
		.planning/todos/pending/strategy-timeframe-finer-than-base-resubscribe.md. Evaluating
		against the TRIAL (its resolved ``warmup``/``timeframe``) covers BOTH a timeframe change
		AND a window-grow that would exceed capacity — a superset of the plan's timeframe-only
		scoping, and strictly safer.
		"""
		base_timeframe = getattr(self.feed, "base_timeframe", None)
		if base_timeframe is None:
			return None
		# Lazy (GATE-01): the feed cache-registration module is pure feed logic, imported
		# locally so the whole reconfigure path stays import-light and consistent with `add`.
		from itrader.price_handler.feed.cache_registration import (
			UnwarmableTimeframeError,
			required_base_depth,
		)
		try:
			depth = required_base_depth(trial.warmup, trial.timeframe, base_timeframe)
		except UnwarmableTimeframeError:
			return (
				"the requested timeframe cannot be served from the feed base cadence "
				"(finer than base, or not a whole multiple) — F-1/D-15")
		capacity = self.feed.cache_capacity()
		if depth > capacity:
			return (
				f"the requested timeframe needs {depth} base bars but the feed ring holds "
				f"only {capacity} (a fixed-maxlen deque cannot resize, so the strategy would "
				f"stay permanently dark) — F-1")
		return None

	def _emit_reconfigure_apply_failure(
		self, event: StrategyCommandEvent, strategy: Strategy, exc: Exception
	) -> None:
		"""D-13 apply-fail egress: a CRITICAL ``ErrorEvent`` on the queue (T-10-58).

		The trial already proved ``cls(**params)`` good, so a raise from the live
		``strategy.reconfigure`` is genuinely exceptional. Per D-13 the persist has ALREADY
		succeeded (the DB holds the NEW config and a restart rehydrates the intended
		configuration), so this does NOT roll back — it reports. The alert binds
		``strategy_name`` + the error KIND ONLY (the P8 declared-fields-only precedent) so no
		config value leaks to the operator channel. Queue-only egress (the handler has no
		alert_sink; this is how it raises an alarm mid-loop), consumed by the ERROR route.
		"""
		from itrader.core.enums import ErrorSeverity
		from itrader.events_handler.events import ErrorEvent

		self.logger.error(
			'reconfigure for strategy %s PERSISTED but APPLY threw (%s) — the DB holds the '
			'new config and a restart heals; the live instance is unchanged',
			event.strategy_name, type(exc).__name__)
		self.global_queue.put(ErrorEvent(
			time=event.time,
			source="strategies",
			error_type=type(exc).__name__,
			error_message=(
				f"Strategy {event.strategy_name!r} reconfigure persisted but apply threw "
				f"({type(exc).__name__}); the DB holds the new config and a restart heals"),
			operation="reconfigure",
			severity=ErrorSeverity.CRITICAL,
			details={"strategy_name": event.strategy_name, "error_kind": type(exc).__name__}))

	def _reconfigure_strategy_verb(
		self, event: StrategyCommandEvent, strategy: Strategy
	) -> None:
		"""D-12/D-13/D-14/D-15 `reconfigure`: trial-validate -> persist -> apply -> re-warm.

		The STRAT-03 atomicity contract. ``_apply_params`` is ALREADY atomic (its WR-02
		resolve-into-locals trial phase commits at ``base.py:295-299``, so a rejected apply
		raises before mutating ``self``), and the single engine thread draining the queue
		ALREADY provides the D-13 quiesce (no signal is in flight between event cycles — no
		lock, no pause mechanism). The genuine tear is that ``Strategy.reconfigure`` calls
		``validate()`` + ``_run_init()`` AFTER that commit, so a cross-field ``validate()``
		failure would leave a LIVE, trading strategy mutated into a state its own validator
		rejects. The fix is a THROWAWAY construction: ``cls(**params)`` runs the whole
		validate chain before the live instance is touched. No hand-rolled snapshot/rollback.

		Order (D-13): allowlist -> merge -> trial-validate -> direction re-gate -> warmability
		-> persist -> apply -> re-warm. Persist precedes apply so the DB and the live instance
		never diverge in the applied-but-unpersisted direction (apply-then-persist was
		rejected: a persist failure would silently lose the change on restart).
		"""
		config = event.config
		if not isinstance(config, dict):
			self.logger.warning(
				'reconfigure for strategy %s carries no config payload — ignored',
				event.strategy_name)
			return
		# D-15 deny-list BEFORE any construction (audit 10-08 F2) — a refused key must not
		# even build a throwaway.
		reason = self._reconfigure_allowlist_check(config)
		if reason is not None:
			self.logger.warning(
				'reconfigure for strategy %s refused — %s', event.strategy_name, reason)
			return
		# D-10 catalog gate: decode needs the injected allowlist to resolve the class. None is
		# the backtest/in-memory path (reconfigure is never driven there) — a clean loud no-op.
		if self.strategy_catalog is None:
			self.logger.warning(
				'reconfigure for strategy %s refused — no strategy_catalog injected (D-10)',
				event.strategy_name)
			return
		# Lazy imports (GATE-01): the registry/codec collaborators reach the store, so a
		# module-top import would pull SQL onto the BACKTEST import graph (test_okx_inertness).
		from itrader.core.exceptions import MissingParamError, UnknownParamError
		from itrader.core.policy_codec import default_policy_registry
		from itrader.strategy_handler.registry.catalog import UnknownStrategyTypeError
		from itrader.strategy_handler.registry.config_codec import (
			StrategyConfigError,
			decode_strategy_config,
			encode_strategy_config,
		)

		# P-4 MERGE in ENCODED blob space (audit 10-08 F3): overlay the partial delta on the
		# CURRENT full authoring blob. An omitted field keeps its prior instance value (encode
		# captured it); an empty/identical payload merges to an identical blob -> no-op.
		current_blob = encode_strategy_config(strategy)
		merged_blob = current_blob | dict(config)
		if merged_blob == current_blob:
			# D-13 idempotency + empty: nothing changed -> no persist, no apply, no re-warm,
			# no poll (the D-09 no-control-plane-churn contract). Stays warm.
			return
		# D-13 TRIAL-VALIDATE. Route the merged blob back through decode_strategy_config — the
		# ONLY function that knows the inverse coercions (Decimal via to_money, policies via
		# decode_policy, envelope-key stripping, `name` from the PK) — into PARAM space, then
		# construct a THROWAWAY. Routing the MERGE (blob space) straight into the constructor
		# (param space) without this decode is the 10-04 defect re-entering: `entry_z` would
		# land as the str '2'. The constructor runs _apply_params + validate() + _run_init(),
		# so a cross-field validation failure raises HERE, against the throwaway, with the
		# LIVE instance untouched.
		rec = {
			"strategy_name": strategy.name,
			"strategy_type": type(strategy).__name__,
			"config_json": merged_blob,
		}
		try:
			cls, params = decode_strategy_config(
				rec, self.strategy_catalog, default_policy_registry())
			trial = cls(**params)
		except (
			StrategyConfigError,
			UnknownStrategyTypeError,
			UnknownParamError,
			MissingParamError,
			ValueError,
		) as exc:
			# Loud no-op naming the error KIND (not the payload values — the P8
			# declared-fields-only precedent). SPECIFIC types (ValueError covers validate()
			# + the _apply_params tickers/enum guards); never a bare except, so a store/infra
			# fault is not silently eaten.
			self.logger.warning(
				'reconfigure for strategy %s rejected (%s) — live instance untouched',
				event.strategy_name, type(exc).__name__)
			return
		# SHORT-01/D-07 direction re-gate (audit 10-08 F1 — the phase's most dangerous fix).
		# validate() does NOT check direction, and the SHORT-01 gate reads HANDLER state, so
		# the trial construction CANNOT catch a short-enabling direction change. Re-run the
		# SHARED predicate against the TRIAL's resolved direction BEFORE persist: a
		# non-LONG_ONLY direction is admitted ONLY when both flags are on. Without this, an
		# external reconfigure(direction=SHORT_ONLY) on a no-margin engine would sail through
		# onto a live strategy — the exact capability SHORT-01 exists to gate (T-10-55).
		if not self._direction_admissible(trial.direction):
			self.logger.warning(
				'reconfigure for strategy %s refused — a non-LONG_ONLY direction requires '
				'BOTH allow_short_selling AND enable_margin (SHORT-01/D-07)',
				event.strategy_name)
			return
		# D-15/F-1 warmability gate against the TRIAL (finer-than-base / non-multiple /
		# over-capacity). Skips cleanly on the backtest feed.
		reason = self._reconfigure_warmability_check(trial)
		if reason is not None:
			self.logger.warning(
				'reconfigure for strategy %s refused — %s', event.strategy_name, reason)
			return
		# D-13 PERSIST FIRST, from the TRIAL's FULL authoring set (P-4: never the partial
		# delta — a partial write would let the row drift from the live instance and silently
		# revert unchanged fields on restart). `enabled` is the LIVE strategy's current
		# activation (a fresh trial is is_active=True; reconfigure does not change activation).
		# A persist FAILURE propagates as infrastructure (the _add_strategy_verb / rehydrate
		# D-19 fail-loud precedent) — but the LIVE instance is UNTOUCHED because persist
		# precedes apply, so the DB and live never diverge in the applied-but-unpersisted
		# direction (D-13: apply-then-persist was rejected). Degrades clean when
		# registry_store is None.
		if self.registry_store is not None:
			self.registry_store.upsert(
				strategy_name=strategy.name,
				strategy_type=type(strategy).__name__,
				config=encode_strategy_config(trial),
				enabled=strategy.is_active,
				at=event.time)
		# D-13 APPLY to the live instance, proven good by the trial. Application happens
		# BETWEEN event cycles on the single engine thread, so no signal is in flight
		# mid-apply — in the single-writer model that IS the STRAT-03 quiesce. When apply
		# nonetheless throws, log/emit CRITICAL and do NOT roll back the persist: the DB holds
		# the NEW config and a restart heals (the deliberate persist-then-apply asymmetry).
		try:
			strategy.reconfigure(**params)
		except (
			StrategyConfigError,
			UnknownParamError,
			MissingParamError,
			ValueError,
		) as exc:
			self._emit_reconfigure_apply_failure(event, strategy, exc)
			return
		# D-12: NO force-flat. Open positions stay open and their subsequent exits are
		# governed by the NEW params — explicitly the operator's responsibility. always-flatten
		# (a harmless sizing tweak would close positions) and param-classified flatten were
		# both rejected.
		#
		# D-14 RE-WARM via the WD-2 seam. `Strategy.reconfigure -> _run_init` UNCONDITIONALLY
		# resets the per-symbol handle state (base.py:409/426), so a handle-bearing instance is
		# DARK after ANY applied reconfigure — `is_ready` is False until it re-warms (verified
		# against the live tree; the plan's "shrank/unchanged stays warm" premise is false for
		# exactly this reason, and preserving warmth would need a conditional `_run_init` on
		# the base HOT PATH — oracle risk — deferred). `mark_unwarm` is the WD-2 seam
		# (idempotent here since `_run_init` already reset; also covers the PairStrategy
		# override if a pair ever reached this path), and `_request_rewarm` marks the symbols
		# FAILED so the CR-02 retry re-warms them on the follow-on poll — the SAME warm path
		# `enable`/`add` use (WD-1: one warm path). During the dark re-warm the instance cannot
		# emit STRATEGY-driven exits, so an open position rides its resting exchange SL/TP
		# brackets until warm (D-14, documented consequence, not a blocker).
		strategy.mark_unwarm()
		self._request_rewarm(strategy)
		self.global_queue.put(UniversePollEvent(time=event.time))

	def on_strategy_command(self, event: StrategyCommandEvent) -> None:
		"""Apply one control-plane verb to one strategy, live AND durably (D-09).

		The STRAT-02 dispatch surface (live-only). Locates the strategy whose ``.name``
		matches ``event.strategy_name`` — the durable per-instance identity (D-02) — and
		applies the verb IDEMPOTENTLY. The LIGHT verbs (no force-flat, no construction):

		- ``enable`` — D-07 ``is_active`` True + persist ``enabled=True``, then FORCE A
		  RE-WARM (WD-1, see the enable branch below). It does NOT trade the next bar.
		- ``disable`` — ``is_active`` False + persist ``enabled=False``. The object STAYS
		  in ``self.strategies``; open positions and resting brackets run to natural exit
		  via the execution layer (which never reads this flag). Stops NEW entries only.
		  ACROSS A RESTART (CR-01): a disabled strategy is now REHYDRATED present-but-dark
		  (``read_all`` loads it, then ``deactivate_strategy()`` re-applies ``is_active``
		  False) — it is re-enable-able and still owns its positions. It is no longer
		  silently dropped at boot (which would orphan its positions and make it permanently
		  unreachable after a restart).
		- ``subscribe_portfolio`` / ``unsubscribe_portfolio`` — D-06/D-09: the fan-out
		  edge is RUNTIME-MUTABLE. Mutates ``strategy.subscribed_portfolios`` live and
		  upserts/deletes the child row. Unsubscribing the LAST portfolio leaves an empty
		  list and zero rows — a LEGAL state (the strategy computes but fans out to
		  nobody), not an error.
		- ``add_ticker`` / ``remove_ticker`` — the v1.7 membership verbs, now ALSO
		  persisting (D-09: a ticker change IS a reconfigure of the ``tickers`` authoring
		  param). ``remove_ticker`` still refuses a remove that would empty the list (the
		  non-empty ``list[str]`` invariant, base.py).

		``add`` / ``remove`` (Plan 07) and ``reconfigure`` (Plan 08) fall through to the
		unknown-verb no-op here.

		D-09 idempotency (IN-02): the ``mutated`` flag gates BOTH the persist and the
		follow-on — a no-op verb mutates nothing, persists nothing and emits nothing (no
		control-plane churn). An unknown ``strategy_name``, an unknown verb, or a
		malformed payload is a LOUD no-op: ``logger.warning`` + return, NEVER a raise into
		the queue.

		D-09 concurrency: verbs are applied on the single engine thread that drains the
		queue, so a verb never interleaves with a signal mid-application — in the
		single-writer model that IS the D-13 quiesce.

		The follow-on ``UniversePollEvent`` is queue-only (D-11 — one selection path, two
		triggers; the mutation happens-before the re-select). This NEVER calls
		``UniverseHandler`` or touches ``Universe.apply``.

		Parameters
		----------
		event: `StrategyCommandEvent`
			The control-plane command addressed to one strategy by name.
		"""
		# D-10: `add` targets a NEW name that is (by design) NOT yet in the roster, so it
		# is dispatched BEFORE the by-name lookup guard below — that guard would reject
		# every add as "unknown strategy". A pair `add` is likewise handled here (the
		# verb-scoped pair guard below only governs EXISTING pair instances; `add`
		# constructs a fresh one, which add_strategy's SHORT-01/D-07 gate admits).
		if event.verb == "add":
			self._add_strategy_verb(event)
			return
		by_name = {strategy.name: strategy for strategy in self.strategies}
		strategy = by_name.get(event.strategy_name)
		if strategy is None:
			# Unknown target — loud no-op (no mutation, no follow-on).
			self.logger.warning(
				'StrategyCommandEvent for unknown strategy %s (verb=%s, symbol=%s) — ignored',
				event.strategy_name, event.verb, event.symbol)
			return
		# D-16/D-17 VERB-SCOPED pair guard. The v1.7 guard here refused EVERY verb for a
		# PairStrategy. That is BROADER than D-16 permits — D-16 requires pairs to
		# add/remove/enable/disable/subscribe and rehydrate as FULL registry instances, so
		# a blanket refusal silently guts pair durability while LOOKING like a
		# conservative safety measure. A refusal that is too broad is as much a defect as
		# one that is too narrow. Refuse EXACTLY _PAIR_REFUSED_VERBS; accept the rest.
		#
		# D-17 — why `reconfigure` is refused for a pair in P10 (params AND the leg-swap,
		# deferred to the next milestone as ONE unit). This is not conservatism; the three
		# evidence sites compose into stranded money:
		#   - pair_base.py::_entry (:247) sets NO stop_loss/take_profit — unlike the
		#     single-leg _intent — so an OPEN SPREAD HAS NO RESTING EXCHANGE BRACKET and
		#     its ONLY exit is evaluate_pair(), which _dispatch_pair gates on
		#     is_pair_ready();
		#   - PairStrategy._run_init (:144) unconditionally re-creates _buf_A/_buf_B and
		#     resets _pair_bar_count (β re-fits from scratch), and reconfigure() ALWAYS
		#     calls _run_init();
		#   - is_pair_ready() (:185) needs beta_warmup + z_lookback bars (280 for the
		#     reference).
		# Net: reconfiguring a pair that holds an open spread strands an UNHEDGED,
		# BRACKET-LESS spread with NO REACHABLE EXIT for 280 bars — ~12 days on 1h, 280
		# days on 1d. Do NOT re-litigate this without re-reading those three sites; see
		# .planning/todos/pending/pair-strategy-live-reconfiguration.md.
		#
		# CR-01 — the ticker verbs stay refused: a pair is bound to an EXACT-2-ticker
		# contract (PairStrategy.validate + the _dispatch_pair len-2 guard), so mutating
		# its tickers would make EVERY subsequent BAR's _dispatch_pair raise — an
		# unbounded self-inflicted ErrorEvent storm with no recovery.
		if isinstance(strategy, PairStrategy) and event.verb in _PAIR_REFUSED_VERBS:
			self.logger.warning(
				'StrategyCommandEvent verb=%s refused for pair strategy %s — pairs '
				'accept the lifecycle verbs (D-16) but refuse reconfigure (D-17) and '
				'the ticker verbs (CR-01: the exact-2-ticker contract is immutable at '
				'the control-plane seam)',
				event.verb, event.strategy_name)
			return
		# D-11 `remove` — a heavy lifecycle verb (force-flat first, pending across event
		# cycles). It is NOT in _PAIR_REFUSED_VERBS, so a pair remove reaches here and
		# force-flats BOTH legs (D-16). Dispatched to its own method; it owns its persist
		# + poll and the pending-removal state, so it returns before the light-verb
		# `mutated` tail below (which is for the D-09 light verbs only).
		if event.verb == "remove":
			self._remove_strategy_verb(event, strategy)
			return
		# D-12/D-13/D-14/D-15 `reconfigure` — an authoring-param delta applied atomically
		# (trial-validate -> persist -> apply -> re-warm). It owns its own persist + poll +
		# the D-13 asymmetry, so it returns before the light-verb `mutated` tail below. A
		# PairStrategy never reaches here — `reconfigure` is in _PAIR_REFUSED_VERBS, so the
		# verb-scoped pair guard above already refused it (D-17).
		if event.verb == "reconfigure":
			self._reconfigure_strategy_verb(event, strategy)
			return
		# IN-02: track whether the verb ACTUALLY mutated anything. Both the persist and
		# the follow-on are gated on this — an idempotent no-op (enable an enabled
		# strategy, add an already-present ticker, unsubscribe an unsubscribed id)
		# mutates nothing, persists nothing and emits nothing.
		mutated = False
		# A deferred (op, portfolio_id) child-table write, applied AFTER the parent
		# upsert below — the child row carries an FK to the registry row (see there).
		# The id is stringified for the store: the column is String and `to_dict`
		# writes `str(pid)`, so this is the same normalization the rest of the system
		# round-trips through (rehydrate parses it straight back).
		child_write: "Optional[tuple[str, str]]" = None
		if event.verb == "enable":
			if not strategy.is_active:
				strategy.activate_strategy()
				# ⚠ WD-1 — the load-bearing half of `enable`. The D-07 guard sits FIRST
				# in calculate_signals, so this strategy's indicators FROZE while it was
				# disabled: their values were computed over a window that now has an
				# N-bar HOLE spanning the disabled period. Trading the next bar would let
				# SMA/MACD silently produce wrong values across that discontinuity —
				# exactly the defect class this milestone exists to eliminate, and
				# invisible because warmth is monotone (nothing downstream re-checks).
				# So force the strategy back to UNWARM: is_ready() now gates emission
				# until the recurrence has re-advanced over a CONTIGUOUS window.
				#
				# mark_unwarm is the WD-2 seam on Strategy (a named wrapper over the
				# existing handle reset, NOT a flag — warmth stays derived from
				# is_ready), and PairStrategy overrides it to clear the spread buffers
				# too (a handle-free pair is is_ready==True always, so a handles-only
				# unwarm would let it re-enter on a cold β). Plan 07's `add` re-warms
				# through this SAME seam — one warm path, not two (WD-1).
				strategy.mark_unwarm()
				self._request_rewarm(strategy)
				mutated = True
		elif event.verb == "disable":
			if strategy.is_active:
				# D-07: deactivate only. Do NOT unwarm here — a disabled strategy's
				# frozen state is discarded by `enable`, and unwarming on the way DOWN
				# would just as happily discard state a re-enable never needs.
				strategy.deactivate_strategy()
				mutated = True
		elif event.verb == "subscribe_portfolio":
			portfolio_id = self._portfolio_id_from(event)
			if portfolio_id is None:
				self.logger.warning(
					'subscribe_portfolio for strategy %s carries no valid '
					'config["portfolio_id"] — ignored',
					event.strategy_name)
				return
			if portfolio_id not in strategy.subscribed_portfolios:
				# base.py's sanctioned idempotent mutator (WR-01) — a duplicate would
				# fan ONE decision out to the same portfolio twice.
				strategy.subscribe_portfolio(portfolio_id)
				child_write = ("add", str(portfolio_id))
				mutated = True
		elif event.verb == "unsubscribe_portfolio":
			portfolio_id = self._portfolio_id_from(event)
			if portfolio_id is None:
				self.logger.warning(
					'unsubscribe_portfolio for strategy %s carries no valid '
					'config["portfolio_id"] — ignored',
					event.strategy_name)
				return
			if portfolio_id in strategy.subscribed_portfolios:
				strategy.unsubscribe_portfolio(portfolio_id)
				child_write = ("remove", str(portfolio_id))
				# D-09: removing the LAST portfolio leaves an empty list and zero child
				# rows — a legal state (the strategy computes but fans out to nobody).
				# Deliberately NOT guarded against.
				mutated = True
		elif event.verb in ("add_ticker", "remove_ticker"):
			# D-08: symbol is now `str | None` and six of the nine verbs carry none, so
			# the read lives HERE, inside the only branches that have one.
			symbol = event.symbol
			if symbol is None:
				self.logger.warning(
					'%s for strategy %s carries no symbol — ignored',
					event.verb, event.strategy_name)
				return
			if event.verb == "add_ticker":
				if symbol not in strategy.tickers:
					strategy.tickers.append(symbol)  # idempotent append
					mutated = True
			else:
				if symbol in strategy.tickers:
					if len(strategy.tickers) == 1:
						# Refuse: removing the last ticker would violate the
						# non-empty list[str] invariant (base.py). Documented no-op —
						# no mutation, no persist, no re-select.
						self.logger.warning(
							'remove_ticker %s refused for strategy %s — would empty its '
							'ticker set (non-empty invariant preserved)',
							symbol, event.strategy_name)
						return
					strategy.tickers.remove(symbol)  # idempotent removal
					mutated = True
		else:
			# Unknown verb (including `add`/`remove`/`reconfigure`, which land in Plans
			# 07/08) — loud no-op.
			self.logger.warning(
				'StrategyCommandEvent unknown verb %s for strategy %s — ignored',
				event.verb, event.strategy_name)
			return
		if not mutated:
			return
		# D-09: EVERY mutating verb persists, parent row first.
		#
		# The subscribe/unsubscribe verbs are deliberately routed through the parent
		# upsert too, even though they only change the CHILD table. It looks redundant —
		# the config blob and `enabled` are unchanged — but strategy_portfolio_subscriptions
		# carries an FK to strategy_registry, so writing a child row for a strategy the
		# registry has never seen (one hand-added rather than rehydrated) raises an
		# IntegrityError straight into the queue, violating this method's never-raise
		# contract. Upserting the parent first is not a workaround for the FK; it is what
		# the FK is telling us: a durable subscription edge whose instance is absent from
		# the registry is an orphan rehydrate would silently drop at restart. Persist the
		# instance, then the edge.
		self._persist_strategy(strategy, event)
		if child_write is not None and self.registry_store is not None:
			operation, stored_portfolio_id = child_write
			if operation == "add":
				self.registry_store.add_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
			else:
				self.registry_store.remove_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
		# D-11 / IN-02 follow-on: mutate happens-before re-select. Queue-only cross-domain
		# write — never call UniverseHandler.
		if event.verb in _POLL_FOLLOW_ON_VERBS:
			self.global_queue.put(UniversePollEvent(time=event.time))

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
			# D-11: a pending-removal strategy is EXCLUDED from the derived membership so
			# the poll's REMOVE branch force-closes its now-unmembered symbols — the trigger
			# that drives the P7 force-close machinery. The instance STAYS in
			# self.strategies (its row is kept until flat for crash-safety); it simply stops
			# CONTRIBUTING to membership. A symbol shared with a non-pending strategy stays a
			# member via that other strategy (correct: it is still needed) — the force-close
			# is symbol-scoped, so a shared symbol's position is not force-closed by removing
			# only one of its strategies (the accepted P10-scope limitation).
			if strategy.name in self._pending_removals:
				continue
			# IN-01: the declared config contract is `tickers: list[str]`, so
			# `tickers[0]` is always a `str` — the legacy pairs-trading branch
			# (`isinstance(tickers[0], tuple)`) was dead on every supported path
			# and has been removed. A typed pairs API will replace it if/when
			# pairs trading is reintroduced, rather than runtime isinstance
			# sniffing on the first element.
			traded_tickers += strategy.tickers

		return list(set(traded_tickers))

	
	def _direction_admissible(self, direction: TradingDirection) -> bool:
		"""SHORT-01/D-07 two-flag registration predicate — the SHARED gate (audit 10-08 F1).

		A non-``LONG_ONLY`` direction is admissible ONLY when BOTH ``allow_short_selling``
		AND ``enable_margin`` are on. Factored out of ``add_strategy`` so the IDENTICAL
		predicate gates ``add`` AND ``reconfigure(direction=...)`` — the two cannot drift.

		Deliberately NOT pushed into ``Strategy.validate()``: the two flags are HANDLER
		policy state that a pure-alpha ``Strategy`` (D-12) must never see, and ``validate()``
		has no access to them. That is exactly why the plan's original "``validate()``
		re-runs the SHORT-01 gate" premise was false — ``validate()`` is a window-shape hook
		and never checks ``direction`` — so the trial construction alone CANNOT admit-gate a
		short-enabling reconfigure. This predicate, called on the reconfigure apply path
		against the trial's resolved direction, is what actually closes T-10-55.
		"""
		return direction is TradingDirection.LONG_ONLY or (
			self._allow_short_selling and self._enable_margin)

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
		# SHORT-01/D-07 two-flag registration gate, via the SHARED predicate so `add` and
		# `reconfigure(direction=...)` cannot drift (audit 10-08 F1): a non-LONG_ONLY
		# direction is admissible ONLY when BOTH allow_short_selling AND enable_margin are on.
		# enable_margin is coupled in because it enables the lock-and-settle model that can
		# actually represent a short. Both default off → the golden LONG_ONLY path is
		# unaffected (oracle byte-exact).
		if not self._direction_admissible(strategy.direction):
			raise ValueError(
				"Non-LONG_ONLY strategies (LONG_SHORT / SHORT_ONLY) require "
				"BOTH allow_short_selling AND enable_margin to be enabled "
				"(SHORT-01/D-07) — enable_margin turns on the lock-and-settle "
				"model that can represent a short. Both flags default off."
			)

		# D-02 duplicate-name loud reject. `strategy_name` is the DURABLE
		# per-instance identity: the registry keys on it, STRATEGY_COMMAND
		# addresses by it, and rehydrate reconstructs by it. (The ephemeral
		# `strategy_id` UUIDv7 at base.py:192 is minted per construction and
		# is NOT restart-stable, so keying durability on it would corrupt
		# rehydrate.) A silent second registration under the same name would
		# shadow the first instance and overwrite its persisted state, so a
		# collision rejects loudly instead — including the rehydrate cases
		# (rehydrating twice, or rehydrating a name already hand-added).
		if any(existing.name == strategy.name for existing in self.strategies):
			raise ValueError(
				f"A strategy named {strategy.name!r} is already registered "
				"(D-02) — strategy_name is the durable per-instance identity, "
				"so a duplicate would silently shadow the existing instance "
				"and overwrite its persisted state. Rename one of them."
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
