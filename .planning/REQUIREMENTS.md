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
   nothing heavy. **Zero new third-party dependency, no poetry change** anywhere in P1–P13 (research STACK).

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

- [x] **RTCFG-03**: Persisted overrides survive restart — `build_live_system` layers them over defaults
  on boot (§6e).

- [x] **RTCFG-04**: Immutable-at-runtime keys (`rng_seed`, money precision, SQL credentials, venue API
  credentials, `environment`, IDs) are rejected by the allowlist (§6e / owner decision).

- [x] **RTCFG-05**: Fee/slippage config keys are runtime-mutable **only for simulated venues**; a
  `ConfigUpdateEvent` targeting a *live* venue's fee/slippage is rejected (venue-kind-aware validation —
  real-venue fees/slippage come from actual venue fills, not engine config) (owner decision 2026-07-09).

- [x] **RTCFG-06**: The `system_store` `stats.snapshot` + `state.*` (status / halt_reason / last_error /
  last_started_at) double as the UI read-model — readable without touching hot-path locks (concerns 22/23,
  §6d). *(Ships regardless of the mutation-path scope.)*

### ★ Strategies Registry (P10)

- [x] **STRAT-01**: `StrategyRegistryStore` persists which strategies are active + config + subscriptions;
  on restart `build_live_system` rehydrates → re-registers active strategies (survives restart)
  (concern 18/§9).

- [x] **STRAT-02**: Runtime add / remove / enable / disable via `STRATEGY_COMMAND` (CONTROL) →
  `StrategiesHandler` applies + persists (§9).

- [x] **STRAT-03**: A strategy's config parameters are mutable at runtime via **atomic reconfiguration**
  (quiesce → apply → re-warmup the affected strategy), persisted to `StrategyRegistryStore` — folds
  `pair-strategy-live-reconfiguration.md` (v1.7 shipped only a refusal guard) (owner decision 2026-07-09).

### Strategies Handler Decomposition (P10.1)

- [x] **DECOMP-01**: `strategies_handler.py` (1648 LOC) is split into a thin data-plane `StrategiesHandler`
  (queue seam), a shared `ManagedStrategies` holder (owns `strategies`/`min_timeframe`/`_pending_removals`

  + registration/membership rules), and a `StrategyLifecycleManager` (the ~700-LOC control plane
  + the D-11 fill-driven removal completion); no behaviour change to any verb, the signal path, or
  pending-removal semantics (follow-up to P10; spec 2026-07-18).

- [x] **DECOMP-01a**: The three live deps stop being `None`-then-assigned. `registry_store` becomes
  handler-owned, derived in `__init__` from `(environment, sql_engine)` through a new
  `StrategyRegistryStorageFactory` (mirroring `SignalStorageFactory`/`OrderStorageFactory`, with the
  `has_table("strategy_registry")` probe inside the live arm so the D-21 first-start state still yields
  `None` + a WARNING); `portfolio_read_model` is passed from `compose.py` (where `portfolio_handler` is
  already a local); `strategy_catalog` rides into `compose_engine` as an `Optional[Any]` kwarg (the
  `alert_sink`/`system_store`/`error_policy` precedent) because D-01 forbids `itrader` importing a concrete
  strategy class. The three post-construction assignments at `live_trading_system.py:1630/1641/1642` are
  deleted. `ManagedStrategies` and `StrategyLifecycleManager` are then both constructed unconditionally in
  `StrategiesHandler.__init__` from module-top imports — no `Optional`, no guard, no late-init helper.

- [x] **DECOMP-02**: The backtest import graph pulls **no SQL stack** — no `sqlalchemy`, `psycopg2`, or
  `alembic` — and `test_okx_inertness.py` asserts that positively, not merely by the hardcoded `_FORBIDDEN`
  module-name list it checks today (a named list cannot catch a regression through an unlisted module).
  Every function-local import in `strategies_handler.py` is gone: the six blocks at 566 / 723-730 / 1010 /
  1041-1042 / 1101-1108 move to module top on their owning unit. *(Restated 2026-07-20: the original
  wording called these five imports "load-bearing" for GATE-01 and required the lifecycle manager to be
  "live-only, constructed only in the live wiring arm". A clean-interpreter probe disproved the first —
  importing all five targets leaks zero forbidden modules and zero SQLAlchemy — and the owner's
  `__init__`-time construction decision deliberately supersedes the second. The invariant GATE-01 actually
  protects is SQL-absence, so the requirement now names that directly.)*

- [x] **DECOMP-03**: `calculate_signals` is renamed `on_bar` (matches the `on_<event>()` callback
  convention) across the `_routes` literal (`full_event_handler.py`), the 59 test call-sites, and the docs
  (incl. the CLAUDE.md flow diagram); no compat shim; `test_dispatch_registry` passes.

