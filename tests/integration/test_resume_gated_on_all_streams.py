"""Resume is gated on ALL venue stream arms being healthy (D-28 / WR-03).

Locks in the D-28 fix: the engine-thread resume drain
``LiveTradingSystem._maybe_resume_after_reconnect`` must resume NEW order submission
ONLY when every wired venue stream arm reports healthy — the exchange arm
(fills+orders) AND the data-provider arm (candles). Before the fix, ``_on_venue_stream_up``
set ``_pending_stream_resume`` on ANY single arm's reconnect, so a candle-stream reconnect
resumed submission while the fill stream was still down — the engine traded blind to fills
(WR-03).

The fix adds NO engine-side aggregation: each arm already owns its ``_streams_down`` set;
it exposes a public ``is_streaming_healthy()`` predicate, and the engine reads a compound
``_all_venue_streams_healthy()`` gate immediately before ``resume_submission()``.

This test drives the RESUME PATH (not the predicate in isolation): it stands up a paused
OKX live system fully offline, drops one arm, fires the resume flag, and asserts submission
STAYS paused; only once BOTH arms report healthy does the next drain resume.
"""

import queue
import threading
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd

from itrader.core.exceptions import StateError
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.trading_system.live_trading_system import LiveTradingSystem


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm constructs fully offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def _exchange(system: LiveTradingSystem):
    """The primary account's execution arm (11-09: read through its lifecycle)."""
    return system._primary_lifecycle.bundle.exchange


def _provider(system: LiveTradingSystem):
    """The one feed data provider — the primary account's (11-09)."""
    return system._primary_lifecycle.provider


