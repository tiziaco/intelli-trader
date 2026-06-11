---
phase: 05-strategy-interface-hardening-signal-storage
plan: 02
subsystem: strategy
tags: [pydantic, enum, ordertype, strategy, refactor, byte-exact, golden-master]

# Dependency graph
requires:
  - phase: 05-01
    provides: "BaseStrategyConfig / SMA_MACDConfig / EmptyStrategyConfig pydantic contracts (HARD-01/HARD-02, D-01..D-06)"
provides:
  - "Strategy ABC collapsed to a single config-object constructor (D-01); self.config is the single source of truth"
  - "order_type is the OrderType enum end-to-end; the OrderType(strategy.order_type) boundary parse is removed (HARD-03 / D-04 / FL-04)"
  - "Framework warmup short-circuit in StrategiesHandler guarding on a dedicated strategy.warmup field (D-15)"
  - "__str__/__repr__ moved to the Strategy base (D-14)"
  - "SMA_MACD_strategy + empty_strategy relocated to itrader/strategy_handler/strategies/ (D-13)"
  - "All construction + import call sites migrated to the config contract"
affects: [05-03, phase-06-strategies, signal-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-object constructor: Strategy(name, config) where config is a frozen pydantic BaseStrategyConfig subclass"
    - "Dedicated warmup threshold (strategy.warmup) distinct from max_window fetch width; framework-enforced short-circuit"
    - "order_type as OrderType enum end-to-end (no stringly-typed seam)"

key-files:
  created:
    - itrader/strategy_handler/strategies/__init__.py
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/empty_strategy.py
  modified:
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/strategies_handler.py
    - scripts/run_backtest.py
    - tests/unit/strategy/test_strategy.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_reservation_inertness.py
    - tests/integration/test_universe_spans.py
    - tests/e2e/strategies/single_market_buy.py

key-decisions:
  - "D-15 conflict resolved (user-approved Option A): added a dedicated `warmup` field to the Strategy base instead of overloading `max_window`. SMA_MACD sets warmup=max_window=100; EmptyStrategy / SingleMarketBuy / count-based canaries keep warmup=0 with a wide max_window."
  - "SingleMarketBuy (e2e canary) external constructor signature kept as (timeframe, tickers, *, fire_on_bar, exit_on_bar); the config is built internally so the scenario call site is untouched and the frozen golden is preserved."

patterns-established:
  - "Strategy declares engine-facing settings via a frozen pydantic config; the base reads them onto the instance. Mutable runtime state (warmup/max_window/subscribed_portfolios) stays on the instance, never on the frozen config (RESEARCH Pitfall 2)."
  - "Warmup gating is a framework concern (handler short-circuit), not an in-strategy guard inside generate_signal (which stays pure pandas, D-12)."

requirements-completed: [HARD-03, HARD-04]

# Metrics
duration: ~35min
completed: 2026-06-09
---

# Phase 5 Plan 02: Strategy Interface Hardening Core Refactor Summary

**Collapsed the Strategy constructor to a single frozen-pydantic config object, made order_type an OrderType enum end-to-end, relocated the warmup guard into a framework short-circuit on a dedicated `warmup` field, moved `__str__`/`__repr__` to the base, and relocated the two reference strategies — all byte-exact against the SMA_MACD golden master (134 trades / 46189.87730727451).**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-09 (executor session)
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 11 (3 created, 8 modified)

## Accomplishments
- `base.py` `Strategy.__init__(self, name, config: BaseStrategyConfig)`: `self.config` is the single source of truth; engine-facing attrs read off the config; `order_type` is the `OrderType` enum; base `__str__`/`__repr__`.
- Added a dedicated `self.warmup: int = 0` field on the base (D-15 conflict resolution) distinct from `max_window` (fetch width).
- `strategies_handler.py`: framework warmup short-circuit `if len(data) < strategy.warmup: continue` before `generate_signal`; `order_type=strategy.order_type` direct enum emit; removed the now-unused `OrderType` import.
- Relocated `SMA_MACD_strategy.py` and `empty_strategy.py` into `itrader/strategy_handler/strategies/` with the config constructors; removed the in-strategy warmup guard and per-strategy dunders.
- Migrated every construction + import call site (run_backtest.py, 4 test modules + 1 e2e strategy) to the config contract.
- SMA_MACD golden re-runs byte-exact (HARD-04); SingleMarketBuy e2e canary keeps its frozen golden; HARD-03 `isinstance(signal.order_type, OrderType)` asserted.

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor base.py to config constructor + base __str__/__repr__** - `bc7720a` (refactor)
2. **Task 2: Relocate strategies + framework warmup short-circuit + enum emit** - `4acc083` (refactor)
3. **Task 3: Migrate all construction call sites to the config contract** - `921b0ed` (refactor)

_Task 3 was a tdd-typed task but a behavior-preserving migration; test updates and code migration landed as one atomic refactor commit. RED/GREEN gate not separately applicable (no new feature behavior added)._

## Files Created/Modified
- `itrader/strategy_handler/base.py` - config-object constructor; `self.config` source of truth; `order_type` enum; base `__str__`/`__repr__`; dedicated `warmup` field (D-15)
- `itrader/strategy_handler/strategies/__init__.py` - empty barrel for the relocated strategies package
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` - relocated; `SMA_MACDConfig` constructor; warmup guard + dunders removed; `generate_signal` math byte-for-byte unchanged
- `itrader/strategy_handler/strategies/empty_strategy.py` - relocated; `EmptyStrategyConfig` constructor; dunders removed
- `itrader/strategy_handler/strategies_handler.py` - framework warmup short-circuit on `strategy.warmup`; direct enum emit; dropped `OrderType` import
- `scripts/run_backtest.py` - construct `SMA_MACDConfig` then `SMA_MACD_strategy(config)`; import path updated
- `tests/unit/strategy/test_strategy.py` - `_sma_config()` helper; `_AlwaysBuyStrategy` config constructor; relocated too-short test to handler-level D-15 assertion; HARD-03 isinstance assertion
- `tests/integration/test_backtest_smoke.py` - config-object construction; import path updated
- `tests/integration/test_reservation_inertness.py` - config-object construction; import path updated
- `tests/integration/test_universe_spans.py` - `BuyEachTickerOnce` migrated to `BaseStrategyConfig` (deviation ripple)
- `tests/e2e/strategies/single_market_buy.py` - config-object adoption; `warmup=0` preserves the frozen e2e golden

## Decisions Made
- **D-15 conflict resolved (Rule 4, user-approved Option A):** A dedicated `warmup` field on the base, separate from `max_window`. SMA_MACD sets `warmup = max([long_window, 100]) = 100` (byte-identical to the removed `if len(bars) < self.max_window: return None`); EmptyStrategy / SingleMarketBuy / count-based canaries keep `warmup = 0` so a wide `max_window` (fetch width) does not gate their firing tick.
- Kept `SingleMarketBuy`'s external constructor signature, building the config internally, so the scenario call site and the frozen e2e golden are untouched.

## Deviations from Plan

### Authorized Deviation (Rule 4 — user-approved)

**1. [Rule 4 - Architectural, user-approved] Dedicated `warmup` field instead of `max_window` guard**
- **Found during:** Pre-execution (D-15 conflict surfaced by the orchestrator)
- **Issue:** The plan's `key_links` specified the framework short-circuit as `len(data) < strategy.max_window`. But `max_window` is overloaded: for SMA_MACD it equals the warmup threshold (100), while for count-based canaries (SingleMarketBuy `max_window=100`, BuyEachTickerOnce `max_window=1`) it is the *fetch width* and gating on it would skip the canary's firing tick and break the SingleMarketBuy frozen golden.
- **Fix:** Added a dedicated `self.warmup` field (default 0) to the base. The handler guards `if len(data) < strategy.warmup`. SMA_MACD sets `warmup = max([long_window, 100])` for byte-exact parity; canaries keep `warmup = 0`.
- **Files modified:** itrader/strategy_handler/base.py, itrader/strategy_handler/strategies/SMA_MACD_strategy.py, itrader/strategy_handler/strategies_handler.py, tests/e2e/strategies/single_market_buy.py
- **Verification:** Oracle byte-exact (134 / 46189.87730727451); e2e golden green; full suite 742 passed; mypy --strict clean.
- **Committed in:** `bc7720a` (warmup field), `4acc083` (handler guard + SMA), `921b0ed` (e2e)

### Auto-fixed Issues

**2. [Rule 3 - Blocking] Migrated BuyEachTickerOnce construction in test_universe_spans.py**
- **Found during:** Task 3 (full-suite verification)
- **Issue:** `tests/integration/test_universe_spans.py::BuyEachTickerOnce` (not listed in the plan's files) called the old kwargs `super().__init__(name, timeframe, tickers, sizing_policy=..., ...)`. The D-01 constructor reshape made this raise `TypeError: Strategy.__init__() got an unexpected keyword argument 'sizing_policy'`, failing the full suite.
- **Issue:** Directly caused by the Task 1 constructor change — a blocking ripple.
- **Fix:** Built a `BaseStrategyConfig` then `super().__init__("BuyEachTickerOnce", config)`; added the config import; documented `warmup=0` intent.
- **Files modified:** tests/integration/test_universe_spans.py
- **Verification:** test_universe_spans passes; full suite 742 passed.
- **Committed in:** `921b0ed` (Task 3 commit)

**3. [Rule 1 - Behavior relocation] Updated test_too_short_frame_returns_none to assert the handler short-circuit**
- **Found during:** Task 3 (unit verification)
- **Issue:** The test called `strategy.generate_signal(_TICKER, _short_frame())` and asserted `None`, relying on the in-strategy warmup guard that D-15 removed. Without the guard, the direct call hit the SMA math and raised `IndexError`.
- **Fix:** Renamed to `test_too_short_window_short_circuits_in_handler` and rewrote it to drive the real `StrategiesHandler` with a too-short stub window, asserting no SignalEvent is emitted (the relocated D-15 framework short-circuit). The behavioral intent ("too-short window yields no signal") is preserved at the correct architectural layer.
- **Files modified:** tests/unit/strategy/test_strategy.py
- **Verification:** test passes; full suite green.
- **Committed in:** `921b0ed` (Task 3 commit)

---

**Total deviations:** 1 authorized (Rule 4, user-approved) + 2 auto-fixed (1 blocking ripple, 1 behavior relocation).
**Impact on plan:** All changes necessary for correctness and for the user-approved D-15 resolution. No scope creep — every change is within the plan's stated goal of migrating the strategy contract and its call sites.

## Issues Encountered
- The oracle gate (`test_backtest_oracle.py`) invokes `scripts/run_backtest.py::main`, so the run_backtest.py construction had to be migrated during Task 2 (not deferred to Task 3) for the Task 2 byte-exact gate to pass. Both Task 2 and Task 3 list `scripts/run_backtest.py`; resolved by migrating the construction in Task 2 and the remaining test call sites in Task 3.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Strategy contract is now config-object + enum end-to-end; `warmup` is a first-class base field. Phase 6 strategy authors inherit a clean config-contract template (SingleMarketBuy already adopted).
- Plan 05-03 can build on the relocated `strategies/` package and the hardened typed interface.

## Self-Check: PASSED

- Created files verified on disk (strategies/__init__.py, SMA_MACD_strategy.py, empty_strategy.py, 05-02-SUMMARY.md).
- Old top-level SMA_MACD_strategy.py + empty_strategy.py confirmed removed (relocated).
- Task commits verified in git log: bc7720a, 4acc083, 921b0ed.

---
*Phase: 05-strategy-interface-hardening-signal-storage*
*Completed: 2026-06-09*
