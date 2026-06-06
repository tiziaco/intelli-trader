---
status: partial
phase: 05-m4-money-transaction-correctness
source: [05-VERIFICATION.md]
started: 2026-06-06T11:40:06Z
updated: 2026-06-06T11:40:06Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. CR-01 — quantity-only modify_order raises TypeError
expected: Disposition decided — either fix-forward (validate_order_modification handles new_price=None / new_quantity=None correctly) or formally accepted as out-of-scope for the backtest milestone (modify path is not on the backtest oracle path)
result: [pending]

### 2. CR-02 — LiveTradingSystem calls nonexistent PortfolioHandler.record_metrics
expected: Disposition decided — either fix-forward (route to the correct metrics recording API per portfolio) or formally accepted as live-mode-only defect deferred beyond the backtest-correctness milestone
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
