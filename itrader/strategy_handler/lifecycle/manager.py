"""
Strategy control-plane collaborator (DECOMP-01/DECOMP-02).

`StrategyLifecycleManager` owns the entire STRATEGY_COMMAND control plane MOVED
VERBATIM (TAB) from `strategies_handler.py` — pure code motion, behaviour-preserving:
the two public entry points `on_strategy_command` / `on_fill` relocated INTACT, the
ten verb/helper privates they reach, and the four module-level verb constants only
those bodies read. `StrategiesHandler.on_strategy_command` / `on_fill` become 1-line
delegations, so the handler's public surface and external ctor stay byte-equal and
`route_registrar.py` needs no edit.

Every import is at MODULE TOP (DECOMP-02). The five formerly function-local blocks
(`registry.config_codec`, `registry.catalog`, `registry.rehydrate`, `core.policy_codec`,
`price_handler.feed.cache_registration`) are hoisted here. Their old "a module-top
import would pull SQL onto the BACKTEST import graph and break GATE-01" rationale was
re-tested in a clean interpreter during 10.1-03 and is FALSE: importing all five leaks
ZERO sqlalchemy / psycopg2 / alembic and leaves the config `sql` cached_property
unresolved. This module is therefore on the backtest import graph by design (the
handler constructs it unconditionally), and `test_okx_inertness.py` now asserts the
real invariant — SQL-absence — positively rather than by a hardcoded name list.

Injected dep subset (constructor injection, all real at construction since 10.1-01):
`managed` (the single `ManagedStrategies` roster owner), `global_queue`, `feed`,
`registry_store`, `strategy_catalog`, `portfolio_read_model`, `logger`.

⚠ DEVIATION from the order-domain analog, stated rather than copied: `LifecycleManager`
(order_handler) declares "NO queue access (D-06/D-18)". This manager DOES hold
`global_queue` — the moved bodies emit `UniversePollEvent` (the D-10/D-11 warmup and
force-close wiring) and a CRITICAL `ErrorEvent` (the D-13 apply-fail egress) directly.
That egress IS the collaborator's contract, not a layering leak: it is queue-only, so
`UniverseHandler` / `Universe` are never called and `PortfolioHandler` is never imported.

⚠ NEGATIVE INVARIANT — ZERO roster state. This class owns NO `strategies` list and NO
`_pending_removals` set. Every roster and pending-removal access routes through
`self._managed`. Giving this manager its OWN pending set is the silent-corruption trap
the extraction exists to avoid: `ManagedStrategies.get_universe` reads ITS set to exclude
a pending strategy's tickers, so a second set here would leave membership never
re-deriving, the D-11 force-close poll never firing, and `remove` hanging forever with
NO error raised. One source of truth: `ManagedStrategies`.

It holds NO handler back-reference (unchanged from the analog).

⚠ SECURITY (T-10.1-01/T-10-18). `strategy_type` arrives as an untrusted string on an
external STRATEGY_COMMAND payload. `_add_strategy_verb` and `_reconfigure_strategy_verb`
resolve it through the injected `strategy_catalog` by CLOSED DICT LOOKUP and nothing
else, and LOUD-reject when the catalog is None. There is deliberately no `importlib`,
no `__import__`, no `getattr`-on-module and no default catalog anywhere on those paths:
resolving a type by name would convert the operator API into remote code execution.

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
	# TYPE_CHECKING-guarded (D-01): the live-only Universe seam is never imported
	# at runtime, so no runtime import cost is added. The annotation stays a
	# string ("Universe | None"). This is NOT a function-local import — it is a
	# module-level import under a guard the interpreter never executes, which is
	# what DECOMP-02's "zero function-local imports" invariant actually targets.
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
# Hardcoded (NOT imported from config_codec) so the deny-list stays a self-contained closed
# set at the control-plane seam; the authoritative derived set is
# config_codec._DERIVED_FIELDS == frozenset({"warmup", "max_window"}) and this MUST track it.
_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type", "name", "warmup", "max_window"})

# D-15: `tickers` is owned by add_ticker/remove_ticker — one path per concern.
_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})


class StrategyLifecycleManager:
	"""The STRATEGY_COMMAND control plane (DECOMP-01).

	Owns `on_strategy_command` / `on_fill` (the two route-facing entry points
	StrategiesHandler delegates into) plus the ten verb/helper privates, moved
	verbatim from the handler. See the module docstring for the queue-access
	deviation from the order-domain analog, the ZERO-roster-state invariant, and
	the closed-dict-lookup security contract.

	The three live deps all accept `None` as their legal backtest/in-memory state,
	and every persist arm short-circuits on it. `registry_store` and
	`strategy_catalog` additionally keep `Optional[Any]` VALUES so the SQL stack
	stays off this module's annotations. `portfolio_read_model` is the EXCEPTION
	(WR-04): `core/portfolio_read_model.py` pulls no SQL — only stdlib plus
	`core.enums` and `core.ids`, both already on this module's import graph — so
	naming the real protocol costs nothing in inertness and buys a genuine
	`mypy --strict` check of the `get_position` call in `_strategy_is_flat`. The
	erased `Any` there was silently suppressing exactly that check. The manager
	is the SINGLE OWNER of all three — the handler exposes read-through properties
	over these attributes rather than keeping its own copies, so a
	post-construction assignment on the handler can never desync the two (T-10.1-03).

	The logger is bound FRESH here with `component="StrategyLifecycleManager"`
	rather than reusing the handler's bind: no test asserts on the `component`
	field, and a distinct tag makes the control plane's log lines attributable to
	the collaborator that now owns them.
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
			The events queue. Queue-only egress: UniversePollEvent (D-10/D-11)
			and the D-13 CRITICAL ErrorEvent.
		feed: `BarFeed`
			The look-ahead-safe market-data read model (D-20). Read for its
			`base_timeframe` / `cache_capacity` on the F-1 warmability gates.
		registry_store: `StrategyRegistryStore | None`
			D-09 durable instance registry. ``None`` is the BACKTEST / in-memory
			path — every persist arm is then a clean no-op.
		strategy_catalog: `StrategyCatalog | None`
			D-10 access-control ALLOWLIST the `add` / `reconfigure` verbs resolve
			an untrusted external ``strategy_type`` through. ``None`` LOUD-rejects.
		portfolio_read_model: `PortfolioReadModel | None`
			D-11 flat-detect read-model consulted on FILL. A READ through an
			injected read-model, NOT a cross-domain handler call.
		logger: `ITraderStructLogger`
			The handler's logger, re-bound to this component. Concretely typed
			(WR-03) so ``mypy --strict`` checks this module's ~23 logger call
			sites rather than erasing them behind ``Any``.
		"""
		self._managed = managed
		self.global_queue: "EventBus" = global_queue
		self.feed: BarFeed = feed
		self.registry_store: "Optional[Any]" = registry_store
		self.strategy_catalog: "Optional[Any]" = strategy_catalog
		self.portfolio_read_model: "Optional[PortfolioReadModel]" = portfolio_read_model
		self.logger = logger.bind(component="StrategyLifecycleManager")
		# WR-02 (D-01) live-only readiness seam, wired ONLY via set_universe.
		# `_request_rewarm` is the sole reader (mark_failed) and it lives here.
		self._universe: "Universe | None" = None

	@property
	def universe(self) -> "Universe | None":
		"""The WR-02 (D-01) universe handle — THIS object, never a copy (IN2-03).

		The public same-object read seam the handler's ``_universe`` property
		forwards to, so no caller has to reach across into this object's private
		attribute (the pattern IN-01 closed for ``pending_removals``). Read-only
		by design: ``set_universe`` below stays the SOLE write path, so widening
		the read surface cannot widen the write surface.
		"""
		return self._universe

	def set_universe(self, universe: "Universe") -> None:
		"""Wire the dynamic universe so ``_request_rewarm`` can mark symbols FAILED (D-01).

		Forwarded unconditionally from ``StrategiesHandler.set_universe``, which
		keeps its own reference for the per-tick readiness gate in
		``on_bar``. Two references to ONE object is the intended shape.
		"""
		self._universe = universe

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

		DECOMP-02: the codec import is now at MODULE TOP. The former lazy-import
		rationale ("would pull SQL onto the BACKTEST import graph and break GATE-01
		inertness") was re-tested in a clean interpreter during 10.1-03 and is false —
		``registry/`` reaches the store only through an INJECTED handle, never an import.
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
	) -> "Optional[PortfolioId]":
		"""Parse ``config["portfolio_id"]`` into the handle the fan-out expects, or None.

		The payload is operator/FastAPI-supplied and therefore untrusted (T-10-35): the
		light verbs read ONLY this one key, and it is validated + PARSED here so a
		malformed payload never reaches live strategy state or SQL. A miss returns None
		and the caller makes it a loud no-op — this path must never raise into the queue.

		⚠ The parse is a CORRECTNESS requirement, not a typing nit — the same defect
		10-05 hit on the rehydrate arm. ``subscribed_portfolios`` is typed
		``list[PortfolioId]``, and ``on_bar`` fans each intent out over
		it and puts each id STRAIGHT onto ``SignalEvent.portfolio_id`` (FL-02: "the
		runtime value is always a UUIDv7-backed PortfolioId"). A bare ``str`` reaches
		the portfolio lookup as an id matching NOTHING: the subscription would look
		perfectly healthy and then fan signals into the void. Value-equality assertions
		pass while the type is wrong, so this is pinned by a TYPE assertion.

		Mirrors ``registry/rehydrate.py::_resolve_portfolio_id`` (parse the one legal
		UUID shape) but returns None instead of raising: rehydrate quarantines a bad
		instance at boot, whereas a bad runtime command is a loud no-op.
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
		"""WR2-01 — the presence probe that makes ABSENT and MALFORMED distinguishable.

		``_portfolio_id_from`` deliberately collapses FOUR outcomes into one ``None``:
		config-not-a-dict, key absent, value of the wrong type, unparseable UUID. That
		collapse is RIGHT for the two light verbs (``subscribe_portfolio`` /
		``unsubscribe_portfolio`` warn on every ``None`` — the operator asked for a
		subscription and did not get one, whatever the cause) and WRONG for ``add``,
		where absence is a LEGAL state (D-09: register now, wire the portfolio later)
		but malformation is operator error. ``add`` needs to tell the two apart; this
		is the one probe that does it.

		The ``"portfolio_id"`` key name and the ``isinstance(config, dict)`` guard live
		HERE, adjacent to ``_portfolio_id_from``, rather than at the call site: the call
		site re-reading ``event.config`` would duplicate the payload parsing this pair
		centralizes and let the probe and the parser drift apart.

		An explicit ``None`` VALUE counts as NOT supplied. A FastAPI/Pydantic model
		declaring ``portfolio_id: str | None = None`` serializes the unsubscribed case as
		a null on EVERY add, so a bare key-PRESENCE probe would reject the most likely
		shape of the legal no-subscription payload. Every OTHER value — non-``str``,
		empty ``str``, non-UUID ``str`` — is supplied-and-malformed.
		"""
		config = event.config
		if not isinstance(config, dict):
			return False
		return config.get("portfolio_id") is not None

	def _add_strategy_verb(self, event: StrategyCommandEvent) -> None:
		"""D-10 `add`: catalog-gate -> construct DARK -> persist -> warm via the P7 poll.

		The phase's highest-value trust boundary (T-10-41): an operator/FastAPI-supplied
		``strategy_type`` + config becomes a live Python object. Every rejection below is a
		LOUD no-op (a log + return) that registers and persists NOTHING — a half-built
		strategy never enters the roster. That contract holds for ANY construction failure,
		not merely the enumerated validation kinds: ``init()`` is arbitrary user-authored
		strategy code, so the zone-1 guard below is two-tier (CR-01).

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
		# DECOMP-01: reads the SINGLE roster owner — this manager holds no roster of its own.
		if any(existing.name == event.strategy_name for existing in self._managed.strategies):
			self.logger.warning(
				'add for strategy %s refused — a strategy with that name is already '
				'registered (D-02); the existing instance is left untouched',
				event.strategy_name)
			return

		# WR2-01 — a SUPPLIED but unparseable portfolio_id rejects the WHOLE add.
		#
		# Reject-without-registering is this method's established idiom, not a new policy:
		# the D-10 catalog gate, the D-02 duplicate gate and the SHORT-01 arm all refuse the
		# command outright rather than half-apply it. Without this arm the malformed id fell
		# into the ABSENT branch below and the add proceeded SILENTLY, leaving a registered,
		# persisted, warming strategy with zero subscriptions — and on_bar fans each intent
		# over subscribed_portfolios, so an empty list means literally zero SignalEvents
		# forever. A healthy-looking engine that trades nothing is worse than a loud refusal.
		#
		# ABSENT stays a clean legal no-op (D-09): the operator may add a strategy
		# unsubscribed and wire it later with subscribe_portfolio. Only supplied-and-
		# unparseable is refused — `_portfolio_id_supplied` is what separates the two.
		#
		# The identical payload sent as subscribe_portfolio ALREADY warns, so the diagnosis
		# must not depend on which verb the operator happened to use.
		#
		# PLACEMENT is load-bearing. This is a pure payload check with no dependency on the
		# constructed object, so it belongs AHEAD of every state mutation: rejecting down at
		# the old parse site would have to UNDO a completed `_managed.add_strategy` roster
		# insert. It also sits deliberately OUTSIDE the CR-01 two-tier zone-1 guard, which
		# stays scoped to the single `build_strategy` call (see its own point 3) — this arm
		# raises nothing, so it needs no guard.
		portfolio_id = self._portfolio_id_from(event)
		if portfolio_id is None and self._portfolio_id_supplied(event):
			# Names the KIND/condition only — never echoes the payload value (the P8
			# declared-fields-only precedent the tier-1 arm below follows).
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
		# into both. build_strategy is the IDENTICAL path rehydrate uses (D-01).
		blob = {key: value for key, value in config.items() if key != "portfolio_id"}
		rec = {
			"strategy_name": event.strategy_name,
			"strategy_type": strategy_type,
			"config_json": blob,
		}
		try:
			strategy = build_strategy(rec, catalog=self.strategy_catalog)
		except StrategyAdmissionError as exc:
			# Tier 1 — EXPECTED validation kinds, i.e. "the operator sent junk". A loud
			# no-op naming the error KIND (not the payload values — the P8
			# declared-fields-only precedent). StrategyAdmissionError is the shared
			# ancestor of every strategy-payload refusal (unknown strategy_type,
			# undeserializable blob, param drift either direction) — one name instead of
			# a hand-listed tuple that can drift out of sync with its siblings, which is
			# what caused CR-01.
			#
			# IN2-02 — the bare `ValueError` member is GONE. It was fully SUBSUMED by the
			# first member (StrategyAdmissionError is declared `(ITraderError, ValueError)`),
			# so the tuple read as a two-name catch while behaving as a one-name one. The
			# residue it was there for — validate() and the _apply_params tickers/enum
			# guards raising BARE ValueError — is now TYPED as StrategyValidationError by
			# the wrap in Strategy.__init__ / Strategy.reconfigure, so the ancestor alone
			# covers it. A third-party validate() override outside our hierarchy is covered
			# too: the wrap converts at the RAISE boundary rather than requiring the class
			# to opt in.
			self.logger.warning(
				'add for strategy %s rejected (%s) — nothing registered or persisted',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — CR-01. Any OTHER construction failure is STILL a loud no-op.
			#
			# 1. CR-01 / D-10. STRATEGY_COMMAND is externally admitted
			#    (LiveTradingSystem.add_event), so an escape from here does not merely
			#    fail one command: it reaches ErrorPolicy.record_failure -> the
			#    failure-rate tripwire -> halt(), and HALTED has NO legal exit except an
			#    operator reset_halt(). Routine bad operator input must never be able to
			#    latch live trading into HALT.
			# 2. Why no finite tuple suffices. build_strategy -> cls(**params) ->
			#    _apply_params -> validate() -> _run_init() -> self.init(), and init() is
			#    ARBITRARY USER-AUTHORED strategy code from my_strategies/. The set of
			#    exceptions escaping construction is unbounded BY CONSTRUCTION; enumerating
			#    more types fixes the instance, never the class. (TypeError needs no
			#    separate decision — this arm subsumes it.)
			# 3. Why this does NOT violate the "never a bare except" doctrine. That
			#    doctrine governs ZONE 2 — register / persist / emit (add_strategy,
			#    _persist_strategy, add_portfolio_subscription, global_queue.put) — where a
			#    store or driver fault MUST stay loud so D-19 fail-loud holds. This guard
			#    covers ZONE 1 ONLY: untrusted payload -> live object, exactly the one
			#    build_strategy call above, which contains no store call. Do not widen it
			#    past that boundary, and do not "simplify" it back to a type tuple.
			# 4. Why the ERROR tier is separate. An unexpected type means a bug in OUR
			#    construction path, not operator junk, so it must be visibly distinct
			#    rather than laundered into the same warning. exc_info carries the
			#    diagnostic; the message itself names no payload values (tier-1 rule).
			self.logger.error(
				'add for strategy %s failed with an UNEXPECTED error kind (%s) — nothing '
				'registered or persisted; this indicates a defect in the construction '
				'path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
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
		# Register through add_strategy (its SHORT-01/D-07 direction gate).
		# D-02 duplicate is already pre-checked, so the only remaining
		# raise is the SHORT-01 system-config mismatch — convert THAT to a loud no-op so an
		# operator add never raises into the queue.
		try:
			self._managed.add_strategy(strategy)
		except ValueError as exc:
			self.logger.warning(
				'add for strategy %s rejected — %s (a non-LONG_ONLY strategy needs the '
				'handler short-enabled, SHORT-01/D-07)', event.strategy_name, exc)
			return
		# Subscribe the portfolio_id carried alongside the config. It was parsed +
		# type-checked at the boundary by the WR2-01 gate ABOVE (T-10-35; a bare str would
		# fan signals at a portfolio matching nothing) and the handle is reused here — the
		# parse does NOT happen at this site. Reaching here with None therefore means
		# ABSENT, never malformed: the strategy computes but fans out to nobody (a legal
		# state, D-09), and the subscribe_portfolio verb can wire it later.
		if portfolio_id is not None:
			strategy.subscribe_portfolio(portfolio_id)
		# Persist parent-first (the child FK requires the registry row to exist first).
		self._persist_strategy(strategy, event)
		if portfolio_id is not None and self.registry_store is not None:
			# B2 (11-03): the column is Uuid now — pass the PortfolioId handle straight
			# through. A str() here would bind a str to a Uuid column and raise
			# StatementError at RUNTIME while mypy stayed green.
			self.registry_store.add_portfolio_subscription(
				strategy_name=strategy.name, portfolio_id=portfolio_id)
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
		the MANAGED ROSTER and its ROW is KEPT (persisted ``enabled=False``) until flat: a
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
		if self._managed.is_pending(strategy.name):
			return
		# Deactivate FIRST — the D-07 `is_active` gate stops NEW entries while the
		# force-close plays out (this is why D-07 is a Plan 03 dependency).
		if strategy.is_active:
			strategy.deactivate_strategy()
		# Enter the pending state BEFORE emitting the poll, so get_strategies_universe
		# already excludes this strategy when the poll re-derives membership.
		self._managed.mark_pending(strategy.name)
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

		Only once flat: delete the rows (the store removes the portfolio-subscription CHILD
		rows BEFORE the ``strategy_registry`` parent — P-6; the FK forbids the reverse and
		the SQLite ``PRAGMA foreign_keys=ON`` hook enforces it on both dialects), then drop
		the object from the MANAGED ROSTER and discard the name from ``_pending_removals``.

		⚠ THE STORE DELETE RUNS FIRST, AND THE ORDER IS LOAD-BEARING. It is the only
		operation here that can raise — the roster drop is membership-guarded and the
		pending discard is a ``set.discard``, both non-raising. Doing the durable delete
		ahead of every in-memory mutation makes a store fault leave the strategy FULLY
		intact and STILL pending, so the next FILL retries the whole completion cleanly.
		The reverse order would strand the name in ``_pending_removals`` with the object
		already gone from the roster: ``get_universe`` would keep filtering on a name
		nothing will ever discard, and ``on_fill`` would re-enter on a strategy
		``by_name()`` can no longer resolve.
		"""
		if not self._strategy_is_flat(strategy):
			return
		if self.registry_store is not None:
			# Child-then-parent delete (P-6) — the store owns the FK ordering.
			self.registry_store.delete(strategy.name)
		self._managed.remove(strategy)
		self._managed.discard_pending(strategy.name)

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

		DECOMP-01: both pending-set reads route through the SINGLE ``ManagedStrategies``
		owner. ``pending_names()`` reproduces the original body's ``list(...)`` snapshot —
		the loop discards entries as it completes them, so iterating the live set would
		raise. This manager owns NO pending set of its own (module docstring).
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

		DECOMP-02: ``ErrorSeverity`` and ``ErrorEvent`` are now imported at MODULE TOP.
		Neither NAME was at ``strategies_handler.py``'s module top before the move (line 5
		imported only ``OrderType``; the events block imported five names, not ``ErrorEvent``),
		so these are genuine ADDS — deleting the lazy block without adding them would raise
		``NameError`` on this path.
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
		except StrategyAdmissionError as exc:
			# Loud no-op naming the error KIND (not the payload values — the P8
			# declared-fields-only precedent). StrategyAdmissionError is the shared ancestor
			# of every strategy-payload refusal.
			#
			# IN2-02 — the bare `ValueError` member is GONE (it entirely SUBSUMED the first
			# member, since StrategyAdmissionError is declared `(ITraderError, ValueError)`).
			# The residue it existed for is now TYPED as StrategyValidationError by the wrap
			# in Strategy.__init__, which is what the throwaway `cls(**params)` above runs —
			# including a third-party validate() override, since the wrap converts at the
			# raise boundary. Still NARROW — never a bare except, so a store/infra fault is
			# not silently eaten.
			self.logger.warning(
				'reconfigure for strategy %s rejected (%s) — live instance untouched',
				event.strategy_name, type(exc).__name__)
			return
		except Exception as exc:
			# Tier 2 — s6b. ZONE 1 fallback: any OTHER trial failure is STILL a loud no-op.
			#
			# 1. WHY A ZONE GUARD AND NOT A TYPE TUPLE. `cls(**params)` above reaches
			#    `Strategy.__init__` -> `_run_init()` -> `init()`, and `init()` is ARBITRARY
			#    operator-supplied code from my_strategies/. `_run_init` sits deliberately
			#    OUTSIDE the `StrategyValidationError` wrap in `Strategy.__init__` (see its
			#    own point 3), so the set of exceptions escaping it is UNBOUNDED BY
			#    CONSTRUCTION and enumerating types fixes the INSTANCE, never the CLASS. The
			#    pre-`ra5` `(StrategyAdmissionError, ValueError)` tuple caught exactly ONE
			#    arbitrary member of that infinite set while TypeError / KeyError /
			#    AttributeError always escaped — it LOOKED like coverage and was a
			#    coincidence. `ra5` did not create this hole; it removed the accident that
			#    concealed it. Do not "simplify" this arm back to a type tuple.
			# 2. THE GENERAL RULE, stated verb-independently so the next verb inherits it:
			#    EVERY D-10 verb that invokes `_run_init` on operator-supplied input carries
			#    a zone guard, and the guard's SHAPE FOLLOWS ITS ZONE — zone 1 refuses as a
			#    loud no-op, zone 2 routes into the designed CRITICAL path (see the apply
			#    arm below). The km2/CR-01 principle is a property of what `init()` IS, not
			#    of which verb it was first noticed in; it landed on `_add_strategy_verb`
			#    only because CR-01 happened to point there. D-10 makes the stakes concrete:
			#    STRATEGY_COMMAND is externally admitted, so an escape reaches
			#    ErrorPolicy.record_failure -> the failure-rate tripwire -> halt(), and
			#    HALTED has NO legal exit except an operator reset_halt(). Routine bad
			#    operator input must never latch live trading into HALT.
			# 3. WHY THIS DOES NOT VIOLATE THE NEVER-A-BARE-EXCEPT DOCTRINE. That doctrine
			#    governs ZONE 2 — the store/persist/emit calls, where an infrastructure
			#    fault MUST stay loud so D-19 holds. This arm covers ZONE 1 ONLY: untrusted
			#    payload -> THROWAWAY object. Neither call in its `try` (decode_strategy_config,
			#    cls(**params)) touches a store, and the arm sits BEFORE the
			#    `registry_store.upsert` below, so returning here persists nothing and the
			#    live instance is unmutated. Do not widen it past that boundary.
			# 4. SCOPE IS THE EXACT `_add_strategy_verb` ANALOG. That site's tier-2 wraps its
			#    single `build_strategy` call — and `build_strategy` is ITSELF
			#    `decode_strategy_config` + `cls(**params)`, the same two calls this `try`
			#    already spans. So no try-splitting is wanted: isolating `cls(**params)`
			#    would make this guard NARROWER than the one it mirrors.
			# 5. ERROR tier, mirroring the add site: an unexpected KIND means a defect in our
			#    path rather than operator junk, so it must be visibly distinct from tier-1's
			#    WARNING. exc_info carries the diagnostic; the message names `type(exc).__name__`
			#    and NOTHING else — no payload values (the P8 declared-fields-only precedent
			#    tier-1 follows), since an arbitrary init() message may quote operator config.
			#
			# Owning these per-site guards in ONE shared admission seam is deferred to
			# .planning/todos/pending/shared-strategy-admission-seam.md (candidate after Phase 11).
			self.logger.error(
				'reconfigure for strategy %s failed with an UNEXPECTED error kind (%s) '
				'during the trial — live instance untouched and nothing persisted; this '
				'indicates a defect in the construction path rather than a bad payload',
				event.strategy_name, type(exc).__name__, exc_info=True)
			return
		# SHORT-01/D-07 direction re-gate (audit 10-08 F1 — the phase's most dangerous fix).
		# validate() does NOT check direction, and the SHORT-01 gate reads HANDLER state, so
		# the trial construction CANNOT catch a short-enabling direction change. Re-run the
		# SHARED predicate against the TRIAL's resolved direction BEFORE persist: a
		# non-LONG_ONLY direction is admitted ONLY when both flags are on. Without this, an
		# external reconfigure(direction=SHORT_ONLY) on a no-margin engine would sail through
		# onto a live strategy — the exact capability SHORT-01 exists to gate (T-10-55).
		# DECOMP-01: the SHARED predicate now lives on the single ManagedStrategies owner,
		# which is also what add_strategy consults — so the two still cannot drift.
		if not self._managed.direction_admissible(trial.direction):
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
		except Exception as exc:
			# s6b — ZONE 2 guard. The SAME unbounded hazard as the trial arm above (this
			# `try` reaches `Strategy.reconfigure` -> `_run_init()` -> `init()`, arbitrary
			# operator code outside the `StrategyValidationError` wrap), but a DIFFERENT
			# SHAPE, because the zone is different. See the trial arm for the full
			# why-a-zone-guard-not-a-type-tuple reasoning and the verb-independent rule.
			#
			# 1. WHY IT ROUTES INSTEAD OF NO-OPING. This is POST-PERSIST, so a silent
			#    refusal would be a lie: the DB already holds the new config. The D-13
			#    asymmetry is deliberate and PRESERVED — `_emit_reconfigure_apply_failure`
			#    reports (CRITICAL ErrorEvent) WITHOUT rolling back, and the invariant is
			#    "the DB holds the NEW config and a restart heals". Both exception classes
			#    route to it with identical semantics, so there is no second narrow arm:
			#    one with a byte-identical body would be pure noise. `exc` is already
			#    annotated `Exception` there, so widening needs no signature change.
			# 2. WHY NEITHER EXTREME WORKS. Letting an arbitrary `init()` exception escape
			#    to halt() would BYPASS this design's own handling of exactly this case (and
			#    latch live trading, D-10). A blanket swallow would hide genuine zone-2
			#    failures that D-19 wants loud.
			# 3. D-19 IS NOT WEAKENED, and the boundary is structural, not conventional:
			#    this `try` body is the SINGLE `strategy.reconfigure(...)` call and contains
			#    no store call. `registry_store.upsert` sits OUTSIDE it (above), so a
			#    store/driver fault still propagates out of this verb unchanged. Do NOT move
			#    the upsert inside this `try`, and do not widen the body.
			#
			# (Pre-s6b this arm read `except StrategyAdmissionError` — narrow for the same
			# IN2-02 reason as the trial arm, with the residue typed by the wrap in
			# `Strategy.reconfigure` rather than `Strategy.__init__`. It also omitted
			# UnknownStrategyTypeError, defensibly, since apply resolves no class. The
			# ancestor remains SUBSUMED here, so admission refusals keep the identical
			# emit shape they had.)
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
		  in the MANAGED ROSTER; open positions and resting brackets run to natural exit
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
		by_name = self._managed.by_name()
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
		# B2 (11-03): the id travels as the PortfolioId HANDLE, not `str(pid)` — the
		# column is Uuid now, so the DB enforces well-formedness and a stringified id
		# would raise StatementError at runtime.
		child_write: "Optional[tuple[str, PortfolioId]]" = None
		if event.verb == "enable":
			if not strategy.is_active:
				strategy.activate_strategy()
				# ⚠ WD-1 — the load-bearing half of `enable`. The D-07 guard sits FIRST
				# in on_bar, so this strategy's indicators FROZE while it was
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
