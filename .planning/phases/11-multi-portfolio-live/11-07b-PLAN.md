---
phase: 11-multi-portfolio-live
plan: 07b
type: execute
wave: 6
depends_on: ["11-07", "11-09"]
files_modified:
  - itrader/portfolio_handler/reconcile/reconciliation_coordinator.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/safety/stream_recovery_handler.py
  - itrader/portfolio_handler/account/conformance.py
  - tests/integration/test_live_system_okx_wiring.py
  - tests/integration/test_live_portfolio_durable_wiring.py
  - tests/integration/test_early_durable_halt_refusal.py
  - tests/integration/test_paper_restart_restore.py
  - tests/unit/execution/test_reconnect_resilience.py
  - tests/integration/test_resume_gated_on_all_streams.py
  - tests/integration/test_resume_missed_fill_catchup.py
  - tests/e2e/test_okx_sandbox_recon.py
autonomous: true
requirements: [MPORT-01]
must_haves:
  truths:
    - "PROVENANCE (owner decision, 2026-07-21): this plan was SPLIT OUT of 11-07. A pre-execution audit found that 11-07 as written would delete the single-account machinery WITHOUT a replacement, and that the deletions destroy live-safety wiring whose tests stay green because they set the fields directly. 11-07 now builds/wires/mints and deletes nothing; this plan carries every deletion and runs AFTER 11-09 has rehomed the coordinator's account access."
    - "MPORT-01/D-13: `_link_venue_account_to_portfolios` (`reconciliation_coordinator.py:151-176`) and its `RuntimeError(>1)` guard (`:165-173`) are DELETED, along with the facade's single `_venue_account` field (declaration `live_trading_system.py:192`, assignment `:196`, read sites `:369` and `:1777`). `grep -rn '_link_venue_account_to_portfolios' itrader/` returns nothing."
    - "THE RECONNECT SNAPSHOT MUST SURVIVE THE DELETION. `_venue_account` read site #2 (`live_trading_system.py:1777`) feeds `StreamRecoveryHandler(venue_account=...)`; the handler guards on it (`stream_recovery_handler.py:122`) and calls `.snapshot()` (`:126`). Passing `None` makes the post-reconnect REST re-snapshot a PERMANENT NO-OP — the engine resumes submission without refreshing venue truth. **Four existing tests would NOT catch this** because they set the field directly on the handler: `tests/unit/execution/test_reconnect_resilience.py:575,615`, `tests/integration/test_resume_gated_on_all_streams.py:57`, `tests/integration/test_resume_missed_fill_catchup.py:78,106`. This plan rehomes the handler to per-account accounts AND adds a test that constructs it through `build_live_system` rather than by field assignment."
    - "THE STARTUP RECONCILE MUST SURVIVE THE DELETION. `reconciliation_coordinator.py:121-123` early-returns when `venue_account is None` — dropping `snapshot()`, `start_streaming()`, `VenueReconciler.reconcile()` AND `_run_session_baseline_guard` (the D-04 HALT-on-unexplained-residual gate). The parameter is required-keyword, so NOT passing it raises `TypeError` (loud) — but the obvious fix, passing `= None`, is SILENT and disables the whole venue reconcile. **11-09 must have already rehomed the coordinator to per-portfolio accounts before this plan runs**; verify that landed before deleting anything."
    - "`test_early_durable_halt_refusal.py` has FUNCTIONAL uses, not prose. `:85`/`:135` assign `system._venue_account = MagicMock(...)`; `:109`/`:110` assert `snapshot.assert_not_called()` / `start_streaming.assert_not_called()`; `:144` asserts `snapshot.assert_called_once()`. Those hold only because `_build_reconciliation_coordinator()` reads the facade field at `:369`. An earlier draft called this file comment-only — it is not. (`test_paper_restart_restore.py` IS docstring-only at `:5`,`:6`,`:15` — that half was correct.)"
    - "THE INVARIANT GAP IS CLOSED BEFORE THE GUARD GOES. Deleting the `RuntimeError(>1)` guard removes the only runtime enforcement that two portfolios cannot share one venue account. The DB `UniqueConstraint('venue_name','account_id')` on `portfolios` (11-01) covers DURABLE ROWS ONLY, not spec-supplied portfolios — `PortfolioSpec.account_id`'s own docstring (`system_spec.py:52-55`) says the application-level check's real job is catching duplicates within a spec, and that check is 11-08's. Confirm 11-08's composition-time invariant is live and TESTED before deleting the guard, or the phase carries a window with no enforcement and no failing test."
    - "`grep -rn '_venue_account' itrader/trading_system/live_trading_system.py` returns nothing. **Scoped deliberately** — the unscoped repo-wide form is UNSATISFIABLE: it returns 24 hits across 6 files, of which 16 are unrelated (`stream_recovery_handler.py`'s own field, `venue_reconciler.py`'s own field, and the substring match inside `build_venue_accounts_table`). An unscoped gate invites an executor to rename unrelated fields to satisfy it."
    - "D-26/deferral bookkeeping: the deferral todos land and the shared-resting-order-book question is answered in writing. NOTE the shared-book finding is scoped as BLOCKING plan 11-11, so a wrong answer surfaces four plans later."
    - "Backtest oracle stays byte-exact: `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` reports 134 trades / 46189.87730727451."
    - "OKX import inertness stays green: `poetry run python -m pytest tests/integration/test_okx_inertness.py -q` exits 0."
  artifacts:
    - path: "itrader/portfolio_handler/reconcile/reconciliation_coordinator.py"
      provides: "link function + >1 guard deleted; per-portfolio account access (from 11-09) is the replacement"
      contains: "portfolio"
    - path: "itrader/trading_system/safety/stream_recovery_handler.py"
      provides: "reconnect snapshot rehomed off the facade singleton onto per-account accounts"
      contains: "snapshot"
  prohibitions:
    - "MUST NOT pass `venue_account=None` into `ReconciliationCoordinator` to satisfy a signature. That silently disables `snapshot`, `start_streaming`, the venue reconcile AND the D-04 baseline guard, with a green suite. If 11-09's rehome is not in place, STOP and report rather than stubbing."
    - "MUST NOT leave `StreamRecoveryHandler` with a permanently-`None` account. A no-op post-reconnect re-snapshot means the engine resumes submitting orders against stale venue truth."
    - "MUST NOT satisfy the `_venue_account` gate by renaming unrelated fields in `stream_recovery_handler.py` or `venue_reconciler.py` — those are their own fields, not the facade singleton."
  flagged_assumptions:
    - "Assumes 11-09 rehomed the ReconciliationCoordinator to per-portfolio accounts and 11-08 landed the composition-time distinct-account invariant. Both are prerequisites, not just orderings. Verify each in code before deleting; if either is absent, this plan cannot run safely."
