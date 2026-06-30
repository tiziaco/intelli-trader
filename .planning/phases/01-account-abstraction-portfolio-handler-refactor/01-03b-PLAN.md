---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 03b
type: execute
wave: 4
depends_on: [01-02, 01-03]
files_modified:
  - tests/unit/portfolio/test_portfolio.py
  - tests/unit/portfolio/test_carry.py
  - tests/unit/portfolio/test_state_storage.py
  - tests/unit/portfolio/test_liquidation.py
  - tests/unit/portfolio/test_portfolio_margin.py
  - tests/unit/portfolio/test_cash_reservations.py
  - tests/unit/portfolio/test_portfolio_update.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/portfolio/test_cash_manager.py
  - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py
  - tests/unit/portfolio/test_money_decimal.py
  - tests/unit/portfolio/test_on_fill_status_guard.py
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
autonomous: true
requirements: [ACCT-01, ACCT-02, ACCT-04]
must_haves:
  truths:
    - "Every unit/integration test accessing `portfolio.cash_manager.*` is re-pointed to the equivalent `portfolio.account.*` public surface, so the AttributeError introduced by 01-03 (Portfolio.cash_manager -> Portfolio.account) is fully closed across tests/unit + tests/integration (ACCT-01)"
    - "The two test modules that import + instantiate `CashManager` directly (test_cash_manager.py, test_wr04_lock_fits_buying_power.py) are retargeted to the account leaves (SimulatedCashAccount / SimulatedMarginAccount), so they collect after cash_manager.py is deleted (ACCT-02)"
    - "Every CashOperation import in unit/integration tests is re-pointed from the deleted `cash.cash_manager` to the new barrel home `itrader.portfolio_handler.account` (ACCT-02)"
    - "The `user_id` strip is rippled through every unit/integration `add_portfolio(...)` call-site — including the dominant POSITIONAL form `add_portfolio(1, name, exchange, cash)` where user_id is the dropped first arg — plus `Portfolio(...)`/`PortfolioSpec(...)` kwargs and the `assert portfolio.user_id`/`portfolio_dict['user_id']` assertions, so no TypeError/AttributeError/KeyError remains (ACCT-04)"
    - "tests/unit collects+passes and tests/integration collects (DB-backed SQL storage tests may skip without PostgreSQL); the terminal full-suite + byte-exact gate is 01-05"
  artifacts:
    - path: "tests/unit/portfolio/test_cash_manager.py"
      provides: "Retargeted cash-leaf test exercising SimulatedCashAccount (replaces direct CashManager test)"
      contains: "SimulatedCashAccount"
  key_links:
    - from: "tests/unit/portfolio/test_portfolio.py"
      to: "itrader.portfolio_handler.account"
      via: "portfolio.cash_manager.* -> portfolio.account.* receiver migration"
      pattern: "\\.account\\."
    - from: "tests/integration/storage/test_sql_portfolio_storage.py"
      to: "itrader.portfolio_handler.account"
      via: "CashOperation import re-pointed to the barrel home"
      pattern: "from itrader.portfolio_handler.account import"
---

<objective>
Close the unit + integration half of the test-consumer ripple that 01-03 opens. When 01-03 replaces
`Portfolio.cash_manager` with `Portfolio.account`, deletes `cash_manager.py`, and strips `user_id` from
the `add_portfolio`/`PortfolioSpec` contract, it orphans a large body of test references that 01-03's
own (production-scoped) verify never sees. This plan migrates the **unit + integration** tests; the
**e2e** half is its Wave-4 peer 01-03c (no file overlap → both run in parallel). The terminal
full-suite + byte-exact gate is 01-05, which depends on both.

Three mechanical migrations, each verified by a residual-zero grep:
1. `portfolio.cash_manager.<m>` -> `portfolio.account.<m>` (balance, available_balance, reserved_balance,
   locked_margin_total, lock_margin, get_cash_operations, withdraw are 1:1 receiver renames;
   `reserve_cash(amount, desc, ref)` -> `reserve(ref, amount)` and `release_reservation(ref)` ->
   `release(ref)` are the only signature adaptations).
2. The two modules that import + construct `CashManager` directly are retargeted to the account leaves;
   every `CashOperation` import is re-pointed to `itrader.portfolio_handler.account`.
3. `user_id` is dropped from every `add_portfolio(...)` call-site — CRITICAL: most pass user_id as the
   FIRST POSITIONAL arg (`add_portfolio(1, "p", "default", 10000)` -> `add_portfolio("p", "default",
   10000)`), a few as `user_id=1` kwargs — plus `Portfolio(...)`/`PortfolioSpec(...)` kwargs and the
   `assert portfolio.user_id`/`portfolio_dict['user_id']` assertions.

