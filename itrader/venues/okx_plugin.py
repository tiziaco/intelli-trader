"""Concrete OKX venue / data / connector plugins (05-05, VENUE-02, D-03/D-04/D-07).

Formalizes the ``if self.exchange == 'okx'`` composition-root block
(``live_trading_system.py`` ~470-552) into three registrable plugins so a venue
registers WITHOUT editing ``LiveTradingSystem``:

  - ``OkxConnectorPlugin`` — the per-venue connector build recipe
    (``ConnectorProvider`` calls ``build(spec)`` once per ``(venue, account_id)``).
  - ``OkxVenuePlugin`` — builds the execution ``VenueBundle`` (an ``OkxExchange``
    over the shared connector + a ``VenueAccount`` factory).
  - ``OkxDataPlugin`` — builds the ``OkxDataProvider`` over the SAME shared
    connector (both arms call ``connectors.get("okx", account_id, spec)`` so one
    ``ccxt.pro`` client serves the exec + data arms for a key, D-03).

CRITICAL — D-04 triple-deferral laziness (the P5 inertness gate, cred-less
machines): EVERY ``build*`` keeps the OKX concretion ``import`` AND the
``OkxSettings()`` credential construction INSIDE the method body. This module
imports NOTHING heavy at module scope — ``from __future__ import annotations`` +
``TYPE_CHECKING``-only annotations keep it ccxt/async/SQL-free, so importing (and
registering) an OKX plugin pulls no ``ccxt.pro`` / ``OkxConnector`` / ``OkxSettings``
(register ≠ build). Hoisting any of these imports to module top silently reddens
``tests/integration/test_okx_inertness.py`` — DO NOT hoist them.

Stream target: the OKX stream symbol/timeframe are read from a default-constructed
``StreamSettings`` INSIDE ``build*`` (the P1 config seam, ``config/stream.py``),
mirroring the retired composition-root ``_STREAM_SETTINGS`` reads. The account is a
single default ``VenueAccount`` (D-07 — the per-portfolio ``account_id`` fan-out is
P11).

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle


class OkxConnectorPlugin:
    """The OKX ``ConnectorPlugin`` build recipe (VENUE-03 / D-04 triple-deferral).

    ``build`` is the ONLY place ``OkxSettings`` (the ``OKX_API_*`` ``SecretStr``
    triple) is constructed and the ``OkxConnector`` (ccxt.pro) concretion is
    imported. Both live inside the method body so registering this plugin (storing
    an object) pulls nothing heavy and needs no credentials; the network
    ``connect()`` stays deferred to ``start()``.
    """

    def build(self, spec: Any) -> LiveConnector:
        """Construct one ``OkxConnector(OkxSettings())`` (concretion + creds inside)."""
        # D-04 layer 1+3: BOTH the concretion import and the OkxSettings()
        # credential construction live here, never at module top or register time.
        from itrader.config.okx_settings import OkxSettings
        from itrader.connectors.okx import OkxConnector

        # OkxSettings fields are env-populated (validation_alias OKX_API_*), so a
        # bare OkxSettings() is the correct runtime construction; mypy sees the
        # fields as required named args (matches connectors/okx.py:81 convention).
        return OkxConnector(OkxSettings())  # type: ignore[call-arg]


class OkxVenuePlugin:
    """The OKX execution ``VenuePlugin`` — builds an ``OkxExchange`` ``VenueBundle`` (D-04).

    ``build_bundle`` borrows the shared ``(venue, account_id)`` connector from the
    ``ConnectorProvider`` (so it never opens a second ccxt.pro client the data arm
    already built, D-03), wraps it in an ``OkxExchange``, and supplies a
    ``VenueAccount`` factory. The concretion imports + ``StreamSettings()`` read
    are all inside the body (D-04).
    """

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the OKX execution ``VenueBundle`` over the shared connector."""
        # D-04: OKX concretions lazy-imported inside the body (never module top).
        from itrader.config.stream import StreamSettings
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.portfolio_handler.account import VenueAccount
        from itrader.venues.bundle import VenueBundle

        # The P1 config seam: read the live stream target from a default-constructed
        # StreamSettings (mirrors the retired _STREAM_SETTINGS composition-root read).
        stream = StreamSettings()
        symbol = stream.okx_stream_symbol
        # D-03 (quote-wiring): the settlement currency is the WIRED pair's right leg
        # (USDC for BTC/USDC — never the USDT default); spot per-symbol truth is
        # derived from total[BASE] (mirror live_trading_system.py:498-503).
        quote = symbol.split("/")[1]

        # D-03/D-07: the SAME memoized connector for ("okx", account_id) the data
        # arm borrows; account_id=None resolves to the "default" logical account.
        account_id = spec.account_id or "default"
        connector = connectors.get("okx", account_id, spec)

        exchange = OkxExchange(ctx.bus, connector)

        def account_factory(*args: Any, **kwargs: Any) -> Account:
            # D-07: a single default VenueAccount bound to the shared connector (the
            # per-portfolio account_id fan-out is P11). Args are absorbed so the
            # 05-06 assemble_venue can call this uniformly with the paper factory.
            return VenueAccount(
                connector,
                quote_currency=quote,
                market_type="spot",
                symbol=symbol,
            )

        # lifecycle stays None — assemble_venue (05-06) builds the VenueLifecycle.
        return VenueBundle(
            exchange=exchange,
            account_factory=account_factory,
            connector=connector,
        )


class OkxDataPlugin:
    """The OKX ``DataProviderPlugin`` — builds an ``OkxDataProvider`` (D-03/D-04).

    ``build_provider`` borrows the SAME ``(venue, account_id)`` connector the
    execution plugin used (D-03), so the exec + data arms share one ccxt.pro client.
    The concretion import + ``StreamSettings()`` read live inside the body (D-04).
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the OKX ``LiveDataProvider`` over the shared connector."""
        # D-04: OKX concretion lazy-imported inside the body (never module top).
        from itrader.config.stream import StreamSettings
        from itrader.price_handler.providers.okx_provider import OkxDataProvider

        stream = StreamSettings()

        # D-03: SAME memoized connector key as OkxVenuePlugin.build_bundle.
        account_id = spec.account_id or "default"
        connector = connectors.get("okx", account_id, spec)

        return OkxDataProvider(
            connector,
            symbol=stream.okx_stream_symbol,
            timeframe=stream.okx_stream_timeframe,
        )
