---
phase: 01-dead-code-doc-hygiene
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/codebase/CONCERNS.md
  - .planning/ROADMAP.md
  - .planning/codebase/CONVENTIONS.md
  - CLAUDE.md
autonomous: true
requirements: [DEAD-02]

must_haves:
  truths:
    - "The obsolete CONCERNS.md screener_event_handler 'known bug' entry is removed outright — the file was deleted in M2-11 so the concern can no longer exist (per D-03)"
    - "ROADMAP 999.5-(d) is TRIMMED to one tight factual closure line (FL-01/FL-02 closed in v1.1, ref quick 260610-sjp); the redundant self-referential 'corrected in v1.2 Phase 1 / DEAD-02' forward-pointer is dropped — net reduction, not growth (per D-03)"
    - "All FOUR conventions are documented in .planning/codebase/CONVENTIONS.md (authoritative full write-up): config-enum-in-config exception (W2-13), broad-except run-mode policy, tab/space indentation hazard, dual-layer validator overlap as justified-by-decision (per D-01, D-02)"
    - "Root CLAUDE.md carries a concise convention pointer/cross-reference for the four conventions (per D-01) — reinforcing, not duplicating, what it already states for indentation and run-mode policy"
    - "The dual-layer validator overlap is DOCUMENTED as justified-by-decision; the validator CODE is NOT removed (per D-02 convention 4)"
    - "No broader ROADMAP/CONCERNS prune is performed beyond the two named stale entries (per D-03 — scope creep avoided)"
    - "Zero source files touched; golden master byte-exact (134 trades / final_equity 46189.87730727451); mypy --strict clean; 58/58 e2e green (doc-only edits cannot move the oracle)"
  artifacts:
    - path: ".planning/codebase/CONCERNS.md"
      provides: "Known Bugs section without the obsolete screener_event_handler entry"
    - path: ".planning/ROADMAP.md"
      provides: "trimmed 999.5-(d) closure line for FL-01/FL-02"
    - path: ".planning/codebase/CONVENTIONS.md"
      provides: "authoritative write-up of the four conventions"
      contains: "config-enum"
    - path: "CLAUDE.md"
      provides: "concise convention cross-reference pointer"
  key_links:
    - from: "CLAUDE.md"
      to: ".planning/codebase/CONVENTIONS.md"
      via: "cross-reference pointer to the authoritative convention home"
      pattern: "CONVENTIONS"
    - from: ".planning/ROADMAP.md 999.5-(d)"
      to: ".planning/codebase/FIX-LIST.md FL-01/FL-02"
      via: "traceability ref (quick 260610-sjp)"
      pattern: "260610-sjp"
---

<objective>
Correct two stale documentation entries and document four established conventions (DEAD-02).
This is a documentation-only plan: it touches NO source files and therefore cannot move the
golden-master oracle. The edit style is "trim to truth" (D-03) — current-state docs, not
append-only logs: remove resolved cruft, leave tight factual lines.

Purpose: make the planning docs tell the truth (the screener concern is gone; FL-01/FL-02
are closed) and pin four conventions so future agents stop re-litigating them.
Output: 4 edited doc files; the four conventions documented in CONVENTIONS.md + a concise
pointer in CLAUDE.md; oracle untouched.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-dead-code-doc-hygiene/01-CONTEXT.md
@.planning/codebase/FIX-LIST.md

<convention_source_facts>
Verified during planning so the executor writes truthfully (D-02):
1. **config-enum exception (W2-13):** the seven `str, Enum` config-domain enums (e.g.
   `FeeModelType`, `SlippageModelType`, `PortfolioType`) live in `config/` (`config/exchange.py`,
   `config/portfolio.py`, `config/system.py`) NOT in `core/enums/` BY DESIGN — they are consumed
   only by their co-located Pydantic models; relocating them would invert the core→config
   dependency. Adjudicated acceptable.
2. **broad-except run-mode policy:** backtest is fail-fast (`EventHandler._on_handler_error`
   re-raises); live is publish-and-continue (`LiveTradingSystem` emits `ErrorEvent`, keeps
   draining). CONVENTIONS.md Error Handling already states this at line ~90 — reinforce that it
   is an INTENTIONAL policy, not an inconsistency. Do not duplicate; tighten/annotate.
