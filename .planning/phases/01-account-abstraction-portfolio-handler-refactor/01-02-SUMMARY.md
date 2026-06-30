---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 02
subsystem: portfolio
tags: [account, cash, margin, decimal, code-motion, byte-exact, liquidation]

# Dependency graph
requires:
  - phase: 01-01
    provides: Account ABC contract (balance/available/reserve/release) + account/ barrel + D-04 SPOT-path resolution naming SimulatedCashAccount the verbatim-critical leaf
provides:
  - SimulatedCashAccount — CashManager cash-leaf moved byte-for-byte (D-05), satisfies the Account ABC, verbatim-critical SPOT leaf
  - SimulatedMarginAccount(SimulatedCashAccount) — margin superset (locks + borrow carry) + margin/liquidation MATH pulled down from PortfolioHandler (ACCT-02)
  - CashOperation entity relocated to account/simulated.py + re-exported from the account/ barrel (stable importer home for 01-03/01-03b)
affects: [01-03, 01-03b, phase-5-reconciliation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cash→margin superset by ABC inheritance (margin adds only the margin-only surface + math, zero cash-logic duplication)"
    - "Full-precision fill/lock/carry paths deliberately skip the 2dp quantize (Pitfall 1 byte-exact gate)"
    - "Math-pulldown moves the Universe dependency seam (set_universe) down with the math (ACCT-02)"

key-files:
  created:
    - itrader/portfolio_handler/account/simulated.py
  modified:
    - itrader/portfolio_handler/account/__init__.py

key-decisions:
  - "SimulatedCashAccount.available added as a thin Decimal alias of the verbatim available_balance to satisfy the Account ABC without altering CashManager internals (byte-exact)"
  - "SimulatedMarginAccount gains a set_universe/_universe seam — the margin/liq math-pulldown moves its Universe dependency down with it (ACCT-02); 01-03 wires it"
  - "margin_ratio binds self.portfolio.total_equity to a Decimal-typed local (self.portfolio is Any) to stay mypy --strict clean — the handler source was strict via its typed total_equity(portfolio_id)->Decimal"

patterns-established:
  - "Account leaves are verbatim money-math homes — code-motion only, no improvement/reorder/re-quantize"

requirements-completed: [ACCT-01, ACCT-02]

# Metrics
duration: 4min
completed: 2026-06-30
---

# Phase 1 Plan 02: Simulated Account Money-Math Code-Motion Summary

**Byte-exact-critical code-motion: SimulatedCashAccount is CashManager moved byte-for-byte (incl. CashOperation), SimulatedMarginAccount adds the margin superset + the margin/liquidation math pulled down from PortfolioHandler — oracle held byte-exact, no consumer re-pointed.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-30T20:41:53Z
- **Completed:** 2026-06-30T20:45:54Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Created `account/simulated.py` with `SimulatedCashAccount(Account)` — the **verbatim** `CashManager` cash-leaf code-motion (D-05). The cash-flow math the SMA_MACD byte-exact oracle exercises is byte-for-byte identical: `balance`, `available_balance`, `deposit`, `withdraw`, `process_transaction_cash_flow`, `apply_fill_cash_flow` (the one full-precision trade-path primitive, no mid-stream quantize), `assert_funds_invariant`, `get_balance_info`, `get_cash_operations`, `validate_balance_consistency`, `_validate_and_convert_amount`, `_create_operation`.
- Moved the `CashOperation` `@dataclass` entity verbatim into `account/simulated.py` — its single canonical home once `cash_manager.py` is deleted in 01-03.
- Satisfied the `Account` ABC: `reserve_cash` → `reserve(order_id, amount)` and `release_reservation` → `release(order_id)` (D-05 drops `portfolio_id`), with the fixed `"order cash reservation"` description and `str(order_id)` reference id folded in; added `available` as a thin Decimal alias of the verbatim `available_balance`.
- Preserved the constructor + injected `PortfolioStateStorage` seam verbatim (WR-02 share-back); logger bound `component="SimulatedCashAccount"`.
- Added `SimulatedMarginAccount(SimulatedCashAccount)` — the strict margin superset (D-02). Margin-only methods moved verbatim from `cash_manager.py` (`locked_margin_total`, `get_locked_margin_for`, `lock_margin`, `release_margin`, `accrue_borrow_interest`, `assert_lock_fits_buying_power`); the pure-Decimal margin/liquidation MATH pulled DOWN from `portfolio_handler.py` (`maintenance_margin`, `margin_ratio`, `_isolated_liq_price`, `_is_breached`, `_liquidation_penalty`, `_liq_inputs`) with receivers adapted to the account's own state (LX-04 1:1).
- The liquidation `global_queue.put` emission + `_liquidate_position`/`_run_liquidation_pass` shell **stayed in `portfolio_handler.py`** (ACCT-02 — verified `maintenance_margin` still present there); no consumer re-pointed this wave.
- Extended the `account/` barrel to export `Account`, `SimulatedCashAccount`, `SimulatedMarginAccount`, `VenueAccount`, `CashOperation`.

## Task Commits

1. **Task 1: SimulatedCashAccount — verbatim CashManager cash-leaf code-motion (incl. CashOperation)** — `706797a` (feat)
2. **Task 2: SimulatedMarginAccount — margin superset + liq math pulldown + barrel** — `54e9cdd` (feat)

## Files Created/Modified
- `itrader/portfolio_handler/account/simulated.py` (created) — `CashOperation` entity + `SimulatedCashAccount` (verbatim cash leaf) + `SimulatedMarginAccount` (margin superset + liq math), 4-space, Decimal end-to-end
- `itrader/portfolio_handler/account/__init__.py` (modified) — barrel extended with the `Simulated*` leaves + `CashOperation` (stable importer home)

## Decisions Made
- **`available` ABC alias (byte-exact):** the `Account` ABC names the buying-power property `available`; `CashManager`'s verbatim internals (`withdraw`/`process_transaction_cash_flow`/`reserve`) read `available_balance`. Kept `available_balance` verbatim and added `available` as a thin alias returning the same Decimal — no math change.
- **`set_universe`/`_universe` on the margin leaf:** the margin/liq math-pulldown depends on the Universe read-model; the seam moves down WITH the math (ACCT-02). Mirrors the handler's `set_universe`. 01-03 wires it when the handler re-points to call down.
- **`margin_ratio` Decimal-typed local:** `self.portfolio` is typed `Any`, so `self.portfolio.total_equity` is `Any`; bound it to a `Decimal` local before the division to keep `mypy --strict` clean (the handler source was strict via its typed `total_equity(portfolio_id) -> Decimal`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] margin_ratio returned Any under mypy --strict**
- **Found during:** Task 2
- **Issue:** Adapting the handler's `total_equity(portfolio_id)` receiver to the account form `self.portfolio.total_equity` returns `Any` (the account's `self.portfolio` is `Any`-typed), so `mypy --strict` flagged `Returning Any from function declared to return "Decimal"` (no-any-return).
- **Fix:** Bound `self.portfolio.total_equity` to a `Decimal`-annotated local before the division. No money-math change — same Decimal value, byte-exact.
- **Files modified:** `itrader/portfolio_handler/account/simulated.py`
- **Commit:** `54e9cdd`

