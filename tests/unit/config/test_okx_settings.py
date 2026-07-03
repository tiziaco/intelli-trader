"""Tests for the OKX credential layer (CONN-06 / D-10).

T-02-01-LEAK: these tests use monkeypatched env values only — never real secrets — and
assert the SecretStr masking rather than printing ``.get_secret_value()``. The auth
triple (key + secret + passphrase) loads from the plain ``OKX_API_*`` env names with NO
``ITRADER_`` prefix (D-10 revises CONN-06).
"""

import pytest
from pydantic import ValidationError

from itrader.config.okx_settings import OkxSettings

_KEY = "demo-key-abc123"
_SECRET = "demo-secret-def456"
_PASSPHRASE = "demo-pass-ghi789"


@pytest.fixture
def okx_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear then set the OKX demo auth triple in the environment (synthetic values)."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE",
                "OKX_SANDBOX", "OKX_REGION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OKX_API_KEY", _KEY)
    monkeypatch.setenv("OKX_API_SECRET", _SECRET)
    monkeypatch.setenv("OKX_API_PASSPHRASE", _PASSPHRASE)


def test_loads_auth_triple_from_plain_okx_env(okx_env: None) -> None:
    """OKX_API_* (no prefix) round-trips through .get_secret_value()."""
    settings = OkxSettings()

    assert settings.api_key.get_secret_value() == _KEY
    assert settings.api_secret.get_secret_value() == _SECRET
    assert settings.api_passphrase.get_secret_value() == _PASSPHRASE


def test_no_itrader_prefix_used(monkeypatch: pytest.MonkeyPatch, okx_env: None) -> None:
    """A prefixed ITRADER_OKX_API_KEY does NOT feed the field — only the plain name does."""
    monkeypatch.setenv("ITRADER_OKX_API_KEY", "wrong-prefixed-value")

    settings = OkxSettings()

    assert settings.api_key.get_secret_value() == _KEY


def test_secrets_masked_in_repr_and_str(okx_env: None) -> None:
    """SecretStr keeps raw credentials out of repr/str (T-02-01-CRED)."""
    settings = OkxSettings()

    rendered = repr(settings) + str(settings)
    assert _KEY not in rendered
    assert _SECRET not in rendered
    assert _PASSPHRASE not in rendered
    assert "**********" in repr(settings)


def test_missing_passphrase_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The passphrase is required — the OKX auth triple is not optional."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE", "OKX_SANDBOX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OKX_API_KEY", _KEY)
    monkeypatch.setenv("OKX_API_SECRET", _SECRET)

    with pytest.raises(ValidationError):
        OkxSettings()


def test_sandbox_defaults_true(okx_env: None) -> None:
    """sandbox defaults to True (demo-first routing)."""
    assert OkxSettings().sandbox is True


def test_sandbox_env_override(monkeypatch: pytest.MonkeyPatch, okx_env: None) -> None:
    """OKX_SANDBOX flips the demo-routing flag."""
    monkeypatch.setenv("OKX_SANDBOX", "false")

    assert OkxSettings().sandbox is False


def test_unrelated_env_ignored(monkeypatch: pytest.MonkeyPatch, okx_env: None) -> None:
    """Unrelated env vars (ITRADER_*/DATABASE_*) are ignored (extra='ignore')."""
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ITRADER_DATABASE_PASSWORD", "not-mine")

    settings = OkxSettings()

    assert settings.api_key.get_secret_value() == _KEY
    assert not hasattr(settings, "log_level")
    assert not hasattr(settings, "password")


# --------------------------------------------------------------------------- region (OKX-REGION)


def test_region_defaults_to_global(okx_env: None) -> None:
    """region defaults to global -> REST host www.okx.com."""
    settings = OkxSettings()

    assert settings.region == "global"
    assert settings.rest_hostname == "www.okx.com"


@pytest.mark.parametrize(
    ("region", "sandbox", "rest_host", "ws_host"),
    [
        ("global", True, "www.okx.com", "wspap.okx.com"),
        ("global", False, "www.okx.com", "ws.okx.com"),
        ("eea", True, "eea.okx.com", "wseeapap.okx.com"),
        ("eea", False, "eea.okx.com", "wseea.okx.com"),
    ],
)
def test_region_sandbox_derive_both_hosts(
    monkeypatch: pytest.MonkeyPatch,
    okx_env: None,
    region: str,
    sandbox: bool,
    rest_host: str,
    ws_host: str,
) -> None:
    """All 4 (region, sandbox) combos derive the VERIFIED REST + WS hosts."""
    monkeypatch.setenv("OKX_REGION", region)
    monkeypatch.setenv("OKX_SANDBOX", "true" if sandbox else "false")

    settings = OkxSettings()

    assert settings.rest_hostname == rest_host
    assert settings.ws_hostname == ws_host


def test_invalid_region_raises(monkeypatch: pytest.MonkeyPatch, okx_env: None) -> None:
    """A non-{global,eea} OKX_REGION fails loud with a pydantic ValidationError."""
    monkeypatch.setenv("OKX_REGION", "apac")

    with pytest.raises(ValidationError):
        OkxSettings()


def test_hostname_field_removed(okx_env: None) -> None:
    """The old OKX_HOSTNAME/hostname field no longer exists on OkxSettings."""
    assert not hasattr(OkxSettings(), "hostname")
