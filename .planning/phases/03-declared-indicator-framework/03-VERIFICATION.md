---
phase: 03-declared-indicator-framework
verified: 2026-06-12T00:00:00Z
status: passed
score: 14/14 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 3: Declared-Indicator Framework Verification Report

**Phase Goal:** A strategy declares indicators (func + input + params) in init() and reads pre-evaluated handles (self.short_sma[-1]), with the base auto-deriving warmup/max_window so authors stop hand-setting them — stateless recompute, byte-exact by construction.
**Verified:** 2026-06-12
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Indicators registered declaration-only in init() (recipes, no compute); author reads ready handles in generate_signal | VERIFIED | `SMAMACDStrategy.init()` calls `self.indicator(SMA,"close",...)` x3; handles bound to `self.short_sma`, `self.long_sma`, `self.macd_hist`; no ta compute in generate_signal |
| 2 | After init(), base auto-derives self.max_window / self.warmup = max(min-periods); hand-set lines gone from reference | VERIFIED | `_run_init()` computes `derived = max((h.min_period() for h in self._handles), default=0)`; SMAMACDStrategy has no `max_window:int=100`/`warmup:int=100` class attrs; runtime confirms both == 100 |
| 3 | Free functions crossover/crossunder/is_above/is_below available and look-ahead-safe | VERIFIED | `primitives.py` exports all four; reads completed-bar window positions [-1]/[-2] only; oracle green confirms look-ahead safety |
| 4 | Reference SMAMACDStrategy byte-exact against BTCUSD oracle: 134 trades / final_equity 46189.87730727451 EXACT | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed; frozen golden in `tests/golden/summary.json` matches exactly |
| 5 | e2e 58/58 green | VERIFIED | `poetry run pytest tests/e2e -m e2e -q` → 58 passed |
| 6 | mypy --strict clean over itrader/ | VERIFIED | `poetry run mypy itrader` → "Success: no issues found in 176 source files" |
| 7 | D-05 (amended): indicators/ PACKAGE (catalog.py + handle.py + barrel) exists, primitives.py flat sibling | VERIFIED | `itrader/strategy_handler/indicators/__init__.py`, `catalog.py`, `handle.py` all present; `primitives.py` is flat sibling |
| 8 | D-04: SMA/MACDHist/EMA/RSI real importable typed singleton instances exposing compute + min_period | VERIFIED | Singleton instances typed against `IndicatorAdapter` Protocol; min_period live: SMA(50)=50, SMA(100)=100, MACDHist(6,12,3)=15; mypy --strict clean |
| 9 | D-03: IndicatorHandle in indicators/handle.py; __len__==0 pre-repopulate; [-1]/[-2] -> float; min_period delegates; no import of base.py | VERIFIED | `len(h)==0` before repopulate confirmed; `h[-1]` returns `float` after repopulate; handle.py imports only `datetime`, `pandas`, `.catalog.IndicatorAdapter` — no base import (AST verified) |
| 10 | D-08 auto-warmup deviation adjudicated: warmup unconditionally overwritten (D-08 spirit honored); max_window = max(derived, hand-set) preserving fetch width for zero-handle fixtures | VERIFIED | `warmup = derived` (unconditional overwrite); `max_window = max(derived, type(self).max_window)` — reference: warmup==max_window==100 confirmed; zero-handle with hand-set max_window=5 keeps max_window=5, warmup=0; all e2e/integration green proves deviation is correct |
| 11 | D-06: handler dispatches through strategy.evaluate(), not generate_signal(ticker, data) directly | VERIFIED | `strategies_handler.py:108` — `intent = strategy.evaluate(ticker, data)`; no 2-arg generate_signal remains in active path |
| 12 | D-01/D-02: crossover/crossunder inclusive-on-current-bar (>=/<= current, </>  previous), scalar broadcast | VERIFIED | `crossover(H([-1.0,1.0]), 0)` returns True; `crossunder(H([1.0,-1.0]), 0)` returns True; primitives.py source confirmed |
| 13 | No active-path 2-arg generate_signal(self, ticker, bars) remains outside my_strategies/ | VERIFIED | `grep -rn "def generate_signal(self" itrader/ tests/ | grep -v my_strategies/ | grep bars` — empty output |
| 14 | Full suite 890 passed under filterwarnings=[error], --strict-markers, --strict-config | VERIFIED | `make test` → 890 passed in 11.81s |

