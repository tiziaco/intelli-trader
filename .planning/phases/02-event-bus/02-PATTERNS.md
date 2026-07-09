# Phase 2: Event Bus - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 8 (1 new, 7 modified)
**Analogs found:** 8 / 8

> Indentation hazard is per-file and load-bearing. Each entry pins the convention the
> planner must carry into `<read_first>`. **New `bus.py` = 4-space** (events-package convention);
> **all handler-ctor / compose edits = TABS**; **`core/enums/event.py` = 4-space**. Never normalize.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/events_handler/bus.py` **(NEW)** | utility / transport substrate | pub-sub (queue) | `events_handler/events/` package + `full_event_handler.py` drain | role-match (new symbol) | 4-space |
| `itrader/core/enums/event.py` (MOD) | config / enum | — | itself (existing `EventType` members) | exact | 4-space |
| `itrader/events_handler/full_event_handler.py` (MOD) | dispatcher | event-driven | itself (drain loop `:125-130`) | exact (retype only) | TABS |
| `itrader/trading_system/compose.py` (MOD) | config / composition seam | request-response (wiring) | itself (`compose_engine` `:116`) | exact | TABS |
| `itrader/trading_system/backtest_trading_system.py` (MOD) | config / factory + legacy ctor | request-response | itself (two call sites) | exact | TABS |
| `itrader/trading_system/system_spec.py` (READ-ref) | model / value object | — | itself (`SystemSpec` fields) | exact | TABS |
| `itrader/order_handler/order_handler.py` (MOD) | controller (thin handler) | CRUD (storage) | `portfolio_handler.py __init__ :68-81` | role-match | TABS |
| `itrader/strategy_handler/strategies_handler.py` (MOD) | controller (thin handler) | CRUD (storage) | `portfolio_handler.py __init__ :68-81` | role-match | TABS |
| `EngineContext` home (NEW dataclass; discretion: `trading_system/`) | model / value object | — | `system_spec.py::SystemSpec` (frozen-dataclass shape) | role-match | TABS if in `trading_system/` |

---

## Pattern Assignments

### `itrader/events_handler/bus.py` (NEW — utility / transport, 4-space)

No exact analog exists — this is net-new. Copy **structure** from three sources:

**1. Enum-member add pattern & string-value convention** — from `core/enums/event.py:8-49`
(shown below in that file's section). `EventTier` mirrors this: a small `enum.Enum` (`CONTROL=0`, `BUSINESS=1`).

**2. Protocol house-pattern** — the project already uses `typing.Protocol` for read-model seams
(`core/portfolio_read_model.py::PortfolioReadModel`, `_AlertSinkLike` in `full_event_handler.py`).
`EventBus` is the same shape: a structural interface, no ABC inheritance. Surface (D-09):
`put`, `get(timeout)`, `get_nowait`, `qsize`, `empty`, `depth_by_tier`.

**3. Drain-contract the buses must satisfy** — from `full_event_handler.py:125-130` (verbatim, the
consumer that pins the invariant):
```python
while True:
    try:
        event = self.global_queue.get_nowait()   # bus.get_nowait() — MUST return a BARE Event
    except queue.Empty:                            # BOTH buses MUST raise queue.Empty
        break
    self._dispatch(event)
```
Load-bearing (RESEARCH Pitfall 2): `FifoEventBus.get_nowait()` delegates to `queue.Queue` (raises
`queue.Empty`); `PriorityEventBus.get()/get_nowait()` return `self._pq.get(...)[2]` (unwrap tuple,
never return `(tier, seq, event)`).

**Priority invariant (BUS-02, verified by running it — RESEARCH Code Examples):**
```python
import itertools, queue
_CONTROL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.STREAM_STATE, EventType.CONNECTOR_FATAL,
    EventType.CONFIG_UPDATE, EventType.STRATEGY_COMMAND,
})
def _tier(event_type: EventType) -> int:
    return 0 if event_type in _CONTROL_EVENT_TYPES else 1  # CONTROL=0 < BUSINESS=1
