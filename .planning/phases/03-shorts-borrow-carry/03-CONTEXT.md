# Phase 3: Shorts & Borrow Carry - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Enable **first-class short positions** in backtest, built on the Phase-2 margin
accounting core. Four deliverables (SHORT-01/02/03, CARRY-01):

- **SHORT-01** — relax the `LONG_ONLY` registration guard in
  `StrategiesHandler.add_strategy` so `SHORT_ONLY` / `LONG_SHORT` strategies are
  admissible, **gated on `allow_short_selling` AND `enable_margin`**.
- **SHORT-02** — fix the **v1.0 M5b CR-01 cover-arm hole** in
  `_resolve_signal_quantity`: a BUY-to-cover on an open short must **reduce/close**
  the short, not fall through to entry sizing and flip the book long.
- **SHORT-03** — **first-class short PnL** (`|size| × (entry − exit)` minus carry),
  modeled as a real direction (the `Position` `PositionSide.SHORT` PnL branches
  already exist; carry nets at the cash/equity level).
- **CARRY-01** — **borrow-interest accrual** on open shorts
  (`days × price × |size| × rate/365`), one parameter, no data feed.

Plus the **Phase-2 margin-hardening review residuals** (WR-01/03/04/05 + WR-02)
that become *reachable* once shorts/levered entries lock margin on the run path —
folded into this phase so the FRAGILE margin/settlement seam is touched **once**.

**Re-baseline discipline:** Phase 3 is part of the **accounting core** whose
golden master re-baselines **once, at Phase 4 / XVAL-01** (cross-validation +
owner sign-off). Phase 3 freezes **no** new golden itself — it holds SMA_MACD
byte-exact (shorts are oracle-dark: the golden strategy is LONG_ONLY) and **parks**
hand-verified short scenarios for the P4 freeze.

**In scope:** registration-guard relaxation (two-flag gated); side-agnostic
cover-arm exit + clamp-to-flat over-cover; per-instrument `borrow_rate`; per-bar
borrow-interest accrual booked to realized cash via a new `BORROW_INTEREST`
CashOperation; short PnL wiring (carry separate from `Position.realised_pnl`);
WR-01/03/04/05 (+WR-02) residual hardening; component/unit tests + a parked
short e2e set.

**Out of scope (later phases / deferred):** the **liquidation force-close
trigger** (Phase 4, LIQ-01 — DEF-01-C stays open until then); cross-validation +
the **golden re-baseline freeze** (Phase 4 / XVAL-01); **single-order flips**
(close+open split — deferred explicit-quantity feature); a **time-varying
borrow-rate series** (Phase B sibling of the funding-data pipeline); funding /
mark-price / perp realism (Phase B / N+4); the pair-trading flagship (Phase 6).

</domain>

<decisions>
## Implementation Decisions

### Borrow-carry model (CARRY-01)
- **D-01 — rate source: per-instrument.** Add `borrow_rate: Decimal = 0` to
  `core/instrument.py` alongside `maintenance_margin_rate` / `max_leverage`
  (the INST-03 risk fields). This mirrors how crypto venues actually attribute
  borrow cost (Binance Margin / Bitfinex / Kraken price borrow **per asset**;
  equities price cost-to-borrow per ticker). The `Universe` read-model already
  resolves `symbol → Instrument`. Default `0` = carry-off → spot golden
  byte-exact. NOT a portfolio-wide blanket rate (unrealistic — no venue does
  that). The static-over-time simplification is the documented approximation
  (a borrow-rate time-series is the Phase-B realism extension).
- **D-02 — accrual: per-bar on close, to realized cash.** Each BAR, accrue
  `days × close_price × |size| × rate/365` on open shorts inside
  `update_portfolios_market_value` and **debit realized cash incrementally**.
  Matches backtrader's reference model; carry is visible in the equity curve as
  it accrues; deterministic (bar close + injected `BacktestClock`); the P4
  liquidation trigger sees carry-eroded equity. NOT lump-sum-at-close (equity
  would ignore the drag while the short is open → P4 under-counts it).
