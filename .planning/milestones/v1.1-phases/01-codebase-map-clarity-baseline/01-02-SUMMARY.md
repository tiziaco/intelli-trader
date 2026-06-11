---
phase: 01-codebase-map-clarity-baseline
plan: 02
subsystem: planning-artifacts
tags: [cleanup-standard, clar-02, golden-master, documentation]
requires:
  - ".planning/codebase/FIX-LIST.md (companion artifact, written by plan 01-01; cross-referenced)"
provides:
  - "opportunistic-cleanup standard (4-gate executor checklist + milestone-close audit)"
  - "PROJECT.md Key Decisions pointer row making the standard discoverable"
affects:
  - "every later v1.1 phase plan (the standard governs opportunistic cleanup along touched paths)"
  - "/gsd:complete-milestone (the CLAR-02 milestone-close audit)"
tech-stack:
  added: []
  patterns:
    - "checklist-as-enforcement: no linter/CI; the 4-gate checklist rides the existing golden-master + mypy gates"
key-files:
  created:
    - ".planning/codebase/CLEANUP-STANDARD.md"
  modified:
    - ".planning/PROJECT.md"
decisions:
  - "Standard lives in a dedicated CLEANUP-STANDARD.md (not embedded in PROJECT.md or FIX-LIST.md) — Q1-RESOLVED in RESEARCH, keeps plan 01-01/01-02 file ownership non-overlapping for parallel execution"
  - "Golden-path gate anchors to the v1.0 final oracle byte-exact (134 trades / final_equity 46189.87730727451); no re-baseline permitted in v1.1"
metrics:
  duration: ~4 min
  completed: 2026-06-09
---

# Phase 1 Plan 02: Opportunistic-Cleanup Standard Summary

Established the v1.1 opportunistic-cleanup standard as a written, enforceable, discoverable
contract — a concrete 4-gate executor checklist (path / eligibility / golden-path / bookkeeping)
plus a milestone-close audit — in `.planning/codebase/CLEANUP-STANDARD.md`, with a PROJECT.md Key
Decisions pointer row so every later-phase executor discovers it. Satisfies CLAR-02. No source
touched; golden master unchanged.

## What Was Built

### Task 1 — `CLEANUP-STANDARD.md` (commit 5993bc2)

Created `.planning/codebase/CLEANUP-STANDARD.md` containing:

- **Purpose + invariant** — cleanup is opportunistic (touched paths only, no big-bang), riding
  the existing golden-master and `mypy --strict` gates (no linter/CI exists in the repo). The
  load-bearing invariant: the v1.0 oracle (134 trades / `final_equity 46189.87730727451`) is NOT
  re-baselined anywhere in v1.1.
- **4-gate executor checklist** (verbatim in intent from RESEARCH "Opportunistic-Cleanup Standard
  Design"):
  1. **Path gate** — only touch a file already modified by this phase's requirement-driven work.
  2. **Eligibility gate** — only an `open` FIX-LIST.md item on an already-touched path; Category C
     deferred items never eligible in v1.1.
  3. **Golden-path gate** — `Golden-path? yes` ⇒ behavior-preserving, byte-exact oracle re-run,
     `mypy --strict` clean, suite warning-clean under `filterwarnings=["error"]`; `Golden-path? no`
     ⇒ full suite green. No re-baseline (owner-gated finding, never a silent fold-in).
  4. **Bookkeeping gate** — flip the item's `Status` to `done (phase N)` and leave a `# FL-NN`
     reference comment at the fix site, matching the CONVENTIONS.md decision-tag convention; no
     tab/space normalization diffs.
- **Milestone-close audit** — the four checks `/gsd:complete-milestone` runs for CLAR-02 (no
  dropped items; no big-bang diff; oracle byte-exact / no re-baseline; indentation discipline held).
- Cross-reference to `FIX-LIST.md`; "opportunistic" used in title/body for greppability.

### Task 2 — PROJECT.md Key Decisions pointer row (commit b6a735a)

Appended one row to the existing `## Key Decisions` Markdown table pointing at
`CLEANUP-STANDARD.md` (and noting `FIX-LIST.md`), with the `◷ v1.1` in-progress outcome marker
matching the other v1.1 rows. Table header intact; the 5 prior v1.1 rows preserved (now 6).

## Verification

- `test -f .planning/codebase/CLEANUP-STANDARD.md` — PASS
- All Task 1 greps (opportunistic / 4 gates / `46189.87730727451` / milestone-close / FIX-LIST) — PASS
- All Task 2 greps (pointer phrase / CLEANUP-STANDARD / table header / `◷ v1.1` count ≥ 6) — PASS (count = 6)
- Plan-level `git diff --stat HEAD~2 HEAD` — only `.planning/PROJECT.md` and
  `.planning/codebase/CLEANUP-STANDARD.md`; **no `itrader/`, no `tests/`** (T-01-02 tampering
  threat mitigated, golden master untouched).

## Deviations from Plan

None — plan executed exactly as written.

Note: `.planning/codebase/FIX-LIST.md` (referenced as a cross-reference target) is the deliverable
of the parallel wave-1 plan 01-01 and did not yet exist in this worktree at execution time. This is
expected — the pointer is a forward cross-reference, not a hard dependency for writing the standard;
the two plans have non-overlapping file ownership by design (Q1-RESOLVED in 01-RESEARCH).

## Known Stubs

None — both deliverables are complete documentation artifacts with no placeholder content.

## Self-Check: PASSED

- `.planning/codebase/CLEANUP-STANDARD.md` — FOUND
- `.planning/PROJECT.md` (modified) — FOUND
- Commit 5993bc2 (Task 1) — FOUND
- Commit b6a735a (Task 2) — FOUND
