# Phase 6: Pair-Trading Flagship - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a **market-neutral long/short pair-trading strategy** (cointegration / spread) that runs
**end-to-end** through the full backtest run path — opening a long leg and a short leg that both
settle through the **existing Phase 2-4 accounting core** (margin reservation, short PnL, borrow
carry, isolated-margin liquidation) with **NO new correctness branches in the engine**.

This is the **flagship demonstration** that the short side works end-to-end. It is explicitly:
- **NOT the correctness oracle** — the crafted short/leverage/liquidation scenarios under XVAL-01
  are the oracle. A two-leg strategy partially cancels its own sign errors, so it is a *weak*
  oracle by construction (ROADMAP Phase 6 "Re-baseline" note).
- **Additive, not a re-baseline** — it does NOT re-baseline the SMA_MACD golden master. It adds a
  new strategy + its own validation.
- **Slip-able** — a self-contained capstone that can move to an immediate follow-on without
  blocking the shippable margin/shorts core.

**Requirement:** PAIR-01 (the only requirement mapped to this phase).

**Net engine surface added:** a new `PairStrategy` base + a pair-aware dispatch branch in
`StrategiesHandler`. Everything below the signal layer (admission, sizing, settlement, liquidation)
is reused unchanged.

**Explicitly OUT of scope (deferred):** divergence stop-loss band, >1x leverage, rolling/adaptive
β, atomic linked-pair execution, cross-validation of the pair flagship.

</domain>

<decisions>
## Implementation Decisions

### Two-leg authoring & dispatch
- **D-01 (Dedicated `PairStrategy` base):** A new base class declared with a *pair* of tickers,
  dispatched **once per tick** with both legs' completed-bar windows available, returning **both
  legs together**. A new dispatch branch in `StrategiesHandler` (keyed on the pair-strategy type)
  runs it. Isolates pair logic from the per-ticker single-leg path. (Chosen over a multi-intent
  `list[SignalIntent]` return on the existing per-ticker path, and over two single-leg emissions
  across separate per-ticker calls.)
- **D-02 (Require both legs present):** Dispatch the pair decision **only** when **both** legs have
  a bar this tick; otherwise skip silently. The spread/z-score is always computed from two real
  simultaneous prices — no stale/forward-filled leg. Mirrors the existing per-ticker guard at
  `strategies_handler.py:112` (`bar is None → continue`). For ETH/BTC (aligned daily) this rarely
  fires; it is correctness insurance and the reason SOL (sparser) is a weaker pair.
- **D-03 (Two independent orders):** Each leg becomes an **ordinary** `SignalEvent → order → fill →
  portfolio` (one short, one long) — **no OCO/bracket linkage between the legs**. Settles through
  the existing Phase 2-4 path unchanged (this is what "no new correctness branches" means). Pair
  coordination lives entirely in the strategy. If one leg rejects (e.g. margin), the other still
  fills — honest and observable. This is the standard/realistic model: real venues cannot fill two
  instruments atomically (legging risk is real; `backtesting.py`/`backtrader` model legs
  independently; atomic pair execution only exists as venue-native combo instruments, out of scope).

### Spread, hedge ratio & signal rule
- **D-04 (OLS-residual spread, static β):** Hedge ratio β from an OLS regression of price_A on
  price_B (use `statsmodels` OLS — a declared-but-currently-unused dependency); `spread = A − β·B`.
  Textbook cointegration pairs trade; deterministic. (Chosen over the log-price ratio and a rolling
  re-estimated β.)
  - **RESOLVED (research, locked 2026-06-17): use LOG prices.** Offline measurement showed raw
    prices give a near-degenerate β≈0.021 (unbalanced legs, weak market-neutrality); log prices
    give a balanced β≈0.53, R²≈0.57 — the standard cointegration transform. So
    `spread = log(A) − β·log(B)`, β fit on log prices over warmup then frozen (D-05). Expose a
    `use_log_prices` class-attr knob **defaulting to log**. This amends D-04's literal "price"
    wording.
