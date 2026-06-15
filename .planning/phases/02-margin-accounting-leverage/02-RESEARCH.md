# Phase 2: Margin Accounting & Leverage - Research

**Researched:** 2026-06-15
**Domain:** Backtest portfolio margin accounting, leverage application, equity-based sizing (iTrader event-driven engine)
**Confidence:** HIGH (codebase-verified; all assertions grounded in live source reads)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (over-margin → REJECT):** Required `initial_margin` > free margin → REJECTED via the existing over-cash path (no reservation, empty cash ledger, CASH-02 `release_rejected` precedent). NOT clipped. With `enable_margin=False`/leverage 1, required margin == notional → byte-exact vs today's funds check.
- **D-02:** Leverage decided by strategy, applied by order/risk layer (the "strategies declare, engine resolves" split, mirroring sizing).
- **D-03:** Strategy emits concrete `leverage: Decimal` on `SignalEvent`, default `Decimal("1")` → byte-exact. NOT a typed policy. Shaped so a typed/equity-aware policy can replace the scalar later without a second contract change.
- **D-04:** `effective = min(signal.leverage, Instrument.max_leverage, portfolio.max_leverage)` when `enable_margin`, else forced to 1. `Instrument.max_leverage` = per-symbol venue ceiling; `portfolio.max_leverage` = account-wide cap.
- **D-05 (over-cap):** clamp to cap + log a warning (venue-realistic). NOT reject, NOT silent.
- **D-06:** A position has ONE effective leverage, set at open (isolated margin). A differing `signal.leverage` on a scale-in is clamped to the position's leverage.
- **D-07:** New equity-based `SizingPolicy` kind (LeveredFraction/KellyFraction) reading equity (like `RiskPercent`), permits `f>1` only when `enable_margin` → `notional = f × equity`. `FractionOfCash` keeps its strict `(0,1]` guard intact.
- **D-07a:** Kelly estimates exposure fraction `f` (sizing), not leverage; `f` sets size, `L` sets margin backing + liquidation distance — complementary.
- **D-08:** Margin reservation = `initial_margin (= notional / L) + estimated_commission`; commission computed on full traded notional. Liquidation penalty rides the existing commission/fee field — no new field.
- **D-09:** Two cash models gated by `enable_margin`. Spot (`False`): today's debit-notional flow untouched (byte-exact). Margin (`True`): lock-and-settle — lock `initial_margin` for the position's life, do not spend notional, settle realized PnL on close, release margin on close.
- **D-10 (ownership):** `CashManager` owns a position-keyed locked-margin container, distinct from the order_id-keyed pending reservation. `available = balance − order_reservations − locked_margin`. No 5th sub-manager reaching into cash state.
- **D-11 (scale-in/out):** Pro-rata aggregate. `locked_margin = aggregate_notional / L`, recomputed as fills aggregate. Scale-in adds margin at the position's leverage; partial close of fraction `p` releases `p × locked_margin` and settles `p × PnL`. NOT per-tranche FIFO.
- **D-12:** Levered-Kelly sizing and the free-margin/maintenance-margin checks use mark-to-market `total_equity()` (cash + unrealized PnL, marked at decision-bar close). Already exists on `PortfolioReadModel`. Oracle-dark.
- **D-13:** Maintenance margin computed on demand, exposed via the read-model — NOT a stored mutable `Position` field. `maintenance_margin = Instrument.maintenance_margin_rate × |size| × current_price`. Expose `maintenance_margin` + `margin_ratio` on `PortfolioReadModel`.
- **D-13a:** Stored field creates a second source of truth that fights the N+4 `Account` mirror. Computed read-model swaps cleanly: backtest computes locally, live reconciles from venue, consumers never change.
- **D-14:** Add `max_leverage: Decimal = 1` to `config/portfolio.py::TradingRules` as the account-wide cap. NO portfolio `default_leverage`. Default 1 → byte-exact.
- **D-15:** Margin/leverage config participates in the uniform `update_config` seam (merge → validate → atomic-swap). Caveat: existing open positions keep their opened-under terms; new config applies only to new orders.
- **D-16:** Phase 2 has NO force-close. Free margin / margin_ratio read negative/breached honestly; new-order admission rejected when free margin < required; equity can drift negative — DEF-01-C stays open until Phase 4 (LIQ-01).
- **D-17:** Thorough component/unit tests AND a hand-verified, PARKED leveraged-long integration/e2e scenario, frozen as golden ONLY at Phase 4 under XVAL-01. SMA_MACD held byte-exact. mypy --strict clean; Decimal end-to-end; determinism double-run byte-identical.

### Claude's / Planner's Discretion
- Exact placement of the `notional/L` division (admission gate vs portfolio reserve) and the precise free-margin computation plumbing.
- The new sizing-policy name/signature (`LeveredFraction` vs `KellyFraction`) and its resolver arm shape (mirror `RiskPercent`).
- The `SignalEvent` `leverage` field name/default plumbing and the `PortfolioReadModel` `maintenance_margin`/`margin_ratio` accessor signatures.
- The BTCUSD `Instrument` `max_leverage` / `maintenance_margin_rate` values for the parked leveraged-long scenario (oracle-dark; realistic crypto defaults).
- Indentation: tabs in `portfolio_handler/`, `order_handler/`, `strategy_handler/`, `execution_handler/`; 4 spaces in `core/`, `config/` — match the file.

### Deferred Ideas (OUT OF SCOPE)
- Equity/drawdown-aware leverage policy (typed risk overlay) — replaces the scalar later.
- Clip-to-fit over-margin handling — alternative to D-01 reject.
- Vol-targeting / portfolio-level leverage overlays.
- Per-tranche FIFO margin.
- Margin-call / liquidation-warning EventType (N+4 live/UI).
- Liquidation force-close trigger LIQ-01 (Phase 4); shorts + CR-01 cover-arm + borrow carry (Phase 3); funding/mark-price/perp realism (Phase B/N+4).
- N+4 `Account` reconciliation mirror.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MARGIN-01 | Opening a position reserves `initial_margin = notional / leverage` against available cash (not full notional) | Lock-and-settle cash model (§ Architecture Pattern 2); `CashManager` position-keyed locked-margin container (D-10). Gated by `enable_margin` so spot path's `net_cash_delta` debit-notional flow is untouched. |
| MARGIN-02 | An order exceeding available free margin is rejected (or clipped) | D-01 reject: reuse the existing `admission_manager.py:227` cash-reservation gate → `InsufficientFundsError` → audited REJECTED. The reservation amount changes from `price*qty+commission` to `initial_margin+commission` when margin-on. |
| MARGIN-03 | Maintenance margin tracked and queryable per open position | Compute-on-demand via `PortfolioReadModel.maintenance_margin` / `margin_ratio` (D-13), using `Instrument.maintenance_margin_rate` and mark-to-market `total_equity()` (D-12). |
| LEV-01 | Configurable leverage > 1; `notional/L` posted as margin | `SignalEvent.leverage` field (D-03) + cap at `min(signal, Instrument.max_leverage, portfolio.max_leverage)` (D-04); `TradingRules.max_leverage` config (D-14); `update_config` participation (D-15). |
| LEV-02 | Levered Kelly fraction > 1 expressible: `notional = f × equity` | New equity-based sizing policy (D-07) reading `total_equity()`, permitting `f>1` only when `enable_margin`; resolver arm mirrors `RiskPercent` (§ Sizing resolver arm). |
</phase_requirements>

