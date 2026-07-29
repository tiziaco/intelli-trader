"""Resume-path missed-fill catch-up wiring.

The engine-thread resume drain ``StreamRecoveryHandler.on_reconnect`` re-fetches fills
that settled while the OKX fill stream was down — by calling
``OkxExchange.catch_up_missed_fills()`` BEFORE the fresh REST ``snapshot()`` — so a trade
that settled during the outage window reaches the mirror/portfolio on reconnect instead of
waiting for the next full startup reconcile.

The ORDERING is the load-bearing part: the snapshot's balance/position picture must
already reflect the recovered trade, so a resume that snapshotted first would clear the
pause on a picture that predates a fill the engine had not yet applied.

Both legs are the same object's methods now — the execution ADAPTER owns the account's
authenticated session, so it is what re-fetches the trades and what reads the venue. This
test drives the RESUME PATH (not the exchange method in isolation): it proves the drain
routes the outage-window trade through ``_handle_trade`` exactly once, and does so before
the snapshot.

Fully offline: the connector's bounded ``fetch_my_trades`` page and the trade router are
stubbed, so the real resume drain + the real ``catch_up_missed_fills`` run without a socket.
"""

import queue
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.trading_system.live_trading_system import LiveTradingSystem
from itrader.trading_system.safety.stream_recovery_handler import (
    StreamRecoveryHandler,
)
from tests.support.live_okx import bring_okx_online


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm constructs fully offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_resume_drain_recovers_fill_settled_during_disconnect(provisioned_okx) -> None:
    """on_reconnect re-fetches an outage-window fill, BEFORE the snapshot.

    The reconnect-resume I/O lives on the injected StreamRecoveryHandler, reached by the
    STREAM_STATE(up) route. It calls ``catch_up_missed_fills`` before the fresh REST
    snapshot, so the settled trade routes through ``_handle_trade`` on resume and the
    snapshot that follows sees a venue picture the engine has already caught up to.
    """
    system = LiveTradingSystem.for_exchange("okx")

    # The single store-derived OKX execution adapter. It is the SAME object the handler
    # enumerates off the account manager's online records.
    exchange = bring_okx_online(system).adapter

    # A trade settled on the venue while the fill stream was down.
    settled_trade = {"id": "trade-during-outage"}
    exchange._active_symbols = {"BTC/USDT"}
    exchange._disconnect_ts_ms = 1_700_000_000_000  # the outage floor (venue ms)

    # Order in which the two blocking venue I/O steps run on resume — catch-up MUST
    # precede the snapshot (recover the fill, then take the fresh balance picture).
    call_order: list[str] = []

    # Stub the connector so the bounded fetch_my_trades page returns the settled trade
    # (offline — no socket). Spy the trade router to prove the resume path recovers it.
    exchange._connector = MagicMock(name="connector")
    exchange._connector.call = MagicMock(return_value=[settled_trade])
    handle_trade_spy = MagicMock(
        name="_handle_trade", side_effect=lambda _t: call_order.append("handle_trade"))
    exchange._handle_trade = handle_trade_spy  # type: ignore[method-assign]

    # The snapshot leg is stubbed on the SAME adapter — it is the adapter's own method now,
    # not a separate account leaf's — and records its ordering relative to the catch-up.
    # It answers a real ``AccountSnapshot`` so the stub cannot pass on a shape the venue
    # read never produces.
    def _snapshot() -> AccountSnapshot:
        call_order.append("snapshot")
        return AccountSnapshot.empty()

    exchange.snapshot = _snapshot  # type: ignore[method-assign]

    # Stand the system in the reconnect-resume precondition: paused on disconnect, then
    # drive the engine-thread reconnect-resume (the STREAM_STATE(up) route target).
    system.pause_submission("paused-on-disconnect")

    system._stream_recovery.on_reconnect()

    # The outage-window trade was recovered exactly once via the resume path.
    handle_trade_spy.assert_called_once_with(settled_trade)
    # Catch-up ran BEFORE the fresh REST snapshot.
    assert call_order == ["handle_trade", "snapshot"]
    # The disconnect floor was consumed by the catch-up (idempotent re-run otherwise).
    assert exchange._disconnect_ts_ms is None
    # Resume completed — the pause is cleared.
    assert system._safety.is_submission_paused() is False


