---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 07
subsystem: database
tags: [storage-seam, abc, factory, portfolio, determinism, clock, decimal, uuid]

# Dependency graph
requires:
  - phase: 03-m2b (Plan 03-06)
    provides: portfolio_handler subdomain packages (position/ transaction/ cash/ metrics/) the seam routes through
  - phase: 02 (M2a)
    provides: injected Clock seam (core/clock.py), Decimal money at entity boundaries, native UUID ids
provides:
  - Unified PortfolioStateStorage ABC in portfolio_handler/base.py (mirrors order_handler/base.py::OrderStorage)
  - InMemoryPortfolioStateStorage backend + PortfolioStateStorageFactory (peer storage/ package)
  - All four portfolio managers route working state + append-only history through the injected seam
  - Event-derived order timestamps (add_state_change / add_fill / modify_order); no bare datetime.now() on that path
affects: [03-08 (test tree split moves the two test files), 03-09 (numeric oracle re-freeze), M4 (live persistence = backend swap)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pluggable state storage: one unified ABC + in-memory backend + environment factory, peer storage/ package (generalized order-storage pattern, D-09/D-10)"
    - "Event-derived transition timestamps threaded through a single validated add_state_change path (D-12)"

key-files:
  created:
    - itrader/portfolio_handler/storage/__init__.py
    - itrader/portfolio_handler/storage/in_memory_storage.py
    - itrader/portfolio_handler/storage/storage_factory.py
  modified:
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/portfolio_handler/transaction/transaction_manager.py
    - itrader/portfolio_handler/metrics/metrics_manager.py
    - itrader/order_handler/order.py
    - test/test_portfolio_handler/test_state_storage.py
    - test/test_order_handler/test_order_timestamps.py

key-decisions:
  - "PortfolioStateStorage ABC lives in portfolio_handler/base.py (not storage/base.py), mirroring order_handler/base.py::OrderStorage per RESEARCH drift correction"
  - "ONE unified seam covering all four managers' containers (D-09) — not four ABCs, not a storage class per manager folder"
  - "Cash *balance* (self._balance) stays on CashManager — it is intrinsic ledger state, not one of the four relocated containers (reserved cash is the working-state container)"
  - "Managers fall back to their own in-memory backend when no seam is injected (standalone/mock construction) so the seam is always present and mypy-clean"
  - "add_state_change gains a time param defaulting to the order's event time (self.time), never datetime.now(); modify_order routes through it via allow_same_status"

patterns-established:
  - "Pluggable state storage seam (ABC + in-memory backend + environment factory)"
  - "Event-derived timestamp threading through a single validated state-change path"

requirements-completed: [M2-08, M2-09]

# Metrics
duration: 18min
completed: 2026-06-05
---

# Phase 3 Plan 07: Portfolio Storage Seam + Order Timestamp Determinism Summary

**Unified PortfolioStateStorage seam (ABC + in-memory backend + factory) routes all four portfolio managers' state, and order timestamps are now event-derived through a single validated add_state_change path — both behavior-preserving (behavioral oracle byte-exact, numeric reference inert at 53229.685 / 134 trades).**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-05
- **Tasks:** 2 (both TDD: RED → GREEN)
- **Files modified:** 16 (3 created, 7 source modified, 6 test files touched)

## Accomplishments
- Built a single unified `PortfolioStateStorage(ABC)` in `portfolio_handler/base.py` covering all four managers' containers (open/closed positions, pending/history transactions, reserved cash + cash operations, metrics snapshots), with the working-state-vs-append-only-history split mirroring the order-storage backend.
- Added the peer `portfolio_handler/storage/` package: `InMemoryPortfolioStateStorage` backend + `PortfolioStateStorageFactory` (backtest/test → in-memory, live → NotImplementedError per D-sql, unknown → ValueError) + `__init__.py` re-exports — copied verbatim from the order-storage pattern.
- `Portfolio` injects one shared seam via the factory; `CashManager`, `PositionManager`, `TransactionManager`, `MetricsManager` stopped owning their `self._*` containers and route every read/write through the injected seam.
- Made order timestamps event-derived: `add_state_change(time=event_time)` stamps the recorded transition + `updated_at`/`filled_at`/`cancelled_at`/`expired_at`; `add_fill` threads `fill_time` into the recorded transition; `modify_order` routes through the single validated `add_state_change` path (duplicated direct append removed); no bare `datetime.now()` remains on that path.

## Task Commits

Each task was committed atomically (TDD: test → feat):

1. **Task 1: PortfolioStateStorage seam + route four managers** - `aa371a7` (test, RED) → `bd1e3f4` (feat, GREEN)
2. **Task 2: Event-derived order timestamps + validated modify path** - `cebbec7` (test, RED) → `9d0fecc` (feat, GREEN)

## Files Created/Modified
- `itrader/portfolio_handler/base.py` - Added `PortfolioStateStorage` ABC + `IdLike` (mirrors `OrderStorage`)
- `itrader/portfolio_handler/storage/__init__.py` - Re-exports ABC + in-memory backend + factory
- `itrader/portfolio_handler/storage/in_memory_storage.py` - `InMemoryPortfolioStateStorage` (the relocated containers)
- `itrader/portfolio_handler/storage/storage_factory.py` - `PortfolioStateStorageFactory.create`
- `itrader/portfolio_handler/portfolio.py` - Injects the shared seam in `_init_managers`
- `itrader/portfolio_handler/{cash,position,transaction,metrics}/*_manager.py` - Route state through `self._storage`
- `itrader/order_handler/order.py` - `add_state_change` time param; `add_fill` threads `fill_time`; `modify_order` routed
- `test/test_portfolio_handler/test_state_storage.py` - Real M2-08 seam tests (17, replacing the Wave-0 stub)
- `test/test_order_handler/test_order_timestamps.py` - Real M2-09 timestamp tests (7, replacing the skip stubs)
- `test/test_portfolio_handler/test_{position,cash,transaction,metrics}_manager.py` - Container assertions migrated to seam accessors

## Decisions Made
- ABC in `portfolio_handler/base.py` (mirroring `order_handler/base.py`, RESEARCH drift); ONE unified seam (D-09), not four ABCs nor per-manager storage classes.
- Cash *balance* stays on `CashManager` (intrinsic ledger state); only reserved cash + cash operations relocate to the seam.
- Managers obtain the seam defensively via `getattr(portfolio, "state_storage", None)` with an in-memory fallback, keeping standalone/mock construction working and `self._storage` typed `PortfolioStateStorage` for mypy --strict.
- `add_state_change` gained `allow_same_status` so `modify_order` (same status) can record through the validated path instead of the removed direct append.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated existing manager-test container assertions to seam accessors**
- **Found during:** Task 1 (routing the four managers through the seam)
- **Issue:** 18 existing tests in `test_{position,cash,transaction,metrics}_manager.py` asserted the managers owned private containers (`_positions`, `_cash_operations`, `_snapshots`, `_pending_transactions`, `_transaction_history`, `_reserved_cash`) — exactly the ownership the plan removes. They failed after routing.
- **Fix:** Re-pointed those assertions at the seam-routed accessors (`manager._storage.get_*()` / `set_reserved_cash`), preserving identical semantics (length / membership / mutation).
- **Files modified:** `test/test_portfolio_handler/test_{position,cash,transaction,metrics}_manager.py`
- **Verification:** `make test` 345 pass, identical behavior; new `test_*_has_no_owned_containers` assert the removal.
- **Committed in:** `bd1e3f4` (Task 1 commit)

**2. [Rule 2 - Missing Critical] Defensive seam fallback + explicit typing for managers**
- **Found during:** Task 1 (mypy --strict + mock-portfolio test construction)
- **Issue:** A bare `portfolio.state_storage` access broke manager unit tests that build a lightweight `MockPortfolio` without a seam, and `getattr(..., None)` produced an `Any | None` type that failed 61 mypy union-attr checks.
- **Fix:** Each manager resolves the seam via `getattr(portfolio, "state_storage", None)` with an in-memory `PortfolioStateStorageFactory.create("backtest")` fallback, annotated `self._storage: PortfolioStateStorage`.
- **Files modified:** the four `*_manager.py`
- **Verification:** `make typecheck` clean (148 files); manager unit tests green.
- **Committed in:** `bd1e3f4` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing-critical)
**Impact on plan:** Both necessary to keep the suite green and mypy --strict clean while moving the state-ownership boundary. No scope creep — strictly the state-ownership relocation the plan mandates.