### ★ Multi-Portfolio-Live (P11)

- [x] **MPORT-01**: The venue plugin's `new_account(portfolio_ref, config)` mints a per-portfolio account
  (venue-truth → `VenueAccount` scoped to `portfolio.account_id`; compute → a fresh `SimulatedAccount`);
  `_link_venue_account_to_portfolios` + its `RuntimeError(>1)` guard are deleted (LR-03/§10b).

- [x] **MPORT-02**: A distinct-`account_id` invariant fails **loud** at composition time — multiple
  portfolios sharing one venue `account_id` is rejected (pooled buying power the venue can't split back
  out is deferred) (§10a).

- [x] **MPORT-03**: A signal fans out to each subscribed portfolio; each sizes/orders independently against
  its own account; the venue partitions balance/positions/fills by `account_id` (§10a).

- [x] **MPORT-04**: `clOrdId` is renamed `client_order_id` (venue↔engine correlation), distinct from
  `portfolio_id` (attribution); every submitted order is tagged with its portfolio; fills route via
  `client_order_id`/`venue_order_id` → engine order → `FillEvent(portfolio_id)` → the right
  `Portfolio.on_fill` (LR-19/§10c).

- [x] **MPORT-05**: `PortfolioSpec` gains `account_id`; the `ReconciliationCoordinator` iterates active
  portfolios, reconciling each against its own `VenueAccount`/`account_id` (§10b-c).

- [x] **MPORT-06**: Connectors are keyed `(venue, account_id)` (VENUE-03) so multi-account portfolios share
  or decouple connectors correctly without a combinatorial matrix (LR-20/§8c).

- [x] **MPORT-07** *(DISCOVERED during P11 discussion, 2026-07-21 — not in the 2026-07-07 design)*: The
  **execution exchange** is keyed `(venue, account_id)`, not by venue name alone. `ExecutionHandler.exchanges`
  keys on the pair, `on_order` resolves the account from `event.portfolio_id` (via a new
  `PortfolioReadModel.account_for`), and `VenueBundle` carries per-account exchanges. **Why this is required, not
  an optimization:** `ExecutionHandler.on_order` currently does a bare `self.exchanges.get(event.exchange)`
  (`execution_handler.py:126`) while `OkxExchange` holds exactly one connector (`okx.py:101`) — so two portfolios
  on one venue with distinct `account_id`s both resolve to the *same* exchange and one account's orders would be
  submitted through the other account's authenticated session, silently defeating MPORT-01/03/06 even when
  credentials, accounts and the distinct-`account_id` invariant are all correct. `watch_my_trades` is a **private
  per-account stream**, so a shared exchange cannot subscribe to both accounts' fills at all. Architecturally this
  makes an existing dimension explicit rather than adding one: every mutable field on `OkxExchange` is already
  account-scoped, and the markets/precision map lives on the connector (`okx.py:952-955`). (P11 CONTEXT D-27.)

### One Venue Path + Account Ownership (P11.1 — added 2026-07-22 when P11.1 was split)

*Source: the 2026-07-22 Phase 11.1 discussion (`11.1-CONTEXT.md`, decisions D-01..D-08 / D-14 /
D-17..D-19). Root decision: domain objects stop participating in their own wiring — **objects receive
their collaborators; composition constructs them**. `Portfolio` mints its own `Account` and
`ExecutionHandler` mints its own `SimulatedExchange`, and composition then reaches in to overwrite or
alias the result. Fixing that at the source DELETES ~360 lines that a relocation would merely have moved.
The discussion explicitly rejected extracting a `trading_system/venue_wiring.py` module. Backtest and
live then differ only in which plugins are registered. Every requirement here is oracle-gated: SMA_MACD
byte-exact `134 / 46189.87730727451`.*

- [ ] **VENUE-01** *(D-01)*: `Account` carries no reference to `Portfolio`. `SimulatedCashAccount(initial_cash)`
  and `SimulatedMarginAccount(initial_cash)` drop the `portfolio` constructor parameter; `VenueAccount` already
  takes none. The two portfolio-dependent reads move into their method signatures — `maintenance_margin(positions, ...)`
  and `margin_ratio(equity)` — supplied by `PortfolioHandler`, already their only caller
  (`portfolio_handler.py:569` / `:581`). The mutual reference is an accident, not a structural constraint:
  `SimulatedCashAccount` stores `self.portfolio` and never reads it (that is the byte-exact oracle leaf), and only
  `SimulatedMarginAccount` reads it, at `simulated.py:831-833` and `:873`. **The `Account` ABC does NOT change** —
  neither method is abstract, and `account/conformance.py` references neither.
