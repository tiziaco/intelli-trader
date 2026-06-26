# Phase 5: Stateful Indicators + Shared Bar Cache - Research

**Researched:** 2026-06-24
**Domain:** Incremental (O(1)/tick) stateful technical indicators + numerical re-baseline de-risking; event-driven backtest engine
**Confidence:** HIGH (the four recurrences and the re-baseline safety are EMPIRICALLY verified against `ta` 0.11.0 / pandas 2.3.3 on the golden dataset, not asserted from training)

<user_constraints>
## User Constraints (from CONTEXT.md)

> The 22 `P5-DNN` decisions are LOCKED. This research does NOT reopen them. It supplies the
> numerical/correctness specifics that make the locked design implementable correctly. The planner
> MUST cite `P5-DNN` tags in must_haves/truths/objective (per the CONTEXT tag-scheme note and the
> MEMORY note on the decision-coverage gate citation format).

### Locked Decisions (verbatim, abbreviated to the load-bearing clause)
- **P5-D01** — The spec supersedes the ROADMAP "byte-exact" mandate; Phase 5 RE-BASELINES the oracle (Phase-5-only carve-out).
- **P5-D02** — Acceptance bar = the EXISTING cross-validation gate (`tests/golden/CROSS-VALIDATION.md`, M5-10): backtesting.py 0.6.5 + backtrader 1.9.78.123 **gating** at 1% rel tol; re-run → confirm PASS → freeze new trade log + equity. Expected movement: firing tick preserved (warmup=100) so trade dates/count (134) stay identical, only ULP equity/PnL drift. If the trade SET moves → explicit cross-val corroboration before freezing.
- **P5-D03** — Gate (b) (W1 perf) stays; same-machine A/B; re-freeze on a cool machine.
- **P5-D04** — EMA/MACD seed = seed-from-first-value (`adjust=False`): `y[0]=x[0]`, seeded ONCE at global first bar, `α=2/(n+1)`. **THE G2 BLOCKER — Plan B is gated on it.**
- **P5-D05** — SMA = running-sum O(1) (LEAN-style): `sum += new − evicted`; evicting value from the indicator's own small ring (Model B). Accept ~1e-9 ULP drift.
- **P5-D06** — Readiness = per-indicator `is_ready = count >= min_period`; emit when `all(h.is_ready)`. `min_period` UNCHANGED (SMA→window, EMA→period, MACD→slow+signal). SMA_MACD fires at the 100th bar → byte-identical firing tick. NO convergence buffer.
- **P5-D07** — Feed-centric Model B (Nautilus/LEAN): indicators fed via pure push `update(...)`, hold OWN minimal bounded buffers, do NOT read the shared cache. AMENDS spec §10.H.
- **P5-D08** — Per-indicator internal buffers: EMA/MACD/RSI scalar-only; SMA holds a small ring sized to its window solely to read the evicting value. Pair β holds oldest-250 for a one-time fit; pair z holds bounded `z_lookback`=30. Handle output-history buffer default depth 2.
- **P5-D09** — `update()` signature: single-input `update(bar)` extracts `input_col`; multi-input (pair) receives both legs. Exact arg form = planner's.
- **P5-D10 / D10a / D10b / D10c** — Per-(symbol[,timeframe]) fan-out; lazy instantiation on first bar; independent per-symbol readiness; missing/gap bar = no update (causality, state frozen, count increments on REAL bars only).
- **P5-D11 / D12** — Drop `ta` on the runtime path; hand-write O(1) recurrences for ALL FOUR (SMA running-sum, EMA seed-from-first, MACD two EMAs+signal, RSI Wilder/RMA). `ta`/pandas retained ONLY as test-time oracle. Re-baseline EMA/RSI unit tests.
- **P5-D13 / D13a / D14** — Remove per-tick `self.bars` master-frame slice ENTIRELY (Option B); handler pushes latest completed bar → `strategy.update(ticker,bar)` → gate on `strategy.is_ready(ticker)` → `generate_signal(ticker)`. Migrate count/date test fixtures off `self.bars`. Drop `feed.window()` + len-gate on per-tick path.
- **P5-D15** — Pair onto §4.2 shapes: β=fit-once-frozen over oldest 250; z=bounded-window over `z_lookback`=30; readiness = β fitted AND z buffer full = 280.
- **P5-D16 / D16a / D16b** — `BarFeed` owns shared recent-bars API; Plan A builds newest-bar + registration INTERFACE, DEFERS deep multi-bar cache. G5: unify the newest-bar pass (one per-symbol-per-tick walk). G1: update-trigger seam interface-only; assert `base_timeframe ≤ min(timeframe)`; golden collapses to "every tick."
- **P5-D17** — `ta`-convergence test: feed bars one-by-one, assert convergence to `ta` batch output **post-warmup** at **~1e-9 abs / 1e-6 rel**. Covers ALL FOUR.
- **P5-D18** — Determinism gate unchanged: double-run byte-identical + `mypy --strict` clean.
- **P5-D19** — `reset()` built now (clears scalar/ring + readiness count + output buffer + fan-out map); a test asserts `reset()`→re-feed reproduces a fresh run.
- **P5-D20** — `causal` flag + decision-path guard built now; all v1 adapters `causal=True`.
- **P5-D21** — Strategy-author declaration surface preserved (`self.indicator(SMA,'close',window)` + handle-only reads).
- **P5-D22** — Spec amendments: (1) §10.H SMA holds its own ring; (2) §10.G/§4.1 cache capacity keys off raw-bar consumers, deep cache deferred; (3) §4.2 cache role thinner.

### Claude's Discretion (planner-territory — NOT locked)
Exact `IndicatorHandle` method signatures; per-symbol handle-storage container type; mypy `--strict`
generics on the new adapter Protocol; the pair-z running-moments-vs-recompute sub-choice; the
Plan A/B/C task-boundary breakdown.

