# Phase 3: Declared-Indicator Framework - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 10 (2 NEW, 6 modified, 2 verify-only)
**Analogs found:** 10 / 10 (this is a brownfield refactor — every file has a strong in-repo analog)

> **BYTE-EXACT PHASE.** Where an analog's *generic shape* would change a computed
> value, this map flags it with a **[BYTE-EXACT]** marker and tells the planner to
> copy the *exact current input semantics*, not the analog's clean shape. The single
> load-bearing landmine is the per-indicator SMA input slice (RESEARCH Pitfall 1) —
> see `indicators.py` and `base.py` below.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/strategy_handler/indicators.py` (NEW) | adapter catalog | transform (compute) | `itrader/execution_handler/fee_model/` (`base.py` + `percent_fee_model.py`) + `core/sizing.py` (singleton-instance + union catalog) | role-match (pluggable typed-adapter catalog) |
| `itrader/strategy_handler/primitives.py` (NEW) | utility (free functions) | transform (pure) | `itrader/core/sizing.py` (module of pure validators/free functions) | role-match (free-function module) |
| `itrader/strategy_handler/base.py` (`IndicatorHandle`) | value-object / wrapper | transform (positional read) | `itrader/core/bar.py` (frozen value object, `__getitem__`-style accessor) | role-match (thin wrapper) |
| `itrader/strategy_handler/base.py` (`indicator()` + `evaluate()` + auto-warmup) | base ABC orchestration | request-response (per-tick) | **self-analog** — `base.py` Phase-2 `init()`/`_apply_params`/`reconfigure`/`to_dict` seam | exact (extend the same file) |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | strategy (concrete) | request-response | **self** (before-state) + `tests/e2e/strategies/scripted_emitter.py` (after-state authoring shape) | exact (the migration target) |
| `itrader/strategy_handler/strategies/empty_strategy.py` | strategy (concrete) | request-response | **self** — signature-only migration | exact |
| `itrader/strategy_handler/strategies_handler.py` | handler (thin) | request-response (cross-domain seam) | **self** — `calculate_signals` call-site swap | exact |
| `itrader/strategy_handler/signal_record.py` | model (verify-only) | — | **self** — `to_dict()` snapshot already captures derived attrs | exact (no edit, verify) |
| `tests/e2e/strategies/scripted_emitter.py` | test fixture (strategy) | request-response | **self** — signature-only migration (4 spaces) | exact |
| `tests/e2e/strategies/single_market_buy.py` | test fixture (strategy) | request-response | **self** — signature-only migration (4 spaces) | exact |

---

## Pattern Assignments

### `itrader/strategy_handler/indicators.py` (NEW — adapter catalog, TABS)

**Analog 1 (catalog/ABC shape):** `itrader/execution_handler/fee_model/base.py` + `percent_fee_model.py`
**Analog 2 (singleton-instance symbols + union alias):** `itrader/core/sizing.py` lines 84-154

The fee_model layer is the established **pluggable typed-model catalog** in this repo: an
`ABC` base declaring `@abstractmethod calculate_fee(...)` plus a concrete pattern with a
module docstring citing decision tags. `core/sizing.py` is the established **typed-symbol
catalog with a union alias** (`FractionOfCash | FixedQuantity | RiskPercent` →
`SizingPolicy`), which is the closest analog for D-04's "real importable symbols, no
stringly-typed name." RESEARCH Pattern 2 recommends the **singleton-instance-of-a-class**
form (`SMA = _SMA()`) — cleaner under `--strict` than the fee_model's instantiated-class
form, because adapters are stateless.

**Module docstring + decision-tag style** — copy from `core/sizing.py` lines 1-38:
```python
"""
Typed indicator adapter catalog for the iTrader strategy engine (IND-01, D-04/D-07/D-08).

- **D-04 — typed adapter symbols.** SMA / MACDHist / EMA / RSI are real importable
  symbols (mypy-visible), each wrapping its exact `ta` call AND a `min_period(params)`.
- **D-08 — first-valid-period min_period only** (SMA/EMA/RSI -> w; MACD -> slow+signal),
  NOT a convergence buffer. ...
- **Pitfall 1 [BYTE-EXACT] — per-indicator input slice.** ...
"""
```
This matches the heavy decision-anchored docstring convention (`core/sizing.py`, `core/bar.py`).

**Abstract/Protocol surface** — model on `fee_model/base.py` lines 20-71 (the ABC +
`@abstractmethod`). RESEARCH Pattern 2 prefers a `Protocol` (`IndicatorAdapter`) the
handle types against, OR a plain ABC. Either is fine; the surface is:
```python
class _SMA:
	def compute(self, bars, input_col, params, now, timeframe) -> "pd.Series": ...
	def min_period(self, params) -> int: ...
