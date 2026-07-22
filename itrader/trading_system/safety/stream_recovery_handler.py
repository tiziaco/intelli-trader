"""Engine-thread reconnect-resume I/O for the live engine (SAFE-04, §11c).

``StreamRecoveryHandler`` owns the blocking venue I/O that runs on the ENGINE
(queue-draining) thread when a venue stream reconnects — byte-moved out of
``LiveTradingSystem._maybe_resume_after_reconnect`` (607-666) +
``_all_venue_streams_healthy`` (668-684) so the I/O-heavy resume path has a
focused, unit-testable home and the pure ``SafetyController`` (Plan 03) stays
free of venue I/O.

Reached by the ``STREAM_STATE(up)`` CONTROL route (Plan 06 wires it), NOT the
per-tick pending-resume ``threading.Event`` flag poll the donor drained — so the
``is_set()``/``clear()`` flag scaffolding is dropped in the move. On a reconnect
``on_reconnect`` does ONLY:

1. ``okx_exchange.catch_up_missed_fills()`` — re-fetch fills that settled while
   the fill stream was down (D-25/WR-01), BEFORE the fresh snapshot so the
   snapshot's balance/position picture already reflects the recovered trade.
2. ``venue_account.snapshot()`` — a fresh REST balance/position snapshot
   (WR-04: NOT a full two-sided ``VenueReconciler.reconcile()`` — a mid-session
   reconcile would spuriously HALT on legitimately-held positions).
3. the all-streams-healthy gate (``_all_venue_streams_healthy`` — each wired
   arm's ``is_streaming_healthy()``; a ``None``/unwired arm is healthy) → only
   when EVERY wired arm reports up call ``safety.resume_submission()``; otherwise
   stay paused (D-28/WR-03).

**D-12** — on a snapshot / catch-up failure the handler STAYS PAUSED and retries
on the next stream-up signal: staying paused is already safe (no new-risk
submission while blind to the venue) and the next reconnect re-drives recovery.
NO failure-counter / halt-escalation is added here (extracted as-is).

**CF-2 (single-writer ring contract)** — this handler does NOT touch the
``LiveBarFeed`` ring writer. The REST ring backfill lands LOOP-NATIVE via the
connector-loop reconnect callback (``spawn_gap_backfill``), never on this
engine-thread path — so ``on_reconnect`` contains no ring-backfill call. The
``live_bar_feed.py`` CF-2 assertion (Task 2) fails loud if any engine-thread path
reaches the ring writer during a backfill.

All collaborators are INJECTED (the ``SafetyController`` this handler resumes,
plus the OKX exchange / venue account / OKX data provider arms — each may be
``None`` on a non-OKX wiring, so every call is guard-claused). The class holds
no facade back-reference. 4-space indentation (matches ``safety_controller.py`` /
``live_trading_system.py``).
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from itrader.logger import get_itrader_logger


def _distinct(items: Iterable[Any]) -> List[Any]:
    """The given objects de-duplicated by IDENTITY, order preserved (11-09).

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
    """Engine-thread reconnect-resume handler — venue I/O + resume gate (SAFE-04).

    Constructed once inside ``build_live_system`` and injected as the
    ``STREAM_STATE(up)`` route consumer (Plan 06). Owns the blocking resume I/O
    (missed-fill catch-up + REST snapshot) that must run OFF the connector asyncio
    loop, plus the compound all-streams-healthy gate that decides whether the
    reconnect actually clears the reversible pause.

    Parameters
    ----------
    safety
        The injected ``SafetyController`` (Plan 03). ``is_submission_paused`` gates
        the resume work; ``resume_submission`` is called only when every wired arm
        is healthy (which also triggers the deferred-protective replay).
    lifecycles
        11-09: the per-account ``VenueLifecycle`` map, keyed by account id and PRIMARY
        FIRST. REPLACES the former ``okx_exchange`` / ``okx_data_provider`` scalars —
        each account's execution arm is reached through ``lifecycle.bundle.exchange``
        and the ONE feed provider through the primary's ``lifecycle.provider``. The
        scalars covered only the primary account, so a second account's missed fills
        were never caught up and its down streams never blocked the resume: submission
        would resume while the engine was still blind to that account's fills. Empty on
        a non-OKX wiring — every call is guard-claused (absent ⇒ skip / healthy).
    venue_accounts
        11-09: a CALLABLE returning the venue-truth account leaves to re-snapshot.
        Callable rather than a captured list because the accounts live ON the portfolios
        and are attached during composition — a build-time capture would go stale. The
        default returns nothing, which is the compute-account case (snapshot skipped).
    """

    def __init__(
        self,
        *,
        safety: Any,
        lifecycles: Optional[Mapping[str, Any]] = None,
        venue_accounts: Optional[Callable[[], Iterable[Any]]] = None,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="StreamRecoveryHandler")
        self._safety = safety
        self._lifecycles: Dict[str, Any] = dict(lifecycles) if lifecycles else {}
        self._venue_accounts: Callable[[], Iterable[Any]] = (
            venue_accounts if venue_accounts is not None else list)

    # ---- venue arms read THROUGH the lifecycles (no stored scalar aliases) ---------

    def _streaming_exchanges(self) -> List[Any]:
        """Every account's execution arm that actually carries a live connector.

        ``bundle.connector is not None`` is the streaming-venue discriminator used
        throughout the live wiring (paper carries a lifecycle with no connector).
        """
        return [
            lifecycle.bundle.exchange
            for lifecycle in self._lifecycles.values()
            if lifecycle.bundle.connector is not None
        ]

    def _data_provider(self) -> Optional[Any]:
        """The ONE feed data provider — the PRIMARY (first-inserted) account's, or None."""
        for lifecycle in self._lifecycles.values():
            if lifecycle.bundle.connector is not None:
                return lifecycle.provider
        return None

    def on_reconnect(self) -> None:
        """Resume after a venue stream reconnected — engine-thread I/O (SAFE-04/D-19).

        Runs on the engine (queue-draining) thread, reached by the ``STREAM_STATE(up)``
        route (Plan 06). Takes a fresh REST balance/position SNAPSHOT (don't trade when
        you can't see the venue), preceded by a missed-fill catch-up, THEN clears the
        pause — but ONLY when every wired venue stream arm is healthy. The connector-loop
        reconnect callback only flips thread-safe flags / emits the CONTROL event; all
        blocking venue I/O happens HERE, off the connector loop (Pitfall 9).

        A failed snapshot / catch-up leaves the pause in place and returns — retried on
        the next stream-up signal (D-12). Never resume blind.

        CF-2: NO ring backfill is invoked here — the REST ring backfill is loop-native
        (connector loop via ``spawn_gap_backfill``), never this engine-thread path.
        """
        # Nothing to resume unless a reversible pause is currently latched. A None-arm /
        # already-resumed engine short-circuits before any venue I/O.
        if not self._safety.is_submission_paused():
            return
        try:
            # D-25 (WR-01): re-fetch fills that settled while the fill stream was down,
            # BEFORE the fresh REST snapshot — so the snapshot's balance/position picture
            # already reflects the recovered trade. Engine thread here (safe to block; the
            # bounded fetch_my_trades page bridges through the connector). Each trade routes
            # through _handle_trade and is deduped by the D-08 {symbol}:{trade_id} guard, so
            # a later reconcile never double-settles it. 11-09: run for EVERY account's
            # execution arm — a second account's fills settled during the outage are just
            # as missed as the primary's. An empty list is the non-OKX skip.
            for venue_exchange in self._streaming_exchanges():
                venue_exchange.catch_up_missed_fills()
            # WR-04: fresh REST balance/position snapshot before resuming (engine
            # thread — safe to block); NOT a full two-sided reconcile — a mid-session
            # reconcile would spuriously HALT on legitimately-held positions.
            # 11-09: one snapshot per DISTINCT account object. Deduped by identity so a
            # shared account is never double-snapshotted; an empty result is the
            # compute-account case (nothing to refresh).
            for account in _distinct(self._venue_accounts()):
                account.snapshot()
        except Exception as e:
            # D-12: on snapshot/catch-up failure, STAY PAUSED and retry on the next
            # stream-up signal (no failure-counter / halt-escalation added in P7). Staying
            # paused is already safe (no new-risk submission while unhealthy); the still-down
            # arm's next up-event re-drives this recovery. No flag is re-set here — the route
            # (not a poll) re-fires on the next STREAM_STATE(up).
            self.logger.error(
                'Resume missed-fill catch-up / REST snapshot failed — staying paused: %s', e)
            return
        # D-28 (WR-03): resume NEW submission ONLY when EVERY wired venue stream arm is
        # healthy. A single arm's reconnect (candle stream up while the fill stream is still
        # down, OR the exchange's own orders-stream up while its fills-stream is still down)
        # must not resume submission while the engine is still blind to fills. Leave the pause
        # in place — the still-down arm's next up-event re-fires this handler. (The D-25
        # catch-up + snapshot above ran regardless — recovering fills while staying paused is
        # correct.)
        if not self._all_venue_streams_healthy():
            self.logger.info(
                'Reconnect handled but venue streams not all healthy — staying paused '
                '(resume gated until every wired arm reports up, D-28/WR-03)')
            return
        self._safety.resume_submission()

    def _all_venue_streams_healthy(self) -> bool:
        """True unless a WIRED venue arm reports its stream set down (D-28 / WR-03).

        The compound resume gate: resume NEW submission only when EVERY wired arm —
        EVERY account's exchange arm (fills+orders) AND the data-provider arm (candles)
        — reports its own ``_streams_down`` empty. Each arm OWNS its health state; the
        handler only READS a public per-arm predicate, adding NO engine-side aggregate
        stream set and NO namespaced stream names. An unwired arm never blocks
        (absent ⇒ healthy), so non-OKX runs resume unconditionally.

        11-09 widened the exchange half from the primary's arm to EVERY account's. A
        second account whose fill stream is still down must keep submission paused for
        the same reason the first one does: resuming while blind to fills is the defect,
        and being blind to only SOME accounts' fills is not a lesser version of it.
        """
        for venue_exchange in self._streaming_exchanges():
            if not venue_exchange.is_streaming_healthy():
                return False
        provider = self._data_provider()
        if provider is not None and not provider.is_streaming_healthy():
            return False
        return True
