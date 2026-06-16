---
phase: 03-shorts-borrow-carry
verified: 2026-06-15T21:00:00Z
status: passed
score: 11/11
overrides_applied: 0
---

# Phase 3: Shorts & Borrow Carry — Verification Report

**Phase Goal:** A strategy can open and hold a first-class short position (the LONG_ONLY guard
removed, the CR-01 cover-arm hole fixed), with correct short PnL and borrow-interest carry
accrued on open shorts.
**Verified:** 2026-06-15
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | `Instrument.borrow_rate: Decimal = Decimal("0")` — carry-off keeps SMA_MACD byte-exact (D-01) | VERIFIED | `itrader/core/instrument.py:90`; runtime check confirms `type == decimal.Decimal` |
| 2  | `CashOperationType.BORROW_INTEREST` exists with value `"BORROW_INTEREST"` (D-03) | VERIFIED | `itrader/core/enums/portfolio.py:74`; `_missing_` case-insensitive parser handles it; runtime confirmed |
| 3  | `StrategiesHandler.add_strategy` admits non-LONG_ONLY strategies ONLY when BOTH `allow_short_selling` AND `enable_margin` are on (SHORT-01/D-07) | VERIFIED | `itrader/strategy_handler/strategies_handler.py:276-285`; 5 tests in `test_strategies_handler_registration.py` all pass |
| 4  | Both flags threaded from `compose.py` and `live_trading_system.py` into `StrategiesHandler.__init__` (SHORT-01) | VERIFIED | `compose.py:205-206`; `live_trading_system.py:170-171` — both read from `trading_rules` and pass to `StrategiesHandler` |
| 5  | Cover detection is side-agnostic: `(SELL and side==LONG) or (BUY and side==SHORT)` on the `side` discriminator, NOT signed `net_quantity`; `abs(open_position.net_quantity)` passed to `resolve_exit`; over-cover clamps to flat (SHORT-02/D-05/D-06) | VERIFIED | `admission_manager.py:773-789`; predicate dispatches on `PositionSide` enum, passes `abs(net_quantity)` to `resolve_exit`; `over_cover_clamp` test passes |
| 6  | Short PnL is first-class `|size| × (entry − exit)` via `PositionSide.SHORT` branches; carry NEVER folds into `Position.realised_pnl` (SHORT-03/D-08) | VERIFIED | `position.py:188-196` (realised) and `209-210` (unrealised) SHORT branches confirmed; `short_pnl` tests green; `_accrue_short_carry` writes to cash ledger, not Position |
| 7  | Per-bar carry `days × close × |size| × borrow_rate / Decimal("365")` — Decimal end-to-end; no `Decimal(float)`; days basis from bar business time, never `datetime.now(UTC)` (CARRY-01/D-02/D-04) | VERIFIED | `portfolio.py:721-731`; `Decimal(str(total_seconds()))` conversion used; `days_basis` and `borrow_interest` tests pass; no `Decimal(float)` on the carry path |
| 8  | CR-01 fix: carry does NOT accrue for a short absent from the bar's prices; `_last_accrual_time` is NOT advanced for unmarked shorts (CARRY-01 / code-review BLOCKER CR-01) | VERIFIED | `portfolio.py:689-690` — early `continue` when `ticker not in marked_tickers`; regression test `test_short_absent_from_prices_defers_carry_and_does_not_advance_clock` present |
| 9  | WR-01/02/03/05 margin-seam residuals hardened in one touch (D-09): settlement-side solvency assertion, lock-release symmetry, per-lock open-commission accumulator, universe-unwired StateError | VERIFIED | `portfolio.py:412,426-452,465`; `portfolio_handler.py:326-334`; all four WR tests (`funds_invariant_lock`, `release_symmetry`, `open_commission_accumulator`, `universe_unwired`) pass |
| 10 | Three PARKED e2e scenarios pass against hand-computed literals on the real run path; synthetic instruments only, NEVER BTCUSD; nothing `--freeze`d; determinism double-run byte-identical (D-10) | VERIFIED | `tests/e2e/short_roundtrip/`, `short_carry/`, `partial_cover/` all pass; no BTCUSD found except in "NEVER BTCUSD" docstring negations; `tests/golden/` has no new artifacts; carry scenario passes twice identically |
| 11 | SMA_MACD oracle byte-exact: 134 trades / `46189.87730727451`; `mypy --strict` clean; full suite (1128 tests) green | VERIFIED | `make test-integration` all 16 integration tests pass, `summary.json`: `trade_count=134`, `final_equity=46189.87730727451`; `poetry run mypy --strict itrader/` → "Success: no issues found in 185 source files"; `make test` → 1128 passed |

**Score:** 11/11 truths verified

---

### Required Artifacts

