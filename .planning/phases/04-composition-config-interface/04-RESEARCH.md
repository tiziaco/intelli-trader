# Phase 4: Composition & Config Interface - Research

**Researched:** 2026-06-12
**Domain:** Composition-root refactor + uniform runtime config surface (Pydantic v2 model-validate/atomic-swap) on an event-driven Python 3.13 backtest engine
**Confidence:** HIGH (all findings verified against the actual codebase; design is locked by CONTEXT.md — this research is execution-risk-focused, not exploratory)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Composition API (COMP-01)**
- **D-01:** Declarative frozen `SystemSpec` (strategies, portfolios, single exchange config, data/`csv_paths`, dates, timeframe) consumed by `build_backtest_system(spec) -> BacktestTradingSystem`. Promotes `ScenarioSpec` ~verbatim. The e2e harness `_build_and_run` collapses onto `build_backtest_system(spec)`.
- **D-02:** The spec is **run-mode-agnostic** — run-mode lives in the FACTORY name (`build_backtest_system` now, `build_live_system` later reuses the same spec). Do NOT name it `BacktestSpec`.
- **D-03:** Rename `TradingSystem` → `BacktestTradingSystem` (pure mechanical byte-exact rename; touches import sites only — conftest, `scripts/run_backtest.py`, integration/oracle scripts). NOT `iTraderBacktestSystem`.
- **D-04:** Factory builds, class is a thin holder. `build_backtest_system(spec)` calls `compose_engine(spec)` to build the component graph, constructs `BacktestRunner`, injects ready components into `BacktestTradingSystem(engine, runner)`. The class `__init__` becomes a dumb holder exposing `run()`. Today's fat `__init__`: loose params → `SystemSpec`; wiring body → `compose_engine`; post-construction `add_strategy`/`add_portfolio` → spec fields.

**OrderConfig (COMP-01)**
- **D-05:** Thin `OrderConfig` (Pydantic, `extra="forbid"`) carrying `market_execution: MarketExecution` (system-level DEFAULT) now, extensible later. Threaded into `OrderManager` replacing the loose `market_execution: str | MarketExecution` ctor param.
- **D-06:** `commission_estimator` stays an **injected dependency, NOT config** (behavior, not serializable Pydantic data). See D-15.

**Uniform `update_config` (COMP-02)**
- **D-07:** One canonical signature + contract: `update_config(self, updates: dict[str, Any]) -> None`. The `dict` arg (over `**kwargs`) supports nested partial sub-model updates. Standardizes the 3 existing inconsistent forms.
- **D-08:** Error contract — reuse existing `core` `ConfigurationError` (`config_key`, `config_value`, `reason`). Return `None`; raise on any failure. Body **wraps** pydantic's `ValidationError` (raised by `model_validate`; `extra="forbid"` catches unknown keys) into `ConfigurationError` so the future web layer catches ONE iTrader type. **No new custom exception.**
- **D-09:** Uniform CONTRACT, per-handler INTERNALS. config-model handlers: `deep_merge(self.config.model_dump(), updates)` → `Config.model_validate(merged)` → atomic-swap. `StrategiesHandler`: re-apply params → `validate()` → re-run `init()` → re-derive warmup. `BacktestBarFeed`: see D-10. Do NOT introduce a `StrategiesHandlerConfig`/`FeedConfig` just to force literal model_validate.
- **D-10:** `BacktestBarFeed.update_config` is interface-conformance — exposes the uniform signature but **raises `ConfigurationError` for changes that can't be safely hot-applied** (notably `base_timeframe`).
- **D-11:** Phase 4 ships the `update_config` METHODS only. Atomic-swap is the thread-safety primitive; a direct call is safe at object level. No new locking machinery. Validate via direct unit tests + the byte-exact gate.
- **D-12:** Defer the transport (TradingInterface bridge methods + direct-call-vs-queued-`ReconfigureEvent`) to N+4.

**Symbol admission / D-14 seam replacement (COMP-01)**
- **D-13:** `SystemSpec` drives `supported_symbols` at construction. Symbols from the spec's data/tickers fold into `ExchangeConfig.limits.supported_symbols`, seeded at `SimulatedExchange` construction. **Removes the hardcoded `register_symbol('BTCUSD')` in `ExecutionHandler.__init__`** AND the conftest post-construction `register_symbol` loop. `register_symbol` stays valid but no longer load-bearing. **Byte-exact target:** final `_supported_symbols` set must equal today's (default ∪ `BTCUSD` ∪ spec tickers). Beware PATTERNS-A2: `update_config` re-derives by REPLACEMENT — construction must seed the COMPLETE set.

**Composition-root cleanups (W4-02/03/05/06/07)**
- **D-14:** Extract within backtest now; design-for-live, defer the live refactor. Split into a shared `compose_engine` wiring seam + a `BacktestRunner` (sync for-loop, **fail-fast**, preserving `record_metrics` post-bar ordering exactly — W4-02 stays a direct call) + reporting lifted into `reporting/` (`_print_metrics_summary`, W4-07). Tidy `feed.precompute` orchestration (W4-03). **Do NOT modify `LiveTradingSystem` this phase.**
- **D-14a:** `compose_engine`-vs-factory boundary — mode-specific backend SELECTION lives in the FACTORY, not the shared seam. `compose_engine` must NOT hardcode `'backtest'`. `build_backtest_system` picks `OrderStorageFactory.create('backtest')` and passes the selected `OrderStorage` into `compose_engine(spec, order_storage=...)`. Do NOT bake a backend string into `compose_engine`.
- **D-15:** Promote the inline `_estimate_commission` closure to a typed `CommissionEstimator` read-model seam (mirroring `PortfolioReadModel`). Define a `CommissionEstimator` **`Protocol`** in `core/` (primitive `(Decimal, Decimal) -> Decimal` signature → zero `itrader` deps). Retype `OrderManager.commission_estimator` from `Callable[...]` to the Protocol. The concrete adapter (e.g. `FeeModelCommissionEstimator`) holds the **exchange ref** and reads `fee_model` in `__call__` to **preserve late binding**, injected at `compose_engine`. Keeps `side="buy", order_type="market"`. **Byte-exact.**
- **D-16:** W4-06 — `rng_seed` stays a run-wide determinism setting. Fix the duplication by reading the seed from the existing process-wide `config` singleton (`from itrader import config`) instead of `ExecutionHandler._resolve_rng_seed()` constructing a 2nd `SystemConfig.default()`. Byte-exact (seed stays 42). Do NOT over-thread `SystemConfig`.
- **D-17:** W4-05 — `BarFeed` ABC stays in `price_handler/feed/base.py`. Zero churn, byte-exact.

