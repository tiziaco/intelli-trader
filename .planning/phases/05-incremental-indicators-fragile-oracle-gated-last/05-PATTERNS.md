# Phase 5: Stateful Indicators + Shared Bar Cache - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 14 (3 new, 11 modified/extended)
**Analogs found:** 14 / 14 (every new/modified surface has an in-repo analog — this is a brownfield conversion-in-place phase)

> **Tag scheme reminder:** the decisions are `P5-DNN` (phase-scoped). The `D-NN`
> tags quoted in code excerpts below are the EXISTING load-bearing code tags
> (code `D-01`=primitives, `D-04`=typed adapters, `D-08`=min_period). The planner
> cites `P5-DNN` in must_haves/truths/objective; the `D-NN` tags are anchors to
> preserve in the code being converted.

> **Read-side stays, value production changes.** This phase converts indicator
> VALUE PRODUCTION (`ta`-recompute → stateful O(1) recurrence) and the
> handler→strategy push contract IN PLACE. The read surfaces (`primitives.py`,
> `handle[-1]`/`[-2]`, the author `self.indicator(...)` declaration) are
> byte-exact references, NOT rewrite targets. The closest analog for almost every
> new file IS the file it replaces.

---

## File Classification

| New/Modified File | Plan | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|------|-----------|----------------|---------------|--------|
| `itrader/strategy_handler/indicators/catalog.py` | B | indicator-adapter | transform (push) | itself (`ta`-backed `_SMA`/`_MACDHist`/`_EMA`/`_RSI`) + RESEARCH §Code-Examples recurrences | convert-in-place | TABS |
| `itrader/strategy_handler/indicators/handle.py` | B | handle | transform (output buffer) | itself (`IndicatorHandle.repopulate`→`__getitem__`) | convert-in-place | TABS |
| `itrader/strategy_handler/indicators/__init__.py` | B | barrel/config | — | itself (re-export barrel) | exact | TABS |
| `itrader/strategy_handler/base.py` | B+C | strategy-base | request-response (evaluate seam) | itself (`evaluate` :328-376, `indicator()` :275-291, `_run_init` :293-326) | convert-in-place | TABS |
| `itrader/strategy_handler/strategies_handler.py` | C | handler-loop | event-driven (BAR→signal) | itself (`calculate_signals` :94-147 single-leg, `_dispatch_pair` :258-311) | convert-in-place | TABS |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | B/C | strategy | request-response | itself (author surface preserved P5-D21) | exact (reference-only edit) | TABS |
| `itrader/strategy_handler/pair_base.py` | C | strategy-base (pair) | request-response (two-leg) | itself (`PairStrategy`, `evaluate_pair` seam, `max_window` validate) | convert-in-place | TABS |
| `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py` | C | pair-strategy | transform (β/z) | itself (`_fit_beta` :121, `_zscore` :170, `evaluate_pair` :205) | convert-in-place | TABS |
| `itrader/price_handler/feed/bar_feed.py` | A | feed | streaming (per-tick) | itself (`generate_bar_event` :378, `current_bars` :415, `_prebuilt` :235, `window` cursor :506) | extend-in-place | SPACES |
| `itrader/price_handler/feed/base.py` | A | feed (ABC) | streaming | itself (`BarFeed` ABC) | extend-in-place | SPACES |
| (new) shared-cache registration fn (likely under `itrader/price_handler/feed/` or `itrader/universe/`) | A | config/derive-fn | derive-once | `universe/instruments.py::derive_instruments` :170 + `membership.py::derive_membership` :44 | role+flow match | SPACES |
| `tests/unit/strategy/test_indicator_convergence.py` (NEW) | B | test (convergence) | batch-vs-stream | `tests/unit/strategy/test_indicators.py` (ta value-equality :71-122) | role match | TABS |
| `tests/unit/strategy/test_indicator_reset.py` (NEW) | B | test (determinism) | batch | `tests/unit/strategy/test_indicators.py` (handle re-runnable :151-159) | role match | TABS |
| `tests/unit/strategy/test_causal_guard.py` (NEW) | B | test (guard) | — | `test_indicators.py` (`pytest.raises` :162-171) + `test_primitives.py` | role match | TABS |
| `tests/integration/test_backtest_oracle.py` + `tests/golden/{trades,equity,summary}` | B | oracle/re-baseline | gate | itself (REUSE, re-freeze) | exact (reuse) | SPACES |

---

## Pattern Assignments

