---
phase: 11-multi-portfolio-live
plan: 07
subsystem: venue-accounts
tags: [MPORT-01, MPORT-06, D-10, D-11, D-12, accounts, credentials, composition-root]
requires:
  - "11-04: CredentialResolver + VenueSpec.secret_ref (shipped dormant; made live here)"
  - "11-05: PortfolioSpec.account_id / Portfolio.account_id"
  - "11-06: pair-keyed ExecutionHandler.exchanges + account-resolving on_order"
provides:
  - "VenueAccount(connector, *, account_id) — required keyword, no default (D-11 guard)"
  - "VenuePlugin.new_account(portfolio_ref, config) + VenueAccountConfig (D-10)"
  - "per-account bundles/connectors/exchanges through build_live_system (MPORT-01)"
  - "per-account secret_ref reads — MPORT-06 is live, not dormant"
  - "venue_accounts row minting, gated on absence"
  - "tests/integration/test_multi_account_composition.py — the MPORT-01/06 gate"
affects:
  - "itrader/venues/bundle.py, okx_plugin.py, paper_plugin.py"
  - "itrader/portfolio_handler/account/venue.py"
  - "itrader/trading_system/live_trading_system.py"
tech-stack:
  added: []
  patterns:
    - "required-keyword-with-no-default as a structural guard (not a Protocol method)"
    - "thin adapter field delegating to a typed Protocol method — one implementation, no drift"
    - "mint-on-absence against a delete-then-insert upsert"
key-files:
  created:
    - tests/unit/portfolio/test_account_venue.py
    - tests/integration/test_multi_account_composition.py
  modified:
    - itrader/venues/bundle.py
    - itrader/venues/okx_plugin.py
    - itrader/venues/paper_plugin.py
    - itrader/portfolio_handler/account/venue.py
    - itrader/trading_system/live_trading_system.py
    - "tests/unit/venues/ (registry, okx_plugin, paper_plugin, venue_uid_guard)"
    - "15 further test files — 32 VenueAccount call sites migrated"
decisions:
  - "account_factory is RETAINED as a thin adapter over new_account rather than replaced, because live_trading_system.py:196 is its only production call site and its deletion belongs to 11-07b. Delegation means there is one minting implementation, so the field and the Protocol method cannot drift."
  - "new_account resolves the account id from the portfolio when one is supplied and from the bundle config only when none is — NO cross-fallback. A fallback from an unnamed portfolio to the bundle's account would look harmless and silently attach that portfolio to whichever account the bundle happens to be for."
  - "Paper's new_account requires no account_id. D-11 scopes VENUE accounts, whose truth is one real venue account's; a simulated leaf computes its own truth from its own portfolio, so an id would push a venue concept onto the byte-exact oracle path for no safety gain."
  - "VenueAccountConfig lives in bundle.py, not paper_plugin.py — that module has a test-enforced single-class gate."
  - "Account-row minting is gated on absence because upsert is delete-then-insert; an unconditional mint would clobber an operator's configured secret_ref on every boot."
  - "Every non-primary exchange/connector gets the primary's halt wiring (Rule 2 addition). Registering a second exchange without it leaves a partially-halted engine whose surviving arm looks healthy."
metrics:
  duration: ~95 min
  tasks: 2
  files: 25
  tests_added: 26
  suite: "2741 passed / 6 skipped (baseline 2715 / 6)"
  completed: 2026-07-21
status: complete
---

# Phase 11 Plan 07: Per-Account Accounts — BUILD, WIRE, MINT Summary

Made an unscoped venue account inexpressible (`account_id` is a required keyword with no
default), promoted account construction onto the `VenuePlugin` Protocol, and — the point of
the plan — wired the composition root to assemble one bundle, one connector and one exchange
**per account**, so `new_account` has a production caller and 11-04's credential resolver
stops being dormant.

## What shipped

**Task 1 — the guard, the Protocol method, both arms (`58a5d5a3`)**

`VenueAccount.__init__` gained `account_id` as a required keyword-only parameter with no
default. That signature is the guard, not the Protocol method: a catch-all `(*args, **kwargs)`
arm satisfies any Protocol member under strict typing and `VenuePlugin` is structural, so an
arg-swallowing arm would have type-checked clean. An explicit `None`/`""` is separately
rejected with a typed `ValidationError`, because a required keyword-only parameter does *not*
reject an explicit `None` — and `account_id` is `Optional[str]` on both the portfolio and the
venue spec, so a bare pass-through of an unset field arrives as `None`.

