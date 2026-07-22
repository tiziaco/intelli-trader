---
phase: quick-260722-g6w
plan: 01
subsystem: live-composition-root, venue-credentials
tags: [security, multi-venue, credentials, code-review-blocker]
status: complete
requires:
  - Phase 11 (MPORT-01..07) multi-portfolio-live composition root
provides:
  - venue-scoped account derivation and venue-account attach (CR-01)
  - per-account credential completeness gate at the OKX connector build (CR-05)
affects:
  - itrader/trading_system/live_trading_system.py
  - itrader/venues/okx_plugin.py
tech-stack:
  added: []
  patterns:
    - required keyword-only venue_name threaded through the composition-root helpers
    - credential-model required-field set DERIVED from pydantic model_fields (anti-drift)
key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - itrader/venues/okx_plugin.py
    - tests/integration/test_multi_account_composition.py
    - tests/integration/test_distinct_account_invariant.py
    - tests/unit/venues/test_okx_plugin.py
decisions:
  - "CR-01: the lifecycle map stays keyed by bare account_id — assemble_venues is single-venue by construction, so the behavioural fix is the venue FILTER, not the key shape"
  - "CR-01: venue resolution is `venue_name or exchange`, so a LEGACY add_portfolio(name, 'okx', cash) portfolio is not stripped as foreign"
  - "CR-01: guard ORDER — the venue check precedes the lifecycle lookup so the same-venue fail-loud refusal is preserved unchanged"
  - "CR-05: the required-field set is derived by CLASS access to OkxSettings.model_fields, not a hardcoded triple, so the gate cannot drift from the model"
  - "CR-05: the settings' env source is deliberately NOT suppressed — init kwargs already outrank it, and suppression would strip sandbox/region and silently flip an EEA production account to the global/sandbox defaults"
metrics:
  duration: ~35min
  completed: 2026-07-22
---

# Quick Task 260722-g6w: Fix Code-Review Blockers CR-01 + CR-05 Summary

Closed two Phase 11 code-review BLOCKERS as two atomic commits: the live composition root
now scopes both its account derivation and its venue-account attach to the booted venue
(CR-01), and `OkxConnectorPlugin.build` refuses an incomplete per-account credential set
rather than silently completing the auth triple from the ambient process environment
(CR-05).

## What Was Built

| Blocker | Commit | Files |
|---------|--------|-------|
| CR-01 — cross-venue account conflation | `5fcf476e` | `live_trading_system.py`, `test_multi_account_composition.py`, `test_distinct_account_invariant.py` |
| CR-05 — ambient credential bleed | `47a0e185` | `okx_plugin.py`, `test_okx_plugin.py` |

### CR-01

- New shared `_venue_of(portfolio)` helper resolving `venue_name or exchange` (both via
  `getattr`, since the callers duck-type over live `Portfolio` objects, spec rows and test
  fakes). An unresolvable venue is treated as FOREIGN.
- `_account_ids_for_spec` gained a **required keyword-only `venue_name`**; only the
  REHYDRATED half of the union is filtered (spec portfolios carry no venue and belong to
  the booted venue by definition — the same premise `assert_distinct_accounts` documents).
  Ordering, de-duplication and the `[None]` single-account shape are unchanged.
- `_attach_venue_accounts` gained the same required keyword and a venue guard placed
  **after** the `account_id` falsy-skip and **before** the `lifecycles.get` lookup, with a
  debug log naming the portfolio, its venue and the booted venue.
- `_build_account_specs` threads its existing `exchange` argument through (no signature
  change), and the single production call site passes `venue_name=exchange`.
- 8 existing test call sites updated + `venue_name`/`exchange` added to the
  `SimpleNamespace` portfolio fakes so they keep exercising the branches they were
  written for.

### CR-05

- A completeness gate between `self._resolver.resolve(...)` and the
  `OkxConnector(OkxSettings(**resolved))` construction, over the required-field set
  derived by CLASS access to `OkxSettings.model_fields`.
- Raises `CredentialResolutionError` naming which required fields resolved, which are
  missing, and the `secret_ref` pointer — **field names only**.
- The `CredentialResolutionError` import lives inside the method body, matching the
  existing in-body imports, so the GATE-01 module-scope inertness AST gate stays green.
- The `secret_ref is None` legacy ambient arm is byte-identical.

## Pre-Fix RED Evidence

Both defects passed a fully green suite before this task — which is exactly why every
test below was run against the unmodified source first.

### CR-01 — the new tests, at the signature level

