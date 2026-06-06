# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 24 new/modified files (+ 4 pure relocations, 3 deletions)
**Analogs found:** 23 / 24 (only `ingestion.py` stub has a partial analog)

All paths relative to repo root. Line numbers verified this session against the working tree
(branch `implement-phase-6`, clean).

## File Classification

### New files

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `itrader/core/bar.py` | model (value object) | transform (float64 → Decimal) | `itrader/events_handler/events/base.py` + `itrader/core/money.py` | exact |
| `itrader/price_handler/store/base.py` | abstract seam (ABC/Protocol) | file I/O contract | `itrader/portfolio_handler/base.py:93-167` (`PortfolioStateStorage`) | exact (CONTEXT.md names it the model) |
| `itrader/price_handler/store/csv_store.py` | store (concrete) | file I/O (read path) | `itrader/price_handler/data_provider.py:131-182` (`_load_csv_data`) | exact (logic inherited verbatim) |
| `itrader/price_handler/feed/base.py` | abstract seam | request-response (query) | `itrader/portfolio_handler/base.py:93+` | exact |
| `itrader/price_handler/feed/bar_feed.py` | read-model / service | request-response (per-tick query) | `itrader/price_handler/data_provider.py:277-346` (`get_bars`/`get_resampled_bars` — logic source, bugs fixed) + `itrader/portfolio_handler/storage/in_memory_storage.py` (dict-backed shape) | role-match |
| `itrader/price_handler/providers/base.py` | abstract seam | event-driven (offline fetch) | `itrader/portfolio_handler/base.py:93+` | role-match |
| `itrader/price_handler/ingestion.py` | utility (stub entry point) | batch | `itrader/price_handler/data_provider.py:96-129` (`load_data` non-csv branch — the provider→store loop being formalized) | partial |
| `tests/unit/core/test_bar.py` | test | — | `tests/unit/core/test_money.py` | exact |
| `tests/unit/price/test_csv_store.py` | test | — | `tests/unit/core/test_money.py` (style) + golden CSV fixture | role-match |
| `tests/unit/price/test_bar_feed.py` | test | — | `tests/unit/execution/test_matching_engine.py` (helper-fn fixtures) | role-match |
| `tests/unit/execution/test_fee_models.py`, `test_slippage_models.py` | test | — | `tests/unit/core/test_money.py` | role-match |
| `tests/conftest.py` shared `make_bar`/`make_bar_event` | test fixture | — | `tests/unit/execution/test_matching_engine.py:12-28` (`make_order_event`/`make_bar`) | exact |

### Modified files

| Modified File | Role | Data Flow | Pattern Source for the Edit | Match Quality |
|---------------|------|-----------|-----------------------------|---------------|
| `itrader/events_handler/events/market.py` (BarEvent redesign) | event dataclass | event-driven | sibling events in the SAME file (`TimeEvent`/`ScreenerEvent` — frozen, minimal, no accessor methods) | exact |
| `itrader/execution_handler/matching_engine.py` | service (pure engine) | event-driven matching | self (D-13 MARKET branch already exists at `:123-125`); Decimal pattern from `core/money.py` | exact |
| `itrader/execution_handler/exchanges/simulated.py` (`_emit_fill`, on_order routing, sleep, factories) | adapter/exchange | event-driven | self + `maker_taker_fee_model.py` `is_maker` kwarg | exact |
| `itrader/execution_handler/fee_model/base.py` + `slippage_model/base.py` (ABC unification) | abstract seam | request-response | fee `base.py` raise-contract is the SURVIVOR pattern; slippage bool-contract dies | exact |
| `itrader/order_handler/order_manager.py:129-148` (partial-fill clamp deletion) | manager | event-driven reconciliation | deletion per D-06 — no analog needed | n/a |
| `itrader/strategy_handler/strategies_handler.py:33-53` | handler | request-response (push) | self — same loop shape, `price_handler` → `feed` repoint | exact |
| `itrader/universe/dynamic.py:58-84` | service | event-driven (BarEvent construction) | self — `get_bar` Series → `feed.current_bars(T)` dict[str, Bar] | exact |
| `itrader/trading_system/backtest_trading_system.py` | composition root | wiring | self — Store/Feed constructed where `PriceHandler` is today (`:61`, `:122-126`) | exact |
| `itrader/trading_system/live_trading_system.py` | composition root | wiring | mirror the backtest wiring (minimal conformance, Pitfall 8) | role-match |
| `itrader/reporting/statistics.py` | reporting | request-response | takes the Store instead of PriceHandler (Pitfall 8); dormant, minimal edit | role-match |
| `pyproject.toml` (mypy override paths) | config | — | existing `[[tool.mypy.overrides]]` entries — update module paths in the same commit as each `git mv` | exact |

