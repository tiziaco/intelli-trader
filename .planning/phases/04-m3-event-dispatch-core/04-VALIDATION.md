---
phase: 4
slug: m3-event-dispatch-core
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-05
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 |
| **Config file** | `pyproject.toml` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/events/ -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` command (each includes targeted unit tests; run-path-touching tasks also run the oracle test)
- **After every plan wave:** Run `make test` + `make typecheck`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds
- **D-22 standing rule:** behavioral + numerical oracle assertions (`tests/integration/test_backtest_oracle.py`, UNMODIFIED) green at EVERY commit — any diff = STOP/investigate, never re-baseline

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01 T1 | 04-01 | 1 | M3-01 | T-04-01/02 | enum `_missing_` raises on unknown | unit+grep | `grep EventType.PING == 0` + `poetry run pytest tests/ -x -q` + `make typecheck` | ✅ existing suite | ⬜ pending |
| 04-01 T2 | 04-01 | 1 | M3-01, M3-04 | — | N/A | unit+integration | `poetry run pytest tests/ -x -q` + oracle test | ✅ existing suite | ⬜ pending |
| 04-02 T1 | 04-02 | 2 | M3-01, M3-04 | T-04-04 | no mutable verdict flag | unit+integration | `grep .verified == 0` + `pytest tests/unit/order tests/unit/events tests/unit/strategy` + oracle | ✅ existing suite | ⬜ pending |
| 04-02 T2 | 04-02 | 2 | M3-01, M3-04 | T-04-03 | audited REJECTED transitions | unit+integration | `pytest tests/unit/order tests/unit/events` + `pytest tests/integration/` | ✅ existing suite | ⬜ pending |
| 04-02 T3 | 04-02 | 2 | M3-01 | T-04-03 | rejection audit locked by test | unit | `pytest tests/unit/order` + `make test` | ✅ updated in-task | ⬜ pending |
| 04-03 T1 | 04-03 | 3 | M3-01, M3-04 | T-04-06/07 | construct-complete fills, fill_id linkage | unit+integration | grep no fill mutation + `pytest tests/unit/events tests/unit/execution` + oracle | ✅ test_fill_event_schema.py updated in-task | ⬜ pending |
| 04-03 T2 | 04-03 | 3 | M3-01, M3-04 | T-04-08 | replace-in-book, id preservation | unit | grep no order mutation + `pytest tests/unit/execution` + `make test` + typecheck | ✅ added in-task | ⬜ pending |
| 04-04 T1 | 04-04 | 4 | M3-01 | T-04-09/10/11 | frozen tree, required IDs, uuid7 | unit | inline python assert + `pytest tests/ -x -q` + typecheck | ✅ new package self-test | ⬜ pending |
| 04-04 T2 | 04-04 | 4 | M3-01 | T-04-09 | FrozenInstanceError contract | unit | `pytest tests/unit/events/test_event_immutability.py` + `make test` | ✅ REWRITTEN in-task (Wave 0 gap closed) | ⬜ pending |
| 04-05 T1 | 04-05 | 5 | M3-01, M3-04 | T-04-12/13/14 | enum boundary parse, single surface | grep+integration | grep zero old-path imports + oracle test | ✅ existing suite | ⬜ pending |
| 04-05 T2 | 04-05 | 5 | M3-01, M3-04 | — | N/A | full suite | grep + `make test` | ✅ existing suite | ⬜ pending |
| 04-05 T3 | 04-05 | 5 | M3-01, M3-04 | T-04-13 | event.py deleted, no stale defs | full gate | `test ! -f event.py` + `make test` + `make typecheck` | ✅ existing suite | ⬜ pending |
| 04-06 T1 | 04-06 | 6 | M3-02, M3-04 | T-04-15/16/18 | fail-fast seam, no TOCTOU, raise on unknown | integration | grep no empty() + `pytest tests/integration/test_event_wiring.py` + oracle | ✅ test_event_wiring.py exists | ⬜ pending |
| 04-06 T2 | 04-06 | 6 | M3-02, M3-03 | T-04-17 | ERROR routing + latent-UPDATE regression | unit | `pytest tests/unit/events/test_dispatch_registry.py test_error_flow.py` + `make test` | ✅ CREATED in-task (Wave 0 gaps closed) | ⬜ pending |
| 04-07 T1 | 04-07 | 6 | M3-03, M3-04 | T-04-19 | correct-typed exception args | unit+grep | grep zero ITradingSystemError/ConcurrencyError + `pytest tests/unit/portfolio tests/unit/core` + `make test` | ✅ existing suite | ⬜ pending |
| 04-07 T2 | 04-07 | 6 | M3-03, M3-04 | T-04-20/21 | domain exceptions, no swallowed bugs | unit | `pytest tests/unit/core/test_exceptions.py` + grep + `make test` + typecheck | ✅ CREATED in-task (Wave 0 gap closed) | ⬜ pending |
| 04-08 T1 | 04-08 | 7 | M3-03 | T-04-22/23/24 | no Settings() at import, no secret logging | unit | `pytest tests/unit/core/test_logger_config.py` + grep + `make test` | ✅ CREATED in-task | ⬜ pending |
| 04-08 T2 | 04-08 | 7 | M3-03, M3-04 | — | N/A | unit+full gate | grep zero stdlib TradingSystem loggers + `pytest` + `make test` + typecheck | ✅ existing suite | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Test scaffolds are created/rewritten INSIDE the plan that lands the behavior (same commit train —
required because the byte-exact oracle gate means pre-landing red tests cannot coexist with
"suite green at every commit"):

- [x] `tests/unit/events/test_event_immutability.py` REWRITE → Plan 04-04 Task 2 (D-23 group 2; current file asserts mutability as contract and must stay green until the freeze)
- [x] `tests/unit/events/test_dispatch_registry.py` → Plan 04-06 Task 2 (D-23 group 1)
- [x] `tests/unit/events/test_error_flow.py` → Plan 04-06 Task 2 (D-23 group 3, incl. latent-UPDATE-crash regression)
- [x] exception-hierarchy test (`tests/unit/core/test_exceptions.py`) → Plan 04-07 Task 2 (KB24, ITraderError)
- [x] Oracle gate: `tests/integration/test_backtest_oracle.py` exists, assertions UNMODIFIED, runs per commit (D-22)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (in-plan creation, same commit train)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner sign-off 2026-06-05
