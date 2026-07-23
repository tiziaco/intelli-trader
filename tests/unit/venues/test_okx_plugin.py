"""Unit contract for the OKX venue/data/connector plugins (05-05, VENUE-02, D-04).

Drives ``OkxVenuePlugin.build_bundle`` / ``OkxDataPlugin.build_provider`` with a
FAKE ``ConnectorProvider`` (``get`` returns a trivial fake connector) + a fake
``ctx`` (``bus`` attr) + a fake ``spec`` (``account_id=None``), asserting:

  - the bundle shape (exchange is an ``OkxExchange`` wrapping the fake connector,
    ``account_factory`` is callable and mints a ``VenueAccount``, ``connector`` is
    the SAME fake instance, ``lifecycle`` is ``None``),
  - the data provider is an ``OkxDataProvider`` bound to the SAME memoized
    connector (both arms call ``connectors.get("okx", "default", spec)``),
  - importing ``itrader.venues.okx_plugin`` pulls NO ccxt at module scope (D-04
    triple-deferral — the concretion import lives inside ``build*``).

No creds / no ccxt.pro client are needed: the OKX concretion constructors only
BIND the injected connector (no network at construction), so a trivial fake
connector suffices. The register-vs-build inertness proof is the subprocess gate
in ``tests/integration/test_okx_inertness.py`` (Task 3).

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class _FakeConnector:
    """Trivial ``LiveConnector`` stand-in — the OKX concretions only bind it."""


class _FakeConnectorProvider:
    """Records every ``get`` call and hands back ONE memoized fake connector.

    Mirrors the real ``ConnectorProvider.get(venue, account_id, spec)`` memo: the
    same ``(venue, account_id)`` key returns the SAME instance, proving both the
    exec bundle and the data provider borrow one connector (D-03).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._memo: dict[tuple[str, str], _FakeConnector] = {}

    def get(self, venue: str, account_id: str, spec: Any) -> _FakeConnector:
        self.calls.append((venue, account_id, spec))
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = _FakeConnector()
        return self._memo[key]


def _fake_ctx() -> SimpleNamespace:
    """A fake ``EngineContext`` exposing the ``bus`` + ``config`` the plugin reads."""
    from itrader.config import ITraderConfig

    return SimpleNamespace(bus=object(), config=ITraderConfig())


def _fake_spec(account_id: str | None = None) -> SimpleNamespace:
    """A fake ``SystemSpec`` exposing only ``account_id`` (defaulted None)."""
    return SimpleNamespace(account_id=account_id)


def test_okx_plugin_module_imports_no_ccxt() -> None:
    """Importing the plugin module pulls no ccxt at MODULE scope (D-04 layer 1)."""
    import ast
    import pathlib

    import itrader.venues.okx_plugin as mod

    source = pathlib.Path(mod.__file__).read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        # Only inspect MODULE-LEVEL imports (direct children of the module body):
        # a lazy import inside a build* method body is exactly what D-04 requires.
        if isinstance(node, ast.Module):
            for child in node.body:
                if isinstance(child, ast.Import):
                    imported += [alias.name for alias in child.names]
                elif isinstance(child, ast.ImportFrom) and child.module:
                    imported.append(child.module)
    forbidden = [
        name
        for name in imported
        if any(
            tok in name
            for tok in ("ccxt", "itrader.connectors.okx", "okx_settings")
        )
    ]
    assert not forbidden, (
        "D-04 violation: itrader.venues.okx_plugin imports an OKX concretion / "
        f"ccxt at module scope: {forbidden!r} (must be lazy inside build*)"
    )


def test_okx_venue_plugin_builds_bundle_wrapping_the_connector() -> None:
    """build_bundle returns an OkxExchange-backed VenueBundle over the fake connector."""
    from itrader.execution_handler.exchanges.okx import OkxExchange
    from itrader.portfolio_handler.account import VenueAccount
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id=None)

    bundle = OkxVenuePlugin().build_bundle(ctx, spec, connectors)

    assert isinstance(bundle, VenueBundle)
    assert isinstance(bundle.exchange, OkxExchange)
    # account_id=None -> the "default" logical account key (D-07).
    assert connectors.calls == [("okx", "default", spec)]
    # The bundle carries the SAME connector the provider handed out.
    assert bundle.exchange._connector is connectors.get("okx", "default", spec)
    assert bundle.connector is connectors.get("okx", "default", spec)
    # 11-09: the dead ``VenueBundle.lifecycle`` field is gone — assemble_venue returns
    # the lifecycle beside the bundle, so there was never anything to store here.
    assert not hasattr(bundle, "lifecycle")
    # account_factory mints a VenueAccount bound to the same connector.
    assert callable(bundle.account_factory)
    account = bundle.account_factory()
    assert isinstance(account, VenueAccount)
    assert account._connector is connectors.get("okx", "default", spec)


