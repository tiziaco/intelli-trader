---
phase: 11-multi-portfolio-live
reviewed: 2026-07-22T00:00:00Z
depth: standard
files_reviewed: 87
files_reviewed_list:
  - itrader/config/credential_resolver.py
  - itrader/config/okx_settings.py
  - itrader/core/exceptions/__init__.py
  - itrader/core/exceptions/credential.py
  - itrader/core/exceptions/portfolio.py
  - itrader/core/portfolio_read_model.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/execution_handler/exchanges/venue_correlation.py
  - itrader/execution_handler/execution_handler.py
  - itrader/execution_handler/matching_engine.py
  - itrader/portfolio_handler/account/conformance.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/reconcile/reconciliation_coordinator.py
  - itrader/portfolio_handler/rehydrate/__init__.py
  - itrader/portfolio_handler/rehydrate/distinct_account_invariant.py
  - itrader/portfolio_handler/rehydrate/portfolio_rehydrate.py
  - itrader/portfolio_handler/storage/cached_sql_storage.py
  - itrader/portfolio_handler/storage/models.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/storage/portfolio_definition_store.py
  - itrader/storage/strategy_registry_store.py
  - itrader/storage/venue_account_store.py
  - itrader/strategy_handler/lifecycle/manager.py
  - itrader/strategy_handler/registry/rehydrate.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/safety/stream_recovery_handler.py
  - itrader/trading_system/system_spec.py
  - itrader/trading_system/universe_wiring.py
  - itrader/trading_system/venue_spec.py
  - itrader/venues/assemble.py
  - itrader/venues/bundle.py
  - itrader/venues/lifecycle.py
  - itrader/venues/okx_plugin.py
  - itrader/venues/paper_plugin.py
  - itrader/venues/venue_uid_guard.py
  - migrations/env.py
  - migrations/versions/p11_b2_uuid_fk_config_move.py
  - migrations/versions/p11_venue_accounts_portfolios.py
  - tests/e2e/test_okx_sandbox_recon.py
  - tests/integration/conftest.py
  - tests/integration/storage/test_cached_sql_portfolio_storage.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/test_config_restart_layering.py
  - tests/integration/test_distinct_account_invariant.py
  - tests/integration/test_early_durable_halt_refusal.py
  - tests/integration/test_live_portfolio_durable_wiring.py
  - tests/integration/test_live_system_okx_wiring.py
  - tests/integration/test_multi_account_composition.py
  - tests/integration/test_multi_portfolio_lifecycle.py
  - tests/integration/test_okx_inertness.py
  - tests/integration/test_p11_migration_chain.py
  - tests/integration/test_per_account_exchange_routing.py
  - tests/integration/test_portfolio_definition_writer.py
  - tests/integration/test_resume_gated_on_all_streams.py
  - tests/integration/test_resume_missed_fill_catchup.py
  - tests/integration/test_strategy_add_warmup.py
  - tests/integration/test_strategy_external_add_lifecycle.py
  - tests/integration/test_strategy_registry_restart.py
  - tests/support/schema.py
  - tests/support/strategy_catalog.py
  - tests/unit/config/test_credential_resolver.py
  - tests/unit/core/test_portfolio_read_model.py
  - tests/unit/execution/test_off_loop_halt_write.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/execution/test_okx_fill_idempotency.py
  - tests/unit/execution/test_reconnect_resilience.py
  - tests/unit/execution/test_venue_correlation.py
  - tests/unit/portfolio/test_account_venue.py
  - tests/unit/portfolio/test_portfolio_identity.py
  - tests/unit/portfolio/test_portfolio_rehydrate.py
  - tests/unit/portfolio/test_reconciliation_coordinator.py
  - tests/unit/storage/test_portfolio_definition_store.py
  - tests/unit/storage/test_strategy_registry_store.py
  - tests/unit/storage/test_venue_account_store.py
  - tests/unit/strategy/test_rehydrate.py
  - tests/unit/strategy/test_strategy_command_verbs.py
  - tests/unit/trading_system/test_stream_recovery_handler.py
  - tests/unit/trading_system/test_system_spec.py
  - tests/unit/venues/test_assemble.py
  - tests/unit/venues/test_okx_plugin.py
  - tests/unit/venues/test_paper_plugin.py
  - tests/unit/venues/test_registry.py
  - tests/unit/venues/test_venue_uid_guard.py
findings:
  critical: 5
  warning: 12
  info: 0
  total: 17
status: issues_found
resolution:
  audited_at: 2026-07-22
  closed: 3
  deferred: 14
  closed_by:
    - "CR-01, CR-05 — quick task 260722-g6w (5fcf476e, 47a0e185)"
    - "WR-08 — quick task 260722-hpz (59eb44e3)"
  deferred_to: "Phase 11.1 (ACCT-01..11) + its discuss-phase"
  do_not_autofix: >-
    Do NOT run /gsd-code-review 11 --fix against this report. It has no finding-ID
    filter and scopes by severity only, so it would autonomously implement CR-02,
    CR-03 and CR-04 — the three findings whose fix is a deliberate product/architecture
    decision already recorded in the Phase 11.1 spec.
