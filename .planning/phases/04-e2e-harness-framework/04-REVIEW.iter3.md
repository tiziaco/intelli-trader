---
phase: 04-e2e-harness-framework
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - itrader/reporting/summary.py
  - scripts/run_backtest.py
  - tests/conftest.py
  - tests/e2e/__init__.py
  - tests/e2e/conftest.py
  - tests/e2e/smoke/__init__.py
  - tests/e2e/smoke/single_market_buy/__init__.py
  - tests/e2e/smoke/single_market_buy/scenario.py
  - tests/e2e/smoke/single_market_buy/test_scenario.py
  - tests/e2e/strategies/__init__.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/unit/core/test_enums.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-09
**Depth:** standard
**Status:** issues_found

## Summary

Re-review (auto-iteration 2) after fixes were applied for the 9 prior findings
(WR-01..WR-04, IN-01..IN-05). I verified each fix against the actual code and
re-ran the gating tests.

**All 9 prior findings are resolved and verified:**

- **WR-01** (unique module name + dead `sys.modules` claim) — `_load_spec`
  (`tests/e2e/conftest.py:125-137`) now derives the module name from the full
  leaf path relative to `tests/e2e/` (`"_".join(rel.parts)`) and actually
  registers `sys.modules[module_name] = module` before `exec_module`. The
  advertised collision-prevention is now engaged.
- **WR-02** (`NaN` from first-bar fill) — `decision_close`
  (`itrader/reporting/summary.py:73-74`) returns a diff-stable `0.0` when
  `position <= 0`, not `NaN`. The docstring now documents the chosen semantics.
- **WR-03** (silent mis-attribution off the store grid) — guarded with
  `assert fill_time in index` (`summary.py:75-79`); the contract is documented.
  The oracle byte-exact gate (`test_backtest_oracle.py`) still passes, so the
  real SMA_MACD run's fill timestamps satisfy the new invariant.
- **WR-04** (asymmetric summary diff) — `_diff_summary`
  (`tests/e2e/conftest.py:284-289`) now asserts scalar key-set equality, so a
  spurious extra top-level key fails just like a missing one.
- **IN-01** (orphan `tests/e2e/data/`) — directory removed (no longer on disk).
- **IN-02** (`--freeze` blind sweep) — the `run_scenario` fixture
  (`conftest.py:387-399`) now refuses `--freeze` when more than one test is
  selected in the session, mechanically enforcing the one-scenario discipline.
- **IN-03** (bare `IndexError`) — `_build_and_run` (`conftest.py:184`) now
  asserts `spec.portfolios` with an explanatory message before indexing.
- **IN-04** (undocumented slippage derivation) — the canary VERIFY note
  (`scenario.py:78-83`) now hand-derives both `slippage_entry`/`slippage_exit` = 6.0.
- **IN-05** (missing `encoding`) — all three `summary.json` `open()` calls now
  pass `encoding="utf-8"` (`run_backtest.py:116`, `conftest.py:311,367`).

Verification: `tests/e2e/smoke/single_market_buy`, `tests/unit/core/test_enums.py`,
and `tests/integration/test_backtest_oracle.py` all pass; the canary golden
reconciles with the VERIFY hand-derivation.

The fixes are correct and introduced no functional regressions. One new defect
was introduced by the WR-03 fix (an `assert` used as a production-path data
guard), plus one residual style nit it carries.

## Warnings

### WR-05: WR-03 grid-mismatch guard uses `assert` in production code — stripped under `python -O`

**File:** `itrader/reporting/summary.py:75-79`
**Issue:** The WR-03 fix guards the decision-bar invariant with a bare
`assert fill_time in index`. `itrader/reporting/summary.py` is production code
under `itrader/` (subject to `mypy --strict`) and is imported by the oracle
generator `scripts/run_backtest.py:37`, not test-only code. Python strips all
`assert` statements when run under `-O`/`-OO` (or with `PYTHONOPTIMIZE` set). If
the oracle or harness is ever invoked under optimization, the grid-mismatch
guard silently disappears and `decision_close` reverts to exactly the
silent-mis-attribution behavior WR-03 set out to prevent — a wrong slippage
number frozen into a golden with no loud failure. The project convention
(CLAUDE.md "Error Handling": "Raise typed exceptions, not bare `Exception` or
boolean returns") also points away from `assert` for a data-validation invariant
on the run path.
**Fix:** Replace the `assert` with an explicit raise that survives `-O`, e.g.:
```python
if fill_time not in index:
    raise ValueError(
        f"fill timestamp {fill_time!r} is not a store-index bar — "
        f"attach_slippage requires fill timestamps drawn from the same grid "
        f"as the close series"
    )
```
(`ValueError` matches the module's existing edge-case error style; a domain
`DataError` from `core/exceptions/data.py` is also acceptable.)

## Info

### IN-06: Review-artifact tag ("WR-03") leaked into a runtime error message

**File:** `itrader/reporting/summary.py:78`
**Issue:** The grid-mismatch guard's message ends with the parenthetical
`"(WR-03)"`, a code-review finding ID. Unlike the load-bearing decision tags
(`D-17`, `M5-04`) that CLAUDE.md mandates preserving as planning-artifact
references, `WR-03` is an ephemeral review iteration ID with no home in the
planning record — it will be meaningless to anyone hitting this error at
runtime. The same tag also appears in the inline comment (`summary.py:66, 71`).
**Fix:** Drop the `(WR-03)` suffix from the user-facing assertion/raise message
(keep or replace the inline comment tag with a real `D-`/decision reference if
one exists). The error text should describe the invariant, not cite the review
that added it.

---

_Reviewed: 2026-06-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
