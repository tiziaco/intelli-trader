---
phase: 08-error-subsystem
plan: 01
subsystem: error-subsystem
tags: [enums, config, okx, errorevent, tripwire-leaves]
requires: []
provides:
  - "FailureClass enum (5 members) in core/enums/system.py, barrel-exported"
  - "HaltReason +4 tripwire members (D-16): SETTLEMENT_FAILURE, ORDER_ROUTE_ERRORS, ADMISSION_ERRORS, LOOP_BACKSTOP"
  - "FailureRateSettings on SafetySettings.failure_rate (D-14 defaults), config-barrel-exported"
  - "okx fill-translation counted ErrorEvent(source=okx_exchange, operation=fill-translation) on both drain paths"
affects:
  - "08-02 (ErrorPolicy _POLICY map reads FailureRateSettings + classifies against FailureClass/HaltReason)"
  - "08-02/08-03 (okx counted emit is the off-thread SETTLEMENT tripwire input)"
tech-stack:
  added: []
  patterns:
    - "ThrottleSettings template reused for FailureRateSettings (ConfigDict extra=forbid + default())"
    - "okx cancel-arm ErrorEvent emit pattern reused for fill-translation (TYPE + fixed literal scrub)"
key-files:
  created:
    - tests/unit/core/test_failure_class.py
  modified:
    - itrader/core/enums/system.py
    - itrader/core/enums/__init__.py
    - itrader/config/safety.py
    - itrader/config/__init__.py
    - itrader/execution_handler/exchanges/okx.py
    - tests/unit/core/test_halt_reason.py
    - tests/unit/config/test_safety_config.py
    - tests/unit/execution/test_okx_exchange.py
decisions:
  - "FailureClass co-located in core/enums/system.py beside HaltReason (D-08 Claude discretion)"
  - "FailureRateSettings uses NAMED per-class (threshold, window_s) fields, not opaque tuples (D-14 discretion — P9 allowlist targets individual keys)"
  - "SETTLEMENT window default = 60.0s nominal (halt-on-first at threshold 1, window irrelevant)"
  - "Both okx drain paths share one module-level fixed-literal message constant _FILL_TRANSLATION_ERROR_MSG"
metrics:
  duration: ~15m
  completed: 2026-07-15
status: complete
---

# Phase 8 Plan 01: Wave-1 Error-Subsystem Leaf Primitives Summary

Landed the three additive, zero-intra-phase-dependency leaves the CF-1 tripwire and ERROR-route consumer build on: the `FailureClass` enum + 4 `HaltReason` tripwire members (D-08/D-16), the `FailureRateSettings` Pydantic model on `SafetySettings.failure_rate` (D-14/D-15), and the D-10 okx FILL_TRANSLATION counted `ErrorEvent` closing the invisible "lost venue fill" hole on both drain paths (ERR-04).

## What Was Built

### Task 1 — FailureClass enum + 4 HaltReason members (`core/enums/system.py`, 4-space)
- New `FailureClass(Enum)`: `SETTLEMENT`, `ORDER_IO`, `ADMISSION`, `LOOP_BACKSTOP`, `FILL_TRANSLATION` with descriptive lowercase-hyphen `.value`s (not persisted). Docstring pins the 1:1 map onto tripwire `HaltReason`s and the FILL_TRANSLATION→SETTLEMENT_FAILURE reuse.
- `HaltReason` gained 4 members: `SETTLEMENT_FAILURE`, `ORDER_ROUTE_ERRORS`, `ADMISSION_ERRORS`, `LOOP_BACKSTOP` (new wire strings). The 5 existing members are byte-unchanged — no durable-record migration.
- Both re-exported from the `itrader.core.enums` barrel (import block + `__all__`).
- Commits: `3a34a1a5` (test/RED), `c908e4b5` (feat/GREEN).

### Task 2 — FailureRateSettings model (`config/safety.py`, 4-space)
- New `FailureRateSettings(BaseModel)` modelled on `ThrottleSettings` (`ConfigDict(extra="forbid")` + `default()`). Named per-class `(threshold: int, window_s: float)` fields carrying exact D-14 defaults: SETTLEMENT 1/60.0 (halt-on-first), ORDER_IO 3/60.0, ADMISSION 3/300.0, LOOP_BACKSTOP 5/60.0. FILL_TRANSLATION reuses SETTLEMENT (no dedicated field). No money types — int/float supervisor tunables.
- `SafetySettings.failure_rate` field added beside `throttle` (default_factory); reachable from eager `SystemConfig.default().safety.failure_rate` (inertness-safe, pydantic-only).
- Exported from the `itrader.config` barrel.
- Commits: `e1ffe4a7` (test/RED), `45f54ebf` (feat/GREEN).