def test_okx_data_plugin_shares_the_same_connector() -> None:
    """build_provider returns an OkxDataProvider bound to the SAME memoized connector."""
    from itrader.price_handler.providers.okx_provider import OkxDataProvider
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id=None)

    bundle = OkxVenuePlugin().build_bundle(ctx, spec, connectors)
    provider = OkxDataPlugin().build_provider(ctx, spec, connectors)

    assert isinstance(provider, OkxDataProvider)
    # ONE connector for ("okx", "default") shared across BOTH builders (D-03):
    # two get() calls, one memoized instance.
    assert connectors.calls == [
        ("okx", "default", spec),
        ("okx", "default", spec),
    ]
    assert provider._connector is bundle.connector


def test_okx_plugins_honor_explicit_account_id() -> None:
    """A non-None spec.account_id keys the connector memo (per-account fan-out seam)."""
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id="sub-7")

    OkxVenuePlugin().build_bundle(ctx, spec, connectors)
    OkxDataPlugin().build_provider(ctx, spec, connectors)

    assert connectors.calls == [
        ("okx", "sub-7", spec),
        ("okx", "sub-7", spec),
    ]


# --------------------------------------------------------------------------- #
# 11-04 (D-03): the plugin is self-describing for credentials + venue UID
# --------------------------------------------------------------------------- #
def test_okx_venue_plugin_exposes_its_credential_model() -> None:
    """``credential_model`` is the OKX settings class (D-03).

    This is what lets a future integrations page render per-venue form fields from
    the venue REGISTRY with zero hardcoding: the alternative — the web app importing
    each venue's settings model directly — makes the registry stop being
    self-describing, so adding a venue would mean editing the web app too.
    """
    from itrader.config.okx_settings import OkxSettings
    from itrader.venues.okx_plugin import OkxVenuePlugin

    assert OkxVenuePlugin().credential_model is OkxSettings


def test_okx_venue_plugin_fetches_the_account_uid_through_the_connector() -> None:
    """``fetch_venue_uid`` returns the venue's own account UID for the session (D-04)."""
    from itrader.venues.okx_plugin import OkxVenuePlugin

    class _UidConnector:
        """A connector whose ``call`` returns the OKX account-config envelope."""

        @property
        def client(self) -> Any:
            return SimpleNamespace(
                private_get_account_config=lambda: {"data": [{"uid": "44219871"}]}
            )

        def call(self, coro: Any) -> Any:
            return coro

    assert OkxVenuePlugin().fetch_venue_uid(_UidConnector()) == "44219871"


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},            # authenticated but no account entry
        {"data": [{}]},          # entry present, uid field absent (venue renamed it)
        {"code": "50119"},       # an OKX error envelope, no data key at all
        None,                    # the venue returned nothing
    ],
)
def test_okx_fetch_venue_uid_returns_none_for_any_unexpected_shape(payload: Any) -> None:
    """A venue that does not supply the expected shape yields ``None``, never raises.

    D-04 is observe-only: an exception here would take down a connect path that is
    otherwise perfectly healthy (T-11-19).
    """
    from itrader.venues.okx_plugin import OkxVenuePlugin

    class _OddConnector:
        @property
        def client(self) -> Any:
            return SimpleNamespace(private_get_account_config=lambda: payload)

        def call(self, coro: Any) -> Any:
            return coro

    assert OkxVenuePlugin().fetch_venue_uid(_OddConnector()) is None


def test_okx_fetch_venue_uid_swallows_a_raising_connector() -> None:
    """A connector that RAISES (network down, auth revoked) yields ``None`` (T-11-19)."""
    from itrader.venues.okx_plugin import OkxVenuePlugin

    class _BrokenConnector:
        @property
        def client(self) -> Any:
            raise RuntimeError("session is not connected")

        def call(self, coro: Any) -> Any:  # pragma: no cover - never reached
            return coro

    assert OkxVenuePlugin().fetch_venue_uid(_BrokenConnector()) is None


