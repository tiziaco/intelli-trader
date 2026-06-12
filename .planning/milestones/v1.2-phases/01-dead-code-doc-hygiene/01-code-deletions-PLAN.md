---
phase: 01-dead-code-doc-hygiene
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/portfolio_handler/base.py
  - itrader/order_handler/base.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/__init__.py
  - itrader/portfolio_handler/portfolio.py
autonomous: true
requirements: [DEAD-01]

must_haves:
  truths:
    - "The 3 dead ABCs (AbstractPortfolioHandler / AbstractPortfolio / AbstractPosition) and the orphan get_last_close abstractmethod no longer exist in the source tree (per D-04)"
    - "The unused OrderBase class no longer exists and OrderHandler is a standalone class (no base / object), with the .base import and the __init__ re-export dropped (per D-04)"
    - "The dead 'import numpy as np' in portfolio.py is removed (per D-04)"
    - "The live PortfolioStateStorage ABC and the OrderStorage ABC are both KEPT untouched (per D-04)"
    - "Only orphaned imports inside the two touched base.py files are cleaned; nothing larger is folded in — larger findings logged to FIX-LIST.md (per D-05)"
    - "tests/unit/events/test_bar_event_ohlc.py is NOT touched — its get_last_close reference is a Bar string assertion, a cleared false alarm (per D-04)"
    - "Golden master byte-exact (134 trades / final_equity 46189.87730727451); mypy --strict clean; 58/58 e2e green; full suite green"
  artifacts:
    - path: "itrader/portfolio_handler/base.py"
      provides: "PortfolioStateStorage only (3 dead ABCs removed)"
      contains: "class PortfolioStateStorage"
    - path: "itrader/order_handler/base.py"
      provides: "OrderStorage only (OrderBase removed)"
      contains: "class OrderStorage"
    - path: "itrader/order_handler/order_handler.py"
      provides: "standalone OrderHandler class"
      contains: "class OrderHandler"
    - path: "itrader/order_handler/__init__.py"
      provides: "barrel without OrderBase re-export"
    - path: "itrader/portfolio_handler/portfolio.py"
      provides: "portfolio module without dead numpy import"
  key_links:
    - from: "itrader/order_handler/order_handler.py"
      to: "itrader/order_handler/base.py"
      via: "from .base import OrderStorage (OrderBase dropped)"
      pattern: "from .base import OrderStorage"
    - from: "itrader/order_handler/__init__.py"
      to: "itrader/order_handler/base.py"
      via: "from .base import OrderStorage (OrderBase dropped from import and __all__)"
      pattern: "from .base import OrderStorage"
---

<objective>
Delete the verified-dead abstractions and the dead numpy import (DEAD-01), with zero
importer breakage and zero behavior change. This is an oracle-dark, byte-exact deletion
plan: every edit removes a symbol nobody reads or rewires an importer to stop reading a
deleted symbol. No runtime behavior may change.

Purpose: make the source tree tell the truth — remove three dead ABCs, the unused
OrderBase base class, and a dead `import numpy as np` so the next milestone builds on a
clean foundation.
Output: 5 edited source files; the golden master byte-exact; mypy --strict clean.
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
@.planning/codebase/CLEANUP-STANDARD.md

<indentation_hazard>
CRITICAL (CLAUDE.md + D-04 code_context): indentation is file-dependent. Match the file,
NEVER normalize — a mixed-indentation diff in a tab file breaks the file.
- `itrader/portfolio_handler/base.py`: the 3 dead ABCs (lines 14-91) use TABS; the kept
  `PortfolioStateStorage` (line 93+) uses 4 SPACES. Deleting the tab-indented classes leaves
  the space-indented class intact — do not re-indent it.
- `itrader/order_handler/base.py`: `OrderBase` (lines 14-22) uses TABS; the kept
  `OrderStorage` (line 25+) uses 4 SPACES.
