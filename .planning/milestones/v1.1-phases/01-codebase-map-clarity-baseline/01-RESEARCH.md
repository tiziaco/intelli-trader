# Phase 1: Codebase Map & Clarity Baseline - Research

**Researched:** 2026-06-09
**Domain:** Planning-artifact engineering (fix-list harvest + cross-cutting cleanup standard). NOT a code phase.
**Confidence:** HIGH

## Summary

Phase 1 is a **pure-analysis, documentation-only** phase. It produces two committed planning
artifacts and touches **zero source files**: (1) an objective, deduplicated **fix-list**
(naming / visibility / seam issues) harvested from the EXISTING, current `.planning/codebase/`
map — not a new `gsd-map-codebase` run — and (2) a written, enforceable **opportunistic-cleanup
standard** that the rest of the v1.1 milestone follows and that is verified at milestone close.

The single most important constraint, confirmed against `CONCERNS.md`, the v1.0 audit, and
`STATE.md`, is that the v1.0 golden oracle (**134 trades / `final_equity 46189.87730727451`**)
is **NOT re-baselined** in v1.1. Phase 1 itself changes no code, so the oracle is trivially
unchanged here; the real work is writing the cleanup standard so that *later* phases apply
naming/visibility fixes only along paths they already touch, re-run the golden master byte-exact,
and never trigger a re-baseline. The fix-list is the harvest; the standard is the discipline that
governs when items become eligible to be fixed.

I verified the two named residual carry-forward items still exist in the current tree:
- **#7/#37** — bare `raise ValueError(...)` in `portfolio.py` (7 sites confirmed at lines
  101, 103, 124, 183, 410, 431, 436), off the golden path.
- **#10** — `portfolio_id: int` annotation carry-over on Signal/Order/Fill events (3 sites
  confirmed: `signal.py:84`, `fill.py:64`, `order.py:52`), runtime-correct (carries a UUID),
  annotation-only.

**Primary recommendation:** Produce a single committed Markdown fix-list at
`.planning/codebase/FIX-LIST.md` using a tabular schema with a stable `FL-NN` ID, category
(naming/visibility/seam/exception/annotation), affected file(s), golden-path flag, and a
**pre-tagged "eligible-in-phase"** column mapping each item to the later v1.1 phase most likely
to touch its path. Write the opportunistic-cleanup standard into the same milestone's working
docs (and reference it from `PROJECT.md` Key Decisions) as a 4-gate executor checklist plus a
milestone-close audit checklist. Perform NO source edits in Phase 1.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Harvest fix-items from existing map | Planning artifacts (`.planning/`) | — | Inputs already exist (`CONCERNS.md` + map files), current as of 2026-06-08 |
| Write committed fix-list | Planning artifacts (`.planning/codebase/`) | — | Consumed by every later phase; lives with the map it derives from |
| Write cleanup standard | Planning artifacts (`PROJECT.md` / milestone docs) | — | Cross-cutting practice; must be discoverable by every later-phase executor |
| Milestone-close verification of CLAR-02 | Verification / audit (`/gsd:complete-milestone`) | — | Standard is VERIFIED at milestone close, not in a standalone phase |
| Source-code cleanup (the fixes themselves) | itrader/ source — **OUT OF SCOPE for Phase 1** | Later phases (2–9) | CLAR-02 cleanup happens along *touched paths* in later phases |

## User Constraints (from ROADMAP / PROJECT / STATE — no CONTEXT.md exists yet)

> No `CONTEXT.md` exists for this phase yet. These constraints are extracted from the
> authoritative ROADMAP Phase 1 detail, PROJECT.md, and STATE.md and carry locked-decision
> authority.

### Locked Decisions
- The codebase map **already exists and is current** (Analysis Date 2026-06-08, after the last
  engine commit `017bf72`). CLAR-01 = **HARVEST** the fix-list from the existing `CONCERNS.md`
  + the 6 map files. This is **NOT** a new `gsd-map-codebase` run. Spot-check only if a doc
  looks stale. [CITED: .planning/ROADMAP.md L43]
