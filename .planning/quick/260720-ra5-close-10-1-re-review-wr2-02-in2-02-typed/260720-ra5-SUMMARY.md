---
phase: quick-260720-ra5
plan: 01
status: complete
requirements: [WR2-02, IN2-02]
subsystem: strategy_handler / core.exceptions
tags: [exceptions, rehydrate, admission, D-19, quarantine]
duration: ~35m
completed: 2026-07-20
key-files:
  created: []
  modified:
    - itrader/core/exceptions/strategy.py
    - itrader/core/exceptions/__init__.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/lifecycle/manager.py
    - itrader/strategy_handler/registry/rehydrate.py
    - tests/unit/core/test_exceptions.py
    - tests/unit/strategy/test_rehydrate.py
    - tests/unit/strategy/test_strategy_command_verbs.py
    - tests/unit/strategy/test_reconfigure_atomic.py
decisions:
  - "StrategyValidationError parented on StrategyAdmissionError only (NOT the house ValidationError) — the wrap carries a message string, not structured fields."
  - "Fixed at the SOURCE (type the residue) rather than widening _QUARANTINABLE — widening would let a programming-bug ValueError silently quarantine a row, collapsing D-19 arm separability."
  - "Clause order (StrategyAdmissionError guard first) chosen over an isinstance test inside one clause — it is the no-double-wrap enforcement."
---

# Quick Task 260720-ra5: Close 10.1 Re-Review WR2-02 / IN2-02 Summary

Typed the bare-`ValueError` residue escaping strategy construction as
`StrategyValidationError` under `StrategyAdmissionError`, which closed both findings as
consequences: the three admission sites dropped their subsumed `ValueError` member (IN2-02)
and `_QUARANTINABLE` became correct as written with zero widening (WR2-02).

## What Changed

| Artifact | Change |
|----------|--------|
| `core/exceptions/strategy.py` | New `StrategyValidationError(StrategyAdmissionError)`, no `__init__` override, plain-message construction inherited through `ITraderError` |
| `core/exceptions/__init__.py` | Exported + added to `__all__` |
| `strategy_handler/base.py` | Both `_apply_params` + `validate()` spans wrapped (in `Strategy.__init__` and `Strategy.reconfigure`), guard clause first |
| `lifecycle/manager.py` | All three admission tuples narrowed to `except StrategyAdmissionError as exc:`; comments rewritten |
| `registry/rehydrate.py` | `_QUARANTINABLE` tuple **byte-unchanged**; rationale comment rewritten to explain why no widening is needed |

## TDD Evidence — the RED traceback

The quarantine regression was written and run against unmodified code first. It failed for
exactly the required reason: the bare `ValueError` **escaped `rehydrate_strategies`** (the
boot dies), not a collection/import/fixture error.

```
itrader/strategy_handler/registry/rehydrate.py:330: in rehydrate_strategies
    strategy = build_strategy(rec, catalog=catalog, policy_registry=registry)
itrader/strategy_handler/registry/rehydrate.py:225: in build_strategy
    return cls(**params)
itrader/strategy_handler/base.py:211: in __init__
    self.validate()
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = stale_1h

    def validate(self) -> None:
>       raise ValueError("cross-field rule added after this row was written")
E       ValueError: cross-field rule added after this row was written

tests/unit/strategy/test_rehydrate.py:782: ValueError
FAILED test_bare_value_error_from_validate_quarantines_the_row_not_the_boot
```

After Task 2's wrap it went GREEN with no test edit: the row is quarantined, the healthy
sibling registers, one CRITICAL alert fires, and the call does not raise.

## Message Preservation — verified UNMODIFIED

`tests/unit/strategy/test_strategy.py:188` / `:347`
(`pytest.raises(ValueError, match="short_window must be < long_window")`, on the init and
reconfigure paths) **passed without any edit**, confirmed by `git status --short` reporting
the file clean throughout. `str(exc)` round-trips verbatim with no prefix or decoration.

## Oracle — byte-exact

`tests/integration/test_backtest_oracle.py` green (3 tests). Frozen golden re-confirmed:

- **Trades: 134** (`tests/golden/trades.csv` = 135 lines incl. header)
- **Final equity: `46189.8773072745`** (final row of `tests/golden/equity.csv`)

## Verification

| Gate | Result |
|------|--------|
| `poetry run mypy` | Success: no issues in **251** source files |
| `pytest tests/unit/strategy tests/unit/core/test_exceptions.py tests/unit/storage/test_strategy_registry_store.py` | **392 passed** |
| `pytest tests/integration/test_strategy_registry_restart.py test_backtest_oracle.py` | **9 passed** |
| Full sweep `pytest tests/unit tests/integration` | **2520 passed, 2 skipped** (pre-existing OKX credential skips) |
| `(StrategyAdmissionError, ValueError)` tuples remaining | **0** |
| `except StrategyAdmissionError as exc:` sites | **3** |
| Guard-clause sites in `base.py` | **2** |
| Space-led added lines in the three tab files | **0** |
| Tab-led added lines in the space files | **0** |
| `make test` used | **No** |

