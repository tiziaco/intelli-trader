# Phase 8: Error Subsystem - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 12 (4 new, 8 modified)
**Analogs found:** 12 / 12 (every target has an in-repo donor — this is an internal refactor)

> **Indentation is load-bearing.** Match the file being edited, never normalize.
> The excerpts below carry each donor's REAL indentation. RESEARCH corrects CONTEXT.md
> for two files: `live_trading_system.py` and `safety_controller.py` are **4-SPACE**, NOT tabs.
> - **TABS:** `full_event_handler.py`, `okx.py`, `compose.py`
> - **4-SPACE:** `live_trading_system.py`, `safety_controller.py`, `error_policy.py`,
>   `alert_sink.py`, `config/safety.py`, `core/enums/system.py`, `storage/system_store.py`,
>   `events_handler/events/*.py`
> New files (`events_handler/error_policy.py` relocated, `events_handler/error_handler.py`,
> `core/enums/error.py` if used) → **4-SPACE**.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/events_handler/error_handler.py` (NEW) | handler/consumer | event-driven (ERROR route) | `full_event_handler.py::_log_error_event` (lines 173-225) + `error_policy.py::ErrorPolicy` (collaborator shape) | role+flow exact (lifted body) | 4-SPACE |
| `itrader/events_handler/error_policy.py` (RELOCATED from `trading_system/`) | policy | event-driven + tripwire | `trading_system/error_policy.py::ErrorPolicy` (itself — verbatim donor) | self (extend in place) | 4-SPACE |
| `FailFastPolicy` + `HandlerErrorPolicy` Protocol (in relocated `error_policy.py`) | policy / protocol | request-response (except-block callback) | `full_event_handler.py::_on_handler_error` (body=bare `raise`, lines 156-171); `alert_sink.py::AlertSink` (runtime_checkable Protocol shape) | exact | 4-SPACE |
| `should_trip(...)` module fn + `_POLICY` map (in relocated `error_policy.py`) | pure utility + data map | transform (windowed count) | `config/safety.py::ThrottleSettings` sliding-window fields; `full_event_handler.py::routes` literal (data-map convention) | role-match | 4-SPACE |
| `FailureClass` enum → `core/enums/system.py` (or new `error.py`) | enum | n/a | `core/enums/system.py::HaltReason` (lines 89-93) | exact | 4-SPACE |
| `HaltReason` +4 members (D-16) | enum | n/a | the enum itself (lines 89-93) | self | 4-SPACE |
| `FailureRateSettings` Pydantic model → `config/safety.py` | config | n/a | `config/safety.py::ThrottleSettings` (lines 29-54) | near-exact template | 4-SPACE |
| `compose.py::compose_engine` (MODIFY — kwargs + build ErrorHandler) | composition | wiring | `results_store` optional-kwarg precedent (compose.py:114, 120, 153-155) | exact precedent | TABS |
| `live_trading_system.py::build_live_system` (MODIFY) | composition root | wiring | own sites: :589 (monkeypatch del), :1007-1019 (SqlEngine/HaltRecordStore mint pattern), :1214 (_alert_sink del), :1226-1249 (ErrorPolicy build) | self | 4-SPACE |
| `full_event_handler.py::EventHandler` (MODIFY — inject policy+handler, del 3 members) | dispatcher | event-driven | own `__init__`/`routes`/`_dispatch` (lines 59-154) | self | TABS |
| `execution_handler/exchanges/okx.py` `_consume_fills` (MODIFY — counted ErrorEvent) | exchange arm | event-driven (off-thread) | `okx.py` cancel-arm ErrorEvent emit (lines 284-294) | exact (same file, same pattern) | TABS |
| `events_handler/events/error.py::ErrorEvent` (reference, likely unchanged) | event | n/a | itself (msgspec.Struct shape, lines 20-52) | self | 4-SPACE |

## Pattern Assignments

### `itrader/events_handler/error_policy.py` (RELOCATED + EXTENDED) — 4-SPACE

**Analog:** itself (`trading_system/error_policy.py`). Move VERBATIM, then add the tripwire.
This is the WR-05/WR-06 body. Preserve the **source guard** and `error_counter` bookkeeping.

**Existing body to keep (lines 58-97)** — `on_handler_error`, note the WR-06 source guard at 85-86:
```python
    def on_handler_error(self, event: Any, handler: Any) -> None:
        exc = sys.exc_info()[1]
        handler_name = getattr(handler, '__qualname__', repr(handler))
        self.logger.error(
            f'Handler {handler_name} failed on {getattr(event, "type", "UNKNOWN")}: {exc}'
        )
        if self._error_counter is not None:
            self._error_counter()
        # WR-06 source guard: do NOT republish (or count) a failing ErrorEvent.
        if getattr(event, 'type', None) is EventType.ERROR:
            return
        self._bus.put(ErrorEvent(
            time=getattr(event, 'time', datetime.now(UTC)),
            source='live_trading_system',
            error_type=type(exc).__name__ if exc is not None else 'UnknownError',
            error_message=str(exc) if exc is not None else 'unknown handler failure',
            operation=handler_name,
            severity=ErrorSeverity.ERROR,
        ))
