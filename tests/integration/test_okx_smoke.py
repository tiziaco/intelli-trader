"""Opt-in live OKX smoke scaffold (Phase 2 / 02-01, D-09).

This test is a SCAFFOLD: it exercises a real OKX demo connection only when demo
credentials are present in the environment (``OKX_API_KEY`` / ``OKX_API_SECRET`` /
``OKX_API_PASSPHRASE``). In CI and credential-free checkouts it AUTO-SKIPS — no import
errors, no network, no session left open. The gating offline suite runs credential-free;
this file never gates it.

The body is intentionally minimal for Wave 0: it loads ``OkxSettings`` and asserts the
credential layer round-trips, with NO network call. Later waves (Plans 02-02..02-05)
grow it into a real connect -> subscribe -> teardown against the live ``OkxConnector``.
All imports of connector code are LAZY (inside the test), so collection never depends on
code that lands in later plans.
"""

import os

import pytest

_OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
_HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)

pytestmark = pytest.mark.skipif(
    not _HAS_OKX_CREDS,
    reason=(
        "OKX demo credentials absent — opt-in live smoke test skipped (D-09). "
        "Set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (demo env) to enable."
    ),
)


def test_okx_credential_layer_loads() -> None:
    """Wave-0 smoke: OkxSettings reads the demo auth triple (no network).

    Lazy import so a credential-free collection never touches connector code. Later
    waves replace this body with a real connect/subscribe/teardown against OkxConnector.
    """
    from itrader.config.okx_settings import OkxSettings

    settings = OkxSettings()  # type: ignore[call-arg]

    assert settings.api_key.get_secret_value()
    assert settings.api_secret.get_secret_value()
    assert settings.api_passphrase.get_secret_value()