# --------------------------------------------------------------------------- #
# 11-04 (D-02/D-12): the connector plugin resolves PER-ACCOUNT credentials
# --------------------------------------------------------------------------- #
def test_okx_connector_plugin_builds_from_the_resolved_secret_ref() -> None:
    """``build(spec)`` resolves ``spec.secret_ref`` through the injected resolver.

    THE load-bearing test for the D-12 caveat. Without this the plugin does a bare
    ``OkxConnector(OkxSettings())`` — reading the ONE global ``OKX_API_*`` set — so
    two ``account_id``s connect with IDENTICAL credentials while the phase claims
    per-account isolation is real. That is the exact misroute D-04's UID guard exists
    to detect, shipped green.
    """
    from pydantic import SecretStr

    from itrader.venues.okx_plugin import OkxConnectorPlugin

    class _RecordingResolver:
        def __init__(self) -> None:
            self.seen: list[str | None] = []

        def resolve(self, secret_ref: str | None) -> dict[str, SecretStr]:
            self.seen.append(secret_ref)
            return {
                "api_key": SecretStr(f"key-for-{secret_ref}"),
                "api_secret": SecretStr("secret"),
                "api_passphrase": SecretStr("passphrase"),
            }

    resolver = _RecordingResolver()
    spec = SimpleNamespace(account_id="acct-a", secret_ref="env:OKX_ACCT_A")

    connector = OkxConnectorPlugin(resolver=resolver).build(spec)

    assert resolver.seen == ["env:OKX_ACCT_A"]
    assert (
        connector._settings.api_key.get_secret_value() == "key-for-env:OKX_ACCT_A"
    )


def test_okx_connector_plugin_isolates_two_accounts() -> None:
    """Two specs with different ``secret_ref``s build connectors with DIFFERENT keys."""
    from pydantic import SecretStr

    from itrader.venues.okx_plugin import OkxConnectorPlugin

    class _PerRefResolver:
        def resolve(self, secret_ref: str | None) -> dict[str, SecretStr]:
            return {
                "api_key": SecretStr(f"{secret_ref}-key"),
                "api_secret": SecretStr("s"),
                "api_passphrase": SecretStr("p"),
            }

    plugin = OkxConnectorPlugin(resolver=_PerRefResolver())
    a = plugin.build(SimpleNamespace(account_id="a", secret_ref="env:A"))
    b = plugin.build(SimpleNamespace(account_id="b", secret_ref="env:B"))

    assert a._settings.api_key.get_secret_value() == "env:A-key"
    assert b._settings.api_key.get_secret_value() == "env:B-key"


