# Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze - Pattern Map

**Mapped:** 2026-06-05
**Files analyzed:** 22 new/modified files (8 requirement clusters M2-06…M2-13)
**Analogs found:** 19 / 22 (3 NEW Pydantic files use stylistic-only analogs)

> All paths in this file are absolute-from-repo-root under `itrader/` / `test/`. Line numbers
> reflect RESEARCH.md's corrected anchors (CONTEXT.md line numbers drift by a few lines — RESEARCH
> drift flags supersede). Indentation rule is load-bearing: **handler/manager/enum/entity modules use
> TABS**; **`config/` + Pydantic models + new test files use 4-SPACES**. Match the file you edit.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/portfolio_handler/storage/base.py` (NEW) | storage ABC | CRUD | `itrader/order_handler/base.py::OrderStorage` (lines 25-325) | exact |
| `itrader/portfolio_handler/storage/in_memory_storage.py` (NEW) | storage backend | CRUD | `itrader/order_handler/storage/in_memory_storage.py` | exact |
| `itrader/portfolio_handler/storage/storage_factory.py` (NEW) | factory | request-response | `itrader/order_handler/storage/storage_factory.py` | exact |
| `itrader/portfolio_handler/storage/__init__.py` (NEW) | package init | — | `itrader/order_handler/storage/__init__.py` | exact |
| `itrader/core/enums/portfolio.py` (MODIFIED) | enum module | transform | `itrader/core/enums/order.py` | exact |
| `itrader/core/enums/execution.py` (MODIFIED — add `FillStatus`) | enum module | transform | `itrader/core/enums/order.py` | exact |
| `itrader/events_handler/event.py` (MODIFIED — move `FillStatus`/`fill_status_map`) | event defs | event-driven | `itrader/core/enums/order.py` (enum home) | role-match |
| `itrader/portfolio_handler/transaction.py` (MODIFIED — de-map) | entity | transform | `itrader/core/enums/order.py` (`_missing_` target) | role-match |
| `itrader/config/settings.py` (NEW) | config model | transform | `itrader/config/portfolio/defaults.py` (spaces style) | stylistic-only |
| `itrader/config/portfolio.py` (NEW Pydantic) | config model | transform | `itrader/config/portfolio/config.py` (spaces style) | stylistic-only |
| `itrader/config/{trading,data,system,exchange}.py` (NEW Pydantic) | config model | transform | `itrader/config/portfolio/defaults.py` (factory funcs) | stylistic-only |
| `itrader/config/__init__.py` (REWRITE) | package init | — | `itrader/core/enums/__init__.py` (clean re-export) | role-match |
| `itrader/core/constants.py` (NEW) | constants | — | `itrader/config.py` (lit source) | role-match |
| `itrader/outils/time_parser.py` (MODIFIED) | utility | transform | self (in-place edit) | self |
| `itrader/order_handler/order.py` (MODIFIED — timestamps) | entity | event-driven | self (lines 250-452) | self |
| `itrader/portfolio_handler/{cash,position,transaction,metrics}_manager.py` (MODIFIED — seam route) | manager | CRUD | self (state-container `__init__`) | self |
| `tests/conftest.py` + `tests/{unit,integration}/conftest.py` (NEW/MOVED) | test harness | — | `test/conftest.py` | exact |
| `tests/integration/test_backtest_oracle.py` (MODIFIED — D-16/17/18) | test | golden-master | `test/test_integration/test_backtest_oracle.py` | self |
| ~29 `unittest.TestCase` files → pytest (MOVED+CONVERTED) | test | — | `test/test_integration/test_backtest_oracle.py` (pytest-native) | role-match |

**DELETE (M2-11, dead-module purge — verify zero in-scope importers first):**
`itrader/legacy_config.py`, `itrader/outils/profiling.py`, `itrader/outils/strategy.py`,
the orphaned `EventHandler` in `itrader/events_handler/screener_event_handler.py`
(file is at `events_handler/`, NOT `screeners_handler/` — CONTEXT path was wrong), the flat
`itrader/config.py` shadow + the `importlib` loader in `config/__init__.py:60-76`.

---

## Pattern Assignments

### `itrader/portfolio_handler/storage/base.py` — NEW `PortfolioStateStorage` ABC (D-09/D-10, M2-08)

**Analog:** `itrader/order_handler/base.py::OrderStorage` (the ABC lives in `base.py`, NOT `storage/base.py` — RESEARCH drift flag). **Indentation: 4-spaces** (the ABC body in `order_handler/base.py` is spaces, even though the surrounding `OrderBase` class uses tabs — match the `OrderStorage` ABC's spaces).

**ABC shape to copy** (`order_handler/base.py:1-7, 25-46`):
```python
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from datetime import datetime

