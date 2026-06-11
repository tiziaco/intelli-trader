---
phase: 04-type-modeling
plan: 02
subsystem: api
tags: [enums, pydantic, mypy, assert_never, newtype, type-modeling]

# Dependency graph
requires:
  - phase: 03-hot-path-performance
    provides: byte-exact golden oracle (134 trades / final_equity 46189.87730727451) as the gate this plan must hold
provides:
  - ErrorSeverity class-based string enum replacing the comment-as-enum on ErrorEvent (D-05)
  - enum-member fee/slippage dispatch with assert_never exhaustiveness in SimulatedExchange (D-08)
  - PortfolioConfig.rebalance_frequency closed-vocabulary boundary validation (D-09)
  - PortfolioConfig.portfolio_id false-affordance removal (D-10/D-11)
  - portfolio/events/validators entity-id NewType retypes (D-12, user_id:int carve-out D-13)
affects: [04-type-modeling subsequent plans, naming-encapsulation, order-manager-decomposition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Enum-member dispatch closing with typing.assert_never so mypy proves exhaustiveness (no runtime warning fallthrough)"
    - "Pydantic v2 Literal-typed field for closed-vocabulary boundary validation"
    - "core/ids NewType annotations on handler/event id parameters (annotation-only, runtime-identical)"

key-files:
  created:
    - itrader/core/enums/severity.py
    - .planning/phases/04-type-modeling/deferred-items.md
  modified:
    - itrader/core/enums/__init__.py
    - itrader/events_handler/events/error.py
    - itrader/events_handler/full_event_handler.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/trading_system/live_trading_system.py
    - itrader/config/portfolio.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/validators.py
    - tests/unit/core/test_enums.py
    - tests/unit/events/test_error_flow.py
    - tests/unit/events/test_event_immutability.py

key-decisions:
  - "FeeModelType.TIERED has no backing model class; with assert_never exhaustiveness it now raises NotImplementedError loudly instead of silently mis-pricing to ZeroFeeModel"
  - "rebalance_frequency vocabulary fixed as Literal[daily/weekly/monthly/quarterly/yearly] (daily/monthly already in presets; standard rebalance cadence superset)"
  - "Two ErrorEvent characterization tests updated to the ErrorSeverity enum contract (D-05 follow-on, test-only)"

patterns-established:
  - "Severity-to-logger map keyed on ErrorSeverity members, default-to-error fallthrough preserved"
  - "assert_never enum-dispatch template (matching sizing_resolver) applied in the execution layer"

requirements-completed: [TYPE-02, TYPE-03]

# Metrics
duration: ~25min
completed: 2026-06-11
---

# Phase 4 Plan 02: Config/Events/Execution Boundary Hardening Summary

**ErrorSeverity class-based enum + enum-member fee/slippage dispatch with assert_never + rebalance_frequency closed-vocab validation + portfolio_id removal + portfolio/events/validators id NewType retypes — all oracle-byte-exact, mypy --strict clean, e2e 58/58.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-11
- **Tasks:** 3
- **Files modified:** 11 (1 new enum module + 1 deferred-items note + 9 edited)

## Accomplishments

- **D-05:** New `core/enums/severity.py` `ErrorSeverity(Enum)` (ERROR/CRITICAL/WARNING, explicit uppercase string values, case-insensitive `_missing_` raising a clear f-string `ValueError`) — re-exported from the `core/enums` barrel, typing `ErrorEvent.severity` (default `ErrorSeverity.ERROR`), and keying the `full_event_handler` severity-to-logger map on members. The `live_trading_system` construction site updated to `ErrorSeverity.ERROR`.
- **D-08:** Both `SimulatedExchange._init_fee_model` / `_init_slippage_model` now dispatch on `FeeModelType` / `SlippageModelType` members via `is`, closing with `assert_never` so mypy proves exhaustiveness; the per-branch `is not None` Decimal-default expressions and T-07-06 comments preserved verbatim.
- **D-09:** `PortfolioConfig.rebalance_frequency` is now `Literal["daily","weekly","monthly","quarterly","yearly"]` — out-of-vocab strings raise a pydantic `ValidationError` at the boundary.
- **D-10/D-11:** `PortfolioConfig.portfolio_id` false affordance deleted (no construction site passed it; `extra="forbid"` now rejects it loudly).
- **D-12:** `portfolio_handler` (get/delete/update/get_portfolio_config) `portfolio_id` retyped `Any -> PortfolioId`; `PortfolioErrorEvent.portfolio_id` `Any | None -> PortfolioId | None`; `validators` `transaction_id` `Optional[int] -> Optional[TransactionId]`. `user_id: int` carve-out (D-13) left unchanged.
- **D-03:** `tests/unit/core/test_enums.py` extended with ErrorSeverity coverage (member `.value`s, case-insensitive parse, clear-error `ValueError`).

## Task Commits

1. **Task 1: Add ErrorSeverity enum + rewire severity consumer (D-05)** - `39b91dc` (feat)
2. **Task 2: Enum-member fee/slippage dispatch with assert_never (D-08)** - `ff966f9` (refactor)
3. **Task 3: rebalance_frequency validation, portfolio_id removal, id NewTypes + D-03 tests (D-09/D-10/D-11/D-12/D-03)** - `7f05547` (feat)

## Files Created/Modified

- `itrader/core/enums/severity.py` (new) - `ErrorSeverity` class-based string enum + case-insensitive `_missing_`
- `itrader/core/enums/__init__.py` - re-export ErrorSeverity in a grouped block + `__all__`
- `itrader/events_handler/events/error.py` - `severity: ErrorSeverity`; `PortfolioErrorEvent.portfolio_id: PortfolioId | None`
- `itrader/events_handler/full_event_handler.py` - severity-to-logger map keyed on ErrorSeverity members
- `itrader/execution_handler/exchanges/simulated.py` - enum-member fee/slippage dispatch with assert_never
- `itrader/trading_system/live_trading_system.py` - ErrorEvent construction uses `ErrorSeverity.ERROR`
- `itrader/config/portfolio.py` - Literal rebalance_frequency; portfolio_id removed
- `itrader/portfolio_handler/portfolio_handler.py` - 4 portfolio_id params Any->PortfolioId
- `itrader/portfolio_handler/validators.py` - transaction_id Optional[int]->Optional[TransactionId]
- `tests/unit/core/test_enums.py` - D-03 ErrorSeverity coverage
- `tests/unit/events/test_error_flow.py`, `tests/unit/events/test_event_immutability.py` - updated to ErrorSeverity contract

## Decisions Made

- **FeeModelType.TIERED:** No `TieredFeeModel` class exists; it previously fell through the silent `else` to `ZeroFeeModel`. With member dispatch + `assert_never`, TIERED is handled explicitly and raises `NotImplementedError` loudly rather than silently mis-pricing. Oracle never selects it (runs ZeroFeeModel).
- **rebalance_frequency vocabulary:** Chosen as `daily/weekly/monthly/quarterly/yearly` — `daily`/`monthly` already appear in presets; this is the standard rebalance-cadence superset. The boundary is `auto_rebalance=False` on the golden path, so the field is oracle-dark.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated two ErrorEvent characterization tests to the ErrorSeverity enum contract**
- **Found during:** Task 3 (verification re-run of the events unit suite)
- **Issue:** `tests/unit/events/test_error_flow.py::test_error_event_severity_maps_to_warning_level` constructed `ErrorEvent(..., severity="WARNING")` (string) and `tests/unit/events/test_event_immutability.py::test_error_event_is_concrete_and_instantiable` asserted `event.severity == "ERROR"`. After D-05 the severity-to-logger map keys on `ErrorSeverity` members, so a bare string `"WARNING"` no longer matches (falls through to `logger.error`) and the `== "ERROR"` assertion fails against the enum member. These are the D-05 change's direct, intended downstream test updates.
- **Fix:** Imported `ErrorSeverity` in both files; construct with `ErrorSeverity.WARNING`; assert `severity is ErrorSeverity.ERROR`.
- **Files modified:** tests/unit/events/test_error_flow.py, tests/unit/events/test_event_immutability.py
- **Verification:** Both tests pass; full events/portfolio/execution/config/core unit suites 478 passed.
- **Committed in:** `7f05547` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — characterization-test contract update).
**Impact on plan:** The test updates are the mechanical downstream of the D-05 enum change, not scope creep. All plan tasks landed as written.

