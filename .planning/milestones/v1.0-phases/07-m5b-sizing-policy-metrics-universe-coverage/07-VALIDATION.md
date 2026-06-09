---
phase: 7
slug: m5b-sizing-policy-metrics-universe-coverage
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-07
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (via Poetry, strict markers/config, filterwarnings=error) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `poetry run pytest <affected test dir> -x -q` |
| **Full suite command** | `make test` |
| **Oracle gate** | `poetry run pytest tests/integration/test_backtest_oracle.py -q` (slow — full 2018→2026 run) |
| **Type gate** | `make typecheck` |
| **Estimated runtime** | ~60 seconds (unit), minutes (oracle) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest <affected test dir> -x -q` + `make typecheck`
- **After every plan wave:** Run `make test` (full suite incl. oracle)
- **Inert-workstream gate:** Oracle byte-exact at the end of every inert plan (07-02..07-06) BEFORE the result-changing plans start (structural-first, Phase 6 D-22 discipline)
- **Before `/gsd:verify-work`:** Full suite green + both D-11 re-freezes owner-signed
- **Max feedback latency:** 90 seconds (unit layer); oracle reserved for plan-end gates

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01 T1 | 07-01 | 1 | M5-06 | T-07-01 | Policy params validated at construction (V5 fail-loud) | unit | `poetry run pytest tests/unit/core/test_sizing.py -x -q` | ❌ test-with-code | ⬜ pending |
| 07-01 T2 | 07-01 | 1 | M5-06 | — | total_equity through the narrow Protocol | unit | `poetry run pytest tests/unit/core/test_portfolio_read_model.py -x -q` | ✅ extend | ⬜ pending |
| 07-01 T3 | 07-01 | 1 | M5-06 | T-07-02 | Resolver byte-exact FractionOfCash arm; typed RiskPercent failure | unit | `poetry run pytest tests/unit/order/test_sizing_resolver.py -x -q` | ❌ test-with-code | ⬜ pending |
| 07-02 T1 | 07-02 | 1 | M5-08, M5-09 | T-07-04 | Membership union pure; missing-ticker warning kept | unit | `poetry run pytest tests/unit/universe tests/unit/price -x -q` | ❌ test-with-code | ⬜ pending |
| 07-02 T2 | 07-02 | 1 | M5-08 | T-07-03 | TIME route rewired; collapse inert | unit+oracle | `poetry run pytest tests/unit/events -x -q && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ⚠️ update existing | ⬜ pending |
| 07-03 T1 | 07-03 | 2 | M5-07, M5-09 | T-07-07 | Guarded denominators; pandas-2 idioms under filterwarnings=error | unit | `poetry run pytest tests/unit/reporting/test_metrics.py -x -q` | ❌ test-with-code | ⬜ pending |
| 07-03 T2 | 07-03 | 2 | M5-07 | T-07-05 | SQL injection-bearing dead path deleted; plotly-6 clean | unit+type | `poetry run pytest tests/unit/reporting -x -q && make typecheck` | ❌ test-with-code | ⬜ pending |
| 07-03 T3 | 07-03 | 2 | M5-07 | T-07-06 | New artifacts produced WITHOUT touching goldens (Pitfall 6) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists | ⬜ pending |
| 07-04 T1 | 07-04 | 2 | M5-06 | — | Typed signal fields; dict deleted | unit+type | `poetry run pytest tests/unit/order tests/unit/events -x -q && make typecheck` | ⚠️ update existing | ⬜ pending |
| 07-04 T2 | 07-04 | 2 | M5-06 | T-07-09, T-07-10 | Pure strategy ABC; LONG_SHORT registration rejection | import+unit | `poetry run pytest tests/unit -x -q` | ⚠️ converted in T3 | ⬜ pending |
| 07-04 T3 | 07-04 | 2 | M5-06, M5-09 | T-07-08 | Intent contract pure-function tests; rewrite proven inert | unit+oracle | `poetry run pytest tests/unit/strategy -x -q && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ⚠️ CONVERT test_strategy.py | ⬜ pending |
| 07-05 T1 | 07-05 | 3 | M5-06 | T-07-11 | Audited sizing rejections; shorts fall-through preserved | unit | `poetry run pytest tests/unit/order -x -q` | ✅ extend | ⬜ pending |
| 07-05 T2 | 07-05 | 3 | M5-06 | T-07-12 | Zero-quantity bypass dead; orphan packages deleted | unit+type | `poetry run pytest tests/unit/order -x -q && make typecheck` | ⚠️ update existing | ⬜ pending |
| 07-05 T3 | 07-05 | 3 | M5-06 | T-07-13 | Resolver swap byte-exact end-to-end | unit+oracle+suite | `poetry run pytest tests/integration/test_backtest_oracle.py -q && make test` | ✅ extend | ⬜ pending |
| 07-06 T1 | 07-06 | 4 | M5-06 | T-07-14 | Fill-anchored children unreachable pre-fill | unit | `poetry run pytest tests/unit/order -x -q && make typecheck` | — | ⬜ pending |
| 07-06 T2 | 07-06 | 4 | M5-06 | T-07-15, T-07-16 | SLTP mechanics oracle-dark | unit+oracle | `poetry run pytest tests/unit/order/test_sltp_policy.py -x -q && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ❌ test-with-code | ⬜ pending |
| 07-07 T1 | 07-07 | 5 | M5-06 | T-07-18, T-07-19 | Direction guard audited; exits/explicit-qty pass | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -x -q` | ❌ test-with-code | ⬜ pending |
| 07-07 T2 | 07-07 | 5 | M5-06 | T-07-17 | BLOCKING owner sign-off on diff note (D-23) | human checkpoint | `test -s tests/golden/REFREEZE-M5B-DIRECTION.md` | — | ⬜ pending |
| 07-07 T3 | 07-07 | 5 | M5-06, M5-07 | T-07-17 | ONE-commit re-freeze 1 + metrics/slippage frozen | suite+oracle | `make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ extend oracle | ⬜ pending |
| 07-08 T1 | 07-08 | 6 | M5-06 | T-07-21, T-07-22 | Increase/max_positions guards; reserve coverage | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -x -q` | ✅ extend | ⬜ pending |
| 07-08 T2 | 07-08 | 6 | M5-06 | T-07-20 | BLOCKING owner sign-off on diff note (D-23) | human checkpoint | `test -s tests/golden/REFREEZE-M5B-INCREASE.md` | — | ⬜ pending |
| 07-08 T3 | 07-08 | 6 | M5-06 | T-07-20 | ONE-commit re-freeze 2 + phase gate | suite+oracle+backtest | `make test && make typecheck && make backtest` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Tests ship **test-with-code** in the same plan as the code they lock (Phase 6 D-24 discipline) —
no standalone Wave 0 scaffold plan is needed. New/converted test files by plan:

- [ ] `tests/unit/core/test_sizing.py` — NEW (07-01 T1)
- [ ] `tests/unit/order/test_sizing_resolver.py` — NEW (07-01 T3)
- [ ] `tests/unit/universe/test_membership.py` — NEW (07-02 T1)
- [ ] `tests/unit/reporting/test_metrics.py` — NEW (07-03 T1)
- [ ] `tests/unit/reporting/test_plots_smoke.py` — NEW (07-03 T2)
- [ ] `tests/unit/strategy/test_strategy.py` — CONVERT to intent contract (07-04 T3)
- [ ] `tests/unit/events/test_dispatch_registry.py`, `test_error_flow.py`, `tests/integration/test_event_wiring.py` — UPDATE for the new bar-event source (07-02 T2)
- [ ] `tests/unit/order/test_sltp_policy.py` — NEW (07-06 T2)
- [ ] `tests/unit/order/test_admission_rules.py` — NEW (07-07 T1, extended 07-08 T1)
- TC2 CSV part: `tests/unit/price/test_csv_store.py` (6) + `test_bar_feed.py` (13) already exist — gap-audit only (07-02)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Re-freeze 1 expected-diff approval | M5-06 (D-08/D-11/D-23) | Result-changing oracle re-baseline requires owner judgment on diff attribution | Read tests/golden/REFREEZE-M5B-DIRECTION.md; verify removed trades are exactly the 2 golden SHORTs; confirm compounding knock-on explanation; sanity-check frozen metrics block |
| Re-freeze 2 expected-diff approval | M5-06 (D-10/D-11/D-23) | Same — second named numeric change | Read tests/golden/REFREEZE-M5B-INCREASE.md; verify N rejected increases (N=0 valid and recorded); confirm max_positions tripped zero times |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test-with-code per D-24)
- [x] No watch-mode flags
- [x] Feedback latency < 90s (unit layer; oracle at plan-end gates only)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-06-07
