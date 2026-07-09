# Architecture Research — v1.8 Live System Refactor Integration Map

**Domain:** Brownfield decomposition of a 2,171-line `LiveTradingSystem` God object into a factory + shared `compose_engine` + `LiveRunner` + focused controllers, around an existing event-driven single-queue engine (Python 3.13).
**Researched:** 2026-07-09
**Confidence:** HIGH — every integration point below is traced against the real existing files (`compose.py`, `full_event_handler.py`, `backtest_runner.py`, `portfolio_handler.py`, `order_handler.py`, `storage/backend.py`). The design spec (`docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md`) locks the topology; this doc validates how it lands on the codebase.

**Two gates govern EVERY foundational seam:**
- **ORACLE (LR-02):** the SMA_MACD backtest run stays byte-exact (`134 trades / final_equity 46189.87730727451`). Blocking for P1–P4 and P7's `UniverseWiring`.
- **INERTNESS:** `tests/integration/test_okx_inertness.py` stays green — importing the backtest composition root pulls no `ccxt.pro`, no async connector, no Postgres `SqlSettings`.

Every seam is tagged `[ORACLE]` and/or `[INERT]` where it touches a gate.

---

## Standard Architecture — target topology (LR-10)

The v1.8 end-state mirrors the already-proven backtest 4-layer split (`SystemSpec → factory → shared compose_engine → Runner → thin facade`) onto the live path:

```
┌──────────────────────────────────────────────────────────────────────┐
│  COMPOSITION ROOT (mode-specific factories)                            │
│  ┌────────────────────────┐        ┌──────────────────────────────┐   │
│  │ build_backtest_system  │        │ build_live_system   [NEW P7]  │   │
│  │ (exists)               │        │ reads SystemConfig; builds    │   │
│  │ env='backtest'         │        │ ONE sql_engine; resolves venue│   │
│  │ sql_engine=None        │        │ plugin(s); builds stores      │   │
│  │ bus=FifoEventBus       │        │ bus=PriorityEventBus          │   │
│  └───────────┬────────────┘        └───────────────┬──────────────┘   │
│              │      builds EngineContext(bus,config,env,sql_engine)    │
│              └───────────────┬───────────────────────┘                 │
├──────────────────────────────┼─────────────────────────────────────────┤
│  SHARED SEAM                  ▼                                         │
│  compose_engine(ctx, spec)  [MODIFIED P2/P3 — signature change]        │
│  builds the mode-agnostic component graph; handlers own their storage  │
│  → returns Engine holder                                               │
├──────────────────────────────┬─────────────────────────────────────────┤
│  RUN DRIVERS                  │                                         │
│  ┌────────────────────────┐   │   ┌──────────────────────────────┐     │
│  │ BacktestRunner (exists)│   │   │ LiveRunner        [NEW P7]    │     │
│  │ sync fail-fast for-loop│   │   │ drain loop bus.get(timeout)  │     │
│  │ bus.get_nowait()       │   │   │ + injected ErrorPolicy (P9)  │     │
│  └────────────────────────┘   │   │ + WorkerSupervisor           │     │
│                               │   └──────────────────────────────┘     │
├──────────────────────────────┼─────────────────────────────────────────┤
│  FACADE                       │                                         │
│  TradingSystem (thin, exists) │   LiveTradingSystem (SHRUNK ~200 lines) │
│                               │   lifecycle + status latch delegation   │
├──────────────────────────────┴─────────────────────────────────────────┤
│  ONE EventHandler (single, data-driven — NO subclass, LR-16)           │
│  routes = base literal + LiveRouteRegistrar additions [MODIFIED P7]     │
│  backtest → base routes only (explicit-empty live slots = inertness)   │
├─────────────────────────────────────────────────────────────────────────┤
│  LIVE-ONLY CONTROLLERS [NEW P6-P12]                                     │
│  VenueRegistry+bundle · SafetyController · StreamRecoveryHandler ·       │
│  ReconciliationCoordinator · SessionInitializer · ErrorHandler ·        │
│  UniverseHandler(proper init) · new durable stores                      │
└─────────────────────────────────────────────────────────────────────────┘
```