- **D-03 — ledger: new `BORROW_INTEREST` CashOperation type.** Book the per-bar
  carry debit as a dedicated, first-class `CashOperation` kind (distinct from
  trade debits/credits) so the financing-cost drag is an auditable, attributable
  line in the `reporting/cash_operations.py` lens — needed for clean
  cross-validation at P4. Mirrors how fees/reservations got their own lifecycle
  entries.
- **D-04 — "days" basis: elapsed between bar timestamps.** Derive `days` from the
  gap between consecutive bar times via the injected `BacktestClock`
  (`(this_bar.time − last_accrual.time)` in days). Correct on the daily grid
  (=1) AND robust to data gaps / non-daily timeframes; deterministic, no
  hardcoded interval. NOT a fixed per-bar = timeframe assumption.

### Cover-arm & flip economics (SHORT-02 + CR-02-residual)
- **D-05 — side-agnostic exit (cover-arm fix).** In `_resolve_signal_quantity`,
  detect a reduction **once** as "order action opposes the open position's side"
  — `SELL` vs long OR `BUY` vs short both route through `resolve_exit`. This is
  how a **netting engine** (NautilusTrader: order effect derived from
  `order_side` vs `position_side`, not inferred from a policy) decides an order's
  effect — the most architecturally correct fit for iTrader's signed-`Position`
  model, and strictly more principled than a second near-duplicate branch. The
  long-exit path stays **byte-exact** (same code, generalized).
- **D-06 — over-cover: clamp-to-flat now; single-order flip deferred as an
  explicit close+open split.** A cover BUY exceeding the open short sizes to
  exactly `|net_quantity|` (close to flat); the excess does **NOT** auto-open a
  long. Rationale: the flip ambiguity only exists because iTrader **sizes from a
  policy** — a cover signal carries an `exit_fraction` (reduction intent) with
  **no opening sizing basis** for the opposite side, so "close AND open size X"
  conflates two sizing intents. This matches freqtrade's exit-then-enter
  discipline. A true single-order flip belongs as an explicit-quantity
  **close+open split** at the fill/position layer (the Nautilus `_flip_position`
  pattern: split into a close-leg that realizes full PnL + an open-leg as a fresh
  position) — **deferred**, not the resolver's job. Resolves the Phase-2
  CR-02-residual via clamp-to-flat; aligns with the Phase-2 CR-02-guard (already
  raises on over-close).

### Short enablement & PnL (SHORT-01, SHORT-03)
- **D-07 — registration guard: require `allow_short_selling` AND `enable_margin`.**
  Admit non-`LONG_ONLY` strategies only when **both** config flags are on.
  `enable_margin` turns on the lock-and-settle model (D-09 Phase 2) — the only
  model that can represent a short (a short has no notional to "spend"; spot
  debit-notional cannot express it; P4 liquidation needs maintenance margin).
  Leverage stays a **separate dial defaulting to 1**, so this gives
  **fully-collateralized shorts (no leverage) by default** (`locked_margin =
  notional / 1` = full notional); **levered** shorts are an opt-in
  (`max_leverage > 1` + `signal.leverage > 1`). Both flags default off → oracle
  byte-exact.
- **D-08 — carry nets at the cash/equity level, not inside `Position`.**
  `Position.realised_pnl` stays the clean trade PnL
  (`|size| × (avg_sold − avg_bought)` via the existing `PositionSide.SHORT`
  branch); borrow carry is the separate per-bar `BORROW_INTEREST` cash debit
  (D-02/D-03). "PnL minus carry" therefore nets out at realized-cash / equity —
  one carry code path, and trade-PnL vs financing-cost attribution stays clean
  for cross-validation. NOT folded into `Position.realised_pnl` (would create a
  second carry site).