## Issues Encountered

- **Pre-existing, out-of-scope:** `tests/unit/portfolio/test_position_manager.py` fails at collection with `ImportError: cannot import name 'PositionEvent' from itrader.portfolio_handler.position.position_manager` — the enum lives in `core/enums/portfolio.py`. This file was last touched in an earlier phase, NOT by Plan 04-02, and reproduces on the 04-02 base commit. Logged to `.planning/phases/04-type-modeling/deferred-items.md`; left untouched (outside this plan's scope boundary).

## Verification Results

- `mypy --strict itrader`: clean (140 source files).
- `pytest tests/integration`: 12 passed — oracle byte-exact (134 trades / final_equity 46189.87730727451).
- `pytest tests/e2e -m e2e`: 58 passed.
- `pytest tests/unit/{core,events,portfolio,execution,config}` (excluding the pre-existing broken `test_position_manager.py`): 478 passed, incl. the 3 new D-03 ErrorSeverity tests.

## Threat Flags

None — the plan's threat register dispositions held. The single `mitigate` item (T-04-02-VAL, `PortfolioConfig.rebalance_frequency`) was positively hardened by the D-09 Literal boundary validation. No new network/auth/file/schema surface introduced (enum/annotation/validation changes only).

## Next Phase Readiness

- TYPE-02 / TYPE-03 boundary defects closed; remaining Phase 4 type-modeling plans (order-domain id retypes, dataclass freezing, BaseStrategyConfig relocation) are unblocked.
- No blockers introduced. Pre-existing `test_position_manager.py` collection error tracked for a later hygiene pass.

## Self-Check: PASSED

- Created files exist: `itrader/core/enums/severity.py`, `04-02-SUMMARY.md`, `deferred-items.md`.
- Task commits exist: `39b91dc`, `ff966f9`, `7f05547` + metadata `3515a12`.
- STATE.md / ROADMAP.md untouched (orchestrator-owned).

---
*Phase: 04-type-modeling*
*Completed: 2026-06-11*