- [ ] **VENUE-02** *(D-02, D-03)*: `Portfolio.__init__` receives a **built** `Account`; the duplicate account-leaf
  selection at `portfolio.py:176-179` is deleted, and `VenuePlugin.new_account` becomes the sole account factory,
  losing its `portfolio_ref` parameter. Passing a *factory* into `Portfolio` was considered and rejected — it would
  leave `Portfolio` participating in its own wiring, which is the defect rather than the fix. Today the same
  margin-vs-cash selection is implemented twice, and `PaperVenuePlugin.new_account`'s own docstring admits it is
  the pre-11-07 `account_factory` copied verbatim.
- [ ] **VENUE-03** *(D-04)*: The backtest registers `PaperVenuePlugin` and goes through the same venue path as live,
  passing a real, empty `ConnectorProvider({})` — **no `Optional`/`None` wiring seam**, honouring the standing
  constraint against late-init. Safe because `ConnectorProvider.__init__` takes a plain plugin dict and
  `PaperVenuePlugin.build_bundle` deliberately ignores its `connectors` argument (paper has no venue session).
  GATE-01 inertness is preserved and independently evidenced: `venues/__init__.py` imports no concretion by P5
  acceptance gate, `venues/registry.py` has zero runtime imports, and `itrader.venues` is absent from
  `test_okx_inertness.py`'s `_FORBIDDEN` list.
- [ ] **VENUE-04** *(D-05, D-19)*: The backtest venue is named `'paper'`, the `('csv', DEFAULT_ACCOUNT_ID)` alias in
  `ExecutionHandler` is retired, and backtest portfolios pass `venue_name='paper'` explicitly so backtest and live
  portfolios are structurally identical at creation. **Highest oracle-risk item in the phase** — it warrants its own
  byte-exact-gated plan. Blast radius: `backtest_trading_system.py:520` (the string is `'csv'`, not `'simulated'`),
  the whole `exchanges` dict literal at `execution_handler.py:290-303` including the dead `('ccxt', …): None` slot,
  the direct reads at `backtest_trading_system.py:395` and `compose.py:239-240`, and ~6 test sites. All fail loudly.
- [ ] **VENUE-05** *(D-06, D-17)*: `PaperVenuePlugin` builds its **own** `SimulatedExchange` inside `build_bundle`,
  symmetric with `OkxVenuePlugin` building its own `OkxExchange`, from an `ExchangeConfig` received at construction
  (`PaperVenuePlugin(exchange_config)` at registration). `ExecutionHandler` neither mints one (`:290`) nor is handed
  one. This dissolves the compose-versus-venue-assembly cycle at its source — `PaperVenuePlugin(execution_handler.exchanges[...])`
  at `live_trading_system.py:2028` has nothing left to reach for. The config must be passed, not imported: it is absent
  from the `ITraderConfig` singleton AND run-derived, since `_seed_supported_symbols` folds this run's complete ticker
  set into `limits.supported_symbols` (`backtest_trading_system.py:67-78`, `:463-466`).
- [ ] **VENUE-06** *(D-07)*: `EngineContext` carries `rng`, so the one shared seeded `random.Random` reaches the plugin
  that now builds a stochastic component. A consequence of VENUE-05: determinism requires ONE instance injected at the
  wiring seam rather than re-derived per plugin. `EngineContext` currently carries only
  `bus`/`config`/`environment`/`feed`/`store`/`sql_engine`.
- [ ] **VENUE-07** *(D-08, D-14)*: A memoized `VenueBundles` provider over `(registry, connectors, ctx)` is held by BOTH
  `ExecutionHandler` and `PortfolioHandler`, each asking for the view it needs (the exchange, or the account). Nothing is
  passed in pre-built and nothing is mutated from outside. It REPLACES `assemble_venues`' eager map plus the registration
  loop at `live_trading_system.py:2101` — a swap, not an addition. Memoization is load-bearing: two independent
  `build_bundle` callers would produce two `OkxExchange` instances per account, and `OkxExchange.connect()` is the sole
  spawn site for `_stream_fills`/`_stream_orders`, so the fill streams would double-spawn. Exactly **one** data provider
  is built, for the feed, which closes `11-REVIEW.md` **WR-07** structurally — non-primary accounts build none, so there
  are no unwired credential-bearing providers to wire. The review's alternative fix (wire halt-signal on every provider)
  is rejected: it contradicts the documented single-feed decision at `live_trading_system.py:2347`.
- [ ] **VENUE-08** *(D-18)*: The commission estimator is decomposed. `FeeModelCommissionEstimator` leaves `compose.py`
  (`:57-81`), the `core/commission_estimator.py` seam narrows to a fee-model provider, and the admission convention
  (`side="buy"`, `order_type="market"`) moves into `AdmissionManager`, which owns it — it is admission policy, not wiring.
  Late binding MUST be preserved: `simulated.py:775` **replaces** the fee model object on config update, so holding it
  directly would silently compute reservations against a stale rate. **Reopens the prior-phase D-15 Protocol shape** —
  deliberate, not accidental. Side effect: the `isinstance(self._exchange, SimulatedExchange)` guard at `compose.py:78`
  is replaced by an explicit "this venue exposes no fee model" contract. The golden run pins `ZeroFeeModel` so the estimate
  is `0` under both shapes, but the reservation path is oracle-critical and value-identity must be PROVEN byte-exact.

