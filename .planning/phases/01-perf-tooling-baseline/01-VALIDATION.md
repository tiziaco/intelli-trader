---
phase: 1
slug: perf-tooling-baseline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-23
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/integration/test_backtest_oracle.py -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | oracle ~tens of seconds; full suite longer |

---

## Sampling Rate

- **After every task commit:** Run the byte-exact oracle (`poetry run pytest tests/integration/test_backtest_oracle.py -q`) — gate (a) must stay green (134 trades / final_equity 46189.87730727451).
- **After every plan wave:** Run `make test`.
- **Before `/gsd:verify-work`:** Full suite + oracle must be green; `make perf-baseline` then `make perf-w1` must run clean and print a delta.
- **Max feedback latency:** oracle run (~tens of seconds).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (planner to populate from RESEARCH.md ## Validation Architecture) | — | — | TOOL-01/02/04 | — | N/A (tooling-only, no engine change) | cli/integration | (per task) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing infrastructure covers all phase requirements (pytest + the byte-exact oracle already exist). No new framework install.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Scalene `perf-profile` writes a gitignored HTML and never wraps the timed run | TOOL-02 | Profiling artifact is human-inspected; profiler-free benchmark is the gated path | Run `make perf-profile`; confirm HTML artifact written under the gitignored path and that `make perf-w1` (timed) runs without any profiler attached |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency acceptable (oracle ~tens of seconds)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
