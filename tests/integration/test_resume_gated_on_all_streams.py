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

from unittest.mock import MagicMock

from itrader.trading_system.live_trading_system import LiveTradingSystem


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm constructs fully offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def _paused_offline_okx_system(monkeypatch) -> LiveTradingSystem:
    """A paused OKX live system with both blocking resume legs stubbed offline."""
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    assert system._okx_exchange is not None
    assert system._okx_data_provider is not None
    # Neutralize the two blocking venue-I/O legs the drain runs before the gate
    # (missed-fill catch-up + REST snapshot) so the resume path runs socket-free.
    system._okx_exchange.catch_up_missed_fills = MagicMock(  # type: ignore[method-assign]
        name="catch_up_missed_fills")
    system._venue_account = MagicMock(name="venue_account")
    system.pause_submission("paused-on-disconnect")
    return system


def test_resume_stays_paused_while_fill_arm_down(monkeypatch) -> None:
    """A candle-stream reconnect while the fill stream is down must NOT resume (D-28).

    RED on current code: ``_on_venue_stream_up`` fired the resume flag on the candle arm's
    up, and the drain resumed with no health gate → submission un-paused while blind to
    fills. GREEN: ``_all_venue_streams_healthy()`` keeps the pause in place.
    """
    system = _paused_offline_okx_system(monkeypatch)

    # FILL/exchange arm still down; DATA/candle arm reconnected.
    system._okx_exchange._supervisor._streams_down = {"fills"}
    system._okx_data_provider._supervisor._streams_down = set()

    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()

    # Still blind to fills → submission MUST remain paused.
    assert system._is_submission_paused() is True

    # The fill arm now recovers; the still-down arm's next up-event re-fires the flag.
    system._okx_exchange._supervisor._streams_down = set()
    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()

    # Both arms healthy → resume exactly once.
    assert system._is_submission_paused() is False


def test_resume_stays_paused_while_data_arm_down(monkeypatch) -> None:
    """Symmetric: an order-stream reconnect while the candle stream is down must NOT resume."""
    system = _paused_offline_okx_system(monkeypatch)

    # DATA/candle arm still down; FILL/exchange arm reconnected.
    system._okx_exchange._supervisor._streams_down = set()
    system._okx_data_provider._supervisor._streams_down = {"candle"}

    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    assert system._is_submission_paused() is True

    system._okx_data_provider._supervisor._streams_down = set()
    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    assert system._is_submission_paused() is False


def test_resume_when_both_arms_healthy(monkeypatch) -> None:
    """Both arms healthy on the first drain → resume immediately (no false gate)."""
    system = _paused_offline_okx_system(monkeypatch)

    system._okx_exchange._supervisor._streams_down = set()
    system._okx_data_provider._supervisor._streams_down = set()

    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    assert system._is_submission_paused() is False


def test_none_arm_never_blocks_resume(monkeypatch) -> None:
    """An unwired (None) arm is treated as healthy — it never blocks resume (absent ⇒ healthy)."""
    system = _paused_offline_okx_system(monkeypatch)

    # Simulate a non-OKX wiring where an arm is absent; the present arm is healthy.
    system._okx_exchange = None
    system._okx_data_provider._supervisor._streams_down = set()

    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    assert system._is_submission_paused() is False
