"""LiveTradingSystem OKX-wiring gate (CR-02) — construction is credential/IO-free for non-OKX.

Locks in the CR-02 fix: constructing a ``LiveTradingSystem`` for a non-OKX venue (the
default ``'binance'``) must

- NOT require the ``OKX_API_*`` credential triple (``OkxSettings()`` is only constructed
  on the ``exchange == 'okx'`` arm),
- NOT perform any OKX network I/O in the constructor (``connect()`` is deferred to
  ``start()``), and
- leave the OKX arms unwired (``_okx_connector is None``, no ``'okx'`` execution arm).

Before the fix, ``__init__`` unconditionally built ``OkxSettings()`` (raising
``pydantic.ValidationError`` with no creds) and called ``connect()`` (a blocking
``load_markets()`` REST round-trip) regardless of the requested venue — so constructing
the live system for ANY venue hard-required OKX credentials + reachability. No test
constructed a ``LiveTradingSystem``, so the defect was uncaught.

This suite does NOT assert on ``sys.modules`` (the sibling connector/execution suites in
the same session may already have imported ``ccxt.pro``); the credential-free construction
+ unwired-arm assertions are the load-bearing gate.
"""

from unittest.mock import MagicMock

import pytest

from itrader.core.enums import ExchangeConnectionStatus, SystemStatus
from itrader.execution_handler.result_objects import ConnectionResult
from itrader.trading_system.live_trading_system import LiveTradingSystem


def _strip_okx_env(monkeypatch) -> None:
    """Remove the OKX credential triple so a stray requirement surfaces as a failure."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm's ``OkxSettings()`` constructs.

    The connector constructor is I/O-free (``connect()`` is deferred to ``start()``),
    so a stubbed credential triple is enough to build ``LiveTradingSystem.for_exchange("okx")``
    fully offline — no socket, no ``load_markets`` round-trip.
    """
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_construct_non_okx_venue_needs_no_okx_credentials(monkeypatch) -> None:
    """A non-OKX LiveTradingSystem constructs with the OKX creds absent (CR-02)."""
    _strip_okx_env(monkeypatch)

    # Must NOT raise pydantic.ValidationError for missing OKX_API_* — the OKX arm is gated.
    system = LiveTradingSystem.for_exchange("binance")

    assert system._okx_connector is None
    assert system._okx_exchange is None
    assert system._okx_data_provider is None
    assert system._venue_account is None
    # The OKX execution arm is not registered for a non-OKX venue.
    assert "okx" not in system.execution_handler.exchanges


def test_construct_does_not_connect_in_constructor(monkeypatch) -> None:
    """Constructing performs no OKX network connect — connect() is deferred to start() (CR-02).

    A non-OKX system has no connector at all, so stop() (which tears the connector down
    unconditionally, CR-01) is a clean no-op that does not raise.
    """
    _strip_okx_env(monkeypatch)

    system = LiveTradingSystem.for_exchange("binance")

    # No connector was built, so there is nothing connected and nothing to leak.
    assert system._okx_connector is None
    # stop() before any start() must not raise even though nothing is wired/running.
    assert system.stop() is True


def test_okx_arm_injects_real_provider_into_live_feed(monkeypatch) -> None:
    """The OKX arm injects the real provider into the feed BEFORE warmup/start_stream (D-01/D-13).

    The load-bearing Phase-3 wiring proof: after construction — and BEFORE any
    ``warmup()``/``start_stream()`` runs — the LIVE feed's INTERNAL provider reference
    (``self._provider``, the private attr ``warmup()``/gap-backfill read) IS the
    constructed ``OkxDataProvider``. A dead-attribute mis-wire (``feed.provider = ...``)
    would leave ``feed._provider is None`` and fail HERE, at the task level, rather than
    as a runtime ``AttributeError`` at warmup. Fully offline — the connector constructor
    is I/O-free and ``start()`` (which does the network connect) is never called.
    """
    _set_okx_env(monkeypatch)

    system = LiveTradingSystem.for_exchange("okx")

    # The OKX data arm was constructed for the okx venue.
    assert system._okx_data_provider is not None
    # The feed is the LIVE feed, and the real provider was injected via set_provider —
    # so the PRIVATE _provider the warmup path reads IS the constructed provider.
    assert system.feed._provider is system._okx_data_provider