### Relocations (pure `git mv`, untouched — D-16/D-21)

| From | To |
|------|----|
| `itrader/price_handler/exchange/CCXT.py` | `itrader/price_handler/providers/ccxt_provider.py` |
| `itrader/price_handler/exchange/OANDA.py` | `itrader/price_handler/providers/oanda_provider.py` |
| `itrader/price_handler/live_streaming/BINANCE_Live.py` | `itrader/price_handler/providers/binance_stream.py` |
| `itrader/price_handler/sql_handler.py` | `itrader/price_handler/store/sql_store.py` |

### Deletions

`itrader/price_handler/data_provider.py`, `itrader/price_handler/base.py` (D-18),
`itrader/execution_handler/fee_model/tiered_fee_model.py` (D-10).

---

## Pattern Assignments

### `itrader/core/bar.py` (model, transform) — NEW

**Analogs:** `itrader/events_handler/events/base.py` (frozen dataclass shape) +
`itrader/core/money.py` (string-path Decimal entry). Spaces indentation (new core module).

**Frozen-dataclass pattern** (`events/base.py:10-47` — copy the decorator stack, docstring
style, and the `object.__setattr__` post-init idiom if Bar needs one):

```python
import uuid
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Immutable event fact. All concrete events subclass this. ..."""
    type: EventType = field(init=False)
    time: datetime
    ...
    def __post_init__(self) -> None:
        if self.created_at is None:
            # stdlib-documented idiom for frozen dataclass __post_init__;
            # works with slots=True (verified on Python 3.13.1).
            object.__setattr__(self, "created_at", self.time)
```

Note: `Bar` is a value object, NOT an Event subclass — copy the decorator
`@dataclass(frozen=True, slots=True, kw_only=True)` and module-docstring style, not the
`type`/`event_id` fields. Fields per RESEARCH Pattern 3: `time: datetime` (open-time stamp),
`open/high/low/close/volume: Decimal`.

**Decimal entry pattern** (`core/money.py:42-49` — the construction path for `from_row`):

```python
def to_money(x: float | int | str | Decimal) -> Decimal:
    """Enter the Decimal domain via the string path (D-04).

    ``Decimal(str(x))`` avoids the binary float-repr artifact that
    ``Decimal(x)`` would introduce for a ``float`` ``x``. NEVER call
    ``Decimal(float)`` directly.
    """
    return Decimal(str(x))
```

Use `Decimal(str(x))` (or `to_money`) once per field at Bar construction — this is the
inertness argument (RESEARCH Pattern 3): identical to today's `to_money(float)` path, so
downstream Decimals are bit-identical. Never round prices/quantities (D-14) — `quantize`
(`money.py:52-65`) applies only at cash/ledger boundaries.

**Docstring convention:** copy `money.py:1-23` — module docstring enumerating the locked
decisions (D-xx) the module embodies. Both analog files do this; the planner should carry the
bar-timing contract (RESEARCH Pattern 1, rules 1-7) as the `feed` module docstring the same way.

---

### `itrader/price_handler/store/base.py`, `feed/base.py`, `providers/base.py` (abstract seams) — NEW

