---
phase: 01-config-centralization
plan: 02
subsystem: infra
tags: [enum, halt-reason, live-safety, wire-compatibility, cf-8, d-10]

# Dependency graph
requires:
  - phase: v1.7 (live operating mode, SystemStatus.HALTED + halt() free strings)
    provides: "live_trading_system.halt(reason: str) call sites and durable halt records"
provides:
  - "Typed HaltReason(Enum) in core/enums/system.py — 4 minimal members, wire values preserved"
  - "core/enums barrel re-exports HaltReason (+ __all__ entry)"
  - "live_trading_system.py:810 baseline guard emits HaltReason.BASELINE_RESIDUAL.value (off-vocabulary free string retired)"
affects: [safety-controller (P8 — halt() signature + remaining 3 literals), error-subsystem]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typed halt-reason vocabulary as a bare Enum (matches SystemStatus style) with .value = existing wire string, so durable records persisted as strings still resolve (no data migration)"
    - "Scope-split retirement: P1 defines the enum + retires the one free string; halt(reason: str) signature migration deferred to P8 (D-11)"

key-files:
  created:
    - tests/unit/core/test_halt_reason.py
  modified:
    - itrader/core/enums/system.py
    - itrader/core/enums/__init__.py
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "HaltReason is MINIMAL per D-10 — exactly the 4 reasons that reach halt()/_update_status(halt_reason=) today; no DRIFT (comment-only) and no PAUSED_ON_DISCONNECT (a pause, not a halt)"
  - "Bare Enum (NOT str, Enum) to match SystemStatus; .value strings byte-preserved (baseline-residual / connector-fatal / reconciliation-unresolved / durable-halt) for durable-record wire compatibility (T-02-01)"
  - "Only the baseline-residual free string at live_trading_system.py:810 retired in P1; the other 3 literals + the halt(reason: str) signature change stay deferred to P8's SafetyController (D-11)"
  - "core/enums/system.py stays stdlib-only (no itrader import added) — inertness/import surface unchanged (T-02-03)"

patterns-established:
  - "Wire-preserving enum retirement: introduce the typed member with .value == the retired free string, swap the call site to Member.value, leaving the literal alive only on the enum definition line (directory-wide grep gate proves the retirement)"

requirements-completed: [CFG-05]

coverage:
  - id: D1
    description: "HaltReason has exactly the 4 minimal members (D-10)"
    requirement: CFG-05
    verification:
      - kind: unit
        ref: "tests/unit/core/test_halt_reason.py#test_halt_reason_has_exactly_the_four_minimal_members"
        status: pass
    human_judgment: false
  - id: D2
    description: "Each member .value equals its existing wire string (durable records still resolve)"
    requirement: CFG-05
    verification:
      - kind: unit
        ref: "tests/unit/core/test_halt_reason.py#test_halt_reason_member_values_are_the_existing_wire_strings"
        status: pass
      - kind: unit
        ref: "tests/unit/core/test_halt_reason.py#test_halt_reason_wire_strings_round_trip_to_members"
        status: pass
    human_judgment: false
  - id: D3
    description: "No DRIFT / PAUSED_ON_DISCONNECT member (D-10 no-dead-members)"
    requirement: CFG-05
    verification:
      - kind: unit
        ref: "tests/unit/core/test_halt_reason.py#test_halt_reason_excludes_drift_and_paused_on_disconnect"
        status: pass
    human_judgment: false
  - id: D4
    description: "baseline-residual free string retired at live_trading_system.py:810 — survives only on the enum .value line (CF-8)"
    requirement: CFG-05
    verification:
      - kind: command
        ref: "grep -rn baseline-residual itrader/ → exactly 1 line (core/enums/system.py:86 .value)"
        status: pass
    human_judgment: false
  - id: D5
    description: "SMA_MACD oracle byte-exact + OKX inertness green (live-only, backtest-dark)"
    requirement: CFG-05
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py + test_okx_inertness.py (5 passed)"
        status: pass
    human_judgment: false

metrics:
  duration_minutes: 12
  completed_date: 2026-07-09
  tasks_completed: 2
  files_created: 1
  files_modified: 3

status: complete
---

