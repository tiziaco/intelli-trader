"""Resume is gated on ALL venue stream arms being healthy.

The engine-thread resume drain ``StreamRecoveryHandler.on_reconnect`` resumes NEW order
submission ONLY when every wired venue stream arm reports healthy — every online
account's exchange arm (fills+orders) AND the data-provider arm (candles). Resuming on
any SINGLE arm's reconnect would let a candle-stream recovery clear the pause while the
fill stream was still down, and the engine would trade blind to its own fills.

There is NO engine-side stream aggregate: each arm owns its own ``_streams_down`` set and
exposes a public ``is_streaming_healthy()`` predicate; the handler reads a compound
``_all_venue_streams_healthy()`` gate immediately before ``resume_submission()``.

These tests drive the RESUME PATH (not the predicate in isolation): they stand up a paused
OKX live system fully offline, drop one arm, fire the reconnect route target, and assert
submission STAYS paused; only once BOTH arms report healthy does the next drain resume.
"""

import queue
import threading
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd

from itrader.core.exceptions import StateError
import pytest

from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.live_okx import bring_okx_online, the_feed_provider, the_okx_record


def _exchange(system: LiveTradingSystem):
    """The (single, store-derived) OKX execution ADAPTER — read off its online record.

    This one object is all three resume arms: it runs the missed-fill catch-up, reads the
    venue snapshot and reports its own stream health, because it owns the account's
    authenticated session.
    """
    return the_okx_record(system).adapter


def _provider(system: LiveTradingSystem):
    """The one data adapter — the candle arm, on its own session."""
    return the_feed_provider(system)


@pytest.fixture
def paused_okx_system(provisioned_okx):
    """A paused OKX live system with both blocking resume legs stubbed offline.

    The reconnect-resume I/O + the all-streams-healthy gate live on the injected
    ``StreamRecoveryHandler``, which the ``STREAM_STATE(up)`` route drives; the tests
    drive that handler directly.

    Both blocking legs are stubbed on the SAME real adapter object, because that is where
    they both live: the adapter owns the session, so it does the catch-up AND the snapshot.
    Its ``is_streaming_healthy`` and ``_supervisor`` are left REAL, so the gate under test
    reads genuine arm health rather than a mock's default.

    The OKX account is STORE-DERIVED, so ``provisioned_okx`` gives the boot one durable
    row to bring online (offline there would be none).
    """
    system = LiveTradingSystem.for_exchange("okx")
    record = bring_okx_online(system)
    assert record.connector is not None
    exchange = record.adapter
    # Neutralize the two blocking venue-I/O legs the resume runs before the gate
    # (missed-fill catch-up + REST snapshot) so the resume path runs socket-free.
    exchange.catch_up_missed_fills = MagicMock(  # type: ignore[method-assign]
        name="catch_up_missed_fills")
    exchange.snapshot = MagicMock(  # type: ignore[method-assign]
        name="snapshot", return_value=AccountSnapshot.empty())
    system.pause_submission("paused-on-disconnect")
    try:
        yield system
    finally:
        system.stop()


def test_resume_stays_paused_while_fill_arm_down(paused_okx_system) -> None:
    """A candle-stream reconnect while the fill stream is down must NOT resume.

    The all-streams-healthy gate (StreamRecoveryHandler._all_venue_streams_healthy) keeps
    the pause in place until EVERY wired arm reports up.
    """
    system = paused_okx_system

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


def test_resume_stays_paused_while_data_arm_down(paused_okx_system) -> None:
    """Symmetric: an order-stream reconnect while the candle stream is down must NOT resume."""
    system = paused_okx_system

    # DATA/candle arm still down; FILL/exchange arm reconnected.
    _exchange(system)._supervisor._streams_down = set()
    _provider(system)._supervisor._streams_down = {"candle"}

    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is True

    _provider(system)._supervisor._streams_down = set()
    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is False


def test_resume_when_both_arms_healthy(paused_okx_system) -> None:
    """Both arms healthy on the first drain → resume immediately (no false gate)."""
    system = paused_okx_system

    _exchange(system)._supervisor._streams_down = set()
    _provider(system)._supervisor._streams_down = set()

    system._stream_recovery.on_reconnect()
    assert system._safety.is_submission_paused() is False


def test_an_unwired_venue_never_blocks_resume(paused_okx_system) -> None:
    """An UNWIRED venue is treated as healthy — it never blocks resume (absent ⇒ healthy).

    "The exchange arm is absent" is expressed as ZERO online account records, which is what
    a non-OKX wiring actually produces: no account comes online, so no adapter exists to
    catch up, snapshot or report health. Nulling one scalar while leaving another described
    a state the composition root never builds. The mixed case — one of several accounts'
    arms down while the rest are healthy — is gated in
    ``tests/unit/trading_system/test_stream_recovery_handler.py``.
    """
    system = paused_okx_system

    system._stream_recovery._accounts = lambda: []
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
