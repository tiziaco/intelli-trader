# Phase 2: Strategy Authoring Surface - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 13 (1 new, 7 modify, 1 delete, 4 test/fixture migrate)
**Analogs found:** 13 / 13 (all in-repo; pure-stdlib + existing-module phase)

> This is a brownfield migration phase, not a greenfield build. Most "analogs" are
> the files' own current shape (the thing being rewritten) plus a sibling that
> demonstrates the target convention. Every pattern below is concrete code already
> in this repo — no external library is added (RESEARCH §Standard Stack).

> **Indentation hazard (CLAUDE.md, load-bearing):** `strategy_handler/` modules use
> **TABS**; `config/`, `core/`, `core/exceptions/`, and `tests/` (e2e + unit) use
> **4 SPACES**. Verified this session: `base.py`/`order.py` exceptions = SPACES;
> `tests/e2e/strategies/*` and `tests/unit/strategy/*` = SPACES; `scripts/run_backtest.py`
> = SPACES. The per-file indentation is pinned in each assignment below — never normalize.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/core/exceptions/strategy.py` (NEW) | exceptions | transform | `itrader/core/exceptions/order.py` + `base.py::ValidationError` | exact | 4-space |
| `itrader/strategy_handler/base.py` (MODIFY) | model/ABC | transform (introspect→setattr) | own current shape + RESEARCH §Code Examples engine skeleton | self/role | TABS |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` (MODIFY) | strategy subclass | transform | own current shape + RESEARCH §validate() example | self/role | TABS |
| `itrader/strategy_handler/strategies/empty_strategy.py` (MODIFY) | strategy subclass | transform | `SMA_MACD_strategy.py` (sibling) | role-match | TABS |
| `itrader/config/strategy.py` (DELETE) | config | — | — (full delete, D-01) | n/a | 4-space |
| `itrader/config/__init__.py` (MODIFY) | barrel | — | own current shape (drop 2 lines) | self | 4-space |
| `itrader/strategy_handler/strategies_handler.py` (MODIFY ~line 126) | handler | event-driven | own current shape (capture-site swap) | self | TABS |
| `itrader/strategy_handler/signal_record.py` (MODIFY) | model (frozen entity) | transform | own current shape (field retype) | self | 4-space |
| `tests/unit/strategy/test_strategy.py` (MODIFY) | test | transform | own current shape (kwargs swap + new tests) | self | 4-space |
| `tests/unit/strategy/test_strategy_config.py` (REWRITE) | test | transform | own current shape (rewrite to surface tests) | self | 4-space |
| `tests/unit/strategy/test_signal_store.py` (MODIFY) | test | transform | own current shape (identity→dict `==`) | self | 4-space |
| `tests/e2e/strategies/scripted_emitter.py` (MODIFY) | test fixture (strategy) | transform | own current shape + `single_market_buy.py` | self | 4-space |
| `tests/e2e/strategies/single_market_buy.py` (MODIFY) | test fixture (strategy) | transform | own current shape | self | 4-space |
| `scripts/run_backtest.py` (MODIFY ~48/77/84) | entrypoint/script | transform | own current shape (construction swap) | self | 4-space |
| integration construction sites (`test_backtest_smoke.py`, `test_universe_spans.py`, `test_reservation_inertness.py`, `test_backtest_oracle.py`) | test | transform | their own construction lines | self | 4-space |

## Pattern Assignments

### `itrader/core/exceptions/strategy.py` (NEW — exceptions, transform) — 4 SPACES

