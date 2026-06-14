---
phase: 02-strategy-authoring-surface
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - itrader/core/exceptions/strategy.py
  - itrader/core/exceptions/__init__.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/strategy_handler/signal_record.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/config/__init__.py
  - scripts/run_backtest.py
  - tests/unit/strategy/test_strategy_config.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/strategy/test_signal_store.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_universe_spans.py
  - tests/integration/test_reservation_inertness.py
  - tests/integration/_oracle_harness.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** clean

## Summary

Iteration-2 re-review of the strategy-authoring-surface refactor (the `Strategy(name, config)`
pydantic constructor replaced by a `**kwargs` class-attr introspection engine: `_apply_params`
over `get_type_hints` + enum-coercion table + `setattr`, with `init()`/`validate()`/`reconfigure()`
lifecycle hooks and a `SignalRecord` sink).

**Iteration-1 fixes verified sound and complete.** Every iteration-1 finding was re-traced against
the committed code and exercised directly:

- **WR-01 (mutable-default aliasing + non-idempotent (un)subscribe)** — `base.py:124` now
  `copy.deepcopy`s `list`/`dict`/`set` class-attr defaults on the fallback path; `subscribe_portfolio`
  / `unsubscribe_portfolio` (`:311`/`:318`) are now membership-guarded. Verified: two instances no
  longer share a mutated class-default list, and a UUID/int portfolio handle survives the
  serialization edge.
- **WR-02 (`to_dict()` omitted timeframe/tickers/windows)** — `to_dict()` (`:194-248`) now
  introspects `get_type_hints(type(self))`, serializing the FULL declared surface (timeframe_alias,
  tickers, short/long/fast/slow/signal windows, max_window, warmup) plus bespoke serializations
  (enum `.value`, policy `repr`, stringified UUIDs). Verified JSON-serializable and faithful across
  `SMAMACDStrategy`, `ScriptedEmitter`, `SingleMarketBuy`, and `EmptyStrategy`.
- **WR-04 (reconfigure omit-keeps-prior asymmetry)** — documented explicitly in
  `reconfigure.__doc__` (`:182-188`) and pinned by `test_reconfigure_omitted_field_keeps_prior_not_default`.
- **IN-01 (dead `tuple`-pair branch)** — removed from `get_strategies_universe`
  (`strategies_handler.py:179-189`); the contract is now plainly `tickers: list[str]`.
- **IN-02 (self-consistency-only snapshot test)** — both `test_signal_store.py:180-185` and
  `test_backtest_oracle.py:299-306` now assert the snapshot against specific intended fields
  (strategy_name, direction, sizing_policy, timeframe_alias, tickers, windows), not a re-derived
  `to_dict()`.
- **IN-03 (duplicated importlib harness)** — extracted to `tests/integration/_oracle_harness.py`;
  both `test_backtest_oracle.py` and `test_reservation_inertness.py` import the single
  `load_run_backtest_module` + path constants.

**No new defects were introduced by the fixes.** The two run-path files touched (`base.py`,
`strategies_handler.py`) keep the change set oracle-dark: `to_dict()` feeds only the
`SignalRecord` sink (never fills or fan-out), and the mutable-default/idempotency guards do not
alter any value on the golden path. Verified by execution:

- **Golden oracle holds at `46189.87730727451`.** `test_backtest_oracle.py` (3 tests) passes,
  including the no-tolerance numeric-magnitude assertion against the committed
  `tests/golden/summary.json` (final_equity == final_cash == 46189.87730727451).
- **Full suite green / typed.** 24 strategy unit tests + 7 strategy-touching integration tests
  (oracle, smoke, reservation inertness) pass; `mypy --strict` is clean on `base.py`,
  `strategies_handler.py`, and `core/exceptions/strategy.py`.
- **Indentation convention intact** — `base.py`/`strategies_handler.py` tab; `core/exceptions/strategy.py`,
  `signal_record.py`, `config/__init__.py`, and all tests 4-space. No mixed-indentation defect.
- **Money string-path Decimal** — every `FractionOfCash(Decimal("0.95"))` literal is the string
  path; `buy()`/`sell()` enter via `to_money`. No `Decimal(float)` in the reviewed surface.

No in-scope actionable findings remain.

## Known-Deferred (not an open finding)

**WR-03 — `generate_signal` precondition crash / relocated warmup guard** (`SMA_MACD_strategy.py:52-95`):
the in-strategy `if len(bars) < self.max_window: return None` guard was removed (D-15) and relocated
to the handler's `strategy.warmup` short-circuit (`strategies_handler.py:103`). This is a standing
owner directive **DEFERRED to Phase 3 (IND-01, framework-derived warmup)** and recorded in STATE.md
Decisions; the missing in-strategy guard is intentional for Phase 2. The HARD byte-exact constraint
for the Phase-3 implementer stands: derived warmup for `SMAMACDStrategy` MUST equal exactly **100**
or the oracle drifts off `46189.87730727451`. Out of scope for this phase's review status.

---

_Reviewed: 2026-06-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
