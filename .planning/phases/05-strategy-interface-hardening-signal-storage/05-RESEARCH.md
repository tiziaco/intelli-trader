# Phase 5: Strategy Interface Hardening & Signal Storage - Research

**Researched:** 2026-06-09
**Domain:** Python strategy-interface design (pydantic v2 config contract), pluggable storage seam, enum propagation, byte-exact golden-master refactor
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Nautilus-style config object as the single constructor arg. `Strategy(config: BaseStrategyConfig)`; the base stores `self.config` as the single source of truth. Engine-facing attrs (timeframe, tickers, order_type, direction, allow_increase, max_positions, sizing_policy, sltp_policy) read from it. Gives SIG-01's config snapshot for free (`self.config` is the snapshot). Touches `run_backtest.py` + strategy test call sites; must re-prove byte-exact.
- **D-02:** Per-strategy params via subclass. `SMA_MACDConfig(BaseStrategyConfig)` adds `short_window`/`long_window`/`FAST`/`SLOW`/`WIN` + cross-field validators (`short_window < long_window`, positivity). One inheritance chain — NOT a parallel `params` submodel. Template every Phase 6-9 strategy author follows.
- **D-03:** `BaseStrategyConfig` is frozen (`model_config` frozen=True) — matches the frozen-value-object convention; makes the snapshot immutable.
- **D-04:** `order_type` is the `OrderType` enum field on the config (default `OrderType.MARKET`); stringly-typed `"market"` removed from `base.py`/`SMA_MACD_strategy.py` and the `OrderType(strategy.order_type)` boundary parse in `strategies_handler.py` collapses (HARD-03 / FL-04). FL-02 `portfolio_id: int` annotation retyped on the event facts.
- **D-05:** Keep the frozen dataclasses; pydantic tolerates them. `BaseStrategyConfig` uses `ConfigDict(arbitrary_types_allowed=True, frozen=True)`; `sizing_policy`/`sltp_policy` stay the frozen dataclass unions in `core/sizing.py`. Zero change to `SignalEvent`/`OrderManager`/`SizingResolver`. Discriminated-union migration routed to v1.3.
- **D-06:** Typed `Timeframe` enum/`Literal` at the config boundary; convert via `to_timedelta` in the base (unchanged). Config field is the supported fixed-duration vocabulary, validated loudly at construction (HARD-01), stored human-readable; base computes `self.timeframe = to_timedelta(config.timeframe)` exactly as today. Structured `(step, unit)` bar-spec routed to roadmap.
- **D-07:** Full pluggable seam mirroring `order_handler/storage/` — ABC + in-memory backend + `SignalStorageFactory`.
- **D-08:** Dedicated frozen `SignalRecord` entity — distinct from `SignalEvent`. Carries SIG-01 fields (strategy id, ticker, action, time, sizing/sltp declarations) + config snapshot.
- **D-09:** Per-intent capture (pre-fan-out). One `SignalRecord` per non-`None` `generate_signal` result, captured BEFORE per-portfolio fan-out → NO `portfolio_id` on the record. Portfolio reconciliation is a natural-key join `(strategy_id, ticker, time)` → orders → per-portfolio, downstream at the order layer. One strategy emits at most one intent per ticker per bar (key is unique). No hard FK in v1.1.
- **D-10:** `SignalRecord` carries a UUIDv7 `SignalId` — new `core/ids.py` type + `idgen.generate_signal_id`, mirroring `StrategyId`/`OrderId`.
- **D-11:** Config snapshot stored by reference — store the frozen `self.config` object directly on the record; serialize (`model_dump`) only at the storage/query edge.
- **D-12:** Wiring: `StrategiesHandler` owns an injected `SignalStore`; writes a record when an intent fires; store read post-run via a `TradingSystem` accessor — queue-only contract preserved (store is a sink/read-model). Query API: `get_all` / `by_strategy` / `by_ticker`.
- **D-13:** Move `SMA_MACD_strategy.py` + `empty_strategy.py` into a new `itrader/strategy_handler/strategies/` package. `base.py` + `strategies_handler.py` stay at top level. Update the 4 real import sites. Re-prove byte-exact.
- **D-14:** Move `__str__`/`__repr__` to the base (derive from `name` + `config.timeframe`); concrete strategies drop their copies. Zero result-path risk.
- **D-15:** Framework-enforced warmup guard. Remove the hand-written `if len(bars) < self.max_window: return None` in each strategy; the handler short-circuits (`if len(data) < strategy.max_window: continue`) BEFORE calling `generate_signal`. Behaviorally identical → prove oracle-dark.

### Claude's Discretion

- Exact `BaseStrategyConfig` field set/shape and validator wiring (subject to D-01..D-06).
- How `max_window` is exposed on the config/strategy (param-derived, e.g. `max([long_window, 100])` for SMA_MACD) — subject to D-15.
- The precise `SignalRecord` field set and `SignalStore` ABC method surface (subject to D-07..D-12).
- Where the `Timeframe` enum/`Literal` lives (`core/enums/` vs config module) and the exact supported vocabulary list (subject to D-06).
- Whether/where the `last_time`/window helper lands (subject to D-15).
- Whether the base-class migration also touches the e2e test strategies in this phase or leaves them as a Phase-6 follow-up (`my_strategies/*` is OUT).

### Deferred Ideas (OUT OF SCOPE)