`VenuePlugin` gained `new_account(portfolio_ref, config)` alongside the frozen
`VenueAccountConfig`. The OKX catch-all factory arm — which absorbed a portfolio argument and
returned one shared account with no error — is gone. Both arms implement `new_account`, and
`account_factory` is retained only as a thin adapter over it. Paper's leaf selection is the
pre-11-07 body verbatim (the byte-exact oracle path).

**Task 2 — the wiring (`76474865`)**

`build_live_system` now derives the account set from the portfolio specs and loops:
`_build_account_specs` → `assemble_venue` per account → one pair-keyed registration per
account. The spec-level account is the deterministic primary and owns the facade's single
`VenueLifecycle` and the one data provider wired to the feed. `N=1` runs the same loop with
one element — deliberately not a second branch.

MPORT-06 moves from dormant to live because the credential pointer is now read **per account**
rather than once for a single spec-level account. `_mint_account_rows` ensures each account has
a `venue_accounts` row so the D-04 venue-UID guard (`record_venue_uid` is a targeted UPDATE and
a silent no-op with no matching row) has somewhere to write.

## Mutation testing

Every gate was mutation-tested before being banked. **No gate was green with its deliverable
absent**, and none was already green before the change.

| # | Mutation | Result |
|---|----------|--------|
| 1 | `VenueAccount.account_id` gains a default | RED — `test_constructing_without_an_account_id_raises_type_error` |
| 2 | remove the explicit-`None` guard | RED — 2 tests (`None` + empty-string) |
| 3 | unnamed portfolio falls back to the bundle's account | RED — `test_new_account_for_a_portfolio_naming_no_account_raises` |
| 4 | `account_factory` ignores the portfolio (old shared-account shape) | RED — `test_bundle_account_factory_delegates_to_new_account` |
| A | loop assembles only the primary account | RED — `test_two_accounts_produce_two_exchanges_over_two_connectors` |
| B | `secret_ref` read once for the spec-level account (MPORT-06 dormant again) | RED — 2 tests, incl. the resolved-credential gate |
| C | minting made unconditional (the clobber) | RED — 3 tests |
| D | minting removed entirely | RED — `test_an_absent_account_row_is_minted_so_the_uid_guard_has_a_home` |

Each mutation was reverted to an empty diff and re-verified before proceeding.

## Plan drift found

The plan is accurate on the decisions; several factual claims about the code were stale.

1. **`Portfolio.account` is NOT settable from the composition root, and `build_live_system`
   creates no portfolios at all.** `Portfolio._initialize_components` constructs its own
   simulated leaf; live portfolios are added by the application *after* boot
   (`system.portfolio_handler.add_portfolio(...)`) or rehydrated. The plan's acceptance
   criterion "each `Portfolio.account` is a distinct `VenueAccount`" is therefore not
   satisfiable at composition time — there is no portfolio to attach an account to yet, and no
   injection seam. **Attaching minted accounts to portfolios is a real remaining gap and
   belongs with 11-08's rehydrate/invariant work.** What this plan delivers instead is the
   per-account *bundle/connector/exchange/account minting* the attachment will consume.

2. **`len(execution_handler.exchanges) == 2` is the wrong assertion.** The registry also holds
   the compose-built `('simulated', 'default')` and `('csv', 'default')` entries, so a bare
   length check counts unrelated rows. The gate filters by venue half and asserts exactly two
   OKX entries.

3. **11-06 left no "placeholder comment" to remove.** The registration site already used
   `venue_spec.account_id or DEFAULT_ACCOUNT_ID` — the real account id. Task 1 Step 4's
   "register under the real account id rather than the default constant" was already done.

4. **The second `build_venue_spec` at `:296` does NOT need the account loop** (the audit asked
   for a finding either way). It is inside `LiveTradingSystem.for_exchange`, the ergonomic
   single-account entry point, and produces a `VenueSpec` — which carries no `portfolios`, so
   `_account_ids_for_spec` returns the single-account list and the N=1 path runs unchanged. A
   test pins this.

5. **Only ONE Protocol fake actually broke**, not two. `test_registry.py::_FakeVenuePlugin`
   failed its `isinstance` assertion as predicted. `test_venue_uid_guard.py`'s `_FakePlugin`
   and its subclasses are duck-typed by the guard (`credential_model` / `fetch_venue_uid`
   read directly) and are never `isinstance`-checked, so they did not break. `new_account`
   was added there anyway for conformance hygiene, with a comment saying so.

6. **32 `VenueAccount(` construction sites across 15 test files**, not 34 across 16. The
   plan's count included `itrader/venues/okx_plugin.py` and matched
   `tests/integration/test_live_portfolio_durable_wiring.py`, whose only occurrence is a
   `_StubVenueAccount` (substring match, not a real construction).

## Deviations from Plan

**1. [Rule 2 — missing critical functionality] Halt-signal wiring for non-primary exchanges**

