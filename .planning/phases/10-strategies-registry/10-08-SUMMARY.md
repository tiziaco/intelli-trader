---
phase: 10-strategies-registry
plan: 08
subsystem: strategy-handler
tags: [D-12, D-13, D-14, D-15, F-1, F-2, F-3, WD-2, SHORT-01, STRAT-03, oracle-gated]
requires:
  - phase: 10-04
    provides: "config_codec.encode/decode_strategy_config — the Decimal-safe blob<->param codec the merge routes through"
  - phase: 10-05
    provides: "registry/rehydrate.build_strategy + decode_strategy_config — the one reconstruction path the trial reuses"
  - phase: 10-06
    provides: "on_strategy_command dispatch skeleton + _PAIR_REFUSED_VERBS (reconfigure already refused for pairs)"
  - phase: 10-07
    provides: "self.feed F-1 gate seam, strategy_catalog/portfolio_read_model injection, _request_rewarm (WD-2)"
provides:
  - "StrategiesHandler._reconfigure_strategy_verb — D-13 trial-validate -> persist -> apply -> re-warm"
  - "StrategiesHandler._direction_admissible — the SHARED SHORT-01/D-07 gate called from add AND reconfigure (audit F1)"
  - "StrategiesHandler._reconfigure_allowlist_check + _reconfigure_warmability_check — D-15/F-1 gates"
  - "_RECONFIGURE_IMMUTABLE (strategy_type + name + warmup + max_window) / _RECONFIGURE_VERB_ONLY (tickers)"
affects:
  - "Plan 09 (restart lifecycle) — Test 3 disable->enable->reconfigure->restart rehydrates the reconfigured params"
  - "next milestone — pair reconfiguration (D-17 deferred) + finer-than-base feed re-subscribe (F-1 ring resize)"
tech-stack:
  added: []
  patterns:
    - "trial-construct cls(**params) on a throwaway to close a validate()/_run_init() tear before touching the live instance"
    - "factor a handler-policy admission predicate (SHORT-01) into a shared method so add and reconfigure cannot drift"
    - "route a config MERGE through decode_strategy_config so blob<->param coercions (Decimal) round-trip; never hand-strip"
    - "persist-then-apply asymmetry: persist-fail propagates untouched; apply-fail emits CRITICAL and heals on restart"
key-files:
  created:
    - tests/unit/strategy/test_reconfigure_atomic.py
    - tests/unit/strategy/test_reconfigure_allowlist.py
    - tests/integration/test_reconfigure_positions.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
key-decisions:
  - "audit F1 BUILT not assumed: validate() does NOT re-run SHORT-01 (it is a no-op window-shape hook), so the gate was factored into _direction_admissible and called on the reconfigure apply path against the trial's direction — NOT pushed into Strategy.validate() (D-12 pure-alpha boundary)."
  - "audit F2: name (store PK) + strategy_type + warmup/max_window (_DERIVED_FIELDS) are in _RECONFIGURE_IMMUTABLE — a rename would orphan the PK row."
  - "audit F3: the merge is in ENCODED blob space and routed THROUGH decode_strategy_config, so Decimal knobs round-trip as Decimal, not str '2' (the 10-04 defect)."
  - "CODE REALITY over plan text (D-14): Strategy.reconfigure -> _run_init unconditionally resets handle state, so EVERY applied reconfigure of a handle-bearing strategy goes DARK and re-warms via the WD-2 seam — the plan's grew/shrank/unchanged 'stays warm' premise is false against the live tree (verified)."
  - "base.py was NOT touched — the merge is built from encode/decode alone and the direction gate is handler-side, so the oracle is safe by construction (re-run byte-exact anyway)."
patterns-established:
  - "reconfigure verb: allowlist -> merge -> trial-validate -> direction re-gate -> warmability -> persist -> apply -> re-warm"
  - "warmability gate evaluated against the TRIAL (its resolved warmup/timeframe) covers timeframe change AND window-grow over-capacity — a strict superset of the plan's timeframe-only scoping"