**Analog:** `itrader/portfolio_handler/base.py:93-127` (`PortfolioStateStorage`) — CONTEXT.md
explicitly names this seam as the shape to mirror (#30). Spaces indentation.

**ABC pattern** (`portfolio_handler/base.py:93-127`):

```python
class PortfolioStateStorage(ABC):
    """Abstract base class for portfolio-manager state storage (D-09/D-10, M2-08).

    Provides a unified interface for managing portfolio state across different
    storage backends (in-memory for backtesting, PostgreSQL for live trading),
    generalizing the proven ``order_handler/base.py::OrderStorage`` pattern.
    ...
    """

    @abstractmethod
    def set_position(self, ticker: str, position: 'Position') -> None:
        """Store (insert or replace) the open position for a ticker.

        Parameters
        ----------
        ticker : str
            The ticker the open position is keyed by.
        """
        pass
```

Copy: ABC + `@abstractmethod` + numpydoc per method + section-comment grouping
(`# -- Positions ---...`). RESEARCH suggests `typing.Protocol` as an alternative; the
established in-repo seam precedent (order storage, portfolio state) is **ABC** — either is
acceptable, but ABC matches three existing seams. Suggested surfaces are in RESEARCH
Pattern 6 (`read_bars/write_bars/has/symbols/index`; `current_bars/window/megaframe`;
`fetch_ohlcv/get_symbols`).

**Package `__init__` re-export pattern** (`portfolio_handler/storage/__init__.py:1-18`):

```python
"""Portfolio state storage module for the iTrader trading system (M2-08).
...
"""
from ..base import PortfolioStateStorage, IdLike
from .in_memory_storage import InMemoryPortfolioStateStorage
from .storage_factory import PortfolioStateStorageFactory

__all__ = [
    'PortfolioStateStorage',
    ...
]
```

**Factory pattern — only if needed** (`portfolio_handler/storage/storage_factory.py:23-62`):
`create(environment)` → backtest/test = in-memory impl, live = `NotImplementedError`
("deferred to D-sql"), unknown = `ValueError` with supported-environments message. RESEARCH
notes direct construction in `TradingSystem` is simpler when only one impl is constructible
this phase (D-18 "trading systems wire Store + Feed directly") — planner discretion; if a
factory ships, copy this file's shape verbatim.

---

### `itrader/price_handler/store/csv_store.py` (store, file I/O) — NEW

**Analog:** `itrader/price_handler/data_provider.py:131-182` (`_load_csv_data`) — the proven
CSV→canonical-frame logic the Store inherits (CONTEXT.md "Reusable Assets"). New file = spaces
(the original uses tabs — re-indent on the move).

**Core read pattern — inherit this logic nearly verbatim** (`data_provider.py:144-182`):

```python
# Trusted-but-verify: validate the Binance-kline header before mapping.
expected_cols = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']
raw = pd.read_csv(self.csv_path)
missing = [col for col in expected_cols if col not in raw.columns]
if missing:
    raise MalformedDataError(
        str(self.csv_path), f"missing columns {missing}")

data = raw[expected_cols].copy()
data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']

# Format index exactly like CCXT._format_data: tz-aware then convert to
# the configured timezone so it matches the ping clock by construction.
data = data.set_index('date')
data.index = pd.to_datetime(data.index, utc=True)
data.index = data.index.tz_convert(TIMEZONE)
data.index.name = 'date'
data = data.astype(float)

# D-02: pin the date window explicitly ... on the feed side
start = pd.Timestamp(self.CSV_START_DATE, tz=TIMEZONE)
end = pd.Timestamp(self.CSV_END_DATE, tz=TIMEZONE) + pd.Timedelta(days=1)
data = data.loc[start:end]

if data.empty:
    raise MissingPriceDataError(
        str(self.csv_path),
        f"empty frame after the {self.CSV_START_DATE} -> "
        f"{self.CSV_END_DATE} window slice")
```

Also carry the class constants pattern (`data_provider.py:44-51`): `CSV_DEFAULT_PATH`,
`CSV_START_DATE = '2018-01-01'`, `CSV_END_DATE = '2026-06-03'`, `CSV_TICKER = 'BTCUSD'` —
the oracle is pinned to these values.

**Error pattern — typed loud errors** (`core/exceptions/data.py:13-28`, already exist):

```python
class MalformedDataError(DataError):
    """Raised when a data source's structure is invalid (e.g. missing columns)."""
    def __init__(self, source: str, details: str):
        ...
        super().__init__(f"Malformed data in '{source}': {details}")

class MissingPriceDataError(DataError):
    """Raised when a data source yields no usable price data."""
```

**FR7 anti-pattern to fix, not copy** (`data_provider.py:241-249, 267-275`) — the bare
`except:` → log + `return None` blocks. Store/Feed accessors must raise
`MissingPriceDataError` instead:

```python
# data_provider.py:267-275 — DO NOT replicate; this is the bug being fixed
if ticker in self.available_symbols:
    try:
        last_prices = self.prices[ticker].loc[time]
        return last_prices
    except:
        self.logger.error('Price data for %s at time %s not found', ticker, str(time))
        return None
```

**Logger convention** (`data_provider.py:88-89`):
`self.logger = get_itrader_logger().bind(component="CsvPriceStore")` + init info log.

---

### `itrader/price_handler/feed/bar_feed.py` (read-model, per-tick query) — NEW

**Analogs:** `data_provider.py:277-346` (the query logic being fixed/repointed) +
`in_memory_storage.py` (dict-backed working state shape) + `matching_engine.py:1-11`
(pure-component docstring discipline: "NO dependency on the event queue ... deterministic and
unit-testable" — the Feed should make the same claim). Spaces.

**The look-ahead bug being replaced** (`data_provider.py:335-346` — for the expected-diff
note and the regression test, NOT to copy):

```python
current_timeframe = to_timedelta(self.timeframe)
if timeframe != current_timeframe:
    ratio = timeframe / current_timeframe
    start_dt = (time - current_timeframe * window * ratio) + timeframe
    # resample_ohlcv takes a pandas offset string, not a timedelta.
    resample_rule = timedelta_to_str(timeframe) or self.timeframe
    return resample_ohlcv(self.get_bars(ticker, start_dt, time+timeframe),  # <- look-ahead:
                resample_rule).head(window)                                 #    upper bound time+timeframe
else:
    start_dt = time - (timeframe * window) + timeframe
    return self.get_bars(ticker, start_dt, time)   # same-tf branch already "last closed bar <= T"
```

Replacement mechanics are RESEARCH Pattern 2 (verified against pandas 2.3.3): precompute
`base_frame.resample(alias, label="left", closed="left").agg(_AGG)` once per
(ticker, timeframe) at construction; per tick
`pos = resampled.index.searchsorted(asof - TF + tf_base, side="right")` then
`resampled.iloc[max(0, pos - max_window):pos]`. The Feed owns its own
timedelta→offset-alias map (`minutes→'min'`, `hours→'h'`, `days→'D'`) — do NOT reuse
`outils/time_parser.timedelta_to_str` for resample rules (Pitfall 2: `'m'` = month-end in
pandas 2.3.3 and FutureWarning = test error).

**Megaframe bugs being fixed in the Feed method (D-19)** (`data_provider.py:369-378`):

```python
df_list: list[Any] = []
for symbol in self.available_symbols:
    df = self.get_resampled_bars(time, symbol, tf_delta, window)
    df.name = symbol
    if df.index.tz is not None:        # FR8 bug 1: silently drops tz-naive symbols
        df_list.append(df)
megaframe = pd.concat(df_list, axis=1, keys=self.prices.keys())  # FR8 bug 2: keys may
return megaframe                                                 # misalign with df_list
```

Fix: store normalizes tz-aware at load (condition disappears); `keys=` must be the actually
included symbols.

**Dict-backed state shape** (`in_memory_storage.py:27-41` — constructor comment style for the
precomputed-frame cache):

```python
def __init__(self) -> None:
    # Open positions (working state, keyed by ticker) — was PositionManager._positions
    self._positions: Dict[str, 'Position'] = {}
    ...
```

Key the Feed's cache `dict[tuple[str, str], pd.DataFrame]` by (ticker, canonical timeframe
string) with the same "what this container is / where it came from" inline comments.

---

### `itrader/events_handler/events/market.py` — BarEvent redesign (MODIFY)

**Analog:** sibling events in the same file. Target shape = `ScreenerEvent`/`TimeEvent`
(`market.py:16-30, 180-203`): frozen dataclass, typed payload field, `__str__`/`__repr__`,
NO accessor methods.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class TimeEvent(Event):
    """..."""
    type: EventType = field(default=EventType.TIME, init=False)

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)
```

New BarEvent: `bars: dict[str, Bar]` (import Bar from `itrader.core.bar`). DELETE
`get_last_close/open/high/low` (`market.py:58-159` — the four hasattr ladders, FR1).
Consumers collapse to `event.bars[ticker].close`. A ticker with no bar at T is absent from
the dict (consumers use `.get`/`KeyError` handling).

**Consumer collapse sites** (verified):
- `strategy_handler/base.py:79` area — `get_last_close` → `bars[ticker].close` (Decimal;
  the WR-12 missing-ticker guard at `base.py:80-87` becomes a dict-membership check)
- `matching_engine.py:106-108` — `bar.get_last_open/high/low(ticker)` → `bar.bars[ticker].open/.high/.low`
- `universe/dynamic.py:72` — `price_handler.get_bar(...)` Series → `feed.current_bars(T)`
- portfolio market-value update (close-marking, D-05) — Decimal close direct

---

### `itrader/execution_handler/matching_engine.py` (MODIFY — D-03/D-12/D-13/D-06)

**Analog:** self. Spaces indentation (this file already uses spaces).

**Existing MARKET branch — D-13 is flipping a switch, not building machinery**
(`matching_engine.py:123-125`):

```python
if order.order_type == OrderType.MARKET:
    # next-bar market order: unconditional fill at the open
    return open_
