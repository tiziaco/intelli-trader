---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: — Margin, Leverage, Shorts & Trailing Stops
status: executing
stopped_at: Completed 05-01-PLAN.md
last_updated: "2026-06-17T07:01:33.341Z"
last_activity: 2026-06-17
progress:
  total_phases: 9
  completed_phases: 4
  total_plans: 29
  completed_plans: 26
  percent: 44
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-14 — v1.4 Margin, Leverage, Shorts & Trailing Stops STARTED; promotes Backlog 999.4 / N+2)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now extended with first-class shorts, leverage, a liquidation model (closing DEF-01-C), and engine-native trailing stops, all owner-gated and cross-validated.
**Current focus:** Phase 05 — engine-native-trailing-stops

## Current Position

Phase: 05 (engine-native-trailing-stops) — EXECUTING
Plan: 3 of 5
Status: Ready to execute

> Note: `phase.complete` auto-resolved next_phase to backlog seed 999.2 because the Phase 5 dir does
> not exist yet (only 01/02/03/04 + 999.x dirs are present). Corrected manually to Phase 5 per the v1.4
> Phase Map (1→2→3→4→**5**→6). 999.2/999.3 remain FUTURE (N+3/N+4) backlog entries, not the next phase.
Last activity: 2026-06-17

## Milestone Gate (v1.4 — owner-gated, result-changing; applies per phase, per re-baseline tag)

**Two re-baseline disciplines run side by side. Each phase declares which it is.** This is an
M5-style **owner-gated, result-changing** milestone: enabling shorts/leverage/liquidation changes
results, so each result-changing phase re-baselines the golden master ONLY after explicit owner
sign-off (full attribution) + external cross-validation (`backtesting.py` 0.6.5 / `backtrader`
1.9.78.123). The existing SMA_MACD spot oracle (134 trades / `final_equity 46189.87730727451`)
stays byte-exact except where shorts/leverage legitimately change a leaf.

**Held throughout, all phases:**

- `mypy --strict` clean across all source files
- Decimal end-to-end (including liquidation formula + interest accrual; `float()` only at the
  serialization/logging edge); no new float-for-money; single UUIDv7 ID scheme

- Determinism double-run byte-identical (reuse the seeded RNG + injected `BacktestClock`; introduce
  no new nondeterminism)

**Byte-exact phase (Phase 1 — Instrument Value Object)** — re-baseline NOTHING. Must hold:

- `pytest tests/integration` byte-exact oracle: **134 trades / `final_equity 46189.87730727451`**
- `pytest tests/e2e -m e2e` green (no leaf re-baselined); full suite green
- **Behavioral gate:** `BTCUSD` ALWAYS takes the declared 8dp branch — inference would drift the
  oracle. Whether the backtest *snaps/rounds* via `Instrument` (vs storing metadata only) is the
  result-changing decision and must hold the oracle byte-exact.

**Owner-gated phases (2: Margin & Leverage; 3: Shorts & Carry; 4: Liquidation & Cross-Validation)** —
result-changing accounting core. The new golden master freezes **ONLY** after explicit owner sign-off
with full attribution, validated by external cross-validation.

- **ONE accounting-core re-baseline, gated by XVAL-01 (Phase 4).** The crafted, hand-computable,
  adversarial scenarios (pure short, leveraged long, forced liquidation) cross-validated against
  `backtesting.py`/`backtrader` are the **correctness oracle** — NOT pair trading. The accounting
  core (margin + shorts + liquidation) re-baselines under that one owner-gated XVAL-01 gate.

**Owner-gated phase (5: Engine-Native Trailing Stops)** — its OWN re-baseline, separate from the
accounting core (a DIFFERENT subsystem: `MatchingEngine` resting-order ratchet vs portfolio/cash
accounting). Cross-validated (TRAIL-03) against `backtesting.py`/`backtrader`. Look-ahead rule: the
trail updates from CLOSED-bar extremes and is live for the NEXT bar — never trail to this bar's
extreme and trigger off the same bar.

**Capstone phase (6: Pair-Trading Flagship)** — NOT a re-baseline of the SMA_MACD oracle (additive
flagship strategy). NOT the correctness oracle (a two-leg market-neutral strategy partially cancels
its own sign errors → weak oracle). Self-contained and slip-able to a follow-on without blocking the
shippable margin/shorts core.

