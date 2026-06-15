# Requirements: iTrader — v1.4 Margin, Leverage, Shorts & Trailing Stops

**Defined:** 2026-06-14
**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
correct, deterministic, cross-validated numbers — now extended with first-class shorts, leverage, a
liquidation model, and engine-native trailing stops, all owner-gated and cross-validated.

> **Milestone discipline (owner-gated, result-changing — like M5).** Enabling shorts/leverage/
> liquidation changes results. A new golden master freezes **ONLY** after explicit owner sign-off
> with full attribution, validated by external cross-validation (`backtesting.py` / `backtrader`).
> `mypy --strict` clean, Decimal end-to-end, determinism double-run byte-identical still hold. The
> existing SMA_MACD spot oracle (134 trades / `final_equity 46189.87730727451`) stays byte-exact
> except where shorts/leverage legitimately change a leaf. Trailing stops are a DIFFERENT subsystem
> (matching-engine vs accounting) → their own phase + own re-baseline. Full design:
> `ROADMAP.md` Phase 999.4 scoping block + `notes/margin-leverage-shorts-999.4.md` (Phase A in;
> Phase B perp realism deferred).

## v1 Requirements

Requirements for milestone v1.4. Each maps to exactly one roadmap phase (see Traceability).

### Instrument (INST)

- [x] **INST-01**: An `Instrument` value object (`core/instrument.py`, frozen) is the per-symbol source
  of price precision, quantity precision, and `min_order_size`; `core/money.py::quantize` reads
  precision from it and the hard-coded `_INSTRUMENT_SCALES` table is deleted.
- [x] **INST-02**: Price precision resolves declared → inferred-from-data (guarded: read the price as a
  string, cap max decimal places) → default; `quantity_precision` and `min_order_size` resolve
  declared → default (not inferable from OHLCV). `BTCUSD` always takes the declared 8dp branch so the
  golden oracle does not drift.
- [x] **INST-03**: `Instrument` carries the margin/funding params (`maintenance_margin_rate`,
  `max_leverage`, `settles_funding: bool`) consumed by the margin, liquidation, and leverage features.
  `ExchangeLimits` is demoted to a venue-level fallback for undeclared symbols.

### Margin (MARGIN)

- [x] **MARGIN-01**: Opening a position reserves `initial_margin = notional / leverage` against
  available cash.
- [x] **MARGIN-02**: Orders exceeding available free margin are rejected (or clipped) rather than
  silently over-leveraging the simulated account.
- [x] **MARGIN-03**: Maintenance margin is tracked per open position.

### Liquidation (LIQ)

- [ ] **LIQ-01**: A position breaching maintenance margin (checked on bar close — the honest proxy on
  daily OHLCV with no mark feed) is force-closed via a `FillEvent`, with loss floored at the position's
  allocated isolated margin.
- [ ] **LIQ-02**: A configurable liquidation penalty/fee is charged so liquidation PnL is not optimistic.
- [ ] **LIQ-03**: Forced liquidation reuses `FillStatus.EXECUTED` and mints an admission-bypassing close
  order tagged with a new `OrderTriggerSource.LIQUIDATION`, reconciling through the existing
  position/cash/order-mirror path (no new `FillStatus`).

### Shorts (SHORT)

- [ ] **SHORT-01**: A strategy can open and hold a short position — the `LONG_ONLY` guard in
  `StrategiesHandler.add_strategy` no longer blocks `SHORT_ONLY` / long-short books.
- [ ] **SHORT-02**: A BUY-to-cover on a `SHORT_ONLY` book reduces/closes the short instead of falling
  through to entry sizing and flipping the book long (CR-01 cover-arm fix in `_resolve_signal_quantity`).
- [ ] **SHORT-03**: Short positions compute first-class short PnL (`|size| × (entry − exit)` minus
  carry), modeled as a first-class direction rather than a sign-flipped long.

### Carry (CARRY)

- [ ] **CARRY-01**: Open short positions accrue borrow interest (`days × price × |size| × rate/365`)
  booked to realized cash (one parameter, no external data feed).

### Leverage (LEV)

- [x] **LEV-01**: A portfolio can trade with configurable leverage > 1 via the existing
  `enable_margin` / `allow_short_selling` config hooks.
- [x] **LEV-02**: A Kelly sizing fraction > 1 is expressible (notional = f × equity, posting
  `notional / L` as margin).
- [ ] **LEV-03**: Strategy-declared leverage flows end-to-end through the run path
  (signal → order → fill → transaction → position), carrying the admission-clamped
  *effective* leverage `min(signal, instr.max, pf.max)` so the position-life locked
  margin (`aggregate_notional / leverage`) equals the admission reservation
  (`notional / effective_leverage`). Discovered during Phase 2 plan 02-06 (Findings A/B:
  `StrategiesHandler` dropped `SignalIntent.leverage` at fan-out; `OrderEvent`/`FillEvent`/
  `Transaction` carried no leverage, so `Position.leverage` defaulted to 1 and locked the
  full notional). Closed by plan 02-07.

### Trailing stop (TRAIL)

- [ ] **TRAIL-01**: A strategy can declare a `TRAILING_STOP` order; the `MatchingEngine` ratchets the
  resting stop in the favorable direction only as price extends.
- [ ] **TRAIL-02**: The trail updates from closed-bar extremes and becomes active on the next bar
  (look-ahead-safe per the `bar_feed.py` contract — never trail to this bar's extreme and trigger off
  the same bar).