### Claude's Discretion
- Exact `SystemSpec` field names / whether portfolios↔strategies subscription is declared in the spec or wired by the factory (subject to the e2e harness mapping cleanly + byte-exact).
- Internal structure of the deep-merge helper and the atomic-swap mechanics per handler (D-07/D-09).
- `compose_engine` signature/return shape and how `BacktestRunner` receives the engine (D-04/D-14).
- Exact module home for the `FeeModelCommissionEstimator` adapter (execution-adapter module vs the `compose_engine` module) (D-15).
- How `csv_paths`/symbol derivation is surfaced on the spec vs derived in the factory (D-13).

### Deferred Ideas (OUT OF SCOPE)
- Live runtime-config transport (N+4) — `TradingInterface.update_*_config(...)` + direct-call-vs-queued-`ReconfigureEvent`.
- `LiveTradingSystem` adopts `compose_engine` (immediate fast-follow, NOT this phase).
- Multi-exchange composition (N+4) — `dict[str, ExchangeConfig]` spec shape.
- Per-signal `market_execution` (fill-timing) override — beyond Phase 5's SIG-02.
- Prune `SystemConfig` to live-essentials (N+4).
- `ConfigUpdateError(ConfigurationError)` subtype — only if runtime-reconfig later needs a distinct HTTP code.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COMP-01 | Engine-level composition API (promote `ScenarioSpec` shape), construction-time `ExchangeConfig` threading, new `OrderConfig`, formalized `csv_paths` passthrough; folds W4-02/03/05/06/07. | §Architecture Patterns (compose_engine/runner/factory split), §Byte-Exact Trap Map (symbol set, commission late-binding, rng dedup), §Don't Hand-Roll (deep-merge, atomic-swap). |
| COMP-02 | Uniform `update_config(dict) -> None` on every handler/manager (merge → `model_validate` → atomic-swap; unified error contract); between event cycles, thread-safe; `StrategiesHandler` re-runs `init()` + re-derives warmup. | §Architecture Patterns (canonical body + per-handler internals), §Common Pitfalls (3 existing forms to migrate), §Validation Architecture (per-handler unit tests + error contract). |
</phase_requirements>

## Summary

This is a **byte-exact structural refactor** of the composition root plus the addition of a uniform runtime config surface. There is no new domain technology to research — Pydantic v2 (^2.13, already in use), the in-house event queue, and the existing config models are the entire stack. The research value here is **execution-risk surfacing**: every place the refactor could accidentally perturb the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) or the e2e golden suite (58 leaves).

The golden run **never fires an `update_config`** (verified: `scripts/run_backtest.py` and the integration oracle construct, `add_strategy`, `add_portfolio`, `subscribe_portfolio`, `run()` — no config update; the e2e harness fires `update_config`-equivalent mutations only via the `Action` operator hook, and only on leaves that carry actions). So COMP-02's methods are oracle-dark **by construction** — they are validated by direct unit tests, not the golden gate. The byte-exact risk is concentrated entirely in **COMP-01's structural moves**: the symbol-set seeding (PATTERNS-A2 replacement-vs-union trap), the commission-estimator late-binding adapter, the rng-seed dedup, and the ordering preservation when the fat `__init__`/`run()` is split into `compose_engine` + `BacktestRunner` + holder.

**Primary recommendation:** Sequence the work so the structural rename + extraction (COMP-01) lands and is proven byte-exact **before** any `update_config` migration (COMP-02) — the two are independently gated, and COMP-02's methods don't touch the golden path. Within COMP-01, treat the symbol-set seeding and the `record_metrics`/`feed.precompute` ordering as the two highest-risk byte-exact points.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Spec → component graph wiring | Composition root (`trading_system/`) | — | `compose_engine` is the shared seam both backtest (now) and live (fast-follow) consume. |
| Mode-specific backend selection (storage, exchange) | Factory (`build_backtest_system`) | — | D-14a: the shared seam must stay mode-agnostic; the factory picks concretes and injects them. |
| Run driver (sync for-loop, fail-fast, record_metrics order) | `BacktestRunner` (composition root) | — | The DRIVER is mode-specific and NOT shared (live = threaded daemon, publish-and-continue). |
| Commission estimate read | `core/` Protocol seam | execution adapter | D-15: order domain reads execution's fee estimate via injected Protocol, no cross-domain import (mirrors `PortfolioReadModel`). |
| Symbol admission | Execution (`SimulatedExchange.config.limits`) | Factory (seeds from spec) | D-13: seeded at construction from spec tickers; `update_config` re-derives by replacement. |
| Runtime config swap | Each handler/manager (owns its config model) | — | D-09: uniform contract, per-handler internals; atomic-swap is the thread-safety primitive (D-11). |
| Reporting (metrics printout) | `reporting/` | — | D-14/W4-07: lifted out of the composition root; pure builders already live in `reporting/`. |
| Determinism seed | `config` singleton (`performance.rng_seed`) | execution (reads it) | D-16: one run-wide setting; `ExecutionHandler` reads the singleton, never re-constructs `SystemConfig`. |

## Standard Stack

No new libraries. Every tool needed is already in the codebase.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | ^2.13 [CITED: pyproject.toml:28] | `model_dump()` / `model_validate()` / `ConfigDict(extra="forbid")` for `OrderConfig` + all config-model handlers | Already the project's config convention (`ExchangeConfig`, `PortfolioConfig`); `OrderConfig` follows it verbatim. |
| stdlib `typing.Protocol` | Python 3.13 | `CommissionEstimator` Protocol in `core/` (D-15) | Mirrors the existing `PortfolioReadModel` `runtime_checkable` Protocol pattern exactly. |
| stdlib `queue.Queue` | Python 3.13 | The single `global_queue` (unchanged) | In-house event-driven core; composition only re-wires it, never changes it. |

**Installation:** None. All dependencies present.

**Version verification:** pydantic pinned `^2.13` in `pyproject.toml` [CITED: pyproject.toml:28]; `pydantic-settings ^2.14` [CITED: pyproject.toml:29]. No registry lookup needed — no new package is added by this phase.

## Package Legitimacy Audit

**Not applicable** — this phase installs zero external packages. All work uses libraries already present in `poetry.lock`. slopcheck/registry verification is unnecessary because no `npm install` / `pip install` / `cargo add` occurs.

## Architecture Patterns

### System Architecture Diagram

