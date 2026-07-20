---
phase: quick-260720-owe
plan: 01
subsystem: strategy_handler
status: complete
tags: [WR-04, type-honesty, portfolio-id, mypy-strict]
requirements: [WR-04-B1]
requires:
  - itrader/core/portfolio_read_model.py (PortfolioReadModel Protocol)
  - itrader/core/ids.py (PortfolioId)
provides:
  - homogeneous list[PortfolioId] handle across the strategy domain
  - genuinely type-checked get_position call in _strategy_is_flat (WR-04 closure)
affects:
  - itrader/strategy_handler/{base,strategies_handler}.py
  - itrader/strategy_handler/{registry/rehydrate,lifecycle/manager}.py
  - itrader/storage/strategy_registry_store.py
tech-stack:
  added: []
  patterns: [module-top protocol import (DECOMP-02), delete-outright resolver narrowing]
key-files:
  created: []
  modified:
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/registry/rehydrate.py
    - itrader/strategy_handler/lifecycle/manager.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/storage/strategy_registry_store.py
    - migrations/versions/p10_strategy_portfolio_subs.py
    - tests/support/strategy_catalog.py
    - tests/unit/storage/test_strategy_registry_store.py
    - tests/unit/strategy/test_rehydrate.py
    - tests/unit/strategy/test_to_dict_snapshot.py
    - tests/unit/strategy/test_is_active_gate.py
    - tests/unit/strategy/test_strategies_handler_remediation.py
    - tests/unit/strategy/test_pair_dispatch.py
    - tests/unit/strategy/test_strategy_command_verbs.py
    - tests/integration/test_strategy_registry_restart.py
decisions:
  - "Resolver arms deleted outright, not converted to rejecting parsers — both resolvers already own the correct loud-failure destination"
  - "PortfolioReadModel imported at module top, not under TYPE_CHECKING — manager.py's DECOMP-02 convention, and the import is free"
metrics:
  duration: ~25min
  tasks: 3
  files: 15
  completed: 2026-07-20
---

# Quick Task 260720-owe: Remove the Vestigial int Arm from subscribed_portfolios (WR-04) Summary

Closed WR-04 — the last open finding in `10.1-REVIEW.md` — by narrowing the
`subscribed_portfolios` portfolio-id handle from `list[PortfolioId | int]` to
`list[PortfolioId]` across the strategy domain, and restoring the honestly-typed
read-model annotation that the arm's presence was suppressing.

**Commits:** `7adfcfa5` (fixtures) → `d2b96089` (narrowing) → `c29ea3c2` (comments)

## The Actual Closure Condition

The finding was never really about the union. It was about what the union *cost*:
`StrategyLifecycleManager._strategy_is_flat` passes each element of
`subscribed_portfolios` into `PortfolioReadModel.get_position`, whose first parameter is
`PortfolioId`. That mismatch was invisible only because the manager declared its
read-model attribute as `Optional[Any]`, which erased the call site from `mypy --strict`
entirely.

Naming the real protocol is what closes the finding. **I verified this is not vacuously
green** by deliberately breaking the call (`get_position(portfolio_id, 123)`) and
confirming mypy now catches it:

```
itrader/strategy_handler/lifecycle/manager.py:587: error: Argument 2 to "get_position"
of "PortfolioReadModel" has incompatible type "int"; expected "str"  [arg-type]
```

The error was then reverted and mypy returned to clean. Under the previous `Optional[Any]`
annotation that same error would not have surfaced at all. I also confirmed
`itrader.strategy_handler.lifecycle.manager` is **not** covered by any
`[[tool.mypy.overrides]] ignore_errors` block (the two blocks cover
`trading_system.live_trading_system`, `trading_interface`, four providers,
`screeners_handler.*`, and `my_strategies.*`) — so the check is genuinely enforced, not
silently skipped. That mattered enough to check: this repo has a known
mypy-`ignore_errors` blindspot on the live facade.

