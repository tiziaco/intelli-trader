import copy
from abc import ABC, abstractmethod
from collections import deque
from decimal import Decimal
from datetime import timedelta, datetime
from enum import Enum
from functools import cache
from typing import Any, cast, get_type_hints

import pandas as pd

from itrader.core.enums import OrderType, Side, Timeframe
from itrader.core.exceptions.strategy import (
	StrategyAdmissionError,
	StrategyValidationError,
	UnknownParamError,
	MissingParamError,
)
from itrader.core.ids import PortfolioId, StrategyId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, SizingPolicy, SLTPPolicy, TradingDirection
from itrader.outils.time_parser import to_timedelta
from itrader.logger import get_itrader_logger
from itrader import idgen

# Module-level bound logger (mirrors SMA_MACD_strategy.py) — the base Strategy has no
# per-instance self.logger, so the CR-01-strategy out-of-order-bar warning in update()
# uses this shared component logger.
logger = get_itrader_logger().bind(component="Strategy")

# D-03/D-05 (amended): the IndicatorHandle and the typed adapter Protocol live in
# the first-party indicators/ subsystem (NOT here) — base imports them, the
# dependency is one-directional base -> indicators (no cycle; handle.py never
# imports base.py).
from .indicators import IndicatorAdapter, IndicatorHandle

# D-07: sentinel distinguishing a bare (required) annotation — a class attr
# with NO value — from a class attr whose default happens to be None.
_MISSING = object()


class _RowBar:
	"""Bar-shaped adapter over a pandas (row, timestamp) for the legacy ``evaluate``.

	P5-D13: the per-tick run path drives ``update(ticker, bar)`` with real ``Bar``
	objects. The legacy window-driven ``evaluate`` (test/back-compat only) replays a
	pandas frame row-by-row, so it wraps each ``(row, ts)`` in this shim exposing the
	two attributes ``update`` reads — the declared ``input_col`` (e.g. ``close``) and
	``time`` (the row's index timestamp). It is NOT used on the run path.
	"""

	__slots__ = ("_row", "time")

	def __init__(self, row: "pd.Series[Any]", ts: Any) -> None:
		self._row = row
		self.time = ts

	def __getattr__(self, name: str) -> Any:
		# Column access by attribute (e.g. bar.close -> row["close"]). __getattr__
		# fires only for names not in __slots__, so ``time`` is served directly.
		# IN-01: a typo'd declared ``input_col`` (e.g. "clse") would otherwise
		# raise a bare pandas KeyError far from the declaration site. Re-raise
		# naming the column and that it is the declared input_col.
		try:
			return self._row[name]
		except KeyError as exc:
			raise KeyError(
				f"_RowBar: column {name!r} not found in the replayed row — "
				f"check the strategy's declared input_col"
			) from exc

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


