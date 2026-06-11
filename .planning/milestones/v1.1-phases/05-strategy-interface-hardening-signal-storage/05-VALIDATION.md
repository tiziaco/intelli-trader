---
phase: 5
slug: strategy-interface-hardening-signal-storage
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.x (via Poetry; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest test/test_strategy/ -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/integration/test_backtest_oracle.py -q` (byte-exact golden gate — the HARD-04 guardrail) plus the touched unit suite.
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green AND the oracle test byte-exact (134 trades / `final_equity 46189.87730727451`)
- **Max feedback latency:** ~10 seconds (oracle gate alone)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | REQ-{XX} | T-{N}-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Note: the executor populates this map per task during execution. Every Phase 5 task is additionally gated by the byte-exact oracle (HARD-04) regardless of its own unit coverage.*

---

## Wave 0 Requirements

- [ ] Existing infrastructure covers all phase requirements — `tests/integration/test_backtest_oracle.py` (byte-exact golden gate) and `test/test_strategy/` already exist.
- [ ] New test stubs for the `SignalStore` seam (SIG-01/SIG-02) and `BaseStrategyConfig` validators (HARD-01/HARD-02) are added in-wave by the plans that introduce those modules.

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Byte-exact golden master re-run | HARD-04 | Automated via `test_backtest_oracle.py` — no manual step required | N/A |

*All phase behaviors have automated verification (oracle gate + unit tests).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
