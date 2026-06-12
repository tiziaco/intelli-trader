---
title: Strategy Authoring Surface — Converged Design (999.5c + strategy-facing edge)
date: 2026-06-12
context: /gsd:explore session converging the strategy authoring interface before /gsd:spec-phase
status: explored — ready to spec
requirements: STRAT-01 (new), IND-01 (refined)
phase: 999.5 Engine Surface Completion — part (c) + the strategy-facing edge
oracles: nautilus-trader, backtesting.py, backtrader (cross-validation oracles already in-repo)
---

# Strategy Authoring Surface — Converged Design

A `/gsd:explore` session converging the **strategy authoring interface** before spec.
Covers 999.5 part (c) (declared-indicator framework / IND-01) **plus a new strategy-facing
edge** that surfaced during the session: a redesign of how a strategy author declares and
passes parameters (now tracked as **STRAT-01**).

> **The central reframe that de-risked the whole exploration:** the *declared-indicator
> framework* (auto-warmup, named handles, crossover sugar) is **orthogonal** to the *compute
> model* (stateless recompute vs stateful incremental). You can ship the entire ergonomic win
> while the engine still recomputes from the window using the identical `ta` calls SMA_MACD
> makes today — **byte-exact by construction**. The stateless→incremental shift becomes a
> separate, opt-in, *later* decision that does not block this phase. W1-05 folds in as
> "declaration layer only; compute stays recompute."

---

## Today's pain (the starting point)

Every strategy author must:
1. Hand-write a frozen pydantic config subclass (`SMA_MACDConfig(BaseStrategyConfig)`) with
   `Field`s + a `@model_validator` for cross-field rules (`short < long`).
2. Pass it to `__init__`.
3. **Manually copy each field onto the instance** (`self.short_window = config.short_window`)
   so `generate_signal` reads `self.short_window` not `self.config` (pure-alpha D-12).
4. Hand-set `self.max_window` (fetch width) and `self.warmup` (D-15 gate).
5. Inline the indicator math and crossover logic in `generate_signal`, recomputing from the
   window every tick (`short_sma.iloc[-1] >= long_sma.iloc[-1]`,
   `MACDhist.iloc[-1] >= 0 and MACDhist.iloc[-2] < 0`).

Boilerplate-heavy and rigid. The goal: lighter-weight authoring that **keeps the D-01 wins**
(typed, validated where it matters, overridable, cross-field where needed) while removing the
ceremony.

---

## Converged design

### 1. Param surface (STRAT-01 — answers PRIMARY Q1 + THIRD Q3)

**One uniform mechanism: class-attribute declarations.** No separate config subclass, no
`@model_validator`, no manual copy.

- The **base `Strategy`** owns the engine-facing names with defaults:
  `timeframe`, `tickers`, `sizing_policy` (required, no default), `order_type` (`MARKET`),
  `direction` (`LONG_ONLY`), `allow_increase` (`False`), `max_positions` (`1`),
  `sltp_policy` (`None`).
- The **subclass** pins what's intrinsic to its logic and adds its alpha knobs as real
  **annotated** class attributes (`short_window: int = 50`).
- **Everything is overridable at construction** via `**kwargs`.
- The base **rejects unknown kwargs loudly** (`UnknownParamError`) — the one accepted runtime
  check, replacing mypy name-checking at the call site.
- `generate_signal` still reads `self.short_window` (real typed instance attrs; **D-12
  preserved**).

```python
# itrader/strategy_handler/base.py — the framework owns these names
class Strategy(ABC):
    timeframe:     Timeframe         # required — no default
    tickers:       list[str]         # required
    sizing_policy: SizingPolicy      # required
    order_type     = OrderType.MARKET
    direction      = LONG_ONLY
    allow_increase = False
    max_positions  = 1
    sltp_policy    = None

# the author's whole file
class SMAMACDStrategy(Strategy):
    sizing_policy  = FractionOfCash("0.95")   # engine-facing: pin what's intrinsic
    direction      = LONG_ONLY
    short_window: int = 50                     # alpha knobs
    long_window:  int = 100
    fast_window:  int = 6
    slow_window:  int = 12
    signal_window: int = 3
    def init(self): ...
    def generate_signal(self, ticker, bars): ...

# deploy (timeframe/tickers are deployment-specific → construction):
s1 = SMAMACDStrategy(tickers=["BTCUSD"], timeframe="1d")
# tune + redeploy the same class, no new file:
s2 = SMAMACDStrategy(tickers=["ETHUSD"], timeframe="4h", short_window=30)
```

**Reuse model = override-at-construction** (chosen): the same class is instantiated many times
with different tickers/timeframes/params; each instance is already a distinct strategy
(`idgen` mints a `strategy_id` per construction, independent registration). This is the
forward-compatible shape for a future ScenarioSpec/composition interface (part b).

**Q3 (declares vs resolves) answer:** no structural split — one declaration surface. The
*engine* knows which attributes to read because the *base* defines the engine-facing names;
the strategy declares everything in one place.

