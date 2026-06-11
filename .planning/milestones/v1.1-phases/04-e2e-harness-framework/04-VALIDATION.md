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
| **Estimated runtime** | ~5–20 seconds (e2e scenarios are ~10 bars; the oracle-dark gate runs the full BTCUSD backtest, ~1–2 min) |

---

## Sampling Rate

- **After every task commit:** Run `make test-e2e` (and `poetry run pytest tests/integration/test_backtest_oracle.py` for any task touching the D-16 reporting extraction — oracle-dark guard)
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green under `filterwarnings=["error"]`
- **Max feedback latency:** ~120 seconds (bounded by the oracle-dark full-backtest gate on Plan 01 Task 2)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | E2E-02 | — | N/A | integration | `poetry run python -c "from itrader.reporting.summary import attach_slippage, build_metrics_block, build_summary, FLOAT_FORMAT, SLIPPAGE_COLUMNS"` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | E2E-02 | T-04 | Oracle-dark: BTCUSD golden byte-identical | integration | `make backtest && poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| 04-01-03 | 01 | 1 | — | — | FL-03 dead-skip removed | unit | `poetry run pytest tests/unit/core/test_enums.py -x` | ✅ | ⬜ pending |
| 04-02-01 | 02 | 2 | E2E-01 | — | e2e marker registered; in default `make test` | integration | `grep -q 'e2e:' pyproject.toml && grep -q '"e2e" in parts' tests/conftest.py && grep -q 'test-e2e' Makefile && poetry run pytest tests/ -m e2e --collect-only -q` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 2 | E2E-02, E2E-04 | T-04 | Goldens never auto-heal; `--freeze` deliberate | integration | `poetry run pytest tests/e2e --collect-only -q` + run_scenario/pytest_addoption presence check | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 3 | E2E-02, E2E-03 | — | Canary warning-clean; deterministic | e2e | `poetry run pytest tests/e2e/smoke/single_market_buy -x -q` (run twice — idempotent) | ❌ W0 | ⬜ pending |
| 04-03-02 | 03 | 3 | E2E-04 | T-04-06, T-04-07 | Hand-verify-once before freeze; diff catches drift | manual (checkpoint) | BLOCKING human-verify: VERIFY note matches frozen goldens; mutated golden makes test FAIL then reverts clean | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> The defining oracle-dark assertion is `tests/integration/test_backtest_oracle.py`
> passing byte-identical (04-01-02) — the meta-validation that the D-16 extraction
> and the new harness do not perturb the frozen BTCUSD oracle. `❌ W0` rows are
> created during their wave (the e2e tree does not exist yet).

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
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
