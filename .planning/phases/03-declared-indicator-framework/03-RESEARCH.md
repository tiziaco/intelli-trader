# Phase 3: Declared-Indicator Framework - Research

**Researched:** 2026-06-12
**Domain:** Strategy authoring framework — declared indicators, pre-evaluated handles, free-function comparison primitives, byte-exact migration of the reference strategy
**Confidence:** HIGH (key byte-exact claims empirically verified in-environment against `ta` 0.11.0 / pandas 2.3.3)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Full primitive-driven migration.** SMA filter → `is_above(short_sma, long_sma)`; MACD arms → `crossover(macd_hist, 0)` / `crossunder(macd_hist, 0)`. Ship `is_above(a,b)` / `is_below(a,b)` alongside the required `crossover` / `crossunder` (additive, not scope creep).
- **D-02 — Inclusive-on-current-bar boundary semantics** (the byte-exact lever):
  - `crossover(a, b)` ≙ `a[-2] < b[-2] and a[-1] >= b[-1]`
  - `crossunder(a, b)` ≙ `a[-2] > b[-2] and a[-1] <= b[-1]`
  - `is_above(a, b)` ≙ `a[-1] >= b[-1]`; `is_below(a, b)` ≙ `a[-1] <= b[-1]`
  - Matches the reference's existing operators exactly. Second arg accepts a **scalar** (`crossover(macd_hist, 0)`), broadcast as `b[-1] == b[-2] == scalar`. Deliberate departure from textbook-strict (`a[-1] > b[-1]`).
- **D-03 — Pre-evaluated handles are a thin positional-index wrapper** (backtesting.py-style): `[-1]` = last value, `[-2]` = previous, positional. Backend-agnostic seam (keeps stateless/incremental/ML backends open). Wraps the same `dropna()`'d values → byte-exact. It is what the primitives operate on (and they accept a scalar 2nd arg).
- **D-04 — Indicators referenced by typed adapter symbols** from a catalog: `self.indicator(SMA, "close", self.short_window)` where `SMA`/`MACDHist`/… are real symbols (mypy-visible, no stringly-typed name). Each adapter wraps the existing `ta` call AND exposes a `min_period(params)`. Extensible + strategy-decoupled.
- **D-05 — Split module layout:** new `itrader/strategy_handler/indicators.py` holds the adapter catalog; the free-function primitives live in a **sibling** module (`primitives.py` recommended; avoid `signals.py` which collides with `SignalEvent`/`SignalIntent`). Both under `strategy_handler/`, **tab** indentation. Two imports for authors.
- **D-06 — `generate_signal(self, ticker)` — the `bars` parameter is dropped.** Before each per-ticker call the base stashes on `self`: pre-evaluated handles, `self.bars` (full raw completed-bars DataFrame — the raw-data escape hatch), and `self.now` (decision timestamp = `self.bars.index[-1]`). Named `self.bars` (not `self.window`) to avoid collision with the integer `*_window`/`warmup` attrs. Per-call context, refreshed per ticker.
- **D-07 — Ship SMA + MACDHist + EMA + RSI in v1.** SMA + MACDHist are required by the reference (oracle-gated). EMA + RSI are additive, unused by the reference (cannot touch the golden), need their own light unit tests + `min_period` conventions (`EMA(w)→w`, `RSI(w)→w`).
- **D-08 — `min_period` is the first-valid-value period ONLY** (SMA/EMA/RSI → `w`; MACD → `slow + signal`), NOT a convergence buffer. The base computes every indicator over the **full `self.bars` window**. `warmup` (firing gate) = `max_window` (fetch width) = `max(min_period)` across registered recipes. For the reference: `MACD.min_period = 15 < SMA long_window = 100`, so `max_window` stays **100**. The trap to avoid: baking a convergence buffer into `min_period` (would push MACD over 100, enlarge `max_window`, shift the MACD value, break the golden) — explicitly rejected.

### Claude's Discretion

- **Handle wrapper interface** — exact surface (`__getitem__`/`__len__` only vs richer). Wrapper as default; finalize at planning, gated by `mypy --strict` + oracle.
- **Handle binding mechanism** — `self.indicator(...)` returns a registered handle (initially empty) the author binds to `self.short_sma`; the base re-populates that same handle each tick (recipe stored on the handle). backtesting.py's `self.I()` pattern.
- **Base orchestration entry point** — handler calls a base-level wrapper (e.g. `evaluate`/`on_bar`) that sets `self.bars`/`self.now`, repopulates handles, then dispatches to `generate_signal(ticker)`. Name + exact shape Claude's discretion.
- **Input spec** — a column-name string (`"close"`); all four v1 indicators are close-only. Multi-column deferred.
- **Primitives module name** (`primitives.py` recommended), input-string default, exact `min_period` formulas — finalize at planning, oracle-gated.

### Deferred Ideas (OUT OF SCOPE)

- **ewm convergence-buffer / "unstable period" mechanism + overridable `max_window` fetch-width** (the rejected D-08 option-2). Only bites EMA/RSI-only strategies with no SMA pinning the window. → future phase / backlog.
- **Stateful/incremental indicator backends (W1-05 / IND-02)** — O(1) per-tick behind the same stable handle interface. Byte-exactness risk is structural (`ewm(adjust=True)` vs `adjust=False`). → future phase.
- **Multi-column indicators** (ATR/Stochastic needing HLC) — input spec is a single column-name string in v1. Extend when the first multi-input indicator lands.
- **Indicator-based SL/TP** — recipe kept strategy-decoupled; percent-offset SL/TP stays.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| IND-01 | Declared-indicator framework on the strategy base — indicators registered in `init()` (declaration only: func + input + params), evaluated per-tick from the pushed window using the same `ta` calls as today, with auto-derived `warmup`/`max_window`; free-function `crossover`/`crossunder` over series (look-ahead-safe). Byte-exact. | §Standard Stack (`ta` 0.11.0 call shapes verified), §Architecture Patterns (handle wrapper, adapter catalog, orchestration seam), §Common Pitfalls (the slice-vs-full SMA ULP landmine — Pitfall 1), §Code Examples (verified `ta` + primitive shapes), §Byte-Exact Verification |
</phase_requirements>