### Account Provisioning + Mandatory Account Identity (P11.2 — split out of P11.1 on 2026-07-22)

*Source: the Phase 11 code review (`11-REVIEW.md` CR-02/CR-03/WR-03/WR-05) plus the 2026-07-22 design
discussion. Root decision: `(venue_name, account_id)` is mandatory for a live portfolio, and the DURABLE
STORE — not the spec — is the source of truth for both portfolios and accounts. The schema already encodes
this (`portfolios.venue_name` / `.account_id` are `NOT NULL` under a composite FK onto `venue_accounts`);
the code does not yet trust it.*

- [ ] **ACCT-01**: The live account set is derived from `VenueAccountStore.read_enabled_for(venue_name)`,
  not from the spec. The spec-derived halves of `_account_ids_for_spec` and the `spec.portfolios` field are
  deleted; `assemble_venues` receives the account set as an argument, and `live_trading_system.py` computes
  no account identity of its own. Decouples provisioning from portfolio creation — an account can be
  provisioned before any portfolio references it, which is what makes the composite FK satisfiable at
  `add_portfolio` time.
- [ ] **ACCT-02**: `_mint_account_rows` is replaced by a deliberate provisioning path — a
  `venue_account:{venue}/{id}` `config_router` scope mirroring the existing `venue:{name}` → `VenueStore`
  scope and reusing its secret-scrub guard. A **handoff, not a deletion**: minting is currently the only
  production writer of `venue_accounts`, so removing it unreplaced makes the FK reject the first
  `add_portfolio` on a fresh DB. Minting also writes `secret_ref=None`, routing that account to the ambient
  `OKX_API_*` credentials — the fail-open composite of `11-REVIEW.md` WR-05 — so it is a liability, not a
  convenience.
- [ ] **ACCT-03** *(closes 11-REVIEW CR-02)*: A live portfolio naming no venue account **raises** at
  composition time. Today it is silently skipped and left on its `SimulatedCashAccount` leaf with
  `is_venue_truth=False`, which disables snapshot, streaming, `VenueReconciler` and the D-04
  unexplained-residual HALT behind a green suite. Hard-raise rather than per-portfolio quarantine (the
  `260718-e36`/`evz` precedent): unlike a dark strategy, an unattached portfolio still routes orders.
  **Mandatory consequence (11-REVIEW WR-11)**: `tests/integration/test_multi_portfolio_lifecycle.py:104-125`
  gives BOTH paper portfolios `account_id=DEFAULT_ACCOUNT_ID` and no `venue_name`, and passes today only
  because that half-null shape makes `_persist_definition` skip the row (so the DB unique constraint never
  sees it) and keeps `assert_distinct_accounts` off the path entirely — i.e. the phase's flagship
  multi-portfolio test demonstrates the exact account sharing D-14/D-15 forbid. ACCT-03 makes the fixture
  illegal, so it must be given distinct `account_id`s and a real `venue_name` in this phase; the phase
  cannot go green otherwise. Close the half-null bypass explicitly rather than relying on it.
- [ ] **ACCT-04** *(closes 11-REVIEW WR-03)*: The six live-path `or DEFAULT_ACCOUNT_ID` coercions are
  deleted. Registration writes `(venue, 'default')` while both readers construct `(venue, None)` raw, so for
  an unnamed account the registered key is unreachable by every reader — a write-only entry, not merely an
  asymmetry. The backtest/simulated uses are KEPT: `DEFAULT_ACCOUNT_ID` is the backtest single-account
  identity and is load-bearing for the golden oracle.
- [ ] **ACCT-05** *(closes 11-REVIEW CR-03)*: The venue account is attached on every portfolio creation
  path, not only inside `build_live_system`. Under DB-as-source-of-truth this is the PRIMARY creation path:
  on a fresh DB nothing rehydrates, so the first `add_portfolio` yields a portfolio submitting real orders
  against a compute-leaf ledger with no reconcile. The attach seam must not use `None`-then-assign late
  wiring or a post-construction setter.
- [ ] **ACCT-06**: The two docstrings asserting the phantom *"plan 11-08 makes account_id mandatory at
  composition time"* invariant (`execution_handler.py:209`, `core/portfolio_read_model.py:227`) are
  corrected — ACCT-03 is what makes it true. The two citing 11-08's **distinct**-account invariant
  (`live_trading_system.py:1627`, `reconciliation_coordinator.py:164`) are accurate and stay untouched.
