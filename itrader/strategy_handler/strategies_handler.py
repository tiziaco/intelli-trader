from datetime import timedelta
from typing import Any, Optional, TYPE_CHECKING, cast

from itrader.core.enums import OrderType
from itrader.core.exceptions import ConfigurationError
from itrader.core.ids import PortfolioId
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
		environment: `str`
			The storage-selection key — ``'backtest'`` / ``'test'`` / ``'live'``.
			CTX-02/D-02 handler-owns-storage-init: the handler derives BOTH
			``signal_store`` and ``registry_store`` from this (together with
			``sql_engine``) through their factories, rather than having a caller
			assign them after construction. An explicitly passed store still WINS
			over the derived one.
		sql_engine: `SqlEngine | None`
			The already-constructed shared SQL spine handed to those same two
			factories. ``None`` on the backtest path, where both factories return
			their in-memory concretes (``registry_store`` becomes ``None`` and every
			persist arm short-circuits). Typed ``Any`` so the SQL stack stays off
			this module's annotations (GATE-01 inertness).
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
		strategy_catalog: `StrategyCatalog | None`
			**D-10**: the access-control ALLOWLIST through which the ``add`` and
			``reconfigure`` verbs resolve an untrusted, externally-supplied
			``strategy_type`` string. ``None`` LOUD-rejects both verbs.
			Security-relevant: this is the boundary that stops an external
			STRATEGY_COMMAND payload from naming an arbitrary class. Owned by the
			lifecycle manager and reached through the read-through property below,
			so a post-construction swap cannot leave the enforcement path reading
			a stale catalog (T-10.1-03).
		portfolio_read_model: `PortfolioReadModel | None`
			**D-11**: the flat-detect read-model consulted on FILL to decide
			whether a pending removal has completed. A READ through an injected
			read-model, NOT a cross-domain handler call, so the queue-only contract
			holds. Passed by ``compose_engine`` on BOTH paths, so it is non-``None``
			in backtest too — do NOT infer the run mode from it.
		"""
		self.global_queue: "EventBus" = global_queue
		self.feed: BarFeed = feed
		# DECOMP-01: bound BEFORE the collaborator block — ManagedStrategies takes
		# the logger by injection (its moved add_strategy body logs through it), so
		# the bind can no longer sit at the end of __init__ as it historically did.
		self.logger = get_itrader_logger().bind(component="StrategiesHandler")
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
		#
		# DECOMP-01: resolved into a LOCAL, not an attribute. The three live deps are
		# now OWNED by the lifecycle manager and reached through the read-through
		# properties below — see the block there for why a handler-side copy would be
		# a silent authorization-bypass hazard (T-10.1-03).
		resolved_registry_store: "Optional[Any]" = (
			registry_store if registry_store is not None
			else StrategyRegistryStorageFactory.create(environment, sql_engine=sql_engine)
		)
		# DECOMP-01: the roster collaborator OWNS `strategies`, `min_timeframe`,
		# `_pending_removals`, and the two SHORT-01/D-07 gate flags — the handler
		# holds NONE of that state itself and reaches all of it through the
		# delegating accessors below. Constructed unconditionally (no Optional, no
		# late init): the comment blocks that documented each field moved WITH the
		# state into managed_strategies.py rather than being duplicated here.
		self._managed: ManagedStrategies = ManagedStrategies(
			allow_short_selling=allow_short_selling,
			enable_margin=enable_margin,
			logger=self.logger,
		)
		# DECOMP-01: the STRATEGY_COMMAND control plane. Constructed UNCONDITIONALLY
		# from a module-top import — no Optional, no assert guard, no late-init
		# helper, no function-local import. That is possible because 10.1-01 made all
		# three live deps REAL at __init__; the manager therefore exists before any
		# set_universe call or verb dispatch can reach it. It shares the SINGLE
		# `ManagedStrategies` roster owner rather than holding roster state of its own.
		self._lifecycle: StrategyLifecycleManager = StrategyLifecycleManager(
			managed=self._managed,
			global_queue=global_queue,
			feed=feed,
			registry_store=resolved_registry_store,
			strategy_catalog=strategy_catalog,
			portfolio_read_model=portfolio_read_model,
			logger=self.logger,
		)
		# WR-02 (D-01) live-only readiness seam: the injected dynamic universe,
		# wired ONLY on the live path via set_universe. Defaults None so the
		# backtest wires no universe → the on_bar readiness gate is a
		# single `is None` short-circuit (oracle byte-exact, RESEARCH OQ8).
		self._universe: "Universe | None" = None

		self.logger.info('Strategies Handler initialized')

	# --- DECOMP-01 roster accessors ---------------------------------------
	#
	# The handler's public surface is preserved by delegation to the single
	# `ManagedStrategies` owner. `strategies` and `_pending_removals` hand back
	# the collaborator's OWN objects — never a copy, never a snapshot. The
	# roster list is mutated in place at 21 test sites (`.append` / `.extend`),
	# so a defensive copy here would silently turn every one of them into a
	# no-op. Read-only: all four `min_timeframe` write sites and both container
	# assignments moved into the collaborator, so no setter is needed.

	@property
	def strategies(self) -> list[Strategy]:
		"""The managed roster — the IDENTICAL list object the collaborator holds."""
		return self._managed.strategies

	@property
	def min_timeframe(self) -> timedelta | None:
		"""The IN-06 derived minimum timeframe across the roster (None when empty)."""
		return self._managed.min_timeframe

	@property
	def _pending_removals(self) -> set[str]:
		"""The D-11 pending-removal name set — the collaborator's OWN set object."""
		return self._managed._pending_removals

	# The two SHORT-01/D-07 flags are read/WRITE by delegation. They are a
	# CAPABILITY gate, so there must be exactly ONE copy: `direction_admissible`
	# reads the collaborator's, and 11 short/pair test files flip these privates
	# on the handler AFTER construction and then register a non-LONG_ONLY
	# strategy. A handler-side shadow attribute would let the gate the tests
	# think they opened diverge from the gate `add_strategy` actually consults —
	# precisely the drift the shared predicate exists to prevent (T-10-55).

	@property
	def _allow_short_selling(self) -> bool:
		"""SHORT-01/D-07 gate flag — single source of truth is the collaborator."""
		return self._managed._allow_short_selling

	@_allow_short_selling.setter
	def _allow_short_selling(self, value: bool) -> None:
		self._managed._allow_short_selling = value

	@property
	def _enable_margin(self) -> bool:
		"""SHORT-01/D-07 gate flag — single source of truth is the collaborator."""
		return self._managed._enable_margin

	@_enable_margin.setter
	def _enable_margin(self, value: bool) -> None:
		self._managed._enable_margin = value

	# --- DECOMP-01 live-dep accessors (single owner) -----------------------
	#
	# The three live deps are OWNED by the lifecycle manager; these are
	# read-through properties, not copies. 28 call sites across 6 test files
	# construct the handler and THEN assign one of these — with a handler-side
	# plain attribute the manager would keep the value it captured at
	# construction and every one of those tests would silently exercise a
	# manager holding `None`. Worse than a failing test: `strategy_catalog` is
	# the D-10 access-control ALLOWLIST, so a caller could believe it swapped
	# the catalog while the enforcement path still read the stale one — a silent
	# authorization bypass (T-10.1-03). Reading and writing THROUGH the single
	# owner makes that divergence unrepresentable, and keeps all 28 assignments
	# working as behaviour-preservation evidence with zero test edits.
	#
	# All three stay typed `Any` so the SQL/registry stack stays off this
	# module's annotations (GATE-01 inertness). `None` remains the legal
	# backtest/in-memory value for `registry_store` (every persist arm
	# short-circuits) and for `strategy_catalog` (`add`/`reconfigure`
	# LOUD-reject). `portfolio_read_model` is passed by compose_engine on BOTH
	# paths, so it is non-None in backtest too — do NOT infer the run mode from
	# any of them.

	@property
	def registry_store(self) -> "Optional[Any]":
		"""D-09 durable instance registry — owned by the lifecycle manager."""
		return self._lifecycle.registry_store

	@registry_store.setter
	def registry_store(self, value: "Optional[Any]") -> None:
		self._lifecycle.registry_store = value

	@property
	def strategy_catalog(self) -> "Optional[Any]":
		"""D-10 strategy-type ALLOWLIST — owned by the lifecycle manager."""
		return self._lifecycle.strategy_catalog

	@strategy_catalog.setter
	def strategy_catalog(self, value: "Optional[Any]") -> None:
		self._lifecycle.strategy_catalog = value

	@property
	def portfolio_read_model(self) -> "Optional[Any]":
		"""D-11 flat-detect read-model — owned by the lifecycle manager."""
		return self._lifecycle.portfolio_read_model

	@portfolio_read_model.setter
	def portfolio_read_model(self, value: "Optional[Any]") -> None:
		self._lifecycle.portfolio_read_model = value

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the dynamic universe for the WR-02 readiness gate (D-01).

		Called on BOTH paths — ``universe_wiring.wire_universe`` invokes it for
		backtest too (reached from ``backtest_runner._initialise_backtest_session``),
		so ``self._universe`` is NOT ``None`` in backtest. The oracle is nonetheless
		unaffected, and by construction rather than by absence: ``Universe.__init__``
		marks every member ``Readiness.READY`` and backtest membership derives FROM
		the strategy tickers, so ``is_ready(ticker)`` always holds at the per-tick
		gate in ``on_bar`` and the gate never skips — oracle-inert, proven
		by the byte-exact double-run.

		DECOMP-01: also forwarded to the lifecycle manager, whose ``_request_rewarm``
		is the sole ``mark_failed`` caller. The forward is UNCONDITIONAL — no
		``is not None`` guard and no ``assert``: the manager is constructed
		unconditionally in ``__init__``, so it always exists by the time this runs
		(an ``assert`` here would abort every backtest run, since
		``universe_wiring`` reaches this method on the backtest path too). The
		handler keeps its OWN reference because ``on_bar`` reads it on
		the per-tick readiness gate — two references to ONE object is the intended
		shape, not a duplicated state.
		"""
		self._universe = universe
		self._lifecycle.set_universe(universe)

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

	def on_bar(self, event: BarEvent) -> None:
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

		Routed from ``on_bar`` for any ``PairStrategy`` (a typed
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

	def on_fill(self, event: "Any") -> None:
		"""D-11 completion hook: drop a pending-removal strategy once its positions are flat.

		The three lifecycle behaviours stay DISTINCT (never conflated): ``disable`` stops
		NEW entries and KEEPS open positions + brackets; ``remove`` force-flats, waits flat,
		then drops; ``reconfigure`` applies live and KEEPS positions.

		Wired on the LIVE FILL route only (``route_registrar``), AFTER
		``PortfolioHandler.on_fill`` so the read model already reflects the settled (flat)
		position. It is NOT on the backtest ``_routes`` FILL list at all, so it never runs on
		the byte-exact oracle path (and the pending-removal set is empty there regardless).

		DECOMP-01: a 1-line delegation. The body moved VERBATIM to
		``StrategyLifecycleManager.on_fill``; the docstring stays here because this is the
		route-facing public surface ``route_registrar.py`` binds.
		"""
		self._lifecycle.on_fill(event)

	def on_strategy_command(self, event: StrategyCommandEvent) -> None:
		"""Apply one control-plane verb to one strategy, live AND durably (D-09).

		The STRAT-02 dispatch surface (live-only). Locates the strategy whose ``.name``
		matches ``event.strategy_name`` — the durable per-instance identity (D-02) — and
		applies the verb IDEMPOTENTLY: the LIGHT verbs (``enable`` / ``disable`` /
		``subscribe_portfolio`` / ``unsubscribe_portfolio`` / ``add_ticker`` /
		``remove_ticker``) plus the heavy ``add`` (D-10), ``remove`` (D-11) and
		``reconfigure`` (D-12/D-13/D-14/D-15).

		An unknown ``strategy_name``, an unknown verb, or a malformed payload is a LOUD
		no-op: ``logger.warning`` + return, NEVER a raise into the queue.

		DECOMP-01: a 1-line delegation. The whole verb dispatch — the D-16/D-17 pair guard,
		every validation gate in its original order, the D-09 persist tail and the
		queue-only ``UniversePollEvent`` follow-on — moved VERBATIM to
		``StrategyLifecycleManager.on_strategy_command``. The docstring stays here because
		this is the route-facing public surface ``route_registrar.py`` binds.

		Parameters
		----------
		event: `StrategyCommandEvent`
			The control-plane command addressed to one strategy by name.
		"""
		self._lifecycle.on_strategy_command(event)


	def get_strategies_universe(self) -> list[str]:
		"""
		Return a list with all the coins traded from the differents strategies.

		Returns
		-------
		traded_tickers: `list`
			List of strings with the traded symbols
		"""
		return self._managed.get_universe()

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
		self._managed.add_strategy(strategy)

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
				# Wrap any reconfigure failure (UnknownParamError /
				# MissingParamError / a validate() ValueError) into the single
				# web-catchable ConfigurationError (D-08).
				raise ConfigurationError(
					config_key=name,
					reason=str(exc),
				) from exc
