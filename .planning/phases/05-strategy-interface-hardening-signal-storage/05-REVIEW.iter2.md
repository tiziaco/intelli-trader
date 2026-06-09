---
phase: 05-strategy-interface-hardening-signal-storage
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - itrader/core/enums/__init__.py
  - itrader/core/enums/trading.py
  - itrader/core/ids.py
  - itrader/outils/id_generator.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/config.py
  - itrader/strategy_handler/signal_record.py
  - itrader/strategy_handler/storage/__init__.py
  - itrader/strategy_handler/storage/base.py
  - itrader/strategy_handler/storage/in_memory_storage.py
  - itrader/strategy_handler/storage/storage_factory.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/strategy_handler/strategies/__init__.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/live_trading_system.py
  - scripts/run_backtest.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_reservation_inertness.py
  - tests/integration/test_universe_spans.py
  - tests/unit/strategy/test_signal_store.py
  - tests/unit/strategy/test_strategy_config.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Phase 5 hardens the strategy interface (typed pydantic config, pure-alpha
`generate_signal` contract, `OrderType`/`Timeframe`/`TradingDirection` enums)
and adds the `SignalStore` capture seam mirroring the order-storage seam. The
core money/Decimal discipline, frozen-config immutability, and the queue-only
read-model boundary are correctly respected. The signal-store seam is clean and
well-tested.

No BLOCKER-class correctness or security defects were found in the reviewed
files. The findings below are robustness and quality issues. The most material
ones are the subscription API asymmetry (`unsubscribe_portfolio` can raise on a
benign double-call and `subscribe_portfolio` allows duplicate fan-out), a silent
overwrite-on-collision in the in-memory store that contradicts the documented
"insertion order" contract, the live system dropping the signal store on the
floor (no `self` retention, no accessor — a write-only accumulation), and the
live event loop bypassing the documented publish-and-continue error seam.

The golden backtest path (`SMA_MACD` / `FractionOfCash(0.95)` / `LONG_ONLY`) is
oracle-locked by `test_backtest_oracle.py`; the relocated SMA_MACD exit-branch
logic is behavior-preserving and out of scope for change here, but one latent
structural oddity is flagged for awareness (IN-05).

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `unsubscribe_portfolio` raises `ValueError` on an already-unsubscribed id; `subscribe_portfolio` allows duplicate fan-out

**File:** `itrader/strategy_handler/base.py:146-150`
**Issue:** The pair is asymmetric and fragile:
```python
def subscribe_portfolio(self, portfolio_id: int) -> None:
    self.subscribed_portfolios.append(portfolio_id)   # no dedup
def unsubscribe_portfolio(self, portfolio_id: int) -> None:
    self.subscribed_portfolios.remove(portfolio_id)   # raises ValueError if absent
```
`list.append` allows the same `portfolio_id` to be subscribed twice — which
fans a signal out to that portfolio TWICE in `calculate_signals` (the fan-out
loops `for portfolio_id in strategy.subscribed_portfolios`), producing two
`SignalEvent`s and two orders for one intent. Conversely `list.remove` raises
`ValueError` on a double-unsubscribe or an unsubscribe of a never-subscribed id.
In live mode (publish-and-continue) this surfaces as a noisy `ErrorEvent`; a
defensive caller cannot make `unsubscribe` idempotent.
**Fix:** Make both operations idempotent (or back the field with a set):
```python
def subscribe_portfolio(self, portfolio_id: int) -> None:
    if portfolio_id not in self.subscribed_portfolios:
        self.subscribed_portfolios.append(portfolio_id)

def unsubscribe_portfolio(self, portfolio_id: int) -> None:
    if portfolio_id in self.subscribed_portfolios:
        self.subscribed_portfolios.remove(portfolio_id)
```

### WR-02: `InMemorySignalStore.add` silently overwrites on `signal_id` key collision, breaking the documented "insertion order / one record per intent" contract