- Do **NOT** use `milestones/v1.0-ARCHITECTURE-REVIEW.md` as a fix-list source — it is a
  PRE-v1.0 historical snapshot (2026-06-04); most of its 40 findings were fixed in v1.0.
  Reference only, no finding-by-finding re-audit. [CITED: .planning/ROADMAP.md L44]
- Pull forward the two residual items from the archived `v1.0-COVERAGE-INDEX.md`: **#7/#37**
  (bare `raise ValueError` in `portfolio.py`, off the golden path) and **#10**
  (`portfolio_id: int` annotation carry-over on Signal/Order/Fill events — runtime-correct,
  annotation-only; **may instead land in Phase 5 retype**). [CITED: .planning/ROADMAP.md L45]
- **NO cleanup is performed in this phase itself** (no source paths touched). The golden master
  is unchanged here; any later cleanup must re-run **byte-exact** (no oracle re-baseline). v1.0
  final golden oracle: **134 trades / `final_equity 46189.87730727451`** — NOT re-baselined in
  v1.1. [CITED: .planning/ROADMAP.md L52; PROJECT.md L185; STATE.md L51]
- The opportunistic-cleanup standard is a **CROSS-CUTTING practice** carried through every later
  phase and **VERIFIED at milestone close** — not a standalone phase. [CITED: ROADMAP L26, L51]
- Program constraints still in force: Money = Decimal end-to-end; IDs = single UUIDv7 via
  `uuid-utils`; determinism (seeded RNG + injected clock); tabs in handler modules / 4 spaces in
  `config/`,`core/`,`price_handler/feed/`,events package — **match the file**. [CITED: PROJECT.md L130-141]

### Claude's Discretion
- The exact **format, schema (columns), and file path** of the committed fix-list artifact
  (Question 2). Recommendation below: `.planning/codebase/FIX-LIST.md`, tabular `FL-NN` schema.
- The exact **wording and gate structure** of the opportunistic-cleanup standard, and where it
  is written so later-phase executors discover it (Question 3).
- Whether **#10** is fixed as a stand-alone annotation cleanup or folded into the Phase 5 retype
  (HARD-03 makes `order_type` an enum end-to-end — a natural co-location for the
  `portfolio_id: int` retype). The fix-list should pre-tag #10 as **eligible-in-Phase-5**.

### Deferred Ideas (OUT OF SCOPE)
- Re-running `gsd-map-codebase` to regenerate fresh map docs (the map is current).
- Any source-code edit in Phase 1 (all cleanup happens in later phases along touched paths).
- Re-baselining the golden numbers (v1.1 is behavior-preserving).
- Finding-by-finding re-audit of the 40-item v1.0 architecture review.
- Live-mode / SQL / screener / provider concerns from CONCERNS.md that no v1.1 phase touches —
  list them in the fix-list as **deferred (no eligible v1.1 phase)** so they are recorded but
  not actioned. (Their owning milestones are N+2..N+4 per STATE.md Deferred Items.)
- Third-party graphify / Understand-Anything tooling (ROADMAP cross-cutting note L280-282).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLAR-01 | An objective fix-list (naming, visibility, seams) is harvested/produced | Harvest source inventory below: CONCERNS.md items + CONVENTIONS/STRUCTURE map notes + #7/#37, #10 residuals. Recommended schema + path in "Fix-List Artifact Design". |
| CLAR-02 | Opportunistic naming/visibility cleanup applied ONLY along touched paths — NO big-bang refactor, no oracle re-baseline; ESTABLISHED here, VERIFIED at milestone close | "Opportunistic-Cleanup Standard" section: 4-gate executor checklist + milestone-close audit. Phase 1 writes the standard; it does NOT perform cleanup. |

## Standard Stack

**Not applicable — no packages installed, no runtime dependencies.** Phase 1 produces Markdown
planning artifacts only. No `npm`/`pip`/`cargo` install occurs.

