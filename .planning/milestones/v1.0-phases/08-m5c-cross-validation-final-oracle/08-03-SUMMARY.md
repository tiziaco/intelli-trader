---
phase: 08-m5c-cross-validation-final-oracle
plan: 03
subsystem: testing
tags: [golden-oracle, re-freeze, decimal, determinism, cross-validation-baseline, D-07, D-08, D-11, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 01
    provides: "Portfolio.total_* money properties retyped to Decimal with Decimal-native aggregation (the result-bearing arithmetic that no longer accumulates float round-off)"
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 02
    provides: "mypy --strict fan-out sweep + documented Decimal->float serialization boundary; make backtest proven end-to-end against the 08-01 Decimal numbers"
provides:
  - "Settled, owner-approved golden oracle re-frozen to the clean Decimal numbers — tests/golden/{trades.csv,equity.csv,summary.json} are the locked cross-validation baseline for 08-04+"
  - "tests/golden/REFREEZE-M5C-DECIMAL.md — named expected-diff note attributing every shifted value to Decimal precision (no residual), owner-approved at the D-08/D-11 blocking checkpoint"
  - "Run-path integration oracle test green against the settled set — the previously sanctioned D-08 numeric design-failure (test_oracle_numeric_values) is now CLOSED"
  - "D-07 gate satisfied: iTrader's numbers are clean and frozen FIRST, so cross-validation never misattributes float-rounding divergence to a reference engine"
affects: [08-04-cross-validation-harness, 08-08-conditional-bugfix-refreeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Phase 6/7 hybrid re-freeze discipline applied to the Decimal cleanup: named expected-diff note + owner sign-off + note/goldens/assertions land as ONE atomic commit (D-21)"
    - "Re-freeze by copying the deterministically-regenerated output/* over tests/golden/* — no hand-editing of frozen artifacts; the oracle test re-locks EXACT automatically via its golden-derived numeric-column mechanic"

key-files:
  created:
    - "tests/golden/REFREEZE-M5C-DECIMAL.md - named expected-diff re-freeze note for the golden-path Decimal cleanup (branch a, SHIFT)"
  modified:
    - "tests/golden/equity.csv - re-frozen: 19/3076 total_equity points + 8 derived total_pnl shifted (max abs 1.019e-10, max rel 1.003e-14); all other columns + timestamp grid byte-identical"
    - "tests/golden/summary.json - re-frozen: max_drawdown/sharpe/sortino each moved ~1 ULP (1e-16); cagr/profit_factor/win_rate + all headline money byte-exact"

key-decisions:
  - "BRANCH (a) SHIFT (precision-only), owner APPROVED at the D-08/D-11 blocking checkpoint (typed 'approved', 2026-06-08): the Decimal cleanup moved 19/3076 equity points and 3 equity-derived ratio metrics by last-bit float-vs-Decimal precision, with trades.csv BYTE-IDENTICAL (134 trades, no structure change) and headline money byte-exact. Re-frozen to the clean values."
  - "trades.csv was NOT modified (byte-identical to the prior golden) — proving the 08-01 validator Decimal retype was admit/reject-inert. Only equity.csv + summary.json carried the precision shift; only those two were re-frozen."
  - "No oracle test code changed: test_backtest_oracle.py derives its numeric columns dynamically from the golden header and asserts EXACT, so the re-frozen goldens re-lock the test automatically (Pitfall 6 satisfied without an assertion edit)."

patterns-established:
  - "Decimal-cleanup re-freeze: when a float->Decimal retype is result-changing only via last-bit precision, the expected-diff note attributes every moved number to the single arithmetic mechanism and confirms zero trade-structure change + zero unexplained residual before owner sign-off."

requirements-completed: [M5-10]

# Metrics
duration: 13min
completed: 2026-06-08
---

# Phase 8 Plan 03: M5c Decimal Oracle Re-freeze Summary

**Regenerated the deterministic oracle against the clean post-08-01/08-02 Decimal numbers, measured the exact precision-only diff vs the frozen golden (trades.csv byte-identical / 134 trades; headline money byte-exact; 19/3076 equity points + 3 equity-derived ratio metrics moved ~1 ULP), got owner sign-off at the D-08/D-11 blocking checkpoint, and re-froze `tests/golden/{equity.csv,summary.json}` with an attributed `REFREEZE-M5C-DECIMAL.md` note — settling the clean, owner-blessed cross-validation baseline (D-07 gate) and closing the sanctioned D-08 oracle numeric design-failure.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-06-08T14:08Z (continuation agent, post-checkpoint resume)
- **Completed:** 2026-06-08T14:20Z
- **Tasks:** 3 (Task 1 measurement re-derived/verified; Task 2 sign-off recorded; Task 3 re-freeze committed)
- **Files modified:** 3 (1 created note + 2 re-frozen goldens)

## Accomplishments

- **Re-derived the deterministic diff (Task 1).** `make backtest` exits 0, writes all three `output/*` artifacts; a second run is byte-identical (determinism preserved under the Decimal cleanup). Diff vs frozen golden:
  - **trades.csv: BYTE-IDENTICAL** — 134 trades, all identities/quantities/fills/PnL/slippage columns unchanged (the validator retype was admit/reject-inert).
  - **Headline money byte-exact (delta 0.0):** final_equity / final_cash = 46189.87730727451, total_realised_pnl = 36189.87730727451, starting_cash = 10000.0.
  - **equity.csv:** total_equity differs in 19/3076 rows (max abs 1.019e-10, max rel 1.003e-14), total_pnl in 8 rows; timestamp grid + cash_balance/positions_value/unrealized_pnl/realized_pnl/open_positions_count/portfolio_return all byte-identical.
  - **summary.json metrics:** max_drawdown +1.110e-16, sharpe -6.661e-16, sortino -6.661e-16 (each ~1 ULP); cagr / profit_factor / win_rate unchanged.
  - **Branch determined: (a) SHIFT** (precision-only). Trade count 134 and equity points 3076 both confirmed unchanged (no STOP/root-cause trigger).
- **Recorded owner sign-off (Task 2).** Owner approved the D-08/D-11 blocking checkpoint ("approved"). The shift is fully attributable to Decimal precision (no trade-structure change, no unexplained residual) → authorized the re-freeze.
- **Settled the golden set (Task 3).** Authored `tests/golden/REFREEZE-M5C-DECIMAL.md` in the precedent format (WHAT changed / Old-vs-new headline table / expected-diff attribution / run config D-09 / determinism / scope note), copied the regenerated clean `output/{equity.csv,summary.json}` over the goldens (trades.csv needed no copy — byte-identical), and committed note + goldens as ONE atomic commit (D-21).
- **Oracle test green against the settled set.** `tests/integration/test_backtest_oracle.py` — both `test_oracle_behavioral_identity` and `test_oracle_numeric_values` PASS. The latter was the sanctioned D-08 design-failure handed forward by 08-01/08-02; it is now CLOSED.

## Task Commits

1. **Task 1 (regenerate + deterministic before/after diff):** no commit — measurement only (`output/*` is gitignored; `tests/golden/*` untouched in this task, per plan).
2. **Task 2 (owner sign-off = approved):** no commit — checkpoint sign-off recorded in this summary + the re-freeze note status line.
3. **Task 3 (re-freeze, atomic):** `fa2d9bf` (feat) — `REFREEZE-M5C-DECIMAL.md` + re-frozen `equity.csv` + `summary.json`.
4. **Plan metadata:** final docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `tests/golden/REFREEZE-M5C-DECIMAL.md` (created) — named expected-diff re-freeze note; owner-APPROVED status line, old-vs-new headline table, single-mechanism Decimal-precision attribution (no residual), D-09 run config, double-run determinism, M5c scope note pointing 08-04+ at these clean numbers.
- `tests/golden/equity.csv` (modified) — re-frozen to the clean Decimal values: 19/3076 `total_equity` points + 8 derived `total_pnl` points settle on a different 10th `%.10f` decimal; everything else byte-identical.
- `tests/golden/summary.json` (modified) — re-frozen: `metrics.max_drawdown`/`sharpe`/`sortino` moved ~1 ULP; all headline money + `cagr`/`profit_factor`/`win_rate` byte-exact.
- `tests/golden/trades.csv` (UNCHANGED) — byte-identical to the prior golden; explicitly NOT re-frozen.

## Old vs New — Headline Numbers (re-frozen)

| Metric | Old golden (M5b) | New (M5c Decimal) | Delta |
|---|---|---|---|
| Trade count | 134 | 134 | 0 |
| Final equity / cash | 46189.87730727451 | 46189.87730727451 | 0.0 (byte-exact) |
| Total realised PnL | 36189.87730727451 | 36189.87730727451 | 0.0 (byte-exact) |
| Equity points | 3076 | 3076 | 0 |
| metrics.cagr | 0.19910032815485068 | 0.19910032815485068 | 0.0 |
| metrics.max_drawdown | -0.5382568231814071 | -0.538256823181407 | +1.110e-16 |
| metrics.profit_factor | 1.291149869385797 | 1.291149869385797 | 0.0 |
| metrics.sharpe | 0.6583614133806533 | 0.6583614133806527 | -6.661e-16 |
| metrics.sortino | 1.0385040387966196 | 1.038504038796619 | -6.661e-16 |
| metrics.win_rate | 0.3656716417910448 | 0.3656716417910448 | 0.0 |

## Decisions Made

- **Branch (a) SHIFT, precision-only, owner-approved.** The diff is exactly one mechanism: the equity aggregate is now summed in Decimal and coerced to float once at the serialization boundary, instead of accumulating IEEE-754 round-off across ~3076 bars through the old `float` Portfolio properties. Trades.csv byte-identical proves no trade-structure change; the only moved numbers are 19 equity points (+8 derived) and the 3 equity-derived ratio metrics. No unexplained residual → approved as the new clean baseline.
- **Only equity.csv + summary.json re-frozen** — trades.csv was byte-identical and deliberately left untouched (the re-freeze is minimal; only what shifted moved).
- **No oracle test code edited** — the test's `_trade_numeric` / `_equity_numeric` column lists are derived from the golden header and compared EXACT, so re-freezing the goldens re-locks the assertions automatically (Pitfall 6 satisfied without a hand-edit).

## Deviations from Plan

None — plan executed as written (branch a). Owner approved at the blocking checkpoint; the re-freeze, note, and (auto-relocked) oracle assertions landed as one atomic commit per D-21.

## Verification

- `make backtest` — exit 0, all three `output/*` written; double-run byte-identical (determinism confirmed).
- `poetry run pytest tests/integration/test_backtest_oracle.py -v` — 2 passed (behavioral identity + numeric values) against the settled golden set.
- trade_count = 134 and equity points = 3076 confirmed unchanged (precision-only, no structure change).

## Handoff to 08-04+

- `tests/golden/{trades.csv,equity.csv,summary.json}` + `REFREEZE-M5C-DECIMAL.md` are the **locked, owner-blessed cross-validation baseline** (D-11). The D-07 gate is satisfied: iTrader's numbers are clean and frozen FIRST.
- The headline reconciliation targets for 08-04 (D-04 metric set): final_equity 46189.87730727451, trade_count 134, cagr 0.19910032815485068, max_drawdown -0.538256823181407, profit_factor 1.291149869385797, sharpe 0.6583614133806527, sortino 1.038504038796619, win_rate 0.3656716417910448.
- A further **conditional** bug-fix re-freeze (08-08) may follow ONLY if cross-validation traces a genuine iTrader defect (D-05); otherwise this is the final oracle.

## Self-Check: PASSED

- Files: `tests/golden/REFREEZE-M5C-DECIMAL.md`, `tests/golden/equity.csv`, `tests/golden/summary.json`, `.planning/phases/08-m5c-cross-validation-final-oracle/08-03-SUMMARY.md` — all FOUND on disk.
- Commit: `fa2d9bf` (Task 3 re-freeze) — verified present in git history.
- Oracle test: `test_backtest_oracle.py` 2 passed (numeric design-failure CLOSED).
- Scope guard: trades.csv unchanged (byte-identical); only equity.csv + summary.json re-frozen; no source code modified in this plan.

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*
