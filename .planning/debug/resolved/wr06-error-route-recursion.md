---
slug: wr06-error-route-recursion
status: resolved
resolved: 2026-07-03
resolution: "ERROR route made terminal-safe. Part A (live_trading_system.py::_publish_and_continue) guards `event.type is EventType.ERROR` and returns without republishing; Part B (full_event_handler.py::_log_error_event) wraps body + alert-sink in try/except that logs once and swallows. New RED->GREEN test test_error_route_consumer_failure_does_not_recurse. 106 passed, oracle byte-exact, mypy strict-clean. User confirmed fixed 2026-07-03; backtest fail-fast for non-ERROR events untouched."
trigger: "WR-06 (Phase 5 review) — the live ERROR-route consumer is not self-protected against its own failure, risking an unbounded error→error feedback loop that floods the engine-thread queue."
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
oracle_dark: true
created: 2026-07-03
updated: 2026-07-03
---

# Debug Session: wr06-error-route-recursion

## Trigger

WR-06 (Phase 5 review) — the live ERROR-route consumer is not self-protected against its
own failure, risking an unbounded error→error feedback loop that floods the engine-thread
queue. Live-only (backtest is fail-fast and never publishes ErrorEvents); the frozen
SMA_MACD backtest MUST stay byte-exact.

## Symptoms

- **Expected behavior:** A failure *while handling an ErrorEvent* (bad field read or a raising
  alert sink) is logged exactly ONCE and is terminal — never re-dispatched, never re-queued.
- **Actual behavior (suspected):** In live mode, `_dispatch` catches the consumer's exception
  and calls `_on_handler_error` = `_publish_and_continue`, which enqueues a NEW `ErrorEvent`
  routed back to the same failing consumer → unbounded error→error loop flooding the
  engine-thread queue.
- **Error messages:** none reported yet; failure mode is a runtime queue flood, not a crash.
- **Timeline:** surfaced in the Phase 5 review (WR-06); live path only.
- **Reproduction:** feed a CRITICAL/plain `ErrorEvent` through `process_events()` with an alert
  sink whose `.alert()` raises (or a field read that raises), under the live
  `_publish_and_continue` error seam.

## Mechanism (symbol-anchored — line numbers rot)

- `itrader/events_handler/full_event_handler.py :: _dispatch` wraps each handler call in
  try/except and routes any exception through `_on_handler_error` (D-16 policy seam).
- Live override:
  `itrader/trading_system/live_trading_system.py :: _publish_and_continue` puts a NEW
  `ErrorEvent` on `global_queue` (consumed by the ERROR route) and keeps draining. It builds
  the ErrorEvent WITHOUT `correlation_id` and WITHOUT `details`.
- ERROR-route consumer `_log_error_event` (full_event_handler.py) unconditionally reads
  `event.correlation_id` and `event.details`; for CRITICAL calls `self._alert_sink.alert(event)`.
- Bug: if ANY read in `_log_error_event` OR the alert-sink call raises, `_dispatch` catches it
  and calls `_on_handler_error` = `_publish_and_continue` AGAIN → another ErrorEvent → routed
  back to `_log_error_event` → unbounded error→error loop.

## Root fix direction (design, don't just patch)

Make the ERROR route terminal-safe. Two parts, apply both if they read cleanly:
- **(A)** Break the recursion at the source: when the FAILING event is itself an `ErrorEvent`,
  `_publish_and_continue` must NOT publish another ErrorEvent — log once and return.
- **(B)** Harden the consumer: wrap `_log_error_event`'s body AND the `_alert_sink.alert()` call
  so a malformed ErrorEvent / a sink that raises is logged once and swallowed, never re-raised
  into `_dispatch`.

Do NOT change the backtest fail-fast policy (base `_on_handler_error` re-raise) for non-ERROR
events — the fix is localized to the ERROR route / the live publish seam.

## Constraints

- Indentation per file: `full_event_handler.py` = TABS; `live_trading_system.py` = 4 SPACES.
  Never normalize.
