import copy
from abc import ABC, abstractmethod
from decimal import Decimal
from datetime import timedelta
from enum import Enum
from functools import cache
from typing import Any, cast, get_type_hints

import pandas as pd

from itrader.core.enums import OrderType, Side, Timeframe
from itrader.core.exceptions.strategy import UnknownParamError, MissingParamError
from itrader.core.ids import PortfolioId, StrategyId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, SizingPolicy, SLTPPolicy, TradingDirection
from itrader.outils.time_parser import to_timedelta
from itrader import idgen

# D-03/D-05 (amended): the IndicatorHandle and the typed adapter Protocol live in
# the first-party indicators/ subsystem (NOT here) — base imports them, the
# dependency is one-directional base -> indicators (no cycle; handle.py never
# imports base.py).
from .indicators import IndicatorAdapter, IndicatorHandle

# D-07: sentinel distinguishing a bare (required) annotation — a class attr
# with NO value — from a class attr whose default happens to be None.
_MISSING = object()

# WR-04: JSON-native types the to_dict() introspection loop may emit as-is.
# Anything else (Decimal/datetime/custom object) is coerced to repr() at the
# serialization edge so json.dumps(strategy.to_dict()) never raises.
def _is_json_native(val: Any) -> bool:
	# `bool` is a subclass of `int`, so it is already covered; `None` is JSON
	# null. NOTE: list/dict are intentionally NOT treated as unconditionally
	# native here — a container is only JSON-safe if its CONTENTS are native
	# too (a `list[Decimal]` / `dict[str, datetime]` would otherwise still break
	# `json.dumps`). The recursive `_json_safe` walk below is the structural
	# guarantee; this scalar predicate only classifies leaves.
	return val is None or isinstance(val, (str, int, float))


def _json_safe(val: Any) -> Any:
	# WR-01 (iter-2): the WR-04 fix only repr-coerced a SCALAR non-native value,
	# but classified a top-level `list`/`dict` as native by container type alone.
	# A declared attr holding e.g. `list[Decimal]` / `dict[str, datetime]`
	# therefore slipped through and `json.dumps(to_dict())` still raised. Make the
	# coercion RECURSIVE: a list/dict is native only if every element/value is
	# native; otherwise repr-coerce the offending leaves. This makes the
	# `json.dumps(strategy.to_dict())` contract structural, not type-list-based.
	if _is_json_native(val):
		return val
	if isinstance(val, list):
		return [_json_safe(x) for x in val]
	if isinstance(val, tuple):
		# tuples serialize to JSON arrays — preserve the JSON-array shape.
		return [_json_safe(x) for x in val]
	if isinstance(val, dict):
		return {str(k): _json_safe(x) for k, x in val.items()}
	return repr(val)


# D-05 (PERF-04): memoize get_type_hints per concrete Strategy subclass. The
# declared-attr annotations are CONSTANT per class (fixed at import), yet to_dict
# (hot — per signal snapshot) re-walked the MRO and re-resolved them on every
# call. `type(self)` keys the cache on the concrete subclass so each class
# resolves exactly once; functools.cache is thread-safe (locks internally) for
# live mode, and no manual invalidation is needed (the strategy-class count is
# bounded and annotations never change after import). Resolution is memoized,
# NOT removed: neither call site uses the resolved TYPES (both only iterate keys
# and enum coercion is driven by _COERCE), but a names-only MRO walk would risk
# snapshot key-ordering in this byte-exact phase, so removal is deferred. Both
# sites only iterate keys (never mutate / .pop), so the shared cached dict is
# read-only-safe (T-04-04).
@cache
def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:
	return get_type_hints(cls)

# D-08: ONLY these three engine fields coerce a str off their annotation to an
# enum (via the enum's case-insensitive _missing_). Every other knob is left as
# supplied — e.g. short_window="50" stays a str, never silently int()-ed.
_COERCE: dict[str, type[Enum]] = {
	"timeframe": Timeframe,
	"direction": TradingDirection,
}

