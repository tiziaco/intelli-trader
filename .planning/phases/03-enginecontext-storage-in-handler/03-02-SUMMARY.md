---
phase: 03-enginecontext-storage-in-handler
plan: 02
subsystem: trading_system
tags: [refactor, signal-store, compose, backtest-oracle, inertness, mypy, D-03]

# Dependency graph
requires:
  - phase: 03-enginecontext-storage-in-handler
    provides: "SqlEngine rename + unified sql_engine vocabulary (03-01); SignalStore owner seam left untouched for this plan"
provides:
  - "Engine holder (compose.py) with no redundant signal_store field"
  - "BacktestTradingSystem with no signal_store ctor param / _signal_store attribute / factory arg"
  - "get_signal_records()/get_signal_store() read through engine.strategies_handler.signal_store (handler-owned store, D-03)"
affects: [phase-04, live-trading, compose, trading_system]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read handler-owned persistence store through its owning handler (order_handler.storage convention) instead of re-surfacing it on the composition holder"

key-files:
  created: []
  modified:
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_trading_system.py

key-decisions:
  - "D-03: collapse the duplicate signal_store surfaces; accessors reach the store through the owning handler, NOT via a new @property (explicitly prohibited)"

patterns-established:
  - "Behavior-preservation guaranteed structurally: engine.strategies_handler.signal_store is the SAME instance previously copied onto the holder, so the accessors return an identical object and the oracle stays byte-exact"

requirements-completed: [CTX-04]

coverage:
  - id: D1
    description: "Engine dataclass and BacktestTradingSystem no longer surface a redundant signal_store (no field, no ctor param, no _signal_store attribute, no factory arg); no @property added"
    requirement: "CTX-04"
    verification:
      - kind: other
        ref: "grep: no 'signal_store: SignalStore' field, no return-arg, orphaned import removed, no ctor param, no _signal_store attribute, no factory arg"
        status: pass
      - kind: other
        ref: "poetry run mypy itrader -> Success: no issues found in 237 source files"
        status: pass
    human_judgment: false
  - id: D2
    description: "Accessors repointed to engine.strategies_handler.signal_store, returning the identical store instance (behavior-preserving); owner seam untouched"
    requirement: "CTX-04"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (3 passed, 134/46189.87730727451 byte-exact; get_signal_records()/get_signal_store() assertions green)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (2 passed)"
        status: pass
      - kind: other
        ref: "git diff --stat itrader/strategy_handler/strategies_handler.py -> no changes (owner untouched)"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-09
status: complete
---

# Phase 3 Plan 02: D-03 signal_store Surface Collapse Summary

**Removed the redundant `signal_store` plumbing that duplicated the handler-owned store on two composition holders (the `Engine` dataclass field and the `BacktestTradingSystem` ctor-param/`_signal_store` attribute) and repointed the public accessors to read `self.engine.strategies_handler.signal_store` directly — behavior-preserving (oracle byte-exact, inertness green, mypy --strict clean), with NO `signal_store` `@property` introduced.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-07-09T15:26:03Z
- **Completed:** 2026-07-09T15:27:49Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- `compose.py`: dropped the `signal_store: SignalStore` field from the `Engine` dataclass, removed the `signal_store=strategies_handler.signal_store` line from `return Engine(...)`, and removed the now-orphaned `from itrader.strategy_handler.storage import SignalStore` import. Trimmed the wiring comment so it no longer claims the store is read back onto the holder — it now documents that the accessors reach the store through the owning handler (D-03).
- `backtest_trading_system.py`: removed the `signal_store: Optional[SignalStore] = None` ctor param (and its docstring mention), removed both `self._signal_store = ...` assignments (factory-mode + legacy-mode), and dropped the `signal_store=engine.signal_store` arg from the `build_backtest_system` factory return.
- Repointed `get_signal_records()` → `self.engine.strategies_handler.signal_store.get_all()` and `get_signal_store()` → `self.engine.strategies_handler.signal_store` (kept the `-> SignalStore` return annotation, so the `SignalStore` import stays).
- No `signal_store` `@property` added (D-03 prohibition upheld). The SignalStore owner (`strategies_handler.py`) and its `signal_store=` test-override seam were left byte-untouched.

## Task Commits

1. **Task 1: Collapse redundant signal_store surfaces; repoint accessors through the handler (D-03)** - `a78c91f5` (refactor)

## Files Created/Modified
- `itrader/trading_system/compose.py` - removed the `Engine.signal_store` field, the return-arg, and the orphaned `SignalStore` import; adjusted the signal-store wiring comment
- `itrader/trading_system/backtest_trading_system.py` - removed the `signal_store` ctor param, both `_signal_store` assignments, and the factory arg; repointed both accessors through `engine.strategies_handler.signal_store`

## Decisions Made
- Kept the `SignalStore` import in `backtest_trading_system.py` (still used by the `get_signal_store() -> SignalStore` return annotation) while removing the now-orphaned import from `compose.py` (its only referent was the deleted field).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All four per-PLAN gates passed on the first run:
1. `poetry run mypy itrader` → Success: no issues found in 237 source files.
2. `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (134 / `46189.87730727451` byte-exact).
3. `poetry run pytest tests/integration/test_okx_inertness.py -q` → 2 passed.
4. `git diff --stat itrader/strategy_handler/strategies_handler.py` → no changes (owner + override seam untouched).

Note: `grep '_signal_store'` still matches the `get_signal_store` method name (substring), but the `self._signal_store` attribute is fully removed — the acceptance criterion (attribute gone) is satisfied.

## Next Phase Readiness
- Phase 3 (both waves) is complete: CTX-04 rename (03-01) + D-03 signal_store collapse (03-02) both landed behavior-preserving.
- The facade now exposes no persistence store as a re-surfaced holder copy — Phase 4 live wiring can rely on the handler-owned store convention throughout.
- No blockers. Per the ROADMAP note, whether Phase 3 folds into P2/P4 is a roadmap-structure question deferred to phase close.

## Self-Check: PASSED

- `itrader/trading_system/compose.py` - FOUND (modified, committed in a78c91f5)
- `itrader/trading_system/backtest_trading_system.py` - FOUND (modified, committed in a78c91f5)
- Commit `a78c91f5` - FOUND in git log

---
*Phase: 03-enginecontext-storage-in-handler*
*Completed: 2026-07-09*
