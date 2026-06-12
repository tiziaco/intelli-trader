---
phase: 02-strategy-authoring-surface
plan: 02
subsystem: strategy_handler
tags: [strategy, authoring-surface, kwargs-engine, introspection, config-deletion, STRAT-01]
requires:
  - "UnknownParamError / MissingParamError (Plan 02-01)"
provides:
  - "Strategy ABC class-attribute authoring surface + **kwargs introspection engine (_apply_params)"
  - "init() / validate() / reconfigure() lifecycle hooks (D-09/D-10/D-12)"
  - "SMAMACDStrategy + EmptyStrategy migrated to class-attr declarations (golden defaults verbatim)"
  - "SignalRecord.config retyped to dict[str, Any] snapshot (D-04)"
affects:
  - "Plan 02-03 (migrates test/script construction sites in lockstep; runs the byte-exact gate)"
  - "Phase 3 IND-01 (auto-warmup re-derived on init() re-run)"
  - "Phase 4 COMP-02 (StrategiesHandler.update_config consumes reconfigure()/init())"
tech-stack:
  added: []
  patterns:
    - "stdlib get_type_hints(type(self)) MRO-merged introspection driving required/unknown detection"
    - "3-entry _COERCE enum table (timeframe/order_type/direction) — only these str->enum coerce"
    - "_MISSING sentinel separating a bare (required) annotation from a None-valued default"
    - "Pitfall 1: self.timeframe resolves to timedelta; coerced enum stashed on _timeframe/timeframe_alias"
key-files:
  created: []
  modified:
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/empty_strategy.py
    - itrader/strategy_handler/signal_record.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/config/__init__.py
  deleted:
    - itrader/config/strategy.py
decisions:
  - "ALL engine-facing knobs are ANNOTATED on the base (order_type/direction/allow_increase/max_positions gained type annotations) — get_type_hints returns only annotated names, so unannotated knobs would be invisible to the engine (un-overridable by kwarg, enum coercion never firing). This was a Rule 1/3 deviation from the RESEARCH skeleton which left those four bare-assigned."
  - "reconfigure required-field fallback: an omitted required field falls back to the prior INSTANCE value (RESEARCH OQ1) instead of raising MissingParamError; timeframe falls back to the stashed _timeframe enum (self.timeframe is a timedelta after the first pass)."
  - "Class-attr timeframe annotated as timedelta (the resolved consumer type) — the bare-annotation-no-value still marks it required; the kwarg arrives as a str/Timeframe and is coerced via _COERCE before resolution."
metrics:
  duration: ~25 min
  completed: 2026-06-12
requirements: [STRAT-01]
---

# Phase 2 Plan 02: Strategy Authoring Surface — Engine + Hooks + Config Deletion Summary

Landed the class-attribute strategy authoring surface across the source layer in one indivisible unit (D-02/D-05, no compatibility shim). Replaced the base `Strategy` `(name, config)` constructor with a pure-stdlib `**kwargs` introspection engine (`get_type_hints` + a 3-entry `_COERCE` enum table + `setattr`), added `init()` / `validate()` / `reconfigure()` lifecycle hooks, migrated `SMAMACDStrategy` and `EmptyStrategy` to class-attr declarations with golden defaults verbatim, retyped `SignalRecord.config` to a dict snapshot, swapped the handler's capture site to `strategy.to_dict()`, and fully deleted the pydantic config layer.

## Expected RED Window (intentional, bounded — D-05)

This plan deliberately leaves the test/integration/e2e/oracle suite RED. The source signature changed from `(name, config)` to `**kwargs` with NO compatibility shim, so all 10 test/script construction sites still call the old signature and fail until **Plan 02-03** migrates them in lockstep and runs the byte-exact gate. This is the EXPECTED, bounded "all-or-broken" window (D-05) — NOT a failure. The construction sites still referencing the deleted config symbols are:

```
tests/unit/strategy/test_strategy_config.py
tests/unit/strategy/test_signal_store.py
tests/unit/strategy/test_strategy.py
tests/integration/test_universe_spans.py
tests/integration/test_backtest_smoke.py
tests/integration/test_reservation_inertness.py
tests/integration/test_backtest_oracle.py
tests/e2e/strategies/scripted_emitter.py
tests/e2e/strategies/single_market_buy.py
scripts/run_backtest.py
```