### `itrader/strategy_handler/indicators/catalog.py` (indicator-adapter, transform) — Plan B

**Analog:** itself (the `ta`-backed adapters) + the verified recurrences in RESEARCH §Code-Examples.

**What changes:** the four `compute(bars, input_col, params, now, timeframe) -> pd.Series`
batch methods become STATEFUL adapters holding O(1) derived state with a pure
push `update(value)`, `value`, `is_ready`, `reset()`, and a `causal` flag (Model B,
P5-D07). The `IndicatorAdapter` Protocol (:45-58) is the surface to re-shape;
`min_period` (:82-84 etc.) is UNCHANGED (P5-D06). `ta`/pandas are removed from the
runtime path, retained only in the convergence test.

**Imports pattern to PRESERVE the float64/money fence** (catalog.py :25-28, docstring):
```
Indicator values are pandas ``float64`` (the ``ta`` compute domain), NOT money —
they are look-ahead-safe series the primitives compare, never routed through
``to_money``.
```
RESEARCH Pitfall 5: keep recurrences in float64; `collections.deque` (stdlib) is the SMA ring.

**`min_period` to keep byte-identical** (catalog.py :113-116):
```python
def min_period(self, params: tuple[int, ...]) -> int:
    # D-08: first-valid is slow + signal (==15 for 6/12/3); NO buffer.
    _fast, slow, signal = params
    return slow + signal
```

**Core recurrences (the load-bearing new content — verified vs `ta`, RESEARCH §Code-Examples):**
- SMA running-sum with `deque(maxlen)` eviction — `sum += new − evicted`, NEVER re-sum (P5-D05; RESEARCH Pitfall: SMA private re-sum).
- EMA seed-from-first-value, FACTORED form `y += α(x−y)` (2× closer to `ta` than expanded; P5-D04).
- MACDHist = factored-EMA(fast) − factored-EMA(slow), then factored-EMA(signal) of that line (P5-D11).
- RSI = factored-RMA `α=1/n` over `close.diff(1)` gain/loss seeded from bar 1 (P5-D11; RESEARCH Pitfall 1 — gain/loss alignment, Pitfall 2 — NOT textbook Wilder seed).

**Readiness pattern (P5-D06):** `is_ready` = `count >= min_period` (catalog `min_period` family unchanged; the count lives on the adapter now). Update during warmup, gate emission only (RESEARCH Pattern 2).

---

### `itrader/strategy_handler/indicators/handle.py` (handle, transform) — Plan B

**Analog:** itself.

**What changes:** `repopulate(bars, now, timeframe)` (which delegates to
`adapter.compute`) becomes a `update(...)`-driven output-history buffer (default
depth 2, P5-D08). The `[-1]`/`[-2]` positional read (:53-62) and the
read-before-ready `RuntimeError` guard are RETAINED.

**Read-edge + guard pattern to PRESERVE** (handle.py :53-62):
```python
def __getitem__(self, idx: int) -> float:
    # WR-01: a real runtime ordering contract must raise unconditionally — an
    # `assert` is stripped under `-O`/PYTHONOPTIMIZE …
    if self._values is None:
        raise RuntimeError("repopulate() must run before reading the handle")
    return float(self._values.iloc[idx])
```
New shape: the buffer holds the last `k` `adapter.value`s; `[-1]`/`[-2]` index that
bounded buffer; `float` at the read edge stays; `__len__` 0-before-warm stays.

**`min_period` delegation to PRESERVE** (handle.py :68-70):
```python
def min_period(self) -> int:
    return self._adapter.min_period(self._params)
```

---

### `itrader/strategy_handler/base.py` (strategy-base, evaluate seam) — Plans B + C

**Analog:** itself — the `evaluate` orchestration seam (:328-376), the `indicator()`
registrar (:275-291), and `_run_init` warmup derivation (:293-326).

**`indicator()` author-declaration registrar to PRESERVE the surface** (base.py :275-291) —
P5-D21 keeps `self.indicator(SMA, "close", window)` identical; underneath, the per-symbol
fan-out (P5-D10) keys one stateful set per symbol:
```python
def indicator(self, adapter: IndicatorAdapter, input_col: str, *params: int) -> IndicatorHandle:
    handle = IndicatorHandle(adapter, input_col, tuple(params))
    self._handles.append(handle)
    return handle
```