- `itrader/order_handler/order_handler.py` and `itrader/order_handler/__init__.py`: TAB modules.
- `itrader/portfolio_handler/portfolio.py`: line 1 is the import — leave indentation untouched.
</indentation_hazard>

<import_retention_facts>
Verified during planning (so the executor does NOT over-delete imports):
- In `portfolio_handler/base.py`, after removing the 3 dead ABCs, EVERY top import remains
  used by the kept `PortfolioStateStorage` and `IdLike`: `uuid`, `ABC`, `abstractmethod`,
  `Decimal`, `Any`, `Dict`, `List`, `Optional`, `Union`, `TYPE_CHECKING`, and the
  TYPE_CHECKING `Position`/`Transaction` imports. There are NO orphaned imports to remove
  in this file — touch only the class bodies.
- In `order_handler/base.py`, after removing `OrderBase`, EVERY top import remains used by
  the kept `OrderStorage` and `IdLike`: `uuid`, `ABC`, `abstractmethod`, `Any`, `Dict`,
  `List`, `Optional`, `Union`, `TYPE_CHECKING`, `datetime`. There are NO orphaned imports to
  remove in this file — touch only the `OrderBase` class.
- `OrderStorage` IS still used in `order_handler.py` (the `order_storage: Optional[OrderStorage]`
  ctor param at line 40) — KEEP the `OrderStorage` import there.
</import_retention_facts>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Delete the 3 dead portfolio ABCs and the dead numpy import</name>
  <files>itrader/portfolio_handler/base.py, itrader/portfolio_handler/portfolio.py</files>
  <read_first>
    - itrader/portfolio_handler/base.py (READ THE WHOLE FILE — you must see where the kept
      PortfolioStateStorage starts at line 93 so you do not delete it)
    - itrader/portfolio_handler/portfolio.py (read line 1 to confirm `import numpy as np`)
    - .planning/phases/01-dead-code-doc-hygiene/01-CONTEXT.md (D-04, D-05)
    - .planning/codebase/CLEANUP-STANDARD.md (touched-path cleanup scope for D-05)
  </read_first>
  <action>
    In `itrader/portfolio_handler/base.py` delete EXACTLY the three dead ABC classes and
    nothing else: `class AbstractPortfolioHandler(ABC)` (and its `get_last_close` orphan
    abstractmethod), `class AbstractPortfolio(ABC)`, `class AbstractPosition(ABC)` — the block
    spanning lines 14 through 91. KEEP `class PortfolioStateStorage(ABC)` (starts line 93) and
    everything below it, KEEP the `IdLike` alias (line 7) and the TYPE_CHECKING block
    (lines 9-11), and KEEP all top-of-file imports — per the planning import_retention_facts,
    every import is still used by PortfolioStateStorage, so DO NOT remove `abc`, `abstractmethod`,
    `typing` names, `Decimal`, or `uuid`. Do not re-indent PortfolioStateStorage (it is 4-space;
    the deleted classes were tab — leave the kept class exactly as-is). This satisfies D-05
    touched-path cleanup: there are no orphaned imports in this file to remove.

    In `itrader/portfolio_handler/portfolio.py` delete line 1 `import numpy as np` (verified
    zero `np.` references in the module). Leave every other import untouched.
  </action>
  <verify>
    <automated>grep -rn "AbstractPortfolioHandler\|AbstractPortfolio\|AbstractPosition" itrader/ ; test $(grep -rc "AbstractPortfolioHandler\|AbstractPortfolio\|AbstractPosition" itrader/portfolio_handler/base.py) -eq 0 && grep -q "class PortfolioStateStorage" itrader/portfolio_handler/base.py && ! grep -qn "import numpy" itrader/portfolio_handler/portfolio.py && echo OK</automated>
  </verify>
  <acceptance_criteria>
    - `grep -rn "AbstractPortfolioHandler\|AbstractPortfolio\|AbstractPosition" itrader/` returns no class-definition or reference hits
    - `itrader/portfolio_handler/base.py` still contains `class PortfolioStateStorage`
    - `grep -n "import numpy" itrader/portfolio_handler/portfolio.py` returns nothing
    - `poetry run python -c "import itrader.portfolio_handler.base; import itrader.portfolio_handler.portfolio"` exits 0 (no ImportError / NameError)
  </acceptance_criteria>
  <done>The 3 dead ABCs and the orphan get_last_close are gone; PortfolioStateStorage is intact; the dead numpy import is removed; both modules import cleanly.</done>
