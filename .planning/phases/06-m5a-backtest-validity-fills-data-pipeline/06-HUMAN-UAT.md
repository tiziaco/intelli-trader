---
status: partial
phase: 06-m5a-backtest-validity-fills-data-pipeline
source: [06-VERIFICATION.md]
started: 2026-06-06T15:35:00Z
updated: 2026-06-06T15:35:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. WR-06 dead-code disposition — `update_portfolios_market`
expected: Owner decides the fate of `itrader/portfolio_handler/portfolio_handler.py:355-377` (`update_portfolios_market` reads nonexistent `bar.close_price`, never called from the production event handler): delete it (preferred) or accept as known dead-code carryforward to Phase 7.
result: [pending]

### 2. CR-01 disposition — bracket children can fill before parent entry
expected: Owner decides whether the MatchingEngine parent-filled gate gap (a LIMIT/STOP primary with SL/TP brackets can see the TP fill before the entry triggers — see 06-REVIEW.md CR-01) is an explicitly deferred Phase 7 item or needs a fix before Phase 7 begins. The golden `SMA_MACD` run uses only market orders with sl=0/tp=0, so the oracle and all 586 tests are unaffected.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
