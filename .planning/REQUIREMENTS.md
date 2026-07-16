# Requirements: iTrader v1.8 — Live System Refactor & Live-Readiness Hardening

**Defined:** 2026-07-09
**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
correct, deterministic, cross-validated numbers (`134 / 46189.87730727451`). v1.8 decomposes the
2,171-line `LiveTradingSystem` God object into a clean, venue-parametrized, FastAPI-ready live engine
**without disturbing that oracle or the OKX import-inertness gate.**

**Design source:** `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md`
(LR-00..LR-22, CF-1..CF-10). **Research:** `.planning/research/` (SUMMARY validates the design vs
Nautilus/LEAN; zero new dependencies; 4 build-order refinements). **Owner refinements (2026-07-09):**
pre-trade throttle folded in (SAFE-06); fee/slippage runtime-mutation gated to simulated venues
(RTCFG-05); strategy-parameter atomic runtime reconfiguration in scope (STRAT-03).

## Milestone-wide gates (apply to EVERY phase — not numbered requirements)

1. **Oracle byte-exact** — `SMA_MACD` stays `134 / 46189.87730727451` (`check_exact=True`), determinism
   double-run identical. **Per-PLAN gate** on the foundational + universe-wiring phases (P1–P4, P5, and
   P6's `UniverseWiring` extraction — the highest oracle-risk seam). Any re-baseline (LR-02) is explicit

   + externally cross-validated (backtesting.py + backtrader), never silent.
2. **OKX import-inertness** — `tests/integration/test_okx_inertness.py` stays green; extended to assert
   register-vs-build on P1/P2/P4/P5. Registering a venue imports no `ccxt.pro` until built; `SystemConfig`
   never constructs Postgres `SqlSettings` at import; `FifoEventBus`/`EngineContext(sql_engine=None)` pull
   nothing heavy. **Zero new third-party dependency, no poetry change** anywhere in P1–P12 (research STACK).

3. **Held throughout** — Decimal money end-to-end; single UUIDv7; determinism (business `time`, seeded RNG,
   injected clock); `mypy --strict` clean on new code; `filterwarnings=["error"]` green; tabs/spaces
   indentation matched to the file (never normalized).

## v1 Requirements

### Config Centralization (P1)

- [x] **CFG-01**: `SystemConfig` aggregates the **cardinality-1 system-wide singletons only**
  (`performance`, `monitoring`, `runtime`, `sql`) with an import-safety split — eager fields (plain
  `BaseModel`, safe defaults) vs a lazy `sql` accessor that resolves Postgres `SqlSettings` only on
  first access, never at import (LR-04/§6a). **Owner amendment (2026-07-09):** `order` is reclassified
  cardinality-N (may diverge per-portfolio / per-venue in the near future) and is therefore **kept out
  of `SystemConfig`** — it lives with its owner (`OrderHandler`) via `OrderConfig.default()`, alongside
  the other per-instance configs (`portfolio`, `exchange`). This intentionally supersedes the spec §6b
  listing of `order` as a `SystemConfig` singleton.

- [x] **CFG-02**: `itrader.config` (root) exposes immutable base defaults importable via
  `from itrader import config`; the backtest path reads these unchanged (concern 24/§6c).

- [x] **CFG-03**: Scattered module constants fold into domain config — `_STREAM_RECONNECT_*` →
  `StreamSettings`/`ConnectionSettings`, `_WARMUP_MARGIN`/`_BACKFILL_PAGE` → feed/provider config;
  `_OKX_*`/`_PAPER_*` deleted (concern 17/§6f).

- [x] **CFG-04**: Dead-config audit removes unused settings + stale `__pycache__`; `extra` policy
  normalized across config models (concern 21/§6f).

- [x] **CFG-05**: A typed `HaltReason` enum in `core/enums/system.py` replaces free-string halt reasons;
  the `'baseline-residual'` off-vocabulary string is retired (CF-8).

- [x] **CFG-06**: The D-03a dual-validator paragraph is applied to `.planning/codebase/CONVENTIONS.md`
  during the P1 cleanup pass (CF-6, doc).

### Event Bus (P2)

- [x] **BUS-01**: An `EventBus` Protocol (`put`/`get`/`get_nowait`/`qsize`/`empty`/`depth_by_tier`) with
  two implementations — `FifoEventBus` (backtest) + `PriorityEventBus` (live) — shares one `.put(event)`
  surface; no handler `.put` call-site changes (LR-11/§4a).

- [x] **BUS-02**: `PriorityEventBus` orders `(tier, seq, event)` with `tier ∈ {CONTROL=0, BUSINESS=1}`
  assigned from a declarative `_CONTROL_EVENT_TYPES` frozenset and a globally-unique monotonic `seq`; a
  test asserts the tuple comparison never dereferences the (non-orderable) frozen event and preserves
  strict within-tier FIFO (§4a).

- [x] **BUS-03**: New CONTROL `EventType` members (`STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE`) are
  added; backtest uses `FifoEventBus` so the oracle stays byte-exact (zero priority-bus on the backtest
  path) (arch refinement 3).

- [x] **BUS-04**: A minimal `EngineContext` skeleton is introduced in P2 so `compose_engine`'s signature
  settles once rather than being double-edited across P2/P3 (arch refinement 2).

### EngineContext + Storage-in-Handler (CTX-01/02/03 → P2, CTX-04 → P3)

> **Phase reassignment (Phase 2 D-03, 2026-07-09):** the owner chose the end-state
> `compose_engine(ctx, spec)` signature in P2 (Option B), which requires handler-owned storage — so
> **CTX-01, CTX-02, and CTX-03 (the byte-exact/inertness gate inseparable from that change) are pulled
> forward into P2.** Only **CTX-04** (the mechanical `SqlBackend→SqlEngine` rename) remains in P3, which is
> now a single-requirement phase. Downstream must NOT "fix" this back — see `phases/02-event-bus/02-CONTEXT.md`.

- [x] **CTX-01** *(→ P2)*: `EngineContext` (frozen: `bus`, `config`, `environment`, `sql_engine`) is threaded
  once into `compose_engine(ctx, spec)`; infra-only, never a god-parameter (LR-14/§7a).

- [x] **CTX-02** *(→ P2)*: Order + Strategies handlers own their storage init from `(environment, sql_engine)`
  with an optional `storage=` override (following `PortfolioHandler`'s shape); `compose_engine` reads the
  concrete instance back off `.storage` for wiring (LR-13/§7b, concern 20).

- [x] **CTX-03** *(→ P2)*: Backtest (`environment='backtest', sql_engine=None`) yields the same in-memory
  storage instances → oracle byte-exact; factory SQL imports stay lazy → inertness green (§7b).

- [x] **CTX-04** *(P3)*: `SqlBackend` is renamed to `SqlEngine` (`storage/backend.py` → `storage/engine.py`;
  field/param `sql_engine`); all importers updated (LR-18, rename folded into P3 per arch refinement 4).

### SqlEngine Migrations Relocation (P4)

- [x] **SQL-01**: `itrader/storage/migrations/` relocates to project-root `migrations/`; `alembic.ini`
  `script_location` updated; `env.py` keeps importing the `build_*_table` registrars + `NAMING_CONVENTION`
  from `itrader.storage`; migrations stay out of the shipped wheel (LR-18/§7e).

- [x] **SQL-02**: An Alembic gate confirms `alembic upgrade head` on a clean DB, `alembic heads == 1`
  (single head) over the full relocated chain incl. the three new stores, and a `create_all`/migration
  parity test (research PITFALLS).

### New Durable Stores (P4)

- [x] **STORE-01**: `SystemStore` (cardinality 1, key-value `(key, value_json, updated_at)`, namespaced
  upsert) holds system-wide config overrides + operational state + the latest stats snapshot (LR-22/§6d).

- [x] **STORE-02**: `VenueStore` (cardinality N) holds per-venue config + which venues are enabled; never
  stores secrets (LR-22/§7d).

- [x] **STORE-03**: `StrategyRegistryStore` (cardinality N) holds which strategies trade + per-strategy
  config + subscriptions (LR-22/§7d).

- [x] **STORE-04**: Each store follows the `HaltRecordStore` template (composes `sql_engine`, own
  `build_*_table` registrar, chained Alembic migration `d10_halt_records → system_store → venue_config →
  strategy_registry` in the relocated `migrations/` tree) and rehydrates on restart (§7d).

- [x] **STORE-05**: An in-memory fallback keeps the backtest path untouched — the new stores are live-only
  composition-root infrastructure (§7c).

### Venue Registry + Bundle (P5)

- [x] **VENUE-01**: Two registries — `ExecutionVenueRegistry` + `DataProviderRegistry` — select execution
  venue + data provider independently via `SystemSpec` (`execution_venue` + `data_provider`) (LR-17/§8a-b).

- [x] **VENUE-02**: A `VenuePlugin` Protocol builds a `VenueBundle` (optional connector, exchange,
  mandatory per-portfolio account factory) with concretions lazy-imported inside `build_bundle` —
  registering `'okx'` pulls no `ccxt.pro` until built; `test_okx_inertness.py` is the P5 acceptance gate
  (§8a, concerns 2/3).

- [x] **VENUE-03**: Connectors are memoized by `(venue, account_id)` at the composition root; credentials
  are per-`account_id`, env-sourced, never persisted (LR-17/LR-20/§8c).

- [x] **VENUE-04**: Precision + validation become exchange capabilities (`resolve_precision(symbol)`,
  `validate_symbol(symbol)` on `AbstractExchange`); `_OkxPrecisionResolver`/`_PrecisionResolver` deleted;
  `_precision_to_scale` → a shared money util (concern 15/§8a).

- [x] **VENUE-05**: A `LiveDataProvider` Protocol (required core + optional streaming seams via a
  `BaseLiveDataProvider` giving no-op defaults) wires every provider uniformly — no `hasattr` sprinkling
  (concern 14/§8b).

- [x] **VENUE-06**: A `VenueLifecycle` orchestrator encodes the fixed start/stop order and None-guards
  absent members (paper/replay skip connector/account steps) — every `if exchange=='okx'` /
  `elif exchange=='paper'` removed (concerns 6/13/§8d).

- [x] **VENUE-07**: A shared `StreamSupervisor` replaces the triplicated `_run_stream_supervisor` +
  `_STREAM_RECONNECT_*` (CF-4); connector-contract docstrings added to `connectors/base.py` (CF-3); OKX
  markets-map freshness closes the fail-open-before-load window via the existing `validate_symbol` →
  removal path (CF-9) (§8f).

### LiveRunner + Factory + Facade Shrink (P6)

- [x] **RUN-01**: `build_live_system(spec)` is the live factory / composition root — reads centralized
  config, builds the one `sql_engine`, resolves venue plugin(s), assembles `EngineContext`, calls
  `compose_engine`, builds bundle(s) + `LiveRunner` + controllers (LR-10/§5).

- [x] **RUN-02**: `LiveRunner` owns the drain loop + injected `ErrorPolicy` + worker supervision,
  replacing `_event_processing_loop` (§5).

- [x] **RUN-03**: `LiveTradingSystem` shrinks to a ~200-line facade (lifecycle, status/read-model,
  `add_event`; delegates everything else); legacy `print_status`/`get_statistics` dropped;
  `__init__` sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` (from config/spec) (concerns 8/25,
  §11e).

- [x] **RUN-04**: A shared `UniverseWiring` helper (`derive_membership → build Universe → inject
  exchange/order/portfolio/strategies → feed.bind`) is extracted and reused by both `BacktestRunner` and
  the live `SessionInitializer`, moved as one intact unit incl. the WR-03 desync assert — **oracle
  byte-exact** (§13a, oracle-sensitive).

- [x] **RUN-05**: `LiveRouteRegistrar` composes live routes (incl. CONTROL routes) into the single
  `EventHandler` declaratively (list order = execution order); no subclass, no runtime mutation; backtest
  gets base routes only (LR-16/§13c).

- [x] **RUN-06**: `UniverseHandler` is constructed at the live composition root as a first-class handler
  with explicit deps (`bus`, `universe`, `feed`, `config`) — zero OKX coupling (symbol validation/precision
  via `set_venue_metadata(exchange)`) (concern 10/§13b).

- [x] **RUN-07**: `_LiveWarmupConsumer` is rehomed to `price_handler/feed/cache_registration.py` as a
  reusable `StrategyWarmupConsumer` sized to `max(strategy.warmup)`; the depth-hint seam is shaped for
  CF-10 (the K-computation change itself stays deferred) (concern 26/§13d).

### Safety + Reconciliation + Stream Recovery (P7)

- [x] **SAFE-01**: A `SafetyController` (pure state machine, no venue I/O) owns the status latch
  (`VALID_STATUS_TRANSITIONS`, single `update_status` seam, `force=` reserved for `reset_halt`),
  `halt(reason)` (winner-only → CRITICAL `ErrorEvent` → durable `HaltRecordStore.record_halt`),
  `is_halted`/`reset_halt`, `pause_submission`/`resume_submission` + bounded deferred-protective queue,
  and the dispatch gate (concern 12/§11a).

- [x] **SAFE-02**: `safety.check_durable_halt_on_start()` runs first (before any venue I/O), refuses
  RUNNING on an unresolved durable halt, and re-latches from the persisted reason via `update_status`
  (no second durable write) (§11b).

- [x] **SAFE-03**: Connector stream up/down + fatal arrive as CONTROL events (`StreamStateEvent` →
  pause / `StreamRecoveryHandler.on_reconnect`; `ConnectorFatalEvent` → `halt`) running on the engine
  thread — the flag side-channel (`_pending_stream_resume`/`_pending_connector_halt`/etc.) is deleted
  (concern 11/§11c).

- [x] **SAFE-04**: `StreamRecoveryHandler` owns reconnect resume I/O (catch-up missed fills + account
  snapshot on the engine thread + all-streams-healthy gate → `resume_submission`); CF-2
  `backfill_on_resume` lands **loop-native** (connector loop via the reconnect callback), never a second
  concurrent engine-thread ring writer (§11c, CF-2).

- [x] **SAFE-05**: A `ReconciliationCoordinator` owns the startup sequence (rehydrate → venue reconcile
  for venue-truth accounts → baseline guard), keyed on account *kind* not `exchange=='okx'`; the bare
  `str(matched["id"])` is guarded with a typed fail-loud error (CF-7) (§11d).

- [x] **SAFE-06**: A **pre-trade submit-rate + max-notional-per-order throttle** rejects order flow
  exceeding configured velocity/notional caps *before* submission (fires ahead of send; complements CF-1's
  post-error breaker and the per-order `EnhancedOrderValidator`); caps are runtime-mutable via the P9
  allowlist (research GAP / owner decision 2026-07-09).

### Error Subsystem (P8)

- [x] **ERR-01**: An `ErrorPolicy` is injected into `EventHandler` at construction (removes the
  `_on_handler_error` monkeypatch): backtest/replay → fail-fast (re-raise; the parity gate can't
  false-green), live → publish-and-continue; per-handler granularity preserved; carries the WR-06 source
  guard (concern 19/§12a).

- [x] **ERR-02**: An `ErrorHandler` formalizes the ERROR-route consumer (severity-mapped structured
  logging, CRITICAL → the pluggable alert sink, persist latest error → `SystemStore state.last_error`,
  WR-06 consumer guard); two-guard terminal safety (source + consumer). The alert-sink seam is threaded so
  a CRITICAL halt *can* reach a real sink (CF-5; substantive egress stays the FastAPI milestone) (§12b).

- [x] **ERR-03**: A **CF-1 aggregate circuit breaker** on the publish-and-continue seam — a
  route-classified ring (SETTLEMENT halt-on-first, ORDER-IO N=3/60s, ADMISSION N=3/300s, LOOP-BACKSTOP
  N=5/60s) that **actually trips** (verified by a "money route failing every event" test), preserves the
  WR-06 terminal swallow, and leaves backtest fail-fast byte-for-byte unchanged (CF-1, hard acceptance
  criterion).

- [x] **ERR-04**: One error funnel — handler failures, `halt()` (CRITICAL), `PortfolioErrorEvent`,
  `ConnectorFatalEvent` all route through the ERROR route (§12b).

### ★ Runtime-Config Platform (P9)

- [x] **RTCFG-01**: A `RuntimeConfig` overlay (`defaults ← YAML ← env ← persisted runtime overrides`) is
  built by the live factory and injected as `EngineContext.config` — engine-thread-write, snapshot-read;
  handlers read it so they see runtime changes (LR-04/§6c).

- [x] **RTCFG-02**: A scoped `ConfigUpdateEvent(scope, key, value)` (CONTROL plane) is validated against an
  **allowlist** of runtime-mutable keys + type/range check, routed on the engine thread to the owning store
  (`system`→SystemStore, `portfolio:{id}`→Portfolio+portfolio store, `venue:{name}`→VenueStore,
  `order`→SystemStore), applied to the overlay + relevant `handler.update_config(...)`, and persisted
  (§6e). Allowlist (v1.8): venue fee/slippage (see RTCFG-05) + enabled; order trail/TIF defaults; portfolio
  risk limits + sizing defaults; system poll_cadence + universe_remove_policy + idle/timeout knobs; strategy
  enable/disable + params (STRAT-03).

- [ ] **RTCFG-03**: Persisted overrides survive restart — `build_live_system` layers them over defaults
  on boot (§6e).

- [x] **RTCFG-04**: Immutable-at-runtime keys (`rng_seed`, money precision, SQL credentials, venue API
  credentials, `environment`, IDs) are rejected by the allowlist (§6e / owner decision).

- [x] **RTCFG-05**: Fee/slippage config keys are runtime-mutable **only for simulated venues**; a
  `ConfigUpdateEvent` targeting a *live* venue's fee/slippage is rejected (venue-kind-aware validation —
  real-venue fees/slippage come from actual venue fills, not engine config) (owner decision 2026-07-09).

- [ ] **RTCFG-06**: The `system_store` `stats.snapshot` + `state.*` (status / halt_reason / last_error /
  last_started_at) double as the UI read-model — readable without touching hot-path locks (concerns 22/23,
  §6d). *(Ships regardless of the mutation-path scope.)*

### ★ Strategies Registry (P10)

- [ ] **STRAT-01**: `StrategyRegistryStore` persists which strategies are active + config + subscriptions;
  on restart `build_live_system` rehydrates → re-registers active strategies (survives restart)
  (concern 18/§9).

- [ ] **STRAT-02**: Runtime add / remove / enable / disable via `STRATEGY_COMMAND` (CONTROL) →
  `StrategiesHandler` applies + persists (§9).

- [ ] **STRAT-03**: A strategy's config parameters are mutable at runtime via **atomic reconfiguration**
  (quiesce → apply → re-warmup the affected strategy), persisted to `StrategyRegistryStore` — folds
  `pair-strategy-live-reconfiguration.md` (v1.7 shipped only a refusal guard) (owner decision 2026-07-09).

### ★ Multi-Portfolio-Live (P11)

- [ ] **MPORT-01**: The venue plugin's `new_account(portfolio_ref, config)` mints a per-portfolio account
  (venue-truth → `VenueAccount` scoped to `portfolio.account_id`; compute → a fresh `SimulatedAccount`);
  `_link_venue_account_to_portfolios` + its `RuntimeError(>1)` guard are deleted (LR-03/§10b).

- [ ] **MPORT-02**: A distinct-`account_id` invariant fails **loud** at composition time — multiple
  portfolios sharing one venue `account_id` is rejected (pooled buying power the venue can't split back
  out is deferred) (§10a).

- [ ] **MPORT-03**: A signal fans out to each subscribed portfolio; each sizes/orders independently against
  its own account; the venue partitions balance/positions/fills by `account_id` (§10a).

- [ ] **MPORT-04**: `clOrdId` is renamed `client_order_id` (venue↔engine correlation), distinct from
  `portfolio_id` (attribution); every submitted order is tagged with its portfolio; fills route via
  `client_order_id`/`venue_order_id` → engine order → `FillEvent(portfolio_id)` → the right
  `Portfolio.on_fill` (LR-19/§10c).

- [ ] **MPORT-05**: `PortfolioSpec` gains `account_id`; the `ReconciliationCoordinator` iterates active
  portfolios, reconciling each against its own `VenueAccount`/`account_id` (§10b-c).

- [ ] **MPORT-06**: Connectors are keyed `(venue, account_id)` (VENUE-03) so multi-account portfolios share
  or decouple connectors correctly without a combinatorial matrix (LR-20/§8c).

### Test Migration + Gates (P12 — except TEST-01, pulled forward into P6)

- [x] **TEST-01** *(delivered in **P6**, pulled forward from P12)*: the ENTIRE replay test-harness moves
  OUT of the `itrader` package into `tests/` — `run_paper_replay` → **`TestRunner`**, `ReplayDataProvider`
  → **`TestLiveDataProvider`**, `ReplayDataPlugin` → **`TestDataPlugin`** (registered **only** by a test
  fixture), `PAPER_PARITY_*`/`_PAPER_*` → `tests/`; production is replay-free (concern 9/§13/§8e). The
  `paper` **execution** venue (`PaperVenuePlugin` + `SimulatedExchange` + `SimulatedAccount`) STAYS a real
  live production mode, **untouched** — its production data feed re-points from `replay` to the **OKX live
  feed** (`{'okx':'okx','paper':'okx'}`), so the `paper`↔replay pairing survives only in the test fixture.
  `Test*`-named classes set `__test__ = False` (pytest auto-collects `Test*`; `filterwarnings=["error"]`
  makes the collection warning a hard failure). Rationale: it needs only P6's `build_live_system` (zero
  P7–P11 dependency), rides the same construction path P6 builds, and removes the recurring
  production-replay tax across P7–P11. `TestRunner` is **fail-fast by default** (drives the EventHandler at
  its default fail-fast seam, never calls `start()`) so the parity gate can't false-green; done as pure
  code-motion, `test_paper_parity` green continuously, sliced AFTER the `UniverseWiring` extraction locks.

- [ ] **TEST-02**: A live-smoke gate exercises the decomposed live surface end-to-end (facade → factory →
  `LiveRunner` → controllers) on the replay fixture.

- [ ] **TEST-03**: A config-restart gate proves persisted runtime overrides survive a restart (RTCFG-03).
- [ ] **TEST-04**: A multi-portfolio attribution gate proves fills route to the correct portfolio and the
  distinct-`account_id` invariant fails loud (MPORT-02/MPORT-04).

## v2 / Future Requirements

Deferred seams — carried and marked, not built this milestone (spec §14).

### Deferred Platform Seams

- **FEED-ROUTER-01**: Multi-provider feed-router (`set_provider` → provider-router keyed by
  symbol/asset-class) for concurrent providers (crypto aggregator + forex). The two-registry decoupling
  *enables* it.

- **CONN-OPT-01**: Single-connector-multi-`account_id` optimization (OKX master key + per-account routing on
  one session) vs one connector per `account_id`.

- **RISK-ALLOC-01**: Shared-`account_id` risk allocator (multiple portfolios pooling one venue account).
- **AUDIT-01**: Config audit-trail table (`system_config_audit`).
- **ERRHIST-01**: Errors-history table.
- **STATSHIST-01**: Stats-history table split (if periodic `stats.snapshot` upserts contend with config
  writes).

## Out of Scope

Explicitly excluded — documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| FastAPI app / routes / ASGI code (LR-01) | This milestone makes the engine *interfacable* (clean control/query seams, event ingress, centralized config); the web layer is a downstream consumer milestone. |
| `livebarfeed-depandas-time-model-datetime` refactor | Large look-ahead-safety-critical own-refactor of the same file — flagged as a co-located follow-on, not folded (spec §18). |
| `mutable-instrument-refactor` | Margin/carry-model concern, orthogonal to the God-object teardown. |
| `margin-equity-double-counts-notional-wr01` fix | Gated on re-freezing 6 owner-frozen goldens + external cross-validation; adjudicate before any live margin consumer (not this milestone). |
| `unify-backtest-direct-bar-generation` | Oracle-risky backtest-loop rewrite — conflicts with the LR-02 byte-exact gate. |
| Perp realism Phase B (FUND-01..04), production screener, multi-asset (forex/equities) | Out of the crypto-first live-refactor scope; backlog. |
| New third-party dependency / poetry change | Research STACK: every mechanic is stdlib or already-pinned; adding a dep regresses inertness. |

## Traceability

Each requirement maps to exactly one phase. As of 2026-07-09 the roadmap is created — the 12 phases are formalized in `.planning/ROADMAP.md` (`### Phase 1` .. `### Phase 12`, goals + success criteria + dependency graph). The old P4 (SqlEngine Migrations Relocation) and P5 (New Durable Stores) were merged into a single storage-schema phase P4 (both live-only, off the oracle hot path). Status `Pending` = mapped + roadmapped, awaiting execution.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CFG-01 | P1 | Complete |
| CFG-02 | P1 | Complete |
| CFG-03 | P1 | Complete |
| CFG-04 | P1 | Complete |
| CFG-05 | P1 | Complete |
| CFG-06 | P1 | Complete |
| BUS-01 | P2 | Complete |
| BUS-02 | P2 | Complete |
| BUS-03 | P2 | Complete |
| BUS-04 | P2 | Complete |
| CTX-01 | P2 | Complete |
| CTX-02 | P2 | Complete |
| CTX-03 | P2 | Complete |
| CTX-04 | P3 | Complete |
| SQL-01 | P4 | Complete |
| SQL-02 | P4 | Complete |
| STORE-01 | P4 | Complete |
| STORE-02 | P4 | Complete |
| STORE-03 | P4 | Complete |
| STORE-04 | P4 | Complete |
| STORE-05 | P4 | Complete |
| VENUE-01 | P5 | Complete |
| VENUE-02 | P5 | Complete |
| VENUE-03 | P5 | Complete |
| VENUE-04 | P5 | Complete |
| VENUE-05 | P5 | Complete |
| VENUE-06 | P5 | Complete |
| VENUE-07 | P5 | Complete |
| RUN-01 | P6 | Complete |
| RUN-02 | P6 | Complete |
| RUN-03 | P6 | Complete |
| RUN-04 | P6 | Complete |
| RUN-05 | P6 | Complete |
| RUN-06 | P6 | Complete |
| RUN-07 | P6 | Complete |
| SAFE-01 | P7 | Complete |
| SAFE-02 | P7 | Complete |
| SAFE-03 | P7 | Complete |
| SAFE-04 | P7 | Complete |
| SAFE-05 | P7 | Complete |
| SAFE-06 | P7 | Complete |
| ERR-01 | P8 | Complete |
| ERR-02 | P8 | Complete |
| ERR-03 | P8 | Complete |
| ERR-04 | P8 | Complete |
| RTCFG-01 | P9 | Complete |
| RTCFG-02 | P9 | Complete |
| RTCFG-03 | P9 | Pending |
| RTCFG-04 | P9 | Complete |
| RTCFG-05 | P9 | Complete |
| RTCFG-06 | P9 | Pending |
| STRAT-01 | P10 | Pending |
| STRAT-02 | P10 | Pending |
| STRAT-03 | P10 | Pending |
| MPORT-01 | P11 | Pending |
| MPORT-02 | P11 | Pending |
| MPORT-03 | P11 | Pending |
| MPORT-04 | P11 | Pending |
| MPORT-05 | P11 | Pending |
| MPORT-06 | P11 | Pending |
| TEST-01 | P6 | Complete |
| TEST-02 | P12 | Pending |
| TEST-03 | P12 | Pending |
| TEST-04 | P12 | Pending |

**Coverage:**

- v1 requirements: 64 total
- Mapped to phases: 64
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-09*
*Last updated: 2026-07-09 — roadmap revised to 12 phases (old P4 SqlEngine Migrations Relocation folded into old P5 New Durable Stores → merged storage-schema phase P4; all downstream phases renumbered −1); 64/64 requirements mapped, 0 orphans; full scope P1–P12 + 3 owner refinements*
