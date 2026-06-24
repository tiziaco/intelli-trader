---
phase: 04-hot-path-discipline
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - itrader/config/settings.py
  - itrader/logger.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/strategy_handler/base.py
  - tests/unit/core/test_logging_gate.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/strategy/test_type_hints_equivalence.py
findings:
  critical: 0
  warning: 5
  info: 3
  total: 8
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

This phase introduces four changes: (1) a central `isEnabledFor` level-gate + module-level `_DISABLE_LOGS` kill-switch in `ITraderStructLogger`; (2) a `disable_logs: bool` field in `Settings`; (3) demotion of the admission-rejection log from `error` to `warning` behind a caller-side `_stdlib.isEnabledFor(WARNING)` guard; deletion of six hot-path `debug()` calls across `cash_manager.py`, `position_manager.py`, and `admission_manager.py`; and (4) memoization of `get_type_hints` per strategy class via `@functools.cache` in `strategy_handler/base.py`.

The phase is behavior-preserving: no money arithmetic is touched, no event routing changes, and the oracle's trade log is unaffected. Most changes are correct and well-reasoned. Five issues are identified below, none of which block the oracle, but two (WR-01, WR-02) could cause silent operational surprises under documented usage patterns.

---

## Warnings

### WR-01: `exception()` is not truly level-independent — misleading docstring and missing gate

**File:** `itrader/logger.py:281-287`

**Issue:** The `exception()` method documents itself as "an always-emit path: exceptions are logged regardless of level" and omits the `isEnabledFor(logging.ERROR)` guard present in `error()`. This is incorrect. `structlog.exception()` runs at `logging.ERROR` (40). When `ITRADER_LOG_LEVEL=CRITICAL` (50) the stdlib root logger's level filter silently drops ERROR-level records before they reach any handler — `exception()` calls return without emitting. A caller who reads the docstring and sets `LOG_LEVEL=CRITICAL` to quiet informational noise while expecting exceptions to always surface will get no exception traces. No current itrader code calls `self.logger.exception()` (all sites use `self.logger.error(..., exc_info=True)`) so this is a latent trap, but the test suite documents the public API and new callers may rely on the "always-emit" promise.

**Fix:** Either add the missing gate (making `exception()` consistent with `error()`):
```python
def exception(self, event: str | None = None, *args: Any, **kw: Any) -> None:
    if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.ERROR):
        return
    self.logger.exception(event, *args, **kw)
```
…and correct the docstring to drop the "regardless of level" claim; or, if the "always-emit" contract is intentional (exceptions must surface even at CRITICAL), fix `exception()` to emit at `CRITICAL` level so it is never filtered:
```python
self.logger.critical(event, *args, exc_info=True, **kw)
```
The first option (consistent gating) is simpler and matches the CONVENTIONS.md pattern `error` is used with `exc_info=True`.

---

### WR-02: `_stdlib` is a private attribute accessed from `admission_manager.py` — implicit coupling

**File:** `itrader/order_handler/admission/admission_manager.py:247`

**Issue:** The caller-side guard at line 247 reaches into the logger's private `_stdlib` attribute:
```python
if self.logger._stdlib.isEnabledFor(logging.WARNING):
```
`_stdlib` is not exported in `itrader/logger.py::__all__` and is prefixed with `_` — it is a private implementation detail of `ITraderStructLogger`. The comment explains why this is done (the central wrapper gate cannot pre-empt eager argument evaluation), but the access point creates invisible coupling: if `ITraderStructLogger` is refactored and `_stdlib` is renamed or replaced with a different gate mechanism, `admission_manager.py` fails with `AttributeError` at the single hottest admission site, with no static-analysis warning. This is the only production caller outside `logger.py` that accesses `_stdlib` directly.

**Fix:** Expose a public level-query method on `ITraderStructLogger` so callers do not reach into internals:
```python
# In ITraderStructLogger:
def is_enabled_for(self, level: int) -> bool:
    """Return True if the underlying stdlib logger would emit at ``level``."""
    return not _DISABLE_LOGS and self._stdlib.isEnabledFor(level)
```
Then `admission_manager.py` becomes:
```python
if self.logger.is_enabled_for(logging.WARNING):
    self.logger.warning(...)
```
This keeps the optimization while insulating the caller from the internal representation.

---

### WR-03: `@functools.cache` on `_declared_hints` retains strong references to ephemeral test classes

**File:** `itrader/strategy_handler/base.py:74-76`

**Issue:** `functools.cache` (an alias for `lru_cache(maxsize=None)`) holds a strong reference to every key-value pair it stores. The key is the concrete `Strategy` subclass itself. Inside the test suite, `tests/unit/strategy/test_type_hints_equivalence.py:67` defines `_OtherStrategy` inside a test function body, and `tests/unit/strategy/test_strategy.py:235` defines `_NestedDeclaredStrategy` inside another test function. Both call `_declared_hints(cls)` (directly or via `to_dict`/`_apply_params`), which caches the class object. These function-local classes are never garbage-collected for the lifetime of the process because `_declared_hints.cache` retains a live reference. In the current test suite the count is small (two extra classes), but the pattern is not bounded: any future test that constructs a `Strategy` subclass inside a function body adds to the cache permanently.

The production code comment says "the strategy-class count is bounded and annotations never change after import" — this assumption holds for production but breaks in the test surface.

**Fix:** Expose the cache's `cache_clear` method and call it from a test teardown fixture, or document the constraint explicitly and add a bounded-test-class convention check. A minimal fix for test isolation:
```python
# In tests/unit/strategy/test_type_hints_equivalence.py or conftest.py:
@pytest.fixture(autouse=True)
def clear_hints_cache():
    yield
    from itrader.strategy_handler.base import _declared_hints
    _declared_hints.cache_clear()
```
Alternatively, replace `@cache` with `@lru_cache(maxsize=64)` so old entries are evicted under memory pressure (though eviction is LRU, not time-based, and does not prevent the indefinite retention of the first N=64 entries).

