# Phase 3: Declared-Indicator Framework - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 3-declared-indicator-framework
**Areas discussed:** SMA_MACD migration depth, Boundary semantics, Indicator handle type, Registration API, Module layout, generate_signal signature, v1 indicator set, warmup/max_window (ewm min_period)

---

## SMA_MACD migration depth

| Option | Description | Selected |
|--------|-------------|----------|
| Partial (handles + auto-warmup, keep literals) | Adopt init()/handles/auto-warmup but keep literal >=/< comparisons; lowest byte-exact risk | |
| Full (use crossover primitive everywhere) | Reference adopts crossover/crossunder + is_above; fully primitive-driven | ✓ |
| You decide | Defer to Claude/oracle | |

**User's choice:** Full primitive-driven (after clarifying that the SMA filter is a level `>=` check, not a crossover).
**Notes:** User raised the question of adding a level-comparison primitive for the SMA "is greater than" case. Resolved by adding `is_above`/`is_below` companions alongside `crossover`/`crossunder`. SMA filter → `is_above`, MACD arms → `crossover`/`crossunder(macd_hist, 0)`.

---

## Boundary semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Inclusive-on-current (match reference) | crossover = a[-2] < b[-2] and a[-1] >= b[-1]; byte-exact by construction | ✓ |
| Textbook-strict, oracle confirms | crossover = a[-2] < b[-2] and a[-1] > b[-1]; relies on macd_hist never == 0.0 | |

**User's choice:** Inclusive-on-current.
**Notes:** Reference operators are all inclusive on the current bar (`>=`/`<=`); textbook-strict would differ only at exact equality but break byte-exact "by construction." Documented as a deliberate departure from textbook-strict. Scalar 2nd arg (`crossover(macd_hist, 0)`) required.

---

## Indicator handle type

| Option | Description | Selected |
|--------|-------------|----------|
| Thin positional-index wrapper | Small class; [-1]/[-2] positional; backend-agnostic seam | ✓ |
| Raw pandas Series | .iloc[-1] reads; no abstraction, not forward-compatible | |

**User's choice:** Thin positional-index wrapper.
**Notes:** User asked whether incremental compute would ever apply given ML/statistical/probabilistic strategies. Clarified: most ML/stat work is windowed-batch (stays stateless); only genuinely-online methods (Kalman/RLS/online-learning) are incremental. Wrapper reframed as a cheap option-preserving seam (not a commitment to incremental); read-sites never change regardless of backend.

---

## Registration API

| Option | Description | Selected |
|--------|-------------|----------|
| Typed adapter symbols | self.indicator(SMA, "close", w); mypy-typed, extensible, decoupled | ✓ |
| String names | self.indicator("sma", ...); stringly-typed, runtime-error on typo | |
| Enum keys | self.indicator(IndicatorType.SMA, ...); extra ceremony, no extra safety | |

**User's choice:** Typed adapter symbols.
**Notes:** Each adapter wraps the existing `ta` call and exposes `min_period(params)` for auto-warmup derivation.

---

## Module layout

| Option | Description | Selected |
|--------|-------------|----------|
| indicators.py + same-module primitives | One import surface | |
| Split: indicators.py + primitives.py | Catalog vs comparisons separated | ✓ |
| You decide | Pick at planning | |

**User's choice:** Split — `indicators.py` (catalog) + sibling primitives module.
**Notes:** Primitives module name Claude's discretion (`primitives.py` recommended; avoid `signals.py` collision).

---

## generate_signal signature

| Option | Description | Selected |
|--------|-------------|----------|
| generate_signal(ticker); self.bars + self.now on base | No bars param; raw window via self.bars, timestamp via self.now | ✓ |
| Keep generate_signal(ticker, bars) | Window as explicit param | |

**User's choice:** `generate_signal(ticker)` with `self.bars` + `self.now` stashed on the base.
**Notes:** User wanted the full raw window available (not only `self.now`). Resolved to expose both on the base. Naming clarified: `self.bars` (not `self.window`) to avoid collision with integer `*_window` attrs. Per-ticker call context.

---

## v1 indicator set

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal: SMA + MACDHist | Only what the reference needs | |
| Seed a small extra set (EMA, RSI) | SMA + MACDHist + EMA + RSI | ✓ |

**User's choice:** Seed EMA + RSI in addition to SMA + MACDHist.
**Notes:** EMA/RSI additive, unused by the reference (cannot touch the golden), need their own unit tests + min_period conventions.

---

## warmup / max_window (ewm min_period)

| Option | Description | Selected |
|--------|-------------|----------|
| First-valid-value only; compute over full window | min_period = w (MACD = slow+signal); full-window compute; byte-exact | ✓ |
| Convergence-buffered min_period | Bake unstable-period buffer into ewm min_period; risks breaking the golden | |
| You decide | Defer formulas to planner | |

**User's choice:** First-valid-value only + full-window compute.
**Notes:** User asked how the window's impact on ewm indicators (EMA/RSI) is usually managed. Explained the min_period-vs-memory-depth distinction and the "unstable period" concept (TA-Lib `TA_SetUnstablePeriod`). User chose option 1 and asked that the rejected option-2 (ewm convergence-buffer + max_window override) be recorded as a TODO for proper later implementation — captured in CONTEXT.md Deferred Ideas.

---

## Claude's Discretion

- Handle wrapper exact interface (`__getitem__`/`__len__` vs richer).
- Handle binding mechanism (registered handle repopulated per tick — backtesting.py `self.I()` pattern).
- Base orchestration entry point name/shape.
- Input spec = column-name string ("close"); single-column for v1.
- Primitives module name (`primitives.py` recommended); exact per-indicator min_period formulas — oracle-gated.

## Deferred Ideas

- **[TODO — owner-requested]** ewm convergence-buffer / "unstable period" mechanism + overridable `max_window` fetch-width (rejected D-08 option-2) → future phase.
- Stateful/incremental indicator backends (W1-05 / IND-02) → future phase.
- Multi-column indicators (ATR/Stochastic, HLC input) → when first one lands.
- Indicator-based SL/TP consuming the strategy-decoupled recipe → future phase.
