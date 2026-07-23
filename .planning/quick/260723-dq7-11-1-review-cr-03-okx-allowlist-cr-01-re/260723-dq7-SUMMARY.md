---
phase: quick-260723-dq7
plan: 01
subsystem: order-admission / paper-worker / portfolio-account / venue-plugins
tags: [code-review-closure, security, money-policy, live-path]
requires:
  - "Phase 11.1 review findings CR-03, CR-01, WR-03, WR-05"
provides:
  - "The registered live OKX venue is admissible at order admission"
  - "A zero-trade paper replay exits non-zero"
  - "One home for the account cash scale (Account.precision / Account.quantize_cash)"
  - "A cross-account OKX mint is refused before any connector is keyed (WR-03)"
affects:
  - itrader/order_handler/order_validator.py
  - scripts/run_live_paper.py
  - itrader/portfolio_handler/account/base.py
  - itrader/portfolio_handler/account/simulated.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/venues/okx_plugin.py
tech-stack:
  added: []
  patterns:
    - "Boundary-quantize helper on the ABC (Account.quantize_cash) instead of per-leaf inline scale literals"
    - "Run-outcome guard in a bootstrap script raising RuntimeError for a non-zero exit"
key-files:
  created:
    - .planning/todos/completed/okx-missing-from-validator-allowlist.md (moved from pending/)
  modified:
    - itrader/order_handler/order_validator.py
    - tests/unit/order/test_order_validator_venue_allowlist.py
    - scripts/run_live_paper.py
    - itrader/portfolio_handler/account/base.py
    - itrader/portfolio_handler/account/simulated.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/venues/okx_plugin.py
    - tests/unit/venues/test_okx_plugin.py
decisions:
  - "WR-05: the cash scale is hoisted onto the Account ABC as a class attribute rather than reordered on the leaf — the briefed 'reorder' mechanism cannot hold once quantize_cash must resolve on the ABC under mypy --strict"
  - "WR-03 (owner decision, later session): ship the guard and rewrite the two conflicting tests — refusing a mismatch is not widening, so D-11's rationale survives intact"
  - "WR-03: ValidationError is hoisted to a module-top import in okx_plugin.py rather than added as a second function-local one (owner has rejected mid-code imports; core.exceptions is inert so D-04 is unaffected)"
metrics:
  duration: ~15min
  completed: 2026-07-23
status: complete
---

# Quick Task 260723-dq7: Phase 11.1 Review Closures (CR-03, CR-01 residual, WR-05) Summary

Closed three decision-settled Phase 11.1 review findings as three atomic commits — the live OKX
venue is now admissible at admission, an inert paper replay exits non-zero, and the 2dp cash scale
has exactly one home on the `Account` ABC. **WR-03 was deliberately deferred, not forgotten** (see
below).

## Scope Restriction Applied (SUPERSEDED — WR-03 closed in a follow-up execution)

> **Superseded 2026-07-23 by commit `95b2929c`.** The deferral recorded below was real and is
> kept verbatim as the historical record of the first execution. The owner has since decided the
> conflict (ship the guard, rewrite the two tests) and WR-03 has landed — see
> **"WR-03 — the cross-account mint guard (follow-up execution)"** near the end of this summary.
> All four plan tasks are now complete; `T-dq7-04` is mitigated, not open.

The dispatch brief restricted this execution to **three of the plan's four tasks**. Plan Task 3
(**WR-03** — the OKX `account_factory` cross-account mint guard) was **NOT executed**:

- `itrader/venues/okx_plugin.py` and `tests/unit/venues/test_okx_plugin.py` are **byte-unchanged**
  (confirmed: `git diff --name-only 4fb84c43..HEAD` lists neither file).
- **Reason:** the planner found that two existing tests
  (`test_account_factory_never_widens_a_supplied_account_id`,
  `test_bundle_account_factory_delegates_to_new_account`) deliberately assert the exact behaviour
  the WR-03 guard would forbid, with D-11 rationale docstrings. That conflict is an **owner
  decision**, not an executor call.
- **Status:** blocked pending owner sign-off. WR-03 remains open and should be re-dispatched once
  the D-11 assurance is settled.

Plan Task 3's success criteria, threat-register row `T-dq7-04`, and the plan's "four commits"
criterion are therefore **not** satisfied by this execution. Three commits landed, not four.

## What Was Built

