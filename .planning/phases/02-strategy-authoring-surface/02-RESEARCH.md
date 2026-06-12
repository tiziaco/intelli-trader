# Phase 2: Strategy Authoring Surface - Research

**Researched:** 2026-06-12
**Domain:** Python class-attribute introspection / coercion engine; strategy authoring API; byte-exact brownfield migration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01..D-13, verbatim)

**Config-layer fate & blast radius**
- **D-01:** Full delete of the config layer. Remove `config/strategy.py` (`BaseStrategyConfig`), `SMA_MACDConfig` (in `strategies/SMA_MACD_strategy.py`), and `EmptyStrategyConfig` (in `strategies/empty_strategy.py`). The class-attribute surface fully replaces them — no dead dual-path. Drop the `config/__init__.py` re-export of `BaseStrategyConfig`.
- **D-02:** The base `__init__` signature changes from `(name, config)` to a class-attribute + `**kwargs` surface. This is an all-or-broken change: every construction site migrates this phase (see D-05).
- **D-03:** `to_dict()` and `__str__`/`__repr__` read real instance attributes (`self.timeframe`, `self.sizing_policy`, `self.order_type`, …) directly — drop all `self.config` references. Keep the serialized shape byte-identical where it is observed downstream (signal store snapshot, any e2e snapshot). `name` and `strategy_id` derivation: Claude's discretion — a sensible default `name` (e.g. class name or a `name` class attr) is fine; `strategy_id` still minted per construction by `idgen` as today.
- **D-04:** `SignalRecord.config: BaseStrategyConfig` → a plain params snapshot dict captured from the strategy's declared attrs at decision time (e.g. `strategy.to_dict()` / `params_snapshot()`). The `config.model_dump()` read-edge callers become dict accessors. Preserves SIG-02 queryability without pydantic. `signal_record.py` field retyped; `test_signal_store.py` (`record.config is strategy.config` + `model_dump()`) updated to assert the dict shape.
- **D-05:** Migrate ALL construction sites this phase, byte-exact — `SMAMACDStrategy` + `EmptyStrategy` (in-scope, mypy-strict), the e2e fixtures `scripted_emitter.py` + `single_market_buy.py`, all unit/integration tests that construct a strategy, `scripts/run_backtest.py`, and any cross-val script. Mechanical authoring swap — e2e 58/58 + oracle stay byte-exact. No compatibility shim. `test_strategy_config.py` largely tests `BaseStrategyConfig` behavior that is going away — rewrite it to test the new class-attribute surface rather than deleting coverage.

**Validation mechanism & cross-field rules**
- **D-06:** Pure-python introspection — no pydantic. Base inspects its own + subclass `__annotations__`/class attrs, applies `**kwargs` overrides, coerces the known enum fields, raises `UnknownParamError` on unknown kwargs and on missing-required. Keeps mypy seeing real annotated attrs.
- **D-07:** Bare annotation = required. A name in `__annotations__` with no class-attr value is required (must arrive via `**kwargs` or be pinned by a subclass) — `timeframe`, `tickers`, `sizing_policy` on the base. Missing → raise loudly. Subclass alpha knobs carry literal defaults (`short_window: int = 50`) and are optional.
- **D-08:** Enum coercion on the known engine fields, driven off their annotations: `timeframe` str→`Timeframe`, `order_type` str→`OrderType`, `direction` str→`TradingDirection`. Subclass int/Decimal knobs are not coerced.
- **D-09:** Drop the pydantic `Field(gt=0)` constraints and the `@model_validator`, but provide an optional overridable `validate()` hook (run after kwargs apply + coerce). `SMAMACDStrategy` keeps its `short_window < long_window` assert (HARD-02 loud-rejection) via that hook.

**init() lifecycle hook (Phase 2 scope)**
- **D-10:** Phase 2 introduces `init()` as an overridable lifecycle hook called at the end of construction (after kwargs applied + validated), structured to be re-runnable/idempotent — the seam Phase 3 and Phase 4 consume. SMA_MACD's `init()` is empty/no-op for now; indicators stay inline in `generate_signal` and `max_window`/`warmup` stay hand-set class attrs until Phase 3.
- **D-11:** Build the re-runnable seam + a light idempotency test — call `init()` twice and assert identical resulting state. Do NOT build the full reconfig pipeline beyond the per-strategy method (D-12).

**Reconfigure surface (Phase 2 vs Phase 4 boundary)**
- **D-12:** Ship a strategy-level `reconfigure(**kwargs)` (a.k.a. `update_params`) now: re-apply + coerce kwargs → re-validate (`validate()` hook) → re-run `init()`. Single-strategy scope only — no handler/queue wiring this phase.
- **D-13:** No runtime mutation guard. Do not add a `__setattr__` guard. Rely on the documented "reconfigure via the sanctioned method only" discipline + the `reconfigure` method as the blessed path.

### Claude's Discretion
- `name` / `strategy_id` derivation details (D-03) — default `name` source and whether a `name` class attr is introduced.
- Exact indicator-handle / snapshot-dict key shape for `to_dict()`/`params_snapshot()` (D-04), subject to keeping observed serialized shapes byte-identical.
- Precise `validate()` hook signature/placement (D-09) and how the SMA_MACD `short<long` assert is expressed within it.
- Internal structure of the introspection/coercion engine (D-06) as long as it stays mypy-strict and byte-exact.

