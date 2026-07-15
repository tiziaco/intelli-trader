# Phase 8: Error Subsystem - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The live engine's error-handling spine, formalized. Three deliverables around the
existing event graph (ERR-01..04):

1. **ErrorPolicy injection (ERR-01)** — replace the `_on_handler_error` monkeypatch
   with a constructor-injected handler-error policy; backtest/replay → fail-fast
   re-raise, live → publish-and-continue; per-handler granularity + WR-06 source guard.
2. **CF-1 aggregate failure-rate tripwire (ERR-03)** — a route-classified ring on the
   live publish-and-continue seam that **actually trips** (proven by a "money route
   failing every event" test), preserving the WR-06 terminal swallow.
3. **ErrorHandler consumer (ERR-02) + one error funnel (ERR-04)** — a formalized
   ERROR-route consumer (severity-mapped log, CRITICAL → alert-sink, persist
   `state.last_error`, WR-06 consumer guard); handler failures, `halt()` (CRITICAL),
   `PortfolioErrorEvent`, `ConnectorFatalEvent` all funnel through the one ERROR route.

**Hard invariant across all of it:** the backtest fail-fast path is **byte-for-byte
unchanged**, the SMA_MACD oracle stays byte-exact (`134 / 46189.87730727451`), and
`test_okx_inertness.py` stays green.

**NOT in this phase:** runtime-config mutation of the thresholds (P9/RTCFG), the
SystemStore stats.snapshot UI read-model wiring (P9/RTCFG-06), an errors-history table
(FastAPI milestone), and a general non-error notification egress (FastAPI milestone).

</domain>

<decisions>
## Implementation Decisions

### ErrorHandler shape (ERR-02)
- **D-01:** The ERROR-route consumer becomes a **standalone `ErrorHandler` class** in
  `itrader/events_handler/error_handler.py`. It owns severity-mapped logging + CRITICAL
  alert-sink escalation + `last_error` persistence. `EventHandler` routes
  `EventType.ERROR: [self.error_handler.on_error]`. Replaces the inline
  `EventHandler._log_error_event` method.
- **D-02:** **Relocate `ErrorPolicy`** from `trading_system/error_policy.py` into
  `itrader/events_handler/` so the **two guards of the ERROR route** (source =
  ErrorPolicy, consumer = ErrorHandler) live beside the dispatcher they protect.
- **D-03:** The **alert-sink is owned by the composition root** and **injected** into
  `ErrorHandler` as a collaborator — `ErrorHandler` holds a reference and calls
  `.alert(event)` on CRITICAL only; it does **not** construct or own the sink.
  **Remove `EventHandler._alert_sink`** entirely (the dispatcher must not hold egress
  state). Rationale: the sink is a *general* egress channel (later Telegram/email) whose
  first customer is errors; future non-error notifiers must reach the same instance
  without routing through `ErrorHandler`. See Deferred Ideas.
- **D-04:** `ErrorHandler` is **built inside `compose_engine`** (the single mode-agnostic
  site, next to `EventHandler`). Its live-only collaborators — `alert_sink` and
  `system_store` — become **new optional `compose_engine` kwargs** (mirroring the
  existing `results_store` idiom), built by `build_live_system`, defaulting to `None`.
  `compose_engine` **always** builds an `ErrorHandler`; backtest passes
  `alert_sink=None, system_store=None` → it logs only, never escalates/persists. One
  wiring shape, no dispatcher branch, oracle untouched, SQL-inert.
- **D-05:** `ErrorHandler` **shares the existing live `SystemStore` instance** (the one
  `build_live_system` builds for halt records / P9 stats) — do NOT mint a fresh
  `SystemStore(sql_engine)`. *(Researcher: confirm build_live_system already constructs
  a SystemStore and thread that instance in.)*

### ErrorPolicy injection shape (ERR-01)
- **D-06:** A **`HandlerErrorPolicy` Protocol** (`on_handler_error(event, handler) ->
  None`) is **always injected** into `EventHandler.__init__`. Backtest/replay inject a
  **`FailFastPolicy`** (method body = bare `raise`); live injects the publish-and-continue
  **`ErrorPolicy`**. **Delete the base `EventHandler._on_handler_error` method**;
  `_dispatch`'s except-block calls `self._error_policy.on_handler_error(event, handler)`.
  No monkeypatch; both modes injectable + unit-testable. Oracle stays byte-exact
  (`FailFastPolicy` re-raises identically via bare `raise` from the except-block call).

### CF-1 failure-rate tripwire — classification (ERR-03)
- **D-07:** Reframe: this is a **one-way failure-rate tripwire**, NOT a classic
  open/half-open/auto-recovery circuit breaker (halt is a latched, operator-reset-only
  freeze). Keep the machinery minimal — no state machine, no auto-reset. Docs keep the
  "CF-1 breaker" label for traceability.
- **D-08:** A **`FailureClass` enum** (in `core/enums/`, likely `core/enums/system.py`
  beside `HaltReason` or a new `core/enums/error.py`) with members **SETTLEMENT,
  ORDER_IO, ADMISSION, LOOP_BACKSTOP, FILL_TRANSLATION**.
- **D-09:** Classification via **Option A**: one declarative module-level frozen map
  keyed primarily on `EventType` (FILL→SETTLEMENT, ORDER→ORDER_IO, SIGNAL→ADMISSION),
  with **handler-qualname refinement only where needed**; unknown/unmapped →
  **LOOP_BACKSTOP** default. Mirrors the routing-is-data `_CONTROL_EVENT_TYPES`
  convention.
- **D-10:** **Ship 5 classes, including FILL_TRANSLATION.** Patch `okx.py` (~:651) so the
  venue fill-translation failure emits a **counted `ErrorEvent(source="okx_exchange",
  operation="fill-translation")`** instead of log-only, classified as **FILL_TRANSLATION
  → treated as SETTLEMENT (halt-on-first)**. Closes the invisible "lost venue fill" hole.
  Live-only path (backtest/simulated exchange never exercises it).

### CF-1 failure-rate tripwire — structure & trip (ERR-03)
- **D-11:** **No dedicated breaker class.** A **pure module-level
  `should_trip(hits, threshold, window, now) -> bool`** function does the windowed-count
  math (append `now`, prune outside `window`, return `len >= threshold`); the
  per-`FailureClass` **hit-deque state dict lives on `ErrorPolicy`**. `now` is
  **injectable** so the ERR-03 "prove it trips" test is deterministic. A `_POLICY` map
  holds `(threshold, window, reason)` per `FailureClass`.
- **D-12:** On trip, `ErrorPolicy` calls an **injected `halt: Callable[[str], None]`**
  (handed `safety.halt` at `build_live_system` wiring) **directly and synchronously**.
  Same-thread idiom (matches `ReconciliationCoordinator`); events are reserved for
  cross-thread hand-offs (connector → `ConnectorFatalEvent`). Already decoupled via DI —
  **no `events_handler`→safety import**, no layer inversion. The trip stays observable
  because `halt()` itself emits a CRITICAL `ErrorEvent`.
- **D-13:** Breaker state (per-class counts + last-trip reason/time) surfaces via the
  live facade **`get_status()`** snapshot (§3b). **P8 scope = `get_status()` only**; the
  SystemStore stats read-model is P9 (RTCFG-06).

### Threshold configuration (ERR-03)
- **D-14:** The `(threshold, window)` values live in a **new `FailureRateSettings`**
  Pydantic model added to the existing **`SafetySettings`** (`config/safety.py`),
  mirroring `ThrottleSettings`' sliding-window shape and its "shapes the P9 mutation
  seam" role. Defaults carry the exact ROADMAP values: **SETTLEMENT 1 / halt-on-first,
  ORDER_IO 3/60s, ADMISSION 3/300s, LOOP_BACKSTOP 5/60s** (FILL_TRANSLATION = SETTLEMENT).
  Config home ⇒ runtime-tunable in P9 for free.
- **D-15:** Settings class is named **`FailureRateSettings`** (pairs with `FailureClass`).
  Rejected `BreakerSettings`/`TripwireSettings`/`ErrorRateSettings`.

### Halt reasons (ERR-03/CF-8)
- **D-16:** Add **one typed `HaltReason` member per `FailureClass`** to the existing
  `HaltReason` enum (`core/enums/system.py`): **`SETTLEMENT_FAILURE`,
  `ORDER_ROUTE_ERRORS`, `ADMISSION_ERRORS`, `LOOP_BACKSTOP`**. **FILL_TRANSLATION reuses
  `SETTLEMENT_FAILURE`** (it is a settlement loss). Machine-readable + UI-classifiable —
  consistent with CF-8's typed-HaltReason intent that retired free-string reasons; §3b's
  free strings become enum values.

### last_error persistence (ERR-02)
- **D-17:** Persist **every ErrorEvent, last-write-wins** to a **single
  `state.last_error` key** via `system_store.upsert('state.last_error', {scrubbed
  ErrorEvent fields + timestamp})` — always the most recent error regardless of severity
  (matches ERR-02 "persist latest error" + the RTCFG-06 read-model). Write volume is
  bounded by the tripwire. Runs **live-only** (`system_store=None` → no-op branch on
  backtest) and **inside the WR-06 consumer guard** (a SQL-write failure is swallowed,
  never re-raised into the dispatcher). **No errors-history table** (see Deferred Ideas).

### Claude's Discretion
- Exact `_POLICY` map literal shape and `FailureRateSettings` field types/representation
  (`tuple` vs named fields) — planner's call, provided defaults match D-14.
- Whether `FailureClass` lands in `core/enums/system.py` vs a new `core/enums/error.py`.
- Order of operations inside `ErrorPolicy.on_handler_error` (count → trip → publish)
  provided the WR-06 source guard (don't republish an ErrorEvent that itself failed) and
  the `error_counter` bookkeeping are preserved.
- Exact `ErrorHandler.on_error` field-binding for the persisted dict (secret-scrub
  discipline: only declared ErrorEvent fields).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` — Phase 8: Error Subsystem, Goal + Success Criteria 1–4.
- `.planning/REQUIREMENTS.md` — **ERR-01, ERR-02, ERR-03, ERR-04** (full text).

### The CF-1 breaker spec (authoritative design)
- `.planning/milestones/v1.7-review/v17_audit_results.md` **§3b** — the ERROR-route
  circuit-breaker spec: route-classification table, per-class policies (N/window),
  attach-point, `_stats_lock` mechanics, WR-06 preservation, and the FILL-TRANSLATION
  prerequisite fix (`okx.py:651` log-only → counted ErrorEvent).
- `.planning/codebase/CONCERNS.md` — **AUD-3** (ERROR-route has no aggregate circuit
  breaker — the "green run with zero settlements" failure class) and the ERROR-route
  circuit-breaker untested/unbuilt note.

### Existing code the phase modifies or extends
- `itrader/events_handler/full_event_handler.py` — `_dispatch`, `_on_handler_error`
  seam (to be replaced by injected policy), `_log_error_event` (→ ErrorHandler),
  `_alert_sink` (to be removed), the routes literal.
- `itrader/trading_system/error_policy.py` — the D-07 minimal `ErrorPolicy` (WR-05/WR-06
  body) to be **relocated to `events_handler/`**, formalized, and given the tripwire +
  injected `halt`.
- `itrader/trading_system/alert_sink.py` — `AlertSink` Protocol + `LogAlertSink` (CF-5),
  injected into ErrorHandler.
- `itrader/trading_system/safety/safety_controller.py` — `halt(reason)` (idempotent,
  emits CRITICAL ErrorEvent); its `reason` param becomes `HaltReason`-typed vocabulary.
- `itrader/core/enums/system.py` — `HaltReason` enum (extend with D-16 members);
  candidate home for `FailureClass`.
- `itrader/config/safety.py` — `SafetySettings` / `ThrottleSettings` (template + home for
  `FailureRateSettings`).
- `itrader/storage/system_store.py` — `SystemStore.upsert/get` (`state.last_error`).
- `itrader/trading_system/compose.py` — `compose_engine` (EventHandler build site; add
  `alert_sink`/`system_store` kwargs; build ErrorHandler + policies).
- `itrader/trading_system/live_trading_system.py` — `build_live_system` (wire live
  ErrorPolicy + FailFastPolicy selection + inject `safety.halt`, `LogAlertSink`,
  `SystemStore`); currently monkeypatches at ~:589 and sets `_alert_sink` at ~:1214.
- `itrader/execution_handler/exchanges/okx.py` — ~:651 fill-translation (D-10 counted
  ErrorEvent).
- `itrader/events_handler/events/control.py` — `ConnectorFatalEvent`;
  `itrader/events_handler/events/error.py` — `ErrorEvent` / `PortfolioErrorEvent`
  (msgspec.Struct — copy this shape for any new event).

### Convention guards to honor
- `.planning/codebase/CONVENTIONS.md` — broad-except run-mode policy (backtest fail-fast
  vs live publish-and-continue is intentional), tab/space indentation hazard.
- WR-06 (two-guard terminal safety) — see the source-guard and consumer-guard memories.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`ThrottleSettings` (`config/safety.py`)** — near-exact template for
  `FailureRateSettings`: sliding-window (`max_orders`/`window_s`), Pydantic v2, ON by
  default, explicitly designed to "shape the P9 mutation seam." Add the new model beside
  it under `SafetySettings`.
- **`LogAlertSink` + `AlertSink` Protocol (`trading_system/alert_sink.py`)** — the CF-5
  egress seam already exists and is already injected at live wiring; ErrorHandler becomes
  its consumer.
- **`SystemStore` (`storage/system_store.py`)** — key/JSON `upsert`/`get` already
  supports `state.last_error`; the live instance already exists (halt records / P9 stats).
- **`HaltReason` enum (`core/enums/system.py`)** — extend, don't recreate; `halt()`
  already emits a CRITICAL ErrorEvent, so the ERR-04 funnel is partly wired.
- **`ErrorPolicy` (`trading_system/error_policy.py`)** — the WR-05/WR-06 publish-and-
  continue body already exists; P8 relocates + formalizes it rather than rewriting.

### Established Patterns
- **Routing-is-data** — the `EventHandler.routes` literal and `_CONTROL_EVENT_TYPES`
  frozenset are the model for the D-09 `FailureClass` map.
- **compose_engine mode-agnostic graph; factories inject backends** — `results_store` is
  the precedent for the new optional `alert_sink`/`system_store` kwargs (D-04).
- **Same-thread → direct call; cross-thread → event** — `ReconciliationCoordinator`
  calls `safety.halt` directly (engine thread); connector emits `ConnectorFatalEvent`
  (asyncio thread). The tripwire is engine-thread → direct call (D-12).
- **WR-06 two-guard terminal safety** — source guard (don't republish a failing
  ErrorEvent) + consumer guard (on_error wraps + swallows). Both preserved.
- **Indentation split (measure per file):** `full_event_handler.py`, `okx.py`,
  `safety_controller.py`, `compose.py`, `live_trading_system.py` are **TABS**;
  `error_policy.py`, `config/safety.py`, `core/`, and the events package are **4 SPACES**.
  Match the file being edited — never normalize.

### Integration Points
- `EventHandler.__init__` gains an `error_policy` param + an `error_handler` param; its
  `_dispatch` except-block calls the injected policy; the ERROR route calls
  `error_handler.on_error`.
- `compose_engine` builds `ErrorHandler` + selects the policy; `build_live_system`
  supplies `LogAlertSink`, the shared `SystemStore`, `safety.halt`, and the live
  `ErrorPolicy`; backtest supplies `FailFastPolicy` + `None` collaborators.
- The tripwire lives on `ErrorPolicy`; its trip calls injected `safety.halt`; `halt`
  emits the CRITICAL ErrorEvent that ErrorHandler consumes → alert-sink + last_error.

</code_context>

<specifics>
## Specific Ideas

- The ERR-03 acceptance test is a **hard criterion**: a "money route (FILL settlement)
  failing on EVERY event" must **trip and halt**, while the WR-06 terminal swallow still
  holds. The pure `should_trip` + injectable `now` design (D-11) exists specifically to
  make this deterministic and cheap to test.
- The user explicitly values the alert-sink as a **future general notification channel**
  (Telegram/email for big wins, big losses, weekly reports) — hence D-03's "owned by the
  composition root, injected, not owned by ErrorHandler."

</specifics>

<deferred>
## Deferred Ideas

- **General notification egress** — generalize the alert-sink beyond `ErrorEvent` so it
  can carry non-error notifications (big wins, big losses, weekly reports) via
  Telegram/email. The signature `alert(event: ErrorEvent)` would broaden then. → future
  phase / **FastAPI milestone**. NOT P8.
- **errors-history table** — append-only durable error log (new Alembic migration +
  store on the `HaltRecordStore` template, ~1 plan). Deferred to the **FastAPI
  milestone**, where the query endpoints (pagination / severity+time filters) that read
  it are built — the schema should be designed against real access patterns. Structured
  logs bridge the gap until then.
- **Breaker counters + `state.*` into the SystemStore `stats.snapshot` UI read-model** —
  that wiring is **P9 (RTCFG-06)**, not P8. P8 surfaces counters only via `get_status()`.
- **Runtime-tunable failure-rate thresholds** — `FailureRateSettings` lands in the config
  home in P8 (static defaults); making it mutable via `ConfigUpdateEvent` is **P9**.

</deferred>

---

*Phase: 8-error-subsystem*
*Context gathered: 2026-07-14*
