---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 03c
subsystem: tests
tags: [account, cash, margin, user-id-strip, test-migration, consumer-ripple, e2e, construction-time-leaf]

# Dependency graph
requires:
  - phase: 01-02
    provides: SimulatedCashAccount / SimulatedMarginAccount leaves + CashOperation barrel home
  - phase: 01-03
    provides: Portfolio.cash_manager -> Portfolio.account, CashManager deleted, user_id stripped (production + PortfolioSpec), account-leaf-at-construction (D-03)
provides:
  - tests/e2e migrated onto the post-extraction production API (account surface, account-leaf-at-construction, user_id-free); e2e suite green (72 passed)
  - The e2e half of the 01-03 test-consumer ripple fully closed (no debt left for the 01-05 terminal gate)
affects: [01-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "e2e margin scenarios construct the margin leaf at CONSTRUCTION (01-03 D-03): pass portfolio_config=PortfolioConfig.model_validate(deep_merge(get_portfolio_preset('default').model_dump(), {trading_rules:{enable_margin:True}})) to add_portfolio; the existing post-construction config swap still refines the remaining trading_rules (read dynamically) but no longer rebuilds the leaf"
    - "The account leaf caches NOTHING from config at construction (verified: SimulatedMarginAccount.__init__ only sets _universe=None/logger) — so a MINIMAL enable_margin=True construction config selects the margin leaf; max_leverage/allow_short_selling stay in the post-construction swap (admission/order/account read portfolio.config dynamically)"
    - "e2e add_portfolio is called BEFORE the three set_universe seams in every _build_*_system helper, so the margin account already exists when portfolio_handler.set_universe runs and is propagated to — NO universe re-propagation needed here (unlike the unit liquidation tests in 01-03b that called set_universe first)"

key-files:
  created: []
  modified:
    - tests/e2e/conftest.py
    - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
    - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
    - tests/e2e/levered_long/test_levered_long_scenario.py
    - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
    - tests/e2e/partial_cover/test_partial_cover_scenario.py
    - tests/e2e/short_carry/test_short_carry_scenario.py
    - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
    - tests/e2e/short_scale_in/test_short_scale_in_scenario.py
    - tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py
    - tests/e2e/trailing_long/test_trailing_long_scenario.py
    - tests/e2e/trailing_short/test_trailing_short_scenario.py
    - tests/e2e/smoke/single_market_buy/scenario.py
    - "tests/e2e/**/scenario.py (47 harness scenario files — user_id kwarg dropped from PortfolioSpec construction)"

key-decisions:
  - "MINIMAL enable_margin=True construction config + KEEP the post-construction config swap (lowest-risk faithful migration): the only bug 01-03 introduced for these scenarios is leaf SELECTION; the account caches no leverage/short config at construction, so a minimal enable_margin config picks the SimulatedMarginAccount and the existing post-construction swap continues to configure max_leverage/allow_short_selling (read dynamically by admission/order/account). No tuned margin arithmetic touched."
  - "Plan's 'CashOperation import from cash.cash_manager' re-point in short_carry was a NO-OP — short_carry imports CashOperationType from itrader.core.enums.portfolio (unaffected, not deleted); there is no CashOperation import from cash.cash_manager anywhere in tests/e2e (grep-zero)."
  - "Plan framing 'user_id strip is consistency-only, not a green-blocker' was only true for the conftest harness path + the single_market_buy LOCAL PortfolioSpec; the 47 shared-import scenario.py and the 11 test_*_scenario.py call the PRODUCTION PortfolioSpec/add_portfolio (both already user_id-free after 01-03), so their user_id constructions were TypeErrors — green-blockers. Work is identical; the strip was required for green."

patterns-established:
  - "e2e consumers track moved production surfaces 1:1: portfolio.cash_manager.* -> portfolio.account.*; margin scenarios construct the leaf via enable_margin config at add_portfolio time"

requirements-completed: [ACCT-01, ACCT-04]

# Metrics
duration: 5min
completed: 2026-06-30
---

# Phase 1 Plan 03c: Test-Consumer Ripple (e2e) Summary

**Migrated the e2e suite onto the post-01-03 production API — the harness + 9 margin `test_*_scenario.py` re-pointed `portfolio.cash_manager.*` to `portfolio.account.*`, `user_id` stripped grep-zero across all 59 e2e files (PortfolioSpec constructions, the local single_market_buy dataclass, and the 11 production `add_portfolio` calls), and the 10 margin scenarios re-wired to construct their `SimulatedMarginAccount` leaf at CONSTRUCTION via an `enable_margin` `portfolio_config` (01-03 D-03) — closing the e2e half of the test-consumer ripple with the full e2e suite green (72 passed) and no assertions weakened.**

## Performance

- **Duration:** ~5 min
- **Tasks:** 2
- **Files modified:** 59 e2e files

## Accomplishments

- **Task 1 — receiver migration (`d955b31`):** re-pointed `conftest.py:372` `build_cash_operations(portfolio.cash_manager.get_cash_operations())` to `portfolio.account.get_cash_operations()`, and the 9 margin `test_*_scenario.py` `cash = portfolio.cash_manager` reads to `cash = portfolio.account` (the snapshot helpers then read `.balance` / `.available_balance` / `.locked_margin_total` / `.get_cash_operations()` off the account leaf). Residual-zero grep clean (T-01-14 mitigation). Pure receiver migration — no assertion values changed.
- **Task 2 — user_id strip + margin-leaf construction (`7dd4cb5`):** dropped `user_id` from all 58 `PortfolioSpec(...)` constructions (sed, mechanical), removed the `user_id` field + two docstring mentions from the local `single_market_buy` `PortfolioSpec`/`ScenarioSpec`, dropped `user_id` from the 11 production `add_portfolio(...)` calls, and re-wired the 10 margin scenarios to pass `portfolio_config` with `enable_margin=True` at construction (Rule 3 deviation — see below). `user_id` grep-zero across `tests/e2e`; e2e suite green.

## Task Commits

1. **Task 1: Re-point e2e cash_manager.* -> account.* (harness + 9 scenario tests)** — `d955b31` (test)
2. **Task 2: Strip user_id + construct margin leaf at construction** — `7dd4cb5` (test)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Margin scenarios must construct the leaf with enable_margin config — the post-construction `portfolio.config = model_copy(enable_margin=True)` toggle no longer rebuilds it**
- **Found during:** Task 1 (discovered) / Task 2 (fixed)
- **Issue:** 01-03 (D-03) selects the account leaf at CONSTRUCTION. The 10 margin `test_*_scenario.py` build a spot portfolio via `add_portfolio(...)` then toggle `enable_margin=True` AFTER construction with `portfolio.config = portfolio.config.model_copy(...)`. After 01-03 that leaves the account a `SimulatedCashAccount` with no margin surface, so the re-pointed `cash.locked_margin_total` reads (and the short/levered settlement paths that call `lock_margin`/borrow-carry) would `AttributeError`. Exactly the sibling 01-03b finding cited in the objective.
- **Fix:** pass `portfolio_config=PortfolioConfig.model_validate(deep_merge(get_portfolio_preset("default").model_dump(), {"trading_rules": {"enable_margin": True}}))` to `add_portfolio` so the leaf is a `SimulatedMarginAccount`; added `from itrader.config import PortfolioConfig, deep_merge, get_portfolio_preset` to each margin file. KEPT the post-construction config swap (it still refines max_leverage/allow_short_selling, which the account/admission/order read dynamically — verified the account caches nothing at construction), minimizing risk to the tuned margin arithmetic. No universe re-propagation needed (e2e helpers call `add_portfolio` before `set_universe`).
- **Files modified:** the 10 margin `test_*_scenario.py` (forced_liq_long/short, levered_long(+_into_liquidation), partial_cover, short_carry, short_roundtrip, short_scale_in(+_partial_cover), trailing_short).
- **Commit:** `7dd4cb5`

**2. [Rule 1 - Plan no-op] short_carry CashOperation import re-point does not apply**
- **Found during:** Task 1
- **Issue:** The plan directed re-pointing `from itrader.portfolio_handler.cash.cash_manager import CashOperation` in short_carry. No such import exists — short_carry imports `CashOperationType` from `itrader.core.enums.portfolio` (a different, undeleted symbol). `grep "cash.cash_manager import"` over tests/e2e is zero.
- **Fix:** none required (no-op); the `CashOperationType` import is correct and left unchanged.
- **Commit:** n/a

**3. [Rule 3 - Blocking] user_id strip was a green-blocker (not consistency-only) for the production-spec consumers**
- **Found during:** Task 2
- **Issue:** The plan classified the user_id strip as a non-green-blocking consistency cleanup, asserting each scenario.py defines a LOCAL PortfolioSpec. In fact only `single_market_buy` defines a local one; the other 47 scenario.py import the PRODUCTION `PortfolioSpec` (via `tests/e2e/scenario_spec.py`, which re-exports `itrader.trading_system.system_spec.PortfolioSpec`), and the 11 `test_*_scenario.py` call production `add_portfolio` — both already had `user_id` removed in 01-03, so the `user_id=...` constructions were `TypeError`s (green-blockers). The required work is identical; recorded for accuracy.
- **Fix:** dropped `user_id` from every construction (sed for PortfolioSpec; manual Edit for the local dataclass + the production add_portfolio calls).
- **Commit:** `7dd4cb5`

## Issues Encountered

None beyond the auto-fixed items above. No production code, no unit/integration tests, and the byte-exact oracle were touched.

## Verification

- `poetry run pytest tests/e2e -q` — **72 passed in 1.42s** (filterwarnings=["error"] in effect; collection clean)
- `grep -rln "\.cash_manager\." tests/e2e` — **ZERO**
- `grep -rn "cash\.cash_manager import" tests/e2e` — **ZERO**
- `grep -rn "user_id" tests/e2e` — **ZERO**
- Production untouched: `git diff --name-only` over both task commits is entirely under `tests/e2e/` (no `itrader/`, `scripts/`, or `test_backtest_oracle` edits)
- Margin leaf wired: forced_liq_long/short, levered_long(+_into_liquidation), partial_cover, short_carry, short_roundtrip, short_scale_in(+_partial_cover), trailing_short all pass — their `.account.locked_margin_total` reads and short/levered settlement paths exercise the `SimulatedMarginAccount` leaf, proving construction-time selection works

## Threat Surface

- **T-01-14 (latent missed e2e `.cash_manager` read surfacing only at 01-05):** mitigated — residual-zero greps (`.cash_manager`, `cash.cash_manager import`, `user_id`) over tests/e2e are clean and the full e2e suite is run green here, so 01-05 inherits no e2e debt.
- **T-01-15 (dropping user_id changes e2e golden attribution):** mitigated (false alarm confirmed) — the harness keys artifacts on `PortfolioSpec.name` and never reads `spec.user_id` (conftest grep-zero); removal is behavior-preserving (72 passed unchanged).
- No production/network/auth/schema surface introduced. No `## Threat Flags`.

## Known Stubs

None.

## Notes for downstream plans

- **01-05 (terminal gate):** the full `poetry run pytest tests` suite + the byte-exact re-confirmation run there after 01-03b/01-03c. The e2e half carries no remaining cash_manager/user_id/account-leaf debt.
- **Construction-time leaf contract (reinforced):** any future e2e margin scenario must pass `enable_margin` in the `add_portfolio` `portfolio_config` — the post-construction `update_config`/`model_copy(enable_margin=...)` toggle does NOT rebuild the leaf (01-03 D-03). The account caches no leverage/short config at construction, so a minimal `enable_margin=True` construction config plus the existing post-construction swap is sufficient.

## Self-Check: PASSED

- Files: `tests/e2e/conftest.py` present with `portfolio.account.get_cash_operations()`; all 59 modified e2e files present on disk.
- Commits: `d955b31`, `7dd4cb5` both present in git log.
- Gates: e2e green (72 passed); residual greps (`.cash_manager`, `cash.cash_manager import`, `user_id`) all zero; production + oracle untouched.

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
