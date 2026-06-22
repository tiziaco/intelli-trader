---
phase: quick-260622-pmk
verified: 2026-06-22T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Quick Task quick-260622-pmk Verification Report

**Task Goal:** Make an unfunded short increase (same-side SELL against an open SHORT with
allow_increase=True) produce a clean AUDITED REJECTED order at the admission gate — symmetric
with the long-increase arm (triggered_by=OrderTriggerSource.CASH_RESERVATION, one audited
REJECTED entity persisted, nothing emitted, free cash unchanged) — instead of being admitted
and aborting the backtest run at settlement.
**Verified:** 2026-06-22
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Unfunded short increase yields exactly ONE audited REJECTED order at admission (not a settlement-time InvalidTransactionError abort) | ✓ VERIFIED | `admission_manager.py:303-365` step 3c gate returns `_reject_unsized_signal(...)` before bracket assembly; `test_unfunded_short_increase_is_rejected_via_audited_path` asserts one REJECTED entity, queue empty; **41 passed** |
| 2 | The short rejection uses the SAME path as the long arm (CASH_RESERVATION via `_reject_unsized_signal`, PENDING→REJECTED, persisted, nothing emitted, queue empty) | ✓ VERIFIED | `admission_manager.py:357-365` calls `_reject_unsized_signal(..., triggered_by=OrderTriggerSource.CASH_RESERVATION, operation_type=OrderOperationType.CASH_RESERVATION)`; test asserts `from_status==PENDING`, `to_status==REJECTED`, `triggered_by is CASH_RESERVATION` |
| 3 | A FUNDED short increase remains byte-identical: admitted, sized, settles through SCALE-IN branch; both frozen short-scale-in e2e leaves green & unchanged | ✓ VERIFIED | `test_funded_short_increase_still_admits` asserts SELL OrderEvent qty 100 emitted; `tests/e2e/short_scale_in` + `short_scale_in_partial_cover` → **2 passed** unchanged |
| 4 | The SELL-add books NO admission-side cash reservation (D-06); the new gate is a SOLVENCY CHECK, never a reserve | ✓ VERIFIED | Gate at `admission_manager.py:320-365` never calls `.reserve(...)`; only `available_cash(...)` read + comparison; reserve block (`:264-301`) remains BUY-only; test asserts `available_cash AFTER == before` |
| 5 | Long arm + direction/max_positions gates byte-exact; SMA_MACD spot oracle byte-exact 134 / 46189.87730727451 | ✓ VERIFIED | `git diff main` shows BUY reserve block, direction gate, max_positions gate unaltered; new code is additive step 3c only; oracle test **3 passed**, frozen `summary.json` trade_count 134 / final_equity 46189.87730727451 intact |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/order_handler/admission/admission_manager.py` | Admission-side margin solvency check emitting audited CASH_RESERVATION rejection for unfunded short SELL-add | ✓ VERIFIED | Contains `PositionSide.SHORT` guard at `:325`; real if-branch on `self._enable_margin` (`:334`); spot arm division-free (`:345-346`); reuses `_reject_unsized_signal` |
| `tests/unit/order/test_admission_rules.py` | Regression test: one audited REJECTED, empty queue, unchanged cash; plus funded non-regression | ✓ VERIFIED | Contains `def test_unfunded_short_increase_is_rejected_via_audited_path` (`:987`) + `test_funded_short_increase_still_admits` (`:1028`); both green |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| Short SELL-add solvency gate | CASH_RESERVATION audited rejection | `_reject_unsized_signal(triggered_by=CASH_RESERVATION)` | ✓ WIRED | `admission_manager.py:357-365` |
| New gate | Available buying power | `available_cash + own_prior_lock` (WR-01 credit-back) | ✓ WIRED | `admission_manager.py:343,347-349`; `own_prior_lock = existing_notional / effective_leverage` mirrors `cash_manager.assert_lock_fits_buying_power` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Admission suite (incl. both new tests) | `pytest tests/unit/order/test_admission_rules.py -q` | 41 passed in 0.16s | ✓ PASS |
| Funded short-scale-in e2e (frozen leaves) | `pytest tests/e2e/short_scale_in tests/e2e/short_scale_in_partial_cover -q` | 2 passed in 0.11s | ✓ PASS |
| SMA_MACD oracle (byte-exact) | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed in 5.09s | ✓ PASS |
| mypy --strict | `poetry run mypy --strict itrader` | Success: no issues found in 187 source files | ✓ PASS |

### Hard-Constraint Checks

| Constraint | Method | Result | Status |
|------------|--------|--------|--------|
| Gate triggers only on SELL against open SHORT when prospective lock > buying power | Read `:320-350` — guard `primary.action is Side.SELL` AND `open_short.side is PositionSide.SHORT`, reject only if `prospective_lock > buying_power` | Confirmed | ✓ |
| Funded scale-in byte-unchanged (WR-01 own-prior-lock credit-back, no over-reject) | `own_prior_lock` credited at `:343/346`; funded test admits; e2e leaves unchanged | Confirmed | ✓ |
| No new FillStatus / OrderTriggerSource | `git diff main -- itrader/core/enums/` empty; enum sources untouched on branch | None added | ✓ |
| No Decimal(float) | grep modified file: only `Decimal("...")` string literals + `to_money`; no `Decimal(float)` | Clean | ✓ |
| TABS preserved in admission_manager.py | New 3c block (lines 320-365): 46 tab-indented, 0 space-indented code lines; no mixed-indent | Pure TABS | ✓ |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None | — | No debt markers (TBD/FIXME/XXX), no stubs, no Decimal(float), no orphaned code |

### Gaps Summary

No gaps. All five must-have truths are VERIFIED against the actual codebase. The admission-side
short-add margin solvency gate (step 3c, `admission_manager.py:303-365`) is real, reachable
(in the post-sizing gate region of `process_signal`, after the BUY reserve block, before bracket
assembly), guarded precisely to the admitted short SELL-add, reuses the long arm's
`_reject_unsized_signal` with `OrderTriggerSource.CASH_RESERVATION`, books no reservation, and
keeps the spot arm division-free behind a real `if self._enable_margin` branch. The WR-01
own-prior-lock credit-back prevents over-rejection of fundable adds. All four gates pass with the
oracle byte-exact (134 / 46189.87730727451), mypy clean (187 files), funded e2e leaves unchanged,
and the branch diff is scoped to exactly the two declared files with enum sources untouched.

---

_Verified: 2026-06-22_
_Verifier: Claude (gsd-verifier)_