# Native UUID scheme (D-14); legacy str/int still accepted at the boundary.
IdLike = Union[str, int, uuid.UUID]

if TYPE_CHECKING:
    from ..position import Position          # adapt to portfolio entities
    from ..transaction import Transaction

class PortfolioStateStorage(ABC):
    """Unified seam for portfolio-manager state (positions/transactions/cash-ops/metrics)."""

    @abstractmethod
    def add_position(self, position: 'Position') -> None:
        ...
```
> One unified interface (D-09) covering all four managers — do NOT make four ABCs and do NOT
> put a storage class inside each manager folder (D-09 anti-pattern). Each abstract method is a
> bare `@abstractmethod` with a numpy-style docstring (mirror `OrderStorage`'s 14 methods, but
> scoped to the four containers: open/closed positions, pending/history transactions, reserved
> cash + cash operations, metrics snapshots). The exact method signatures are Claude's discretion.

### `itrader/portfolio_handler/storage/in_memory_storage.py` — NEW backend (D-10, M2-08)

**Analog:** `itrader/order_handler/storage/in_memory_storage.py` (read in full). **Indentation: 4-spaces** (analog is spaces).

**Import + ctor pattern** (`storage/in_memory_storage.py:1-11, 29-41`):
```python
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..base import PortfolioStateStorage, IdLike

if TYPE_CHECKING:
    from ..position import Position
    from ..transaction import Transaction

class InMemoryPortfolioStateStorage(PortfolioStateStorage):
    """Dict/list-backed in-memory state. One instance per Portfolio. Single-threaded backtest."""

    def __init__(self) -> None:
        self._positions: Dict[str, 'Position'] = {}          # was PositionManager._positions (open, keyed by ticker)
        self._closed_positions: List['Position'] = []        # was PositionManager._closed_positions
        self._pending_transactions: Dict[Any, Any] = {}      # was TransactionManager._pending_transactions
        self._transaction_history: List['Transaction'] = []  # was TransactionManager._transaction_history
        self._cash_operations: List[Any] = []                # was CashManager._cash_operations
        self._snapshots: List[Any] = []                      # was MetricsManager snapshot list
```
> These are the EXACT containers being relocated OUT of the four managers (see "Storage seam
> routing sites" below). The order analog keeps `active_orders` + `all_orders` + a flat `_by_id`
> index for O(1) lookup (`:32-41`) and "deactivate keeps in history" semantics (`:58-101`) — mirror
> the "working-state vs append-only history" split per D-10 (open positions = working; closed
> positions/transaction history/cash ops/snapshots = append-only).

### `itrader/portfolio_handler/storage/storage_factory.py` — NEW factory (D-09, M2-08)

**Analog:** `itrader/order_handler/storage/storage_factory.py` (read in full). **Indentation: 4-spaces.**

**Copy this factory verbatim, renaming** (`storage_factory.py:6-51`):
```python
from typing import Optional
from ..base import PortfolioStateStorage
from .in_memory_storage import InMemoryPortfolioStateStorage

