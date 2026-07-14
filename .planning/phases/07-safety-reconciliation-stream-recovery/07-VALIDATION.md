---
phase: 7
slug: safety-reconciliation-stream-recovery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `07-RESEARCH.md` § Validation Architecture. Task-level rows are
> completed by the planner/executor once PLAN.md task IDs exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (Poetry-managed) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `poetry run pytest tests` |
| **Gate (do NOT use `make test`)** | `make test` exports `ITRADER_DISABLE_LOGS=true`, which fails `caplog` warn-assertion tests — use `poetry run pytest` as the gate |
| **Estimated runtime** | ~10s (unit) · full suite longer (integration + oracle) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit -q`
- **After every plan wave:** Run `poetry run pytest tests`
- **Before `/gsd-verify-work`:** Full suite must be green, INCLUDING the two per-phase gates:
  - `poetry run pytest tests/integration/test_backtest_oracle.py` (byte-exact `134 / 46189.87730727451`)
  - `poetry run pytest tests/integration/test_okx_inertness.py` (live-stack import inertness)
- **Max feedback latency:** ~10 seconds (unit quick run)

---

## Per-Task Verification Map

> Filled by the planner/executor once PLAN.md task IDs exist. Each success
> criterion below MUST map to at least one automated task (see 07-RESEARCH.md
> § Validation Architecture for the criterion→test mapping).

> Wave-0 test scaffolds are created INSIDE the owning plans (not a separate Wave-0 plan) — each row's
> "File Exists" column reflects the plan that authors the test.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-T1/T2/T3 | 01 | 1 | SAFE-01/03/06 | T-07-01/06 | `OrderRiskRole` enum, msgspec CONTROL events (fixed-literal reason), static throttle caps | unit | `poetry run pytest tests/unit/core/test_order_risk_role.py tests/unit/events/test_control_events.py tests/unit/config/test_safety_config.py -x` | ❌ W0 (authored in 07-01) | ⬜ pending |
| 07-02-T1/T2 | 02 | 1 | SAFE-05 | T-07-09/02 | CF-7 typed `ReconciliationError` guard; coordinator keyed on account kind, not `exchange=='okx'` | unit | `poetry run pytest tests/unit/portfolio/test_reconciliation_coordinator.py -x` | ❌ W0 (authored in 07-02) | ⬜ pending |
| 07-03-T1/T2 | 03 | 2 | SAFE-01/02 | T-07-02/05/07/11 | Pure `SafetyController` latch/halt/pause/resume/gate; `check_durable_halt_on_start` refuses RUNNING; D-11 overflow→HALT; shared `classify()` | unit | `poetry run pytest tests/unit/trading_system/test_safety_controller.py tests/unit/core/test_order_risk_role.py -x` | ❌ W0 (authored in 07-03) | ⬜ pending |
| 07-04-T1/T2 | 04 | 3 | SAFE-04 | T-07-03/12/13 | `StreamRecoveryHandler.on_reconnect` resume; D-12 stay-paused-on-failure; CF-2 loop-native + no-engine-thread-ring-writer assertion | unit + integration | `poetry run pytest tests/unit/trading_system/test_stream_recovery_handler.py tests/integration/test_resume_missed_fill_catchup.py tests/integration/test_resume_gated_on_all_streams.py -x` | ❌/✅ (unit W0; resume tests extended) | ⬜ pending |
| 07-05-T1 | 05 | 3 | SAFE-06 | T-07-04/07/08 | Throttle rejects over-cap ENTRY → `FillEvent(REFUSED)`; CANCEL/PROTECTIVE bypass uncounted; injected-clock window; Decimal notional; de-duped WARNING | unit | `poetry run pytest tests/unit/trading_system/test_pre_trade_throttle.py -x` | ❌ W0 (authored in 07-05) | ⬜ pending |
| 07-06-T1/T2/T3 | 06 | 4 | SAFE-03 (+02/04/05/06 wiring) | T-07-06/02/03/10 | CONTROL routes on engine thread; flag side-channel deleted; delegator facade; `build_live_system` wiring; check_durable_halt first | integration | `poetry run pytest tests/integration/test_live_system_okx_wiring.py tests/integration/test_early_durable_halt_refusal.py tests/integration/test_durable_halt.py -x` | ❌/✅ (control-route new; durable tests repointed) | ⬜ pending |
| Gate | all | — | Oracle byte-exact | — | `134 / 46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| Gate | all | — | Import inertness | T-07 (backtest-dark) | live stack stays off the backtest import graph | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave-0 test scaffolds are embedded in the owning plans (final paths below):

- [ ] `tests/unit/trading_system/test_safety_controller.py` — pure `SafetyController` isolation + D-11 overflow→HALT + `check_durable_halt_on_start` (SAFE-01/02) — **Plan 07-03**
- [ ] `tests/unit/core/test_order_risk_role.py` — `OrderRiskRole` enum (Plan 07-01) + shared `classify()` CANCEL/PROTECTIVE/ENTRY (Plan 07-03) — SAFE-01
- [ ] `tests/unit/events/test_control_events.py` — msgspec `StreamStateEvent`/`ConnectorFatalEvent` type pins + fixed-literal reason (SAFE-03) — **Plan 07-01**
- [ ] `tests/unit/config/test_safety_config.py` — throttle default caps + extra=forbid + `SystemConfig.safety` (SAFE-06) — **Plan 07-01**
- [ ] `tests/integration/test_live_system_okx_wiring.py` — CONTROL-route test (STREAM_STATE/CONNECTOR_FATAL on engine thread; flags absent) (SAFE-03) — **Plan 07-06**
- [ ] extend `tests/integration/test_resume_missed_fill_catchup.py` + `test_resume_gated_on_all_streams.py` with the CF-2 no-engine-thread-ring-writer assertion (SAFE-04) — **Plan 07-04**
- [ ] `tests/unit/trading_system/test_stream_recovery_handler.py` — resume + D-12 stay-paused (SAFE-04) — **Plan 07-04**
- [ ] `tests/unit/portfolio/test_reconciliation_coordinator.py` — account-kind keying + CF-7 typed guard (SAFE-05) — **Plan 07-02**
- [ ] `tests/unit/trading_system/test_pre_trade_throttle.py` — sliding-window rate + max-notional; ENTRY-only; CANCEL/PROTECTIVE bypass; de-duped WARNING (SAFE-06) — **Plan 07-05**
- [ ] Confirm the two per-phase gates stay green (oracle `134 / 46189.87730727451` + inertness)

Note (MEMORY): do NOT add `__init__.py` to `tests/unit/*` dirs (package-collision breaks full-suite collection).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | All P7 behaviors are automatable (pure state machine + event routing + throttle are unit/integration-testable; the design is live-only but exercised via injected clock + simulated connector callbacks) | — |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
