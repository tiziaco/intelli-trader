# Stateful Indicators + Shared Bar Cache — Design Spec

**Date:** 2026-06-24
**Status:** design approved (brainstorm), pending GSD plan-phase
**Scope:** strategy indicator computation model + the feed/data layer it reads from
**Re-baseline:** YES (numerical oracle may move, cross-validated) — confirmed by user

---

## 1. Problem

Today every indicator recomputes its **entire** `ta` pandas Series **every tick** over a
per-tick-sliced window (`Strategy.evaluate` → `IndicatorHandle.repopulate` →
`adapter.compute`). That is O(N) per tick → O(N²) per backtest, and it constructs/`dropna`s
fresh pandas/`ta` objects per tick per indicator.

Separately, the W2 Scalene profile attributes ~26% of program CPU to `bar_feed.window()`:
- `searchsorted` 13.2% — **already banked** by the committed monotonic cursor (`00c5480`).
- `iloc` slice 7.9% + `start` calc 5.3% — residual, exists only because a trailing-window
  DataFrame is materialized per tick, per consumer.

## 2. Goals

1. Replace per-tick full-series recompute with **stateful, incremental indicators** (O(1)/tick).
2. Make the indicator model **live-safe and backtest/live-parity** (one code path) — the
   Nautilus/LEAN family, idiomatic to this single-`global_queue` event engine.
3. **Eliminate the residual ~13% per-tick window slice** by removing the per-tick
   master-frame window for all strategies (handle-only strategies pushed the latest bar;
   the pair strategy migrated onto the shared cache).
4. Open a clean home for **statistical / ML indicators** (rolling cointegration, Kalman,
   Hawkes) without re-auditing look-ahead each time.

**Non-goal (this phase):** a parameter-optimization module, a screener subsystem, concrete
Kalman/Hawkes adapters, and a first-class `Instrument` abstraction. The design *accommodates*
all four without rework; none is built here.

## 3. Framework grounding (why these choices)

