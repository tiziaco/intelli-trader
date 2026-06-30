---
phase: 05-cache-classification-3
plan: 01
subsystem: docs + test-harness
tags: [cache-classification, documentation, sc2, nyquist-anchor, wave-0]
requires:
  - ".planning/research/ARCHITECTURE.md §Q7/§Q8 (source inventory + no-Arrow decision)"
  - "Phase-4 D-04 CachedSql* topology (the 3 (d)-class sites)"
provides:
  - "docs/CACHE-CLASSIFICATION.md (authoritative committed cache map — CACHE-01/SC1, D-01 home #1)"
  - "tests/integration/test_cache_classification.py (runnable SC2 grep-matches-inventory check)"
affects:
  - "05-02 (per-site CACHE-CLASS anchors — turns the RED arm GREEN)"
  - "05-03 (D-02 vestigial-knob removal, documented here as scheduled)"
tech-stack:
  added: []
  patterns:
    - "doc-as-source-of-truth: the SC2 test parses the doc's machine-readable anchor block"
    - "Wave-0 RED->GREEN: anchor-count arm is intentionally RED until 05-02"
key-files:
  created:
    - "docs/CACHE-CLASSIFICATION.md"
    - "tests/integration/test_cache_classification.py"
  modified:
    - ".gitignore (negate **cache** for the two mandated Phase-5 artifact names)"
decisions:
  - "(d)-class label finalized: '(d) live-retention working-set cache (built in Phase 4)'"
  - "docs filename finalized: docs/CACHE-CLASSIFICATION.md, grouped-by-class layout"
  - "14 live anchor sites enumerated in a machine-readable block (representative anchor per multi-field family)"
metrics:
  duration: "~30m"
  completed: "2026-06-30"
  tasks: 2
  files: 3
---

# Phase 5 Plan 01: Cache-Classification Map + SC2 Anchor Summary

Built the durable committed cache-classification map (`docs/CACHE-CLASSIFICATION.md`) from the
RESEARCH reconciled-HEAD spine, and codified the SC2 grep-matches-inventory check as a doc-driven
pytest assertion (the Nyquist Wave-0 anchor) — RED only on the not-yet-placed CACHE-CLASS anchors.

## What was built

### Task 1 — `docs/CACHE-CLASSIFICATION.md` (commit `4cb94b0`)
The authoritative, grouped-by-class map (D-01 home #1). Re-grepped `itrader/` at current HEAD and
reconciled against the 2026-06-27 §Q8 table (D-03 — fresh re-grep, not a verbatim copy). All spine
line numbers re-verified this session. Contents:
- **Boundary statement** "classify, do not rewrite or unify" + the **Q7 no-Arrow** DECISION,
  cross-referenced to FEATURES anti-features and PITFALLS Pitfall 3, citing `§Q8` as the source.
- One subsection per class, each with a "what this class is / why it is left alone or routed"
  paragraph then a per-site table (`file:line`, construct, class, Q8 xref, lifecycle):
  - **(c)** 5 sites (#1 bar_feed `_offset_alias`:91, #2 time_parser `_aligned`:139, #3 base.py
    `_declared_hints`:124, #4 base.py `_to_dict_static_cache`:197, #5 position.py
    `_net_quantity_cache`/`_avg_price_cache`:88-89).
  - **(a)** #6 bar-feed precompute family (`_frames`/`_spans`/`_prebuilt`/`_cursor_cut`/`_newest_bars`,
    `_spans` folded in — no new class), #7 stateful indicator state.
  - **(a-infra)** #8 `cache_registration.derive():105`; **(a-engine)** #10 `matching_engine._resting:106`;
    **(b)** #9 `in_memory_storage` derived indexes:62-64 (documentation-only); **(c-config)** #11
    `simulated` venue snapshot:114/123/124.
  - **(d) live-retention working-set cache (built in Phase 4)** — d1/d2/d3 the three
    `CachedSql*Storage._cache` caches, each pointed at Phase-4 D-04 + RETAIN-01/02/03.
- **Removed / superseded** rows: #12 `_metrics_cache` (deleted v1.5 D-04), #13 `sql_store.py`
  `inspector.clear_cache()` (gone via Phase-1 FL-06) — recorded as NON-live.
