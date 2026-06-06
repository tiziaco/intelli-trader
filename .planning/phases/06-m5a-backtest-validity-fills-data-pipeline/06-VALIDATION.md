---
phase: 6
slug: m5a-backtest-validity-fills-data-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-06
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (strict markers, strict config, filterwarnings=error) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `poetry run pytest -m unit -x -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest -m unit -x -q`
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (filled by planner) | | | M5-01..M5-05 | — | N/A | unit/integration | `poetry run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Test stubs for resampling look-ahead / completed-bars rule (M5-01)
- [ ] Test stubs for fill semantics (limit fills, next-bar-open market fills) (M5-02)
- [ ] Test stubs for Bar struct construction and immutability (M5-03)
- [ ] Test stubs for fee/slippage model corrections (M5-04)
- [ ] Test stubs for Provider/Store/Feed read-only run path (M5-05)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Oracle re-freeze review | M5-02 | Result-changing fills require human sign-off on new golden numbers | Run golden backtest, diff trade log vs M1 oracle, approve re-baseline |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
