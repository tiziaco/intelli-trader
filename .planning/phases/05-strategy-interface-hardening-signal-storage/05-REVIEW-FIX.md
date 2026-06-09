---
phase: 05-strategy-interface-hardening-signal-storage
fixed_at: 2026-06-09T20:40:00Z
review_path: .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
iteration: 3
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-06-09T20:40:00Z
**Source review:** .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
**Iteration:** 3 (final iteration at the 3-iteration cap)

**Summary:**
- Findings in scope: 2 (fix_scope = all, so IN-01 is included)
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: `subscribed_portfolios` and subscribe/unsubscribe signatures typed `int` but carry runtime UUID `PortfolioId`s

**Files modified:** `itrader/strategy_handler/base.py`, `itrader/strategy_handler/strategies_handler.py`
**Commit:** a21e6da
**Applied fix:** Typed the strategy-layer portfolio-handle seam to its real
dual-handle runtime contract `PortfolioId | int` (the exact union
`order.py:55` / `order_manager.py:51` already use), instead of the lying plain
`int`:

- `base.py`: `self.subscribed_portfolios: list[PortfolioId | int] = []`;
  `subscribe_portfolio(self, portfolio_id: PortfolioId | int)`;
  `unsubscribe_portfolio(self, portfolio_id: PortfolioId | int)`. Added
  `PortfolioId` to the existing `from itrader.core.ids import ...` line and
  replaced the stale IN-04 "keep integer handles" comment with a WR-01
  dual-handle rationale.
- `strategies_handler.py`: the fan-out at line 145 passes the loop handle into
  `SignalEvent(portfolio_id=...)`, whose field is the documented int-declared
  **event seam** that already absorbs runtime UUIDs and is cast back to
  `PortfolioId` downstream in `order_manager.py`. To keep the honest `base.py`
  union from widening the entire event chain (signal/order/fill events +
  order_manager consumers — out of scope for this finding), the boundary is
  bridged with `cast(int, portfolio_id)`, the same idiom `order_manager.py`
  uses for this seam. Added `cast` to the `typing` import.

**Why a cast rather than widening `SignalEvent.portfolio_id`:** The event-layer
`portfolio_id: int` type-lie is a separate, broader seam spanning
`signal.py` / `order.py` / `fill.py` events and the `order_manager.py`
consumers. Widening it on this final capped iteration risked cascading mypy
errors across the order/fill event chain and destabilizing the gate. The
scoped `cast(int, ...)` closes WR-01 (honest `base.py` declaration) without
expanding scope.

**Verification:**
- `mypy --strict` clean over the full `itrader` tree (137 source files, no
  issues) — confirms the union stays gate-clean and the cast bridges the event
  boundary.
- Golden oracle `tests/integration/test_backtest_oracle.py` (3 cases) passes
  byte-exact; the change is a type annotation plus a runtime-noop `cast`.
- 21 strategy unit tests pass (24 total with the oracle cases).

**Note on the reviewer's secondary suggestion** ("consider adding `scripts/` to
the mypy `files` list"): deliberately NOT applied. Expanding mypy's scope to
`scripts/run_backtest.py` is a gate-policy change beyond this finding and would
likely surface unrelated pre-existing errors in scripts/ on a final capped
iteration. The type-contract defect itself — the lying `int` declaration — is
fully closed by the seam retype above.

### IN-01: `min(min_timeframe, strategy.timeframe)` relies on the `is None` guard narrowing `min_timeframe`

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** 569fd94
**Applied fix:** Applied the reviewer's optional hardening — a comment on the
`else` arm documenting that `min_timeframe` is guaranteed non-None there (the
None seed from IN-06 is handled by the `is None` branch above) and that this
arm is the load-bearing non-None branch a careless refactor must not move out
from under the guard. The reviewer classified this as "No change required";
the change is comment-only with zero behavioral or oracle impact.

**Verification:** `mypy --strict` clean; comment-only, no runtime change.

---

_Fixed: 2026-06-09T20:40:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3_