The full suite was NOT run as a pass/fail gate — per the plan, a RED full suite here is correct. The actual done-criteria (below) are all GREEN.

## What Was Built

### Task 1 — Introspection engine + hooks in `base.py` (commits `0ba079a`, `e1c8546`)
- Replaced `__init__(self, name, config)` with `__init__(self, **kwargs)`: mints the per-construction UUIDv7 `strategy_id`, sets `is_active`/`subscribed_portfolios`, then calls `_apply_params(**kwargs)` → `validate()` → `init()`.
- `_apply_params`: `get_type_hints(type(self))` (MRO-merged) drives required/unknown detection; the 3-entry `_COERCE = {timeframe: Timeframe, order_type: OrderType, direction: TradingDirection}` table coerces str→enum off the annotation; leftover kwargs raise `UnknownParamError(sorted(kwargs))`; a bare-annotation-no-default-no-prior-value raises `MissingParamError(nm)`.
- **Pitfall 1 (the #1 oracle trap):** `self.timeframe` resolves to a `timedelta` (`to_timedelta(self._timeframe.value)`) consumed by `check_timeframe`/`min_timeframe`/SMA; the coerced enum is stashed on `self._timeframe` and the alias on `self.timeframe_alias` (read by `__str__`). Re-derived on EVERY `_apply_params` pass.
- Added `validate()` (D-09 no-op hook), `init()` (D-10 idempotent no-op hook), `reconfigure(**kwargs)` (D-12: re-apply → re-validate → re-init). No `__setattr__` guard (D-13).
- `to_dict()` reads real instance attrs (the 10-key shape is byte-identical); `__str__` reads `self.timeframe_alias` (Pitfall 5). `buy/sell/subscribe/activate/generate_signal` UNCHANGED.

### Task 2 — Migrate strategies + delete config layer (commit `f4ba20c`)
- `SMAMACDStrategy`: golden defaults declared VERBATIM as class attrs (`name="SMA_MACD"`, `sizing_policy=FractionOfCash(Decimal("0.95"))` string-path, `direction=LONG_ONLY`, `short_window=50`, `long_window=100`, `fast_window=6`, `slow_window=12`, `signal_window=3`, `max_window=100`, `warmup=100`). `validate()` carries `short<long` (was the `@model_validator`, D-09); no-op `init()`. `generate_signal` byte-identical.
- `EmptyStrategy`: `max_window: int = 1` class attr; `EmptyStrategyConfig` deleted; `generate_signal` returns `None`.
- Deleted `itrader/config/strategy.py` (`BaseStrategyConfig`) entirely (D-01); dropped its import + `__all__` entry from `config/__init__.py`. No dead dual-path.

### Task 3 — Retype `SignalRecord.config` + swap handler capture (commit `52df9f4`)
- `SignalRecord.config`: `BaseStrategyConfig` → `dict[str, Any]` (D-04). Dropped the `BaseStrategyConfig` import; added `typing.Any`. Updated the D-11→D-04 docstrings.
- `strategies_handler.py`: `config=strategy.config` → `config=strategy.to_dict()`. The warmup short-circuit and per-portfolio `SignalEvent` fan-out are unchanged.

## Threat Mitigations Delivered

| Threat ID | Disposition | Mitigation |
|-----------|-------------|------------|
| T-02-01 (unknown kwarg silently dropped) | mitigate | `_apply_params` raises `UnknownParamError(sorted(kwargs))` on any leftover kwarg (D-06) |
| T-02-02 (under-specified strategy) | mitigate | `_apply_params` raises `MissingParamError(nm)` on a required field with no value/no prior (D-07) |
| T-02-03 (partial direct-poke reconfigure) | accept | No `__setattr__` guard (D-13); sanctioned `reconfigure(**kwargs)` re-validates + re-runs init() |
| T-02-04 (invalid enum string) | mitigate | `_COERCE` runs the enum's `_missing_` (`Timeframe("bogus")` raises `ValueError`) — bounds the 3 enum fields (D-08) |

## Verification

- `poetry run mypy --strict itrader/` — clean, **172 source files**.
- `test ! -f itrader/config/strategy.py` — config layer deleted; no `BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig` references remain anywhere in `itrader/`.
- `python -c "import itrader.strategy_handler.base; import itrader.config; import itrader.strategy_handler.strategies.SMA_MACD_strategy; import itrader.strategy_handler.strategies.empty_strategy"` — imports clean.
- Per-task grep acceptance criteria all pass (`self.config`→0, `to_timedelta` present, hooks present, `config=strategy.to_dict()`→1, etc.).
- **Runtime engine smoke-test (all GREEN):** kwarg override; `UnknownParamError`/`MissingParamError`; str→enum coercion (`order_type="market"`, `direction="long_only"`); non-enum NOT coerced (`max_positions="3"` stays str); `validate()` short≥long raises; `init()` idempotent (`to_dict()` identical); `to_dict()` 10-key set + byte-identical serialization; `reconfigure(short_window=40)` preserves prior timeframe AND prior required fields (tickers/sizing_policy); `reconfigure(timeframe="4h")` updates the alias.
- **NOTE:** the unit/integration/e2e/oracle suite is intentionally RED (construction sites still call the old signature) — Plan 02-03 closes it and runs the byte-exact gate (134 trades / `46189.87730727451`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug / Rule 3 - Blocking] Annotated all four engine knobs on the base**
- **Found during:** Task 1 runtime smoke-test.
- **Issue:** The RESEARCH skeleton (and the plan's action list) declared `order_type = OrderType.MARKET`, `direction = TradingDirection.LONG_ONLY`, `allow_increase = False`, `max_positions = 1` WITHOUT type annotations. But `_apply_params` iterates `get_type_hints(type(self))`, which returns ONLY annotated names — so these four were invisible to the engine: un-overridable by kwarg, and the stated `order_type="market"` / `direction="long_only"` enum coercion (an explicit Task-1 behavior) would never fire. A `max_positions=3` kwarg raised `UnknownParamError`.
- **Fix:** Added type annotations (`order_type: OrderType`, `direction: TradingDirection`, `allow_increase: bool`, `max_positions: int`) so all engine-facing knobs are introspectable.
- **Files modified:** `itrader/strategy_handler/base.py`
- **Commit:** `e1c8546`

**2. [Rule 1 - Bug] reconfigure required-field fallback**
- **Found during:** Task 1 runtime smoke-test.
- **Issue:** `reconfigure(short_window=40)` (no `timeframe`/`tickers`/`sizing_policy` kwargs) raised `MissingParamError` for the required `timeframe` field — required-detection read the bare CLASS annotation and never considered the prior INSTANCE value. RESEARCH Open Question 1 specifies the reconfigure fallback is the prior instance value.
- **Fix:** In `_apply_params`, an omitted required field now falls back to the prior instance value when `_apply_params` has already run (detected via `hasattr(self, "_timeframe")`); `timeframe` specifically falls back to the stashed `_timeframe` enum (since `self.timeframe` is a `timedelta` after the first pass). First-construction behavior (raise on a genuinely missing required) is unchanged.
- **Files modified:** `itrader/strategy_handler/base.py`
- **Commit:** `e1c8546`

Both fixes are within Task 1's scope (the base engine) and were committed together as a follow-up `fix(02-02)` commit after the initial `feat` commit, because the gap only surfaced under runtime exercise (the per-task gate is mypy + grep; the behavior tests land in Plan 02-03).

## Known Stubs

None. `init()` is an intentional no-op hook in Phase 2 (D-10 — indicators stay inline); it is a documented lifecycle seam Phase 3 (IND-01) and Phase 4 (COMP-02) build on, not an unwired stub.

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/base.py (modified)
- FOUND: itrader/strategy_handler/strategies/SMA_MACD_strategy.py (modified)
- FOUND: itrader/strategy_handler/strategies/empty_strategy.py (modified)
- FOUND: itrader/strategy_handler/signal_record.py (modified)
- FOUND: itrader/strategy_handler/strategies_handler.py (modified)
- FOUND: itrader/config/__init__.py (modified)
- CONFIRMED DELETED: itrader/config/strategy.py
- FOUND: commit 0ba079a
- FOUND: commit f4ba20c
- FOUND: commit 52df9f4
- FOUND: commit e1c8546