</task>

<task type="auto">
  <name>Task 2: Delete OrderBase and make OrderHandler standalone (importer sweep)</name>
  <files>itrader/order_handler/base.py, itrader/order_handler/order_handler.py, itrader/order_handler/__init__.py</files>
  <read_first>
    - itrader/order_handler/base.py (READ THE WHOLE FILE — confirm OrderBase is lines 14-22 and OrderStorage starts line 25; you must keep OrderStorage)
    - itrader/order_handler/order_handler.py lines 1-40 (the .base import line 6 and `class OrderHandler(OrderBase)` at line 17, plus the OrderStorage use at line 40)
    - itrader/order_handler/__init__.py (the .base import line 11 and `'OrderBase'` in __all__ line 19)
    - .planning/phases/01-dead-code-doc-hygiene/01-CONTEXT.md (D-04 importer-update scope)
  </read_first>
  <action>
    In `itrader/order_handler/base.py` delete EXACTLY `class OrderBase(object)` and its
    `__init__` (lines 14-22) and nothing else. KEEP `class OrderStorage(ABC)` (starts line 25)
    and the `IdLike` alias and TYPE_CHECKING block. Per import_retention_facts, KEEP all
    top-of-file imports — they are all used by OrderStorage; no orphan cleanup here.

    In `itrader/order_handler/order_handler.py`: change the import at line 6 from
    `from .base import OrderBase, OrderStorage` to `from .base import OrderStorage` (keep
    OrderStorage — it is used at line 40). Change the class declaration at line 17 from
    `class OrderHandler(OrderBase):` to `class OrderHandler:` (standalone, no base). Do not
    change anything else; `OrderHandler.__init__` already sets its own state and never relied on
    `OrderBase.__init__` for the run path (OrderBase only set `self.portfolios`, which has zero
    reads — verified false affordance).

    In `itrader/order_handler/__init__.py`: change the import at line 11 from
    `from .base import OrderBase, OrderStorage` to `from .base import OrderStorage`, and remove
    the `'OrderBase',` entry (line 19) from the `__all__` list. Keep `'OrderStorage'` in
    `__all__`. This is the established barrel pattern: editing the re-export means updating both
    the import and `__all__`.
  </action>
  <verify>
    <automated>! grep -rn "OrderBase" itrader/ && grep -q "class OrderStorage" itrader/order_handler/base.py && grep -q "^class OrderHandler:" itrader/order_handler/order_handler.py && grep -q "from .base import OrderStorage" itrader/order_handler/order_handler.py && echo OK</automated>
  </verify>
  <acceptance_criteria>
    - `grep -rn "OrderBase" itrader/` returns no hits (no class def, no import, no __all__ entry)
    - `itrader/order_handler/base.py` still contains `class OrderStorage`
    - `itrader/order_handler/order_handler.py` contains `class OrderHandler:` (no base) and `from .base import OrderStorage`
    - `itrader/order_handler/__init__.py` `__all__` no longer lists `'OrderBase'` but still lists `'OrderStorage'`
    - `poetry run python -c "from itrader.order_handler import OrderHandler, OrderStorage"` exits 0
  </acceptance_criteria>
  <done>OrderBase is deleted everywhere; OrderHandler is standalone; OrderStorage is kept and re-exported; the package imports cleanly.</done>
</task>

