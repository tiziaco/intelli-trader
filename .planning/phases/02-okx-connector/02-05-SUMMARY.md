---
phase: 02-okx-connector
plan: 05
subsystem: trading_system/composition-root
tags: [composition-root, dependency-injection, lazy-import, inertness-gate, okx, venue-account, milestone-gate]

# Dependency graph
requires:
  - phase: 02-okx-connector
    plan: 02
    provides: "OkxConnector session/transport primitive (call/spawn/client/sandbox/connect/disconnect) — the concretion constructed once here"
  - phase: 02-okx-connector
    plan: 03
    provides: "OkxExchange(AbstractExchange) order arm — registered under the 'okx' venue here"
  - phase: 02-okx-connector
    plan: 04
    provides: "OkxDataProvider data arm — injected the session here"
provides:
  - "Composition-root wiring: OkxConnector constructed exactly ONCE in LiveTradingSystem.__init__ and the LiveConnector session injected into OkxExchange (registered 'okx'), OkxDataProvider, and VenueAccount — the whole OKX stack lazy-imported inside the live path (D-04, CONN-04)"
  - "VenueAccount injection seam: constructor accepting the injected LiveConnector session (body still Phase 5, RECON-01)"
  - "The recurring milestone-gate proof: a fresh-subprocess inertness test (tests/integration/test_okx_inertness.py) asserting itrader.connectors.okx + ccxt.pro absent from sys.modules after a backtest-root import; SMA_MACD oracle byte-exact"
affects: [03-livebarfeed, 04-paper-path, 05-real-sandbox-recon]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "composition-root DI: the concrete OkxConnector is built ONCE at the root and the LiveConnector session injected into the three arms — only the root imports the concretion; the arms type against the Protocol (D-04)"
    - "lazy import of the whole OKX stack inside LiveTradingSystem.__init__ (mirrors the existing lazy SQL import) — the backtest import path stays async/ccxt/credential-free (hot-path inertness)"
    - "TYPE_CHECKING-guarded LiveConnector import in venue.py: the account barrel is on the backtest hot path, so a runtime connectors-barrel import would pull ccxt.pro and break inertness"
    - "fresh-subprocess import-inertness gate (v1.6 quarantine pattern): the running session already imported the OKX stack via sibling suites, so a clean interpreter is required for a sys.modules-absence assertion"

key-files:
  created:
    - tests/unit/portfolio/test_venue_account_wiring.py
    - tests/integration/test_okx_inertness.py
  modified:
    - itrader/portfolio_handler/account/venue.py
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "LiveConnector typed under TYPE_CHECKING (string annotation) in venue.py — NOT a runtime import from itrader.connectors. The account barrel re-exports VenueAccount and is imported by the backtest hot path (SimulatedCashAccount), so a runtime connectors-barrel import would pull ccxt.pro onto the backtest path and fail the inertness gate this plan proves."
  - "The connector is constructed + connect()'d in __init__ and disconnect()'d in stop(); the arms are registered + injected but their stream startup (OkxExchange.connect() / OkxDataProvider.start_stream()) is deferred to Phase 4/5 live wiring (the 02-03 SUMMARY boundary) — this plan wires the seam, it does not start live streaming."
  - "The inertness probe forbids plain ccxt as well as ccxt.pro + itrader.connectors.okx — a stronger gate than the plan-mandated pair; all three are absent on the backtest path today, so the tighter assertion is honest and catches any future async/connector import hoist."

requirements-completed: [CONN-04]

# Metrics
duration: 9min
completed: 2026-07-01
---

# Phase 2 Plan 05: OKX Composition-Root Wiring + Milestone Gate Summary

**Wired the phase together at the composition root: `OkxConnector` is constructed exactly ONCE in `LiveTradingSystem.__init__` and the `LiveConnector` session injected into the three arms (`OkxExchange` registered under the `'okx'` venue, `OkxDataProvider`, `VenueAccount`) — the whole OKX stack lazy-imported inside the live path so the backtest path stays async/ccxt/credential-free (D-04, CONN-04) — plus the `VenueAccount` injection seam (body still Phase 5) and a fresh-subprocess inertness gate proving the SMA_MACD oracle byte-exact with the OKX machinery inert on the backtest hot path.**

## Performance