**CR-03 — the registered live OKX venue is admitted at admission** (`c42cb22a`)

`EnhancedOrderValidator.supported_exchanges` had exactly one assignment tree-wide
(`order_validator.py:125`, confirmed by grep before editing) and it did not contain `"okx"` — while
the live composition root registers the venue (`exec_registry.register('okx', OkxVenuePlugin())`,
`live_trading_system.py:1944`) and a live OKX portfolio carries `Portfolio.exchange == "okx"`.
Nothing derives the allowlist from the registry, so the two disagreed silently. PHASE 2 of
`validate_order_pipeline` short-circuits on any ERROR from `_validate_market_conditions` (verified
at `order_validator.py:165-169`), so every live OKX order was refused with a typed
`UNSUPPORTED_EXCHANGE` and the session submitted nothing.

Fix was **tactical, not structural** as instructed: `"okx"` added to the set literal. No registry
derivation, no `supported_venues` constructor parameter, no signature change.

The adjacent comment no longer reads as a complete inventory. It now records that a REGISTERED
execution venue *has to* be a member, names the concrete failure (PHASE 2 refuses every order,
short-circuits before sizing, run submits nothing, nothing else red), and keeps the existing
default-deny / "repoint it, do not weaken it" instructions verbatim.

One regression test added — `test_live_okx_venue_is_admitted` — using the file's existing
`_validator_reporting_venue` helper and `_make_order()`. The three default-deny tests
(`test_unknown_venue_is_refused_with_the_typed_error_code`, `test_empty_venue_name_is_refused`,
`test_allowlist_is_default_deny_not_accept_all`) are **unchanged**.

**CR-01 residual — the paper replay fails loud on an inert run** (`7d36b08a`)

Premise re-verified before editing: `_compose` already passes `account_id=DEFAULT_ACCOUNT_ID`
(`run_live_paper.py:92`, the first half of CR-01 fixed in `ccfdc3ef`), and `_run_replay` /
`_run_okx_smoke` are separate functions dispatched by `main`.

Added module-level `_refuse_inert_replay(trade_count: int) -> None`, raising `RuntimeError` on a
zero count and returning otherwise. Its message names the three required facts: the replay drives
the committed golden CSV so zero trades means the composition submitted nothing; the concrete
shape that produced it before (a portfolio naming no venue account has every order refused at
`ExecutionHandler.on_order`); and that this is the offline parity harness, so unlike the live smoke
a flat session is not legitimate here.

Called from `_run_replay` **after** the existing `logger.info(...)` and summary `print(...)`, so an
inert run still emits diagnostics before the process dies. The uncaught raise is the non-zero exit
— no `sys.exit` alongside it, `main` does not swallow it. No exact trade count is asserted and the
golden numbers are not referenced in the guard.

`_run_okx_smoke`, `main`, `_compose` and the argparse block are byte-unchanged.

**WR-05 — one home for the cash scale** (`0181956f`)

Three writings of one 2dp scale collapsed to one, strictly value-preserving:

- `Account` ABC (`account/base.py`, 4-space) now declares `precision: Decimal = Decimal('0.01')`
  as a class attribute and exposes a non-abstract
  `quantize_cash(self, value: "float | Decimal") -> Decimal` returning
  `to_money(value).quantize(self.precision, rounding=ROUND_HALF_UP)`. Its docstring records that
  this is the single home of the cash scale and that it is a **boundary quantize only** — never to
  be applied mid-stream on the fill / lock / carry paths, which carry full precision or the
  byte-exact oracle moves. `ROUND_HALF_UP` and `to_money` imported alongside the existing
  `Decimal` / `OrderId` imports (core was already on this module's import graph; the inertness gate
  is green).
- `SimulatedCashAccount.__init__` computes the opening balance via `self.quantize_cash(initial_cash)`
  and its `precision` instance assignment is **deleted**; the comment now says the scale comes from
  the account's declared precision and restates no numeric literal.
  `_validate_and_convert_amount` (plan called it `_validate_amount` — minor naming drift, code
  wins) keeps reading `self.precision`, now resolving to the inherited class attribute of the same
  value.
- `Portfolio._validate_initial_state` (TAB-indented, re-confirmed 928 tab lines before the first
  edit; 0 space-indented lines added, verified on the diff) now sets
  `expected = account.quantize_cash(cash)`. The exact-equality comparison, the raised
  `ValidationError` and its message are unchanged.

