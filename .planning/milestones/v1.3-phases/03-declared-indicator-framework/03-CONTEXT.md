# Phase 3: Declared-Indicator Framework - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

**IND-01 — the declared-indicator framework on the strategy base.** A strategy declares
indicators in `init()` (declaration-only recipes: `func + input + params`, computing nothing),
the base **auto-derives `warmup`/`max_window`** from the registered recipes (authors stop
hand-setting them), and **pre-evaluates** each indicator per-tick from the pushed window into
ready handles the author reads in `generate_signal` (model-B pre-eval — never passing `bars`
into the indicator). Ship free-function comparison primitives `crossover`/`crossunder` (plus
`is_above`/`is_below`, see D-01) over series, look-ahead-safe by construction. Compute model is
**stateless recompute** using the same `ta` calls as today — **byte-exact by construction**.

**Byte-exact phase.** The reference `SMAMACDStrategy`, migrated onto the framework, runs
byte-exact against the BTCUSD oracle (**134 trades / `final_equity 46189.87730727451`**); e2e
**58/58**; full suite green; `mypy --strict` clean; determinism double-run byte-identical. No
re-baseline.

**Already locked by the converged design note (NOT re-litigated here):** model-B pre-eval (not
lazy `bars`-passing model A); auto-derived `warmup`/`max_window`; `crossover`/`crossunder`
existence as free functions; stateless recompute (incremental/stateful deferred, W1-05); the
`self.indicator(...)` registration-in-`init()` shape; the re-runnable idempotent `init()` seam
built in Phase 2.

**Explicitly NOT in this phase:**
- **Stateful/incremental indicator backends (W1-05 / IND-02)** — deferred; the handle interface
  is designed to accommodate them later behind a stable interface, but every v1 backend is
  stateless recompute.
- **ewm convergence-buffer / "unstable period" mechanism + `max_window` fetch-width override**
  — deferred (see Deferred Ideas; only bites EMA/RSI-only strategies with no SMA pinning the
  window).
- **COMP-02 handler-level `update_config`** (Phase 4) — Phase 3 only makes `init()`/warmup
  re-derivation re-runnable so Phase 4 can call it.
- **SIG-01/02/03 signal-contract completion** (Phase 5) — untouched.
- **Indicator-based SL/TP** — recipe kept strategy-decoupled for a future phase to consume;
  percent-offset SL/TP stays.

</domain>

<decisions>
## Implementation Decisions

### Migration depth & comparison primitives
- **D-01:** **Full primitive-driven migration** of the reference. The SMA filter becomes
  `is_above(short_sma, long_sma)`; the MACD arms become `crossover(macd_hist, 0)` /
  `crossunder(macd_hist, 0)`. The strategy reads entirely through handles + primitives +
  auto-warmup. This means shipping a **level-comparison companion** `is_above(a, b)` /
  `is_below(a, b)` alongside the required `crossover`/`crossunder` — an in-spirit additive
  extension to the same primitives module (beyond IND-01's literal text, which names only
  crossover/crossunder), **not** scope creep / a new capability.
- **D-02:** **Inclusive-on-current-bar boundary semantics** (the byte-exact lever):
  - `crossover(a, b)` ≙ `a[-2] < b[-2] and a[-1] >= b[-1]`
  - `crossunder(a, b)` ≙ `a[-2] > b[-2] and a[-1] <= b[-1]`
  - `is_above(a, b)` ≙ `a[-1] >= b[-1]`; `is_below(a, b)` ≙ `a[-1] <= b[-1]`

  This matches the reference's existing operators exactly (`short_sma[-1] >= long_sma[-1]`;
  `MACDhist[-1] >= 0 and MACDhist[-2] < 0`; `MACDhist[-1] <= 0 and MACDhist[-2] > 0`), so the
  migration is **byte-exact by construction** rather than relying on `macd_hist` never landing
  exactly on `0.0`. Documented as a **deliberate departure from textbook-strict** (`a[-1] > b[-1]`)
  to preserve engine semantics. The second arg must accept a **scalar** (`crossover(macd_hist, 0)`),
  broadcast as `b[-1] == b[-2] == scalar`.

### Indicator handle type
- **D-03:** Pre-evaluated handles (`self.short_sma`, `self.macd_hist`, …) are a **thin
  positional-index wrapper** (backtesting.py-style): `[-1]` = last value, `[-2]` = previous,
  positional. Chosen NOT as a commitment to incremental, but as a **cheap backend-agnostic
  seam** — it keeps stateless / Kalman / online / ML-feature backends all open at ~zero cost and
  the author read-sites never change regardless of what's picked later (the design note's
  "stable interface from v1" requirement for the future stateless→incremental switch). Wraps the
  same `dropna()`'d values today → byte-exact. It is also what `crossover`/`crossunder`/
  `is_above`/`is_below` operate on (and they accept a scalar for the 2nd arg).