**Validation posture:** heavy pydantic cross-field validation is **not** required on user
strategies (owner call). The base does the lightweight work pydantic used to: collect declared
attrs, apply kwargs overrides, coerce the couple of enum fields (`timeframe` str → enum), raise
on missing-required / unknown-kwarg. `my_strategies/` is already in the mypy `ignore_errors`
override, so user strategies are unconstrained by `--strict`; only the reference SMA_MACD (in
`strategies/`, in-scope) must stay mypy-clean — and it does, because the declared params are
real annotated class attributes mypy sees directly (unlike backtrader's synthesized `self.p.x`).

### 2. Compute model (settled by constraints — answers Q2 crux)

**Stateless recompute-from-window. Byte-exact by construction.** Incremental/stateful is
**rejected for the golden path** and deferred (W1-05). See "Stateful vs stateless" below.

### 3. Indicator framework (IND-01 — answers SECONDARY Q2)

- **Declared in an `init()` hook** (declaration-only — registers `func + input + params`
  recipes; computes nothing). This differs from backtesting.py's `init()` which precomputes
  the full array, because iTrader's feed *pushes a window per tick* (D-20) — there is no full
  series up front. Computation is lazy, per-tick, from the pushed window — the same `ta` calls
  as today.
- **Auto-derived warmup/max_window:** after `init()` runs, the base inspects the registered
  recipes, asks each its min-period from its params (`SMA(50)→50`; `MACD(6,12,3)→slow+signal`),
  and sets `self.max_window` / `self.warmup = max(...)`. The hand-set lines disappear. This is
  backtrader's auto-min-period **idea** as an explicit, inspectable computation (NOT metaclass
  line-propagation).
- **Read shape = model B (pre-evaluated):** the base wraps `generate_signal` — before calling
  it, the base evaluates each declared indicator over that ticker's window, stashes the result
  as `self.short_sma` / `self.macd_hist`, then hands control to the author. The author just
  reads ready handles:

```python
def init(self):
    self.short_sma = self.indicator(SMA, "close", self.short_window)
    self.long_sma  = self.indicator(SMA, "close", self.long_window)
    self.macd_hist = self.indicator(MACDHist, "close", self.fast_window,
                                    self.slow_window, self.signal_window)

def generate_signal(self, ticker, bars):
    if self.short_sma[-1] >= self.long_sma[-1]:        # ready series, no bars passed
        if crossover(self.macd_hist, 0): ...
```

  Model B was chosen over model A (`self.short_sma(bars)` lazy call) partly because **B is
  strictly more future-proof for the incremental switch** — under incremental there is no
  `bars` arg to leak the compute model; the read shape `self.short_sma[-1]` is invariant.

### 4. Comparison primitives (Q2 sub-question)

`crossover(a, b)` / `crossunder(a, b)` — **free functions over series**,
`crossover` ≙ `a[-2] < b[-2] and a[-1] > b[-1]`, reading "previous" from the completed-bars
window (**look-ahead-safe by construction** — the feed window holds only completed bars).
**Additive for new strategies.** SMA_MACD keeps its literal `>=`/`<` comparisons unless we
match the primitive's boundary semantics exactly (byte-exact flag — see Parked decisions).

### 5. Runtime reconfiguration constraint (folds in COMP-01 / part b)

The web-interface use case (change params/timeframe at runtime, e.g. after a re-optimization)
is **in reach and not blocked by this design — but it is not automatic.** A naive
`strategy.short_window = 30` would be *partially* applied and therefore wrong: the indicator
recipes captured the param value at `init()` time, and `max_window`/`warmup` were derived once.

**The constraint this puts on part (c):** make **`init()` and warmup-derivation re-runnable /
idempotent** — not one-shot, construction-only. If the base can call `init()` again (clear
prior recipes, re-register, re-derive warmup), then a later reconfigure is purely *additive* —
it calls the same idempotent rebuild. The stateless model makes this nearly free (no
accumulated state to reset).

- **Tractable tier (alpha params):** `update_params(**kwargs)` → re-validate → re-run `init()`
  → re-derive warmup. Stateless model recomputes from the window with new periods next tick.
- **System-level tier (`timeframe`/`tickers`):** ripples into the feed subscription and ping
  grid / `min_timeframe`; realistically a *replace* rather than a hot-swap.
- **Architecturally consistent path:** web UI → `TradingInterface` → enqueue a reconfigure
  command → applied between event cycles (thread-safe in live), not a cross-thread attribute
  poke mid-`generate_signal`. This **is** COMP-01's "uniform per-handler runtime config-update
  surface" (`StrategiesHandler` currently has none, unlike `PortfolioHandler`/`SimulatedExchange`).
- **Replace-vs-mutate:** each instance is independent, so `remove_strategy(old)` +
  `add_strategy(new(**new_params))` gives a clean fresh `init()`. Cleanest when **flat** (open
  positions are tagged to the old `strategy_id`; in-place mutation preserves that lineage,
  replacement does not). Offer both in the UI.
