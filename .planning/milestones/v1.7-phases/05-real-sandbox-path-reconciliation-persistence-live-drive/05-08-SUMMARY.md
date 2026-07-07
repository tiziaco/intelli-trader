---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 08
subsystem: resilience
tags: [reconnect, backoff, failure-classification, pause-on-disconnect, halt, RES-01, D-19, D-20]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 04
    provides: "LiveTradingSystem.halt(reason) freeze-in-place entrypoint (HALTED + halt_reason + CRITICAL alert) + _dispatch_live submission gate"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 05
    provides: "Hardened, idempotent OkxExchange fill/stream surface (_stream_fills/_stream_orders + _handle_trade dedup) the supervisor wraps"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 07
    provides: "VenueReconciler / restart reconcile path + VenueAccount.snapshot() the resume-after-reconnect reuses"
provides:
  - "Bounded-retry reconnect supervisor around EVERY venue stream consume-loop (fills/orders/candles): transient -> exponential backoff after a debounce (stay running), fatal or ceiling-exhausted -> HALTED + CRITICAL alert (reason='connector-fatal') — a socket drop reconnects instead of the task dying silently (RES-01/D-20)"
  - "ccxt failure classification (NetworkError/RequestTimeout/DDoSProtection transient; AuthenticationError/PermissionDenied fatal) + secret-scrubbed escalation (log type only, fixed halt reason — no exception text reaches the alert)"
  - "Reversible pause-on-disconnect (D-19): a sustained venue-stream disconnect pauses NEW order submission (positions/orders untouched), a reconnect + a fresh REST snapshot/reconcile resumes it; a sub-second blip does not pause. Engine-thread resume drain (Pitfall 9-safe); paused state surfaced distinctly on get_status()"
  - "Injected supervisor seams on both stream arms: set_halt_signal + set_stream_state_listener, wired at the OKX composition root"
affects: [resilience, live-drive, OkxExchange, OkxDataProvider, LiveTradingSystem]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reconnect supervisor wraps the OUTER consume-loop, preserving the existing per-item skip-and-log INSIDE and the async-with session teardown; asyncio.CancelledError is re-raised (cooperative cancel, Pitfall 4)"
    - "Debounce-then-pause: the pause fires only on the SECOND consecutive failure (past the debounce sleep), so a blip that recovers on the first retry never pauses (D-19). _on_stream_healthy (first successful watch/subscribe) resets backoff and fires resume on the down->up transition"
    - "Connector-loop callbacks only flip thread-safe flags (pause / request-resume); all blocking venue I/O (the fresh REST snapshot on resume) runs on the ENGINE thread via _maybe_resume_after_reconnect (Pitfall 9 — never connector.call on the loop that is running the callback)"
    - "Secret scrub (T-05-27): the supervisor logs type(exc).__name__ + a fixed cause string (never str(exc)) and halts with the fixed reason 'connector-fatal', so no request context / API secret can reach the CRITICAL ErrorEvent egress"
    - "Per-instance tuning seeded from named module [ASSUMED] constants (debounce 0.25s / backoff base 1s cap 30s / ceiling 6) so a test or a sandbox tune shrinks them without monkeypatching the module"

key-files:
  created:
    - tests/unit/execution/test_reconnect_resilience.py
  modified:
    - itrader/execution_handler/exchanges/okx.py
    - itrader/price_handler/providers/okx_provider.py
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "The supervisor is implemented per-file (TABS okx.py / 4-space okx_provider.py) rather than a shared helper: the plan frames the two as parallel implementations, the grep gates tie backoff+AuthenticationError to okx.py specifically, and a shared connectors.* module would drag the ccxt.pro-pulling connectors barrel into the import graph. The tuning constants are documented [ASSUMED] in both."
  - "Pause fires on the SECOND consecutive transient (attempt > 1, past the debounce sleep), not the first — this gives clean, deterministic blip-vs-disconnect semantics: a one-transient blip recovers on the first retry and never pauses; a sustained drop reaches attempt 2 and pauses (D-19)."
  - "Resume is engine-thread-only. The connector-loop reconnect callback (_on_venue_stream_up) merely SETS threading.Event; _maybe_resume_after_reconnect (drained in the event loop's dispatch + idle branches) takes the fresh VenueAccount.snapshot() then clears the pause. A connector.call on the connector loop would deadlock (Pitfall 9); a failed snapshot re-sets the flag and stays paused (never resume blind)."
  - "pause-on-disconnect is a REVERSIBLE state distinct from the terminal HALT: _dispatch_live suppresses SIGNAL/ORDER on either, but get_status surfaces `paused`/`paused_reason` separately from `status`/`halt_reason`, and a terminal halt supersedes a pause (pause_submission is a no-op while HALTED)."
  - "The candle stream's clean return (server-closed socket) is treated as a reconnect trigger, not a terminal stop — a stream is not supposed to end on its own; aiohttp.ClientError/ConnectionError/asyncio.TimeoutError join the ccxt transient set for the native aiohttp socket."

