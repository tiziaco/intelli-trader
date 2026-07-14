---
phase: 08-error-subsystem
plan: 02
subsystem: error-subsystem
tags: [error-policy, error-handler, tripwire, wr-06, relocation, dispatcher-seam]
requires:
  - "08-01: FailureClass enum, HaltReason +4 tripwire members, FailureRateSettings, okx counted ErrorEvent"
provides:
  - "events_handler/error_policy.py (RELOCATED from trading_system, D-02): ErrorPolicy + HandlerErrorPolicy Protocol + FailFastPolicy + should_trip/classify_failure/_POLICY/record_failure/bind"
  - "events_handler/error_handler.py (NEW, D-01): ErrorHandler.on_error ERROR-route consumer with WR-06 two-guard terminal safety + D-17 last_error persist + FILL_TRANSLATION counting seam"
  - "shared record_failure counter surface (Open-Q#1 resolution): routed-handler seam + off-thread okx ERROR event count into one ErrorPolicy tripwire"
affects:
  - "08-03 wires ErrorPolicy(FailFastPolicy default)/ErrorHandler into compose_engine + build_live_system + EventHandler (new kwargs), binds halt=safety.halt/error_counter, repoints ERROR route"
  - "drift verification must EXCLUDE events_handler/error_policy.py (relocated) + error_handler.py (new) as intentional surface"
tech-stack:
  added: []
  patterns:
    - "AlertSink runtime_checkable Protocol shape reused for HandlerErrorPolicy Protocol"
    - "full_event_handler _on_handler_error bare-raise body reused for FailFastPolicy (oracle-safe)"
    - "EventHandler.routes data-map convention reused for _ROUTE_CLASS / _POLICY_FIELDS literals"
    - "_log_error_event body lifted verbatim (4-space) into ErrorHandler.on_error; WR-06 consumer guard preserved byte-for-byte"
key-files:
  created:
    - itrader/events_handler/error_policy.py
    - itrader/events_handler/error_handler.py
    - tests/unit/events/test_error_policy.py
    - tests/unit/events/test_error_handler.py
  modified:
    - itrader/trading_system/live_runner.py
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_okx_inertness.py
  deleted:
    - itrader/trading_system/error_policy.py
decisions:
  - "failure_settings=None still arms the tripwire — D-14 defaults carried in-module _POLICY_FIELDS so no runtime config import (TYPE_CHECKING edge only)"
  - "on_handler_error counts AFTER the publish (end of method); source guard returns first so a COSMETIC/ERROR-type failure is never counted"
  - "correlation_id stringified in the persisted state.last_error dict for JSON portability; only declared ErrorEvent fields bound (T-05-27)"
  - "record_failure is the single shared counter surface; ErrorHandler.on_error counts the off-thread okx FILL_TRANSLATION event through the same ErrorPolicy (no second breaker object)"
metrics:
  duration: ~40m
  completed: 2026-07-15
status: complete
---

# Phase 8 Plan 02: ERROR-route guards relocated + CF-1 tripwire Summary

Relocated `ErrorPolicy` verbatim beside the dispatcher (D-02), formalized both ERROR-route guards' source/consumer sides, and built the CF-1 aggregate failure-rate tripwire that actually trips on the first settlement failure — resolving RESEARCH Open Question #1 with one shared `record_failure` counter surface that both the routed-handler seam and the off-thread okx ERROR-route consumer call into.

## What Was Built

### Task 1 — Relocate ErrorPolicy + FailFastPolicy + HandlerErrorPolicy Protocol (`events_handler/error_policy.py`, 4-space)
- Moved the entire `ErrorPolicy` body VERBATIM from `trading_system/error_policy.py` to `events_handler/error_policy.py` (D-02); old module `git rm`-deleted. WR-06 source guard (`if getattr(event,'type',None) is EventType.ERROR: return`) and `error_counter` bookkeeping preserved byte-for-byte, including the pre-existing `error_message=str(exc)` handler-failure emit (pre-existing internal-exception behavior, not a new leak).
- Added `HandlerErrorPolicy` (`@runtime_checkable` Protocol, single `on_handler_error(event, handler) -> None: ...`) modelled on the `AlertSink` shape, and `FailFastPolicy` (body = bare `raise`, the oracle-safety-critical backtest arm).
- Repointed 3 importers (path-only, no wiring-logic change): `live_runner.py:49`, `live_trading_system.py:1226`, `test_okx_inertness.py:225` → `from itrader.events_handler.error_policy import ErrorPolicy`.
- Commit: `fa655025`.

### Task 2 — CF-1 tripwire (`error_policy.py`, 4-space, TDD)
- Module-level `should_trip(hits, threshold, window, now)` — pure `collections.deque` sliding-window predicate (append, prune `<= now-window`, `len >= threshold`); `now` injectable, one-way (no auto-reset).
- Module-level `classify_failure(event)` (D-09 Option A): `_ROUTE_CLASS` map FILL→SETTLEMENT, ORDER→ORDER_IO, SIGNAL→ADMISSION, unmapped non-ERROR→LOOP_BACKSTOP; an ERROR-typed event refined by `(source, operation)` → FILL_TRANSLATION only for `("okx_exchange","fill-translation")`, else None (no double-count of already-counted downstream ErrorEvents).
- `ErrorPolicy.__init__` extended: optional `failure_settings` (TYPE_CHECKING `FailureRateSettings`, read duck-typed via getattr) + optional injected `halt`; builds `self._policy` (from `_POLICY_FIELDS` + D-14 defaults carried in-module so `None` settings still arms) and per-class `self._hits` deques (D-11 state-on-ErrorPolicy, no breaker class).
- `bind(*, halt, error_counter)` late-wire (D-12); `record_failure(failure_class, now=None)` shared counter surface calling `self._halt(reason.value)` on trip (None halt = no-op).
- `on_handler_error` counts AFTER the WR-06 source-guard return + publish (`fc = classify_failure(event); if fc is not None: self.record_failure(fc)`).
- Tests: `test_error_policy.py` (23 tests) — FailFastPolicy re-raise, should_trip windowed parametrized math, classify_failure table, record_failure/bind, WR-06 source guard, and `test_settlement_trips_on_first` (CF-1 hard criterion). Commits: `93425531` (RED), `fad0ab61` (GREEN).