3. **tab/space indentation hazard:** tabs in handler modules; 4 spaces in `config/`, `core/`,
   `price_handler/feed/`, events package, and tests. CONVENTIONS.md Code Style already states this
   at lines ~44-47 — reinforce "match the file, never normalize."
4. **dual-layer validator overlap (W4-04):** `order_validator.py:176-260` /
   `simulated.py:375-434` price/qty validation is JUSTIFIED-BY-DECISION (defense-in-depth — the
   exchange must validate independently because `create_order` and live paths bypass the domain
   validator). DOCUMENT it; do NOT remove the code.

CONVENTIONS.md section homes (natural placement, Claude's Discretion per D-05): Code Style
(indentation), Error Handling (run-mode policy + validator overlap), Type Hints / a new note
(config-enum exception). CONVENTIONS.md is regenerated by map-codebase, which is WHY D-01 also
requires the concise pointer in CLAUDE.md (survives per-session context).
</convention_source_facts>

<doc_edit_targets>
- `.planning/codebase/CONCERNS.md` lines ~25-31: the `## Known Bugs` section, "Dead
  `screener_event_handler` with a latent `AttributeError`" entry — remove the whole entry
  (file deleted in M2-11). If it was the only Known Bugs item, leave the `## Known Bugs`
  header with a brief "(none currently open)" line rather than an empty section — match the
  surrounding doc style.
- `.planning/ROADMAP.md` lines ~261-266: the 999.5-(d) "Order lifecycle completion" bullet.
  The last sentence currently reads "The v1.1 fix-list stragglers FL-01/FL-02 were marked
  **done** (quick 260610-sjp) — their stale ROADMAP text is corrected in v1.2 Phase 1 /
  DEAD-02." Drop the self-referential "their stale ROADMAP text is corrected in v1.2 Phase 1 /
  DEAD-02" clause (it self-stales the moment this plan lands) and leave one tight factual
  closure line: FL-01/FL-02 closed in v1.1 (quick 260610-sjp). NET REDUCTION. Do NOT touch the
  (a)/(b)/(c) bullets or any other ROADMAP section.
- `.planning/codebase/CONVENTIONS.md`: sections Code Style (line ~40), Type Hints (line ~54),
  Error Handling (line ~77).
- `CLAUDE.md` (repo root): already documents indentation (Conventions section) and the run-mode
  policy (Architecture section) — reinforce/cross-reference, do not duplicate wholesale.
</doc_edit_targets>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Trim the two stale doc entries (CONCERNS + ROADMAP)</name>
  <files>.planning/codebase/CONCERNS.md, .planning/ROADMAP.md</files>
  <read_first>
    - .planning/codebase/CONCERNS.md lines 25-45 (the Known Bugs entry to remove)
    - .planning/ROADMAP.md lines 254-271 (the 999.5-(d) bullet to trim)
    - .planning/codebase/FIX-LIST.md lines 54-55, 71 (confirms FL-01/FL-02 done, quick 260610-sjp — the traceability ref)
    - .planning/phases/01-dead-code-doc-hygiene/01-CONTEXT.md (D-03 trim-to-truth style)
  </read_first>
  <action>
    In `.planning/codebase/CONCERNS.md`: remove the entire "Dead `screener_event_handler` with a
    latent `AttributeError`:" entry under `## Known Bugs` (the heading line plus its Symptoms /
    Files / Trigger / Workaround bullets, lines ~27-31). The file was deleted in M2-11 so the
    concern can no longer exist (D-03). If this leaves `## Known Bugs` empty, add a single line
    "(none currently open)". Do NOT prune any other CONCERNS entry — out of scope (scope creep).

    In `.planning/ROADMAP.md` 999.5-(d) bullet: edit only the final sentence. Replace
    "The v1.1 fix-list stragglers FL-01/FL-02 were marked **done** (quick 260610-sjp) — their
    stale ROADMAP text is corrected in v1.2 Phase 1 / DEAD-02." with a single tight factual
    closure line stating FL-01/FL-02 were closed in v1.1 (quick 260610-sjp). Drop the
    self-referential "corrected in v1.2 Phase 1 / DEAD-02" forward-pointer entirely — the result
    must be a NET REDUCTION (a slightly shorter bullet), not a longer annotated one. Touch nothing
    else in ROADMAP.
  </action>
  <verify>
    <automated>! grep -q "screener_event_handler" .planning/codebase/CONCERNS.md && ! grep -q "corrected in v1.2 Phase 1 / DEAD-02" .planning/ROADMAP.md && grep -q "260610-sjp" .planning/ROADMAP.md && echo OK</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n "screener_event_handler" .planning/codebase/CONCERNS.md` returns nothing
    - `grep -n "corrected in v1.2 Phase 1 / DEAD-02" .planning/ROADMAP.md` returns nothing (forward-pointer dropped)
    - `grep -n "260610-sjp" .planning/ROADMAP.md` still returns the 999.5-(d) closure line (traceability ref kept)
    - The 999.5-(d) bullet is shorter than before (net reduction) and still references FL-01/FL-02 as done
    - No other CONCERNS or ROADMAP section is modified (diff scoped to the two named entries)
  </acceptance_criteria>
  <done>The obsolete screener_event_handler known-bug is removed; the 999.5-(d) bullet is trimmed to one factual FL-01/FL-02 closure line with the quick-task ref retained.</done>
</task>

<task type="auto">
  <name>Task 2: Document the four conventions in CONVENTIONS.md (authoritative) + CLAUDE.md pointer</name>
  <files>.planning/codebase/CONVENTIONS.md, CLAUDE.md</files>
  <read_first>
    - .planning/codebase/CONVENTIONS.md lines 40-122 (Code Style, Type Hints, Error Handling, Function & Module Design — the placement homes)
    - CLAUDE.md (the Conventions section + the Architecture run-mode / indentation notes already present)
    - .planning/phases/01-dead-code-doc-hygiene/01-CONTEXT.md (D-01 dual home, D-02 the four conventions verbatim)
    - .planning/codebase/V1.2-CLEANUP-REVIEW.md rows W2-13 (config-enum exception, ~line 65) and W4-04 (validator overlap) for the adjudication wording
  </read_first>
  <action>
    In `.planning/codebase/CONVENTIONS.md` (the authoritative, full write-up per D-01), document
    all four conventions using the verified convention_source_facts above. Place each in its
    natural section (Claude's Discretion on exact wording/placement):
    (1) config-enum-in-`config/` exception (W2-13) — add a note (Type Hints or a short
        "Enum Placement" note) that the seven `str, Enum` config-domain enums live in `config/`
        not `core/enums/` by design because they are consumed only by co-located Pydantic models;
        relocating would invert the core→config dependency. Adjudicated acceptable.
    (2) broad-`except` run-mode policy — reinforce in Error Handling (line ~90 already states it)
        that backtest fail-fast vs live publish-and-continue is an INTENTIONAL policy, not an
        inconsistency. Tighten, do not duplicate.
    (3) tab/space indentation hazard — reinforce in Code Style (lines ~44-47 already state it)
        with "match the file, never normalize."
    (4) dual-layer validator overlap (W4-04) — add to Error Handling (or Function & Module Design)
        that the `order_validator.py:176-260` / `simulated.py:375-434` price/qty validation overlap
        is JUSTIFIED-BY-DECISION (defense-in-depth; the exchange must validate independently because
        `create_order` and live paths bypass the domain validator). State explicitly: DOCUMENT,
        do NOT remove.

    In root `CLAUDE.md` (concise pointer per D-01 — it is what Claude reads every session, and
    CONVENTIONS.md is regenerated by map-codebase so the convention must also survive here): add a
    short cross-reference noting the four documented conventions and pointing to
    `.planning/codebase/CONVENTIONS.md` as the authoritative home. Reinforce — do NOT duplicate the
    full write-ups — for indentation and run-mode policy CLAUDE.md already covers; just ensure the
    config-enum exception and the validator-overlap justification are at least named with a pointer.
  </action>
  <verify>
    <automated>grep -qi "config-enum\|config/.*enum\|enum.*config/" .planning/codebase/CONVENTIONS.md && grep -qi "justified-by-decision\|defense-in-depth\|defence-in-depth" .planning/codebase/CONVENTIONS.md && grep -qi "CONVENTIONS" CLAUDE.md && echo OK</automated>
  </verify>
  <acceptance_criteria>
    - CONVENTIONS.md documents the config-enum-in-`config/` exception (W2-13) with the core→config-inversion rationale
    - CONVENTIONS.md states the broad-`except` run-mode policy is intentional (backtest fail-fast vs live publish-and-continue)
    - CONVENTIONS.md reinforces the tab/space indentation "match the file, never normalize" rule
    - CONVENTIONS.md documents the dual-layer validator overlap as justified-by-decision and explicitly says the code is NOT removed
    - `grep -rn "176-260\|375-434" itrader/` is irrelevant — NO validator code is changed (this is documentation only; verify no source diff in Task 3)
    - CLAUDE.md contains a concise pointer to `.planning/codebase/CONVENTIONS.md` for the four conventions
  </acceptance_criteria>
  <done>All four conventions are documented authoritatively in CONVENTIONS.md and cross-referenced concisely in CLAUDE.md; the validator code is untouched.</done>
</task>

<task type="auto">
  <name>Task 3: Confirm doc-only — no source touched, oracle byte-exact</name>
  <files>(verification only — no edits)</files>
  <read_first>
    - .planning/ROADMAP.md §Phase 1 Success Criteria (criterion 4)
    - .planning/STATE.md Milestone Gate (oracle numbers)
  </read_first>
  <action>
    Confirm this plan changed ONLY documentation, never source. Verify the git diff for this plan
    touches no path under `itrader/` or `tests/`. Then run the milestone gate to prove the doc
    edits left the engine untouched: `poetry run mypy --strict`, the byte-exact integration oracle
    `poetry run pytest tests/integration`, and the e2e leaf `poetry run pytest tests/e2e -m e2e`.
    (Doc-only edits cannot move the oracle; this is a guard against an accidental stray source edit.)
  </action>
  <verify>
    <automated>git diff --name-only | grep -E "^(itrader|tests)/" && echo "SOURCE TOUCHED - FAIL" || (poetry run mypy --strict && poetry run pytest tests/integration tests/e2e -m e2e -q)</automated>
  </verify>
  <acceptance_criteria>
    - `git diff --name-only` for this plan lists only files under `.planning/` and root `CLAUDE.md` — no `itrader/` or `tests/` paths
    - `poetry run mypy --strict` exits 0
    - `poetry run pytest tests/integration` byte-exact: 134 trades / final_equity 46189.87730727451
    - `poetry run pytest tests/e2e -m e2e` 58/58 green
  </acceptance_criteria>
  <done>Diff is documentation-only; oracle byte-exact; mypy clean; e2e 58/58 — doc edits confirmed inert to the engine.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none introduced) | This plan edits planning docs + CLAUDE.md only. No runtime path, input handling, auth, secrets, or network surface is added or touched. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-03 | Tampering | Accidental stray source edit while editing docs | mitigate | Task 3 asserts `git diff --name-only` lists no `itrader/`/`tests/` path, plus byte-exact oracle + mypy --strict. No new attack surface — documentation only. |
| T-01-04 | Information disclosure | Removing a CONCERNS security entry by over-pruning | mitigate | D-03 scopes the edit to ONE named obsolete Known-Bugs entry; "do not prune any other CONCERNS entry" instruction; the Security Considerations section is explicitly out of scope. |
| T-01-SC | Tampering | npm/pip/cargo installs | n/a | No package installs in this plan — documentation edits only, no dependency changes. |
</threat_model>

<verification>
Phase-level checks for this plan:
- `grep -n "screener_event_handler" .planning/codebase/CONCERNS.md` returns nothing.
- ROADMAP 999.5-(d) trimmed: no "corrected in v1.2 Phase 1 / DEAD-02" forward-pointer; 260610-sjp ref retained.
- CONVENTIONS.md documents all four conventions; CLAUDE.md cross-references them.
- Validator code under `itrader/` unchanged (documentation only).
- `git diff --name-only` lists only `.planning/` + `CLAUDE.md`.
- Oracle byte-exact (134 / 46189.87730727451); mypy --strict clean; 58/58 e2e.
</verification>

<success_criteria>
Measurable completion:
1. CONCERNS.md screener_event_handler known-bug removed; ROADMAP 999.5-(d) trimmed to a tight
   FL-01/FL-02 closure line (net reduction, ref retained).
2. All four conventions documented in CONVENTIONS.md (authoritative) + concise pointer in CLAUDE.md;
   validator code NOT removed.
3. Doc-only diff; golden master byte-exact (134 / 46189.87730727451); mypy --strict clean; 58/58 e2e.
</success_criteria>

<output>
Create `.planning/phases/01-dead-code-doc-hygiene/01-02-SUMMARY.md` when done.
</output>
