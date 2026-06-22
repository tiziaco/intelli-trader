---
phase: 03-shorts-borrow-carry
plan: 04
subsystem: order-admission
tags: [shorts, cover-arm, admission, leverage, wr-04, short-pnl, cr-01]
requires:
  - "itrader/order_handler/sizing_resolver.py resolve_exit (reused unchanged)"
  - "itrader/core/portfolio_read_model.py PositionView (side + unsigned net_quantity)"
  - "tests/unit/order/test_admission_rules.py (Wave-0 cover_arm / over_cover_clamp / leverage_floor stubs)"
  - "tests/unit/order/test_sizing_resolver.py (Wave-0 cover_magnitude stub)"
  - "tests/unit/portfolio/test_position_manager.py (Wave-0 short_pnl stub)"
provides:
  - "side-agnostic cover-arm in AdmissionManager._resolve_signal_quantity (BUY-cover-on-short routes through resolve_exit)"
  - "side-based increase/cover split in AdmissionManager._enforce_position_admission (no longer misclassifies a short as a long)"
  - "WR-04 leverage floor at Decimal(1) on AdmissionManager._effective_leverage"
  - "SHORT-03 short-PnL confirmation tests (realised + unrealised SHORT branches)"
affects:
  - "Plan 03-05 (carry nets at cash/equity — Position.realised_pnl stays clean trade PnL, D-08)"
  - "any SHORT_ONLY / LONG_SHORT order path that covers an open short"
tech-stack:
  added: []
  patterns:
    - "side-agnostic reduction predicate: action opposes open position side (SELL-on-LONG or BUY-on-SHORT)"
    - "dispatch on PositionView.side, never the sign of the (unsigned) net_quantity magnitude"
key-files:
  created: []
  modified:
    - itrader/order_handler/admission/admission_manager.py
    - tests/unit/order/test_admission_rules.py
    - tests/unit/order/test_sizing_resolver.py
    - tests/unit/portfolio/test_position_manager.py
decisions:
  - "D-05 side-agnostic exit: a reduction routes BOTH SELL-on-long AND BUY-on-short through the same resolve_exit, passing abs(net_quantity)"
  - "D-06 clamp-to-flat: a full cover sizes to exactly the short magnitude (resolve_exit caps at the full magnitude); the excess never auto-opens a long"
  - "D-08 confirm-only: Position.realised_pnl SHORT branch already first-class; carry nets at cash/equity in Plan 05; position.py untouched"
  - "D-09/WR-04: floor _effective_leverage at Decimal(1) with a sub-1/zero cap guard"
  - "DEVIATION (Rule 1): PLAN framed cover detection as net_quantity < 0, but the order-boundary read-model carries an UNSIGNED magnitude + a side discriminator (PositionView.net_quantity == abs(buy-sell) >= 0). Detection dispatches on side; the same sign bug also lived in _enforce_position_admission and was fixed there too (it blocked the cover BUY as a disallowed increase)."
metrics:
  duration: ~25m
  completed: 2026-06-15
  tasks: 2
  files: 4
---

# Phase 3 Plan 04: Side-Agnostic Cover-Arm + WR-04 Leverage Floor Summary

Closed the v1.0 M5b CR-01 cover-arm hole: a BUY-to-cover on an open short now routes through the proven `resolve_exit` (clamped to flat) instead of falling into entry sizing and flipping the short book long, folded in the WR-04 leverage floor, and confirmed SHORT-03 PnL is first-class — all while holding the SMA_MACD golden oracle byte-exact (134 / `46189.87730727451`).

## What Was Built

**Task 1 — side-agnostic cover-arm + clamp-to-flat (commits `89e1731` RED, `9cf59d7` GREEN):**
- `_resolve_signal_quantity`: replaced the long-only exit predicate (`action is SELL and net>0`) with ONE generalized reduction predicate — "the order action opposes the open position's side": `(SELL on LONG) or (BUY on SHORT)` — both passing `abs(net_quantity)` to the unchanged `resolve_exit`.
- `_enforce_position_admission`: the increase/cover split now dispatches on `side` instead of the sign of `net_quantity` (see deviation below).
- Result: a BUY-cover reduces/closes the short (clamp-to-flat at `exit_fraction == 1`); the long-exit and long-increase paths stay byte-exact.

