# Phase 5: Strategy Interface Hardening & Signal Storage - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 14 (8 new / 6 modified)
**Analogs found:** 14 / 14 (every new file has an exact in-repo template)

> This phase is pattern-assembly, not invention. Every new file copies an existing
> repo pattern verbatim in shape. The single risk is **byte-exact preservation** and
> the **tabs-vs-spaces** rule. Indentation per file is called out in every assignment.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| **NEW** `itrader/strategy_handler/config.py` (or `base.py`) — `BaseStrategyConfig` | config (pydantic model) | transform/validate | `itrader/config/portfolio.py` | exact |
| **NEW** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` — `SMA_MACDConfig` subclass | config (pydantic model) | transform/validate | `itrader/config/portfolio.py` (`PortfolioLimits`/`RiskManagement` subclassing + `Field(gt=0)`) | exact |
| **NEW** `itrader/strategy_handler/storage/base.py` — `SignalStore` ABC | storage (ABC) | CRUD | `itrader/order_handler/base.py::OrderStorage` | exact |
| **NEW** `itrader/strategy_handler/storage/in_memory_storage.py` — `InMemorySignalStore` | storage (backend) | CRUD | `itrader/order_handler/storage/in_memory_storage.py` | exact |
| **NEW** `itrader/strategy_handler/storage/storage_factory.py` — `SignalStorageFactory` | factory | request-response | `itrader/order_handler/storage/storage_factory.py` | exact |
| **NEW** `itrader/strategy_handler/storage/__init__.py` — barrel | config (barrel) | — | `itrader/order_handler/storage/__init__.py` | exact |
| **NEW** `SignalRecord` frozen dataclass (location: storage module or new `signal_record.py`) | model (entity) | transform | `itrader/order_handler/order.py::Order` + `events/signal.py::SignalEvent` | exact |
| **NEW** `Timeframe` enum (`itrader/core/enums/trading.py` or new module) | model (enum) | transform | `itrader/core/enums/trading.py::TradingDirection` / `order.py::OrderType` | exact |
| **MODIFIED** `itrader/core/ids.py` — add `SignalId` | model (id type) | — | existing `OrderId`/`StrategyId` NewType in same file | exact |
| **MODIFIED** `itrader/outils/id_generator.py` — add `generate_signal_id` | utility | — | existing `generate_order_id` in same file | exact |
| **MODIFIED** `itrader/strategy_handler/base.py` — config constructor, `__str__`/`__repr__` | model (ABC) | transform | itself (re-shape) | self |
| **MODIFIED** `itrader/strategy_handler/strategies_handler.py` — warmup short-circuit, per-intent capture, enum collapse | service (handler) | event-driven | itself (re-shape) | self |
| **MODIFIED** `itrader/strategy_handler/strategies/empty_strategy.py` — `EmptyStrategyConfig` + relocation | config + model | transform | `SMA_MACDConfig` pattern | role-match |
| **MODIFIED** `itrader/trading_system/backtest_trading_system.py` — inject SignalStore + accessor | composition root | event-driven | itself (`OrderStorageFactory.create('backtest')` wiring at lines 122-125) | self |

---

## Pattern Assignments

### `itrader/strategy_handler/config.py` — `BaseStrategyConfig` / `SMA_MACDConfig` (config, validate)

**Analog:** `itrader/config/portfolio.py`
**Indentation:** 4 SPACES (pydantic config modules use spaces; verified against `config/portfolio.py`).

**Imports + ConfigDict + Field pattern** (`config/portfolio.py` lines 8-12, 33-44):
```python
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PortfolioLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_positions: int = Field(default=50, gt=0)
    max_position_value: Decimal = Decimal("1000000.0")
    max_portfolio_concentration: float = Field(default=0.25, gt=0, le=1)