### Phase-2 residuals & proof scope (carry-forward + milestone discipline)
- **D-09 — fold the WR residuals into this phase's plans.** WR-01 (settlement-side
  solvency assertion that the locked margin fits buying power), WR-03 (lock-release
  symmetry at the assembly-failure site), WR-04 (`≥1` leverage floor + zero guard
  on `_effective_leverage`), WR-05 (per-lock open-commission accumulator), and
  WR-02 (universe-unwired `None` guard → fail-loud `StateError`, spans P3/P4) are
  hardened **as integral parts of the shorts work** — they guard the exact
  margin-lock paths shorts newly exercise. Bundling keeps the FRAGILE
  margin/settlement seam touched **once** under the single P4/XVAL-01 owner-gated
  re-baseline, not twice. (IN-03 per-instrument MMR table → Phase 4; IN-01/IN-02
  doc/convention nits → future.)
- **D-10 — proof: component tests + a parked short e2e set; freeze only at P4.**
  Build thorough component/unit tests (side-agnostic cover-arm, clamp-to-flat
  over-cover, carry accrual / days-basis / `BORROW_INTEREST` op, short PnL,
  two-flag registration gating, each WR residual fix) **AND** parked,
  hand-verified integration/e2e scenarios: **pure short round-trip**,
  **short-with-carry**, **partial cover**. These are **parked** (hand-verified in
  a VERIFY note, NOT `--freeze`d) and frozen as golden **only at Phase 4 /
  XVAL-01** under cross-validation + owner sign-off. SMA_MACD held byte-exact
  throughout; `mypy --strict` clean; Decimal end-to-end (carry formula included);
  determinism double-run byte-identical.

### Claude's / Planner's Discretion
- Exact placement of the per-bar carry-accrual call within
  `update_portfolios_market_value` (per-portfolio vs per-position loop) and the
  `last_accrual` timestamp bookkeeping site.
- The `BORROW_INTEREST` op-type name/enum member and its `cash_operations.py`
  serializer wiring.
- The precise `resolve_exit` generalization signature for the side-agnostic
  branch (how the opposing-side magnitude is passed).
- The BTCUSD `Instrument.borrow_rate` value used for the parked short scenarios
  (oracle-dark; a realistic crypto default).
- Plan decomposition / sequencing of the shorts feature vs the WR residual fixes
  within the single FRAGILE-seam touch.
- Indentation: tabs in `portfolio_handler/`, `order_handler/`,
  `strategy_handler/`, `execution_handler/`; 4 spaces in `core/`, `config/` —
  match the file.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone discipline
- `.planning/REQUIREMENTS.md` — SHORT-01/02/03, CARRY-01 (the locked Phase 3
  requirements); the owner-gated/result-changing milestone discipline.
- `.planning/ROADMAP.md` — v1.4 Phase 3 entry + Phase Details (success criteria);
  the Phase-3 **Carry-forward (Phase 2 review residuals)** block listing
  CR-02-residual + WR-01/03/04/05 + WR-02/IN-03; the "Owner-gated phases (2/3/4)"
  re-baseline block; the Phase 4 XVAL-01 gate.
- `.planning/STATE.md` — "Milestone Gate (v1.4)" → the owner-gated accounting-core
  block: **one** re-baseline at P4/XVAL-01; oracle 134 / `46189.87730727451`;
  determinism + Decimal + mypy held all phases; CR-01 cover-arm (P3) note.

### Design source
- `.planning/notes/margin-leverage-shorts-999.4.md` — §6 item 4 (short
  enablement: LONG_ONLY guard + CR-01 cover-arm + first-class direction), item 5
  (borrow-interest carry `days × price × |size| × rate/365`, backtrader the
  reference), §4 (spot-margin vs perp: short PnL `|size| × (entry − exit)` −
  interest; carry = borrow interest, a parameter not a dataset), §7 (data
  flow — a short, end to end; Decimal/determinism/validation), §8 (Phase-B
  deferrals — funding/mark-price/time-varying rate).