**The two loops + the deleted third mechanism (§4c):** the connector asyncio loop (own daemon thread, `ccxt.pro` streaming) and the engine thread (`LiveRunner` drain) both stay; **the queue is the bulkhead**. The `threading.Event` flag side-channel (`_pending_stream_resume`, `_pending_connector_halt`, `_maybe_*` pollers, the `queue.Empty`-branch polling) is **deleted** — replaced by CONTROL-plane events that wake `bus.get(timeout)` naturally.

---

## Component Responsibilities — NEW vs MODIFIED vs UNCHANGED

| Component | Status | Owns / Change | Gate | Phase |
|-----------|--------|---------------|------|-------|
| `EventBus` Protocol + `FifoEventBus` / `PriorityEventBus` (`events_handler/bus.py`) | **NEW** | tiered `.put()` routing; drop-in for `queue.Queue` surface | `[INERT]` Fifo pulls nothing heavy | P2 |
| `EngineContext` (`bus, config, environment, sql_engine`) | **NEW** | frozen infra carrier, threaded once into `compose_engine` | `[INERT]` `sql_engine=None` on backtest | P3 |
| `compose_engine` | **MODIFIED** | signature `(ctx, spec)`; stops creating the queue; reads `ctx.bus`; handlers own storage; reads `.storage` back | `[ORACLE]` backtest graph byte-identical | P2, P3 |
| `Engine` holder | **MODIFIED** | `global_queue` field → `bus` reference | `[ORACLE]` | P2/P3 |
| `EventHandler` | **MODIFIED** | ctor takes bus; routes = base literal + injected `LiveRouteRegistrar` additions; `ErrorPolicy` injected (P9) | `[ORACLE]` backtest base routes only | P2/P7/P9 |
| `BacktestRunner` | **MODIFIED** | `engine.global_queue.put` → `engine.bus.put`; `UniverseWiring` call extracted | `[ORACLE]` | P3, P7 |
| `OrderHandler` / `StrategiesHandler` | **MODIFIED** | adopt `PortfolioHandler`'s `environment`/`sql_engine`/`storage=` shape; expose `.storage` read-back | `[ORACLE]` in-memory same-instance | P3 |
| `SqlBackend → SqlEngine` (`storage/backend.py → engine.py`) | **MODIFIED** | mechanical rename; migrations → project root | `[INERT]` lazy | P4 |
| `SystemStore` / `VenueStore` / `StrategyRegistryStore` | **NEW** | durable KV + cardinality-N tables; `HaltRecordStore` template | `[INERT]` live-only, in-memory fallback | P5 |
| `ExecutionVenueRegistry` + `DataProviderRegistry` + `VenuePlugin`/`VenueBundle` | **NEW** | 4-collaborator venue bundle; kills every `if self.exchange==` | `[INERT]` lazy-import concretions in `build_bundle` | P6 |
| `LiveDataProvider` Protocol + `BaseLiveDataProvider` | **NEW** | formal provider contract; no-op optional seams | — | P6 |
| shared `StreamSupervisor` | **NEW** | collapses triplicated `_run_stream_supervisor` | — | P6 |
| `LiveRunner` | **NEW** | replaces `_event_processing_loop`; drain + workers + ErrorPolicy | — | P7 |
| `build_live_system` factory | **NEW** | live composition root | `[INERT]` all SQL/ccxt imports lazy here | P7 |
| `SessionInitializer` + shared `UniverseWiring` | **NEW (extract)** | universe/route wiring; `UniverseWiring` shared with backtest | `[ORACLE]` pure code-motion | P7 |
| `LiveRouteRegistrar` | **NEW** | declarative live route composition (no subclass, no runtime mutation) | `[ORACLE]` backtest gets none | P7 |
| `UniverseHandler` | **MODIFIED** | first-class ctor at live root; zero OKX coupling via `set_venue_metadata` | `[INERT]` routes explicit-empty on backtest | P7 |
| `StrategyWarmupConsumer` (rehomed `_LiveWarmupConsumer`) | **MODIFIED (rehome)** | `price_handler/feed/cache_registration.py`; sized `max(warmup)` | — | P7 |
| `SafetyController` | **NEW (extract)** | status latch, halt/pause, deferred-protective queue, dispatch gate | — | P8 |
| `StreamRecoveryHandler` | **NEW (extract)** | reconnect resume I/O on engine thread | — | P8 |
| `ReconciliationCoordinator` | **NEW (extract)** | rehydrate → reconcile → baseline guard; iterates portfolios | — | P8 |
| CONTROL routes (`STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`) | **NEW** | flag machinery → events | — | P8/P10 |
| `ErrorPolicy` + `ErrorHandler` + CF-1 circuit breaker | **NEW (extract+add)** | injected failure policy; formalized ERROR consumer; aggregate tripwire | `[ORACLE]` backtest fail-fast identical | P9 |

