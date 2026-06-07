# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

The **backtest validity, fills & data pipeline** phase. Fix the correctness of the backtest
itself across five locked requirements (M5-01…M5-05): remove resampling look-ahead and the
limit-fill slippage violation with a documented bar-timing convention (#21), replace the
per-tick pandas payload with an immutable `Bar` struct (#3/FR1), precompute resampled frames
out of the hot loop (#4), fix the fee/slippage models (#28/PERF1), and split the price handler
into Provider/Store/Feed seams with an offline-deterministic, physically read-only run path
(#30, #27 price seam, FR6/FR7/FR8, PERF4).

**Golden-master position:** This is the FIRST phase sanctioned to change results. The
byte-exact behavioral + numerical oracle assertions (law since Phase 3) WILL break by design
when validity fixes land. The final sanctioned numerical re-baseline remains Phase 8 (post
cross-validation); this phase operates under the hybrid working discipline in D-15…D-17 below.

**Boundary with adjacent milestones (do NOT pull forward):**
- **M5b (Phase 7)** owns: sizing-policy completion (M5-06), `RiskManager.check_cash`,
  `calculate_signal` contract enforcement, reporting/metrics (#38 — including the derived
  slippage trade-log column, D-08), universe stub (#33 — including the fate of PriceHandler's
  symbol methods), **DEF-01-C margin/liquidation** (routed there this discussion, D-07), and
  the formal TC2/TC4/TC6 coverage audit (this phase ships test-with-code; Phase 7 gap-fills).
- **Phase 8 (M5c)** owns: external cross-validation vs backtesting.py + backtrader and the
  final frozen numerical reference.
- **D-sql / D-oanda / D-live** own: the SQL store backend, CCXT/OANDA provider rework, live
  streaming. Their existing code RELOCATES behind the new seams untouched (D-21) — quarantined,
  not reworked, not deleted.
- **D-screener** owns: actually consuming the megaframe; this phase fixes and tests the
  megaframe as a Feed method (D-24) so D-screener later wires into a working API.

</domain>

<decisions>
## Implementation Decisions

### Bar-timing & fill convention (M5-01, #21)
- **D-01: Next-bar-open market fills.** Decide on close of bar N → market orders fill at the
  open of bar N+1. The industry-standard look-ahead-free convention and the DEFAULT in both
  backtesting.py and backtrader — Phase 8 cross-validation becomes like-for-like.
- **D-02: Completed bars only in resampled windows.** Higher-timeframe windows contain only
  fully-closed bars (open-time stamped, `label='left'`/`closed='left'`, upper bound exclusive
  at decision time; the forming bar is invisible). The same-timeframe branch gets the identical
  "last closed bar ≤ T" rule so both branches agree. Matches backtesting.py, backtrader, AND
  Nautilus (`on_bar` fires only at bar close). Look-ahead safety is an ENGINE invariant
  enforced in the Feed and regression-tested there — never a strategy responsibility.
- **D-03: Hard limit bound + gap-aware stops.** Limits fill at limit-or-better (gap-throughs
  fill at the better open); slippage is NEVER applied to limit fills. Stops become market-like
  on trigger: fill at stop price, or at the worse open on gap-through; slippage may apply to
  stops. Removes the `simulated.py` post-matching slippage multiplication that violated the
  engine's own invariant. Real-exchange semantics, matched by all three reference engines.
- **D-04: Open-time stamping kept, documented + asserted.** Bars stay stamped by open time
  (Binance kline / CCXT / TradingView convention; what the Phase 8 external engines will see).
  The documented invariant: the tick at T processes the bar stamped T at its close; fills land
  at the bar stamped T+1tf at its open. Nautilus close-time stamping acknowledged and rejected
  as churn (equally look-ahead-safe, shifts every oracle timestamp for no validity gain).
- **D-05: Equity curve stays close-marked.** Equity at bar T = cash + positions valued at T's
  close (the Decimal Bar close). Unchanged behavior, now explicit in the documented timing
  contract and asserted alongside the look-ahead tests. Matches all three reference engines.

### Fill realism & fee/slippage (M5-04, #28, PERF1)
- **D-06: Partial-fill scaffolding REMOVED.** Full-quantity fills become the documented
  contract; the misleading `fill_quantity` plumbing is deleted. Matches the reference engines'
  defaults; one daily bar provides no intrabar liquidity to calibrate partials against.
- **D-07: DEF-01-C routes to Phase 7 (M5b) risk layer.** Margin/short-solvency is an
  admission-time risk check, not a fill mechanic — it belongs with `RiskManager.check_cash` +
  sizing policy (M5-06). This phase only documents the current behavior (un-liquidated short
  can drive equity negative; blessed into the M1 oracle).
- **D-08: FillEvent stays minimal — executed price + commission only** (FIX/Nautilus shape).
  Principle locked: fee is an execution FACT (must travel on the fill report); slippage is a
  MEASUREMENT (derived analytics). M5b reporting computes slippage per trade vs the
  decision-bar close as its own trade-log column (fee-style attribution, derived). Accepted
  nuance: that column measures total execution cost (overnight gap + model slippage); model
  slippage alone is unit-tested at the model level.
- **D-09: Golden reference run stays zero-fee / zero-slippage.** The oracle remains a pure
  engine-correctness reference: every M5a diff attributable to timing/fill fixes alone, and
  Phase 8 cross-validation is trivially replicable. Fee/slippage model fixes get unit tests,
  not oracle exposure.
- **D-10: Fee-model lineup pruned to zero / percent / maker_taker.** `TieredFeeModel` is
  DELETED (provably never worked — its only construction path crashes with a `TypeError`).
  The three survivors are fixed and unit-tested. Matches the Phase 3–5 dead-code discipline.
- **D-11: Maker/taker classification: resting limit fills = maker; market orders and triggered
  stops = taker.** `_emit_fill` passes real order context instead of the hardcoded
  `order_type="market"`. Universal exchange rule (Binance, FIX LastLiquidityInd, Nautilus
  liquidity_side).
- **D-12: Execution internals go Decimal-native NOW.** Fee models, slippage models, and
  MatchingEngine math are retyped Decimal end-to-end using the `core/money` quantization
  policy; the Phase 5 D-22 engineered-inert float boundaries die. M5a is the only sanctioned
  phase for this — Phase 8 freezes Decimal-native numbers. The disagreeing fee/slippage ABC
  money signatures unify; slippage validation raises typed exceptions instead of silently
  returning 1.0 (per requirement). `time.sleep(0.1)` connect latency removed from the backtest
  path (locked by M5-04, no discussion needed).
- **D-13: Market orders rest in the unified MatchingEngine book.** Their trigger rule is
  "fill at next bar's open, unconditionally" — ONE matching path for market/stop/limit, one
  source of truth for resting state, OCO/bracket interplay handled in one place. The BAR
  cascade order (portfolios → execution → strategies) already guarantees orders from bar N
  first meet data at bar N+1.

### Bar struct & data pipeline (M5-02, M5-03, M5-05, #3, #4, #30)
- **D-14: `Bar` OHLCV fields are Decimal**, converted once at construction
  (`Decimal(str(x))` — exact for micro-prices like 0.000005 where float64 is not; user probed
  Nautilus fixed-point `Price`/`Quantity` and Binance string-price APIs before locking).
  Companion rule: **prices and quantities are NEVER rounded to the cash quantum** — the money
  quantization policy applies only to cash/PnL at the quote-currency boundary (per-instrument
  precision preserved by design, no Instrument model needed yet).
- **D-15: `BarEvent.bars: dict[str, Bar]` — current bar only.** One immutable Bar per ticker;
  the `hasattr` ladders and `get_last_*` methods collapse to `bars[ticker].close`. Strategies
  needing history get windows from the Feed. Event = fact, feed = query.
- **D-16: Full Provider/Store/Feed seams now, backtest implementations only.** All three
  Protocols + the package layout land this phase; implemented and tested: CSV-loaded store +
  look-ahead-safe BarFeed with frames precomputed once per (ticker, timeframe) at load and
  sliced per tick (#4 — no `resample` in the hot loop). Dormant CCXT/SQL/streaming code
  RELOCATES behind the seams as untouched deferred modules. The run path is physically
  read-only and errors loudly on missing data (FR6); bare `except:`→`None` accessors fixed to
  raise (FR7). Ingestion stays a stub entry point (offline pipeline, never in the run loop).
- **D-17: Feed windows are float64 pandas frames** — indicators compute at native pandas speed
  (Nautilus does the same: indicators on float, money on fixed-point). The Decimal Bar is the
  only thing that touches money. Documented as the analytics/money type boundary.
- **D-18: `PriceHandler` is DELETED.** Trading systems wire Store + Feed directly;
  universe/strategies take the Feed. Rewiring paid once this phase while results are allowed
  to change. Matches the deletion discipline (saga, locks, ExecutionResult precedent).
- **D-19: Megaframe becomes a BarFeed method, fixed + tested.** FR8 bugs fixed (tz-naive
  symbol drop, `pd.concat` key misalignment), unit-tested with a multi-symbol fixture despite
  the single-ticker golden run. D-screener later wires into a working API.
- **D-20: Strategy data access is PUSH.** `StrategiesHandler` queries the Feed per declared
  `(timeframe, max_window)` and hands `calculate_signal` its window + current Bar — strategies
  stay pure functions of data, look-ahead safety enforced in exactly one place. Industry
  framing locked: strategies never choose the as-of time (backtesting.py truncated views,
  backtrader relative indexing, Zipline/Nautilus time-scoped portals all enforce this
  structurally). A guarded pull portal can layer onto the Feed later (M5b+) without breaking
  push.

### Oracle discipline & sequencing (phase gate)
- **D-21: Hybrid oracle discipline — inert-proven vs explained re-freeze.** Workstreams are
  classified up front. Structural work (Bar struct, precompute, price split, Decimal retype
  under zero costs) must reproduce the CURRENT oracle byte-exact — proven inert, Phase 3 D-17
  style; any diff in structural work is a BUG. Validity fixes (next-open fills, look-ahead
  removal, limit-slippage fix) re-freeze the working reference (behavioral + numerical
  together) in the same commit with a documented expected-diff note (what changed, why, trade
  count, equity, spot-checked trades). Suite green at every commit; every numeric change in
  history has a name. Phase 8 still owns the final sanctioned baseline.
- **D-22: Structural first, validity last.** All inert workstreams land and prove
  byte-exactness against today's oracle BEFORE any result-changing fix lands — maximum
  tripwire coverage. Exact wave/plan ordering within each group is planner discretion.
- **D-23: Blocking owner sign-off per re-freeze.** Each result-changing re-freeze pauses at a
  checkpoint: the user reviews the expected-diff note before the new reference commits
  (Phase 3 D-17 precedent). Expected: ~2–3 re-freezes this phase.
- **D-24: Test-with-code.** Every new component ships with its unit tests this phase: Bar
  construction/precision, Store read path + loud missing-data errors, Feed windows including
  the M5-01 look-ahead regression test + completed-bars rule + megaframe fixture,
  matching-rule tests (next-open, limit bound, gap fills, maker/taker). Phase 7's TC2 becomes
  a gap-fill audit.

### Claude's Discretion
- Exact module layout of the `price_handler/` split (providers/store/feed package shape per
  the #30 sketch), Protocol names/surfaces, and where `Bar` lives (likely `itrader/core/`).
- Which timeframes to precompute (derive from registered strategies' declarations) and the
  precomputed-frame keying/slicing mechanics.
- MatchingEngine trigger-rule implementation details for resting market orders (D-13),
  including bracket-children sequencing on top of the Phase 4 create-all-then-emit flow, and
  the last-bar-of-dataset edge (orders decided on the final bar never fill — document).
- The fate of `PriceHandler`'s symbol methods (`_init_symbols`, `set_symbols`,
  `get_tradable_symbols`) pending the M5b universe stub — minimal relocation, no redesign.
- How `OrderEvent.price` for market orders is documented (decision-price estimate feeding the
  Phase 5 D-04 reservation math; actual fill settles at next open — the reservation is a
  pre-trade gate, not a ceiling; gap fills still settle).
- Decimal quantization details within `core/money` for the execution retype (D-12), under the
  never-round-prices rule (D-14).
- Workstream classification list for D-21 (which exact plans are "inert" vs "result-changing")
  and commit sequencing within the D-22 ordering.
- Expected-diff note format for re-freeze sign-offs (D-23).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions (Decimal money,
  UUIDv7), golden-master discipline
- `.planning/COVERAGE-INDEX.md` — items→milestone contract; M5 row: findings 3, 4, 21,
  27 (price seam), 28, 30 + PERF1, PERF4, FR1, FR6, FR7, FR8; §E logs any gap-discovery deltas
- `.planning/PROJECT.md` — milestone breakdown, two-point numerical re-baseline rule (the
  post-M5 point is Phase 8, NOT this phase), Out-of-Scope tags, DEF-01-C provenance
- `.planning/REQUIREMENTS.md` — **M5-01…M5-05** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 6 goal + 4 success criteria

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — **#21** (look-ahead, limit-slippage violation,
  partial-fill scaffolding, undocumented bar timing — the M5-01 fix list), **#3** (Bar struct
  design sketch — note: field types now Decimal per D-14, superseding the float sketch),
  **#4** (precompute-don't-cache design), **#28** (fee/slippage defects: dead maker fees,
  broken tiered ctor, inconsistent validation contracts), **#30** (Provider/Store/Feed target
  architecture + offline-vs-runtime lifecycle — the D-16 blueprint), **#27** (price-seam half).
  Boundary refs (do NOT pull forward): #24/#31/#38/#33 (sizing/reporting/universe — M5b),
  #25/#26 (provider resilience / SQL safety — D-sql/D-oanda).
- `.planning/codebase/CONCERNS.md` — FR1 (get_last_close type-branching), FR6 (network in run
  path), FR7 (bare except→None), FR8 (to_megaframe tz/key bugs), PERF1 (time.sleep), PERF4
  (strategies touch price_handler.prices directly)

### Phase carry-forward (constrains M5a)
- `.planning/phases/05-m4-money-transaction-correctness/05-CONTEXT.md` — **D-22** (event money
  Decimal with engineered-inert float matching internals — THIS phase removes the float
  carve-out per D-12), **D-04** (reservation = price × qty + commission estimate; pre-trade
  gate not ceiling — interacts with next-open fills), **D-21** (events are the only execution
  output; FillEvent(REFUSED) rejection path).
- `.planning/phases/04-m3-event-dispatch-core/04-CONTEXT.md` — **D-01/D-02** (frozen Event
  base, event_id/created_at — the Bar struct + BarEvent redesign builds on this), **D-11/D-13**
  (create-all-then-emit brackets; Order entity as pipeline state), **D-12** (FillEvent
  construct-complete at the exchange boundary), **D-14** (route-dict dispatch — BAR ordering
  portfolios→execution→strategies is the D-13 resting-order guarantee).
- `.planning/phases/01-m1-ignition-lock-the-oracle/01-CONTEXT.md` + STATE.md decisions —
  D-07 (csv feed inside PriceHandler — dissolved by the D-16/D-18 split), DEF-01-C
  (no margin/liquidation — routed to Phase 7 per D-07 this phase).

### Existing patterns to mirror / golden assets
- `itrader/order_handler/storage/in_memory_storage.py` + Phase 3 `PortfolioStateStorage` seam —
  the Factory + Protocol + in-memory shape the Store/Feed seams mirror (#30 explicitly).
- `itrader/execution_handler/matching_engine.py` — the pure resting-book engine that gains the
  market-order trigger rule (D-13) and loses the slippage violation (D-03).
- `itrader/execution_handler/exchanges/simulated.py` — `_emit_fill` (D-11 maker/taker context,
  D-03 limit-slippage removal), `time.sleep` (`:270`), fee/slippage model factories.
- `itrader/price_handler/data_provider.py` — the god-object being decomposed; `_load_csv_data`
  is the proven CSV-read logic the Store inherits; `get_resampled_bars` (`:310-346`) carries
  the #21 look-ahead bug being fixed.
- `itrader/events_handler/events/market.py` — BarEvent with the payload + ladders this phase
  replaces (D-15); the frozen-event pattern for the Bar struct.
- `itrader/core/money.py`, `itrader/core/ids.py`, `itrader/core/clock.py`,
  `itrader/core/enums/` — quantization policy (D-12/D-14), NewType/enum/frozen patterns.
- `itrader/outils/data_outils.py` — `resample_ohlcv` (`label='right'` bug at `:23`).
- `tests/integration/` oracle tests — the byte-exact assertions that become the D-21 hybrid
  gate; `scripts/run_backtest.py` — pinned oracle config (zero fees/slippage, D-09 keeps it).
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` + committed golden oracle — current reference frozen at
  M2b end-state; re-frozen per D-21/D-23 as validity fixes land.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_load_csv_data` (data_provider.py:131-182) — proven CSV→canonical-frame logic (header
  validation, tz handling, date-window pinning) that becomes the CSV store's read path.
- `MatchingEngine` — already gap-aware with intrabar high/low triggers and same-bar OCO
  priority; gains one trigger rule (market = next open) and keeps its purity.
- Phase 3/5 storage-seam pattern (ABC/Protocol + in-memory + factory) — the Store/Feed shape.
- Phase 4 frozen-event machinery (`events_handler/events/base.py`) — the Bar struct pattern.
- `core/money` quantization policy — extended to the execution retype under never-round-prices.
- Seeded RNG seam (Phase 2 D-11) already injected into slippage models — survives the Decimal
  retype.

### Established Patterns
- Tabs in handler modules; spaces in config/ and newer modules — the new price_handler
  packages and Bar struct are new code → spaces; match files edited in place.
- `make typecheck` (mypy --strict) gate live; `filterwarnings=["error"]`, strict markers.
  Note: `price_handler` modules currently carry D-sql/D-oanda mypy overrides — the new
  store/feed packages must be strict-clean; quarantined modules keep overrides.
- Phase 3–5 commit discipline: bisectable workstreams, pure-move commits separate from logic
  commits, suite green at every commit (now under the D-21 hybrid oracle rule).
- Enum `_missing_`/`from_string` pattern; frozen/slots DTOs; NewType aliases.

### Integration Points
- BarEvent consumers (D-15): `strategy_handler/base.py:79` (`get_last_close` → `bars[t].close`),
  `portfolio_handler` market-value update (close-marking, D-05), `execution_handler/
  execution_handler.py` → exchange `on_market_data` (Bar feeds matching), `universe/dynamic.py:
  68-77` (BarEvent construction — switches from `get_bar` Series to Feed-built Bars).
- Window consumers (D-17/D-20): `strategy_handler/strategies_handler.py:52`
  (`get_resampled_bars` call — repoints to Feed), `universe/dynamic.py:71`
  (`price_handler.prices` direct access — PERF4, dies with the Feed).
- Fill path (D-01/D-03/D-11): `exchanges/simulated.py:150` (immediate market fill — becomes
  rest-in-book), `:171-211` (`_emit_fill` fee/slippage application), `matching_engine.py:99,102`
  (limit fill price), `:157` (full-quantity fill).
- Wiring (D-16/D-18): `trading_system/backtest_trading_system.py` (PriceHandler construction +
  `set_dates(prices[...].index)` ping-clock derivation — re-pointed to the Store),
  `live_trading_system.py` (same, D-live minimal conformance).
- Reservation interplay (D-08/D-01): Phase 5 admission gate uses `order.price` × qty — with
  next-open fills the actual settle price differs; reservation stays a pre-trade gate
  (documented, Claude discretion item).

</code_context>

<specifics>
## Specific Ideas

- User repeatedly asked **"what's the industry standard?"** — every decision is anchored to
  named references: next-bar-open + completed-bars-only matched against backtesting.py /
  backtrader / Nautilus defaults (D-01/D-02); limit-or-better + stop-gap-risk as real exchange
  semantics (D-03); fee-as-fact vs slippage-as-measurement from FIX/Nautilus execution reports
  (D-08); maker/taker from Binance/FIX LastLiquidityInd (D-11); Decimal prices from Nautilus
  fixed-point `Price`/`Quantity` and Binance string-price APIs (D-14); indicators-on-float /
  money-on-fixed-point split from Nautilus (D-17); "strategies never choose the as-of time"
  distilled from backtesting.py/backtrader/Zipline/Nautilus data access (D-20).
- User asked whether Decimal handles micro-priced tokens (0.000005 USD) — locked the
  never-round-prices rule (D-14) and surfaced the per-instrument-precision concern, then
  explicitly deferred the full Instrument model after scope advice.
- User asked for a concrete example before locking the oracle discipline — the
  $0.001-refactor-bug vs next-open-diff walkthrough led to the hybrid choice (D-21).
- User confirmed slippage should be derivable "like fee, in its own column" — locked the
  derived trade-log column in M5b reporting rather than an event field (D-08).

</specifics>

<deferred>
## Deferred Ideas

- **DEF-01-C margin/liquidation model** (un-liquidated short → negative equity) → **Phase 7
  (M5b) risk layer**, alongside `RiskManager.check_cash` + sizing policy (M5-06). This phase
  documents the behavior only.
- **Slippage attribution column in the trade log** (per-trade fill vs decision-close cost) →
  **M5b reporting (#38)** — the derived-analytics half of D-08.
- **Instrument metadata model** (tick size, step size, price/size precision, exchange
  filters) → step-size quantity rounding fits **M5b sizing**; live-venue filter validation →
  **D-live**. The D-14 never-round-prices rule keeps the door open.
- **Guarded pull portal on the Feed** (time-scoped `(ticker, timeframe, depth)` API for
  multi-timeframe/multi-symbol strategies, Zipline/Nautilus style) → **M5b+** when a strategy
  actually needs it; layers onto the Feed without breaking push (D-20).
- **Volume-based partial fills / liquidity model** → out of program scope (no intrabar
  liquidity data); revisit only if a future milestone ingests finer-grained data.
- **SQL store backend, CCXT/OANDA provider rework, live streaming provider** → **D-sql /
  D-oanda / D-live** — their code quarantines behind the new seams untouched (D-16).
- **Ingestion pipeline as a real CLI** (provider→store offline job) → persistence milestone;
  this phase ships only the stub entry point.

</deferred>

---

*Phase: 6-m5a-backtest-validity-fills-data-pipeline*
*Context gathered: 2026-06-06*
