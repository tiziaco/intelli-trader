---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 03c
type: execute
wave: 4
depends_on: [01-02, 01-03]
files_modified:
  - tests/e2e/conftest.py
  - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
  - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
  - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
  - tests/e2e/levered_long/test_levered_long_scenario.py
  - tests/e2e/partial_cover/test_partial_cover_scenario.py
  - tests/e2e/short_carry/test_short_carry_scenario.py
  - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
  - tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py
  - tests/e2e/short_scale_in/test_short_scale_in_scenario.py
  - tests/e2e/trailing_long/test_trailing_long_scenario.py
  - tests/e2e/trailing_short/test_trailing_short_scenario.py
  - tests/e2e/admission/max_positions/scenario.py
  - tests/e2e/admission/re_entry/scenario.py
  - tests/e2e/admission/scale_in/scenario.py
  - tests/e2e/admission/scale_out/scenario.py
  - tests/e2e/cash/release_cancelled/scenario.py
  - tests/e2e/cash/release_refused/scenario.py
  - tests/e2e/cash/release_rejected/scenario.py
  - tests/e2e/cost/combined_roundtrip/scenario.py
  - tests/e2e/cost/fixed_slippage/scenario.py
  - tests/e2e/cost/limit_no_slip/scenario.py
  - tests/e2e/cost/linear_slippage/scenario.py
  - tests/e2e/cost/maker_taker/scenario.py
  - tests/e2e/cost/percent_fee/scenario.py
  - tests/e2e/matching/brackets/oco_lifecycle/scenario.py
  - tests/e2e/matching/brackets/stop_beats_limit/scenario.py
  - tests/e2e/matching/entries/limit_entry_crossval/scenario.py
  - tests/e2e/matching/entries/limit_gap_through/scenario.py
  - tests/e2e/matching/entries/limit_touch/scenario.py
  - tests/e2e/matching/entries/market_next_open/scenario.py
  - tests/e2e/matching/entries/stop_gap_down/scenario.py
  - tests/e2e/matching/entries/stop_gap_up/scenario.py
  - tests/e2e/matching/gaps/clean_through_limit/scenario.py
  - tests/e2e/matching/gaps/clean_through_stop/scenario.py
  - tests/e2e/matching/gaps/gap_past_both_legs/scenario.py
  - tests/e2e/matching/never_fill/scenario.py
  - tests/e2e/matching/operator/cancel/scenario.py
  - tests/e2e/matching/operator/modify_reprice/scenario.py
  - tests/e2e/matching/operator/modify_resize/scenario.py
  - tests/e2e/multi/contended_cash/scenario.py
  - tests/e2e/multi/fanout_portfolios/scenario.py
  - tests/e2e/multi/two_strategies/scenario.py
  - tests/e2e/multi/two_tickers/scenario.py
  - tests/e2e/robust/flat/scenario.py
  - tests/e2e/robust/losing/scenario.py
  - tests/e2e/robust/no_trade/scenario.py
  - tests/e2e/robust/sparse_bar/scenario.py
  - tests/e2e/robust/union_window/scenario.py
  - tests/e2e/sizing/fixed_quantity/scenario.py
  - tests/e2e/sizing/over_cash_reject/scenario.py
  - tests/e2e/sizing/risk_percent/scenario.py
  - tests/e2e/sltp/from_decision_held/scenario.py
  - tests/e2e/sltp/from_decision_sl_hit/scenario.py
  - tests/e2e/sltp/from_decision_tp_hit/scenario.py
  - tests/e2e/sltp/from_fill_held/scenario.py
  - tests/e2e/sltp/from_fill_sl_hit/scenario.py
  - tests/e2e/sltp/from_fill_tp_hit/scenario.py
  - tests/e2e/smoke/single_market_buy/scenario.py
autonomous: true
requirements: [ACCT-01, ACCT-04]
must_haves:
  truths:
    - "The e2e harness + the 10 e2e `test_*_scenario.py` files that read `portfolio.cash_manager.*` (incl. conftest.py:~372 `portfolio.cash_manager.get_cash_operations()`) are re-pointed to `portfolio.account.*`, closing the AttributeError 01-03 introduces — this is REQUIRED for the e2e suite to run green (ACCT-01)"
    - "The CashOperation import in the short_carry e2e scenario is re-pointed to the new barrel home `itrader.portfolio_handler.account` (ACCT-02)"
    - "The vestigial `user_id` is removed from the e2e harness PortfolioSpec dataclass definitions + every `PortfolioSpec(user_id=...)` construction across the 58 scenario/test_*_scenario files, keeping the test tree consistent with the production strip (ACCT-04). NOTE (verified): the e2e harness (conftest.py) does NOT forward user_id to production add_portfolio, so this strip is a consistency/grep-zero cleanup, not a green-blocker"
    - "01-03c is a Wave-4 peer of 01-03b with ZERO file overlap (e2e vs unit/integration) — both run in parallel and both gate into 01-05"
  artifacts:
    - path: "tests/e2e/conftest.py"
      provides: "e2e harness re-pointed off portfolio.cash_manager onto portfolio.account"
      contains: ".account."
  key_links:
    - from: "tests/e2e/conftest.py"
      to: "portfolio.account.get_cash_operations"
      via: "harness cash-ops read re-pointed from cash_manager to account"
      pattern: "account\\.get_cash_operations"
