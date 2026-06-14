---
phase: 02-strategy-authoring-surface
plan: 03
subsystem: strategy_handler
tags: [strategy, authoring-surface, kwargs-migration, byte-exact-gate, test-migration, STRAT-01]
requires:
  - "Strategy ABC **kwargs introspection engine + init/validate/reconfigure hooks (Plan 02-02)"
  - "UnknownParamError / MissingParamError (Plan 02-01)"
  - "SignalRecord.config retyped to dict snapshot (Plan 02-02)"
provides:
  - "All strategy construction sites migrated to the **kwargs surface (D-05, no shim)"
  - "Class-attribute-surface unit tests (unknown/missing/override/coerce/no-coerce/validate/idempotent/reconfigure/dict-snapshot)"
  - "Green byte-exact phase gate: oracle 134/46189.87730727451, e2e 58/58, mypy --strict clean, full suite green, determinism identical"
affects:
  - "Phase 2 closes STRAT-01 — the reference strategy authors through the new surface with zero numerical drift"
  - "Phase 3 IND-01 / Phase 4 COMP-02 author against the same migrated **kwargs construction surface"
tech-stack:
  added: []
  patterns:
    - "Construction-site migration: BaseStrategyConfig(...) + super().__init__(name, config) -> super().__init__(**kwargs); name/max_window pinned as class attrs on fixtures"
    - "record.config is a dict snapshot (strategy.to_dict()) — assert with == (fresh dict per call), never identity is; model_dump() retired"
    - "missing-required tested via EmptyStrategy (does not pin sizing_policy/tickers); non-coercion tested via max_positions (a non-_COERCE base knob)"
key-files:
  created: []
  modified:
    - tests/unit/strategy/test_strategy_config.py
    - tests/unit/strategy/test_strategy.py
    - tests/unit/strategy/test_signal_store.py
    - tests/e2e/strategies/scripted_emitter.py
    - tests/e2e/strategies/single_market_buy.py
    - scripts/run_backtest.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_universe_spans.py
    - tests/integration/test_reservation_inertness.py
    - tests/integration/test_backtest_oracle.py
  deleted: []
decisions:
  - "missing-required (MissingParamError) is asserted via EmptyStrategy, not SMAMACDStrategy — SMA pins sizing_policy as a class attr, so omitting it on SMA would not miss. EmptyStrategy declares no sizing_policy/tickers, so the bare base annotation stays required and the engine raises (D-07)."
  - "non-coercion (no-coerce-int) is asserted via max_positions='3' (a non-_COERCE base knob), not short_window='50' — SMAMACDStrategy.validate() compares short_window >= long_window, so a str short_window would raise a TypeError inside validate() and mask the actual non-coercion behavior. max_positions has no validate dependency and proves the str is applied verbatim (D-08)."
  - "VALIDATION.md -k selector `short_lt_long` pins the test name: the migrated cross-field rejection test is named test_validate_short_lt_long_rejection so the phase gate selector hits it."
  - "Fixture max_window pinned as a class attr (was set after super().__init__) — under the **kwargs surface there is no post-init mutation window; a class attr is the clean equivalent and is byte-exact (warmup stays 0)."
metrics:
  duration: ~20 min
  completed: 2026-06-12
requirements: [STRAT-01]
---

# Phase 2 Plan 03: Close the kwargs migration + byte-exact phase gate Summary

Migrated every remaining strategy construction site from the deleted `(name, config)` pydantic
signature to the `**kwargs` class-attribute surface (D-05, no shim), rewrote the strategy unit tests
for the new class-attribute engine surface, and ran the byte-exact phase gate GREEN. This is the wave
that turned the suite from the intentional Plan 02-02 RED window back to fully green and proved
byte-exactness: the BTCUSD oracle holds 134 trades / `final_equity 46189.87730727451`, e2e is 58/58,
`mypy --strict` is clean, the full 853-test suite is green, and a determinism double-run is
byte-identical.

## What Was Built

