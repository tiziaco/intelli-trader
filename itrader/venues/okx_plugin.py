"""Concrete OKX venue / data / connector plugins.

Three registrable plugins so a venue registers WITHOUT editing ``LiveTradingSystem``:

  - ``OkxConnectorPlugin`` — the per-venue connector build recipe
    (``ConnectorProvider`` calls ``build(spec)`` once per ``(venue, account_id)``).
  - ``OkxVenuePlugin`` — builds the execution ``VenueBundle`` (an ``OkxExchange``
    over the shared connector + a ``VenueAccount`` factory).
  - ``OkxDataPlugin`` — builds the ``OkxDataProvider`` over the SAME shared
    connector (both arms call ``connectors.get("okx", account_id, spec)`` so one
    ``ccxt.pro`` client serves the exec + data arms for a key).

CRITICAL — laziness gate: EVERY ``build*`` keeps the OKX concretion ``import`` AND
the ``OkxSettings()`` credential construction INSIDE the method body, never at
module top or register time. This module itself imports NOTHING heavy at module
scope (``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations), so registering an OKX plugin pulls no ``ccxt.pro`` / ``OkxConnector``
/ ``OkxSettings`` — register ≠ build. Hoisting any of these imports to module top
silently reddens ``tests/integration/test_okx_inertness.py``.

Stream target: the OKX stream symbol/timeframe are read from the injected
``ctx.config.stream`` INSIDE ``build*`` — ``EngineContext.config`` is the
process-wide ``ITraderConfig`` singleton wired at the composition root, so there is
one wiring source and no inline default-construction.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.config.credential_resolver import CredentialResolver
    from itrader.connectors.base import LiveConnector
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle

#: The OKX venue-level market type default. Deliberately NOT delegated to
#: ``VenueAccountConfig``'s own ``"derivative"`` default: ``VenueAccount`` derives
#: ``_cash_stream_nets_holds = market_type != "spot"``, so falling through to that
#: default would invert cash accounting for every OKX account whose row names no
#: market type.
_OKX_DEFAULT_MARKET_TYPE: Literal["spot", "derivative"] = "spot"

#: The account-level, non-secret connection knobs ``OkxSettings`` accepts.
#: ``market_type`` is NOT here — it is a bundle/account knob, not a session one, and
#: ``OkxSettings`` has no such field.
_OKX_CONNECTION_KNOBS = ("sandbox", "region")


def _connection_overrides(spec: Any) -> dict[str, Any]:
    """The account's own non-secret connection knobs, or ``{}``.

    Only knobs the account ACTUALLY names are returned. A ``None`` must never be
    forwarded to ``OkxSettings``: the precedence rule is "a key the account does not
    name leaves the venue default in force", and passing ``sandbox=None`` through
    would break it in the worst direction — ``None`` is not a valid bool, so it would
    either fail validation or coerce a configured PRODUCTION account onto the demo
    host. Absence is not an override.
    """
    overrides: dict[str, Any] = {}
    for name in _OKX_CONNECTION_KNOBS:
        value = getattr(spec, name, None)
        if value is not None:
            overrides[name] = value
    return overrides


class OkxConnectorPlugin:
    """The OKX ``ConnectorPlugin`` build recipe.

    ``build`` is the ONLY place ``OkxSettings`` (the ``OKX_API_*`` ``SecretStr``
    triple) is constructed and the ``OkxConnector`` (ccxt.pro) concretion is
    imported. Both live inside the method body so registering this plugin (storing
    an object) pulls nothing heavy and needs no credentials; the network
    ``connect()`` stays deferred to ``start()``.

    ``ConnectorProvider._memo`` is keyed on the ``(venue, account_id)`` pair, but a
    bare ``OkxConnector(OkxSettings())`` would authenticate every account from the
    SAME global environment — two accounts would connect with identical credentials
    while the system believes them separate, and orders would route to the wrong
    real account with reconciliation succeeding cleanly against it. The injected
    ``CredentialResolver`` + the spec's ``secret_ref`` pointer are what make the
    per-account isolation real.

    A supplied ``secret_ref`` must resolve to the COMPLETE credential set — an
    incomplete prefix is refused, never completed, because ``OkxSettings`` is a
    ``pydantic_settings.BaseSettings`` and would otherwise silently fill any missing
    field from the ambient global ``OKX_API_*`` environment.
    """

    def __init__(self, resolver: "CredentialResolver | None" = None) -> None:
        # Optional: the inertness probe constructs this plugin bare. The live
        # composition root injects an EnvCredentialResolver.
        self._resolver = resolver
        self.logger = get_itrader_logger().bind(component="OkxConnectorPlugin")

    def build(self, spec: Any) -> LiveConnector:
        """Construct one ``OkxConnector`` from the account's resolved credentials."""
        from itrader.config.okx_settings import OkxSettings
        from itrader.connectors.okx import OkxConnector

        secret_ref = getattr(spec, "secret_ref", None)
        # The account's OWN non-secret connection knobs, merged onto the spec from its
        # `venue_accounts.config_json` by `VenueAccountManager`. `region` selects the
        # regional entity (an EEA key answers 50119 on the global host) and `sandbox`
        # selects demo vs production. Supplied as init kwargs — pydantic-settings'
        # highest-priority source — so an account that pins them is not silently
        # overridden by the ambient `OKX_SANDBOX` / `OKX_REGION` environment.
        connection = _connection_overrides(spec)
        if self._resolver is None or secret_ref is None:
            # No pointer: single global OKX_API_* deployment. An account with no
            # pointer simply has no per-account credentials — this is not the
            # fail-open case below, where a well-formed pointer resolves to nothing.
            return OkxConnector(OkxSettings(**connection))

        # A resolution failure PROPAGATES: an operator typo in secret_ref must stop
        # the connect, not quietly authenticate as whichever account the ambient
        # process environment happens to hold.
        resolved = self._resolver.resolve(secret_ref)

        # Completeness gate: OkxSettings is a pydantic_settings.BaseSettings, so any
        # required field this mapping omits would otherwise be silently completed
        # from the ambient global OKX_API_* environment — authenticating as whichever
        # account the process env holds. The required set is derived from the model
        # by CLASS access (never instance access, which pydantic deprecates and
        # `filterwarnings=["error"]` turns into a failure), so the gate tracks the
        # model automatically when a credential field is added.
        #
        # Suppressing the settings' env source instead would buy nothing once this
        # gate holds (init kwargs already outrank env), and would also strip
        # `sandbox`/`region` — silently flipping a configured EEA production account
        # to the global/sandbox defaults is a worse failure than the one being fixed.
        from itrader.core.exceptions import CredentialResolutionError

        required = {
            name
            for name, field in OkxSettings.model_fields.items()
            if field.is_required()
        }
        missing = required - set(resolved)
        if missing:
            # Field names only: CredentialResolutionError is a redaction boundary and
            # never carries a credential value.
            raise CredentialResolutionError(
                secret_ref,
                f"resolved {sorted(set(resolved) & required)} but is missing the "
                f"required credential field(s) {sorted(missing)} — refusing to complete "
                "the credential set from the ambient process environment",
            )

        # Merged into ONE dict rather than splatted as two `**` arguments: a resolver
        # whose prefix exposed a `*_SANDBOX`/`*_REGION` var would put that key in both
        # mappings, and two splats collide with a bare TypeError. Merging makes the
        # precedence explicit — the account row's own connection knobs win.
        return OkxConnector(OkxSettings(**{**resolved, **connection}))


