# Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage - Context

**Gathered:** 2026-06-07
**Status:** Ready for planning

<domain>
## Phase Boundary

The **sizing policy, metrics, universe & coverage** phase. Complete the strategy-declared
sizing policy started minimally in M1 across four locked requirements (M5-06…M5-09): a typed
policy vocabulary resolved per-portfolio in the order/risk layer with enforced admission rules
(closing the `#24`/`#31`/KB11 span and DEF-01-C), correct reporting/metrics with computation
split from presentation (`#38`/`#14`), the universe collapsed to a documented membership stub
(`#33`), and targeted strategy/data/reporting/universe test coverage (TC2/TC4/TC6 gap-fill).

**Golden-master position:** Phase 7 is inside M5 — result changes are sanctioned under the
Phase 6 hybrid discipline (D-21/D-23 carry forward). This phase has EXACTLY TWO result-changing
workstreams (the admission rules, D-08/D-10 below), each with its own named, owner-gated
re-freeze. Everything else — the entire sizing-policy refactor included — is INERT and must
reproduce the current M5a reference byte-exact (`tests/golden/REFREEZE-M5A.md`). New frozen
artifacts (derived metrics in summary.json, slippage column in trades.csv) ride the named
re-freezes. Phase 8 still owns the final sanctioned baseline.

**Boundary with adjacent work (do NOT pull forward):**
- **Phase 8 (M5c)** owns: external cross-validation vs backtesting.py + backtrader and the
  final frozen numerical reference.
- **Future margin milestone** owns: margin reservation, maintenance margin, forced liquidation —
  shorts return only with that model (D-08/D-09 below).
- **D-screener** owns: the screener→strategy rebalance loop and the real time-aware Universe
  (LEAN UniverseSelectionModel shape) that returns alongside it.
- **D-sql** owns: stats persistence — `StatisticsReporting._to_sql` and the SQL path die here,
  reborn there if ever needed.
- **D-live** owns: the full Instrument metadata model (tick size, min-notional, venue filters);
  this phase ships only the optional `step_size` policy param.

</domain>

<decisions>
## Implementation Decisions

### Sizing policy (M5-06)
- **D-01: Typed policy + engine resolver.** A frozen `SizingPolicy` dataclass (kind + params)
  declared in `Strategy.__init__`, carried on the signal, REPLACING the untyped
  `strategy_setting` dict. ONE resolver component in the order layer dispatches on policy kind
  with the `PortfolioReadModel` injected — the institutional hybrid (LEAN
  Insight→PortfolioConstruction shape; per-strategy sizer objects rejected as the outlier
  pattern). A resolver registry for custom sizing code can layer on later behind the same typed
  seam without changing the signal contract.
- **D-02: v1 vocabulary = FractionOfCash(fraction) + FixedQuantity(qty) + RiskPercent(risk_pct).**
  RiskPercent: qty = (equity × risk%) / |price − stop| (Van Tharp). FractionOfCash/FixedQuantity
  are golden-exercised; RiskPercent ships unit-tested but oracle-dark.
- **D-03: Golden SMA_MACD declares FractionOfCash(0.95) — the ENTIRE sizing refactor is
  oracle-inert.** 0.95 is exactly what today's hardcode does; byte-exact reproduction of the M5a
  reference is the proof the new plumbing is sound. 0.95-vs-0.80 is configuration, not
  correctness — no re-freeze spent on it.
- **D-04: The three orphaned strategy_handler packages are DELETED** (`position_sizer/`,
  `risk_manager/`, `sltp_models/` — zero instantiations, zero tests). New files live in
  `order_handler/`: the policy types + the sizing resolver. Capabilities rewritten clean in
  Decimal: resolver absorbs DynamicSizer's correct ideas; admission rules join the Phase 5
  check-and-reserve gate; the `quantity=0` "transition period" validator bypass dies. M5-06
  satisfied by capability, not filename.
- **D-05: Optional `step_size: Decimal | None = None` on SizingPolicy.** Resolver quantizes
  ROUND_DOWN when set; golden run leaves it None (inert). Mechanism ships unit-tested,
  oracle-dark. The never-round-prices rule (Phase 6 D-14) is untouched — this rounds
  QUANTITIES only, opt-in.
- **D-06: Resolver failures reject loudly** — typed failure → the Phase 4 audited REJECTED
  route with a reason naming the policy violation (e.g. "RiskPercent requires stop_loss").
  No silent fallbacks (FR7 / slippage-validation fail-loud precedent).
