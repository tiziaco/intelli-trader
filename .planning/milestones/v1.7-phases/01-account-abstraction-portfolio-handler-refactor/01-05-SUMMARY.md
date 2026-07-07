---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 05
subsystem: verification
tags: [terminal-gate, oracle, byte-exact, determinism, mypy-strict, no-float-money, no-orphan, perf, ACCT-03]

# Dependency graph
requires:
  - phase: 01-03
    provides: Portfolio/PortfolioHandler delegate balance/margin/liq truth to the Account leaf; CashManager deleted; user_id stripped (production)
  - phase: 01-03b
    provides: unit + integration test-consumer migration (cash_manager -> account, user_id strip, account-leaf-at-construction)
  - phase: 01-03c
    provides: e2e test-consumer migration (cash_manager -> account, user_id strip, margin-leaf-at-construction)
  - phase: 01-04
    provides: TradingInterface deleted (removed a quantity: float live-path leak)
provides:
  - "Terminal gate PASSED (ACCT-03): the Account extraction (01-02..01-04 + 01-03b/01-03c) is proven behavior-preserving — oracle byte-exact, deterministic, mypy --strict clean, full suite green, no float-money introduced, no orphaned consumer reference, no W1 perf regression"
affects: [02-okx-connector]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verification-only terminal gate: no production code changed except one docstring hygiene reword to clear the no-orphan grep"

key-files:
  created: []
  modified:
    - itrader/reporting/cash_operations.py

key-decisions:
  - "The W1 single-symbol SMA_MACD oracle run loop wall is ~1-2s, comfortably under the 15.7s v1.5 baseline band — being faster is not a regression. The refactor is pure code-motion behind the FROZEN PortfolioReadModel seam and the backtest path imports no async/connector code, so no hot-path cost was added."
  - "All float() casts under portfolio_handler/account are serialization/logging/exception-edge casts (to_dict / get_balance_info -> Dict[str,float], structured-log dicts, InsufficientFundsError detail fields), moved byte-for-byte from CashManager in 01-02 — NO new float-money introduced; the money math stays Decimal end-to-end."

patterns-established:
  - "Stale docstring references to deleted modules are reworded (not code-changed) to clear the literal no-orphan grep gate — same hygiene pattern as 01-03 dev #4 / 01-04 dev #1"

requirements-completed: [ACCT-03]

# Metrics
duration: 3min
completed: 2026-06-30
---

# Phase 1 Plan 05: Terminal Gate — Account Extraction Behavior-Preservation Summary

**The Account extraction (plans 01-02 → 01-04 + the 01-03b/01-03c test-consumer migration) is proven behavior-preserving: the SMA_MACD backtest oracle re-confirms BYTE-EXACT (134 trades / final equity 46189.87730727451, check_exact=True), a double-run is byte-identical (determinism), `mypy --strict itrader` is clean over 214 files, the full `filterwarnings=[error]` suite is green (1463 passed), no float-for-money was introduced (only serialization-edge casts remain), no orphaned cash_manager/user_id reference survives, and the W1 oracle run wall (~1-2s) is well under the 15.7s v1.5 baseline — the phase universal gate (ACCT-03) is satisfied.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-30T21:54:25Z
- **Tasks:** 2
- **Files modified:** 1 (docstring hygiene only)

## Gate Results

### Task 1 — Oracle byte-exact + determinism double-run

- **`poetry run pytest tests/integration/test_backtest_oracle.py -q`** — **3 passed** (`test_oracle_behavioral_identity`, `test_oracle_numeric_values`, + the storage record test).
- **Recorded oracle values:** `trade_count = 134`, `final_equity = 46189.87730727451`, `final_cash = 46189.87730727451`, `total_realised_pnl = 36189.87730727451` — the fresh `output/summary.json` is byte-identical to the FROZEN `tests/golden/summary.json` (diff clean). Metrics block also exact (cagr 0.19910032815485068, max_drawdown -0.538256823181407, profit_factor 1.291149869385797, sharpe 0.6583614133806527, sortino 1.038504038796619, win_rate 0.3656716417910448).
- **Determinism double-run:** ran `scripts/run_backtest.py` twice; `diff` of `output/trades.csv`, `output/equity.csv`, and `output/summary.json` across the two runs — **all three IDENTICAL**. The run output also matches the frozen golden summary exactly.
- **No golden mutation** — `tests/golden/` was read-only; the byte-exact value was the immovable ceiling and it held without any change (T-01-09 mitigated).

### Task 2 — mypy --strict + full suite + no-orphan + float audit + perf