### Carried-forward phase context
- `.planning/phases/02-margin-accounting-leverage/02-CONTEXT.md` — D-09
  lock-and-settle (the only model supporting shorts), D-10 position-keyed locked
  margin in `CashManager`, D-11 pro-rata scale-in/out, D-13 compute-on-demand
  maintenance margin, D-03/D-04 leverage rides `SignalEvent` + the cap
  (`min(signal, Instrument.max_leverage, portfolio.max_leverage)`, forced to 1
  when `enable_margin` off), D-16 the P2/P4 pre-liquidation boundary.
- `.planning/phases/02-margin-accounting-leverage/deferred-items.md` — the
  "Code review residuals (02-REVIEW.md)" table: CR-02-residual (clamp-to-flat
  resolves it, D-06) + WR-01/03/04/05 + WR-02 + IN-01/02/03 with severity +
  target (the D-09 fold-in list).
- `.planning/phases/01-instrument-value-object/01-CONTEXT.md` — the `Instrument`
  value object + the `Universe` read-model façade that resolves `symbol →
  Instrument` (the seam `borrow_rate` is added to and read through).

### Code to change / mirror
- `itrader/strategy_handler/strategies_handler.py:253` — the `LONG_ONLY`
  registration guard (D-07: two-flag relaxation).
- `itrader/order_handler/admission/admission_manager.py` — `_resolve_signal_quantity`
  (~637; the side-agnostic cover-arm + clamp-to-flat, D-05/D-06); the existing
  symmetric direction-admission gate `_enforce_direction_admission` (~410, already
  handles SHORT_ONLY).
- `itrader/order_handler/sizing_resolver.py` — `resolve_exit` (the no-op exit
  sizing the side-agnostic branch reuses).
- `itrader/core/instrument.py` — add `borrow_rate: Decimal = 0` (D-01).
- `itrader/portfolio_handler/portfolio_handler.py:417` —
  `update_portfolios_market_value` (the per-bar carry-accrual hook, D-02).
- `itrader/portfolio_handler/cash/cash_manager.py` — the realized-cash debit path
  for carry; the position-keyed locked-margin container (P2 D-10) + WR-01/03/05
  hardening.
- `itrader/portfolio_handler/position/position.py:169` — `realised_pnl` /
  `unrealised_pnl` (existing `PositionSide.SHORT` branches; stays clean, D-08).
- `itrader/reporting/cash_operations.py` + the `CashOperation` enum — the new
  `BORROW_INTEREST` op type (D-03).
- `itrader/config/portfolio.py` — `TradingRules` (`allow_short_selling`,
  `enable_margin`, `max_leverage`) — read by the D-07 guard.