### Task 3 — okx FILL_TRANSLATION counted ErrorEvent (`okx.py`, TABS)
- Both per-trade translation-skip drain paths (`_consume_fills` and `catch_up_missed_fills`) changed from log-ONLY to log + counted `ErrorEvent` emit: `source="okx_exchange"`, `operation="fill-translation"`, `error_type=type(exc).__name__`, `severity=ErrorSeverity.ERROR`, `time=datetime.now(timezone.utc)`.
- Shared module-level fixed-literal message `_FILL_TRANSLATION_ERROR_MSG` — no `str(exc)`, no raw trade/connector payload (T-05-27 / V7 secret scrub). Local `exc_info=True` log retained.
- Unit tests drive one iteration of each drain path (`_handle_trade` monkeypatched to raise a secret-bearing exception) and assert exactly one scrubbed `ErrorEvent` per path, `error_type` == exception class name, `error_message` == the fixed literal (secret substring absent).
- Commit: `2b9bb52e` (feat).

## Deviations from Plan

**1. [Rule 3 - Blocking] Updated existing `test_halt_reason.py` characterization test**
- **Found during:** Task 1
- **Issue:** `test_halt_reason_has_exactly_the_five_reachable_members` asserted the `HaltReason` member set was *exactly* the 5 original reasons. Adding the 4 D-16 tripwire members (a required Task-1 change) breaks that assertion — a blocking test failure.
- **Fix:** Renamed to `test_halt_reason_has_the_five_original_plus_four_tripwire_members`, updated the expected set to the 5 originals + 4 D-16 members, and added `test_halt_reason_d16_tripwire_member_values` asserting the new wire strings. The existing `.value` and round-trip assertions for the 5 originals are unchanged (proving additive-only).
- **Files modified:** tests/unit/core/test_halt_reason.py
- **Commit:** 3a34a1a5

No other deviations — the three source changes match the plan exactly.

## Verification

All run with the worktree PYTHONPATH prefix (`.venv` editable-install shadow guard):
- `tests/unit/core tests/unit/config tests/unit/execution` — **467 passed**.
- `tests/integration/test_backtest_oracle.py` — **3 passed** (byte-exact 134 / 46189.87730727451; enum/config additions inert, okx edit backtest-dark).
- `tests/integration/test_okx_inertness.py` — **4 passed** (no new heavy import; okx already imported ErrorEvent).
- `mypy itrader/core/enums/system.py itrader/config/safety.py` — clean (2 files).

okx.py is under the deferred-typing mypy overrides (live subsystem), so it is not in the strict gate; the two new emits reuse the already-imported `ErrorEvent`/`ErrorSeverity`/`datetime`/`timezone` symbols (no new imports).

## Threat Mitigations Applied

- **T-08-01 (Information Disclosure, okx fill-translation ErrorEvent):** bind `type(exc).__name__` + fixed literal only; no `str(exc)`/payload. Tests assert the secret substring is absent.
- **T-08-03 (Tampering, silent fill loss AUD-3):** log-only → counted ErrorEvent on BOTH drain paths so a skipped settlement is visible and (downstream) trips SETTLEMENT halt-on-first.
- **T-08-05 (mass-assign, FailureRateSettings):** `ConfigDict(extra="forbid")` — test asserts `FailureRateSettings(bogus=1)` raises `pydantic.ValidationError`.

## Notes for Downstream Plans (08-02 / 08-03)

- `FailureRateSettings` exposes named fields (`settlement_threshold`, `settlement_window_s`, `order_io_threshold`, `order_io_window_s`, `admission_threshold`, `admission_window_s`, `loop_backstop_threshold`, `loop_backstop_window_s`) — the `_POLICY` map builder reads these directly (no tuple unpacking).
- The okx counted `ErrorEvent` lands OFF-THREAD on the **ERROR route** (`ErrorHandler.on_error`), NOT `ErrorPolicy.on_handler_error` where the tripwire deque lives. The FILL_TRANSLATION counting seam (shared tripwire object vs ErrorHandler halt-on-first for SETTLEMENT-classed ErrorEvents) is still the open design point 08-02/08-03 must resolve (Open Question #1).

## Known Stubs

None — all three leaves are fully wired and reachable; no placeholder data or TODO stubs introduced.
