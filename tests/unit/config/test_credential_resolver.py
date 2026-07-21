"""Unit contract for the ``CredentialResolver`` seam + ``EnvCredentialResolver`` (11-04, D-02, MPORT-06).

The credentials boundary: a durable ``venue_accounts`` row holds a POINTER
(``secret_ref``), never a secret. This resolver is what turns that pointer into
credential material at connect time, in memory, and the resolved mapping is never
written back to any store.

Load-bearing assertions here:

  - **T-11-18 (elevation of privilege):** a well-formed ``secret_ref`` that matches
    ZERO environment variables RAISES. It never returns an empty mapping and never
    falls through to the ambient process credentials — a silent fallback is exactly
    how account A's keys reach account B's connector.
  - **T-11-17 (information disclosure):** the resolved mapping is
    ``Mapping[str, SecretStr]``, so a ``repr`` of the mapping (or of any exception
    or log record carrying it) masks every value. Asserted structurally, not by
    prose.
  - **The round-trip:** the resolver's output must be feedable into ``OkxSettings``
    without transformation, which is the whole point of the scheme.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from itrader.config.credential_resolver import (
    CredentialResolver,
    EnvCredentialResolver,
)
from itrader.core.exceptions import CredentialResolutionError

# The three credential env vars a per-account prefix supplies. Values are obvious
# sentinels so a leak assertion can search for them verbatim.
_SEEDED = {
    "OKX_ACCT_A_API_KEY": "seeded-key-8f21",
    "OKX_ACCT_A_API_SECRET": "seeded-secret-3c07",
    "OKX_ACCT_A_API_PASSPHRASE": "seeded-passphrase-b514",
}


@pytest.fixture
def seeded_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Seed the ``OKX_ACCT_A_`` per-account prefix and CLEAR the ambient global set.

    Clearing ``OKX_API_*`` is what makes the T-11-18 no-fallback assertions real: if
    the resolver ever reached for the ambient process credentials, the test would
    still find a mapping and pass vacuously.
    """
    for name, value in _SEEDED.items():
        monkeypatch.setenv(name, value)
    for name in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(name, raising=False)
    return dict(_SEEDED)


# --------------------------------------------------------------------------- #
# The Protocol seam (D-02)
# --------------------------------------------------------------------------- #
def test_env_resolver_satisfies_the_runtime_checkable_protocol() -> None:
    """``EnvCredentialResolver`` is structurally a ``CredentialResolver``.

    ``@runtime_checkable`` so a Vault/AWS/GCP-backed implementation registered from
    the web app's own repo is swap-in with no ``itrader`` change (D-02).
    """
    assert isinstance(EnvCredentialResolver(), CredentialResolver)
    assert not isinstance(object(), CredentialResolver)


# --------------------------------------------------------------------------- #
# The env:<PREFIX> scheme (D-02 / D-12)
# --------------------------------------------------------------------------- #
def test_resolve_collects_the_prefixed_env_vars_keyed_by_lowercased_suffix(
    seeded_env: dict[str, str],
) -> None:
    """``env:OKX_ACCT_A`` collects ``OKX_ACCT_A_<SUFFIX>`` keyed by ``suffix.lower()``."""
    resolved = EnvCredentialResolver().resolve("env:OKX_ACCT_A")

    assert set(resolved) == {"api_key", "api_secret", "api_passphrase"}
    assert resolved["api_key"].get_secret_value() == seeded_env["OKX_ACCT_A_API_KEY"]
    assert resolved["api_secret"].get_secret_value() == seeded_env["OKX_ACCT_A_API_SECRET"]
    assert (
        resolved["api_passphrase"].get_secret_value()
        == seeded_env["OKX_ACCT_A_API_PASSPHRASE"]
    )


def test_resolve_isolates_accounts_by_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two account prefixes resolve to DIFFERENT material — the D-12 caveat closed.

    Without this, two ``account_id``s build two connectors reading IDENTICAL global
    credentials, which is precisely the misroute D-04's UID guard exists to detect.
    """
    monkeypatch.setenv("OKX_ACCT_A_API_KEY", "key-A")
    monkeypatch.setenv("OKX_ACCT_B_API_KEY", "key-B")

    resolver = EnvCredentialResolver()
    assert resolver.resolve("env:OKX_ACCT_A")["api_key"].get_secret_value() == "key-A"
    assert resolver.resolve("env:OKX_ACCT_B")["api_key"].get_secret_value() == "key-B"


def test_resolve_prefix_match_is_delimiter_anchored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``env:OKX_ACCT_A`` must not swallow ``OKX_ACCT_ABC_*`` (a bare-startswith bug).

    A bare ``startswith(prefix)`` would fold a DIFFERENT account's variables into
    this account's mapping — a cross-account credential leak from a naming
    coincidence. The match is anchored on the ``_`` delimiter.
    """
    monkeypatch.setenv("OKX_ACCT_A_API_KEY", "key-A")
    monkeypatch.setenv("OKX_ACCT_ABC_API_KEY", "key-ABC")

    resolved = EnvCredentialResolver().resolve("env:OKX_ACCT_A")

    assert set(resolved) == {"api_key"}
    assert resolved["api_key"].get_secret_value() == "key-A"


