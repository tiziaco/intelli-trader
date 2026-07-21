"""Resume-path missed-fill catch-up wiring (D-25 / WR-01).

Locks in the D-25 fix: the engine-thread resume drain
``LiveTradingSystem._maybe_resume_after_reconnect`` must re-fetch fills that settled
while the OKX fill stream was down — by calling ``OkxExchange.catch_up_missed_fills()``
BEFORE the fresh REST ``snapshot()`` — so a trade that settled during the outage window
reaches the mirror/portfolio on reconnect instead of waiting for the next full startup
reconcile.

Before the fix, ``catch_up_missed_fills`` (okx.py:626) was fully built and unit-tested
in isolation (tests/unit/execution/test_missed_fill_catchup.py calls it DIRECTLY) but had
ZERO production call sites — the resume drain called only ``venue_account.snapshot()`` +
``resume_submission()``, so the missed fill was never recovered on resume (WR-01). This
test drives the RESUME PATH (not the exchange method in isolation): it proves the drain
routes the outage-window trade through ``_handle_trade`` exactly once, and does so before
the snapshot.

Fully offline: the connector's bounded ``fetch_my_trades`` page and the trade router are
stubbed, so the real resume drain + the real ``catch_up_missed_fills`` run without a socket.
"""

import queue
import threading
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.trading_system.live_trading_system import LiveTradingSystem
from itrader.trading_system.safety.stream_recovery_handler import (
    StreamRecoveryHandler,
)


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm constructs fully offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_resume_drain_recovers_fill_settled_during_disconnect(monkeypatch) -> None:
    """StreamRecoveryHandler.on_reconnect re-fetches an outage-window fill, before snapshot (D-25).

    P7 (§11c): the reconnect-resume I/O lives on the injected StreamRecoveryHandler,
    reached by the STREAM_STATE(up) route. It calls ``catch_up_missed_fills`` BEFORE the
    fresh REST snapshot, so the settled trade routes through ``_handle_trade`` on resume.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    # 11-09: the execution arm is read through the primary account's lifecycle.
    exchange = system._primary_lifecycle.bundle.exchange

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

    # A stub venue account whose snapshot records its ordering relative to the catch-up.
    venue_account = MagicMock(name="venue_account")
    venue_account.snapshot = MagicMock(
        name="snapshot", side_effect=lambda: call_order.append("snapshot"))
    system._stream_recovery._venue_accounts = lambda: [venue_account]

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


def test_resume_drain_skips_catchup_when_no_venue_arm(monkeypatch) -> None:
    """The catch-up is skipped when no account carries an execution arm.

    11-09: "no OKX exchange" is an EMPTY lifecycle map — the shape a non-OKX wiring
    actually produces — rather than a nulled scalar. The snapshot leg still runs and the
    resume still completes: absent ⇒ healthy, never a blocked resume.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    system._stream_recovery._lifecycles = {}
    venue_account = MagicMock(name="venue_account")
    system._stream_recovery._venue_accounts = lambda: [venue_account]

    system.pause_submission("paused-on-disconnect")

    system._stream_recovery.on_reconnect()

    venue_account.snapshot.assert_called_once()
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
    exchange = MagicMock(name="okx_exchange")
    exchange.is_streaming_healthy = MagicMock(return_value=True)
    venue_account = MagicMock(name="venue_account")
    provider = MagicMock(name="okx_data_provider")
    provider.is_streaming_healthy = MagicMock(return_value=True)
    # 11-09: the per-account lifecycle map replaces the exchange/provider scalars, and
    # the accounts arrive through a callable (they live on the portfolios).
    handler = StreamRecoveryHandler(
        safety=safety,
        lifecycles={"acct-1": SimpleNamespace(
            bundle=SimpleNamespace(connector=object(), exchange=exchange),
            provider=provider)},
        venue_accounts=lambda: [venue_account],
    )

    # Run on a stand-in ENGINE thread (NOT the connector loop).
    engine_thread = threading.Thread(target=handler.on_reconnect, name="engine")
    engine_thread.start()
    engine_thread.join()

    # The resume completed on the engine thread ...
    assert safety.resumed is True
    exchange.catch_up_missed_fills.assert_called_once()
    venue_account.snapshot.assert_called_once()
    # ... and NOT a single ring write happened from the engine thread (CF-2).
    assert deliver_calls == []
    # on_reconnect never claimed ring ownership — the loop-native path owns that seam.
    assert feed._loop_backfill_owner is None