def _paused_offline_okx_system(monkeypatch) -> LiveTradingSystem:
    """A paused OKX live system with both blocking resume legs stubbed offline.

    P7 (§11c): the reconnect-resume I/O + the all-streams-healthy gate live on the
    injected StreamRecoveryHandler; the ``STREAM_STATE(up)`` route drives its
    ``on_reconnect``. The tests drive that handler directly. The venue-account snapshot
    leg is stubbed on the HANDLER (it captured the real account at build); the missed-fill
    catch-up leg is stubbed on the real exchange object the handler shares.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    # 11-09: the venue arms are read through the PRIMARY account's lifecycle (the six
    # facade scalars are deleted), and the handler holds the per-account lifecycle map
    # plus a CALLABLE over the accounts the portfolios hold.
    lifecycle = system._primary_lifecycle
    assert lifecycle is not None and lifecycle.bundle.connector is not None
    # Neutralize the two blocking venue-I/O legs the resume runs before the gate
    # (missed-fill catch-up + REST snapshot) so the resume path runs socket-free.
    lifecycle.bundle.exchange.catch_up_missed_fills = MagicMock(  # type: ignore[method-assign]
        name="catch_up_missed_fills")
    system._stream_recovery._venue_accounts = lambda: [
        MagicMock(name="venue_account")]
    system.pause_submission("paused-on-disconnect")
    return system


def test_resume_stays_paused_while_fill_arm_down(monkeypatch) -> None:
    """A candle-stream reconnect while the fill stream is down must NOT resume (D-28).

    The all-streams-healthy gate (StreamRecoveryHandler._all_venue_streams_healthy) keeps
    the pause in place until EVERY wired arm reports up.
    """
    system = _paused_offline_okx_system(monkeypatch)

    # FILL/exchange arm still down; DATA/candle arm reconnected.
    _exchange(system)._supervisor._streams_down = {"fills"}
    _provider(system)._supervisor._streams_down = set()

    system._stream_recovery.on_reconnect()

    # Still blind to fills → submission MUST remain paused.
    assert system._safety.is_submission_paused() is True

    # The fill arm now recovers; the still-down arm's next up-event re-fires on_reconnect.
    _exchange(system)._supervisor._streams_down = set()
    system._stream_recovery.on_reconnect()

    # Both arms healthy → resume exactly once.
    assert system._safety.is_submission_paused() is False


def test_resume_stays_paused_while_data_arm_down(monkeypatch) -> None:
    """Symmetric: an order-stream reconnect while the candle stream is down must NOT resume."""
    system = _paused_offline_okx_system(monkeypatch)

    # DATA/candle arm still down; FILL/exchange arm reconnected.
    _exchange(system)._supervisor._streams_down = set()
    _provider(system)._supervisor._streams_down = {"candle"}

    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is True

    _provider(system)._supervisor._streams_down = set()
    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is False


def test_resume_when_both_arms_healthy(monkeypatch) -> None:
    """Both arms healthy on the first drain → resume immediately (no false gate)."""
    system = _paused_offline_okx_system(monkeypatch)

    _exchange(system)._supervisor._streams_down = set()
    _provider(system)._supervisor._streams_down = set()

    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is False


def test_an_unwired_venue_never_blocks_resume(monkeypatch) -> None:
    """An UNWIRED venue is treated as healthy — it never blocks resume (absent ⇒ healthy).

    11-09: "an arm is absent" is now expressed as an EMPTY lifecycle map, which is what a
    non-OKX wiring actually produces (no account assembles, so neither the exchange arm
    nor the data arm exists). The old spelling — nulling one scalar while leaving the
    other — described a state the composition root never builds. The mixed case, where
    one of several accounts' arms is down while the rest are healthy, is gated in
    ``tests/unit/trading_system/test_stream_recovery_handler.py``.
    """
    system = _paused_offline_okx_system(monkeypatch)

    system._stream_recovery._lifecycles = {}
    _provider(system)._supervisor._streams_down = set()

    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is False


# -- CF-2: the LiveBarFeed ring writer is single-writer on resume (T-07-03). ----
# -- A ring write from a non-owner (engine) thread during a loop-native backfill --
# -- fails loud; the guard is inert on the happy loop-native + no-backfill paths. --


def _closed_bar() -> dict:
    """A well-formed Decimal-edge ClosedBar for a direct _deliver call."""
    return {
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "ts": 1_700_000_000_000,
        "open": Decimal("1"),
        "high": Decimal("2"),
        "low": Decimal("1"),
        "close": Decimal("2"),
        "volume": Decimal("10"),
    }


def _bound_feed() -> LiveBarFeed:
    feed = LiveBarFeed(provider=None, base_timeframe=timedelta(days=1))
    feed.bind(queue.Queue(), ["BTC/USDT"])
    return feed


def test_cf2_engine_thread_ring_write_during_loop_backfill_fails_loud() -> None:
    """A ring write from a NON-owner (engine) thread during a loop-native backfill raises (CF-2).

    While the connector loop owns an in-flight backfill (``_loop_backfill_owner`` set to the
    loop thread's ident), any OTHER thread reaching the ring writer is the concurrent-writer
    tampering hazard CF-2 forbids — the guard fails loud with a typed ``StateError`` instead
    of silently interleaving appends and corrupting the monotonic bar stream.
    """
    feed = _bound_feed()
    cb = _closed_bar()
    t = pd.Timestamp(cb["ts"], unit="ms", tz="UTC")

    # The connector loop (= THIS/main thread here) owns the in-flight backfill.
    feed._loop_backfill_owner = threading.get_ident()

    # A ring write from a DIFFERENT (engine) thread must fail loud.
    errors: list[BaseException] = []

    def _engine_write() -> None:
        try:
            feed._deliver("BTC/USDT", "1d", t, cb)
        except StateError as exc:
            errors.append(exc)

    engine_thread = threading.Thread(target=_engine_write, name="engine")
    engine_thread.start()
    engine_thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], StateError)
    # No ring was actually written by the rejected engine-thread attempt.
    assert feed.newest_bar("BTC/USDT") is None


def test_cf2_owning_loop_thread_backfill_write_passes() -> None:
    """A ring write on the OWNING loop thread during a backfill is fine (happy path)."""
    feed = _bound_feed()
    cb = _closed_bar()
    t = pd.Timestamp(cb["ts"], unit="ms", tz="UTC")

    # This thread owns the backfill; a same-thread ring write is the legitimate single writer.
    feed._loop_backfill_owner = threading.get_ident()
    feed._deliver("BTC/USDT", "1d", t, cb)

    assert feed.newest_bar("BTC/USDT") is not None


def test_cf2_guard_inert_when_no_backfill_active() -> None:
    """No loop-native backfill active (owner None) → the guard never fires on any thread."""
    feed = _bound_feed()
    cb = _closed_bar()
    t = pd.Timestamp(cb["ts"], unit="ms", tz="UTC")

    # Owner is None (default) — a normal engine-thread delivery must NOT raise.
    errors: list[BaseException] = []

    def _engine_write() -> None:
        try:
            feed._deliver("BTC/USDT", "1d", t, cb)
        except StateError as exc:  # pragma: no cover — must not happen
            errors.append(exc)

    engine_thread = threading.Thread(target=_engine_write, name="engine")
    engine_thread.start()
    engine_thread.join()

    assert errors == []
    assert feed.newest_bar("BTC/USDT") is not None
