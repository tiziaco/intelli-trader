---
phase: quick-260703-bza
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/config/okx_settings.py
  - itrader/connectors/base.py
  - itrader/connectors/okx.py
  - itrader/price_handler/providers/okx_provider.py
  - tests/unit/config/test_okx_settings.py
  - tests/unit/connectors/test_okx_connector.py
  - tests/unit/connectors/test_okx_data_provider.py
autonomous: true
requirements: [OKX-REGION]

must_haves:
  truths:
    - "OKX_REGION=global derives REST host www.okx.com; OKX_REGION=eea derives eea.okx.com"
    - "WS host is derived from (region, sandbox): (global,demo)->wspap.okx.com, (global,prod)->ws.okx.com, (eea,demo)->wseeapap.okx.com, (eea,prod)->wseea.okx.com"
    - "Both WS consumers (ccxt client + native candle socket) build wss://{ws_hostname}:8443/ws/v5[/business] off the single derived ws_hostname"
    - "An invalid OKX_REGION fails loud with a pydantic ValidationError"
    - "The removed OKX_HOSTNAME/hostname field no longer exists on OkxSettings"
  artifacts:
    - path: "itrader/config/okx_settings.py"
      provides: "region field + rest_hostname/ws_hostname derived properties; hostname field removed"
      contains: "def ws_hostname"
    - path: "itrader/connectors/okx.py"
      provides: "OkxConnector.ws_hostname property; client.urls[api][ws] set from ws_hostname"
      contains: "ws_hostname"
    - path: "itrader/price_handler/providers/okx_provider.py"
      provides: "native candle host reads connector.ws_hostname"
      contains: "self._connector.ws_hostname"
    - path: "itrader/connectors/base.py"
      provides: "ws_hostname on the LiveConnector Protocol"
      contains: "def ws_hostname"
  key_links:
    - from: "itrader/connectors/okx.py::_build_client"
      to: "itrader/config/okx_settings.py::ws_hostname"
      via: "self._settings.ws_hostname interpolated into client.urls[api][ws]"
      pattern: "urls\\[.api.\\]\\[.ws.\\]"
    - from: "itrader/price_handler/providers/okx_provider.py::_connect_and_consume_candles"
      to: "OkxConnector.ws_hostname (LiveConnector.ws_hostname)"
      via: "host = self._connector.ws_hostname"
      pattern: "self\\._connector\\.ws_hostname"
---

<objective>
Replace the single `OKX_HOSTNAME`/`hostname` field on `OkxSettings` with an `OKX_REGION`
knob (`global` | `eea`) that derives BOTH the REST host and the WebSocket host, so the two
WS consumers (the ccxt.pro client and the native business-candle socket) build their URL
off one authoritative `ws_hostname` instead of a hardcoded `sandbox` ternary that only knew
the global entity.

Purpose: an EEA-issued key returns 50119 on the global host (and vice versa), and the demo
WS host differs per entity (`wspap` vs `wseeapap`). A single region knob fixes the misroute
class the old `sandbox`-only ternary could not express.

Output: `region` config + `rest_hostname`/`ws_hostname` derived properties; connector wires
both hosts into ccxt; provider reads `ws_hostname`; `LiveConnector` Protocol gains
`ws_hostname`; tests cover all four (region, sandbox) combos.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

<host_tables>
VERIFIED (no research — do not re-derive):

REST hostname by region:
  global -> www.okx.com
  eea    -> eea.okx.com

WS hostname by (region, sandbox):  (sandbox=True == demo, sandbox=False == prod)
  (global, demo) -> wspap.okx.com
  (global, prod) -> ws.okx.com
  (eea,    demo) -> wseeapap.okx.com
  (eea,    prod) -> wseea.okx.com

WS URL both consumers build:
  ccxt client:      wss://{ws_hostname}:8443/ws/v5
  native candle:    wss://{ws_hostname}:8443/ws/v5/business
</host_tables>

<indentation>
- itrader/config/okx_settings.py -> 4 SPACES
- itrader/connectors/base.py -> 4 SPACES
- itrader/connectors/okx.py -> TABS
- itrader/price_handler/providers/okx_provider.py -> 4 SPACES
Match each file exactly; do NOT normalize.
</indentation>

