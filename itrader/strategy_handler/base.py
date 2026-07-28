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

# The base Strategy has no per-instance self.logger, so update()'s out-of-order-bar
# warning uses this shared component logger.
logger = get_itrader_logger().bind(component="Strategy")

from .indicators import IndicatorAdapter, IndicatorHandle

# Distinguishes a bare (required) annotation — a class attr with NO value — from a
# class attr whose default happens to be None.
_MISSING = object()


class _RowBar:
	"""Bar-shaped adapter over a pandas (row, timestamp) for the legacy ``evaluate``.

	The run path drives ``update(ticker, bar)`` with real ``Bar`` objects. The legacy
	window-driven ``evaluate`` replays a pandas frame row-by-row, so it wraps each
	``(row, ts)`` in this shim exposing the two attributes ``update`` reads: the
	declared ``input_col`` and ``time``. NOT used on the run path.
	"""

	__slots__ = ("_row", "time")

	def __init__(self, row: "pd.Series[Any]", ts: Any) -> None:
		self._row = row
		self.time = ts

	def __getattr__(self, name: str) -> Any:
		# Column access by attribute (bar.close -> row["close"]); __getattr__ fires
		# only for names not in __slots__, so ``time`` is served directly. A typo'd
		# declared ``input_col`` would otherwise surface as a bare pandas KeyError far
		# from the declaration site.
		try:
			return self._row[name]
		except KeyError as exc:
			raise KeyError(
				f"_RowBar: column {name!r} not found in the replayed row — "
				f"check the strategy's declared input_col"
			) from exc

def _is_json_native(val: Any) -> bool:
	# Classifies scalar LEAVES only (`bool` is covered as an `int` subclass).
	# list/dict are deliberately not native by container type — a `list[Decimal]`
	# would still break `json.dumps` — so `_json_safe` below is the real guarantee.
	return val is None or isinstance(val, (str, int, float))


def _json_safe(val: Any) -> Any:
	# Recursively repr-coerce non-native leaves at the serialization edge so
	# `json.dumps(strategy.to_dict())` never raises. A container is JSON-safe only
	# if its CONTENTS are, so the contract has to be structural rather than a
	# top-level type check.
	if _is_json_native(val):
		return val
	if isinstance(val, list):
		return [_json_safe(x) for x in val]
	if isinstance(val, tuple):
		# tuples serialize to JSON arrays — preserve that shape.
		return [_json_safe(x) for x in val]
	if isinstance(val, dict):
		return {str(k): _json_safe(x) for k, x in val.items()}
	return repr(val)


# Per-call isolating copy for the to_dict static-snapshot cache, standing in for
# copy.deepcopy at the serve site (~5% of the W1 hot path). _json_safe has already
# normalized the snapshot's value domain to immutable scalars plus plain list/dict
# containers — there are NO custom mutable leaves — so a recursive walk over only
# list/dict reproduces deepcopy's per-call isolation at any depth, without its memo
# dict and immutable-copying overhead. `type(...) is` rather than isinstance keeps
# the walk conservative against container subclasses.
def _isolating_copy(val: Any) -> Any:
	if type(val) is list:
		return [_isolating_copy(x) for x in val]
	if type(val) is dict:
		return {k: _isolating_copy(v) for k, v in val.items()}
	return val


# Memoize get_type_hints per concrete Strategy subclass: the declared-attr
# annotations are fixed at import, yet to_dict re-walked and re-resolved the MRO on
# every signal snapshot. functools.cache is thread-safe for live mode and needs no
# invalidation — the strategy-class count is bounded and annotations never change
# after import. Both call sites only ITERATE keys and never mutate, so sharing one
# cached dict across them is safe.
# CACHE-CLASS: (c) pure-function memo — see docs/CACHE-CLASSIFICATION.md
@cache
def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:
	return get_type_hints(cls)

# ONLY these engine fields coerce a str off their annotation to an enum, via the
# enum's case-insensitive _missing_. Every other knob is left exactly as supplied —
# short_window="50" stays a str, never silently int()-ed.
_COERCE: dict[str, type[Enum]] = {
	"timeframe": Timeframe,
	"direction": TradingDirection,
}

