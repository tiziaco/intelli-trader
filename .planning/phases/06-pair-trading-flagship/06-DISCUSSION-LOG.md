# Phase 6: Pair-Trading Flagship - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 6-Pair-Trading Flagship
**Areas discussed:** Two-leg authoring & dispatch, Spread/hedge-ratio/signal rule, Leg sizing & market-neutrality, Pair choice & validation, Mechanics (position-awareness, firing, direction, run-end)

---

## Two-leg authoring & dispatch

### How does the strategy see both legs and emit a coordinated long+short?

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated PairStrategy base | New base declared with a ticker pair, dispatched once per tick with both windows; returns both legs; new dispatch branch in StrategiesHandler | ✓ |
| Multi-intent + partner access | Keep per-ticker dispatch; return list[SignalIntent] + feed access to the partner leg | |
| Two single-leg emissions | Cache spread state; emit long on one ticker call, short on the other | |

**User's choice:** Dedicated PairStrategy base.

### On a tick where only one leg has a bar, what should dispatch do?

| Option | Description | Selected |
|--------|-------------|----------|
| Require both legs present | Dispatch only when both legs have a bar this tick; else skip silently | ✓ |
| Forward-fill missing leg | Carry last-seen price and still compute the spread | |

**User's choice:** Require both legs present.

### How should the two legs reach the accounting core?

| Option | Description | Selected |
|--------|-------------|----------|
| Two independent orders | Each leg an ordinary SignalEvent→order→fill→portfolio; no linkage; reuses Phase 2-4 path | ✓ |
| Linked atomic pair | Both legs commit-or-reject together; requires a new correctness branch | |

**User's choice:** Two independent orders.
**Notes:** User asked whether independent legs is the common choice for pair trading systems. Confirmed yes — real venues can't fill two instruments atomically (legging risk is real and named); backtesting.py/backtrader model legs as independent orders; atomic pair execution only exists as venue-native combo instruments (out of scope). Independent legs is the faithful model, not a shortcut.

---

## Spread, hedge ratio & signal rule

### Spread / hedge-ratio definition

| Option | Description | Selected |
|--------|-------------|----------|
| OLS residual, static β | β = OLS(A on B); spread = A − β·B; fixed β | ✓ |
| Log-price ratio | spread = log(A) − log(B), implicit β=1 | |
| Rolling β (re-estimated) | Re-fit β on a rolling window each tick | |

**User's choice:** OLS residual, static β.

### Trigger rule

| Option | Description | Selected |
|--------|-------------|----------|
| Z-score bands | Enter |z|>2 (short rich/long cheap), exit |z|<~0.5 | ✓ |
| Fixed spread bands | Trigger on raw spread crossing fixed absolute levels | |

**User's choice:** Z-score bands.

### β-timing / look-ahead safety

| Option | Description | Selected |
|--------|-------------|----------|
| Fit on warmup, then freeze | OLS over a warmup window of completed bars, then frozen | ✓ |
| Precompute β offline, hardcode | Fit over the whole dataset offline (look-ahead leak) | |

**User's choice:** Fit on warmup, then freeze.

### Divergence stop?

| Option | Description | Selected |
|--------|-------------|----------|
| No stop — let margin/liquidation govern | No stop band; diverging leg governed by margin/maintenance (possibly liquidation) | ✓ |
| Add a divergence stop | Force-close both legs when |z| > stop_threshold | |

**User's choice:** No stop — let margin/liquidation govern (deliberate: makes the flagship demonstrate the liquidation core).

---

## Leg sizing & market-neutrality

### Leg sizing

| Option | Description | Selected |
|--------|-------------|----------|
| β-weighted notional | qty_B = β·qty_A; position P&L tracks the z-score; reuses caller-quantity seam | ✓ |
| Equal dollar notional | Same $ per leg; only β-neutral when β≈1 | |
| FractionOfCash per leg | Each leg X% of cash independently; uncoordinated | |

**User's choice:** β-weighted notional.
**Notes:** User asked the difference between approaches + what's best. Explained that β-weighted is the only choice internally consistent with the `A − β·B` spread — the position P&L then *is* the spread, so it tracks the z-score we enter on. Equal-dollar leaves residual common-factor exposure when β≠1; FractionOfCash isn't coordinated at all.

