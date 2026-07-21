---
phase: 11-multi-portfolio-live
plan: 06
subsystem: execution
tags: [routing, multi-account, security, D-27, MPORT-07]
requires: ["11-05"]
provides:
  - "pair-keyed ExecutionHandler.exchanges registry — dict[tuple[str, str], AbstractExchange | None]"
  - "DEFAULT_ACCOUNT_ID module constant (the logical account of a single-account venue)"
  - "account-resolving on_order via an injected PortfolioReadModel, fail-closed on every miss"
  - "compose_engine(route_orders_by_account=...) — the asymmetric backtest/live injection seam"
  - "tests/integration/test_per_account_exchange_routing.py — the MPORT-07 gate"
affects:
  - "itrader/execution_handler/execution_handler.py"
  - "itrader/trading_system/compose.py"
  - "itrader/trading_system/live_trading_system.py"
  - "itrader/trading_system/universe_wiring.py"
  - "itrader/trading_system/backtest_trading_system.py"
tech-stack:
  added: []
  patterns:
    - "read-model seam (Protocol imported under TYPE_CHECKING, never a concrete handler import)"
    - "asymmetric composition-root injection via an explicit keyword, not an environment-string read"
    - "fail-closed routing: refuse rather than guess an authenticated session"
key-files:
  created:
    - "tests/integration/test_per_account_exchange_routing.py"
  modified:
    - "itrader/execution_handler/execution_handler.py"
    - "itrader/trading_system/compose.py"
    - "itrader/trading_system/live_trading_system.py"
    - "itrader/trading_system/universe_wiring.py"
    - "itrader/trading_system/backtest_trading_system.py"
    - "tests/integration/conftest.py (+ 21 further test files)"
decisions:
  - "compose_engine gained an explicit route_orders_by_account keyword rather than reading ctx.environment — an environment-string read would silently skip account routing for a live system built with a test environment string."
  - "get_exchange_health keeps its str parameter and matches the venue half; its output dict keys stay venue names, disambiguated as 'venue:account' only for non-default accounts. Zero callers repo-wide (verified)."
  - "_venue_kind matches over the venue half rather than the default-account pair — 'is this venue simulated?' is a property of the venue, not of one account on it."
  - "The live registration site uses venue_spec.account_id or DEFAULT_ACCOUNT_ID. This is a REGISTRATION-side default for an unnamed account and is NOT the forbidden resolution-side fallback."
  - "Four paper-system test portfolios now name their venue account explicitly, because paper builds a LIVE system and D-27 makes account naming a real contract there."
metrics:
  duration: ~50 min
  tasks: 3
  files: 27
  completed: 2026-07-21
status: complete
---

# Phase 11 Plan 06: Per-Account Exchange Routing (MPORT-07) Summary

Keyed `ExecutionHandler.exchanges` on the `(venue, account_id)` pair and made `on_order` resolve the
account from the order's portfolio through an injected read-model, closing the path where account B's
orders were submitted through account A's authenticated session.

## What shipped

**The registry is pair-keyed.** `exchanges: dict[tuple[str, str], AbstractExchange | None]`. The
`simulated` and `csv` entries remain the *same object*, paired with `DEFAULT_ACCOUNT_ID` — that
deliberate aliasing, plus the untouched identity dedup, is what keeps the backtest resting-order book
matched once per bar and the oracle byte-exact.

**`on_order` resolves the account, and fails closed everywhere.** Three distinct refusal branches,
each logged separately: unknown portfolio, portfolio naming no account, and unregistered
`(venue, account)` pair. There is no bare-venue-name fallback anywhere on the path.

**The read-model injection is asymmetric**, per the owner decision. `compose_engine` gained an
explicit `route_orders_by_account` keyword: the backtest arm passes nothing (every backtest portfolio
has `account_id=None`, so injecting there would turn the oracle route into a refusal), and
`build_live_system` passes `True`.

**All 12 source lookup sites converted**, including the two the original scope missed:
`universe_wiring.py` (where a stale bare-name `.get` returns `None`, the `isinstance` guard silently
fails, and the Universe is never injected into the exchange) and the oracle file
`backtest_trading_system.py` (diff is the single `.get` line plus its import — verified by reading
`git diff` on that file alone).

**25 test lookup sites across 22 files migrated**, plus the MPORT-07 routing gate.

## Falsifiability — verified by mutation, not assumed

The routing gate was green on first run, so I did not treat that as proof. I injected each of the two
regressions it exists to catch and confirmed it goes red, then reverted and confirmed a clean diff
against the committed tree:

| Injected bug | Result |
|---|---|
| Fall back to a bare-venue-name match on a pair miss | `test_unregistered_account_reaches_neither_exchange` FAILS |
| `account_for(...) or DEFAULT_ACCOUNT_ID` | `test_portfolio_naming_no_account_is_refused_not_defaulted` FAILS (+ its unit twin) |

Both mutations were reverted by restoring a pre-mutation copy; `git diff` on the file afterwards was
empty.

## Plan drift found