- **Stateful incremental indicators** — Nautilus (`update_raw()` + internal state, Cython),
  LEAN (`IndicatorBase.Update()`, `RollingWindow`, `SetWarmUp`). Chosen for backtest/live
  parity and structural look-ahead safety. The vectorized-precompute alternative
  (freqtrade `populate_indicators`, backtesting.py `self.I()`, vectorbt) fits *batch* engines,
  not event-driven ones, and ships a look-ahead hazard class (freqtrade's `lookahead-analysis`).
- **Shared raw-bar cache, private derived state** — Nautilus `Cache` (recent bars per
  instrument, read by strategies/indicators/actors), LEAN `SecurityCache` + one feed
  auto-updating all registered indicators, zipline `DataPortal.history()`. Raw history is
  shared; indicators hold only derived state (running EMA value, Kalman state, fitted β).
  This is what prevents duplication when a symbol is in both a strategy and a screener.
  NOTE: Nautilus colocates `Instrument`s and bars in one `Cache`; iTrader deliberately keeps
  reference data as a separate derived map (`derive_instruments`), so this cache holds bars
  ONLY (see §4.1). Colocation is a possible future unification, not this phase.
- **Window-needing indicators stay stateful** via an incrementally-maintained bounded buffer
  (LEAN `RollingWindow`, Nautilus bounded deques / Cache depth), not a master-frame re-slice.
  Refitting indicators split `estimate(window)` (periodic cadence) from `propagate(bar)` (O(1)/tick).

## 4. Architecture

### 4.1 Shared bar cache + feed rename
- Abstract, consumer-facing **`BarFeed`** (promote `feed/base.py`) owns a **shared recent-bars
  read API**: one trailing view per `(symbol, timeframe)` per tick, shared by ALL consumers.
  - Backtest backing: **`BacktestBarFeed`** (today's master-frame view + committed monotonic cursor).
  - Live backing: **`LiveBarFeed`** (ring buffer) — interface-shaped now, not implemented.
- Cache capacity per `(symbol, timeframe)` = `max(lookback)` over **all registered consumers**.
  Derive it with a pure wiring-time function that **mirrors `universe/instruments.py::derive_instruments`**:
  compose strategy `max_window` (and future screener lookbacks) over
  `derive_membership(strategies, screener_tickers)`. Screener-extensibility is therefore the
  same already-solved pattern, not a new mechanism — do NOT hardcode strategies-only.
  **(Multi-timeframe refinement — §10.G: under the register-at-base model the base-source entry is
  sized to the *coarsest* consumer in base-bar-equivalents, each derived `(symbol, timeframe)` keeps
  its own depth, and `base_timeframe` must be ≤ `min(timeframe)` over all consumers.)**
- Cache entry is `{symbol → (recent_bars, cursor)}` — **bars only**. Per-symbol reference data
  (`Instrument`) is NOT held here; it already lives in the derived `dict[str, Instrument]` from
  `derive_instruments`, injected to its consumers (money/order/execution). See §6.
- Preserve the 7-rule bar-timing contract and the D-08/D-10 cursor byte-for-byte. This plan
  is structural and should stay byte-exact (no numeric change here).

### 4.2 Stateful indicators (derived-state only)
`IndicatorHandle` + adapters convert from per-tick `ta`-Series recompute to stateful
`update(...)` + O(1) positional read. **The scalar adapters DROP `ta` on the runtime path** — `ta`
has no incremental/streaming API (Series-in/Series-out only), so each indicator becomes a
hand-written O(1) recurrence (SMA running-sum; EMA `y += α(x−y)`, `α = 2/(n+1)`, `adjust=False`;
MACD = two EMAs + a signal EMA; RSI = Wilder smoothing). `ta`/pandas are **retained only as a
test-time oracle** (feed the series bar-by-bar, assert convergence to the batch output within
tolerance after warmup) — never called per tick. Dropping `ta` is the direct *cause* of the Plan B
re-baseline (float-summation order + EMA seeding, §10.B). The `handle[-1]`/`handle[-2]` read surface
and the `crossover`/`is_above` primitives and `generate_signal` are **unchanged**. Three internal
shapes:

1. **Scalar-recursive** — SMA, EMA, MACD, RSI, Kalman *filter*, Hawkes intensity. O(1)
   `update(latest_bar)`. EMA/MACD/RSI hold O(1) *scalar* state; SMA additionally needs the value
   *leaving* the window — read it as a single indexed position from the shared cache (depth
   guaranteed ≥ window by §4.1/§10.G), NOT a private ring nor a window scan, so SMA stays
   derived-state-only too.
2. **Bounded-window** — rolling regression/cointegration/windowed statistic. Reads the shared
   cache window; holds only derived output.
3. **Refitting** — Kalman/Hawkes MLE. `estimate(window)` on a declared cadence + O(1)
   `propagate(bar)` per tick; holds fitted params + state.

All three: **causal by construction** (state absorbs only past bars). An adapter declares
`causal`; the decision path **rejects** non-causal adapters (smoothers, centered windows).
`reset()` clears state between optimizer runs (the one discipline a future sweep must honor).

**Three distinct buffers — do not conflate (§10.H):** (i) the **shared raw-bar cache** — input
bars, capacity = max lookback (§4.1/§10.G); (ii) **indicator internal state** — scalar for
EMA/MACD/RSI, the running sum for SMA (its evicting value sourced from (i)); (iii) the **handle
output-history buffer** — *computed* indicator values for `handle[-k]` reads. Buffer (iii) defaults
to **depth 2** (the floor `crossover` needs; LEAN's default `RollingWindow`) but is a **declared
per-handle depth**, so a strategy that compares an indicator to its own deeper past (e.g. "3 rising
MACD bars", indicator-vs-price divergence over N) declares the depth it reads. Default small,
bounded, never unbounded — "retain more" for raw history lives in (i), not (iii).

### 4.3 Cut the per-tick window
Rework `strategies_handler.calculate_signals` → `Strategy.evaluate` so a **handle-only**
strategy is pushed the latest bar, not a sliced window — no DataFrame materialized.
`self.bars` as a fresh per-tick master-frame slice is removed; where a strategy still needs
frame access it is a **shared-cache read**, not a new slice.

## 5. Three plans (for GSD plan-phase to expand)

**Plan A — Shared recent-bars cache + `BarFeed` rename (data layer).**
Promote `BarFeed` base; rename `BacktestBarFeed` as the view backing; add the shared
recent-bars read API + consumer registration + capacity derivation (pure wiring-time function
mirroring `derive_instruments`, screener-extensible). Cache holds bars only — instruments stay
in the existing `derive_instruments` map. Stay byte-exact (no numeric change). Preserve the
7-rule contract + cursor.

**Plan B — Stateful indicators + oracle re-baseline.**
Convert `IndicatorHandle`/adapters to stateful `update` + O(1) read. Implement scalar-recursive
(SMA/EMA/MACD/RSI) as **hand-written O(1) recurrences — drop `ta` on the runtime path; retain
`ta`/pandas as a test-time oracle only** (§4.2/§10.H) — plus the `causal` flag + decision-path
guard; the bounded-window / `estimate`-`propagate` interface with one exemplar. Add the declared
per-handle output-buffer depth (default 2, §10.H). Drop the SMA byte-exact `bars[start_dt:]`
slice; **re-baseline the SMA_MACD oracle** with backtesting.py / backtrader cross-validation.

**Plan C — Pair migration + drop per-tick `self.bars`.**
Migrate `eth_btc_pair_strategy` β/z to a window-needing indicator reading the shared cache.
Rework the `strategies_handler → evaluate` seam to push the latest bar to handle-only
strategies; remove the per-tick master-frame slice across all strategies. Re-validate.

**Dependency order:** A → B → C (data layer → indicators on it → consumers cut over).

## 6. Deferred (accommodated, not built)
- **Optimizer cache / parallel-run harness** — derived state `reset()`s per run; throughput
  comes from parallel full runs (Nautilus/LEAN), not vectorization (the event-driven
  order/portfolio layer can't be vectorized across params). The cache key shape is sweep-ready.
- **Screener subsystem** — deferred; the cache consumer-registration + capacity derivation
  must accept screener lookbacks when they arrive.
- **Concrete Kalman / Hawkes adapters** — the §4.2 interface admits them; no impl now.

> NOTE: `Instrument` is **already first-class** (`core/instrument.py` +
> `universe/instruments.py::derive_instruments`, the `derive_membership` sibling;
> `_INSTRUMENT_SCALES` already removed, `quantize(value, instrument, kind)` reads precision off
> the handed-in `Instrument`). It is NOT a deferred item and is NOT moved into the feed.
> A possible future unification (one Nautilus-style `Cache` over both bars and instruments) is
> out of scope.

## 7. Perf expectation (honest)
- `searchsorted` 13.2% — already banked (committed cursor).
- Residual `iloc`+`start` ~13% — **banked by this phase** (Plan C removes the per-tick
  master-frame slice across all strategies).
- Indicator recompute (part of the ~9% `base.py`) — reduced by Plan B (O(N²) → O(N)/O(1)).
- Net: between the committed cursor and this phase, the full ~26% window overhead is addressed,
  plus the indicator recompute. Primary value is also **architecture + live parity + ML-readiness**;
  the optimizer payoff is realized later, on this design.

## 8. Risks
- **Look-ahead** — Plans A/C touch the look-ahead-critical seam; the 7-rule contract and
  causality guard are the protections. Re-validate determinism + byte-exactness per plan.
- **Oracle re-baseline (Plan B)** — must be cross-validated against backtesting.py/backtrader,
  not silently changed; the new reference is frozen and regression-locked.
- **Scope** — substantial (data layer + indicators + strategy migration). Mitigated by the
  A→B→C split.

## 9. Pre-planning review agenda (run in a fresh session before GSD plan-phase)

Bounded verification pass — verify + find adjacent wins, do NOT redesign. Output: an addendum
to this spec (gaps found, adjacent optimizations, framework deltas), then hand to GSD.

**A. Per-tick consumer trace (completeness).** Enumerate every consumer of `feed.window()` /
bars / indicator values on the TIME→BAR route and confirm the design covers or relieves each:
- `strategies_handler` single + pair (known) — confirm these are the ONLY per-tick `window()`
  consumers, so Plan C truly removes the slice.
- `execution_handler.on_market_data` — does it read bars per tick? what shape?
- `portfolio_handler.update_portfolios_market_value` — per-tick mark-to-market; where does the
  price come from, and is it O(positions)/tick?
- `screeners_handler.screen_markets` (deferred) — will it slice windows? confirm it routes
  through the shared cache, not a parallel path.
- `reporting` / `signal_record` — does anything downstream read indicator series (e.g. plots)?
  If so, the stateful read surface must still serve it.

**B. Warmup/gating semantics under stateful.** Today `warmup`/`max_window` derive from indicator
`min_period` and drive BOTH the feed fetch width AND the handler short-circuit. Re-derive how
gating works when indicators are stateful and the per-tick window is gone — warmup becomes
"indicator readiness" (Nautilus `initialized` / LEAN `IsReady`), not window width. Nail this
before planning; it crosses all three plans.

**C. Adjacent optimizations (out of indicator scope, but next-biggest).**
- Per-bar logging ~22% of W2 (the largest non-indicator frame) — worth its own look.
- Per-tick portfolio mark-to-market cost; shared last-price read.
- Multi-timeframe / multi-symbol fan-out cost on the shared cache.

**D. Framework comparison (targeted, not a survey).** Nautilus / LEAN / zipline / vectorbt —
the data-layer → indicator → strategy → screener pipeline only: how they share recent bars
across strategy+screener, indicator registration + warmup, live/backtest parity, multi-timeframe,
and the optimizer loop. Capture only deltas that would change this design.

**Tooling:** an `Explore`/code-explorer fan-out for A–C (trace the impacted subsystems), a
targeted research pass for D. Or run `/gsd:discuss-phase` for this phase, which is built for
exactly this pre-planning context gathering.

---

## 10. Pre-planning review addendum (2026-06-24)

Result of the §9 agenda — a bounded verify + find-adjacent-wins pass against the live code
(three code-traces + a framework research pass; all claims below carry `file:line`). **Not a
redesign.** Hand this to GSD plan-phase alongside §1–§9.

### 10.0 Verdict

The design is **sound and idiomatic** — Nautilus and LEAN independently validate all five core
seams (stateful incremental indicators, shared raw-bar cache, readiness-flag warmup, single
backtest/live path, parallel-run optimizer); none is novel risk (§10.D). The A→B→C split holds.
**Five gaps must be closed before planning** (§10.E) — all in Plan B/C, none invalidating the
architecture. The largest are the **indicator update-trigger seam under multi-timeframe** (G1)
and the **EMA seeding convention that sets the re-baselined reference** (G2). The biggest
non-indicator cost (per-bar logging) is real but **out of scope and independently addressable**.

### 10.A Per-tick consumer trace — completeness (verified)

**The window-slice claim is CONFIRMED.** The complete `feed.window()` consumer census across the
whole repo is exactly: `strategies_handler.py:125` (single-leg), `:294`/`:295` (pair legs), and
`bar_feed.py:573` (`megaframe`'s internal per-symbol loop, screener path). **No other consumer
slices a price window per tick.** So Plan C's "remove the per-tick master-frame slice across all
strategies" does reach every direct consumer.

Per-tick consumers on the TIME→BAR route (`full_event_handler.py` `_routes`):

| Consumer | Reads a window? | Data shape | Cost/tick | Cite |
|---|---|---|---|---|
| `strategies_handler.calculate_signals` (single) | **YES** `feed.window()` | trailing `max_window` DataFrame | O(tickers × log n) | `strategies_handler.py:125` |
| `strategies_handler._dispatch_pair` | **YES** ×2 | two trailing DataFrames | O(log n) | `strategies_handler.py:294-295` |
| `execution_handler.on_market_data` | **NO** | reads `BarEvent.bars` payload only (resting-order matching) | O(exchanges) | `execution_handler.on_market_data` |
| `portfolio_handler.update_portfolios_market_value` | **NO** | scalar `bar.close` from `BarEvent.bars` (prebuilt Decimal) | O(portfolios × positions) | `portfolio_handler.py:737-746,774` |
| `feed.generate_bar_event` → `current_bars` | **NO** (dict lookup) | `{ticker: Bar}` over all symbols | **O(symbols)** | `bar_feed.py:392,415-436` |
| `screeners_handler.screen_markets` (deferred) | **via `megaframe`→`window`** | multi-symbol close frame | O(symbols × log n) when fired | `screeners_handler.py:80`, `bar_feed.py:573` |
| `portfolio.record_metrics` (direct call, not routed) | **NO** | portfolio state only | O(portfolios) | per-bar in backtest runner |

**Three findings:**

1. **Mark-to-market does NOT read the feed** — it marks off the `BarEvent.bars` payload (already
   prebuilt `Bar`s with Decimal closes, `bar_feed.py:248-251`). §9.C's "shared last-price read" is
   *already realized* via the event payload; the only residual is O(portfolios × positions) Decimal
   multiplies (trivial for the single-portfolio golden run). **No action — flag as already-optimal**
   so planning doesn't invent a price-cache it doesn't need.

2. **Surprise per-tick consumer the agenda didn't name: the BarEvent factory itself.**
   `generate_bar_event`/`current_bars` iterates **all symbols** every tick (`bar_feed.py:432`). It's
   O(symbols) dict-lookup (cheap, no slice), but the "latest bar per symbol" it builds *overlaps*
   with what Plan A's shared cache will hold. **Adjacent simplification (low priority): the per-tick
   BarEvent payload and the cache's newest row should come from one pass** — fold into Plan A rather
   than maintaining two per-symbol per-tick walks.

3. **No downstream consumer reads indicator *series*.** `signal_record`/`SignalRecord` captures
   intent fields + `strategy.to_dict()` (a declared-attr config snapshot, `base.py:397`), never
   handle values; reporting builds from the trade log / equity curve, not indicator buffers. So the
   O(1) positional read surface (`handle[-1]`) **fully serves every downstream reader** — §9.A item 5
   resolves cleanly, no stateful-read-surface obligation beyond what strategies already use.

### 10.B Warmup / gating semantics under stateful (the load-bearing reframe)

**Today (verified):** warmup is enforced by a per-tick handler short-circuit on **window length**,
not indicator state. Two distinct gates exist:
- single-leg: `if len(data) < strategy.warmup: continue` (`strategies_handler.py:135`), where
  `strategy.warmup = max(handle.min_period())` auto-derived in `_run_init` (`base.py:322-323`;
  SMA_MACD → `max(50,100,15)=100`).
- pair: `if len(win_A) < beta_warmup + z_lookback` (`strategies_handler.py:299-301`) — gates on the
  fit/z requirement (280), **NOT** the handle-derived `warmup` (which is 0 for the handle-free pair,
  `pair_base.py:27-33`).

There is **no run-loop warmup prefix** — `TimeGenerator` yields every date; the handler gate is the
only enforcement. There is **no `is_ready`/`initialized` concept today** — readiness ≡ "window wide
enough."

**The reframe (this is what Plan B/C must implement):**

- **Readiness moves from window-length to per-indicator state.** `IndicatorHandle` gains
  `is_ready` (Nautilus `initialized` / LEAN `IsReady`): `count >= min_period`. The strategy gate
  becomes `all(h.is_ready for h in self._handles)` — which for SMA_MACD first turns true at exactly
  the 100th consumed bar, **byte-identical firing tick to today's `len==warmup==100`** *iff the feed
  pushes one completed bar per visibility event in order, starting from bar 0*.

- **Indicators must update during warmup, even when no signal is emitted.** Today the window is
  recomputed fresh each fire; a stateful indicator accumulates from the first bar. So
  `indicator.update()` must run on every consumed bar regardless of the signal gate — the gate
  suppresses *emission*, not *consumption*. This is a behavioral seam change to state explicitly in
  Plan C (`evaluate` currently couples repopulate+dispatch, `base.py:368-373`).

- **The pair maps to two of the §4.2 shapes, cleanly.** β-fit = the degenerate **refitting**
  indicator (`estimate(window)` once at readiness, then frozen — matches today's
  `if self._beta is None:` fit-once, `eth_btc_pair_strategy.py:229-239`); the z-score = a
  **bounded-window** indicator (rolling mean/std over `z_lookback`). Strategy readiness = β fitted
  (250 bars) **and** z buffer full (30 more) = 280. The `max_window>=beta_warmup+z_lookback` validate
  (`pair_base.py:121-128`) becomes the cache-capacity contribution. **Subtlety to pin:** β fits the
  *oldest* 250 bars of the window (`[: beta_warmup]`), so the stateful version must fit at the
  first-ready tick over the first 250 buffered bars and freeze — re-fitting on the slid buffer would
  break parity.

- **Two warmups, not one (LEAN delta, §10.D-2).** Separate (i) *cache hydration* — the shared
  buffer holds ≥ `max(lookback)` bars — from (ii) *indicator readiness* — each indicator's own
  `is_ready`. Window-needing indicators (pair β/z, rolling cointegration) depend on (i); pure
  scalar-recursive indicators (SMA/EMA/MACD/RSI) depend only on their own (ii). Modeling these as one
  gate will mis-warm a window-needing indicator.

**Re-baseline mechanics (Plan B) — now pinned to the exact float drivers:**

- **SMA — running-sum vs rolling-recompute.** Today `_SMA.compute` slices `bars[start_dt:]`
  (`start_dt = now - timeframe*window`) and runs `ta.SMAIndicator(...).dropna()` — pandas recomputes
  each window's mean fresh (`catalog.py:64-80`). A stateful running-sum SMA (`sum += new - oldest`)
  differs by ~1 ULP in float summation order. **This is the dominant re-baseline driver.**
- **MACD — seed-once vs sliding re-seed (verified).** `ta`'s EMA is `ewm(span=n, adjust=False)` —
  **seed-once recursive** (confirmed: `ta.trend._ema`). Today MACD recomputes over a *sliding*
  `frame.iloc[pos-100:pos]` window each tick (`catalog.py:90-111`), so the recursion re-seeds from a
  *different* bar every tick. A stateful EMA seeds **once** at the first bar and never re-seeds. After
  warmup the transient decays to sub-ULP (slow span 12 over 100 bars ≈ `e^-17`), so practical
  divergence is tiny — **but the seeding convention is a decision that sets the new reference and
  must be pinned** (seed-from-first-value vs SMA-seed) before cross-validation, and the readiness
  offset (`min_period = slow+signal = 15`, the `min_periods=window` NaN prefix) must be reproduced.

**Net for Plan B:** re-baseline is genuinely required (SMA running-sum ULP is unavoidable; MACD
seeding is a pinned choice), exactly as §8 anticipated — and the cross-validation gate (backtesting.py
/ backtrader) is the right guard. The MACD divergence is *bounded*, so cross-validation should pass
comfortably; the SMA ULP is the line item to expect movement on.

### 10.C Adjacent optimizations (out of indicator scope)

- **Per-bar logging (~22% of W2) — real, but workload-dependent and out of scope.** The static
  trace found few hot-path log sites on the *golden* path: one `logger.debug('Strategy signal…')`
  per emitted signal per portfolio (`strategies_handler.py:255`) and the screener INFO logs
  (oracle-dark, no screeners registered). The 22% is therefore concentrated in **structlog's
  per-call event processing on the per-signal debug log** under W2's higher signal volume (the
  golden run barely logs). **Cheap fix, independent of this phase:** ensure a level-filtering bound
  logger (short-circuit below the configured level) and/or set backtest log level to WARNING so the
  per-signal `debug` never builds its event dict. **Recommend a one-shot per-line profile to confirm
  the dominant call site before optimizing** (the static read can't see call *counts* under W2).
  Keep this as a separate quick task, not folded into A/B/C.
- **Mark-to-market — already optimal (see §10.A-1).** No action.
- **Multi-symbol/timeframe fan-out** — handled under G1 below (the update-trigger seam is the
  scaling axis, not the window slice).

### 10.D Framework deltas (targeted — only what changes the design)

**Three actionable deltas:**

1. **Multi-timeframe: feed an aggregator from the fast stream; do NOT resample-per-tick.** Both
   first-class engines key a slow-TF indicator off an aggregated bar type (Nautilus `BarAggregator`
   → composite `BarType`; LEAN `RegisterIndicator(symbol, indicator, timedelta(hours=1))` hiding a
   consolidator). The `(symbol, timeframe)` cache key is the right shape — but the **producer of a
   slow-TF key must be a consolidator that consumes the base feed and emits on bucket-close**, driven
   by the existing rule-4 visibility (`bar_feed.py:24-30`), not a per-tick resample. Copy LEAN's
   single-call `RegisterIndicator(symbol, indicator, timeframe)` ergonomic. (For the golden
   SMA_MACD, `timeframe == base == 1d`, so this collapses to "update every tick" — Plan A/B can ship
   without solving it, but the **interface must not hardcode per-base-tick updates**, see G1.)
   **→ RESOLVED 2026-06-24: the full data model is now §10.G (register-at-base, consolidate-up),
   folding in a real near-term requirement — the same instrument traded on two portfolios at two
   timeframes.**
2. **Separate cache-warmup from indicator-readiness** (LEAN makes this explicit; → §10.B two-warmups).
3. **Route live-start backfill through the same `update(bar)` path** (Nautilus `request_bars()` flows
   historical bars through the identical `handle_bar`/`update_raw`). Don't add a bulk-warmup method
   that bypasses `update` — it's the cleanest guarantee of the single-code-path claim.

**Confirmations (validated by ≥2 frameworks → idiomatic, do not re-litigate):** stateful incremental
indicators with derived-state-only (Nautilus + LEAN); shared raw-bar cache, indicators don't buffer
raw bars (Nautilus `Cache` + LEAN `SecurityCache` + zipline `DataPortal`); readiness flag over
window-length checks (Nautilus `initialized` + LEAN `IsReady`; zipline's manual `context.i < 300` is
the anti-example being improved on); single backtest/live path (Nautilus + LEAN "no code changes");
**optimizer throughput from parallel full runs, not vectorized indicators** (Nautilus `BacktestNode`,
LEAN N-backtests, zipline repeated `run_algorithm` — vectorbt is the lone vectorize-across-params
model, and it pays by surrendering incremental state + live parity). The §3 anti-pattern call
(reject vectorized precompute for look-ahead safety) is correct: vectorbt materializes all values
before any decision, making look-ahead a manual-discipline problem; an event-driven engine makes the
future *structurally absent*.

### 10.E Gaps to close before plan-phase (the actionable checklist)

- **G1 — Wire the indicator update-trigger seam** (data model RESOLVED in §10.G; this is the
  remaining *implementation* item). Two parts: **(a)** specify *who* calls `indicator.update()` and
  *on what bar-close* — a consolidator emits on rule-4 bucket-close per `(symbol, timeframe)`, which
  drives both the derived-bar buffer and the indicator update (no per-tick resample); **(b)** the
  wiring-time derivation asserts `base_timeframe ≤ min(timeframe)` over consumers and sizes the
  base-source entry to the coarsest consumer in base-bar-equivalents (§10.G). For the golden
  SMA_MACD `timeframe == base == 1d`, so the trigger collapses to "every tick." Crosses Plan A
  (cache + consolidator) + Plan C (the `evaluate` seam). **Highest-leverage gap.**
- **G2 — Pin the EMA seeding convention** (seed-from-first-value vs SMA-seed) and the MACD readiness
  offset before re-baseline — it *sets* the new reference numbers (§10.B). Plan B blocker.
- **G3 — State the "update during warmup, emit after" contract.** Indicators consume every bar from
  bar 0; the warmup gate suppresses emission only. Rework `evaluate` (`base.py:368-373`) accordingly.
- **G4 — Map the pair onto §4.2 shapes explicitly in Plan C**: β = refitting/fit-once-frozen, z =
  bounded-window; strategy readiness = both; β fits the oldest 250 buffered bars at first-ready and
  freezes. Folds the `beta_warmup+z_lookback` gate and the `max_window` validate into cache capacity.
- **G5 — Decide the BarEvent-payload / cache-newest-row unification** (§10.A-2): one per-symbol
  per-tick pass, or keep two. Low risk, but settle it in Plan A so it isn't discovered mid-execution.

### 10.F What did NOT change (so planning doesn't reopen it)

The shared-cache-holds-bars-only decision, the `derive_instruments`-mirroring capacity-derivation
*pattern* (`universe/instruments.py:170`, `membership.py:44` both exist; the capacity *formula* is
refined for multi-timeframe in §10.G, the mirror pattern is not), the read surface
(`handle[-1]`/`crossover`/`is_above`, `handle.py:53-62`), the 7-rule contract + D-08/D-10 cursor, and
the A→B→C order all stand as written. Re-baseline scope is unchanged (§8). Logging is explicitly
**not** in this phase. No framework finding contradicts §3.

### 10.G Multi-timeframe data model — RESOLVED (2026-06-24)

Resolves §10.D delta-1 / part of G1. Triggered by a concrete near-term requirement: **the same
instrument traded on two portfolios at two different timeframes** (e.g. BTCUSD on a 1h strategy and a
4h strategy at once).

**Decision: register each instrument ONCE at the base (lowest) timeframe; derive every higher
timeframe by consolidating up. Never fetch/subscribe the same instrument per-timeframe
independently.**

- **This is already how backtest works — keep and extend it.** `BacktestBarFeed` loads one base
  frame per ticker (`store.read_bars(ticker)`, `bar_feed.py:245`); `_resampled_frame(ticker, alias)`
  resamples-from-base-and-memoizes per `(ticker, timeframe)` (`bar_feed.py:332-354`). The
  consumer-facing `window(ticker, timeframe, …)` hides the resample — "fetch a different timeframe"
  *is* "resample from base." The stateful design keeps this and extends it to drive incremental
  indicator updates (the consolidator on bucket-close), instead of recomputing a window per tick.
- **Why, over per-timeframe fetch:** (1) *consistency by construction* — a 4h bar built from your own
  1h bars always agrees with the 1h bars the other strategy sees; two independent provider feeds can
  desync (aggregation/gaps/revisions/session alignment). (2) *no duplication* — one base entry per
  symbol; the 1h and 4h views are derived (this is the symbol-in-two-consumers case the shared cache
  exists to solve). (3) *one look-ahead contract* — rule-4 visibility (`bar_feed.py:24-30`) governs
  when a resampled bucket is complete; provider-native higher-TF bars would re-open that audit each
  time. (4) *live parity* — one subscription at base, a consolidator builds higher TFs incrementally
  (Nautilus `BarAggregator` / LEAN consolidators); no duplicate per-TF subscriptions.

**Hard constraint:** you resample UP, never DOWN — so `base_timeframe ≤ min(timeframe)` across all
consumers. The wiring-time derivation (the `derive_instruments` mirror) must compute the required
base resolution = `min(timeframe)` over consumers and assert the store/provider can supply it.

**Capacity — two layers (refines §4.1's flat `max(lookback)`):**
- **Base-source entry** `(symbol, base)`: capacity = `max` over consumers of *lookback expressed in
  base bars* = `max(lookback_c × timeframe_c / base_timeframe)`. The coarsest consumer binds.
- **Each derived** `(symbol, timeframe)`: keeps its own `lookback` depth.

**Worked example (the requirement):** BTCUSD on P1 @ 1h (lookback 100) + P2 @ 4h (lookback 50), store
base = 1h → base-source holds **200** 1h-bars (the 4h consumer binds: 50 × 4); derived `BTCUSD@1h`
depth 100, `BTCUSD@4h` depth 50. P1's indicators update on each 1h bucket-close, P2's on each 4h
bucket-close (every 4th 1h bar) — both fed from the one base stream; the bucket-close *is* the
`indicator.update()` trigger (G1-a).

**Exception (does not apply to the crypto golden path):** markets with provider-native or
session-aligned higher-TF bars (e.g. equities trading sessions) may need native per-TF fetch; 24/7
crypto resamples exactly, so register-at-base is unconditionally correct here.

### 10.H Indicator buffers + `ta` drop (clarified 2026-06-24)

Folded into §4.2 + Plan B. Two decisions:

- **Scalar adapters drop `ta` on the runtime path.** `ta` has no incremental API, so SMA/EMA/MACD/RSI
  become hand-written O(1) recurrences; `ta`/pandas survive **only as a test-time oracle**
  (bar-by-bar convergence check), never per tick. This is the *cause* of the Plan B re-baseline, not
  a side effect (§10.B).
- **Three buffers, sized independently** (the "size 2?" question): **(i)** shared raw-bar cache =
  input depth = max lookback (§4.1/§10.G) — this is where "retain more raw history" lives; **(ii)**
  indicator internal state — O(1) scalar for EMA/MACD/RSI, running-sum for SMA (its evicting value
  read from (i), so SMA holds no private ring); **(iii)** handle output-history buffer for
  `handle[-k]` reads = **default depth 2, but a declared per-handle depth** so deeper indicator-vs-own-past
  patterns ("3 rising bars", divergence over N) request what they read. Bounded, never unbounded.

**Correction to §4.2 shape-1 as originally written:** "O(1) state / reads only the newest bar" is
exact for EMA/MACD/RSI but **not** for SMA, which needs the value leaving the window — sourced as one
indexed read from the shared cache (§4.2 now reflects this). No architectural change; a precision fix
so Plan B doesn't implement SMA with a redundant private ring.