### Deferred Ideas (OUT OF SCOPE)
- Auto-derived `warmup`/`max_window` from indicator recipes → Phase 3 (IND-01). Phase 2 keeps them hand-set.
- Declared-indicator framework, model-B pre-eval reads (`self.short_sma[-1]`), free-function `crossover`/`crossunder` → Phase 3 (IND-01).
- Handler-level uniform `update_config` on `StrategiesHandler` → Phase 4 (COMP-02). Phase 2 ships only the per-strategy `reconfigure` method it will call.
- Indicator handle type (raw Series vs wrapper) → Phase 3 spec-time.
- SMA_MACD full migration onto the indicator framework → Phase 3.
- Indicator-based SL/TP → future phase (percent-offset stays).
- Stateful/incremental indicator backends (IND-02) → deferred (byte-exactness risk).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRAT-01 | Replace frozen-pydantic-config + manual-copy strategy authoring with real annotated class-attribute declarations introspected at construction; `**kwargs` overrides; reject unknown/missing-required; idempotent `init()` seam; per-strategy `reconfigure(**kwargs)`; `validate()` hook | This document — the introspection/coercion engine algorithm (§Architecture Pattern 1-3), enum-coercion mechanics (§Pattern 2), `UnknownParamError` placement (§Pattern 4), idempotent `init()`/`reconfigure` (§Pattern 5-6), D-04 snapshot dict (§Pattern 7), and the byte-exact migration risk map (§Common Pitfalls + §Byte-Exact Migration Risk Map). |
</phase_requirements>

## Summary

This is a **pure-stdlib introspection** phase. There is no library to add, no version to verify, no package to audit — the entire engine is `typing.get_type_hints()` + MRO walking + a tiny coercion table + `setattr`. The risk is not "will the library work" but "will the mechanical authoring swap stay byte-exact against the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) and the 58 frozen e2e goldens." Every finding here is verified against the **actual code in the repo**, not training data.

The single most load-bearing discovery: **`self.timeframe` is type-overloaded across three consumers and must NOT become a bare `Timeframe` enum on the instance**. The base currently stores `self.timeframe = to_timedelta(config.timeframe.value)` — a `timedelta`. The handler (`check_timeframe`, `feed.window`, `min_timeframe = min(...)`) and `SMA_MACD.generate_signal` (`last_time - self.timeframe * self.short_window`) all consume the **timedelta**, not the enum. The design note's `timeframe: Timeframe` class-attr is the **declared/coerced** form; the instance must still resolve it to a `timedelta`. Collapsing these breaks both the handler's alignment check and SMA's slice arithmetic — silently changing which ticks fire and therefore the trade count. This is the #1 byte-exactness trap.

Second key finding: **no module in the blast radius uses `from __future__ import annotations`** (verified by grep). Annotations are real runtime type objects, so `typing.get_type_hints(cls)` resolves cleanly across the full MRO with zero forward-ref/string-annotation hazard. This is the cleanest, mypy-strict-safe introspection primitive — strongly preferred over hand-walking `__annotations__`.

**Primary recommendation:** Build the engine as a private `Strategy._apply_params(**kwargs)` classmethod-style helper shared by `__init__` and `reconfigure`. Drive required-detection and coercion off `get_type_hints(type(self))` + a fixed `_COERCE: dict[str, type[Enum]]` table for the three engine enums. Keep `self.timeframe` resolved to a `timedelta` (store the enum separately, e.g. `self._timeframe_enum` or a `timeframe_alias`, for serialization). Place `UnknownParamError`/`MissingParamError` in `core/exceptions/strategy.py` (new module) subclassing `ValidationError`. Migrate every construction site to the kwargs surface byte-exact; the oracle and e2e goldens are the gate.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Param declaration (class attrs + annotations) | Strategy ABC (`strategy_handler/base.py`) | concrete strategy subclass | The base owns engine-facing names; the subclass pins/adds alpha knobs. D-06/D-07. |
| Introspection + coercion + kwargs override | Strategy ABC | `core/enums` (coercion targets), `core/exceptions` (errors) | One engine, shared by `__init__`/`reconfigure`. Pure stdlib; no cross-domain reach. |
| `init()` / `validate()` / `reconfigure` hooks | Strategy ABC | concrete strategy (overrides) | Lifecycle seam owned by the base; SMA_MACD overrides `validate()`. D-09/D-10/D-12. |
| Param snapshot dict (`to_dict`/`params_snapshot`) | Strategy ABC | `signal_record.py` (consumer), `strategies_handler.py` (capture site) | Serialization edge; the handler snapshots it into `SignalRecord`. D-04. |
| Timeframe resolution (enum → timedelta) | Strategy ABC `__init__` | `outils/time_parser.to_timedelta` | The instance must carry a `timedelta` for the handler + SMA slice arithmetic. |
| Warmup short-circuit / fan-out / SignalEvent build | `StrategiesHandler` | — | UNCHANGED this phase (#24 boundary). Only the `config=` capture arg changes (D-04). |

## Standard Stack

**No external packages are added, removed, or upgraded in this phase.** The engine is built entirely from the Python standard library and existing in-repo modules.

### Core (stdlib + in-repo, all already present)
| Module | Purpose | Why Standard |
|--------|---------|--------------|
| `typing.get_type_hints` | Resolve merged MRO annotations to real type objects | The canonical, MRO-aware way to read declared attrs; resolves across base+subclass in one call. Verified working on the repo's class shapes. |
| `enum` (`Enum._missing_`) | str→enum coercion for `timeframe`/`order_type`/`direction` | The three target enums already implement case-insensitive `_missing_` (M2-07). Calling `Timeframe("1d")` is the existing coercion path. |
| `itrader.outils.time_parser.to_timedelta` | `Timeframe.value` → `timedelta` for the instance | Already the path the base uses today (`to_timedelta(config.timeframe.value)`). Keep it. |
| `itrader.core.exceptions.base.ValidationError` | Base class for `UnknownParamError`/`MissingParamError` | The established exception convention (structured `field`/`value`/`message`). |
| `itrader.core.sizing` (`FractionOfCash`, `SizingPolicy`, …) | Typed class-attr values | Frozen dataclasses — safe to share as class-level defaults (immutable, no mutable-default aliasing hazard). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `typing.get_type_hints(cls)` | Hand-walk `cls.__mro__` reading each `__annotations__` | More code, must re-implement MRO merge ordering + override precedence. `get_type_hints` does it correctly and resolves real types. Only switch if a forward-ref breaks it (none exist — no `from __future__ import annotations`). |
| `dataclasses` for the base | A `@dataclass` Strategy base | Rejected by design — the design note wants class-attribute declarations mypy sees directly, plus required-from-bare-annotation semantics (D-07) that dataclasses don't express (a bare annotation in a dataclass with no default is a required `__init__` arg, but the base isn't a dataclass and mixing frozen-dataclass policy values complicates it). Pure ABC + manual `setattr` is cleaner and matches the design note. |
| pydantic (current) | keep pydantic config | Explicitly deleted (D-01/D-06). |

