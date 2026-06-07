---
status: partial
phase: 07-m5b-sizing-policy-metrics-universe-coverage
source: [07-VERIFICATION.md]
started: 2026-06-08T08:45:00Z
updated: 2026-06-08T08:45:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. make backtest end-to-end run

expected: `scripts/run_backtest.py` prints the D-14 metrics block to stdout, produces `output/summary.json` containing the nested `metrics` object (cagr, max_drawdown, profit_factor, sharpe, sortino, win_rate), and two consecutive runs are byte-identical (`trades.csv`, `equity.csv`, `summary.json`).
result: [pending]

### 2. Golden re-freeze content review

expected: Both `tests/golden/REFREEZE-M5B-DIRECTION.md` and `tests/golden/REFREEZE-M5B-INCREASE.md` fully attribute the trade changes with no unexplained residual; the approved golden reflects a clean long-only, non-pyramiding run (0 SHORT rows, 6 audited admission rejections total).
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
