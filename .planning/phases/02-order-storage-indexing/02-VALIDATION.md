---
phase: 2
slug: order-storage-indexing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-23
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, strict markers) |
| **Quick run command** | `poetry run pytest tests/unit/order/test_order_storage.py -q` |
| **Full suite command** | `make test` (full suite) |
| **Gate (a) oracle** | `poetry run pytest tests/integration/test_backtest_oracle.py -q` (134 trades / `final_equity 46189.87730727451`) |
| **Static gate** | `poetry run mypy --strict itrader` (in-scope: `in_memory_storage.py` is strict) |
| **Gate (b) benchmark** | `make perf-w1` (Δ vs locked W1-BASELINE.json ≈ 247.5 s) + re-freeze with `make perf-baseline` |
| **Estimated runtime** | unit ~seconds; oracle ~minutes; perf-w1 ~4 min |

---

## Sampling Rate

- **After every task commit:** Run the quick command (`pytest tests/unit/order/test_order_storage.py -q`)
- **After every plan wave:** Run the full suite (`make test`)
- **Before gate sign-off:** oracle green + `mypy --strict` clean + determinism double-run byte-identical + `make perf-w1` shows ≥5% improvement (human-read the printed Δ — the soft guard only fails on regressions)
- **Max feedback latency:** ~30 seconds for the quick unit loop

---

## Per-Task Verification Map

> Populated by the planner from PLAN.md tasks. Every index-maintenance task maps to a
> `tests/unit/order/test_order_storage.py` assertion; the gate tasks map to the oracle / mypy /
> perf-w1 commands above.

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| TBD | TBD | TBD | PERF-01 | unit | `poetry run pytest tests/unit/order/test_order_storage.py -q` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing infrastructure covers all phase requirements (pytest + the order-storage suite + the
  byte-exact oracle already exist). The D-09 order-equivalence regression test is **added** in this
  phase, not a Wave-0 framework install.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gate (b) ≥5% wall-clock improvement | PERF-01 | `make perf-w1` soft guard only fails on regressions, not on confirming the improvement | Run `make perf-w1`, read the printed Δ vs W1-BASELINE.json; confirm ≥5% faster, then `make perf-baseline` to re-freeze |
| Determinism double-run byte-identical | PERF-01 (gate a) | Two full runs compared for byte-identical output | Run the backtest twice with the fixed seed; diff the trade log / equity output |

*All correctness behaviors (index consistency, ordering equivalence) have automated unit + oracle verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