Value-preservation was checked explicitly, not assumed: all three sites were
`to_money(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)` before and resolve to exactly that
after. `VenueAccount` has no `precision` of its own (grepped — confirmed) and gets no override.
`position_manager.py`'s separate 8dp scale is untouched.

## Deviations from Plan

### Recorded deviations

**1. [Planned deviation — WR-05 ABC hoist instead of leaf reorder]**

- **Found during:** Task 4 (WR-05)
- **Briefed mechanism:** reorder `SimulatedCashAccount`'s `precision` assignment above the
  opening-balance computation.
- **Why it cannot hold:** `quantize_cash` must resolve on the `Account` ABC under `mypy --strict`,
  because `Portfolio._validate_initial_state` calls it through the ABC-typed `self.account`. A
  helper on the ABC needs `precision` declared on the ABC — so reordering the leaf assignment would
  leave **two** writings of the literal (one on the ABC for the helper, one on the leaf), which is
  the defect WR-05 exists to remove.
- **Verified against the code before applying:** `VenueAccount` has no `precision` attribute (so
  the ABC declaration is the only value it can inherit); `SimulatedMarginAccount` does not
  reassign it; `simulated.py:170` was the only `precision = ` assignment in the account package;
  no test reads or patches `account.precision`. The ABC-declared value and the deleted leaf value
  are the same `Decimal('0.01')`, so the hoist is byte-identical.
- **Consequence:** `self.quantize_cash(...)` at `__init__` line ~139 resolves the class attribute
  even though it runs before the old line-170 assignment site — the ordering hazard the reorder was
  meant to solve disappears entirely rather than being worked around.
- **Commit:** `0181956f`

**2. [Rule 3 — unused import removed] `to_money` dropped from `portfolio.py`**

- **Found during:** Task 4, step 3
- **Issue:** the plan sanctioned removing `ROUND_HALF_UP` from `portfolio.py`'s `decimal` import
  "only if no other use remains", and said to leave `to_money` alone "if still used". After the
  edit `to_money` was no longer used in code — its only remaining occurrence was a prose mention
  inside a docstring (line 225). An unused import is dead code, and `mypy --strict` does not flag
  it.
- **Checked before removing:** nothing imports `to_money` from `itrader.portfolio_handler.portfolio`
  (only `Portfolio` and `Position` are re-imported from that module tree-wide), and no test patches
  `itrader.portfolio_handler.portfolio.to_money`.
- **Commit:** `0181956f`

### Plan-vs-code discrepancies found (code wins, no fix needed)

- `simulated.py`'s amount validator is `_validate_and_convert_amount`, not `_validate_amount` as
  the plan's `read_first` calls it. Same function, same `self.precision` read. No impact.
- Every other line reference in the plan resolved correctly by symbol.

## Verification Results

All gates run from the repo root with `poetry run` (never `make test`):

| Gate | Result |
|------|--------|
| `pytest tests/integration/test_backtest_oracle.py -q` | **3 passed** — byte-exact 134 / `46189.87730727451` (`check_exact=True`) |
| `pytest tests/integration/test_okx_inertness.py -q` | **4 passed** |
| `mypy itrader` | **Success: no issues found in 282 source files** (baseline) |
| `pytest tests -q` | **2878 passed, 6 skipped** |
| `python scripts/run_live_paper.py --mode replay` | exit **0**, `trades: 134`, `46189.87730727451` |
| `pytest tests/unit/portfolio tests/unit/core -q` | 614 passed |
| `pytest tests/unit/order/test_order_validator_venue_allowlist.py tests/unit/order/test_order_validator.py -q` | 23 passed |

**Full-suite count delta: 2877 → 2878 passed (+1), 6 skipped (unchanged).**
The +1 is exactly Task 1's `test_live_okx_venue_is_admitted`. The plan predicted +2 (Task 1's one
plus Task 3's net +1); Task 3 was not executed, so +1 is the correct count for this scope. The 6
skips are all OKX-credential-gated (unchanged).

**Inert-run guard proven end-to-end, not just as a unit:**
- `_refuse_inert_replay(1)` returns; `_refuse_inert_replay(0)` raises `RuntimeError` with the full
  three-fact message.
- Patching `build_trade_log` to return `[]` and calling `main(mode='replay')` gives process exit
  code **1** — proving `_run_replay` does not swallow the raise and the guard really produces a
  non-zero exit.