- **D-05 (β fit on warmup, then frozen — look-ahead-safe):** Compute β **once** via OLS over a
  warmup window of **completed bars only** (the strategy's declared warmup), then **freeze** it for
  the rest of the run. The z-score rolling mean/std also use completed bars only. Respects the
  bar-timing/look-ahead contract in `price_handler/feed/bar_feed.py` even though this is not the
  oracle. (Chosen over precomputing β offline over the whole dataset, which leaks future prices.)
- **D-06 (Z-score band trigger):** Standardize the spread to a rolling z-score
  (`z = (spread − rolling_mean) / rolling_std` over a lookback). **Enter** when `|z| > entry`
  (default **2.0**): short the rich leg, long the cheap leg. **Exit** when z reverts toward 0
  (default `|z| < 0.5`). Lookback + thresholds are **overridable class-attr alpha knobs** — pick the
  concrete lookback at plan time.
- **D-07 (No divergence stop — let margin/liquidation govern):** No divergence stop band. If a leg
  keeps diverging, the short leg's margin/maintenance is what eventually governs — possibly a
  Phase 4 liquidation. **Deliberate:** this makes the flagship *demonstrate* the margin/short/
  liquidation core it exists to showcase. A divergence stop is a deferred enhancement.

### Leg sizing & market-neutrality
- **D-08 (β-weighted notional):** Size the legs to the cointegration relationship — for N units of A,
  hold **β·N units of B** (the hedge ratio *is* the neutrality weight). This is the only choice whose
  position P&L actually tracks the z-score signal we trade on (consistent with the `A − β·B` spread).
  The strategy computes both leg quantities and emits an **explicit per-leg `quantity`**; the signal
  contract already honors a caller-supplied quantity (`strategies_handler.py:211`, WR-01), so this
  needs **no new sizing-engine code**. (Chosen over equal-dollar notional and FractionOfCash-per-leg.)
- **D-09 (1x leverage, overridable):** Both legs at leverage **1.0** (each reserves full initial
  margin = notional). Simple capital math; the validation leaf stays hand-verifiable; the short leg
  still exercises the margin + borrow-carry path regardless. Leverage stays an overridable class-attr
  defaulting to `Decimal("1")`; aggressive leverage is a deferred enhancement.

### Pair choice & validation
- **D-10 (ETHUSD / BTCUSD):** The canonical crypto pair — most correlated/cointegrated, deepest
  history overlap (**2021-01-01 → 2026-01-08, ~1834 aligned daily bars**), least sparse. Research
  MUST confirm the `statsmodels` `coint` p-value over the warmup window. (SOL is sparser — 1416 bars
  over the same span — reinforcing D-02.)
  - **RESOLVED (research, locked 2026-06-17): coint is a logged DIAGNOSTIC, not a gate; keep
    ETH/BTC.** ETH/BTC fails strict Engle-Granger over every warmup window (p never < 0.05) — normal
    for crypto majors, and no other pair in `data/` is likely to pass. Log the p-value as an honest
    run diagnostic; do **NOT** gate the run on `p < 0.05`. The rolling z-score still produces 48-72
    round trips, satisfying the "non-trivial round trips" success criterion. The D-10 discretion
    fallback ("MAY fall back if not cointegrated") is therefore **not triggered** — ETH/BTC stays.
- **D-11 (Snapshot + unit tests validation):** Because this is NOT the oracle and IS slip-able, and
  cross-validation is explicitly NOT required:
  - **Hand-verified unit tests** on the hand-computable parts: β/z-score math, `PairStrategy`
    dispatch emits both legs, the require-both-present sync guard (D-02), and β-weighted leg
    quantities (D-08).
  - **A regression-locked SNAPSHOT** of the real ETH/BTC run output (trades/equity), **explicitly
    labeled a STABILITY lock, NOT a hand-verified correctness oracle** — a real multi-year pair run
    is not trade-by-trade hand-computable. Guards against silent output drift without overclaiming.
  - **Determinism double-run byte-identical**; **`mypy --strict` clean**.

### Mechanics (position-awareness, firing, direction, run-end)
- **D-12 (Internal in-pair flag + close-only exits):** The strategy tracks its **own** in-pair state
  (set on entry, cleared on exit), keeping the D-12 "pure alpha / no portfolio access" contract and
  staying simple for the single-portfolio flagship. **REQUIRES** the exit be emitted with close/exit
  semantics (`exit_fraction=1.0`) that the engine resolves as "close existing position, **no-op when
  flat**" — so a liquidated-away leg is NOT re-opened by a stale close. **⚠ MUST-VERIFY in research**
  (see Open Questions): confirm the exit/cover path is close-only / safe-when-flat. This interacts
  directly with D-07 (no stop → a leg can be liquidated out from under the strategy). (Chosen over
  giving `PairStrategy` `PortfolioReadModel` access, which breaks the pure-alpha contract and is
  awkward under the per-portfolio fan-out.)
  - **RESOLVED (research, locked 2026-06-17): exit path is SAFE; single-sided-liquidation re-entry
    ACCEPTED + DOCUMENTED.** The close-only / safe-when-flat path exists — the strategy MUST emit
    β-weighted **explicit-quantity entries** and **quantity-free `exit_fraction=1.0` exits** (an
    explicit `quantity` on an exit would short-circuit the reduction resolver and open a new
    position). Residual hazard (D-07 × D-12): if a leg is liquidated mid-pair while the in-pair flag
    is still set, the next exit crossing's close of the *already-liquidated* leg resolves as a NEW
    entry when flat (bounded to once per round trip). **Accepted as honest flagship behavior** —
    D-11 labels the run a stability lock, not a correctness oracle; the snapshot test captures
    whatever happens; zero new engine surface (keeps the D-12 pure-alpha contract). The dispatch
    guard to suppress it is a tracked follow-up (see Deferred Ideas).
- **D-13 (Crossing-based stateful firing):** **Enter** only when z *crosses into* the band (was
  inside, now `|z| > entry`) AND the strategy is flat; **exit** only when z *crosses back inside*
  (`|z| < exit`) AND the strategy is in-pair. One clean entry/exit per round trip; pairs naturally
  with the D-12 in-pair flag. (Chosen over level-based every-bar emission, which floods the signal
  log with `allow_increase`-rejected repeats.)
- **D-14 (Declare `direction = TradingDirection.LONG_SHORT`):** Strategy-level class attr, carried
  onto each leg's `SignalEvent` at fan-out (`strategies_handler.py:202`). The BUY leg passes
  admission as a long entry, the SELL leg as a short entry — both clear the direction gate.
  **VERIFIED in code:** `LONG_SHORT` already exists (`core/enums/trading.py:26`) and is already
  handled at `admission_manager.py:441` (the Phase 3 short seam) → **ZERO new admission code**.
  (Chosen over per-leg intent-level direction threading, which is unneeded.)
- **D-15 (Leave open at run end, mark-to-market):** If z hasn't reverted at run end, both legs stay
  open and are marked-to-market in final equity — the existing engine behavior (TIF expiry only
  sweeps RESTING orders, not filled positions). Honest unrealized pair P&L; no new code. (Chosen over
  a bespoke run-end force-close.)

### Claude's Discretion
- Concrete z-score **lookback window** and the exact **entry/exit thresholds** (defaults 2.0 / 0.5)
  are overridable class-attr alpha knobs — planner picks sensible values; tune so the ETH/BTC run
  produces a non-trivial number of round trips.
- The concrete pair MAY fall back from ETH/BTC only if research finds it is not cointegrated over the
  warmup window (unlikely); default stays ETH/BTC.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirement
- `.planning/ROADMAP.md` §"Phase 6: Pair-Trading Flagship" (lines 315-331) — goal, success
  criteria, "NOT the correctness oracle / slip-able capstone" framing, re-baseline stance.
- `.planning/REQUIREMENTS.md` — PAIR-01 (line 117), the single mapped requirement.
- `.planning/notes/margin-leverage-shorts-999.4.md` §7 ("Flagship validation") and §9 Q3
  ("Pair-trading flagship placement") — original design intent for the flagship.

### Strategy authoring surface (where the new PairStrategy + dispatch land)
- `itrader/strategy_handler/base.py` — `Strategy` base, `evaluate()` orchestration seam,
  `generate_signal()`, the `buy`/`sell` intent sugar, required class-attr contract (tickers,
  timeframe, sizing_policy, direction, warmup/max_window auto-derivation).
- `itrader/strategy_handler/strategies_handler.py` — the per-ticker dispatch loop (lines 76-215):
  the both-legs-present guard model (`:112`), warmup short-circuit (`:127`), per-intent signal
  recording + per-portfolio fan-out, the caller-supplied-quantity seam (`:211`, WR-01), and
  `direction`/`leverage` carry onto `SignalEvent` (`:202`/`:210`).
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` — the reference strategy / authoring
  pattern (class-attr params, `init()` indicator declaration, `validate()`).
- `itrader/core/sizing.py` — `SignalIntent`, `TradingDirection`, sizing-policy vocabulary
  (`FractionOfCash`/`FixedQuantity`/`RiskPercent`) and the caller-`quantity` field.

### Accounting core the legs reuse (no new branches — read to confirm reuse)
- `itrader/order_handler/admission/admission_manager.py` — direction gate (`:441` `LONG_SHORT`
  branch; `:459` `LONG_ONLY`, `:471` `SHORT_ONLY`), the cover-arm / `allow_increase`
  direction-agnostic settlement reuse.
- `itrader/core/enums/trading.py` — `TradingDirection` (`LONG_ONLY`/`LONG_SHORT`/`SHORT_ONLY`).
- `itrader/price_handler/feed/bar_feed.py` — the bar-timing / look-ahead contract β-fit and z-score
  must respect (D-05).
- Phase 2-4 / 05.1 CONTEXT + ATTRIBUTION docs under `.planning/phases/02..05.1/` — margin
  reservation, short PnL, borrow carry, isolated-margin liquidation, short scale-in semantics the
  legs settle through.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Per-portfolio fan-out + signal recording** (`strategies_handler.py:135-215`) — once the pair
  dispatch produces two intents, the existing fan-out loop turns each into a `SignalEvent` per
  subscribed portfolio with no change.
- **Caller-supplied `quantity` seam** (`strategies_handler.py:211`, WR-01) — lets the strategy emit
  explicit β-weighted leg sizes (D-08) without touching `SizingResolver`.
- **`TradingDirection.LONG_SHORT` + admission branch** (`core/enums/trading.py:26`,
  `admission_manager.py:441`) — already present from Phase 3; the pair declares it and both legs are
  admitted with zero new gate code (D-14).
- **Margin/short/carry/liquidation core** (Phases 2-4) — each leg is an ordinary short/long, so all
  settlement is reused unchanged (D-03).
- **`statsmodels` OLS/`coint`** — a declared dependency currently unused in `itrader/`; this phase is
  its first real use (β fit + cointegration check).

### Established Patterns
- **D-12 pure-alpha contract:** strategies have no portfolio access; the handler owns everything
  portfolio-shaped. D-12 (internal flag) keeps the new pair strategy inside this contract.
- **Class-attr authoring + `init()` recipes** (v1.3 STRAT-01/IND-01) — the pair base should follow
  the same shape (engine-facing attrs on the base, alpha knobs on the subclass, reject-unknown-kwargs,
  re-runnable `init()`).
- **Look-ahead safety enforced in the window slice / feed, never in strategies** — β-fit and z use
  completed bars only.
- **Tabs in handler modules; 4 spaces in `core/`, `config/`, `price_handler/feed/`** — match the file.

### Integration Points
- New `PairStrategy` base: `itrader/strategy_handler/` (alongside `base.py`).
- New dispatch branch: `StrategiesHandler.calculate_signals` (the per-strategy loop) — detect the
  pair-strategy type and route to a pair dispatch that delivers both legs' windows, instead of the
  per-ticker loop.
- Reference pair strategy: `itrader/strategy_handler/strategies/` (alongside `SMA_MACD_strategy.py`).
- Validation: unit tests under `tests/unit/strategy/` (β/z/dispatch); a stability snapshot +
  determinism run under `tests/integration/` (or a dedicated `tests/e2e/` leaf) using ETH/BTC.

</code_context>

<specifics>
## Specific Ideas

- Pair: **ETHUSD / BTCUSD**, daily.
- Spread: **OLS residual `A − β·B`**, β = OLS(price_ETH on price_BTC), fit once on warmup then frozen.
- Signal: **z-score bands**, enter `|z| > 2.0` (short rich / long cheap), exit `|z| < 0.5`,
  crossing-based and stateful.
- Sizing: **β-weighted** explicit per-leg quantity; **1x** leverage.
- The flagship should produce a **non-trivial number of round trips** over the 2021-2026 window and
  ideally surface at least one margin/liquidation event (D-07) as the headline demonstration.

</specifics>

<deferred>
## Deferred Ideas

- **Divergence stop-loss band** (force-close both legs when `|z| > stop_threshold`) — deferred; the
  no-stop choice (D-07) is deliberate so the flagship demonstrates the liquidation core.
- **Aggressive / levered legs (>1x)** to amplify the leverage + liquidation interplay — deferred;
  1x chosen for a hand-verifiable first flagship (leverage stays an overridable class-attr, D-09).
- **Rolling / adaptive hedge-ratio β re-estimation** — deferred; static fit-on-warmup-then-freeze
  chosen (D-05).
- **Atomic linked-pair execution** (both legs commit-or-reject together) — rejected; would require a
  new correctness branch in admission/settlement, contradicting the phase boundary (D-03).
- **`PortfolioReadModel` access for strategies** — rejected for this phase; breaks the pure-alpha
  contract and is awkward under per-portfolio fan-out (D-12).
- **Cross-validation of the pair flagship vs `backtesting.py`/`backtrader`** — explicitly NOT
  required (the crafted XVAL-01 scenarios are the oracle); a possible later nice-to-have.
- **TODO — single-sided-liquidation re-entry guard (follow-up to D-12 resolution, 2026-06-17):**
  Investigate the D-07 × D-12 edge case where a liquidated-away leg's stale close re-opens a new
  single-leg position, and **ideally implement a guard** (a read-model check at the *dispatch*
  layer that detects an in-pair flag with only one live leg and suppresses the spurious re-entry).
  Deferred for the flagship (accepted + documented for now, per D-12 resolution); not blocking. The
  Phase 6 snapshot should capture whether this actually fires on the ETH/BTC 1x run to size the
  follow-up.

</deferred>

<open_questions>
## Open Questions for Research (must resolve before/while planning)

1. **⚠ Exit path is close-only / safe-when-flat (D-12 blocker).** Confirm that a cover/close signal
   (BUY to close a short leg, SELL to close a long leg, `exit_fraction=1.0`) resolves to "close the
   existing position only, no-op when flat" — so a leg that was **liquidated out from under the
   strategy** (D-07) is NOT re-opened into an unintended new position by a stale close. Trace
   `OrderManager`/admission exit-vs-entry resolution + the CR-01 cover-arm. If the path can flip
   flat→new-position, escalate (the D-12 internal-flag choice depends on this being safe).
2. **ETH/BTC cointegration over the warmup window** — confirm `statsmodels.coint` p-value supports
   the pair; record the fitted β and a sensible z-score lookback.
3. **Where the pair dispatch branches** — confirm the cleanest hook in `StrategiesHandler` to deliver
   both legs' windows once per tick without disturbing the per-ticker path for single-leg strategies.

</open_questions>

---

*Phase: 6-Pair-Trading Flagship*
*Context gathered: 2026-06-17*
