---
phase: 05-m4-money-transaction-correctness
plan: 02
subsystem: portfolio
tags: [d-19, single-writer, lock-removal, thread-safety-theater, dependency-prune]
requires: []
provides:
  - "Lock-free portfolio domain with documented D-19 single-writer contract"
  - "Dependency set without readerwriterlock"
affects:
  - itrader/portfolio_handler/
  - itrader/execution_handler/exchanges/simulated.py
  - pyproject.toml
tech-stack:
  added: []
  removed: [readerwriterlock]
  patterns:
    - "D-19 single-writer: all portfolio state mutations on the engine thread; queue.Queue is the thread boundary"
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/portfolio_handler/transaction/transaction_manager.py
    - itrader/portfolio_handler/metrics/metrics_manager.py
    - itrader/execution_handler/exchanges/simulated.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - pyproject.toml
    - poetry.lock
decisions:
  - "D-19 executed: all 8 portfolio-state locks deleted; single-writer contract documented in Portfolio + PortfolioHandler docstrings"
  - "PortfolioHandler concurrency-limiting machinery (max_concurrent_operations, _active_operations, config shim property) deleted with _operations_lock — it existed only to gate the deleted lock; tests converted to D-19 absence regression locks"
  - "readerwriterlock physically reinstalled into the SHARED .venv after poetry remove (worktree-only mitigation): sibling wave-1 agents' base-commit code still imports it; pyproject.toml + poetry.lock (the durable artifacts) carry the removal"
metrics:
  duration: "10 min"
  completed: "2026-06-06"
  tasks: 2
  files: 11
---

# Phase 5 Plan 02: Delete Thread-Safety Theater (D-19) Summary

**One-liner:** Deleted all 8 portfolio-state locks (4 manager RLocks, Portfolio RLock, PortfolioHandler RWLockFair + operations Lock, SimulatedExchange config RLock) and replaced them with a documented D-19 single-writer contract; readerwriterlock dependency removed in its own bisectable commit — zero behavior change, oracle byte-exact.

## What Was Done

### Task 1: Delete all portfolio-state locks; document the single-writer contract (commit 65b65ad)

**Full list of deleted locks:**

| Lock | File | What replaced it |
|------|------|------------------|
| `CashManager._lock` (RLock, 13 with-blocks) | cash/cash_manager.py | D-19 one-line marker comment |
| `PositionManager._lock` (RLock, 13 with-blocks) | position/position_manager.py | D-19 one-line marker comment |
| `TransactionManager._lock` (RLock, 4 with-blocks) | transaction/transaction_manager.py | D-19 one-line marker comment |
| `MetricsManager._lock` (RLock, 7 with-blocks) | metrics/metrics_manager.py | D-19 one-line marker comment |
| `Portfolio._lock` (RLock, 15 with-blocks) | portfolio.py | D-19 contract in class docstring; "Thread safety" bullet replaced |
| `PortfolioHandler._portfolios_lock` (rwlock.RWLockFair, 9 gen_rlock/gen_wlock blocks) | portfolio_handler.py | D-19 contract in module + class docstring |
| `PortfolioHandler._operations_lock` (Lock) + `_active_operations` limiting | portfolio_handler.py | deleted with the concurrency-limit check |
| `SimulatedExchange._lock` (RLock, 2 with-blocks) | exchanges/simulated.py | D-19 contract note in class docstring |

All `with self._lock:` bodies were dedented exactly (mechanical transform, body code preserved). `import threading` removed from all 7 files (lock was the sole use in each). `from readerwriterlock import rwlock` removed.

**What survived in `_operation_context` (Pitfall 8):**
- `_generate_correlation_id()` — correlation IDs still generated per operation
- The `with self._operation_context(...) as correlation_id` shape at all 3 call sites (add_portfolio, delete_portfolio, on_fill) — unchanged
- `_publish_error_event` wiring in every except path — error-event publication fully intact (4 references)
- Only the concurrency limiting died: the `max_concurrent_operations` check, `_active_operations` set, `_operations_lock`, and the try/finally bookkeeping

**Explicitly untouched:** `LiveTradingSystem._status_lock` / `_stats_lock` (system lifecycle, 3 `_status_lock` references unchanged).

