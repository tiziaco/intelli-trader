---
phase: 11-multi-portfolio-live
plan: 08
subsystem: portfolio-bootstrap
tags: [MPORT-02, MPORT-03, D-07, D-08, D-09, D-14, D-15, rehydrate, composition-root]
requires:
  - "11-01: PortfolioDefinitionStore + the (venue_name, account_id) unique constraint"
  - "11-03: the D-09 config rehome onto portfolios.config_json (and its legacy arms)"
  - "11-05: add_portfolio's portfolio_id / account_id / venue_name + the duplicate-id guard"
  - "11-07: the per-account assembly loop and _build_account_specs / _mint_account_rows"
provides:
  - "PortfolioHandler.definition_store — the FIRST production writer of the portfolios table"
  - "rehydrate_portfolios(store, portfolio_handler) — boot-time reconstruction with persisted ids"
  - "assert_distinct_accounts(persisted, spec_portfolios, venue_name) — the D-14/D-15 union check"
  - "DuplicateVenueAccountError in the portfolio exception family"
  - "the live boot ordering: invariant -> rehydrate -> minting -> layering -> strategy rehydrate"
  - "tests/integration/test_distinct_account_invariant.py — the MPORT-02/MPORT-03 boot gates"
affects:
  - "itrader/portfolio_handler/portfolio_handler.py, storage/sql_storage.py"
  - "itrader/trading_system/live_trading_system.py"
  - "itrader/core/exceptions/portfolio.py"
tech-stack:
  added: []
  patterns:
    - "gate-the-write-on-absence against a delete-then-insert upsert (inherited from 11-07)"
    - "read the store back off the handler that OWNS it (DECOMP-01a)"
    - "probe for the TABLE, not for errors, when separating 'un-migrated' from 'broken'"
    - "assert the NEGATIVE (nothing was minted), not merely that an exception fired"
key-files:
  created:
    - itrader/portfolio_handler/rehydrate/__init__.py
    - itrader/portfolio_handler/rehydrate/portfolio_rehydrate.py
    - itrader/portfolio_handler/rehydrate/distinct_account_invariant.py
    - tests/unit/portfolio/test_portfolio_rehydrate.py
    - tests/integration/test_distinct_account_invariant.py
    - tests/integration/test_portfolio_definition_writer.py
  modified:
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - itrader/core/exceptions/portfolio.py
    - itrader/core/exceptions/__init__.py
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_config_restart_layering.py
    - tests/integration/test_p11_migration_chain.py
decisions:
  - "The writer lives on PortfolioHandler.add_portfolio, not at the composition root, because 11-07 established that build_live_system creates NO portfolios — live portfolios are added by the application after boot, so a boot-only writer would persist none of them."
  - "The definition write is GATED ON ABSENCE. upsert is a delete-then-insert, and rehydrate re-enters add_portfolio for every persisted portfolio on every boot, so the unconditional form would wipe the D-09 config_json on the first restart after it was saved."
  - "A write failure PROPAGATES rather than degrading clean: a portfolio whose definition did not persist boots into nothing next restart while its positions and cash orphan — a silent, money-relevant loss."
  - "A disabled definition row loads present-but-INACTIVE rather than being dropped (the CR-01 strategy precedent), because dropping it would orphan its open positions and make the portfolio unreachable across the restart."
  - "The layering call was NOT moved. 11-07's restructure already placed it well below the insertion point; the plan's prediction was written against the pre-11-07 tree. Pinned by an executable ordering test instead of by reading the source."
  - "An un-provisioned `portfolios` table degrades with a WARNING (the D-21 first-start state), probed by inspecting for the TABLE specifically so a genuine store fault still propagates loud."
metrics:
  duration: ~85 min
  tasks: 4
  files: 13
  tests_added: 36
  suite: "2777 passed / 6 skipped (baseline 2741 / 6)"
  completed: 2026-07-21
status: complete
---

# Phase 11 Plan 08: The W4 Bootstrap Boundary Summary

Gave the `portfolios` table its first production writer, then used that guarantee to land the
boot-time portfolio rehydrate, the two-source distinct-account invariant, and the removal of
two legacy storage arms that had been waiting on exactly this plan.

