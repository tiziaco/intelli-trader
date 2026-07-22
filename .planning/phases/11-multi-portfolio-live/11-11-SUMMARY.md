---
phase: 11-multi-portfolio-live
plan: 11
subsystem: testing
tags: [multi-portfolio, lifecycle, fill-attribution, restart, rehydrate, paper, postgres-gated, D-25, MPORT-03, MPORT-04, F-1, D-08]

requires:
  - phase: 11-07
    provides: "per-account bundles/connectors/exchanges + the shared simulated exchange"
  - phase: 11-08
    provides: "PortfolioDefinitionStore writer + rehydrate_portfolios + assert_distinct_accounts"
  - phase: 11-09
    provides: "_attach_venue_accounts + per-portfolio reconcile + venue-truth cash edge (D-15)"
  - phase: 11-10
    provides: "matching_engine OCO cross-portfolio-safety finding (parent_order_id global uniqueness)"
provides:
  - "tests/integration/test_multi_portfolio_lifecycle.py — the phase's D-25 end-to-end proof (10 tests: 8 offline paper + 2 Postgres-gated restart)"
  - "the offline two-paper-account harness (_PaperPair) driving independent sizing + fill attribution with the negative"
  - "the real teardown+rebuild restart proof (stable ids, persisted cash + config by value, subscription rebind)"
  - "11-VALIDATION.md closed out — Per-Task Verification Map populated, Wave 0 checklist ticked, wave_0_complete: true, status: validated"
affects: [milestone-close, gsd-verify-work, gsd-secure-phase]

tech-stack:
  added: []
  patterns:
    - "mutation-test every gate: break the behaviour, confirm RED, revert to an empty diff (proof the test can fail)"
    - "assert the NEGATIVE for attribution — snapshot the OTHER portfolio before the fill, compare byte-for-byte after"
    - "the load-bearing sizing proof is qty_A != qty_B BECAUSE cash_A != cash_B (different starting cash), not two non-identical account objects (vacuous)"
    - "restart proof reads initial_cash + config off the DEFINITION ROW, never portfolio.cash (venue-truth raises pre-snapshot, D-15)"
    - "bracket-free MARKET orders side-step the shared resting-order book (11-10 OCO finding) for determinism"

key-files:
  created:
    - tests/integration/test_multi_portfolio_lifecycle.py
  modified:
    - .planning/phases/11-multi-portfolio-live/11-VALIDATION.md

key-decisions:
  - "SPLIT DELIVERY honoured (audit_corrections wins): Tasks 1 & 2 OFFLINE on build_paper_replay_system (no Docker); Task 3 Postgres-gated real restart. Not one offline recipe."
  - "Both paper portfolios name DEFAULT_ACCOUNT_ID and resolve to ONE simulated exchange object — the F-3 reality. NO per-account routing assertion is made here; that gate lives in test_per_account_exchange_routing.py (11-06)."
  - "Task 3 modelled on test_distinct_account_invariant.py::test_a_persisted_portfolio_survives_a_full_teardown_and_rebuild, NOT test_paper_restart_restore.py's offline recipe (which is unfalsifiable: _no_pg_env → no definition rows → rebinds a double to the SAME object)."
  - "Subscription-rebind (Task 3b) modelled on test_strategy_registry_restart.py — a real strategy registry rehydrate across a rebuild, subscribed to the two portfolio ids."

patterns-established:
  - "Mutation table in the SUMMARY: every gate broken once, RED observed, reverted."
  - "Offline paper lifecycle harness reusable for future multi-portfolio proofs."

requirements-completed: [MPORT-03, MPORT-04]

coverage:
  - id: D1
    description: "Two paper accounts trade independently — DIFFERENT cash → qty_A != qty_B (2:1 exact); one signal fans out to each subscribed portfolio; draining A leaves B able to order."
    requirement: MPORT-03
    verification:
      - kind: integration
        ref: "tests/integration/test_multi_portfolio_lifecycle.py#test_each_portfolio_sizes_against_its_own_cash (+ fans_out, distinct_account, draining)"
        status: pass
    human_judgment: false
  - id: D2
    description: "A fill reaches exactly one portfolio and leaves the other byte-unchanged (both directions); two portfolios hold independent positions in one symbol; the durable order row carries the ordering portfolio id."
    requirement: MPORT-04
    verification:
      - kind: integration
        ref: "tests/integration/test_multi_portfolio_lifecycle.py#test_a_fill_for_a_changes_a_and_leaves_b_byte_unchanged (+ fill_for_b, same_symbol, durable_order_row)"
        status: pass
    human_judgment: false
  - id: D3
    description: "REAL restart: a second build_live_system over the same DB returns both ids from the definition rows; initial_cash + config_json read off the ROW equal persisted (config by value); strategy subscriptions rebind to the same ids."
    requirement: MPORT-03
    verification:
      - kind: integration
        ref: "tests/integration/test_multi_portfolio_lifecycle.py#test_a_full_restart_returns_both_portfolios_with_stable_ids (+ rebind); Postgres-gated, ran (Docker up)"
        status: pass
    human_judgment: false

