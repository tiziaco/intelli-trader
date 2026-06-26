# Phase 5: Stateful Indicators + Shared Bar Cache - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

> **Tag scheme:** decisions below are tagged `P5-DNN` (phase-scoped) to avoid collision with the
> load-bearing `D-NN` tags already in the indicator/strategy code (e.g. code `D-01` = primitives,
> `D-04` = typed adapters, `D-08` = min_period). Planner MUST cite the `P5-DNN` tags in
> must_haves/truths/objective.

<domain>
## Phase Boundary

Replace the per-tick full-series `ta` indicator recompute with **stateful, incremental
indicators** (O(1)/tick) on a **shared recent-bars feed**, then cut the per-tick master-frame
window slice. This is a **structural/architectural refactor that deliberately RE-BASELINES the
SMA_MACD oracle** (it is NOT the byte-exact perf tweak the pre-spec ROADMAP entry described — the
design spec supersedes; see P5-D01).

**Design of record (supersedes the ROADMAP Phase 5 entry):**
`docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` (§1–§10, esp. the §10 addendum).

Delivered as **3 plans, A→B→C** (data layer → stateful indicators + re-baseline → pair migration +
drop per-tick window). Plan A is plannable byte-exact in parallel; **only Plan B is blocked by the
G2 seeding decision (P5-D04)**.

**In scope:** stateful incremental indicators (drop `ta` on the runtime path); feed-centric
indicator model with per-symbol/per-pair state; shared recent-bars feed (newest-bar + registration
interface); per-tick `self.bars` removal; pair β/z migration; oracle re-baseline + cross-validation
freeze; `reset()` + `causal` guard surfaces.

**Out of scope (deferred, accommodated not built):** the full multi-timeframe consolidator, the
deep capacity-derived multi-bar cache, the synthetic-spread instrument, live backfill wiring, the
optimizer/parameter-sweep module, concrete Kalman/Hawkes adapters, the screener subsystem. Each has
a tracked to-do (see Deferred Ideas).
</domain>

<decisions>
## Implementation Decisions

### Re-baseline & oracle governance
- **P5-D01 — The spec supersedes the ROADMAP "byte-exact" mandate; Phase 5 RE-BASELINES the oracle.**
  The pre-spec ROADMAP/PROJECT/STATE describe Phase 5 as byte-exact ("change the numbers nowhere",
  Gate (a) = `134 / 46189.87730727451`), the v1.5 milestone invariant honored by Phases 1–4.
  Dropping `ta` on the runtime path (P5-D11) forces a re-baseline (SMA running-sum ULP + EMA
  single-seed transient). This breaks the byte-exact invariant **for Phase 5 only**, deliberately.
  ROADMAP/PROJECT/STATE are updated this session to record the carve-out.
- **P5-D02 — Acceptance bar that freezes the new oracle.** Reuse the EXISTING cross-validation gate
  (`tests/golden/CROSS-VALIDATION.md`, M5-10): backtesting.py 0.6.5 + backtrader 1.9.78.123
  **gating** at 1% relative tolerance (nautilus non-gating). Re-run → confirm PASS → freeze the new
  trade log + equity as the oracle, regression-lock. **Expected movement:** firing tick preserved
  (warmup=100, P5-D06) so trade dates/count (134) stay identical and only numeric equity/PnL drift
  at ULP scale. **If the trade SET moves** (a borderline ULP crossover flips), that requires
  **explicit cross-val corroboration that the new set is correct before freezing** — never a silent
  update. The oracle test already separates behavioral identity (`test_oracle_behavioral_identity`,
  trade keys) from numeric values (`test_oracle_numeric_values`).
- **P5-D03 — Gate (b) (W1 perf) stays.** A measurable W1 improvement vs the prior re-frozen
  baseline, re-frozen as the new locked reference. Attribute via same-machine A/B per the
  established method; re-freeze on a cool machine (W1 baseline is thermally sensitive — see
  `04-PERF-ATTRIBUTION.md`).

### Indicator numerics — G2 (THE re-baseline drivers; sets the new reference)
- **P5-D04 — EMA/MACD seed = seed-from-first-value (`adjust=False`).** `y[0]=x[0]`, seeded ONCE at
  the global first bar, `α=2/(n+1)`. Matches today's `ta` semantics + Nautilus + LEAN default EMA,
  and keeps the §10.H `ta`-convergence test valid (same seeding family). NOT SMA-seed. **This is the
  G2 BLOCKER decision — Plan B is gated on it.**
