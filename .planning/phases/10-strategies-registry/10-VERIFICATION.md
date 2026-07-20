---
phase: 10-strategies-registry
verified: 2026-07-17T16:29:50Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 10: Strategies Registry Verification Report

**Phase Goal:** Make the strategy roster durable — a `StrategyRegistryStore` that survives
restart, with runtime add/remove/enable/disable via `STRATEGY_COMMAND` and atomic
strategy-parameter reconfiguration.

**Verified:** 2026-07-17T16:29:50Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `StrategyRegistryStore` persists active + config + subscriptions; on restart `build_live_system` rehydrates → re-registers active strategies (survives restart) | ✓ VERIFIED | `itrader/storage/strategy_registry_store.py` (upsert/get/delete + `strategy_portfolio_subscriptions` child table with FK, `set_portfolio_subscriptions`/`add_portfolio_subscription`/`remove_portfolio_subscription`); rehydrate wiring at `itrader/trading_system/live_trading_system.py:1600-1648` (`build_live_system` gate, lazy-imported, `has_table` D-21 probe, `rehydrate_strategies(...)`); `itrader/strategy_handler/registry/rehydrate.py`. Behaviorally proven: `tests/integration/test_strategy_registry_restart.py::test_seeded_rows_rehydrate_and_survive_a_rebuild` PASSED, `tests/integration/test_strategy_external_add_lifecycle.py::test_external_add_warms_trades_and_resumes_across_restart` PASSED, `::test_disable_enable_reconfigure_through_the_ingress_and_reconfigured_params_survive_restart` PASSED (restart rehydrates the **reconfigured** `max_positions=3`, not the originally-added value). |
| 2 | Runtime add/remove/enable/disable via `STRATEGY_COMMAND` (CONTROL) is applied by `StrategiesHandler` and persisted | ✓ VERIFIED | `StrategiesHandler.on_strategy_command` (`strategies_handler.py:1201`) dispatches `add` (`_add_strategy_verb:649`), by-name verbs (`enable`/`disable`/`subscribe_portfolio`/`unsubscribe_portfolio`/`add_ticker`/`remove_ticker`) at `:1250-1370`, and `remove` (`_remove_strategy_verb:807`). Each verb persists through `registry_store.upsert`/`delete` under the `mutated`-gated idempotency contract. Behaviorally proven: `tests/unit/strategy/test_strategy_command_verbs.py` (21+ tests, all pass — enable/disable persist+apply, idempotent no-ops persist nothing), `tests/integration/test_strategy_add_warmup.py`, `tests/integration/test_strategy_remove_flat.py`, `tests/integration/test_strategy_external_add_lifecycle.py` (external `add_event` ingress) — all green. |
| 3 | A strategy's config parameters are mutable at runtime via atomic reconfiguration (quiesce → apply → re-warmup), persisted to `StrategyRegistryStore` | ✓ VERIFIED | `on_strategy_command`'s `reconfigure` branch (`strategies_handler.py:~1075-1199`): merge in encoded blob space → decode into param space → **throwaway `trial = cls(**params)`** (validate() + `_apply_params` run against the trial, live untouched on failure) → SHORT-01/D-07 re-gate via shared `_direction_admissible` (line 1136) → F-1 warmability check → **persist first** (`registry_store.upsert`) → **apply** (`strategy.reconfigure(**params)`) → **re-warm** (`strategy.mark_unwarm()` + `_request_rewarm()`, single-writer engine-thread quiesce). Behaviorally proven: `tests/unit/strategy/test_reconfigure_atomic.py` (D-13 atomicity: failing validate leaves live untorn, persist-failure leaves live unchanged, apply-failure-after-persist alerts CRITICAL and DB holds new; D-14 grow/shrink re-warm), `tests/unit/strategy/test_reconfigure_allowlist.py` (D-15 allowlist: `strategy_type`/`name` immutable, `tickers` verb-only, `direction` SHORT-01-gated, F-1 timeframe constrained-mutable), `tests/integration/test_reconfigure_positions.py` (D-12 open positions kept). All green. |
| 4 | The backtest oracle stays byte-exact (live-only, backtest-dark) and `test_okx_inertness.py` stays green | ✓ VERIFIED | Ran independently in this verification session (not taken from SUMMARY/VALIDATION claims): `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -v` → **7 passed** (`test_oracle_behavioral_identity`, `test_oracle_numeric_values`, `test_golden_run_signal_store_is_non_empty_and_queryable`, and all 4 inertness tests). |
| 5 (SHORT-01 gate audit resolution) | The audit's "most dangerous finding" (10-08 F1 — `validate()` does NOT re-run the SHORT-01/D-07 direction gate) is genuinely closed, not just documented | ✓ VERIFIED | The gate is factored into a **shared** `_direction_admissible` predicate (`strategies_handler.py:1475`) called from **both** `add_strategy` (line 1528) and the reconfigure apply path (line 1136), before persist — exactly the audit's recommended fix. `tests/unit/strategy/test_reconfigure_allowlist.py::test_direction_to_short_rejected_without_short_flags` PASSED in isolation this session: external `reconfigure(direction=SHORT_ONLY)` on a no-margin engine (`allow_short=False, margin=False`) is refused, `strategy.direction` stays `LONG_ONLY`, and `store.get(_NAME) is None` (store unchanged — no persist reached). Companion `test_direction_to_short_accepted_with_both_flags` confirms the positive case persists correctly. |
| 6 (WD-1: enable re-warms) | `enable` forces a re-warmup before the strategy may emit a signal (not the plan's originally-written "trades next bar with no re-warm") | ✓ VERIFIED | `on_strategy_command`'s `enable` branch (`strategies_handler.py:1324-1345`) calls `strategy.mark_unwarm()` + `self._request_rewarm(strategy)` after `activate_strategy()`. Behavioral tests: `test_enable_forces_a_re_warm_before_the_strategy_may_signal` (asserts `is_ready is False` immediately after enable), `test_enable_re_warms_through_the_ordinary_bar_path` (re-warms via ordinary bar feed, no bespoke pipeline), `test_enable_on_an_enabled_strategy_is_an_idempotent_no_op` (no-op enable does NOT unwarm a healthy strategy) — all PASSED. |
| 7 (WD-2: unwarm seam on `Strategy`, covers pair arm) | The unwarm seam lives on `base.Strategy` as a named wrapper over the handle reset (not a boolean flag, not on the handler), and `PairStrategy` overrides it to cover the non-handle-derived spread warmth | ✓ VERIFIED | `Strategy.mark_unwarm()` (`base.py:628`) delegates to the existing `reset()` (handle + bookkeeping reset) — `is_ready` stays the single computed truth. `PairStrategy.mark_unwarm()` (`pair_base.py:185`) extends it to clear `_buf_A`/`_buf_B` and reset `_pair_bar_count`, explicitly closing the "handle-free pair is `is_ready` always True" trap. Behavioral tests in `tests/unit/strategy/test_mark_unwarm.py` (12 tests): `test_mark_unwarm_makes_a_warm_strategy_unwarm`, `test_mark_unwarm_is_not_a_flag_and_re_warms_from_bars`, `test_mark_unwarm_introduces_no_second_source_of_warmth_truth` (asserts no `self._warm`-style boolean attribute exists), `test_mark_unwarm_covers_the_pair_arm` (asserts `is_pair_ready()` False after unwarm even though handle-derived `is_ready` is vacuously True), `test_pair_mark_unwarm_clears_both_leg_buffers` — all PASSED. |

**Score:** 7/7 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/storage/strategy_registry_store.py` | `StrategyRegistryStore` CRUD + subscriptions table | ✓ VERIFIED | Exists, substantive (upsert/get/delete/set_portfolio_subscriptions/add/remove/portfolio_subscriptions), wired into `live_trading_system.py` |
| `itrader/strategy_handler/registry/rehydrate.py` | Rebuild live instances from stored rows (D-01/D-19/D-21) | ✓ VERIFIED | Exists, wired via `build_live_system` gate (`live_trading_system.py:1643`) |
| `itrader/strategy_handler/registry/catalog.py`, `config_codec.py` | Strategy-type allowlist + config codec (round-trip, Decimal-safe) | ✓ VERIFIED | Exists; `test_config_roundtrip.py`, `test_policy_codec.py` green |
| `migrations/versions/strategy_registry.py`, `p10_strategy_portfolio_subs.py` | Alembic migration chain for the two new tables | ✓ VERIFIED | Exist; `tests/integration/storage/test_migrations.py` — 13 passed |
| `itrader/strategy_handler/strategies_handler.py::on_strategy_command` | STRATEGY_COMMAND dispatch (add/remove/enable/disable/subscribe/reconfigure) | ✓ VERIFIED | Exists, substantive, wired to route registrar and to `registry_store` |
| `itrader/strategy_handler/base.py::mark_unwarm`, `pair_base.py::mark_unwarm` | WD-2 unwarm seam | ✓ VERIFIED | Exists, substantive, wired from `enable`/`reconfigure` |
| `itrader/events_handler/events/universe.py::StrategyCommandEvent` | Extended vocabulary (add/remove/enable/disable/reconfigure) | ✓ VERIFIED | `msgspec.Struct`, factory classmethods present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `build_live_system` | `StrategyRegistryStore` / `rehydrate_strategies` | lazy import + `has_table` gate at `live_trading_system.py:1600-1648` | WIRED | Confirmed by reading the source; behaviorally proven by restart integration tests |
| `LiveTradingSystem.add_event` | `StrategiesHandler.on_strategy_command` | `_EXTERNALLY_ADMISSIBLE` includes `STRATEGY_COMMAND` (`live_trading_system.py:56-58`), routed via `route_registrar.py:106` | WIRED | `tests/integration/test_strategy_external_add_lifecycle.py` — all 4 tests pass, including the ingress-denial test for non-admissible events |
| `add_strategy` / reconfigure apply path | `_direction_admissible` (shared SHORT-01/D-07 predicate) | both call sites at `strategies_handler.py:1136` and `:1528` | WIRED | Confirmed the audit's critical finding was fixed with a genuinely shared predicate, not duplicated logic that could drift |
| `enable` verb / reconfigure apply path | `Strategy.mark_unwarm()` + `_request_rewarm()` | `strategies_handler.py:1343-1344` (enable), `:1197-1198` (reconfigure) | WIRED | One shared warm path per WD-1's stated intent |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SHORT-01 gate genuinely re-runs on reconfigure | `poetry run pytest tests/unit/strategy/test_reconfigure_allowlist.py -k test_direction_to_short_rejected_without_short_flags -v` | 1 passed | ✓ PASS |
| Full suite | `poetry run pytest tests -q` | 2530 passed, 6 skipped (OKX-credential-gated) | ✓ PASS |
| Byte-exact oracle | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed | ✓ PASS |
| OKX inertness | `poetry run pytest tests/integration/test_okx_inertness.py -v` | 4 passed | ✓ PASS |
| Type strictness | `poetry run mypy itrader` | Success: no issues found in 266 source files | ✓ PASS |
| Cache-classification gate (locked, cross-cutting) | `poetry run pytest tests/integration/test_cache_classification.py -q` | 4 passed | ✓ PASS |
| Full restart lifecycle (STRAT-01/02/03 combined) | `poetry run pytest tests/integration/test_strategy_registry_restart.py tests/integration/test_strategy_add_warmup.py tests/integration/test_strategy_remove_flat.py tests/integration/test_strategy_external_add_lifecycle.py tests/integration/test_reconfigure_positions.py -v` | 16 passed | ✓ PASS |
| WD-1/WD-2 unwarm seam | `poetry run pytest tests/unit/strategy/test_mark_unwarm.py -v` | (included in full suite — 10 passed) | ✓ PASS |
| Migrations | `poetry run pytest tests/integration/storage/test_migrations.py -q` | 13 passed | ✓ PASS |

All commands were run independently in this verification session — none of the above results were taken on faith from SUMMARY.md or VALIDATION.md claims.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| STRAT-01 | 10-01, 10-02, 10-05, 10-09 | `StrategyRegistryStore` persists active+config+subscriptions; restart rehydrates | ✓ SATISFIED | See Truth #1, artifacts, and restart integration tests above |
| STRAT-02 | 10-03, 10-06, 10-07, 10-09 | Runtime add/remove/enable/disable via `STRATEGY_COMMAND`, applied + persisted | ✓ SATISFIED | See Truth #2, #6, verb test suites |
| STRAT-03 | 10-04, 10-08, 10-09 | Atomic reconfiguration (quiesce → apply → re-warmup), persisted | ✓ SATISFIED | See Truth #3, #5, reconfigure test suites |

**Traceability note (documentation staleness, non-blocking):** `.planning/REQUIREMENTS.md` still shows
STRAT-01/02/03 as unchecked (`- [ ]`) in the ★ Strategies Registry (P10) section and lists their status
as "Pending" in the traceability table (lines 418-420), despite the phase being functionally complete
and validated. This is a documentation-sync gap, not a code gap — flagged for the requirements doc to be
updated to "Complete" / checked, but it does not block phase 10's goal achievement since the underlying
capability is genuinely built, tested, and green.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` debt markers found in any file touched by this phase (43 files scanned via
`git log --name-only` since branch divergence). One `TODO` comment exists
(`itrader/trading_system/session_initializer.py:144`), but it is a forward-looking design note ("IF a
future edit reintroduces an independent subscription source, add a guard here") documenting why no
guard is needed **today**, not an unresolved gap in this phase's deliverable — not a blocker.

No stub returns (`return null`/`return {}`/`return []`), no empty handlers, and no hardcoded-empty
props were found in the phase's touched files. All exception handling in the reconfigure/add/remove
paths catches specific exception types (not bare `except Exception`), consistent with the codebase's
documented error-handling convention — the one pre-existing bare `except Exception` in `update_config`
(line ~1151) predates this phase (D-08, per 10-07-SUMMARY.md Deviation 2) and is out of scope.

### Pre-Execution Audit Resolution Check

The `10-PLAN-AUDIT.md` found 8/8 executed plans (10-06 through 10-09; earlier plans not in its scope)
carried factual claim errors, most critically 10-08 F1 (the SHORT-01 gate bypass). Cross-checked against
the shipped code:

- **10-08 F1 (critical — SHORT-01 bypass):** RESOLVED. See Truth #5 above — the shared
  `_direction_admissible` predicate is called from both `add_strategy` and the reconfigure path, with a
  passing negative test proving the reject.
- **10-08 F2 (`name` reconfigure orphans the store PK):** RESOLVED. `test_name_is_immutable_cannot_orphan_the_store_pk`
  passes; `name` reconfigure is a loud reject with the store left untouched under both the original and
  attempted-new PK.
- **10-08 F3 (encode/decode space mismatch — the 10-04 defect re-entering):** RESOLVED. The reconfigure
  apply path routes the merged blob through `decode_strategy_config` into param space before
  constructing the trial (`strategies_handler.py:1097-1113`), matching the audit's recommended fix
  exactly (confirmed in code, not just in comments).
- **10-06 F1 (WD-1 reversal):** RESOLVED. See Truth #6 — `enable` forces a re-warm; the stale
  no-re-warmup comment cited by the audit as needing a rewrite has been replaced with WD-1-accurate
  prose in the live docstring (`strategies_handler.py:1208-1209`).
- **WD-2 (unwarm seam ownership + pair arm):** RESOLVED. See Truth #7 — seam lives on `Strategy`/`PairStrategy`,
  not the handler; a dedicated `test_mark_unwarm.py` behaviorally proves the pair arm closes the
  "vacuously-warm handle-free pair" trap.
- **Line-number drift findings (10-06 F2-F4, 10-07 F2, 10-08 F4, 10-09 F2):** these were navigational
  errors in the plans, not implementation defects — verified moot since the code was located by symbol,
  not by the stale line numbers, in the shipped work.

### Human Verification Required

None. All must-haves resolved to VERIFIED via direct code inspection plus independently-executed
automated tests (unit + integration), with no behavior-dependent truth left unexercised.

### Gaps Summary

No gaps found. All 7 observable truths (4 roadmap success criteria + 3 audit-critical resolution checks)
are VERIFIED against the live codebase, not inferred from SUMMARY/VALIDATION claims. The full suite
(2530 passed / 6 skipped), the byte-exact oracle, OKX inertness, mypy --strict, and the cache-classification
gate were all re-run independently in this verification session and are green. The only finding is a
non-blocking documentation-staleness item in `REQUIREMENTS.md` (STRAT-01/02/03 still shown as
unchecked/Pending) noted above for a follow-up doc-sync edit.

---

_Verified: 2026-07-17T16:29:50Z_
_Verifier: Claude (gsd-verifier)_