## Package Legitimacy Audit

**Not applicable** — Phase 1 installs no external packages. (No slopcheck/registry verification
needed; no source dependencies are added.)

## Harvest Source Inventory (the raw material for CLAR-01)

This is the deduplicated set of candidate fix-items already recorded in the current map. The
planner scopes the fix-list deliverable from this. Items are grouped by whether a v1.1 phase
will plausibly touch their path (eligible) vs. not (recorded-but-deferred).

### Category A — Residual carry-forward items (MUST be in the fix-list)

| Candidate | Type | File(s) (verified) | Golden path? | Eligible phase | Notes |
|-----------|------|---------------------|--------------|----------------|-------|
| Bare `raise ValueError` → typed domain exception | exception/visibility | `itrader/portfolio_handler/portfolio.py` lines 101,103,124,183,410,431,436 | **No** (off golden path) | Phase 8 (Admission/Position/Cash — touches portfolio.py admission gates) | [VERIFIED: grep] 7 sites confirmed. #7/#37. `core/exceptions/portfolio.py` already has `PortfolioError`/`InsufficientFundsError`/`PortfolioNotFoundError` to use. |
| `portfolio_id: int` annotation carry-over | annotation/naming | `events/signal.py:84`, `events/fill.py:64`, `events/order.py:52` | Touches event facts on golden path (annotation-only, runtime carries UUID) | **Phase 5** (HARD-03 retype) or stand-alone | [VERIFIED: grep] 3 sites confirmed. #10. Annotation-only — runtime-correct. ROADMAP explicitly says "may instead land in Phase 5 retype." |

### Category B — Map-recorded concerns mapped to an ELIGIBLE v1.1 phase

| Candidate | Type | File(s) | Eligible phase | Source |
|-----------|------|---------|----------------|--------|
| Stale `pytest.skip("pending M2-07…")` masking a now-passing FillStatus test | visibility / test-hygiene | `tests/unit/core/test_enums.py:25-40` | Phase 4 (E2E harness work touches the test tree) or opportunistic any phase touching tests | [CITED: CONCERNS.md Known Bugs] FillStatus added Phase 3; skip is dead. |
| Stringly-typed `order_type: str = "market"` on strategy base | naming/seam | `itrader/strategy_handler/base.py:27,38,64` | **Phase 5** (HARD-03 explicitly removes stringly-typed `order_type`) | [VERIFIED: grep] confirmed default `"market"`. This is HARD-03's core target, not a Phase-1 fix. |

### Category C — Map-recorded concerns with NO eligible v1.1 phase (record-but-defer)

> These are real CONCERNS.md items but they live on paths v1.1 does not touch (live / SQL /
> providers / `my_strategies`). The fix-list RECORDS them (CLAR-01 is "objective"), tags them
> deferred with the owning milestone, and the standard's path-eligibility gate keeps them from
> being touched. Do NOT plan fixes for these in v1.1.

| Candidate | Type | File(s) | Owning milestone |
|-----------|------|---------|-------------------|
| `PostgreSQLOrderStorage` is a `NotImplementedError` stub | tech-debt/seam | `order_handler/storage/postgresql_storage.py` | v1.3 (D-sql) |
| SQL table-name injection (`delete_all_tables`, `read_prices`) | security | `price_handler/store/sql_store.py:35,~60` | v1.3 (D-sql) |
| OANDA provider unfinished, Italian TODOs | tech-debt | `price_handler/providers/oanda_provider.py:36,74` | with D-multiasset |
| `my_strategies/*` stranded `long_only` compliance TODO (5 files) | seam/visibility | `strategy_handler/my_strategies/**` | OUT (relocated by user) / v1.2 compliance |
| Stale screener/indicator TODOs (`volume_spyke` window bug, etc.) | tech-debt | `screeners_handler/screeners/**`, `custom_indicators/ehlers_indicators.py:228` | v1.4 (D-screener) |
| Data-download no retry/backoff | robustness | `price_handler/providers/ccxt_provider.py`, `oanda_provider.py` | v1.4 (D-live) |
| Binance streamer unbounded buffer | fragility | `price_handler/providers/binance_stream.py:176` | v1.4 (D-live) |
| Broad `except Exception` in domain logic | fragility (by-design) | `order_manager.py`, `portfolio_handler.py`, `simulated.py` | awareness-only (intentional per CLAUDE.md) |
| Live system / `TradingInterface` zero test coverage | test-gap | `live_trading_system.py`, `trading_interface.py` | v1.4 (D-live) |
| `pandas-ta 0.4.71b0` beta pin | dependency-risk | `pyproject.toml` | isolated to non-reference strategy code |