**Deleted:** `_OkxPrecisionResolver`, `_precision_to_scale`, `_link_venue_account_to_portfolios` (+ its `RuntimeError(>1)` guard), `print_status`, `get_statistics`, the flag side-channel methods, `run_paper_replay` (→ `tests/`), `_PAPER_*`/`_OKX_*` module constants.

---

## Recommended structure — new & relocated files

```
itrader/
├── events_handler/
│   ├── bus.py                          # NEW P2 — EventBus Protocol + Fifo/Priority
│   └── full_event_handler.py           # MODIFIED P2/P7/P9 — bus ctor, injected routes+policy
├── trading_system/
│   ├── compose.py                      # MODIFIED P2/P3 — compose_engine(ctx, spec)
│   ├── engine_context.py               # NEW P3 — EngineContext frozen dataclass
│   ├── build_live_system.py            # NEW P7 — live factory / composition root
│   ├── live_runner.py                  # NEW P7 — LiveRunner drain
│   ├── live_trading_system.py          # SHRUNK P7 — thin facade ~200 lines
│   ├── session_initializer.py          # NEW P7 — SessionInitializer
│   ├── universe_wiring.py              # NEW P7 — shared UniverseWiring [ORACLE]
│   ├── live_route_registrar.py         # NEW P7 — declarative live routes
│   ├── safety_controller.py            # NEW P8
│   ├── stream_recovery_handler.py      # NEW P8
│   ├── reconciliation_coordinator.py   # NEW P8
│   └── error_policy.py / error_handler.py  # NEW P9
├── execution_handler/
│   ├── venue/registry.py, plugin.py, bundle.py, lifecycle.py  # NEW P6
│   └── stream_supervisor.py            # NEW P6 — shared
├── price_handler/
│   ├── providers/base_live_provider.py # NEW P6 — LiveDataProvider Protocol
│   └── feed/cache_registration.py      # MODIFIED P7 — StrategyWarmupConsumer
└── storage/
    ├── engine.py                       # RENAMED P4 (was backend.py)
    ├── system_store.py, venue_store.py, strategy_registry_store.py  # NEW P5
    └── (migrations moved OUT →) <repo-root>/migrations/            # RELOCATED P4
```

**Structure rationale:** live-only modules live in their handler's package but are **never re-exported from a backtest-path `__init__` barrel** — that is the mechanical rule that keeps the inertness gate green. `build_live_system` is the single place lazy SQL/ccxt imports are allowed.

---

## Architectural Patterns — the integration seams

### Pattern 1: EventBus as a drop-in `queue.Queue` surface `[ORACLE][INERT]`

**What:** A small `EventBus` Protocol (`put`, `get(timeout)`, `get_nowait`, `qsize`, `empty`, `depth_by_tier`). `FifoEventBus` wraps `queue.Queue`; `PriorityEventBus` wraps `queue.PriorityQueue` keyed `(tier, seq, event)`.