class Strategy(ABC):
	"""
	The pure-alpha abstract base for all strategies.

	A concrete strategy is a pure function of market data: it implements
	``generate_signal(ticker) -> SignalIntent | None`` and DECLARES its sizing
	policy, trading direction, and admission settings as CLASS ATTRIBUTES. The base
	introspects its own plus the subclass's annotations, applies ``**kwargs`` over
	them, coerces the ``_COERCE`` enum fields, and rejects unknown or
	missing-required params loudly.

	It never touches the events queue, never stamps time or price, and never knows
	anything portfolio-shaped — ``StrategiesHandler`` owns stamping, policy
	attachment, per-portfolio fan-out, and enqueueing.
	"""

	# Base-owned engine-facing names. A BARE annotation (no value) marks a REQUIRED
	# param: it must be pinned by a subclass class-attr or passed as a kwarg, else
	# MissingParamError.
	#
	# EVERY engine-facing knob must be ANNOTATED — `_apply_params` iterates
	# `_declared_hints(type(self))`, which returns only ANNOTATED names, so an
	# unannotated class attr is invisible to the engine: un-overridable by kwarg,
	# and its enum coercion never fires.
	#
	# `timeframe` is annotated as its RESOLVED consumer type. The kwarg arrives as a
	# "1d" str or Timeframe enum, but _apply_params leaves a timedelta on
	# self.timeframe (read as `last_time - self.timeframe * self.short_window`).
	timeframe: timedelta          # required — no class-attr value
	tickers: list[str]            # required
	sizing_policy: SizingPolicy   # required
	direction: TradingDirection = TradingDirection.LONG_ONLY
	allow_increase: bool = False
	max_positions: int = 1
	sltp_policy: SLTPPolicy | None = None
	max_window: int = 0
	warmup: int = 0
	name: str = "strategy"        # a subclass pins it

	def __init__(self, **kwargs: Any) -> None:
		# The portfolio-id handle carries exactly ONE shape, the UUIDv7-backed
		# PortfolioId (the FL-02 invariant): it feeds PortfolioReadModel.get_position
		# and the on_bar fan-out's SignalEvent.portfolio_id, both of which require a
		# real PortfolioId.
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.is_active = True
		self.subscribed_portfolios: list[PortfolioId] = []
		# Cache of the STATIC portion of to_dict, built lazily on first call (the
		# declared params are only committed by _apply_params below, so building it
		# here would be __init__-order-fragile). PER-INSTANCE, never per-class: a
		# per-class cache would leak one instance's declared windows (short_window=10
		# vs 20) into another.
		# CACHE-CLASS: (c) explicitly-invalidated memo (via _invalidate_to_dict_cache) — see docs/CACHE-CLASSIFICATION.md
		self._to_dict_static_cache: dict[str, Any] | None = None
		# TYPE the bare-``ValueError`` residue escaping this span. Four collaborators
		# inside it raise a bare ``ValueError``: ``Strategy.validate``, any subclass
		# override of it (including third-party ones outside our hierarchy),
		# ``_apply_params``'s malformed-``tickers`` guard, and its ``_COERCE`` coercion
		# off a bogus enum string. Untyped, that residue sits outside
		# ``StrategyAdmissionError`` and so outside ``registry.rehydrate._QUARANTINABLE``,
		# where ONE stale registry row whose class had gained a cross-field rule aborts
		# the whole live boot instead of being quarantined — a bad ROW becoming a bad
		# SYSTEM. Converting at the raise boundary is what lets ``_QUARANTINABLE`` stay
		# narrow instead of asking every strategy class to opt into our hierarchy.
		#
		# CLAUSE ORDER IS LOAD-BEARING — do not reorder, and do not collapse the two
		# clauses into one ``isinstance`` test. ``StrategyAdmissionError`` already
		# subclasses ``ValueError``, so a lone ``ValueError`` clause would also claim
		# ``UnknownParamError`` / ``MissingParamError`` / ``StrategyConfigError`` /
		# ``UnknownStrategyTypeError``, and re-raising those as
		# ``StrategyValidationError`` would DESTROY the structured fields (``field`` /
		# ``message`` / ``.names``) every rejection diagnostic reads.
		#
		# ``_run_init`` / ``init()`` sit deliberately OUTSIDE the span: ``init()`` is
		# arbitrary user-authored code, and ``_add_strategy_verb``'s tier-2 guard owns
		# that zone.
		#
		# ACCEPTED TRADE: this reclassifies a genuine programming bug inside a
		# strategy's ``validate()`` (a typo'd comparison, say) as an admission failure
		# rather than a crash — the same trade ``_add_strategy_verb``'s tier-2 catch-all
		# already makes at the add site.
		try:
			self._apply_params(**kwargs)
			self.validate()
		except StrategyAdmissionError:
			raise
		except ValueError as exc:
			raise StrategyValidationError(str(exc)) from exc
		# Register declared indicators (init() calls self.indicator()), then
		# auto-derive warmup/max_window from the registered handles.
		self._run_init()

	def _apply_params(self, **kwargs: Any) -> None:
		"""Apply ``**kwargs`` over the declared class-attr surface.

		``_declared_hints(type(self))`` merges the full MRO so base-owned names and
		the subclass's params are introspected together. Per declared name the
		resolution order is: the kwarg if present, else the prior INSTANCE value on a
		reconfigure (a partial reconfigure keeps the prior value), else the class-attr
		default. A bare annotation with no default and no prior value is a required
		param and raises ``MissingParamError``; any leftover kwarg raises
		``UnknownParamError`` — loud rejection, never a silent drop.
		"""
		# Recorded BEFORE the loop pops it.
		timeframe_supplied = "timeframe" in kwargs
		# Has _apply_params run before? (reconfigure path — fall back to instance)
		reconfiguring = hasattr(self, "_timeframe")
		hints = _declared_hints(type(self))
		# Resolve + coerce + validate the FULL kwarg set into a local dict first,
		# committing to `self` only once every check passes: setattr'ing inside the
		# loop leaves the instance PARTIALLY mutated when a later coercion failure or
		# the tickers guard rejects a reconfigure. Popping from the local copy keeps
		# resolution side-effect-free until the commit phase.
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
				# Copy mutable class-attr defaults so one is not ALIASED across every
				# instance built without that kwarg — the classic mutable-default bug
				# re-expressed through class attributes, where
				# `a.tickers.append(...)` leaks into `b.tickers`. The guard is
				# mutability-based rather than a list/dict/set whitelist, so a declared
				# default of a deque / numpy array / custom object is alias-safe too.
				# Deep-copying an effectively-immutable policy yields an equal fresh
				# copy — harmless.
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
		# Reject a malformed-but-present `tickers`. A bare `str` iterates
		# char-by-char, so `for ticker in strategy.tickers` would silently request
		# windows for "B", "T", … and produce nothing rather than failing loudly; an
		# empty list trades nothing. Checked against the RESOLVED value so it covers
		# the kwarg and class-attr-default paths alike, and fires BEFORE any commit.
		tickers = resolved.get("tickers", _MISSING)
		if tickers is not _MISSING:
			if isinstance(tickers, str) or not isinstance(tickers, list) \
					or not tickers or not all(isinstance(t, str) for t in tickers):
				raise ValueError(
					"tickers must be a non-empty list[str] (a bare str is rejected)"
				)
		# Commit phase: every check above passed. A rejected reconfigure raised
		# before this line, leaving prior instance state intact.
		for nm, val in resolved.items():
			setattr(self, nm, val)
		# self.timeframe is consumed as a TIMEDELTA (`last_time - self.timeframe *
		# self.short_window`), but the loop just setattr'd the coerced Timeframe ENUM
		# onto it. Stash the enum on a stable attr, then re-resolve both the timedelta
		# and the serialization alias on EVERY pass.
		if timeframe_supplied:
			self._timeframe: Timeframe = cast(Timeframe, self.timeframe)
		else:
			# Reconfigure with no timeframe kwarg: fall back to the prior INSTANCE
			# enum, not the class attr, so a partial reconfigure keeps the prior
			# timeframe. On first construction the loop already applied the class
			# default (or a required miss has already raised).
			self._timeframe = getattr(self, "_timeframe", cast(Timeframe, self.timeframe))
		self.timeframe_alias: str = self._timeframe.value
		self.timeframe = to_timedelta(self._timeframe.value)

	def validate(self) -> None:
		"""Overridable cross-field validation hook.

		Runs after ``_apply_params`` on every construction and reconfigure. No-op by
		default; ``SMAMACDStrategy`` expresses ``short_window < long_window`` here.
		"""
		...

	def init(self) -> None:
		"""Overridable idempotent lifecycle hook.

		Called at the end of construction and on every ``reconfigure``; calling it
		twice leaves identical state. A concrete strategy registers its declared
		indicators here via ``self.indicator(...)``.
		"""
		...

	def indicator(
		self, adapter: IndicatorAdapter, input_col: str, *params: int
	) -> IndicatorHandle:
		"""Register a declared indicator and return its handle.

		Mirrors the ``backtesting.py`` ``self.I()`` shape: constructs an
		``IndicatorHandle`` over the typed ``adapter``, records it, and returns the
		handle so the author binds it to a named attr
		(``self.short_sma = self.indicator(SMA, "close", self.short_window)``). The
		auto-warmup post-pass derives ``warmup``/``max_window`` from
		``handle.min_period()``.

		A non-causal adapter is REJECTED here at the registration boundary, raised
		explicitly rather than asserted (``assert`` is stripped under ``-O``), so a
		future statistical/ML adapter that peeks the future can never silently enter
		the look-ahead-safe decision path.

		The per-symbol fan-out spec is recorded alongside so the framework can mint
		one stateful handle-set per symbol lazily, on that ticker's first bar, without
		the author declaring anything per-symbol.
		"""
		if not getattr(adapter, "causal", False):
			raise RuntimeError(
				f"non-causal adapter {type(adapter).__name__!r} rejected at "
				f"registration (P5-D20 causal guard): the decision path admits "
				f"only causal indicators (all v1 adapters declare causal=True)."
			)
		params_tuple = tuple(params)
		handle = IndicatorHandle(adapter, input_col, params_tuple)
		self._handles.append(handle)
		# The recipe, so per-symbol handle-sets can be minted lazily.
		self._handle_specs.append((adapter, input_col, params_tuple))
		return handle

	def _run_init(self) -> None:
		"""Reset handles, run ``init()``, then auto-derive warmup.

		Resetting ``self._handles`` BEFORE ``self.init()`` is what keeps a re-run
		idempotent. The post-``init()`` pass derives both thresholds from the declared
		handles' ``min_period``:

		- ``warmup`` is UNCONDITIONALLY overwritten to ``max(min_period, default=0)``,
		  so an author cannot hand-set it too LOW and under-gate the handler
		  short-circuit. A zero-handle strategy ends at ``warmup == 0`` — no gating.

		- ``max_window`` is the FETCH WIDTH requested from the feed, NOT a gating
		  threshold, so it takes ``max(handle-derived, hand-set class value)``. That
		  lets a zero-handle count/date-keyed fixture keep the wide window its logic
		  needs: a 0-width window is always empty against a real feed
		  (``frame.iloc[pos:pos]``), which would break its firing entirely.

		Called from both ``__init__`` and ``reconfigure``.
		"""
		self._handles: list[IndicatorHandle] = []
		# The declared recipes. Reset BEFORE init() so a re-run is idempotent: the
		# author declares once via self.indicator(...) and the framework fans out one
		# stateful handle-set per symbol on that symbol's FIRST bar.
		self._handle_specs: list[tuple[IndicatorAdapter, str, tuple[int, ...]]] = []
		# Per-symbol fan-out by state-swap over the SINGLE registration handle-set.
		# The author binds self.short_sma etc. to those handles, and the base does not
		# know the attr names it bound, so an independent recurrence per symbol cannot
		# be delivered by re-binding. Instead each ticker's (state, buffer) is stashed
		# here and swapped INTO the registration handles before that ticker's update /
		# generate_signal; _active_ticker tracks which is loaded so a switch saves the
		# outgoing ticker first.
		self._handle_state_store: dict[str, list[tuple[Any, Any]]] = {}
		self._active_ticker: str | None = None
		# Per-symbol bar bookkeeping. update() increments a per-ticker completed-bar
		# count and stashes the latest bar, so an indicator-free count/date-keyed
		# strategy derives its firing from bar_count()/latest_bar(). The decision
		# anchor self.now is the dispatched bar's tz-aware open-time.
		self._bar_counts: dict[str, int] = {}
		self._latest_bar: dict[str, Any] = {}
		# Bounded recent-CLOSE buffer for the indicator-free strategies that read more
		# than the latest bar (a `[-2]` prior-bar compare, or a short rolling window).
		# Depth is max(max_window, 2) so `[-2]` is available even when max_window < 2.
		# max_window is only derived in the post-init() pass below, so the deques are
		# sized lazily in update() against the resolved depth.
		self._recent_closes: dict[str, deque[float]] = {}
		# Per-symbol monotonic cursor of the last ACCEPTED bar.time. Cleared in
		# reset()/_reset_ticker() so an evaluate() window replay still works.
		self._last_bar_time: dict[str, datetime] = {}
		self.now: Any = None
		self.current_bar: Any = None
		self.init()
		derived = max((h.min_period() for h in self._handles), default=0)
		self.warmup = derived
		# Fetch width: never shrink below a hand-set class value.
		self.max_window = max(derived, type(self).max_window)

	def _activate_ticker(self, ticker: str) -> None:
		"""Load ``ticker``'s per-symbol recurrence state into the registration handles.

		Swaps each ticker's ``(state, buffer)`` in and out of the ONE registration
		handle-set so the read surface always reflects the active ticker without
		re-binding the author's attrs. Switching from another active ticker SAVES the
		outgoing ticker's live state first; a never-seen ticker gets a fresh state
		minted. A no-op when ``ticker`` is already active, and for handle-free
		strategies (empty registration set).
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
		"""Push ``ticker``'s latest completed bar into its handle-set.

		Extracts each handle's declared ``input_col`` from the bar and pushes it
		through THAT ticker's stateful handle-set. Called on EVERY consumed bar —
		update during warmup, gate emission only: skipping ``update`` during warmup
		would corrupt the O(1) recurrence state. A missing/gap bar is the CALLER's
		problem; it simply does not call ``update``, so state freezes and the count
		advances on REAL bars only. This method never fabricates a bar.
		"""
		# Reject a re-delivered bar BEFORE any state mutation. A failed-poll retry
		# re-warms an overlapping window through this path, and the live path can
		# receive a duplicate on a reconnect resend — either would inflate _bar_counts
		# past min_period OFF DUPLICATES and advance the O(1) recurrences over repeated
		# values, leaving garbage indicator state that reads as warm and makes the
		# symbol tradeable on corruption. The None-check is REQUIRED: a never-seen
		# ticker has last is None, and `bar.time <= None` would TypeError. Rejection is
		# `<=` — strict `<` (out-of-order) warns and drops, `==` (duplicate) drops
		# silently, being expected and benign. Backtest bars for a ticker arrive
		# strictly increasing, so this branch is never taken there.
		last_time = self._last_bar_time.get(ticker)
		if last_time is not None and bar.time <= last_time:
			if bar.time < last_time:
				logger.warning(
					"Out-of-order bar for %s at %s (< last=%s) — dropped "
					"(no state mutation)", ticker, str(bar.time), str(last_time))
			return
		self._bar_counts[ticker] = self._bar_counts.get(ticker, 0) + 1
		self._latest_bar[ticker] = bar
		# Bounded recent-close buffer, created lazily here because max_window is only
		# resolved after init().
		recent = self._recent_closes.get(ticker)
		if recent is None:
			recent = deque(maxlen=max(self.max_window, 2))
			self._recent_closes[ticker] = recent
		recent.append(float(bar.close))
		self.now = bar.time
		self.current_bar = bar
		# Load this ticker's recurrence state into the registration handles (the
		# author-bound self.short_sma etc.), then push the bar value.
		self._activate_ticker(ticker)
		for handle, (_adapter, input_col, _params) in zip(self._handles, self._handle_specs):
			handle.update(float(getattr(bar, input_col)))
		# Record the accepted bar.time so the guard at the top of update() can reject a
		# later duplicate or out-of-order bar before it mutates state.
		self._last_bar_time[ticker] = bar.time

	def bar_count(self, ticker: str) -> int:
		"""Completed-bar count seen for ``ticker``.

		The count seam for indicator-free count-keyed strategies. Increments once per
		consumed bar in ``update``, REAL bars only — a gap bar is skipped by the
		caller, so the count freezes rather than counting a hole.
		"""
		return self._bar_counts.get(ticker, 0)

	def latest_bar(self, ticker: str) -> Any:
		"""Latest completed bar pushed for ``ticker``.

		The latest-bar seam for indicator-free date-keyed strategies: the decision bar
		IS the latest pushed bar. Returns ``None`` before any bar is seen.
		"""
		return self._latest_bar.get(ticker)

	def recent_closes(self, ticker: str) -> list[float]:
		"""Last ``max(max_window, 2)`` closes for ``ticker``, oldest-first.

		The multi-bar read seam for indicator-free strategies needing a small trailing
		close window. Returns the bounded buffer as a plain list, empty before any bar
		arrives. Depth ``max(max_window, 2)`` means ``[-2]`` is available as soon as
		two bars have landed, whatever ``max_window`` is.
		"""
		recent = self._recent_closes.get(ticker)
		return list(recent) if recent is not None else []

	def is_ready(self, ticker: str) -> bool:
		"""True iff ALL of ``ticker``'s handles are ready.

		Per-indicator readiness aggregated per symbol. A symbol with no declared
		handles is ALWAYS ready (no gating); readiness is independent across symbols,
		so one ticker being ready never gates another. A ticker that has never
		received a bar is NOT ready.
		"""
		stored = self._handle_state_store.get(ticker)
		if stored is None:
			# No bar seen yet for this ticker -> not ready (unless handle-free).
			return not self._handle_specs
		# Read the stored states directly — no need to load them onto the registration
		# handles just to ask whether they are ready.
		return all(state.is_ready for state, _buffer in stored)

	def reset(self) -> None:
		"""Clear every per-symbol recurrence state AND the fan-out store.

		Returns the strategy's indicator state to a just-constructed shape, so a
		re-feed reproduces a fresh run.
		"""
		for handle in self._handles:
			handle.reset()
		self._handle_state_store.clear()
		self._active_ticker = None
		self._bar_counts.clear()
		self._latest_bar.clear()
		self._recent_closes.clear()
		# Clearing the monotonic cursor too is what lets a replay after reset() land:
		# otherwise every replayed bar is rejected as an old timestamp.
		self._last_bar_time.clear()
		self.now = None
		self.current_bar = None

	def mark_unwarm(self) -> None:
		"""Force this strategy back to UNWARM so it must re-warm before signalling.

		The single control-plane re-warm seam, called by every verb that invalidates
		the strategy's indicator window (``enable``, ``add``, ``reconfigure``).

		WHY it exists. The ``is_active`` guard sits FIRST in the ``on_bar`` loop, so
		``update`` never runs while a strategy is disabled and its O(1) recurrence
		state FREEZES rather than advancing. Re-enabling without this call leaves the
		strategy holding values computed across an N-bar HOLE spanning the disabled
		period, and it fires IMMEDIATELY from that state — SMA/MACD silently produce
		wrong values across the discontinuity, and since warmth is monotone nothing
		else in the engine ever notices.

		WHY a WRAPPER and not a flag. Warmth is DERIVED: ``is_ready`` is
		``all(state.is_ready)`` over the per-symbol handles. A ``self._warm = False``
		flag would be a SECOND source of truth, diverging from that computation the
		moment the next bar lands. There is deliberately no ``mark_warm`` inverse —
		warmth is EARNED by feeding bars, never asserted.

		Clearing ``_last_bar_time`` (which ``reset`` does) is LOAD-BEARING: the
		monotonic guard rejects any ``bar.time <= last accepted`` before mutating
		state, so without the clear a re-warm replay of historical bars is rejected
		wholesale and the strategy stays dark FOREVER.

		⚠ ``PairStrategy`` OVERRIDES this — its warmth is not handle-derived.
		"""
		self.reset()

	def evaluate(self, ticker: str, window: pd.DataFrame) -> SignalIntent | None:
		"""LEGACY window-driven seam — OFF the per-tick run path.

		The handler drives value production through ``update(ticker, bar)`` per tick
		and gates on ``is_ready(ticker)``, so this is never called from
		``StrategiesHandler.on_bar``. It survives only as a direct window-driven
		test/back-compat seam: it RESETS ``ticker``'s state, replays the window's bars
		through the SAME ``update`` push, then dispatches ``generate_signal``.

		NOT re-entrant — it mutates shared per-symbol state (the handle-set, the
		count/latest-bar bookkeeping, ``self.now``) before dispatch, so one writer at a
		time. The backtest loop is synchronous and live mode processes on one daemon
		thread, so the contract holds on both paths.

		A zero-warmup strategy can be handed an empty frame: the replay loop is then a
		no-op and the strategy still runs.
		"""
		# Debug-build re-entrancy guard; `assert` compiles out under `python -O`, and
		# on the single-writer path the flag is always clear on entry.
		assert not getattr(self, "_evaluating", False), (
			"Strategy.evaluate is not re-entrant — a second writer raced on the "
			"per-tick snapshot (IN-06 single-writer contract)."
		)
		self._evaluating = True
		try:
			# Reset first so a repeated evaluate(ticker, window) is idempotent, then
			# replay through the per-tick update() push so frame-driven callers get
			# value-identical handle state.
			self._reset_ticker(ticker)
			for _ts, row in window.iterrows():
				self.update(ticker, _RowBar(row, _ts))
			return self.generate_signal(ticker)
		finally:
			self._evaluating = False

	def _reset_ticker(self, ticker: str) -> None:
		"""Drop ``ticker``'s recurrence state + bar bookkeeping.

		Keeps the legacy window-driven ``evaluate`` idempotent — a fresh
		``evaluate(ticker, window)`` rebuilds state from scratch. Dropping the stored
		state and clearing the active marker forces ``_activate_ticker`` to mint a
		fresh state on the next ``update``.
		"""
		self._handle_state_store.pop(ticker, None)
		if self._active_ticker == ticker:
			self._active_ticker = None
		self._bar_counts.pop(ticker, None)
		self._latest_bar.pop(ticker, None)
		self._recent_closes.pop(ticker, None)
		# LOAD-BEARING for evaluate(), which resets then replays the window through
		# update(): without this pop a SECOND replay rejects every bar as an old
		# timestamp.
		self._last_bar_time.pop(ticker, None)

	def reconfigure(self, **kwargs: Any) -> None:
		"""Re-apply + re-coerce kwargs, re-validate, re-run init().

		There is no ``__setattr__`` guard — sanctioned reconfiguration goes through
		here so validate() and init() always re-run.

		ASYMMETRIC FALLBACK: a field OMITTED from ``kwargs`` keeps its PRIOR INSTANCE
		VALUE, not the class default. Omission is therefore not a reset, and there is
		no way through an omitted kwarg to clear an optional field back to its
		default — you MUST pass it explicitly (``reconfigure(sltp_policy=None)``). A
		caller expecting "omitted == default" will be surprised.
		"""
		# The SAME wrap as ``Strategy.__init__`` — see the rationale there. Both
		# construction paths must type the residue identically, otherwise a reconfigure
		# refusal escapes ``_reconfigure_strategy_verb``'s narrowed catch.
		try:
			self._apply_params(**kwargs)
			self.validate()
		except StrategyAdmissionError:
			raise
		except ValueError as exc:
			raise StrategyValidationError(str(exc)) from exc
		# Re-register handles + re-derive warmup (idempotent).
		self._run_init()
		# _apply_params just re-committed the declared params, so the static to_dict
		# cache is stale.
		self._invalidate_to_dict_cache()

	def to_dict(self) -> dict[str, Any]:
		# The full snapshot is otherwise re-introspected and re-walked PER SIGNAL (a
		# ~3.3% hotspot), yet all of it is static except two runtime fields. Build it
		# once per instance, then return a copy with only ``is_active`` and
		# ``subscribed_portfolios`` refreshed IN PLACE. Both keys already exist in the
		# cached dict at their original positions, so assigning to them preserves key
		# ordering and the output stays byte-identical.
		if self._to_dict_static_cache is None:
			self._to_dict_static_cache = self._build_to_dict_snapshot()
		# Isolate the cached snapshot per serve. A shallow dict() copy would SHARE the
		# snapshot's nested mutables (a declared `tickers` list, any list/dict knob)
		# across the cache and every returned dict, so one caller mutating
		# result["tickers"] would poison the cache and every other caller. The value
		# domain is scalars plus plain list/dict, so the recursive walk gives the same
		# isolation deepcopy did at a fraction of the cost.
		# The annotation is explicit because _isolating_copy returns Any; pinning the
		# concrete type keeps `return snapshot` strict-clean.
		snapshot: dict[str, Any] = _isolating_copy(self._to_dict_static_cache)
		snapshot["subscribed_portfolios"] = [str(pid) for pid in self.subscribed_portfolios]
		snapshot["is_active"] = self.is_active
		return snapshot

	def _build_to_dict_snapshot(self) -> dict[str, Any]:
		# A faithful params snapshot must capture the FULL declared surface — every
		# base knob AND every subclass tuning knob — not a hand-listed subset, so that
		# a stored signal can be interpreted later (which timeframe, which tickers,
		# which windows). The identity/runtime fields and bespoke serializations below
		# take precedence over the raw declared value. The two runtime fields are
		# written with their current values so the cached dict carries the keys at the
		# right positions; to_dict overwrites them in place per call.
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
				# Capturing the full declared surface has to stay compatible with the
				# documented `json.dumps(strategy.to_dict())` contract: a declared attr
				# holding a Decimal / datetime / custom object — or a container of
				# them — is not JSON-safe.
				val = _json_safe(val)
			snapshot[nm] = val
		# Identity/runtime fields + bespoke serializations (override declared).
		snapshot.update({
			# Stringified: a raw uuid.UUID makes json.dumps(strategy.to_dict()) raise
			# "Object of type UUID is not JSON serializable".
			"strategy_id" : str(self.strategy_id),
			"strategy_name": self.name,
			# self.timeframe is a timedelta — serialize the stashed alias so the
			# snapshot records WHICH timeframe.
			"timeframe_alias" : self.timeframe_alias,
			# Stringified for the same reason as strategy_id: these are uuid.UUID on
			# every real run path. This str() is why the durable portfolio_id column
			# is a String — rehydrate's _resolve_portfolio_id is its parsing inverse.
			"subscribed_portfolios" : [str(pid) for pid in self.subscribed_portfolios],
			"is_active" : self.is_active,
			"sizing_policy" : repr(self.sizing_policy),
			"direction" : self.direction.value,
			"allow_increase" : self.allow_increase,
			"max_positions" : self.max_positions,
			"sltp_policy" : repr(self.sltp_policy) if self.sltp_policy is not None else None,
		})
		return snapshot

	def _invalidate_to_dict_cache(self) -> None:
		# ANY setter that mutates a DECLARED param — anything serialized in
		# _build_to_dict_snapshot other than is_active/subscribed_portfolios — MUST
		# call this, or to_dict serves a stale snapshot forever. ``reconfigure`` is
		# currently the only such setter.
		self._to_dict_static_cache = None

	def __str__(self) -> str:
		# The alias, not self.timeframe — the latter is a timedelta by this point.
		return f'{self.name}_{self.timeframe_alias}'

	def __repr__(self) -> str:
		return str(self)

	@abstractmethod
	def generate_signal(self, ticker: str) -> SignalIntent | None:
		"""
		Evaluate market data for ``ticker`` and return a trading intent.

		The pure-alpha contract. No market data is passed in: by the time this runs
		the handler has already pushed ``ticker``'s latest completed bar through
		``update(ticker, bar)`` and gated on ``is_ready(ticker)``. A concrete strategy
		reads its declared handles (``self.short_sma[-1]``) and the per-symbol
		decision anchors (``self.now`` / ``self.current_bar``, or
		``self.bar_count(ticker)`` / ``self.latest_bar(ticker)`` when it declares no
		indicators), then returns a ``SignalIntent`` — typically via the ``buy()`` /
		``sell()`` sugar — or ``None`` when there is nothing to do.

		No queue, no event construction, no portfolio knowledge.
		"""
		raise NotImplementedError("Should implement generate_signal()")

	def _intent(self, ticker: str, action: Side, order_type: OrderType,
			entry_price: float | Decimal | None,
			sl: float | Decimal | None,
			tp: float | Decimal | None,
			exit_fraction: Decimal) -> SignalIntent:
		"""
		Shared factory behind all six buy/sell sugar methods.

		``price`` is keyword-only on the limit/stop sugar so an illegal
		``(order_type, price)`` combination is unrepresentable by construction.

		``sl`` / ``tp`` / ``entry_price`` enter the Decimal domain via ``to_money``,
		NEVER ``Decimal(float)``. ``None`` means "not declared" for sl/tp, and
		"MARKET, fills at the decision-bar close" for entry_price.
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
		"""MARKET BUY intent for ``ticker`` — fills at the decision-bar close."""
		return self._intent(ticker, Side.BUY, OrderType.MARKET,
			None, sl, tp, exit_fraction)

	def sell(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""MARKET SELL intent for ``ticker`` — fills at the decision-bar close."""
		return self._intent(ticker, Side.SELL, OrderType.MARKET,
			None, sl, tp, exit_fraction)

	def buy_limit(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""LIMIT BUY intent for ``ticker`` resting at ``price``."""
		return self._intent(ticker, Side.BUY, OrderType.LIMIT,
			price, sl, tp, exit_fraction)

	def buy_stop(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""STOP BUY intent for ``ticker`` triggering at ``price``."""
		return self._intent(ticker, Side.BUY, OrderType.STOP,
			price, sl, tp, exit_fraction)

	def sell_limit(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""LIMIT SELL intent for ``ticker`` resting at ``price``."""
		return self._intent(ticker, Side.SELL, OrderType.LIMIT,
			price, sl, tp, exit_fraction)

	def sell_stop(self, ticker: str, *, price: float | Decimal,
			sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""STOP SELL intent for ``ticker`` triggering at ``price``."""
		return self._intent(ticker, Side.SELL, OrderType.STOP,
			price, sl, tp, exit_fraction)

	def subscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
		# Idempotent: a duplicate subscription fans the same intent out to one
		# portfolio TWICE in on_bar — two SignalEvents, two orders, one decision.
		if portfolio_id not in self.subscribed_portfolios:
			self.subscribed_portfolios.append(portfolio_id)

	def unsubscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
		# Idempotent: list.remove raises ValueError on a double-unsubscribe or a
		# never-subscribed id, which surfaces as a noisy ErrorEvent in live mode.
		if portfolio_id in self.subscribed_portfolios:
			self.subscribed_portfolios.remove(portfolio_id)

	def activate_strategy(self) -> None:
		self.is_active = True

	def deactivate_strategy(self) -> None:
		self.is_active = False
