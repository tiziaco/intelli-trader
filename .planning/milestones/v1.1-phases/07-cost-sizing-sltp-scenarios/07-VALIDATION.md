---
phase: 7
slug: cost-sizing-sltp-scenarios
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-10
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (Poetry) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error"]`, strict markers/config) |
| **Quick run command** | `poetry run pytest tests/e2e/<subsystem>/<leaf> -x` |
| **Full suite command** | `poetry run pytest tests/e2e -x` + `make test` |
| **Estimated runtime** | ~5–30 seconds per leaf; ~2 min full E2E |

---

## Sampling Rate

- **After every task commit:** Run the leaf's `poetry run pytest tests/e2e/<subsystem>/<leaf> -x`
- **After every plan wave:** Run `poetry run pytest tests/e2e -x`
- **Before `/gsd:verify-work`:** Full suite must be green AND `poetry run pytest tests/integration/test_backtest_oracle.py -x` byte-exact (oracle-dark gate)
- **Max feedback latency:** ~30 seconds (single leaf)

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| COST-01 | percent fee round-trip | e2e golden | `poetry run pytest tests/e2e/cost/percent_fee -x` | ❌ Wave (COST) |
| COST-02 | maker vs taker (limit/market) | e2e golden | `poetry run pytest tests/e2e/cost/maker_taker -x` | ❌ Wave (COST) |
| COST-03 | fixed slippage | e2e golden | `poetry run pytest tests/e2e/cost/fixed_slippage -x` | ❌ Wave (COST) |
| COST-04 | linear slippage | e2e golden | `poetry run pytest tests/e2e/cost/linear_slippage -x` | ❌ Wave (COST) |
| COST-05 | slippage not on limit | e2e golden | `poetry run pytest tests/e2e/cost/limit_no_slip -x` | ❌ Wave (COST) |
| COST-06 | combined fee+slippage to the cent | e2e golden | `poetry run pytest tests/e2e/cost/combined_roundtrip -x` | ❌ Wave (COST) |
| SIZE-01 | FixedQuantity | e2e golden | `poetry run pytest tests/e2e/sizing/fixed_quantity -x` | ❌ Wave (SIZE) |
| SIZE-02 | RiskPercent off stop distance | e2e golden | `poetry run pytest tests/e2e/sizing/risk_percent -x` | ❌ Wave (SIZE) |
| SIZE-03 | over-cash REJECTED (orders snapshot) | e2e golden | `poetry run pytest tests/e2e/sizing/over_cash_reject -x` | ❌ Wave (SIZE) |
| SLTP-01 | PercentFromDecision × {SL,TP,held} | e2e golden | `poetry run pytest tests/e2e/sltp/from_decision_* -x` | ❌ Wave (SLTP) |
| SLTP-02 | PercentFromFill × {SL,TP,held} | e2e golden | `poetry run pytest tests/e2e/sltp/from_fill_* -x` | ❌ Wave (SLTP) |
| SLTP-03 | SL-hit / TP-hit / held-to-end | e2e golden | covered by the 6 SLTP leaves above | ❌ Wave (SLTP) |
| (gate) | BTCUSD oracle stays byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| (gate) | 15 existing E2E goldens re-frozen (commission col) | e2e | `poetry run pytest tests/e2e/matching tests/e2e/smoke -x` | ✅ exists |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Foundational Plan 1 installs the shared scaffolding before any scenario leaf can be verified:

- [ ] `commission` golden column wired in the E2E serialization path (D-07/D-08) — proven on the canary
- [ ] `ScriptedEmitter.sltp_policy` constructor kwarg (D-12) — flows to `SignalEvent.sltp_policy`
- [ ] Exchange-config seam fix in `tests/e2e/conftest.py` (D-14) — `simulated.config = spec.exchange` + `_init_*` re-init
- [ ] ONE canary leaf proving the wiring end-to-end
- [ ] Phase 6 zero-fee trade goldens re-frozen with `commission=0.00` (15 single-test `--freeze` re-freezes)
- [ ] BTCUSD oracle re-run byte-exact

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Per-cent cash-math derivation | COST-06 | Hand-derivation is the audit; the test asserts the frozen golden | Each leaf's VERIFY note hand-derives fee+slippage to the cent, cross-checked against the frozen `commission` column + `summary.json` `final_cash` |

*All scenario behaviors otherwise have automated golden-diff verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 (Plan 1) dependencies
- [ ] Sampling continuity: every leaf has an automated `pytest -x` command
- [ ] Wave 0 (Plan 1) covers all shared-scaffolding MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s per leaf
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
