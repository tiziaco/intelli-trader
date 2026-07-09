# Phase 2: Event Bus - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Introduce a stdlib two-tier `EventBus` (`itrader/events_handler/bus.py`) — `FifoEventBus`
(backtest, thin `queue.Queue` wrapper) + `PriorityEventBus` (live, `PriorityQueue` keyed
`(tier, seq, event)`) — behind one `.put(event)` surface; add the three new CONTROL `EventType`
members; and **settle `compose_engine`'s signature to its end-state `(ctx, spec)` form** via a
frozen `EngineContext` — **without disturbing the byte-exact backtest oracle
(`134 / 46189.87730727451`) or the OKX import-inertness gate** (`tests/integration/test_okx_inertness.py`).

Delivers (BUS-01..04 + the pulled-forward CTX-01/CTX-02 — see D-03):
- `EventBus` Protocol (`put`/`get`/`get_nowait`/`qsize`/`empty`/`depth_by_tier`) with two
  byte-compatible implementations sharing one `.put()`.
- New CONTROL `EventType`s (`STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`) + a declarative
  `_CONTROL_EVENT_TYPES` frozenset.
- A frozen `EngineContext` (`bus`/`config`/`environment`/`sql_engine`) threaded once into
  `compose_engine(ctx, spec)`, with Order + Strategies handlers owning their storage init.
- Backtest wires `FifoEventBus` at **zero oracle risk**; the priority bus is backtest-dark.

This is an **oracle-gated foundation phase** — blast radius is the enemy. The owner chose the
end-state `(ctx, spec)` signature (Option B) over the minimal prepend-ctx form, accepting a wider
P2 in exchange for never re-editing the signature downstream. The heavy SQL/migrations/rename work
stays in P3/P4.

</domain>

<decisions>
## Implementation Decisions

### `compose_engine` signature (BUS-04) — OWNER OVERRIDE OF SPEC PHASING
- **D-01:** The signature settles to the design's **end-state two-arg form `compose_engine(ctx, spec)`**
  (spec §5) — reached in P2 so it is **never re-edited** downstream. This is Option B, chosen over the
  minimal "prepend `ctx`, keep the 8 kwargs" form. The backtest factory builds the `FifoEventBus` + the
  `EngineContext` and injects it; the internal `queue.Queue()` at `compose.py:164` is **deleted**.