```

**Stop gap fills already D-03-conformant — keep** (`matching_engine.py:127-133`):

```python
if order.order_type == OrderType.STOP:
    if order.action is Side.SELL:           # stop-loss on a long
        if low <= trigger:
            return min(open_, trigger)      # pessimistic gap-down
    else:                                   # BUY stop (cover short)
        if high >= trigger:
            return max(open_, trigger)      # pessimistic gap-up
```

**Limit branch CHANGES (D-03 limit-or-better)** — current code at `:135-144` fills at trigger
even on favorable gaps; new rule (RESEARCH Pattern 4): SELL limit `open >= trigger → open`,
else `high >= trigger → trigger`; BUY limit `open <= trigger → open`, else
`low <= trigger → trigger`.

**Decimal retype (D-12)** — these D-22 float boundaries die:
- `matching_engine.py:121` `trigger = float(order.price)` → compare Decimal directly against
  `Bar` Decimal OHLC
- `FillDecision.fill_price: float` (`:25-37`) → `Decimal`; delete `fill_quantity` (D-06)
- No quantization anywhere in matching (D-14 never-round-prices)

**Replace-in-book idiom to preserve** (`matching_engine.py:86-90` — frozen events are never
mutated):

```python
self._resting[order_id] = dataclasses.replace(
    order,
    price=order.price if new_price is None else to_money(new_price),
    quantity=order.quantity if new_quantity is None else to_money(new_quantity),
)
```

---

### `itrader/execution_handler/exchanges/simulated.py` (MODIFY — D-01/D-11/D-12/PERF1)

**Analog:** self. Tabs indentation — match the file.

**`_emit_fill` hardcoded context — the D-11 defect** (`simulated.py:189-195`):

```python
commission = self.fee_model.calculate_fee(
    quantity=quantity_f, price=price_f,
    side=event.action.value.lower(), order_type="market")     # <- hardcoded (D-11 fix)