**Naming/visibility/seam emphasis (CLAR-01's explicit categories):** The convention map
(`CONVENTIONS.md`) documents the *intended* naming/visibility/seam conventions but records **no
violations** of them in the current tree beyond the carry-forwards above — i.e. the post-refactor
naming is largely clean. The objective fix-list should therefore be honest that the naming-fix
surface is small (chiefly #10's annotation and the `order_type` string), the visibility surface
is the bare-`ValueError`/dead-skip items, and the seam surface is the deferred-path stubs. Do not
pad the list to look bigger. [CITED: CONVENTIONS.md; CONCERNS.md]

## Fix-List Artifact Design (answers Question 2)

### Recommended location
`.planning/codebase/FIX-LIST.md` — lives beside the map files it derives from
(`CONCERNS.md`, `CONVENTIONS.md`, `STRUCTURE.md`), so any later-phase planner reading the
codebase map finds the fix-list in the same directory. `commit_docs: true` in config, so it is
committed automatically by the GSD flow. (Rationale: the existing analysis artifacts already
live in `.planning/codebase/`; co-location keeps the harvest discoverable. An alternative —
under the phase dir `.planning/phases/01-…/` — would bury a cross-cutting artifact inside one
phase's folder, hurting discoverability for phases 2–9.) [CITED: STRUCTURE.md; config.json]

### Recommended schema (columns)
A single Markdown table keyed by a stable ID so later phases can cite items unambiguously:

| Column | Purpose |
|--------|---------|
| `ID` | Stable `FL-NN` identifier (survives reorder; later phases cite "fixes FL-03"). |
| `Category` | `naming` / `visibility` / `seam` / `exception` / `annotation` / `test-hygiene`. |
| `Description` | One-line objective statement of the issue. |
| `File(s):line` | Exact path(s) and line(s) — verified, not approximate. |
| `Golden-path?` | `yes` / `no` — drives the byte-exact re-run requirement when fixed. |
| `Eligible-in-phase` | Pre-tagged v1.1 phase whose touched paths make this item eligible (or `deferred → vX.Y`). |
| `Status` | `open` / `done (phase N)` / `deferred`. Updated as later phases consume items. |
| `Origin` | Provenance: `CONCERNS.md` / `#7/#37` / `#10` / `CONVENTIONS.md`. |

The pre-tagged `Eligible-in-phase` column is the key consumer contract: it lets a later phase's
planner filter `FIX-LIST.md` to "items eligible along my paths" without re-deriving the mapping.

## Opportunistic-Cleanup Standard Design (answers Question 3)

### Where to write it
Write the standard as a short, named section in the milestone's authoritative decision record —
add a **Key Decision row in `PROJECT.md`** ("v1.1 opportunistic-cleanup standard") pointing at a
canonical statement, and keep the full checklist text in the Phase 1 deliverable
(`.planning/codebase/FIX-LIST.md` header, or a sibling `CLEANUP-STANDARD.md`). It MUST be
discoverable by every later-phase executor — PROJECT.md is read at every phase plan. The ROADMAP
already frames it as cross-cutting and milestone-close-verified, so the standard formalizes that.

### The standard (4-gate executor checklist — what a later executor checks BEFORE applying a cleanup)
1. **Path gate** — Is the file already being modified by this phase's planned work for its own
   requirement? If NOT, do not touch it (no big-bang, no drive-by edits to untouched files).
2. **Eligibility gate** — Is there an `open` `FIX-LIST.md` item whose `File(s)` falls on a path
   this phase is already touching? Only those items are eligible. (Category C deferred items are
   never eligible in v1.1.)
3. **Golden-path gate** — If the item is `Golden-path? yes`, the cleanup MUST be
   behavior-preserving and the golden master MUST re-run **byte-exact** (134 trades /
   `final_equity 46189.87730727451`) after the change, with `mypy --strict` clean and the suite
   warning-clean under `filterwarnings=["error"]`. If `Golden-path? no`, still run the full suite
   green; no oracle interaction expected. **No re-baseline is permitted** — a result change is an
   owner-gated finding, not a silent fold-in.
4. **Bookkeeping gate** — Flip the item's `Status` to `done (phase N)` in `FIX-LIST.md` in the
   same change. Leave a `# FL-NN` reference comment at the fix site, matching the existing
   decision-tag comment convention (`# D-04`, `# FL-03`). [CITED: CONVENTIONS.md L107,L114]

### Milestone-close audit (what `/gsd:complete-milestone` verifies for CLAR-02)
- Every `FIX-LIST.md` item is either `done (phase N)` with a path that phase N legitimately
  touched, or `deferred` with an owning milestone — none silently dropped.
- No commit in v1.1 shows a "big-bang refactor" (a cleanup-only diff touching files outside any
  phase's requirement-driven work).
- The golden master is byte-exact against the v1.0 final oracle at milestone close (no
  re-baseline occurred). [CITED: PROJECT.md L185; ROADMAP L52]
- Indentation discipline held (no tab/space normalization diffs in touched files).

## Architecture Patterns

### Process flow (Phase 1 has no system architecture — it is a documentation pipeline)

```
EXISTING MAP (current, 2026-06-08)                 ARCHIVED (reference only)
  .planning/codebase/CONCERNS.md  ─┐                 v1.0-ARCHITECTURE-REVIEW.md (DO NOT harvest)
  .../CONVENTIONS.md              ─┤                 v1.0-COVERAGE-INDEX.md ──┐ (pull #7/#37, #10 only)
  .../STRUCTURE.md                ─┤                                          │
  .../ARCHITECTURE/STACK/TESTING  ─┤                                          │
                                   ▼                                          ▼
                         [ HARVEST + DEDUPE + CATEGORIZE + verify line refs ]
                                   │
                                   ▼
              .planning/codebase/FIX-LIST.md  (committed; FL-NN schema, eligible-in-phase tags)
                                   │
                                   ▼
              CLEANUP STANDARD (PROJECT.md Key Decision + checklist text)
                                   │
                  consumed by ─────┼──────────────────────────────────────────►  Phases 2–9
                                   ▼                                              (apply along touched paths)
                          /gsd:complete-milestone  ──►  CLAR-02 audit (verified at milestone close)
```

### Recommended deliverable structure
```
.planning/codebase/
├── CONCERNS.md          # existing (input — unchanged)
├── CONVENTIONS.md       # existing (input — unchanged)
├── STRUCTURE.md         # existing (input — unchanged)
└── FIX-LIST.md          # NEW (Phase 1 deliverable: harvested fix-list + cleanup standard)
```

### Anti-Patterns to Avoid
- **Regenerating the map.** The map is current (post-`017bf72`). A fresh `gsd-map-codebase`
  run is explicitly out of scope and wastes effort. [CITED: ROADMAP L43]
- **Harvesting from the architecture review.** Most of its 40 findings are already fixed; it is
  a pre-v1.0 snapshot. Reference only. [CITED: ROADMAP L44]
- **Editing source in Phase 1.** Any `itrader/` edit risks touching the golden path and is
  outside this phase's mandate (success criterion 3).
- **Padding the fix-list.** Report the small naming surface honestly; do not invent issues to
  fill categories.
- **Burying the standard.** If the cleanup standard is not discoverable in PROJECT.md / the map
  dir, later executors won't apply it and CLAR-02 fails silently at milestone close.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Codebase analysis | A new mapping pass / third-party graphify tool | The EXISTING `.planning/codebase/` map | Already current as of 2026-06-08; ROADMAP forbids third-party graphify (L280-282) |
| Fix-item provenance | Re-deriving issues from source | Harvest from CONCERNS.md + the two named residuals | "Authoritative analysis already exists" (PROJECT.md L110); don't re-derive |
| Cleanup enforcement | A bespoke linter/CI gate | The 4-gate executor checklist + milestone-close audit | No autoformatter/linter is configured (CONVENTIONS.md L41-43); the gate is a human/agent checklist riding the existing golden-master + mypy gates |

**Key insight:** This phase's value is *organizing existing knowledge into a consumable,
enforceable contract*, not generating new analysis. The hard engineering is the schema and the
gates, not the discovery.

## Runtime State Inventory

> Phase 1 touches no source, no runtime state, no stored data. This section is included because
> the milestone is a brownfield refactor, but Phase 1 specifically performs no rename/migration.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 1 writes only `.planning/codebase/FIX-LIST.md` | None |
| Live service config | None — no services touched | None |
| OS-registered state | None | None |
| Secrets/env vars | None touched | None |
| Build artifacts | None — no package rebuild; no source change | None |

**Nothing found in every category — verified:** Phase 1 is documentation-only; the only file
written is a new Markdown artifact under `.planning/`. The `itrader/` package and `tests/golden/`
are untouched, so no installed package, oracle, or runtime registration is affected.

## Common Pitfalls

### Pitfall 1: Accidentally touching the golden path
**What goes wrong:** An executor "tidies" a source file while producing the fix-list (e.g.
fixes a bare `ValueError` because it's right there).
**Why it happens:** The residual items name exact source lines; the temptation to fix-in-place
is high.
**How to avoid:** Phase 1 deliverables are Markdown only. The fix-list *records* `portfolio.py`
lines; it does not edit them. The cleanup happens in Phase 8 (the phase that touches
`portfolio.py`'s admission gates), under the byte-exact gate.
**Warning signs:** Any diff under `itrader/` or `tests/` in a Phase 1 commit.

### Pitfall 2: Treating #10 as a Phase-1 fix
**What goes wrong:** Retyping `portfolio_id: int` in event dataclasses during Phase 1.
**Why it happens:** It's annotation-only and looks trivial.
**How to avoid:** Pre-tag #10 `eligible-in-Phase-5` (the HARD-03 retype is the natural home).
ROADMAP explicitly permits this. Phase 1 records, does not fix.
**Warning signs:** Edits to `events/{signal,order,fill}.py`.

### Pitfall 3: Harvesting deferred-path concerns as actionable v1.1 work
**What goes wrong:** Planning fixes for live/SQL/provider concerns that no v1.1 phase touches.
**Why it happens:** CONCERNS.md lists them prominently (it's a full audit).
**How to avoid:** Use the Category C "record-but-defer" treatment with an owning milestone tag;
the eligibility gate keeps them untouched.
**Warning signs:** A v1.1 plan referencing `postgresql_storage.py`, `sql_store.py`, or
`my_strategies/`.

### Pitfall 4: Making the standard aspirational instead of verifiable
**What goes wrong:** A vague "clean up opportunistically" sentence that can't be audited.
**Why it happens:** Standards drift to platitudes.
**How to avoid:** The 4-gate checklist + the milestone-close audit list are both concrete and
checkable against commit diffs and the golden gate.
**Warning signs:** No measurable acceptance criterion in the standard text.

## Code Examples

Not applicable — no code is written in Phase 1. The only "example" is the recommended
`FIX-LIST.md` table schema (see "Fix-List Artifact Design") and the in-source reference-comment
convention (`# FL-NN`) that *later* phases use, matching the existing decision-tag style
(`# D-04`, `# RESEARCH Pitfall 5`) documented in CONVENTIONS.md L107,L114.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pre-v1.0 40-finding architecture review as the issue ledger | Post-refactor `CONCERNS.md` (only still-present concerns) + `REQUIREMENTS.md` | v1.0 close 2026-06-08 | Most review findings fixed; fix-list harvests from the *current* concerns, not the stale review |
| Per-milestone `COVERAGE-INDEX §E` delta log | `REQUIREMENTS.md` traceability table | v1.1 start 2026-06-09 | COVERAGE-INDEX archived; only #7/#37 + #10 residuals are pulled forward |

**Deprecated/outdated:**
- `milestones/v1.0-ARCHITECTURE-REVIEW.md` — historical reference only; not a v1.1 fix source.
- `milestones/v1.0-COVERAGE-INDEX.md` — archived; harvest only the two named residuals.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `.planning/codebase/FIX-LIST.md` is the best location (vs. phase dir or PROJECT.md) | Fix-List Artifact Design | Low — discoverability preference; planner may relocate. Co-location with the map is the documented rationale. |
| A2 | #7/#37 (`portfolio.py` ValueError) is best fixed in Phase 8 (which touches admission gates) | Harvest Inventory Cat. A | Low — eligibility is a pre-tag, re-tunable; if no Phase 8 plan touches those lines it simply stays `open` and is fixed whenever a phase does. Off golden path, so non-blocking. |
| A3 | The naming/visibility violation surface is genuinely small post-refactor (no padding warranted) | Harvest Inventory | Low — based on CONVENTIONS.md recording conventions with no violations beyond carry-forwards; a deeper grep during planning could surface more, which the schema accommodates. |
| A4 | Writing the standard into PROJECT.md Key Decisions makes it discoverable to every later phase | Cleanup Standard Design | Low — PROJECT.md is read at every phase plan; if the team prefers a dedicated file, the reference row still points there. |

## Open Questions (RESOLVED)

> Both questions were resolved during planning (Phase 1 plans 01-01 / 01-02):
> - **Q1 RESOLVED:** the cleanup standard is a **separate `CLEANUP-STANDARD.md`** (Plan 01-02), with a PROJECT.md Key Decisions pointer row — chosen over embedding so the two plans keep clean, non-overlapping file ownership and run in parallel.
> - **Q2 RESOLVED:** #10 is **pre-tagged `eligible-in-Phase-5`, status `open`** in FIX-LIST.md (Plan 01-01).

1. **Stand-alone file vs. embedded standard.**
   - What we know: `commit_docs: true`; map artifacts live in `.planning/codebase/`.
   - What's unclear: Whether the cleanup standard should be a separate `CLEANUP-STANDARD.md` or
     a header section inside `FIX-LIST.md` plus a PROJECT.md pointer.
   - Recommendation: Embed the checklist in `FIX-LIST.md` and add a one-line PROJECT.md Key
     Decision row pointing to it — single source, maximally discoverable. Planner's call.

2. **#10 destination.**
   - What we know: ROADMAP explicitly allows #10 to land in Phase 5 (HARD-03 retype) instead of
     a stand-alone fix.
   - What's unclear: Whether the user wants it pre-committed to Phase 5 or left flexible.
   - Recommendation: Pre-tag `eligible-in-Phase-5`, status `open`; Phase 5 planning consumes it.

## Environment Availability

> Skipped — Phase 1 has no external dependencies (documentation-only; produces a Markdown
> artifact under `.planning/`). No tools, services, runtimes, or CLIs are required beyond the
> editor. (Step 2.6: SKIPPED — no external dependencies identified.)

## Validation Architecture

> `nyquist_validation: true` in config, but Phase 1 produces **no testable code** — it writes
> planning Markdown and touches no source. There is no behavior to sample. The relevant
> "validation" for this phase is **documentation correctness**, verified at plan/verify time and
> at milestone close (CLAR-02 audit), not via the pytest harness.

### Test Framework (context only — not exercised by Phase 1)
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) [CITED: pyproject.toml / CLAUDE.md] |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/integration/test_backtest_oracle.py -x` |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLAR-01 | Fix-list artifact exists, is committed, and contains the required items (#7/#37, #10) | doc-presence / manual review | n/a (artifact existence check) | n/a — documentation deliverable |
| CLAR-02 | Cleanup standard is written and enforceable; VERIFIED at milestone close | manual audit (`/gsd:complete-milestone`) | n/a | n/a — verified later, not in Phase 1 |

### Sampling Rate
- **Per task commit:** n/a (no code). The phase's own "test" is that `itrader/` and
  `tests/golden/` are untouched — verifiable by `git diff --stat` showing only `.planning/`.
- **Phase gate:** Fix-list present + standard written; golden master byte-exact only matters
  once *later* phases apply cleanups.

### Wave 0 Gaps
- None — no test infrastructure is created or needed for a documentation-only phase. (Optional
  guard the planner may add: a verification step asserting `git diff` for the Phase 1 commit
  touches only `.planning/`, never `itrader/` or `tests/`.)

## Security Domain

> `security_enforcement` not set in config; the phase performs no code/data/network operations.
> Phase 1 writes a single Markdown file under `.planning/` and introduces no attack surface
> (no input handling, no auth, no crypto, no SQL). The SQL-injection concern in
> `price_handler/store/sql_store.py` is RECORDED in the fix-list as a Category C deferred item
> (owning milestone v1.3 / D-sql) — it is not fixed or touched in Phase 1.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | no | Phase 1 handles no input; the sql_store injection item is recorded-deferred, not fixed here |
| V6 Cryptography | no | No crypto in scope |

## Sources

### Primary (HIGH confidence)
- `.planning/ROADMAP.md` (Phase 1 detail L40-53; cross-cutting notes L26, L280-282) — scope authority.
- `.planning/REQUIREMENTS.md` (CLAR-01, CLAR-02; L92-94) — requirement text.
- `.planning/PROJECT.md` (golden oracle L185; constraints L130-141; Key Decisions) — locked decisions.
- `.planning/STATE.md` (load-bearing constraints L48-51; Deferred Items table) — current state.
- `.planning/codebase/CONCERNS.md` (2026-06-08) — fix-item harvest source.
- `.planning/codebase/CONVENTIONS.md`, `STRUCTURE.md` (2026-06-08) — naming/visibility/seam context.
- `.planning/milestones/v1.0-COVERAGE-INDEX.md` (L86-87) — #7/#37, #10 residual provenance.
- `tests/golden/{FINAL-ORACLE.md, summary.json}` — confirmed 134 trades / `46189.87730727451`.
- Source greps [VERIFIED] — `portfolio.py` 7 ValueError sites; `events/*.py` 3 `portfolio_id: int`
  sites; `strategy_handler/base.py` `order_type: str = "market"`.

### Secondary (MEDIUM confidence)
- None — all findings are from primary in-repo planning docs and direct source verification.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Scope (no code, harvest-not-regenerate): **HIGH** — explicit in ROADMAP L43-45, L52.
- Fix-item inventory: **HIGH** — residuals verified by grep against current source; CONCERNS.md
  is current (post-`017bf72`).
- Artifact format/location: **MEDIUM** — a reasoned recommendation in Claude's-discretion space;
  planner may adjust schema/path.
- Cleanup standard design: **MEDIUM-HIGH** — gates derive directly from the locked golden-master
  and path-eligibility constraints; exact wording is discretionary.

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable — planning artifacts; the only invalidation risk is a new
`itrader/` commit changing the carry-forward line numbers, which a planning-time re-grep catches).
