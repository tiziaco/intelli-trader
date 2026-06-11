---
phase: 06-order-matching-scenarios
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 33
files_reviewed_list:
  - itrader/reporting/orders.py
  - itrader/trading_system/backtest_trading_system.py
  - tests/e2e/conftest.py
  - tests/e2e/scenario_spec.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/matching/entries/market_next_open/scenario.py
  - tests/e2e/matching/entries/market_next_open/test_scenario.py
  - tests/e2e/matching/entries/limit_touch/scenario.py
  - tests/e2e/matching/entries/limit_touch/test_scenario.py
  - tests/e2e/matching/entries/limit_gap_through/scenario.py
  - tests/e2e/matching/entries/limit_gap_through/test_scenario.py
  - tests/e2e/matching/entries/stop_gap_down/scenario.py
  - tests/e2e/matching/entries/stop_gap_down/test_scenario.py
  - tests/e2e/matching/entries/stop_gap_up/scenario.py
  - tests/e2e/matching/entries/stop_gap_up/test_scenario.py
  - tests/e2e/matching/brackets/oco_lifecycle/scenario.py
  - tests/e2e/matching/brackets/oco_lifecycle/test_scenario.py
  - tests/e2e/matching/brackets/stop_beats_limit/scenario.py
  - tests/e2e/matching/brackets/stop_beats_limit/test_scenario.py
  - tests/e2e/matching/gaps/clean_through_stop/scenario.py
  - tests/e2e/matching/gaps/clean_through_stop/test_scenario.py
  - tests/e2e/matching/gaps/clean_through_limit/scenario.py
  - tests/e2e/matching/gaps/clean_through_limit/test_scenario.py
  - tests/e2e/matching/gaps/gap_past_both_legs/scenario.py
  - tests/e2e/matching/gaps/gap_past_both_legs/test_scenario.py
  - tests/e2e/matching/operator/cancel/scenario.py
  - tests/e2e/matching/operator/cancel/test_scenario.py
  - tests/e2e/matching/operator/modify_reprice/scenario.py
  - tests/e2e/matching/operator/modify_reprice/test_scenario.py
  - tests/e2e/matching/operator/modify_resize/scenario.py
  - tests/e2e/matching/operator/modify_resize/test_scenario.py
  - tests/e2e/matching/never_fill/scenario.py
  - tests/e2e/matching/never_fill/test_scenario.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: issues_found
---

# Phase 6: Code Review Report (Re-review)

**Reviewed:** 2026-06-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 33
**Status:** issues_found

## Summary

Re-review after the six prior findings (WR-01, WR-02, WR-03, IN-01, IN-02, IN-03)
were fixed across five commits (`1200cc0`..`443c3b7`). I verified each fix against
the live code, re-ran the full Phase 6 suite (14 e2e matching scenarios:
`14 passed in 0.30s`; broader reporting/orders/summary/e2e set: `58 passed`), and
ran `mypy --strict` over `itrader/reporting/` (`Success: no issues found in 6
source files`). I also adversarially traced the fixes for newly-introduced defects
(timezone-naive `tz_convert` crashes, sort-dtype drift, masked round-trip failures,
broken return contracts).

**All five substantive findings are genuinely resolved:**

- **WR-01 (silent operator no-op) — RESOLVED.** `_make_on_tick` now asserts a
  PENDING order exists, captures the `ok` boolean from `cancel_order`/`modify_order`,
  and `assert ok` hard-fails a failed round-trip. I confirmed both handler methods
  return `result.success` (a real `bool`, `order_handler.py:156,188`), so `assert ok`
  is a meaningful check, not a tautology. An `else: raise ValueError` now also guards
  an unknown `action.kind`.
- **WR-02 (sole-resting predicate) — RESOLVED.** `if len(resting) != 1:
  pytest.fail(...)` enforces the documented D-07 "exactly one PENDING order"
  contract before `resting[0]`.
- **WR-03 (Europe/Paris date coupling) — RESOLVED, and applied symmetrically.**
  Both producers now anchor the date key to UTC: `conftest._make_on_tick` uses
  `time_event.time.tz_convert("UTC").strftime(...)` and
  `scripted_emitter.generate_signal` uses `bars.index[-1].tz_convert("UTC")`. I
  verified the crash risk: `time_event.time` derives from `ping_grid` (built from
  `store.index(s)`, which `csv_store` returns `tz_convert(TIMEZONE)`-aware), and
  `bars.index` is the same tz-aware store index — so neither `tz_convert` call can
  hit a tz-naive `TypeError` on the backtest path. The fix is behavior-preserving for
  the frozen midnight-UTC goldens (Paris `+01:00` and UTC land on the same calendar
  day), confirmed by all 14 tests still passing without a re-freeze.
- **IN-01 (`_order_role` defaults non-STOP child to "TP") — RESOLVED.** Now maps
  STOP→SL, LIMIT→TP explicitly and `raise ValueError` on anything else, annotated
  `-> OrderRole` (`Literal["ENTRY","STANDALONE","SL","TP"]`). `mypy --strict` passes,
  confirming exhaustiveness. The `raise` lands in the test-harness `_assemble` path
  (not a handler), so it propagates loudly to fail a generating/comparing test rather
  than being swallowed.
- **IN-02 (`time` omitted from orders sort keys) — RESOLVED.** `_ORDERS_SORT_KEYS`
  now appends `"time"` as a trailing key. The sort runs on the round-tripped
  (CSV-string) frame on BOTH fresh and golden sides (`_diff` calls `_roundtrip`
  before `_diff_frame`), so the tiebreak compares like-typed strings deterministically.
- **IN-03 (stop_gap_down docstring drift) — PARTIALLY RESOLVED.** The primary defect
  (test docstring said "short entry", contradicting the LONG_ONLY scenario) is fixed
  and now reads "stop-loss exit leg of a long". The secondary half — hard-coded
  source line numbers (`strategies_handler.py:225`, `order_manager.py:641`) in the
  `scenario.py` comments — was NOT addressed; see IN-01 below (re-numbered).

No blockers, no warnings. The fixes introduced no regressions: I specifically ruled
out tz-naive crashes, sort-dtype drift, masked round-trip failures, and broken
return contracts. The single remaining item is a low-severity carryover.

## Info

### IN-01: Hard-coded source line-number references still rot in `stop_gap_down/scenario.py`

**File:** `tests/e2e/matching/entries/stop_gap_down/scenario.py:11,15,117`
**Issue:** The IN-03 fix corrected the *test* docstring but left the second half of
the original finding unaddressed: the `scenario.py` comments still cite hard-coded
source line numbers — `strategies_handler.py:225` (lines 11, 117) and
`order_manager.py:641` (line 15). These are positional references into files outside
this leaf; they silently rot as `strategies_handler.py`/`order_manager.py` change,
pointing future readers at the wrong line. The durable anchors in this codebase are
the decision tags (`D-`/`MATCH-`), per CLAUDE.md ("these tags are load-bearing
references to planning artifacts"). Low severity — comments only, no runtime impact,
and the same pattern recurs in sibling scenarios — but it is the one piece of the
prior IN-03 finding that remains open.
**Fix:** Drop the `:NNN` suffixes and reference the symbol/decision tag only, e.g.
"the LONG_ONLY guard in `strategies_handler.add_strategy`" and "the bracket assembler
in `order_manager` (D-15)", so the comment survives unrelated edits to those files.

---

_Reviewed: 2026-06-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