```
                         build_backtest_system(spec: SystemSpec)         [FACTORY — mode-specific]
                                        |
                  +---------------------+----------------------+
                  |                                            |
        select mode-specific concretes               compose_engine(spec, order_storage=...)   [SHARED SEAM]
        (D-14a):                                              |
          order_storage =                          builds the component graph mode-agnostically:
          OrderStorageFactory.create('backtest')     queue, clock, store, feed, strategies_handler,
                  |                                    screeners_handler, portfolio_handler,
                  |                                    execution_handler(ExchangeConfig from spec),
                  |                                    CommissionEstimator adapter (holds exchange ref),
                  |                                    order_handler(OrderConfig, commission_estimator),
                  |                                    event_handler
                  |                                            |
                  +------------------+-------------------------+
                                     |
                          BacktestRunner(engine, ...)          [DRIVER — mode-specific, NOT shared]
                                     |  sync for-loop over TimeGenerator
                                     |  per tick: clock.set_time -> queue.put(time_event)
                                     |            -> event_handler.process_events()
                                     |            -> portfolio.record_metrics(time)  [ORDER-SENSITIVE]
                                     |            -> on_tick hook (e2e only)
                                     v
                          BacktestTradingSystem(engine, runner)   [THIN HOLDER]
                                     |  .run(print_summary) delegates to runner,
                                     |   then reporting.print_metrics_summary(...)  [LIFTED OUT — W4-07]
                                     v
                              (post-run read-models: signal_store, portfolios)
```

The diagram traces the primary backtest use case: `spec` enters the factory, the factory selects mode-specific backends and calls the shared `compose_engine`, the runner drives the loop, the holder exposes `run()`. Live mode (fast-follow, NOT this phase) reuses `compose_engine` with a different factory + a threaded driver.

### Recommended Project Structure
```
itrader/trading_system/
├── system_spec.py          # NEW: frozen SystemSpec (+ PortfolioSpec/StrategySpec) — D-01/D-02
├── compose.py              # NEW: compose_engine(spec, order_storage, ...) shared seam — D-14/D-14a
├── backtest_runner.py      # NEW: BacktestRunner (sync for-loop, fail-fast) — D-14
├── backtest_trading_system.py  # SLIMMED: BacktestTradingSystem thin holder + build_backtest_system factory — D-03/D-04
└── simulation/time_generator.py  # unchanged
itrader/core/
└── commission_estimator.py  # NEW: CommissionEstimator Protocol — D-15 (mirrors portfolio_read_model.py)
itrader/config/
└── order.py                # NEW: OrderConfig (Pydantic, extra="forbid") — D-05
itrader/execution_handler/
└── (adapter home — Claude's discretion: compose.py or an execution-adapter module) FeeModelCommissionEstimator — D-15
itrader/reporting/
└── (metrics printout home) print_metrics_summary(...) — W4-07/D-14 (pure builders already here)
```
*Exact module homes for the new `trading_system/` files and the adapter are within the planner's discretion (CONTEXT.md). The structure above is one byte-exact-compatible layout.*

### Pattern 1: Canonical `update_config` body (config-model handlers)
**What:** deep-merge the partial update onto the dumped model, re-validate, atomic-swap, wrap pydantic errors.
**When to use:** `PortfolioHandler`, `Portfolio`, `SimulatedExchange`, `ExecutionHandler`, `OrderManager`/`OrderHandler` (via `OrderConfig`).
**Example:**
```python
# Source: CONTEXT.md §specifics (locked preview) + itrader/core/exceptions/base.py:28 (ConfigurationError)
def update_config(self, updates: dict[str, Any]) -> None:
    merged = deep_merge(self.config.model_dump(), updates)
    try:
        new = SomeConfig.model_validate(merged)   # extra="forbid" catches unknown keys
    except pydantic.ValidationError as e:
        raise ConfigurationError(reason=str(e)) from e
    self.config = new                              # atomic swap (GIL-atomic reference assign)
    # then re-derive any cached internals from new (e.g. SimulatedExchange size caches / fee model)
```

### Pattern 2: `StrategiesHandler.update_config` (non-config-model internals)
**What:** re-apply params → `validate()` → re-run `init()` → re-derive warmup. Consumes Phase 2's `reconfigure(**kwargs)` (idempotent `init()`) + Phase 3's auto-warmup.
**When to use:** `StrategiesHandler` only (D-09 explicitly forbids inventing a `StrategiesHandlerConfig`).
**Example:**
```python
# Source: itrader/strategy_handler/base.py:323-341 (reconfigure -> _apply_params -> validate -> _run_init)
# StrategiesHandler.update_config delegates per-strategy to strategy.reconfigure(**kwargs);
# _run_init() resets handles, re-runs init(), and re-derives warmup/max_window (base.py:256-289).
```
Note: the dict→**kwargs translation at the handler boundary is the planner's call (Claude's discretion). The per-strategy seam (`reconfigure`) already exists and is idempotent — `StrategiesHandler.update_config` is new, but the heavy lifting is pre-built.

### Pattern 3: `CommissionEstimator` Protocol + late-binding adapter (D-15)
**What:** A `core/` Protocol with primitive signature; a concrete adapter holding the exchange ref (NOT the fee_model) reading `fee_model` at call time.
**Why late binding matters:** `_estimate_commission` today reads `simulated_exchange.fee_model` at CALL time (`backtest_trading_system.py:124-128`); `SimulatedExchange.update_config` may rebuild `self.fee_model` (`simulated.py:656`). The adapter MUST hold the exchange ref and dereference `exchange.fee_model` in `__call__`, never capture `fee_model` at construction — otherwise a fee-model reconfigure would silently use a stale estimator.
**Example:**
```python
# Source: itrader/core/portfolio_read_model.py (Protocol pattern) + backtest_trading_system.py:124-128 (current closure)
# core/commission_estimator.py
@runtime_checkable
class CommissionEstimator(Protocol):
    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal: ...

# execution adapter (home = Claude's discretion)
class FeeModelCommissionEstimator:
    def __init__(self, exchange: SimulatedExchange) -> None:
        self._exchange = exchange                 # hold the REF (late binding)
    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
        return self._exchange.fee_model.calculate_fee(
            quantity, price, side="buy", order_type="market")  # D-04 admission convention preserved
```
**Byte-exact note:** `OrderManager.commission_estimator` is currently typed `Optional[Callable[[Decimal, Decimal], Decimal]]` (`order_manager.py:50`). Retyping to `Optional[CommissionEstimator]` is a pure typing change — `FeeModelCommissionEstimator` is callable with the identical signature, and the golden run pins fees 0 (`ZeroFeeModel`), so the estimate is `Decimal("0")` exactly as today.