**Why the `.put()` call sites don't change (the load-bearing claim):** handlers receive the bus **in the same constructor slot they receive `global_queue` today** and keep calling `self.global_queue.put(event)`. The bus is API-compatible with `queue.Queue.put`. Tier assignment happens **inside** `PriorityEventBus.put` by consulting a declarative `_CONTROL_EVENT_TYPES` frozenset — no call-site edits. The monotonic `seq` (`itertools.count()`) guarantees the tuple comparison never falls through to the (non-orderable, frozen) event and preserves strict FIFO within a tier.

**Why zero oracle risk:** backtest injects `FifoEventBus`; its `get_nowait()` re-raises `queue.Empty`, so `EventHandler.process_events()` (lines 125-130, the `get_nowait()`+`queue.Empty`→`break` drain) is **unchanged**. The priority bus is only ever constructed by `build_live_system` and never touches `BacktestRunner`/`process_events()`.

**Backtest vs live drain divergence:** backtest keeps `process_events()` → `bus.get_nowait()` (drain-to-empty). Live's `LiveRunner` uses `bus.get(timeout)` (blocking, wakes on CONTROL events). Same bus Protocol, two consumers.

### Pattern 2: EngineContext threaded once (LR-14) `[INERT]`

**What:** `@dataclass(frozen=True) EngineContext(bus, config: RuntimeConfig, environment: str, sql_engine: Optional[SqlEngine])`. Infra-only. `compose_engine(ctx, spec)` hands each handler only what it needs.

**Signature ripple (traced concretely against current `compose.py`):** today `compose_engine` is keyword-only over `order_storage, signal_store, csv_paths, start_date, end_date, timeframe, exchange_config, order_config, results_store` and creates `global_queue = queue.Queue()` internally (line 164). After P3:
- `queue.Queue()` creation is **deleted** — `compose_engine` reads `ctx.bus`.
- `order_storage`/`signal_store` params **removed** — handlers build their own from `ctx.environment`/`ctx.sql_engine` (Pattern 3); `compose_engine` reads the concrete back off `.storage`.
- `csv_paths`/`start_date`/`end_date`/`timeframe`/`exchange_config`/`order_config`/`results_store` **move into `spec`** (`SystemSpec` already exists and is mode-agnostic).
- The `Engine` holder's `global_queue` field → `bus`.

**Byte-exactness contract:** backtest factory builds `EngineContext(bus=FifoEventBus(queue.Queue()), config=<defaults>, environment='backtest', sql_engine=None)`. The wiring body of `compose_engine` (lines 169-246: clock → store → feed → screeners → portfolio → execution → commission estimator → strategies → order → `set_order_storage` → time_generator → EventHandler) stays in the exact same order → identical graph → byte-exact.

### Pattern 3: Handler-owns-storage-init (LR-13) `[ORACLE]`

**What:** `OrderHandler`/`StrategiesHandler` adopt the shape `PortfolioHandler` already ships (`portfolio_handler.py:68-69`: `environment='backtest', backend=None` → `PortfolioStateStorageFactory.create(environment=..., backend=...)`):

```python
OrderHandler(..., *, environment='backtest', sql_engine=None, storage=None)
    → self.storage = storage or OrderStorageFactory.create(environment, backend=sql_engine)
```

The factory already exists with exactly this signature: `OrderStorageFactory.create(environment: str, backend: Optional[SqlBackend]=None)` (`storage/storage_factory.py:24-25`).

**The read-back seam (byte-exact-critical):** currently `compose_engine` receives `order_storage` and injects the **same instance** into both `OrderHandler` and `portfolio_handler.set_order_storage(order_storage)` (line 234). After P3, `OrderHandler` builds it internally (via `OrderManager`, which owns storage per D-18 — the handler retains no ref). So P3 must add a `.storage` read-back property on `OrderHandler` returning the **actual instance `OrderManager` holds**, and `compose_engine` calls `portfolio_handler.set_order_storage(order_handler.storage)`. Backtest env→`InMemoryOrderStorage`, same instance both places → byte-exact. **Flag:** if the read-back returns a copy or a different instance, the BAR-route liquidation forced-close (LIQ-03) writes to the wrong mirror — silent divergence.