slippage_factor = self.slippage_model.calculate_slippage_factor(
    quantity=quantity_f, price=price_f,
    side=event.action.value.lower(), order_type="market")     # <- applied to ALL fills (D-03 fix)
executed_price = price_f * slippage_factor
```

Fix shape (RESEARCH "Code Examples", maker/taker): pass
`order_type=decision.order_event.order_type.value` and
`is_maker=(order_type is OrderType.LIMIT)` (`MakerTakerFeeModel._is_maker_order` at
`maker_taker_fee_model.py:88-120` already supports the `is_maker` override); apply slippage
only for MARKET/triggered-STOP, never LIMIT. Decimal-native: `price_f`/`quantity_f` float
casts (`:183-184`) die; `executed_price = fill_price * slippage_factor` in Decimal.

**Routing switch deleted (D-13)** (`simulated.py:252-255`):

```python
if event.order_type == OrderType.MARKET and self.execution_timing == "immediate":
    self.execute_order(event)
else:
    self.matching_engine.submit(event)
```

→ all NEW orders `submit()`; `execution_timing` attr (`:68`) deleted. Pre-trade
validation/rejection stays at `on_order` time — preserve the
`FillEvent(REFUSED)` path (`_emit_rejection`, `:162-169`) and the
`FillEvent(CANCELLED)` shape (`:219-224`, `commission=Decimal("0")`).

**PERF1** — `time.sleep(0.1)` at `simulated.py:270` — delete.

**D-10** — `TieredFeeModel` factory branch in `_init_fee_model` (~`:465-475`) — delete with
the file.

---

### Fee/slippage ABC unification (MODIFY — D-12, M5-04)

**Survivor pattern — fee base raise-contract** (`fee_model/base.py:52-88`):

```python
def validate_inputs(self, quantity, price, side="buy", order_type="market") -> None:
    """...
    Raises
    ------
    ValueError
        If any parameter is invalid
    """
    if not isinstance(quantity, (int, float, Decimal)) or quantity <= 0:
        raise ValueError(f"Quantity must be positive, got {quantity}")
    ...