---

<objective>
Close the e2e half of the test-consumer ripple that 01-03 opens (peer of 01-03b; no file overlap →
parallel in Wave 4). Two migrations:

1. REQUIRED for green — re-point `portfolio.cash_manager.<m>` -> `portfolio.account.<m>` in the e2e
   harness (conftest.py:~372 `portfolio.cash_manager.get_cash_operations()`) and the 10
   `test_*_scenario.py` files that read margin/cash state off `.cash_manager` (forced_liq_long/short,
   levered_long(+_into_liquidation), partial_cover, short_carry, short_roundtrip, short_scale_in(+
   _partial_cover), trailing_long/short). Re-point the short_carry CashOperation import to the new
   `itrader.portfolio_handler.account` barrel home.

2. Consistency cleanup — remove the vestigial `user_id` from the e2e harness `PortfolioSpec` dataclass
   definitions and every `PortfolioSpec(user_id=...)` construction across the 58 scenario files. The
   e2e harness does NOT forward user_id to production add_portfolio (verified — conftest.py never reads
   spec.user_id), so this does not block green, but it keeps the test tree consistent with the
   production strip and satisfies the phase-wide `user_id`-gone invariant before the 01-05 gate.

Purpose: make the e2e suite green against the post-extraction production API and remove the dangling
user_id fixture field, so 01-05 can run the full suite under filterwarnings=[error].
Output: ~59 migrated e2e files (no production edits — production is 01-03).
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
<!-- Public account surface (from 01-02). Same 1:1 receiver renames as 01-03b. -->
portfolio.account.get_cash_operations(), .locked_margin_total, .lock_margin, .balance,
.available_balance, .reserved_balance. CashOperation lives in account/simulated.py, re-exported from
`itrader.portfolio_handler.account`.

<!-- e2e cash_manager touch-points (REQUIRED). -->
conftest.py:~372  build_cash_operations(portfolio.cash_manager.get_cash_operations())
  -> build_cash_operations(portfolio.account.get_cash_operations()).
The 10 test_*_scenario.py files each read one margin/cash attribute off `.cash_manager`
  (e.g. forced_liq_long reads .cash_manager.locked_margin_total) -> `.account.<same>`.
short_carry test_short_carry_scenario.py also imports CashOperation from cash.cash_manager
  -> re-point to `itrader.portfolio_handler.account`.

<!-- e2e user_id touch-points (consistency). -->
Each scenario.py defines a LOCAL harness `PortfolioSpec` dataclass (e.g. single_market_buy/scenario.py
  class PortfolioSpec with `user_id: int` field at ~114) and constructs `PortfolioSpec(user_id=1,
  name=..., cash=...)`. Remove the `user_id` dataclass field, the docstring mention, and the
  `user_id=...` kwarg from every construction. The harness (conftest.py) reads spec.name / spec.cash /
  spec.exchange only — NEVER spec.user_id — so dropping the field is safe.