def test_okx_connector_plugin_falls_back_to_ambient_env_only_without_a_pointer(
    monkeypatch: Any,
) -> None:
    """No ``secret_ref`` at all -> the legacy single-account ambient-env construction.

    This is NOT the T-11-18 fail-open case: T-11-18 forbids falling back when a
    well-formed pointer resolves to nothing (the resolver raises there). An account
    with NO pointer is the pre-MPORT-06 single-account deployment, which must keep
    working unchanged.
    """
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    monkeypatch.setenv("OKX_API_KEY", "ambient-key")
    monkeypatch.setenv("OKX_API_SECRET", "ambient-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "ambient-passphrase")

    connector = OkxConnectorPlugin().build(SimpleNamespace(account_id=None))

    assert connector._settings.api_key.get_secret_value() == "ambient-key"


def test_okx_connector_plugin_propagates_a_resolution_failure(monkeypatch: Any) -> None:
    """A pointer that fails to resolve RAISES — it never degrades to ambient creds.

    The T-11-18 elevation-of-privilege gate at the wiring boundary: an operator
    typo in ``secret_ref`` must stop the connect, not quietly authenticate as
    whichever account the process environment happens to hold.
    """
    from itrader.config.credential_resolver import EnvCredentialResolver
    from itrader.core.exceptions import CredentialResolutionError
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    monkeypatch.setenv("OKX_API_KEY", "ambient-key")
    monkeypatch.setenv("OKX_API_SECRET", "ambient-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "ambient-passphrase")

    plugin = OkxConnectorPlugin(resolver=EnvCredentialResolver())
    spec = SimpleNamespace(account_id="typo", secret_ref="env:OKX_ACCT_TYPO")

    with pytest.raises(CredentialResolutionError):
        plugin.build(spec)


def test_okx_connector_plugin_refuses_a_partial_per_account_credential_prefix(
    monkeypatch: Any,
) -> None:
    """CR-05: an INCOMPLETE per-account prefix is REFUSED, never env-completed.

    ``OkxSettings`` is a ``pydantic_settings.BaseSettings``, so every field the resolved
    mapping does not supply is silently completed from the ambient ``OKX_API_*``
    environment. Feeding it a partial mapping therefore builds a connector whose secret
    and passphrase belong to WHICHEVER account the process environment holds, while the
    system believes it authenticated account B. That is the exact credential bleed
    ``EnvCredentialResolver``'s fail-loud contract (T-11-18) exists to prevent,
    reintroduced one layer down at FIELD granularity instead of REFERENCE granularity.

    The D-04 UID guard does NOT catch it: the ambient secret belongs to a real account
    whose UID is perfectly stable, so trust-on-first-use records it as this account's.

    The other ``OKX_ACCT_B_*`` names are deleted defensively so a developer's real shell
    cannot green this test, and every value here is monkeypatched — nothing is sourced
    from the repo's ``.env``.
    """
    from itrader.config.credential_resolver import EnvCredentialResolver
    from itrader.core.exceptions import CredentialResolutionError
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    monkeypatch.setenv("OKX_ACCT_B_API_KEY", "acct-b-key")
    for name in ("OKX_ACCT_B_API_SECRET", "OKX_ACCT_B_API_PASSPHRASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OKX_API_KEY", "AMBIENT-KEY-VALUE")
    monkeypatch.setenv("OKX_API_SECRET", "AMBIENT-SECRET-VALUE")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "AMBIENT-PASSPHRASE-VALUE")

    plugin = OkxConnectorPlugin(resolver=EnvCredentialResolver())
    spec = SimpleNamespace(account_id="acct-b", secret_ref="env:OKX_ACCT_B")

    with pytest.raises(CredentialResolutionError) as caught:
        plugin.build(spec)

    message = str(caught.value)
    # The message names the MISSING FIELD NAMES so an operator can act without
    # opening the source...
    assert "api_secret" in message
    assert "api_passphrase" in message
    assert "env:OKX_ACCT_B" in message
    # ...and NEVER a credential value. CredentialResolutionError is a redaction
    # boundary: it has no slot that could carry one, and nothing on this path may
    # build a message from one.
    for secret in (
        "acct-b-key", "AMBIENT-KEY-VALUE", "AMBIENT-SECRET-VALUE",
        "AMBIENT-PASSPHRASE-VALUE",
    ):
        assert secret not in message


def test_a_complete_per_account_prefix_beats_the_ambient_environment(
    monkeypatch: Any,
) -> None:
    """The premise the CR-05 gate rests on: init kwargs OUTRANK the env source.

    Gated rather than assumed. The fix deliberately does NOT suppress the settings'
    env source — doing so would also strip ``sandbox`` and ``region``, the non-secret
    connection knobs that belong in the account row's ``config_json``, and silently
    flipping a configured EEA production account to the ``global``/sandbox defaults is
    a worse failure than the one being fixed (OKX answers 50119 on the wrong regional
    host). The gate is what makes suppression unnecessary: once every REQUIRED — i.e.
    every credential — field is present in the resolved mapping, no credential can be
    env-completed.

    Also proves the fix did not break the happy path.
    """
    from itrader.config.credential_resolver import EnvCredentialResolver
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    monkeypatch.setenv("OKX_ACCT_B_API_KEY", "acct-b-key")
    monkeypatch.setenv("OKX_ACCT_B_API_SECRET", "acct-b-secret")
    monkeypatch.setenv("OKX_ACCT_B_API_PASSPHRASE", "acct-b-passphrase")
    monkeypatch.setenv("OKX_API_KEY", "AMBIENT-KEY-VALUE")
    monkeypatch.setenv("OKX_API_SECRET", "AMBIENT-SECRET-VALUE")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "AMBIENT-PASSPHRASE-VALUE")

    plugin = OkxConnectorPlugin(resolver=EnvCredentialResolver())
    connector = plugin.build(
        SimpleNamespace(account_id="acct-b", secret_ref="env:OKX_ACCT_B"))

    settings = connector._settings
    assert settings.api_key.get_secret_value() == "acct-b-key"
    assert settings.api_secret.get_secret_value() == "acct-b-secret"
    assert settings.api_passphrase.get_secret_value() == "acct-b-passphrase"


