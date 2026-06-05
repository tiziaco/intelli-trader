---
phase: 02-m2a-identity-money-determinism
plan: 05
subsystem: refactoring
tags: [abc, protocol, typing, mypy-strict, abstract-methods, conformance]

# Dependency graph
requires:
  - phase: 02-01
    provides: mypy --strict gate (make typecheck) + core/ids NewType aliases (StrategyId, ScreenerId)
provides:
  - 3 structural-seam bases converted to runtime_checkable Protocols (AbstractExchange, AbstractPriceHandler, AbstractPositionSizer)
  - 8 shared-impl/lifecycle bases converted to real ABCs (AbstractExecutionHandler, AbstractStatistics, Universe, Strategy, Screener, AbstractPortfolioHandler/AbstractPortfolio/AbstractPosition, SimulationEngine)
  - SimulatedExchange.configure conformance method (Pitfall 3, D-08)
  - Strategy.calculate_signal now @abstractmethod (real enforcement, #20)
  - screener screen_market self-ful signature fix
  - Strategy.strategy_id / Screener.id retyped to StrategyId / ScreenerId
affects: [02-06 (RNG injection into SimulatedExchange), 02-07 (mypy deferral burn-down), M5b universe-collapse, M5b reporting-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Protocol for swap-a-fake structural seams; ABC for shared-impl/lifecycle bases (D-07)"
    - "Minimal-conformance ABC: convert to real ABC but drop @abstractmethod on methods no concrete subclass implements yet (deep rework deferred)"

key-files:
  created: []
  modified:
    - itrader/execution_handler/exchanges/base.py
    - itrader/price_handler/base.py
    - itrader/strategy_handler/position_sizer/base.py
    - itrader/execution_handler/base.py
    - itrader/reporting/base.py
    - itrader/universe/universe.py
    - itrader/strategy_handler/base.py
    - itrader/screeners_handler/screeners/base.py
    - itrader/portfolio_handler/base.py
    - itrader/trading_system/simulation/base.py
    - itrader/execution_handler/exchanges/simulated.py
    - test/test_strategy/test_strategy.py

key-decisions:
  - "Protocol subclasses keep explicit inheritance (SimulatedExchange/PriceHandler/FixedPositionSizer) — valid and instantiable; Protocol bases are runtime_checkable"
  - "Minimal-conformance ABCs: Universe.get_assets and all AbstractStatistics methods left non-abstract because DynamicUniverse / StatisticsReporting / EngineLogger do not implement them (deep rework deferred to M5b #33 universe-collapse, #38 reporting-split)"
  - "Strategy.calculate_signal made @abstractmethod (both concrete strategies implement it); base test switched to a concrete _ConcreteStrategy subclass since the base is now non-instantiable"
  - "configure delegates to existing update_config and returns bool (False on unknown key) — conformance only, no RNG injection (that is Plan 06)"

patterns-established:
  - "Pattern A (PATTERNS.md): dead Py2 __metaclass__ = ABCMeta is a Py3 no-op; replace with class X(ABC)+@abstractmethod or @runtime_checkable class X(Protocol)"
  - "When real ABC enforcement would break a concrete subclass slated for deferred rework, keep the ABC but demote the unimplemented method to a regular NotImplementedError interface method (behavior-preserving)"

requirements-completed: [M2-04, M2-03]

# Metrics
duration: 22min
completed: 2026-06-04
---

# Phase 2 Plan 5: Dead-Metaclass ABC/Protocol Conversion Summary

**11 dead Py2 `__metaclass__ = ABCMeta` bases across 9 files converted to 3 runtime_checkable Protocols + 8 real ABCs, with SimulatedExchange.configure added for AbstractExchange conformance — enabling real abstract-method enforcement (#20) that was previously a no-op.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-04T19:48:00Z
- **Completed:** 2026-06-04T19:58:00Z
- **Tasks:** 3
- **Files modified:** 12 (11 plan-owned + 1 test fixup)

## Accomplishments
- All 11 dead-metaclass bases across the 9 owned files now use real `Protocol` or `ABC` constructs — no `__metaclass__ = ABCMeta` remains in any of the 9 (the only repo-wide remnant is `price_handler/exchange/base.py`, a different D-oanda-deferred `AbstractExchange`, out of scope).
- `AbstractExchange`/`AbstractPriceHandler`/`AbstractPositionSizer` are `@runtime_checkable` Protocols (structural swap-a-fake seams, D-07).
- The 8 shared-impl/lifecycle bases are real ABCs (D-07 + D-08b 2-class expansion).
- `SimulatedExchange.configure` added (Pitfall 3 — `update_config` existed but was not the Protocol method name); `SimulatedExchange` now structurally satisfies `AbstractExchange` (verified `isinstance` True; `configure`/`is_connected`/`validate_symbol` present).
- `Strategy.calculate_signal` now `@abstractmethod` — real enforcement (#20): the base can no longer be silently instantiated.
- `screen_market` self-less signature fixed to `(self, prices, event)`; `Strategy.strategy_id` and `Screener.id` retyped to `StrategyId` / `ScreenerId`.
- Full test suite green (288 passed).

## Task Commits

Each task was committed atomically:

1. **Task 1: Convert the 3 Protocol bases (D-07)** - `a6e90cd` (refactor)
2. **Task 2: Convert the 8 ABC bases + fix screener signature + retype base ids** - `2db39ff` (refactor)
3. **Task 3: SimulatedExchange minimal conformance to AbstractExchange (D-08)** - `d027d68` (feat)

## Files Created/Modified
- `itrader/execution_handler/exchanges/base.py` — AbstractExchange → runtime_checkable Protocol (dropped optional default-impl helpers; concrete SimulatedExchange retains them)
- `itrader/price_handler/base.py` — AbstractPriceHandler → Protocol; dropped obsolete `from __future__ import print_function`
- `itrader/strategy_handler/position_sizer/base.py` — AbstractPositionSizer → Protocol
- `itrader/execution_handler/base.py` — AbstractExecutionHandler → ABC
- `itrader/reporting/base.py` — AbstractStatistics → ABC (interface methods left non-abstract; reporting split deferred M5b #38)
- `itrader/universe/universe.py` — Universe → ABC (`get_assets` left non-abstract; universe collapse deferred M5b #33)
- `itrader/strategy_handler/base.py` — Strategy → ABC; `calculate_signal` made @abstractmethod; `strategy_id` retyped StrategyId
- `itrader/screeners_handler/screeners/base.py` — Screener → ABC; `screen_market` self-ful; `id` retyped ScreenerId
- `itrader/portfolio_handler/base.py` — AbstractPortfolioHandler/AbstractPortfolio/AbstractPosition → ABCs (D-08b)
- `itrader/trading_system/simulation/base.py` — SimulationEngine → ABC (D-08b)
- `itrader/execution_handler/exchanges/simulated.py` — added `configure(self, config) -> bool` delegating to `update_config`
- `test/test_strategy/test_strategy.py` — base Strategy now non-instantiable; test uses a minimal `_ConcreteStrategy` subclass

## Decisions Made
- **Protocol inheritance kept:** Concrete classes that previously inherited the now-Protocol bases (`SimulatedExchange`, `PriceHandler`, `FixedPositionSizer`) keep explicit inheritance. Inheriting from a `Protocol` is valid and produces a concrete, instantiable class — verified.
- **Minimal-conformance ABC carve-out:** For `Universe.get_assets` and the `AbstractStatistics` interface methods, the concrete subclasses on the run path (`DynamicUniverse`, `StatisticsReporting`, `EngineLogger`) do NOT implement them. Marking them `@abstractmethod` would raise `TypeError: Can't instantiate abstract class` and break the suite + run path. Per the plan's explicit "minimal conformance only — deep rework deferred" directive (M5b #33 universe collapse, M5b #38 reporting split), these methods were demoted to regular interface methods with their existing `NotImplementedError` bodies. The classes are still real ABCs (enforcement is live for any genuinely-abstract method) — exactly the conversion goal — without forcing deferred rework.
- **configure → update_config delegation:** Conformance-only, returns `True` on success / `False` on unknown key. No RNG injection (Plan 06).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] base `Strategy` test instantiated a now-abstract class**
- **Found during:** Task 2 (Strategy → ABC with abstract `calculate_signal`)
- **Issue:** `test/test_strategy/test_strategy.py` instantiated the base `Strategy` directly to exercise shared `buy`/`sell`/init behavior. Making `calculate_signal` abstract (the intended #20 enforcement) made the base non-instantiable → 3 test ERRORs.
- **Fix:** Added a minimal `_ConcreteStrategy(Strategy)` implementing `calculate_signal` in the test; `setUpClass` now uses it. `isinstance(self.strategy, Strategy)` assertion still holds.
- **Files modified:** test/test_strategy/test_strategy.py
- **Verification:** `poetry run pytest test/test_strategy -q` → 3 passed; full suite 288 passed.
- **Committed in:** 2db39ff (Task 2 commit)

**2. [Rule 3 - Blocking] minimal-conformance demotion of unimplemented abstract methods**
- **Found during:** Task 2 (Universe / AbstractStatistics → ABC)
- **Issue:** Keeping the existing `@abstractmethod` decorators on `Universe.get_assets` and the `AbstractStatistics` interface methods would break instantiation of `DynamicUniverse`, `StatisticsReporting`, and `EngineLogger` (verified: `Can't instantiate abstract class DynamicUniverse without ... 'get_assets'`).
- **Fix:** Converted the classes to real `ABC` but dropped `@abstractmethod` on the methods no concrete subclass implements yet, preserving their `NotImplementedError` bodies. Honors the plan's "deep rework deferred (M5b #33/#38)" boundary.
- **Files modified:** itrader/universe/universe.py, itrader/reporting/base.py
- **Verification:** `DynamicUniverse`/`StatisticsReporting`/`EngineLogger` `__abstractmethods__` empty; suite green.
- **Committed in:** 2db39ff (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking, directly caused by this plan's owned base changes)
**Impact on plan:** Both are necessary consequences of the conversion and stay within "minimal conformance only." No scope creep; deep rework remains deferred to M5b.

## Issues Encountered

- **mypy --strict error count rose 316 → 906** after the conversions. Investigated thoroughly: this is NOT a regression from the 3 commits. The owned base files are mypy-clean except `strategy_handler/base.py` (pre-existing untyped methods I did not modify, plus one surfaced latent mismatch — see below). The increase is dominated by `[no-untyped-def]` (342) and `[no-untyped-call]` (100) in unrelated modules (`my_strategies/*` (OUT), `logger.py`, `legacy_config.py`, `fee_model/*`, `order_handler/*`, …). Converting the bases made the previously-unresolvable type graph resolvable, so mypy now follows imports deeper and **unmasks pre-existing untyped-function debt** that the abstract-instantiation errors previously short-circuited. The mypy gate was already red at baseline and is explicitly **deferred to Plan 07** (STATE.md: "gate runs but errors deferred to Plan 07"). No action taken here beyond documenting.
- **`strategy_handler/base.py:81` `[arg-type]`:** retyping `self.strategy_id` to `StrategyId` surfaced an existing latent mismatch — `SignalEvent.strategy_id` is annotated `int` but has always received a UUID-typed id. Pre-existing (old code passed `uuid.UUID`); the explicit `StrategyId` type just makes it visible. Real fix (retyping the `SignalEvent.strategy_id` field) belongs to event-typing work, not this conformance plan. Noted for Plan 07.

## COVERAGE-INDEX §E — Owner Triage Item (NOT applied inline)

Per the plan ("note it for the SUMMARY; do not edit COVERAGE-INDEX inline unless the executor confirms the §E append convention") and the §E triage protocol (which requires owner approval, status ☐, before any row is added), the following is flagged for owner triage rather than written into COVERAGE-INDEX:

- **D-08b expansion (already user-approved per PROJECT.md / STATE.md):** the ABC conversion scope was expanded by 2 extra targets beyond the original 9-base set — `itrader/trading_system/simulation/base.py` (`SimulationEngine`) and the 2 additional classes in `itrader/portfolio_handler/base.py` (`AbstractPortfolio`, `AbstractPosition`, alongside `AbstractPortfolioHandler`). These have no concrete subclasses on the run path, so converting them to real ABCs is harmless interface hardening. Suggested §E framing: `DX2 | D-08b ABC-scope expansion (SimulationEngine + AbstractPortfolio/AbstractPosition) | refactor/typing | M2a | Phase 2 Plan 05 execution | ☑` — pending owner confirmation of the append convention.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Real ABC/Protocol enforcement is now live; Plan 06 can inject the seeded RNG into `SimulatedExchange` against a conforming `AbstractExchange`.
- Plan 07 (mypy deferral burn-down) should expect the unmasked `[no-untyped-def]`/`[no-untyped-call]` debt and the `SignalEvent.strategy_id` `int`→`StrategyId` field retype.
- Deep rework remains deferred: `calculate_signal` rich contract (M5b #24), universe collapse (M5b #33), reporting split (M5b #38), screener wiring (D-screener).

---
*Phase: 02-m2a-identity-money-determinism*
*Completed: 2026-06-04*

## Self-Check: PASSED

- FOUND: 02-05-SUMMARY.md
- FOUND commits: a6e90cd (Task 1), 2db39ff (Task 2), d027d68 (Task 3)