duration: ~70min
completed: 2026-07-22
status: complete
---

# Phase 11 Plan 11: Multi-Portfolio Lifecycle — the Phase's Own Proof Summary

**One integration file (10 tests) that actually demonstrates two accounts trading independently, fill attribution with the negative asserted, and a real teardown+rebuild restart with stable ids — every gate mutation-tested to prove it can fail.**

## Performance

- **Duration:** ~70 min
- **Completed:** 2026-07-22
- **Tasks:** 3 (single test file, TDD-style RED probes first)
- **Files modified:** 2 (1 created, 1 doc)

## Accomplishments

- **Tasks 1 & 2 (offline, two paper accounts):** built `_PaperPair` on the offline
  `build_paper_replay_system` seam. Two portfolios with DIFFERENT cash size independently —
  `qty_A == 500`, `qty_B == 250` (exactly 2:1, the cash ratio, zero fees on the paper venue).
  One signal fans out through the REAL `StrategiesHandler.on_bar` loop to each subscribed
  portfolio. A fill for A changes A and leaves B **byte-for-byte unchanged** (cash, positions,
  transaction count — asserted both directions on real `Portfolio` objects). Two portfolios hold
  independent positions in one symbol; each filled order row carries only its own portfolio id.
- **Task 3 (Postgres-gated, real restart):** two portfolios created through the real
  `add_portfolio` on a booted engine → teardown → a SECOND `build_live_system` over the SAME
  database returns BOTH ids from the definition rows, with names/account-ids/`initial_cash`/
  `config_json` read off the ROW equal to what was persisted (config compared by VALUE, not
  non-null). A companion test proves a strategy's portfolio subscriptions rebind to the SAME two
  ids across a rebuild, so the fan-out still reaches both.
- **Every gate mutation-tested** (table below). No production code touched; oracle byte-exact;
  zero new dependencies.
- **`11-VALIDATION.md` closed:** Per-Task Verification Map populated, Wave 0 checklist ticked,
  `wave_0_complete: true`, `status: validated`.

## Task Commits

Single atomic commit (one test file + the validation doc; splitting would leave an
importable-but-incomplete file with no benefit):

1. **Tasks 1–3: multi-portfolio lifecycle proof + VALIDATION close-out** — `test(11-11)`

**Plan metadata:** included in the same commit (SUMMARY added in the docs commit).

## Files Created/Modified

- `tests/integration/test_multi_portfolio_lifecycle.py` — the D-25 lifecycle proof: 8 offline
  paper tests (independent sizing, fan-out, cash isolation, fill attribution with the negative,
  same-symbol independence, order-row attribution) + 2 Postgres-gated restart tests (stable ids +
  config by value; subscription rebind). 4-space, no explicit marker, no `__init__.py`.
- `.planning/phases/11-multi-portfolio-live/11-VALIDATION.md` — Per-Task Verification Map filled;
  Wave 0 checklist closed; `wave_0_complete: true`; `status: validated`.

## Mutation Testing

Every gate was broken once, observed RED, and reverted to an empty diff. **No gate was green
with its behaviour absent.**

| # | Gate | Mutation | Result |
|---|------|----------|--------|
| M1 | fan-out reaches both portfolios | subscribe only `pid_a` | RED — `test_one_signal_fans_out_to_each_subscribed_portfolio` |
| M2 | independent sizing (load-bearing) | give both portfolios EQUAL cash | RED — `test_each_portfolio_sizes_against_its_own_cash` |
| M3 | attribution NEGATIVE | fill B instead of A in the A-fill test | RED — `test_a_fill_for_a_changes_a_and_leaves_b_byte_unchanged` (both the positive AND the negative failed) |
| M4 | durable order-row attribution | portfolio B never orders (its filled set empties) | RED — `test_the_durable_order_row_carries_the_ordering_portfolio_id` |
| M5 | config-by-value across restart | persist `config=None` for id_a | RED — `test_a_full_restart_returns_both_portfolios_with_stable_ids` (equality gate caught it — proves it is NOT a non-null check, closing T-11-60) |
| M6 | subscription rebind | seed the strategy subscribed to only `id_a` | RED — `test_a_strategy_subscription_rebinds_to_the_same_portfolio_ids_across_a_restart` |

Each mutation was reverted and the full file re-verified (10 passed) before proceeding.

## Decisions Made

- **Split delivery honoured (audit block wins over task bodies).** Tasks 1 & 2 stay OFFLINE on
  `build_paper_replay_system` (compute accounts, `.cash` readable immediately, no Docker); only
  Task 3 is the Postgres-gated real restart. The plan bodies pointed at
  `test_paper_restart_restore.py`'s offline recipe for the restart — that recipe is UNFALSIFIABLE
  (`_no_pg_env` forces the in-memory fallback, so no definition rows persist and its "restart"
  rebinds a double to the SAME object; id stable by construction). Task 3 is modelled on
  `test_distinct_account_invariant.py::test_a_persisted_portfolio_survives_a_full_teardown_and_rebuild`.
