# Phase 4: Liquidation & Cross-Validation Re-baseline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 4-Liquidation & Cross-Validation Re-baseline
**Areas discussed:** Trigger basis, Fill price & floor, Penalty model, XVAL & freeze

---

## Trigger basis

### Detection

| Option | Description | Selected |
|--------|-------------|----------|
| Per-position liq price | Compute each position's isolated liquidation price (`Entry×(1−(WB/size)/L)/(1+MMR)`, short mirrored); breach when bar close crosses it. Most realistic + freqtrade reference; hand-computable. | ✓ |
| Per-position margin coverage | Position equity vs maintenance requirement (MMR×|size|×close). Mathematically equivalent, no formula inversion. | |
| Portfolio-aggregate ratio | Reuse `margin_ratio = total_equity/maintenance` < 1.0. Simplest but cross-margin-flavored; conflicts with isolated. | |

**User's choice:** Per-position liq price (locked after asking "what's the most realistic / what do other frameworks do").
**Notes:** Established the realism evidence — real venues (Binance/Bybit/OKX isolated) and freqtrade (only backtest framework modeling liquidation) both use a per-position liquidation price. Bar-close trigger instant (vs mark price) is the one locked deliberate simplification. backtesting.py = crude `equity≤0 close-all` (cross-margin), backtrader/nautilus = no isolated liquidation.

### Multi-breach

| Option | Description | Selected |
|--------|-------------|----------|
| Each independent, fixed order | Liquidate every breaching position independently, deterministic order. True isolated; order affects only ledger sequence. | ✓ |
| Liquidate, re-mark, re-check | Re-mark equity after each; cross-margin behavior. | |

**User's choice:** Each independent, fixed order (after confirming it's the most realistic — isolated buckets don't interact).
**Notes:** Re-mark/re-check is moot under isolated (a liq price depends only on its own bucket); it's a cross-margin concept (deferred).

---

## Fill price & floor

| Option | Description | Selected |
|--------|-------------|----------|
| Fill at liquidation price | Settle at the computed liq price → loss = allocated isolated margin by construction; floor automatic, no clamp. freqtrade model; most realistic; hand-computable. | ✓ |
| Fill at bar close + clamp | Settle at observed close, explicitly clamp loss to allocated margin; excess uncharged. More conservative on gaps; needs clamp + excess disposition. | |
| Fill at bar close, no clamp | No floor; loss can exceed margin. Rejected — doesn't close DEF-01-C. | |