def test_resolve_none_is_the_documented_no_credentials_path() -> None:
    """``resolve(None)`` — the paper case, ``secret_ref`` NULL — is an empty mapping.

    A paper account has nothing to point at. This is the ONE case where an empty
    mapping is correct, and it is reached only via an explicit ``None``.
    """
    assert EnvCredentialResolver().resolve(None) == {}


# --------------------------------------------------------------------------- #
# Fail-loud (T-11-18) — never an empty mapping, never an ambient fallback
# --------------------------------------------------------------------------- #
def test_resolve_zero_matches_raises_rather_than_returning_empty(
    seeded_env: dict[str, str],
) -> None:
    """T-11-18: a well-formed ref matching NO env vars RAISES, naming the reference.

    The load-bearing negative: it must not return ``{}`` (which a caller could read
    as "no credentials needed") and must not fall back to the ambient ``OKX_API_*``
    set the fixture deliberately cleared.
    """
    with pytest.raises(CredentialResolutionError) as excinfo:
        EnvCredentialResolver().resolve("env:OKX_ACCT_NOPE")

    assert "env:OKX_ACCT_NOPE" in str(excinfo.value)


def test_resolve_unknown_scheme_raises_naming_scheme_and_supported_set() -> None:
    """An unrecognised scheme fails loud, naming both the scheme and what IS supported."""
    with pytest.raises(CredentialResolutionError) as excinfo:
        EnvCredentialResolver().resolve("vault:secret/okx/acct-a")

    message = str(excinfo.value)
    assert "vault" in message
    assert "env:" in message


def test_resolve_bare_reference_without_a_scheme_raises() -> None:
    """A reference with no scheme at all is not silently treated as an env prefix."""
    with pytest.raises(CredentialResolutionError):
        EnvCredentialResolver().resolve("OKX_ACCT_A")


def test_resolve_empty_prefix_raises_rather_than_collecting_the_whole_environment() -> None:
    """``env:`` (empty prefix) must RAISE, not sweep the entire process environment.

    A bare ``env:`` with a naive implementation matches every variable, handing the
    connector the whole environment as "credentials".
    """
    with pytest.raises(CredentialResolutionError):
        EnvCredentialResolver().resolve("env:")


# --------------------------------------------------------------------------- #
# T-11-17 — no credential value in any message or repr
# --------------------------------------------------------------------------- #
def test_resolved_values_are_secretstr_so_repr_masks_them(
    seeded_env: dict[str, str],
) -> None:
    """The mapping's ``repr`` leaks NO value — redaction is structural, not prose.

    Any ``repr()`` of the dict, any exception carrying it, any structlog ``**kwargs``
    spread and any debugger frame go through ``SecretStr.__repr__``.
    """
    resolved = EnvCredentialResolver().resolve("env:OKX_ACCT_A")

    assert all(isinstance(value, SecretStr) for value in resolved.values())
    rendered = repr(resolved)
    for value in seeded_env.values():
        assert value not in rendered


def test_error_messages_never_contain_a_credential_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolution failure names the reference and variable NAMES, never values."""
    monkeypatch.setenv("OKX_ACCT_A_API_KEY", "seeded-key-8f21")

    with pytest.raises(CredentialResolutionError) as excinfo:
        EnvCredentialResolver().resolve("env:OKX_ACCT_NOPE")

    assert "seeded-key-8f21" not in str(excinfo.value)
    assert "seeded-key-8f21" not in repr(excinfo.value)


# --------------------------------------------------------------------------- #
# The round-trip the whole scheme exists for (audit correction #3)
# --------------------------------------------------------------------------- #
def test_resolved_mapping_constructs_okx_settings_without_transformation(
    seeded_env: dict[str, str],
) -> None:
    """The resolver's output feeds ``OkxSettings(**resolved)`` directly.

    The scheme is worthless if its output cannot construct the venue's credential
    model. ``OkxSettings`` binds each field via ``validation_alias`` (``OKX_API_KEY``
    ...), so this round-trip only works because the model opts into
    ``populate_by_name`` — asserted here rather than assumed.
    """
    from itrader.config.okx_settings import OkxSettings

    resolved = EnvCredentialResolver().resolve("env:OKX_ACCT_A")
    settings = OkxSettings(**resolved)  # type: ignore[arg-type]

    assert settings.api_key.get_secret_value() == seeded_env["OKX_ACCT_A_API_KEY"]
    assert settings.api_secret.get_secret_value() == seeded_env["OKX_ACCT_A_API_SECRET"]
    assert (
        settings.api_passphrase.get_secret_value()
        == seeded_env["OKX_ACCT_A_API_PASSPHRASE"]
    )