---

# Phase 11: Code Review Report

**Reviewed:** 2026-07-22
**Depth:** standard
**Files Reviewed:** 87 (42 source + 45 test)
**Status:** issues_found — **3 CLOSED / 14 DEFERRED as of 2026-07-22** (see Resolution Status below)

> **⚠ Do not run `/gsd-code-review 11 --fix` against this report.** The fix workflow scopes by
> SEVERITY only (`critical_and_warning`, or `--all` to add Info) — there is no finding-ID filter.
> It would autonomously implement CR-02, CR-03 and CR-04, whose fixes are deliberate
> product/architecture decisions already made and recorded in the Phase 11.1 spec. The 14 deferred
> findings are scheduled work, not unaddressed ones.

---

## Resolution Status (audited 2026-07-22)

The two findings needing no product decision were fixed ahead of Phase 11.1; the one finding
independent of account identity was fixed as a standalone task; the remaining 14 are scheduled into
**Phase 11.1 — Account Provisioning + Mandatory Account Identity** (`ACCT-01..11`), whose root
decision — *`(venue_name, account_id)` is mandatory for a live portfolio, and the durable store, not
the spec, is the source of truth* — is what most of them were blocked on.

| ID | Verdict | Disposition |
|----|---------|-------------|
| **CR-01** — cross-venue account conflation | **CLOSED** | Quick task `260722-g6w` (`5fcf476e`). `_account_ids_for_spec` / `_attach_venue_accounts` take a required keyword-only `venue_name` and skip portfolios whose venue is not the booted one; venue resolved as `venue_name or exchange` so legacy portfolios are not stripped. RED reproduced pre-fix: derivation returned `['main']` for a binance portfolio on an okx boot, `[None]` after. The lifecycle map was deliberately NOT re-keyed to a pair — `assemble_venues` keys by `spec.account_id or 'default'` and every spec in one call shares `exchange`, so it is single-venue by construction. |
| **CR-02** — account-less live portfolio loses every venue safety gate | **DEFERRED → ACCT-03** | Decision made 2026-07-22: **hard-raise**, not per-portfolio quarantine — unlike a dark strategy, an unattached portfolio still routes orders. |
| **CR-03** — post-boot `add_portfolio` never attaches an account | **DEFERRED → ACCT-05** | Re-scoped upward: under DB-as-source-of-truth this is the PRIMARY creation path, not an edge case. On a fresh DB nothing rehydrates, so the first `add_portfolio` is how every portfolio is born. |
| **CR-04** — D-09 config move is a guaranteed no-op | **DEFERRED → ACCT-11** | Confirmed greenfield 2026-07-22 (no deployment holds real persisted state), so this collapses from a data migration to a guard against a state that should never arise: count orphans and refuse. |
| **CR-05** — partial per-account credentials mix with the ambient set | **CLOSED** | Quick task `260722-g6w` (`47a0e185`). `OkxConnectorPlugin.build` gates on `OkxSettings`' required field set (verified = exactly the auth triple) before construction and raises `CredentialResolutionError` naming missing FIELD NAMES only. The env source is deliberately NOT suppressed — init kwargs already outrank it, and suppression would strip `sandbox`/`region` and silently flip a configured EEA account to global+sandbox (OKX 50119). RED: `DID NOT RAISE`, with a probe showing the connector carrying the ambient secret. |
| **WR-01** — `save_config` raises for portfolios `_persist_definition` skips | **DEFERRED → ACCT-07** | ACCT-03 makes the early-return unreachable, which resolves the disagreement at its root. |
| **WR-02** — one bad portfolio config aborts layering for the rest | **DEFERRED → ACCT-08** | Folded there because WR-02 and ACCT-08 edit the SAME statement (`live_trading_system.py:1341`). |
| **WR-03** — registration and resolution normalize the key differently | **DEFERRED → ACCT-04** | Sharpened during the 2026-07-22 discussion: it is not merely an asymmetry. Both readers construct `(venue, None)` raw, so for an unnamed account the registered `(venue,'default')` key is unreachable by every reader — a write-only entry. Dissolves when the 6 live-path coercions are deleted. |
| **WR-04** — `enabled` is write-once-`True` | **DEFERRED → ACCT-10** | Decision made 2026-07-22: **persist deactivation** via `PortfolioDefinitionStore.set_enabled`, so a stopped portfolio does not resume trading on the next boot. |
| **WR-05** — minting + secret-ref read compose into an ambient-credential fallback | **DEFERRED → ACCT-02** | Dies with `_mint_account_rows`, which writes `secret_ref=None` and is the root of the fail-open composite. |
| **WR-06** — the D-04 spoofing guard has five paths to silent inertness | **DEFERRED → 11.1 discussion** | A genuine open choice, not a consequence. Recorded lean: fold only the `venue_uid_guard_active` status flag; defer the alert-sink rerouting so the phase does not double in size. |
| **WR-07** — non-primary accounts build unwired data providers | **DEFERRED → 11.1 discussion** | Open choice: build providers for the primary only, or wire halt-signal / stream-state listeners on all. Depends on whether multi-account data streams are on the roadmap. |
| **WR-08** — teardown drives only the first lifecycle | **CLOSED** | Quick task `260722-hpz` (`59eb44e3`). `stop()` snapshots `_venue_lifecycles.items()` before the `try` and loops in the `finally`, with per-iteration `try/except` at the call site (not inside `VenueLifecycle.stop()`, which must keep raising for its own callers). Safe because `close_all()` clears its memo in a `finally` — idempotency independently verified. RED: exactly 3 failed / 99 passed pre-fix. |
| **WR-09** — three modules reach into `PortfolioHandler._portfolios` | **DEFERRED → ACCT-08** | ACCT-01 and ACCT-05 rewrite two of the four call sites anyway. |
| **WR-10** — `on_order` failures are invisible outside the log | **DEFERRED → ACCT-09** | Scope shrinks under ACCT-03: the `account_id is None` branch becomes unreachable, so this covers two paths and deletes the third. |
| **WR-11** — the flagship multi-portfolio test demonstrates the forbidden shape | **DEFERRED → ACCT-03 (mandatory)** | Not optional: ACCT-03 makes the half-null fixture illegal, so Phase 11.1 cannot go green until it is corrected. Recorded as a gate condition rather than a separate requirement. |
| **WR-12** — the migration tests cannot detect the CR-04 failure mode | **DEFERRED → ACCT-11** | Travels with CR-04; the new test stages ONLY `portfolio_account_state` rows, the real pre-upgrade shape. |