- **D-07: Policy-driven partial exits via `exit_fraction` (default 1.0).** Unsized exit =
  net_quantity × exit_fraction, with a remainder rule (final exit takes all when the remainder
  would drop below step_size/dust). Default 1.0 keeps the golden run inert. The explicit-quantity
  partial-exit path (order_manager.py:583 preserve-as-is; TradingInterface) is UNCHANGED.
  Bracket interaction (children sized at entry vs partial signal-exit) documented as a v1
  limitation. Policy sizes entries; exits never route through entry sizing.

### Risk admission rules (M5-06, DEF-01-C)
- **D-08: Per-strategy `TradingDirection` enum, enforced at admission (RESULT-CHANGING).**
  Declared in `Strategy.__init__` (LONG_ONLY / LONG_SHORT / SHORT_ONLY), carried on the signal,
  enforced in the admission gate: LONG_ONLY + unsized SELL + no open long → audited REJECTED.
  SMA_MACD declares LONG_ONLY → the 2 blessed golden shorts disappear (the very first golden
  trade is a 9-month short, −2176 PnL — expect material equity-curve diff). LONG_SHORT is
  reserved but REJECTED at strategy registration with a loud documented error until the margin
  milestone exists. Kills DEF-01-C structurally; Phase 8 cross-validates a clean long-only run.
- **D-09: Margin model explicitly deferred.** Margin reservation alone (cheap via the Phase 5
  reservation API) would NOT fix DEF-01-C — no liquidation means equity can still go negative —
  and is result-changing anyway (reservations shrink available_balance → sizing changes). Full
  margin + maintenance + forced liquidation is a new BAR-path engine mechanic → its own designed
  milestone, for when shorts return intentionally.