- Serializable discriminated-union sizing/SLTP vocabulary → v1.3 (Persistence).
- Structured `(step, unit)` bar-spec value object → roadmap.
- Declared-indicator framework (auto-derived warmup, stateful incremental indicators) → roadmap.
- Hard signal→order FK (Order stores the `SignalId`) → v1.3.
- Re-baselining the golden numbers; `my_strategies/*`; shorts / non-LONG_ONLY (v1.2).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-01 | Pydantic `BaseStrategyConfig` validating engine-facing declarations | Mirror `itrader/config/portfolio.py` pydantic v2 pattern (`ConfigDict`, `Field(gt=0)`, enum fields). Must use `arbitrary_types_allowed=True` to hold the `core/sizing.py` frozen-dataclass unions (verified: pydantic 2.13.4 accepts them and `model_dump()` recurses into them). |
| HARD-02 | Per-strategy params model with validators (`short_window < long_window`, positivity) | `SMA_MACDConfig(BaseStrategyConfig)` subclass adds the 5 params + a `@model_validator(mode="after")` for the cross-field rule and `Field(gt=0)` for positivity. SMA_MACD golden defaults: short=50, long=100, FAST=6, SLOW=12, WIN=3 (`SMA_MACD_strategy.py:25-29`). |
| HARD-03 | `order_type` is the `OrderType` enum end-to-end (`"market"` removed) | `OrderType` already exists (`core/enums/order.py`); `SignalEvent.order_type` is ALREADY `OrderType`. Change is: config field typed `OrderType` (default `OrderType.MARKET`), drop `self.order_type` string on base (`base.py:27,38,64`), collapse `OrderType(strategy.order_type)` at `strategies_handler.py:95`. This is FL-04. |
| HARD-04 | Behavior-preserving — SMA_MACD golden byte-exact (134 trades / `final_equity 46189.87730727451`) | Gate is `tests/integration/test_backtest_oracle.py` (exact `assert_frame_equal(check_exact=True)`). Re-run after every change. Note: HARD-04 in REQUIREMENTS.md cites `46189.87730727451`; the oracle test's comment cites a stale interim `46132.7668` — trust the committed `tests/golden/summary.json` as the live truth (the test asserts against it, not the comment). |
| SIG-01 | Typed signal records (strategy id, ticker, action, time, sizing/sltp declarations, config snapshot) | New frozen `SignalRecord` dataclass + `SignalId` (`core/ids.py` + `idgen.generate_signal_id`). Mirrors the `Order`-vs-`OrderEvent` separation. Config snapshot = `self.config` stored by reference (D-11). |
| SIG-02 | Stored signals queryable for post-run inspection + feed E2E assertions | `SignalStore` ABC + `InMemorySignalStore` + `SignalStorageFactory`, mirroring `order_handler/storage/`. Query API `get_all`/`by_strategy`/`by_ticker` (predicate-filter over a flat dict). Read post-run via a `TradingSystem` accessor. |
</phase_requirements>

## Summary

This is a **byte-exact brownfield hardening refactor** of the strategy interface, plus a new **pluggable signal-storage seam** that mirrors the existing order-storage pattern exactly. The decision set (D-01..D-15) is fully locked by an unusually detailed CONTEXT.md; almost nothing here is open-ended research — the work is **mechanical and pattern-following**, and every change is guarded by one exact-diff golden gate.

The single biggest finding from the codebase: **most of the "hard" infrastructure already exists.** `OrderType` is already an enum and `SignalEvent.order_type` is already `OrderType`-typed; `SignalEvent.portfolio_id` / `OrderEvent.portfolio_id` / `FillEvent.portfolio_id` are already annotated `int` (FL-02 may already be satisfied — verify). The `core/sizing.py` frozen-dataclass unions already self-validate. The order-storage seam (ABC + in-memory flat-dict + factory) is a clean template to copy verbatim for `SignalStore`. The `core/ids.py` `NewType` + `idgen.generate_*_id` pattern extends trivially for `SignalId`. The pydantic `config/` package (e.g. `portfolio.py`) is the exact model/validator/`ConfigDict` style to follow.

The two genuine landmines are: (1) the **D-01 constructor-contract change ripples to 4 import sites and ~6 construction call sites** (`run_backtest.py`, 3 strategy tests including an inline `_AlwaysBuyStrategy(**kwargs)` helper and the e2e `SingleMarketBuy`), each of which must be migrated to build a config object; and (2) the **byte-exact requirement** means the D-15 warmup-guard relocation and the D-01 refactor must be proven to produce identical fills — the SMA_MACD `len(bars) < max_window` short-circuit moves from the strategy to the handler and must short-circuit at the *same* tick.

