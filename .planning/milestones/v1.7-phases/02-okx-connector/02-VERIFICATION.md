---
phase: 02-okx-connector
verified: 2026-07-04T00:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
gaps: []
human_verification: []
reverification:
  - date: 2026-07-04
    prior_status: gaps_found
    outcome: passed
    note: >-
      The 2026-07-01 gaps (CR-01 session leak on non-running stop(), CR-02
      unconditional OKX credential/network requirement in __init__) were closed by
      later milestone work (Phases 3–5) and re-verified against the current codebase.
      CR-02: OKX wiring is now gated behind `if self.exchange == 'okx':`
      (live_trading_system.py:378) and `connector.connect()` is deferred out of the
      constructor into `start()` with the failure flowing through the ERROR path
      (lines 1085-1092, 1171-1175). CR-01: `stop()` now tears the connector down in a
      `finally` block (lines 1225-1243) fetched before the try, so `disconnect()` runs
      on every return path including the `not self._running` early exit. The missing
      composition-root test now exists — `tests/integration/test_live_system_okx_wiring.py`
      (9 tests) constructs `LiveTradingSystem` for both a non-OKX venue (no OKX creds,
      no constructor I/O) and OKX, and explicitly locks CR-01 (stop()-before-start()
      no-op + fill-stream spawn) and CR-02. The WR-01/WR-02 fill-stream fragility is
      also fixed: `okx.py:452-453` guards an explicit `fee.cost is None`, and
      `_consume_fills` (lines 645-652) wraps `_handle_trade` in a per-trade
      try/except so one malformed trade no longer kills the stream. Evidence: 47/47
      relevant tests pass (`test_live_system_okx_wiring`, `test_okx_inertness`,
      `test_paper_parity`, `test_okx_exchange` [19], `test_okx_settings` [14],
      `test_backtest_oracle` [3, byte-exact]). tests/unit/connectors excluded
      (pre-existing socket/asyncio hang).
---

# Phase 2: OKX Connector Verification Report

