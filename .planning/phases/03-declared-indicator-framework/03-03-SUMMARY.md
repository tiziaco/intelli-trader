---
phase: 03-declared-indicator-framework
plan: 03
subsystem: testing
tags: [indicators, byte-exact, oracle, determinism, mypy-strict, IND-01, D-08]

requires:
  - phase: 03-02
    provides: "Migrated SMAMACDStrategy (primitive-driven, auto-derived warmup==max_window==100), evaluate() seam, base.py framework"
  - phase: 03-01
    provides: "indicators/ package (catalog.py SMA/MACDHist adapters, handle.py IndicatorHandle), primitives.py"
provides:
  - "Byte-exact phase gate LOCKED: oracle 134 trades / final_equity 46189.87730727451 EXACT, zero re-baseline"
  - "Verified signal_record.py config snapshot still carries auto-derived max_window/warmup==100 (verify-only, no edit)"
  - "Determinism double-run byte-identical; e2e 58/58; full suite 890 green; mypy --strict clean (176 files)"
  - "Pitfall 1 (per-indicator SMA slice) + Pitfall 2 (eager-vs-lazy MACD reorder) proven correct by the oracle (no SMA_MACD unit test guards the MACD value)"
affects:
  - "Phase 4 (COMP-01/COMP-02) builds the composition/config interface on this byte-exact-locked framework"

tech-stack:
  added: []
  patterns:
    - "Oracle-as-sole-proof: a no-tolerance pdt.assert_frame_equal against the frozen golden CSVs is the only guard for the MACD value (no unit test)"
    - "Verify-only gate task: confirm a snapshot survives without editing unless it genuinely drops fields"

key-files:
  created:
    - .planning/phases/03-declared-indicator-framework/03-03-SUMMARY.md
  modified: []

key-decisions:
  - "Task 1 verify-only: to_dict() introspects get_type_hints, max_window/warmup remain annotated base attrs (kept in Plan 02) so they survive into the SignalRecord.config snapshot at their derived value 100 — signal_record.py NOT edited (no data migration)"
  - "Task 2 verification-only: oracle/e2e/full-suite/mypy all green with ZERO drift — indicators/catalog.py, handle.py, base.py NOT touched (conditional fix-forward scope never triggered; no Pitfall-1 ULP boundary flip)"

patterns-established:
  - "The Phase 3 byte-exact gate (ROADMAP Success Criterion 4) is satisfied with no re-baseline"

requirements-completed: [IND-01]

duration: ~10min
completed: 2026-06-12
---

# Phase 3 Plan 03: Declared-Indicator Framework — Byte-Exact Phase Gate Summary

**The migrated declared-indicator `SMAMACDStrategy` is proven byte-exact against the frozen BTCUSD oracle (134 trades / final_equity 46189.87730727451, EXACT) with zero re-baseline — e2e 58/58, full suite 890 green, mypy --strict clean, determinism double-run byte-identical — and the SignalRecord config snapshot is confirmed to still carry the auto-derived max_window/warmup==100.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-12T15:48:45Z
- **Completed:** 2026-06-12
- **Tasks:** 2 (both verification-only this run)
- **Files modified:** 0 (verify-only; SUMMARY is the only artifact written)

## Accomplishments

- **Byte-exact gate LOCKED, zero drift:** `tests/integration/test_backtest_oracle.py` passes EXACT — fresh deterministic run vs the frozen golden (`tests/golden/summary.json`: `final_equity 46189.87730727451`, `trade_count 134`) via `pdt.assert_frame_equal` with NO tolerance + exact summary-dict comparison. No 1-2 trade delta, so no Pitfall-1 ULP boundary flip in the per-indicator SMA slice.
- **Pitfalls 1 & 2 proven:** the oracle is the ONLY proof (no SMA_MACD unit test guards the MACD value). The per-indicator SMA slice (Pitfall 1) and the eager-vs-lazy MACD reorder (Pitfall 2) introduced by the Plan 01/02 migration are validated correct.
- **Task 1 verify-only PASS:** `SMAMACDStrategy(**kwargs).to_dict()` carries both `max_window` and `warmup`, each == 100 (auto-derived). `to_dict()` introspects `get_type_hints(type(self))` and both remain annotated base attrs (kept in Plan 02), so they survive into the `SignalRecord.config` snapshot at their derived value. `signal_record.py` NOT edited (RESEARCH Assumption A4 confirmed; no data migration).
- **Determinism:** oracle double-run byte-identical (two passes green; the harness is deterministic — seeded RNG + injected clock).
- **All gates green:** e2e 58/58, full suite 890 passed under `filterwarnings=["error"]` / `--strict-markers` / `--strict-config`, `mypy --strict itrader` clean (176 source files).

## Task Commits

