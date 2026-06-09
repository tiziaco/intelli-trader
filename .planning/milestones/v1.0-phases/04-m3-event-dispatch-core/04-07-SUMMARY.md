---
phase: 04-m3-event-dispatch-core
plan: 07
subsystem: core-exceptions
tags: [exceptions, itrader-error, kb24, d-18, d-19, order-exceptions, data-exceptions]
requires:
  - "04-05 (big-bang cutover — order.py enum-typed OrderType, single events surface)"
provides:
  - "ITraderError root exception (ITradingSystemError renamed, D-19, zero stragglers, no back-compat alias)"
  - "core/exceptions/execution.py deleted (12 dead classes) — execution failure is data via FillEvent/ExecutionErrorCode; the enum stays"
  - "ConcurrencyError + PortfolioConcurrencyError deleted with zero dangling importers (transaction/position/cash managers, simulated.py, test_transaction_manager pruned)"
  - "KB24 fixed: PortfolioConfigurationError(config_key, config_value, reason) and PortfolioNotFoundError(portfolio_id) constructed to real signatures in portfolio_handler"
  - "core/exceptions/order.py: OrderError root + UnsizedSignalError (adopted at order.py unsized-signal raise)"
  - "core/exceptions/data.py: DataError root + MalformedDataError/MissingPriceDataError (adopted at data_provider CSV-path raises)"
  - "storage_factory config-shaped ValueErrors -> ConfigurationError (cross-cutting base)"
  - "tests/unit/core/test_exceptions.py: hierarchy + execution-module-deletion + KB24 regression lock (12 tests)"
affects: [04-08]
tech-stack:
  added: []
  patterns:
    - "domain-exception shape: args stored as attributes, human message via super().__init__ (portfolio.py shape copied to order.py/data.py)"
    - "verify-zero-importers-then-delete (D-13 precedent): prune dead import blocks in the same commit as the module delete"
    - "config-shaped errors use the cross-cutting ConfigurationError base, not a new domain class"
key-files:
  created:
    - itrader/core/exceptions/order.py
    - itrader/core/exceptions/data.py
    - tests/unit/core/test_exceptions.py
  modified:
    - itrader/core/exceptions/base.py
    - itrader/core/exceptions/portfolio.py
    - itrader/core/exceptions/__init__.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/transaction/transaction_manager.py
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/price_handler/data_provider.py
    - itrader/order_handler/storage/storage_factory.py
    - itrader/order_handler/order.py
    - tests/unit/portfolio/test_transaction_manager.py
    - tests/unit/order/test_order_storage.py
key-decisions:
  - "ConfigurationError.config_value widened Optional[str] -> Optional[object] so typed context stores the real value (KB24 fix passes the int max_portfolios; mypy strict stays clean)"
  - "order.py:171 unsized-signal ValueError migrated to UnsizedSignalError(OrderError) — the only live order-domain bare raise; gives OrderError a real raise site instead of an invented unused class (add_state_change returns False on invalid transitions, it never raises, so no InvalidOrderTransitionError)"
  - "storage_factory ValueErrors retyped to the existing cross-cutting ConfigurationError (they are config errors, per plan); the two test catchers updated to the new type with message substrings preserved"
  - "No InvalidOrderTransitionError / OrderNotFoundError classes created: zero raise sites exist (order_manager/order_handler/in_memory_storage contain no raises)"
metrics:
  duration: "~10 min"
  completed: "2026-06-05"
  tasks: 2
  files: 16
---

# Phase 4 Plan 07: Domain-Exception Hierarchy Summary

Exception hierarchy made real: root renamed to ITraderError with the dead execution/concurrency families deleted (zero dangling importers), KB24 wrong-arg portfolio constructions fixed to real signatures, and new order/data exception modules adopted at every in-scope bare-raise on the backtest path — locked by 12 hierarchy regression tests (423 passed, mypy strict clean, both oracle layers byte-exact with unmodified assertions).

## Tasks Completed

| Task | Name | Commit | Key Files |
| ---- | ---- | ------ | --------- |
| 1 | Rename root to ITraderError; delete execution.py + ConcurrencyError family; fix KB24 call sites | 1022d09 | itrader/core/exceptions/{base,portfolio,__init__}.py, portfolio_handler.py |
| 2 | New order/data exception modules + in-scope bare-raise replacement | e93b741 | itrader/core/exceptions/{order,data}.py, data_provider.py, storage_factory.py, tests/unit/core/test_exceptions.py |

## What Was Built

