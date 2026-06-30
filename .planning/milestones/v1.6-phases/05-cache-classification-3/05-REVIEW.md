---
phase: 05-cache-classification-3
reviewed: 2026-06-30T13:18:53Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - docs/CACHE-CLASSIFICATION.md
  - itrader/config/system.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/matching_engine.py
  - itrader/order_handler/storage/cached_sql_storage.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/outils/time_parser.py
  - itrader/portfolio_handler/position/position.py
  - itrader/portfolio_handler/storage/cached_sql_storage.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/indicators/handle.py
  - itrader/strategy_handler/storage/cached_sql_storage.py
  - tests/integration/test_cache_classification.py
  - .gitignore
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-30T13:18:53Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 5 is a documentation + inert-comment phase. I reviewed the full `git diff ba9c55d..HEAD`
of every listed source file and verified the four phase invariants the brief flagged as
high-risk:

- **No accidental non-comment edits.** Filtering the whole `itrader/` diff to non-`CACHE-CLASS`
  added/removed lines yields *only* the two removed config fields. Every other change is a single
  inert `# CACHE-CLASS:` comment line. Confirmed clean.
- **No indentation normalization.** Byte-level inspection of each inserted comment and its
  neighbours confirms tab files stayed tab (`simulated.py`, `position.py`, `base.py:198`,
  `handle.py`) and 4-space files stayed 4-space (`matching_engine.py`, `in_memory_storage.py`,
  the three `cached_sql_storage.py`, `bar_feed.py`). No mixed-indent diff introduced.
- **config/system.py is exactly the two-field removal.** Only `enable_caching` and `cache_size_mb`
  were deleted; `rng_seed: int = 42` (determinism-critical) is intact; `mypy --strict` is clean on
  the file; no remaining references to the deleted fields in tracked `itrader/`, `settings/`,
  `scripts/`, or `tests/`.
- **The new SC2 test passes (all 4 arms green)** and its field/decorator-surface arms are robust.
- **`.gitignore` negations are correctly ordered** after the broad `**cache**` rule; both mandated
  artifacts are tracked and not ignored.

The functional goal of the phase is met. The defects below are accuracy/maintainability issues in
the *committed documentation artifact* (the whole deliverable of a doc phase), not behavioral bugs —
hence no Blocker. The headline issue is that the committed map's line numbers were never reconciled
after plan 05-02 inserted the anchors, so nearly every `file:line` in the "authoritative,
re-verified" map is now off by 1-2, and the SC2 drift-guard does not catch it.

## Warnings

### WR-01: Committed cache map's line numbers are systematically stale at HEAD; SC2 test does not guard them

**File:** `docs/CACHE-CLASSIFICATION.md:7` (claim), `:74-140` (prose tables), `:184-198` (machine-readable inventory)

**Issue:** The doc asserts (line 7) "line numbers re-verified" and (lines 177-178) that each
`file:line` in the machine-readable inventory is where plan 05-02 places the `# CACHE-CLASS:`
anchor. But 05-02 inserts each anchor *above* the definition, shifting every definition (and every
line below it in the same file) down by 1 — and for files with two anchors, the second anchor's
targets shift by 2. The doc was written in 05-01 against the *pre-anchor* line numbers and was
never reconciled. Cross-checking every cited line against the actual code at HEAD:

- Second-anchor entries are off by 2 and point to neither anchor nor definition:
  - `bar_feed.py:241` claims "anchor `_prebuilt`" — actual anchor is at `242`, `self._prebuilt` at `243`; line `241` is the comment "so a cache would serve zero hits."
  - `base.py:197` claims "`_to_dict_static_cache` field" — actual anchor at `198`, field at `199`; line `197` is the comment "mutator). Never invalidated...".
