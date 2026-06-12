# Phase 4: Composition & Config Interface - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

**COMP-01 + COMP-02 — the engine-level composition API and the uniform runtime config-update
surface.** The system is composed through a **declarative `SystemSpec`** (promoted from the
`tests/e2e/scenario_spec.py` `ScenarioSpec` shape) consumed by a `build_backtest_system(spec)`
factory, with **faithful construction-time `ExchangeConfig` threading** (`BacktestTradingSystem`
→ `ExecutionHandler` → `SimulatedExchange`) replacing the Phase-7 D-14 post-construction conftest
re-init seam, a formalized `csv_paths`/symbol passthrough, and a new **`OrderConfig`** Pydantic
model folding the loose stringly-typed `OrderManager` ctor params. **Every** handler/manager
(`OrderHandler`/`OrderManager`, `StrategiesHandler`, `ExecutionHandler`, `PortfolioHandler`,
`SimulatedExchange`, `BacktestBarFeed`) exposes a **uniform `update_config(dict) -> None`** with one
consistent contract (deep-merge → `model_validate` → atomic-swap; raise `ConfigurationError`),
applied **between event cycles, never mid-cycle**. For `StrategiesHandler`, `update_config`
re-validates → re-runs `init()` → re-derives warmup (consuming Phase 2's idempotent `init()` +
Phase 3's auto-warmup).

This phase also **folds the composition-root cleanups W4-02/03/05/06/07**: it extracts a shared
`compose_engine` wiring seam + a `BacktestRunner`, lifts reporting out of the root, removes the
duplicate `SystemConfig` construction (W4-06), and promotes the inline commission-estimator closure
to a typed `CommissionEstimator` read-model seam.

**Byte-exact phase.** Composition + config changes hold the v1.1 E2E golden suite + BTCUSD oracle
byte-exact (**134 trades / `final_equity 46189.87730727451`**); e2e **58/58**; full suite green;
`mypy --strict` clean. **No result change** — config updates are applied between event cycles and
the golden run never fires an `update_config`, so the oracle holds trivially.

**Already locked by REQUIREMENTS.md / the design note (NOT re-litigated here):** composition API
promoted from the `ScenarioSpec` shape; `OrderConfig` is a Pydantic model; the `update_config`
recipe (merge → `model_validate` → atomic-swap); applied between event cycles, never a mid-cycle
attribute poke; the re-runnable idempotent `init()` seam (Phase 2 D-10/D-12) + auto-warmup
re-derivation (Phase 3 D-08) that `StrategiesHandler.update_config` consumes.

**Explicitly NOT in this phase:**
- **The live runtime-config transport** (TradingInterface bridge methods + the direct-call-vs-queued-
  `ReconfigureEvent` decision) — needs the live threading model to exist/be testable → **N+4**.
- **Refactoring `LiveTradingSystem`** to adopt the shared `compose_engine` seam — unverified by the
  byte-exact suite; **deferred fast-follow** (design the seam for it now, don't touch live this phase).
- **Per-signal / per-intent execution** (entry price + `order_type` from the `SignalEvent`) — that is
  owner-gated **Phase 5** (SIG-01/02). Phase 4 keeps `market_execution` as a system-level default.
- **Multi-exchange composition** (Alpaca+Binance / Binance+IB) — live concern → **N+4**.
- **Pruning `SystemConfig`** down to live-essentials — deferred until live (N+4) clarifies needs.

</domain>

<decisions>
## Implementation Decisions

### Composition API (COMP-01)
- **D-01:** **Declarative spec + factory.** A frozen `SystemSpec` (strategies, portfolios, single
  exchange config, data/`csv_paths`, dates, timeframe) consumed by `build_backtest_system(spec)
  -> BacktestTradingSystem`. Promotes `ScenarioSpec` ~verbatim; serializable / web-UI-friendly /
  replayable. The e2e harness `_build_and_run` collapses onto `build_backtest_system(spec)`.
- **D-02:** **The spec is run-mode-agnostic.** `SystemSpec` describes WHAT to run (identical for
  backtest or live); the run-mode lives in the FACTORY name — `build_backtest_system(spec)` now,
  `build_live_system(spec)` later reuses the same spec. Do NOT name the spec `BacktestSpec`.
- **D-03:** **Rename `TradingSystem` → `BacktestTradingSystem`.** Restores symmetry with
  `LiveTradingSystem`, matches the existing `backtest_trading_system.py` filename. Pure mechanical
  byte-exact rename; touches import sites only (conftest, `scripts/run_backtest.py`,
  integration/oracle scripts). NOT `iTraderBacktestSystem` (package already namespaces it).
- **D-04:** **Construction pattern — factory builds, class is a thin holder.** `build_backtest_system(spec)`
  calls `compose_engine(spec)` to build the component graph, constructs the `BacktestRunner`, and
  injects the ready components into `BacktestTradingSystem(engine, runner)`. The class `__init__`
  becomes a dumb holder of pre-built components exposing `run()`. Maximizes the shared seam (live
  reuses `compose_engine` the same way) and is the most testable. Today's fat `__init__` is
  **partially replaced + slimmed**: its loose params → `SystemSpec`; its wiring body → `compose_engine`;
  the strategies/portfolios (today added post-construction via `add_strategy`/`add_portfolio`) → spec fields.

### OrderConfig (COMP-01)
- **D-05:** **Thin `OrderConfig`** (Pydantic, `extra="forbid"`) carrying the order-domain config —
  `market_execution: MarketExecution` (the system-level DEFAULT) now, extensible later. Threaded
  into `OrderManager` replacing the loose `market_execution: str | MarketExecution` ctor param
  (resolves COMP-01's "no more loose stringly-typed ctor params").
- **D-06:** **`commission_estimator` stays an injected dependency, NOT config.** It is behavior (a
  callable bound to the exchange fee model), not serializable Pydantic data — it cannot live in a
  `model_validate`/atomic-swap config model. See D-15 for its promoted seam.

### Uniform `update_config` (COMP-02)
- **D-07:** **One canonical signature + contract:** `update_config(self, updates: dict[str, Any]) -> None`.
  The `dict` arg (over `**kwargs`) maps cleanly onto a serialized reconfigure command / web-UI JSON
  payload and supports nested partial sub-model updates (e.g. `{'limits': {'min_order_size': ...}}`)
  that `**kwargs` can't express ergonomically. Standardizes the 3 existing inconsistent forms
  (`PortfolioHandler` `Dict→bool`; `Portfolio`/`SimulatedExchange` `**kwargs→None`).
- **D-08:** **Error contract — reuse the existing `core` `ConfigurationError`** (`config_key`,
  `config_value`, `reason`). Return `None`; raise on any failure. The canonical body **wraps
  pydantic's `ValidationError`** (raised by `model_validate`, which also catches unknown keys via
  `extra="forbid"`) into `ConfigurationError`, so the future web layer catches ONE iTrader type →
  HTTP 4xx with structured fields. Standardizes `SimulatedExchange` off its bare `ValueError` and
  `PortfolioHandler` off its `bool` return. **No new custom exception** (a `ConfigUpdateError(ConfigurationError)`
  subtype is only warranted if runtime-reconfig failures later need a different HTTP code; deferrable
  without breaking the single-catch contract).
- **D-09:** **Uniform CONTRACT, per-handler INTERNALS.** Every handler shares the same signature +
  error contract + between-cycles discipline. Internals differ:
  - config-model handlers (`Portfolio`, `SimulatedExchange`, `OrderManager`/`OrderHandler` via the
    new `OrderConfig`, `ExecutionHandler`): `deep_merge(self.config.model_dump(), updates)` →
    `Config.model_validate(merged)` → atomic-swap the reference.
  - `StrategiesHandler`: re-apply params → `validate()` → re-run `init()` → re-derive warmup.
  - `BacktestBarFeed`: see D-10.
  Do NOT introduce a `StrategiesHandlerConfig`/`FeedConfig` just to force literal model_validate on
  every handler — `StrategiesHandler`'s real work is re-running `init()` regardless.
- **D-10:** **`BacktestBarFeed.update_config` is interface-conformance.** It exposes the uniform
  signature but **raises `ConfigurationError` for changes that can't be safely hot-applied
  mid-run** (notably `base_timeframe` — a "replace, not a hot-swap" that ripples into the ping grid /
  `min_timeframe`). Honest about backtest reality; the live "replace" path is N+4.

### Runtime/live scope (COMP-02)
- **D-11:** **Phase 4 ships the `update_config` METHODS only.** Atomic-swap (build a fully-validated
  config object, then `self.config = new` — atomic under the GIL) **is the thread-safety primitive**;
  a direct call is safe at the object level. Thread-safety otherwise honored via the existing
  per-handler locks (`Portfolio`/`SimulatedExchange` `RLock` in live) + the single-writer backtest
  contract — **no new locking machinery**. Validate via direct unit tests + the byte-exact gate
  (methods don't fire during the golden run).
- **D-12:** **Defer the transport to N+4.** The `TradingInterface` bridge methods
  (`update_portfolio_config(...)` → `handler.update_config(...)`) AND the **direct-call vs queued
  `ReconfigureEvent`** decision both need the live threading model to exist and be testable. The
  queued-command path's only extra guarantee over a direct atomic-swap is *intra-cycle consistency*
  (a swap landing between two reads in one event) — a refinement, not a blocker. Decide it in N+4.

### Symbol admission / D-14 seam replacement (COMP-01)
- **D-13:** **`SystemSpec` drives `supported_symbols` at construction.** The symbols declared in the
  spec (its `data`/tickers — already known from `csv_paths` keys) are folded into
  `ExchangeConfig.limits.supported_symbols` and seeded at `SimulatedExchange` construction.
  This **removes the hardcoded `register_symbol('BTCUSD')` in `ExecutionHandler.__init__`** AND the
  conftest post-construction `register_symbol` loop. Works for both `build_backtest_system(spec)`
  and direct construction (oracle path derives from `csv_paths` keys). `register_symbol` stays a
  valid public seam but is **no longer load-bearing for composition**. **Byte-exact target:** the
  final `_supported_symbols` set must equal today's (default ∪ `BTCUSD` ∪ spec tickers). Beware the
  PATTERNS-A2 trap: `update_config` re-derives `_supported_symbols` by *replacement* — construction
  must seed the complete set, not rely on additive registration.

### Composition-root cleanups (W4-02/03/05/06/07, folded into COMP-01)
- **D-14:** **Extract within backtest now; design-for-live, defer the live refactor.** Split
  `backtest_trading_system.py` into a **shared `compose_engine` wiring seam** (the component-graph
  build that both modes duplicate today, per CLAUDE.md) + a **`BacktestRunner`** (the sync for-loop,
  **fail-fast**, preserving `record_metrics` post-bar ordering exactly — W4-02 stays a direct call,
  no event reroute) + **reporting lifted into `reporting/`** (`_print_metrics_summary`, W4-07).
  Tidy the `feed.precompute` run-setup orchestration (W4-03). **Do NOT modify `LiveTradingSystem`
  this phase** (unverified by the byte-exact suite; live error-policy/threading/storage differences).
  → fast-follow: `LiveTradingSystem` adopts `compose_engine`.
- **D-15:** **Promote the inline `_estimate_commission` closure to a typed `CommissionEstimator`
  read-model seam** (mirroring `PortfolioReadModel`). Define a `CommissionEstimator` **`Protocol`**
  in `core/` (primitive `(Decimal, Decimal) -> Decimal` signature → zero `itrader` deps, honors
  core's dependency rule). **Retype `OrderManager.commission_estimator`** from `Callable[...]` to the
  Protocol. The concrete adapter is a small named class over the exchange (e.g.
  `FeeModelCommissionEstimator`) holding the **exchange ref** and reading `fee_model` in `__call__`
  to **preserve late binding** (`update_config` may rebuild the fee model), living in the
  execution/wiring layer, injected at `compose_engine`. Keeps the `side="buy", order_type="market"`
  D-04 admission convention. **Byte-exact** (pure structure/typing change; fees pinned 0 in golden).
- **D-16:** **W4-06 — `rng_seed` stays a run-wide determinism setting** (`SystemConfig.performance`,
  per locked **D-11** "one shared seeded `random.Random` injected at wiring" — shared across all
  stochastic components, present and future; NOT scoped into `ExchangeConfig`, which would mis-model
  it the moment a 2nd stochastic component / 2nd exchange appears). Fix the duplication by reading the
  seed from the existing process-wide `config` singleton (`from itrader import config`) instead of
  `ExecutionHandler._resolve_rng_seed()` constructing a **2nd** `SystemConfig.default()`. Byte-exact
  (seed stays 42). Do NOT over-thread the mostly-future `SystemConfig` through composition.
- **D-17:** **W4-05 — `BarFeed` ABC stays in `price_handler/feed/base.py`.** It is a price-domain
  abstraction; `PortfolioReadModel` lives in `core/` only because it's a read seam shared by
  `portfolio_handler` AND `order_handler` (cross-domain pull `BarFeed` lacks). Zero churn, byte-exact.

### Claude's Discretion
- Exact `SystemSpec` field names / whether portfolios↔strategies subscription is declared in the
  spec or wired by the factory (subject to the e2e harness mapping cleanly + byte-exact).
- Internal structure of the deep-merge helper and the atomic-swap mechanics per handler (D-07/D-09),
  as long as mypy-strict + byte-exact.
- `compose_engine` signature/return shape and how the `BacktestRunner` receives the engine (D-04/D-14).
- Exact module home for the `FeeModelCommissionEstimator` adapter (execution-adapter module vs the
  `compose_engine` module) (D-15).
- How `csv_paths`/symbol derivation is surfaced on the spec vs derived in the factory (D-13).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source / requirements
- `.planning/REQUIREMENTS.md` — **COMP-01** + **COMP-02** (§"Composition & Config Interface", the
  authoritative requirements); the byte-exact-vs-owner-gated re-baseline discipline; the sequencing
  rationale (STRAT-01 → COMP-02 dependency).
- `.planning/ROADMAP.md` §"Phase 4: Composition & Config Interface" — goal + 4 success criteria (the
  pass/fail contract); §"Phase 5" (SIG-01/02) for the per-signal-execution out-of-scope boundary.
- `.planning/notes/strategy-authoring-surface-999.5c.md` §5 "Runtime reconfiguration constraint (folds
  in COMP-01 / part b)" — the between-event-cycles / `init()`-re-runnable rationale behind D-09/D-11/D-12;
  §"deploy" (override-at-construction reuse model) behind D-01.
- `.planning/notes/v1.3-concerns-triage.md` — the W4-02/03/05/06/07/09 item definitions folded here.

### Prior phase decisions this phase consumes
- `.planning/phases/02-strategy-authoring-surface/02-CONTEXT.md` — Phase 2 D-10 (re-runnable
  idempotent `init()`), D-12 (per-strategy `reconfigure(**kwargs)` = the unit `StrategiesHandler.update_config`
  calls), D-13 (no `__setattr__` guard; mutability enables reconfig).
- `.planning/phases/03-declared-indicator-framework/03-CONTEXT.md` — Phase 3 D-08 (auto-warmup
  re-derivation on `init()` re-run, re-derived by `StrategiesHandler.update_config`).

### Code to migrate / touch (the blast radius)
- `itrader/trading_system/backtest_trading_system.py` — `TradingSystem`→`BacktestTradingSystem`
  rename; fat `__init__` split into `compose_engine` + `BacktestRunner` + thin holder; the
  `_estimate_commission` closure (lines ~124-128) → `CommissionEstimator` seam; `record_metrics`
  ordering (line ~221) preserved; `_print_metrics_summary` (line ~276) → `reporting/`; `feed.precompute`
  orchestration (line ~190).
- `itrader/order_handler/order_manager.py` + `order_handler.py` — new `OrderConfig` threading;
  `commission_estimator` retyped `Callable`→`CommissionEstimator` Protocol; `update_config` added.
- `itrader/execution_handler/execution_handler.py` — `_resolve_rng_seed` (line ~54-62) reads the
  `config` singleton instead of a 2nd `SystemConfig`; hardcoded `register_symbol('BTCUSD')` (line ~111)
  removed; `update_config` added.
- `itrader/execution_handler/exchanges/simulated.py` — `update_config` (line ~622) migrated to the
  canonical `dict`→`ConfigurationError` contract; `_supported_symbols` seeded from construction config
  (lines ~98, ~664-665 the replacement trap).
- `itrader/portfolio_handler/portfolio_handler.py` (`update_config` line ~456, `Dict→bool`) +
  `portfolio.py` (`update_config` line ~163, `**kwargs→None`) — migrated to the canonical contract.
- `itrader/strategy_handler/strategies_handler.py` — `update_config` (re-validate→`init()`→re-derive
  warmup); `BacktestBarFeed` (`price_handler/feed/bar_feed.py`) — interface-conformance `update_config`.
- NEW: `core/commission_estimator.py` (`CommissionEstimator` Protocol); `config/order.py`
  (`OrderConfig`); the `SystemSpec` + `build_backtest_system` + `compose_engine` + `BacktestRunner`
  homes (planner's discretion within `trading_system/`).
- `tests/e2e/scenario_spec.py` (`ScenarioSpec`→`SystemSpec` promotion) + `tests/e2e/conftest.py`
  (`_build_and_run` collapses to `build_backtest_system(spec)`; D-14 post-construction re-init seam
  lines ~316-333 + `register_symbol` loop line ~349 removed).
- `scripts/run_backtest.py` + the oracle/integration construction sites — `BacktestTradingSystem`/
  `build_backtest_system` migration.

### Config convention (must match)
- `itrader/config/exchange.py` (`ExchangeConfig`, `extra="forbid"`, nested sub-models, `default()`)
  and `itrader/config/portfolio.py` (`PortfolioConfig`) — the Pydantic convention the new `OrderConfig`
  follows.
- `itrader/core/portfolio_read_model.py` — the read-model-seam Protocol pattern `CommissionEstimator`
  mirrors (D-15).
- `CLAUDE.md` + `.planning/codebase/CONVENTIONS.md` — tabs in handler modules / 4 spaces in `config/`,
  `core/`, `price_handler/feed/`; Decimal money policy; the config-enum exception; the broad-`except`
  run-mode policy.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`tests/e2e/scenario_spec.py::ScenarioSpec`** (frozen dataclass: `start/end/timeframe/ticker/
  starting_cash/data/strategies/portfolios/exchange/actions` + `PortfolioSpec`) — the shape `SystemSpec`
  promotes ~verbatim. `tests/e2e/conftest.py::_build_and_run` (lines ~287-369) is the imperative
  unpacking that `build_backtest_system(spec)` replaces.
- **The 3 existing `update_config` implementations** — `PortfolioHandler` (line 456, `Dict→bool`, the
  only one already doing `model_validate` via `_deep_merge`), `Portfolio` (line 163, `**kwargs→None`,
  `config_mapping` pokes), `SimulatedExchange` (line 622, `**kwargs→None`, re-derives size caches).
  PortfolioHandler's deep-merge + `model_validate` is the closest existing template for the canonical body.
- **Phase 2/3 `init()`/`reconfigure`/auto-warmup seam** (`strategy_handler/base.py`) — already
  re-runnable/idempotent; `StrategiesHandler.update_config` calls it.
- **`ExchangeConfig`/`PortfolioConfig` Pydantic models** (`extra="forbid"`, `default()`, nested
  sub-models) — the `OrderConfig` template.
- **`PortfolioReadModel` Protocol** (`core/portfolio_read_model.py`) — the typed read-model-seam
  pattern for `CommissionEstimator` (D-15).

### Established Patterns
- **Read-model seams in `core/`** sidestep the queue-only rule for cross-domain *reads* (PortfolioReadModel);
  `CommissionEstimator` is the same shape (order reads execution's fee estimate).
- **`register_symbol` is additive (union); `update_config` re-derives by replacement** (PATTERNS-A2) —
  the byte-exact trap D-13 must respect: seed the complete `supported_symbols` at construction.
- **`_estimate_commission` reads `fee_model` at CALL time** (late binding; `update_config` may rebuild it)
  — D-15's adapter holds the exchange ref, not the fee_model.
- **`record_metrics` post-bar ordering** (run loop) is byte-exact-sensitive — D-14 keeps it a direct call.
- **Determinism is engine-wiring-level** (D-11/D-16) — one shared seeded `Random`, seed from
  `performance.rng_seed=42`.

### Integration Points
- `compose_engine` is the shared wiring seam both `build_backtest_system` (now) and `LiveTradingSystem`
  (fast-follow) consume — the genuine backtest↔live overlap (the run DRIVER is mode-specific and NOT shared).
- `OrderManager` ↔ execution decoupling is via the injected `CommissionEstimator` (no cross-domain import).
- The byte-exact gate: e2e 58/58 + BTCUSD oracle (134 / `46189.87730727451`); config updates never fire
  in the golden run.

</code_context>

<specifics>
## Specific Ideas

- Target factory/holder shape (D-04):
  ```python
  def build_backtest_system(spec: SystemSpec) -> BacktestTradingSystem:
      engine = compose_engine(spec)          # SHARED wiring seam (live reuses later)
      runner = BacktestRunner(engine, ...)   # sync for-loop, fail-fast, record_metrics order kept
      return BacktestTradingSystem(engine, runner)  # thin holder, exposes run()
  ```
- Canonical `update_config` body (D-07/D-08/D-09):
  ```python
  def update_config(self, updates: dict[str, Any]) -> None:
      merged = deep_merge(self.config.model_dump(), updates)
      try:
          new = SomeConfig.model_validate(merged)   # extra="forbid" catches unknown keys
      except pydantic.ValidationError as e:
          raise ConfigurationError(reason=str(e)) from e
      self.config = new                              # atomic swap (GIL-atomic reference assign)
  ```
- `CommissionEstimator` Protocol + late-binding adapter (D-15) — see the locked preview in D-15.

</specifics>

<deferred>
## Deferred Ideas

- **Live runtime-config transport (N+4)** — `TradingInterface.update_*_config(...)` bridge methods +
  the **direct-call vs queued `ReconfigureEvent`** decision (the queue path's only extra guarantee is
  intra-cycle consistency). Build when the live threading model exists/is testable.
- **`LiveTradingSystem` adopts `compose_engine` (immediate fast-follow)** — dedupe the live composition
  root onto the shared wiring seam. Out of the byte-exact gate (no live golden coverage); do it once the
  backtest shape is proven.
- **Multi-exchange composition (N+4)** — shape the spec's exchange field as `dict[str, ExchangeConfig]`
  with strategies/portfolios naming their venue (Alpaca+Binance / Binance+IB). Engine already hints at it
  (`ExecutionHandler.exchanges` is a dict).
- **Per-signal `market_execution` (fill-timing) override** — beyond Phase 5's SIG-02 (which does per-intent
  `order_type`/entry-price). A finer extension; capture for a future signal-contract phase.
- **Prune `SystemConfig` to live-essentials (N+4)** — ~95% of it (threading/async/pools/monitoring/daemon
  lifecycle) is future-live scaffolding; the backtest uses only `performance.rng_seed`. Audit when live
  work clarifies what's actually needed.
- **`ConfigUpdateError(ConfigurationError)` subtype** — only if runtime-reconfig failures later need a
  distinct HTTP code; addable without breaking the single-catch contract (D-08).

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 4-composition-config-interface*
*Context gathered: 2026-06-12*