**Next review:** after Phase 11.1 lands, re-run as `11-REVIEW-2.md` and produce a *Prior Finding
Closure Audit* verifying the 14 deferred findings against the then-current code — the
`10.1-REVIEW-2.md` pattern. Verifying closure independently is the point; do not mark them closed
from commit messages.

---

## Summary

Phase 11 delivers per-account venue bundles, durable portfolio definitions, boot-time
rehydrate, and pair-keyed order routing. The pair-keying of `ExecutionHandler.exchanges`
(D-27) is thorough and complete — every call site was converted, the identity-based
`on_market_data` dedup is correctly preserved, and `test_per_account_exchange_routing.py`
gates it with real negatives. `VenueCorrelationIndex`, `VenueAccount`, and the credential
*exception* boundary are careful work.

The multi-portfolio wiring itself is not. The phase repeatedly states that a portfolio's
identity is the PAIR `(venue_name, account_id)` — the store schema, the DB unique
constraint, the connector memo and the exchange registry all honour that. **The composition
root does not.** `_account_ids_for_spec` / `_attach_venue_accounts` key on `account_id`
alone, so the exact cross-venue conflation the phase documents as impossible is reachable
today, and an existing green test (`test_the_same_account_id_on_two_venues_boots`) drives it
without observing it (CR-01).

Three further gaps share one shape: a guard was deleted on the strength of a guarantee
another plan was supposed to provide, and that guarantee was never actually implemented.
`_link_venue_account_to_portfolios` was deleted but `_attach_venue_accounts` skips
account-less portfolios (CR-02); `on_order`'s refusal and `save_config`'s new raise both
cite "plan 11-08 makes account_id mandatory in live", but `assert_distinct_accounts`
explicitly *skips* account-less portfolios (CR-02, WR-01); the attach runs only inside
`build_live_system` while `PortfolioHandler._persist_definition`'s own docstring states live
portfolios are added *after* it returns (CR-03).

Finally, the migration's self-declared "single highest-regression-risk operation" — the D-09
config move — is a provable no-op on any real upgrade, and its test stages a database state
that cannot exist in the production chain (CR-04). And `OkxSettings`' `BaseSettings` nature
reintroduces the ambient-credential fallback at field granularity that the resolver's
fail-loud contract forbids at reference granularity (CR-05).

No Decimal/float violations, no second ID scheme, no determinism leaks, no indentation
mixing, and no eager imports that would break GATE-01 inertness were found.

## Critical Issues

### CR-01: Venue accounts are attached by `account_id` alone — cross-venue conflation

**File:** `itrader/trading_system/live_trading_system.py:1394-1449` (`_account_ids_for_spec`),
`itrader/trading_system/live_trading_system.py:1537-1621` (`_attach_venue_accounts`),
`itrader/trading_system/live_trading_system.py:1502-1534` (`_build_account_specs`)

**Issue:** The whole phase pins identity on the PAIR. `distinct_account_invariant.py:5-8`
states it explicitly: *"The same account-id STRING on two different venues names two
different real accounts and is perfectly legitimate."* `venue_account_store.py` uses a
composite PK, `portfolios` carries a composite FK, `ExecutionHandler.exchanges` is
pair-keyed, and `ConnectorProvider._memo` is pair-keyed.

`_account_ids_for_spec` throws the venue half away. It unions account-id STRINGS from the
spec and from every rehydrated portfolio, regardless of each portfolio's own `venue_name`
(`rehydrate_portfolios` reads `row["venue_name"]` per row, so portfolios on other venues are
routinely in `portfolio_handler._portfolios`). `_build_account_specs` then builds a
`VenueSpec` for the BOOT venue for each of those ids, `_mint_account_rows` writes a
`venue_accounts` row under `(boot_venue, foreign_account_id)`, and `_attach_venue_accounts`
does `lifecycles.get(account_id)` — a venue-blind lookup — and assigns the boot venue's
`VenueAccount` to the foreign-venue portfolio.

