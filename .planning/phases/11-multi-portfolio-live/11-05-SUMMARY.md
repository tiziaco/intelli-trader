---
phase: 11-multi-portfolio-live
plan: 05
subsystem: portfolio-identity
tags: [F-1, F-5, D-06, D-07, D-27, MPORT-05, restart-stability, read-model]
requires: []
provides:
  - "Portfolio.__init__(portfolio_id=, account_id=, venue_name=) — supplyable id (F-1)"
  - "PortfolioHandler.add_portfolio(portfolio_id=, account_id=, venue_name=)"
  - "PortfolioReadModel.account_for(portfolio_id) -> str | None (D-27 seam for 11-06)"
  - "PortfolioHandler.account_for implementation"
  - "PortfolioSpec.account_id (MPORT-05)"
  - "duplicate-supplied-id guard on add_portfolio"
affects:
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/core/portfolio_read_model.py
  - itrader/trading_system/system_spec.py
tech-stack:
  added: []
  patterns: [read-model-protocol-seam, defaulting-params-for-oracle-safety]
key-files:
  created:
    - tests/unit/portfolio/test_portfolio_identity.py
    - tests/unit/trading_system/test_system_spec.py
  modified:
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/core/portfolio_read_model.py
    - itrader/trading_system/system_spec.py
    - tests/unit/core/test_portfolio_read_model.py
decisions:
  - "account_for typed `-> str | None` (not `-> str`, not cast()) because Portfolio.account_id is Optional and mypy runs strict over itrader/"
  - "Kept the legacy `exchange` parameter; venue_name WINS when supplied, exchange is the fallback — removing it would break the byte-exact oracle call site"
  - "Duplicate supplied portfolio_id raises PortfolioValidationError, mirroring the sibling guards in the same method"
metrics:
  duration: ~35m
  completed: 2026-07-21
status: complete
---

# Phase 11 Plan 05: Portfolio Identity Plumbing Summary

Made `portfolio_id` supplyable so a rehydrated portfolio reattaches to its durable
child tables (F-1), gave every portfolio an `account_id` (D-06), derived `exchange`
from `venue_name` (D-07), added the `account_for` read-model seam that plan 11-06
needs (D-27), and added `PortfolioSpec.account_id` (MPORT-05) — all with defaulting
parameters so the byte-exact backtest oracle call site is untouched.

## What was built

**Task 1 — one signature change per method (`4ca99275` RED, `dc7bfc3a` GREEN)**

`Portfolio.__init__` gained `portfolio_id` / `account_id` / `venue_name`, all
defaulting. A supplied id is used verbatim; omitting it still mints a UUIDv7 through
the single `idgen` singleton (no second id scheme). `self.exchange` is derived from
`venue_name` when supplied, falling back to the legacy `exchange` parameter otherwise.
The false restart-survival docstring claim was rewritten to say what is now true and
why (the id is supplied on rehydrate, not regenerated).

`add_portfolio` mirrors the three parameters and threads them into the `Portfolio`
construction. Everything else in the method — validation, `max_portfolios` guard,
store assignment, error-publishing wrapper — is unchanged.

**Duplicate-id guard (correction-notice item 4).** `add_portfolio` now raises
`PortfolioValidationError` when a supplied `portfolio_id` is already registered.
Without it, the unconditional `self._portfolios[...] = portfolio` store would have
silently destroyed the first portfolio, its cash and its positions.

**Task 2 — `account_for` (`2810fcac`)**

Added to the `PortfolioReadModel` Protocol and implemented on `PortfolioHandler` as
the direct mirror of `exchange_for` (routed through `get_portfolio`, so an unknown id
raises `PortfolioNotFoundError` identically). Typed `-> str | None`. Both docstrings
state that `ExecutionHandler` reads this through the injected Protocol and must never
import `PortfolioHandler`, so a later reader does not "simplify" it into a direct
import. `grep -c 'portfolio_handler' itrader/execution_handler/execution_handler.py`
returns 0.

`tests/unit/core/test_portfolio_read_model.py` was updated as the correction notice
required: `_ConformingFake` gained `account_for`, the `expected` literal set gained
`"account_for"`, and `test_protocol_declares_exactly_eleven_methods` was renamed to
`..._twelve_methods`.

**Task 3 — `PortfolioSpec.account_id` (`444e928c` RED, `d6e352c3` GREEN)**

Appended LAST with a `None` default so every existing construction site stays valid,
with a docstring note recording the 11-08 union-check rationale.

## Plan drift found

**1. `poetry run pytest` does NOT test the worktree code — this invalidated an
acceptance-criteria command.** Every `<verify>` block and acceptance criterion in the
plan specifies `poetry run pytest`. In this worktree that resolves `itrader` from the
`.venv` editable install pointing at the MAIN repo, so it ran against unmodified
source. Concretely: after Task 1 was fully implemented and `inspect.signature` showed
the new parameters at runtime, `poetry run pytest` still reported
`TypeError: Portfolio.__init__() got an unexpected keyword argument 'portfolio_id'`
and 13 failures, while `poetry run python -m pytest` on the identical tree reported
12 passed / 3 failed (only the not-yet-implemented Task 2 tests).

