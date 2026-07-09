"""Look-ahead-safe backtest bar feed — THE bar-timing contract (M5-01/M5-03).

This module is the single enforcement point and the single written home of
the engine's bar-timing contract (D-01..D-05, RESEARCH Pattern 1). Every
component is tested against these seven rules; look-ahead safety is an
ENGINE invariant enforced in the window slice below — never a strategy
responsibility.

The bar-timing contract
-----------------------

1. **Bars are stamped by open time** (D-04). The bar stamped ``T`` covers
   the interval ``[T, T + tf_base)`` (Binance kline / CCXT / TradingView
   convention — what the Phase 8 external engines will see).
2. **The tick at ``T`` means "the bar stamped ``T`` just closed."** The
   wall-clock semantics of the tick are ``T + tf_base``, but it is
   labeled ``T``.
3. **Decision visibility at tick ``T``:** all base bars stamped ``<= T``
   (every one of them is closed by rule 2). The same-timeframe window is
   the last ``N`` bars stamped ``<= T`` — both branches obey the same
   "last closed bar <= T" rule (D-02).
4. **Resampled visibility at tick ``T``:** a resampled bucket stamped
   ``B`` (``label='left'``, ``closed='left'``, covering ``[B, B + TF)``)
   is visible iff its last base bar has closed:
   ``B + TF <= T + tf_base``, equivalently ``B <= T - TF + tf_base``.
   The forming bucket is INVISIBLE. (Worked example: base 1d, TF = 7d,
   tick T = Sun Jan 7. Bucket B = Mon Jan 1 covers Jan 1-7; its last base
   bar is stamped Jan 7 = T and closed at the tick -> visible. At
   T = Sat Jan 6 it is NOT visible.) Rules 3 and 4 coincide when
   ``TF == tf_base``.
5. **Fills land at the next open** (D-01): a market order decided at tick
   ``T`` rests in the book and fills at the open of the bar stamped
   ``T + tf_base``, at tick ``T + tf_base``, with
   ``FillEvent.time = T + tf_base``.
6. **Equity at tick ``T``** = cash + positions valued at the close of the
   bar stamped ``T`` (D-05, close-marked).
7. **Last-bar edge:** orders decided on the final tick never fill — there
   is no next bar. Documented, not special-cased.

Replaces ``data_provider.get_resampled_bars``, whose resampled-branch upper
bound ``time + timeframe`` was the #21 look-ahead (future bars leaked into
the decision window), and whose per-tick ``resample`` was the dominant
hot-loop cost (#4). Here resampled frames are computed ONCE per
(ticker, timeframe) and the per-tick path is a pure ``searchsorted`` slice
(M5-03 — zero resample calls per tick).

Purity: like ``MatchingEngine``, the slice path has NO dependency on the
event queue, performs no network access and no store writes, and is fully
deterministic given the store frames. The logger is bound at construction
only; the per-tick QUERY path (window/megaframe/current_bars) does not
log. The one queue-aware seam is the BarEvent FACTORY
(``generate_bar_event``, relocated from the deleted dynamic universe —
Plan 07-02, D-20): the data engine produces the per-tick BarEvent and may
log the missing-ticker warning (RESEARCH OQ4).
"""

import functools
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import numpy as np
import pandas as pd

from itrader.core.bar import Bar
from itrader.core.exceptions import (
    ConfigurationError,
    MalformedDataError,
    MissingPriceDataError,
)
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.logger import get_itrader_logger
from itrader.price_handler.store.base import PriceStore
from itrader.universe import is_active

from .base import BarFeed, assert_update_trigger

