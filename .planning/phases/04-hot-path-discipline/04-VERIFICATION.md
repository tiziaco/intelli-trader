---
phase: 04-hot-path-discipline
verified: 2026-06-24T00:00:00Z
status: passed
score: 5/5 must-haves verified (1 owner-acknowledged)
overrides_applied: 0
human_verification:
  - test: "Run a clean W1 benchmark on a quiet machine and confirm the re-frozen baseline of 238.5s is an accurate Phase-4 reference"
    expected: "A quiet-machine run should clock meaningfully faster than 238.5s, confirming the contended-machine freeze does not understate Phase-4 performance for Phase-5 planning"
    why_human: "Gate (b) verdict rests entirely on the same-machine A/B (mean -7.8%, best -9.8%) — which is solid — but the re-frozen W1-BASELINE.json was committed on a contended machine (238.5s vs the cool-night 199.4s baseline). The owner accepted this with provenance recorded. The practical concern is whether Phase 5 will be judged against an inflated absolute; this is an owner-level decision already made, but a human should confirm awareness before Phase 5 begins measuring against it."
    resolution: "ACKNOWLEDGED by owner 2026-06-24 during phase-4 close. Owner is aware the 238.5s baseline is contended/inflated and that Phase-5 deltas must be read against it accordingly (or W1-BASELINE.json re-frozen on a quiet machine before Phase 5). Phase marked verified/passed on this acknowledgement; gate (b) substance already PASS on the A/B independent of the absolute."
---

# Phase 4: Hot-Path Discipline — Verification Report

**Phase Goal:** The per-bar path stops paying structural waste on two behavior-only sinks — hot-loop logging and re-resolved type hints — neither of which has a numeric surface, so they bundle cleanly into one discipline phase.

**Verified:** 2026-06-24
**Status:** passed (1 human item owner-acknowledged at close)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Hot-loop log calls are level-gated (cached `isEnabledFor`/bool); per-bar admission-rejection warnings are demoted/sampled; `debug()` calls removed from per-bar path | ✓ VERIFIED | `itrader/logger.py`: 7 `isEnabledFor` gates (one per wrapper method). `itrader/order_handler/admission/admission_manager.py:247`: `isEnabledFor(WARNING)` guard + `warning()` (not `error()`). 8 debug calls deleted from `position_manager.py` / `cash_manager.py` / `admission_manager.py`. KEEP lines (`'Strategy signal'`, `'Order executed'`) confirmed present. |
| 2 | `get_type_hints` is memoized per class in `Strategy.to_dict` (resolved once per class, not per signal snapshot) | ✓ VERIFIED | `itrader/strategy_handler/base.py:75`: `@cache def _declared_hints(cls)`. Both hot call sites route through it — `to_dict:377` and `_apply_params:166`. `grep -c "get_type_hints(type(self))"` = 0. |
| 3 | No emitted-log content or signal-snapshot content changes on any oracle/e2e-observed path | ✓ VERIFIED | Oracle passes byte-exact (134 / 46189.87730727451). 8/8 `test_logging_gate.py` tests green, including `test_admission_line_warning_renders_same_content_as_error` (content-equivalence at WARNING vs prior error) and `test_below_level_emits_nothing`. `to_dict` snapshot regression in `test_strategy.py::test_to_dict_snapshot_regression_full_surface` green. |
| 4 | Gate (a): byte-exact SMA_MACD oracle green (134 / 46189.87730727451); `mypy --strict` clean; determinism double-run byte-identical | ✓ VERIFIED | `tests/integration/test_backtest_oracle.py` — 3 passed (oracle byte-exact). `mypy` — no issues found in 6 source files. Oracle double-run held after every task per SUMMARY. |
| 5 | Gate (b): clean W1 benchmark shows measurable improvement vs prior baseline; re-frozen as new locked reference | ✓ VERIFIED (owner-acknowledged) | Same-machine A/B: mean -7.8% / best -9.8% (well above >=5% bar), attributed to PERF-03+PERF-04, topology byte-identical — gate verdict PASS on the A/B. `W1-BASELINE.json` re-frozen at 238.5s on a contended machine under explicit owner sign-off (provenance in `04-PERF-ATTRIBUTION.md §7` + commit `01cb764`). Owner ACKNOWLEDGED the contended/inflated absolute at phase close (2026-06-24); Phase-5 deltas to be read against it accordingly or re-frozen cool beforehand. |

