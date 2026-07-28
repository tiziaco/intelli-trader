"""Strategy control-plane collaborator.

`StrategyLifecycleManager` owns the entire STRATEGY_COMMAND control plane: the two
route-facing entry points `on_strategy_command` / `on_fill`, the verb/helper privates they
reach, and the module-level verb constants only those bodies read. The handler's methods
of the same name are 1-line delegations. It holds NO handler back-reference.

Every import is at MODULE TOP. This module is on the backtest import graph by design, and
importing it leaks ZERO sqlalchemy / psycopg2 / alembic and leaves the config `sql`
cached_property unresolved — which `test_okx_inertness.py` asserts positively.

⚠ DEVIATION from the order-domain analog, whose `LifecycleManager` declares "NO queue
access". This manager DOES hold `global_queue`: the bodies emit `UniversePollEvent` (the
warmup and force-close wiring) and a CRITICAL `ErrorEvent` (the apply-fail egress). That
egress IS the collaborator's contract, not a layering leak — it is queue-only, so
`UniverseHandler` / `Universe` are never called and `PortfolioHandler` is never imported.

⚠ NEGATIVE INVARIANT — ZERO roster state. This class owns NO `strategies` list and NO
`_pending_removals` set; every access routes through `self._managed`. Giving this manager
its OWN pending set is the silent-corruption trap the extraction exists to avoid:
`ManagedStrategies.get_universe` reads ITS set to exclude a pending strategy's tickers, so
a second set here would leave membership never re-deriving, the force-close poll never
firing, and `remove` hanging forever with NO error raised.

⚠ SECURITY. `strategy_type` arrives as an untrusted string on an external payload. The
`add` and `reconfigure` verbs resolve it through the injected `strategy_catalog` by CLOSED
DICT LOOKUP and nothing else, and LOUD-reject when the catalog is None. There is
deliberately no `importlib`, no `__import__`, no `getattr`-on-module and no default catalog
anywhere on those paths: resolving a type by name would convert the operator API into
remote code execution.

TABS file.
"""

import uuid
from typing import Any, Optional, TYPE_CHECKING

from itrader.core.enums import ErrorSeverity
from itrader.core.exceptions import StrategyAdmissionError
from itrader.core.ids import PortfolioId
from itrader.core.policy_codec import default_policy_registry
from itrader.core.portfolio_read_model import PortfolioReadModel
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import (
	ErrorEvent,
	StrategyCommandEvent,
	UniversePollEvent,
)
from itrader.logger import ITraderStructLogger
from itrader.price_handler.feed.base import BarFeed
from itrader.price_handler.feed.cache_registration import (
	UnwarmableTimeframeError,
	required_base_depth,
)
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.managed_strategies import ManagedStrategies
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.registry.config_codec import (
	decode_strategy_config,
	encode_strategy_config,
)
from itrader.strategy_handler.registry.rehydrate import build_strategy

if TYPE_CHECKING:
	# A module-level import under a guard the interpreter never executes, NOT a
	# function-local import. The annotation stays a string.
	from itrader.universe.universe import Universe


# Verb-scoped pair guard: a PairStrategy refuses EXACTLY these verbs and accepts every
# other one — see the rationale block in on_strategy_command.
_PAIR_REFUSED_VERBS = frozenset({"reconfigure", "add_ticker", "remove_ticker"})

# The verbs needing a UniversePollEvent follow-on. The ticker verbs change MEMBERSHIP;
# `enable` needs it because enabling unwarms the strategy and the re-warm rides the
# FAILED-retry, which only runs on a poll. disable/subscribe/unsubscribe change neither
# membership nor warmth. `reconfigure` and `remove` emit their OWN poll inline.
_POLL_FOLLOW_ON_VERBS = frozenset({"add_ticker", "remove_ticker", "enable"})

# The `reconfigure` DENY-lists: two closed key sets refused loudly BEFORE any throwaway is
# built. Everything else is left to _apply_params' unknown-param rejection, so no second
# hand-maintained allowlist can drift from the class annotations.
#
# IDENTITY + DERIVED, never a param: `strategy_type`, because changing the class IS a
# different strategy; `name`, the store PK, since a rename would UPSERT a NEW row and ORPHAN
# the old one (the codec omits `name` from the blob precisely so a PK-vs-blob disagreement is
# unrepresentable); and `warmup` / `max_window`, which `_run_init` UNCONDITIONALLY overwrites
# from the declared indicators, so a passed value is silently clobbered — refuse loudly
# rather than accept-then-clobber.
#
# Hardcoded rather than imported from config_codec so the deny-list stays a self-contained
# closed set at this seam; it MUST track config_codec._DERIVED_FIELDS.
_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type", "name", "warmup", "max_window"})

# `tickers` is owned by add_ticker/remove_ticker — one path per concern.
_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})