- **D-19 rename:** `ITradingSystemError` → `ITraderError` in base.py and every reference (portfolio.py, exceptions `__init__.py`); repo-wide grep returns zero stragglers; no back-compat alias.
- **D-18 deletes (verify-zero-importers-then-delete):** `git rm core/exceptions/execution.py` (12 classes, zero raise sites anywhere — execution failure is data by design via `FillEvent`/`ExecutionErrorCode`; the ENUM in core/enums/execution.py is untouched and still importable). `ConcurrencyError` (base.py) and `PortfolioConcurrencyError` (portfolio.py) deleted; verified-dead importers pruned in the same commits: simulated.py's 4-class import block (imported, never raised), the exceptions `__init__.py` execution block + `__all__` names, transaction_manager (import + docstring), position_manager, cash_manager, and test_transaction_manager's import.
- **KB24 fixes:** `portfolio_handler.py` now raises `PortfolioConfigurationError("max_portfolios", self.max_portfolios, "maximum portfolios limit reached")` (real `ConfigurationError(config_key, config_value, reason)` signature) and `PortfolioNotFoundError(portfolio_id)` (the class builds its message via `NotFoundError("Portfolio", portfolio_id)`); repo-wide grep confirmed these were the only two wrong-arg construction sites.
- **New modules (portfolio.py shape, 4-space):** `order.py` — `OrderError(ITraderError)` + `UnsizedSignalError(ticker)`; `data.py` — `DataError(ITraderError)` + `MalformedDataError(source, details)` + `MissingPriceDataError(source, reason)`. All store constructor args as attributes and build the human message via super. Re-exported from `__init__.py` in grouped, commented blocks.
- **In-scope raise replacement (verified inventory):** `data_provider.py` CSV-path raises → `MalformedDataError` (malformed header) and `MissingPriceDataError` (empty frame after window slice); `storage_factory.py` raises → `ConfigurationError` ("db_url" missing / unknown "environment"); `order.py` unsized-signal raise → `UnsizedSignalError`. KEPT: enum `_missing_` ValueErrors (house pattern, D-04), all NotImplementedError raises with real messages, and everything in deferred modules (CCXT/OANDA/live_streaming/sql_handler/trading_interface/postgresql_storage).
- **Catcher audit:** the only `except ValueError` in itrader/ (simulated.py:544, config-key path) is unrelated to any retyped raise; the two pytest catchers in test_order_storage.py updated to `ConfigurationError` with their message-substring assertions preserved.
- **Regression tests (12 new):** ITraderError is the root with `__bases__ == (Exception,)`; Portfolio/Order/DataError subclass it; legacy root name gone; importing `itrader.core.exceptions.execution` raises ModuleNotFoundError; ConcurrencyError family gone; KB24 signatures (`.portfolio_id` exposed, "Portfolio" in message; PortfolioConfigurationError("k", v, "r") constructs with typed attributes); new classes store args as attributes.

## Verification Results

- `grep -rn "ITradingSystemError\|ConcurrencyError" itrader/ tests/` → **0 matches**; `execution.py` does not exist; `ExecutionErrorCode` still importable from `itrader.core.enums`
- `grep "raise ValueError" data_provider.py storage_factory.py` → **0 matches**
- `tests/integration/test_backtest_oracle.py` — **passes UNMODIFIED**: behavioral + numerical oracle byte-exact (M3-04)
- Full suite: **423 passed** (Wave 6a baseline 411 + 12 new; zero tests lost)
- `poetry run mypy itrader` (the `make typecheck` command): Success — 134 files

## Deviations from Plan

### Minor in-scope clarifications

**1. [Rule 2 - Typed context] ConfigurationError.config_value annotation widened str → object**
- **Found during:** Task 1 (KB24 fix)
- **Issue:** the plan-mandated `PortfolioConfigurationError("max_portfolios", self.max_portfolios, ...)` passes an int where the annotation said `Optional[str]` — mypy strict would reject, and stringifying would lose the typed context the threat model (T-04-19) requires
- **Fix:** `config_value: Optional[object]` in base.py; the f-string message renders any value
- **Files modified:** itrader/core/exceptions/base.py
- **Commit:** 1022d09

**2. [Rule 2 - In-scope adoption] order.py unsized-signal ValueError migrated (file not in files_modified list)**
- **Found during:** Task 2 read_first review of order.py
- **Issue:** the plan's artifact requires `OrderError(ITraderError)` with children "covering the order-domain raises you migrate" and forbids unused classes; the only live order-domain bare raise is `order.py:171` ('Cannot create order from unsized signal'), which sits on the backtest signal→order path
- **Fix:** `UnsizedSignalError(OrderError)` raised there (message preserved verbatim); no test asserted the old ValueError and no catcher exists on the path — behavior-preserving, oracle byte-exact
- **Files modified:** itrader/order_handler/order.py
- **Commit:** e93b741

**3. [Rule 3 - Catcher update] test_order_storage.py catchers retyped**
- **Found during:** Task 2 (storage_factory retyping)
- **Issue:** two tests asserted `pytest.raises(ValueError)` against the factory raises being retyped to ConfigurationError (which does not subclass ValueError)
- **Fix:** catchers updated to `ConfigurationError`; the message-substring assertions ("Database URL is required", "Unknown environment: unknown") pass unmodified — mandated by the plan's "update catchers so behavior is preserved" instruction
- **Files modified:** tests/unit/order/test_order_storage.py
- **Commit:** e93b741

### Swallowed-None audit (#7 rule)

No bug-class silent-None returns found within the touched files: storage_factory has none; data_provider's `if price is None: continue` sits on the deferred SQL/CCXT download path (D-sql), out of scope.

## Known Stubs

None — no placeholder values or unwired data.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-19 mitigated (KB24 constructions to real signatures + regression tests); T-04-20 mitigated (domain exceptions with typed attributes, catcher sites audited before retyping, oracle byte-exact); T-04-21 audited (no bug-class silent-None returns in touched files).

## TDD Gate Compliance

Not applicable — plan type is `execute`, not `tdd`.

## Self-Check: PASSED

- `itrader/core/exceptions/base.py` contains `class ITraderError(Exception)`; no ConcurrencyError
- `itrader/core/exceptions/order.py` contains `class OrderError(ITraderError)`; `data.py` contains `class DataError(ITraderError)`
- `itrader/core/exceptions/execution.py` does not exist
- `tests/unit/core/test_exceptions.py` exists and contains `ITraderError`
- Commits exist: 1022d09, e93b741
- Deletion check: Task 1 commit deletes only `itrader/core/exceptions/execution.py` (intentional, D-18); Task 2 commit deletes nothing
- Oracle assertions untouched: `git diff` over `tests/integration/` empty across the plan
