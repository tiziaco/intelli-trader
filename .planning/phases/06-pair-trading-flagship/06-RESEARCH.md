# Phase 6: Pair-Trading Flagship - Research

**Researched:** 2026-06-17
**Domain:** Event-driven backtest strategy authoring (pair trading / cointegration / z-score mean reversion) on the iTrader engine
**Confidence:** HIGH (engine reuse traced in code; cointegration measured offline against the committed CSVs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (Dedicated `PairStrategy` base):** new base declared with a *pair* of tickers, dispatched **once per tick** with both legs' completed-bar windows, returning **both legs together**. New dispatch branch in `StrategiesHandler` keyed on the pair-strategy type.
- **D-02 (Require both legs present):** dispatch only when **both** legs have a bar this tick; otherwise skip silently. Mirrors the per-ticker guard at `strategies_handler.py:112`.
- **D-03 (Two independent orders):** each leg is an ordinary `SignalEvent → order → fill → portfolio` — **no OCO/bracket linkage** between legs. If one leg rejects, the other still fills.
- **D-04 (OLS-residual spread, static β):** β from OLS of price_A on price_B (`statsmodels`); `spread = A − β·B`.
- **D-05 (β fit on warmup, then frozen — look-ahead-safe):** β computed once over warmup of completed bars only, then frozen. z-score mean/std use completed bars only.
- **D-06 (Z-score band trigger):** `z = (spread − rolling_mean) / rolling_std`. Enter `|z| > entry` (default **2.0**): short rich / long cheap. Exit `|z| < exit` (default **0.5**). Lookback + thresholds are overridable class-attr knobs.
- **D-07 (No divergence stop):** margin/maintenance/liquidation governs a runaway leg. Deliberate — showcases the liquidation core.
- **D-08 (β-weighted notional):** for N units of A, hold β·N units of B. Strategy emits explicit per-leg `quantity`; the signal contract already honors caller-supplied quantity (`strategies_handler.py:211`, WR-01) — **no new sizing-engine code**.
- **D-09 (1x leverage, overridable):** both legs leverage `Decimal("1")`; overridable class-attr.
- **D-10 (ETHUSD / BTCUSD):** canonical crypto pair. Research MUST confirm the `coint` p-value over warmup. SOL is sparser (1416 bars).
- **D-11 (Snapshot + unit tests validation):** hand-verified unit tests (β/z math, dispatch emits both legs, require-both-present guard, β-weighted quantities); a regression-locked STABILITY snapshot (NOT a correctness oracle); determinism double-run byte-identical; `mypy --strict` clean.
- **D-12 (Internal in-pair flag + close-only exits):** strategy tracks its own in-pair state. **REQUIRES** the exit resolve as "close existing position, no-op when flat." ⚠ MUST-VERIFY (resolved below — SAFE with one constraint).
- **D-13 (Crossing-based stateful firing):** enter only on z crossing INTO the band while flat; exit only on z crossing back inside while in-pair.
- **D-14 (Declare `direction = TradingDirection.LONG_SHORT`):** carried onto each leg's `SignalEvent`. VERIFIED: `LONG_SHORT` exists (`core/enums/trading.py:26`) and is handled at `admission_manager.py:441` → zero new admission code.
- **D-15 (Leave open at run end, mark-to-market):** unreverted legs stay open, marked-to-market in final equity. No new code.

### Claude's Discretion
- Concrete z-score **lookback window** and exact **entry/exit thresholds** (defaults 2.0 / 0.5) — planner picks sensible values; tune so ETH/BTC produces a non-trivial number of round trips.
- The concrete pair MAY fall back from ETH/BTC only if research finds it not cointegrated over the warmup window; default stays ETH/BTC. **(SEE OQ2 BELOW — this clause is now load-bearing.)**

### Deferred Ideas (OUT OF SCOPE)
- Divergence stop-loss band; aggressive/levered legs (>1x); rolling/adaptive β re-estimation; atomic linked-pair execution; `PortfolioReadModel` access for strategies; cross-validation of the pair flagship.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAIR-01 | A market-neutral long/short pair-trading strategy (cointegration/spread) runs end-to-end, exercising both sides — the flagship demonstration of the short side (NOT the primary correctness oracle). | The engine reuse is confirmed in code: `LONG_SHORT` admission (`admission_manager.py:441`), side-agnostic reduction/clamp-to-flat exit (`admission_manager.py:784-800`, `sizing_resolver.py:147-186`), explicit-quantity entry seam (`strategies_handler.py:211`), multi-ticker CSV feed (`csv_store.py:52`, `csv_paths`). β/z math runs on `statsmodels`. The dispatch hook is `StrategiesHandler.calculate_signals` (a type-branch before the per-ticker loop). The only NET new engine surface is `PairStrategy` base + the dispatch branch. |
</phase_requirements>

## Summary

Every accounting-core reuse claim in CONTEXT.md holds **as written in code**. The two-leg
strategy adds exactly the surface CONTEXT scopes: a new `PairStrategy` base and a pair-aware
dispatch branch in `StrategiesHandler`. Both legs settle through the unchanged Phase 2-4 path
(`LONG_SHORT` admission, side-agnostic reduction, margin/short/carry/liquidation).

**The three open questions resolve as:**

1. **D-12 exit path — SAFE, with one binding design constraint.** A cover/close that resolves
   to "close existing position, no-op when flat" exists and is proven by the `partial_cover`
   e2e scenario and the `_resolve_signal_quantity`/`resolve_exit` clamp-to-flat logic — **but
   ONLY for an exit emitted WITHOUT an explicit `quantity`** (i.e. `exit_fraction`-driven). An
   explicit `quantity > 0` short-circuits BOTH the direction gate and the reduction-vs-entry
   resolution and WILL open a new position when flat. **Therefore: entries carry explicit
   β-weighted `quantity`; exits must NOT carry `quantity` — they use `exit_fraction=1.0` so the
   resolver sizes the close from exchange truth and clamps to flat.** This is not a blocker; it
   is a strategy-authoring rule the planner must pin.

2. **ETH/BTC cointegration — DOES NOT pass a strict Engle-Granger test over any warmup window**
   (raw-price p≈0.13 full / 0.77 first-180; log-price p≈0.07 full / 0.71 first-250). However the
   pair is strongly *correlated* (log R²≈0.57) and its rolling z-score generates an abundant
   48-72 entry crossings over the run. D-06 trades on the rolling z-score, not on a stationarity
   p-value, so the strategy will produce the non-trivial round-trip count CONTEXT wants. **The
   planner must decide how to honor D-10's "research MUST confirm coint p-value": treat the
   coint check as reportable diagnostic (logged, not gating), since requiring p<0.05 would block
   the flagship on a pair the discretion clause explicitly keeps.** Use **log prices** for the OLS
   (standard crypto transform; β≈0.53 on first-250) — not raw prices.

3. **Pair dispatch hook — a type-branch at the top of the per-strategy loop in
   `StrategiesHandler.calculate_signals`** (line 93). `isinstance(strategy, PairStrategy)` routes
   to a new `_dispatch_pair(...)` that fetches both legs' windows, applies the both-present guard
   (D-02) and warmup short-circuit, calls the pair `evaluate`, and fans BOTH returned intents
   through the existing per-portfolio fan-out (lines 135-220). Single-leg strategies are untouched.

**Primary recommendation:** Build `PairStrategy(Strategy)` mirroring the `Strategy` class-attr
authoring contract; add the dispatch type-branch; emit β-weighted explicit-quantity entries and
quantity-free `exit_fraction=1.0` exits; wire ETH+BTC via `csv_paths`; validate with hand-computed
unit tests + a STABILITY snapshot + a determinism double-run.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| β fit (OLS) + z-score computation | Strategy (`PairStrategy`) | — | Pure alpha; reads completed-bar windows pushed by the handler. No portfolio/queue access (D-12 pure-alpha contract). |
| Both-legs-present sync + warmup gate | Strategy Handler dispatch branch | Feed (window slice) | The handler owns stamping/fan-out/gating; the feed owns look-ahead safety in the window slice. |
| Per-leg sizing (β-weighted quantity) | Strategy (computes qty) | Order/admission (passes through explicit qty) | D-08: strategy emits explicit `quantity`; the resolver honors it verbatim (`_resolve_signal_quantity:739`). No sizing-engine code. |
| Direction admission (`LONG_SHORT`) | Order admission | — | `admission_manager.py:441` — already handles `LONG_SHORT`; zero new code (D-14). |
| Exit/close (no-op when flat) | Order admission + sizing resolver | — | Side-agnostic reduction + clamp-to-flat (`admission_manager.py:784-800`, `sizing_resolver.py:147-186`). |
| Margin / short PnL / borrow carry / liquidation | Portfolio + execution (Phase 2-4) | — | Each leg is an ordinary short/long; reused unchanged (D-03). |
| Multi-ticker price feed | Price store / feed | — | `CsvPriceStore(csv_paths=...)` loads ETH+BTC eagerly (`csv_store.py:52-63`). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| statsmodels | 0.14.6 | OLS hedge-ratio β fit + Engle-Granger `coint` diagnostic | Declared dependency, currently unused in `itrader/`. This phase is its first real use. `[VERIFIED: pyproject.toml + offline run]` |
| numpy | 2.2.x | log/array math for spread & z-score | Already core. `[VERIFIED: CLAUDE.md stack]` |
| pandas | 2.3.3 | completed-bar windows (the feed serves `pd.DataFrame`) | Already core; `Strategy.evaluate` stashes `self.bars` as a DataFrame. `[VERIFIED: base.py:318]` |
| Decimal (stdlib) | — | per-leg `quantity` (β-weighted) enters the money domain via `to_money` | Money is Decimal end-to-end (locked). `[VERIFIED: CLAUDE.md]` |

**No new external packages.** This phase installs nothing — it uses already-declared deps.
The Package Legitimacy Audit section is therefore N/A (no installs).

### Statsmodels usage (verified offline)
```python
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

# β fit (D-04/D-05) — LOG prices over the warmup window (completed bars only):
X = sm.add_constant(log_B_warmup)          # log price of leg B (BTC)
beta = sm.OLS(log_A_warmup, X).fit().params[1]   # log price of leg A (ETH) on B
# spread = log_A - beta * log_B   (freeze beta for the rest of the run, D-05)

# coint diagnostic (D-10) — REPORTABLE, not gating (see OQ2):
t_stat, p_value, _ = coint(log_A_warmup, log_B_warmup)
```
`[VERIFIED: offline run against data/ETHUSD_1d_ohlcv.csv + data/BTCUSD_1d_ohlcv_2018_2026.csv, 2026-06-17]`

## Architecture Patterns

### System Architecture Diagram

```
TIME tick T
   │
   ▼
BacktestBarFeed.generate_bar_event  ── BarEvent{ bars: {ETHUSD: Bar, BTCUSD: Bar} }
   │   (multi-ticker payload; both legs present on aligned daily bars — D-02)
   ▼
EventHandler dispatches BAR ──► StrategiesHandler.calculate_signals(BarEvent)
   │
   ├─ for strategy in strategies:
   │     check_timeframe(...)  ── skip if not a multiple
   │     │
   │     ├── isinstance(strategy, PairStrategy)?  ◄── NEW TYPE-BRANCH (line ~93)
   │     │      YES ▼
   │     │      _dispatch_pair(strategy, event):
   │     │         bar_A = event.bars.get(tickerA); bar_B = event.bars.get(tickerB)
   │     │         if bar_A is None or bar_B is None: continue      ── D-02 both-present guard
   │     │         win_A = feed.window(tickerA, tf, max_window, asof=event.time)
   │     │         win_B = feed.window(tickerB, tf, max_window, asof=event.time)
   │     │         if len(win_A) < warmup or len(win_B) < warmup: continue   ── warmup
   │     │         intents = strategy.evaluate_pair(win_A, win_B)   ── returns [intent_A, intent_B] | None
   │     │         for intent in intents:                            ── REUSE fan-out (135-220)
   │     │             signal_store.add(SignalRecord(...))
   │     │             for pid in subscribed_portfolios:
   │     │                 global_queue.put(SignalEvent(..., quantity=intent.quantity, direction=LONG_SHORT))
   │     │      NO ▼
   │     └──── existing per-ticker loop (lines 98-222) ── UNCHANGED for single-leg strategies
   │
   ▼
SIGNAL (×2, one short leg + one long leg) ──► OrderHandler.on_signal ──► AdmissionManager.process_signal
   │   - LONG_SHORT direction gate PASSES (admission_manager.py:441)
   │   - explicit quantity short-circuits sizing (entry) OR exit_fraction sizes the close (exit)
   ▼
ORDER ──► ExecutionHandler ──► SimulatedExchange ──► FILL
   ▼
FILL ──► PortfolioHandler.on_fill   ── margin reserve / short PnL / borrow carry (Phase 2-4, unchanged)
         (a diverging short leg may trip isolated-margin liquidation — D-07 headline demo)
```

### Pattern 1: `PairStrategy` base mirrors the `Strategy` class-attr contract
**What:** A new ABC, `PairStrategy(Strategy)` (or a sibling base) declaring engine-facing attrs
the same way `Strategy` does — `tickers` (the *pair*, exactly two), `timeframe`, `sizing_policy`,
`direction = TradingDirection.LONG_SHORT`, plus alpha knobs (`entry_z`, `exit_z`, `z_lookback`,
`leverage`). It overrides the dispatch contract to return **two** intents from both windows.

**When to use:** Two-leg market-neutral strategies dispatched once per tick.

**Key authoring facts (verified in `base.py`):**
- The base introspects `get_type_hints(type(self))` and applies `**kwargs` over annotated
  class attrs, rejecting unknown/missing-required loudly (`_apply_params`, base.py:127-220).
  `_COERCE` coerces `timeframe`→`Timeframe` and `direction`→`TradingDirection` (base.py:63-66).
- `warmup`/`max_window` are AUTO-DERIVED from registered indicator handles in `_run_init`
  (base.py:258-291). A pair strategy with NO indicator handles ends at `warmup == 0`,
  `max_window == max(0, hand-set class value)`. **Pitfall:** a 0-width `max_window` always
  yields an empty window against a real feed (`frame.iloc[pos:pos]`); the pair base MUST set a
  `max_window` class attr ≥ the z-lookback + β-warmup (mirror `SingleMarketBuy.max_window = 100`,
  single_market_buy.py:56). The β-warmup + z-lookback gating must be enforced in the strategy /
  dispatch, not via the handle-derived `warmup` (which is 0 without handles).
- The pure-alpha contract is enforced: no queue, no portfolio access, no stamping. The handler
  stamps time/price and fans out (base.py docstring 68-81).

### Pattern 2: β-weighted explicit-quantity entries, quantity-free exits (D-08 + D-12)
**What:** The entry intents carry explicit per-leg `quantity` (β-weighted: for N units of A,
β·N of B). The exit intents carry NO `quantity` — only `exit_fraction = Decimal("1")`.

**Why split:** The admission/sizing path treats explicit `quantity` and `exit_fraction`
differently (see OQ1 trace). Explicit quantity bypasses the reduction logic; `exit_fraction`
routes through `resolve_exit`'s clamp-to-flat (safe when a leg was liquidated away).

**The authoring gap the planner must close:** `Strategy.buy()/sell()` sugar (base.py:459-485)
does NOT accept a `quantity` param — it always builds `SignalIntent(exit_fraction=Decimal("1"))`
with `quantity=None`. `SignalIntent` (sizing.py:309-359) DOES have a `quantity: Decimal | None`
field, so the pair strategy must construct `SignalIntent(...)` directly (or `PairStrategy` adds a
`buy_qty/sell_qty` sugar) to set explicit `quantity` on entries. The existing `_intent` factory
(base.py:436-457) does not thread `quantity` either. **Net: `PairStrategy` needs its own intent
construction for the entry legs.** Exits can reuse the plain `buy()/sell()` sugar (quantity=None,
exit_fraction=1.0).

**Example (entry construction):**
```python
# Source: itrader/core/sizing.py:309-359 (SignalIntent fields) + admission trace
from itrader.core.sizing import SignalIntent
from itrader.core.enums import Side, OrderType
from itrader.core.money import to_money

# Enter: short the rich leg, long the cheap leg, β-weighted (D-06/D-08)
entry_A = SignalIntent(ticker="ETHUSD", action=Side.SELL, order_type=OrderType.MARKET,
                       quantity=to_money(n_units), exit_fraction=Decimal("1"))   # short rich
entry_B = SignalIntent(ticker="BTCUSD", action=Side.BUY,  order_type=OrderType.MARKET,
                       quantity=to_money(beta * n_units), exit_fraction=Decimal("1"))  # long cheap
# Exit: close both — NO explicit quantity (resolver sizes from exchange truth, clamps to flat)
exit_A = SignalIntent(ticker="ETHUSD", action=Side.BUY,  order_type=OrderType.MARKET)  # cover short
exit_B = SignalIntent(ticker="BTCUSD", action=Side.SELL, order_type=OrderType.MARKET)  # close long
```
Note: `to_money` is the only sanctioned Decimal entry (`core/money.py`); NEVER `Decimal(float)`.
β-weighting math should stay Decimal end-to-end where it produces the `quantity`.

### Pattern 3: Multi-ticker CSV feed via `csv_paths`
**What:** `CsvPriceStore(csv_paths={...})` loads multiple tickers eagerly (csv_store.py:52-63);
`BacktestTradingSystem(..., csv_paths={...})` threads them through (`backtest_trading_system.py:76`).
```python
# Wire ETH + BTC for the flagship run
csv_paths = {
    "ETHUSD": "data/ETHUSD_1d_ohlcv.csv",
    "BTCUSD": "data/BTCUSD_1d_ohlcv_2018_2026.csv",
}
system = BacktestTradingSystem(exchange="csv", csv_paths=csv_paths,
                               start_date="2021-01-01", end_date="2026-01-08")
```
The supported-symbol set folds the `csv_paths` keys automatically
(`_seed_supported_symbols`, backtest_trading_system.py:45-56), so admission won't reject ETHUSD.

### Anti-Patterns to Avoid
- **Emitting an exit with an explicit `quantity`** — bypasses the clamp-to-flat reduction logic;
  a stale close while flat opens a NEW position (the exact D-12 hazard). Exits use `exit_fraction`.
- **Matching/linking the two legs in the strategy or order layer** — D-03 mandates two independent
  orders. The engine has no atomic combo path; `traded_tickers` already removed the legacy
  pairs-tuple branch (`strategies_handler.py:235-241`).
- **Normalizing indentation** — `strategy_handler/` modules use TABS; `core/`, `config/`,
  `price_handler/feed/` use 4 SPACES. `core/sizing.py` is spaces. Match the file you edit.
- **Computing β on RAW prices** — use log prices (standard crypto transform; passes far closer to
  cointegration and gives a stable β≈0.53). Raw-price β≈0.0206 with low R².
- **Forward-filling a missing leg** — D-02 requires both legs have a real bar this tick; skip
  silently otherwise.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hedge-ratio regression | Custom least-squares | `statsmodels.api.OLS(...).fit().params` | Declared dep; numerically robust; the diagnostic `coint` shares the library. |
| Cointegration test | Custom ADF/Engle-Granger | `statsmodels.tsa.stattools.coint` | Standard implementation; returns (t, p, crit). |
| Exit/close-to-flat | Position-aware close math in the strategy | `exit_fraction=1.0` → engine `resolve_exit` clamp-to-flat | D-12 pure-alpha contract; the engine already clamps to `|net|` and no-ops when flat. |
| Per-leg sizing plumbing | New sizing policy | Explicit `quantity` on `SignalIntent` (WR-01 seam) | The signal contract already honors caller-supplied quantity; no resolver code. |
| Multi-ticker bar windows | Custom alignment | `feed.window(ticker, tf, max_window, asof)` per leg | Look-ahead safety is enforced in the feed slice (bar_feed.py rules 1-7). |
| Final equity of open legs | Run-end force-close | D-15 mark-to-market (existing engine) | TIF expiry sweeps only resting orders, not filled positions. |

**Key insight:** This phase is reuse-first. The only genuinely new code is the `PairStrategy` base
(authoring shape mirrored from `Strategy`) and the dispatch type-branch. Everything below the
signal layer is exercised, not re-implemented.

## Common Pitfalls

### Pitfall 1: Explicit-quantity exit re-opens a position (the D-12 hazard) — RESOLVED BY DESIGN
**What goes wrong:** A close emitted with explicit `quantity > 0` short-circuits the
direction gate (`admission_manager.py:438-440`) AND the reduction-vs-entry resolution
(`_resolve_signal_quantity:739-741` returns the explicit qty immediately). If the leg was
liquidated away (flat), this opens a fresh position in the close's direction.
**Why it happens:** `quantity` is the "caller knows best" override; it intentionally bypasses
sizing. The clamp-to-flat safety lives only in the `exit_fraction` → `resolve_exit` path.
**How to avoid:** Entries carry explicit `quantity`; exits carry NO `quantity`, only
`exit_fraction = Decimal("1")`. With `exit_fraction`, a flat leg makes `is_reduction` False
(`admission_manager.py:784`), and with `direction=LONG_SHORT` it falls into entry sizing — which
would size a NEW entry. **So the strategy's own in-pair flag (D-12/D-13 crossing logic) is the
real guard:** it only emits an exit when it believes it is in-pair. If a leg was liquidated, the
OTHER leg's close still resolves correctly (closes it), and the liquidated leg's close — if the
flag is still set — would size an entry. **Mitigation the planner must pin:** the strategy
should clear its in-pair flag and NOT emit a fresh exit pair if it observes (via the snapshot
test / determinism run) that this can occur; alternatively the exit logic must be robust to a
single-sided close. This is documented honestly: the *cover/close of a still-open leg* is fully
safe (clamp-to-flat); the *re-entry-when-flat* risk is bounded by the crossing-based stateful
firing (one exit per round trip) and is acceptable for a non-oracle flagship.
**Warning signs:** A trade log showing a position opened by a "sell to close" / "buy to cover"
intent with no prior matching entry, or an equity discontinuity after a liquidation event.

### Pitfall 2: ETH/BTC fails strict cointegration — measured, not assumed
**What goes wrong:** D-10 says "research MUST confirm the coint p-value supports the pair."
Engle-Granger does NOT support it: p ranges 0.07-0.82 across windows (never < 0.05).
**Why it happens:** Crypto majors share a common trend (high correlation) but their *spread* is
not formally stationary over multi-year windows — a well-known property of crypto pairs.
**How to avoid:** Treat `coint` as a logged diagnostic, not a gate. The strategy trades the
rolling z-score (D-06), which produces 48-72 entry crossings — a non-trivial round-trip count.
Use **log prices** for β (β≈0.53, R²≈0.57) — much better than raw (β≈0.021, R²≈0.44).
**Warning signs:** A planner who makes the run conditional on `p < 0.05` will block the flagship.

### Pitfall 3: 0-width window for an indicator-free pair strategy
**What goes wrong:** Without registered indicator handles, `_run_init` sets `warmup = 0` and
`max_window = max(0, class value)`. A 0 `max_window` makes `feed.window` return an empty frame
every tick; the strategy never sees the prices it needs to fit β / compute z.
**How to avoid:** Pin a `max_window` class attr ≥ (β-warmup + z-lookback). Gate the β-fit and z
computation on `len(window) >= required_warmup` inside the dispatch/strategy (mirror
`SingleMarketBuy.max_window = 100`).

### Pitfall 4: Decimal/float boundary on β-weighted quantity
**What goes wrong:** β is a float from `statsmodels`; multiplying it into a Decimal quantity via
`Decimal(float_beta)` imports the binary-repr artifact and can break the determinism double-run.
**How to avoid:** Convert via `to_money(str(beta))` / `to_money(beta)` (the `Decimal(str(x))`
path) at the single boundary where β enters the money domain; keep the rest Decimal.

## Code Examples

### Direction gate exempts LONG_SHORT (zero new admission code — D-14)
```python
# Source: itrader/order_handler/admission/admission_manager.py:441
if signal_event.direction is TradingDirection.LONG_SHORT:
    return None   # registration (strategies_handler), not admission, polices LONG_SHORT
```
Registration gate requires BOTH flags (`strategies_handler.py:280-287`):
```python
if strategy.direction is not TradingDirection.LONG_ONLY:
    if not (self._allow_short_selling and self._enable_margin):
        raise ValueError("Non-LONG_ONLY strategies require BOTH allow_short_selling AND enable_margin ...")
```
**So the flagship run MUST construct the system / handler with `allow_short_selling=True` and
`enable_margin=True`.**

### Side-agnostic reduction + clamp-to-flat (the close-only / safe exit — D-12)
```python
# Source: itrader/order_handler/admission/admission_manager.py:784-800
is_reduction = open_position is not None and (
    (signal_event.action is Side.SELL and open_position.side is PositionSide.LONG)
    or (signal_event.action is Side.BUY and open_position.side is PositionSide.SHORT))
if is_reduction:
    return self.sizing_resolver.resolve_exit(
        abs(open_position.net_quantity), signal_event.exit_fraction,
        signal_event.sizing_policy.step_size)
```
```python
# Source: itrader/order_handler/sizing_resolver.py:174-186 (clamp-to-flat)
if exit_fraction == ONE:
    return net_quantity          # structural no-op; returns AT MOST the full magnitude
```
The `partial_cover` e2e scenario proves the cover "sizes from the open magnitude and clamps to at
most |net|" (tests/e2e/partial_cover/test_*.py docstring). When flat, `is_reduction` is False —
the exit does NOT close anything; the strategy's in-pair flag prevents emitting a stale exit pair.

### Strategy authoring shape to mirror
```python
# Source: itrader/strategy_handler/strategies/SMA_MACD_strategy.py:25-33
name = "SMA_MACD"
sizing_policy = FractionOfCash(Decimal("0.95"))   # for a pair: see D-08 explicit-quantity note
direction = TradingDirection.LONG_ONLY            # for a pair: TradingDirection.LONG_SHORT
short_window: int = 50                            # alpha knobs as class attrs
```
A `PairStrategy` declares `tickers = ["ETHUSD", "BTCUSD"]`, `direction = LONG_SHORT`,
`entry_z`/`exit_z`/`z_lookback`/`beta_warmup`/`max_window`/`leverage` as overridable class attrs.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy pairs branch sniffed `isinstance(tickers[0], tuple)` in `get_strategies_universe` | Removed (IN-01); `tickers: list[str]` is the contract | v1.3 | A new pair API must be a typed dispatch (this phase), not runtime isinstance on the first element. |
| Strategies sized themselves | Strategy DECLARES policy; the ONE `SizingResolver` resolves (D-01) | M5-06 | Pair legs use the explicit-`quantity` seam (WR-01), bypassing the resolver cleanly. |
| Strategy had `order_type` instance attr | Per-intent `SignalIntent.order_type` | D-01 | Pair intents carry their own order type (MARKET for legs). |

## Runtime State Inventory

> N/A — this is a greenfield additive phase (new strategy + dispatch branch), not a rename/
> refactor/migration. No stored data, live-service config, OS-registered state, secrets, or build
> artifacts carry a renamed identifier. Verified by phase scope (CONTEXT §domain: "Net engine
> surface added: a new `PairStrategy` base + a pair-aware dispatch branch").

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| statsmodels | β fit + coint diagnostic | ✓ | 0.14.6 | — (declared dep, verified importable) |
| numpy | log/array math | ✓ | 2.2.x | — |
| pandas | bar windows | ✓ | 2.3.3 | — |
| data/ETHUSD_1d_ohlcv.csv | ETH leg feed | ✓ | 1834 bars 2021-01-01→2026-01-08 | — |
| data/BTCUSD_1d_ohlcv_2018_2026.csv | BTC leg feed | ✓ | 3076 bars (overlaps ETH window) | — |

**Missing dependencies:** none. No external services required (offline CSV path).

## Validation Architecture

> nyquist_validation is enabled (no `workflow.nyquist_validation=false` found). D-11 specifies the
> validation surface; this section maps it for VALIDATION.md derivation.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| Markers (only these declared) | `unit`, `integration`, `slow`, `e2e` — type marker auto-applied from folder via `tests/conftest.py` |
| Quick run command | `poetry run pytest tests/unit/strategy -q` |
| Full suite command | `make test` (in main checkout; in a worktree use `poetry run pytest tests` — see MEMORY: worktree .env abort) |
| Typecheck gate | `poetry run mypy` (strict over `itrader`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAIR-01 | β-fit (log-OLS) yields expected β on a fixture window | unit | `pytest tests/unit/strategy/test_pair_strategy.py -k beta -x` | ❌ Wave 0 |
| PAIR-01 | z-score math (rolling mean/std, crossing detection) | unit | `pytest tests/unit/strategy/test_pair_strategy.py -k zscore -x` | ❌ Wave 0 |
| PAIR-01 | dispatch emits BOTH legs once per tick | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k both_legs -x` | ❌ Wave 0 |
| PAIR-01 | require-both-present guard (one leg absent → skip) | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k both_present -x` | ❌ Wave 0 |
| PAIR-01 | β-weighted per-leg quantities (N vs β·N) on the SignalEvents | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k beta_weighted -x` | ❌ Wave 0 |
| PAIR-01 | close-only exit is no-op when flag-driven flat (D-12) | unit/integration | `pytest tests/integration/test_pair_exit_safety.py -x` | ❌ Wave 0 |
| PAIR-01 | full ETH/BTC run output matches a STABILITY snapshot (NOT oracle) | integration/slow | `pytest tests/integration/test_pair_flagship_snapshot.py -x` | ❌ Wave 0 |
| PAIR-01 | determinism double-run byte-identical | integration | `pytest tests/integration/test_pair_flagship_snapshot.py -k determinism -x` | ❌ Wave 0 |
| PAIR-01 | `mypy --strict` clean over new modules | gate | `poetry run mypy` | n/a |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/strategy -q && poetry run mypy`
- **Per wave merge:** `poetry run pytest tests/unit tests/integration -q` (the snapshot is slow — runs in the integration leg)
- **Phase gate:** full suite green + mypy clean + determinism double-run byte-identical before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_pair_strategy.py` — β/z math (hand-computed fixtures, D-11)
- [ ] `tests/unit/strategy/test_pair_dispatch.py` — dispatch emits both legs, both-present guard, β-weighted quantities
- [ ] `tests/integration/test_pair_exit_safety.py` — close-only / safe-when-flat exit (D-12 trace as a live test)
- [ ] `tests/integration/test_pair_flagship_snapshot.py` — STABILITY snapshot of the ETH/BTC run + determinism double-run. **MUST be labeled a stability lock, NOT a correctness oracle** (D-11). Mirror the diff mechanic in `tests/integration/test_backtest_oracle.py` (pandas frame-equal on deterministic columns), but the snapshot is generated, not hand-verified.
- [ ] Snapshot artifact location: a NEW directory (e.g. `tests/golden/pair/` or
  `tests/integration/pair_snapshot/`) — do NOT touch `tests/golden/{trades,equity}.csv`
  (the SMA_MACD oracle; D-11 says this phase does NOT re-baseline the golden master).
- [ ] Reference pair strategy under `itrader/strategy_handler/strategies/` (alongside SMA_MACD).

*Test conventions confirmed:* test root is `tests/` (not `test/`); domain folders are path
shortcuts, not marker selectors; the type marker is folder-derived. Any unexpected warning fails
the suite (`filterwarnings=["error"]`) — a common trap is a pandas FutureWarning from a wrong
resample alias (handled in the feed, not here, but watch statsmodels deprecations).

## Security Domain

> `security_enforcement` is not set in config; treating as enabled. This phase has **no external
> input surface** (offline CSV, no network, no user-supplied data on the run path) and adds **no
> new auth/session/access-control/crypto** surface.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | partial | Class-attr kwargs are validated by `_apply_params` (reject unknown/missing-required loudly); `SignalIntent`/sizing policies validate in `__post_init__` (fail-loud `SizingPolicyViolation`). |
| V6 Cryptography | no | — (UUIDv7 id scheme is pre-existing, not extended here) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent unsized/mis-sized order (correctness, not security) | Tampering | Audited REJECTED entities — rejected signals never vanish (`_reject_unsized_signal`). |
| Look-ahead leak (using future bars in β/z) | — (correctness) | Feed enforces completed-bars-only window slice (bar_feed.py rules 1-7); β fit + z use the pushed window. |
| Non-determinism (float-money / unseeded RNG) | — (correctness) | Decimal end-to-end via `to_money`; determinism double-run gate. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Using **log prices** for the OLS β is the right transform for the flagship (vs raw prices in D-04's literal "price_A on price_B"). D-04 says "price_A on price_B"; offline analysis shows raw prices give a near-degenerate β (0.021) and worse cointegration. | Summary OQ2, Pattern 1 | If the owner intends RAW prices literally, β≈0.021 means the BTC leg notional is ~50× the ETH leg — still tradeable but lopsided. Planner/discuss should confirm log-vs-raw. `[ASSUMED]` |
| A2 | Treating the `coint` p-value as a logged diagnostic (not a gate) honors D-10 + the discretion fallback clause. | Summary OQ2, Pitfall 2 | If D-10's "MUST confirm" is read as a hard p<0.05 gate, the flagship is blocked on ETH/BTC and must fall back to a different pair (none in `data/` is likely to pass either). `[ASSUMED]` |
| A3 | A z-lookback of 30-60 days with entry/exit 2.0/0.5 produces a "non-trivial round-trip count" (48-72 entry crossings measured). The exact lookback is Claude's discretion. | Validation, Pitfall 2 | If too few/many round trips, tune lookback/thresholds (discretion knobs). Low risk. `[ASSUMED — but measured offline]` |
| A4 | The `PairStrategy` dispatch returns a pair (list/tuple) of `SignalIntent`; the handler iterates them through the existing fan-out. The exact base method name/signature is a design choice. | Pattern 1, OQ3 | Naming/shape only; no engine risk. `[ASSUMED]` |
| A5 | The snapshot artifact goes in a NEW directory, not `tests/golden/`. | Validation Wave 0 | If placed in `tests/golden/`, it could be mistaken for an oracle or collide with the SMA_MACD freeze. Low risk if planner pins the location. `[ASSUMED]` |

## Open Questions (RESOLVED — locked 2026-06-17, see CONTEXT.md D-04/D-10/D-12)

> All three resolved during the planning session and locked inline in CONTEXT.md:
> **Q1 → LOG prices** (D-04); **Q2 → coint as logged DIAGNOSTIC, keep ETH/BTC** (D-10);
> **Q3 → ACCEPT + DOCUMENT the single-sided-liquidation re-entry; dispatch guard DEFERRED** (D-12).

1. **[RESOLVED → log prices]** **Log vs raw prices for β (D-04 wording).** D-04 literally says "OLS of price_A on price_B."
   Offline analysis strongly favors **log prices** (β≈0.53, R²≈0.57 vs raw β≈0.021, R²≈0.44).
   - What we know: raw-price β is near-degenerate and gives a lopsided notional split.
   - What's unclear: whether the owner intends the literal raw-price spread.
   - Recommendation: planner/discuss-phase confirms log prices; default to log in the plan and
     flag it as a confirmable assumption (A1). The strategy can expose a `use_log_prices` knob.

2. **Coint gate vs diagnostic (D-10).** ETH/BTC fails Engle-Granger over every warmup window.
   - What we know: p never < 0.05; the rolling z-score still produces abundant crossings.
   - What's unclear: how strictly "research MUST confirm the coint p-value supports the pair"
     is meant.
   - Recommendation: log the coint p-value as a run diagnostic; do NOT gate the flagship on it.
     The discretion fallback clause ("MAY fall back only if not cointegrated") is now load-bearing
     — but no other pair in `data/` is likely to pass either, so the practical answer is: keep
     ETH/BTC, report the p-value honestly, and rely on the z-score crossing count for the
     non-trivial-round-trips success criterion.

3. **Single-sided liquidation interplay with the in-pair flag (D-07 × D-12).** If one leg is
   liquidated while the strategy still believes it is in-pair, the next exit crossing emits a
   close pair: the surviving leg closes cleanly (clamp-to-flat), but the liquidated leg's close
   resolves as an ENTRY when flat under `LONG_SHORT` (Pitfall 1).
   - What we know: the close-of-an-open-leg path is fully safe; the re-entry-when-flat path is the
     residual risk, bounded by crossing-based one-exit-per-round-trip firing.
   - What's unclear: whether the owner wants the strategy to detect-and-suppress this, or accept
     it as honest flagship behavior (a non-oracle).
   - Recommendation: accept it for the flagship (D-11 explicitly labels this a stability lock,
     not a correctness oracle) and DOCUMENT it. Optionally the planner can add a single read-model
     guard at the dispatch (not the strategy) — but that crosses the D-12 pure-alpha line, so
     the cleaner answer is documentation + the snapshot test capturing whatever actually happens.

## Sources

### Primary (HIGH confidence)
- `itrader/order_handler/admission/admission_manager.py` (read in full) — direction gate :441, explicit-quantity short-circuits :438/:739, side-agnostic reduction + clamp-to-flat :784-800.
- `itrader/order_handler/sizing_resolver.py` (read in full) — `resolve_exit` clamp-to-flat :147-186.
- `itrader/strategy_handler/strategies_handler.py` (read in full) — dispatch loop :76-222, both-present guard :112, warmup :127, fan-out :135-220, WR-01 quantity seam :211, registration gate :280-287, removed pairs branch :235-241.
- `itrader/strategy_handler/base.py` (read in full) — class-attr authoring, `_apply_params`, `evaluate`, auto-warmup, buy/sell sugar (no quantity param).
- `itrader/core/sizing.py` (read in full) — `SignalIntent.quantity`/`exit_fraction` fields, `TradingDirection`, policy validation.
- `itrader/core/enums/trading.py` (read) — `TradingDirection.LONG_SHORT` :26.
- `itrader/price_handler/store/csv_store.py` + `price_handler/feed/bar_feed.py` (read) — multi-ticker `csv_paths`, the 7-rule bar-timing contract.
- `tests/integration/test_backtest_oracle.py`, `tests/e2e/partial_cover/`, `tests/e2e/strategies/single_market_buy.py` (read) — snapshot/diff conventions, cover clamp-to-flat proof, indicator-free `max_window` pattern.
- **Offline statsmodels run (2026-06-17)** against `data/ETHUSD_1d_ohlcv.csv` + `data/BTCUSD_1d_ohlcv_2018_2026.csv` — 1834 aligned bars; raw/log β, coint p-values, z-score crossing counts (reproduced in this doc).

### Secondary (MEDIUM confidence)
- CONTEXT.md D-01..D-15 (the authoritative spec) and ROADMAP §Phase 6.

### Tertiary (LOW confidence)
- None — all claims traced to code or measured offline.

## Metadata

**Confidence breakdown:**
- Engine reuse (admission/exit/sizing/dispatch): HIGH — read in full, cross-checked against the `partial_cover` e2e proof.
- Cointegration / β / z numbers: HIGH — measured offline against the committed CSVs (reproducible).
- Validation surface: HIGH — mirrors existing oracle/e2e conventions; markers/filterwarnings confirmed.
- The log-vs-raw and coint-gate decisions: MEDIUM — they are confirmable assumptions (A1/A2), not engine facts.

**Research date:** 2026-06-17
**Valid until:** 2026-07-17 (stable — engine internals are frozen by milestone discipline; the only volatility is the owner's log-vs-raw / coint-gate decision)
