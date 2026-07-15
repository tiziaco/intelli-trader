# Phase 8: Error Subsystem - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 8-error-subsystem
**Areas discussed:** ErrorHandler shape, Route classification, Breaker→halt wiring, last_error persistence, ErrorPolicy injection shape, Thresholds config vs constants, Breaker halt reasons, FailureClass enum placement

---

## ErrorHandler shape

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone ErrorHandler class | New events_handler/error_handler.py owning severity-log + alert-sink + last_error persist; ERROR route = [error_handler.on_error] | ✓ |
| Keep method on EventHandler | Leave _log_error_event a method; add persist inline | |

| Option | Description | Selected |
|--------|-------------|----------|
| Both guards in events_handler/ | Relocate ErrorPolicy beside the new ErrorHandler + dispatcher | ✓ |
| Keep ErrorPolicy in trading_system/ | Split guards across two packages | |

| Option | Description | Selected |
|--------|-------------|----------|
| Sink built at root, injected into ErrorHandler | ErrorHandler references the sink, calls on CRITICAL; does not own it; EventHandler._alert_sink removed | ✓ |
| ErrorHandler constructs its own sink | Buries the shared egress inside the error path | |

| Option | Description | Selected |
|--------|-------------|----------|
| Build in compose_engine; sink+store as new kwargs | Mirror results_store; None on backtest; one graph | ✓ |
| Build ErrorHandler in each factory, pass in | Two construction sites | |

| Option | Description | Selected |
|--------|-------------|----------|
| Share the existing live SystemStore | Inject the instance build_live_system already builds | ✓ |
| ErrorHandler mints its own from sql_engine | Risks two SystemStore instances over one table | |

**User's choice:** Standalone ErrorHandler in events_handler/; sink owned by composition root and injected; built in compose_engine with alert_sink+system_store as new optional kwargs; share the existing live SystemStore.
**Notes:** User surfaced that the alert-sink is a *general* egress (future Telegram/email for wins/losses/weekly reports), so it must stay owned outside ErrorHandler and reusable by future notifiers — clarified ownership-vs-use. Also clarified the ErrorPolicy (in-loop source seam) vs ErrorHandler (route consumer) distinction, and that typed exceptions feed the ErrorEvent system via the ErrorPolicy converter.

---

## Route classification

| Option | Description | Selected |
|--------|-------------|----------|
| Declarative (EventType, handler-qualname) map | Frozen map keyed on EventType + qualname refinement; unknown → LOOP-BACKSTOP | ✓ |
| EventType-only map | Ignore handler qualname | |
| Handler declares its own class | Distributed route_class attribute per handler | |

| Option | Description | Selected |
|--------|-------------|----------|
| 4 classes; defer FILL-TRANSLATION | Ship ROADMAP's 4; note the venue gap | |
| 5 classes; fix okx.py fill-translation | Also patch okx.py:651 to emit counted ErrorEvent (SETTLEMENT) | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| RouteClass | Ties to routing dict | |
| FailureClass | Category of failure + trip policy; pairs with the vocabulary | ✓ |
| BreakerClass | Named after the breaker | |

**User's choice:** Option A declarative map (EventType-keyed + qualname refinement); 5 classes including FILL-TRANSLATION (patch okx.py); enum named FailureClass.
**Notes:** User asked for plain-language explanation of "route class" + concrete examples per option, and for the 4-vs-5 scope tradeoff. Explained the breaker's purpose (catch a money route failing every event → green run with zero settlements) and that FILL-TRANSLATION is an invisible log-only venue-arm hole before a FillEvent exists.

---

## Breaker→halt wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Pure should_trip() fn + state dict on ErrorPolicy | Injectable now; deterministic ERR-03 test; no new class | ✓ |
| Dedicated FailureRateBreaker object | Standalone record/snapshot; earns keep only if reused | |
| Inline everything in ErrorPolicy | Testable only by driving whole policy | |

| Option | Description | Selected |
|--------|-------------|----------|
| Injected halt callable, called directly | Same-thread idiom; DI-decoupled; synchronous; §3b | ✓ |
| Emit a CONTROL event that routes to halt | Defers halt a dispatch turn; extra machinery | |