- **D-02 note**: #14 `enable_caching`/`cache_size_mb` removal scheduled for 05-03 + the harmless-override
  migration note.
- A **machine-readable live-site anchor block** (14 sites) that the SC2 test parses as source of truth.

### Task 2 — `tests/integration/test_cache_classification.py` (commit `096f367`)
The runnable SC2 check (D-01 home #2's verifier). pathlib + re only; emits no warnings under
`filterwarnings=["error"]`; package-less (no `__init__.py`). Four arms, doc-driven:
1. `test_applied_decorator_surface_is_exactly_three_documented_sites` — asserts EXACTLY 3 applied
   memoization decorators and each maps to the doc. **PASS.**
2. `test_every_cache_field_maps_to_a_documented_site` — every `self._cache`/position/to_dict field
   maps to a documented site (no surprise cache). **PASS.**
3. `test_doc_records_q7_no_arrow_decision_and_d_label` — Q7 + Arrow + (d) label + boundary phrase
   present. **PASS.**
4. `test_cache_class_anchors_match_live_inventory` — `# CACHE-CLASS:` anchor count == 14 live sites.
   **RED (0/14) — the intended Wave-0 state; turns GREEN when 05-02 places the per-site anchors.**

Result: `3 passed, 1 failed` under `-W error` — exactly the documented Wave-0 RED→GREEN sequence.

## Verification

- Task 1 automated verify: PASS (file exists; contains "(d) live-retention working-set cache",
  "classify, do not rewrite or unify", "Q8"; `git diff itrader/` empty).
- Task 2 automated verify: PASS (collects + runs under `-W error`; clear RED on the anchor arm;
  decorator arm asserts exactly 3 applied sites; test references `CACHE-CLASSIFICATION`).
- No `itrader/` source modified across the whole plan (`git diff ba9c55d HEAD -- itrader/` empty) —
  hot path byte-inert (CACHE-02 satisfied structurally).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.gitignore` `**cache**` rule ignored both deliverables by filename**
- **Found during:** Task 1 commit (the mandated filename `docs/CACHE-CLASSIFICATION.md` and the test
  both contain the substring "cache"/"CACHE", which the broad `**cache**` rule at `.gitignore:32`
  matches; macOS case-insensitive matching catches the uppercase `CACHE` too).
- **Fix:** Added two `!`-negation lines following the repo's existing convention — `.gitignore` lines
  33-50 already negate `**cache**` for other mandated cache-named artifacts (e.g.
  `cache_registration.py`, the Phase-4 `cached_sql_storage.py` files, the Phase-5 planning dir). The
  plan FINALIZED these exact filenames, so renaming was not an option.
- **Files modified:** `.gitignore`
- **Commit:** `4cb94b0` (committed with Task 1).

### Documentation drift reconciled (no code impact)

**2. [Rule 1 adjacent - doc accuracy] RESEARCH's `settings/domains/system.default.yaml` cache block does not exist at HEAD**
- The RESEARCH D-02 section described a `cache:` YAML block (`enable_caching`/`max_cache_size_mb`/…).
  A fresh check shows `settings/domains/system.default.yaml` does not exist and no tracked YAML sets
  these keys. The map documents this accurately: the 05-03 D-02 removal touches only the two Python
  fields (`config/system.py:45-46`); there is no tracked YAML line to delete. The harmless-override
  migration note still applies. No code changed (D-02 is 05-03's edit, not this plan's).

## Known Stubs

None. Both artifacts are complete deliverables. The RED test arm is an intentional Wave-0 anchor
(documented above), not a stub.

## Threat Flags

None. This plan adds one in-repo doc and one test file; no new runtime surface, endpoint, credential,
or data flow. Threat T-05-01 (doc drifting from code) is the mitigation this plan ships (the SC2 test).

## Self-Check: PASSED
- `docs/CACHE-CLASSIFICATION.md` — FOUND
- `tests/integration/test_cache_classification.py` — FOUND
- commit `4cb94b0` — FOUND
- commit `096f367` — FOUND
- `itrader/` diff vs base — empty (hot path untouched)