### Task 3 — ErrorHandler ERROR-route consumer (`events_handler/error_handler.py`, 4-space, TDD)
- New `ErrorHandler.on_error` lifts the `_log_error_event` body verbatim (re-indented 4-space): severity-mapped log binding only declared ErrorEvent fields, CRITICAL→injected alert-sink, whole body inside the WR-06 consumer guard (inner `try/except: pass` last-resort; never re-raises into `_dispatch`).
- INSIDE the guard: D-17 `state.last_error` persist via injected `system_store.upsert('state.last_error', {scrubbed declared fields}, at=<event.time|now(UTC)>)` (live-only; `correlation_id` stringified; None store = no-op); and the FILL_TRANSLATION counting seam `failure_sink.record_failure(classify_failure(event))` (off-thread okx event → shared ErrorPolicy tripwire).
- `alert_sink` typed by a local relocated `_AlertSinkLike` Protocol; `system_store`/`failure_sink` held as `Any` — no runtime import of `trading_system.alert_sink` or `storage.system_store` (inertness _FORBIDDEN).
- Tests: `test_error_handler.py` (11 tests) — severity map, CRITICAL escalation gating, WR-06 swallow of raising alert_sink/system_store/failure_sink, scrubbed persist + backtest no-op, FILL_TRANSLATION count vs generic-not-counted. Commits: `74565d3d` (RED), `644a710a` (GREEN).

## Deviations from Plan

**1. [Rule 3 - Blocking] Reworded relocated-module docstring to keep the grep gate empty**
- **Found during:** Task 1
- **Issue:** Hazard #8 requires `grep -rn "trading_system.error_policy" itrader tests` to return nothing; the regex `.` matches `/`, so a docstring reference `trading_system/error_policy.py` tripped it.
- **Fix:** Reworded the relocation docstring to "RELOCATED (D-02) from the `trading_system` package …" (no `trading_system/error_policy` substring). grep now CLEAN.
- **Files modified:** itrader/events_handler/error_policy.py
- **Commit:** fa655025

**2. [Rule 3 - Blocking] Explicit `Any` annotation on classify_failure's event_type**
- **Found during:** Task 2
- **Issue:** `event_type = getattr(event, "type", None)` inferred `Any | None`; `_ROUTE_CLASS.get(event_type, ...)` failed mypy `--strict` (`.get` expects `EventType`).
- **Fix:** Annotated `event_type: Any = getattr(...)` so the dict lookup typechecks (behavior unchanged; None still falls through to LOOP_BACKSTOP).
- **Files modified:** itrader/events_handler/error_policy.py
- **Commit:** fad0ab61

No other deviations — the relocation, tripwire, and consumer match the plan.

## Threat Mitigations Applied
- **T-08-01 (Info Disclosure, state.last_error + alert-sink):** persisted dict binds ONLY declared ErrorEvent fields (correlation_id stringified, severity.value), never `str(exc)`/raw payload; `set(value.keys()) <= declared` asserted. alert_sink/system_store typed via Protocol/Any (no layer edge).
- **T-08-02 (DoS, error→error livelock):** WR-06 two guards preserved byte-for-byte — source guard in ErrorPolicy (no republish/count of ERROR-typed failing event), consumer guard in ErrorHandler (whole body wrapped, inner last-resort pass, never re-raises); tripwire count sits AFTER the source guard.
- **T-08-03 (Tampering, tripwire fails to trip AUD-3):** deterministic `should_trip` + injectable `now`; `test_settlement_trips_on_first` proves SETTLEMENT halt-on-first from a FILL handler failing every event; okx off-thread event counts via `ErrorHandler.on_error → record_failure` (shared surface).
- **T-08-04 (Layering):** DI only — no runtime import of `trading_system.alert_sink` or `storage.system_store`; collaborators injected + typed Any/TYPE_CHECKING.

## Verification
All PYTHONPATH-prefixed (`.venv` editable-install shadow guard):
- `tests/unit/events` — **154 passed** (new test_error_policy.py 23 + test_error_handler.py 11).
- `tests/integration/test_okx_inertness.py` — **4 passed** (relocated ErrorPolicy import repointed; error_policy/error_handler pull nothing forbidden).
- `tests/integration/test_backtest_oracle.py` — **3 passed** (byte-exact vs frozen golden; these modules not yet on the compose path).
- `mypy itrader/events_handler/error_policy.py itrader/events_handler/error_handler.py` — clean (2 files).
- `grep -rn "trading_system.error_policy" itrader tests` — CLEAN (relocation complete).

## Known Stubs
None — both modules are fully implemented; `bind`/`halt`/`system_store`/`failure_sink`/`error_counter` are the intended DI seams 08-03 wires (documented as such, not stubs).

## Self-Check: PASSED
- Created source + test files present on disk; old `trading_system/error_policy.py` deleted.
- All 5 task commits (fa655025, 93425531, fad0ab61, 74565d3d, 644a710a) present in git history.
- STATE.md / ROADMAP.md NOT modified (orchestrator owns those).