### Registration API & module layout
- **D-04:** Indicators are referenced by **typed adapter symbols** imported from a catalog:
  `self.indicator(SMA, "close", self.short_window)` where `SMA`/`MACDHist`/… are real symbols
  (mypy-visible, no stringly-typed name). Each adapter wraps the existing `ta` call **and**
  exposes a `min_period(params)` so the base auto-derives warmup. Extensible (new indicators
  behind the same interface) and strategy-decoupled (a future indicator-based SL/TP can consume
  the same recipe).
- **D-05:** **Package module layout (amended 2026-06-12).** A new `itrader/strategy_handler/indicators/`
  **package** holds the adapter catalog **and** the handle wrapper — matching the codebase's
  established pluggable-catalog convention (`execution_handler/fee_model/`, `slippage_model/`,
  `exchanges/` are all folder packages, not flat files):
  - `indicators/__init__.py` — barrel re-exporting the adapter symbols (`SMA`/`MACDHist`/`EMA`/`RSI`)
    and `IndicatorHandle`, so authors do `from itrader.strategy_handler.indicators import SMA, MACDHist`.
  - `indicators/catalog.py` — the four typed adapters.
  - `indicators/handle.py` — `IndicatorHandle` (moved **out of** `base.py`; it belongs to the
    indicator subsystem, not the `Strategy` ABC). Optionally also the `IndicatorAdapter` Protocol.

  The free-function primitives (`crossover`/`crossunder`/`is_above`/`is_below`) live in a **flat
  sibling** module `primitives.py` — they are a handful of pure free functions (the `core/sizing.py`
  free-function-module analog), **not** a catalog, so they stay a flat file, not a package (avoid
  `signals.py`, which collides with `SignalEvent`/`SignalIntent`). All under `strategy_handler/`,
  **tab** indentation. Two imports for authors (recipes from `indicators`, comparisons from
  `primitives`). `base.py` imports `IndicatorHandle` + adapter symbols from the `indicators` package
  (one-directional `base → indicators`; no cycle).
  *(Supersedes the original flat-`indicators.py` + `IndicatorHandle`-in-`base.py` form. The
  catalog-is-a-folder shape is more consistent with the codebase's other typed-model catalogs and
  keeps `base.py` to the `Strategy` ABC.)*

