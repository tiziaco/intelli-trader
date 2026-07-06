---
phase: 06-dynamic-universe-membership
plan: 02
subsystem: infra
tags: [okx, asyncio, websocket, live-data, ccxt, dynamic-subscription]

# Dependency graph
requires:
  - phase: 02-okx-connector
    provides: OkxConnector.spawn/_on_task_done/disconnect cooperative-cancel task lifecycle + OkxDataProvider native confirm-gated candle stream + reconnect supervisor
  - phase: 03-livebarfeed
    provides: LiveBarFeed.warmup (REST replay through update(bar)) that the warmup-before-subscribe contract feeds
provides:
  - "OkxDataProvider.subscribe(symbol)/unsubscribe(symbol) — idempotent dynamic per-symbol candle subscription"
  - "{symbol: asyncio.Task} subscription registry (mechanical socket state, zero membership knowledge)"
  - "Per-symbol supervisor keys (reconnect budget / down-state keyed on the member symbol, not a shared literal)"
  - "Documented warmup-before-subscribe ordering contract for the plan-05 UniverseUpdateEvent consumer"
affects: [06-03, 06-04, 06-05, universe-poll-handler, remove-policy-consumer, live_trading_system-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-symbol supervisor keying: thread the member symbol as stream_name through the whole candle path so N channels never share reconnect/down-state (Pitfall 2)"
    - "Additional-index registry: {symbol: task} is an index over the connector's own _stream_tasks, not a second lifecycle owner (reuse cooperative-cancel teardown)"

key-files:
  created:
    - tests/unit/price/test_okx_dynamic_subscribe.py
    - tests/unit/price/test_warmup_on_add.py
  modified:
    - itrader/price_handler/providers/okx_provider.py
    - tests/unit/connectors/test_okx_data_provider.py

key-decisions:
  - "subscribe passes the member symbol through _stream_candles as the supervisor key; start_stream passes self._symbol so single-symbol wiring behaviour is unchanged"
  - "unsubscribe reuses the connector's cooperative-cancel teardown (async-with closes the socket on CancelledError) — no new teardown code"
  - "No WS rate-limit throttler added (RESEARCH §3: at N=1-2 dynamic symbols the subscribe op is far under any OKX limit; REST warmup is already paced by ccxt enableRateLimit)"
  - "No new snapshot-dedup logic: the confirm='0' snapshot is already dropped by _process_row; warmup-before-subscribe is the documented ordering contract"

patterns-established:
  - "Per-symbol supervisor keys: one symbol's drop no longer marks all streams down; one symbol's payload no longer resets all reconnect budgets"
  - "Registry-as-index: dynamic {symbol: task} map derived from membership events; the provider never decides membership (Arm B data plane)"

requirements-completed: [UNIV-02]

# Metrics
duration: 9min
completed: 2026-07-06
---

# Phase 6 Plan 02: OKX Dynamic Candle Subscribe/Unsubscribe Summary

**Grew `OkxDataProvider` from a single wiring-time symbol to idempotent per-symbol dynamic `subscribe`/`unsubscribe` over a `{symbol: asyncio.Task}` registry, with per-symbol reconnect-supervisor keys replacing the shared `"candles"` literal (D-05, Arm B data plane).**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-06T12:08:00+02:00 (approx)
- **Completed:** 2026-07-06T12:15:52+02:00
- **Tasks:** 2 (both TDD)
- **Files modified:** 4 (1 production, 3 test)

## Accomplishments
- Idempotent `subscribe(symbol)` spawns one supervised `candle{tf}` coroutine on the connector loop and records the task in a `{symbol: asyncio.Task}` registry; a second call for an already-subscribed symbol is a no-op.
- `unsubscribe(symbol)` pops the registry entry and cancels the task once, reusing the connector's existing cooperative-cancel teardown (no new teardown code); an unknown symbol is a safe no-op.
- Per-symbol supervisor keying: `_stream_candles` / `_connect_and_consume_candles` thread the member symbol as `stream_name`, so `_reconnect_attempts` / `_streams_down` / `_on_stream_healthy` / `_reset_reconnect_budget` key per-symbol (Pitfall 2). One symbol's drop no longer marks all streams down; `is_streaming_healthy()` keeps any-symbol-down semantics.
- `confirm='0'` snapshot-on-subscribe stays dropped by `_process_row` with zero new dedup logic; the warmup-before-subscribe ordering contract (Pitfall 6) is documented on `subscribe` for the plan-05 consumer.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: subscribe/unsubscribe + {symbol: task} registry**
   - `821a1af6` (test — RED)
   - `7587f91b` (feat — GREEN)
2. **Task 2: per-symbol supervisor keys + snapshot/warmup contract docs**
   - `43695a54` (test — RED)
   - `3460adcc` (feat — GREEN)

_Task 2's GREEN commit also updated the existing `test_okx_data_provider.py` call sites to the new 3-arg per-symbol signature (required by the signature change)._

## Files Created/Modified
- `itrader/price_handler/providers/okx_provider.py` - Added `self._streams` registry + `subscribe`/`unsubscribe`; threaded the member symbol as the per-symbol supervisor key through `start_stream`, `subscribe`, `_stream_candles`, and `_connect_and_consume_candles` (replacing the two `"candles"` literals); documented the warmup-before-subscribe contract.
- `tests/unit/price/test_okx_dynamic_subscribe.py` - NEW. Recording-connector fake (closes un-started coroutines for strict-suite safety) asserting the six subscribe/unsubscribe behaviours.
- `tests/unit/price/test_warmup_on_add.py` - NEW. Independent per-symbol down-state/budget + any-symbol-down health + a fake-WS stream-path test proving the per-symbol `stream_name` is threaded (not `"candles"`) + confirm='0' snapshot drop.
- `tests/unit/connectors/test_okx_data_provider.py` - Updated `_drive_stream` and the supervisor tests to the 3-arg per-symbol signature and the per-symbol reconnect-budget key.

## Decisions Made
- **Signature threading split across tasks:** Task 1 kept `_stream_candles` at 2 args (registry + subscribe/unsubscribe only) so each commit stayed internally consistent and atomically green; Task 2 threaded the member `symbol` through the whole candle path and replaced the `"candles"` literals. This keeps mypy `--strict` and the test suite green at every commit (the plan's Task-1 action text showed the 3-arg call, but folding the signature change into Task 1 would have broken `start_stream`'s 2-arg call at that commit — see Deviations).
- **No WS throttler, no snapshot-dedup:** matched RESEARCH §2/§3 — the confirm gate + monotonic feed guard already cover the snapshot; the WS subscribe op is far under any OKX limit at this phase's N.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Deferred the `_stream_candles` 3-arg signature from Task 1 to Task 2**
- **Found during:** Task 1 (subscribe/unsubscribe + registry)
- **Issue:** The plan's Task-1 action text called `self._stream_candles(symbol_okx, channel, symbol)` (3 args), but Task 1 does not change the `_stream_candles`/`start_stream` signatures — introducing the 3-arg call in Task 1 would have left `start_stream`'s 2-arg call broken and mypy `--strict` failing at the Task-1 commit boundary.
- **Fix:** Task 1's `subscribe` calls `_stream_candles(symbol_okx, channel)` (2 args, matching the then-current signature). Task 2 threads the member `symbol` through `start_stream`, `subscribe`, `_stream_candles`, and `_connect_and_consume_candles` in one consistent change. Net end-state is identical to the plan's intent (per-symbol key threaded from `subscribe`).
- **Files modified:** itrader/price_handler/providers/okx_provider.py
- **Verification:** Both task commits are green (tests + mypy `--strict`) individually.
- **Committed in:** 7587f91b (Task 1), 3460adcc (Task 2)

**2. [Rule 3 - Blocking] Updated existing `test_okx_data_provider.py` to the 3-arg signature**
- **Found during:** Task 2 (per-symbol supervisor keys)
- **Issue:** The `_stream_candles` / `_connect_and_consume_candles` signature change broke pre-existing supervisor/consume tests that called them with 2 args and asserted `_reconnect_attempts["candles"]`.
- **Fix:** Updated `_drive_stream` and the supervisor tests to pass the member symbol as the third arg and to assert the per-symbol reconnect key (`_reconnect_attempts["BTC-USDT"]`).
- **Files modified:** tests/unit/connectors/test_okx_data_provider.py
- **Verification:** `tests/unit/connectors/test_okx_data_provider.py` 14/14 green; full price+connectors suites 107/107 green.
- **Committed in:** 3460adcc (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 blocking).
**Impact on plan:** Both are mechanical consequences of the signature change; end-state matches the plan's intent. No scope creep.

## Issues Encountered
- The Task-2 direct-helper contract tests (`is_streaming_healthy`, `_reset_reconnect_budget`, `_process_row`) pass on the pre-change code because those helpers were already per-symbol-keyed; the genuine RED gate was the fake-WS stream-path test asserting the 3-arg per-symbol `stream_name` is threaded (fails with `TypeError` on the old 2-arg signature). Resolved by keeping that test as the RED anchor and the others as characterization/contract locks.

## Verification
- `poetry run pytest tests/unit/price/test_okx_dynamic_subscribe.py tests/unit/price/test_warmup_on_add.py -q` → 11 passed
- `poetry run pytest tests/integration/test_okx_inertness.py -x -q` → 1 passed (provider stays off the backtest import path; oracle-dark by construction)
- `poetry run mypy --strict itrader/price_handler/providers/okx_provider.py` → clean
- Acceptance greps met: `def subscribe`/`def unsubscribe`/`self._streams` present; `self._connector.spawn` used inside subscribe; `"candles"` literal returns NO matches in the file; `def _stream_candles` shows the added `symbol` param.
- Broader `tests/unit/price tests/unit/connectors` → 107 passed.

## Known Stubs
None. `subscribe`/`unsubscribe` are fully wired mechanical socket-state methods; the provider carries no membership knowledge by design (D-05) — the poll handler / `UniverseUpdateEvent` consumer that drives them lands in a later plan (06-03/05), which is the documented seam boundary, not a stub.

## Next Phase Readiness
- Plan 05 (composition-root wiring + `UniverseUpdateEvent` consumer) can now drive `provider.subscribe(sym)` / `provider.unsubscribe(sym)` from membership, honouring the documented warmup-before-subscribe ordering.
- `live_trading_system.py` still hardcodes `_OKX_STREAM_SYMBOL` and calls the single-symbol `start_stream()`; un-hardcoding it to iterate `universe.members` (warmup→subscribe per member) is the follow-on wiring plan's job, not this data-plane plan.
- Milestone gate: change is confined to the live-only `OkxDataProvider`; inertness test green, so the SMA_MACD backtest oracle and W1/W2 are unaffected by construction.

## Self-Check: PASSED

All created files exist on disk; all four task commits (`821a1af6`, `7587f91b`, `43695a54`, `3460adcc`) are present in the git history.

---
*Phase: 06-dynamic-universe-membership*
*Completed: 2026-07-06*
