# Phase 2: M2a — Identity, Money & Determinism - Pattern Map

**Mapped:** 2026-06-04
**Files analyzed:** 24 (3 new + 21 modified)
**Analogs found:** 24 / 24

> **Indentation law (per file):** `core/` and `config/` use **4 spaces**; handler modules use **tabs**.
> Each target below is tagged `[spaces]` or `[tabs]` — match the file you edit. New `core/` files
> (`ids.py`, `money.py`, `clock.py`) use **spaces** (consistent with `core/exceptions/` + `core/enums/`).

## File Classification

### New files (3)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `itrader/core/ids.py` `[spaces]` | utility (type aliases) | transform | `itrader/core/enums/order.py` (sibling shared-core type module) | role-match |
| `itrader/core/money.py` `[spaces]` | utility (money policy) | transform | `transaction_manager.py::_calculate_transaction_cost` (existing `Decimal(str(...))` pattern) | exact (pattern), new file |
| `itrader/core/clock.py` `[spaces]` | provider (clock) | request-response | `order_validator.py:287` (`signal.time.time()` event-time idiom) + `core/exceptions/base.py` (spaces base-class style) | role-match |

### Modified files (21)

| Modified File | Role | Data Flow | Indent | Closest Analog / Self |
|---------------|------|-----------|--------|-----------------------|
| `itrader/outils/id_generator.py` | utility (id facade) | transform | tabs | self (replace body) |
| `itrader/order_handler/order.py` | model (entity) | CRUD | tabs | self (`id` field :50) |
| `itrader/portfolio_handler/transaction.py` | model (entity) | CRUD | tabs | self (`id` :28, money fields :24-27) |
| `itrader/portfolio_handler/position.py` | model (entity) | CRUD | tabs | self (`id` :38) |
| `itrader/portfolio_handler/portfolio.py` | model (entity) | CRUD | tabs | self (`portfolio_id` :44, `cash` arg :37) |
| `itrader/strategy_handler/base.py` | model + ABC base | event-driven | tabs | self (`strategy_id` :19) |
| `itrader/screeners_handler/screeners/base.py` | model + ABC base | event-driven | tabs | self (`id` :24, `@abstractmethod` :67) |
| `itrader/portfolio_handler/transaction_manager.py` | service (money) | CRUD | spaces | self (`cash += float(...)` :229) |
| `itrader/portfolio_handler/cash_manager.py` | service (money) | CRUD | spaces | `transaction_manager.py` Decimal style |
| `itrader/order_handler/storage/in_memory_storage.py` | store | CRUD | spaces | self (`Union[str,int]` keys) |
| `itrader/core/exceptions/base.py` | utility (exceptions) | transform | spaces | self (`entity_id: int` :45,62,77) |
| `itrader/core/exceptions/portfolio.py` | utility (exceptions) | transform | spaces | `base.py` retype pattern |
| `itrader/execution_handler/exchanges/base.py` | Protocol base | request-response | tabs | self (`__metaclass__` :17) |
| `itrader/execution_handler/base.py` | ABC base | event-driven | tabs | self (`__metaclass__` :21) |
| `itrader/price_handler/base.py` | Protocol base | streaming | tabs | self (`__metaclass__` :18) |
| `itrader/strategy_handler/position_sizer/base.py` | Protocol base | transform | spaces | self (`__metaclass__` :10) |
| `itrader/reporting/base.py` | ABC base | batch | spaces | self (`__metaclass__` :23) |
| `itrader/universe/universe.py` | ABC base | event-driven | tabs | self (`__metaclass__` :9) |
| `itrader/portfolio_handler/base.py` | ABC base | CRUD | tabs | self (`__metaclass__` :15,34) [D-08b extra] |
| `itrader/trading_system/simulation/base.py` | ABC base | event-driven | spaces | self (`__metaclass__` :22) [D-08b extra] |
| `itrader/execution_handler/exchanges/simulated.py` | service (exchange) | request-response | tabs | self (conformance + `random.*` :142,150,181,338) |
| `itrader/execution_handler/slippage_model/fixed_slippage_model.py` | service (slippage) | transform | spaces | self (`random.uniform` :61) |
| `itrader/execution_handler/slippage_model/linear_slippage_model.py` | service (slippage) | transform | spaces | self (`random.uniform` :63) |
| `pyproject.toml` | config | — | toml | self ([tool.pytest] :37) |
| `Makefile` | config | — | make | self (`test:` :27) |
| `test/test_integration/test_backtest_oracle.py` | test | batch | spaces | self (`check_exact=True` :98-103) |