<task type="auto">
  <name>Task 3: Verify oracle byte-exact, mypy --strict clean, full + e2e suite green</name>
  <files>(verification only — no source edits)</files>
  <read_first>
    - .planning/ROADMAP.md §Phase 1 Success Criteria (criterion 4: golden master byte-exact, mypy clean, 58/58 e2e)
    - .planning/STATE.md Milestone Gate (the byte-exact oracle numbers)
    - CLAUDE.md Commands section (test targets)
  </read_first>
  <action>
    Run the milestone gate after the deletions in Tasks 1-2. If any check fails, the deletion
    touched a live path — STOP and investigate before declaring done (do not "fix forward" by
    changing behavior; the correct deletions cannot move the oracle). Run, in order:
    `poetry run mypy --strict` (or `make typecheck`); the full suite `make test`; the e2e
    leaf `poetry run pytest tests/e2e -m e2e`; and the byte-exact integration oracle
    `poetry run pytest tests/integration`. Confirm the integration oracle still reports
    134 trades and final_equity 46189.87730727451, and e2e reports 58/58 green.
  </action>
  <verify>
    <automated>poetry run mypy --strict && make test && poetry run pytest tests/integration tests/e2e -m e2e -q</automated>
  </verify>
  <acceptance_criteria>
    - `poetry run mypy --strict` exits 0 (clean across all source files)
    - `poetry run pytest tests/integration` is green and the golden run yields `134 trades` and `final_equity 46189.87730727451` (byte-exact, no re-baseline)
    - `poetry run pytest tests/e2e -m e2e` reports 58/58 passed
    - `make test` (full suite) is green
    - `grep -rn "get_last_close" tests/` still shows the untouched `tests/unit/events/test_bar_event_ohlc.py:62` line (false alarm left intact per D-04)
  </acceptance_criteria>
  <done>Oracle byte-exact, mypy --strict clean, e2e 58/58, full suite green — deletions confirmed behavior-preserving.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none introduced) | This plan only deletes dead code and rewires two importers; no input handling, auth, secrets, or network surface is added or touched. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-01 | Tampering | Accidental deletion of a live symbol (PortfolioStateStorage / OrderStorage) | mitigate | "Read whole file first" gate in Tasks 1-2 + grep assertions that the kept ABCs still exist + full suite / mypy --strict / byte-exact oracle in Task 3. No new attack surface — deletions reduce code; importer edits touch no runtime data path. |
| T-01-02 | Tampering | Indentation normalization corrupting a tab-indented file | accept-with-control | Explicit indentation_hazard context + "do not re-indent the kept class" instruction; mypy/parse failure in Task 3 catches a broken file. |
| T-01-SC | Tampering | npm/pip/cargo installs | n/a | No package installs in this plan — pure deletions, no dependency changes. |
</threat_model>

<verification>
Phase-level checks for this plan:
- `grep -rn "AbstractPortfolioHandler\|AbstractPortfolio\|AbstractPosition\|OrderBase" itrader/` returns no hits.
- Kept ABCs present: `class PortfolioStateStorage` and `class OrderStorage` both still exist.
- `grep -n "import numpy" itrader/portfolio_handler/portfolio.py` returns nothing.
- `poetry run mypy --strict` exits 0.
- `poetry run pytest tests/integration` byte-exact: 134 trades / final_equity 46189.87730727451.
- `poetry run pytest tests/e2e -m e2e` 58/58 green; `make test` full suite green.
</verification>

<success_criteria>
Measurable completion:
1. The 3 dead ABCs + orphan get_last_close, OrderBase (and its importer references), and the
   dead numpy import are all deleted (grep-clean).
2. PortfolioStateStorage and OrderStorage are intact and still imported/re-exported.
3. Golden master byte-exact (134 trades / 46189.87730727451); mypy --strict clean; 58/58 e2e;
   full suite green.
</success_criteria>

<output>
Create `.planning/phases/01-dead-code-doc-hygiene/01-01-SUMMARY.md` when done.
</output>