## Summary

This is a **byte-exact** brownfield refactor with a converged, locked design (D-01..D-08). The job is not design but **surfacing the concrete implementation knowledge that makes the migration byte-exact by construction**. Three new mechanisms land on the strategy base: (1) declaration-only indicator recipes registered in `init()`; (2) a thin positional-index handle wrapper the base re-populates per tick; (3) auto-derived `warmup`/`max_window`. Two new sibling modules (`indicators.py` adapter catalog, `primitives.py` free functions) and a base orchestration seam (`evaluate`/`on_bar`) that sets `self.bars`/`self.now`, repopulates handles, then calls `generate_signal(ticker)`. The reference `SMAMACDStrategy` migrates fully onto this surface; the `EmptyStrategy` + two e2e fixtures migrate their `generate_signal` signature.

**The single most important finding — and it CONTRADICTS one claim in CONTEXT.md.** CONTEXT.md `<code_context>` states "the SMA tail value is slice-independent." **This is empirically FALSE.** pandas `rolling().mean()` (which `ta.SMAIndicator` wraps) uses a streaming running-sum algorithm whose result at the tail position depends on the **accumulation history of the whole input series**, not just the trailing `w` elements. I verified in-environment (`ta` 0.11.0, pandas 2.3.3) that SMA(50) computed over the current code's sliced window (`bars[start_dt:]` = 51 rows) differs from SMA(50) over the full 100-bar window by **1 ULP (~1e-13), data-dependently** — sometimes equal, sometimes not. The today-code computes **short SMA on a 51-row slice, long SMA on the full window, MACD on the full window**. A model-B base that uniformly computes every indicator over the full `self.bars` window would therefore **silently break the BTCUSD oracle on the short SMA**. The adapter/orchestration design MUST replicate the current per-indicator input slice exactly (`start_dt = last_time - timeframe * window`), or the planner must accept that the short SMA's input differs and validate against the oracle. This is the #1 byte-exact landmine.

**Primary recommendation:** Make each SMA adapter recompute over the **same `bars[start_dt:]` slice the current code feeds it** (`start_dt = self.now - self.timeframe * window`), NOT over the uniform full window. MACD already runs on the full window (no slice) — keep it that way. Drive the migration to byte-exactness by replicating the *input window per indicator*, then prove it with the existing oracle test (`tests/integration/test_backtest_oracle.py`) and the e2e suite. There is no SMA_MACD unit test guarding the MACD value (only the oracle), so the oracle gate is load-bearing.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Indicator recipe declaration (`init()`) | Strategy base (`base.py`) | — | The base owns the `init()` lifecycle hook (Phase 2); recipes are pure declaration, no compute. |
| Per-tick indicator evaluation (`ta` calls) | Strategy base orchestration seam | Adapter catalog (`indicators.py`) | The base repopulates handles before dispatch; the adapter encapsulates the exact `ta` call + input slice. Compute belongs with the strategy domain (it always has — inline today). |
| Auto-derive `warmup`/`max_window` | Strategy base (`init()` post-pass) | Adapter `min_period(params)` | The base inspects registered recipes; each adapter answers its own min-period. |
| Comparison primitives (`crossover`/`is_above`/…) | Free functions (`primitives.py`) | — | Pure functions over handle/scalar; no engine state. Look-ahead-safe by reading only completed-bar window positions. |
| Window delivery (push per tick) | Price-handler feed (`bar_feed.py`) | — | Unchanged. The handler reads `feed.window(...)` and now passes it to the base orchestration seam instead of `generate_signal(ticker, bars)`. |
| Warmup short-circuit (skip tick if `len(window) < warmup`) | `StrategiesHandler.calculate_signals` (D-15) | — | Unchanged logic; now reads the auto-derived `strategy.warmup`. |
| Signal fan-out / stamping / enqueue | `StrategiesHandler` | — | Unchanged — fully downstream of `generate_signal`. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ta` | 0.11.0 | Technical-indicator compute (`trend.SMAIndicator`, `trend.MACD`, `trend.EMAIndicator`, `momentum.RSIIndicator`) | Already the in-repo TA library; reused verbatim so recompute stays byte-identical `[VERIFIED: importlib.metadata version 0.11.0 in-environment]` |
| `pandas` | 2.3.3 | Underlying Series/rolling math `ta` builds on | Already pinned; the rolling-mean accumulation behavior is the byte-exact lever `[VERIFIED: pandas.__version__ in-environment]` |

No new dependencies. This phase adds **only first-party modules** (`indicators.py`, `primitives.py`) — no `pip install`.

**`ta` 0.11.0 verified call shapes** (signatures inspected in-environment):
- `trend.SMAIndicator(close: pd.Series, window: int, fillna: bool = False)` → `.sma_indicator()` returns `pd.Series`. Current code: `trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()` — the 3rd positional arg `True` is `fillna`.
- `trend.MACD(close: pd.Series, window_slow=26, window_fast=12, window_sign=9, fillna=False)` → `.macd_diff()` returns the histogram (`macd - signal`). Current code: `trend.MACD(bars.close, window_fast=self.fast_window, window_slow=self.slow_window, window_sign=self.signal_window, fillna=False).macd_diff().dropna()`.
- `trend.EMAIndicator(close, window, fillna=False)` → `.ema_indicator()` (additive, D-07).
- `momentum.RSIIndicator(close, window, fillna=False)` → `.rsi()` (additive, D-07).

> **`[VERIFIED: in-environment]`** `inspect.signature` confirmed `SMAIndicator.__init__(self, close, window, fillna=False)` and `MACD.__init__(self, close, window_slow=26, window_fast=12, window_sign=9, fillna=False)` against `ta` 0.11.0.

### Supporting
None — the framework is built from `ta` + pandas + stdlib typing.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Replicate per-indicator input slice | Compute all indicators on the uniform full window | REJECTED for SMA — breaks the oracle by 1 ULP on the short SMA (verified). Acceptable only for MACD (already full-window) and the additive EMA/RSI (oracle-dark). |
| `ta` recompute | Incremental/stateful backend | Deferred (IND-02) — structural byte-exactness risk (`ewm(adjust)`). |
| Thin positional wrapper (D-03) | Raw pandas Series + `.iloc[-1]` | D-03 locks the wrapper for the future incremental switch; raw Series would leak the backend. |

**Installation:** None required — `ta` and `pandas` are already in `pyproject.toml`. No registry interaction this phase.

## Package Legitimacy Audit

> Not applicable — this phase installs **zero** external packages. All compute reuses `ta` 0.11.0 and `pandas` 2.3.3, both already committed to `poetry.lock`. slopcheck/registry verification is moot (no new dependency). The two new modules are first-party (`itrader/strategy_handler/indicators.py`, `itrader/strategy_handler/primitives.py`).

## Architecture Patterns

### System Architecture Diagram

```
StrategiesHandler.calculate_signals(BarEvent)              [cross-domain seam — UNCHANGED logic]
   │  per strategy, per ticker:
   │     bar = event.bars.get(ticker)            ── skip if None (sparse guard)
   │     window = feed.window(ticker, tf, strategy.max_window, asof=event.time)
   │     if len(window) < strategy.warmup: continue          ── D-15 short-circuit (reads AUTO-derived warmup)
   │     ┌──────────────────────────────────────────────────────────────┐
   └────▶│ strategy.evaluate(ticker, window)   ◀── NEW base orchestration seam (replaces generate_signal(ticker, bars)) │
         │   self.bars = window                                          │
         │   self.now  = window.index[-1]                                │
         │   for handle in self._handles:                                │
         │       handle.repopulate(self.bars, self.now, self.timeframe)  │── per-indicator INPUT SLICE (Pitfall 1)
         │   return self.generate_signal(ticker)   ◀── author code, reads handles + primitives │
         └──────────────────────────────────────────────────────────────┘
                          │ returns SignalIntent | None
                          ▼
   signal_store.add(SignalRecord(..., config=strategy.to_dict()))    [UNCHANGED — to_dict now auto-derived warmup/max_window]
   fan-out per subscribed portfolio → SignalEvent → global_queue     [UNCHANGED]

