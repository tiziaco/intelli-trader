---
phase: 05-strategy-interface-hardening-signal-storage
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 22
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
  - tests/unit/strategy/test_signal_store.py
  - tests/unit/strategy/test_strategy_config.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 4
  info: 6
  total: 10
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-09
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Phase 5 hardened the strategy interface (single pydantic config constructor, `OrderType`
enum end-to-end, warmup guard relocated to the handler, strategies relocated to
`strategies/`) and added a pluggable signal-storage seam. The architectural shape is sound:
the config contract is frozen and validates loudly, the `SignalStore` seam mirrors the
order-storage seam faithfully, per-intent pre-fan-out capture is implemented correctly
(verified one-record-per-intent against the fan-out loop), and the warmup short-circuit is
behaviorally equivalent to the removed in-strategy guard (`warmup == max_window == max(long_window, 100)`
for SMA_MACD), so the golden byte-exactness claim holds for the result-bearing path.

No correctness defect that would alter the golden run was found, so there are **no
BLOCKERs**. The defects found are type-contract violations that contradict `mypy --strict`
(which covers `base.py` and `strategies_handler.py`) and the project's typed-ID discipline,
plus dead imports and quality issues. The most material is the `int`-typed portfolio-id
seam that at runtime always carries a `PortfolioId` (UUID) — a standing mismatch that the
Phase 5 rewrite of `base.py` re-stamped rather than corrected.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `subscribe_portfolio` / `subscribed_portfolios` typed `int` but always receives a `PortfolioId` (UUID) at runtime

**File:** `itrader/strategy_handler/base.py:44,146-150`
**Issue:** `self.subscribed_portfolios: list[int]` and `subscribe_portfolio(self, portfolio_id: int)`
declare `int`, but every real call site subscribes the return of
`PortfolioHandler.add_portfolio(...) -> PortfolioId` (a `uuid.UUID`) — see
`scripts/run_backtest.py:89-95` (`portfolio_id = system.portfolio_handler.add_portfolio(...)`
then `strategy.subscribe_portfolio(portfolio_id)`). The value then flows unchanged into
`SignalEvent(portfolio_id=portfolio_id)` at `strategies_handler.py:141`, whose field is also
`int` (`events/signal.py:84`). `base.py` is in scope for `mypy --strict` (only
`strategy_handler.my_strategies.*` and `live_trading_system` are overridden). This is a real
type-contract violation and undermines the D-12/D-13 single-UUID-ID discipline — the id is a
nominal `PortfolioId`, not an `int`.
**Fix:**
```python
from itrader.core.ids import PortfolioId

# base.py
self.subscribed_portfolios: list[PortfolioId] = []

def subscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
    self.subscribed_portfolios.append(portfolio_id)

def unsubscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
    self.subscribed_portfolios.remove(portfolio_id)
```
Also retype `SignalEvent.portfolio_id` to `PortfolioId` so the whole seam is consistent.

### WR-02: `unsubscribe_portfolio` raises an unguarded `ValueError` on an unknown id

**File:** `itrader/strategy_handler/base.py:149-150`
**Issue:** `self.subscribed_portfolios.remove(portfolio_id)` raises `ValueError` if the id is
not subscribed. `subscribe_portfolio` does not guard against duplicate appends either, so the
two are asymmetric: a double-subscribe silently creates two fan-out events for the same
portfolio (duplicate `SignalEvent`s → duplicate orders), and an unsubscribe of an unknown id
crashes the caller. Under the backtest fail-fast policy (`EventHandler._on_handler_error`
re-raises) a stray unsubscribe would abort the run.
**Fix:**
```python
def subscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
    if portfolio_id not in self.subscribed_portfolios:
        self.subscribed_portfolios.append(portfolio_id)

def unsubscribe_portfolio(self, portfolio_id: PortfolioId) -> None:
    if portfolio_id in self.subscribed_portfolios:
        self.subscribed_portfolios.remove(portfolio_id)
```

### WR-03: `SignalStorageFactory` lowercases `environment` then reports the lowercased value in the "unknown" error

**File:** `itrader/strategy_handler/storage/storage_factory.py:48,59-63`
**Issue:** `environment = environment.lower()` mutates the parameter before the `else` branch
builds the error message with the already-lowercased value. A caller who passes `"PROD"` gets
`"Unknown environment: prod"`, which obscures what they actually typed and makes the loud
error less useful for debugging a misconfiguration. The `'live'` branch has the same problem.
**Fix:**
```python
normalized = environment.lower()
if normalized in ('backtest', 'test'):
    return InMemorySignalStore()
elif normalized == 'live':
    raise ConfigurationError("environment", environment, "...deferred...")
else:
    raise ConfigurationError(
        "environment", environment,
        f"Unknown environment: {environment!r}. Supported: 'backtest', 'test'")
```

