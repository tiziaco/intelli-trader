# Phase 02 — Deferred / Out-of-Scope Items (Execution Delta Log)

Items discovered during plan execution that are outside the executing plan's scope.
Per STATE.md policy, new issues go to COVERAGE-INDEX §E with owner approval — never
silently folded into the running plan.

## From Plan 02-04 (Decimal money + UUID entity retype)

### DEF-02-04-A — Golden oracle numeric drift after float→Decimal (numeric re-baseline)

- **Discovered during:** Plan 02-04, Task 2 (portfolio.cash → Decimal, transaction_manager
  round-trip removal).
- **What:** `test/test_integration/test_backtest_oracle.py::test_full_backtest_matches_frozen_oracle`
  fails. The behavioral oracle is fully preserved — 134 trades in both runs, and the
  identity key columns `_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]` plus
  `pair` are byte-identical. Only **numeric** columns drift by the expected float→Decimal
  precision shift:
  | column | max abs diff |
  |--------|--------------|
  | net_quantity | 1.4e-16 |
  | avg_bought | 5.8e-11 |
  | avg_price / avg_sold | 7.5e-6 |
  | realised_pnl | 7.9e-3 |
  | total_bought | 1.9e-2 |
  | total_sold | 2.7e-2 |
- **Why out of scope for 02-04:** `test_backtest_oracle.py` is NOT in plan 02-04's
  `files_modified`. The fix is **Pattern E** (split identity-EXACT from numeric-TOLERANT,
  `02-PATTERNS.md` §"Pattern E — D-15 oracle test tolerance"), which is assigned to a
  different plan. Additionally, the **numerical oracle re-baseline** is a controlled
  golden-master phase-boundary gate (CLAUDE.md: "the numerical oracle re-baselines at
  exactly two points — after M2, after M5") that requires owner approval; the executor
  must NOT overwrite `test/golden/trades.csv` or regenerate the golden silently.
- **Status:** Deferred to the Pattern E / post-M2 numeric re-baseline plan (owner-gated).
- **Not a regression of behavior:** trade timing, count, side, and pair are exactly
  preserved — this is precisely the intended M2a numeric improvement (exact Decimal money
  replacing accumulated float error).