```

**Extension (D-11/D-12):** add to `__init__` an injected `halt: Callable[[str], None]`, a
per-`FailureClass` hit-deque state dict (`collections.deque`), and the `_POLICY` map. The
tripwire count/classify/trip goes **AFTER** the source-guard `return` (RESEARCH Order-of-ops:
COSMETIC/ERROR-type must never be counted). `now` is injectable for the deterministic ERR-03
trip test.

**`FailFastPolicy` + `HandlerErrorPolicy` Protocol** to add here:
- Protocol shape donor — `alert_sink.py::AlertSink` (runtime_checkable Protocol, method body `...`):
```python
@runtime_checkable
class AlertSink(Protocol):
    def alert(self, event: "ErrorEvent") -> None:
        ...
```
  → `HandlerErrorPolicy` mirrors it: `def on_handler_error(self, event, handler) -> None: ...`
- `FailFastPolicy.on_handler_error` body donor — `full_event_handler.py::_on_handler_error` (line 171):
```python
	def _on_handler_error(self, event, handler) -> None:
		raise  # bare raise re-raises the active except-block exception → oracle byte-exact
```
  (Re-indent to 4-SPACE in the new file. This is the ORACLE-SAFETY-critical excerpt — a bare
  `raise` from a fn called inside the except block re-raises identically.)

**Pure `should_trip` math** — model the sliding-window fields on `ThrottleSettings` (below);
append `now`, prune entries outside `window`, return `len >= threshold`. Use `collections.deque`.

---

### `itrader/events_handler/error_handler.py` (NEW) — 4-SPACE

**Analog:** `full_event_handler.py::_log_error_event` (lines 173-225) — lift the body VERBATIM,
re-indent tab→4-space. It becomes `ErrorHandler.on_error`.

**Consumer body + WR-06 consumer guard (lines 189-225)** — the ENTIRE body wrapped in
`try/except`, with an inner `try/except: pass` last-resort:
```python
		try:
			log_method = {
				ErrorSeverity.WARNING: self.logger.warning,
				ErrorSeverity.CRITICAL: self.logger.critical,
			}.get(event.severity, self.logger.error)
			context: dict[str, Any] = {
				"source": event.source,
				"error_type": event.error_type,
				"error_message": event.error_message,
				"operation": event.operation,
				"correlation_id": event.correlation_id,
			}
			portfolio_id = getattr(event, "portfolio_id", None)
			if portfolio_id is not None:
				context["portfolio_id"] = portfolio_id
			if event.details is not None:
				context["details"] = event.details
			log_method("Error event consumed", **context)

			if event.severity is ErrorSeverity.CRITICAL and self._alert_sink is not None:
				self._alert_sink.alert(event)
		except Exception:
			try:
				self.logger.error("ERROR-route consumer failed; swallowed ... (WR-06)", exc_info=True)
			except Exception:
				pass