- [ ] **ACCT-07** *(closes 11-REVIEW WR-01)*: `PortfolioHandler._persist_definition` and
  `SqlPortfolioStorage.save_config` agree on when a definition row is required. `save_config`'s legacy
  account-state arm was deleted on the stated grounds that *"a live portfolio now always has a definition
  row"*, but `_persist_definition` returns early when `venue_name` or `account_id` is `None` — so for such a
  portfolio a runtime `portfolio:{id}` `CONFIG_UPDATE` raises `PortfolioStateError` out of `ConfigRouter`
  and its config never persists. ACCT-03 makes that early-return unreachable, which resolves the
  disagreement; the early-return itself is then removed or converted to the same typed raise so the two
  halves cannot drift apart again.
- [ ] **ACCT-08** *(closes 11-REVIEW WR-09)*: `PortfolioHandler` exposes `all_portfolios()` and
  `has_portfolio(portfolio_id)`, and the production reach-ins to the private `_portfolios` dict are
  converted (`portfolio_rehydrate.py:124`, `live_trading_system.py:1341/1591/1964`). Folded here because
  ACCT-01 and ACCT-05 rewrite two of those call sites anyway — the handler already exposes
  `get_active_portfolios()`, and every consumer reached for the private field only because no "all
  portfolios" / "is registered" accessor existed. **Co-located (11-REVIEW WR-02)**: the portfolio arm of
  `_layer_persisted_overrides` wraps its whole `for` loop in ONE `try/except _degrade_clean`, so a single
  poisoned `config_json` skips every portfolio after it in iteration order with one warning naming only the
  first failure — despite the docstring claiming per-scope isolation. The guard moves INSIDE the loop.
  Folded here because WR-02 and this requirement edit the SAME statement (`live_trading_system.py:1341`).
- [ ] **ACCT-09** *(closes 11-REVIEW WR-10)*: `ExecutionHandler.on_order`'s fail-closed paths emit a
  `FillEvent(REFUSED)` — the established rejection-as-event convention, which also reconciles the order
  mirror instead of leaving it PENDING forever — rather than only calling `logger.error(...)` and
  returning. Today a misconfigured live engine drops 100% of its orders while `get_status()` reports
  `RUNNING`, `errors_count: 0` and no halt reason. **Scope note**: ACCT-03 makes the middle branch
  (`if account_id is None`) unreachable, so this covers TWO paths (unknown portfolio, unregistered
  `(venue, account)` pair), and the dead branch is removed rather than instrumented — its comment is one of
  the two phantom-invariant citations ACCT-06 corrects.
- [ ] **ACCT-10** *(closes 11-REVIEW WR-04)*: Runtime portfolio deactivation PERSISTS. `_persist_definition`
  hardcodes `enabled=True` and is gated on row absence, and nothing else ever writes `enabled=False`, so
  `Portfolio.set_state(INACTIVE)` never reaches the store and a portfolio an operator deliberately stopped
  comes back ACTIVE and trading on the next restart — money-relevant, and silent. Add a
  `set_enabled(portfolio_id, enabled)` write on `PortfolioDefinitionStore`, called from whatever flips
  `PortfolioState`. This also makes `rehydrate_portfolios`' present-but-inactive branch
  (`portfolio_rehydrate.py:141-147`) reachable as designed instead of only via an out-of-band DB write.
- [ ] **ACCT-11** *(closes 11-REVIEW CR-04 + WR-12)*: The D-09 config move REFUSES rather than silently
  skipping. `_move_config` copies `portfolio_account_state.config_json` onto a matching `portfolios` row and
  counts a non-match as a benign "orphan" — but `portfolios` is created empty by the immediately preceding
  revision and the module docstring itself states nothing wrote `portfolios` rows before this phase, so
  EVERY source row is an orphan and `moved` is provably `0`. Meanwhile `load_config` (`sql_storage.py:597`)
  now reads ONLY `portfolios.config_json`, so any such blob is unreadable after `alembic upgrade head` —
  verbatim the failure the revision docstring calls *"the single highest-regression-risk operation in the
  phase, and the risk is that it fails SILENTLY"*. **Confirmed greenfield (2026-07-22): no deployment holds
  real persisted state**, so this is a guard against a state that should never arise, not a data migration —
  count orphans and raise with remediation instructions. WR-12: `_seed_for_the_move`
  (`test_p11_migration_chain.py:78-111`) hand-inserts a `portfolios` row at `_REVISION_ONE`, a state
  unreachable in a real chain, and the negative control varies only the chain head — so add a test whose
  staging inserts ONLY `portfolio_account_state` rows (the real pre-upgrade shape) and asserts the refusal.