def test_the_credential_gate_covers_every_required_okx_settings_field() -> None:
    """The gate is DERIVED from the model, so it cannot drift when a field is added.

    A hardcoded triple would silently stop covering a fourth credential field the day
    one is introduced — and the failure mode would be the CR-05 bleed again, on the
    new field only, behind a green suite.
    """
    from itrader.config.okx_settings import OkxSettings

    required = {
        name for name, field in OkxSettings.model_fields.items()
        if field.is_required()
    }
    # The auth triple, and NOT ``sandbox`` / ``region`` — those carry defaults and are
    # non-secret connection knobs the resolver could not carry anyway (it wraps every
    # value in SecretStr and ``region`` is a Literal).
    assert required == {"api_key", "api_secret", "api_passphrase"}


def test_okx_connector_plugin_is_runtime_checkable_connector_plugin() -> None:
    """OkxConnectorPlugin satisfies the ConnectorPlugin Protocol structurally."""
    from itrader.connectors.provider import ConnectorPlugin
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    assert isinstance(OkxConnectorPlugin(), ConnectorPlugin)


def test_okx_plugins_satisfy_venue_and_data_protocols() -> None:
    """The venue/data plugins structurally satisfy their build Protocols."""
    from itrader.venues.bundle import DataProviderPlugin, VenuePlugin
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    assert isinstance(OkxVenuePlugin(), VenuePlugin)
    assert isinstance(OkxDataPlugin(), DataProviderPlugin)


# --------------------------------------------------------------------------- #
# new_account — per-portfolio minting (11-07, D-10/D-11/D-12)
# --------------------------------------------------------------------------- #
def _account_config(connectors: Any, spec: Any, account_id: str | None = None) -> Any:
    """The ``VenueAccountConfig`` the OKX arm is handed by its own ``build_bundle``."""
    from itrader.venues.bundle import VenueAccountConfig

    return VenueAccountConfig(
        account_id=account_id,
        connectors=connectors,
        spec=spec,
        quote_currency="USDC",
        market_type="spot",
        symbol="BTC/USDC",
    )


def test_new_account_scopes_the_account_to_the_configs_account_id() -> None:
    """new_account mints a VenueAccount carrying the CONFIG's account id (D-11).

    11.1-09 (D-03): the id used to arrive on a ``portfolio_ref`` parameter. It now
    rides on the config, put there by the caller that legitimately knows which
    account a portfolio names — the resolution MOVED, it was not dropped.
    """
    from itrader.portfolio_handler.account import VenueAccount
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")

    account = OkxVenuePlugin().new_account(
        _account_config(connectors, spec, "acct-a"))

    assert isinstance(account, VenueAccount)
    assert account.account_id == "acct-a"
    assert account._connector is connectors.get("okx", "acct-a", spec)


def test_two_account_ids_get_two_accounts_over_two_connectors() -> None:
    """D-12: two account ids -> two DISTINCT accounts over two DISTINCT connectors.

    This is the isolation premise of the whole phase. A shared connector would mean
    account B's venue truth (and its orders) traverse account A's authenticated
    session, which is a real-money wrong answer that no downstream assertion catches.
    """
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")
    plugin = OkxVenuePlugin()

    account_a = plugin.new_account(_account_config(connectors, spec, "acct-a"))
    account_b = plugin.new_account(_account_config(connectors, spec, "acct-b"))

    assert account_a is not account_b
    assert account_a.account_id == "acct-a"
    assert account_b.account_id == "acct-b"
    assert account_a._connector is not account_b._connector


def test_new_account_refuses_a_config_naming_no_account() -> None:
    """The D-11 refusal, asserted DIRECTLY on ``new_account`` (MPORT-01 edge probe).

    Deliberately independent of how the callers are shaped: 11.1-09 collapsed
    ``_account_id_for``'s two-rule branch into one, and the risk of that collapse is
    a silent cross-fallback that attaches a caller naming no account to whichever
    real venue balance is at hand. This test pins the refusal itself, so it survives
    regardless of which callers exist — the connectors and spec are fully wired here,
    so the ONLY reason to refuse is the absent id.
    """
    from itrader.core.exceptions import ValidationError
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")

    with pytest.raises(ValidationError):
        OkxVenuePlugin().new_account(_account_config(connectors, spec, None))


def test_account_factory_with_no_account_id_mints_the_bundles_own_account() -> None:
    """The facade's no-argument ``account_factory()`` mints THIS bundle's account.

    ``live_trading_system.py`` mints the facade's venue account with no portfolio.
    That omitted id resolves to the account the BUNDLE was built for — which is not
    the cross-fallback D-11 forbids, because no portfolio is involved and therefore
    no unnamed caller is being attached to someone else's balance.
    """
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")

    bundle = OkxVenuePlugin().build_bundle(_fake_ctx(), spec, connectors)

    assert bundle.account_factory().account_id == "acct-a"


