---
phase: 1
slug: instrument-value-object
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-15
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (+ pytest-cov, pandas.testing) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/core/test_money.py tests/unit/core/test_instrument.py -v` |
| **Full suite command** | `make test` |
| **Byte-exact gate** | `poetry run pytest tests/integration/test_backtest_oracle.py -v` |
| **Estimated runtime** | ~5s unit / ~30–60s oracle |

---

## Sampling Rate

- **After every task commit:** Run the relevant unit file (e.g. `test_money.py` / `test_instrument.py` / `test_derive_instruments.py`) + `poetry run mypy itrader`
- **After every plan wave:** Run `make test-unit` + `poetry run pytest tests/integration/test_backtest_oracle.py`
- **Before `/gsd:verify-work`:** `make test` green AND `test_backtest_oracle.py` byte-exact AND `mypy --strict` clean AND `test_determinism.py` green
- **Max feedback latency:** ~60 seconds (oracle is the slow gate)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| INST-01a | core | 1 | INST-01 | — | N/A | unit | `poetry run pytest tests/unit/core/test_instrument.py -v` | ❌ W0 | ⬜ pending |
| INST-01b | core | 1 | INST-01 | — | N/A | unit | `poetry run pytest tests/unit/core/test_money.py -v` | ✅ (update to pass `Instrument`) | ⬜ pending |
| INST-03a | core | 1 | INST-03 | — | N/A | unit | `poetry run pytest tests/unit/core/test_instrument.py -k margin` | ❌ W0 | ⬜ pending |
| INST-02a | universe | 2 | INST-02 | — | N/A | unit | `poetry run pytest tests/unit/universe/test_derive_instruments.py -k infer` | ❌ W0 | ⬜ pending |
| INST-02b | universe | 2 | INST-02 | — | N/A | unit | `poetry run pytest tests/unit/universe/test_derive_instruments.py -k declared` | ❌ W0 | ⬜ pending |
| INST-02c | universe | 2 | INST-02 | — | N/A | unit | `poetry run pytest tests/unit/universe/test_derive_instruments.py -k default` | ❌ W0 | ⬜ pending |
| INST-03b | execution | 2 | INST-03 | — | min_order_size: Instrument-first → ExchangeLimits(0.001) fallback | unit | `poetry run pytest tests/unit/execution/ -k min_order` | ❌ W0 | ⬜ pending |
| GATE-oracle | all | 3 | INST-01/02/03 | — | Byte-exact oracle holds (134 trades / 46189.87730727451) | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | ✅ | ⬜ pending |
| GATE-mypy | all | 3 | ALL | — | strict-clean on new core/universe modules | static | `poetry run mypy itrader` | ✅ | ⬜ pending |
| GATE-determinism | all | 3 | ALL | — | double-run byte-identical | e2e | `poetry run pytest tests/e2e/robust/test_determinism.py -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/core/test_instrument.py` — frozen-ness, field defaults, declared-vs-undeclared `min_order_size`, scale reproduces `Decimal("0.00000001")` (INST-01/03)
- [ ] `tests/unit/universe/test_derive_instruments.py` — declared / inferred (string-count, 8dp cap) / default ladder on a SYNTHETIC non-oracle symbol; BTCUSD-takes-declared assertion (INST-02)
- [ ] `tests/unit/execution/` min_order_size fallback test — `Instrument(None)` → `ExchangeLimits(0.001)` (INST-03)
- [ ] Update `tests/unit/core/test_money.py` (`:45, :50, :57`) to pass `Instrument` objects instead of `str` (INST-01)
- [ ] (Optional) `tests/unit/universe/test_universe.py` — `.members` equals `derive_membership(...)` exactly; `.instrument(sym)` round-trips

*No new framework install needed — pytest infrastructure covers all of this.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | — |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