```

**Changes for D-01/D-03/D-17:**
- `__init__` takes injected collaborators: `alert_sink: AlertSink | None = None`,
  `system_store: SystemStore | None = None` (D-03/D-04 — held, not constructed).
- `.alert()` call is unchanged (already gated on `severity is CRITICAL and _alert_sink is not None`).
- **D-17 `last_error` persist** — add `system_store.upsert('state.last_error', {...}, at=...)`
  INSIDE the outer `try/except` (WR-06: a SQL failure must be swallowed). Gate on
  `system_store is not None` (backtest = None → no-op). See SystemStore excerpt below for `upsert`.
- Field-bind discipline (secret scrub, T-05-27): bind ONLY declared `ErrorEvent` fields.

**Collaborator injection shape donor** — `alert_sink.py::LogAlertSink.__init__`/`alert` (holds a
ref, calls `.alert(event)`, binds declared fields only).

---

### `should_trip` + `_POLICY` map — 4-SPACE (lives in relocated `error_policy.py`)

**Analog A — sliding-window math:** `config/safety.py::ThrottleSettings` (lines 43-44)
`max_orders: int` / `window_s: float` — the same window/threshold pair.

**Analog B — declarative data map (routing-is-data):** `full_event_handler.py::routes` literal
(lines 89-117) — a single reviewable `dict[EventType, ...]` literal. D-09's `FailureClass` map
mirrors this: `dict[EventType, FailureClass]` keyed primarily on `EventType`, with handler-qualname
/ `source`+`operation` refinement (FILL_TRANSLATION must be refined by `source`/`operation`, NOT
`EventType` — an ErrorEvent's type is ERROR which would default to LOOP_BACKSTOP).

---

### `core/enums/system.py` — `FailureClass` (NEW) + `HaltReason` +4 (D-16) — 4-SPACE

**Analog:** `HaltReason` enum (lines 89-93). `.value` = wire string (durable records persist as
strings — additive, no migration).
```python
    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
    DRIFT = "drift"
```
**D-16 adds:** `SETTLEMENT_FAILURE`, `ORDER_ROUTE_ERRORS`, `ADMISSION_ERRORS`, `LOOP_BACKSTOP`
(planner picks the `.value` literals, e.g. `"settlement-failure"`). FILL_TRANSLATION reuses
`SETTLEMENT_FAILURE`. New `FailureClass` enum members: `SETTLEMENT, ORDER_IO, ADMISSION,
LOOP_BACKSTOP, FILL_TRANSLATION` (same `str, Enum` style; co-locate here per RESEARCH rec).

---

### `config/safety.py` — `FailureRateSettings` (NEW) — 4-SPACE

**Analog:** `ThrottleSettings` (lines 29-54) — near-exact template.
```python
class ThrottleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_orders: int = 10
    window_s: float = 10.0
    max_notional_per_order: Decimal = Decimal("25000")
    warn_min_interval_s: float = 5.0

    @classmethod
    def default(cls) -> "ThrottleSettings":
        return cls()
```
**Build `FailureRateSettings` in the same shape** (`ConfigDict(extra="forbid")` + `default()`),
holding the per-`FailureClass` `(threshold, window)` D-14 defaults: SETTLEMENT 1 / halt-on-first,
ORDER_IO 3/60s, ADMISSION 3/300s, LOOP_BACKSTOP 5/60s. Add a `failure_rate: FailureRateSettings`
field on `SafetySettings` beside `throttle` (line 67 pattern):
```python
    throttle: ThrottleSettings = Field(default_factory=ThrottleSettings)
```
Field representation (tuple vs named fields) is D-14 discretion.

---

### `compose.py::compose_engine` (MODIFY) — TABS

**Analog:** the `results_store` optional-kwarg precedent (same function). Signature (lines 117-120):
```python
def compose_engine(
	ctx: "EngineContext", *,
	exchange_config: Optional[Any] = None,
	results_store: Optional["ResultsStore"] = None) -> Engine:
```
**D-04 adds** `alert_sink: Optional[Any] = None` and `system_store: Optional[Any] = None` kwargs.
**Pitfall (inertness):** type them `Optional[Any]` — do NOT module-import `SystemStore`/`LogAlertSink`
concretes (compose is on the backtest import graph; mirror the ABC-only `ResultsStore` import).
Build `ErrorHandler(alert_sink=alert_sink, system_store=system_store)` and select the policy
(`FailFastPolicy` default) next to the `EventHandler` build (lines 237-245), then pass both into
`EventHandler(..., error_policy=..., error_handler=...)`.

---

### `full_event_handler.py::EventHandler` (MODIFY) — TABS

Own `__init__` (59-83), `routes` (89-117), `_dispatch` (136-154):
- **Add** `error_policy` + `error_handler` params to `__init__` (lines 59-68).
- **Delete** `_alert_sink` attr (line 81) + `_AlertSinkLike` Protocol (lines 23-34) — D-03.
- **Delete** `_on_handler_error` method (156-171) — D-06; `_dispatch` except-block (line 154)
  calls `self._error_policy.on_handler_error(event, handler)` instead of `self._on_handler_error(...)`.
- **Delete** `_log_error_event` method (173-225) — D-01; ERROR route (line 116) becomes
  `EventType.ERROR: [self.error_handler.on_error]`.
- Current `_dispatch` except block to change (lines 150-154):
```python
		for handler in handlers:
			try:
				handler(event)
			except Exception:
				self._on_handler_error(event, handler)   # → self._error_policy.on_handler_error(event, handler)
```
**Note (live-facade mypy blindspot, MEMORY):** sweep now-unused imports (`ErrorSeverity`,
`_AlertSinkLike`, `Protocol`) after the deletions — `ignore_errors` won't catch them.

---

### `okx.py` `_consume_fills` (MODIFY, D-10) — TABS

**Target is lines 757-765** (RESEARCH corrects the stale `:651`). Current log-only skip:
```python
				try:
					self._handle_trade(trade)
				except Exception:
					self.logger.error(
						"OKX fill translation failed — skipping trade", exc_info=True)
```
**Analog for the counted emit** — the cancel-arm `ErrorEvent` in the SAME file (lines 284-294):
```python
				self.global_queue.put(ErrorEvent(
					time=event.time,
					source="okx_exchange",
					error_type=type(exc).__name__,   # T-05-27: TYPE only, never str(exc)
					error_message=("OKX cancel failed ..."),
					operation="cancel_order",
					severity=ErrorSeverity.ERROR))
```
**Emit** `ErrorEvent(source="okx_exchange", operation="fill-translation", error_type=type(exc).__name__, ...)`
so it's classified FILL_TRANSLATION → SETTLEMENT halt-on-first. `ErrorEvent` already imported
(line 42). **A2/Pitfall 8:** a SECOND log-only drain path exists in `catch_up_missed_fills`
(lines 673-675) — planner decides whether D-10 covers both. **Landmine (Open Q#1):** this ErrorEvent
is OFF-THREAD → lands on the ERROR route (`ErrorHandler.on_error`), NOT `ErrorPolicy.on_handler_error`
where the tripwire deque lives. Resolve the counting seam (shared tripwire object vs ErrorHandler
halt-on-first for SETTLEMENT-classed ErrorEvents) before writing the tripwire plan.

---

### `live_trading_system.py::build_live_system` / `start()` (MODIFY) — 4-SPACE

- **Remove monkeypatch** (line 589, in `start()`): `self.event_handler._on_handler_error = self._error_policy.on_handler_error` — policy now injected in `compose_engine`.
- **Remove `_alert_sink` set** (line 1214): `event_handler._alert_sink = LogAlertSink()` → becomes the `alert_sink=LogAlertSink()` kwarg to `compose_engine`.
- **Mint `SystemStore`** — D-05 resolves NEGATIVE: there is NO existing `SystemStore` to share.
  Reuse the SAME `SqlEngine` (`system_db_backend`, built line 1007), mirroring the `HaltRecordStore`
  gate (lines 1015-1019):
```python
    if system_db_backend is not None:
        from itrader.storage.halt_record_store import HaltRecordStore
        halt_record_store: Optional[Any] = HaltRecordStore(system_db_backend)
    else:
        halt_record_store = None