### Live Composition-Root Dissolution (P12 — INSERTED 2026-07-22)

> Source: the 2026-07-22 pre-11.1 structural read of `itrader/trading_system/live_trading_system.py`.
> The file is **2409 lines** — a 1143-line facade class (105–1248) welded to a 1160-line composition
> root (1250–2409) of which `build_live_system` alone is **687 lines**. The backtest path splits the
> same job three ways (`backtest_trading_system.py` / `compose.py` / `backtest_runner.py`); live has
> no `compose.py` peer. The milestone goal states a *~200-line* facade and the `__init__` docstring
> at `:138` still cites that P7-EXIT gate; post-P7 the class is 1143 lines and grew through P9/P10/P11.
> These are the "Tier 2" findings — Tier 1 (the account-provisioning + venue-wiring extraction,
> ~510 lines) is Phase 11.1's own Wave 1, since 8 of 11 ACCT criteria edit that region.
> All six are **behaviour-preserving code motion**: no semantic change to any live contract.

- [ ] **COMP-01**: `build_live_system` **disappears as a builder**. No single function anywhere in the
  tree carries the live composition root. Composition becomes an ordered sequence of named,
  independently-constructible steps — storage bootstrap → engine → portfolio bootstrap → venue wiring →
  runtime-config platform → safety → runner — each constructible and assertable **without booting a
  `LiveTradingSystem`**. The seams are already legible in the current body's own section comments
  (`:1779` / `:1828` / `:1896` / `:1971` / `:2147` / `:2266`). A thin ordered entry point survives so
  the three externally-imported names keep resolving — verified 2026-07-22 that `LiveTradingSystem`,
  `build_live_system` and `_layer_persisted_overrides` are the **complete** external surface across
  `itrader/`, `tests/` (37 files touch the module) and `scripts/`, so the move is cheap behind a
  re-export. Whether the entry point keeps the `build_live_system` name is a discussion decision.
- [ ] **COMP-02**: Live storage bootstrap is a pure step. The `SqlSettings` credential probe that
  resolves `(environment, sql_engine, halt_record_store, system_store)` (`:1779–1826`) has no facade,
  venue or handler knowledge and is unit-testable on both arms — Postgres credential present, and the
  in-memory fallback that WR-10 requires to warn loudly rather than default a credential string.
- [ ] **COMP-03**: Config-ingress validation leaves the facade. `_validate_config_ingress` +
  `_dry_validate_config_ingress` (`:1135–1238`, 105 lines) touch no facade state beyond
  `self._config_router is None` and the logger, and are the literal FastAPI-400 boundary this milestone
  exists to expose (LR-01 keeps the ASGI code out; the *seam* is in scope). **Reconcile with**
  `config_router.py:402::_dry_validate_copy` — today two implementations of one validation contract,
  hand-synced and deliberately divergent (a fresh default instance vs `model_copy`, because the ingress
  check runs on the EXTERNAL caller thread and must not read the sub-models the engine thread writes).
  Either unify them or pin the divergence as a decision with the thread-ownership rationale in-code.
- [ ] **COMP-04**: The live stats + status read-model leaves the facade — `_stats` / `_stats_lock` /
  `_update_stats` / `_on_order_throttle_rejected` / `_increment_error_count` / `_snapshot_system_stats`
  (`:498`, 49 lines) / `get_status` (`:973`, 68 lines) — ~180 lines into one collaborator owning its own
  lock. `get_status` merges four sources (safety snapshot, stats dict, throttle counter, runner thread
  state, error-policy breaker snapshot) into a dict; that is what the FastAPI layer serves, so it belongs
  in a read-model, not on the lifecycle object. Together with COMP-05 this is what breaks the
  construction cycle COMP-06 measures.
- [ ] **COMP-05**: The three connector-loop callbacks leave the facade —
  `_on_venue_stream_down` / `_on_venue_stream_up` / `_request_connector_halt` (`:423–462`, 41 lines) —
  onto an object constructed with the bus. They touch **only** `global_queue` and the logger; nothing
  facade-owned. Load-bearing beyond tidiness: they are one of the two knots forcing the builder to
  construct the facade mid-function (`:2138`) before it can wire venue callbacks (`:2348–2358`). Their
  Pitfall-9 contract is preserved verbatim — thread-safe `bus.put` only, never blocking venue I/O on the
  connector asyncio loop, and `_request_connector_halt` keeps emitting the FIXED
  `HaltReason.CONNECTOR_FATAL.value` literal and never `str(exc)` (V7/T-07-01, no secret crosses the
  loop→engine boundary).
