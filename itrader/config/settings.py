"""Application settings via pydantic-settings (M2-06 / D-02).

A minimal ``Settings(BaseSettings)`` layer. Backtest-relevant fields carry safe
defaults (``timezone``/``log_level``/``environment``) so the backtest path never needs
an environment or a ``.env`` file. Secrets (the DB URL, future API keys) are declared
as required-no-default ``SecretStr`` so a *live* instantiation that omits them fails
loud with a ``pydantic.ValidationError`` rather than silently shipping a working default
(the explicit M2-06 "no working secret defaults" criterion).

``SecretStr`` additionally masks ``repr``/``str``/``model_dump`` so the secret never
appears in logs or serialised output — its value is reachable only via
``.get_secret_value()``. DB / exchange auth are NOT wired here (D-live deferred); this
is a declaration-only fail-loud stub.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings read from ``ITRADER_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")

    # Backtest path reads these — safe, documented defaults.
    timezone: str = "Europe/Paris"
    log_level: str = "INFO"
    environment: str = "backtest"

    # Secrets: NO default -> ValidationError if a live path ever instantiates Settings
    # without ITRADER_DATABASE_URL set. Access only via database_url.get_secret_value().
    database_url: SecretStr