- **D-10: `allow_increase` enforced per-strategy (RESULT-CHANGING if golden has increases).**
  Typed flag riding the signal: False → unsized BUY-while-long audited REJECTED ("position
  increase not allowed by strategy"); True → sized by policy on remaining cash, covered by
  check-and-reserve (the literal M5-06 check_cash requirement). Strategies stay portfolio-blind
  and keep emitting duplicate signals — filtering is the admission gate's job, per portfolio.
  Golden SMA_MACD declares False (its declared-but-ignored value, finally honest).
- **D-11: Two named re-freezes** (Phase 6 D-21/D-23 style): (1) direction guard first —
  expected-diff note (2 shorts removed + knock-on), owner sign-off, re-freeze; (2) increase
  enforcement on the post-guard reference — diff note (N rejected increases), sign-off,
  re-freeze. Every numeric change separately named and attributable. The new frozen artifacts
  (D-15/D-17) ride these re-freezes.

### Strategy contract (M5-06 `calculate_signal` clause)
- **D-12: Return-typed AND renamed: `generate_signal(ticker, bars) -> SignalIntent | None`.**
  The strategy becomes a pure alpha function: no `global_queue`, no `last_event` mutation, no
  `subscribed_portfolios` knowledge. The handler stamps time/price from the current bar,
  attaches policy/direction, fans out per subscribed portfolio, builds the SignalEvents,
  enqueues. `buy()`/`sell()` may survive as thin sugar building the intent. Oracle-inert. The
  old private `_generate_signal` emit helper dissolves. The dead `my_strategies/` tree stays
  untouched/quarantined.
- **D-13: SL/TP — explicit levels primary + typed `SLTPPolicy` alternative.** `SignalIntent`
  carries optional explicit sl/tp levels (strategy-computed from its window — the universal
  pattern: backtesting.py/backtrader/Nautilus). A strategy may instead declare a typed
  `SLTPPolicy` — v1 kinds: `PercentFromFill(sl_pct, tp_pct)` resolved engine-side at parent
  fill (IB attached-order semantics — the anchoring a strategy structurally cannot express),
  and `PercentFromDecision`. Explicit levels win when both present. All oracle-dark (golden has
  no brackets). Fill-time bracket-price mechanics (update children via validated modify path vs
  deferred pricing) = planner discretion. Trailing stops and AtrMultiple kinds deferred.

### Reporting & metrics (M5-07)
- **D-14: Pure computation functions on run artifacts.** `reporting/` becomes a pure module:
  metric functions consuming the equity curve + closed-trades frame (the artifacts
  `run_backtest.py` builds from MetricsManager snapshots). No handler imports, no SQL, no class
  state. `run_backtest.py` and tests call it directly. `StatisticsReporting._prepare_data`/
  `_to_sql` die (SQL → D-sql); `EngineLogger` deleted (locked by requirement). Presentation is
  a separate optional module consuming the same frames.
- **D-15: Derived metrics FREEZE into golden `summary.json`** — sharpe, sortino, cagr, max
  drawdown, profit factor, win rate, computed deterministically by the golden run. Phase 8
  reconciles a frozen metrics reference; future metric-math regressions trip the oracle. Rides
  the D-11 re-freezes.
- **D-16: Industry-standard metric definitions, matched to the Phase 8 reference engines.**
  True profit factor (gross profit / gross loss), textbook Sortino (downside deviation,
  full-period denominator, target 0), Sharpe with risk_free_rate=0, annualization 365 (daily
  crypto bars), max drawdown on `equity.cummax()`. The misspelled `profict_factor` count-ratio,
  the non-standard Sortino, and `periods=355` die. Guarded denominators; pandas-2-safe idioms
  (`.iloc[-1]`, no chained assignment) throughout — `filterwarnings=["error"]` enforces.
- **D-17: D-08 (Phase 6) slippage-attribution column joins frozen `trades.csv`** — per-trade
  execution cost (fill price vs decision-bar close, entry + exit attribution). In the
  zero-slippage golden run it measures the overnight next-open gap introduced by Phase 6 fill
  realism. Rides the D-11 re-freezes.
- **D-18: Rolling Sharpe implemented** as one pure function (rolling window over returns),
  unit-tested — resolves the M5-07 rolling-stats stub by finishing it.
- **D-19: plots.py — fix the minimal set as an optional presentation module:** equity curve,
  drawdown, trade P/L scatter, fixed for current plotly/pandas, consuming the same frames as
  the metric functions, smoke-tested (figure builds without raising). Dead/broken extras
  (`profit_loss_scatter` column bugs, `titlefont_size`, dev comments) deleted.

### Universe stub (M5-08)
- **D-20: BarEvent factory moves into the `BarFeed`** (LEAN/Nautilus shape: the data engine
  produces data events; no reference engine puts event production in a universe). `universe/`
  collapses to ONE documented module deriving membership (union of strategy tickers ∪ screener
  set — `get_strategies_universe` logic survives), with a prominent docstring naming the LEAN
  `UniverseSelectionModel` as the future growth target alongside the D-screener rebalance loop.
  `StaticUniverse` + the `get_assets` ABC deleted (unused, contract never honored). Trading
  systems wire the feed directly for bar events. Purity is the expansion strategy: the future
  rebalance milestone touches only membership, never event plumbing.
- **D-21: Multi-strategy support is UNAFFECTED** — StrategiesHandler already iterates N
  strategies with per-strategy timeframe gating; the membership stub IS the multi-strategy
  union; the Feed precomputes per (ticker, timeframe) across all declarations. Only
  time-varying mid-run membership is deferred (D-screener). Multi-strategy runs remain
  oracle-dark (golden is single-strategy).

### Test coverage (M5-09)
- **D-22: Targeted gap-fill with hand-verified fixtures.** Audit TC2/TC4/TC6 against existing
  tests (test_csv_store.py and test_bar_feed.py exist from Phase 6) and fill only the gaps.
  Metric functions tested with small synthetic frames whose expected values are hand-computable
  (known equity series → known sharpe/drawdown); frozen summary.json metrics double as the
  golden-level regression. `generate_signal` tested as a pure function (synthetic crossover
  frames → expected intent). New components (resolver, admission rules, intent contract,
  SLTPPolicy) ship test-with-code per the Phase 6 D-24 discipline. No coverage-percent targets.

### Claude's Discretion
- Exact shapes/files for `SizingPolicy`, `SLTPPolicy`, `SignalIntent`, `TradingDirection`
  within `order_handler/` (and where the intent type lives so strategy_handler can import it
  without circularity).
- Whether `direction`/`allow_increase`/`max_positions` are policy fields or sibling strategy
  fields; `max_positions` multi-ticker enforcement semantics (oracle-dark, golden is
  single-ticker).
- FractionOfCash semantics when allow_increase=True (fraction of remaining available cash vs
  target-equity) — oracle-dark, golden declares False.
- Fill-time bracket mechanics for PercentFromFill (validated modify path vs deferred child
  pricing on top of create-all-then-emit).
- The `cash < 30` magic floor dies with RiskManager (never wired — removal inert); no
  min-notional rule this phase (future Instrument model).
- summary.json schema for the frozen metrics block; trades.csv slippage column naming;
  expected-diff note format for the two re-freezes (Phase 6 precedent).
- Sequencing: all inert workstreams land and prove byte-exactness BEFORE the two
  result-changing admission rules (Phase 6 D-22 structural-first discipline).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REQUIREMENTS.md` — **M5-06…M5-09** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 7 goal + 4 success criteria
- `.planning/REFACTOR-BRIEF.md` — program goal, locked decisions (Decimal money, UUIDv7),
  golden-master discipline
- `.planning/PROJECT.md` — milestone breakdown, two-point re-baseline rule (post-M5 point is
  Phase 8, NOT this phase), DEF-01-C provenance

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — **#24** (composition fiction, contract
  inconsistency), **#31** (the DECIDED sizing architecture: strategy owns alpha+intent incl.
  SL/TP levels + declarative policy; order/risk layer owns allocation — D-01 implements
  this), **#33** (universe collapse blueprint), **#38** (reporting defect list: drawdown,
  pandas-2, `is np.nan`, profict_factor, plots), **#14** (reporting split:
  computation/presentation/persistence, EngineLogger deletion)
- `.planning/codebase/CONCERNS.md` — KB11 (stranded sizing), KB2/KB23 (reporting bugs), TD6,
  TD7, TD10; TC2/TC4/TC6 (the M5-09 coverage targets)

### Phase carry-forward (constrains M5b)
- `.planning/phases/06-m5a-backtest-validity-fills-data-pipeline/06-CONTEXT.md` — **D-07**
  (DEF-01-C routed here), **D-08** (fee=fact / slippage=measurement → the D-17 trade-log
  column), **D-14** (never-round-prices; Instrument deferral → the D-05 step_size shape),
  **D-20** (push-based windows; strategies never choose as-of time — the D-12 intent contract
  completes this), **D-21/D-22/D-23** (hybrid oracle discipline, structural-first, owner
  sign-off per re-freeze — this phase's law), **D-24** (test-with-code; TC2 as gap-fill audit)
- `.planning/phases/05-m4-money-transaction-correctness/05-CONTEXT.md` — **D-02** (sync
  check-and-reserve at admission — where the new admission rules live), **D-03** (only
  cash-debiting orders reserve), **D-04** (reservation = price × qty + commission estimate),
  **D-15** (frozen PositionView reads)
- `.planning/phases/04-m3-event-dispatch-core/04-CONTEXT.md` — **D-11/D-13** (create-all-then-emit
  brackets; Order entity as audited pipeline state — the REJECTED route D-06/D-08/D-10 use)
- `tests/golden/REFREEZE-M5A.md` — the current frozen reference the inert work must reproduce
  byte-exact; precedent format for the two D-11 expected-diff notes

### Golden assets
- `tests/golden/summary.json` — gains the frozen derived-metrics block (D-15)
- `tests/golden/trades.csv` — gains the slippage-attribution column (D-17); source of the
  2-shorts fact behind D-08 (134 trades: 132 LONG, 2 SHORT)
- `scripts/run_backtest.py` — the deterministic artifact builder the pure metric functions
  plug into (its docstring already declares sharpe/sortino/cagr "M5-owned")
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — golden dataset

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OrderManager._resolve_signal_quantity` (order_manager.py:553-629) — the M1 sizing seam the
  resolver replaces; its exit-to-full-position and explicit-quantity-preserved branches are the
  behavior contract (explicit-quantity path at :583 survives unchanged).
- Phase 5 admission gate (check-and-reserve in OrderManager via `PortfolioReadModel`) — where
  direction/increase rules land; the audited REJECTED route (Phase 4) is the rejection vehicle.
- `MetricsManager.get_snapshots()` + `run_backtest.py::build_equity_curve/build_trade_log` —
  the canonical artifact builders the pure metric functions consume.
- `BarFeed` (price_handler/feed/) — gains the BarEvent factory from DynamicUniverse
  (generate_bar_event is already thin: feed.current_bars + wrap).
- `StrategiesHandler.calculate_signals` (strategies_handler.py:36-59) — the per-strategy window
  push loop that becomes the intent→event construction site (fan-out moves here from
  Strategy._generate_signal).
- `core/money.py` quantization (to_money), frozen-event machinery, enum `_missing_` pattern —
  the idioms for the new policy/intent types.

### Established Patterns
- Frozen/slots dataclasses + NewType aliases + enum boundary parsing (Phases 2-4) — the
  SizingPolicy/SLTPPolicy/SignalIntent/TradingDirection shapes.
- Deletion discipline: saga, locks, ExecutionResult, TieredFeeModel, PriceHandler precedents —
  the D-04 package deletion follows it.
- Hybrid oracle discipline (Phase 6 D-21): inert work byte-exact gated; result-changing work
  re-frozen with named expected-diff notes + owner sign-off.
- Tabs in handler modules; spaces in new modules — new order_handler sizing files are new code
  → spaces; match files edited in place.
- mypy --strict gate; `filterwarnings=["error"]` — the pandas-2 reporting fixes are forced.

### Integration Points
- SignalEvent consumers: `order_manager.on_signal`/`_create_orders_from_signal` (reads
  stop_loss/take_profit for brackets at :196-202), `order_validator` (quantity-0 bypass at
  :222 dies). SignalEvent schema changes: `strategy_setting` dict → typed policy/direction
  fields.
- `Strategy.__init__` signature: max_positions/max_allocation/allow_increase kwargs →
  sizing_policy/direction/allow_increase typed params; `setting_to_dict()` dies with the dict.
- Trading systems (`backtest_trading_system.py`, `live_trading_system.py`): DynamicUniverse
  wiring → feed-direct bar events + membership stub; `StatisticsReporting` construction +
  `calculate_statistics()/print_summary()` calls (:107-187) → pure-function reporting calls.
- `tests/integration/` oracle tests — the byte-exact gate for all inert work; extended by the
  frozen metrics/slippage artifacts after the D-11 re-freezes.
- `empty_strategy.py` + `tests/unit/strategy/test_strategy.py` — must convert to the
  generate_signal intent contract alongside SMA_MACD.

</code_context>

<specifics>
## Specific Ideas

- User repeatedly anchored on **"what's the industry standard?"** — decisions are matched to
  named references: typed-policy-plus-engine-resolver from LEAN's Insight→PortfolioConstruction
  pipeline (D-01); per-strategy Sizer objects identified as the backtrader outlier and rejected;
  fill-anchored SL/TP from IB attached-order/pegged-order semantics (D-13); explicit stop levels
  as the universal baseline (backtesting.py/backtrader/Nautilus); BarEvent-factory-in-feed from
  LEAN/Nautilus data-engine separation (D-20); metric definitions matched to the Phase 8
  reference engines (D-16).
- User explicitly wants **partial exits in this version** — delivered both ways: the existing
  explicit-quantity path (confirmed unchanged) and the new declarative `exit_fraction` (D-07).
- User probed whether a **margin mechanism is simple** — walked through reservation-only vs
  full liquidation; chose long-only guard now + margin as its own future milestone (D-08/D-09).
- User asked how **multiple strategies** work post-collapse — confirmed unaffected (D-21);
  concern was about future extensibility, resolved by the purity argument (D-20).
- User chose `generate_signal` as the new method name over `on_bars`/keeping
  `calculate_signal` (D-12).

</specifics>

<deferred>
## Deferred Ideas

- **Margin + liquidation milestone** — margin reservation, maintenance margin, mark-to-market
  forced liquidation on the BAR path; shorts (`TradingDirection.LONG_SHORT`) unlock only with
  it. The enum seam ships now (D-08), the capability later.
- **Resolver registry for custom sizing code** — additive behind the typed SizingPolicy seam
  when a strategy actually needs arbitrary sizing logic.
- **Trailing stops + AtrMultiple SLTP kinds** — trailing needs MatchingEngine per-bar stop
  updates (new engine mechanic); ATR kind needs intent-carried indicator values. Both deferred
  from D-13.
- **Full Instrument metadata model** (tick size, min-notional, venue filters) → D-live; the
  optional step_size param (D-05) keeps the door open.
- **Real time-aware Universe** (LEAN UniverseSelectionModel: scheduled membership +
  subscription updates) → returns ONLY alongside the D-screener rebalance loop (D-20 docstring
  marks the target).
- **Multi-strategy oracle validation** — mechanics work (D-21) but golden/cross-validation
  stays single-strategy this program.
- **Declarative scale-out policies beyond exit_fraction** — future vocabulary growth.
- **Stats persistence** (SQL) → D-sql, dying with `_to_sql` here.

</deferred>

---

*Phase: 7-m5b-sizing-policy-metrics-universe-coverage*
*Context gathered: 2026-06-07*