```

**Dying pattern — slippage bool-and-silently-neutralize** (`slippage_model/base.py:59-85`
returns `bool`; `fixed_slippage_model.py:61-62` does `if not self.validate_inputs(...):
return 1.0`). Unify both ABCs on: Decimal signatures
(`calculate_fee(quantity: Decimal, price: Decimal, ...) -> Decimal`,
`calculate_slippage_factor(...) -> Decimal`), `validate_inputs` RAISES typed exceptions
(use the `ValidationError` family in `itrader/core/exceptions/base.py`, matching the
project's `<Specific><Category>Error` convention). Seeded-RNG seam in slippage models
(Phase 2 D-11, `simulated.py:62-63`) survives: the float `rng.uniform` jitter enters Decimal
once via `to_money`.

---

### Trading-system rewiring (MODIFY — D-18)

**Analog:** `backtest_trading_system.py` itself. Tabs.

**Construction site being replaced** (`backtest_trading_system.py:61-63`):

```python
self.price_handler = PriceHandler(self.exchange, [], '', start_date or '', end_dt = end_date)
self.universe = DynamicUniverse(self.price_handler, self.global_queue)
self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)
```

→ construct `CsvPriceStore` + `BarFeed`, pass the Feed to `DynamicUniverse` and
`StrategiesHandler` (construction-time dependency, NOT queue traffic — same injection style
as today's `price_handler` arg; CLAUDE.md queue-only rule applies to handlers, the Feed is a
read-model).

**Ping-clock derivation being repointed** (`backtest_trading_system.py:126`):

```python
self.time_generator.set_dates(next(iter(self.price_handler.prices.items()))[1].index)
```

→ `self.time_generator.set_dates(store.index(ticker))` (the `PriceStore.index()` surface
exists for exactly this).

**Pitfall-8 consumers needing minimal conformance edits:**
`StatisticsReporting(self.portfolio_handler, self.price_handler)` (`:95-97`) → takes the
Store; `live_trading_system.py:12,104` → same Store+Feed wiring shape (D-live owns making it
work). Symbol methods (`set_symbols` at `data_provider.py:382-386`, `_init_symbols`
`:395-409`) — minimal relocation onto Store/trading system, `'all'`-branch stays dormant
(M5b #33 owns redesign).

---

### Strategy push repoint (MODIFY — D-20)

**Analog:** `strategies_handler.py:45-53` — keep the exact loop shape, swap the data source:

```python
for strategy in self.strategies:
    # Check if the strategy's timeframe is a multiple of the bar event time
    if not check_timeframe(event.time, strategy.timeframe):
        continue
    # Calculate the signal for each ticker or pair traded from the strategy
    strategy.last_event = event
    for ticker in strategy.tickers:
        data = self.price_handler.get_resampled_bars(event.time, ticker, strategy.timeframe, strategy.max_window)
        strategy.calculate_signal(ticker, data)