Concrete, currently-reachable sequence (this is the data
`tests/integration/test_distinct_account_invariant.py::test_the_same_account_id_on_two_venues_boots`
already seeds):

1. Durable row: portfolio `pf-binance`, `venue_name='binance'`, `account_id='main'`.
2. Boot with `execution_venue='okx'`, spec portfolio naming `account_id='main'`.
3. `assert_distinct_accounts` passes — `('binance','main') != ('okx','main')`. Correct.
4. `_account_ids_for_spec` yields `['main']` (deduped across venues).
5. One OKX lifecycle for `'main'`.
6. `_attach_venue_accounts` assigns the **OKX** `VenueAccount` to the **binance** portfolio.

Consequences, all silent: `ReconciliationCoordinator` snapshots the OKX account and
reconciles it against the binance portfolio's believed positions; `_run_session_baseline_guard`
compares binance engine quantities against OKX venue quantities and can HALT (or, worse, pass
because both happen to be flat) ; `VenueReconciler` emits reconciling `FillEvent`s into the
wrong portfolio; `StreamRecoveryHandler` re-snapshots it on every reconnect. If two portfolios
on two venues share the id, they receive the *same* `VenueAccount` object — literally the
buying-power conflation D-14/D-15 exist to prevent, having passed the invariant that is
supposed to prevent it. The existing test asserts only membership and registry keys, so it
passes.

**Fix:** Key the account set and the lifecycle map on the pair, and refuse/skip portfolios
whose venue is not the one being booted.

```python
def _account_keys_for_spec(spec, exchange, portfolios=()):
    ordered: list[tuple[str, Optional[str]]] = []
    primary = getattr(spec, 'account_id', None)
    if primary is not None:
        ordered.append((exchange, primary))
    for ps in getattr(spec, 'portfolios', None) or ():
        key = (exchange, getattr(ps, 'account_id', None))
        if key[1] is not None and key not in ordered:
            ordered.append(key)
    for portfolio in portfolios:
        venue = getattr(portfolio, 'venue_name', None) or portfolio.exchange
        account_id = getattr(portfolio, 'account_id', None)
        if account_id is None or venue != exchange:
            continue                    # another venue's account — not ours to assemble
        if (venue, account_id) not in ordered:
            ordered.append((venue, account_id))
    return ordered or [(exchange, None)]


def _attach_venue_accounts(portfolio_handler, lifecycles, *, venue_name):
    for portfolio in portfolio_handler._portfolios.values():
        pf_venue = getattr(portfolio, 'venue_name', None) or portfolio.exchange
        if pf_venue != venue_name:
            continue                    # a portfolio on another venue is NOT ours to attach
        ...
```

---

### CR-02: A live portfolio that names no account silently loses the entire venue reconcile and baseline HALT gate

**File:** `itrader/trading_system/live_trading_system.py:1591-1594`,
`itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:222-233` (deleted linker),
`itrader/portfolio_handler/rehydrate/distinct_account_invariant.py:104-120`

**Issue:** Before this phase, `ReconciliationCoordinator._link_venue_account_to_portfolios`
assigned the single `VenueAccount` to the one active portfolio unconditionally — a portfolio
did not need an `account_id` to become venue-truth. That method was deleted. Its replacement,
`_attach_venue_accounts`, opens with:

```python
account_id = getattr(portfolio, 'account_id', None)
if not account_id:
    continue
```

So a live OKX portfolio created the pre-existing way (`add_portfolio(name, 'okx', cash)`, no
`account_id`) keeps the `SimulatedCashAccount` leaf built in `Portfolio._initialize_components`.
`account.is_venue_truth` is then `False`, and `run_startup_reconcile` (`:169-200`) and
`_run_session_baseline_guard` (`:289-292`) both `continue` past it. That silently disables:
`VenueAccount.snapshot()`, `start_streaming()`, `VenueReconciler.reconcile()`, and the D-04
unexplained-residual HALT — i.e. every safety gate that stops the engine trading against venue
exposure it cannot explain. The function's own docstring names this outcome as the thing it
exists to prevent ("never left on its simulated leaf (which would … silently skip the entire
venue reconcile … behind a fully green suite)") and then implements it for the unnamed case.

The compounding half: `ExecutionHandler.on_order` (`execution_handler.py:205-215`) refuses such
an order outright, logging and returning. Both that refusal and this skip cite the same
backstop — *"Plan 11-08 owns the composition-time invariant that makes account_id mandatory in
live"*. That invariant does not exist: `assert_distinct_accounts._claim` explicitly returns
early for `account_id is None` ("the legacy single-account shape … has always been valid"), and
nothing else checks it. The net result for a legacy live deployment is an engine that boots
green, reconciles nothing, halts on nothing, and drops every order with a log line.

**Fix:** Implement the missing composition-time invariant (this is the cheapest correct
option), and make the skip loud rather than silent:

```python
# in build_live_system, beside assert_distinct_accounts
for portfolio in portfolio_handler._portfolios.values():
    if not getattr(portfolio, 'account_id', None):
        raise ValidationError(
            "account_id", "None",
            f"Live portfolio '{portfolio.name}' names no venue account: its orders "
            "cannot be routed and its venue reconcile / baseline HALT guard cannot run.")
```

If the legacy shape must stay supported, it must at minimum log at ERROR in
`_attach_venue_accounts` and be surfaced on `get_status()` the way `quarantined_strategies` is
— an inert safety gate must never be indistinguishable from a passing one.

---

### CR-03: Portfolios added after `build_live_system` returns never receive a venue account

**File:** `itrader/trading_system/live_trading_system.py:2014-2021` (attach call site),
`itrader/portfolio_handler/portfolio_handler.py:219-302` (`add_portfolio`)

**Issue:** `_attach_venue_accounts` runs exactly once, inside `build_live_system`, over the
portfolios that exist at that moment — i.e. only the rehydrated ones (`build_live_system` never
instantiates `spec.portfolios`). `add_portfolio` has no attach hook. Yet
`PortfolioHandler._persist_definition`'s own rationale (`portfolio_handler.py:304-338`) states:
*"live portfolios are added by the application after build_live_system returns."*
`tests/integration/test_distinct_account_invariant.py:487-494` does exactly that.

A portfolio created post-boot with an `account_id` that WAS assembled at boot is the dangerous
case: `on_order` resolves `(venue, account_id)`, finds the registered `OkxExchange`, and
**submits real orders to the venue** — while the portfolio's cash, positions and PnL are tracked
by a `SimulatedCashAccount` compute leaf, and it is excluded from snapshot, `VenueReconciler`
and the baseline residual guard because `is_venue_truth` is `False`. Real fills settle against
fabricated local cash with no venue cross-check.

If the `account_id` was NOT assembled at boot, the order is silently refused instead (CR-02's
failure mode). Neither outcome is acceptable and neither raises.

**Fix:** Move the attach behind the handler so it fires on every creation path. E.g. inject an
account-factory resolver into `PortfolioHandler` at composition:

```python
# build_live_system
portfolio_handler.set_account_resolver(
    lambda portfolio: _account_for(portfolio, venue_lifecycles, exchange))

# PortfolioHandler.add_portfolio, after self._portfolios[...] = portfolio
if self._account_resolver is not None:
    portfolio.account = self._account_resolver(portfolio)   # raises on an unassembled account
```

`_attach_venue_accounts` then becomes a loop over the resolver for the rehydrated set, and
there is one code path instead of two.

---

### CR-04: The D-09 config migration is a guaranteed no-op on a real upgrade; existing portfolio config is silently lost

**File:** `migrations/versions/p11_b2_uuid_fk_config_move.py:200-233` (`_move_config`),
`migrations/versions/p11_b2_uuid_fk_config_move.py:50-52` (the acknowledgement),
`itrader/portfolio_handler/storage/sql_storage.py:597-613` (`load_config`)

**Issue:** `_move_config` copies `portfolio_account_state.config_json` onto a **matching**
`portfolios` row and counts a non-match as a benign "orphan". But `portfolios` is created empty
by the immediately preceding revision (`p11_venue_accounts_portfolios`), and the module
docstring itself states the fact that makes the operation vacuous:

> "A `portfolio_account_state` row whose `portfolio_id` has no `portfolios` parent is an
> already-orphaned pre-Phase-11 row (**nothing wrote `portfolios` rows before this phase**)."

If nothing ever wrote a `portfolios` row before this phase, then at `upgrade()` time **every**
source row is an orphan. `moved` is provably `0` on any real deployment; the loop logs at INFO
and returns.

Meanwhile the read side moved unconditionally: `load_config` (`sql_storage.py:597-613`) now
reads ONLY `portfolios.config_json` and the legacy account-state fallback was deleted. So after
`alembic upgrade head`, every pre-existing live portfolio's persisted config becomes unreadable
— `load_config()` returns `None`, `_layer_persisted_overrides` guards on truthiness and applies
nothing, boot is clean, suite is green, and every portfolio trades on defaults. That is verbatim
the failure mode the revision docstring calls *"the single highest-regression-risk operation in
the phase, and the risk is that it fails SILENTLY"*.

The test that is supposed to close this gap cannot: `_seed_for_the_move`
(`tests/integration/test_p11_migration_chain.py:78-111`) hand-inserts a `portfolios` row at
`_REVISION_ONE` — a state unreachable in a real chain — and the negative control varies only the
chain head, not the staging, so both tests are blind to the actual production shape.

**Fix:** Either (a) make the move self-sufficient by back-filling definition rows from the state
rows it is about to move (they need a `venue_accounts` parent, so this requires an operator-
supplied default account), or (b) count and **refuse** rather than silently skipping:

```python
if orphaned:
    raise RuntimeError(
        f"REFUSING the D-09 config move: {orphaned} portfolio_account_state row(s) carry a "
        f"config blob with no `portfolios` parent ({moved} moved). After this migration "
        "load_config reads ONLY portfolios.config_json, so these blobs would be silently "
        "unreadable. Create the definition rows (portfolio_id, name, venue_name, account_id, "
        "initial_cash) for these portfolios, then re-run 'alembic upgrade head'.")
```

