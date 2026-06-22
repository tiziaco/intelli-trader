---
status: complete
phase: 01-instrument-value-object
source: [01-VERIFICATION.md]
started: 2026-06-15T07:39:42Z
updated: 2026-06-15T07:39:42Z
---

## Current Test

[all items resolved in code]

## Tests

### 1. WR-02 — `_infer_price_scale` miscounts scientific-notation cells
expected: Owner acknowledges this as a known latent bug, or it is fixed before non-declared symbols are wired through live inference.
result: resolved — FIXED in code. A `frac.isdigit()` guard was added to `_infer_price_scale` in `itrader/universe/instruments.py` (fix(01) commit `5bf5821`); scientific-notation / trailing-garbage cells are now skipped instead of miscounted. No longer a latent defect.

### 2. WR-01 — `Instrument.quote_currency` not read by `quantize` cash precision
expected: Owner decides — fix the docstring (inert) or implement the `quote_currency`-derived cash scale before non-USD instruments land.
result: resolved — FIXED in code and owner-approved. `quantize(kind="cash")` now derives the scale from `instrument.quote_currency` via `_CASH_SCALES` (USD -> 2dp, byte-identical) in `itrader/core/money.py` (fix(01) commit `1498048`). Owner reviewed the design and chose to keep the forward-looking derivation. Inert today (all instruments USD; `quantize` has no production caller yet); byte-exact oracle independently re-verified passing post-fix.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