class Strategy(ABC):
	"""
	Strategy is the pure-alpha abstract base for all strategies (D-12).

	A concrete strategy is a pure function of market data: it implements
	``generate_signal(ticker, bars) -> SignalIntent | None`` and DECLARES
	its sizing policy, trading direction, and admission settings as CLASS
	ATTRIBUTES (D-02/D-06); the base introspects its own + the subclass's
	annotations and applies ``**kwargs`` over them, coercing the three enum
	fields and rejecting unknown/missing-required loudly (D-06/D-07/D-08).
	It never touches the events queue, never stamps time or price, and never
	knows anything portfolio-shaped — ``StrategiesHandler`` owns stamping,
	policy attachment, per-portfolio fan-out, and enqueueing (the #24 boundary).
	"""

	# Base-owned engine-facing names. A BARE annotation (no value) marks a
	# REQUIRED param (D-07): timeframe / tickers / sizing_policy must be either
	# pinned by a subclass class-attr or passed as a kwarg, else MissingParamError.
	# Pitfall 1: the kwarg arrives as a "1d" str / Timeframe enum (coerced by
	# _COERCE), but the RESOLVED runtime value on self.timeframe is a timedelta
	# (consumed by check_timeframe / min_timeframe and SMA's
	# `last_time - self.timeframe * self.short_window`). The annotation reflects
	# the resolved consumer type; the bare annotation (no value) still marks it
	# REQUIRED for get_type_hints-driven detection (D-07).
	# EVERY engine-facing knob is ANNOTATED — `_apply_params` iterates
	# `_declared_hints(type(self))` (memoized get_type_hints, D-05), which
	# returns ONLY annotated names, so an
	# unannotated class attr would be invisible to the engine (un-overridable by
	# kwarg, and its enum coercion would never fire). The three bare annotations
	# (no value) are REQUIRED (D-07); the rest carry defaults.
	timeframe: timedelta          # required — no class-attr value
	tickers: list[str]            # required
	sizing_policy: SizingPolicy   # required
	# D-01: the per-instance ``order_type`` class attr is RETIRED. With the
	# explicit buy_limit/buy_stop/sell_limit/sell_stop factories every call
	# states its own type, so a strategy-wide default is never read; the type
	# now lives per-intent on ``SignalIntent.order_type``.
	direction: TradingDirection = TradingDirection.LONG_ONLY
	allow_increase: bool = False
	max_positions: int = 1
	sltp_policy: SLTPPolicy | None = None
	max_window: int = 0
	warmup: int = 0
	name: str = "strategy"        # D-03 discretion: default name (a subclass pins it)

	def __init__(self, **kwargs: Any) -> None:
		# WR-01: portfolio-id handle is opaque (PortfolioId | int) — the
		# fan-out never resolves a portfolio object here, so both shapes are
		# legal. Mint a fresh UUIDv7 strategy_id per construction (KEEP).
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.is_active = True
		self.subscribed_portfolios: list[PortfolioId | int] = []
		# D-06/D-07/D-08: required/unknown detection + enum coercion + setattr.
		self._apply_params(**kwargs)
		# D-09: cross-field validation hook (no-op by default).
		self.validate()
		# D-03/D-08: register declared indicators (init() calls self.indicator())
		# then auto-derive warmup/max_window from the registered handles.
		self._run_init()

	def _apply_params(self, **kwargs: Any) -> None:
		"""Apply ``**kwargs`` over the declared class-attr surface (D-06/D-07/D-08).

		``_declared_hints(type(self))`` (memoized ``get_type_hints``, D-05)
		merges the full MRO so the base-owned
		names and the subclass's params are introspected together. For each
		declared name, resolution order is: the kwarg if present, else the prior
		INSTANCE value on a reconfigure (RESEARCH Open Question 1 — a partial
		reconfigure keeps the prior value), else the class-attr default; a bare
		annotation with no default and no prior value (``_MISSING``) is a
		required param and raises ``MissingParamError``. The three ``_COERCE``
		enum fields coerce a str off their annotation (the enum's ``_missing_``);
		any leftover kwarg is an unknown param and raises ``UnknownParamError``
		(loud rejection, no silent drop — T-02-01/T-02-02/T-02-04).
		"""
		# Record whether the caller supplied a `timeframe` kwarg BEFORE the loop
		# pops it (RESEARCH Open Question 1 — the reconfigure fallback order).
		timeframe_supplied = "timeframe" in kwargs
		# Has _apply_params run before? (reconfigure path — fall back to instance)
		reconfiguring = hasattr(self, "_timeframe")
		hints = _declared_hints(type(self))
		# WR-02: resolve + coerce + validate the FULL kwarg set into a local dict
		# FIRST, committing to `self` only after every check (resolution,
		# coercion, unknown/missing, malformed-tickers) passes. Previously each
		# value was setattr'd inside the loop, so a coercion failure or the
		# post-loop tickers guard left the instance partially mutated on a
		# rejected reconfigure. Mutating `kwargs` (pop) only affects the local
		# copy below, never `self`, so resolution stays side-effect-free until
		# the commit phase.
		remaining = dict(kwargs)
		resolved: dict[str, Any] = {}
		for nm in hints:
			default = getattr(type(self), nm, _MISSING)
			if nm in remaining:
				val = remaining.pop(nm)
			elif nm == "timeframe" and reconfiguring:
				# self.timeframe is a timedelta after the first pass — fall back
				# to the stashed ENUM so the prior timeframe is preserved.
				val = self._timeframe
			elif nm != "timeframe" and reconfiguring and hasattr(self, nm):
				# Reconfigure: a required field with a prior instance value keeps
				# it (no MissingParamError on an omitted-but-already-set field).
				val = getattr(self, nm)
			elif default is not _MISSING:
				# WR-01/IN-01: copy mutable class-attr defaults so a declared
				# default is not ALIASED across every instance constructed without
				# that kwarg (the classic mutable-default bug, re-expressed through
				# class attributes — `a.tickers.append(...)` would otherwise leak
				# into `b.tickers`). IN-01: the guard is now mutability-based, not a
				# `list`/`dict`/`set` whitelist — any default that is NOT a known
				# immutable scalar (str/int/float/bool/None/Enum) is deep-copied, so
				# a declared default of a deque / numpy array / custom mutable object
				# is alias-safe too. Deep-copying an effectively-immutable declared
				# policy (FractionOfCash, etc.) yields an equal fresh copy — harmless.
				val = (
					default
					if default is None or isinstance(default, (str, int, float, bool, Enum))
					else copy.deepcopy(default)
				)
			else:
				raise MissingParamError(nm)
			coerce = _COERCE.get(nm)
			if coerce is not None and not isinstance(val, coerce):
				val = coerce(val)  # enum _missing_ (str -> enum); raises on bogus
			resolved[nm] = val
		if remaining:
			raise UnknownParamError(sorted(remaining))
		# IN-02: reject a malformed-but-present `tickers`. A bare `str` is
		# iterable char-by-char, so `for ticker in strategy.tickers` would
		# silently request windows for "B", "T", … (producing nothing) rather
		# than failing loudly; an empty list trades nothing. Extend the engine's
		# "reject loudly" philosophy from unknown/missing to malformed values.
		# Checked against the RESOLVED value (WR-02) so it covers both the kwarg
		# and class-attr-default paths and fires BEFORE any commit to self.
		tickers = resolved.get("tickers", _MISSING)
		if tickers is not _MISSING:
			if isinstance(tickers, str) or not isinstance(tickers, list) \
					or not tickers or not all(isinstance(t, str) for t in tickers):
				raise ValueError(
					"tickers must be a non-empty list[str] (a bare str is rejected)"
				)
		# WR-02 commit phase: every check above passed — now mutate self. A
		# rejected reconfigure raised before reaching this line, leaving prior
		# instance state intact.
		for nm, val in resolved.items():
			setattr(self, nm, val)
		# Pitfall 1 (the #1 oracle trap): self.timeframe is consumed as a
		# TIMEDELTA by check_timeframe / min_timeframe and SMA's
		# `last_time - self.timeframe * self.short_window`. The coerced
		# Timeframe enum was just setattr'd onto self.timeframe by the loop —
		# stash it on a stable instance attr, then resolve BOTH the timedelta
		# and the serialization alias on EVERY pass. On a reconfigure with no
		# `timeframe` kwarg the loop already restored the enum from the class
		# default; per RESEARCH Open Question 1 we re-read the INSTANCE enum
		# stashed below (not the class attr) so a partial reconfigure keeps the
		# prior timeframe.
		if timeframe_supplied:
			# A `timeframe` kwarg arrived: the loop placed the coerced Timeframe
			# enum on self.timeframe (the annotation says timedelta, but at this
			# point the value is still the enum) — stash it as the instance enum.
			self._timeframe: Timeframe = cast(Timeframe, self.timeframe)
		else:
			# Reconfigure with no timeframe kwarg: fall back to the prior
			# INSTANCE enum (not the class attr), keeping the prior timeframe.
			# On first construction with no kwarg, the loop applied the class
			# default (a Timeframe enum or a required miss already raised).
			self._timeframe = getattr(self, "_timeframe", cast(Timeframe, self.timeframe))
		self.timeframe_alias: str = self._timeframe.value
		# Resolve the enum to the timedelta the engine consumers read.
		self.timeframe = to_timedelta(self._timeframe.value)

	def validate(self) -> None:
		"""Overridable cross-field validation hook (D-09).

		Run after ``_apply_params`` (kwargs applied + enums coerced) on every
		construction and reconfigure. No-op by default; ``SMAMACDStrategy``
		expresses ``short_window < long_window`` through it.
		"""
		...

	def init(self) -> None:
		"""Overridable idempotent lifecycle hook (D-10/D-11).

		Called at the end of construction and on every ``reconfigure``. No-op by
		default; calling it twice leaves identical state. A concrete strategy
		registers its declared indicators here via ``self.indicator(...)``.
		"""
		...

	def indicator(
		self, adapter: IndicatorAdapter, input_col: str, *params: int
	) -> IndicatorHandle:
		"""Register a declared indicator and return its handle (D-03).

		Mirrors the ``backtesting.py`` ``self.I()`` shape: constructs an
		``IndicatorHandle`` over the typed ``adapter`` (imported from the
		``indicators`` package), appends it to ``self._handles``, and returns the
		handle so the author binds it to a named attr
		(``self.short_sma = self.indicator(SMA, "close", self.short_window)``).
		The base re-populates the SAME handle each tick in ``evaluate``; the
		auto-warmup post-pass derives ``warmup``/``max_window`` from
		``handle.min_period()`` (D-08).
		"""
		handle = IndicatorHandle(adapter, input_col, tuple(params))
		self._handles.append(handle)
		return handle

	def _run_init(self) -> None:
		"""Reset handles, run ``init()``, then auto-derive warmup (D-08/D-10).

		Resetting ``self._handles`` BEFORE ``self.init()`` keeps a re-run
		idempotent (calling init() twice leaves identical state — D-10).

		The post-``init()`` pass auto-derives BOTH thresholds from the declared
		handles' ``min_period``:

		- ``warmup`` is UNCONDITIONALLY overwritten to ``max(min_period, default=0)``
		  — this is the WR-03 footgun fix (D-08): an author can no longer hand-set
		  ``warmup`` too LOW and under-gate the handler short-circuit. The reference
		  ends at ``warmup == 100`` (``max(SMA50->50, SMA100->100, MACDHist->15)``);
		  a zero-handle strategy ends at ``warmup == 0`` (no gating, as before).

		- ``max_window`` is the FETCH WIDTH the handler requests from the feed
		  (``feed.window(..., max_window, ...)``), NOT a gating threshold. It is
		  ``max(handle-derived, hand-set class value)`` so a zero-handle COUNT/DATE
		  -keyed fixture (SingleMarketBuy/ScriptedEmitter/BuyEachTickerOnce) keeps
		  the wide window its logic needs (a 0-width window is always empty against
		  a REAL feed — ``frame.iloc[pos:pos]`` — which would break its firing and
		  the e2e/integration golden). For the reference the hand-set value is
		  deleted (class default 0), so ``max_window == 100`` (handle-derived). The
		  assertion ``warmup == max_window == 100`` therefore still holds.

		Called from both ``__init__`` and ``reconfigure``.
		"""
		self._handles: list[IndicatorHandle] = []
		self.init()
		derived = max((h.min_period() for h in self._handles), default=0)
		self.warmup = derived
		# Fetch width: never shrink below a hand-set class value (preserve the
		# fixtures' wide window; the reference's deleted hand-set is 0 -> derived).
		self.max_window = max(derived, type(self).max_window)

	def evaluate(self, ticker: str, window: pd.DataFrame) -> SignalIntent | None:
		"""Orchestration seam: stash the window, repopulate handles, dispatch (D-06).

		IN-03: ``evaluate`` is NOT re-entrant. It mutates shared instance state
		(``self.bars``/``self.now`` and the registered handles) before dispatch,
		so a single ``Strategy`` instance must be evaluated by one writer at a time
		(the single-writer contract — the backtest loop is synchronous and live
		mode processes on one daemon thread). Concurrent/re-entrant evaluation of
		the same instance would race on this shared mutable state.

		The handler calls this (NOT ``generate_signal`` directly). It stashes the
		pushed completed-bar window on ``self.bars`` and the decision anchor on
		``self.now`` (``window.index[-1]`` — Pitfall 4, the SAME anchor the legacy
		``last_time`` used, so the SMA ``start_dt`` arithmetic is unchanged), then
		re-populates every registered handle BEFORE dispatching to
		``generate_signal``. For an indicator-free strategy ``self._handles`` is
		empty so the repopulate loop is a no-op (Pitfall 6 — no AttributeError).

		Empty-window guard: a zero-warmup strategy can be dispatched with an empty
		window (``feed.window`` returns ``frame.iloc[pos:pos]`` when max_window is
		small and the cutoff is at the frame start). ``window.index[-1]`` would
		raise ``IndexError`` on a size-0 frame, so when the window is empty we
		leave ``self.now`` as ``None`` and skip the repopulate loop — the strategy
		still runs (count/date fixtures guard on ``self.bars.empty`` / ``len``).
		"""
		# IN-06: cheap debug-build re-entrancy guard. The single-writer contract
		# above is enforced only by prose; in a perf milestone where parallel
		# strategy evaluation is a plausible future optimization, a second writer
		# would silently race on the per-tick snapshot (self.bars/self.now/the
		# handles). Set a flag around the body and assert it is clear on entry so
		# a future re-entrant/concurrent call on the SAME instance trips LOUDLY
		# instead of corrupting the snapshot. The `assert` compiles out under
		# `python -O`, and on the synchronous single-writer oracle/live path the
		# flag is always clear on entry — so this is a pure no-op there.
		assert not getattr(self, "_evaluating", False), (
			"Strategy.evaluate is not re-entrant — a second writer raced on the "
			"per-tick snapshot (IN-06 single-writer contract)."
		)
		self._evaluating = True
		try:
			self.bars: pd.DataFrame = window
			self.now = window.index[-1] if len(window) else None
			if self.now is not None:
				for handle in self._handles:
					handle.repopulate(self.bars, self.now, self.timeframe)
			return self.generate_signal(ticker)
		finally:
			self._evaluating = False

	def reconfigure(self, **kwargs: Any) -> None:
		"""Re-apply + re-coerce kwargs, re-validate, re-run init() (D-12/D-13).

		Single-strategy-scope reconfiguration replacing the dropped frozen-config
		mutation guard. No ``__setattr__`` guard exists (D-13) — sanctioned
		reconfiguration goes through here so validate() + init() always re-run.

		WR-04 — asymmetric fallback (RESEARCH Open Question 1): a field OMITTED
		from ``kwargs`` keeps its PRIOR INSTANCE VALUE, NOT the class default.
		Omission is therefore NOT a reset: there is no way through an omitted
		kwarg to clear an optional field back to its class default. To reset a
		field you MUST pass it explicitly (e.g. ``reconfigure(sltp_policy=None)``
		restores ``None``); a caller who expects "omitted == default" will be
		surprised. Only an explicitly-supplied kwarg overrides the prior value.
		"""
		self._apply_params(**kwargs)
		self.validate()
		# D-08/D-10: re-register handles + re-derive warmup (idempotent).
		self._run_init()

	def to_dict(self) -> dict[str, Any]:
		# WR-02: a faithful "params snapshot" (SIG-02 queryability) must capture
		# the FULL declared surface — timeframe / tickers / max_window / warmup
		# AND every subclass tuning knob (short_window, long_window, …) — not a
		# hand-listed subset. Introspect _declared_hints(type(self)) (memoized
		# get_type_hints, D-05) so the
		# snapshot can interpret a signal (which timeframe, which tickers, which
		# windows). The identity/runtime fields below (strategy_id,
		# strategy_name, is_active, subscribed_portfolios) and the bespoke
		# serializations (enum .value, policy repr, timeframe_alias instead of
		# the timedelta) take precedence over the raw declared value.
		snapshot: dict[str, Any] = {}
		for nm in _declared_hints(type(self)):
			# `timeframe` resolves to a timedelta at runtime — skip it here and
			# serialize via the stable `timeframe_alias` below (the str the
			# snapshot can round-trip). `name` is surfaced as `strategy_name`.
			if nm in ("timeframe", "name"):
				continue
			val = getattr(self, nm, None)
			if isinstance(val, Enum):
				val = val.value
			elif isinstance(val, (SizingPolicy, SLTPPolicy)):
				val = repr(val)
			else:
				# WR-04 / WR-01 (iter-2): the introspection loop is the whole point
				# of to_dict (capture the FULL declared surface), but it must honour
				# the documented `json.dumps(strategy.to_dict())` contract (IN-03). A
				# declared attr whose value is e.g. a Decimal / datetime / custom
				# object — OR a list/dict CONTAINING such non-native leaves — is not
				# JSON-safe. `_json_safe` recursively walks containers and repr-
				# coerces non-native leaves at the serialization edge (mirroring how
				# the bespoke policy fields are handled), so the snapshot stays
				# round-trippable structurally, not by top-level container type.
				val = _json_safe(val)
			snapshot[nm] = val
		# Identity/runtime fields + bespoke serializations (override declared).
		snapshot.update({
			# IN-03: stringify the UUID — to_dict is a serialization-edge dict,
			# and a raw uuid.UUID makes json.dumps(strategy.to_dict()) raise
			# "Object of type UUID is not JSON serializable". order_type /
			# direction are already .value-serialized; align strategy_id.
			"strategy_id" : str(self.strategy_id),
			"strategy_name": self.name,
			# WR-02: the timeframe is a timedelta on self — serialize the stashed
			# alias so the snapshot records WHICH timeframe (the #1 missing knob).
			"timeframe_alias" : self.timeframe_alias,
			# WR-01: subscribed_portfolios holds runtime PortfolioId handles that
			# are uuid.UUID on every real run path (PortfolioHandler.add_portfolio
			# returns a UUID). A raw UUID makes json.dumps(strategy.to_dict())
			# raise "Object of type UUID is not JSON serializable" — the same
			# defect class IN-03 closed for strategy_id. Stringify at the
			# serialization edge; str() is safe for both int and UUID handles
			# (str(1) == "1", str(uuid) == "019e...").
			"subscribed_portfolios" : [str(pid) for pid in self.subscribed_portfolios],
			# D-01: the per-instance order_type attr is retired — order type is now
			# per-intent on SignalIntent, so to_dict no longer emits an "order_type".
			"is_active" : self.is_active,
			# Typed declarations serialized in place of the dead settings dict.
			"sizing_policy" : repr(self.sizing_policy),
			"direction" : self.direction.value,
			"allow_increase" : self.allow_increase,
			"max_positions" : self.max_positions,
			# WR-06: the SLTP declaration is now a first-class typed kwarg, so it
			# serializes alongside the other declarations (None when undeclared).
			"sltp_policy" : repr(self.sltp_policy) if self.sltp_policy is not None else None,
		})
		return snapshot

	def __str__(self) -> str:
		# D-14: generalize the per-strategy shape (was f'{self.name}_{self.timeframe}'
		# on SMA_MACD) onto the base. Pitfall 5: read the stashed serialization
		# alias (self.timeframe is now a timedelta), NOT self.config (deleted).
		return f'{self.name}_{self.timeframe_alias}'

	def __repr__(self) -> str:
		return str(self)

	@abstractmethod
	def generate_signal(self, ticker: str) -> SignalIntent | None:
		"""
		Evaluate market data for ``ticker`` and return a trading intent.

		The pure-alpha contract (D-06/D-12, M5-06): the ``bars`` param is dropped
		— ``evaluate`` has already stashed the pushed completed-bar window on
		``self.bars`` (and ``self.now`` = ``window.index[-1]``) and re-populated
		every declared indicator handle. A concrete strategy reads its handles
		(``self.short_sma[-1]``) and ``self.bars``, and returns a ``SignalIntent``
		(typically via the ``buy()`` / ``sell()`` sugar) or ``None`` when there is
		nothing to do. No queue, no event construction, no portfolio knowledge.
		"""
		raise NotImplementedError("Should implement generate_signal()")

	def _intent(self, ticker: str, action: Side, order_type: OrderType,
			entry_price: float | Decimal | None,
			sl: float | Decimal | None,
			tp: float | Decimal | None,
			exit_fraction: Decimal) -> SignalIntent:
		"""
		Shared factory (D-01) folding the sl/tp/exit_fraction/entry_price
		logic across all six buy/sell sugar methods.

		``sl``/``tp``/``entry_price`` enter the Decimal domain via ``to_money``
		(the D-04 string path) — NEVER ``Decimal(float)``; ``None`` means
		"not declared" (sl/tp) or "MARKET, fills at close" (entry_price).
		"""
		return SignalIntent(
			ticker=ticker,
			action=action,
			order_type=order_type,
			entry_price=to_money(entry_price) if entry_price is not None else None,
			stop_loss=to_money(sl) if sl is not None else None,
			take_profit=to_money(tp) if tp is not None else None,
			exit_fraction=exit_fraction,
		)

	def buy(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Thin sugar returning a MARKET BUY ``SignalIntent`` for ``ticker``.

		Byte-exact (D-01): no ``price`` param, ``order_type=MARKET`` and
		``entry_price=None`` (fills at the decision-bar close). Optional
		``sl``/``tp`` enter the Decimal domain via ``to_money`` (the D-04
		string path); ``None`` means "not declared".
		"""
		return self._intent(ticker, Side.BUY, OrderType.MARKET,
			None, sl, tp, exit_fraction)

	def sell(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Thin sugar returning a MARKET SELL ``SignalIntent`` for ``ticker``.

		Byte-exact (D-01): no ``price`` param, ``order_type=MARKET`` and
		``entry_price=None`` (fills at the decision-bar close). Optional
		``sl``/``tp`` enter the Decimal domain via ``to_money`` (the D-04
		string path); ``None`` means "not declared".
		"""
		return self._intent(ticker, Side.SELL, OrderType.MARKET,
			None, sl, tp, exit_fraction)

	def buy_limit(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Sugar returning a LIMIT BUY ``SignalIntent`` (D-01/SIG-01).

		``price`` is required and keyword-only — illegal ``(order_type, price)``
		combos are unrepresentable by construction (D-04). The limit entry price
		enters the Decimal domain via ``to_money`` (never ``Decimal(float)``).
		"""
		return self._intent(ticker, Side.BUY, OrderType.LIMIT,
			price, sl, tp, exit_fraction)

	def buy_stop(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Sugar returning a STOP BUY ``SignalIntent`` (D-01/SIG-01).

		``price`` is required and keyword-only — illegal ``(order_type, price)``
		combos are unrepresentable by construction (D-04). The stop entry price
		enters the Decimal domain via ``to_money`` (never ``Decimal(float)``).
		"""
		return self._intent(ticker, Side.BUY, OrderType.STOP,
			price, sl, tp, exit_fraction)

	def sell_limit(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Sugar returning a LIMIT SELL ``SignalIntent`` (D-01/SIG-01).

		``price`` is required and keyword-only — illegal ``(order_type, price)``
		combos are unrepresentable by construction (D-04). The limit entry price
		enters the Decimal domain via ``to_money`` (never ``Decimal(float)``).
		"""
		return self._intent(ticker, Side.SELL, OrderType.LIMIT,
			price, sl, tp, exit_fraction)

	def sell_stop(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Sugar returning a STOP SELL ``SignalIntent`` (D-01/SIG-01).

		``price`` is required and keyword-only — illegal ``(order_type, price)``
		combos are unrepresentable by construction (D-04). The stop entry price
		enters the Decimal domain via ``to_money`` (never ``Decimal(float)``).
		"""
		return self._intent(ticker, Side.SELL, OrderType.STOP,
			price, sl, tp, exit_fraction)

	def subscribe_portfolio(self, portfolio_id: PortfolioId | int) -> None:
		# WR-01: idempotent subscribe — a duplicate subscription would fan the
		# same intent out to one portfolio TWICE in calculate_signals (two
		# SignalEvents, two orders for one decision). Guard the append.
		if portfolio_id not in self.subscribed_portfolios:
			self.subscribed_portfolios.append(portfolio_id)

	def unsubscribe_portfolio(self, portfolio_id: PortfolioId | int) -> None:
		# WR-01: idempotent unsubscribe — list.remove raises ValueError on a
		# double-unsubscribe / never-subscribed id (a noisy ErrorEvent in live
		# mode). Guard so a defensive caller can unsubscribe safely.
		if portfolio_id in self.subscribed_portfolios:
			self.subscribed_portfolios.remove(portfolio_id)

	def activate_strategy(self) -> None:
		self.is_active = True

	def deactivate_strategy(self) -> None:
		self.is_active = False