**File:** `itrader/strategy_handler/storage/in_memory_storage.py:33-39`
**Issue:** `add` is a bare dict write `self._by_id[record.signal_id] = record`.
The class docstring and `base.py` promise `get_all()` returns records "in
insertion order" and one record per intent (D-09). If a caller ever re-`add`s a
`SignalRecord` whose `signal_id` already exists (e.g. a record constructed with
an explicit `signal_id=` rather than the defaulted UUIDv7, or a replayed
record), the dict write SILENTLY replaces the prior record AND moves it to the
end of insertion order — corrupting both the count and the ordering invariant
the tests rely on. The seam advertises a queryable append-only sink but
implements a mutable upsert with no guard. (This is about idempotency of
explicit ids, not RNG collision odds.)
**Fix:** Reject a duplicate id, or document the upsert semantics honestly:
```python
def add(self, record: SignalRecord) -> None:
    if record.signal_id in self._by_id:
        raise ValueError(f"duplicate signal_id: {record.signal_id!r}")
    self._by_id[record.signal_id] = record
```

### WR-03: Live system constructs a `SignalStore` but neither retains it on `self` nor exposes an accessor — captured signals are permanently unreachable

**File:** `itrader/trading_system/live_trading_system.py:110-111`
**Issue:**
```python
signal_store = SignalStorageFactory.create('backtest')
self.strategies_handler = StrategiesHandler(self.global_queue, self.feed, signal_store)
```
The store is a local variable. The backtest system holds it as
`self._signal_store` and exposes `get_signal_records()` / `get_signal_store()`
(backtest_trading_system.py:102, 234-257); the live system does neither. Every
`SignalRecord` the handler captures during a live run accumulates in a heap
object that nothing can ever read — a growing, write-only structure with no
consumer (a slow, unbounded accumulation). A live integrator who expects
symmetry with backtest will find no way to inspect captured signals. Either
retain + expose it, or (if signal capture is genuinely backtest-only in v1.1)
do not pay the capture cost in live mode.
**Fix:** Retain and expose it, mirroring the backtest system:
```python
self._signal_store = SignalStorageFactory.create('backtest')
self.strategies_handler = StrategiesHandler(self.global_queue, self.feed, self._signal_store)
...
def get_signal_records(self):
    return self._signal_store.get_all()
```

### WR-04: `get_strategies_universe` shadows the builtin `tuple` and carries a dead-but-wrong pair branch inconsistent with the `list[str]` config contract

**File:** `itrader/strategy_handler/strategies_handler.py:160-177`
**Issue:** Two problems in one comprehension:
```python
if strategy.tickers and isinstance(strategy.tickers[0], tuple):
    traded_tickers += [value for tuple in strategy.tickers for value in tuple]
```
(1) The loop variable `tuple` shadows the builtin `tuple` — a readability/quality
defect that would break any later `tuple(...)` use in scope. (2) The pair/single
decision is made SOLELY from `strategy.tickers[0]`: a mixed list (pair tuple at
index 0, plain strings later) would iterate a `str` character-by-character. The
declared contract in `config.py` is `tickers: list[str]` — tuples are not even
representable under the declared type, so the `isinstance(..., tuple)` branch
can never legitimately fire for a config-built strategy, yet it remains as a
trap.
**Fix:** Rename the loop variable and align with the declared `list[str]`
contract:
```python
for strategy in self.strategies:
    if strategy.tickers and isinstance(strategy.tickers[0], tuple):
        traded_tickers += [sym for pair in strategy.tickers for sym in pair]
    else:
        traded_tickers += strategy.tickers
```

### WR-05: `LiveTradingSystem` event loop calls private `_dispatch` and swallows handler exceptions, bypassing the documented publish-and-continue `ErrorEvent` seam