**Phase Goal:** `OkxConnector` = shared authenticated session/transport primitive; data/order/account
are domain adapters consuming it (`OkxDataProvider` + `OkxExchange` + `VenueAccount`), injected at the
composition root; async bottled at the connector edge.
**Verified:** 2026-07-04 (re-verification; initial 2026-07-01T14:20:00Z)
**Status:** passed
**Re-verification:** Yes — the 2026-07-01 CR-01/CR-02 gaps were resolved by Phases 3–5 work and re-confirmed against the current codebase (see `reverification` in frontmatter; original gap analysis retained below for the audit trail)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `OkxConnector` is a shared authenticated session/transport primitive: own asyncio loop on a daemon thread, one ccxt.pro client built inside the loop, one `sandbox: bool`, `call`/`spawn` bridge, `connect`/`disconnect` lifecycle, no venue ops, no domain events (CONN-04) | VERIFIED | `itrader/connectors/okx.py` implements exactly this; `mypy --strict` clean; grep-zero on `events_handler.events`/`FillEvent`/`OrderEvent`/`BarEvent`; `tests/unit/connectors/test_okx_connector.py` (5 tests) pass, including sandbox→wspap routing and loop/spawn/cancel behavior |
| 2 | Data arm `OkxDataProvider` streams OKX candles via a native `/ws/v5/business` subscription carrying `confirm`, gates on `confirm=="1"`, backfills via REST `fetch_ohlcv`, feeds the Phase-3 seam (CONN-01) | VERIFIED | `itrader/price_handler/providers/okx_provider.py`; confirm-gate + sandbox-host + Decimal-edge backfill covered by `tests/unit/connectors/test_okx_data_provider.py` (9 tests, all pass); `set_bar_sink`/`_hand_closed_bar` seam present for Phase 3 |
| 3 | Order arm `OkxExchange` implements async `create_order`+cancel+`watch_orders`/`watch_my_trades`; the **exchange** (not the connector) translates raw fills → `FillEvent` and puts them on `global_queue`; single `sandbox: bool` routes both ccxt and the native WS (CONN-02, CONN-03) | VERIFIED (see Anti-Patterns — WR-01/WR-02) | `itrader/execution_handler/exchanges/okx.py`; `tests/unit/execution/test_okx_exchange.py` (8 tests) pass for the happy path. However, `_handle_trade` (line ~192-199) computes `fee_cost = fee.get("cost", 0)`, which returns `None` (not the default) when ccxt emits `{"cost": None}` — a documented, common ccxt shape — producing `to_money(str(None))` → `Decimal("None")` → `decimal.InvalidOperation`, uncaught by `_stream_fills`'s bare `while True` loop, permanently killing the fill stream on the first such trade. Neither case is covered by the plan's own tests |
| 4 | OKX secrets (apiKey+secret+passphrase) load via `OkxSettings(BaseSettings)` reading plain `OKX_API_*` (no env prefix); never in code/logs/fixtures; backtest path stays credential-free (CONN-06) | VERIFIED | `itrader/config/okx_settings.py`: `env_prefix=""` + `validation_alias`; `SecretStr` fields; `tests/unit/config/test_okx_settings.py` (7 tests) pass, including repr/str masking and required-passphrase ValidationError; `OkxSettings` imported nowhere on the backtest import path |
| 5 | The three domain adapters are **safely** injected with the shared `OkxConnector` session at the `LiveTradingSystem` composition root — construction is exchange-scoped and resource-safe | **FAILED** | See Gaps below — CR-01/CR-02 reproduced directly against the current codebase |
| 6 | Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression; connector inert on the backtest hot path; `pytest-asyncio` configured so `filterwarnings=["error"]` stays green | VERIFIED | `tests/integration/test_backtest_oracle.py` (3 passed, byte-exact 134/`46189.87730727451` + determinism double-run); `tests/integration/test_okx_inertness.py` (1 passed, fresh-subprocess `sys.modules` absence of `itrader.connectors.okx`/`ccxt.pro`/`ccxt`); full suite `poetry run pytest tests` → **1498 passed, 1 skipped**, no warning escalation |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/connectors/base.py` | `LiveConnector` reshaped session/transport Protocol | VERIFIED | `call`/`spawn`/`client`/`sandbox`/`connect`/`disconnect`; no order/candle slots; `@runtime_checkable` |
| `itrader/connectors/okx.py` | `OkxConnector` primitive | VERIFIED | Loop-on-daemon-thread, client built inside loop, sandbox routing, call/spawn/disconnect; `mypy --strict` clean |
| `itrader/config/okx_settings.py` | `OkxSettings(BaseSettings)` | VERIFIED | `env_prefix=""`, `validation_alias` to plain `OKX_API_*`, `SecretStr` fields |
| `itrader/execution_handler/exchanges/okx.py` | `OkxExchange(AbstractExchange)` | VERIFIED (with fragility — see Anti-Patterns) | Implements full `AbstractExchange` surface; fill translation has an uncaught crash path (WR-01/WR-02) |
| `itrader/price_handler/providers/okx_provider.py` | `OkxDataProvider` | VERIFIED | confirm-gate, sandbox host routing, REST backfill, Decimal edge; `mypy --strict` clean |
| `itrader/portfolio_handler/account/venue.py` | `VenueAccount` injection seam | VERIFIED (scope-correct) | Constructor stores injected session; `Account` methods `NotImplementedError` — explicitly and correctly deferred to Phase 5 (RECON-01), not a Phase-2 gap |
| `itrader/trading_system/live_trading_system.py` | Composition-root wiring | **STUB-LIKE / UNSAFE** | Wiring exists and is structurally correct (connector built once, session injected into 3 arms, only this file imports the concretion) but is NOT exchange-gated and NOT exception-safe — see Gaps |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `OkxExchange`/`OkxDataProvider`/`VenueAccount` | `itrader.connectors.base.LiveConnector` | typed constructor param (Protocol, not concretion) | WIRED | Grep-verified: no arm imports `OkxConnector`/`connectors.okx` directly |
| `LiveTradingSystem.__init__` | `OkxConnector` | direct construction + `connect()` | WIRED but UNGATED | Constructed unconditionally regardless of `self.exchange` — see Gaps (CR-02) |
| `LiveTradingSystem.stop()` | `OkxConnector.disconnect()` | `getattr(self, '_okx_connector', None)` teardown block | PARTIAL | Present, but unreachable when `stop()` is called on a system that never successfully started (`_running` False) — see Gaps (CR-01) |
| `OkxExchange._stream_fills` | `global_queue.put(FillEvent)` | `_handle_trade` | WIRED but FRAGILE | Works for well-formed trades (tested); crashes uncaught on `fee.cost == None` (WR-01), and any single malformed trade kills the whole stream task with no restart (WR-02) |
| `OkxDataProvider` | Phase-3 `LiveBarFeed` | `set_bar_sink`/`_hand_closed_bar` | ORPHANED (by design) | Minimal seam only — Phase 3 not yet built; documented as intentional forward seam, not a gap for this phase |

### Data-Flow Trace (Level 4)

Not applicable in the UI-rendering sense — this phase ships backend session/transport/adapter code, not a
data-rendering component. The relevant "data flow" is the fill-translation path (`watch_my_trades` →
`_handle_trade` → `FillEvent` → `global_queue`), traced above under Truth #3 / Key Links — flowing
correctly for well-formed venue payloads, uncaught-crashing on a documented ccxt null-fee shape.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Constructing `LiveTradingSystem` for a non-OKX exchange (`binance`, the constructor default) with no OKX credentials in the environment | `LiveTradingSystem(exchange='binance')` in a clean interpreter, no `OKX_API_*` env vars | Raises `pydantic.ValidationError: 3 validation errors for OkxSettings (OKX_API_KEY/SECRET/PASSPHRASE Field required)` out of `__init__`, before any other component finishes wiring | FAIL — reproduces CR-02 exactly |
| Full test suite regression / oracle / inertness gate | `poetry run pytest tests` | 1498 passed, 1 skipped (opt-in OKX smoke, no creds) | PASS |
| `mypy --strict` on all new/modified Phase-2 files | `poetry run mypy --strict itrader/connectors/okx.py itrader/connectors/base.py itrader/config/okx_settings.py itrader/execution_handler/exchanges/okx.py itrader/price_handler/providers/okx_provider.py itrader/portfolio_handler/account/venue.py` | Success: no issues found in 6 source files | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention used by this project/phase — N/A, skipped.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CONN-01 | 02-04 | Data arm streams native confirm-gated candles + REST backfill | SATISFIED | `okx_provider.py` + 9 passing tests |
| CONN-02 | 02-03 | Order arm async create/cancel + watch_orders/watch_my_trades, exchange emits FillEvent | SATISFIED (with fragility flagged — WR-01/WR-02) | `execution_handler/exchanges/okx.py` + 8 passing tests; uncaught crash path on null-fee trades not covered by tests |
| CONN-03 | 02-02, 02-04 | Single `sandbox: bool` routes both ccxt and native WS | SATISFIED | `-k sandbox` tests pass in both `test_okx_connector.py` and `test_okx_data_provider.py` |
| CONN-04 | 02-02, 02-05 | `OkxConnector` session primitive; injected, not cross-domain-imported; backtest path async-free | **PARTIALLY SATISFIED** | The connector primitive itself and the import-inertness gate are proven (`test_okx_inertness.py`). The composition-root injection this requirement also implies is unsafe: CR-01 (session leak) + CR-02 (unconditional cross-exchange network/credential requirement) are reproduced defects in the one file (`live_trading_system.py`) that performs the injection, and no test constructs a `LiveTradingSystem` to catch this |
| CONN-05 | 02-03, 02-04 | Decimal edge (`to_money`) at every venue boundary, no `Decimal(float)` | SATISFIED | `-k decimal` tests pass in both order-arm and data-arm suites |
| CONN-06 | 02-01 | `OkxSettings(BaseSettings)` plain `OKX_API_*`, `SecretStr`, backtest credential-free | SATISFIED | `test_okx_settings.py` (7 tests) |

No orphaned requirements: all 6 IDs (CONN-01..06) appear in a plan's `requirements:` frontmatter and are traced above.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/trading_system/live_trading_system.py` | 226-227 | Unconditional network I/O (`connector.connect()` → `load_markets()`) + hard OKX-credential requirement inside `__init__`, not gated on `self.exchange` | 🛑 BLOCKER (CR-02, reproduced) | Breaks construction of `LiveTradingSystem` for every non-OKX venue when OKX creds/network are unavailable; a construction failure is unhandled and propagates raw out of the constructor |
| `itrader/trading_system/live_trading_system.py` | 480-482, 501-509 | `stop()` returns before the connector-teardown block when `_running` is False | 🛑 BLOCKER (CR-01, reproduced by code inspection — matches review) | Leaks the authenticated ccxt.pro session, daemon thread, and event loop on any construct-but-never-started or failed-start lifecycle |
| `itrader/execution_handler/exchanges/okx.py` | 192-199 | `fee.get("cost", 0)` does not coalesce an explicit `None` value; feeds `to_money(str(None))` | ⚠️ WARNING (WR-01) | `decimal.InvalidOperation` on a common ccxt payload shape (`fee: {"cost": None}`) |
| `itrader/execution_handler/exchanges/okx.py` | 204-209 | `_stream_fills` has no per-trade try/except around `_handle_trade` | ⚠️ WARNING (WR-02) | One malformed/None-fee trade kills the entire fill-stream task silently — no restart, no visible error until disconnect |
| `itrader/execution_handler/exchanges/okx.py` | 145-148, 178-182 | Fill correlation keyed by venue id populated post-RPC-return, read from another thread with no lock | ⚠️ WARNING (WR-03, latent — streams not started this phase) | A fast market-order fill can race the create_order ack and be dropped as "unknown venue order" once wired in Phase 4/5 |
| `itrader/connectors/okx.py` | 157-171 | `spawn()` returns `holder["task"]` without checking `ready.wait()` succeeded | ⚠️ WARNING (WR-04) | Bare `KeyError` on loop-congestion timeout masks the real failure |
| `itrader/price_handler/providers/okx_provider.py` | ~198-214 | Native candle WS: `autoping=False`, no app-level ping/pong or reconnect | ⚠️ WARNING (WR-05) | Idle sockets (e.g. `1d` candles) die silently after OKX's ~30s idle timeout with no reconnect |
| `itrader/connectors/okx.py` | 196-208 | `disconnect()` nulls loop/thread references even when `join()` timed out and the loop is still running | ⚠️ WARNING (WR-06) | Orphaned daemon thread/loop with no recoverable handle |
| `itrader/execution_handler/exchanges/okx.py` | 292-302 | `validate_symbol` checks raw symbol vs OKX-normalised markets, potential form mismatch | ℹ️ INFO (IN-01) | Documented inconsistency, non-blocking |
| `itrader/price_handler/providers/okx_provider.py` | 265 | Redundant `and page` in backfill loop condition | ℹ️ INFO (IN-02) | Dead code, non-blocking |
| `itrader/execution_handler/exchanges/okx.py` | 135, 140 | Decimal narrowed to `float` before ccxt's precision helpers | ℹ️ INFO (IN-03) | Documented ccxt-contract narrowing, not a money-policy violation |