### Task 1 — Rewrite + extend the strategy unit tests (commit `196236c`)
- **`test_strategy_config.py` (REWRITE):** dropped the pydantic `BaseStrategyConfig`/`SMA_MACDConfig`
  tests entirely; wrote the class-attribute-surface tests so the VALIDATION.md `-k` selectors hit:
  `reject_unknown_kwarg` (`UnknownParamError`), `missing_required_param` (`MissingParamError` via
  `EmptyStrategy`), `kwargs_override_class_attr_default` (`short_window=30`), `timeframe_str_coerces`
  (`isinstance(s.timeframe, timedelta)` + stashed `_timeframe`/`timeframe_alias`), `non_enum_knob_not_coerced`
  (`max_positions="3"` stays a str), plus `str_direction_coerces` for the enum-coercion happy path.
- **`test_strategy.py`:** migrated `_sma_config()` → `_sma_kwargs()` and every
  `SMAMACDStrategy(_sma_config())` → `SMAMACDStrategy(**_sma_kwargs())`; migrated `_AlwaysBuyStrategy` to
  `super().__init__(**kwargs)` with `name`/`max_window` as class attrs; kept the `short>=long`
  rejection (`test_validate_short_lt_long_rejection`, now a plain `ValueError`); ADDED `test_init_is_idempotent`
  (D-11) and `test_reconfigure_reapplies_and_revalidates` (D-12 — preserves prior timeframe, re-runs validate()).
- **`test_signal_store.py`:** migrated both local fixtures to `super().__init__(**kwargs)`; changed the
  `record.config is strategy.config` identity + `record.config.model_dump()` assertions to a dict-shape
  `record.config == strategy.to_dict()` (D-04 — `to_dict()` returns a fresh dict per call, so `is` is wrong).

### Task 2 — Migrate e2e fixtures, scripts, integration sites (commit `21559d5`)
- **e2e fixtures** (`scripted_emitter.py`, `single_market_buy.py`): replaced the `BaseStrategyConfig(...)`
  build + `super().__init__("name", config)` with a direct `super().__init__(**kwargs)` passing every param
  through; `name`/`max_window` pinned as class attrs; dropped the `BaseStrategyConfig` import. Every value
  verbatim — `FractionOfCash(Decimal("0.95"))` string-path, `allow_increase=False`, `max_positions=1`,
  `max_window=100`.
- **`scripts/run_backtest.py`** (the byte-exact oracle generator): dropped the `SMA_MACDConfig` import;
  collapsed the `SMA_MACDConfig(...)` + `SMAMACDStrategy(strategy_config)` into a single
  `SMAMACDStrategy(timeframe=..., tickers=..., sizing_policy=FractionOfCash(Decimal("0.95")), ...)`.
- **Four integration sites** (`test_backtest_smoke.py`, `test_universe_spans.py`,
  `test_reservation_inertness.py`, `test_backtest_oracle.py`): mechanical swap to the `**kwargs` surface,
  every value verbatim; the oracle's `record.config` assertion migrated to the dict-snapshot shape
  (`== strategy.to_dict()`).

### Task 3 — Byte-exact phase gate (verification only, no code edits)
Ran the full gate; all green, no source fix needed (no oracle drift, no re-baseline).

## Byte-Exact Phase Gate Results (GREEN)

