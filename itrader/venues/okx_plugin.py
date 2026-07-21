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

Stream target: the OKX stream symbol/timeframe are read from the injected
``ctx.config.stream`` INSIDE ``build*`` (IN-01 — ``EngineContext.config`` is the
process-wide ``ITraderConfig`` singleton wired at the composition root; one wiring
source, no inline default-construction). The account is a single default
``VenueAccount`` (D-07 — the per-portfolio ``account_id`` fan-out is P11).

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.config.credential_resolver import CredentialResolver
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

    11-04 (D-02/D-12) — PER-ACCOUNT credentials. ``ConnectorProvider._memo`` is keyed
    on the ``(venue, account_id)`` PAIR, but the ``_plugins`` map behind it is
    venue-only and ``build`` receives one spec — so a bare ``OkxConnector(OkxSettings())``
    means two ``account_id``s connect with IDENTICAL global credentials while the
    system believes they are separate accounts. Orders then route to the wrong REAL
    account and reconciliation succeeds cleanly against it. The injected
    ``CredentialResolver`` + the spec's ``secret_ref`` POINTER are what make the
    isolation real.
    """

    def __init__(self, resolver: "CredentialResolver | None" = None) -> None:
        # Optional so the pre-MPORT-06 single-account wiring (and the inertness probe,
        # which constructs this plugin bare) keeps working. The live composition root
        # injects an EnvCredentialResolver.
        self._resolver = resolver
        self.logger = get_itrader_logger().bind(component="OkxConnectorPlugin")

    def build(self, spec: Any) -> LiveConnector:
        """Construct one ``OkxConnector`` from the account's RESOLVED credentials (D-02)."""
        # D-04 layer 1+3: BOTH the concretion import and the credential construction
        # live here, never at module top or register time.
        from itrader.config.okx_settings import OkxSettings
        from itrader.connectors.okx import OkxConnector

        secret_ref = getattr(spec, "secret_ref", None)
        if self._resolver is None or secret_ref is None:
            # LEGACY single-account path: no pointer means the pre-MPORT-06 deployment
            # with one global OKX_API_* set. This is NOT the T-11-18 fail-open case —
            # T-11-18 forbids falling back when a well-formed pointer resolves to
            # NOTHING, and the resolver RAISES there (never returns an empty mapping).
            # An account with no pointer at all simply has no per-account credentials.
            #
            # OkxSettings fields are env-populated (validation_alias OKX_API_*), so a
            # bare OkxSettings() is the correct runtime construction; mypy sees the
            # fields as required named args (matches connectors/okx.py:81 convention).
            return OkxConnector(OkxSettings())  # type: ignore[call-arg]

        # A resolution failure PROPAGATES: an operator typo in secret_ref must stop the
        # connect, not quietly authenticate as whichever account the ambient process
        # environment happens to hold (T-11-18).
        resolved = self._resolver.resolve(secret_ref)
        # The resolved mapping is Mapping[str, SecretStr] keyed by the model's field
        # names; OkxSettings opts into populate_by_name so it is feedable verbatim.
        # It lives in memory for the lifetime of this connector and is written nowhere.
        return OkxConnector(OkxSettings(**resolved))  # type: ignore[arg-type]


class OkxVenuePlugin:
    """The OKX execution ``VenuePlugin`` — builds an ``OkxExchange`` ``VenueBundle`` (D-04).

    ``build_bundle`` borrows the shared ``(venue, account_id)`` connector from the
    ``ConnectorProvider`` (so it never opens a second ccxt.pro client the data arm
    already built, D-03), wraps it in an ``OkxExchange``, and supplies a
    ``VenueAccount`` factory. The concretion imports live inside the body (D-04); the
    stream target is the injected ``ctx.config.stream`` read (IN-01).
    """

    def __init__(self) -> None:
        self.logger = get_itrader_logger().bind(component="OkxVenuePlugin")

    @property
    def credential_model(self) -> type[Any] | None:
        """The OKX credential model — ``OkxSettings`` (D-03).

        A ``@property`` with a LAZY import, NOT ``credential_model = OkxSettings``:
        the module-scope AST gate in ``tests/unit/venues/test_okx_plugin.py`` rejects
        any module-level import whose name contains ``okx_settings``, so the plain
        class attribute would redden the D-04 inertness discipline. Reading this
        property pulls the pure pydantic settings class only — no ccxt.
        """
        from itrader.config.okx_settings import OkxSettings

        return OkxSettings

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """OKX's own account UID for the connected session, or ``None`` (D-04).

        Reads ``GET /api/v5/account/config`` through the connector's synchronous
        ``call`` RPC (the ONLY sanctioned async->sync bridge) and returns
        ``data[0].uid``.

        DEFENSIVE BY CONTRACT: every failure mode — a session that is not connected,
        an OKX error envelope, a missing ``data`` list, a renamed ``uid`` field —
        yields ``None`` rather than raising, because D-04 is observe-only and an
        exception here would abort an otherwise healthy connect (T-11-19). The
        trade-off is that a renamed field degrades the guard silently, so the miss is
        LOGGED here and the guard warns again at its own boundary.

        NOTE (operator verification): the endpoint/field pair below could not be
        confirmed against a live authenticated session in the build environment (the
        available demo account is a single EEA sub-account), so real-venue
        confirmation is recorded as a manual verification in ``11-VALIDATION.md``.
        """
        try:
            response = connector.call(connector.client.private_get_account_config())
            entries = (response or {}).get("data") or []
            uid = entries[0].get("uid") if entries else None
        except Exception:
            self.logger.warning(
                "OKX venue-UID fetch failed; the D-04 spoofing guard is inert for "
                "this connect",
                exc_info=True,
            )
            return None
        if not uid:
            self.logger.warning(
                "OKX account config carried no 'uid'; the D-04 spoofing guard is "
                "inert for this connect"
            )
            return None
        return str(uid)

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the OKX execution ``VenueBundle`` over the shared connector."""
        # D-04: OKX concretions lazy-imported inside the body (never module top).
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.portfolio_handler.account import VenueAccount
        from itrader.venues.bundle import VenueBundle

        # IN-01: read the live stream target from the injected ITraderConfig
        # (EngineContext.config is the process-wide singleton wired at the composition
        # root) — one wiring source, no inline default-construction.
        stream = ctx.config.stream
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
    The concretion import lives inside the body (D-04); the stream target is the
    injected ``ctx.config.stream`` read (IN-01).
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the OKX ``LiveDataProvider`` over the shared connector."""
        # D-04: OKX concretion lazy-imported inside the body (never module top).
        from itrader.price_handler.providers.okx_provider import OkxDataProvider

        # IN-01: the injected ITraderConfig stream target (one wiring source).
        stream = ctx.config.stream

        # D-03: SAME memoized connector key as OkxVenuePlugin.build_bundle.
        account_id = spec.account_id or "default"
        connector = connectors.get("okx", account_id, spec)

        return OkxDataProvider(
            connector,
            symbol=stream.okx_stream_symbol,
            timeframe=stream.okx_stream_timeframe,
        )