| Artifact | Provides | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/instrument.py` | `borrow_rate: Decimal = Decimal("0")` on frozen `Instrument` | VERIFIED | Line 90; Decimal-typed, default-off, docstring entry at line 74-76 |
| `itrader/core/enums/portfolio.py` | `CashOperationType.BORROW_INTEREST` member | VERIFIED | Line 74; serializer at `reporting/cash_operations.py` untouched (enum-agnostic) |
| `itrader/strategy_handler/strategies_handler.py` | Two-flag-gated `add_strategy` registration | VERIFIED | Lines 29-64 (params), 276-285 (guard); tabs indentation correct |
| `itrader/trading_system/compose.py` | Flags threaded from `trading_rules` into `StrategiesHandler` | VERIFIED | Lines 205-206 |
| `itrader/trading_system/live_trading_system.py` | Flags threaded into `StrategiesHandler` for live system | VERIFIED | Lines 170-171 |
| `itrader/order_handler/admission/admission_manager.py` | Side-agnostic cover-arm + clamp-to-flat + WR-04 leverage floor | VERIFIED | Lines 773-789 (cover-arm); lines 641-651 (leverage floor at `Decimal("1")`) |
| `itrader/portfolio_handler/portfolio_handler.py` | Bar business time + Universe threaded into mark hook; WR-02 StateError | VERIFIED | Lines 447-463 (bar_time + _universe); lines 326-334 (StateError guard) |
| `itrader/portfolio_handler/portfolio.py` | `_accrue_short_carry` with CR-01 skip; WR-01/03/05 in `_process_transaction_margin` | VERIFIED | Lines 657-739 (carry); lines 412, 426-465 (WR-01/03/05) |
| `itrader/portfolio_handler/cash/cash_manager.py` | `accrue_borrow_interest` debiting via `BORROW_INTEREST` op with bar business timestamp | VERIFIED | Lines 362-398 |
| `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py` | Parked pure-short round-trip | VERIFIED | Passes; synthetic instrument; hand-computed literals |
| `tests/e2e/short_carry/test_short_carry_scenario.py` | Parked multi-bar held-short carry with determinism double-run | VERIFIED | Passes; `BORROW_INTEREST` asserted; double-run byte-identical |
| `tests/e2e/partial_cover/test_partial_cover_scenario.py` | Parked partial-cover reduce-not-close | VERIFIED | Passes; remaining short carries on |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `compose.py` | `StrategiesHandler.add_strategy` | `trading_rules.allow_short_selling / .enable_margin` at construction | VERIFIED | Lines 205-206 pass both flags |
| `live_trading_system.py` | `StrategiesHandler.__init__` | `_trading_rules.allow_short_selling / .enable_margin` | VERIFIED | Lines 170-171 |
| `admission_manager._resolve_signal_quantity` | `sizing_resolver.resolve_exit` | `abs(open_position.net_quantity)` passed on BUY-cover-on-short | VERIFIED | Lines 785-789 |
| `portfolio_handler.update_portfolios_market_value` | `portfolio.update_market_value_of_portfolio` | `bar_event.time` + `self._universe` threaded (not wall clock) | VERIFIED | Lines 447-463 |
| `portfolio._accrue_short_carry` | `cash_manager.accrue_borrow_interest` | `BORROW_INTEREST` debit with bar business `timestamp` | VERIFIED | Lines 733-738 |
| `portfolio._accrue_short_carry` | marked_tickers (CR-01 skip) | `ticker not in marked_tickers` → `continue` without clock advance | VERIFIED | Lines 689-690 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `portfolio._accrue_short_carry` | `borrow_rate` | `universe.instrument(ticker).borrow_rate` — Instrument read-model | Yes — real per-symbol Decimal value | FLOWING |
| `portfolio._accrue_short_carry` | `days` | `Decimal(str((bar_time - last_accrual).total_seconds())) / Decimal("86400")` | Yes — bar business time delta | FLOWING |
| `portfolio._accrue_short_carry` | `carry` | `days * current_price * abs(net_quantity) * borrow_rate / Decimal("365")` | Yes — Decimal arithmetic, no float | FLOWING |
| `cash_manager.accrue_borrow_interest` | `balance_before/after` | computed from `_balance` before/after debit | Yes — real ledger values | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `short_registration` tests (5 cases) | `pytest -k short_registration` | 5 passed | PASS |
| `cover_arm or over_cover_clamp or leverage_floor` (6 cases) | `pytest -k "cover_arm or over_cover_clamp or leverage_floor"` | 6 passed | PASS |
| `borrow_interest or borrow_interest_op or days_basis or short_pnl` (11 cases) | `pytest -k "borrow_interest or borrow_interest_op or days_basis or short_pnl"` | 11 passed | PASS |
| `funds_invariant_lock or release_symmetry or open_commission_accumulator or universe_unwired` (7 cases) | `pytest` with k filter | 7 passed | PASS |
| Three parked e2e scenarios | `pytest tests/e2e/short_roundtrip tests/e2e/short_carry tests/e2e/partial_cover -m e2e` | 3 passed | PASS |
| Oracle byte-exact (integration suite) | `make test-integration` | 16 passed; trade_count=134, final_equity=46189.87730727451 | PASS |
| Full suite | `make test` | 1128 passed | PASS |
| `mypy --strict` | `poetry run mypy --strict itrader/` | "Success: no issues found in 185 source files" | PASS |
| Determinism double-run (carry scenario) | `pytest tests/e2e/short_carry -m e2e` × 2 | Both runs pass; carry amounts + timestamps byte-identical | PASS |

---

### Probe Execution

No conventional probe scripts found. Behavioral spot-checks above subsume probe-level verification.

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| SHORT-01 | Plans 03, 02 | LONG_ONLY guard removed; non-LONG_ONLY admitted only under both flags | SATISFIED | `strategies_handler.py:276-285`; registration tests green |
| SHORT-02 | Plans 04, 06 | BUY-to-cover routes through `resolve_exit`; over-cover clamps to flat | SATISFIED | `admission_manager.py:773-789`; `cover_arm`/`over_cover_clamp` tests green |
| SHORT-03 | Plans 04, 06 | First-class short PnL `|size|×(entry−exit)` in `PositionSide.SHORT` branches | SATISFIED | `position.py:188-196, 209-210`; `short_pnl` tests green; carry separate |
| CARRY-01 | Plans 01, 05 | Per-bar `days × price × |size| × rate/365` booked as `BORROW_INTEREST` cash op; days from bar business time | SATISFIED | `portfolio.py:657-739`; `cash_manager.py:362-398`; `borrow_interest`/`days_basis` tests green; CR-01 fix confirmed |

Note: REQUIREMENTS.md traceability table still shows "Pending" for all four IDs — this is expected; the orchestrator updates the table on phase close, not the executor. The implementation evidence above confirms all four requirements are satisfied in code.

---

### Code-Review BLOCKER: CR-01 Fixed Inline

The code-review BLOCKER CR-01 ("carry accrues on a stale `current_price` for a short absent from the tick's prices") was found and fixed inline during execution:

- **Commits**: `1667467` (CR-01/WR-02/WR-03/WR-05) and `01db518` (WR-01 unsized SELL gate)
- **Fix**: `_accrue_short_carry` now takes `marked_tickers: set[str]`; a short whose ticker is absent from `prices` hits `continue` at line 689 WITHOUT advancing `_last_accrual_time` — the next priced bar accrues the full elapsed interval on a correct mark.
- **Regression test**: `test_short_absent_from_prices_defers_carry_and_does_not_advance_clock` in `tests/unit/portfolio/test_carry.py`.
- **WR-04 tracking**: WR-04 (`assert_lock_fits_buying_power` add-back reads 0 due to call order) is deliberately deferred to Phase 4 with explicit rationale: conservative (fails loud, not a leak), fix requires a call-order change best bundled with the P4/XVAL-01 margin-seam re-baseline to avoid touching the FRAGILE seam twice. Tracked in `deferred-items.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `portfolio.py` | 632 | `datetime.now(UTC)` fallback in `update_market_value_of_portfolio` | Info | Only fires when `bar_time is None` (legacy mark-only path); the carry accrual path requires `bar_time is not None` (line 646) so the wall-clock fallback never reaches carry. Not a determinism hazard. |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase-3 modified file.

