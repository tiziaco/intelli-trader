# Phase 04: Type Modeling - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 14 modified + 1 relocation target (`config/strategy.py`)
**Analogs found:** 14 / 14 (all in-repo; this is a self-templating refactor)

> This is a **behavior-preserving type-modeling refactor**. There are almost no
> "new files" — every change modifies an existing site to match a template that
> ALREADY EXISTS elsewhere in the same repo. The analogs below are not loose
> inspiration; they are the **exact house pattern** the executor copies, often
> in the same package. Oracle byte-exact (134 trades / `final_equity
> 46189.87730727451`), `mypy --strict` clean, 58/58 e2e green.

> **INDENTATION HOUSE (read before every edit — D-15) — VERIFY PER FILE:**
> `core/enums/` is **NOT uniformly 4-space** — it is a per-file hazard. Always
> `grep -qP '^\t' <file>` before editing.
> - **4-space:** `core/` (most), `config/` (incl. new `config/strategy.py`),
>   `events_handler/events/`, `price_handler/feed/`, and within `core/enums/`:
>   `core/enums/execution.py` and `core/enums/__init__.py` (verified 4-space).
> - **TAB:** `order_handler/`, `execution_handler/`, `portfolio_handler/`,
>   `strategy_handler/` (incl. `strategies/SMA_MACD_strategy.py` /
>   `empty_strategy.py`), AND **`core/enums/order.py`** — verified TAB-indented
>   despite living under `core/`. Every D-01/D-04/D-06 edit to `order.py`
>   (OrderStatus/OrderCommand/OrderOperationType/OrderTriggerSource/MarketExecution)
>   MUST use TABS. The 04-04 / 04-05 plans already say "match TAB" — they are
>   correct; this is the canonical home of that fact.
> - **NEW `core/enums/` files:** `core/enums/severity.py` (D-05 ErrorSeverity)
>   mirrors `core/enums/execution.py::FillStatus`, so it is **4-space** (matches
>   its template file; 04-02 already specifies "4-SPACE house, like
>   core/enums/execution.py"). Any other new `core/enums/` file should match the
>   indentation of the in-file template it copies — verify that template's
>   indentation first.
> - **Acute case (D-15):** moving a 4-space pydantic config class into the
>   TAB-indented strategy files REQUIRES re-indenting the moved class to tabs.

---

## File Classification

| Modified File | Indent | Role | Decision | Closest Analog | Match |
|---------------|--------|------|----------|----------------|-------|
| `core/enums/order.py` (OrderStatus/OrderCommand) | TAB | enum/model | D-01 | `core/enums/order.py::OrderType` (same file, lines 11-31) | exact (in-file) |
| `core/enums/order.py` (OrderOperationType — NEW) | TAB | enum/model | D-04 | `core/enums/order.py::OrderType` | exact |
| `core/enums/order.py` (OrderTriggerSource — NEW) | TAB | enum/model | D-04 | `core/enums/order.py::OrderType` | exact |
| `core/enums/severity.py` (ErrorSeverity — NEW) | 4-space | enum/model | D-05 | `core/enums/execution.py::FillStatus` (4-space) | exact |
| `core/enums/order.py` (MarketExecution — NEW) | TAB | enum/model | D-06 | `core/enums/order.py::OrderType` | exact |
| `execution_handler/matching_engine.py` (FillDecision/CancelDecision) | 4-space* | value-object | D-07 | `events_handler/events/error.py::ErrorEvent` (frozen/slots/kw_only) | exact |
| `order_handler/operation_result.py` (OperationResult/SignalProcessingResult) | TAB | value-object | D-07 | `events_handler/events/error.py` + `_PendingBracket` | exact |
| `order_handler/order_manager.py::_PendingBracket` | TAB | value-object | D-07 | already `frozen=True` here (lines 34-51) — add slots/kw_only | exact (in-file) |
| `execution_handler/exchanges/simulated.py` (fee/slippage dispatch) | TAB | service | D-08 | `order_handler/sizing_resolver.py` (match + `assert_never`, lines 105-126) | exact |
| `config/portfolio.py::rebalance_frequency` | 4-space | config | D-09 | `strategy_handler/config.py::_short_lt_long` (pydantic v2 validator) | role-match |
| `config/portfolio.py::portfolio_id` | 4-space | config | D-10 | (deletion — no analog needed) | n/a |
| `order_handler/order_manager.py` + `order_handler.py` (id params) | TAB | facade/service | D-12 | `core/ids.py` NewType aliases (annotation reuse) | exact |
| `order_handler/order.py` (factory id params + triggered_by) | TAB | model | D-12, D-04 | `core/ids.py` + new enums | exact |
| `events_handler/events/error.py::portfolio_id` | 4-space | event | D-12 | `core/ids.py::PortfolioId` (already imports `CorrelationId`) | exact (in-file) |
| `portfolio_handler/portfolio_handler.py` + `validators.py` (id params) | TAB | facade | D-12 | `core/ids.py` NewTypes | exact |
| `strategy_handler/config.py` → `config/strategy.py` (relocation) | 4-space | config | D-14 | `config/__init__.py` re-export block | exact |
| `strategies/SMA_MACD_strategy.py` / `empty_strategy.py` (concrete config in-file) | TAB | config-in-strategy | D-14/D-15 | `strategy_handler/config.py::SMA_MACDConfig` (RE-INDENT to TAB) | exact + hazard |

\* `matching_engine.py` is `4-space` (it is a pure engine module under
`execution_handler/` but uses 4-space — VERIFY the file before editing; the
existing `@dataclass`-decorated `FillDecision` at line 60 is 4-space indented).

> **⚠ core/enums per-file indentation (verified):** `core/enums/order.py` is
> **TAB**; `core/enums/execution.py` and `core/enums/__init__.py` are **4-space**.
> Do NOT assume the package is uniform. The new `severity.py` follows its
> 4-space `execution.py` template; the new enums added INSIDE `order.py`
> (OrderOperationType/OrderTriggerSource/MarketExecution) follow `order.py`'s TAB.

---

## Pattern Assignments

### 1. The enum house pattern — D-01, D-04, D-05, D-06

**Template (THE canonical form):** `itrader/core/enums/order.py::OrderType` (lines 11-31)
and `core/enums/execution.py::FillStatus` (lines 59-89).

```python
class OrderType(Enum):
    """Order type at the event/entity boundary.

    Class-based with explicit string values and a case-insensitive
    ``_missing_`` (FillStatus house pattern) ...
    """
    MARKET = "MARKET"
    STOP = "STOP"
    LIMIT = "LIMIT"

    @classmethod
    def _missing_(cls, value: object) -> "OrderType":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown OrderType: {value!r}")
```

> **NOTE — `order.py` is TAB-indented:** the snippet above is shown 4-space for
> readability, but the LIVE `core/enums/order.py` uses TABS. Match the file
> (D-01/D-04/D-06 edits to `order.py` are all TAB).

**Accompanying `<domain>_<type>_map`** (lines 36-40):

```python
order_type_map = {
    "MARKET": OrderType.MARKET,
    "STOP": OrderType.STOP,
    "LIMIT": OrderType.LIMIT
}
```

**D-01 — `OrderStatus` / `OrderCommand` (BEHAVIOR-SENSITIVE, ⚠ but byte-inert):**
Replace the functional form at `order.py:33` / `:64`:

```python
# CURRENT (functional, auto-int .value):
OrderStatus = Enum("OrderStatus", "PENDING PARTIALLY_FILLED FILLED CANCELLED REJECTED EXPIRED")
OrderCommand = Enum("OrderCommand", "NEW CANCEL MODIFY")
```

with the class-based form, **member values = member name** (`PENDING = "PENDING"`,
`NEW = "NEW"`, ...), a case-insensitive `_missing_`, and **keep**
`order_status_map`/`order_command_map` (lines 43-50, 67-71) and
`VALID_ORDER_TRANSITIONS` (lines 52-61) UNCHANGED — member identity is
unaffected; only `.value` flips int→string.

> **D-02 load-bearing audit (the real deliverable):** the int→string `.value`
> change is byte-inert because status serializes via `.name`, never `.value`:
> - `reporting/orders.py:91` → `"status": o.status.name`
> - `order_handler/order.py:133` → `f"{self.status.name}"`
> `.name` is `"PENDING"` whether `.value` is `1` or `"PENDING"`. Do NOT switch
> any serializer to `.value`. No `status.value == <int>` assertion exists in the
> suite (grep-confirmed).

**D-04 — `OrderOperationType` (10-value) / `OrderTriggerSource` (value-equal):**
NEW enums in `core/enums/order.py` (TAB). **Hard constraint:** each member's
`.value` MUST equal the **exact current string literal** (value-equal swap, e.g.
`"create_primary_order"`). Then convert all call-sites in `order_manager.py`
(20+ `operation_type=`, 8+ `triggered_by=`) and `order.py` (the
`OrderStateChange.triggered_by` field at line 27, default `"system"`) and the
factory methods. **Also retype `OperationResult.operation_type`** (field +
`success_result`/`failure_result` params) from `str` to `OrderOperationType` so
the enum-member carrier type-checks under `mypy --strict` (Plan 04-04 owns this,
co-located with the enum definition). Pure annotation + value-equal literal swap
— reconciliation / reservation-release LOGIC is FROZEN.

**D-05 — `ErrorSeverity`:** NEW enum in `core/enums/severity.py` (**4-space**,
mirrors `execution.py::FillStatus`). Replaces the comment-as-enum at
`events/error.py:53` (`severity: str = "ERROR"  # ERROR, CRITICAL, WARNING`).
Member values are the exact strings `"ERROR"`/`"CRITICAL"`/`"WARNING"`. Update
the consumer compare at `full_event_handler.py:157`
(`}.get(event.severity, self.logger.error)`) — the dict key set must match enum
members (or use member identity). Follow `FillStatus`.

**D-06 — `MarketExecution`:** NEW enum for `"immediate"`/`"next_bar"`
(value-equal), added INSIDE `core/enums/order.py` (**TAB**). Coerce at the
`OrderManager.__init__` boundary (`order_manager.py:70`, param
`market_execution: str = "immediate"` → enum-typed/coerced). Per SYN-05 the
ENUM alone lands; NO `OrderConfig` model (deferred 999.5-(b)).

---

### 2. The frozen-fact dataclass pattern — D-07

**Template:** `events_handler/events/error.py::ErrorEvent` (lines 21-22) and the
existing `_PendingBracket` (`order_manager.py:34`, already `frozen=True`).

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorEvent(Event):
    ...
    type: EventType = field(default=EventType.ERROR, init=False)
    source: str
    error_type: str
```

**`_PendingBracket`** is the same-package precedent — it is ALREADY
`@dataclass(frozen=True)` (line 34); D-07 only adds `slots=True, kw_only=True`:

```python
@dataclass(frozen=True)   # → @dataclass(frozen=True, slots=True, kw_only=True)
class _PendingBracket:
    policy: PercentFromFill
    ticker: str
    action: str
    quantity: Decimal
    exchange: str
    strategy_id: StrategyId
    portfolio_id: "PortfolioId | int"
```

**`FillDecision` / `CancelDecision`** (`matching_engine.py:60,75`) are plain
`@dataclass` today — add `frozen=True, slots=True, kw_only=True`. They are
constructed positionally elsewhere in `matching_engine.py`; freezing + `kw_only`
surfaces positional construction as errors → migrate call-sites to keyword args,
do NOT unfreeze.

**`OperationResult` / `SignalProcessingResult`** (`operation_result.py:13,56`)
are plain `@dataclass` with **mutable `List` fields + classmethod factories**:

```python
@dataclass            # → @dataclass(frozen=True, slots=True, kw_only=True)
class OperationResult:
    success: bool
    message: str
    order_events: List[OrderEvent] = field(default_factory=list)   # → tuple[OrderEvent, ...] = ()
    ...
    @classmethod
    def success_result(cls, message: str, order_events=None, ...): ...
```

**W2-04:** prefer `tuple[OrderEvent, ...]` over the mutable `List` field. Audit:
- `success_result`/`failure_result`/`from_operations` classmethods build via
  KEYWORD args already (lines 32-49, 86-90) — `kw_only` is satisfied.
- `all_order_events` (lines 69-74) does `events.extend(result.order_events)` into
  a LOCAL list — that is fine; the FROZEN field just becomes a `tuple`.
- Any in-place mutation of `order_events`/`affected_order_ids`/`operation_results`
  on a constructed instance becomes a `FrozenInstanceError` — migrate to building
  the tuple at construction. Pick the byte-exact-safe form (tuple).

> **`operation_type` field type (D-04, Plan 04-04):** once `OrderOperationType`
> exists, `OperationResult.operation_type` (field + factory params) is retyped
> `str` → `OrderOperationType` so the enum-member call-sites type-check under
> `mypy --strict`. Plan 04-01 only freezes the DTO shape + tuple fields; the
> `operation_type` annotation flip is co-located in 04-04 with the enum it needs.

---

### 3. NewType id aliases — D-12 (annotation-only, mypy-gated)

**Template:** `itrader/core/ids.py:17-26` — ten existing `NewType` aliases. NO
new types minted; pure annotation reuse, runtime-identical (values are already
UUIDs).

```python
OrderId = NewType("OrderId", uuid.UUID)
PortfolioId = NewType("PortfolioId", uuid.UUID)
TransactionId = NewType("TransactionId", uuid.UUID)
StrategyId = NewType("StrategyId", uuid.UUID)
```

**Retype these exact sites (`int`/`Optional[int]`/`Any` → NewType):**

| Site | Current | → |
|------|---------|---|
| `order_manager.py:1089` `modify_order` | `order_id: int`, `portfolio_id: Optional[int]` | `OrderId`, `Optional[PortfolioId]` |
| `order_manager.py:1177` `cancel_order` | `order_id: int`, `portfolio_id: Optional[int]` | `OrderId`, `Optional[PortfolioId]` |
| `order_manager.py:1255` `get_order_by_id` | `order_id: int`, `portfolio_id: Optional[Any]` | `OrderId`, `Optional[PortfolioId]` |
| `order_manager.py:1259` `get_orders_by_status` | `portfolio_id: Optional[Any]` | `Optional[PortfolioId]` |
| `order_manager.py:1263` `get_active_orders` | `portfolio_id: Optional[Any]` | `Optional[PortfolioId]` |
| `order_manager.py:1267` `get_order_history` | `order_id: int` | `OrderId` |
| `order_manager.py` `get_order_history`/`get_orders_by_ticker`/`search_orders`/`get_orders_summary` | `int`/`Any` | matching NewType |
| `order_handler.py:40,121,158,222,274` + `get_orders_*` block | `int`/`Any` | matching NewType |
| `order.py:199,232` `new_stop_order`/`new_limit_order` factories | `strategy_id: Any`, `portfolio_id: Any` | `StrategyId`, `PortfolioId` |
| `portfolio_handler.py:167,173,495,507` | `portfolio_id: Any` | `PortfolioId` |
| `events/error.py:78` `PortfolioErrorEvent.portfolio_id` | `Any \| None` | `PortfolioId \| None` |
| `portfolio_handler/validators.py:83` | `transaction_id: Optional[int]` | `Optional[TransactionId]` |

**D-13 carve-outs — DO NOT retype:** `user_id: int` (`portfolio.py:46`,
`portfolio_handler.py:123`, `validators.py:56`) stays `int` (no `UserId` exists;
inventing one = forbidden new id scheme). Off-path deferred subsystems
(`trading_interface.py`, `screeners/base.py`) untouched.

> `events/error.py` ALREADY imports a NewType (`from itrader.core.ids import
> CorrelationId`, line 16) — `PortfolioId` import follows the identical idiom.

---

### 4. `assert_never` exhaustive dispatch — D-08

**Template:** `order_handler/sizing_resolver.py:105-126` — `match` on enum/type
members closing with `assert_never`:

```python
from typing import assert_never   # already imported there (line 33)

match policy:
    case FractionOfCash():
        ...
    case FixedQuantity():
        qty = policy.qty
    case RiskPercent():
        ...
    case _:
        assert_never(policy)   # mypy --strict fails on an unhandled kind
```

(Also present at `order_manager.py:636` and `core/sizing.py:153`.)

**D-08 target — `simulated.py::_init_fee_model` / `_init_slippage_model`
(lines 492-541):** CURRENTLY dispatches on `config.model_type.value` STRINGS in
an `if/elif` chain:

```python
if config.model_type.value in ['no_fee', 'zero']:
    return ZeroFeeModel()
elif config.model_type.value == 'percent':
    ...
else:
    self.logger.warning('Unknown fee model %s ...', config.model_type.value)
    return ZeroFeeModel()
```

Convert to compare **enum MEMBERS** (`config.model_type is FeeModelType.ZERO`,
`is SlippageModelType.LINEAR`, ...) — `FeeModelType`/`SlippageModelType` are
already imported via `config/` (re-exported in `config/__init__.py:89-90`). Use a
`match`/`if-elif` whose exhaustive final branch is `assert_never(config.model_type)`
so mypy proves completeness. The `else: logger.warning` fallthrough is replaced by
`assert_never` (no runtime warning path — mypy is the gate). **Oracle-safe:** the
oracle runs Zero* models and never reaches percent/maker_taker/linear/fixed.

> NOTE: preserve the `is not None` Decimal-default handling inside each branch
> (T-07-06 comments, lines 485-491) verbatim — that is money-policy load-bearing,
> NOT part of the enum-dispatch change.

---

### 5. Pydantic v2 boundary validation — D-09

**Template:** `strategy_handler/config.py::SMA_MACDConfig._short_lt_long`
(lines 72-77) — the ONLY existing pydantic-v2 validator pattern in the config
surface (there is NO existing `field_validator` in `config/`; this is the nearest
analog, and it is a `model_validator`):

```python
from pydantic import model_validator   # v2 ONLY — never v1 @validator

@model_validator(mode="after")
def _short_lt_long(self) -> "SMA_MACDConfig":
    """HARD-02 cross-field rule ..."""
    if self.short_window >= self.long_window:
        raise ValueError("short_window must be < long_window")
    return self
```

**D-09 target — `config/portfolio.py:124` `rebalance_frequency: str = "monthly"`:**
add closed-vocabulary validation at the Pydantic boundary. Either a
`@field_validator("rebalance_frequency")` (Pydantic v2) checking membership in the
closed set, or a `Literal[...]` type / `model_validator(mode="after")` mirroring
`_short_lt_long`. **Pydantic v2 decorators ONLY** — `filterwarnings=["error"]`
fails on v1 `@validator` deprecation. Field is oracle-dark
(`auto_rebalance=False` on backtest path) — this hardens the boundary without
changing run behavior.

**D-10 (same file, line 108):** DELETE `portfolio_id: Optional[int] = None`
entirely — false affordance + stray int id (never read; entity mints fresh
UUIDv7). No construction site passes `portfolio_id=` (grep-confirmed); executor
double-checks `tests/unit/portfolio/test_portfolio_handler.py:107`.

---

### 6. Config re-export + relocation — D-14, D-15, D-16

**Template:** `config/__init__.py:24-55, 63-98` — the grouped domain re-export
block (`ExchangeConfig`/`PortfolioConfig`/`SystemConfig`):

```python
from .portfolio import (PortfolioConfig, ...)
from .system import (SystemConfig, ...)
from .exchange import (ExchangeConfig, ...)

__all__ = [
    ...
    "PortfolioConfig",
    "SystemConfig",
    "ExchangeConfig",
    ...
]
```

**D-14 plan:**
- Move `BaseStrategyConfig` (`strategy_handler/config.py:38-55`) → NEW
  `itrader/config/strategy.py` (4-space module — matches `config/` house).
  Add `from .strategy import BaseStrategyConfig` + `"BaseStrategyConfig"` to
  `config/__init__.py` following the block above.
- Move `SMA_MACDConfig` (`config.py:58-77`) → `strategies/SMA_MACD_strategy.py`.
- Move `EmptyStrategyConfig` (`config.py:80-82`) → `strategies/empty_strategy.py`.
- Each concrete config subclasses `BaseStrategyConfig` imported from `config/`.
- Empty/remove `strategy_handler/config.py`.
- The `core.sizing`/`core.enums` imports (`config.py:34-35`) carry over unchanged
  (`config/` already legally imports `core/`).

> **D-15 INDENTATION HAZARD (acute):** `config.py` is **4-space**;
> `strategies/SMA_MACD_strategy.py` and `empty_strategy.py` are **TAB**. The moved
> `SMA_MACDConfig`/`EmptyStrategyConfig` classes (incl. the `_short_lt_long`
> validator body) MUST be **RE-INDENTED to tabs** to match their destination
> file. `config/strategy.py` (the base) STAYS 4-space. A mixed-indentation diff
> breaks a tab file.

**D-16 import-churn list (update these importers of old `strategy_handler.config`):**
- `strategy_handler/base.py:12`, `strategy_handler/signal_record.py:35`
- the two strategy files (now hold the concrete configs)
- `tests/unit/strategy/test_strategy_config.py`, `test_strategy.py`,
  `test_signal_store.py`
- `tests/integration/test_universe_spans.py`, `test_backtest_oracle.py:255`,
  `test_backtest_smoke.py`, `test_reservation_inertness.py`
- `tests/e2e/strategies/single_market_buy.py`, `scripted_emitter.py`
- `scripts/run_backtest.py:48`
- Base resolves to `itrader.config.strategy` (or `itrader.config`); concrete
  configs resolve to the strategy modules now holding them.

---

## Shared Patterns

### Enum house form (case-insensitive `_missing_` + f-string ValueError)
**Source:** `core/enums/order.py:11-31` (`OrderType`, TAB), `core/enums/execution.py:59-89`
(`FillStatus`, 4-space).
**Apply to:** D-01 (`OrderStatus`/`OrderCommand`), D-04 (`OrderOperationType`/
`OrderTriggerSource`), D-05 (`ErrorSeverity`), D-06 (`MarketExecution`).
**Invariant:** member name = `.value` (UPPERCASE for status/command; EXACT current
string for value-equal enums D-04/D-06).
**Indentation:** enums added INSIDE `order.py` are TAB; `severity.py` is 4-space.

### D-03 enum unit-test home
**Source:** `tests/unit/core/test_enums.py` (already exists; pins `FillStatus`
case-insensitive parse + clear-error f-string; 4-space). EXTEND this single file for
every phase-04 `core/enums` enum: `.value` strings, `_missing_` parse,
`*_map` round-trip (where a map exists), and the `.name`-serialization invariant
(OrderStatus). Folder-derived `unit` marker via `tests/conftest.py` — do NOT add an
explicit marker (only `unit`/`integration`/`slow`/`e2e` declared;
`filterwarnings=["error"]` in force). Coverage split: ErrorSeverity → Plan 04-02;
OrderStatus/OrderCommand/OrderOperationType/OrderTriggerSource → Plan 04-04;
MarketExecution → Plan 04-05.

### Frozen-fact dataclass
**Source:** `events_handler/events/error.py:21` + `order_manager.py:34`.
**Apply to:** all D-07 DTOs. `@dataclass(frozen=True, slots=True, kw_only=True)`;
migrate positional construction to keyword; replace mutable `List` fields with
`tuple[...]`.

### `.name` serialization (DO NOT regress)
**Source:** `reporting/orders.py:91`, `order_handler/order.py:133`.
**Apply to:** D-01/D-02 — never switch a serializer to `.value`; this is what
makes the int→string flip byte-inert.

### NewType id annotations
**Source:** `core/ids.py:17-26`.
**Apply to:** every D-12 site. Annotation-only; mypy `--strict` is the sole gate
(no runtime change). Carve out `user_id` and deferred subsystems (D-13).

### `assert_never` exhaustive dispatch
**Source:** `order_handler/sizing_resolver.py:105-126`.
**Apply to:** D-08 fee/slippage dispatch — compare members, close with
`assert_never`.

### Pydantic v2 validator (NEVER v1)
**Source:** `strategy_handler/config.py:72-77`.
**Apply to:** D-09 `rebalance_frequency`. `@model_validator(mode="after")` or
`@field_validator(...)`; v1 `@validator` fails under `filterwarnings=["error"]`.

### Money-policy guard (preserve, do not touch)
**Source:** `simulated.py:485-491` (`is not None` Decimal-default comments).
**Apply to:** D-08 — keep the per-branch `is not None` Decimal handling verbatim
when restructuring the dispatch.

---

## No Analog Found

None. Every modified site has an exact in-repo template (most in the same package).
This phase is self-templating by design — `OrderType`/`FillStatus`/`ErrorEvent`/
`_PendingBracket`/`core/ids.py`/`sizing_resolver.py`/`SMA_MACDConfig` are the
authoritative house patterns the executor copies.

---

## Metadata

**Analog search scope:** `itrader/core/enums/`, `itrader/core/ids.py`,
`itrader/order_handler/`, `itrader/execution_handler/`,
`itrader/events_handler/events/`, `itrader/config/`, `itrader/strategy_handler/`.
**Files scanned:** ~12 source files (targeted reads, no full-file re-reads).
**Pattern extraction date:** 2026-06-11
**Indentation re-verification:** 2026-06-11 (`core/enums/order.py` = TAB;
`core/enums/execution.py` / `__init__.py` = 4-space — per-file `grep -qP '^\t'`).