<interfaces>
From itrader/config/okx_settings.py (current — the `hostname` field at the bottom is REPLACED):
```python
class OkxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    api_key: SecretStr = Field(validation_alias="OKX_API_KEY")
    api_secret: SecretStr = Field(validation_alias="OKX_API_SECRET")
    api_passphrase: SecretStr = Field(validation_alias="OKX_API_PASSPHRASE")
    sandbox: bool = Field(default=True, validation_alias="OKX_SANDBOX")
    hostname: str = Field(default="www.okx.com", validation_alias="OKX_HOSTNAME")  # REMOVE
```

From itrader/connectors/okx.py::_build_client (current — uses "hostname"):
```python
self._client = ccxtpro.okx({ ..., "hostname": self._settings.hostname, "enableRateLimit": True })
if self._sandbox:
    self._client.set_sandbox_mode(True)
await self._client.load_markets()
```
OkxConnector exposes `sandbox` property (~L91). `self._settings` is the OkxSettings instance.

From itrader/connectors/base.py::LiveConnector (Protocol, 4 spaces, @runtime_checkable):
  members: call, spawn, client (property), sandbox (property), connect, disconnect.

From itrader/price_handler/providers/okx_provider.py::_connect_and_consume_candles (~L247):
```python
host = "wspap.okx.com" if self._connector.sandbox else "ws.okx.com"
url = f"wss://{host}:8443/ws/v5/business"
```
`self._connector` is typed `LiveConnector`; okx_provider IS mypy-strict (NOT in the
pyproject mypy override list).
</interfaces>

<test_patterns>
tests/unit/config/test_okx_settings.py: `okx_env` fixture sets the OKX_API_* triple and
clears OKX_SANDBOX; construct `OkxSettings()`; assert `.sandbox`; `pytest.raises(ValidationError)`.

tests/unit/connectors/test_okx_connector.py: `_settings(monkeypatch, sandbox=...)` sets env
+ builds OkxSettings; `_real_offline_okx` builds a REAL ccxt.pro.okx offline (load_markets
mocked); connect() under `patch(_PATCH_TARGET, _real_offline_okx)`; assert on
`str(client.urls["api"])`. `_settings` does NOT set OKX_REGION today — add a `region` kwarg.