class OkxVenuePlugin:
    """The OKX execution ``VenuePlugin`` — builds an ``OkxExchange`` ``VenueBundle``.

    ``build_bundle`` borrows the shared ``(venue, account_id)`` connector from the
    ``ConnectorProvider`` — so it never opens a second ccxt.pro client the data arm
    already built — wraps it in an ``OkxExchange``, and supplies a ``VenueAccount``
    factory.
    """

    def __init__(self) -> None:
        self.logger = get_itrader_logger().bind(component="OkxVenuePlugin")

    @property
    def credential_model(self) -> type[Any] | None:
        """The OKX credential model — ``OkxSettings``.

        A ``@property`` with a lazy import, not ``credential_model = OkxSettings``:
        the module-scope AST gate in ``tests/unit/venues/test_okx_plugin.py`` rejects
        any module-level import whose name contains ``okx_settings``, so a plain
        class attribute would break the inertness discipline this module keeps.
        """
        from itrader.config.okx_settings import OkxSettings

        return OkxSettings

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """OKX's own account UID for the connected session, or ``None``.

        Reads ``GET /api/v5/account/config`` through the connector's synchronous
        ``call`` RPC (the only sanctioned async->sync bridge) and returns
        ``data[0].uid``.

        Defensive by contract: every failure mode — a session that is not connected,
        an OKX error envelope, a missing ``data`` list, a renamed ``uid`` field —
        yields ``None`` rather than raising, because the venue-UID guard this feeds
        is observe-only and an exception here would abort an otherwise healthy
        connect. The trade-off is that a renamed field degrades the guard silently,
        so the miss is logged here and the guard warns again at its own boundary.

        The endpoint/field pair could not be confirmed against a live authenticated
        session in the build environment (only a single EEA demo sub-account was
        available) — treat as unverified against a real venue.
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

    def _account_id_for(self, config: Any) -> str:
        """The account id ``new_account`` must mint under, or RAISE.

        One rule, no fallback behind it: the id is ``config.account_id`` and comes
        from nowhere else. An absent id RAISES — there is no legitimate "default"
        venue account to mint under, because minting under whichever account
        happens to be at hand attaches a caller that named no account to a real
        venue balance. The caller that knows a portfolio's account
        (``PortfolioHandler.add_portfolio``) puts that id on ``config`` before
        calling.
        """
        account_id = getattr(config, "account_id", None)
        source = "venue account config"
        if not account_id:
            raise ValidationError(
                "account_id",
                str(account_id),
                f"Cannot mint an OKX venue account: the {source} names no venue "
                "account, and there is no legitimate default one (D-11)",
            )
        return str(account_id)

    def new_account(self, config: Any) -> Account:
        """Mint the ``VenueAccount`` for one account, over its own connector.

        The connector comes from the shared ``ConnectorProvider`` memo keyed on
        ``(venue, account_id)``, so this account and the bundle's exchange share one
        authenticated session per account, and two different accounts get two
        different sessions built from two different resolved credential sets.

        ``config.enable_margin`` is deliberately UNREAD here: venue-cached truth has
        no margin-vs-cash leaf to choose — the venue owns the balance — so the flag
        is the compute arm's alone, and its home is the owning ``PortfolioConfig``
        rather than the ``venue_accounts`` row.
        """
        from itrader.portfolio_handler.account import VenueAccount

        account_id = self._account_id_for(config)
        connector = config.connectors.get("okx", account_id, config.spec)
        return VenueAccount(
            connector,
            config.quote_currency,
            account_id=account_id,
            # Carry the venue half of the pair onto the leaf: the one storage site
            # `Portfolio.venue_name` reads back.
            venue_name=getattr(config, "venue_name", None) or "okx",
            market_type=config.market_type,
            symbol=config.symbol,
        )

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the OKX execution ``VenueBundle`` over the shared connector."""
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.venues.bundle import VenueAccountConfig, VenueBundle

        # The live stream target: EngineContext.config is the process-wide
        # ITraderConfig singleton wired at the composition root, so there is one
        # wiring source and no inline default-construction.
        stream = ctx.config.stream
        symbol = stream.okx_stream_symbol
        # The settlement currency is the wired pair's right leg (USDC for
        # BTC/USDC) — never a hardcoded USDT default.
        quote = symbol.split("/")[1]

        # The SAME memoized connector for ("okx", account_id) the data arm borrows.
        # `account_id` is read UNCOERCED: a `None` is a wiring bug and RAISES rather
        # than being memoized under a fabricated "default" key while the exchange
        # registry keys the same account differently — normalizing in two places is
        # how the two end up disagreeing about the same real account.
        account_id = getattr(spec, "account_id", None)
        if account_id is None:
            raise ValidationError(
                "account_id",
                str(account_id),
                "Cannot build the OKX venue bundle: the spec names no venue account, "
                "and there is no legitimate default one (ACCT-04/WR-03)",
            )
        connector = connectors.get("okx", account_id, spec)

        exchange = OkxExchange(ctx.bus, connector)

        # The market type flows from the account's own `venue_accounts.config_json`,
        # merged onto the spec by `VenueAccountManager.bring_online`.
        # `VenueAccount.__init__` derives `_cash_stream_nets_holds = market_type !=
        # "spot"`, which decides whether the leaf's cash channel nets a venue-side
        # hold into `_venue_balance` — on a spot leaf the local pending overlay is the
        # sole tracker of a resting order's hold and must be held until terminal
        # release, while a derivative leaf may drop it on ack. Getting this wrong
        # over- or under-states buying power.
        market_type = getattr(spec, "market_type", None) or _OKX_DEFAULT_MARKET_TYPE

        # The per-account knobs `new_account` mints from. The bundle's own
        # `account_id` is carried so the facade's no-portfolio `account_factory()`
        # call site mints THIS bundle's account rather than an unscoped one.
        account_config = VenueAccountConfig(
            account_id=account_id,
            venue_name="okx",
            connectors=connectors,
            spec=spec,
            quote_currency=quote,
            market_type=market_type,
            symbol=symbol,
        )

        def account_factory(
            *,
            initial_cash: Any = 0.0,
            enable_margin: bool = False,
            account_id: str | None = None,
            state_storage: Any = None,
            venue_name: str | None = None,
        ) -> Account:
            # A thin, explicitly-signed keyword-only adapter that delegates to the
            # typed `new_account`, so the bundle field and the Protocol method can
            # never mint different accounts. `initial_cash` / `enable_margin` /
            # `state_storage` are accepted because both bundles are called uniformly
            # (the compute arm needs all three) but are not meaningful for
            # venue-cached truth, where the balance comes from the venue.
            #
            # An OMITTED `account_id` falls back to the bundle's own id — the
            # documented facade call site that mints THIS bundle's account. A
            # SUPPLIED id must MATCH the bundle's own or it is refused: `replace(...)`
            # below moves the id but not `account_config.spec` — the spec (and
            # therefore the `secret_ref`) the bundle was built for — so minting
            # another id from this bundle would hand `new_account` a mismatched pair.
            # `connectors.get("okx", <other id>, <this bundle's spec>)` would then
            # memoize a session under the OTHER account's key while authenticated
            # from THIS account's credentials — an order routed to a different real
            # venue balance, with every lookup above it still looking correct.
            if account_id is not None and account_id != account_config.account_id:
                raise ValidationError(
                    "account_id",
                    str(account_id),
                    f"Refusing to mint OKX venue account '{account_id}' from the "
                    f"bundle built for '{account_config.account_id}': the bundle "
                    f"carries '{account_config.account_id}'s resolved credentials on "
                    "its spec, and the spec does not travel with a substituted "
                    f"account_id — the connector would be memoized under "
                    f"('okx', '{account_id}') while authenticated from "
                    f"'{account_config.account_id}'s secret_ref, attaching this id to "
                    "a DIFFERENT real venue balance. Build a bundle for this account "
                    "instead (D-11/D-12).",
                )
            return self.new_account(replace(
                account_config,
                account_id=account_id or account_config.account_id,
                initial_cash=initial_cash,
                enable_margin=enable_margin,
                state_storage=state_storage,
            ))

        # lifecycle stays None — assemble_venue builds the VenueLifecycle.
        return VenueBundle(
            exchange=exchange,
            account_factory=account_factory,
            connector=connector,
        )


class OkxDataPlugin:
    """The OKX ``DataProviderPlugin`` — builds an ``OkxDataProvider``.

    ``build_provider`` borrows the SAME ``(venue, account_id)`` connector the
    execution plugin used, so the exec + data arms share one ccxt.pro client.
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the OKX ``LiveDataProvider`` over the shared connector."""
        from itrader.price_handler.providers.okx_provider import OkxDataProvider

        stream = ctx.config.stream

        # SAME memoized connector key as OkxVenuePlugin.build_bundle: `account_id` is
        # read UNCOERCED — a `None` RAISES rather than coercing onto a "default" key —
        # so the data arm constructs the SAME (venue, account_id) pair the exec arm
        # does. A divergent memo key would open two sessions for one account.
        account_id = getattr(spec, "account_id", None)
        if account_id is None:
            raise ValidationError(
                "account_id",
                str(account_id),
                "Cannot build the OKX data provider: the spec names no venue account, "
                "and there is no legitimate default one (ACCT-04/WR-03)",
            )
        connector = connectors.get("okx", account_id, spec)

        return OkxDataProvider(
            connector,
            symbol=stream.okx_stream_symbol,
            timeframe=stream.okx_stream_timeframe,
        )