### Pattern 4: LiveRouteRegistrar — routes composed at construction, not mutated (LR-16) `[ORACLE][INERT]`

**What:** The single `EventHandler` already carries explicit-empty live slots in its routes literal (`full_event_handler.py:105-111`): `SCREENER`, `UPDATE`, `UNIVERSE_UPDATE`, `UNIVERSE_POLL`, `STRATEGY_COMMAND`, `BARS_LOADED`, `BARS_LOAD_FAILED` are all `[]`. Backtest keeps them empty (proven inert by `test_okx_inertness`). Live composes consumers **into** these lists + adds the NEW CONTROL routes.

**Integration mechanism (no subclass, no runtime mutation):** `EventHandler.__init__` gains an optional `extra_routes: dict[EventType, list[Callable]] | None = None` merged into the base literal at construction. `LiveRouteRegistrar` builds the live additions; `build_live_system` passes them in. Backtest passes `None` → base routes only. This modifies `EventHandler.__init__` — **`[ORACLE]`: the base literal must be byte-identical when `extra_routes` is None.**

**New EventType members required in P2** (so `PriorityEventBus._CONTROL_EVENT_TYPES` can reference them): `STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE` are **new** in `core/enums/event.py`; `STRATEGY_COMMAND`, `BARS_LOADED`, `BARS_LOAD_FAILED` already exist. `_dispatch` raises `NotImplementedError` on unrouted types, but backtest never *emits* the CONTROL types, so no backtest route is strictly required — adding explicit-empty entries (matching the existing pattern) is the safer, convention-consistent choice.

### Pattern 5: Shared UniverseWiring extraction (§13a) `[ORACLE]` — the highest-risk seam

**What:** `BacktestRunner._initialise_backtest_session` (`backtest_runner.py:50-131`) contains the ordered block: `derive_membership → derive_instruments → WR-03 desync assert → Universe(...) → set on exchange/order/portfolio → feed.bind`, then **backtest-only** ping-grid `reduce(pd.Index.union)` + `time_generator.set_dates` + per-strategy `feed.precompute`.

**Extraction:** the common prefix (`derive_membership → … → feed.bind`, lines 64-113) moves into a shared `UniverseWiring` helper both `BacktestRunner` and the live `SessionInitializer` call. The ping-grid/precompute tail (lines 119-131) stays backtest-only.

**Why it's the riskiest oracle seam:** this is a **pure code-motion** refactor of the exact block that builds the `Universe` value object and injects it into three domains in a fixed order (`exchange.set_universe → order_handler.set_universe → portfolio_handler.set_universe → feed.bind`). It is the direct analog of the v1.2 MOD-01 order-manager decomposition (pure code-motion, byte-for-byte). The WR-03 desync assert (lines 84-90) and the injection ordering must move as **one intact unit**. Any reorder changes the graph → oracle breaks. **Recommend: byte-exact diff gate on this extraction specifically; no re-baseline permitted (LR-02 default target holds).**

### Pattern 6: Connector flag side-channel → CONTROL events (§4b/§11c)

**What:** The connector asyncio loop does only venue I/O + `bus.put()`; it never touches handler state. Stream/fatal signals that were `threading.Event` flags become CONTROL events on the priority bus:

| CONTROL event | Route → | Runs on |
|---|---|---|
| `StreamStateEvent(down)` | `SafetyController.pause_submission` | engine thread |
| `StreamStateEvent(up)` | `StreamRecoveryHandler.on_reconnect` | engine thread |
| `ConnectorFatalEvent(reason)` | `SafetyController.halt(reason)` | engine thread |

**Single-writer contract (LR-12):** all state mutation on the one engine thread; blocking venue I/O triggered by a stream event (resume snapshot, reconcile, durable halt write) runs on the **engine thread inside the CONTROL handler**, never on the connector loop. CONTROL preemption means a `pause_submission` jumps ahead of queued market data — the safety-latency reason for the two-tier bus.

