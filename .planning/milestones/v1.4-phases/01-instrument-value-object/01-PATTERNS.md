# Phase 1: Instrument Value Object - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 9 (3 new, 6 modified)
**Analogs found:** 9 / 9

> Source-of-truth caveat: RESEARCH.md verified every claim below at file:line.
> Where RESEARCH and this map agree, prefer the file:line citations here.
> All `Instrument`/`quantize`/`Universe` work must stay **byte-exact** against the
> SMA_MACD oracle (134 trades / `final_equity 46189.87730727451`) and
> **mypy --strict clean** (core/, universe/membership.py, backtest_runner.py are all in-scope).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| NEW `itrader/core/instrument.py` | model (frozen value object) | transform (read-off scale) | `itrader/core/bar.py::Bar` | exact (frozen VO template) | **4 spaces** |
| MODIFY `itrader/core/money.py` | utility (rounding mechanism) | transform | self (`quantize` rewire) | self-modify | **4 spaces** |
| NEW `itrader/universe/universe.py` (`Universe` class) | read-model / provider | request-response (poll) | `core/portfolio_read_model.py` + `price_handler/feed/bar_feed.py::BacktestBarFeed` | role-match (injected read-model) | **4 spaces** |
| NEW `itrader/universe/instruments.py` (`derive_instruments`) — or fold into `membership.py` | utility (pure derive-once) | batch / transform | `universe/membership.py::derive_membership` | exact (pure derive-once sibling) | **4 spaces** |
| MODIFY `itrader/universe/__init__.py` (barrel) | config (barrel re-export) | — | self (existing barrel) | self-modify | **4 spaces** |
| MODIFY `itrader/trading_system/backtest_runner.py` | composition root (wiring) | event-driven loop | self (`_initialise_backtest_session`) | self-modify | **TABS** |
| MODIFY `itrader/trading_system/compose.py` (`Engine` field) | composition root (DI holder) | — | self (`Engine` dataclass) | self-modify | **TABS** |
| MODIFY `itrader/execution_handler/exchanges/simulated.py` | service (exchange) | request-response (admission) | self (`_min_order_size` read/use) | self-modify | **TABS** |
| MODIFY `itrader/config/exchange.py` (`ExchangeLimits` demote) | config (pydantic model) | — | self (`ExchangeLimits`) | self-modify | **4 spaces** |

**Indentation hazard (Pitfall 5):** `backtest_runner.py`, `compose.py`, `simulated.py` are **TABS**; `core/`, `config/`, `universe/` are **4 spaces**. New files in `core/`/`universe/` → 4 spaces. NEVER normalize.

---

## Pattern Assignments

### `itrader/core/instrument.py` (NEW — frozen value object)

**Analog:** `itrader/core/bar.py::Bar` (the exact in-tree template).

**Frozen-VO + module-docstring + Decimal-string-path pattern** (`core/bar.py:23-68`):
```python
from dataclasses import dataclass
from datetime import datetime          # not needed by Instrument; drop unused imports
from decimal import Decimal
from typing import Any, Mapping

@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    time: datetime
    open: Decimal
    # ... full-precision Decimal fields, never rounded

    @classmethod
    def from_row(cls, time: datetime, row: Mapping[str, Any]) -> "Bar":
        return cls(
            open=Decimal(str(row["open"])),   # D-14 string path, NEVER Decimal(float)
            ...
        )
```

**Copy these exact conventions onto `Instrument`:**
- `@dataclass(frozen=True, slots=True, kw_only=True)` — same decorator line, byte-for-byte.
- Module docstring citing the decision tags (D-04, D-05, D-01a, D-10) — `bar.py:1-21` is the style template.
- Decimal fields entered via the string path (`Decimal(str(x))` / `to_money`) in any factory — NEVER `Decimal(float)`.
- Intra-`core` import of `to_money` from `money.py` is allowed (D-05).