## Summary

Phase 2 adds margin accounting to a backtest engine whose spot golden master (SMA_MACD: 134 trades / `final_equity 46189.87730727451`) MUST stay byte-exact. The entire risk is **leakage of the new code into the spot path**. The good news from reading the live code: the spot path is narrow and well-isolated, and every new behavior naturally collapses to the existing behavior when `enable_margin=False`, leverage=1, and `FractionOfCash` is the policy. The byte-exact gate is structural, not incidental.

The single most important byte-exact insight: the spot cash flow is owned by exactly TWO expressions — `admission_manager.py:228` (`cost = primary.price * primary.quantity + self._estimate_commission(primary)`, the pre-trade reservation) and `Transaction.net_cash_delta` (`-(price*quantity + commission)` for a BUY, the settlement debit). Margin mode replaces the reservation amount with `initial_margin + commission` and replaces the settlement from "debit full notional" to "lock margin + settle realized PnL on close". Both are reachable through a clean `enable_margin` branch; with margin OFF the new arithmetic is literally `notional / 1 == notional`, so the spot path can be made provably byte-identical.

Three structural gaps the planner must close: (1) the order domain (`AdmissionManager`) has **no current access to `Instrument` / `Universe`** — `Universe` is injected only into `SimulatedExchange` today, so `max_leverage` / `maintenance_margin_rate` are not reachable where the cap and reservation are computed; a new injection seam is required. (2) `CashManager` has a single `available_balance = balance − reserved` figure — the position-keyed `locked_margin` is a genuinely new container, and `available` must subtract both. (3) `Position` carries no leverage; the one-leverage-per-position invariant (D-06) needs a new home, and `locked_margin` is position-keyed so the lifecycle (open/scale-in/partial-close/full-close) must be plumbed against position transitions, NOT order transitions.

**Primary recommendation:** Land the `enable_margin` branch at exactly two sites (the admission reservation amount and the portfolio settlement), inject `Universe` into the order domain for leverage capping, add a position-keyed `locked_margin` container to `CashManager` and a `_locked_margin` figure to `available_balance`, add the `LeveredFraction` resolver arm mirroring `RiskPercent`, and expose `maintenance_margin`/`margin_ratio` compute-on-demand on `PortfolioReadModel`. Hold SMA_MACD byte-exact by keeping every new path gated and oracle-dark. Park (do not freeze) the leveraged-long e2e for P4/XVAL-01.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Leverage value carried on signal | `events_handler/events/signal.py` (event contract) | `core/sizing.py::SignalIntent` (strategy-return) | The strategy declares; the event is the cross-domain transport (D-03). Strategies never compute margin. |
| Leverage cap (`min(...)`) + force-to-1 | `order_handler/admission/admission_manager.py` (order/risk layer) | `universe/universe.py` (Instrument source) | "Engine resolves against per-portfolio state" (D-02/D-04). Requires `Instrument.max_leverage` + `portfolio.max_leverage`. |
| Initial-margin reservation (`notional/L + commission`) | `admission_manager.py` (admission gate) | `CashManager.reserve_cash` (pending reservation) | Pre-trade gate is admission's job (the existing `:227` cash gate); the reservation mechanism is CashManager's. |
| Over-margin reject (MARGIN-02) | `admission_manager.py` (existing REJECTED path) | — | D-01 reuses the existing `InsufficientFundsError` → audited REJECTED path verbatim. |
| Lock-and-settle position-lifetime margin | `portfolio_handler/cash/cash_manager.py` (cash authority, D-10) | `portfolio.py::process_transaction` (settlement orchestration) | One cash authority owns locked margin; the Portfolio orchestrates the open/scale/close sequence that drives lock/release. |
| Equity-based sizing (`notional = f × equity`) | `order_handler/sizing_resolver.py` (the ONE resolver) | `core/sizing.py` (policy kind) | "Strategies declare, engine resolves" (D-07). New resolver arm reads `total_equity()` via the read-model. |
| Maintenance-margin / margin_ratio query | `core/portfolio_read_model.py` (read boundary) + `portfolio_handler.py` (impl) | `core/instrument.py` (`maintenance_margin_rate`) | Compute-on-demand read-model (D-13/D-13a) — single source of truth, live-ready. |
| `max_leverage` config + runtime reconfig | `config/portfolio.py::TradingRules` | `portfolio_handler.py::update_config` | Account-wide cap config (D-14) flows through the uniform `update_config` seam (D-15). |

## Standard Stack

This is a brownfield refactor of an existing pure-Python engine. **No new external dependencies are required or recommended.** Everything is built on the existing stack.

### Core (existing, reused — no install)
| Module | Purpose | Why standard here |
|--------|---------|-------------------|
| `decimal.Decimal` (stdlib) | All margin/leverage/equity math | Money is Decimal end-to-end (locked project decision); `notional/L` stays Decimal. |
| `itrader/core/money.py::to_money` / `quantize` | Decimal entry + boundary rounding | The ONLY sanctioned Decimal entry point (string path); `quantize(value, instrument, kind)` now reads scale off the Phase-1 `Instrument`. |
| `itrader/core/sizing.py` | `SizingPolicy` union, `RiskPercent` template | The new `LeveredFraction` policy lives here beside `RiskPercent` (D-02 growth rule: add a kind). |
| `itrader/core/portfolio_read_model.py` | `PortfolioReadModel` Protocol, `total_equity()` | Margin checks read equity here (D-12); new `maintenance_margin`/`margin_ratio` accessors land here. |
| `itrader/core/instrument.py::Instrument` | `max_leverage`, `maintenance_margin_rate` | Landed INERT in Phase 1; consumed here (the fields already exist, frozen, Decimal-typed). |
| `itrader/universe/universe.py::Universe` | `symbol → Instrument` resolution | The injectable seam to reach `Instrument` fields; **currently NOT injected into the order domain** (see Pitfall 1). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Position-keyed `locked_margin` in `CashManager` (D-10) | A 5th `MarginManager` sub-manager | D-10 explicitly rejects this — it would create a second authority reaching into cash state. Locked margin IS cash state. |
| `leverage: Decimal` scalar on `SignalEvent` (D-03) | A typed `LeveragePolicy` object | D-03 rejects this for v1 — a scalar is already fully dynamic; the field is shaped to grow into a typed policy later without a second contract change. |
| Compute-on-demand maintenance margin (D-13) | Stored `Position.maintenance_margin` field | D-13a rejects this — a stored field fights the N+4 venue-reconciliation mirror (second source of truth). |

