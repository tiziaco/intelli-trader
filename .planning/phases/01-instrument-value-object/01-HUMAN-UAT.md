---
status: partial
phase: 01-instrument-value-object
source: [01-VERIFICATION.md]
started: 2026-06-15T07:39:42Z
updated: 2026-06-15T07:39:42Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. WR-02 — `_infer_price_scale` miscounts scientific-notation cells
expected: Owner acknowledges this as a known latent bug. `_infer_price_scale` counts characters after the first `.` without digit validation, so a cell like `"1.0e-5"` infers 4dp instead of 5dp. Oracle-dark today (inference is never called on the golden BTCUSD run — `price_data={}`, BTCUSD is declared). Acknowledge and schedule the one-line `frac.isdigit()` guard before any non-declared symbol is wired through live inference (INST-02 consumers in later phases).
result: [pending]

### 2. WR-01 — `Instrument.quote_currency` not read by `quantize` cash precision
expected: Owner acknowledges the contract/code mismatch. The `quote_currency` docstring says it is the cash-scale source, but `money.quantize` hard-codes cash precision at 2dp and never reads `instrument.quote_currency`. Inert while all instruments are USD. Either fix the docstring ("(inert this phase — cash fixed at 2dp)") or implement the derivation before non-USD instruments land.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
