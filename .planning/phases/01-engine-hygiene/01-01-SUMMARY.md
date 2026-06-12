---
phase: 01-engine-hygiene
plan: 01
subsystem: engine-hygiene
tags: [cleanup, dead-code, money-policy, mypy, test-hygiene]
requires: []
provides:
  - "core.money.ONE public money primitive"
  - "public-API-only position-manager test asserts"
  - "strict-Decimal validate_transaction_data"
affects:
  - itrader/core/money.py
  - itrader/core/sizing.py
  - itrader/order_handler/sizing_resolver.py
  - itrader/order_handler/brackets/levels.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/validators.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - pyproject.toml
  - tests/unit/portfolio/test_position_manager.py
tech-stack:
  added: []
  patterns:
    - "Single canonical public money constant (ONE) shared cross-module from core/money.py"
key-files:
  created: []
  modified:
    - itrader/core/money.py
    - itrader/core/sizing.py
    - itrader/order_handler/sizing_resolver.py
    - itrader/order_handler/brackets/levels.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/validators.py
    - itrader/order_handler/reconcile/reconcile_manager.py
    - pyproject.toml
    - tests/unit/portfolio/test_position_manager.py
decisions:
  - "D-02: ONE is public (no leading underscore) because it is now shared cross-module"
  - "D-04: ONE entered via string-path Decimal('1'), never Decimal(1.0)"
  - "D-06: validate_transaction_data retyped to strict Decimal with no widening, no to_money coercion"
  - "D-07: strict scope honored — only the 7 enumerated HYG-01 items touched"
metrics:
  duration: ~12 min
  completed: 2026-06-12
---

# Phase 1 Plan 1: Engine Hygiene (HYG-01) Summary

Cleared the seven SAFE, byte-exact engine-hygiene debts (HYG-01): rewrote position-manager test
asserts to public query APIs, removed stale mypy/dead-constant residue, retyped a dead validator to
strict Decimal, and consolidated three duplicate `_ONE` copies into a single public `core.money.ONE`
— all with zero run-path behavior change (golden master unchanged, mypy --strict clean).

## What Was Built

**Task 1 — test asserts via public API (item 1) + item 5 verify** (commit 32dd8f5)
- Replaced 14 `pm._storage.get_positions()` / `get_closed_positions()` reaches across 11 assert lines
  in `tests/unit/portfolio/test_position_manager.py` with `pm.get_all_positions()` /
  `pm.get_closed_positions()`. The `get_all_positions()` return is the ticker-keyed `Dict`, so it
  preserves both `len(...)` and the `"BTCUSDT" in ...` membership assert. 19 tests still green.
- Item 5 (verify-only): confirmed `StrategyId` is absent from `order_manager.py` (already removed in
  commit 2ffbeb8); `order.py` keeps its 4 legitimate uses untouched. No edit made.

**Task 2 — stale override / dead constant / strict validator / reconcile doc** (commit 69faa97)
- Item 2: deleted the dead `itrader.events_handler.screener_event_handler` mypy override (+ its 2
  comment-continuation lines) from `pyproject.toml`; preserved the live `screeners_handler.*` wildcard.
- Item 3: deleted the dead `TOLERANCE = 1e-3` float constant from `portfolio_handler/portfolio.py`.
- Item 4 (D-06): retyped `validate_transaction_data` params (`price`/`quantity`/`commission`) to strict
  `decimal.Decimal` AND changed the three `isinstance(..., (int, float))` guards to
  `isinstance(..., decimal.Decimal)` — both halves together, so a real Decimal arg passes (Pitfall 1).
  Numeric-limit checks and sibling methods left unchanged (D-07). Method has zero callers — inert.
- Item 7 (IN-01): softened the `reconcile_manager.py` TYPE_CHECKING docstring so it no longer implies
  `BracketManager` is never loaded at runtime — it states the guard only keeps the annotation NAME off
  runtime name bindings (the `from ..brackets import BracketBook` runtime import loads the class anyway,
  harmlessly — no cycle). Docstring prose only.

**Task 3 — consolidate three `_ONE` copies into public `core.money.ONE`** (commit aa178ce)
- Added canonical public `ONE = Decimal("1")` to `core/money.py` (D-01/D-02/D-04, string-path literal).
- Removed the local `_ONE` from `core/sizing.py`, `order_handler/sizing_resolver.py`, and
  `order_handler/brackets/levels.py`; all three now import the shared `ONE` (D-03 — all 3, not 3-to-2).
- Left `_ZERO` in `core/sizing.py` untouched (D-05 — single copy, no dedup target).
- Corrected the `levels.py` module docstring residue that claimed `_ONE` was a module-private constant
  living in that file (Pitfall 5), and removed the stale `_ONE` token from its prose.

## Verification — byte-exact gate (all green, in order)

1. `mypy --strict` (poetry run mypy itrader): **Success: no issues found in 150 source files**.
2. Integration golden oracle (`tests/integration`): **12 passed** — `test_backtest_oracle.py` asserts
   the frozen golden EXACT (no tolerance): `trade_count 134`, `final_equity 53229.68512642488`. No drift.
3. e2e (`tests/e2e`): **58/58 passed**.
4. Full suite (`poetry run pytest`): **851 passed**.

## Deviations from Plan

### Tooling adjustments (not behavior changes)

**1. [Rule 3 - Blocking] Ran `mypy`/`pytest` directly instead of `make typecheck`/`make test`**
- **Found during:** Task 2 verification.
- **Issue:** The worktree has no `.env` file (it lives only in the main repo). The Makefile does
  `include .env` at the top, so every `make` target aborts with `make: *** No rule to make target '.env'`.
- **Fix:** Ran the exact underlying commands the targets invoke — `poetry run mypy itrader` (== `make
  typecheck`) and `poetry run pytest [...]` (== the test targets), with `PYTHONPATH="$PWD"` prepended to
  defeat the editable-install shadowing of worktree edits (per project memory note). Equivalent output.
- **Files modified:** none (CI-invocation only).

### Note on golden value vs plan frontmatter

The plan frontmatter/objective cited `final_equity 46189.87730727451`; the live frozen oracle asserts
`53229.68512642488` (the M2b-end re-baseline per `test_backtest_oracle.py` docstring). The plan figure
was a stale planning-time reference. What governs correctness is the byte-exact oracle gate, which
**passed unchanged** — confirming no run-path behavior drift, exactly as the plan intended.

## Key Decisions

- **D-02:** `ONE` is public (no leading underscore) because it is now shared across three modules.
- **D-04:** `ONE` entered via the string path `Decimal("1")`, never `Decimal(1.0)`.
- **D-06:** validator retyped to strict `Decimal` — no `(int|Decimal)` widening, no `to_money` coercion.
- **D-07:** strict scope — only the 7 enumerated HYG-01 items touched; no opportunistic adjacent cleanup.

## Known Stubs

None.

## Threat Flags

None — no new trust boundary, input, auth/crypto, IO, or persistence surface introduced.