```
E       TypeError: _account_ids_for_spec() got an unexpected keyword argument 'venue_name'
tests/integration/test_multi_account_composition.py:157: TypeError
E       TypeError: _attach_venue_accounts() got an unexpected keyword argument 'venue_name'
tests/integration/test_multi_account_composition.py:566: TypeError
FAILED ...::test_a_foreign_venue_portfolio_contributes_no_account_to_this_venues_set
FAILED ...::test_a_foreign_venue_portfolio_is_never_given_this_venues_account
2 failed, 17 deselected in 0.92s
```

A signature `TypeError` proves the parameter is absent, **not** that the behaviour is
wrong. So the defect itself was demonstrated with a throwaway probe calling the
unmodified venue-blind signatures positionally:

```
DERIVATION (booted venue = okx, one BINANCE rehydrated portfolio):
  expected: [None]
  actual:   ['main']

ATTACH (booted venue = okx, one BINANCE portfolio, OKX 'main' lifecycle):
  expected minted:               {}
  actual minted:                 {'main': <object object at 0x10c2d0bb0>}
  expected portfolio.account:    the sentinel it came in with
  actual  portfolio.account is sentinel: False
  actual  portfolio.account is OKX marker: True
```

### CR-01 — the boot-level (Postgres) test

Docker **was** available, so this arm **ran** — it was not skipped. To prove it was
genuinely RED rather than merely green-after-the-fact, the venue guard was temporarily
neutralized (`if False and portfolio_venue != venue_name:`) and the test re-run:

```
>           assert not isinstance(portfolio.account, VenueAccount)
E           AssertionError: assert not True
E            +  where True = isinstance(<itrader.portfolio_handler.account.venue.VenueAccount object at 0x119236270>, <class '...VenueAccount'>)
E            +    where <...VenueAccount object...> = Portfolio-d3655d7f-7666-4280-a0ca-8f87c9d3c1d8[active].account
tests/integration/test_distinct_account_invariant.py:459: AssertionError
FAILED ...::test_a_binance_portfolio_does_not_receive_the_okx_venue_account
```

The `binance` portfolio really was holding an OKX `VenueAccount`. The guard was restored
immediately and the file re-run green; the neutralization was never committed.

### CR-05

```
>       with pytest.raises(CredentialResolutionError) as caught:
E       Failed: DID NOT RAISE <class 'itrader.core.exceptions.credential.CredentialResolutionError'>
tests/unit/venues/test_okx_plugin.py:387: Failed
FAILED ...::test_okx_connector_plugin_refuses_a_partial_per_account_credential_prefix
1 failed, 2 passed, 23 deselected in 0.80s
```

And the bleed itself, demonstrated against the unmodified plugin:

```
secret_ref resolved ONLY api_key for prefix OKX_ACCT_B; connector built anyway:
  api_key        = acct-b-key               <- per-account (correct)
  api_secret     = AMBIENT-SECRET-VALUE     <- AMBIENT BLEED
  api_passphrase = AMBIENT-PASSPHRASE-VALUE <- AMBIENT BLEED
```

**Reported honestly:** of the three CR-05 tests, only
`test_okx_connector_plugin_refuses_a_partial_per_account_credential_prefix` is a
behavioural RED. The other two passed pre-fix **by design** and are labelled as such in
their docstrings — `test_a_complete_per_account_prefix_beats_the_ambient_environment`
*gates the premise the fix rests on* (init kwargs outrank the env source) rather than
assuming it, and `test_the_credential_gate_covers_every_required_okx_settings_field` is
the anti-drift assertion. Neither is claimed as proof of the defect.

## Verification

| Gate | Result |
|------|--------|
| `poetry run pytest tests` | **2819 passed, 6 skipped** |
| SMA_MACD oracle | byte-exact — `trade_count = 134`, `final_equity = 46189.87730727451` |
| `tests/integration/test_okx_inertness.py` | green (4 passed) |
| `poetry run mypy` | `Success: no issues found in 281 source files` |
| Commits | exactly 2, one per blocker |
| Files touched | exactly the 5 planned; nothing under `reconcile/`, `migrations/` or `tests/golden/` |

The 6 skips are all pre-existing opt-in live-demo OKX suites that skip when demo
credentials are absent from the ambient environment (`test_okx_dynamic_universe.py`,
`test_okx_sandbox_recon.py` ×3, `test_okx_connectivity.py`, `test_okx_smoke.py`). They are
unrelated to this task and skip identically at the parent commit.

`tests/golden/` was not touched by either commit (last golden-touching commits are
`26b914e3` and `88390d85`, both long predating this task).

## Deviations from Plan

### Auto-fixed / plan-refined

**1. [Rule 2 — missing critical coverage] Added a third CR-05 test the plan did not enumerate**

