---
phase: 5
slug: cache-classification-3
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-30
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `make test` (or `poetry run pytest tests` in a worktree) |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run the relevant quick command (grep-match check + targeted unit subset)
- **After every plan wave:** Run the full suite
- **Before `/gsd:verify-work`:** Full suite green + SMA_MACD oracle byte-exact (`134` / `46189.87730727451`) + `mypy --strict` clean
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

> Drafted during planning — the spine for this phase is the SC2 "grep matches inventory exactly" check
> and the SC3 recurring oracle/mypy/filterwarnings gate. Populate from the planner's task IDs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 1 | CACHE-01 / CACHE-02 | — | N/A (docs/classification) | cli | `grep -rnE 'lru_cache|functools\.cache|@cache|_cache' itrader/` matches `docs/CACHE-CLASSIFICATION.md` inventory | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] SC2 grep-matches-inventory check codified as a runnable assertion (script or test) — anchors the committed map to HEAD
- [ ] SMA_MACD oracle harness available (`tests/integration/test_backtest_oracle.py`) — recurring SC3 gate

*Existing infrastructure (pytest + oracle + mypy --strict + filterwarnings) covers all phase requirements; no new framework needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Classification correctness (a/b/c/d tag per site) | CACHE-01 | Semantic judgement, not mechanically assertable | Reviewer reads `docs/CACHE-CLASSIFICATION.md` against the RESEARCH spine table |

*The grep-matches-inventory and oracle/mypy/filterwarnings checks ARE automated; only the per-site classification judgement is manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