**Installation:** None. No packages added. (Cross-validation oracles `backtesting.py 0.6.5` and `backtrader 1.9.78.123` are already installed; they are consumed at Phase 4, not here.)

## Package Legitimacy Audit

> Not applicable — Phase 2 installs no external packages. All work is internal refactor on the existing pinned stack (`pyproject.toml` / `poetry.lock`, already committed and slopcheck-irrelevant). slopcheck gate: SKIPPED (no install).

## Architecture Patterns

### System Architecture Diagram (the margin-relevant data flow)

```
STRATEGY (SMA_MACD or levered)
   │  emits SignalIntent → SignalEvent { ..., leverage: Decimal = 1 }   [D-03]
   ▼
SIGNAL route
   │
   ▼
OrderHandler.on_signal → OrderManager → AdmissionManager.process_signal
   │
   ├─ 0. admission gates (direction / max_positions / increase)         [unchanged]
   ├─ 1. SizingResolver.resolve_entry(policy, ...)                       [D-07 new arm]
   │        FractionOfCash → (frac*available)/price        (spot, oracle-dark)
   │        LeveredFraction → (f*total_equity())/price      (margin; f>1 iff enable_margin)
   ├─ 1b. effective_leverage = cap(signal.leverage, instr.max_lev, pf.max_lev)  [D-04]
   │        ── needs Universe.instrument(ticker) in the order domain ──  [GAP — Pitfall 1]
   │        ── force to 1 when not enable_margin ──                       [D-04 byte-exact]
   ├─ 2. build primary Order (PENDING)
   ├─ 3. validate ENTITY
   ├─ 3b. CASH-RESERVATION GATE  [admission_manager.py:227–248]           [BYTE-EXACT SITE #1]
   │        spot:   cost = price*qty + commission          (notional)
   │        margin: cost = (price*qty)/L + commission       (initial_margin)
   │        InsufficientFunds → audited REJECTED (D-01, reuse verbatim)
   └─ 4. assemble bracket + emit OrderEvent(s)
   ▼
ORDER route → ExecutionHandler → SimulatedExchange/MatchingEngine → FillEvent(EXECUTED)
   ▼
FILL route
   ├─ PortfolioHandler.on_fill → Portfolio.process_transaction           [BYTE-EXACT SITE #2]
   │        net_delta = Transaction.net_cash_delta
   │        spot:   debit full notional  (-(price*qty+commission))       (unchanged)
   │        margin: lock initial_margin (open), settle realized PnL (close), release margin (close)
   │        ── CashManager owns position-keyed locked_margin (D-10) ──
   │        ── available = balance − order_reservations − locked_margin ──
   └─ OrderHandler.on_fill → ReconcileManager → release order reservation (terminal)  [unchanged]
   ▼
each BAR: PortfolioHandler.update_portfolios_market_value → mark positions to close   [unchanged]
   │
   ▼  (query-only, no mutation)
PortfolioReadModel.maintenance_margin / margin_ratio  ← UI/live query  [D-13 compute-on-demand]
```

### Recommended Code-Change Map (not new dirs — surgical edits to existing files)
```
itrader/
├── events_handler/events/signal.py     # + leverage: Decimal = Decimal("1")   (D-03, 4-space file)
├── core/
│   ├── sizing.py                        # + LeveredFraction dataclass + union member (D-07)
│   │                                    # + SignalIntent.leverage field
│   ├── portfolio_read_model.py          # + maintenance_margin(), margin_ratio() Protocol members (D-13)
│   └── instrument.py                    # (no change — fields already inert from Phase 1)
├── config/portfolio.py                  # + TradingRules.max_leverage: Decimal = 1   (D-14, 4-space file)
├── order_handler/
│   ├── sizing_resolver.py               # + LeveredFraction case arm (mirror RiskPercent)  (4-space? — VERIFY, see below)
│   └── admission/admission_manager.py   # leverage cap + margin reservation branch (D-04/D-08, TAB file)
│                                        # + Universe injection (Pitfall 1)
└── portfolio_handler/
    ├── cash/cash_manager.py             # + position-keyed locked_margin container (D-10, 4-space file)
    │                                    # + available_balance subtracts locked_margin
    ├── position/position.py             # + leverage attribute / aggregate notional (D-06/D-11, TAB file)
    ├── portfolio.py                     # process_transaction: enable_margin lock-and-settle branch (TAB file)
    └── portfolio_handler.py             # maintenance_margin/margin_ratio impl; update_config (D-15, 4-space file)
```

### Pattern 1: The byte-exact `enable_margin` gate (the central pattern)
**What:** Every new behavior branches on `enable_margin`; the `False` arm is the EXISTING expression, untouched.
**When to use:** At both byte-exact sites (admission reservation, settlement) and in the leverage cap.
**Example (admission reservation, `admission_manager.py:227`, TAB-indented file):**
```python
# Source: live code admission_manager.py:227-228 (verified). Margin branch is the
# Phase-2 addition; spot branch is byte-identical to today.
if self.portfolio_handler is not None and primary.action is Side.BUY:
    notional = primary.price * primary.quantity
    commission = self._estimate_commission(primary)
    if enable_margin:                      # D-09 gate
        cost = notional / effective_leverage + commission   # D-08 initial_margin
    else:
        cost = notional + commission        # UNCHANGED — byte-exact, == notional/1
    self.portfolio_handler.reserve(primary.portfolio_id, primary.id, cost)
```
**Byte-exact proof obligation:** with `enable_margin=False`, `cost == primary.price * primary.quantity + commission` — operand-for-operand identical to today. The planner MUST assert the spot arm does NOT enter the `notional / L` division (a `/1` could still produce a different Decimal exponent — verified concern, see Pitfall 4).

### Pattern 2: Lock-and-settle cash lifecycle (D-09/D-10/D-11)
**What:** In margin mode, opening a position does NOT debit notional; it locks `initial_margin` for the position's life. Closing settles realized PnL and releases the locked margin.
**When to use:** `Portfolio.process_transaction` (the settlement orchestration at `portfolio.py:270`), gated on `enable_margin`.
**Plumbing (the lifecycle the planner must build):**
- **Open fill (new position):** lock `aggregate_notional / L` into `CashManager`'s position-keyed `locked_margin[position_id]`. Do NOT apply the notional debit (`net_cash_delta`). Commission IS still debited (fees ride traded value, D-08).
- **Scale-in fill:** recompute `locked_margin[position_id] = new_aggregate_notional / L` at the position's one leverage (D-06/D-11). The signal's differing leverage is clamped to the position's leverage (documented).
- **Partial close (fraction `p`):** release `p × locked_margin`, settle `p × realized_PnL` to cash.
- **Full close:** release the whole `locked_margin[position_id]`, settle realized PnL, remove the key.
**Critical:** `locked_margin` is keyed by **position**, not order — it survives the order's terminal reservation release (which is order-keyed and happens in `ReconcileManager._release_reservation`). These are two distinct containers (D-10).
**Spot arm:** untouched — `process_transaction` still calls `apply_fill_cash_flow(net_delta, ...)` exactly as today.