- **P5-D05 — SMA = running-sum O(1) (LEAN-style).** `sum += new − evicted`; the evicting value
  retrieved from the indicator's own small ring (Model B, P5-D08). Accept the (negligible-on-golden,
  ~1e-9) ULP accumulation drift. Chosen over the numerically-stabler fresh-windowed-sum (Nautilus)
  for strict O(1) + LEAN idiom; keeps spec §4.2/§10.H "running-sum" as written. (Computation is
  incremental; the ring is a lookup for the departing value, never re-summed.)
- **P5-D06 — Readiness = per-indicator `is_ready = count >= min_period`** (Nautilus `initialized` /
  LEAN `IsReady`). Emit when `all(h.is_ready)`. `min_period` UNCHANGED (code D-08: SMA→window,
  EMA→period, MACD→slow+signal). For SMA_MACD that's the 100th bar → byte-identical firing tick →
  re-baseline is value-drift only, not behavioral. NO convergence buffer.

### Indicator architecture model — Model B (feed-centric, amends spec §10.H)
- **P5-D07 — Feed-centric model (Nautilus/LEAN), NOT cache-centric.** Indicators are fed values via a
  pure push `update(...)`; they hold their OWN minimal bounded buffers and do NOT read the shared
  cache. **This AMENDS spec §10.H** ("SMA reads evicting value from shared cache / no private ring")
  and the §10.G capacity premise (cache capacity now keys off raw-bar consumers, not indicator
  `min_period`). Rationale: encapsulation, isolated testability (the P5-D17 `ta`-convergence test
  feeds bars directly — no cache needed), portability, live parity; it is what both first-class
  engines do.
- **P5-D08 — Per-indicator internal buffers (the working set, bounded):** EMA/MACD/RSI hold
  scalar-only state (no window buffer). SMA holds a small ring sized to its window solely to read the
  evicting value. Pair β holds the oldest-250 window for a ONE-TIME fit; pair z holds a bounded
  `z_lookback` (30) window. Handle output-history buffer (`handle[-k]` reads) defaults to depth 2,
  declared per-handle; SMA_MACD reads `[-1]`/`[-2]` only, so default suffices.
- **P5-D09 — `update()` signature.** Single-input indicators: `update(bar)` extracts their
  `input_col` (e.g. `close`). Multi-input indicators are first-class: the pair β/z indicator's update
  receives BOTH legs' values for the tick (e.g. `update(bar_A, bar_B)`/a small struct). Exact arg
  form is the planner's to finalize.

### Per-symbol / per-pair fan-out (the multi-instrument requirement)
- **P5-D10 — Stateful indicators are per-(symbol[, timeframe]); a strategy fans out one indicator-set
  per trading unit.** REQUIRED because stateful state can't be shared across symbols the way the old
  stateless per-tick recompute did. The framework auto-fans-out: author declares once
  (`self.indicator(SMA,'close',window)` in `init()`), the framework instantiates one stateful set per
  symbol, keyed internally; handler routes `update(ticker,bar)` to that ticker's set,
  `generate_signal(ticker)` reads it. Author surface = same code as today (LEAN/Nautilus pattern).
  Multi-pair: per-PAIR β/z state keyed by canonical `(legA,legB)` identity (**Pattern 1**; the
  synthetic-spread-instrument Pattern 2 is deferred). Preserves the multi-instrument/multi-pair
  performance benchmark.
- **P5-D10a — Lazy instantiation.** A symbol's handle-set is created on its FIRST bar (keyed lazily),
  not eagerly from a declared ticker list. Supports dynamic universes (the deferred screener case)
  with no special path; a symbol added mid-run warms from its own first bar.
- **P5-D10b — Independent per-symbol readiness.** Each symbol's handles warm from that symbol's own
  first bar; `generate_signal(ticker)` emits only when THAT ticker is ready. One symbol being ready
  never gates another (correct for staggered universes).
- **P5-D10c — Missing/gap bar = no update (causality).** When `event.bars` has no entry for a symbol
  this tick, that symbol's indicators DON'T update (state frozen, never fabricated); `is_ready` count
  increments on REAL bars only. Matches Nautilus + LEAN (update only on real bars) + iTrader's
  existing absent-by-contract skip + the look-ahead contract (the FEED owns bar existence). Any
  future fill-forward belongs at the FEED layer (LEAN-style feed option), never the indicator.

