---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
fixed_at: 2026-06-08T05:30:00Z
review_path: .planning/phases/07-m5b-sizing-policy-metrics-universe-coverage/07-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 9
skipped: 1
status: partial
---

# Phase 7: Code Review Fix Report

**Fixed at:** 2026-06-08T05:30:00Z
**Source review:** .planning/phases/07-m5b-sizing-policy-metrics-universe-coverage/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 10 (CR-01 + WR-01..WR-09)
- Fixed: 9
- Skipped: 1 (WR-09, D-live scope)

All 716 tests pass after the fixes. The backtest oracle
(`tests/integration/test_backtest_oracle.py`) remains byte-exact, confirming the
golden FractionOfCash/LONG_ONLY path is unchanged.

**Verification note on the worktree:** this phase's `itrader` package is an
editable install whose `.pth` points at the MAIN repo, not the per-run worktree.
Tests were therefore run with `PYTHONPATH=<worktree>` to force the worktree
source to shadow the installed copy — without this, pytest silently exercised the
unmodified main-repo source. This is environment plumbing, not a code finding,
but it is recorded here because it materially affected fix verification.

## Fixed Issues

### CR-01: SHORT_ONLY covers are sized as entries — a BUY cover can flip a SHORT_ONLY book long

**Files modified:** `itrader/strategy_handler/strategies_handler.py`, `tests/unit/strategy/test_strategy.py`
**Commit:** 668400f
**Applied fix:** Option (b) — closed the door at registration. `add_strategy`
already rejected `LONG_SHORT`; widened the guard to reject any direction that is
not `LONG_ONLY` (so `SHORT_ONLY` is now also rejected loudly), consistent with
the D-09 "shorts need the margin model" stance and the smaller, oracle-dark
change. Rationale for choosing (b) over (a): the codebase already gates shorting
out of v1 (`LONG_SHORT` was rejected; the margin/liquidation milestone is a
documented future stop), and the project context instructs to prefer (b) unless
the codebase clearly intends SHORT_ONLY to be usable now — it does not. Option
(a) would have made SHORT_ONLY usable, which contradicts D-09. Updated the
existing `test_long_short_registration_rejected` message assertion and added
`test_short_only_registration_rejected`. The admission-gate tests
(`test_admission_rules.py`) that exercise the SHORT_ONLY direction gate via
`process_signal` directly are untouched and still pass — CR-01 only closes the
*registration* door; the gate itself remains intact.

### WR-01: `SignalIntent.quantity` is silently dropped at fan-out

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** e710713
**Applied fix:** Added `quantity=intent.quantity` to the `SignalEvent`
construction in `calculate_signals`. Both fields are `Decimal | None` in the
money domain, so no boundary parse is needed; `None` preserves the golden
"resolver decides" behavior.

### WR-02: `step_size` quantization snaps to the Decimal exponent, not the step value

**Files modified:** `itrader/order_handler/sizing_resolver.py`, `tests/unit/order/test_sizing_resolver.py`
**Commit:** aaa69f8
**Applied fix:** Added a module-level `_quantize_to_step(qty, step)` helper
(`(qty / step).to_integral_value(ROUND_DOWN) * step`) and used it in both
`resolve_entry` and `resolve_exit` in place of `qty.quantize(step, ...)`. Added
four tests covering non-power-of-ten steps (0.5, integer 5, trailing-zero
"0.010", and an exit on the 0.5 grid). The existing power-of-ten tests still pass
because `_quantize_to_step` is identical to `quantize` for `1 x 10^n` steps —
the golden path uses `step_size=None` and is therefore untouched. Did not add the
optional "raise on zero" since the validator already surfaces an `INVALID_QUANTITY`
outcome and adding a new raise was not required to close the defect.

### WR-03: `_pending_brackets` hygiene — entries leak on local cancel, assembly failure, and survive order modification

**Files modified:** `itrader/order_handler/order_manager.py`
**Commit:** 45f6ef1
**Applied fix:** Three changes. (1) `cancel_order` now pops
`self._pending_brackets[order.id]` on a successful local terminal transition, so a
locally-cancelled PercentFromFill parent disarms its pending entry. (2) The
`_assemble_bracket_and_emit` exception handler pops `primary.id` so a storage
failure after pending registration cannot orphan the entry. (3) `modify_order`
refreshes `pending.quantity` via `dataclasses.replace` when the parent's quantity
changes, so fill-anchored children use the current quantity. Additionally gated
child creation in `on_fill` on `applied` being True (children are only anchored
when the mirror actually applied the fill). **Requires human verification:** this
finding includes logic-sensitive lifecycle gating (the `applied` condition and
the pop ordering) that passes syntax/structure checks but should be manually
confirmed against the intended PercentFromFill lifecycle.

