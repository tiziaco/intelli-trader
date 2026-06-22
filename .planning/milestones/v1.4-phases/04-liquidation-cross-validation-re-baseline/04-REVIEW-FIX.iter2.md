---
phase: 04-liquidation-cross-validation-re-baseline
fixed_at: 2026-06-16T13:05:00Z
review_path: .planning/phases/04-liquidation-cross-validation-re-baseline/04-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 8
skipped: 1
status: partial
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-06-16T13:05:00Z
**Source review:** .planning/phases/04-liquidation-cross-validation-re-baseline/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (CR-01 + 5 Warnings + 4 Infos)
- Fixed: 8 (5 Warnings + 3 Infos; IN-03 covers two files)
- Skipped: 1 (CR-01 — already resolved before this run)

All fixes are behavior-preserving with zero numerical change. Verification gates
re-run after the full set:
- `mypy --strict itrader` → clean (163 source files)
- `poetry run pytest tests` → 1146 passed
- `tests/integration/test_backtest_oracle.py` → byte-exact (134 / 46189.87730727451, D-11)
- `scripts/determinism_liquidation_double_run.py` → DETERMINISM OK, final_balance 6081.191919191919191919191919
- No accounting-core golden re-freeze; owner-signed liquidation e2e goldens untouched.

## Fixed Issues

### WR-01: `_collect_breaches` (single-close) is dead in production — only `_collect_breaches_over_prices` runs

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`, `tests/unit/portfolio/test_liquidation.py`
**Commit:** 56ac31a
**Applied fix:** Collapsed `_collect_breaches` into a thin adapter that builds a
`{ticker: close}` map (all open positions marked at the same close) and delegates
to `_collect_breaches_over_prices`, so there is ONE breach predicate. Moved the
WR-02 unwired-Universe `StateError` guard into the shared collector so the
fail-loud behaviour is retained for both entry points. Repointed
`test_multi_breach_deterministic` at the production collector
(`_collect_breaches_over_prices`) so the deterministic-sort assertion guards the
real BAR-route path.

### WR-02: Determinism gate has a dead/misleading `final_balance` branch and a fragile hard-coded magic number

**Files modified:** `scripts/determinism_liquidation_double_run.py`
**Commit:** 94c7c56
**Applied fix:** Split the dead `or`-condition into two hard, independent
assertions (`closed_count != 1` and `final_balance != expected`). The
`final_balance` half now actually fails and returns 1 on divergence (previously
the inner block only acted on `closed_count`, so a balance divergence still
printed "DETERMINISM OK"). The expected balance is now derived from named
constants (`_INITIAL_CASH - _FORCED_CLOSE_LOSS`) rather than a bare 28-digit
literal; the derived value is byte-identical to the original literal
(`6081.191919191919191919191919`, verified). Gate re-run: DETERMINISM OK, exit 0.

### WR-03: `_liq_inputs` reaches through `cash_manager._storage` private API

**Files modified:** `itrader/portfolio_handler/cash/cash_manager.py`, `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** ef1405a
**Applied fix:** Added a public `CashManager.get_locked_margin_for(position_id) ->
Decimal` delegator over the storage seam and switched `_liq_inputs` to call it
instead of reaching through the private `_storage` attribute. A future storage
backend refactor now surfaces as a typed contract change on the public surface
rather than a silent cross-domain `AttributeError`.

### WR-04: Forced-close fill is emitted at `liq_price` (not breach close) — load-bearing, undocumented at the call site

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** 4548795
**Applied fix:** Added an explicit comment at the `_liquidate_position` call site
in `_run_liquidation_pass` recording that the breach is DETECTED on the bar close
but the position is SETTLED at `liq_price`, and that — with no `min(loss+penalty,
WB)` clamp — filling at the maintenance floor IS the loss-bounding mechanism
(DEF-01-C). Cross-references CR-01, the `_liquidate_position` docstring, and the
gap-through regression `test_liquidation_fills_at_liq_price_on_far_gap_through`
(name corrected to the test that actually exists). Comment-only; zero behaviour
change.

### WR-05: `update_portfolios_market_value` runs the liquidation pass even when a per-portfolio mark raised (live path)

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** dd1cbf4
**Applied fix:** The mark loop now records each portfolio that re-marked cleanly
this tick into `marked_portfolio_ids`; `_run_liquidation_pass` accepts that set
and SKIPS any active portfolio not in it. In the backtest path the re-raise still
aborts before the pass (all-or-nothing, unchanged); in the live
`_publish_and_continue` path a portfolio whose mark raised mid-loop is no longer
evaluated against its stale, partially-marked equity. `None` (legacy/unit-test
callers) means no gating. **Logic change — flagged for human verification** (the
set-membership gating is a new conditional path; backtest oracle + determinism
gate confirm zero numerical change on the existing single-portfolio paths, but a
reviewer should confirm the live-path skip semantics match the intended D-02
invariant).

### IN-01: `_run_liquidation_pass` re-derives closes already computed by the caller

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** 69fa36a
**Applied fix:** Changed `_run_liquidation_pass` to accept the already-built
`prices` map (renamed param `closes: Dict[str, Decimal]`) instead of re-iterating
`bar_events` to rebuild an identical dict. The mark price and the breach price are
now sourced from a single map, removing the place where they could diverge.

### IN-02: `_liquidate_position` does a function-local `from itrader.core.money import quantize`

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** 44ceaf1
**Applied fix:** Hoisted `quantize` into the module-level import alongside
`to_money` (`from itrader.core.money import to_money, quantize`) and removed the
in-method import. No import-cycle rationale existed (same module already imported).

### IN-03: Cross-val scenario qty was correct only by coincidence of the flat-100 entry

**Files modified:** `scripts/crossval/levered_run.py`, `scripts/crossval/liquidation_run.py`
**Commit:** 1558e20
**Applied fix:** Replaced the hard-coded `QTY = 200` in both runners with
`QTY = int(NOTIONAL / _entry_price(_BUY_DATE))`, where `NOTIONAL = 2 * CASH` and
`_entry_price` resolves the next-bar fill close from `_PRICES`. QTY now tracks the
synthetic frame; verified it still evaluates to 200 in both runners
(behaviour-preserving).

### IN-04: `cross_validate_accounting.py` unused `Decimal` import

**Files modified:** `scripts/cross_validate_accounting.py`
**Commit:** d8136cf
**Applied fix:** Removed the dead `from decimal import Decimal` (confirmed
`Decimal` is referenced nowhere else in the module).

## Skipped Issues

### CR-01: The DEF-01-C loss-cap (`_capped_realized_loss`) is dead code

**File:** `itrader/portfolio_handler/portfolio_handler.py`
**Reason:** Already resolved before this run by fix `b461db0` (via `/gsd:debug
liq-loss-cap-dead-code`, owner decision 2026-06-16). The REVIEW.md frontmatter
records it under `resolved:` and the CR-01 section carries a ✅ RESOLVED banner.
Verified against current code: `_capped_realized_loss` is gone, owner option (a)
fill-at-liq-price is the deliberate loss bound, and the docstrings/e2e comments
already state this. Out of scope for this fix run — not re-touched.

---

_Fixed: 2026-06-16T13:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
