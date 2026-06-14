# Phase 4: Composition & Config Interface - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 14 (4 NEW + 10 MODIFY)
**Analogs found:** 14 / 14

## Indentation Law (read before any edit — CLAUDE.md)

| Package | Indentation | New/touched files here |
|---------|-------------|------------------------|
| `itrader/trading_system/` | **TABS** | `system_spec.py`, `compose.py`, `backtest_runner.py`, `backtest_trading_system.py` |
| `itrader/core/` | **4 SPACES** | `commission_estimator.py` |
| `itrader/config/` | **4 SPACES** | `order.py` |
| `itrader/price_handler/feed/` | **4 SPACES** | `bar_feed.py` |
| `itrader/order_handler/` | **TABS** | `order_manager.py`, `order_handler.py` |
| `itrader/execution_handler/` | **TABS** | `execution_handler.py`, `exchanges/simulated.py` |
| `itrader/portfolio_handler/` | **TABS** | `portfolio_handler.py`, `portfolio.py` |
| `itrader/strategy_handler/` | **TABS** | `strategies_handler.py` |
| `tests/` | **4 SPACES** | `scenario_spec.py`, `conftest.py` |

NEVER normalize. A space-vs-tab diff in a tab file breaks the file. New-file rule: match the package the file lives in (per RESEARCH §Anti-Patterns).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/commission_estimator.py` (NEW) | core Protocol (read-model seam) | request-response (read) | `itrader/core/portfolio_read_model.py` | exact (same seam shape) |
| `config/order.py` (NEW) | config model | transform (validate) | `itrader/config/exchange.py` | exact (same Pydantic convention) |
| `trading_system/system_spec.py` (NEW) | spec value object | transform (declarative) | `tests/e2e/scenario_spec.py::ScenarioSpec` | exact (promoted ~verbatim) |
| `trading_system/compose.py` (NEW) | composition/wiring seam | event-driven (wiring) | `backtest_trading_system.py::__init__` (lines 88-149) | role-match (extracted from) |
| `trading_system/backtest_runner.py` (NEW) | run driver | event-driven (for-loop) | `backtest_trading_system.py::_run_backtest` (lines 192-229) | role-match (extracted from) |
| `FeeModelCommissionEstimator` adapter (NEW; home = compose.py or exec adapter) | execution adapter | request-response | `_estimate_commission` closure (`backtest_trading_system.py:124-128`) | exact (promotes the closure) |
| `trading_system/backtest_trading_system.py` (MODIFY) | thin holder + factory | event-driven | itself (rename + slim) | self |
| `order_handler/order_manager.py` (MODIFY) | manager | CRUD/admission | itself + `OrderConfig` threading | self |
| `order_handler/order_handler.py` (MODIFY) | handler (facade) | event-driven | itself + `update_config` add | self |
| `execution_handler/execution_handler.py` (MODIFY) | handler | event-driven | itself (rng dedup, config thread, update_config) | self |
| `execution_handler/exchanges/simulated.py` (MODIFY) | exchange | request-response | `PortfolioHandler.update_config` (canonical body) | role-match |
| `portfolio_handler/portfolio_handler.py` (MODIFY) | handler | CRUD | itself (line 456 — the canonical template) | self (template source) |
| `portfolio_handler/portfolio.py` (MODIFY) | model holder | CRUD | `PortfolioHandler.update_config` (canonical body) | role-match |
| `strategy_handler/strategies_handler.py` (MODIFY) | handler | event-driven | `strategy_handler/base.py::reconfigure` (lines 323-341) | role-match (delegates to) |
| `price_handler/feed/bar_feed.py` (MODIFY) | feed (read-model) | streaming | interface-conformance raise (no analog body) | partial (raise-only stub) |

---

## Pattern Assignments

### `core/commission_estimator.py` (NEW — core Protocol, 4 SPACES)

**Analog:** `itrader/core/portfolio_read_model.py` — the read-model-seam Protocol that order-domain code reads cross-domain without importing the handler. `CommissionEstimator` is the identical shape: order domain reads execution's fee estimate via an injected Protocol.

**Protocol pattern** (`portfolio_read_model.py` lines 42-49, 78-89):
```python
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["PortfolioReadModel", "PositionView"]


