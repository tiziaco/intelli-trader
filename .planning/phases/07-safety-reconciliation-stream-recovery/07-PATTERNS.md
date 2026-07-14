# Phase 7: Safety + Reconciliation + Stream Recovery - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 11 (5 new, 6 modified)
**Analogs found:** 11 / 11

> This is a **behavior-preserving live-only extraction**, not a greenfield build. Almost every new
> module is code-motion of an already-tested body out of `live_trading_system.py`. The analogs below
> are therefore mostly the **donor bodies themselves** plus the sibling-collaborator shape they must
> match. The two genuinely-new artifacts (`PreTradeThrottle`, the two CONTROL event classes) have real
> structural analogs in-tree.

## Indentation Ledger (measured this session — per file, DO NOT normalize)

| Target file | Indentation | Verified |
|-------------|-------------|----------|
| `core/enums/order.py` (add `OrderRiskRole`) | **TABS** | `grep -nP '^\t'` → TAB |
| `config/safety.py` (new) | **4 SPACES** | matches `config/stream.py` (SPACE) |
| `trading_system/safety/*.py` (new) | **4 SPACES** | matches `live_trading_system.py` / `live_runner.py` / `route_registrar.py` (all SPACE) |
| `trading_system/live_runner.py` (edit) | **4 SPACES** | SPACE |
| `trading_system/live_trading_system.py` (edit) | **4 SPACES** | SPACE |
| `portfolio_handler/reconcile/venue_reconciler.py` (edit) | **4 SPACES** | SPACE (verified — NOT tabs despite `portfolio_handler/` being a tab-tree elsewhere) |
| `events_handler/events/control.py` (new) | **4 SPACES** | matches `events/base.py` / `events/error.py` (SPACE) |

**Landmine:** `core/enums/order.py` is the ONE tab-indented target. CLAUDE.md's "`core/` is 4-space"
is wrong for `enums/order.py` (predates the space-indented core modules). Every other target is
4-space.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| NEW `trading_system/safety/safety_controller.py` | service (pure state machine) | event-driven / state | donor bodies in `live_trading_system.py:400-584,724-834` | exact (code-motion) |
| NEW `trading_system/safety/stream_recovery_handler.py` | service (engine-thread I/O) | event-driven | donor `live_trading_system.py:607-684` | exact (code-motion) |
| NEW `trading_system/safety/pre_trade_throttle.py` | service (net-new backstop) | request-response (pre-submit filter) | `live_runner.py` collaborator shape + `_dispatch_live` classification `741-765` | role-match |
| NEW `config/safety.py` | config | — | `config/stream.py` (`StreamSettings`/`FeedProviderSettings`) | exact |
| NEW `events_handler/events/control.py` (`StreamStateEvent`/`ConnectorFatalEvent`) | event (msgspec.Struct) | event-driven (CONTROL tier) | `events/error.py::ErrorEvent` + `events/base.py::Event` | exact |
| MODIFY `core/enums/order.py` (add `OrderRiskRole`) | enum | — | `OrderCommand` (same file, `92-118`) | exact (same file) |
| MODIFY `portfolio_handler/reconcile/venue_reconciler.py` (CF-7 guard) | service | CRUD/reconcile | in-place edit at `venue_reconciler.py:411` | in-place |
| NEW/HOME `portfolio_handler/reconcile/reconciliation_coordinator.py` | service (orchestration) | batch/reconcile | `venue_reconciler.py` (sibling in same dir) | role-match |
| MODIFY `trading_system/live_trading_system.py` (delete flags, thin delegators) | composition root / facade | — | self (donor); delegator shape in RESEARCH §Patterns | in-place |
| MODIFY `trading_system/live_runner.py` (delete 2 hooks) | runtime engine | event-driven | self | in-place |
| MODIFY `trading_system/route_registrar.py` (register CONTROL routes) | route table | event-driven | `route_registrar.py:81-100` (existing SET/APPEND entries) | in-place |

## Pattern Assignments

### NEW `events_handler/events/control.py` (`StreamStateEvent` / `ConnectorFatalEvent`)

**Analog:** `events_handler/events/error.py::ErrorEvent` (msgspec, NOT dataclass) + `events/base.py::Event`.

**CRITICAL:** author as `msgspec.Struct` subclass of `Event`, NOT `@dataclass`. CLAUDE.md's "frozen
dataclass" language is stale — the events package migrated to msgspec. `EventType.STREAM_STATE` /
`CONNECTOR_FATAL` / `CONFIG_UPDATE` already exist (`core/enums/event.py:36-38`).

**Base to subclass** (`events/base.py:21-49`):
```python
class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType]
    time: datetime
    event_id: uuid.UUID = msgspec.field(default_factory=uuid_compat.uuid7)
    created_at: datetime | None = None
    def __post_init__(self) -> None:
        if self.created_at is None:
            object.__setattr__(self, "created_at", self.time)
```