---

<objective>
Retire the single-account machinery that plan 11-07 replaced — but only after its replacements are
provably in place.

This plan was split out of 11-07 because a pre-execution audit found the original would have deleted
`account_factory()`'s only call site while creating `new_account` with no caller, and would have
silently disabled two pieces of live-safety wiring (the post-reconnect re-snapshot and the entire
startup venue reconcile including the D-04 baseline HALT gate) whose tests stay green because they
assign the fields directly rather than exercising the real path.

Purpose: deletions are the easiest place in this phase to cause a silent regression, because the
thing being deleted is load-bearing for machinery whose tests do not go through it. Sequencing them
last, behind 11-08's invariant and 11-09's coordinator rehome, is what makes them safe.

Output: the link function, its guard and the facade singleton gone; the reconnect and reconcile paths
rehomed onto per-account accounts; the deferral todos and the shared-resting-book finding recorded.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/11-multi-portfolio-live/11-CONTEXT.md
@.planning/phases/11-multi-portfolio-live/11-07-SUMMARY.md
@.planning/phases/11-multi-portfolio-live/11-08-SUMMARY.md
@.planning/phases/11-multi-portfolio-live/11-09-SUMMARY.md
</context>

<prerequisite_verification priority="critical">
BEFORE deleting anything, verify BOTH prerequisites landed. If either is missing, STOP and report —
do not stub, do not pass `None`.

1. **11-09 rehomed the coordinator.** `ReconciliationCoordinator` must obtain accounts per-portfolio
   rather than from a single injected `venue_account`. Read
   `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` and confirm the early-return at
   the old `:121-123` no longer gates the whole reconcile on one scalar account.
2. **11-08 landed the composition-time distinct-account invariant, with a test.** Deleting the
   `RuntimeError(>1)` guard removes the only runtime enforcement. Confirm 11-08's replacement exists
   AND has a test that fails when two portfolios share an account.
</prerequisite_verification>

<tasks>

