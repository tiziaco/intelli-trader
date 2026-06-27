---
phase: 6
slug: bar-feed-window-copies-optional-slip-able
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-24
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Quick run command** | `poetry run pytest tests/unit/price -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~quick: <30s · full: minutes |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/price -q`
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite + byte-exact oracle (`tests/integration/test_backtest_oracle.py`) must be green
- **Max feedback latency:** ~30 seconds (quick)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 6-01-01 | 01 | 1 | PERF-06 | — | N/A | unit | `poetry run pytest tests/unit/price -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Planner fills the full task-to-test map. Hard anchors: D-08 drift/equivalence test (content-equality across sampled ticks; mutation of a returned window RAISES `ValueError` via a direct numpy write — NOT a pandas `.iloc` assignment which raises a copy-warning under `filterwarnings=error`; 7-rule bar-timing contract green). Gate (a) = byte-exact oracle (134 / `46189.87730727451`). Gate (b) = `perf-w2` ≥10% at 50 symbols + W1 non-regression.*

---

## Wave 0 Requirements

- [ ] Drift/equivalence test stub under `tests/unit/price/` (co-located with the existing 7-rule contract tests in `tests/unit/price/test_bar_feed.py`, per RESEARCH open-question on D-08 home) — covers PERF-06 behavior-preservation
- [ ] Existing pytest infrastructure covers the rest (oracle, e2e, contract tests already present)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gate (b) W2 ≥10% @ 50 symbols + W1 non-regression | PERF-06 | Wall-clock benchmark; thermal-drift sensitive — same-session/same-machine before/after capture | Run `perf-w2`/`perf-w1` before and after on a cool machine; commit `W2-BASELINE.json`, re-freeze `W1-BASELINE.json` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
