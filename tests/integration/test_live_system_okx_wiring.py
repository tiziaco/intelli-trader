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
