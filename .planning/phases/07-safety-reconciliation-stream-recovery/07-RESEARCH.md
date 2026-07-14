# Phase 7: Safety + Reconciliation + Stream Recovery - Research

**Researched:** 2026-07-14
**Domain:** Live-only God-object decomposition — pure state-machine extraction, connector-callback → CONTROL-event handoff, pre-trade throttle. Brownfield, behavior-preserving on the live path, backtest-dark.
**Confidence:** HIGH (internal-codebase extraction; every boundary line-verified against the current tree this session)

## Summary

This is a **behavior-preserving live-only extraction**, not a greenfield build. The architecture is
fully locked (CONTEXT.md D-01..D-17 + design spec §11). The research value is entirely in **verifying
the current code boundaries** (the CONTEXT.md line numbers had drifted), **surfacing the three genuinely-
open discretion items against codebase prior-art**, and **cataloguing the live-only landmines** that can
break the two per-phase gates (`test_backtest_oracle.py` byte-exact `134 / 46189.87730727451`,
`test_okx_inertness.py`). Everything the phase extracts already exists and runs inside
`live_trading_system.py` (1700 lines, 4-space indented); P7 carves it into `SafetyController` (pure state
machine), `StreamRecoveryHandler` (engine-thread resume I/O), `ReconciliationCoordinator`
(`portfolio_handler/reconcile/`), and a net-new `PreTradeThrottle` — plus it deletes the
`_pending_stream_resume`/`_pending_connector_halt` flag side-channel in favor of CONTROL events.

Two facts materially change the plan from what CONTEXT.md implies. **(1) The CONTROL event dataclasses do
not exist yet** — `EventType.STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE` members and their empty
routes exist (`full_event_handler.py:113-115`), but `StreamStateEvent`/`ConnectorFatalEvent` **classes
must be authored in P7** as `msgspec.Struct` events (NOT `@dataclass` — the events package migrated to
msgspec; CLAUDE.md's "frozen dataclass" language is stale). **(2) Deleting the flag side-channel also
deletes the two `LiveRunner` per-tick drain hooks** (`_resume_after_reconnect`,
`_halt_after_connector_fatal`) that today the runner calls on both the event-received and queue-empty
paths (`live_runner.py:161-166, 171-175`) — those become CONTROL routes instead, which means the
`LiveRunner` constructor changes (it is explicitly designed to be "filled in without re-touching," but
this phase DOES re-touch it to remove two callables).

**Primary recommendation:** Extract in the spec's dependency order — `SafetyController` first (pure, no
I/O, unit-testable in isolation), then the CONTROL event classes + connector-callback rewiring +
`StreamRecoveryHandler`, then `ReconciliationCoordinator`, then the independent `PreTradeThrottle`.
Keep every extracted method body byte-identical to its donor (change ONLY the two decided deltas: D-11
overflow→halt and the flag→CONTROL handoff); the facade retains thin delegators so the ~45 external call
sites and the live test suite keep working.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Status latch (`_status`, `VALID_STATUS_TRANSITIONS`, `update_status`, `force=`) | `SafetyController` (pure) | — | No venue I/O; single-writer rule; unit-testable in isolation (§11a) |
| `halt`/`reset_halt`/`is_halted` + durable record write | `SafetyController` (pure) | `HaltRecordStore` (durable infra) | Winner-only check-and-set; durable write is a store call, not venue I/O (§11a/b) |
| `pause_submission`/`resume_submission` + deferred-protective queue + dispatch gate | `SafetyController` (pure) | — | Reversible quiesce + gate = pure decision logic (§11a) |
| `check_durable_halt_on_start` | `SafetyController` (pure) | `HaltRecordStore` | Runs FIRST, before any venue I/O; re-latch via `update_status` not `halt()` (§11b) |
| Reconnect resume I/O (catch-up fills + account snapshot + health gate) | `StreamRecoveryHandler` (engine thread) | OKX exchange / VenueAccount | I/O-heavy; must NOT live in the pure controller (§11c) |
| REST ring backfill on resume (CF-2) | Connector asyncio loop (loop-native) | `LiveBarFeed.backfill_on_resume` | Single-writer ring contract — engine thread must never reach the ring writer (CF-2) |
| Startup reconcile (rehydrate → venue reconcile → baseline guard) | `ReconciliationCoordinator` | `VenueReconciler`/`drift.py` | Orchestration next to the reconcile it wraps; keyed on account *kind* (§11d, CF-7) |
| Connector stream up/down + fatal → CONTROL events | Connector callbacks (asyncio loop) → bus | engine-thread CONTROL routes | Thread-safe `bus.put`; blocking response runs engine-side (LR-12, §11c) |
| Pre-submit rate + notional cap | `PreTradeThrottle` (engine thread, runner-invoked) | `OrderRiskRole` classifier | Owner risk backstop at the order→execution boundary, meters ENTRY only (D-01..D-10) |

## Standard Stack

No new external packages. This phase is pure internal refactor + net-new in-tree modules. All building
blocks are stdlib or already-vendored:

| Facility | Source | Purpose in P7 |
|----------|--------|---------------|
| `collections.deque` | stdlib `[VERIFIED: codebase — 26 prod usages]` | Deferred-protective queue (extract as-is) AND the D-04 sliding-window ring |
| `threading.Lock`/`Event` | stdlib | Status lock + stop-event (extract as-is) |
| `msgspec.Struct` | vendored (`events_handler/events/base.py`) `[VERIFIED: base.py:21]` | The new `StreamStateEvent`/`ConnectorFatalEvent` — frozen, kw_only, gc=False |
| `pydantic.BaseModel` | vendored `[VERIFIED: config/stream.py]` | `config/safety.py` — `ThrottleSettings`/`SafetySettings` |
| `PriorityEventBus` | `events_handler/bus.py` `[VERIFIED]` | CONTROL-tier preemption already implemented; STREAM_STATE/CONNECTOR_FATAL already enumerated as CONTROL |
| injected clock | `core/clock.py` (determinism seam) | The sliding-window throttle reads the injected clock, never wall clock (D-04) |

**Installation:** none — no `poetry add`.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages (verified: every dependency is stdlib or
already in `pyproject.toml`/the vendored tree). No `SLOP`/`SUS`/`OK` verdicts to record.

## Architecture Patterns

### CONTROL-event handoff (the core structural change)

```
CONNECTOR ASYNCIO LOOP THREAD                          ENGINE (queue-draining) THREAD
─────────────────────────────                         ──────────────────────────────
 okx_provider / okx_exchange / okx_connector
   stream-down callback  ──put(StreamStateEvent(down))──►┐
   stream-up   callback  ──put(StreamStateEvent(up))────►│  PriorityEventBus  (CONTROL tier
   fatal signal          ──put(ConnectorFatalEvent(r))──►┘   preempts BUSINESS/market data)
                                                              │
   (loop-native REST ring backfill:                          ▼  LiveRunner.get() dequeues
    reconnect callback → spawn_gap_backfill                  │  → EventHandler._dispatch → route:
    → LiveBarFeed.backfill_on_resume → ring.update())        │
                                                    STREAM_STATE(down) → SafetyController.pause_submission
                                                    STREAM_STATE(up)   → StreamRecoveryHandler.on_reconnect
                                                                          (catch_up_missed_fills +
                                                                           account.snapshot +
                                                                           all-streams-healthy gate →
                                                                           safety.resume_submission →
                                                                           replay deferred-protective)
                                                    CONNECTOR_FATAL(r) → SafetyController.halt(r)
                                                                          (winner-only → CRITICAL
                                                                           ErrorEvent → record_halt)
```

**DELETED by this handoff:** `_pending_stream_resume` / `_pending_connector_halt` /
`_pending_connector_halt_reason` fields (`live_trading_system.py:215-218`); the flag-flip callbacks
`_on_venue_stream_up`/`_request_connector_halt` bodies become CONTROL-event emitters; the engine-thread
drains `_maybe_resume_after_reconnect`/`_maybe_halt_after_connector_fatal` migrate INTO
`StreamRecoveryHandler.on_reconnect` / `SafetyController.halt` (reached by routing, not by per-tick
polling); the two `LiveRunner` injected hooks `resume_after_reconnect`/`halt_after_connector_fatal` and
their 4 call sites (`live_runner.py:161-166, 171-175`) are removed.

### Pattern: pure state machine + thin facade delegators

**What:** `SafetyController` owns state; `LiveTradingSystem` keeps `halt`/`pause_submission`/`reset_halt`/
`get_status` as one-line delegators to the controller.
**When to use:** Every extracted method — the ~45 external construction sites and the live test suite call
the facade surface; breaking it is out of scope.
**Example (delegator shape):**
```python
# facade retains the public name, delegates to the pure controller
def halt(self, reason: str) -> None:
    self._safety.halt(reason)
def get_status(self) -> dict[str, Any]:
    return {**self._safety.status_snapshot(), 'exchange': self.exchange, ...}
```

### Pattern: msgspec CONTROL event (NOT dataclass)

```python
# Source: itrader/events_handler/events/base.py (verified msgspec.Struct base)
from typing import ClassVar
from .base import Event
from itrader.core.enums import EventType

class StreamStateEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.STREAM_STATE
    stream_name: str
    up: bool                      # True=reconnected, False=disconnected

class ConnectorFatalEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.CONNECTOR_FATAL
    reason: str                   # fixed literal ('connector-fatal') — NEVER str(exc) (V7 scrub)
```
Register the routes through `LiveRouteRegistrar.install` (§13c) — the registrar already documents the
CONTROL routes as "populate when their consumers land" (`route_registrar.py:102-105`). List order =
execution order; these are new SET entries, not appends.

### Anti-Patterns to Avoid
- **Putting any venue I/O in `SafetyController`.** `catch_up_missed_fills`/`snapshot`/`backfill` live in
  `StreamRecoveryHandler` (engine thread) or loop-native — never the pure controller (§11a).
- **Running `backfill_on_resume` on the engine thread.** It is a second concurrent ring writer — a
  single-writer-contract violation. Must land loop-native via the reconnect callback (CF-2).
- **Re-exporting the safety modules from a barrel** (`trading_system/__init__.py` or any `__init__`).
  The whole live stack is lazy-imported inside `build_live_system` only; a barrel re-export pulls it onto
  the backtest import graph and breaks `test_okx_inertness.py`.