requirements-completed: [STRAT-03]
coverage:
  - id: D1
    description: "Atomic reconfigure: a cross-field validate() failure leaves the live strategy completely untorn (D-13 trial-validate)."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_atomic.py#test_a_failing_validate_leaves_the_live_strategy_untorn"
        status: pass
    human_judgment: false
  - id: D2
    description: "SHORT-01 direction re-gate: an external reconfigure(direction=SHORT_ONLY) on a no-margin engine is loud-rejected; accepted only with both flags (audit F1 / T-10-55)."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_allowlist.py#test_direction_to_short_rejected_without_short_flags"
        status: pass
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_allowlist.py#test_direction_to_short_accepted_with_both_flags"
        status: pass
    human_judgment: false
  - id: D3
    description: "name is immutable via reconfigure — cannot orphan the store PK (audit F2)."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_allowlist.py#test_name_is_immutable_cannot_orphan_the_store_pk"
        status: pass
    human_judgment: false
  - id: D4
    description: "Merge routed through decode_strategy_config: omitted fields keep prior values and the persisted blob is the full post-merge set with Decimal fidelity (audit F3 / P-4)."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_atomic.py#test_partial_payload_merges_and_persists_the_full_set_merge"
        status: pass
    human_judgment: false
  - id: D5
    description: "Persist/apply asymmetry: persist-fail leaves live untouched; apply-fail emits CRITICAL with the DB holding the new config (D-13)."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_atomic.py#test_persist_failure_leaves_the_live_instance_unchanged"
        status: pass
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_atomic.py#test_apply_failure_after_persist_alerts_critical_and_db_holds_new"
        status: pass
    human_judgment: false
  - id: D6
    description: "D-15/F-1 timeframe constrained-mutable gate: coarser-or-equal within capacity accepted + warmable; finer/unknown/over-capacity rejected."
    requirement: "STRAT-03"
    verification:
      - kind: unit
        ref: "tests/unit/strategy/test_reconfigure_allowlist.py#test_timeframe_over_ring_capacity_is_rejected_boundary"
        status: pass
    human_judgment: false
  - id: D7
    description: "D-12: reconfigure keeps open positions (no force-flat) and applies new params live end-to-end."
    requirement: "STRAT-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_reconfigure_positions.py#test_reconfigure_keeps_the_open_position_and_applies_new_params"
        status: pass
    human_judgment: false
  - id: D8
    description: "Backtest oracle byte-exact (base.py untouched) + OKX inertness + @cache classification unchanged."
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false
duration: 75min
completed: 2026-07-17
status: complete
---

# Phase 10 Plan 08: Atomic `reconfigure` — trial-validate, persist, apply, re-warm Summary

**A trial-construct atomicity contract for the `reconfigure` verb that closes the phase's one CRITICAL hole — the SHORT-01 direction gate that `validate()` never actually ran — by BUILDING the missing shared gate rather than assuming it.**

## Performance

- **Duration:** ~75 min
- **Completed:** 2026-07-17
- **Tasks:** 3 (2 TDD + 1 integration)
- **Files created:** 3 · **Files modified:** 1