**Contract text** (in Portfolio and PortfolioHandler docstrings): "D-19 single-writer contract: ALL portfolio state mutations happen on the engine thread; queue.Queue is the thread boundary — other threads only put events. Composite reads are consistent because nothing mutates concurrently. Live cross-thread reads are a D-live design item."

### Task 2: Remove dead readerwriterlock dependency (commit 0ef95bf)

`poetry remove readerwriterlock` — pyproject.toml + poetry.lock updated in a lockfile-only commit (Phase 3/4 bisectability precedent). Zero matches for `readerwriterlock` in pyproject.toml, poetry.lock, itrader/, tests/.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Tests asserting deleted locks converted to D-19 regression locks**
- **Found during:** Task 1
- **Issue:** Three tests asserted the existence/behavior of deleted locks: `test_default_initialization` + `test_thread_safety_setup` (`hasattr(exchange, '_lock')`, lock acquisition) in test_simulated_exchange.py; `test_concurrent_operation_limits` (`config.limits.max_concurrent_operations`, `_active_operations`) in test_portfolio_handler.py; `test_update_config_thread_safety` exercised concurrent config updates against the deleted config lock.
- **Fix:** Converted to absence assertions that regression-lock D-19 (`assert not hasattr(...)` for `_lock`, `_active_operations`, `_operations_lock`, `_portfolios_lock`); concurrent-config test rewritten as sequential single-writer updates.
- **Files modified:** tests/unit/execution/exchanges/test_simulated_exchange.py, tests/unit/portfolio/test_portfolio_handler.py
- **Commit:** 65b65ad

**2. [Rule 2 - Missing critical] Concurrency-limiting config surface deleted with its machinery**
- **Found during:** Task 1
- **Issue:** `max_concurrent_operations`, the `config` shim property ("for test compatibility"), and the health-report `active_operations`/`max_concurrent_operations` keys existed only to serve the deleted `_active_operations` limiting — leaving them would be dead theater contradicting D-19.
- **Fix:** Deleted attribute, shim property, and health-report keys; `global_limits` now reports only `max_portfolios`. Orphaned `PortfolioHandlerError` import removed.
- **Files modified:** itrader/portfolio_handler/portfolio_handler.py
- **Commit:** 65b65ad

**3. [Rule 3 - Blocking, worktree-only] readerwriterlock reinstalled into shared .venv after poetry remove**
- **Found during:** Task 2
- **Issue:** This worktree shares `.venv` with the main repo and sibling wave-1 agents. `poetry remove` uninstalled the package from the shared env, which would break sibling agents whose base-commit code still imports `readerwriterlock` (portfolio_handler.py:11 at base).
- **Fix:** `poetry run pip install readerwriterlock==1.0.9` reinstalled the wheel WITHOUT touching pyproject.toml/poetry.lock. The durable artifacts (pyproject + lock, both committed) carry the removal; a fresh `poetry install --sync` on the merged main branch will drop the orphan wheel. `poetry install --sync` was correspondingly skipped (it would re-uninstall).
- **Files modified:** none (env-only)
- **Commit:** n/a

## Verification Results

- Unit suite: 422 passed (`tests/unit -q -x`)
- Full suite: 429 passed (`python -m pytest tests/ -q`, cwd-first import per worktree .pth pitfall)
- `mypy itrader`: Success, no issues in 134 source files
- Behavioral + numerical oracle: `tests/integration/test_backtest_oracle.py` 2 passed (byte-exact)
- `git diff --stat tests/golden/`: empty
- `grep -rn "RLock\|readerwriterlock\|rwlock" itrader/portfolio_handler/ itrader/execution_handler/exchanges/simulated.py`: 0 matches
- `grep -c "_status_lock" itrader/trading_system/live_trading_system.py`: 3 (unchanged)
- `grep -c "single-writer"`: portfolio.py 3, portfolio_handler.py 4
- `grep -c "_publish_error_event" portfolio_handler.py`: 4 (error publication survives)
- `poetry run python -c "import itrader"`: OK

## Known Stubs

None — pure deletion, no stubs introduced.

## Threat Flags

None — no new security surface; dependency removal only (matches threat register T-05-SC accept disposition).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 65b65ad | refactor(05-02): delete portfolio-state locks, document single-writer contract (D-19) |
| 2 | 0ef95bf | chore(05-02): remove dead readerwriterlock dependency |

## Self-Check: PASSED

- SUMMARY.md exists
- Commit 65b65ad exists
- Commit 0ef95bf exists