def test_resume_drain_does_no_venue_io_when_no_account_is_online(monkeypatch) -> None:
    """With no online account there is nothing to catch up, and the resume still completes.

    "No OKX exchange arm" is ZERO online account records — the shape a boot with no enabled
    ``venue_accounts`` row actually produces. One enumeration feeds the catch-up, the
    snapshot and the health gate, so an empty one means no venue I/O is even reachable;
    a mirrored snapshot container is what previously let a snapshot loop run over something
    nothing populated.

    The resume must still clear: absent ⇒ healthy. Treating "no venue arm" as an unhealthy
    arm would leave such a boot permanently paused.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    system._stream_recovery._accounts = lambda: []

    system.pause_submission("paused-on-disconnect")

    system._stream_recovery.on_reconnect()

    # No adapter to reach: the catch-up and the snapshot both iterate THIS list, so an
    # empty one is the whole statement — there is no second container that could still
    # hold something to snapshot.
    assert system._stream_recovery._streaming_adapters() == []
    assert system._safety.is_submission_paused() is False


# -- CF-2: the reconnect-resume path (StreamRecoveryHandler, Plan 04) writes NO ---
# -- LiveBarFeed ring on the engine thread (the ring backfill is loop-native only). --


class _PausedSafety:
    """Minimal SafetyController stand-in: paused, records the resume."""

    def __init__(self) -> None:
        self._paused = True
        self.resumed = False

    def is_submission_paused(self) -> bool:
        return self._paused

    def resume_submission(self) -> None:
        self._paused = False
        self.resumed = True


def test_on_reconnect_does_no_engine_thread_ring_write_cf2() -> None:
    """StreamRecoveryHandler.on_reconnect (engine thread) writes NO LiveBarFeed ring (CF-2).

    The reconnect-resume path does catch-up + snapshot + resume on the ENGINE thread; the
    REST ring backfill is loop-native only (connector loop via spawn_gap_backfill). Driving
    ``on_reconnect`` on a stand-in engine thread must therefore never reach the ring writer
    — the single-writer contract's engine-side half. Spy the feed's ``_deliver`` and assert
    it is never called, and that ``on_reconnect`` never claims ring ownership.
    """
    # A real feed with a spied ring-writer; the handler must never touch it.
    feed = LiveBarFeed(provider=None, base_timeframe=timedelta(days=1))
    feed.bind(queue.Queue(), ["BTC/USDT"])
    deliver_calls: list[tuple] = []
    original_deliver = feed._deliver

    def _spy_deliver(*args, **kwargs):  # type: ignore[no-untyped-def]
        deliver_calls.append(args)
        return original_deliver(*args, **kwargs)

    feed._deliver = _spy_deliver  # type: ignore[method-assign]

    # A paused safety + healthy arms so on_reconnect runs the FULL resume (catch-up +
    # snapshot + gate -> resume) — the path that would be tempted to backfill the ring.
    safety = _PausedSafety()
    adapter = MagicMock(name="okx_adapter")
    adapter.is_streaming_healthy = MagicMock(return_value=True)
    adapter.snapshot = MagicMock(return_value=AccountSnapshot.empty())
    provider = MagicMock(name="okx_data_provider")
    provider.is_streaming_healthy = MagicMock(return_value=True)
    # The accounts arrive as the account manager's ONLINE RECORDS, read through a callable:
    # ``record.connector is not None`` marks a record as streaming, and ``record.adapter``
    # is the adapter that gets caught up, snapshotted and health-checked.
    handler = StreamRecoveryHandler(
        safety=safety,
        accounts=lambda: [SimpleNamespace(
            spec=SimpleNamespace(venue_name="okx", account_id="acct-1"),
            connector=object(), adapter=adapter)],
        feed_provider=lambda: provider,
    )

    # Run on a stand-in ENGINE thread (NOT the connector loop).
    engine_thread = threading.Thread(target=handler.on_reconnect, name="engine")
    engine_thread.start()
    engine_thread.join()

    # The resume completed on the engine thread ...
    assert safety.resumed is True
    adapter.catch_up_missed_fills.assert_called_once()
    adapter.snapshot.assert_called_once()
    # ... and NOT a single ring write happened from the engine thread (CF-2).
    assert deliver_calls == []
    # on_reconnect never claimed ring ownership — the loop-native path owns that seam.
    assert feed._loop_backfill_owner is None
