---
phase: 08-error-subsystem
reviewed: 2026-07-15T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/safety.py
  - itrader/core/enums/__init__.py
  - itrader/core/enums/system.py
  - itrader/events_handler/error_handler.py
  - itrader/events_handler/error_policy.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_runner.py
  - itrader/trading_system/live_trading_system.py
  - tests/support/replay_harness.py
  - tests/unit/events/test_error_policy.py
  - tests/unit/events/test_error_handler.py
  - tests/unit/events/test_error_flow.py
  - tests/unit/execution/test_drift_halt_policy.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/config/test_safety_config.py
  - tests/unit/core/test_failure_class.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-07-15
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Phase 8 formalizes the live ERROR-route: the constructor-injected `HandlerErrorPolicy`
seam (backtest `FailFastPolicy` / live `ErrorPolicy`), the CF-1 aggregate failure-rate
tripwire, and the `ErrorHandler` consumer. I traced each of the seven load-bearing
invariants called out for the phase end-to-end against both the implementation and the
tests. **All seven invariants are implemented correctly.** No correctness, security, or
data-loss defects were found. The findings below are low-severity robustness/observability
notes, not blockers.

### Invariants verified intact (evidence)

1. **WR-06 two-guard terminal safety** — SOURCE guard: `ErrorPolicy.on_handler_error`
   returns at `error_policy.py:303-304` for an ERROR-typed failing event, *before* both
   the republish (`:305`) and the tripwire count (`:321-323`). CONSUMER guard:
   `ErrorHandler.on_error` wraps its entire body (log + CRITICAL alert + `state.last_error`
   upsert + `record_failure`) in `try/except` (`error_handler.py:101-173`) with an inner
   last-resort `try/except: pass` (`:166-173`). The tripwire count sits after the source
   guard as required. `test_error_flow.py::test_live_fill_route_failure_trips_halt_and_keeps_draining`
   proves no error→error livelock.

2. **CF-1 tripwire correctness** — `should_trip` (`error_policy.py:100-115`) windowed math
   is off-by-one-clean: `len(hits) >= threshold` trips SETTLEMENT (threshold 1) on the
   first call, ORDER_IO on the 3rd, LOOP_BACKSTOP on the 5th; prune `hits[0] <= now-window`
   drops entries spaced beyond the window. `classify_failure` maps FILL→SETTLEMENT,
   ORDER→ORDER_IO, SIGNAL→ADMISSION, unmapped→LOOP_BACKSTOP, and returns FILL_TRANSLATION
   only for `("okx_exchange","fill-translation")` ERROR events (else `None`, no
   double-count). `record_failure` is a no-op when `_halt` is unbound and passes
   `HaltReason.value` on trip. `_POLICY_FIELDS` field names and HaltReason mappings match
   `FailureRateSettings` exactly.

3. **Inertness / layering** — `error_policy.py` and `error_handler.py` import only
   stdlib + `core/enums` + the events package + logger; neither runtime-imports
   `trading_system.alert_sink` or `storage.system_store`. `compose.py` types the new
   kwargs `Optional[Any]` (no `SystemStore`/`LogAlertSink` concrete at module scope). The
   `SystemStore` import in `build_live_system` stays lazy inside the
   `system_db_backend is not None` gate (`live_trading_system.py:1057-1059`).

4. **Secret scrub (T-05-27)** — both okx FILL_TRANSLATION emits bind `type(exc).__name__`
   + the fixed `_FILL_TRANSLATION_ERROR_MSG` literal, never `str(exc)`/payload
   (`okx.py:692-698, 794-800`). The `state.last_error` persist dict binds only declared
   ErrorEvent fields (`error_handler.py:134-151`). Verified via the diff that these are the
   sole okx.py changes.

5. **Oracle safety** — `FailFastPolicy.on_handler_error` is a bare `raise`
   (`error_policy.py:164-166`) invoked from `_dispatch`'s `except Exception` block
   (`full_event_handler.py:150-158`); bare-raise re-raises the active exception identically.
   `_dispatch` control flow is otherwise unchanged. `test_error_policy.py::test_failfast_policy_reraises_active_exception`
   pins it.

6. **DI construction-cycle** — `build_live_system` builds `ErrorPolicy` before `compose`
   and late-binds `error_policy.bind(halt=safety.halt, error_counter=...)` after
   SafetyController exists (`live_trading_system.py:1259`). `get_status` reads
   `breaker_snapshot()` None-safely (`:829-831`); a facade built outside `build_live_system`
   has `_error_policy = None` and does not crash.