and add a migration test whose staging inserts **only** the state rows (no `portfolios` row),
asserting the chosen behaviour.

---

### CR-05: Per-account credentials silently fall back to the ambient global `OKX_API_*` set field-by-field

**File:** `itrader/venues/okx_plugin.py:96-100`, `itrader/config/okx_settings.py:54-76`,
`itrader/config/credential_resolver.py:129-143`

**Issue:** `EnvCredentialResolver` fails loud only when a well-formed `secret_ref` matches
**zero** variables (T-11-18). A prefix matching *some* variables returns a partial mapping, and
the plugin feeds it straight into the venue model:

```python
resolved = self._resolver.resolve(secret_ref)          # e.g. {"api_key": SecretStr(...)}
return OkxConnector(OkxSettings(**resolved))
```

`OkxSettings` is a `pydantic_settings.BaseSettings`. Init kwargs are the highest-priority
source, but every field they do **not** supply is still resolved from the environment via its
`validation_alias` — `OKX_API_SECRET`, `OKX_API_PASSPHRASE`, `OKX_SANDBOX`, `OKX_REGION`. So an
account whose prefix supplies only `OKX_ACCT_B_API_KEY` authenticates with **account B's key and
the ambient global secret + passphrase**. Construction succeeds (no `ValidationError`, because
the missing fields were populated), no warning is emitted, and the connector believes it is
scoped to account B.

This is precisely the cross-account credential bleed the resolver's fail-loud contract is
written against — the module docstring says *"a silent fallback is precisely how account A's
keys reach account B's connector"* — reintroduced one layer down, at field granularity instead
of reference granularity. The D-04 UID guard would not necessarily catch it either: the ambient
secret/passphrase belong to *some* real account, so the session is valid and its UID is stable;
on first connect the guard simply records the wrong UID as trusted.

No test covers a partial prefix. `test_resolve_isolates_accounts_by_prefix`
(`tests/unit/config/test_credential_resolver.py:91-102`) seeds only `_API_KEY` for both accounts
and asserts on the resolver output alone, so it never exercises the `OkxSettings` construction
where the fallback occurs.

**Fix:** Construct the credential model from the resolved mapping ONLY — never letting the env
source fill gaps — and fail loud on an incomplete per-account prefix:

```python
resolved = self._resolver.resolve(secret_ref)
required = {"api_key", "api_secret", "api_passphrase"}
missing = required - set(resolved)
if missing:
    raise CredentialResolutionError(
        secret_ref,
        f"resolved {sorted(set(resolved) & required)} but is missing "
        f"{sorted(missing)}; refusing to complete the credential triple from the "
        "ambient process environment")
return OkxConnector(OkxSettings.model_construct_from(resolved))  # or a non-BaseSettings DTO
```

Add a unit test that seeds `OKX_ACCT_B_API_KEY` **and** the ambient `OKX_API_SECRET`, then
asserts the build raises rather than producing a connector whose secret is the ambient one.

## Warnings

### WR-01: `save_config` now raises for portfolios `_persist_definition` deliberately skips

**File:** `itrader/portfolio_handler/storage/sql_storage.py:566-595`,
`itrader/portfolio_handler/portfolio_handler.py:339-342`