### WR-04: Live system reaches across the boundary into the private `EventHandler._dispatch`

**File:** `itrader/trading_system/live_trading_system.py:258`
**Issue:** The processing loop calls `self.event_handler._dispatch(event)` — a private method —
instead of the public `process_events()`. The WR-09 comment explains the intent (avoid the
get→put-back→process re-ordering), but bypassing the public API means the loop no longer
benefits from any draining/error-routing the public method may perform, and it couples the
live loop to a private contract that can change without notice. `live_trading_system` is
mypy-overridden (D-live), so this will not fail the gate, but it is a robustness/coupling
defect in shipping code. Note also that `process_events()` exists precisely to drain the
whole queue per tick; dispatching exactly one event per `get()` is correct for the live
streaming model but should go through a public, documented entry point.
**Fix:** Add a public single-event entry point to `EventHandler` (e.g. `dispatch_one(event)`)
that wraps `_dispatch` with the same error seam, and call that from the live loop.

## Info

### IN-01: Dead imports in `live_trading_system.py`

**File:** `itrader/trading_system/live_trading_system.py:4,5,26`
**Issue:** `import time` (line 4), `import json` (line 5), and `TimeEvent` / `OrderEvent`
(line 26) are never referenced. Only `EventType` from line 26 is used (line 267).
**Fix:** Remove the unused imports: `import time`, `import json`, and reduce the events
import to `from itrader.events_handler.events import EventType`.

### IN-02: `_update_status` / `_update_stats` use `str = None` defaults instead of `Optional[str]`

**File:** `itrader/trading_system/live_trading_system.py:167,191`
**Issue:** `def _update_status(self, new_status, error_msg: str = None)` and
`_update_stats(self, event_type: str = None)` annotate a non-optional `str` with a `None`
default. The module is mypy-overridden so the gate stays green, but the annotation is
incorrect and misleads readers/IDEs.
**Fix:** `error_msg: Optional[str] = None` and `event_type: Optional[str] = None`.

### IN-03: Loop variable shadows the `tuple` builtin

**File:** `itrader/strategy_handler/strategies_handler.py:173`
**Issue:** `[value for tuple in strategy.tickers for value in tuple]` binds the comprehension
variable to the name `tuple`, shadowing the builtin within the comprehension scope. Pre-existing,
but it lives in a reviewed/modified file and is a readability/correctness hazard.
**Fix:** Rename to `pair`: `[value for pair in strategy.tickers for value in pair]`.

### IN-04: Stale "string order_type" comment after the enum migration

**File:** `itrader/strategy_handler/strategies_handler.py:124-125`
**Issue:** The comment block above the fan-out reads "D-05 boundary parse: the strategy
string order_type is converted to the enum HERE" but Phase 5 made `order_type` an
`OrderType` enum end-to-end (`base.py:41`, `config.py:50`), and the code now assigns
`order_type=strategy.order_type` directly with no string conversion. The comment describes a
seam that no longer exists and will mislead the next reader.
**Fix:** Update the comment to state that `order_type` is already an `OrderType` enum read off
the strategy; remove the "string ... converted to the enum HERE" claim.

### IN-05: `signal_store` parameter is unused in the live system after construction

**File:** `itrader/trading_system/live_trading_system.py:110-111`
**Issue:** `signal_store = SignalStorageFactory.create('backtest')` is constructed and injected
into the handler, but unlike the backtest system (which holds `self._signal_store` and exposes
`get_signal_records()` / `get_signal_store()`), the live system keeps no reference and offers
no post-run accessor. Captured signals are therefore unreachable in live mode. This is
consistent with the "D-live deferred" posture, but worth recording so the gap is intentional,
not forgotten.
**Fix:** When D-live lands, hold the store on `self._signal_store` and add accessors mirroring
the backtest system; until then, a one-line comment noting the deliberate drop suffices.

### IN-06: `List`/`Dict`/`Optional` typing imports could use builtin generics for consistency

**File:** `itrader/strategy_handler/storage/base.py:11`, `in_memory_storage.py:12`, `storage_factory.py:11`
**Issue:** The new storage modules use `typing.List` / `typing.Dict` / `typing.Optional` while
the surrounding modern modules (`config.py`, `ids.py`, `base.py` strategy) use builtin
generics (`list[...]`, `dict[...]`, `X | None`). Purely stylistic and consistent with the
sibling `order_handler/storage/` modules they intentionally mirror, so no change is required —
flagged only for consistency awareness.
**Fix:** Optional: align with the modern `list[...]` / `X | None` style if the codebase is
standardizing on it.

---

_Reviewed: 2026-06-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
