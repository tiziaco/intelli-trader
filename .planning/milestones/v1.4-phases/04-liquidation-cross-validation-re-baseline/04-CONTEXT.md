# Phase 4: Liquidation & Cross-Validation Re-baseline - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Close **DEF-01-C** — a position breaching maintenance margin on bar close is
**force-closed via a `FillEvent`** (loss floored at allocated isolated margin +
a configurable penalty), reconciling through the existing position/cash/order-mirror
path — AND **cross-validate** the margin/shorts/liquidation accounting core and
**freeze its golden master** under owner sign-off. Four deliverables
(LIQ-01/02/03, XVAL-01):

- **LIQ-01** — per-bar (bar-close) maintenance-margin breach check; force-close
  the breaching position via a `FillEvent`, loss floored at the position's
  allocated isolated margin (equity can no longer drift impossibly negative).
- **LIQ-02** — a configurable liquidation penalty/fee so liquidation PnL is not
  optimistic.
- **LIQ-03** — forced liquidation reuses `FillStatus.EXECUTED`, mints an
  admission-bypassing close order tagged a NEW `OrderTriggerSource.LIQUIDATION`,
  reconciling through the existing path with **no new `FillStatus`**.
- **XVAL-01** — short, leveraged-long, and liquidation scenarios cross-validated
  against `backtesting.py`/`backtrader`; the new accounting-core golden master
  freezes ONLY after explicit owner sign-off with full attribution.

Plus the **carry-forward review residuals → Phase 4**: WR-04 (the
`assert_lock_fits_buying_power` call-order fix) and IN-03 (per-instrument
maintenance-margin-rate, already on `Instrument` since P1 — confirm sufficient).

**Re-baseline discipline:** Phase 4 is the **single owner-gated accounting-core
golden re-baseline** the whole milestone was structured around. The crafted,
hand-computable, adversarial scenarios (pure short, leveraged long, forced
liquidation) are the **correctness oracle** — NOT pair trading (Phase 6). The
accounting core (margin P2 + shorts P3 + liquidation P4) re-baselines **once**,
here, under XVAL-01 (cross-validation + owner sign-off). The SMA_MACD spot oracle
(134 trades / `46189.87730727451`) stays **byte-exact** (oracle-dark: LONG_ONLY
spot, margin/shorts/liquidation default-off).

**In scope:** the bar-close per-position liquidation trigger + isolated
liquidation-price formula; the forced-close `FillEvent` minted on the BAR route;
`OrderTriggerSource.LIQUIDATION`; the `liquidation_fee_rate` (Instrument + config
fallback) and the %-of-notional penalty capped at allocated margin; WR-04 + IN-03
carry-forward; component/unit tests; the new crafted liquidation e2e scenarios;
freezing ALL parked P2/P3 + new P4 scenarios as the accounting-core golden; an
accounting-core cross-validation evidence doc + owner sign-off.

**Out of scope (later phases / deferred):** mark-price liquidation trigger and
`freqtrade` as a 4th oracle (Phase B / N+4); cross-margin / account-wide joint
liquidation (beyond Phase B); tiered MMR brackets (schema wired, table deferred);
engine-native trailing stops (Phase 5); the pair-trading flagship (Phase 6);
single-order flips (deferred explicit-quantity feature).

</domain>

<decisions>
## Implementation Decisions

### Liquidation trigger (LIQ-01)
- **D-01 — per-position liquidation PRICE, breach on bar close.** Detect a breach
  by computing each position's isolated liquidation price (design-note §6:
  `Long Liq = Entry×(1 − (WB/size)/L)/(1+MMR)`, short mirrored; `WB` = that
  position's allocated isolated margin) and flagging when the **bar close** crosses
  it. This is the **most realistic** model (matches what real isolated-margin
  venues publish, and `freqtrade` — the only backtest framework that models
  liquidation — computes a per-position liquidation price), and it is closed-form
  **hand-computable** for XVAL. Bar-close as the trigger **instant** (vs mark
  price) is the single deliberate simplification (locked: no mark feed on daily
  OHLCV; avoids phantom-wick liquidations). NOT the portfolio-aggregate
  `margin_ratio` read-model (that pools positions → cross-margin behavior,
  contradicts isolated).