**The evaluate seam being RESTRUCTURED (P5-D13/G3)** — base.py :367-375, the repopulate+dispatch coupling to DECOUPLE into "update always, emit only when ready":
```python
self.bars: pd.DataFrame = window
self.now = window.index[-1] if len(window) else None
if self.now is not None:
    for handle in self._handles:
        handle.repopulate(self.bars, self.now, self.timeframe)
return self.generate_signal(ticker)
```
New contract (P5-D13/D14): `self.now = event.time`; `strategy.update(ticker, bar)`
pushes the latest completed bar to that ticker's handle-set; gate on
`strategy.is_ready(ticker)`; NO `self.bars`, NO `feed.window()` slice. Keep the
non-re-entrancy `_evaluating` guard idea (single-writer contract).

**Warmup derivation to KEEP as the gate-source** (base.py :320-326) — readiness moves from
`len(window) < warmup` to per-indicator `is_ready` (P5-D06), but `min_period` aggregation stays:
```python
self._handles: list[IndicatorHandle] = []
self.init()
derived = max((h.min_period() for h in self._handles), default=0)
self.warmup = derived
self.max_window = max(derived, type(self).max_window)
```

**New surfaces to add here:** `update(ticker, bar)`, `is_ready(ticker)`, per-symbol
lazy handle-set map keyed by ticker (P5-D10a — created on first bar), and `reset()`
(P5-D19, clears the fan-out map). The `causal`-guard rejection (P5-D20) lives at the
decision-path / `indicator()` registration boundary.

---

### `itrader/strategy_handler/strategies_handler.py` (handler-loop, event-driven) — Plan C

**Analog:** itself — `calculate_signals` single-leg loop (:94-147), `_dispatch_pair` (:258-311).

**The per-tick loop being RESTRUCTURED (P5-D14)** — strategies_handler.py :119-140, REMOVE the `feed.window()` slice and the len-gate:
```python
bar = event.bars.get(ticker)
if bar is None:
    continue
data = self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)
if len(data) < strategy.warmup:
    continue
intent = strategy.evaluate(ticker, data)
```
New shape (P5-D14): `strategy.update(ticker, bar)` → `if strategy.is_ready(ticker):` →
`generate_signal(ticker)`. The `bar is None` absence skip (gap bar) STAYS — it now also
means "no indicator update this tick" (P5-D10c, causality, state frozen).

**The price-stamp + fan-out path to PRESERVE byte-identically** (strategies_handler.py :204-254,
`_emit_intent`) — MARKET stamps `to_money(bar.close)`, one `SignalEvent` per subscribed
portfolio. This is downstream of the decision and UNCHANGED.

**Pair dispatch loop being migrated by P5-D15** (strategies_handler.py :294-301) — the
`feed.window()` + `beta_warmup + z_lookback` gate moves into the pair's own buffer/readiness:
```python
win_A = self.feed.window(ticker_A, strategy.timeframe, strategy.max_window, asof=event.time)
win_B = self.feed.window(ticker_B, strategy.timeframe, strategy.max_window, asof=event.time)
required = strategy.beta_warmup + strategy.z_lookback
if len(win_A) < required or len(win_B) < required:
    return
intents = strategy.evaluate_pair(win_A, win_B)
```

**Fixture migration (P5-D13a)** — the count/date fixtures
(SingleMarketBuy/ScriptedEmitter/BuyEachTickerOnce) read `self.bars`; migrate them to
bar-count / latest-bar PRESERVING their firing (so e2e/integration golden guards stay green).

---

### `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` (strategy) — reference-only

**Analog:** itself — the author surface is PRESERVED (P5-D21).

**The declaration + read surface that must stay byte-identical** (SMA_MACD_strategy.py :50-71):
```python
self.short_sma = self.indicator(SMA, "close", self.short_window)
self.long_sma = self.indicator(SMA, "close", self.long_window)
self.macd_hist = self.indicator(MACDHist, "close", self.fast_window, self.slow_window, self.signal_window)
...
if is_above(self.short_sma, self.long_sma):
    if crossover(self.macd_hist, 0):
        return self.buy(ticker)
    if crossunder(self.macd_hist, 0):
        return self.sell(ticker)
```
This file is the **re-baseline witness**, not an edit target: the values feeding
`is_above`/`crossover` change (stateful vs `ta`) but the firing tick (bar 100) and the
trade SET (134 trades) are empirically unchanged (RESEARCH §Empirical re-baseline safety proof).

---

### `itrader/strategy_handler/pair_base.py` + `eth_btc_pair_strategy.py` (pair) — Plan C

