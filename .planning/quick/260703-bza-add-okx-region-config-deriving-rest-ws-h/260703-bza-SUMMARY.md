---
phase: quick-260703-bza
plan: 01
subsystem: connectors / config
tags: [okx, region, websocket, config, live-trading]
requires: [OkxSettings, LiveConnector, OkxConnector, OkxDataProvider]
provides:
  - "OkxSettings.region (Literal global|eea) + rest_hostname/ws_hostname derived properties"
  - "LiveConnector.ws_hostname Protocol member"
  - "OkxConnector.ws_hostname + region-authoritative client.urls[api][ws]"
  - "OkxDataProvider native candle host driven off connector.ws_hostname"
affects: [itrader/config/okx_settings.py, itrader/connectors/base.py, itrader/connectors/okx.py, itrader/price_handler/providers/okx_provider.py]
tech-stack:
  added: []
  patterns: [region-derives-both-hosts, single-authoritative-ws-host]
key-files:
  created: []
  modified:
    - itrader/config/okx_settings.py
    - itrader/connectors/base.py
    - itrader/connectors/okx.py
    - itrader/price_handler/providers/okx_provider.py
    - tests/unit/config/test_okx_settings.py
    - tests/unit/connectors/test_okx_connector.py
    - tests/unit/connectors/test_okx_data_provider.py
decisions:
  - "OKX_REGION is a Literal[global,eea] field — invalid region fails loud via pydantic ValidationError (no manual validator, no silent coercion)"
  - "WS host derived from (region, sandbox) via a module-level dict; the connector UNCONDITIONALLY overrides client.urls[api][ws] so the region-specific host supersedes ccxt's global-only demo swap"
metrics:
  duration: ~35min
  completed: 2026-07-03
---

# Quick Task 260703-bza: Add OKX region config deriving REST + WS hosts Summary

Replaced the single `OKX_HOSTNAME`/`hostname` field on `OkxSettings` with an `OKX_REGION`
(`global` | `eea`) knob that derives BOTH the REST host and the WebSocket host, so the two
WS consumers (the ccxt.pro client and the native business-candle socket) build their URL off
one authoritative `ws_hostname` instead of a hardcoded `sandbox`-only ternary that only knew
the global entity.

## What changed

**Task 1 — OkxSettings (`itrader/config/okx_settings.py`)**
- Removed the `hostname: str` / `OKX_HOSTNAME` field (added in 3790990f).
- Added `region: Literal["global", "eea"]` (alias `OKX_REGION`, default `global`). The
  `Literal` makes an invalid region fail loud with a pydantic `ValidationError`.
- Added two read-only `@property` derived hosts (NOT env-sourced fields): `rest_hostname`
  (region → www.okx.com / eea.okx.com) and `ws_hostname` ((region, sandbox) →
  wspap / ws / wseeapap / wseea) backed by module-level dict literals.

**Task 2 — connector + Protocol (`itrader/connectors/base.py`, `itrader/connectors/okx.py`)**
- `LiveConnector` Protocol gains a `ws_hostname` read-only property.
- `_build_client` now passes `settings.rest_hostname` as ccxt's `hostname` and, after the
  `set_sandbox_mode` block, UNCONDITIONALLY pins
  `client.urls["api"]["ws"] = f"wss://{settings.ws_hostname}:8443/ws/v5"` — overriding ccxt's
  own global-only demo swap so the region-specific WS host is authoritative.
- Added `OkxConnector.ws_hostname` property returning `self._settings.ws_hostname`.

**Task 3 — data provider (`itrader/price_handler/providers/okx_provider.py`)**
- `_connect_and_consume_candles` now builds `host = self._connector.ws_hostname` (removed the
  `"wspap.okx.com" if sandbox else "ws.okx.com"` ternary); the `wss://{host}:8443/ws/v5/business`
  URL now follows the region+sandbox-derived host.
- `_StubConnector` gained a `ws_hostname` param (sandbox-derived default preserves the legacy
  sandbox-routing tests); added `test_native_host_follows_connector_ws_hostname` (EEA demo →
  wseeapap).

## Verification

- `poetry run pytest tests/unit/config/test_okx_settings.py -q` → **14 passed** (region
  defaults, all 4 (region, sandbox) → rest+ws hosts, invalid region ValidationError, hostname
  attr gone).
- `poetry run pytest tests/unit/connectors/test_okx_connector.py -q` → **7 passed** (includes
  new region_ws_host global-demo→wspap and eea-demo→wseeapap asserts; existing sandbox
  routing assertions unweakened).
- `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k "backfill" -q` →
  **3 passed** (collection + Decimal-edge intact).
- `poetry run mypy itrader/config/okx_settings.py itrader/connectors/base.py itrader/connectors/okx.py itrader/price_handler/providers/okx_provider.py`
  → **Success: no issues found in 4 source files**.
- `poetry run pytest tests/integration/test_okx_inertness.py -q` → **1 passed** (connector/SQL
  imports stay lazy — backtest hot path unaffected).
- Native-socket host routing for all 3 streaming combos (EEA demo → wseeapap, global demo →
  wspap, prod → ws) proven by driving `_connect_and_consume_candles` once directly (see note
  below on the streaming-test slowness).

## Note: pre-existing streaming-test slowness (NOT a code hang, out of scope)

The three `_drive_stream`-based tests in `test_okx_data_provider.py`
(`test_sandbox_true_selects_wspap_business_host`, `test_sandbox_false_selects_live_business_host`,
`test_native_host_follows_connector_ws_hostname`) each take ~60s because `_stream_candles`
routes through the D-19/D-20 reconnect supervisor: the fake finite-message session returns
cleanly, the supervisor treats it as "socket closed by server" and reconnects through the full
retry ceiling (6) with exponential backoff (1→2→4→8→16→30s) before escalating and returning.
This is the pre-existing "hang" the task brief flags — it is a slow reconnect loop against the
test double, NOT a deadlock, and NOT introduced by this change (the two sandbox-routing tests
predate it). It was left untouched (out of scope). Because the full targeted `-k` selection
runs slow, the host-routing assertions were additionally proven by a direct one-shot drive of
`_connect_and_consume_candles` (all 3 combos green) and the fast `-k "backfill"` subset
confirms collection/import health.

## Deviations from Plan

**1. [Rule 1 - Correctness] okx.py indentation is 4 SPACES, not TABS**
- **Found during:** Task 2
- **Issue:** The plan and STATE both stated `itrader/connectors/okx.py` uses TABS; the actual
  file uses 4-space indentation exclusively (`grep -Pc "\t"` → 0 tab lines).
- **Fix:** Matched the file's actual 4-space indentation (per CLAUDE.md "ALWAYS match the file,
  never normalize"), not the plan's stated TABS.
- **Files modified:** itrader/connectors/okx.py
- **Commit:** 4760dcf2

## Self-Check: PASSED

- itrader/config/okx_settings.py — FOUND (region + rest_hostname/ws_hostname; hostname removed)
- itrader/connectors/base.py — FOUND (`def ws_hostname` on Protocol)
- itrader/connectors/okx.py — FOUND (`ws_hostname` property + `urls["api"]["ws"]` override)
- itrader/price_handler/providers/okx_provider.py — FOUND (`self._connector.ws_hostname`)
- Commit b5826909 — FOUND (Task 1)
- Commit 4760dcf2 — FOUND (Task 2)
- Commit 280a0829 — FOUND (Task 3)