**Primary recommendation:** Sequence the work so the golden gate runs green after each atomic change — (1) add `SignalId`/`idgen` + the `Timeframe` enum; (2) build `BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig` and refactor `base.py` to the single-config constructor (D-01..D-06, D-14), migrating all call sites in the same commit; (3) collapse the `order_type` string + the boundary parse (D-04/HARD-03); (4) relocate the two strategies (D-13); (5) build the `SignalStore` seam + `SignalRecord` and wire per-intent capture + the handler warmup short-circuit (D-09/D-12/D-15) + the `TradingSystem` accessor. Re-run `test_backtest_oracle.py` after each.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Strategy config validation (HARD-01/02) | Strategy base (`base.py`) + config (pydantic model) | — | Construction-time concern; pure-alpha D-12 keeps `generate_signal` free of it |
| `order_type` enum end-to-end (HARD-03) | `core/enums` (type) → config (declaration) → `strategies_handler` (no parse) | events (`SignalEvent` already typed) | The enum is a core vocabulary; the handler is where the old string parse lived |
| Warmup short-circuit (D-15) | `StrategiesHandler.calculate_signals` | strategy base (optional `max_window`/`last_time` helper) | Warmup is a framework concern (nautilus/LEAN contract), not per-strategy alpha |
| Signal record capture (SIG-01) | `StrategiesHandler` (writes per intent, pre-fan-out) | `core/ids` (`SignalId`), strategy (`self.config` snapshot) | Per-intent capture must happen before the per-portfolio fan-out loop |
| Signal storage + query (SIG-02) | new `strategy_handler/storage/` seam | `TradingSystem` (injection + post-run accessor) | Mirror of `order_handler/storage/`; sink/read-model, queue-contract preserved |
| Strategy relocation (D-13) | `strategy_handler/strategies/` package | 4 import sites | Folder = supported-reference vs `my_strategies/` (user IP) |

## Standard Stack

### Core (already in the repo — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.13.4 | `BaseStrategyConfig` / `SMA_MACDConfig` model + validators (HARD-01/02) | `[VERIFIED: poetry run python -c "import pydantic"]` — already the repo's config-modelling library (`itrader/config/*.py`); matches the typed/single-source ethos |
| `uuid-utils` | ^0.16.0 | `SignalId` UUIDv7 via `idgen.generate_signal_id` (D-10) | `[CITED: CLAUDE.md tech stack]` — single UUIDv7 scheme (locked decision) |
| stdlib `dataclasses` | 3.13 | frozen `SignalRecord` entity (D-08) | `[CITED: CLAUDE.md]` — the repo's entity/value-object convention (`Order`, `SignalIntent`, `Bar` are all frozen dataclasses) |
| stdlib `enum` | 3.13 | `Timeframe` enum (D-06) + `OrderType` (existing) | `[CITED: core/enums/]` — house pattern is class-based `Enum` with `_missing_` case-insensitive parse |

**No new third-party packages are introduced by this phase.** No package-legitimacy audit / slopcheck is required.

### Alternatives Considered (resolved by CONTEXT.md — do NOT re-open)

| Instead of | Could Use | Tradeoff (locked outcome) |
|------------|-----------|---------------------------|
| frozen-dataclass sizing held under `arbitrary_types_allowed` (D-05) | serializable discriminated union with `kind` tags | Routed to v1.3 — forces a rewrite on the byte-exact path; out of scope |
| `to_timedelta(str)` conversion in base (D-06) | structured `(step, unit)` bar-spec value object | Routed to roadmap — rewrites the time core; out of scope |
| handler short-circuit on `max_window` (D-15) | declared-indicator framework w/ auto-warmup | Routed to roadmap; out of scope |

## Architecture Patterns

### System Architecture Diagram (the Phase-5 deltas on the signal path)

```
BAR event
   │
   ▼
StrategiesHandler.calculate_signals(event)                 [strategy_handler/strategies_handler.py]
   │
   ├─ for strategy in self.strategies:
   │     check_timeframe(event.time, strategy.timeframe) ──no──▶ skip
   │     │ yes
   │     for ticker in strategy.tickers:
   │        bar = event.bars.get(ticker) ──None──▶ skip          (sparse-ticker guard, unchanged)
   │        data = self.feed.window(ticker, tf, max_window, asof=event.time)
   │        ┌─────────────────────────────────────────────────┐
   │        │ D-15: if len(data) < strategy.max_window: continue │  ◀── NEW framework warmup guard
   │        └─────────────────────────────────────────────────┘   (was inside generate_signal)
   │        intent = strategy.generate_signal(ticker, data)        (PURE pandas, D-12 — unchanged)
   │        if intent is None: continue
   │        ┌─────────────────────────────────────────────────┐
   │        │ D-09/D-12: signal_store.add(SignalRecord(...))     │  ◀── NEW per-intent capture
   │        │   captured ONCE here, BEFORE the fan-out loop      │     (no portfolio_id on record)
   │        └─────────────────────────────────────────────────┘
   │        for portfolio_id in strategy.subscribed_portfolios:    (per-portfolio fan-out)
   │           signal = SignalEvent(
   │              order_type = strategy.order_type,  ◀── D-04: was OrderType(strategy.order_type)
   │              ... )                                  now already an OrderType enum from config
   │           self.global_queue.put(signal)
   ▼
SIGNAL events ──▶ OrderHandler.on_signal ──▶ Order(strategy_id, portfolio_id, ticker, time, ...)
                                                  │
                              D-09 natural-key join: (strategy_id, ticker, time) links
                              the per-intent SignalRecord to its downstream per-portfolio Orders

POST-RUN:  TradingSystem.<accessor>() ──▶ signal_store.get_all() / by_strategy() / by_ticker()
           (queue-only contract preserved — store is a read-model sink, not a cross-domain call)
```

### Recommended Project Structure (after D-13 + D-07)

