---
status: passed
phase: 09-multi-entity-robustness-metrics-edges
source: [09-VERIFICATION.md, 09-REVIEW.md]
started: 2026-06-10T00:00:00Z
updated: 2026-06-10T00:00:00Z
resolved: 2026-06-10T00:00:00Z
---

## Current Test

[resolved 2026-06-10 — both decisions made during the v1.1 milestone audit; see Summary]

## Tests

### 1. WR-01 — Determinism test frame scope (ROBUST-04 contract)
expected: `tests/e2e/robust/test_determinism.py:67-69` should decide whether the double-run identity assertion must cover the three NEW Phase-9 frames (orders, cash_ops, portfolios_frame) — currently it asserts identity only on trades/equity/summary (indices 0/1/2), silently discarding 3/4/5. The MULTI-04 contended-cash ledger and MULTI-03 per-portfolio snapshot — the exact new vehicles most exposed to non-determinism — are computed then thrown away. Decision: accept the narrowing as-is, or extend the assertion (≈3 lines) before closing the phase.
result: PASSED — extended (option b). Fixed in commit `9c56162`: `test_determinism.py` now asserts `assert_frame_equal` on all six frames (orders a[3], cash_ops a[4], portfolios_frame a[5] added). All 9 leaves pass byte-identical, confirming no frame is non-deterministic.

### 2. WR-02 — `Infinity` profit_factor in four multi-entity goldens
expected: `two_tickers`, `two_strategies`, `fanout_portfolios`, `contended_cash` all freeze `"profit_factor": Infinity` (all-win frames), and `_diff_summary` locks it (`inf == inf`) with no finiteness gate — while the project's own `_assert_finite.py` treats `inf` as a degenerate-metrics smell and runs only on the three opt-in ROBUST-03 leaves. Decision: document `inf` as an explicit carve-out in those four VERIFY notes, or extend the finiteness guard framework-wide.
result: PASSED — ratified the documented carve-out. `inf` is mathematically correct for a genuinely all-win run (gross losses = 0); the finiteness guard is intentionally scoped to the degenerate ROBUST-03 leaves only. Carve-out documented in all four scenario VERIFY notes (commit `d0293a9`, per 09-REVIEW-FIX.md). Owner decision recorded in `.planning/v1.1-MILESTONE-AUDIT.md`.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
