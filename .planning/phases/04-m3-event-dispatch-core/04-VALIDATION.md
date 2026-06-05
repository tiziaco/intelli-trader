---
phase: 4
slug: m3-event-dispatch-core
status: draft
nyquist_compliant: false
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

- **After every task commit:** Run `poetry run pytest tests/unit/events/ -q`
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (filled by planner) | | | M3-01..M3-04 | — | N/A | unit | (per plan) | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/events/test_event_immutability.py` — REWRITE: current file asserts mutability as the contract; must assert `FrozenInstanceError` instead
- [ ] `tests/unit/events/test_dispatch_registry.py` — stubs for M3-02 (race-free loop, registry routing, unknown-type `NotImplementedError`)
- [ ] `tests/unit/events/test_error_flow.py` — stubs for M3-03/D-17 (ErrorEvent hierarchy, ERROR dispatch route)
- [ ] Oracle gate: behavioral + post-M2 numerical oracle test runs per-commit (D-22)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
