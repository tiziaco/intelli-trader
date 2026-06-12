---
phase: 03-declared-indicator-framework
plan: 02
subsystem: strategy_handler
tags: [indicators, framework, byte-exact, IND-01, D-06, D-08, evaluate-seam]
requires:
  - "03-01: itrader.strategy_handler.indicators barrel (SMA/MACDHist/IndicatorHandle/IndicatorAdapter) + primitives.py (crossover/crossunder/is_above)"
  - "Phase 2 base Strategy kwargs/init()/reconfigure lifecycle seam"
provides:
  - "Strategy.indicator(adapter, input, *params) recipe registration -> IndicatorHandle"
  - "Strategy.evaluate(ticker, window) orchestration seam (stashes self.bars/self.now, repopulates handles, dispatches generate_signal(ticker))"
  - "Auto-derived warmup (unconditional from handle min_period) + max_window (fetch width = max(derived, hand-set))"
  - "generate_signal(self, ticker) 1-arg abstract contract (bars dropped, D-06)"
affects:
  - "Plan 03 proves the byte-exact oracle against backtesting.py/backtrader on this migrated reference"
  - "Plan 4 (COMP-02) StrategiesHandler.update_config re-runs init() -> re-derives warmup via _run_init"
tech-stack:
  added: []
  patterns:
    - "backtesting.py self.I() shape — self.indicator() returns a thin positional handle the author binds to a named attr"
    - "evaluate() orchestration seam (handler dispatches through it, not generate_signal directly)"
    - "Auto-derived gating threshold + fetch-width separation (warmup vs max_window)"
key-files:
  created: []
  modified:
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/empty_strategy.py
    - itrader/strategy_handler/strategies_handler.py
    - tests/e2e/strategies/scripted_emitter.py
    - tests/e2e/strategies/single_market_buy.py
    - tests/integration/test_universe_spans.py
    - tests/unit/strategy/test_strategy.py
    - tests/unit/strategy/test_signal_store.py
decisions:
  - "D-06: generate_signal(self, ticker) — bars dropped; the handler dispatches through evaluate(ticker, window) which stashes self.bars/self.now"
  - "D-08: warmup is UNCONDITIONALLY auto-derived from handle min_period (the WR-03 footgun fix); the reference ends at warmup == max_window == 100"
  - "[DEVIATION from must_have prose] max_window = max(derived, hand-set class value), NOT unconditional overwrite to 0 — the literal 'zero-handle ends at max_window==0' claim BREAKS the byte-exact e2e/integration golden (a 0-width window is always empty against a REAL feed), so the fetch width must not shrink below a hand-set value"
metrics:
  duration: ~40 min
  tasks: 3
  files: 9
  completed: 2026-06-12
---

# Phase 3 Plan 02: Declared-Indicator Framework — base.py framework + full run/test-path migration Summary

Landed the strategy-base framework (`self.indicator()` recipe registration, the `evaluate(ticker, window)` orchestration seam, and the auto-warmup post-`init()` pass) onto `base.py` consuming Plan 01's `IndicatorHandle`/adapters, and migrated the ENTIRE active run/test path onto it in one indivisible lockstep: the reference `SMAMACDStrategy` is now fully primitive-driven (`is_above`/`crossover`/`crossunder` over handles, hand-set `warmup`/`max_window` deleted, auto-derived to 100), `EmptyStrategy`/both e2e fixtures/`BuyEachTickerOnce`/in-test stubs migrated to `generate_signal(self, ticker)`, and the handler call-site swapped to `evaluate()`. Byte-exact gate HOLDS: oracle 134 trades / `46189.87730727451`, e2e 58/58, full suite 890 green, mypy --strict clean (176 files), determinism double-run identical.

## What Was Built

