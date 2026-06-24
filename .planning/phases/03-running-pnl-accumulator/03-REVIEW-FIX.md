---
phase: 03-running-pnl-accumulator
fixed_at: 2026-06-24T00:00:00Z
review_path: .planning/phases/03-running-pnl-accumulator/03-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-06-24
**Source review:** .planning/phases/03-running-pnl-accumulator/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (fix_scope: all — 3 warning, 3 info)
- Fixed: 6
- Skipped: 0

All fixes verified by `poetry run pytest tests/unit/portfolio/` — 275 passed
(2 original accumulator tests + 3 new WR-02 equivalence tests, plus the full
existing portfolio suite including `test_close_all_positions`).

## Fixed Issues

### WR-01: `close_all_positions` bypasses the accumulator — realised PnL silently dropped

**Files modified:** `itrader/portfolio_handler/position/position_manager.py`
**Commit:** 1427ebd
**Status:** fixed: requires human verification (equivalence-critical logic change)
**Applied fix:** Fed the running accumulator from inside `close_all_positions`
(the emergency bypass path) — capturing `position.realised_pnl` BEFORE the close
and applying `apply_realised_increment(position.realised_pnl - prior_realised)`
after `_close_position`. Critically, `_close_position` itself was NOT touched and
the Portfolio settle arms were NOT changed: the normal funnel
(`process_position_update` -> `_close_position`, then the Portfolio arm feeds the
increment) remains the single funnel for the run path. Feeding inside
`_close_position` (as the review sketched) would double-count the normal path,
because the Portfolio arms already feed the increment for fills routed through
`process_position_update`; and a partial close never reaches `_close_position`
(it returns in-place), so `_close_position` is not a complete funnel anyway.
`close_all_positions` is the only caller that bypasses the Portfolio arms, so it
is the only site that needed its own feed. This preserves byte-identity on the
SMA_MACD golden path (`close_all_positions` is dormant on that path) and restores
equivalence on the emergency path. **Flagged for human verification** because
this is an equivalence-correctness change on a Decimal-end-to-end money path;
`test_close_all_positions` passes and the new WR-02 tests confirm no double-count
on the normal funnel.

### WR-02: No accumulator test covers the margin arm, SHORT, or multi-position lifecycles

**Files modified:** `tests/unit/portfolio/test_realised_pnl_accumulator.py`
**Commit:** 1abc290
**Applied fix:** Added three equivalence cases reusing the existing
`_resum_realised` dual-loop oracle and `==` drift-lock assertion:
(1) `test_accumulator_equals_resum_margin_open_partial_full` — a margin portfolio
(`enable_margin=True`, `max_leverage=10`) driving open -> partial close -> full
close on a levered (L=5) position through `_process_transaction_margin`;
(2) `test_accumulator_equals_resum_short_lifecycle_spot` — a SHORT lifecycle
(sell to open, partial cover, full cover) through the spot funnel, asserting the
SHORT `realised_pnl` branch stays in sync;
(3) `test_accumulator_equals_resum_two_tickers_interleaved` — two tickers (BTC,
ETH) interleaved, asserting the accumulator equals the cross-ticker re-sum after
each close (a per-ticker desync would not show on a single-ticker re-sum).
All three pass.

### WR-03: Accumulator silently desyncs when a close path is driven outside the funnel

**Files modified:** `itrader/portfolio_handler/position/position_manager.py`
**Commit:** 09a3b11
**Applied fix:** Added a gated enforcement seam `assert_accumulator_consistent()`
(the review's explicit alternative to feeding inside the manager, which would
double-count — see WR-01). It recomputes the prior dual open+closed re-sum
(seeded `Decimal('0.00')`, no mid-sum quantize) and raises
`PositionCalculationError` on any value-`==` divergence, so a desync fails LOUD
in tests rather than producing a quietly wrong total. It is deliberately NOT on
the per-bar hot path (D-03: no runtime re-sum guard — that would re-pay the
O(positions) cost PERF-02 removed); it is a test/debug seam callable on demand.
The prose-only contract in the docstrings now has an actual enforcement path.

### IN-01: Non-deterministic naive `datetime.now()` in test fixtures

**Files modified:** `tests/unit/portfolio/test_realised_pnl_accumulator.py`
**Commit:** 1abc290
**Applied fix:** Replaced `datetime.now()` in the `portfolio` fixture and the
`_buy`/`_sell` builders with a module-level `_FIXED_TIME = datetime(2024, 1, 1,
tzinfo=timezone.utc)` — fixed business time, tz-aware, aligned with the
determinism convention. (Committed together with WR-02/IN-02 as they edit the
same shared fixtures/builders.)

### IN-02: Money passed as `int`/`float` into a Decimal-end-to-end portfolio

**Files modified:** `tests/unit/portfolio/test_realised_pnl_accumulator.py`
**Commit:** 1abc290
**Applied fix:** Passed `Decimal` literals for cash (`Decimal("150000")`),
prices, quantities, and commission (`Decimal("0")`) throughout the fixtures,
builders, and call sites — modeling the intended Decimal money discipline rather
than mirroring the production-discouraged float-for-money entry. (Committed with
WR-02/IN-01.)

### IN-03: Docstring/method name overstates what `get_total_realized_pnl` now does

**Files modified:** `itrader/portfolio_handler/position/position_manager.py`
**Commit:** 09a3b11
**Applied fix:** Rewrote the `get_total_realized_pnl` docstring to state it
returns the cached running accumulator and does NOT inspect open/closed positions,
with an explicit warning not to "fix" a suspected desync by re-adding a loop
(which would re-pay the removed O(positions) cost) and a pointer to the new
`assert_accumulator_consistent` seam. (Committed together with the WR-03 seam as
both edit the same method region.)

---

_Fixed: 2026-06-24_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
