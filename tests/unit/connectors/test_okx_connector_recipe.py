"""``build_okx_connector``: per-account credential isolation and routing precedence.

The recipe form of what was the OKX connector plugin's ``build``. These are the assertions
that make per-account isolation REAL rather than nominal — without them two ``account_id``s
connect with identical credentials while the system believes they are separate accounts,
and orders route to the wrong real money.

Every test here is I/O-free: ``OkxConnector`` opens no socket at construction (``connect()``
is deferred), so the whole credential path is exercisable offline.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is folder-derived.
Indentation: 4-space.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from itrader.connectors.okx import build_okx_connector
from itrader.core.exceptions import CredentialResolutionError
from itrader.venues.catalog import CATALOG

_OKX = CATALOG["okx"]


@pytest.fixture
def ambient_creds(monkeypatch):
    """A global ``OKX_API_*`` triple — the single-credential-set deployment shape."""
    monkeypatch.setenv("OKX_API_KEY", "ambient-key")
    monkeypatch.setenv("OKX_API_SECRET", "ambient-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "ambient-pass")
    monkeypatch.delenv("OKX_SANDBOX", raising=False)
    monkeypatch.delenv("OKX_REGION", raising=False)


class _Resolver:
    """A ``CredentialResolver`` returning a fixed mapping, recording what it was asked."""

    def __init__(self, resolved: dict[str, Any]) -> None:
        self._resolved = resolved
        self.asked: list[str] = []

    def resolve(self, reference: str | None) -> dict[str, Any]:
        self.asked.append(str(reference))
        return self._resolved


def _spec(**fields: Any) -> Any:
    return SimpleNamespace(**fields)


def _complete(prefix: str) -> dict[str, Any]:
    """A complete resolved credential set, distinguishable per account."""
    return {
        "api_key": SecretStr(f"{prefix}-key"),
        "api_secret": SecretStr(f"{prefix}-secret"),
        "api_passphrase": SecretStr(f"{prefix}-pass"),
    }


# --------------------------------------------------------------------------- #
# Per-account credential isolation
# --------------------------------------------------------------------------- #
def test_a_resolved_pointer_supplies_the_account_credentials(ambient_creds) -> None:
    """The account's OWN resolved material reaches the session, not the ambient env.

    Asserted on the credential VALUES the settings object carries, because the failure this
    guards is silent: an ambient fallback produces a working, connectable session that
    simply belongs to the wrong account.
    """
    resolver = _Resolver(_complete("acct-a"))
    connector = build_okx_connector(
        descriptor=_OKX,
        spec=_spec(secret_ref="env:ACCT_A"),
        resolver=resolver,
    )
    settings = connector._settings
    assert settings.api_key.get_secret_value() == "acct-a-key"
    assert settings.api_secret.get_secret_value() == "acct-a-secret"
    assert settings.api_passphrase.get_secret_value() == "acct-a-pass"
    assert resolver.asked == ["env:ACCT_A"]


def test_two_accounts_get_different_credentials(ambient_creds) -> None:
    """The isolation premise, stated directly: two pointers, two credential sets."""
    a = build_okx_connector(
        descriptor=_OKX, spec=_spec(secret_ref="env:A"),
        resolver=_Resolver(_complete("a")))
    b = build_okx_connector(
        descriptor=_OKX, spec=_spec(secret_ref="env:B"),
        resolver=_Resolver(_complete("b")))
    assert (a._settings.api_key.get_secret_value()
            != b._settings.api_key.get_secret_value())


def test_no_pointer_falls_back_to_the_ambient_credential_set(ambient_creds) -> None:
    """An account with NO pointer has no per-account credentials — a supported shape.

    Distinct from the fail-open case below, where a well-formed pointer resolves to
    something incomplete.
    """
    connector = build_okx_connector(
        descriptor=_OKX, spec=_spec(secret_ref=None), resolver=_Resolver({}))
    assert connector._settings.api_key.get_secret_value() == "ambient-key"


def test_no_resolver_falls_back_to_the_ambient_credential_set(ambient_creds) -> None:
    """A deployment with one global credential set needs no resolver."""
    connector = build_okx_connector(
        descriptor=_OKX, spec=_spec(secret_ref="env:IGNORED"), resolver=None)
    assert connector._settings.api_key.get_secret_value() == "ambient-key"


# --------------------------------------------------------------------------- #
# The completeness gate — the fail-open this exists to close
# --------------------------------------------------------------------------- #
def test_an_incomplete_resolution_is_refused_not_completed(ambient_creds) -> None:
    """A partial resolution must NOT be topped up from the ambient environment.

    ``OkxSettings`` is a ``BaseSettings``, so any omitted field would otherwise be filled
    silently from the process env — producing a session authenticated with a MIX of two
    accounts' material. Refusing is the only safe answer.
    """
    resolver = _Resolver({"api_key": SecretStr("partial-key")})
    with pytest.raises(CredentialResolutionError) as excinfo:
        build_okx_connector(
            descriptor=_OKX, spec=_spec(secret_ref="env:PARTIAL"), resolver=resolver)
    message = str(excinfo.value)
    assert "api_secret" in message and "api_passphrase" in message


def test_the_refusal_carries_field_names_but_no_credential_values(ambient_creds) -> None:
    """The error is a redaction boundary — it never carries credential material."""
    resolver = _Resolver({"api_key": SecretStr("super-secret-value")})
    with pytest.raises(CredentialResolutionError) as excinfo:
        build_okx_connector(
            descriptor=_OKX, spec=_spec(secret_ref="env:PARTIAL"), resolver=resolver)
    assert "super-secret-value" not in str(excinfo.value)


def test_the_required_set_is_derived_from_the_descriptors_model(ambient_creds) -> None:
    """The gate reads the model named by the descriptor, so it tracks a new field for free.

    Proven by handing the recipe a descriptor whose model requires MORE than OKX's three:
    the extra required field must be reported missing. A hand-written required list could
    not notice.
    """
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class _ExtraSettings(BaseSettings):
        model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

        api_key: SecretStr = Field()
        api_secret: SecretStr = Field()
        api_passphrase: SecretStr = Field()
        api_broker_id: SecretStr = Field()

    descriptor = SimpleNamespace(credential_model=_ExtraSettings)
    with pytest.raises(CredentialResolutionError) as excinfo:
        build_okx_connector(
            descriptor=descriptor, spec=_spec(secret_ref="env:A"),
            resolver=_Resolver(_complete("a")))
    assert "api_broker_id" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Routing precedence — sandbox/region are the demo-vs-production switch
# --------------------------------------------------------------------------- #
def test_the_accounts_own_routing_knobs_win_over_the_environment(monkeypatch) -> None:
    """An account that PINS production must not be flipped to demo by ambient env.

    The worst direction of this failure is a production key on a demo host (orders vanish)
    or a demo key on production (orders are real). The account row wins.
    """
    monkeypatch.setenv("OKX_SANDBOX", "true")
    monkeypatch.setenv("OKX_REGION", "global")
    connector = build_okx_connector(
        descriptor=_OKX,
        spec=_spec(secret_ref="env:A", sandbox=False, region="eea"),
        resolver=_Resolver(_complete("a")))
    assert connector._settings.sandbox is False
    assert connector._settings.region == "eea"
    # The (region, sandbox) pair — not a bare sandbox ternary — derives BOTH hosts.
    assert connector._settings.ws_hostname == "wseea.okx.com"
    assert connector._settings.rest_hostname == "eea.okx.com"


def test_a_knob_the_account_does_not_name_leaves_the_venue_default(monkeypatch) -> None:
    """Absence is not an override.

    Forwarding ``sandbox=None`` would either fail validation or coerce a configured
    PRODUCTION account onto the demo host, so a knob the account does not name must not be
    forwarded at all.
    """
    monkeypatch.setenv("OKX_SANDBOX", "false")
    monkeypatch.delenv("OKX_REGION", raising=False)
    connector = build_okx_connector(
        descriptor=_OKX,
        spec=_spec(secret_ref="env:A", sandbox=None, region=None),
        resolver=_Resolver(_complete("a")))
    assert connector._settings.sandbox is False
    assert connector._settings.region == "global"


def test_routing_knobs_are_derived_from_field_metadata_not_a_hand_list() -> None:
    """The routing set comes off the model's field metadata (the D-6 declaration).

    A parallel hand-written tuple of knob names must be edited in step with the model, and
    the failure when it is not is silent: a newly added routing field is simply never
    forwarded, so an account that pins it keeps the venue default with nothing reporting
    the omission. Asserted on the derivation helper directly, and cross-checked against the
    model so the two cannot drift.
    """
    from itrader.config.okx_settings import OkxSettings
    from itrader.connectors.okx import _routing_fields

    assert set(_routing_fields(OkxSettings)) == {"sandbox", "region"}

    declared_routing = {
        name
        for name, field in OkxSettings.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get("kind") == "routing"
    }
    assert set(_routing_fields(OkxSettings)) == declared_routing


def test_every_credential_field_declares_a_kind() -> None:
    """A field added without a kind is a visible omission, not a silently mis-sorted value.

    The secret/routing split decides what may be logged and persisted, so an unclassified
    field is a question nobody answered rather than a safe default.
    """
    from itrader.config.okx_settings import OkxSettings

    unclassified = [
        name
        for name, field in OkxSettings.model_fields.items()
        if not isinstance(field.json_schema_extra, dict)
        or field.json_schema_extra.get("kind") not in {"secret", "routing"}
    ]
    assert not unclassified, (
        f"OkxSettings fields declare no kind: {unclassified} — every field is either "
        "credential material (secret) or a connection knob (routing)")


def test_the_secret_and_routing_kinds_partition_the_model() -> None:
    """The two kinds are exhaustive and disjoint, and the secrets are the required set."""
    from itrader.config.okx_settings import OkxSettings

    by_kind: dict[str, set[str]] = {"secret": set(), "routing": set()}
    for name, field in OkxSettings.model_fields.items():
        assert isinstance(field.json_schema_extra, dict)
        by_kind[str(field.json_schema_extra["kind"])].add(name)

    assert by_kind["secret"] == {"api_key", "api_secret", "api_passphrase"}
    assert by_kind["routing"] == {"sandbox", "region"}
    assert not (by_kind["secret"] & by_kind["routing"])


# --------------------------------------------------------------------------- #
# Public sessions
# --------------------------------------------------------------------------- #
def test_a_public_session_is_refused_loudly_rather_than_returned_authenticated(
    ambient_creds,
) -> None:
    """``spec=None`` asks for a credential-free session, which OKX cannot build yet.

    ``OkxConnector`` reads all three credential fields unconditionally when it builds its
    ccxt client, so there is no credential-free construction to return. The refusal is the
    deliberate behaviour: silently handing back an AUTHENTICATED session under a public
    name would recreate the borrowed-credentialed-session arrangement that public sessions
    exist to remove, and would do it invisibly. Wiring the data plane onto public sessions
    requires a public arm in the client build.
    """
    with pytest.raises(NotImplementedError) as excinfo:
        build_okx_connector(descriptor=_OKX, spec=None, resolver=None)
    assert "credential-free" in str(excinfo.value)
