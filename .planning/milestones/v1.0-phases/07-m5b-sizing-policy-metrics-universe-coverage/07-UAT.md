---
status: complete
phase: 07-m5b-sizing-policy-metrics-universe-coverage
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md, 07-05-SUMMARY.md, 07-06-SUMMARY.md, 07-07-SUMMARY.md, 07-08-SUMMARY.md]
started: 2026-06-08T09:00:00Z
updated: 2026-06-08T09:15:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. Backtest runs end-to-end + metrics printout (cold start)
expected: Run from scratch (`make backtest`). Engine boots, runs SMA_MACD over the golden BTCUSD_1d dataset, completes with no errors/warnings, and prints a metrics summary block per portfolio (sharpe, sortino, cagr, max_drawdown, profit_factor, win_rate) plus final equity + trade count. Writes output/{trades.csv, equity.csv, summary.json}.
result: pass

### 2. summary.json carries the nested metrics block
expected: output/summary.json contains a nested `metrics` object with cagr, max_drawdown, profit_factor, sharpe, sortino, win_rate — all numeric. Computed by the same pure functions the engine prints.
result: pass

### 3. Deterministic re-run (byte-identical output)
expected: Running the backtest twice produces byte-identical output. `diff -r` between two consecutive output trees (trades.csv, equity.csv, summary.json) is clean — no differences.
result: pass

### 4. trades.csv slippage columns
expected: output/trades.csv carries `slippage_entry` and `slippage_exit` columns (next-bar-open gap attribution; zero-slippage golden measures the overnight gap).
result: pass

### 5. Long-only enforcement (re-freeze 1)
expected: With SMA_MACD declaring LONG_ONLY, trades.csv has ZERO rows with side SHORT. SELL signals with no open long are rejected and audited (triggered_by=admission_direction). Final equity reflects the long-only baseline (~46k, down from the pre-guard ~53k).
result: pass

### 6. Non-pyramiding enforcement (re-freeze 2)
expected: With allow_increase=False, a BUY against an already-open long is rejected (no position increase) and audited (triggered_by=admission_increase). Trade count holds at 134; each trade keeps its identity. Across both guards there are 6 total audited admission rejections (3 direction + 3 increase).
result: pass

### 7. Golden re-freeze attribution docs (owner-approved)
expected: tests/golden/REFREEZE-M5B-DIRECTION.md and tests/golden/REFREEZE-M5B-INCREASE.md both exist, are owner-approved, and fully attribute the numeric change with no unexplained residual. They record exactly two named result-changing re-freezes (long-only, then non-pyramiding).
result: pass

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