- **Duration:** ~9 min
- **Tasks:** 3 (all `type=auto`)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **Task 1 — VenueAccount injection seam:** added `VenueAccount.__init__(connector)` storing the injected `LiveConnector` session (`self._connector = connector`) so the composition root can wire it (D-04 / CONN-04). The `Account` contract methods (`balance`/`available`/`reserve`/`release`) stay Phase-5 `NotImplementedError` stubs (RECON-01). `LiveConnector` is typed under a `TYPE_CHECKING` guard with a string annotation — a runtime `from itrader.connectors import ...` would pull the connectors barrel (and `ccxt.pro`) onto the backtest hot path (the account barrel re-exports `VenueAccount`), breaking the inertness gate. `mypy --strict itrader/portfolio_handler/account/venue.py` clean (the real type gate — venue.py is NOT in the mypy overrides).
- **Task 2 — composition-root wiring:** inside `LiveTradingSystem.__init__` the whole OKX stack is LAZY-imported (mirroring the existing lazy SQL import), then `OkxConnector(OkxSettings())` is constructed exactly ONCE and `connect()`'d, and the session is injected into each arm: `OkxExchange(self.global_queue, connector)` registered via `self.execution_handler.exchanges['okx'] = ...` (the `on_order` router already dispatches by `event.exchange`; `init_exchanges` is UNCHANGED), `OkxDataProvider(connector, symbol, timeframe)`, and `VenueAccount(connector)`. `connector.disconnect()` is wired into `stop()` (cancels stream tasks + closes sessions). Only this file imports the `OkxConnector` concretion; the arms type against the `LiveConnector` Protocol. No top-level `connectors.okx` / `okx_settings` / `providers.okx_provider` / `exchanges.okx` import.
- **Task 3 — milestone gate:** wrote `tests/integration/test_okx_inertness.py` — a fresh-subprocess probe (mirroring the v1.6 import-quarantine pattern) that imports ONLY `itrader.trading_system.backtest_trading_system` and asserts `itrader.connectors.okx`, `ccxt.pro`, and plain `ccxt` are absent from `sys.modules`. A clean interpreter is required because the running session already imported the OKX stack via the sibling connector/execution suites. Proved the recurring gate: SMA_MACD oracle byte-exact (**134 trades / final_equity 46189.87730727451**, `check_exact=True`), full suite **1498 passed / 1 skipped** under `filterwarnings=["error"]`.

## Task Commits

Each task was committed atomically:

1. **Task 1: VenueAccount injection seam** — `36c04d55` (feat)
2. **Task 2: OkxConnector composition-root wiring + inject the three arms** — `7058d9a5` (feat)
3. **Task 3: backtest-path OKX/ccxt.pro import-inertness gate** — `a2e14fb5` (test)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `itrader/portfolio_handler/account/venue.py` (modified, 4-space) — added `__init__(connector)` injection seam; `LiveConnector` typed under `TYPE_CHECKING`; body still Phase-5 stubs.
- `itrader/trading_system/live_trading_system.py` (modified, 4-space) — lazy-import + construct `OkxConnector` once in `__init__`, inject the session into the three arms, register `'okx'`, wire `disconnect()` into `stop()`.
- `tests/unit/portfolio/test_venue_account_wiring.py` (created) — 5 tests: the seam stores the injected session; the four abstract methods still raise `NotImplementedError` (Phase-5 boundary intact).
- `tests/integration/test_okx_inertness.py` (created) — fresh-subprocess inertness gate (`itrader.connectors.okx` + `ccxt.pro` + `ccxt` absent after a backtest-root import).

## Decisions Made

- **TYPE_CHECKING-guarded `LiveConnector` import (venue.py):** the plan said "import `LiveConnector` from `itrader.connectors`", but that barrel imports `OkxConnector` → `ccxt.pro`. Since `VenueAccount` is re-exported from the `account` barrel that the backtest hot path imports (`SimulatedCashAccount`), a runtime connectors-barrel import would pull `ccxt.pro` onto the backtest path and fail the very inertness gate Task 3 proves. Guarding the import under `TYPE_CHECKING` with a string annotation satisfies `mypy --strict` at zero runtime cost — the correct realization of the D-04 typing intent.
- **Seam-only arm wiring (no stream startup):** the connector transport is `connect()`'d in `__init__` and `disconnect()`'d in `stop()`, but the arms are only registered + injected — their stream startup (`OkxExchange.connect()` / `OkxDataProvider.start_stream()`) is a Phase 4/5 live-wiring step (the boundary the 02-03 SUMMARY drew). This plan wires the seam; it does not begin live streaming.
- **Stronger inertness assertion:** the probe forbids plain `ccxt` in addition to the plan-mandated `ccxt.pro` + `itrader.connectors.okx`. All three are absent on the backtest path today, so the tighter gate is honest and catches any future async/connector import hoist earlier.

## Deviations from Plan

### Auto-fixed Issues

