"""Application settings via pydantic-settings (M2-06 / D-02).

A minimal ``Settings(BaseSettings)`` layer. Backtest-relevant fields carry safe
defaults (``timezone``/``log_level``/``environment``) so the backtest path never needs
an environment or a ``.env`` file.

Postgres connection (260629-jh2 — supersedes IN-02): the operational store is
parametrized via component-level ``ITRADER_DATABASE_*`` fields (host/port/user/name/
password). ``database_password`` is the required-no-default ``SecretStr`` so a *live*
Postgres instantiation that omits it fails loud with a ``pydantic.ValidationError``
rather than silently shipping a working default (the explicit M2-06 "no working secret
defaults" criterion). The default port is ``5544`` (NOT the conventional 5432, which is
taken by another DB on the target machine). ``database_url`` is now an OPTIONAL verbatim
escape hatch — when set it wins over the assembled component URL.

``SecretStr`` masks ``repr``/``str``/``model_dump`` so the secret never appears in logs
or serialised output — its value is reachable only via ``.get_secret_value()``. Exchange
auth is NOT wired here (D-live deferred).
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

    # ITRADER_DISABLE_LOGS — D-08 full-off kill-switch (Phase 4, PERF-03). Default
    # False keeps the backtest path env-free; pydantic-settings coerces
    # "true"/"1"/"yes" natively. This is the documented knob surface; the logger
    # reads the same env var cache-once via os.environ (Pitfall 8 — it must NOT
    # instantiate Settings() at import, database_url is required-no-default).
    disable_logs: bool = False

    # Postgres connection components (260629-jh2 — supersedes IN-02). The operational
    # store URL is assembled from these in sql.py::engine_url() via sqlalchemy.URL.create
    # (which URL-escapes special chars in the password). Non-secret components carry safe
    # defaults; only the password is a required-no-default secret.
    database_host: str = "localhost"   # ITRADER_DATABASE_HOST
    database_port: int = 5544          # ITRADER_DATABASE_PORT — NOT 5432 (5432 is taken)
    database_user: str = "postgres"    # ITRADER_DATABASE_USER
    database_name: str = "itrader"     # ITRADER_DATABASE_NAME

    # Secret: NO default -> ValidationError if a live Postgres path instantiates Settings
    # without ITRADER_DATABASE_PASSWORD set (fail-loud, M2-06 "no working secret defaults").
    # Access only via database_password.get_secret_value().
    database_password: SecretStr       # ITRADER_DATABASE_PASSWORD

    # Optional verbatim escape hatch: when ITRADER_DATABASE_URL is set, engine_url() returns
    # it as-is (scheme/driver authoritative) instead of assembling from the components above.
    database_url: SecretStr | None = None