---

## Pattern Assignments

### `itrader/outils/id_generator.py` (utility, transform) `[tabs]`

**Self-modification.** Replace the integer timestamp+counter+prefix body (lines 26-58) with a single
`uuid_utils.compat.uuid7()` call; keep the 6 method names so the ~7 call sites stay byte-identical.

**Current body to delete** (lines 14-58): the `__init__` counters/`_lock`/`_last_timestamp`,
`_generate_unique_id`, and the `type_prefix * 10**19 + ...` formula (the only `* 10**19` site in the
tree — D-13 prefix-decode verified absent).

**Current method signatures to retype** (return `int` → `uuid.UUID`):
```python
	def generate_transaction_id(self) -> int:   # → -> uuid.UUID
		return self._generate_unique_id('transaction_counter', 1)
	def generate_order_id(self) -> int:          # → -> uuid.UUID
		return self._generate_unique_id('order_counter', 4)
	# ... portfolio/position/strategy/screener identical
```

**Target body** (RESEARCH Pattern 1 — `uuid_utils.compat`, NOT top-level `uuid_utils.uuid7()`):
```python
import uuid
import uuid_utils.compat as uuid_compat   # compat → returns stdlib uuid.UUID

class IDGenerator:
	def _uuid7(self) -> uuid.UUID:
		return uuid_compat.uuid7()
	def generate_order_id(self) -> uuid.UUID: return self._uuid7()
	# ... 6 methods, each -> uuid.UUID (or the matching NewType alias from core/ids.py)
```
> CRITICAL (Pitfall 1): `uuid_utils.uuid7()` returns the custom `uuid_utils.UUID`; only
> `uuid_utils.compat.uuid7()` returns stdlib `uuid.UUID` (D-14 requires native). Smoke-assert:
> `assert type(idgen.generate_order_id()) is uuid.UUID`.
> Singleton stays inside `itrader/__init__.py` (`from itrader import idgen`) — do not change the
> import-time contract.

---

### `itrader/core/ids.py` (NEW — utility, transform) `[spaces]`

**Analog:** `itrader/core/enums/order.py` (sibling shared-core type module — same tier, spaces, simple
module-level definitions imported across all handlers).

**Module style to mirror** (from `core/enums/__init__.py` — barrel re-export, docstring header):
```python
"""
Core enums for the iTrader system.
"""
from .portfolio import (PortfolioState, PositionSide, TransactionType, ...)
```

**Target content** (RESEARCH Pattern 2 — `NewType` over `uuid.UUID`, D-12):
```python
import uuid
from typing import NewType

OrderId       = NewType("OrderId", uuid.UUID)
PortfolioId   = NewType("PortfolioId", uuid.UUID)
PositionId    = NewType("PositionId", uuid.UUID)
TransactionId = NewType("TransactionId", uuid.UUID)
StrategyId    = NewType("StrategyId", uuid.UUID)
ScreenerId    = NewType("ScreenerId", uuid.UUID)
```
> Optionally re-export from `core/__init__.py` to match the enums/exceptions barrel convention.

---

### `itrader/core/money.py` (NEW — utility, transform) `[spaces]`

**Analog:** `transaction_manager.py::_calculate_transaction_cost` (lines 239-255) — the codebase
**already has the correct entry pattern** (`Decimal(str(transaction.price))`); centralize it here.

**Existing correct pattern to lift** (`transaction_manager.py:246-255`):
```python
        price = Decimal(str(transaction.price))
        quantity = Decimal(str(transaction.quantity))
        commission = Decimal(str(transaction.commission))
        ...
        return -(price * quantity + commission)   # full precision, no intermediate quantize
```
Note `transaction_manager.py:7` already imports `from decimal import Decimal, ROUND_HALF_UP` — mirror.