### WR-04: `OrderManager.on_fill` swallows all reconciliation exceptions — reservation release can be skipped silently

**Files modified:** `itrader/order_handler/order_manager.py`
**Commit:** 42416b2
**Applied fix:** Moved the terminal reservation release into a `finally` block
gated by a `should_release` flag (False on the non-terminal "unknown status"
early-return path, which intentionally holds the reservation), so a terminal fill
always releases even if the reconciliation body raises. Added `exc_info=True` to
the error log and `raise` after logging to honor the backtest fail-fast policy
(matching the portfolio side of the same FILL via `_on_handler_error`). The
release inside `finally` is itself wrapped so a release failure is logged, never
masked. **Requires human verification:** this changes the on_fill exception and
release control flow (swallow → fail-fast + finally-release); the re-raise
semantics and release ordering relative to child cancellation/creation should be
manually confirmed.

### WR-05: Mutable default argument in the reference strategy

**Files modified:** `itrader/strategy_handler/SMA_MACD_strategy.py`
**Commit:** 40c247e
**Applied fix:** Changed `tickers: list[str] = []` to
`tickers: list[str] | None = None` and pass `list(tickers or [])` to `super()`.
All call sites pass an explicit non-empty `tickers=[...]`, so the golden path is
byte-identical (a fresh copy of the same contents); the oracle confirms this.

### WR-06: SLTP policy has no declaration seam on the Strategy base

**Files modified:** `itrader/strategy_handler/base.py`, `itrader/strategy_handler/strategies_handler.py`
**Commit:** b252686
**Applied fix:** Added `sltp_policy: SLTPPolicy | None = None` as a typed
constructor kwarg to `Strategy.__init__`, set `self.sltp_policy`, serialized it in
`to_dict` (repr or None), and replaced the `getattr(strategy, 'sltp_policy', None)`
in the handler fan-out with the direct attribute read `strategy.sltp_policy`. The
default `None` preserves the golden "no policy" path; the SLTP unit tests and the
oracle still pass.

### WR-07: Ping grid derived from `store.symbols()[0]` only

**Files modified:** `itrader/trading_system/backtest_trading_system.py`
**Commit:** 0c12b55
**Applied fix:** Fail loudly with `ConfigurationError` when the store has no
symbols, and derive the ping grid from `reduce(pd.Index.union, (store.index(s)
for s in symbols))` so a sparse multi-symbol universe never silently drops bars.
For the single-symbol golden run the `reduce` returns that one index unchanged
(no union call), so the tick grid is byte-identical — confirmed by the oracle.
**Requires human verification:** this modifies the golden backtest composition
root; the single-symbol no-op was verified by the oracle, but the multi-symbol
union behavior (ordering/dtype of the unioned `DatetimeIndex`) should be manually
confirmed before relying on multi-symbol runs.

### WR-08: Mark-to-market failures are swallowed per portfolio

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** e5efd8b
**Applied fix:** Replaced the per-portfolio `except ... logger.warning ...
continue` in `update_portfolios_market_value` with the same fail-fast posture as
`on_fill` on the same dispatch path: publish a `PortfolioErrorEvent` via
`_publish_error_event`, then `raise` so the registry's `_on_handler_error`
backtest policy aborts the run instead of consuming a stale mark. **Requires
human verification:** this changes error-handling control flow (swallow →
fail-fast) on a hot dispatch path; the re-raise behavior under the registry's
error policy should be manually confirmed.

## Skipped Issues

### WR-09: Live loop records equity before the tick's BAR is processed, and continues after partial dispatch

**File:** `itrader/trading_system/live_trading_system.py:257-268, 281-286`
**Reason:** Skipped — genuinely out of scope / risky. The reviewer itself flags
this as **D-live scope** ("this code was modified this phase, so the drift is
fresh"). The fix requires two substantial architectural changes to the LIVE
trading path (which is not the golden backtest path): (1) reordering metric
recording so it runs only after the tick's BAR is dispatched/drained, and (2)
replacing the catch-and-continue around `_dispatch` with a dedicated
`EventHandler` subclass that overrides `_on_handler_error` with the documented
publish-and-continue live policy. Both are non-trivial behavioral changes on the
live path with no golden-oracle coverage to protect them, and the program's
definition of done is centered on the backtest path being correct and
regression-locked. Per the fixer's risk guidance, forcing these changes now would
introduce live-path drift without a safety net. Recommended for a dedicated
D-live work item rather than an automated review-fix.

---

_Fixed: 2026-06-08T05:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