### Anti-Patterns to Avoid
- **Capturing `fee_model` in the commission adapter constructor** — breaks late binding (Pattern 3). Hold the exchange ref.
- **Re-deriving `_supported_symbols` from `config.limits` by replacement at construction without first folding the full set into `config.limits`** — this is the PATTERNS-A2 trap (see Byte-Exact Trap Map). The current `register_symbol('BTCUSD')` is additive (union); the new construction-time seeding must put the COMPLETE set (default ∪ BTCUSD ∪ spec tickers) into `ExchangeConfig.limits.supported_symbols` BEFORE construction reads it.
- **Hardcoding `'backtest'` inside `compose_engine`** — violates D-14a; the factory selects backends.
- **Re-running `record_metrics` at a different point in the loop, or routing it through an event** — W4-02 keeps it a direct post-`process_events` call (`backtest_trading_system.py:220-221`). Any reorder breaks the equity curve byte-exactly.
- **Inventing a `FeedConfig`/`StrategiesHandlerConfig` to force literal `model_validate` everywhere** — D-09 explicitly forbids this.
- **Normalizing indentation** — handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, events package use 4 spaces (CLAUDE.md). New files: match the package they live in (`core/commission_estimator.py` and `config/order.py` = 4 spaces; `trading_system/` files currently use tabs — match `backtest_trading_system.py`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Deep-merge of partial nested config updates | A fresh recursive merge per handler | The existing `PortfolioHandler._deep_merge` (`portfolio_handler.py:437-454`) lifted to a shared helper | Already handles the shallow-merge footgun (WR-04): a partial `{"limits": {...}}` must preserve sibling fields, not replace the whole submodel. Promote it, don't re-derive. |
| Config validation + unknown-key rejection | Manual `hasattr`/`setattr` poking (the current `Portfolio`/`SimulatedExchange` `config_mapping` style) | `Model.model_validate(merged)` with `ConfigDict(extra="forbid")` | Pydantic already rejects unknown keys via `extra="forbid"` and coerces types; the `config_mapping` dicts (`portfolio.py:166-178`, `simulated.py:625-640`) are exactly what D-07/D-09 replace. |
| Thread-safety for the swap | A new lock around config reads | Atomic reference assignment (`self.config = new`) under the GIL (D-11) | A fully-built validated object swapped in one assignment is atomic; existing per-handler `RLock`s (live) + single-writer backtest contract cover the rest. No new locking machinery. |
| Error→HTTP mapping surface | A new exception type | `core.ConfigurationError` wrapping pydantic `ValidationError` (D-08) | One iTrader type the future web layer catches → HTTP 4xx; `ConfigurationError` already carries `config_key`/`config_value`/`reason` (`base.py:28-42`). |
| Cross-domain commission read | An import of `execution_handler` into `order_manager` | The injected `CommissionEstimator` Protocol (D-15) | Mirrors `PortfolioReadModel` — keeps `order_manager` execution-import-free; the Protocol's primitive `(Decimal, Decimal) -> Decimal` signature has zero `itrader` deps (core's dependency rule). |
| Metrics printout | A new formatter | The existing `reporting.frames` + `reporting.metrics` builders the printout already calls (`backtest_trading_system.py:285-309`) | W4-07 is pure code-motion: move `_print_metrics_summary` into `reporting/`; the formula source is already there (one source the oracle also serializes). |

**Key insight:** Almost nothing in this phase is genuinely new code. `PortfolioHandler` already does deep-merge + `model_validate` (the canonical template, `portfolio_handler.py:456-469`); the strategy `reconfigure`/`init`/warmup seam already exists (Phase 2/3); the commission closure already late-binds. The work is **standardizing 3 inconsistent forms onto 1 contract** and **moving wiring into seams** — not invention.

## Runtime State Inventory

> This phase is a **structural refactor + rename** (`TradingSystem` → `BacktestTradingSystem`). The rename is a Python-symbol rename, not a stored-string rename, so the OS/datastore categories are mostly empty — but they were checked explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — `TradingSystem` is a Python class name, not stored as a key/collection/user_id in any datastore. The backtest uses in-memory order storage (`OrderStorageFactory.create('backtest')`) and a `CsvPriceStore`; nothing persists the class name. Verified: no DB writes the string. | None |
| Live service config | **None** — backtest has no external service config. The e2e/oracle paths construct fresh in-process; no n8n/Datadog/scheduler holds the name. | None |
| OS-registered state | **None** — no Task Scheduler / launchd / systemd / pm2 registration references `TradingSystem`. Verified: no OS-level artifact. | None |
| Secrets/env vars | **None** — the rename touches no env var name. `ITRADER_`-prefixed settings (pydantic-settings) and `performance.rng_seed` are config keys, unchanged by this phase. D-16 reads `config.performance.rng_seed` (existing key, value unchanged at 42). | None |
| Build artifacts / import sites | **Import sites only** — `from itrader.trading_system.backtest_trading_system import TradingSystem` appears in: `scripts/run_backtest.py:47`, `tests/integration/test_backtest_oracle.py:249`, `tests/integration/conftest.py`, `tests/integration/test_universe_spans.py`, `tests/integration/test_reservation_inertness.py`, `tests/integration/test_backtest_smoke.py`, `tests/e2e/conftest.py:295` (deferred import). | Update every import site to `BacktestTradingSystem` / `build_backtest_system`. No egg-info/compiled-artifact concern (pure source rename; `mypy --strict` + the suite catch a missed site). |

**The canonical question** — *after every file is updated, what runtime systems still have the old string cached/stored/registered?* — answer: **nothing**. This is a pure in-process Python rename. The only "runtime state" is the import graph, fully covered by updating the import sites and re-running `mypy --strict` + the test suite.

## Byte-Exact Trap Map

The locked decisions name several byte-exact traps. This is the consolidated execution-risk map — the single most load-bearing section for the planner.

### Trap 1 — Symbol set: replacement vs union (PATTERNS-A2, D-13) — HIGHEST RISK
**Current reality (3 layers stack to the byte-exact set):**
1. `SimulatedExchange.__init__` seeds `_supported_symbols = config.limits.supported_symbols` — the default preset = `{BTCUSDT, ETHUSDT, ADAUSDT, DOTUSDT, SOLUSDT}` (`exchange.py:182`, `simulated.py:98`).
2. `ExecutionHandler.init_exchanges` then **additively** `register_symbol('BTCUSD')` (union — `execution_handler.py:111`).
3. The e2e conftest then **additively** `register_symbol(ticker.upper())` for each spec ticker (`conftest.py:347-349`).
**The trap:** `update_config` re-derives `_supported_symbols` from `config.limits` by **REPLACEMENT** (`simulated.py:664-665`). If you seed the exchange from a spec-derived `ExchangeConfig.limits` that omits `BTCUSD` (the default preset omits it!), and rely on a later additive `register_symbol`, then ANY subsequent `update_config(limits=...)` wipes BTCUSD and silently REFUSEs every order.
**The fix (D-13):** Construction must fold the COMPLETE set — `default preset symbols ∪ {BTCUSD} ∪ spec tickers (upper-cased)` — into `ExchangeConfig.limits.supported_symbols` BEFORE `SimulatedExchange` reads it. Then remove the hardcoded `register_symbol('BTCUSD')` (`execution_handler.py:111`) AND the conftest loop (`conftest.py:347-349`). Byte-exact assertion: the final `_supported_symbols` must equal today's union.
**Subtle point:** the oracle path (`scripts/run_backtest.py`) trades `BTCUSD` but constructs WITHOUT a spec today — the factory's `csv_paths`-keys-derive-tickers logic (D-13) must produce `{BTCUSD}` for the oracle, and the seeding must still union the default preset symbols so existing e2e leaves (ETHUSDT etc.) stay admitted. **Verify the oracle's derived set == `{BTCUSD} ∪ default preset` exactly.**