@runtime_checkable
class PortfolioReadModel(Protocol):
    def available_cash(self, portfolio_id: PortfolioId) -> Decimal: ...
```
Mirror this for `CommissionEstimator` — primitive signature only, **zero `itrader` deps** (honors core's dependency rule; do NOT import `SimulatedExchange` here):
```python
@runtime_checkable
class CommissionEstimator(Protocol):
    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal: ...
```

**Conformance discipline:** `PortfolioReadModel` is satisfied **structurally** (D-16, no adapter/inheritance) and `mypy --strict` enforces the boundary at every retyped ctor. `OrderManager.commission_estimator` retypes the same way (see below).

---

### `FeeModelCommissionEstimator` adapter (NEW — execution/wiring layer, home = Claude's discretion)

**Analog:** the inline `_estimate_commission` closure being promoted (`backtest_trading_system.py` lines 122-128):
```python
simulated_exchange = self.execution_handler.exchanges.get('simulated')

def _estimate_commission(quantity: Decimal, price: Decimal) -> Decimal:
    if not isinstance(simulated_exchange, SimulatedExchange):
        return Decimal("0")
    return simulated_exchange.fee_model.calculate_fee(
        quantity, price, side="buy", order_type="market")
```

**LATE-BINDING TRAP (D-15, RESEARCH Trap 2):** the closure reads `simulated_exchange.fee_model` at CALL time, NOT construction. `SimulatedExchange.update_config` rebuilds `self.fee_model` (`simulated.py:656`). The adapter MUST hold the **exchange ref** and dereference `exchange.fee_model` in `__call__` — never capture `fee_model` at `__init__` (a fee-model reconfigure would silently use a stale estimator). Preserve the `side="buy", order_type="market"` admission convention (D-04). Indentation: if homed in `compose.py` → tabs; if in an exec-handler adapter module → tabs.

---

### `config/order.py` (NEW — `OrderConfig` Pydantic, 4 SPACES)

**Analog:** `itrader/config/exchange.py::ExchangeConfig` (lines 136-166) — the `extra="forbid"` + nested-submodel + `default()` convention.

**Model + config-dict pattern** (`exchange.py` lines 45-50, 136-166):
```python
from pydantic import BaseModel, ConfigDict, Field

class ExchangeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange_type: ExchangeVenue = ExchangeVenue.SIMULATED
    fee_model: FeeModelConfig = Field(default_factory=FeeModelConfig)
    # ...
    @classmethod
    def default(cls) -> "ExchangeConfig":
        return get_exchange_preset("default")
```
For `OrderConfig`: one field `market_execution: MarketExecution` (D-05), `ConfigDict(extra="forbid")`, a `default()` classmethod reproducing `"immediate"`.

**COERCION-EQUIVALENCE TRAP (D-05, RESEARCH Trap 5):** `OrderManager.__init__` today does `self.market_execution = MarketExecution(market_execution)` (`order_manager.py:86`) — str→enum, no-op on a member. `MarketExecution` is a plain `Enum` (not `str, Enum`) with case-insensitive `_missing_`. Pydantic v2 validates `Enum` by value. **Wave-0 test required (A1):** assert `OrderConfig.model_validate({"market_execution": "immediate"}).market_execution is MarketExecution.IMMEDIATE`. The backtest default is `"immediate"` (`order_handler.py:41`) — `OrderConfig` default must reproduce it byte-identically. Note the config-enum exception (CONVENTIONS.md): `MarketExecution` lives in `core/enums/order.py`, NOT relocated.

---

### `trading_system/system_spec.py` (NEW — frozen `SystemSpec`, TABS in package — match `backtest_trading_system.py`)

**Analog:** `tests/e2e/scenario_spec.py::ScenarioSpec` + `PortfolioSpec` (lines 30-98) — promoted ~verbatim (D-01).

**Frozen-dataclass pattern** (`scenario_spec.py` lines 30-42, 75-97):
```python
@dataclass(frozen=True)
class PortfolioSpec:
    user_id: int
    name: str
    cash: int

@dataclass(frozen=True)
class ScenarioSpec:
    start: str
    end: str
    timeframe: str
    ticker: str
    starting_cash: int
    data: dict[str, Any]
    strategies: list[Any]
    portfolios: list[PortfolioSpec]
    exchange: Any = None
    actions: tuple[Action, ...] = field(default_factory=tuple)