# OHLCV aggregation spec for resampled buckets (RESEARCH Pattern 2,
# verified against pandas 2.3.3).
_AGG = {"open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}


# D-01 (PERF-06): memoize the per-call offset-alias string compute — it fires
# ONCE per distinct timeframe across __init__/precompute/the per-tick window()
# path. timedelta is hashable; functools.cache does NOT cache exceptions, so the
# raise-on-unsupported ValueError guard inside is preserved (RESEARCH Pitfall 4).
# The function BODY is byte-unchanged — only this decorator was added.
# CACHE-CLASS: (c) pure-function memo — see docs/CACHE-CLASSIFICATION.md
@functools.cache
def _offset_alias(timeframe: timedelta) -> str:
    """Map a timeframe to its canonical pandas offset alias.

    The Feed OWNS this map (Pitfall 2): the legacy ``outils.time_parser``
    timedelta-to-string helper must NEVER be reused for resample rules — it
    produces ``'30m'`` for minutes, which pandas 2.3.3 parses as MONTH-END
    and deprecates with a FutureWarning (a test error under
    ``filterwarnings=["error"]``).

    Mapping: minutes -> ``'min'``, hours -> ``'h'``, days -> ``'D'``;
    weeks resolve through the day branch as ``f'{n*7}D'`` (data-anchored —
    never ``'W'``, which anchors to Sunday with right labels).

    Parameters
    ----------
    timeframe : timedelta
        The bar timeframe to canonicalize.

    Returns
    -------
    str
        The pandas offset alias, e.g. ``'30min'``, ``'4h'``, ``'7D'``.

    Raises
    ------
    ValueError
        For unsupported units — anything not a whole number of minutes
        (months are not representable as a timedelta and are unsupported).
    """
    total = timeframe.total_seconds()
    seconds = int(total)
    if seconds <= 0 or seconds != total:
        raise ValueError(
            f"unsupported resample timeframe {timeframe!r} — must be a "
            "positive whole number of minutes/hours/days/weeks")
    if seconds % 86400 == 0:
        return f"{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    raise ValueError(
        f"unsupported resample timeframe {timeframe!r} — supported units "
        "are minutes, hours, days and weeks (months are not supported)")