```
itrader/strategy_handler/
├── base.py                      # Strategy ABC — config constructor, __str__/__repr__ (D-01/D-14)
├── strategies_handler.py        # warmup short-circuit + per-intent capture + no order_type parse
├── config.py  (NEW)             # BaseStrategyConfig (or under config/ — Claude's discretion)
├── strategies/        (NEW pkg) # supported-reference strategies (D-13)
│   ├── __init__.py
│   ├── SMA_MACD_strategy.py     # relocated; + SMA_MACDConfig
│   └── empty_strategy.py        # relocated; + EmptyStrategyConfig
├── my_strategies/               # user IP — OUT of scope, untouched
└── storage/           (NEW pkg) # SignalStore seam — mirror order_handler/storage/ (D-07)
    ├── __init__.py
    ├── base.py                  # SignalStore ABC  (or co-locate ABC, your call)
    ├── in_memory_storage.py     # InMemorySignalStore (flat dict + predicate filters)
    └── storage_factory.py       # SignalStorageFactory.create(environment)

itrader/core/
├── ids.py                       # + SignalId NewType (D-10)
├── sizing.py                    # UNCHANGED (D-05)
└── enums/
    └── trading.py | new module  # + Timeframe enum (D-06 — location is Claude's discretion)
itrader/outils/id_generator.py   # + generate_signal_id (D-10)
```

### Pattern 1: pydantic v2 config model (mirror `config/portfolio.py`)
**What:** A `BaseModel` subclass with `ConfigDict`, `Field(...)` constraints, enum fields, and `@model_validator`/`@field_validator`.
**When to use:** `BaseStrategyConfig` + `SMA_MACDConfig`.
**Example (verified shape against the repo + pydantic 2.13.4):**
```python
# Source: pattern from itrader/config/portfolio.py; arbitrary_types verified live
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from itrader.core.enums import OrderType, TradingDirection
from itrader.core.sizing import SizingPolicy, SLTPPolicy   # frozen-dataclass unions

class BaseStrategyConfig(BaseModel):
    # D-03 frozen + D-05 arbitrary_types (holds the frozen sizing dataclasses)
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    timeframe: str                      # D-06 typed Timeframe enum/Literal at boundary
    tickers: list[str]
    order_type: OrderType = OrderType.MARKET          # D-04 (HARD-03)
    direction: TradingDirection = TradingDirection.LONG_ONLY
    allow_increase: bool = False
    max_positions: int = Field(default=1, gt=0)
    sizing_policy: SizingPolicy         # required — honest contract (D-05)
    sltp_policy: SLTPPolicy | None = None

class SMA_MACDConfig(BaseStrategyConfig):
    short_window: int = Field(default=50, gt=0)
    long_window: int = Field(default=100, gt=0)
    FAST: int = Field(default=6, gt=0)
    SLOW: int = Field(default=12, gt=0)
    WIN: int = Field(default=3, gt=0)

    @model_validator(mode="after")
    def _short_lt_long(self) -> "SMA_MACDConfig":
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")
        return self
```
**Verified behaviour (pydantic 2.13.4):** with `arbitrary_types_allowed=True`, constructing with a `FractionOfCash(Decimal("0.95"))` instance works; `frozen=True` raises `ValidationError` on mutation; `model_dump()` **recurses into the frozen dataclass** (`{'sizing_policy': {'fraction': Decimal('0.95')}}`) — this is what gives SIG-02 a queryable snapshot serialization at the storage edge (D-11).

### Pattern 2: pluggable storage seam (copy `order_handler/storage/` verbatim in shape)
**What:** ABC (`base.py:OrderStorage`) + flat-dict in-memory backend (predicate-filter queries) + factory keyed on environment string.
**When to use:** `SignalStore` (D-07).
**Example (the in-memory query style to mirror):**
```python
# Source: itrader/order_handler/storage/in_memory_storage.py
class InMemorySignalStore(SignalStore):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, SignalRecord] = {}   # flat-dict, O(1), native-UUID key
    def add(self, record: SignalRecord) -> None:
        self._by_id[record.signal_id] = record
    def get_all(self) -> list[SignalRecord]:
        return list(self._by_id.values())
    def by_strategy(self, strategy_id) -> list[SignalRecord]:
        return [r for r in self._by_id.values() if r.strategy_id == strategy_id]
    def by_ticker(self, ticker: str) -> list[SignalRecord]:
        return [r for r in self._by_id.values() if r.ticker == ticker]
```
Factory mirrors `OrderStorageFactory.create(environment)` → `('backtest','test') -> InMemory`, `'live' -> NotImplemented/Postgres placeholder` (the order factory raises `ConfigurationError` on unknown env).

### Pattern 3: entity-vs-event separation (mirror `Order` vs `OrderEvent`)
**What:** `SignalRecord` is a frozen dataclass entity distinct from the in-flight `SignalEvent` fact (D-08), exactly as `Order` (`order_handler/order.py`) is distinct from `OrderEvent`.
**SignalRecord field set (proposed, subject to D-08):**
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SignalRecord:
    signal_id: SignalId          # D-10 — own identity (per-intent, no event_id exists yet)
    strategy_id: StrategyId      # D-09 natural-key
    ticker: str                  # D-09 natural-key
    time: datetime               # D-09 natural-key (event.time, business time)
    action: Side
    stop_loss: Decimal | None
    take_profit: Decimal | None
    exit_fraction: Decimal
    quantity: Decimal | None
    config: BaseStrategyConfig   # D-11 snapshot by reference (frozen → safe to share)
    # NO portfolio_id (D-09 — captured pre-fan-out)
```

### Pattern 4: core id type + generator (extend `core/ids.py` + `idgen`)
```python
# itrader/core/ids.py        — add to the NewType list + __all__
SignalId = NewType("SignalId", uuid.UUID)
# itrader/outils/id_generator.py — add the generator method
def generate_signal_id(self) -> uuid.UUID:
    return self._uuid7()