```
Promote field-for-field (D-02: name it `SystemSpec`, run-mode-agnostic — do NOT prefix `Backtest`). The harness reads attributes BY NAME, so keep `start/end/timeframe/data/strategies/portfolios/exchange` named identically so the e2e collapse maps cleanly. Drop `actions` if the operator hook stays e2e-only (Claude's discretion). NOTE: the source dataclass uses 4 spaces; if `system_spec.py` lands in `trading_system/` (tabs) the new file uses tabs — re-indent the promoted shape, do not paste 4-space lines into a tab file.

---

### `trading_system/compose.py` (NEW — `compose_engine` shared seam, TABS) + `backtest_runner.py` (NEW, TABS)

**Analog:** the current fat `__init__` (extract lines 88-149) + `_run_backtest` (extract lines 192-229) + `_initialise_backtest_session` (lines 152-190).

**Wiring body to extract** (`backtest_trading_system.py` lines 130-147 — the DI graph):
```python
order_storage = OrderStorageFactory.create('backtest')   # → moves to FACTORY (D-14a), passed IN
self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler, order_storage,
                                  commission_estimator=_estimate_commission)
self.event_handler = EventHandler(
    self.strategies_handler, self.screeners_handler, self.portfolio_handler,
    self.order_handler, self.execution_handler, self.feed.generate_bar_event,
    self.global_queue)
```
**D-14a boundary:** `compose_engine(spec, order_storage=...)` must NOT hardcode `'backtest'`. The factory `build_backtest_system` selects `OrderStorageFactory.create('backtest')` and passes it in (mirrors the injected `CommissionEstimator`/`PortfolioReadModel` DI rationale).

**Run-loop body to extract** (`backtest_trading_system.py` lines 211-225) — **ORDER-SENSITIVE (D-14/W4-02, RESEARCH Trap 4):**
```python
for time_event in self.time_generator:
    self.clock.set_time(time_event.time)
    self.global_queue.put(time_event)
    self.event_handler.process_events()
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(time_event.time)        # DIRECT call — never an event reroute
    if on_tick is not None:
        on_tick(self, time_event)
```
Preserve this exact sequence AND the `get_active_portfolios()` iteration order (dict-insertion → factory must `add_portfolio` in spec order, Trap 6). Also preserve `_initialise_backtest_session` ordering (lines 152-190): membership derive → `feed.bind` → ping-grid `reduce(pd.Index.union)` → `time_generator.set_dates` → per-strategy `feed.precompute` in registration order (W4-03 is a tidy, NOT a reorder). Backtest runner stays **fail-fast** (do not adopt live's publish-and-continue).

---

### `trading_system/backtest_trading_system.py` (MODIFY — rename + thin holder + factory, TABS)

**Self-analog.** D-03 mechanical rename `TradingSystem` → `BacktestTradingSystem`; the class `__init__` becomes a dumb holder of pre-built `engine`/`runner` exposing `run()`. Target shape (CONTEXT §specifics):
```python
def build_backtest_system(spec: SystemSpec) -> BacktestTradingSystem:
    engine = compose_engine(spec, order_storage=OrderStorageFactory.create('backtest'))
    runner = BacktestRunner(engine, ...)
    return BacktestTradingSystem(engine, runner)
