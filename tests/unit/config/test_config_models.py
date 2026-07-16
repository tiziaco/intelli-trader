"""M2-06 config-model tests (Pydantic v2 collapse, landed by 03-05).

Pins the M2-06 behaviors the config collapse delivers:

  1. ``PortfolioConfig.model_validate(d).model_dump(mode="json")`` round-trips a config
     dict with JSON-safe coercion (Decimal -> str) — the single model that serves BOTH
     the backtest-dict and the live-JSONB path.
  2. ``PortfolioConfig.default()`` returns the conservative-preset-equivalent model.

NOTE (260629-l0q): the former env-layer secret tests (fail-loud + masking) were RELOCATED
to ``tests/unit/storage/test_sql_settings.py`` — the DB connection (and its required-secret
fail-loud) now lives wholly on the unified ``SqlSettings``; the runtime env layer no longer
carries any DB field or secret.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_config/``
during the 03-08 type-split — 03-08 must reconcile it there without duplicating it here.
"""

from decimal import Decimal

from itrader.config.models import PortfolioConfig


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
