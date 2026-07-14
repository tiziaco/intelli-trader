# Phase 8: Error Subsystem - Research

**Researched:** 2026-07-14
**Domain:** Live-engine error-handling spine (ErrorPolicy injection, CF-1 failure-rate tripwire, ErrorHandler ERROR-route consumer) — internal refactor, zero new dependencies
**Confidence:** HIGH (all claims verified against current source at cited line numbers)

## Summary

This is a code-verification research pass, not a technology survey. The 17 CONTEXT.md decisions
(D-01..D-17) are LOCKED; the job here is to confirm the code reality those decisions assume, pin
exact line numbers for every seam the planner touches, and surface the landmines the decisions did
NOT fully resolve. Every recommended package already ships — the milestone gate forbids any new
dependency, so there is no Package Legitimacy Audit or Environment Availability section.

Three findings materially change the plan and must be read before planning: **(1)** D-05's explicit
open question resolves NEGATIVE — `build_live_system` constructs **no** `SystemStore` anywhere in the
codebase; it builds a `SqlEngine` (`system_db_backend`) and a `HaltRecordStore` over it, so the
planner must MINT `SystemStore(system_db_backend)` sharing that SAME engine (not a fresh one), gated
on `system_db_backend is not None`. **(2)** CONTEXT.md's indentation table is WRONG for two target
files — `live_trading_system.py` and `safety_controller.py` are **4-SPACE**, not TABS (MEMORY warned
this exact CONTEXT.md class of error bit a prior planner). **(3)** The FILL_TRANSLATION counting path
(D-10) is the one genuine architectural gap the decisions leave open: an okx fill-translation failure
arrives as an off-thread `ErrorEvent` on the ERROR route, NOT through `ErrorPolicy.on_handler_error`
(the handler-failure seam where D-11's tripwire state lives), so where it gets counted is undecided.

**Primary recommendation:** Plan the ErrorPolicy relocation + FailFastPolicy split first (oracle-safe,
mechanical), then the ErrorHandler + alert/system_store wiring, then the CF-1 tripwire — and resolve
the FILL_TRANSLATION counting-seam question (Open Question #1) before writing the tripwire plan.

## Project Constraints (from CLAUDE.md + milestone gates)

- **Oracle byte-exact:** `SMA_MACD` stays `134 / 46189.87730727451` (`check_exact=True`); the backtest
  fail-fast path must be byte-for-byte unchanged. Per-PLAN gate.
- **OKX import-inertness:** `tests/integration/test_okx_inertness.py` stays green. New modules must
  import stdlib + msgspec + pydantic ONLY — no ccxt / async / sql / pandas on the backtest import graph.
- **Zero new third-party dependency, no poetry change** anywhere in the milestone. Every mechanic here
  is stdlib (`collections.deque`, `time.monotonic`, `datetime`) + already-pinned pydantic/msgspec.
- **Money is Decimal end-to-end** — not exercised in this phase (windowed counters are `int`/`float`
  like `ThrottleSettings.max_orders`/`window_s`; no money math in the error subsystem).
- **Events are `msgspec.Struct`** (`Event, frozen=True, kw_only=True, gc=False`), NOT frozen
  dataclasses despite CLAUDE.md prose. Copy `events_handler/events/error.py::ErrorEvent`.
- **`mypy --strict` clean on new code; `filterwarnings=["error"]` green** (any unexpected warning
  fails the suite; every marker declared).
- **Backtest fail-fast vs live publish-and-continue is intentional documented policy**
  (`.planning/codebase/CONVENTIONS.md`), not an inconsistency — preserve it.
- **Indentation matched per file, never normalized** — see the corrected table below (CRITICAL).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Handler-failure policy (fail-fast vs publish-and-continue) | `EventHandler._dispatch` seam (injected `HandlerErrorPolicy`) | composition root (selects policy) | The dispatcher owns the except-block; the policy is DI'd so both modes are unit-testable |
| Failure-rate classification + trip | `ErrorPolicy` (live only, engine thread) | `core/enums` (FailureClass), `config/safety` (thresholds) | D-11 puts the hit-deque state on ErrorPolicy; classification is declarative data |
| Halt on trip | injected `safety.halt` (SafetyController) | — | D-12 same-thread direct call; halt is the latched freeze |
| ERROR-route consumption (log / alert / persist) | `ErrorHandler` (engine thread) | injected `AlertSink` + `SystemStore` collaborators | D-01/D-03 two-guard consumer, egress owned by comp root |
| CRITICAL egress | `AlertSink` (`LogAlertSink`) | — | D-03 general notification channel, injected not owned |
| `last_error` persistence | `SystemStore.upsert('state.last_error', …)` | — | D-17 live-only, inside the WR-06 consumer guard |
| Off-thread fatal/fill-translation hand-off | connector emits event on bus → engine thread | — | Cross-thread = event; same-thread = direct call |

## Corrected Indentation Table (CRITICAL — CONTEXT.md is WRONG for two files)

Verified empirically (function-body leading whitespace), 2026-07-14:

| File | Actual indent | CONTEXT.md claim | Status |
|------|--------------|------------------|--------|
| `events_handler/full_event_handler.py` | **TAB** | TABS | ✅ correct |
| `execution_handler/exchanges/okx.py` | **TAB** | TABS | ✅ correct |
| `trading_system/compose.py` | **TAB** | TABS | ✅ correct |
| `trading_system/live_trading_system.py` | **4-SPACE** | TABS | ❌ **WRONG** |
| `trading_system/safety/safety_controller.py` | **4-SPACE** | TABS | ❌ **WRONG** |
| `trading_system/error_policy.py` | **4-SPACE** | 4 SPACES | ✅ correct |
| `trading_system/alert_sink.py` | **4-SPACE** | (implied) | ✅ 4-space |
| `config/safety.py` | **4-SPACE** | 4 SPACES | ✅ correct |
| `core/enums/system.py` | **4-SPACE** | 4 SPACES | ✅ correct |
| `events_handler/events/error.py` (+ `control.py`) | **4-SPACE** | 4 SPACES | ✅ correct |

**Landmine:** MEMORY (`live-trading-system-is-space-indented.md`) already flagged that CONTEXT.md
misclassifies `live_trading_system.py` — this exact error bit a prior planner. It also misclassifies
`safety_controller.py`. **Edits to `live_trading_system.py` (monkeypatch removal ~:589, alert-sink
site ~:1214, `SystemStore` wiring, tripwire `halt` injection) and to `safety_controller.py` (HaltReason
typing) are 4-SPACE.** `compose.py`, `full_event_handler.py`, `okx.py` are TABS. `[VERIFIED: grep/sed on current source]`

**New-file indent choices (Claude's discretion, D-08 / D-01):**
- `events_handler/error_policy.py` (RELOCATED from `trading_system/error_policy.py`) — keep **4-SPACE**
  (the donor is 4-space; the events package is 4-space). `[VERIFIED]`
- `events_handler/error_handler.py` (NEW) — recommend **4-SPACE** to match its two-guard sibling
  `error_policy.py`, even though the `_log_error_event` body it absorbs currently lives in the TAB file
  `full_event_handler.py`. Re-indent the lifted body to 4-space. `[ASSUMED — planner's call]`
- `core/enums/error.py` (NEW, if FailureClass lands there) — **4-SPACE** (core/ convention). `[VERIFIED]`

## Open Question #1 (LANDMINE — resolve before the tripwire plan): where is FILL_TRANSLATION counted?

**The gap.** D-11 puts the per-`FailureClass` hit-deque state dict on `ErrorPolicy`, and the tripwire
fires inside `ErrorPolicy.on_handler_error` — the seam invoked when a **routed handler raises**
(`full_event_handler.py:150-154`). But a FILL_TRANSLATION failure (D-10) happens on the **connector
asyncio thread** inside `OkxExchange._consume_fills` (`okx.py:757-765`), which does NOT go through a
routed handler. D-10 says it "emits a counted `ErrorEvent(source="okx_exchange",
operation="fill-translation")`". That ErrorEvent lands on the bus → the **ERROR route** →
`ErrorHandler.on_error` — NOT `ErrorPolicy.on_handler_error`. So the tripwire state on ErrorPolicy is
never touched by it.

**What §3b actually says:** the attach point is "`_publish_and_continue` (S1) **plus a shared counter
surface for S8/S9 which bypass S1**" (`v17_audit_results.md:242`). §3b explicitly acknowledges that
S8 (okx fill-translation) and S9 (loop-backstop) bypass the handler-failure seam and need a
**shared counter surface**. The decisions (D-11 state-on-ErrorPolicy) did not re-close this.

**Options for the planner (decisions win where they speak; this is genuinely undecided):**
1. **Shared tripwire seam.** Extract the hit-deque state + `should_trip` into a small shared object
   (e.g. `FailureTripwire`) that BOTH `ErrorPolicy` (routed failures) and `ErrorHandler` (off-thread
   ErrorEvents classified by `source`/`operation`) reference. Consistent with §3b's "shared counter
   surface." `ErrorHandler` would need the injected `halt` too.
2. **Halt-on-first shortcut.** SETTLEMENT/FILL_TRANSLATION are N=1, so `ErrorHandler.on_error` can
   halt-on-first directly for an ErrorEvent whose `source=="okx_exchange"` and
   `operation=="fill-translation"` (and any SETTLEMENT-classed ErrorEvent), needing only an injected
   `halt`, no shared deque. The windowed classes (ORDER_IO/ADMISSION/LOOP_BACKSTOP) stay entirely on
   ErrorPolicy. Simpler; splits classification across two sites.

**Recommendation:** Option 1 if the planner wants one classification map and one counter; Option 2 if
it wants minimal surface (the only off-thread counted class is halt-on-first anyway). Either way,
note: D-09's classification map keyed "primarily on `EventType`" would map an ErrorEvent (type=ERROR)
to LOOP_BACKSTOP by default — FILL_TRANSLATION MUST be refined by `source`/`operation`, not `EventType`.
`[VERIFIED: okx.py:757-765 off-thread; error_policy.py:58-97 handler-failure-only seam]`

## Seam Verification (all line numbers current as of 2026-07-14)

### `events_handler/full_event_handler.py` (TAB)
- **`_dispatch` except block** — lines 150-154; calls `self._on_handler_error(event, handler)` (the D-16
  seam). D-06 change: `_dispatch` calls `self._error_policy.on_handler_error(event, handler)` instead.
- **`_on_handler_error` method** — lines 156-171; body is a bare `raise` (line 171). **D-06 DELETES
  this method**; the injected `HandlerErrorPolicy` replaces it (`FailFastPolicy` body = bare `raise`).
- **`_log_error_event` method** — lines 173-225; the ERROR-route consumer with the WR-06 consumer guard
  (whole body wrapped in `try/except`, plus an inner `try/except pass` for the last-resort log, lines
  215-225). **D-01 replaces this with `ErrorHandler.on_error`.** The CRITICAL→alert-sink escalation is
  lines 213-214.
- **`_alert_sink` attribute** — declared `None` at `__init__` line 81 (`_AlertSinkLike | None`); consumed
  at 213-214. **D-03 REMOVES this attribute entirely** (dispatcher must hold no egress state); the
  `_AlertSinkLike` Protocol (lines 23-34) goes with it.
- **`routes` literal** — lines 89-117; the ERROR route is line 116 `EventType.ERROR:
  [self._log_error_event]` → becomes `[self.error_handler.on_error]`. `EventHandler.__init__` (lines
  59-68) gains `error_policy` + `error_handler` params.
- **`_CONTROL_EVENT_TYPES` is NOT in this file** — it lives in the bus module (`events_handler/bus.py`);
  D-09 cites it only as the *convention model* for the FailureClass frozen map, not a co-located symbol.
  `[VERIFIED]`

### `trading_system/error_policy.py` → relocate to `events_handler/error_policy.py` (4-SPACE)
- `ErrorPolicy` class lines 38-97; `on_handler_error(event, handler)` lines 58-97.
- **WR-06 source guard** — lines 85-86: `if getattr(event, 'type', None) is EventType.ERROR: return`
  (don't republish a fresh ErrorEvent for a failing ErrorEvent → prevents error→error livelock).
- **`error_counter` bookkeeping** — lines 76-77 (increments the facade's `_stats['errors_count']` via
  the injected callback), CURRENTLY fires BEFORE the source guard. See Order-of-ops note below.
- Constructor takes `bus` + optional `error_counter` (lines 47-56). D-11/D-12 ADD the per-`FailureClass`
  hit-deque state dict + `_POLICY` map + injected `halt: Callable[[str], None]`. `[VERIFIED]`

### `trading_system/live_trading_system.py` (4-SPACE — NOT tabs)
- **Monkeypatch site** — line 589: `self.event_handler._on_handler_error =
  self._error_policy.on_handler_error  # type: ignore[method-assign]` (inside `start()`, D-17 comment
  582-588). **D-06 REMOVES this** (policy injected at `EventHandler.__init__` in `compose_engine`).
- **`_alert_sink` set site** — line 1214: `event_handler._alert_sink = LogAlertSink()` (in
  `build_live_system`). **D-03/D-04 REMOVES this**; `LogAlertSink()` becomes the `alert_sink=`
  kwarg into `compose_engine`.
- **`ErrorPolicy` construction** — line 1231: `error_policy = ErrorPolicy(global_queue,
  error_counter=facade._increment_error_count)`; attached `facade._error_policy = error_policy` (1249)
  and passed to `LiveRunner(error_policy=…)` (1236). D-12 adds `halt=safety.halt` here.
- **`SqlEngine` / durable stores** — live arm builds `backend = SqlEngine(SqlSettings(...))` (line 1007),
  `system_db_backend = backend` (1009); `HaltRecordStore(system_db_backend)` gated on
  `system_db_backend is not None` (1015-1019). `import LogAlertSink` already at line 8. `[VERIFIED]`
- **`compose_engine` call** — line 1044: `engine = compose_engine(ctx, exchange_config=None,
  results_store=None)`. D-04 adds `alert_sink=…, system_store=…` kwargs here. `[VERIFIED]`

### `execution_handler/exchanges/okx.py` (TAB)
- **D-10 target is NOT line 651.** The live-stream per-trade skip is `_consume_fills` lines **757-765**:
  `try: self._handle_trade(trade) except Exception: self.logger.error("OKX fill translation failed —
  skipping trade", exc_info=True)`. The `:651` in CONTEXT.md/§3b is a STALE v1.7 line reference. There
  is a SECOND log-only variant in `catch_up_missed_fills` at lines **673-675** ("OKX missed-fill
  catch-up translation failed — skipping trade") — the planner should decide whether D-10's counted
  ErrorEvent covers both drain paths or only the live `_consume_fills` one. `ErrorEvent` is already
  imported (line 42); an existing `ErrorEvent` emit pattern is at lines 284-294 (cancel-arm). Bind only
  declared fields + the exception TYPE (never `str(exc)` — T-05-27 secret scrub). `[VERIFIED]`

### `trading_system/alert_sink.py` (4-SPACE)
- `AlertSink` `@runtime_checkable Protocol` lines 35-47 (`alert(event: "ErrorEvent") -> None`);
  `LogAlertSink` lines 50-83 (marked `logger.critical`, binds only declared ErrorEvent fields).
  Ready to inject as-is; no change needed beyond wiring. `[VERIFIED]`

### `trading_system/safety/safety_controller.py` (4-SPACE — NOT tabs)
- `halt(reason: str)` — line 144; `reason` is currently `str`-typed (docstring vocab at 165-166).
  **Already emits ONE CRITICAL `ErrorEvent`** on the winning transition (lines 187-197,
  `error_type='EngineHalted'`, `severity=ErrorSeverity.CRITICAL`) and records the durable halt
  (207-208). **The ERR-04 funnel for `halt()` is therefore ALREADY wired** — the CRITICAL ErrorEvent
  reaches the ERROR route → ErrorHandler. D-16 changes `reason` to a `HaltReason`-typed vocabulary; the
  trip callers pass the new members. `update_status` is the single mutation seam (line 421). `[VERIFIED]`

### `core/enums/system.py` (4-SPACE)
- `HaltReason` current members (lines 89-93): `BASELINE_RESIDUAL`, `CONNECTOR_FATAL`,
  `RECONCILIATION_UNRESOLVED`, `DURABLE_HALT`, `DRIFT`. **D-16 ADDS** `SETTLEMENT_FAILURE`,
  `ORDER_ROUTE_ERRORS`, `ADMISSION_ERRORS`, `LOOP_BACKSTOP` (FILL_TRANSLATION reuses
  `SETTLEMENT_FAILURE`). `.value` must be the wire string (durable halt records persist as strings —
  no migration). Candidate home for `FailureClass` here or a new `core/enums/error.py` (D-08 discretion).
  `[VERIFIED]`

### `config/safety.py` (4-SPACE)
- `ThrottleSettings` (lines 29-54) is the near-exact template: sliding window `max_orders: int = 10` /
  `window_s: float = 10.0`, `model_config = ConfigDict(extra="forbid")`, `default()` classmethod.
  `SafetySettings` (lines 57-72) holds `throttle: ThrottleSettings`. **D-14 ADDS a `FailureRateSettings`
  model beside `ThrottleSettings` and a `failure_rate:` field on `SafetySettings`.** Defaults:
  SETTLEMENT 1/halt-on-first, ORDER_IO 3/60s, ADMISSION 3/300s, LOOP_BACKSTOP 5/60s (FILL_TRANSLATION =
  SETTLEMENT). Field shape (tuple vs named) is D-14 discretion. `[VERIFIED]`

### `storage/system_store.py` (4-SPACE)
- `SystemStore(sql_engine: SqlEngine)` (line 69); `upsert(key: str, value: dict[str, Any], at:
  datetime) -> None` (line 82); `get(key) -> Optional[Mapping]` (line 99). **Clock-free store — caller
  supplies `at`** (use the ErrorEvent's business `time`, or `datetime.now(UTC)` fallback, matching the
  ErrorPolicy convention `error_policy.py:91`). D-17 persists `state.last_error` = scrubbed ErrorEvent
  fields + timestamp. `[VERIFIED]`

### `trading_system/compose.py` (TAB)
- `compose_engine(ctx, *, exchange_config=None, results_store=None)` — signature lines 117-120.
  `EventHandler` build site lines 237-245. `Engine` holder `results_store: Optional[ResultsStore] = None`
  (line 114) is the PRECEDENT for the new optional kwargs. **D-04 adds `alert_sink: Optional[Any] =
  None` and `system_store: Optional[Any] = None` kwargs**, builds `ErrorHandler` + selects the policy,
  passes both into `EventHandler(...)`. Type the new kwargs `Optional[Any]` (or a TYPE_CHECKING
  Protocol) — do NOT module-import `SystemStore`/`LogAlertSink` concretes here (compose is on the
  backtest import graph; keep it SQL/egress-import-inert, mirroring the `ResultsStore` ABC-only import
  at line 44). `[VERIFIED]`

### `events_handler/events/error.py` + `control.py` (4-SPACE, msgspec.Struct)
- `ErrorEvent(Event, frozen=True, kw_only=True, gc=False)` fields: `type: ClassVar =
  EventType.ERROR`, `source`, `error_type`, `error_message`, `operation: str|None = None`,
  `correlation_id: CorrelationId|None = None`, `severity: ErrorSeverity = ERROR`, `details:
  dict|None = None` (lines 45-52). `PortfolioErrorEvent` narrows `source="portfolio"` + adds
  `portfolio_id` (64-75) and carries `type=EventType.ERROR` (inherited) → **routes to the ERROR route**.
- `ConnectorFatalEvent(type=EventType.CONNECTOR_FATAL, reason: str)` (control.py:57-71) → routes to the
  **CONNECTOR_FATAL route (`EventType.CONNECTOR_FATAL: []` today, live-wired to `safety.halt` per
  SAFE-03), NOT the ERROR route directly.** Its ERR-04 funnel is INDIRECT: CONNECTOR_FATAL → `halt` →
  CRITICAL ErrorEvent → ERROR route. Copy `ErrorEvent`'s msgspec shape for any new event. `[VERIFIED]`

## ERR-04 funnel reality (what "one error funnel" actually means)

Every error source ultimately produces an `ErrorEvent` on the **ERROR route**, but via different paths:

| Source | Path to the ERROR route |
|--------|-------------------------|
| Handler failure (live) | `ErrorPolicy.on_handler_error` publishes `ErrorEvent(severity=ERROR)` → ERROR route |
| `halt()` (CRITICAL) | `safety_controller.halt` emits `ErrorEvent(EngineHalted, CRITICAL)` directly → ERROR route (already wired, `safety_controller.py:187-197`) |
| `PortfolioErrorEvent` | subclasses ErrorEvent, `type=EventType.ERROR` → ERROR route directly |
| `ConnectorFatalEvent` | CONNECTOR_FATAL route → `safety.halt` → CRITICAL ErrorEvent → ERROR route (INDIRECT) |
| FILL_TRANSLATION (okx) | `_consume_fills` emits `ErrorEvent(okx_exchange, fill-translation)` → ERROR route (see Open Q#1 for counting) |

So `ErrorHandler.on_error` is the single consumer where log + CRITICAL-alert + `last_error`-persist all
converge. `[VERIFIED]`

## CF-1 §3b Distilled (authoritative breaker spec) + deltas vs decisions

Route-classification table (`v17_audit_results.md:239-270`):

| Class | Failing route (spec) | Policy (spec) | HaltReason (D-16) |
|-------|----------------------|---------------|-------------------|
| SETTLEMENT | `EventType.FILL` → `PortfolioHandler.on_fill` / `OrderHandler.on_fill`/ReconcileManager | **halt on FIRST** (N=1, no window) | `SETTLEMENT_FAILURE` |
| ORDER_IO | `EventType.ORDER` → execution/exchange handlers; S7 submit-recovery | N=3 / W=60s → halt | `ORDER_ROUTE_ERRORS` |
| ADMISSION | `EventType.SIGNAL` → order admission | N=3 / W=300s → halt | `ADMISSION_ERRORS` |
| FILL_TRANSLATION | S8 `okx.py` per-trade skip (now :757-765) | prerequisite: counted ErrorEvent → treat as SETTLEMENT (halt on first) | `SETTLEMENT_FAILURE` (reused) |
| LOOP_BACKSTOP | S9 loop catch-all (unknown locus) | N=5 / W=60s → halt | `LOOP_BACKSTOP` |
| COSMETIC | ERROR-route consumer, callbacks, lifecycle | **never counted (WR-06 preserved)** | — |

**Deltas the planner must honor (decisions win, but note the movement):**
1. **Attach point moves.** §3b attaches to `LiveTradingSystem._publish_and_continue` with a ring on the
   facade guarded by `_stats_lock`. D-07/D-11/D-12 relocate: the `ErrorPolicy` (now in `events_handler/`)
   owns the hit-deque state; a **pure module-level `should_trip(hits, threshold, window, now) -> bool`**
   does the windowed-count math; a `_POLICY` map holds `(threshold, window, reason)`. No facade ring,
   no breaker class, no state machine, no auto-reset (D-07: one-way tripwire, not open/half-open).
2. **Free strings → enum.** §3b halt reasons are free strings (`"fill-settlement-failure"`,
   `"order-route-errors"`); D-16 makes them typed `HaltReason` members. Decisions win.
3. **`_stats_lock` mechanics.** §3b guards the ring with the facade `_stats_lock`. The relocated state
   lives on `ErrorPolicy` on the engine thread (D-12 same-thread). The tripwire runs on the engine
   thread only (routed-handler failures + engine-thread-consumed ErrorEvents), so heavy locking may be
   unnecessary — but if `ErrorPolicy._error_counter` still writes the facade `_stats` cross-referenced
   from `get_status()` (another thread reads), keep the existing lock discipline. Verify the read side
   (`live_trading_system.py:789-815`, `get_status` merges the safety snapshot + facade stats). `[VERIFIED]`
4. **"COSMETIC never counted" == WR-06 source guard.** The tripwire count MUST sit so an ErrorEvent that
   itself failed is neither republished NOR counted (see Order-of-ops note). `[VERIFIED]`
5. **The §3b "hard dependency → ARCH-4 transition table" is now SATISFIED.** §3b warned the breaker was
   inert until the HALTED-latch transition table landed. That shipped in P7 (`SafetyController` +
   `VALID_STATUS_TRANSITIONS`, `HALTED: set()` terminal, `safety_controller.py`/`core/enums/system.py`).
   So a tripwire `halt()` will latch and not be clobbered. `[VERIFIED]`

## WR-06 Two-Guard Terminal Safety — exact current shape (preserve byte-for-byte)

**Source guard** (`ErrorPolicy.on_handler_error`, `error_policy.py:85-86`):
```python
if getattr(event, 'type', None) is EventType.ERROR:
    return
```
Don't publish a fresh ErrorEvent when the failing event is itself an ErrorEvent — otherwise the fresh
ErrorEvent routes back to the ERROR consumer, and if that consumer keeps failing you get an unbounded
error→error feedback loop livelocking one `process_events()` drain. The `error_counter()` call
currently precedes this guard (lines 76-77 vs 85-86).

**Consumer guard** (`_log_error_event`, `full_event_handler.py:189-225` → moves to
`ErrorHandler.on_error`): the ENTIRE body (severity-map log + CRITICAL alert escalation) is wrapped in
`try/except`, and the last-resort recovery log is itself wrapped in an inner `try/except: pass`. The
consumer NEVER re-raises into `_dispatch`. **D-17's `last_error` persist (`system_store.upsert`) MUST
sit INSIDE this outer guard** so a SQL-write failure is swallowed, never re-raised. `[VERIFIED]`

**Order-of-ops for the tripwire (D — Claude's discretion, but WR-06-constrained):** put the
count/classify/trip AFTER the WR-06 source guard's `return` so ERROR-type failures (COSMETIC) are
neither counted nor republished. Decide explicitly whether the tripwire count follows the existing
`error_counter` position (which currently counts ALL failures incl. ERROR-type) or the republish guard
(which skips ERROR-type). §3b's "COSMETIC never counted" ⇒ the tripwire count belongs after the guard.

## Oracle-Safety Proof Surface

**Why `FailFastPolicy` is byte-exact.** Today `_dispatch`'s except block calls
`self._on_handler_error(event, handler)` whose body is a bare `raise` (`full_event_handler.py:171`),
re-raising the exception active in the calling except block — a handler failure aborts the run. D-06
replaces the method with an injected `FailFastPolicy.on_handler_error` whose body is ALSO a bare
`raise`, called from the same except block. A bare `raise` inside a function called from an except
block re-raises the currently-handled exception identically (the exception context propagates into
calls made from except blocks). The ONLY change on the backtest path is a method→injected-object
indirection with an identical control-flow effect — no behavior change, no new branch, no egress, no
SQL. Backtest injects `FailFastPolicy` + `alert_sink=None` + `system_store=None`, so `ErrorHandler`
logs only and never escalates/persists.

**Proving it:**
- `tests/integration/test_backtest_oracle.py::test_oracle_numeric_values` — `check_exact=True`, final
  equity `46189.87730727451` (lines 173-211).
- `tests/integration/test_backtest_oracle.py::test_oracle_behavioral_identity` — 134 trades,
  `check_exact=True` (lines 128-161).
- `tests/integration/test_backtest_smoke.py` — smoke import/run.
- `tests/integration/test_okx_inertness.py` — import-inertness (new modules must not drag
  ccxt/async/sql/pandas onto the backtest graph; compose must not module-import egress/SQL concretes).
`[VERIFIED: oracle test file located, MEMORY oracle-test-location confirms this is THE oracle]`

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| CRITICAL egress | a new alerting class | inject `LogAlertSink` (`alert_sink.py`) | Already the CF-5 seam, already secret-scrubbed |
| `last_error` persistence | a new table/store | `SystemStore.upsert('state.last_error', …)` | KV store exists, clock-free, `state.*` is the RTCFG-06 read-model home |
| Halt latch / idempotency | a new breaker state machine | injected `safety.halt` (`SafetyController`) | D-07 explicitly: one-way tripwire, halt owns the latch; halt is idempotent + already emits CRITICAL ErrorEvent |
| Threshold config | constants in code | `FailureRateSettings` on `SafetySettings` (D-14) | Config home = free P9 runtime-tunability; `ThrottleSettings` is the template |
| Sliding-window count | a custom ring buffer class | `collections.deque` + pure `should_trip(now)` | D-11: minimal, deterministic via injectable `now`, unit-testable |
| Classification | an if/elif chain | declarative frozen `dict[EventType, FailureClass]` + qualname refinement | D-09 Option A, mirrors `_CONTROL_EVENT_TYPES` routing-is-data |

## Common Pitfalls

1. **Wrong indentation on `live_trading_system.py`/`safety_controller.py`** — they are 4-SPACE, not
   TABS (CONTEXT.md is wrong). A tab-vs-space diff breaks the file. Match per file (table above).
2. **Module-importing `SystemStore`/`LogAlertSink` into `compose.py`** — breaks OKX inertness (compose
   is on the backtest graph). Keep new kwargs `Optional[Any]`; build concretes in `build_live_system`.
3. **Minting a fresh `SqlEngine` for `SystemStore`** — D-05: reuse `system_db_backend`. There is NO
   existing `SystemStore` to share, but there IS a shared `SqlEngine`; a second engine = a second pool.
4. **Counting the WR-06-guarded ERROR-type failures into the tripwire** — COSMETIC must never count;
   trip AFTER the source guard.
5. **Persisting `last_error` OUTSIDE the consumer guard** — a SQL failure would re-raise into `_dispatch`
   and (live) republish → error→error loop. Keep the upsert inside the try/except.
6. **Assuming FILL_TRANSLATION flows through `on_handler_error`** — it does not (off-thread ErrorEvent).
   See Open Question #1.
7. **`str(exc)` on the okx ErrorEvent** — secret-scrub (T-05-27): bind exception TYPE + declared fields
   only. The existing cancel-arm emit (`okx.py:284-294`) is the pattern.
8. **Forgetting the second okx fill-translation drain path** (`catch_up_missed_fills`, `okx.py:673-675`)
   — decide whether D-10's counted ErrorEvent covers it.

## Runtime State Inventory

This phase adds new code + a new `HaltReason` member set; it does not rename stored keys. One item:
- **Stored data (`HaltReason.value` wire strings):** D-16 adds enum members whose `.value` are NEW
  strings (`settlement-failure`, `order-route-errors`, `admission-errors`, `loop-backstop` — planner
  picks the literals). No migration of EXISTING durable halt records (existing `.value`s unchanged;
  `core/enums/system.py:84-86` notes durable records persist as strings and still resolve). New reasons
  only appear on NEW trips. **Action: none (additive).**
- **`state.last_error` key (new SystemStore key):** first write is live-only; no pre-existing rows to
  migrate. **Action: none.**
- **Live service config / OS-registered state / secrets / build artifacts:** None — verified this is an
  in-process refactor with no external-service or OS registration surface.

## Validation Architecture

> Nyquist validation is ENABLED for this phase. `plan-phase` will materialize VALIDATION.md from this
> section. All tests run through Poetry (`make test` / `poetry run pytest`); markers are folder-derived
> (`unit`/`integration`) plus hand-applied `live`. `filterwarnings=["error"]` — no unexpected warnings.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/events -x -q` (+ new `tests/unit/error/` or similar) |
| Full suite command | `poetry run pytest tests` (use `poetry run pytest` in worktrees; `make test` exports `ITRADER_DISABLE_LOGS=true` which breaks caplog-based warn assertions — see MEMORY) |

### Phase Requirements → Test Map
| Req | Behavior | Test type | Command (illustrative) | File exists? |
|-----|----------|-----------|------------------------|--------------|
| ERR-01 | `FailFastPolicy.on_handler_error` re-raises the active exception identically (oracle byte-exact) | unit | `pytest tests/unit/error/test_error_policy.py::test_failfast_reraises -x` | ❌ Wave 0 |
| ERR-01 | Oracle stays `134 / 46189.87730727451` after policy injection | integration | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ existing |
| ERR-01 | Live `ErrorPolicy` publishes one ErrorEvent per non-ERROR handler failure, per-handler qualname in `operation` | unit | `pytest tests/unit/error/test_error_policy.py::test_publish_per_handler -x` | ❌ Wave 0 |
| ERR-01 | WR-06 **source guard**: a failing ERROR event is NOT republished and NOT counted | unit | `…::test_source_guard_no_republish_no_count -x` | ❌ Wave 0 |
| ERR-03 | **"money route failing every event" trips + halts** (SETTLEMENT N=1), WR-06 swallow holds, no error→error livelock | unit | `…::test_settlement_trips_on_first -x` | ❌ Wave 0 |
| ERR-03 | Windowed classes trip at threshold via injectable `now` (ORDER_IO 3/60s, ADMISSION 3/300s, LOOP_BACKSTOP 5/60s) | unit (parametrized/property) | `…::test_should_trip_windows -x` | ❌ Wave 0 |
| ERR-03 | `FailureRateSettings` defaults match D-14; `extra="forbid"` rejects unknown keys | unit | `pytest tests/unit/config/test_safety.py -x` | ✅/❌ extend |
| ERR-03 | FILL_TRANSLATION emits a counted `ErrorEvent(source="okx_exchange", operation="fill-translation")` → SETTLEMENT halt-on-first | unit (live) | `pytest tests/unit/execution/test_okx_exchange.py::test_fill_translation_counted -x` | ❌ Wave 0 |
| ERR-02 | `ErrorHandler.on_error` severity-maps log; CRITICAL → injected `AlertSink.alert` | unit | `pytest tests/unit/error/test_error_handler.py -x` | ❌ Wave 0 |
| ERR-02 | WR-06 **consumer guard**: a raising alert-sink/logger/SQL-write is swallowed, never re-raised | unit | `…::test_consumer_guard_swallows -x` | ❌ Wave 0 |
| ERR-02 | `last_error` persisted via `system_store.upsert('state.last_error', …)` live; `system_store=None` → no-op on backtest | unit | `…::test_last_error_persist_and_noop -x` | ❌ Wave 0 |
| ERR-04 | `halt()` / `PortfolioErrorEvent` / handler failure / (indirect) `ConnectorFatalEvent` all reach `ErrorHandler.on_error` | unit/integration | `…::test_error_funnel -x` | ❌ Wave 0 |
| gate | `test_okx_inertness.py` stays green (new modules import-inert; compose SQL/egress-inert) | integration | `pytest tests/integration/test_okx_inertness.py -x` | ✅ existing |

### Sampling Rate
- **Per task commit:** the touched unit slice + `test_backtest_oracle.py` (any file under the compose /
  event-handler / error seam is oracle-risk).
- **Per wave merge:** `poetry run pytest tests/unit tests/integration -q`.
- **Phase gate:** full suite green + oracle byte-exact + `test_okx_inertness.py` green before `/gsd-verify-work`.

### Deterministic vs held-out
- **Inferable / deterministic (must pass):** FailFastPolicy re-raise, oracle regression, inertness,
  source-guard + consumer-guard units, backtest `system_store=None`/`alert_sink=None` no-op branches,
  the SETTLEMENT halt-on-first trip (N=1, no clock needed).
- **Held-out / property-based:** the windowed `should_trip(hits, threshold, window, now)` math — a
  property test over arbitrary timestamp sequences (trips iff ≥ threshold hits within `window`,
  pruning older hits), driven by an injected `now` so ORDER_IO/ADMISSION/LOOP_BACKSTOP windows are
  exercised without wall-clock flakiness. This is the D-11 "injectable now" payoff.

### Wave 0 Gaps
- [ ] `tests/unit/error/test_error_policy.py` — FailFastPolicy re-raise, publish-per-handler, WR-06
  source guard, tripwire trips (ERR-01/ERR-03).
- [ ] `tests/unit/error/test_error_handler.py` — severity map, CRITICAL→alert, consumer guard,
  last_error persist + backtest no-op (ERR-02).
- [ ] `tests/unit/error/test_should_trip.py` (or property module) — windowed count math (ERR-03).
- [ ] Extend `tests/unit/config/test_safety.py` — `FailureRateSettings` defaults + `extra="forbid"`.
- [ ] Extend the okx exchange unit tests — FILL_TRANSLATION counted ErrorEvent (ERR-03/D-10).
- [ ] `tests/conftest.py` fixtures: a fake `AlertSink`, a fake `SystemStore` (record upserts), a fake
  `halt` callable, an injectable `now` — shared across the error unit slice.
- Confirm the `tests/unit/error/` (or chosen) directory stays package-less (no `__init__.py`) to avoid
  the top-level package-collision collection bug (MEMORY `test-dir-init-py-package-collision`).

## Security Domain

`security_enforcement` applies. This phase is error-handling infra; the relevant control is **V7
(error handling / logging) secret-scrub**, already the house discipline:

| ASVS | Applies | Standard control (existing) |
|------|---------|------------------------------|
| V7 Error Handling & Logging | yes | Bind ONLY declared `ErrorEvent` fields (never `str(exc)` / connector payload) — `alert_sink.py`, `error.py`, okx emit pattern `okx.py:284-294` |
| V5 Input Validation | yes | `FailureRateSettings` `ConfigDict(extra="forbid")` rejects unknown config keys (mass-assignment defense, T-04-01) |
| V6 Cryptography | no | — |

| Threat | STRIDE | Mitigation |
|--------|--------|------------|
| Secret leak via error/alert/persisted `last_error` | Information Disclosure | Field-bind discipline at the ErrorEvent boundary; the `state.last_error` upsert stores only declared/scrubbed fields |
| error→error livelock (DoS via ERROR-route recursion) | Denial of Service | WR-06 two-guard terminal safety (source + consumer); tripwire count after the source guard |
| Silent settlement loss hiding a halt-worthy failure | Tampering | D-10 FILL_TRANSLATION counted ErrorEvent → SETTLEMENT halt-on-first (closes the "green run, zero settlements" class, AUD-3) |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | New `error_handler.py` should be 4-SPACE (matches `error_policy.py` sibling) | Indentation | Low — planner may pick; re-indent lifted `_log_error_event` body accordingly |
| A2 | D-10's counted ErrorEvent may need to cover BOTH okx drain paths (`_consume_fills` :757-765 and `catch_up_missed_fills` :673-675) | Seam / okx.py | Medium — a lost catch-up fill stays invisible if only the live path is patched |
| A3 | The tripwire runs engine-thread-only, so facade `_stats_lock` may be reusable rather than a new lock | CF-1 deltas | Medium — verify `get_status()` cross-thread read of counters before dropping locking |

**Everything else is `[VERIFIED]` against current source at the cited line numbers.**

## Open Questions

1. **(LANDMINE) Where is FILL_TRANSLATION counted?** — off-thread ErrorEvent vs the ErrorPolicy
   handler-failure seam. Resolve before the tripwire plan (see the dedicated section). Recommendation:
   a shared tripwire seam referenced by both ErrorPolicy and ErrorHandler, OR ErrorHandler halt-on-first
   for SETTLEMENT-classed ErrorEvents (N=1) with the windowed classes staying on ErrorPolicy.
2. **Does `ErrorHandler` need the injected `halt`?** — only if Open Q#1 lands FILL_TRANSLATION counting
   in the ERROR consumer. D-12 injects `halt` into `ErrorPolicy`; the planner may need to thread it to
   `ErrorHandler` too (add it as a compose kwarg / build-live wiring).
3. **`FailureClass` home** (D discretion): `core/enums/system.py` (beside `HaltReason`) vs new
   `core/enums/error.py`. Both 4-SPACE. Recommendation: co-locate in `system.py` since `HaltReason`
   maps 1:1 to `FailureClass` and they are read together at the trip site.

## Sources

### Primary (HIGH — current source, verified)
- `itrader/events_handler/full_event_handler.py` (dispatch seam, routes, `_log_error_event`, `_alert_sink`)
- `itrader/trading_system/error_policy.py` (WR-05/WR-06 body, source guard)
- `itrader/trading_system/live_trading_system.py` (monkeypatch :589, alert-sink :1214, SqlEngine/stores :1007-1044, ErrorPolicy :1231-1249)
- `itrader/execution_handler/exchanges/okx.py` (`_consume_fills` :757-765, catch-up :673-675, emit pattern :284-294)
- `itrader/trading_system/alert_sink.py`, `safety/safety_controller.py`, `compose.py`, `config/safety.py`
- `itrader/core/enums/system.py` (HaltReason), `storage/system_store.py`, `events_handler/events/error.py` + `control.py`
- `tests/integration/test_backtest_oracle.py`, `test_okx_inertness.py`
- `.planning/milestones/v1.7-review/v17_audit_results.md` §3a/§3b (CF-1 spec)

### Secondary (MEDIUM — planning artifacts)
- `.planning/phases/08-error-subsystem/08-CONTEXT.md` (D-01..D-17)
- `.planning/REQUIREMENTS.md` (ERR-01..04), `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/CONCERNS.md` (AUD-3)
- MEMORY: `live-trading-system-is-space-indented.md`, `events-are-msgspec-struct.md`,
  `wr06-error-route-terminal-safety.md`, `oracle-test-location.md`, `make-test-env-disables-logs.md`,
  `test-dir-init-py-package-collision.md`

## Metadata

**Confidence breakdown:**
- Seam line numbers / code shape: HIGH — read directly from current source this session.
- D-05 resolution (no SystemStore): HIGH — zero `SystemStore(` sites in `itrader/`, grep-verified.
- Indentation corrections: HIGH — empirically measured per file.
- CF-1 §3b distillation + deltas: HIGH — spec read; deltas cross-checked vs decisions.
- FILL_TRANSLATION counting seam: flagged as Open Question (the decisions themselves are the gap).

**Research date:** 2026-07-14
**Valid until:** ~2026-08-14 (stable internal code; re-verify line numbers if P8 slips behind further commits)
