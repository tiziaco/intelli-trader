---
phase: 5
slug: real-sandbox-path-reconciliation-persistence-live-drive
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-02
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~{N} seconds |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit -q`
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** {N} seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | REQ-{XX} | T-{N}-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Populated during planning from RESEARCH.md §Validation Architecture (11 Wave-0 test files + shared FakeLiveConnector; offline reconciliation gate + opt-in network-gated `slow` live-sandbox suite per D-09).*

---

## Wave 0 Requirements

- [ ] Offline reconciliation fixtures (mocked/recorded OKX payloads) — deterministic, credential-free
- [ ] Shared `FakeLiveConnector` test double
- [ ] Opt-in live-sandbox suite scaffold (`skipif-no-creds`, marked `slow`)

*Derived from RESEARCH.md §Validation Architecture — finalized at planning time.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| {behavior} | REQ-{XX} | {reason} | {steps} |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < {N}s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