single_market_buy/scenario.py has 4 user_id occurrences (docstring x2, field, construction);
  multi/fanout_portfolios/scenario.py has 2 (two specs); the rest have 1 each.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Re-point e2e cash_manager.* -> account.* (harness + scenario tests) + CashOperation import</name>
  <files>tests/e2e/conftest.py, tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py, tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py, tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py, tests/e2e/levered_long/test_levered_long_scenario.py, tests/e2e/partial_cover/test_partial_cover_scenario.py, tests/e2e/short_carry/test_short_carry_scenario.py, tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py, tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py, tests/e2e/short_scale_in/test_short_scale_in_scenario.py, tests/e2e/trailing_long/test_trailing_long_scenario.py, tests/e2e/trailing_short/test_trailing_short_scenario.py</files>
  <read_first>
    - tests/e2e/conftest.py (the harness — locate `portfolio.cash_manager.get_cash_operations()` at ~372)
    - itrader/portfolio_handler/account/simulated.py (the public account surface + CashOperation home)
    - Each test_*_scenario.py in <files> before editing (grep `\.cash_manager\|CashOperation` to find the single access each)
  </read_first>
  <action>Re-point every `portfolio.cash_manager.<method>` access to `portfolio.account.<method>` (1:1
  receiver rename — get_cash_operations, locked_margin_total, lock_margin, balance, available_balance,
  reserved_balance). In tests/e2e/conftest.py:~372 change
  `build_cash_operations(portfolio.cash_manager.get_cash_operations())` to
  `build_cash_operations(portfolio.account.get_cash_operations())`. In each of the 10
  test_*_scenario.py files re-point the single `.cash_manager.<attr>` read to `.account.<attr>`. In
  tests/e2e/short_carry/test_short_carry_scenario.py also re-point `from
  itrader.portfolio_handler.cash.cash_manager import CashOperation` -> `from
  itrader.portfolio_handler.account import CashOperation`. Read each file before editing; match
  indentation; change no assertion values (pure receiver/import migration). Docstring/comment mentions
  of `cash_manager.py:NNN` line citations are historical references — leave them (they are not code).</action>
  <verify>
    <automated>! grep -rln "\.cash_manager\.\|cash\.cash_manager import" tests/e2e/conftest.py tests/e2e/forced_liq_long tests/e2e/forced_liq_short tests/e2e/levered_long_into_liquidation tests/e2e/levered_long tests/e2e/partial_cover tests/e2e/short_carry tests/e2e/short_roundtrip tests/e2e/short_scale_in_partial_cover tests/e2e/short_scale_in tests/e2e/trailing_long tests/e2e/trailing_short && echo "no-residual-cash_manager-access"</automated>
  </verify>
  <acceptance_criteria>
    - conftest.py reads `portfolio.account.get_cash_operations()` (no `.cash_manager` attribute access remains in the harness)
    - All 10 test_*_scenario.py `.cash_manager.<attr>` reads are re-pointed to `.account.<attr>`
    - short_carry imports CashOperation from `itrader.portfolio_handler.account`
    - No `.cash_manager.` attribute access nor `cash.cash_manager import` remains in the listed files (grep marker prints)
    - No assertion values changed
  </acceptance_criteria>
  <done>The e2e harness + scenario tests read account state off portfolio.account; CashOperation import re-pointed.</done>
</task>

