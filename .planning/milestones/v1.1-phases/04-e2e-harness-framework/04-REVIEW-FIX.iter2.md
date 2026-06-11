---
phase: 04-e2e-harness-framework
fixed_at: 2026-06-09T00:00:00Z
review_path: .planning/phases/04-e2e-harness-framework/04-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-06-09
**Source review:** .planning/phases/04-e2e-harness-framework/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (0 critical, 4 warning, 5 info; fix_scope = all)
- Fixed: 9
- Skipped: 0

All fixes were verified against the canary E2E scenario test
(`tests/e2e/smoke/single_market_buy/test_scenario.py`) and the byte-exact oracle
gate (`tests/integration/test_backtest_oracle.py`) — both remained green after
every change, confirming no frozen golden value was altered.

## Fixed Issues

### WR-01: "Unique module name per leaf" invariant is false; references an unused `sys.modules` mechanism

**Files modified:** `tests/e2e/conftest.py`
**Commit:** cd1e44d
**Applied fix:** Derived the in-process module name from the FULL leaf path
relative to `tests/e2e/` (`"_".join(rel.parts)`) instead of just the leaf
folder name, so same-named leaves in different parents
(`smoke/single_market_buy` vs a future `regression/single_market_buy`) get
distinct names. Added the missing `import sys` and `sys.modules[module_name] =
module` registration BEFORE `exec_module`, so the advertised
collision-prevention mechanism is now actually engaged. Updated the module
docstring + inline comments to match the real behavior.

### WR-02: `attach_slippage.decision_close` emits `NaN` for a fill on the first store bar

**Files modified:** `itrader/reporting/summary.py`
**Commit:** 1f54322
**Applied fix:** `decision_close` now returns a diff-stable `0.0` (documented as
"no overnight gap measurable") instead of `float("nan")` when `position <= 0`
(fill at/before the first store bar), so the harness's exact, no-tolerance diff
can compare the column for first-bar fills. Verified no current golden fills on
the first bar (all `position > 0`), so no frozen value changed — canary + oracle
remain byte-exact.

### WR-03: `decision_close` is only correct when fill timestamps coincide exactly with store-index bars

**Files modified:** `itrader/reporting/summary.py`
**Commit:** 7e3c58c
**Applied fix:** Chose the "fail loud" option from the review — added
`assert fill_time in index` (after the first-bar early-return) so a fill
timestamp drawn from a different grid (e.g. a resampled run timeframe) raises a
clear error instead of silently mis-attributing slippage to the wrong bar via
`position - 1`. Documented the contract ("fill timestamps must be drawn from the
same grid as `closes`"). Ran the full oracle integration test (134 real trades)
to confirm every real fill timestamp lies exactly on the store-index grid — the
assertion holds and does not break the byte-exact gate.

### WR-04: Summary diff is asymmetric — spurious extra top-level keys never caught

**Files modified:** `tests/e2e/conftest.py`
**Commit:** c1fb555
**Applied fix:** Added a scalar key-set equality assertion in `_diff_summary`
before the key-by-key loop (`fresh_scalar == gold_scalar`, both excluding
`metrics`), so an additive drift (a regressed `build_summary` emitting an extra
top-level key) now fails the no-tolerance lock instead of being silently ignored.

### IN-01: Orphan `tests/e2e/data/` directory with `.gitkeep` referenced nowhere

**Files modified:** `tests/e2e/data/.gitkeep` (removed)
**Commit:** 191e85a
**Applied fix:** Removed the dead `tests/e2e/data/.gitkeep` (and the now-empty
directory). No code under `tests/`, `itrader/`, or `scripts/` referenced it, and
the canary keeps its `bars.csv` inside its own leaf — removing it avoids implying
a convention authors should follow. (Committed via `git commit` on the staged
deletion: the `gsd-sdk commit` helper cannot stage a path that no longer exists.)

### IN-02: `--freeze` writes goldens for EVERY collected e2e scenario

**Files modified:** `tests/e2e/conftest.py`
**Commit:** b7997a9
**Applied fix:** The `run_scenario` fixture now mechanically enforces the
"freeze ONE scenario at a time" discipline: under `--freeze` it inspects
`request.session.items` and `pytest.fail`s when more than one test is selected,
instructing the developer to combine `--freeze` with a `-k`/path selector.
Verified single-scenario freeze still works and a multi-test session is refused
without touching any golden.

### IN-03: `IndexError` on an empty-portfolio spec instead of a clear harness error

**Files modified:** `tests/e2e/conftest.py`
**Commit:** a637c27
**Applied fix:** Added `assert spec.portfolios, "scenario spec must declare at
least one portfolio"` in `_build_and_run` before the `portfolio_ids[0]` index,
matching the explanatory-failure style used elsewhere (`_load_spec`).

### IN-04: Canary VERIFY note does not derive the frozen `slippage_entry`/`slippage_exit` columns

**Files modified:** `tests/e2e/smoke/single_market_buy/scenario.py`
**Commit:** 07588d5
**Applied fix:** Added the one-line hand-derivation of both slippage columns to
the VERIFY block (entry = bar2 open 120 − bar1 close 114 = 6.0; exit = bar4 open
140 − bar3 close 134 = 6.0), and added the slippage columns to the list of
load-bearing hand-checked facts. Values confirmed against `golden/trades.csv`
(6.0 / 6.0). Docstring-only change.

### IN-05: `open()` calls for golden/summary serialization omit explicit `encoding`

**Files modified:** `scripts/run_backtest.py`, `tests/e2e/conftest.py`
**Commit:** 0e796dc
**Applied fix:** Passed `encoding="utf-8"` to all three `open()` calls that
read/write the committed `summary.json` golden (one in `run_backtest.py`, the
freeze-write and diff-read in `conftest.py`), removing the platform-default
encoding dependency that would silently diverge on a future non-ASCII
ticker/name.

---

_Fixed: 2026-06-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