Note: mypy reports 251 files, not the plan's predicted 273. The plan's number was stale; the
gate is "clean", which it is.

## Protected Sites — confirmed untouched

- km2/CR-01 tier-2 `except Exception` guard in `_add_strategy_verb` — present, unchanged
- SHORT-01 `except ValueError` around `self._managed.add_strategy(strategy)` — unchanged
- WR2-01 malformed-`portfolio_id` gate from task `260720-qfs` — unchanged
- `RehydrateInfrastructureError(RuntimeError)` — parentage intact (D-19 separability)
- `_QUARANTINABLE` tuple body — byte-identical (verified by diff)

## Deviations from Plan

**1. [Rule 1 — Test-double fidelity] `test_apply_failure_after_persist_alerts_critical_and_db_holds_new`**

- **Found during:** Task 3, after narrowing the APPLY-site tuple
- **Issue:** The test monkeypatches `strategy.reconfigure` with a stub raising a raw
  `ValueError("simulated apply failure")` — a shape the real collaborator can no longer
  produce, since a validation refusal escaping `Strategy.reconfigure` is now typed. It
  false-failed against the narrowed catch.
- **Fix:** Realigned the double to raise `StrategyValidationError` (what the real path now
  raises), preserving the test's intent exactly. The production assertions — persist-then-apply
  ordering, DB holds NEW, live instance unmodified, CRITICAL alert — are unchanged.
- **Not a production regression:** verified by reading the double, not by weakening the test.
- **Files:** `tests/unit/strategy/test_reconfigure_atomic.py`
- **Commit:** `cdd46971`

**2. [Plan-checker warning — resolved, no false-fail]** The `grep -c "except StrategyAdmissionError:"`
gate was flagged as self-contradicting (a verbatim quote in the required comment would push the
count past 2). Resolved by **paraphrasing the clause in prose** in both comments rather than
quoting it. The gate returned exactly **2** with the decision-anchored comment fully intact —
no code was bent and no comment weakened.

**3. [Two test-authoring bugs, self-corrected before commit]** My first draft of the
no-double-wrap tests asserted `exc.message` (not an attribute — `ValidationError` stores
`field`/`value` and folds the message into the string) and used `EthBtcPairStrategy(timeframe="1h")`
to trigger `MissingParamError` (it does not). Corrected to `str(exc)` containment and
`EmptyStrategy(timeframe="1d", tickers=[...])` (which omits the required `sizing_policy`,
matching the existing `test_strategy_config.py` idiom). The tests, not the code, were wrong.

## Finding for the owner (NOT fixed — out of scope, Rule 4)

Narrowing the two **reconfigure** sites removes bare-`ValueError`-from-`init()` coverage
there. `_run_init()` sits outside the wrap by design, so a `my_strategies` class whose
`init()` raises a bare `ValueError` would now escape the TRIAL and APPLY catches.

This is a **pre-existing asymmetry, slightly widened**, not a new hole: only
`_add_strategy_verb` has a tier-2 `except Exception` guard, so *any* other exception type
from `init()` (`TypeError`, `ZeroDivisionError`, …) already escaped both reconfigure sites
before this change. Those sites were always admission-error guards, never construction
catch-alls.

Closing it means adding a tier-2 guard to `_reconfigure_strategy_verb` — a structural
decision (Rule 4) the plan explicitly scoped out. Flagging rather than silently expanding
scope. Worth a follow-up task if D-10 never-raise is meant to hold for reconfigure as
completely as it does for add.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `03fc3c86` | `test(ra5-01)`: `StrategyValidationError` + RED rehydrate quarantine regression |
| 2 | `ae987ce3` | `feat(ra5-02)`: wrap both construction spans, guard clause first |
| 3 | `cdd46971` | `refactor(ra5-03)`: narrow three admission tuples, rewrite `_QUARANTINABLE` rationale |

## Self-Check: PASSED

- `itrader/core/exceptions/strategy.py` — FOUND (`StrategyValidationError` present)
- `itrader/strategy_handler/base.py` — FOUND (2 guard-clause sites)
- `itrader/strategy_handler/lifecycle/manager.py` — FOUND (3 narrowed sites, 0 subsumed tuples)
- `itrader/strategy_handler/registry/rehydrate.py` — FOUND (tuple byte-unchanged)
- Commits `03fc3c86`, `ae987ce3`, `cdd46971` — all FOUND in `git log`
