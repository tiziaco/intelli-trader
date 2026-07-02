"""OKX credential layer — ``OkxSettings(BaseSettings)`` (CONN-06 / D-10).

The OKX auth triple (API key + secret + passphrase) crosses from the process
environment into the connector here, and NOWHERE else. Two disciplines are load-bearing:

- **SecretStr end-to-end (CONN-06 / T-02-01-CRED):** every credential is a
  ``SecretStr`` — masked in ``repr``/``str``/logs as ``**********`` — surfaced only
  via ``.get_secret_value()`` at the ccxt/native client edge. Mirrors the
  ``SqlSettings`` discipline (``config/sql.py``). The backtest path never imports this
  module, so the credential surface stays off the hot path entirely.

- **Plain ``OKX_API_*`` names, NO ``ITRADER_`` prefix (D-10 revises CONN-06):**
  ``env_prefix=""`` so no prefix is prepended, and each field binds to its plain env
  name via ``validation_alias`` (``OKX_API_KEY`` / ``OKX_API_SECRET`` /
  ``OKX_API_PASSPHRASE`` — already present in ``.env.example``). An explicit alias is
  required because, under ``env_prefix=""``, a bare field named ``api_key`` would read
  ``API_KEY`` rather than ``OKX_API_KEY``. ``extra="ignore"`` drops unrelated env vars
  (``ITRADER_*`` / ``DATABASE_*``) instead of erroring.

This is env-only — there is deliberately NO YAML layer (unlike the domain configs).
Only the connector reads it, so it stays import-by-path (no ``config`` barrel export).
Construction is where the env-source pipeline runs; importing this module is inert.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OkxSettings(BaseSettings):
    """OKX demo/live credentials read from the plain ``OKX_API_*`` environment (D-10).

    The passphrase is required — OKX authentication is a triple, not a pair, so a
    missing ``OKX_API_PASSPHRASE`` fails loud with a ``pydantic.ValidationError``
    rather than silently shipping a half-authenticated client.
    """

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")  # NO prefix (D-10)

    api_key: SecretStr = Field(validation_alias="OKX_API_KEY")
    api_secret: SecretStr = Field(validation_alias="OKX_API_SECRET")
    api_passphrase: SecretStr = Field(validation_alias="OKX_API_PASSPHRASE")
    sandbox: bool = Field(default=True, validation_alias="OKX_SANDBOX")
    # Regional-entity host (ccxt okx uses the ``https://{hostname}`` template). Default
    # ``www.okx.com`` is the global entity; the EEA entity (and its demo environment) is
    # reached via ``eea.okx.com`` — a key issued on one entity returns 50119 "API key
    # doesn't exist" on another, so the host must match where the key was created.
    hostname: str = Field(default="www.okx.com", validation_alias="OKX_HOSTNAME")