- **Found during:** Task 2
- **Issue:** The plan offered a *conditional* fallback ("if class-level `model_fields` is
  unusable under `mypy --strict` or the warnings filter, fall back to a module-level
  frozenset AND add a test asserting the literal equals the model's required set"). Class
  access turned out to work fine under both (verified with `python -W error`), so the
  fallback was not needed — but the *anti-drift property* the fallback's test was meant to
  protect is worth pinning regardless.
- **Fix:** Added `test_the_credential_gate_covers_every_required_okx_settings_field`,
  asserting the required set is exactly `{api_key, api_secret, api_passphrase}` and
  excludes `sandbox`/`region`.
- **Commit:** `47a0e185`

**2. [Rule 2] Extended CR-01 Test 1 with a LEGACY-venue companion assertion**

- **Found during:** Task 1
- **Issue:** The plan's action text correctly requires reading `venue_name or exchange`
  (correction 3), but the behaviour it specified for Test 1 only covered the foreign and
  same-`venue_name` cases. Nothing would have caught a fix that read `venue_name` alone
  and silently stripped every legacy live portfolio's venue account — a regression worse
  than the defect.
- **Fix:** Test 1 now also asserts a portfolio with `venue_name=None, exchange='okx'` IS
  included.
- **Commit:** `5fcf476e`

**3. [refinement] Introduced a shared `_venue_of` helper**

- **Found during:** Task 1
- **Issue:** The plan describes the identical venue-resolution rule in two functions
  without naming a home for it; two hand-written copies is how the two drift apart.
- **Fix:** One module-level `_venue_of(portfolio)` helper, called by both.
- **Commit:** `5fcf476e`

### Plan claims confirmed against the code

Every factual claim in the plan and the orchestrator brief was verified against the
source before implementing, and **all held**:

- `_account_ids_for_spec` unioned bare id strings with no venue read; `_attach_venue_accounts`
  did a venue-blind `lifecycles.get(account_id)`.
- `assemble_venues` keys on `spec.account_id or 'default'` (`venues/assemble.py:179`) and is
  called once per boot over specs that all share `exchange` — the map **is** single-venue by
  construction. It was **not** re-keyed.
- `Portfolio.venue_name` exists at `portfolio.py:111` with `self.exchange` derived at `:112`.
- The 8 test call sites were exactly where the brief said.
- `OkxSettings.model_fields` required set is exactly `{api_key, api_secret, api_passphrase}`;
  `sandbox` and `region` carry defaults.
- `okx_plugin.py` is 4-space; `live_trading_system.py` is 4-space. Zero tab-indented lines
  added to either (verified on the diff, not on the whole file).

No plan claim had to be overridden.

## Deliberately Left Alone (per scope)

- **WR-03** — the normalization asymmetry between the registration write
  `exchanges[(exchange, account_spec.account_id or DEFAULT_ACCOUNT_ID)]`
  (`live_trading_system.py:2001-2003`, now `:2088`-ish after the docstring growth) and the
  raw `exchanges.get((venue_name, portfolio.account_id))` read in
  `reconciliation_coordinator.py:218-220`. Both halves are byte-identical to before.
- **CR-02, CR-03, CR-04** and every other WR-* finding.

## Observations (NOT fixed — noted only)

- **The `docs/webapp-design-prompt.md` working-tree modification is pre-existing.** It was
  already `M` in `git status` before this task began and was never staged or committed here.
- **`_attach_venue_accounts`'s foreign-venue skip is debug-only.** A boot that silently
  attaches nothing to a foreign-venue portfolio leaves that portfolio on its simulated leaf
  with `is_venue_truth` False — correct for this fix, but invisible on `get_status()`. That
  observability gap is CR-02/WR-06 territory (threat register `T-g6w-05`, disposition
  *accept*), so it was left as a debug log per the plan.
- **A foreign-venue portfolio is now rehydrated but functionally inert.** After this fix a
  persisted `binance` portfolio on an `okx` boot comes back with a compute leaf and no venue
  account. That is strictly safer than the pre-fix conflation, but whether such a portfolio
  should be rehydrated at all on a single-venue boot is a product question this task did not
  answer.

## Self-Check: PASSED

- `itrader/trading_system/live_trading_system.py` — FOUND
- `itrader/venues/okx_plugin.py` — FOUND
- `tests/integration/test_multi_account_composition.py` — FOUND
- `tests/integration/test_distinct_account_invariant.py` — FOUND
- `tests/unit/venues/test_okx_plugin.py` — FOUND
- commit `5fcf476e` — FOUND
- commit `47a0e185` — FOUND
