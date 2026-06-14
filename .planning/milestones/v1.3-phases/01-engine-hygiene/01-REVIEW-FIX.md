---
phase: 01-engine-hygiene
fixed_at: 2026-06-12T00:00:00Z
review_path: .planning/phases/01-engine-hygiene/01-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 4
skipped: 1
status: partial
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-06-12T00:00:00Z
**Source review:** .planning/phases/01-engine-hygiene/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (all severities — fix_scope=all)
- Fixed: 4
- Skipped: 1

All fixes were applied in an isolated git worktree, committed atomically, and
validated against the phase guardrails. After all fixes:
- `mypy itrader` — clean (no issues found in 150 source files).
- Full test suite — 851 passed.
- Golden oracle (134 trades / final_equity 46189.87730727451) preserved: the
  changes are documentation-leaning and byte-exact (no behavioral path touched;
  `Decimal('1000000') == 1_000_000` so the IN-03 bound comparisons are identical).

## Fixed Issues

### IN-01: `ONE` exported but absent from `core/money.py` public surface

**Files modified:** `itrader/core/money.py`
**Commit:** c16f983
**Applied fix:** Added `__all__ = ["ONE", "to_money", "quantize"]` to pin the
module's public surface, matching the `__all__` convention in `core/sizing.py`
and `sizing_resolver.py`. The list mirrors the actual public names (`ONE`
constant + `to_money`/`quantize` functions). Pure surface-declaration change, no
runtime behavior affected.

### WR-01: Validator retype narrows accepted types and rejects `int`

**Files modified:** `itrader/portfolio_handler/validators.py`
**Commit:** c3028a6
**Applied fix:** Took the reviewer's *strict-Decimal-retained* option (NOT the
re-widening option) to honor HYG-01 success-criterion #2. Added an explicit NOTE
comment above the `isinstance(..., decimal.Decimal)` guards documenting that
int/float are intentionally rejected and callers must enter the Decimal domain
via `to_money()` first, with a "do not re-widen" warning for future readers. Also
tightened the three error messages to say "positive/non-negative Decimal" and use
`{...!r}` so a rejected non-Decimal input is unambiguous. Runtime guard behavior
is unchanged (still strict-Decimal); only the message text and an explanatory
comment changed.

### WR-02: Retyped validator is fully dead code

**Files modified:** `itrader/portfolio_handler/validators.py`
**Commit:** d56ea81
**Applied fix:** Took the documentation option (NOT deletion — deletion is out
of HYG-01 scope per D-07). Added a module-docstring NOTE marking
`validators.py` as a not-yet-wired future seam with zero importers, and flagging
that the module deliberately mixes the Decimal-strict `validate_transaction_data`
with still-`float`-typed siblings — making the inconsistency intentional-by-scope
rather than an oversight a future reader might "fix." Did NOT retype the sibling
methods (`validate_portfolio_data(cash: float)`, `PositionValidator`,
`to_decimal`): a behavioral retype of dead code carries no value and risks
diverging from the surrounding still-float design; documentation is the minimal,
byte-exact choice.

### IN-03: Upper-bound checks compare Decimal against bare int magic numbers

**Files modified:** `itrader/portfolio_handler/validators.py`
**Commit:** bcc4855
**Applied fix:** Hoisted the two inline `1_000_000` literals to named module
constants `_MAX_REASONABLE_PRICE = decimal.Decimal('1000000')` and
`_MAX_REASONABLE_QUANTITY = decimal.Decimal('1000000')`, and rewrote the
comparisons to use them. The bounds now compare Decimal-against-Decimal and are
documented. `Decimal('1000000')` equals the prior `1_000_000` exactly, so the
comparison results are identical — behavior-preserving.

## Skipped Issues

### IN-02: `exit_fraction`/slippage `Decimal("1")` literals not consolidated to `ONE`

**File:** `itrader/core/sizing.py:241`
**Reason:** skipped — reviewer explicitly marked this finding "Out of scope for
this phase." Consolidating the inline `Decimal("1")` literals (especially the
dataclass field defaults, which double as D-07 documentation anchors) is a
deferred follow-up, not a HYG-01 defect. No change made to `sizing.py`,
`signal.py`, `signal_record.py`, `base.py`, the slippage models, or `simulated.py`.

---

_Fixed: 2026-06-12T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
