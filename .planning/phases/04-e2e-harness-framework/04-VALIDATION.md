---
phase: 04
slug: e2e-harness-framework
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (pinned) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `make test-e2e` (`-m e2e`) |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~{N} seconds (e2e scenarios are ~10 bars; fast) |

---

## Sampling Rate

- **After every task commit:** Run `make test-e2e` (and `poetry run pytest tests/integration/test_backtest_oracle.py` for any task touching the D-16 reporting extraction — oracle-dark guard)
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green under `filterwarnings=["error"]`
- **Max feedback latency:** {N} seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | E2E-{XX} | — | N/A | integration | `{command}` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> Planner: populate one row per task. The defining oracle-dark assertion for any
> D-16 reporting-extraction task is `tests/integration/test_backtest_oracle.py`
> passing byte-identical (the meta-validation that the harness/extraction does
> not perturb the frozen BTCUSD oracle).

---

## Wave 0 Requirements

- [ ] `tests/e2e/conftest.py` — shared `run_scenario` fixture (E2E-02)
- [ ] `tests/e2e/<subsystem>/<canary>/test_*.py` — canary leaf test (E2E-03)
- [ ] `pyproject.toml` + `tests/conftest.py` — `e2e` marker registration + folder-derived auto-marking (E2E-01)

*Existing pytest infrastructure covers the framework; new e2e fixtures install in Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Canary golden fixtures are correct before freeze | E2E-04 | Hand-verify-once discipline — a human derives expected fills/PnL and signs off in the VERIFY note before the golden is committed | Read the scenario's VERIFY note / `scenario.py` docstring; confirm expected MARKET trade + PnL matches the committed `golden/` files |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < {N}s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