**User's choice:** Fill at liquidation price.
**Notes:** Surfaced the follow-up that at the liq price remaining equity = the maintenance buffer (`/(1+MMR)` term), so the LIQ-02 penalty is what consumes it — connecting to the Penalty area. Also resolved (via the user's "is the penalty delivered via a FillEvent from the exchange?" question) that the portfolio-side liquidation engine mints the `FillEvent` directly on the BAR route, NOT through the exchange (which fills next-bar-open).

---

## Penalty model

### Penalty basis

| Option | Description | Selected |
|--------|-------------|----------|
| % of notional | rate × |size| × liq price. Binance/Bybit clearance-fee model; scales with size. | ✓ |
| % of allocated margin | rate × allocated margin. Simpler vs floor; not how venues quote it. | |
| Flat fee | Fixed per-liquidation; doesn't scale; unrealistic. | |

**User's choice:** % of notional.

### Penalty config home

| Option | Description | Selected |
|--------|-------------|----------|
| Instrument-first + config fallback | `liquidation_fee_rate` on Instrument (default unset) + config-level default for undeclared symbols. P1/P3 pattern; one-knob ergonomics, zero realism loss. | ✓ |
| On Instrument only | No separate config dial. | |
| On PortfolioConfig/TradingRules only | Single account-wide dial; less faithful to per-market reality. | |

**User's choice:** Instrument-first + config fallback (option 1).
**Notes:** User initially tempted by the single-dial option (3); chose option 1 after learning liquidation fees track MMR and are near-uniform across majors (this milestone's universe), AND that option 1 gives option-3 ergonomics for free (set fallback, declare no overrides) at the cost of one optional field — no realism/rework tradeoff, and avoids the asymmetry of an account-wide fee next to per-instrument MMR.

### Floor interaction

| Option | Description | Selected |
|--------|-------------|----------|
| Consumes buffer, capped at margin | Penalty deducted within the margin envelope; total loss capped at allocated isolated margin. Most realistic (max loss = isolated margin); keeps DEF-01-C closed; satisfies LIQ-02. | ✓ |
| Charged on top, can exceed margin | No cap; loss can exceed margin. Rejected — reopens negative-equity hole. | |

**User's choice:** Consumes buffer, capped at margin.

---

## XVAL & freeze

### Liquidation oracle

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-computed primary + engines corroborate | Hand-computed closed-form is primary oracle; backtesting.py/backtrader fully validate short & leveraged-long + directional liquidation corroboration. | ✓ |
| Force engines to reproduce isolated liq | Custom liquidation logic in crossval runners; high-effort, fragile, weakens independence. | |
| Hand-computed only, no external for liq | Liquidation hand-verified alone; engines only short + leveraged-long. | |

**User's choice:** Hand-computed primary + engines corroborate.
**Notes:** User asked whether freqtrade (mentioned as supporting liquidation) should be included. Verified freqtrade is NOT installed (absent from pyproject/poetry.lock, not importable); ruled out — also circular (we copy its formula) and slotted as the Phase-B funding oracle. XVAL-01 names only backtesting.py + backtrader. Both remaining options cross-validate short + leveraged-long; user chose to keep the near-free directional liquidation corroboration.

### Freeze set

| Option | Description | Selected |
|--------|-------------|----------|
| All parked P2/P3 + new P4 liq | Freeze the parked P2 leveraged-long + P3 short scenarios together with new P4 liquidation scenarios — the single accounting-core re-baseline. | ✓ |
| Only new P4 liquidation scenarios | Splits the oracle; contradicts the locked one-re-baseline-at-P4 plan. | |

**User's choice:** All parked P2/P3 + new P4 liq.

### SMA_MACD oracle

| Option | Description | Selected |
|--------|-------------|----------|
| Stays byte-exact, untouched | LONG_ONLY spot, margin/shorts/liq default-off → oracle-dark. "Re-baseline" = freezing NEW crafted goldens, not changing SMA_MACD. | ✓ |
| SMA_MACD also re-derived | Rejected — nothing touches the LONG_ONLY spot path. | |

**User's choice:** Stays byte-exact, untouched.

---

## Claude's Discretion

- Deterministic tiebreak ordering for multi-breach (symbol/open-time/position-id).
- Placement of the liquidation check within `update_portfolios_market_value` relative to the P3 carry accrual.
- `OrderTriggerSource.LIQUIDATION` member value + trade-log/metrics filtering wiring.
- Crafted-scenario shape/count + test-tree location (`tests/e2e/<scenario>/`).
- BTCUSD `Instrument.liquidation_fee_rate` value + config fallback default for the crafted scenarios.
- WR-04 fix shape (assert before release vs thread the released amount in); whether IN-03 needs more than the existing per-instrument `maintenance_margin_rate`.
- New accounting-core cross-validation doc filename/location + crossval-runner additions (following the v1.3 `_limit` precedent).
- Owner sign-off mechanism: reuse the blocking human-verify checkpoint + a new accounting-core cross-validation evidence doc + Owner Sign-Off section (mirroring `CROSS-VALIDATION.md`) — captured as default (user chose "Ready for context" rather than discussing it separately).

## Deferred Ideas

- freqtrade as a 4th oracle → Phase B (funding validation; formula source for liquidation).
- Mark-price liquidation trigger → Phase B.
- Cross-margin / account-wide joint liquidation → beyond Phase B.
- Tiered MMR brackets → future (flat per-instrument MMR + first-tier cap this phase).
- Single-order flips (explicit close+open split) → deferred from P3.
- Engine-native trailing stops (TRAIL-*) → Phase 5; pair-trading flagship (PAIR-01) → Phase 6.
- IN-01/IN-02/IN-04 P3 doc/convention nits → future cleanup.