init()  [Phase-2 idempotent hook, called at construction + reconfigure]:
   self.short_sma = self.indicator(SMA, "close", self.short_window)   ── registers recipe, returns empty handle
   ...
   └─ base post-init pass: self.warmup = self.max_window = max(recipe.min_period() for recipe in self._handles)
```

### Recommended Project Structure
```
itrader/strategy_handler/
├── base.py            # Strategy ABC: init() recipe registration, self.indicator(),
│                      #   auto-warmup derivation, evaluate() orchestration seam,
│                      #   the IndicatorHandle wrapper (or a co-located handle.py — discretion)
├── indicators.py      # NEW: typed adapter catalog — SMA, MACDHist, EMA, RSI symbols,
│                      #   each wrapping its ta call + min_period(params). TABS.
├── primitives.py      # NEW: crossover, crossunder, is_above, is_below free functions. TABS.
├── strategies/
│   ├── SMA_MACD_strategy.py   # migrate: register recipes in init(), drop hand-set
│   │                          #   max_window/warmup, generate_signal(ticker) via primitives
│   └── empty_strategy.py      # migrate generate_signal(ticker) signature only
└── strategies_handler.py      # calculate_signals: call evaluate(ticker, window) seam
```

### Pattern 1: Declaration-only recipe + registered-empty-then-repopulated handle (backtesting.py `self.I()` shape)
**What:** `self.indicator(ADAPTER, input, *params)` in `init()` stores a recipe and returns an empty `IndicatorHandle`. The base re-populates that same handle object each tick from the pushed window. The author binds it to a named attr (`self.short_sma = self.indicator(...)`).
**When to use:** Every declared indicator.
**Why this shape (D-03):** the read-site `self.short_sma[-1]` is invariant across a future stateless→incremental switch — the wrapper hides the backend.
**Example:**
```python
# itrader/strategy_handler/base.py (TABS) — illustrative; finalize at planning
class IndicatorHandle:
	"""Thin positional-index wrapper over a recomputed pandas Series (D-03)."""
	def __init__(self, adapter, input_col, params):
		self._adapter = adapter
		self._input = input_col
		self._params = params
		self._values: pd.Series | None = None   # empty until first repopulate
	def repopulate(self, bars, now, timeframe) -> None:
		# Pitfall 1: the adapter owns its OWN input slice for byte-exactness.
		self._values = self._adapter.compute(bars, self._input, self._params, now, timeframe)
	def __getitem__(self, idx: int) -> float:
		assert self._values is not None
		return float(self._values.iloc[idx])       # [-1], [-2] positional
	def __len__(self) -> int:
		return 0 if self._values is None else len(self._values)
	def min_period(self) -> int:
		return self._adapter.min_period(self._params)