```

`self.price_handler.get_resampled_bars(...)` → `self.feed.window(ticker, strategy.timeframe,
strategy.max_window, asof=event.time)`. Keep the two-arg `calculate_signal(ticker, window)`
signature (RESEARCH Open Question 2 recommendation — M5b owns the contract); the current Bar
rides on `last_event.bars[ticker]`. The Feed window must keep its tz-aware DatetimeIndex
(`SMA_MACD` slices by time). Constructor: `__init__(global_queue, feed)` mirrors today's
`__init__(global_queue, price_handler)` (`:17-25`). Tabs.

### Universe repoint (MODIFY — D-15)

**Analog:** `universe/dynamic.py:58-84` — same method, Feed-built Bars:

```python
for ticker in self.strategies_universe:
    if ticker in self.price_handler.prices.keys():          # PERF4: direct .prices access dies
        bar = self.price_handler.get_bar(ticker, time_event.time)   # Series via bare-except getter
        bars[ticker] = bar
    ...
bar_event = BarEvent(time=time_event.time, bars=bars)
```

→ `bars = self.feed.current_bars(time_event.time)` (dict[str, Bar]); keep the
`last_bar` caching, queue-put, and warning-log shape. Tabs.

---

### Test files (NEW — D-24)

**Unit-test style analog** (`tests/unit/core/test_money.py:23-34`) — flat functions, module
`pytestmark`, decision-tagged comments:

```python
from decimal import Decimal
import pytest
from itrader.core.money import quantize, to_money

pytestmark = pytest.mark.unit


def test_to_money_uses_str_path():
    # D-04: Decimal(str(10.1)) == Decimal("10.1"); Decimal(10.1) would NOT.
    assert to_money(10.1) == Decimal("10.1")
```

Apply to `tests/unit/core/test_bar.py`, `tests/unit/price/test_csv_store.py`,
`tests/unit/price/test_bar_feed.py`, `tests/unit/execution/test_fee_models.py`,
`test_slippage_models.py`. Markers: only declared ones (`unit`, `execution`, ...) —
`--strict-markers`. New `tests/unit/price/` dir mirrors existing per-domain layout
(no `__init__.py` files in test dirs — match `tests/unit/core/`).

**Fixture-helper analog — the Pitfall 9 conversion target**
(`tests/unit/execution/test_matching_engine.py:12-33`):

```python
def make_order_event(order_type, action, price, order_id,
                     ticker="BTCUSDT", quantity=1.0, parent_order_id=None):
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker=ticker, action=Side(action), price=price,
        quantity=quantity, exchange="default", strategy_id=1, portfolio_id=1,
        order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
        command=OrderCommand.NEW,
    )


def make_bar(open_, high, low, close, ticker="BTCUSDT"):
    bars = {
        ticker: pd.DataFrame(
            {"open": [open_], "high": [high], "low": [low], "close": [close], "volume": [1]}
        )
    }
    return BarEvent(time=datetime(2024, 1, 1), bars=bars)


@pytest.fixture
def engine():
    return MatchingEngine()