### generate_signal signature & per-tick context
- **D-06:** `generate_signal(self, ticker)` — **the `bars` parameter is dropped.** Before each
  per-ticker call the base stashes on `self`: the pre-evaluated handles, `self.bars` (the full
  raw completed-bars DataFrame — the raw-data escape hatch for ML/statistical strategies:
  feature matrices, `model.predict()`, z-scores), and `self.now` (the decision timestamp =
  `self.bars.index[-1]`, replacing today's `last_time = bars.index[-1]`). Indicator reads go
  through handles; the window stays available via `self.bars` without being baked into the
  signature (forward-compatible — read-shape independent of a window arg). Named **`self.bars`**
  (not `self.window`) to avoid collision with the integer `*_window` / `warmup` attrs. The
  handles / `self.bars` / `self.now` are **per-call context, refreshed per ticker** — fine for
  the serialized backtest path.

### v1 indicator catalog
- **D-07:** Ship **SMA + MACDHist + EMA + RSI** in v1. SMA + MACDHist are required by the
  reference (oracle-gated). **EMA + RSI are additive**, unused by the reference (so they cannot
  touch the golden), and need their own light unit tests + `min_period` conventions (`EMA(w)→w`,
  `RSI(w)→w`).

### warmup / max_window derivation (the ewm subtlety)
- **D-08:** `min_period` is defined as the **first-valid-value period only** (SMA/EMA/RSI → `w`;
  MACD → `slow + signal`), **NOT** a convergence buffer. The base computes every indicator over
  the **full `self.bars` window** (maximal ewm convergence from available history — what the
  reference already does for MACD). `warmup` (firing gate, D-15 handler short-circuit) =
  `max_window` (fetch width) = `max(min_period)` across registered recipes. For the reference:
  `MACD.min_period = 15 < SMA long_window = 100`, so `max_window` stays **100**, MACD computes
  over 100 bars = exactly today → **byte-exact**. The trap to avoid: baking a convergence buffer
  into `min_period` (could push MACD over 100, enlarge `max_window`, shift the MACD value, break
  the golden) — explicitly rejected. The genuine ewm under-convergence for future EMA/RSI-only
  strategies is **deferred** (see Deferred Ideas).

### Claude's Discretion
- **Handle wrapper interface** — exact surface (`__getitem__`/`__len__` only vs a richer
  min-period/current-value/history interface). Take the wrapper as default; finalize at planning,
  gated by `mypy --strict` + the oracle.
- **Handle binding mechanism** — `self.indicator(...)` returns a **registered handle** (initially
  empty) that the author binds to `self.short_sma`; the base re-populates that same handle object
  from `self.bars` each tick (recipe stored on the handle). backtesting.py's `self.I()` pattern.
- **Base orchestration entry point** — the handler calls a base-level wrapper (e.g.
  `evaluate`/`on_bar`) that sets `self.bars`/`self.now`, repopulates handles, then dispatches to
  the author's `generate_signal(ticker)`. Name + exact shape Claude's discretion.
- **Input spec** — a column-name string (`"close"`); all four v1 indicators are close-only.
  Multi-column indicators (ATR/Stochastic needing HLC) deferred until one is added.
- **Primitives module name** (`primitives.py` recommended), input-string default, exact
  `min_period` formulas — finalize at planning, oracle-gated.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Converged design (authoritative for this phase)
- `.planning/notes/strategy-authoring-surface-999.5c.md` — the `/gsd:explore` converged design.
  **§3 "Indicator framework (IND-01)"** is THE design (model-B pre-eval, auto-warmup, declared
  recipes); **§4 "Comparison primitives"** governs crossover/crossunder; **§"Stateful vs
  stateless"** records the stable-interface requirement behind D-03; **§"Parked for spec-time"**
  (§§1–3) are exactly the gray areas resolved here (handle type → D-03, migration depth → D-01,
  v1 set → D-07). **Read first.**

### Phase source / requirements
- `.planning/REQUIREMENTS.md` — **IND-01** (§"Indicator Framework & Strategy Authoring", the
  authoritative requirement); STRAT-01 (Phase 2, the seam this builds on).
- `.planning/ROADMAP.md` §"Phase 3: Declared-Indicator Framework" — goal + 4 success criteria
  (the pass/fail contract); §"Phase 4" (COMP-02) for the out-of-scope boundary.
- `.planning/phases/02-strategy-authoring-surface/02-CONTEXT.md` — Phase 2 decisions; the
  re-runnable idempotent `init()`/`reconfigure` seam (D-10/D-11/D-12) this phase consumes, and
  the Deferred Ideas list that scoped IND-01 here.

### Code to migrate / touch (the blast radius)
- `itrader/strategy_handler/base.py` — the `Strategy` ABC; `init()` recipe registration,
  auto-warmup derivation, the per-tick handle pre-eval + `self.bars`/`self.now` orchestration
  entry point land here. The Phase-2 `_apply_params`/`init()`/`reconfigure` seam is here.
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` — the reference; migrate onto the
  framework (register SMA/MACDHist in `init()`, read handles, drop hand-set `max_window`/`warmup`,
  full primitive-driven `generate_signal(ticker)`). In-scope, mypy-strict, **byte-exact gate**.
- `itrader/strategy_handler/strategies/empty_strategy.py` — `EmptyStrategy`; `generate_signal`
  signature migrates to `(ticker)`.
- `itrader/strategy_handler/strategies_handler.py` — `calculate_signals` call-site changes from
  `generate_signal(ticker, bars)` to the base orchestration entry point; the D-15 warmup
  short-circuit (reads `strategy.warmup`) is untouched but now reads the auto-derived value.
- `itrader/strategy_handler/signal_record.py` — verify the `to_dict()`/params-snapshot shape
  still captures the (now auto-derived) `max_window`/`warmup`.
- `tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/strategies/single_market_buy.py` — e2e
  fixture strategies; `generate_signal` signature migrates (byte-exact, **e2e 58/58**).
- NEW: `itrader/strategy_handler/indicators/` package (`__init__.py` barrel, `catalog.py` adapters,
  `handle.py` IndicatorHandle) + flat sibling `primitives.py` (D-05 amended — package layout).

### Conventions (must respect)
- `CLAUDE.md` — pure-alpha D-12 contract; **tabs** in `strategy_handler/` modules (4 spaces in
  `config/`, `tests/e2e`/`conftest`-aligned files) — match the file, never normalize.
- `.planning/codebase/CONVENTIONS.md` — money policy, naming, the documented conventions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-2 introspection/lifecycle seam** (`base.py` `_apply_params`/`init()`/`validate()`/
  `reconfigure()`) — `init()` is already a re-runnable idempotent hook called at construction and
  on every `reconfigure`. IND-01 fills it with recipe registration + adds auto-warmup
  re-derivation; the re-runnable seam is what makes Phase 4 `update_config` cheap.
- **`Strategy.buy()`/`sell()` sugar** (`base.py`) and **`SignalIntent`** return contract —
  unchanged; D-01 only changes how the firing condition is *expressed* (primitives), not how the
  signal is returned.
- **The `ta` calls themselves** — `trend.SMAIndicator(...).sma_indicator()`,
  `trend.MACD(...).macd_diff()` — reused verbatim inside the SMA/MACDHist adapters (same compute,
  same `dropna()`) so the recompute stays byte-identical.

### Established Patterns
- **Today's inline indicators** (`SMA_MACD_strategy.py::generate_signal`): SMA computed on a
  **sliced** window `bars[start_dt:].close`; MACD on the **full** `bars.close`; MACD computed
  **lazily inside** the SMA filter guard (W1-12). Model-B pre-eval computes both **eagerly** over
  the full window every tick — **value-identical** (same MACD value, just eager vs lazy; the SMA
  tail value is slice-independent), proven by code review + the byte-exact oracle ONLY (no new
  SMA_MACD test). Record this for the planner: the W1-12 lazy optimization is intentionally
  replaced by eager pre-eval, byte-identical.
- **D-15 warmup short-circuit** (handler `calculate_signals`): guards on `strategy.warmup` so
  `generate_signal` is only called with ≥ warmup bars. Handle reads (`[-1]`/`[-2]`, crossover's
  `[-2]`) therefore always have ≥2 values — relied upon, not re-checked.
- **Tabs** throughout `strategy_handler/`.

### Integration Points
- `StrategiesHandler.calculate_signals` is the one cross-domain seam: it changes from calling
  `generate_signal(ticker, bars)` to calling the base orchestration entry point (sets
  `self.bars`/`self.now`, repopulates handles, dispatches). Per-ticker, per-strategy; portfolio
  fan-out happens AFTER `generate_signal` returns and never re-enters it.
- Indicators are declared **ticker-agnostic** in `init()` (a recipe: "SMA of close, window 50")
  and **evaluated per-ticker** against that ticker's window right before each call — the natural
  multi-ticker model, matching today's per-ticker inline compute.

</code_context>

<specifics>
## Specific Ideas

- Target authoring shape (from the design note §3, now fully primitive-driven per D-01/D-06):
  ```python
  def init(self):
      self.short_sma = self.indicator(SMA, "close", self.short_window)
      self.long_sma  = self.indicator(SMA, "close", self.long_window)
      self.macd_hist = self.indicator(MACDHist, "close", self.fast_window,
                                      self.slow_window, self.signal_window)

  def generate_signal(self, ticker):              # no bars param (D-06)
      if is_above(self.short_sma, self.long_sma):           # SMA filter (level)
          if crossover(self.macd_hist, 0):  return self.buy(ticker)
          if crossunder(self.macd_hist, 0): return self.sell(ticker)
      return None
  ```
- `self.bars` / `self.now` remain available in `generate_signal` for ML/statistical strategies
  that read the raw window directly (no indicator handle needed).

</specifics>

<deferred>
## Deferred Ideas

- **[TODO — owner-requested] ewm convergence-buffer / "unstable period" mechanism + overridable
  `max_window` fetch-width.** The deliberately-rejected D-08 option-2, captured for proper later
  implementation. For ewm/infinite-memory indicators (EMA/RSI/MACD) the value keeps converging
  with more history; a strategy that uses EMA/RSI **without** an SMA pinning the window would be
  under-converged at `max_window = max(min_period)`. Add a per-indicator stabilization/unstable-
  period buffer (cf. TA-Lib `TA_SetUnstablePeriod`) and/or an explicit `max_window` fetch-width
  override so fetch can exceed the firing gate. Out of scope for byte-exact Phase 3 (does not bite
  the reference: SMA pins the window at 100 and MACD already runs on the full window). → future
  phase / backlog.
- **Stateful/incremental indicator backends (W1-05 / IND-02)** — O(1) per-tick update behind the
  same stable handle interface (D-03 was chosen to keep this open). Byte-exactness risk is
  structural (`ewm(adjust=True)` vs `adjust=False` recursion disagree during warmup) → must be
  validated value-identical or accept a re-baseline. → future phase.
- **Multi-column indicators** (ATR/Stochastic needing HLC) — the input spec is a single
  column-name string in v1 (D-04/discretion); extend when the first multi-input indicator lands.
- **Indicator-based SL/TP** — the recipe is kept strategy-decoupled (design note §6) so a future
  phase can drive SL/TP off an indicator; percent-offset SL/TP stays for now.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 3-declared-indicator-framework*
*Context gathered: 2026-06-12*