**User's choice:** Pure should_trip() function + hit-deque state dict on ErrorPolicy; trip calls an injected halt callable directly.
**Notes:** User challenged whether a CircuitBreaker class was over-engineered — reframed the mechanism as a one-way rate tripwire (not a real open/half-open breaker) and picked the minimal pure-function form. On trip→halt, user weighed decoupling; explained the codebase rule (same-thread → direct call, à la ReconciliationCoordinator; events reserved for cross-thread hand-offs, à la connector ConnectorFatalEvent) and that the injected callable is already DI-decoupled with no import edge.

---

## last_error persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Every ErrorEvent, last-write-wins | state.last_error = most recent error regardless of severity | ✓ |
| Only CRITICAL errors | Cheaper but stale during non-critical floods | |
| Every error, throttled | Premature; path already bounded by the breaker | |

| Option | Description | Selected |
|--------|-------------|----------|
| Single state.last_error key; defer history | One upsert row; logs cover history until FastAPI | ✓ |
| Add the errors-history table now | New migration + store + wiring (~1 plan) | |

**User's choice:** Every ErrorEvent last-write-wins into a single state.last_error key; no errors-history table in P8.
**Notes:** User asked whether an errors-history table would be much work — estimated ~1 plan (HaltRecordStore template + Alembic migration) but recommended deferring: logs already capture every error, P9's read-model needs only last_error, and the table should be designed against the FastAPI query endpoints that read it ("right work, wrong phase").

---

## ErrorPolicy injection shape

| Option | Description | Selected |
|--------|-------------|----------|
| Policy Protocol, always injected | HandlerErrorPolicy Protocol; FailFastPolicy (backtest) / ErrorPolicy (live); delete base _on_handler_error method | ✓ |
| Optional param, method fallback | Keep base method; None on backtest | |

**User's choice:** Policy Protocol always injected; base _on_handler_error method deleted.
**Notes:** —

---

## Thresholds config vs constants

| Option | Description | Selected |
|--------|-------------|----------|
| SafetySettings.<field>: FailureRateSettings | Mirror ThrottleSettings; ROADMAP defaults; P9-tunable | ✓ |
| Module constants in the breaker | Off the config seam | |

| Option | Description | Selected |
|--------|-------------|----------|
| FailureRateSettings | Pairs with FailureClass | ✓ |
| TripwireSettings | Matches the tripwire reframe | |
| ErrorRateSettings | Overlaps Error* vocabulary | |

**User's choice:** FailureRateSettings model on SafetySettings.
**Notes:** User asked for an alternative to the initial "BreakerSettings" name; chose FailureRateSettings.

---

## Breaker halt reasons

| Option | Description | Selected |
|--------|-------------|----------|
| One HaltReason member per FailureClass | SETTLEMENT_FAILURE, ORDER_ROUTE_ERRORS, ADMISSION_ERRORS, LOOP_BACKSTOP; FILL_TRANSLATION reuses SETTLEMENT_FAILURE | ✓ |
| Single ERROR_RATE_BREAKER member | Coarser halt bucket | |

**User's choice:** One typed HaltReason member per FailureClass.
**Notes:** —

---

## FailureClass enum placement

| Option | Description | Selected |
|--------|-------------|----------|
| core/enums/ | The enum convention; import-safe; ExecutionErrorCode precedent | ✓ |
| Local beside the breaker (events_handler/) | Colocated but breaks convention | |

**User's choice:** core/enums/.
**Notes:** —

---

## Claude's Discretion

- Exact `_POLICY` map literal shape and `FailureRateSettings` field representation (tuple vs named fields).
- `FailureClass` in `core/enums/system.py` vs a new `core/enums/error.py`.
- Operation order inside `ErrorPolicy.on_handler_error` (count → trip → publish), preserving the WR-06 source guard + error_counter bookkeeping.
- Exact field-binding for the persisted `state.last_error` dict (secret-scrub: declared ErrorEvent fields only).

## Deferred Ideas

- General notification egress (Telegram/email for wins/losses/weekly reports) via a generalized alert-sink — FastAPI milestone.
- errors-history table (append-only durable log, ~1 plan) — FastAPI milestone, designed against real query endpoints.
- Breaker counters + state.* into the SystemStore stats.snapshot UI read-model — P9 (RTCFG-06).
- Runtime-tunable failure-rate thresholds via ConfigUpdateEvent — P9.
