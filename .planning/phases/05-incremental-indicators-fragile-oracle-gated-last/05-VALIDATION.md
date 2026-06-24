---
phase: 5
slug: incremental-indicators-fragile-oracle-gated-last
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-24
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (Poetry) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Quick run command** | `poetry run pytest tests/unit/strategy -q` |
| **Full suite command** | `make test` (or `poetry run pytest tests` in a worktree) |
| **Estimated runtime** | ~TBD seconds (planner to fill) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/strategy -q`
- **After every plan wave:** Run the full suite
- **Before `/gsd:verify-work`:** Full suite must be green + oracle + cross-val gate
- **Max feedback latency:** TBD seconds

---

## Per-Task Verification Map

> Planner fills this from RESEARCH.md "## Validation Architecture" (maps the 4 Success Criteria
> to concrete test surfaces — convergence test, reset test, causal-guard test, EMA/RSI re-baseline,
> golden re-freeze, oracle behavioral-identity vs numeric-values split).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | A/B/C | — | PERF-05 | — | N/A | unit/integration | TBD | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> Planner to finalize from RESEARCH.md (5 flagged gaps):

- [ ] ta-convergence test (P5-D17) — all four indicators, post-warmup, ~1e-9 abs / 1e-6 rel
- [ ] `reset()` → re-feed reproduces fresh run (P5-D19)
- [ ] causal-guard rejects non-causal adapters (P5-D20)
- [ ] EMA/RSI re-baselined unit tests (P5-D12)
- [ ] golden oracle re-freeze + cross-val gate re-run (P5-D02)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| W1 perf re-freeze (Gate b) | PERF-05 | Thermally sensitive; same-machine A/B on a cool machine | See `04-PERF-ATTRIBUTION.md` method (P5-D03) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < TBDs
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