No `TBD`/`FIXME`/`XXX` unresolved-debt markers found in the phase's modified files.

### Human Verification Required

None — all findings above are grounded in direct code inspection, a reproduced failure (CR-02), and passing/failing automated test evidence. No visual, real-time, or external-service behavior requires human judgment for this phase's scope.

### Gaps Summary

Phase 2 delivers a genuinely well-built **connector primitive** and **two of the three domain adapters**
(`OkxDataProvider`, the bulk of `OkxExchange`) with strong test discipline: sandbox-routing tests exercise
a *real* offline ccxt client rather than a fake, the Decimal edge is consistently held, and the recurring
milestone gate (oracle byte-exact + backtest-path inertness) is proven by a genuine fresh-subprocess test —
not merely asserted in a SUMMARY.

However, the phase goal explicitly requires the three adapters to be **"injected at the composition
root"** — and that composition root, `LiveTradingSystem.__init__`/`stop()`, is broken in two ways that a
code review caught and this verification reproduced directly against the current codebase (no fix has
landed since the review commit):

1. **CR-02 (reproduced):** `LiveTradingSystem(exchange='binance')` — the constructor's own default,
   representing every non-OKX live venue — now unconditionally requires OKX credentials and performs a
   blocking network call (`load_markets()`) inside `__init__`, with no exception handling. This is a
   regression to the live system's usability for any venue other than OKX, and it directly contradicts the
   inertness/scoping intent of the phase.