**Installation:** None — no dependency changes.

## Package Legitimacy Audit

> Not applicable. This phase installs **zero** external packages. The engine is built from the Python standard library (`typing`, `enum`) and existing in-repo modules. No registry verification, slopcheck, or postinstall audit is required.

## Architecture Patterns

### System Architecture Diagram

```
                    Author writes a class
                           │
            class SMAMACDStrategy(Strategy):
              sizing_policy = FractionOfCash("0.95")   ← class-attr value (default)
              short_window: int = 50                    ← annotated + default (optional)
              def validate(self): assert short<long     ← D-09 hook
              def init(self): ...                        ← D-10 no-op hook
                           │
                           ▼
        s = SMAMACDStrategy(tickers=[...], timeframe="1d", short_window=30)
                           │  **kwargs
                           ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ Strategy.__init__  (and reconfigure shares the same engine)   │
   │                                                               │
   │  1. hints = get_type_hints(type(self))      ← merged MRO      │
   │  2. for each declared name:                                   │
   │       value = kwargs.pop(name, <class-attr default or MISSING>)│
   │       if MISSING → MissingParamError (bare annotation, D-07)  │
   │  3. if kwargs remain → UnknownParamError (D-06)               │
   │  4. coerce: name in _COERCE → enum(value)  (D-08, str→enum)   │
   │  5. setattr(self, name, value)                                │
   │  6. resolve self.timeframe = to_timedelta(tf_enum.value)      │ ← KEEP timedelta!
   │  7. strategy_id = idgen.generate_strategy_id()                │
   │  8. self.validate()    ← D-09 cross-field hook                │
   │  9. self.init()        ← D-10 idempotent lifecycle hook       │
   └─────────────────────────────────────────────────────────────┘
                           │
                           ▼
       self.short_window (real typed attr) ← generate_signal reads this (D-12)
       self.timeframe (timedelta)          ← handler check_timeframe / SMA slice
       to_dict()/params_snapshot()         ← handler captures into SignalRecord (D-04)
```

### Recommended Module Layout

```
itrader/
├── strategy_handler/
│   ├── base.py                  # Strategy ABC: introspection engine + init/validate/reconfigure hooks
│   └── strategies/
│       ├── SMA_MACD_strategy.py # class-attr declarations + validate() (short<long) + no-op init()
│       └── empty_strategy.py    # class-attr declarations only
├── core/
│   └── exceptions/
│       └── strategy.py          # NEW: UnknownParamError, MissingParamError (subclass ValidationError)
```

### Pattern 1: MRO-aware required-detection + kwargs override (D-06/D-07)

**What:** Walk merged annotations; a name with a class-attr value is optional (default = that value), a name with only an annotation is required.

**When to use:** Once, in the shared `_apply_params` engine called by `__init__` and `reconfigure`.