### Leg leverage

| Option | Description | Selected |
|--------|-------------|----------|
| 1x (default 1.0, overridable) | Each leg reserves full margin = notional; simple, hand-verifiable | ✓ |
| Modest leverage (e.g. 2x) | Levered legs to amplify liquidation interplay | |
| You decide at plan time | Leave value to planning | |

**User's choice:** 1x (default 1.0, overridable).

---

## Pair choice & validation

### Which pair?

| Option | Description | Selected |
|--------|-------------|----------|
| ETHUSD / BTCUSD | Canonical crypto pair; deepest overlap (~1834 aligned daily bars); least sparse | ✓ |
| SOLUSD / ETHUSD | Both alt-coins; SOL sparser; noisier cointegration | |
| You decide at plan time | Pick strongest cointegration at planning (default ETH/BTC) | |

**User's choice:** ETHUSD / BTCUSD.

### Validation approach

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot + unit tests | Hand-verified unit tests (β/z/dispatch/sizing) + regression-locked stability snapshot of the real run + determinism | ✓ |
| Crafted synthetic leaf | Tiny hand-computable 2-symbol scenario in addition to unit tests | |
| Integration smoke only | End-to-end runs, opens both legs, deterministic; no snapshot | |

**User's choice:** Snapshot + unit tests.

---

## Mechanics (additional gray areas — user chose to explore all four)

### Position-awareness seam

| Option | Description | Selected |
|--------|-------------|----------|
| Internal flag + close-only exits | Strategy tracks its own in-pair state; exits are close-only/no-op-when-flat; keeps D-12 | ✓ |
| PortfolioReadModel access | Give PairStrategy read-only position access; robust vs liquidation but breaks pure-alpha | |

**User's choice:** Internal flag + close-only exits.
**Notes:** Surfaced a tension with the no-stop decision — a liquidated-away leg could be re-opened by a stale close. Resolved by requiring close-only/safe-when-flat exit semantics (flagged as a must-verify research item in CONTEXT Open Questions).

### Entry/exit firing & re-entry

| Option | Description | Selected |
|--------|-------------|----------|
| Crossing-based (stateful) | Enter on crossing into band & flat; exit on crossing back inside & in-pair | ✓ |
| Level-based every bar | Emit entry every bar |z|>2; rely on allow_increase=False to reject repeats | |

**User's choice:** Crossing-based (stateful).

### Direction & admission

| Option | Description | Selected |
|--------|-------------|----------|
| Declare LONG_SHORT | direction = TradingDirection.LONG_SHORT; both legs admitted; reuses Phase 3 seam (admission_manager.py:441); zero new code | ✓ |
| Per-leg intent direction | Thread direction onto each SignalIntent | |

**User's choice:** Declare LONG_SHORT.

### Run-end open positions

| Option | Description | Selected |
|--------|-------------|----------|
| Leave open, mark-to-market | Both legs stay open, marked-to-market in final equity (existing behavior) | ✓ |
| Force-close at run end | Bespoke run-end close of open legs | |

**User's choice:** Leave open, mark-to-market.

---

## Claude's Discretion

- Concrete z-score lookback window and exact entry/exit thresholds (defaults 2.0 / 0.5) — overridable
  class-attr alpha knobs, planner picks sensible values for a non-trivial number of round trips.
- Pair MAY fall back from ETH/BTC only if research finds it not cointegrated over the warmup window
  (unlikely); default stays ETH/BTC.

## Deferred Ideas

- Divergence stop-loss band (deferred; no-stop is deliberate per D-07).
- Aggressive / >1x leverage (deferred; 1x for a hand-verifiable first flagship).
- Rolling / adaptive β re-estimation (deferred; static fit-on-warmup chosen).
- Atomic linked-pair execution (rejected; would add a new correctness branch).
- PortfolioReadModel access for strategies (rejected this phase; breaks pure-alpha contract).
- Cross-validation of the pair flagship vs backtesting.py/backtrader (explicitly NOT required here).
