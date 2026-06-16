---
phase: 04
slug: liquidation-cross-validation-re-baseline
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-16
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (run via Poetry; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/portfolio/test_liquidation.py -x` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~90 seconds (full suite); <5s for the targeted liquidation unit file |

---

## Sampling Rate

- **After every task commit:** Run the specific new unit test file (`poetry run pytest tests/unit/portfolio/test_liquidation.py -x`)
- **After every plan wave:** Run `make test-portfolio && make test-orders` + the new e2e leaves
- **Before `/gsd:verify-work`:** `make test` green AND `tests/integration/test_backtest_oracle.py` byte-exact (134 / `46189.87730727451`, D-11); cross-validation evidence doc + owner sign-off before the freeze (D-12)
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| LIQ-01 (formula/breach/floor) | TBD | 1 | LIQ-01 | — | Loss can never drive equity impossibly negative (capped at WB) | unit + e2e | `poetry run pytest tests/unit/portfolio/test_liquidation.py -x` | ❌ W0 | ⬜ pending |
| LIQ-01 (multi-breach order) | TBD | 1 | LIQ-01 | — | Deterministic liquidation order → byte-identical double-run | unit | `poetry run pytest -k "multi_breach_deterministic" -x` | ❌ W0 | ⬜ pending |
| LIQ-02 (penalty + cap) | TBD | 1 | LIQ-02 | — | Penalty = rate×\|size\|×liq, total loss capped at WB | unit | `poetry run pytest -k "liquidation_penalty" -x` | ❌ W0 | ⬜ pending |
| LIQ-03 (mirror reconcile) | TBD | 2 | LIQ-03 | — | EXECUTED→FILLED, `OrderTriggerSource.LIQUIDATION`, no new `FillStatus` | unit | `poetry run pytest tests/unit/order -k "liquidation" -x` | ❌ W0 | ⬜ pending |
| LIQ-01/02/03 (run path) | TBD | 2 | LIQ-01, LIQ-02, LIQ-03 | — | Forced-liq long / short / leveraged-long-into-liquidation full run path | e2e (white-box, mirror `levered_long`) | `poetry run pytest tests/e2e/forced_liq_long -x` | ❌ W0 | ⬜ pending |
| WR-04 (call-order fix) | 04-02 | 1 | LIQ-01 (carry) | — | `assert_lock_fits_buying_power` credits the prior lock add-back | unit (regression, TDD RED→GREEN inline) | `poetry run pytest tests/unit/portfolio -k "lock_fits_buying_power" -x` | created by 04-02 (TDD) — no W0 stub | ⬜ pending |
| D-11 (oracle-dark hold) | TBD | 3 | XVAL-01 | — | SMA_MACD byte-exact (134 / `46189.87730727451`) | integration (existing) | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| D-10 (freeze parked scenarios) | TBD | 3 | XVAL-01 | — | Parked P2/P3 scenarios frozen alongside P4 | e2e | `poetry run pytest tests/e2e/levered_long tests/e2e/short_roundtrip tests/e2e/short_carry tests/e2e/partial_cover -x` | ✅ (assert inline; no `golden/` yet) | ⬜ pending |
| XVAL-01 (cross-validate) | TBD | 3 | XVAL-01 | — | Short/leveraged/liquidation cross-validated vs backtesting.py + backtrader | script (not in suite) | `poetry run python scripts/cross_validate.py` (extend) | ✅ driver exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are TBD until the planner assigns plan/wave numbers; rows are keyed by requirement + behavior so the planner can map them onto concrete `{NN}-{PP}-{TT}` IDs.*

---

## Wave 0 Requirements

- [ ] `tests/unit/portfolio/test_liquidation.py` — stubs for LIQ-01/LIQ-02 (formula, breach, penalty, cap, determinism)
- [ ] `tests/unit/order/test_liquidation_reconcile.py` — stubs for LIQ-03 (EXECUTED→FILLED, `LIQUIDATION` trigger, no new status, registered order)
- [ ] `tests/e2e/forced_liq_long/`, `tests/e2e/forced_liq_short/`, `tests/e2e/levered_long_into_liquidation/` — new white-box e2e leaves (mirror `tests/e2e/levered_long/test_levered_long_scenario.py`)
- [ ] Framework: pytest already installed — no install needed

*Existing infrastructure (pytest + Poetry + golden harness) covers the framework; the gaps above are new test files only.*

**Note (WR-04 ownership):** `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` is NOT a Wave 0 stub — it is created and made green inline by plan **04-02** as a TDD RED→GREEN task. The `-k "lock_fits_buying_power"` selector therefore resolves within 04-02's own task (no separate Wave 0 collectible needed); this is why `nyquist_compliant: true` holds despite the test not existing before 04-02 runs.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Accounting-core golden freeze | XVAL-01 | Owner-gated, result-changing re-baseline (D-12) — requires explicit human sign-off with attribution | After cross-validation evidence doc (`tests/golden/CROSS-VALIDATION-ACCOUNTING.md`) is complete: blocking human-verify checkpoint; owner reviews the per-scenario reconciliation table + Owner Sign-Off block; freeze happens ONLY after sign-off |
| Cross-validation reconciliation | XVAL-01 | backtesting.py/backtrader give directional corroboration on liquidation, not byte-match; divergences need human root-cause + disposition | Run `scripts/cross_validate.py` (extended); review per-divergence root-cause in the evidence doc against the apples-to-apples boundary |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