**Concrete-event shape to copy** (`events/error.py:20-52` — `type: ClassVar[EventType] = ...` pin + typed fields):
```python
class ErrorEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.ERROR
    source: str
    error_type: str
    ...
    severity: ErrorSeverity = ErrorSeverity.ERROR
```

**New classes (from RESEARCH §Patterns):**
```python
class StreamStateEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.STREAM_STATE
    stream_name: str
    up: bool                      # True=reconnected, False=disconnected

class ConnectorFatalEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.CONNECTOR_FATAL
    reason: str                   # fixed literal only — NEVER str(exc) (V7 scrub)
```

**Barrel export pattern** (`events/__init__.py:44-45,81-82`): add `from .control import ...` + `__all__`
entries. These are already CONTROL-routed; the backtest never constructs them, so the barrel export is
inertness-safe (msgspec-only, no live/ccxt import).

---

### MODIFY `core/enums/order.py` — add `OrderRiskRole` (D-16)

**Analog:** `OrderCommand` in the SAME file (`order.py:92-110`) — class-based `Enum`, explicit string
values, case-insensitive `_missing_` house pattern. **TAB-INDENTED.**

```python
# TABS — match OrderCommand's leading '\t'
class OrderRiskRole(Enum):
	"""..."""
	CANCEL = "CANCEL"
	PROTECTIVE = "PROTECTIVE"
	ENTRY = "ENTRY"

	@classmethod
	def _missing_(cls, value: object) -> "OrderRiskRole":
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderRiskRole: {value!r}")
```

Per D-16 only the **enum** lands here; the `classify()` function travels with `SafetyController`.

---

### NEW `trading_system/safety/safety_controller.py` (pure state machine, SAFE-01/02)

**Analog:** the donor bodies in `live_trading_system.py` — extract **byte-identical** except D-11.
Boundary rows (verified this session): `halt` 400-464, `_is_halted` 466-469, `reset_halt` 471-512,
`_is_submission_paused` 514-517, `pause_submission` 519-545, `resume_submission` 547-565,
`_replay_deferred_protective` 567-584, `_dispatch_live`(gate) 724-766, `_update_status` 768-834,
`_notify_status_change` 836-862; fields `_submission_paused`/`_paused_reason` 213-214,
`_deferred_protective` deque 219-221.

**Winner-only halt** (`live_trading_system.py:433-464`) — DO NOT re-implement; move verbatim:
```python
transitioned = self._update_status(SystemStatus.HALTED, error_msg=f'halt: {reason}', halt_reason=reason)
if not transitioned:
    return  # already halted — first reason wins (idempotent).
self.global_queue.put(ErrorEvent(... severity=ErrorSeverity.CRITICAL))
if self._halt_record_store is not None:
    self._halt_record_store.record_halt(reason, datetime.now(UTC))
```

**Single-mutation seam** (`_update_status`, `761-834`) — the atomic check-and-set under `_status_lock`;
`force=True` reserved for `reset_halt`. Move verbatim.

**Dispatch gate → `gate_and_dispatch(event, dispatch_fn)`** (`_dispatch_live`, `724-766`). The inline
CANCEL/PROTECTIVE/ENTRY classification at `741-765` is the SEED for the shared `OrderRiskRole.classify`
(Pitfall 6): `command is OrderCommand.CANCEL` → CANCEL; `type is ORDER and parent_order_id is not None`
→ PROTECTIVE; else → ENTRY. Extract ONCE; both gate and throttle import it.

**D-11 — the ONE behavior change** (`_deferred_protective` deque, `live_trading_system.py:219-221`,
`maxlen=1000`): the append path currently silently drops-oldest. Change ONLY the overflow branch → on
append-to-full escalate to `halt` + CRITICAL. `_replay_deferred_protective` (snapshot-then-clear,
`567-584`) stays identical. Needs exactly one new test.

**check_durable_halt_on_start** (donor `start()` `1013-1030`): runs FIRST, re-latch via `update_status`
(not `halt()` — no second durable write). `HaltRecordStore.has_unresolved/get_unresolved` verified.

---

### NEW `trading_system/safety/stream_recovery_handler.py` (engine-thread resume I/O, SAFE-04)

**Analog:** donor `_maybe_resume_after_reconnect` (`607-666`) + `_all_venue_streams_healthy` (`668-684`).
Becomes `StreamRecoveryHandler.on_reconnect` — reached by the `STREAM_STATE(up)` route, not per-tick
polling.

- Engine-thread `on_reconnect` does ONLY `catch_up_missed_fills()` + `account.snapshot()` +
  all-streams-healthy gate → `safety.resume_submission`.