- **Heads-up — dropped guardrail:** the new plain-attribute surface is mutable by default (the
  old frozen pydantic config, D-03, made `strategy.x = ...` raise). This *enables* reconfig but
  removes the accidental-mutation guardrail (RESEARCH Pitfall 2). The sanctioned-reconfigure-
  method-only discipline is therefore not nice-to-have; it *replaces* the guard being given up.

### 6. Designed-for-later (not built)

Keep the indicator recipe **strategy-decoupled** so an indicator-based SL/TP policy can consume
it in a future phase (SL/TP is currently percent-offset only and out of scope here).

---

## Prior-art verdicts (oracle research)

| Pattern | Verdict | Why |
|---|---|---|
| nautilus typed `StrategyConfig` (read via `self.config.x`) | partial-borrow | Best for mypy, but the owner wants *less* ceremony than a per-strategy config class → class-attribute surface instead, keeping the "engine reads declared values" spirit. |
| backtesting.py class-attribute params (`_check_params` setattr) | borrow the **shape**, add a typed twist | The class-attribute + kwargs-override ergonomics are the target; the runtime "reject unknown key" check is borrowed (the one accepted bit of param magic). |
| backtrader `params` tuple + `MetaParams` metaclass | **REJECT (hard)** | `self.p.x` is synthesized → invisible to `mypy --strict` (a gate). Real annotated class attrs instead. |
| backtesting.py `self.I()` stateless full-array recompute | borrow the **model** | Stateless recompute is the byte-exactness-safe model; adapt to per-tick window (no full-series precompute — feed pushes windows). |
| nautilus/backtrader incremental-stateful indicators | **REJECT for the golden path** | Recursive float accumulators (EMA/MACD) drift the golden numbers; deferred (W1-05). |
| backtrader auto-`minperiod` | borrow the **idea**, reject the **mechanism** | Auto-derive `warmup = max(periods)` as an explicit pure computation, not metaclass line-propagation. |
| crossover primitive | borrow the **free-function shape** | `lib.crossover(a, b)` over series; reject backtrader's `CrossOver`-as-indicator-object (drags in line/metaclass machinery). |

---

## Stateful vs stateless (recorded for the future incremental decision)

- **Stateless recompute** (today + this phase): indicator = pure function of the window;
  recomputed each tick. Trivially deterministic/byte-exact; pure-alpha; reuses `ta`/pandas.
  Cost: O(W) per tick (wasteful but cheap at daily/bounded-window scale — the real cost is
  per-tick `ta`/pandas object construction, negligible here).
- **Stateful incremental** (deferred, W1-05): O(1) per-tick update; ideal for intraday/live/
  many-ticker scale and streaming. Cost: carries mutable state (init/order-sensitive), and
  **byte-exactness risk is structural, not just float noise** — `ta` uses pandas
  `ewm(adjust=True)` (decaying weighted average over all history), while a naive incremental
  EMA is `adjust=False` recursion; they disagree *structurally* during warmup. An incremental
  indicator must be validated value-identical to its stateless twin (or accept a re-baseline).
- **The API is invariant across the switch** *iff* indicators are modelled as a **class behind
  a stable interface** (min-period, current value, **short history buffer** for `[-2]`/
  crossover) from v1, even though every v1 backend is stateless. The switch then = "add a new
  backend implementing the same interface" + a per-bar "feed every bar once, in order" pass the
  base owns (incremental can't be lazy). Author code (`init()` / `generate_signal`) untouched.

---

## Parked for spec-time (genuine decisions, not blockers)

1. **Indicator handle type** — raw pandas Series (`.iloc[-1]`) vs a thin positional-index
   wrapper (`[-1]`, backtesting.py-style reveal). Byte-exact either way; ergonomics call.
2. **SMA_MACD migration depth** — full migration onto the framework vs partial (adopt `init()`/
   handles, keep literal comparisons). The MACD trigger's `>=`/`<` boundary differs from a
   textbook strict `crossover`, so a full migration must match boundary semantics exactly or
   break byte-parity. The per-tick SMA **slice** (`bars[start_dt:]`) is value-neutral for the
   tail → base can compute on the full window uniformly, but the **byte-exact oracle gates it**.
3. **v1 indicator set** — minimum SMA + MACD-hist to migrate the reference; plus the framework
   to add more (EMA/RSI/…) behind the same interface.
4. **Phase slicing** — STRAT-01 (authoring surface) and IND-01 (indicator framework) are
   separable; STRAT-01 could ship first as a smaller byte-exact slice, IND-01 second.

---

## Constraints (carried)

Decimal end-to-end · deterministic (seeded RNG + injected clock) · **tabs** in
`strategy_handler/` modules (4 spaces in `config/`) · SMA_MACD **byte-exact** vs the v1.1 E2E
golden suite unless explicitly re-baselined · `mypy --strict` clean for in-scope code.

## Explicit non-goals (other 999.5 parts — explore separately)

(a) full signal-contract completion (per-intent limit/stop entry price, per-bar order_type) ·
(b) system composition/config interface (ScenarioSpec) — **except** the runtime config-update
seam this design must not preclude · (d) order lifecycle / time-in-force · SL/TP redesign
(percent-offset stays; only designed-for-later consumption of indicators).