<task type="auto">
  <name>Task 2: Delete the link function, its guard, and the facade singleton — with a verified dead-code sweep (MPORT-01/D-13)</name>
  <files>itrader/portfolio_handler/reconcile/reconciliation_coordinator.py, itrader/trading_system/live_trading_system.py, itrader/portfolio_handler/account/conformance.py, tests/integration/test_live_system_okx_wiring.py, tests/integration/test_live_portfolio_durable_wiring.py, tests/integration/test_early_durable_halt_refusal.py, tests/integration/test_paper_restart_restore.py</files>
  <read_first>
    - `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` — **4-space, 216 lines, read
      it in full.** The link function and its more-than-one-active-portfolio `RuntimeError`, plus the
      call to it inside the startup reconcile. Its raise message is also the clearest statement of why
      this phase exists — read it before deleting it. Note it contains the third occurrence of the
      venue's wire field spelling, which is what makes plan 11-02's completion grep ordering-sensitive.
    - `itrader/trading_system/live_trading_system.py` — **4-space, under a mypy `ignore_errors`
      override.** The field's declaration, its assignment from the bundle's account factory, and its
      TWO read sites (one passing it into the reconciliation coordinator's constructor, one much
      further down). Locate all four by symbol.
      <!-- planner-discipline-allow: _venue_account -->
    - `itrader/portfolio_handler/account/conformance.py` — **4-space.** Nothing imports it at runtime;
      it exists solely so strict type checking verifies the portfolio-account assignment that the live
      module's `ignore_errors` override would otherwise skip. Its docstrings reference the function
      being deleted, and were ALREADY stale (that function moved packages an earlier phase ago).
      <!-- planner-discipline-allow: _link_venue_account_to_portfolios -->
    - `tests/integration/test_live_system_okx_wiring.py` — the two tests that CALL the deleted function
      directly. One of them is the direct ancestor of the composition-time invariant test plan 11-08
      writes; read its "raises BEFORE any assignment" post-assertion shape, which asserts no portfolio
      received the account, not merely that it raised.
    - `tests/integration/test_live_portfolio_durable_wiring.py` — the monkeypatch target string naming
      the deleted function.
    - `tests/integration/test_early_durable_halt_refusal.py` and
      `tests/integration/test_paper_restart_restore.py` — comment/docstring references only. These do
      not break, but their prose goes stale, and the restart test's behavior assumptions need review
      because it is the analog plan 11-11 builds on.
  </read_first>
  <action>
    Delete `_link_venue_account_to_portfolios` and its more-than-one-active-portfolio `RuntimeError`
    guard from the reconciliation coordinator, along with the call to it in the startup reconcile.
    <!-- planner-discipline-allow: _link_venue_account_to_portfolios -->
    The portfolio's own account attribute is now the designed home, populated per portfolio by
    `new_account`, so the link step has nothing left to do.

    Delete the facade's single venue-account field: its declaration, its assignment from the bundle's
    account factory, and BOTH read sites. The coordinator constructor no longer takes it (plan 11-09
    drops those scalar parameters entirely; for now, stop passing it).
    <!-- planner-discipline-allow: _venue_account -->

    **Do not replace it with a map from account key to account object.** That reintroduces a second
    source of truth for which account a portfolio uses — the exact drift the distinct-account invariant
    exists to prevent.

    **The dead-code sweep is not optional here.** The live trading module is under a per-module
    `ignore_errors` override, so a leftover field reference or orphaned import passes BOTH strict type
    checking and the full test suite, and only review catches it. After the deletions, prove by grep
    that neither symbol survives anywhere in the source tree, and read the module's import block for
    imports that are now unused.

    **Keep the conformance module and UPDATE both its docstrings.** Its purpose — compile-time
    enforcement that every account leaf is assignable to the abstract-base-typed field — becomes MORE
    important now, not less, because more code paths assign accounts. Its references to the deleted
    function were already stale; rewrite them to name `new_account` as the assignment path being
    mirrored.

    Rewrite the two tests that call the deleted function. The fail-loud-on-two-portfolios case does not
    simply disappear — its INTENT (two portfolios must not share one venue account) is now enforced by
    the composition-time invariant plan 11-08 builds, so replace the call-the-deleted-function test
    with one asserting that two portfolios get two DIFFERENT account objects through `new_account`.
    Fix the monkeypatch target string in the durable-wiring test.

    Refresh the stale prose in the halt-refusal test and the restart-restore test. While in the restart
    test, note in the summary whether its offline-drive recipe still holds — its no-op coercion of the
    live session initializer is the same monkeypatch that would silently swallow a misplaced portfolio
    rehydrate, which is plan 11-08's central hazard.

    All source files are **4-space**; all test files are 4-space.
  </action>
  <verify>
    <automated>poetry run python -m pytest tests/integration -q</automated>
  </verify>
  <acceptance_criteria>
    - `poetry run python -m pytest tests -q` exits 0.
    - `grep -rn '_link_venue_account_to_portfolios' itrader/` returns nothing (exit status 1).
    - `grep -rn '_venue_account' itrader/` returns nothing (exit status 1).
    - `grep -rln 'clOrdId' itrader/` lists exactly two files, both under `itrader/execution_handler/exchanges/`
      (this is plan 11-02's C-1 completion check, resolvable only after this deletion).
    - `itrader/portfolio_handler/account/conformance.py` still exists and its docstrings no longer name
      the deleted function.
    - A named test asserts two portfolios receive two DIFFERENT account objects.
    - `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` exits 0.
    - `poetry run python -m pytest tests/integration/test_okx_inertness.py -q` exits 0.
    - `poetry run mypy` exits 0.
  </acceptance_criteria>
  <done>Both single-account assumptions are deleted, no reference to either symbol survives the grep sweep, the conformance mirror is kept and corrected, and every test that referenced them is rewritten or refreshed.</done>
</task>

<task type="auto">
  <name>Task 3: The D-26 naming guard, the deferral todos, and the shared-resting-book investigation</name>
  <files>itrader/trading_system/system_spec.py, itrader/venues/okx_plugin.py, .planning/todos/pending/data-provider-connector-account-model.md</files>
  <read_first>
    - `itrader/trading_system/system_spec.py` — the system-spec account field. **This file is TABS**
      while its sibling live trading module is 4-space; measure, do not generalize. Read the field's
      declaration and its docstring.
    - `itrader/venues/okx_plugin.py` — the DATA arm's account resolution, which is the only remaining
      reader of that field after Task 1 moves the execution arm to per-portfolio accounts.
    - `itrader/execution_handler/matching_engine.py` and
      `itrader/execution_handler/exchanges/simulated.py` — the resting-order book and the
      one-cancels-other handling. This is the investigation target: the book is a single dictionary
      shared by every portfolio trading through the simulated exchange.
    - An existing file in `.planning/todos/pending/` — for the todo file's front-matter shape and
      section conventions.
  </read_first>
  <action>
    **Part B — the deferral todos.** Write
    `.planning/todos/pending/data-provider-connector-account-model.md` recording the D-26 deferral: what
    is deferred, why (owner intends to redesign the data connector; it folds into the multi-provider
    feed-router work), the accepted cost (one extra connector), and the renamed field as the breadcrumb.
    Add a second todo for the D-30 deferral: per-account pre-trade throttle keying. Record that the
    global engine-wide cap IS wrong in a multi-account system for the same reason the global halt was —
    account A's order rate starves account B — but that unlike the halt it fails CONSERVATIVELY: it
    under-trades rather than mis-trades, costing opportunity rather than correctness. Given this
    phase's load that is the right thing to cut, and the shaped seam from the safety phase stays shaped.

    **Part C — the open question RESEARCH escalated.** Investigate whether two portfolios sharing one
    simulated exchange's resting-order book interfere on brackets or one-cancels-other. Orders carry a
    portfolio id, but the book is a single dictionary. Concretely: check whether resting-order storage,
    trigger evaluation, and one-cancels-other cancellation are keyed or filtered by portfolio, or
    whether a fill on portfolio A's bracket child could cancel portfolio B's sibling.

    **This must be answered before plan 11-11 writes the two-paper-account lifecycle test.** Do not
    assume safety from "no credentials are involved" — that is a different property. Record the finding
    in the plan summary. If interference exists it is a REAL multi-portfolio defect, not a test
    artifact: raise it, do not work around it in the test.

    `system_spec.py` is **TABS**; `okx_plugin.py` is 4-space.
  </action>
  <verify>
    <automated>poetry run python -m pytest tests -q</automated>
  </verify>
  <acceptance_criteria>
    - `poetry run python -m pytest tests -q` exits 0.
    - The old system-spec field name survives nowhere:
      `grep -rn '<old field name>' itrader/ tests/ scripts/` returns nothing (substitute the actual
      identifier at execution time).
    - The renamed field's docstring states it is data-provider-scoped and names the deferral.
    - `.planning/todos/pending/data-provider-connector-account-model.md` exists.
    - A second todo file recording the per-account throttle-keying deferral exists in the same directory.
    - The plan summary records an explicit finding for the shared-resting-book question — either
      "no interference, evidence: <the keying/filtering that makes it safe>" or
      "interference exists, shape: <what crosses>" — not "appears fine".
    - Added lines in `system_spec.py` carry no space indentation:
      `git diff -U0 -- itrader/trading_system/system_spec.py | grep -cP '^\+    [^ ]'` returns 0.
    - `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` exits 0.
    - `poetry run python -m pytest tests/integration/test_okx_inertness.py -q` exits 0.
    - `poetry run mypy` exits 0.
  </acceptance_criteria>
  <done>The field that only the data arm reads is named for the data arm, both deferrals have todos with their rationale and accepted cost, and the shared-resting-book question has a recorded evidence-backed answer before the lifecycle test is written.</done>
</task>

</tasks>

<success_criteria>
- Link function, its `RuntimeError(>1)` guard, and the facade `_venue_account` singleton all deleted
- Reconnect re-snapshot and startup venue reconcile provably still function, tested through the real
  composition root rather than by field assignment
- Both prerequisites (11-08 invariant, 11-09 coordinator rehome) verified in code before deletion
- Deferral todos written; shared-resting-order-book question answered in writing
- Oracle byte-exact and OKX inertness green
</success_criteria>

<output>
Create `.planning/phases/11-multi-portfolio-live/11-07b-SUMMARY.md` when done.
</output>