**Mechanics (verified in this session against the repo's class shapes):**

```python
# Source: verified via stdlib probe in this research session.
from typing import get_type_hints

# get_type_hints merges the FULL MRO into one dict, base keys first, then
# subclass keys; later (subclass) annotations override earlier ones.
hints = get_type_hints(type(self))   # {'timeframe': Timeframe, 'tickers': list[str],
                                      #  'sizing_policy': SizingPolicy, 'short_window': int, ...}

# Class-attr DEFAULT detection: a declared name is "required" iff NO class in the
# MRO supplies a value for it. hasattr(type(self), name) is the simplest correct test
# (it climbs the MRO). Distinguish from "annotation only":
_MISSING = object()
for name in hints:
    default = getattr(type(self), name, _MISSING)   # class-attr value or sentinel
    if name in kwargs:
        value = kwargs.pop(name)
    elif default is not _MISSING:
        value = default                              # optional — use the class default
    else:
        raise MissingParamError(name)                # D-07 bare annotation = required
    ...
```

**Verified MRO behavior** (probe output this session): for `class A: x:int=1; req:str` and `class B(A): y:float=2.0`, `get_type_hints(B)` returns `{'x': int, 'req': str, 'y': float}` (full merge), `B.__annotations__` is only `{'y': float}` (own-only). `hasattr(B, 'x')` is True (default exists), `hasattr(B, 'req')` is False (bare annotation = required). This is exactly the D-07 semantics.

**Why `get_type_hints` over `__annotations__`:** raw `__annotations__` is own-class-only, forcing a manual MRO walk + merge. `get_type_hints` does the merge and resolves string/forward annotations to real types. Confirmed safe here because **no blast-radius module uses `from __future__ import annotations`** (grep verified) — but `get_type_hints` would handle it even if one did.

### Anti-Patterns to Avoid
- **Collapsing `self.timeframe` to the enum.** The handler and SMA slice need a `timedelta`. Store the resolved timedelta on `self.timeframe`; keep the enum/alias separately for serialization (see Pitfall 1).
- **Mutable class-attr defaults that alias across instances.** `tickers: list[str]` has no class-attr default (it's required, D-07), so no aliasing — but be careful if any subclass ever pins a mutable default (e.g. `tickers = ["BTCUSD"]` at class level shared by every instance). The frozen-dataclass policy values (`FractionOfCash(...)`) are immutable and safe to share. If a mutable default is ever introduced, copy it per-instance.
- **Coercing non-enum knobs.** Only `timeframe`/`order_type`/`direction` coerce (D-08). `short_window: int` arriving as `"50"` must NOT be silently `int()`-ed — leave it; a wrong type is the author's bug, surfaced by mypy on the in-scope reference strategy.
- **Reading `__annotations__` for class-attr-value detection.** Annotations tell you the declared *names/types*, not whether a *value* exists. Use `hasattr`/`getattr` for value presence.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Merge base+subclass annotations across MRO | A manual `for klass in cls.__mro__` loop merging `__annotations__` | `typing.get_type_hints(cls)` | Stdlib does the merge + override-precedence + real-type resolution correctly; hand-rolling re-introduces ordering bugs. |
| str→enum coercion with clear error | A custom string-match / dict lookup | The enum's existing `_missing_` (`Timeframe("1d")`, `OrderType("market")`, `TradingDirection("long_only")`) | All three already have case-insensitive `_missing_` raising a clear `ValueError`. Reuse it. |
| Timeframe string→timedelta | New parsing | `outils.time_parser.to_timedelta` | Already the path the base uses; handles d/h/m/w + month-rejection. |
| Structured validation error | A bare `raise ValueError` | `ValidationError` subclass in `core/exceptions/strategy.py` | The house exception convention carries `field`/`value`/`message`. |

**Key insight:** This phase is "wire stdlib primitives together," not "build a validation framework." The temptation is to re-create pydantic-lite; resist it. Every primitive already exists.

## Runtime State Inventory

> This is a brownfield refactor/migration phase — but it touches **code only**, no persisted runtime state. All five categories verified below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None.** Strategy params are never persisted to a datastore — `SignalRecord.config` lives only in the in-memory `InMemorySignalStore` (rebuilt per run); the SQL signal store is not on the backtest path. The BTCUSD CSV is read-only input, not strategy state. | code edit only |
| Live service config | **None.** No external service stores strategy params. Live trading (`my_strategies/`, `LiveTradingSystem`) is out of the in-scope mypy set and not migrated this phase. | none |
| OS-registered state | **None.** No OS-level registration of strategy config. | none |
| Secrets/env vars | **None.** `Settings(env_prefix="ITRADER_")` carries DB/exchange creds, not strategy params. Untouched. | none |
| Build artifacts | **None new.** Deleting `config/strategy.py` removes a source module; `.pyc` caches under `__pycache__/` regenerate automatically. No installed-package egg-info references `BaseStrategyConfig`. | none (caches self-heal) |

**The canonical question — "after every file is updated, what runtime systems still have the old shape cached?"** Answer: only Python bytecode caches (`__pycache__`), which Poetry/pytest regenerate. There is no out-of-repo state. This is a pure code migration.

## Common Pitfalls

### Pitfall 1: `self.timeframe` type collision (timedelta vs enum) — the #1 oracle risk
**What goes wrong:** The design note declares `timeframe: Timeframe`. If `__init__` does `setattr(self, "timeframe", Timeframe.D1)` (the coerced enum) and stops there, three consumers break:
- `StrategiesHandler.calculate_signals` → `check_timeframe(event.time, strategy.timeframe)` expects `timedelta` (`_aligned` calls `tf.total_seconds()`).
- `StrategiesHandler.add_strategy` → `min_timeframe = min(self.min_timeframe, strategy.timeframe)` compares timedeltas.
- `SMA_MACD.generate_signal` → `last_time - self.timeframe * self.short_window` multiplies a timedelta by an int.

An enum has no `.total_seconds()` and can't be multiplied — but worse, if a `timedelta`-typed default somehow slipped through it could *silently* shift the alignment grid and change which ticks fire → different trade count.

**Why it happens:** The "declared" form (`Timeframe`, the D-08 coercion target) and the "resolved runtime" form (`timedelta`, what the engine consumes) are different. The current code already separates them: `self.timeframe = to_timedelta(config.timeframe.value)`.

**How to avoid:** After coercing the kwarg to a `Timeframe` enum, **resolve it to a timedelta before storing on `self.timeframe`** — i.e. `self.timeframe = to_timedelta(tf_enum.value)`. Keep the enum (or its `.value` alias string, e.g. `"1d"`) in a separate attr for `__str__`/`to_dict()` serialization (the current `__str__` uses `self.config.timeframe.value`, which must become a real instance attr like `self.timeframe_alias` or a stashed enum). This is the most important byte-exactness move in the phase.

**Warning signs:** `AttributeError: 'Timeframe' object has no attribute 'total_seconds'` at first BAR; or the oracle trade count drifting from 134.

### Pitfall 2: Dropped mutation guard, mutable surface (D-13)
**What goes wrong:** The old frozen pydantic config made `strategy.x = ...` raise. The new plain-attribute surface is mutable. A direct `strategy.short_window = 30` partially applies (skips re-`init()` / re-`validate()`).
**Why it happens:** Mutability is what *enables* runtime reconfig (D-12), so a hard guard is deliberately not added (D-13).
**How to avoid:** Document "reconfigure only via `reconfigure(**kwargs)`" and ship that method as the blessed path. The discipline replaces the guard.
**Warning signs:** A param changed without warmup/validate re-running.

### Pitfall 3: `to_dict()` shape drift on observed snapshots (D-03/D-04)
**What goes wrong:** Changing `to_dict()` keys/order breaks the tests that assert the snapshot, and could change `SignalRecord.config` shape.
**Why it happens:** D-03 rewrites `to_dict()` to read instance attrs; D-04 retypes `SignalRecord.config` to a plain dict.
**How to avoid:** `to_dict()` is **NOT consumed by any frozen e2e golden** (verified — e2e goldens are `trades.csv`/`summary.json` built from `Position.to_dict()`, not strategy serialization). The only observers are the unit/integration tests that assert `record.config` (`test_signal_store.py` line 171-173, `test_backtest_oracle.py` line 303). Those tests are explicitly in the migrate-set (D-05) and become dict-shape assertions. So shape changes are safe **as long as the migrated tests are updated in lockstep**. Keep the existing `to_dict()` key set (`strategy_id`, `strategy_name`, `subscribed_portfolios`, `order_type`, `is_active`, `sizing_policy`, `direction`, `allow_increase`, `max_positions`, `sltp_policy`) to minimize churn; add the alpha knobs to `params_snapshot()` if a richer snapshot is wanted.

### Pitfall 4: `string-path Decimal` literals (carried project pitfall)
**What goes wrong:** A class-attr default `sizing_policy = FractionOfCash(Decimal(0.95))` (float path) carries a binary-repr artifact and breaks byte-exactness.
**How to avoid:** Every Decimal literal enters via the string path: `FractionOfCash(Decimal("0.95"))`. The golden literal is already string-path everywhere (verified in run_backtest.py, all fixtures). Preserve it verbatim when moving it to a class attr.

### Pitfall 5: `name` / `strategy_id` derivation drift (D-03)
**What goes wrong:** The current base takes `name` as a constructor arg (`super().__init__("SMA_MACD", config)`). Removing the `(name, config)` signature means `name` must come from somewhere — a class attr, the class name, or a kwarg. `__str__` returns `f'{self.name}_{self.config.timeframe.value}'`; tests assert `strategy.name`. If `name` changes value, any test asserting it (or `__str__`) drifts.
**How to avoid:** Introduce a `name` class attr defaulting to the class name (or keep the literal string per strategy). `strategy_id` stays minted per construction via `idgen.generate_strategy_id()` (unchanged). Confirm no frozen golden depends on the literal `name` string (verified: e2e goldens don't serialize strategy name; unit tests assert `strategy.strategy_id`, not `.name`, for identity).

### Pitfall 6: `filterwarnings=["error"]` + `--strict-markers`
**What goes wrong:** Any new warning (e.g. a pydantic deprecation surfacing during the transitional period, or a `DeprecationWarning` from `get_type_hints` on exotic types) fails the suite.
**How to avoid:** The engine is plain stdlib — no warnings expected. But run `make test-strategy` early and watch for warning-as-error failures. Every test marker must be declared (`unit`/`integration`/`slow`/`e2e` only).

## Code Examples

### Engine skeleton (shared by `__init__` and `reconfigure`)
```python
# Source: synthesized from the converged design note + verified repo mechanics.
# itrader/strategy_handler/base.py  (TABS in this file — match it)
from enum import Enum
from typing import Any, get_type_hints

from itrader.core.enums import OrderType, TradingDirection, Timeframe
from itrader.core.exceptions.strategy import UnknownParamError, MissingParamError
from itrader.outils.time_parser import to_timedelta
from itrader import idgen

_MISSING = object()
# D-08: only these three engine fields coerce str -> enum, off their annotation.
_COERCE: dict[str, type[Enum]] = {
    "timeframe": Timeframe,
    "order_type": OrderType,
    "direction": TradingDirection,
}

class Strategy(ABC):
    # base-owned engine-facing names (annotations drive required-detection, D-07)
    timeframe: Timeframe          # required — no class-attr value
    tickers: list[str]            # required
    sizing_policy: SizingPolicy   # required
    order_type     = OrderType.MARKET
    direction      = TradingDirection.LONG_ONLY
    allow_increase = False
    max_positions  = 1
    sltp_policy: SLTPPolicy | None = None
    max_window: int = 0
    warmup: int = 0
    name: str = "strategy"        # D-03 discretion: default name (class can pin)

    def __init__(self, **kwargs: Any) -> None:
        self.strategy_id = StrategyId(idgen.generate_strategy_id())
        self.is_active = True
        self.subscribed_portfolios: list[PortfolioId | int] = []
        self._apply_params(**kwargs)   # required/unknown/coerce + setattr
        self.validate()                # D-09 hook
        self.init()                    # D-10 idempotent hook

    def _apply_params(self, **kwargs: Any) -> None:
        hints = get_type_hints(type(self))
        for nm in hints:
            default = getattr(type(self), nm, _MISSING)
            if nm in kwargs:
                val = kwargs.pop(nm)
            elif default is not _MISSING:
                val = default
            else:
                raise MissingParamError(nm)
            coerce = _COERCE.get(nm)
            if coerce is not None and not isinstance(val, coerce):
                val = coerce(val)      # uses the enum's _missing_ (str -> enum)
            setattr(self, nm, val)
        if kwargs:
            raise UnknownParamError(sorted(kwargs))
        # Pitfall 1: resolve the enum to a timedelta for the engine consumers,
        # keep the alias for serialization.
        self.timeframe_alias = self.timeframe.value     # e.g. "1d"
        self.timeframe = to_timedelta(self.timeframe.value)  # timedelta on the instance

    def validate(self) -> None:        # D-09 overridable hook (no-op default)
        ...

    def init(self) -> None:            # D-10 overridable idempotent hook (no-op default)
        ...

    def reconfigure(self, **kwargs: Any) -> None:  # D-12
        # re-apply + coerce -> re-validate -> re-run init (idempotent)
        self._apply_params(**kwargs)
        self.validate()
        self.init()
```
*(Note: the `_apply_params` above mutates `self.timeframe` in place; in the real implementation reconfigure must re-coerce from the alias or accept that a second call without a `timeframe` kwarg re-reads the already-resolved timedelta — handle by storing the enum, not overwriting it, OR by gating the resolve. See Open Question 1.)*

### `validate()` hook on SMA_MACD (D-09)
```python
# itrader/strategy_handler/strategies/SMA_MACD_strategy.py (TABS)
class SMAMACDStrategy(Strategy):
    name = "SMA_MACD"
    sizing_policy = FractionOfCash(Decimal("0.95"))   # string-path literal (Pitfall 4)
    direction     = TradingDirection.LONG_ONLY
    short_window: int = 50
    long_window:  int = 100
    fast_window:  int = 6
    slow_window:  int = 12
    signal_window: int = 3
    max_window: int = 100
    warmup: int = 100

    def validate(self) -> None:
        # HARD-02 cross-field rule, was the pydantic @model_validator.
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")

    def init(self) -> None:   # no-op in Phase 2 (D-10); indicators stay inline
        ...
```

### Light idempotency test (D-11)
```python
# tests/unit/strategy/test_strategy.py (4-space — tests house style)
def test_init_is_idempotent():
    s = SMAMACDStrategy(tickers=["BTCUSD"], timeframe="1d")
    before = s.params_snapshot()      # or to_dict()
    s.init()                          # call the hook a second time
    after = s.params_snapshot()
    assert before == after            # identical resulting state
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Frozen pydantic `SMA_MACDConfig(BaseStrategyConfig)` + manual field-copy | Annotated class-attribute declarations introspected at construction | This phase (STRAT-01) | Less ceremony; mypy sees real attrs; override-at-construction reuse model. |
| `(name, config)` constructor | `**kwargs` constructor with required/unknown detection | This phase (D-02) | All-or-broken migration of every construction site. |
| `@model_validator(mode="after")` cross-field rule | `validate()` overridable hook | This phase (D-09) | Same loud-reject behavior, no pydantic. |
| `SignalRecord.config: BaseStrategyConfig` + `model_dump()` | plain `dict` snapshot via `to_dict()`/`params_snapshot()` | This phase (D-04) | Queryability preserved without pydantic. |

**Deprecated/outdated in this phase:**
- `itrader/config/strategy.py` (`BaseStrategyConfig`) — deleted (D-01).
- `SMA_MACDConfig`, `EmptyStrategyConfig` — deleted (D-01).
- `config/__init__.py` re-export of `BaseStrategyConfig` — removed (line 56 + line 100).

## Byte-Exact Migration Risk Map

Ranked by likelihood of perturbing the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) or the 58 e2e goldens:

| Risk | Mechanism | Mitigation | Oracle-visible? |
|------|-----------|------------|-----------------|
| **`self.timeframe` becomes enum not timedelta** | Breaks `check_timeframe` alignment + SMA slice arithmetic → different firing ticks | Resolve to `timedelta` on the instance (Pitfall 1) | YES — changes trade count |
| **Decimal float-path in a class-attr default** | `FractionOfCash(Decimal(0.95))` carries binary artifact | String-path literal verbatim (Pitfall 4) | YES — changes sizing |
| **`max_window`/`warmup` value drift** | Hand-set values changed during the swap → different warmup short-circuit tick | Keep `max_window=100`, `warmup=100` on SMA_MACD exactly (verified current values) | YES — changes firing tick |
| **Attribute read ORDER in `generate_signal`** | SMA_MACD reads `self.short_window`, `self.long_window`, `self.fast/slow/signal_window` — values must be identical | Migrate defaults verbatim (50/100/6/12/3) | YES |
| **`__str__`/`name` drift** | If a frozen artifact serialized the strategy name | Verified NOT in any e2e golden; only `strategy_id`-based identity asserted | NO (low risk) |
| **`to_dict()` key/shape change** | Only `test_signal_store.py` / `test_backtest_oracle.py` observe it | Migrate those tests in lockstep (D-05) | NO (test-only, migrated) |
| **`SignalRecord.config` identity vs equality** | `test_signal_store.py:171` asserts `record.config is strategy.config` (identity) | Becomes a dict-shape assertion (D-04); `params_snapshot()` returns a fresh dict each call → switch `is` to `==` on the dict | NO (test-only) |
| **e2e fixture kwargs construction** | `ScriptedEmitter`/`SingleMarketBuy` build a `BaseStrategyConfig` then `super().__init__(name, config)` | Rewrite to `super().__init__(**kwargs)`; keep every param value identical (`FractionOfCash(Decimal("0.95"))`, `max_window=100`, etc.) | YES if a param value drifts |

**The gate:** `make test` full suite (274 component + integration + 58 e2e) green, BTCUSD oracle byte-exact, `mypy --strict` clean on the in-scope reference strategy + base.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No frozen e2e golden serializes the strategy `name` or `to_dict()` output | Pitfall 3/5, Risk Map | LOW — grep found no `strategy_name`/`SMA_MACD_1d` in any `tests/e2e/**/golden/`; verified absent. If a golden does serialize it, `__str__`/`name` must be preserved exactly. |
| A2 | `get_type_hints(type(self))` returns the full merged-MRO dict with subclass-overrides applied | Pattern 1 | LOW — VERIFIED by live stdlib probe this session on representative class shapes. |
| A3 | The three coercion-target enums (`Timeframe`/`OrderType`/`TradingDirection`) are the ONLY fields needing str→enum coercion | Pattern 2, _COERCE table | LOW — VERIFIED against current `BaseStrategyConfig` fields; `sizing_policy`/`sltp_policy` are dataclass values (passed as objects, not strings), `tickers`/`allow_increase`/`max_positions` are native types. |

## Open Questions

1. **`reconfigure` re-resolving `timeframe` without a `timeframe` kwarg.**
   - What we know: `_apply_params` overwrites `self.timeframe` (enum→timedelta). On a second call (`reconfigure(short_window=30)`) the `timeframe` default is read via `getattr(type(self), "timeframe", ...)` — which returns the *class* attr (annotation-only on base = `_MISSING` unless the subclass pins it), NOT the already-resolved instance timedelta.
   - What's unclear: how to make the re-resolve idempotent when `timeframe` was supplied only at first construction via kwargs (so there's no class-attr default to fall back to).
   - Recommendation: store the coerced **enum** on a stable attr (e.g. `self._timeframe`) and derive `self.timeframe` (timedelta) + `self.timeframe_alias` from it on every `_apply_params` pass; when no `timeframe` kwarg arrives in a reconfigure, fall back to `getattr(self, "_timeframe", default)` (instance, not class). This makes `reconfigure(short_window=30)` keep the prior timeframe. The planner should pin this exact fallback order in a task. (This is a real mechanic the design note left to spec-time.)

2. **`params_snapshot()` vs `to_dict()` — one method or two?**
   - What we know: D-04 says "e.g. `strategy.to_dict()` / `params_snapshot()`". The current `to_dict()` has a specific 10-key serialization shape (stringified UUIDs, `.value` enums, `repr()` policies).
   - What's unclear: whether the SignalRecord snapshot should reuse `to_dict()` (the serialization-edge shape) or a new `params_snapshot()` (raw declared attrs).
   - Recommendation: keep `to_dict()` as the JSON-safe serialization edge (preserve its key set), and capture the SignalRecord snapshot from `to_dict()` directly so the migrated `model_dump()`→dict callers get a stable shape. Claude's discretion per D-04 — the planner picks one and pins the key set.

## Environment Availability

> Skipped — this phase has no external dependencies (pure code/config changes within the existing Poetry-managed `.venv`). No new tools, services, or runtimes are introduced.

## Validation Architecture

> `workflow.nyquist_validation` is not `false` in config → section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/strategy/ -x` (or `make test-strategy`) |
| Full suite command | `make test` (unit + integration + e2e + oracle) |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| STRAT-01 | reject unknown kwarg → `UnknownParamError` | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k unknown -x` | ❌ Wave 0 (rewrite of test_strategy_config.py) |
| STRAT-01 | reject missing-required → `MissingParamError` | unit | `... -k missing_required -x` | ❌ Wave 0 |
| STRAT-01 | kwargs override class-attr default | unit | `... -k override -x` | ❌ Wave 0 |
| STRAT-01 | str→enum coercion (`timeframe="1d"`→timedelta on instance) | unit | `... -k coerce -x` | ❌ Wave 0 |
| STRAT-01 | non-enum knob NOT coerced | unit | `... -k no_coerce_int -x` | ❌ Wave 0 |
| STRAT-01 | `validate()` rejects `short>=long` (HARD-02) | unit | `... -k short_lt_long -x` | ⚠️ migrate from `test_short_window_ge_long_window_raises` |
| STRAT-01 | `init()` idempotent (call twice → identical state) | unit | `... -k idempotent -x` | ❌ Wave 0 |
| STRAT-01 | `reconfigure(**kwargs)` re-applies + re-validates | unit | `... -k reconfigure -x` | ❌ Wave 0 |
| STRAT-01 | SignalRecord carries dict snapshot (D-04) | unit | `poetry run pytest tests/unit/strategy/test_signal_store.py -k record_fields -x` | ⚠️ migrate `record.config is strategy.config` → dict-shape `==` |
| STRAT-01 | BTCUSD oracle byte-exact (134 / 46189.877…) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists (gate) |
| STRAT-01 | e2e 58/58 byte-exact | e2e | `poetry run pytest tests/e2e/ -x` | ✅ exists (gate) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/strategy/ -x` (the engine + hook unit coverage).
- **Per wave merge:** `make test-strategy && poetry run pytest tests/integration/ -x`.
- **Phase gate:** `make test` full suite green (incl. `test_backtest_oracle` + 58 e2e) AND `mypy --strict` clean, before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_strategy_config.py` — **rewrite** from `BaseStrategyConfig` pydantic tests to the class-attribute-surface tests (unknown/missing/override/coerce/no-coerce). D-05 note explicitly calls for rewrite-not-delete.
- [ ] `tests/unit/strategy/test_strategy.py` — add idempotency test (D-11) + reconfigure test (D-12); update the `_AlwaysBuyStrategy`/`_sma_config` construction to the kwargs surface.
- [ ] `tests/unit/strategy/test_signal_store.py` — migrate `record.config is strategy.config` (identity) + `model_dump()` to dict-shape `==` assertions (D-04).
- [ ] `core/exceptions/strategy.py` — NEW module: `UnknownParamError`, `MissingParamError` (no test file needed beyond the engine unit tests that raise them).
- [ ] No framework install needed (pytest already present).

## Security Domain

> `security_enforcement` not configured `false` → section included, but this phase has **no security surface**: it is an internal authoring-API refactor with no auth, network, crypto, session, or external-input boundary. The only "input validation" is the param-coercion engine, which is functional (not security) validation.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth surface) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | partial | The kwargs engine rejects unknown/missing params loudly (`UnknownParamError`/`MissingParamError`) and coerces only known enum fields via `_missing_`. This is functional fail-loud validation, not a trust boundary — strategy authors are first-party developers, not untrusted callers. |
| V6 Cryptography | no | — (never hand-roll; not relevant) |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent param drop (typo'd kwarg ignored) | Tampering (correctness) | `UnknownParamError` on unknown kwargs (D-06) — the design note's "one accepted runtime check." |
| Partial reconfigure (direct attr poke) | Tampering (correctness) | Documented sanctioned-`reconfigure`-only discipline (D-13) — replaces the dropped frozen guard. |

## Sources

### Primary (HIGH confidence)
- Repo source (verified this session): `itrader/strategy_handler/base.py`, `strategies/SMA_MACD_strategy.py`, `strategies/empty_strategy.py`, `config/strategy.py`, `strategies_handler.py`, `signal_record.py`, `core/sizing.py`, `core/enums/trading.py`, `core/enums/order.py`, `core/exceptions/base.py`/`order.py`, `outils/time_parser.py`, `scripts/run_backtest.py`.
- Test source (verified): `tests/unit/strategy/test_strategy.py`, `test_strategy_config.py`, `test_signal_store.py`; `tests/integration/test_backtest_oracle.py`, `test_backtest_smoke.py`, `test_universe_spans.py`, `test_reservation_inertness.py`; `tests/e2e/strategies/scripted_emitter.py`, `single_market_buy.py`, `tests/e2e/scenario_spec.py`, `tests/e2e/matching/entries/market_next_open/scenario.py`.
- `typing.get_type_hints` MRO-merge behavior — VERIFIED by live stdlib probe (A2).
- `.planning/notes/strategy-authoring-surface-999.5c.md` (converged design), `.planning/phases/02-strategy-authoring-surface/02-CONTEXT.md` (locked decisions), `CLAUDE.md` (conventions).

### Secondary / Tertiary
- None — this phase required no web search or external docs (pure-stdlib + in-repo).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no external packages; stdlib primitives verified by probe.
- Architecture: HIGH — engine algorithm derived directly from verified repo code + converged design note; MRO mechanics probe-verified.
- Pitfalls: HIGH — the `self.timeframe` type collision, Decimal string-path, and snapshot-shape risks all traced to concrete consuming code in the repo.
- Open questions: 2 genuine spec-time mechanics (reconfigure timeframe fallback; snapshot method choice) the design note left open.

**Research date:** 2026-06-12
**Valid until:** stable — this is an internal-code phase against a pinned repo; findings hold until the source files change. Re-verify only if base.py/strategies_handler.py/the enums are edited before planning.