class PortfolioStateStorageFactory:
    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> PortfolioStateStorage:
        environment = environment.lower()
        if environment in ('backtest', 'test'):
            return InMemoryPortfolioStateStorage()
        elif environment == 'live':
            if not db_url:
                raise ValueError("Database URL is required for live environment")
            # D-sql: PostgreSQL backend deferred — raise NotImplementedError or import lazily
            raise NotImplementedError("PortfolioStateStorage live backend deferred to D-sql")
        else:
            raise ValueError(
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'live', 'test'"
            )
```
> `__init__.py` mirrors `order_handler/storage/__init__.py:9-20`: re-export the ABC,
> in-memory class, factory in `__all__`. Live branch raises (D-sql out of scope) rather than
> importing a PostgreSQL module that does not exist yet.

**Wiring:** `Portfolio` injects the storage (mirror how `OrderManager`/`OrderHandler` receive
`OrderStorage` via `OrderStorageFactory.create(environment)`). The four managers stop owning their
containers and read/write through the injected seam.

---

### `itrader/core/enums/portfolio.py` + `execution.py` — relocated enums with `_missing_` (D-04/D-05, M2-07)

**Analog:** `itrader/core/enums/order.py` (the centralized-enum home). **Indentation: TABS** (match `order.py`).

**CRITICAL conversion (RESEARCH Pitfall 2):** every existing enum uses **functional syntax** which
CANNOT host `_missing_`/classmethods:
```python
# Existing functional form (order.py:11, event.py:11-12) — CANNOT host _missing_:
OrderType = Enum("OrderType", "MARKET STOP LIMIT")
FillStatus = Enum("FillStatus", "EXECUTED REFUSED CANCELLED")   # event.py:12
```
Rewrite each RELOCATED enum as a class-based enum to add the parse classmethod (RESEARCH Pattern 4):
```python
from enum import Enum

