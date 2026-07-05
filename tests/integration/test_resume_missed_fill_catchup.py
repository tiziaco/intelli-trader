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

from unittest.mock import MagicMock

from itrader.trading_system.live_trading_system import LiveTradingSystem


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm constructs fully offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_resume_drain_recovers_fill_settled_during_disconnect(monkeypatch) -> None:
    """_maybe_resume_after_reconnect re-fetches an outage-window fill, before snapshot (D-25).

    RED on current code: the resume drain never calls ``catch_up_missed_fills``, so the
    settled trade is never routed through ``_handle_trade`` and the assertion FAILS.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem(exchange="okx")

    exchange = system._okx_exchange
    assert exchange is not None

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
    system._venue_account = venue_account

    # Stand the system in the reconnect-resume precondition: paused on disconnect, with
    # the connector-loop reconnect callback having flagged an engine-thread resume.
    system.pause_submission("paused-on-disconnect")
    system._pending_stream_resume.set()

    system._maybe_resume_after_reconnect()

    # The outage-window trade was recovered exactly once via the resume path.
    handle_trade_spy.assert_called_once_with(settled_trade)
    # Catch-up ran BEFORE the fresh REST snapshot.
    assert call_order == ["handle_trade", "snapshot"]
    # The disconnect floor was consumed by the catch-up (idempotent re-run otherwise).
    assert exchange._disconnect_ts_ms is None
    # Resume completed — the pause is cleared.
    assert system._is_submission_paused() is False


def test_resume_drain_skips_catchup_when_no_okx_exchange(monkeypatch) -> None:
    """The catch-up call is guard-claused on _okx_exchange (mirrors the _venue_account guard).

    A non-OKX resume path (no OKX exchange arm) must resume cleanly without the catch-up.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem(exchange="okx")

    system._okx_exchange = None  # simulate the guard's None branch
    venue_account = MagicMock(name="venue_account")
    system._venue_account = venue_account

    system.pause_submission("paused-on-disconnect")
    system._pending_stream_resume.set()

    system._maybe_resume_after_reconnect()

    venue_account.snapshot.assert_called_once()
    assert system._is_submission_paused() is False
