# Phase 4: Retention + Live Write-Through (#2 — live path) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the **two-knob retention machinery** that turns the Phase-3 SQL backends into a long-running,
restart-safe live system of record — write-through, a bounded working-set cache, purge-on-terminalize,
read-through, and restart rehydration — and prove it on **testcontainers Postgres**. Backtest stays
**write-through OFF** (zero hot-path serialization; backend-selection at wiring, the backtest backend
contains no per-tick serialization code).

The new behavior lives in a **per-concern wrapper** (`CachedSql<Concern>Storage`, see D-04) that
composes an in-memory working set + the Phase-3 `Sql<Concern>Storage`. The wrappers are built,
integration-tested against real Postgres, and returned by each factory's `'live'` arm — but **the
live composition root is NOT rewired this phase** (see D-01 for the deliberate scope line).

**Requirements (from REQUIREMENTS.md):** RETAIN-01, RETAIN-02, RETAIN-03 (+ GATE-01 bound here, GATE-02
recurring).

**In scope:**
- The three `CachedSql<Concern>Storage` wrapper classes (order, portfolio-state, signal), each
  implementing its existing ABC, composing the in-memory working set + the Phase-3 `Sql*Storage`.
- Write-through (synchronous-in-txn for create/terminalize — Pitfall 8), purge-on-terminalize with the
  terminal-state gate (D-02), read-through fallback, restart rehydration (D-03).
- Wire each factory's **`'live'` arm** to return the wrapper (the order path is exercised end-to-end —
  `LiveTradingSystem` already calls `OrderStorageFactory.create('live', …)`).
- Integration tests on testcontainers Postgres: evict-then-read-through, flat-RSS long-run,
  bracket-parent-resident, open-only rehydration, crash-after-emit/restart-equals-pre-crash.

**Out of scope (deferred — see Deferred Ideas):**
- Rewiring `LiveTradingSystem`'s composition root — `Portfolio.__init__`'s hardcoded `"backtest"`
  state storage (`portfolio.py:93`) and the hardcoded `'backtest'` signal store
  (`live_trading_system.py:113`) are **left as-is**; closing those seams + a synthetic end-to-end
  event driver is **N+4** (D-01).
- Any real live feed / venue reconciliation (N+4).
- A reconciliation buffer window for terminal records (D-02 chose immediate purge — buffering is N+4's
  concern when reconciliation actually needs it).
- Cache classification (Phase 5).

</domain>

<decisions>
## Implementation Decisions

### Live-path scope — how far without a real feed (RETAIN-01/02/03)
- **D-01:** **Build the full retention machinery + integration-test it on testcontainers; wire the
  factory `'live'` arms to the wrappers; do NOT rewire the live composition root.** Rationale: every
  Phase-4 success criterion (SC2 evict-then-read / flat-RSS / bracket-resident; SC3 open-only rehydration
  / crash-after-emit) is a **component-level test against real Postgres** — none needs a live feed or a
  full `LiveTradingSystem` event-loop run. The order seam is exercised end-to-end **for free**
  (`LiveTradingSystem` already routes orders to `OrderStorageFactory.create('live', backend=…)`); the
  portfolio-state and signal wrappers are **built + component-tested** but their hardcoded-`"backtest"`
  seams in the live composition root (`portfolio.py:93`, `live_trading_system.py:113`) **stay untouched**.
  Rewiring the composition root + a synthetic end-to-end event driver is **N+4** (where the real feed
  lands and the whole loop is validated) — doing it now is risky surgery on `Portfolio.__init__`'s
  self-created storage plus throwaway test scaffolding.

### Terminal-record retention policy (RETAIN-02)
- **D-02:** **Immediate purge-on-terminalize + read-through** — evict the record from the working-set
  cache as soon as its terminalize transaction commits; serve any later terminal-record query
  (status/recon/reporting) via **read-through to Postgres, off the hot path** (an open record is always
  resident, so the hot path never read-throughs). **No Nautilus buffer window, no age/count sweep timer**
  this phase — simplest, tightest memory bound, zero tuning knobs; reconciliation buffering is N+4's
  concern. **The terminal-state gate is mandatory and kept:** never evict an open order/position, and a
  **bracket parent stays resident until all its children terminalize** (port of Nautilus's contingency
  rule onto `parent_order_id` / `child_order_ids`).

