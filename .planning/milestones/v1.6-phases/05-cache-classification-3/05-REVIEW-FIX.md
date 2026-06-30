---
phase: 05-cache-classification-3
fixed_at: 2026-06-30T00:00:00Z
review_path: .planning/phases/05-cache-classification-3/05-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 5: Code Review Fix Report

**Fixed at:** 2026-06-30
**Source review:** .planning/phases/05-cache-classification-3/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2 (WR-01, WR-02 — Warning tier)
- Fixed: 2
- Skipped: 0
- Out of scope this pass: IN-01 (Info)

**Gate verification (re-run after fixes, green):**
```
PYTHONPATH="$PWD" poetry run pytest \
  tests/integration/test_cache_classification.py \
  tests/integration/test_backtest_oracle.py -q
=> 7 passed in 1.46s  (SC2 4/4 + oracle 3/3 byte-exact)
```

## Fixed Issues

### WR-01: Committed cache map's line numbers are systematically stale at HEAD

**Files modified:** `docs/CACHE-CLASSIFICATION.md`
**Commit:** 183ef44
**Applied fix:** Reconciled every cited `file:line` against current HEAD by reading each
source file at the referenced line (option (a) from the review). Adopted and documented an
explicit line convention so the numbers are unambiguous going forward.

Convention recorded in the doc: the **Site `file:line`** column is the `# CACHE-CLASS:`
anchor-comment line (05-02 places each anchor one line *above* the definition), so the Site
number matches the machine-readable anchor inventory; embedded field-family references inside
the *Construct* column point at the **definition** line.

Reconciliations applied (verified against HEAD source):
- Prose #4 `base.py` Site `:197 -> :198` (anchor line); `_invalidate_to_dict_cache def L782 -> L784`.
- Prose #5 `position.py` field pair `L88-89 -> L89-90`; `update_position` invalidation `L288-289 -> L289-290` (Site `:88` already correct = anchor).
- Prose #6 `bar_feed.py` Site `:241 -> :242` (anchor line); family `_frames:213->214`, `_spans:224->225`, `_prebuilt:241->243`, `_cursor_cut:316->318`, `_newest_bars:326->328`; "Anchor row is `_prebuilt` (L241 -> L242)".
- Prose #10 `matching_engine.py` `_trails:110 -> :111` (Site `:106` already correct = anchor).
- Prose #9 `in_memory_storage.py` field range `L62-64 -> L63-65` (Site `:62` already correct = anchor).
- Prose #11 `simulated.py` `_min_order_size:123 -> :124`, `_max_order_size:124 -> :125` (Site `:114` already correct = anchor).
- Machine-readable block: `base.py:197 -> :198`, `bar_feed.py:241 -> :242`.

References that were already correct at HEAD and left unchanged (re-verified): the 14 anchor
Site lines for #1/#2/#3/#5/#7/#8/#9/#10/#11/d1/d2/d3, the catalog.py state-class lines
(`_SMAState:97 / _EMAState:143 / _MACDHistState:184 / _RSIState:241`), and
`derive_required_depths:65`.

**Decision on WR-01 part (2) — the suggested SC2 line-equality assertion (NOT applied, by design):**
The review offered an alternative (b): tighten the SC2 test to assert each scanned anchor's
`(file, line)` equals an inventory `(file, line)` pair. I deliberately did **not** add this. The
phase plans scoped SC2 to file membership + count precisely because a line-level set-equality
assertion makes the suite brittle: it would go red on *any* future edit that shifts a cache site
by even one line — including edits entirely unrelated to caching — turning a doc-accuracy guard
into a tripwire on ordinary refactors. Reconciling the doc (part 1) fixes the actual defect (the
shipped numbers were wrong); the new explicit line convention plus the existing file+count guard
is the right durability/robustness trade-off. This is a conscious decision, not an oversight.

### WR-02: SC2 test docstring still described itself as "EXPECTED RED until 05-02"

**Files modified:** `tests/integration/test_cache_classification.py`
**Commit:** f8902ab
**Applied fix:** Comment-only change (assertion logic untouched). Updated the module docstring,
the `test_cache_class_anchors_match_live_inventory` docstring, the section banner
(`arm 3 (RED)` -> `arm 3 (GREEN)`), and the assertion failure message to describe the now-GREEN
state: anchors were placed by 05-02, the Wave-0 RED->GREEN sequence is complete, and the arm now
locks the per-site anchor count to the doc inventory. Dropped the "EXPECTED RED"/"intended Wave-0
state" framing that no longer matches behavior. Verified `4 passed` for the SC2 module.

## Skipped Issues

None — both in-scope findings fixed.

(IN-01 was intentionally out of scope for this pass per the fix instructions; it remains open in
05-REVIEW.md for a future iteration.)

---

_Fixed: 2026-06-30_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