<task type="auto">
  <name>Task 2: Strip the vestigial user_id from e2e harness PortfolioSpec defs + constructions</name>
  <files>tests/e2e/admission/max_positions/scenario.py, tests/e2e/admission/re_entry/scenario.py, tests/e2e/admission/scale_in/scenario.py, tests/e2e/admission/scale_out/scenario.py, tests/e2e/cash/release_cancelled/scenario.py, tests/e2e/cash/release_refused/scenario.py, tests/e2e/cash/release_rejected/scenario.py, tests/e2e/cost/combined_roundtrip/scenario.py, tests/e2e/cost/fixed_slippage/scenario.py, tests/e2e/cost/limit_no_slip/scenario.py, tests/e2e/cost/linear_slippage/scenario.py, tests/e2e/cost/maker_taker/scenario.py, tests/e2e/cost/percent_fee/scenario.py, tests/e2e/matching/brackets/oco_lifecycle/scenario.py, tests/e2e/matching/brackets/stop_beats_limit/scenario.py, tests/e2e/matching/entries/limit_entry_crossval/scenario.py, tests/e2e/matching/entries/limit_gap_through/scenario.py, tests/e2e/matching/entries/limit_touch/scenario.py, tests/e2e/matching/entries/market_next_open/scenario.py, tests/e2e/matching/entries/stop_gap_down/scenario.py, tests/e2e/matching/entries/stop_gap_up/scenario.py, tests/e2e/matching/gaps/clean_through_limit/scenario.py, tests/e2e/matching/gaps/clean_through_stop/scenario.py, tests/e2e/matching/gaps/gap_past_both_legs/scenario.py, tests/e2e/matching/never_fill/scenario.py, tests/e2e/matching/operator/cancel/scenario.py, tests/e2e/matching/operator/modify_reprice/scenario.py, tests/e2e/matching/operator/modify_resize/scenario.py, tests/e2e/multi/contended_cash/scenario.py, tests/e2e/multi/fanout_portfolios/scenario.py, tests/e2e/multi/two_strategies/scenario.py, tests/e2e/multi/two_tickers/scenario.py, tests/e2e/robust/flat/scenario.py, tests/e2e/robust/losing/scenario.py, tests/e2e/robust/no_trade/scenario.py, tests/e2e/robust/sparse_bar/scenario.py, tests/e2e/robust/union_window/scenario.py, tests/e2e/sizing/fixed_quantity/scenario.py, tests/e2e/sizing/over_cash_reject/scenario.py, tests/e2e/sizing/risk_percent/scenario.py, tests/e2e/sltp/from_decision_held/scenario.py, tests/e2e/sltp/from_decision_sl_hit/scenario.py, tests/e2e/sltp/from_decision_tp_hit/scenario.py, tests/e2e/sltp/from_fill_held/scenario.py, tests/e2e/sltp/from_fill_sl_hit/scenario.py, tests/e2e/sltp/from_fill_tp_hit/scenario.py, tests/e2e/smoke/single_market_buy/scenario.py, tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py, tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py, tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py, tests/e2e/levered_long/test_levered_long_scenario.py, tests/e2e/partial_cover/test_partial_cover_scenario.py, tests/e2e/short_carry/test_short_carry_scenario.py, tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py, tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py, tests/e2e/short_scale_in/test_short_scale_in_scenario.py, tests/e2e/trailing_long/test_trailing_long_scenario.py, tests/e2e/trailing_short/test_trailing_short_scenario.py</files>
  <read_first>
    - tests/e2e/smoke/single_market_buy/scenario.py (the reference harness spec — `class PortfolioSpec` with `user_id: int` at ~114, docstring at ~106/125, construction at ~154)
    - tests/e2e/multi/fanout_portfolios/scenario.py (two PortfolioSpec constructions)
    - tests/e2e/conftest.py (confirm the harness never reads spec.user_id — only spec.name/cash/exchange)
  </read_first>
  <action>Remove the vestigial `user_id` from the e2e harness `PortfolioSpec`. In each file that defines
  a local `PortfolioSpec` dataclass with a `user_id: int` field (the scenario.py files), delete the
  `user_id` field declaration and any docstring mention of it. In every `PortfolioSpec(user_id=1,
  ...)` / `PortfolioSpec(user_id=N, ...)` construction (all listed files, including
  multi/fanout_portfolios which has two), drop the `user_id=` kwarg, keeping name/cash/(exchange). The
  harness (conftest.py) consumes spec.name/spec.cash/spec.exchange only — it NEVER reads spec.user_id —
  so removing the field is behavior-preserving (the e2e oracle/golden artifacts are keyed on
  PortfolioSpec.name, never user_id). Read each file before editing; match indentation; change no other
  spec field or assertion. This is the consistency cleanup that makes `user_id` grep-zero across the
  whole test tree.</action>
  <verify>
    <automated>! grep -rn "user_id" tests/e2e/ | grep -v '^\s*#' && echo "no-residual-user_id-e2e"</automated>
  </verify>
  <acceptance_criteria>
    - No `user_id` token remains anywhere under tests/e2e/ (grep marker prints; comments excluded)
    - The local PortfolioSpec dataclasses no longer declare a `user_id` field
    - Every PortfolioSpec construction dropped the `user_id=` kwarg; name/cash/exchange preserved
    - No spec field or assertion value other than user_id changed
  </acceptance_criteria>
  <done>The e2e harness PortfolioSpec no longer carries user_id; user_id is grep-zero across tests/e2e.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Test-only migration of e2e scenarios + harness to track the 01-03 production API change. No network/IO/auth surface; no production code touched. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-14 | Tampering | A missed e2e `.cash_manager` read left as a latent AttributeError surfacing only in the 01-05 full-suite gate | mitigate | Residual-zero grep scoped to tests/e2e is the Task-1 gate; the harness + all 10 scenario readers are enumerated in files_modified. |
| T-01-15 | Tampering | Dropping the user_id field changes e2e golden attribution | mitigate (false alarm) | The harness keys golden artifacts on PortfolioSpec.name and never reads spec.user_id (verified in conftest.py); the field is vestigial, so removal is behavior-preserving. The 01-05 byte-exact + e2e suite gate confirms. |
| T-01-SC | Tampering | pip installs | accept | No package installs — test-file edits only. |
</threat_model>

<verification>
- `! grep -rln "\.cash_manager\." tests/e2e | grep -v '#'` returns nothing (harness + scenarios re-pointed)
- `! grep -rn "user_id" tests/e2e | grep -v '#'` returns nothing
- `! grep -rn "cash\.cash_manager import" tests/e2e` returns nothing (CashOperation re-pointed)
- e2e collection is clean; the full e2e + byte-exact suite gate is 01-05
</verification>

<success_criteria>
- The e2e harness + all 10 scenario readers reference portfolio.account (no `.cash_manager` access remains)
- short_carry CashOperation import re-pointed to the account/ barrel
- user_id removed from every e2e PortfolioSpec dataclass + construction (grep-zero across tests/e2e)
- e2e collects clean; no e2e debt left for the 01-05 terminal gate
</success_criteria>

<output>
Create `.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-03c-SUMMARY.md` when done.
</output>