### Deferred Ideas (OUT OF SCOPE)
Full multi-timeframe consolidator; deep capacity-derived multi-bar shared cache; live backfill through
`update(bar)`; synthetic/spread instrument; optimizer/param-sweep; concrete Kalman/Hawkes adapters;
screener subsystem. Also adjacent-but-out: per-bar logging (~22% W2) is a SEPARATE quick task.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-05 | SMA & MACD indicators compute incrementally (rolling/memoized) instead of a full-window `ta` rebuild every bar. *(Note: the original REQUIREMENTS.md text says "reproducing `[BYTE-EXACT]` output" and "Oracle-gated" — this is SUPERSEDED by P5-D01: the design spec re-baselines deliberately. The planner must treat the re-baseline carve-out, not byte-exactness, as the contract.)* | This research supplies the exact O(1) recurrences (SMA running-sum, EMA `y+=α(x−y)`, MACD two-EMAs+signal), empirically verified against `ta`; the convergence-test tolerance; and the **empirical proof that the SMA_MACD trade SET does NOT move** (signal-set identity + 9-orders-of-magnitude crossover margin). |
</phase_requirements>

## Summary

This phase converts four `ta`-backed indicators (SMA, EMA, MACD, RSI) from per-tick full-series pandas
recompute to hand-written O(1)/tick stateful recurrences, on a feed-centric (Model B) push contract,
and deliberately re-baselines the SMA_MACD oracle (cross-validated, not byte-exact). The architecture
is fully locked by CONTEXT.md's 22 `P5-D` decisions and the design spec; the research question is purely
numerical: **do the hand-written recurrences match `ta`'s semantics closely enough that (a) the
`ta`-convergence test passes post-warmup and (b) no borderline ULP difference flips a SMA_MACD trade?**

The answer, verified empirically against `ta` 0.11.0 / pandas 2.3.3 / numpy 2.2.6 on the actual golden
dataset (`data/BTCUSD_1d_ohlcv_2018_2026.csv`, 3076 bars), is **yes, with overwhelming margin**:

- All three SMA_MACD indicators converge to `ta`'s batch output post-bar-100 at **max_abs ≤ 1.9e-10,
  max_rel ≤ 2.7e-11** — far inside the P5-D17 ~1e-9/1e-6 tolerance.
- Replicating the strategy's EXACT decision logic (`is_above` SMA filter + `crossover/crossunder`
  MACD-zero) on incremental vs `ta` values produces an **IDENTICAL signal set (274 raw fires each,
  zero flips)**.
- The nearest any decision value gets to its flip boundary is **|macd_hist| ≥ 7.7e-3** from zero and
  **|sma50−sma100| ≥ 0.16** from zero, against a max indicator drift of ~2e-10 — a safety margin of
  **~9 orders of magnitude**. A trade-SET flip is effectively impossible on the golden data.

Two non-obvious correctness landmines were found and must be specified to the planner: (1) **`ta`'s RSI
does NOT use textbook Wilder seeding** (simple mean of first n) — it uses pure `ewm(alpha=1/n,
adjust=False)`, i.e. single-value seed-from-first-gain; the gain/loss alignment (`close.diff(1)`,
seeded from bar 1) is the RSI pitfall. (2) **P5-D04's seed-from-first-value matches Nautilus EMA and
`ta`/pandas `ewm(adjust=False)`, but NOT LEAN's *default* EMA** (which SMA-seeds) — the objective's
claim that it matches "LEAN default EMA" is imprecise; it matches LEAN's *explicit-smoothing-factor*
constructor instead.

