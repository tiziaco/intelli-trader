---
phase: 02-okx-connector
plan: 01
subsystem: infra
tags: [pytest-asyncio, pydantic-settings, ccxt, asyncio, protocol, okx, secretstr]

# Dependency graph
requires:
  - phase: 01-account-abstraction
    provides: "LiveConnector Protocol seam (connectors/base.py) + connectors package"
provides:
  - "pytest-asyncio 1.4.0 configured (asyncio_mode=auto, function-scoped fixture loop) under strict filterwarnings"
  - "package-less tests/unit/connectors/ with an async mocked-ccxt conftest (teardown-safe FakeLiveConnector)"
  - "shape-accurate OKX fixtures (business-channel candles confirm 0..0..1; order->ack->fill lifecycle)"
  - "opt-in live OKX smoke scaffold (auto-skips without demo creds, D-09)"
  - "OkxSettings(BaseSettings) credential layer — SecretStr auth triple from plain OKX_API_* (CONN-06 / D-10)"
  - "LiveConnector reshaped to a session/transport contract (call/spawn/client/sandbox/connect/disconnect, D-02)"
affects: [02-02-okx-connector, 02-03-order-arm, 02-04-data-arm, 02-05-native-candle, 03-livebarfeed]

# Tech tracking
tech-stack:
  added: [pytest-asyncio ^1.4.0]
  patterns:
    - "async/sync bridge bottled at the connector edge via call (sync RPC) + spawn (fire-and-track stream task)"
    - "SecretStr env-only credential layer with validation_alias binding plain provider env names under env_prefix=''"
    - "teardown-safe async test double (loop-on-daemon-thread) satisfying a runtime_checkable Protocol"

key-files:
  created:
    - itrader/config/okx_settings.py
    - tests/unit/connectors/conftest.py
    - tests/unit/connectors/fixtures/okx_business_candles.json
    - tests/unit/connectors/fixtures/okx_order_lifecycle.json
    - tests/integration/test_okx_smoke.py
    - tests/unit/config/test_okx_settings.py
  modified:
    - pyproject.toml
    - poetry.lock
    - itrader/connectors/base.py

key-decisions:
  - "OkxSettings uses validation_alias to bind .api_key/.api_secret/.api_passphrase to plain OKX_API_* while keeping env_prefix='' (a bare field under env_prefix='' would read API_KEY, not OKX_API_KEY)"
  - "OKX_SANDBOX alias added for the sandbox flag (avoids a generic SANDBOX env var flipping demo routing)"
  - "FakeLiveConnector implements the real loop-on-daemon-thread design so call() is a genuine synchronous RPC and spawn() returns a cancellable asyncio.Task handle"

patterns-established:
  - "Pattern 1: connector session/transport contract = scheduling seam (call/spawn) + client/sandbox accessors + lifecycle; NO domain (order/candle/balance) slots"
  - "Pattern 2: async fixtures MUST cancel spawned tasks + close the client in teardown (Pitfall 4 — ResourceWarning/RuntimeWarning escalate under filterwarnings=['error'])"

requirements-completed: [CONN-06]

# Metrics
duration: 7min
completed: 2026-07-01
---

# Phase 2 Plan 01: OKX Connector Foundation Summary

**Async test infra (pytest-asyncio + teardown-safe mocked-ccxt harness), the SecretStr `OkxSettings` credential layer reading plain `OKX_API_*`, and the `LiveConnector` Protocol reshaped from a two-arm marker to a call/spawn/client/sandbox session/transport contract — the Wave-0 seam the three OKX arms build against.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-07-01T10:50:31Z
- **Completed:** 2026-07-01T10:57:45Z
- **Tasks:** 3 (Task 2 is TDD: RED → GREEN)
- **Files modified:** 8 (6 created, 3 modified — 1 overlap: none)

## Accomplishments
- Added + configured `pytest-asyncio` 1.4.0 (`asyncio_mode="auto"`, `asyncio_default_fixture_loop_scope="function"`) with `filterwarnings`/`markers` byte-unchanged; lockfile authoritative.
- Built a package-less `tests/unit/connectors/` tree: an async mocked-ccxt conftest with a `FakeLiveConnector` that satisfies the reshaped Protocol and cancels tasks + closes the client in teardown; two documented-shape JSON fixtures; and an auto-skipping opt-in live smoke scaffold.
- Landed `OkxSettings` — the OKX auth triple via `SecretStr` from plain `OKX_API_*` (no `ITRADER_` prefix), passphrase required, `sandbox` defaults True.
- Reshaped `LiveConnector` to a session/transport contract (`call`/`spawn`/`client`/`sandbox`/`connect`/`disconnect`), citing D-02/D-04 and the wspap demo-host correction; `mypy --strict` clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: pytest-asyncio + package-less connectors test tree** - `e1e4613d` (test)
2. **Task 2: OkxSettings credential layer (RED)** - `ff87524c` (test)
3. **Task 2: OkxSettings credential layer (GREEN)** - `537b5002` (feat)
4. **Task 3: Reshape LiveConnector to session/transport contract** - `791d1070` (refactor)

**Plan metadata:** committed separately (docs: complete plan)