**Issue:** `save_config`'s legacy account-state arm was deleted on the stated grounds that
*"Plan 11-08 added the production writer … so a live portfolio now always has a definition
row."* But `_persist_definition` returns early when `venue_name` or `account_id` is `None`, and
that shape is explicitly documented as still supported ("This is the pre-11-05 call shape … and
it stays supported"). For such a portfolio, a runtime `portfolio:{id}` `CONFIG_UPDATE` now raises
`PortfolioStateError` out of `ConfigRouter`, and its config never persists across restarts. The
guarantee the deletion depends on is conditional, not universal.

**Fix:** Either make the definition row unconditional in live (see CR-02's invariant), or keep
`save_config`'s raise but have `_persist_definition` raise the same typed error instead of
silently returning, so the two agree on when a definition row is required.

### WR-02: One bad portfolio config aborts layering for every later portfolio

**File:** `itrader/trading_system/live_trading_system.py:1340-1348`

**Issue:** The portfolio arm of `_layer_persisted_overrides` wraps the entire `for` loop in one
`try/except _degrade_clean`. The docstring claims *"Per-scope isolation means one bad scope never
aborts the others"* — but within the portfolio scope, a single poisoned `config_json` (or a
`save_config`-shaped raise, WR-01) skips every portfolio after it in `_portfolios` iteration
order, with one warning naming only the first failure.

**Fix:** Move the guard inside the loop so isolation is per portfolio:

```python
for _pid, portfolio in portfolio_handler._portfolios.items():
    try:
        cfg = portfolio.state_storage.load_config()
        if cfg:
            portfolio.update_config(cfg)
    except _degrade_clean as exc:
        logger.warning("Skipping persisted config for portfolio %s (%s)", _pid, exc)
```

### WR-03: Registration and resolution normalize the account key differently

**File:** `itrader/trading_system/live_trading_system.py:2001-2003` vs
`itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:218-220`

**Issue:** Registration writes `exchanges[(exchange, account_spec.account_id or DEFAULT_ACCOUNT_ID)]`,
but `_exchange_for` reads `exchanges.get((venue_name, getattr(portfolio, "account_id", None)))`
with no normalization. For an unnamed account the two halves disagree: the exchange registers
under `'default'` and the lookup misses with `None`, so `VenueReconciler` receives `exchange=None`
and the correlation-map repopulation seam silently no-ops. `ExecutionHandler._resolve_account_id`
(`execution_handler.py:230-240`) deliberately does NOT coerce `None`, which is correct there —
but that makes the registration-side `or DEFAULT_ACCOUNT_ID` the asymmetric half.

**Fix:** Pick one rule and state it in one place. Given `on_order` must never coerce, registration
should not coerce either: register under the raw `account_spec.account_id` and let CR-02's
invariant guarantee it is never `None` in live.

### WR-04: `enabled` is write-once-`True`; the rehydrate `INACTIVE` branch is unreachable in production

**File:** `itrader/portfolio_handler/portfolio_handler.py:346-356`,
`itrader/portfolio_handler/rehydrate/portfolio_rehydrate.py:141-147`

**Issue:** `_persist_definition` hardcodes `enabled=True` and is gated on row absence, and no
other code path ever writes `enabled=False` to `portfolios`. `Portfolio.set_state(INACTIVE)` at
runtime therefore never persists. `rehydrate_portfolios`' CR-01-posture branch (reconstruct
present-but-inactive) can only be reached by an out-of-band DB write, and a portfolio deactivated
by an operator comes back ACTIVE and trading on the next restart.

**Fix:** Add a `set_enabled(portfolio_id, enabled)` write on the definition store and call it
from whatever flips `PortfolioState`, or document `enabled` as operator-only (out-of-band) and
say so in the column comment.

### WR-05: `_mint_account_rows` and `_read_account_secret_ref` compose into an ambient-credential fallback

**File:** `itrader/trading_system/live_trading_system.py:1351-1391`, `:1452-1499`

**Issue:** Both degrade clean with a WARNING on any store failure. Together they mean: a transient
DB problem during minting or reading leaves `secret_ref=None`, and `OkxConnectorPlugin.build`
then takes the "LEGACY single-account path" — `OkxSettings()` from the ambient global
`OKX_API_*` set. In a multi-account deployment that connects account B's bundle with account A's
credentials, which is the exact misroute the D-04 guard was built to detect (and which the guard
itself may then trust-on-first-use if no `venue_uid` was ever recorded, since minting failed).
Two individually-reasonable degrade-clean decisions produce a fail-open composite.

**Fix:** Once more than one account is derived (`len(account_ids) > 1`), a read failure must be
fatal rather than degrading — the ambient-credential path is only safe when there is exactly one
account.

### WR-06: The D-04 spoofing guard has five independent paths to silent inertness

**File:** `itrader/venues/venue_uid_guard.py:98-124`, `:146-179`,
`itrader/venues/lifecycle.py:115-122`, `itrader/venues/okx_plugin.py:130-166`

**Issue:** The phase's only high-severity spoofing mitigation degrades to "inert" — logged, never
alerted, never surfaced on `get_status()` — when: the plugin's UID fetch raises (double-swallowed:
`OkxVenuePlugin.fetch_venue_uid` catches `Exception`, and `_fetch_uid` catches it again), the venue
returns no `uid`, the store read fails, no `venue_accounts` row exists, or the record write fails.
`VenueLifecycle._assert_venue_uid` adds a sixth (no store / no sink wired). The plugin docstring
further records that the endpoint/field pair *"could not be confirmed against a live authenticated
session"* — so the most likely real-world outcome (a wrong endpoint or renamed field) lands on the
silent path.

**Fix:** Route the degraded paths through the same `alert_sink` the mismatch uses (severity
`WARNING`), and expose a `venue_uid_guard_active` boolean per account on `get_status()` so an
operator can see whether the detector is armed. A security control that cannot be observed as
inert will ship inert.

### WR-07: Non-primary accounts build data providers (and OKX connectors) that are wired to nothing

**File:** `itrader/venues/assemble.py:168-180`, `itrader/trading_system/live_trading_system.py:2005-2012`

**Issue:** `assemble_venues` calls `assemble_venue` per account, and each one unconditionally
builds a `LiveDataProvider` via `data_plugin.build_provider(...)`, which for OKX resolves the
account's connector. Only the primary's provider is ever bound (`feed.set_provider` /
`set_bar_sink` / `set_global_queue` / `set_halt_signal`). Every other account therefore holds a
fully-constructed, credential-bearing, unwired data provider whose halt signal and stream-state
listener are never attached — so a fault on those sockets has no escalation path. For the `paper`
venue the default-provider map (`venue_spec.py:92-93`) additionally forces an OKX connector per
paper account, requiring OKX credentials in a credential-free deployment.

