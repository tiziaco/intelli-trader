---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 03b
subsystem: tests
tags: [account, cash, margin, user-id-strip, test-migration, consumer-ripple, liquidation]

# Dependency graph
requires:
  - phase: 01-02
    provides: SimulatedCashAccount / SimulatedMarginAccount leaves + CashOperation barrel home
  - phase: 01-03
    provides: Portfolio.cash_manager -> Portfolio.account, CashManager deleted, user_id stripped, margin/liq math moved onto the account leaf
provides:
  - tests/unit + tests/integration migrated onto the post-extraction production API (account surface, account-leaf-at-construction, user_id-free); both suites green
  - The unit/integration half of the 01-03 test-consumer ripple fully closed (no debt left for the 01-05 terminal gate)
affects: [01-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Account-leaf selection is a CONSTRUCTION-time concern (01-03 D-03): margin tests build a PortfolioConfig with enable_margin=True and pass it to Portfolio(...)/add_portfolio(portfolio_config=...); the former post-construction update_config(enable_margin=True) toggle no longer rebuilds the leaf"
    - "Spot leaf (SimulatedCashAccount) has NO margin surface — spot tests assert structural absence (not hasattr 'locked_margin_total') instead of a 0 total"
    - "Liquidation MATH (_isolated_liq_price/_is_breached/_liquidation_penalty) is exercised on SimulatedMarginAccount (static methods); the _collect_breaches_over_prices / emission shell stays on PortfolioHandler"
    - "set_universe propagates only to accounts that exist when it runs; tests that create a portfolio AFTER set_universe re-propagate the universe down to the new account"

key-files:
  created: []
  modified:
    - tests/unit/portfolio/test_cash_manager.py
    - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py
    - tests/unit/portfolio/test_portfolio.py
    - tests/unit/portfolio/test_portfolio_margin.py
    - tests/unit/portfolio/test_liquidation.py
    - tests/unit/portfolio/test_carry.py
    - tests/unit/portfolio/test_realised_pnl_accumulator.py
    - tests/unit/portfolio/test_spot_oversell_guard.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - tests/unit/portfolio/test_state_storage.py
    - tests/unit/portfolio/test_portfolio_update.py
    - tests/unit/portfolio/test_cash_reservations.py
    - tests/unit/portfolio/test_on_fill_status_guard.py
    - tests/unit/portfolio/test_money_decimal.py
    - tests/unit/portfolio/test_update_config.py
    - tests/unit/order/test_order_manager.py
    - tests/unit/order/test_liquidation_reconcile.py
    - tests/unit/order/test_order_update_config.py
    - tests/unit/order/test_stop_limit_orders.py
    - tests/unit/order/test_order_handler.py
    - tests/unit/order/test_admission_rules.py
    - tests/unit/order/test_on_signal.py
    - tests/unit/order/test_sltp_policy.py
    - tests/unit/order/test_trailing_bracket.py
    - tests/unit/order/test_admission_snapshot.py
    - tests/unit/order/test_order_storage.py
    - tests/unit/order/test_expire_all_resting.py
    - tests/unit/core/test_portfolio_read_model.py
    - tests/unit/reporting/test_cash_operations.py
    - tests/integration/test_reservation_inertness.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_expire_non_cascade.py
    - tests/integration/test_pair_exit_safety.py
    - tests/integration/test_pair_flagship_snapshot.py
    - tests/integration/test_results_persist.py
    - tests/integration/test_universe_spans.py
    - tests/integration/storage/test_sql_portfolio_storage.py
    - tests/integration/storage/test_cached_sql_portfolio_storage.py

key-decisions:
  - "test_cash_manager.py keeps a SimulatedCashAccount `cm` fixture (cash-leaf contract, satisfies the artifact token) AND adds a SimulatedMarginAccount `mcm` fixture for the margin-only tests (lock/release/locked_margin_total/borrow_interest) — the margin surface lives only on the margin leaf after the split, so the same behaviors are tested on the correct leaf with zero coverage loss (T-01-13)"
  - "Margin portfolios are constructed with enable_margin config AT CONSTRUCTION, not toggled via update_config — the new production contract (01-03 D-03) selects the leaf at construction; the real backtest/run wiring already passes config at construction and never toggles enable_margin mid-flight"
  - "Spot-leaf 'no lock' is asserted structurally (not hasattr 'locked_margin_total') — a stronger guarantee than the prior `== 0` (the spot leaf cannot lock margin at all)"

patterns-established:
  - "Test consumers track moved production surfaces 1:1: cash_manager.* -> account.*; CashManager -> account leaves; PortfolioHandler liq math -> SimulatedMarginAccount static methods"

requirements-completed: []

# Metrics
duration: 26min
completed: 2026-06-30
---

# Phase 1 Plan 03b: Test-Consumer Ripple (unit + integration) Summary

**Migrated the unit + integration test suites onto the post-01-03 production API — every `portfolio.cash_manager.*` re-pointed to `portfolio.account.*`, both direct-`CashManager` modules retargeted to the `SimulatedCashAccount`/`SimulatedMarginAccount` leaves, every `CashOperation` import re-pointed to the `account/` barrel, and `user_id` stripped from every construction call-site/assertion — closing the unit/integration half of the test-consumer ripple with `tests/unit` + `tests/integration` green (1391 passed) and no assertions weakened.**

## Performance

- **Duration:** ~26 min
- **Tasks:** 3
- **Files modified:** 38 test files

## Accomplishments

- **Task 1 — receiver/import migration (`b869e50`):** re-pointed every `portfolio.cash_manager.<m>` to `portfolio.account.<m>` across 11 unit/integration files (balance, available_balance, reserved_balance, locked_margin_total, lock_margin, get_cash_operations, withdraw, get_locked_margin_for); adapted the two signature sites `reserve_cash(amount, desc, ref) -> reserve(ref, amount)` (test_state_storage, test_portfolio_update); re-pointed every `CashOperation` import from `cash.cash_manager` to the `itrader.portfolio_handler.account` barrel (test_cash_operations + both SQL storage tests). Residual-zero grep clean (T-01-12 mitigation).
- **Task 2 — direct-CashManager retarget (`6a7ec79`):** `test_cash_manager.py` now exercises `SimulatedCashAccount` (`cm`, the dedicated cash-leaf contract) plus a `SimulatedMarginAccount` (`mcm`) fixture for the margin-only tests; `test_wr04_lock_fits_buying_power.py` retargeted to `SimulatedMarginAccount`. All reserve/release call-sites adapted; CashOperation from the account barrel; 52 tests green with no coverage loss (T-01-13 mitigation).
- **Task 3 — user_id strip + margin-leaf construction (`88b76f9`):** dropped `user_id` from every `add_portfolio`/`Portfolio`/`PortfolioSpec` call-site (dominant leading-positional form + kwarg form), deleted the `assert portfolio.user_id` / `portfolio_dict["user_id"]` assertions + the `"user_id"` dict-key, renamed the `create_portfolio(user_id)` helper, and removed the `_USER_ID` constant. Migrated all margin fixtures to construct with `enable_margin` config at construction, re-pointed the moved liquidation math, and re-propagated the universe to late-created accounts. `tests/unit` + `tests/integration` green (1391 passed).

## Task Commits

1. **Task 1: Re-point cash_manager.* -> account.* + CashOperation imports** — `b869e50` (test)
2. **Task 2: Retarget direct-CashManager modules to the account leaves** — `6a7ec79` (test)
3. **Task 3: Strip user_id + migrate margin-leaf construction** — `88b76f9` (test)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Margin fixtures must construct the leaf with config — update_config(enable_margin) no longer rebuilds it**
- **Found during:** Tasks 2 & 3
- **Issue:** 01-03 (D-03) selects the account leaf at CONSTRUCTION (`SimulatedCashAccount` vs `SimulatedMarginAccount`). The existing margin fixtures created a spot portfolio and toggled `enable_margin=True` via `update_config`/`model_copy` AFTER construction — which leaves the account a `SimulatedCashAccount`, so every margin call (`lock_margin`, `assert_lock_fits_buying_power`, `accrue_borrow_interest`, `maintenance_margin`) raised `AttributeError`/returned 0. The real backtest/run wiring already passes config at construction and never toggles `enable_margin` mid-flight, so this is the faithful migration to the new contract — not a production change.
- **Fix:** Added a `_margin_config()` helper (`PortfolioConfig.model_validate(deep_merge(default, {enable_margin:True,...}))`) and constructed margin portfolios with it (`Portfolio(..., config=...)` / `add_portfolio(..., portfolio_config=...)`).
- **Files modified:** test_portfolio, test_portfolio_margin, test_realised_pnl_accumulator, test_carry, test_liquidation, test_liquidation_reconcile, test_portfolio_handler, test_wr04, test_pair_exit_safety, test_pair_flagship_snapshot.
- **Commits:** `6a7ec79`, `88b76f9`

**2. [Rule 3 - Blocking] Moved liquidation math + spot-leaf surface absence**
- **Found during:** Task 3
- **Issue:** 01-03 moved `_isolated_liq_price`/`_is_breached`/`_liquidation_penalty` from `PortfolioHandler` DOWN to `SimulatedMarginAccount`; `test_liquidation.py` still called them on the handler. Spot tests asserted `account.locked_margin_total == 0`, but the spot leaf has no such attribute.
- **Fix:** Re-pointed the static-method calls to `SimulatedMarginAccount` (kept `_collect_breaches_over_prices` on the handler shell); replaced the spot `locked_margin_total == 0` assertion with `not hasattr(account, "locked_margin_total")` (structural, stronger).
- **Files modified:** test_liquidation, test_portfolio.
- **Commit:** `88b76f9`

**3. [Rule 3 - Blocking] Re-propagate universe to accounts created after set_universe**
- **Found during:** Task 3
- **Issue:** The 01-03 math-pulldown made `set_universe` propagate the Universe to EXISTING margin accounts only. Liquidation tests call `set_universe` before `add_portfolio`, so the later-created account kept `_universe=None` → `AttributeError: 'NoneType' has no attribute 'instrument'`. Production adds portfolios before `set_universe` (documented Trap-4 wiring), so this is a test-ordering artifact.
- **Fix:** In the affected test helpers, re-propagate `handler._universe` down to the new account after creation.
- **Files modified:** test_liquidation, test_liquidation_reconcile.
- **Commit:** `88b76f9`

**4. [Rule 3 - Blocking] Under-enumerated files in the plan's file lists**
- **Found during:** Tasks 1 & 3
- **Issue:** Several files carrying positional `Portfolio(1, ...)` / `add_portfolio(1, ...)` (no literal `user_id` token, so invisible to the plan's `grep user_id` selector) were not enumerated: `test_cash_reservations.py`, `test_spot_oversell_guard.py`, `test_realised_pnl_accumulator.py`, and the `Portfolio(1, ...)` sites in `test_portfolio.py`. They broke under the new signatures.
- **Fix:** Stripped the leading positional user_id from those sites too (required for the suite-green success criterion).
- **Commits:** `b869e50`, `88b76f9`

## Issues Encountered

None beyond the auto-fixed items above. No production code, no e2e tests, and the byte-exact oracle were touched.

## Verification

- `poetry run pytest tests/unit -q` — **1304 passed**
- `poetry run pytest tests/unit tests/integration -q` — **1391 passed** (0 skipped; SQL storage tests ran green)
- `grep -rn "\.cash_manager\|cash\.cash_manager\|import CashManager\|CashManager(" tests/unit tests/integration` (excl. comments) — **ZERO**
- `grep -rn "user_id" tests/unit tests/integration` (excl. comments) — **ZERO**
- e2e untouched (`git diff --name-only` over `tests/e2e/` — none); owned by 01-03c
- Production untouched (no `itrader/` or `scripts/` edits)
- Oracle byte-exact still green (owned by 01-03): `tests/integration/test_backtest_oracle.py` — **3 passed**

## Threat Surface

- **T-01-12 (latent missed reference surfacing only at 01-05):** mitigated — residual-zero greps (`.cash_manager`, `user_id`) scoped to tests/unit + tests/integration are clean, and both suites are run green here, so 01-05 inherits no unit/integration debt.
- **T-01-13 (silent coverage loss on the test_cash_manager retarget):** mitigated — receivers/fixtures only re-pointed (CashManager -> SimulatedCashAccount + a SimulatedMarginAccount `mcm` fixture for the margin surface); all assertion values preserved; the file stays the dedicated cash-leaf contract test.
- No production/network/auth/schema surface introduced. No `## Threat Flags`.

## Known Stubs

None.

## Notes for downstream plans

- **01-03c (e2e half):** untouched here — the e2e suite is its sole owner (no file overlap).
- **01-05 (terminal gate):** the full `poetry run pytest tests` suite + the byte-exact re-confirmation runs there after 01-03b/01-03c. The unit + integration halves carry no remaining cash_manager/user_id/account-leaf debt.
- **New production contract surfaced (informational, not a defect):** `update_config(enable_margin=...)` does NOT rebuild the account leaf — leaf selection is construction-time only (01-03 D-03). Any future test/consumer must pass `enable_margin` in the constructor config.

## Self-Check: PASSED

- Files: `tests/unit/portfolio/test_cash_manager.py` present with the `SimulatedCashAccount` token; all 38 modified test files present on disk.
- Commits: `b869e50`, `6a7ec79`, `88b76f9` all FOUND in git log.
- Gates: `tests/unit` + `tests/integration` green (1391 passed); residual greps zero; e2e + production + oracle untouched.

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
