# v1.1 Opportunistic-Cleanup Standard

> **Status:** ESTABLISHED in Phase 1 (Codebase Map & Clarity Baseline), VERIFIED at milestone
> close by `/gsd:complete-milestone` (requirement **CLAR-02**).
>
> **Discoverable from:** `.planning/PROJECT.md` → `## Key Decisions` (the
> "v1.1 opportunistic-cleanup standard" pointer row).
>
> **Companion artifact:** `.planning/codebase/FIX-LIST.md` (the harvested, categorized fix-list
> this standard operates over; `FL-NN` schema, `open` / `done (phase N)` / `deferred` status,
> `Golden-path? yes|no` flag, eligible-in-phase tags).

## Purpose

v1.1 ("Backtest Trustworthiness: Breadth") performs **no big-bang refactor**. Naming and
visibility cleanup is applied **opportunistically** — ONLY along paths a phase is *already*
touching for its own requirement-driven work — and never re-baselines the v1.0 golden numbers.

This document is the single, enforceable home of that practice. It is **not** an aspirational
sentence; it is a concrete **4-gate executor checklist** a later-phase executor runs *before*
applying any cleanup, plus a **milestone-close audit** the milestone-completion command checks
against the commit diffs.

There is no autoformatter, linter, or CI gate configured in this repo (CONVENTIONS.md "Code
Style"). This checklist is the enforcement mechanism — a human/agent checklist riding the
existing golden-master and `mypy --strict` gates.

The locked, load-bearing invariant behind every gate: the v1.0 final golden oracle —
**134 trades / `final_equity 46189.87730727451`** — is NOT re-baselined anywhere in v1.1. Any
result change is an **owner-gated finding**, never a silent fold-in.

---

## The 4-gate executor checklist

A later-phase executor checks **all four gates, in order**, BEFORE applying any cleanup. If any
gate fails, the cleanup is not eligible in this phase — leave the item `open` and move on.

### 1. Path gate

Is the file already being modified by this phase's planned work **for its own requirement**?

- If **NOT** → do not touch it. No big-bang refactor. No drive-by edits to untouched files.
- Cleanup rides on top of requirement-driven changes; it never originates a file edit on its own.

### 2. Eligibility gate

Is there an **`open`** `FIX-LIST.md` item whose `File(s)` falls on a path this phase is already
touching (i.e. a path that passed the Path gate)?

- Only such items are eligible.
- **Category C deferred items are never eligible in v1.1** — they carry an owning milestone and
  are out of scope here.

### 3. Golden-path gate

Look at the item's `Golden-path?` flag in `FIX-LIST.md`:

- **`Golden-path? yes`** — the cleanup MUST be **behavior-preserving**. After the change, the
  golden master MUST re-run **byte-exact**: **134 trades / `final_equity 46189.87730727451`**,
  with `mypy --strict` clean and the suite warning-clean under `filterwarnings=["error"]`.
- **`Golden-path? no`** — still run the full suite green; no oracle interaction is expected.

**No re-baseline is permitted.** If a `Golden-path? yes` cleanup changes the result, STOP: it is
an **owner-gated finding**, not a silent fold-in. Surface it for owner approval; do not edit the
oracle to make the suite pass.

### 4. Bookkeeping gate

In the **same change** that applies the cleanup:

- Flip the item's `Status` to **`done (phase N)`** in `FIX-LIST.md` (N = the phase doing the work).
- Leave a **`# FL-NN`** reference comment at the fix site, matching the existing decision-tag
  comment convention (`# D-04 — string entry`, `# FL-03 — …`; see CONVENTIONS.md "Inline
  comments"). The tag is a load-bearing back-reference from the source to the fix-list.
- Preserve the file's indentation (tabs in handler modules; 4 spaces in `config/`, `core/`,
  `price_handler/feed/`, the events package) — **no tab/space normalization diffs**.

---

## Milestone-close audit (what `/gsd:complete-milestone` verifies for CLAR-02)

At milestone close, the completion command audits the v1.1 commit history against this standard.
CLAR-02 passes only if **all** of the following hold:

- **No dropped items.** Every `FIX-LIST.md` item is either `done (phase N)` on a path that phase
  N legitimately touched (passed the Path gate), or `deferred` with an owning milestone. None
  silently dropped — no item left `open` with no owner and no resolution.
- **No big-bang diff.** No commit in v1.1 shows a "big-bang refactor": a cleanup-only diff
  touching files **outside** any phase's requirement-driven work. Every cleanup rode an
  already-touched path.
- **Oracle byte-exact (no re-baseline).** The golden master is byte-exact against the v1.0 final
  oracle — **134 trades / `final_equity 46189.87730727451`** — at milestone close. No
  re-baseline occurred anywhere in v1.1.
- **Indentation discipline held.** No tab/space normalization diffs in touched files; each fix
  matched the indentation of the file it edited.

---

## One-line summary (for the PROJECT.md pointer)

> v1.1 opportunistic-cleanup standard: apply naming/visibility fixes ONLY along paths a phase
> already touches (no big-bang refactor), re-run the golden master byte-exact (no re-baseline),
> bookkeep against `FIX-LIST.md` with a `# FL-NN` comment — verified at milestone close (CLAR-02).