## Phase Map (v1.4 — Phases 1-6)

Execution order: 1 → 2 → 3 → 4 → 5 → 6. Derived from the 20 v1.4 requirements + the locked
sequencing (Instrument first; the margin/shorts/liquidation accounting core under one owner-gated
XVAL-01 re-baseline; trailing stops as a separate subsystem with its own re-baseline; pair trading
as the final, slip-able capstone). Numbering reset to Phase 1 (matching v1.1/v1.2/v1.3; v1.3 phase
dirs archived to `.planning/milestones/v1.3-phases/`, so the new `01-*..06-*` dirs do not collide —
only the `999.2`/`999.3` backlog seed dirs remain in `.planning/phases/`).

| Phase | Name | Requirements | Re-baseline | Depends on |
|-------|------|--------------|-------------|------------|
| 1 | Instrument Value Object | INST-01, INST-02, INST-03 | Byte-exact (BTCUSD declared 8dp; oracle holds) | — |
| 2 | Margin Accounting & Leverage | MARGIN-01/02/03, LEV-01, LEV-02 | Owner-gated (part of the accounting-core re-baseline, frozen at P4/XVAL-01) | 1 |
| 3 | Shorts & Borrow Carry | SHORT-01/02/03, CARRY-01 | Owner-gated (accounting-core re-baseline, frozen at P4/XVAL-01) | 2 |
| 4 | Liquidation & Cross-Validation Re-baseline | LIQ-01/02/03, XVAL-01 | Owner-gated — THE accounting-core golden re-baseline (cross-validated + owner sign-off) | 2 AND 3 |
| 5 | Engine-Native Trailing Stops | TRAIL-01, TRAIL-02, TRAIL-03 | Owner-gated — OWN re-baseline (MatchingEngine subsystem) | 4 |
| 6 | Pair-Trading Flagship | PAIR-01 | Capstone — additive, NOT a re-baseline; slip-able | 3, 4 |

**Sequencing rationale:** INST-* (P1) is foundational — margin/liquidation/leverage all consume the
per-instrument `Instrument`; it deletes `_INSTRUMENT_SCALES`. Margin (P2) precedes shorts (P3 — a
short reserves margin and carry rides shorts) and liquidation (P4 — needs maintenance margin AND
shorts to liquidate). Liquidation (P4) co-phases XVAL-01 because all three crafted scenario types
(short, leveraged-long, liquidation) exist by then — it is the single owner-gated accounting-core
re-baseline. Trailing stops (P5) are a different subsystem (resting-order ratchet, not accounting),
so they own a separate re-baseline. Pair trading (P6) is the final, slip-able capstone — the flagship
"shorts work end-to-end" demo, NOT the correctness oracle.

## Performance Metrics

**Velocity (v1.3):**

- Total plans completed: 44
- Average duration: — min
- Total execution time: 0.0 hours

*Updated after each plan completion. v1.0/v1.1/v1.2/v1.3 velocity is archived in the respective MILESTONE-AUDIT.md.*

## Accumulated Context

### Roadmap Evolution

- v1.4 roadmap created 2026-06-14 (promotes Backlog 999.4 / N+2): 6 phases derived from the 20 v1.4
  requirements; all 20 mapped (100% coverage). Phase 999.4 backlog entry marked PROMOTED-TO-v1.4
  (design intent retained as the historical seed); 999.2 (N+3) / 999.3 (N+4) backlog entries kept
  intact. Phase B perp realism (FUND-01..04) folded into the N+4 backlog seed; ACCT-01 stays in N+4.

- Phase 999.4 edited (pre-promotion): added Scope bullet for the minimal crypto-only Instrument value
  object; refined Instrument seed to the 7-field set + layered price precision (declared-wins →
  infer-guarded → default, oracle stays declared); funding is flag not rate; min_order_size moved onto
  Instrument; ExchangeLimits demoted to venue fallback.

- Phase 999.3 edited: added Scope bullet for dynamic universe membership (UniverseSelectionModel poll
  seam), sequenced near the N+4 data engine.

### Decisions

Active decisions live in PROJECT.md Key Decisions. Load-bearing program constraints + the v1.4 locked
scope decisions:

- Money = Decimal end-to-end; float money is a correctness defect — applies to the liquidation formula
  and interest accrual (`float()` only at the serialization/logging edge).