**Task 1 — Framework on base.py (commit `7b8c3ae`, fix amended in `b47b097`):**
- `from .indicators import IndicatorAdapter, IndicatorHandle` (one-directional `base -> indicators`, no cycle; base does NOT define the handle).
- `self.indicator(adapter, input_col, *params) -> IndicatorHandle` — constructs a handle, appends to `self._handles`, returns it (the `backtesting.py` `self.I()` shape; author binds to a named attr).
- `_run_init()` (called from `__init__` and `reconfigure`): resets `self._handles = []` BEFORE `init()` (D-10 idempotency), runs `init()`, then auto-derives the thresholds.
- `evaluate(self, ticker, window)`: stashes `self.bars = window`, `self.now = window.index[-1]` (Pitfall 4 anchor), repopulates every handle (no-op for zero-handle fixtures, Pitfall 6), returns `generate_signal(ticker)`.
- `@abstractmethod generate_signal(self, ticker)` — `bars` dropped (D-06); the annotated `max_window: int = 0` / `warmup: int = 0` base attrs KEPT (`to_dict` introspects `get_type_hints`).

**Task 2 — Reference + EmptyStrategy + unit tests (commit `b47b097`):**
- `SMA_MACD_strategy.py`: `init()` declares `self.short_sma = self.indicator(SMA, "close", self.short_window)`, `self.long_sma` (long_window), `self.macd_hist = self.indicator(MACDHist, "close", fast, slow, signal)`; hand-set `max_window: int = 100`/`warmup: int = 100` DELETED; `generate_signal(ticker)` reads `is_above(self.short_sma, self.long_sma)` then `crossover`/`crossunder(self.macd_hist, 0)`; inline `ta`/`last_time`/`start_dt` removed; `validate()` + oracle-visible defaults KEPT verbatim.
- `empty_strategy.py`: signature-only migration to `generate_signal(self, ticker)`; dropped now-unused `pandas` import.
- `test_strategy.py`: migrated the direct call at line 106 to `strategy.evaluate(...)`; migrated `_AlwaysBuy.generate_signal` to `(self, ticker)`; ADDED `test_auto_derived_warmup_equals_max_window_100` (`-k warmup`).
- `test_signal_store.py`: migrated the two inline stubs (`_AlwaysBuy`/`_NeverSignal`) to `(self, ticker)`.

**Task 3 — Handler call-site swap + e2e/integration fixtures (commit `f00117b`):**
- `strategies_handler.py`: SINGLE call-site swap `intent = strategy.generate_signal(ticker, data)` -> `intent = strategy.evaluate(ticker, data)`; the D-15 warmup short-circuit, `feed.window(..., strategy.max_window, ...)` fetch, `to_dict` snapshot, and per-portfolio fan-out UNCHANGED.
- `scripted_emitter.py` / `single_market_buy.py` (4 SPACES): `generate_signal(self, ticker)` reading `self.bars`/`len(self.bars)`; dropped now-unused `pandas` import.
- `test_universe_spans.py::BuyEachTickerOnce` (4 SPACES, active-path via `system.run()`): signature-only migration; hand-set `max_window: int = 1` left AS-IS (now a fetch-width floor — see deviation).

## Verification