## What shipped

**Task 0 — the writer (`892f9b7f`)**

The owner's pre-execution audit was correct: this plan was a reader with no writer.
`grep -rn 'PortfolioDefinitionStore' itrader/` returned only the store's own module and
`upsert` had zero production callers, so `read_all()` would have returned `[]` on every
production boot forever while every acceptance criterion passed against a fixture-provisioned
store.

`PortfolioHandler` now constructs a `PortfolioDefinitionStore` on the live arm
(`environment == "live"` and a real `sql_engine`) and `add_portfolio` persists a definition
row. Because that guarantee now exists, both legacy arms in `sql_storage.py` are gone — the
`save_config` zero-sentinel INSERT and the `load_config` account-state fallback — and a
missing definition row raises instead of silently writing the config blob to a column
`load_config` no longer reads.

**Task 1 — the rehydrate collaborator (`ee3858e2`)**

`rehydrate_portfolios` reconstructs each portfolio with its **persisted** `portfolio_id`, so
the seven portfolio-scoped child tables reattach to the right portfolio. Zero rows is a clean
no-op; two same-venue rows under different accounts both load; a disabled row loads
present-but-inactive; the pass is idempotent within a boot; store faults propagate loud.

**Task 2 — the invariant (`211268ec`)**

`assert_distinct_accounts` runs over the **union** of persisted rows and spec-supplied
portfolios, keyed on the `(venue_name, account_id)` PAIR. `DuplicateVenueAccountError` joins
the portfolio exception family carrying the pair and both labels, with a message naming the
consequence and the remediation.

**Task 3 — the wiring (`0f4c4752`)**

The invariant and rehydrate run above the venue-wiring block, so a collision is refused before
any `venue_accounts` row is minted. Clause (1) of the strategy-rehydrate comment was rewritten
to name what actually supplies the ordering guarantee.

## Mutation testing

Every gate was mutation-tested before being banked, and each mutation was reverted to an empty
diff and re-verified. **No gate was already green before its deliverable existed.**

| # | Mutation | Result |
|---|----------|--------|
| 1 | delete the `_persist_definition` call | RED — 3 tests, incl. the writer gate |
| 2 | remove the absence gate (unconditional upsert) | RED — the config-clobber gate |
| 3 | `save_config` swallows a missing definition row | RED — the fail-loud gate |
| A | rehydrate mints a fresh id instead of the persisted one | RED — 8 tests |
| B | `enabled` ignored | RED — the present-but-inactive gate |
| C | idempotence guard removed | RED — the double-rehydrate gate |
| D | invariant checks only the persisted source | RED — both spec-side gates |
| E | invariant keys on `account_id` alone (venue dropped) | RED — the two-venues gate |
| F | **delete the `assert_distinct_accounts` call site** | RED — gates (a), (b) AND (e) |
| G | delete the `rehydrate_portfolios` call site | RED — 3 boot gates |
| H | **invariant moved BELOW account minting** | RED — gate (e) ONLY |
| I | **rehydrate moved BELOW `_layer_persisted_overrides`** | RED — the config-ordering gate |

Mutations H and I are the ones worth reading. **H was caught by exactly one test** — the
"no account was minted" negative assertion. Every other gate stayed green, because the
collision still raised; only the negative assertion noticed that it raised *too late*. That
is the concrete justification for the plan's insistence on asserting the negative rather than
just `pytest.raises`.

**I confirms the silent-no-op hazard is real** even though the predicted fix was not needed:
with rehydrate below the layering call, the persisted portfolio config is never applied, and
only the ordering test reddens — no exception, no warning, and every portfolio-counting
assertion still green.

## Plan drift found

The decisions all held. Several factual claims about the code did not.

1. **The layering call did NOT need to move — this plan's central ordering change was already
   satisfied.** The plan (and its must_haves) state that `_layer_persisted_overrides` sits
   ABOVE the venue-assembly block and must be moved below rehydrate or it becomes a silent
   no-op. In the post-11-07 tree the layering call is at `:1816` and `assemble_venue` /
   `_build_account_specs` are at `:1712` / `:1693` — the layering call is already well BELOW
   the point where rehydrate belongs. Placing the bootstrap above the venue block therefore
   satisfies the ordering constraint with no move at all. The hazard is genuine (mutation I
   proves it), so it is pinned by an executable test rather than by the relocation.