---

### WR Residuals Disposition

| ID | Status | Disposition |
|----|--------|-------------|
| WR-01 | Fixed inline (commit 1667467, 01db518) | Settlement-side solvency assertion added; `funds_invariant_lock` test green |
| WR-02 | Fixed inline (commit 1667467) | Universe-unwired `StateError` at both read sites; `universe_unwired` test green |
| WR-03 | Fixed inline (commit 1667467) | Lock-release symmetry + `current_price <= 0` guard; `release_symmetry` test green |
| WR-04 | Deliberately deferred | Conservative (fails loud); fix bundled with P4/XVAL-01 seam touch — tracked in `deferred-items.md` |
| WR-05 | Fixed inline (commit 88af0c7) | Per-lock open-commission accumulator; `open_commission_accumulator` test green; also applied as `borrow_rate==0 → plain continue` in carry loop |
| IN-01..04 | Tracked in `deferred-items.md` | Info-level dead code / inconsistent conventions; no behavioral impact |

---

### Human Verification Required

None. All phase-3 truths are verifiable from code, tests, and the oracle gate. The blocking human-verify checkpoint (Task 3, Plan 06) was executed and approved by the owner ("approved", 2026-06-15) — recorded in `03-06-VERIFY-SIGNOFF.md`.

---

### Gaps Summary

No gaps. All 11 must-have truths verified, all required artifacts exist and are substantive and wired, all key links confirmed, all four requirement IDs satisfied, 1128 tests green, `mypy --strict` clean, oracle byte-exact.

---

_Verified: 2026-06-15T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
