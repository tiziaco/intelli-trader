---
phase: 04
slug: retention-live-write-through-2-live-path
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-30
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `poetry run pytest tests` (integration needs Docker for testcontainers Postgres) |
| **Estimated runtime** | ~unit fast; integration gated on testcontainers Postgres (skips without Docker) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit -q`
- **After every plan wave:** Run `poetry run pytest tests` (with Docker up for the testcontainers Postgres integration tests)
- **Before `/gsd:verify-work`:** Full suite green + `mypy --strict` clean (GATE-02) + SMA_MACD oracle byte-exact (GATE-01)
- **Max feedback latency:** unit < ~30s; integration bounded by container spin-up

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _to be populated by planner from PLAN.md tasks_ | | | | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Reuse the existing session-scoped testcontainers Postgres fixture (Phase 1 D-10) — no new framework install
- [ ] Per-concern integration test files under `tests/integration/` for the wrappers (evict-then-read-through, flat-RSS long-run, bracket-parent-resident, open-only rehydration, crash-after-emit/restart)

*Existing infrastructure (pytest + testcontainers Postgres harness) covers all phase requirements — Wave 0 adds test stubs only, no framework install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| _none anticipated_ | RETAIN-01/02/03, GATE-01 | — | All phase behaviors verifiable via pytest + testcontainers Postgres |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (unit)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
