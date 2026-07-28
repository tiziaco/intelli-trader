"""Strategy control-plane collaborator.

`StrategyLifecycleManager` owns the entire STRATEGY_COMMAND control plane: the two
route-facing entry points `on_strategy_command` / `on_fill`, the verb/helper privates they
reach, and the module-level verb constants only those bodies read.
`StrategiesHandler.on_strategy_command` / `on_fill` are 1-line delegations.

Injected dep subset (constructor injection, all real at construction): `managed` (the single
`ManagedStrategies` roster owner), `global_queue`, `feed`, `registry_store`,
`strategy_catalog`, `portfolio_read_model`, `logger`. It holds NO handler back-reference.

Every import is at MODULE TOP. This module is on the backtest import graph by design — the
handler constructs it unconditionally — and importing it leaks ZERO sqlalchemy / psycopg2 /
alembic and leaves the config `sql` cached_property unresolved, which
`test_okx_inertness.py` asserts positively.

⚠ DEVIATION from the order-domain analog: `LifecycleManager` (order_handler) declares "NO
queue access". This manager DOES hold `global_queue` — the bodies emit `UniversePollEvent`
(the warmup and force-close wiring) and a CRITICAL `ErrorEvent` (the apply-fail egress)
directly. That egress IS the collaborator's contract, not a layering leak: it is queue-only,
so `UniverseHandler` / `Universe` are never called and `PortfolioHandler` is never imported.

⚠ NEGATIVE INVARIANT — ZERO roster state. This class owns NO `strategies` list and NO
`_pending_removals` set; every roster and pending-removal access routes through
`self._managed`. Giving this manager its OWN pending set is the silent-corruption trap the
extraction exists to avoid: `ManagedStrategies.get_universe` reads ITS set to exclude a
pending strategy's tickers, so a second set here would leave membership never re-deriving,
the force-close poll never firing, and `remove` hanging forever with NO error raised. One
source of truth: `ManagedStrategies`.

⚠ SECURITY. `strategy_type` arrives as an untrusted string on an external STRATEGY_COMMAND
payload. `_add_strategy_verb` and `_reconfigure_strategy_verb` resolve it through the
injected `strategy_catalog` by CLOSED DICT LOOKUP and nothing else, and LOUD-reject when
the catalog is None. There is deliberately no `importlib`, no `__import__`, no
`getattr`-on-module and no default catalog anywhere on those paths: resolving a type by
name would convert the operator API into remote code execution.

TABS file (matching `strategy_handler/` source).
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
	# The live-only Universe seam is never imported at runtime, so no runtime import
	# cost is added and the annotation stays a string. This is a module-level import
	# under a guard the interpreter never executes, NOT a function-local import.
	from itrader.universe.universe import Universe


# Verb-scoped pair guard: a PairStrategy refuses EXACTLY these verbs and accepts every
# other one — see the rationale block in on_strategy_command.
_PAIR_REFUSED_VERBS = frozenset({"reconfigure", "add_ticker", "remove_ticker"})

# The verbs whose effect requires a UniversePollEvent follow-on. The two ticker verbs
# change universe MEMBERSHIP; `enable` needs it because enabling unwarms the strategy and
# the re-warm rides the FAILED-retry, which only runs on a poll. disable/subscribe/
# unsubscribe change neither membership nor warmth, so no poll. `reconfigure` emits its
# OWN poll inline (like `remove`), so it is NOT listed here.
_POLL_FOLLOW_ON_VERBS = frozenset({"add_ticker", "remove_ticker", "enable"})

# The `reconfigure` mutability DENY-lists. `reconfigure` MUTATES the authoring surface, but
# these two closed key sets are refused loudly BEFORE any throwaway is built; everything else
# is left to _apply_params' existing unknown-param rejection, so no second hand-maintained
# allowlist can drift from the class annotations.
#
# _RECONFIGURE_IMMUTABLE — IDENTITY + DERIVED, never a param:
#   - `strategy_type`: changing the class IS a different strategy (remove + add). An ENVELOPE
#     key, not a declared param, so _apply_params would also reject it — kept here as
#     defense-in-depth and to name the remove+add path in the operator-facing reject.
#   - `name`: the store PK. A rename would UPSERT a NEW row and ORPHAN the old one; the codec
#     omits `name` from the blob precisely so a PK-vs-blob disagreement is unrepresentable.
#     Identity is not a param — renaming is remove + add.
#   - `warmup` / `max_window`: `_run_init` UNCONDITIONALLY overwrites both from the declared
#     indicators, so a passed value is silently clobbered. Refuse loudly rather than
#     accept-then-clobber.
# Hardcoded rather than imported from config_codec so the deny-list stays a self-contained
# closed set at the control-plane seam; it MUST track config_codec._DERIVED_FIELDS.
_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type", "name", "warmup", "max_window"})

# `tickers` is owned by add_ticker/remove_ticker — one path per concern.
_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})


class StrategyLifecycleManager:
	"""The STRATEGY_COMMAND control plane.

	Owns `on_strategy_command` / `on_fill` — the two route-facing entry points
	StrategiesHandler delegates into — plus the verb/helper privates. See the module
	docstring for the queue-access deviation from the order-domain analog, the
	ZERO-roster-state invariant, and the closed-dict-lookup security contract.

	The three live deps all accept `None` as their legal backtest/in-memory state, and every
	persist arm short-circuits on it. `registry_store` and `strategy_catalog` keep
	`Optional[Any]` VALUES so the SQL stack stays off this module's annotations.
	`portfolio_read_model` is the EXCEPTION: `core/portfolio_read_model.py` pulls no SQL —
	only stdlib plus `core.enums` and `core.ids`, both already on this import graph — so
	naming the real protocol costs nothing in inertness and buys a genuine `mypy --strict`
	check of the `get_position` call in `_strategy_is_flat`, which an erased `Any` would
	suppress. The manager is the SINGLE OWNER of all three: the handler exposes read-through
	properties over these attributes rather than keeping its own copies, so a
	post-construction assignment on the handler can never desync the two.

	The logger is bound FRESH with `component="StrategyLifecycleManager"` so the control
	plane's log lines are attributable to the collaborator that owns them.
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
			The handler's logger, re-bound to this component. Concretely typed so
			``mypy --strict`` checks this module's logger call sites rather than
			erasing them behind ``Any``.
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

		The public same-object read seam the handler's ``_universe`` property forwards to, so
		no caller reaches across into this object's private attribute. Read-only by design:
		``set_universe`` stays the SOLE write path, so widening the read surface cannot widen
		the write surface.
		"""
		return self._universe

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the dynamic universe so ``_request_rewarm`` can mark symbols FAILED.

		Forwarded unconditionally from ``StrategiesHandler.set_universe``, which keeps its own
		reference for the per-tick readiness gate in ``on_bar``. Two references to ONE object is
		the intended shape.
		"""
		self._universe = universe

	def _persist_strategy(
		self, strategy: Strategy, event: StrategyCommandEvent
	) -> None:
		"""Write the strategy's post-mutation state to the durable registry.

		A clean no-op when no registry store is injected (the backtest/in-memory path).

		Writes the FULL post-mutation authoring set from ``encode_strategy_config``, never the
		incoming delta: a partial write would let the row drift from the live instance, and the
		row is what rehydrate reconstructs from at restart — a divergence there resurrects a
		strategy that never existed.

		``at`` comes from ``event.time`` — BUSINESS time, never wall clock. The store is
		clock-free by contract, so the audit trail stays reproducible.
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

		``mark_unwarm`` alone is already CORRECT — ``is_ready``/``is_pair_ready`` gate emission,
		so the strategy re-warms from live bars and cannot signal off a holed window either way.
		This method only makes it FAST: without it a re-enabled 1d strategy would wait ~``warmup``
		real bars (100 days for SMA_MACD) before trading again, which is a control-plane verb
		behaving like a decommission.

		There is no strategy-level warm API to call — the warmup pipeline is per-SYMBOL and owned
		by ``UniverseHandler`` behind the queue boundary. Its existing trigger is the FAILED-retry:
		a still-desired member whose readiness is FAILED is re-warmed on the next poll (``on_poll``
		flips it PENDING and folds it into ``added`` -> ``_begin_warmup`` -> ``BarsLoaded`` ->
		``on_bars_loaded`` replays the window through ``strategy.update``). So marking this
		strategy's symbols FAILED and letting the follow-on poll land IS the re-warm request — one
		warm path, no new event type, no cross-domain call.

		``_universe`` is None on the backtest/in-memory path, where there is no warmup pipeline at
		all and the passive re-warm above is the whole story — hence the short-circuit.

		Two accepted consequences, both bounded and self-healing:
		  - a symbol shared with an already-warm sibling strategy goes dark for ONE poll interval
		    (readiness is per-symbol and aggregate by design);
		  - the replayed warmup bars are re-delivered to that warm sibling, which the monotonic
		    guard in ``Strategy.update`` rejects before any state mutation. That guard exists for
		    exactly this re-warm case.
		"""
		if self._universe is None:
			return
		for ticker in strategy.tickers:
			# mark_failed, NOT mark_pending: only FAILED members are collected by the retry
			# in on_poll, so PENDING would leave the symbol dark FOREVER — the
			# silent-permanent-no-warm failure mode. The re-warm streak counter is
			# incremented at the FAILURE sites, not here, so this raises no false alarm.
			self._universe.mark_failed(ticker)

	def _portfolio_id_from(
		self, event: StrategyCommandEvent
	) -> "Optional[PortfolioId]":
		"""Parse ``config["portfolio_id"]`` into the handle the fan-out expects, or None.

		The payload is operator/FastAPI-supplied and therefore untrusted: the light verbs read
		ONLY this one key, and it is validated and PARSED here so a malformed payload never
		reaches live strategy state or SQL. A miss returns None and the caller makes it a loud
		no-op — this path must never raise into the queue.

		⚠ The parse is a CORRECTNESS requirement, not a typing nit. ``subscribed_portfolios`` is
		typed ``list[PortfolioId]`` and ``on_bar`` fans each intent over it, putting each id
		STRAIGHT onto ``SignalEvent.portfolio_id``. A bare ``str`` reaches the portfolio lookup as
		an id matching NOTHING: the subscription would look perfectly healthy and then fan signals
		into the void. Value-equality assertions pass while the type is wrong, so this is pinned
		by a TYPE assertion.

		Mirrors ``registry/rehydrate.py::_resolve_portfolio_id`` but returns None instead of
		raising: rehydrate quarantines a bad instance at boot, whereas a bad runtime command is a
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
			return None

	def _portfolio_id_supplied(self, event: StrategyCommandEvent) -> bool:
		"""The presence probe that makes ABSENT and MALFORMED distinguishable.

		``_portfolio_id_from`` deliberately collapses FOUR outcomes into one ``None``:
		config-not-a-dict, key absent, wrong value type, unparseable UUID. That collapse is RIGHT
		for the two light verbs (``subscribe_portfolio`` / ``unsubscribe_portfolio`` warn on every
		``None`` — the operator asked for a subscription and did not get one, whatever the cause)
		and WRONG for ``add``, where absence is a LEGAL state (register now, wire the portfolio
		later) but malformation is operator error. This is the one probe that tells them apart.

		The ``"portfolio_id"`` key name and the ``isinstance(config, dict)`` guard live HERE,
		adjacent to ``_portfolio_id_from``, rather than at the call site: a call site re-reading
		``event.config`` would duplicate the parsing this pair centralizes and let the probe and
		the parser drift apart.

		An explicit ``None`` VALUE counts as NOT supplied. A FastAPI/Pydantic model declaring
		``portfolio_id: str | None = None`` serializes the unsubscribed case as a null on EVERY
		add, so a bare key-PRESENCE probe would reject the most likely shape of the legal
		no-subscription payload. Every OTHER value — non-``str``, empty ``str``, non-UUID ``str``
		— is supplied-and-malformed.
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

		Access control: the injected ``strategy_catalog`` IS the allowlist. Without it nothing may
		be instantiated from an external payload, and resolution goes ONLY through
		``build_strategy`` -> ``decode_strategy_config`` -> ``resolve_strategy_class``, a closed
		dict lookup. This branch NEVER resolves a type by dynamic module import or by evaluating
		the payload as source text — either would turn the operator API into remote code execution.

		One reconstruction path: ``add`` builds through the IDENTICAL ``build_strategy`` path
		rehydrate uses, so the two cannot drift. Construction runs the real ``_apply_params`` ->
		``validate()`` -> ``_run_init()``, so unknown/missing-param rejection and warmup
		re-derivation happen on the real path.

		Warm via the poll: a freshly constructed instance is DARK (its handles are reset at
		construction, so ``is_ready`` is False until bars feed it). The emitted
		``UniversePollEvent`` IS the whole warmup wiring — membership is derived FROM the
		registered strategies, so the poll re-selects, the new symbol enters the universe, and the
		EXISTING pipeline runs ``spawn_warmup`` -> ``BarsLoaded`` -> ``on_bars_loaded``
		(mark_ready) -> it trades; a ``BarsLoadFailed`` -> FAILED -> retry next poll. This works on
		a COLD symbol, the COMMON case — add-only-if-already-warm was rejected because it would
		refuse any genuinely new symbol. NO second warmup path is built: ``live_bar_feed``
		explicitly refuses a second state-building path, and a parallel path would re-open the
		paper-replay parity gate.

		Queue-only: the poll is emitted on ``self.global_queue``; this NEVER calls
		``UniverseHandler`` or touches ``Universe``.
		"""
		# Catalog gate — the access-control allowlist. Its absence is a LOUD reject: without
		# an injected catalog nothing may be instantiated from an external payload. Types
		# resolve ONLY through the allowlist (build_strategy below), never by consulting the
		# import system or interpreting the payload as source text — that would convert the
		# operator API into arbitrary code execution.
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
		# Duplicate-name loud reject BEFORE any construction — a collision would silently
		# shadow another instance and overwrite its persisted state. Pre-checked by name
		# (rather than catching add_strategy's raise) so nothing is constructed. Reads the
		# SINGLE roster owner; this manager holds no roster of its own.
		if any(existing.name == event.strategy_name for existing in self._managed.strategies):
			self.logger.warning(
				'add for strategy %s refused — a strategy with that name is already '
				'registered (D-02); the existing instance is left untouched',
				event.strategy_name)
			return

		# A SUPPLIED but unparseable portfolio_id rejects the WHOLE add. Reject-without-
		# registering is this method's established idiom: the catalog gate, the duplicate
		# gate and the direction arm all refuse outright rather than half-apply. Letting a
		# malformed id fall into the ABSENT branch below would leave a registered, persisted,
		# warming strategy with zero subscriptions — and on_bar fans each intent over
		# subscribed_portfolios, so an empty list means literally zero SignalEvents forever.
		# A healthy-looking engine that trades nothing is worse than a loud refusal.
		#
		# ABSENT stays a clean legal no-op: the operator may add a strategy unsubscribed and
		# wire it later with subscribe_portfolio. Only supplied-and-unparseable is refused,
		# and `_portfolio_id_supplied` is what separates the two.
		#
		# PLACEMENT is load-bearing. This is a pure payload check with no dependency on the
		# constructed object, so it belongs AHEAD of every state mutation: rejecting at the
		# parse site further down would have to UNDO a completed `_managed.add_strategy`
		# roster insert. It sits deliberately OUTSIDE the two-tier zone-1 guard, which stays
		# scoped to the single `build_strategy` call — this arm raises nothing.
		portfolio_id = self._portfolio_id_from(event)
		if portfolio_id is None and self._portfolio_id_supplied(event):
			# Names the KIND/condition only — never echoes the payload value, the
			# declared-fields-only rule the tier-1 arm below follows.
			self.logger.warning(
				'add for strategy %s refused — its config["portfolio_id"] is present but '
				'unparseable; nothing was registered or persisted. A registered strategy '
				'with no subscription computes signals and fans them to nobody. Re-issue '
				'with a valid portfolio UUID, or omit the key to add it unsubscribed',
				event.strategy_name)
			return

		# Build the row-shaped record from the payload. The config_json blob is the payload
		# MINUS portfolio_id (a subscription is a child-table concern, NOT a declared param —
		# leaving it in the blob would make build_strategy's _apply_params raise
		# UnknownParamError). strategy_type stays IN the blob (an envelope key decode reads)
		# AND is the top-level column; the two agree because the .add factory folds one value
		# into both. build_strategy is the IDENTICAL path rehydrate uses.
		blob = {key: value for key, value in config.items() if key != "portfolio_id"}
		rec = {
			"strategy_name": event.strategy_name,
			"strategy_type": strategy_type,
			"config_json": blob,
		}
		try:
			strategy = build_strategy(rec, catalog=self.strategy_catalog)
		except StrategyAdmissionError as exc:
			# Tier 1 — EXPECTED validation kinds, i.e. "the operator sent junk". A loud no-op
			# naming the error KIND, never the payload values. StrategyAdmissionError is the
			# shared ancestor of every strategy-payload refusal (unknown strategy_type,
			# undeserializable blob, param drift either direction) — one name instead of a
			# hand-listed tuple that drifts out of sync with its siblings.
			#
			# It needs no `ValueError` companion: StrategyAdmissionError is declared
			# `(ITraderError, ValueError)`, and the bare-ValueError residue (validate() and the
			# _apply_params tickers/enum guards) is TYPED as StrategyValidationError by the wrap
			# in Strategy.__init__ / Strategy.reconfigure. A third-party validate() override is
			# covered too, since the wrap converts at the RAISE boundary.
			self.logger.warning(
				'add for strategy %s rejected (%s) — nothing registered or persisted',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — THE ZONE-1 GUARD. Any OTHER construction failure is STILL a loud no-op.
			# This is the canonical statement of the rule; the reconfigure verb's two guards
			# refer back here.
			#
			# 1. WHY NO FINITE TUPLE SUFFICES. build_strategy -> cls(**params) -> _apply_params
			#    -> validate() -> _run_init() -> self.init(), and init() is ARBITRARY
			#    USER-AUTHORED strategy code from my_strategies/. The set of exceptions escaping
			#    construction is unbounded BY CONSTRUCTION, so enumerating more types fixes the
			#    instance, never the class. Do not "simplify" this back to a type tuple.
			# 2. WHY THE STAKES ARE HIGH. STRATEGY_COMMAND is externally admitted
			#    (LiveTradingSystem.add_event), so an escape does not merely fail one command:
			#    it reaches ErrorPolicy.record_failure -> the failure-rate tripwire -> halt(),
			#    and HALTED has NO legal exit except an operator reset_halt(). Routine bad
			#    operator input must never latch live trading into HALT.
			# 3. WHY THIS DOES NOT VIOLATE THE NEVER-A-BARE-EXCEPT DOCTRINE. That doctrine
			#    governs ZONE 2 — register / persist / emit (add_strategy, _persist_strategy,
			#    add_portfolio_subscription, global_queue.put) — where a store or driver fault
			#    MUST stay loud so fail-loud holds. This guard covers ZONE 1 ONLY: untrusted
			#    payload -> live object, exactly the one build_strategy call above, which
			#    contains no store call. Do not widen it past that boundary.
			# 4. WHY THE ERROR TIER IS SEPARATE. An unexpected type means a bug in OUR
			#    construction path, not operator junk, so it must be visibly distinct rather
			#    than laundered into the same warning. exc_info carries the diagnostic; the
			#    message names no payload values.
			self.logger.error(
				'add for strategy %s failed with an UNEXPECTED error kind (%s) — nothing '
				'registered or persisted; this indicates a defect in the construction '
				'path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
			return
		# Warmability gate. `cache_capacity()` re-derives lazily, but an existing ring is a
		# `deque(maxlen=...)` fixed at creation and CANNOT resize, so re-registering a deeper
		# consumer does not deepen it — a strategy needing more base bars than the ring holds
		# would register, stay is_ready False FOREVER, and emit nothing while raising nothing.
		# That silent permanent no-trade is a correctness defect, so reject loudly. Keyed on
		# `base_timeframe`, which only the LIVE feed carries, so the backtest/in-memory feed
		# skips the gate cleanly. Ring RESIZE is deferred to
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
		# Register through add_strategy and its direction gate. The duplicate name is
		# already pre-checked, so the only remaining raise is the system-config mismatch —
		# convert THAT to a loud no-op so an operator add never raises into the queue.
		try:
			self._managed.add_strategy(strategy)
		except ValueError as exc:
			self.logger.warning(
				'add for strategy %s rejected — %s (a non-LONG_ONLY strategy needs the '
				'handler short-enabled, SHORT-01/D-07)', event.strategy_name, exc)
			return
		# Subscribe the portfolio_id carried alongside the config. It was parsed and
		# type-checked by the gate ABOVE and the handle is reused here — the parse does NOT
		# happen at this site. Reaching here with None therefore means ABSENT, never
		# malformed: the strategy computes but fans out to nobody (a legal state), and the
		# subscribe_portfolio verb can wire it later.
		if portfolio_id is not None:
			strategy.subscribe_portfolio(portfolio_id)
		# Persist parent-first (the child FK requires the registry row to exist first).
		self._persist_strategy(strategy, event)
		if portfolio_id is not None and self.registry_store is not None:
			# The column is Uuid — pass the PortfolioId handle straight through. A str() here
			# would bind a str to a Uuid column and raise StatementError at RUNTIME while mypy
			# stayed green.
			self.registry_store.add_portfolio_subscription(
				strategy_name=strategy.name, portfolio_id=portfolio_id)
		# The poll IS the warmup wiring — see the method docstring. Queue-only.
		self.global_queue.put(UniversePollEvent(time=event.time))

	def _remove_strategy_verb(
		self, event: StrategyCommandEvent, strategy: Strategy
	) -> None:
		"""`remove`: force-flat FIRST, hold PENDING across cycles, then drop.

		The three lifecycle behaviours stay DISTINCT and are never conflated:
		  - ``disable`` -> stop NEW entries, KEEP open positions + resting brackets;
		  - ``remove`` -> force-flat, WAIT flat, then drop the object + delete the rows;
		  - ``reconfigure`` -> apply live, KEEP positions.

		Orphaning positions on remove was REJECTED: a removed strategy's positions would become
		unmanaged, with no exit logic owning them and nothing closing them on a bracket-less
		instrument. So the sequence is deactivate -> pending -> persist ``enabled=False`` -> poll
		(drive the force-close) -> drop only once the flat is observed on a FILL. Because the flat
		is observed on a LATER event cycle this is a PENDING state, mirroring the pending-bracket
		and reconnect-resume precedents, not an inline mutation.

		THE load-bearing design call: the force-close is driven by making the strategy's symbols
		LEAVE the derived membership. ``get_strategies_universe`` excludes a pending-removal
		strategy's tickers, so the follow-on ``UniversePollEvent`` re-derives membership WITHOUT
		them, the poll's REMOVE branch fires ``_on_symbol_removed`` for the now-unmembered symbols,
		and the EXISTING force-close -> detach-on-flat machinery manages the positions out —
		reusing the pipeline rather than building a second force-close path. The instance STAYS in
		the MANAGED ROSTER and its ROW is KEPT (persisted ``enabled=False``) until flat, so a crash
		mid-force-close rehydrates it PRESENT-BUT-DEACTIVATED and it resumes managing its own
		positions rather than orphaning them. Queue-only: ``UniverseHandler`` is never called and
		``Universe`` is never touched.

		⚠ CAVEAT — no auto-resume. An interrupted ``remove`` does NOT re-drive the force-close on
		restart: the rehydrated strategy comes back merely deactivated (``_pending_removals`` is
		in-memory only and is NOT reconstructed), so the operator must RE-ISSUE ``remove``.

		⚠ FOOTGUN — after a restart a strategy mid-``remove`` is INDISTINGUISHABLE from a
		merely-``disable``d one: both come back present-and-dark, because the removing/disabled
		distinction lived only in the in-memory ``_pending_removals`` set. Re-issuing the intended
		verb is how the operator disambiguates.
		"""
		# Idempotency: a name already pending is a no-op — no second force-close, no second
		# poll. The unknown-name case is the shared loud no-op upstream.
		if self._managed.is_pending(strategy.name):
			return
		# Deactivate FIRST — the `is_active` gate stops NEW entries while the force-close
		# plays out.
		if strategy.is_active:
			strategy.deactivate_strategy()
		# Enter the pending state BEFORE emitting the poll, so get_strategies_universe
		# already excludes this strategy when the poll re-derives membership.
		self._managed.mark_pending(strategy.name)
		# Persist enabled=False — the row must reflect "should not be trading" even if the
		# process dies mid-removal. Do NOT delete the row here: the order is force-flat ->
		# wait flat -> THEN drop. Deleting first would leave a crash mid-force-close with
		# open positions and no row to rehydrate, so no owner: orphaned.
		self._persist_strategy(strategy, event)
		# The poll drives the force-close (see the docstring). Queue-only.
		self.global_queue.put(UniversePollEvent(time=event.time))
		# Complete immediately when the flat condition already holds (the no-position case
		# completes on the same cycle).
		self._try_complete_removal(strategy)

	def _strategy_is_flat(self, strategy: Strategy) -> bool:
		"""True when NONE of ``strategy``'s tickers are held in any subscribed portfolio.

		A READ through the injected ``PortfolioReadModel``, which the queue-only rule permits —
		reads go through injected read-models; only writes are queue-mediated. Checks the
		strategy's tickers across its subscribed portfolios, so a pair's BOTH legs must be flat.

		With no read model injected there is nothing to observe: return True. Both composition
		roots pass the portfolio_handler, so that arm guards only directly-constructed handlers
		(the unit tests) — a defensive default, not a live degrade arm. A strategy with no
		subscribed portfolios is likewise vacuously flat.
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

		Only once flat: delete the rows (the store removes the portfolio-subscription CHILD rows
		BEFORE the ``strategy_registry`` parent — the FK forbids the reverse and the SQLite
		``PRAGMA foreign_keys=ON`` hook enforces it on both dialects), then drop the object from
		the MANAGED ROSTER and discard the name from ``_pending_removals``.

		⚠ THE STORE DELETE RUNS FIRST, AND THE ORDER IS LOAD-BEARING. It is the only operation
		here that can raise — the roster drop is membership-guarded and the pending discard is a
		``set.discard``, both non-raising. Doing the durable delete ahead of every in-memory
		mutation makes a store fault leave the strategy FULLY intact and STILL pending, so the
		next FILL retries the whole completion cleanly. The reverse order would strand the name in
		``_pending_removals`` with the object already gone from the roster: ``get_universe`` would
		keep filtering on a name nothing will ever discard, and ``on_fill`` would re-enter on a
		strategy ``by_name()`` can no longer resolve.
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

		The removal spans event cycles, so it is a PENDING state (like pending-bracket and
		reconnect-resume), not an inline mutation. On each FILL this re-scans EVERY pending
		removal's flatness via the injected ``PortfolioReadModel`` — a READ through an injected
		read-model, which the queue-only rule permits; ``PortfolioHandler`` is never imported —
		and completes the ones that reached flat. It re-scans ALL pending removals rather than
		keying on ``event.ticker``, so a multi-leg strategy completes on whichever fill flattens
		its LAST open leg.

		Wired on the LIVE FILL route only, AFTER ``PortfolioHandler.on_fill`` so the read model
		already reflects the settled (flat) position. It is NOT on the backtest FILL route at all.

		``pending_names()`` returns a snapshot: the loop discards entries as it completes them, so
		iterating the live set would raise.
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

		Deny ONLY the two closed sets (IMMUTABLE identity/derived, VERB-ONLY tickers) and let the
		existing ``_apply_params`` unknown-param rejection own the rest — a positive
		mutable-allowlist would be a second hand-maintained list that drifts from the class
		annotations. Called BEFORE the trial construction so a refused key never builds a
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
		"""Timeframe + capacity gate against the TRIAL — reason or None.

		Runs on the LIVE feed only (keyed on ``base_timeframe``, which the backtest feed lacks, so
		the whole arm skips cleanly — the same degrade the ``add`` gate uses).
		``required_base_depth`` raises ``UnwarmableTimeframeError`` for a finer-than-base timeframe
		(the ring holds base bars, and the off-grid guard would actively DROP sub-base bars even if
		they arrived) and for a non-multiple. The capacity gate then rejects a depth the ring can
		never serve: an existing ring is a ``deque(maxlen=...)`` fixed at creation and CANNOT
		resize, so a deeper consumer would leave the strategy ``is_ready`` False FOREVER —
		registered, silent, error-free, never trading. Ring RESIZE is deferred to
		.planning/todos/pending/strategy-timeframe-finer-than-base-resubscribe.md.

		Evaluating against the TRIAL's resolved ``warmup``/``timeframe`` covers BOTH a timeframe
		change AND a window-grow that would exceed capacity.
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
		``strategy.reconfigure`` is genuinely exceptional. The persist has ALREADY succeeded — the
		DB holds the NEW config and a restart rehydrates the intended configuration — so this does
		NOT roll back, it reports. The alert binds ``strategy_name`` and the error KIND ONLY, so
		no config value leaks to the operator channel. Queue-only egress (the handler has no
		alert_sink; this is how it raises an alarm mid-loop), consumed by the ERROR route.
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

		The atomicity contract. ``_apply_params`` is ALREADY atomic — its resolve-into-locals
		trial phase commits only after every field resolves, so a rejected apply raises before
		mutating ``self`` — and the single engine thread draining the queue ALREADY provides the
		quiesce, with no signal in flight between event cycles and so no lock or pause mechanism.
		The genuine tear is that ``Strategy.reconfigure`` calls ``validate()`` + ``_run_init()``
		AFTER that commit, so a cross-field ``validate()`` failure would leave a LIVE, trading
		strategy mutated into a state its own validator rejects. The fix is a THROWAWAY
		construction: ``cls(**params)`` runs the whole validate chain before the live instance is
		touched. No hand-rolled snapshot/rollback.

		Order: allowlist -> merge -> trial-validate -> direction re-gate -> warmability -> persist
		-> apply -> re-warm. Persist precedes apply so the DB and the live instance never diverge
		in the applied-but-unpersisted direction; apply-then-persist was rejected because a
		persist failure would silently lose the change on restart.
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
		# TRIAL-VALIDATE. Route the merged blob back through decode_strategy_config — the ONLY
		# function that knows the inverse coercions (Decimal via to_money, policies via
		# decode_policy, envelope-key stripping, `name` from the PK) — into PARAM space, then
		# construct a THROWAWAY. Routing the merge straight from blob space into the constructor
		# (param space) without this decode lands `entry_z` as the str '2'. The constructor runs
		# _apply_params + validate() + _run_init(), so a cross-field validation failure raises
		# HERE, against the throwaway, with the LIVE instance untouched.
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
			# Loud no-op naming the error KIND, never the payload values.
			# StrategyAdmissionError is the shared ancestor of every strategy-payload refusal
			# and needs no `ValueError` companion (it is declared `(ITraderError, ValueError)`,
			# and the residue is typed by the wrap in Strategy.__init__, which the throwaway
			# `cls(**params)` above runs). Still NARROW — never a bare except, so a store or
			# infra fault is not silently eaten.
			self.logger.warning(
				'reconfigure for strategy %s rejected (%s) — live instance untouched',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — the ZONE-1 guard, per the canonical statement in `_add_strategy_verb`:
			# `cls(**params)` reaches `Strategy.__init__` -> `_run_init()` -> `init()`, arbitrary
			# operator code outside the `StrategyValidationError` wrap, so the escaping-exception
			# set is unbounded and no type tuple suffices. THE GENERAL RULE, stated
			# verb-independently so the next verb inherits it: EVERY verb that invokes
			# `_run_init` on operator-supplied input carries a zone guard, and the guard's SHAPE
			# FOLLOWS ITS ZONE — zone 1 refuses as a loud no-op, zone 2 routes into the designed
			# CRITICAL path (the apply arm below).
			#
			# Scope is the exact `_add_strategy_verb` analog: that site's tier 2 wraps its single
			# `build_strategy` call, and `build_strategy` IS `decode_strategy_config` +
			# `cls(**params)` — the same two calls this `try` spans. Do not split the try;
			# isolating `cls(**params)` would make this guard NARROWER than the one it mirrors.
			# Neither call touches a store, and the arm sits BEFORE the `registry_store.upsert`
			# below, so returning here persists nothing and the live instance is unmutated.
			#
			# ERROR tier, mirroring the add site: an unexpected KIND means a defect in our path
			# rather than operator junk. exc_info carries the diagnostic; the message names
			# `type(exc).__name__` and nothing else, since an arbitrary init() message may quote
			# operator config.
			#
			# Owning these per-site guards in ONE shared admission seam is deferred to
			# .planning/todos/pending/shared-strategy-admission-seam.md.
			self.logger.error(
				'reconfigure for strategy %s failed with an UNEXPECTED error kind (%s) '
				'during the trial — live instance untouched and nothing persisted; this '
				'indicates a defect in the construction path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
			return
		# Direction re-gate. validate() does NOT check direction, and the gate reads HANDLER
		# state, so the trial construction CANNOT catch a short-enabling direction change.
		# Re-run the SHARED predicate against the TRIAL's resolved direction BEFORE persist: a
		# non-LONG_ONLY direction is admitted ONLY when both flags are on. Without this, an
		# external reconfigure(direction=SHORT_ONLY) on a no-margin engine would sail through
		# onto a live strategy. The predicate lives on the single ManagedStrategies owner,
		# which add_strategy also consults, so the two cannot drift.
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
		# would let the row drift from the live instance and silently revert unchanged fields
		# on restart. `enabled` is the LIVE strategy's current activation (a fresh trial is
		# is_active=True; reconfigure does not change activation). A persist FAILURE propagates
		# as infrastructure, but the LIVE instance is UNTOUCHED because persist precedes apply,
		# so the DB and live never diverge in the applied-but-unpersisted direction. Degrades
		# clean when registry_store is None.
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
			# ZONE 2 guard. The SAME unbounded hazard as the trial arm above (this `try`
			# reaches `Strategy.reconfigure` -> `_run_init()` -> `init()`), but a DIFFERENT
			# SHAPE, because the zone is different.
			#
			# 1. WHY IT ROUTES INSTEAD OF NO-OPING. This is POST-PERSIST, so a silent refusal
			#    would be a lie: the DB already holds the new config. The asymmetry is
			#    deliberate — `_emit_reconfigure_apply_failure` reports a CRITICAL ErrorEvent
			#    WITHOUT rolling back, and the invariant is "the DB holds the NEW config and a
			#    restart heals". Every exception class routes there with identical semantics,
			#    so a second narrow arm would be pure noise.
			# 2. WHY NEITHER EXTREME WORKS. Letting an arbitrary `init()` exception escape to
			#    halt() would BYPASS this design's own handling of exactly this case, and latch
			#    live trading. A blanket swallow would hide genuine zone-2 failures.
			# 3. FAIL-LOUD IS NOT WEAKENED, and the boundary is structural rather than
			#    conventional: this `try` body is the SINGLE `strategy.reconfigure(...)` call
			#    and contains no store call. `registry_store.upsert` sits OUTSIDE it, so a
			#    store/driver fault still propagates out of this verb unchanged. Do NOT move
			#    the upsert inside this `try`, and do not widen the body.
			self._emit_reconfigure_apply_failure(event, strategy, exc)
			return
		# NO force-flat. Open positions stay open and their subsequent exits are governed by
		# the NEW params — explicitly the operator's responsibility. Always-flatten (a harmless
		# sizing tweak would close positions) and param-classified flatten were both rejected.
		#
		# RE-WARM. `Strategy.reconfigure -> _run_init` UNCONDITIONALLY resets the per-symbol
		# handle state, so a handle-bearing instance is DARK after ANY applied reconfigure —
		# `is_ready` is False until it re-warms. (Preserving warmth would need a conditional
		# `_run_init` on the base HOT PATH, which is oracle risk, so it is deferred.)
		# `mark_unwarm` is idempotent here since `_run_init` already reset, and also covers the
		# PairStrategy override if a pair ever reached this path; `_request_rewarm` marks the
		# symbols FAILED so the retry re-warms them on the follow-on poll — the SAME warm path
		# `enable`/`add` use. During the dark re-warm the instance cannot emit STRATEGY-driven
		# exits, so an open position rides its resting exchange SL/TP brackets until warm: a
		# documented consequence, not a blocker.
		strategy.mark_unwarm()
		self._request_rewarm(strategy)
		self.global_queue.put(UniversePollEvent(time=event.time))

	def on_strategy_command(self, event: StrategyCommandEvent) -> None:
		"""Apply one control-plane verb to one strategy, live AND durably.

		The dispatch surface (live-only). Locates the strategy whose ``.name`` matches
		``event.strategy_name`` — the durable per-instance identity — and applies the verb
		IDEMPOTENTLY. The LIGHT verbs (no force-flat, no construction):

		- ``enable`` — ``is_active`` True + persist ``enabled=True``, then FORCE A RE-WARM (see
		  the enable branch below). It does NOT trade the next bar.
		- ``disable`` — ``is_active`` False + persist ``enabled=False``. The object STAYS in the
		  MANAGED ROSTER; open positions and resting brackets run to natural exit via the
		  execution layer, which never reads this flag. Stops NEW entries only. Across a restart
		  a disabled strategy is REHYDRATED present-but-dark, so it is re-enable-able and still
		  owns its positions rather than being dropped at boot with its positions orphaned.
		- ``subscribe_portfolio`` / ``unsubscribe_portfolio`` — the fan-out edge is
		  RUNTIME-MUTABLE. Mutates ``strategy.subscribed_portfolios`` live and upserts/deletes
		  the child row. Unsubscribing the LAST portfolio leaves an empty list and zero rows — a
		  LEGAL state (the strategy computes but fans out to nobody), not an error.
		- ``add_ticker`` / ``remove_ticker`` — the membership verbs, which also persist (a ticker
		  change IS a reconfigure of the ``tickers`` authoring param). ``remove_ticker`` refuses
		  a remove that would empty the list (the non-empty ``list[str]`` invariant).

		Idempotency: the ``mutated`` flag gates BOTH the persist and the follow-on — a no-op verb
		mutates nothing, persists nothing and emits nothing. An unknown ``strategy_name``, an
		unknown verb, or a malformed payload is a LOUD no-op: ``logger.warning`` + return, NEVER a
		raise into the queue.

		Concurrency: verbs are applied on the single engine thread that drains the queue, so a
		verb never interleaves with a signal mid-application — in the single-writer model that IS
		the quiesce.

		The follow-on ``UniversePollEvent`` is queue-only (one selection path, two triggers; the
		mutation happens-before the re-select). This NEVER calls ``UniverseHandler`` or touches
		``Universe.apply``.

		Parameters
		----------
		event: `StrategyCommandEvent`
			The control-plane command addressed to one strategy by name.
		"""
		# `add` targets a NEW name that is by design NOT yet in the roster, so it is
		# dispatched BEFORE the by-name lookup guard below — that guard would reject every
		# add as "unknown strategy". A pair `add` is likewise handled here: the verb-scoped
		# pair guard below governs only EXISTING pair instances, while `add` constructs a
		# fresh one that add_strategy's direction gate admits.
		if event.verb == "add":
			self._add_strategy_verb(event)
			return
		by_name = self._managed.by_name()
		strategy = by_name.get(event.strategy_name)
		if strategy is None:
			# Unknown target — loud no-op (no mutation, no follow-on).
			self.logger.warning(
				'StrategyCommandEvent for unknown strategy %s (verb=%s, symbol=%s) — ignored',
				event.strategy_name, event.verb, event.symbol)
			return
		# VERB-SCOPED pair guard. Pairs must add/remove/enable/disable/subscribe and
		# rehydrate as FULL registry instances, so a blanket refusal would silently gut pair
		# durability while LOOKING like a conservative safety measure — a refusal that is too
		# broad is as much a defect as one that is too narrow. Refuse EXACTLY
		# _PAIR_REFUSED_VERBS; accept the rest.
		#
		# Why `reconfigure` is refused for a pair. This is not conservatism; three sites
		# compose into stranded money:
		#   - `PairStrategy._entry` sets NO stop_loss/take_profit — unlike the single-leg
		#     `_intent` — so an OPEN SPREAD HAS NO RESTING EXCHANGE BRACKET and its ONLY exit
		#     is `evaluate_pair()`, which `_dispatch_pair` gates on `is_pair_ready()`;
		#   - `PairStrategy._run_init` unconditionally re-creates `_buf_A`/`_buf_B` and resets
		#     `_pair_bar_count` (β re-fits from scratch), and `reconfigure()` ALWAYS calls
		#     `_run_init()`;
		#   - `is_pair_ready()` needs `beta_warmup + z_lookback` bars (280 for the reference).
		# Net: reconfiguring a pair that holds an open spread strands an UNHEDGED,
		# BRACKET-LESS spread with NO REACHABLE EXIT for 280 bars — ~12 days on 1h, 280 days
		# on 1d. Do NOT re-litigate this without re-reading those three methods; see
		# .planning/todos/pending/pair-strategy-live-reconfiguration.md.
		#
		# The ticker verbs stay refused: a pair is bound to an EXACT-2-ticker contract
		# (`PairStrategy.validate` plus the `_dispatch_pair` len-2 guard), so mutating its
		# tickers would make EVERY subsequent BAR's `_dispatch_pair` raise — an unbounded
		# self-inflicted ErrorEvent storm with no recovery.
		if isinstance(strategy, PairStrategy) and event.verb in _PAIR_REFUSED_VERBS:
			self.logger.warning(
				'StrategyCommandEvent verb=%s refused for pair strategy %s — pairs '
				'accept the lifecycle verbs (D-16) but refuse reconfigure (D-17) and '
				'the ticker verbs (CR-01: the exact-2-ticker contract is immutable at '
				'the control-plane seam)',
				event.verb, event.strategy_name)
			return
		# `remove` — a heavy lifecycle verb (force-flat first, pending across event cycles).
		# It is NOT in _PAIR_REFUSED_VERBS, so a pair remove reaches here and force-flats
		# BOTH legs. It owns its persist, poll and pending-removal state, so it returns
		# before the light-verb `mutated` tail below.
		if event.verb == "remove":
			self._remove_strategy_verb(event, strategy)
			return
		# `reconfigure` — an authoring-param delta applied atomically (trial-validate ->
		# persist -> apply -> re-warm). It owns its own persist, poll and the
		# persist-then-apply asymmetry, so it returns before the light-verb `mutated` tail
		# below. A PairStrategy never reaches here — `reconfigure` is in
		# _PAIR_REFUSED_VERBS, so the verb-scoped pair guard above already refused it.
		if event.verb == "reconfigure":
			self._reconfigure_strategy_verb(event, strategy)
			return
		# Track whether the verb ACTUALLY mutated anything. Both the persist and the
		# follow-on are gated on this — an idempotent no-op (enable an enabled strategy, add
		# an already-present ticker, unsubscribe an unsubscribed id) mutates nothing,
		# persists nothing and emits nothing.
		mutated = False
		# A deferred (op, portfolio_id) child-table write, applied AFTER the parent upsert
		# below — the child row carries an FK to the registry row. The id travels as the
		# PortfolioId HANDLE, not `str(pid)`: the column is Uuid, so the DB enforces
		# well-formedness and a stringified id would raise StatementError at runtime.
		child_write: "Optional[tuple[str, PortfolioId]]" = None
		if event.verb == "enable":
			if not strategy.is_active:
				strategy.activate_strategy()
				# ⚠ THE LOAD-BEARING HALF OF `enable`. The is_active guard sits FIRST in on_bar,
				# so this strategy's indicators FROZE while it was disabled: their values were
				# computed over a window that now has an N-bar HOLE spanning the disabled
				# period. Trading the next bar would let SMA/MACD silently produce wrong values
				# across that discontinuity — invisible, because warmth is monotone and nothing
				# downstream re-checks. So force the strategy back to UNWARM: is_ready() then
				# gates emission until the recurrence has re-advanced over a CONTIGUOUS window.
				#
				# mark_unwarm is a named wrapper over the existing handle reset, NOT a flag —
				# warmth stays derived from is_ready — and PairStrategy overrides it to clear the
				# spread buffers too, since a handle-free pair is always is_ready==True and a
				# handles-only unwarm would let it re-enter on a cold β. `add` re-warms through
				# this SAME seam: one warm path, not two.
				strategy.mark_unwarm()
				self._request_rewarm(strategy)
				mutated = True
		elif event.verb == "disable":
			if strategy.is_active:
				# Deactivate only. Do NOT unwarm here — a disabled strategy's frozen state
				# is discarded by `enable`, and unwarming on the way DOWN would just as
				# happily discard state a re-enable never needs.
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
				# The sanctioned idempotent mutator — a duplicate would fan ONE decision
				# out to the same portfolio twice.
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
				# Removing the LAST portfolio leaves an empty list and zero child rows — a
				# legal state (the strategy computes but fans out to nobody). Deliberately
				# NOT guarded against.
				mutated = True
		elif event.verb in ("add_ticker", "remove_ticker"):
			# `symbol` is `str | None` and most verbs carry none, so the read lives HERE,
			# inside the only branches that have one.
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
						# Refuse: removing the last ticker would violate the non-empty
						# list[str] invariant. Documented no-op — no mutation, no persist,
						# no re-select.
						self.logger.warning(
							'remove_ticker %s refused for strategy %s — would empty its '
							'ticker set (non-empty invariant preserved)',
							symbol, event.strategy_name)
						return
					strategy.tickers.remove(symbol)  # idempotent removal
					mutated = True
		else:
			# Unknown verb — loud no-op.
			self.logger.warning(
				'StrategyCommandEvent unknown verb %s for strategy %s — ignored',
				event.verb, event.strategy_name)
			return
		if not mutated:
			return
		# EVERY mutating verb persists, parent row first.
		#
		# The subscribe/unsubscribe verbs are deliberately routed through the parent upsert
		# too, even though they only change the CHILD table. It looks redundant — the config
		# blob and `enabled` are unchanged — but strategy_portfolio_subscriptions carries an
		# FK to strategy_registry, so writing a child row for a strategy the registry has
		# never seen raises an IntegrityError straight into the queue, violating this
		# method's never-raise contract. Upserting the parent first is not a workaround for
		# the FK; it is what the FK is telling us: a durable subscription edge whose instance
		# is absent from the registry is an orphan rehydrate would silently drop at restart.
		# Persist the instance, then the edge.
		self._persist_strategy(strategy, event)
		if child_write is not None and self.registry_store is not None:
			operation, stored_portfolio_id = child_write
			if operation == "add":
				self.registry_store.add_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
			else:
				self.registry_store.remove_portfolio_subscription(
					strategy_name=strategy.name, portfolio_id=stored_portfolio_id)
		# Follow-on: mutate happens-before re-select. Queue-only cross-domain write —
		# never call UniverseHandler.
		if event.verb in _POLL_FOLLOW_ON_VERBS:
			self.global_queue.put(UniversePollEvent(time=event.time))