**Analog:** `itrader/core/exceptions/order.py` (domain-exception module shape) +
`itrader/core/exceptions/base.py::ValidationError` (the base to subclass, RESEARCH §Don't Hand-Roll).

**Module-shape pattern** — copy from `order.py` lines 1-18 (module docstring → import base → domain
base class → specific subclasses with structured `__init__`):
```python
"""
Order-specific exceptions for the iTrader system.
"""

from .base import ITraderError


class OrderError(ITraderError):
    """Base exception for order-related errors."""
    pass


class UnsizedSignalError(OrderError):
    """Raised when an order is constructed from a signal that was never sized."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Cannot create order from unsized signal for {ticker}")
```

**Base to subclass** — `core/exceptions/base.py` lines 14-25. `ValidationError` already carries the
house structured-field convention `(field, value, message)`. RESEARCH §Don't Hand-Roll mandates
`UnknownParamError`/`MissingParamError` subclass `ValidationError`, NOT a bare `ValueError`:
```python
class ValidationError(ITraderError):
    """Base exception for validation errors."""

    def __init__(self, field: str, value: Optional[str] = None, message: Optional[str] = None):
        self.field = field
        self.value = value
        error_msg = f"Validation error for field '{field}'"
        if value:
            error_msg += f" with value '{value}'"
        if message:
            error_msg += f": {message}"
        super().__init__(error_msg)
```

**Pattern to write** (synthesized — `MissingParamError(name)` and `UnknownParamError(sorted(names))`
per RESEARCH §Code Examples lines 316/322): two subclasses of `ValidationError`, each setting its
structured field and building a message in `__init__`. Mirror `order.py`'s docstring-per-class style.

**Barrel update:** `core/exceptions/__init__.py` (lines 31-43 for the import block, 65-73 for `__all__`)
— add a `# Strategy exceptions` group importing the two new classes and append them to `__all__`,
exactly mirroring the existing `# Order exceptions` block.

---

### `itrader/strategy_handler/base.py` (MODIFY — Strategy ABC, transform) — TABS

**Analog:** the file's own current `__init__` (lines 27-80) shows what the old `(name, config)` surface
copies onto the instance — the engine reads to *preserve byte-exact*. RESEARCH §Code Examples (lines
266-339) is the target engine skeleton (`_apply_params` shared by `__init__`/`reconfigure`).

**Current imports to drop** (line 12): `from itrader.config import BaseStrategyConfig`. **Add**
(per RESEARCH skeleton): `from typing import get_type_hints`, `from enum import Enum`,
`from itrader.core.enums import Timeframe` (already has `OrderType`), and
`from itrader.core.exceptions.strategy import UnknownParamError, MissingParamError`.

**Instance-attr set to PRESERVE byte-exact** (current lines 32-80) — every one of these must end up on
`self` with the same value/type; the engine just changes HOW they arrive (kwargs vs `config.x`):
```python
self.strategy_id = StrategyId(idgen.generate_strategy_id())   # KEEP minting per-construction
self.is_active = True
self.timeframe = to_timedelta(config.timeframe.value)         # CRITICAL: stays TIMEDELTA (Pitfall 1)
self.tickers = config.tickers
self.order_type: OrderType = config.order_type
self.subscribed_portfolios: list[PortfolioId | int] = []
self.sizing_policy: SizingPolicy = config.sizing_policy
self.direction: TradingDirection = config.direction
self.allow_increase = config.allow_increase
self.max_positions = config.max_positions
self.sltp_policy: SLTPPolicy | None = config.sltp_policy
self.max_window: int = 0
self.warmup: int = 0
```

**#1 byte-exactness trap (RESEARCH Pitfall 1 + Risk Map row 1):** `self.timeframe` is consumed as a
`timedelta` by `check_timeframe`, `min_timeframe`, and SMA's `last_time - self.timeframe * self.short_window`.
The coerced `Timeframe` enum must be resolved to a timedelta before storing on `self.timeframe`; stash
the enum/alias separately (e.g. `self._timeframe` / `self.timeframe_alias`) for serialization. RESEARCH
Open Question 1 pins the reconfigure fallback order (instance enum, not class attr) — planner must task it.

**`to_dict()` — PRESERVE the 10-key shape** (current lines 82-109), just swap `self.config.*` reads for
real instance attrs (D-03). The key set is observed by `test_signal_store.py` / `test_backtest_oracle.py`
(RESEARCH Pitfall 3 — keep keys to minimize churn):
```python
return {
    "strategy_id" : str(self.strategy_id),
    "strategy_name": self.name,
    "subscribed_portfolios" : [str(pid) for pid in self.subscribed_portfolios],
    "order_type": self.order_type.value,
    "is_active" : self.is_active,
    "sizing_policy" : repr(self.sizing_policy),
    "direction" : self.direction.value,
    "allow_increase" : self.allow_increase,
    "max_positions" : self.max_positions,
    "sltp_policy" : repr(self.sltp_policy) if self.sltp_policy is not None else None,
}
```

**`__str__` — Pitfall 5:** current line 114 reads `f'{self.name}_{self.config.timeframe.value}'`. The
`self.config.timeframe.value` must become a real instance attr (the stashed `timeframe_alias`). Introduce
a `name` class attr defaulting to the class name (D-03 discretion).

**UNCHANGED (Reusable Assets, CONTEXT §code_context):** `buy()`/`sell()` (lines 131-165),
`subscribe_portfolio`/`unsubscribe_portfolio` (167-179), `activate`/`deactivate`, the abstract
`generate_signal` (119-129). Only the param-declaration surface changes, not the signal-return contract.

**New methods to add** (RESEARCH §Code Examples): `_apply_params(**kwargs)` (introspect→required/unknown→
coerce→setattr), `validate()` no-op hook (D-09), `init()` no-op idempotent hook (D-10),
`reconfigure(**kwargs)` (re-apply→re-validate→re-init, D-12).

---

### `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` (MODIFY — strategy subclass) — TABS

**Analog:** its own current shape (lines 16-67 = the `SMA_MACDConfig` to DELETE + the copy-onto-instance
`__init__`) and RESEARCH §Code Examples lines 343-364 (the target class-attr + `validate()` form).

**DELETE** `SMA_MACDConfig` (lines 16-36) and its pydantic imports (lines 4-6: `Field`, `model_validator`,
`BaseStrategyConfig`). The `@model_validator` `_short_lt_long` (lines 31-36) migrates verbatim into a
`validate()` hook (D-09).

**Golden defaults to migrate VERBATIM** (Risk Map rows 3-4 — these are oracle-visible; any drift breaks
134 trades / `46189.87730727451`):
```python
short_window: int = 50      # current lines 25-29 + 56-60
long_window:  int = 100
fast_window:  int = 6
slow_window:  int = 12
signal_window: int = 3
max_window: int = 100       # current line 63: max([self.long_window, 100]) == 100
warmup: int = 100           # current line 67: max([self.long_window, 100]) == 100
```

**Cross-field rule** (current lines 31-36 → RESEARCH lines 357-360) becomes:
```python
def validate(self) -> None:
    if self.short_window >= self.long_window:
        raise ValueError("short_window must be < long_window")
```

**`init()`** is empty/no-op in Phase 2 (D-10). `generate_signal` (lines 69-112) is UNCHANGED — it already
reads `self.short_window`/`self.timeframe` (the timedelta) and must stay byte-identical.

**Decimal string-path (Pitfall 4):** `sizing_policy = FractionOfCash(Decimal("0.95"))` — preserve the
string-path literal verbatim when it moves to a class attr.

---

### `itrader/strategy_handler/strategies/empty_strategy.py` (MODIFY — strategy subclass) — TABS

**Analog:** the migrated `SMA_MACD_strategy.py` (sibling, same role). DELETE `EmptyStrategyConfig`
(lines 10-11) and the `BaseStrategyConfig` import (line 5). Current `__init__` (lines 19-25) sets
`self.max_window = 1`, warmup stays 0 — migrate to a `max_window: int = 1` class attr. `generate_signal`
returns `None` (unchanged). No `validate()` needed.

---

### `itrader/config/strategy.py` (DELETE) + `itrader/config/__init__.py` (MODIFY) — 4 SPACES

**D-01 full delete.** Remove the file. In `config/__init__.py` drop line 56
(`from .strategy import BaseStrategyConfig`) and line 100 (`"BaseStrategyConfig",` in `__all__`). No
analog — pure removal.

---

### `itrader/strategy_handler/strategies_handler.py` (MODIFY ~line 126 — handler) — TABS

**Analog:** its own current capture site. The ONLY change (D-04) is line 126 `config=strategy.config` →
`config=strategy.to_dict()` (or `params_snapshot()`). Everything around it — the warmup short-circuit
(lines 103-104), the `SignalRecord(...)` build (117-127), the per-portfolio `SignalEvent` fan-out
(136-166) — is UNCHANGED (CONTEXT §Integration Points; the #24 boundary stays).

```python
self.signal_store.add(SignalRecord(
    strategy_id=strategy.strategy_id,
    ticker=ticker,
    time=event.time,
    action=intent.action,
    stop_loss=intent.stop_loss,
    take_profit=intent.take_profit,
    exit_fraction=intent.exit_fraction,
    quantity=intent.quantity,
    config=strategy.config,          # ← D-04: becomes strategy.to_dict() (dict snapshot)
))
```

---

### `itrader/strategy_handler/signal_record.py` (MODIFY — frozen entity) — 4 SPACES

**Analog:** own current shape. Retype the `config` field (line 83) `config: BaseStrategyConfig` →
`config: dict[str, Any]` (D-04). Drop the `from itrader.config import BaseStrategyConfig` import (line 35);
add `from typing import Any`. Update the field docstring (lines 67-69) from "frozen config / model_dump()"
to "plain params snapshot dict". The frozen-dataclass declaration pattern itself is unchanged:
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SignalRecord:
    ...
    config: BaseStrategyConfig    # ← becomes  config: dict[str, Any]
```

---

### `tests/e2e/strategies/scripted_emitter.py` + `single_market_buy.py` (MODIFY — fixtures) — 4 SPACES

**Analog:** their own current `__init__` (`scripted_emitter.py` lines 81-115; `single_market_buy.py`
lines 53-68). Both build a `BaseStrategyConfig(...)` then call `super().__init__("name", config)`. Rewrite
to pass params straight through to `super().__init__(**kwargs)` (D-05). Keep EVERY param value identical —
`FractionOfCash(Decimal("0.95"))`, `max_window=100`, the kwarg defaults (`order_type`, `direction`,
`allow_increase=False`, `max_positions=1`) (Risk Map row 8 — e2e 58/58 byte-exact). Drop the
`from itrader.config import BaseStrategyConfig` import. `scripted_emitter.py` current target block:
```python
config = BaseStrategyConfig(
    timeframe=timeframe,
    tickers=list(tickers),
    sizing_policy=sizing_policy,
    direction=direction,
    allow_increase=allow_increase,
    max_positions=max_positions,
    order_type=order_type,
    sltp_policy=sltp_policy,
)
super().__init__("scripted_emitter", config)   # → super().__init__(timeframe=..., tickers=..., ...)
```

---

### `scripts/run_backtest.py` (MODIFY ~48/77/84 — entrypoint) — 4 SPACES

**Analog:** own current construction. Line 48 imports `SMA_MACDConfig` (drop it). Lines 77-84 build
`SMA_MACDConfig(timeframe=TIMEFRAME, ..., sizing_policy=FractionOfCash(Decimal("0.95")))` then
`SMAMACDStrategy(strategy_config)`. Collapse to a single `SMAMACDStrategy(timeframe=TIMEFRAME,
tickers=[...], sizing_policy=FractionOfCash(Decimal("0.95")))`. This is the **byte-exact oracle
generator** (CONTEXT §Integration Points) — the constructed strategy behavior must be identical.

---

### Unit tests (MODIFY/REWRITE) — 4 SPACES

- **`test_strategy_config.py` (REWRITE, Wave 0):** currently tests `BaseStrategyConfig`/`SMA_MACDConfig`
  pydantic behavior (frozen, `Field(gt=0)`, cross-field) — that all goes away. Rewrite to test the
  class-attribute surface: kwargs override, reject-unknown (`UnknownParamError`), missing-required
  (`MissingParamError`), str→enum coercion, non-enum knob NOT coerced (RESEARCH §Test Map rows). Reuse the
  `_golden_sizing()` helper pattern (current lines 23-25).
- **`test_strategy.py` (MODIFY):** swap `_sma_config()` (lines 55-60) + `SMAMACDStrategy(_sma_config())`
  (lines 101/127/138) and `_AlwaysBuyStrategy` `super().__init__("always_buy", config)` (lines 163-178) to
  the kwargs surface. ADD the idempotency test (RESEARCH lines 369-374) and a `reconfigure` test (D-11/D-12).
- **`test_signal_store.py` (MODIFY):** the local `_AlwaysBuy`/`_NeverSignal` fixtures (lines 64-88) move to
  kwargs `super().__init__`. The assertions at lines 170-173 (`record.config is strategy.config` identity +
  `record.config.model_dump()`) become dict-shape `==` assertions (D-04, Risk Map row 7 — `params_snapshot()`
  returns a fresh dict each call, so `is` → `==`).

---

### Integration construction sites (MODIFY) — 4 SPACES

`test_backtest_smoke.py`, `test_universe_spans.py`, `test_reservation_inertness.py`,
`test_backtest_oracle.py` each construct a strategy via the old `Config(...)` + `(name, config)` path.
Mechanical swap to the kwargs surface, every param value verbatim. `test_backtest_oracle.py` is a GATE
(byte-exact 134 / `46189.87730727451`); its `record.config` assertion (~line 303 per RESEARCH) migrates to
the dict shape.

## Shared Patterns

### House exception convention
**Source:** `itrader/core/exceptions/base.py` lines 14-25 (`ValidationError`) + `order.py` lines 8-31.
**Apply to:** `core/exceptions/strategy.py`.
Subclass `ValidationError`; set structured field(s) in `__init__`; build the message in `__init__`
(never a bare `raise ValueError` for the param-engine errors — RESEARCH §Don't Hand-Roll).

### Barrel re-export
**Source:** `itrader/core/exceptions/__init__.py` lines 31-43 (`# Order exceptions` import group) + 65-68
(`__all__` group).
**Apply to:** adding the strategy-exceptions group; and (inverse) removing the `BaseStrategyConfig` lines
from `config/__init__.py` (lines 56 + 100).

### Timeframe enum→timedelta resolution (oracle-critical)
**Source:** `strategy_handler/base.py` line 37 — `self.timeframe = to_timedelta(config.timeframe.value)`.
**Apply to:** the engine's `_apply_params` in `base.py`. After coercing the kwarg to a `Timeframe` enum,
resolve to a timedelta before storing on `self.timeframe`; keep the enum/alias separately. RESEARCH Open
Question 1 pins the reconfigure-without-`timeframe` fallback (read instance enum, not class attr).

### Decimal string-path literal
**Source:** `FractionOfCash(Decimal("0.95"))` — appears verbatim in `run_backtest.py:80`,
`scripted_emitter.py:93`, `single_market_buy.py:64`, `test_strategy.py:60`.
**Apply to:** every migrated class-attr default and construction site. Never `Decimal(0.95)` (float path,
Pitfall 4 — breaks byte-exactness).

### kwargs construction migration (D-05 mechanical swap)
**Source:** the `BaseStrategyConfig(...)` + `super().__init__(name, config)` block in
`scripted_emitter.py:105-115`.
**Apply to:** all fixtures, scripts, unit + integration construction sites. Pass params as kwargs to
`super().__init__(**kwargs)`; keep every value identical; drop the `BaseStrategyConfig` import.

### `to_dict()` snapshot shape preservation (D-03/D-04)
**Source:** `strategy_handler/base.py` lines 82-109 (the 10-key dict).
**Apply to:** the rewritten `to_dict()` and the `strategies_handler.py:126` capture site. Keep the key set;
only swap `self.config.*` reads for instance attrs. Observers: `test_signal_store.py`, `test_backtest_oracle.py`.

## No Analog Found

None. Every file maps to an in-repo analog (its own current shape, a sibling, or a `core/exceptions`
template). This is a pure-stdlib + existing-module migration — no external package, no novel role.

The only genuinely NEW construct, the introspection engine (`_apply_params` via
`typing.get_type_hints` + `_COERCE` table), has no codebase analog because no other module introspects
class annotations — but RESEARCH §Architecture Pattern 1 + §Code Examples (lines 266-339) provide the
verified, probe-tested algorithm the planner should follow directly. The planner should source that
engine from RESEARCH, not from a codebase pattern.

## Metadata

**Analog search scope:** `itrader/core/exceptions/`, `itrader/strategy_handler/` (+ `strategies/`),
`itrader/config/`, `tests/unit/strategy/`, `tests/e2e/strategies/`, `scripts/`.
**Files scanned:** 11 source/test files read in full or in targeted ranges.
**Pattern extraction date:** 2026-06-12