- [ ] **TRAIL-03**: Trailing-stop backtest behavior is cross-validated against `backtesting.py` and
  `backtrader`.

### Validation & flagship (XVAL / PAIR)

- [ ] **XVAL-01**: Short, leveraged-long, and liquidation scenarios are cross-validated against
  `backtesting.py` and `backtrader`; the new golden master freezes only after explicit owner sign-off
  with full attribution.
- [ ] **PAIR-01**: A market-neutral long/short pair-trading strategy (cointegration/spread) runs
  end-to-end, exercising both sides — the flagship demonstration of the short side (NOT the primary
  correctness oracle; that is the crafted scenarios under XVAL-01).

## Future Requirements

Deferred to a future milestone. Tracked but not in the v1.4 roadmap.

### Perp realism — "Phase B" (FUND) → future (additive on the v1.4 core)

- **FUND-01**: Funding-rate accrual at funding-timestamp boundaries (`cash += −side_sign × mark_price
  × |size| × rate`, only for positions open at the stamp).
- **FUND-02**: Mark-price liquidation trigger (swap bar-close for a mark-price series; resolves the
  phantom-wick risk).
- **FUND-03**: Funding-data pipeline (ccxt `fetchFundingRateHistory` → per-symbol CSV; per-symbol
  funding interval from market metadata — do not hardcode 8h).
- **FUND-04**: `freqtrade` adopted as a fourth cross-validation oracle (the only ecosystem framework
  modeling funding + liquidation in backtest).

### Live account (ACCT) → N+4 (Backlog 999.3)

- **ACCT-01**: A first-class `Account` domain object as the reconciled local mirror of the venue's
  balance/margin state (`CashAccount` vs `MarginAccount`); born with the live connector — no backtest
  analogue.

## Out of Scope

Explicitly excluded from v1.4. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Funding-rate accrual / mark-price liquidation / funding-data pipeline (Phase B) | Purely additive on the v1.4 core; needs a real funding time-series + a finer-than-daily mark feed. Deferred as FUND-0x; v1.4 uses borrow-interest carry + bar-close liquidation. |
| `Account` abstraction (reconciliation mirror) | Reconciliation has no backtest analogue — the source of truth only flips to the venue in live mode. Born in N+4 with the connector (ACCT-01). |
| Trailing-stop native-vs-synthetic capability seam on `AbstractExchange` | A live-execution concern (survive disconnect, modify churn, cancel-replace gaps). v1.4 models only the ideal engine-native trail in backtest; the live seam is N+4. |
| Cross-margin (account-wide collateral pool / joint liquidation) | v1.4 uses isolated margin (per-position, deterministic). Cross-margin needs an account-equity pool — a separate, later effort behind the same `Instrument`/position seam. |
| Tiered maintenance-margin brackets | v1.4 uses a flat per-instrument MMR with notional capped to first-tier validity (documented approximation; schema wired so a tier table can replace it later). |
| Inverse / coin-margined perps; bankruptcy price / insurance fund / ADL; hedge mode | Each is its own milestone-sized effort; crypto-first linear USD-settled only. |
| `Portfolio.user_id` removal | Independent multi-tenancy cleanup (constructor-signature ripple); kept out so it does not muddy the owner-gated golden re-baseline. |

## Traceability

Which phases cover which requirements. Filled during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INST-01 | Phase 1 — Instrument Value Object | Complete |
| INST-02 | Phase 1 — Instrument Value Object | Complete |
| INST-03 | Phase 1 — Instrument Value Object | Complete |
| MARGIN-01 | Phase 2 — Margin Accounting & Leverage | Complete |
| MARGIN-02 | Phase 2 — Margin Accounting & Leverage | Complete |
| MARGIN-03 | Phase 2 — Margin Accounting & Leverage | Complete |
| LEV-01 | Phase 2 — Margin Accounting & Leverage | Complete |
| LEV-02 | Phase 2 — Margin Accounting & Leverage | Complete |
| LEV-03 | Phase 2 — Margin Accounting & Leverage | Pending |
| SHORT-01 | Phase 3 — Shorts & Borrow Carry | Pending |
| SHORT-02 | Phase 3 — Shorts & Borrow Carry | Pending |
| SHORT-03 | Phase 3 — Shorts & Borrow Carry | Pending |
| CARRY-01 | Phase 3 — Shorts & Borrow Carry | Pending |
| LIQ-01 | Phase 4 — Liquidation & Cross-Validation Re-baseline | Pending |
| LIQ-02 | Phase 4 — Liquidation & Cross-Validation Re-baseline | Pending |
| LIQ-03 | Phase 4 — Liquidation & Cross-Validation Re-baseline | Pending |
| XVAL-01 | Phase 4 — Liquidation & Cross-Validation Re-baseline | Pending |
| TRAIL-01 | Phase 5 — Engine-Native Trailing Stops | Pending |
| TRAIL-02 | Phase 5 — Engine-Native Trailing Stops | Pending |
| TRAIL-03 | Phase 5 — Engine-Native Trailing Stops | Pending |
| PAIR-01 | Phase 6 — Pair-Trading Flagship | Pending |

**Coverage:**
- v1.4 requirements: 20 total
- Mapped to phases: 20 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-14*
*Last updated: 2026-06-14 — roadmap created, all 20 requirements mapped to 6 phases (100% coverage)*