## Files Created/Modified
- `pyproject.toml` - Added `pytest-asyncio ^1.4.0` dev dep + `asyncio_mode`/`asyncio_default_fixture_loop_scope` keys.
- `poetry.lock` - pytest-asyncio 1.4.0 pinned.
- `itrader/config/okx_settings.py` - `OkxSettings(BaseSettings)` SecretStr auth triple, `env_prefix=""` + `validation_alias` OKX_API_*.
- `itrader/connectors/base.py` - `LiveConnector` reshaped to the session/transport Protocol.
- `tests/unit/connectors/conftest.py` - async mocked-ccxt fixtures + teardown-safe `FakeLiveConnector`.
- `tests/unit/connectors/fixtures/okx_business_candles.json` - business-channel candle push sequence (confirm 0,0,0,1).
- `tests/unit/connectors/fixtures/okx_order_lifecycle.json` - order → ack → partial → fill payload sequence.
- `tests/integration/test_okx_smoke.py` - opt-in live smoke scaffold (skipif on absent OKX creds).
- `tests/unit/config/test_okx_settings.py` - 7 tests covering round-trip, masking, required passphrase, sandbox, isolation.

## Decisions Made
- **`validation_alias` bridge (deviation from the literal pseudo-code):** the plan/RESEARCH pseudo-code shows fields named `api_key` with `env_prefix=""`, but pydantic-settings would then read `API_KEY`, not `OKX_API_KEY`. Bound each field to its plain `OKX_API_*` name via `validation_alias` while keeping `env_prefix=""` and the `.api_key` accessor — this satisfies every must-have (env_prefix="" present, plain OKX_API_* read, `.get_secret_value()` round-trip) and the behavior tests. See Deviations.
- **`OKX_SANDBOX` alias** added for the `sandbox` flag so a generic `SANDBOX` env var cannot flip demo routing (Rule 2 — safer default).
- **Faithful `FakeLiveConnector`** (loop-on-daemon-thread) rather than a shallow mock, so the transport seam the arms depend on is genuinely exercised (`call` synchronous, `spawn` cancellable) and teardown truly closes resources.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Bound OkxSettings fields to plain OKX_API_* via `validation_alias`**
- **Found during:** Task 2 (OkxSettings implementation)
- **Issue:** The plan's "exact target" pseudo-code declares fields named `api_key`/`api_secret`/`api_passphrase` with `model_config = SettingsConfigDict(env_prefix="")`. Under `env_prefix=""`, pydantic-settings maps field `api_key` to env var `API_KEY` (case-insensitive) — NOT `OKX_API_KEY`. Following the pseudo-code literally would leave the fields unpopulated when `OKX_API_*` is set, making the behavior test (and the credential layer itself) non-functional.
- **Fix:** Kept `env_prefix=""` and the `.api_key` accessor (both required by must-haves/acceptance), and bound each field to its plain env name with `Field(validation_alias="OKX_API_KEY")` etc. Added `OKX_SANDBOX` for the sandbox flag.
- **Files modified:** itrader/config/okx_settings.py
- **Verification:** All 7 `test_okx_settings.py` tests pass (round-trip from OKX_API_*, SecretStr masking, required passphrase, sandbox default/override, extra="ignore" isolation); `grep env_prefix` shows `env_prefix=""`; `mypy --strict` clean.
- **Committed in:** 537b5002 (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix is required for the credential layer to function; it honors every must-have and acceptance criterion (env_prefix="" retained, plain OKX_API_* read, `.get_secret_value()` round-trip, `.api_key` accessor). No scope creep.

## Issues Encountered
- `poetry add` rewrote `pyproject.toml`, so the initial in-place edit of the pytest config had to be re-applied after re-reading the file. No impact.

## Known Stubs
None — the smoke scaffold is an intentional opt-in placeholder (D-09) that grows in later waves; it skips cleanly and is documented as such. Fixtures are documented-shape synthetic payloads (Assumption A1), not stubs blocking any plan goal.

## User Setup Required
OKX demo API keys (`OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE`) are needed ONLY for the opt-in D-09 live smoke test and optional fixture refinement. The gating offline suite runs credential-free — no setup required to build or verify this plan. See the plan's `user_setup` block.

## Next Phase Readiness
- The three OKX arms (Plans 02-03/02-04/02-05) and `OkxConnector` (02-02) can type against the stable `LiveConnector` session/transport contract and reuse the async conftest fixtures.
- `OkxSettings` is ready for the connector to consume via `.get_secret_value()` at the ccxt/native client edge.
- Full suite 1470 passed / 1 skipped under `filterwarnings=["error"]`; `mypy --strict` clean on both new/modified `itrader` files. No async regressions; backtest hot path untouched (no async/connector import on the run path).

## Self-Check: PASSED

- FOUND: itrader/config/okx_settings.py
- FOUND: itrader/connectors/base.py (reshaped)
- FOUND: tests/unit/connectors/conftest.py
- FOUND: tests/unit/connectors/fixtures/okx_business_candles.json
- FOUND: tests/unit/connectors/fixtures/okx_order_lifecycle.json
- FOUND: tests/integration/test_okx_smoke.py
- FOUND: tests/unit/config/test_okx_settings.py
- FOUND commit: e1e4613d, ff87524c, 537b5002, 791d1070

---
*Phase: 02-okx-connector*
*Completed: 2026-07-01*