tests/unit/connectors/test_okx_data_provider.py: `_StubConnector(sandbox, client=None)` at
L40; existing routing tests (L186-208) assert `recorder["url"] == "wss://{host}:8443/ws/v5/business"`
driven off `sandbox`. `_drive_stream` records the ws_connect URL.
</test_patterns>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Replace hostname with region + derived hosts on OkxSettings</name>
  <files>itrader/config/okx_settings.py, tests/unit/config/test_okx_settings.py</files>
  <behavior>
    - region defaults to "global"; OKX_REGION=eea overrides it
    - OKX_REGION=global -> rest_hostname == "www.okx.com"; =eea -> "eea.okx.com"
    - ws_hostname per (region, sandbox): (global,True)->wspap.okx.com, (global,False)->ws.okx.com, (eea,True)->wseeapap.okx.com, (eea,False)->wseea.okx.com
    - OKX_REGION=apac (or any non-{global,eea}) raises pydantic ValidationError
    - OkxSettings no longer has a `hostname` attribute
  </behavior>
  <action>
    In itrader/config/okx_settings.py (4 SPACES): REMOVE the `hostname` field (the
    OKX_HOSTNAME line added in 3790990f) and its comment. ADD a `region` field typed
    `Literal["global", "eea"]` with `Field(default="global", validation_alias="OKX_REGION")`
    — the Literal makes an invalid region fail loud with pydantic ValidationError (no manual
    validator needed; do NOT silently coerce). Keep `sandbox`.

    Add two read-only derived properties (regular `@property`, not pydantic fields, so they
    are not env-sourced): `rest_hostname` returns "www.okx.com" for global and "eea.okx.com"
    for eea; `ws_hostname` returns the (region, self.sandbox) mapping from <host_tables>. Use
    small module-level dict literals keyed by region (REST) and by (region, sandbox) (WS) for
    the lookup, mirroring the file's existing style. Update the module/field docstrings to
    describe region-derives-both-hosts, dropping the old single-hostname wording. NEVER touch
    .env.

    In tests/unit/config/test_okx_settings.py: the `okx_env` fixture already clears
    OKX_SANDBOX — also `monkeypatch.delenv("OKX_REGION", raising=False)` in it so a real env
    OKX_REGION can't leak in. Add tests: region defaults to global; all 4 (region, sandbox)
    combos yield the correct rest_hostname AND ws_hostname (parametrize or 4 asserts, set
    OKX_REGION + OKX_SANDBOX via monkeypatch); an invalid OKX_REGION="apac" raises
    ValidationError; `not hasattr(OkxSettings(), "hostname")`. There are no existing tests
    referencing `hostname` to remove (grep-confirmed).
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/config/test_okx_settings.py -q</automated>
  </verify>
  <done>All (region, sandbox) combos resolve to the VERIFIED hosts; invalid region raises ValidationError; `hostname` attr gone; config tests green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire ws_hostname through connector + LiveConnector Protocol</name>
  <files>itrader/connectors/base.py, itrader/connectors/okx.py, tests/unit/connectors/test_okx_connector.py</files>
  <behavior>
    - _build_client passes "hostname": self._settings.rest_hostname to ccxtpro.okx(...)
    - After the `if self._sandbox: set_sandbox_mode(True)` block, client.urls["api"]["ws"] == f"wss://{settings.ws_hostname}:8443/ws/v5" UNCONDITIONALLY
    - region=eea + sandbox=True -> client.urls["api"]["ws"] host == wseeapap.okx.com
    - region=global + sandbox=True -> host == wspap.okx.com
    - OkxConnector.ws_hostname == self._settings.ws_hostname
    - LiveConnector Protocol declares ws_hostname (mypy-strict clean)
  </behavior>
  <action>
    In itrader/connectors/base.py (4 SPACES): add a `ws_hostname` read-only `@property`
    returning `str` to the `LiveConnector` Protocol (method body `...`, docstring: the demo/live
    WS host the native data socket keys its URL off, derived from region+sandbox). Place it
    near the `sandbox` property; keep the module's existing docstring/comment style.

    In itrader/connectors/okx.py (TABS): in `_build_client`, change the ccxt config
    `"hostname": self._settings.hostname` to `"hostname": self._settings.rest_hostname` and
    update the inline comment (region-derived REST host). AFTER the existing
    `if self._sandbox: self._client.set_sandbox_mode(True)` block and BEFORE `load_markets()`,
    unconditionally set `self._client.urls["api"]["ws"] = f"wss://{self._settings.ws_hostname}:8443/ws/v5"`
    with a comment noting this overrides ccxt's own demo swap so the region-specific WS host
    (wspap/ws/wseeapap/wseea) is authoritative. Add a public `ws_hostname` `@property` on
    OkxConnector returning `self._settings.ws_hostname` (near the `sandbox` property). Keep the
    `sandbox` property. Update the class/module docstring sandbox note if it still claims the
    ccxt wspap swap is the sole WS routing — the region override now supersedes it.

    In tests/unit/connectors/test_okx_connector.py: add a `region` kwarg to `_settings(...)`
    (`monkeypatch.setenv("OKX_REGION", region)`, default "global"). Add tests asserting
    `connector.client.urls["api"]["ws"] == "wss://{ws_hostname}:8443/ws/v5"` after connect()
    for (region="eea", sandbox=True) -> wseeapap.okx.com and (region="global", sandbox=True)
    -> wspap.okx.com, using the `_real_offline_okx` pattern under `patch(_PATCH_TARGET, ...)`,
    and `connector.ws_hostname` exposed. Every test disconnects in a `finally` (Pitfall 4 —
    no ResourceWarning). Do NOT weaken the existing sandbox-routing assertions.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/connectors/test_okx_connector.py -q</automated>
  </verify>
  <done>ccxt client.urls["api"]["ws"] is the region-derived WS URL for both asserted combos; connector.ws_hostname exposed; Protocol declares ws_hostname; connector tests green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Provider reads connector.ws_hostname + gate sweep</name>
  <files>itrader/price_handler/providers/okx_provider.py, tests/unit/connectors/test_okx_data_provider.py</files>
  <behavior>
    - _connect_and_consume_candles builds host = self._connector.ws_hostname (no sandbox ternary)
    - native URL == f"wss://{connector.ws_hostname}:8443/ws/v5/business"
    - _StubConnector exposes ws_hostname; URL follows it (eea demo -> wseeapap; global demo -> wspap)
  </behavior>
  <action>
    In itrader/price_handler/providers/okx_provider.py (4 SPACES): at ~L247 replace
    `host = "wspap.okx.com" if self._connector.sandbox else "ws.okx.com"` with
    `host = self._connector.ws_hostname`. Update the nearby docstring/comment (currently "host
    is driven off the injected connector's `sandbox` bool") to say the host is the connector's
    region+sandbox-derived `ws_hostname`. The `url = f"wss://{host}:8443/ws/v5/business"` line
    is unchanged. mypy-strict must stay clean (ws_hostname now on the LiveConnector Protocol
    from Task 2).

    In tests/unit/connectors/test_okx_data_provider.py: give `_StubConnector.__init__` a
    `ws_hostname` param. To keep the existing two sandbox-routing tests (L186-208) passing,
    default `ws_hostname` derived from `sandbox` ("wspap.okx.com" if sandbox else
    "ws.okx.com") so those tests still assert wspap/ws.okx.com. Add a `ws_hostname` attribute
    on the stub. Add a new test: `_StubConnector(sandbox=True, ws_hostname="wseeapap.okx.com")`
    -> `_drive_stream` records `recorder["url"] == "wss://wseeapap.okx.com:8443/ws/v5/business"`,
    proving the native host follows connector.ws_hostname (name it e.g.
    `test_native_host_follows_connector_ws_hostname` so it matches `-k "region or ws_host"`).

    Do NOT run the whole test_okx_data_provider.py file (a pre-existing async test HANGS —
    unrelated, do NOT fix). Verify with the targeted `-k` gate only. Note the hang in SUMMARY.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k "sandbox or ws_host or region or backfill" -q</automated>
  </verify>
  <done>Provider native socket host == connector.ws_hostname; _StubConnector carries ws_hostname; targeted `-k` selection green (full file NOT run).</done>
</task>

</tasks>

<verification>
Final gate sweep (run these exact commands, NOT `make test`):

1. mypy clean on the changed source files (+ Protocol):
   `poetry run mypy itrader/config/okx_settings.py itrader/connectors/base.py itrader/connectors/okx.py itrader/price_handler/providers/okx_provider.py`
2. Inertness gate unaffected:
   `poetry run pytest tests/integration/test_okx_inertness.py -q`
3. New/updated unit tests:
   `poetry run pytest tests/unit/config/test_okx_settings.py tests/unit/connectors/test_okx_connector.py -q`
   `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k "sandbox or ws_host or region or backfill" -q`

Do NOT run the full test_okx_data_provider.py file (pre-existing async hang, unrelated).
</verification>

<success_criteria>
- `OkxSettings.region` (Literal global|eea, alias OKX_REGION, default global) replaces `hostname`; `rest_hostname`/`ws_hostname` derived properties return the VERIFIED hosts for all 4 (region, sandbox) combos; invalid region raises ValidationError.
- `OkxConnector._build_client` passes `rest_hostname` to ccxt and unconditionally sets `client.urls["api"]["ws"] = wss://{ws_hostname}:8443/ws/v5`; `OkxConnector.ws_hostname` exposed.
- `LiveConnector` Protocol declares `ws_hostname`.
- `OkxDataProvider` native candle host reads `connector.ws_hostname`.
- mypy clean on the 4 source files; inertness green; targeted unit tests green.
- Only the 4 source files + 3 test files are staged (NOT Makefile, NOT scripts/diagnose_okx_creds.py, NOT .env).
</success_criteria>

<commit_scope>
When committing (only if the user asks / execute-plan commits), stage by EXPLICIT path:
`itrader/config/okx_settings.py itrader/connectors/base.py itrader/connectors/okx.py itrader/price_handler/providers/okx_provider.py tests/unit/config/test_okx_settings.py tests/unit/connectors/test_okx_connector.py tests/unit/connectors/test_okx_data_provider.py`
Do NOT `git add -A`. Pre-existing unrelated changes (Makefile, scripts/diagnose_okx_creds.py) must stay unstaged.
</commit_scope>

<output>
Create `.planning/quick/260703-bza-add-okx-region-config-deriving-rest-ws-h/260703-bza-SUMMARY.md` when done.
Note in SUMMARY: the pre-existing async-stream hang in test_okx_data_provider.py (not fixed, out of scope).
</output>