## mypy Errors Surfaced by the Narrowing

**None. Zero.** `poetry run mypy` was clean over 273 source files immediately after the
narrowing, with no type-ignore comments added and no annotation re-widened.

Per the plan's own framing, that absence *is* the finding: **the int arm was purely
vestigial.** Nothing in the codebase was relying on it. Every runtime path already
produced and consumed a real `PortfolioId`, exactly as the FL-02 invariant claims. The
arm's only measurable effect was the erased annotation it justified, which cost a real
type check on the flat-detect seam.

The only code that *did* depend on the arm was test fixtures (see Correction 1) and the
one acceptance test asserting the arm was accepted — both handled deliberately.

## The Two Decisions

**1. Resolver arms deleted outright, not converted to rejecting parsers.**

Both resolvers already own a loud-failure arm that is the correct destination for a
malformed id. A "parse-then-reject" fallback would be dead code reconstructing the same
outcome one branch later. Deleting leaves each resolver's failure *semantics* byte-identical
— only the set of ACCEPTED inputs narrows:

| Resolver | Malformed-id behavior before | after |
|---|---|---|
| `rehydrate._resolve_portfolio_id` | raises `StrategyConfigError` → D-19 quarantine | **unchanged** |
| `manager._portfolio_id_from` | returns `None` → caller makes it a loud no-op | **unchanged** |

Return types narrowed to match (`-> PortfolioId`, `-> Optional[PortfolioId]`). I did adjust
the rehydrate raise's *message* text from "is neither a UUID nor an int" to "is not a UUID",
since the old wording described an accepted-input set that no longer exists. The exception
type, the `from exc` chaining, and the quarantine path it feeds are all untouched.

**2. `PortfolioReadModel` imported at module top, not under `TYPE_CHECKING`.**

The task brief suggested `TYPE_CHECKING`. I used a module-top import instead:

- `manager.py`'s own module docstring states *"Every import is at MODULE TOP (DECOMP-02)"*
  and records that the GATE-01 lazy-import rationale was re-tested and found FALSE for this
  module. A `TYPE_CHECKING` guard would contradict a documented, deliberately-tested
  convention.
- The import is genuinely free: `itrader/core/portfolio_read_model.py` pulls only stdlib
  plus `core.enums` and `core.ids` — **both already on manager.py's module-top import
  graph** (it imports `PortfolioId` from `core.ids` directly). Zero inertness risk; the
  integration suite including `test_okx_inertness.py` stayed green.

I recorded this rationale in the class docstring too, since the docstring previously
asserted that all three live deps keep erased values — it now names `portfolio_read_model`
as the explicit exception and says why.

## Corrections to the Task Brief (both confirmed)

**Correction 1 — the int-fixture surface was 14 sites across 6 files, not 1.**
Confirmed by measurement before any edit. The brief disclosed only
`test_to_dict_snapshot.py`. Three sites were **hard breakages**, not cosmetic incoherence,
because they round-trip through `rehydrate` (where a non-UUID now raises into the D-19
quarantine): `test_rehydrate.py:207/208/210`, `test_rehydrate.py:551`, and
`test_strategy_registry_restart.py:135`. Had the source change landed first, those tests
would have gone red. This is why Task 1 ran first and why there was no red window at any
point.

Where an assertion compared against a stringified literal, I updated it to compare against
`str(<the new constant>)` rather than dropping it — so each test still proves the
serialize/parse round trip rather than a hardcoded value.

**Correction 2 — the repo DOES have a live Alembic chain, contradicting the brief.**
The brief deferred B2 partly on the claim that "there is NO Alembic chain in this repo
(verified: no `itrader/storage/migrations/` directory exists)". That directory is absent
because the chain was **relocated to the repo root** in Phase 04-01 (`git mv`, STATE.md
line 211). `migrations/versions/` is present and live, and
`migrations/versions/p10_strategy_portfolio_subs.py:106` carried the same dead
justification comment as the other three sites.

