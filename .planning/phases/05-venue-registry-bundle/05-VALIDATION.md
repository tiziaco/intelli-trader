---
phase: 5
slug: venue-registry-bundle
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `make test` (or `poetry run pytest tests` in a worktree — see memory) |
| **Estimated runtime** | ~10-30 seconds (unit); full suite longer |

**Standing gates (run per-PLAN, every wave):**
- **Byte-exact oracle:** `poetry run pytest tests/integration/test_backtest_oracle.py -q` — must stay `46189.87730727451`
- **OKX inertness (P5 acceptance gate):** `poetry run pytest tests/integration/test_okx_inertness.py -q` — register-vs-build; registering `'okx'` pulls no `ccxt.pro`/async/SQL

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit -q` plus the two standing gates when the task touches live/compose/registry surfaces
- **After every plan wave:** Run `make test` + both standing gates
- **Before `/gsd-verify-work`:** Full suite + both standing gates must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Seeded scaffold — the planner fills concrete per-task rows from each PLAN's `<verify>` blocks and RESEARCH.md `## Validation Architecture`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 1 | VENUE-XX | T-5-XX / — | expected secure behavior or "N/A" | unit | `poetry run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `tests/integration/test_okx_inertness.py` — register-vs-build assertions for the plugin/registry surface (VENUE-01/02, D-04 triple-deferral)
- [ ] New unit tests for the registry / `ConnectorProvider` / `StreamSupervisor` / `assemble_venue` seams (fakes against the `runtime_checkable` Protocols)
- [ ] `resolve_precision` capability tests on `AbstractExchange` (VENUE-04)

*If existing infrastructure covers a requirement, note it in the plan rather than adding a Wave 0 stub.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live OKX connect / real WS stream reconnect | VENUE-03/07 | Requires network + demo creds; not CI-safe | Manual sandbox run against demo sub-account (see memory: OKX demo creds) — offline `ReplayDataProvider` parity gate covers the CI-safe path |

*Offline paper-replay parity + the two standing gates cover the automated surface.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