None. The plan executed as written, with one planned-import realization decision (TYPE_CHECKING guard for `LiveConnector` in venue.py) driven by the plan's own inertness gate — documented under Decisions Made rather than as a deviation, since it is the faithful way to honor both the D-04 typing intent and the CONN-04 inertness requirement simultaneously (the plan's `<interfaces>` note flags venue.py as the real type gate, and the inertness gate as the milestone gate — the guard is the only way both hold).

**Total deviations:** 0 auto-fixed. No architectural changes, no scope creep.

## Milestone Gate

- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` green — SMA_MACD **134 trades / final_equity 46189.87730727451** (`check_exact=True`), determinism double-run identical (the oracle harness asserts both).
- **No W1/W2 regression:** the backtest import path pulls NO OKX/async/ccxt code — proven structurally by the fresh-subprocess inertness gate (not disciplined). The OKX stack is additive, lazy-imported inside the live path only; no backtest-path module changed.
- **Held constraints:** `mypy --strict itrader/portfolio_handler/account/venue.py` clean (the real type gate — `live_trading_system.py` is in the D-live `ignore_errors` override, so a mypy invocation on it is a no-op and is NOT claimed); full suite **1498 passed / 1 skipped** under `filterwarnings=["error"]` (no ResourceWarning/RuntimeWarning escalation); 4-space indentation matched to both edited files.

## Known Stubs

None blocking. Two documented seam boundaries (not incomplete stubs):

- **`VenueAccount` body** — `balance`/`available`/`reserve`/`release` remain `NotImplementedError` "deferred to Phase 5 (RECON-01)". This plan lands only the constructor injection seam (D-03); the cached-venue body is Phase 5.
- **Arm stream startup** — the arms are registered + injected but their `connect()` / `start_stream()` are Phase 4/5 live-wiring steps. The connector transport is connected; live streaming is not started here.

## Threat Flags

None. All new surface is covered by the plan's `<threat_model>`: T-02-05-INERT (subprocess inertness gate — tested), T-02-05-CROSSIMPORT (only the root imports the concretion; grep-verified no top-level okx import), T-02-05-CRED (`OkxSettings()` constructed once at the root, backtest path never constructs it), T-02-05-SHUTDOWN (`disconnect()` wired into `stop()`), T-02-SC (no new package).

## Verification Evidence

- `poetry run pytest tests/unit/portfolio/test_venue_account_wiring.py -x` → 5 passed.
- `poetry run mypy --strict itrader/portfolio_handler/account/venue.py` → Success: no issues found.
- `grep -q "OkxConnector" itrader/trading_system/live_trading_system.py` → present; `grep -nE "^(from|import).*(connectors\.okx|okx_settings|providers\.okx_provider|exchanges\.okx)"` → grep-zero (no top-level okx import).
- `init_exchanges` in `execution_handler.py` unchanged (no `okx`/`OkxExchange` reference).
- `poetry run pytest tests/unit -x` → 1338 passed.
- `poetry run pytest tests/integration/test_okx_inertness.py` → 1 passed (backtest-root import: `itrader.connectors.okx` + `ccxt.pro` + `ccxt` absent).
- `poetry run pytest tests/integration/test_backtest_oracle.py` → 3 passed (byte-exact + determinism).
- `poetry run pytest tests` → 1498 passed, 1 skipped (the opt-in OKX smoke test, credentials absent), no warning escalation.

## Next Phase Readiness

- The phase is wired end-to-end: the connector is built once at the root and injected into all three arms; the `'okx'` venue is registered; the backtest path is proven inert. Phase 3 (`LiveBarFeed`) registers its closed-bar consumer via `OkxDataProvider.set_bar_sink(...)` and drives warmup/stream through the connector loop. Phase 5 (real/sandbox + reconciliation) fills the `VenueAccount` cached-venue body against the injection seam landed here, and starts the arm streams (`OkxExchange.connect()`).
- **Phase 2 milestone gate green:** oracle byte-exact + backtest path OKX/async-free, proven by a dedicated fresh-subprocess inertness test.

## Self-Check: PASSED

- FOUND: itrader/portfolio_handler/account/venue.py (VenueAccount.__init__ seam)
- FOUND: itrader/trading_system/live_trading_system.py (OkxConnector wiring)
- FOUND: tests/unit/portfolio/test_venue_account_wiring.py
- FOUND: tests/integration/test_okx_inertness.py
- FOUND commit: 36c04d55 (feat, Task 1)
- FOUND commit: 7058d9a5 (feat, Task 2)
- FOUND commit: a2e14fb5 (test, Task 3)

---
*Phase: 02-okx-connector*
*Completed: 2026-07-01*