- **D-02:** Storage placement = **handlers own their storage init** (spec §7b / LR-13). Order + Strategies
  handlers adopt `PortfolioHandler`'s **existing** shape (`OrderHandler(..., *, environment, sql_engine,
  storage=None) → self.storage = storage or OrderStorageFactory.create(environment, backend=sql_engine)`);
  `compose_engine` reads the concrete back off `.storage` for the `portfolio_handler.set_order_storage(...)`
  wiring. **Backtest slice only** — `environment='backtest', sql_engine=None` → the same in-memory storage
  instances as today → byte-exact.
  - **Rejected:** B2 (putting `order_storage`/`signal_store` backend instances onto `SystemSpec` — pollutes
    the declarative spec) and B3 (hybrid `(ctx, spec, *, order_storage, signal_store)` — reintroduces the
    P3 double-edit). The clean two-arg form only pays off *with* handler-owned storage.
- **D-03 (PHASING / TRACEABILITY SHIFT):** Choosing D-01+D-02 means **P2 absorbs CTX-01
  (`compose_engine(ctx, spec)`) and CTX-02 (storage-in-handler)** — both scheduled as **P3** in the design
  (§16) and REQUIREMENTS.md. **P3 shrinks** to CTX-03 (`SqlBackend→SqlEngine` rename) + CTX-04 (lazy-import
  guard). This is a deliberate owner-directed roadmap reshape (like P1's cardinality override), same total
  work, P2/P3 merged on the compose seam. **Downstream must NOT "fix" this back.** REQUIREMENTS.md/ROADMAP.md
  traceability should be updated so CTX-01/CTX-02 point at P2 (see Deferred → action item).
- **D-04:** The kwargs→spec fold is **mostly 1:1 with existing `SystemSpec` fields** — `csv_paths→data`,
  `start_date→start`, `end_date→end`, `timeframe→timeframe`, `exchange_config←exchange` (factory already
  derives `ExchangeConfig` from `spec.exchange`), `results_store→results_store` (already on the spec). The
  **one** kwarg without a spec field is `order_config`; planner decides: keep it **handler-owned** via
  `OrderConfig.default()` (consistent with P1 D-03 "order lives with its owner", **leaned**) or add a spec
  field. This clean mapping is what makes B low-risk despite the wider surface.

### `EngineContext` skeleton
- **D-05:** Frozen dataclass with **all 4 fields now** (spec §7a): `bus: EventBus`, `config`,
  `environment: str`, `sql_engine`. `bus`/`environment`/`sql_engine` are **actively consumed in P2** (handlers
  derive storage from `environment`+`sql_engine`); `config` is carried but **unread until P9**. **Loose types**
  for the not-yet-built pieces: `config` typed as today's `SystemConfig` (P9 widens/swaps to `RuntimeConfig`);
  `sql_engine: Optional[...] = None` (the concrete `SqlEngine` type lands with the P3/P4 rename). **P3/P4/P9
  only tighten types — never add fields.** Settling the full shape once matches the reason B was chosen.
- **D-06:** Backtest factory constructs `EngineContext(bus=FifoEventBus(), config=<the SystemConfig>,
  environment='backtest', sql_engine=None)`. `sql_engine=None` + `FifoEventBus` **pull nothing heavy** →
  inertness gate stays green (extended register-vs-build assertion).

### `EventBus` Protocol + `FifoEventBus` (bus reach / blast radius)
- **D-07:** **Full bus swap** — every handler constructor that takes `global_queue` now receives the
  `FifoEventBus` in its place (duck-typed `.put()`, **no `.put` call-site changes**, BUS-01); `EventHandler`
  drains via `bus.get_nowait()`/`bus.empty()`. `FifoEventBus` is a thin wrapper over `queue.Queue` → **byte-identical
  FIFO** → oracle safe. Boundary-only wrapping was rejected as a throwaway seam given the compose rewrite.
- **D-08:** The constructor **parameter name stays `global_queue`/`events_queue`** (CLAUDE.md naming
  convention: "the shared event queue is always named `global_queue` or `events_queue`") — **retyped** to
  `EventBus`. Do NOT rename the param to `bus` (breaks the documented convention + widens the diff).
- **D-09:** Protocol surface = `put`, `get(timeout)`, `get_nowait`, `qsize`, `empty`, `depth_by_tier`
  (§4a). `bus.py` lives at `itrader/events_handler/bus.py`, **4-space indent** (the `events_handler/events/`
  package convention — NOT the tab handler-module convention).

### `PriorityEventBus` + CONTROL events (live-wiring boundary)
- **D-10:** P2 = **define `PriorityEventBus` + unit-test only** (Option 1). Ship the full substrate:
  `PriorityEventBus` (`PriorityQueue` keyed `(tier, seq, event)`; `tier ∈ {CONTROL=0, BUSINESS=1}` assigned
  from `_CONTROL_EVENT_TYPES`; `seq = itertools.count()` — thread-safe, globally-unique); the **BUS-02
  ordering test** (proves the tuple comparison never dereferences the non-orderable frozen event, and strict
  within-tier FIFO holds); the 3 new CONTROL `EventType`s in `core/enums/event.py`; and `_CONTROL_EVENT_TYPES`.
- **D-11:** **ZERO live wiring in P2** — `live_trading_system.py` stays untouched on its raw `queue.Queue`
  until P6/P7. Rationale: (a) the 3 new CONTROL events have **no producers/consumers** until P6/P7/P8
  (`SafetyController`/`StreamRecoveryHandler`/connector→CONTROL-route handoff); (b) the **one existing**
  CONTROL event `STRATEGY_COMMAND` already flows through the live queue — swapping to priority now would
  **silently change validated v1.7 live ordering** (preemption) with **no live-smoke gate until P12**; (c) the
  live drain loop + flag side-channel (`_pending_stream_resume`/`_pending_connector_halt`) is **deleted and
  rewritten by `LiveRunner`** in P6/P7 anyway, so Option 2 saves no work and creates a half-migrated
  intermediate. **Option 2 (wire live now) explicitly rejected.**

### Tier assignment (spec §4a — finalize in P2)
- **CONTROL** (preempts market data): `STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`, `STRATEGY_COMMAND`.
- **BUSINESS** (strict FIFO): `BAR`, `SIGNAL`, `ORDER`, `FILL`, `UNIVERSE_*`, `BARS_*`, `ERROR`,
  `PORTFOLIO_UPDATE` (plus existing `TIME`/`UPDATE`/`ORDER_ACK`/`SCREENER`). **Externally-injected `SIGNAL`s
  stay BUSINESS** (must interleave in order with bars/fills — control priority is for operational commands,
  not trading intents).

### Claude's Discretion
- The `EngineContext` class **home/module** (near `compose_engine` in `trading_system/`, or `events_handler/`
  — pick to avoid an import cycle with `EventBus`).
- `FifoEventBus.depth_by_tier` exact shape (FIFO is tierless — a single-bucket mapping such as
  `{BUSINESS: qsize}` is fine; must satisfy the Protocol).
- Whether to add an **optional standalone integration test** driving a representative CONTROL+BUSINESS
  interleaving through `PriorityEventBus` (no `live_trading_system.py` touch) for integration confidence
  beyond unit tests — the better buy than wiring live.
- `order_config` home under the fold (D-04) — leaned handler-owned per P1 D-03.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source (the P2 contract)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` — **§4 (event bus &
  threading model)** = `FifoEventBus`/`PriorityEventBus`, `(tier, seq, event)` keying,
  `_CONTROL_EVENT_TYPES`, tier assignment, single-writer engine-thread contract; **§5 (topology)** =
  the `compose_engine(ctx, spec)` end-state signature; **§7a–7b (`EngineContext` + storage-in-handler,
  LR-13/LR-14)** = the frozen `EngineContext` shape and handler-owns-init pattern. **Note the P2
  deviations D-01/D-02/D-03 above** — P2 pulls CTX-01/CTX-02 forward from P3.