SMA = _SMA()
```

**[BYTE-EXACT] Core compute pattern — copy the EXACT current `ta` call + slice from
`SMA_MACD_strategy.py` lines 59-65, 75-76.** This is the load-bearing excerpt — the
adapter must reproduce it verbatim, NOT a clean uniform-window version:
```python
# SMA (sliced input — RESEARCH Pitfall 1; the SMA tail value is NOT slice-independent):
last_time = bars.index[-1]                                # -> base passes `now`
start_dt = last_time - self.timeframe * self.short_window # -> now - timeframe * window
short_sma = trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()
#                              ^^^^^^^^^^^^^^^^^^^^^^^^                     ^^^^ fillna=True (3rd positional)

# MACD histogram (FULL window — NO slice; keep it that way):
MACDhist = trend.MACD(bars.close, window_fast=self.fast_window, window_slow=self.slow_window,
                      window_sign=self.signal_window, fillna=False).macd_diff().dropna()
```
So the SMA adapter's `compute` MUST do `bars[start_dt:][input_col]` with
`start_dt = now - timeframe * window` and `fillna=True`; the MACDHist adapter MUST use
the full `bars[input_col]` with `fillna=False`. Do not "tidy" either into a uniform window.

**`min_period` formulas (D-08):** SMA → `window`; MACD → `slow + signal` (=15 for 6/12/3);
EMA → `window`; RSI → `window`. For the reference `max(50, 100, 15) == 100` (Pitfall 3 — assert it).

**EMA/RSI (additive, oracle-dark, D-07):** `trend.EMAIndicator(close, window, fillna=False).ema_indicator()`
and `momentum.RSIIndicator(close, window, fillna=False).rsi()` — use `fillna=False` so `dropna()`
gives genuine first-valid alignment (RESEARCH Open Question 3). These need their own unit tests.

---

### `itrader/strategy_handler/primitives.py` (NEW — free-function module, TABS)

**Analog:** `itrader/core/sizing.py` lines 59-81 (module-level `_`-prefixed free functions
with one-line decision-tag docstrings, `__all__` export, module-private `_ZERO` constant).

`core/sizing.py` is the canonical **pure-free-function-module** convention in this repo:
module docstring, `__all__` list, leading-underscore private helpers (`_require_positive`,
`_require_unit_interval`), single-line docstrings citing the decision tag.

**[BYTE-EXACT] Boundary semantics — copy D-02 EXACTLY** (these reproduce
`SMA_MACD_strategy.py` lines 70, 77, 80 operator-for-operator):
```python
def _at(series_or_scalar, idx: int) -> float:
	# D-02 scalar broadcast: b[-1] == b[-2] == scalar (crossover(macd_hist, 0)).
	if isinstance(series_or_scalar, (int, float)):
		return float(series_or_scalar)
	return float(series_or_scalar[idx])

def is_above(a, b) -> bool:    return _at(a, -1) >= _at(b, -1)   # short_sma[-1] >= long_sma[-1]
def is_below(a, b) -> bool:    return _at(a, -1) <= _at(b, -1)
def crossover(a, b) -> bool:   return _at(a, -2) <  _at(b, -2) and _at(a, -1) >= _at(b, -1)
def crossunder(a, b) -> bool:  return _at(a, -2) >  _at(b, -2) and _at(a, -1) <= _at(b, -1)
```
Maps to today's operators (RESEARCH lines 233-236): `MACDhist[-1] >= 0 and MACDhist[-2] < 0`
→ `crossover(macd_hist, 0)`; `<= 0 / > 0` → `crossunder`. The inclusive `>=` on current bar
and strict `<` on previous is the byte-exact lever — do NOT switch to textbook-strict `>`.

**Module name:** `primitives.py` (avoid `signals.py` — collides with `SignalEvent`/`SignalIntent`).

---

### `itrader/strategy_handler/base.py` — `IndicatorHandle` (thin wrapper, TABS)

**Analog:** `itrader/core/bar.py` (frozen value object) — for the construction +
positional-accessor + typing convention. The handle is NOT frozen (it is re-populated
per tick), but the **thin-wrapper-over-data** shape and docstring style transfer.

**Surface (RESEARCH Pattern 1, lines 155-172) — `__getitem__`/`__len__`/`min_period`:**
```python
class IndicatorHandle:
	"""Thin positional-index wrapper over a recomputed pandas Series (D-03)."""
	def __init__(self, adapter, input_col, params):
		self._adapter = adapter; self._input = input_col; self._params = params
		self._values: pd.Series | None = None
	def repopulate(self, bars, now, timeframe) -> None:
		self._values = self._adapter.compute(bars, self._input, self._params, now, timeframe)
	def __getitem__(self, idx: int) -> float:
		assert self._values is not None
		return float(self._values.iloc[idx])      # [-1], [-2] positional
	def __len__(self) -> int:
		return 0 if self._values is None else len(self._values)
	def min_period(self) -> int:
		return self._adapter.min_period(self._params)