### Indicator catalog conversion (ta-drop)
- **P5-D11 — Drop `ta` on the runtime path; hand-write O(1) recurrences.** SMA (running-sum), EMA
  (`y+=α(x−y)` seed-from-first), MACD (two EMAs + signal EMA), RSI (Wilder smoothing). `ta`/pandas
  retained ONLY as a test-time oracle (P5-D17), never called per tick. This is the CAUSE of the
  re-baseline, not a side effect.
- **P5-D12 — Convert ALL FOUR indicators** (incl. oracle-dark EMA/RSI), re-baseline EMA/RSI unit
  tests. Uniform stateful surface + live parity for any future strategy. EMA/RSI are blessed via the
  `ta`-convergence test (`ta` batch IS their reference); no external cross-val for them (they're off
  the frozen SMA_MACD oracle).

### Evaluate/update seam (strategy ↔ handler contract — Plan C)
- **P5-D13 — Remove the per-tick `self.bars` master-frame slice ENTIRELY (Option B).** New uniform
  contract: handler pushes the latest completed bar → `strategy.update(ticker,bar)` updates that
  ticker's handles every tick → gate on `strategy.is_ready(ticker)` (replaces `len(window)<warmup`) →
  `generate_signal(ticker)`. `self.now=event.time`. NO `self.bars`, NO `feed.window()` slice on the
  per-tick path. Decouples the current repopulate+dispatch coupling (`base.py:368-373`). Multi-bar
  history, where genuinely needed, is an explicit shared-cache read — not a fresh slice.
- **P5-D13a — Migrate frame-needers off `self.bars`.** The pair is migrated by Plan C regardless
  (P5-D15). The only net-extra work is migrating the zero-handle count/date TEST FIXTURES
  (SingleMarketBuy/ScriptedEmitter/BuyEachTickerOnce) off `self.bars` (→ bar-count / latest-bar),
  **preserving their count/date firing** so the e2e/integration golden guards stay green.
- **P5-D14 — Handler loop shape (planner fills mechanics):** for each ticker with a bar in
  `event.bars` → `strategy.update(ticker,bar)` → `if strategy.is_ready(ticker)` → `generate_signal`;
  drop `feed.window()` + the len-gate.