```

### Anti-Patterns to Avoid
- **Putting pydantic validation or config knowledge inside `generate_signal`.** D-12 pure-alpha: `generate_signal` stays pure pandas (no config reads beyond the params the base already copies onto `self`). Validation is construction-only.
- **Capturing `SignalRecord` inside the per-portfolio fan-out loop.** That would write N records per intent and force a (wrong) `portfolio_id` onto the record. Capture ONCE, before the loop (D-09).
- **Calling the `SignalStore` across a domain boundary at runtime.** It is an injected sink/read-model read POST-run via a `TradingSystem` accessor (D-12) — never a cross-domain handler call mid-run.
- **Hand-rolling a second id scheme for `SignalId`.** Use `idgen.generate_signal_id()` → `uuid_utils.compat.uuid7()` (single UUIDv7 scheme, locked).
- **Re-baselining the golden numbers to make a change pass.** Any result change is owner-gated (HARD-04); a drift means the refactor was NOT behavior-preserving.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Strategy-config validation | bespoke `if`-checks in `__init__` | pydantic `BaseModel` + `Field`/`@model_validator` | HARD-01/02 mandate it; matches `config/` house style; free serialization for SIG-02 |
| Signal storage backend | a one-off dict in the handler | `SignalStore` ABC + factory mirroring `order_handler/storage/` | D-07; consistency + v1.3 Postgres readiness |
| Signal id | custom counter / prefix scheme | `idgen.generate_signal_id()` (UUIDv7) | Single UUIDv7 scheme is a locked correctness decision |
| Timeframe→timedelta conversion | new parsing | existing `to_timedelta` (`outils/time_parser.py`) | D-06 — only TYPE the boundary; conversion stays byte-exact |
| Sizing-policy validation/serialization | new union model | existing `core/sizing.py` frozen dataclasses (`__post_init__` self-validate) | D-05; discriminated-union migration is v1.3 |
| Enum string parse | manual `.upper()` map | existing `OrderType._missing_` / `TradingDirection._missing_` house pattern | Already case-insensitive + fail-loud |

**Key insight:** This phase is almost entirely *assembling existing patterns* — pydantic-config (from `config/`), storage-seam (from `order_handler/storage/`), id-type (from `core/ids.py`), entity-vs-event (from `Order`). The risk is not novelty; it is **byte-exact preservation** while reshaping the constructor surface and moving the warmup guard.

## Runtime State Inventory

> This phase is a code/config refactor of an in-process backtest engine. There is NO external runtime state (no DB writes on the golden path, no OS-registered tasks, no live services). The "state" that matters is the **golden master fixtures** and the **construction call sites** that the D-01 contract change breaks.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the golden run uses in-memory order storage and writes only `output/{trades,equity}.csv` + `summary.json` (regenerated each run). The new `SignalStore` is in-memory only (v1.1). | None |
| Live service config | None — backtest is fully in-process, no external services. | None |
| OS-registered state | None. | None |
| Secrets/env vars | None — no secret names reference the strategy interface. | None |
| Build artifacts / construction call sites | **Strategy constructor signature change (D-01) breaks every call site.** Confirmed sites that pass loose kwargs and MUST migrate to a config object: `scripts/run_backtest.py:72` (`SMA_MACD_strategy(timeframe=..., tickers=...)`), `tests/unit/strategy/test_strategy.py:87,104,111,120` (`SMA_MACD_strategy(...)`) + the inline `_AlwaysBuyStrategy(**kwargs)` helper at `:136-145` (calls `super().__init__("always_buy","1d",[...],**kwargs)` with `direction=...`) + `_AlwaysBuyStrategy(direction=...)` at `:251,267`, `tests/integration/test_backtest_smoke.py:18` (import), `tests/integration/test_reservation_inertness.py:69` (inline import + constructs via `module.START_DATE` path), `tests/e2e/strategies/single_market_buy.py:36-67` (`SingleMarketBuy(Strategy)` passes positional+kwargs to `super().__init__`). | Migrate all to build a config object; same-commit. The e2e `SingleMarketBuy` adoption is Claude's-discretion (this phase vs Phase-6 follow-up). |
| Import sites (D-13 relocation) | The **4 REAL import sites** of `from itrader.strategy_handler.SMA_MACD_strategy import SMA_MACD_strategy`: `scripts/run_backtest.py:45`, `tests/unit/strategy/test_strategy.py:40`, `tests/integration/test_backtest_smoke.py:18`, `tests/integration/test_reservation_inertness.py:69` (inline). `scripts/crossval/*` mentions (`indicators.py:5`, `backtrader_run.py:9`, `backtesting_py_run.py:9`) are **verbatim-quote comments only** — optional stale-path touch-up, NOT functional imports. `empty_strategy.py` has no production import site (test-only). | Update the 4 import paths to `itrader.strategy_handler.strategies.SMA_MACD_strategy`; re-prove byte-exact. |

## Common Pitfalls

### Pitfall 1: D-15 warmup-guard relocation changes the firing tick
**What goes wrong:** Moving `if len(bars) < max_window: return None` from the strategy to a handler `continue` could short-circuit at a *different* boundary if `max_window` is read differently (e.g. from config-derived vs the `self.max_window` the strategy set in `__init__`).
**Why it happens:** SMA_MACD sets `self.max_window = max([self.long_window, 100])` (=100) in `__init__`. The handler already passes `strategy.max_window` to `feed.window(...)` (`strategies_handler.py:80`). The guard must use the **same** `strategy.max_window` value, and the comparison must be `len(data) < strategy.max_window` (strictly-less, matching the strategy's `<`).
**How to avoid:** Keep `max_window` on the strategy instance (param-derived in `__init__`, Claude's discretion how it's exposed via config); use the identical `<` comparison; verify the empty/exactly-100-bar boundary produces an identical first-signal tick. Prove with the oracle gate.
**Warning signs:** Trade count drifts from 134; first trade entry_date shifts.

### Pitfall 2: pydantic `frozen=True` blocks the post-construction attribute copies the base does today
**What goes wrong:** `base.py.__init__` currently sets `self.timeframe = to_timedelta(...)`, `self.max_window`, `self.subscribed_portfolios`, etc. on the *Strategy instance* — that is fine (Strategy is a plain object, not the pydantic model). But if you try to mutate the frozen **config** object, it raises `ValidationError`.
**Why it happens:** D-03 makes the *config* frozen, not the strategy. The strategy still holds mutable runtime state (`subscribed_portfolios`, `is_active`).
**How to avoid:** Keep mutable runtime state on the `Strategy` instance; read immutable declarations from `self.config`. Do not store runtime state on the config.
**Warning signs:** `ValidationError: Instance is frozen` at subscribe/activate time.

### Pitfall 3: FL-02 may already be satisfied — verify, don't blindly retype
**What goes wrong:** Re-annotating `portfolio_id` when it's already `int` is a no-op churn that risks touching frozen event files unnecessarily.
**Why it happens:** Grep confirms `SignalEvent.portfolio_id: int` (signal.py:84), `OrderEvent.portfolio_id: int` (order.py:52), `FillEvent.portfolio_id: int` (fill.py:64) are ALREADY annotated `int`. The `Order` entity still uses `"PortfolioId | int"` (order.py:55) and `order_manager.py` casts `PortfolioId`. The ROADMAP note (#10) says this is "annotation-only; may instead land in Phase 5 retype."
**How to avoid:** Confirm current state first. FL-02's event-fact retype appears DONE; the only remaining `int|PortfolioId` ambiguity is on the `Order` entity, which D-09 leaves alone (the natural-key join uses it as-is). Treat FL-02 as a verification step, not a change, unless the planner finds a residual loose annotation.
**Warning signs:** mypy --strict surfaces a new error after an unnecessary retype.

### Pitfall 4: `arbitrary_types_allowed` + mypy --strict on the config model
**What goes wrong:** pydantic accepts the frozen sizing dataclasses at runtime, but mypy --strict (`files=["itrader"]`) must also be clean on the model.
**Why it happens:** `SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent` is a union of frozen dataclasses; pydantic needs `arbitrary_types_allowed=True` to NOT try to build a core-schema for them.
**How to avoid:** Type `sizing_policy: SizingPolicy` (the union alias) directly; verified to construct cleanly. Run `mypy --strict` on the new config module. The sizing dataclasses are typed, so the union annotation is mypy-clean.
**Warning signs:** `PydanticSchemaGenerationError` (means `arbitrary_types_allowed` is missing); mypy `no-any` errors.

### Pitfall 5: `filterwarnings=["error"]` test strictness
**What goes wrong:** A pydantic deprecation warning (e.g. using a v1-style `@validator` instead of v2 `@field_validator`/`@model_validator`) becomes a test failure.
**Why it happens:** `pyproject.toml` sets `filterwarnings=["error"]` — any warning fails the suite.
**How to avoid:** Use pydantic **v2** decorators only (`@field_validator`, `@model_validator(mode="after")`, `ConfigDict` not class `Config`). The existing `config/` models are clean v2 — follow them exactly.
**Warning signs:** `PydanticDeprecatedSince20` raised as an error in any test that imports the config.

### Pitfall 6: tabs-vs-spaces per file (CLAUDE.md indentation rule)
**What goes wrong:** A mixed-indentation diff breaks a tab-indented file.
**Why it happens:** `strategy_handler/*` and `order_handler/*` use **tabs**; `core/`, `config/`, and the events package use **4 spaces**. `base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`, `strategies_handler.py` are **tabs**. New `core/ids.py` additions, the `config.py` model, and the events are **spaces**.
**How to avoid:** Match the file being edited. The NEW `strategy_handler/storage/` package — match the sibling `order_handler/storage/` style (in_memory_storage.py and base.py there use **4 spaces** despite being under a tab-handler dir; storage_factory.py also 4 spaces). Verify by reading the target file's existing indentation before editing.
**Warning signs:** `TabError`/`IndentationError` on import.

## Code Examples

### Constructing a strategy under the new contract (D-01) — the migration every call site makes
```python
# BEFORE (run_backtest.py:72)
strategy = SMA_MACD_strategy(timeframe="1d", tickers=["BTCUSD"])

# AFTER (config-object contract, D-01) — exact shape is Claude's discretion;
# a convenience classmethod on the strategy is one option to keep call sites terse:
config = SMA_MACDConfig(
    timeframe="1d",
    tickers=["BTCUSD"],
    sizing_policy=FractionOfCash(Decimal("0.95")),   # golden defaults
    direction=TradingDirection.LONG_ONLY,
    allow_increase=False,
)
strategy = SMA_MACD_strategy(config)
```
Note: the **golden sizing literal MUST be `FractionOfCash(Decimal("0.95"))`** (string-path Decimal, Pitfall 1 in `core/sizing.py`) to reproduce the byte-exact compounding. `SMA_MACD_strategy.__init__` currently hard-codes this default at lines 41-44 — preserve the exact same value when the config carries it.

### The boundary-parse collapse (D-04 / HARD-03)
```python
# BEFORE (strategies_handler.py:95)   — strategy.order_type is a "market" string
order_type=OrderType(strategy.order_type),
# AFTER                                — strategy.order_type IS the enum (from config)
order_type=strategy.order_type,
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Loose `__init__` kwargs on strategy | Single pydantic config object (`self.config`) | This phase (D-01) | Matches nautilus-trader `StrategyConfig`; single source of truth; free SIG-01 snapshot |
| Stringly-typed `order_type="market"` + boundary parse | `OrderType` enum end-to-end | This phase (D-04) | Removes a fail-late stringly-typed hole |
| Hand-written warmup guard per strategy | Framework short-circuit in handler | This phase (D-15) | nautilus `.initialized` / LEAN `SetWarmUp` contract |
| No signal persistence | Pluggable `SignalStore` + typed `SignalRecord` | This phase (SIG-01/02) | Queryable post-run; v1.3 Postgres-ready |

**Deprecated/outdated:** pydantic v1 `@validator`/class `Config` — must NOT be used (v2 only; `filterwarnings=["error"]` will fail on the deprecation).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | FL-02 (`portfolio_id: int`) is already satisfied on the SignalEvent/OrderEvent/FillEvent facts; only a verification is needed, not a change | Pitfall 3 / HARD-03 row | Low — if a residual loose annotation exists, planner adds a one-line retype; grep already confirms `int` on all three events |
| A2 | **RESOLVED (verified live):** `tests/golden/summary.json` carries `final_equity 46189.87730727451`, `trade_count 134`, `final_cash 46189.87730727451` — matching REQUIREMENTS.md HARD-04 exactly. The oracle test's in-code comment value `46132.7668` IS a stale interim note (the test asserts against the file, not the comment). | HARD-04 row | None — confirmed by reading the committed golden file |
| A3 | The e2e `SingleMarketBuy` and `_AlwaysBuyStrategy` test helpers will need migration to the config contract in THIS phase (else their `super().__init__(...)` breaks) | Runtime State Inventory | Low — confirmed they call the base `__init__` with the old signature; whether to migrate now or defer the e2e one is explicitly Claude's discretion per CONTEXT.md |
| A4 | `max_window` stays a Strategy-instance attribute (param-derived in `__init__`), read by the handler for the D-15 short-circuit | Pitfall 1 | Low — matches current code (`strategies_handler.py:80` already reads `strategy.max_window`) |

**A2 is RESOLVED (verified live). A1/A3/A4 are low-risk execution-time checks — none changes the locked decision set.**

## Open Questions

1. **Should `BaseStrategyConfig` live in `strategy_handler/config.py` or under `itrader/config/`?**
   - What we know: CONTEXT.md marks the location as Claude's discretion (D-06 also leaves the `Timeframe` enum home open). The `config/` package is for *system/portfolio/exchange* domain config; strategy config is arguably a strategy-handler concern.
   - What's unclear: which import-cycle is cleaner — `config/` imports `core/sizing` (fine), but a strategy-config in `config/` would couple the config package to the strategy vocabulary.
   - Recommendation: put `BaseStrategyConfig` in `strategy_handler/` (e.g. `strategy_handler/config.py` or in `base.py`) to keep the strategy vocabulary co-located and avoid widening the `config/` package's dependency surface. Put `SMA_MACDConfig` next to its strategy in `strategies/`.

2. **Where does the `Timeframe` enum live and what is the exact vocabulary?**
   - What we know: D-06 supported set example is `1m/5m/15m/1h/4h/1d/1w`; conversion stays via `to_timedelta` which accepts `d/h/m/w` (case-insensitive) and rejects month.
   - What's unclear: whether to use a strict `Enum` or a `Literal[...]` — and whether to constrain to exactly the example set or all `to_timedelta`-parseable strings.
   - Recommendation: a `Timeframe` `Enum` in `core/enums/` (house pattern, with `_missing_` case-insensitive parse) constrained to the fixed-duration vocabulary; the base still calls `to_timedelta(config.timeframe.value)`. The golden run uses `"1d"` — keep `1d` valid and verify byte-exact.

3. **Does `SignalRecord.action` use `Side` (BUY/SELL) like `SignalIntent`?**
   - What we know: `SignalIntent.action` is `Side`; SIG-01 says "action".
   - Recommendation: use `Side` for type-consistency with `SignalIntent`/`SignalEvent`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pydantic | HARD-01/02 config model | ✓ | 2.13.4 | — |
| uuid-utils | SignalId (D-10) | ✓ (per CLAUDE.md ^0.16.0) | 0.16.x | — |
| pandas | golden run + `generate_signal` | ✓ | ^2.3.3 | — |
| ta | SMA_MACD indicators | ✓ | ^0.11.0 | — |
| pytest | golden gate + unit tests | ✓ | ^8.4.2 | — |
| Poetry / Python 3.13 | run environment | ✓ | 3.13.1 | — |

**Missing dependencies:** None. All required tooling is already in `pyproject.toml`. No new install step in this phase.

## Validation Architecture

> nyquist_validation is not explicitly false in config — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (minversion 8.0) under Poetry, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/strategy/test_strategy.py -x` |
| Full suite command | `make test` (or `poetry run pytest`) |
| Golden gate | `poetry run pytest tests/integration/test_backtest_oracle.py -x` (the byte-exact HARD-04 guard) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-01 | config validates engine-facing declarations (bad timeframe/negative window raises) | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -k config -x` | ❌ Wave 0 (new config-validation tests) |
| HARD-02 | `short_window >= long_window` raises; positivity enforced | unit | `poetry run pytest tests/unit/strategy/ -k validator -x` | ❌ Wave 0 |
| HARD-03 | `order_type` is `OrderType` enum; no string path; `strategies_handler` emits enum directly | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -x` | ✅ (existing fan-out tests cover the emit path; add an enum-type assertion) |
| HARD-04 | SMA_MACD golden byte-exact (134 trades / final_equity) | integration/slow | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ existing |
| SIG-01 | `SignalRecord` carries all fields incl. config snapshot | unit | `poetry run pytest tests/unit/strategy/ -k signal_record -x` | ❌ Wave 0 |
| SIG-02 | store queryable `get_all`/`by_strategy`/`by_ticker`; post-run accessor returns records for the golden run | unit + integration | `poetry run pytest tests/unit/strategy/ -k signal_store -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/strategy/test_strategy.py -x` (fast) + the relevant new unit file.
- **Per wave merge:** `poetry run pytest tests/integration/test_backtest_oracle.py -x` (the byte-exact gate) + `make test-strategy`.
- **Phase gate:** Full suite green (`make test`) + `mypy --strict` clean + `test_backtest_oracle.py` byte-exact before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_strategy_config.py` — HARD-01/HARD-02 config validation (good defaults, bad timeframe, negative windows, `short>=long`).
- [ ] `tests/unit/strategy/test_signal_store.py` — SIG-01/SIG-02 (`SignalRecord` fields, store `add`/`get_all`/`by_strategy`/`by_ticker`, snapshot serialization via `model_dump`).
- [ ] An integration assertion that the golden SMA_MACD run produces a non-empty, queryable `SignalStore` via the `TradingSystem` accessor (SIG-02 post-run inspection).
- [ ] Migrate existing strategy-construction call sites (`test_strategy.py`, `test_backtest_smoke.py`, `test_reservation_inertness.py`) to the config contract — these are EDITS to existing tests, gated by the golden master.
- Framework install: none — pytest already present.

## Security Domain

This phase is a pure in-process backtest-engine refactor: no authentication, sessions, access control, network I/O, untrusted input, or cryptography on the touched path. Strategy config is constructed by the developer/test author, not from untrusted external input. The only relevant control is **V5 input validation at the config boundary** — satisfied by pydantic `Field` constraints + `@model_validator` (HARD-01/02), which fail loudly on invalid declarations.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes (config boundary) | pydantic `BaseStrategyConfig` validators (HARD-01/02) |
| V6 Cryptography | no | UUIDv7 ids are identity, not secrets |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Invalid/contradictory strategy declarations (e.g. short>=long) | Tampering (misconfiguration) | fail-loud pydantic validation at construction |
| Float-money artifact in sizing literal | Information disclosure (numeric corruption) | string-path `Decimal("…")` (core/sizing Pitfall 1) — preserved, not changed |

## Sources

### Primary (HIGH confidence)
- Codebase (read in full): `strategy_handler/base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`, `strategies_handler.py`; `events_handler/events/signal.py`; `core/ids.py`, `core/sizing.py`, `core/enums/order.py`, `core/enums/trading.py`, `core/enums/__init__.py`; `order_handler/base.py` (OrderStorage ABC), `order_handler/storage/in_memory_storage.py`, `order_handler/storage/storage_factory.py`, `order_handler/order.py`, `order_manager.py` (grep); `config/system.py`, `config/portfolio.py`, `config/__init__.py`; `outils/time_parser.py`, `outils/id_generator.py`; `trading_system/backtest_trading_system.py`; `scripts/run_backtest.py`; `tests/integration/test_backtest_oracle.py`; `tests/unit/strategy/test_strategy.py`; `tests/e2e/strategies/single_market_buy.py`.
- Live verification: `poetry run python -c "import pydantic; print(pydantic.VERSION)"` → **2.13.4**; pydantic frozen + `arbitrary_types_allowed` + frozen-dataclass construction + `model_dump()` recursion — **verified live**.
- `.planning/phases/05-.../05-CONTEXT.md` (locked decisions D-01..D-15), `.planning/REQUIREMENTS.md` (HARD/SIG), `.planning/ROADMAP.md` (Phase 5 success criteria), CLAUDE.md.

### Secondary (MEDIUM confidence)
- ROADMAP note #10 on FL-02 portfolio_id annotation carry-over (informs Pitfall 3 / A1).

### Tertiary (LOW confidence)
- None — all claims grounded in the codebase or live verification. External pattern references (nautilus-trader `StrategyConfig`, LEAN `SetWarmUp`) are cited in CONTEXT.md as design rationale, not used as factual API claims here.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in the repo; pydantic version + behavior live-verified.
- Architecture: HIGH — every pattern (config, storage seam, id type, entity-vs-event) read directly from existing repo code; decisions fully locked by CONTEXT.md.
- Pitfalls: HIGH — derived from the exact code (indentation rule, frozen-config trap, warmup boundary, filterwarnings) and the live golden gate mechanics.

**Research date:** 2026-06-09
**Valid until:** stable (~30 days) — this is an in-repo refactor with no external moving parts; the only volatility is the live golden `summary.json` value (read it at execution time, A2).