def test_okx_arm_wires_provider_sink_to_feed_update(monkeypatch) -> None:
    """The provider's closed-bar sink is wired to ``feed.update`` (the ingest seam).

    Proves the composition-root wire ``set_bar_sink(self.feed.update)``: a confirm-gated
    ClosedBar pushed from the provider drives the feed's monotonic-guard ingest.
    """
    _set_okx_env(monkeypatch)

    system = LiveTradingSystem.for_exchange("okx")

    assert system._okx_data_provider is not None
    # The provider holds the feed's update() as its closed-bar sink.
    assert system._okx_data_provider._bar_sink == system.feed.update


def test_okx_arm_binds_provider_to_engine_queue(monkeypatch) -> None:
    """The OKX arm binds the provider's engine queue so spawn_warmup can emit (WR-02 blocker).

    ``OkxDataProvider.spawn_warmup`` (the async half of the WR-02 warmup pipeline) raises a
    typed ``StateError`` unless ``self._global_queue`` was bound via ``set_global_queue``. The
    composition root wires the provider's bar sink / halt signal / stream-state listener but
    (before this fix) never bound the queue — so every poll-driven add's ``spawn_warmup`` failed
    immediately (swallowed by the per-symbol try/except), no ``BarsLoaded`` was ever emitted, and
    the symbol stayed permanently PENDING (dark), breaking the core live WR-02 deliverable.

    Removing the ``self._okx_data_provider.set_global_queue(self.global_queue)`` wire makes this
    FAIL (``_global_queue is None``) — so the test genuinely catches the wiring gap.
    """
    _set_okx_env(monkeypatch)

    system = LiveTradingSystem.for_exchange("okx")

    assert system._okx_data_provider is not None
    # The provider's warmup-emit queue IS the engine queue — spawn_warmup can now put
    # BarsLoaded/BarsLoadFailed without raising the unbound StateError.
    assert system._okx_data_provider._global_queue is system.global_queue


def test_okx_live_feed_capacity_derives_to_strategy_warmup(monkeypatch) -> None:
    """After session init the LIVE feed's cache_capacity() derives to the max strategy warmup (D-13).

    The D-13 consumer registration in ``_initialize_live_session`` makes
    ``cache_capacity()`` equal the deepest registered strategy warmup — for the golden
    SMA_MACD that is 100, not the newest-bar floor (1). Drives the session init directly
    (offline; no OKX connect, no stream).
    """
    _set_okx_env(monkeypatch)

    system = LiveTradingSystem.for_exchange("okx")
    # Pre-registration: no raw-bar consumer yet -> the newest-bar floor.
    assert system.feed.cache_capacity() == 1

    # Run only the session-init wiring (membership derive + D-13 registration + bind);
    # this performs no network I/O (the OKX connect lives in start(), not here).
    system._initialize_live_session()

    expected = max(
        (s.warmup for s in system.strategies_handler.strategies), default=1)
    assert system.feed.cache_capacity() == expected


def _stub_okx_network(system: LiveTradingSystem) -> None:
    """Stub every network-touching call in start() so it runs fully offline.

    Leaves ``system._okx_exchange.connect`` untouched — that is the call under
    test (CR-01). The VenueReconciler path is skipped because the in-memory order
    store does not expose ``rehydrate`` (start() guards on ``hasattr``).
    """
    system._okx_connector.connect = MagicMock(name="connector.connect")
    system.feed.warmup = MagicMock(name="feed.warmup")
    system._okx_data_provider.start_stream = MagicMock(name="provider.start_stream")
    system._venue_account = MagicMock(name="venue_account")