class FillStatus(Enum):
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown FillStatus: {value!r}")   # real f-string, NOT ('Value %s', x)
```
> **Value-type oracle risk (RESEARCH Assumption A1, Open Question 1):** functional `Enum(...)`
> auto-numbers members `1,2,3…` so `.value` is an **int**; switching to explicit string values
> changes `.value` to **str**. The planner MUST grep `\.value` near `OrderStatus`/`FillStatus`/
> `TransactionState` in Wave 0 BEFORE converting and keep values consistent with any persisted form.
> If nothing compares int `.value`, string values are fine and clearer.

**Enums to relocate to `core/enums` (D-05):** `FillStatus` (from `event.py:12` → `execution.py`),
`CashOperationType` (from `cash_manager.py:22-28`), `PositionEvent` (from `position_manager.py:26-31`),
`MetricsPeriod` (from `metrics_manager.py:19-25`), `TransactionState` (from `transaction_manager.py:26-32`).
**Leave `EventType` inline** in `event.py:11` (M3/#11 reworks it — D-05).

**Register in `core/enums/__init__.py`** following its existing re-export block
(`__init__.py:8-56`): add per-domain `from .X import (...)` group + the `__all__` entry.

**De-map sites** (replace `map.get()` + buggy `ValueError`):
- `event.py:23` `fill_status_map` + its use at `:411` → `FillStatus(value)` (drives `_missing_`).
- `transaction.py:13-16` `transaction_type_map` + the buggy `raise ValueError('Value %s ...', x)`
  at `transaction.py:96-98` → `TransactionType.from_string(...)` / `TransactionType(value)`.
- `event_type_map` at `event.py:14-21` may stay or convert at discretion (EventType stays inline).

---

### `itrader/order_handler/order.py` — timestamp determinism (D-12, M2-09)

**Analog:** SELF (in-place edit, lines 250-452). **Indentation: TABS.** **Mechanism analog:**
`itrader/core/clock.py` (M2a injected `Clock`).

**Sites to change** (RESEARCH-corrected lines):
```python
# add_state_change — replace datetime.now() with the event/transition time arg:
#   order.py:269  timestamp=datetime.now()      → timestamp=<event_time param>
#   order.py:277  self.updated_at = datetime.now()
#   order.py:284  self.filled_at = datetime.now()
#   order.py:286  self.cancelled_at = datetime.now()
#   order.py:288  self.expired_at = datetime.now()
```
```python
# add_fill (order.py:297, 334): route fill_time INTO the recorded transition timestamp
#   — currently fill_time only lands in additional_data["fill_time"] (:334); the actual
#   state-change record uses datetime.now() (:269). Thread fill_time → add_state_change.
```
```python
# modify_order (order.py:436-448): REMOVE the duplicated DIRECT append:
#   :436 self.last_modification_time = datetime.now()
#   :437 self.updated_at = datetime.now()
#   :440-448 builds OrderStateChange(timestamp=datetime.now()) and self.state_changes.append(...)
#   → route through the single validated add_state_change path instead (D-12).
```
**Clock seam** (`core/clock.py:26-29, 44-52`): where a wall-clock fallback is genuinely needed,
use the injected `Clock.now()` — never bare `datetime.now()`. `BacktestClock.now()` raises
`RuntimeError` if not advanced (deterministic; survives `python -O`). Default `add_state_change`'s
time param to the **event time** (D-12: "default to event time, never `datetime.now()`").

**Transaction record timestamps** are already event-derived — `transaction.py:101` passes
`filled_order.time` into `new_transaction` (`:81-109`). Preserve that; ensure no manager re-stamps
with `datetime.now()` when routing through the seam.

---

### `itrader/outils/time_parser.py` — epoch anchor + to_timedelta (D-06/D-07/D-08, M2-10)

**Analog:** SELF (in-place edit, read in full). **Indentation:** mixed tab/space — D-08 says fix
the mix (the module currently mixes; `round_timestamp_to_frequency:152-178` uses spaces, the rest
tabs).

**`check_timeframe` anchor change (D-06)** — current midnight-of-day-UTC anchor at `:124-147`:
```python
# CURRENT (time_parser.py:138-142) — seconds-since-midnight-UTC anchor:
time = time.astimezone(pytz.utc).replace(second=0, microsecond=0)
seconds = (time - time.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
if seconds % timeframe.total_seconds() == 0:
    return True
```
Replace with a SINGLE replaceable seam (D-06) — epoch anchor:
```python
def _aligned(ts: datetime, tf: timedelta) -> bool:
    """Unix-epoch alignment (D-06). DST-immune; coincides with midnight-anchor for daily bars."""
    return int(ts.timestamp()) % int(tf.total_seconds()) == 0
```
> **Oracle risk (RESEARCH Pitfall 3 / A2 / D-18):** for daily bars at 00:00 UTC the epoch and
> midnight anchors AGREE, so `test_oracle_behavioral_identity` MUST stay green. Run it IMMEDIATELY
> after this change — any firing-schedule shift is a STOP/investigate (D-18), never a re-baseline.

**`to_timedelta` (D-08)** — current at `:45-75` already raises-on-unknown (M1-03) but is NOT
case-insensitive, lacks `w`, and has no `M`-specific message:
```python
# CURRENT attributes (time_parser.py:64): {'d':'days','h':'hours','m':'minutes'}
# D-08: make case-insensitive (lowercase the unit), ADD 'w':'weeks', RAISE a clear
#       month-specific error on 'M' (not a fixed timedelta), guard timeframe is None.
```
**Delete dead helpers (D-08):** `format_timeframe` (`:109-122`), `elapsed_time` (`:149-150`),
`round_timestamp_to_frequency` (`:152-178`) — verify zero importers first.

---

### `itrader/config/` — Pydantic v2 collapse (D-01/D-02/D-03, M2-06)

**Analog (stylistic only — NO direct functional analog; NEW Pydantic code):**
`itrader/config/portfolio/config.py` + `defaults.py` for the spaces-indented module style and the
preset-function shape. **Indentation: 4-spaces** (all `config/` is spaces). Pydantic is **NOT yet a
dependency** (RESEARCH drift flag) — `poetry add pydantic@^2.13 pydantic-settings@^2.14` is the FIRST task.

**Preset→factory-classmethod conversion (D-03):** the analog is the preset-FUNCTION form in
`config/portfolio/defaults.py:14-52`:
```python
# CURRENT preset function (defaults.py:19-22) → becomes a Pydantic classmethod:
def get_conservative_portfolio_preset() -> PortfolioConfig:
    return PortfolioConfig(name="Conservative Portfolio", initial_capital=Decimal('50000.0'), ...)
```
Convert to (RESEARCH Pattern 3):
```python
class PortfolioConfig(BaseModel):
    cash: Decimal
    # ... Field(gt=0, le=1) validators + @field_validator at discretion ...

    @classmethod
    def default(cls) -> "PortfolioConfig":
        return cls(cash=Decimal("100000.00"), ...)
```

**`Settings(BaseSettings)` fail-loud secrets (D-02, RESEARCH Pattern 1)** — NEW `config/settings.py`:
```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ITRADER_")
    timezone: str = "Europe/Paris"     # backtest reads — safe default (current Config.TIMEZONE)
    log_level: str = "INFO"
    environment: str = "backtest"
    database_url: SecretStr            # required-no-default → ValidationError if live instantiates
```
> Pydantic v2 idioms (RESEARCH State of the Art): `model_config = SettingsConfigDict(...)` NOT inner
> `class Config:`; `@field_validator` NOT `@validator`; `model_validate`/`model_dump(mode="json")`
> NOT `.dict()`/`.json()`. `BaseSettings`/`SettingsConfigDict` import from `pydantic_settings`, NOT
> `pydantic`. The `model_dump(mode="json")` round-trip (Decimal→str, UUID→str) is the M2-06 JSONB seam.

**Reference-data literals → `core/constants.py` (D-03):** move `FORBIDDEN_SYMBOLS`
(flat `config.py:33-46`), `SUPPORTED_CURRENCIES`/`SUPPORTED_EXCHANGES` (`config.py:30-31, 67-68`).
**Fix the implicit-concat literal bug while moving** — `config.py:41` `'BTG/USDT'` and `:44`
`'BCHABC/USDT' '1INCH/USDT'` are missing commas (Python silently concatenates adjacent string
literals). `core/constants.py` is a plain module — closest analog is the flat `config.py` literal
block; **indentation: 4-spaces** (new `core/` module, match `core/clock.py`).

**Flat-shadow deletion (RESEARCH Pitfall 1 — CRITICAL, not in CONTEXT):** the flat
`itrader/config.py` (the file read above) is the REAL source of `TIMEZONE`/`FORBIDDEN_SYMBOLS`,
loaded via `importlib` in `config/__init__.py:60-76`. The D-01 collapse MUST absorb `TIMEZONE` into
`Settings`/system model + `FORBIDDEN_SYMBOLS` into `core/constants.py`, then DELETE the flat module
AND the `config/__init__.py:60-76` importlib shim. Grep every `config.TIMEZONE` reader:
`time_parser.py:6,9`, `data_provider.py`, `CCXT.py`, `itrader/__init__.py`.

**`config/__init__.py` rewrite (D-01):** delete the getters (`get_config_registry`,
`get_*_config_provider` at `:79-109`) — clean re-export only, analog `core/enums/__init__.py:8-56`
(grouped `from .X import (...)` + `__all__`). Rewire the ~4 consumers to construct models directly:
- `itrader/__init__.py:1,6-7` (`get_config_registry` + `get_system_config_provider`)
- `execution_handler.py:10,63` (`SystemConfig` + `get_system_config_provider().get_config()`)
- `portfolio_handler.py:23-24,56,425` (`get_config_registry`, `get_portfolio_config_provider`,
  `validate_portfolio_config`)
`mypy --strict` (`make typecheck`, live gate) catches any missed site (D-01 / RESEARCH A4).

---

### `tests/` — restructure + pytest conversion (D-13/D-14/D-15, M2-12)

**Analog (harness):** `test/conftest.py` (the M1 skeleton, read in full). **Analog (pytest-native
target style):** `test/test_integration/test_backtest_oracle.py` (already function+fixture form).
**Indentation: 4-spaces** (test files are spaces).

**`DIR_MARKERS` rework (D-13):** current maps **path-segment-DOMAIN** → marker (`conftest.py:25-37`):
```python
# CURRENT (domain-derived — the gap D-13 fixes):
DIR_MARKERS = {
    "test_portfolio_handler": "portfolio", "test_events": "events",
    "test_order_handler": "orders", "test_integration": "integration",
    "test_smoke": "unit", ...   # component dirs get a DOMAIN marker but neither unit nor integration
}
def pytest_collection_modifyitems(config, items):   # :40-54
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        for segment, marker in DIR_MARKERS.items():
            if segment in parts:
                item.add_marker(getattr(pytest.mark, marker))
        if "test_integration" in parts:
            item.add_marker(pytest.mark.slow)
```
Rework to folder-derived **TYPE** markers (`unit`/`integration` from `tests/unit` vs
`tests/integration` path), with layered conftests (root + `unit/` + `integration/`). Move shared
fixtures (`global_queue:64-67`, `golden_*:70-91`, `backtest_engine:94-121`) to the appropriate
layer. **Marker-registration home: pick exactly ONE** — `pyproject.toml markers` list OR
`pytest_configure` in conftest, never both (discretion clause / RESEARCH anti-pattern).

**Conversion mechanics (D-14, RESEARCH Pitfalls 4-6):** 29 `unittest.TestCase` files remain (verified
count). Per file, ONE commit each: `git mv` first (history-preserving), THEN convert
`TestCase`→functions, `setUp`→fixtures (with `yield` teardown to close queues/files — avoids
`ResourceWarning` that `filterwarnings=["error"]` promotes to failure), `self.assertX`→`assert`,
`assertRaises`→`pytest.raises`. Assert `pytest --collect-only -q | wc -l` UNCHANGED each commit.
**Update on move:** `pyproject.toml:41` `testpaths=["test"]`→`["tests"]`, the 8 Makefile `test-*`
targets, `DIR_MARKERS` segments — else `collected 0 items`.

**unit/integration boundary (D-15):** unit = ONE collaborating component (may use a real
`global_queue` + several classes from its own domain); integration = MORE than one collaborating
component (cross-domain, cross-manager, or full cascade). Document in the conftests/README.

---

### `tests/integration/test_backtest_oracle.py` — oracle re-freeze (D-16/D-17/D-18, M2-13) — LAST

**Analog:** SELF (read in full). **Indentation: 4-spaces.**

**D-16 — remove the xfail + tolerance:** delete `@pytest.mark.xfail(...)` on
`test_oracle_numeric_values` (`:183`), delete `_D15_RTOL`/`_D15_ATOL` (`:74-75`) and the
`_DEF_02_08_A_XFAIL_REASON` (`:64-68`); flip the numeric asserts (`:201-228`) to `check_exact=True`
(drop `rtol`/`atol`). Numeric cols: `final_cash`/`final_equity`/`total_realised_pnl`/`final_equity`.

**D-18 — `test_oracle_behavioral_identity` (`:138-180`) stays byte-exact + active UNCHANGED** at
every commit: trades `(entry_date, exit_date, side, pair)` `check_exact=True` (`:156-161`), equity
timestamp grid (`:168-173`), `trade_count` (`:176-180`). This is the law throughout the phase.

**D-17 — inertness gate:** capture the M2a-end `output/{trades,equity}.csv`+`summary.json` (from
`scripts/run_backtest.py::main`, invoked in-process at `:78-94, 113`) as a reference at phase START;
the phase-END run must equal it byte-exact (behavioral AND numeric) BEFORE re-freezing. Any non-zero
diff BLOCKS the re-freeze, logged as a COVERAGE-INDEX §E delta. Re-freeze regenerates `test/golden/*`
from `main()` as the strictly-LAST task.

---

## Shared Patterns

### Pluggable storage (ABC + in-memory + factory)
**Source:** `itrader/order_handler/base.py:25-325` (ABC) + `storage/in_memory_storage.py` (backend) +
`storage/storage_factory.py:6-51` (factory) + `storage/__init__.py:9-20` (re-export).
**Apply to:** the entire new `portfolio_handler/storage/` package (D-09). 4-spaces. Factory `create`
switches `backtest`/`test`→in-memory, `live`→raise/defer (D-sql).

### Centralized enum with parse-on-the-type
**Source:** `itrader/core/enums/order.py` (home + tabs) + RESEARCH Pattern 4 (`_missing_`).
**Apply to:** all relocated enums (`FillStatus`, `CashOperationType`, `PositionEvent`,
`MetricsPeriod`, `TransactionState`). Convert functional→class syntax FIRST (Pitfall 2). Register in
`core/enums/__init__.py:8-56`. Replace every string→enum map `.get()` + buggy `ValueError`.

### Injected deterministic clock
**Source:** `itrader/core/clock.py:26-59` (`Clock` Protocol + `BacktestClock`/`WallClock`).
**Apply to:** every `datetime.now()` in `order.py` (`:269,277,284,286,288,436,437,443`) — default to
event time; clock only where a fallback is genuinely needed. Never bare `datetime.now()` on the
domain path.

### Money + ID domain conventions (preserve while moving)
**Source:** `transaction.py:38-47` (`__post_init__` → `to_money`), `position.py:46` (`PositionId`),
`transaction.py:108` (`idgen.generate_transaction_id`). **Apply to:** durable record shapes for the
storage seam (D-12: Decimal money via `to_money`, native UUID ids, event-derived time). No DB code.

### Strict-suite hygiene
**Source:** `pyproject.toml` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) +
`make typecheck` (`mypy --strict`). **Apply to:** every commit — config collapse must be
strict-clean; pytest conversion must not surface a promoted `ResourceWarning`; every marker declared
in exactly one home.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `itrader/config/settings.py` | config model | transform | No Pydantic `BaseSettings` exists in-tree (Pydantic not yet a dep). Use RESEARCH Pattern 1 + spaces style of `config/portfolio/config.py`. |
| `itrader/config/portfolio.py` (Pydantic) | config model | transform | The existing `config/portfolio/config.py` is a hand-rolled dataclass-style config being DELETED — use its field names/style as a stylistic reference only; structure follows Pydantic v2 (RESEARCH Patterns 2-3). |
| `itrader/config/{trading,data,system,exchange}.py` (Pydantic) | config model | transform | Same — new Pydantic models; the deleted domain dirs supply field intent, not structure. |

> For these three, follow RESEARCH §"Standard Stack" + Patterns 1-3 (verified Pydantic v2 idioms)
> and the 4-space `config/` convention. The closest STYLISTIC analog is `config/portfolio/defaults.py`
> (preset functions → factory classmethods) and `core/clock.py` (clean spaces-indented `core` module).

---

## Metadata

**Analog search scope:** `itrader/order_handler/{base.py,storage/}`, `itrader/core/{enums,clock.py,
constants}`, `itrader/portfolio_handler/{position,transaction,cash,metrics}*.py`,
`itrader/config/{__init__.py,portfolio/}` + flat `itrader/config.py`, `itrader/outils/time_parser.py`,
`itrader/order_handler/order.py`, `itrader/events_handler/event.py`, `test/{conftest.py,
test_integration/test_backtest_oracle.py}`.
**Files scanned:** 17 read in full/part + 5 grep verifications.
**Pattern extraction date:** 2026-06-05
**Drift corrections applied:** OrderStorage ABC home (`order_handler/base.py` not `storage/base.py`);
`event.py` enum lines (:11-12, :23, :411); `order.py` `datetime.now()` lines (:269,277,284,286,288,
436,437,443); flat-config shadow + importlib shim (Pitfall 1); functional→class enum conversion
(Pitfall 2); `screener_event_handler.py` actual path (`events_handler/`, not `screeners_handler/`);
29 unittest files (not "~32").