### Restart rehydration — snapshot + accumulators (RETAIN-03)
- **D-03:** **Periodic snapshot row + load-latest, with the accumulator scalars riding the synchronous
  write-through txn.** Rehydration is **two reads**: (1) load the **working set** — open positions +
  working orders + brackets — from the Phase-3 indexed queries (`is_open`, `status`, `parent_order_id`);
  (2) restore the **account aggregate + running accumulators** (cash, equity, realised-PnL, peak equity)
  from the **latest persisted snapshot row**, because those depend on **closed** trades whose history we
  deliberately do **NOT** replay (D-02 purged them). The per-TIME-bar `equity_snapshots` rows remain the
  historical equity curve (cheap, append-only), **but the accumulator scalars needed for an exact restart
  are persisted synchronously in the same txn as the terminalize/fill that changed them** — so the latest
  persisted account state is **never behind** the working set after a crash. This is what makes SC3's
  "rehydrated working set equals pre-crash state" exact under immediate-purge (a per-bar-only snapshot
  cadence would let a crash between a fill and the next bar leave the snapshot stale). **Never replay
  terminal history; load open-only.**

### Cache-layer class topology (RETAIN-01/02/03)
- **D-04:** **Wrapper-per-concern decorator**, one new live-only class per concern — **`CachedSqlOrderStorage`**,
  **`CachedSqlPortfolioStateStorage`**, **`CachedSqlSignalStorage`** — each **implements its existing ABC**
  and **composes** an in-memory working set + the Phase-3 `Sql<Concern>Storage`: write-through on mutate,
  purge on terminalize, read-through on miss, rehydrate on boot. The factory `'live'` arm returns the
  wrapper. Rationale: keeps the Phase-3 `Sql*Storage` classes as a **pure persistence layer** (untouched,
  already round-trip-tested in Phase 3 — a cache bug can't compromise the store's proven correctness) and
  isolates all the new/risky behavior in a separate composed layer. Composition-not-inheritance (Phase 1
  rule). **Reject** folding cache/purge/read-through into the `Sql*Storage` classes (re-opens gate-passed
  code, blurs store↔cache). **Naming:** `CachedSql…` — the `InMemory` / `Sql` / `CachedSql` per-concern
  triple; emphasizes cache-over-SQL (owner choice; "WorkingSet" rejected).

### Carried forward from Phase 3 / research (locked — restated)
- **Write-through durability (Pitfall 8):** create/terminalize are **synchronous inside a transaction** —
  the store commits **before** the engine acknowledges the state change (persist-then-acknowledge). A
  multi-row write (bracket parent + children; transaction + position + snapshot) is **atomic** (one txn,
  all-or-nothing). The cache must never be ahead of the store for create/terminalize.
- **No premature async (keep-only-measured):** append-heavy writes (transaction/cash-op ledger,
  historical snapshots) are **all-synchronous now**; do **not** pre-build an async batch path — defer it
  to *only* the non-durability-critical writes and *only if* profiling later justifies it.
- **Backend-selection at wiring, not a hot-path flag:** the backtest backend imports no SQLAlchemy /
  serialization symbol; the no-serialization-in-backtest rule holds structurally (GATE-01 inertness).
- Money on the live path = Postgres-native `Numeric`; single UUIDv7; determinism (business `time`, not
  wall-clock; `sort_keys`; stable `ORDER BY`).

### Claude's Discretion (planner/researcher to settle)
- The exact in-memory working-set structure the wrapper holds (reuse the existing `InMemory*Storage`
  internally vs a purpose-built resident set) — D-04 fixes the *topology* (separate composed layer), not
  the internal data structure.
- The precise rehydration query surface / boot sequence, and exactly which accumulator scalars must ride
  the write-through txn vs which can be recomputed from the loaded working set (D-03 fixes load-latest +
  no-history-replay + sync accumulator persistence; the scalar split is open).
- The transaction-boundary mechanics per write point (which existing manager call-sites — `add_order`,
  `update_order` on terminalize, `set_position`, `add_snapshot`, etc. — wrap in which txn), and whether
  the multi-row atomic write is one txn or store-first.
- The `LiveTradingSystem` daemon-thread vs `TradingInterface` API-thread interaction for read-through /
  status queries: all storage **mutation** happens single-threaded on the daemon event-loop thread, but
  status reads originate on the API thread — the planner/researcher settles whether read-through is
  daemon-only or API-thread-safe (research SUMMARY §Research Flags explicitly flags this).