**2. [Rule 3 - Blocking] margin leaf needs a Universe seam**
- **Found during:** Task 2
- **Issue:** The pulled-down margin/liq math dereferences a Universe read-model; the account had no universe attribute (only the handler did), so the math could not be mypy-clean or callable.
- **Fix:** Added `_universe` + `set_universe` to `SimulatedMarginAccount` (the math-pulldown moves its dependency down with it, ACCT-02). Dark this wave; wired in 01-03. Documented in Decisions.
- **Files modified:** `itrader/portfolio_handler/account/simulated.py`
- **Commit:** `54e9cdd`

## Issues Encountered
None beyond the two Rule-3 mypy/seam fixes above.

## Verification

- Task 1 smoke: `issubclass(SimulatedCashAccount, Account)` — ok; `CashOperation` importable from `account.simulated`
- Task 2 smoke: `issubclass(SimulatedMarginAccount, SimulatedCashAccount)` — ok; all five symbols import from the barrel incl. `CashOperation`
- `poetry run mypy --strict itrader/portfolio_handler/account` — Success: no issues found in 4 source files
- Float-money grep on `simulated.py`: only serialization-edge `float(...)` casts (exception payloads + `get_balance_info`, verbatim from source) and one comment line referencing the `Decimal(float)` prohibition — no `Decimal(float)` introduced
- `portfolio_handler.py` margin/liq math still present (NOT removed this wave): `grep -c "def maintenance_margin"` returns 1
- Indentation: no tabs in `account/simulated.py` (4-space, matching the `cash_manager.py` code-motion source)
- **Oracle byte-exact gate:** `poetry run pytest tests/integration/test_backtest_oracle.py` — 3 passed. This plan adds only net-new, unimported leaf files; no consumer wired, no money-math movement on the hot path, so the SMA_MACD oracle (`134 / 46189.87730727451`) is structurally untouched and confirmed green.

## Known Stubs
None. The margin leaf's `set_universe`/`_universe` is a wiring seam (not a data stub) — dark this wave by design (ACCT-02), consumed in 01-03.

## Next Phase Readiness
- Plan 01-03 receives both `Simulated*` leaves + the `CashOperation` barrel home — ready to re-point `Portfolio` onto `SimulatedCashAccount`/`SimulatedMarginAccount` (D-03 leaf selection by `enable_margin`), wire `set_universe`, re-point `PortfolioHandler`'s liquidation emission shell to call DOWN into the account math, and delete `cash_manager.py` (importers re-point to `itrader.portfolio_handler.account`).
- No blockers.

## Self-Check: PASSED

- Files: `itrader/portfolio_handler/account/simulated.py` FOUND; `account/__init__.py` modification FOUND
- Commits: `706797a`, `54e9cdd` FOUND in git log

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