def test_account_factory_refuses_a_supplied_id_the_bundle_was_not_built_for() -> None:
    """WR-03: a MISMATCHED supplied id is refused, not minted (D-11/D-12).

    ``_attach_venue_accounts`` looks a lifecycle up BY the portfolio's account id and
    then mints under it, so the id the closure receives must be honoured — if the
    closure preferred its bundle-level id, a portfolio would silently receive an
    account for a DIFFERENT real venue balance while every lookup above it still
    looked correct. That D-11 concern is why this closure may not widen a supplied id.

    But the id cannot travel ALONE. ``replace(...)`` overrides ``account_id`` and
    leaves ``account_config.spec`` — the spec (and ``secret_ref``) the BUNDLE was
    built for — so a mismatched pair reaches
    ``connectors.get("okx", <other id>, <this bundle's spec>)``, memoizing a session
    under the other account's key while authenticated from THIS account's
    credentials. Refusing is NOT widening: a disagreeing id now yields NO account
    rather than the wrong one, so D-11's rule survives intact and D-12's per-account
    credential isolation stops resting on caller discipline.
    """
    from itrader.core.exceptions import ValidationError
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")

    bundle = OkxVenuePlugin().build_bundle(_fake_ctx(), spec, connectors)

    with pytest.raises(ValidationError) as excinfo:
        bundle.account_factory(account_id="acct-b")

    # BOTH ids must be named: the message has to say which id was refused AND which
    # account's credentials the bundle actually carries, or an operator cannot tell
    # which of the two wirings is wrong.
    message = str(excinfo.value)
    assert "acct-b" in message
    assert "acct-a" in message
    # The refusal precedes the mint: no connector was ever keyed under the foreign id.
    assert ("okx", "acct-b") not in connectors._memo


def test_account_factory_accepts_a_supplied_id_matching_the_bundles_own() -> None:
    """The supplied-id path still mints — the WR-03 guard refuses only a MISMATCH.

    ``_attach_venue_accounts`` passes the id EXPLICITLY (never omitted), and the
    lifecycle it passes was looked up by that same id, so this is the real live call
    shape. If the guard rejected it too, every live portfolio would lose its venue
    account.
    """
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    spec = _fake_spec(account_id="acct-a")

    bundle = OkxVenuePlugin().build_bundle(_fake_ctx(), spec, connectors)

    assert bundle.account_factory(account_id="acct-a").account_id == "acct-a"


def test_bundle_account_factory_delegates_to_new_account() -> None:
    """The bundle field and the Protocol method can never mint different accounts.

    ``account_factory`` is retained (the facade and ``assemble_venue`` call it) but
    is now a thin adapter over ``new_account``, so there is exactly ONE minting
    implementation rather than two that can drift apart.

    WR-03: the delegation is proven on a MATCHING id. It used to be proven by minting
    ``acct-b`` from an ``acct-a`` bundle, which the guard now refuses — the property
    under test (one minting implementation, the connector coming from the shared
    ``(venue, account_id)`` memo) is unchanged, only the id it is demonstrated with.
    """
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id="acct-a")

    bundle = OkxVenuePlugin().build_bundle(ctx, spec, connectors)

    from_factory = bundle.account_factory(account_id="acct-a")
    assert from_factory.account_id == "acct-a"
    assert from_factory._connector is connectors.get("okx", "acct-a", spec)


def test_okx_account_factory_is_keyword_only_and_has_no_catch_all() -> None:
    """The 11-07 removal of the ``(*args, **kwargs)`` catch-all is NOT reverted.

    An arg-swallowing arm type-checks clean against a STRUCTURAL Protocol while
    silently returning one shared unscoped account — exactly the defect 11-07
    removed. Pinned on the SIGNATURE so a future widening fails here.
    """
    import inspect

    from itrader.venues.okx_plugin import OkxVenuePlugin

    bundle = OkxVenuePlugin().build_bundle(
        _fake_ctx(), _fake_spec(account_id="acct-a"), _FakeConnectorProvider())
    parameters = inspect.signature(bundle.account_factory).parameters

    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    ), f"account_factory must be keyword-only: {parameters!r}"
    assert set(parameters) == {
        "initial_cash", "enable_margin", "account_id", "state_storage"}