---

## Data Flow

### Backtest path (unchanged behavior, new plumbing)

```
BacktestRunner._run_backtest loop (byte-exact ordering, Trap 4):
  clock.set_time → bus.put(TimeEvent) → EventHandler.process_events()
    → bus.get_nowait() drain → _dispatch per base route
  → portfolio.record_metrics(time)  [DIRECT call, never a reroute]
  → on_tick hook
```
Only change: `engine.global_queue.put` → `engine.bus.put` (FifoEventBus, identical FIFO).

### Live path (new)

```
connector asyncio loop (daemon)            engine thread (LiveRunner)
  venue I/O                                  bus.get(timeout)  ← wakes on CONTROL
  ├─ fill/bar    → bus.put(BUSINESS) ──┐        │
  └─ stream/fatal→ bus.put(CONTROL) ───┼──────► _dispatch via injected ErrorPolicy
                                       │        ├─ CONTROL: pause/resume/halt (engine-thread I/O)
                    [queue = bulkhead] │        └─ BUSINESS: BAR→SIGNAL→ORDER→FILL (existing flow)
```

### Runtime-config mutation (P10★, scoped)

```
ConfigUpdateEvent(scope, key, value) → CONTROL plane → engine-thread handler
  → route to owner (system→SystemStore, portfolio:{id}→Portfolio+store, venue:{name}→VenueStore)
  → apply to RuntimeConfig overlay + handler.update_config(...) + persist
  → on restart: build_live_system layers persisted overrides over defaults
```

---

## Build-Order Validation — §16 P1→P13 confirmed, with 4 refinements

The overall sequence is **sound**: foundation (config → bus → context → sql → stores) → venue registry → God-object teardown → safety/error → ★ feature-adds → test migration. Dependencies below are real (file-level), and I challenge 4 entries in the §16 table:

| # | Phase | §16 deps | Verdict | Refinement |
|---|-------|----------|---------|-----------|
| P1 | Config centralization | — | ✓ | Hosts CF-8 `HaltReason` enum + CF-6 doc; lazy `sql` accessor is the inertness lever. |
| P2 | Event bus | — | ✓ w/ note | **Must add the NEW CONTROL EventType members** (`STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`) here — `_CONTROL_EVENT_TYPES` references them, even though consumers land P8/P10. |
| P3 | EngineContext + storage-in-handler | P1 | ⚠ **add P2** | `EngineContext.bus` needs the `EventBus` type/instance from P2. The table omits P2→P3. **Recommend P3 deps = {P1, P2}.** |
| P2+P3 | compose_engine | — | ⚠ double-edit | **P2 and P3 both mutate `compose_engine`'s signature/body** (P2 injects the bus; P3 folds bus+config+env+sql into `EngineContext` and drops storage params). Options: (a) accept the small re-edit, or (b) introduce a minimal `EngineContext` skeleton in P2 so the signature settles once. Prefer (b). |
| P4 | SqlEngine rename + migrations relocation | P3 | ⚠ ordering | `EngineContext.sql_engine` is typed `Optional[SqlEngine]` in §7a, but the `SqlBackend→SqlEngine` **rename lands in P4, after P3**. Either do the *rename* in/before P3 (P3 references the new name) or let P3 use `SqlBackend` and P4 sweeps `EngineContext` too. The *migrations relocation* is genuinely independent and stays P4. **Recommend: split P4 — rename folds into P3, relocation stays P4-standalone.** |
| P5 | New stores | P4 | ✓ | Chains Alembic onto relocated `migrations/`; live-only, in-memory fallback keeps backtest dark. |
| P6 | Venue registry + bundle | P2, P3 | ✓ | Needs bus (CONTROL emitters) + EngineContext. CF-3/4/9 fold here. `[INERT]` lazy `build_bundle`. |
| P7 | LiveRunner + factory + facade + UniverseWiring | P5, P6 | ✓ | Transitively needs P2 (LiveRunner `bus.get(timeout)`). **UniverseWiring is `[ORACLE]` — gate it hardest.** |
| P8 | Safety + reconciliation + stream recovery | P7 | ✓ | CONTROL routes consume P2's new EventTypes; flag machinery deleted. CF-2/7/8. |
| P9 | Error subsystem | P7 | ✓ | `ErrorPolicy` injection modifies `EventHandler.__init__` — `[ORACLE]` backtest fail-fast must stay identical to the current `_on_handler_error` bare-`raise`. CF-1 circuit breaker is the one added acceptance criterion. |
| P10★ | Runtime-config platform | P5, P8 | ✓ | CONFIG_UPDATE route (CONTROL). |
| P11★ | Strategies registry | P5, P7 | ✓ | STRATEGY_COMMAND route (already an empty slot today). |
| P12★ | Multi-portfolio-live | P6, P8 | ✓ | Drops the single-portfolio guard + `_link_venue_account_to_portfolios`; connector keyed `(venue, account_id)`. |
| P13 | Replay→fixture + gates | P7, P12 | ✓ | Lands last; production replay-free. |