**Score:** 14/14 truths verified

### D-08 Deviation Adjudication

The plan's must_have prose stated the auto-warmup pass "UNCONDITIONALLY overwrites max_window to 0" for zero-handle strategies, claiming this was "benign." The executor found this claim was factually incorrect against a real BacktestBarFeed: `feed.window(..., max_window=0, ...)` returns `frame.iloc[pos:pos]` — an empty window — which crashes `evaluate()` on `window.index[-1]` and breaks e2e/integration fixtures.

**Implemented behavior:**
- `warmup` is unconditionally overwritten to `max(min_period, default=0)` — this IS the D-08 WR-03 footgun fix, the stated goal
- `max_window = max(handle-derived, type(self).max_window)` — fetch width preserved for zero-handle count/date-keyed fixtures

**Verdict: HONORS THE SPIRIT of D-08.** The D-08 goal was "authors stop hand-setting warmup" and the "WR-03 footgun fix." That is fully achieved: `warmup` is unconditionally auto-derived, removing the footgun. The reference ends at `warmup == max_window == 100` as required. The max_window deviation is a necessary correctness fix (byte-exact e2e/integration golden proves it), not a scope reduction. The must_have prose's "overwrite to 0" claim was the INCORRECT part of the prose, not the INTENT. This is categorically correct behavior.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/strategy_handler/indicators/__init__.py` | Barrel re-exporting SMA/MACDHist/EMA/RSI + IndicatorHandle | VERIFIED | Exports all 5 symbols + IndicatorAdapter Protocol via `__all__` |
| `itrader/strategy_handler/indicators/catalog.py` | Typed adapter catalog with compute + min_period | VERIFIED | 4 singleton adapters with byte-exact ta calls; D-08 min_period formulas |
| `itrader/strategy_handler/indicators/handle.py` | IndicatorHandle thin positional-index wrapper (D-03) | VERIFIED | Substantive: 65 lines; wired to catalog via IndicatorAdapter; base imports it |
| `itrader/strategy_handler/primitives.py` | crossover/crossunder/is_above/is_below free functions | VERIFIED | Flat sibling; D-02 semantics; scalar broadcast via `_at()` |
| `itrader/strategy_handler/base.py` | self.indicator() + evaluate() + auto-warmup + 1-arg abstract | VERIFIED | All four seams present and wired; dispatches through evaluate() |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | Migrated reference: recipes in init(), primitive-driven generate_signal, no hand-set warmup/max_window | VERIFIED | init() has 3 self.indicator() calls; generate_signal reads is_above/crossover/crossunder; no max_window/warmup class attrs |
| `tests/unit/strategy/test_indicators.py` | min_period assertions + IndicatorHandle lifecycle coverage | VERIFIED | 13 tests: min_period(50)=50, (100)=100, MACDHist=15, max=100; handle __len__/[-1]/[-2]/min_period |
| `tests/unit/strategy/test_primitives.py` | D-02 boundary semantics + scalar broadcast tests | VERIFIED | 22 tests; boundary cases; scalar broadcast; macd-vs-0 trigger |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `strategies_handler.py` | `strategy.evaluate` | call-site swap line 108 | WIRED | `intent = strategy.evaluate(ticker, data)` confirmed at line 108 |
| `base.py` | `indicators/catalog.py` | `from .indicators import IndicatorAdapter, IndicatorHandle` | WIRED | Line 22 of base.py; `_run_init` appends handles; `evaluate` repopulates |
| `SMA_MACD_strategy.py` | `primitives.py` | is_above/crossover/crossunder imports | WIRED | `from itrader.strategy_handler.primitives import crossover, crossunder, is_above` at line 7 |
| `indicators/catalog.py` | `ta.trend / ta.momentum` | verbatim ta calls | WIRED | `trend.SMAIndicator(bars[start_dt:][input_col], window, True)`, `trend.MACD(bars[input_col], ...)`, etc. confirmed |
| `indicators/handle.py` | `indicators/catalog.py` | `_adapter.compute` + `_adapter.min_period` | WIRED | `repopulate` calls `self._adapter.compute(...)`, `min_period` calls `self._adapter.min_period(self._params)` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `SMA_MACD_strategy.py` | `self.short_sma`, `self.long_sma`, `self.macd_hist` | `IndicatorHandle.repopulate` → `_SMA.compute` / `_MACDHist.compute` → ta library on real OHLCV bar window | Yes — ta computes over committed CSV data; oracle confirms 134 real trades | FLOWING |
| `evaluate()` in `base.py` | `window` (pushed from feed) | `StrategiesHandler.calculate_signals` → `feed.window(ticker, timeframe, max_window, asof)` → `BacktestBarFeed` → committed CSV | Yes — real bar feed confirmed by oracle | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SMAMACDStrategy warmup==max_window==100 | Python: `SMAMACDStrategy(**kwargs).warmup == .max_window == 100` | True | PASS |
| SMA min_period(50)=50, MACDHist min_period(6,12,3)=15 | Python: direct call | SMA=50, MACDHist=15 confirmed | PASS |
| crossover(H([-1,1]),0) returns True | Python: direct call | True | PASS |
| IndicatorHandle: len==0 pre, float post, min_period delegates | Python: repopulate on synthetic frame | All confirmed | PASS |
| Oracle 134 trades / 46189.87730727451 EXACT | `pytest tests/integration/test_backtest_oracle.py -x` | 3 passed | PASS |
| e2e 58/58 | `pytest tests/e2e -m e2e -q` | 58 passed | PASS |
| mypy --strict | `poetry run mypy itrader` | Success: 176 files | PASS |
| Full suite 890 | `make test` | 890 passed | PASS |
| Determinism double-run | Oracle run twice | Both 3 passed, byte-identical | PASS |