Purpose: make tests/unit + tests/integration green against the post-extraction production API so the
01-05 terminal gate can run the full suite under filterwarnings=[error].
Output: ~36 migrated unit/integration test files (no production edits — production is 01-03).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-CONTEXT.md
@.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-PATTERNS.md
@.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-02-SUMMARY.md
@.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-03-SUMMARY.md

<interfaces>
<!-- Public account surface the tests migrate ONTO (from plan 01-02 account/simulated.py). -->
Portfolio.account is a SimulatedCashAccount (spot) or SimulatedMarginAccount (margin).
Cash leaf (both): balance, available_balance, reserved_balance, deposit, withdraw,
  process_transaction_cash_flow, apply_fill_cash_flow, get_cash_operations, get_balance_info,
  validate_balance_consistency, assert_funds_invariant; reserve(order_id, amount) / release(order_id).
Margin leaf (SimulatedMarginAccount only): locked_margin_total, get_locked_margin_for, lock_margin,
  release_margin, accrue_borrow_interest, assert_lock_fits_buying_power, maintenance_margin,
  margin_ratio. CashOperation entity now lives in account/simulated.py, re-exported from
  `itrader.portfolio_handler.account`.

<!-- Signature adaptations (the ONLY non-1:1 receiver renames). -->
OLD: cash_manager.reserve_cash(amount, description, reference_id)  NEW: account.reserve(order_id=reference_id, amount)
     -> e.g. reserve_cash(Decimal("500"), "test reserve", "ref-1")  becomes  reserve("ref-1", Decimal("500"))
OLD: cash_manager.release_reservation(reference_id)                NEW: account.release(reference_id)

<!-- add_portfolio signature change (01-03 Task 2/3): user_id was the FIRST positional param. -->
OLD def add_portfolio(self, user_id, name, exchange, cash, portfolio_config=None)
NEW def add_portfolio(self, name, exchange, cash, portfolio_config=None)
  POSITIONAL call-sites: add_portfolio(1, "p", "default", 10000)  -> add_portfolio("p", "default", 10000)
                         add_portfolio(i + 1, f"p{i}", ...)        -> add_portfolio(f"p{i}", ...)
  KWARG call-sites:      add_portfolio(user_id=1, name=..., ...)   -> drop the user_id= kwarg
  Assertions:            assert portfolio.user_id == 1  and  portfolio_dict["user_id"] == 1  -> DELETE
  In test_portfolio_handler.py: the `_USER_ID` constant + its uses, the `add_portfolio(_USER_ID, ...)`
  positional sites, and the user_id field in the get_info dict-keys assertion (~575) all drop user_id.

<!-- File set by migration type (verify with grep before editing each). -->
cash_manager.* receiver renames: test_portfolio.py, test_carry.py, test_state_storage.py,
  test_liquidation.py, test_portfolio_margin.py, test_cash_reservations.py, test_portfolio_update.py,
  test_portfolio_handler.py (withdraw), test_order_manager.py, test_liquidation_reconcile.py,
  test_cash_operations.py, test_reservation_inertness.py, storage/test_sql_portfolio_storage.py,
  storage/test_cached_sql_portfolio_storage.py.
CashManager direct instantiation (retarget): test_cash_manager.py, test_wr04_lock_fits_buying_power.py.
CashOperation import re-point: test_cash_operations.py, test_cash_manager.py, test_portfolio.py,
  test_carry.py, storage/test_sql_portfolio_storage.py, storage/test_cached_sql_portfolio_storage.py.
user_id strip (add_portfolio + Portfolio/PortfolioSpec + assertions): test_order_update_config.py,
  test_stop_limit_orders.py, test_order_handler.py, test_admission_rules.py, test_order_manager.py,
  test_on_signal.py, test_sltp_policy.py, test_trailing_bracket.py, test_admission_snapshot.py,
  test_liquidation_reconcile.py, test_order_storage.py, test_expire_all_resting.py,
  test_portfolio_read_model.py, test_on_fill_status_guard.py, test_portfolio_handler.py,
  test_carry.py, test_liquidation.py, test_money_decimal.py, test_state_storage.py,
  test_update_config.py, and integration: test_backtest_smoke.py, test_expire_non_cascade.py,
  test_pair_exit_safety.py, test_pair_flagship_snapshot.py, test_reservation_inertness.py,
  test_results_persist.py, test_universe_spans.py.