**Task 2 — WR-04 leverage floor + SHORT-03 confirm (commits `263ad2b` RED, `d288f30` GREEN):**
- `_effective_leverage`: floors the resolved effective leverage at `Decimal("1")` after the venue-cap `min`, guarding a misconfigured `Instrument.max_leverage` of 0 or sub-1 — no sub-1 effective leverage, no downstream divide-by-zero (`locked_margin = notional / L`). Logs the floor loudly; normal caps unaffected.
- SHORT-03: added confirmation tests asserting the existing `PositionSide.SHORT` branches compute realised `|size| × (entry − exit)` net of commissions and unrealised `(avg_price − current_price) × net_quantity`. `position.py` is untouched (D-08 confirm-only).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug / Rule 3 - Blocking] Cover detection and the increase gate keyed on the wrong sign convention**
- **Found during:** Task 1 (RED→GREEN). The PLAN and its `<interfaces>` framed the cover as `open_position.net_quantity < 0`.
- **Issue:** The order-boundary read-model carries an **unsigned magnitude** plus a `side` discriminator — `PositionView.net_quantity == Position.net_quantity == abs(buy_quantity − sell_quantity) >= 0` (`position.py:121`). A short never presents `net_quantity < 0` here; direction lives in `side`. The plan's `< 0` predicate would never match, and the pre-existing `_enforce_position_admission` gate (`net_quantity > 0` → "increase") misclassified an open short as a long, **rejecting the legitimate BUY-cover as a disallowed increase** (`ADMISSION_INCREASE`) — which is why the first GREEN attempt emitted no order.
- **Fix:** Both the cover-arm reduction predicate (`_resolve_signal_quantity`) and the increase/cover split (`_enforce_position_admission`) now dispatch on `open_position.side` (`PositionSide.LONG` vs `SHORT`). `abs(net_quantity)` is still passed to `resolve_exit` (identity on a magnitude, kept for symmetry/defence). The long INCREASE and long-exit paths stay byte-exact (an open long has `side LONG`).
- **Files modified:** `itrader/order_handler/admission/admission_manager.py` (added `PositionSide` import).
- **Tests:** the `cover_arm` / `over_cover_clamp` assertions were updated to check `position.side is PositionSide.SHORT` instead of `net_quantity < 0`.
- **Commit:** `9cf59d7`
- **`net_quantity < 0` artifact note:** the PLAN's `must_haves.artifacts.contains: "net_quantity < 0"` string is intentionally NOT present in the production code — that framing was incorrect for the verified read-model. The verified, correct convention (unsigned magnitude + `side`) is documented inline at the fix site.

## Verification

- `poetry run pytest tests/unit/order -k "cover_arm or over_cover_clamp or cover_magnitude"` — 5 passed
- `poetry run pytest tests/unit/order -k leverage_floor` — 3 passed
- `poetry run pytest tests/unit/portfolio -k short_pnl` — 2 passed
- `poetry run pytest tests/unit/order tests/unit/portfolio` — 453 passed, 8 skipped (no regressions)
- `poetry run pytest tests/unit` — 1027 passed, 9 skipped
- `make test-integration` (oracle) — 16 passed, byte-exact 134 / `46189.87730727451` (`test_backtest_oracle.py` vs `tests/golden/summary.json`)
- `mypy --strict itrader/order_handler/admission/admission_manager.py` — clean
- `position.py`, `sizing_resolver.py`, `portfolio.py` UNCHANGED (over-close guard intact, confirmed via `git diff`)

## Threat Mitigations Applied

- **T-03-08 (Tampering, cover-arm fall-through):** the side-agnostic predicate routes a BUY-cover-on-short through `resolve_exit` instead of entry sizing — CR-01 hole closed. Verified by `cover_arm`.
- **T-03-09 (Elevation, over-leverage / div-by-zero):** WR-04 floors effective leverage at `Decimal("1")` with a sub-1/zero cap guard. Verified by `leverage_floor`.
- **T-03-10 (Tampering, golden drift):** the long-exit operands are unchanged (an open long has `side LONG`) — oracle held 134 / `46189.87730727451`.

## Known Stubs

None. All five Wave-0 stubs (`cover_arm`, `over_cover_clamp`, `cover_magnitude`, `leverage_floor`, `short_pnl`) are un-skipped and passing.

## Self-Check: PASSED

- Created/modified files exist: `03-04-SUMMARY.md`, `admission_manager.py` — FOUND
- Commits exist: `89e1731`, `9cf59d7`, `263ad2b`, `d288f30` — FOUND