- [ ] **COMP-06**: **The None-then-assign wiring pattern is GONE — zero survivors, not a reduced count.**
  `LiveTradingSystem.__init__` today declares **nine** `Optional[Any] = None` wiring fields (`_safety`,
  `_stream_recovery`, `_throttle`, `_config_router`, `_system_store`, `_system_stats_store`,
  `_live_runner`, `_error_policy`, `_quarantined_strategies`) that composition assigns afterward across
  ~10 statements. Every one becomes a **required constructor argument** with a real value at
  construction: no `Optional[Any] = None` wiring field, no post-construction `facade._<field> =`
  assignment anywhere in composition. Grep-clean on both, verified as a completion gate.

  *Scope boundary — WIRING fields only, not runtime state.* `universe` / `_universe_handler` /
  `_session_initialized` are populated by `_initialize_live_session` at `start()` and legitimately do not
  exist at construction (D-12 keeps session init deferred, and the live suite monkeypatches that method
  in three places). They are runtime state, stay as they are, and this requirement does not touch them.
  The distinction is the point: a collaborator that exists before the facade must be injected; state that
  comes into being during the run must not be faked into the constructor.

  *Why this is achievable rather than aspirational* (verified against the code 2026-07-22):
  **six of the nine hold no facade reference at all** — `_stream_recovery`, `_throttle`,
  `_config_router`, `_system_store`, `_system_stats_store`, `_quarantined_strategies` are constructed
  from stores/config/bus/lifecycles and are late-attached only by habit; they are injectable today with
  no prerequisite. The **three genuine construction cycles** — `_safety` (needs
  `notify_status_change=facade._notify_status_change`), `_live_runner` (needs five facade hooks:
  `_on_loop_start` / `_update_stats` / `_record_bar_metrics` / `_on_loop_error` /
  `_on_order_throttle_rejected`), and `_error_policy` (`.bind(error_counter=facade._increment_error_count)`)
  — all close once **COMP-04 and COMP-05** move those callback bodies off the facade: every one of them
  reduces to `safety.update_status` + a stats write + a `portfolio_handler` read, none of which is
  facade-unique. COMP-04/05 are therefore hard prerequisites of this requirement, not neighbours.

  *One field needs explicit handling:* `_stop_event` is created in `__init__` today and handed **out**
  to `LiveRunner` + `WorkerSupervisor` by the builder. It must be created before the facade and injected
  into all three, so ownership is stated once rather than inverted.

  *Consequence that makes this checkable:* the WR-02 `StateError` guard at `start()`
  (`live_trading_system.py:697` — *"facade constructed outside build_live_system
  (LiveRunner/ErrorPolicy/SafetyController unwired)"*) becomes **unreachable and is deleted**. An unwired
  facade stops being constructible, so it stops needing a runtime check. If that guard cannot be deleted,
  this requirement is not met.

  *Blast radius (measured 2026-07-22):* exactly **one** production construction site
  (`live_trading_system.py:2138`) and **zero** direct constructions in `tests/` — every test reaches the
  facade through `build_live_system` / `for_exchange`. Five test-side late-attach assignments
  (`tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` ×2,
  `tests/support/replay_harness.py`, `tests/integration/test_strategy_external_add_lifecycle.py`,
  `tests/integration/test_config_ingress.py`) convert to construction-time injection. The other ~10
  matching assignments elsewhere in `itrader/` are other classes assigning their OWN constructor
  arguments (`session_initializer`, `route_registrar`, `stream_recovery_handler`, `config_router`,
  `full_event_handler`, `error_handler`) and are out of scope.
- [ ] **COMP-07** *(deferred here from Phase 11.1 by owner sign-off, 2026-07-22)*: **the live venue-truth
  account swap stops being a reach-in.** `_attach_venue_accounts` (`live_trading_system.py:1608-1721`,
  116 lines) re-assigns `portfolio.account` AFTER venue assembly, which is the exact
  "composition reaches in afterwards to overwrite the result" pattern Phase 11.1's goal names. Phase 11.1
  closes it for the **compute-account path** (backtest + paper) via VENUE-01/02 (D-01/D-02/D-03) but
  **cannot** close it for the live venue-truth path, for a boot-order fact discovered during 11.1 planning
  and stated in neither `11.1-CONTEXT.md` nor `11.1-RESEARCH.md`: live portfolios are rehydrated
  (`portfolio_rehydrate.py:130`) **before** `_build_account_specs` builds their per-account `VenueSpec`, so
  a `VenueAccount` — which needs that spec's `secret_ref` to resolve a connector — cannot exist at
  portfolio-creation time. The construction-time account is therefore always the compute leaf, which is
  what `_attach_venue_accounts:1640-1645` / `:1708-1711` already document that they expect.

  Satisfied when `Portfolio` receives its final `Account` — venue-truth or compute — at construction on
  the live path too, `_attach_venue_accounts` is deleted, and the `compute_venue` parameter injected into
  `PortfolioHandler` by 11.1's plan 09 (the seam this requirement removes) is gone.

  **⚠ Scope-fence conflict — decide this at Phase 12's discuss step, do not let an executor discover it.**
  This requirement needs the live boot ORDER to change (venue/account assembly must precede portfolio
  rehydrate). Phase 12's cross-cutting constraint says *"pure code-motion — no semantic change to any live
  contract"*, and its success criterion 7 pins the current order — distinct-account invariant → portfolio
  rehydrate → account/venue assembly → config layering → strategy rehydrate — as *"a hard invariant, not
  an implementation detail,"* pinned by `tests/integration/test_distinct_account_invariant.py` and
  documented as load-bearing in four independent ways at `live_trading_system.py:1896-1929`. COMP-07 is
  therefore **the one semantic change inside an otherwise behaviour-preserving phase**. Either widen the
  fence explicitly for this requirement (and re-derive what the four load-bearing reasons actually require,
  since `test_distinct_account_invariant.py` must then change rather than pass unmodified), or split
  COMP-07 into its own phase. Do not fold it in silently.

### Test Migration + Gates (P13 — except TEST-01, pulled forward into P6)

- [x] **TEST-01** *(delivered in **P6**, pulled forward from this phase)*: the ENTIRE replay test-harness moves
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

Each requirement maps to exactly one phase. The roadmap was created 2026-07-09 with 12 phases; it now carries **13 integer phases plus four decimal insertions** (6.1, 10.1, 11.1, 11.2), formalized in `.planning/ROADMAP.md` (`### Phase 1` .. `### Phase 13`, goals + success criteria + dependency graph). The old P4 (SqlEngine Migrations Relocation) and P5 (New Durable Stores) were merged into a single storage-schema phase P4 (both live-only, off the oracle hot path); Phase 12 (Live Composition-Root Dissolution) was inserted 2026-07-22, renumbering Test Migration + Gates to P13. Status `Pending` = mapped + roadmapped, awaiting execution.

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
| RTCFG-03 | P9 | Complete |
| RTCFG-04 | P9 | Complete |
| RTCFG-05 | P9 | Complete |
| RTCFG-06 | P9 | Complete |
| STRAT-01 | P10 | Complete |
| STRAT-02 | P10 | Complete |
| STRAT-03 | P10 | Complete |
| DECOMP-01 | P10.1 | Complete |
| DECOMP-01a | P10.1 | Complete |
| DECOMP-02 | P10.1 | Complete |
| DECOMP-03 | P10.1 | Complete |
| MPORT-01 | P11 | Complete |
| MPORT-02 | P11 | Complete |
| MPORT-03 | P11 | Complete |
| MPORT-04 | P11 | Complete |
| MPORT-05 | P11 | Complete |
| MPORT-06 | P11 | Complete |
| MPORT-07 | P11 | Complete |
| COMP-01 | P12 | Pending |
| COMP-02 | P12 | Pending |
| COMP-03 | P12 | Pending |
| COMP-04 | P12 | Pending |
| COMP-05 | P12 | Pending |
| COMP-06 | P12 | Pending |
| COMP-07 | P12 | Pending |
| TEST-01 | P6 | Complete |
| TEST-02 | P13 | Pending |
| TEST-03 | P13 | Pending |
| TEST-04 | P13 | Pending |

**Coverage:**

- v1 requirements: 64 total
- Mapped to phases: 64
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-09*
*Last updated: 2026-07-22 (second edit) — **Phase 11.1 was SPLIT in two (D-16)**. The eleven `ACCT-*` requirements moved from P11.1 to the new **Phase 11.2: Account Provisioning Bootstrap + Review Closures**, and eight new **VENUE-0N** requirements were added for P11.1's retained structural scope (one venue path + account ownership), derived from its locked decisions D-01..D-08 / D-14 / D-17..D-19. **94/94 requirements mapped, 0 orphans** (86 before VENUE). Every phase maps at least one requirement again.*

*Previously: 2026-07-22 — added the six **COMP-0N** requirements for the INSERTED **Phase 12: Live Composition-Root Dissolution** (`build_live_system` disappears; the facade sheds config-ingress validation, the stats/status read-model, and the connector-loop signal callbacks). Test Migration + Gates renumbered **P12 → P13**. **86/86 requirements mapped, 0 orphans** (80 before COMP). Note the previously-stated "69/69" was stale: it predated the eleven `ACCT-*` requirements added 2026-07-22 for the inserted Phase 11.1, so the true count was already 80 before COMP. Full scope P1–P13 + 3 owner refinements.*

*Prior: 2026-07-09 — roadmap revised to 12 phases (old P4 SqlEngine Migrations Relocation folded into old P5 New Durable Stores → merged storage-schema phase P4; all downstream phases renumbered −1); full scope P1–P12 + 3 owner refinements*