**Analog:** themselves — `PairStrategy.evaluate_pair` seam (pair_base.py :145-163), the
`max_window` validate (:97-128); `EthBtcPairStrategy._fit_beta` (:121-147), `_zscore` (:170-174),
`evaluate_pair` (:205-318).

**β fit-once-frozen pattern to MIGRATE onto the §4.2 stateful shape (P5-D15, RESEARCH Pattern 3)** —
eth_btc_pair_strategy.py :229-231 is the existing fit-once cache; the migration buffers the
OLDEST 250 bars, fits at first-ready, FREEZES:
```python
if self._beta is None:
    self._beta = self._fit_beta(win_A, win_B)
    p_value = self._coint_pvalue(win_A, win_B)
```

**z rolling-window pattern (P5-D15)** — eth_btc_pair_strategy.py :170-174, becomes a bounded
`z_lookback`=30 buffer; planner's sub-choice running-moments vs recompute-over-30 (RESEARCH OQ2 →
prefer recompute-over-30):
```python
def _zscore(self, spread: pd.Series, lookback: int) -> pd.Series:
    rolling_mean = spread.rolling(lookback).mean()
    rolling_std = spread.rolling(lookback).std()
    return (spread - rolling_mean) / rolling_std
```

**Multi-input `update` signature (P5-D09)** — the pair β/z indicator receives BOTH legs'
values per tick (`update(bar_A, bar_B)`); readiness = β fitted AND z buffer full = 280. The
`_crosses_into`/`_crosses_inside` band logic and the `_in_pair` flag (:176-201, :283-316) stay.

**β→money fence to PRESERVE (RESEARCH Pitfall 5)** — β is a float; it enters Decimal ONLY at
the β-weighted quantity via `to_money` (eth_btc_pair_strategy.py :302).

---

### `itrader/price_handler/feed/bar_feed.py` + `feed/base.py` (feed, streaming) — Plan A

**Analog:** themselves — `generate_bar_event` (:378-411), `current_bars` (:415-436), the
`_prebuilt` eager map (:235-251), the monotonic cursor `window` (:506-551), the `BarFeed` ABC.

**G5 unify-the-newest-bar-pass (P5-D16a)** — the existing per-symbol walk in
`current_bars` (:431-436) is the ONE walk to extend so it ALSO writes the cache newest row:
```python
bars: dict[str, Bar] = {}
for ticker in self._symbols:
    bar = self._prebuilt[ticker].get(time)
    if bar is not None:
        bars[ticker] = bar
return bars
```
`generate_bar_event` (:392-411) wraps that into one `BarEvent`/tick with a `{ticker: Bar}`
payload — unchanged shape (P5-D16a).

**Byte-exact preservation constraint (RESEARCH A3)** — the 7-rule contract (module docstring
:9-55) + the D-08/D-10 monotonic int64 cursor (`window` :506-551) MUST stay byte-for-byte; only
indicator VALUES re-baseline. The `_offset_alias`/`_readonly_master`/searchsorted-rebuild paths
are untouched.

**G1 update-trigger seam, interface-only (P5-D16b)** — the consolidator seam is "emit on
`(symbol,timeframe)` bucket-close → drives `update()`"; wiring asserts `base_timeframe ≤
min(timeframe)`; for golden `1d==base` it collapses to "every tick." Deep multi-bar cache is
DEFERRED (only newest-bar + registration interface ships).

---

### Shared-cache consumer-registration / capacity-derivation fn (NEW) — Plan A

**Analog (THE mirror to copy, P5-D16 — do NOT invent a new mechanism):**
`itrader/universe/instruments.py::derive_instruments` (:170-255) +
`itrader/universe/membership.py::derive_membership` (:44-83).

**The pure derive-once-at-wiring shape to MIRROR** (membership.py :44-83) — no class, no state,
no queue/feed/store import; composes over the registered consumers; sorted/deduped output:
```python
def derive_membership(strategies, screener_tickers=()) -> list[str]:
    tickers: list[str] = []
    for strategy in strategies:
        for entry in strategy.tickers:
            if isinstance(entry, tuple):
                tickers.extend(entry)
            else:
                tickers.append(entry)
    tickers.extend(screener_tickers)
    return sorted(set(tickers))
