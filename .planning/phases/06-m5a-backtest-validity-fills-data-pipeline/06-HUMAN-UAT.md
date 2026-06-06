---
status: diagnosed
phase: 06-m5a-backtest-validity-fills-data-pipeline
source: [06-VERIFICATION.md]
started: 2026-06-06T15:35:00Z
updated: 2026-06-06T15:45:00Z
---

## Current Test

[complete — owner routed both items to gap closure]

## Tests

### 1. WR-06 dead-code disposition — `update_portfolios_market`
expected: Owner decides the fate of `itrader/portfolio_handler/portfolio_handler.py:355-377` (`update_portfolios_market` reads nonexistent `bar.close_price`, never called from the production event handler): delete it (preferred) or accept as known dead-code carryforward to Phase 7.
result: issue — owner routed to gap closure: delete the dead method (it reads a nonexistent `Bar.close_price` field and can never work)

### 2. CR-01 disposition — bracket children can fill before parent entry
expected: Owner decides whether the MatchingEngine parent-filled gate gap (a LIMIT/STOP primary with SL/TP brackets can see the TP fill before the entry triggers — see 06-REVIEW.md CR-01) is an explicitly deferred Phase 7 item or needs a fix before Phase 7 begins. The golden `SMA_MACD` run uses only market orders with sl=0/tp=0, so the oracle and all 586 tests are unaffected.
result: issue — owner routed to gap closure: add a parent-filled gate so bracket children cannot fill while their parent entry still rests

## Summary

total: 2
passed: 0
issues: 2
pending: 0
skipped: 0
blocked: 0

## Gaps

### Gap 1: Dead `update_portfolios_market` method (WR-06)
status: failed
source: 06-VERIFICATION.md / 06-REVIEW.md WR-06
detail: `itrader/portfolio_handler/portfolio_handler.py:355-377` — `update_portfolios_market` reads `bar.close_price` (field does not exist on `Bar`; correct field is `close`), so every price resolves to None. Never called from the production event handler (run path uses `update_portfolios_market_value`). Resolution: delete the method and any references; oracle must stay byte-exact (structural deletion, D-21 inert).

### Gap 2: MatchingEngine lacks parent-filled gate for bracket children (CR-01)
status: failed
source: 06-REVIEW.md CR-01 (Critical)
detail: `MatchingEngine.on_bar` (itrader/execution_handler/matching_engine.py:178-267) evaluates resting bracket children without confirming the parent entry has filled. With a LIMIT/STOP primary + SL/TP bracket, a TP can fill while the entry never triggered — silently opening a reverse position from flat and leaving the still-resting parent unprotected. Unreachable on the golden market-order path (sl=0/tp=0), so the oracle is unaffected. Resolution: two-pass on_bar (parents first; children eligible only once their parent has left the book as FILLED) or hold child activation until the parent's EXECUTED fill; regression-lock with unit tests for limit-entry brackets; oracle must stay byte-exact.
