# Phase 2: Event Bus - Research

**Researched:** 2026-07-09
**Domain:** stdlib event-bus substrate + `compose_engine` end-state signature settlement (oracle-gated foundation refactor)
**Confidence:** HIGH — every claim below verified against the current code in this session (line numbers re-confirmed, not trusted from CONTEXT.md)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** `compose_engine` settles to the design's **end-state two-arg form `compose_engine(ctx, spec)`** (spec §5) — reached in P2 so it is **never re-edited** downstream. Option B, chosen over the minimal "prepend `ctx`, keep the 8 kwargs" form. The backtest factory builds `FifoEventBus` + `EngineContext` and injects it; the internal `queue.Queue()` at `compose.py:164` is **deleted**.
- **D-02:** Storage placement = **handlers own their storage init** (spec §7b / LR-13). Order + Strategies handlers adopt `PortfolioHandler`'s **existing** shape (`OrderHandler(..., *, environment, sql_engine, storage=None) → self.storage = storage or OrderStorageFactory.create(environment, backend=sql_engine)`); `compose_engine` reads the concrete back off `.storage` for the `portfolio_handler.set_order_storage(...)` wiring. **Backtest slice only** — `environment='backtest', sql_engine=None` → same in-memory instances as today → byte-exact. **Rejected:** B2 (backend instances on `SystemSpec`) and B3 (hybrid `(ctx, spec, *, order_storage, signal_store)`).
- **D-03 (PHASING SHIFT):** P2 absorbs CTX-01 (`compose_engine(ctx, spec)`), CTX-02 (storage-in-handler), CTX-03 (backtest byte-exact + lazy-SQL-inertness gate). **P3 shrinks to just CTX-04** (`SqlBackend→SqlEngine` rename). **Downstream must NOT "fix" this back.** Traceability already updated (done 2026-07-09).
- **D-04:** kwargs→spec fold is **mostly 1:1 with existing `SystemSpec` fields** — `csv_paths→data`, `start_date→start`, `end_date→end`, `timeframe→timeframe`, `exchange_config←exchange`, `results_store→results_store`. The **one** kwarg without a spec field is `order_config`; planner decides keep it **handler-owned** via `OrderConfig.default()` (leaned) or add a spec field.
- **D-05:** Frozen `EngineContext` dataclass with **all 4 fields now**: `bus: EventBus`, `config`, `environment: str`, `sql_engine`. `bus`/`environment`/`sql_engine` actively consumed in P2; `config` carried but **unread until P9**. **Loose types**: `config` = today's `SystemConfig`; `sql_engine: Optional[...] = None`. **P3/P4/P9 only tighten types — never add fields.**
- **D-06:** Backtest factory constructs `EngineContext(bus=FifoEventBus(), config=<the SystemConfig>, environment='backtest', sql_engine=None)`. `sql_engine=None` + `FifoEventBus` pull nothing heavy → inertness gate stays green.
- **D-07:** **Full bus swap** — every handler constructor that takes `global_queue` now receives the `FifoEventBus` in its place (duck-typed `.put()`, **no `.put` call-site changes**, BUS-01); `EventHandler` drains via `bus.get_nowait()`/`bus.empty()`. `FifoEventBus` is a thin wrapper over `queue.Queue` → **byte-identical FIFO** → oracle safe. Boundary-only wrapping rejected.
- **D-08:** Constructor **parameter name stays `global_queue`/`events_queue`** (CLAUDE.md naming convention) — **retyped** to `EventBus`. Do NOT rename the param to `bus`.
- **D-09:** Protocol surface = `put`, `get(timeout)`, `get_nowait`, `qsize`, `empty`, `depth_by_tier` (§4a). `bus.py` lives at `itrader/events_handler/bus.py`, **4-space indent** (events-package convention, NOT tabs).
- **D-10:** P2 = **define `PriorityEventBus` + unit-test only** (Option 1). Ship: `PriorityEventBus` (`PriorityQueue` keyed `(tier, seq, event)`; `tier ∈ {CONTROL=0, BUSINESS=1}` from `_CONTROL_EVENT_TYPES`; `seq = itertools.count()`); the BUS-02 ordering test; 3 new CONTROL `EventType`s; `_CONTROL_EVENT_TYPES`.
- **D-11:** **ZERO live wiring in P2** — `live_trading_system.py` stays untouched on its raw `queue.Queue` until P6/P7. **Option 2 (wire live now) explicitly rejected.**

### Tier assignment (finalize in P2)
- **CONTROL** (preempts market data): `STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`, `STRATEGY_COMMAND`.
- **BUSINESS** (strict FIFO): `BAR`, `SIGNAL`, `ORDER`, `FILL`, `UNIVERSE_*`, `BARS_*`, `ERROR`, `PORTFOLIO_UPDATE` (+ existing `TIME`/`UPDATE`/`ORDER_ACK`/`SCREENER`). **Externally-injected `SIGNAL`s stay BUSINESS.**

