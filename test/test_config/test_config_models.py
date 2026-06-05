"""Wave-0 characterization stub for M2-06 (config → Pydantic models).

This stub is written at Wave 0 of Phase 3 (M2b) under the CURRENT ``test/`` tree
(``testpaths=["test"]``) so ``make test`` collects it immediately. It pins the two
M2-06 behaviors the config-collapse wave (03-05) must deliver:

  1. ``PortfolioConfig.model_validate(d).model_dump(mode="json")`` round-trips a config
     dict with JSON-safe coercion (Decimal → str, UUID → str) — the single model that
     serves BOTH the backtest-dict and the live-JSONB path.
  2. ``Settings()`` raises ``pydantic.ValidationError`` (fail-loud) when a required-no-default
     secret (``database_url``) is absent from the environment — secrets never silently
     default.

Until 03-05 lands the Pydantic ``PortfolioConfig`` / ``Settings`` models, the concrete
assertions are gated behind ``pytest.importorskip`` so the suite stays GREEN (no red
collection error). When the code arrives, the importorskip resolves and the assertions
turn live; the skip is removed.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_config/`` during
the 03-08 type-split — 03-08 must reconcile it there without duplicating it here.
"""

import pytest


def test_portfolio_config_model_dump_json_round_trips():
    """M2-06: PortfolioConfig.model_dump(mode="json") round-trips with JSON-safe coercion.

    Pending 03-05 (config → Pydantic). The model does not exist yet, so import-skip keeps
    this green at Wave 0; the body becomes a live assertion when 03-05 lands the model.
    """
    pydantic = pytest.importorskip("pydantic", reason="pending 03-05: config → Pydantic models")
    config_models = pytest.importorskip(
        "itrader.config.models",
        reason="pending 03-05: PortfolioConfig Pydantic model not built yet",
    )

    from decimal import Decimal

    PortfolioConfig = config_models.PortfolioConfig
    source = {"name": "oracle_pf", "cash": Decimal("10000.00")}
    dumped = PortfolioConfig.model_validate(source).model_dump(mode="json")

    # JSON mode coerces Decimal → str (no float round-trip); the round-trip re-validates.
    assert isinstance(dumped["cash"], str)
    assert PortfolioConfig.model_validate(dumped).cash == Decimal("10000.00")


def test_settings_missing_required_secret_raises_validation_error():
    """M2-06: Settings() fails loud (ValidationError) when a required secret is absent.

    Pending 03-05 (pydantic-settings). Import-skip keeps this green at Wave 0; becomes a
    live assertion when 03-05 lands the Settings model with a required-no-default
    ``database_url`` secret.
    """
    pydantic = pytest.importorskip("pydantic", reason="pending 03-05: config → Pydantic models")
    settings_module = pytest.importorskip(
        "itrader.config.settings",
        reason="pending 03-05: pydantic-settings Settings model not built yet",
    )

    Settings = settings_module.Settings
    with pytest.raises(pydantic.ValidationError):
        # database_url is required-no-default; absent from env → fail loud, never silent-default.
        Settings(_env_file=None)