**Primary recommendation:** Implement the four recurrences exactly as specified in `## Code Examples`
(SMA running-sum with deque eviction; EMA in the **factored form** `y += α(x−y)` — verified 2× closer
to `ta` than the expanded `α·x+(1−α)·y` form; MACD = factored-EMA(fast) − factored-EMA(slow), then
factored-EMA(signal) of that line; RSI = factored-RMA `α=1/n` over `close.diff(1)`-derived gain/loss
seeded from bar 1). Set the P5-D17 convergence tolerance to `atol=1e-9, rtol=1e-6` comparing only on
indices where BOTH the incremental and `ta` series are non-NaN (post each indicator's own `min_period`).
The re-baseline is safe; expect trade count = 134 unchanged, only sub-ULP equity drift.

## Architectural Responsibility Map

> All capabilities are server-side / engine-internal (this is a Python backtest library, no client/CDN
> tiers). "Tier" here = the engine layer that owns the responsibility.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Incremental indicator value production | Indicator adapter (`strategy_handler/indicators/catalog.py`) | `IndicatorHandle` (output buffer) | Model B (P5-D07): the adapter holds derived state; the handle holds the `[-k]` output history. Value math is the adapter's job, not the handler's. |
| Per-bar push / update trigger | `StrategiesHandler` loop → `Strategy.update(ticker,bar)` | consolidator (G1, interface-only) | The handler routes the latest completed bar to the ticker's handle-set (P5-D14); the consolidator seam is the future multi-TF producer (deferred). |
| Readiness gating | `Strategy.is_ready(ticker)` (aggregates handle `is_ready`) | per-indicator `is_ready=count≥min_period` (P5-D06) | Readiness moves from window-length to per-indicator state. The strategy gate replaces `len(window)<warmup`. |
| Shared recent-bars provision | `BarFeed` (newest-bar API + registration interface, P5-D16) | `BacktestBarFeed` (view backing) | Cache holds bars only; instruments stay in `derive_instruments`. Plan A ships newest-bar + interface, defers deep cache. |
| Look-ahead safety | `BarFeed` 7-rule contract + D-08/D-10 cursor | causal-flag decision-path guard (P5-D20) | The structural contract stays byte-exact; the causal guard is the structural fence for future non-causal adapters. |
| Pair β/z state | window-needing indicator (Plan C) | `BarFeed` (the 280-bar buffer feeds it) | β=fit-once-frozen over oldest 250; z=bounded-window over 30 (P5-D15). |
| Money / ledger | `core/money.py` + portfolio managers (UNCHANGED) | — | **Indicators are float64 (the `ta` domain), NOT money.** The Decimal-end-to-end rule governs the ledger, never the recurrences (see `## Common Pitfalls` #5). |

## Standard Stack

**No new external packages are installed by this phase.** It hand-writes recurrences using stdlib +
already-present `numpy`/`pandas`, and *removes* `ta` from the runtime path (retaining it test-only).

### Core (all already in `pyproject.toml`, all verified present in `.venv`)
| Library | Version (verified) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| `ta` | 0.11.0 (`from ta import trend, momentum`) | **Test-time oracle ONLY** post-phase (P5-D11/D17). The convergence reference. | It IS the current reference these indicators were frozen against; using it as the oracle means the convergence test asserts against the exact prior semantics. |
| pandas | 2.3.3 [VERIFIED: `.venv`] | The oracle's batch compute (`rolling().mean()`, `ewm(adjust=False).mean()`). | `ewm(adjust=False)` is the canonical seed-from-first-value EMA — the P5-D04 reference. |
| numpy | 2.2.6 [VERIFIED: `.venv`] | float64 scalar math in the recurrences. | Indicator domain is float64; no Decimal. |
| `collections.deque` (stdlib) | — | SMA's bounded ring for O(1) eviction (P5-D05/D08). | `deque(maxlen=n)` gives O(1) append + auto-evict; the evicted value is read before it falls off. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| backtesting.py | 0.6.5 [CITED: CROSS-VALIDATION.md] | Gating cross-val engine for the re-baseline (P5-D02). | REUSE the existing harness — do NOT rebuild. |
| backtrader | 1.9.78.123 [CITED: CROSS-VALIDATION.md] | Gating cross-val engine. backtrader matched iTrader to the cent on final equity in M5-10. | REUSE. |
| nautilus-trader | 1.227.0 [CITED: CROSS-VALIDATION.md] | Non-gating reconciliation oracle. | REUSE (non-gating). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-written recurrences | `ta`'s streaming API | **`ta` has NO incremental/streaming API** (Series-in/Series-out only) — this is the *cause* of the re-baseline, not a choice (spec §10.H, verified: `_sma` = `series.rolling(...).mean()`, `_ema` = `series.ewm(...).mean()`). No alternative exists; this is forced. |
| EMA factored form `y+=α(x−y)` | Expanded form `α·x+(1−α)·y` (Nautilus's literal code) | Empirically the factored form matches `ta` to 1.5e-11 vs 2.9e-11 for expanded (pandas `ewm` uses the factored form internally). Both pass tolerance; **pick factored** for minimal drift + best `ta` match. |
| SMA running-sum (P5-D05, LEAN) | Fresh-windowed-sum each tick (Nautilus) | Running-sum is strict O(1) but accumulates ~1e-9 ULP drift; fresh-sum is O(n)/tick but numerically stabler. P5-D05 locks running-sum (LEAN idiom, strict O(1)) and accepts the drift — **verified negligible** (max_abs 1.9e-10 on golden). |

**Installation:** none. (Removing `ta` from the runtime path is a code change, not a dependency change —
`ta` stays in `pyproject.toml` for the test oracle.)

## Package Legitimacy Audit

> **Not applicable** — this phase installs ZERO external packages. It removes `ta` from the runtime
> import path (retaining it as a test-only dependency already in `pyproject.toml`) and uses only
> stdlib + already-vendored numpy/pandas. No registry interaction, no slopcheck surface. All libraries
> referenced are pre-existing, pinned, and lockfile-committed (`poetry.lock`).

## Architecture Patterns

### System Architecture Diagram (the per-tick data flow Plan B/C reshapes)

```
TIME route
    │
    ▼
feed.generate_bar_event  ──(G5: one per-symbol walk)──►  {ticker: Bar}  ──►  BAR event
    │                                                          │
    │  (Plan A: same walk writes the cache newest row)         │
    ▼                                                          ▼
BarFeed newest-bar cache                          ┌─────────────────────────────────┐
(bars only; capacity from registered consumers)   │  StrategiesHandler.calculate_   │
                                                   │  signals  (Plan C restructure)  │
                                                   └─────────────────────────────────┘
                                                          │ for each ticker in event.bars:
                                  ┌───────────────────────┼────────────────────────┐
                                  ▼                       ▼                        ▼
                       strategy.update(ticker,bar)   if is_ready(ticker):     [gap bar → skip,
                       (push latest completed bar)   generate_signal(ticker)   state FROZEN,
                                  │                       │                     P5-D10c]
                                  ▼                       ▼
                  per-ticker handle-set (lazy,     reads handles via primitives
                  P5-D10a):                        (crossover/is_above, UNCHANGED)
                    short_sma.update(close)              │
                    long_sma.update(close)               ▼
                    macd_hist.update(close)         SignalIntent | None
                  each adapter: O(1) recurrence,
                  is_ready = count >= min_period
```

Key structural change vs today: the per-tick `feed.window(ticker, tf, max_window, asof)` slice
(`strategies_handler.py:125`) and the `if len(data) < strategy.warmup: continue` gate
(`strategies_handler.py:135`) are **removed**. The handler pushes the single latest bar; readiness is
per-indicator state, not window length. `evaluate()`'s repopulate+dispatch coupling
(`base.py:368-373`) decouples into "update always, emit only when ready" (P5-D13/G3).

### Pattern 1: Stateful adapter with seed-from-first-value (Nautilus/LEAN idiom)
**What:** Each adapter holds O(1) derived state + a `count`; `update(value)` advances the recurrence;
`is_ready` = `count >= min_period`; `reset()` clears state + count + output buffer.
**When to use:** all four scalar indicators (SMA/EMA/MACD/RSI) under Model B (P5-D07).
**Example:** see `## Code Examples` — the recurrences are the load-bearing content.

### Pattern 2: Update-during-warmup, emit-after (the G3 seam change)
**What:** `indicator.update()` runs on EVERY consumed bar from bar 0; the readiness gate suppresses
*emission*, never *consumption*. A stateful indicator accumulates from the first bar (unlike today's
fresh-window recompute), so skipping `update` during warmup would corrupt state.
**Source:** spec §10.B (verified against `base.py:368-373` coupling); Nautilus/LEAN both update on
every bar and gate output on `initialized`/`IsReady`.

### Pattern 3: Fit-once-frozen refitting indicator (the pair β, Plan C)
**What:** β fits the OLDEST 250 buffered bars at first-ready, then FROZEN forever. Re-fitting on the
slid buffer would break parity.
**Source:** P5-D15; verified against `eth_btc_pair_strategy.py:229-231` (`if self._beta is None: self._beta = self._fit_beta(...)`).

### Anti-Patterns to Avoid
- **Decimal-izing the recurrences.** Indicators are float64 (the `ta` domain). Routing them through
  `to_money` would (a) be wrong (TA values aren't money) and (b) change the numbers. The
  Decimal-end-to-end rule governs the ledger only. Confirmed: `catalog.py` docstring + `primitives.py`
  docstring both state "indicator values are the `ta` float64 domain, NOT money."
- **SMA private re-sum.** P5-D05/§10.H: the ring is a *lookup for the departing value*, never
  re-summed. `sum += new − evicted`, not `sum = sum(ring)`.
- **Textbook Wilder RSI seeding.** Do NOT seed RSI's RMA with a simple mean of the first n gains —
  `ta` does not (see Pitfall #2). Single-value seed via the RMA recurrence from bar 1.
- **Re-seeding EMA each tick.** Today's MACD re-seeds from a sliding window each tick (`catalog.py:90-111`);
  the stateful EMA seeds ONCE at the global first bar (P5-D04). Re-seeding would re-introduce the O(n)
  cost this phase removes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| O(1) window eviction for SMA | A manual index-tracking ring with modular arithmetic | `collections.deque(maxlen=window)` | `deque` auto-evicts on append at the cap; read `ring[0]` (or capture the popped value) before it falls off. Stdlib, O(1), no off-by-one. |
| Convergence reference for the test | A re-derived "expected" formula | `ta` batch output (P5-D17) | `ta` IS the prior reference; asserting against it proves "no divergence bug" against the exact frozen semantics, not against a possibly-wrong hand re-derivation. |
| Cross-engine re-baseline validation | A new comparison harness | The existing `tests/golden/CROSS-VALIDATION.md` harness (P5-D02) | It already force-matches config across 3 engines and recomputes metrics through `itrader.reporting.metrics`. Rebuilding risks a worse oracle. |
| Capacity derivation for the shared cache | A bespoke strategies-only loop | Mirror `universe/instruments.py::derive_instruments` (P5-D16) | The screener-extensibility pattern is already solved; a strategies-only hardcode would have to be re-done when the screener lands. |

**Key insight:** In this domain the "complexity" is not the indicator math (the recurrences are 3-5
lines each) — it is the *exact float semantics* matching `ta`. The empirical convergence harness IS the
de-risking; do not approximate it.

## Common Pitfalls

### Pitfall 1: RSI gain/loss alignment (the one real footgun, EMPIRICALLY caught)
**What goes wrong:** A naive RSI using `np.diff(x, prepend=np.nan)` then zeroing `up[0]` shifts the
gain/loss series by one bar relative to `ta`'s `close.diff(1)`, producing **huge divergence**
(max_abs ≈ 28 RSI points in this session's first attempt).
**Why it happens:** `ta` computes `diff = close.diff(1)` (so `diff[i] = close[i]−close[i-1]`, NaN at
index 0), `up = diff.where(diff>0, 0)`, `dn = -diff.where(diff<0, 0)`, then `ewm(alpha=1/n,
adjust=False).mean()` on each. The RMA must seed from **bar 1** (the first real diff), not bar 0.
**How to avoid:** Mirror `ta`'s exact alignment: `gain_i = max(close_i − close_{i-1}, 0)`,
`loss_i = max(close_{i-1} − close_i, 0)`, both first defined at i=1; seed the up-RMA and down-RMA from
their bar-1 value; `RS = up_rma/down_rma`; `RSI = 100 if down_rma==0 else 100 − 100/(1+RS)`.
**Verified result with correct alignment:** max_abs = **2.84e-14**, max_rel = **9.4e-16** vs `ta` — perfect.
**Warning sign:** RSI convergence error > 1e-6 anywhere post-bar-`n` → alignment bug, not a tolerance issue.

### Pitfall 2: `ta` RSI does NOT use textbook Wilder seeding
**What goes wrong:** The objective (and most TA literature) says Wilder's RSI seeds the first average as
the *simple mean of the first n gains/losses*, then applies the recurrence. **`ta` does not do this.**
**Root cause (verified from `ta/momentum.py` source):** `ta` applies
`ewm(alpha=1/window, min_periods=window, adjust=False).mean()` directly to the gain/loss series — i.e. a
pure RMA seeded from the **first single value** (`y[0]=x[0]`), with `min_periods=window` only *masking*
output until index `window-1`, NOT changing the seed. The smoothed-mean recursion runs from bar 1.
**How to avoid:** The stateful RSI must seed-from-first-value (consistent with EMA, P5-D04), NOT
simple-mean-of-first-n. The `min_period` for the convergence-test alignment is `window` (output first
emitted at index `window-1` = 13 for n=14), but the recursion starts at bar 1.
**Impact if wrong:** RSI is oracle-dark (not in SMA_MACD), so this won't move the frozen oracle — but it
WILL fail the P5-D17 RSI convergence test and produce wrong RSI unit-test re-baselines (P5-D12).

### Pitfall 3: EMA seed-from-first-value matches Nautilus + `ta`, NOT LEAN's default EMA
**What goes wrong:** Trusting the objective's claim that P5-D04 "matches Nautilus + LEAN default EMA."
**Root cause:** LEAN's `ExponentialMovingAverage` (default constructor) seeds the first EMA value from an
**SMA of the first `period` values** ("the first value of the EMA is equivalent to the simple moving
average" — LEAN class reference / `_initialValueSMA`). Nautilus's EMA seeds from the first value
(`if not self.has_inputs: self.value = value` — verified from `ema_python.py`), as does pandas
`ewm(adjust=False)`. P5-D04 (seed-from-first-value) therefore matches **Nautilus + `ta`/pandas**, and
LEAN's *explicit-smoothing-factor* constructor, but NOT LEAN's *default* EMA.
**How to avoid:** This is harmless for correctness — P5-D04 is the RIGHT choice (it matches the `ta`
oracle the convergence test asserts against). Just don't cite "LEAN default EMA" as the justification;
cite Nautilus EMA + `ta`/pandas `ewm(adjust=False)`. The planner should not "fix" the seeding to
SMA-seed to match LEAN — that would BREAK the convergence test.

### Pitfall 4: MACD warmup transient — convergence is bar-position-dependent
**What goes wrong:** Comparing the incremental MACD histogram to `ta` over the FULL series shows large
divergence (max_abs ≈ 9.5 near bars 13-38) — alarming if read as a failure.
**Root cause (verified):** The divergence is entirely confined to the EMA *transient* region (bars
13-38). Today's `ta` MACD recomputes over a *sliding* window each tick, re-seeding; the stateful EMA
seeds once. After the transient decays (slow-span-12 EMA over ~100 bars), they reconverge. **Post-bar-100
(the SMA_MACD firing region) max_abs = 1.7e-11** — fully converged.
**How to avoid:** The P5-D17 convergence test must compare only **post-warmup** (from each indicator's
`min_period` onward — explicitly P5-D17's "skipping the legitimately-different pre-ready region").
For MACD that is `slow+signal = 15`; on the golden data the residual transient extends to ~bar 38 at
1e-6 but is gone by bar 100. **Recommendation:** assert MACD convergence from a settle offset (e.g.
the indicator's own `min_period`, with the understanding that the first few post-`min_period` bars may
sit near the 1e-6 rel edge during the transient). SMA_MACD only READS macd_hist at bar 100+, where
drift is 1.7e-11 — so the oracle is unaffected regardless.

### Pitfall 5: indicators are float64, NOT money (do not Decimal-ize)
**What goes wrong:** Applying the project's Decimal-end-to-end rule to the recurrences.
**Root cause:** The Decimal rule governs the money/ledger path. TA values are the `ta`/pandas float64
domain — `catalog.py` and `primitives.py` docstrings both state this explicitly ("NOT money, do NOT
route through `to_money`"). The pair β is a float; it enters Decimal ONLY at the β-weighted *quantity*
via `to_money` (`eth_btc_pair_strategy.py:246-258`).
**How to avoid:** Keep the recurrences in float64. The float-summation order (SMA running-sum) is the
*intended* re-baseline driver (P5-D05), not a defect to "fix" with Decimal.

### Pitfall 6: tab/space indentation hazard at the edited files
**What goes wrong:** A mixed-indentation diff breaks a tab file.
**Root cause (CLAUDE.md):** `strategy_handler/` handler modules use **tabs**; `price_handler/feed/` and
`core/` use **4 spaces**. Plan B edits `strategy_handler/indicators/*.py` (tabs — verified: `catalog.py`,
`handle.py`, `primitives.py` all tab-indented) and Plan A/C edit `price_handler/feed/bar_feed.py`
(4 spaces).
**How to avoid:** Match the file being edited; never normalize. mypy won't catch this — it's a
whitespace correctness issue.

## Code Examples

> These recurrences are EMPIRICALLY VERIFIED in this session against `ta` 0.11.0 / pandas 2.3.3 on
> `data/BTCUSD_1d_ohlcv_2018_2026.csv`. The convergence figures next to each are measured, not assumed.
> Source for the `ta` semantics: live `inspect.getsource` of the installed package (quoted below).

### `ta`'s actual internal semantics (the reference to match) [VERIFIED: live source inspection]
```python
# ta/trend.py
def _sma(series, periods, fillna=False):
    min_periods = 0 if fillna else periods
    return series.rolling(window=periods, min_periods=min_periods).mean()

def _ema(series, periods, fillna=False):
    min_periods = 0 if fillna else periods
    return series.ewm(span=periods, min_periods=min_periods, adjust=False).mean()
    # ewm(adjust=False) == seed-from-first-value, alpha = 2/(span+1), factored recurrence.

# ta MACD._run:
#   emafast = _ema(close, fast);  emaslow = _ema(close, slow)
#   macd = emafast - emaslow;  macd_signal = _ema(macd, sign);  macd_diff = macd - macd_signal
#   NOTE: iTrader calls MACD(close, window_fast=6, window_slow=12, window_sign=3) by KEYWORD,
#   so the (close, window_slow, window_fast, window_sign) default order does NOT misassign.

# ta RSIIndicator._run:
#   diff = close.diff(1)
#   up = diff.where(diff>0, 0.0);  dn = -diff.where(diff<0, 0.0)
#   emaup = up.ewm(alpha=1/window, min_periods=window, adjust=False).mean()   # RMA, single-value seed
#   emadn = dn.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
#   rsi = where(emadn==0, 100, 100 - 100/(1 + emaup/emadn))
```

### SMA — running-sum O(1) (P5-D05) [VERIFIED: max_abs 1.9e-10, max_rel 5.1e-15 vs ta on golden, post-bar-100]
```python
from collections import deque

class _SMAState:
    def __init__(self, window: int) -> None:
        self._n = window
        self._ring: deque[float] = deque()
        self._sum = 0.0
        self._count = 0
        self.value: float | None = None
    def update(self, x: float) -> None:
        self._ring.append(x); self._sum += x
        if len(self._ring) > self._n:
            self._sum -= self._ring.popleft()   # P5-D05: subtract the EVICTED value; never re-sum
        self._count += 1
        if len(self._ring) == self._n:
            self.value = self._sum / self._n
    @property
    def is_ready(self) -> bool:        # P5-D06
        return self._count >= self._n
```

### EMA — seed-from-first-value, factored form (P5-D04) [VERIFIED: factored 1.5e-11 vs expanded 2.9e-11; pick factored]
```python
class _EMAState:
    def __init__(self, period: int) -> None:
        self._period = period
        self._alpha = 2.0 / (period + 1.0)     # P5-D04
        self._count = 0
        self.value: float | None = None
    def update(self, x: float) -> None:
        if self.value is None:
            self.value = x                     # y[0] = x[0]  (Nautilus / ta ewm(adjust=False))
        else:
            self.value += self._alpha * (x - self.value)   # FACTORED form — 2x closer to ta than alpha*x+(1-alpha)*y
        self._count += 1
    @property
    def is_ready(self) -> bool:
        return self._count >= self._period
```

### MACD histogram — two EMAs + signal EMA (P5-D11) [VERIFIED: post-bar-100 max_abs 1.7e-11; transient bars 13-38 differ, expected]
```python
class _MACDHistState:
    def __init__(self, fast: int, slow: int, signal: int) -> None:
        self._fast = _EMAState(fast)
        self._slow = _EMAState(slow)
        self._signal = _EMAState(signal)
        self._count = 0
        self._min_period = slow + signal       # P5-D06 / code D-08 (==15 for 6/12/3)
        self.value: float | None = None
    def update(self, x: float) -> None:
        self._fast.update(x); self._slow.update(x)
        macd_line = self._fast.value - self._slow.value   # both seeded from bar 0, defined every bar
        self._signal.update(macd_line)
        self.value = macd_line - self._signal.value
        self._count += 1
    @property
    def is_ready(self) -> bool:
        return self._count >= self._min_period
```

### RSI — Wilder RMA, ta-style single-value seed (P5-D11/D12) [VERIFIED: max_abs 2.84e-14, max_rel 9.4e-16 vs ta]
```python
class _RSIState:
    def __init__(self, window: int) -> None:
        self._n = window
        self._alpha = 1.0 / window             # Wilder RMA == ewm(alpha=1/n, adjust=False)
        self._prev_close: float | None = None
        self._up: float | None = None          # seed from FIRST gain (bar 1), NOT mean-of-first-n
        self._dn: float | None = None
        self._count = 0                         # counts DIFFS seen (bars after the first)
        self.value: float | None = None
    def update(self, close: float) -> None:
        if self._prev_close is None:            # bar 0: no diff yet
            self._prev_close = close
            return
        change = close - self._prev_close       # ta: close.diff(1)
        self._prev_close = close
        gain = change if change > 0.0 else 0.0
        loss = -change if change < 0.0 else 0.0
        if self._up is None:                    # bar 1: seed-from-first-value
            self._up, self._dn = gain, loss
        else:
            self._up += self._alpha * (gain - self._up)
            self._dn += self._alpha * (loss - self._dn)
        self._count += 1
        self.value = 100.0 if self._dn == 0.0 else 100.0 - 100.0 / (1.0 + self._up / self._dn)
    @property
    def is_ready(self) -> bool:                 # ta emits first at index window-1 (==13 for n=14)
        return self._count >= self._n           # _count is diffs-seen; window diffs ↔ ta's min_periods=window
```

### The P5-D17 convergence test shape (Model B = direct feed, no cache) [pattern]
```python
# Feed bars one-by-one; assert convergence to ta's batch output post each indicator's min_period.
def assert_converges(StateCls, ta_series, closes, min_period, atol=1e-9, rtol=1e-6):
    state = StateCls(...)
    inc = []
    for c in closes:
        state.update(c)
        inc.append(state.value if state.value is not None else float("nan"))
    ta = ta_series.values
    for i in range(min_period, len(closes)):
        if np.isnan(ta[i]) or np.isnan(inc[i]):   # compare only where BOTH defined
            continue
        assert abs(ta[i] - inc[i]) <= atol + rtol * abs(ta[i]), f"bar {i}: ta={ta[i]} inc={inc[i]}"
```

### Empirical re-baseline safety proof (run this in Plan B's verification) [VERIFIED this session]
```python
# Replicate the EXACT SMA_MACD decision logic on incremental vs ta indicator values.
# is_above: short[-1] >= long[-1]  (inclusive current)
# crossover(macd_hist, 0): macd_hist[-2] < 0 AND macd_hist[-1] >= 0
# Result on golden data: IDENTICAL signal set (274 raw fires each, zero flips).
# Nearest decision-boundary margins (post-bar-100):
#   min |macd_hist| = 7.726e-03   (vs max drift 1.7e-11) → ~9 orders of magnitude headroom
#   min |sma50-sma100| = 1.645e-01 (vs max drift 1.9e-10) → ~9 orders of magnitude headroom
# Zero bars sit within 1e-6 of either boundary → trade-SET flip effectively impossible.
```

## Runtime State Inventory

> This is a refactor of in-process compute (indicator value production), NOT a rename/migration of
> stored data or external state. There are no databases, no live services, no OS-registered tasks, no
> secrets keyed on the changed code. The "state" being changed is purely in-memory indicator math.
> Included for completeness with each category answered explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None.** No indicator values are persisted. SignalStore records intent + `strategy.to_dict()` config snapshot, never handle/indicator series (verified: spec §10.A-3, `base.py:397`). The golden `trades.csv`/`equity.csv`/`summary.json` ARE the only persisted artifacts — and they are DELIBERATELY re-frozen here (P5-D02), the one intentional exception. | Re-freeze the golden artifacts after cross-val PASS (P5-D02). No other stored data. |
| Live service config | **None — verified.** No running service, no UI-held config, no external dashboards reference this code. Pure backtest library. | None. |
| OS-registered state | **None — verified.** No Task Scheduler / cron / systemd / pm2 entries. | None. |
| Secrets / env vars | **None reference indicator code.** `.env`/`ITRADER_` vars cover DB/exchange creds (INTEGRATIONS), not indicators. `ITRADER_DISABLE_LOGS` affects logging only (MEMORY note: `make test` disables logs). | None — but run the gate as `poetry run pytest` (MEMORY: `make test` exports `ITRADER_DISABLE_LOGS` and can break caplog tests). |
| Build artifacts / installed packages | **Worktree `.venv` shadowing risk (MEMORY note).** The editable install can hide worktree edits from pytest/mypy — prepend `PYTHONPATH="$PWD"`. `ta` stays installed (now test-only). | If executed in a worktree, set `PYTHONPATH="$PWD"`; run `make test` (or the oracle) in the MAIN checkout (MEMORY: worktree `make test` aborts on missing `.env`). |

**The canonical question — after every file is updated, what still holds the old behavior?** Nothing
persistent. The ONLY downstream artifact that encodes the old indicator numbers is the frozen golden
(`tests/golden/*`), and re-freezing it is the explicit deliverable (P5-D02). There is no cache, no DB,
no service to invalidate.

## State of the Art

| Old Approach | Current (this phase) | When Changed | Impact |
|--------------|----------------------|--------------|--------|
| Per-tick full-series `ta` recompute over a sliced window | Stateful O(1) recurrence per bar | This phase (PERF-05) | O(N²)→O(N) per backtest; removes the per-tick window slice (the residual ~13% W2). |
| Readiness ≡ "window wide enough" (`len(data) < warmup`) | Per-indicator `is_ready = count >= min_period` (Nautilus `initialized` / LEAN `IsReady`) | This phase (P5-D06) | Readiness decouples from window width; supports staggered per-symbol universes (P5-D10b). |
| `evaluate` couples repopulate + dispatch (`base.py:368-373`) | "update always, emit only when ready" (G3) | This phase (P5-D13) | Indicators consume every bar; gate suppresses emission only. |
| `self.bars` master-frame slice per tick | Pushed latest bar; multi-bar history = explicit shared-cache read | This phase (P5-D13) | No DataFrame materialized per tick. |

**Deprecated/outdated as of this phase:**
- `ta` on the runtime path — `ta` has no streaming API; it survives test-only (P5-D11).
- The byte-exact-Phase-5 framing in the pre-spec ROADMAP/REQUIREMENTS-PERF-05 — superseded by P5-D01.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The golden CSV the convergence harness loads (`data/BTCUSD_1d_ohlcv_2018_2026.csv`, Close column) is byte-identical to what the run-path feed consumes through `CsvPriceStore`. | Empirical proofs | If the feed applies a transform (it does NOT appear to — `read_bars` loads the committed CSV), the convergence figures could shift. LOW risk — the cross-val gate (P5-D02) is the backstop regardless. |
| A2 | The `crossover/is_above` signal-set replication captures every decision path that can flip a trade. It models entry/exit fires but NOT the position-state de-dup (274 raw fires → 134 trades). | Re-baseline safety | If a flip occurred ONLY in a bar the de-dup would have surfaced, the raw-fire test might miss it. MITIGATED: the 9-orders-of-magnitude boundary margin makes ANY flip impossible, de-dup or not. And P5-D02's cross-val gate is the authoritative check. |
| A3 | Plan A/C structural changes (cache, window removal) preserve the 7-rule contract + cursor byte-for-byte, so ONLY indicator values re-baseline. | All | If a structural change perturbs bar timing, the re-baseline scope widens. MITIGATED: P5-D16/§4.1 mandate byte-exact preservation; the oracle's behavioral-identity test (trade dates/count) would catch it. |

## Open Questions

1. **MACD convergence-test settle offset.**
   - What we know: post-bar-100 max_abs = 1.7e-11 (perfect); but the EMA transient leaves residual
     >1e-6 out to ~bar 38 on the golden data.
   - What's unclear: whether the P5-D17 test should assert from `min_period=15` (and tolerate the first
     ~23 transient bars near the 1e-6 rel edge) or from a documented settle offset.
   - Recommendation: assert from `min_period`, but if early-transient bars trip the tolerance, add a
     small documented settle margin (e.g. `+2*slow`) — the SMA_MACD oracle is unaffected either way
     (it reads macd_hist only at bar 100+). This is a Plan B test-authoring detail, planner's call.

2. **Pair-z running-moments vs recompute-over-30 (already flagged as Claude's discretion, P5-D15).**
   - What we know: P5-D15 leaves this open; z = rolling mean/std over `z_lookback`=30.
   - What's unclear: running-moments (Welford) vs recompute-over-30 — a numerical sub-choice.
   - Recommendation: recompute-over-30 is numerically stabler for a small window and the pair is
     fit-once-dormant on the golden path (PERF-07 is deferred), so O(30)/tick is irrelevant to W1.
     Prefer recompute-over-30 unless the planner wants strict O(1) symmetry with the scalar adapters.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | all | ✓ | 3.13.x (pinned `>=3.13,<3.14`) | — |
| `ta` | test-time oracle (P5-D17) | ✓ | 0.11.0 | — (no fallback; it's the reference) |
| pandas | oracle batch compute | ✓ | 2.3.3 | — |
| numpy | float64 math | ✓ | 2.2.6 | — |
| backtesting.py | cross-val gate (P5-D02) | ✓ | 0.6.5 (pyproject) | — |
| backtrader | cross-val gate (P5-D02) | ✓ | 1.9.78.123 (pyproject) | — |
| mypy | strict gate (P5-D18) | ✓ | ^2.1.0 | — |

**Missing dependencies with no fallback:** None — every dependency is present and pinned.
**Missing dependencies with fallback:** None.

## Validation Architecture

> nyquist_validation is ENABLED (`.planning/config.json workflow.nyquist_validation: true`). REQUIRED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion=8.0`, `testpaths=["tests"]`, `--strict-markers --strict-config`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/strategy -x` (per-task indicator unit tests) |
| Full suite command | `make test` (full) — **but use `poetry run pytest tests` for caplog/log-sensitive runs** (MEMORY: `make test` exports `ITRADER_DISABLE_LOGS=true`) |
| Oracle gate | `poetry run pytest tests/integration/test_backtest_oracle.py -x` (the re-baseline; MEMORY: oracle lives in `tests/integration/`, NOT `tests/golden/` which is 0-collected artifacts) |

### Phase Requirements → Test Map (the 4 Success Criteria → concrete surfaces)

| SC | Behavior | Test Type | Automated Command | File Exists? |
|----|----------|-----------|-------------------|-------------|
| **SC1** — Incremental recurrences match `ta` post-warmup | P5-D17 convergence: feed bars one-by-one, assert convergence to `ta` batch at atol=1e-9/rtol=1e-6 for SMA/EMA/MACD/RSI | unit | `poetry run pytest tests/unit/strategy/test_indicator_convergence.py -x` | ❌ Wave 0 (NEW — the P5-D17 test) |
| **SC1b** — EMA/RSI re-baselined unit tests | Re-frozen EMA/RSI expected values (P5-D12, oracle-dark) | unit | `poetry run pytest tests/unit/strategy/ -k "ema or rsi" -x` | ❌ Wave 0 (re-baseline existing EMA/RSI tests) |
| **SC2** — SMA_MACD oracle re-baseline, behavior preserved | `test_oracle_behavioral_identity` (trade count 134 + entry/exit/side/pair EXACT) stays green; `test_oracle_numeric_values` re-frozen to new equity/PnL | integration+slow | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (re-freeze golden `tests/golden/{trades,equity,summary}` after cross-val PASS) |
| **SC2b** — Cross-validation gate confirms the new oracle | Re-run the M5-10 harness (backtesting.py + backtrader gating, 1% rel tol); confirm PASS before freezing (P5-D02) | manual/integration | (the existing `tests/golden/CROSS-VALIDATION.md` harness/runners — REUSE) | ✅ harness exists |
| **SC3** — Determinism preserved | Double-run byte-identical + `mypy --strict` clean (P5-D18) | integration + static | `poetry run pytest tests/integration/ -k determinism` ; `poetry run mypy itrader` | ✅ (determinism + mypy already gated) |
| **SC3b** — `reset()` reproduces a fresh run | `reset()` → re-feed == fresh-run output, per stateful indicator (P5-D19) | unit | `poetry run pytest tests/unit/strategy/test_indicator_reset.py -x` | ❌ Wave 0 (NEW) |
| **SC3c** — `causal` guard rejects non-causal adapters | decision path rejects a non-causal adapter; all v1 adapters `causal=True` (P5-D20) | unit | `poetry run pytest tests/unit/strategy/test_causal_guard.py -x` | ❌ Wave 0 (NEW) |
| **SC4** — W1 perf improvement (Gate (b)) | ≥5% wall-clock vs frozen baseline; same-machine A/B; re-freeze on a cool machine (P5-D03, TOOL-04) | benchmark | `make perf-w1` (prints delta vs `perf/results/W1-BASELINE.json`) | ✅ (TOOL surface exists; MEMORY: thermal drift caveat — attribute via Scalene CPU-share if throttled) |
| **SC4b** — Fixture migration keeps golden guards green | Count/date fixtures (SingleMarketBuy/ScriptedEmitter/BuyEachTickerOnce) migrated off `self.bars`, firing preserved (P5-D13a) | unit+e2e | `poetry run pytest tests/unit/strategy tests/e2e -x` | ✅ (existing fixtures; migrate in place) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/strategy -x` (fast indicator unit + convergence).
- **Per wave merge:** `poetry run pytest tests` (full suite via Poetry, NOT `make test`, to keep
  caplog tests valid) + `poetry run mypy itrader`.
- **Phase gate (before `/gsd:verify-work`):** oracle green + cross-val PASS confirmed + golden
  re-frozen + determinism double-run byte-identical + `make perf-w1` shows the locked improvement.

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_indicator_convergence.py` — the P5-D17 ta-convergence test, all four indicators (SC1)
- [ ] `tests/unit/strategy/test_indicator_reset.py` — `reset()` reproduces fresh run (SC3b / P5-D19)
- [ ] `tests/unit/strategy/test_causal_guard.py` — non-causal adapter rejection (SC3c / P5-D20)
- [ ] Re-baseline the existing EMA/RSI unit tests to the new incremental values (SC1b / P5-D12)
- [ ] Re-freeze `tests/golden/{trades.csv,equity.csv,summary.json}` AFTER cross-val PASS (SC2 / P5-D02)
- [ ] Framework install: none — pytest/mypy/ta/backtesting.py/backtrader all present.

## Security Domain

> `security_enforcement` is not set in `.planning/config.json` (treated as enabled by default), but
> this phase has **no security-relevant surface**: it is pure in-process numerical compute on a
> committed offline CSV. No auth, no sessions, no access control, no network input, no untrusted data,
> no crypto, no secrets touched. The only "input validation" relevant is the existing non-finite-z
> guard in the pair (`eth_btc_pair_strategy.py:256`) which is preserved, not added.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth surface) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | minimal | The input is a committed, trusted golden CSV; the non-finite-z guard (existing) handles degenerate windows. No new untrusted input. |
| V6 Cryptography | no | — (TA floats, not money; no crypto) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Look-ahead leakage (future bar visible to a decision) | Information disclosure | The 7-rule bar-timing contract + D-08/D-10 cursor (preserved byte-for-byte) + the new `causal` decision-path guard (P5-D20) — a structural fence for future statistical/ML adapters. |
| Silent numerical drift flipping a trade | Tampering (integrity of results) | The P5-D17 convergence test + the existing cross-val gate (P5-D02) + the empirically-proven 9-orders-of-magnitude boundary margin. |

## Sources

### Primary (HIGH confidence)
- **Live `inspect.getsource` of installed `ta` 0.11.0** (`.venv/.../ta/trend.py`, `momentum.py`) — exact
  `_sma` (rolling.mean), `_ema` (ewm adjust=False), MACD `_run`, RSIIndicator `_run` semantics.
- **Empirical convergence harness run this session** against `data/BTCUSD_1d_ohlcv_2018_2026.csv`
  (3076 bars) — all max_abs/max_rel figures, the signal-set identity result, and the boundary-margin
  measurements are computed, not assumed.
- `itrader/strategy_handler/indicators/catalog.py`, `handle.py`, `primitives.py` — current adapter +
  read surface (the conversion targets; byte-exact comparison semantics).
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, `base.py:290-376`,
  `strategies_handler.py:100-147,280-312` — the evaluate/gate/emit seam being restructured.
- `tests/integration/test_backtest_oracle.py`, `tests/golden/CROSS-VALIDATION.md` — the re-baseline gate
  (behavioral identity vs numeric values; the 3-engine 1%-tol harness).
- `.planning/phases/05-.../05-CONTEXT.md` (22 P5-D decisions),
  `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` (§1-§10).

### Secondary (MEDIUM confidence)
- [Nautilus EMA reference impl](https://github.com/nautechsystems/nautilus_trader/blob/develop/nautilus_trader/examples/indicators/ema_python.py)
  — `alpha=2/(period+1)`, seed-from-first-value (`if not has_inputs: value=value`), `initialized` when
  `count>=period`. Confirms P5-D04 matches Nautilus.
- [Nautilus indicators API](https://docs.nautilustrader.io/api_reference/indicators.html) —
  `update_raw`/`initialized`/`has_inputs` contract.
- [LEAN ExponentialMovingAverage source](https://github.com/QuantConnect/Lean/blob/master/Indicators/ExponentialMovingAverage.cs)
  + [class reference](https://www.lean.io/docs/v2/lean-engine/class-reference/classQuantConnect_1_1Indicators_1_1ExponentialMovingAverage.html)
  — LEAN's DEFAULT EMA SMA-seeds (`_initialValueSMA`); confirms the Pitfall-3 correction.
- [LEAN SimpleMovingAverage source](https://github.com/QuantConnect/Lean/blob/master/Indicators/SimpleMovingAverage.cs)
  — the running-sum SMA idiom P5-D05 follows.

### Tertiary (LOW confidence)
- None relied upon. The numerical claims are all from live source inspection + empirical measurement,
  not unverified search results.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions verified present in `.venv`.
- Recurrence correctness: HIGH — empirically verified against `ta` on the actual golden dataset, not
  from training knowledge.
- Re-baseline safety: HIGH — signal-set identity + 9-orders-of-magnitude boundary margin measured.
- Framework grounding (Nautilus/LEAN): MEDIUM — from official source/docs via web (Context7 CLI
  unavailable); the EMA seeding citations are confirmed against Nautilus source directly.
- Pitfalls: HIGH — Pitfalls 1-2 (RSI alignment/seeding) and 4 (MACD transient) were caught by running
  the code, not by reasoning.

**Research date:** 2026-06-24
**Valid until:** ~30 days (stable — `ta`/pandas pinned; the recurrences are mathematical and won't
drift; only a `ta`/pandas version bump in `pyproject.toml` could invalidate the convergence figures,
and the convergence test itself would catch that).