### Pair migration — G4 (Plan C)
- **P5-D15 — Pair onto the §4.2 shapes.** β = refitting/**fit-once-frozen**: fits the OLDEST 250
  buffered bars at first-ready, then FROZEN (re-fitting on the slid buffer would break parity). z =
  bounded-window (rolling mean/std over `z_lookback`=30; running-moments vs recompute-over-30 is a
  Plan-C numerical sub-choice). Strategy readiness = β fitted AND z buffer full = 280. Folds the old
  `beta_warmup+z_lookback` gate + the `max_window` validate into the pair's own buffer sizing.

### Shared bar feed (Plan A) + G1 + G5
- **P5-D16 — `BarFeed` owns the shared recent-bars API; Plan A builds newest-bar + the registration
  INTERFACE, DEFERS the deep multi-bar cache.** Under Model B (P5-D07) indicators + pair self-buffer,
  so NO current consumer needs deep history. Plan A ships: the newest-bar provision + the
  consumer-registration/capacity-derivation INTERFACE (mirrors
  `universe/instruments.py::derive_instruments`, keyed off raw-bar consumers). The deep
  capacity-derived multi-bar buffer is deferred to the first raw-bar consumer (screener / raw-history
  strategy) — tracked to-do.
- **P5-D16a — G5: unify the newest-bar pass.** One per-symbol-per-tick walk computes "newest bar per
  symbol," feeding BOTH the BarEvent payload AND the cache newest-row write (and mark-to-market) — not
  two parallel walks. One `BarEvent`/tick with a `{ticker: Bar}` payload, unchanged.
- **P5-D16b — G1: update-trigger seam, interface-only.** Defined as "a consolidator emits on
  `(symbol,timeframe)` bucket-close → drives `indicator.update()`," but the interface MUST NOT
  hardcode per-base-tick updates. Wiring asserts `base_timeframe ≤ min(timeframe)`. For golden
  SMA_MACD (`1d==base==1d`) the trigger collapses to "every tick." The full multi-timeframe
  consolidator is deferred — tracked to-do.

### Testing
- **P5-D17 — `ta`-convergence test oracle (§10.H).** Feed bars one-by-one to each stateful
  indicator; assert convergence to `ta`'s batch output **post-warmup** (from `min_period` onward,
  skipping the legitimately-different pre-ready region) at a **generous tolerance** (~1e-9 abs /
  1e-6 rel) — proving "no divergence bug," NOT byte-exactness (the frozen oracle is the byte-lock).
  Covers ALL FOUR indicators (Model B makes this a direct feed — no cache to stand up).
- **P5-D18 — Determinism gate unchanged.** Double-run byte-identical + `mypy --strict` clean stay
  green (indicators are deterministic).

### Optimizer / causality surfaces (build now)
- **P5-D19 — `reset()` built now.** Each stateful indicator implements `reset()` (clears scalar/ring
  state + readiness count + output buffer; clears the per-symbol fan-out map). "The one discipline a
  future sweep must honor." A test asserts `reset()`→re-feed reproduces a fresh run. The deferred
  optimizer just calls it.
- **P5-D20 — `causal` flag + decision-path guard built now.** Adapters declare `causal`; the decision
  path REJECTS non-causal adapters (smoothers, centered windows). All v1 adapters `causal=True`.
  Structural look-ahead fence for the future statistical/ML indicators the design opens the door to.

### Author surface
- **P5-D21 — Strategy-author declaration surface preserved.** `self.indicator(SMA,'close',window)` in
  `init()` + handle-only `generate_signal` reads (`is_above`/`crossover`/`[-1]`/`[-2]`, code
  D-01/D-02 byte-exact primitives) stay as today (spec §4.2). What changes underneath: value
  PRODUCTION (stateful `update` vs `ta`-recompute), the handler→strategy push contract (P5-D13), and
  the per-symbol fan-out (P5-D10, transparent to the author).

### Spec amendments (explicit — so planning doesn't reopen the wrong baseline)
- **P5-D22 — This discussion AMENDS the spec at three points:** (1) §10.H — SMA holds its own ring
  (feed-centric Model B), NOT a shared-cache evicting-value read; (2) §10.G/§4.1 — shared-cache
  capacity keys off raw-bar consumers (indicators self-buffer), and the deep cache is deferred; (3)
  §4.2 wording — SMA running-sum is confirmed (P5-D05), but the Plan-A cache role is thinner than the
  spec implied. Everything else in the spec stands as written (P5 follows §10.F "what did NOT
  change").

### Claude's Discretion (planner-territory — intentionally NOT locked)
- Exact `IndicatorHandle` method signatures, the per-symbol handle-storage container type, mypy
  `--strict` generics on the new adapter Protocol, the pair-z running-moments-vs-recompute sub-choice,
  and the Plan A/B/C task-boundary breakdown. These are left to `/gsd:plan-phase`; over-specifying
  them here would constrain the planner without adding correctness.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design of record (supersedes the ROADMAP Phase 5 entry)
- `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` — the full design; §1–§9 + the
  §10 pre-planning addendum (§10.A–H). **This CONTEXT amends §10.H, §10.G/§4.1, and §4.2's cache
  framing (P5-D22) — read CONTEXT's amendments alongside it.**

### Oracle & cross-validation (the re-baseline gate)
- `tests/integration/test_backtest_oracle.py` — the run-path oracle test (behavioral identity vs
  numeric values); the SMA_MACD numbers re-baseline here.
- `tests/golden/CROSS-VALIDATION.md` — the gating cross-val evidence (backtesting.py + backtrader,
  1% rel tol); the re-baseline is validated against this harness (P5-D02).
- `tests/integration/_oracle_harness.py` — the in-process oracle generator.

### Indicator / strategy code (the surfaces being converted)
- `itrader/strategy_handler/indicators/catalog.py` — the `ta`-backed adapters (SMA/MACDHist/EMA/RSI)
  being converted to hand-written recurrences (P5-D11/D12).
- `itrader/strategy_handler/indicators/handle.py` — `IndicatorHandle` (repopulate→update,
  `[-1]`/`[-2]` read retained).
- `itrader/strategy_handler/primitives.py` — `crossover`/`is_above` (code D-02 byte-exact, UNCHANGED).
- `itrader/strategy_handler/base.py` (`evaluate` seam ~`:300-380`, `_run_init` warmup derivation) —
  the repopulate+dispatch decoupling (P5-D13).
- `itrader/strategy_handler/strategies_handler.py` (`:110-145` single-leg, `:294-301` pair) — the
  handler loop restructure (P5-D14) + the per-tick `feed.window()` removal.
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` — the oracle strategy (author surface
  preserved, P5-D21).
- `itrader/strategy_handler/pair_base.py`, `strategies/eth_btc_pair_strategy.py` — the pair migration
  (P5-D15).
- `itrader/price_handler/feed/bar_feed.py` — `BarFeed` promotion/rename + shared-bar API + the 7-rule
  bar-timing contract + D-08/D-10 cursor (P5-D16); `generate_bar_event`/`current_bars` (G5 unify).
- `itrader/universe/instruments.py::derive_instruments` (`:170`), `universe/membership.py` (`:44`) —
  the capacity-derivation mirror pattern (P5-D16).

### Perf attribution
- `.planning/phases/04-hot-path-discipline/04-PERF-ATTRIBUTION.md` — W1 baseline provenance + thermal
  caveat (Gate (b), P5-D03).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The typed-adapter catalog (`catalog.py`, code D-04) + `IndicatorHandle` + the free-function
  primitives (`primitives.py`, D-01/D-02) are the surfaces to convert in place — the read side stays;
  only value production changes.
- `derive_instruments`/`derive_membership` (`universe/`) are the exact mirror pattern for the
  consumer-registration/capacity-derivation function (don't invent a new mechanism).
- The existing cross-val harness (`tests/golden/CROSS-VALIDATION.md` + runners) is the re-baseline
  gate — reuse, don't rebuild.

### Established Patterns
- Queue-only cross-domain writes; injected read-models for reads (`BacktestBarFeed`,
  `PortfolioReadModel`) — the shared-bar feed follows the read-model seam.
- 7-rule bar-timing contract + D-08/D-10 monotonic cursor = the single home of look-ahead safety;
  Plans A/C must preserve them byte-for-byte (the structural parts stay byte-exact; only the
  indicator VALUES re-baseline).
- Tabs in `strategy_handler/` handler modules; 4-spaces in `price_handler/feed/` + `core/` — match
  the file.

### Integration Points
- TIME→BAR route (`full_event_handler._routes`): the BarEvent factory (G5), `strategies_handler`
  (the update/gate/emit restructure), mark-to-market (already optimal, reads `BarEvent.bars`).
- `__init__.py` singletons (`config`/`logger`/`idgen`) — unchanged.
</code_context>

<specifics>
## Specific Ideas

- The user explicitly prioritizes **architecturally-correct + framework-aligned (Nautilus/LEAN)**
  choices over strict golden-artifact preservation — this drove the re-baseline acceptance, Model B
  (feed-centric), and the framework-grounded answers throughout.
- The user runs a **multi-instrument / multi-pair-in-one-strategy performance benchmark** — P5-D10
  (per-symbol/per-pair fan-out) is load-bearing for it.
- Three open spec gaps were intentionally CONFIRMED-as-settled during discussion (not reopened): G3
  (warmup-emit), G4 (pair shapes), G5 (newest-bar unify).
</specifics>

<deferred>
## Deferred Ideas

Each has a tracked to-do under `.planning/todos/`:

- **Full multi-timeframe consolidator** (register-at-base/consolidate-up, §10.G) —
  `.planning/todos/multi-timeframe-consolidator.md`. Phase 5 ships interface + golden-collapsed only.
- **Deep capacity-derived multi-bar shared cache** (raw-history depth, §4.1/§10.G) —
  `.planning/todos/deep-shared-bar-history.md`. Lands with the first raw-bar consumer (screener).
- **Live backfill through the `update(bar)` path** (single code path, §10.D-3) —
  `.planning/todos/live-backfill-through-update.md`. Belongs to N+4 Live Trading Readiness; **also to
  be added as a ROADMAP backlog item this session.**
- **Synthetic / spread instrument** (multi-pair Pattern 2 unification) —
  `.planning/todos/synthetic-spread-instrument.md`. Future Instrument/Cache unification; spec §2
  non-goal this phase.

Also accommodated-not-built (spec §6, no separate to-do — design already admits them): optimizer /
parallel-run harness, concrete Kalman/Hawkes adapters, the screener subsystem.

### Adjacent (out of scope, independently addressable)
- **Per-bar logging (~22% of W2)** — real but NOT this phase (spec §10.C); a separate quick task with
  a one-shot per-line profile to confirm the dominant call site first.

</deferred>

---

*Phase: 5-Incremental Indicators (Stateful Indicators + Shared Bar Cache)*
*Context gathered: 2026-06-24*