(test_backtest_oracle.py user_id is owned by 01-03 — NOT touched here.)
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migrate portfolio.cash_manager.* -> portfolio.account.* + re-point CashOperation imports</name>
  <files>tests/unit/portfolio/test_portfolio.py, tests/unit/portfolio/test_carry.py, tests/unit/portfolio/test_state_storage.py, tests/unit/portfolio/test_liquidation.py, tests/unit/portfolio/test_portfolio_margin.py, tests/unit/portfolio/test_cash_reservations.py, tests/unit/portfolio/test_portfolio_update.py, tests/unit/portfolio/test_portfolio_handler.py, tests/unit/order/test_order_manager.py, tests/unit/order/test_liquidation_reconcile.py, tests/unit/reporting/test_cash_operations.py, tests/integration/test_reservation_inertness.py, tests/integration/storage/test_sql_portfolio_storage.py, tests/integration/storage/test_cached_sql_portfolio_storage.py</files>
  <read_first>
    - itrader/portfolio_handler/account/simulated.py (the public account surface the tests migrate onto — note reserve/release signatures, CashOperation home)
    - tests/unit/portfolio/test_portfolio.py (19 cash_manager refs — the bulk receiver renames)
    - tests/unit/portfolio/test_state_storage.py (reserve_cash signature site at ~293)
    - tests/unit/portfolio/test_portfolio_update.py (reserve_cash signature site at ~93)
    - Each file in <files> before editing it (grep `\.cash_manager\|CashOperation` to locate every site)
  </read_first>
  <action>For every file listed in <files>, re-point each `portfolio.cash_manager.<method>` (and any
  `pf.cash_manager.<method>` / `self.portfolio.cash_manager.<method>`) access to the equivalent
  `<...>.account.<method>` on the public account surface. The 1:1 receiver renames are: balance,
  available_balance, reserved_balance, locked_margin_total, lock_margin, get_cash_operations, withdraw,
  get_locked_margin_for. The ONLY signature adaptations: `reserve_cash(amount, description,
  reference_id)` -> `reserve(reference_id, amount)` (drop the description; order_id is the old
  reference_id) at tests/unit/portfolio/test_state_storage.py:~293 and
  tests/unit/portfolio/test_portfolio_update.py:~93; and `release_reservation(ref)` -> `release(ref)`.
  Separately, re-point every `from itrader.portfolio_handler.cash.cash_manager import CashOperation`
  to `from itrader.portfolio_handler.account import CashOperation` (test_cash_operations.py,
  test_portfolio.py, test_carry.py, both storage tests). Read each file before editing; match its
  indentation. Do NOT change any test assertion values — this is a pure receiver/import migration.</action>
  <verify>
    <automated>! grep -rn "\.cash_manager\b\|from .*cash_manager import\|cash\.cash_manager" tests/unit/portfolio/test_portfolio.py tests/unit/portfolio/test_carry.py tests/unit/portfolio/test_state_storage.py tests/unit/portfolio/test_liquidation.py tests/unit/portfolio/test_portfolio_margin.py tests/unit/portfolio/test_cash_reservations.py tests/unit/portfolio/test_portfolio_update.py tests/unit/order/test_order_manager.py tests/unit/order/test_liquidation_reconcile.py tests/unit/reporting/test_cash_operations.py tests/integration/test_reservation_inertness.py tests/integration/storage/test_sql_portfolio_storage.py tests/integration/storage/test_cached_sql_portfolio_storage.py | grep -v '^\s*#' && echo "no-residual-cash_manager"</automated>
  </verify>
  <acceptance_criteria>
    - No `.cash_manager` attribute access remains in any of the listed files (grep above prints the success marker)
    - reserve_cash/release_reservation sites are adapted to `account.reserve(order_id, amount)` / `account.release(order_id)`
    - Every CashOperation import points at `itrader.portfolio_handler.account`
    - `poetry run pytest tests/unit/portfolio/test_portfolio.py tests/unit/portfolio/test_carry.py tests/unit/portfolio/test_state_storage.py -q` passes
    - No assertion values changed (diff is receiver/import-only)
  </acceptance_criteria>
  <done>All unit/integration cash_manager accesses + CashOperation imports point at the account surface; no residual `.cash_manager`.</done>
</task>