# ONE shared itertools.count() as seq; each next() is C-atomic → thread-safe, globally unique
# → the (tier, seq, event) tuple NEVER dereferences the non-orderable Event.
```
Note (RESEARCH State-of-the-Art): `Event` is a `msgspec.Struct(frozen=True)` (NOT a dataclass) —
`Event < Event` raises `TypeError`; the BUS-02 negative test asserts this to prove the `seq`
guarantee is load-bearing. `depth_by_tier` on `FifoEventBus` may be a single-bucket mapping
(`{BUSINESS: qsize}` — discretion, FIFO is tierless).

---

### `itrader/core/enums/event.py` (MOD — enum add, 4-space)

**Analog:** itself. The 3 new CONTROL members slot alongside the existing v1.7 additions
(`UNIVERSE_POLL`/`STRATEGY_COMMAND`/`BARS_LOADED`), same explicit-uppercase-string style
(current members `:23-36`, `_missing_` parser `:38-49`):
```python
    STREAM_STATE = "STREAM_STATE"        # BUS-03: connector stream up/down (CONTROL)
    CONNECTOR_FATAL = "CONNECTOR_FATAL"  # BUS-03: connector fatal → halt (CONTROL)
    CONFIG_UPDATE = "CONFIG_UPDATE"      # BUS-03: scoped runtime config change (CONTROL)
```
`_missing_` (case-insensitive parse) needs no change — it iterates all members. `EventHandler.routes`
does NOT need a new branch in P2 (D-11: no consumers) unless the planner mirrors the existing
`STRATEGY_COMMAND: []` explicit-empty style (`full_event_handler.py:108-111`) for the 3 new types to
avoid `_dispatch`'s `NotImplementedError` if ever routed — recommended for parity with the v1.7 members.

---

### `itrader/events_handler/full_event_handler.py` (MOD — retype only, TABS)

**Analog:** itself. Ctor param `global_queue: "queue.Queue[Any]"` at `:66` → retype annotation to
`EventBus` (D-08: **name stays `global_queue`**). Body is unchanged — the drain (`:125-130`, above)
already uses only Protocol methods (`get_nowait`). RESEARCH Pitfall 3: this class is shared with the
untouched live path, but `live_trading_system` is in the mypy `ignore_errors` override
(`pyproject.toml:104`), so the retype is strict-safe. Run `poetry run mypy itrader` after.

---

### `itrader/trading_system/compose.py` (MOD — signature settle + delete internal queue, TABS)

**Analog:** itself. Current signature (`:116-127`) is 8 kwargs; the internal
`global_queue: "queue.Queue[Any]" = queue.Queue()` at `:164` is **deleted** (D-01). Target end-state:
`compose_engine(ctx: EngineContext, spec: SystemSpec) -> Engine`.

**Current kwargs → spec fold (D-04, mostly 1:1):**
```python
# CURRENT (compose.py:116-127) — the 8-kwarg form to collapse
def compose_engine(*, order_storage, signal_store, csv_paths=None,
    start_date=None, end_date=None, timeframe="1d",
    exchange_config=None, order_config=None, results_store=None) -> Engine:
```
Fold map: `csv_paths→spec.data`, `start_date→spec.start`, `end_date→spec.end`, `timeframe→spec.timeframe`,
`exchange_config←spec.exchange` (factory still derives via `_seed_supported_symbols`), `results_store→spec.results_store`.
`order_storage`/`signal_store` come off the **handlers** now (D-02, below), not params. `order_config`
stays handler-owned via `OrderConfig.default()` (D-04 lean; current `:220`
`resolved_order_config = order_config or OrderConfig.default()`).

**A1 (RESEARCH Assumptions):** keep the body's spec reads to `{data, start, end, timeframe, exchange, results_store}`
ONLY — `compose_engine` must NOT read `spec.ticker`/`spec.starting_cash` (the legacy arm passes placeholders).

**Bus injection & storage back-read (D-01/D-02):** replace the deleted `queue.Queue()` with `ctx.bus`;
pass `ctx.bus` into every handler ctor (`ScreenersHandler(global_queue, feed)` `:180`,
`PortfolioHandler(global_queue)` `:181`, `ExecutionHandler(global_queue, ...)` `:187`,
`StrategiesHandler(global_queue, ...)` `:215`, `OrderHandler(global_queue, ...)` `:221`,
`EventHandler(..., global_queue)` `:245`). Then read storage back off the handlers for wiring:
```python
# CURRENT (compose.py:234): order_storage is a param today
portfolio_handler.set_order_storage(order_storage)
# TARGET: order_storage = order_handler.storage; portfolio_handler.set_order_storage(order_storage)
```

---

### `itrader/trading_system/backtest_trading_system.py` (MOD — TWO call sites, TABS)

**Analog:** itself. **RESEARCH Pitfall 1 (highest-value finding):** there are TWO call sites and
the oracle runs through the spec-LESS legacy arm.

**Site 1 — legacy `__init__` arm (`:131-140`, what `scripts/run_backtest.py` + `test_backtest_oracle.py:261` call):**
```python
# CURRENT — builds kwargs inline, NO SystemSpec
order_storage = OrderStorageFactory.create('backtest')
self._signal_store = SignalStorageFactory.create('backtest')
tickers = {str(t).upper() for t in (csv_paths or {}).keys()}
exchange_config = _seed_supported_symbols(get_exchange_preset('default'), tickers)
self.engine = compose_engine(order_storage=..., signal_store=..., csv_paths=..., ...)
```
Must synthesize a minimal `SystemSpec` (data=`csv_paths or {}`, start/end/timeframe from ctor args,
exchange=the seeded `ExchangeConfig`, empty `strategies`/`portfolios`, placeholder `ticker`/`starting_cash`
— `compose_engine` reads none of these per A1) and build `EngineContext(bus=FifoEventBus(), config=<SystemConfig>, environment='backtest', sql_engine=None)` here.

**Site 2 — `build_backtest_system(spec)` factory (`:437-447`):** already has a `spec`. Build the
same `EngineContext` and call `compose_engine(ctx, spec)`. Storage is now handler-owned; the factory's
`OrderStorageFactory.create('backtest')` (`:414-415`) moves INTO the handlers (D-02) — the factory keeps
only symbol-set seeding + `EngineContext` construction.

---

### `itrader/order_handler/order_handler.py` (MOD — adopt handler-owned storage, TABS)

**Analog:** `portfolio_handler.py::__init__` (`:68-81`) — the exact template (see Shared Patterns).
Current ctor (`:43-49`) already takes `order_storage: Optional[OrderStorage] = None` and forwards it to
`OrderManager` (`:83-84`, `order_storage or OrderStorageFactory.create_in_memory()`). Add keyword-only
`environment: str = "backtest"`, `sql_engine: Optional[Any] = None`; resolve:
```python
# TARGET shape (D-02), mirroring PortfolioHandler:
self.storage = order_storage or OrderStorageFactory.create(environment, backend=sql_engine)
# then pass self.storage into OrderManager instead of the create_in_memory() fallback
```
`OrderStorageFactory.create('backtest', backend=None)` → `InMemoryOrderStorage()` (RESEARCH-verified
`storage_factory.py:51-52`) → byte-exact. Expose `.storage` so `compose_engine` reads it back.
Retype `global_queue` param → `EventBus` (D-08, name unchanged).

---

### `itrader/strategy_handler/strategies_handler.py` (MOD — adopt handler-owned storage, TABS)

**Analog:** `portfolio_handler.py::__init__` (`:68-81`). Current ctor (`:39-46`) takes
`signal_store: SignalStore` as a required positional. Add keyword-only `environment`/`sql_engine` and
resolve like Order:
```python
# TARGET (D-02): signal_store optional → handler owns it
self.signal_store = signal_store or SignalStorageFactory.create(environment, backend=sql_engine)
```
`SignalStorageFactory.create('backtest', backend=None)` → `InMemorySignalStore()` (RESEARCH-verified
`storage/storage_factory.py:67-68`). Expose the concrete for `compose_engine` back-read. Retype
`global_queue` → `EventBus`.

---

### `EngineContext` (NEW frozen dataclass — home: `trading_system/`, TABS — RESEARCH OQ1)

**Analog:** `system_spec.py::SystemSpec` (`:79-111`) — the frozen-dataclass value-object house style
(`@dataclass(frozen=True)`, loose `Any` types to stay import-inert, e.g. `results_store: Any = None`).
Shape (D-05, all 4 fields now, types only tightened in P3/P4/P9):
```python
@dataclass(frozen=True)
class EngineContext:
    bus: "EventBus"                 # from events_handler.bus — no cycle (bus imports only stdlib + core.enums)
    config: Any                     # today's SystemConfig (loose; P9 → RuntimeConfig)
    environment: str                # 'backtest'
    sql_engine: Optional[Any] = None  # concrete SqlEngine lands P3/P4
