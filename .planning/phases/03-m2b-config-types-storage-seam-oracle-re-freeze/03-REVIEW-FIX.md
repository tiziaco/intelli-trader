---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
fixed_at: 2026-06-05T00:00:00Z
review_path: .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/03-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 4
skipped: 1
status: partial
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-06-05
**Source review:** .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (WR-01 through WR-05; Info findings out of scope under `critical_warning`)
- Fixed: 4 (WR-02, WR-03, WR-04, WR-05)
- Skipped: 1 (WR-01 — resolved out-of-band per orchestrator override)

**Guardrail status (post-fix):**
- Oracle (`tests/integration/test_backtest_oracle.py`): `test_oracle_behavioral_identity` AND `test_oracle_numeric_values` BOTH PASS (byte-exact, 2 passed in 5.39s). Golden master not drifted.
- Full suite (`poetry run pytest -q`): 346 passed, 0 failed.
- Typecheck (`poetry run mypy itrader`, mypy --strict): Success, no issues found in 126 source files. (Ran mypy directly; `make typecheck` aborts in the worktree because the gitignored `.env` is absent — not a code failure.)

## Fixed Issues

### WR-02: Standalone manager fallback creates divergent (unshared) storage backends

**Files modified:** `itrader/portfolio_handler/cash/cash_manager.py`, `itrader/portfolio_handler/position/position_manager.py`, `itrader/portfolio_handler/transaction/transaction_manager.py`, `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** b22b471
**Applied fix:** In each of the four managers' `__init__`, when the portfolio lacks `state_storage` and a fallback backend is fabricated, the manager now writes that backend back onto the portfolio (`portfolio.state_storage = storage`, guarded by `try/except AttributeError`) so sibling managers constructed afterward share the same seam instead of each minting a disjoint store. Real `Portfolio` construction is unaffected (it sets `state_storage` before building managers, so the fallback branch never runs). Behavior-preserving for the golden path; closes the latent cross-manager-invariant trap in standalone/test construction.

### WR-03: `Order.created_at` is wall-clock `datetime.now()` despite event-derived-timestamp goal

**Files modified:** `itrader/order_handler/order.py`
**Commit:** 1c783f0
**Applied fix:** Removed the `datetime.now` default factories on `created_at`/`updated_at` (now `default=None`) and derive both from the order's own event-derived `self.time` in `__post_init__`. Used a `None`-guard (`if self.created_at is None`) rather than the review's unconditional assignment so an explicit caller-supplied timestamp is preserved — slightly more conservative than the suggested snippet while achieving the D-12 event-derived invariant. Does not reach the oracle output, so the golden master is unaffected (confirmed: oracle still byte-exact).

### WR-04: `add_fill` does not normalize `fill_price` to Decimal before storing it in audit data

**Files modified:** `itrader/order_handler/order.py`
**Commit:** 11b3da7
**Applied fix:** Added `fill_price = to_money(fill_price)` at the top of `add_fill` (alongside the existing `fill_quantity` normalization) so the value written into `additional_data["fill_price"]` is always Decimal, enforcing the D-04 money-domain boundary for the price as well as the quantity.

### WR-05: `_load_run_backtest_module` does not guard `spec`/`spec.loader` being `None`

**Files modified:** `tests/integration/test_backtest_oracle.py`
**Commit:** 38452ce
**Applied fix:** Added an existence check that `pytest.fail`s with a clear "oracle generator missing" message when `_RUN_BACKTEST` is absent, plus an `assert spec is not None and spec.loader is not None` guard before `module_from_spec`/`exec_module`, replacing the opaque `AttributeError: 'NoneType' object has no attribute 'loader'` with an actionable failure message.

## Skipped Issues

### WR-01: `_aligned` epoch-grid anchor silently changes firing behavior for non-daily timeframes

**File:** `itrader/outils/time_parser.py:127-145`
**Reason:** Resolved out-of-band per orchestrator override. The owner dispositioned WR-01 as "accept + note + follow-up": the `_aligned` docstring has already been qualified to daily-UTC-only with an explicit weekly epoch-Thursday caveat, and a follow-up todo was filed at `.planning/todos/pending/weekly-anchor-time-parser.md`. Per instruction, the `_aligned`/`check_timeframe` anchoring logic was NOT modified.
**Original issue:** The new epoch-grid alignment is not behavior-preserving for weekly/non-day-divisor timeframes (weekly now fires only on Thursdays vs. the prior every-midnight behavior). Only the daily golden path at 00:00 UTC is unaffected, so the regression-locked oracle numbers are safe.

---

_Fixed: 2026-06-05_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