**Fix:** Build the data provider only for the primary account (`assemble_venues` knows which is
first), or wire `set_halt_signal` / `set_stream_state_listener` on every provider the way the
exchange loop at `:2244-2251` already does.

### WR-08: Teardown drives only the first lifecycle

**File:** `itrader/trading_system/live_trading_system.py:897-928`, `itrader/venues/lifecycle.py:137-149`

**Issue:** `start()` starts every lifecycle (`:762-763`) but `stop()` takes `next(iter(...))` and
stops only that one, relying on the comment "ConnectorProvider.close_all() … the memo is shared
across accounts". That holds only for the `self._connectors is not None` branch of
`VenueLifecycle.stop`; the documented fallback branch (`elif self._bundle.connector is not None:
self._bundle.connector.disconnect()`) exists precisely for lifecycles built without a shared
provider, and in that configuration every non-primary connector leaks (a `ResourceWarning` under
`filterwarnings=["error"]`, a dangling authenticated socket in production). Asymmetric start/stop
is also simply harder to reason about than the symmetric form.

**Fix:** `for lifecycle in self._venue_lifecycles.values(): lifecycle.stop()` — `close_all()` is
idempotent, so the shared-provider case is unaffected.

### WR-09: Three modules reach into `PortfolioHandler._portfolios`

**File:** `itrader/portfolio_handler/rehydrate/portfolio_rehydrate.py:124`,
`itrader/trading_system/live_trading_system.py:1341`, `:1591`, `:1964`,
`itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` (via `get_active_portfolios`, OK)

**Issue:** The rehydrate collaborator, the config layering function, the attach function and the
account-spec builder all iterate or membership-test the handler's private `_portfolios` dict from
outside the class. `tests/integration/test_distinct_account_invariant.py` and
`test_multi_portfolio_lifecycle.py` assert on it too, and
`tests/integration/test_per_account_exchange_routing.py:108` assigns
`handler._portfolio_read_model` directly rather than through the constructor. The handler already
exposes `get_active_portfolios()`; there is no public "all portfolios" or "is registered" accessor,
so every consumer reached for the private field instead.

**Fix:** Add `PortfolioHandler.all_portfolios()` and `has_portfolio(portfolio_id)` and convert the
four production call sites; inject `portfolio_read_model` through the `ExecutionHandler`
constructor in the routing test.

### WR-10: `ExecutionHandler.on_order` failures are invisible outside the log

**File:** `itrader/execution_handler/execution_handler.py:197-228`

**Issue:** All three fail-closed paths (unknown portfolio, unnamed account, unregistered pair) call
`self.logger.error(...)` and `return`. No `ErrorEvent` is published, no counter is incremented, and
nothing reaches `get_status()`. Given CR-02 and CR-03 both terminate in this branch, a
misconfigured live engine drops 100% of its orders while `get_status()` reports `RUNNING`,
`errors_count: 0`, and no halt reason. Fail-closed is right; fail-silent is not.

**Fix:** Emit a `FillEvent(REFUSED)` (the established rejection-as-event convention — it also
reconciles the order mirror instead of leaving it PENDING forever) or at minimum publish an
`ErrorEvent` with `severity=ERROR` so the live publish-and-continue policy counts it.

### WR-11: The phase's flagship multi-portfolio test demonstrates the shape D-14/D-15 forbid

**File:** `tests/integration/test_multi_portfolio_lifecycle.py:104-125`

**Issue:** `_PaperPair.add_portfolio` gives **both** portfolios `account_id=DEFAULT_ACCOUNT_ID`
and passes no `venue_name`. Two portfolios naming one venue account is exactly the T-11-38
collision; it passes only because `venue_name is None` makes `_persist_definition` skip the row
(so the DB unique constraint never sees it) and `assert_distinct_accounts` is not on this path at
all. The module docstring acknowledges the shared-exchange consequence but not that the fixture
also demonstrates the forbidden account sharing — and it shows how trivially the invariant is
bypassed: omit `venue_name`.

**Fix:** Give the two paper portfolios distinct `account_id`s (`'paper-a'` / `'paper-b'`) and pass
`venue_name`, or add an explicit test asserting that a portfolio with `account_id` but no
`venue_name` is refused, so the half-null bypass is closed rather than relied upon.

### WR-12: The migration tests cannot detect the CR-04 failure mode

**File:** `tests/integration/test_p11_migration_chain.py:78-111`, `:231-280`

**Issue:** `_seed_for_the_move` inserts a `portfolios` row at `_REVISION_ONE` before running the
move. No real upgrade can reach that state (nothing wrote `portfolios` rows pre-Phase-11), so the
positive test exercises copy mechanics against a hand-built precondition. The negative control
varies only the chain head — identical staging — so it proves "the move step runs" and nothing
about whether the move has anything to move. The module docstring's claim that this file closes
the silent-failure gap does not hold.

**Fix:** Add a test whose staging inserts **only** `portfolio_account_state` rows with config
blobs (the real pre-upgrade shape) and asserts the chosen CR-04 behaviour — refusal, or a
back-filled definition row — after `upgrade(head)`.

---

_Reviewed: 2026-07-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
