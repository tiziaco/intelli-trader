---
phase: 05-strategy-interface-hardening-signal-storage
reviewed: 2026-06-09T19:25:00Z
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

# Phase 05: Code Review Report (Re-Review)

**Reviewed:** 2026-06-09T19:25:00Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

This is a re-review after fixes were applied to the prior review's 11 findings
(WR-01..05, IN-01..06). I verified each fix against the source AND against the
test suite + mypy, then ran a fresh adversarial pass.

**Fix verification — all 11 prior findings correctly resolved:**

- **WR-01** (subscribe/unsubscribe asymmetry) — FIXED. Both
  `subscribe_portfolio` and `unsubscribe_portfolio` are now membership-guarded
  and idempotent (`base.py:157-169`).
- **WR-02** (silent overwrite-on-collision) — FIXED. `InMemorySignalStore.add`
  now raises `ValueError` on a duplicate `signal_id`
  (`in_memory_storage.py:41-43`).
- **WR-03** (live signal store dropped on the floor) — FIXED. The live system
  retains `self._signal_store` and exposes `get_signal_records()` /
  `get_signal_store()` mirroring the backtest system
  (`live_trading_system.py:113, 455-470`).
- **WR-04** (`tuple` builtin shadow + dead pair branch) — FIXED. Loop variable
  renamed to `pair`/`sym` (`strategies_handler.py:180-183`).
- **WR-05** (live loop bypassed the publish-and-continue seam) — FIXED, and
  functionally verified: the live system now binds
  `event_handler._on_handler_error = self._publish_and_continue`
  (`live_trading_system.py:174`), so a handler failure during `_dispatch`
  enqueues an `ErrorEvent` and increments `errors_count` instead of going
  silent. I exercised this with a forced-raise handler and confirmed exactly one
  `ErrorEvent` (correct `error_type`/`error_message` via `sys.exc_info()`) is
  enqueued.
- **IN-01** (`str = None` type lie) — FIXED. Both annotations are now
  `Optional[str] = None` (`live_trading_system.py:206, 230`).
- **IN-02** (divergent deferred-backend exception) — FIXED.
  `SignalStorageFactory.create('live')` now raises `NotImplementedError`,
  aligned with `OrderStorageFactory` and the live system's `except
  NotImplementedError` fallback (`storage_factory.py:59-62`).
- **IN-03** (UUID not stringified in `to_dict`) — PARTIALLY FIXED — see WR-01
  below. `strategy_id` is now `str(...)`-serialized (`base.py:85`), but the same
  JSON-unsafe class re-enters through `subscribed_portfolios`.
- **IN-04** (`list[int]` vs UUID identity) — documented (`base.py:44-50`); the
  underlying type/runtime mismatch is the root cause of the new WR-01 below.
- **IN-05** (SMA_MACD exit-branch oddity) — correctly left unchanged
  (oracle-locked); confirmed `test_backtest_oracle.py` still passes byte-exact.
- **IN-06** (100-week magic sentinel) — FIXED. `min_timeframe` initializes to
  `None` and `add_strategy` computes the min defensively
  (`strategies_handler.py:44, 229-232`).

**Verification evidence:** 21 strategy unit tests pass, 5 strategy-related
integration tests pass, the golden `test_backtest_oracle.py` (3 cases) passes
byte-exact, and `mypy --strict` is clean over `itrader/strategy_handler`,
`itrader/core/ids.py`, and `itrader/outils/id_generator.py`.

**One NEW finding (WR-01 below):** the IN-03 JSON-safety fix is incomplete.
`to_dict()` still raises `TypeError: Object of type UUID is not JSON
serializable` on every real run path, because `subscribed_portfolios` holds
runtime `PortfolioId` UUIDs (the value `PortfolioHandler.add_portfolio` returns
and that `run_backtest.py` subscribes). IN-03 stringified `strategy_id` but left
the adjacent UUID-bearing field unstringified — the identical defect class IN-03
was opened to close.

The golden backtest path remains oracle-locked and byte-exact; this finding is a
serialization-edge robustness defect, not a correctness/oracle regression.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `to_dict()` is still JSON-unsafe — `subscribed_portfolios` holds runtime UUID `PortfolioId`s, re-introducing the exact `TypeError` IN-03 was opened to fix

**File:** `itrader/strategy_handler/base.py:79-99` (specifically line 87)
**Issue:** The prior IN-03 fix stringified `strategy_id` (`base.py:85`) to make
`json.dumps(strategy.to_dict())` succeed, but the method serializes
`subscribed_portfolios` raw:
```python
"subscribed_portfolios" : self.subscribed_portfolios,
```
`PortfolioHandler.add_portfolio` returns a `uuid.UUID` at runtime (confirmed:
`UUID('019e...')`), and every real run path subscribes that UUID —
`run_backtest.py:95` (`strategy.subscribe_portfolio(portfolio_id)`),
`test_reservation_inertness.py:94`, `test_universe_spans.py:163`,
`test_backtest_smoke.py:62`. So `subscribed_portfolios` is a `list[uuid.UUID]`
at runtime, and `json.dumps(strategy.to_dict())` raises:
```
TypeError: Object of type UUID is not JSON serializable
```
(reproduced directly). This is the SAME failure mode IN-03 fixed for
`strategy_id` — the fix closed one UUID field on a serialization-edge method
named `to_dict` while leaving the adjacent UUID-bearing field open. Any caller
that JSON-serializes the dict (the implied contract of a `to_dict`) crashes the
moment a real portfolio is subscribed. The `list[int]` annotation on
`subscribed_portfolios` (IN-04) is what masks this from mypy: the field is typed
int, so a reader believes it is JSON-safe, but it carries UUIDs at runtime.
**Fix:** Stringify the portfolio ids at the serialization edge, exactly as
IN-03 did for `strategy_id`:
```python
"subscribed_portfolios": [str(pid) for pid in self.subscribed_portfolios],
```
(Stringifying is safe for both int and UUID handles — `str(1) == "1"`,
`str(uuid) == "019e..."`.) Better still, resolve IN-04 at the same time so the
declared type stops lying about the runtime contract.

## Info

### IN-01: `_publish_and_continue` imports `sys` / `ErrorEvent` inside the method body on every handler failure

**File:** `itrader/trading_system/live_trading_system.py:187-188`
**Issue:** The live error-policy override does its imports inside the method:
```python
def _publish_and_continue(self, event, handler) -> None:
    import sys
    from itrader.events_handler.events import ErrorEvent
```
This is on the hot error path: a persistent per-event failure re-imports on
every invocation. The imports are correct and cheap (cached in `sys.modules`
after the first call), so this is a style/consistency nit, not a defect — the
module already imports `datetime` and `Decimal` at the top, and the
`ErrorEvent` runtime import is deliberately deferred elsewhere (the dispatcher
keeps the events package out of its import graph). Flagged only for awareness;
if the deferred-import rationale (avoid pulling pandas via the events package at
module load) applies here too, a top-of-method comment stating that would stop a
future reader from "cleaning it up" into a module-level import that breaks the
light-import contract.
**Fix:** Either hoist `import sys` to module scope (it is stdlib, no
side-effect concern) and add a one-line comment explaining why `ErrorEvent`
stays a deferred import, or leave as-is with that comment. No behavior change
required.

---

_Reviewed: 2026-06-09T19:25:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