```
  → build `SystemStore(system_db_backend)` under the same `is not None` gate; pass into
  `compose_engine(..., system_store=...)` (call at line 1044).
- **Inject `halt` into ErrorPolicy** — construction at line 1231:
```python
    error_policy = ErrorPolicy(global_queue, error_counter=facade._increment_error_count)
```
  → add `halt=safety.halt` (D-12, same-thread direct call). `LogAlertSink` already imported (line 8).

---

## Shared Patterns

### WR-06 Two-Guard Terminal Safety (preserve byte-for-byte)
**Apply to:** `error_policy.py` (source guard) + `error_handler.py` (consumer guard).
- **Source guard** (`error_policy.py:85-86`): `if getattr(event, 'type', None) is EventType.ERROR: return`
  — don't republish (or count into the tripwire) a failing ErrorEvent.
- **Consumer guard** (`full_event_handler.py:189-225` → `ErrorHandler.on_error`): whole body wrapped
  in `try/except`, inner `try/except: pass` last-resort. The D-17 `system_store.upsert` MUST sit inside.

### Secret-scrub field binding (T-05-27 / V7)
**Source:** `alert_sink.py::LogAlertSink.alert` (lines 69-82); `okx.py:284-294`.
**Apply to:** every ErrorEvent construction/consumption. Bind ONLY declared `ErrorEvent` fields +
exception TYPE (`type(exc).__name__`) — NEVER `str(exc)` or raw connector context.

### Injected-collaborator, comp-root-owned egress (D-03/D-04)
**Source:** `results_store` seam (`compose.py:114/120/153-155`) + `alert_sink.py` Protocol.
**Apply to:** `alert_sink` + `system_store` — new optional `compose_engine` kwargs, `Optional[Any]`
typed to keep compose SQL/egress-import-inert; concretes built in `build_live_system`.

### SystemStore.upsert (clock-free KV) — D-17
**Source:** `storage/system_store.py::upsert` (lines 82-97):
```python
    def upsert(self, key: str, value: dict[str, Any], at: datetime) -> None:
```
Caller supplies `at` — use the ErrorEvent's business `time` or `datetime.now(UTC)` fallback
(matches `error_policy.py:91`). Key = `'state.last_error'`, last-write-wins.

### Event shape (msgspec.Struct, NOT dataclass)
**Source:** `events_handler/events/error.py::ErrorEvent` (lines 20-52) —
`class ErrorEvent(Event, frozen=True, kw_only=True, gc=False)`, `type: ClassVar[EventType]`.
Copy this for any new event. (No new event type is required this phase.)

## No Analog Found

None. Every target has an in-repo donor — this is a self-contained internal refactor with zero new
dependencies. The only genuinely undecided design point is not a missing analog but the
**FILL_TRANSLATION counting seam** (Open Question #1): decide shared-tripwire-object vs
ErrorHandler-halt-on-first before the tripwire plan.

## Metadata

**Analog search scope:** `itrader/events_handler/`, `itrader/trading_system/`, `itrader/config/`,
`itrader/core/enums/`, `itrader/storage/`, `itrader/execution_handler/exchanges/`.
**Files scanned (read):** `error_policy.py`, `alert_sink.py`, `config/safety.py`,
`full_event_handler.py`, `core/enums/system.py`, `storage/system_store.py`,
`events/error.py`, `compose.py`, `okx.py`, `live_trading_system.py`.
**Pattern extraction date:** 2026-07-14
</content>
</invoke>