### Pattern 3: New sizing-policy kind (D-07, mirror `RiskPercent`)
**What:** Add `LeveredFraction` (or `KellyFraction`) as a frozen dataclass in `core/sizing.py` and a `case` arm in `sizing_resolver.py`. It reads `total_equity()` like `RiskPercent` reads equity.
**Example (the dataclass, mirroring `RiskPercent` at `core/sizing.py:128`):**
```python
# Source: pattern mirrored from RiskPercent (core/sizing.py:128, verified).
@dataclass(frozen=True, slots=True)
class LeveredFraction:
    """Size entry as a fraction of total equity (D-07): notional = f × equity.
    Permits f > 1 ONLY when enable_margin (the resolver/admission enforces the
    gate — the policy itself does not know enable_margin). Oracle-dark: the
    golden FractionOfCash run never constructs this."""
    fraction: Decimal           # f — NOT bounded to (0,1]; the f>1 gate is enable_margin-conditional
    step_size: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive("LeveredFraction", "fraction", self.fraction)   # f > 0, not (0,1]
        _validate_step_size("LeveredFraction", self.step_size)
```
**Resolver arm (`sizing_resolver.py`, mirror the `RiskPercent` arm at line 113):**
```python
# Source: mirror of resolve_entry RiskPercent arm (sizing_resolver.py:113, verified).
case LeveredFraction():
    equity = self._read_model.total_equity(portfolio_id)   # D-12 mark-to-market
    qty = (policy.fraction * equity) / to_money(price)     # notional = f × equity
```
**Where the `f>1 only when enable_margin` guard lives (discretion, recommended):** in `AdmissionManager` (it knows `enable_margin`), NOT in the policy or resolver (which are config-agnostic). A `LeveredFraction(fraction>1)` reaching admission with `enable_margin=False` → audited REJECTED (consistent with D-01's REJECT precedent). The resolver/`SizingResolver` stays pure and config-free (preserves its `PortfolioReadModel`-only discipline).
**The `assert_never` consequence (D-02 mypy gate):** adding a member to `SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent` makes `sizing_resolver.py`'s `case _: assert_never(policy)` fail under `mypy --strict` until the new `case` is added — this is the intended fail-loud growth guard, not a bug.

### Anti-Patterns to Avoid
- **A `/1` that changes the Decimal exponent on the spot path.** `Decimal("100") / Decimal("1")` → `Decimal("100")` (same), but division CAN normalize/extend the exponent in other cases. The spot arm must NOT route through the division at all (use an `if enable_margin` branch, not `notional / leverage` with leverage forced to 1). VERIFIED concern — see Pitfall 4.
- **Subtracting `locked_margin` from `available_balance` unconditionally.** In spot mode there is no locked margin (the container is empty), so `balance − reserved − 0 == balance − reserved` — byte-exact. But the planner must ensure the empty container is exactly `Decimal("0")` and the subtraction does not re-quantize. Prefer a guard or a provably-zero default.
- **Mutating `Position` with a stored maintenance-margin field.** D-13 forbids it — compute on demand in the read-model.
- **Reaching into `CashManager` internals from a new sub-manager.** D-10: one cash authority. Locked margin is a CashManager container.
- **Per-tranche FIFO margin.** D-11: pro-rata aggregate only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pending-order cash reservation | A new margin-reservation mechanism | `CashManager.reserve_cash` / `release_reservation` (order-keyed) — already idempotent, full-precision, audited | The over-margin reject (D-01) reuses this verbatim; building a parallel mechanism duplicates the WR-03 leak-prevention logic in `AdmissionManager`. |
| Over-margin REJECTED path | A new rejection branch | The existing `InsufficientFundsError` → `add_state_change(REJECTED, triggered_by=CASH_RESERVATION)` path (`admission_manager.py:233-248`) | D-01 explicitly reuses the over-cash precedent — empty cash ledger, no reservation, audited entity. |
| Equity for sizing/margin checks | A fresh cash+PnL aggregation | `PortfolioReadModel.total_equity()` (`portfolio_read_model.py:214`, impl `portfolio_handler.py:270`) | Already Decimal-native (CashManager.balance + position market value); a re-derivation risks a float narrowing or a different basis. |
| Symbol → Instrument resolution | A new instrument lookup | `Universe.instrument(symbol)` (`universe/universe.py:62`) | The Phase-1 facade is the single instrument source; building a parallel map fragments the source of truth (D-06/D-07). |
| Decimal entry / boundary rounding | `Decimal(float)` or ad-hoc quantize | `to_money(x)` / `quantize(value, instrument, kind)` (`core/money.py`) | Locked money policy — `Decimal(float)` imports the binary-repr artifact and breaks byte-exactness. |
| Config merge + validate + swap | A bespoke config update | `PortfolioHandler.update_config` (`portfolio_handler.py:454`) | D-15 — `max_leverage` rides the uniform deep_merge → model_validate → atomic-swap seam. |

**Key insight:** The phase is almost entirely *gating existing primitives behind `enable_margin`*, plus exactly one genuinely new container (`locked_margin`) and one new sizing arm. The temptation to build a "MarginManager" or a parallel reservation system is the main architectural risk — D-10 and the discretion notes explicitly steer against it.

## Runtime State Inventory

> Phase 2 is additive (new config field, new event field, new cash container, new sizing kind, new read-model accessors). It is NOT a rename/refactor/migration. No stored runtime state carries a string that changes meaning. Inventory below confirms nothing requires data migration.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — backtest uses in-memory storage (`PortfolioStateStorageFactory.create("backtest")`), reset per run. No persisted margin state to migrate. | None — verified: backtest path is in-memory only. |
| Live service config | None — Phase 2 is backtest-only; the live `PostgreSQLOrderStorage` is a `NotImplementedError` placeholder and out of scope. | None. |
| OS-registered state | None — no scheduler/daemon registrations involved. | None. |
| Secrets/env vars | None — no new secret or env var; `enable_margin`/`max_leverage` are config fields, not env vars. | None. |
| Build artifacts | None — no package rename; pure source edits to existing modules. | None. |

## Common Pitfalls

### Pitfall 1: The order domain cannot see `Instrument` today (BLOCKING structural gap)
**What goes wrong:** D-04's leverage cap needs `Instrument.max_leverage`, computed in `AdmissionManager` (the order/risk layer). But `Universe` is currently injected ONLY into `SimulatedExchange` (`execution_handler/exchanges/simulated.py:131`, `set_universe`). `AdmissionManager.__init__` (`admission_manager.py:60`) takes `order_storage, logger, order_validator, sizing_resolver, portfolio_handler, commission_estimator, brackets, bracket_manager` — no instrument seam.
**Why it happens:** Phase 1 only needed `Instrument` in the exchange (for `min_order_size`). The order domain reads portfolio state through `PortfolioReadModel` and bar windows through `BacktestBarFeed` — neither exposes per-symbol instrument metadata.
**How to avoid:** Inject `Universe` (or a narrow instrument read-model) into `AdmissionManager` (and thread it through `OrderManager`'s constructor wiring at the compose root). Keep it `Optional[Universe] = None` so existing no-universe constructions (and the spot path) are byte-exact — when `None` or `enable_margin=False`, the cap degrades to leverage 1 with no instrument read. **The planner must add a wiring task at the compose root (`trading_system/compose.py`).**
**Warning signs:** A plan that computes `min(signal.leverage, Instrument.max_leverage, ...)` in `AdmissionManager` without first establishing how `Instrument` reaches that method.

### Pitfall 2: `locked_margin` is position-keyed, the order reservation is order-keyed — they are NOT the same lifecycle
**What goes wrong:** Treating the locked margin as just a longer-lived order reservation. The order reservation (`reserve`/`release`, keyed by `order_id`) is released on the order's TERMINAL fill (`ReconcileManager._release_reservation`, `reconcile_manager.py:321`). The locked margin (keyed by `position_id`, D-10) is locked on the opening fill's SETTLEMENT and survives until the position CLOSES — which may be many orders later.
**Why it happens:** Both look like "held cash", but one tracks a pending order's pre-trade hold and the other tracks an open position's lifetime collateral.
**How to avoid:** Build `locked_margin` as a distinct container in `CashManager` driven by `Portfolio.process_transaction` (the settlement path), NOT by the order reservation path. On an opening fill: release the order reservation (existing path, order-keyed) AND lock the margin (new path, position-keyed). `available = balance − order_reservations − locked_margin` (D-10).
**Warning signs:** A plan that releases the order reservation and expects the margin to "stay reserved" — it won't; the order reservation is fully popped on terminal fill.

### Pitfall 3: Settlement debits the FULL notional today via `net_cash_delta` — margin mode must NOT
**What goes wrong:** Leaving `Portfolio.process_transaction` calling `apply_fill_cash_flow(net_delta=...)` in margin mode debits the full notional, double-counting against the locked margin.
**Why it happens:** `Transaction.net_cash_delta` (`transaction.py:85`) returns `-(price*quantity + commission)` for a BUY — the spot debit-notional flow. It is the single settlement primitive (`portfolio.py:313`).
**How to avoid:** Branch `process_transaction` on `enable_margin`. Spot: unchanged (debit `net_delta`). Margin: debit ONLY commission on open (D-08), lock margin; settle realized PnL on close. The `assert_funds_invariant` guard (`portfolio.py:305`, `cash_manager.py:342`) checks `net_delta < 0` against balance — in margin mode the open-fill "debit" is only commission, so the invariant still holds but must be fed the margin-adjusted delta.
**Warning signs:** Equity that drops by the full notional when a levered position opens.

### Pitfall 4: A `/leverage` with leverage==1 can shift a Decimal exponent — the spot path must not divide at all
**What goes wrong:** Implementing the reservation as `notional / effective_leverage` with `effective_leverage` forced to `Decimal("1")` on the spot path. While `Decimal("9500.00") / Decimal("1") == Decimal("9500.00")`, Decimal division follows context precision and CAN produce a differently-normalized result than the bare `price * quantity` expression — and the golden master is byte-exact to the repr.
**Why it happens:** It looks equivalent ("dividing by 1 is a no-op") but Decimal division is context-sensitive (28-digit precision, exponent normalization), unlike multiplication of two clean operands.
**How to avoid:** Use a real `if enable_margin:` branch (Pattern 1). The spot arm computes `notional + commission` with NO division — operand-for-operand identical to `admission_manager.py:228` today. The margin arm does the division. NEVER route the spot path through `notional / 1`.
**Warning signs:** The integration oracle drifts by sub-cent amounts (a quantize/exponent artifact) even though "the math is the same".

### Pitfall 5: `mypy --strict` will fail loudly when `SizingPolicy` grows (this is correct)
**What goes wrong:** Adding `LeveredFraction` to the `SizingPolicy` union without adding the `case` arm to `sizing_resolver.py` breaks `mypy --strict` at the `assert_never(policy)` (`sizing_resolver.py:124`).
**Why it happens:** D-02's growth rule is enforced structurally — `assert_never` makes the resolver exhaustive.
**How to avoid:** This is the intended behavior. The plan must update the union AND the resolver arm in the same change. Tests run under `filterwarnings=["error"]` + `--strict-markers` — any unexpected warning also fails.
**Warning signs:** `mypy itrader` reporting an unhandled `LeveredFraction` in `assert_never` — that means the `case` arm is missing, not that mypy is wrong.

### Pitfall 6: `available_balance` is the single buying-power figure read everywhere — changing it ripples
**What goes wrong:** `CashManager.available_balance` (`cash_manager.py:107`) = `balance − reserved`. It is read by `reserve_cash`'s own sufficiency check (`:391`), `withdraw`, `process_transaction_cash_flow`, and surfaced as `available_cash` to the order domain (D-14 single trading-decision figure). Subtracting `locked_margin` changes ALL of these at once.
**Why it happens:** D-14 deliberately routes every cash decision through one figure so they can never disagree.
**How to avoid:** That single-figure design is exactly what makes the change safe — subtract `locked_margin` once in `available_balance` and every consumer is consistent. In spot mode `locked_margin == 0` so `available_balance` is byte-exact. The planner must verify the empty-container default is `Decimal("0")` (Pitfall 4's exponent concern applies to the subtraction too — `x - Decimal("0")` preserves `x`, which is safe, but confirm the storage seam returns a clean zero).
**Warning signs:** Any spot-path test where `available_balance` differs from `balance − reserved`.

## Code Examples

### Capping leverage (D-04/D-05, in `AdmissionManager`)
```python
# Source: D-04/D-05 decision + Universe.instrument (universe.py:62, verified).
# Lives in AdmissionManager (the order/risk layer). enable_margin forces 1 (byte-exact).
def _effective_leverage(self, signal_event) -> Decimal:
    if not self._enable_margin:                 # D-04: forced to 1 when margin off
        return Decimal("1")                     # spot byte-exact — no instrument read
    instr_cap = (self._universe.instrument(signal_event.ticker).max_leverage
                 if self._universe is not None else Decimal("1"))
    pf_cap = self._portfolio_max_leverage       # from TradingRules.max_leverage (D-14)
    requested = signal_event.leverage           # D-03 scalar, default Decimal("1")
    capped = min(requested, instr_cap, pf_cap)
    if requested > capped:                      # D-05: clamp + warn, NOT reject
        self.logger.warning("leverage clamped to cap",
                            requested=str(requested), capped=str(capped),
                            ticker=signal_event.ticker)
    return capped
```

### Maintenance margin / margin_ratio read-model (D-13, in `PortfolioReadModel` + impl)
```python
# Source: D-13 formula + total_equity (portfolio_read_model.py:214, verified).
# Protocol member (core/portfolio_read_model.py, 4-space file):
def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
    """maintenance_margin = Σ (instr.maintenance_margin_rate × |size| × current_price)
    over open positions — computed on demand (D-13), never a stored Position field."""
    ...

def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
    """total_equity() / maintenance_margin (D-13); the surface a UI computes
    margin-call warnings from (deferred N+4). Reads honestly even when breached (D-16)."""
    ...

# Impl in portfolio_handler.py (tabs in handler dir — VERIFY this file's indentation,
# portfolio_handler.py uses 4-space per the read above lines 234-285): iterate open
# positions, resolve each ticker's Instrument via the injected Universe, accumulate Decimal.
```

### SignalEvent leverage field (D-03, `events/signal.py`, 4-space file)
```python
# Source: D-03 + SignalEvent (events/signal.py:75-95, verified). kw_only=True so a
# defaulted field is legal among required ones.
leverage: Decimal = Decimal("1")   # D-03: default 1 → byte-exact; SMA_MACD never sets it
```
The mirror field on `SignalIntent` (`core/sizing.py:211`) lets the strategy declare it; the handler fans it onto the `SignalEvent` (same pattern as `sizing_policy`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Cash-only model: notional fully debited on open | Lock-and-settle: lock `notional/L`, settle PnL on close | This phase (margin mode only) | Makes leverage and Phase-3 shorts expressible; spot path unchanged. |
| Leverage inexpressible (implicit 1) | `leverage: Decimal` on the signal, capped by venue + account | This phase | `notional = f × equity` with `notional/L` margin becomes structurally possible (levered Kelly). |
| Two sizing arms reading equity (`RiskPercent`) | Adds `LeveredFraction` reading `total_equity()` | This phase | Kelly `f>1` expressible only under `enable_margin`. |

**Deprecated/outdated:** Nothing deprecated. Phase 2 is purely additive; the `Instrument.max_leverage`/`maintenance_margin_rate` fields landed inert in Phase 1 and are simply activated.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `portfolio_handler.py` and `cash_manager.py` use 4-space indentation (read confirms 4-space in both); `admission_manager.py`, `position.py`, `portfolio.py` use tabs (read confirms tabs). The planner must MATCH each file. | Code-Change Map / Code Examples | A mixed-indentation diff breaks a tab file (CLAUDE.md hazard). LOW risk — verified by reads, but re-confirm per file at edit time. |
| A2 | Injecting `Universe` (vs a new narrow instrument read-model Protocol) into `AdmissionManager` is the cleanest seam. CONTEXT leaves the exact instrument-access seam to discretion. | Pitfall 1 | If the team prefers a narrow Protocol over the concrete `Universe`, the wiring task changes shape (still required). MEDIUM — a design choice, not a correctness risk. |
| A3 | The `f>1 only when enable_margin` guard belongs in `AdmissionManager`, not the resolver/policy. Recommended for resolver purity; CONTEXT (discretion) does not pin the location. | Pattern 3 | If placed in the resolver, `SizingResolver` would need `enable_margin` injected, breaking its config-free `PortfolioReadModel`-only discipline. MEDIUM — confirm during planning. |
| A4 | backtesting.py models leverage as `margin = 1/leverage` (a single initial+maintenance ratio) with an `equity ≤ 0` liquidation; backtrader uses a per-instrument margin in `comminfo`. Informational for the P4/XVAL-01 freeze only — NOT a Phase-2 implementation input. | Cross-Validation Signal | Phase 2 freezes no oracle; wrong detail here has no Phase-2 impact. LOW. |
| A5 | The parked leveraged-long scenario's BTCUSD `max_leverage`/`maintenance_margin_rate` values are discretion (realistic crypto defaults, e.g. `max_leverage` ~10–125, `maintenance_margin_rate` ~0.004–0.05). Oracle-dark. | Validation Architecture | Values affect only the parked (not-frozen) scenario. LOW until P4. |

## Open Questions

1. **Exact instrument-access seam into the order domain (Pitfall 1).**
   - What we know: `Universe` exists and resolves `symbol → Instrument`; it is injected into `SimulatedExchange` only.
   - What's unclear: inject the concrete `Universe` into `AdmissionManager`/`OrderManager`, or define a narrow `InstrumentReadModel` Protocol (mirroring `PortfolioReadModel`'s discipline)?
   - Recommendation: inject `Optional[Universe]` for v1 (smallest seam; the order domain already injects concrete read-models like `BacktestBarFeed`). Revisit a Protocol if the live path needs a different instrument source. Planner must add the compose-root wiring task either way.

2. **Where the locked-margin lifecycle is driven from in the settlement sequence.**
   - What we know: `Portfolio.process_transaction` (`portfolio.py:270`) orchestrates validate → funds-invariant → position-mutate → cash-apply → record; `PositionManager` decides open/update/close (`_should_close_position`).
   - What's unclear: whether the lock/release calls hang off `process_transaction` directly (it sees the position transition via the returned `Position`) or off `PositionManager`'s open/close transitions.
   - Recommendation: drive lock/release from `process_transaction` (it already holds both the `Position` result and the `CashManager`); keep `PositionManager` cash-agnostic (it has no cash access today — preserve that).

3. **`assert_funds_invariant` semantics in margin mode.**
   - What we know: it guards `net_delta < 0` against `balance` (`portfolio.py:305`).
   - What's unclear: in margin mode the open-fill cash debit is only commission, not notional — the invariant input must be the margin-adjusted delta.
   - Recommendation: feed the invariant the actual margin-mode cash delta (commission on open); document that the locked-margin sufficiency was enforced pre-trade by the admission reservation gate (the same precedent as today's `Pitfall 2` note in `cash_manager.py:342`).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All code | ✓ | 3.13.1 | — |
| pytest | Component/integration tests | ✓ | 9.0.3 | — |
| Poetry | Run commands | ✓ | (in-project `.venv`) | — |
| mypy --strict | DoD gate | ✓ | ^2.1.0 (per pyproject) | — |
| backtesting.py | Phase-4 cross-val (NOT this phase) | ✓ | 0.6.5 | — |
| backtrader | Phase-4 cross-val (NOT this phase) | ✓ | 1.9.78.123 | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None. All work is on the installed stack.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `filterwarnings=["error", ...]`, `--strict-markers`, `--strict-config`; markers: `unit`, `integration`, `slow`, `e2e` only |
| Quick run command | `poetry run pytest tests/unit/portfolio tests/unit/order -x` |
| Full suite command | `make test` (full suite) |
| Type gate | `poetry run mypy itrader` (strict, files=["itrader"]) |
| Byte-exact oracle | `poetry run pytest tests/integration` → MUST stay **134 trades / final_equity 46189.87730727451** |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MARGIN-01 | Opening reserves `initial_margin = notional/L` (not notional) when margin on | unit | `poetry run pytest tests/unit/portfolio/test_cash_reservations.py -k margin -x` | ❌ Wave 0 (extend existing file) |
| MARGIN-01 | Lock-and-settle: lock on open, settle PnL + release on close | unit | `poetry run pytest tests/unit/portfolio/test_cash_manager.py -k locked_margin -x` | ❌ Wave 0 |
| MARGIN-01 | Scale-in adds pro-rata margin at the position's one leverage (D-11) | unit | `poetry run pytest tests/unit/portfolio/test_position_manager.py -k scale_in_margin -x` | ❌ Wave 0 |
| MARGIN-01 | Partial close releases `p × locked_margin`, settles `p × PnL` (D-11) | unit | `poetry run pytest tests/unit/portfolio/test_position_manager.py -k partial_close_margin -x` | ❌ Wave 0 |
| MARGIN-02 | Order exceeding free margin → audited REJECTED (D-01) | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -k over_margin -x` | ❌ Wave 0 (extend) |
| MARGIN-03 | `maintenance_margin` computed = `mmr × |size| × price` (D-13) | unit | `poetry run pytest tests/unit/portfolio/test_portfolio_handler.py -k maintenance_margin -x` | ❌ Wave 0 |
| MARGIN-03 | `margin_ratio` = equity / maintenance; reads honestly when breached (D-16) | unit | `poetry run pytest tests/unit/portfolio/test_portfolio_handler.py -k margin_ratio -x` | ❌ Wave 0 |
| LEV-01 | `effective = min(signal, instr.max_lev, pf.max_lev)`; clamp+warn over cap (D-04/D-05) | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -k leverage_cap -x` | ❌ Wave 0 |
| LEV-01 | `enable_margin=False` forces leverage to 1 (byte-exact) | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -k leverage_forced_one -x` | ❌ Wave 0 |
| LEV-01 | `max_leverage` rides `update_config` (D-15) | unit | `poetry run pytest tests/unit/portfolio/test_update_config.py -k max_leverage -x` | ❌ Wave 0 (extend) |
| LEV-02 | `LeveredFraction` resolves `notional = f × equity`; f>1 only when enable_margin | unit | `poetry run pytest tests/unit/order/test_sizing_resolver.py -k levered_fraction -x` | ❌ Wave 0 (extend) |
| LEV-02 | `f>1` with `enable_margin=False` → audited REJECTED | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -k levered_fraction_gate -x` | ❌ Wave 0 |
| BYTE-EXACT | SMA_MACD spot run unchanged: 134 trades / 46189.87730727451 | integration | `poetry run pytest tests/integration` | ✅ (existing oracle test) |
| DETERMINISM | Double-run byte-identical (margin mode) | integration | `poetry run pytest tests/integration -k determinism` (or run twice + diff) | ❌ Wave 0 (parked scenario) |
| PARKED e2e | Leveraged-long scenario, hand-verified, NOT frozen until P4/XVAL-01 (D-17) | e2e | `poetry run pytest tests/e2e -m e2e -k levered_long` | ❌ Wave 0 (parked; assertions are hand-computed numbers, not a frozen golden) |
| TYPE | mypy --strict clean incl. new `assert_never` arm | static | `poetry run mypy itrader` | ✅ (gate exists) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/<touched-domain> -x` + `poetry run mypy itrader` on touched files.
- **Per wave merge:** `make test-unit` + `poetry run pytest tests/integration` (oracle MUST hold byte-exact) + `poetry run mypy itrader`.
- **Phase gate:** Full `make test` green + `mypy itrader` clean + integration oracle byte-exact (134 / 46189.87730727451) + the parked leveraged-long e2e passing its hand-computed assertions (frozen-as-golden DEFERRED to P4) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/portfolio/test_cash_manager.py` — extend: position-keyed `locked_margin` lock/release/settle, `available_balance` subtracts locked margin, spot-mode locked_margin == 0 (byte-exact).
- [ ] `tests/unit/portfolio/test_cash_reservations.py` — extend: margin-mode reservation = `notional/L + commission`; spot reservation unchanged.
- [ ] `tests/unit/portfolio/test_position_manager.py` — extend: one-leverage-per-position (D-06), scale-in/partial-close pro-rata proportioning (D-11).
- [ ] `tests/unit/portfolio/test_portfolio_handler.py` — extend: `maintenance_margin` / `margin_ratio` compute-on-demand; honest-when-breached (D-16).
- [ ] `tests/unit/order/test_admission_rules.py` — extend: leverage cap+clamp+warn, force-to-1, over-margin reject, levered-fraction f>1 gate.
- [ ] `tests/unit/order/test_sizing_resolver.py` — extend: `LeveredFraction` arm; `assert_never` exhaustiveness still holds.
- [ ] `tests/unit/order/test_update_config.py` / `tests/unit/portfolio/test_update_config.py` — extend: `max_leverage` merge/validate/swap (D-15).
- [ ] `tests/e2e/` — new PARKED leveraged-long scenario directory (hand-computed assertions; NOT frozen as golden until P4/XVAL-01, D-17).
- [ ] Framework install: none — pytest/mypy already present.

## Security Domain

> No application-layer security surface in this phase (no auth, sessions, access control, network input). Phase 2 is internal backtest accounting. `security_enforcement` is not configured in config.json; the only relevant control is **input/value validation**, which the existing patterns already enforce.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Engine is owner-agnostic; `user_id` is app-layer (design note). |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | `SizingPolicyViolation` fail-loud (`core/sizing.py`); Pydantic `extra="forbid"` on config; `to_money` string-path Decimal entry; new `LeveredFraction.__post_init__` must validate `f > 0`. |
| V6 Cryptography | no | No crypto in this phase (UUIDv7 ids are existing, not phase work). |

### Known Threat Patterns for the iTrader margin core
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent over-leverage (order exceeds margin, fills anyway) | Tampering / Repudiation | D-01 audited REJECTED via the existing cash-reservation gate — no silent fall-through. |
| Float-repr artifact corrupting money | Tampering | Decimal end-to-end; `to_money` string path; NEVER `Decimal(float)`. |
| Unhandled new sizing kind silently mis-sizing | Tampering | `assert_never(policy)` exhaustiveness under `mypy --strict` (fail-loud, D-02). |
| Stale/wrong equity basis in margin check | Tampering | Single `total_equity()` figure (D-12); single `available_cash`/`available_balance` buying-power figure (D-14). |

## Sources

### Primary (HIGH confidence — codebase reads, this session)
- `itrader/order_handler/admission/admission_manager.py` (lines 1-647) — the cash-reservation gate (227-248), the audited REJECTED path, the sizing-resolution call.
- `itrader/portfolio_handler/cash/cash_manager.py` (1-540) — `available_balance` (107), `reserve_cash`/`release_reservation`, `apply_fill_cash_flow`, `assert_funds_invariant`.
- `itrader/order_handler/sizing_resolver.py` (1-172) — the `resolve_entry` match dispatch, the `RiskPercent` arm (113), `assert_never` (124).
- `itrader/core/sizing.py` (1-254) — `SizingPolicy` union (154), `RiskPercent` (128), `_require_*` guards, `SignalIntent`.
- `itrader/core/portfolio_read_model.py` (1-234) — `PortfolioReadModel` Protocol, `total_equity()` (214), `available_cash`, `reserve`/`release`.
- `itrader/portfolio_handler/portfolio_handler.py` (220-519) — read-model impl (234-285), `on_fill` (288), `update_config` (454).
- `itrader/portfolio_handler/portfolio.py` (1-475) — `process_transaction` (270), `transact_shares` (398).
- `itrader/portfolio_handler/position/position.py` (1-278) — `Position` accounting, `open_position`/`update_position`/`close_position`.
- `itrader/portfolio_handler/position/position_manager.py` (95-194) — `process_position_update`, `_should_close_position`.
- `itrader/portfolio_handler/transaction/transaction.py` (31-107) — `net_cash_delta` (85), `cost`.
- `itrader/core/instrument.py` (1-84) — `max_leverage`, `maintenance_margin_rate` (inert from Phase 1).
- `itrader/config/portfolio.py` (66-79) — `TradingRules` (`enable_margin`, `allow_short_selling`).
- `itrader/events_handler/events/signal.py` (19-102) — `SignalEvent` field layout.
- `itrader/universe/universe.py` (1-81) — `Universe.instrument(symbol)`; wiring check (injected only into `SimulatedExchange`).
- `.planning/phases/02-margin-accounting-leverage/02-CONTEXT.md` — D-01..D-17, code-to-change map.
- `.planning/notes/margin-leverage-shorts-999.4.md` — §4 spot-vs-perp, §5 liquidation location, §6 Phase A components.
- `.planning/STATE.md` — Milestone Gate, oracle 134 / 46189.87730727451, P4/XVAL-01 re-baseline.
- `.planning/config.json` — nyquist_validation true, commit_docs true.

### Secondary (MEDIUM confidence — web, informational for P4)
- [backtesting.py source/docs](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html) — `margin = 1/leverage`, single initial+maintenance ratio, `hedging` FIFO close, equity/margin_available tracking. Informational only; Phase 2 freezes no oracle.

## Metadata

**Confidence breakdown:**
- Byte-exact safety map: HIGH — both byte-exact sites identified and read directly (`admission_manager.py:228`, `Transaction.net_cash_delta`); the `enable_margin` branch points are precise.
- Lock-and-settle lifecycle: HIGH (design) — D-09/D-10/D-11 plumbing maps cleanly onto `process_transaction` + `CashManager`; the position-vs-order keying distinction is verified from the reconcile path.
- Sizing resolver arm: HIGH — `RiskPercent` template + `assert_never` growth gate read directly.
- Maintenance-margin read-model: HIGH — formula and `total_equity()` reuse verified.
- Instrument-access gap (Pitfall 1): HIGH — confirmed `Universe` is injected only into `SimulatedExchange`; the order domain has no instrument seam today.
- Cross-validation signal: MEDIUM — web-sourced, informational, P4-only.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable internal codebase; re-verify if `admission_manager`/`cash_manager`/`sizing_resolver` change before planning)

## RESEARCH COMPLETE

**Phase:** 2 - Margin Accounting & Leverage
**Confidence:** HIGH

### Key Findings
- The spot byte-exact path collapses to exactly TWO expressions: `admission_manager.py:228` (reservation = `price*qty + commission`) and `Transaction.net_cash_delta` (settlement debit). Margin mode branches both behind `enable_margin`; with margin OFF the spot arm must NOT route through `/leverage` (Decimal exponent risk — Pitfall 4).
- BLOCKING structural gap (Pitfall 1): the order domain (`AdmissionManager`) has no access to `Instrument`/`Universe` today — `Universe` is injected only into `SimulatedExchange`. D-04's leverage cap needs a new injection seam wired at the compose root.
- `locked_margin` (D-10) is position-keyed and lives the position's life; the existing order reservation is order-keyed and released on the terminal fill. They are two distinct containers/lifecycles — driving the margin lock from the order reservation path is the main correctness trap.
- The new `LeveredFraction` sizing kind mirrors `RiskPercent` exactly (reads `total_equity()`); adding it to the union forces the `assert_never` arm in `sizing_resolver.py` (intended mypy-strict fail-loud growth gate). The `f>1 only when enable_margin` guard belongs in `AdmissionManager`, not the config-free resolver.
- Maintenance margin / margin_ratio are compute-on-demand read-model accessors (D-13), reading `Instrument.maintenance_margin_rate` and mark-to-market `total_equity()` — no stored `Position` field.

### File Created
`.planning/phases/02-margin-accounting-leverage/02-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Byte-exact safety map | HIGH | Both sites read directly; branch points precise |
| Lock-and-settle lifecycle | HIGH | Maps cleanly onto verified settlement path; position/order keying distinction confirmed |
| Sizing resolver arm | HIGH | `RiskPercent` template + `assert_never` gate read directly |
| Maintenance-margin read-model | HIGH | Formula + `total_equity()` reuse verified |
| Cross-validation signal | MEDIUM | Web-sourced, P4-only, informational |

### Open Questions
1. Instrument-access seam into the order domain — concrete `Universe` vs narrow Protocol (recommend `Optional[Universe]` for v1).
2. Whether the locked-margin lifecycle hangs off `process_transaction` or `PositionManager` transitions (recommend `process_transaction` — keep `PositionManager` cash-agnostic).
3. `assert_funds_invariant` input in margin mode (feed it the margin-adjusted commission-only delta on open).

### Ready for Planning
Research complete. The planner can create PLAN.md files; the BLOCKING items are the compose-root Universe-wiring task (Pitfall 1) and the two byte-exact `enable_margin` branch sites (Pattern 1 + Pitfall 4).