```
`run(print_summary, on_tick)` keeps its existing signature (lines 231-232) and after the runner finishes calls `reporting.print_metrics_summary(...)` (W4-07 — `_print_metrics_summary` at line ~276 lifts into `reporting/`; the builders it calls already live in `reporting/frames.py`/`metrics.py`). **Import sites to update** (RESEARCH Runtime State Inventory): `scripts/run_backtest.py:47`, `tests/integration/test_backtest_oracle.py:249`, `tests/integration/conftest.py`, `test_universe_spans.py`, `test_reservation_inertness.py`, `test_backtest_smoke.py`, `tests/e2e/conftest.py:295` (deferred import).

---

### `execution_handler/execution_handler.py` (MODIFY — rng dedup + ExchangeConfig thread + update_config, TABS)

**Self-analog.** Three changes:

1. **rng dedup (D-16, Trap 3)** — replace `_resolve_rng_seed` (lines 54-62) which builds a 2nd `SystemConfig.default()`:
```python
# CURRENT (lines 61-62):
system_config = SystemConfig.default()
return int(system_config.performance.rng_seed)
# TARGET: read the process-wide singleton
from itrader import config
return int(config.performance.rng_seed)
```
Seed stays 42 → shared `random.Random(42)` unchanged → byte-exact.

2. **Remove hardcoded `register_symbol('BTCUSD')`** (line 111) — see Trap 1 below. Add an optional `ExchangeConfig` param to `__init__`/`init_exchanges` (Pitfall 4: today `ExecutionHandler(global_queue)` takes NO config; the param must be optional with default-None reproducing the default preset byte-exactly), threaded from `compose_engine`. Seeding rides this path (`SimulatedExchange(queue, rng=..., config=...)`).

3. **Add `update_config`** following the canonical body below (delegating to the exchange / its own config as applicable).

---

### `execution_handler/exchanges/simulated.py` (MODIFY — canonical update_config + symbol-seed trap, TABS)

**Analog (canonical body):** `PortfolioHandler.update_config` (`portfolio_handler.py:456-469`) + its `_deep_merge` (lines 437-454). Migrate the CURRENT `**kwargs`/`config_mapping`/bare-`ValueError` form (lines 622-672) to:
```python
def update_config(self, updates: dict[str, Any]) -> None:
    merged = _deep_merge(self.config.model_dump(), updates)
    try:
        new = ExchangeConfig.model_validate(merged)        # extra="forbid" catches unknown keys
    except pydantic.ValidationError as e:
        raise ConfigurationError(reason=str(e)) from e
    self.config = new                                       # atomic GIL swap
    # then RE-DERIVE the cached internals (Pitfall 1) — reproduce the existing
    # side-effects at simulated.py:654-672:
    self.fee_model = self._init_fee_model()
    self.slippage_model = self._init_slippage_model()
    self._supported_symbols = self.config.limits.supported_symbols   # REPLACEMENT — Trap 1
    self._min_order_size = self.config.limits.min_order_size          # Decimal — no float()
    self._max_order_size = self.config.limits.max_order_size
```
**Pitfall 2 — the `configure()` Protocol method** (lines 606-620): it delegates to `update_config(**config)` and catches `ValueError`. After migration it MUST call `update_config(config)` (dict, not kwargs) and catch `ConfigurationError` (not `ValueError`). Update the existing `configure` test accordingly. **Error contract (D-08):** wrap pydantic `ValidationError` into `core.ConfigurationError` (`base.py:28-42`, carries `config_key`/`config_value`/`reason`) — drop the bare `ValueError`.

---

### `portfolio_handler/portfolio_handler.py` (MODIFY — the canonical template source, TABS)

**Self-analog — this IS the closest existing template.** Current body (lines 456-469) already does deep-merge + `model_validate`; the migration is (a) `Dict→bool` becomes `dict→None` + raise (D-07/D-08 — stop returning `bool`, stop swallowing into `False`), and (b) keep the post-swap re-derivation `self.max_portfolios = config.limits.max_portfolios` (line 464, Pitfall 1):
```python
def update_config(self, updates: dict[str, Any]) -> None:
    merged = self._deep_merge(self.config_data.model_dump(), updates)
    try:
        self.config_data = PortfolioConfig.model_validate(merged)
    except pydantic.ValidationError as e:
        raise ConfigurationError(reason=str(e)) from e
    self.max_portfolios = self.config_data.limits.max_portfolios   # preserve re-derive
```
Its `_deep_merge` (lines 437-454) is the helper to **promote to a shared util** (RESEARCH Don't Hand-Roll — WR-04 sibling-preservation already handled; do NOT re-derive a fresh merge per handler):
```python
@staticmethod
def _deep_merge(base, updates):
    merged = dict(base)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