**Score:** 5/5 truths verified (truth 5 owner-acknowledged — gate (b) substance PASS on A/B; re-freeze absolute is contended-machine-inflated by accepted owner decision)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/logger.py` | Central `isEnabledFor` gate + `_DISABLE_LOGS` kill-switch (D-02, D-08) | ✓ VERIFIED | `_stdlib` cached in `__init__` (line 222), carried through `bind()` (line 249). 7 `isEnabledFor` guards in wrapper methods (lines 255, 260, 265, 272, 277). `_DISABLE_LOGS` module-level bool (line 63). `_env_disable_logs()` helper (lines 45-56). `exception()` left as always-emit. |
| `itrader/config/settings.py` | `disable_logs: bool = False` field (D-08) | ✓ VERIFIED | Line 35: `disable_logs: bool = False` with comment citing D-08 Phase 4 PERF-03. |
| `itrader/order_handler/admission/admission_manager.py` | Demoted warning-level admission-rejection log + `isEnabledFor(WARNING)` guard (D-01) | ✓ VERIFIED | Line 247: `if self.logger._stdlib.isEnabledFor(logging.WARNING):`. Line 248: `self.logger.warning(...)`. Audit trail (`add_state_change` + `add_order`, lines 252-257) untouched. No `self.logger.error` call with `validation_result` in it. |
| `itrader/portfolio_handler/position/position_manager.py` | Signed-off debug deletions (D-04) | ✓ VERIFIED | `grep -n "\.debug("` returns only `'Scale-in leverage clamped'` — not a D-04 target. `'Position updated'` and `'Position market values updated'` debug calls are gone. |
| `itrader/portfolio_handler/cash/cash_manager.py` | Signed-off debug deletions (D-04) | ✓ VERIFIED | `grep -n "\.debug("` shows only `'Transaction cash flow processed'` (line 310) and `'Borrow interest accrued'` (line 411) — neither in the D-04 delete list. The 5 D-04 targets ('Fill cash flow applied', 'Cash reserved', 'Cash reservation released', 'Margin locked', 'Margin released') produce zero matches. |
| `itrader/strategy_handler/base.py` | `_declared_hints` @cache helper; both call sites routed through it (D-05) | ✓ VERIFIED | Lines 74-76: `@cache def _declared_hints(cls)`. Line 166: `hints = _declared_hints(type(self))` (_apply_params). Line 377: `for nm in _declared_hints(type(self))` (to_dict). `get_type_hints(type(self))` count = 0 (both sites migrated). |
| `tests/unit/core/test_logging_gate.py` | Gate-transparency + admission-content + disable-logs drift-lock tests (D-06) | ✓ VERIFIED | 8 tests present; all 8 green. `pytestmark = pytest.mark.unit` declared. |
| `tests/unit/strategy/test_type_hints_equivalence.py` | Equivalence + cache-identity + subclass-keying drift-lock test (D-07) | ✓ VERIFIED | 3 tests (equivalence keys+order, cache-identity `is`, subclass keying). All 3 green. `pytestmark = pytest.mark.unit` declared. |
| `.planning/phases/04-hot-path-discipline/04-LOGGING-AUDIT.md` | Written D-06 behavior-preservation audit | ✓ VERIFIED | File exists. `grep -c "D-0"` = 16 (>= required 4). Enumerates 3 change classes (central-gate D-02 / demote D-01 / delete-debug D-04). States oracle/e2e do not observe logs. References `test_logging_gate.py`. |
| `perf/results/W1-BASELINE.json` | Re-frozen Phase-4 W1 reference (wall_clock_s + peak_mem_mb) | ✓ VERIFIED (with caveat) | `wall_clock_s: 238.5`, `peak_mem_mb: 162.7`, `frozen_at: 2026-06-24`. `oracle_provenance.final_equity: "46189.87730727451"` (STRING constant, unchanged). Schema v1 preserved. File is tracked (not gitignored). Provenance note: frozen on a contended machine under explicit owner sign-off; absolute is inflated vs cool-night. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `ITraderStructLogger.__init__` | `self._stdlib` | `logging.getLogger(log_name)` cached at construction | ✓ WIRED | Line 222 sets `self._stdlib`. |
| `ITraderStructLogger.bind()` | `new_logger._stdlib` | `__new__` + explicit carry-over | ✓ WIRED | Line 249: `new_logger._stdlib = self._stdlib`. |
| `ITraderStructLogger.debug/info/warning/error/critical` | `self._stdlib.isEnabledFor(<level>)` | short-circuit before structlog pipeline | ✓ WIRED | 5 wrapper methods each gate on `_DISABLE_LOGS or not self._stdlib.isEnabledFor(...)`. |
| `admission_manager.py` validation rejection | `self.logger.warning(...)` | demoted level + local `isEnabledFor(WARNING)` guard | ✓ WIRED | Line 247-249: guard wraps the demoted call. Audit trail (lines 252-257) is outside the guard. |
| `Strategy.to_dict` | `_declared_hints(type(self))` | memoized per-class cache lookup | ✓ WIRED | Line 377 uses `_declared_hints` instead of `get_type_hints(type(self))`. |
| `Strategy._apply_params` | `_declared_hints(type(self))` | memoized per-class cache lookup | ✓ WIRED | Line 166 uses `_declared_hints`. |
| `make perf-baseline` equivalent | `perf/results/W1-BASELINE.json` | direct invocation with `ITRADER_LOG_LEVEL=ERROR PYTHONPATH=$PWD` | ✓ WIRED | Commit `01cb764` re-froze the file. Soft guard (`--check`) ran at 234.9s, Δ -1.5%, exit 0. |

---

## Data-Flow Trace (Level 4)

Not applicable — this phase modifies logging infrastructure and memoization. No new data-rendering components introduced. The oracle run (behavioral spot-check below) serves as the end-to-end data-flow proof.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact (134 / 46189.87730727451) | `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed | ✓ PASS |
| Logging gate tests all green | `PYTHONPATH="$PWD" poetry run pytest tests/unit/core/test_logging_gate.py -v` | 8 passed | ✓ PASS |
| Type-hint equivalence + strategy tests | `PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy/test_type_hints_equivalence.py tests/unit/strategy/test_strategy.py -v` | 22 passed | ✓ PASS |
| mypy --strict clean on all touched files | `PYTHONPATH="$PWD" poetry run mypy itrader/logger.py itrader/config/settings.py ... itrader/strategy_handler/base.py` | Success: no issues found in 6 source files | ✓ PASS |