### External-framework reference (verified during discussion)
- NautilusTrader (installed, `.venv/.../nautilus_trader/`): `model/position.pyx`
  (signed `Position`, side from order side) + `execution/engine.pyx`
  (`_will_flip_position` / `_flip_position` close+open split, `reduce_only`) — the
  netting + flip-split pattern D-05/D-06 mirror.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Position.realised_pnl` / `unrealised_pnl` (`position/position.py:169/195`) —
  **already branch on `PositionSide.SHORT`** (`(avg_sold − avg_bought) ×
  buy_quantity`); SHORT-03 builds on existing first-class-direction PnL, not from
  scratch.
- `_enforce_direction_admission` (`admission_manager.py:410`) — the admission
  gate **already handles `SHORT_ONLY` symmetrically** (rejects BUY with no open
  short at :464); the remaining block is the *registration* guard in
  `strategies_handler` (D-07).
- `resolve_exit` (`sizing_resolver.py:147`) — the proven exit-sizing no-op the
  side-agnostic cover branch reuses (D-05).
- `CashManager.reserve_cash` / `release_reservation` + the P2 position-keyed
  locked-margin container — the realized-cash and margin-lifecycle mechanism carry
  + WR residuals extend.
- `reporting/cash_operations.py` — the determinism-safe `CashOperation` ledger
  lens the new `BORROW_INTEREST` op slots into (D-03).
- The injected `BacktestClock` — the deterministic time source for the D-04 days
  basis.

### Established Patterns
- **Netting / signed-`Position` model** — one `Position` per ticker/portfolio with
  signed `net_quantity`; an order's effect = (order side vs position side). D-05's
  side-agnostic exit is the principled expression of this (Nautilus parallel).
- **Byte-exact gate via default-off** — `allow_short_selling=False` /
  `enable_margin=False` / `borrow_rate=0` keep SMA_MACD byte-exact; all new
  behavior is gated and oracle-dark.
- **Compute/accrue at the read/cash edge, not stored mutable state** — carry
  books to the cash ledger; `Position` PnL stays clean (D-08), mirroring P2 D-13
  compute-on-demand maintenance margin.
- **Decimal end-to-end** — the carry formula (`days × price × |size| × rate/365`)
  stays Decimal; `float()` only at the serialization/logging edge.
- **FRAGILE seam, single touch** — the margin/settlement path is touched once
  this phase (shorts + WR residuals together) under the P4/XVAL-01 gate (D-09).

### Integration Points
- `Instrument` gains `borrow_rate`; the `Universe` read-model surfaces it per
  symbol; `update_portfolios_market_value` reads it per open short each bar.
- `_resolve_signal_quantity` gains the side-agnostic exit + clamp-to-flat;
  `strategies_handler.add_strategy` gains the two-flag relaxation.
- `CashManager` gains the per-bar `BORROW_INTEREST` debit; `CashOperation` /
  `cash_operations.py` gain the new op type.
- WR-01/03/04/05 + WR-02 land on the P2 margin-lock / `_effective_leverage` /
  maintenance-margin read paths.

</code_context>

<specifics>
## Specific Ideas

- The user pushed hard on **architectural correctness over expedience**, asking
  explicitly how NautilusTrader / QuantConnect LEAN / freqtrade model
  direction-changing orders before choosing — which is why the cover-arm fix is
  the **side-agnostic netting** form (D-05) and the over-cover is **clamp-to-flat
  with the flip deferred as an explicit close+open split** (D-06, the Nautilus
  `_flip_position` pattern), not an in-place mutation.
- The user verified that **per-instrument borrow rate mirrors reality** (crypto
  venues + equities both attribute borrow cost per asset) before locking D-01.
- The user confirmed understanding that **`enable_margin=True` + leverage 1 =
  fully-collateralized shorts (no leverage)** — leverage is a separate opt-in
  dial — which is why the registration guard couples both flags (D-07).

</specifics>

<deferred>
## Deferred Ideas

- **Single-order flips (explicit close+open split)** — the Nautilus
  `_flip_position` pattern (split a fill into a full-close leg that realizes PnL +
  a fresh open leg), driven by an **explicit quantity** at the fill/position
  layer, NOT inferred by the policy resolver. Out of Phase 3 (clamp-to-flat now,
  D-06); a deliberate future feature if explicit-quantity flips are wanted.
- **Time-varying borrow-rate series** — a per-symbol borrow-rate time-series
  (CSV alongside OHLCV), the realism extension of the static D-01 parameter;
  sibling of the deferred Phase-B funding-data pipeline.
- **Liquidation force-close trigger (LIQ-01)** — Phase 4; DEF-01-C stays open
  until then (P2 D-16).
- **Cross-validation + golden re-baseline freeze (XVAL-01)** — Phase 4; Phase 3
  parks scenarios, freezes nothing (D-10).
- **Per-instrument MMR table (IN-03)** — Phase 4 declares it before liquidation
  consumes `margin_ratio`.
- **IN-01 / IN-02** — doc/convention nits (`fill.py` comment trim; `to_money`
  house-helper use) — future, doc-only.
- **Funding / mark-price / perp realism** — Phase B / N+4.
- **Pair-trading flagship (PAIR-01)** — Phase 6 (the first real use of the short
  side; additive, NOT the correctness oracle).

None outside phase scope were raised that aren't already tracked above.

</deferred>

---

*Phase: 3-Shorts & Borrow Carry*
*Context gathered: 2026-06-15*