**Indentation re-measured per file before the first edit to each (never generalized):**
`portfolio.py` 928 tabs / 0 space-indented lines (933 tabs after edit, 0 space-indented lines added
— verified on the diff, not on the whole file); `account/base.py` 0 tabs / 46 space-indented lines;
`account/simulated.py` 0 tabs; `order_validator.py` and `run_live_paper.py` both 4-space.

**Post-commit deletion check:** no unintended tracked-file deletions in any of the three commits.
The only rename is the intentional todo move.

## Commits

| # | Hash | Task | Message |
|---|------|------|---------|
| 1 | `c42cb22a` | CR-03 | `fix(11.1): admit the registered live OKX venue at admission (CR-03)` |
| 2 | `7d36b08a` | CR-01 residual | `fix(11.1): fail the paper replay loud on an inert run (CR-01 residual)` |
| 3 | `0181956f` | WR-05 | `refactor(11.1): give the cash scale one home on the Account ABC (WR-05)` |

Base: `4fb84c43` on branch `v1.8/phase-11.1-account-provisioning` (non-isolated, no worktree, no
branch switch).

## Todo File Move

`.planning/todos/pending/okx-missing-from-validator-allowlist.md` was present as the plan described
and was `git mv`'d to `.planning/todos/completed/` in commit `c42cb22a` (the CR-03 commit), as
instructed. The `completed/` directory already existed.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, file-access pattern or trust-boundary schema change was
introduced. The three threat-register rows this execution covers — `T-dq7-01` (DoS at admission),
`T-dq7-03` (repudiation via a silently-successful inert run) and `T-dq7-05` (tampering via a
one-sided cash-scale change) — are all mitigated as planned. `T-dq7-04` (spoofing via a
cross-account OKX mint) remains **OPEN** because WR-03 was deferred.

## Out of Scope (untouched, as instructed)

CR-02, WR-01, WR-04, WR-06, WR-08 — not looked at, not opportunistically fixed.
`itrader/venues/paper_plugin.py` — untouched.

## Notes for the Orchestrator

Per the dispatch constraints, **no docs artifacts were committed** — `STATE.md`, `ROADMAP.md` and
this SUMMARY are left for the orchestrator's docs commit. `ROADMAP.md` was not updated.

## Self-Check: PASSED

- All modified source files exist on disk and are staged into the three commits above.
- All three commit hashes resolve in `git log`.
- `okx_plugin.py` / `test_okx_plugin.py` confirmed absent from
  `git diff --name-only 4fb84c43..HEAD` — the WR-03 deferral is real, not a claim.
  *(True as of the first execution; both files are modified by `95b2929c` below.)*

---

# WR-03 — the cross-account mint guard (follow-up execution)

Executed after the owner settled the D-11 conflict the first execution correctly refused to
decide. One atomic commit, `95b2929c`, on the same branch (non-isolated, no worktree, no branch
switch), based on `0181956f`.

## Owner Decision That Unblocked It

The planner found two existing tests that deliberately assert the behaviour the guard forbids,
with D-11 rationale docstrings. The owner was shown both tests and the conflict, and chose:
**ship the guard and rewrite both tests.**

The reasoning accepted: D-11's stated concern is the closure preferring its BUNDLE's id over a
supplied one — which would attach a portfolio to a different real venue balance while every lookup
above it still looked correct. **Refusing a mismatch is not widening**, so D-11's rationale
survives intact; what changed is only the assertion those two tests chose for a case that is
unreachable today.

## What Was Built

`OkxVenuePlugin.build_bundle`'s `account_factory` closure overrode `account_id` via `replace(...)`
but left `account_config.spec` — the spec (and therefore the `secret_ref`) the BUNDLE was built
for. A mismatched id therefore reached
`config.connectors.get("okx", <other id>, <this bundle's spec>)`, and `ConnectorProvider.get`
would build a connector from `OkxConnectorPlugin.build(spec_of_account_A)` and memoize it under
`("okx", "B")` — account B's session authenticated with account A's credentials. That is the
cross-account misroute D-11/D-12 exist to close.

Added, immediately BEFORE the `replace(...)`:

```python
if account_id is not None and account_id != account_config.account_id:
    raise ValidationError("account_id", str(account_id), <message>)
```