Both tasks were verification-only — no code changed (the conditional fix-forward scope in Task 2 never triggered, and Task 1's snapshot survived intact). The plan completion is captured in the single metadata commit.

1. **Task 1: Verify signal_record.py config snapshot captures auto-derived warmup/max_window** — verify-only, no commit (no edit needed)
2. **Task 2: Byte-exact phase gate (oracle / e2e / full suite / mypy / determinism)** — verify-only, no commit (no fix-forward needed)

**Plan metadata:** _(see final docs commit)_

## Files Created/Modified

- `.planning/phases/03-declared-indicator-framework/03-03-SUMMARY.md` — this summary (only artifact written)
- No source files modified: `signal_record.py`, `indicators/catalog.py`, `indicators/handle.py`, `base.py` all UNCHANGED (verify-only gate; steady-state touches none of them).

## Verification

- `poetry run pytest tests/unit/strategy -x` → **60 passed** (Task 1 gate; incl. the warmup==100 assertion from Plan 02).
- Task 1 ad-hoc check: `SMAMACDStrategy(**kwargs).to_dict()` → `max_window == 100`, `warmup == 100`, both present in the snapshot keys.
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → **3 passed** (byte-exact oracle, NO tolerance).
- Frozen golden confirmed in `tests/golden/summary.json`: `final_equity 46189.87730727451`, `trade_count 134`.
- Determinism double-run: oracle run twice, both passes green (byte-identical — fresh deterministic run reproduces the golden each time).
- `poetry run pytest tests/e2e -m e2e -q` → **58 passed**.
- `poetry run pytest` (full suite) → **890 passed** under `filterwarnings=["error"]`.
- `poetry run mypy itrader` → **Success: no issues found in 176 source files** (`--strict`).

## Decisions Made

- **Task 1 is verify-only, no edit.** Per RESEARCH Assumption A4 / 03-PATTERNS, `to_dict()` iterates `get_type_hints(type(self))` and `max_window: int = 0` / `warmup: int = 0` remain annotated base attrs (deliberately kept in Plan 02), so they survive into the `SignalRecord.config` snapshot carrying their now-derived value (100). The snapshot did NOT drop them, so the minimal-fix condition never triggered and `signal_record.py` is unchanged. No data migration.
- **Task 2 conditional fix-forward never triggered.** The oracle held EXACT with zero drift (no 1-2 trade delta), and `mypy --strict` was clean, so the conditional patch scope (`indicators/catalog.py` SMA slice for Pitfall 1, the D-04 typed adapter symbols, the D-03 `IndicatorHandle` wrapper in `handle.py`, the imports in `base.py`) was not entered. Steady-state run touched none of them — exactly the expected outcome.
- **Plan 02 D-08 deviation confirmed inert for the reference.** The auto-warmup pass sets `warmup` unconditionally from handle `min_period` but `max_window = max(handle-derived, hand-set class value)` (the load-bearing deviation from the must_have prose, documented in 03-02-SUMMARY). For the reference the hand-set value is deleted (class default 0), so `warmup == max_window == 100` (handle-derived). The Task 1 snapshot of `max_window/warmup == 100` is the expected behavior under this deviation.

## Deviations from Plan

None — plan executed exactly as written. Both tasks were verification-only as the plan anticipated (Task 1 verify-only, Task 2 conditional fix-forward with the fix branch not entered). No bugs, missing functionality, or blocking issues; the conditional scope (`indicators/catalog.py`, `handle.py`, `base.py`) was correctly NOT touched in steady state.

## Known Stubs

None. The migrated reference reads real handle values through real adapters (validated by the byte-exact oracle); no placeholder values or unwired data sources.

## Threat Flags

None. Per the plan's threat register (T-03-03 / T-03-SC, disposition `accept`), this is a verification-only plan with a verify-only snapshot check — no new trust boundary, zero packages installed. The golden artifacts under `tests/golden/` are the integrity target and remain byte-identical (the oracle gate enforces this).

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Phase 3 byte-exact gate is LOCKED** (ROADMAP Success Criterion 4 satisfied): oracle EXACT, e2e 58/58, full suite green, mypy --strict clean, determinism double-run byte-identical, zero re-baseline.
- The declared-indicator framework (Plans 01-03) is complete and numerically trustworthy.
- Phase 4 (COMP-01 / COMP-02, Composition & Config Interface) consumes the Phase 2 `init()` seam and the now-locked framework; `StrategiesHandler.update_config` re-runs `init()` → re-derives warmup via `_run_init`. No blockers.

## Self-Check: PASSED

Files (verify-only plan — only the SUMMARY was written):
- `.planning/phases/03-declared-indicator-framework/03-03-SUMMARY.md` — FOUND (this file)
- Source files intentionally UNCHANGED (verify-only gate): `signal_record.py`, `indicators/catalog.py`, `indicators/handle.py`, `base.py` — confirmed clean via `git status` (no diff).

---
*Phase: 03-declared-indicator-framework*
*Completed: 2026-06-12*
