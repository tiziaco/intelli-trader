---
phase: 04-liquidation-cross-validation-re-baseline
fixed_at: 2026-06-16T13:10:00Z
review_path: .planning/phases/04-liquidation-cross-validation-re-baseline/04-REVIEW.md
iteration: 2
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-06-16T13:10:00Z
**Source review:** .planning/phases/04-liquidation-cross-validation-re-baseline/04-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 3 (fix_scope=all: WR-01, WR-02, IN-01)
- Fixed: 3
- Skipped: 0

All three findings were introduced/left by the iteration-1 fixes and were resolved
behavior-preservingly (one dead-code deletion + two documentation-truthfulness fixes).
No control flow changed, no logged value changed, no numerical change.

## Fixed Issues

### WR-01: `_collect_breaches` is dead code after the WR-01 collapse

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** 22764c9
**Applied fix:** Deleted the `_collect_breaches` single-shared-close adapter
entirely (former lines 462-474). A grep across `itrader/`, `tests/`, and
`scripts/` confirmed zero call sites — the production path (`_run_liquidation_pass`)
and the migrated unit test (`test_multi_breach_deterministic`) both call
`_collect_breaches_over_prices` directly. Also corrected the now-stale docstring in
`_collect_breaches_over_prices` that described itself as the target of "a thin
adapter `_collect_breaches`" — it now states the live path and unit tests call it
directly with no second collector to drift apart. Removing dead code; no behavior
change. (Reviewer note: the latent divergent-predicate hazard the adapter carried —
`position.current_price <= 0` vs `close <= 0` — is moot once the adapter is gone.)

### WR-02: WR-05 liquidation-pass gating describes an unreachable live-path scenario

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** c0e09e3
**Applied fix:** Applied review option (a) — corrected the docstring of
`_run_liquidation_pass`, the inline comment on `marked_portfolio_ids` in
`update_portfolios_market_value`, and the call-site comment, to state that the
`marked_portfolio_ids` gate is purely a DEFENSIVE guardrail. The comments now make
clear that under the current error policy the gate NEVER fires: the per-portfolio
mark failure RE-RAISES (line ~777) rather than continuing the loop, and the dispatch
error seam (`_on_handler_error` / live `_publish_and_continue`) works at whole-handler
granularity — so the pass either runs with the full active set or is never reached.
The previous comments asserting a reachable LIVE partial-mark skip were false; the gate
is kept as a guardrail for a possible FUTURE per-portfolio continue-on-mark-failure
policy. **No control flow changed** — the swallow was NOT moved; only the comments
were made truthful (documentation-only edit).

### IN-01: Liquidation log emits a quantized `liq_price` but reads as the formula value

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** f97c91f
**Applied fix:** Added a clarifying comment above the `Position force-liquidated`
log call in `_liquidate_position` explaining that the `liq_price` field logs the
QUANTIZED FillEvent price (`fill_price`) while `penalty` carries full precision, so a
reader cross-checking the log against the hand-computed isolated liq formula sees the
rounded field alongside the full-precision penalty — intentional, the logged value
mirrors the emitted FillEvent. **No logged value changed** (`liq_price=str(fill_price)`
is unchanged) — comment-only, so no test that inspects log output is affected.

## Verification

Run from the isolated worktree (PYTHONPATH set to avoid editable-install shadowing):

- SMA_MACD oracle byte-exact (`tests/integration/test_backtest_oracle.py`): 3 passed.
- `mypy --strict itrader`: Success, no issues found in 163 source files.
- Liquidation/reconcile/lock unit tests (15): all passed (incl.
  `test_multi_breach_deterministic`).
- Liquidation determinism double-run gate: DETERMINISM OK, byte-identical
  (`final_balance: 6081.191919191919191919191919`).
- Full suite (`poetry run pytest tests`): 1146 passed.

All fixes are documentation-only or dead-code removal — behavior-preserving with zero
numerical change. No accounting-core golden re-freeze. Tab/space per-file indentation
respected (edited regions were space-indented).

---

_Fixed: 2026-06-16T13:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
