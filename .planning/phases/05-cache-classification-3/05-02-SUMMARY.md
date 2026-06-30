---
phase: 05-cache-classification-3
plan: 02
subsystem: cache-classification (per-site code anchors)
tags: [cache-classification, sc2, code-anchors, wave-2, tab-space-hazard]
requires:
  - "05-01 (docs/CACHE-CLASSIFICATION.md authoritative map + the SC2 anchor-arm test)"
  - "docs/CACHE-CLASSIFICATION.md machine-readable 14-site live anchor block"
provides:
  - "14 `# CACHE-CLASS:` per-site code anchors across 12 itrader/ source files (D-01 home #2)"
  - "SC2 anchor arm GREEN: tests/integration/test_cache_classification.py 4/4 passing"
affects:
  - "05-03 (D-02 vestigial-knob removal; consumes the now-GREEN SC2 surface as a drift gate)"
tech-stack:
  added: []
  patterns:
    - "drift-proof code-side anchor: one inert `# CACHE-CLASS: (x) <label> — see docs/CACHE-CLASSIFICATION.md` comment per live cache site"
    - "tab/space hazard isolation: split annotation work into two tasks by indentation style (4-space vs tab) with per-file `grep -cP '^\\t'` re-verification at edit time"
key-files:
  created: []
  modified:
    - "itrader/price_handler/feed/bar_feed.py (2 anchors: c memo + a hot-path family)"
    - "itrader/price_handler/feed/cache_registration.py (a-infra)"
    - "itrader/order_handler/storage/in_memory_storage.py (b)"
    - "itrader/execution_handler/matching_engine.py (a-engine)"
    - "itrader/order_handler/storage/cached_sql_storage.py (d)"
    - "itrader/portfolio_handler/storage/cached_sql_storage.py (d)"
    - "itrader/strategy_handler/storage/cached_sql_storage.py (d)"
    - "itrader/outils/time_parser.py (c)"
    - "itrader/strategy_handler/base.py (2 anchors: c memo + c invalidated memo)"
    - "itrader/portfolio_handler/position/position.py (c)"
    - "itrader/strategy_handler/indicators/handle.py (a)"
    - "itrader/execution_handler/exchanges/simulated.py (c-config)"
decisions:
  - "Anchors placed as separate comment lines directly above each canonical definition line (never overwriting existing trailing decision-tag comments such as in_memory_storage's `# derived cache (D-02)`)"
  - "Module-level decorators (time_parser _aligned, base.py _declared_hints) anchored at column 0; in-method fields anchored at the field's exact tab depth"
metrics:
  duration: "~20m"
  completed: "2026-06-30"
  tasks: 2
  files: 12
---

# Phase 5 Plan 02: Per-Site CACHE-CLASS Anchors Summary

Placed the 14 drift-proof `# CACHE-CLASS:` code anchors (D-01 home #2) on the canonical
definition line of every live cache site enumerated in `docs/CACHE-CLASSIFICATION.md`, turning the
05-01 SC2 anchor arm from RED (0/14) to GREEN (14/14) — classify-not-rewrite honored: only inert
comment lines were added, no class-(a)/(b)/(c) logic was touched.

## What was built

### Task 1 — 4-space cache sites (8 anchors, 7 files) — commit `f333568`
All 7 files re-verified 4-space (`grep -cP '^\t'` == 0) before editing. Anchors:
- **bar_feed.py** (two): `(c) pure-function memo` on the `@functools.cache` `_offset_alias` decorator;
  `(a) hot-path data cache [family: _frames/_spans/_prebuilt/_cursor/_cursor_cut/_newest_bars]` on
  `self._prebuilt`.
- **cache_registration.py**: `(a-infra) shared-bar-cache capacity (wiring-time)` on `def derive(`.
- **in_memory_storage.py**: `(b) storage-index lookup — solved by Phase-3 SQL WHERE/indexes` as a
  SEPARATE line above `self._active_by_portfolio` (left the pre-existing `# derived cache (D-02)`
  trailing comment intact).
- **matching_engine.py**: `(a-engine) resting-order working state` on `self._resting`.
- **three `cached_sql_storage.py`** (order / portfolio / strategy): `(d) live-retention working-set
  cache (built in Phase 4)` on each `self._cache = InMemory*Storage(...)`.

### Task 2 — tab-indented cache sites (6 anchors, 5 files) — commit `7ed2e49`
All 5 files re-verified tab-indented (`grep -cP '^\t'` > 0). Each anchor's leading whitespace matches
its anchor line exactly (two module-level decorators at column 0; in-method fields at 2 tabs):
- **time_parser.py**: `(c) pure-function memo` (column 0) on the `@functools.lru_cache(maxsize=32)`
  `_aligned` decorator.
- **base.py** (two): `(c) pure-function memo` (column 0) on the `@cache` `_declared_hints` decorator;
  `(c) explicitly-invalidated memo (via _invalidate_to_dict_cache)` (2 tabs) on
  `self._to_dict_static_cache`.
- **position.py**: `(c) fill-invalidated memo [pair: _net_quantity_cache / _avg_price_cache]` (2 tabs).
- **handle.py**: `(a) hot-path indicator state [family: catalog.py _SMAState/_EMAState/_MACDHistState/
  _RSIState]` (2 tabs) on `self._buffer`.
- **simulated.py**: `(c-config) venue config snapshot [family: _supported_symbols / _min_order_size /
  _max_order_size]` (2 tabs) on `self._supported_symbols`.

## Verification

- **SC2 GREEN:** `poetry run pytest tests/integration/test_cache_classification.py` → **4 passed**
  under `-W error` (the previously-RED `test_cache_class_anchors_match_live_inventory` arm now passes;
  anchor count 14 == live-site count 14).
- **Anchor inventory:** `grep -rn "CACHE-CLASS:" itrader/` returns exactly 14 anchors, each on a file
  named in the doc's machine-readable live-site block.
- **Task 1 automated verify:** anchor count 8; `git diff` introduces no tab-prefixed line (`^\+\t`) in
  the 4-space files; only comment lines added.
- **Task 2 automated verify:** anchor count 6; no space-indented anchor (`^\+ +# CACHE-CLASS:` empty);
  tab anchors land under `^\+\t`; only comment lines added.
- **No logic touched:** every added line is a `#`-prefixed comment (verified `git diff | grep '^\+[^+]'`
  has no non-comment add). The applied-decorator surface stayed exactly 3 (decorator arm still PASS).
- **Syntax integrity:** `python -m py_compile` clean on all 12 edited files (tab/space hazard avoided).

## Deviations from Plan

None — plan executed exactly as written. Both tasks split by indentation as designed; no tab/space
normalization; no architectural or blocking issue encountered.

## Known Stubs

None. All 14 anchors are complete, inert comment lines referencing the committed map.

## Threat Flags

None. This plan adds only inert single-line comments — no runtime input, control flow, endpoint,
credential, or data flow is introduced. Threats T-05-03 (tab/space) and T-05-04 (accidental hot-path
edit) were mitigated as planned: per-file indentation re-verification at edit time, comment-only diffs,
and a clean `py_compile` gate.

## Self-Check: PASSED
- All 12 modified files contain `# CACHE-CLASS:` anchors (bar_feed.py and base.py carry 2 each) — FOUND
- `grep -rn "CACHE-CLASS:" itrader/` == 14 — FOUND
- commit `f333568` (Task 1) — FOUND
- commit `7ed2e49` (Task 2) — FOUND
- SC2 test 4/4 GREEN — FOUND
