---
phase: 02-m2a-identity-money-determinism
plan: 01
subsystem: infra
tags: [mypy, uuid-utils, uuidv7, pytest, poetry, typecheck]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: run-path import fix + frozen golden oracle + conftest DIR_MARKERS auto-marking
provides:
  - uuid-utils ^0.16.0 + mypy ^2.1.0 installed and importable in the .venv
  - mypy --strict gate (`make typecheck`) with documented per-module deferral overrides (D-05/D-06)
  - conftest DIR_MARKERS registration for test_outils + test_core (auto-unit marker)
  - red-but-importing UUID Wave 0 test scaffold (M2-01 contract: stdlib uuid.UUID, uniqueness, time-order)
affects: [02-02 money-clock-scaffolds, 02-03 uuid-implementation, 02-07 strict-clean-pass, all-phase-02-plans]

# Tech tracking
tech-stack:
  added: [uuid-utils ^0.16.0, mypy ^2.1.0]
  patterns: [mypy strict gate with [[tool.mypy.overrides]] deferral excludes, conftest DIR_MARKERS path-based unit marking, red-but-collecting Wave 0 test scaffold]

key-files:
  created: [test/test_outils/test_id_generator.py, .planning/phases/02-m2a-identity-money-determinism/02-01-SUMMARY.md]
  modified: [pyproject.toml, poetry.lock, Makefile, test/conftest.py]

key-decisions:
  - "mypy 2.1.0 config keys (python_version/strict/files/ignore_errors/ignore_missing_imports/[[tool.mypy.overrides]]) validated against installed version before commit (Pitfall 6)"
  - "make typecheck stands up the gate only — 939 errors expected and deferred to Plan 07; the gate's job here is to merely execute"
  - "UUID scaffold type assertion is the binding red contract (current int idgen); uniqueness/ordering pass incidentally on ints — acceptable"

patterns-established:
  - "mypy strict gate: [tool.mypy] strict=true files=[itrader] + first override (ignore_errors) for 7 deferred D-live/D-sql/D-oanda/D-screener modules + second override (ignore_missing_imports) for ta/pandas_ta/ccxt"
  - "Wave 0 scaffold: tests precede implementation (D-15) — import the target, assert the locked contract, collect cleanly, stay red until impl lands"

requirements-completed: [M2-01, M2-02, M2-03, M2-05]

# Metrics
duration: ~6min
completed: 2026-06-04
---

# Phase 2 Plan 01: Wave 0 Infrastructure Summary

**Installed uuid-utils + mypy, stood up the `make typecheck` strict gate with per-subsystem deferral overrides (D-05/D-06), registered test_outils/test_core markers, and landed the red UUIDv7 Wave 0 test scaffold every downstream Phase 2 plan depends on.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-04 (continuation from Task 1 checkpoint approval)
- **Completed:** 2026-06-04
- **Tasks:** 2 (Tasks 2-3; Task 1 was a blocking-human checkpoint, approved by user)
- **Files modified:** 6 (4 modified, 2 created)

## Accomplishments
- Installed the two program-locked deps: `uuid-utils ^0.16.0` (UUIDv7) and `mypy ^2.1.0` (dev), committed to `poetry.lock`
- Added `[tool.mypy]` strict config (`python_version="3.13"`, `strict=true`, `files=["itrader"]`) with a `ignore_errors` override listing all 7 deferred subsystems (each tagged D-live/D-sql/D-oanda/D-screener) and an `ignore_missing_imports` override for `ta`/`pandas_ta`/`ccxt`
- Wired `make typecheck` (→ `poetry run mypy itrader`) + added `typecheck` to `.PHONY`; verified it executes (reports 939 errors, deferred to Plan 07)
- Registered `test_outils` + `test_core` in conftest `DIR_MARKERS` (auto-`unit` marker under `--strict-markers`)
- Created the red-but-collecting UUID Wave 0 scaffold asserting the M2-01 contract (stdlib `uuid.UUID`, uniqueness, uuid7 time-ordering)

## Task Commits

Each task was committed atomically:

1. **Task 1: Verify + install uuid-utils and mypy** — blocking-human checkpoint (Package Legitimacy Gate); approved by user "approved" — no code commit
2. **Task 2: Install deps + add mypy strict config + make typecheck gate** — `3ec3f89` (chore)
3. **Task 3: Register test dirs + create UUID Wave 0 test scaffold** — `0d5d1c3` (test)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `pyproject.toml` - Added `uuid-utils`/`mypy` deps + `[tool.mypy]` strict config + two `[[tool.mypy.overrides]]` blocks (deferral + missing-imports)
- `poetry.lock` - Pinned uuid-utils 0.16.0, mypy 2.1.0 (+ ast-serialize, librt, mypy-extensions, pathspec)
- `Makefile` - Added `typecheck:` target (mirrors `test:` style, tab-indented) + `typecheck` in `.PHONY`
- `test/conftest.py` - Added `"test_outils": "unit"` and `"test_core": "unit"` to `DIR_MARKERS`
- `test/test_outils/test_id_generator.py` - M2-01 UUID Wave 0 scaffold (red until Plan 03)

## Decisions Made
- Validated mypy 2.1.0 accepts all config keys via `poetry run mypy --help` before committing (Pitfall 6 — mypy 2.x is newer than common knowledge).
- Both `test_outils` and `test_core` registered here even though Plan 02 creates the actual `test_core` files — conftest is a single shared file owned by this plan and registration is idempotent (path-based hook coexists with Plan 02's module-level marks).
- Money/clock scaffolds intentionally NOT created here — co-located with Plan 02 (which builds those modules) to avoid a same-wave scaffold race. This plan owns only the UUID scaffold (consumed by Plan 03 in a later wave).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. `poetry add` placed both dep lines automatically; all 7 deferral override module paths were validated against real package paths before committing.

## Known Stubs
None. The UUID test scaffold is an intentional red-but-collecting Wave 0 test (per D-15 strategy), not a stub — it is documented as red pending Plan 03's `IDGenerator` implementation and must NOT be made green here.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `make typecheck` gate is live; every downstream Phase 2 plan can verify against it (errors remain until Plan 07's strict-clean pass).
- `test_outils` + `test_core` test dirs collect under `--strict-markers`; Plan 02 can drop `test_core` money/clock scaffolds without touching conftest.
- UUID scaffold is red and ready for Plan 03 to turn green by swapping `IDGenerator` to `uuid_utils.compat.uuid7()`.

## Self-Check: PASSED

- FOUND: test/test_outils/test_id_generator.py
- FOUND: .planning/phases/02-m2a-identity-money-determinism/02-01-SUMMARY.md
- FOUND commit: 3ec3f89 (Task 2)
- FOUND commit: 0d5d1c3 (Task 3)

---
*Phase: 02-m2a-identity-money-determinism*
*Completed: 2026-06-04*