- **Leaking `str(exc)` / connector payload across any halt handoff.** Only fixed reason literals cross
  (T-05-01/V7). Preserved verbatim in every donor body.
- **Normalizing indentation.** See Pitfall 2 — mixed tab/space per target file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate window | Token bucket / fixed window | `deque` of timestamps, prune-left off injected clock | D-04 decided; deque is the codebase idiom (26 prod usages); deterministic, no refill math |
| "What counts as protective" | New predicate in the throttle | The shared `OrderRiskRole.classify()` (D-05/D-16) | One source of truth; gate + throttle both import it — throttle physically can't touch a stop/cancel |
| Halt idempotency | New winner flag | Extract `_update_status` winner-only check-and-set verbatim | Already correct (WR-01); re-implementing risks a double-alert/double-durable-write |
| Durable halt survival | New persistence | `HaltRecordStore.record_halt/has_unresolved/get_unresolved/resolve_all` `[VERIFIED: halt_record_store.py:97-141]` | Already the durable spine |
| CONTROL preemption | Manual priority | `PriorityEventBus` — STREAM_STATE/CONNECTOR_FATAL already CONTROL-tier `[VERIFIED: bus.py:48-50]` | Bus already does the tiering |
| Order rejection egress | New reject path | `FillEvent.new_fill('REFUSED', order, ...)` `[VERIFIED: fill.py:94]` | Same path `EnhancedOrderValidator` uses; mirror reconciles REFUSED→REJECTED |

**Key insight:** Almost nothing in P7 is net-new logic. The only genuinely new code is the
`PreTradeThrottle` (sliding window + notional check) and the two CONTROL event classes; everything else is
code-motion of already-correct, already-tested bodies.

## Runtime State Inventory

> This is a code-structure refactor (extraction), not a data rename. No stored data / keys / OS
> registrations change. Reviewed all five categories explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no DB keys, collection names, or user_ids change. Durable halt records persist `HaltReason.value` wire strings which are UNCHANGED (`system.py:85` note: "no data migration"). | None |
| Live service config | None — no external UI/venue config embeds a renamed string. Throttle caps are new config with defaults, not a rename. | None |
| OS-registered state | None — no Task Scheduler / systemd / pm2 names touched. | None |
| Secrets/env vars | None — new `config/safety.py` reads no secrets; throttle caps are static defaults (D-14: no runtime env wiring in P7). | None |
| Build artifacts / imports | New `trading_system/safety/` subpackage + `config/safety.py` + two event classes. Risk: an accidental barrel re-export pulls the live stack onto the backtest graph. | Verify `test_okx_inertness.py` after; keep all safety imports lazy inside `build_live_system` |

**Nothing found in 4 of 5 categories — verified by grep of the extraction surface.** The only build-side
concern is the import-inertness contract (covered under Pitfalls + Validation).

## Common Pitfalls