- IDs = single UUIDv7 scheme via `uuid-utils`. Determinism = seeded RNG + injected `BacktestClock`;
  v1.4 introduces NO new nondeterminism.

- **Owner-gated, result-changing milestone (M5-style):** enabling shorts/leverage/liquidation changes
  results; the new golden master freezes ONLY after explicit owner sign-off (full attribution) +
  external cross-validation (`backtesting.py`/`backtrader`). The SMA_MACD oracle (134 /
  46189.87730727451) stays byte-exact except where a leaf legitimately changes.

- **Instrument first (LOCKED):** INST-* is foundational. `Instrument` (`core/instrument.py`, frozen,
  mirrors `core/bar.py::Bar`) is the per-symbol source of precision + lot step + `min_order_size` +
  margin params; `core/money.py::quantize` reads precision from it; the hard-coded `_INSTRUMENT_SCALES`
  table is DELETED. BTCUSD stays declared 8dp (inference would drift the oracle). Whether the backtest
  *snaps* via Instrument is the behavioral gate. `ExchangeLimits` demoted to a venue-level fallback.

- **Accounting core = one owner-gated re-baseline at Phase 4 (LOCKED):** margin (P2) + shorts (P3) +
  liquidation (P4) are the tightly-coupled accounting core. Liquidation depends on maintenance margin
  AND on shorts existing to be liquidated; carry rides shorts; levered Kelly needs margin. The single
  owner-gated golden re-baseline is gated by XVAL-01 (cross-validation + owner sign-off), co-phased
  with Liquidation (P4) where all three crafted scenario types exist. Phases are kept clean and
  independently verifiable rather than one giant phase.

- **Liquidation — NO new `FillStatus` (LOCKED):** reuse `FillStatus.EXECUTED`; the liquidation engine
  mints an admission-bypassing forced-close order (real `strategy_id`/`order_id`) tagged
  `OrderTriggerSource.LIQUIDATION`, reconciling through the existing position/cash/order-mirror path.
  The penalty rides the existing `commission`/fee field. (Resolves §9 Q2 of the design note.)

- **Trailing stop = SEPARATE phase, OWN re-baseline (LOCKED):** a different subsystem (`MatchingEngine`
  resting-order ratchet, not portfolio/cash accounting). Sequenced after the accounting core (P5).
  Look-ahead rule: trail updates from CLOSED-bar extremes, active the NEXT bar. The native-vs-synthetic
  live capability seam is deferred to N+4.

- **Pair trading = FINAL, slip-able capstone; NOT the correctness oracle (LOCKED):** the crafted
  short/leveraged/liquidation scenarios under XVAL-01 are the oracle. Pair trading is the flagship
  long/short demonstration, scoped as a distinct last phase so it can slip to a follow-on without
  blocking the shippable margin/shorts core.

- **Phase numbering reset to 1 for v1.4** (matching v1.1/v1.2/v1.3). The v1.3 phase dirs were archived
  to `.planning/milestones/v1.3-phases/`, so the new `01-*..06-*` dirs do not collide. The `999.x`
  backlog entries are FUTURE milestones (N+3/N+4), left intact in ROADMAP.md `## Backlog`; 999.4 is
  marked PROMOTED-TO-v1.4.

