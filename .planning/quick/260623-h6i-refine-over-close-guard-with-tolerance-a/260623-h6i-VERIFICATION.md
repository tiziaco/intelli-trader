---
phase: quick-260623-h6i
verified: 2026-06-23T00:00:00Z
status: passed
score: 6/6 must-haves verified
gross_protection_preserved: true
---

# Quick Task 260623-h6i: Refine Over-Close Guard With Tolerance — Verification Report

**Task Goal:** Refine the over-close guard (spot + margin CR-02) to compare the over-sell
excess against the existing `PositionManager.tolerance` (1e-5) instead of strict `>`, so
sub-quantum Decimal noise is absorbed as a clean full close while a GROSS over-sell still
raises loudly — WITHOUT drifting the SMA_MACD oracle (134 / 46189.87730727451).

**Verified:** 2026-06-23
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | Sub-tolerance spot over-sell (hold 1, sell 1+1e-9) does NOT raise, ends flat | ✓ VERIFIED | `test_spot_sub_tolerance_over_close_absorbs_as_clean_close` (test_spot_oversell_guard.py:57) asserts no raise, `len(positions)==0`, `len(closed_positions)==1`. PASSED in run. |
| 2 | Sub-tolerance margin over-close does NOT raise, ends flat + lock released | ✓ VERIFIED | `test_margin_sub_tolerance_over_close_absorbs_as_clean_close` (test_portfolio.py:444) asserts no raise, `len(positions)==0`, `locked_margin_total==Decimal("0")`. PASSED. |
| 3 | GROSS spot over-sell (hold 1, sell 5) STILL raises InvalidTransactionError | ✓ VERIFIED | `test_spot_over_close_fill_fails_loud` (test_spot_oversell_guard.py:42) `pytest.raises(InvalidTransactionError)`. PASSED. Guard math: excess=4 > 1e-5. |
| 4 | GROSS margin over-close (hold 2, sell 3) STILL raises | ✓ VERIFIED | `test_margin_over_close_fill_fails_loud` (test_portfolio.py:426) + `test_margin_short_over_cover_fill_fails_loud` (:496) `pytest.raises`. Both PASSED. excess=1 > 1e-5. |
| 5 | Both guard sites compare `(transaction.quantity - prior_qty) > self.position_manager.tolerance`, no new constant | ✓ VERIFIED | portfolio.py:346 (spot) and :444 (margin) both read the exact expression. `grep -c position_manager.tolerance` = 2. tolerance defined once in position_manager.py:88 (`Decimal('0.00001')`). |
| 6 | SMA_MACD oracle stays byte-exact at 134 / 46189.87730727451 | ✓ VERIFIED | `pytest tests/integration/test_backtest_oracle.py` → 3 passed. Golden frozen reference (tests/golden/summary.json): trade_count=134, final_equity=46189.87730727451, final_cash=46189.87730727451. Oracle asserts fresh run == golden EXACT (no tolerance). |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `itrader/portfolio_handler/portfolio.py` | Tolerance-aware guards at spot (:346) + margin (:444), TABS, Decimal | ✓ VERIFIED | Both lines start with TAB indentation (confirmed via awk). Subtraction + comparison are Decimal end-to-end. Decision-anchored comments cite 260623-gao + 260623-h6i debug session, the 64-BTC phantom-equity case, and `_should_close_position`. |
| `tests/unit/portfolio/test_spot_oversell_guard.py` | Spot sub-tolerance absorbed-as-close + GROSS-still-raises | ✓ VERIFIED | New test at :57 (Decimal-typed `Decimal("1")+Decimal("1e-9")`); existing GROSS test at :42 intact. |
| `tests/unit/portfolio/test_portfolio.py` | Margin CR-02 sub-tolerance + GROSS-still-raises | ✓ VERIFIED | New test at :444 (Decimal-typed); GROSS tests at :426 and :496 intact. |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| portfolio.py spot guard :346 | self.position_manager.tolerance | `(transaction.quantity - prior_qty) > tolerance` | ✓ WIRED |
| portfolio.py margin CR-02 guard :444 | self.position_manager.tolerance | `(transaction.quantity - prior_qty) > tolerance` | ✓ WIRED |
| sub-tolerance excess passes guard | _should_close_position (position_manager.py:205) | `abs(net_quantity) <= self.tolerance` absorbs residual as clean close | ✓ WIRED (tests assert ends flat / closed) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed in 5.71s | ✓ PASS |
| Guard regression suite | `pytest ...test_spot_oversell_guard.py ...test_portfolio.py -k "sub_tolerance or fails_loud or over_cover"` | 5 passed, 28 deselected | ✓ PASS |
| mypy --strict | `mypy itrader` | Success: no issues found in 187 source files | ✓ PASS |

### Scope Check (out-of-scope changes NOT made)

| Check | Status | Evidence |
| ----- | ------ | -------- |
| git diff scope = portfolio.py + 2 test files only | ✓ VERIFIED | `git diff --stat 69af7d0^..HEAD`: portfolio.py (+20), test_portfolio.py (+21), test_spot_oversell_guard.py (+18). No other files. |
| Fix C (sign-aware net_quantity/market_value) NOT made | ✓ VERIFIED | Not in diff; no market_value/net_quantity sign changes. |
| Strategy/sizing/matching NOT changed | ✓ VERIFIED | No strategy_handler / sizing / matching_engine files in diff. |
| portfolio.py change = only the two guard-condition lines | ✓ VERIFIED | diff shows exactly two `-`/`+` pairs converting strict `>` to tolerance-aware; rest is comment edits. |

### Anti-Patterns Found

None. No debt markers (TODO/FIXME/XXX) introduced. No float-on-money: the subtraction and comparison operands are Decimal (`transaction.quantity`, `prior_qty`, `tolerance` all Decimal).

## GROSS-Over-Sell Protection Verdict

**INTACT — protection is NOT weakened.**

The guard changed from `transaction.quantity > prior_qty` to
`(transaction.quantity - prior_qty) > self.position_manager.tolerance` where
`tolerance = Decimal('0.00001')` (1e-5). The branch still raises whenever the over-sell
excess exceeds 1e-5:

- Spot GROSS (hold 1, sell 5): excess = 4 >> 1e-5 → raises (test PASSED).
- Margin GROSS over-close (hold 2, sell 3): excess = 1 >> 1e-5 → raises (test PASSED).
- Margin SHORT over-cover GROSS: raises (`test_margin_short_over_cover_fill_fails_loud` PASSED).

Only sub-tolerance dust (1e-9 << 1e-5) now passes the guard, after which
`_should_close_position` (`abs(net) <= tolerance`) settles the ~1e-27 residual to flat.
The 64-BTC phantom-equity case (a gross excess) remains protected. The relaxation window
is bounded to [0, 1e-5), strictly below the position-closure tolerance — there is no
silent net-short/flip path for any real over-sell.

## Gaps Summary

None. All six must-haves verified against the actual codebase. Both guard sites use the
correct tolerance-aware Decimal comparison with TABS and reuse the single existing
`PositionManager.tolerance` constant. Sub-tolerance and GROSS regression tests exist and
pass for both spot and margin. The SMA_MACD oracle is byte-exact at 134 /
46189.87730727451 (independently re-run, 3 passed), mypy --strict is clean, and the change
is scoped to exactly portfolio.py plus the two test files — no Fix C, strategy, sizing, or
matching drift.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