```

**Subclass + per-strategy fields pattern** (`config/portfolio.py` 103-119 shows nested-model composition; the SMA_MACDConfig subclass mirrors the `PortfolioLimits → PortfolioConfig` inheritance/composition style):
- `BaseStrategyConfig(BaseModel)` with `model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)` (D-03/D-05 — NOTE: `config/portfolio.py` uses `extra="forbid"`; here use `arbitrary_types_allowed=True, frozen=True` per RESEARCH Pattern 1, because the `core/sizing.py` frozen-dataclass unions need it).
- `SMA_MACDConfig(BaseStrategyConfig)` adds the 5 params, each `Field(default=..., gt=0)`.

**Enum field + default pattern** (`config/portfolio.py` 59, 111):
```python
risk_level: RiskLevel = RiskLevel.MODERATE      # enum field with enum default
portfolio_type: PortfolioType = PortfolioType.EQUITY
```
→ `order_type: OrderType = OrderType.MARKET` (D-04), `direction: TradingDirection = TradingDirection.LONG_ONLY`.

**Cross-field validator** — `config/portfolio.py` has none; use the pydantic-v2 `@model_validator(mode="after")` shown in RESEARCH Pattern 1 lines 198-202 (`short_window < long_window`). **MUST use v2 decorators only** (`@field_validator`/`@model_validator`, never v1 `@validator`) — `filterwarnings=["error"]` fails on the deprecation (RESEARCH Pitfall 5).

**Golden defaults to encode** (from `SMA_MACD_strategy.py` lines 25-29, 41): short=50, long=100, FAST=6, SLOW=12, WIN=3; `sizing_policy=FractionOfCash(Decimal("0.95"))` (string-path Decimal — byte-exact, RESEARCH Code Examples line 343). `max_window = max([long_window, 100])` (line 53).

---

### `itrader/strategy_handler/storage/base.py` — `SignalStore` ABC (storage, CRUD)

**Analog:** `itrader/order_handler/base.py::OrderStorage` (lines 25-43)
**Indentation:** 4 SPACES — RESEARCH Pitfall 6 confirms `order_handler/storage/*` ABC/impl/factory use **4 spaces** despite being under a tab-handler dir. Match the sibling.

**ABC pattern** (`order_handler/base.py` 25-43):
```python
import uuid
from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .signal_record import SignalRecord


class SignalStore(ABC):
    """Abstract base class for signal storage implementations."""

    @abstractmethod
    def add(self, record: 'SignalRecord') -> None:
        ...
```
Method surface (D-12 query API): `add(record)`, `get_all() -> list`, `by_strategy(strategy_id) -> list`, `by_ticker(ticker) -> list`. Each `@abstractmethod` with a NumPy-style docstring (match the `OrderStorage` docstring density at lines 33-98).

---

### `itrader/strategy_handler/storage/in_memory_storage.py` — `InMemorySignalStore` (storage, CRUD)

**Analog:** `itrader/order_handler/storage/in_memory_storage.py` (lines 11-46, 112-114)
**Indentation:** 4 SPACES.

**Flat-dict + native-UUID key pattern** (`in_memory_storage.py` 34-51):
```python
def __init__(self) -> None:
    self._by_id: Dict[uuid.UUID, 'Order'] = {}   # flat-dict, O(1), native-UUID key

def add_order(self, order: 'Order') -> None:
    self._by_id[order.id] = order
```

**Predicate-filter query pattern** (`in_memory_storage.py` 112-114, 134-136):
```python
def get_orders_by_ticker(self, ticker: str, ...) -> List['Order']:
    return [order for order in self._orders(...) if order.ticker == ticker]

def get_active_orders(self, ...) -> List['Order']:
    return [order for order in self._orders(...) if order.is_active]
```
→ `InMemorySignalStore`: `self._by_id: dict[uuid.UUID, SignalRecord] = {}`; `add` writes `self._by_id[record.signal_id] = record`; `get_all` returns `list(self._by_id.values())`; `by_strategy`/`by_ticker` are list-comprehension predicate filters (exact shape in RESEARCH Pattern 2 lines 212-222).

---

### `itrader/strategy_handler/storage/storage_factory.py` — `SignalStorageFactory` (factory)

**Analog:** `itrader/order_handler/storage/storage_factory.py` (lines 1-73)
**Indentation:** 4 SPACES.

**Environment-keyed factory pattern** (`storage_factory.py` 18-58):
```python
from itrader.core.exceptions import ConfigurationError
from ..base import OrderStorage              # → from .base import SignalStore
from .in_memory_storage import InMemoryOrderStorage

class OrderStorageFactory:
    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> OrderStorage:
        environment = environment.lower()
        if environment in ('backtest', 'test'):
            return InMemoryOrderStorage()
        elif environment == 'live':
            if not db_url:
                raise ConfigurationError("db_url", None, "...required for live...")
            from .postgresql_storage import PostgreSQLOrderStorage
            return PostgreSQLOrderStorage(db_url)
        else:
            raise ConfigurationError("environment", environment, f"Unknown environment: {environment}...")

    @staticmethod
    def create_in_memory() -> InMemoryOrderStorage:
        return InMemoryOrderStorage()
```
→ `SignalStorageFactory.create('backtest'|'test') -> InMemorySignalStore`; `'live'` raises `ConfigurationError` OR returns a NotImplemented placeholder (v1.1 has no Postgres backend — simplest is to raise `ConfigurationError` for `'live'`, deferring the placeholder import). Keep the `create_in_memory()` convenience method — the `TradingSystem` may call `SignalStorageFactory.create('backtest')` exactly like line 123.

**`__init__.py` barrel** — mirror `order_handler/storage/__init__.py` (lines 9-20): re-export `SignalStore`, `InMemorySignalStore`, `SignalStorageFactory` with module docstring.

---

### `SignalRecord` frozen entity (model, transform)

**Analog (entity-vs-event):** `itrader/order_handler/order.py::Order` (lines 33-56) — the entity that carries `strategy_id`/`portfolio_id`/`ticker`/`time` and an `idgen`-defaulted id.
**Analog (frozen+slots+kw_only fact shape):** `events/signal.py::SignalEvent` (lines 19-20) and `core/sizing.py::SignalIntent` (lines 211-242).
**Indentation:** match the file it lands in. If co-located with the storage seam (4 spaces) use 4 spaces; if a standalone `signal_record.py` in `strategy_handler/` (tabs dir) decide by reading the target — RESEARCH recommends co-locating near storage; prefer 4 spaces to match the storage seam and the events package.

**Frozen-dataclass entity pattern** (`SignalIntent`, `core/sizing.py` 211-242 — the closest frozen-fact analog):
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SignalIntent:
    ticker: str
    action: Side
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    exit_fraction: Decimal = Decimal("1")
    quantity: Decimal | None = None
```

**id-defaulted-via-idgen pattern** (`order.py` line 56 — adapt for kw_only frozen):
```python
id: OrderId = field(default_factory=lambda: OrderId(idgen.generate_order_id()))
```
→ `signal_id: SignalId = field(default_factory=lambda: SignalId(idgen.generate_signal_id()))` (D-10).

**Proposed field set** (RESEARCH Pattern 3 lines 230-242, subject to D-08): `signal_id`, `strategy_id: StrategyId`, `ticker: str`, `time: datetime`, `action: Side`, `stop_loss`/`take_profit`/`exit_fraction`/`quantity` (Decimal | None), `config: BaseStrategyConfig` (D-11 snapshot by reference). **NO `portfolio_id`** (D-09 — captured pre-fan-out). `action` uses `Side` for consistency with `SignalIntent`/`SignalEvent` (RESEARCH OQ3).

---

### `Timeframe` enum (model, transform)

**Analog:** `itrader/core/enums/trading.py::TradingDirection` (lines 16-36) and `enums/order.py::OrderType` (lines 11-30) — the case-insensitive `_missing_` house pattern.
**Indentation:** 4 SPACES (`core/enums/` is spaces).

**Class-Enum + `_missing_` pattern** (`trading.py` 16-36):
```python
from enum import Enum

class TradingDirection(Enum):
    LONG_ONLY = "LONG_ONLY"
    LONG_SHORT = "LONG_SHORT"
    SHORT_ONLY = "SHORT_ONLY"

    @classmethod
    def _missing_(cls, value: object) -> "TradingDirection":
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown TradingDirection: {value!r}")
```
→ `Timeframe` with members `1m/5m/15m/1h/4h/1d/1w` (D-06; keep `1d` valid for golden). Add to the `core/enums/__init__.py` barrel (lines 45-48, 86-87) the same way `TradingDirection` is imported+`__all__`-listed. The base still converts via `to_timedelta(config.timeframe.value)` (D-06 — `to_timedelta` unchanged).

---

### `itrader/core/ids.py` — add `SignalId` (model, id type)

**Analog:** same file, the existing `NewType` list (lines 17-35).
**Indentation:** 4 SPACES.
```python
StrategyId = NewType("StrategyId", uuid.UUID)
```
→ add `SignalId = NewType("SignalId", uuid.UUID)` to the alias block AND to `__all__` (lines 26-35).

---

### `itrader/outils/id_generator.py` — add `generate_signal_id` (utility)

**Analog:** same file, `generate_order_id`/`generate_strategy_id` (lines 38-44).
**Indentation:** TABS (this module uses tabs).
```python
def generate_order_id(self) -> uuid.UUID:
    """Generate unique order ID."""
    return self._uuid7()
```
→ add `generate_signal_id(self) -> uuid.UUID: return self._uuid7()` (D-10). Single UUIDv7 scheme — never hand-roll.

---

### `itrader/strategy_handler/base.py` (MODIFIED — config constructor) (model ABC, transform)

**Indentation:** TABS (verified — `base.py` is tabs).

**Change-shape:**
1. **D-01 constructor collapse:** replace the kwargs `__init__` (lines 26-57) with `def __init__(self, config: BaseStrategyConfig) -> None:` storing `self.config = config` as single source of truth. Engine-facing attrs read from `self.config`: `self.timeframe = to_timedelta(config.timeframe.value)` (line 36 stays — D-06), `self.tickers = config.tickers`, `self.order_type = config.order_type` (now an `OrderType` enum, D-04), `self.sizing_policy`/`self.direction`/`self.allow_increase`/`self.max_positions`/`self.sltp_policy` read from config. Keep mutable runtime state on the instance — `self.strategy_id`, `self.is_active`, `self.subscribed_portfolios`, `self.max_window` (RESEARCH Pitfall 2 — do NOT mutate the frozen config).
2. **D-04:** drop the `order_type: str = "market"` param (lines 27, 38, 64) — FL-04. `self.order_type` becomes the enum read from config. Update `to_dict` line 64 accordingly (the enum's `.value` or the enum itself).
3. **D-14:** add `__str__`/`__repr__` to the base (derive from `self.name` + `config.timeframe`) — copy the shape from `SMA_MACD_strategy.py` 55-59 / `empty_strategy.py` 29-33, generalized.
4. Keep `buy`/`sell` sugar (88-122), `subscribe_portfolio`/`unsubscribe_portfolio` (124-128), `generate_signal` abstractmethod (76-86) **pure** (D-12 — no config reads inside `generate_signal`).

---

### `itrader/strategy_handler/strategies_handler.py` (MODIFIED — handler) (service, event-driven)

**Indentation:** TABS (verified).

**Change-shape (all inside `calculate_signals`, lines 56-119):**
1. **D-15 warmup short-circuit** — INSERT after line 80 (`data = self.feed.window(...)`), BEFORE `intent = strategy.generate_signal(...)` (line 81):
   ```python
   if len(data) < strategy.max_window:
       continue
   ```
   Use the IDENTICAL `<` comparison and the SAME `strategy.max_window` the feed window already reads (line 80) — RESEARCH Pitfall 1 (firing-tick parity is the byte-exact landmine).
2. **D-09/D-12 per-intent capture** — INSERT after the `if intent is None: continue` (line 83), BEFORE the per-portfolio fan-out loop (line 92):
   ```python
   self.signal_store.add(SignalRecord(
       strategy_id=strategy.strategy_id, ticker=ticker, time=event.time,
       action=intent.action, stop_loss=intent.stop_loss, take_profit=intent.take_profit,
       exit_fraction=intent.exit_fraction, quantity=intent.quantity,
       config=strategy.config,   # D-11 snapshot by reference
   ))
   ```
   Captured ONCE, no `portfolio_id` (RESEARCH Anti-Pattern: do NOT capture inside the fan-out loop).
3. **D-04 enum collapse** — line 95: `order_type=OrderType(strategy.order_type)` → `order_type=strategy.order_type` (already an enum from config). The `OrderType` import (line 5) may now be unused for this site — verify before removing (it may be used elsewhere).
4. **Constructor injection (D-12)** — `__init__` (lines 20-37) gains a `signal_store: SignalStore` param stored as `self.signal_store`, mirroring how `OrderHandler.__init__` takes `order_storage` (`order_handler.py` lines 39-40) and passes it to its manager (line 71-72).

---

### `itrader/strategy_handler/strategies/` package — relocation (D-13)

**`SMA_MACD_strategy.py`** (TABS): becomes `SMA_MACDConfig(BaseStrategyConfig)` + a `SMA_MACD_strategy(Strategy)` whose `__init__(self, config: SMA_MACDConfig)` calls `super().__init__(config)` and copies the 5 params onto `self` for `generate_signal` (D-12 pure-alpha — `generate_signal` reads `self.short_window` etc., NOT `self.config`). REMOVE the warmup guard (lines 66-67 — moved to handler, D-15) and `__str__`/`__repr__` (lines 55-59 — moved to base, D-14). `generate_signal` body (lines 72-107) unchanged byte-for-byte.
**`empty_strategy.py`** (TABS): same treatment — `EmptyStrategyConfig` + drop `__str__`/`__repr__` (lines 29-33).
**`__init__.py`** (NEW): empty or barrel, mirror `my_strategies/__init__.py` (empty file).
**4 import sites to update** (RESEARCH Runtime State Inventory): `scripts/run_backtest.py:45`, `tests/integration/test_backtest_smoke.py:18`, `tests/unit/strategy/test_strategy.py:40`, `tests/integration/test_reservation_inertness.py:69` → `itrader.strategy_handler.strategies.SMA_MACD_strategy`.

---

### `itrader/trading_system/backtest_trading_system.py` (MODIFIED — composition root)

**Indentation:** TABS.

**Change-shape:**
1. **Inject SignalStore** — mirror the order-storage wiring at lines 122-125:
   ```python
   order_storage = OrderStorageFactory.create('backtest')   # existing line 123
   ```
   → add `signal_store = SignalStorageFactory.create('backtest')` and pass it to `StrategiesHandler(self.global_queue, self.feed, signal_store)` (line 95). Hold `self._signal_store = signal_store` for the accessor.
2. **Post-run accessor (D-12)** — add a method (e.g. `get_signal_store()` or `signal_records()`) returning `self._signal_store.get_all()` / the store. This is a read-model sink read post-run — NOT a cross-domain call (queue-only contract preserved). No existing accessor of this exact shape; pattern is a plain getter consistent with `core` conventions (`get_<thing>()` naming, CLAUDE.md).
3. **Relocated import** — update the `SMA_MACD_strategy` import path if `run_backtest.py`/this file imports it (D-13).

---

## Shared Patterns

### pydantic v2 model house style
**Source:** `itrader/config/portfolio.py` (lines 8-12, 33-44, 103-129)
**Apply to:** `BaseStrategyConfig`, `SMA_MACDConfig`, `EmptyStrategyConfig`
- `from pydantic import BaseModel, ConfigDict, Field` (+ `model_validator` for cross-field).
- `model_config = ConfigDict(...)` as the FIRST class attribute (here `arbitrary_types_allowed=True, frozen=True`).
- `Field(default=..., gt=0)` / `Field(default=..., ge=0, le=1)` for constraints.
- Enum fields with enum defaults (`order_type: OrderType = OrderType.MARKET`).
- v2 decorators ONLY (`@model_validator(mode="after")`) — `filterwarnings=["error"]` (RESEARCH Pitfall 5).
- 4-SPACE indentation.

### pluggable storage seam (ABC + in-memory + factory + barrel)
**Source:** `itrader/order_handler/base.py::OrderStorage` + `order_handler/storage/{in_memory_storage,storage_factory,__init__}.py`
**Apply to:** the entire `itrader/strategy_handler/storage/` package
- ABC with `@abstractmethod` + NumPy-style docstrings.
- Flat `dict[uuid.UUID, T]` single container, native-UUID key, O(1) `add`, predicate-filter list-comprehension queries.
- `Factory.create(environment)` keyed on lowercased env string; `('backtest','test') -> InMemory`; `'live'` raises `ConfigurationError` (`from itrader.core.exceptions import ConfigurationError`).
- 4-SPACE indentation (Pitfall 6 — sibling uses spaces despite tab-handler dir).

### entity-vs-event separation
**Source:** `order_handler/order.py::Order` vs `events/signal.py::SignalEvent`; `core/sizing.py::SignalIntent` (frozen fact)
**Apply to:** `SignalRecord` (D-08) — a frozen `@dataclass(frozen=True, slots=True, kw_only=True)` entity distinct from the in-flight `SignalEvent`; `id` defaulted via `field(default_factory=lambda: SignalId(idgen.generate_signal_id()))` (order.py:56 shape).

### single UUIDv7 id scheme
**Source:** `core/ids.py` (`NewType` aliases) + `outils/id_generator.py` (`generate_*_id` → `self._uuid7()`)
**Apply to:** `SignalId` + `generate_signal_id`. NEVER hand-roll a second scheme (RESEARCH Anti-Pattern).

### case-insensitive enum (`_missing_`)
**Source:** `core/enums/trading.py::TradingDirection` / `order.py::OrderType`
**Apply to:** `Timeframe` enum (D-06). Register in the `core/enums/__init__.py` barrel.

### handler-owns-injected-storage wiring
**Source:** `order_handler/order_handler.py` (`__init__` takes `order_storage`, passes to manager) + `backtest_trading_system.py:122-125` (`OrderStorageFactory.create('backtest')`)
**Apply to:** `StrategiesHandler` takes an injected `signal_store`; `TradingSystem` constructs it via `SignalStorageFactory.create('backtest')` and exposes a post-run accessor (D-12).

### Decimal money + string-path literal
**Source:** `core/sizing.py` Pitfall-1 note (lines 26-29); `FractionOfCash(Decimal("0.95"))` golden literal
**Apply to:** every Decimal in the config defaults and `SignalRecord`. `Decimal("0.95")` NEVER `Decimal(0.95)` — byte-exact against the oracle.

---

## No Analog Found

None. Every new file has an exact in-repo template:

| File | Template |
|------|----------|
| `BaseStrategyConfig` / `SMA_MACDConfig` | `config/portfolio.py` |
| `SignalStore` ABC | `order_handler/base.py::OrderStorage` |
| `InMemorySignalStore` | `order_handler/storage/in_memory_storage.py` |
| `SignalStorageFactory` | `order_handler/storage/storage_factory.py` |
| `SignalRecord` | `order_handler/order.py::Order` + `core/sizing.py::SignalIntent` |
| `Timeframe` enum | `core/enums/trading.py::TradingDirection` |
| `SignalId` / `generate_signal_id` | `core/ids.py` / `outils/id_generator.py` (same files) |

---

## Metadata

**Analog search scope:** `itrader/config/`, `itrader/order_handler/` (+ `storage/`), `itrader/core/` (`ids.py`, `sizing.py`, `enums/`), `itrader/outils/id_generator.py`, `itrader/strategy_handler/` (`base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`, `strategies_handler.py`), `itrader/events_handler/events/signal.py`, `itrader/trading_system/backtest_trading_system.py`.
**Files scanned:** 14 analog/target files read in full or targeted.
**Indentation map (CLAUDE.md / RESEARCH Pitfall 6):** TABS — `base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`, `strategies_handler.py`, `id_generator.py`, `backtest_trading_system.py`. 4 SPACES — `config.py`/config models, `strategy_handler/storage/*` (match `order_handler/storage/` sibling), `core/ids.py`, `core/enums/*`, events package, `SignalRecord` (recommend co-locating with the spaces storage seam).
**Pattern extraction date:** 2026-06-09
