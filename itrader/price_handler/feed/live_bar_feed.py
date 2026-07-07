"""LiveBarFeed — the live push-driven ring-buffer BarFeed (Phase 3, FEED-01/02/04).

The live sibling of ``BacktestBarFeed``: a second concrete ``BarFeed`` that,
instead of precomputing frames from a store, ingests confirm-gated ``ClosedBar``
dicts pushed from the Phase-2 ``OkxDataProvider`` and serves the same read-model
surface off a bounded ``deque`` ring per ``(symbol, timeframe)`` (FEED-01, D-09).

Unlike the backtest feed (``TimeEvent`` -> ``generate_bar_event`` pull, D-20), the
live feed emits a single-ticker ``BarEvent`` DIRECTLY onto ``global_queue`` the
moment a closed bar arrives (D-02/D-03/D-04) — the bar's arrival IS the event,
replacing ``TimeGenerator``'s driver role (FEED-05). ``generate_bar_event`` is kept
as a DORMANT no-op so the reserved TIME route (D-05) stays wired without crashing.

The genuinely novel logic (no backtest analog) is the FEED-04 monotonic guard in
``update()``: every incoming bar is classified against the last-delivered stamp
``L`` per ``(symbol, timeframe)`` — in-sequence deliver, gap backfill-and-replay,
duplicate drop, revision forward-only WARN+drop (no state mutation, D-07), stale
reject (D-06). An out-of-order or replayed bar can never rewind indicator state.

Thread model (D-02/D-19): all ``update()`` calls stay on the single connector
asyncio thread (single-writer ring/guard); only the MPSC-safe ``queue.Queue.put``
crosses to the engine thread — no lock needed.

Inertness: this module is LAZY-imported inside ``LiveTradingSystem.__init__`` only
and MUST NOT be pulled onto the backtest hot path (the recurring milestone gate).
It is deliberately NOT re-exported from the ``feed`` package barrel.

Indentation: 4 SPACES (the ``price_handler/feed/`` package convention) — NO tabs.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

import pandas as pd

from itrader.core.bar import Bar
from itrader.core.exceptions import (
    MalformedDataError,
    MissingPriceDataError,
    StateError,
)
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.logger import get_itrader_logger
from itrader.outils.time_parser import to_timedelta

from .bar_feed import _AGG, _offset_alias
from .base import BarFeed

if TYPE_CHECKING:
    # ClosedBar is a TypedDict — needed only for annotations. Guarding the import
    # keeps aiohttp/connector code out of this module's runtime import graph
    # (``from __future__ import annotations`` makes every annotation a lazy string).
    from itrader.price_handler.providers.okx_provider import ClosedBar

_NS_PER_MS = 1_000_000

# Warmup safety margin (D-10): a small FIXED additive over cache_capacity(), NOT a
# multiplier — the driver is a readiness threshold (RESEARCH §Warmup safety-margin
# survey; K = required_warmup + 5 absorbs the REST boundary-bar dedup slack).
_WARMUP_MARGIN = 5


class LiveBarFeed(BarFeed):
    """Push-driven ring-buffer ``BarFeed`` for the live path (FEED-01/02/04).

    Holds a bounded ``deque(maxlen=cache_capacity())`` ring per ``(symbol,
    timeframe)`` (D-09), constructs ``Bar`` facts with tz-aware venue-open time
    from confirm-gated ``ClosedBar`` dicts, and emits single-ticker ``BarEvent``s
    directly onto the bound queue. The data provider is held on the PRIVATE
    ``self._provider`` (may be ``None`` at construction) and injected
    post-construction ONLY through :meth:`set_provider` (D-01/D-13).

    Parameters
    ----------
    provider : Any
        The data provider exposing ``fetch_ohlcv_backfill(symbol, timeframe,
        since, limit) -> list[ClosedBar]`` for gap-backfill/warmup. May be
        ``None`` (the OKX provider is injected later via :meth:`set_provider`).
    base_timeframe : timedelta
        The base-bar timeframe of the subscribed stream (``tf_base``).
    """

    def __init__(self, provider: Any, base_timeframe: timedelta) -> None:
        # The data provider lives on the PRIVATE attr; set_provider is the only
        # public post-construction write path (no public ``provider`` attribute).
        self._provider: Any = provider
        self._base_timeframe = base_timeframe
        self._base_alias = _offset_alias(base_timeframe)
        # Bounded ring per (symbol, timeframe) — created lazily on first delivery
        # with maxlen=cache_capacity() (D-09: read at creation, NEVER cached at
        # __init__, so the 03-04 D-13 registration sizes it to 100).
        self._ring: dict[tuple[str, str], deque[Bar]] = {}
        # Monotonic-guard L-tracking: last-delivered open-time per (symbol, tf).
        self._last_delivered: dict[tuple[str, str], pd.Timestamp] = {}
        # Newest-bar provision (P5-D16 / G5) written by every delivery.
        self._newest_bars: dict[str, Bar] = {}
        # D-29 (WR-05): re-entrancy guard set for the duration of a loop-native
        # backfill replay. If update() detects a gap WHILE a replay is in progress
        # (an under-returning venue page with a hole inside the replayed range), it
        # fails loud instead of spawning a nested/overlapping backfill.
        #
        # WR-04 (07-09, D-14 hazard FIXED): the guard is now PER-THREAD scoped via
        # threading.local — it encodes "THIS thread's replay is active." The plain
        # instance bool it replaced was correct ONLY while replay and its nested
        # update() calls stayed on the single connector-loop thread; but update() is
        # also reachable from the ENGINE thread (warmup / backfill_on_resume), so an
        # engine-thread gap arriving mid connector-loop replay would read the
        # connector's True, be misclassified as a nested in-replay gap, and spuriously
        # HALT the connector. Thread-local storage makes the engine thread read its
        # OWN default (False), so the deferred concurrent-bar path (05.3-06) no longer
        # needs the "scope re-entrancy before enabling" caveat. Exposed through the
        # ``_replaying_backfill`` property (getter/setter) so the three call sites
        # (read / set-True / set-False) stay unchanged.
        self._replay_local = threading.local()
        # Run-path bindings (mirror bar_feed.py:334-335); set via bind().
        self.global_queue: "Optional[queue.Queue[Any]]" = None
        self.membership: list[str] = []
        self.logger = get_itrader_logger().bind(component="LiveBarFeed")
        self.logger.info(
            "Live bar feed initialized (base timeframe %s)", self._base_alias)

    # -- WR-04 per-thread replay re-entrancy guard ----------------------------

    @property
    def _replaying_backfill(self) -> bool:
        """True iff the CURRENT thread is inside a loop-native backfill replay (WR-04).

        Backed by ``threading.local``: the setter stashes ``active`` on the calling
        thread, and the getter defaults to ``False`` on any thread that never set it
        (the engine thread reads its OWN False even while the connector thread has
        set True). This keeps the D-29 interior-hole guard correct without a lock and
        without cross-thread poison — a backfill on one symbol/thread never
        misclassifies a legitimate gap on another thread.
        """
        return getattr(self._replay_local, "active", False)

    @_replaying_backfill.setter
    def _replaying_backfill(self, value: bool) -> None:
        self._replay_local.active = value

    # -- Provider -> feed seam (D-01/D-13) ------------------------------------

    def set_provider(self, provider: Any) -> None:
        """Inject the data provider post-construction (the ONLY public write path).

        The 03-04 composition root constructs the OKX provider AFTER the feed and
        wires it here. ``update()`` / warmup / gap-backfill read the PRIVATE
        ``self._provider``; there is deliberately NO public ``provider`` attribute
        (a bare ``feed.provider = x`` would create a dead attribute and leave
        ``self._provider`` ``None``).
        """
        self._provider = provider

    def bind(self, global_queue: "Optional[queue.Queue[Any]]",
             membership: list[str]) -> None:
        """Bind the run-path event sink + membership (mirror ``BacktestBarFeed.bind``).

        ``update()`` needs ``self.global_queue`` to ``put`` the ``BarEvent``.
        """
        self.global_queue = global_queue
        self.membership = membership

    # -- Bar construction (Decimal edge already crossed at the provider) -------

    @staticmethod
    def _build_bar(t: pd.Timestamp, cb: "ClosedBar") -> Bar:
        """Build a ``Bar`` straight from the Decimal ``ClosedBar`` fields.

        The OHLCV are ALREADY ``Decimal`` (the provider crossed the edge via
        ``to_money``) — never re-cast through float / ``Bar.from_row`` (D-14).

        Self-less by construction, so it is a ``@staticmethod`` (07-03 / D-03a): the
        ONE canonical ``ClosedBar`` → ``Bar`` conversion, reused read-only by
        ``OkxDataProvider.spawn_warmup`` (``LiveBarFeed._build_bar(t, cb)``) so the
        warmup bulk-transport path and the live ``update()`` path build byte-identical
        ``Bar`` facts — never a second bulk conversion.
        """
        return Bar(time=t, open=cb["open"], high=cb["high"], low=cb["low"],
                   close=cb["close"], volume=cb["volume"])

    # -- Ingestion — the FEED-04 monotonic-forward-only guard (D-06/D-07) ------

    def update(self, closed_bar: "ClosedBar") -> None:
        """Ingest one confirm-gated ``ClosedBar`` through the monotonic guard.

        Classifies the incoming open-time ``t`` against the last-delivered stamp
        ``L`` per ``(symbol, timeframe)`` (D-06 taxonomy):

        - ``L is None`` (first bar) or ``t == L + tf`` (in-sequence) → deliver.
        - ``t < L`` (stale) → reject + log, NO emit, no state mutation.
        - ``t == L`` (duplicate/revision) → identical values drop quietly;
          differing values are a forward-only revision (WARN + drop, NO state
          mutation — indicator state is never rewound, D-07).
        - ``t > L + tf`` (gap) → backfill the interior range ``[L+tf .. t-tf]``
          and replay each bar through ``update()``, THEN deliver ``t``.

        Every incoming bar AND every replayed backfill bar takes this one path
        (FEED-03 — no bulk fast-path). The gap recursion terminates because each
        replayed bar advances ``L`` by exactly one ``tf`` (no nested gap; a
        boundary re-send is absorbed by the duplicate branch, Pitfall 5). Stale /
        duplicate / revision are LOGGED, never raised — they are legitimate venue
        events. ``t`` is the venue open-time only (never ``datetime.now()``).
        """
        sym = closed_bar["symbol"]
        tf_str = closed_bar["timeframe"]
        tf = to_timedelta(tf_str)
        t = pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")
        last = self._last_delivered.get((sym, tf_str))
        if last is None:
            return self._deliver(sym, tf_str, t, closed_bar)
        if t < last:
            return self._reject_stale(sym, t, last)
        if t == last:
            return self._duplicate_or_revision(sym, tf_str, t, closed_bar)
        if t > last + tf:
            if self._replaying_backfill:
                # D-29 (WR-05): a gap detected WHILE a loop-native backfill replay is
                # in progress means the venue page under-returned (a hole INSIDE the
                # replayed range). Fail loud instead of spawning a nested/overlapping
                # backfill — the shape-independent structural stop against recursion.
                # The raise escalates through the provider's supervised-backfill error
                # path (_run_gap_backfill -> _on_gap_backfill_done -> connector halt).
                #
                # WR-04 (07-09, FIXED): `_replaying_backfill` encodes "THIS thread's
                # replay is active," NOT "any replay is active" — and it is now backed
                # by threading.local (a property over self._replay_local), so that
                # scoping is enforced rather than merely assumed. update() is also
                # reachable from the ENGINE thread (warmup / backfill_on_resume); with
                # the per-thread guard a legitimate engine-thread gap arriving mid
                # connector-loop replay reads its OWN thread-local False (not the
                # connector's True), so it is NOT misclassified as a nested in-replay
                # gap and does NOT spuriously HALT the connector. The previously
                # DEFERRED D-14 concurrent-bar path (05.3-06) therefore no longer needs
                # the "scope re-entrancy before enabling" caveat — it is scoped here.
                #
                # WR-02: carry BOTH {expected, got} coordinates so an operator triaging a
                # connector-fatal halt sees where in the interior the hole is without
                # cross-referencing logs (integer-ms, secret-free — matches the sibling
                # under-returning-page raise in _replay_and_deliver).
                raise MalformedDataError(
                    f"gap-backfill:{sym}/{tf_str}",
                    "gap detected during an in-progress backfill replay "
                    f"(expected in-sequence L+tf={int((last + tf).value // _NS_PER_MS)}, "
                    f"got ts={int(t.value // _NS_PER_MS)}) "
                    "— refusing a nested backfill")
            return self._fill_gap_and_deliver(
                sym, tf_str, last + tf, t - tf, t, closed_bar)
        if t == last + tf:
            return self._deliver(sym, tf_str, t, closed_bar)
        # WR-01: the remaining region is last < t < last + tf — an off-grid
        # timestamp (e.g. a sub-timeframe bar from a mis-subscribed channel or a
        # timeframe mismatch). Delivering it would set L off the tf-grid and make
        # every subsequent bar spuriously trip the gap branch. Reject explicitly:
        # WARN and DROP, with no delivery and no state mutation.
        self.logger.warning(
            "Off-grid bar for %s at %s (not L+tf, last-delivered=%s) — dropped "
            "(no delivery, no state mutation)", sym, str(t), str(last))

    # -- Backfill entry points — both replay one-by-one through update() -------

    def warmup(self, symbol: str, timeframe: str,
               depth: int | None = None) -> None:
        """Live-start warmup: REST-fetch ``depth`` bars and replay each via ``update()``.

        The FEED-03 warmup driver. When ``depth`` is not given it resolves to
        ``self.cache_capacity() + _WARMUP_MARGIN`` (D-10 — the derived ring depth
        plus a FIXED additive margin, RESEARCH §Warmup safety-margin survey; with the
        03-04 D-13 registration ``cache_capacity()`` is 100, so K >= 105 fetches
        enough bars that stateful indicators actually warm — otherwise
        ``calculate_signals`` short-circuits and the oracle produces zero trades,
        RESEARCH Pitfall 1).

        Every fetched ``ClosedBar`` is replayed one-by-one through the SAME
        ``update()`` guard (each advances ``L`` by one ``tf`` → no spurious gap) —
        there is deliberately NO bulk ``warmup_from`` fast-path (LX-09, the parity
        audit): a second state-building path would diverge and re-open the parity
        gate. Timestamps come from the venue bars only (never ``datetime.now()``).
        """
        if depth is None:
            depth = self.cache_capacity() + _WARMUP_MARGIN
        bars = self._provider.fetch_ohlcv_backfill(
            symbol, timeframe, limit=depth)
        self.logger.info(
            "Warmup for %s/%s: replaying %d bar(s) one-by-one through update()",
            symbol, timeframe, len(bars))
        for cb in bars:
            self.update(cb)

    def absorb_warmup(self, symbol: str, timeframe: str,
                      bars: tuple[Bar, ...]) -> None:
        """Silently absorb pre-built warmup ``Bar``s into the ring + ``L`` — NO ``BarEvent`` (D-03/OQ1).

        The non-emitting twin of :meth:`_deliver` (RESEARCH OQ1 / D-03b). For each
        pre-built ``Bar`` in order it runs the EXACT ring / ``L`` / newest-bar logic of
        ``_deliver`` (:490-499) — lazily create the ``deque(maxlen=cache_capacity())``
        ring, ``ring.append(bar)``, set ``_newest_bars[symbol]`` and
        ``_last_delivered[(symbol, timeframe)]`` — but DELIBERATELY SKIPS the terminal
        ``_emit`` (the single divergence). No tradeable ``BarEvent`` is put on the queue
        during warmup: the ring is warmed and ``L`` is advanced so the feed read-model is
        query-ready and L-continuous, but strategies are NOT signalled off historical bars
        (D-03b — "no tradeable BarEvent during warmup").

        This closes the documented warmup-before-subscribe ``L`` contract (RESEARCH OQ1):
        the ``BarsLoaded`` warmup window is absorbed here so ``L`` is set from REST history
        and the first subsequent live ``update()`` lands on the in-sequence branch instead
        of being misclassified as a fresh first delivery (a cold ring / unset ``L`` would
        starve ``window()`` and mis-sequence the first live bar).

        Bars arrive already built (from the ``BarsLoaded`` payload), so ``_build_bar`` is
        skipped. This is a controlled single-purpose absorb, NOT a second state path
        (D-03a / LX-09): the ring-append / ``L``-advance is byte-identical to ``_deliver``;
        only the emit is suppressed. ``window()`` still RAISES ``MissingPriceDataError`` for
        an unknown ticker (D-01 — never softened to return-empty).
        """
        for bar in bars:
            # CR-01-feed (Option B design point 1): reuse the EXISTING _last_delivered
            # cursor _deliver already honors — stop bypassing its dup/stale guard so a
            # re-delivered warmup window (the CR-02 next-poll FAILED-retry re-fetch of a
            # largely-overlapping REST window) is IDEMPOTENT. Reject bar.time <= cursor
            # BEFORE ring.append so the ring never gains a duplicate bar.time and L never
            # rewinds off an overlapping re-warm. This is the SAME `<=` monotonic contract
            # update() enforces via _reject_stale (strict `<` warns) and
            # _duplicate_or_revision (`==` silent). A first clean warmup is unaffected
            # (cursor unset -> last is None -> every bar passes), so absorb stays
            # byte-identical to _deliver on the cold path. The cursor STAYS pd.Timestamp
            # (the feed's ring/window() model is pandas-native; the de-pandas migration is
            # the DEFERRED livebarfeed-depandas-time-model-datetime todo).
            last = self._last_delivered.get((symbol, timeframe))
            if last is not None:
                bt = pd.Timestamp(bar.time)
                if bt < last:
                    self.logger.warning(
                        "Out-of-order warmup bar for %s at %s (< last-delivered=%s) "
                        "— dropped (no absorb, no state mutation)",
                        symbol, str(bt), str(last))
                    continue
                if bt == last:
                    # Duplicate re-delivery (== cursor) — expected/benign overlap on a
                    # retry re-warm; drop SILENTLY (no log) so the ring gains no dup.
                    continue
            ring = self._ring.get((symbol, timeframe))
            if ring is None:
                # D-09: size the ring by the derived capacity AT CREATION (byte-identical
                # to _deliver) so the 03-04 D-13 registration makes it 100 on the live feed.
                ring = deque(maxlen=self.cache_capacity())
                self._ring[(symbol, timeframe)] = ring
            ring.append(bar)
            self._newest_bars[symbol] = bar
            # L is stamped as a pd.Timestamp (matching _deliver's t) so a subsequent live
            # update() compares like-for-like on the tf grid (bar.time is a datetime; the
            # provider builds it as a pd.Timestamp, this wrap is idempotent + mypy-exact).
            self._last_delivered[(symbol, timeframe)] = pd.Timestamp(bar.time)

    def backfill_on_resume(self, symbol: str, timeframe: str,
                           latest_completed_ts: int) -> None:
        """Reconnect recovery: boundary-gated REST backfill replayed via ``update()``.

        The FEED-04 reconnect case (D-08). Recovery is a completed-bar BOUNDARY
        check, NOT raw outage duration — a short drop can still straddle a bar close
        (e.g. a 30 s outage across the 1d midnight boundary). On resume:

        - ``L is None`` (no bar delivered yet) → no-op; warmup owns cold start.
        - ``latest_completed_ts <= L`` → no boundary crossed → no-op.
        - ``latest_completed_ts > L`` → REST-backfill ``[L+tf .. latest]`` (inclusive
          of the boundary bar) and replay each through the SAME ``update()`` gap
          path. Composes with the resumed stream: a re-sent bar lands on the
          ``update()`` duplicate branch (D-06), so there is no double-delivery
          (Pitfall 5).

        ``latest_completed_ts`` is the venue completed-bar open-time in ms (business
        time), never the process wall-clock.
        """
        last = self._last_delivered.get((symbol, timeframe))
        if last is None:
            return
        latest = pd.Timestamp(latest_completed_ts, unit="ms", tz="UTC")
        if latest <= last:
            return
        tf = to_timedelta(timeframe)
        self.logger.info(
            "Reconnect boundary crossed for %s/%s: backfilling [%s .. %s] "
            "(last-delivered=%s)", symbol, timeframe,
            str(last + tf), str(latest), str(last))
        # Reuse the ONE shared "fetch range -> replay each via update()" path
        # (the 03-02 gap helper): range [L+tf .. latest] inclusive.
        self._backfill_gap(symbol, timeframe, last + tf, latest)

    def _reject_stale(self, sym: str, t: pd.Timestamp,
                      last: pd.Timestamp) -> None:
        """Stale bar (``t < L``) → warn + drop, NO emit, no state mutation (D-06)."""
        self.logger.warning(
            "Stale bar rejected for %s: t=%s < last-delivered=%s "
            "(no emit, no state mutation)", sym, str(t), str(last))

    def _duplicate_or_revision(self, sym: str, tf_str: str, t: pd.Timestamp,
                               cb: "ClosedBar") -> None:
        """``t == L`` → duplicate drop (identical) or forward-only revision (D-07).

        A revision (differing OHLCV at the same open-time) is dropped WITHOUT any
        state mutation — the ``confirm==1`` gate means a forming bar is never
        delivered to revise, and indicator state is never rewound.
        """
        ring = self._ring.get((sym, tf_str))
        last_bar = ring[-1] if ring else None
        incoming = self._build_bar(t, cb)
        if last_bar is not None and self._same_ohlcv(last_bar, incoming):
            self.logger.debug(
                "Duplicate bar dropped for %s at %s (identical OHLCV)",
                sym, str(t))
            return
        self.logger.warning(
            "Revision dropped for %s at %s (forward-only, no state mutation, "
            "D-07): last-close=%s incoming-close=%s", sym, str(t),
            str(last_bar.close) if last_bar is not None else None,
            str(incoming.close))

    def _fill_gap_and_deliver(
        self, sym: str, tf_str: str, first_missing: pd.Timestamp,
        last_missing: pd.Timestamp, t: pd.Timestamp, closed_bar: "ClosedBar",
    ) -> None:
        """Resolve a gap ``[first_missing .. last_missing]`` then deliver the trigger ``t`` (D-17).

        Two paths, one contract (interior bars replayed contiguous, THEN ``t`` delivered exactly
        once):

        - **Loop-triggered (the connector loop thread).** The live candle coroutine calls
          ``update()`` synchronously inside its running loop, so a synchronous
          ``fetch_ohlcv_backfill`` here would bridge through ``connector.call(...).result()`` and
          self-deadlock the loop (30s stall → livelock, RESEARCH Pitfall 4 / V17-15). Hand the gap
          range to a loop-native supervised backfill coroutine (``provider.spawn_gap_backfill``) that
          ``await``s the client fetch DIRECTLY on the loop, then replays the interior + delivers
          ``t`` on this same loop thread once the fetch resolves.
        - **Off the loop (engine-thread warmup-adjacent / reconnect-resume, or the offline paper
          ``ReplayDataProvider``).** No running loop → the synchronous ``fetch_ohlcv_backfill`` /
          ``connector.call()`` bridge is SAFE; fill the interior then deliver ``t`` inline (the
          pre-D-17 behaviour, byte-identical for the socket-free unit matrix).

        Note (scope): the loop-native path schedules the backfill and returns; a second live bar
        arriving before the coroutine completes is the concurrent-bar case owned by the D-14
        pause-defer-replay work (05.3-06), not D-17 (which only kills the self-deadlock).
        """
        if self._loop_native_backfill_available():
            self._spawn_loop_native_gap_backfill(
                sym, tf_str, first_missing, last_missing, t, closed_bar)
            return
        self._backfill_gap(sym, tf_str, first_missing, last_missing)
        self._deliver(sym, tf_str, t, closed_bar)

    def _loop_native_backfill_available(self) -> bool:
        """True iff the gap fired on a running loop AND the provider offers the D-17 seam.

        ``asyncio.get_running_loop()`` succeeds only when called from within a running loop — i.e.
        the connector loop thread, where ``update()`` runs synchronously inside the candle
        coroutine. The engine-thread warmup / reconnect-resume paths (and the offline synchronous
        ``ReplayDataProvider``) have no running loop and raise ``RuntimeError`` → synchronous path.
        The ``spawn_gap_backfill`` capability check keeps a provider without the seam on the safe
        synchronous fallback.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return hasattr(self._provider, "spawn_gap_backfill")

    def _spawn_loop_native_gap_backfill(
        self, sym: str, tf_str: str, first_missing: pd.Timestamp,
        last_missing: pd.Timestamp, t: pd.Timestamp, closed_bar: "ClosedBar",
    ) -> None:
        """Hand the gap range to the provider's loop-native supervised backfill coroutine (D-17)."""
        tf = to_timedelta(tf_str)
        since_ms = int(first_missing.value // _NS_PER_MS)
        last_ms = int(last_missing.value // _NS_PER_MS)
        limit = int((last_missing - first_missing) / tf) + 1
        self.logger.info(
            "Gap for %s: loop-native backfilling %d interior bar(s) [%s .. %s] "
            "(awaiting client fetch on the connector loop — no call().result() bridge)",
            sym, limit, str(first_missing), str(last_missing))

        def _replay_and_deliver(bars: "list[ClosedBar]") -> None:
            # Runs on the connector loop thread once the awaited fetch resolves. Replay the
            # interior CLAMPED at BOTH ends — below since_ms (D-29 low clamp, mirroring the
            # existing upper > last_ms break: the real provider treats limit as a page size
            # and can straddle the interior on either side) and above last_missing (CR-01,
            # it over-fetches past the interior into t and beyond) — each in-range bar
            # advancing L by one tf (in-sequence, no nested gap), THEN deliver the trigger t
            # exactly once — mirroring the synchronous gap path's ordering.
            #
            # D-29 (WR-05): the first in-range replayed bar MUST be exactly first_missing
            # (ts == since_ms). An under-returning page that omits the earliest missing bar
            # would otherwise re-enter the gap branch and spawn a nested backfill; fail loud
            # (typed data-integrity error, secret-free — fixed literal + coordinates only, no
            # str(payload)) so it escalates to a connector halt instead. The _replaying_backfill
            # guard is the shape-independent backstop for a hole INSIDE the range.
            self._replaying_backfill = True
            try:
                first_replayed = False
                for cb in bars:
                    ts = cb["ts"]
                    if ts < since_ms:
                        continue
                    if ts > last_ms:
                        break
                    if not first_replayed:
                        if ts != since_ms:
                            raise MalformedDataError(
                                f"gap-backfill:{sym}/{tf_str}",
                                "under-returning backfill page "
                                f"(expected first bar ts={since_ms}, got ts={ts})")
                        first_replayed = True
                    self.update(cb)
                # CR-01: the interior must be fully contiguous up to last_missing
                # before t is delivered. A tail-truncated page (contiguous prefix
                # that stops short of last_missing) or an empty / no-in-range page
                # leaves L short — the loop raises nothing (no bar exists AFTER the
                # hole to trip the interior-hole guard), and the trailing _deliver(t)
                # would otherwise jump L straight past never-backfilled interior bars,
                # silently swallowing the gap and defeating D-29's fail-loud goal.
                # Fail loud (typed, secret-free — integer-ms coordinates only, no
                # str(payload)) so it escalates through the same supervised-backfill
                # error path to a connector halt.
                last_delivered = self._last_delivered.get((sym, tf_str))
                if last_delivered != last_missing:
                    last_delivered_ms = (
                        int(last_delivered.value // _NS_PER_MS)
                        if last_delivered is not None else None)
                    raise MalformedDataError(
                        f"gap-backfill:{sym}/{tf_str}",
                        "under-returning backfill page (interior incomplete: "
                        f"last-delivered={last_delivered_ms}, "
                        f"expected last_missing={last_ms})")
                self._deliver(sym, tf_str, t, closed_bar)
            finally:
                self._replaying_backfill = False

        self._provider.spawn_gap_backfill(
            sym, tf_str, since_ms, limit, _replay_and_deliver)

    def _backfill_gap(self, sym: str, tf_str: str, first_missing: pd.Timestamp,
                      last_missing: pd.Timestamp) -> None:
        """Fill a hole ``[first_missing .. last_missing]`` and replay each bar.

        Fetches the interior missing bars (one per ``tf``, inclusive both ends) via
        the PRIVATE ``self._provider.fetch_ohlcv_backfill`` (injected in the 03-04
        OKX arm via :meth:`set_provider`) and replays each returned ``ClosedBar``
        through ``update()`` — the single FEED-03 path. The replay is CLAMPED to
        ``last_missing`` (CR-01): the real provider treats ``limit`` as a per-page
        size and over-fetches past the interior, so bars beyond ``last_missing`` are
        dropped here and the trigger bar ``t`` is delivered exactly once by the outer
        ``update()``.
        """
        tf = to_timedelta(tf_str)
        since_ms = int(first_missing.value // _NS_PER_MS)
        last_ms = int(last_missing.value // _NS_PER_MS)
        limit = int((last_missing - first_missing) / tf) + 1
        self.logger.info(
            "Gap for %s: backfilling %d interior bar(s) [%s .. %s]",
            sym, limit, str(first_missing), str(last_missing))
        bars = self._provider.fetch_ohlcv_backfill(
            sym, tf_str, since=since_ms, limit=limit)
        # CR-01: `limit` is a PER-PAGE size on the real provider, NOT a hard cap —
        # `fetch_ohlcv_backfill` paginates `while len(page) == limit` and over-fetches
        # PAST the interior into the trigger bar `t` (and beyond) whenever the venue
        # has more bars. Replaying those here would re-deliver `t` (the outer update()
        # already delivers it exactly once) and rewind the FEED-04 monotonic stamp `L`.
        # Clamp to the requested closed interior [first_missing .. last_missing]
        # (last_missing is INCLUSIVE on both the gap and the reconnect-resume path).
        for cb in bars:
            if cb["ts"] > last_ms:
                break
            self.update(cb)

    @staticmethod
    def _same_ohlcv(a: Bar, b: Bar) -> bool:
        """True iff two Bars carry identical OHLCV (duplicate vs revision, D-06)."""
        return (a.open == b.open and a.high == b.high and a.low == b.low
                and a.close == b.close and a.volume == b.volume)

    def _deliver(self, sym: str, tf_str: str, t: pd.Timestamp,
                 cb: "ClosedBar") -> None:
        """Construct the Bar, append to the (lazily-sized) ring, and emit."""
        bar = self._build_bar(t, cb)
        ring = self._ring.get((sym, tf_str))
        if ring is None:
            # D-09: size the ring by the derived capacity AT CREATION (read
            # lazily, not cached at __init__) so the 03-04 D-13 registration
            # makes it 100 on the live feed.
            ring = deque(maxlen=self.cache_capacity())
            self._ring[(sym, tf_str)] = ring
        ring.append(bar)
        self._newest_bars[sym] = bar
        self._last_delivered[(sym, tf_str)] = t
        self._emit(sym, bar)

    def _emit(self, sym: str, bar: Bar) -> None:
        """Put a single-ticker ``BarEvent`` on the queue (D-02/D-03/D-04).

        The ``(sym, bar)`` shape is the Phase-6 burst-coalescing seam — a
        consolidator can slot in here WITHOUT changing the ``BarEvent`` contract.
        Emission is one ``queue.Queue.put`` (MPSC-safe, no lock — D-19).
        """
        # WR-02: an `assert` is stripped under `python -O`, which would let a
        # `None` queue reach `.put(...)` and raise AttributeError — swallowed by the
        # connector task's broad except and silently drop bars. A bound queue is a
        # runtime wiring precondition (caller must call bind() first), not an
        # invariant, so guard it with a typed StateError that always fires.
        if self.global_queue is None:
            raise StateError(
                "LiveBarFeed",
                "unbound",
                required_state="queue-bound (call bind() first)",
                operation="_emit",
            )
        self.global_queue.put(BarEvent(time=bar.time, bars={sym: bar}))

    # -- Newest-bar provision (P5-D16 / G5) -----------------------------------

    def newest_bar(self, ticker: str) -> Bar | None:
        """Return the newest completed ``Bar`` delivered for ``ticker``, or ``None``."""
        return self._newest_bars.get(ticker)

    # -- Per-tick fact lookup (mostly dormant on live — direct emission used) --

    def current_bars(self, time: datetime) -> dict[str, Bar]:
        """Return the ``Bar`` facts stamped exactly ``time``, keyed by ticker.

        Required by the ABC and the reserved TIME/``generate_bar_event`` path;
        live delivery is direct via ``update()`` so this is mostly dormant. Reads
        the ring newest-first and stops once a bar is older than ``time`` (the
        ring is monotonically ordered).
        """
        bars: dict[str, Bar] = {}
        for (sym, _tf), ring in self._ring.items():
            for bar in reversed(ring):
                if bar.time == time:
                    bars[sym] = bar
                    break
                if bar.time < time:
                    break
        return bars

    # -- History windows (D-11 pull-resample from the ring) -------------------

    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame:
        """Return the last ``max_window`` COMPLETED bars visible at ``asof``.

        Mirrors the ``BacktestBarFeed`` rule-4 cutoff
        (``cutoff = asof - timeframe + base_timeframe``, degenerating to ``asof``
        when ``timeframe == base_timeframe``): a bucket stamped ``B`` is included
        iff ``B <= cutoff`` (``searchsorted`` side ``"right"``). For a coarser
        ``timeframe`` the base ring is resampled (``label='left', closed='left'``,
        ``_offset_alias`` — never the legacy ``time_parser`` string, Pitfall 4).

        Raises
        ------
        MissingPriceDataError
            If ``ticker`` has no ring (FR7 — never ``None``).
        ValueError
            If ``asof`` is tz-naive (would skew the tz-aware index compare).
        """
        base = self._base_frame(ticker)
        if timeframe == self._base_timeframe:
            resampled = base
        else:
            alias = _offset_alias(timeframe)
            resampled = (base.resample(alias, label="left", closed="left")
                         .agg(_AGG).dropna(how="all"))
        cutoff = asof - timeframe + self._base_timeframe
        if getattr(cutoff, "tzinfo", None) is None:
            raise ValueError(
                "window() asof must be tz-aware to match the tz-aware ring "
                f"index; got {asof!r}")
        pos = int(resampled.index.searchsorted(pd.Timestamp(cutoff),
                                               side="right"))
        start = max(0, pos - max_window)
        return resampled.iloc[start:pos]

    def _base_frame(self, ticker: str) -> pd.DataFrame:
        """Build a tz-aware float64 OHLCV frame from the ticker's base ring (D-17).

        Analytics stay float (only ``Bar`` touches money) — the ring ``Decimal``
        OHLCV are cast to ``float`` for the resample/window path.
        """
        ring = self._find_ring(ticker)
        index = pd.DatetimeIndex([bar.time for bar in ring])
        return pd.DataFrame(
            {
                "open": [float(bar.open) for bar in ring],
                "high": [float(bar.high) for bar in ring],
                "low": [float(bar.low) for bar in ring],
                "close": [float(bar.close) for bar in ring],
                "volume": [float(bar.volume) for bar in ring],
            },
            index=index,
        )

    def _find_ring(self, ticker: str) -> "deque[Bar]":
        """Return the ``ticker`` ring at the feed's BASE timeframe, or raise (FR7 / WR-05).

        WR-05: honor the timeframe key rather than returning whichever ring iterates
        first for the symbol. The old first-match loop was safe only while a single
        base timeframe existed per feed — pushing the same symbol at two base
        timeframes into one feed could silently return the wrong-timeframe ring.

        The ring is keyed by the RAW delivered timeframe string (e.g. ``"1d"`` from
        the stream/warmup ``ClosedBar``), which is NOT byte-equal to
        ``self._base_alias`` (the pandas offset alias, e.g. ``"1D"``). So the match
        normalizes each ring's timeframe through ``_offset_alias(to_timedelta(tf))``
        and compares it to ``self._base_alias`` — selecting ONLY the ring at this
        feed's base timeframe (a coarser/other-timeframe ring for the same symbol is
        NOT returned) while staying robust to ``"1d"``/``"1D"`` format differences.
        A miss raises ``MissingPriceDataError``.
        """
        for (sym, tf), ring in self._ring.items():
            if sym == ticker and _offset_alias(to_timedelta(tf)) == self._base_alias:
                return ring
        raise MissingPriceDataError(
            ticker, "ticker not known to LiveBarFeed (no ring)")

    # -- Multi-symbol megaframe (screener path, D-19) --------------------------

    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame:
        """Return a multi-symbol close-price frame visible at ``asof`` (D-19).

        Per-symbol ``window`` close columns keyed by the symbols ACTUALLY
        included (FR8). Golden SMA_MACD is N=1 and never exercises this — a
        correct-but-simple form suffices (RESEARCH §Pattern 1).
        """
        closes: list[pd.Series] = []
        included: list[str] = []
        seen: set[str] = set()
        for (sym, _tf) in self._ring:
            if sym in seen:
                continue
            seen.add(sym)
            frame = self.window(sym, timeframe, max_window, asof)
            if frame.empty:
                continue
            closes.append(frame["close"].rename(sym))
            included.append(sym)
        if not closes:
            return pd.DataFrame()
        return pd.concat(closes, axis=1, keys=included)

    # -- Dormant TIME route (D-05) --------------------------------------------

    def generate_bar_event(self, time_event: TimeEvent) -> Optional[BarEvent]:
        """DORMANT no-op — live emits BarEvents directly via ``update()`` (D-02/D-03).

        ``generate_bar_event`` is concrete on ``BacktestBarFeed`` ONLY and is NOT
        inherited by ``LiveBarFeed(BarFeed)`` — it is defined here so
        ``LiveTradingSystem.__init__`` can pass ``self.feed.generate_bar_event``
        to ``EventHandler`` unconditionally (live_trading_system.py:201) without
        crashing on any venue. The live TIME route is reserved but inert (D-05).
        """
        return None