The message names BOTH ids, states that the bundle carries the other account's resolved
credentials on its spec and that the spec does not travel with a substituted `account_id`, names
the concrete consequence (a connector memoized under `('okx', '<supplied>')` while authenticated
from `'<bundle>'`'s `secret_ref`, attaching the id to a DIFFERENT real venue balance), and cites
D-11/D-12.

**Docstring/comment corrected in the same commit.** The old text asserted "A SUPPLIED id always
wins and is never widened" — half the state that has to move together. It now records all three
cases explicitly: an OMITTED id falls back to the bundle's own (documented D-11 behaviour,
**preserved verbatim**), a MATCHING id is accepted, and a MISMATCHED id is refused because the id
and the credential-bearing spec cannot move independently. It also records why refusing is not
widening — a disagreeing id now yields no account at all rather than the wrong one.

`itrader/venues/paper_plugin.py` is **untouched**, as instructed: its factory is reached by
`PortfolioHandler._new_compute_account`, which fetches the compute bundle keyed at
`DEFAULT_ACCOUNT_ID` and then legitimately mints under an arbitrary portfolio account id.

## Reachability Check (done BEFORE writing the guard)

The dispatch required stopping if the guard turns out to be reachable on a real call path, which
would make this a live behaviour change rather than a latent-hazard guard. Both call sites of
`account_factory` were traced:

| Call site | Reaches the OKX closure? | Ids match? |
|-----------|--------------------------|------------|
| `live_trading_system.py:1726` — `lifecycle.bundle.account_factory(account_id=account_id)` | Yes | **Always.** `lifecycles[spec.account_id or "default"]` (`assemble.py:227`) and `build_bundle`'s own `account_id = spec.account_id or DEFAULT_ACCOUNT_ID` derive from the SAME spec, and the loop looks the lifecycle up by the very id it then passes. |
| `portfolio_handler.py:428` — `bundle.account_factory(account_id=account_id)` with an arbitrary portfolio id | **No.** It fetches `self._venue_bundles.get(self._compute_venue, ...)`, and `compute_venue` is wired once, to `COMPUTE_VENUE` (`compose.py:233` — "the one home of the 'paper' name"). This is the paper arm. | n/a |

**Conclusion: the guard is unreachable on every current call path** — it is a latent-hazard guard,
not a behaviour change. Confirmed empirically too: the whole suite is green with no third test red.

## Tests

Exactly the two named tests changed (net +1 test):

- `test_account_factory_never_widens_a_supplied_account_id` → replaced by TWO tests:
  - `test_account_factory_refuses_a_supplied_id_the_bundle_was_not_built_for` — asserts
    `ValidationError` is raised, that BOTH ids appear in the message, and that no connector was
    ever keyed under the foreign id (`("okx", "acct-b") not in connectors._memo`), which proves the
    refusal precedes the mint rather than merely undoing it.
  - `test_account_factory_accepts_a_supplied_id_matching_the_bundles_own` — the real live call
    shape (`_attach_venue_accounts` always passes the id explicitly, looked up by that same id)
    still mints.
- `test_bundle_account_factory_delegates_to_new_account` — re-pointed to a MATCHING id. The
  `_connector is connectors.get(...)` assertion is kept, updated to `acct-a`.

**Docstring rationale preserved, not deleted.** The rewritten refusal test keeps the original
`_attach_venue_accounts` / "a portfolio would silently receive an account for a DIFFERENT real
venue balance while every lookup above it still looked correct" paragraph as the D-11 premise, then
adds why the id cannot travel without the spec and why refusing does not widen. The delegation test
records that only the id it is demonstrated with changed, not the property under test.

**Pinned and untouched, as required:**
- `test_account_factory_with_no_account_id_mints_the_bundles_own_account` — the D-11 omitted-id
  fallback. Unchanged, green.
- `test_okx_account_factory_is_keyword_only_and_has_no_catch_all` — the signature gate. Unchanged,
  green.
- `test_okx_plugin_module_imports_no_ccxt` — the D-04 module-scope AST gate. Unchanged, green
  (see the import deviation below).

**No third test went red** at any point, so the guard is exactly as broad as intended.

## Deviations (WR-03)

**3. [Deviation — module-top `ValidationError` import instead of a second function-local one]**

- **Found during:** WR-03, step 1.
- **Plan text:** "Reuse the module's existing `ValidationError` import site/style (the same one
  `_account_id_for` uses)" — which is a FUNCTION-LOCAL import (`okx_plugin.py:243` at the time).