2. **`add_portfolio` was already being called with a `Decimal`.**
   `test_paper_restart_restore.py:173` passes `cash=Decimal("100000.00")` against the
   `cash: float` annotation. Widening to `float | Decimal` (audit correction #2) corrects an
   annotation that production and tests had already outgrown.

3. **Audit correction #7 does not bite.** `test_paper_restart_restore.py:172`'s hand-rolled
   `add_portfolio` was predicted to collide with 11-05's duplicate-id guard once the writer
   landed. It does not: that test's `_no_pg_env` fixture forces the in-memory fallback, so
   `sql_engine` is `None`, the handler owns no definition store, and nothing is persisted. The
   file needed no change.

4. **A third test pinned the legacy arm, and the plan named only two.** The plan scoped
   `test_config_restart_layering.py:121-125` and `:162-185`.
   `test_p11_migration_chain.py::test_save_config_falls_back_to_the_state_row_without_a_definition_row`
   asserted the fallback explicitly (its docstring says "the zero-sentinel arm SURVIVES this
   plan… 11-08 removes the arm once it creates the guarantee"). It was inverted to assert the
   fail-loud behaviour, with the history recorded in the docstring.

5. **`SqlPortfolioStateStorage._account_state` became dead code** when both arms went. Its
   only remaining consumers were those arms — the account-state carrier is owned by
   `CachedSqlPortfolioStateStorage`, which binds its own handle. Removed; the TABLE is still
   registered by `build_portfolio_tables`, so provisioning is unchanged. This is the class of
   orphan the brief warned passes both mypy and the full suite silently.

6. **Audit correction #9 was right about the false-green criteria.** `grep -c 'def
   assert_distinct_accounts'` and the barrel-export grep are satisfied by merely defining
   things, and "a boot with zero persisted portfolios succeeds cleanly" is today's exact
   behaviour. Those are recorded as hygiene checks, not as evidence of delivery; the delivery
   evidence is the mutation table above.

7. **Baseline was 2741, not 2715** (matching 11-07's summary, not the plan's pin of `>= 2715`).

## Deviations from Plan

**1. [Rule 2 — missing critical functionality] Un-provisioned-table probe before rehydrate**

- **Found during:** Task 3.
- **Issue:** The plan specifies calling `read_all()` unconditionally inside the durable-store
  gate. On a database whose Alembic chain has not run, that raises and takes the whole boot
  down — including for deployments that never had a portfolio.
- **Fix:** probe `inspect(engine).has_table("portfolios")` and degrade with a WARNING when
  absent. Deliberately narrow: it probes for the TABLE and nothing else, so a genuine store
  fault still propagates loud out of `rehydrate_portfolios` rather than being converted into
  the silent zero-portfolio boot D-19 forbids. This mirrors `StrategyRegistryStorageFactory`'s
  existing D-21 first-start warning verbatim.
- **Commit:** `0f4c4752`

**2. [Rule 1 — bug avoided] The definition write is gated on absence**

- **Found during:** Task 0, reading `PortfolioDefinitionStore.upsert` before using it (as the
  owner's brief instructed).
- **Issue:** `upsert` is a delete-then-insert on `portfolio_id`. Rehydrate re-enters
  `add_portfolio` for every persisted portfolio on every boot, so an unconditional write would
  DELETE-then-INSERT each row and wipe its `config_json` — the D-09 home of the per-portfolio
  config blob. The engine would boot looking entirely healthy and trade on defaults.
- **Fix:** skip when `get(portfolio_id)` returns a row. Mutation 2 confirms the gate catches
  the unconditional form.
- **Commit:** `892f9b7f`

**3. [Scope] `cached_sql_storage.py`'s config carry-forward left in place**

`save_account_state`'s delete-then-insert still carries `config_json` forward on the
`portfolio_account_state` row. That carry-forward is now vestigial — the blob lives on the
definition row and a fill structurally cannot reach it — but it is harmless, the plan scoped
only `sql_storage.py`'s two markers, and removing it is a behaviour change with no gate.
Recorded as a follow-up rather than done silently.

## Known limitations

- **A persisted portfolio's venue account is still not assembled.** `_account_ids_for_spec`
  derives the account set from the SPEC only, so a rehydrated portfolio whose account appears
  in no spec gets no bundle, connector or exchange. This is the pre-existing 11-07 gap (its
  drift item 1: minted accounts are not attached to portfolios), and per the dispatch brief
  attaching them is 11-09's scope — no second attachment path was built here. It is visible in
  the test shapes: the rehydrate gates pass `_spec([])`, because a spec portfolio naming the
  persisted account would be a genuine cross-source collision.
- **A two-portfolio LIVE `start()` remains unreachable.**
  `reconciliation_coordinator.py:165-173` still raises on more than one active portfolio; it
  was left untouched (11-07b removes it in Wave 6). Everything here is gated at BUILD time,
  which is what 11-07b's prerequisite asks for.
- **The `max_portfolios` limit (default 50) now applies to rehydrated portfolios.** A restart
  above the limit fails loud partway through, leaving a partial set registered. Accepted at
  this phase's realistic count of two and documented in the collaborator's docstring.
- **The boot gates require Docker** (the session-scoped testcontainers Postgres via
  `pg_database_env`) and skip Dockerless, like every other live-SQL test in the suite. The
  pure-function and SQLite gates run unconditionally.

## Verification

| Gate | Result |
|------|--------|
| `pytest tests -q` | 2777 passed / 6 skipped (baseline 2741 / 6) |
| `pytest tests/integration/test_backtest_oracle.py -q` | pass (byte-exact) |
| `pytest tests/integration/test_okx_inertness.py -q` | pass |
| `PYTHONPATH="$PWD" mypy` | Success, 259 source files |
| `git diff -- backtest_trading_system.py` | EMPTY |
| `grep -rn 'PortfolioDefinitionStore' itrader/ \| grep -v portfolio_definition_store.py` | a real construction site at `portfolio_handler.py:103` (returned none before) |
| `grep -c 'removed by 11-08' sql_storage.py` | 0 |
| `grep -cE 'Decimal\(' portfolio_rehydrate.py` | 0 |
| `grep -rc 'portfolio_rehydrate' portfolio_handler/__init__.py` | 0 (not barrel-exported) |
| `grep -c 'def assert_distinct_accounts'` | 1 |
| tab-indented added lines in 4-space files | 0 |
| `pyproject.toml` / `poetry.lock` changed | no |

The six required invariant gates (a)–(f) are all present and all drive the real
`build_live_system`: (a) `test_two_spec_portfolios_on_one_account_refuse_to_boot`;
(b) `test_a_spec_portfolio_colliding_with_a_persisted_row_refuses_to_boot`;
(c) `test_two_persisted_portfolios_on_one_venue_both_rehydrate` +
`test_two_spec_portfolios_on_one_venue_assemble_two_accounts`;
(d) `test_the_same_account_id_on_two_venues_boots`;
(e) `test_a_refused_boot_mints_no_account_and_registers_no_exchange`;
(f) mutation F in the table above.

The end-to-end restart proof is
`test_a_persisted_portfolio_survives_a_full_teardown_and_rebuild`: it boots the real system,
creates a portfolio through the real `add_portfolio`, tears down, boots a second system on the
same database, and asserts the SAME `portfolio_id` comes back. No fixture provisions the
definition row — it comes from production's writer, which is why the test cannot pass at all
without Task 0.

## Self-Check: PASSED

- `itrader/portfolio_handler/rehydrate/portfolio_rehydrate.py` — FOUND (`def rehydrate_portfolios`)
- `itrader/portfolio_handler/rehydrate/distinct_account_invariant.py` — FOUND (`def assert_distinct_accounts`)
- `tests/integration/test_distinct_account_invariant.py` — FOUND (19 tests)
- `tests/integration/test_portfolio_definition_writer.py` — FOUND (7 tests)
- `tests/unit/portfolio/test_portfolio_rehydrate.py` — FOUND (10 tests)
- `892f9b7f`, `ee3858e2`, `211268ec`, `0f4c4752` — all FOUND in `git log`