### Claude's Discretion
- The `EngineContext` class **home/module** (near `compose_engine` in `trading_system/`, or `events_handler/` — pick to avoid an import cycle with `EventBus`).
- `FifoEventBus.depth_by_tier` exact shape (FIFO is tierless — a single-bucket mapping such as `{BUSINESS: qsize}` is fine; must satisfy the Protocol).
- Whether to add an **optional standalone integration test** driving a representative CONTROL+BUSINESS interleaving through `PriorityEventBus` (no `live_trading_system.py` touch).
- `order_config` home under the fold (D-04) — leaned handler-owned per P1 D-03.

### Deferred Ideas (OUT OF SCOPE)
- REQUIREMENTS.md / ROADMAP.md traceability update (D-03) — ✅ already done 2026-07-09.
- Wiring `PriorityEventBus` into the live system — P6/P7.
- `RuntimeConfig` overlay — P9 (`EngineContext.config` is a loose placeholder until then).
- `SqlBackend→SqlEngine` rename + migrations relocation — P3/P4.
- `order_config` onto `SystemSpec` — only if the planner rejects the handler-owned lean.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BUS-01 | `EventBus` Protocol (`put`/`get`/`get_nowait`/`qsize`/`empty`/`depth_by_tier`) + `FifoEventBus`/`PriorityEventBus` sharing one `.put()`; no handler `.put` call-site changes | Protocol surface + drain interaction verified (`full_event_handler.py:125-130`); `queue.Queue` supplies `put/get/get_nowait/qsize/empty` natively, `FifoEventBus` adds `depth_by_tier` |
| BUS-02 | `PriorityEventBus` orders `(tier, seq, event)`; test proves tuple comparison never dereferences the non-orderable event + strict within-tier FIFO | **Verified live:** `Event` (msgspec.Struct) raises `TypeError` on `<`; unique `itertools.count()` `seq` guarantees the heap never compares events (ran the harness — see Code Examples) |
| BUS-03 | 3 new CONTROL `EventType` members (`STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`); backtest uses `FifoEventBus` | `EventType` current members enumerated (`core/enums/event.py:23-36`); string-valued enum, `_missing_` case-insensitive parse — the 3 slot alongside the v1.7 members |
| BUS-04 | Minimal `EngineContext` skeleton so `compose_engine` settles once | `EngineContext` 4-field shape from spec §7a; frozen-dataclass convention confirmed |
| CTX-01 | `EngineContext` threaded once into `compose_engine(ctx, spec)`; infra-only | Two call sites found (`__init__:131`, `build_backtest_system:437`) — **both** must fold to `(ctx, spec)`; see Common Pitfall 1 |
| CTX-02 | Order + Strategies handlers own storage init from `(environment, sql_engine)` w/ `storage=` override; `compose_engine` reads `.storage` back for wiring | `PortfolioHandler.__init__:68-81` is the exact template; `OrderStorageFactory.create(env, backend=)` + `SignalStorageFactory.create(env, backend=)` signatures verified |
| CTX-03 | Backtest (`environment='backtest', sql_engine=None`) → same in-memory instances → oracle byte-exact; factory SQL imports stay lazy → inertness green | Both factories return `InMemory*` for `'backtest'`/`'test'` with SQL imports lazily inside the `'live'` arm (verified) |
</phase_requirements>

## Summary

This is a **specified/mechanical, oracle-gated foundation refactor** — STATE.md explicitly flags P2 as "skip research-phase (specified)." The design contract (spec §4/§5/§7) and the eleven locked decisions (D-01..D-11) fully determine WHAT to build. This research exists purely to **de-risk EXECUTION**: it re-verifies every pinned touchpoint against the live code (the CONTEXT.md line numbers were checked and are accurate as of this session), enumerates the exact blast radius of the full-bus-swap, and proves the load-bearing stdlib invariant (the priority-queue tuple never compares two events) by running it.

The single highest-value finding: **there are TWO `compose_engine` call sites on the backtest path, and the oracle runs through the one that does NOT have a `SystemSpec`.** `scripts/run_backtest.py::main` → `BacktestTradingSystem(exchange="csv", ...)` → the *legacy direct-construction* arm (`__init__:118-141`), which builds kwargs inline, not a spec. `build_backtest_system(spec)` (`:401`) is the second site and already has a spec. Settling `compose_engine(ctx, spec)` means the legacy arm must synthesize a `SystemSpec` (with placeholder `ticker`/`starting_cash` that `compose_engine` never reads) or the planner must otherwise thread a spec into it. This is the one place where the "mostly 1:1 fold" (D-04) has a wrinkle.

The second load-bearing finding: `FifoEventBus.get_nowait()` **must raise the same `queue.Empty`** the `EventHandler` drain already catches (`full_event_handler.py:128`), and `PriorityEventBus.get*()` must **unwrap the `(tier, seq, event)` tuple and return only the event** — the drain expects a bare event, not a tuple. Both are byte-exactness-critical.