## Issues Encountered
- The `no datetime.now()` AST guard initially false-positived on the docstring mention of `datetime.now()`. Resolved by parsing the function AST and asserting on actual `Call` nodes (and the absence of a `self.state_changes.append` call) rather than string-matching the source.

## Known Stubs
None. The live storage backend deliberately raises `NotImplementedError` (D-sql deferred, documented in PROJECT.md Out of Scope) — this is an intentional, owner-blessed deferral, not a stub blocking the plan goal.

## Verification Evidence
- `test/test_portfolio_handler/test_state_storage.py` — 17 pass; `test/test_order_handler/test_order_timestamps.py` — 7 pass.
- `make test` — 345 passed, 1 xfailed (numeric oracle, DEF-02-08-A deferred to 03-09). Collected 346 (was 326; +2 stub tests replaced by 24 real tests, net +20).
- `make typecheck` — `mypy --strict` clean, 148 source files.
- `test_oracle_behavioral_identity` — byte-exact green.
- Inertness: in-process backtest final_equity = 53229.68512642488, trade_count = 134 — byte-exact vs M2A-INERTNESS-REF.

## Next Phase Readiness
- Portfolio state is swap-ready: live persistence becomes a pure backend swap behind `PortfolioStateStorageFactory` (D-sql).
- Order audit + transaction timestamps are deterministic/event-derived (excluded from the oracle per D-12).
- 03-08 will move the two new test files into `tests/unit/...` during the type-split; 03-09 re-freezes the numeric oracle (this plan left it inert).

## Self-Check: PASSED
- All created files exist (storage package, base.py ABC, modified order.py, both test files).
- All task commits exist: `aa371a7`, `bd1e3f4`, `cebbec7`, `9d0fecc`.

---
*Phase: 03-m2b-config-types-storage-seam-oracle-re-freeze*
*Completed: 2026-06-05*
