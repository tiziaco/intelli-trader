---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
plan: 01
subsystem: portfolio_handler
tags: [perf, fusion, valuation, decimal, byte-exact]
requires:
  - position_manager.get_positions() read-owner seam (Phase 6/7)
provides:
  - "position_manager._fused_valuation(): single-pass (market_value, unrealized_pnl, margin_basis)"
  - "get_total_market_value / get_total_unrealized_pnl delegate to the fused result"
affects:
  - itrader/portfolio_handler/position/position_manager.py
tech-stack:
  added: []
  patterns:
    - "Fused single-pass accumulator + delegating accessors (mirrors apply_realised_increment / get_total_realized_pnl, PERF-02 D-01)"
    - "IN-03 do-not-re-add-a-loop comment on the single iteration owner"
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/position/position_manager.py
    - tests/unit/portfolio/test_position_manager.py
decisions:
  - "D-04 fusion scope: only the two genuine per-bar passes (get_total_market_value + get_total_unrealized_pnl) are fused; maintenance_margin and the per-FILL margin lock are NOT per-bar, so no portfolio/portfolio_handler wiring changed."
metrics:
  duration: ~20m
  completed: 2026-06-25
  tasks: 3
  files: 2
requirements: [PERF-08]
---

# Phase 8 Plan 01: Hot-Path Valuation Fusion Summary

Fused the per-bar portfolio mark-to-market into a SINGLE pass over the open positions:
`position_manager._fused_valuation()` accumulates total market value, total unrealised PnL,
and the locked-margin basis in one `for` loop; the public accessors delegate to it and return
byte-identical Decimals. SMA_MACD oracle stays byte-exact (134 / 46189.87730727451).

## What Was Built

- **`_fused_valuation(self) -> tuple[Decimal, Decimal, Decimal]`** — one iteration of
  `self._storage.get_positions().values()` accumulating `Σ market_value`, `Σ unrealised_pnl`,
  `Σ aggregate_notional` (the locked-margin basis), each seeded `Decimal('0.00')` with `+=` order
  preserved → byte-identical to the prior two independent passes. NO quantize, NO mid-sum rounding.
- **`get_total_market_value` / `get_total_unrealized_pnl`** now delegate to `_fused_valuation()`
  (unpack the relevant component). Public signatures and returned Decimals unchanged.
- **IN-03 comment** on the fused owner warning the next dev not to re-add per-accessor loops
  (mirrors the `apply_realised_increment` / `get_total_realized_pnl` precedent in the same file).
- **Fusion-equivalence tests** (`tests/unit/portfolio/test_position_manager.py`): a mixed
  LONG/SHORT multi-position set asserts fused accessors == reference loops byte-for-byte
  (`str()` equality), an empty-portfolio test, and a margin-basis equivalence test.

## Task 1 Audit — per-bar position-iteration set & fusion scope (D-04)

Per-bar golden hot path: `update_portfolios_market_value` → `portfolio.update_market_value`
(`portfolio.py:567`) → `position_manager.update_position_market_values` (`:255`).

**Genuine per-bar position iterations:**
1. `update_position_market_values` (`position_manager.py:255-265`) — the WRITE pass that mutates each
   `position.current_price`. This is a mutation pass, NOT a valuation read; it is unchanged.
2. `get_total_market_value` (`:286-295` pre-change) — per-bar valuation READ #1 (metrics snapshot).
3. `get_total_unrealized_pnl` (`:297-305` pre-change) — per-bar valuation READ #2.

Passes 2 and 3 are the two D-04 targets — now fused into one.

**NOT per-bar (excluded from the fusion, public numbers untouched):**
- `assert_accumulator_consistent` (`:348-352`) — gated test/debug re-sum seam, deliberately
  oracle-dark (D-03: no runtime re-sum on the hot path).