### Trap 2 — Commission estimator late binding (D-15)
The adapter must dereference `exchange.fee_model` in `__call__`, not capture it at construction. The golden run pins fees 0 (`ZeroFeeModel` default), so the estimate is `Decimal("0")` and the reservation = price × quantity exactly. A construction-time `fee_model` capture would still be byte-exact *for the golden run* (fees stay 0) but would silently break `update_config`-driven fee changes — a latent correctness defect the unit tests must catch. Retyping `OrderManager.commission_estimator: Callable → CommissionEstimator` is pure structure/typing (mypy-only impact).

### Trap 3 — rng_seed dedup (D-16)
`ExecutionHandler._resolve_rng_seed()` currently constructs a **2nd** `SystemConfig.default()` (`execution_handler.py:54-62`). D-16: read `from itrader import config; config.performance.rng_seed` instead. The value is 42 either way (the singleton and a fresh `.default()` both yield 42 unless a YAML override exists — and the YAML override, if present, would apply to BOTH, so the singleton read is byte-identical or strictly more correct). Seed stays 42 → the single shared `random.Random(42)` is unchanged → determinism holds.

### Trap 4 — Ordering preservation in the extracted runner (D-14/W4-02)
The run loop's per-tick order is byte-exact-sensitive (`backtest_trading_system.py:211-225`):
`clock.set_time(time)` → `queue.put(time_event)` → `event_handler.process_events()` → `for portfolio: portfolio.record_metrics(time)` → `on_tick` hook. `record_metrics` stays a **direct post-`process_events` call** (NOT an event reroute). When extracting `BacktestRunner`, preserve this exact sequence and the `for portfolio in get_active_portfolios()` iteration order. Also preserve `_initialise_backtest_session` ordering (`backtest_trading_system.py:152-190`): membership derive → `feed.bind` → ping-grid `reduce(Index.union)` → `time_generator.set_dates` → `feed.precompute` per strategy. The `feed.precompute` loop iterates `self.strategies_handler.strategies` in registration order — preserve it (W4-03 is a tidy, not a reorder).

### Trap 5 — `OrderConfig` coercion equivalence (D-05)
`OrderManager.__init__` currently coerces `MarketExecution(market_execution)` at the ctor boundary (`order_manager.py:86`) — a str→enum parse that's a no-op on an existing member. Folding this into `OrderConfig.market_execution: MarketExecution` must preserve the stored value byte-identically: the default `"immediate"`/`"next_bar"` literal must map to the same enum member. `MarketExecution` is a plain `Enum` (not `str, Enum`) with a case-insensitive `_missing_` (`order.py:144-170`) — Pydantic v2 validates `Enum` fields by value; confirm `OrderConfig.model_validate({"market_execution": "immediate"})` yields `MarketExecution.IMMEDIATE`. **Default-equivalence check:** the backtest path uses `market_execution="immediate"` by default (`order_handler.py:41`); the new `OrderConfig` default must reproduce this.

### Trap 6 — `record_metrics` / get_active_portfolios iteration determinism
Multi-portfolio specs exist in the e2e suite. The metrics-recording loop and the post-run portfolio reads must iterate in the same order as today. `get_active_portfolios()` order is dict-insertion order (Python 3.7+ guarantee); the factory must `add_portfolio` in spec order to preserve it. Verify against the multi-portfolio e2e leaves.

## Common Pitfalls

### Pitfall 1: Migrating the 3 existing `update_config` forms loses behavior
**What goes wrong:** The 3 existing implementations have DIFFERENT side effects beyond the swap that a naive "standardize the signature" misses.
**The 3 forms (verified):**
- `PortfolioHandler.update_config(Dict) -> bool` (`portfolio_handler.py:456`) — already deep-merge + `model_validate`; ALSO re-derives `self.max_portfolios = config.limits.max_portfolios` (`:464`). Returns `bool` (must become `None` + raise — D-07/D-08). The closest template.
- `Portfolio.update_config(**kwargs) -> None` (`portfolio.py:163`) — `config_mapping` `setattr` pokes; raises `ConfigurationError` on unknown key (`:189`). Migrate to dict + `model_validate`.
- `SimulatedExchange.update_config(**kwargs) -> None` (`simulated.py:622`) — `config_mapping` pokes; ALSO re-inits `fee_model`/`slippage_model`/`simulate_failures`/`failure_rate` and re-derives `_supported_symbols`/`_min_order_size`/`_max_order_size` size caches (`:654-672`); raises bare `ValueError` (must become `ConfigurationError` — D-08). The `configure(config) -> bool` Protocol method (`:606`) catches `ValueError` — it must be updated to catch `ConfigurationError` after migration.
**How to avoid:** For each handler, enumerate its post-swap re-derivations and reproduce them after `self.config = new`. The size-cache re-derivation in `SimulatedExchange` is the same code the e2e harness inlines (`conftest.py:332-333`) — that inline goes away (D-13/D-14 collapse) and is replaced by the real `update_config`.
**Warning signs:** A unit test that swaps config but reads a stale cached attribute (`max_portfolios`, `_min_order_size`, `fee_model`).

### Pitfall 2: `SimulatedExchange.configure()` Protocol method breaks on error-contract change
**What goes wrong:** `configure(config) -> bool` (`simulated.py:606`) delegates to `update_config(**config)` and catches `ValueError`. After D-08 migrates `update_config` to raise `ConfigurationError`, the `except ValueError` no longer catches → `configure` propagates instead of returning `False`.
**How to avoid:** Update `configure`'s `except ValueError` → `except ConfigurationError`. Also: `configure` calls `update_config(**config)` (kwargs) but the new signature is `update_config(dict)` — `configure` must call `update_config(config)`. Check the `AbstractExchange` Protocol's `configure` signature stays satisfied.
**Warning signs:** `test_simulated_exchange.py` (which has update_config tests) failing on signature/exception mismatch.