**Primary recommendation:** Implement `bus.py` first (pure, testable in isolation — `FifoEventBus`, `PriorityEventBus`, `EventBus` Protocol, `_CONTROL_EVENT_TYPES`, the 3 CONTROL `EventType`s, BUS-02 ordering test) with zero touch to any wiring; then in a second slice do the retype-not-rename bus swap + the `compose_engine(ctx, spec)` fold + `EngineContext` + handler-owned storage, gated by the oracle + inertness tests after each edit. Run the two gate tests (`test_backtest_oracle.py`, `test_okx_inertness.py`) as a per-PLAN gate.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event transport / tiered `.put()` routing | Event-transport substrate (`events_handler/bus.py`) | — | The bus is the queue-replacement bulkhead; handlers stay tier-unaware (bus assigns tier from `_CONTROL_EVENT_TYPES`) |
| Event-type vocabulary (CONTROL members) | Shared core (`core/enums/event.py`) | — | `EventType` is a cross-cutting primitive; `core` depends on nothing inside `itrader` |
| Component-graph wiring / storage back-read | Composition seam (`trading_system/compose.py`) | Backtest factory + legacy `__init__` | `compose_engine` is mode-agnostic; the factory/legacy arm selects concretes and injects the `EngineContext` |
| Handler-owned storage init | Domain handlers (order/strategies) | Storage factories | LR-13 — the handler derives its own backend from `(environment, sql_engine)`, mirroring `PortfolioHandler` |
| Queue drain / dispatch | Event dispatcher (`events_handler/full_event_handler.py`) | — | The drain switches from `queue.Queue` methods to the `EventBus` Protocol surface (`get_nowait`) |

## Standard Stack

**No new packages.** Every mechanic is Python 3.13 stdlib or already-pinned. Adding any dependency **regresses the inertness gate and violates the "no poetry change P1–P12" milestone rule** (REQUIREMENTS.md gate 2).

### Core (all stdlib — already available)
| Module | Purpose | Why Standard |
|--------|---------|--------------|
| `queue.Queue` | `FifoEventBus` internal buffer (thin wrapper) | Already THE backtest queue — byte-identical FIFO, zero oracle risk (D-07) |
| `queue.PriorityQueue` | `PriorityEventBus` internal heap | stdlib min-heap; `get/get_nowait/qsize/empty` inherited from `Queue`, `queue.Empty` raised identically |
| `itertools.count()` | Monotonic globally-unique `seq` source | Thread-safe (each `next()` is a single bytecode-atomic C call); guarantees the tuple comparison never reaches the event (D-10) |
| `typing.Protocol` | `EventBus` structural interface | Duck-typed `.put()` needs no ABC inheritance on `queue.Queue`; matches the `PortfolioReadModel`/`_AlertSinkLike` house pattern |
| `dataclasses.dataclass(frozen=True)` | `EngineContext` | Same frozen-value-object pattern used across `system_spec.py` / events |
| `enum.Enum` | 3 new `EventType` members | Existing `EventType` is a string-valued `Enum` with a `_missing_` parser (`core/enums/event.py`) |

### Installation
None. `poetry install` unchanged. **Any `poetry.lock` diff in this phase is a defect.**

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.** All mechanics are Python 3.13 standard library (`queue`, `itertools`, `typing`, `dataclasses`, `enum`) or already-pinned in-repo modules. The milestone gate forbids any `poetry` change across P1–P12; a lockfile diff is itself a gate failure.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────┐
                         │  EventBus (Protocol)                 │
                         │  put · get · get_nowait · qsize ·    │
                         │  empty · depth_by_tier               │
                         └───────────────┬─────────────────────┘
                    ┌────────────────────┴────────────────────┐
                    ▼                                          ▼
        ┌───────────────────────┐              ┌──────────────────────────────┐
        │ FifoEventBus          │              │ PriorityEventBus               │
        │  wraps queue.Queue    │              │  wraps queue.PriorityQueue     │
        │  put(e)→q.put(e)      │              │  put(e)→pq.put(                │
        │  get_nowait()→q.g_nw()│              │    (tier(e.type), next(seq),e))│
        │  (raises queue.Empty) │              │  get_nowait()→pq.g_nw()[2]     │
        │  BACKTEST (oracle)    │              │  LIVE (P2: DARK, unit-only)    │
        └───────────┬───────────┘              └──────────────┬───────────────┘
                    │                                          │
                    │                        tier = CONTROL(0) if type in
                    │                        _CONTROL_EVENT_TYPES else BUSINESS(1)
                    ▼
   BACKTEST WIRING (the only path P2 changes at runtime):

   run_backtest.py::main / build_backtest_system(spec)
        │
        ▼  builds EngineContext(bus=FifoEventBus(), config, environment='backtest', sql_engine=None)
   compose_engine(ctx, spec)  ──────────────────────────────────────────┐
        │  ctx.bus injected (retyped param, NAME unchanged) into every   │
        │  handler ctor; handlers own storage from (environment,          │
        │  sql_engine); reads .storage back for set_order_storage         │
        ▼                                                                 │
   ScreenersHandler · PortfolioHandler · ExecutionHandler(→SimulatedExchange) ·
   StrategiesHandler · OrderHandler · EventHandler(bar_source, bus)       │
        │                                                                 │
        ▼                                                                 │
   EventHandler.process_events():  event = bus.get_nowait()  ← unchanged loop
        except queue.Empty: break   (FifoEventBus MUST raise queue.Empty) │
                                                                          │
   live_trading_system.py ── UNTOUCHED (raw queue.Queue, D-11) ──────────┘