- **CF-2 / Pitfall 4:** the REST ring backfill (`LiveBarFeed.backfill_on_resume`, `live_bar_feed.py:392`)
  must land **loop-native** via the reconnect callback (`okx_provider.spawn_gap_backfill` pattern) — the
  engine thread must NEVER reach the ring writer (single-writer contract). Add the no-engine-thread-ring-writer
  assertion.
- D-12: on snapshot/catch-up failure, stay paused, retry on next stream-up (extract as-is).

---

### NEW `trading_system/safety/pre_trade_throttle.py` (SAFE-06, net-new)

**Analog (collaborator shape):** `trading_system/live_runner.py` — a plain injected collaborator,
`get_itrader_logger().bind(component=...)`, injected clock (determinism seam), NO facade back-reference.
**Analog (classification):** the shared `OrderRiskRole.classify` (D-05) — throttle meters `ENTRY` only.

- D-04 sliding window: `deque` of timestamps, prune-left off the **injected clock** (never wall clock).
  See RESEARCH Code Examples `_RateWindow`.
- D-02/D-10: reject via `FillEvent.new_fill('REFUSED', order, ...)` (`fill.py:94`) — same egress
  `EnhancedOrderValidator` uses; max-notional uses limit price when present, else last mark, **Decimal**.
- D-09: increment a breach counter (read-model, P9) + de-duped WARNING `ErrorEvent` (min-interval off
  injected clock). See RESEARCH Code Example.
- D-06/A3: a distinct injected `pre_submit(event) -> bool` runner callable at the ORDER→execution
  boundary, ahead of `dispatch_gate` — mirrors how `dispatch_gate` is already injected into `LiveRunner`.
  **Planner to confirm A3.**

---

### NEW `config/safety.py` (`ThrottleSettings` / `SafetySettings`, D-13)

**Analog:** `config/stream.py::StreamSettings` (exact).

```python
from pydantic import BaseModel, ConfigDict

class ThrottleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")   # mass-assignment defense (T-04-01)
    max_orders: int = 10
    window_s: float = 10.0
    max_notional_per_order: Decimal = Decimal("25000")   # D-07 defaults, ON by default
    warn_min_interval_s: float = ...

    @classmethod
    def default(cls) -> "ThrottleSettings":
        return cls()
```

- Convention: `ConfigDict(extra="forbid")` + a `default()` classmethod (`stream.py:41,53-56`).
- Pydantic-only, so it MAY be an eager `SystemConfig` field like `config/stream.py` (`system.py:112`) —
  inertness-safe. D-14: static caps + shape the P9 mutation seam (settable caps object); NO runtime
  `ConfigUpdateEvent` wiring in P7.

---

### MODIFY `portfolio_handler/reconcile/venue_reconciler.py` (CF-7, SAFE-05) — **4 SPACES**

**In-place edit at `venue_reconciler.py:411`**: `venue_id = str(matched["id"])`. Replace the bare
coercion with a typed fail-loud guard (A1 — Claude's discretion; recommend a new
`ReconciliationError(ITraderError)` per `core/exceptions/base.py` hierarchy):
```python
raw_id = matched.get("id")
if raw_id is None:
    raise ReconciliationError(
        f"venue resting order for leg {child.internal_id} has no 'id' — cannot re-link OCO")
venue_id = str(raw_id)
```

---

### NEW `portfolio_handler/reconcile/reconciliation_coordinator.py` (D-17, SAFE-05) — **4 SPACES**

**Analog:** `venue_reconciler.py` (sibling in the same dir — same indentation, same logger/typed-error
conventions). Wraps the donor `start()` rehydrate→reconcile block (`1124-1165`) + baseline guard
(`_run_session_baseline_guard`, `349-398`). **Key on account *kind*** (venue-truth discriminator: add
`is_venue_truth` on the `Account` ABC OR `isinstance(VenueAccount)` — A4), NOT `exchange=='okx'`, so
paper/simulated never reaches the venue reconcile.

---

### MODIFY `trading_system/route_registrar.py` (CONTROL routes) — **4 SPACES**

**In-place**: the registrar already documents (`route_registrar.py:102-105`) that CONTROL routes
"populate when their consumers land." Add SET entries in `install()` alongside `81-100`:
```python
routes[EventType.STREAM_STATE] = [<stream-state consumer>]        # down→safety.pause / up→recovery.on_reconnect
routes[EventType.CONNECTOR_FATAL] = [<safety.halt-from-fatal>]
```
List order IS execution order (D-03b). These are new SET entries, not appends.

---

### MODIFY `trading_system/live_runner.py` (delete 2 hooks, Pitfall 3) — **4 SPACES**

