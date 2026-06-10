---
phase: 07-cost-sizing-sltp-scenarios
reviewed: 2026-06-10T12:38:30Z
depth: standard
iteration: 2
files_reviewed: 11
files_reviewed_list:
  - itrader/execution_handler/exchanges/simulated.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/cost/percent_fee/scenario.py
  - tests/e2e/cost/percent_fee/test_scenario.py
  - tests/e2e/cost/combined_roundtrip/scenario.py
  - tests/e2e/cost/linear_slippage/scenario.py
  - tests/e2e/sizing/risk_percent/scenario.py
  - tests/e2e/sizing/over_cash_reject/scenario.py
  - tests/e2e/sltp/from_fill_held/scenario.py
  - tests/e2e/sltp/from_decision_sl_hit/scenario.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 7: Code Review Report (Iteration 2)

**Reviewed:** 2026-06-10T12:38:30Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** clean

## Summary

Re-review of Phase 7 after the prior iteration's five findings (WR-01, WR-02,
WR-03, IN-01, IN-02) were fixed. This pass verifies each fix is correct and
complete, and adversarially checks that the WR-02 signature widening
(`LinearSlippageModel` / `FixedSlippageModel` `__init__` to `float | Decimal`)
introduced no new defect. **All five findings are resolved and no new issues were
introduced.**

### Verification of prior findings

- **WR-01 (combined_roundtrip cost-compounding comment) — RESOLVED.** Fixed in
  commit `0d790a4` (the lower exclusive bound of the stated fix range, hence not in
  the `0d790a4..ae95466` log). The module-level comment at
  `combined_roundtrip/scenario.py:106-110` now correctly states the fee is charged
  on the BASE (un-slipped) notional and "the two costs do NOT compound," matching
  `simulated.py::_emit_fill` (commission computed on `price` at line 203-205 BEFORE
  `executed_price = price * slippage_factor` at line 213) and the frozen golden
  `commission=285.00`. The previously-contradicting sentence is gone.

- **WR-02 (Decimal→float→Decimal round-trip in fee/slippage init) — RESOLVED and
  verified safe.** `simulated.py` now passes the configured `Decimal` through
  unchanged for percent fee, maker/taker, linear, and fixed slippage; the `float()`
  casts are dropped and the `is not None` defaults are now `Decimal("...")`
  literals. The receiving models' `__init__` signatures widened to `float | Decimal`
  with matching docstrings. I confirmed:
  - **mypy --strict clean** on all three changed production files (`Success: no
    issues found in 3 source files`).
  - **The remaining `float()` casts in the model bodies are correct, not
    round-trips.** `LinearSlippageModel` (`base_pct = float(self.base_slippage_pct)`)
    and `FixedSlippageModel` (`jitter_pct = float(self.slippage_pct)`) coerce to
    float ONLY to feed `random.Random.uniform()` — the seeded-RNG float seam (D-11)
    is itself a float domain; the result re-enters Decimal once via `to_money(noise)`.
    This is the same seam that already existed; no money value is float-round-tripped.
    The non-random fixed path uses `to_money(self.slippage_pct)` directly with no
    float cast, so a configured `Decimal("2")` stays exact.
  - **`validate_inputs` is unaffected** — it validates quantity/price/side/order_type
    only, never the rate params, so the widened rate types cannot trip it.
  - **Defaults stay `float` literals** (`0.01`, `0.00001`, `0.1`) consistent with the
    `float | Decimal` annotation.
  - **15 slippage/fee/execution unit + integration tests pass**, including
    `test_slippage_models.py` (15) and the BTCUSD oracle (3) — oracle-dark holds.

- **WR-03 (commission merge key non-uniqueness) — RESOLVED.** `conftest.py:344-347`
  now passes `validate="one_to_one"` to the commission merge. This is the correct
  pandas guard: a non-unique `(entry_date, exit_date, side)` key on EITHER side now
  raises `MergeError` (hard, diagnosable) instead of silently many-to-many
  duplicating trade rows. Adversarial check of the comment's parenthetical claim that
  "the parallel `attach_slippage` path shares the same key assumption":
  `reporting/summary.py::attach_slippage` does NOT merge on that key — it uses a
  row-wise `.apply()` keyed on each trade's fill times — so it is not vulnerable to
  the many-to-many duplication and correctly needs no equivalent guard. The comment's
  side-note is imprecise but the fix targets the only actual merge; nothing was left
  inconsistent.

- **IN-01 (VERIFY tables omit golden columns) — RESOLVED.**
  `over_cash_reject/scenario.py:57-60` and `from_fill_held/scenario.py:72-75` now
  carry an explicit note that the illustrative table abbreviates and the real golden
  also pins the leading `ticker` and trailing deterministic `time` identity column
  per `ORDER_SNAPSHOT_COLUMNS`.

- **IN-02 (drift-prone engine line citations) — RESOLVED.**
  `over_cash_reject/scenario.py` now anchors the cash-reservation rejection path to
  the stable D-15 decision tag and the `OrderManager` admission gate description
  rather than the fragile `order_manager.py:393-414` line range.

### Regression gates (all green)

- `mypy --strict` on the three changed production files: clean.
- `tests/e2e/` full suite: 30 passed.
- slippage / fee / execution / oracle scope: 141 passed (incl. oracle 3/3,
  `test_slippage_models.py` 15/15) — the BTCUSD numerical oracle is unchanged,
  confirming the production fix is behavior-preserving for the golden run.

No BLOCKER- or WARNING-class defects remain, and the iteration-1 findings are all
correctly and completely resolved. No new issues introduced by the WR-02 signature
widening.

---

_Reviewed: 2026-06-10T12:38:30Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (iteration 2)_
