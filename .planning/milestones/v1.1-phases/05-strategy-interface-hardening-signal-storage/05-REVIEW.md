---
phase: 05-strategy-interface-hardening-signal-storage
reviewed: 2026-06-09T20:40:00Z
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
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 05: Code Review Report (Re-Review #2)

**Reviewed:** 2026-06-09T20:40:00Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

This is the second re-review of Phase 05, focused on verifying the two fixes
applied since the prior review (WR-01 — incomplete IN-03 JSON-safety fix; IN-01 —
hot-path imports in `_publish_and_continue`) and running a fresh adversarial pass
over the full file set.

**Both applied fixes verified CORRECT:**

- **WR-01 (incomplete IN-03 fix) — FIXED and verified.** `to_dict()` now
  stringifies `subscribed_portfolios` at the serialization edge
  (`base.py:94`):
  ```python
  "subscribed_portfolios" : [str(pid) for pid in self.subscribed_portfolios],
  ```
  I reproduced the original failure path: built a real `SMA_MACD_strategy`,
  subscribed a `uuid.UUID` (the runtime shape `PortfolioHandler.add_portfolio`
  returns), and confirmed `json.dumps(strategy.to_dict())` now succeeds where it
  previously raised `TypeError: Object of type UUID is not JSON serializable`.
  The list-comprehension is correct for BOTH runtime handle types
  (`str(1) == "1"`, `str(uuid) == "019e..."`), so neither the int-keyed test
  path nor the UUID-keyed real path breaks.

- **IN-01 (hot-path imports) — FIXED and verified.** `sys` is now a module-level
  import (`live_trading_system.py:3`) and `ErrorEvent` is hoisted into the
  existing module-level events import (`live_trading_system.py:27`:
  `from itrader.events_handler.events import EventType, TimeEvent, OrderEvent, ErrorEvent`).
  The `_publish_and_continue` body no longer re-imports on every handler failure
  — the in-method `import sys` / `from ... import ErrorEvent` are gone, replaced
  by a comment documenting why the deferred-import rationale does not apply to
  this module (`live_trading_system.py:188-193`). The error event is still
  correctly constructed from `sys.exc_info()`.

**Verification evidence:** 21 strategy unit tests pass; the golden
`test_backtest_oracle.py` (3 cases) passes byte-exact; `mypy --strict` is clean
over `itrader/strategy_handler`, `itrader/core/ids.py`, and
`itrader/outils/id_generator.py` (36 source files, no issues).

**One STANDING finding carried forward (WR-01 below, was IN-04):** The WR-01
`to_dict` fix closes the JSON-serialization symptom, but the ROOT CAUSE remains:
`subscribe_portfolio`/`unsubscribe_portfolio` and the `subscribed_portfolios`
field are typed `int` (`base.py:51, 164, 171`) while every real run path passes
runtime `PortfolioId` UUIDs. This type-lie is invisible to the gate because
`scripts/run_backtest.py` — the only caller that passes the real UUID — is
OUTSIDE mypy's scope (`pyproject.toml` pins `files = ["itrader"]`). The prior
review classified this as Info (IN-04); on re-examination it warrants a Warning:
it is the documented seam that masked the WR-01 crash from both mypy and the
test suite, and any future code that trusts the declared `int` type (indexing,
arithmetic, an int-keyed lookup) will misbehave against the UUID runtime value.
The golden backtest path remains oracle-locked and byte-exact; this is a
type-contract defect, not a correctness/oracle regression.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `subscribed_portfolios` and the subscribe/unsubscribe signatures are typed `int` but carry runtime UUID `PortfolioId`s — a type-lie mypy cannot see (scripts/ is out of scope)

**File:** `itrader/strategy_handler/base.py:51, 164, 171` (and the unchecked call site `scripts/run_backtest.py:95`)
**Issue:** The strategy declares its portfolio handles as plain `int`:
```python
self.subscribed_portfolios: list[int] = []          # base.py:51
def subscribe_portfolio(self, portfolio_id: int) -> None:    # base.py:164
def unsubscribe_portfolio(self, portfolio_id: int) -> None:  # base.py:171
```
But `PortfolioHandler.add_portfolio` returns a `PortfolioId`
(`portfolio_handler.py:124` — `-> PortfolioId`, a `NewType` over `uuid.UUID`),
and the real run path subscribes that UUID directly:
```python
portfolio_id = system.portfolio_handler.add_portfolio(...)   # run_backtest.py:89 — UUID
strategy.subscribe_portfolio(portfolio_id)                   # run_backtest.py:95 — int arg gets a UUID
```
This was the exact mechanism that masked the prior WR-01/IN-03 JSON crash from
mypy: the field is typed `int`, so a reader (and mypy) believes
`subscribed_portfolios` is JSON-safe and int-shaped, while at runtime it is a
`list[uuid.UUID]`. The declared type lies about the runtime contract.

Crucially, mypy does NOT catch the mismatched call: `pyproject.toml` pins
`files = ["itrader"]`, so `scripts/run_backtest.py` — the only caller that
passes the real UUID — is never type-checked. The unit/integration tests all use
plain-int handles (`_PORTFOLIO_A = 1`, etc.), so they exercise the declared
`int` contract and never surface the UUID runtime path. The result: a field
whose declared type is structurally wrong on every production run, with zero gate
coverage.

The WR-01 `to_dict` fix is correct and SHOULD be kept (it defends the
serialization edge regardless of handle type), but it treats the symptom. The
type-lie is the underlying defect.

**Fix:** Type the seam to its real runtime contract so the declaration stops
lying and a future int-assuming consumer is caught at the gate:
```python
from itrader.core.ids import PortfolioId

self.subscribed_portfolios: list[PortfolioId] = []
def subscribe_portfolio(self, portfolio_id: PortfolioId) -> None: ...
def unsubscribe_portfolio(self, portfolio_id: PortfolioId) -> None: ...
```
If the strategy layer must genuinely support BOTH int (tests/canaries) and UUID
(real path) handles, type the union explicitly (`PortfolioId | int`) and document
the dual-handle contract — but `int` alone is provably wrong for the production
path. Separately, consider adding `scripts/` (or at least `run_backtest.py`) to
the mypy `files` list so cross-boundary call sites like this one are checked.

## Info

### IN-01: `min(min_timeframe, strategy.timeframe)` relies on `min_timeframe` being narrowed from `timedelta | None` — correct today, fragile under reorder

**File:** `itrader/strategy_handler/strategies_handler.py:229-232`
**Issue:** `add_strategy` computes the running minimum:
```python
if self.min_timeframe is None:
    self.min_timeframe = strategy.timeframe
else:
    self.min_timeframe = min(self.min_timeframe, strategy.timeframe)
```
This is correct — the `else` branch only runs when `min_timeframe` is non-None,
so `min(timedelta, timedelta)` is well-typed and mypy narrows it. It is flagged
only as a robustness note: the IN-06 change (initialize to `None` instead of a
100-week sentinel) means any future edit that moves the `min(...)` call out from
under the `is None` guard would feed `min()` a `None` and raise
`TypeError: '<' not supported between 'NoneType' and 'timedelta'` at runtime
(mypy would catch it inside `itrader/`, but the failure is a hard crash on the
wiring path). The current structure is sound; no change required. If anything,
a one-line assertion or comment that the `else` arm is the load-bearing
non-None branch would harden it against a careless refactor.
**Fix:** No change required. Optionally annotate the invariant:
```python
else:
    # min_timeframe is guaranteed non-None here (the None seed is handled above)
    self.min_timeframe = min(self.min_timeframe, strategy.timeframe)
```

---

_Reviewed: 2026-06-09T20:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