- **Found during:** Task 2
- **Issue:** The plan specifies registering each account's exchange but not wiring it. The
  existing halt/stream-state wiring is written against the single primary exchange and
  connector, so a second account's exchange would be registered and routable while remaining
  deaf to `_request_connector_halt`.
- **Why it is Rule 2 and not scope creep:** a connector-fatal halt would latch the primary and
  leave the secondary account accepting and submitting orders, with nothing reporting that
  half the venue is still live. A partially-halted engine is a worse failure than the
  single-account engine it replaced.
- **Fix:** every non-primary bundle's exchange and connector receives the same halt signal and
  stream-state listeners. Gated by `test_every_accounts_exchange_is_wired_to_the_halt_signal`.
- **Files:** `itrader/trading_system/live_trading_system.py`
- **Commit:** `76474865`

**2. [Rule 1 — bug avoided] Minting gated on absence**

- **Found during:** Task 2, reading `VenueAccountStore.upsert` before using it.
- **Issue:** The plan says "mint the `venue_accounts` row for each account". `upsert` is a
  delete-then-insert over the composite key, so minting unconditionally would overwrite an
  operator's configured `secret_ref` and the recorded `venue_uid` on **every boot** — silently
  reverting per-account credentials to the ambient single-account path while the system keeps
  running, authenticated as the wrong account.
- **Fix:** mint only when `get()` returns `None`. Mutation C confirms the gate catches the
  unconditional form.
- **Files:** `itrader/trading_system/live_trading_system.py`
- **Commit:** `76474865`

**3. [Scope, per the restructure] Nothing deleted, D-26 rename dropped**

Per the approved 2026-07-21 restructure, no deletion was performed and the spec-field rename
was not attempted. Verified: `_venue_account` occurs 6 times in `live_trading_system.py`
(identical to the base commit), and `_link_venue_account_to_portfolios` and its
`RuntimeError(>1)` guard are untouched. The two D-26 deferral todos were **not** written —
they belong with the rename, which was dropped.

## Known limitations

- **Minted accounts are not yet attached to portfolios.** See drift item 1. The engine now
  produces a correctly-scoped account per account id, but nothing assigns it to a
  `Portfolio.account`; live portfolios still carry their simulated leaf until the
  reconciliation coordinator links a venue account. This is the pre-existing behaviour, not a
  regression, and is the natural seam for 11-08/11-09.
- **The MPORT-06 credential gate constructs its `VenueAccountStore` in the test**, because
  `build_live_system`'s SQL arm requires Postgres and is unreachable offline.
  `_build_account_specs` — the production function `build_live_system` calls — is exercised
  unmodified; only the store's provisioning is test-side. The two-exchange/two-connector gate
  drives the real `build_live_system` end to end with no stubbing.
- **The shared resting-order-book question** (flagged in the plan as an open question for two
  paper portfolios on one matching engine) was **not** investigated — it belonged to the
  plan's Task 3, which the restructure removed along with the deletions. It remains open and
  must be answered before the W7 lifecycle test.

## Verification

| Gate | Result |
|------|--------|
| `pytest tests -q` | 2741 passed / 6 skipped (baseline 2715 / 6) |
| `pytest tests/integration/test_backtest_oracle.py -q` | pass (byte-exact) |
| `pytest tests/integration/test_okx_inertness.py -q` | pass |
| `mypy` | Success, 256 source files |
| `grep -c '_venue_account' live_trading_system.py` | 6 — unchanged from base |
| `_link_venue_account_to_portfolios` | present, untouched |
| `grep -cE 'def account_factory\(\*args' okx_plugin.py` | 0 |
| `grep -c 'account_id' account/base.py` | 0 |
| new module-top imports in either plugin | 0 |
| tab-indented added lines in 4-space files | 0 |
| `pyproject.toml` / `poetry.lock` changed | no |

`mypy` was confirmed to actually read the worktree sources (not the `.venv` editable-install
shadow) by injecting a deliberate type error and observing it reported in both the mutated
file and a downstream consumer.

## Self-Check: PASSED

- `itrader/venues/bundle.py` — FOUND (`def new_account`, `VenueAccountConfig`)
- `itrader/portfolio_handler/account/venue.py` — FOUND (required keyword `account_id`)
- `tests/unit/portfolio/test_account_venue.py` — FOUND
- `tests/integration/test_multi_account_composition.py` — FOUND
- `58a5d5a3` — FOUND
- `76474865` — FOUND
- `.planning/todos/pending/data-provider-connector-account-model.md` — NOT created, and
  deliberately so: it is the D-26 deferral todo, and the D-26 rename was dropped by the
  approved restructure.