- **D-02 — multiple breaches: each liquidates independently, deterministic order.**
  When several positions breach the same bar, liquidate each **independently** in a
  fixed deterministic order (e.g. by symbol then open-time — planner's discretion).
  True isolated margin: one liquidation never changes another's trigger (each liq
  price depends only on its own bucket). A "liquidate, re-mark, re-check" loop is
  **cross-margin** behavior (deferred). Ordering affects only the cash-ledger
  *sequence*, not any outcome — but it must be fixed for the byte-identical
  double-run.

### Fill price & loss floor (LIQ-01)
- **D-03 — forced close settles AT the computed liquidation price.** The
  forced-close `FillEvent` executes at the liquidation price from D-01, so realized
  loss = the position's allocated isolated margin **by construction** — the floor
  is automatic, **no clamp** needed. This is freqtrade's model and the most
  realistic for isolated liquidation ("you lose your margin, no more"); trivially
  hand-computable for XVAL. (Tradeoff accepted: a computed price can be better than
  the observed close on a gap-through bar — slightly optimistic, but consistent
  with the isolated "max loss = margin" reality.) NOT bar-close + clamp; NOT
  bar-close uncapped (the latter reopens DEF-01-C).

### Liquidation emission mechanism (LIQ-03)
- **D-04 — the portfolio-side liquidation engine mints the `FillEvent` directly on
  the BAR route.** Liquidation lives in **portfolio/cash accounting**, NOT the
  `MatchingEngine` (locked, design-note §5: it is an *equity* event, not an order
  fill). The breach check in `update_portfolios_market_value` detects the breach,
  mints an **admission-bypassing** forced-close order tagged a new
  `OrderTriggerSource.LIQUIDATION`, computes the penalty itself, and **emits
  `FillEvent(EXECUTED)` directly** with the penalty in the existing `commission`
  field. It does **NOT** round-trip through `ExecutionHandler`/exchange — that path
  fills at next-bar-open, but a liquidation must settle at the liq price on the
  **breach bar**. The `FillEvent` is consumed by `portfolio.on_fill` (settle) +
  `order_handler.on_fill` (mirror reconcile: EXECUTED→FILLED) with **no new
  `FillStatus`**. Conceptually: iTrader's portfolio-side liquidation engine plays
  the role the exchange's liquidation engine plays on a real venue.

### Liquidation penalty (LIQ-02)
- **D-05 — penalty basis: % of notional.** Penalty = `liquidation_fee_rate ×
  |size| × liq_price`. Most realistic (Binance/Bybit charge a liquidation
  clearance fee as a rate on notional); scales with position size;
  cross-validatable. NOT a flat fee (doesn't scale) or %-of-margin (not how venues
  quote it).
- **D-06 — rate home: `Instrument`-first + config fallback.** Add
  `liquidation_fee_rate` to `core/instrument.py` (default unset) alongside
  `maintenance_margin_rate` / `max_leverage` / `borrow_rate`, resolved via the
  `Universe` read-model; fall back to a config-level default for undeclared
  symbols. Mirrors P1 `min_order_size` (Instrument-first, `ExchangeLimits`
  fallback) and P3 `borrow_rate`. Gives **one-knob ergonomics** (set the fallback
  default, declare no per-symbol overrides) with **zero realism loss** and no
  rework later; avoids the asymmetry of an account-wide fee next to per-instrument
  MMR. Default 0 = oracle-dark.