def _readonly_master(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a SINGLE-BLOCK float64 frame with its values buffer read-only (D-09).

    The PERF-06 read-only enforcement: lock the underlying numpy buffer so a
    per-tick ``window()`` VIEW inherits read-only and a consumer in-place
    mutation raises ``ValueError(read-only)`` instead of silently poisoning a
    future tick (RESEARCH Pattern 1, verified pandas 2.3.3 / numpy 2.2.6).

    Two steps, both byte-identity-preserving:

    1. **Consolidate to a single block.** The store's canonical OHLCV frame is
       NOT always a single homogeneous float64 block — ``read_csv`` + the
       ``astype(float)`` + ``.loc`` window slice can leave it MULTI-block (e.g.
       4×N and 1×N). On a multi-block frame ``to_numpy(copy=False)`` returns a
       fresh CONSOLIDATED COPY, so locking individual block buffers would NOT
       be observable through ``to_numpy`` and a consumer's
       ``view.to_numpy(copy=False)[i,j] = x`` would write to a throwaway copy
       (no protection, no leak — but the guarantee is unobservable). A plain
       ``frame.copy()`` consolidates to ONE block while preserving values,
       float64 dtype, the tz-aware ``DatetimeIndex`` and column set+order
       byte-identically (``assert_frame_equal`` passes). A frame that is
       already single-block is copied harmlessly.
    2. **Lock the single block's buffer.** For the consolidated single-block
       frame ``to_numpy(copy=False)`` returns a non-owning VIEW whose ``.base``
       IS the block's writeable buffer — the flag must be set on that base
       buffer, NOT on the returned view (a view carries its own ``writeable``
       flag; clearing it leaves the buffer writeable). The ``np.shares_memory``
       assert proves the handle aliases the frame's own buffer (RESEARCH
       Pattern 1 caveat — ``to_numpy(copy=False)`` is not contractually
       zero-copy); after the ``copy()`` consolidation it always does.

    ``resample``/``searchsorted``/``iterrows`` and the ``ta`` reads all work on
    a non-writeable frame — no D-09 per-view fallback is triggered.
    """
    master = frame.copy()  # consolidate to a single block (byte-identical)
    arr = master.to_numpy(copy=False)
    # Walk to the buffer the frame actually owns: the block buffer is `arr.base`
    # for a non-owning view, else `arr` itself.
    buffer: "np.ndarray[Any, np.dtype[Any]]" = (
        arr if arr.flags.owndata else arr.base)
    assert np.shares_memory(buffer, master.to_numpy(copy=False)), (
        "to_numpy(copy=False) did not alias the frame's own buffer after "
        "consolidation — read-only flag would not take effect (D-09 fallback)")
    buffer.flags.writeable = False
    return master


class BacktestBarFeed(BarFeed):
    """Precompute-then-slice backtest feed (M5-01/M5-03/M5-05).

    Pulls every base frame from the store at construction, resamples once
    per (ticker, timeframe) — eagerly via ``precompute`` from strategy
    declarations, lazily-memoized on first access for undeclared timeframes
    (screener/megaframe path) — and serves per-tick windows as O(log n)
    positional slices under the completed-bars visibility rule (module
    docstring, rule 4).

    Parameters
    ----------
    store : PriceStore
        The canonical OHLCV store; its frames seed the cache at the base
        timeframe. Read-only access (FR6) — the feed never writes.
    base_timeframe : timedelta
        The timeframe of the store's base bars (``tf_base`` in the
        contract), e.g. ``timedelta(days=1)`` for the golden dataset.
    """

    def __init__(self, store: PriceStore, base_timeframe: timedelta) -> None:
        self._base_timeframe = base_timeframe
        self._base_alias = _offset_alias(base_timeframe)
        self._symbols: list[str] = store.symbols()

        # Precomputed frames (working state) keyed by (ticker, canonical
        # timeframe string) — base frames from store.read_bars seed the
        # cache; resampled frames memoize on precompute()/first access.
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        # Per-ticker [first_bar, last_bar] availability span (D-01 span model),
        # cached ONCE here from the SAME loaded frame the slice path reads
        # (M5-03 compute-once — zero extra store reads). Reading index[-1] at
        # wiring time is availability metadata (the listing/delisting calendar),
        # NOT a decision-price look-ahead — the slice path is unchanged (the
        # 7-rule contract above). Bounds are kept as the SAME tz-aware type the
        # tick carries (pd.Timestamp), so is_active's <= comparison against the
        # tz-aware TimeEvent.time never raises TypeError under
        # filterwarnings=["error"] (RESEARCH Pitfall 2), mirroring how
        # current_bars searchsorts against the tz-aware time.
        self._spans: dict[str, tuple[datetime, datetime]] = {}
        # Eager-materialized {ticker: {time: Bar}} map (D-07) — every base
        # row's Bar is built ONCE here at construction via the UNCHANGED
        # Bar.from_row, alongside _frames/_spans, over the SAME loaded frame
        # the slice path reads (mirrors the already-blessed _spans precompute:
        # batch transform at init, not a per-tick cost). current_bars(time)
        # below is then a pure dict lookup — no per-tick searchsorted/iloc/
        # Bar.from_row.
        #
        # HONEST D-09 rationale: the win is "structural hot-loop de-pandas,
        # bit-identical" — it removes pandas iloc/searchsorted + per-tick Bar
        # object churn from the hot loop and front-loads Bar.from_row to init.
        # It does NOT reduce the Decimal-conversion count: each (ticker, time)
        # row is converted exactly once across the run either way, so this
        # front-loads the SAME conversions, it does not eliminate them. No
        # lazy memoization (D-08): each (ticker, time) is queried exactly once,
        # so a cache would serve zero hits.
        # CACHE-CLASS: (a) hot-path data cache [family: _frames/_spans/_prebuilt/_cursor/_cursor_cut/_newest_bars] — see docs/CACHE-CLASSIFICATION.md
        self._prebuilt: dict[str, dict[datetime, Bar]] = {}
        for ticker in self._symbols:
            # D-09 (PERF-06): store a SINGLE-BLOCK, read-only master so every
            # per-tick window VIEW inherits a non-writeable buffer and any
            # in-place mutation fails loudly (ValueError) instead of silently
            # poisoning a future tick (the look-ahead invariant, hard-enforced
            # at the feed source — subsumes D-02 view-safety). The consolidation
            # is byte-identical to the store frame (Pitfall 3: the index[0]/[-1]
            # reads and frame.itertuples() below both work on a non-writeable
            # frame). The store frame is returned UNTOUCHED — we lock our copy.
            frame = _readonly_master(store.read_bars(ticker))
            # WR-01: an empty store frame (sparse universe / mis-keyed CSV)
            # would make frame.index[0] raise a bare IndexError naming nothing.
            # Fail loud with a typed, ticker-named error.
            if frame.empty:
                raise MissingPriceDataError(
                    ticker, "store returned an empty frame for ticker")
            self._frames[(ticker, self._base_alias)] = frame
            self._spans[ticker] = (frame.index[0], frame.index[-1])
            # Req 3 (08-03, Claude's-Discretion): build the {ts: Bar} prebuild
            # via itertuples instead of frame.iterrows(). iterrows() materializes
            # one throwaway pandas Series PER ROW (~69k across the golden run);
            # itertuples yields a lightweight NamedTuple per row with no Series
            # allocation. Body byte-unchanged: str() parity verified — for the
            # float64 OHLCV columns str(native scalar) == str(series_value), so
            # the Bar.from_row D-14 Decimal(str(...)) string path receives a
            # byte-identical string (test_bar_prebuild_equivalence pins this
            # field-for-field + an explicit str_parity assertion). The column
            # labels (open/high/low/close/volume) are valid identifiers, so the
            # NamedTuple exposes them as attributes (r.open, ...); r.Index is the
            # timestamp. Construct Bar directly via the SAME Decimal(str(...))
            # path so the D-14 contract is preserved without re-routing through a
            # Series-shaped mapping.
            # WR-02 (08-REVIEW): the str() parity that makes itertuples
            # byte-identical to the iterrows path is a float64-column property
            # (verified for all golden values, but dataset-specific, not
            # structurally enforced). Assert the precondition so a future non-float
            # OHLCV dtype (object/Decimal/int) fails LOUD here instead of silently
            # feeding a differently-formatted str() into the Bar Decimal(str(...))
            # path and drifting the oracle.
            _ohlcv = ("open", "high", "low", "close", "volume")
            _bad_dtypes = {
                c: str(frame[c].dtype)
                for c in _ohlcv
                if not pd.api.types.is_float_dtype(frame[c])
            }
            if _bad_dtypes:
                raise MalformedDataError(
                    ticker,
                    f"itertuples prebuild requires float OHLCV columns "
                    f"(str-parity precondition); got non-float dtypes: {_bad_dtypes}",
                )
            self._prebuilt[ticker] = {
                r.Index: Bar(
                    time=r.Index,
                    open=Decimal(str(r.open)),
                    high=Decimal(str(r.high)),
                    low=Decimal(str(r.low)),
                    close=Decimal(str(r.close)),
                    volume=Decimal(str(r.volume)),
                )
                for r in frame.itertuples(index=True)
            }

        # D-10 (PERF-06): monotonic forward-cursor state for window(), keyed
        # (ticker, alias) EXACTLY like self._frames (Pitfall 5 — keying on
        # ticker alone would share one cursor across two timeframes). The
        # backtest asof cutoff advances monotonically per (ticker, alias), so
        # window() steps a cached position FORWARD over frame.index.asi8 int64
        # ns instead of re-running searchsorted every tick (the 13.2% W2
        # hotspot). _cursor holds the last forward position; _cursor_cut holds
        # the last cutoff (int64 ns) so a backwards/jumped cutoff is detected
        # (cutoff_i8 < last_cut) and SAFE-REBUILT via searchsorted — never
        # trusting stale state, never leaking a future bar (D-10 reset-safety).
        self._cursor: dict[tuple[str, str], int] = {}
        self._cursor_cut: dict[tuple[str, str], int] = {}

        # Shared recent-bars newest-row cache (P5-D16 / G5 — newest-bar provision
        # only; the deep multi-bar buffer is DEFERRED, P5-D16/P5-D22). Written by
        # the SINGLE per-symbol walk in current_bars (P5-D16a) that also builds the
        # BarEvent payload — one source of truth, NOT a second parallel pass.
        # Read back via newest_bar(ticker). Empty until the first tick produces a
        # bar for a symbol (newest_bar returns None before then). This is the
        # newest-bar floor of the cache (capacity NEWEST_BAR_ONLY); a deep buffer
        # lands with the first raw-bar consumer registered through the ABC seam.
        self._newest_bars: dict[str, Bar] = {}

        # Run-path bindings for the BarEvent factory (Plan 07-02, D-20) —
        # set by the trading system at wiring time via ``bind``. The queue
        # is optional (unbound: the factory RETURNS the event); membership
        # is used ONLY for the missing-ticker warning (RESEARCH OQ4).
        self.global_queue: "Optional[EventBus]" = None
        self.membership: list[str] = []

        self.logger = get_itrader_logger().bind(component="BacktestBarFeed")
        self.logger.info(
            'Backtest bar feed initialized (%d symbols, base timeframe %s)',
            len(self._symbols), self._base_alias)

    # -- Uniform config surface (COMP-02 / D-10 — interface-conformance) ------

    def update_config(self, updates: dict[str, Any]) -> None:
        """Interface-conformance RAISE — the feed cannot hot-swap mid-run (D-10).

        COMP-02's uniform ``update_config(self, updates: dict[str, Any]) -> None``
        surface. The backtest feed has NO Pydantic config model — D-09 forbids
        inventing a config model just to force a literal model_validate here.
        ``base_timeframe`` is held as a plain construction attr that ripples
        into ``_base_alias`` and the window cutoff math — a "replace, not a
        hot-swap" (the live replace path is N+4).

        This method exists PURELY to satisfy the uniform interface and to fail
        LOUDLY (Pitfall 3 — never a silent no-op): it always raises
        ``ConfigurationError`` for any update. ``base_timeframe`` is named as
        the unsafe key so the future web layer catches the one iTrader type
        (D-08) and surfaces an honest "replace the feed" message.

        Parameters
        ----------
        updates: `dict[str, Any]`
            Ignored — the feed cannot apply any update in place.

        Raises
        ------
        ConfigurationError
            Always — the backtest feed is not runtime-reconfigurable.
        """
        raise ConfigurationError(
            config_key="base_timeframe",
            reason="cannot hot-swap base_timeframe in backtest — replace the feed",
        )

    # -- Precompute (M5-03 — resample once, out of the hot loop) --------------

    def precompute(self, tickers: list[str], timeframe: timedelta) -> None:
        """Eagerly resample and memoize frames for a (tickers, timeframe) set.

        Called at run-init from registered strategy declarations (06-05).
        Timeframes not declared here lazily compute-and-memoize on first
        ``window``/``megaframe`` access — either way each (ticker,
        timeframe) pair is resampled at most ONCE (M5-03).

        Parameters
        ----------
        tickers : list[str]
            The tickers to precompute.
        timeframe : timedelta
            The target bar timeframe.
        """
        alias = _offset_alias(timeframe)
        for ticker in tickers:
            self._resampled_frame(ticker, alias)

    def _resampled_frame(self, ticker: str, alias: str) -> pd.DataFrame:
        """Return the memoized frame for (ticker, alias), resampling once.

        ``label='left', closed='left'`` stamps each bucket by its open time
        (rule 1). NOTE (Pitfall 1): pandas KEEPS the trailing forming
        bucket — visibility is enforced at slice time in ``window``, never
        by resample alone.
        """
        key = (ticker, alias)
        frame = self._frames.get(key)
        if frame is not None:
            return frame
        base = self._frames.get((ticker, self._base_alias))
        if base is None:
            raise MissingPriceDataError(
                ticker, "ticker not loaded in BacktestBarFeed")
        resampled = base.resample(alias, label="left", closed="left").agg(_AGG)
        # WR-01: a resample yielding an empty result would make downstream
        # index reads raise a bare IndexError naming nothing. Fail loud with a
        # typed, ticker-named error.
        if resampled.empty:
            raise MissingPriceDataError(
                ticker, f"resample to {alias!r} produced an empty frame")
        # D-09 (PERF-06): resample produced a NEW writeable frame, so lock it
        # (single-block + read-only buffer) before any window() view aliases it.
        # Same one-time, out-of-hot-loop mark as the __init__ base load.
        resampled = _readonly_master(resampled)
        self._frames[key] = resampled
        return resampled

    # -- BarEvent factory (relocated from the legacy universe — Plan 07-02, D-20) --

    def bind(self, global_queue: "Optional[EventBus]",
             membership: list[str]) -> None:
        """Bind the run-path event sink and membership set (wiring time).

        Called once by the trading system after membership is derived
        (``itrader.universe.derive_membership``). ``global_queue`` may be
        ``None`` — the factory then returns the BarEvent instead of
        enqueueing it.

        Parameters
        ----------
        global_queue : Optional[queue.Queue]
            The global events queue, or ``None`` for the return contract.
        membership : list[str]
            The derived tradable symbol set — used ONLY for the
            missing-ticker warning loop (RESEARCH OQ4).
        """
        self.global_queue = global_queue
        self.membership = membership

    def generate_bar_event(self, time_event: TimeEvent) -> Optional[BarEvent]:
        """Generate the per-tick BarEvent from the feed's own bar facts.

        The relocated legacy-universe ``generate_bar_event`` body (D-20 —
        the data engine owns BarEvent production, LEAN/Nautilus shape):
        wrap ``current_bars(time)`` in a BarEvent, warn for any membership
        ticker absent from the produced bars (sparse universe), and either
        enqueue (queue bound: returns ``None``) or return the event.

        Parameters
        ----------
        time_event : TimeEvent
            Simulation-clock event carrying the last closed bar time.
        """
        bars = self.current_bars(time_event.time)

        for ticker in self.membership:
            # D-04: the feed is the SINGLE span-aware owner of absence
            # observability. WARN only on a true mid-life gap (T inside the
            # ticker's listed [first,last] span but no bar at T — a real
            # data-quality anomaly); stay SILENT for expected absence
            # (pre-listing / post-end — T outside the span). Log-only: bars,
            # current_bars, and the BarEvent below are untouched (oracle-dark).
            if ticker not in bars and is_active(self._spans, ticker, time_event.time):
                self.logger.warning(
                    'Bar feed: mid-life gap for %s at %s (active, no bar)',
                    ticker, str(time_event.time))

        bar_event = BarEvent(time=time_event.time, bars=bars)

        if self.global_queue is not None:
            self.global_queue.put(bar_event)
            return None
        return bar_event

    # -- Per-tick fact lookup (BarEvent payload, D-15) ------------------------

    def current_bars(self, time: datetime) -> dict[str, Bar]:
        """Return the ``Bar`` facts stamped exactly ``time``, keyed by ticker.

        Pure dict lookup into the prebuilt ``{ticker: {time: Bar}}`` map (D-07
        — built once in ``__init__`` via the UNCHANGED ``Bar.from_row``, Decimal
        string path, D-14): NO per-tick ``searchsorted``/``iloc``/``Bar.from_row``.
        Tickers with no bar stamped exactly ``time`` are ABSENT from the dict
        (sparse universe, D-15) — the same exact-stamp existence semantics the
        old ``index[pos] == time`` guard enforced, now ``time in prebuilt``.
        The close of the returned ``Bar`` is the value the portfolio marks
        equity with at the tick (rule 6).

        D-09: this is "structural hot-loop de-pandas, bit-identical" — the Bar
        values are identical to the old per-tick ``Bar.from_row`` path; the
        conversions were front-loaded to ``__init__``, not eliminated.

        G5 unify (P5-D16a): this SINGLE existing per-symbol walk ALSO writes the
        shared recent-bars newest-row cache (``self._newest_bars[ticker] = bar``)
        — one walk, not two. The cache row and the returned ``BarEvent`` payload
        come from the SAME ``bar`` for the SAME tick, so ``newest_bar(ticker)``
        is provably ``bars[ticker]`` for every present symbol (one source of
        truth). No second per-symbol loop is added for the cache write — it rides
        this same walk.
        """
        bars: dict[str, Bar] = {}
        for ticker in self._symbols:
            bar = self._prebuilt[ticker].get(time)
            if bar is not None:
                bars[ticker] = bar
                self._newest_bars[ticker] = bar  # G5: same walk feeds the cache
        return bars

    # -- Shared recent-bars: newest-bar provision (P5-D16 / G5) ----------------

    def newest_bar(self, ticker: str) -> Bar | None:
        """Return the newest completed ``Bar`` written for ``ticker``, or ``None``.

        Pure dict read of the G5-written newest-row cache (``_newest_bars``): the
        value the SINGLE ``current_bars`` walk last stored for ``ticker`` (P5-D16a
        — same ``bar`` as the ``BarEvent`` payload, one source of truth). Returns
        ``None`` before the symbol's first bar. The deep multi-bar history is
        DEFERRED (P5-D16/P5-D22) — this is the newest-bar provision only.
        """
        return self._newest_bars.get(ticker)

    def assert_update_trigger(self, timeframes: Iterable[timedelta]) -> None:
        """G1 update-trigger wiring guard (P5-D16b) — asserts the causality order.

        Delegates to the interface-only ``base.assert_update_trigger`` with THIS
        feed's ``base_timeframe``: every consumed timeframe must satisfy
        ``base_timeframe <= min(timeframe)`` so no consumer drives off a bar the
        base feed has not produced (a non-causal sub-base trigger). For golden
        SMA_MACD (``1d == base == 1d``) this collapses to "every tick" and holds
        trivially. The full multi-timeframe consolidator is DEFERRED.

        Parameters
        ----------
        timeframes : Iterable[timedelta]
            Every timeframe a registered consumer drives its update off.

        Raises
        ------
        ValueError
            If ``base_timeframe > min(timeframe)`` for any consumed timeframe.
        """
        assert_update_trigger(self._base_timeframe, timeframes)

    # -- History windows (strategy push path, D-20) ---------------------------

    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame:
        """Return the last ``max_window`` COMPLETED bars visible at ``asof``.

        The completed-bars cutoff implements rule 4:
        ``cutoff = asof - timeframe + base_timeframe`` (degenerating to
        ``asof`` when ``timeframe == base_timeframe``, rule 3 — both
        branches agree, D-02); a bucket stamped ``B`` is included iff
        ``B <= cutoff``. The cutoff is resolved by a per-(ticker, alias)
        monotonic forward cursor over the index int64 ns (D-10, replacing the
        per-tick ``searchsorted``); zero resample calls on this path (M5-03).

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.
        timeframe : timedelta
            The bar timeframe of the requested window.
        max_window : int
            Maximum number of bars to return.
        asof : datetime
            The decision tick (from the BarEvent — D-20).

        Returns
        -------
        pd.DataFrame
            float64 OHLCV frame (D-17), tz-aware ``DatetimeIndex``
            preserved (SMA_MACD slices by time), completed bars only.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the feed (FR7).
        ValueError
            If ``timeframe`` maps to no supported pandas offset alias.
        """
        # PERF-06 (D-01/D-06/D-07/D-09/D-12): return a READ-ONLY VIEW on the
        # cached master frame instead of materializing a fresh wrapper every
        # tick (06-01, kept). On the homogeneous float64 single-block OHLCV
        # frame frame.iloc[start:pos] is ALREADY a view — no large copy ever
        # happened. The PIVOT (D-10/D-11, post-profile 06-04) sits ON TOP of
        # that view: the real reducible per-tick cost is the fresh
        # searchsorted over the full index every tick × every symbol (13.2% of
        # W2), now replaced by the monotonic int64 forward cursor below. The
        # iloc slice is KEPT cursor-only (D-11): every cheaper-slice candidate
        # measured SLOWER than iloc on this single-block frame (reconstruct 9.2
        # vs iloc 7.3 µs; take 21 µs) and D-07 forbids pd.DataFrame(...)
        # reconstruction (tz/dtype/column-order drift) — D-11's separate
        # cheaper-slice idea is recorded as investigated + empirically
        # infeasible, superseded by research; the 7.9% iloc cost is accepted
        # via the D-15 ship-and-reframe fallback (06-05).
        alias = _offset_alias(timeframe)
        frame = self._resampled_frame(ticker, alias)
        cutoff = asof - timeframe + self._base_timeframe
        # WR-01 guard: the forward-step branch compares cutoff_i8 (raw ns since
        # the UTC epoch) against the tz-aware index's asi8. A tz-naive cutoff
        # would skew that int64 compare by the tz offset and SILENTLY return a
        # wrong cursor (leak/hide a bar), whereas the cold/rebuild searchsorted
        # path raises TypeError on a tz-naive↔tz-aware compare. Assert
        # tz-awareness once so BOTH branches fail loudly and identically — the
        # engine path always passes tz-aware asof (TimeEvent.time), so this only
        # restores the loud-fail backstop for a future tz-naive caller/test.
        if getattr(cutoff, "tzinfo", None) is None:
            raise ValueError(
                "window() asof must be tz-aware to match the tz-aware index; "
                f"got {asof!r}")
        # D-10: per-(ticker, alias) monotonic forward cursor over int64 ns —
        # byte-identical to int(frame.index.searchsorted(cutoff, side="right"))
        # on every reachable cutoff (VERIFIED on-grid + mid-gap; proven by the
        # D-16 drift suite). The int64 path is load-bearing: iv_i8[pos] <=
        # cutoff_i8 is 0.14 µs/step; a pandas-Timestamp compare (2.0 µs) or a
        # per-tick np.datetime64 conversion (3.3 µs ≈ the searchsorted it
        # replaces) deliver NO win — use asi8 + Timestamp.value (Pitfall 1).
        # The `<=` (not `<`) reproduces searchsorted side="right" exactly: pos
        # is count(index <= cutoff), the exclusive-right cutoff (rule 4).
        key = (ticker, alias)
        n = len(frame.index)
        iv_i8 = frame.index.asi8          # zero-copy int64 ns view (UTC; fresh wrapper, shared buffer)
        # O(1) int64 ns; == asi8[k] for the tz-aware index (Timestamp.value).
        # asof arrives as a pd.Timestamp at run time but is typed `datetime`, so
        # the pd.Timestamp(...) wrap is a no-op box that keeps mypy --strict
        # happy (datetime has no `.value`) without a per-tick datetime64 convert.
        cutoff_i8 = pd.Timestamp(cutoff).value
        last_pos = self._cursor.get(key)
        last_cut = self._cursor_cut.get(key)
        if last_pos is None or last_cut is None or cutoff_i8 < last_cut:
            # COLD (key unseen) or NON-MONOTONIC (backwards/jumped cutoff —
            # universe re-entry re-issuing an earlier asof, resampled cutoffs):
            # SAFE FULL REBUILD via searchsorted. Never trust stale state, never
            # leak a future bar; silent rebuild (NOT fail-loud — a non-monotonic
            # cutoff is legitimate, RESEARCH A3). Byte-identical to today.
            pos = int(frame.index.searchsorted(cutoff, side="right"))
        else:
            # MONOTONIC forward step from the cached position (0.14 µs/step).
            pos = last_pos
            while pos < n and iv_i8[pos] <= cutoff_i8:
                pos += 1
        self._cursor[key] = pos
        self._cursor_cut[key] = cutoff_i8
        start = max(0, pos - max_window)
        if start >= pos:
            # D-06: empty window (cutoff at frame start) returns the size-0
            # slice UNCHANGED — bypass the view/read-only machinery entirely,
            # preserving byte-identical empty semantics base.py relies on.
            return frame.iloc[pos:pos]
        # D-07: slice the existing (already non-writeable, single-block) float64
        # master — do NOT reconstruct via pd.DataFrame(...) (tz/dtype/column-order
        # drift risk; byte-identity is the hard constraint) and do NOT re-copy
        # (that would defeat the view return). The slice is a VIEW that aliases
        # the master's read-only buffer, so it inherits writeable=False for free
        # (D-09) — a consumer in-place mutation raises ValueError(read-only).
        return frame.iloc[start:pos]

    # -- Multi-symbol megaframe (screener path, D-19) --------------------------

    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame:
        """Return a multi-symbol close-price frame visible at ``asof`` (D-19).

        Per-symbol ``window`` close columns (named by symbol) concatenated
        with ``keys`` equal to the symbols ACTUALLY included — the FR8 key
        fix (the legacy ``to_megaframe`` keyed by ``self.prices.keys()``,
        misaligning columns whenever a symbol was dropped). The legacy
        tz-naive drop condition disappears: the store normalizes every
        frame tz-aware at load. A symbol with an empty window at ``asof``
        is excluded together with its key, loudly.

        Parameters
        ----------
        asof : datetime
            The decision tick (same visibility rule as ``window``).
        timeframe : timedelta
            The bar timeframe of the per-symbol windows.
        max_window : int
            Maximum number of bars per symbol.

        Returns
        -------
        pd.DataFrame
            Close columns keyed by included symbol, tz-aware index; empty
            frame if no symbol has a visible window.
        """
        closes: list[pd.Series] = []
        included: list[str] = []
        for symbol in self._symbols:
            frame = self.window(symbol, timeframe, max_window, asof)
            if frame.empty:
                self.logger.warning(
                    'Megaframe: excluding %s — no completed bars at %s',
                    symbol, asof)
                continue
            closes.append(frame["close"].rename(symbol))
            included.append(symbol)
        if not closes:
            return pd.DataFrame()
        return pd.concat(closes, axis=1, keys=included)
