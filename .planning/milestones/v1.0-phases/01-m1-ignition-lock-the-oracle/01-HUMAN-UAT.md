---
status: partial
phase: 01-m1-ignition-lock-the-oracle
source: [01-VERIFICATION.md]
started: 2026-06-04T00:00:00Z
updated: 2026-06-04T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. DEF-01-C oracle acceptance (negative-equity short)
expected: The human confirms the 184 negative-equity rows in test/golden/equity.csv (min ~-$33,748 at 2023-11-10) are accepted current-behavior-to-preserve, driven by an un-liquidated short with no margin/liquidation model, and that deferred-items.md DEF-01-C accurately records the blessing. (Blessed during Plan 05 checkpoint — this is confirmation of the record.)
result: [pending]

### 2. Code-review advisory acknowledgment (CR-01 / CR-02)
expected: The human acknowledges CR-01 (SELL exit sizing guard on net_quantity > 0 at order_manager.py:267 — overlaps DEF-01-C / M5) and CR-02 (to_megaframe key-mismatch, latent multi-symbol path not exercised by the single-BTCUSD oracle) as consciously accepted advisory (non-blocking) risks that do not affect the current oracle.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