- **F-3 boundary respected.** Both paper portfolios name `DEFAULT_ACCOUNT_ID` and resolve to ONE
  simulated exchange object; NO per-account routing assertion is made here (it would pass while
  proving nothing). The docstring states this and names where the real gate lives
  (`test_per_account_exchange_routing.py`, 11-06).
- **Load-bearing sizing = different cash.** Two non-identical account objects is vacuous (every
  `add_portfolio` builds its own `SimulatedCashAccount`), so it is asserted only as a secondary
  check; the real proof is `qty_A != qty_B BECAUSE cash_A != cash_B`.
- **Bracket-free MARKET orders** are used offline so the shared matching-engine resting book is
  never engaged — consistent with 11-10's recorded finding that cross-portfolio OCO isolation is
  safe (globally-unique `parent_order_id`). No interference case needed to be designed around.
- **`initial_cash`/`config` read off the definition ROW** in the restart test, never
  `portfolio.cash` — the rebuilt account is venue-truth and raises until the first snapshot (D-15,
  the 11-09 cash sharp edge).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `live_db` fixture must register the strategy stores**
- **Found during:** Task 3 (running the Postgres-gated tests).
- **Issue:** The copied `_purge` deletes `strategy_portfolio_subscriptions` / `strategy_registry`
  rows (needed to keep the session-scoped container clean for the 3b subscription test), but the
  `live_db` fixture only constructed `PortfolioDefinitionStore` + `VenueAccountStore`, so those
  strategy tables were never registered on the engine's `metadata` → `KeyError` in `_purge`.
- **Fix:** construct `StrategyRegistryStore(engine)` in `live_db` too, so `provision_schema`
  creates all four tables and `_purge` can clear them.
- **Files modified:** `tests/integration/test_multi_portfolio_lifecycle.py` (test-only).
- **Verification:** both Postgres-gated tests pass; full suite green.
- **Committed in:** the single task commit.

---

**Total deviations:** 1 auto-fixed (1 blocking). Test-only; no production impact, no scope creep.

## Plan drift found

- **The plan bodies' restart recipe was wrong; the `<audit_corrections>` block was right.** As the
  block warned, `test_paper_restart_restore.py`'s recipe cannot prove a real restart. Followed the
  block (Task 3 modelled on the distinct-account invariant restart test). Recorded here per
  CODE_WINS.
- **Task 1's `<action>` says to seed durable rows then drive the offline start recipe.** Audit #3
  overrides: Tasks 1 & 2 stay offline on `build_paper_replay_system` with `add_portfolio` (no
  durable rows). Followed the block.
- **11-07's summary left the shared resting-book question "open".** 11-10 ITEM 2 actually recorded
  the answer (OCO isolation is safe via globally-unique `parent_order_id`). Used bracket-free
  MARKET orders to keep the offline gates deterministic regardless; no interference was designed
  around and none needed to be.
- **Paper venue charges no fee in this harness** — offline fills are exact (`0.5 * cash / price`),
  which let the sizing gate assert exact quantities (500 / 250) rather than a fee-tolerant ratio.

## Issues Encountered

- One residual Wave-0 doc item is a **cosmetic** stale docstring in
  `tests/integration/test_paper_restart_restore.py:6,15` (still references the deleted
  `_link_venue_account_to_portfolios` / `_venue_account` in prose). The executable test passes; it
  is out of this plan's file scope. Marked `[~]` in `11-VALIDATION.md` and carried as doc hygiene,
  not a coverage gap.

## User Setup Required

None — no external service configuration required. The restart tests use the shared
session-scoped testcontainers Postgres and SKIP cleanly when Docker is unavailable.

## Next Phase Readiness

- This is D-28, the W7 test boundary and the **last wave of the phase**. The phase now has its own
  end-to-end proof: two accounts trade independently, fills attribute correctly (negative
  asserted), and a real restart returns stable ids with persisted cash + config.
- Two manual-only verifications remain (real-venue two-account routing on OKX demo; venue-UID TOFU
  against a real venue) — documented in `11-VALIDATION.md § Manual-Only Verifications`, deferred to
  the milestone owner because this project has only one demo account and it cannot reach a fill.
- Phase-wide gates green: full suite 2813 passed / 6 skipped, oracle byte-exact
  (134 / 46189.87730727451), OKX inertness green, `mypy` clean, zero dependency change.

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/integration/test_multi_portfolio_lifecycle.py -q` | 10 passed |
| `pytest tests -q` | 2813 passed / 6 skipped (baseline 2803 / 6) |
| `pytest tests/integration/test_backtest_oracle.py -q` | pass (byte-exact 134 / 46189.87730727451) |
| `pytest tests/integration/test_okx_inertness.py -q` | pass |
| `mypy` | Success, 259 source files |
| `git diff -- itrader/` | EMPTY (test-only) |
| `git diff --stat -- pyproject.toml poetry.lock` | empty (zero new deps) |
| tabs in the new 4-space file | 0 |
| `grep -c 'pytest.mark.integration'` in the new file | 0 (folder-derived) |
| `tests/integration/__init__.py` | absent |

## Self-Check: PASSED