- `calculate_position_metrics` (`:368`) — on-demand single-position query.
- `_get_positions_by_side` (`:478`) — on-demand summary.
- `close_all_positions` (`:488`) — emergency bypass.
- `portfolio_handler.maintenance_margin` (`:365`) — on-demand query (consumed by `margin_ratio`),
  oracle-dark on the golden path (no breaches → never written).
- `portfolio.py:489/:514` margin lock (`new_lock = position.aggregate_notional / leverage`) —
  fires PER-FILL only (open / scale-in / close), NOT per bar.

**Stale-CONTEXT correction (per 08-PATTERNS.md, confirmed):** CONTEXT.md cited
`portfolio_handler:638-645`/`:706` as a per-bar mark-to-market margin loop. Those lines are the
**liquidation breach loop** (`_run_liquidation_pass`, now `portfolio_handler.py:597`) and the `on_fill`
Transaction build — neither is a per-bar mark-to-market margin pass. The real per-bar margin basis is
`aggregate_notional`, which the fused pass now exposes from the single owner.

## Task 3 — wiring + gate (a)

Per the Task 1 scope decision, **there is no per-bar caller that iterates positions for the margin
basis** (the per-FILL lock and on-demand `maintenance_margin` are the only `aggregate_notional`
consumers, neither per-bar). The fused method exposes the locked-margin basis component for future
per-bar consumers, but no `portfolio` / `portfolio_handler` caller changed — so Task 3 made **no
production code change**. The fusion is complete with the two valuation accessors delegating, and
`position_manager` is the single owner of per-bar position iteration.

Gate (a) byte-exact: `tests/integration/test_backtest_oracle.py` — 3/3 pass (numeric values
134 / 46189.87730727451, behavioral identity, determinism double-run). `mypy --strict itrader`:
"no issues found in 166 source files".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Orphaned assertion leaked into the empty-portfolio test**
- **Found during:** Task 2 (GREEN run)
- **Issue:** The RED-phase Edit's `old_string` for the test append did not capture the final
  `assert marked.unrealised_pnl > 0` line of the preceding test, so it landed at the end of the
  new `test_fusion_empty_portfolio` (NameError: `marked` not defined).
- **Fix:** Moved the orphaned assertion back into
  `test_short_pnl_unrealised_is_avg_minus_current_times_net` where it belongs and removed it from
  the empty-portfolio test.
- **Files modified:** tests/unit/portfolio/test_position_manager.py
- **Commit:** 48da911 (folded into the GREEN commit)

## Verification

- `tests/unit/portfolio/test_position_manager.py` — 32/32 pass (incl. 4 new fusion tests).
- `tests/integration/test_backtest_oracle.py` — 3/3 pass (134 / 46189.87730727451, determinism identical).
- `mypy --strict itrader` — clean (166 files).
- `git diff --check` — no whitespace errors; indentation unchanged (0 tab-lines, 4 spaces).
- Single per-bar position iteration confirmed by grep (the fused loop at
  `position_manager.py:316`; the other two iterations are the gated test seam and on-demand summary).

## Commits

- `277c2f6` test(08-01): add failing fusion-equivalence test (RED)
- `48da911` feat(08-01): fuse per-bar valuation into single position pass (GREEN)

## TDD Gate Compliance

RED (`test`) commit `277c2f6` precedes GREEN (`feat`) commit `48da911`. No REFACTOR commit needed
(the GREEN implementation is already minimal and clean). Note: the two market_value/unrealized
equivalence tests passed at RED because they assert against the existing accessors; the two tests
exercising the new `_fused_valuation` method (`test_fusion_margin_basis`, `test_fusion_empty_portfolio`)
failed at RED with `AttributeError: 'PositionManager' object has no attribute '_fused_valuation'`,
satisfying the RED gate for the new method.

## Self-Check: PASSED

- itrader/portfolio_handler/position/position_manager.py — FOUND
- tests/unit/portfolio/test_position_manager.py — FOUND
- Commit 277c2f6 — FOUND
- Commit 48da911 — FOUND