**Target content** (RESEARCH Pattern 3 — D-01…D-04):
```python
from decimal import Decimal, ROUND_HALF_UP

_DEFAULT_SCALES = {"price": Decimal("0.01"), "quantity": Decimal("0.00000001"), "cash": Decimal("0.01")}
_INSTRUMENT_SCALES = {
    "BTCUSD": {"price": Decimal("0.00000001"), "quantity": Decimal("0.00000001"), "cash": Decimal("0.01")},
}

def to_money(x) -> Decimal:                       # D-04 entry: str() avoids float-repr artifacts
    return Decimal(str(x))

def quantize(value: Decimal, instrument: str, kind: str) -> Decimal:  # D-03 HALF_UP at boundaries only
    scale = _INSTRUMENT_SCALES.get(instrument, _DEFAULT_SCALES).get(kind, _DEFAULT_SCALES[kind])
    return value.quantize(scale, rounding=ROUND_HALF_UP)
```
> Anti-pattern (Pitfall 5): quantize ONLY at boundaries (cash ledger write / reported PnL / serialize),
> never per-multiply. Anti-pattern: `Decimal(float)` — always `Decimal(str(x))`.

---

### `itrader/core/clock.py` (NEW — provider, request-response) `[spaces]`

**Analog:** `order_validator.py:287` (`current_time = signal.time.time()` — the existing event-time
idiom to mirror); base-class spaces style from `core/exceptions/base.py`.

**Target content** (RESEARCH Pattern 5 — D-09/D-10):
```python
from typing import Protocol
from datetime import datetime

class Clock(Protocol):
    def now(self) -> datetime: ...

class BacktestClock:
    def __init__(self) -> None: self._t: datetime | None = None
    def set_time(self, t: datetime) -> None: self._t = t
    def now(self) -> datetime:
        assert self._t is not None, "BacktestClock not advanced"
        return self._t

class WallClock:
    def now(self) -> datetime: return datetime.now()
```
> D-10 scope: build the mechanism + replace **engine-path** `datetime.now()` only. **Do NOT** convert
> `order.py` audit timestamps or transaction timestamps (M2b SC2). **Keep** perf-telemetry wall-clock
> at `backtest_trading_system.py:97,105` (run-duration is not a domain fact, D-09).

---

### Entity `id`/money field retyping (model, CRUD) `[tabs]`

All five entities + two base entities currently type `id`/`*_id` as `int` and money as `float`.
**Self-modify the field declarations; the `idgen.generate_*()` call sites stay byte-identical** (only
return type changes).

**`order.py:40-66`** — `id: int` → `UUID` (or `OrderId`); `price: float`/`quantity: float` →
`Decimal`; `strategy_id: int`/`portfolio_id: int` → aliases; `parent_order_id: Optional[int]` /
`child_order_ids: List[int]` → `UUID`. The `field(default_factory=lambda: idgen.generate_order_id())`
at :50 is unchanged (factory return type now `UUID`).
> Do NOT freeze `Order` (Open Q3): it is a mutable entity (`updated_at`/`status`/`state_changes`
> mutated in place). Leave `created_at`/`updated_at` `default_factory=datetime.now` for M2b.

**`transaction.py:21-29`** — `price/quantity/commission: float` → `Decimal`; `portfolio_id: int`,
`id: int`, `position_id: int` → aliases. `cost`/`total_cost` properties (:38-60) return `Decimal`.
`new_transaction` (:82-91) passes `idgen.generate_transaction_id()` — unchanged.

**`position.py:38`** — `self.id = idgen.generate_position_id()`; many `float` money attrs (:41-48) →
`Decimal`; `portfolio_id: int` → alias.

**`portfolio.py:37,44`** — `cash: float` constructor arg → `Decimal`;
`self.portfolio_id = idgen.generate_portfolio_id()`; `user_id: int`. NB: the `self.portfolio.cash +=`
routing through `CashManager` is **M4** — M2a only types the field `Decimal`.

**`strategy_handler/base.py:19`** — `self.strategy_id = idgen.generate_strategy_id()` (also converted
to ABC, see below). **`screeners/base.py:24`** — `self.id = idgen.generate_screener_id()`.

---

### `itrader/portfolio_handler/transaction_manager.py` (service, money) `[spaces]`

