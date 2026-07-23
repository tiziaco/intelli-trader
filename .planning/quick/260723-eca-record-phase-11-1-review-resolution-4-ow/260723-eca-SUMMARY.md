---
id: 260723-eca
title: "Record the Phase 11.1 review resolution + 4 owner decisions"
status: complete
type: quick
scope: docs-only
branch: v1.8/phase-11.1-account-provisioning
started_from: d245b01a
commit: 631d7e30
created: 2026-07-23
completed: 2026-07-23
files_created:
  - .planning/todos/pending/venue-bundle-memo-check-then-set-race.md
  - .planning/todos/pending/account-reservation-ledger-narrow-port.md
  - .planning/todos/pending/fee-model-provider-venue-blind.md
files_modified:
  - .planning/phases/11.1-account-provisioning-mandatory-account-identity/11.1-REVIEW.md
  - .planning/todos/pending/enable-margin-runtime-flip-vs-fixed-account-kind.md
---

# Quick Task 260723-eca: Record the Phase 11.1 review resolution

Documentation transcription of the Phase 11.1 code-review closure: 7 of 12 findings closed in
code, 4 owner decisions recorded with their rationale, and 3 new todos filed for the work queued
into Phase 11.2 and Phase 12.

## What was written

**`11.1-REVIEW.md`** — appended a `## Resolution (2026-07-23)` section *after* the review's
`_Reviewed / _Reviewer / _Depth` footer, so the footer still closes the review proper and the
resolution reads as the later addendum it is. Contents: a disposition table for all 12 findings;
the 7 closed findings with their commits and the two delivering quick tasks (`260723-dc4`,
`260723-dq7`); the post-fix gate state; four decision subsections (CR-02, WR-04+WR-08, WR-01,
WR-03); and a standing `CR-*`/`WR-*` namespace-collision hazard for whoever plans Phase 11.2.

The existing 12 findings were **not** touched — no rewrites, no renumbering, no edits.

**Frontmatter `status:`** — moved `issues_found` → `partially_resolved`. This value already
exists in this repo's convention (6 uses across `*-REVIEW.md`, alongside `resolved`,
`fully_resolved`, `partially_remediated`, `clean`, `issues`), so no new value was invented. The
body's `**Status:** issues_found` header line was deliberately left unchanged — it records the
state at review time and falls under the append-only instruction; the Resolution section says so
explicitly.

**`enable-margin-runtime-flip-vs-fixed-account-kind.md`** — existing analysis kept verbatim;
added `resolves_by: Phase 11.2` to the frontmatter and a `## Decision (2026-07-23)` section
selecting option 1 (reject the flip) with the five-collaborator rationale, including the point
that four of the five are already desynchronized by a runtime flip today.

**Three new todos**, all matching the `venue-requirement-id-collision-v18.md` frontmatter shape
(`id` / `title` / `status` / `severity` / `source` / `created` / `resolves_by`):

| File | Source | resolves_by |
|------|--------|-------------|
| `venue-bundle-memo-check-then-set-race.md` | 11.1-REVIEW.md (WR-06) | Phase 12 |
| `account-reservation-ledger-narrow-port.md` | 2026-07-23 design discussion following WR-04 | Phase 12 |
| `fee-model-provider-venue-blind.md` | 11.1-REVIEW.md (WR-01) | Phase 11.2 |

## Cross-links written

- Resolution section → `venue-requirement-id-collision-v18.md` (same namespace-collision class)
- Resolution section → all three new todos, plus the enable-margin todo
- `venue-bundle-memo-check-then-set-race.md` ↔ `account-reservation-ledger-narrow-port.md`
  (the two Phase 12 items out of this review)
- `account-reservation-ledger-narrow-port.md` → records the 11.2 WR-04 required-kwarg fix as a
  down-payment on the narrow port, not throwaway work
- both `enable-margin-*` and `fee-model-provider-venue-blind` → back to the Resolution section

## Verification

**No test gates were run, by design.** This task is docs-only: nothing under `itrader/`,
`tests/` or `scripts/` was touched, so the oracle, OKX import-inertness and `mypy` gates are
structurally unreachable — there is no importable change for them to observe. Running them would
only re-measure the state already recorded from quick tasks `260723-dc4` / `260723-dq7`
(oracle byte-exact `134 / 46189.87730727451`, inertness green, `mypy itrader` clean over 282
files, 2879 passed / 6 skipped, `run_live_paper.py --mode replay` exit 0 at 134 trades).

What *was* verified:

- `git status --short` before staging showed exactly the 5 intended files and nothing else;
- `git show --stat` confirms 5 files, 400 insertions, 1 deletion — that single deletion is the
  replaced `status:` frontmatter line, so no existing review content was removed;
- the `partially_resolved` status value was checked against every `*-REVIEW.md` in `.planning/`
  before being used, rather than invented;
- `git check-ignore` confirmed `.planning/` is tracked in this repo.

## Deviations from plan

None. Every fact written was supplied pre-verified in the dispatch and was transcribed rather
than re-derived; no claim was independently re-checked against the codebase, and no internal
contradictions were found that would need reporting.

One judgement call left open by the prompt was exercised: the Resolution section was placed
*after* the review footer rather than before it, because a `_Reviewed: 2026-07-22_` footer
trailing a 2026-07-23 resolution would misread as dating the resolution.

## Commit

`631d7e30` — `docs(11.1): record review resolution — 7 closed, 4 owner decisions, 3 todos`

One atomic commit, all 5 files. `SUMMARY.md` / `STATE.md` intentionally not committed here — the
orchestrator owns the docs commit. `ROADMAP.md` untouched as instructed.

## Self-Check: PASSED

All 5 files present on disk; commit `631d7e30` present in `git log`.
