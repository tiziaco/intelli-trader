"""Slim runtime logging-knob env layer (successor to the removed legacy env layer).

Purpose-built replacement for the deleted ``config/settings.py`` env layer. It carries
ONLY the two documented ``ITRADER_*`` logging knobs — ``log_level`` and
``disable_logs`` — so their environment-variable parsing (via ``BaseSettings``) is
preserved after the legacy layer was retired (user decision 4). ``environment`` and
``timezone`` are NOT re-homed here: ``timezone`` moved to the frozen ``ITraderConfig``
base and ``environment`` is already an ``Environment`` enum base field on the root.

Inertness (GATE-01): this module imports ONLY from ``pydantic_settings`` (pydantic +
stdlib), carrying no DB/secret/venue fields, so mounting it on ``ITraderConfig`` keeps
``import itrader`` free of sqlalchemy/ccxt/async. The DB surface stays behind the lazy
``sql`` cached_property on the root.

Pitfall 8: the logger reads ``ITRADER_LOG_LEVEL``/``ITRADER_DISABLE_LOGS`` straight from
``os.environ`` at import — this model is a documented-knob surface, NEVER constructed
inside ``logger.py``.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class LogConfig(BaseSettings):
    """Runtime logging knobs read from ``ITRADER_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")

    log_level: str = "INFO"

    # ITRADER_DISABLE_LOGS — D-08 full-off kill-switch (Phase 4, PERF-03). Default
    # False keeps the backtest path env-free; pydantic-settings coerces
    # "true"/"1"/"yes" natively. The logger reads the same env var cache-once via
    # os.environ (Pitfall 8 — it must NOT instantiate LogConfig() at import).
    disable_logs: bool = False