### Pitfall 3: `BacktestBarFeed.update_config` must raise, not silently no-op
**What goes wrong:** D-10 says `BacktestBarFeed.update_config` is interface-conformance that RAISES `ConfigurationError` for unsafe hot-swaps (notably `base_timeframe` — `bar_feed.py:145` `_base_timeframe` ripples into `_base_alias` and the window cutoff math at `:364`). A no-op implementation would silently accept a change it can't honor.
**How to avoid:** Implement `update_config` to raise `ConfigurationError(config_key="base_timeframe", reason="cannot hot-swap base_timeframe in backtest — replace the feed")` for the unsafe keys. The feed has NO Pydantic config model today (verified: no `update_config`/`reconfigure`/config attr on `bar_feed.py`) — D-09/D-10 explicitly do NOT require inventing a `FeedConfig`. The method exists purely to satisfy the uniform interface and fail loudly.
**Warning signs:** A test that calls `feed.update_config({"base_timeframe": ...})` and expects a raise but gets silent acceptance.

### Pitfall 4: `ExecutionHandler` currently takes no `ExchangeConfig`
**What goes wrong:** `ExecutionHandler(global_queue)` constructs `SimulatedExchange(queue, rng=...)` with the DEFAULT preset (`execution_handler.py:104`) — there is NO config threading today (both backtest and live call `ExecutionHandler(self.global_queue)`). COMP-01's "construction-time `ExchangeConfig` threading (`TradingSystem` → `ExecutionHandler` → `SimulatedExchange`)" is a genuine new parameter path, not a rewire of an existing one.
**How to avoid:** Add an optional `ExchangeConfig` param to `ExecutionHandler.__init__` (and `init_exchanges`), threaded from the spec via `compose_engine`. Default-None must reproduce the current default-preset behavior byte-exactly for any non-spec construction site. The symbol-set seeding (Trap 1) rides this path.
**Warning signs:** `test_execution_handler.py` / `test_execution_handler_routing.py` constructing `ExecutionHandler(queue)` and breaking on a required-config signature change — keep the config optional.

### Pitfall 5: e2e harness `_build_and_run` collapse drops the D-14 re-init seam AND the size-cache inline
**What goes wrong:** `conftest.py:_build_and_run` (`:287-398`) does THREE post-construction things the collapse onto `build_backtest_system(spec)` must reproduce inside the factory/`update_config`: (a) the fee/slippage re-init seam (`:316-333`, applied when `spec.exchange is not None`), (b) the size-cache re-derivation (`:332-333`), (c) the `register_symbol` loop (`:347-349`). After the collapse, (a)+(b) are subsumed by constructing the exchange with the spec's `ExchangeConfig` at `compose_engine` time (no post-construction re-init needed), and (c) by Trap 1's construction-time seeding.
**How to avoid:** Verify the spec's `ExchangeConfig` (when non-None) is passed to `compose_engine` → `ExecutionHandler` → `SimulatedExchange.__init__` so the fee/slippage models and size caches derive from it at construction — making the post-construction re-init seam unnecessary. The `_build_and_run` body shrinks to: `system = build_backtest_system(spec); system.run(on_tick=...)`.
**Warning signs:** Any e2e leaf with a non-None `spec.exchange` (fee/slippage/limits scenarios — Phase 7/8 leaves) diffing after the collapse. These are the leaves most at risk.

## Code Examples

### Existing deep-merge to promote (the canonical helper)
```python
# Source: itrader/portfolio_handler/portfolio_handler.py:437-454 (VERIFIED in codebase)
@staticmethod
def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = PortfolioHandler._deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
```

### Existing closure to replace (the commission late-binding)
```python
# Source: itrader/trading_system/backtest_trading_system.py:124-128 (VERIFIED)
simulated_exchange = self.execution_handler.exchanges.get('simulated')
def _estimate_commission(quantity: Decimal, price: Decimal) -> Decimal:
    if not isinstance(simulated_exchange, SimulatedExchange):
        return Decimal("0")
    return simulated_exchange.fee_model.calculate_fee(
        quantity, price, side="buy", order_type="market")
```

### Existing OrderConfig template (Pydantic convention to follow)
```python
# Source: itrader/config/exchange.py:136-149 (VERIFIED — the extra="forbid" + default() convention)
class ExchangeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange_type: ExchangeVenue = ExchangeVenue.SIMULATED
    # ... nested sub-models via Field(default_factory=...)
    @classmethod
    def default(cls) -> "ExchangeConfig":
        return get_exchange_preset("default")
```

## State of the Art

No external state-of-the-art shift applies — this is an internal refactor on a pinned, stable stack (pydantic ^2.13, Python 3.13). The only "old → new" is internal:

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fat `TradingSystem.__init__` wiring + post-construction `add_strategy`/`add_portfolio` | `SystemSpec` + `build_backtest_system(spec)` + `compose_engine` + `BacktestRunner` + thin holder | This phase (D-01/D-04/D-14) | Declarative, serializable, live-reusable wiring; e2e harness collapses. |
| 3 inconsistent `update_config` (`Dict→bool`, 2× `**kwargs→None`) | 1 uniform `update_config(dict) -> None` raising `ConfigurationError` | This phase (D-07/D-08) | Single web-catchable contract. |
| Inline `_estimate_commission` closure (`Callable`) | `CommissionEstimator` Protocol + `FeeModelCommissionEstimator` adapter | This phase (D-15) | Typed read-model seam, mirrors `PortfolioReadModel`. |
| `ExecutionHandler._resolve_rng_seed()` builds 2nd `SystemConfig` | Read `config.performance.rng_seed` from the singleton | This phase (D-16) | Removes duplicate config construction. |
| Hardcoded `register_symbol('BTCUSD')` + conftest re-init seam | Spec-driven construction-time `supported_symbols` seeding | This phase (D-13) | Removes the post-construction admission hack. |

