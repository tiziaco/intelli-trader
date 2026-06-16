# Phase 3: Shorts & Borrow Carry - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 3-Shorts & Borrow Carry
**Areas discussed:** Borrow-carry model, Cover-arm & flip economics, Short enablement & PnL, P2 residuals & proof scope

---

## Borrow-carry model (CARRY-01)

### Rate source

| Option | Description | Selected |
|--------|-------------|----------|
| Instrument field | `borrow_rate: Decimal = 0` per-instrument on `core/instrument.py` | ✓ |
| Portfolio TradingRules knob | Single account-wide rate | |
| Both (Instrument + portfolio override) | Per-symbol source + optional override | |

**User's choice:** Instrument field (D-01)
**Notes:** User first asked whether per-instrument mirrors reality. Confirmed: crypto venues (Binance Margin / Bitfinex / Kraken) price borrow per asset; equities price cost-to-borrow per ticker. The per-instrument-ness is real; the static-over-time part is the documented approximation. The portfolio-wide knob is the *less* realistic option.

### Accrual timing & booking

| Option | Description | Selected |
|--------|-------------|----------|
| Per-bar on close, to realized cash | Accrue each BAR in `update_portfolios_market_value`, debit realized cash | ✓ |
| Lump sum at position close | Compute once at close, subtract from `realised_pnl` | |
| You decide | — | |

**User's choice:** Per-bar on close, to realized cash (D-02)
**Notes:** Matches backtrader; carry visible in equity as it accrues; P4 liquidation sees carry-eroded equity.

### Carry ledger recording

| Option | Description | Selected |
|--------|-------------|----------|
| New BORROW_INTEREST op type | Dedicated CashOperation kind | ✓ |
| Reuse generic TRANSACTION_DEBIT | No new op type | |
| You decide | — | |

**User's choice:** New `BORROW_INTEREST` op type (D-03)

### Days basis

| Option | Description | Selected |
|--------|-------------|----------|
| Elapsed between bar timestamps | Derive from bar-time gap via `BacktestClock` | ✓ |
| Fixed per-bar = configured timeframe | Assume 1 bar = timeframe | |
| You decide | — | |

**User's choice:** Elapsed between bar timestamps (D-04)

---

## Cover-arm & flip economics (SHORT-02 + CR-02-residual)

> User first asked for clarification: what a "cover-arm" is, how NautilusTrader / QuantConnect LEAN / freqtrade handle direction-changing orders, and what is architecturally most correct. Verified Nautilus source (installed) + current LEAN/freqtrade docs before re-posing. Also disambiguated: the "CR-01 cover-arm hole" here is the **v1.0 M5b CR-01**, NOT the Phase-2 CR-01 (leverage threading, already closed by 02-08).

### Cover-arm fix shape

| Option | Description | Selected |
|--------|-------------|----------|
| Side-agnostic exit | "action opposes open-position side ⇒ reduce" (Nautilus netting) | ✓ |
| Minimal symmetric arm | Add just the one missing BUY+short branch | |
| You decide | — | |

**User's choice:** Side-agnostic exit (D-05)
**Notes:** Chosen as the most architecturally correct — matches how a netting engine derives order effect from order-side vs position-side. Trade-off (touches FRAGILE seam more broadly) accepted.

### Over-cover / flip economics

| Option | Description | Selected |
|--------|-------------|----------|
| Clamp-to-flat now; split = future explicit-flip | Cover only reduces/closes; flip deferred as close+open split | ✓ |
| Full flip = close+open split NOW | Implement same-fill two-leg settlement this phase | |
| You decide | — | |

**User's choice:** Clamp-to-flat now; close+open split deferred (D-06)
**Notes:** Flip ambiguity only exists because iTrader sizes from a policy; a cover signal has no opening sizing basis. Clamp-to-flat keeps one-signal-one-intent (freqtrade discipline); single-order flip belongs as an explicit-quantity close+open split (Nautilus `_flip_position`) later.

---

## Short enablement & PnL (SHORT-01, SHORT-03)

### Registration guard relaxation

| Option | Description | Selected |
|--------|-------------|----------|
| Require allow_short_selling AND enable_margin | Both flags required | ✓ |
| Gate on allow_short_selling only | Independent of enable_margin | |
| You decide | — | |

**User's choice:** Require both flags (D-07)
**Notes:** User confirmed `enable_margin=True` + leverage 1 = fully-collateralized shorts (no leverage), leverage being a separate opt-in dial. `enable_margin` (lock-and-settle) is structurally required because a short has no notional to spend.

### Where "minus carry" applies

| Option | Description | Selected |
|--------|-------------|----------|
| Carry separate at cash/equity level | `Position.realised_pnl` stays clean trade PnL | ✓ |
| Fold carry into Position.realised_pnl | Position reports PnL-net-of-carry | |
| You decide | — | |

**User's choice:** Carry separate at cash/equity level (D-08)

---

## P2 residuals & proof scope

### Phase-2 margin-hardening residuals

| Option | Description | Selected |
|--------|-------------|----------|
| Fold into this phase's plans | WR-01/03/04/05 (+WR-02) integral to shorts work | ✓ |
| Separate hardening slice/plan | Dedicated plan, separate attribution | |
| You decide | — | |

**User's choice:** Fold into this phase's plans (D-09)
**Notes:** Single FRAGILE-seam touch under the P4/XVAL-01 gate.

### Proof / scenario set

| Option | Description | Selected |
|--------|-------------|----------|
| Component tests + parked short e2e set | Full component coverage + parked pure-short / short+carry / partial-cover scenarios | ✓ |
| Component tests only; defer all e2e to P4 | No parked scenarios this phase | |
| You decide | — | |

**User's choice:** Component tests + parked short e2e set (D-10)
**Notes:** Phase 3 freezes no golden; parked scenarios hand-verified, frozen only at P4/XVAL-01.

---

## Claude's Discretion

- Placement of the per-bar carry-accrual call + `last_accrual` bookkeeping.
- `BORROW_INTEREST` op-type name/enum member + serializer wiring.
- `resolve_exit` generalization signature for the side-agnostic branch.
- The BTCUSD `Instrument.borrow_rate` value for parked scenarios (oracle-dark).
- Plan decomposition/sequencing of shorts vs WR residuals within the single seam touch.

## Deferred Ideas

- Single-order flips (explicit close+open split, Nautilus `_flip_position`) — future explicit-quantity feature.
- Time-varying borrow-rate series (Phase-B sibling of the funding-data pipeline).
- Liquidation force-close trigger (LIQ-01) → Phase 4; DEF-01-C open until then.
- Cross-validation + golden re-baseline freeze (XVAL-01) → Phase 4.
- Per-instrument MMR table (IN-03) → Phase 4; IN-01/IN-02 doc nits → future.
- Funding / mark-price / perp realism → Phase B / N+4.
- Pair-trading flagship (PAIR-01) → Phase 6.
