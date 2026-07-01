---
phase: 3
slug: livebarfeed
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-01
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit/price_handler -q` |
| **Full suite command** | `make test` (or `poetry run pytest tests` in a worktree) |
| **Estimated runtime** | ~TBD (planner fills) seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** TBD seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | FEED-01..05 | — | N/A | unit | TBD | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Planner: populate one row per task. Cover the FEED-04 taxonomy (in-sequence / gap-backfill-replay / duplicate-drop / revision-forward-only / stale-reject), confirm-gating (FEED-02), warmup one-by-one replay (FEED-03), reconnect-boundary backfill (D-08), and the recurring milestone gate (oracle byte-exact 134 / `46189.87730727451`; W1/W2 inertness probe).*

---

## Wave 0 Requirements

- [ ] `tests/unit/price_handler/test_live_bar_feed.py` — stubs for FEED-01..05 (synthetic `ClosedBar` driver, stub provider)
- [ ] Shared fixtures — synthetic closed-bar sequence builder, monotonic-guard fixtures

*Planner refines.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TBD | TBD | TBD | TBD |

*Target: all Phase-3 behaviors have automated verification (validation is fully offline per RESEARCH — no live socket needed).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < TBDs
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