Delete the injected `resume_after_reconnect` / `halt_after_connector_fatal` callables (ctor params
`65-66`, assigns `111-112`) and their 4 call sites (`161-166` on the event path, `171-175` on the
queue-empty path). The `dispatch_gate` injection STAYS (repointed to `SafetyController.gate_and_dispatch`).
`build_live_system:1688-1689` stops passing the two callables. CONTROL events now wake `bus.get()`
naturally, so the idle-resume path the queue-empty drain covered is preserved.

---

### MODIFY `trading_system/live_trading_system.py` (facade cleanup) — **4 SPACES**

- **DELETE** flag fields `_pending_stream_resume`/`_pending_connector_halt`/`_pending_connector_halt_reason`
  (`215-218`).
- Rewrite `_on_venue_stream_down`/`_on_venue_stream_up`/`_request_connector_halt` (`586-605,686-703`) →
  connector-loop callbacks that **`bus.put(StreamStateEvent/ConnectorFatalEvent)`** instead of flipping flags.
- Rewrite wiring `set_stream_state_listener`/`set_halt_signal` (`build_live_system` `1652-1660`, 3 call
  sites: provider, okx_exchange, okx_connector) → CONTROL-event emitters.
- Retain thin **delegators** for the extracted surface (`halt`/`pause_submission`/`reset_halt`/`get_status`)
  so the ~45 external call sites + live test suite keep working:
  ```python
  def halt(self, reason: str) -> None:
      self._safety.halt(reason)
  ```
- **Keep all safety imports LAZY inside `build_live_system`** (Pitfall 5) — never barrel-export
  `trading_system/safety/*`, or `test_okx_inertness.py` breaks.

## Shared Patterns

### Shared `OrderRiskRole` classifier (D-05/D-16 — one source of truth)
**Source:** extract inline classification from `live_trading_system.py:741-765`.
**Apply to:** `SafetyController.gate_and_dispatch` AND `PreTradeThrottle`. Enum in `core/enums/order.py`
(TABS); `classify(event)` travels with `SafetyController`. Throttle meters ENTRY only; CANCEL/PROTECTIVE
bypass uncounted → the throttle physically cannot reject a stop/bracket-child/cancel.

### Injected clock determinism (D-04)
**Source:** `core/clock.py` seam (already injected across stochastic components).
**Apply to:** `PreTradeThrottle` sliding window + D-09 WARNING dedup — read the injected clock, never
wall clock.

### V7 secret-scrub (load-bearing, ASVS V7 / T-05-01)
**Source:** `halt`/`_update_status` bodies bind ONLY fixed reason literals + declared ErrorEvent fields.
**Apply to:** EVERY halt/pause/CONTROL handoff. `ConnectorFatalEvent.reason` is a fixed literal
(`'connector-fatal'`), NEVER `str(exc)` / connector payload. Preserve verbatim in extracted bodies.

### CRITICAL ErrorEvent egress
**Source:** `live_trading_system.py:443-453`.
**Apply to:** `SafetyController.halt` (CRITICAL) + `PreTradeThrottle` D-09 (WARNING). Route through the
`global_queue`/bus ERROR route; bind only declared fields.

### Order-rejection egress
**Source:** `FillEvent.new_fill('REFUSED', order, ...)` (`events/fill.py:94`).
**Apply to:** `PreTradeThrottle` breach (D-02) — same path `EnhancedOrderValidator` uses; mirror
reconciles REFUSED→REJECTED.

### Durable-halt spine
**Source:** `HaltRecordStore.record_halt/has_unresolved/get_unresolved/resolve_all`
(`storage/halt_record_store.py:97-141`).
**Apply to:** `SafetyController.halt` (record) / `reset_halt` (resolve_all) /
`check_durable_halt_on_start` (has_unresolved). Do NOT re-implement persistence.

### Config convention
**Source:** `config/stream.py` — `BaseModel` + `ConfigDict(extra="forbid")` + `default()` classmethod.
**Apply to:** `config/safety.py`.

## No Analog Found

None. Every target has a real in-tree analog (donor body or sibling collaborator). The only net-new
LOGIC is the `PreTradeThrottle` sliding-window + notional check and the two CONTROL event classes — and
both have strong structural analogs (`live_runner.py` collaborator shape / `events/error.py` msgspec
event).

## Metadata

**Analog search scope:** `itrader/trading_system/`, `itrader/events_handler/events/`,
`itrader/config/`, `itrader/core/enums/`, `itrader/portfolio_handler/reconcile/`.
**Files scanned:** ~9 read in full/part + grep sweeps for indentation and EventType members.
**Pattern extraction date:** 2026-07-14
**Caveat:** `live_trading_system.py` line numbers drift when touched — re-verify boundary rows against
the current tree at plan time (RESEARCH "Verified Extraction Boundaries" is the authoritative table).