- `poetry run pytest tests/unit/strategy -x` — 60 passed (incl. the new warmup assertion + migrated call sites).
- `poetry run pytest tests/e2e -m e2e -q` — 58/58 green.
- `poetry run pytest tests/integration` — 12 passed (incl. `test_backtest_oracle.py` 134 trades / `46189.87730727451` byte-exact; `test_universe_spans.py` no `TypeError`).
- `poetry run pytest tests/unit tests/integration tests/e2e` — 890 passed.
- `poetry run mypy itrader` — clean, 176 source files (`--strict`).
- Determinism: oracle double-run byte-identical.
- Indentation preserved: base.py/SMA_MACD/empty_strategy/strategies_handler TABS; scripted_emitter/single_market_buy/test_universe_spans/test_strategy/test_signal_store 4 SPACES (each matched its actual file).
- `grep "def generate_signal(self" itrader/ tests/ | grep -v my_strategies/ | grep bars` — CLEAN (no active-path 2-arg def remains).
- `SMAMACDStrategy(**_sma_kwargs()).warmup == .max_window == 100` — confirmed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] max_window auto-derivation must not shrink below a hand-set value (fetch width)**
- **Found during:** Task 3 (e2e + integration verify — all 58 e2e tests and `test_universe_spans` failed with `IndexError: index -1 is out of bounds for axis 0 with size 0`).
- **Issue:** The plan's must_have prose (D-08 truth) specified the auto-warmup post-pass `UNCONDITIONALLY overwrites ... max_window` to `max(min_period, default=0)`, claiming zero-handle fixtures "stay green ... benign: stub feeds ignore max_window." That claim holds ONLY for the unit-test STUB feed (`_StubFeed.window` ignores `max_window`). Against the REAL `BacktestBarFeed`, `feed.window(..., max_window=0, ...)` returns `frame.iloc[pos:pos]` — an EMPTY window. The count/date-keyed e2e fixtures (`SingleMarketBuy` `len(bars)==fire_on_bar`, `ScriptedEmitter` date key, `BuyEachTickerOnce` first-bar) then (a) crashed in `evaluate` on `window.index[-1]` of a size-0 frame, and (b) even if guarded, would NEVER fire (0 bars delivered), breaking the e2e/integration golden.
- **Fix:** Separated the two thresholds in `_run_init`: `warmup` is UNCONDITIONALLY auto-derived from handle `min_period` (this IS the WR-03 footgun fix — the real D-08 goal); `max_window` is the FETCH WIDTH `= max(handle-derived, type(self).max_window)` so a hand-set wide window is preserved for zero-handle fixtures. For the reference the hand-set value is deleted (class default 0), so `max_window == 100` (handle-derived) and the `warmup == max_window == 100` assertion still holds. Also added a defensive empty-window guard in `evaluate` (`self.now = window.index[-1] if len(window) else None`; skip repopulate when empty) so a zero-warmup strategy dispatched with an empty window does not raise.
- **Why this outranks the prose:** the byte-exact e2e/integration golden (58/58, 134 trades / `46189.87730727451`) is a HARD milestone constraint; the must_have prose claim of "benign overwrite to 0" was factually incorrect against the real feed. The deviation preserves the D-08 INTENT (auto-derive thresholds, remove the warmup footgun) while keeping every gate green.
- **Files modified:** itrader/strategy_handler/base.py
- **Commit:** b47b097

**2. [Rule 1 - Doc] test_strategy.py is 4 SPACES, not TABS**
- **Found during:** Task 2.
- **Issue:** The plan's `<action>` for Task 2 labelled `tests/unit/strategy/test_strategy.py` as "(TABS)". The actual file is 4-SPACE indented (consistent with the tests house style and `test_signal_store.py`).
- **Fix:** Matched the file's actual 4-SPACE indentation (CLAUDE.md: always match the file, never normalize). No content impact.
- **Files modified:** tests/unit/strategy/test_strategy.py
- **Commit:** b47b097

## Known Stubs

None. The migrated reference reads real handle values through real adapters; no placeholder values, empty returns, or unwired data sources.

## Threat Flags

None. Per the plan's threat register (T-03-02 / T-03-SC, disposition `accept`), this is a pure in-process numerical/dispatch refactor with no new trust boundary; zero packages installed. The look-ahead-safety property is preserved by the unchanged bar-feed contract.

## Self-Check: PASSED

Files modified (all confirmed present + committed):
- itrader/strategy_handler/base.py — FOUND
- itrader/strategy_handler/strategies/SMA_MACD_strategy.py — FOUND
- itrader/strategy_handler/strategies/empty_strategy.py — FOUND
- itrader/strategy_handler/strategies_handler.py — FOUND
- tests/e2e/strategies/scripted_emitter.py — FOUND
- tests/e2e/strategies/single_market_buy.py — FOUND
- tests/integration/test_universe_spans.py — FOUND
- tests/unit/strategy/test_strategy.py — FOUND
- tests/unit/strategy/test_signal_store.py — FOUND

Commits (confirmed in git log):
- 7b8c3ae (Task 1 — base.py framework) — FOUND
- b47b097 (Task 2 — reference + framework fix) — FOUND
- f00117b (Task 3 — handler swap + fixtures) — FOUND
