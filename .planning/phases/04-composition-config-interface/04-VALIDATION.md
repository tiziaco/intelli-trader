---
phase: 4
slug: composition-config-interface
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-12
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (Poetry) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Quick run command** | `poetry run pytest tests/unit/<domain>/ -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~TBD seconds (set after Wave 0) |

---

## Sampling Rate

- **After every task commit:** Run the domain-scoped `poetry run pytest tests/unit/<domain>/ -q`
- **After every plan wave:** Run `make test` (full suite green required)
- **Before `/gsd:verify-work`:** Full suite + e2e (58/58) + BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) + `mypy --strict` all green
- **Max feedback latency:** TBD seconds

---

## Byte-Exact Gate (phase-level, non-negotiable)

| Gate | Expected | Command |
|------|----------|---------|
| BTCUSD oracle | 134 trades / `final_equity 46189.87730727451` | oracle / integration run-path test |
| E2E golden suite | 58/58 | `poetry run pytest tests/e2e/ -q` |
| Full suite | green | `make test` |
| Type check | clean | `mypy --strict` |

> COMP-02 (`update_config`) is oracle-dark by construction — the golden run never fires `update_config`, so config-method correctness is validated by **direct unit tests only**. All byte-exact risk lives in COMP-01's structural moves.

---

## Per-Task Verification Map

*Populated by the planner. Each `update_config` method, the error contract, the SystemSpec/factory collapse, the CommissionEstimator seam, and the symbol-seeding trap (PATTERNS-A2) must map to an automated test.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | COMP-01 / COMP-02 | — | N/A | unit/e2e | TBD | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Per RESEARCH.md Wave 0 test gaps — confirmed against real test files during planning.*

- [ ] Unit tests for the uniform `update_config` contract on each handler (deep-merge → model_validate → atomic-swap → `ConfigurationError`)
- [ ] Unit test for the symbol-seeding replacement trap (construction seeds complete set; later `update_config(limits=...)` does not silently REFUSE orders)
- [ ] Unit test for `OrderConfig` Pydantic model (`extra="forbid"`)
- [ ] Unit/type test for the `CommissionEstimator` Protocol + `FeeModelCommissionEstimator` late-binding adapter
- [ ] `tests/e2e/conftest.py` `_build_and_run` collapse onto `build_backtest_system(spec)` keeps e2e 58/58

*If existing infrastructure covers a row, mark it so during planning.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none expected) | — | — | — |

*All phase behaviors should have automated verification — this is a byte-exact refactor.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency target set
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
