"""Application settings via pydantic-settings (M2-06 / D-02).

A minimal ``Settings(BaseSettings)`` layer for NON-DB process env only. Backtest-relevant
fields carry safe defaults (``timezone``/``log_level``/``environment``/``disable_logs``) so the
backtest path never needs an environment or a ``.env`` file.

The DB connection no longer lives here (260629-l0q — supersedes 260629-jh2). It is owned wholly
by the unified ``SqlSettings`` (``itrader/config/sql.py``, ``env_prefix="ITRADER_DATABASE_"``),
which carries the connection params, the conditional Postgres validation, and the engine-URL
builder. ``Settings`` therefore no longer carries any required secret — that is intentional: the
DB fail-loud moved to ``SqlSettings``' driver-conditional Postgres validator.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings read from ``ITRADER_*`` environment variables (non-DB)."""

    model_config = SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")

    # Backtest path reads these — safe, documented defaults.
    timezone: str = "Europe/Paris"
    log_level: str = "INFO"
    environment: str = "backtest"

    # ITRADER_DISABLE_LOGS — D-08 full-off kill-switch (Phase 4, PERF-03). Default
    # False keeps the backtest path env-free; pydantic-settings coerces
    # "true"/"1"/"yes" natively. The logger reads the same env var cache-once via
    # os.environ (Pitfall 8 — it must NOT instantiate Settings() at import).
    disable_logs: bool = False
