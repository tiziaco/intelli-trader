"""Engine-thread reconnect-resume I/O for the live engine.

``StreamRecoveryHandler`` owns the blocking venue I/O that must run on the ENGINE
(queue-draining) thread when a venue stream reconnects — which is what keeps the pure
``SafetyController`` free of venue I/O. Every collaborator is injected, and each may be
absent on a non-OKX wiring, so every call is guard-claused.

**4-SPACE** indented, like its ``safety/`` siblings. ``trading_system/`` is mixed:
``compose.py`` / ``engine_context.py`` / ``backtest_trading_system.py`` are TABS. Match
this file.
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from itrader.logger import get_itrader_logger


def _distinct(items: Iterable[Any]) -> List[Any]:
    """The given objects de-duplicated by IDENTITY, order preserved.

    ``Account`` leaves are not hashable-by-value and two portfolios may legitimately be
    handed the SAME account object, so identity — not equality — is the right key: a
    duplicate would otherwise double-snapshot one venue account on every reconnect.
    """
    seen: set[int] = set()
    unique: List[Any] = []
    for item in items:
        if id(item) in seen:
            continue
        seen.add(id(item))
        unique.append(item)
    return unique


class StreamRecoveryHandler:
    """Engine-thread reconnect-resume handler — venue I/O plus the resume gate.

    Constructed once inside ``build_live_system`` and injected as the
    ``STREAM_STATE(up)`` route consumer — a route, never a per-tick flag poll. Owns the
    blocking resume I/O (missed-fill catch-up + REST snapshot) plus the compound
    all-streams-healthy gate deciding whether the reconnect actually clears the
    reversible pause.

    Parameters
    ----------
    safety
        The injected ``SafetyController``. ``is_submission_paused`` gates the resume
        work; ``resume_submission`` is called only when every wired arm is healthy
        (which also triggers the deferred-protective replay).
    lifecycles
        The per-account ``VenueLifecycle`` map, keyed by account id; each account's
        execution arm is reached through ``lifecycle.bundle.exchange``. Covering EVERY
        account rather than a single primary is load-bearing: with one scalar arm, a
        second account's missed fills were never caught up and its down streams never
        blocked the resume, so submission resumed while the engine was still blind to
        that account's fills. Empty on a non-OKX wiring (absent ⇒ skip / healthy).
    venue_accounts
        A CALLABLE returning the venue-truth account leaves to re-snapshot. Callable
        rather than a captured list because the accounts live ON the portfolios and are
        attached during composition — a build-time capture would go stale. The default
        returns nothing, which is the compute-account case (snapshot skipped).
    feed_provider
        A CALLABLE returning the ONE feed data provider, or ``None``. Read live because
        the ``FeedConnectionBinder`` owns the borrowed connection and may RE-BORROW it at
        runtime, so a build-time capture would go stale. ``None`` means no data arm is
        bound, which the health gate treats as "no candle stream to be down".
    """

    def __init__(
        self,
        *,
        safety: Any,
        lifecycles: Optional[Mapping[str, Any]] = None,
        venue_accounts: Optional[Callable[[], Iterable[Any]]] = None,
        feed_provider: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="StreamRecoveryHandler")
        self._safety = safety
        self._lifecycles: Dict[str, Any] = dict(lifecycles) if lifecycles else {}
        self._venue_accounts: Callable[[], Iterable[Any]] = (
            venue_accounts if venue_accounts is not None else list)
        self._feed_provider: Callable[[], Any] = (
            feed_provider if feed_provider is not None else (lambda: None))

    def _streaming_exchanges(self) -> List[Any]:
        """Every account's execution arm that actually carries a live connector.

        ``bundle.connector is not None`` is the streaming-venue discriminator — a paper
        bundle carries a lifecycle with no connector.
        """
        return [
            lifecycle.bundle.exchange
            for lifecycle in self._lifecycles.values()
            if lifecycle.bundle.connector is not None
        ]

    def _data_provider(self) -> Optional[Any]:
        """The ONE feed data provider the binder currently holds, or ``None``."""
        return self._feed_provider()

    def on_reconnect(self) -> None:
        """Resume after a venue stream reconnected — engine-thread I/O.

        The connector-loop reconnect callback only flips thread-safe flags and emits the
        CONTROL event; all blocking venue I/O happens HERE, on the engine (queue-draining)
        thread, off the connector loop.

        NO ring backfill is invoked here: the REST ring backfill is loop-native
        (connector loop, ``spawn_gap_backfill``), never this engine-thread path, and
        ``LiveBarFeed._assert_ring_writer_single_thread`` fails loud if an engine-thread
        path reaches the ring writer during one.
        """
        if not self._safety.is_submission_paused():
            return
        try:
            # Re-fetch fills that settled while the fill stream was down BEFORE the snapshot,
            # so the snapshot's balance/position picture already reflects the recovered trade.
            for venue_exchange in self._streaming_exchanges():
                venue_exchange.catch_up_missed_fills()
            # A fresh REST snapshot, NOT a full two-sided ``VenueReconciler.reconcile()``:
            # a mid-session reconcile would spuriously HALT on legitimately-held positions.
            for account in _distinct(self._venue_accounts()):
                account.snapshot()
        except Exception as e:
            # Stay paused and retry on the next stream-up signal: staying paused is already
            # safe (no new-risk submission while blind to the venue) and the still-down arm's
            # next up-event re-drives recovery, so there is no failure counter and no halt
            # escalation. Nothing is re-armed here — this is a route, not a poll.
            self.logger.error(
                'Resume missed-fill catch-up / REST snapshot failed — staying paused: %s', e)
            return
        # Resume NEW submission ONLY when EVERY wired arm is healthy: one arm coming back up
        # (candles, or the exchange's orders stream) must not resume while the engine is
        # still blind to fills. The catch-up and snapshot above ran regardless — recovering
        # fills while staying paused is correct.
        if not self._all_venue_streams_healthy():
            self.logger.info(
                'Reconnect handled but venue streams not all healthy — staying paused '
                '(resume gated until every wired arm reports up, D-28/WR-03)')
            return
        self._safety.resume_submission()

    def _all_venue_streams_healthy(self) -> bool:
        """True unless a WIRED venue arm reports its stream set down.

        The compound resume gate: EVERY account's exchange arm (fills+orders) AND the
        data-provider arm (candles) must report healthy. Each arm OWNS its health state
        and the handler only READS its public ``is_streaming_healthy`` predicate, so
        there is NO engine-side aggregate stream set and NO namespaced stream names. An
        unwired arm never blocks (absent ⇒ healthy), so non-OKX runs resume
        unconditionally.
        """
        for venue_exchange in self._streaming_exchanges():
            if not venue_exchange.is_streaming_healthy():
                return False
        provider = self._data_provider()
        if provider is not None and not provider.is_streaming_healthy():
            return False
        return True
