---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: "Backtest Trustworthiness: Breadth"
status: ready_to_plan
last_updated: 2026-06-10T12:25:07.577Z
last_activity: 2026-06-10
progress:
  total_phases: 12
  completed_phases: 7
  total_plans: 21
  completed_plans: 21
  percent: 58
stopped_at: Phase 07 complete (4/4) — ready to discuss Phase 999.2
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-09)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — the backtest path must import, run, and yield trustworthy results.
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-10

## Performance Metrics

**Velocity (v1.1):**

- Total plans completed: 24
- Average duration: — min
- Total execution time: 0.0 hours

*Updated after each plan completion. v1.0 velocity is archived in `milestones/v1.0-MILESTONE-AUDIT.md`.*

## Accumulated Context

### Decisions

Active decisions live in PROJECT.md Key Decisions (including the five v1.1 decisions: crypto-first; dedicated `tests/e2e/` + `e2e` marker; hand-verify-once-then-regression-lock; normalize data via committed script not loader logic; minimal real universe). v1.0 per-plan decisions are archived in `milestones/v1.0-MILESTONE-AUDIT.md` and the v1.0 phase records under `milestones/v1.0-phases/`.

Load-bearing program constraints still in force for v1.1:

- Money = Decimal end-to-end; float money is a correctness defect.
- IDs = single UUIDv7 scheme via `uuid-utils`.
- v1.1 is **behavior-preserving** — the v1.0 final golden oracle (134 trades / `final_equity 46189.87730727451`) is NOT re-baselined; any result-changing finding is owner-gated, never silently folded in.
- [Phase ?]: D-06 volume check relaxed to non-negative (NaN/negative still raise): zero-volume bars on SOLUSD(11)/AAVEUSD(35) are a provider missing-data sentinel, not true zeros; OHLC is real and bar volume is inert on the v1.1 run path
- [Phase ?]: is_active/active_membership added alongside derive_membership (D-03); span model inclusive both ends (D-01); active_membership returns set[str]
- [Phase ?]: [Phase 03 P02]: feed is the single span-aware observability owner (D-04) — silent for pre-listing/post-end, warns only on a true mid-life gap; span bounds cached as tz-aware pd.Timestamp; bar/fill path untouched (oracle-dark)
- [Phase ?]: [Phase 03 P03]: optional csv_paths passthrough on TradingSystem.__init__ (default None = byte-identical golden behavior, oracle-dark); UNIV-02 engine-proven on synthetic fixtures (no crash, no look-ahead over the union window) — real ETH/SOL/AAVE E2E deferred to Phase 9 (D-06)
- [Phase ?]: [Phase 07 P01]: commission golden column is conftest-LOCAL + oracle-dark (D-07/D-08), sourced from real Position.commission, kept out of itrader/reporting so the BTCUSD oracle stays byte-exact
- [Phase ?]: [Phase 07 P01]: D-14 exchange seam re-inits fee/slippage from spec.exchange via the constructor path, NEVER touching _supported_symbols (re-deriving it would wipe BTCUSD admission and silently REFUSE every order)
- [Phase ?]: [Phase 07 P01]: COST-01 canary commission=285.00 / final_cash=19215.00 hand-verified to the cent; 15 pre-existing goldens re-frozen additively (commission=0.00, no other value drift)
- [Phase ?]: [Phase 07 P02]: COST cluster complete — 5 leaves (COST-02..06) hand-verified to the cent and frozen; maker/taker contrast via two emitter instances (LIMIT=maker / MARKET=taker) on non-overlapping windows (D-11)
- [Phase ?]: [Phase 07 P02]: engine fix — _init_fee_model/_init_slippage_model use 'is not None' not 'or' so a configured Decimal(0) determinism knob (COST-04 base_slippage_pct=0) is honored; oracle-safe (oracle runs Zero* models, byte-exact)
- [Phase ?]: [Phase 07 P02]: engine truth — percent fee is charged on the BASE/un-slipped notional (fee_model called before executed_price = price*slippage_factor); fee and slippage are independent deductions, verified cent-exact in COST-06
- [Phase ?]: [Phase 07 P03]: SIZE cluster complete — SIZE-01/02/03 hand-verified to the cent and frozen; no engine change (SizingResolver + admission gate already wired, PR #12/05-06)
- [Phase ?]: [Phase 07 P03]: SIZE-02 RiskPercent sizes off a decision-time stop (D-13): the same explicit sl both sizes qty=(equity*risk_pct)/|price-stop| AND becomes the STOP child that closes the trade (pnl -200 = 2% risk) — a CLOSED TRADE, not REJECTED (T-07-09)
- [Phase ?]: [Phase 07 P03]: SIZE-03 over-cash REJECTED via the opt-in orders.csv (D-15); empty-placeholder opt-in vehicle; reserve() InsufficientFundsError -> audited PENDING->REJECTED (triggered_by=cash_reservation)
- [Phase 07]: [Phase 07 P04]: SLTP cluster complete — 6 leaves (PercentFromDecision/PercentFromFill x SL-hit/TP-hit/held) hand-verified to the cent and frozen; Decision anchor (decision close) vs Fill anchor (next-bar open) produce DISTINCT SL/TP levels for the same percentages
- [Phase 07]: [Phase 07 P04]: PercentFromFill cash-reservation contract — the admission gate sizes/reserves off the DECISION close, so the fill anchor must keep entry notional within that reservation; authored the next-bar open BELOW the decision close (90 < 100) to satisfy both the distinct-anchor requirement AND the funds invariant (no engine change)

### Pending Todos

None yet.

### Blockers/Concerns

- **Behavior-preserving guardrail:** the Phase 5 strategy-interface refactor must re-run the SMA_MACD golden master byte-exact (zero drift). Phase 1 cleanup and all later phases must not re-baseline the oracle.
- **E2E oracle discipline:** each new scenario's expected fills/PnL are hand-verified once, then frozen as a regression lock (a lock proves stability, not correctness — verification happens before the freeze).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not silently folded into a running phase.

### Quick Tasks Completed

None this milestone. (v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`.)

## Deferred Items

Program-level items out of scope for v1.1, with their target milestone:

| Category | Item | Status | Target |
|----------|------|--------|--------|
| D-margin | Margin/liquidation model, shorts, leverage, levered Kelly, trailing stop, real pair trading | Deferred | v1.2 |
| D-compliance | Compliance layer (long_only/short_only enforcement) | Deferred | v1.2 (with shorts) |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | v1.3 |
| D-screener | Production screener / ranking / rebalance loop (minimal `membership` IS in v1.1 Phase 3) | Deferred | v1.4 |
| D-live | Live mode (streaming, TradingInterface modify/cancel, live threading, secrets) | Deferred | v1.4 |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions (forex/equities/ETF) | Deferred | indefinite (crypto-first) |
| D-oanda | OANDA + non-crypto adapters | Deferred | with D-multiasset |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | — |

v1.0 milestone-close acknowledgments (12 advisory/UAT/verification items) are recorded in `milestones/v1.0-MILESTONE-AUDIT.md`.
| Phase 02 P01 | 2min | 3 tasks | 5 files |
| Phase 03 P01 | 4 | 2 tasks | 3 files |
| Phase 03 P02 | 4 | 3 tasks | 3 files |
| Phase 03 P03 | 12min | 2 tasks | 2 files |
| Phase 04 P03 | 25min | 2 tasks | 11 files |
| Phase 07 P01 | 5min | 4 tasks | 24 files |
| Phase 07 P02 | 15min | 3 tasks | 35 files |
| Phase 07 P03 | 6min | 2 tasks | 19 files |
| Phase 07 P04 | 12min | 2 tasks | 39 files |

## Session Continuity

Last session: 2026-06-10T12:07:33.150Z
Resume file: None

## Operator Next Steps

- Phase 05 (strategy-interface-hardening-signal-storage) is COMPLETE — verified (05-VERIFICATION.md passed) and the code-review loop is closed (05-REVIEW-FIX.iter3.md all_fixed). HARD-01..04 + SIG-01/02 validated.
- `/clear`, then `/gsd:plan-phase 6` — plan Phase 6 (Order Matching Scenarios). The Phase 04 canary leaf remains the copy-template for Phase 6-9 scenario authors.