```

### Pattern 2: Typed adapter catalog (D-04) — callable class symbols exposing `compute` + `min_period`
**What:** `SMA`, `MACDHist`, `EMA`, `RSI` are real importable symbols (mypy-visible). Each encapsulates the exact `ta` call AND the per-indicator input slice AND its `min_period`.
**When to use:** The catalog backing every recipe.
**Typing tradeoffs (mypy --strict):**
- **Singleton instance of a class** (recommended): `class _SMA: def compute(...)->pd.Series; def min_period(p)->int`, then `SMA = _SMA()`. Real symbol, fully typed, no metaclass. Clean under `--strict`.
- **`Protocol` + module-level instances:** define an `IndicatorAdapter` Protocol the handle/base type against; each adapter structurally satisfies it. Best for the `_handles: list[IndicatorHandle]` typing and the `min_period` call.
- **Avoid:** plain functions stuffed in a dict (stringly-typed lookup — exactly what D-04 forbids) and metaclass/`__init_subclass__` registration (backtrader's rejected mechanism).
**Example:**
```python
# itrader/strategy_handler/indicators.py (TABS) — illustrative
from ta import trend

class _SMA:
	def compute(self, bars, input_col, params, now, timeframe) -> "pd.Series":
		(window,) = params
		# Pitfall 1 (BYTE-EXACT): replicate the current per-indicator slice EXACTLY.
		# Today: start_dt = last_time - self.timeframe * self.short_window; bars[start_dt:].close
		start_dt = now - timeframe * window
		return trend.SMAIndicator(bars[start_dt:][input_col], window, True).sma_indicator().dropna()
	def min_period(self, params) -> int:
		(window,) = params
		return window                      # SMA(w) -> w  (D-08, first-valid period only)

class _MACDHist:
	def compute(self, bars, input_col, params, now, timeframe) -> "pd.Series":
		fast, slow, signal = params
		# Today: MACD on the FULL window (NO slice) — keep it that way.
		return trend.MACD(bars[input_col], window_fast=fast, window_slow=slow,
		                  window_sign=signal, fillna=False).macd_diff().dropna()
	def min_period(self, params) -> int:
		fast, slow, signal = params
		return slow + signal               # MACD -> slow+signal (D-08)

SMA = _SMA()
MACDHist = _MACDHist()
# EMA, RSI analogous (additive, oracle-dark): min_period(w) -> w each.
```

### Pattern 3: Free-function comparison primitives (D-02) with scalar broadcast
**What:** `crossover`/`crossunder`/`is_above`/`is_below` over a handle and a handle-or-scalar.
**When to use:** Every firing condition in `generate_signal`.
**Example:**
```python
# itrader/strategy_handler/primitives.py (TABS) — illustrative, matches D-02 exactly
def _at(series_or_scalar, idx: int) -> float:
	# Scalar broadcast: b[-1] == b[-2] == scalar (D-02).
	if isinstance(series_or_scalar, (int, float)):
		return float(series_or_scalar)
	return float(series_or_scalar[idx])

def is_above(a, b) -> bool:
	return _at(a, -1) >= _at(b, -1)            # a[-1] >= b[-1]
def is_below(a, b) -> bool:
	return _at(a, -1) <= _at(b, -1)            # a[-1] <= b[-1]
def crossover(a, b) -> bool:
	return _at(a, -2) <  _at(b, -2) and _at(a, -1) >= _at(b, -1)
def crossunder(a, b) -> bool:
	return _at(a, -2) >  _at(b, -2) and _at(a, -1) <= _at(b, -1)
