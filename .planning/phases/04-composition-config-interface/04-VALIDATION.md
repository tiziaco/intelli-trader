---
phase: 4
slug: composition-config-interface
status: approved
nyquist_compliant: true
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
| **Estimated runtime** | unit ~10–20s · full `make test` ~60–120s (confirm at Wave 0) |

---

## Sampling Rate

- **After every task commit:** Run the domain-scoped `poetry run pytest tests/unit/<domain>/ -q`
- **After every plan wave:** Run `make test` (full suite green required)
- **Before `/gsd:verify-work`:** Full suite + e2e (58/58) + BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) + `mypy --strict` all green
- **Max feedback latency:** ~20s (domain-scoped unit run); wave-boundary full suite ~120s

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

Each `update_config` method, the error contract, the SystemSpec/factory collapse, the CommissionEstimator seam (incl. late-binding), and the symbol-seeding trap (PATTERNS-A2) map to an automated test.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | COMP-01 | — | N/A | unit | `pytest tests/unit/core/test_commission_estimator.py -q && mypy itrader/core/commission_estimator.py` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | COMP-01 | T-04-cfg | unknown/malformed keys raise `ConfigurationError` (`extra="forbid"`) | unit | `pytest tests/unit/config/test_order_config.py -q && mypy itrader/config/order.py` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | COMP-01 | — | N/A | unit | `python -c "from itrader.trading_system.system_spec import SystemSpec" && mypy itrader/trading_system/system_spec.py` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 2 | COMP-01 | — | N/A | unit+integration | `pytest tests/unit/execution -q && pytest tests/integration/test_backtest_oracle.py -q && mypy itrader/execution_handler/execution_handler.py` | ✅ | ⬜ pending |
| 04-02-02 | 02 | 2 | COMP-01 | — | N/A (D-15 late-binding) | unit | `pytest tests/unit/order tests/unit/execution tests/unit/core/test_commission_estimator.py -q && mypy itrader` | ✅/❌ W0 | ⬜ pending |
| 04-02-03 | 02 | 2 | COMP-01 | — | N/A | integration | `pytest tests/integration/test_symbol_seeding.py -q && pytest tests/integration/test_backtest_oracle.py -q && mypy itrader && make test-e2e` | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 3 | COMP-02 | T-04-cfg | malformed config raises `ConfigurationError`, no partial apply | unit | `pytest tests/unit/portfolio -q && mypy itrader/portfolio_handler` | ✅ | ⬜ pending |
| 04-03-02 | 03 | 3 | COMP-02 | T-04-cfg | symbol-set replacement seeds complete set; malformed raises | unit | `pytest tests/unit/execution -q && mypy itrader/execution_handler/exchanges/simulated.py` | ✅/❌ W0 | ⬜ pending |
| 04-03-03 | 03 | 3 | COMP-02 | T-04-cfg | malformed config raises `ConfigurationError` | unit | `pytest tests/unit/order -q && mypy itrader/order_handler` | ✅ | ⬜ pending |
| 04-04-01 | 04 | 3 | COMP-02 | T-04-cfg | re-validate→init()→re-derive warmup; malformed raises | unit | `pytest tests/unit/strategy/test_strategies_handler_update_config.py -q && mypy itrader/strategy_handler` | ❌ W0 | ⬜ pending |
| 04-04-02 | 04 | 3 | COMP-02 | T-04-cfg | unsafe hot-swap (`base_timeframe`) raises `ConfigurationError` | unit | `pytest tests/unit/price_handler/test_bar_feed_update_config.py -q && mypy itrader/price_handler/feed/bar_feed.py` | ❌ W0 | ⬜ pending |
| 04-05-01 | 05 | 4 | COMP-01 | — | N/A | integration | `pytest tests/integration -q && mypy itrader` | ✅ | ⬜ pending |
| 04-05-02 | 05 | 4 | COMP-01, COMP-02 | — | N/A | e2e | `make test-e2e && mypy itrader` | ✅ | ⬜ pending |
| 04-05-03 | 05 | 4 | COMP-01, COMP-02 | — | byte-exact PHASE GATE | e2e+full | `pytest tests/integration/test_backtest_oracle.py -q && make test-e2e && mypy itrader && make test` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · File Exists: ✅ existing test dir · ❌ W0 new file created in Wave 0/Wave 1*

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

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (checker Dimension 8 Check 8a: PASS — all 14 tasks)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (checker Check 8c: PASS)
- [x] Wave 0 covers all MISSING references (4 new unit-test files: commission_estimator, order_config, strategies_handler_update_config, bar_feed_update_config + symbol-seeding integration test)
- [x] No watch-mode flags (checker Check 8b: PASS)
- [x] Feedback latency target set (~20s domain unit / ~120s full)
- [x] `nyquist_compliant: true` set in frontmatter

> `wave_0_complete` remains `false` until Wave 1 execution creates the new test files; the per-task map's `❌ W0` rows flip to `✅` as those files land.

**Approval:** approved 2026-06-12 (planning-time; nyquist sampling contract satisfied)