---

### WR-04: `test_env_disable_logs_parses_truthy_values` uses raw `os.environ` mutation without `monkeypatch`

**File:** `tests/unit/core/test_logging_gate.py:189-207`

**Issue:** This test function directly writes to `os.environ` using `os.environ[...] = value` and `os.environ.pop()` within a `try/finally` block instead of using pytest's `monkeypatch` fixture. If the test raises an unexpected exception between the `os.environ` write and the `finally` clause executing (which `try/finally` does guarantee in CPython, but relying on it is the discouraged pattern in pytest), the cleanup still runs. The real risk is different: this test runs with `filterwarnings=["error"]` and if any warning is raised between the write and the `finally` (converting it to an exception), the `finally` still fires, but the test leaves no trace of which env-state was active when the warning was raised. More concretely: this is the ONLY test in the file that does NOT use `_reset_module_disable_flag` — if pytest runs this test while `_DISABLE_LOGS` is `True` from a prior test's monkeypatch that wasn't cleaned up, `_env_disable_logs()` will read `os.environ` correctly but the cached module-level `_DISABLE_LOGS` will not track it. The test is technically testing only the pure function, which is correct, but the `try/finally` idiom instead of `monkeypatch` makes it a fragile outlier among the other tests in the file.

**Fix:** Convert to `monkeypatch`:
```python
def test_env_disable_logs_parses_truthy_values(monkeypatch):
    for truthy in ("1", "true", "TRUE", "yes", "Yes"):
        monkeypatch.setenv("ITRADER_DISABLE_LOGS", truthy)
        assert _env_disable_logs() is True
    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("ITRADER_DISABLE_LOGS", falsy)
        assert _env_disable_logs() is False
    monkeypatch.delenv("ITRADER_DISABLE_LOGS", raising=False)
    assert _env_disable_logs() is False
```

---

### WR-05: `calculate_position_metrics` uses naive `datetime.now()` — breaks tz-awareness and determinism contract on the calling boundary

**File:** `itrader/portfolio_handler/position/position_manager.py:389`

**Issue:** Line 389 calls `datetime.now()` (no timezone argument) to compute the holding period for open positions:
```python
end_time = position.exit_date if position.exit_date else datetime.now()
```
This is a naive `datetime` with no timezone info. The rest of the system uses timezone-aware datetimes (`datetime.now(UTC)` or event-derived times). If `position.entry_date` is tz-aware (which it is — transactions carry the fill's event-derived tz-aware time), computing `end_time - position.entry_date` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. This method is not on the backtest hot path (it's in `calculate_position_metrics` which computes analytics) but it would crash at runtime if any caller requests metrics on an open position. The phase's diff did not introduce this line (it is pre-existing), but the reviewed file is in scope and this crash path is present.

**Fix:**
```python
from datetime import datetime, UTC
end_time = position.exit_date if position.exit_date else datetime.now(UTC)
```

---

## Info

### IN-01: `_COERCE` dict comment says "three engine fields" but only two entries exist

**File:** `itrader/strategy_handler/base.py:78` and `94`, `156`

**Issue:** Three separate comment lines (lines 78, 94, 156) say "the three engine fields" or "the three _COERCE enum fields" that coerce strings to enums. The actual `_COERCE` dict has exactly two entries: `"timeframe"` and `"direction"`. The third entry (`"order_type"`) was removed when D-01 retired the per-instance `order_type` class attribute. The stale "three" in the comments is internally inconsistent and will mislead a future reader who counts the entries.

**Fix:** Update all three comment occurrences from "three" to "two":
- Line 78: "ONLY these **two** engine fields coerce a str..."
- Line 94: "coercing the **two** enum fields"
- Line 156: "The **two** `_COERCE` enum fields coerce a str..."

---

### IN-02: Dead `operation` variable assignments in `CashManager.deposit`, `withdraw`, and `process_transaction_cash_flow`

**File:** `itrader/portfolio_handler/cash/cash_manager.py:179`, `239`, `300`

**Issue:** In `deposit()`, `withdraw()`, and `process_transaction_cash_flow()`, the return value of `self._create_operation()` is assigned to `operation` but never used:
```python
operation = self._create_operation(...)  # result never read
return True
```
The `apply_fill_cash_flow` and `accrue_borrow_interest` methods (the hot-path equivalents) correctly omit the assignment. The dead assignments are not harmful (the side effect — appending to `_storage` — still runs) but they are misleading: a reader may think `operation` is used somewhere below the assignment.

**Fix:** Replace the dead assignments with bare calls (or prepend `_` by convention):
```python
self._create_operation(...)   # side-effect: appended to _storage audit trail
```

---

### IN-03: `test_disable_logs_silences_every_level` does not exercise `exception()`

**File:** `tests/unit/core/test_logging_gate.py:172-186`

**Issue:** The test docstring says "ALL levels, including error/critical" but the test body only calls `debug`, `info`, `warning`, `error`, and `critical`. It does not call `exception()`, which has a separate code path (no `isEnabledFor` gate, only the `_DISABLE_LOGS` check). The D-08 contract should cover `exception()` too, since it is the only method with a different guard shape.

**Fix:** Add `log.exception("ex")` (or `log.exception(None)`) to the test body:
```python
log.exception("ex")
assert capture_records == []
```
Note: calling `exception()` outside an exception context may raise in some structlog configurations; using `log.exception(None)` is safer.

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
