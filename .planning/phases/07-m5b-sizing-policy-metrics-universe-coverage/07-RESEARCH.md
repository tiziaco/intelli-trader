# Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage - Research

**Researched:** 2026-06-07
**Domain:** Brownfield refactor — typed sizing policy + admission rules (order/risk layer), pure metrics module, universe collapse, targeted test coverage. Python 3.13 / pandas 2.3.3 / plotly 6.8.0 / pytest 8.4.2, all in-repo.
**Confidence:** HIGH (all codebase claims verified by direct file reads; all library-breakage claims verified empirically against the project's installed `.venv`; metric definitions verified against backtesting.py source)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Sizing policy (M5-06)
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

#### Risk admission rules (M5-06, DEF-01-C)
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

#### Strategy contract (M5-06 `calculate_signal` clause)
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

#### Reporting & metrics (M5-07)
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

#### Universe stub (M5-08)
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

#### Test coverage (M5-09)
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

### Deferred Ideas (OUT OF SCOPE)
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
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M5-06 | Strategy-declared sizing **policy** fully resolved per-portfolio in the order/risk layer, completing the M1 minimal seam — `VariableSizer` finished, `RiskManager.check_cash` covers position increases, `calculate_signal` contract enforced (completes #24/#31/KB11, TD7, TD10) | The M1 seam (`OrderManager._resolve_signal_quantity`, order_manager.py:553-629) mapped line-by-line; the orphaned packages inventoried (381 LOC total, zero importers); the import-cycle constraint for policy types on `SignalEvent` analyzed (Pitfall 7); `PortfolioReadModel` gap for RiskPercent identified (Pitfall 10); the audited-REJECTED route and check-and-reserve gate seams located; the byte-exact-inertness arithmetic rules documented (Pitfall 1) |
| M5-07 | Reporting/metrics correct — drawdown math, pandas-2/plotly API breakage, `is np.nan` bug, rolling-stats stub, dead `EngineLogger` resolved; computation split from presentation (#38, #14, KB2, KB23, TD6) | Every documented bug verified in code AND empirically against pandas 2.3.3 / plotly 6.8.0 / numpy 2.2.6 in the project venv; D-16 metric formulas verified against backtesting.py source (`_stats.py`); artifact-builder seams (`run_backtest.py::build_equity_curve/build_trade_log`) confirmed; mypy-override removals enumerated |
| M5-08 | `universe/` collapses to a thin documented symbol-set stub (#33) | Full blast radius mapped: `EventHandler` TIME-route + constructor, both trading systems, 3 test files that mock `universe`, `generate_bar_event` body (already thin: `feed.current_bars` + wrap + enqueue) |
| M5-09 | Strategy/data/reporting/universe paths gain test coverage — CSV price store, reporting/statistics, universe (TC2 CSV-part, TC4, TC6) | Existing test inventory audited: test_csv_store.py (6 tests) + test_bar_feed.py (13 tests) already cover the TC2 CSV part; tests/unit/strategy/test_strategy.py (4 tests) must convert to the intent contract; reporting and universe have ZERO tests — Wave 0 gaps listed in Validation Architecture |
</phase_requirements>

## Summary

This phase is a brownfield refactor of four subsystems in an engine the team fully controls. There are **zero new dependencies** — everything ships on the already-locked stack (pandas 2.3.3, numpy 2.2.6, plotly 6.8.0, pytest 8.4.2). The research effort therefore went into (1) verifying every claimed defect against the actual code and the actual installed libraries, (2) mapping the precise seams the new components plug into, and (3) finding the traps that would silently break the byte-exact inertness gate that governs most of this phase.

Three findings matter most for planning. **First, an import cycle constrains where the policy types live:** `SignalEvent` (in `events_handler/events/signal.py`) must carry the typed `SizingPolicy`/`TradingDirection`, but `order_handler/__init__.py` imports `order_handler.py` which imports `events_handler.events` — so a runtime import of `order_handler` types from `signal.py` is a circular import. The carried types must either live in `core/` (the established home of every other event-carried type: `Side`, `OrderType`, `Bar`) or be imported under `TYPE_CHECKING` only. **Second, byte-exactness is sensitive to Decimal arithmetic *shape*, not just value:** `trades.csv` serializes raw Decimal reprs (e.g. `0E-27`, 27-digit quantities), so `net_quantity × Decimal("1.0")` produces a different exponent/repr than `net_quantity` — the `exit_fraction=1.0` default path must be a structural no-op (skip the multiply), and the resolver must reproduce the existing `(Decimal("0.95") * available) / to_money(price)` expression exactly. **Third, the oracle test only compares golden-known columns and a fixed key tuple**, so the new slippage columns and metrics block can be *produced* by `run_backtest.py` early (oracle-safe) and become regression-locked only when the goldens are regenerated at the two named re-freezes.

The reporting bugs are all real and all verified: `s[-1]` and chained `.iloc` assignment raise `FutureWarning` (suite-fatal under `filterwarnings=["error"]`), `np.mean` of an empty slice raises `RuntimeWarning` (also fatal), plotly 6.8.0 rejects `titlefont_size` with a hard `ValueError`, and the D-16 replacement formulas match the Phase 8 reference engine (backtesting.py `_stats.py`) verbatim: profit factor = gross profit / gross loss, Sortino downside deviation = `sqrt(mean(clip(r,−inf,0)²))` (full-period denominator), max drawdown on `equity / equity.cummax()`.

**Primary recommendation:** sequence all inert work (sizing plumbing, intent contract, reporting module, universe collapse, coverage) first under the byte-exact gate, then land the two result-changing admission rules last with their named re-freezes — and put the event-carried types (`SizingPolicy`, `TradingDirection`, `SLTPPolicy`) in `core/` to break the import cycle while keeping the resolver and admission rules in `order_handler/`.

## Architectural Responsibility Map

The "tiers" here are the engine's layers (single-process event-driven system — no web/client tiers).

| Capability | Primary Layer | Secondary Layer | Rationale |
|------------|--------------|-----------------|-----------|
| Alpha + intent (direction, sl/tp levels, policy declaration) | Strategy (`strategy_handler/`) | — | D-12: strategy is a pure function `(ticker, bars) → SignalIntent \| None`; it knows market data, never portfolio state |
| Signal construction + fan-out per portfolio | StrategiesHandler | — | D-12: handler stamps time/price from the bar event, attaches policy/direction, builds SignalEvents, enqueues |
| Policy → quantity resolution | Order/risk layer (`order_handler/` resolver) | core/ (policy type definitions) | D-01: one resolver, `PortfolioReadModel` injected; per-portfolio quantity is portfolio state the strategy must not know |
| Admission rules (direction guard, allow_increase, cash reserve) | Order/risk layer (Phase 5 check-and-reserve gate in `OrderManager.process_signal`) | — | D-08/D-10: rejection via the Phase 4 audited PENDING→REJECTED route |
| Bracket declaration + fill-time SLTP resolution | Order/risk layer (`OrderManager`) | Execution (matching engine holds resting children) | D-13: `PercentFromFill` resolves at parent fill; exchange remains sole fill authority |
| Fill matching / OCO | Execution (`MatchingEngine` via `SimulatedExchange`) | — | Unchanged this phase |
| BarEvent production | Data layer (`BarFeed`) | Trading systems (wiring) | D-20: data engine produces data events (LEAN/Nautilus shape) |
| Symbol membership | Universe stub (one documented module) | — | D-20: pure derivation, union of strategy tickers ∪ screener set |
| Metric computation | Reporting (pure functions on frames) | `scripts/run_backtest.py` (artifact builder + caller) | D-14: no handler imports, no SQL, no class state |
| Chart presentation | Reporting presentation module (optional) | — | D-19: consumes the same frames; smoke-tested only |
| Golden regression | tests/integration oracle + frozen `tests/golden/` | — | D-11: byte-exact for inert work; two named re-freezes for the admission rules |

## Standard Stack

### Core (all already installed — verified against the project's `.venv` and `poetry.lock`)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 | Equity/trades frames, rolling stats, resample (feed) | Already the project's frame layer `[VERIFIED: poetry run python]` |
| numpy | 2.2.6 | Metric math (sqrt, clip, where) | Already installed `[VERIFIED: poetry run python]` |
| plotly | 6.8.0 | Presentation module (D-19) | Already installed; API verified `[VERIFIED: poetry run python]` |
| pytest | 8.4.2 | Test runner, strict markers/config | Project standard `[VERIFIED: pyproject.toml]` |
| mypy (strict) | ^2.1.0 | Type gate — new modules must be strict-clean | Program DoD `[VERIFIED: pyproject.toml]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `decimal` (stdlib) | 3.13 | All money/quantity math; `ROUND_DOWN` for step_size | D-05 quantize; `core.money.to_money` is the only entry path |
| `pandas.testing` | 2.3.3 | Golden frame comparison (`assert_frame_equal`, `check_exact=True`) | Existing oracle-test pattern — reuse for new fixtures |
| `typing.assert_never` | 3.13 | Exhaustiveness check on policy-kind `match` dispatch | mypy --strict catches unhandled policy kinds at type-check time |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-written metric functions | `quantstats` / `empyrical` | New dependency, different formula conventions vs the Phase 8 reference engines, harder to freeze deterministically — D-16 locks specific formulas; write them as ~10-line pure functions instead |
| Tagged-union frozen dataclasses for `SizingPolicy` | Single class + kind enum + params dict | Dict params are untyped — loses mypy --strict exhaustiveness; the union of frozen dataclasses matches the project's frozen/slots event idiom |
| `match`/`assert_never` dispatch | Registry dict of handlers | Registry is the *deferred* extension (CONTEXT: "resolver registry ... can layer on later"); v1's 3 kinds need exhaustiveness, not pluggability |

**Installation:** none — zero new packages this phase.

## Package Legitimacy Audit

**No external packages are installed by this phase.** All work uses libraries already present in `poetry.lock` (pandas, numpy, plotly, pytest, stdlib). No slopcheck run required; no registry verification required.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                          TIME tick (TimeGenerator)
                                  │
                                  ▼
        ┌──────────── EventHandler TIME route ───────────────┐
        │  (today: universe.generate_bar_event;               │
        │   after D-20: BarFeed-owned factory, wired by the   │
        │   trading system — universe stub no longer in loop) │
        └──────────────────────┬──────────────────────────────┘
                               ▼
                       BarEvent {ticker: Bar}
                               │
        ┌──────────────────────┼───────────────────────────────┐
        ▼                      ▼                               ▼
 portfolio mark-to-mkt   execution.on_market_data      StrategiesHandler
                         (resting stop/limit match)    .calculate_signals
                                                              │ feed.window(...)
                                                              ▼
                                            strategy.generate_signal(ticker, bars)
                                                  → SignalIntent | None   (D-12: pure)
                                                              │
                                       handler stamps time/price, attaches
                                       SizingPolicy + TradingDirection,
                                       fans out per subscribed portfolio
                                                              ▼
                                                  SignalEvent (typed policy fields,
                                                   strategy_setting dict DELETED)
                                                              │
                                                              ▼
                            OrderManager.process_signal  (order/risk layer)
                            ────────────────────────────────────────────
                            0. ADMISSION RULES (new, D-08/D-10):
                               direction guard → audited REJECTED
                               allow_increase guard → audited REJECTED
                            1. SIZING RESOLVER (new, D-01/D-02):
                               match policy kind → Decimal quantity
                               (PortfolioReadModel injected)
                            2. validate entity (zero-qty bypass DELETED)
                            3. check-and-reserve (Phase 5, unchanged)
                            4. create-all-then-emit brackets (Phase 4)
                               + SLTPPolicy fill-time resolution (D-13)
                                                              │
                                                              ▼
                                     OrderEvent → SimulatedExchange → FillEvent
                                                              │
                                              portfolio.on_fill / order mirror
                                                              │
                                     (post-run) MetricsManager snapshots
                                                              │
                                                              ▼
                          scripts/run_backtest.py: build_equity_curve / build_trade_log
                                                              │
                                  ┌───────────────────────────┴─────────────────┐
                                  ▼                                             ▼
                     reporting metric functions (D-14, pure)        reporting presentation
                     sharpe/sortino/cagr/max_dd/PF/win_rate/        (plotly figures, D-19,
                     rolling_sharpe — consumed by run_backtest      optional, smoke-tested)
                     → summary.json metrics block (D-15)
                     + trades.csv slippage columns (D-17)
                                  │
                                  ▼
                  tests/golden/ byte-exact oracle (re-frozen twice, D-11)
```

### Recommended Project Structure

```
itrader/
├── core/
│   ├── sizing.py            # NEW: SizingPolicy union (FractionOfCash/FixedQuantity/RiskPercent),
│   │                        #      SLTPPolicy union, TradingDirection enum — event-carried types
│   │                        #      live in core/ (see Pitfall 7: import cycle). [planner may instead
│   │                        #      use TYPE_CHECKING imports to keep them in order_handler/ per D-04 letter]
│   └── portfolio_read_model.py   # +total_equity() accessor (RiskPercent needs equity — Pitfall 10)
├── order_handler/
│   ├── sizing_resolver.py   # NEW: ONE resolver, match-dispatch on policy kind, ReadModel injected
│   └── order_manager.py     # admission rules join process_signal; _resolve_signal_quantity replaced
├── strategy_handler/
│   ├── base.py              # Strategy ABC: generate_signal abstract; declares policy/direction;
│   │                        #   SignalIntent type (or import from core/) — strategy-side contract
│   ├── strategies_handler.py # intent → SignalEvent construction + fan-out moves here
│   ├── SMA_MACD_strategy.py # rewritten to generate_signal → SignalIntent
│   ├── empty_strategy.py    # converted alongside
│   └── (position_sizer/ risk_manager/ sltp_models/ DELETED — D-04)
├── reporting/
│   ├── metrics.py           # NEW: pure metric functions (D-14/D-16/D-18)
│   ├── plots.py             # fixed minimal set (D-19); presentation only
│   └── (statistics.py engine_logger.py base.py DELETED/absorbed — D-14)
├── universe/
│   └── membership.py        # ONE documented module (or collapse into universe/__init__.py);
│                            #   dynamic.py/static.py/universe.py deleted (D-20)
└── price_handler/feed/
    └── bar_feed.py          # +generate_bar_event factory (from DynamicUniverse, D-20)
```

### Pattern 1: Tagged-union policy types + exhaustive match dispatch

**What:** Each policy kind is its own frozen/slots dataclass; `SizingPolicy` is their union; the resolver dispatches with `match` and closes with `assert_never` so mypy --strict fails compilation if a kind is added without a resolver arm.
**When to use:** The resolver (D-01) and the SLTP resolution (D-13).
**Example:**

```python
# Source: project idiom (core/bar.py frozen/slots precedent) + typing.assert_never (Python 3.13 stdlib)
from dataclasses import dataclass
from decimal import Decimal
from typing import assert_never

@dataclass(frozen=True, slots=True)
class FractionOfCash:
    fraction: Decimal                      # declare as Decimal("0.95") — NEVER Decimal(0.95)
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True)
class FixedQuantity:
    qty: Decimal
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True)
class RiskPercent:
    risk_pct: Decimal                      # qty = (equity × risk_pct) / |price − stop|
    step_size: Decimal | None = None

SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent

def resolve_entry_quantity(policy: SizingPolicy, *, available: Decimal,
                           equity: Decimal, price: Decimal,
                           stop: Decimal | None) -> Decimal:
    match policy:
        case FractionOfCash(fraction=f):
            # MUST reproduce order_manager.py:628 byte-exact for the golden run:
            # (Decimal("0.95") * available) / to_money(price) — same ops, same order.
            qty = (f * available) / price
        case FixedQuantity(qty=q):
            qty = q
        case RiskPercent(risk_pct=r):
            if stop is None or stop == price:
                raise SizingPolicyViolation("RiskPercent requires stop_loss")  # D-06 typed failure
            qty = (equity * r) / abs(price - stop)
        case _:
            assert_never(policy)
    if policy.step_size is not None:        # D-05 — oracle-dark (golden leaves it None)
        qty = qty.quantize(policy.step_size, rounding=ROUND_DOWN)
    return qty
```

### Pattern 2: Pure metric functions on run artifacts (D-14), formulas matched to backtesting.py (D-16)

**What:** Stateless functions over the equity-curve frame (`total_equity` column) and the closed-trades frame (`realised_pnl`, `trade_return` derivable). All denominators guarded; all pandas-2-safe idioms.
**When to use:** `reporting/metrics.py`; called from `run_backtest.py` and tests.
**Example:**

```python
# Source: verified against backtesting.py _stats.py (raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/_stats.py)
import numpy as np
import pandas as pd

PERIODS = 365  # D-16: daily crypto bars (the old periods=355 dies)

def compute_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().fillna(0.0)

def max_drawdown(equity: pd.Series) -> float:
    # D-16: drawdown on equity.cummax(). backtesting.py: dd = 1 − equity/np.maximum.accumulate(equity)
    dd = equity / equity.cummax() - 1.0          # ≤ 0 series; no zero-seeded HWM, no div-by-zero
    return float(dd.min())                        # most-negative value (sign convention: negative)

def sharpe(returns: pd.Series, periods: int = PERIODS) -> float:
    sd = returns.std(ddof=1)                      # pin ddof EXPLICITLY (np.std default is ddof=0!)
    if sd == 0 or len(returns) < 2:
        return 0.0                                # guarded denominator (D-16)
    return float(np.sqrt(periods) * returns.mean() / sd)   # rf = 0 (D-16)

def sortino(returns: pd.Series, periods: int = PERIODS) -> float:
    # Textbook/backtesting.py downside deviation: full-period denominator, target 0:
    # sqrt(mean(clip(r, −inf, 0)^2)) — NOT std of the negative subset (the old bug).
    downside = np.sqrt(np.mean(np.clip(returns.to_numpy(), -np.inf, 0.0) ** 2))
    if downside == 0:
        return 0.0
    return float(np.sqrt(periods) * returns.mean() / downside)

def profit_factor(trades: pd.DataFrame) -> float:
    # D-16 true PF: gross profit / gross loss (the count-ratio `profict_factor` dies).
    pnl = trades["realised_pnl"]
    gross_loss = abs(pnl[pnl < 0].sum())
    if gross_loss == 0:
        return float("inf") if pnl[pnl > 0].sum() > 0 else 0.0   # guard (old code ZeroDivisionError'd)
    return float(pnl[pnl > 0].sum() / gross_loss)

def cagr(equity: pd.Series, periods: int = PERIODS) -> float:
    years = len(equity) / periods
    if years <= 0 or equity.iloc[0] <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)   # .iloc — never equity[-1]

def rolling_sharpe(returns: pd.Series, window: int, periods: int = PERIODS) -> pd.Series:
    # D-18: finishes the rolling-stats stub (the commented-out block in statistics.py:171-177).
    roll = returns.rolling(window)
    return np.sqrt(periods) * roll.mean() / roll.std(ddof=1)
```

### Pattern 3: Slippage attribution computed post-hoc from store frames (D-17) — engine-inert

**What:** Under the next-bar-open fill convention (Phase 6), a fill at bar `T` was decided at bar `T − 1tf`; the decision-bar close is `close(T − 1tf)` in the golden CSV. The slippage columns are therefore computable purely in `run_backtest.py` from the store frame + the trades frame — no engine change, no event change, no Position field.
**When to use:** `run_backtest.py` after `build_trade_log`; the column rides the D-11 re-freezes.
**Example:**

```python
# Source: tests/golden/REFREEZE-M5A.md (verified: new avg_bought == next-bar Open exactly)
def attach_slippage(trades: pd.DataFrame, closes: pd.Series) -> pd.DataFrame:
    # closes: base-frame close indexed by bar open-time (store.read_bars(ticker)['close'])
    # entry fill bar = entry_date; decision bar = the bar immediately BEFORE it in the index.
    idx = closes.index
    def decision_close(fill_time):
        pos = idx.searchsorted(fill_time, side="left")
        return closes.iloc[pos - 1] if pos > 0 else float("nan")
    trades["slippage_entry"] = trades.apply(
        lambda r: float(r["avg_bought" if r["side"] == "LONG" else "avg_sold"]) - decision_close(r["entry_date"]), axis=1)
    trades["slippage_exit"] = trades.apply(
        lambda r: float(r["avg_sold" if r["side"] == "LONG" else "avg_bought"]) - decision_close(r["exit_date"]), axis=1)
    return trades
```

(Exact column naming/shape is planner discretion per CONTEXT; the load-bearing insight is *post-hoc from store data = engine-inert*, with the alternative — carrying decision price on Position/Fill — touching frozen entities for no gain.)

### Pattern 4: Intent contract — value-identical rewrite of SMA_MACD

**What:** `generate_signal(ticker, bars) -> SignalIntent | None`. SMA_MACD's only uses of `self.last_event`/`last_time()` are (a) the window-slice start times and (b) the signal price. Both have value-identical pure substitutes: `bars.index[-1]` equals `event.time` for the golden run (the feed window's last completed bar at tick T is stamped T when timeframe == base), and the handler stamps price from `event.bars[ticker].close` exactly as `_generate_signal` does today.
**When to use:** D-12 conversion of SMA_MACD + empty_strategy + `tests/unit/strategy/test_strategy.py`.
**Example:**

```python
# Source: itrader/strategy_handler/SMA_MACD_strategy.py:47-76 (current) — inert rewrite
def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
    if len(bars) < self.max_window:
        return None
    last_time = bars.index[-1]              # replaces self.last_time() — value-identical (rule 3)
    start_dt = last_time - self.timeframe * self.short_window
    short_sma = trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()
    ...
    if short_sma.iloc[-1] >= long_sma.iloc[-1]:
        if (MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0):
            return self.buy(ticker)         # sugar: builds SignalIntent(action=Side.BUY, ...)
        elif (MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0):
            return self.sell(ticker)
    return None
```

The handler side (StrategiesHandler.calculate_signals, strategies_handler.py:36-59) keeps its push loop and gains: `intent = strategy.generate_signal(ticker, data)` → if not None, build one `SignalEvent` per subscribed portfolio with `time=event.time`, `price=to_money(event.bars[ticker].close)`, policy/direction from the strategy object — the exact construction `Strategy._generate_signal` (base.py:73-115) does today, relocated.

### Pattern 5: Fill-time SLTP resolution — two viable mechanics (planner discretion per D-13)

Both options are oracle-dark (golden has no brackets). The pieces for each already exist:

- **Option A — validated modify path:** children are created at signal time with placeholder prices, rest in the book; on parent EXECUTED, `OrderManager.on_fill` computes final child prices from `fill_event.price` and calls `self.modify_order(...)` → MODIFY OrderEvents (handler already enqueues `on_fill` return events — extend the return list). The full chain exists: `OrderManager.modify_order` (order_manager.py:631) → `OrderEvent(command=MODIFY)` → `SimulatedExchange.on_order` MODIFY branch (simulated.py:278) → `MatchingEngine.modify` (matching_engine.py:103). Risk: a placeholder-priced child resting in the book could trigger before the parent fills — placeholder must be unreachable or children must be held locally.
- **Option B — create children at parent fill (IB attached-order semantics):** for a `PercentFromFill` policy, `_assemble_bracket_and_emit` skips child creation; `on_fill` on the parent's EXECUTED creates, stores, links, and emits the children priced from the actual fill. Cleaner (no placeholder-trigger hazard, no modify round-trip), slightly extends create-all-then-emit (D-11 Phase 4) with a documented "policy children are created at fill" carve-out. The WR-05 orphan-child cancellation logic (order_manager.py:174-184) needs no change — policy children simply don't exist before the parent fills.

Where the policy is readable at fill time: the parent `Order` entity needs to carry it (new optional field) or the manager keeps a pending-bracket map keyed by parent id. The entity field survives storage round-trips; the map is simpler. Planner's call.

### Anti-Patterns to Avoid

- **Matching/sizing in the strategy:** the strategy fans one signal to N portfolios (base.py:89) — a strategy-computed quantity is wrong for every portfolio but one (#31's core argument). Policy declaration only.
- **Re-implementing `DynamicSizer`'s slot-split float math:** the resolver absorbs its *ideas* (close-the-position-on-exit, slot guard) but is written clean in Decimal; the `round(quantity, 5)` and `float()` coercions die with the file.
- **Routing exits through entry sizing:** D-07 is explicit — exits size from `net_quantity × exit_fraction`, never from cash. (Today's SELL-with-no-long falls through to entry sizing and opens a short — that exact fall-through is what the D-08 guard removes.)
- **Adding new keys to `_SUMMARY_NUMERIC_KEYS` / golden files outside the named re-freezes** — frozen-artifact growth rides D-11 only.
- **`reporting` importing handlers** (today `statistics.py` imports `PortfolioHandler`, `Portfolio`, `PriceStore`, sqlalchemy) — the new module imports pandas/numpy only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Metric formula definitions | Your own Sharpe/Sortino/PF variants | The D-16 formulas verified against backtesting.py `_stats.py` (this doc, Pattern 2) | Phase 8 reconciles against backtesting.py + backtrader — any home-grown variant becomes a cross-validation discrepancy to explain |
| Golden frame diffs for new tests | Byte/string compares | `pandas.testing.assert_frame_equal(check_exact=True)` | Existing oracle pattern (test_backtest_oracle.py) gives column-level failure messages |
| Decimal entry | `Decimal(float)` anywhere | `core.money.to_money` (string path) | `Decimal(0.95)` carries the binary float-repr artifact and breaks byte-exactness (core/money.py rule) |
| Policy exhaustiveness checks | Runtime `else: raise` only | `match` + `typing.assert_never` | mypy --strict turns a missing policy arm into a type error at gate time |
| Quantity rounding | Custom floor/modulo | `Decimal.quantize(step, rounding=ROUND_DOWN)` | D-05; stdlib-correct for negative exponents and dust |
| Rolling Sharpe | Manual loop over windows | `returns.rolling(window).mean() / .std(ddof=1)` | One pure pandas expression (D-18); loop versions diverge on ddof/window edges |

**Key insight:** this phase's hard part is not algorithms — every formula is ≤ 5 lines — it is *preserving byte-exactness through a large structural refactor*. The protective discipline is: same Decimal expressions, same operation order, structural no-ops for default-valued new parameters, and the oracle test run after every inert plan.

## Runtime State Inventory

This is a refactor phase — the inventory was checked explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — backtest is fully in-memory (`InMemoryOrderStorage`); the only persistent run state is `tests/golden/*` (in git) and `output/` (gitignored, regenerated per run). Verified by reading `OrderStorageFactory.create('backtest')` wiring and run_backtest.py. | Golden files regenerate at the two D-11 re-freezes only |
| Live service config | None — no external services on the backtest path (CSV store is offline; PostgreSQL/OANDA/Binance are D-sql/D-oanda/D-live, untouched). Verified: `TradingSystem.__init__` wires `CsvPriceStore` only. | None |
| OS-registered state | None — no scheduled tasks, daemons, or service registrations exist for this project. | None |
| Secrets / env vars | None touched — `.env` is loaded by Makefile but nothing this phase renames any key. The hardcoded credential in `sql_store.py` (CONCERNS) is D-sql scope, not this phase. | None |
| Build artifacts | `pyproject.toml` mypy overrides: `itrader.reporting.statistics`, `itrader.reporting.engine_logger`, `itrader.reporting.plots` carry `ignore_errors = true` (pyproject.toml:105-118). When these modules are deleted/rewritten, the override entries MUST be removed or mypy errors on missing modules / silently un-gates the new code. `__pycache__` of deleted packages is gitignored noise. | Remove the three reporting override entries (and the deleted-module entries) in the same plan that deletes/rewrites them |

## Common Pitfalls

### Pitfall 1: Decimal arithmetic *shape* changes break byte-exactness even when values are equal
**What goes wrong:** `tests/golden/trades.csv` serializes raw Decimal reprs (verified: `net_quantity` column contains `0E-27`, prices carry 27+ digits). `Decimal("28.5") * Decimal("1.0") == Decimal("28.50")` — numerically equal, *different repr*. An `exit_fraction` default of 1.0 implemented as a multiplication changes the serialized bytes of every exit-sized trade.
**Why it happens:** Decimal preserves exponent through arithmetic; CSV writes `str(Decimal)`.
**How to avoid:** (a) `exit_fraction == 1` ⇒ return `net_quantity` unchanged — a structural no-op, not an arithmetic identity; (b) the resolver's FractionOfCash arm must reproduce `(Decimal("0.95") * available) / to_money(price)` with the same operands in the same order (order_manager.py:628); (c) declare policy literals via the string path (`Decimal("0.95")`), never `Decimal(0.95)`.
**Warning signs:** oracle numeric test fails with values that *look* identical; diffs only in trailing zeros / exponent notation.

### Pitfall 2: `filterwarnings` nuance — DeprecationWarning is IGNORED, FutureWarning/RuntimeWarning are FATAL
**What goes wrong:** Planning treats all warnings as suite-fatal, or assumes deprecations fail. Reality (pyproject.toml:69-73): `["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`.
**Verified empirically (project venv):** `series[-1]` on a DatetimeIndex → `FutureWarning` (FATAL); chained `df['col'].iloc[0] = x` → `FutureWarning`/ChainedAssignmentError (FATAL); `np.mean` of empty slice → `RuntimeWarning` (FATAL); plotly `append_trace` → `DeprecationWarning` (ignored by the suite — but fix it anyway, removal is announced); plotly `titlefont_size` → **hard `ValueError`, no warning involved** (plots.py:31,55,108,159 raise the moment any figure builds).
**How to avoid:** the D-16 idioms — `.iloc[-1]`, direct column assignment (`df['Drawdown'] = ...` building the series fully formed), explicit empty-subset guards before `np.mean`/`np.max` (the trade-stats `avg_win_pct` on a zero-win frame currently raises), `yaxis=dict(title=dict(text=..., font=dict(size=14)))` for plotly 6.
**Warning signs:** tests pass locally with `-W ignore` habits but fail under `make test`.

### Pitfall 3: Import cycle — typed policy on `SignalEvent` cannot import from `order_handler` at runtime
**What goes wrong:** D-01 puts `SizingPolicy` on the signal; D-04's letter says policy types live in `order_handler/`. But `import itrader.order_handler.anything` executes `order_handler/__init__.py` → imports `order_handler.py` → imports `events_handler.events` → imports `signal.py`; if `signal.py` imports the policy module from `order_handler`, the package is mid-initialization → `ImportError`/partially-initialized-module.
**How to avoid:** Two compliant options (the discretion clause explicitly opens "where the intent type lives ... without circularity"):
1. **Recommended:** event-carried types (`SizingPolicy`, `SLTPPolicy`, `TradingDirection`) in `core/` (e.g. `core/sizing.py`; `TradingDirection` in `core/enums` like every other event-carried enum: `Side`, `OrderType`). `core/` depends on nothing in itrader — both `events_handler` and `order_handler` and `strategy_handler` import downward. The *resolver* (behavior) stays in `order_handler/` per D-04's spirit ("satisfied by capability, not filename").
2. D-04-letter-strict: types in `order_handler/sizing_policy.py`, `signal.py` imports under `if TYPE_CHECKING:` with string annotations — works (dataclasses don't resolve annotations at runtime) but leaves the runtime field untyped-by-import and is fragile against future `get_type_hints` use.
**Warning signs:** `ImportError: cannot import name ... (most likely due to a circular import)` only when the events package is imported first (i.e., in some test orderings, not others).

### Pitfall 4: The 2 golden shorts come from the SELL-falls-through-to-entry-sizing path — know the mechanism before writing the guard
**What goes wrong:** SMA_MACD's short block is commented out (SMA_MACD_strategy.py:79-87), yet `trades.csv` has 2 SHORT trades. Mechanism (verified): an exit SELL trigger fires while no long is open → `_resolve_signal_quantity` finds no open position → falls to the entry branch → fraction-of-cash sizes a SELL → opens a short (the very first golden trade, 2018-06-10 → 2019-03-12, −2176.39 PnL). The D-08 guard must intercept exactly this: `LONG_ONLY` + `Side.SELL` + (no open long or `net_quantity <= 0`) → audited REJECTED — *before* sizing, replacing the silent fall-through.
**Why it matters for the diff note:** the first short spans 9 months during which equity/cash trajectories differ materially; downstream sizing of every subsequent trade changes (fraction-of-cash compounds), so the re-freeze diff is NOT just "2 rows removed" — entry quantities of later trades shift too. The expected-diff note should say so explicitly (REFREEZE-M5A.md is the format precedent).

### Pitfall 5: Audited REJECTED route needs an Order entity — but admission rules fire before sizing
**What goes wrong:** D-06/D-08/D-10 mandate the Phase 4 audited PENDING→REJECTED route (entity + `add_state_change` + storage — order_manager.py:252-258 is the template). But sizing failures today short-circuit *before* entity creation (the DEF-01-B narrow gate, order_manager.py:231-233), returning an un-audited `OperationResult`. A direction-guard rejection has no quantity yet, and `Order.new_order` requires one.
**How to avoid:** options for the planner: (a) build the rejected entity with the unsized quantity (0/None) — safe because the entity is REJECTED before validation, so the deleted zero-quantity bypass is never consulted; (b) size first, then reject — wasteful but uniform; (c) extend the entity factory with a rejected-at-admission constructor. Whichever — the rejection reason string must name the policy violation (D-06) and `triggered_by` should identify the gate (e.g. `"admission_direction"`, `"admission_increase"`), following the `"validator"`/`"cash_reservation"` precedent.
**Warning signs:** rejected signals vanishing from order storage (the pre-Phase-4 regression this route exists to prevent).

### Pitfall 6: Oracle test compares only golden-known columns/keys — new artifacts are oracle-safe to *produce*, but freezing rides the re-freezes
**What goes wrong (or rather, what's easy to misread):** `_trade_numeric` is derived from `golden_trades_sorted.columns` (test_backtest_oracle.py:184-186) and summary checks use fixed tuples (`_SUMMARY_NUMERIC_KEYS`, line 55) — extra columns/keys in fresh `output/` are silently ignored. So `run_backtest.py` may grow the metrics block and slippage columns during the inert workstreams without tripping the gate.
**How to avoid:** plan it deliberately: produce early (so the metric functions are exercised by the real run), freeze at the D-11 re-freezes (regenerate `tests/golden/*`, extend `_SUMMARY_NUMERIC_KEYS`/identity column lists in the oracle test in the SAME commit as the re-freeze, per the REFREEZE-M5A one-commit precedent).
**Warning signs:** a plan that adds new keys to `tests/golden/summary.json` outside a named re-freeze commit.

### Pitfall 7: `EventHandler` constructor change has a mocked-test blast radius
**What goes wrong:** D-20 removes `universe.generate_bar_event` from the TIME route. `EventHandler.__init__` takes `universe: Universe` positionally (full_event_handler.py:48) and three test files construct it with MagicMock universes asserting the routing literal: `tests/unit/events/test_dispatch_registry.py` (asserts `wiring.universe.generate_bar_event` at line 100), `tests/unit/events/test_error_flow.py`, `tests/integration/test_event_wiring.py`. Both trading systems pass `self.universe`.
**How to avoid:** the planner owns the new TIME-route shape (feed-backed factory callable injected by the trading system, or a `bar_event_source` parameter); whatever the choice, update the dispatch-registry assertions and the two trading systems in the same plan. `live_trading_system.py` is mypy-deferred (D-live) but still constructs `DynamicUniverse` (line 111) and calls `init_universe` (line 213) — it must keep importing something that exists.

### Pitfall 8: `PortfolioReadModel` has no equity accessor — RiskPercent needs one
**What goes wrong:** the Protocol (core/portfolio_read_model.py) exposes `available_cash`, `get_position`, `reserve`, `release`, `exchange_for`, `open_position_count` — no `total_equity`. RiskPercent's formula (D-02) is equity-based.
**How to avoid:** add `total_equity(portfolio_id) -> Decimal` to the Protocol + the concrete handler. Note `Portfolio.total_equity` is currently a *float* property (CONCERNS "Float Leaks"); since RiskPercent is oracle-dark, a documented `to_money(float)` coercion at the read-model boundary is acceptable this phase, but computing from Decimal internals (cash + Σ position market values) is preferable if cheap. Either way: unit-test the accessor; do not silently widen the Protocol without the structural-conformance test pattern used in Phase 5.

### Pitfall 9: `strategy_setting` dict deletion ripples beyond the signal
**What goes wrong:** killing the dict (D-01) touches: `SignalEvent.strategy_setting` field (signal.py:67) and every constructor call; `Strategy.setting_to_dict()` (base.py:45-50) and `to_dict()` (base.py:52-60); `DynamicSizer` (reads it — dies anyway, D-04); `StrategiesHandler.assign_symbol` (reads `.settings`, already broken+dead — #31 says delete it, removal is inert: never called); and `tests/unit/strategy/test_strategy.py` (4 tests asserting current signal construction).
**How to avoid:** grep-audit `strategy_setting` and `setting_to_dict` in the plan that retypes the signal; convert `test_strategy.py` to the intent contract in the same plan (CONTEXT lists it explicitly).

### Pitfall 10: Drawdown sign and ddof conventions must be pinned once, in writing
**What goes wrong:** backtesting.py reports Max DD as a negative percentage (`dd.min()` where dd ≤ 0); the broken legacy code produced positive magnitudes from a zero-seeded HWM. `np.std` defaults ddof=0; `pandas.Series.std` defaults ddof=1 — a silent factor on every Sharpe/Sortino. These don't break tests; they create Phase 8 reconciliation noise and hand-computed-fixture mismatches.
**How to avoid:** pin in the metrics module docstring: drawdown sign (recommend negative, matching backtesting.py), ddof=1 (sample std, matching pandas default and backtesting.py's `ddof=int(bool(...))` for n>1), annualization 365, rf=0. Hand-computed test fixtures must use the same pins.

### Pitfall 11: `aggregate_returns`' un-raised ValueError, and `_temporal_statistics`' `is np.nan` bug — decide their fate explicitly
**What goes wrong:** `performance.py:28` constructs but never raises `ValueError`; `statistics.py:147` `x is np.nan` is always False for computed NaNs (verified: `float('nan') is np.nan` → False). D-14's pure-module rewrite supersedes both files, but if the temporal/monthly stats are *not* carried into the new module, the bugs die by deletion — the plan must say which functions survive (D-15 lists the frozen set: sharpe, sortino, cagr, max drawdown, profit factor, win rate; rolling sharpe per D-18; temporal/monthly aggregations are NOT in the frozen set and may be dropped or kept unfrozen).
**Warning signs:** a "fix `is np.nan`" task pointing at a file the same phase deletes.

## Code Examples

(See Patterns 1-5 above for the five load-bearing examples: policy union + resolver, metric functions, post-hoc slippage, intent-contract rewrite, fill-time SLTP options. All are sourced from the verified current code or backtesting.py source.)

### Hand-computable metric fixture (D-22 pattern)

```python
# Synthetic equity: 100 → 110 → 99 → 121
# returns: [0, 0.10, -0.10, 0.2222...]; cummax: [100, 110, 110, 121]
# drawdown: [0, 0, -0.10, 0]  → max_drawdown == -0.10 exactly
equity = pd.Series([100.0, 110.0, 99.0, 121.0])
assert max_drawdown(equity) == pytest.approx(-0.10)
```

### plotly 6 axis-title API (the `titlefont_size` fix)

```python
# Source: verified against plotly 6.8.0 in the project venv (titlefont_size raises ValueError)
chart.update_layout(
    yaxis=dict(title=dict(text='[%]', font=dict(size=14)), tickfont=dict(size=12)),
)
# and: append_trace(...) → add_trace(..., row=r, col=c)   (deprecated; removal announced)
```

## State of the Art

| Old Approach (current code) | Current Approach (this phase) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `series[-1]` positional on Series | `.iloc[-1]` | pandas 2.x deprecation (FutureWarning today, removed in 3.0) | suite-fatal under filterwarnings — verified |
| `df['col'].iloc[0] = x` chained assignment | build column whole / `df.loc[...]` | pandas 2.x CoW transition | suite-fatal — verified |
| plotly `titlefont_size` / `append_trace` | `title=dict(font=dict(size=...))` / `add_trace(row=,col=)` | plotly 6.0 removed `titlefont` | hard ValueError — verified |
| Count-ratio "profict factor", subset-std Sortino, zero-seeded HWM drawdown, periods=355 | backtesting.py-matched formulas (Pattern 2), periods=365 | D-16 (this phase) | Phase 8 cross-validation becomes like-for-like |
| Untyped `strategy_setting` dict on the signal | Frozen `SizingPolicy`/`TradingDirection` typed fields | D-01/D-08 (this phase) | mypy-checked signal contract |
| `universe.generate_bar_event` on the TIME route | BarFeed-owned factory | D-20 (this phase) | universe becomes a pure membership stub |

**Deprecated/outdated (dying this phase):** `EngineLogger` (SQLAlchemy 1.x APIs, reads non-existent FillEvent fields — verified imported nowhere), `StatisticsReporting._prepare_data`/`_to_sql` (reads non-existent `portfolio.metrics`; `self.engine` never assigned), `StaticUniverse` + `Universe.get_assets` ABC (unused, contract never honored), `DynamicSizer`/`RiskManager`/`sltp_models` (zero instantiations outside their own files — verified), the validator `ZERO_QUANTITY_TRANSITION` warning bypass (order_validator.py:219-225), `StrategiesHandler.assign_symbol` (dead + would AttributeError), the `cash < 30` floor (risk_manager:75, never wired).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The golden run contains BUY-while-long signals (position increases), making D-10 result-changing — inferred from SMA_MACD logic (SELL exit gated by the SMA filter can be skipped, allowing consecutive BUY triggers), not counted empirically | Pitfall 4 / re-freeze 2 | If zero increases exist post-guard, re-freeze 2 is a no-diff re-freeze — harmless; the diff note simply records N=0 |
| A2 | `bars.index[-1] == event.time` for every golden tick where SMA_MACD signals (timeframe == base timeframe), making the `last_time()` → `bars.index[-1]` substitution value-identical | Pattern 4 | Oracle behavioral test catches any divergence immediately; bar-timing contract rule 3 supports it |
| A3 | backtrader's analyzer formulas are compatible with the D-16 definitions (only backtesting.py's source was verified this session) | D-16 | Phase 8 owns reconciliation; tolerance/diff-explanation happens there |
| A4 | Live-system universe call sites can be satisfied by a minimal shim (live is D-live, mypy-deferred, untested) without a dedicated live plan | Pitfall 7 | Worst case: one extra small task to keep `live_trading_system.py` importing |

All other claims in this document are `[VERIFIED]` (direct file reads, empirical venv checks) or `[CITED]` (backtesting.py source).

## Open Questions

1. **Where exactly do rejected-at-admission orders get their quantity?** (Pitfall 5 options a/b/c)
   - What we know: the audited route requires an entity; sizing currently precedes entity creation.
   - What's unclear: which option the planner prefers; all three are correct.
   - Recommendation: option (a) — entity with quantity 0 + immediate REJECTED transition; cheapest, and the REJECTED state means the dead validator bypass is irrelevant.
2. **Does `SignalIntent` live in `core/` or `strategy_handler/`?**
   - What we know: it is NOT event-carried (it's the strategy→handler return value), so the Pitfall-3 cycle does not constrain it; `strategy_handler` already imports `core` and could import `order_handler` safely (no reverse import).
   - Recommendation: co-locate with `SizingPolicy` in `core/` for one coherent vocabulary module — but `strategy_handler/` is equally safe.
3. **Frozen metrics block schema** (planner discretion per CONTEXT): flat keys (`"sharpe": ...`) vs nested (`"metrics": {...}`) in summary.json — nested keeps `_SUMMARY_NUMERIC_KEYS` churn to one entry but changes the comparison code; flat reuses the existing key-loop verbatim. Recommendation: nested block + one dict-equality assertion added at re-freeze 1.
4. **Should the universe membership stub still feed the missing-ticker warning loop** currently in `generate_bar_event` (dynamic.py:75-77)? The feed factory can accept the membership list for the warning, or the warning dies with the module. Low stakes; recommend keeping the warning (it caught sparse-universe gaps in Phase 6).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (pyenv) | everything | ✓ | 3.13.1 | — |
| Poetry + in-project `.venv` | all commands | ✓ | (verified via `poetry run`) | — |
| pandas | metrics, feed | ✓ | 2.3.3 | — |
| numpy | metrics | ✓ | 2.2.6 | — |
| plotly | presentation module | ✓ | 6.8.0 | — |
| pytest (+cov, +watch, +html) | suite | ✓ | 8.4.2 | — |
| mypy | strict gate | ✓ | ^2.1.0 (poetry) | — |
| Golden dataset | oracle runs | ✓ | `data/BTCUSD_1d_ohlcv_2018_2026.csv` (committed) | — |
| PostgreSQL | NOT required | n/a | — | backtest path is CSV-only; SQL is D-sql |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. The phase is fully executable in the current environment.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (strict markers, strict config, `filterwarnings=["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`); markers auto-derived from folder in `tests/conftest.py` |
| Quick run command | `poetry run pytest tests/unit -m unit -x -q` |
| Full suite command | `make test` (= `poetry run pytest`) |
| Oracle gate | `poetry run pytest tests/integration/test_backtest_oracle.py -q` (runs the full 2018→2026 backtest in-process; slow) |
| Type gate | `make typecheck` (mypy --strict over `itrader`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M5-06 | Resolver: each policy kind → expected Decimal quantity; step_size ROUND_DOWN; exit_fraction (incl. 1.0 structural no-op + remainder rule); typed failures | unit | `poetry run pytest tests/unit/order/test_sizing_resolver.py -x` | ❌ Wave 0 (test-with-code, D-24) |
| M5-06 | Admission: LONG_ONLY SELL-no-long → audited REJECTED; allow_increase=False BUY-while-long → REJECTED; LONG_SHORT rejected at registration; increase+reserve coverage | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -x` | ❌ Wave 0 |
| M5-06 | `generate_signal` intent contract: synthetic crossover frames → expected SignalIntent; handler fan-out builds correct SignalEvents | unit | `poetry run pytest tests/unit/strategy/ -x` | ⚠️ `test_strategy.py` exists (4 tests) — must CONVERT to intent contract |
| M5-06 (inertness) | Entire sizing refactor reproduces M5a goldens byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py` | ✅ exists |
| M5-07 | Metric functions vs hand-computed fixtures (sharpe/sortino/cagr/max_dd/PF/win_rate/rolling_sharpe); guarded denominators (no-loss PF, zero-std sharpe, empty subsets) | unit | `poetry run pytest tests/unit/reporting/test_metrics.py -x` | ❌ Wave 0 |
| M5-07 | Plots smoke: each figure builds without raising under `-W error::FutureWarning` semantics | unit | `poetry run pytest tests/unit/reporting/test_plots_smoke.py -x` | ❌ Wave 0 |
| M5-07 (freeze) | Frozen metrics block + slippage columns match goldens | integration | oracle test, extended at the D-11 re-freezes | ✅ exists (extend at re-freeze) |
| M5-08 | Membership stub: union of strategy tickers ∪ screener set; tuple-pair flattening (from `get_strategies_universe`) | unit | `poetry run pytest tests/unit/universe/test_membership.py -x` | ❌ Wave 0 |
| M5-08 | TIME-route rewiring: dispatch registry asserts the new bar-event source | unit | `poetry run pytest tests/unit/events/test_dispatch_registry.py -x` | ⚠️ exists — must UPDATE (asserts `universe.generate_bar_event` today) |
| M5-09 | TC2 CSV part | unit | `poetry run pytest tests/unit/price/ -x` | ✅ exists (test_csv_store.py 6 tests, test_bar_feed.py 13 tests) — audit for gaps only |
| M5-09 | TC4 reporting / TC6 universe | unit | covered by the M5-07/M5-08 rows above | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit -m unit -x -q` + `make typecheck`
- **Per wave merge:** `make test` (full suite incl. integration/oracle)
- **Inert-workstream gate:** oracle test green (byte-exact) before ANY result-changing plan starts (CONTEXT sequencing discretion: structural-first)
- **Phase gate:** full suite green + both D-11 re-freezes signed off before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/order/test_sizing_resolver.py` — M5-06 resolver (test-with-code)
- [ ] `tests/unit/order/test_admission_rules.py` — M5-06 direction/increase guards (test-with-code)
- [ ] `tests/unit/reporting/test_metrics.py` — M5-07 metric functions (+ `tests/unit/reporting/__init__` dir creation; folder-derived `unit` marker applies automatically)
- [ ] `tests/unit/reporting/test_plots_smoke.py` — M5-07 presentation smoke
- [ ] `tests/unit/universe/test_membership.py` — M5-08 stub
- [ ] CONVERT `tests/unit/strategy/test_strategy.py` (4 tests assert the old `buy()/sell()` → queue flow) to the intent contract
- [ ] UPDATE `tests/unit/events/test_dispatch_registry.py`, `tests/unit/events/test_error_flow.py`, `tests/integration/test_event_wiring.py` (mock/route the new bar-event source)
- Framework install: none — pytest infrastructure complete.

## Security Domain

This phase touches an offline, single-user backtest engine with no network surface, no auth, no sessions. ASVS applicability:

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | no auth surface on the backtest path |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes (narrow) | Policy params validated at construction (`fraction ∈ (0,1]`, `risk_pct > 0`, `step_size > 0` or None) — fail-loud typed errors per D-06; CSV input validation already exists (`test_csv_store.py` malformed-column tests) |
| V6 Cryptography | no | — |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via table names (legacy `_to_sql` DROP TABLE f-string) | Tampering | **Dies this phase** — `_to_sql` deleted (D-14); nothing replaces it (D-sql owns any rebirth) |
| Hardcoded credentials (`sql_store.py:17`) | Information disclosure | Out of phase scope (D-sql) — do NOT touch; already tracked in CONCERNS |
| Unvalidated policy params producing absurd orders | Tampering/DoS (self) | Frozen dataclass `__post_init__` validation + D-06 loud rejection |

No new attack surface is introduced; net security posture improves (an injection-bearing dead path is deleted).

## Sources

### Primary (HIGH confidence)
- Direct file reads of the working tree (branch `implement-phase-7`, clean): `order_manager.py`, `order_validator.py`, `strategy_handler/*`, `reporting/*`, `universe/*`, `bar_feed.py`, `full_event_handler.py`, `events/signal.py`, `portfolio_read_model.py`, `backtest_trading_system.py`, `run_backtest.py`, `tests/golden/*`, `tests/integration/test_backtest_oracle.py`, `pyproject.toml`, Makefile — all line references in this document point at the current tree
- Empirical verification in the project venv (`poetry run python -W error`): pandas 2.3.3 `series[-1]`/chained-assignment FutureWarnings, numpy 2.2.6 empty-slice RuntimeWarning, `float('nan') is np.nan == False`, plotly 6.8.0 `titlefont` ValueError + `append_trace` DeprecationWarning
- backtesting.py `_stats.py` source (raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/_stats.py) — profit factor, Sharpe, Sortino, max drawdown, CAGR formulas `[CITED]`

### Secondary (MEDIUM confidence)
- `.planning/codebase/ARCHITECTURE-REVIEW.md` (#14, #24, #31, #33, #38), `.planning/codebase/CONCERNS.md`, `.planning/COVERAGE-INDEX.md` (TC2/TC4/TC6) — authoritative project analysis, spot-verified against code during this session
- `tests/golden/REFREEZE-M5A.md` — re-freeze format precedent + next-bar-open fill verification

### Tertiary (LOW confidence)
- A3 (backtrader formula compatibility) — not verified this session; Phase 8 scope

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; versions read from the live venv
- Architecture (seams, blast radius, cycle analysis): HIGH — every seam read directly; cycle traced through actual `__init__` chains
- Pitfalls: HIGH — library pitfalls verified empirically; Decimal-repr pitfall verified against the actual golden CSV bytes
- Metric formulas: HIGH for backtesting.py alignment (source cited); MEDIUM for backtrader (deferred to Phase 8)

**Research date:** 2026-06-07
**Valid until:** ~2026-07-07 (stable in-repo domain; re-verify only if `poetry.lock` changes pandas/plotly majors)