```
`__getitem__` returning `float(... .iloc[idx])` mirrors `Bar.from_row`'s edge-cast discipline
(value-domain conversion at the read edge). Keep the surface minimal (`__getitem__`/`__len__`)
unless `mypy --strict` forces more (Claude's Discretion — gated by oracle).

---

### `itrader/strategy_handler/base.py` — `indicator()` + `evaluate()` seam + auto-warmup (SELF-ANALOG, TABS)

**Analog:** the SAME file's Phase-2 lifecycle seam — `base.py` lines 72-84 (`__init__` calls
`validate()` then `init()`), `_apply_params` (86-156), `to_dict` (194-248), and the
`@abstractmethod generate_signal` (259-269).

**Where each new piece lands (self-analog map):**

- **`self.indicator(...)` registration** — called from the subclass's `init()` (already the
  idempotent hook at `base.py` line 84 / 167-173). Stores a recipe, returns an empty
  `IndicatorHandle`, appends it to a base-owned `self._handles: list[IndicatorHandle]`.
  Pattern matches backtesting.py `self.I()`. `init()` is ALREADY re-runnable (reconfigure
  calls it, line 192) — so a fresh `init()` must reset `self._handles` first (idempotency,
  D-10: "calling it twice leaves identical state").

- **Auto-warmup post-`init()` pass** — after `self.init()` in `__init__` (and in
  `reconfigure`), add: `self.warmup = self.max_window = max((h.min_period() for h in self._handles), default=0)`.
  This OVERWRITES the base class-attr annotations `max_window: int = 0` / `warmup: int = 0`
  (lines 68-69) — **keep those annotations** (RESEARCH lines 366): `to_dict()` introspects
  `get_type_hints(type(self))` (lines 205-216) and only annotated names survive into the
  snapshot. **[BYTE-EXACT] Pitfall 3:** the reference must end at `warmup == max_window == 100`.

- **`evaluate(ticker, window)` orchestration seam** (name Claude's discretion) — the NEW
  base method the handler calls instead of `generate_signal(ticker, bars)`. RESEARCH lines
  114-120 / Pitfalls 4 & 6:
```python
def evaluate(self, ticker: str, window: pd.DataFrame) -> SignalIntent | None:
	self.bars = window
	self.now = window.index[-1]                 # replaces today's last_time = bars.index[-1]
	for handle in self._handles:                # empty list for indicator-free fixtures -> no-op
		handle.repopulate(self.bars, self.now, self.timeframe)
	return self.generate_signal(ticker)
```
  **[BYTE-EXACT] Pitfall 4:** `self.now` MUST be `window.index[-1]` (the same anchor today's
  `last_time` uses) so the SMA `start_dt` arithmetic is unchanged. `self.timeframe` is already
  the resolved `timedelta` (lines 133-156) — exactly what `start_dt = now - timeframe * window`
  expects. **Pitfall 6:** `evaluate` sets `self.bars`/`self.now` for EVERY strategy (even
  zero-handle fixtures), or `EmptyStrategy`/e2e fixtures break with `AttributeError`.

- **`generate_signal` abstract signature** (lines 259-269) — drop `bars`: `generate_signal(self, ticker: str) -> SignalIntent | None`.

- **Naming:** `self.bars` (NOT `self.window` — collides with `*_window`/`warmup` int attrs, D-06).

---

### `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` (the byte-exact GATE, TABS)

**Before-state analog:** itself, lines 48-95 (inline compute).
**After-state authoring analog:** `tests/e2e/strategies/scripted_emitter.py` (the post-Phase-2
authoring shape) + RESEARCH lines 330-346 (the migrated target).

**Migrated shape — copy from RESEARCH Code Examples (lines 330-346):**
```python
from itrader.strategy_handler.indicators import SMA, MACDHist
from itrader.strategy_handler.primitives import crossover, crossunder, is_above