```
> **Byte-exact mapping to today's operators (verified by reading `SMA_MACD_strategy.py`):**
> - `short_sma.iloc[-1] >= long_sma.iloc[-1]` → `is_above(self.short_sma, self.long_sma)` ✓
> - `MACDhist.iloc[-1] >= 0 and MACDhist.iloc[-2] < 0` → `crossover(self.macd_hist, 0)` ✓ (D-02 inclusive `>=` on current, strict `<` on previous)
> - `MACDhist.iloc[-1] <= 0 and MACDhist.iloc[-2] > 0` → `crossunder(self.macd_hist, 0)` ✓

### Anti-Patterns to Avoid
- **Uniform full-window SMA compute:** computing SMA over `self.bars` (full window) instead of the current `bars[start_dt:]` slice. Breaks the oracle (Pitfall 1).
- **Stringly-typed indicator names:** `self.indicator("SMA", ...)` — D-04 mandates typed symbols.
- **Baking a convergence buffer into `min_period`:** D-08 — would enlarge `max_window`, shift the MACD value, break the golden.
- **`crossover` reading the forming bar:** the feed window holds only completed bars (rule 4, `bar_feed.py`); `[-1]` is the last completed bar — look-ahead-safe by construction. Never reach beyond `[-1]`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SMA / EMA / MACD / RSI math | A custom rolling-mean / ewm implementation | The existing `ta` 0.11.0 calls **verbatim** | A re-implementation will NOT reproduce pandas' exact rolling/`ewm` accumulation → guaranteed oracle break. Byte-exactness depends on calling the *same* `ta` code. |
| Min-period / warmup arithmetic | A clever closed-form for all indicators | A per-adapter `min_period(params)` method (D-04/D-08) | Each indicator's first-valid period differs (SMA→w, MACD→slow+signal); centralize per adapter. |
| Crossover detection | A pandas `.shift()`/vectorized crossover series | Two positional reads `[-2]`/`[-1]` (D-02) | The engine pushes one window per tick; a scalar boolean from two positions is exact and look-ahead-safe. Avoids backtrader's `CrossOver`-as-indicator-object machinery. |

**Key insight:** In a byte-exact phase, *every* indicator value must come from the identical library call path the oracle was frozen against. The framework's value is ergonomic (declaration + auto-warmup + handles), NOT a new compute path. The compute must be a pass-through.

## Runtime State Inventory

> This is a code-refactor of the strategy authoring surface — there is **no stored data, live-service config, OS-registered state, or secret** that embeds an indicator recipe or handle. The only persisted artifact touched is the **golden master** (`tests/golden/{trades,equity,summary}.csv/json`), which must NOT change (byte-exact phase).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — indicators are computed per-tick from the in-memory feed window; nothing persisted. The `SignalRecord.config` dict snapshots `strategy.to_dict()`, which now reports auto-derived `max_window`/`warmup` instead of hand-set values. | Verify `to_dict()` still emits `max_window`/`warmup` (it introspects `get_type_hints` — both are annotated base attrs, so they remain captured). No data migration. |
| Live service config | None — no external service holds indicator state. | None — verified: indicators are strategy-local. |
| OS-registered state | None. | None. |
| Secrets/env vars | None. | None. |
| Build artifacts | None — pure source edits within `itrader/strategy_handler/`. | None. |

**The one "frozen artifact" at risk:** `tests/golden/` (the BTCUSD oracle) + the 46 e2e leaf `golden/` dirs. These must stay byte-identical — that is the phase gate, not a migration target.

## Common Pitfalls

### Pitfall 1: The slice-vs-full-window SMA divergence (THE byte-exact landmine) — CONTRADICTS CONTEXT.md
**What goes wrong:** A model-B base that computes every indicator over the uniform full `self.bars` window produces a short-SMA tail value that differs from today's value by ~1e-13 (1 ULP), **data-dependently**. On the BTCUSD oracle this can flip a `short_sma[-1] >= long_sma[-1]` boundary tick and change a trade → oracle break (≠ 134 trades / 46189.87730727451).
**Why it happens:** `ta.SMAIndicator(...).sma_indicator()` wraps pandas `Series.rolling(window).mean()`, which uses a **streaming running-sum** (add-new/subtract-old) algorithm. The float result at the tail position depends on the accumulation history of the *entire input series*, not just the trailing `w` elements. Today's code feeds SMA a **sliced** input (`bars[start_dt:].close`, where `start_dt = last_time - timeframe * window`); that slice is 51 rows for the short SMA (window 50) and 100 rows for the long SMA (window 100). Feeding the full 100-row window to the short SMA changes the accumulation prefix → last-ULP drift.
**Verified in-environment** (`ta` 0.11.0 / pandas 2.3.3):
```
rolling on 51-slice : 1012.9679649187834
rolling on 100-full : 1012.9679649187833   ← differs in last ULP
51-slice == 100-full: False   diff: 1.14e-13
```
The divergence is data-dependent: across different synthetic series the short-SMA `[-1]` was equal in 2 of 3 trials and unequal in 1. **You cannot assume it is safe.** CONTEXT.md `<code_context>` asserts "the SMA tail value is slice-independent" — this is incorrect; flag it to the planner.
**How to avoid:** Make each SMA adapter recompute over the **same `bars[start_dt:]` slice** the current code feeds (`start_dt = self.now - self.timeframe * window`). The MACD adapter keeps the full-window input (today's `bars.close`, no slice). Then the migration is byte-exact by construction. The long SMA (window == max_window == 100) is slice-invariant (the slice == the full window), but the short SMA (window 50 < 100) is NOT — so the per-indicator slice is mandatory for SMA.
**Warning signs:** Oracle test fails with a *small* trade-count or equity delta (1-2 trades), not a large structural change — the tell-tale of an ULP boundary flip rather than a logic error.

### Pitfall 2: Eager-vs-lazy MACD reorder (this one IS safe — verify and document)
**What goes wrong:** Today MACD is computed **lazily inside** the SMA filter guard (W1-12) — only on ticks where the SMA filter holds. Model-B pre-eval computes MACD **eagerly every tick**. A reviewer may fear the reorder changes values.
**Why it's safe:** The MACD call is a pure function of the same full window; computing it eagerly vs lazily yields the identical value (`macd_eager == macd_lazy` verified `True` in-environment). The only difference is *how often* it runs, not *what* it returns. No SMA_MACD unit test guards the MACD value — only the oracle — so document the reorder as proven by code review + the byte-exact oracle (per CONTEXT.md `<code_context>`).
**How to avoid:** Nothing to avoid — but note the eager pre-eval is mandatory in model B (handles are populated before `generate_signal` runs). Confirm via the oracle.
**Warning signs:** None expected; if the oracle breaks it is Pitfall 1 (SMA), not this.

### Pitfall 3: `warmup` gate value must stay exactly 100
**What goes wrong:** Auto-derivation computes `warmup = max(min_period) = max(SMA50→50, SMA100→100, MACD→15) = 100`. If `min_period` for any adapter is mis-defined (e.g. MACD → `slow+signal+buffer`, or SMA → `w+1`), `warmup`/`max_window` shifts off 100, changing which ticks fire (D-15 short-circuit) and how wide a window MACD sees → oracle break.
**Why it happens:** D-08's "first-valid period only" is easy to violate by adding a convergence/stabilization buffer (the deferred option-2).
**How to avoid:** `min_period`: SMA/EMA/RSI → `w`; MACD → `slow + signal` (= 15 for 6/12/3). `max(50,100,15) == 100` — verified. The reference must end with `warmup == max_window == 100` after `init()`. Assert this in a unit test on the migrated strategy.
**Warning signs:** `strategy.warmup != 100` after construction → wrong `min_period` formula.

### Pitfall 4: `self.now` vs the dropped `bars`-derived `last_time`
**What goes wrong:** Today `generate_signal(ticker, bars)` reads `last_time = bars.index[-1]`. D-06 drops `bars`; the base must stash `self.now = self.bars.index[-1]` BEFORE dispatch, and the SMA `start_dt` arithmetic must use `self.now` (or be done inside the adapter from `now`). If `self.now` is set from anything other than the same window's last index, the SMA slice shifts.
**Why it happens:** The slice anchor moves from a local var to instance state across the seam.
**How to avoid:** In `evaluate(ticker, window)`: `self.bars = window; self.now = window.index[-1]`. Pass `now`+`timeframe` into `handle.repopulate(...)` so each adapter computes `start_dt` identically. This preserves the exact `start_dt = last_time - timeframe * window` the current code uses.
**Warning signs:** Off-by-one-bar SMA window → oracle break.

### Pitfall 5: Indentation — tabs in `strategy_handler/`, spaces in e2e fixtures
**What goes wrong:** New modules `indicators.py`/`primitives.py` and edits to `base.py`/`SMA_MACD_strategy.py`/`empty_strategy.py` MUST use **tabs** (D-05, CLAUDE.md). The two e2e fixtures (`tests/e2e/strategies/scripted_emitter.py`, `single_market_buy.py`) use **4 spaces** (they declare it in their docstrings, matching `tests/conftest.py`). A mixed-indentation diff in a tab file breaks it.
**How to avoid:** Match the file. `base.py` and `SMA_MACD_strategy.py` are tabs; the e2e fixtures are spaces — verified by reading the files (the e2e fixtures' `generate_signal` migration is a spaces edit).
**Warning signs:** `mypy`/import error or a visually-broken diff.

### Pitfall 6: The e2e and Empty/Scripted/SingleMarketBuy fixtures don't use indicators — migrate signature ONLY
**What goes wrong:** `EmptyStrategy`, `ScriptedEmitter`, `SingleMarketBuy` register no indicators; they read `bars` directly (`bars.index[-1]`, `len(bars)`, `bars.empty`). Their `generate_signal(ticker, bars)` must migrate to `generate_signal(ticker)` reading `self.bars`. If `self.bars` isn't set for a strategy with zero handles, these break.
**Why it happens:** The orchestration seam must set `self.bars`/`self.now` for **every** strategy, indicator-declaring or not.
**How to avoid:** `evaluate(ticker, window)` always sets `self.bars`/`self.now` and always repopulates `self._handles` (empty list for these fixtures — a no-op loop), then dispatches. The fixtures replace `bars` reads with `self.bars` reads (`len(self.bars)`, `self.bars.index[-1].tz_convert("UTC")`, `self.bars.empty`).
**Warning signs:** e2e leaves fail (≠ 58/58 — see Open Question 1 on the exact count) with `AttributeError: 'X' object has no attribute 'bars'` or a `TypeError` on the `generate_signal` arity.

## Code Examples

### Verified `ta` call shapes (the byte-exact compute path)
```python
# Source: itrader/strategy_handler/strategies/SMA_MACD_strategy.py (current) + verified in-env
from ta import trend
# SMA (short): sliced input — Pitfall 1
start_dt = last_time - self.timeframe * self.short_window
short_sma = trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()
# MACD histogram: FULL-window input, no slice
MACDhist = trend.MACD(bars.close, window_fast=self.fast_window, window_slow=self.slow_window,
                      window_sign=self.signal_window, fillna=False).macd_diff().dropna()
