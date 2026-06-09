---
phase: 1
slug: codebase-map-clarity-baseline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> **Phase 1 is a pure-analysis, documentation-only phase** — deliverables are committed planning
> artifacts (a fix-list + a written cleanup standard), NOT engine code. There are no source-code
> changes, so validation here is primarily **artifact-existence + content-assertion** checks, plus a
> **golden-master no-drift guard** to prove the engine was not touched.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing; not the primary verifier this phase) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `grep`/`test -f` assertions against the produced `.md` artifacts |
| **Full suite command** | `make test` (regression guard only — must remain green/unchanged) |
| **Estimated runtime** | ~1 second (doc assertions); full suite per existing baseline |

---

## Sampling Rate

- **After every task commit:** Run the artifact assertion for that task (`test -f`, `grep` for required sections/columns/IDs).
- **After every plan wave:** Re-verify all artifact assertions for the wave.
- **Before `/gsd:verify-work`:** All required artifacts exist with required content; golden master unchanged (no source paths touched in this phase).
- **Max feedback latency:** 5 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | CLAR-01 | — | N/A (docs only) | doc-assert | `test -f .planning/codebase/FIX-LIST.md` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | CLAR-01 | — | N/A | doc-assert | `grep -E 'FL-0?1' .planning/codebase/FIX-LIST.md` (items harvested incl. #7/#37, #10) | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | CLAR-02 | — | N/A | doc-assert | `grep -i 'opportunistic' PROJECT.md` (standard recorded) | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | CLAR-02 | — | N/A (no source touched) | regression | golden master unchanged — no `itrader/` diff in phase commits | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.planning/codebase/FIX-LIST.md` — created by Plan 01 (no test stub; artifact IS the deliverable)
- [ ] Opportunistic-cleanup standard text — created by Plan 02 in `PROJECT.md` Key Decisions

*Existing infrastructure (pytest) covers regression-guard needs; no new test framework required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Fix-list is objective & non-padded (only real post-refactor concerns) | CLAR-01 | Editorial judgment — automation can count rows but not assess relevance | Reviewer reads FIX-LIST.md; confirms each item traces to CONCERNS.md / map / verified carry-forward (#7/#37, #10); no invented items |
| Cleanup standard is enforceable at milestone close | CLAR-02 | The verification is a future milestone-close audit, not runnable now | Reviewer confirms the 4-gate checklist + milestone-close audit step are written and unambiguous |

---

## Validation Sign-Off

- [ ] All tasks have an automated artifact assertion or are listed as manual-only
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] Golden-master no-drift guard included (proves no source touched)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