def init(self):
	self.short_sma = self.indicator(SMA, "close", self.short_window)
	self.long_sma  = self.indicator(SMA, "close", self.long_window)
	self.macd_hist = self.indicator(MACDHist, "close", self.fast_window,
	                                self.slow_window, self.signal_window)
	# NO hand-set max_window/warmup — base derives them post-init (== 100).

def generate_signal(self, ticker):            # no bars param (D-06)
	if is_above(self.short_sma, self.long_sma):
		if crossover(self.macd_hist, 0):  return self.buy(ticker)
		if crossunder(self.macd_hist, 0): return self.sell(ticker)
	return None
```
**DELETE** the hand-set `max_window: int = 100` / `warmup: int = 100` class attrs (current
lines 39-40) — base auto-derives them (Success Criterion 2). **KEEP** `validate()` verbatim
(lines 42-46, `short_window >= long_window`) and the oracle-visible class-attr defaults
(`short_window=50`, `long_window=100`, `fast=6`, `slow=12`, `signal=3`, lines 28-36).

**[BYTE-EXACT]** The eager-vs-lazy MACD reorder (today MACD is computed lazily inside the SMA
guard, lines 71-76; model-B computes it eagerly every tick) is **value-identical** (RESEARCH
Pitfall 2 — verified). The W1-12 lazy optimization is intentionally replaced. Proven by the
oracle ONLY (no SMA_MACD unit test guards the MACD value).

---

### `itrader/strategy_handler/strategies/empty_strategy.py` (signature-only, TABS)

**Analog:** itself (lines 22-23). Migrate `generate_signal(self, ticker: str, bars: pd.DataFrame)`
→ `generate_signal(self, ticker: str) -> SignalIntent | None`. Body is `return None` — no `bars`
read, so nothing else changes. Registers no indicators (empty `self._handles`); `evaluate`'s
no-op repopulate loop covers it (Pitfall 6).

---

### `itrader/strategy_handler/strategies_handler.py` (cross-domain seam, TABS)

**Analog:** itself, `calculate_signals` line 105.

**The single call-site swap** — line 105:
```python
# BEFORE:
intent = strategy.generate_signal(ticker, data)
# AFTER (D-06 orchestration seam):
intent = strategy.evaluate(ticker, data)
```
**UNCHANGED** (do not touch): the D-15 warmup short-circuit (lines 103-104,
`if len(data) < strategy.warmup`) — now reads the **auto-derived** `strategy.warmup` (still
100 for the reference). The `feed.window(..., strategy.max_window, ...)` fetch (line 93) —
now reads the auto-derived `max_window` (still 100). The `to_dict()` snapshot (line 126) and
the per-portfolio fan-out (lines 136-166) are fully downstream and unchanged.

---

### `itrader/strategy_handler/signal_record.py` (VERIFY-ONLY, 4 spaces)

**Analog:** itself. NO edit. Verify the `config` snapshot (set from `strategy.to_dict()` at
`strategies_handler.py` line 126) still captures `max_window`/`warmup` — it does: `to_dict()`
(`base.py` lines 205-216) iterates `get_type_hints(type(self))`, and both remain **annotated**
base attrs (lines 68-69) carrying their now-derived values (RESEARCH Assumption A4). No data
migration.

---

### `tests/e2e/strategies/scripted_emitter.py` (signature-only, **4 SPACES**)

**Analog:** itself, lines 117-136. Migrate signature → `generate_signal(self, ticker: str)`.
Replace `bars` reads with `self.bars`:
```python
# BEFORE (line 118-127):
if bars.empty: return None
decision_date = bars.index[-1].tz_convert("UTC").strftime("%Y-%m-%d")
# AFTER:
if self.bars.empty: return None
decision_date = self.bars.index[-1].tz_convert("UTC").strftime("%Y-%m-%d")
```
Registers no indicators. **[INDENTATION] 4 spaces** (declared in its docstring, line 39) —
do NOT use tabs here. (Pitfall 5.)

---

### `tests/e2e/strategies/single_market_buy.py` (signature-only, **4 SPACES**)

**Analog:** itself, lines 77-82. Migrate signature → `generate_signal(self, ticker: str)`.
Replace `len(bars)` → `len(self.bars)`:
```python
# AFTER:
if len(self.bars) == self.fire_on_bar: return self.buy(ticker)
if len(self.bars) == self.exit_on_bar: return self.sell(ticker)
return None
```
**[INDENTATION] 4 spaces.** (Pitfall 5.)

---

## Shared Patterns

### Module docstring + decision-tag convention
**Source:** `itrader/core/sizing.py` lines 1-38, `itrader/core/bar.py` lines 1-21
**Apply to:** Both NEW modules (`indicators.py`, `primitives.py`) and all docstring additions
A triple-quoted module docstring opening with a one-line purpose, then a bulleted list of
load-bearing decision tags (`D-04`, `D-08`, `Pitfall 1`). Heavy, decision-anchored — these tags
are references to planning artifacts, not noise. Preserve the style.

### `[BYTE-EXACT]` per-indicator input slice (THE landmine)
**Source:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` lines 59-76
**Apply to:** `indicators.py` (SMA adapter) + `base.py` (`evaluate`/`repopulate` passing `now`+`timeframe`)
SMA computes over `bars[start_dt:]` (sliced, `start_dt = now - timeframe*window`, `fillna=True`);
MACD over the full `bars` (`fillna=False`). A uniform full-window SMA breaks the oracle by 1 ULP
on the short SMA (RESEARCH Pitfall 1 — empirically verified; CONTRADICTS the CONTEXT.md claim
"the SMA tail value is slice-independent"). The slice ownership belongs in the adapter's `compute`
(RESEARCH Open Question 2).