<task type="auto">
  <name>Task 2: Retarget the two direct-CashManager test modules to the account leaves</name>
  <files>tests/unit/portfolio/test_cash_manager.py, tests/unit/portfolio/test_wr04_lock_fits_buying_power.py</files>
  <read_first>
    - tests/unit/portfolio/test_cash_manager.py (imports CashManager + CashOperation; fixture `cm`; reserve_cash/release_reservation call-sites listed in 01-PATTERNS analog)
    - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py (imports CashManager; exercises lock-fits-buying-power → margin surface)
    - itrader/portfolio_handler/account/simulated.py (SimulatedCashAccount + SimulatedMarginAccount constructors, reserve/release, lock_margin, assert_lock_fits_buying_power)
  </read_first>
  <action>Retarget tests/unit/portfolio/test_cash_manager.py to exercise `SimulatedCashAccount` instead
  of the deleted `CashManager`: change the import to `from itrader.portfolio_handler.account import
  SimulatedCashAccount, CashOperation`, construct the fixture `cm` as a `SimulatedCashAccount(...)`
  with the same constructor args (portfolio, initial_cash), and adapt the reserve/release call-sites —
  `cm.reserve_cash(amount, description, reference_id)` -> `cm.reserve(reference_id, amount)` and
  `cm.release_reservation(ref)` -> `cm.release(ref)` (the file has many of these; the underlying
  mechanics are identical so the assertion values stay). Keep the test as the dedicated cash-leaf
  contract test (optionally note in a module docstring that it now covers SimulatedCashAccount). Retarget
  tests/unit/portfolio/test_wr04_lock_fits_buying_power.py to `SimulatedMarginAccount` (lock-fits-buying-power
  is a margin-leaf method): change the CashManager import to `SimulatedMarginAccount` and construct the
  margin account; keep assertions. Read both files fully before editing; match indentation. Do NOT
  weaken or delete coverage — the same behaviors are tested against the new leaf.</action>
  <verify>
    <automated>! grep -rn "import CashManager\|CashManager(\|cash\.cash_manager\|reserve_cash\|release_reservation" tests/unit/portfolio/test_cash_manager.py tests/unit/portfolio/test_wr04_lock_fits_buying_power.py | grep -v '^\s*#' && poetry run pytest tests/unit/portfolio/test_cash_manager.py tests/unit/portfolio/test_wr04_lock_fits_buying_power.py -q</automated>
  </verify>
  <acceptance_criteria>
    - test_cash_manager.py imports + constructs SimulatedCashAccount (no `CashManager` symbol remains)
    - test_wr04_lock_fits_buying_power.py imports + constructs SimulatedMarginAccount
    - All reserve_cash/release_reservation calls are adapted to reserve(order_id, amount)/release(order_id)
    - CashOperation (if imported) comes from `itrader.portfolio_handler.account`
    - `poetry run pytest tests/unit/portfolio/test_cash_manager.py tests/unit/portfolio/test_wr04_lock_fits_buying_power.py -q` passes; coverage of the same behaviors is preserved
  </acceptance_criteria>
  <done>The two direct-CashManager modules exercise the account leaves and collect/pass after cash_manager.py is deleted.</done>
</task>