**Deprecated/outdated:** `pydantic-settings` `Settings(BaseSettings)` env layer is NOT touched this phase (it's the `ITRADER_`-prefix layer, orthogonal to `OrderConfig`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `MarketExecution` (a plain `Enum`, not `str, Enum`) validates cleanly under pydantic v2 `model_validate` from its string `.value` ("immediate"/"next_bar"). | Trap 5 / D-05 | LOW — if pydantic v2 needs `use_enum_values` or a validator for a non-`str` Enum, `OrderConfig` must add it; the planner must include a unit test `OrderConfig.model_validate({"market_execution": "immediate"}).market_execution is MarketExecution.IMMEDIATE`. Verifiable in one test, not a design risk. |
| A2 | The e2e suite is 58 leaves and the oracle assertion is exactly 134 trades / `final_equity 46189.87730727451`. | Validation Architecture | LOW — stated verbatim in CONTEXT.md/ROADMAP as the locked gate; the oracle test file references the numbers. Re-confirm the live count with `make test-e2e` before the gate. |
| A3 | Reading `config.performance.rng_seed` from the singleton yields the same value (42) as `SystemConfig.default().performance.rng_seed` in all paths (including any YAML override). | Trap 3 / D-16 | LOW — a `settings/system.yaml` override would apply to BOTH the singleton and a fresh `.default()` (same construction). If an override exists and differs, the singleton read is the MORE correct one (single source). No golden-run override is present (seed 42 holds). |
| A4 | No external/OS/datastore state references the string "TradingSystem" (rename is in-process only). | Runtime State Inventory | LOW — verified by grep across the repo; backtest has no persistence of the class name. A missed import site is caught by `mypy --strict` + the suite. |

## Open Questions (RESOLVED)

1. **Does any e2e leaf with `spec.exchange is not None` rely on the EXACT post-construction re-init ordering that the collapse removes?**
   - What we know: `_build_and_run` re-inits fee/slippage models + size caches AFTER construction (`conftest.py:316-333`); the collapse moves this to construction-time via `compose_engine`.
   - What's unclear: whether constructing the exchange with the spec config (vs. default-then-reassign) produces a byte-identical fee/slippage/limits state for every Phase-7/8 leaf.
   - **RESOLVED:** Plan 04-05 Task 2 is the isolation point — the full e2e suite (`make test-e2e`, 58/58) runs against the collapsed `build_backtest_system(spec)` construction-time config threading, BEFORE no `update_config` fires in the golden run. Any fee/slippage/limits divergence from the default-then-reassign → construct-with-spec change surfaces there and only there. The byte-exact gate (oracle 134 / `46189.87730727451`) is the decisive check; if a leaf diverges, the construction-time `ExchangeConfig` threading (04-02) is the sole suspect.

2. **Where does `csv_paths`-keys → tickers derivation live (spec field vs factory)?** (Claude's discretion, D-13.)
   - What we know: today `csv_paths` passes straight to `CsvPriceStore` (`backtest_trading_system.py:92-95`); the e2e harness derives tickers from `spec.data` keys (`conftest.py:348`).
   - **RESOLVED:** Derive in the **FACTORY** (`build_backtest_system`), per Plan 04-02 Task 2/3: the symbol set = `spec.data`/`csv_paths` keys (upper-cased) ∪ default-preset symbols ∪ `{BTCUSD}` (oracle path), folded into `ExchangeConfig.limits.supported_symbols` and passed into `compose_engine` already-seeded. Keeps `compose_engine` mode-agnostic (D-14a) and the spec serializable. `compose_engine` never derives symbols itself.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | 3.13 (pinned `>=3.13,<3.14`) | — |
| Poetry / `.venv` | Tests + mypy | ✓ | in-project `.venv` | — |
| pydantic | OrderConfig + config handlers | ✓ | ^2.13 | — |
| pytest (+ pytest-cov/html) | Validation | ✓ | ^8.4.2 | — |
| mypy | `mypy --strict` gate | ✓ | ^2.1.0 | — |
| backtesting.py / backtrader | Cross-validation oracles | ✓ (present) | 0.6.5 / 1.9.78 | NOT needed this phase — byte-exact, no re-baseline (cross-validation is for owner-gated Phases 5-6) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None. This is a code-only phase on a fully-provisioned environment.

> **Worktree note (from user memory):** if working in a git worktree, the editable `.venv` install can shadow worktree edits from pytest/mypy — prepend `PYTHONPATH="$PWD"` to test/mypy invocations.

## Validation Architecture

> `workflow.nyquist_validation: true` [CITED: .planning/config.json] — this section is REQUIRED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `--strict-config`, `filterwarnings=["error", ...]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/<domain> -x` (e.g. `tests/unit/execution`, `tests/unit/order`, `tests/unit/portfolio`) |
| Full suite command | `make test` (unit + integration + e2e) |
| Byte-exact gate | `make test-e2e` (58/58) + `poetry run pytest tests/integration/test_backtest_oracle.py` (134 trades / `final_equity 46189.87730727451`) + `mypy --strict` (`poetry run mypy itrader`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COMP-01 | `build_backtest_system(spec)` wires a byte-exact system | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (oracle exists; add a build-via-spec construction path) |
| COMP-01 | Rename `TradingSystem`→`BacktestTradingSystem`; all import sites updated | static | `poetry run mypy itrader && poetry run pytest tests -x` | ✅ (suite catches missed sites) |
| COMP-01 | Construction-time `ExchangeConfig` threading + symbol seeding == today's set (Trap 1) | integration | `poetry run pytest tests/integration/test_universe_spans.py tests/integration/test_backtest_smoke.py -x` | ✅ (universe_spans does the same symbol mutation; assert final `_supported_symbols`) |
| COMP-01 | `OrderConfig` coercion equivalence (Trap 5) | unit | `poetry run pytest tests/unit/order -x` | ❌ Wave 0 — `tests/unit/config/test_order_config.py` |
| COMP-01 | `CommissionEstimator` late binding (fee-model rebuild → fresh estimate) | unit | `poetry run pytest tests/unit/order tests/unit/execution -x` | ❌ Wave 0 — `tests/unit/core/test_commission_estimator.py` (or order) |
| COMP-01 | `rng_seed` read from singleton == 42; determinism double-run identical | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` (double-run) | ✅ (determinism double-run exists in the oracle/gate plans) |
| COMP-01 | e2e `_build_and_run` collapse byte-exact (incl. non-None `spec.exchange` leaves) | e2e | `make test-e2e` | ✅ (58 leaves) |
| COMP-02 | `update_config` canonical contract: valid update swaps config | unit | per-handler | ⚠️ extend — `PortfolioHandler`/`Portfolio`/`SimulatedExchange` have some tests; add the new contract |
| COMP-02 | `update_config` raises `ConfigurationError` on unknown key (`extra="forbid"`) | unit | per-handler | ❌ Wave 0 — one test per migrated handler |
| COMP-02 | `update_config` raises `ConfigurationError` wrapping pydantic `ValidationError` on bad value | unit | per-handler | ❌ Wave 0 |
| COMP-02 | `update_config` deep-merge preserves sibling submodel fields (WR-04) | unit | `tests/unit/portfolio` + new | ⚠️ template exists in PortfolioHandler tests |
| COMP-02 | `update_config` re-derives cached internals (max_portfolios / size caches / fee_model) | unit | `tests/unit/execution`, `tests/unit/portfolio` | ⚠️ extend `test_simulated_exchange.py` |
| COMP-02 | `StrategiesHandler.update_config` re-runs init() + re-derives warmup | unit | `tests/unit/strategy` | ❌ Wave 0 — `tests/unit/strategy/test_strategies_handler_update_config.py` |
| COMP-02 | `BacktestBarFeed.update_config` raises on unsafe hot-swap (`base_timeframe`) | unit | `tests/unit/price_handler` (or feed) | ❌ Wave 0 |
| COMP-02 | `SimulatedExchange.configure()` Protocol method still works after error-contract change (Pitfall 2) | unit | `tests/unit/execution` | ⚠️ update existing `configure` test (catch `ConfigurationError`, pass dict) |

### Sampling Rate
- **Per task commit:** the domain-scoped quick run for the file touched (e.g. `make test-execution`, `make test-portfolio`, `make test-order`, `make test-strategy`) + `poetry run mypy itrader`.
- **Per wave merge:** `make test` (full unit+integration+e2e) + the oracle byte-exact assertion.
- **Phase gate:** `make test-e2e` (58/58) + oracle (134 / `46189.87730727451`) + `mypy --strict` clean + determinism double-run byte-identical — all green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/config/test_order_config.py` — `OrderConfig` `extra="forbid"`, `MarketExecution` coercion equivalence (Trap 5 / A1)
- [ ] `tests/unit/core/test_commission_estimator.py` — Protocol conformance + `FeeModelCommissionEstimator` late binding (fee-model rebuild yields fresh estimate)
- [ ] `tests/unit/strategy/test_strategies_handler_update_config.py` — re-validate → re-run `init()` → re-derive warmup (consumes Phase 2/3 seams)
- [ ] `tests/unit/.../test_bar_feed_update_config.py` — raises `ConfigurationError` on `base_timeframe` (D-10 interface-conformance)
- [ ] Per-handler `update_config` contract tests (unknown-key raise, bad-value wrap, deep-merge sibling preserve, cached-internal re-derive) for OrderHandler/OrderManager, ExecutionHandler — extend existing PortfolioHandler/Portfolio/SimulatedExchange tests onto the canonical `dict→None→ConfigurationError` contract
- [ ] Update `SimulatedExchange.configure()` test: pass a dict, catch `ConfigurationError` (Pitfall 2)
- [ ] Integration: assert final `_supported_symbols` == `{BTCUSD} ∪ default-preset ∪ spec-tickers` after `build_backtest_system` (Trap 1)
- [ ] Framework install: none needed (pytest present)

## Security Domain

`security_enforcement` is not set to a value in `.planning/config.json` (only `workflow.nyquist_validation` was found); treating as enabled per the absent-means-enabled rule. This phase is an **internal backtest-engine refactor with no external input surface, no auth, no network, no untrusted data** — the input boundary is developer-authored `SystemSpec`/config dicts and a committed golden CSV. The applicable ASVS surface is minimal.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface (backtest engine). |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | No multi-user boundary this phase. |
| V5 Input Validation | yes | `OrderConfig` + all `update_config` paths use `pydantic.model_validate` with `ConfigDict(extra="forbid")` — unknown keys rejected, types coerced/validated. This IS the input-validation control. |
| V6 Cryptography | no | No crypto (the determinism RNG is `random.Random`, NOT a security primitive — never treat `rng_seed` as a secret). |

### Known Threat Patterns for {Python config-dict ingestion}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mass-assignment via unexpected config keys | Tampering | `ConfigDict(extra="forbid")` on every config model (already the convention) — `update_config` rejects unknown keys (D-08). |
| Silent type confusion in a partial update | Tampering | `model_validate(merged)` coerces/validates the full merged object; deep-merge preserves siblings (WR-04). |
| Stale-estimator after fee-model swap (correctness, not classic security) | Tampering (integrity of cost accounting) | `CommissionEstimator` late binding (D-15) — adapter reads `exchange.fee_model` at call time. |

> Note: the known FL-06 SQL-injection + hardcoded-creds defect in `SqlHandler` is **explicitly out of scope** (REQUIREMENTS.md "Out of Scope" → 999.2); the module is quarantined off the backtest run path. Do NOT touch it this phase.

## Sources

### Primary (HIGH confidence)
- **Codebase (read directly, line-referenced throughout):** `itrader/trading_system/backtest_trading_system.py`, `itrader/execution_handler/execution_handler.py`, `itrader/execution_handler/exchanges/simulated.py`, `itrader/portfolio_handler/portfolio_handler.py`, `itrader/portfolio_handler/portfolio.py`, `itrader/order_handler/order_manager.py`, `itrader/order_handler/order_handler.py`, `itrader/core/portfolio_read_model.py`, `itrader/core/exceptions/base.py`, `itrader/config/exchange.py`, `itrader/core/enums/order.py` (MarketExecution), `itrader/strategy_handler/strategies_handler.py`, `itrader/strategy_handler/base.py`, `tests/e2e/scenario_spec.py`, `tests/e2e/conftest.py`, `scripts/run_backtest.py`, `tests/integration/test_backtest_oracle.py`.
- **CONTEXT.md** (`.planning/phases/04-composition-config-interface/04-CONTEXT.md`) — the 18 locked decisions (authoritative design contract).
- **REQUIREMENTS.md / ROADMAP.md** — COMP-01/COMP-02, byte-exact gate, sequencing.
- **CLAUDE.md** — tabs/spaces hazard, Decimal policy, config-enum exception, queue-only contract, determinism seam.
- **pyproject.toml** — pydantic ^2.13, pytest config, mypy strict.
- **.planning/config.json** — `workflow.nyquist_validation: true`.

### Secondary (MEDIUM confidence)
- None — every claim is verified directly against the codebase or the locked CONTEXT.md.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; pydantic ^2.13 verified in pyproject.toml and already the project convention.
- Architecture: HIGH — design is locked by CONTEXT.md; the current shapes (`__init__`, `run`, `_run_backtest`, 3 update_config forms, commission closure, symbol seeding) are read directly and line-referenced.
- Byte-exact traps: HIGH — each trap is traced to specific verified line numbers (symbol seeding `simulated.py:98/664`, commission `backtest_trading_system.py:124`, rng `execution_handler.py:54`, ordering `:211-225`, MarketExecution `order.py:144`).
- Pitfalls: HIGH — the 3 update_config forms and the `configure()` Protocol coupling are read directly.
- Validation: HIGH — framework + gate verified; Wave 0 gaps enumerated against existing test files.

**Research date:** 2026-06-12
**Valid until:** 2026-07-12 (stable internal stack; refresh only if pydantic majors or the config convention changes)
