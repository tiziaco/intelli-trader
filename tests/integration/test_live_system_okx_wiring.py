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

from itrader.trading_system.live_trading_system import LiveTradingSystem


def _strip_okx_env(monkeypatch) -> None:
    """Remove the OKX credential triple so a stray requirement surfaces as a failure."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm's ``OkxSettings()`` constructs.

    The connector constructor is I/O-free (``connect()`` is deferred to ``start()``),
    so a stubbed credential triple is enough to build ``LiveTradingSystem(exchange="okx")``
    fully offline — no socket, no ``load_markets`` round-trip.
    """
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_construct_non_okx_venue_needs_no_okx_credentials(monkeypatch) -> None:
    """A non-OKX LiveTradingSystem constructs with the OKX creds absent (CR-02)."""
    _strip_okx_env(monkeypatch)

    # Must NOT raise pydantic.ValidationError for missing OKX_API_* — the OKX arm is gated.
    system = LiveTradingSystem(exchange="binance")

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

    system = LiveTradingSystem(exchange="binance")

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

    system = LiveTradingSystem(exchange="okx")

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

    system = LiveTradingSystem(exchange="okx")

    assert system._okx_data_provider is not None
    # The provider holds the feed's update() as its closed-bar sink.
    assert system._okx_data_provider._bar_sink == system.feed.update


def test_okx_live_feed_capacity_derives_to_strategy_warmup(monkeypatch) -> None:
    """After session init the LIVE feed's cache_capacity() derives to the max strategy warmup (D-13).

    The D-13 consumer registration in ``_initialize_live_session`` makes
    ``cache_capacity()`` equal the deepest registered strategy warmup — for the golden
    SMA_MACD that is 100, not the newest-bar floor (1). Drives the session init directly
    (offline; no OKX connect, no stream).
    """
    _set_okx_env(monkeypatch)

    system = LiveTradingSystem(exchange="okx")
    # Pre-registration: no raw-bar consumer yet -> the newest-bar floor.
    assert system.feed.cache_capacity() == 1

    # Run only the session-init wiring (membership derive + D-13 registration + bind);
    # this performs no network I/O (the OKX connect lives in start(), not here).
    system._initialize_live_session()

    expected = max(
        (s.warmup for s in system.strategies_handler.strategies), default=1)
    assert system.feed.cache_capacity() == expected
