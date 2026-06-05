---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 02
subsystem: dead-code-purge
tags: [M2-11, dead-code, refactor, behavior-preserving]
requires: ["03-01"]
provides: ["dead-module-purge-M2-11"]
affects:
  - itrader/legacy_config.py (deleted)
  - itrader/outils/profiling.py (deleted)
  - itrader/outils/strategy.py (deleted)
  - itrader/events_handler/screener_event_handler.py (deleted)
tech-stack:
  added: []
  patterns: ["D-13 mechanical-delete discipline (re-verify zero importers before each delete)"]
key-files:
  created: []
  modified: []
  deleted:
    - itrader/legacy_config.py
    - itrader/outils/profiling.py
    - itrader/outils/strategy.py
    - itrader/events_handler/screener_event_handler.py
decisions:
  - "Flat itrader/config.py shadow left untouched — its TIMEZONE/FORBIDDEN_SYMBOLS consumers depend on it until the Pydantic collapse in 03-05; absorbed-then-deleted there, not here."
  - "self.cross_up/cross_down calls in my_strategies/* are instance methods on out-of-scope strategy classes, NOT imports of the deleted outils.strategy module — no real importer."
metrics:
  duration_min: 2
  tasks: 1
  files_changed: 4
  completed: 2026-06-05
---

# Phase 3 Plan 02: Dead-Module Purge (M2-11) Summary

Deleted four confirmed-dead modules with zero in-scope importers as an isolated, bisectable, behavior-preserving commit; full suite stays 300 pass / 11 skip / 1 xfail and the behavioral oracle stays byte-exact.

## What Was Built

Removed dead code (D-11 / TD4 / TD5 / KB14 / #32) in a single mechanical-delete commit, kept separate from the storage-seam logic (03-03+) and the pytest move (03-08) so any break is bisectable:

- `itrader/legacy_config.py` — legacy config backward-compat shim (already in mypy overrides)
- `itrader/outils/profiling.py` — dead `speed`/`s_speed` profiling helpers
- `itrader/outils/strategy.py` — dead `cross_up`/`cross_down`/`price_cross_*` module-level helpers
- `itrader/events_handler/screener_event_handler.py` — orphaned duplicate `EventHandler` (the real one is `events_handler/full_event_handler.py`; already in mypy overrides)

## How It Was Verified

- **Pre-delete importer re-grep (D-13):** re-confirmed ZERO in-scope importers for each module's public names before deleting (`legacy_config`, `outils.profiling`, `outils.strategy` / `cross_up`/`cross_down`/`price_cross_*`, `screener_event_handler`). The only `cross_up`/`cross_down` hits were `self.cross_up(...)` instance-method calls inside out-of-scope `my_strategies/*` strategy classes — not module imports.
- **Files gone:** all four `! test -f` checks pass.
- **`import itrader` succeeds** — package import side effects unaffected.
- **No residual references:** `grep -rnE 'legacy_config|outils\.profiling|outils\.strategy|screener_event_handler' itrader/ test/` returns nothing.
- **`make test` green:** 300 passed, 11 skipped, 1 xfailed (collected count unchanged at 312 = identical to pre-delete count; no test imported a deleted name).
- **Behavioral oracle identity:** `test_oracle_behavioral_identity` byte-exact green — behavior preserved.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- Commit `fb7f0c6` exists in git log.
- All four target files confirmed absent (`! test -f` checks pass; `git diff --diff-filter=D` lists exactly the four intended deletions, no unexpected deletions).