# WR-01 (260626-dnq): per-call isolating copy for the to_dict static-snapshot
# cache, replacing copy.deepcopy at the serve site (~5% W1 hot-path). The cached
# snapshot's value domain is normalized by _json_safe to scalars (str/int/float/
# bool/None — immutable) plus plain list/dict containers; there are NO custom
# mutable leaf objects. A recursive structural copy over ONLY list/dict (returning
# scalars unchanged, since immutables need no copy) therefore reproduces deepcopy's
# per-call isolation at ANY nesting depth, byte-identically (same types/values),
# without deepcopy's memo dict / introspection / immutable-copying overhead.
# `type(...) is list/dict` (identity, matching the to_money fast-path style) keeps
# the walk tight and conservative against container subclasses.
def _isolating_copy(val: Any) -> Any:
	if type(val) is list:
		return [_isolating_copy(x) for x in val]
	if type(val) is dict:
		return {k: _isolating_copy(v) for k, v in val.items()}
	return val


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
# CACHE-CLASS: (c) pure-function memo — see docs/CACHE-CLASSIFICATION.md
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
	# (consumed by check_timeframe and SMA's
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
		# WR-04: the portfolio-id handle carries exactly ONE shape, the
		# UUIDv7-backed PortfolioId (the FL-02 invariant). The handle feeds
		# PortfolioReadModel.get_position and the on_bar fan-out's
		# SignalEvent.portfolio_id, both of which require a real PortfolioId.
		# Mint a fresh UUIDv7 strategy_id per construction (KEEP).
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.is_active = True
		self.subscribed_portfolios: list[PortfolioId] = []
		# D-06 (PERF-04 / 08-03 Req 4): per-INSTANCE cache of the serialized STATIC
		# portion of to_dict (the _declared_hints introspection + _json_safe walk +
		# the bespoke set-once serializations). None until the first to_dict call
		# builds it lazily (avoids __init__-ordering fragility — the declared params
		# are committed by _apply_params just below). PER-INSTANCE, never per-class:
		# a per-class cache would leak one instance's declared windows
		# (short_window=10 vs 20) into another (a correctness bug). Invalidated by
		# _invalidate_to_dict_cache (called by reconfigure, the only declared-param
		# mutator). Never invalidated in backtest (no reconfigure on the run path).
		# CACHE-CLASS: (c) explicitly-invalidated memo (via _invalidate_to_dict_cache) — see docs/CACHE-CLASSIFICATION.md
		self._to_dict_static_cache: dict[str, Any] | None = None
		# WR2-02 / IN2-02 — TYPE the bare-``ValueError`` residue escaping this span.
		#
		# 1. WHY. Four collaborators inside this span raise a BARE ``ValueError``:
		#    ``Strategy.validate``, any subclass override of it (``SMAMACDStrategy.validate``,
		#    ``PairStrategy.validate``, and third-party overrides outside our hierarchy),
		#    ``_apply_params``'s malformed-``tickers`` guard, and its ``_COERCE`` enum
		#    coercion off a bogus enum string. Untyped, that residue sat OUTSIDE
		#    ``StrategyAdmissionError`` and therefore outside
		#    ``registry.rehydrate._QUARANTINABLE``, so ONE stale registry row whose class
		#    had gained a cross-field rule aborted the whole live boot instead of being
		#    quarantined — a bad ROW becoming a bad SYSTEM. Converting at the raise
		#    boundary (rather than asking every strategy class to opt into our hierarchy)
		#    is what lets ``_QUARANTINABLE`` stay narrow.
		# 2. CLAUSE ORDER IS LOAD-BEARING — do not reorder, and do not collapse the two
		#    clauses into one with an ``isinstance`` test. ``StrategyAdmissionError``
		#    already subclasses ``ValueError``, so a lone ``ValueError`` clause would also
		#    claim ``UnknownParamError`` / ``MissingParamError`` / ``StrategyConfigError`` /
		#    ``UnknownStrategyTypeError``. Re-raising those as ``StrategyValidationError``
		#    would DESTROY the ``ValidationError`` structured fields (``field`` /
		#    ``message`` / ``.names``) that the ``ljn`` task deliberately preserved,
		#    degrading every rejection diagnostic. The guard clause below claims them first
		#    and re-raises them completely untouched.
		# 3. ``_run_init`` / ``init()`` are deliberately OUTSIDE this span — ``init()`` is
		#    arbitrary user-authored strategy code, and
		#    ``StrategyLifecycleManager._add_strategy_verb``'s tier-2 guard already owns
		#    that zone.
		# 4. ACCEPTED TRADE, stated plainly: this reclassifies a genuine PROGRAMMING BUG
		#    inside a strategy's ``validate()`` (say a typo'd comparison) as an admission
		#    failure rather than a crash. That is the SAME trade
		#    ``_add_strategy_verb``'s tier-2 catch-all already accepted at the add site,
		#    so it is consistent with the established boundary rather than a new concession.
		try:
			# D-06/D-07/D-08: required/unknown detection + enum coercion + setattr.
			self._apply_params(**kwargs)
			# D-09: cross-field validation hook (no-op by default).
			self.validate()
		except StrategyAdmissionError:
			raise
		except ValueError as exc:
			raise StrategyValidationError(str(exc)) from exc
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
		# TIMEDELTA by check_timeframe and SMA's
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

		P5-D20 causal guard: a non-causal adapter (``adapter.causal is False``) is
		REJECTED here at the decision-path / registration boundary — raised
		EXPLICITLY (not an ``assert``, which is stripped under ``-O``/PYTHONOPTIMIZE)
		so a future statistical/ML adapter that peeks the future can never silently
		enter the look-ahead-safe decision path. All v1 adapters declare
		``causal = True``.

		P5-D21: the author surface is UNCHANGED — only the per-symbol fan-out spec is
		recorded alongside (``self._handle_specs``) so the framework can auto-fan-out
		one stateful handle-set per symbol (P5-D10), lazily on the ticker's first bar.
		"""
		# P5-D20: reject a non-causal adapter at the registration boundary.
		if not getattr(adapter, "causal", False):
			raise RuntimeError(
				f"non-causal adapter {type(adapter).__name__!r} rejected at "
				f"registration (P5-D20 causal guard): the decision path admits "
				f"only causal indicators (all v1 adapters declare causal=True)."
			)
		params_tuple = tuple(params)
		handle = IndicatorHandle(adapter, input_col, params_tuple)
		self._handles.append(handle)
		# P5-D10: record the recipe so per-symbol handle-sets can be minted lazily.
		self._handle_specs.append((adapter, input_col, params_tuple))
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
		# P5-D10: the per-symbol fan-out spec (the declared recipes) + the lazy
		# per-ticker handle-set map. Reset BEFORE init() so a re-run is idempotent
		# (D-10). The author declares once via self.indicator(...); the framework
		# auto-fans-out one stateful handle-set per symbol on that symbol's FIRST
		# bar (P5-D10a), with independent per-symbol readiness (P5-D10b).
		self._handle_specs: list[tuple[IndicatorAdapter, str, tuple[int, ...]]] = []
		# P5-D10/D14 per-symbol fan-out via state-swap on the SINGLE registration
		# handle-set. The author binds self.short_sma etc. to the registration
		# handles (self._handles, returned by self.indicator()). To fan out one
		# independent recurrence per symbol WITHOUT re-binding those attrs (whose
		# names the base does not know — P5-D21 keeps the author surface untouched),
		# each ticker's (state, buffer) per handle is stashed in _handle_state_store
		# and swapped INTO the registration handles before that ticker's update /
		# generate_signal. _active_ticker tracks which ticker's state is currently
		# loaded so a switch saves the outgoing ticker first (independent per-symbol
		# state + readiness, P5-D10b).
		self._handle_state_store: dict[str, list[tuple[Any, Any]]] = {}
		self._active_ticker: str | None = None
		# P5-D13/D13a: per-symbol bar bookkeeping replacing the removed per-tick
		# self.bars master-frame slice. update(ticker,bar) increments a per-ticker
		# completed-bar count and stashes the latest bar, so a zero-handle COUNT/
		# DATE-keyed fixture (SingleMarketBuy/ScriptedEmitter) derives its firing
		# from bar_count(ticker)/latest_bar(ticker) instead of len(self.bars). The
		# decision anchor self.now is the dispatched bar's open-time (a tz-aware
		# pandas Timestamp — the SAME value the legacy window.index[-1] carried, so
		# every e2e scenario's self.now.tz_convert("UTC") keeps working).
		self._bar_counts: dict[str, int] = {}
		self._latest_bar: dict[str, Any] = {}
		# P5-D13a: a small per-ticker bounded recent-CLOSE buffer for the handful of
		# indicator-free strategies that read more than the latest bar (a prior-bar
		# compare, e.g. close vs close[-2], or a short rolling z over the last
		# `max_window` closes). It replaces those strategies' old `self.bars["close"]`
		# window reads. Depth = max(max_window, 2) so a `[-2]` prior-bar read is
		# always available even when max_window < 2. NOTE: max_window is derived in
		# the post-init() pass below, so the deques are (re)sized in update() lazily
		# against the resolved depth (init() runs before max_window is known).
		self._recent_closes: dict[str, deque[float]] = {}
		# CR-01-strategy (Option B design point 2): per-symbol monotonic cursor of the
		# last ACCEPTED bar.time (raw stdlib datetime — no pandas, no conversion). update()
		# rejects bar.time <= this before ANY state mutation so a re-delivered warmup bar
		# (CR-02 retry re-warm) or a live reconnect-resend duplicate cannot double-count
		# _bar_counts / _recent_closes / advance the O(1) indicator handles. Cleared in
		# reset()/_reset_ticker() so an evaluate() window replay still works (see below).
		self._last_bar_time: dict[str, datetime] = {}
		self.now: Any = None
		self.current_bar: Any = None
		self.init()
		derived = max((h.min_period() for h in self._handles), default=0)
		self.warmup = derived
		# Fetch width: never shrink below a hand-set class value (preserve the
		# fixtures' wide window; the reference's deleted hand-set is 0 -> derived).
		self.max_window = max(derived, type(self).max_window)

	def _activate_ticker(self, ticker: str) -> None:
		"""Load ``ticker``'s per-symbol recurrence state into the registration handles.

		The per-symbol fan-out (P5-D10/D14) keeps ONE set of registration handles
		(the author-bound ``self.short_sma`` etc.) and swaps each ticker's
		``(state, buffer)`` in/out so the read surface always reflects the active
		ticker WITHOUT re-binding the author's attrs (P5-D21). Switching from a
		different active ticker SAVES the outgoing ticker's live state first
		(independent per-symbol state, P5-D10b); a never-seen ticker gets a fresh
		state minted on the handles (P5-D10a). A no-op when ``ticker`` is already
		active. Handle-free strategies have an empty registration set, so this is a
		no-op loop for them.
		"""
		if self._active_ticker == ticker:
			return
		# Save the currently-loaded ticker's live state back to its slot.
		if self._active_ticker is not None:
			self._handle_state_store[self._active_ticker] = [
				h.snapshot_state() for h in self._handles
			]
		stored = self._handle_state_store.get(ticker)
		if stored is None:
			# Never-seen ticker: mint a fresh state on each registration handle.
			self._handle_state_store[ticker] = [h.fresh_state() for h in self._handles]
		else:
			for handle, (state, buffer) in zip(self._handles, stored):
				handle.load_state(state, buffer)
		self._active_ticker = ticker

	def update(self, ticker: str, bar: Any) -> None:
		"""Push ``ticker``'s latest completed bar into its handle-set (P5-D07/D10/D14).

		Extracts each handle's declared ``input_col`` from the bar and pushes it
		through THAT ticker's stateful handle-set. Called on EVERY consumed bar
		(update during warmup, gate emission only — RESEARCH Pattern 2): skipping
		``update`` during warmup would corrupt the O(1) recurrence state. A
		missing/gap bar is handled by the CALLER (it never calls ``update`` when the
		bar is absent — P5-D10c, state frozen, count increments on REAL bars only —
		so this method never fabricates a bar).
		"""
		# CR-01-strategy (Option B design point 2): reject a re-delivered bar BEFORE any
		# state mutation. A CR-02 next-poll FAILED-retry re-warms an overlapping window
		# through THIS path (StrategiesHandler.on_bars_loaded), and the live per-tick path
		# can receive a duplicate bar on a reconnect resend — either would inflate
		# _bar_counts past min_period OFF DUPLICATES and advance the O(1) recurrences over
		# repeated values (garbage indicator state → a symbol tradeable on corruption). The
		# None-check is REQUIRED (a never-seen ticker has last is None → bar.time <= None
		# would TypeError). Reject is `<=`: strict `<` (out-of-order) warns + drops; `==`
		# (duplicate) drops SILENTLY (expected/benign). Monotonic bars (bar.time > last, and
		# the first bar) fall through and record the raw bar.time at the end of the method.
		# BACKTEST INERTNESS: update() IS on the backtest per-tick path
		# (strategies_handler.on_bar), BUT backtest bars for a ticker arrive
		# strictly monotonically increasing in bar.time, so `bar.time <= last` is NEVER
		# true — the reject branch is never taken and the SMA_MACD oracle is byte-exact.
		last_time = self._last_bar_time.get(ticker)
		if last_time is not None and bar.time <= last_time:
			if bar.time < last_time:
				logger.warning(
					"Out-of-order bar for %s at %s (< last=%s) — dropped "
					"(no state mutation)", ticker, str(bar.time), str(last_time))
			return
		# P5-D13a: per-symbol completed-bar bookkeeping (replaces the removed
		# self.bars slice). Count increments on REAL bars only (gap bar = caller
		# skips update -> count frozen, P5-D10c); the latest bar + decision anchor
		# self.now (the bar's tz-aware open-time Timestamp, the SAME value the
		# legacy window.index[-1] carried) are stashed for the count/date fixtures
		# and generate_signal.
		self._bar_counts[ticker] = self._bar_counts.get(ticker, 0) + 1
		self._latest_bar[ticker] = bar
		# P5-D13a: maintain the per-ticker bounded recent-close buffer for the
		# multi-bar indicator-free strategies (recent_closes seam). Depth is
		# max(max_window, 2) — created lazily here (max_window is resolved by now).
		recent = self._recent_closes.get(ticker)
		if recent is None:
			recent = deque(maxlen=max(self.max_window, 2))
			self._recent_closes[ticker] = recent
		recent.append(float(bar.close))
		self.now = bar.time
		self.current_bar = bar
		# P5-D10/D14: load this ticker's recurrence state into the registration
		# handles (the author-bound self.short_sma etc.), then push the bar value.
		self._activate_ticker(ticker)
		for handle, (_adapter, input_col, _params) in zip(self._handles, self._handle_specs):
			handle.update(float(getattr(bar, input_col)))
		# CR-01-strategy: record the accepted bar.time (raw) as the per-symbol monotonic
		# cursor so a subsequent duplicate (==) or out-of-order (<) bar is rejected by the
		# guard at the top of update() before it can mutate state.
		self._last_bar_time[ticker] = bar.time

	def bar_count(self, ticker: str) -> int:
		"""Completed-bar count seen for ``ticker`` (P5-D13a count seam).

		Replaces ``len(self.bars)`` for the zero-handle COUNT-keyed fixtures
		(SingleMarketBuy): the count increments once per consumed bar in
		``update`` (REAL bars only — a gap bar is skipped by the caller, so the
		count is frozen, P5-D10c), so ``bar_count(ticker)`` on the decision tick
		equals the number of completed bars visible — byte-identically to the old
		``len(self.bars)`` against a wide ``max_window``.
		"""
		return self._bar_counts.get(ticker, 0)

	def latest_bar(self, ticker: str) -> Any:
		"""Latest completed bar pushed for ``ticker`` (P5-D13a latest-bar seam).

		Replaces ``self.bars.index[-1]`` / ``self.bars["close"].iloc[-1]`` for the
		zero-handle DATE-keyed fixture (ScriptedEmitter): the decision bar IS the
		latest pushed bar. Returns ``None`` before any bar is seen (the fixtures
		guard the empty case, mirroring the old ``self.bars.empty`` skip).
		"""
		return self._latest_bar.get(ticker)

	def recent_closes(self, ticker: str) -> list[float]:
		"""Last ``max(max_window, 2)`` closes for ``ticker``, oldest-first (P5-D13a).

		The multi-bar read seam for the handful of indicator-free strategies that
		need a small trailing close window (a prior-bar compare ``[-2]`` or a short
		rolling z over the last ``max_window`` closes) — replacing their old
		``self.bars["close"]`` window. Returns the bounded buffer as a plain list
		(empty before any bar). The buffer is depth ``max(max_window, 2)``, so
		``[-2]`` is always available once two bars have arrived and the rolling
		window covers ``max_window`` closes.
		"""
		recent = self._recent_closes.get(ticker)
		return list(recent) if recent is not None else []

	def is_ready(self, ticker: str) -> bool:
		"""True iff ALL of ``ticker``'s handles are ready (P5-D06/D10b).

		Per-indicator readiness aggregated per symbol (``all(h.is_ready)``); a
		symbol with no declared handles is ALWAYS ready (no gating). Readiness is
		independent across symbols (P5-D10b) — one ticker being ready never gates
		another. A ticker that has never received a bar is NOT ready.
		"""
		stored = self._handle_state_store.get(ticker)
		if stored is None:
			# No bar seen yet for this ticker -> not ready (unless handle-free).
			return not self._handle_specs
		# Readiness reads the per-ticker stored states directly (no need to load
		# them onto the registration handles) — each stored entry is (state, buffer)
		# and the state carries is_ready (count >= min_period, P5-D06).
		return all(state.is_ready for state, _buffer in stored)

	def reset(self) -> None:
		"""Clear every per-symbol recurrence state AND the fan-out store (P5-D19).

		Each stored per-symbol ``(state, buffer)`` is dropped and the registration
		handles are reset, returning the strategy's indicator state to a
		just-constructed shape (so a re-feed reproduces a fresh run, P5-D19).
		"""
		for handle in self._handles:
			handle.reset()
		self._handle_state_store.clear()
		self._active_ticker = None
		# P5-D13a/D19: clear the per-symbol bar bookkeeping + decision anchors so a
		# re-feed reproduces a fresh run (the count/latest-bar fixtures see no prior
		# bars after reset).
		self._bar_counts.clear()
		self._latest_bar.clear()
		self._recent_closes.clear()
		# CR-01-strategy: clear the per-symbol monotonic cursor so a re-feed reproduces a
		# fresh run (an evaluate()/replay after reset() is not rejected on old timestamps).
		self._last_bar_time.clear()
		self.now = None
		self.current_bar = None

	def mark_unwarm(self) -> None:
		"""Force this strategy back to UNWARM so it must re-warm before signalling (WD-1/WD-2).

		The control-plane re-warm seam. ``StrategiesHandler`` calls this when a verb
		invalidates the strategy's indicator window — today ``enable`` (WD-1), and the
		same seam Plan 07's ``add`` and Plan 08's ``reconfigure`` re-warm through (ONE
		warm path, not three).

		WHY it exists (WD-1). The D-07 ``is_active`` guard sits FIRST in the
		``on_bar`` loop, so ``update`` never runs while a strategy is disabled
		and its O(1) recurrence state FREEZES rather than advancing. Re-enabling without
		this call would leave the strategy holding values computed across an N-bar HOLE
		spanning the disabled period, and it would fire IMMEDIATELY from that state —
		SMA/MACD silently produce wrong values across a discontinuity. Warmth is monotone,
		so nothing else in the engine would ever notice. WD-1 accepts the re-warm cost on
		correctness grounds: never compute a signal from a discontinuous window.

		WHY it is a WRAPPER and NOT a flag (WD-2). Warmth is DERIVED — ``is_ready`` is
		``all(state.is_ready)`` over the per-symbol handles (P5-D06/D10b). A
		``self._warm = False`` flag would be a SECOND source of truth that diverges from
		that computation the moment the next bar lands. So this delegates to ``reset()``
		(the existing P5-D19 handle+bookkeeping reset) and ``is_ready`` remains the single
		computed truth. There is deliberately no ``mark_warm`` inverse: warmth is EARNED by
		feeding bars, never asserted.

		Clearing ``_last_bar_time`` (which ``reset`` does) is LOAD-BEARING, not incidental:
		the CR-01 monotonic guard rejects any ``bar.time <= last accepted`` BEFORE mutating
		state, so without the clear a ``BarsLoaded`` re-warm replay of historical bars
		would be rejected wholesale and the strategy would stay dark FOREVER.

		⚠ ``PairStrategy`` OVERRIDES this — its warmth is not handle-derived. See
		``pair_base.py::mark_unwarm``.
		"""
		self.reset()

	def evaluate(self, ticker: str, window: pd.DataFrame) -> SignalIntent | None:
		"""LEGACY window-driven seam (P5-D13 — OFF the per-tick run path).

		Plan C removed the per-tick ``feed.window()`` slice: the handler now drives
		value production via ``update(ticker, bar)`` per tick and gates on
		``is_ready(ticker)`` (P5-D14), so ``evaluate`` is NO LONGER called from
		``StrategiesHandler.on_bar``. It survives ONLY as a direct
		window-driven test/back-compat seam (e.g. ``test_strategy`` feeds a
		synthetic frame): it RESETS ``ticker``'s state, replays the window's bars
		through the SAME ``update`` push (Model B — value-identical to the old
		``repopulate``), then dispatches ``generate_signal``. The per-tick
		master-frame stash and the window-replay handle-rebuild are both GONE
		(removed by P5-D13); ``update`` sets the per-symbol count/latest-bar/
		``self.now`` anchors the fixtures and ``generate_signal`` read.

		IN-03: still NOT re-entrant — it mutates shared per-symbol state (the
		handle-set + count/latest-bar + ``self.now``) before dispatch, so one writer
		at a time (the single-writer contract; the backtest loop is synchronous and
		live mode processes on one daemon thread).

		Empty-window guard: a zero-warmup strategy can be handed an empty frame; the
		replay loop is then a no-op (no bar pushed -> count stays 0, ``self.now``
		stays ``None``) and the strategy still runs (count/date fixtures guard the
		empty case).
		"""
		# IN-06: cheap debug-build re-entrancy guard (see class docstring). The
		# `assert` compiles out under `python -O`; on the synchronous single-writer
		# path the flag is always clear on entry, so this is a pure no-op there.
		assert not getattr(self, "_evaluating", False), (
			"Strategy.evaluate is not re-entrant — a second writer raced on the "
			"per-tick snapshot (IN-06 single-writer contract)."
		)
		self._evaluating = True
		try:
			# Replay the window through the per-tick update() push so the legacy
			# frame-driven callers (tests) get value-identical handle state without
			# the removed self.bars slice. Reset ticker state first so a repeated
			# evaluate(ticker, window) is idempotent (mirrors the old repopulate's
			# mint-fresh-state behavior).
			self._reset_ticker(ticker)
			for _ts, row in window.iterrows():
				self.update(ticker, _RowBar(row, _ts))
			return self.generate_signal(ticker)
		finally:
			self._evaluating = False

	def _reset_ticker(self, ticker: str) -> None:
		"""Drop ``ticker``'s recurrence state + bar bookkeeping (legacy evaluate replay).

		Keeps the legacy window-driven ``evaluate`` idempotent: a fresh
		``evaluate(ticker, window)`` rebuilds state from scratch, matching the old
		``repopulate`` (mint-fresh-state) semantics for the single ticker. Dropping
		the stored state + clearing the active marker forces ``_activate_ticker`` to
		mint a fresh state on the next ``update``.
		"""
		self._handle_state_store.pop(ticker, None)
		if self._active_ticker == ticker:
			self._active_ticker = None
		self._bar_counts.pop(ticker, None)
		self._latest_bar.pop(ticker, None)
		self._recent_closes.pop(ticker, None)
		# CR-01-strategy: pop the per-symbol cursor too — LOAD-BEARING for evaluate(): it
		# calls _reset_ticker(ticker) then replays the window through update(), so without
		# this pop a SECOND evaluate() replay would reject every bar (bar.time <= last) and
		# break the legacy window-driven tests.
		self._last_bar_time.pop(ticker, None)

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
		# WR2-02 / IN2-02 — the SAME wrap as ``Strategy.__init__``; see the full rationale
		# there (clause order is the no-double-wrap enforcement, and ``_run_init`` stays
		# outside on purpose). Both construction paths must type the residue identically,
		# otherwise a reconfigure refusal would still escape
		# ``StrategyLifecycleManager._reconfigure_strategy_verb``'s narrowed catch.
		try:
			self._apply_params(**kwargs)
			self.validate()
		except StrategyAdmissionError:
			raise
		except ValueError as exc:
			raise StrategyValidationError(str(exc)) from exc
		# D-08/D-10: re-register handles + re-derive warmup (idempotent).
		self._run_init()
		# D-06 (08-03 Req 4): _apply_params re-commits DECLARED params, so the
		# per-instance static to_dict cache is now stale — drop it so the next
		# to_dict re-introspects the new declared values. reconfigure is the ONLY
		# declared-param mutator in Phase 8; it is never on the backtest run path.
		self._invalidate_to_dict_cache()

	def to_dict(self) -> dict[str, Any]:
		# D-06 (PERF-04 / 08-03 Req 4): the FULL snapshot is re-introspected +
		# re-walked (_declared_hints loop + _json_safe) PER SIGNAL — a ~3.3%
		# hotspot, all of it static except two runtime fields. Build the static
		# snapshot ONCE per instance (lazily, on first call), stash it on self,
		# and on every call return a COPY with ONLY the two genuinely runtime-
		# mutable keys refreshed IN PLACE: is_active (activate/deactivate) and
		# subscribed_portfolios (subscribe/unsubscribe). Both keys already exist
		# in the cached dict at their original positions, so assigning to them
		# preserves key ordering — the output stays byte-identical to the pre-
		# change dict (test_to_dict_snapshot pins this). All other fields are
		# set-once in __init__/_apply_params with no setter except reconfigure
		# (which calls _invalidate_to_dict_cache). The cache is never invalidated
		# on the backtest run path → zero backtest cost, byte-exact preserved.
		if self._to_dict_static_cache is None:
			self._to_dict_static_cache = self._build_to_dict_snapshot()
		# WR-01 (08-REVIEW; 260626-dnq): isolate the cached static snapshot per
		# serve. A shallow dict() copy would SHARE the snapshot's nested mutables
		# (e.g. a declared `tickers` list, any list/dict knob walked by _json_safe)
		# across the cache and every returned dict — so a caller mutating
		# result["tickers"] would poison the cache and all other callers (the
		# pre-cache code rebuilt a fresh dict per call, so each got its own nested
		# lists). The snapshot value domain is scalars + plain list/dict (normalized
		# by _json_safe — no custom mutable leaves), so the recursive list/dict copy
		# in _isolating_copy gives the SAME per-call nested-container isolation
		# copy.deepcopy gave (a caller mutating result["tickers"] cannot poison the
		# cache) while staying byte-identical (same types/values) and skipping
		# deepcopy's memo/introspection overhead (~5% W1 hot-path). The top-level
		# cache is a dict, so the dict branch copies the top level.
		# test_to_dict_snapshot still pins this. The two runtime keys are rebuilt
		# fresh below so they need no copy.
		# Explicit annotation: _isolating_copy is recursively heterogeneous and
		# returns Any; the top-level cache is a dict, so pin the concrete type
		# here to keep `return snapshot` strict-clean (no-any-return).
		snapshot: dict[str, Any] = _isolating_copy(self._to_dict_static_cache)
		snapshot["subscribed_portfolios"] = [str(pid) for pid in self.subscribed_portfolios]
		snapshot["is_active"] = self.is_active
		return snapshot

	def _build_to_dict_snapshot(self) -> dict[str, Any]:
		# WR-02: a faithful "params snapshot" (SIG-02 queryability) must capture
		# the FULL declared surface — timeframe / tickers / max_window / warmup
		# AND every subclass tuning knob (short_window, long_window, …) — not a
		# hand-listed subset. Introspect _declared_hints(type(self)) (memoized
		# get_type_hints, D-05) so the
		# snapshot can interpret a signal (which timeframe, which tickers, which
		# windows). The identity/runtime fields below (strategy_id,
		# strategy_name, is_active, subscribed_portfolios) and the bespoke
		# serializations (enum .value, policy repr, timeframe_alias instead of
		# the timedelta) take precedence over the raw declared value. The two
		# runtime fields (is_active, subscribed_portfolios) are written here with
		# their CURRENT values so the cached dict carries the keys at the correct
		# positions; to_dict overwrites them in place per call (D-06 / 08-03).
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
			# serialization edge (str(uuid) == "019e..."); this str() IS the
			# reason the durable portfolio_id column is a String — rehydrate's
			# _resolve_portfolio_id is its parsing inverse.
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

	def _invalidate_to_dict_cache(self) -> None:
		# D-06 (08-03 Req 4): drop the per-instance static to_dict cache so the
		# next to_dict rebuilds it. ANY setter that mutates a DECLARED param
		# (anything serialized in _build_to_dict_snapshot other than the two
		# runtime fields is_active/subscribed_portfolios) MUST call this. In
		# Phase 8 the only such setter is reconfigure (_apply_params re-commits
		# declared params); the backtest run path never reconfigures, so this is
		# never called on the hot path → zero backtest cost, byte-exact preserved.
		self._to_dict_static_cache = None

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

		The pure-alpha contract (D-06/D-12/P5-D13/D14, M5-06): the ``bars`` param is
		dropped — the handler has already pushed ``ticker``'s latest completed bar
		via ``update(ticker, bar)`` (driving the declared indicator handles) and
		gated on ``is_ready(ticker)``. A concrete strategy reads its handles
		(``self.short_sma[-1]``) and the per-symbol decision anchors
		(``self.now`` / ``self.current_bar``; the zero-handle COUNT/DATE fixtures use
		``self.bar_count(ticker)`` / ``self.latest_bar(ticker)``), and returns a
		``SignalIntent`` (typically via the ``buy()`` / ``sell()`` sugar) or ``None``
		when there is nothing to do. No queue, no event construction, no portfolio
		knowledge. The per-tick ``self.bars`` master-frame slice is GONE (P5-D13).
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

	def subscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
		# WR-01: idempotent subscribe — a duplicate subscription would fan the
		# same intent out to one portfolio TWICE in on_bar (two
		# SignalEvents, two orders for one decision). Guard the append.
		if portfolio_id not in self.subscribed_portfolios:
			self.subscribed_portfolios.append(portfolio_id)

	def unsubscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
		# WR-01: idempotent unsubscribe — list.remove raises ValueError on a
		# double-unsubscribe / never-subscribed id (a noisy ErrorEvent in live
		# mode). Guard so a defensive caller can unsubscribe safely.
		if portfolio_id in self.subscribed_portfolios:
			self.subscribed_portfolios.remove(portfolio_id)

	def activate_strategy(self) -> None:
		self.is_active = True

	def deactivate_strategy(self) -> None:
		self.is_active = False