**Field set** (RESEARCH §2; YAGNI-gated to named consumers):
```python
symbol: str                              # upper-cased; universe key
quote_currency: str = "USD"              # source of kind="cash" scale -> 2dp
price_precision: Decimal                 # store the SCALE Decimal directly (Pitfall 3):
                                         #   BTCUSD = Decimal("0.00000001")
quantity_precision: Decimal              # BTCUSD = Decimal("0.00000001")
min_order_size: Decimal | None = None    # D-01a: UNDECLARED (None) for BTCUSD
maintenance_margin_rate: Decimal         # inert Phase 1 (Phase 4 consumer)
max_leverage: Decimal                    # inert Phase 1 (Phase 2 consumer)
settles_funding: bool = False            # inert Phase 1 (Phase B deferred)
```

> **Pitfall 3 (byte-exact):** store the Decimal **scale** (`Decimal("0.00000001")`) directly, NOT an int place-count. If an int `price_precision: int = 8` is chosen instead, add a test asserting `Decimal(1).scaleb(-8) == Decimal("0.00000001")`. Storing the scale is the lower-risk choice (RESEARCH A1).

---

### `itrader/core/money.py` (MODIFY — `quantize` rewire, delete `_INSTRUMENT_SCALES`)

**Analog:** self. The current code is the rewire target.

**Current `quantize` + tables** (`money.py:38-76`):
```python
_DEFAULT_SCALES: dict[str, Decimal] = {
    "price": Decimal("0.01"),
    "quantity": Decimal("0.00000001"),
    "cash": Decimal("0.01"),
}
_INSTRUMENT_SCALES: dict[str, dict[str, Decimal]] = {       # <-- DELETE this whole table
    "BTCUSD": {"price": Decimal("0.00000001"),
               "quantity": Decimal("0.00000001"),
               "cash": Decimal("0.01")},
}

def quantize(value: Decimal, instrument: str, kind: str) -> Decimal:   # <-- str -> Instrument
    scale = _INSTRUMENT_SCALES.get(instrument, _DEFAULT_SCALES).get(
        kind, _DEFAULT_SCALES[kind])
    return value.quantize(scale, rounding=ROUND_HALF_UP)
```

