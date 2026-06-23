---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: — Margin, Leverage, Shorts & Trailing Stops
status: Awaiting next milestone
stopped_at: Milestone v1.4 closed and archived
last_updated: "2026-06-22T19:18:25.396Z"
last_activity: 2026-06-22 — Milestone v1.4 completed, archived, and tagged
progress:
  total_phases: 7
  completed_phases: 7
  total_plans: 35
  completed_plans: 35
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-22 — v1.4 Margin, Leverage, Shorts & Trailing Stops SHIPPED + archived; N+3 next)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now extended with first-class shorts, leverage, a bar-close liquidation model (closing DEF-01-C), engine-native trailing stops, short scale-in, and a market-neutral pair flagship, all owner-gated and cross-validated.
**Current focus:** v1.4 shipped, archived, and tagged. Next: N+3 — Persistence & Performance (Backlog 999.2); start with `/gsd:new-milestone`.

## Current Position

Phase: Milestone v1.4 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-06-23 — Completed quick task 260623-gao: engine over-sell protection A+B (spot settlement guard + orphaned-bracket cancel), oracle byte-exact

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

- Total plans completed: 56
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

- Phase 05.1 inserted after Phase 5: Short Position Scale-In (Margin Increase) — lift short-increase admission gate behind allow_increase; flip/split deferred; owner-gated re-baseline (URGENT)

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
- [Phase ?]: 05-02: order.price is the trailing reference/anchor (HWM/LWM seed), not the initial stop — confirmed via D-TRAIL-7 validator
- [Phase ?]: 05-02: D-TRAIL-8 quantize seam made optional (instrument_resolver); pure engine quantization-free by default, HWM/LWM always full precision
- [Phase ?]: 05-03: trailing intent = extended PercentFromFill (optional trail_type/trail_value, all-or-nothing); rides the existing fill-anchored carve-out, no new SLTPPolicy variant
- [Phase ?]: 05-03: trailing SL child price = ENTRY FILL anchor (the engine _seed_trail HWM/LWM seed per 05-02), NOT the computed initial stop; TP-limit unchanged (D-TRAIL-5 EITHER/OR)
- [Phase ?]: 05-03: fee/slippage _KNOWN_ORDER_TYPES gained trailing_stop (triggered TRAILING_STOP fills/fees like a STOP); long+short e2e ratcheted-exit proven (long 135 vs seed 90, short 55 vs seed 110)
- [Phase 05]: 05-04: trailing-stop cross-validated (TRAIL-03) vs backtesting.py 0.6.5 + backtrader 1.9.78.123 — trade-level reconciliation EXACT (exit 100.8, PnL +8.0), 8/8 metrics within 1%, A1 oracle API CONFIRMED (both CLOSE-basis); high-vs-close gap (D-TRAIL-1, iTrader closed-bar-extreme correct per TRAIL-02) dispositioned LEGITIMATE-DIFFERENCE, 0 BUG; phase's OWN trailing golden re-baseline FROZEN under owner sign-off (tiziaco, 2026-06-17); SMA_MACD spot oracle byte-exact 134/46189.87730727451, mypy --strict clean, determinism byte-identical
- [Phase ?]: 05.1-01: short-increase admission gate lifted behind allow_increase (byte-symmetric mirror of long gate, long arm byte-exact); D-06 admission-gate reality — a short SELL-add reserves NOTHING at admission (admission_manager.py:264 reserves only Side.BUY), margin lock rides settlement (Plan 05.1-02); CR-02 over-cover guard regression-locked for SHORT side (RED-verified); SMA_MACD oracle byte-exact 134/46189.87730727451
- [Phase 05.1]: 05.1-02 (Tasks 1-2): admitted short SELL-add settles through the EXISTING side-agnostic SCALE-IN branch (portfolio.py:423-441) — margin RE-LOCKS to aggregate_notional/leverage (1000->2000 on the second add; pro-rata release to 1000 + realised PnL 200 on a half-cover), proven by two parked e2e leaves (SCALEUSD/SCALPCUSD, NEVER BTCUSD); NO new settlement branch (D-02/D-03); cross-validated vs backtesting.py 0.6.5 / backtrader 1.9.78.123 (CROSS-VALIDATION-SCALE-IN.md, trade-level PRIMARY GREEN, 0 BUG); determinism byte-identical, SMA_MACD oracle byte-exact, mypy --strict clean (185 files).
- [Phase 05.1]: 05.1-02 (Task 3): owner-gated short scale-in re-baseline FROZEN under explicit owner sign-off (tiziaco, tiziano.iaco@gmail.com, 2026-06-17) at the blocking human-verify checkpoint. CROSS-VALIDATION-SCALE-IN.md Owner Sign-Off PENDING->APPROVED with full attribution; both scale-in e2e leaves (SCALEUSD/SCALPCUSD) carry a D-10/D-12 FROZEN freeze-provenance banner (test logic + hand-computed Decimal assertions UNCHANGED); SCALE-02/SCALE-03 marked complete. Re-confirmed at the freeze: mypy --strict clean (185 files), SMA_MACD oracle byte-exact 134/46189.87730727451, both frozen leaves green. No production code touched (portfolio.py / sizing_resolver.py untouched).

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

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260610-sjp | Close FL-01 & FL-02 fix-list residuals + reconcile FIX-LIST.md status | 2026-06-10 | 4db1907 | | [260610-sjp-close-fl01-fl02](./quick/260610-sjp-close-fl01-fl02/) |
| 260614-atk | v1.3 tech-debt doc reconcile: REQUIREMENTS checkboxes + stale Phase 6 WR-02/WR-03 audit ledger | 2026-06-14 | 191e21f | | [260614-atk-v1-3-tech-debt-doc-reconcile-requirement](./quick/260614-atk-v1-3-tech-debt-doc-reconcile-requirement/) |
| 260622-pmk | Audited admission rejection for unfunded short increase (close P05.1 WR-03) | 2026-06-22 | 9270146 | Verified | [260622-pmk-audited-admission-rejection-for-unfunded](./quick/260622-pmk-audited-admission-rejection-for-unfunded/) |
| 260622-vlh | Durable evals/ benchmark harness (PERF-BASELINE Step 1): hardened CCXT fetch + 4×5m CSVs, coverage strategies A–D, W1 topology + W2 synthetic generator, W1/W2 runners, scalene dev dep | 2026-06-22 | bbc5987 | Verified | [260622-vlh-build-the-durable-evals-benchmark-harnes](./quick/260622-vlh-build-the-durable-evals-benchmark-harnes/) |
| 260623-ajs | Enriched end-of-run backtest summary print: 9 guarded derived metrics + format_backtest_summary grouped block (Capital/Trades/Risk-Return), run-level Period+Duration header, per-portfolio instrument list; display-only / oracle-inert | 2026-06-23 | ef0dd6e | | [260623-ajs-enriched-backtest-summary-print](./quick/260623-ajs-enriched-backtest-summary-print/) |
| fast | Rename `evals/` → `perf/` (reserve `benchmarks/` for cross-framework comparison); updated package imports, README commands, docstrings | 2026-06-23 | ee77f37 | | — |
| 260623-bmg | Fix perf coverage instruments B/C/D so positions recycle (boost trade density): added the missing exit leg to each (D short tp+sl bracket, B limit-long sl + tightened tp, C pyramiding tp) — 30d-slice fills jumped ~11→759, closed 0→291 across P2_B/P3_C/P4-6_D; coverage semantics unchanged | 2026-06-23 | 4cd2be7 | | [260623-bmg-fix-perf-coverage-instruments-b-c-d-so-p](./quick/260623-bmg-fix-perf-coverage-instruments-b-c-d-so-p/) |
| 260623-f80 | Fix perf coverage instrument A over-selling: removed the cash-sized discretionary crossunder exit (sized off FractionOfCash(0.95), not the held qty → sold 65 vs held 1 → net-short inventory mislabeled LONG → $100k→$10M phantom equity → fills froze after Jan); now bracket-only (OCO sl/tp) so longs close cleanly & recycle. A-only full-window: fills spread Dec–Jun (251, was frozen 184), closed 61→125, equity sane $76,452 (was phantom $10M). Surfaced a SEPARATE engine anomaly (spot LONG_ONLY over-sell allowed) → /gsd:debug | 2026-06-23 | 3657d30 | | [260623-f80-fix-perf-coverage-instrument-a-over-sell](./quick/260623-f80-fix-perf-coverage-instrument-a-over-sell/) |
| 260623-gao | Engine over-sell protection A+B (TDD, oracle-gated) for the spot LONG_ONLY over-sell / phantom-equity bug (diagnosed in .planning/debug/spot-long-only-oversell.md). A: ported the CR-02 over-close guard into the SPOT settlement path (portfolio.py _process_transaction_spot) — a reducing SELL exceeding held qty now raises InvalidTransactionError (was silent corruption). B: cancel orphaned bracket children on flatten-by-fill in the order domain (reconcile on_fill), scoped to (portfolio_id, ticker). Fix C (sign-aware net_quantity/market_value) left owner-gated/out-of-scope. Oracle byte-exact 134/46189.87730727451; e2e 72, full suite 1231 green; mypy --strict clean | 2026-06-23 | c004672 | Verified | [260623-gao-engine-over-sell-protection-a-b-spot-set](./quick/260623-gao-engine-over-sell-protection-a-b-spot-set/) |
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
| Phase 05 P03 | 25 | 2 tasks | 10 files |
| Phase 05 P04 | 40 | 2 tasks tasks | 6 files files |
| Phase 05.1 P01 | 12 | 3 tasks | 3 files |

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

Last session: 2026-06-17T13:54:24.830Z
Stopped at: Phase 6 context gathered
Resume file: .planning/phases/06-pair-trading-flagship/06-CONTEXT.md

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