```

---

### `portfolio_handler/portfolio.py` (MODIFY — canonical migration, TABS)

**Analog:** the canonical body above. Current form (lines 163-189) is `**kwargs` + `config_mapping` `setattr` pokes raising `ConfigurationError(config_key=key)` on unknown key. Migrate to `dict` + `_deep_merge` + `model_validate` + atomic swap. It already raises `ConfigurationError` (line 189) — keep that type, but source it from the pydantic-wrap path. The `config_mapping` poke dict (lines 166-178) is exactly what D-07/D-09 replace.

---

### `order_handler/order_manager.py` + `order_handler.py` (MODIFY — OrderConfig + retype + update_config, TABS)

**Self-analog + canonical body.** Three changes:

1. **OrderConfig threading (D-05):** replace the loose ctor param `market_execution: "str | MarketExecution" = "immediate"` (`order_manager.py:48`) with an `OrderConfig` (carrying `market_execution`). The coercion `self.market_execution = MarketExecution(market_execution)` (line 86) moves INTO `OrderConfig` validation.

2. **Retype commission_estimator (D-15):**
```python
# CURRENT (order_manager.py:50, 74-80):
commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]] = None
# TARGET:
commission_estimator: Optional[CommissionEstimator] = None
```
Pure typing change — `FeeModelCommissionEstimator` is callable with the identical signature; golden run pins fees 0 (`ZeroFeeModel`) → estimate `Decimal("0")` exactly as today (Trap 2).

3. **Add `update_config`** via the canonical body over `OrderConfig` (on the handler facade or manager — keep the facade thin per CLAUDE.md: handler delegates to manager).

---

### `strategy_handler/strategies_handler.py` (MODIFY — NON-config-model internals, TABS)

**Analog:** `strategy_handler/base.py::reconfigure` (lines 323-341) + `_run_init` (lines 256-289). D-09 explicitly FORBIDS inventing a `StrategiesHandlerConfig`. `StrategiesHandler.update_config` is NEW but delegates per-strategy to the pre-built idempotent seam:
```python
# base.py:338-341 — the unit StrategiesHandler.update_config calls per strategy:
self._apply_params(**kwargs)   # re-apply + re-coerce
self.validate()                # re-validate
self._run_init()               # reset handles, re-run init(), re-derive warmup/max_window (lines 283-289)
```
`_run_init` UNCONDITIONALLY re-derives `self.warmup = max(min_period, default=0)` and `self.max_window` (Phase 3 D-08 auto-warmup). The handler iterates `self.strategies` (registration order — `strategies_handler.py:189`) and calls `strategy.reconfigure(**kwargs)`. The **dict→`**kwargs`** translation at the handler boundary is Claude's discretion. Error contract: wrap any failure in `ConfigurationError` (D-08) to keep the single-catch surface.

---

### `price_handler/feed/bar_feed.py` (MODIFY — interface-conformance RAISE, 4 SPACES)

**No body analog — D-10 is a raise-only stub.** The feed has NO Pydantic config model (`__init__` at line 144 holds `_base_timeframe`/`_base_alias` as plain attrs; no `self.config`, no `update_config`/`reconfigure` today). Do NOT invent a `FeedConfig` (D-09). Implement to RAISE on unsafe hot-swaps (Pitfall 3):
```python
def update_config(self, updates: dict[str, Any]) -> None:
    # D-10: interface-conformance. base_timeframe (line 145) ripples into
    # _base_alias and the window cutoff math (line 364) — a replace, not a hot-swap.
    raise ConfigurationError(
        config_key="base_timeframe",
        reason="cannot hot-swap base_timeframe in backtest — replace the feed")
```
The method exists purely to satisfy the uniform interface and fail loudly (D-10). Match the 4-space `price_handler/feed/` indentation. (D-17: the `BarFeed` ABC stays in `feed/base.py` — zero churn.)

---

## Shared Patterns

### Canonical `update_config` body (config-model handlers)
**Source:** `PortfolioHandler.update_config` + `_deep_merge` (`portfolio_handler.py:437-469`)
**Apply to:** `SimulatedExchange`, `Portfolio`, `ExecutionHandler`, `OrderManager`/`OrderHandler`
```python
def update_config(self, updates: dict[str, Any]) -> None:
    merged = deep_merge(self.config.model_dump(), updates)
    try:
        new = SomeConfig.model_validate(merged)     # extra="forbid" rejects unknown keys
    except pydantic.ValidationError as e:
        raise ConfigurationError(reason=str(e)) from e
    self.config = new                                # atomic GIL-safe reference swap (D-11)
    # re-derive cached internals from new (Pitfall 1 — handler-specific)