**Rewire to** (D-05 — pure/stateless, reads scale off the handed-in `Instrument`):
- Signature: `quantize(value: Decimal, instrument: Instrument, kind: str) -> Decimal`.
- `kind -> field` map (Claude's Discretion, RESEARCH §2): `"price" -> instrument.price_precision`, `"quantity" -> instrument.quantity_precision`, `"cash" -> _DEFAULT_SCALES["cash"]` (2dp, derived from `quote_currency`, default `"USD"`).
- Keep `ROUND_HALF_UP` (`money.py:76`) unchanged.
- Keep `_DEFAULT_SCALES` (the no-data fallback, D-09).
- **Delete `_INSTRUMENT_SCALES`** — RESEARCH §1 proves zero non-docstring references outside this module.
- Import `Instrument` from `itrader.core.instrument` (intra-core, allowed by D-05).
- Update the module docstring (currently D-02 "per-instrument scales" at `money.py:12-13`) to reflect Instrument-driven scales.

> **D-02a blast radius (PROVEN, RESEARCH §1):** the module function `quantize()` is imported ONLY by `tests/unit/core/test_money.py:27`. Every production `.quantize(` (e.g. `cash_manager.py:64,502`, `validators.py:140`) is the stdlib `Decimal.quantize()` **method** — untouched. The production rounding path changes by **zero bytes**, so the oracle holds by construction.

---

### `tests/unit/core/test_money.py` (MODIFY — pass `Instrument` not `str`)

**Analog:** self. Three call sites at `test_money.py:45,50,57` pass a `str`:
```python
quantize(Decimal("1.005"), "BTCUSD", "cash")        # :45 -> pass an Instrument(BTCUSD 8dp)
quantize(Decimal("0.123456785"), "BTCUSD", "quantity")  # :50 -> same Instrument
quantize(Decimal("1.005"), "UNKNOWN", "cash")       # :57 -> "default Instrument -> default scale"
```
The `"UNKNOWN"` test (`:57`) becomes a "default-Instrument → default-scale" test. `pytestmark = pytest.mark.unit` is already set (`:29`).

---

### `itrader/universe/universe.py` (NEW — `Universe` class, D-06/D-07)

**Analog (read-model shape):** `core/portfolio_read_model.py::PortfolioReadModel` (Protocol shape, precise return types, docstring style) AND `BacktestBarFeed` (object constructed once at wiring, injected).

**Analog (composition target):** `universe/membership.py::derive_membership` / `is_active` — the `Universe` **delegates** to these pure fns, never reimplements them (D-07).

**Read-model method/docstring conventions to copy** (`core/portfolio_read_model.py:42-49,78-107`):
```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["PortfolioReadModel", "PositionView"]      # explicit public surface

@runtime_checkable
class PortfolioReadModel(Protocol):
    def available_cash(self, portfolio_id: PortfolioId) -> Decimal: ...   # precise return types
    def get_position(self, portfolio_id, ticker: str) -> PositionView | None: ...
```

**`Universe` surface (D-06; concrete class is fine — RESEARCH §8):**
- `.members -> list[str]` — MUST return the **same set-derived `list[str]`** `derive_membership` produces today so `feed.bind` stays byte-exact (Pitfall 4).
- `.instrument(symbol: str) -> Instrument` — looks up the injected `dict[str, Instrument]`.
- `.is_active(symbol, asof) -> bool` (OPTIONAL) — fold only if a Phase-1 consumer needs it; RESEARCH OQ2 recommends **defer** (none identified) to keep D-07 scope discipline.
- Constructed from the already-computed `membership` list + the `derive_instruments` map (do NOT recompute membership inside `Universe`).
- Strict-clean: `.members -> list[str]`, `.instrument -> Instrument`, no `Any`.

---

### `itrader/universe/instruments.py` (NEW — `derive_instruments`, D-07) OR fold into `membership.py`

**Analog:** `universe/membership.py::derive_membership` (`membership.py:44-79`) — the exact pure derive-once-at-wiring sibling.

**Pure-function + docstring-style + SupportsTickers Protocol pattern** (`membership.py:28-79`):
```python
from collections.abc import Iterable, Sequence
from typing import Protocol

class SupportsTickers(Protocol):
    @property
    def tickers(self) -> Sequence[str | tuple[str, ...]]: ...

def derive_membership(
    strategies: Iterable[SupportsTickers],
    screener_tickers: Iterable[str] = (),
) -> list[str]:
    """... NumPy-style Parameters/Returns; cites M5-08/D-20 ..."""
    ...
    return list(set(tickers))   # set-derived, order unspecified
```

**Copy onto `derive_instruments`:**
- Pure function, no class/state/queue/feed import (mirror `is_active`/`derive_membership` purity rule, `membership.py:90-94`).
- Signature (RESEARCH §3): `derive_instruments(strategies, screener_tickers, declared_config, price_data) -> dict[str, Instrument]` (precise dict type, NOT `dict[str, Any]`).
- NumPy-style `Parameters`/`Returns` docstring citing the decision tags.
- Build the precision ladder per symbol (D-09): **declared → inferred (guarded) → default**.
- **Declared-config home** (OQ1, Claude's Discretion): RESEARCH recommends a small in-code declared table in this module for Phase 1 (one symbol: `BTCUSD` price 8dp, quantity 8dp, `min_order_size` UNDECLARED), reproducing `_INSTRUMENT_SCALES["BTCUSD"]` exactly.

> **Inference guard (Pitfall 1, INST-02):** the loaded frame is float64 (`csv_store.py:178` `.astype(float)`). String-inference MUST read the **raw CSV cell** (e.g. `pd.read_csv(..., dtype={'Close': str})`) before the float cast, count decimal places, **cap at 8dp**. BTCUSD never hits this path (D-10 declared wins) — cover INST-02 with a **synthetic non-oracle symbol** fixture.

---

### `itrader/universe/__init__.py` (MODIFY — barrel)

**Analog:** self (`universe/__init__.py:11-17`):
```python
from .membership import active_membership, derive_membership, is_active
__all__ = ['active_membership', 'derive_membership', 'is_active']
```
Add `Universe` and `derive_instruments` to imports + `__all__` (single-quote string style, matching this file). 4 spaces.

---

### `itrader/trading_system/backtest_runner.py` (MODIFY — wiring; **TABS**)

**Analog:** self. The Trap-4-ordered session setup at `backtest_runner.py:46-81`.

**Trap-4 ordering (PRESERVE EXACTLY — Pitfall 4)** (`backtest_runner.py:60-81`):
```python
membership = derive_membership(
    engine.strategies_handler.strategies,
    engine.screeners_handler.get_screeners_universe())  # type: ignore[no-untyped-call]
engine.feed.bind(engine.global_queue, membership)       # <-- must receive SAME list
# ... ping-grid reduce(pd.Index.union) -> time_generator.set_dates
# ... per-strategy feed.precompute in registration order
```

**Change shape (D-08):** construct the `Universe` here from the already-computed `membership` + `derive_instruments(...)` map, then pass `universe.members` (the same list) to `feed.bind`. Set the universe onto the `Engine` for injection downstream. Do NOT reorder membership-derive → feed.bind → ping-grid → precompute. **TABS** (file convention noted in its own docstring at `backtest_runner.py:19`).

> Live mirror: `live_trading_system.py:259-263` (same shape, **mypy-deferred** — `ignore_errors=true` at `pyproject.toml:88`). Keep it behavior-byte-exact but it won't break the gate.

---

### `itrader/trading_system/compose.py` (MODIFY — `Engine` field; **TABS**)

**Analog:** self. The `Engine` dataclass at `compose.py:80-101`:
```python
@dataclass
class Engine:
    global_queue: "queue.Queue[Any]"
    clock: BacktestClock
    store: CsvPriceStore
    feed: BacktestBarFeed
    ...
    time_generator: TimeGenerator
```
Add a `universe: Universe` field (populated in wiring order, Trap-4-respecting). **TABS**.

---

### `itrader/execution_handler/exchanges/simulated.py` (MODIFY — min_order_size resolution; **TABS**)

**Analog:** self. Read point and use site.

**Current read** (`simulated.py:112-118`):
```python
# Exchange limits and settings
self._supported_symbols = self.config.limits.supported_symbols
# DEC-02 / D-06: size limits carried as Decimal end-to-end ...
self._min_order_size = self.config.limits.min_order_size      # <-- venue-wide today
self._max_order_size = self.config.limits.max_order_size
```

**Current use** (`simulated.py:422-425`):
```python
if event.quantity <= 0:
    failed_checks.append("Order quantity must be positive")
elif event.quantity < self._min_order_size:                  # <-- per-order admission gate
    failed_checks.append(f"Order quantity {event.quantity} below minimum {self._min_order_size}")
```

**Teach Instrument-first → ExchangeLimits-fallback (RESEARCH §6, Claude's Discretion on plumbing):**
- Resolve per-order/per-symbol: `instrument.min_order_size if instrument.min_order_size is not None else self.config.limits.min_order_size`.
- The per-order symbol is on `event` (the `OrderEvent.ticker`).
- The exchange needs access to the injected `Universe` read-model to look up the per-symbol `Instrument`.
- Because BTCUSD's `Instrument.min_order_size` is **None** (D-01a), resolution returns `ExchangeLimits(0.001)` — byte-identical to today's `self._min_order_size`.
- Also re-derived on config update at `simulated.py:696` — keep consistent.
- **TABS** — match the file.

> **Pitfall 2:** do NOT declare BTCUSD's `min_order_size`. Setting it changes the admission gate at `simulated.py:424` → oracle drift.

---

### `itrader/config/exchange.py` (MODIFY — `ExchangeLimits` demote; 4 spaces)

**Analog:** self. `ExchangeLimits` at `exchange.py:98-108`:
```python
class ExchangeLimits(BaseModel):
    """Exchange trading limits."""
    model_config = ConfigDict(extra="forbid")
    min_order_size: Decimal = Decimal("0.001")     # <-- KEEP value; reframe as venue fallback
    max_order_size: Decimal = Decimal("1000000.0")
    ...
```
**Change shape (D-01):** keep the class and the `min_order_size = Decimal("0.001")` value; **reframe the docstring** to "venue-level fallback for undeclared symbols". Do NOT change the value (byte-exact). 4 spaces (config convention).

---

## Shared Patterns

### Decimal money policy (applies to: `instrument.py`, `money.py`, `derive_instruments`)
**Source:** `itrader/core/money.py:53-60`
```python
def to_money(x: float | int | str | Decimal) -> Decimal:
    return Decimal(str(x))      # D-04 string path — NEVER Decimal(float)
```
Every Decimal field/scale on `Instrument` and every literal in the declared table enters via the string path. Store scales as `Decimal("0.00000001")` literals.

### Frozen value object (applies to: `instrument.py`)
**Source:** `itrader/core/bar.py:29`, `core/portfolio_read_model.py:52`
```python
@dataclass(frozen=True, slots=True, kw_only=True)   # bar.py:29 (kw_only) — use this for Instrument
@dataclass(frozen=True, slots=True)                 # portfolio_read_model.py:52 (positional DTO)
```
Use the `bar.py` `kw_only=True` variant for `Instrument` (named-field VO). `@dataclass` auto-derives `__eq__`/`__hash__`/immutability — do not hand-roll.

### Module docstring with decision tags (applies to: all new files)
**Source:** `core/bar.py:1-21`, `core/money.py:1-23`, `core/portfolio_read_model.py:1-40`
Open every new module with a triple-quoted docstring citing the load-bearing decision tags (D-04, D-05, D-01a, D-09, D-10, INST-01/02/03). These tags are load-bearing references to planning artifacts — preserve the style.

### Explicit `__all__` public surface (applies to: `instrument.py`, `universe.py`, `instruments.py`, `__init__.py`)
**Source:** `money.py:31`, `portfolio_read_model.py:49`, `universe/__init__.py:13`
```python
__all__ = ["Instrument"]            # core/ uses double quotes
__all__ = ['Universe', ...]         # universe/ barrel uses single quotes — match the file
```

### Injected read-model (applies to: `Universe`)
**Source:** `core/portfolio_read_model.py:78-107` (Protocol shape), `BacktestBarFeed` (wiring/injection)
Object-shaped, constructed once at wiring, injected into consumers (exchange now; margin code later). Precise return types, `runtime_checkable` Protocol only if a Protocol is wanted for injection (concrete class is acceptable — RESEARCH §8).

### Pure derive-once-at-wiring (applies to: `derive_instruments`)
**Source:** `universe/membership.py:44-79`
Pure function producing derived data at run-init; no class, no state, no queue, no feed/store import; NumPy-style docstring; precise return type (`dict[str, Instrument]`).

---

## No Analog Found

None. Every new file has a direct in-tree template, and every modification is a self-modify with the analog being the existing code.

The only **genuinely new logic** (RESEARCH "Key insight") with no copy-source:
| Logic | File | Note |
|-------|------|------|
| INST-02 string decimal-count + 8dp cap | `derive_instruments` | No in-tree precedent; raw-CSV-string read (Pitfall 1). Cover with synthetic non-oracle fixture. |
| declared-instrument table | `instruments.py` | No per-symbol config exists today (RESEARCH §4, A2); introduce a small in-code table. |

Everything else is composition over existing primitives.

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/universe/`, `itrader/trading_system/`, `itrader/config/`, `itrader/execution_handler/exchanges/`, `tests/unit/core/`
**Files read for excerpts:** `core/bar.py`, `core/money.py`, `core/portfolio_read_model.py`, `universe/membership.py`, `universe/__init__.py`, `trading_system/backtest_runner.py`, `trading_system/compose.py`, `config/exchange.py`, `execution_handler/exchanges/simulated.py`, `tests/unit/core/test_money.py`
**Pattern extraction date:** 2026-06-15
