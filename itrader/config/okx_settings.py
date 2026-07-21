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

- **Region derives BOTH hosts (OKX-REGION):** a single ``OKX_REGION`` knob
  (``global`` | ``eea``) derives the REST host AND the WebSocket host. An EEA-issued
  key returns 50119 "API key doesn't exist" on the global host (and vice versa), and the
  demo WS host differs per entity (``wspap`` vs ``wseeapap``). The region knob fixes the
  misroute class the old ``sandbox``-only WS ternary could not express. ``rest_hostname``
  and ``ws_hostname`` are derived read-only properties (NOT env-sourced fields):
  ``rest_hostname`` keys off region alone; ``ws_hostname`` keys off ``(region, sandbox)``.

This is env-only — there is deliberately NO YAML layer (unlike the domain configs).
Only the connector reads it, so it stays import-by-path (no ``config`` barrel export).
Construction is where the env-source pipeline runs; importing this module is inert.
"""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# REST host by region (the ccxt okx ``https://{hostname}`` template substitutes this).
_REST_HOSTNAME_BY_REGION: dict[str, str] = {
    "global": "www.okx.com",
    "eea": "eea.okx.com",
}

# WS host by (region, sandbox). sandbox=True == demo, sandbox=False == prod. Both WS
# consumers (ccxt.pro client + native business-candle socket) build their URL off this.
_WS_HOSTNAME_BY_REGION_SANDBOX: dict[tuple[str, bool], str] = {
    ("global", True): "wspap.okx.com",
    ("global", False): "ws.okx.com",
    ("eea", True): "wseeapap.okx.com",
    ("eea", False): "wseea.okx.com",
}


class OkxSettings(BaseSettings):
    """OKX demo/live credentials read from the plain ``OKX_API_*`` environment (D-10).

    The passphrase is required — OKX authentication is a triple, not a pair, so a
    missing ``OKX_API_PASSPHRASE`` fails loud with a ``pydantic.ValidationError``
    rather than silently shipping a half-authenticated client.
    """

    # ``populate_by_name`` (11-04 / D-02): WITHOUT it this model is constructible ONLY
    # from the ambient ``OKX_API_*`` environment. Each field binds a ``validation_alias``,
    # and ``extra="ignore"`` silently DROPS a field-named kwarg — so
    # ``OkxSettings(api_key=...)`` drops the kwarg and then fails "OKX_API_KEY Field
    # required". That is fine while ONE global credential set exists, but per-account
    # credentials (MPORT-06) must construct this model from a resolved mapping instead of
    # the process environment, or two ``account_id``s connect with IDENTICAL keys (the
    # D-12 caveat). ``populate_by_name`` only ADDS the field-name input form; the
    # ``OKX_API_*`` alias path is untouched.
    model_config = SettingsConfigDict(
        env_prefix="", extra="ignore", populate_by_name=True)  # NO prefix (D-10)

    api_key: SecretStr = Field(validation_alias="OKX_API_KEY")
    api_secret: SecretStr = Field(validation_alias="OKX_API_SECRET")
    api_passphrase: SecretStr = Field(validation_alias="OKX_API_PASSPHRASE")
    sandbox: bool = Field(default=True, validation_alias="OKX_SANDBOX")
    # Regional entity (OKX-REGION). ``global`` (default) is reached via www.okx.com;
    # ``eea`` via eea.okx.com. A key issued on one entity returns 50119 "API key doesn't
    # exist" on the other, and the demo WS host differs per entity, so region — not a bare
    # sandbox ternary — derives BOTH hosts. The ``Literal`` makes an invalid OKX_REGION
    # fail loud with a pydantic ValidationError (no silent coercion).
    region: Literal["global", "eea"] = Field(
        default="global", validation_alias="OKX_REGION")

    @property
    def rest_hostname(self) -> str:
        """Region-derived REST host (ccxt ``https://{hostname}`` template)."""
        return _REST_HOSTNAME_BY_REGION[self.region]

    @property
    def ws_hostname(self) -> str:
        """(region, sandbox)-derived WS host both WS consumers key their URL off."""
        return _WS_HOSTNAME_BY_REGION_SANDBOX[(self.region, self.sandbox)]