- **Dispatch override:** the owner has rejected mid-code imports as a pattern, and instructed
  "import at module top if the file's convention allows it".
- **What was done:** `from itrader.core.exceptions import ValidationError` added at module top, and
  `_account_id_for`'s now-redundant function-local import **deleted**. Both instructions are then
  satisfied together: the file has exactly ONE import form for the symbol (the plan's real
  constraint — "do not add a second import form"), and no mid-code import.
- **Why this is safe against D-04 (checked, not assumed):** the module's laziness discipline is
  about OKX/ccxt/async/SQL concretions. `itrader.core.exceptions` is pure stdlib-only and is
  already on the backtest import graph; the module already imports `itrader.logger` and
  `itrader.venues.registry` at module scope. The AST gate forbids only names containing `ccxt`,
  `itrader.connectors.okx`, `okx_settings`, and the inertness probe forbids only the OKX/async and
  SQL stacks. Both are green.
- **Not touched:** `OkxConnectorPlugin.build`'s function-local `CredentialResolutionError` import
  stays as-is — it sits inside a D-04-guarded lazy body and is out of WR-03's scope.
- **Commit:** `95b2929c`

### Plan-vs-code discrepancies (WR-03)

None. Every symbol in the WR-03 task description matched the code at `0181956f`
(`account_factory` at ~:321-349 with its D-11 paragraph at ~:338-342, `new_account`'s
`config.connectors.get("okx", account_id, config.spec)`, and the three named tests at their
described line numbers).

## Verification Results (WR-03)

All gates run from the repo root with `poetry run` (never `make test`):

| Gate | Result |
|------|--------|
| `pytest tests/unit/venues -q` | **94 passed** |
| `pytest tests/integration/test_okx_inertness.py test_multi_account_composition.py test_backtest_oracle.py -q` | **28 passed** — oracle byte-exact 134 / `46189.87730727451` (`check_exact=True`) |
| `mypy itrader` | **Success: no issues found in 282 source files** (baseline) |
| `pytest tests -q` | **2879 passed, 6 skipped** |

**Full-suite count delta: 2878 → 2879 passed (+1), 6 skipped (unchanged).**
Exactly the plan's predicted Task 3 net +1: one test removed, two added. Cumulative delta for the
whole quick task is 2877 → 2879 (+2), as the plan predicted. The 6 skips remain the
OKX-credential-gated ones.

**Indentation re-measured before the first edit** (per file, never generalized):
`itrader/venues/okx_plugin.py` 0 tabs, `tests/unit/venues/test_okx_plugin.py` 0 tabs / 331
space-indented lines — both 4-space, and both still 0 tabs after the edits.

**Post-commit deletion check:** `git diff --diff-filter=D --name-only 0181956f..95b2929c` is empty —
no tracked file was deleted. No untracked files were produced.

## Commits (WR-03)

| # | Hash | Task | Message |
|---|------|------|---------|
| 4 | `95b2929c` | WR-03 | `fix(11.1): refuse a cross-account OKX mint in account_factory (WR-03)` |

## Threat Flags (WR-03)

None new. `T-dq7-04` (Spoofing — `OkxVenuePlugin.build_bundle::account_factory` →
`ConnectorProvider.get`) is now **MITIGATED**: a mismatched `account_id` is refused before any
`replace(...)` and before any `connectors.get`, so account B's session can never be memoized from
account A's `secret_ref`. All five threat-register rows for this plan are now dispositioned as
planned.

## Out of Scope (WR-03 execution)

CR-02, WR-01, WR-04, WR-06, WR-08 — not looked at, not opportunistically fixed. The three
already-completed tasks (CR-03, CR-01 residual, WR-05) were not revisited; their files are
byte-unchanged by `95b2929c`. No docs artifacts (SUMMARY.md, STATE.md, PLAN.md) were committed —
left for the orchestrator. ROADMAP.md not updated.

## Self-Check (WR-03): PASSED

- `itrader/venues/okx_plugin.py` and `tests/unit/venues/test_okx_plugin.py` exist on disk and are
  the only two files in `git show --name-only 95b2929c`.
- Commit `95b2929c` resolves in `git log`; HEAD is `95b2929c`.
- Working tree clean apart from this untracked `.planning/quick/` directory.