| Gate | Command | Result |
|------|---------|--------|
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -x` | 3 passed — 134 trades / `final_equity 46189.87730727451` |
| e2e | `pytest tests/e2e/ -x` | **58 passed** (no leaf re-baselined) |
| mypy --strict | `mypy --strict itrader/` | Success — no issues in **172 source files** |
| Full suite | `make test` | **853 passed** (no `filterwarnings=["error"]` failures, all markers declared) |
| Determinism double-run | two consecutive `run_backtest.py` runs | `final_equity` byte-identical: `46189.87730727451` == `46189.87730727451` |
| Trade count | `output/trades.csv` data rows | **134** |

No oracle drift surfaced — the source surface from Plan 02-02 (the `self.timeframe` enum→timedelta
resolution, the Decimal string-path defaults, the `max_window`/`warmup` golden values) was already
byte-correct, so Task 3 was pure verification with zero source edits and **zero re-baseline**.

## Threat Mitigations Delivered

| Threat ID | Disposition | Mitigation |
|-----------|-------------|------------|
| T-02-01 (unknown construction kwarg silently dropped) | mitigate | `test_strategy_config.py::test_reject_unknown_kwarg_raises` asserts `UnknownParamError` (D-06) |
| T-02-02 (under-specified strategy, missing required attr) | mitigate | `test_strategy_config.py::test_missing_required_param_raises` asserts `MissingParamError` via `EmptyStrategy` (D-07) |
| T-02-05 (silent numerical drift from the mechanical migration) | mitigate | The byte-exact oracle gate (134 / 46189.87730727451) + e2e 58/58 + determinism double-run all green — no param-value or timeframe-resolution drift |
| T-02-SC (npm/pip/cargo installs) | accept | Zero external packages installed — pure migration, no install task |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] missing-required test target switched from SMAMACDStrategy to EmptyStrategy**
- **Found during:** Task 1 first test run (`test_missing_required_param_raises` DID NOT RAISE).
- **Issue:** The plan's behavior spec said "missing-required (no sizing_policy/tickers/timeframe) →
  `pytest.raises(MissingParamError)`". But `SMAMACDStrategy` pins `sizing_policy` AND `direction` as
  class attrs (golden defaults), so omitting `sizing_policy` on SMA falls back to the class attr and
  never raises. The required-omittable surface is only observable on a strategy that does NOT pin those.
- **Fix:** Asserted `MissingParamError` via `EmptyStrategy` (which declares no `sizing_policy`/`tickers`),
  so the bare base annotation stays required and the engine raises (D-07).
- **Files modified:** `tests/unit/strategy/test_strategy_config.py`
- **Commit:** `196236c`

**2. [Rule 3 - Blocking] non-coercion test knob switched from short_window to max_positions**
- **Found during:** Task 1 second test run (`test_non_enum_knob_not_coerced_to_int` raised a TypeError).
- **Issue:** The plan's behavior spec used `short_window="50"` to prove non-coercion. The str DID stay a
  str (correct, non-coercion held), but `SMAMACDStrategy.validate()` runs `self.short_window >= self.long_window`
  during construction, and `"50" >= 100` raises `TypeError: '>=' not supported between instances of 'str'
  and 'int'` — the validate() hook crashed before the assertion could observe the un-coerced str.
- **Fix:** Asserted non-coercion via `max_positions="3"` — a non-`_COERCE` base knob with no validate
  dependency — which proves the engine applies the str verbatim, never silently `int()`-ing it (D-08).
- **Files modified:** `tests/unit/strategy/test_strategy_config.py`
- **Commit:** `196236c`

Both are test-construction adjustments (the engine behavior under test is exactly as Plan 02-02 built it);
the plan's chosen probe values happened to collide with SMAMACDStrategy's pinned class attrs / validate()
cross-field rule, so a different (semantically equivalent) probe was used. No source code changed.

### Naming alignment

The VALIDATION.md `-k short_lt_long` selector pins the migrated cross-field rejection test name —
`test_validate_short_lt_long_rejection` — so the phase gate selector hits it.

## Known Stubs

None. Every construction site is fully migrated to the live `**kwargs` surface; no placeholder, mock, or
empty-data path was introduced. The byte-exact gate is the integrity proof.

## Self-Check: PASSED

- FOUND: tests/unit/strategy/test_strategy_config.py (modified)
- FOUND: tests/unit/strategy/test_strategy.py (modified)
- FOUND: tests/unit/strategy/test_signal_store.py (modified)
- FOUND: tests/e2e/strategies/scripted_emitter.py (modified)
- FOUND: tests/e2e/strategies/single_market_buy.py (modified)
- FOUND: scripts/run_backtest.py (modified)
- FOUND: tests/integration/test_backtest_smoke.py (modified)
- FOUND: tests/integration/test_universe_spans.py (modified)
- FOUND: tests/integration/test_reservation_inertness.py (modified)
- FOUND: tests/integration/test_backtest_oracle.py (modified)
- FOUND: commit 196236c
- FOUND: commit 21559d5
