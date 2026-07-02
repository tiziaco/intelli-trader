---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 02
subsystem: testing
tags: [pytest, ccxt.pro, okx, reconciliation, test-double, fixtures, asyncio]

# Dependency graph
requires:
  - phase: 02-okx-connector
    provides: "Phase-2 teardown-safe FakeLiveConnector (loop-on-daemon-thread; call/spawn/client/sandbox) + OKX-shaped synthetic fixtures + skipif-no-creds opt-in sandbox pattern"
provides:
  - "Tree-agnostic tests/support package with a credential-free, teardown-safe FakeLiveConnector reusable from every Phase-5 test tree (portfolio/order/execution/integration)"
  - "Fake ccxt.pro client wired with canned watch_my_trades/watch_orders/watch_balance/watch_positions push streams + fetch_balance/fetch_positions/fetch_open_orders/fetch_my_trades REST snapshots"
  - "Synthetic ccxt-unified OKX recon payload fixtures (no secrets, no real order ids)"
  - "Root fake_venue_connector pytest fixture (connected, teardown-safe)"
  - "Opt-in slow OKX-demo reconciliation suite scaffold (skipif-no-creds) with three named skeleton bodies"
affects: [05-03, 05-04, 05-05, VenueAccount, reconciliation, restart-rehydration, persistence-live-drive]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared test double promoted OUT of a subtree conftest into a tests/support package (outside tests/unit/* so no same-named-package collision)"
    - "Canned async push stream (_CannedStream): returns fixture batches one per await, then parks on a never-set Event until the spawned task is cancelled (Pitfall-4 teardown-safe)"
    - "ccxt-unified fixtures keep floats on purpose (Pitfall 2) so downstream to_money(str(...)) edge is exercised, not pre-Decimalized"

key-files:
  created:
    - tests/support/__init__.py
    - tests/support/fake_venue_connector.py
    - tests/support/fixtures/okx_recon_payloads.json
    - tests/e2e/test_okx_sandbox_recon.py
    - tests/unit/connectors/test_fake_venue_connector.py
  modified:
    - tests/conftest.py

key-decisions:
  - "Recon fixtures use ccxt-UNIFIED shapes (watch_balance()['total']['USDT'], fetch_positions() list, trades with id/order/amount/price/fee/timestamp) — matching what Phase-5 VenueAccount/reconcile code consumes via the ccxt.pro client, not the raw OKX WS row shapes the Phase-2 data-arm fixtures use"
  - "Exhausted _CannedStream parks on asyncio.Event().wait() (blocks until cancelled) rather than raising StopAsyncIteration — mirrors a live ccxt.pro socket with no further updates and keeps disconnect() teardown clean"
  - "make_fake_venue_connector returns an UNCONNECTED connector; the root fixture owns connect()/disconnect() so lifecycle/teardown stays in one place"

patterns-established:
  - "tests/support is the tree-agnostic home for shared Phase-5 doubles; import via `from tests.support.fake_venue_connector import ...` (mirrors existing `from tests.integration._oracle_harness import ...`)"
  - "Opt-in network suites: module-level pytestmark = [mark.slow, skipif-no-creds] + _pending() body skips so a creds-holding dev never hits false failures before the feature lands"

requirements-completed: [RECON-06, RES-01]

# Metrics
duration: 18min
completed: 2026-07-02
---

# Phase 5 Plan 02: Wave-0 Offline Reconciliation Test Infrastructure Summary

**Credential-free, teardown-safe FakeLiveConnector with canned ccxt-unified account/fill/order streams + REST snapshots, reusable from every Phase-5 test tree, plus an opt-in slow OKX-demo reconciliation suite scaffold that collects and skips cleanly without credentials.**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-07-02
- **Tasks:** 2
- **Files modified:** 6 (5 created, 1 modified)

## Accomplishments
- Promoted the Phase-2 teardown-safe `FakeLiveConnector` out of the connectors subtree into a tree-agnostic `tests/support` package (verbatim loop-on-daemon-thread teardown discipline), extended with the Phase-5 reconciliation surface: canned `watch_my_trades` / `watch_orders` / `watch_balance` / `watch_positions` push streams + `fetch_balance` / `fetch_positions` / `fetch_open_orders` / `fetch_my_trades` REST snapshots driven from a synthetic fixture.
- Recorded credential-free, ccxt-unified OKX recon payloads (`okx_recon_payloads.json`) narrating a BTC/USDT limit-buy filling in two increments (streams) plus the post-full-fill restart state (REST snapshots + one resting take-profit leg) — floats kept on purpose so the downstream `to_money(str(...))` edge is exercised.
- Exposed a root `fake_venue_connector` fixture so portfolio / order / execution / integration trees request the same double with no per-tree conftest.
- Stood up the opt-in `slow` OKX-demo reconciliation suite scaffold with three named skeleton bodies (real demo fill → FillEvent, VenueAccount post-fill reconcile, two-sided restart) that skip cleanly without credentials and fill in as later Phase-5 plans land.
- Full suite still collects (1559 tests) — no package-collision regression from the new `tests/support` package.

## Task Commits

Each task was committed atomically:

1. **Task 1: Shared FakeLiveConnector + recorded recon payloads (D-09 offline gate)** - `ca29843a` (test)
2. **Task 2: Opt-in slow live-sandbox suite scaffold (D-09, RECON-06)** - `af29a99f` (test)

## Files Created/Modified
- `tests/support/__init__.py` - Barrel re-exporting the shared double's public surface (`FakeLiveConnector`, `build_fake_recon_client`, `make_fake_venue_connector`, `load_recon_payloads`).
- `tests/support/fake_venue_connector.py` - The teardown-safe `FakeLiveConnector`, the `_CannedStream` async push driver, `build_fake_recon_client` (fake ccxt.pro client wiring), and the `make_fake_venue_connector` factory.
- `tests/support/fixtures/okx_recon_payloads.json` - Synthetic ccxt-unified recon payloads (streams + REST snapshots), no secrets, all `PLACEHOLDER-*` ids.
- `tests/conftest.py` - Added the root `fake_venue_connector` fixture (deferred import; connect on setup, disconnect on teardown).
- `tests/unit/connectors/test_fake_venue_connector.py` - Smoke coverage: credential-free gate, full recon surface, construct→disconnect teardown-safety, `call` REST drive, `spawn` stream consume-then-cancel, root-fixture reuse, `_CannedStream` parking.
- `tests/e2e/test_okx_sandbox_recon.py` - Opt-in `slow` OKX-demo reconciliation suite scaffold (skipif-no-creds + three skeleton bodies).

## Decisions Made
- **ccxt-unified fixture shapes (not raw OKX WS rows).** Phase-5 reconciliation code (`VenueAccount._stream_account`, `snapshot`, per-fill reconcile) consumes the ccxt.pro client's unified return shapes — `watch_balance()["total"]["USDT"]`, `fetch_positions()` list, trades with `id`/`order`/`amount`/`price`/`fee`/`timestamp`, orders with cumulative `filled`/`status`. The fixtures match that, distinct from the Phase-2 data-arm fixtures which capture raw OKX business-channel rows.
- **Exhausted stream parks, not raises.** `_CannedStream` blocks on `asyncio.Event().wait()` after its canned batches, mirroring a live socket with no further updates and keeping `disconnect()` cancellation clean under `filterwarnings=["error"]`.
- **Factory returns unconnected; fixture owns lifecycle.** `make_fake_venue_connector` builds client+connector but does not connect, so the single `fake_venue_connector` fixture owns `connect()`/`disconnect()` teardown.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added a committed smoke test file for the shared double**
- **Found during:** Task 1 (shared FakeLiveConnector)
- **Issue:** Task 1's acceptance criteria explicitly require "A smoke test constructing FakeLiveConnector then calling disconnect() emits no ResourceWarning/RuntimeWarning under the strict filter", but the plan's `files_modified` list did not name a test file to host it.
- **Fix:** Added `tests/unit/connectors/test_fake_venue_connector.py` (7 tests) so the smoke coverage runs under the exact Task-1 verify command (`pytest tests/unit/connectors -x -q`), carries the folder-derived `unit` marker, and lives alongside the Phase-2 FakeLiveConnector tests it extends.
- **Files modified:** tests/unit/connectors/test_fake_venue_connector.py
- **Verification:** `poetry run pytest tests/unit/connectors -x -q` → 21 passed (7 new + 14 Phase-2), clean under `filterwarnings=["error"]`.
- **Committed in:** `ca29843a` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical / acceptance-mandated test file)
**Impact on plan:** The added test file is required to satisfy Task 1's own acceptance criteria — no scope creep beyond the smoke coverage the plan called for.

## Issues Encountered
- The credential grep gate (`grep -rc 'OKX_API|secret|passphrase' ... == 0`) initially failed because the fixture's own `_comment` described it as containing "no secrets, passphrases" — the literal substrings `secret`/`passphrase` tripped the gate. Reworded the comment to "no real credentials, API keys, auth tokens, or account IDs" — gate now returns 0.

## User Setup Required
None - no external service configuration required. The opt-in sandbox suite is dormant until a developer sets `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` (demo env) to run it against OKX demo.

## Next Phase Readiness
- The shared offline reconciliation double is ready: plans 05-03 (order/fill reconcile), 05-04 (VenueAccount reconcile), and 05-05 (two-sided restart) write their offline tests against `fake_venue_connector` and extend the recon fixtures.
- The three sandbox skeleton bodies are named to their target plans (`05-03`/`05-04`/`05-05`) — each replaces its `_pending()` skip with the real assertion as the feature lands.
- No blockers. Backtest inertness unaffected (test-only additions); full suite collects 1559 tests.

## Self-Check

- `tests/support/__init__.py` — FOUND
- `tests/support/fake_venue_connector.py` — FOUND
- `tests/support/fixtures/okx_recon_payloads.json` — FOUND
- `tests/e2e/test_okx_sandbox_recon.py` — FOUND
- `tests/unit/connectors/test_fake_venue_connector.py` — FOUND
- Commit `ca29843a` — FOUND
- Commit `af29a99f` — FOUND

## Self-Check: PASSED

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