- Whether the `CachedSql*Storage` modules enter `mypy --strict` scope now or stay deferred (cf. Phase 1
  D-09 for `sql_store.py`) — planner's call under GATE-02.
- **Plan-time research is flagged** (`/gsd:plan-phase --research-phase`): the write-through
  transaction-boundary design, the bracket-parent safety invariant, the read-through scope, the
  rehydration query surface, and the daemon/API-thread interaction are the novel surfaces to nail before
  implementation (research SUMMARY §Research Flags; PITFALLS 7/8).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ⚠️ Precedence (read FIRST)
- `.planning/PROJECT.md` → "Current Milestone" + "Owner Decisions" — authoritative locked scope. Owner
  Decisions supersede the research where they differ (money native `Numeric`, no `DecimalAsText`,
  backend-selection-at-wiring not a hot-path flag).
- **This CONTEXT's D-01** draws the Phase-4 scope line: build machinery + factory `'live'` arms, **defer**
  the live-composition-root rewiring to N+4. Do not rewire `Portfolio.__init__` / the signal hardcode.

### Requirements & scope
- `.planning/REQUIREMENTS.md` — RETAIN-01/02/03 (full text + Out-of-Scope table); GATE-01 (bound here),
  GATE-02 (recurring).
- `.planning/ROADMAP.md` → "Phase 4: Retention + Live Write-Through (#2 — live path)" — the four Success
  Criteria + the **Research flag** ("NEEDS DEEPER PLAN-TIME RESEARCH").
- `.planning/STATE.md` → "Milestone Gate (v1.6 — DB-gated)" — the two-part gate (a hot-path inertness /
  b DB verification on testcontainers Postgres) restated.