**Net:** no cycle, no blocker. The only substantive corrections are **P3 must depend on P2**, and the **compose_engine signature should settle in one step** (fold a minimal EngineContext into P2) rather than editing the same param list twice. The P4 rename-vs-relocation split is a nicety, not a blocker.

---

## Anti-Patterns to avoid (from spec + existing conventions)

### Anti-Pattern 1: Subclassing EventHandler for live routes
**What people do:** create `LiveEventHandler(EventHandler)` overriding `routes`. **Why wrong:** two dispatch surfaces to reason about; the inertness proof (base-routes-only) evaporates. **Instead:** LR-16 — one data-driven `EventHandler`, live routes injected at construction via `LiveRouteRegistrar`.

### Anti-Pattern 2: Runtime `routes` mutation
**What people do:** `event_handler.routes[EventType.X].append(consumer)` at `start()`. **Why wrong:** non-declarative, order-fragile, breaks the "change routing in one reviewable literal" contract. **Instead:** compose routes once at construction.

### Anti-Pattern 3: Changing `.put()` call sites for the priority bus
**What people do:** add `bus.put(event, tier=CONTROL)` across handlers. **Why wrong:** touches every handler, breaks byte-exactness risk surface, re-litigates the queue-only contract. **Instead:** the bus assigns the tier from `_CONTROL_EVENT_TYPES` inside `put`; call sites stay `self.global_queue.put(event)`.

### Anti-Pattern 4: Reordering the UniverseWiring block during extraction
**What people do:** "tidy" the injection order (exchange/order/portfolio/feed.bind) while extracting. **Why wrong:** the ordering IS the byte-exact contract (Trap 4). **Instead:** move the block verbatim as one unit; diff-gate against the oracle.

### Anti-Pattern 5: Hoisting a live import to module scope
**What people do:** `import ccxt.pro` / `from itrader.storage.system_store import SystemStore` at a backtest-reachable module top. **Why wrong:** fails `test_okx_inertness`, silently pulls async/SQL onto the hot path. **Instead:** lazy-import inside `build_live_system` / `VenuePlugin.build_bundle`; never re-export live modules from a backtest-path barrel.

### Anti-Pattern 6: `Decimal(float)` / tab-space normalization
Carried project constraints: money enters Decimal only via `to_money`; handler modules use **tabs**, `config/`/`core/`/`price_handler/feed/`/`events_handler/events/` use **4 spaces** — match the file, never normalize (`bus.py` under `events_handler/` → 4 spaces; `trading_system/` new files → tabs).

---

## Integration Points

### Internal boundaries (where v1.8 seams meet existing code)