<task type="auto">
  <name>Task 3: Strip user_id from unit/integration add_portfolio + Portfolio/PortfolioSpec call-sites + assertions</name>
  <files>tests/unit/order/test_order_update_config.py, tests/unit/order/test_stop_limit_orders.py, tests/unit/order/test_order_handler.py, tests/unit/order/test_admission_rules.py, tests/unit/order/test_order_manager.py, tests/unit/order/test_on_signal.py, tests/unit/order/test_sltp_policy.py, tests/unit/order/test_trailing_bracket.py, tests/unit/order/test_admission_snapshot.py, tests/unit/order/test_liquidation_reconcile.py, tests/unit/order/test_order_storage.py, tests/unit/order/test_expire_all_resting.py, tests/unit/core/test_portfolio_read_model.py, tests/unit/portfolio/test_on_fill_status_guard.py, tests/unit/portfolio/test_portfolio_handler.py, tests/unit/portfolio/test_carry.py, tests/unit/portfolio/test_liquidation.py, tests/unit/portfolio/test_money_decimal.py, tests/unit/portfolio/test_state_storage.py, tests/unit/portfolio/test_update_config.py, tests/integration/test_backtest_smoke.py, tests/integration/test_expire_non_cascade.py, tests/integration/test_pair_exit_safety.py, tests/integration/test_pair_flagship_snapshot.py, tests/integration/test_results_persist.py, tests/integration/test_universe_spans.py</files>
  <read_first>
    - itrader/portfolio_handler/portfolio_handler.py (the NEW add_portfolio signature after 01-03 — name, exchange, cash, portfolio_config=None)
    - tests/unit/portfolio/test_portfolio_handler.py (the `_USER_ID` constant + the user_id assertions at ~94 and the dict-keys assertion at ~575/583 — the heaviest file)
    - Each file before editing (grep `add_portfolio(\|Portfolio(\|PortfolioSpec(\|user_id` to locate every site)
  </read_first>
  <action>For every file in <files>, drop `user_id` from the production-construction call-sites now that
  01-03 removed it from the `add_portfolio`/`Portfolio`/`PortfolioSpec` signatures. user_id was the
  FIRST POSITIONAL parameter of add_portfolio, so the dominant fix is removing the leading positional
  arg: `add_portfolio(1, "p", "default", 10000)` -> `add_portfolio("p", "default", 10000)`;
  `add_portfolio(i + 1, f"p{i}", "default", 100000)` -> `add_portfolio(f"p{i}", "default", 100000)`;
  `add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)` -> `add_portfolio(_PORTFOLIO_NAME,
  _EXCHANGE, _CASH)`. For the kwarg form (`add_portfolio(user_id=1, name=..., ...)` at
  test_liquidation_reconcile.py:~77 and similar), drop the `user_id=` kwarg. Drop `user_id` from any
  `Portfolio(...)` / `PortfolioSpec(...)` construction in these tests. DELETE the assertions that read
  the removed attribute: `assert portfolio.user_id == 1` (test_portfolio_handler.py:~94) and the
  `portfolio_dict["user_id"] == 1` assertion + the `"user_id"` entry in the expected dict-keys set
  (~575/583). In test_portfolio_handler.py, also remove the now-unused `_USER_ID` constant. Read each
  file before editing; preserve indentation; change NO other test logic or assertion values.</action>
  <verify>
    <automated>! grep -rn "user_id" tests/unit/order tests/unit/core tests/unit/portfolio tests/integration/test_backtest_smoke.py tests/integration/test_expire_non_cascade.py tests/integration/test_pair_exit_safety.py tests/integration/test_pair_flagship_snapshot.py tests/integration/test_results_persist.py tests/integration/test_universe_spans.py tests/integration/test_reservation_inertness.py | grep -v '^\s*#' && echo "no-residual-user_id"</automated>
  </verify>
  <acceptance_criteria>
    - No `user_id` token remains in any listed unit/integration file (grep prints the success marker; comments excluded)
    - All add_portfolio positional call-sites dropped the leading user_id arg; kwarg sites dropped `user_id=`
    - The `assert portfolio.user_id` and `portfolio_dict["user_id"]` assertions are deleted; `_USER_ID` constant removed where unused
    - `poetry run pytest tests/unit/order tests/unit/core tests/unit/portfolio -q` passes
  </acceptance_criteria>
  <done>user_id is gone from all unit/integration production-construction call-sites + assertions; the unit suite is green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Test-only migration. Edits test files to track the 01-03 production API change. No network/IO/auth surface; no production code touched. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-12 | Tampering | A missed `.cash_manager` / `user_id` reference left as a latent AttributeError/TypeError that only surfaces in the 01-05 full-suite gate | mitigate | Residual-zero greps scoped to tests/unit + tests/integration are the per-task gate; the migrated unit suite is run green here so 01-05 has no unit/integration debt. |
| T-01-13 | Tampering | Silent coverage loss when retargeting test_cash_manager.py (deleting hard cases instead of adapting receivers) | mitigate | Retarget receivers only (reserve_cash->reserve, CashManager->SimulatedCashAccount); assertion values preserved; the file stays the dedicated cash-leaf contract test. |
| T-01-SC | Tampering | pip installs | accept | No package installs — test-file edits only. |
</threat_model>

<verification>
- `! grep -rn "\.cash_manager\|cash\.cash_manager\|import CashManager" tests/unit tests/integration | grep -v '#'` returns nothing
- `! grep -rn "user_id" tests/unit tests/integration | grep -v '#'` returns nothing (test_backtest_oracle.py handled by 01-03)
- `poetry run pytest tests/unit -q` passes green under filterwarnings=[error]
- tests/integration collects (DB-backed storage tests may skip without PostgreSQL); the full byte-exact + suite gate is 01-05
</verification>

<success_criteria>
- All unit/integration cash_manager accesses re-pointed to the account surface; no residual `.cash_manager`
- The two direct-CashManager modules retargeted to SimulatedCashAccount/SimulatedMarginAccount with preserved coverage
- All CashOperation imports re-pointed to the account/ barrel
- user_id stripped from every unit/integration production-construction call-site + assertions
- tests/unit green; tests/integration collects — no unit/integration debt left for 01-05
</success_criteria>

<output>
Create `.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-03b-SUMMARY.md` when done.
</output>