- No money in this path; no Decimal changes.
- Test strictness: `filterwarnings=["error"]`, `--strict-markers` — every marker declared; no
  new markers.
- Backtest byte-exact: this touches the shared ERROR consumer — verify
  `tests/integration/test_backtest_oracle.py` stays byte-exact.

## Verification (report ACTUAL output; use `poetry run pytest`, NOT `make test`)

- New error→error-recursion test — RED before, GREEN after.
- `tests/unit/events/` (full) + `tests/unit/execution/test_reconnect_resilience.py` (full).
- `tests/integration/test_backtest_oracle.py` (byte-exact).
- `poetry run mypy itrader` (strict-clean).

## Current Focus

reasoning_checkpoint:
  hypothesis: "The ERROR route is not terminal-safe. A failure WHILE consuming an ErrorEvent
    (a raising alert sink on a CRITICAL event, a broken logger/structlog processor, or a
    malformed field) propagates out of _log_error_event into _dispatch, which (live) calls
    _on_handler_error = _publish_and_continue, which puts a FRESH ErrorEvent on global_queue
    routed straight back to _log_error_event. When the failure is deterministic on the
    re-consumed event (logger raises / field read raises), this is an unbounded error->error
    livelock draining the engine-thread queue forever inside a single process_events() call."
  confirming_evidence:
    - "full_event_handler.py::_dispatch (L140-144) wraps every handler in try/except and
      routes ANY exception through _on_handler_error — including a failure of the ERROR
      route's own consumer _log_error_event."
    - "live_trading_system.py::_publish_and_continue (L511-521) unconditionally puts a new
      ErrorEvent on global_queue with NO guard on event.type — it republishes even when the
      failing event was itself an ErrorEvent."
    - "process_events() (L119-124) loops on get_nowait() until Empty, so a republished
      ErrorEvent is consumed within the SAME drain — the loop never terminates when the
      consumer fails deterministically."
    - "_log_error_event (L163-195) has NO try/except: log_method(...) (structlog) and
      _alert_sink.alert(event) both run unguarded; either raising escapes into _dispatch."
  falsification_test: "Feed a CRITICAL ErrorEvent through process_events() with the live
    _publish_and_continue seam bound and an alert sink whose .alert() raises. If NO fresh
    ErrorEvent is put on the queue after the original, the recursion hypothesis is wrong."
  fix_rationale: "Part A (source): _publish_and_continue returns without republishing when the
    failing event.type is EventType.ERROR — breaks the loop at the seam regardless of the
    consumer's failure mode. Part B (consumer): wrap _log_error_event's body + alert-sink call
    in try/except that logs once (best-effort, inner swallow) and never re-raises — the ERROR
    route can never reach _on_handler_error. Both address the root cause (recursion), not a
    symptom. Backtest fail-fast for non-ERROR events is untouched."
  blind_spots: "The alert-sink-raise-on-CRITICAL case alone is BOUNDED under current code (the
    republished event is severity=ERROR and skips the sink, so it self-terminates after one
    spurious extra event) — the genuinely UNBOUNDED path needs a failure that repeats on the
    ERROR-severity republished event (logger raises / unconditional field read). The RED test
    uses the bounded sink-raise case (safe, won't hang) but asserts the republish does not
    happen, which is the exact invariant both parts enforce."
- next_action: "RESOLVED — user confirmed the ERROR-route recursion fix 2026-07-03 ('confirmed —
  commit'). Session archived; fix + test + archived record committed (no push)."

- RED confirmed then GREEN: added test_error_route_consumer_failure_does_not_recurse. Under buggy
  code the logs showed the republish ('Handler EventHandler._log_error_event failed on
  EventType.ERROR' -> a second 'Error event consumed'), republished list had 1 item -> FAIL.
  After Part A + B -> republished == [], sink.calls == 1, queue drained -> PASS.

## Evidence

- timestamp: 2026-07-03
  checked: "STEP 1 — ErrorEvent field defaults in events_handler/events/error.py (L49-52)"
  found: "operation, correlation_id, severity, details ALL have defaults (None / ErrorSeverity.ERROR).
    A _publish_and_continue-built ErrorEvent (which omits correlation_id and details) therefore
    does NOT crash _log_error_event's direct reads — correlation_id reads None, details is None
    so the `if event.details is not None` guard skips it, portfolio_id via getattr(...,None)."
  implication: "The SPECIFIC direct-field-read recursion in the brief is NOT reachable with
    current defaults. The trigger was over-stated for that exact path. The recursion-on-ANY-
    failure risk (raising alert sink, broken logger, future required field) still stands —
    confirmed via the code paths below."

- timestamp: 2026-07-03
  checked: "full_event_handler.py _dispatch / _log_error_event and live _publish_and_continue"
  found: "_dispatch routes ANY handler exception (incl. _log_error_event's own) to
    _on_handler_error. Live binds _on_handler_error = _publish_and_continue (L1071), which puts
    a fresh ErrorEvent with NO event.type guard. _log_error_event has no try/except around
    log_method() or _alert_sink.alert(). process_events() drains in a single get_nowait loop."
  implication: "Reachable failure paths: (1) CRITICAL event + raising alert sink -> republish
    ERROR event (BOUNDED, 1 spurious event, masks the halt); (2) logger/structlog processor
    raises OR an unconditional field read raises -> EVERY ErrorEvent fails identically ->
    _publish_and_continue republishes forever -> UNBOUNDED livelock inside one process_events()."

## Eliminated

- hypothesis: "The direct reads `event.correlation_id` / `event.details` in _log_error_event
    crash on a _publish_and_continue-built ErrorEvent, triggering the recursion."
  evidence: "error.py L50/L52 default both to None; the details read is None-guarded and
    correlation_id=None logs fine. No crash on that path. (STEP 1)"
  timestamp: 2026-07-03

## Resolution

root_cause: "The live ERROR route is not terminal-safe. A failure while CONSUMING an ErrorEvent
  (raising alert sink on CRITICAL, or any logger/field failure) escapes _log_error_event into
  _dispatch, whose live policy _publish_and_continue republishes a fresh ErrorEvent with no
  event.type guard — routed straight back to the same failing consumer. When the failure repeats
  on the re-consumed event this is an unbounded error->error livelock draining the engine-thread
  queue forever within a single process_events() call."
fix: "Two localized parts making the ERROR route terminal-safe (backtest fail-fast for non-ERROR
  events untouched). Part A (source) — live_trading_system.py::_publish_and_continue: after the
  single log + stats increment, guard `if getattr(event, 'type', None) is EventType.ERROR: return`
  BEFORE republishing, so a failing ErrorEvent never spawns a fresh ErrorEvent. Part B (consumer) —
  full_event_handler.py::_log_error_event: wrap the whole body (log_method call + alert-sink call)
  in try/except that logs once (best-effort, with an inner try/except: pass around the recovery
  log so a broken logger can't re-raise either) and swallows — the consumer never re-raises into
  _dispatch/_on_handler_error. Defense-in-depth: either part alone breaks the loop; together the
  recursion is impossible."
verification: "poetry run pytest (NOT make test — make disables logs and breaks caplog asserts):
  new test_error_route_consumer_failure_does_not_recurse RED before / GREEN after; full
  tests/unit/events/ + tests/unit/execution/test_reconnect_resilience.py + backtest oracle =
  106 passed (oracle byte-exact: test_oracle_behavioral_identity + test_oracle_numeric_values
  green). poetry run mypy itrader: Success, no issues in 226 files."
files_changed:
  - "itrader/trading_system/live_trading_system.py (Part A: _publish_and_continue ErrorEvent guard)"
  - "itrader/events_handler/full_event_handler.py (Part B: _log_error_event try/except swallow)"
  - "tests/unit/execution/test_reconnect_resilience.py (RED->GREEN recursion test + imports)"
user_confirmation: "2026-07-03 — user relayed 'CONFIRMED — commit' via main context after
  reviewing root cause + Part A/Part B fix + verification results."
