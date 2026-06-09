---
phase: 04-e2e-harness-framework
plan: 01
subsystem: reporting
tags: [reporting, serialization, oracle, refactor, cleanup, FL-03, D-16]
requires:
  - itrader.reporting.frames (build_trade_log, build_equity_curve, TRADE_COLUMNS, EQUITY_COLUMNS)
  - itrader.reporting.metrics (sharpe, sortino, cagr, max_drawdown, profit_factor, win_rate, compute_returns)
provides:
  - itrader.reporting.summary (attach_slippage, build_metrics_block, build_summary, FLOAT_FORMAT, SLIPPAGE_COLUMNS)
affects:
  - scripts/run_backtest.py
  - tests/integration/test_backtest_oracle.py (oracle-dark gate — unchanged, still GREEN)
  - "future: e2e harness plans (the shared serialization seam they consume)"
tech-stack:
  added: []
  patterns:
    - "Verbatim relocation (D-16): function bodies moved character-identical; only closed-over constants become keyword params"
    - "Pure reporting module: pandas + stdlib + metrics formulas only, duck-typed portfolio/trades, zero handler imports"
key-files:
  created:
    - itrader/reporting/summary.py
  modified:
    - scripts/run_backtest.py
    - tests/unit/core/test_enums.py
decisions:
  - "D-16: summary/metrics/slippage assembly is the single shared serialization path — oracle generator and the future e2e harness import ONE module so they cannot drift"
  - "build_summary is the ONLY signature change: the five closed-over pins (ticker/timeframe/start_date/end_date/starting_cash) became keyword-only params"
  - "build_metrics_block return annotated dict[str, float] and build_summary dict[str, Any] (strict-mypy requirement; the originals in scripts/ were unannotated and out of mypy scope)"
metrics:
  duration: ~14 min
  completed: 2026-06-09
  tasks: 3
  files: 3
---

# Phase 04 Plan 01: Shared Serialization Assembly (D-16) + FL-03 Cleanup Summary

Extracted the summary/metrics/slippage serialization assembly out of `scripts/run_backtest.py` into a new shared `itrader/reporting/summary.py` (D-16) as a verbatim, oracle-dark relocation, and removed the dead Wave-0 `pytest.skip` in `test_enums.py` (FL-03).

## What Was Built

- **`itrader/reporting/summary.py` (new):** Houses `attach_slippage`, `build_metrics_block`, `build_summary` with bodies character-identical to the `run_backtest.py` originals, plus the two byte-load-bearing module constants `FLOAT_FORMAT = "%.10f"` and `SLIPPAGE_COLUMNS = ["slippage_entry", "slippage_exit"]`. The module is pure (pandas + stdlib + `itrader.reporting.metrics` only), duck-typed, zero handler imports, and `mypy --strict` clean. `build_summary`'s five previously-closed-over pins are now keyword-only params: `build_summary(portfolio, trades, *, ticker, timeframe, start_date, end_date, starting_cash)`.
- **`scripts/run_backtest.py` (slimmed):** Deletes the three local function defs and the duplicated `FLOAT_FORMAT`/`SLIPPAGE_COLUMNS`/now-unused `pandas`/metrics imports; imports the assembly from `itrader.reporting.summary`; passes its pins explicitly at the `build_summary` call site. All serialization (`to_csv`/`json.dump`) and the pinned-constant block stay in the script.
- **`tests/unit/core/test_enums.py` (FL-03):** Removed the Wave-0 `_fill_status_or_skip` helper (both the `importorskip` and the dead `if fill_status is None: pytest.skip(...)` branch); `FillStatus` is now imported directly and the two assertions run against the real enum. Stale Wave-0 docstring refreshed.

## How It Was Verified

- **Oracle-dark proof gate:** `poetry run python scripts/run_backtest.py` regenerates the BTCUSD oracle; `tests/integration/test_backtest_oracle.py` is GREEN (2 passed) — the BTCUSD golden run is byte-identical (trade log, equity curve, summary, metrics block all exact). The extraction changed zero oracle bytes.
- **FL-03:** `tests/unit/core/test_enums.py` — 2 passed, 0 skips (`-rs` shows no skip markers).
- **No regression:** full suite 734 passed, 0 failures, 0 skips.
- **Strict typing:** `mypy itrader` clean across all 130 source files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added type annotations to `summary.py` for mypy --strict**
- **Found during:** Task 1
- **Issue:** The original functions in `scripts/run_backtest.py` were unannotated (scripts/ is outside `files = ["itrader"]` mypy scope). Once relocated into `itrader/reporting/summary.py` they ARE in scope and `mypy --strict` flagged 9 errors (missing annotations on the three top-level functions, the three nested helpers in `attach_slippage`, and bare `dict` returns).
- **Fix:** Added signature annotations only — top-level functions typed `(equity: Any, trades: Any)` etc.; nested helpers `decision_close`/`entry_fill_price`/`exit_fill_price` annotated `(... : Any) -> float`; `build_metrics_block -> dict[str, float]` and `build_summary -> dict[str, Any]`. **Function bodies remain character-identical** — only signatures gained annotations, which is required for an in-scope `itrader/` module and does not alter runtime behavior (proven by the byte-identical oracle gate).
- **Files modified:** itrader/reporting/summary.py
- **Commit:** b2f22a5

**2. [Rule 3 - Blocking] Worktree/shared-venv module resolution for the oracle gate**
- **Found during:** Task 2
- **Issue:** `make backtest` / `poetry run python scripts/run_backtest.py` resolved `itrader` to the **main repo** (the shared `.venv` editable install `itrader.pth` points at the main repo, not the worktree), so the new `summary.py` was not found when running the script as `__main__`. Additionally the worktree had no `.env`, so `make` (which does `include .env`) hard-failed.
- **Fix:** Symlinked the main repo's gitignored `.env` into the worktree and ran the gate with `PYTHONPATH=<worktree-root>` so worktree code precedes the `.pth` entry. This is a worktree/shared-venv artifact, not a code defect — `make backtest` works normally in the main checkout. No source change. The `.env` symlink is gitignored and was not committed.
- **Files modified:** none (environment-only)
- **Commit:** n/a

### Other adjustments
- Removed the now-unused `import pandas as pd` from `run_backtest.py` (dead after the relocation).
- Refreshed the stale Wave-0 docstring at the top of `test_enums.py` (FillStatus shipped at M2-07; the skip gating is gone).

## Authentication Gates
None.

## Known Stubs
None.

## Threat Flags
None — internal library/test refactoring, no new external surface. The T-04-01 tampering risk (silent oracle re-format) was mitigated exactly as planned: the byte-exact `test_backtest_oracle.py` gate is GREEN.

## Self-Check: PASSED
- FOUND: itrader/reporting/summary.py
- FOUND: `from itrader.reporting.summary import` in scripts/run_backtest.py
- FOUND commit b2f22a5 (Task 1)
- FOUND commit 294f099 (Task 2)
- FOUND commit 90fdcc9 (Task 3)