# fillna=True back-fills leading NaN; dropna() then drops nothing — but the TAIL value is
# IDENTICAL with fillna True or False (verified). fillna only affects leading values.
```

### Target authoring shape (from CONTEXT.md `<specifics>`, D-01/D-06)
```python
# itrader/strategy_handler/strategies/SMA_MACD_strategy.py (migrated) — TABS
from itrader.strategy_handler.indicators import SMA, MACDHist
from itrader.strategy_handler.primitives import crossover, crossunder, is_above

def init(self):
	self.short_sma = self.indicator(SMA, "close", self.short_window)
	self.long_sma  = self.indicator(SMA, "close", self.long_window)
	self.macd_hist = self.indicator(MACDHist, "close", self.fast_window,
	                                self.slow_window, self.signal_window)
	# NO hand-set max_window/warmup — base derives them post-init (max(min_period) == 100).

def generate_signal(self, ticker):            # no bars param (D-06)
	if is_above(self.short_sma, self.long_sma):           # short_sma[-1] >= long_sma[-1]
		if crossover(self.macd_hist, 0):  return self.buy(ticker)
		if crossunder(self.macd_hist, 0): return self.sell(ticker)
	return None
```

### `validate()` cross-field rule is unchanged
```python
# SMA_MACD keeps its Phase-2 validate() (short_window < long_window) verbatim.
def validate(self) -> None:
	if self.short_window >= self.long_window:
		raise ValueError("short_window must be < long_window")