```
Place in `trading_system/` (composition-root infra; `compose_engine` is its only P2 consumer). If an
import cycle with `EventBus` appears, fall back to a `TYPE_CHECKING`-only import (RESEARCH OQ1).

---

## Shared Patterns

### Handler-owns-storage (the D-02 template — copy verbatim in shape)
**Source:** `itrader/portfolio_handler/portfolio_handler.py::__init__` (`:68-81`)
**Apply to:** `OrderHandler`, `StrategiesHandler`
```python
def __init__(self, global_queue: "Queue[Any]", config_dir: str = "settings",
             environment: str = "backtest", backend: "Optional[Any]" = None) -> None:
    self.global_queue: "Queue[Any]" = global_queue
    ...
    self._environment = environment   # 'backtest' = in-memory oracle-dark path
    self._backend = backend           # typed Any to keep SQL import off the hot path (GATE-01)
```
Order/Strategies adopt the `storage or Factory.create(environment, backend=sql_engine)` resolution and
expose the concrete on `.storage` for `compose_engine`'s `set_order_storage(...)` back-read.
Backtest slice: `environment='backtest', sql_engine=None` → identical in-memory instances → byte-exact.

### Retype-not-rename bus swap
**Source:** CLAUDE.md convention + D-08. Every handler ctor's `global_queue: "queue.Queue[Any]"` (or
`"Queue[Any]"`) annotation → `EventBus`; **name unchanged**. Sites: `full_event_handler.py:66`,
`order_handler.py:43`, `strategies_handler.py:41`, `portfolio_handler.py:68`,
`compose.py` handler-construction calls. No `.put()` call-site changes (duck-typed). `.empty()` is NOT
used by the drain (D-15 race-free); it stays on the Protocol for monitoring only.

### Frozen value-object convention
**Source:** `system_spec.py` (`@dataclass(frozen=True)`, `Any`-typed inertness-sensitive fields).
**Apply to:** `EngineContext`.

### Import-inertness discipline (gate: `test_okx_inertness.py`)
**Source:** `system_spec.py:93-98` (`results_store: Any` — spec never imports SQL) + factory lazy-SQL
arms. `EngineContext(sql_engine=None)` + `FifoEventBus` must pull nothing heavy; `bus.py` imports only
stdlib (`queue`, `itertools`, `typing`, `dataclasses`, `enum`) + `core.enums.event`.

## No Analog Found

None. Every file has an in-repo analog (mostly itself for retype/settle edits; `PortfolioHandler` for
the two storage retrofits; `SystemSpec` for `EngineContext`). `bus.py` is net-new but composes
established house patterns (`Protocol` read-model seam, string-enum, frozen dataclass, stdlib `queue`).

## Metadata

**Analog search scope:** `itrader/events_handler/`, `itrader/trading_system/`, `itrader/core/enums/`,
`itrader/order_handler/`, `itrader/strategy_handler/`, `itrader/portfolio_handler/`
**Files scanned:** 8 (all touchpoints from RESEARCH.md `## Sources`, line numbers re-verified)
**Pattern extraction date:** 2026-07-09