- **`poetry run mypy --strict itrader`** — **Success: no issues found in 214 source files** (exit 0). Deleting TradingInterface (01-04) removed a `quantity: float` live-path leak, so the no-float-money posture is stronger.
- **`poetry run pytest tests -q`** — **1463 passed in 13.73s** under `filterwarnings=["error"]` (unit + integration + e2e + golden oracle all green; no orphaned cash_manager/user_id reference failed late — T-01-16 mitigated).
- **No-orphan grep** `grep -rn "\.cash_manager\|user_id" tests/ itrader/ | grep -v '#'` — **ZERO** after one docstring hygiene reword (see Deviations). 01-03b + 01-03c closed every test reference; the only residual was a stale prose docstring in the reporting serializer.
- **Float-money audit** `grep -rnE "Decimal\(float|float\(" itrader/portfolio_handler/account itrader/connectors` — returns **only serialization-edge casts** (`to_dict` / `get_balance_info` returning `Dict[str, float]`, structured-log detail dicts, `InsufficientFundsError` detail fields). All moved byte-for-byte from CashManager in 01-02; the money math stays Decimal end-to-end. `itrader/connectors` does not exist yet (no connector code on the backtest path — confirms hot-path inertness). **No new float-money introduced.**
- **W1 perf no-regression:** the SMA_MACD oracle run-loop wall is **~1-2s**, comfortably under the 15.7s v1.5 frozen baseline band (T-01-10 mitigated). The refactor is pure code-motion behind the FROZEN `PortfolioReadModel` seam and the backtest path imports no async/connector code, so no accidental hot-path cost was added. (The 15.7s baseline reflects the broader benchmark harness; the single-symbol oracle run is well within band — being faster is not a regression.)

## Task Commits

This is a verification-only plan — no per-task source commits. One Rule 1 hygiene commit was required to clear the plan's own no-orphan grep gate:

1. **Docstring hygiene (clears the `.cash_manager` no-orphan grep)** — `80b2ab3` (docs)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Hygiene] Stale `cash_manager` docstring references in the reporting serializer tripped the no-orphan grep**
- **Found during:** Task 2 (no-orphan grep)
- **Issue:** `itrader/reporting/cash_operations.py` carried three stale prose references to the now-deleted `cash_manager.py`: a module-docstring line citing `(cash_manager.py:34)`, one citing `(admission audit wall-clock — cash_manager.py:409,441)`, and a `build_cash_operations` docstring line "the harness passes ``portfolio.cash_manager.get_cash_operations()``". The last one matched the plan's `grep -rn "\.cash_manager\|user_id"` acceptance gate and would have failed it; the first two cited a deleted file. All are docstring prose — no code path touched.
- **Fix:** Reworded the deleted-file citations to "the account leaf" and re-pointed the harness prose to `portfolio.account.get_cash_operations()` (matches the 01-03c harness migration). Docstring-only, no behavior change; `import` verified, oracle + suite unaffected.
- **Files modified:** `itrader/reporting/cash_operations.py`
- **Commit:** `80b2ab3`

This is the same hygiene class as 01-03 deviation #4 and 01-04 deviation #1 (deleted-symbol prose references reworded to clear a literal grep gate). No scope creep.

## Issues Encountered

None. Every gate passed on the first run; the only adjustment was the docstring hygiene reword above.

## Threat Surface

- **T-01-09 (silent oracle drift / golden mutated to fit a regressed run):** mitigated — `check_exact=True` against the FROZEN `tests/golden/`; the oracle held byte-exact (134 / 46189.87730727451) with zero golden mutation.
- **T-01-10 (hot-path perf regression from code-motion):** mitigated — W1 oracle run ~1-2s, well under the 15.7s baseline; backtest path imports no async/connector code.
- **T-01-16 (residual orphaned cash_manager/user_id reference passing collection but failing a single test late):** mitigated — full-suite gate green (1463 passed) + the explicit no-orphan grep returns ZERO after the one docstring reword.
- **T-01-SC (pip installs):** N/A — no package installs; pure verification.
- No new external/network/auth/schema surface introduced. No `## Threat Flags`.

## Known Stubs

None.

## Notes for downstream plans

- **Phase 1 is locked:** the Account extraction is behavior-preserving and the SMA_MACD backtest path is re-confirmed byte-exact. No live code may have weakened the backtest hot path — the universal v1.7 gate (oracle byte-exact + no W1/W2 regression) holds after the refactor.
- **Phase 2 (OKX Connector):** the `itrader/connectors` package does not exist yet — the no-float-money discipline (`to_money` at the ccxt edge) and the hot-path inertness gate (no async/connector import on the backtest path) carry forward as the recurring milestone gate.

## Self-Check: PASSED

- File: `itrader/reporting/cash_operations.py` present on disk with the reworded docstrings (no `.cash_manager` token; import OK).
- Commit: `80b2ab3` FOUND in git log.
- Gates: oracle 3 passed (134 / 46189.87730727451, golden diff clean); determinism double-run byte-identical; `mypy --strict` 0 issues / 214 files; full suite 1463 passed under filterwarnings=[error]; no-orphan grep ZERO; float audit edge-only; W1 ~1-2s within the 15.7s baseline.

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