- **D-07 — penalty consumes the maintenance buffer, total loss CAPPED at allocated
  isolated margin.** At the liq price the position retains the maintenance buffer
  (the formula's `/(1+MMR)` term); the penalty is deducted **within** the margin
  envelope and total realized loss is **capped at the allocated isolated margin**
  (never exceeds it). Most realistic (max loss = isolated margin; the clearance fee
  eats the buffer, the insurance fund covers any excess) and keeps DEF-01-C closed
  while satisfying LIQ-02 (PnL not optimistic). NOT charged-on-top-uncapped (would
  reopen impossible-negative-equity).

### Cross-validation & freeze (XVAL-01)
- **D-08 — liquidation oracle: hand-computed primary, engines corroborate.** The
  hand-computed closed-form (liq price + penalty + floored loss) is the **PRIMARY
  oracle** for the liquidation event (asserted in the e2e). `backtesting.py` /
  `backtrader` **fully cross-validate** the short & leveraged-long scenarios (which
  they model: shorts, `margin = 1/L`) and the pre-liquidation accounting path, and
  give **directional corroboration** on liquidation (e.g. `backtesting.py`'s
  `equity ≤ 0 → close-all` confirms the leveraged-long-into-liquidation scenario
  liquidates). They are NOT expected to byte-match the isolated formula. Mirrors
  the existing `CROSS-VALIDATION.md` trade-level + metric-level discipline.
- **D-09 — `freqtrade` ruled out for Phase 4.** It is **NOT installed** (verified:
  absent from `pyproject.toml`/`poetry.lock`, not importable — the design note's
  "installed-ecosystem framework" claim is inaccurate); adding it = a heavyweight
  new dependency. It is also **circular** (we copy freqtrade's isolated liquidation
  formula, so validating against it only proves we copied it correctly — the
  hand-computed closed-form is the stronger *independent* oracle), and it is
  explicitly slotted as the **Phase-B** oracle for **funding** (which
  `backtesting.py`/`backtrader` genuinely cannot validate). XVAL-01 names only
  `backtesting.py` + `backtrader`.
- **D-10 — freeze set: ALL parked P2/P3 scenarios + new P4 liquidation scenarios.**
  Freeze the previously-parked-but-unfrozen Phase 2 (leveraged-long e2e) and Phase
  3 (pure-short round-trip, short-with-carry, partial-cover) scenarios **together
  with** the new Phase 4 liquidation scenarios (forced-liq long, forced-liq short,
  leveraged-long-into-liquidation) as the **single accounting-core golden** under
  one owner-gated sign-off. NOT only the P4 scenarios (would split the oracle and
  leave the short/leveraged scenarios permanently parked).
- **D-11 — SMA_MACD stays byte-exact, untouched.** SMA_MACD is LONG_ONLY spot with
  margin/shorts/liquidation default-OFF → oracle-dark, **unchanged**. "Re-baseline"
  here means **freezing NEW crafted accounting-core goldens for the first time**,
  NOT changing SMA_MACD. `tests/golden/{trades,equity,summary}` stay byte-identical
  and `tests/integration/test_backtest_oracle.py` still asserts
  134 / `46189.87730727451`. The byte-exact hold is part of the phase gate.
- **D-12 — owner sign-off: reuse the established pattern.** XVAL-01's "explicit
  owner sign-off with full attribution" reuses the existing discipline: a **blocking
  human-verify checkpoint** + a **new accounting-core cross-validation evidence
  doc** (the existing `tests/golden/CROSS-VALIDATION.md` is SMA_MACD-specific — write
  a sibling for the accounting-core scenarios) carrying a per-scenario reconciliation
  table + an **Owner Sign-Off** section (mirroring `CROSS-VALIDATION.md`'s sign-off
  block). The freeze happens ONLY after that sign-off.

### Claude's / Planner's Discretion
- The exact deterministic tiebreak ordering for D-02 multi-breach (symbol /
  open-time / position-id), and the precise placement of the liquidation check
  within `update_portfolios_market_value` (before/after the P3 carry accrual).
- The `OrderTriggerSource.LIQUIDATION` member value string and its trade-log /
  metrics filtering wiring.
- The crafted-scenario shape/count and where they live in the test tree
  (`tests/e2e/<scenario>/` dirs, mirroring the parked P2/P3 e2e layout).
- The BTCUSD `Instrument.liquidation_fee_rate` value + the config-level fallback
  default used for the crafted scenarios (realistic crypto defaults; oracle-dark).
- WR-04 fix shape (assert before release, or thread the released amount into
  `assert_lock_fits_buying_power`) and whether IN-03 needs more than the existing
  per-instrument `maintenance_margin_rate`.
- The new accounting-core cross-validation doc's filename/location and the
  crossval-runner additions (short / leveraged-long / liquidation variants of the
  `scripts/crossval/` runners + `scripts/cross_validate.py`, following the v1.3
  `_limit` precedent).
- Indentation: tabs in `portfolio_handler/`, `order_handler/`, `execution_handler/`,
  `strategy_handler/`; 4 spaces in `core/`, `config/`, `events_handler/events/` —
  match the file, never normalize.

### Planning-time correction (owner-authorized 2026-06-16, via Phase 4 research)
- **D-01-CORR — the D-01 formula string is a transcription error; use the
  freqtrade-canonical isolated form.** `Entry×(1−(WB/size)/L)/(1+MMR)` as literally
  written yields a NEGATIVE price (hand-verified in a Decimal harness: −297.03 for
  Entry=100, L=5, MMR=0.01) because `WB/size` already equals `Entry/L` (the extra
  `/L` double-counts leverage) and `(1+MMR)` has the wrong sign for a long. The
  CORRECT formula (WB = the position's allocated isolated margin from the
  `CashManager` locked-margin container):
  - **Long:** `liq_price = (entry − WB/|size|) / (1 − MMR)`
  - **Short:** `liq_price = (entry + WB/|size|) / (1 + MMR)`
  - Worked (Entry=100, size=200, L=5 → WB=4000, MMR=0.01): **long 80.8080…, short
    118.8118…**. These corrected numbers are the e2e oracle + golden master.
- **D-03-CORR — the loss floor is NOT automatic; D-07's cap is an explicit clamp.**
  D-03's "loss == allocated margin by construction, no clamp needed" is exact only
  at the bankruptcy price (MMR=0). At the maintenance liq price the position retains
  a `/(1−MMR)` buffer (realized loss −3838.38, not −4000 for the worked long); D-05's
  %-of-notional penalty consumes that buffer, and total realized loss is capped via
  an **explicit** `total_realized_loss = min(realized_loss + penalty, WB)` (a fat
  penalty or deep MMR can push past WB → the clamp guards the tail and keeps DEF-01-C
  closed). D-03's "no clamp" wording is superseded by D-07's cap.
- **IN-03 (clarification, not a change):** the existing per-instrument
  `Instrument.maintenance_margin_rate` (INST-03, read by `maintenance_margin`)
  already satisfies the LIQ MMR need — no new field. The `deferred-items.md` "IN-03"
  is a *different* (carry-gap) item; do not conflate the label.
- **LIQ-03 mechanism (clarification):** the forced-close engine mints and persists a
  REAL `Order` (tagged `OrderTriggerSource.LIQUIDATION`) in `order_storage` so the
  mirror's `on_fill` reconcile (EXECUTED→FILLED) fires — `ReconcileManager.on_fill`
  early-returns if the fill's `order_id` is unknown, so a real registered Order is
  required to keep LIQ-03's "reconciles through the existing path" literally true.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone discipline
- `.planning/REQUIREMENTS.md` — LIQ-01/02/03, XVAL-01 (the locked Phase 4
  requirements); the owner-gated/result-changing milestone discipline; the
  Traceability table.
- `.planning/ROADMAP.md` — v1.4 Phase 4 entry + Phase Details (success criteria);
  the Phase-4 **Carry-forward (review residuals → Phase 4)** block (WR-04 + IN-03);
  the "Owner-gated phases (2/3/4)" re-baseline block; the locked liquidation /
  no-new-FillStatus / Instrument-metadata scoping decisions in the 999.4 block.
- `.planning/STATE.md` — "Milestone Gate (v1.4)" → the owner-gated accounting-core
  block: **one** re-baseline at P4/XVAL-01; oracle 134 / `46189.87730727451`;
  determinism + Decimal + mypy held all phases; the "FillEvent forced-close shape"
  + "correctness oracle = crafted scenarios" blockers/concerns.

### Design source
- `.planning/notes/margin-leverage-shorts-999.4.md` — §3 (mark price & why
  bar-close is the honest proxy), §4 (spot-margin vs perp comparison table:
  liquidation trigger = bar close, formula `Entry×(1−(WB/size)/L)/(1+MMR)`), §5
  (where liquidation lives — portfolio/cash accounting on the BAR route, NOT the
  MatchingEngine; reference designs adopted — freqtrade formula, backtesting.py
  minimal liquidation), §6 item 3 (Liquidation component: isolated margin, flat
  per-instrument MMR, configurable penalty, force-close via FillEvent), §7 (data
  flow — a short end to end; Decimal/determinism), §8 (Phase-B deferrals:
  funding, mark-price trigger, freqtrade 4th oracle, cross-margin), §9 Q2
  (FillEvent forced-close shape — resolved by D-04 here).

### Cross-validation reference (existing harness to extend)
- `tests/golden/CROSS-VALIDATION.md` — the SMA_MACD cross-validation evidence doc:
  the trade-level (PRIMARY) + metric-level (SECONDARY) reconciliation discipline,
  the apples-to-apples metrics boundary, the per-divergence root-cause +
  disposition format, and the **Owner Sign-Off** block — the template for the new
  accounting-core cross-validation doc (D-12).
- `scripts/cross_validate.py` + `scripts/crossval/` — the existing crossval driver
  + per-engine runners (`backtesting_py_run.py`, `backtrader_run.py`,
  `nautilus_run.py`, `reconcile.py`, `indicators.py`) and the v1.3 `_limit`
  variants (`*_limit_run.py`, `cross_validate_limit.py`) — the precedent for
  adding short / leveraged-long / liquidation scenario runners.
- `tests/integration/test_backtest_oracle.py` — asserts the byte-exact SMA_MACD
  oracle (134 / `46189.87730727451`) that must hold (D-11).

### Carried-forward phase context
- `.planning/phases/03-shorts-borrow-carry/03-CONTEXT.md` — D-05/D-06
  side-agnostic cover-arm + clamp-to-flat; D-08 carry nets at cash/equity (not in
  Position); the per-bar accrual hook in `update_portfolios_market_value` (where
  the liquidation check co-locates).
- `.planning/phases/03-shorts-borrow-carry/deferred-items.md` — WR-04 (the exact
  `assert_lock_fits_buying_power` call-order defect + fix options) and IN-03
  (per-instrument MMR table) routed to this phase; IN-01/IN-02/IN-04 future nits.
- `.planning/phases/02-margin-accounting-leverage/02-CONTEXT.md` — D-09
  lock-and-settle margin model; D-13 compute-on-demand maintenance margin /
  `margin_ratio`; D-16 the P2/P4 pre-liquidation boundary (this phase closes it).
- `.planning/phases/01-instrument-value-object/01-CONTEXT.md` — the `Instrument`
  value object + `Universe` read-model façade (the seam `liquidation_fee_rate` is
  added to and read through; `maintenance_margin_rate` already lives here per
  INST-03).

### Code to change / mirror
- `itrader/portfolio_handler/portfolio_handler.py:432` —
  `update_portfolios_market_value` (the BAR-route hook where the per-position
  liquidation breach check co-locates with the P3 carry accrual, D-01/D-04).
- `itrader/portfolio_handler/portfolio_handler.py:307/342` — `maintenance_margin`
  / `margin_ratio` read-model accessors (per-position liq math reuses the MMR
  read; D-01).
- `itrader/portfolio_handler/cash/cash_manager.py` — the position-keyed
  locked-margin container + realized-cash settle path (the liquidation settles
  loss + penalty; WR-04 `assert_lock_fits_buying_power` call-order fix).
- `itrader/portfolio_handler/position/position.py` — `PositionSide.SHORT` PnL
  branches (the forced close realizes short/long PnL through the existing path).
- `itrader/core/enums/order.py:174` — `OrderTriggerSource` (add the
  `LIQUIDATION` member, D-04/LIQ-03).
- `itrader/events_handler/events/fill.py:81` — `FillEvent.new_fill` (the
  forced-close fill minted on the BAR route, D-04).
- `itrader/core/instrument.py` — add `liquidation_fee_rate` (D-06); confirm
  `maintenance_margin_rate` (INST-03) satisfies IN-03.
- `itrader/config/portfolio.py` — `TradingRules` (the config-level
  `liquidation_fee_rate` fallback default, D-06).
- `itrader/order_handler/order_handler.py` — `on_fill` mirror reconcile
  (EXECUTED→FILLED) handles the liquidation fill with no new status (LIQ-03).

### External-framework reference
- `backtesting.py` 0.6.5 (installed) — minimal liquidation (`equity ≤ 0 →
  close-all`), `margin = 1/leverage`; gating oracle for short/leveraged-long +
  directional liquidation corroboration (D-08).
- `backtrader` 1.9.78.123 (installed) — margin via `comminfo`, no isolated
  liquidation model; gating oracle for short/leveraged-long (D-08).
- `freqtrade` — the isolated long/short liquidation **formula** reference
  (`Entry×(1−(WB/size)/L)/(1+MMR)`) we copy; **NOT installed**, ruled out as an
  oracle here (D-09).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `update_portfolios_market_value` (`portfolio_handler.py:432`) — the per-bar BAR
  route hook already wired (P3 carry accrual lives here); the liquidation breach
  check co-locates with it (one per-bar pass over open positions).
- `maintenance_margin` / `margin_ratio` read-model accessors
  (`portfolio_handler.py:307/342`, P2 D-13) — the MMR-per-position math the D-01
  liquidation-price formula reuses (compute-on-demand, no stored state).
- `OrderTriggerSource` (`core/enums/order.py:174`) — a **closed vocabulary** enum
  ready for the new `LIQUIDATION` member (mirrors how `ADMISSION_*` members were
  added); `FillEvent.new_fill` (`fill.py:81`) is the forced-close fill factory.
- `Position.realised_pnl` / `unrealised_pnl` (`position/position.py`) — already
  branch on `PositionSide.SHORT`; the forced close realizes PnL through the
  existing path (no new branch).
- `order_handler.on_fill` EXECUTED→FILLED reconcile — handles the liquidation fill
  with **no new `FillStatus`** (LIQ-03).
- The position-keyed locked-margin container in `CashManager` (P2 D-10) — the
  allocated-isolated-margin source (`WB`) the liquidation floor reads.
- `scripts/crossval/` + `scripts/cross_validate.py` (+ the v1.3 `_limit`
  variants) — the crossval harness to extend with short/leveraged-long/liquidation
  runners; `tests/golden/CROSS-VALIDATION.md` is the evidence-doc template.

### Established Patterns
- **Liquidation = equity event on the BAR route, not the MatchingEngine** —
  the matching engine owns *order* fills; liquidation is detected in portfolio
  accounting and emits a `FillEvent` so the position/cash/order-mirror path
  reconciles uniformly (design-note §5).
- **Byte-exact gate via default-off** — `liquidation_fee_rate` default 0,
  margin/shorts default-off → SMA_MACD stays byte-exact; all new behavior is gated
  and oracle-dark (D-11).
- **Per-instrument risk metadata on `Instrument` + venue/config fallback** — MMR /
  max_leverage / borrow_rate / liquidation_fee_rate all resolve Instrument-first
  (D-06), consistent with P1/P3.
- **Compute-at-the-edge, not stored mutable state** — liquidation price + penalty
  computed on demand from current close + position fields each bar (mirrors P2 D-13
  compute-on-demand margin, P3 D-08 carry).
- **Decimal end-to-end** — the liquidation formula, penalty, and floored loss stay
  Decimal; `float()` only at the serialization/logging edge.
- **Crafted scenarios are the correctness oracle; hand-computed primary** — the
  cross-validation evidence + owner sign-off discipline from `CROSS-VALIDATION.md`
  (D-08/D-12).

### Integration Points
- `Instrument` gains `liquidation_fee_rate`; `Universe` surfaces it per symbol;
  the BAR-route liquidation check reads it per breaching position.
- `update_portfolios_market_value` gains the per-position liquidation breach
  check → mints forced-close order + emits `FillEvent(EXECUTED)` directly.
- `OrderTriggerSource` gains `LIQUIDATION`; the order mirror's `on_fill` reconcile
  handles the fill with no new status.
- `CashManager` settle path applies floored loss + penalty (WR-04 call-order fix
  lands here).
- `scripts/crossval/` gains short/leveraged-long/liquidation runners; a new
  accounting-core cross-validation doc + owner sign-off freezes the goldens.

</code_context>

<specifics>
## Specific Ideas

- The user consistently steered to **"what's the most realistic thing / what do
  other frameworks do"** before locking each decision — which is why detection is
  the **per-position isolated liquidation price** (real venues + freqtrade), the
  fill settles **at the liquidation price** (freqtrade model, max-loss = isolated
  margin), the penalty is **% of notional** (Binance/Bybit clearance fee), and the
  loss is **capped at allocated margin** (real isolated max-loss + insurance-fund
  absorption).
- The user probed including **freqtrade** as a liquidation oracle; ruled out after
  verifying it is **not installed** and recognizing the **circularity** (we copy
  its formula) — kept as the Phase-B funding oracle.
- The user accepted **Instrument-first + config fallback** for the penalty rate
  once it was clear that gives single-knob ergonomics for free (set the fallback,
  declare no per-symbol overrides) with no realism loss, after confirming
  liquidation fees track MMR and are near-uniform across majors (this milestone's
  universe).
- The user explicitly raised the **"is the penalty delivered via a FillEvent from
  the exchange?"** mechanism question → resolved as the portfolio-side liquidation
  engine minting the `FillEvent` directly on the BAR route (D-04), not routing
  through the exchange (wrong next-bar-open timing).

</specifics>

<deferred>
## Deferred Ideas

- **`freqtrade` as a 4th cross-validation oracle** — Phase B (validates funding,
  which backtesting.py/backtrader can't); also the formula source for liquidation
  (D-09). Not installed today.
- **Mark-price liquidation trigger** — Phase B; swaps the bar-close honest proxy
  for a mark-price series (resolves phantom-wick risk, §3).
- **Cross-margin / account-wide joint liquidation (collateral pool, cascade)** —
  beyond Phase B; the isolated model here needs no account-equity pool (and so no
  `Account` class — that's the N+4 live-reconciliation driver).
- **Tiered MMR brackets** — future; v1.4 uses a flat per-instrument MMR with
  notional capped to first-tier validity (schema wired so a tier table can replace
  it).
- **Single-order flips (explicit close+open split)** — deferred from P3; the
  Nautilus `_flip_position` pattern, an explicit-quantity feature, not the
  resolver's job.
- **Engine-native trailing stops (TRAIL-01/02/03)** — Phase 5 (own re-baseline,
  MatchingEngine subsystem).
- **Pair-trading flagship (PAIR-01)** — Phase 6; the headline long/short demo, NOT
  the correctness oracle (the crafted scenarios under XVAL-01 are).
- **IN-01/IN-02/IN-04** — P3 doc/convention nits (dead `update_market_value`,
  unreachable branch, zero-exponent consistency) — future cleanup.

None outside phase scope were raised that aren't already tracked above.

</deferred>

---

*Phase: 4-Liquidation & Cross-Validation Re-baseline*
*Context gathered: 2026-06-16*