```

File-to-responsibility mapping is in the Architectural Responsibility Map above; the diagram shows data/wiring flow.

### Recommended Project Structure
```
itrader/events_handler/
├── bus.py                  # NEW (4-space): EventBus Protocol, FifoEventBus,
│                           #   PriorityEventBus, EventTier, _CONTROL_EVENT_TYPES
├── full_event_handler.py   # EDIT (tabs): retype global_queue param → EventBus
└── events/
    └── base.py             # (unchanged) Event is a msgspec.Struct, frozen

itrader/core/enums/
└── event.py                # EDIT (4-space): +STREAM_STATE +CONNECTOR_FATAL +CONFIG_UPDATE

itrader/trading_system/
├── compose.py              # EDIT (tabs): compose_engine(ctx, spec); delete queue.Queue():164
├── backtest_trading_system.py  # EDIT (tabs): both call sites fold to (ctx, spec)
└── (EngineContext home — discretion: here or events_handler/)

itrader/order_handler/order_handler.py       # EDIT (tabs): +environment,+sql_engine,storage= ; self.storage
itrader/strategy_handler/strategies_handler.py # EDIT (tabs): same handler-owned storage shape
```

### Pattern 1: Bus assigns tier — handlers stay tier-unaware
**What:** `.put(event)` reads `event.type`, looks it up in the `_CONTROL_EVENT_TYPES` frozenset, assigns tier. Handlers never pass a tier.
**When to use:** all producers (BUS-01 "no `.put` call-site changes").
**Example:**
```python
# Source: spec §4a; verified pattern
_CONTROL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.STREAM_STATE, EventType.CONNECTOR_FATAL,
    EventType.CONFIG_UPDATE, EventType.STRATEGY_COMMAND,
})
# Default = BUSINESS. New event types are BUSINESS unless explicitly listed CONTROL —
# robust to future EventType additions (no enumeration of the BUSINESS set needed).
def _tier(event_type: EventType) -> int:
    return 0 if event_type in _CONTROL_EVENT_TYPES else 1  # CONTROL=0 < BUSINESS=1
```

### Pattern 2: Protocol surface must cover the drain's exact needs
**What:** `EventHandler.process_events` calls `bus.get_nowait()` and catches `queue.Empty`. The Protocol must expose `get_nowait`; both implementations must raise `queue.Empty` on empty (inherited free from `Queue`/`PriorityQueue`).
**Example:**
```python
# Source: verified — full_event_handler.py:125-130 (unchanged by P2)
while True:
    try:
        event = self.global_queue.get_nowait()   # bus.get_nowait() — returns a bare Event
    except queue.Empty:                            # FifoEventBus & PriorityEventBus BOTH raise this
        break
    self._dispatch(event)
```
Note: the drain does **not** use `.empty()` (D-15 race-free drain removed the precheck). `empty()` stays on the Protocol for monitoring only.

### Pattern 3: Handler-owns-storage (copy PortfolioHandler verbatim in shape)
**What:** the handler derives its backend; the seam reads it back.
**Example:**
```python
# Source: PortfolioHandler.__init__ (portfolio_handler.py:68-81) — the template
def __init__(self, global_queue: "EventBus", ..., *,
             environment: str = "backtest", sql_engine: "Optional[Any]" = None,
             storage: "Optional[OrderStorage]" = None) -> None:
    self.storage = storage or OrderStorageFactory.create(environment, backend=sql_engine)