```

**The "compose, never reimplement, ladder per member" shape** (instruments.py :208-255) — the
new capacity fn keys off RAW-BAR consumers (NOT indicator `min_period`, P5-D07/D22): indicators
self-buffer, so Plan A's capacity is the max raw-history depth any registered raw-bar consumer
requests. With no raw-bar consumer yet, the deep cache is deferred; the INTERFACE ships now.

**Purity rule to honor** (instruments.py :3-8): "pure function producing derived data at wiring
time … no parallel registry subsystem."

---

## Shared Patterns

### Float64 / money fence (apply to ALL Plan B/C indicator code)
**Source:** `catalog.py` :25-28 + `primitives.py` :19-24 docstrings (RESEARCH Pitfall 5).
**Apply to:** every recurrence in `catalog.py`, the handle buffer, the pair β/z.
```
Indicator values are pandas float64 (the ta compute domain), NOT money — never
routed through to_money. (β enters Decimal ONLY at the β-weighted quantity.)
```

### Read-before-ready loud guard (apply to handle + adapter value reads)
**Source:** `handle.py` :53-62 (`RuntimeError`, survives `-O`). Mirror the explicit-raise
(not bare `assert`) discipline for any new ordering contract.

### Comparison primitives — BYTE-EXACT, UNCHANGED (reference only)
**Source:** `itrader/strategy_handler/primitives.py` :58-75 (`is_above`/`crossover`/`crossunder`,
code D-02 inclusive-on-current-bar). The decision logic reads these; do NOT touch them — they are
a load-bearing byte-exact lever. The re-baseline flows through the VALUES fed in, not the operators.

### Pure derive-once-at-wiring fn (apply to the Plan A registration interface)
**Source:** `membership.py` :44-83 / `instruments.py` :170-255 — no class/state/queue, compose
over registered consumers, sorted-deduped output, "propose/dispose" extensibility. The screener
extension lands here with zero structural change (P5-D16).

### Re-baseline gate — REUSE, don't rebuild (apply to Plan B verification)
**Source:** `tests/integration/test_backtest_oracle.py` (`test_oracle_behavioral_identity` :128
trade keys; `test_oracle_numeric_values` :173 numeric) + `tests/golden/CROSS-VALIDATION.md`
(backtesting.py + backtrader gating, 1% rel tol). Behavioral identity (134 trades) stays GREEN;
numeric values re-freeze AFTER cross-val PASS (P5-D02). The oracle already separates identity from
numeric — exactly the seam the re-baseline needs.

### Determinism + reset (apply to Plan B new tests)
**Source:** `test_indicators.py` :151-159 (`test_handle_repopulate_is_re_runnable`) is the analog
for `test_indicator_reset.py` (P5-D19: `reset()`→re-feed == fresh run). The `pytest.raises`
shape (:162-171) is the analog for `test_causal_guard.py` (P5-D20).

### Convergence test — direct feed, no cache (Model B, P5-D17)
**Source:** `test_indicators.py` :71-122 (ta value-equality via `pd.testing.assert_series_equal`)
is the existing analog; the NEW `test_indicator_convergence.py` feeds bars one-by-one and asserts
convergence to `ta` batch POST each indicator's `min_period` at `atol=1e-9, rtol=1e-6`, comparing
only where BOTH series are non-NaN (RESEARCH §convergence-test shape; Pitfall 4 — MACD transient is
pre-warmup, skip it).

---

## No Analog Found

None. Every new surface has a direct in-repo analog (the file it converts, or the
`universe/` derive-once mirror, or the existing indicator/oracle tests). This is a
convert-in-place phase, not a greenfield one — the three "new" test files all copy
the structure of `tests/unit/strategy/test_indicators.py`.

---

## Indentation Map (planner read_first/action must respect — RESEARCH Pitfall 6)

| Surface | Indent |
|---------|--------|
| `itrader/strategy_handler/**` (catalog, handle, base, strategies_handler, pair_base, strategies/*, indicators/__init__) | **TABS** |
| `tests/unit/strategy/**` (incl. the 3 NEW test files) | **TABS** (match `test_indicators.py`) |
| `itrader/price_handler/feed/**` (bar_feed, base) | **4 SPACES** |
| `itrader/universe/**` (the derive-fn mirror) + a new feed-side registration fn | **4 SPACES** |
| `tests/integration/test_backtest_oracle.py` | **4 SPACES** |

A mixed-indentation diff breaks a tab file and mypy will NOT catch it — match the file.

## Metadata

**Analog search scope:** `itrader/strategy_handler/{indicators,strategies}/`, `itrader/price_handler/feed/`, `itrader/universe/`, `tests/unit/strategy/`, `tests/integration/`, `tests/golden/`.
**Files scanned:** 14 source/test files read in full + indentation probe across 9.
**Pattern extraction date:** 2026-06-24