- **Deferred OUT of v1.4 (tracked):** Phase B perp realism (FUND-01..04: funding-rate accrual,
  mark-price liquidation trigger, funding-data pipeline, `freqtrade` 4th oracle) → future / N+4 data
  work; the `Account` reconciliation abstraction (ACCT-01) → N+4 live; the trailing-stop
  native-vs-synthetic live seam → N+4; `Portfolio.user_id` removal → independent cleanup (kept out so
  it doesn't muddy the re-baseline).

- [Phase ?]: Phase 1 Plan 01: Instrument stores the Decimal SCALE directly (price_precision=Decimal('0.00000001')) not an int place-count — byte-identical to the deleted _INSTRUMENT_SCALES['BTCUSD']; quantize reads scale off the handed-in Instrument (D-05 pure/stateless)
- [Phase ?]: Phase 1 Plan 02: symbol->Instrument resolution lives in universe/ (derive_instruments + Universe facade, D-03 no separate registry); ExchangeLimits demoted to venue fallback; SimulatedExchange resolves min_order_size Instrument-first via set_universe (None default = byte-exact); oracle held 134/46189.87730727451
- [Phase ?]: Phase 1 Plan 03: byte-exact phase gate PASSED — oracle held 134/46189.87730727451, mypy --strict clean (185 files), determinism 9/9 double-run identical, full suite 1023 passed, golden artifacts untouched; no production code modified, phase re-baselines nothing (D-10/D-01a/D-02a)
- [Phase 02]: Phase 2 Plan 00: 13 collectible pytest.skip Wave 0 stubs (6 unit files + new tests/e2e/levered_long/ e2e stub) satisfy the Nyquist contract — every Phase-2 (02-06) -k/-m verify target selects >=1 test before any RED step; folder-derived markers only (no decorator); test-only, oracle untouched
- [Phase ?]: Phase 2 Plan 01: SignalEvent.leverage (D-03) + TradingRules.max_leverage ge=1 (D-14) landed as inert defaulted Decimal('1') fields — oracle-dark (134/46189.87730727451 held), Wave 2 admission-gate (D-04) consumes them
- [Phase 02]: Phase 2 Plan 02: LeveredFraction sizing kind (notional = f x total_equity, D-07/LEV-02) — f guarded >0 NOT (0,1] (f>1 gate lives in AdmissionManager/Plan 03); SizingPolicy union grew forcing the assert_never arm; SignalIntent.leverage mirror (D-03) added; resolver reads total_equity (D-12) via the read-model Protocol, never cash; FractionOfCash (0,1] oracle-dark path untouched; mypy --strict clean (185 files)
- [Phase ?]: Phase 2 Plan 04: lock-and-settle margin model (enable_margin gate, D-09/D-10/D-11) — position-keyed locked_margin in CashManager (Pitfall 2); available_balance = balance − reserved − locked_margin (spot byte-exact); Position.leverage at open (D-06) + aggregate_notional; margin close cash delta = realised_increment + p×prior_entry_commission so round-trip == realised_pnl; SMA_MACD 134/46189.87730727451 byte-exact
- [Phase 02]: Phase 2 Plan 05: maintenance_margin/margin_ratio compute-on-demand read-model accessors (D-13/MARGIN-03) — Σ(mmr × |size| × current_price) over open positions via injected Universe (PortfolioHandler.set_universe seam, Trap-4 ordering, mirrors order/exchange set_universe); margin_ratio = total_equity()/maintenance honest-when-breached (D-16, no clamp), Decimal('0') zero-maintenance sentinel; max_leverage rides update_config UNCHANGED (D-15, TradingRules field); 3 Wave-0 stubs (maintenance_margin/margin_ratio/max_leverage) turned green; SMA_MACD 134/46189.87730727451 byte-exact, mypy --strict clean (185 files)
- [Phase ?]: Phase 2 Plan 07: LEV-03 closed — strategy-declared EFFECTIVE leverage min(signal,instr,pf) flows signal->order->fill->transaction->position; run-path Transaction in PortfolioHandler.on_fill (not new_transaction) was the actual carry site (deviation); locked margin == admission reservation under L>1; SMA_MACD 134/46189.87730727451 byte-exact, mypy clean (185 files)
- [Phase 02]: Phase 2 Plan 08: gap closure for the two 02-REVIEW BLOCKERs — CR-01 CLOSED (new_limit_order/new_stop_order carry keyword-only leverage; admission LIMIT/STOP arms pass effective_leverage → locked margin == admission reservation for ALL order types, LEV-03 complete); CR-02 MITIGATED (margin over-close fill raises InvalidTransactionError before any mutation/settlement — full flip economics deferred to Phase 3); residual WR-01..05 + IN-01..03 + CR-02-residual tracked in deferred-items.md; SMA_MACD 134/46189.87730727451 byte-exact (oracle-dark), mypy --strict clean (185 files), make test 1089 passed
- [Phase 02]: Phase 2 Plan 06: parked leveraged-long e2e (D-17 — hand-computed, NOT a frozen golden) + GREEN phase gate (SMA_MACD 134/46189.87730727451 byte-exact, margin-mode determinism byte-identical, mypy --strict clean 185 files, make test 1079 passed); blocking human-verify checkpoint owner-APPROVED — Phase 2 freezes NO new golden (accounting-core re-baseline stays the single owner-gated freeze at P4/XVAL-01, D-16/D-17). The two findings this e2e surfaced (A: StrategiesHandler dropped SignalIntent.leverage at fan-out; B: leverage not carried order->fill->transaction) were CLOSED by 02-07/LEV-03 — not open.
- [Phase ?]: Phase 5 Plan 00: 7 collectible pytest.skip Wave-0 trailing stubs satisfy the Nyquist contract — every Phase-5 -k/-m selector including compound 'trailing and bracket' collects >=1 before any RED; test-only, oracle byte-exact
- [Phase ?]: Phase 5 Plan 01: TrailType lives in config/order.py (config-enum exception, order-domain cohesion); TRAILING_STOP order type + trail_type/trail_value carriage (Order->OrderEvent) + new_trailing_stop_order factory; D-TRAIL-7 dual-layer non-viable-trail gate with Pitfall-6 strategy (a) positive computed initial stop (price<=0 gate NOT branched out, both layers agree D-03a); SMA_MACD spot oracle byte-exact, mypy --strict clean (185 files)

### Pending Todos

None yet.

### Blockers/Concerns

- **Owner-gate dependency:** Phases 2-5 cannot freeze a new golden without explicit owner sign-off —
  plan them so the result-change is fully attributed before re-baseline. The accounting-core
  re-baseline (P2+P3+P4) is gated by XVAL-01 at Phase 4; Phase 5 (trailing) owns its own re-baseline.

- **BTCUSD oracle protection (Phase 1):** the `Instrument` precision-resolution MUST route BTCUSD
  through the declared 8dp branch — inference from BTCUSD data would yield ~2-4dp and drift the golden
  master off `46189.87730727451`. The byte-exact gate is the proof.

- **Correctness oracle = crafted scenarios, NOT pair trading:** lock correctness with crafted,
  hand-computable, adversarial scenarios (pure short, leveraged long, forced liquidation)
  cross-validated against `backtesting.py`/`backtrader` (XVAL-01). A two-leg market-neutral strategy
  partially cancels its own sign errors and is a weak oracle.

- **FillEvent forced-close shape (Phase 4):** confirm the forced-close `FillEvent` reconciles cleanly
  through the existing position/cash/order-mirror path with NO new `FillStatus` (LOCKED design above);
  open question §9 Q2 of the design note is resolved but verify at plan time.

- **Indentation hazard:** tabs in handler modules (`order_handler/`, `strategy_handler/`,
  `execution_handler/`, `portfolio_handler/`); 4 spaces in `config/`/`core/`/`price_handler/feed/`/
  events package — match the file, never normalize (a mixed-indentation edit breaks a tab file). v1.4
  touches `core/` (new `Instrument`, 4 spaces) AND tab-indented portfolio/execution/strategy modules.

- **CR-01 cover-arm hole (Phase 3):** `_resolve_signal_quantity` (in `order_manager.py` `admission/`)
  has no BUY-to-cover arm for a `SHORT_ONLY` book — a cover falls through to entry sizing and flips the
  book long. This is the oracle-dark critical surfaced at v1.0 Phase 7 (07-REVIEW), routed here.

- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not
  silently folded into a running phase (it would corrupt the owner-gated re-baseline attribution).

### Quick Tasks Completed

(v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`; v1.1/v1.2/v1.3 per-phase plan
records archived under `milestones/v1.1-phases/`, `milestones/v1.2-phases/`, `milestones/v1.3-phases/`.)

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-sjp | Close FL-01 & FL-02 fix-list residuals + reconcile FIX-LIST.md status | 2026-06-10 | 4db1907 | [260610-sjp-close-fl01-fl02](./quick/260610-sjp-close-fl01-fl02/) |
| 260614-atk | v1.3 tech-debt doc reconcile: REQUIREMENTS checkboxes + stale Phase 6 WR-02/WR-03 audit ledger | 2026-06-14 | 191e21f | [260614-atk-v1-3-tech-debt-doc-reconcile-requirement](./quick/260614-atk-v1-3-tech-debt-doc-reconcile-requirement/) |
| Phase 01 P01 | 4 | 2 tasks | 4 files |
| Phase 01 P02 | 5 | 2 tasks | 11 files |
| Phase 01 P03 | 2 | 1 tasks | 0 files |
| Phase 02 P00 | 3 | 1 tasks | 8 files |
| Phase 02 P01 | 5 | 2 tasks | 2 files |
| Phase 02 P02 | 8 | 2 tasks | 3 files |
| Phase 02 P03 | 18 | 3 tasks | 8 files |
| Phase 02 P04 | 35 | 3 tasks | 9 files |
| Phase 02 P05 | 8 | 2 tasks | 7 files |
| Phase 02 P07 | 18 | 3 tasks | 9 files |
| Phase 02 P06 | 0 | 2 tasks | 3 files |
| Phase 02 P08 | 12 | 3 tasks | 7 files |
| Phase 05 P00 | 6 | 2 tasks | 7 files |
| Phase 05 P01 | 4 | 2 tasks | 8 files |

## Bookkeeping

- **v1.1 phase dirs archived:** moved to `.planning/milestones/v1.1-phases/` (before the v1.2
  phase-number reset, so renumbering v1.2 to Phases 1-6 produced no directory collision).

- **v1.2 phase dirs archived (2026-06-12):** the six v1.2 phase working directories (`01`-`06`) moved
  to `.planning/milestones/v1.2-phases/`.

- **v1.3 phase dirs archived (2026-06-14, at milestone close):** the six v1.3 phase working
  directories (`01`-`06`) were `git mv`'d to `.planning/milestones/v1.3-phases/`. Only the `999.x`
  backlog seed dirs (`999.2`/`999.3`) remain in `.planning/phases/`, so the new v1.4 `01-*..06-*`
  dirs will not collide.

## Deferred Items

Program-level items out of scope for v1.4, with their target milestone:

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Perp realism (Phase B) | Funding-rate accrual (FUND-01), mark-price liquidation trigger (FUND-02), funding-data pipeline (FUND-03), `freqtrade` 4th oracle (FUND-04) | Deferred | future / N+4 data work (additive on the v1.4 core) |
| Live account | `Account` reconciliation mirror (`CashAccount`/`MarginAccount`) (ACCT-01) | Deferred | N+4 Live Readiness (Backlog 999.3) |
| Live execution | Trailing-stop native-vs-synthetic capability seam on `AbstractExchange` | Deferred | N+4 (Backlog 999.3) |
| Backtest accounting | Cross-margin (account-wide collateral pool / joint liquidation) | Deferred | beyond Phase B (own milestone) |
| Margin realism | Tiered maintenance-margin brackets (v1.4 = flat per-instrument MMR, first-tier cap) | Deferred | future (schema wired for a tier table) |
| Perps | Inverse / coin-margined perps; bankruptcy price / insurance fund / ADL; hedge mode | Deferred | each its own milestone (crypto-first linear USD) |
| Cleanup | `Portfolio.user_id` removal (app-layer multi-tenancy concern) | Deferred | N+4 (with the connector); kept out of v1.4 to protect the re-baseline |
| Live coverage | `LiveTradingSystem`/`TradingInterface` test coverage (FL-13) | Deferred | N+4 Live Readiness (Backlog 999.3) |
| Persistence/security | SQL injection + hardcoded creds in `SqlHandler` (FL-06) | Deferred | N+3 Persistence (Backlog 999.2) |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | N+3 (Backlog 999.2) |
| D-screener | Production screener / ranking / rebalance loop (minimal `membership` shipped v1.1) | Deferred | N+4 (Backlog 999.3) |
| D-live | Live mode (streaming, TradingInterface modify/cancel, live threading, secrets) | Deferred | N+4 |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions (forex/equities/ETF) | Deferred | indefinite (crypto-first) |
| Indicators | IND-02 incremental/stateful indicator backends (behind the IND-01 stable interface) | Deferred | future (post-v1.3) |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | — |

v1.0/v1.1/v1.2/v1.3 milestone-close acknowledgments are recorded in the respective MILESTONE-AUDIT.md
files under `milestones/`.

## Session Continuity

Last session: 2026-06-17T07:01:33.333Z
Stopped at: Completed 05-01-PLAN.md
Resume file: None

## Operator Next Steps

- Review the v1.4 roadmap draft (`.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` Traceability).
- Plan Phase 1 (Instrument Value Object) with `/gsd:plan-phase 1`.