```

## State of the Art

| Old Approach | Current Approach (this phase) | When Changed | Impact |
|--------------|-------------------------------|--------------|--------|
| Inline `ta` compute in `generate_signal`, hand-set `max_window`/`warmup` | Declared recipes in `init()`, auto-derived warmup, pre-eval handles | Phase 3 (this) | Ergonomic win; byte-exact compute preserved |
| `generate_signal(ticker, bars)` | `generate_signal(ticker)` + `self.bars`/`self.now`/handles | Phase 3 | Read-shape decoupled from window arg (future-proof for incremental) |
| MACD computed lazily inside SMA guard (W1-12) | MACD pre-evaluated eagerly every tick | Phase 3 | Value-identical (verified); just eager vs lazy |

**Deprecated/outdated:**
- The Phase-2 `SMAMACDStrategy.init()` no-op (`...`) — now filled with recipe registration.
- Hand-set `max_window = 100` / `warmup = 100` class attrs on `SMAMACDStrategy` — replaced by auto-derivation (the lines disappear per Success Criterion 2). NOTE: the base still declares `max_window: int = 0` / `warmup: int = 0` as engine-facing annotated attrs (they must stay annotated so `to_dict()`/kwargs see them); the base post-init pass overwrites them from `max(min_period)`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | EMA `min_period(w) → w` and RSI `min_period(w) → w` are the correct first-valid conventions (D-07) | Standard Stack / Pattern 2 | LOW — EMA/RSI are additive (oracle-dark, unused by the reference); a wrong min_period only affects their own light unit tests, never the golden. Verify the `ta` first-valid index for EMA/RSI when writing those unit tests. |
| A2 | The e2e suite is **58** leaf assertions/tests but the repo has **46** `scenario.py` files | Open Questions / Success criteria | MEDIUM — the "58/58" gate count predates a count check; confirm what "58" enumerates (parametrized cases vs leaves) before treating a number as the gate. The pass/fail (all green) is unambiguous regardless. |
| A3 | The orchestration seam should be named `evaluate(ticker, window)` and live on the base | Architecture Patterns | LOW — name is Claude's discretion (D-06 discretion); any name works as long as it sets `self.bars`/`self.now`, repopulates handles, dispatches. |
| A4 | `to_dict()` continues to capture `max_window`/`warmup` after they become auto-derived | Runtime State Inventory | LOW — verified by reading `base.py`: `to_dict()` introspects `get_type_hints(type(self))`, and both are annotated base attrs; they remain in the snapshot with their derived values. |

## Open Questions

1. **What exactly does the "e2e 58/58" gate enumerate?**
   - What we know: `find tests/e2e -name scenario.py` returns **46** files. The gate is stated as "58/58" in CONTEXT.md/ROADMAP.
   - What's unclear: whether 58 counts parametrized test cases, multiple assertions per leaf, or includes non-`scenario.py` e2e tests.
   - Recommendation: The planner should run `make test-e2e` (or `poetry run pytest tests/e2e -q`) on the current green tree to capture the exact baseline count, then gate on "same count, all green" rather than a hardcoded 58. The migration touches only the 2 fixture signatures, so the count should not change.

2. **Should the SMA adapter's input slice be done in the adapter or the handle/base?**
   - What we know: byte-exactness requires the slice `bars[start_dt:]` per SMA indicator (Pitfall 1). The adapter has `params` (the window); the base has `now`/`timeframe`.
   - What's unclear: cleanest ownership — adapter (`compute(bars, input, params, now, timeframe)`) vs handle pre-slicing.
   - Recommendation: Put the slice in the adapter's `compute` (it owns the `ta` call AND its input semantics), passing `now`/`timeframe` through `repopulate`. Keeps MACD's no-slice and SMA's slice each self-contained. Oracle-gate it.

3. **Does `min_period(w) → w` for SMA correctly reproduce the warmup with `fillna=True`?**
   - What we know: current SMA uses `fillna=True` (back-fills leading NaN), so `dropna()` drops nothing and the series is full-length; the long SMA(100) over 100 rows yields 100 values (not 1). But `min_period` for warmup is about the *firing gate* (D-15), which is `max(50,100,15)=100` regardless of fillna.
   - What's unclear: whether the additive EMA/RSI (which also need ≥2 valid values for crossover) interact with `fillna` defaults differently.
   - Recommendation: EMA/RSI are oracle-dark; define their adapters with `fillna=False` (no back-fill) so `dropna()` gives genuine first-valid alignment, and test `min_period(w)→w` against the `ta` output directly in their unit tests.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `ta` | SMA/MACD/EMA/RSI compute | ✓ | 0.11.0 | — (mandatory; byte-exact depends on this exact version) |
| `pandas` | rolling/ewm math under `ta` | ✓ | 2.3.3 | — |
| Poetry `.venv` | running tests / mypy | ✓ | in-project | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.
> Note: `ta` 0.11.0 and `pandas` 2.3.3 are the **exact versions the golden was frozen against**. Any future bump to either is a separate, oracle-gated change — not this phase.

## Validation Architecture

> `.planning/config.json` was not found to explicitly disable `nyquist_validation`; section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`testpaths = ["tests"]`, `minversion = "8.0"`), `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/strategy -x` |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IND-01 | BTCUSD oracle byte-exact (134 trades / 46189.87730727451) | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ existing |
| IND-01 | e2e leaves byte-exact (all green) | e2e | `make test-e2e` | ✅ existing |
| IND-01 | SMA_MACD `generate_signal(ticker)` returns BUY on bullish crossover; None on short frame | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -x` | ✅ existing (signature migration needed) |
| IND-01 | `warmup == max_window == 100` after `init()` (auto-derived) | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -k warmup -x` | ❌ Wave 0 (new assertion) |
| IND-01 | `crossover`/`crossunder`/`is_above`/`is_below` boundary semantics (D-02) incl. scalar broadcast | unit | `poetry run pytest tests/unit/strategy/test_primitives.py -x` | ❌ Wave 0 (new file) |
| IND-01 | EMA/RSI adapters produce expected `ta` values + `min_period(w)→w` | unit | `poetry run pytest tests/unit/strategy/test_indicators.py -x` | ❌ Wave 0 (new file; additive D-07) |
| IND-01 | determinism double-run byte-identical | integration | run oracle twice, diff | ✅ via oracle harness (deterministic, no tolerance) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/strategy -x` (fast — sub-second indicator/primitive units)
- **Per wave merge:** `make test-e2e` + `poetry run pytest tests/integration/test_backtest_oracle.py`
- **Phase gate:** `make test` green + `mypy --strict` clean before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_primitives.py` — covers IND-01 crossover/crossunder/is_above/is_below + scalar broadcast (D-02)
- [ ] `tests/unit/strategy/test_indicators.py` — covers EMA/RSI adapters + `min_period` (additive D-07); assert SMA/MACDHist `min_period` (50/100/15)
- [ ] New assertion in `test_strategy.py`: `strategy.warmup == strategy.max_window == 100` post-`init()`
- [ ] Migrate `test_strategy.py` `generate_signal` call sites to the no-`bars` shape (the pure-function tests call `generate_signal` directly — they must go through the `evaluate` seam or set `self.bars`/`self.now` manually)
- Framework install: none — `ta`/`pandas` already present.

## Security Domain

> `security_enforcement` not explicitly set; this is a pure in-process numerical refactor with **no** auth, session, access-control, network, crypto, or untrusted-input surface. The only "input" is committed golden OHLCV CSVs read by the backtest. No applicable ASVS category and no STRIDE threat pattern is introduced by this phase. (The quarantined `SqlHandler` SQL-injection defect is explicitly out of v1.3 scope per REQUIREMENTS.md.)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | no | Inputs are committed golden CSVs + typed kwargs (Phase 2's `UnknownParamError` already guards kwargs); no untrusted input. |
| All others (V2/V3/V4/V6/…) | no | No auth/session/access/crypto surface in a strategy-compute refactor. |

## Migration Blast Radius (verified touch-sites)

| File | Change | Indentation | Oracle-gated? |
|------|--------|-------------|---------------|
| `itrader/strategy_handler/base.py` | Add `self.indicator()`, `IndicatorHandle`, `evaluate()` seam, auto-warmup post-`init()` pass; `generate_signal` abstract signature → `(self, ticker)` | tabs | yes |
| `itrader/strategy_handler/indicators.py` | NEW — SMA/MACDHist/EMA/RSI adapter catalog | tabs | SMA/MACDHist yes; EMA/RSI no |
| `itrader/strategy_handler/primitives.py` | NEW — crossover/crossunder/is_above/is_below | tabs | yes (via SMA_MACD) |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | Migrate `init()` (register recipes), drop `max_window`/`warmup` class attrs, `generate_signal(ticker)` via primitives | tabs | **YES — the gate** |
| `itrader/strategy_handler/strategies/empty_strategy.py` | `generate_signal(ticker)` signature; `bars`→`self.bars` (none used) | tabs | yes (e2e) |
| `itrader/strategy_handler/strategies_handler.py` | `calculate_signals`: replace `strategy.generate_signal(ticker, data)` with `strategy.evaluate(ticker, data)` seam | tabs | yes |
| `itrader/strategy_handler/signal_record.py` | Verify only — `config` snapshot still captures auto-derived `max_window`/`warmup` (it does, via `to_dict`) | 4 spaces | no (verify) |
| `tests/e2e/strategies/scripted_emitter.py` | `generate_signal(ticker)`; `bars.index[-1]`→`self.bars.index[-1]`, `bars.empty`→`self.bars.empty` | **4 spaces** | yes (e2e) |
| `tests/e2e/strategies/single_market_buy.py` | `generate_signal(ticker)`; `len(bars)`→`len(self.bars)` | **4 spaces** | yes (e2e) |
| `tests/unit/strategy/test_strategy.py` | Migrate direct `generate_signal(ticker, bars)` call sites; add warmup assertion | tabs | — |

**Note:** `itrader/strategy_handler/my_strategies/*` subclass `Strategy` but are in the mypy `ignore_errors` override and out-of-scope (REQUIREMENTS.md). They are NOT migrated this phase; if any are imported by a test they would break on the `generate_signal` arity change — verify none are wired into the run/test path (they read `bars` and were never updated for Phase 2's kwargs surface either, suggesting they are already dormant). Flag for the planner to confirm `my_strategies/` is not imported anywhere on the active test path.

## Byte-Exact Verification Protocol (for the plan)

1. **SMA per-indicator slice** — adapter feeds `bars[start_dt:]` for each SMA (start_dt = `now - timeframe*window`); MACD feeds full `bars`. (Pitfall 1.)
2. **Eager MACD == lazy MACD** — verified value-identical; no guard needed beyond the oracle. (Pitfall 2.)
3. **`warmup == max_window == 100`** — assert post-`init()`. (Pitfall 3.)
4. **Run the oracle:** `poetry run pytest tests/integration/test_backtest_oracle.py` — must show 134 trades / `final_equity 46189.87730727451`, EXACT (no tolerance). This is the load-bearing gate (no SMA_MACD unit test guards MACD).
5. **Determinism double-run:** the oracle harness is deterministic (seeded RNG + injected clock); two runs are bit-identical by construction — a second run + diff confirms.
6. **e2e:** `make test-e2e` all green (baseline count — see Open Question 1).
7. **`mypy --strict`:** `poetry run mypy itrader` clean — the typed adapter symbols (D-04) and the handle wrapper must satisfy `--strict`.

## Sources

### Primary (HIGH confidence)
- In-environment empirical verification (`ta` 0.11.0, pandas 2.3.3): SMA slice-vs-full ULP divergence; MACD eager==lazy; fillna tail-invariance; `min_period` arithmetic (`max(50,100,15)==100`); `ta` signatures via `inspect.signature`.
- `itrader/strategy_handler/base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`, `strategies_handler.py`, `signal_record.py`, `price_handler/feed/bar_feed.py` — read directly (the migration surface + the bar-timing contract).
- `tests/integration/test_backtest_oracle.py` — the byte-exact gate mechanism (EXACT, no tolerance).
- `.planning/phases/03-declared-indicator-framework/03-CONTEXT.md` — locked decisions D-01..D-08.
- `.planning/notes/strategy-authoring-surface-999.5c.md` — converged design (§3 model-B, §4 primitives, §"Stateful vs stateless").
- `CLAUDE.md` — indentation, money, mypy, pytest strictness conventions.

### Secondary (MEDIUM confidence)
- e2e leaf count (46 `scenario.py` files) via `find` — vs the stated "58/58" gate (Open Question 1).

### Tertiary (LOW confidence)
- EMA/RSI `min_period(w)→w` conventions (D-07) — asserted from the SMA analogy; verify against `ta` output when writing the additive unit tests (Assumption A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions and call shapes verified in-environment.
- Architecture: HIGH — design is locked (D-01..D-08); patterns map directly to the converged note and existing code.
- Pitfalls: HIGH — Pitfall 1 (the headline) is empirically verified and contradicts a CONTEXT.md claim; Pitfalls 2-6 verified by code read + in-env checks.

**Research date:** 2026-06-12
**Valid until:** 2026-07-12 (stable; tied to `ta` 0.11.0 / pandas 2.3.3 — re-verify Pitfall 1 if either is bumped, since rolling-mean accumulation is version-sensitive)