### Pitfall 1: CONTROL event classes must be msgspec.Struct, not @dataclass
**What goes wrong:** Authoring `StreamStateEvent`/`ConnectorFatalEvent` as `@dataclass(frozen=True)` per
CLAUDE.md's stale description; they won't share the `Event` base and `_dispatch` route lookup / bus
tiering will mis-handle them.
**Why it happens:** CLAUDE.md says "frozen dataclasses"; the events package actually migrated to
`msgspec.Struct(frozen=True, kw_only=True, gc=False)` with `type: ClassVar[EventType]` (`base.py:21`,
`error.py:21`).
**How to avoid:** Subclass `Event` as msgspec.Struct exactly like `ErrorEvent`. Place in a new
`events_handler/events/control.py` (or `market.py`-style domain file) and export from the events barrel
ONLY on the live-reachable path (they're already CONTROL-routed; the backtest never constructs them).
**Warning sign:** `TypeError: cannot inherit frozen dataclass from non-frozen` or a route KeyError.

### Pitfall 2: Per-file tab/space indentation — the `OrderRiskRole` home is TAB-indented
**What goes wrong:** Adding `OrderRiskRole` to `core/enums/order.py` with 4-space indentation → a mixed-
indentation diff that breaks the file. CLAUDE.md claims `core/` is 4-space, but `core/enums/order.py` is
**TAB-indented** `[VERIFIED: order.py:92-100 lead chars = '\t']`.
**Why it happens:** The convention is per-file, and `order.py` predates the space-indented core modules.
**How to avoid:** Measure bytes per target file before editing (MEMORY: "measure bytes per file, never
generalize"):
- `core/enums/order.py` (OrderRiskRole enum) → **TABS**
- `config/safety.py` (new) → **4 SPACES** (config convention)
- `trading_system/safety/*.py` (new) → **4 SPACES** (matches the `live_trading_system.py` donor + the
  4-space `route_registrar.py`/`live_runner.py` siblings — all explicitly 4-space)
- `trading_system/live_runner.py` edits → **4 SPACES**
- `portfolio_handler/reconcile/*.py` (ReconciliationCoordinator) → verify (venue_reconciler.py) before edit
**Warning sign:** `git diff` shows whole-block re-indentation; `filterwarnings=["error"]` unaffected but
the file breaks.

### Pitfall 3: Deleting the flag side-channel forces a LiveRunner constructor change
**What goes wrong:** Treating the flag deletion as facade-local; the two `LiveRunner` hooks
`resume_after_reconnect`/`halt_after_connector_fatal` (injected + called at `live_runner.py:161-166,
171-175`) still poll the (now-deleted) drains and either crash or no-op silently.
**Why it happens:** `live_runner.py` was designed for P7 to "fill in without re-touching" (docstring), but
that assumed adding CONTROL routes, not removing the per-tick polling. Removing the flags removes the
poll → the two injected callables + their 4 call sites must go, and `build_live_system:1688-1689` stops
passing them.
**How to avoid:** Plan the LiveRunner edit explicitly as part of SAFE-03. The `dispatch_gate` injection
(→ `SafetyController.gate_and_dispatch`) stays; the two resume/halt drains are deleted.
**Warning sign:** A reconnect during a quiet spell no longer resumes (the queue-empty drain was the only
path for idle resume) — now handled because CONTROL events wake `bus.get()` naturally.

### Pitfall 4: CF-2 — engine thread must never reach the ring writer
**What goes wrong:** `StreamRecoveryHandler.on_reconnect` (engine thread) calls
`LiveBarFeed.backfill_on_resume` → `_backfill_gap` → `update()` → `ring.append` while the connector loop
is also writing the ring on the resumed stream = concurrent writers, single-writer-contract violation.
**Why it happens:** The natural reading of "resume recovery" bundles fills + snapshot + backfill into one
engine-thread method.
**How to avoid:** Split it exactly as the spec/CF-2 says. Engine-thread `on_reconnect` does ONLY
`catch_up_missed_fills()` + `account.snapshot()` + the health gate. The REST ring backfill lands
**loop-native** via the reconnect callback (`okx_provider.spawn_gap_backfill` pattern,
`okx_provider.py:622`) on the connector loop. Add the required **assertion that no engine-thread path
reaches the ring writer** (`LiveBarFeed` already has a `_replaying_backfill` guard, `live_bar_feed.py:113`
— assert current-thread ≠ engine, or gate on it).
**Warning sign:** Duplicate/interleaved bars in the ring; `test_reconnect_resilience` flakiness.

### Pitfall 5: Import inertness — the backtest oracle must stay byte-exact and dark
**What goes wrong:** A barrel re-export of `SafetyController`/`StreamRecoveryHandler` from
`trading_system/__init__.py`, or a module-top `import` of a safety module in a backtest-reachable file,
pulls the live stack onto the backtest import graph.
**Why it happens:** New subpackage → the reflex is to add barrel exports.
**How to avoid:** Keep every safety import lazy inside `build_live_system`'s body (the module already does
this for the whole live/venue/SQL stack, `live_trading_system.py:1453-1455`). `config/safety.py` is
pydantic-only so it MAY be an eager `SystemConfig` field like `config/stream.py` (`system.py:112`) — that
is inertness-safe (Pitfall 1 of stream.py). But `trading_system/safety/*` must NOT be barrel-exported.
**Warning sign:** `test_okx_inertness.py` fails (`ccxt`/`ccxt.pro`/`SqlSettings` on the import graph);
`test_backtest_oracle.py` drifts from `134 / 46189.87730727451`.

### Pitfall 6: The dispatch-gate risk-classification predicate must become the shared classifier
**What goes wrong:** Two copies of "CANCEL/PROTECTIVE/ENTRY" logic — one in the extracted
`gate_and_dispatch`, one re-written in the throttle — drift apart, and the throttle meters a protective
order (D-05 violation → could reject a stop).
**Why it happens:** The classification is currently inline in `_dispatch_live` (`live_trading_system.py:
741-765`): `command is OrderCommand.CANCEL` → CANCEL; `type is ORDER and parent_order_id is not None` →
PROTECTIVE; else → ENTRY.
**How to avoid:** Extract it ONCE as `OrderRiskRole.classify(event)` (enum in `core/enums/order.py`,
`classify()` travels with `SafetyController` per D-16). Both `gate_and_dispatch` and `PreTradeThrottle`
import the single predicate. Throttle meters `ENTRY` only; CANCEL/PROTECTIVE bypass uncounted.
**Warning sign:** A bracket child or cancel gets a `FillEvent(REFUSED)` from the throttle.

### Pitfall 7: D-11 overflow→halt is the ONE behavior change in an otherwise byte-identical extraction
**What goes wrong:** Extracting the deferred-protective queue verbatim keeps the silent drop-oldest
(`deque(maxlen=1000)` at `live_trading_system.py:220`); or over-reaching and changing other bodies.
**Why it happens:** "Extract as-is" and "change overflow policy" are competing instructions.
**How to avoid:** Change ONLY the overflow branch: on append-to-full, escalate to `halt` + CRITICAL alert
instead of silent eviction. Everything else in `_replay_deferred_protective`/the append path stays
identical. Needs exactly one new test (D-11). All other extracted bodies must be byte-identical.

## Code Examples

### D-04 sliding-window throttle (recommended structure)
```python
# deque-of-timestamps, prune-left off the INJECTED clock (determinism, D-04)
from collections import deque

class _RateWindow:
    def __init__(self, max_orders: int, window_s: float, clock):
        self._max = max_orders
        self._window_s = window_s
        self._clock = clock                 # injected — never wall clock
        self._stamps: deque[float] = deque()

    def would_breach(self) -> bool:
        now = self._clock.now_monotonic()   # or business time per clock seam
        cutoff = now - self._window_s
        while self._stamps and self._stamps[0] < cutoff:
            self._stamps.popleft()
        return len(self._stamps) >= self._max

    def record(self) -> None:               # called ONLY on a metered ENTRY that passed
        self._stamps.append(self._clock.now_monotonic())
```

### CF-7 typed fail-loud guard (replaces bare `str(matched["id"])`)
```python
# Source site: venue_reconciler.py:411  venue_id = str(matched["id"])
# Recommend a typed error subclassing ITraderError (core/exceptions/base.py hierarchy)
class ReconciliationError(ITraderError):        # or reuse StateError with fields
    """A venue resting-order payload is missing/uncoercible where reconciliation needs an id."""

raw_id = matched.get("id")
if raw_id is None:
    raise ReconciliationError(
        f"venue resting order for leg {child.internal_id} has no 'id' — cannot re-link OCO")
venue_id = str(raw_id)
```

### D-09 breach observability — de-duped WARNING ErrorEvent (recommended)
```python
# min-interval dedup off the injected clock (deterministic; a burst can't flood the ERROR route)
if self._clock.now_monotonic() - self._last_warn_ts >= self._warn_min_interval_s:
    self._last_warn_ts = self._clock.now_monotonic()
    self._bus.put(ErrorEvent(
        time=..., source='pre_trade_throttle', error_type='ThrottleBreach',
        error_message='order rejected: submit-rate/notional cap exceeded',
        operation='pre_submit', severity=ErrorSeverity.WARNING))
self._breach_count += 1     # always increment the read-model counter (P9 UI, D-09)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Connector→engine via `threading.Event` flags polled per tick | CONTROL events on `PriorityEventBus`, routed on engine thread | P7 (this phase) | Deletes flag side-channel; wakes `bus.get()` naturally; CONTROL preempts market data |
| Safety logic inline in the `LiveTradingSystem` God object | Pure `SafetyController` + `StreamRecoveryHandler` + `ReconciliationCoordinator` collaborators | P7 | Independently unit-testable; facade shrinks to thin delegators |
| Deferred-protective overflow = silent drop-oldest | Overflow → HALT + CRITICAL | P7 (D-11) | Loud, latched — a dropped protective order is unacceptable |
| Frozen `@dataclass` events | `msgspec.Struct` events | pre-P7 (already done) | CLAUDE.md text is stale; author new events as msgspec |

**Deprecated/outdated:**
- CLAUDE.md "frozen dataclasses" for events → actually `msgspec.Struct`.
- CLAUDE.md "`core/` uses 4 spaces" → `core/enums/order.py` is TABS (per-file rule wins).
- CONTEXT.md line numbers (`735-765` gate, `215-221`/`600-720` flags) → drifted; see Verified Boundaries.
- Design spec §16 labels this work "**P8**"; the ROADMAP/CONTEXT/REQUIREMENTS call it **Phase 7**. The
  spec's phase numbering is offset by one — the §11 content IS this phase. Do not be misled by "P8" in
  §16/§11 cross-references.

## Verified Extraction Boundaries (live_trading_system.py, current tree)

> The single most load-bearing research output. CONTEXT.md numbers had drifted; these are line-verified
> this session against the 1700-line file. `[VERIFIED: read this session]`

| Method / field | Lines | Destination | Notes |
|----------------|-------|-------------|-------|
| `_run_session_baseline_guard` | 349–398 | `ReconciliationCoordinator` | baseline guard arm; fixed halt literal |
| `halt` | 400–464 | `SafetyController` | winner-only; CRITICAL ErrorEvent; durable `record_halt` |
| `_is_halted` | 466–469 | `SafetyController` | |
| `reset_halt` | 471–512 | `SafetyController` | sole off-table exit (`force=True`); `resolve_all` |
| `_is_submission_paused` | 514–517 | `SafetyController` | |
| `pause_submission` | 519–545 | `SafetyController` | thread-safe locked flag flip |
| `resume_submission` | 547–565 | `SafetyController` | clears pause → replay deferred-protective |
| `_replay_deferred_protective` | 567–584 | `SafetyController` | snapshot-then-clear drain |
| `_on_venue_stream_down` | 586–594 | **rewrite** → emits `StreamStateEvent(down)` | connector-loop callback |
| `_on_venue_stream_up` | 596–605 | **rewrite** → emits `StreamStateEvent(up)` | was: set `_pending_stream_resume` flag |
| `_maybe_resume_after_reconnect` | 607–666 | `StreamRecoveryHandler.on_reconnect` | engine-thread I/O; catch-up + snapshot + health gate |
| `_all_venue_streams_healthy` | 668–684 | `StreamRecoveryHandler` | None arm = healthy |
| `_request_connector_halt` | 686–703 | **rewrite** → emits `ConnectorFatalEvent(reason)` | was: set `_pending_connector_halt` flag |
| `_maybe_halt_after_connector_fatal` | 705–722 | folds into `ConnectorFatalEvent` route → `SafetyController.halt` | drain deleted |
| `_dispatch_live` (gate) | 724–766 | `SafetyController.gate_and_dispatch(event, dispatch_fn)` | risk classification 741–765 → `OrderRiskRole.classify` |
| `_update_status` | 768–834 | `SafetyController` | THE single mutation seam; WR-01 atomic |
| `_notify_status_change` | 836–862 | `SafetyController` (or facade callback) | runs outside lock |
| flag fields `_pending_stream_resume`/`_pending_connector_halt`/`_pending_connector_halt_reason` | 215–218 | **DELETE** | replaced by CONTROL events |
| `_submission_paused`/`_paused_reason` | 213–214 | `SafetyController` | pause state |
| `_deferred_protective` deque | 219–221 | `SafetyController` | maxlen=1000; overflow→halt (D-11) |
| durable-halt refusal gate (in `start()`) | 1013–1030 | `SafetyController.check_durable_halt_on_start()` | runs FIRST, before venue I/O; re-latch via `update_status` |
| rehydrate→reconcile block (in `start()`) | 1124–1165 | `ReconciliationCoordinator` | key on account *kind* not `exchange=='okx'` (CF-7/§11d) |
| `_link_venue_account_to_portfolios` | 314–347 | stays facade or ReconciliationCoordinator | fail-loud >1 portfolio |
| wiring `set_stream_state_listener`/`set_halt_signal` (build_live_system) | 1652–1660 | **rewrite** → callbacks emit CONTROL events | 3 call sites (provider, okx_exchange, okx_connector) |
| LiveRunner hook injection | 1688–1689 | **DELETE** `resume_after_reconnect`/`halt_after_connector_fatal` | see Pitfall 3 |

**ReconciliationCoordinator "key on account kind" (CF-7/§11d):** the `Account` ABC (`account/base.py:35`)
has **no `kind` discriminator today** `[VERIFIED]`. The venue reconcile currently runs gated on
`self._venue_account is not None and hasattr(self._order_storage,'rehydrate')` (`start():1128,1143`) — a
proxy for "OKX arm." The coordinator should key on a venue-truth discriminator (VenueAccount vs
Simulated*Account) — either add an `is_venue_truth` property to the `Account` ABC or `isinstance` check —
so paper/simulated never reaches the venue reconcile (matches current D-23 RESTORE-only behavior).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CF-7 typed error should be a new `ReconciliationError(ITraderError)` (Claude's discretion; spec says only "typed fail-loud error") | Code Examples | Low — planner/owner may prefer reusing `StateError`; either satisfies CF-7 |
| A2 | D-09 dedup via min-interval off the injected clock (Claude's discretion) | Code Examples | Low — first-breach-edge is an equally valid choice; both flood-guard |
| A3 | Throttle seam = a second runner-invoked `pre_submit(event)->bool` callable at the ORDER→execution boundary (D-06 says "invoked by the runner," exact mechanism is discretion) | Validation / Don't-Hand-Roll | Med — if the planner instead wraps the ORDER route consumer, the wiring differs; both honor "before submission" + shared classifier |
| A4 | `is_venue_truth` discriminator on `Account` is the clean way to key the coordinator on "kind" | Verified Boundaries | Low — `isinstance(VenueAccount)` also works; ABC has no kind field today |
| A5 | New CONTROL events go in a new `events_handler/events/control.py` module | Patterns | Low — file placement, not behavior |

**No assumptions touch a locked D-decision, compliance, retention, or a security control.** The five
above are all Claude's-discretion mechanism choices the planner/owner confirms.

## Open Questions

1. **Exact throttle placement mechanism (A3).**
   - What we know: D-06 = pre-submit boundary, invoked by the runner, shares `OrderRiskRole` with the
     gate, NOT in `gate_and_dispatch`, NOT in OrderHandler admission. ORDER route =
     `execution_handler.on_order` (`full_event_handler.py:100`). The runner calls `dispatch_gate(event)`
     per event (`live_runner.py:147`).
   - What's unclear: whether the throttle is (a) a distinct `pre_submit(event)->bool` callable the runner
     invokes for ORDER events ahead of `dispatch_gate`, rejecting via `FillEvent(REFUSED)` and skipping
     dispatch; or (b) a filter composed into the dispatch path.
   - Recommendation: (a) — a separate injected runner callable keeps the pure `SafetyController` free of
     notional inspection (D-06 intent) and mirrors how `dispatch_gate` is already injected. Planner to
     confirm.

2. **Where the D-09 breach counter surfaces in the read-model.**
   - What we know: D-09 wants a counter in `get_status()`/read-model for P9's UI. `get_status()` is at
     `live_trading_system.py:1289`.
   - What's unclear: whether the counter lives on the throttle (read via a delegator) or is threaded into
     the status snapshot dict.
   - Recommendation: counter on `PreTradeThrottle`; facade `get_status()` reads it via a thin accessor
     (shapes the P9 stats seam without wiring runtime mutation, D-14).

## Environment Availability

No external tools/services required — this is a pure-code refactor executed with the existing Poetry
`.venv`. Gates run via `poetry run pytest`. `SKIPPED` for external-dependency probing.

## Project Constraints (from CLAUDE.md)

- **Queue-only cross-domain writes**; read-model seams for reads. CONTROL routing keeps this — connector
  callbacks emit events, they do not call handlers.
- **Money is Decimal end-to-end**; `float()` only at the serialization edge. The throttle's max-notional
  math is Decimal (limit price / mark). `[from CLAUDE.md — authoritative]`
- **Event-driven dispatch**: adding an event type = define frozen struct + `EventType` member + route
  branch. Members + routes already exist; only the classes + route wiring are new here.
- **Live-stack inertness**: the live stack stays lazy-imported, never re-exported from barrels.
- **Per-file indentation** (see Pitfall 2) — tabs in handler modules + `core/enums/order.py`; 4 spaces in
  `config/`, `trading_system/` new+live modules, events package. Match the file; never normalize.
- **Determinism**: injected clock + seeded RNG. The sliding window reads the injected clock.
- **`filterwarnings=["error"]` + `--strict-markers`/`--strict-config`**: any stray warning fails the
  suite; new markers must be declared (none needed — reuse `unit`/`integration`).
- **Decision tags are load-bearing** in module/method docstrings — carry `SAFE-0x`/`D-xx`/`CF-x` tags into
  the extracted code.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SAFE-01 | Pure `SafetyController` (status latch, halt/pause/resume, deferred-protective queue, dispatch gate) | Verified Boundaries rows 349–862 + fields 213–221; all pure (no venue I/O) → extract verbatim except D-11 |
| SAFE-02 | `check_durable_halt_on_start()` runs first, refuses RUNNING on unresolved durable halt, re-latch via `update_status` | Boundary row 1013–1030; `HaltRecordStore.has_unresolved/get_unresolved` verified (`halt_record_store.py:116-127`) |
| SAFE-03 | Connector up/down/fatal as CONTROL events; flag side-channel deleted | CONTROL handoff diagram; EventType members + empty routes verified; callbacks 586–722 + wiring 1652–1660; LiveRunner hooks deleted (Pitfall 3) |
| SAFE-04 | `StreamRecoveryHandler` resume I/O; CF-2 backfill loop-native; no engine-thread ring writer | Boundary rows 607–684; `catch_up_missed_fills`/`snapshot`/`is_streaming_healthy` verified; CF-2 split (Pitfall 4); `backfill_on_resume` at `live_bar_feed.py:392` |
| SAFE-05 | `ReconciliationCoordinator` keyed on account kind; CF-7 typed guard | Boundary rows 1124–1165 + 349–398; CF-7 site `venue_reconciler.py:411` verified; kind discriminator note (A4) |
| SAFE-06 | Pre-trade submit-rate + max-notional throttle, rejects before submission | D-01..D-10; sliding-window + FillEvent(REFUSED) examples; `OrderRiskRole` from gate 741–765; placement OQ1/A3 |

## Sources

### Primary (HIGH confidence — read this session)
- `itrader/trading_system/live_trading_system.py` (1700 lines) — all extraction boundaries line-verified
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §11a–e, §4a–c, §8d, §12, §13c, CF table (CF-2 line 662)
- `itrader/trading_system/{live_runner,route_registrar}.py`; `itrader/events_handler/{full_event_handler,bus}.py`; `itrader/events_handler/events/{base,error,fill}.py`
- `itrader/core/enums/{system,event,order}.py` (HaltReason, EventType, OrderCommand + order.py tab-indent verified)
- `itrader/config/{stream,order,system}.py` (config convention); `itrader/portfolio_handler/reconcile/venue_reconciler.py:411` (CF-7); `itrader/price_handler/feed/live_bar_feed.py:392` (CF-2)
- `itrader/storage/halt_record_store.py` (API); `itrader/portfolio_handler/account/base.py` (no kind field)
- `.planning/phases/07-.../{07-CONTEXT.md,07-DISCUSSION-LOG.md}`; `.planning/REQUIREMENTS.md` SAFE-01..06; `.planning/config.json` (nyquist_validation=true)

### Secondary / Tertiary
- None — no web/external sources; internal-codebase phase.

## Validation Architecture

> Nyquist validation is ENABLED (`.planning/config.json: workflow.nyquist_validation = true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/trading_system -x` (per-task; pure controller is fast) |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — MEMORY: `.env` abort) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SAFE-01 | Pure `SafetyController` state machine in isolation (latch transitions, winner-only halt, pause/resume, deferred-protective replay) | unit | `poetry run pytest tests/unit/trading_system/test_safety_controller.py -x` | ❌ Wave 0 (new; `test_pause_defer_replay.py` exists to port from) |
| SAFE-01 (D-11) | Deferred-protective overflow → HALT + CRITICAL (not silent drop) | unit | `poetry run pytest tests/unit/trading_system/test_safety_controller.py -k overflow -x` | ❌ Wave 0 (new test, D-11) |
| SAFE-02 | Durable-halt-on-start refuses RUNNING inert, re-latch no second durable write | integration | `poetry run pytest tests/integration/test_early_durable_halt_refusal.py tests/integration/test_durable_halt.py -x` | ✅ (repoint to controller) |
| SAFE-03 | STREAM_STATE(down/up) + CONNECTOR_FATAL route on engine thread; flags gone | integration | `poetry run pytest tests/integration/test_live_system_okx_wiring.py -k "control or stream_state or fatal" -x` | ❌ Wave 0 (new CONTROL-route test) |
| SAFE-04 | Reconnect resume: catch-up + snapshot + all-streams-healthy gate → resume; CF-2 loop-native; **assert no engine-thread ring writer** | integration | `poetry run pytest tests/integration/test_resume_missed_fill_catchup.py tests/integration/test_resume_gated_on_all_streams.py -x` | ✅ (extend with the ring-writer-thread assertion) |
| SAFE-05 | Coordinator keyed on account kind; CF-7 typed error on missing/uncoercible `matched["id"]` | unit + integration | `poetry run pytest tests/unit/portfolio/ -k reconcil -x` and `tests/integration/test_okx_sandbox_recon.py` (e2e, `live`) | ❌ Wave 0 (CF-7 guard test new) |
| SAFE-06 | Throttle rejects ENTRY over rate/notional → FillEvent(REFUSED); CANCEL/PROTECTIVE bypass uncounted; breach counter + de-duped WARNING | unit | `poetry run pytest tests/unit/trading_system/test_pre_trade_throttle.py -x` | ❌ Wave 0 (new) |
| Gate | Backtest oracle byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ |
| Gate | Import inertness | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/trading_system -x` (pure-controller + throttle units; sub-second).
- **Per wave merge:** the SAFE-0x integration set above + both gate tests.
- **Phase gate:** `make test` full suite green + `test_backtest_oracle.py` (`134 / 46189.87730727451`) + `test_okx_inertness.py` before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/trading_system/test_safety_controller.py` — SAFE-01 pure-machine isolation (port assertions from `test_pause_defer_replay.py`; add D-11 overflow→halt case)
- [ ] `tests/unit/trading_system/test_pre_trade_throttle.py` — SAFE-06 (sliding window off a fake clock, notional via Decimal, ENTRY-only metering, REFUSED egress, breach counter, WARNING dedup)
- [ ] `tests/unit/core/test_order_risk_role.py` — the shared `OrderRiskRole.classify` (CANCEL/PROTECTIVE/ENTRY) reused by gate + throttle (D-05/D-16)
- [ ] `tests/integration/` CONTROL-route test — SAFE-03 (connector callback puts StreamStateEvent/ConnectorFatalEvent; engine-thread route reaches SafetyController/StreamRecoveryHandler; flags absent)
- [ ] Extend `test_resume_*` with the **CF-2 assertion**: no engine-thread path reaches `LiveBarFeed.update`/ring writer during resume
- [ ] `tests/unit/portfolio/` CF-7 test — typed error on missing/uncoercible `matched["id"]`
- [ ] Framework install: none (existing infra covers all)

## Security Domain

> `security_enforcement` not present in `.planning/config.json` → treated as enabled. This is a
> money-handling live-trading safety subsystem — security is directly relevant.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface added; connector creds owned by the connector (unchanged) |
| V3 Session Management | no | — |
| V4 Access Control | yes | Fail-closed posture preserved: `add_event` default-deny (unchanged); throttle is a default-deny risk backstop (reject over-cap ENTRY) |
| V5 Input Validation | yes | Throttle validates notional/rate on inbound order flow before submission; `OrderCommand`/`OrderRiskRole` typed classification; CF-7 typed guard on venue payload `matched["id"]` |
| V6 Cryptography | no | — |
| V7 Error/Log — secret scrub | yes | **Load-bearing**: halt/pause/CONTROL handoffs bind ONLY fixed reason literals + declared ErrorEvent fields — NEVER `str(exc)` or connector payload (T-05-01). Preserve verbatim in every extracted body |
| V11 Business Logic | yes | Winner-only halt (no double-alert/double-durable-write); latched HALTED with sole `reset_halt` exit; throttle as a runaway-strategy / fat-finger backstop (D-01) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Connector secret/exception leaking into a halt reason or ErrorEvent | Information Disclosure | Fixed reason literals only; declared-field bind (V7 scrub); carry the discipline into extracted bodies |
| Auto-restart silently clearing a breaker halt | Tampering / EoP | `check_durable_halt_on_start` refuses RUNNING inert on an unresolved durable record (SAFE-02) |
| Concurrent ring writers on reconnect corrupting the bar stream | Tampering | CF-2 loop-native backfill + no-engine-thread-ring-writer assertion (Pitfall 4) |
| Runaway strategy / bad loop / fat-finger flooding orders | DoS / financial | SAFE-06 pre-trade rate + notional caps (default 10/10s + $25k), reject-that-order |
| Silent drop of a protective order leaving a position naked | Tampering (safety) | D-11 overflow → HALT + CRITICAL instead of silent drop-oldest |
| Unrouted/unknown CONTROL event silently dropped | Tampering | `_dispatch` raises `NotImplementedError` on an unrouted type (`full_event_handler.py`); routes registered via `LiveRouteRegistrar` |

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all facilities line-verified in the tree.
- Architecture / boundaries: HIGH — every extraction boundary read this session; spec §11 is the locked source.
- Pitfalls: HIGH — msgspec-vs-dataclass, tab/space order.py, LiveRunner hook deletion, CF-2 ring writer, inertness all verified against code.
- Discretion items (CF-7 error / D-09 dedup / D-04 window): MEDIUM — recommendations grounded in codebase prior-art; final mechanism is planner/owner choice (A1–A3).

**Research date:** 2026-07-14
**Valid until:** ~2026-08-13 (stable internal code; re-verify boundary line numbers if `live_trading_system.py` is touched before planning — it drifts).