**THE money defect** (line 229):
```python
        old_cash = self.portfolio.cash
        self.portfolio.cash += float(transaction_cost)     # ← float() round-trip — REMOVE the cast
```
M2a: type `portfolio.cash` `Decimal` and drop `float(...)` → `self.portfolio.cash += transaction_cost`.
Also drop the defensive `Decimal(str(self.portfolio.cash))` at :205 once `cash` is already `Decimal`.
Remove `float(...)` casts in log/error payloads (:170,176,185,209-211,236) where they re-floatify money
(keep `str(...)` for log values — already used at :217-218).
> Do NOT route through `CashManager` (M4 #22). M2a types fields + removes the round-trip only.

---

### `itrader/order_handler/storage/in_memory_storage.py` (store, CRUD) `[spaces]`

**Current loose keying** (every method): `order_key = str(order.id)`, params typed
`Union[str, int]`. Tighten to native `UUID` (D-14) and add the flat index.

**Current pattern** (`add_order` :32-42, repeated across all methods):
```python
        portfolio_key = str(order.portfolio_id)
        order_key = str(order.id)
        self.all_orders.setdefault(portfolio_key, {})[order_key] = order
```
**Targets:** retype the ~14 `Union[str, int]` params (`:44,89,144,164,175,196,...`) to `uuid.UUID`;
add a flat `self._by_id: Dict[uuid.UUID, 'Order']` alongside the nested dicts; populate in
`add_order`/`update_order`, read in `get_order_by_id` (replaces the O(n) cross-portfolio scan at
:185-194), remove in `remove_order`/`_remove_order_search_all`.
> Scope (RESEARCH Pattern 7): add the flat index + UUID keying NOW; the **full** nested-scan
> elimination is M4-06 (PERF3). Keep nested dicts for portfolio-scoped queries.

---

### `itrader/core/exceptions/{base,portfolio}.py` (utility) `[spaces]`

**Current** (`base.py:45,62,77`): `entity_id: int = None`. Retype to the `core/ids.py` aliases / `UUID`.
```python
    def __init__(self, entity_id: int, current_state: str, ...):   # → entity_id: uuid.UUID
```
`portfolio.py` mirrors: `portfolio_id: int` / `transaction_id: int` → `PortfolioId` / `TransactionId`.
> `= None` defaults on non-Optional params will trip `mypy --strict` — fix to `Optional[...] = None`
> while retyping (this is part of the M2-03 strict pass).

---

## Shared Patterns

### Pattern A — Dead `__metaclass__ = ABCMeta` → real ABC / Protocol (D-07/D-08/D-08b)

**Apply to all 11 bases.** Current dead pattern (identical in every base file):
```python
from abc import ABCMeta, abstractmethod
class AbstractExchange(object):
	__metaclass__ = ABCMeta          # ← Py2 no-op on Py3; enforces NOTHING
	@abstractmethod
	def execute_order(self, event): ...
```

**ABC conversion** (subclasses inherit shared impl/lifecycle) — `execution_handler/base.py`,
`reporting/base.py`, `universe/universe.py`, `strategy_handler/base.py`, `screeners/base.py`,
`portfolio_handler/base.py` (×3 classes), `trading_system/simulation/base.py`:
```python
from abc import ABC, abstractmethod
class AbstractExecutionHandler(ABC):    # was (object) + __metaclass__ = ABCMeta
    @abstractmethod
    def on_order(self, event: OrderEvent) -> None: ...
```

**Protocol conversion** (swap-a-fake structural seams) — `execution_handler/exchanges/base.py`,
`price_handler/base.py`, `strategy_handler/position_sizer/base.py`:
```python
from typing import Protocol, runtime_checkable
@runtime_checkable
class AbstractExchange(Protocol):
	def execute_order(self, event: OrderEvent) -> ExecutionResult: ...
	def configure(self, config: dict) -> bool: ...
```

**Per-base classification** (D-07 + D-08b extras):
| Base file | Class | Target | Notes |
|-----------|-------|--------|-------|
| `execution_handler/exchanges/base.py` | `AbstractExchange` | **Protocol** | declares `configure`/`is_connected`/`validate_symbol` |
| `execution_handler/base.py` | `AbstractExecutionHandler` | **ABC** | holds queue + routing |
| `price_handler/base.py` | `AbstractPriceHandler` | **Protocol** | eases M5 split; has `__future__ print_function` line to drop |
| `position_sizer/base.py` | `AbstractPositionSizer` | **Protocol** | `[spaces]` |
| `reporting/base.py` | `AbstractStatistics` | **ABC** | `[spaces]`; `print_summary`/`update`/`get_results`/`plot_results`/`save` abstract |
| `universe/universe.py` | `Universe` | **ABC** | minimal conformance only (collapse is M5b #33) |
| `strategy_handler/base.py` | `Strategy` | **ABC** | bare `class Strategy(object)` — NO metaclass today; add `ABC` |
| `screeners/base.py` | `Screener` | **ABC** | `@abstractmethod screen_market` (:67) has **self-less** signature `(prices, event)` — fix to `(self, prices, event)` |
| `portfolio_handler/base.py` | `AbstractPortfolioHandler`, `AbstractPortfolio`, `AbstractPosition` | **ABC** ×3 | D-08b extra (log COVERAGE-INDEX §E) |
| `trading_system/simulation/base.py` | `SimulationEngine` | **ABC** | D-08b extra (log §E); `[spaces]` |

> **Pitfall 3 (the #20 payoff):** flipping `AbstractExchange` to a real Protocol/ABC starts enforcing
> abstract methods. `SimulatedExchange` (`exchanges/simulated.py`) ALREADY implements `configure` is
> NOT present — but it DOES have `is_connected` (:319), `validate_symbol` (:411), `connect`/`disconnect`
> /`health_check`/`validate_order`/`execute_order`/`on_order`/`on_market_data`. **Verify `configure`**:
> grep shows no `def configure` — add a minimal `configure(self, config) -> bool` (D-08 minimal
> conformance). `update_config` (:502) exists but is not the ABC method name.

### Pattern B — Injected seeded `Random` (D-11)

**Apply to:** `fixed_slippage_model.py:61`, `linear_slippage_model.py:63`, `simulated.py:142,150,181,338`.

**Current (forbidden) module-level `random.*`** (`fixed_slippage_model.py:5,61`):
```python
import random
        slippage = random.uniform(-self.slippage_pct, self.slippage_pct) / 100.0   # :61
```
**Target** (RESEARCH Pattern 6 — accept an injected instance):
```python
    def __init__(self, slippage_pct=0.01, random_variation=True, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        ...
        slippage = self._rng.uniform(-self.slippage_pct, self.slippage_pct) / 100.0
```
`simulated.py` sites: `random.random() < self.failure_rate` (:142), `random.choice(error_scenarios)`
(:150), `random.uniform(5, 25)` (:181), `random.uniform(10, 50)` (:338) → `self._rng.*`; accept `rng`
in `__init__` (:41) and store `self._rng`. The wall-clock `datetime.now()` sites in `simulated.py`
(:88,106,280,325,352,453) are **live/health-telemetry** — leave as wall-clock (D-09/D-10).
> No oracle impact (M1 runs failure-sim off + zero slippage). Seed source = config (Pattern C).

### Pattern C — Config seed source (D-11)

**Analog:** `itrader/config/system/config.py` (`@dataclass` settings classes, `[spaces]`, e.g.
`PerformanceSettings` :30-40 with typed defaults). Add a documented default-seed key here (or the
`exchange` domain) following the same `@dataclass` + `field`-default convention:
```python
@dataclass
class PerformanceSettings:
    max_threads: int = 10        # ← add e.g.  rng_seed: int = 42  (documented default)
```
Engine wiring constructs `random.Random(seed)` from this and injects it into the slippage models +
`SimulatedExchange` at `ExecutionHandler.__init__`/`backtest_trading_system.py` construction.

### Pattern D — mypy strict gate (D-05/D-06)

**Apply to:** `pyproject.toml` (new `[tool.mypy]`), `Makefile` (new `typecheck` target).

`pyproject.toml` — add after `[tool.pytest.ini_options]` (RESEARCH Code Examples):
```toml
[tool.mypy]
python_version = "3.13"
strict = true
files = ["itrader"]

[[tool.mypy.overrides]]
module = [
    "itrader.trading_system.live_trading_system",   # D-live
    "itrader.trading_system.trading_interface",     # D-live
    "itrader.price_handler.sql_handler",            # D-sql
    "itrader.price_handler.exchange.CCXT",          # D-oanda
    "itrader.price_handler.exchange.OANDA",         # D-oanda
    "itrader.price_handler.live_streaming.BINANCE_Live",  # D-live
    "itrader.screeners_handler.*",                  # D-screener
]
ignore_errors = true

[[tool.mypy.overrides]]
module = ["ta.*", "pandas_ta.*", "ccxt.*"]
ignore_missing_imports = true
```
Also add `mypy = "^2.1.0"` to `[tool.poetry.group.dev.dependencies]` (currently absent; install with
`poetry add --group dev mypy@^2.1.0`) and `uuid-utils = "^0.16.0"` to `[tool.poetry.dependencies]`
(`poetry add uuid-utils@^0.16.0`).

`Makefile` — mirror the existing `test:` target style (:27-29, tab-indented recipe):
```makefile
typecheck:
	@echo "🔍 Running mypy --strict..."
	poetry run mypy itrader
```
Add `typecheck` to the `.PHONY` line (:6).
> Pitfall 6: mypy 2.1.0 is newer than common knowledge — validate `[tool.mypy]` keys against the
> installed version (`poetry run mypy --help`) before committing the config.

### Pattern E — D-15 oracle test tolerance (test, batch) `[spaces]`

**Current** (`test_backtest_oracle.py:97-103`) — `check_exact=True` on the FULL frame:
```python
    pdt.assert_frame_equal(fresh_trades_sorted, golden_trades_sorted,
                           check_exact=True, check_like=True)
```
**Target** — split identity-EXACT from numeric-TOLERANT (`_TRADE_KEY_COLUMNS` already defined at :39):
```python
    pdt.assert_frame_equal(fresh_trades_sorted[_TRADE_KEY_COLUMNS],
                           golden_trades_sorted[_TRADE_KEY_COLUMNS], check_exact=True)  # behavioral LAW
    _NUMERIC = [c for c in fresh_trades_sorted.columns if c not in _TRADE_KEY_COLUMNS]
    pdt.assert_frame_equal(fresh_trades_sorted[_NUMERIC], golden_trades_sorted[_NUMERIC],
                           check_exact=False, rtol=1e-9, atol=1e-2)  # D-15 transitional — re-frozen EXACT at M2b
```
Apply the same split to the equity frame (:116-121) and the summary-key loop (:124+).
> Tolerance magnitude is Claude's discretion (start `atol=1e-2`/`rtol=1e-9`, tighten empirically).
> Comment each inline: `# D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)`.

### Pattern F — `frozen=True`/`slots=True` rollout (M2-03, discretion)

**Apply to:** genuinely-immutable hot-path events in `event.py` (`@dataclass` decorators).
**Do NOT freeze `SignalEvent`** — `verified` is mutated at `event.py:235` (Pitfall 4 →
`FrozenInstanceError`). Audit each of ~9 events for post-construction assignment before freezing;
defer ambiguous ones to M3 (#11). `event.py:6` already imports `from uuid import uuid4` for
event-level concerns — that is M3's domain, do NOT touch it in M2a.

---

## Test scaffolding (Wave 0 — new dirs need markers)

| New test file | Covers | conftest `DIR_MARKERS` note |
|---------------|--------|-----------------------------|
| `test/test_outils/test_id_generator.py` | M2-01 (uuid7 type/uniqueness/ordering) | add `"test_outils": "unit"` |
| `test/test_core/test_money.py` | M2-02 (quantize HALF_UP, per-instrument, `to_money`) | add `"test_core": "unit"` |
| `test/test_core/test_clock.py` | M2-05 (Clock returns bar time; advance contract) | (same `test_core` entry) |

> `--strict-markers` is active (`pyproject.toml:48`) — every new test dir needs a `DIR_MARKERS` entry
> in `conftest.py` or an explicit `@pytest.mark.unit`, else discovery fails.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All 24 targets have a concrete in-tree analog (mostly self-modification or a sibling shared-core module). The 3 new `core/` files follow the established `core/enums/` + `core/exceptions/` sibling convention and the existing `Decimal(str(...))` pattern in `transaction_manager.py`. |

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/outils/`, `itrader/portfolio_handler/`,
`itrader/order_handler/`, `itrader/execution_handler/`, `itrader/strategy_handler/`,
`itrader/screeners_handler/`, `itrader/price_handler/`, `itrader/reporting/`, `itrader/universe/`,
`itrader/trading_system/`, `itrader/config/`, `itrader/events_handler/`, `test/test_integration/`,
`pyproject.toml`, `Makefile`
**Files scanned:** ~28 read in full or targeted; all CONTEXT.md/RESEARCH.md line refs verified.
**Pattern extraction date:** 2026-06-04