### Probe Execution

Step 7c: SKIPPED — no probe scripts declared in PLAN or found at `scripts/*/tests/probe-*.sh` for this phase. The oracle test suite serves as the functional equivalent.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| IND-01 | 03-01, 03-02, 03-03 | Declared-indicator framework on the strategy base — indicators registered in init(), auto-derived warmup/max_window, free-function crossover/crossunder, byte-exact | SATISFIED | Indicators package ships 4 typed adapters; IndicatorHandle; auto-warmup in _run_init; primitives.py; oracle 134/46189.87... EXACT; e2e 58/58; mypy clean; full suite 890 green |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `indicators/handle.py` | 55 | `assert self._values is not None` — assert-based guard silently disabled under `-O` | WARNING (WR-01 in REVIEW, non-blocking) | Under `PYTHONOPTIMIZE` the guard is stripped; next line raises `AttributeError` instead of a clear contract error; documented in 03-REVIEW.md; does not affect golden path |
| `primitives.py` | 38 | `isinstance(series_or_scalar, (int, float))` — misses numpy scalars | WARNING (WR-02 in REVIEW, non-blocking) | `numpy.float64` / `numpy.int64` fall through to indexing path; reference passes literal `0` so oracle is unaffected; latent trap for future authors; documented in 03-REVIEW.md |

No TBD/FIXME/XXX debt markers found in any phase-modified file.

**Stub classification:** The `assert` guard is a runtime ordering guard (not a stub — the handle computes real indicator data and is wired end-to-end). The numpy scalar miss in `_at` is a type-coverage gap, not a data stub. Neither prevents the phase goal.

### Human Verification Required

None — all success criteria are machine-verifiable and confirmed by running the test suite and runtime checks.

### Gaps Summary

No gaps. All 14 must-have truths verified. The D-08 deviation (max_window preservation vs literal "overwrite to 0" prose) honors the SPIRIT of D-08 — warmup is unconditionally auto-derived (the footgun fix), the reference ends at warmup==max_window==100, and the deviation keeps the byte-exact e2e/integration golden green. This is the correct behavior; the plan's must_have prose contained a factually incorrect claim about the feed behavior. Two advisory warnings (assert guard WR-01, numpy scalar WR-02) were surfaced in 03-REVIEW.md and are non-blocking robustness gaps on the non-golden path.

---

_Verified: 2026-06-12_
_Verifier: Claude (gsd-verifier)_