requirements-completed: [RES-01]

# Metrics
duration: ~40min
completed: 2026-07-02
---

# Phase 5 Plan 08: Live Resilience — Reconnect Supervisor + Pause-on-Disconnect Summary

**Wrapped every venue stream consume-loop (fills/orders/candles — which had NO reconnect today, a code-verified gap) in a bounded-retry reconnect supervisor: a transient socket drop reconnects with exponential backoff after a debounce (staying running, publish-and-continue), a fatal connector error or an exhausted retry ceiling halts the engine (HALTED + secret-scrubbed CRITICAL alert, reason='connector-fatal'), and a sustained disconnect pauses NEW order submission — resuming only after reconnect + a fresh engine-thread REST snapshot/reconcile, while a sub-second blip never pauses (RES-01/D-19/D-20).**

## Performance
- **Duration:** ~40 min
- **Completed:** 2026-07-02
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- **Task 1 — reconnect supervisor + failure classification (D-20).** Refactored `OkxExchange._stream_fills`/`_stream_orders` (TABS) into supervisor + `_consume_*` forever-loops, and `OkxDataProvider._stream_candles` (4-space) into a supervisor + `_connect_and_consume_candles` connection body. `_run_stream_supervisor` classifies each caught error: transient (`ccxt.NetworkError`/`RequestTimeout`/`DDoSProtection`; plus `aiohttp.ClientError`/`ConnectionError`/`asyncio.TimeoutError` for the native candle socket) → exponential backoff (cap) after a debounce, staying running; fatal (`ccxt.AuthenticationError`/`PermissionDenied`) OR the retry ceiling exhausted → `_escalate_connector_halt` → the injected halt signal (`connector-fatal`). The per-item skip-and-log stays INSIDE the loop and the candle `async with` teardown survives the wrapper; `asyncio.CancelledError` is re-raised (clean cancel, Pitfall 4). Secret scrub (T-05-27): log `type(exc).__name__` only, halt with a fixed reason — no exception text reaches the alert. No custom rate-limit bucket (ccxt `enableRateLimit=True` already on, RES-01).
- **Task 2 — pause-on-disconnect / resume-after-reconcile (D-19).** `LiveTradingSystem.pause_submission`/`resume_submission` are a REVERSIBLE quiesce of NEW order submission (distinct from the terminal HALT); `_dispatch_live` now suppresses SIGNAL/ORDER while HALTED **or** paused. `_on_venue_stream_down` (connector-loop callback) pauses; `_on_venue_stream_up` only FLAGS a resume; `_maybe_resume_after_reconnect` runs on the ENGINE thread (drained in the event loop's dispatch + idle branches), takes a fresh `VenueAccount.snapshot()` then clears the pause (Pitfall 9 — no blocking venue I/O on the connector loop). `get_status()` surfaces `paused`/`paused_reason` distinctly. The composition root wires `set_halt_signal(self.halt)` + `set_stream_state_listener(...)` on both OKX stream arms.

## Task Commits
1. **Task 1: reconnect supervisor + failure classification on the stream loops (D-20)** — `8ee71db9` (feat)
2. **Task 2: pause-on-disconnect / resume-after-reconcile (D-19)** — `018192ab` (feat)

## Files Created/Modified
- `itrader/execution_handler/exchanges/okx.py` (TABS) — `import asyncio` + `Awaitable`/`Callable`; four named `_STREAM_RECONNECT_*` module constants; reconnect-supervisor instance state + per-instance tuning; `set_halt_signal`/`set_stream_state_listener`; `_run_stream_supervisor`/`_escalate_connector_halt`/`_mark_stream_down`/`_on_stream_healthy`; `_stream_fills`/`_stream_orders` → supervisor + `_consume_fills`/`_consume_orders`. `grep backoff` = 16, `grep AuthenticationError` = 2; 0 pure-4-space lines introduced (stays TAB).
- `itrader/price_handler/providers/okx_provider.py` (4-space) — `import asyncio` + `Awaitable`; mirrored `_STREAM_RECONNECT_*` constants + supervisor state; `set_halt_signal`/`set_stream_state_listener`; `_run_stream_supervisor` (clean-return = reconnect; aiohttp transient set)/`_escalate_connector_halt`/`_mark_stream_down`/`_on_stream_healthy`; `_stream_candles` → supervisor + `_connect_and_consume_candles`. `grep backoff` = 16.
- `itrader/trading_system/live_trading_system.py` (4-space, mypy-deferred) — reversible pause state (`_submission_paused`/`_paused_reason`/`_pending_stream_resume`); `pause_submission`/`resume_submission`/`_is_submission_paused`/`_on_venue_stream_down`/`_on_venue_stream_up`/`_maybe_resume_after_reconnect`; `_dispatch_live` HALTED-or-paused gate; `get_status` paused fields; event-loop resume drain (dispatch + idle); composition-root supervisor-seam wiring on both OKX arms. `grep paused-on-disconnect` = 6.
- `tests/unit/execution/test_reconnect_resilience.py` (created, 12 tests) — Task 1: transient→reconnect+survive (both arms), fatal→HALTED (both arms), retry-ceiling→HALTED (both arms), no-secret-in-CRITICAL-alert. Task 2: blip→no-pause, pause suppresses new submission (BAR/FILL continue), get_status paused distinct, reconnect+snapshot→resume, pause no-op while HALTED. Scripted consume driven on a per-test `asyncio.run` loop (clean teardown under `filterwarnings=["error"]`).

## Decisions Made
See frontmatter `key-decisions`. Load-bearing: per-file supervisor (not a shared connectors.* helper that would drag the ccxt.pro barrel into the graph); pause on the SECOND consecutive transient (deterministic blip-vs-disconnect); engine-thread-only resume via a flag (Pitfall 9 deadlock avoidance); reversible pause distinct from terminal HALT; candle clean-return treated as reconnect.

## Deviations from Plan
None — plan executed as written. Both auto-fix rules were not required; the only in-flight design refinement (candle clean-return handled as a reconnect, plus aiohttp transient classes added for the native socket) is a correctness completion of the plan's "wrap the consume-loop" instruction, folded into the Task-1 commit, not a behavioral deviation from the plan.

## Verification Results
- `poetry run pytest tests/unit/execution/test_reconnect_resilience.py -x` → **12 passed** (transient→reconnect, fatal→HALTED, ceiling→HALTED, no-secret, blip→no-pause, pause/resume, get_status distinct).
- `poetry run pytest tests/integration/test_okx_inertness.py -x` → **1 passed** (backtest import path pulls no OKX/async/ccxt — the supervisor lives in the lazy okx arm).
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → **3 passed** (byte-exact: 134 / 46189.87730727451 — resilience off the backtest path).
- `poetry run pytest tests/unit/execution/test_drift_halt_policy.py tests/integration/test_live_system_okx_wiring.py` → **20 passed** (the `_dispatch_live` + `get_status` + composition-root changes regress nothing).
- `poetry run pytest tests/unit/execution tests/unit/price tests/unit/portfolio` → **581 passed** (no regressions).
- `poetry run mypy --strict itrader/execution_handler/exchanges/okx.py itrader/price_handler/providers/okx_provider.py itrader/trading_system/live_trading_system.py` → **Success: no issues found in 3 source files**.
- No ResourceWarning/RuntimeWarning under `filterwarnings=["error"]` (per-test `asyncio.run` loops close cleanly).
- Acceptance greps: `backoff` okx.py = 16 / okx_provider.py = 16 (≥1); `AuthenticationError` okx.py = 2 (≥1); `paused-on-disconnect` live_trading_system.py = 6 (≥1); okx.py introduces 0 pure-4-space lines (stays TAB-indented).

## Known Stubs
None — no hardcoded/placeholder values or unwired data sources. The supervisor + pause/resume machinery is fully implemented and exercised offline (scripted consume + credential-free `LiveTradingSystem(exchange='binance')`).

## Threat Flags
None beyond the plan's `<threat_model>`. The four registered threats are mitigated as designed: T-05-24 (stream task dies on socket drop) — bounded-retry supervisor around every consume-loop, per-item skip-and-log preserved; T-05-25 (trading blind during a gap) — pause on disconnect, resume only after reconnect + fresh REST reconcile (D-19); T-05-26 (infinite silent retry / auth loop) — fatal or ceiling-exhausted → HALTED + CRITICAL alert, never spin forever (D-20); T-05-27 (secret in a connector-exception alert) — the supervisor logs the exception TYPE only and halts with a fixed reason, so no exception text reaches the egress (unit-asserted). No new network endpoint, auth path, or schema surface at a trust boundary.

## Self-Check
- `itrader/execution_handler/exchanges/okx.py` — FOUND (modified)
- `itrader/price_handler/providers/okx_provider.py` — FOUND (modified)
- `itrader/trading_system/live_trading_system.py` — FOUND (modified)
- `tests/unit/execution/test_reconnect_resilience.py` — FOUND
- Commit `8ee71db9` — FOUND
- Commit `018192ab` — FOUND

## Self-Check: PASSED

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
