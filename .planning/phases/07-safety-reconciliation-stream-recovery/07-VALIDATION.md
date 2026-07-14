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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 01 | 1 | SAFE-01 | — | Pure `SafetyController` status-latch transitions enforce `VALID_STATUS_TRANSITIONS`; `check_durable_halt_on_start()` refuses RUNNING on unresolved durable halt | unit | `poetry run pytest tests/unit -q -k safety_controller` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Test module(s) for the pure `SafetyController` (isolated, no venue I/O) — SAFE-01
- [ ] Test module(s) for CONTROL-event routing (`StreamStateEvent`/`ConnectorFatalEvent` on the engine thread) — SAFE-02
- [ ] Test module(s) for `StreamRecoveryHandler` resume + CF-2 loop-native assertion (no engine-thread path reaches the ring writer) — SAFE-03/SAFE-04
- [ ] Test module(s) for the SAFE-06 pre-trade throttle (sliding-window rate + max-notional; ENTRY-only metering, CANCEL/PROTECTIVE bypass) — SAFE-06
- [ ] Test module(s) for `ReconciliationCoordinator` account-*kind* keying + CF-7 typed guard — SAFE-05
- [ ] Confirm the two per-phase gates stay green (oracle + inertness)

*Precise file paths are set by the planner (Wave 0 tasks) against the final module layout.*

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