## Accomplishments
- **audit F1 (the phase's most dangerous finding) — the SHORT-01 gate is BUILT, not assumed.** `Strategy.validate()` is a no-op window-shape hook that never checks `direction`, and the SHORT-01 gate reads HANDLER state, so the plan's "`validate()` re-runs the gate" premise was false — a trial construction could never admit-gate a short. The predicate is now factored into `_direction_admissible`, shared by `add_strategy` AND the reconfigure apply path (called against the TRIAL's resolved direction, before persist). An external `reconfigure(direction=SHORT_ONLY)` on a no-margin engine is loud-rejected (T-10-55). Test 15's RED was resolved by adding the gate — NOT by adjusting a fixture.
- **D-13 atomicity via a THROWAWAY.** The merged config is trial-constructed (`cls(**params)`) before the live instance is touched, so a cross-field `validate()` failure raises against the throwaway and leaves the live strategy untorn.
- **audit F2 — `name` (the store PK) is immutable**, alongside `strategy_type` and the derived `warmup`/`max_window`; a rename can no longer orphan the registry row.
- **audit F3 — the merge routes THROUGH `decode_strategy_config`**, so Decimal knobs round-trip as `Decimal`, not the str `'2'` (the 10-04 defect re-entering). Verified against a live probe (`FractionOfCash(fraction=Decimal('0.95'))` survived the round-trip).
- **D-13 persist/apply asymmetry, D-15/F-1 timeframe gate, D-12 keep-positions** — all shipped and gated.

## Task Commits

1. **Task 1: Wave-0 RED tests** — `8c42ac9f` (test) — 23 tests; RED (12 fail requiring the verb).
2. **Task 2: reconfigure verb + shared SHORT-01 gate + merge/decode/persist/apply/re-warm** — `907f8e68` (feat).
3. **Task 3: D-12 keep-positions integration** — `6cdee57b` (test).

_TDD: RED (`8c42ac9f`) → GREEN (`907f8e68`)._

## Files Created/Modified
- `itrader/strategy_handler/strategies_handler.py` — `_reconfigure_strategy_verb`, `_direction_admissible` (shared SHORT-01 gate; `add_strategy` refactored to use it), `_reconfigure_allowlist_check`, `_reconfigure_warmability_check`, `_emit_reconfigure_apply_failure`, the two deny-list constants, and the `reconfigure` dispatch in `on_strategy_command`.
- `tests/unit/strategy/test_reconfigure_atomic.py` — D-13/P-4/D-14/D-12 (12 tests).
- `tests/unit/strategy/test_reconfigure_allowlist.py` — D-15/F-1/F-2/direction/D-17 (11 tests).
- `tests/integration/test_reconfigure_positions.py` — D-12 end-to-end (2 tests).

## Decisions Made
- **The direction gate is handler-side, never in `Strategy.validate()`** (audit F1's explicit instruction) — threading handler flags onto every strategy would invert the D-12 pure-alpha boundary.
- **The warmability gate runs against the TRIAL and on every reconfigure** (a live feed), so it covers both a timeframe change and a window-grow that would exceed ring capacity — a strict superset of the plan's timeframe-only scoping.
- **`base.py` was NOT touched.** The merge is built from `encode_strategy_config`/`decode_strategy_config` alone (no `current_authoring_params()` accessor needed), and the gate is handler-side. The oracle is safe by construction; re-run byte-exact anyway.
- **Persist-fail propagates as infrastructure** (matching `_add_strategy_verb` and rehydrate's D-19 fail-loud arm) rather than a silent no-op — the live instance is untouched because persist precedes apply, so the invariant D-13 protects (no applied-but-unpersisted divergence) holds. No NEW broad `except` was added.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-14 "shrank/unchanged stays warm" is FALSE against the live tree — every applied reconfigure goes dark**
- **Found during:** Task 1 (writing the D-14 tests)
- **Issue:** The plan (must_haves + Task 2 step 6) asserts a reconfigure that shrinks/keeps the window "stays WARM -> trades immediately." Empirically (probe: warm SMA_MACD → `reconfigure(short_window=10)` → `is_ready` False), `Strategy.reconfigure` → `_run_init` UNCONDITIONALLY resets `_handles`/`_handle_state_store` (`base.py:409/426`), so ANY applied reconfigure of a handle-bearing strategy goes dark. The "stays warm" path does not exist through `strategy.reconfigure`.
- **Fix:** Adopted the code-true, safe behavior: every applied reconfigure re-warms via the WD-2 seam (`mark_unwarm` + `_request_rewarm` + poll — one warm path, WD-1). A genuine no-op (empty or identical payload) short-circuits before `strategy.reconfigure` and stays warm. Tests 6/7/8 rewritten to assert dark+re-warm; Tests 9/10 assert the no-op stays warm. Preserving warmth across config-only changes would require a conditional `_run_init` on the base HOT PATH (oracle risk) — deferred.
- **Files modified:** strategies_handler.py; test_reconfigure_atomic.py
- **Verification:** `test_reconfigure_config_change_goes_dark_and_rewarms` + the idempotency/empty tests pass; oracle byte-exact.
- **Committed in:** `907f8e68` / `8c42ac9f`

**2. [Rule 1 - Bug] The "non-multiple timeframe" reject (Test 18) is unreachable via a valid alias**
- **Found during:** Task 1 (designing the timeframe tests)
- **Issue:** The `Timeframe` vocab (1m/5m/15m/1h/4h/1d/1w) has NO coarser NON-multiple pair — every coarser member is a whole multiple of every finer one — so `required_base_depth`'s non-multiple branch cannot be reached through a valid operator payload.
- **Fix:** Tested the reachable analog — an UNKNOWN timeframe alias (`"2h"`) is a loud reject via `Timeframe` coercion in the trial construction (`test_timeframe_unknown_alias_is_rejected`). The finer-than-base and over-capacity arms (Tests 17/19) are reachable and tested directly.
- **Files modified:** test_reconfigure_allowlist.py
- **Committed in:** `8c42ac9f`

**3. [Rule 2 - Missing Critical] Persisted `enabled` must be the LIVE strategy's activation, not the trial's**
- **Found during:** Task 2 (implementing persist)
- **Issue:** A fresh trial instance is always `is_active=True`; persisting `enabled=trial.is_active` would silently re-enable a DISABLED strategy on reconfigure.
- **Fix:** Persist `enabled=strategy.is_active` (the live activation), `config=encode_strategy_config(trial)` (the trial's full authoring set).
- **Files modified:** strategies_handler.py
- **Committed in:** `907f8e68`

---

**Total deviations:** 3 (2 code-reality corrections, 1 missing-critical). **Impact:** No scope creep — deviations 1/2 are the audit's "the code wins" directive applied to two stale plan premises; deviation 3 is a correctness fix. The audit's four findings (F1–F4) were all handled as specified.

## Issues Encountered
- None beyond the deviations above. The audit's guidance was precise and every finding reproduced against the tree exactly as described.

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-50 | mitigated | D-13 trial construction closes the validate()/_run_init() tear (Test 1). |
| T-10-51 | mitigated | Persist-fail leaves live untouched (propagates); apply-fail emits CRITICAL, DB correct (Tests 2/3). |
| T-10-52 | mitigated | Persisted blob is `encode_strategy_config(trial)` — the full post-merge set (Test 4). |
| T-10-53 | mitigated | F-1 capacity gate against the trial rejects an unwarmable timeframe (Tests 17/19). |
| T-10-54 | mitigated | D-17 pair refusal via the Plan 06 verb-scoped guard (Test 20). |
| T-10-55 | mitigated | **BUILT** the shared SHORT-01 gate `_direction_admissible`, called on the reconfigure apply path (Test 15) — the plan's assumed mechanism did not exist. |
| T-10-56 | mitigated | `strategy_type` (and `name`) in `_RECONFIGURE_IMMUTABLE`, rejected before construction (Tests 12/name). |
| T-10-57 | mitigated | `base.py` untouched + reconfigure is live-only; byte-exact oracle re-verified. |
| T-10-58 | mitigated | The apply-fail CRITICAL binds `strategy_name` + error KIND only (Test 3). |
| T-10-59 | accept | Rate limiting deferred to the FastAPI layer (unchanged). |

## Known Stubs
None. The verb is fully wired end-to-end and proven on an offline integration driver.

## Threat Flags
None. The one new operator-facing surface (the reconfigure payload) is gated by the deny-lists, the trial-validate, the SHORT-01 re-gate, and the F-1 warmability gate; no new network endpoint or schema change.

## Verification Results

| Gate | Result |
|------|--------|
| **Backtest oracle (MANDATORY, byte-exact 134 / `46189.87730727451`)** | **PASS** (3 passed; base.py untouched) |
| **OKX inertness (MANDATORY)** | **PASS** (4 passed) |
| `test_cache_classification.py` (the `@cache` trap) | **PASS** (4 passed — no memoization added) |
| `test_reconfigure_atomic.py` + `test_reconfigure_allowlist.py` | **PASS** (23) |
| `test_reconfigure_positions.py` | **PASS** (2) |
| `test_pair_dispatch.py -k reconfigure` (D-17) | **PASS** (1) |
| existing verb/update_config/registration suites | **PASS** (58) |
| **FULL tree `pytest tests` (incl. `tests/e2e`)** | **PASS — 2526 passed, 6 skipped** (OKX creds absent) |
| `mypy --strict` (whole package) | **clean (244 files)** |

**Source gates:** space-indent lines = 0 (stays TABS) · base.py untouched · `_RECONFIGURE_IMMUTABLE` = 3 · `_RECONFIGURE_VERB_ONLY` = 2 · `required_base_depth` = 6 · D-12/D-13/D-14/D-15/F-1 all ≥ 1 · `eval(` = 0 · NEW `except Exception` = 0 (the one match is the pre-existing `update_config` D-08 wrapper) · `caplog` in atomic test = 0 · no `__init__.py` in the test dirs · `-k merge`=2, `-k warm`=3, `-k timeframe`=4.

All runs used `PYTHONPATH="$PWD"` to defeat worktree `.venv` shadowing; the FULL tree (incl. `tests/e2e`) was gated.

## Next Phase Readiness
- Plan 09 (restart lifecycle) can now drive `disable → enable → reconfigure → restart` and assert the row rehydrates the RECONFIGURED params.
- Deferred (next milestone): pair reconfiguration (D-17) and the finer-than-base feed re-subscribe + ring resize (F-1), both already tracked under `.planning/todos/pending/`.

## Self-Check: PASSED

- `itrader/strategy_handler/strategies_handler.py` — FOUND (modified)
- `tests/unit/strategy/test_reconfigure_atomic.py` — FOUND, tracked
- `tests/unit/strategy/test_reconfigure_allowlist.py` — FOUND, tracked
- `tests/integration/test_reconfigure_positions.py` — FOUND, tracked
- Commits `8c42ac9f`, `907f8e68`, `6cdee57b` — all verified in `git log`
- Working tree clean; no deletions across the branch; no STATE.md / ROADMAP.md changes (orchestrator-owned)

## TDD Gate Compliance

Task 1 & 2 followed RED → GREEN: `test(10-08) 8c42ac9f` (12 failing / 11 trivially-green) → `feat(10-08) 907f8e68` (all 23 green). Each RED failed for the intended reason (the verb was an unknown-verb no-op). Task 3 is an integration task (no RED gate required). No REFACTOR commits — none needed.

---
*Phase: 10-strategies-registry*
*Completed: 2026-07-17*
