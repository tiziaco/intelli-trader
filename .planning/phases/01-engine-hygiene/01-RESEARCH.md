# Phase 1: Engine Hygiene - Research

**Researched:** 2026-06-12
**Domain:** Codebase hygiene / byte-exact cleanup (no external libraries; pure in-repo investigation)
**Confidence:** HIGH (every claim verified against the working tree via grep/sed/git/pytest/mypy this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**`_ONE` duplication (item 6)**
- **D-01:** Consolidate, do not document-and-keep. Define a **public** canonical `ONE = Decimal("1")` in `core/money.py` (the money-primitives module; depends on nothing inside `itrader`, no circular-import risk vs `core/sizing.py` — verified neither imports the other).
- **D-02:** Name it `ONE` (no leading underscore). The `_`-prefix convention marks a *module-private* constant; once shared across modules that no longer applies.
- **D-03:** Eliminate **all three** copies, not just the two named ones. Import the canonical `ONE` in `core/sizing.py:59`, `order_handler/sizing_resolver.py:43`, and `order_handler/brackets/levels.py:23`. Going 3→2 would leave the duplication half-done.
- **D-04:** Byte-exact rationale: `Decimal("1")` is value-identical regardless of definition site, so consolidation cannot move the golden master.
- **D-05:** Leave `_ZERO` (`core/sizing.py:72` — actually defined at line 58) untouched — not named, no second copy to dedupe, keeps the diff tight.

**Validator retype (item 4)**
- **D-06:** Retype `validate_transaction_data` parameters `price` / `quantity` / `commission` to **strict `Decimal`** (not `Decimal | int`, not a `to_money`-coercible boundary). Cleanest honoring of the Decimal-money policy and the "no longer accepts `float`" success criterion. Validators validate — coercion stays out of scope.
  - Planner note: confirm callers on this path already pass `Decimal`; if a caller passes `int`/`float`, that's a real defect to surface, not a reason to widen the type.

**Cleanup discipline (whole phase)**
- **D-07:** **Strict scope** — touch ONLY the enumerated items (including the agreed 3rd `_ONE` copy). No opportunistic adjacent cleanup. Anything else noticed during execution → deferred idea, not a fix in this phase.

### Claude's Discretion
- Exact public query APIs to assert through when rewriting `test_position_manager.py` (item 1) — pick the existing public `PositionManager` query surface.
- Precise wording of the softened `TYPE_CHECKING` doc comment (item 7).

### Deferred Ideas (OUT OF SCOPE)
- **`_ZERO` consolidation** (`core/sizing.py`) — single copy, no duplication to fix. Mirror the `ONE` treatment only if a `ZERO` money primitive becomes useful across modules later. Not in this phase (D-05/D-07).
- **Opportunistic mypy-override / residue sweep** — any other stale overrides or sibling residue spotted during execution are captured as deferred ideas, not fixed (D-07).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HYG-01 | Engine-hygiene slice (SAFE, byte-exact): private-storage test asserts → public query APIs; remove stale `screener_event_handler` mypy override; delete dead `TOLERANCE = 1e-3`; retype `validate_transaction_data` off `float`; + three v1.2 Phase-6 residues (dead `StrategyId` import, duplicated `_ONE`, misleading `TYPE_CHECKING` doc). | Every one of the 7 items investigated below with file/line evidence, an exact public-API replacement map, caller-trace results, indentation per file, circular-import clearance, and the byte-exact verification command set. |
</phase_requirements>

## Summary

This is a **pure codebase-hygiene phase** — there is no technology to research, no library to choose, no external documentation to consult. "Research" here means *verifying the seven enumerated work items against the actual working tree* so the planner can write tasks with zero ambiguity and the executor cannot accidentally move the golden master.

I verified all seven items this session. Two findings materially change the plan from what CONTEXT.md anticipated:

1. **Item 5 (dead `StrategyId` import) is ALREADY RESOLVED.** `git` shows it was removed in commit `2ffbeb8` (the v1.2 Phase-6 decomposition PR itself — the same change that surfaced the review finding). `grep` confirms zero `StrategyId` references remain in `order_manager.py`. This is a **verify-and-skip** item, not an edit.
2. **Item 4 (`validate_transaction_data`) has ZERO callers.** A repo-wide grep across `itrader/` and `tests/` finds the method is defined but never called. The D-06 planner note ("confirm callers pass `Decimal`") resolves to *there are no callers* — so the retype is provably inert on the run path, and there is no caller-defect to surface. **Caveat (critical):** the current body uses `isinstance(price, (int, float))` guards that would *reject* a `Decimal`; the retype is not just an annotation change — the `isinstance` checks must change to `Decimal` too, or a future Decimal caller would be wrongly rejected.

The other five items are confirmed safe and mechanical. The whole phase is byte-exact by construction: every edit is a dead-import/dead-constant removal, a doc-comment softening, an annotation-only change to dead code, an import-consolidation of a value-identical constant, or a test-only rewrite — none touch run-path *behavior*.

**Primary recommendation:** Plan one small plan (or two tight plans split test-only vs source) covering all seven items, with a single byte-exact verification gate at the end: `make typecheck` (mypy --strict clean), `make test-integration` (the 134-trade / final_equity oracle), `poetry run pytest tests/e2e` (58/58), `make test` (full suite green). Mark item 5 as verify-only.

## Architectural Responsibility Map

This phase changes no architecture. Each item is local to one tier; included for the planner's tier sanity-check.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Test asserts via public API (item 1) | Test suite | — | `tests/unit/portfolio/` — no production code touched |
| Stale mypy override removal (item 2) | Build/config (`pyproject.toml`) | — | Tooling config, not runtime |
| Dead constant deletion (item 3) | Portfolio handler (`portfolio.py`) | — | Module-level dead constant, no consumers |
| Validator retype (item 4) | Portfolio handler (`validators.py`) | — | Dead method; annotation + isinstance only |
| Dead import (item 5) | Order handler (`order_manager.py`) | — | Already removed — verify only |
| `ONE` constant consolidation (item 6) | Core (`core/money.py`) | Order handler + core/sizing | money.py is leaf (depends on nothing in `itrader`) |
| Doc-comment softening (item 7) | Order handler (`reconcile/`) | — | Docstring only, no code |

## Standard Stack

**Not applicable.** This phase installs nothing and imports no new third-party packages. The only "stack" touched is the stdlib `decimal.Decimal` (already pervasive) and the project's own `core/money.py`. **No `## Package Legitimacy Audit` is required** — zero external packages installed.

Existing tooling used for verification (already in `pyproject.toml`, all `[VERIFIED: working tree]`):
- `mypy ^2.1.0` — `make typecheck` → `poetry run mypy itrader` (currently clean: "Success: no issues found in 172 source files").
- `pytest ^8.4.2` — `make test` / `make test-integration` / `poetry run pytest tests/e2e`.

## Per-Item Findings (the core of this research)

### Item 1 — Rewrite `pm._storage` private asserts to public query APIs

**File:** `tests/unit/portfolio/test_position_manager.py` (4-space indent — it's a test file; CONVENTIONS line 45: "all test files" use spaces). `[VERIFIED: working tree]`

**Current state:** 14 occurrences of `pm._storage.<method>()` across 11 assert lines (the test currently passes: `19 passed`). The private surface used is exactly two storage methods: `get_positions()` (returns the open-positions dict) and `get_closed_positions()` (returns the closed-positions list). `[VERIFIED: grep + pytest run]`

**Exact line-by-line replacement map** (private → public). The `PositionManager` public query API fully covers every assertion — verified by reading `position_manager.py:253-270`:

| Line(s) | Current private assert | Public-API replacement | Public method (signature) |
|---------|------------------------|------------------------|---------------------------|
| 62 | `len(pm._storage.get_positions()) == 0` | `len(pm.get_all_positions()) == 0` *or* `pm.get_position_count() == 0` | `get_all_positions() -> Dict[str, Position]` / `get_position_count() -> int` |
| 63 | `len(pm._storage.get_closed_positions()) == 0` | `len(pm.get_closed_positions()) == 0` | `get_closed_positions(limit=None) -> List[Position]` |
| 79 | `len(pm._storage.get_positions()) == 1` | `len(pm.get_all_positions()) == 1` | `get_all_positions()` |
| 80 | `"BTCUSDT" in pm._storage.get_positions()` | `"BTCUSDT" in pm.get_all_positions()` | `get_all_positions()` returns a `Dict[str, Position]` keyed by ticker — `in` works |
| 118 | `len(pm._storage.get_positions()) == 1` | `len(pm.get_all_positions()) == 1` | `get_all_positions()` |
| 135 | `len(pm._storage.get_positions()) == 0` | `len(pm.get_all_positions()) == 0` | `get_all_positions()` |
| 136 | `len(pm._storage.get_closed_positions()) == 1` | `len(pm.get_closed_positions()) == 1` | `get_closed_positions()` |
| 148 | `len(pm._storage.get_positions()) == 1` | `len(pm.get_all_positions()) == 1` | `get_all_positions()` |
| 149 | `len(pm._storage.get_closed_positions()) == 0` | `len(pm.get_closed_positions()) == 0` | `get_closed_positions()` |
| 354 | `len(pm._storage.get_positions()) == 3` | `len(pm.get_all_positions()) == 3` | `get_all_positions()` |
| 361 | `len(pm._storage.get_positions()) == 0` | `len(pm.get_all_positions()) == 0` | `get_all_positions()` |
| 362 | `len(pm._storage.get_closed_positions()) == 3` | `len(pm.get_closed_positions()) == 3` | `get_closed_positions()` |
| 393 | `len(pm._storage.get_positions()) == 10` | `len(pm.get_all_positions()) == 10` | `get_all_positions()` |
| 426 | `len(pm._storage.get_positions()) == 1` | `len(pm.get_all_positions()) == 1` | `get_all_positions()` |

**Recommendation:** use `get_all_positions()` uniformly for the open-positions dict (preserves both the `len(...)` and the `"BTCUSDT" in ...` membership assert on line 80 — `get_position_count()` would NOT support line 80's membership test, so a single uniform substitution is cleaner than mixing). Use `get_closed_positions()` for the closed-list asserts. **The public API is a complete superset of what the test needs — no test logic changes, no new assertions, identical semantics.** `[VERIFIED: source read of position_manager.py + working tree]`

**Byte-exact note:** test-only change; cannot touch the golden master. Confidence: **HIGH**.

### Item 2 — Remove stale `screener_event_handler` mypy override

**File:** `pyproject.toml`, the first `[[tool.mypy.overrides]]` block (lines 86-100). `[VERIFIED: working tree]`

The dead entry is:
```toml
    "itrader.events_handler.screener_event_handler",     # D-screener — dead, superseded by full_event_handler;
                                                         #   references self.universe never set in __init__ (latent
                                                         #   AttributeError). Not imported anywhere. Wiring is D-screener.
```
(the module string on line 96 plus its trailing comment continuation on lines 97-98).

**Evidence the module is genuinely stale/absent:**
- `find itrader -name "screener_event_handler*"` → **no results**. The module does not exist. `[VERIFIED]`
- **Do NOT remove the adjacent line 95** `"itrader.screeners_handler.*"` — that wildcard still matches live modules under `itrader/screeners_handler/` and is a different, still-needed override. Only the `events_handler.screener_event_handler` entry is dead. `[VERIFIED: directory listing]`
- mypy does NOT error on the stale override today (`make typecheck` → "Success: no issues found in 172 source files"). Removing it is pure cleanliness, not a fix for a current failure. `[VERIFIED: ran mypy this session]`

**Byte-exact note:** config-only, no runtime effect. Confidence: **HIGH**.

### Item 3 — Delete dead `TOLERANCE = 1e-3`

**File:** `itrader/portfolio_handler/portfolio.py:26`. `[VERIFIED: grep -n]`

**Evidence it is dead:** a repo-wide `grep -rn "TOLERANCE" itrader/ tests/` returns **exactly one hit** — the definition line itself. No reader anywhere. `[VERIFIED]`

Note the project context: `1e-3` is a float constant, and the WR-01/WR-02 comments in `position_manager.py` already show the engine migrated quantity-closure tolerances to `Decimal` literals (`self.tolerance = Decimal('0.00001')`), leaving this top-level `TOLERANCE` orphaned. Deleting the line is provably inert.

**Indentation:** `portfolio.py` is a portfolio-handler module → **tabs** (CONVENTIONS line 44). The constant is at column 0, so the deletion removes a whole line — no indentation hazard for this edit, but match tabs if any surrounding edit is needed.

**Byte-exact note:** dead constant, zero consumers. Confidence: **HIGH**.

### Item 4 — Retype `PortfolioValidator.validate_transaction_data` off `float`

**File:** `itrader/portfolio_handler/validators.py:19-53`. **Indentation: 4 SPACES** (verified — body lines under the methods are space-indented, NOT tabs, despite being under `portfolio_handler/`; this file predates the tab convention for that package). `[VERIFIED: sed inspection]`

**Caller trace (the D-06 planner note):** `grep -rn "validate_transaction_data" itrader/ tests/` → **the definition site is the ONLY hit.** The method has **zero callers** anywhere in the codebase or test suite. `[VERIFIED]`

Consequences for the planner:
- The D-06 note "confirm callers already pass `Decimal`; if a caller passes `int`/`float` that's a real defect to surface" **resolves to: there are no callers, so there is no caller-defect to surface and nothing to surface as a bug.**
- The retype is **provably inert on the run path** — dead code, byte-exact guaranteed.

**Current signature (lines 20-26):**
```python
def validate_transaction_data(
    ticker: str,
    price: float,
    quantity: float,
    commission: float,
    transaction_type: str
) -> None:
```

**CRITICAL — the body, not just the signature, must change.** The current body guards with `isinstance(price, (int, float))` (lines 36, 39, 42). A bare annotation change to `price: Decimal` while leaving `isinstance(price, (int, float))` would mean a real `Decimal` argument *fails* the guard (`Decimal` is not an `int`/`float`) and raises `InvalidTransactionError` — a latent behavior trap if the method is ever wired up. The strict-`Decimal` retype per D-06 should be:

```python
from decimal import Decimal
...
def validate_transaction_data(
    ticker: str,
    price: Decimal,
    quantity: Decimal,
    commission: Decimal,
    transaction_type: str
) -> None:
    ...
    if not isinstance(price, Decimal) or price <= 0:   # was (int, float)
    ...
    if not isinstance(quantity, Decimal) or quantity <= 0:
    ...
    if not isinstance(commission, Decimal) or commission < 0:
```

The numeric-limit checks (`price > 1_000_000`, `quantity > 1_000_000`) compare `Decimal > int`, which is valid Python — no change needed there. `Decimal` is already imported in the module as `decimal.Decimal` (line 5 `import decimal`); the planner can either use `decimal.Decimal` to match the file's existing style or add `from decimal import Decimal`. **Match the file: it currently writes `decimal.Decimal('...')`** (lines 13-14), so prefer `decimal.Decimal` annotations to keep the diff stylistically consistent. `[VERIFIED: source read]`

**Scope discipline (D-07):** the sibling methods in the same file (`validate_portfolio_data`'s `cash: float`, `PositionValidator.validate_position_consistency`'s `float` params, the `to_decimal`/`from_decimal` float-boundary helpers) are **out of scope** — D-07 strict scope, item 4 names only `validate_transaction_data`. Do not retype them.

**Byte-exact note:** dead method, no callers. Confidence: **HIGH**.

### Item 5 — Drop dead `StrategyId` import (`order_manager.py:20`)

**Status: ALREADY RESOLVED — this is a verify-and-skip item, not an edit.** `[VERIFIED: grep + git]`

- `grep -n "StrategyId" itrader/order_handler/order_manager.py` → **no matches.** The import is gone.
- `git log -p -S "StrategyId" -- itrader/order_handler/order_manager.py` shows the removal landed in commit **`2ffbeb8` ("V1.2/phase 6 refactor order handler (#34)")** — the *same* v1.2 Phase-6 PR that produced the WR-01 review finding. The review noted it on line 20, but the cleanup shipped within that PR.
- `StrategyId` is still legitimately used in `order.py` (lines 9, 53, 200, 233) and `brackets/bracket_book.py` (lines 23, 43) — those are correct and **must not be touched** (the `_PendingBracket` relocation moved the consumer there, per WR-01's own fix note: "now used only in bracket_book.py").

**Planner action:** include a one-line verification task ("confirm `StrategyId` no longer imported in `order_manager.py`") and a note in the success-criteria mapping that criterion 3's "dead `StrategyId` import dropped" is satisfied by prior work. Do NOT create an edit task that will no-op or error. Confidence: **HIGH**.

### Item 6 — Consolidate the three `_ONE = Decimal("1")` copies into public `ONE` in `core/money.py`

**The three definition sites** (all `[VERIFIED: grep -n]`):

| # | File | Def line | Usages | Indentation | Import situation |
|---|------|----------|--------|-------------|------------------|
| a | `itrader/core/sizing.py` | `_ONE` at line 58 (`_ZERO` at 57) | line 72 (`_ZERO < value <= _ONE`) | **4 spaces** | Does NOT currently import `core/money.py` → needs a NEW import line `from itrader.core.money import ONE` |
| b | `itrader/order_handler/sizing_resolver.py` | line 43 | line 161 (`if exit_fraction == _ONE`) | module-level/imports: spaces; **function bodies: TABS** (line 161 starts with `\t\t`) | ALREADY imports `from itrader.core.money import to_money` (line 37) → just add `ONE` to that existing import |
| c | `itrader/order_handler/brackets/levels.py` | line 23 | lines 39-40 (`anchor * (_ONE + ...)` ×4) | **TABS** (line 39 starts `\t\t`) | imports `from ...core.sizing import SLTPPolicy` (line 22); does NOT import money → needs NEW import `from ...core.money import ONE` |

**Circular-import clearance (D-01/D-03):** `[VERIFIED]`
- `core/money.py` imports only `from decimal import Decimal, ROUND_HALF_UP` (line 25) — it imports NOTHING from `core/sizing.py` or `order_handler`. Adding `ONE` and having those three modules import it is strictly one-directional (leaf → consumers). **No cycle.**
- `core/sizing.py` does NOT currently import `core/money.py` — adding the import is safe (money is a pure leaf).

**Where to place `ONE` in `core/money.py`:** alongside the existing module-level constants near the top (after the `from decimal import ...` on line 25, before/after `_DEFAULT_SCALES` on line 27). `money.py` is 4-space indented (CONVENTIONS line 45). Suggested: `ONE = Decimal("1")` as a public module constant. There is no `__all__` in `money.py`, so no export list to update. `[VERIFIED: read money.py:25-55]`

**Docstring residue to update (do NOT miss — this is part of item 6, not a separate item):** `[VERIFIED]`
- `levels.py` lines 11-13 and 16-17 of its module docstring explicitly describe `_ONE` as "the module-private constant used ONLY by `_bracket_levels`" and "a leading-underscore module-level constant." After consolidation that narrative is false. The docstring must be softened/updated to reflect that the constant now lives in `core/money.py` and is imported. Leaving the stale docstring would re-introduce a (smaller) version of item 7's "misleading doc" problem.
- `sizing_resolver.py` line 2's docstring title "The ONE sizing resolver" is about the *resolver being singular*, NOT about the `_ONE` constant — do **not** touch it (unrelated wording).

**Indentation hazard summary for the executor:** money.py + core/sizing.py = **spaces**; sizing_resolver.py function bodies + levels.py = **TABS**. The import-statement edits all happen at column 0 (no indentation), but the executor must match each file's convention if any wrapped/continued line is involved. A mixed-indent diff in `levels.py` or `sizing_resolver.py` breaks the file (CLAUDE.md / CONVENTIONS line 46).

**Out of scope (D-05/D-07):** `_ZERO` in `core/sizing.py` (line 57) stays — single copy, no dedup target.

**Byte-exact note (D-04):** `Decimal("1")` is value-identical at every site; replacing three local definitions with one imported public constant cannot change any computed value. The golden master is untouched. Confidence: **HIGH**.

### Item 7 — Soften the misleading `TYPE_CHECKING` guard doc in `reconcile/reconcile_manager.py`

**File:** `itrader/order_handler/reconcile/reconcile_manager.py`, module docstring lines 23-26 (the `BracketManager` / `TYPE_CHECKING` claim). The relevant code: `from ..brackets import BracketBook` (runtime, line 41) and `if TYPE_CHECKING: from ..brackets import BracketManager` (lines 47-48). `[VERIFIED: read]`

**Why the current doc is misleading** (origin: v1.2 06-REVIEW finding **IN-01**, `[CITED: .planning/milestones/v1.2-phases/06-order-manager-decomposition/06-REVIEW.md:94-108]`):
> The docstring says the `BracketManager` type "is imported only under `TYPE_CHECKING`," implying the runtime import graph never loads `BracketManager`. But line 41 imports `BracketBook` from `..brackets` at runtime, which triggers `brackets/__init__.py` to import `BracketManager` anyway. The `TYPE_CHECKING` guard does NOT actually avoid loading `BracketManager` at runtime. **This is harmless** (the `brackets` package does not import `reconcile`, so there is no cycle, and the import probe is green) — but the "imported only under `TYPE_CHECKING`" phrasing misdescribes the real runtime import graph.

**Corrected wording intent (per IN-01's own fix note — planner specifies exact prose, Claude's discretion per CONTEXT):** soften the docstring to state that the runtime `BracketBook` import already pulls in the `brackets` package (so `BracketManager` is loaded at runtime regardless), and the `TYPE_CHECKING` guard exists only to keep the `BracketManager` *annotation name* off the module's runtime name bindings — NOT to avoid loading the class. No code change; docstring-only.

**Indentation:** `reconcile_manager.py` is an order-handler module → **tabs** (the docstring text itself is inside `"""..."""` so the prose lines are flush-left; only edit the prose). Confidence: **HIGH**.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Open/closed position assertions in the test (item 1) | A new test helper that reaches into storage | The existing `PositionManager` public query methods (`get_all_positions`, `get_closed_positions`, `get_position_count`) | They already exist, are typed, and are the documented read surface — that's the entire point of the W3-07 encapsulation fix |
| A `ONE` money constant (item 6) | A re-defined `Decimal("1")` per module | The new public `core.money.ONE` | `core/money.py` is the locked home for money primitives (`to_money`, `quantize`); one canonical constant is the whole D-01..D-04 decision |
| Decimal coercion inside the validator (item 4) | `to_money()` calls inside `validate_transaction_data` | Nothing — strict `Decimal` params (D-06); coercion is explicitly out of scope | "Validators validate" — coercion is the caller's job, per D-06 |

**Key insight:** every "build" in this phase is actually a "delete" or a "point at the thing that already exists."

## Common Pitfalls

### Pitfall 1: Annotation-only retype of item 4 leaving the `isinstance` guards
**What goes wrong:** changing `price: float` → `price: Decimal` but leaving `isinstance(price, (int, float))` makes the method reject real `Decimal` inputs (latent bug if ever wired).
**How to avoid:** change the three `isinstance(..., (int, float))` checks to `isinstance(..., Decimal)` as part of the same edit. **Warning sign:** a diff that touches only the signature lines and not lines 36/39/42.

### Pitfall 2: Mixed-indentation diff in a tab file (item 6, item 3, item 7)
**What goes wrong:** `levels.py` and `sizing_resolver.py` (bodies) and `portfolio.py` and `reconcile_manager.py` use **tabs**; an editor that inserts spaces produces a broken/garbled diff. `core/money.py` and `core/sizing.py` use **spaces**.
**How to avoid:** match each file's existing indentation exactly; never normalize (CLAUDE.md, CONVENTIONS line 46). The per-file indentation is tabulated in Item 6 above.

### Pitfall 3: Treating item 5 as an edit
**What goes wrong:** creating a task to "remove the `StrategyId` import from `order_manager.py:20`" — the import is already gone (commit `2ffbeb8`); an edit task will fail to find it or no-op, and an over-eager executor might wrongly strip `StrategyId` from `order.py`/`bracket_book.py` where it's still used.
**How to avoid:** make item 5 a verify-only step; protect `order.py` and `brackets/bracket_book.py`.

### Pitfall 4: Removing the wrong mypy override line (item 2)
**What goes wrong:** deleting `"itrader.screeners_handler.*"` (still live) instead of / in addition to `"itrader.events_handler.screener_event_handler"` (dead).
**How to avoid:** remove ONLY the `events_handler.screener_event_handler` entry and its two trailing comment-continuation lines; leave the `screeners_handler.*` wildcard.

### Pitfall 5: Forgetting the docstring residue in item 6
**What goes wrong:** consolidating the constant but leaving `levels.py`'s docstring (lines 11-13/16-17) claiming `_ONE` is "the module-private constant used ONLY by `_bracket_levels`" — now false, and a fresh "misleading doc."
**How to avoid:** the docstring update is PART of item 6, not optional polish.

## Runtime State Inventory

This is a code/config/test-only hygiene phase — there is no rename of a *stored* string, no datastore key change, no live-service reconfiguration. The `_ONE`→`ONE` change is a constant *value* `Decimal("1")` that is value-identical, not a stored identifier. Each category is explicitly cleared:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no DB/datastore key, collection, or user_id is touched; `Decimal("1")` is a literal value, not a stored identifier. Verified: edits are confined to `.py`/`.toml` source and one test file. | None |
| Live service config | None — no n8n/Datadog/Tailscale/etc. The only "config" file touched is `pyproject.toml` (mypy override, build-time only). | None |
| OS-registered state | None — no Task Scheduler / pm2 / launchd / systemd registration references the changed names. | None |
| Secrets/env vars | None — no SOPS key, `.env` var, or CI env var named `_ONE`/`TOLERANCE`/`StrategyId`/`screener_event_handler`. The `screener_event_handler` string lives ONLY in the `pyproject.toml` mypy override (verified by grep). | None |
| Build artifacts | None — no compiled binary, egg-info, or Docker tag carries these names. Pure-source change; `poetry`/in-project `.venv` re-resolves on next import. | None |

**Verified by:** repo-wide grep for each changed identifier (`StrategyId`, `TOLERANCE`, `_ONE`, `screener_event_handler`, `validate_transaction_data`) confined to `.py`/`.toml`; no runtime-state surface implicated.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Poetry + in-project `.venv` | All verification (`make test*`, `make typecheck`) | ✓ | per `pyproject.toml` (Python `>=3.13,<3.14`) | — |
| `pytest` | full suite, e2e, integration oracle | ✓ | `^8.4.2` | — |
| `mypy` | `make typecheck` | ✓ | `^2.1.0` (ran clean this session) | — |
| Golden dataset `data/BTCUSD_1d_ohlcv_2018_2026.csv` | integration oracle (134-trade gate) | ✓ (oracle test + `tests/golden/` committed) | — | — |

**No missing dependencies.** All verification gates run with the existing toolchain. PostgreSQL is NOT needed (backtest path uses in-memory storage; no item touches live/SQL paths).

## Validation Architecture

(`workflow.nyquist_validation` not disabled → section included.)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `^8.4.2` (`testpaths = ["tests"]`, `minversion = "8.0"`; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` (item 1) |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| HYG-01 item 1 | Position-manager test asserts via public API, still green | unit | `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` | ✅ (19 tests, currently green) |
| HYG-01 item 4 | Validator retype is type-clean | static | `make typecheck` | ✅ |
| HYG-01 items 2-7 | No run-path behavior change | static + e2e + integration | `make typecheck` && `poetry run pytest tests/e2e` && `make test-integration` | ✅ |
| HYG-01 (whole) | Golden master byte-exact | integration | `make test-integration` (runs `tests/integration/test_backtest_oracle.py` — 134 trades / `final_equity 46189.87730727451`, exact no-tolerance frame-equal) | ✅ |

### Sampling Rate
- **Per task commit:** the item's local test (e.g. `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` for item 1; `make typecheck` for items 2/4).
- **Per wave/plan merge:** `make typecheck` + `poetry run pytest tests/e2e`.
- **Phase gate (byte-exact):** `make typecheck` (clean) → `make test-integration` (134-trade oracle exact) → `poetry run pytest tests/e2e` (58/58) → `make test` (full suite green).

### Wave 0 Gaps
None — existing test infrastructure (the 19-case position-manager unit test, the 58 e2e scenarios, the `test_backtest_oracle.py` integration gate, and `mypy --strict`) fully covers every phase requirement. No new test files, fixtures, or framework install needed.

## Byte-Exact Verification Command Set (for the plan's gates)

`[VERIFIED: Makefile + ran mypy/pytest this session]`

```bash
make typecheck          # poetry run mypy itrader  → must print "Success: no issues found in 172 source files"
make test-integration   # runs tests/integration/test_backtest_oracle.py → 134 trades / final_equity 46189.87730727451, EXACT (no tolerance)
poetry run pytest tests/e2e   # → 58 passed (the e2e golden scenarios)
make test               # full suite green
```

Current baseline (this session): `mypy` clean (172 files); `test_position_manager.py` 19 passed; e2e collects 58 tests. The plan should assert the *same* counts post-change.

## Project Constraints (from CLAUDE.md)

- **Money is `Decimal` end-to-end**; `float()` only at the serialization/logging edge; enter the Decimal domain only via `to_money(x)`, never `Decimal(float)`. → directly governs item 4 (retype to strict `Decimal`) and item 6 (the `ONE` primitive lives with `to_money` in `core/money.py`).
- **Indentation by file** — handler/manager modules use tabs; `core/`, `config/`, `events_handler/events/`, and test files use 4 spaces. Match the file; never normalize (a mixed-indent diff breaks a tab file). → governs items 3, 4, 6, 7 (per-file table in Item 6).
- **Module-private constants use a leading underscore** (`_ONE`, `_ZERO`); a *shared* constant must be public (`ONE`). → the D-02 rationale for naming the consolidated constant `ONE`.
- **Queue-only cross-domain writes; read-models for cross-domain reads.** → not implicated by any item (no cross-domain wiring changes), but confirms item 1's public-API approach is consistent with the encapsulation philosophy.
- **GSD workflow enforcement** — file edits go through a GSD command. → executor operates inside `/gsd:execute-phase`.

## State of the Art

Not applicable — no evolving technology in scope. The only "old vs new" relevant facts (all already landed in v1.2):

| Old | Current | When changed | Impact on this phase |
|-----|---------|--------------|----------------------|
| `pm._storage` direct access in tests | Public `PositionManager` query API | v1.2 NAME-04 (encapsulation) — but the test wasn't migrated (W3-07 owed) | Item 1 closes the owed migration |
| `StrategyId` imported in `order_manager.py` | Removed; `StrategyId` now only in `order.py`/`bracket_book.py` | commit `2ffbeb8` (v1.2 Phase 6) | Item 5 already done — verify only |
| float tolerances on quantity-closure | `Decimal` tolerances | v1.2 WR-01/WR-02 | Item 3's `TOLERANCE = 1e-3` is the orphaned remnant |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | (none) | — | — |

**This table is empty: every claim in this research was verified against the working tree (grep/sed/git/pytest/mypy) or cited from a committed artifact (06-REVIEW.md, CONVENTIONS.md, CONTEXT.md). No user confirmation needed.** The only judgment calls left open are the two CONTEXT-designated discretion items (exact public-method choice for item 1 — recommended `get_all_positions`; exact softened wording for item 7 — intent specified), which are the planner's to finalize, not assumptions about facts.

## Open Questions (RESOLVED)

1. **Plan granularity (1 plan vs 2).** — RESOLVED: the planner chose one byte-exact plan (01-01) with a single shared verification gate, as recommended.
   - What we know: seven items, all small; item 1 is test-only, items 2-7 touch source/config.
   - What's unclear: whether the planner wants a single byte-exact plan or a test-only/source split.
   - Recommendation: one plan is fine given the tiny surface and single shared verification gate; split only if the executor benefits from committing the test-only change (item 1) independently. Either way, ONE byte-exact gate at the end.

2. **Item 5 representation in success-criteria mapping.** — RESOLVED: the plan records item 5 as a verify-only task citing commit 2ffbeb8 (no edit), as recommended.
   - What we know: criterion 3 lists "dead `StrategyId` import dropped" — already true.
   - What's unclear: whether to record it as "satisfied by prior work (commit 2ffbeb8)" vs a live task.
   - Recommendation: record as verify-only with the commit citation so the milestone audit isn't confused by a no-op edit.

## Security Domain

`security_enforcement` not disabled → section included, but **no security surface is touched.** No auth, session, access-control, crypto, or input-validation *behavior* changes. Item 4 touches a *validator*, but it is dead code (zero callers) and the change is annotation/type-guard only — it neither adds nor removes any runtime validation on any live path. ASVS V5 (Input Validation) is nominally relevant to `validators.py` but the method is unwired; no live input path is affected. No new threat patterns introduced.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | nominal only | `validate_transaction_data` is dead code; retype does not change any live validation |
| (V2/V3/V4/V6) | no | not in scope |

## Sources

### Primary (HIGH confidence — verified this session against the working tree)
- `tests/unit/portfolio/test_position_manager.py` — grep of all `_storage` usages (14 across 11 lines); `pytest` run (19 passed).
- `itrader/portfolio_handler/position/position_manager.py:253-270` — full public query API surface.
- `itrader/portfolio_handler/validators.py:19-53` — signature + isinstance body; caller grep (zero callers).
- `itrader/portfolio_handler/portfolio.py:26` — `TOLERANCE`; repo-wide grep (sole hit).
- `itrader/order_handler/order_manager.py` — `StrategyId` grep (absent); `git log -S StrategyId` (removed in 2ffbeb8).
- `itrader/core/sizing.py`, `itrader/order_handler/sizing_resolver.py`, `itrader/order_handler/brackets/levels.py` — `_ONE` def lines + usages + per-file indentation (od/sed); import graphs.
- `itrader/core/money.py:25-55` — leaf module (imports only `decimal`); placement site for `ONE`; circular-import clearance.
- `itrader/order_handler/reconcile/reconcile_manager.py:1-60` — `TYPE_CHECKING` docstring + code.
- `pyproject.toml:86-100` — mypy override block; `make typecheck` (clean, 172 files); `make test-integration` target; `tests/e2e` collects 58.
- `Makefile` — `typecheck`, `test`, `test-integration`, `test-e2e` targets.

### Secondary (committed artifacts — CITED)
- `.planning/milestones/v1.2-phases/06-order-manager-decomposition/06-REVIEW.md:74-118` — WR-01 (StrategyId), IN-01 (TYPE_CHECKING misleading doc), IN-02 (`_ONE` duplication).
- `.planning/codebase/CONVENTIONS.md:20-21,43-46,84-85` — private-constant convention, indentation map, money policy.
- `.planning/phases/01-engine-hygiene/01-CONTEXT.md` — locked decisions D-01..D-07.
- `.planning/REQUIREMENTS.md:93-103` (HYG-01); `.planning/ROADMAP.md` §Phase 1 (4 success criteria).

### Tertiary (LOW confidence)
- None. No WebSearch/external sources used — this is an in-repo hygiene phase.

## Metadata

**Confidence breakdown:**
- Item-by-item findings: **HIGH** — each verified by direct tool invocation against the working tree this session.
- Byte-exact safety: **HIGH** — every edit is dead-code/dead-constant removal, doc softening, annotation-only change to uncalled code, value-identical constant consolidation, or test-only rewrite.
- Two plan-shaping surprises (item 5 already done; item 4 has zero callers): **HIGH** — git + grep evidence.

**Research date:** 2026-06-12
**Valid until:** stable indefinitely for this working tree — re-verify only if the branch advances past `f5cacc5` before planning (the seven file locations are pinned to current HEAD).