**File:** `itrader/trading_system/live_trading_system.py:258-287`
**Issue:** The loop dispatches `self.event_handler._dispatch(event)` inside a
broad `try/except Exception` that logs, increments `errors_count`, and
`continue`s. The documented live error policy is publish-and-continue:
`_on_handler_error` should emit an `ErrorEvent` and keep draining (CLAUDE.md).
By calling the private `_dispatch` directly rather than the public
`process_events()`, the loop never runs the `_on_handler_error` publication —
a failed handler is reduced to a log line and a counter, and no `ErrorEvent` is
queued for `status_callback`/ERROR-route consumers. A persistent per-event
failure (e.g. an unrouted type hitting `_dispatch`'s `NotImplementedError`)
becomes an invisible hot spin. Reaching into a private method is also an
encapsulation break.
**Fix:** Route through the public processing seam so `_on_handler_error` runs,
or explicitly emit an `ErrorEvent` in the `except` block before `continue`. Stop
calling the private `_dispatch`.

## Info

### IN-01: `_update_status` / `_update_stats` annotate `str = None` defaults (type lie under the union)

**File:** `itrader/trading_system/live_trading_system.py:167, 191`
**Issue:** `def _update_status(self, new_status, error_msg: str = None)` and
`def _update_stats(self, event_type: str = None)` declare a `str` parameter with
a `None` default — the value can be `None` but the annotation forbids it. Masked
only because the live module is in the mypy-deferred override set; the
annotation still misleads a reader.
**Fix:** `error_msg: Optional[str] = None` / `event_type: Optional[str] = None`.

### IN-02: `SignalStorageFactory` rejects deferred `'live'` with `ConfigurationError` while the order-storage path next to it uses `NotImplementedError` — divergent deferred-backend contract

**File:** `itrader/strategy_handler/storage/storage_factory.py:52-57`, `itrader/trading_system/live_trading_system.py:124-131`
**Issue:** The signal factory raises `ConfigurationError` for `'live'`, but the
order-storage fallback (live system) catches only `NotImplementedError`. The two
storage seams encode "not yet implemented" with different exception types. A
future live wiring of the signal store would need to catch `ConfigurationError`
for signals but `NotImplementedError` for orders — an inconsistency that invites
an uncaught exception.
**Fix:** Align the deferred-backend exception type across both storage
factories, or document the divergence at the live call sites.

### IN-03: `to_dict()` serializes `strategy_id` (a `uuid.UUID`) without stringifying — JSON-unsafe

**File:** `itrader/strategy_handler/base.py:72-88`
**Issue:** `to_dict` returns `"strategy_id": self.strategy_id` where
`strategy_id` is a `StrategyId` (`uuid.UUID` at runtime). `order_type` /
`direction` are correctly `.value`-serialized and policies are `repr`-ed, but
the raw UUID is left as a `UUID` object, so `json.dumps(strategy.to_dict())`
raises `TypeError: Object of type UUID is not JSON serializable`. The method
name implies a serialization-edge dict.
**Fix:** `"strategy_id": str(self.strategy_id)`.

### IN-04: `subscribed_portfolios` typed `list[int]` but the system's portfolio identity is `PortfolioId` (UUID)

**File:** `itrader/strategy_handler/base.py:44, 146-150`
**Issue:** `self.subscribed_portfolios: list[int]` and `subscribe_portfolio(...,
portfolio_id: int)` declare integer portfolio ids, but `core/ids.py` defines
`PortfolioId = NewType("PortfolioId", uuid.UUID)`. Tests pass plain ints, so the
in-memory backtest works, but the type contract diverges from the canonical
UUID scheme and will mismatch when the strategy layer is wired to real
portfolio ids.
**Fix:** Use `PortfolioId` (or document why the strategy layer keeps integer
portfolio handles distinct from the UUID scheme).

### IN-05: Relocated SMA_MACD exit branch (`sell`) is gated by the bullish trend filter — latent logic oddity (behavior-preserving, flagged for awareness)

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:66-72`
**Issue:** The exit `elif` is nested under `if short_sma.iloc[-1] >=
long_sma.iloc[-1]` (the bullish entry filter), so a long EXIT (`self.sell`) can
ONLY fire while the short SMA is still above the long SMA. A bearish SMA cross
that also flips the MACD histogram down would NOT exit the position. This is a
pre-existing structure carried verbatim from the deleted `SMA_MACD_strategy.py`
and is locked by `test_backtest_oracle.py`, so it MUST NOT be changed in this
phase — but it is a genuine logic smell (the `# Exit` comment reads as if outside
the filter while the code is inside it).
**Fix:** No change now (oracle-locked). Revisit at a future re-baseline whether
the exit should be filter-independent.

### IN-06: `min_timeframe` seeded with a `timedelta(weeks=100)` magic sentinel that survives when no strategy is registered

**File:** `itrader/strategy_handler/strategies_handler.py:40, 220`
**Issue:** `self.min_timeframe = timedelta(weeks=100)` is an arbitrary
large-sentinel so `min([self.min_timeframe, strategy.timeframe])` collapses to
the first real strategy timeframe. If no strategy is ever added, `min_timeframe`
stays at the meaningless 100-week value; a downstream consumer reading it gets
silent garbage rather than a clear "no strategies" signal.
**Fix:** Initialize to `None` and compute the min defensively, or compute
`min_timeframe` lazily from `self.strategies` only when at least one exists.

---

_Reviewed: 2026-06-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