### Phase 3 store layer (the SQL backends Phase 4 wraps — read before designing the wrappers)
- `.planning/phases/03-operational-sql-backends-2-store-layer/03-CONTEXT.md` — D-01..D-10: fully-typed
  relational columns, self-referential `parent_order_id` bracket FK (D-02 — serves the "parent resident
  until children terminalize" invariant), normalized portfolio tables (D-03), Core + hand-written
  `to_row`/`from_row`, `'live'`-only factory arm (D-06 — **no `postgresql` arm**), enums-as-text (D-07),
  Phase-4-readiness indexes (D-08: `(portfolio_id, status)`, `(portfolio_id, is_open)`, `parent_order_id`).
- `.planning/phases/01-sql-spine-security-hardening/01-CONTEXT.md` — the `itrader/storage/` `SqlBackend`
  spine (Core/MetaData), `SqlSettings`, testcontainers harness, composition-not-inheritance.
- ⚠️ **Config wiring** (changed since Phase 1): `itrader/config/sql.py` — unified `SqlSettings(BaseSettings)`
  (`env_prefix="ITRADER_DATABASE_"`, default Postgres port **5544**); `SqlSettings.default()` operational
  vs `SqlSettings.results_default()`. Backends source their engine from `SqlSettings`, not `Settings`.

### Research (HIGH-confidence; some PREDATES Owner Decisions — apply with the precedence note)
- `.planning/research/SUMMARY.md` §"Phase 4" + §"Research Flags Summary" — the live-retention design is the
  most novel surface; recommends `--research-phase`.
- `.planning/research/PITFALLS.md` — **Pitfall 7** (live retention bugs: evict-then-need, unbounded growth,
  rehydration loading terminal history, rehydration breaking determinism/bracket safety) + **Pitfall 8**
  (write-through durability/ordering: persist-then-acknowledge, atomic multi-row). These two are the
  load-bearing pitfalls for this phase — read in full, including their verification tests.
- `.planning/research/ARCHITECTURE.md` — Pattern 2 (backend-selection write-through, zero hot-path cost),
  Pattern 3 (end-of-run batch dump), Q9. ⚠️ **Predates Owner Decisions** — ignore its `DecimalAsText` /
  `write_through:bool`-on-`SqlSettings` framing (both retracted; money is native `Numeric`,
  backend-selection is at wiring).
- `.planning/research/FEATURES.md` — **Q10** (the second knob: purge-on-terminalize + age/count safety
  net, resident-vs-evicted inventory table, read-through fallback, restart-rehydration sequence, Nautilus
  precedent). Note: D-02 chose immediate purge (no buffer window/sweep) — apply Q10's *gate* + *rehydration
  sequence*, drop its buffer-window default.
- `.planning/notes/persistence-milestone-design.md` — the converged two-knob seed (write-through ×
  retention table; live lifecycle steps 1-4).

### Code to read (the live path Phase 4 integrates with — from the Phase-4 code map)
- `itrader/trading_system/live_trading_system.py` — storage wiring (order `'live'` branch gated on
  `SYSTEM_DB_URL`, lines ~125-150; signal hardcoded `'backtest'` L113; portfolio-state never wired),
  daemon event loop (`_event_processing_loop` ~337-396), `start`/`stop`/status lifecycle,
  `_publish_and_continue` live error policy (~217-248).
- `itrader/trading_system/trading_interface.py` — API-thread bridge; `create_market_order`/
  `create_limit_order` → `add_event` → `global_queue.put` (the thread-safe API↔daemon handoff).
- `itrader/order_handler/storage/` — `storage_factory.py` (`'live'` arm → `SqlOrderStorage`),
  `base.py` (`OrderStorage` ABC, 14 methods), `sql_storage.py` (`SqlOrderStorage`,
  `_ACTIVE_STATUS_VALUES`, `_load_child_ids` from `parent_order_id`), `in_memory_storage.py`
  (`_by_id` + active secondary indexes — the working-set structures the wrapper mirrors),
  `models.py` (`orders` indexes). `order.py` (`Order.parent_order_id` / `child_order_ids`,
  `is_active`/`is_terminal`). Write points: `AdmissionManager`/`BracketManager`/`LifecycleManager`/
  `ReconcileManager` (`add_order`/`update_order` on terminalize, OCO child-cancel).
- `itrader/portfolio_handler/` — `portfolio.py:93` (hardcoded `"backtest"` state storage — D-01 leaves it),
  `storage/storage_factory.py` (`'live'` arm needs `portfolio_id`), `base.py` (`PortfolioStateStorage` ABC,
  21 methods, one-instance-per-Portfolio), `storage/sql_storage.py` (`SqlPortfolioStateStorage`,
  `get_positions`/`get_position` filter `is_open`), `storage/in_memory_storage.py` (open `_positions` by
  ticker; append histories; `_snapshots = deque(maxlen=max_snapshots)`). Managers: cash/transaction/
  position/metrics write on fill. `position/position.py` (`Position.is_open`).
- `itrader/strategy_handler/storage/` — `storage_factory.py` (`'live'` arm → `SqlSignalStorage`),
  `base.py` (`SignalStore` ABC, 4 methods), `sql_storage.py`, `in_memory_storage.py`. `StrategiesHandler`
  `.add(record)` per signal.
- `itrader/core/enums/` — `order_*_map` string↔enum converters; `OrderStatus` terminal set. `core/money.py`
  — `Decimal`/`quantize` contract.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-3 `Sql<Concern>Storage`** (order/portfolio/signal `storage/sql_storage.py`): the pure
  persistence layer each `CachedSql*Storage` wrapper composes — already round-trip-tested on testcontainers
  Postgres (Phase-3 D-10). Indexed open/active queries (`is_open`, `status`, `parent_order_id`) are the
  rehydration read surface, baked in by Phase-3 D-08.
- **`InMemory<Concern>Storage`** (each `storage/in_memory_storage.py`): the working-set data structures
  the wrapper mirrors — `_by_id` + active-by-portfolio/status secondary indexes (orders), open
  `_positions` + reservation/margin maps + bounded `_snapshots` deque (portfolio). The wrapper's resident
  set can reuse these structurally.
- **Factory `'live'` arm** (each `storage_factory.py`): the existing backend-selection seam Phase 4 points
  at the wrapper (lazy SQL imports preserved for GATE-01 import inertness).
- **Testcontainers Postgres fixture** (Phase 1 D-10, session-scoped; skips without Docker): the gate-(b)
  substrate for every Phase-4 integration test.
- **Self-referential `parent_order_id` FK + `SqlOrderStorage._load_child_ids`** (Phase-3 D-02): the
  clean status query backing the "bracket parent resident until children terminalize" invariant (D-02).

### Established Patterns
- **Composition not inheritance** (Phase 1 D-01): the wrapper *has-a* SQL store + *has-a* working set;
  no cross-concern god base.
- **Backend selection at wiring** (not a hot-path flag): the backtest backend imports no SQL symbol — the
  zero-hot-path-cost rule holds structurally (GATE-01).
- **Single daemon-thread mutation**: in live mode all storage mutation runs on the one
  `LiveTradingSystem-EventProcessor` daemon thread (the event loop); the API thread only enqueues via
  `queue.Queue` and reads status. So the working-set cache has a single writer — locking is a read-through
  concern, not a write concern.

### Integration Points
- New files: `order_handler/storage/cached_sql_storage.py`, `portfolio_handler/storage/cached_sql_storage.py`,
  `strategy_handler/storage/cached_sql_storage.py` (or similar — match each `storage/` package's existing
  module naming + indentation; all three `storage/` packages are **4-space**).
- Edited: the three `storage_factory.py` files (`'live'` arm → `CachedSql*Storage`).
- **NOT edited (D-01):** `portfolio.py:93`, `live_trading_system.py:113` — the live-composition-root
  hardcodes stay until N+4.
- Tests: per-concern testcontainers Postgres integration tests (evict-then-read-through, flat-RSS long-run,
  bracket-parent-resident, open-only rehydration, crash-after-emit/restart-equals-pre-crash).

### Indentation map (DO NOT normalize — match the file)
- `order_handler/storage/`, `portfolio_handler/storage/`, `strategy_handler/storage/`, `config/`,
  `itrader/storage/` → **4 spaces**. `portfolio_handler/base.py` has a TAB-import / 4-space-class mix —
  match surrounding lines exactly.

</code_context>

<specifics>
## Specific Ideas

- **Naming locked by owner:** `CachedSqlOrderStorage` / `CachedSqlPortfolioStateStorage` /
  `CachedSqlSignalStorage` — the `InMemory` / `Sql` / `CachedSql` per-concern triple. "WorkingSet" in the
  name was explicitly rejected.
- **Owner values the store as the pure system of record** — chose the wrapper topology (D-04) specifically
  so the Phase-3 SQL classes stay untouched and a cache bug can't compromise their proven correctness.
- **Owner draws a deliberate, conservative scope line** (D-01): build + component-test the machinery, but
  don't perform risky surgery on the live composition root or build throwaway end-to-end scaffolding that
  N+4 would redo — N+4 is where the real feed and full-loop validation belong.
- **FastAPI application layer is coming** (carried from Phase 3): the read-through surface + indexed
  rehydration queries serve the planned web-app's status/recon reads as well as restart.

</specifics>

<deferred>
## Deferred Ideas

- **Rewiring the live composition root** — closing `Portfolio.__init__`'s hardcoded `"backtest"` state
  storage (`portfolio.py:93`) and the hardcoded `'backtest'` signal store (`live_trading_system.py:113`)
  so `LiveTradingSystem` actually instantiates the `CachedSql*Storage` wrappers for portfolio + signal —
  **N+4** (the order seam is wired now because the factory already routes to it; portfolio/signal stay
  component-tested). (D-01)
- **Synthetic end-to-end event driver** — pushing synthetic market/signal/order/fill events through the
  real `LiveTradingSystem` daemon loop to validate the whole retention loop in-process — **N+4**. Phase 4
  validates the wrappers as components against testcontainers Postgres. (D-01)
- **Real live feed + venue reconciliation** — connecting a broker/market feed and reconciling the
  rehydrated cache against the venue — **N+4**. (Roadmap goal: "driven by a real live feed only in N+4".)
- **Reconciliation buffer window for terminal records** — the Nautilus `*_buffer_mins` / `*_interval_mins`
  recent-N/recent-T resident window + age/count sweep timer — **N+4**, when reconciliation actually needs
  briefly-resident terminal records. Phase 4 uses immediate purge + read-through (D-02).
- **Async batch write-through** for append-heavy non-durability-critical writes (transaction/snapshot
  ledger) — only if profiling later justifies it (keep-only-measured); not pre-built. (D-04 carried)

None lost — discussion stayed within phase scope; all deferrals are forward-context for N+4 / later, not
new Phase-4 work.

</deferred>

---

*Phase: 4-Retention + Live Write-Through (#2 — live path)*
*Context gathered: 2026-06-30*
