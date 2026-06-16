# Phase 4: Liquidation & Cross-Validation Re-baseline - Research

**Researched:** 2026-06-16
**Domain:** Isolated-margin liquidation accounting + golden-master cross-validation (Python 3.13, event-driven backtest engine)
**Confidence:** HIGH (all claims grounded in the live codebase; the liquidation formula was hand-verified in a Decimal harness this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01 … D-12 — DO NOT relitigate)
- **D-01** — per-position liquidation PRICE, breach detected on **bar close**. Compute each position's isolated liquidation price; flag when the bar close crosses it. NOT the portfolio-aggregate `margin_ratio` (that pools positions → cross-margin).
- **D-02** — multiple breaches each liquidate **independently** in a fixed deterministic order (symbol then open-time — planner's discretion). One liquidation never changes another's trigger. Ordering affects only the cash-ledger *sequence*, must be fixed for the byte-identical double-run.
- **D-03** — forced close settles **AT the computed liquidation price**; the floor (loss = allocated isolated margin) is intended to be automatic. **(SEE Pitfall 1 + Open Question 1 — this is true only at the bankruptcy price, not at the maintenance liq price; a cap/penalty is still required. The planner MUST reconcile D-03 with D-07.)**
- **D-04** — the **portfolio-side** liquidation engine mints the `FillEvent` **directly on the BAR route** (in `PortfolioHandler.update_portfolios_market_value`), tagged `OrderTriggerSource.LIQUIDATION`, penalty in the existing `commission` field, `FillEvent(EXECUTED)`. Does NOT round-trip through `ExecutionHandler` (wrong next-bar-open timing). Consumed by `portfolio.on_fill` (settle) + `order_handler.on_fill` (mirror EXECUTED→FILLED), no new `FillStatus`.
- **D-05** — penalty basis: **% of notional** = `liquidation_fee_rate × |size| × liq_price`.
- **D-06** — rate home: **`Instrument`-first + config fallback**. Add `liquidation_fee_rate` to `core/instrument.py` (default `Decimal("0")` = oracle-dark), resolved via the `Universe` read-model; fall back to a `config/portfolio.py::TradingRules` default. Default 0 = oracle-dark.
- **D-07** — penalty consumes the maintenance buffer; **total realized loss CAPPED at the allocated isolated margin** (never exceeds it). NOT charged-on-top-uncapped.
- **D-08** — liquidation oracle: **hand-computed closed-form is PRIMARY**; `backtesting.py`/`backtrader` fully cross-validate short & leveraged-long, give **directional corroboration** on liquidation. NOT expected to byte-match the isolated formula.
- **D-09** — `freqtrade` ruled out for Phase 4 (NOT installed — VERIFIED this session; circular — we copy its formula). XVAL-01 names only `backtesting.py` + `backtrader`.
- **D-10** — freeze set = **ALL parked P2/P3 scenarios + new P4 liquidation scenarios** as the single accounting-core golden under one owner-gated sign-off.
- **D-11** — SMA_MACD stays **byte-exact, untouched** (134 trades / `46189.87730727451`); `tests/integration/test_backtest_oracle.py` still asserts it. The byte-exact hold is part of the phase gate.
- **D-12** — owner sign-off reuses the established pattern: a **blocking human-verify checkpoint** + a **new accounting-core cross-validation evidence doc** (sibling to `tests/golden/CROSS-VALIDATION.md`) with a per-scenario reconciliation table + an **Owner Sign-Off** block. Freeze ONLY after sign-off.

### Claude's / Planner's Discretion
- D-02 deterministic tiebreak ordering (symbol / open-time / position-id); placement of the liquidation check vs the P3 carry accrual within the BAR route.
- The `OrderTriggerSource.LIQUIDATION` member value string + trade-log / metrics filtering wiring.
- The crafted-scenario shape/count and where they live (`tests/e2e/<scenario>/` dirs, mirroring the parked P2/P3 layout).
- BTCUSD-vs-synthetic `Instrument.liquidation_fee_rate` value + config fallback default.
- WR-04 fix shape (assert before release, or thread the released amount into `assert_lock_fits_buying_power`); whether IN-03 needs more than the existing per-instrument `maintenance_margin_rate`.
- New cross-validation doc filename/location + crossval-runner additions (following the v1.3 `_limit` precedent).
- Indentation: tabs in `portfolio_handler/`, `order_handler/`, `execution_handler/`; 4 spaces in `core/`, `config/`, `events_handler/events/` — match the file, never normalize.

### Deferred Ideas (OUT OF SCOPE)
- `freqtrade` as a 4th oracle (Phase B); mark-price liquidation trigger (Phase B); cross-margin / account-wide joint liquidation (beyond Phase B); tiered MMR brackets (future); single-order flips (deferred from P3); engine-native trailing stops (Phase 5, TRAIL-01/02/03); pair-trading flagship (Phase 6, PAIR-01); IN-01/IN-02/IN-04 P3 nits.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LIQ-01 | Bar-close maintenance-margin breach check; force-close the breaching position via a `FillEvent`, loss floored at allocated isolated margin. | Liquidation-price formula (corrected — see Architecture Pattern 1); the BAR-route hook (`update_portfolios_market_value`, handler line 432) co-located with P3 carry; `maintenance_margin` read-model (handler 307); the WB source = `CashManager` position-keyed locked-margin container. |
| LIQ-02 | Configurable liquidation penalty/fee so liquidation PnL is not optimistic. | `liquidation_fee_rate` on `Instrument` (default 0) + `TradingRules` fallback; penalty = `rate × |size| × liq_price` carried in `FillEvent.commission`; capped within margin envelope (Pattern 2). |
| LIQ-03 | Forced liquidation reuses `FillStatus.EXECUTED`, mints an admission-bypassing close order tagged `OrderTriggerSource.LIQUIDATION`, reconciling through the existing path (no new `FillStatus`). | `OrderTriggerSource` enum pattern (`core/enums/order.py` 174, mirror `ADMISSION_*`); `ReconcileManager.on_fill` EXECUTED→FILLED (reconcile_manager.py 242) — **requires the forced-close Order to exist in `order_storage` or the mirror silently no-ops (Pitfall 4)**. |
| XVAL-01 | Short / leveraged-long / liquidation cross-validated; new golden freezes only after owner sign-off. | `scripts/cross_validate.py` + `scripts/crossval/` runners (+ `_limit` precedent); `CROSS-VALIDATION.md` Owner Sign-Off template; the parked P2/P3 e2e scenarios + new P4 scenarios (D-10 freeze set). |
</phase_requirements>

## Summary

Phase 4 closes DEF-01-C by adding an isolated-margin liquidation engine that lives **in portfolio/cash accounting on the BAR route**, plus a one-time owner-gated golden re-baseline of the whole accounting core (margin P2 + shorts P3 + liquidation P4). The design is heavily locked (D-01…D-12); this research surfaces the code-level facts that make those decisions executable and flags two correctness traps the planner must resolve before writing tasks.

The seams are all present and shaped for this: `PortfolioHandler.update_portfolios_market_value` (line 432) already holds `self.global_queue` and `self._universe` and already runs a per-bar pass over open positions (the P3 carry accrual), so the liquidation breach check co-locates there cleanly. `maintenance_margin` (handler 307) gives the per-position MMR read. The allocated isolated margin (WB) is the `CashManager` position-keyed locked-margin container (`get_locked_margin_for`). `OrderTriggerSource` (order.py 174) is a closed-vocabulary enum that adds `LIQUIDATION` exactly like the existing `ADMISSION_*` members. `FillEvent.new_fill` (fill.py 81) mints the forced-close fill but **requires an `OrderEvent`** as input, and `ReconcileManager.on_fill` (reconcile_manager.py 210-214) **silently early-returns if the fill's `order_id` is not in `order_storage`** — so the liquidation engine must register a real forced-close `Order` in the mirror, not just synthesize a fill. WR-04 is a precise call-order defect in `portfolio.py` (release_margin runs before assert_lock_fits_buying_power, so the add-back reads 0).

**Two correctness findings the planner MUST act on:** (1) the CONTEXT D-01 formula string `Entry×(1−(WB/size)/L)/(1+MMR)` is **mathematically wrong as literally written** (it yields a negative price — `WB/size` already equals `Entry/L`, so `/L` double-counts leverage and the `(1+MMR)` sign is inverted for a long); the correct freqtrade-canonical isolated formula is long `(Entry − WB/size)/(1 − MMR)`, short `(Entry + WB/size)/(1 + MMR)`. (2) D-03's "loss == allocated margin by construction, no clamp" is **only exact at the bankruptcy price** (MMR=0); at the actual maintenance liq price the position retains a `/(1−MMR)` buffer, so the floor is NOT automatic — the penalty (D-07) consumes that buffer and an explicit cap is still required. Both are hand-verified below.

**Primary recommendation:** Implement the corrected isolated formula, settle the forced close at the maintenance liq price, deduct the D-05 penalty within the envelope, and **explicitly clamp total realized loss to WB** (the cap is real, not automatic). Register a real forced-close `Order` in `order_storage` so the mirror reconciles. Run the liquidation check at the handler level (queue + universe access) AFTER the per-portfolio mark/carry call, sorting breached positions deterministically. Reuse the white-box hand-computed e2e pattern from `tests/e2e/levered_long/` for the new liquidation scenarios; freeze the parked P2/P3 scenarios alongside them.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bar-close breach detection | Portfolio accounting (`PortfolioHandler`) | Universe read-model | Liquidation is an *equity* event, not an order fill (D-04, design §5); the handler holds the queue + universe + per-bar mark pass. |
| Isolated liq-price computation | `core` math (compute-on-demand) | `Position` fields + `CashManager` WB | Closed-form, hand-computable; reuses `maintenance_margin_rate` (Universe) + locked-margin (CashManager). NO stored state (P2 D-13 pattern). |
| Forced-close order minting | Order domain (`OrderManager`/storage) | Portfolio handler | The mirror reconcile (`ReconcileManager.on_fill`) requires a real `Order` in storage keyed by the fill's `order_id` — Pitfall 4. |
| `FillEvent(EXECUTED)` emission | Portfolio handler (BAR route) | Event queue | D-04 — handler mints + emits directly; bypasses `ExecutionHandler` (next-bar-open timing is wrong). |
| Penalty / cash settle | `CashManager` settle path | `Portfolio.process_transaction` | Penalty rides `FillEvent.commission`; loss + penalty settle through the existing `apply_fill_cash_flow` + lock release. |
| Cross-validation | `scripts/` (script-only path) | `backtesting.py` / `backtrader` | D-10: crossval imports reference engines; must NEVER be imported under `tests/` (keeps `filterwarnings=["error"]` intact). |

## Standard Stack

No new third-party packages. Phase 4 is pure first-party code against the existing stack. The two cross-validation oracles are already installed and pinned.

### Core (already present — versions verified against poetry.lock this session)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `backtesting` | 0.6.5 `[VERIFIED: poetry.lock + import]` | Gating cross-val oracle for short / leveraged-long + directional liquidation corroboration | `margin = 1/leverage`; `equity ≤ 0 → close-all` (the minimal liquidation model, D-08). |
| `backtrader` | 1.9.78.123 `[VERIFIED: poetry.lock]` | Gating cross-val oracle for short / leveraged-long | `comminfo` margin; **no isolated liquidation model** (D-08 — corroborates accounting, not liquidation). |
| `pandas` | 2.3.x `[CITED: CLAUDE.md]` | Bars / golden CSV diffing | Existing harness dependency. |
| `Decimal` (stdlib) | — | Liquidation formula, penalty, floored loss — Decimal end-to-end | Money policy (locked); `float()` only at serialization edge. |

**No installation step.** `freqtrade` is **absent** — `grep -ci freqtrade poetry.lock pyproject.toml` → `0` / `0` `[VERIFIED: grep]`. Do NOT add it (D-09).

## Package Legitimacy Audit

Phase 4 installs **no external packages**. Audit not applicable — all dependencies (`backtesting`, `backtrader`, `pandas`, stdlib `Decimal`) are already present, pinned in `poetry.lock`, and import-verified this session. slopcheck not run (no install action to gate).

## Architecture Patterns

### System Architecture Diagram — liquidation on the BAR route

```
BarEvent(s) ─▶ PortfolioHandler.update_portfolios_market_value  (handler.py:432)
                  │  (holds self.global_queue + self._universe)
                  │
                  ├─ for each active portfolio:
                  │     portfolio.update_market_value_of_portfolio(prices, bar_time, universe)
                  │        ├─ mark positions @ bar_time
                  │        └─ _accrue_short_carry(...)         ← P3 carry (erodes equity FIRST)
                  │
                  └─ LIQUIDATION CHECK  (NEW — runs at HANDLER level, post-mark/carry)
                        ├─ collect breached open positions (bar_close crosses liq_price)
                        ├─ sort deterministically (D-02: symbol, then open-time)
                        └─ for each breached position (independent — D-02):
                              ├─ compute liq_price (isolated formula, Pattern 1)
                              ├─ compute penalty = fee_rate × |size| × liq_price  (D-05)
                              ├─ register forced-close Order in order_storage   ← Pitfall 4
                              │     action = opposite side, qty = |size|,
                              │     OrderTriggerSource.LIQUIDATION (admission-bypass)
                              └─ global_queue.put( FillEvent(EXECUTED,
                                       price=liq_price, quantity=|size|,
                                       commission=penalty, time=bar_time) )
                                         │
        ┌────────────────────────────────┴───────────────────────────┐
        ▼                                                             ▼
  portfolio.on_fill(EXECUTED)                            order_handler.on_fill
   = settle: realize PnL + penalty, release lock,         = ReconcileManager.on_fill
     CAP total loss at WB (D-07, NOT automatic)             EXECUTED → FILLED (no new status)
```

**Key ordering insight (planner discretion D-02 placement):** run the liquidation check **after** the P3 carry accrual so the breach is evaluated against carry-eroded equity (carry is a real outflow that pushes a short toward liquidation — matches the design-note §7 "carry erodes equity as it accrues so the P4 liquidation trigger sees carry-eroded equity"). The carry hook lives *inside* `portfolio.update_market_value_of_portfolio` (per-portfolio); the liquidation check lives at the *handler* level (needs queue + universe). So the natural placement is: handler loops portfolios calling mark+carry, THEN handler loops portfolios again (or in the same loop, after the per-portfolio call returns) running the liquidation check.

### Pattern 1: Isolated liquidation price — CORRECTED formula (HAND-VERIFIED)

**The CONTEXT D-01 string is wrong as literally written.** `Entry×(1−(WB/size)/L)/(1+MMR)` produces a negative price (verified: Entry=100, L=5, MMR=0.01 → −297.03). Root cause: `WB = notional/L = Entry×size/L`, so `WB/size = Entry/L` already encodes one division by L; dividing by `L` again is a double-count, and `/(1+MMR)` has the wrong sign for a long.

**Correct freqtrade-canonical isolated linear formula** `[CITED: freqtrade isolated liquidation; HAND-VERIFIED this session]`:

```python
# WB = position's allocated isolated margin = aggregate_notional / leverage
#    = the CashManager position-keyed locked-margin (get_locked_margin_for)
# margin_per_unit = WB / |size|  (== Entry / L for a fresh single-fill open)

# LONG:
liq_price = (entry - WB/abs(size)) / (Decimal("1") - mmr)
# SHORT:
liq_price = (entry + WB/abs(size)) / (Decimal("1") + mmr)
```

Worked numbers (Entry=100, size=200, L=5 → WB=4000, MMR=0.01):
- **Long liq** = `(100 − 4000/200)/(1 − 0.01)` = `80/0.99` = **80.8080…**
- **Short liq** = `(100 + 20)/(1.01)` = **118.8118…**

### Pattern 2: The floor is NOT automatic at the maintenance liq price (D-03 vs D-07)

D-03 says settling at the liq price makes "realized loss == allocated isolated margin by construction — no clamp needed." **This is only exact at the BANKRUPTCY price (MMR=0):** long bankruptcy = `Entry×(1−1/L)` = 80.0 → loss `(80−100)×200` = **−4000 = WB exactly**.

At the actual **maintenance liq price** (80.808…), the position retains the `/(1−MMR)` maintenance buffer:
- realized loss = `(80.808 − 100)×200` = **−3838.38** (NOT −4000)
- the position still holds a `MMR×|size|×liq` = `0.01×200×80.808` = **161.62** buffer.

D-07 reconciles this: the **penalty consumes that buffer**, and total loss is **capped at WB**. Hand-verified with `fee_rate=0.005`:
- long: loss 3838.38 + penalty 80.81 = **3919.19 ≤ 4000** ✓ (within envelope, no clamp triggered)
- short: loss 3762.38 + penalty 118.81 = **3881.19 ≤ 4000** ✓

But with a larger penalty (or deeper MMR), `loss + penalty` can exceed WB → **the cap must be an explicit clamp** (`total_realized_loss = min(loss + penalty, WB)`), NOT a by-construction identity. The planner must implement the clamp and reconcile the D-03 "no clamp" wording with the D-07 cap.

**Example:** `tests/e2e/levered_long/test_levered_long_scenario.py` — the canonical white-box hand-computed e2e to mirror for new liquidation scenarios.

### Recommended placement of the new code

```
itrader/
├── core/
│   ├── instrument.py            # ADD liquidation_fee_rate: Decimal = Decimal("0")  (D-06; 4-space)
│   └── enums/order.py           # ADD OrderTriggerSource.LIQUIDATION  (line ~174; 4-space, tab? — file uses TABS, match it)
├── config/portfolio.py          # ADD liquidation_fee_rate to TradingRules (fallback; 4-space)
├── portfolio_handler/
│   ├── portfolio_handler.py     # ADD liquidation check in update_portfolios_market_value (~432; TABS)
│   ├── portfolio.py             # WR-04 call-order fix (~430/449); forced-close settle path (TABS)
│   └── cash/cash_manager.py     # WR-04 assert/release ordering; loss+penalty cap settle (4-space)
└── (forced-close Order minting — order domain or a portfolio-side helper, planner's call)
```

**INDENTATION TRAP (verified):** `core/enums/order.py` uses **TABS** (the `OrderTriggerSource` block is tab-indented). `core/instrument.py` and `config/portfolio.py` use **4 SPACES**. `portfolio_handler/*.py` uses **TABS** *except* `cash/cash_manager.py` which uses **4 SPACES**. `events_handler/events/fill.py` and `order.py` use **4 SPACES**. Match each file — a mixed diff breaks a tab file.

### Anti-Patterns to Avoid
- **Routing the forced close through `ExecutionHandler`/`SimulatedExchange`** — fills at next-bar-open (wrong; D-04 requires settle on the breach bar at liq price).
- **A "liquidate, re-mark, re-check" loop across positions** — that is cross-margin behavior (D-02 forbids it; each breach is independent).
- **Emitting the `FillEvent` with a fresh `order_id` that has no `Order` in storage** — `ReconcileManager.on_fill` silently early-returns (Pitfall 4); the mirror never reaches FILLED.
- **Treating the D-03 floor as automatic** — implement the explicit cap (Pattern 2).
- **Using the portfolio-aggregate `margin_ratio` as the trigger** — pools positions → cross-margin (D-01 forbids).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Forced-close fill construction | A bespoke FillEvent literal | `FillEvent.new_fill(status, order, price=, quantity=, commission=, time=)` (fill.py:81) | Construct-complete (D-12); mints fill_id, carries audit chain. **Needs an `OrderEvent`/order** as input. |
| Mirror reconcile EXECUTED→FILLED | New status / bespoke transition | The existing `ReconcileManager.on_fill` EXECUTED arm (reconcile_manager.py:242) | LIQ-03 — no new `FillStatus`. Register the order in storage so it isn't no-op'd (Pitfall 4). |
| Short/long PnL on the forced close | A liquidation-specific PnL branch | `Position.realised_pnl` / `unrealised_pnl` (position.py:175/201, already branch on `PositionSide.SHORT`) | The forced close is just a close fill through the existing settle path. |
| Per-position maintenance margin | A new MMR computation | `PortfolioHandler.maintenance_margin` (handler.py:307) reads `Instrument.maintenance_margin_rate` via Universe | P2 D-13 compute-on-demand; the liq formula reuses the same per-position read. |
| Allocated isolated margin (WB) | Re-deriving notional/L | `CashManager.get_locked_margin_for(position_id)` (the position-keyed locked-margin container) | WB IS the lock; reading it keeps the floor consistent with the reservation. |
| Golden diff / freeze mechanic | A new comparison harness | `tests/e2e/conftest.py::run_scenario` (`--freeze`, no-tolerance `assert_frame_equal`) | E2E harness already does build→run→assemble→diff; freeze one verified scenario at a time. |
| Cross-val runner | A new orchestrator | Extend `scripts/cross_validate.py` + `scripts/crossval/*_run.py` (mirror the `_limit` variants) | The v1.3 `cross_validate_limit.py` + `*_limit_run.py` are the precedent for scenario-specific runners. |

**Key insight:** Every seam the liquidation engine needs already exists and is the same path a normal close fill travels. The novelty is (a) the trigger/price math and (b) minting the fill on the BAR route instead of from the exchange — NOT a new reconciliation, settle, or PnL path.

## Runtime State Inventory

> Phase 4 is greenfield-feature code (no rename/migration). This section is included only to confirm no stored/registered state carries an old string.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys change; liquidation is computed on demand each bar (no new stored Position field, mirrors P2 D-13). | None |
| Live service config | None — backtest-only feature; no external service. | None |
| OS-registered state | None. | None |
| Secrets/env vars | None. | None |
| Build artifacts | None — no package rename. | None |

**Default-off discipline (the only "state" concern):** `liquidation_fee_rate` defaults to `Decimal("0")`, margin/shorts default-off → SMA_MACD is oracle-dark and byte-exact (D-11). The new `OrderTriggerSource.LIQUIDATION` member and the new `Instrument`/`TradingRules` field must NOT change any serialized golden output for the spot oracle. **Verified by X:** the spot oracle path (`scripts/run_backtest.py` → `test_backtest_oracle.py`) never opens a margin/short position, so the liquidation check finds zero breaches and emits nothing.

## Common Pitfalls

### Pitfall 1: The CONTEXT D-01 liquidation formula is mathematically wrong as written
**What goes wrong:** Implementing `Entry×(1−(WB/size)/L)/(1+MMR)` verbatim yields a negative liquidation price (−297.03 for the worked case) — the position would "liquidate" at an impossible price, or never.
**Why it happens:** `WB = Entry×size/L`, so `WB/size = Entry/L` already divides by leverage once; the literal `/L` double-counts it, and `(1+MMR)` is the short-side denominator misapplied to a long.
**How to avoid:** Use long `(Entry − WB/|size|)/(1 − MMR)`, short `(Entry + WB/|size|)/(1 + MMR)`. Hand-verify against the worked numbers (long 80.808, short 118.811) before freezing any golden.
**Warning signs:** A liq price below 0, above 2×entry for a long, or a "loss" that doesn't approach WB.

### Pitfall 2: D-03 "loss == margin by construction, no clamp" is false at the maintenance liq price
**What goes wrong:** Trusting the floor to be automatic leaves a residual maintenance buffer unaccounted (161.62 in the worked long case), so the realized loss is −3838.38, not −4000; OR, with a fat penalty, the loss+penalty silently exceeds WB and re-opens DEF-01-C (impossible-negative equity).
**Why it happens:** The maintenance liq price retains the `/(1−MMR)` buffer by design; only the *bankruptcy* price (MMR=0) gives loss == WB exactly.
**How to avoid:** Implement an explicit cap: `total_realized_loss = min(realized_loss + penalty, WB)`. The penalty (D-05) consumes the buffer first; the clamp guards the tail.
**Warning signs:** Equity goes more negative than `−allocated_margin` on a liquidation; a unit test that asserts loss == WB passes only when MMR is set to 0.

### Pitfall 3: Determinism of the multi-breach liquidation order (D-02)
**What goes wrong:** Iterating breached positions in dict/hash order makes the cash-ledger sequence non-deterministic → the determinism double-run gate fails (different CashOperation timestamps/order).
**Why it happens:** `position_manager.get_all_positions()` returns a dict; Python preserves insertion order but a future refactor or a multi-symbol bar could reorder.
**How to avoid:** Sort breached positions by an explicit, total deterministic key (D-02 suggests symbol then open-time; add position-id as a final tiebreak). Outcomes are independent (isolated), so only the *sequence* matters — but it must be fixed.
**Warning signs:** A second run of the same scenario produces a different cash-operations CSV ordering.

### Pitfall 4: The forced-close FillEvent silently no-ops the mirror if no Order is in storage
**What goes wrong:** `ReconcileManager.on_fill` (reconcile_manager.py:210-214) does `if order_id is None: return` and `if order is None: return` — a liquidation fill carrying a fresh `order_id` with no matching `Order` in `order_storage` reconciles **nothing** (no EXECUTED→FILLED), violating LIQ-03's "reconciling through the existing mirror path."
**Why it happens:** The mirror is built from real admitted orders; the liquidation engine bypasses admission, so unless it explicitly registers the forced-close `Order`, the mirror has no record.
**How to avoid:** Mint a real forced-close `Order` (opposite side, qty = |size|, tagged `OrderTriggerSource.LIQUIDATION`), persist it via the order storage, build the `OrderEvent`/`FillEvent` from it (`FillEvent.new_fill` needs the order), then emit. The portfolio settle (`on_fill`) does not need the order, but the mirror reconcile does.
**Warning signs:** Portfolio cash/position settles correctly but `get_orders_by_ticker` shows no FILLED liquidation order; the order mirror count is short by one.

### Pitfall 5: Decimal precision in the `/(1−MMR)` division
**What goes wrong:** `Decimal(float)` on the MMR or rate (e.g. `Decimal(0.01)`) injects a binary-float artifact; the liq price drifts and the golden won't double-run byte-identically.
**Why it happens:** The money policy forbids `Decimal(float)` — enter via `to_money(x)` (`Decimal(str(x))`). The division `/(1−MMR)` carries full 28-digit precision and must only `quantize` at the money boundary (the fill price), not mid-formula.
**How to avoid:** Keep `liquidation_fee_rate`, `maintenance_margin_rate` as `Decimal` fields on `Instrument` (already the case for MMR); carry full precision through the formula; quantize the liq price to the instrument's price scale only at `FillEvent` construction.
**Warning signs:** A liq price with >8 dp leaking into the trade log; a double-run diff failing on the last decimal.

### Pitfall 6: FillEvent timing — must settle on the breach bar, not next-bar-open
**What goes wrong:** Reusing the exchange path stamps the fill at the next bar's open (the look-ahead-safe matching contract); the liquidation would settle a bar late at a different price.
**Why it happens:** `ExecutionHandler`/`SimulatedExchange` deliberately fill market orders next-bar-open (D-01/D-13). Liquidation is an equity event that must settle NOW.
**How to avoid:** Mint and emit the `FillEvent` directly on the BAR route with `time=bar_time` (the breach bar) and `price=liq_price` (D-04). Do NOT enqueue an `OrderEvent` to the execution handler for the close.
**Warning signs:** The liquidation trade's exit_date is one bar after the breach; the fill price is the next bar's open, not the computed liq price.

## Code Examples

### Adding the OrderTriggerSource.LIQUIDATION member (mirror the ADMISSION_* pattern)
```python
# Source: itrader/core/enums/order.py:174 (TABS — match the file)
class OrderTriggerSource(Enum):
	SYSTEM = "system"
	STRATEGY = "strategy"
	# … existing members …
	ADMISSION_LEVERAGE = "admission_leverage"
	LIQUIDATION = "liquidation"   # NEW (LIQ-03) — value-equal string, _missing_ case-insensitive parse already handles it
```

### Adding liquidation_fee_rate to Instrument (4 SPACES — match the file)
```python
# Source: itrader/core/instrument.py (frozen dataclass; D-06)
    maintenance_margin_rate: Decimal
    max_leverage: Decimal
    # ... existing defaulted fields ...
    borrow_rate: Decimal = Decimal("0")
    liquidation_fee_rate: Decimal = Decimal("0")   # NEW (D-06) — default 0 = oracle-dark
```

### The corrected liquidation-price + capped-loss math (Decimal end-to-end)
```python
# Source: HAND-VERIFIED this session (freqtrade-canonical isolated linear)
from decimal import Decimal

def isolated_liq_price(side, entry: Decimal, size: Decimal, wb: Decimal, mmr: Decimal) -> Decimal:
    margin_per_unit = wb / abs(size)            # == entry / leverage for a fresh open
    if side is PositionSide.LONG:
        return (entry - margin_per_unit) / (Decimal("1") - mmr)
    else:  # SHORT
        return (entry + margin_per_unit) / (Decimal("1") + mmr)

def forced_close_loss(side, entry, size, liq_price, fee_rate, wb) -> tuple[Decimal, Decimal]:
    if side is PositionSide.LONG:
        realized = (liq_price - entry) * abs(size)     # negative
    else:
        realized = (entry - liq_price) * abs(size)     # negative
    penalty = fee_rate * abs(size) * liq_price          # D-05 (carried in FillEvent.commission)
    total_loss = -realized + penalty                    # positive magnitude
    capped_loss = min(total_loss, wb)                   # D-07 — explicit clamp (NOT automatic)
    return capped_loss, penalty
```

### WR-04 fix — the call-order defect (TABS — match portfolio.py)
```python
# Source: itrader/portfolio_handler/portfolio.py:430-435  (the DEFECT, verbatim)
self.cash_manager.release_margin(str(position.id))          # pops the lock FIRST
new_lock = position.aggregate_notional / leverage
self.cash_manager.assert_lock_fits_buying_power(new_lock, str(position.id))
#                                       ^ reads own_prior_lock via get_locked_margin_for() == 0
#                                         because release_margin already popped it.
self.cash_manager.lock_margin(str(position.id), new_lock)

# FIX SHAPE (planner's discretion, D-discretion):
#  Option A — assert BEFORE release (re-order so own_prior_lock is still present):
#     released = ... compute new_lock ...; assert_lock_fits_buying_power(new_lock, pid); release; lock
#  Option B — thread the released amount into the assertion:
#     released = self.cash_manager.release_margin(str(position.id))
#     self.cash_manager.assert_lock_fits_buying_power(new_lock, str(position.id), prior_lock=released)
# Two call sites: open/scale-in (~430) AND partial/full close (~449). Fix BOTH.
```

### The e2e scenario shape to mirror (white-box hand-computed, NOT golden-diff)
```python
# Source: tests/e2e/levered_long/test_levered_long_scenario.py
# - synthetic ticker (NEVER BTCUSD — oracle byte-exact), oracle-dark margin Instrument
# - drives the REAL engine tick-by-tick via system.engine.time_generator
# - asserts margin INTERNALS (locked, available, maintenance, realised_pnl) with
#   the full arithmetic shown inline in the module docstring
# The new liquidation scenarios (forced-liq long, forced-liq short,
# leveraged-long-into-liquidation) follow THIS pattern, NOT the golden/ run_scenario
# harness (which only captures trades/equity/summary, not the liquidation internals).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No liquidation model (DEF-01-C — equity can drift impossibly negative) | Per-position isolated bar-close liquidation (P4) | This phase | Equity floored at allocated margin; the milestone's correctness gate. |
| Parked P2/P3 scenarios assert inline, no frozen golden | Freeze ALL parked + new P4 scenarios as one accounting-core golden | This phase (D-10) | Single owner-gated re-baseline; short/leveraged scenarios stop being permanently parked. |
| Liquidation via exchange/MatchingEngine (a naive default) | Portfolio-side liquidation engine mints FillEvent on BAR route (D-04) | This phase | Settles on the breach bar at liq price; bypasses next-bar-open matching. |

**Deprecated/outdated:**
- The CONTEXT D-01 formula string `Entry×(1−(WB/size)/L)/(1+MMR)` — superseded by the corrected freqtrade-canonical form (Pitfall 1). Treat the CONTEXT string as a transcription error, not the spec.
- `freqtrade` as an oracle — ruled out for P4 (D-09); it is the Phase-B funding oracle.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The freqtrade-canonical isolated formula `(Entry ∓ WB/\|size\|)/(1 ∓ MMR)` is the intended D-01 math (the CONTEXT string is a transcription error). | Pattern 1 / Pitfall 1 | If the user actually intends a different liquidation model, the worked numbers and goldens are wrong. **HIGH-priority confirmation — surface to discuss-phase.** Mitigated: the math is the only reading that produces a sane price AND matches the D-03/D-07 buffer reconciliation. |
| A2 | `WB` (the floor / formula numerator) = the `CashManager` position-keyed locked-margin (`get_locked_margin_for`), i.e. `aggregate_notional / leverage`. | Pattern 1 / Don't Hand-Roll | If WB should instead be a live mark-to-market wallet balance, the per-position floor shifts. CONTEXT D-01 explicitly says "WB = that position's allocated isolated margin," which is the lock — confidence HIGH. |
| A3 | Running the liquidation check AFTER the P3 carry accrual (carry-eroded equity) is correct. | Architecture / placement | If the user wants pre-carry breach detection, the trigger bar could differ by one. Design §7 supports post-carry; D-discretion leaves placement to the planner. |
| A4 | The forced-close `Order` must be registered in `order_storage` for the mirror to reconcile (vs. tolerating a missing order). | Pitfall 4 | If the planner instead chooses to relax `ReconcileManager.on_fill` to mint-on-missing, that's a different (larger) change. Code-verified that today it silently no-ops — confidence HIGH on the constraint. |
| A5 | A realistic crypto `liquidation_fee_rate` (e.g. 0.005 = 0.5%) is the scenario default; BTCUSD leaves it 0 (oracle-dark). | Discretion | Pure scenario-shaping value; oracle-dark either way. LOW risk. |

## Open Questions (RESOLVED)

> All three resolved in `04-CONTEXT.md` "Planning-time correction (owner-authorized 2026-06-16)": Q1 → D-01-CORR (corrected formula) + D-03-CORR (explicit clamp); Q2 → register a real Order (LIQ-03 clarification); Q3 → existing `Instrument.maintenance_margin_rate` is sufficient, no new field.

1. **RESOLVED (D-01-CORR / D-03-CORR): reconcile D-03 ("no clamp needed") with D-07 (explicit cap).** The hand-computation proves the floor is NOT automatic at the maintenance liq price — an explicit `min(loss+penalty, WB)` clamp is required, contradicting D-03's literal wording.
   - What we know: at the bankruptcy price loss == WB exactly; at the maintenance liq price a buffer remains and the penalty (plus deep-MMR/large-fee cases) can push loss past WB.
   - What's unclear: whether D-03's intent was the bankruptcy price (loss == WB automatic) or the maintenance liq price + cap.
   - Recommendation: implement the maintenance liq price + explicit cap (the most realistic, matches D-05/D-07); flag the D-03 wording to the user during discuss-phase as a clarification, not a re-decision.

2. **RESOLVED (register a real Order): forced-close Order — register a real Order, or relax the reconcile?** (Pitfall 4 / A4)
   - Recommendation: register a real `Order` (smaller, local change; keeps LIQ-03's "existing path" literally true).

3. **RESOLVED (no new field): IN-03 (per-instrument MMR) — already satisfied?** `Instrument.maintenance_margin_rate` exists (INST-03, instrument.py:85) and is read per-position by `maintenance_margin` (handler:307). The deferred-items.md "IN-03" is a *different* item (carry-gap approximation, a Phase-B nit) — naming collision.
   - Recommendation: confirm the existing per-instrument `maintenance_margin_rate` is sufficient for LIQ (it is — the formula reads it directly); no new field needed. Note the IN-03 label collision so it isn't conflated.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `backtesting` | XVAL short/leveraged + liquidation corroboration | ✓ | 0.6.5 | — |
| `backtrader` | XVAL short/leveraged accounting | ✓ | 1.9.78.123 | — |
| `pandas` | golden diff | ✓ | 2.3.x | — |
| `freqtrade` | (D-09 — explicitly ruled out) | ✗ | — | Hand-computed closed-form is the primary oracle (D-08) — no fallback needed; absence is by design. |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** `freqtrade` is absent but intentionally not used (D-09).

## Validation Architecture

> `.planning/config.json` not inspected for `nyquist_validation`; treating as enabled (absent = enabled).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (run via Poetry; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/portfolio -x` (or the specific new test file) |
| Full suite command | `make test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIQ-01 | bar-close breach → forced FillEvent at liq price, loss floored at WB | unit + e2e | `poetry run pytest tests/unit/portfolio/test_liquidation.py -x` | ❌ Wave 0 |
| LIQ-01 | deterministic multi-breach order | unit | `poetry run pytest -k "multi_breach_deterministic" -x` | ❌ Wave 0 |
| LIQ-02 | penalty = rate×\|size\|×liq, capped at WB | unit | `poetry run pytest -k "liquidation_penalty" -x` | ❌ Wave 0 |
| LIQ-03 | EXECUTED→FILLED mirror reconcile, OrderTriggerSource.LIQUIDATION, no new FillStatus | unit | `poetry run pytest tests/unit/order -k "liquidation" -x` | ❌ Wave 0 |
| LIQ-01/02/03 | forced-liq long / short / leveraged-long-into-liquidation, full run path | e2e (white-box, mirror `levered_long`) | `poetry run pytest tests/e2e/forced_liq_long -x` | ❌ Wave 0 |
| WR-04 | assert reads the prior lock add-back correctly | unit (regression) | `poetry run pytest tests/unit/portfolio -k "lock_fits_buying_power" -x` | ❌ Wave 0 (add) |
| D-11 | SMA_MACD byte-exact (134 / 46189.87730727451) | integration (existing) | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ |
| D-10 | parked P2/P3 scenarios freeze (golden or asserted) | e2e | `poetry run pytest tests/e2e/levered_long tests/e2e/short_roundtrip tests/e2e/short_carry tests/e2e/partial_cover -x` | ✅ (assert inline; no golden/ yet) |
| XVAL-01 | short/leveraged/liquidation cross-validated | script (not in suite) | `poetry run python scripts/cross_validate.py` (extend) | ✅ driver exists |

### Sampling Rate
- **Per task commit:** the specific new unit test file (`poetry run pytest tests/unit/portfolio/test_liquidation.py -x`).
- **Per wave merge:** `make test-portfolio && make test-orders` + the new e2e leaves.
- **Phase gate:** `make test` green AND `test_backtest_oracle.py` byte-exact (D-11) before `/gsd:verify-work`; cross-val evidence doc + owner sign-off before the freeze (D-12).

### Wave 0 Gaps
- [ ] `tests/unit/portfolio/test_liquidation.py` — covers LIQ-01/LIQ-02 (formula, breach, penalty, cap, determinism)
- [ ] `tests/unit/order/test_liquidation_reconcile.py` — covers LIQ-03 (EXECUTED→FILLED, LIQUIDATION trigger, no new status, registered order)
- [ ] `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` — WR-04 regression
- [ ] `tests/e2e/forced_liq_long/`, `tests/e2e/forced_liq_short/`, `tests/e2e/levered_long_into_liquidation/` — new white-box e2e leaves (mirror `levered_long/test_levered_long_scenario.py`)
- [ ] D-10 freeze: decide per parked scenario (`levered_long`, `short_roundtrip`, `short_carry`, `partial_cover`) whether to add a `golden/` dir + convert to `run_scenario`, or keep the white-box asserted form and "freeze" = commit-with-VERIFY-note. **They currently have NO `golden/` subdir** — verified.
- [ ] Extend `scripts/cross_validate.py` + add `scripts/crossval/{short,levered,liquidation}_run.py` (mirror `*_limit_run.py`)
- [ ] New evidence doc `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` (sibling, mirror the Owner Sign-Off block)

## Security Domain

> No `security_enforcement` config inspected. This is a local, offline backtest engine with no network surface, no auth, no untrusted input on the liquidation path. The only "security-adjacent" concern is **financial-correctness integrity**, covered by the Decimal/determinism/byte-exact gates above. ASVS categories (auth, session, access control, crypto) do not apply to this phase.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | partial | The liquidation engine inputs are engine-internal (position fields, Universe Instrument). Guard non-positive price / unwired Universe with the existing `StateError` pattern (mirrors `_accrue_short_carry` WR-02/WR-03). |
| V6 Cryptography | no | UUIDv7 ids via `idgen` (existing); no new crypto. |
| (others) | no | No network/auth/session surface. |

**Correctness threat patterns for this stack:**
| Pattern | Mitigation |
|---------|------------|
| Impossible-negative equity (DEF-01-C re-open) | Explicit loss cap at WB (Pitfall 2) — the whole point of LIQ-01. |
| Non-deterministic ledger ordering | Deterministic multi-breach sort (Pitfall 3). |
| Float-money artifact in the liq formula | `Decimal(str(x))` only; quantize at the fill boundary (Pitfall 5). |
| Silent mirror divergence | Register the forced-close Order; assert FILLED in tests (Pitfall 4). |
| Golden drift on the spot oracle | Default-off (`liquidation_fee_rate=0`); `test_backtest_oracle.py` byte-exact gate (D-11). |

## Sources

### Primary (HIGH confidence — read directly this session)
- `itrader/portfolio_handler/portfolio_handler.py` (lines 280-477) — `maintenance_margin` (307), `margin_ratio` (342), `on_fill` (359), `update_portfolios_market_value` (432); holds `global_queue` (59) + `_universe` (88).
- `itrader/portfolio_handler/cash/cash_manager.py` (full) — `assert_lock_fits_buying_power` (437), `release_margin` (583), `apply_fill_cash_flow` (308), `accrue_borrow_interest` (362).
- `itrader/portfolio_handler/portfolio.py` (380-489, 608-740) — WR-04 call order (430/449), the carry accrual hook, `_accrue_short_carry`.
- `itrader/portfolio_handler/position/position.py` (85-211) — `realised_pnl` (175), `unrealised_pnl` (201), `aggregate_notional` (96), SHORT/LONG branches.
- `itrader/core/enums/order.py` (174-201) — `OrderTriggerSource` closed-vocab enum + `_missing_`.
- `itrader/core/instrument.py` (full) — frozen value object, `maintenance_margin_rate` (85), `borrow_rate` (90, the pattern `liquidation_fee_rate` follows).
- `itrader/config/portfolio.py` (66-86) — `TradingRules` (the config fallback home).
- `itrader/events_handler/events/fill.py` (full) — `FillEvent.new_fill` (81, requires an OrderEvent), `commission` field (63).
- `itrader/events_handler/events/order.py` (full) — `OrderEvent.new_order_event` (82).
- `itrader/order_handler/order_handler.py` (150) + `order_manager.py` (206) + `reconcile/reconcile_manager.py` (179-296) — the EXECUTED→FILLED mirror reconcile + the order-missing early-return (210-214).
- `tests/e2e/conftest.py` (full) — the `run_scenario` golden-diff harness + `--freeze` discipline.
- `tests/e2e/levered_long/test_levered_long_scenario.py` (full) — the white-box hand-computed e2e pattern.
- `tests/golden/CROSS-VALIDATION.md` (Owner Sign-Off block, 206-224) — the D-12 template.
- `scripts/cross_validate.py` (1-50) — the crossval driver.
- `.venv/.../backtesting/backtesting.py` (744-765, 849-864, 1152-1155) — `margin=1/leverage`, `equity ≤ 0 → close-all` (D-08 corroboration model).

### Verified facts (tool-confirmed)
- `freqtrade` absent: `grep -ci freqtrade poetry.lock pyproject.toml` → 0 (D-09). `[VERIFIED: grep]`
- `backtesting` 0.6.5 / `backtrader` 1.9.78.123 installed. `[VERIFIED: poetry.lock + import]`
- The corrected liquidation formula + capped-loss reconciliation — `[HAND-VERIFIED: Decimal harness, this session]`.

### Tertiary (LOW confidence — flagged for validation)
- freqtrade-canonical isolated formula shape — `[CITED: freqtrade docs, training knowledge]`, cross-checked against backtesting.py's `margin=1/L` and the hand-computation; confirm against the design note §4/§6 reading (A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; oracles verified installed/pinned.
- Architecture / seams: HIGH — every named seam read directly; the BAR-route hook, mirror reconcile, and WR-04 defect are code-confirmed.
- Liquidation math: HIGH — hand-verified in a Decimal harness; the CONTEXT formula error and the D-03/D-07 reconciliation are demonstrated numerically.
- Pitfalls: HIGH — each traced to a specific line in the live code.
- D-03 intent (bankruptcy vs maintenance price): MEDIUM — surfaced as Open Question 1 / Assumption A1 for user confirmation.

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (stable first-party codebase; the only external dependency is two pinned oracles).