class StrategyLifecycleManager:
	"""The STRATEGY_COMMAND control plane.

	See the module docstring for the queue-access deviation, the ZERO-roster-state
	invariant, and the closed-dict-lookup security contract.

	The three live deps all accept `None` as their legal backtest/in-memory state, and every
	persist arm short-circuits on it. Two keep `Optional[Any]` VALUES so the SQL stack stays
	off this module's annotations; `portfolio_read_model` is the EXCEPTION, because
	`core/portfolio_read_model.py` pulls no SQL — only stdlib plus modules already on this
	import graph — so naming the real protocol costs nothing in inertness and buys a genuine
	`mypy --strict` check of the `get_position` call in `_strategy_is_flat`, which an erased
	`Any` would suppress. The manager is the SINGLE OWNER of all three; the handler exposes
	read-through properties rather than its own copies, so a post-construction assignment
	cannot desync the two.
	"""

	def __init__(
		self,
		managed: ManagedStrategies,
		global_queue: "EventBus",
		feed: BarFeed,
		registry_store: "Optional[Any]",
		strategy_catalog: "Optional[Any]",
		portfolio_read_model: "Optional[PortfolioReadModel]",
		logger: ITraderStructLogger,
	) -> None:
		"""
		Parameters
		----------
		managed: `ManagedStrategies`
			The SINGLE roster owner. This manager holds no roster state of its
			own — see the module docstring's negative invariant.
		global_queue: `EventBus`
			The events queue. Queue-only egress: UniversePollEvent and the
			CRITICAL ErrorEvent.
		feed: `BarFeed`
			The look-ahead-safe market-data read model. Read for its
			`base_timeframe` / `cache_capacity` on the warmability gates.
		registry_store: `StrategyRegistryStore | None`
			The durable instance registry. ``None`` is the BACKTEST / in-memory
			path — every persist arm is then a clean no-op.
		strategy_catalog: `StrategyCatalog | None`
			The access-control ALLOWLIST the `add` / `reconfigure` verbs resolve
			an untrusted external ``strategy_type`` through. ``None`` LOUD-rejects.
		portfolio_read_model: `PortfolioReadModel | None`
			The flat-detect read-model consulted on FILL. A READ through an
			injected read-model, NOT a cross-domain handler call.
		logger: `ITraderStructLogger`
			The handler's logger, re-bound to this component so the control plane's
			lines are attributable to it. Concretely typed so ``mypy --strict`` checks
			this module's call sites rather than erasing them behind ``Any``.
		"""
		self._managed = managed
		self.global_queue: "EventBus" = global_queue
		self.feed: BarFeed = feed
		self.registry_store: "Optional[Any]" = registry_store
		self.strategy_catalog: "Optional[Any]" = strategy_catalog
		self.portfolio_read_model: "Optional[PortfolioReadModel]" = portfolio_read_model
		self.logger = logger.bind(component="StrategyLifecycleManager")
		# Live-only readiness seam, wired ONLY via set_universe. `_request_rewarm` is
		# the sole reader.
		self._universe: "Universe | None" = None

	@property
	def universe(self) -> "Universe | None":
		"""The universe handle — THIS object, never a copy.

		The same-object read seam the handler's ``_universe`` property forwards to, so no
		caller reaches into this object's private attribute. Read-only by design:
		``set_universe`` stays the SOLE write path, so widening the read surface cannot
		widen the write surface.
		"""
		return self._universe

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the dynamic universe so ``_request_rewarm`` can mark symbols FAILED.

		Forwarded unconditionally from the handler, which keeps its own reference for the
		per-tick readiness gate. Two references to ONE object is the intended shape.
		"""
		self._universe = universe

	def _persist_strategy(
		self, strategy: Strategy, event: StrategyCommandEvent
	) -> None:
		"""Write the strategy's post-mutation state to the durable registry.

		A clean no-op when no registry store is injected. Writes the FULL post-mutation
		authoring set, never the incoming delta: a partial write would let the row drift from
		the live instance, and the row is what rehydrate reconstructs at restart — a
		divergence there resurrects a strategy that never existed.

		``at`` is BUSINESS time, never wall clock, so the audit trail stays reproducible.
		"""
		if self.registry_store is None:
			return
		self.registry_store.upsert(
			strategy_name=strategy.name,
			strategy_type=type(strategy).__name__,
			config=encode_strategy_config(strategy),
			enabled=strategy.is_active,
			at=event.time,
		)

	def _request_rewarm(self, strategy: Strategy) -> None:
		"""Drive an unwarmed strategy's symbols back through the warmup pipeline.

		``mark_unwarm`` alone is already CORRECT — the readiness gates block emission either
		way. This method only makes it FAST: without it a re-enabled 1d strategy would wait
		~``warmup`` real bars before trading again, which is a control-plane verb behaving
		like a decommission.

		There is no strategy-level warm API to call: the pipeline is per-SYMBOL and owned by
		``UniverseHandler`` behind the queue boundary, and its existing trigger is the
		FAILED-retry. So marking this strategy's symbols FAILED and letting the follow-on poll
		land IS the re-warm request — one warm path, no new event type, no cross-domain call.
		``_universe`` is None on the backtest path, where no warmup pipeline exists at all.

		Two accepted consequences, both bounded and self-healing: a symbol shared with an
		already-warm sibling goes dark for ONE poll interval, and the replayed bars are
		re-delivered to that sibling, where the monotonic guard in ``Strategy.update`` rejects
		them before any state mutation — that guard exists for exactly this case.
		"""
		if self._universe is None:
			return
		for ticker in strategy.tickers:
			# mark_failed, NOT mark_pending: only FAILED members are collected by the retry
			# in on_poll, so PENDING would leave the symbol dark FOREVER.
			self._universe.mark_failed(ticker)

	def _portfolio_id_from(
		self, event: StrategyCommandEvent
	) -> "Optional[PortfolioId]":
		"""Parse ``config["portfolio_id"]`` into the handle the fan-out expects, or None.

		The payload is untrusted, so it is validated and PARSED here and a malformed one never
		reaches live strategy state or SQL. A miss returns None and the caller makes it a loud
		no-op — this path must never raise into the queue.

		⚠ The parse is a CORRECTNESS requirement, not a typing nit. ``on_bar`` fans each intent
		over ``subscribed_portfolios``, putting each id STRAIGHT onto
		``SignalEvent.portfolio_id``, so a bare ``str`` reaches the portfolio lookup as an id
		matching NOTHING: the subscription looks perfectly healthy and fans signals into the
		void. Value-equality assertions pass while the type is wrong.

		Mirrors ``rehydrate._resolve_portfolio_id`` but returns None instead of raising:
		rehydrate quarantines a bad instance at boot, whereas a bad runtime command is a loud
		no-op.
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
			return None

	def _portfolio_id_supplied(self, event: StrategyCommandEvent) -> bool:
		"""The presence probe that makes ABSENT and MALFORMED distinguishable.

		``_portfolio_id_from`` collapses FOUR outcomes into one ``None``: config-not-a-dict, key
		absent, wrong value type, unparseable UUID. That is RIGHT for the two light verbs, which
		warn on every ``None`` whatever the cause, and WRONG for ``add``, where absence is a
		LEGAL state (register now, wire the portfolio later) but malformation is operator error.

		The key name and the dict guard live HERE, adjacent to the parser, rather than at the
		call site: a call site re-reading ``event.config`` would duplicate this parsing and let
		probe and parser drift apart.

		An explicit ``None`` VALUE counts as NOT supplied, because a Pydantic model declaring
		``portfolio_id: str | None = None`` serializes the unsubscribed case as a null on EVERY
		add — so a bare key-PRESENCE probe would reject the most likely shape of the legal
		no-subscription payload. Every OTHER value is supplied-and-malformed.
		"""
		config = event.config
		if not isinstance(config, dict):
			return False
		return config.get("portfolio_id") is not None

	def _add_strategy_verb(self, event: StrategyCommandEvent) -> None:
		"""`add`: catalog-gate -> construct DARK -> persist -> warm via the poll.

		The highest-value trust boundary here: an operator/FastAPI-supplied ``strategy_type`` plus
		config becomes a live Python object. Every rejection below is a LOUD no-op (log + return)
		that registers and persists NOTHING — a half-built strategy never enters the roster. That
		contract holds for ANY construction failure, not merely the enumerated validation kinds:
		``init()`` is arbitrary user-authored strategy code, so the zone-1 guard below is two-tier.

		One reconstruction path: ``add`` builds through the IDENTICAL ``build_strategy`` path
		rehydrate uses, so the two cannot drift, and construction runs the real
		``_apply_params`` -> ``validate()`` -> ``_run_init()``.

		Warm via the poll: a freshly constructed instance is DARK, its handles reset at
		construction. The emitted ``UniversePollEvent`` IS the whole warmup wiring — membership
		is derived FROM the registered strategies, so the poll re-selects and the EXISTING
		pipeline warms the new symbol, retrying on failure at the next poll. This works on a
		COLD symbol, the COMMON case; add-only-if-already-warm was rejected because it would
		refuse any genuinely new symbol. NO second warmup path is built — a parallel path would
		re-open the paper-replay parity gate. Queue-only: this NEVER calls ``UniverseHandler``.
		"""
		# Catalog gate — see the module docstring's security note. Without an injected
		# allowlist nothing may be instantiated from an external payload.
		if self.strategy_catalog is None:
			self.logger.warning(
				'add for strategy %s refused — no strategy_catalog injected; an external '
				'payload may only be instantiated through the injected allowlist (D-10)',
				event.strategy_name)
			return
		config = event.config
		if not isinstance(config, dict) or not isinstance(config.get("strategy_type"), str):
			self.logger.warning(
				'add for strategy %s carries no string strategy_type in its config '
				'payload — ignored', event.strategy_name)
			return
		strategy_type = config["strategy_type"]
		# Duplicate-name reject BEFORE any construction — a collision would silently shadow
		# another instance and overwrite its persisted state. Pre-checked by name rather than
		# catching add_strategy's raise, so nothing is constructed.
		if any(existing.name == event.strategy_name for existing in self._managed.strategies):
			self.logger.warning(
				'add for strategy %s refused — a strategy with that name is already '
				'registered (D-02); the existing instance is left untouched',
				event.strategy_name)
			return

		# A SUPPLIED but unparseable portfolio_id rejects the WHOLE add. Letting it fall into
		# the ABSENT branch would leave a registered, persisted, warming strategy with zero
		# subscriptions — and on_bar fans each intent over subscribed_portfolios, so an empty
		# list means literally zero SignalEvents forever. A healthy-looking engine that trades
		# nothing is worse than a loud refusal. ABSENT stays a legal no-op: add unsubscribed
		# now, wire it later with subscribe_portfolio.
		#
		# PLACEMENT is load-bearing: a pure payload check with no dependency on the constructed
		# object belongs AHEAD of every state mutation, since rejecting further down would have
		# to UNDO a completed roster insert.
		portfolio_id = self._portfolio_id_from(event)
		if portfolio_id is None and self._portfolio_id_supplied(event):
			# Names the KIND/condition only — never echoes the payload value.
			self.logger.warning(
				'add for strategy %s refused — its config["portfolio_id"] is present but '
				'unparseable; nothing was registered or persisted. A registered strategy '
				'with no subscription computes signals and fans them to nobody. Re-issue '
				'with a valid portfolio UUID, or omit the key to add it unsubscribed',
				event.strategy_name)
			return

		# The config_json blob is the payload MINUS portfolio_id: a subscription is a
		# child-table concern, not a declared param, so leaving it in would make _apply_params
		# raise UnknownParamError. strategy_type stays IN the blob (an envelope key decode
		# reads) AND is the top-level column; the two agree because one value folds into both.
		blob = {key: value for key, value in config.items() if key != "portfolio_id"}
		rec = {
			"strategy_name": event.strategy_name,
			"strategy_type": strategy_type,
			"config_json": blob,
		}
		try:
			strategy = build_strategy(rec, catalog=self.strategy_catalog)
		except StrategyAdmissionError as exc:
			# Tier 1 — EXPECTED validation kinds, i.e. the operator sent junk. A loud no-op
			# naming the error KIND, never the payload values. StrategyAdmissionError is the
			# shared ancestor of every strategy-payload refusal, so one name replaces a
			# hand-listed tuple that would drift out of sync with its siblings. It needs no
			# `ValueError` companion: it is declared `(ITraderError, ValueError)`, and the
			# bare-ValueError residue is typed by the wrap in `Strategy.__init__`, which
			# converts at the RAISE boundary and so covers a third-party validate() override.
			self.logger.warning(
				'add for strategy %s rejected (%s) — nothing registered or persisted',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — THE ZONE-1 GUARD, the canonical statement of the rule; the reconfigure
			# verb's guards refer back here.
			#
			# 1. NO FINITE TUPLE SUFFICES. Construction reaches `init()`, which is ARBITRARY
			#    user-authored strategy code, so the escaping-exception set is unbounded BY
			#    CONSTRUCTION and enumerating more types fixes the instance, never the class.
			#    Do not "simplify" this back to a type tuple.
			# 2. THE STAKES. STRATEGY_COMMAND is externally admitted, so an escape does not
			#    merely fail one command: it reaches the failure-rate tripwire and halt(), and
			#    HALTED has NO legal exit except an operator reset. Routine bad operator input
			#    must never latch live trading into HALT.
			# 3. THIS IS NOT A BARE-EXCEPT VIOLATION. That doctrine governs ZONE 2 — register /
			#    persist / emit — where a store or driver fault MUST stay loud. This guard
			#    covers ZONE 1 only: untrusted payload -> live object, exactly the one
			#    build_strategy call above, which contains no store call. Do not widen it.
			# 4. THE ERROR TIER IS SEPARATE because an unexpected type means a bug in OUR path,
			#    not operator junk, so it must be visibly distinct rather than laundered into
			#    the same warning.
			self.logger.error(
				'add for strategy %s failed with an UNEXPECTED error kind (%s) — nothing '
				'registered or persisted; this indicates a defect in the construction '
				'path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
			return
		# Warmability gate. An existing ring is a `deque(maxlen=...)` fixed at creation and
		# CANNOT resize, so re-registering a deeper consumer does not deepen it: a strategy
		# needing more base bars than the ring holds would register, stay is_ready False
		# FOREVER, and emit nothing while raising nothing. Keyed on `base_timeframe`, which
		# only the LIVE feed carries, so the backtest feed skips the gate cleanly.
		base_timeframe = getattr(self.feed, "base_timeframe", None)
		if base_timeframe is not None:
			try:
				depth = required_base_depth(
					strategy.warmup, strategy.timeframe, base_timeframe)
			except UnwarmableTimeframeError as exc:
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
		# The duplicate name is already pre-checked, so the only remaining raise is the
		# system-config mismatch — convert THAT to a loud no-op so an operator add never
		# raises into the queue.
		try:
			self._managed.add_strategy(strategy)
		except ValueError as exc:
			self.logger.warning(
				'add for strategy %s rejected — %s (a non-LONG_ONLY strategy needs the '
				'handler short-enabled, SHORT-01/D-07)', event.strategy_name, exc)
			return
		# The handle was parsed and type-checked by the gate ABOVE and is reused here, so
		# reaching this point with None means ABSENT, never malformed.
		if portfolio_id is not None:
			strategy.subscribe_portfolio(portfolio_id)
		# Persist parent-first (the child FK requires the registry row to exist first).
		self._persist_strategy(strategy, event)
		if portfolio_id is not None and self.registry_store is not None:
			# The column is Uuid — pass the handle straight through. A str() here would bind a
			# str to a Uuid column and raise StatementError at RUNTIME while mypy stayed green.
			self.registry_store.add_portfolio_subscription(
				strategy_name=strategy.name, portfolio_id=portfolio_id)
		# The poll IS the warmup wiring — see the method docstring. Queue-only.
		self.global_queue.put(UniversePollEvent(time=event.time))

	def _remove_strategy_verb(
		self, event: StrategyCommandEvent, strategy: Strategy
	) -> None:
		"""`remove`: force-flat FIRST, hold PENDING across cycles, then drop.

		Orphaning positions on remove was REJECTED: a removed strategy's positions would become
		unmanaged, with no exit logic owning them and nothing closing them on a bracket-less
		instrument. So the sequence is deactivate -> pending -> persist ``enabled=False`` ->
		poll -> drop only once the flat is observed on a FILL. That flat arrives on a LATER
		event cycle, which is why this is a PENDING state rather than an inline mutation.

		THE load-bearing design call: the force-close is driven by making the strategy's symbols
		LEAVE the derived membership. ``get_strategies_universe`` excludes a pending-removal
		strategy's tickers, so the follow-on poll re-derives membership WITHOUT them and the
		EXISTING force-close -> detach-on-flat machinery manages the positions out — reusing the
		pipeline rather than building a second force-close path. The instance STAYS in the roster
		and its ROW is KEPT until flat, so a crash mid-force-close rehydrates it
		PRESENT-BUT-DEACTIVATED and it resumes managing its own positions rather than orphaning
		them.

		⚠ CAVEAT — no auto-resume, and a restart makes a mid-``remove`` strategy
		INDISTINGUISHABLE from a merely-``disable``d one: both come back present-and-dark,
		because ``_pending_removals`` is in-memory only and is NOT reconstructed. The operator
		must RE-ISSUE the intended verb.
		"""
		# Idempotency: a name already pending is a no-op — no second force-close, no second poll.
		if self._managed.is_pending(strategy.name):
			return
		# Deactivate FIRST — the `is_active` gate stops NEW entries while the force-close plays out.
		if strategy.is_active:
			strategy.deactivate_strategy()
		# Enter the pending state BEFORE emitting the poll, so get_strategies_universe already
		# excludes this strategy when the poll re-derives membership.
		self._managed.mark_pending(strategy.name)
		# The row must reflect "should not be trading" even if the process dies mid-removal. Do
		# NOT delete it here: deleting first would leave a crash mid-force-close with open
		# positions and no row to rehydrate, hence no owner — orphaned.
		self._persist_strategy(strategy, event)
		self.global_queue.put(UniversePollEvent(time=event.time))
		# The no-position case completes on this same cycle.
		self._try_complete_removal(strategy)

	def _strategy_is_flat(self, strategy: Strategy) -> bool:
		"""True when NONE of ``strategy``'s tickers are held in any subscribed portfolio.

		A READ through the injected read-model, which the queue-only rule permits — only writes
		are queue-mediated. Checks tickers across subscribed portfolios, so a pair's BOTH legs
		must be flat. With no read model there is nothing to observe, so True; both composition
		roots pass one, making that a defensive default rather than a live degrade arm.
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
		"""Drop + delete a pending-removal strategy IFF its positions are now flat.

		⚠ THE STORE DELETE RUNS FIRST, AND THE ORDER IS LOAD-BEARING. It is the only operation
		here that can raise — the roster drop is membership-guarded and the pending discard is a
		``set.discard``. Doing the durable delete ahead of every in-memory mutation makes a store
		fault leave the strategy FULLY intact and STILL pending, so the next FILL retries the
		whole completion cleanly. The reverse order would strand the name in ``_pending_removals``
		with the object already gone from the roster: ``get_universe`` would keep filtering on a
		name nothing will ever discard, and ``on_fill`` would re-enter on a strategy ``by_name()``
		can no longer resolve.
		"""
		if not self._strategy_is_flat(strategy):
			return
		if self.registry_store is not None:
			# Child-then-parent delete — the store owns the FK ordering.
			self.registry_store.delete(strategy.name)
		self._managed.remove(strategy)
		self._managed.discard_pending(strategy.name)

	def on_fill(self, event: "Any") -> None:
		"""Completion hook: drop a pending-removal strategy once its positions are flat.

		Re-scans ALL pending removals on each FILL rather than keying on ``event.ticker``, so a
		multi-leg strategy completes on whichever fill flattens its LAST open leg.

		Wired on the LIVE FILL route only, AFTER ``PortfolioHandler.on_fill`` so the read model
		already reflects the settled position. NOT on the backtest FILL route at all.

		``pending_names()`` returns a snapshot: the loop discards entries as it completes them,
		so iterating the live set would raise.
		"""
		if not self._managed.has_pending():
			return
		by_name = self._managed.by_name()
		for name in self._managed.pending_names():
			strategy = by_name.get(name)
			if strategy is None:
				# Already dropped — a stale pending entry; clear it defensively.
				self._managed.discard_pending(name)
				continue
			self._try_complete_removal(strategy)

	def _reconfigure_allowlist_check(self, config: dict[str, Any]) -> "Optional[str]":
		"""Deny-list gate — returns a rejection reason or None.

		Deny ONLY the two closed sets and let ``_apply_params``' unknown-param rejection own the
		rest: a positive mutable-allowlist would be a second hand-maintained list that drifts
		from the class annotations. Called BEFORE the trial construction, so a refused key never
		builds a throwaway.
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
		"""Timeframe + capacity gate against the TRIAL — reason or None.

		LIVE feed only; the backtest feed lacks ``base_timeframe`` so the arm skips cleanly. A
		finer-than-base timeframe can never warm from a ring of base bars, and the off-grid guard
		would actively DROP sub-base bars even if they arrived. The capacity gate then rejects a
		depth the ring can never serve, since a fixed-maxlen deque cannot resize and the strategy
		would stay ``is_ready`` False FOREVER — registered, silent, error-free, never trading.

		Evaluating against the TRIAL's resolved values covers BOTH a timeframe change AND a
		window-grow that would exceed capacity.
		"""
		base_timeframe = getattr(self.feed, "base_timeframe", None)
		if base_timeframe is None:
			return None
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
		"""Apply-fail egress: a CRITICAL ``ErrorEvent`` on the queue.

		The trial already proved ``cls(**params)`` good, so a raise from the live
		``strategy.reconfigure`` is genuinely exceptional. The persist has ALREADY succeeded, so
		this does NOT roll back — it reports, and a restart rehydrates the intended
		configuration. The alert binds ``strategy_name`` and the error KIND ONLY, so no config
		value leaks to the operator channel.
		"""
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
		"""`reconfigure`: trial-validate -> persist -> apply -> re-warm.

		``_apply_params`` is ALREADY atomic and the single engine thread ALREADY provides the
		quiesce, so no lock or pause is needed. The genuine tear is that ``Strategy.reconfigure``
		calls ``validate()`` + ``_run_init()`` AFTER that commit, so a cross-field ``validate()``
		failure would leave a LIVE, trading strategy mutated into a state its own validator
		rejects. The fix is a THROWAWAY construction that runs the whole validate chain before
		the live instance is touched — no hand-rolled snapshot/rollback.

		Order: allowlist -> merge -> trial-validate -> direction re-gate -> warmability ->
		persist -> apply -> re-warm. Persist precedes apply so the DB and the live instance never
		diverge in the applied-but-unpersisted direction; apply-then-persist was rejected because
		a persist failure would silently lose the change on restart.
		"""
		config = event.config
		if not isinstance(config, dict):
			self.logger.warning(
				'reconfigure for strategy %s carries no config payload — ignored',
				event.strategy_name)
			return
		# Deny-list BEFORE any construction — a refused key must not even build a throwaway.
		reason = self._reconfigure_allowlist_check(config)
		if reason is not None:
			self.logger.warning(
				'reconfigure for strategy %s refused — %s', event.strategy_name, reason)
			return
		# Catalog gate: decode needs the injected allowlist to resolve the class. None is the
		# backtest/in-memory path, where reconfigure is never driven — a clean loud no-op.
		if self.strategy_catalog is None:
			self.logger.warning(
				'reconfigure for strategy %s refused — no strategy_catalog injected (D-10)',
				event.strategy_name)
			return

		# MERGE in ENCODED blob space: overlay the partial delta on the CURRENT full authoring
		# blob. An omitted field keeps its prior instance value (encode captured it); an
		# empty/identical payload merges to an identical blob and is a no-op.
		current_blob = encode_strategy_config(strategy)
		merged_blob = current_blob | dict(config)
		if merged_blob == current_blob:
			# Idempotency: nothing changed -> no persist, no apply, no re-warm, no poll (the
			# no-control-plane-churn contract). Stays warm.
			return
		# TRIAL-VALIDATE. decode_strategy_config is the ONLY function that knows the inverse
		# coercions, so routing the merge straight from blob space into the constructor without
		# it lands `entry_z` as the str '2'. The throwaway construction runs the full
		# _apply_params + validate() + _run_init() chain, so a cross-field failure raises HERE
		# with the LIVE instance untouched.
		rec = {
			"strategy_name": strategy.name,
			"strategy_type": type(strategy).__name__,
			"config_json": merged_blob,
		}
		try:
			cls, params = decode_strategy_config(
				rec, self.strategy_catalog, default_policy_registry())
			trial = cls(**params)
		except StrategyAdmissionError as exc:
			# Tier 1, per the canonical statement in `_add_strategy_verb`. Still NARROW — never
			# a bare except, so a store or infra fault is not silently eaten.
			self.logger.warning(
				'reconfigure for strategy %s rejected (%s) — live instance untouched',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — the ZONE-1 guard, per the canonical statement in `_add_strategy_verb`.
			# THE GENERAL RULE, stated verb-independently so the next verb inherits it: EVERY
			# verb that invokes `_run_init` on operator-supplied input carries a zone guard, and
			# the guard's SHAPE FOLLOWS ITS ZONE — zone 1 refuses as a loud no-op, zone 2 routes
			# into the designed CRITICAL path (the apply arm below).
			#
			# Scope is the exact add-verb analog: `build_strategy` IS `decode_strategy_config` +
			# `cls(**params)`, the same two calls this `try` spans. Do not split the try;
			# isolating `cls(**params)` would make this guard NARROWER than the one it mirrors.
			# Neither call touches a store, and the arm sits BEFORE the upsert below, so
			# returning here persists nothing and the live instance is unmutated.
			self.logger.error(
				'reconfigure for strategy %s failed with an UNEXPECTED error kind (%s) '
				'during the trial — live instance untouched and nothing persisted; this '
				'indicates a defect in the construction path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
			return
		# validate() does NOT check direction, and the gate reads HANDLER state, so the trial
		# construction CANNOT catch a short-enabling direction change: without this re-gate an
		# external reconfigure(direction=SHORT_ONLY) on a no-margin engine would sail through
		# onto a live strategy. The predicate lives on the single ManagedStrategies owner, which
		# add_strategy also consults, so the two cannot drift.
		if not self._managed.direction_admissible(trial.direction):
			self.logger.warning(
				'reconfigure for strategy %s refused — a non-LONG_ONLY direction requires '
				'BOTH allow_short_selling AND enable_margin (SHORT-01/D-07)',
				event.strategy_name)
			return
		# Warmability gate against the TRIAL (finer-than-base / non-multiple /
		# over-capacity). Skips cleanly on the backtest feed.
		reason = self._reconfigure_warmability_check(trial)
		if reason is not None:
			self.logger.warning(
				'reconfigure for strategy %s refused — %s', event.strategy_name, reason)
			return
		# PERSIST FIRST, from the TRIAL's FULL authoring set — never the partial delta, which
		# would let the row drift from the live instance and silently revert unchanged fields on
		# restart. `enabled` is the LIVE strategy's activation: a fresh trial is is_active=True,
		# and reconfigure does not change activation.
		if self.registry_store is not None:
			self.registry_store.upsert(
				strategy_name=strategy.name,
				strategy_type=type(strategy).__name__,
				config=encode_strategy_config(trial),
				enabled=strategy.is_active,
				at=event.time)
		# APPLY to the live instance, proven good by the trial. Application happens BETWEEN
		# event cycles on the single engine thread, so no signal is in flight mid-apply — in
		# the single-writer model that IS the quiesce. When apply nonetheless throws, log/emit
		# CRITICAL and do NOT roll back the persist: the DB holds the NEW config and a restart
		# heals (the deliberate persist-then-apply asymmetry).
		try:
			strategy.reconfigure(**params)
		except Exception as exc:
			# ZONE 2 guard. The SAME unbounded hazard as the trial arm above, but a DIFFERENT
			# SHAPE, because the zone is different.
			#
			# 1. IT ROUTES INSTEAD OF NO-OPING because this is POST-PERSIST, so a silent refusal
			#    would be a lie — the DB already holds the new config. The asymmetry is
			#    deliberate: report a CRITICAL ErrorEvent WITHOUT rolling back, on the invariant
			#    that the DB holds the NEW config and a restart heals.
			# 2. NEITHER EXTREME WORKS. Letting an arbitrary `init()` exception escape to halt()
			#    would BYPASS this design's own handling of exactly this case and latch live
			#    trading; a blanket swallow would hide genuine zone-2 failures.
			# 3. FAIL-LOUD IS NOT WEAKENED, and the boundary is structural rather than
			#    conventional: this `try` body is the SINGLE `strategy.reconfigure(...)` call and
			#    contains no store call. The upsert sits OUTSIDE it, so a store/driver fault
			#    still propagates. Do NOT move the upsert inside, and do not widen the body.
			self._emit_reconfigure_apply_failure(event, strategy, exc)
			return
		# NO force-flat: open positions stay open and their exits are governed by the NEW
		# params, explicitly the operator's responsibility. Always-flatten would close positions
		# for a harmless sizing tweak.
		#
		# RE-WARM. `_run_init` UNCONDITIONALLY resets the per-symbol handle state, so a
		# handle-bearing instance is DARK after ANY applied reconfigure. `mark_unwarm` is
		# idempotent here but also covers the PairStrategy override; `_request_rewarm` marks the
		# symbols FAILED so the retry re-warms on the follow-on poll — the SAME warm path
		# `enable`/`add` use. During the dark re-warm the instance cannot emit STRATEGY-driven
		# exits, so an open position rides its resting exchange brackets until warm.
		strategy.mark_unwarm()
		self._request_rewarm(strategy)
		self.global_queue.put(UniversePollEvent(time=event.time))

	def on_strategy_command(self, event: StrategyCommandEvent) -> None:
		"""Apply one control-plane verb to one strategy, live AND durably.

		The dispatch surface (live-only). Locates the strategy whose ``.name`` matches
		``event.strategy_name`` — the durable per-instance identity — and applies the verb
		IDEMPOTENTLY. The LIGHT verbs (no force-flat, no construction):

		- ``enable`` — activate + persist, then FORCE A RE-WARM. It does NOT trade the next bar.
		- ``disable`` — deactivate + persist. The object STAYS in the roster and open positions
		  and resting brackets run to natural exit via the execution layer, which never reads
		  this flag, so it stops NEW entries only. Across a restart a disabled strategy is
		  REHYDRATED present-but-dark, so it still owns its positions rather than being dropped
		  at boot with them orphaned.
		- ``subscribe_portfolio`` / ``unsubscribe_portfolio`` — the fan-out edge is
		  RUNTIME-MUTABLE. Unsubscribing the LAST portfolio leaves an empty list and zero rows,
		  a LEGAL state where the strategy computes but fans out to nobody.
		- ``add_ticker`` / ``remove_ticker`` — the membership verbs, which also persist, since a
		  ticker change IS a reconfigure of the ``tickers`` authoring param. ``remove_ticker``
		  refuses a remove that would empty the list.

		The ``mutated`` flag gates BOTH the persist and the follow-on, so a no-op verb mutates
		nothing, persists nothing and emits nothing. An unknown name, an unknown verb, or a
		malformed payload is a LOUD no-op — warn and return, NEVER a raise into the queue.

		Verbs are applied on the single engine thread draining the queue, so a verb never
		interleaves with a signal mid-application — in the single-writer model that IS the
		quiesce.

		Parameters
		----------
		event: `StrategyCommandEvent`
			The control-plane command addressed to one strategy by name.
		"""
		# `add` targets a NEW name that is by design NOT yet in the roster, so it is dispatched
		# BEFORE the by-name guard below, which would otherwise reject every add as "unknown
		# strategy". A pair `add` lands here too: the pair guard governs only EXISTING
		# instances.
		if event.verb == "add":
			self._add_strategy_verb(event)
			return
		by_name = self._managed.by_name()
		strategy = by_name.get(event.strategy_name)
		if strategy is None:
			self.logger.warning(
				'StrategyCommandEvent for unknown strategy %s (verb=%s, symbol=%s) — ignored',
				event.strategy_name, event.verb, event.symbol)
			return
		# VERB-SCOPED pair guard, refusing EXACTLY _PAIR_REFUSED_VERBS. Pairs must
		# add/remove/enable/disable/subscribe and rehydrate as FULL registry instances, so a
		# blanket refusal would silently gut pair durability while LOOKING conservative — a
		# refusal that is too broad is as much a defect as one too narrow.
		#
		# `reconfigure` is refused because three sites compose into stranded money:
		# `PairStrategy._entry` sets NO stop_loss/take_profit, so an OPEN SPREAD HAS NO RESTING
		# EXCHANGE BRACKET and its ONLY exit is `evaluate_pair()`; `_run_init` unconditionally
		# re-creates the buffers and resets the bar count, and `reconfigure()` ALWAYS calls it;
		# and `is_pair_ready()` then needs `beta_warmup + z_lookback` bars (280 for the
		# reference). Net: reconfiguring a pair holding an open spread strands an UNHEDGED,
		# BRACKET-LESS spread with NO REACHABLE EXIT for 280 bars — ~12 days on 1h, 280 on 1d.
		# Do NOT re-litigate without re-reading those three methods.
		#
		# The ticker verbs stay refused because a pair is bound to an EXACT-2-ticker contract,
		# so mutating its tickers would make EVERY subsequent `_dispatch_pair` raise — an
		# unbounded self-inflicted ErrorEvent storm with no recovery.
		if isinstance(strategy, PairStrategy) and event.verb in _PAIR_REFUSED_VERBS:
			self.logger.warning(
				'StrategyCommandEvent verb=%s refused for pair strategy %s — pairs '
				'accept the lifecycle verbs (D-16) but refuse reconfigure (D-17) and '
				'the ticker verbs (CR-01: the exact-2-ticker contract is immutable at '
				'the control-plane seam)',
				event.verb, event.strategy_name)
			return
		# A heavy lifecycle verb. NOT in _PAIR_REFUSED_VERBS, so a pair remove reaches here and
		# force-flats BOTH legs. It owns its persist, poll and pending state, so it returns
		# before the light-verb `mutated` tail below.
		if event.verb == "remove":
			self._remove_strategy_verb(event, strategy)
			return
		# Owns its own persist, poll and the persist-then-apply asymmetry, so it returns before
		# the light-verb `mutated` tail. A PairStrategy never reaches here — the pair guard
		# above already refused it.
		if event.verb == "reconfigure":
			self._reconfigure_strategy_verb(event, strategy)
			return
		mutated = False
		# A deferred (op, portfolio_id) child-table write, applied AFTER the parent upsert —
		# the child row carries an FK to the registry row. The id travels as the HANDLE, not
		# `str(pid)`: the column is Uuid, so a stringified id would raise StatementError at
		# runtime.
		child_write: "Optional[tuple[str, PortfolioId]]" = None
		if event.verb == "enable":
			if not strategy.is_active:
				strategy.activate_strategy()
				# ⚠ THE LOAD-BEARING HALF OF `enable`. The is_active guard sits FIRST in on_bar,
				# so this strategy's indicators FROZE while disabled: their values were computed
				# over a window that now has an N-bar HOLE. Trading the next bar would let
				# SMA/MACD silently produce wrong values across that discontinuity — invisible,
				# because warmth is monotone and nothing downstream re-checks.
				#
				# mark_unwarm is a named wrapper over the handle reset, NOT a flag, so warmth
				# stays derived from is_ready. PairStrategy overrides it to clear the spread
				# buffers too, since a handle-free pair is always is_ready==True and a
				# handles-only unwarm would let it re-enter on a cold β.
				strategy.mark_unwarm()
				self._request_rewarm(strategy)
				mutated = True
		elif event.verb == "disable":
			if strategy.is_active:
				# Do NOT unwarm here — `enable` discards the frozen state anyway, and
				# unwarming on the way DOWN would discard state a re-enable never needs.
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
				# A duplicate would fan ONE decision out to the same portfolio twice.
				strategy.subscribe_portfolio(portfolio_id)
				child_write = ("add", portfolio_id)
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
				child_write = ("remove", portfolio_id)
				# Removing the LAST portfolio is a legal state, deliberately NOT guarded.
				mutated = True
		elif event.verb in ("add_ticker", "remove_ticker"):
			# `symbol` is `str | None` and most verbs carry none, so the read lives inside
			# the only branches that have one.
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
						# Removing the last ticker would violate the non-empty list[str]
						# invariant. A documented no-op.
						self.logger.warning(
							'remove_ticker %s refused for strategy %s — would empty its '
							'ticker set (non-empty invariant preserved)',
							symbol, event.strategy_name)
						return
					strategy.tickers.remove(symbol)  # idempotent removal
					mutated = True
		else:
			self.logger.warning(
				'StrategyCommandEvent unknown verb %s for strategy %s — ignored',
				event.verb, event.strategy_name)
			return
		if not mutated:
			return
		# EVERY mutating verb persists, parent row first. The subscribe/unsubscribe verbs are
		# routed through the parent upsert too, even though they only change the CHILD table.
		# It looks redundant, but the child carries an FK to the registry row, so writing one
		# for a strategy the registry has never seen raises IntegrityError straight into the
		# queue — violating this method's never-raise contract. That is not a workaround for
		# the FK; it is what the FK is saying: a subscription edge whose instance is absent
		# from the registry is an orphan rehydrate would silently drop at restart.
		self._persist_strategy(strategy, event)
		if child_write is not None and self.registry_store is not None:
			operation, stored_portfolio_id = child_write
			if operation == "add":
				self.registry_store.add_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
			else:
				self.registry_store.remove_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
		# Mutate happens-before re-select. Queue-only cross-domain write.
		if event.verb in _POLL_FOLLOW_ON_VERBS:
			self.global_queue.put(UniversePollEvent(time=event.time))