### Requirements
- `.planning/REQUIREMENTS.md` — **BUS-01..BUS-04** (P2 as-scheduled) **plus CTX-01, CTX-02** (pulled into
  P2 per D-03; traceability update pending). CTX-03/CTX-04 remain P3.

### Roadmap
- `.planning/ROADMAP.md` — Phase 2 (Event Bus) success criteria + Phase 3 (which shrinks per D-03).

### Prior-phase decisions that bind here
- `.planning/phases/01-config-centralization/01-CONTEXT.md` — P1 **D-01** (config mutable-by-convention),
  **D-03** (order config lives with its owner — informs D-04's `order_config` lean), **D-05** (lazy `sql`
  accessor — the inertness seam `EngineContext.sql_engine=None` must not disturb).

### Gates (must stay green — verify after every plan)
- `tests/integration/test_backtest_oracle.py` — SMA_MACD byte-exact oracle (`134 / 46189.87730727451`).
- `tests/integration/test_okx_inertness.py` — extended register-vs-build assertion: `FifoEventBus` /
  `EngineContext(sql_engine=None)` pull nothing heavy; import constructs no `SqlSettings`.

### Code touchpoints
- `itrader/trading_system/compose.py` (`compose_engine` :116, internal `queue.Queue()` :164 deleted),
  `itrader/trading_system/backtest_trading_system.py` (`build_backtest_system` :401/:437,
  `BacktestTradingSystem.__init__` compose call :131), `itrader/trading_system/system_spec.py` (`SystemSpec`
  fields for the kwargs→spec fold), `itrader/events_handler/full_event_handler.py` (`EventHandler` drain
  :66/:127 → `bus.get_nowait()`), `itrader/core/enums/event.py` (`EventType` — add 3 CONTROL members),
  `itrader/portfolio_handler/portfolio_handler.py` (the handler-owns-storage template),
  `itrader/trading_system/live_trading_system.py` (**untouched** in P2 per D-11).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`PortfolioHandler` already owns its storage** — it is the exact template Order + Strategies handlers
  adopt for D-02. No new pattern is invented; two handlers adopt an established one.
