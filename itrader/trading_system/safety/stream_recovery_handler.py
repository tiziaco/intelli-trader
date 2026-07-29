"""Engine-thread reconnect-resume I/O for the live engine.

``StreamRecoveryHandler`` owns the blocking venue I/O that must run on the ENGINE
(queue-draining) thread when a venue stream reconnects — which is what keeps the pure
``SafetyController`` free of venue I/O. Every collaborator is injected, and each may be
absent on a non-OKX wiring, so every call is guard-claused.

**4-SPACE** indented, like its ``safety/`` siblings. ``trading_system/`` is mixed:
``compose.py`` / ``engine_context.py`` / ``backtest_trading_system.py`` are TABS. Match
this file.
"""

from datetime import UTC, datetime
from typing import Any, Callable, Iterable, List, Optional

from itrader.core.enums import ErrorSeverity
from itrader.events_handler.events import ErrorEvent
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
    accounts
        A CALLABLE returning the venue-account manager's ONLINE records. Callable rather
        than a captured list because accounts come online and go offline at runtime, so a
        build-time capture goes stale — and, more importantly, a build-time CONTAINER is
        how this handler previously ended up iterating something nothing ever wrote.

        ONE enumeration serves every job here: each record's execution adapter is what
        gets the missed-fill catch-up, the REST snapshot AND the health check. There is no
        second mirrored container to populate, so "the snapshot list is empty while
        accounts are online" is no longer a representable state.

        Covering EVERY account rather than a single primary is load-bearing: with one
        scalar arm, a second account's missed fills were never caught up and its down
        streams never blocked the resume, so submission resumed while the engine was still
        blind to that account's fills.
    feed_provider
        A CALLABLE returning the ONE feed data provider, or ``None``. Read live because
        the data arm may be re-pointed at runtime, so a build-time capture would go stale.
        ``None`` means no data arm is bound, which the health gate treats as "no candle
        stream to be down".
    alert_sink
        The CRITICAL-alert egress. A failed resume snapshot raises a CRITICAL alert and
        stays PAUSED — a reversible quiesce retried on the next stream-up — rather than
        latching a halt: the engine is blind to the venue, which is a reason not to submit,
        not a reason to require operator intervention. Optional; absent means log-only.
    """

    def __init__(
        self,
        *,
        safety: Any,
        accounts: Optional[Callable[[], Iterable[Any]]] = None,
        feed_provider: Optional[Callable[[], Any]] = None,
        alert_sink: Optional[Any] = None,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="StreamRecoveryHandler")
        self._safety = safety
        self._accounts: Callable[[], Iterable[Any]] = (
            accounts if accounts is not None else list)
        self._feed_provider: Callable[[], Any] = (
            feed_provider if feed_provider is not None else (lambda: None))
        self._alert_sink = alert_sink

    def _streaming_adapters(self) -> List[Any]:
        """Every online account's execution adapter that carries a live connector.

        Read off the manager's records at USE time, so an account brought online after
        this handler was built is covered and one taken offline is not.

        ``bundle.connector is not None`` is the streaming-venue discriminator — a paper
        account carries no connector, has no streams to recover and no venue to snapshot.

        De-duplicated by IDENTITY: the composition invariant refuses two portfolios
        sharing an account, but this must not ASSUME it — a duplicate would double-snapshot
        one venue account on every reconnect.
        """
        return _distinct([
            record.bundle.exchange
            for record in self._accounts()
            if record.bundle.connector is not None
        ])

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
        adapters = self._streaming_adapters()
        try:
            # Re-fetch fills that settled while the fill stream was down BEFORE the snapshot,
            # so the snapshot's balance/position picture already reflects the recovered trade.
            for adapter in adapters:
                adapter.catch_up_missed_fills()
            # A fresh REST snapshot, NOT a full two-sided ``VenueReconciler.reconcile()``:
            # a mid-session reconcile would spuriously HALT on legitimately-held positions.
            # The SAME adapters, because the adapter owning the session is the thing that
            # can read the venue — there is no separate account object to enumerate.
            for adapter in adapters:
                adapter.snapshot()
        except Exception as e:
            # Stay paused and retry on the next stream-up signal: staying paused is already
            # safe (no new-risk submission while blind to the venue) and the still-down arm's
            # next up-event re-drives recovery, so there is no failure counter and no halt
            # escalation. Nothing is re-armed here — this is a route, not a poll.
            #
            # A CRITICAL alert accompanies it: "still paused, and the reason is that the
            # venue could not be read" is an operator-visible state, whereas an error log
            # alone leaves a quiesced engine looking like a quiet one.
            self.logger.error(
                'Resume missed-fill catch-up / REST snapshot failed — staying paused: %s', e)
            self._raise_snapshot_alert(e)
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
        for adapter in self._streaming_adapters():
            if not adapter.is_streaming_healthy():
                return False
        provider = self._data_provider()
        if provider is not None and not provider.is_streaming_healthy():
            return False
        return True

    def _raise_snapshot_alert(self, exc: BaseException) -> None:
        """CRITICAL-alert a failed resume snapshot, without escalating to a halt (D-4).

        The distinction is deliberate. Being unable to read the venue is a reason not to
        submit new risk, which the still-latched pause already enforces, and the next
        stream-up re-drives recovery. Latching a HALT instead would demand operator
        intervention for a condition that routinely clears itself, and a halt has no legal
        exit except an operator reset.

        Wrapped so a raising alert sink cannot turn a recoverable snapshot failure into an
        exception escaping the resume route.
        """
        if self._alert_sink is None:
            return
        try:
            # Only DECLARED ErrorEvent fields are bound, so no connector payload or
            # credential can leak out through the alert egress.
            self._alert_sink.alert(ErrorEvent(
                time=datetime.now(UTC),
                source="stream_recovery",
                error_type=type(exc).__name__,
                error_message=(
                    "Reconnect-resume venue snapshot failed — submission stays PAUSED "
                    "until a stream-up retry succeeds; the engine is blind to the venue "
                    "and will not submit new risk"),
                operation="on_reconnect",
                severity=ErrorSeverity.CRITICAL,
            ))
        except Exception:
            self.logger.error("CRITICAL alert egress failed", exc_info=True)