- Every embedded field-family reference in the prose tables is off by 1 and lands on an unrelated
  comment line: `_frames:213`, `_spans:224`, `_cursor_cut:316`, `_newest_bars:326` (bar_feed.py),
  `_trails:110` (matching_engine.py), `_min_order_size:123`/`_max_order_size:124` (simulated.py),
  `_invalidate_to_dict_cache def L782` (base.py — now `return snapshot`), position invalidation
  `L288-289` (now `# exists outside __init__ construction.`), `_active_by_portfolio L62-64`
  (62 is now the anchor comment).
- Single-anchor sites land the reader on the anchor comment rather than the definition the doc
  names (e.g. `_offset_alias def` cited at `bar_feed.py:91` but the `def` is at `93`).

The SC2 test (`test_cache_class_anchors_match_live_inventory`) only checks anchor *file membership*
and *total count* (14 == 14) — it never compares anchor line numbers to the inventory line numbers.
So this drift is silent: the doc advertises a line-accurate, drift-guarded map but ships line
references that are wrong at the very HEAD it claims to be verified against.

**Fix:** Either (a) re-run the grep after 05-02 and update the line numbers in both the prose tables
and the machine-readable block to the post-anchor values, or (b) restate the doc's convention to "the
listed line is the anchor-comment line" and strengthen the SC2 test to assert each scanned anchor's
`(file, line)` equals an inventory `(file, line)` pair (not just file + count), so the line numbers
become drift-guarded for real:
```python
anchor_set = set(_scan_itrader(_ANCHOR_RE, whole_file=True))
inv_set = {(f, ln) for f, lines in inventory.items() for ln in lines}
assert anchor_set == inv_set, f"anchor line-numbers drifted: {anchor_set ^ inv_set}"
```

### WR-02: SC2 test docstring still describes itself as "EXPECTED RED until 05-02" — but it is GREEN at the committed HEAD

**File:** `tests/integration/test_cache_classification.py:15-17`, `:149-153`, `:160-162`

**Issue:** The module docstring and `test_cache_class_anchors_match_live_inventory` claim the anchor
arm is "EXPECTED RED (Wave-0 RED->GREEN sequence, NOT a failure)" and "fails until plan 05-02 places
the per-site `# CACHE-CLASS:` annotations." Plan 05-02 has run and all 14 anchors are present, so the
arm passes (verified: `4 passed`). At the committed final state of the phase, this commentary
misdescribes the test's actual behavior and will mislead a maintainer (the assertion message even
says "This RED is the intended Wave-0 state" on a path that no longer goes red). For a phase whose
entire deliverable is documentation accuracy, a committed test that lies about its own state is a
defect.

**Fix:** Update the docstring and the assertion message to reflect the now-GREEN state, e.g.
"Anchors placed by 05-02; this arm is GREEN at HEAD and locks the per-site anchor count to the doc
inventory." Drop the "EXPECTED RED" framing.

## Info

### IN-01: Doc states `settings/domains/system.default.yaml` "does not exist", but it exists on disk with a live `cache:` block

**File:** `docs/CACHE-CLASSIFICATION.md:163-166`

**Issue:** The D-02 section asserts the `cache:` YAML block "is **not present** in tracked `settings/`
at HEAD — `settings/domains/system.default.yaml` does not exist." The file does exist on disk (it is
gitignored/untracked) and contains a full `cache:` block including `enable_caching: true` and
`max_cache_size_mb: 512`. The doc's operative, scoped claim ("no *tracked* YAML sets these keys") is
correct and the conclusion ("no migration required") holds because the block is untracked, top-level
`cache:` (not under `performance:`), and Pydantic `extra="ignore"` drops unknowns. But the absolute
"does not exist" phrasing is factually wrong and weakens the audit trail.

**Fix:** Soften to "no *tracked* `settings/*.yaml` sets these keys; the untracked local
`settings/domains/system.default.yaml` carries a dead top-level `cache:` block that never maps to
`PerformanceSettings` and is dropped by `extra='ignore'`."

---

_Reviewed: 2026-06-30T13:18:53Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
