"""M2-06 config-model tests (Pydantic v2 collapse, landed by 03-05).

Pins the three M2-06 behaviors the config collapse delivers:

  1. ``PortfolioConfig.model_validate(d).model_dump(mode="json")`` round-trips a config
     dict with JSON-safe coercion (Decimal -> str) — the single model that serves BOTH
     the backtest-dict and the live-JSONB path.
  2. ``PortfolioConfig.default()`` returns the conservative-preset-equivalent model.
  3. ``Settings()`` raises ``pydantic.ValidationError`` (fail-loud) when the
     required-no-default secret (``database_url``) is absent from the environment —
     secrets never silently default.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_config/``
during the 03-08 type-split — 03-08 must reconcile it there without duplicating it here.
"""

from decimal import Decimal

import pytest

import pydantic
from itrader.config.models import PortfolioConfig
from itrader.config.settings import Settings


def test_portfolio_config_model_dump_json_round_trips():
    """M2-06: PortfolioConfig round-trips via model_validate / model_dump(mode="json").

    JSON mode coerces Decimal -> str (no float round-trip); re-validating the dumped
    dict reconstructs the model exactly.
    """
    source = {"name": "oracle_pf", "initial_capital": Decimal("10000.00")}
    model = PortfolioConfig.model_validate(source)
    dumped = model.model_dump(mode="json")

    # JSON mode: Decimal -> str.
    assert isinstance(dumped["initial_capital"], str)
    # Round-trips exactly (Decimal value preserved, model equality holds).
    revalidated = PortfolioConfig.model_validate(dumped)
    assert revalidated.initial_capital == Decimal("10000.00")
    assert revalidated == model


def test_portfolio_config_default_factory():
    """M2-06 (D-03): PortfolioConfig.default() replaces the 'default' preset function."""
    cfg = PortfolioConfig.default()
    assert isinstance(cfg, PortfolioConfig)
    # The 'default' preset historically returned an all-default PortfolioConfig.
    assert cfg == PortfolioConfig()
    assert cfg.initial_capital == Decimal("100000.0")


def test_settings_missing_required_secret_raises_validation_error():
    """M2-06 (D-02): Settings() fails loud when the required secret is absent.

    ``database_url`` is required-no-default; with no ITRADER_DATABASE_URL in the env and
    ``_env_file=None`` (ignore any local .env), instantiation must raise — never
    silently default to a working secret.
    """
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None)


def test_settings_secret_is_masked_when_provided():
    """M2-06 (D-02): a provided secret is a SecretStr — masked in repr, value via getter."""
    settings = Settings(_env_file=None, database_url="postgresql://u:p@host/db")
    # SecretStr masks repr/str so the secret never appears in logs/serialization.
    assert "p@host" not in repr(settings)
    assert settings.database_url.get_secret_value() == "postgresql://u:p@host/db"