def test_start_spawns_okx_order_arm_fill_stream(monkeypatch) -> None:
    """start() invokes _okx_exchange.connect() — the SOLE spawn site of the fill stream (CR-01).

    This is the assertion the verification proved absent (``grep _okx_exchange.connect(``
    returned 0 across tests/). Removing the Task-1 ``self._okx_exchange.connect()`` call in
    start() makes ``connect_spy.assert_called_once()`` FAIL — so the test genuinely catches
    the CR-01 gap (order mirror stays PENDING forever with no fill stream).
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    _stub_okx_network(system)
    connect_spy = MagicMock(
        name="okx_exchange.connect",
        return_value=ConnectionResult(
            success=True,
            status=ExchangeConnectionStatus.CONNECTED,
            exchange_name="okx"))
    system._okx_exchange.connect = connect_spy

    try:
        started = system.start()
        assert started is True
        connect_spy.assert_called_once()          # fill/order streams spawned
        assert system.get_status()["status"] == SystemStatus.RUNNING.value
    finally:
        system.stop()


def test_start_arms_okx_connector_halt_signal(monkeypatch) -> None:
    """The composition root arms _okx_connector's halt signal to _request_connector_halt (D-26/WR-02).

    WR-02 gap: ``OkxConnector.set_halt_signal`` had no caller — only ``_okx_exchange``,
    ``_okx_data_provider`` and ``portfolio_handler`` were armed — so
    ``OkxConnector._on_task_done``'s ``if self._halt_signal is not None:`` guard was always
    False and a task dying OUTSIDE the stream supervisors logged-and-vanished with no halt.

    This asserts the REAL connector's halt signal is armed by the composition root (not the
    ``_on_task_done`` unit's injected halt-signal double), and that it survives ``start()``.
    Removing the ``self._okx_connector.set_halt_signal(...)`` arm makes this FAIL (the arm
    is the SOLE caller of ``OkxConnector.set_halt_signal``).
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    _stub_okx_network(system)
    system._okx_exchange.connect = MagicMock(
        name="okx_exchange.connect",
        return_value=ConnectionResult(
            success=True,
            status=ExchangeConnectionStatus.CONNECTED,
            exchange_name="okx"))

    try:
        started = system.start()
        assert started is True
        # The connector arm is wired to the SAME flag-only callback the exchange/provider
        # arms pass — so _on_task_done can now escalate a dead task to a fail-safe halt.
        # (== not is: each `self._request_connector_halt` access is a fresh bound-method
        # object; bound methods compare equal by function+instance, mirroring this file's
        # `_bar_sink == system.feed.update` check.)
        assert system._okx_connector._halt_signal == system._request_connector_halt
    finally:
        system.stop()


def test_start_fails_when_okx_exchange_connect_fails(monkeypatch) -> None:
    """A failed ConnectionResult from _okx_exchange.connect() drives ERROR and returns False.

    connect() RETURNS a ConnectionResult (never raises), so start() must check ``.success``
    and re-raise; the failure then flows through the existing except → SystemStatus.ERROR.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")
    _stub_okx_network(system)
    system._okx_exchange.connect = MagicMock(
        name="okx_exchange.connect",
        return_value=ConnectionResult(
            success=False,
            status=ExchangeConnectionStatus.ERROR,
            exchange_name="okx",
            error_message="stream spawn failed"))

    try:
        started = system.start()
        assert started is False
        assert system.get_status()["status"] == SystemStatus.ERROR.value
    finally:
        system.stop()


# --- WR-02: one VenueAccount per portfolio; single-portfolio-live fail-loud ----


def test_link_venue_account_single_portfolio_assigns(monkeypatch) -> None:
    """One active portfolio: the venue account is linked onto it (WR-02, unchanged path).

    Exercises the extracted wiring seam directly (no network) — the single active
    portfolio receives the venue-cached account so the engine-thread drift compare
    reads venue truth.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    venue_account = MagicMock(name="venue_account")
    system._venue_account = venue_account
    portfolio = MagicMock(name="portfolio")
    system.portfolio_handler.get_active_portfolios = MagicMock(  # type: ignore[method-assign]
        return_value=[portfolio])

    system._link_venue_account_to_portfolios()

    assert portfolio.account is venue_account


def test_link_venue_account_two_portfolios_fails_loud(monkeypatch) -> None:
    """Two active portfolios: wiring FAILS LOUD rather than sharing one VenueAccount (WR-02).

    Sharing a single VenueAccount across portfolios would conflate their buying
    power / positions and silently discard each SimulatedAccount ledger. Until a
    per-portfolio VenueAccount keyed by venue sub-account exists, the wiring must
    refuse (RuntimeError) — a second portfolio can never silently mis-attribute
    venue truth.
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    system._venue_account = MagicMock(name="venue_account")
    p1 = MagicMock(name="portfolio_1")
    p2 = MagicMock(name="portfolio_2")
    system.portfolio_handler.get_active_portfolios = MagicMock(  # type: ignore[method-assign]
        return_value=[p1, p2])

    with pytest.raises(RuntimeError, match="at most one active portfolio"):
        system._link_venue_account_to_portfolios()

    # The guard raises BEFORE any assignment — no portfolio received the shared
    # venue account (each ``.account`` is an untouched auto-child mock, not it).
    assert p1.account is not system._venue_account
    assert p2.account is not system._venue_account