```

The shared `make_bar`/`make_bar_event` (new, in conftest) keeps this helper signature but
builds `Bar` structs: `{ticker: Bar(time=..., open=Decimal(str(open_)), ...)}`. Must land in
the SAME commit as the BarEvent change and convert all 9 fixture-constructing test files
mechanically (Pitfall 9: `test_stop_limit_orders`, `test_matching_engine`,
`test_simulated_exchange`, `test_portfolio_update`, `test_bar_event_ohlc`, `test_events`,
`test_event_immutability`, `test_strategy`, `test_execution_handler_routing`).

Look-ahead regression, next-open matching, and megaframe-fixture test cores are written out
in RESEARCH "Code Examples" — use those as the seed assertions.

---

## Shared Patterns

### Decimal money policy
**Source:** `itrader/core/money.py` (whole file, 65 lines)
**Apply to:** `core/bar.py`, `matching_engine.py`, fee/slippage models, `_emit_fill`
- Entry ALWAYS via `to_money`/`Decimal(str(x))` (`money.py:42-49`); never `Decimal(float)`.
- `quantize(value, instrument, kind)` (`money.py:52-65`) ONLY at cash/ledger/PnL boundaries —
  never on prices, quantities, or intermediate arithmetic (D-14).

### Frozen value-object / event machinery
**Source:** `itrader/events_handler/events/base.py:19-47`
**Apply to:** `core/bar.py`, BarEvent redesign
- `@dataclass(frozen=True, slots=True, kw_only=True)`; mutation via `dataclasses.replace`
  only (the `matching_engine.py:86-90` replace-in-book idiom).

### Seam = ABC + concrete impl (+ factory if >1 backend)
**Source:** `itrader/portfolio_handler/base.py:93+` + `storage/in_memory_storage.py` +
`storage/storage_factory.py` + `storage/__init__.py`
**Apply to:** all three `price_handler` Protocol/ABC files and `csv_store.py`/`bar_feed.py`
- Numpydoc on every abstract method; section comments grouping the surface; `__init__.py`
  re-exports with `__all__`; live/SQL backends raise `NotImplementedError("deferred to D-sql")`.

### Typed loud errors, never silent None
**Source:** `itrader/core/exceptions/data.py` (`MalformedDataError`, `MissingPriceDataError`),
`itrader/core/exceptions/base.py` (`ValidationError` family)
**Apply to:** Store/Feed accessors (FR7), fee/slippage `validate_inputs` (D-12)
- Exceptions carry context args and compose the message in `__init__`
  (`data.py:16-19` shape). Raising replaces both the bare-`except:`→`None` accessors and the
  slippage bool-contract.

### Logger binding
**Source:** every handler, e.g. `data_provider.py:88`, `simulated.py:57`
**Apply to:** `CsvPriceStore`, `BarFeed`, anything new with runtime behavior
```python
self.logger = get_itrader_logger().bind(component="ClassName")
self.logger.info('<Component> initialized')
```
Pure components (MatchingEngine-style) take NO logger — the Feed's slice path should stay
pure/deterministic like `matching_engine.py:7-10` documents.

### Indentation rule (CLAUDE.md)
New files (`core/bar.py`, all `price_handler/` packages, all tests): **spaces**.
Edited in place: `matching_engine.py` = spaces; `simulated.py`, `strategies_handler.py`,
`universe/dynamic.py`, `backtest_trading_system.py`, `order_manager.py` = **tabs**.

### Oracle tripwire (D-21/D-22)
**Source:** `tests/integration/test_backtest_oracle.py` + `scripts/run_backtest.py`
**Apply to:** every plan
- Structural commits: `poetry run pytest tests/integration/test_backtest_oracle.py -q` must
  pass byte-exact. Result-changing commit(s): regenerate `tests/golden/` via
  `scripts/run_backtest.py`, owner-signed expected-diff note in the same commit (D-23).

### mypy override hygiene (Pitfall 7)
**Source:** `pyproject.toml` `[[tool.mypy.overrides]]` (~lines 83-96)
**Apply to:** every relocation commit — update
`itrader.price_handler.sql_handler` → `itrader.price_handler.store.sql_store`,
`...exchange.CCXT`/`...exchange.OANDA` → `...providers.*`,
`...live_streaming.BINANCE_Live` → `...providers.binance_stream` in the same commit as each
`git mv`. New store/feed/bar packages get NO override — they must be `mypy --strict` clean.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `itrader/price_handler/ingestion.py` | utility (stub) | batch | No offline-pipeline entry point exists; nearest shape is the `load_data` non-csv loop (`data_provider.py:109-127` — provider fetch → store write). Ship as a stub function/docstring only; real CLI deferred to the persistence milestone. |

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/events_handler/`,
`itrader/portfolio_handler/storage/` + `base.py`, `itrader/order_handler/storage/`,
`itrader/price_handler/`, `itrader/execution_handler/` (matching engine, exchanges,
fee/slippage models), `itrader/strategy_handler/`, `itrader/universe/`,
`itrader/trading_system/`, `tests/unit/`
**Files scanned:** ~60 listed; 16 read in full or in targeted ranges
**Pattern extraction date:** 2026-06-06