7. **Replay-harness deviation** — `replay_harness.py:405` sets
   `system.event_handler._error_policy = FailFastPolicy()`; `TestRunner.run` drives
   `event_handler.process_events()` directly, and `_dispatch` reads `self._error_policy`
   at call time, so the override genuinely takes effect (parity gate stays fail-fast).

## Warnings

### WR-01: `breaker_snapshot()` is read cross-thread from `get_status` without synchronization

**File:** `itrader/events_handler/error_policy.py:261-273` (read site: `itrader/trading_system/live_trading_system.py:829-831`)
**Issue:** `ErrorPolicy.breaker_snapshot` reads `self._hits` deque lengths with no lock.
Its docstring justifies this as "the live drain is single-threaded (engine thread)."
That justification covers the *writers* (`record_failure` runs on the engine thread), but
the *reader* does not: `LiveTradingSystem.get_status` is a public status API invoked by
external/web callers on a *different* thread while the engine thread mutates the deques via
`should_trip` (`append`/`popleft`). Under CPython the GIL makes each `len()`/`append`
individually atomic, so this cannot crash or corrupt — but the snapshot can be momentarily
inconsistent, and the "single-threaded" comment understates the actual concurrency (the
`_stats` block right beside it *does* take `self._stats_lock`, so the asymmetry is
conspicuous). This is a robustness/observability note, not a correctness bug.
**Fix:** Either tighten the comment to "writes are single-threaded (engine thread); this is
a best-effort GIL-atomic cross-thread read" so the concurrency is documented accurately, or
snapshot under the same `_stats_lock` the surrounding `get_status` block already holds:
```python
# in get_status(), inside the existing `with self._stats_lock:` block is not enough
# (ErrorPolicy has no lock); simplest is to make the intent explicit:
'breaker': (self._error_policy.breaker_snapshot()
            if self._error_policy is not None else {}),  # best-effort GIL-atomic read
```

## Info

### IN-01: `_error_counter()` is bumped before the WR-06 source-guard early-return

**File:** `itrader/events_handler/error_policy.py:293-304`
**Issue:** In `on_handler_error`, `self._error_counter()` (`:293-294`) runs before the
WR-06 source guard returns for an ERROR-typed failing event (`:303-304`). The guard
correctly suppresses republish and tripwire count, but the facade `errors_count` stat is
still incremented when the *ERROR-route consumer itself* fails. This is defensible (a
consumer failure is genuinely an error) and has no control-flow effect — `errors_count` is
surfaced only in `get_status` statistics — but it means the counter conflates primary
handler failures with ERROR-route consumer failures, which the phase's own WR-06 comments
otherwise treat as a should-be-invisible path.
**Fix:** If a clean "swallowed ERROR-consumer failure is a complete bookkeeping no-op" is
desired, move the `_error_counter()` call below the `EventType.ERROR` guard. Otherwise leave
as-is and note the intended semantics in the comment.

### IN-02: FILL_TRANSLATION ErrorEvent uses wall-clock `time` on the catch-up/consume paths

**File:** `itrader/execution_handler/exchanges/okx.py:693, 795`
**Issue:** The two new FILL_TRANSLATION emits stamp `time=datetime.now(timezone.utc)`
(wall clock), whereas the sibling cancel-failure ErrorEvent uses `time=event.time`
(business time, `okx.py:295`). This `time` flows into `ErrorHandler`'s `state.last_error`
`at=` field. For a *failed* translation there is no reliable business timestamp (the trade
did not translate), so wall clock is defensible for an operational error record — flagging
only because the framework's business-time discipline makes the divergence worth a conscious
sign-off rather than an oversight.
**Fix:** No change required; if desired, add a one-line comment that the error-record `time`
is intentionally wall clock (no business time is recoverable for an untranslatable trade).

### IN-03: `catch_up_missed_fills` leaves `_disconnect_ts_ms` set on the empty-symbols early return

**File:** `itrader/execution_handler/exchanges/okx.py:663-666, 699-700`
**Issue:** `since = self._disconnect_ts_ms` is read, then the method returns early when
`not symbols` (`:665-666`) *before* the `self._disconnect_ts_ms = None` clear at `:700`.
`_on_stream_down_with_floor` only arms the floor when it is `None` (`:760`), so a stale
non-`None` floor from a symbols-empty resume would suppress re-arming on the next
disconnect. Harmless in practice (no active symbols means no orders whose fills could be
missed), and this is pre-existing (Phase-7 D-12) code untouched by the Phase-8 diff — noted
only because `okx.py` is in review scope.
**Fix:** Clear the floor before the early return, or hoist the `not symbols` guard above the
`since` read so the clear path is unconditional:
```python
symbols = sorted(self._active_symbols)
if not symbols:
    self._disconnect_ts_ms = None
    return
```

---

_Reviewed: 2026-07-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