1. **The plan's Task 3 recipe (fake `VenuePlugin` through the composition root) is unreachable** —
   as the audit block predicted. Confirmed in code: `build_live_system` takes one `exchange` string,
   builds one `venue_spec` and performs a single registration write gated on `bundle.connector is not
   None`. Built the gate by constructing `ExecutionHandler` directly.

2. **Task 1's acceptance gates needed more than Task 1's file list** — also as audited, but *more*
   than audited. The audit named three test files to pull forward; in practice the four
   `live_trading_system.py` sites had to come forward too, because
   `live_trading_system.py:1473` (`exchanges['simulated']`) raised `KeyError` and took 19 tests in
   `tests/unit/execution/` down with it. Task 1 therefore landed the live sites as well.

3. **NEW, not in the plan or the audit: five tests failed on the paper path after wiring the live
   arm.** `test_paper_parity`, `test_reconfigure_positions`, `test_strategy_remove_flat`,
   `test_universe_force_close`, `test_universe_remove_policy` all build *live* (paper) systems whose
   portfolios named no account, so the new refusal correctly rejected every order. The tempting fix
   was exactly the forbidden coercion. Instead the four portfolio-creation sites now pass
   `account_id=DEFAULT_ACCOUNT_ID` — parity-preserving (same object, same orders) and forward
   compatible with the 11-08 composition-time invariant. `test_paper_parity.py` was **outside
   `files_modified`**; the alternative was leaving the parity gate red or violating the prohibition.

4. **The mechanical test migration silently weakened one assertion.**
   `test_live_system_okx_wiring.py:63` was `"okx" not in ...exchanges`; rewritten as
   `("okx", DEFAULT_ACCOUNT_ID) not in ...exchanges` it would pass even with an OKX arm registered
   under a named account. Changed to assert over the venue half, restoring the original intent. This
   is the one place where a mechanical rewrite of a *fetch* was not behavior-neutral.

5. **`get_exchange_health` behavior change (zero callers).** Previously an unregistered venue name
   returned a `{'name': {'status': 'not_configured'}}` entry; it now returns `{}`. Confirmed zero
   callers repo-wide before deciding, per audit correction 6.

6. **The literal grep gate is confirmed insufficient**, as audited. It now returns nothing (exit 1),
   but that is not proof — I read all 12 source sites individually and confirmed each is pair-keyed
   or unpacks the tuple. The four variable-keyed sites are invisible to it.

7. **One `account_for(...) or ` grep hit remains**, at `execution_handler.py:77`. It is docstring
   prose *forbidding* the pattern, not code. A future mechanical gate on that string will flag it.

## Verification

| Gate | Result |
|---|---|
| `pytest tests -q` | **2661 passed, 6 skipped** (baseline 2645 + 16 new tests) |
| `pytest tests/integration/test_backtest_oracle.py -q` | passed — byte-exact (134 / 46189.87730727451) |
| `pytest tests/integration/test_okx_inertness.py -q` | passed |
| `pytest tests/e2e -q` | 72 passed, 4 skipped |
| `PYTHONPATH="$PWD" poetry run mypy` | Success, 253 source files |
| `grep -c 'id(exchange)' execution_handler.py` | **4** (both identity dedups intact) |
| `grep -c 'portfolio_handler' execution_handler.py` | **0** (D-27 read-model seam preserved) |
| Bare-name lookup grep over `itrader/ tests/ scripts/` | no hits (exit 1) |
| Added-line indentation (tabs vs 4-space, per file) | 0 violations both directions |
| `git diff --stat pyproject.toml poetry.lock` | empty — zero new dependencies |

All commands used `poetry run python -m pytest` and `PYTHONPATH="$PWD" poetry run mypy` per the
worktree-shadowing warning. The RED run confirmed the worktree tree was under test (the traceback
named the worktree path).

## Threat model

`T-11-26` (Elevation of Privilege — cross-account order routing) is mitigated and gated by
`test_per_account_exchange_routing.py`, with the MISS assertion specifically guarding the regression
path. `T-11-29` (tampering with the identity dedup) is held by the pinned `id(exchange)` count of 4
plus comments at both dedups recording why they must stay identity-based. `T-11-30` (unresolvable
pair) fails closed. `T-11-SC`: no packages installed.

## Notes for the next plan

- **11-07** owns per-account bundles and the multi-account registration write. The registration site
  at `live_trading_system.py` currently defaults an unnamed account to `DEFAULT_ACCOUNT_ID`; once
  bundles are per-account that default should become unnecessary.
- **11-08** owns the composition-time invariant making `account_id` mandatory in live. When it lands,
  the four `account_id=DEFAULT_ACCOUNT_ID` test-fixture additions in item 3 above become the enforced
  norm rather than a local patch, and the `None`-refusal branch in `on_order` becomes unreachable
  defense-in-depth rather than the primary guard.
- The `get_exchange_health` display-key scheme (`venue` / `venue:account`) is unexercised — it has no
  callers. If an operator surface starts consuming it, that format is the thing to review.

## Self-Check: PASSED

- `tests/integration/test_per_account_exchange_routing.py` — FOUND
- Commit `10a88c6c` (Task 1) — FOUND
- Commit `0e894165` (Task 2) — FOUND
- Commit `3a3e2ee9` (Task 3) — FOUND
