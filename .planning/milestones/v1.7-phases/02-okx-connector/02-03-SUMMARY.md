---
phase: 02-okx-connector
plan: 03
subsystem: execution
tags: [ccxt-pro, okx, order-arm, fill-stream, decimal-edge, venue-time, abstract-exchange]

# Dependency graph
requires:
  - phase: 02-okx-connector
    plan: 02
    provides: "OkxConnector session/transport primitive (call/spawn/client/sandbox/connect/disconnect) + async mocked-ccxt conftest — the injected LiveConnector seam this arm drives its venue calls through"
provides:
  - "OkxExchange(AbstractExchange) — the live sibling of SimulatedExchange (order arm): drops into ExecutionHandler.on_order routed by event.exchange; submits/cancels via connector.call, streams orders+fills via connector.spawn, translates raw fills into frozen FillEvents it puts on global_queue itself (D-07)"
  - "The Decimal edge held at the venue boundary (CONN-05): inbound to_money(str(x)); outbound amount_to_precision/price_to_precision (ccxt string helpers) — no Decimal(float)"
  - "Venue-time stamping: FillEvent.time from the venue fill timestamp (ms->UTC datetime), never wall-clock"
affects: [04-paper-path, 05-real-sandbox-recon, execution-composition-root-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "live exchange = AbstractExchange sibling with an INJECTED LiveConnector session (D-04) — never imports the OkxConnector concretion; grep-guarded"
    - "fill correlation: venue-order-id <-> OrderEvent map so a streamed watch_my_trades fill resolves to its originating order (FillEvent.new_fill carries the order_id/strategy_id/portfolio_id audit chain)"
    - "the EXCHANGE emits FillEvents (D-07); the connector emits nothing — put() may fire from the connector asyncio thread (queue.Queue MPSC-safe, D-19 single-writer preserved)"
    - "input validation at the venue boundary: fills for unknown orders / missing price|amount|timestamp are skipped-and-logged, never crashed (T-02-03-VALID)"

key-files:
  created:
    - itrader/execution_handler/exchanges/okx.py
    - tests/unit/execution/test_okx_exchange.py
  modified: []

key-decisions:
  - "watch_my_trades yields ccxt-UNIFIED trades (price/amount/fee.cost/timestamp/order), not the raw OKX socket shape — _handle_trade consumes the unified dict; the recorded raw fixture is mapped into a unified trade in the test (reuse without coupling to raw field names)"
  - "connect() spawns the two watch_* consume-loops via connector.spawn and marks connected; the connector owns loop/task-cancellation lifecycle (its disconnect cancels-all) — the exchange.disconnect only flips state"
  - "docstring token hygiene (mirrors 02-02): the Task-1 verify grep-guard scans the FULL source, so the D-04/venue-time discipline paragraphs were worded to avoid the literal tokens watch_fills / datetime.now / OkxConnector while stating the same rule"

requirements-completed: [CONN-02, CONN-05]

# Metrics
duration: 9min
completed: 2026-07-01
---

# Phase 2 Plan 03: OKX Order Arm (OkxExchange) Summary

**`OkxExchange` — the live sibling of `SimulatedExchange`: an `AbstractExchange` that drops into the same `ExecutionHandler.on_order` seam, submits/cancels orders through the injected `OkxConnector` session (`connector.call`), streams venue orders + fills (`connector.spawn` on `watch_orders` / `watch_my_trades` — the fill stream), and translates each raw fill into a frozen `FillEvent` it puts on `global_queue` itself (D-07) — holding the Decimal edge (`to_money(str(x))` inbound, ccxt `amount_to_precision`/`price_to_precision` strings outbound) and venue-time stamping throughout.**

## Performance
- **Duration:** ~9 min
- **Tasks:** 2 (both `type=auto`)
- **Files modified:** 2 (2 created, 0 modified)

## Accomplishments
- Built `itrader/execution_handler/exchanges/okx.py::OkxExchange` (TABS) — implements the full `AbstractExchange` surface (`on_order`, `on_market_data`, `connect`/`disconnect`, `is_connected`, `health_check`, `configure`, `validate_order`, `validate_symbol`) and is `isinstance`-checkable against the runtime-checkable Protocol.
- **Order I/O (D-06):** `on_order` routes NEW → `_submit_order` (rounds outbound qty/price via `client.amount_to_precision`/`price_to_precision`, submits `create_order` through `connector.call`) and CANCEL → `_cancel_order` (resolves the correlated venue id, routes `cancel_order` through `connector.call`). Matching is the venue's job — nothing fills here.
- **Fill emission (D-07):** `_stream_fills` consumes `watch_my_trades` and calls `_handle_trade` per trade; `_handle_trade` builds `FillEvent.new_fill('EXECUTED', order, ...)` and puts it on `global_queue`. A small venue-id↔`OrderEvent` correlation map resolves a streamed fill back to its originating order so the fill carries the `order_id`/`strategy_id`/`portfolio_id` audit chain. `_stream_orders` consumes `watch_orders` for status reconciliation (status only — never mints money). Both are launched via `connector.spawn` in `connect()`.
- **`on_market_data` is a no-op for live** (CONTEXT §Reusable Assets — the venue matches, not us); proven by an empty-queue test.
- **Decimal edge (CONN-05):** every inbound venue float crosses `to_money(str(x))`; outbound uses the ccxt string precision helpers; no `Decimal(<venue float>)`. **Venue time:** `FillEvent.time` stamped from the venue ms timestamp via `_ms_to_dt` (`datetime.fromtimestamp(ms/1000, tz=UTC)`), never wall-clock.
- **D-04 dependency injection:** the arm types against the `LiveConnector` Protocol imported from the top-level `itrader.connectors` barrel — it never imports the `OkxConnector` concretion (grep-guarded, mirrors 02-02's no-domain-import guard).
- Wrote `tests/unit/execution/test_okx_exchange.py` (8 tests): outbound rounding + RPC submit, market-order price omission, raw-fill→FillEvent-on-queue, the `-k decimal` no-float-artifact assertion, unknown/malformed-fill skip guards, `on_market_data` no-op, and cancel routing. Uses a local AsyncMock ccxt client + minimal fake `LiveConnector` (the connectors conftest is directory-scoped); the recorded `okx_order_lifecycle.json` fill is mapped into a unified trade; the private loop is closed in teardown (no ResourceWarning/RuntimeWarning under `filterwarnings=["error"]`).

## Task Commits
1. **Task 1: OkxExchange order arm** — `dc8c8e70` (feat)
2. **Task 2: OkxExchange unit tests** — `72dae958` (test)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified
- `itrader/execution_handler/exchanges/okx.py` (created, TABS) — `OkxExchange(AbstractExchange)`: injected `LiveConnector` session, create/cancel via `call`, `watch_orders`/`watch_my_trades` via `spawn`, `_handle_trade` fill→`FillEvent`-on-queue, Decimal edge + venue-time, no-op `on_market_data`.
- `tests/unit/execution/test_okx_exchange.py` (created, 4-space) — 8 tests proving order-arm rounding, fill translation/emission, the Decimal edge, and the no-op market-data path offline.

## Decisions Made
- **Unified trade shape for the fill stream:** ccxt's `watch_my_trades` returns UNIFIED trades (`price`/`amount`/`fee.cost`/`timestamp`/`order`), not the raw OKX socket envelope. `_handle_trade` consumes the unified dict; the test maps the recorded raw fixture (`fillPx`/`fillSz`/`fee`/`ts`/`ordId`) into a unified trade so it reuses the fixture data without coupling the implementation to raw field names.
- **`connect()` spawns the streams; the connector owns cancellation:** `connect()` launches the two `watch_*` consume-loops via `connector.spawn` and records the handles; task cancellation is the connector's `disconnect` responsibility (it cancels-all + `gather`s, 02-02), so `OkxExchange.disconnect` only flips connection state.
- **Docstring token hygiene (mirrors 02-02):** the Task-1 verify grep-guard scans the full module source, so the discipline paragraphs avoid the literal tokens `watch_fills` / `datetime.now` / `OkxConnector` while stating the same rules.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded docstrings to avoid grep-guarded literal tokens**
- **Found during:** Task 1 (first verify run)
- **Issue:** The Task-1 automated verify greps the entire module source (docstrings included) for absence of `watch_fills`, `datetime.now`, and `OkxConnector`. The initial docstrings used those literal strings while explaining the discipline ("there is NO `watch_fills` method", "never `datetime.now`", "never imports the `OkxConnector` concretion"), so the guard failed despite the code being clean.
- **Fix:** Reworded to "the fill stream is the my-trades channel, NOT a fills channel", "never the process wall-clock", and "never imports the connector concretion (types against the Protocol only)" — same meaning, no literal tokens. No behavior change.
- **Files modified:** itrader/execution_handler/exchanges/okx.py
- **Verification:** the Task-1 verify command reads `ok`; `grep -c watch_fills` = 0, `grep -cE 'connectors\.okx|OkxConnector'` = 0, `datetime.now` grep-zero.
- **Committed in:** dc8c8e70 (Task 1)

---

**Total deviations:** 1 auto-fixed (blocking, Rule 3 — identical class of fix to 02-02's docstring-hygiene deviation). No architectural changes, no scope creep. Every must-have and acceptance criterion is honored.

## Milestone Gate
- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` passes within the full suite — the backtest hot path imports no async/connector/order-arm code (`OkxExchange` is additive, off the run path and not yet wired into any composition root).
- **No W1/W2 regression:** no change to any backtest-path module; `OkxExchange` is imported only by the (future) live wiring.
- **Held constraints:** `mypy --strict` clean (217 files); full suite green under `filterwarnings=["error"]` (1483 passed / 1 skipped, no ResourceWarning/RuntimeWarning escalation — Pitfall 4); Decimal end-to-end (`to_money(str(x))` at the venue edge, ccxt precision strings outbound — no float money); business `time` from the venue timestamp (no wall-clock); TAB indentation matched to the `execution_handler/exchanges/` tree.

## Known Stubs
None functionally blocking. `_stream_orders` currently logs order-status updates at debug (status reconciliation of the order mirror is a Phase 5 reconciliation concern, RECON-*); the fill money path (`_stream_fills`/`_handle_trade`) is fully implemented. `configure()` returns `True` (venue credentials/routing live on the connector, D-04 — the arm has no local config today). `validate_symbol` accepts when `client.markets` is not yet a dict. Neither prevents the CONN-02/CONN-05 goal; the arm submits/cancels, streams, and emits fills end-to-end against the injected seam.

## Threat Flags
None. All new surface is covered by the plan's `<threat_model>`: T-02-03-FLOAT (Decimal edge — tested), T-02-03-CLOCK (venue-time — grep-guarded + tested), T-02-03-QUEUE (MPSC put — D-19 preserved), T-02-03-VALID (skip-and-log guards — tested), T-02-03-SC (no new package).

## Verification Evidence
- `poetry run pytest tests/unit/execution/test_okx_exchange.py -x` → 8 passed.
- `poetry run pytest tests/unit/execution/test_okx_exchange.py -k decimal` → 1 passed (no `Decimal(float)` artifact).
- `poetry run pytest tests/unit/execution/test_okx_exchange.py tests/unit/connectors` → 13 passed.
- `poetry run pytest tests` → 1483 passed, 1 skipped (no warning escalation).
- `poetry run mypy` (`--strict`, 217 files) → Success.
- Task-1 verify: TAB count > 0; `watch_my_trades` present, `watch_fills` grep-zero; `datetime.now` grep-zero; `connectors.okx`/`OkxConnector` grep-zero; `amount_to_precision` present; `global_queue.put` present; `isinstance(ex, AbstractExchange)` True.

## Next Phase Readiness
- The order arm is complete against the proven 02-02 connector seam. Phase 4 (paper path) reaches the DoD on the connector **data arm only** (Plans 02-04/02-05) — the order arm is needed by Phase 5 (real/sandbox + reconciliation) alongside the Phase-1 `VenueAccount` and the v1.6 store.
- **Composition-root wiring is NOT done here** (out of plan scope): registering `'okx' -> OkxExchange` in the live `ExecutionHandler.init_exchanges` and calling `OkxExchange.connect()` to spawn the streams is a Phase 4/5 wiring step (PATTERNS §composition-root note). The seam is ready: `ExecutionHandler.on_order` already routes by `event.exchange`.

## Self-Check: PASSED
- FOUND: itrader/execution_handler/exchanges/okx.py
- FOUND: tests/unit/execution/test_okx_exchange.py
- FOUND commit: dc8c8e70 (feat, Task 1)
- FOUND commit: 72dae958 (test, Task 2)

---
*Phase: 02-okx-connector*
*Completed: 2026-07-01*
