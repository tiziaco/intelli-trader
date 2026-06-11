---
phase: 06-order-matching-scenarios
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/06-order-matching-scenarios/06-REVIEW.md
iteration: 2
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 6: Code Review Fix Report

**Fixed at:** 2026-06-10T00:00:00Z
**Source review:** .planning/phases/06-order-matching-scenarios/06-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 1
- Fixed: 1
- Skipped: 0

This is iteration 2 of the fix cycle. Iteration 1 resolved six findings (WR-01,
WR-02, WR-03, IN-01, IN-02, IN-03) across five commits (`1200cc0`..`443c3b7`). The
re-review confirmed all five substantive findings genuinely resolved and surfaced a
single low-severity carryover (the second, comment-only half of the original IN-03),
re-numbered IN-01 in the re-review. That carryover is fixed here.

Cumulative across both iterations: 7 findings fixed, 0 skipped.

## Fixed Issues

### IN-01: Hard-coded source line-number references still rot in `stop_gap_down/scenario.py`

**Files modified:** `tests/e2e/matching/entries/stop_gap_down/scenario.py`
**Commit:** d0c1867
**Applied fix:** Removed the three stale positional `file.py:NNN` citations
(`strategies_handler.py:225` at the docstring AUTHORING-PATH block and the trailing
inline comment; `order_manager.py:641` at the bracket-assembler sentence) and
replaced them with durable symbol + decision-tag anchors per CLAUDE.md:

- `strategies_handler.py:225` → "the LONG_ONLY guard in
  `StrategiesHandler.add_strategy` (D-08/D-09)". (The actual guard is the
  `direction is not TradingDirection.LONG_ONLY` check in `add_strategy`, annotated
  D-08/D-09 in the source — the review's suggested wording, made precise against the
  live code.)
- `order_manager.py:641` → "the bracket assembler in
  `OrderManager._assemble_bracket_and_emit` (D-11) ... via `Order.new_stop_order`".
  (The review suggested tag "D-15", but D-15 is the PositionView read-model seam; the
  create-all-then-emit bracket assembly is D-11 in `order_manager.py`. Used the
  accurate tag so the anchor is correct, not just durable.)

Comment/citation-only change — no runtime behavior altered. Verified: Python
`ast.parse` clean, no `\.py:[0-9]+` citations remain in the file, and the full Phase
6 e2e matching suite still passes (`14 passed`).

---

_Fixed: 2026-06-10T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