# Phase 01 Plan 02: HaltReason Enum (CFG-05 / CF-8) Summary

Introduced a typed `HaltReason(Enum)` and retired the one off-vocabulary free-string halt reason
(`baseline-residual`) at `live_trading_system.py:810`, so every reachable live-path halt reason now has a
typed, wire-compatible vocabulary an operator / control-plane can classify.

## What Was Built

- **`HaltReason(Enum)`** in `itrader/core/enums/system.py` (4-space indent, stdlib-only) with exactly the
  four members that reach `halt()` / `_update_status(halt_reason=)` today —
  `BASELINE_RESIDUAL` / `CONNECTOR_FATAL` / `RECONCILIATION_UNRESOLVED` / `DURABLE_HALT`. Each `.value` is
  the existing wire string, so durable halt records persisted before the change still resolve (no
  migration). Per D-10 no dead members: `DRIFT` (comment-only) and `PAUSED_ON_DISCONNECT` (a
  `pause_submission` reason) are deliberately absent.
- **Barrel export** — `HaltReason` re-exported from the `core/enums` package (`__init__.py` import +
  `__all__`) and added to `system.py`'s module `__all__`.
- **Retired free string** — `live_trading_system.py:810` (the session-start baseline guard) now passes
  `HaltReason.BASELINE_RESIDUAL.value` instead of a bare `'baseline-residual'` literal. `halt(reason: str)`
  stays wire-compatible; the signature migration is P8's job (D-11).
- **Unit test** — `tests/unit/core/test_halt_reason.py` (TDD RED→GREEN): 4-member, 4-wire-value,
  value-to-member round-trip, and 2-absence assertions.

## Tasks

| Task | Name | Type | Commit |
| ---- | ---- | ---- | ------ |
| 1 | Author the failing HaltReason unit test | test (RED) | 64431026 |
| 2 | Define HaltReason enum + retire baseline-residual free string | feat (GREEN) | 7383b1fa |

## Verification (real command output)

- `poetry run pytest tests/unit/core/test_halt_reason.py -x -q` → **4 passed**.
- `grep -rn "'baseline-residual'\|"baseline-residual"" itrader/` → **exactly 1 line**
  (`itrader/core/enums/system.py:86` — the enum `.value` definition; the call site no longer carries the
  bare literal).
- `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q`
  → **5 passed** (oracle byte-exact 134 / `46189.87730727451`; OKX import-inertness sentinel green).
- `poetry run mypy itrader/core/enums/system.py itrader/core/enums/__init__.py` → **Success: no issues**.

## Deviations from Plan

None — plan executed exactly as written. `HaltReason` was authored as a bare `Enum` (not `str, Enum`) per
the plan and the SystemStatus style donor; the RESEARCH member/value table was used verbatim.

## Threat Mitigations Applied

- **T-02-01 (Tampering — wire strings):** the test asserts every `HaltReason.value` equals its existing
  wire string and round-trips value→member, so durable halt records persisted before the change still
  resolve (no data migration).
- **T-02-02 (Repudiation — off-vocabulary reason):** the `baseline-residual` free string is retired to a
  typed member, so every reachable halt reason is classifiable (the CF-8 motivation).
- **T-02-03 (Info Disclosure — import surface, accept):** `core/enums/system.py` stays stdlib-only; the
  OKX inertness gate confirms no import-surface change.

## Deferred (P8 — DO NOT LOSE)

Per LOCKED assumption A2 / D-11, the REMAINDER is deferred to the SafetyController phase (P8) and tracked
in `.planning/todos/pending/off-vocabulary-halt-reason-baseline-residual-wr04.md` (§ "P1 scope split"):
1. Migrate the remaining three halt literals (`connector-fatal`, `reconciliation-unresolved`,
   `durable-halt`) at their call sites to the enum members.
2. Change `halt(reason: str)` to accept/require `HaltReason`, update its docstring, and drop the
   free-string path.

That todo stays OPEN until the deferred half lands.

## Self-Check: PASSED

- `tests/unit/core/test_halt_reason.py` — FOUND.
- `itrader/core/enums/system.py` HaltReason — FOUND (grep line 86).
- Commit 64431026 — FOUND. Commit 7383b1fa — FOUND.
