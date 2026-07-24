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

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger
from itrader.venues.registry import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    from itrader.config.credential_resolver import CredentialResolver
    from itrader.connectors.base import LiveConnector
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle

#: The OKX VENUE-level market type (11.2-06, D-38) — the value ``build_bundle`` used
#: to hardcode inline. It stays "spot" and is deliberately NOT delegated to
#: ``VenueAccountConfig``'s own ``"derivative"`` default: ``VenueAccount`` derives
#: ``_cash_stream_nets_holds = market_type != "spot"``, so falling through to that
#: default would invert CASH ACCOUNTING for every OKX account whose row names no
#: market type. The hardcode was removed to make the ACCOUNT-level key live, not to
#: change what an account that names nothing gets.
_OKX_DEFAULT_MARKET_TYPE: Literal["spot", "derivative"] = "spot"

#: The account-level, NON-SECRET connection knobs ``OkxSettings`` accepts (D-38).
#: ``market_type`` is NOT here — it is a bundle/account knob, not a session one, and
#: ``OkxSettings`` has no such field.
_OKX_CONNECTION_KNOBS = ("sandbox", "region")


def _connection_overrides(spec: Any) -> dict[str, Any]:
    """The account's own non-secret connection knobs, or ``{}`` (11.2-06, D-38).

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

    CR-05 — a supplied ``secret_ref`` must resolve to the COMPLETE credential set; an
    INCOMPLETE prefix is REFUSED, never completed. ``OkxSettings`` is a
    ``pydantic_settings.BaseSettings``, so every field a partial resolved mapping omits
    is silently filled from the ambient global ``OKX_API_*`` set — authenticating
    account B's bundle as whichever account the process environment happens to hold,
    with a perfectly stable UID that D-04's trust-on-first-use then records as this
    account's. This is the FIELD-granularity twin of the REFERENCE-granularity T-11-18
    rule the resolver already enforces.
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
        # 11.2-06 (D-38): the account's OWN non-secret connection knobs, merged onto the
        # spec from its ``venue_accounts.config_json`` by ``VenueAccountManager``. They
        # decide WHICH HOST this session reaches — ``region`` selects the regional entity
        # (an EEA key answers 50119 on the global host) and ``sandbox`` selects demo vs
        # PRODUCTION. Supplied as INIT kwargs, which are pydantic-settings' HIGHEST
        # priority source, so an account that pins them is not silently overridden by the
        # ambient ``OKX_SANDBOX`` / ``OKX_REGION`` environment. This is the same
        # init-kwargs-outrank-env premise the CR-05 gate below rests on, and the CR-05
        # required set is unaffected: both knobs carry defaults, so neither is REQUIRED.
        connection = _connection_overrides(spec)
        if self._resolver is None or secret_ref is None:
            # LEGACY single-account path: no pointer means the pre-MPORT-06 deployment
            # with one global OKX_API_* set. This is NOT the T-11-18 fail-open case —
            # T-11-18 forbids falling back when a well-formed pointer resolves to
            # NOTHING, and the resolver RAISES there (never returns an empty mapping).
            # An account with no pointer at all simply has no per-account credentials.
            #
            # OkxSettings fields are env-populated (validation_alias OKX_API_*), so the
            # credentials are still sourced from the environment here; only the D-38
            # connection knobs (never a credential) are supplied as kwargs. The former
            # ``# type: ignore[call-arg]`` is gone because the ``**`` splat of a
            # ``dict[str, Any]`` already makes mypy stop treating the alias-bound fields
            # as missing named arguments — the suppression became unused, not unneeded.
            return OkxConnector(OkxSettings(**connection))

        # A resolution failure PROPAGATES: an operator typo in secret_ref must stop the
        # connect, not quietly authenticate as whichever account the ambient process
        # environment happens to hold (T-11-18).
        resolved = self._resolver.resolve(secret_ref)

        # CR-05 — COMPLETENESS GATE. OkxSettings is a pydantic_settings.BaseSettings, so
        # any REQUIRED field this mapping omits is silently completed from the ambient
        # global OKX_API_* environment: account B's bundle would then authenticate as
        # whichever account the process env holds, and D-04's UID guard would NOT catch
        # it (the ambient secret belongs to a real account whose UID is stable and gets
        # trust-on-first-use recorded as this account's).
        #
        # The required set is DERIVED from the model by CLASS access — never instance
        # access, which pydantic deprecates and `filterwarnings=["error"]` would turn
        # into a failure — so the gate cannot drift from the model when a credential
        # field is added. Required == credential today (the auth triple); `sandbox` and
        # `region` carry defaults and are correctly excluded.
        #
        # WHY NOT suppress the settings' env source instead (no settings_customise_sources
        # override, no model_construct, no parallel non-BaseSettings DTO): init kwargs are
        # ALREADY the highest-priority pydantic-settings source, so once this gate
        # guarantees every required field arrives in `resolved`, no credential can be
        # env-completed — suppression buys nothing. It would also strip `sandbox` and
        # `region`, the non-secret connection knobs `credential_resolver.py`'s own
        # docstring assigns to the account row's `config_json` rather than a credential
        # prefix (and which the resolver could not carry anyway: it wraps every value in
        # SecretStr and `region` is a Literal). Silently flipping a configured EEA
        # production account to the `global`/sandbox defaults is a worse failure than the
        # one being fixed — OKX answers 50119 on the wrong regional host.
        from itrader.core.exceptions import CredentialResolutionError

        required = {
            name
            for name, field in OkxSettings.model_fields.items()
            if field.is_required()
        }
        missing = required - set(resolved)
        if missing:
            # Field NAMES only. CredentialResolutionError is a redaction boundary with no
            # slot that could carry a VALUE, and nothing here builds a message from one.
            raise CredentialResolutionError(
                secret_ref,
                f"resolved {sorted(set(resolved) & required)} but is missing the "
                f"required credential field(s) {sorted(missing)} — refusing to complete "
                "the credential set from the ambient process environment",
            )

        # The resolved mapping is Mapping[str, SecretStr] keyed by the model's field
        # names; OkxSettings opts into populate_by_name so it is feedable verbatim.
        # It lives in memory for the lifetime of this connector and is written nowhere.
        #
        # 11.2-06 (D-38): the two mappings are merged into ONE dict rather than splatted
        # as two ``**`` arguments. A resolver whose prefix happened to expose a
        # ``*_SANDBOX`` / ``*_REGION`` var would put that key in BOTH mappings, and two
        # splats collide with a bare ``TypeError: got multiple values``. Merging makes
        # the precedence explicit instead: the account row's own ``config_json`` wins,
        # which is the same account-overrides-everything-else rule D-38 states.
        return OkxConnector(OkxSettings(**{**resolved, **connection}))


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

    def _account_id_for(self, config: Any) -> str:
        """The account id ``new_account`` must mint under, or RAISE (D-11, 11.1-09).

        ONE rule, and NO fallback behind it: the id is ``config.account_id`` and
        comes from nowhere else. An absent id RAISES — there is no legitimate
        "default" venue account to mint under (the MPORT-01 edge probe), because
        minting under whichever account happens to be at hand attaches a caller that
        named no account to a real venue balance.

        D-03/F-1 (11.1-09): this used to be a TWO-branch rule, because
        ``new_account`` also took a ``portfolio_ref`` and had to read the id off the
        portfolio when one was supplied — deliberately WITHOUT falling back to the
        bundle's own id, since that fallback is the exact conflation D-11 closes.
        That branch is gone with the parameter. Note what did NOT change: the caller
        that knows a portfolio's account (``PortfolioHandler.add_portfolio``) now
        puts that id on ``config`` before calling, so the id still comes from the
        portfolio when there is one — the resolution moved OUT of this method, it was
        not weakened into a fallback. The refusal below is the D-11 invariant itself
        and is copied verbatim; only the interpolated source word changed, because
        the config is now where the id is expected from.
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
        """Mint the ``VenueAccount`` for one account, over ITS OWN connector (D-03).

        D-12: the connector comes from the shared ``ConnectorProvider`` memo keyed on
        ``(venue, account_id)``, so this account and the bundle's exchange share ONE
        authenticated session per account — and two different accounts get two
        different sessions built from two different resolved credential sets (the
        11-04 resolver reads each account's own ``secret_ref``).

        D-11: ``account_id`` is passed EXPLICITLY as a required keyword. There is no
        arm here that can absorb its arguments and return a shared account.

        D-03: ``config.enable_margin`` is deliberately UNREAD here. Venue-cached
        truth has no margin-vs-cash leaf to choose — the venue owns the balance — so
        the flag is the compute arm's alone, which is why the owning
        ``PortfolioConfig`` rather than the ``venue_accounts`` row is its home.
        """
        # D-04: OKX/account concretions lazy-imported inside the body (never module top).
        from itrader.portfolio_handler.account import VenueAccount

        account_id = self._account_id_for(config)
        connector = config.connectors.get("okx", account_id, config.spec)
        return VenueAccount(
            connector,
            config.quote_currency,
            account_id=account_id,
            # D-23 (11.2-08): carry the venue half of the pair onto the leaf so it is
            # the ONE storage site ``Portfolio.venue_name`` reads back.
            venue_name=getattr(config, "venue_name", None) or "okx",
            market_type=config.market_type,
            symbol=config.symbol,
        )

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the OKX execution ``VenueBundle`` over the shared connector."""
        # D-04: OKX concretions lazy-imported inside the body (never module top).
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.venues.bundle import VenueAccountConfig, VenueBundle

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
        account_id = spec.account_id or DEFAULT_ACCOUNT_ID
        connector = connectors.get("okx", account_id, spec)

        exchange = OkxExchange(ctx.bus, connector)

        # 11.2-06 (D-38): the market type now FLOWS FROM THE ACCOUNT — its own
        # ``venue_accounts.config_json``, merged onto the spec by
        # ``VenueAccountManager.bring_online`` — instead of being hardcoded here. This
        # line is BEHAVIOURAL, not cosmetic: ``VenueAccount.__init__`` derives
        # ``_cash_stream_nets_holds = market_type != "spot"``, which decides whether the
        # leaf's cash channel nets a venue-side hold into ``_venue_balance``. On a spot
        # leaf the local pending overlay is the SOLE tracker of a resting order's hold
        # and must be held until terminal release; a derivative leaf may drop it on ack.
        # Getting this value wrong therefore OVER- or UNDER-states buying power.
        # An account naming nothing keeps the venue-level ``"spot"`` this call site used
        # to hardcode — never ``VenueAccountConfig``'s ``"derivative"`` default.
        market_type = getattr(spec, "market_type", None) or _OKX_DEFAULT_MARKET_TYPE

        # 11-07 (D-10): the per-account knobs `new_account` mints from. The bundle's
        # own `account_id` is carried so the facade's no-portfolio `account_factory()`
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
            # 11-07: the former `(*args, **kwargs)` catch-all — which absorbed a
            # portfolio argument and returned ONE shared unscoped account with no
            # error — is GONE and STAYS gone. This is a thin, explicitly-signed
            # KEYWORD-ONLY adapter that DELEGATES to the typed `new_account`, so the
            # bundle field and the Protocol method can never mint different accounts.
            # `initial_cash` / `enable_margin` / `state_storage` are accepted because
            # both bundles are called uniformly (the compute arm needs all three) and
            # are not meaningful for venue-cached truth, where the balance comes from
            # the venue rather than from wiring.
            #
            # D-11: an OMITTED `account_id` falls back to the BUNDLE's own id — the
            # documented facade call site, which mints THIS bundle's account. That is
            # NOT the cross-fallback D-11 forbids: no portfolio is involved, so there
            # is no unnamed caller being attached to someone else's balance. That
            # fallback is PRESERVED exactly as it was.
            #
            # WR-03 — a SUPPLIED id must MATCH the bundle's own or it is REFUSED. The
            # `replace(...)` below moves the id but NOT `account_config.spec`, which is
            # the spec (and therefore the `secret_ref`) the BUNDLE was built for — the
            # two cannot be moved independently. Minting another id from this bundle
            # would hand `new_account` a mismatched pair, and
            # `connectors.get("okx", <other id>, <this bundle's spec>)` would memoize a
            # session under the OTHER account's key while authenticated from THIS
            # account's credentials: an order routed to a different REAL venue balance,
            # with every lookup above it still looking correct (D-11/D-12). Refusing a
            # mismatch does NOT widen anything — D-11's rule that the closure must never
            # prefer its own id over a supplied one is untouched, because a supplied id
            # that disagrees now yields no account at all rather than the wrong one.
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
        account_id = spec.account_id or DEFAULT_ACCOUNT_ID
        connector = connectors.get("okx", account_id, spec)

        return OkxDataProvider(
            connector,
            symbol=stream.okx_stream_symbol,
            timeframe=stream.okx_stream_timeframe,
        )