Had I trusted the plan's command, I would have concluded Task 1 was broken and
"fixed" working code. **All gates in this summary were run with
`poetry run python -m pytest`**, which prepends cwd to `sys.path`. Successor plans in
this phase should use `poetry run python -m pytest` (or `PYTHONPATH="$PWD"`) inside a
worktree. This matches the known `.venv`-shadowing hazard.

**2. Task 3's grep gate was already true before any edit — replaced.** The plan asked
for `grep -c 'account_id' itrader/trading_system/system_spec.py` to return `> 1`. It
returned 3 on the untouched file (`SystemSpec.account_id` plus two docstring
mentions), so it could not fail. Used the correction notice's replacement,
`grep -cE '^\s*account_id: str \| None' ... == 1`, which is 0 before and 1 after.

**3. Task 3's "extend the existing spec unit tests" had no target.** Confirmed: no
test for `system_spec.py` or `PortfolioSpec` existed anywhere under `tests/unit/`.
Created `tests/unit/trading_system/test_system_spec.py` (5 tests). Running
`pytest tests/unit/trading_system` before this would have been a false green — it
passed 96 tests none of which touched `PortfolioSpec`.

**4. Two of the 15 identity tests were green before any change** — recorded rather
than counted as proof:
- `test_omitted_portfolio_id_still_mints_a_fresh_uuidv7` — the pre-existing mint path;
  it is a regression guard that the id was not re-schemed, not evidence of new work.
- `test_handler_still_satisfies_the_read_model_protocol` — trivially true before the
  Protocol gained a member. It became load-bearing only after Task 2.
The other 13 failed at RED and passed at GREEN.

**5. Minor:** re-emitting two lines of the `add_portfolio` validation block stripped
pre-existing trailing whitespace on them. Whitespace-only, no behavior change.

Claims that verified TRUE against the code: `portfolio_handler.py:235` unconditional
store; `exchange_for` at `:365-368`; `rehydrate` at `:918` (getattr-guarded at
`:963-969`, left untouched — no second rehydrate path introduced);
`backtest_trading_system.py:516-520` oracle call; the by-equality Protocol member-set
test at `:180-203` with `_ConformingFake` at `:99-133`; and every indentation
measurement (`portfolio.py` 846 tab lines, `portfolio_handler.py` 0 tab lines,
`system_spec.py` 69 tab lines, `portfolio_read_model.py` 0 tab lines).

## Verification

| Gate | Result |
|---|---|
| `python -m pytest tests -q` | 2620 passed, 6 skipped |
| `python -m pytest tests/unit/core/test_portfolio_read_model.py -q` | passed (16, was 15) |
| `python -m pytest tests/integration/test_backtest_oracle.py -q` | 3 passed — byte-exact |
| `python -m pytest tests/integration/test_okx_inertness.py -q` | passed |
| `mypy` | Success: no issues in 251 source files |
| `git diff -- itrader/trading_system/backtest_trading_system.py` | EMPTY (oracle call untouched) |
| added space-indented lines in `portfolio.py` | 0 |
| added tab-indented lines in `portfolio_handler.py` | 0 |
| added space-indented lines in `system_spec.py` | 0 |
| `grep -c 'def account_for'` in Protocol / handler | 1 / 1 |
| `grep -c 'portfolio_handler' execution_handler.py` | 0 |

## Notes for later plans

- **11-06** injects `PortfolioReadModel` into `ExecutionHandler` and reads
  `account_for`. The seam is in place and returns `str | None` — the consumer must
  handle `None` (a portfolio that names no account), not assume `str`.
- **11-08** owns the composition-time invariant: distinctness across the union of
  spec-supplied and rehydrated portfolios, and requiring a named account in live. The
  duplicate-id guard landed here closes only the same-id-twice window inside
  `add_portfolio`; it does NOT check account distinctness.
- **`max_portfolios` (default 50) applies to rehydrated portfolios** once 11-08 routes
  rehydrate through `add_portfolio`. A restart above 50 persisted portfolios fails
  loud mid-rehydrate leaving a partial set. Unchanged per RESEARCH; carried forward.
- **All-zeros UUID remains a reserved sentinel** (`itrader/results/sql_storage.py:52-53`,
  `_AGGREGATE_PORTFOLIO_ID`). Nothing here rejects a supplied all-zeros `portfolio_id`;
  if that is worth refusing, it belongs with 11-08's invariant.

## Self-Check: PASSED

All created files exist; all four commits (`4ca99275`, `dc7bfc3a`, `2810fcac`,
`444e928c`, `d6e352c3`) present in `git log`.
