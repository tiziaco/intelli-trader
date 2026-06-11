---
phase: 07-cost-sizing-sltp-scenarios
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/07-cost-sizing-sltp-scenarios/07-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 7: Code Review Fix Report

**Fixed at:** 2026-06-10
**Source review:** .planning/phases/07-cost-sizing-sltp-scenarios/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (WR-01, WR-02, WR-03, IN-01, IN-02 — fix_scope "all")
- Fixed: 5
- Skipped: 0

## Fixed Issues

### WR-01: combined_roundtrip module-level comment contradicts engine truth

**Files modified:** `tests/e2e/cost/combined_roundtrip/scenario.py`
**Commit:** 0d790a4
**Applied fix:** Replaced the false `_EXCHANGE` comment ("fee is charged on the slipped
notional, so both costs compound") with the correct statement matching the engine
(`simulated.py:196-205` computes commission on the BASE/un-slipped notional before
`executed_price = price * factor`) and this file's own VERIFY derivation. Comment-only
change; AST syntax check passed.

### WR-02: Decimal config values round-tripped through float() in fee/slippage init

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`, `itrader/execution_handler/slippage_model/linear_slippage_model.py`, `itrader/execution_handler/slippage_model/fixed_slippage_model.py`
**Commit:** cefbfba
**Applied fix:** Dropped the `float()` cast in `_init_fee_model` and `_init_slippage_model`
so configured `Decimal` rates (all `Optional[Decimal]` in `config/exchange.py`) flow
through unchanged and enter the Decimal domain once via `to_money` — removing the
`Decimal -> float -> Decimal(str(float))` round-trip flagged by CLAUDE.md's money policy.

Scope note beyond the literal finding: the finding claimed "the slippage models already
accept `float | Decimal`", but only the fee models did. The linear/fixed slippage model
`__init__` annotations were `float`-only, so passing a `Decimal` would have broken
`mypy --strict` (a program DoD gate). I therefore widened both slippage `__init__`
signatures to `float | Decimal` and coerced the stored rate to `float` only at the RNG
`uniform()` jitter boundary (the D-11 float seam — non-money noise, not a money
round-trip; the rate still enters Decimal via `to_money`). The `to_money(self.*_pct)`
call sites already accept Decimal. `mypy --strict` clean on all three files; 132 execution
unit tests, 30 E2E tests, and the 3-test BTCUSD oracle all pass.

### WR-03: commission merge key not guaranteed unique

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 4a678ec
**Applied fix:** Added `validate="one_to_one"` to the `commission_frame` left-merge on
`(entry_date, exit_date, side)` so a non-unique key (future multi-trade leaves opening/
closing on the same bars) raises a pandas `MergeError` instead of silently many-to-many
duplicating trade rows or mis-attributing commission. All 30 E2E tests still pass (current
single-round-trip leaves have unique keys, so the validation is satisfied).

### IN-01: VERIFY-note column tables omit columns the frozen golden contains

**Files modified:** `tests/e2e/sizing/over_cash_reject/scenario.py`, `tests/e2e/sltp/from_fill_held/scenario.py`
**Commit:** e625481
**Applied fix:** Added a one-line note above each illustrative order-mirror table stating
that the real golden also pins the leading `ticker` and the trailing deterministic `time`
identity column per `ORDER_SNAPSHOT_COLUMNS` (`reporting/orders.py:39-49`). Chose the note
over reformatting the tables to keep the load-bearing abbreviated tables readable.
Docstring-only change; AST checks passed.

### IN-02: over_cash_reject VERIFY references engine line numbers

**Files modified:** `tests/e2e/sizing/over_cash_reject/scenario.py`
**Commit:** ae95466
**Applied fix:** Replaced both `order_manager.py:393-414` cash-reservation-gate citations
(the drift-prone references the finding names) with an anchor to the stable `OrderManager`
admission cash-reservation gate and the `D-15` decision tag. The secondary
`strategies_handler.py:141` / `sizing_resolver.py:113-114` citations were left as
best-effort per the finding's allowance ("or accept that these citations are best-effort").
Docstring-only change; the over_cash_reject E2E test still passes.

---

_Fixed: 2026-06-10_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