**B2's deferral stands on its own merits and was not taken here** — but it should be
re-recorded against a true premise. The migration's *comment* was the same rot being
removed elsewhere, so it was rewritten. The edit is provably comment-only: the diff gate
confirmed 1 file touched and **0** added/removed lines matching `sa.Column`,
`op.create_table`, `revision`, or `down_revision`.

## Observed but Deliberately Untouched

The same two-arm union survives on a different domain's fields, out of scope by decision:

| Site | Field |
|---|---|
| `itrader/portfolio_handler/transaction/transaction.py:36` | `portfolio_id: "PortfolioId \| int"` |
| `itrader/portfolio_handler/position/position.py:44` | `portfolio_id: "PortfolioId \| int"` |

After this task these are the **only** two occurrences remaining anywhere in the
repository (verified by repo-wide grep). Whether the same vestigiality argument applies to
the portfolio domain is a separate question and was not investigated.

Also left open by decision: **B2** — whether the
`strategy_portfolio_subscriptions.portfolio_id` column should become `Uuid` now that the
handle is homogeneous. Nothing type-level forbids it anymore. All four rewritten comments
say so explicitly, so no future reader concludes the String choice is settled.

## Observed Gate Results (actual, not expected)

Every number below was observed on the final tree. All match the plan's stated baselines
exactly — no deviations to explain.

| Gate | Baseline | **Observed** |
|---|---|---|
| `poetry run pytest tests/unit -q` | 2299 passed | **2299 passed** (12.43s) |
| `poetry run pytest tests/integration -q` | 204 passed, 2 skipped | **204 passed, 2 skipped** (26.79s) |
| `poetry run mypy` | clean, 273 files | **Success: no issues found in 273 source files** |
| Oracle `trade_count` | 134 | **134** |
| Oracle `final_equity` | 46189.87730727451 | **46189.87730727451** |

The 2 integration skips are `test_okx_connectivity.py` and `test_okx_smoke.py` — absent OKX
demo credentials, pre-existing and expected, not a regression.

Oracle values were read directly from the generated `output/summary.json` rather than
inferred from a green test, since the test diffs against committed goldens and I wanted the
actual magnitudes on record. `final_cash` also matched at `46189.87730727451`.

Ran via `poetry run pytest` throughout, never `make test` (it exports
`ITRADER_DISABLE_LOGS=true`, which breaks caplog-based assertions elsewhere in the suite).

## Per-Task Grep Gates

All gates were falsification-verified by the planner as failing pre-change; each passed
post-change:

- Task 1: bare-int `subscribe_portfolio` args under `tests/` — 14 → **0**
- Task 2: `PortfolioId | int` in strategy domain — 11 → **0**; `return int(raw)` in
  `itrader/` — 2 → **0**; `cast` tokens in `strategies_handler.py` — 3 → **0**
- Task 3: repo-wide `PortfolioId | int` excluding the two portfolio-domain files — 5 → **0**

Both indentation regression guards held: `rehydrate.py` still has exactly **7**
space-indented lines (the legitimate module-docstring prose at 23–30, untouched) and
`itrader/storage/strategy_registry_store.py` still has **0** tab lines. Every source file
edited was tab-indented and matched byte-for-byte; every test file was 4-space.

## Test Coverage Change

`test_the_legacy_int_portfolio_id_arm_still_works` was **repurposed, not deleted**, into
`test_a_bare_numeric_portfolio_id_is_a_loud_no_op`. Same command, inverted expectation: the
roster stays empty and no subscription row is written. This preserves coverage of that input
class — a numeric portfolio id is now proven *refused* rather than silently dropped from the
suite.

## Self-Check: PASSED

All 15 modified files verified present; all 3 commits verified in `git log`. Working tree
clean apart from the untracked planning directory (docs commit is the orchestrator's).