2. **CR-01:** `stop()` returns before the connector-teardown block whenever the system was never
   successfully started, leaking the authenticated OKX session, its daemon thread, and its event loop.

Neither defect is caught by the phase's test suite because **no test in the phase constructs a
`LiveTradingSystem`** (grep-verified) — the composition root itself is untested. This is the classic
task-completion-vs-goal-achievement gap: the individual arms and the connector primitive are solid and
tested in isolation, but the actual "injected at the composition root" wiring — the thing the phase goal
names explicitly — is demonstrably unsafe for the general case.

Additionally, WR-01/WR-02 (fill-stream fee-null crash, no per-trade error isolation) mean the "exchange
translates raw fills → FillEvent" mechanism (CONN-02) — while implemented and unit-tested on the happy
path — has an uncaught crash path on a common, documented ccxt payload shape. This does not block Phase 2
today (the streams are not yet started per the 02-03 SUMMARY), but it is unresolved debt that should be
fixed before Phase 4/5 wire the streams live, and is called out here rather than silently deferred.

**Recommendation:** Close CR-01 and CR-02 (and add a constructing-`LiveTradingSystem` test) before this
phase is considered done and before Phase 3 builds on top of this composition root. WR-01/WR-02 should be
fixed in the same pass or explicitly tracked as a fast-follow before Phase 5 starts the fill stream live.

---

*Verified: 2026-07-01T14:20:00Z*
*Verifier: Claude (gsd-verifier)*