| Boundary | Communication | Notes / Gate |
|----------|---------------|--------------|
| factory ↔ `compose_engine` | `EngineContext` + `SystemSpec` (data) | `[ORACLE]` backtest arm identical graph |
| handlers ↔ bus | `global_queue`-slot injection; `.put()` API-compatible | `[ORACLE]` no call-site change; `[INERT]` Fifo light |
| `compose_engine` ↔ handlers | reads `.storage` back after handler-owns-init | `[ORACLE]` same in-memory instance into `set_order_storage` |
| `EventHandler` ↔ live controllers | `LiveRouteRegistrar` extra_routes at ctor | `[ORACLE]` None on backtest = base routes |
| connector loop ↔ engine thread | bus (CONTROL/BUSINESS) — the bulkhead | single-writer; blocking I/O on engine thread only |
| `VenueRegistry` ↔ `ExecutionHandler` | registry distributes exchange into existing `register_exchange` sub-registry | `on_order` already routes by `event.exchange` |
| new stores ↔ composition root | built by factory over shared `sql_engine`, handed to controllers | `[INERT]` live-only; `HaltRecordStore` template |
| `BacktestRunner`/`SessionInitializer` ↔ `UniverseWiring` | shared helper call | `[ORACLE]` pure code-motion |
| `EventHandler` ↔ `ErrorPolicy` | injected at ctor (removes `_on_handler_error` monkeypatch) | `[ORACLE]` backtest fail-fast identical |

### External services (unchanged integration patterns)
| Service | Pattern | Notes |
|---------|---------|-------|
| OKX | `OkxConnector` (one asyncio loop + one `ccxt.pro` client) | `[INERT]` lazy in `build_bundle`; creds per-`account_id` in env `OkxSettings`, never persisted |
| Postgres | shared `SqlEngine` (was `SqlBackend`) | `[INERT]` lazy `sql` accessor; raises without credential |

---

## Oracle- & Inertness-sensitive seam register (roadmap must flag these per phase)

| Seam | Gate | Phase | Failure mode if mishandled |
|------|------|-------|----------------------------|
| `compose_engine` signature + wiring-order | `[ORACLE]` | P2/P3 | any reorder → graph diff → oracle breaks |
| `FifoEventBus` FIFO/`queue.Empty` parity | `[ORACLE][INERT]` | P2 | non-FIFO or missing `queue.Empty` → drain misbehaves |
| Handler-owns-init `.storage` read-back | `[ORACLE]` | P3 | different instance → LIQ-03 writes wrong mirror |
| `EngineContext(sql_engine=None)` / lazy `sql` | `[INERT]` | P1/P3 | Postgres `SqlSettings` at import → inertness fails |
| `EventHandler` route composition (extra_routes None) | `[ORACLE]` | P7 | base literal drift → routing diff |
| **UniverseWiring extraction** | `[ORACLE]` | P7 | reorder/split injection → oracle breaks (**highest risk**) |
| `ErrorPolicy` injection (backtest fail-fast) | `[ORACLE]` | P9 | non-re-raising default → silent state corruption |
| Venue plugin lazy `build_bundle` | `[INERT]` | P6 | eager `ccxt.pro` import → inertness fails |
| New stores / live modules not re-exported | `[INERT]` | P5/P7/P8 | barrel re-export → SQL/async on hot path |
| `test_okx_inertness` forbidden list | `[INERT]` | P5-P12 | new live modules must be added to the probe's `_FORBIDDEN` |

---

## Sources

- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` (LR-00..LR-22, CF-1..CF-10, §4/§5/§7/§13/§16) — HIGH (authoritative design)
- `itrader/trading_system/compose.py`, `backtest_runner.py`, `events_handler/full_event_handler.py`, `portfolio_handler/portfolio_handler.py`, `order_handler/order_handler.py`, `order_handler/storage/storage_factory.py`, `storage/backend.py`, `tests/integration/test_okx_inertness.py` — HIGH (real code traced)
- `.planning/PROJECT.md` (Current Milestone v1.8) + `CLAUDE.md` (architecture) — HIGH

---
*Architecture research for: v1.8 Live System Refactor integration mapping*
*Researched: 2026-07-09*