### Indentation (tabs vs 4 spaces) — match the file
**Source:** CLAUDE.md convention + RESEARCH Pitfall 5 / Blast Radius table
**Apply to:** all touched files
- **TABS:** `base.py`, `indicators.py` (NEW), `primitives.py` (NEW), `SMA_MACD_strategy.py`,
  `empty_strategy.py`, `strategies_handler.py`
- **4 SPACES:** `signal_record.py` (verify-only), `tests/e2e/strategies/scripted_emitter.py`,
  `tests/e2e/strategies/single_market_buy.py`
Never normalize — a mixed-indentation diff in a tab file breaks it.

### `mypy --strict` typing idioms
**Source:** `core/sizing.py` (union alias `SizingPolicy = A | B | C`), `base.py` (`get_type_hints`,
`cast`, modern union `X | None`)
**Apply to:** the typed adapter symbols (D-04) and the handle wrapper. RESEARCH Pattern 2:
prefer a singleton instance of a class (`SMA = _SMA()`) and optionally an `IndicatorAdapter`
`Protocol` for typing `self._handles`. Avoid stringly-typed dict lookup and metaclass registration.

### `float(...)` only at the read edge
**Source:** `core/bar.py` (`Decimal(str(x))` at construction), the handle `__getitem__`
The indicator values are pandas `float64` (the `ta` compute domain), NOT money — so `float(...)`
at the handle read edge is correct here (this is NOT the Decimal-money path; indicators are
look-ahead-safe float series the primitives compare). Do not route indicator values through `to_money`.

---

## No Analog Found

None. Every file has a strong in-repo analog (this is a brownfield refactor with a converged,
locked design). The two NEW modules (`indicators.py`, `primitives.py`) are first-party and modeled
on the established fee_model catalog + `core/sizing.py` free-function-module conventions.

---

## Metadata

**Analog search scope:** `itrader/strategy_handler/`, `itrader/execution_handler/fee_model/`,
`itrader/execution_handler/slippage_model/`, `itrader/core/` (`sizing.py`, `bar.py`),
`itrader/core/enums/order.py`, `tests/e2e/strategies/`
**Files read (analogs):** `base.py`, `SMA_MACD_strategy.py`, `empty_strategy.py`,
`strategies_handler.py`, `signal_record.py`, `core/sizing.py`, `core/bar.py`,
`fee_model/base.py`, `fee_model/percent_fee_model.py`, `core/enums/order.py`,
`tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/strategies/single_market_buy.py`
**Pattern extraction date:** 2026-06-12
```