- **`SystemSpec` already carries `data`/`start`/`end`/`timeframe`/`exchange`/`results_store`/`actions`**
  (`system_spec.py`) — so the D-01 kwargs→spec fold is mostly 1:1 with existing fields (this is what makes
  Option B low-risk). `results_store` is already typed `Any` on the spec to stay SQL-import-inert.
- **`OrderStorageFactory.create(environment, backend=...)`** — the factory the handler-owned init calls;
  backtest → in-memory regardless of `backend`, so D-02's backtest slice needs no `SqlEngine`.
- **`itertools.count()`** (stdlib) — the thread-safe monotonic `seq` source for `PriorityEventBus`; zero
  new dependency (milestone gate: no poetry change in P1–P12).

### Established Patterns
- `EventType` enum (`core/enums/event.py`) already holds `STRATEGY_COMMAND`, `UNIVERSE_POLL`, `BARS_LOADED`,
  `BARS_LOAD_FAILED` from v1.7 — the 3 new CONTROL members slot alongside.
- Import-side-effect singletons (`itrader/__init__.py` builds `config`, `idgen`) — `EngineContext.config`
  carries the existing `SystemConfig` instance in P2 (loose type, D-05).
- Indentation split: `events_handler/events/` = 4-space; handler modules = tabs. New `bus.py` follows the
  4-space events-package convention (D-09); the handler-ctor edits for the bus swap (D-07) touch tab files —
  match each file, never normalize.

### Integration Points
- `compose_engine` grows a leading `ctx: EngineContext` and reads run config off `spec`; its internal
  `queue.Queue()` is deleted (D-01). The backtest factory builds `ctx` + `FifoEventBus` and injects.
- Every handler constructor's `global_queue` param is **retyped** to `EventBus` (name unchanged, D-08); the
  `EventHandler` drain switches to `bus.get_nowait()`/`bus.empty()` (D-07).
- `live_trading_system.py` is **not** an integration point in P2 (D-11) — it stays on its raw queue.

</code_context>

<specifics>
## Specific Ideas

- The owner deliberately chose the **end-state `compose_engine(ctx, spec)` signature now** (Option B) over
  the smaller prepend-ctx form, on the "settle it once, never re-edit" principle — and, seeing that the
  clean two-arg form requires handler-owned storage, accepted pulling CTX-01/CTX-02 forward into P2 because
  that is exactly what the spec (§7b) already designed. This mirrors the P1 stance of reshaping the roadmap
  around a load-bearing design principle rather than following phase numbering mechanically.
- The **priority bus earns its keep only once CONTROL traffic exists** — so P2 builds and proves it in
  isolation and refuses to wire it into the human-validated live path before its producers/consumers (and
  live gates) land in P6/P7/P12.

</specifics>

<deferred>
## Deferred Ideas

- **REQUIREMENTS.md / ROADMAP.md traceability update** (action item, D-03) — move CTX-01 + CTX-02 into P2's
  requirement set; note P3 shrinks to CTX-03 (`SqlBackend→SqlEngine` rename) + CTX-04 (lazy-import guard).
  Do this before/at planning so the plan-checker's decision-coverage gate sees CTX-01/02 cited under P2.
- **Wiring `PriorityEventBus` into the live system** — P6/P7, when `LiveRunner` replaces
  `_event_processing_loop` and the connector→CONTROL-route handoff + flag-machinery deletion land.
- **`RuntimeConfig` overlay** — P9; P2's `EngineContext.config` is a loose-typed placeholder (today's
  `SystemConfig`) until then.
- **`SqlBackend→SqlEngine` rename + migrations relocation** — P3/P4; P2's `EngineContext.sql_engine` is
  typed loosely (`Optional[...] = None`) and only exercised on the `None` (backtest/in-memory) path.
- **`order_config` onto `SystemSpec`** — only if the planner rejects the handler-owned lean in D-04.

</deferred>

---

*Phase: 2-Event Bus*
*Context gathered: 2026-07-09*