---

## Probe Execution

No probes declared (phase uses `make perf-w1` harness, not `probe-*.sh` scripts). Step 7c: SKIPPED (no probe-*.sh files applicable).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PERF-03 | 04-01-PLAN.md | Hot-path logging is level-gated; per-bar admission-rejection warnings demoted; `debug()` calls removed from per-bar path | ✓ SATISFIED | Central `isEnabledFor` gate in `logger.py`; admission log demoted `error→warning`; 8 debug deletions applied; drift-lock tests green. |
| PERF-04 | 04-02-PLAN.md | `get_type_hints` memoized per class in `Strategy.to_dict` — resolved once per class, not per snapshot | ✓ SATISFIED | `@cache def _declared_hints(cls)` in `base.py`; both call sites (to_dict + _apply_params) route through it; equivalence + snapshot tests green. |

**Traceability note:** `REQUIREMENTS.md` traceability table still shows PERF-03 and PERF-04 as "Pending" — this is a static planning artifact not updated by the phase (consistent with prior phases: TOOL-01/02/04 and PERF-01/02 were also left as "Complete" only after the merge PR updated the doc). The implementation is complete in code; the doc update is a housekeeping item for the orchestrator.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

No TBD/FIXME/XXX markers, no unreferenced debt markers, no stub returns, no float-for-money in modified files. The remaining `debug()` calls in `cash_manager.py` (lines 310, 411) are not in the D-04 delete list — they are legitimate post-Phase-3 additions ("Transaction cash flow processed", "Borrow interest accrued") and are NOT hot-path-only internal mechanics targeted by this phase.

---

## Human Verification Required

### 1. Confirm Awareness of Contended-Machine Re-Freeze Before Phase 5 Begins

**Test:** Read `04-PERF-ATTRIBUTION.md` §7 and `W1-BASELINE.json` `frozen_at`/`metric` fields. Confirm you are aware that `wall_clock_s: 238.5` is the Phase-5 regression reference and that it was frozen on a contended machine (not a quiet-night machine), per the owner-accepted provenance record. Optionally run `make perf-baseline` on a quieter machine to get a cleaner Phase-5 reference if one is desired.

**Expected:** Owner is aware of the contended-machine provenance; Phase 5 will interpret gate (b) deltas as A/B comparisons, not absolute comparisons against 238.5s. Alternatively, owner re-freezes on a quiet machine to set a cleaner baseline before Phase 5 proceeds.

**Why human:** The gate (b) A/B verdict (mean -7.8%) is machine-verifiable and already recorded. The question is whether the re-frozen absolute (238.5s) is the right reference for Phase 5 — that is a judgment call the owner already made (with provenance recorded), but a human confirmation before the next phase prevents accidental misinterpretation. This cannot be verified programmatically.

---

## Gaps Summary

No blockers. All four must-have truths with clear programmatic evidence are VERIFIED:

- Central `isEnabledFor` gate is live in all 5 wrapper methods (D-02)
- `_DISABLE_LOGS` kill-switch is live (D-08)
- Admission-rejection log is demoted `error→warning` with local `isEnabledFor(WARNING)` guard (D-01)
- 8 signed-off internal-mechanics `debug()` calls are deleted; 4 KEEP lines are present (D-04)
- D-06 drift lock (written audit + 8-test `test_logging_gate.py`) is in place
- `_declared_hints` @cache helper in `strategy_handler/base.py` memoizes `get_type_hints` per concrete class (D-05)
- Both call sites (to_dict + _apply_params) route through `_declared_hints` (D-05)
- D-07 equivalence + cache-identity + snapshot tests all green
- Oracle byte-exact (134 / 46189.87730727451); mypy --strict clean; all suites green
- `W1-BASELINE.json` re-frozen with correct schema and STRING oracle constant

The one UNCERTAIN item (Truth 5) is not a code gap — the A/B gate is conclusively PASS. The human item is a forward-looking awareness check about the contended-machine freeze absolute being Phase 5's regression reference.

---

_Verified: 2026-06-24_
_Verifier: Claude (gsd-verifier)_