```
Return `None`, raise on any failure (D-07/D-08). No new lock (atomic swap IS the thread-safety primitive, D-11). Applied between event cycles, never mid-cycle.

### Error contract (single web-catchable type)
**Source:** `itrader/core/exceptions/base.py:28-42` (`ConfigurationError(config_key, config_value, reason)`)
**Apply to:** every migrated `update_config` — wrap pydantic `ValidationError` into `ConfigurationError`. No new exception type (D-08; `ConfigUpdateError` subtype deferred).

### Read-model-seam Protocol
**Source:** `itrader/core/portfolio_read_model.py` (`runtime_checkable` Protocol, structural conformance, zero-dep primitive signature)
**Apply to:** `core/commission_estimator.py` + the retyped `OrderManager.commission_estimator`.

### Deep-merge helper (promote, don't re-derive)
**Source:** `portfolio_handler.py:437-454` — already handles WR-04 sibling-preservation.
**Apply to:** all config-model `update_config` bodies — lift to ONE shared helper.

---

## Byte-Exact Trap: PATTERNS-A2 symbol seeding (HIGHEST RISK — D-13, RESEARCH Trap 1)

**Three layers stack to today's `_supported_symbols`:**
1. `SimulatedExchange.__init__` seeds `_supported_symbols = config.limits.supported_symbols` = default preset `{BTCUSDT, ETHUSDT, ADAUSDT, DOTUSDT, SOLUSDT}` (`exchange.py:182`, `simulated.py:98`).
2. `ExecutionHandler.init_exchanges` then **ADDITIVELY** `register_symbol('BTCUSD')` (union — `execution_handler.py:111`).
3. e2e conftest then **ADDITIVELY** `register_symbol(ticker.upper())` per spec ticker (`conftest.py:347-349`).

**The trap:** `SimulatedExchange.update_config` re-derives `_supported_symbols` from `config.limits` by **REPLACEMENT** (`simulated.py:664-665`). The default preset OMITS `BTCUSD`. If construction seeds a spec-derived `ExchangeConfig.limits` lacking `BTCUSD` and relies on a later additive `register_symbol`, ANY subsequent `update_config(limits=...)` WIPES `BTCUSD` → every order silently REFUSEd.

**The fix (D-13):** the FACTORY folds the COMPLETE set — `default preset ∪ {BTCUSD} ∪ spec tickers (upper-cased)` — into `ExchangeConfig.limits.supported_symbols` BEFORE `SimulatedExchange` reads it (construction-time replacement-safe). Then REMOVE the hardcoded `register_symbol('BTCUSD')` (`execution_handler.py:111`) AND the conftest loop (`conftest.py:347-349`). Oracle path (`scripts/run_backtest.py`, no spec) → derive `{BTCUSD}` from `csv_paths` keys, union the default preset. **Assertion:** final `_supported_symbols` == today's union exactly. `register_symbol` stays a valid public seam but is no longer load-bearing for composition.

The conftest comment block at `conftest.py:306-349` is the EXACT inline this collapse removes (the fee/slippage re-init + size-cache re-derivation + `register_symbol` loop) — subsumed by constructing the exchange with the spec's `ExchangeConfig` at `compose_engine` time. Plan a wave that runs the FULL e2e suite immediately after the `compose_engine` exchange-config threading lands (Open Question 1: isolate any non-None-`spec.exchange` fee/slippage/limits diff).

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `price_handler/feed/bar_feed.py::update_config` | feed | streaming | No config-model hot-swap exists; D-10 is a deliberate raise-only stub (interface-conformance), no body to copy. |

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/config/`, `itrader/trading_system/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/strategy_handler/`, `itrader/price_handler/feed/`, `tests/e2e/`
**Files read for excerpts:** 11 (`portfolio_read_model.py`, `config/exchange.py`, `portfolio_handler.py`, `simulated.py`, `scenario_spec.py`, `backtest_trading_system.py`, `order_manager.py`, `execution_handler.py`, `portfolio.py`, `core/exceptions/base.py`, `tests/e2e/conftest.py`, `strategy_handler/base.py`, `strategies_handler.py`, `bar_feed.py`)
**Pattern extraction date:** 2026-06-12
</content>
</invoke>