# compose_engine then: order_storage = order_handler.storage
#                       portfolio_handler.set_order_storage(order_storage)
```
`OrderStorageFactory.create('backtest', backend=None)` → `InMemoryOrderStorage()` (verified `storage_factory.py:51-52`); `SignalStorageFactory.create('backtest', backend=None)` → `InMemorySignalStore()` (verified `storage/storage_factory.py:67-68`). The `'live'` arm lazy-imports SQLAlchemy — inertness preserved.

### Anti-Patterns to Avoid
- **Renaming `global_queue` → `bus`:** breaks the CLAUDE.md naming convention AND widens the diff across ~6 files (D-08). Retype the annotation only.
- **Returning the `(tier, seq, event)` tuple from `PriorityEventBus.get*()`:** the drain expects a bare `Event`. Unwrap `[2]`.
- **A `FifoEventBus.get_nowait()` that raises anything but `queue.Empty`:** the drain's `except queue.Empty` would miss it → hang or crash. Delegate to the wrapped `queue.Queue`.
- **Enumerating the BUSINESS set in a frozenset:** only enumerate CONTROL; BUSINESS is the default fall-through (robust to new event types).
- **Wiring `PriorityEventBus` into `live_trading_system.py`:** explicitly rejected (D-11) — it silently changes validated v1.7 live ordering with no live gate until P12.
- **Adding fields to `EngineContext` in P3/P4/P9:** D-05 — those phases only *tighten types*.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Priority ordering | Custom heap / sorted list | `queue.PriorityQueue` | Thread-safe min-heap, `queue.Empty` semantics identical to `Queue` |
| Monotonic sequence | A locked `int` counter | `itertools.count()` | `next()` is atomic at the C level — thread-safe without a lock |
| Making events non-orderable | Adding `__lt__`/`@total_ordering` guards | Nothing — `msgspec.Struct` already raises `TypeError` on `<` (verified) | The unique `seq` means events are never compared; adding ordering is dead code |
| FIFO wrapper | Reimplementing a queue | `queue.Queue` behind `FifoEventBus` | Byte-identical to today's backtest queue → zero oracle risk |
| Structural interface | ABC + inheritance on `queue.Queue` | `typing.Protocol` | Duck-typing; `queue.Queue` needs no modification |

**Key insight:** the entire substrate is a thin typing/composition layer over stdlib primitives already present in the backtest hot path. The risk is not in the primitives — it is in the *wiring reach* (below).

## Runtime State Inventory

This is a **code-and-signature refactor**, not a data/service rename. Each category verified explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — no datastore keys, collection names, or IDs change. `EventType` member *values* are wire strings (`"STREAM_STATE"` etc.) but the 3 new ones have no producers/consumers/persisted records in P2 (D-11). | None |
| Live service config | **None** — no external service (OKX/n8n/Datadog) config references the bus or the new event types. Live wiring is untouched (D-11). | None |
| OS-registered state | **None** — no OS-level task/process names involved. | None |
| Secrets / env vars | **None new.** `ITRADER_DISABLE_LOGS=true` is exported by `make test` (see Pitfall 5) — pre-existing, not introduced here. | None |
| Build artifacts / installed packages | **None** — no `poetry.lock` change (forbidden by milestone gate); no egg-info/package rename. | Verify `poetry.lock` is byte-unchanged at phase close |

**Verified by:** grep for the 3 new `EventType` names (`STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`) and `PriorityEventBus`/`FifoEventBus`/`EngineContext`/`_CONTROL_EVENT_TYPES` across `itrader` + `tests` returned **zero** existing references — all are net-new symbols with no runtime state to migrate.

## Common Pitfalls

### Pitfall 1: The oracle runs through the SPEC-LESS legacy `__init__` arm
**What goes wrong:** the planner folds only `build_backtest_system(spec)` (`:437`) to `(ctx, spec)` and misses `BacktestTradingSystem.__init__`'s legacy arm (`:118-141`), which is what `scripts/run_backtest.py::main` and `test_backtest_oracle.py:261` actually call. The oracle breaks or the legacy arm won't compile.
**Why it happens:** the legacy arm builds `compose_engine(**kwargs)` inline; it has no `SystemSpec` and its ctor params (`exchange`, `start_date`, `end_date`, `timeframe`, `csv_paths`) lack `ticker`/`starting_cash` that `SystemSpec` *requires* as fields.
**How to avoid:** in the legacy arm, synthesize a minimal `SystemSpec` (data=`csv_paths or {}`, start/end/timeframe from ctor args, exchange=the seeded `ExchangeConfig`, empty `strategies`/`portfolios`, placeholder `ticker`/`starting_cash`). `compose_engine` reads none of `ticker`/`starting_cash`/`strategies`/`portfolios` — strategies/portfolios are added *post-compose* in both arms — so placeholders are byte-safe. Build the `EngineContext(bus=FifoEventBus(), ...)` here too.
**Warning signs:** oracle test asserts a trade-count/equity drift; or `TypeError: compose_engine() got an unexpected keyword argument`.

### Pitfall 2: `PriorityEventBus.get*()` returns a tuple; `FifoEventBus.get_nowait()` swallows `queue.Empty`
**What goes wrong:** dispatch receives `(tier, seq, event)` instead of `event` (`event.type` → `AttributeError`), or the drain never terminates because the empty signal changed.
**How to avoid:** `PriorityEventBus.get()/get_nowait()` return `self._pq.get(...)[2]`; both buses inherit/re-raise `queue.Empty` unchanged. Verified the drain (`full_event_handler.py:128`) catches exactly `queue.Empty`.
**Warning signs:** `AttributeError: 'tuple' object has no attribute 'type'`; or an infinite drain loop.

### Pitfall 3: The shared `EventHandler` retype vs. the untouched live construction sites
**What goes wrong:** retyping `EventHandler.__init__(global_queue: EventBus)` — a class **shared** by backtest and live — could flag mypy at the live construction sites (`live_trading_system.py:499` passes a raw `queue.Queue`, which does NOT satisfy the `EventBus` Protocol: it lacks `depth_by_tier`).
**Why it's actually SAFE here:** `itrader.trading_system.live_trading_system` is in the mypy `ignore_errors` override list (`pyproject.toml:104`, verified). So the live sites are not strict-checked in P2. The strict-checked handler *modules* (`order_handler`, `strategies_handler`, `portfolio_handler`, `execution_handler`, `full_event_handler`) only call `.put()` / `.get_nowait()` on the param — both on the Protocol — so their bodies stay mypy-clean after the retype.
**How to avoid regressions:** run `poetry run mypy itrader` after the retype. Do NOT remove the live_trading_system mypy override to "clean it up" — that is P6/P7 work.
**Warning signs:** mypy errors of the form `Argument 1 to "EventHandler" has incompatible type "Queue[Any]"; expected "EventBus"` on an *in-scope* module.

### Pitfall 4: msgspec.Struct is `__eq__`-comparable — only `seq` uniqueness saves you
**What goes wrong:** if two priority tuples ever share the same `(tier, seq)`, `heapq` falls through to comparing the events; `Event == Event` returns a bool (msgspec defines `__eq__`), but `Event < Event` raises `TypeError`. A duplicated `seq` (e.g. per-instance counter instead of one shared `itertools.count()`) is a latent crash.
**How to avoid:** ONE module-level (or per-bus-instance) `itertools.count()` shared across all `.put()` calls; never reset it. The BUS-02 test must assert uniqueness produces stable ordering AND (negative test) that comparing two events directly raises `TypeError` (proving the guarantee is load-bearing).
**Warning signs:** `TypeError: '<' not supported between instances of '...Event'` under concurrent puts.

### Pitfall 5: `make test` disables logs and aborts in worktrees
**What goes wrong:** (from project memory) `make test` exports `ITRADER_DISABLE_LOGS=true`, which fails `caplog` warn-assertion tests; and `make test` aborts in a git worktree on a missing `.env`.
**How to avoid:** for the phase gate, run `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -v` directly; re-run `make test` only in the main checkout. Also honor the worktree `.venv` shadowing note: prepend `PYTHONPATH="$PWD"` if editable-install edits aren't picked up.
**Warning signs:** a caplog test fails only under `make test`; `make test` aborts with a `.env` error.

## Code Examples

### PriorityEventBus ordering invariant — VERIFIED by running it
```python
# Ran in-session (poetry run python) against the REAL Event base (msgspec 0.21.1):
import msgspec, itertools, queue
class E(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    x: int = 0
a, b = E(x=1), E(x=1)
a == b          # True   (msgspec defines __eq__)
a < b           # TypeError: '<' not supported  ← the non-orderability the test must prove
seq = itertools.count()
pq = queue.PriorityQueue()
pq.put((1, next(seq), b)); pq.put((0, next(seq), a)); pq.put((1, next(seq), a))
[pq.get_nowait()[:2] for _ in range(3)]
# → [(0, 1), (1, 0), (1, 2)]  ← CONTROL first; within BUSINESS strict FIFO by seq
```
This is the exact BUS-02 assertion shape: enqueue a CONTROL after two BUSINESS events, prove CONTROL dequeues first, BUSINESS stays FIFO, and a bare `event < event` raises `TypeError`.

### The 3 new EventType members (slot into `core/enums/event.py`, 4-space)
```python
# Source: core/enums/event.py:23-36 (current members) — add alongside, string-valued
    STREAM_STATE = "STREAM_STATE"        # BUS-03: connector stream up/down (CONTROL)
    CONNECTOR_FATAL = "CONNECTOR_FATAL"  # BUS-03: connector fatal → halt (CONTROL)
    CONFIG_UPDATE = "CONFIG_UPDATE"      # BUS-03: scoped runtime config change (CONTROL)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw `global_queue: queue.Queue` threaded everywhere | `EventBus` Protocol with FIFO/priority impls behind `.put()` | This phase (P2) | Enables CONTROL-plane preemption in live (P6/P7) without touching the backtest hot path |
| `compose_engine(*, 8 kwargs)` | `compose_engine(ctx, spec)` end-state | This phase (P2, D-01 Option B) | Never re-edited downstream; CTX-01/02/03 pulled forward from P3 |
| `OrderHandler`/`StrategiesHandler` receive a pre-built storage | Handlers own storage init from `(environment, sql_engine)` | This phase (P2, CTX-02) | Matches `PortfolioHandler`; the seam reads `.storage` back |

**Deprecated/outdated in the docs (do not trust literally):**
- CLAUDE.md and CONTEXT.md call events "frozen dataclasses." **Reality (verified):** `Event` is a `msgspec.Struct(frozen=True, kw_only=True, gc=False)` (`events_handler/events/base.py:21`). The non-orderability premise still holds (msgspec raises `TypeError` on `<`), but any BUS-02 test comment should say "msgspec.Struct," not "dataclass."
- CLAUDE.md's Component-Responsibilities table lists a `TradingInterface` class and `postgresql_storage.py` `NotImplementedError` placeholder — both stale (removed in v1.7 per the CLAUDE.md architecture prose). Not relevant to P2 but do not use them as touchpoints.

## Validation Architecture

> Nyquist validation is ENABLED for this project. This section drives VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion="8.0"`, `--strict-markers --strict-config`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| Quick run command | `poetry run pytest tests/unit/events -x` (new bus unit tests land here) |
| Full suite command | `make test` (main checkout) or `poetry run pytest tests` (worktree — see Pitfall 5) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BUS-01 | Both buses satisfy the Protocol; `.put()`/`get_nowait()` surface; no call-site change | unit | `poetry run pytest tests/unit/events/test_event_bus.py -x` | ❌ Wave 0 |
| BUS-02 | `(tier,seq,event)` ordering: CONTROL preempts, within-tier FIFO, event never compared, `Event < Event` raises `TypeError` | unit | `poetry run pytest tests/unit/events/test_event_bus.py -k priority -x` | ❌ Wave 0 |
| BUS-03 | 3 CONTROL `EventType`s exist + assigned CONTROL via `_CONTROL_EVENT_TYPES`; backtest wires `FifoEventBus` | unit | `poetry run pytest tests/unit/events/test_event_bus.py -k control_types -x` | ❌ Wave 0 |
| BUS-04 / CTX-01 | `compose_engine(ctx, spec)` signature; internal `queue.Queue()` deleted | unit/integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ (extend) |
| CTX-02 | Order + Strategies handlers own storage from `(environment, sql_engine)`; `.storage` readable back | unit | `poetry run pytest tests/unit/order tests/unit/strategy -x` | ✅ (extend) / ❌ new case |
| CTX-03 / oracle | Backtest → same in-memory instances → byte-exact `134 / 46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ |
| inertness | `FifoEventBus`/`EngineContext(sql_engine=None)` pull nothing heavy; import builds no `SqlSettings` | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ (extend register-vs-build) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/events/test_event_bus.py -x` (fast — pure stdlib, no data load).
- **Per wave merge / per PLAN gate:** `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -x` (the two milestone gates — oracle byte-exact + inertness). Determinism double-run: run the oracle twice, assert identical.
- **Phase gate:** full suite green + `poetry run mypy itrader` clean on new/edited in-scope code + `poetry.lock` byte-unchanged.

### Wave 0 Gaps
- [ ] `tests/unit/events/test_event_bus.py` — covers BUS-01/02/03 (Protocol conformance for both buses; priority ordering + non-orderability negative test; `_CONTROL_EVENT_TYPES` tier assignment). **Do NOT add `tests/unit/events/__init__.py`** — the empty-`__init__` package-collision hazard (project memory) breaks full-suite collection; keep `tests/unit/*` package-less.
- [ ] Extend `tests/integration/test_okx_inertness.py` — add the register-vs-build assertion that constructing `EngineContext(sql_engine=None)` + `FifoEventBus` pulls no SQLAlchemy/ccxt (append to `_PROBE` and/or a new in-process assertion that `FifoEventBus()` and the backtest `compose_engine` build no `SqlSettings`).
- [ ] New handler-storage unit cases: `OrderHandler(..., environment='backtest', sql_engine=None)` yields `InMemoryOrderStorage` and exposes `.storage`; same for `StrategiesHandler` → `InMemorySignalStore`.
- Framework install: none — pytest infra already present.

## Security Domain

> `security_enforcement` default-enabled. This is an internal engine refactor with **no auth, no network ingress, no user input, no secrets** introduced. ASVS categories are largely N/A; the relevant controls are the milestone gates.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth surface touched) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | minimal | `EventType._missing_` case-insensitive parse already guards unknown type strings; the bus never parses external input in P2 |
| V6 Cryptography | no | — (UUIDv7 via `idgen`, unchanged) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent event drop (unrouted type) | Tampering / Repudiation | `EventHandler._dispatch` raises `NotImplementedError` on an unrouted type (unchanged) — the 3 new CONTROL types are backtest-inert but must not silently vanish if ever routed |
| Inertness regression (eager SQL/ccxt import) | (availability/perf) | `test_okx_inertness.py` extended register-vs-build assertion — the recurring failure mode per STATE.md Blockers |
| Live-ordering change slipped in via priority bus | Tampering (behavioral) | D-11: zero live wiring in P2; `live_trading_system.py` stays on its raw queue until a live-smoke gate exists (P12) |

## Sources

### Primary (HIGH confidence — verified against live code this session)
- `itrader/trading_system/compose.py` — `compose_engine` signature `:116`, internal `queue.Queue()` `:164`, `Engine` holder, both concretes-injected kwargs. **Confirmed.**
- `itrader/trading_system/backtest_trading_system.py` — legacy `__init__` compose call `:131`, `build_backtest_system` `:401`, factory compose call `:437`, ctor signature `:83-94`. **Confirmed two call sites; oracle uses the legacy arm.**
- `itrader/trading_system/system_spec.py` — `SystemSpec` fields (`start/end/timeframe/ticker/starting_cash/data/strategies/portfolios/exchange/actions/results_store`). **Confirmed the D-04 fold mapping + the `ticker`/`starting_cash` required-field wrinkle.**
- `itrader/events_handler/full_event_handler.py` — drain `:125-130` (`get_nowait()` + `except queue.Empty`, no `.empty()` precheck), ctor `global_queue` param `:66`. **Confirmed.**
- `itrader/core/enums/event.py` — current `EventType` members `:23-36`, string values, `_missing_` parser. **Confirmed.**
- `itrader/portfolio_handler/portfolio_handler.py` — storage template `:68-81` (`environment`, `backend` params). **Confirmed the handler-owns-storage shape.**
- `itrader/order_handler/order_handler.py:43-99` + `itrader/strategy_handler/strategies_handler.py:39-94` — target ctors for the storage retrofit.
- `itrader/order_handler/storage/storage_factory.py:24-69` + `itrader/strategy_handler/storage/storage_factory.py:36-92` — `create(env, backend=)` signatures; `'backtest'/'test'` → in-memory, `'live'` → lazy SQL import. **Confirmed inertness path.**
- `itrader/events_handler/events/base.py:21` — `Event` is a `msgspec.Struct(frozen=True)`, not a dataclass. **Confirmed via runtime check that `<` raises `TypeError`.**
- `tests/integration/test_backtest_oracle.py` + `tests/integration/test_okx_inertness.py` — the two gates; the inertness probe's `_FORBIDDEN` module list + the CFG-02 register-vs-build assertion pattern. **Read in full.**
- `pyproject.toml` mypy overrides — `live_trading_system` in `ignore_errors` `:104`. **Confirmed the retype is mypy-safe.**
- Live in-session verification: msgspec 0.21.1 `Struct` non-orderability + `PriorityQueue`/`itertools.count` ordering. **Ran and captured output.**

### Secondary (MEDIUM confidence)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §4a/§4b/§5/§7a/§7b — the design contract for the bus, threading, topology, `EngineContext`, handler-owns-init.
- Project memory notes (worktree `.venv` shadowing; `make test` `.env` abort + `ITRADER_DISABLE_LOGS`; test-dir `__init__.py` collision; oracle test location).

### Tertiary (LOW confidence)
- None — all claims verified or cited.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The legacy `__init__` arm can pass placeholder `ticker`/`starting_cash` in a synthesized `SystemSpec` because `compose_engine` reads neither | Pitfall 1 | If `compose_engine` (post-fold) is written to read `spec.ticker`/`spec.starting_cash`, placeholders would corrupt the run — planner must keep `compose_engine` reading only `data/start/end/timeframe/exchange/results_store` |
| A2 | Retyping the shared `EventHandler` param to `EventBus` is mypy-safe because live sites are `ignore_errors` | Pitfall 3 | If a future edit removes the `live_trading_system` mypy override, the live construction sites would flag — but that is out of P2 scope |

**Note:** A1/A2 are LOW-risk execution assumptions, not open design questions — the locked decisions (D-01/D-08/D-11) already resolve the design. Confirm A1 by keeping the `compose_engine` body's spec reads to the D-04 fold set only.

## Open Questions

1. **`EngineContext` home module (Claude's Discretion, D-05).**
   - What we know: must avoid an import cycle with `EventBus` (which lives in `events_handler/bus.py`).
   - What's unclear: `trading_system/` (near `compose_engine`) vs `events_handler/`.
   - Recommendation: place `EngineContext` in `trading_system/` (it is composition-root infra and `compose_engine` is its only consumer in P2); import `EventBus` from `events_handler.bus` for the `bus:` field type. `events_handler.bus` imports only stdlib + `core.enums.event`, so no cycle arises. If a cycle appears, fall back to a `TYPE_CHECKING`-only import of `EventBus`.

2. **`order_config` under the fold (Claude's Discretion, D-04).**
   - What we know: it is the one kwarg with no `SystemSpec` field; P1 D-03 leaned "order lives with its owner."
   - Recommendation: keep it handler-owned via `OrderConfig.default()` inside `compose_engine` (unchanged from today's `:220`), do NOT add a `SystemSpec` field — consistent with P1 D-03 and keeps the spec declarative.

3. **Optional standalone `PriorityEventBus` integration test (Claude's Discretion).**
   - Recommendation: add a small `tests/unit/events` test that interleaves a representative CONTROL+BUSINESS stream through `PriorityEventBus` and asserts drain order — cheap integration confidence with zero `live_trading_system.py` touch. The better buy than any live wiring.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python stdlib `queue`/`itertools`/`typing`/`dataclasses`/`enum` | all of P2 | ✓ | 3.13.1 | — |
| pytest + poetry venv | test gates | ✓ | pytest 8.4.2 | — |
| msgspec | `Event` base (non-orderability premise) | ✓ | 0.21.1 | — |

**Missing dependencies:** none. **New dependencies:** none (forbidden by milestone gate).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, no packages; verified present and behavior confirmed by running it.
- Architecture / touchpoints: HIGH — every pinned line number re-verified against live code this session; two-call-site subtlety discovered and documented.
- Pitfalls: HIGH — the three load-bearing ones (spec-less legacy arm, tuple-unwrap/`queue.Empty`, shared-EventHandler retype) each traced to a specific verified line.

**Research date:** 2026-07-09
**Valid until:** 2026-08-08 (stable — pure stdlib + a locked design contract; only invalidated by an unrelated refactor of the touchpoints)
