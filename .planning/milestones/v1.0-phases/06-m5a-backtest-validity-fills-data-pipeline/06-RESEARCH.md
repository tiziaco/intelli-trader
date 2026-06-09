# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline - Research

**Researched:** 2026-06-06
**Domain:** Event-driven backtest engine correctness — bar timing, fill simulation, OHLCV resampling, data-pipeline seams (brownfield refactor, no new dependencies)
**Confidence:** HIGH (all findings verified against the live codebase and the in-environment pandas 2.3.3)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Bar-timing & fill convention (M5-01, #21)
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

#### Fill realism & fee/slippage (M5-04, #28, PERF1)
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

#### Bar struct & data pipeline (M5-02, M5-03, M5-05, #3, #4, #30)
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

#### Oracle discipline & sequencing (phase gate)
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

### Deferred Ideas (OUT OF SCOPE)
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
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M5-01 | Backtest validity fixed — resampling look-ahead removed, limit fills no longer slip past the limit, bar-timing documented and consistent between same/other-timeframe branches *(#21)* | Look-ahead mechanism pinpointed and empirically verified (`data_outils.py:23` `label='right'` + `data_provider.py:342` `time+timeframe` upper bound); the precise timing contract is formalized in "Pattern 1: The Bar-Timing Contract"; limit-slippage violation located at `simulated.py:192-195` (post-matching multiply) with the fix path in Pattern 4 |
| M5-02 | Per-tick payload is an immutable `Bar` struct; `hasattr` ladders and `get_last_close` type-branching disappear *(#3, FR1)* | Bar struct design in Pattern 3 (frozen/slots/kw_only Decimal dataclass mirroring `events/base.py`); full consumer inventory (9 itrader sites + 9 test files) in Integration Surface |
| M5-03 | Resampled frames precomputed once per (ticker, timeframe) at load and sliced per tick — no `resample` in the hot loop *(#4)* | Precompute + `searchsorted` slice mechanics in Pattern 2, empirically verified; pandas offset-alias hazard (`'m'` = month-end in pandas 2.3.3!) verified and documented in Pitfall 2 |
| M5-04 | Fee/slippage models correct — maker fees live, tiered model fixed (→ deleted per D-10), validation consistent, slippage not misapplied to limit fills; `time.sleep(0.1)` gated/removed *(#28, PERF1)* | Defect locations confirmed (`simulated.py:191/194` hardcoded `order_type="market"`, `:270` sleep, slippage `base.py:59-85` bool contract vs fee `base.py:52-88` raise contract); maker/taker context-passing path in Pattern 4; Decimal-native retype boundaries in Pattern 5 |
| M5-05 | Price handler splits into Provider/Store/Feed seams with offline-vs-runtime lifecycle; run path read-only, loud missing-data errors; bare `except:`→`None` and `to_megaframe` tz/key bugs fixed; strategies use the resampled-bars API *(#30, #27 price seam, FR6, FR7, FR8, PERF4)* | Package layout + Protocol surfaces in Pattern 6; the full `PriceHandler` consumer inventory for the D-18 deletion (8 production consumers found); FR7 bare-except sites at `data_provider.py:245,271`; FR8 megaframe bugs at `:374,377` |
</phase_requirements>

## Summary

This phase is a pure brownfield refactor: **zero new packages**, no network, no external
services. Everything needed already exists in the repo — pandas 2.3.3, stdlib `decimal`,
the Phase 4 frozen-event machinery, the Phase 3/5 storage-seam pattern, and a MatchingEngine
that (crucially) **already contains the `OrderType.MARKET` → fill-at-next-open branch and the
`execution_timing` switch** (`matching_engine.py:123-125`, `simulated.py:67-68`). The D-13
"market orders rest in the book" change is largely *flipping an existing switch and deleting
the immediate path*, not building new matching machinery.

The research verified the two load-bearing external facts empirically against the
in-environment pandas 2.3.3: (1) `label='left', closed='left'` stamps resampled buckets by
open time and the trailing forming bucket IS included by pandas — the completed-bars rule
must be enforced by the Feed's slice, not by resample alone; (2) the offset alias `'m'`
(which `timedelta_to_str` produces for minutes) is interpreted by pandas as **month-end** and
raises a FutureWarning that the strict test config escalates to an error — the new Feed must
own a correct timeframe→offset-alias mapping.

The dominant planning risk is not technical novelty but **oracle sequencing**: of the five
requirements, only the next-bar-open fill change (D-01/D-13) is guaranteed to change the
golden numbers. The look-ahead fix and limit-fill fixes are likely oracle-neutral on the
golden run (the same-timeframe branch already conforms to "last closed bar ≤ T", and
`SMA_MACD` emits market orders with `sl=0, tp=0` — no resting stop/limit legs on the golden
path). The planner should classify workstreams accordingly (suggested split below) and expect
**one, possibly two** re-freezes rather than three.

**Primary recommendation:** Land all structural workstreams first (Bar struct → Store/Feed
split → precompute → Decimal retype, each proven byte-exact against today's oracle), then land
the single result-changing fill-timing fix last with one owner-gated re-freeze. Use the
existing in-repo patterns (frozen-event dataclass, storage Protocol + factory, `to_money`
string entry) for every new component.

## Architectural Responsibility Map

This is a single-process Python engine; tiers here are the internal architectural layers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bar-timing contract / look-ahead safety | **Feed** (`price_handler/feed/`) | tests (regression lock) | D-02: engine invariant enforced in exactly one place — never a strategy responsibility |
| Window construction (per-tick history) | **Feed** | StrategiesHandler (push caller) | D-20: strategies never choose the as-of time |
| Resample precompute | **Feed** (at construction/load) | Store (supplies base frames) | #4: precompute at load, slice per tick |
| OHLCV persistence & read path | **Store** (`price_handler/store/`) | — | D-16: run path read-only, loud errors |
| External data fetch | **Provider** (quarantined, dormant) | ingestion stub | FR6: never in the run loop |
| Current-bar fact distribution | **BarEvent (Bar struct)** | Universe (constructs BarEvent from Feed) | D-15: event = fact, feed = query |
| Order matching (market/stop/limit triggers, OCO) | **MatchingEngine** | — | D-13: one matching path, one resting book |
| Fee/slippage application + fill emission | **SimulatedExchange `_emit_fill`** | fee/slippage models | D-11/D-12: order context passed in, Decimal-native |
| Fill reconciliation (mirror) | **OrderManager `on_fill`** | — | unchanged; partial-fill plumbing deleted (D-06) |
| Mark-to-market / equity | **PortfolioHandler** | Bar struct (Decimal close) | D-05: close-marked equity, unchanged behavior |
| System wiring (Store+Feed construction) | **TradingSystem** | LiveTradingSystem (D-live minimal) | D-18: PriceHandler deleted, systems wire seams directly |
| Oracle gate | **tests/integration/test_backtest_oracle.py** | scripts/run_backtest.py | D-21 hybrid discipline |

## Standard Stack

### Core (all already installed — no additions)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 | Store frames, precomputed resampled frames, float64 Feed windows | Already the data backbone; `resample(label='left', closed='left')` + `DatetimeIndex.searchsorted` verified in-environment `[VERIFIED: ran against the project venv]` |
| python stdlib `decimal` | 3.13.1 | Bar OHLCV fields, MatchingEngine math, fee/slippage retype | Locked program decision; `core/money.to_money`/`quantize` policy already exists `[VERIFIED: itrader/core/money.py]` |
| python stdlib `dataclasses` | 3.13.1 | `Bar` value object (`frozen=True, slots=True`) | Mirrors the Phase 4 `Event` base pattern (`events/base.py`) `[VERIFIED: codebase]` |
| python stdlib `typing.Protocol` | 3.13.1 | `PriceProvider` / `PriceStore` / `BarFeed` seams | Mirrors `AbstractPriceHandler` / order-storage / `PortfolioStateStorage` precedent `[VERIFIED: codebase]` |
| pytest | 8.4.2 | Test-with-code (D-24) | Existing suite; strict markers/filterwarnings `[VERIFIED: pyproject.toml]` |
| mypy | 2.1.0 | `--strict` gate on new packages | `make typecheck` gate live `[VERIFIED: poetry run mypy --version]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ta` | 0.11.0 | SMA/MACD indicators in the reference strategy | Unchanged — operates on the float64 Feed window (D-17) |
| `uuid-utils` | installed | Event/order IDs | Unchanged |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `@dataclass(frozen=True, slots=True)` Bar | `NamedTuple` | NamedTuple is lighter but breaks the project's frozen-dataclass house style and loses `kw_only` clarity; dataclass matches `events/base.py` — use the dataclass |
| `DatetimeIndex.searchsorted` slice | `.loc[start:end]` label slice | `.loc` is fine for correctness but `searchsorted` + `iloc` gives O(log n) positional windows without label-boundary ambiguity at duplicate/missing stamps; either acceptable — `searchsorted` recommended for the hot loop |
| pandas `resample` at load | hand-rolled groupby bucketing | Never hand-roll OHLCV aggregation (see Don't Hand-Roll) |

**Installation:** none — no new packages.

**Version verification:** all versions read from the live environment (`poetry run python`,
`pyproject.toml`, `poetry.lock` present). No registry lookups needed.

## Package Legitimacy Audit

**This phase installs no external packages.** All work uses already-locked dependencies
(pandas 2.3.3, pytest 8.4.2, mypy 2.1.0) and the Python 3.13 stdlib. slopcheck not run — not
applicable.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Project Constraints (from CLAUDE.md)

- **Queue-only cross-domain communication** — handlers never call each other; emit events.
  The Feed is NOT a handler: it is a read-model injected into StrategiesHandler/Universe the
  same way PriceHandler is today (construction-time dependency, not queue traffic). This is
  the established pattern (`StrategiesHandler.__init__(global_queue, price_handler)`).
- **Money = Decimal end-to-end**; float money is a correctness defect. D-12/D-14 complete this.
- **Tabs in handler modules; spaces in config/ and newer modules.** New `price_handler`
  packages, `Bar`, and new tests = spaces. Edits to `matching_engine.py` (spaces),
  `simulated.py` (tabs), `strategies_handler.py` (tabs), `universe/dynamic.py` (tabs),
  `backtest_trading_system.py` (tabs) — match each file.
- **`pyproject.toml` strictness:** `filterwarnings=["error", "ignore::UserWarning",
  "ignore::DeprecationWarning"]` — **FutureWarning is NOT ignored** and pandas 2.3.3 emits
  FutureWarning for deprecated offset aliases (verified). `--strict-markers`/`--strict-config`;
  markers limited to the declared list.
- **Import side effects:** `itrader/__init__.py` initializes `config`/`logger`/`idgen` on
  import — new modules follow the existing `from itrader import idgen` style.
- **`mypy --strict` clean** for in-scope code; quarantined modules keep `ignore_errors`
  overrides — **override module paths in `pyproject.toml` must be updated when modules are
  relocated** (see Pitfall 7).
- **Run tests via Poetry/make** (`make test`, `make typecheck`, `make backtest`).

## Architecture Patterns

### System Architecture Diagram

Target data flow after the split (run path only; ingestion is offline and dormant):

```
                       OFFLINE (stub this phase)
  Provider (CCXT/OANDA/stream — quarantined) ──fetch──> Store.write_bars()
 ─────────────────────────────────────────────────────────────────────────
                       RUNTIME (read-only, no network)

  CsvPriceStore.load() ──base frames──> BarFeed.__init__
                                          │  precompute resampled frames
                                          │  once per (ticker, timeframe)
  TimeGenerator (ticks = store index)     │
        │ TimeEvent(T)                    │
        ▼                                 │
  Universe.generate_bar_event ──asks──> BarFeed.current_bars(T) → dict[str, Bar]
        │ BarEvent(time=T, bars={tkr: Bar})
        ▼
  EventHandler BAR route (order is law):
    1) PortfolioHandler.update_portfolios_market_value   (bars[t].close, Decimal)
    2) ExecutionHandler.on_market_data ──> SimulatedExchange ──> MatchingEngine.on_bar
         resting MARKET fills at Bar.open (next-open rule)        │ FillDecision (Decimal)
         resting STOP/LIMIT trigger vs Bar.high/low               ▼
         ── _emit_fill(order context → maker/taker fee, slippage only for MARKET/STOP)
         ── FillEvent(EXECUTED, price, commission)  → queue
    3) StrategiesHandler.calculate_signals
         ──asks──> BarFeed.window(ticker, timeframe, max_window, asof=T)  (float64 frame,
         │          completed bars only — look-ahead enforced HERE)
         ▼
       Strategy.calculate_signal(window, current Bar) → SignalEvent → ORDER → rests in book
                                                        (fills next BAR at its open)
```

Component-to-file mapping is in the Integration Surface table below.

### Recommended Project Structure

```
itrader/
├── core/
│   └── bar.py                  # Bar value object (frozen/slots, Decimal OHLCV) — NEW
├── price_handler/
│   ├── __init__.py              # re-export Protocols + concrete backtest impls
│   ├── providers/
│   │   ├── base.py              # PriceProvider Protocol (fetch_ohlcv, get_symbols) — NEW
│   │   ├── ccxt_provider.py     # RELOCATED exchange/CCXT.py — untouched (D-oanda)
│   │   ├── oanda_provider.py    # RELOCATED exchange/OANDA.py — untouched (D-oanda)
│   │   └── binance_stream.py    # RELOCATED live_streaming/BINANCE_Live.py — untouched (D-live)
│   ├── store/
│   │   ├── base.py              # PriceStore Protocol: read_bars/write_bars/has/symbols/index — NEW
│   │   ├── csv_store.py         # inherits _load_csv_data logic — NEW (tested)
│   │   └── sql_store.py         # RELOCATED sql_handler.py — untouched (D-sql)
│   ├── feed/
│   │   ├── base.py              # BarFeed Protocol (window, current_bars, megaframe) — NEW
│   │   └── bar_feed.py          # the ONE impl: precompute + look-ahead-safe slices — NEW (tested)
│   └── ingestion.py             # stub entry point: provider.fetch() → store.write() — NEW
└── (DELETED: price_handler/data_provider.py, price_handler/base.py,
             price_handler/exchange/, price_handler/live_streaming/,
             execution_handler/fee_model/tiered_fee_model.py)
```

Relocations are pure `git mv` commits (Phase 3 precedent), separate from logic commits.
`Bar` in `itrader/core/bar.py` (sibling of `money.py`/`ids.py`/`clock.py`) — it is consumed by
events, matching, portfolio, and feed, so it belongs in the dependency-free core layer.

### Pattern 1: The Bar-Timing Contract (M5-01 / D-01..D-05) — document + assert verbatim

**What:** the single written invariant every component is tested against. The golden CSV is
open-time stamped (verified: `Open time` 00:00:00 UTC, `Close time` 23:59:59.999 — Binance
kline shape), and ticks ARE the open timestamps (`TimeGenerator.set_dates(store index)`).

The contract, precisely:

1. **Bars are stamped by open time** (D-04). Bar stamped `T` covers `[T, T + tf_base)`.
2. **The tick at `T` means "the bar stamped `T` just closed."** Wall-clock semantics of the
   tick are `T + tf_base`, but it is labeled `T`.
3. **Decision visibility at tick `T`:** all base bars stamped `≤ T` (every one of them is
   closed by rule 2). The same-timeframe window is the last `N` bars stamped `≤ T` — this is
   what `get_bars(start, T)` already returns, so the same-tf branch is *already conformant*.
4. **Resampled visibility at tick `T`:** a resampled bucket stamped `B` (label='left',
   closed='left', covering `[B, B + TF)`) is visible iff its last base bar has closed:
   **`B + TF ≤ T + tf_base`**, equivalently `B ≤ T − TF + tf_base`. The forming bucket is
   invisible. (Worked example: base 1d, TF=7d, tick T=Sun Jan 7. Bucket B=Mon Jan 1 covers
   Jan 1–7; its last base bar is stamped Jan 7 = T and closed at the tick → visible. At
   T=Sat Jan 6 it is NOT visible.) This rule and rule 3 coincide when TF = tf_base — the
   D-02 "both branches agree" requirement.
5. **Fills:** a market order decided at tick `T` rests in the book and fills at the open of
   the bar stamped `T + tf_base`, at tick `T + tf_base`, with `FillEvent.time = T + tf_base`
   (the BAR event time). Guaranteed by the BAR route order: portfolios → execution →
   strategies (`full_event_handler.py:72-76`) — strategy orders from tick `T` cannot be
   matched until the next BAR event.
6. **Equity at tick `T`** = cash + positions × close of bar stamped `T` (D-05, unchanged).
7. **Last-bar edge:** orders decided on the final tick never fill (no next bar). Document; do
   not special-case.

**When to use:** put this contract in the Feed module docstring (or a `docs/`/module-level
doc) and assert each numbered rule in the D-24 regression tests.

### Pattern 2: Precompute-then-slice (M5-03 / #4)

**What:** at `BarFeed` construction, for each `(ticker, timeframe)` pair required by
registered strategies (collect declarations before feed construction, or lazily on first
request — planner's choice; eager-from-declarations is simpler to test), compute the
resampled frame ONCE; per tick, return a positional slice.

**Example (verified mechanics against pandas 2.3.3):**

```python
# Source: verified empirically in the project venv (pandas 2.3.3)
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

# at load — once per (ticker, timeframe):
resampled = base_frame.resample(offset_alias, label="left", closed="left").agg(_AGG)
# NOTE: pandas KEEPS the trailing forming bucket (verified: 10 daily bars / '7D'
# -> 2 buckets, the 2nd partial). Visibility is enforced at slice time, not here.

# per tick — O(log n), no resample in the loop:
cutoff = asof_time - resample_tf + base_tf      # rule 4: B <= T - TF + tf_base
pos = resampled.index.searchsorted(cutoff, side="right")
window = resampled.iloc[max(0, pos - max_window):pos]
```

For the same-timeframe branch the cutoff degenerates to `asof_time` (`side='right'` includes
the bar stamped `T`). Frames stay float64 (D-17). Key by `(ticker, timeframe_str)` with a
canonical timeframe string (see Pitfall 2 for the alias mapping).

**Anti-pattern avoided:** LRU caching of `(ticker, tf, window, asof)` keys — sequential
forward walk makes recency caching useless and leaves resample in the loop (#4).

### Pattern 3: The `Bar` value object (M5-02 / D-14/D-15)

**What:** mirror the `events/base.py` frozen pattern; convert float64 store values exactly
once via the string path.

```python
# Source: pattern mirrors itrader/events_handler/events/base.py (verified in repo)
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    time: datetime          # open-time stamp (D-04)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_row(cls, time: datetime, row: "pandas row/mapping") -> "Bar":
        # Decimal(str(x)) — the D-04 string path; NEVER Decimal(float).
        return cls(time=time, open=Decimal(str(row["open"])), ...)
```

**Inertness argument (for D-21 classification):** today the float close reaches money via
`to_money(float)` = `Decimal(str(float))` (`strategy_handler/base.py:102`,
`matching_engine` → `new_fill`). `Bar` construction performs the *same* `Decimal(str(x))` on
the *same* float64 values, so every downstream Decimal is bit-identical — the Bar struct
workstream is provably inert.

`BarEvent` becomes `bars: dict[str, Bar]`; delete `get_last_close/open/high/low` (the four
`hasattr` ladders, `events/market.py:58-159`). Consumers collapse to `event.bars[t].close`.
A ticker with no bar at `T` is simply absent from the dict (sparse universe — the WR-12 guard
in `strategy_handler/base.py:80-87` adapts to a `KeyError`/`get` check).

### Pattern 4: One matching path — market orders rest in the book (D-01/D-03/D-11/D-13)

**What already exists (do not rebuild):**
- `MatchingEngine._evaluate` has the MARKET branch: "next-bar market order: unconditional
  fill at the open" (`matching_engine.py:123-125`).
- `SimulatedExchange.on_order` routes `MARKET + execution_timing=="immediate"` to
  `execute_order`, everything else to `matching_engine.submit` (`simulated.py:252-255`).
- Stop gap fills are already pessimistic and D-03-conformant: SELL stop `min(open, trigger)`,
  BUY stop `max(open, trigger)` (`matching_engine.py:127-133`).

**What changes:**
1. Remove the immediate path: market orders always `submit()` to the book (delete
   `execution_timing` and `execute_order`'s immediate-fill role; pre-trade validation/rejection
   still runs at `on_order` time so `FillEvent(REFUSED)` reconciliation is preserved).
2. **Limit gap-through fills at the better open** (D-03 changes current behavior, which fills
   at trigger even on favorable gaps — `matching_engine.py:135-144`):
   - SELL limit: `open >= trigger → fill at open`, else `high >= trigger → fill at trigger`.
   - BUY limit: `open <= trigger → fill at open`, else `low <= trigger → fill at trigger`.
3. `_emit_fill` receives real order context (`decision.order_event`): slippage applied only
   to MARKET and triggered STOP fills, never LIMIT; fee model gets liquidity classification —
   resting LIMIT = maker, MARKET/STOP = taker (D-11). `MakerTakerFeeModel._is_maker_order`
   already classifies by order_type string and supports an `is_maker` override
   (`maker_taker_fee_model.py:88-120`) — pass the real value instead of `"market"`
   (`simulated.py:191,194`).
4. Same-bar bracket priority already handles STOP-beats-LIMIT; with market orders in the book
   verify the bracket-children sequencing on top of Phase 4 create-all-then-emit: parent
   MARKET fills at next open; children (SL/TP) are already resting and may trigger on the SAME
   bar that fills the parent. Current `_pick_bracket_winner` only arbitrates siblings sharing
   `parent_order_id`; the parent itself has `parent_order_id=None` and fills independently.
   Decide and test the same-bar parent-fill + child-trigger interaction (entry at open, SL/TP
   evaluated against the same bar's high/low is the realistic choice — both reference engines
   allow same-bar exit). Planner discretion, but it MUST be an explicit matching-rule test.
5. Delete `FillDecision.fill_quantity` and the partial-fill mirror logic (D-06): the float-
   roundtrip clamp block in `order_manager.on_fill` (`order_manager.py:129-148`) collapses to
   the full-quantity contract — with Decimal-native fills the roundtrip ambiguity it defends
   against no longer exists.

### Pattern 5: Decimal-native execution internals (D-12, under D-14 never-round-prices)

- `MatchingEngine._evaluate` compares `order.price` (Decimal) directly against `Bar.high/low/
  open` (Decimal) — the `float(order.price)` boundary conversion (`matching_engine.py:121`)
  and the FillDecision float price die. No quantization anywhere in matching (prices are
  never rounded — D-14).
- `_emit_fill`: `executed_price = fill_price * slippage_factor` in Decimal. Slippage factor:
  the seeded `rng.uniform(...)` float jitter enters Decimal once via `to_money` (deterministic
  given the seeded RNG — the Phase 2 D-11 seam survives).
- Unify the ABCs: `FeeModel.calculate_fee(quantity: Decimal, price: Decimal, ...) -> Decimal`
  and `SlippageModel.calculate_slippage_factor(...) -> Decimal`; both `validate_inputs` RAISE
  typed exceptions (`itrader/core/exceptions` — `ValidationError` family) instead of the
  slippage bool-and-`return 1.0` silent-neutralize (`slippage_model/base.py:59-85`,
  `fixed_slippage_model.py:61-62`).
- `time.sleep(0.1)` at `simulated.py:270` — remove (locked).
- `TieredFeeModel` — delete file + factory branch (`simulated.py:465-475`) + config enum value
  if present (D-10).
- Commission remains quantized only at the cash/ledger boundary (existing `core/money`
  policy); document in `money.py` if any new quantization call sites appear.

### Pattern 6: Provider/Store/Feed Protocols (D-16/D-18/D-19)

Mirror the order-storage shape (`runtime_checkable` Protocol or ABC + concrete impl; factory
only if >1 impl is constructible this phase — for the backtest path, direct construction in
`TradingSystem` is simpler and matches D-18 "trading systems wire Store + Feed directly").

Suggested surfaces (planner discretion on names):

```python
class PriceStore(Protocol):                      # read AND write; run path uses read only
    def read_bars(self, ticker: str) -> pd.DataFrame: ...   # raises MissingPriceDataError
    def write_bars(self, ticker: str, frame: pd.DataFrame) -> None: ...
    def has(self, ticker: str) -> bool: ...
    def symbols(self) -> list[str]: ...
    def index(self, ticker: str) -> pd.DatetimeIndex: ...   # feeds TimeGenerator.set_dates

class BarFeed(Protocol):                          # runtime read-model
    def current_bars(self, time: datetime) -> dict[str, Bar]: ...
    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame: ...          # float64, completed bars only
    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame: ...      # D-19, FR8 fixed

class PriceProvider(Protocol):                    # offline only; dormant impls quarantine
    def fetch_ohlcv(self, symbol: str, timeframe: str, start: str,
                    end: str | None) -> pd.DataFrame: ...
    def get_symbols(self) -> list[str]: ...
```

- `CsvPriceStore` inherits the proven `_load_csv_data` logic (`data_provider.py:131-182`):
  header validation, tz-aware UTC→TIMEZONE index, pinned date window, loud
  `MalformedDataError`/`MissingPriceDataError` — both exceptions already exist in
  `core/exceptions`.
- FR7: all accessors raise on missing data — replace the two bare `except:`→`None` blocks
  (`data_provider.py:241-249, 267-275`) with `KeyError`-raising reads in the Store/Feed.
- FR8 megaframe fix: build `pd.concat(..., keys=[actually included symbols])` (not
  `self.prices.keys()` — `data_provider.py:377`), and don't silently drop tz-naive frames
  (`:374`) — the store normalizes everything tz-aware at load so the condition disappears;
  log loudly if a symbol is excluded. Unit-test with a ≥2-symbol fixture (D-24).
- Symbol methods (`set_symbols`/`_init_symbols`/`get_tradable_symbols`): minimal relocation —
  the backtest path only needs "the store knows its symbols"; the screener `'all'` branch is
  D-screener-dormant. Park a thin equivalent on the Store or the trading system (M5b #33
  owns the redesign).

### Pattern 7: Push-based strategy data (D-20)

`StrategiesHandler.calculate_signals` (currently `strategies_handler.py:45-53`) becomes:

```
for strategy in self.strategies:
    if not check_timeframe(event.time, strategy.timeframe): continue
    strategy.last_event = event           # or hand the Bar explicitly
    for ticker in strategy.tickers:
        window = self.feed.window(ticker, strategy.timeframe, strategy.max_window,
                                  asof=event.time)
        strategy.calculate_signal(ticker, window)   # + current Bar per chosen signature
```

`SMA_MACD_strategy.calculate_signal` slices its window by time (`bars[start_dt:]`) — the Feed
window must keep its tz-aware DatetimeIndex so this keeps working unchanged. Signature change
(window-only vs window+Bar) is planner discretion; the strategy reads the current close via
`last_event.bars[ticker].close` either way (signal price = decision-bar close, unchanged).
PERF4 (`my_strategies` direct `price_handler.prices` access) is resolved by relocation/OUT —
the in-tree `my_strategies` files are mypy-ignored and not on the golden path; they lose
their `price_handler` attribute when PriceHandler dies — they are out-of-program (OUT tag),
do not fix them, just ensure nothing imports them on the run path (verify: they are not
imported by the backtest path today).

### Pattern 8: D-21 workstream classification (suggested input to the planner)

| Workstream | Class | Why |
|------------|-------|-----|
| Bar struct + BarEvent redesign + consumer collapse | **Inert** | `Decimal(str(x))` on the same float64 values = today's `to_money` path (Pattern 3) |
| Store/Feed split, PriceHandler deletion, rewiring, quarantine moves | **Inert** | Same frames, same windows, same tick grid |
| Precompute + slice (incl. same-tf branch repoint) | **Inert** | Golden run is same-timeframe only (1d strategy on 1d data — the resample branch never executes); window equality is testable directly |
| Decimal retype of matching/fee/slippage + validation contract + tiered deletion + sleep removal | **Inert** | Golden run pins zero fee/slippage (D-09); trigger comparisons on Decimal vs float of identical string-converted values are order-isomorphic |
| Megaframe fix | **Inert** | Not on the golden path (no screeners in the oracle run) |
| **Next-bar-open market fills (D-01/D-13)** | **RESULT-CHANGING** | Every golden trade's fill price moves from decision-bar close to next-bar open; entry/exit dates shift +1 bar; trades near dataset end may disappear (last-bar edge) |
| Look-ahead fix (resampled branch label/closed) | Likely oracle-neutral (same-tf branch already conformant) — classify result-changing defensively, verify byte-exactness; if exact, no re-freeze needed |
| Limit-or-better gap fills + slippage-never-on-limit | Likely oracle-neutral (`SMA_MACD` emits `sl=0, tp=0` market orders — no resting stop/limit legs on the golden run) — same defensive treatment |

Expected re-freezes: **1** (next-open fills), possibly 2 if either "likely neutral" item
surprises. Budget D-23 checkpoints accordingly.

### Anti-Patterns to Avoid

- **`resample` inside `calculate_signals`/`window()` per tick** — the precompute exists to
  kill this; a regression test should assert no `resample` call on the per-tick path (e.g.,
  monkeypatch-count or timing budget).
- **Quantizing prices/quantities to the cash quantum** — D-14 companion rule; only cash/PnL
  at the ledger boundary.
- **Strategies choosing the as-of time** — no Feed method that takes a strategy-supplied
  arbitrary timestamp on the push path; `asof` comes from the BarEvent only.
- **Network or SqlHandler construction on the run path** — the Store is constructed from a
  file; providers are never imported by the run path.
- **Silent `None` returns from data accessors** — FR7; raise `MissingPriceDataError`.
- **Mutating events** — all events frozen since Phase 4; replace-in-book via
  `dataclasses.replace` (existing `MatchingEngine.modify` pattern).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OHLCV downsampling | manual bucket/groupby aggregation | `df.resample(alias, label='left', closed='left').agg(...)` | tz/DST boundary handling, bucket anchoring, and empty-bucket semantics are subtle; pandas is the reference implementation both external engines effectively share |
| As-of window lookup | manual binary search over timestamps | `DatetimeIndex.searchsorted` + `iloc` | verified O(log n), handles tz-aware indices correctly |
| Decimal entry | `Decimal(float)` or custom converters | `core/money.to_money` / `Decimal(str(x))` | the D-04 string-path policy already exists and is tested |
| Frozen value objects | custom `__setattr__` guards | `@dataclass(frozen=True, slots=True, kw_only=True)` | the Phase 4 event machinery proved the pattern on Python 3.13 |
| Resting-order book | a new book for market orders | existing `MatchingEngine` (`submit`/`on_bar`/OCO) | D-13 explicitly unifies into the existing engine; the MARKET branch already exists |
| Missing-data errors | new exception classes | `MissingPriceDataError`, `MalformedDataError`, `ValidationError` family in `core/exceptions` | already defined and used by `_load_csv_data` |
| Oracle diffing | bespoke comparators | existing `tests/integration/test_backtest_oracle.py` frame-equal machinery | the re-freeze just regenerates `tests/golden/` via `scripts/run_backtest.py` |

**Key insight:** every seam this phase needs has an in-repo precedent (order storage seam,
portfolio state seam, frozen events, money policy). The phase is recomposition, not invention.

## Runtime State Inventory

Rename/refactor phase — explicit audit of state outside the edited files:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `tests/golden/{trades.csv,equity.csv,summary.json}` — the committed oracle; `output/` (gitignored, regenerated per run) | Re-frozen by the D-21/D-23 result-changing commits (regenerate via `scripts/run_backtest.py`, owner sign-off). `output/` self-heals. |
| Stored data | `data/BTCUSD_1d_ohlcv_2018_2026.csv` — golden dataset | Read-only input; unchanged. CSV header shape verified (Binance kline, open-time stamped). |
| Live service config | None — no external services on the backtest path; PostgreSQL/OANDA/Binance config dormant (D-sql/D-oanda/D-live) | None — verified by reading `TradingSystem` wiring (csv path constructs no SqlHandler/CCXT). |
| OS-registered state | None — no scheduled tasks, daemons, or registered services | None — verified (pure library + make targets). |
| Secrets/env vars | `.env` loaded by Makefile; `Settings.database_url` (SecretStr, fail-loud) — not used on csv path | None — no secret names change. |
| Build artifacts | `__pycache__` dirs under relocated/deleted packages (e.g., `price_handler/__pycache__`, `events_handler/__pycache__` contains stale `event.cpython-*.pyc` from pre-Phase-4) | Self-healing on import; no installed-package or egg-info artifacts (Poetry in-project venv, no editable rename). |
| Tooling config | `pyproject.toml` mypy override module paths reference `itrader.price_handler.sql_handler`, `...exchange.CCXT`, `...exchange.OANDA`, `...live_streaming.BINANCE_Live` | **Must be updated to the post-relocation module paths** or the quarantined modules become strict-checked and break the gate (Pitfall 7). |

## Common Pitfalls

### Pitfall 1: Switching to `label='left'` does NOT drop the forming bucket
**What goes wrong:** assuming `label='left', closed='left'` alone fixes look-ahead. Verified:
pandas keeps the trailing partial bucket (10 daily bars resampled '7D' → 2 buckets, second
covers only 3 days).
**Why it happens:** resample labels windows; it doesn't know your decision time.
**How to avoid:** enforce visibility at slice time with the rule `B + TF ≤ T + tf_base`
(Pattern 1, rule 4). The look-ahead regression test must include a tick where the forming
bucket exists and assert it is absent from the window.
**Warning signs:** resampled window's last row timestamp > `T − TF + tf_base`.

### Pitfall 2: pandas 2.3.3 offset aliases — `'m'` means MONTH-END, and FutureWarnings are test errors
**What goes wrong:** `timedelta_to_str` (`time_parser.py:95-125`) produces `'30m'` for
minutes; `df.resample('30m')` in pandas 2.3.3 raises `FutureWarning: 'm' is deprecated …
use 'ME'` — pandas parses lowercase `m` as month-end. Under
`filterwarnings=["error", ...]` (FutureWarning NOT ignored) this **fails the test suite**;
outside tests it would silently resample to month-end. `'H'`/`'T'`/`'M'` similarly warn.
**Why it happens:** pandas 2.2+ deprecated the single-letter aliases; minutes are `'min'`,
hours `'h'`, days `'D'`/`'d'` (fine), weeks via `'7D'` (note: `'W'` anchors to Sunday and
defaults to right-labels — prefer `f'{n*7}D'` from the timedelta to keep data-anchored
buckets).
**How to avoid:** the Feed owns a canonical `timedelta → offset alias` mapping
(`minutes→'min'`, `hours→'h'`, `days→'D'`); do NOT reuse `timedelta_to_str` for resample
rules. Verified empirically against the project venv.
**Warning signs:** FutureWarning in any feed test; monthly-looking buckets in a minutes test.

### Pitfall 3: Decimal × float `TypeError` at the new type boundary
**What goes wrong:** `Bar.close` (Decimal) leaking into float pandas/indicator math, or a
float bar value reaching Decimal matching math. `Decimal * float` raises `TypeError`.
**How to avoid:** the boundary is exactly two one-way doors — Store float64 → `Bar`
(`Decimal(str(x))`, once, at Bar construction) and Store float64 → Feed windows (stay float).
Nothing converts back. mypy --strict on the new packages catches most leaks; the matching
tests (Decimal bars) catch the rest.
**Warning signs:** `float(...)` casts appearing inside `matching_engine.py` after the retype.

### Pitfall 4: Breaking the oracle with a "structural" commit
**What goes wrong:** a workstream classified inert produces a 1-cent diff (e.g., an
accidental quantize, a changed iteration order in `to_megaframe`, or a `Decimal(float)`).
**How to avoid:** D-22 ordering is the tripwire — run the oracle integration test
(`poetry run pytest tests/integration/test_backtest_oracle.py`) after every structural
commit; any diff in a structural commit is a BUG by definition (D-21), not a re-freeze.
**Warning signs:** `test_oracle_numeric_values` failing while `test_oracle_behavioral_identity`
passes (precision leak) — or both failing (timing leak).

### Pitfall 5: The next-open re-freeze breaks more than the oracle test
**What goes wrong:** unit/integration tests that implicitly assume same-bar fills (e.g.,
`test_simulated_exchange.py` immediate `execute_order` expectations,
`test_execution_handler_routing.py`, order-mirror tests asserting FILLED right after ORDER)
go red together with the oracle.
**How to avoid:** inventory the assumption before the flip: tests asserting a FillEvent on
the same `process_events` drain as the OrderEvent must enqueue a follow-up BAR. Budget this
in the result-changing plan, not as cleanup.
**Warning signs:** suite failures clustered in `tests/unit/execution/` and
`tests/unit/order/` after flipping the routing.

### Pitfall 6: Reservation vs gap-up settle (D-01 × Phase 5 D-04)
**What goes wrong:** the admission gate reserved `decision_close × qty + est_commission`;
the next-open fill settles HIGHER on a gap-up, so the debit exceeds the reservation.
**Why it's (probably) fine:** the 05-05 invariant guard checks `balance`, not
`available_balance`, and the reservation releases on terminal reconciliation — but this is
exactly the interaction D-08/D-01 flags for documentation.
**How to avoid:** document `OrderEvent.price` as a decision-price ESTIMATE (gate, not
ceiling) and add one unit test: gap-up fill above reserved estimate settles successfully and
releases the reservation. If the cash manager rejects over-reservation debits, that is a
Phase 5 behavior to surface to the owner, not silently patch.
**Warning signs:** `InsufficientFundsError`/settlement failures only on gap-up entries after
the flip.

### Pitfall 7: Relocations silently un-quarantine mypy-deferred modules
**What goes wrong:** `git mv` of `sql_handler.py`/`CCXT.py`/`OANDA.py`/`BINANCE_Live.py`
changes their module paths; the `[[tool.mypy.overrides]]` entries (`pyproject.toml:83-96`)
stop matching, the gate type-checks quarantined code, and `make typecheck` explodes with
hundreds of deferred errors.
**How to avoid:** update the override module list in the same commit as each move; also
re-point the `itrader.strategy_handler.my_strategies.*` and reporting overrides if touched.
**Warning signs:** typecheck error count jumping after a pure-move commit.

### Pitfall 8: `live_trading_system` and `reporting/statistics` import PriceHandler
**What goes wrong:** D-18 deletes `PriceHandler`, but `live_trading_system.py:12,104` and
`StatisticsReporting` (constructed with `self.price_handler` in
`backtest_trading_system.py:95-97`; reads `.prices`/`.get_bars` at `statistics.py:187-235`)
still reference it — import errors on the run path even though both are mypy-deferred.
**How to avoid:** minimal conformance edits, no redesign: live system gets the same Store+Feed
wiring shape (D-live owns making it actually work); `StatisticsReporting` takes the Store (its
uses are start/end date + bar count + get_bars — all Store-served) — its broken
`print_summary` path stays dormant.
**Warning signs:** `ImportError` in the smoke test after the deletion commit.

### Pitfall 9: BarEvent test fixtures are everywhere
**What goes wrong:** 9 test files construct `BarEvent(... bars={t: pd.DataFrame(...)})`
(verified: `test_stop_limit_orders`, `test_matching_engine`, `test_simulated_exchange`,
`test_portfolio_update`, `test_bar_event_ohlc`, `test_events`, `test_event_immutability`,
`test_strategy`, `test_execution_handler_routing`). The D-15 redesign breaks all of them at
once.
**How to avoid:** ship a shared `make_bar`/`make_bar_event` fixture (conftest) in the same
commit as the BarEvent change; convert all nine in one mechanical commit.
**Warning signs:** drip-feeding fixture fixes across multiple commits (breaks the
suite-green-at-every-commit rule).

## Code Examples

### Look-ahead regression test core (M5-01, D-24)

```python
# Source: pattern derived from verified pandas behavior in the project venv
# base: 1d bars stamped 2020-01-01..2020-01-10 (open-time). TF = 7d window.
# Tick at T = 2020-01-06: bucket B=2020-01-01 covers Jan1-7; last base bar (Jan 7)
# has NOT closed (7th closes at the Jan-7 tick) -> bucket invisible.
window = feed.window("BTCUSD", timedelta(days=7), max_window=5,
                     asof=ts("2020-01-06"))
assert window.empty or window.index[-1] < ts("2020-01-01")  # forming bucket invisible

# Tick at T = 2020-01-07: bucket B=Jan-1 completes (B + 7d == T + 1d) -> visible.
window = feed.window("BTCUSD", timedelta(days=7), max_window=5,
                     asof=ts("2020-01-07"))
assert window.index[-1] == ts("2020-01-01")
assert float(window.iloc[-1]["close"]) == base.loc[ts("2020-01-07"), "close"]
```

### Next-open matching-rule test core (D-01/D-13)

```python
# Source: existing MatchingEngine API (matching_engine.py, verified)
engine.submit(market_order)                       # decided at tick T
fills, _ = engine.on_bar(bar_event_at(T_plus_1))  # next bar
assert fills[0].fill_price == bar_T_plus_1.open   # Decimal == Decimal after retype
# limit-or-better gap-through (D-03):
# SELL limit 110, next bar opens 115 -> fill at 115 (better), never below 110;
# slippage factor never applied to this fill.
```

### Maker/taker context at the fill boundary (D-11)

```python
# Source: simulated.py:_emit_fill + maker_taker_fee_model.py (verified surfaces)
is_maker = decision.order_event.order_type is OrderType.LIMIT   # resting limit = maker
commission = self.fee_model.calculate_fee(
    quantity=qty, price=fill_price,
    side=event.action.value.lower(),
    order_type=decision.order_event.order_type.value, is_maker=is_maker)
```

## State of the Art

| Old Approach (current code) | Current Approach (this phase) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Immediate same-bar market fills at signal close (`simulated.py:252`) | Rest in book, fill at next bar's open (existing MARKET branch) | this phase (result-changing) | Oracle re-freeze; cross-validation becomes like-for-like with backtesting.py/backtrader defaults |
| `resample(label='right')` per tick with `time+timeframe` upper bound | Precompute `label='left', closed='left'` at load + per-tick searchsorted slice with completed-bars cutoff | this phase | Look-ahead removed; dominant hot-loop cost removed |
| `BarEvent.bars: dict[str, pd.DataFrame]` (actually Series) + 4× hasattr ladders | `dict[str, Bar]` frozen Decimal struct | this phase | FR1 type-branching deleted; Decimal money at the bar boundary |
| Slippage multiplied onto ALL fills incl. limits, `order_type="market"` hardcoded | Slippage only MARKET/STOP; real order context; maker/taker live | this phase | #28/M5-04; fee models become honest |
| God-object `PriceHandler` (network+SQL+cache+query+symbols) | Provider/Store/Feed seams; run path physically read-only | this phase | FR6/FR7/FR8/PERF4 resolved; reproducible offline runs |
| Float matching internals with engineered-inert boundaries (Phase 5 D-22) | Decimal-native end-to-end | this phase (sanctioned) | Phase 8 freezes Decimal-native numbers |

**Deprecated/outdated within this codebase after the phase:**
- `data_provider.py`, `price_handler/base.py` (AbstractPriceHandler): deleted (D-18).
- `outils/data_outils.resample_ohlcv` with `label='right'`: superseded by the Feed's
  precompute (delete or fix-and-relocate; nothing else imports it besides `get_resampled_bars`
  — verify before deleting).
- `TieredFeeModel`: deleted (D-10).
- `FillDecision.fill_quantity` / partial-fill mirror clamp: deleted (D-06).
- `SimulatedExchange.execution_timing` flag: deleted (one matching path).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | backtesting.py and backtrader default to next-bar-open market fills (`trade_on_close=False` / `cheat_on_open=False`) | Summary, Pattern 8 | Low for THIS phase (convention is locked by D-01 regardless); matters in Phase 8 cross-validation, which will verify directly. [ASSUMED] |
| A2 | The golden run never exercises the resampled branch (1d strategy on 1d data → `timeframe == current_timeframe` at `data_provider.py:337`) | Pattern 8 classification | If wrong, the look-ahead fix is result-changing and needs its own re-freeze; verify by asserting byte-exactness after landing it (the D-21 protocol covers this defensively). [VERIFIED-by-code-read, runtime not traced] |
| A3 | `SMA_MACD` emits no stop/limit children on the golden run (`buy/sell` with `sl=0, tp=0`; bracket assembly only attaches legs for non-zero SL/TP) | Pattern 8 | Same defensive treatment as A2 — if brackets exist, the limit-fill fix changes the oracle and re-freezes. [VERIFIED-by-code-read of `SMA_MACD_strategy.py:72,76` + `base.py:114-126`; `_assemble_bracket_and_emit` zero-handling not fully traced] |
| A4 | The cash manager tolerates a settle debit larger than the reservation (gap-up fill) because the invariant guard checks balance, not available_balance | Pitfall 6 | Settlement failures on gap-up entries after the flip; surface to owner if the unit test disproves it. [ASSUMED from Phase 5 plan notes in `order_manager.py:175-181` comments] |

## Open Questions

1. **Same-bar bracket interaction after a parent market fill (D-13 discretion item)**
   - What we know: parent MARKET fills at bar N+1 open; SL/TP children are already resting;
     `_pick_bracket_winner` arbitrates only siblings, not parent-vs-child.
   - What's unclear: whether a child may trigger on the SAME bar that filled its parent
     (realistic: yes — entry at open, intrabar high/low can hit SL/TP), and the cancel
     sequencing if both parent fills and a child triggers in one `on_bar`.
   - Recommendation: allow same-bar child triggers (matches real-exchange semantics and both
     reference engines), STOP-beats-LIMIT priority already covers the double-trigger case;
     make it an explicit matching-rule test either way.
2. **`calculate_signal` signature for the push contract (D-20)**
   - What we know: today `calculate_signal(ticker, bars: pd.DataFrame)`; the current Bar is
     reachable via `strategy.last_event`.
   - What's unclear: whether to widen the signature now (window + Bar) or keep it and let
     `last_event.bars[ticker]` carry the Bar; the richer contract is M5b #24's job.
   - Recommendation: keep the two-arg signature (minimal churn, M5b owns the contract
     enforcement); the Bar rides on `last_event`.
3. **Where the megaframe's per-symbol resample comes from**
   - What we know: D-19 makes `megaframe` a Feed method; the screener path is dormant.
   - What's unclear: whether megaframe shares the strategy precompute cache or resamples
     lazily per call (screeners declare their own timeframes that may not be precomputed).
   - Recommendation: lazy compute-and-memoize per (ticker, timeframe) inside the Feed — same
     cache dict, populated on demand; keeps "no resample in the hot loop" for the strategy
     path while staying correct for arbitrary screener timeframes.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (pyenv) | everything | ✓ | 3.13.1 | — |
| Poetry venv (in-project) | tests/typecheck/backtest | ✓ | active | — |
| pandas | store/feed/resample | ✓ | 2.3.3 | — |
| pytest | D-24 tests | ✓ | 8.4.2 | — |
| mypy | strict gate | ✓ | 2.1.0 | — |
| Golden CSV `data/BTCUSD_1d_ohlcv_2018_2026.csv` | store, oracle | ✓ | header verified | — |
| Committed oracle `tests/golden/` | D-21 gate | ✓ | M2b re-freeze state | — |
| PostgreSQL | NOT required (csv path; sql_store quarantined) | n/a | — | — |
| Network | NOT required (FR6 — run path offline by design) | n/a | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov 5.0.0) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (strict markers/config, filterwarnings=error) |
| Quick run command | `poetry run pytest tests/unit -x -q` (or a targeted file) |
| Full suite command | `make test` (suite) + `make typecheck` (mypy --strict) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M5-01 | Completed-bars rule, forming bucket invisible, both branches agree; timing contract rules 1–7 asserted | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -x` | ❌ Wave 0 |
| M5-01 | Next-open fill, limit-or-better gap, stop gap, last-bar edge | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -x` | ✅ extend |
| M5-01/all | Oracle gate (behavioral + numerical, re-frozen per D-21/D-23) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py` | ✅ |
| M5-02 | Bar construction, Decimal precision (micro-price), immutability | unit | `poetry run pytest tests/unit/core/test_bar.py -x` | ❌ Wave 0 |
| M5-02 | BarEvent dict[str, Bar] consumers (portfolio mark, signal price) | unit | `poetry run pytest tests/unit/events/test_bar_event_ohlc.py tests/unit/portfolio/test_portfolio_update.py -x` | ✅ rewrite |
| M5-03 | Precomputed-frame window == naive-resample window; no resample per tick | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k precompute -x` | ❌ Wave 0 |
| M5-04 | Maker/taker classification live; slippage never on limits; typed validation exceptions; tiered deleted | unit | `poetry run pytest tests/unit/execution/ -x` | ✅ extend + new fee/slippage files |
| M5-05 | CSV store read path, loud missing-data errors, read-only run path | unit | `poetry run pytest tests/unit/price/test_csv_store.py -x` | ❌ Wave 0 |
| M5-05 | Megaframe multi-symbol fixture (tz + keys correct) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k megaframe -x` | ❌ Wave 0 |
| all | Run-path smoke + wiring | integration | `poetry run pytest tests/integration/test_backtest_smoke.py -x` | ✅ |

### Sampling Rate
- **Per task commit:** targeted unit file + `poetry run pytest tests/integration/test_backtest_oracle.py -q` (the D-21 tripwire — mandatory on every structural commit)
- **Per wave merge:** `make test` + `make typecheck`
- **Phase gate:** full suite green + oracle re-frozen with owner-signed expected-diff note(s) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/core/test_bar.py` — covers M5-02 (construction, precision, frozen)
- [ ] `tests/unit/price/__init__`-less package dir + `test_csv_store.py` — covers M5-05 (note: NO unit tests exist today for any price_handler code — TC2)
- [ ] `tests/unit/price/test_bar_feed.py` — covers M5-01 look-ahead regression, M5-03 precompute equality, M5-05 megaframe fixture
- [ ] `tests/unit/execution/test_fee_models.py` / `test_slippage_models.py` — covers M5-04 (existing exchange test covers some; model-level tests missing)
- [ ] Shared `make_bar`/`make_bar_event` fixtures in `tests/conftest.py` (Pitfall 9 — must land WITH the BarEvent change)
- [ ] Framework install: none needed

## Security Domain

This phase has no auth/session/crypto surface; it strictly *improves* the security posture
of the run path.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | CSV header/shape validation with loud typed errors (existing `MalformedDataError` pattern, inherited by the Store); FR7 removes silent-`None` error masking |
| V6 Cryptography | no | — (UUIDv7 ids are not security tokens) |
| V10 Malicious Code / SSRF-ish | yes (positive) | FR6 removes the mid-run network fetch — the run path becomes physically offline/read-only, eliminating the silent-network-dependency class |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/poisoned price CSV | Tampering | Header validation + empty-frame raise (existing `_load_csv_data` checks, kept in CsvPriceStore); golden CSV committed + oracle-locked |
| Silent data-gap → wrong valuation | Information integrity | FR7: accessors raise `MissingPriceDataError` instead of returning `None` |
| Nondeterministic results masking tampering | Repudiation | Seeded RNG + injected clock (existing); offline read-only run path (this phase) |

## Sources

### Primary (HIGH confidence)
- Project codebase, read directly this session: `itrader/price_handler/data_provider.py`,
  `itrader/outils/data_outils.py`, `itrader/outils/time_parser.py`,
  `itrader/execution_handler/{matching_engine.py, execution_handler.py,
  exchanges/simulated.py, fee_model/*, slippage_model/*}`,
  `itrader/events_handler/{events/market.py, events/base.py, events/order.py,
  full_event_handler.py}`, `itrader/core/money.py`, `itrader/strategy_handler/{base.py,
  strategies_handler.py, SMA_MACD_strategy.py}`, `itrader/universe/{universe.py, dynamic.py}`,
  `itrader/order_handler/order_manager.py`, `itrader/portfolio_handler/portfolio_handler.py`
  (grep), `itrader/trading_system/{backtest_trading_system.py, live_trading_system.py
  (grep)}`, `itrader/reporting/statistics.py` (grep), `scripts/run_backtest.py`,
  `tests/integration/test_backtest_oracle.py`, `tests/unit/**` (layout + fixtures),
  `pyproject.toml`, `Makefile`, `data/BTCUSD_1d_ohlcv_2018_2026.csv` (header)
- Empirical verification in the project venv (pandas 2.3.3, Python 3.13.1): resample
  `label`/`closed` stamping, forming-bucket retention, `'m'`/`'H'`/`'T'`/`'M'` alias
  FutureWarnings, `searchsorted` slicing
- Planning corpus: `.planning/phases/06-.../06-CONTEXT.md`, `.planning/REQUIREMENTS.md`,
  `.planning/ROADMAP.md`, `.planning/STATE.md`,
  `.planning/codebase/ARCHITECTURE-REVIEW.md` (#3, #4, #21, #27, #28, #30),
  `.planning/codebase/CONCERNS.md` (FR/PERF/Fragile sections)

### Secondary (MEDIUM confidence)
- None needed — no external library additions; industry-convention claims are locked
  decisions carried from CONTEXT.md (anchored during discuss-phase).

### Tertiary (LOW confidence)
- A1 (external engines' fill-timing defaults) — training knowledge, flagged [ASSUMED];
  Phase 8 verifies directly.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions read from the live environment
- Architecture: HIGH — every pattern anchored to existing in-repo precedent + locked decisions; defect line numbers verified by reading the files this session
- Pitfalls: HIGH — Pitfalls 1, 2 verified empirically; 4–9 derived from direct code/config reads; Pitfall 6 partially [ASSUMED] (A4)
- Oracle classification (Pattern 8): MEDIUM-HIGH — A2/A3 code-read but not runtime-traced; the D-21 protocol is defensive against misclassification by design

**Research date:** 2026-06-06
**Valid until:** ~2026-07-06 (stable: brownfield internal refactor, pinned lockfile; re-verify only if pandas or pyproject test config changes)
