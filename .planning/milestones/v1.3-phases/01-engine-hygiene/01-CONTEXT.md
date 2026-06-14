# Phase 1: Engine Hygiene - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

SAFE, **byte-exact** cleanup slice (HYG-01). Close the hygiene debt — private-internals
test asserts, stale config/typing residue, and three v1.2 Phase-6 review leftovers —
**without changing run-path behavior or the golden numbers** (134 trades /
`final_equity 46189.87730727451`; e2e 58/58; full suite green; `mypy --strict` clean).

Editing run-path *files* is allowed where the edit is provably inert (dead imports/constants,
doc comments, value-identical refactors); changing run-path *behavior* is not.

**Enumerated work items (the whole scope):**
1. `tests/unit/portfolio/test_position_manager.py` — rewrite `pm._storage` private asserts to public query APIs only (W3-07, owed from v1.2 NAME-04).
2. Remove the stale `screener_event_handler.py` mypy override from `pyproject.toml`.
3. Delete the dead `TOLERANCE = 1e-3` float constant from `portfolio_handler/portfolio.py`.
4. Retype `PortfolioValidator.validate_transaction_data` off `float` (`portfolio_handler/validators.py`).
5. Drop the dead `StrategyId` import (`order_handler/order_manager.py:20`).
6. Consolidate the duplicated `_ONE = Decimal("1")` (`brackets/levels.py` + `sizing_resolver.py`, + the third copy in `core/sizing.py`).
7. Soften the misleading `TYPE_CHECKING` guard doc in `reconcile/reconcile_manager.py`.

</domain>

<decisions>
## Implementation Decisions

### `_ONE` duplication (item 6)
- **D-01:** Consolidate, do not document-and-keep. Define a **public** canonical
  `ONE = Decimal("1")` in `core/money.py` (the money-primitives module; depends on
  nothing inside `itrader`, no circular-import risk vs `core/sizing.py` — verified
  neither imports the other).
- **D-02:** Name it `ONE` (no leading underscore). The `_`-prefix convention marks a
  *module-private* constant; once shared across modules that no longer applies.
- **D-03:** Eliminate **all three** copies, not just the two named ones. Import the
  canonical `ONE` in `core/sizing.py:59`, `order_handler/sizing_resolver.py:43`, and
  `order_handler/brackets/levels.py:23`. Going 3→2 would leave the duplication half-done.
- **D-04:** Byte-exact rationale: `Decimal("1")` is value-identical regardless of
  definition site, so consolidation cannot move the golden master.
- **D-05:** Leave `_ZERO` (`core/sizing.py:72`) untouched — not named, no second copy to
  dedupe, keeps the diff tight. (See deferred.)

### Validator retype (item 4)
- **D-06:** Retype `validate_transaction_data` parameters `price` / `quantity` /
  `commission` to **strict `Decimal`** (not `Decimal | int`, not a `to_money`-coercible
  boundary). Cleanest honoring of the Decimal-money policy and the "no longer accepts
  `float`" success criterion. Validators validate — coercion stays out of scope.
  - Planner note: confirm callers on this path already pass `Decimal`; if a caller
    passes `int`/`float`, that's a real defect to surface, not a reason to widen the type.

### Cleanup discipline (whole phase)
- **D-07:** **Strict scope** — touch ONLY the enumerated items above (including the agreed
  3rd `_ONE` copy). No opportunistic adjacent cleanup. Keeps the golden gate unambiguous
  and the byte-exact guarantee clean. Anything else noticed during execution → deferred
  idea, not a fix in this phase.

### Claude's Discretion
- Exact public query APIs to assert through when rewriting `test_position_manager.py`
  (item 1) — pick the existing public `PositionManager` query surface; implementation
  detail for the planner/researcher.
- Precise wording of the softened `TYPE_CHECKING` doc comment (item 7).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source / requirements
- `.planning/REQUIREMENTS.md` — HYG-01 (the authoritative item list, lines ~93–103).
- `.planning/ROADMAP.md` §"Phase 1: Engine Hygiene" — goal + 4 success criteria.

### Triage / review provenance (the three v1.2 Phase-6 residues)
- `.planning/notes/v1.3-concerns-triage.md` §B items 1–4 — origin of items 5–7.
- `.planning/milestones/v1.2-phases/06-order-manager-decomposition/06-REVIEW.md` — WR-01 / IN-01 / IN-02 (the dead `StrategyId` import, `_ONE` duplication, `TYPE_CHECKING` doc).

### Conventions (must respect)
- `.planning/codebase/CONVENTIONS.md` — module-private-constant convention, tab/space indentation hazard, money policy.
- `CLAUDE.md` "Money Policy" — Decimal end-to-end; `to_money` is the only Decimal entry point; informs the validator retype.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/money.py` — money-primitives home (`to_money`, `quantize`); natural site for the new public `ONE` constant.
- `PositionManager` public query API — the assertion surface for the `test_position_manager.py` rewrite (replaces `pm._storage` access).

### Established Patterns
- Module-private constants use a leading underscore (`_ONE`, `_ZERO`, `_DEFAULT_SCALES`) — so a *shared* constant must be public (`ONE`), not `_ONE`.
- **Indentation hazard:** handler/manager modules under `order_handler/` use **tabs**; `core/money.py` and `core/sizing.py` use **4 spaces**. Match each file exactly — a mixed-indentation diff breaks a tab file. (`sizing_resolver.py` / `brackets/levels.py` = tabs; `core/*` = spaces.)

### Integration Points
- `core/money.py` is imported broadly; adding `ONE` is additive/inert. `core/sizing.py` and the two `order_handler` files will gain an import of `ONE`.

</code_context>

<specifics>
## Specific Ideas

- Canonical constant lives in `core/money.py` specifically (not `core/sizing.py`) — money.py is the semantically correct home and has no `itrader`-internal dependencies.

</specifics>

<deferred>
## Deferred Ideas

- **`_ZERO` consolidation** (`core/sizing.py:72`) — currently a single copy, no duplication to fix. If a `ZERO` money primitive becomes useful across modules later, mirror the `ONE` treatment. Not in this phase (D-05/D-07).
- **Opportunistic mypy-override / residue sweep** — any other stale overrides or sibling residue spotted during execution are captured here rather than fixed, per the strict-scope decision (D-07).

</deferred>

---

*Phase: 1-Engine Hygiene*
*Context gathered: 2026-06-12*
