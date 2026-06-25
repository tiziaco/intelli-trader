---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: Backtest Performance Optimization
status: ready_to_plan
stopped_at: Phase 08 complete (6/6) — ready to discuss Phase 999.2
last_updated: 2026-06-25T16:34:34.817Z
last_activity: 2026-06-25 -- Phase 08 execution started
progress:
  total_phases: 10
  completed_phases: 7
  total_plans: 26
  completed_plans: 26
  percent: 70
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-23 — v1.5 Backtest Performance Optimization STARTED; Persistence split out to a following milestone)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers. v1.5 makes that run **faster** — profiler-ranked, oracle-gated hot-path optimizations against the frozen W1 baseline (240.8 s / 167.3 MB), changing the numbers nowhere — **except Phase 5, which deliberately re-baselines the oracle (cross-validated), see carve-out below.**
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-25

> NOTE: `phase.complete` advanced Current Position to **Phase 06** (scanner artifact — see memory
> `phase-complete-jumps-to-backlog`). Corrected manually: Phase 6 already ran BEFORE Phase 5 (the
> 6-before-5 reorder), so it is NOT "next". With Phase 5 now complete, ALL SIX v1.5 phases (1-6) are
> Complete — **v1.5 (Backtest Performance Optimization) is finished**. The next step is milestone close
> (`/gsd-complete-milestone`), not a new phase. 999.2/999.3 remain FUTURE-milestone backlog seeds.
> Carried todo **CLEARED 2026-06-25** (quick `260625-0qj`): Gate (b) W1/W2 baselines re-frozen on a
> verified-cool box (`pmset` clean, in-battery HEAD drift +0.9%) — **W1 153.7 s / 162.3 MB**, **W2 4.05 s
> @50 / 210.87 MB**. Cool same-machine A/B attributes Phase 5: **W1 −40.1%** (255.4 s→153.0 s) and
> **W2@50 −70.2%** (13.61 s→4.05 s), Gate (a) byte-exact 134/46189.87730727451, owner sign-off tiziaco.
> See `.planning/quick/260625-0qj-refreeze-w1-w2-baseline-cool/ATTRIBUTION.md`. v1.5 ready for milestone close.

## Milestone Gate (v1.5 — behavior-preserving performance; applies to EVERY optimization phase)

**This is the perf analog of v1.2 Consolidation: it re-baselines NOTHING — EXCEPT Phase 5.** Every
optimization phase **2, 3, 4, 6** is gated on BOTH gates below with byte-exact Gate (a). **Phase 5
is the exception** (reframed by spec 2026-06-24, `05-CONTEXT.md` P5-D01): it drops `ta` on the runtime
path and **deliberately re-baselines the SMA_MACD oracle** — its Gate (a) becomes a re-baseline +
cross-validation freeze (backtesting.py + backtrader, 1% rel tol), not byte-identity (P5-D02). Trade
dates/count (134) are expected to stay identical (firing tick preserved); numeric equity/PnL drift.

1. **Gate (a) — oracle lock:** `tests/integration/test_backtest_oracle.py` — SMA_MACD **134 trades /
   `final_equity 46189.87730727451`** for Phases 2/3/4/6 (byte-exact). **Phase 5 re-baselines this
   number** via cross-val freeze (P5-D02) — the new reference is frozen + regression-locked.

2. **Gate (b) — measurable, locked W1 improvement:** the clean W1 benchmark shows a real wall-clock
   and/or peak-memory reduction vs the frozen baseline (**240.8 s / 167.3 MB**), **re-frozen after
   the phase** as the new locked reference the next phase is judged against. **v1.5-final locked
   reference: W1 28.3 s / 162.3 MB (re-frozen 2026-06-25 on branch `perf/w1-benchmark-indexed-active-query`
   after a W1-benchmark-probe bug fix) · W2 4.05 s @50 / 210.87 MB (re-frozen cool 2026-06-25, quick
   `260625-0qj`).** NOTE: the W1 28.3 s figure is NOT comparable to the prior 153.7 s — the drop is a
   benchmark-probe fix (per-bar `get_orders_by_status` full-scan → indexed `get_active_orders`),
   workload byte-identical (1578 fills / 659 closed), engine untouched. Do NOT diff post-fix W1
   numbers against any pre-fix figure.

Phase 1 (tooling) **builds** gate (b)'s measurement harness and re-freezes the baseline; it changes
no engine code and is held to gate (a) only.

**Held throughout, all phases:**

- `mypy --strict` clean across all source files
- Decimal end-to-end — no new float-for-money; **every fix is *less repeated work*, never a float
  swap** (`float()` stays only at the serialization/logging edge); single UUIDv7 ID scheme

- Determinism double-run byte-identical (reuse the seeded RNG + injected `BacktestClock`; introduce
  no new nondeterminism)

**Two scope exceptions (LOCKED):**

- **Opportunistic in-file CONCERNS cleanups** are allowed ONLY where a perf phase already edits that
  file (notably P3 in `position_manager.py` / `portfolio.py`), as separate atomic commits, oracle
  staying green — zero behavior change. General CONCERNS.md tech debt stays OUT (its own future sweep).

- **Persistence is split out** to its own following milestone (N+3b) — PostgreSQL storage + FL-06 are
  live-path, DB-gated, not covered by the backtest oracle. PERF-01 designs the `OrderStorage`
  interface for extension so that backend can satisfy the same contract later.

## Phase Map (v1.5 — Phases 1-6)

Execution order: 1 → 2 → 3 → 4 → 5 → 6. Derived from the 10 v1.5 requirements + the
`perf/results/PERF-BASELINE-RESULTS.md` §6 sequencing (payoff × safety; low-risk/no-numeric-surface
first, the dangerous oracle-gated indicators LAST, optional contract-gated bar-feed work as a
slip-able final phase). Numbering reset to Phase 1 (matching v1.1/v1.2/v1.3/v1.4). The only dirs in
`.planning/phases/` are the `999.2`/`999.3` backlog placeholders (999.x prefix — no collision with
the new `01-*..06-*` dirs); they are FUTURE milestones, left intact (999.3 = N+4 live; 999.2's
persistence half is deferred to its own next milestone).

| Phase | Name | Requirements | Hotspot(s) | Gate | Depends on |
|-------|------|--------------|------------|------|------------|
| 1 | Perf Tooling & Baseline | TOOL-01/02/03/04 | — (harness) | (a) only — no engine code; re-freeze baseline | — |
| 2 | Order-Storage Indexing | PERF-01 | #1 (~37% CPU) | (a) + (b) | 1 |
| 3 | Running PnL Accumulator | PERF-02 | #3 (~13% CPU) | (a) + (b) | 1 |
| 4 | Hot-Path Discipline | PERF-03, PERF-04 | #4 (~6%W1/22%W2) + #6 (~2%W1/14%W2) | (a) + (b) | 1 |
| 5 | Incremental Indicators (FRAGILE, LAST) | PERF-05 | #2 + #7 (~24% CPU) | (a) + (b) — oracle is THE lock | 1 |
| 6 | Bar-Feed Window Copies (OPTIONAL, slip-able) | PERF-06 | #5 (~4%W1/22%W2) | (a) + (b) — contract-gated | 1 |

**Sequencing rationale:** P1 is the prerequisite — it builds the measurement harness every later
phase's gate (b) depends on and re-freezes the baseline before any optimization. Then optimizations
run low-risk/high-return first and the dangerous one last: P2 order-storage indexing (~37%, pure
data-structure, no numeric surface) → P3 running PnL accumulator (~13%, less re-summation, Decimal
preserved) → P4 hot-path discipline (logging PERF-03 + `get_type_hints` PERF-04, both behavior-only
with no numeric surface, merged into one clean phase) → **P5 incremental indicators (~24%,
oracle-gated, isolated LAST** so a byte-exactness regression is attributable) → P6 optional bar-feed
window copies (contract-gated by the look-ahead 7 rules, slip-able to a follow-on without blocking
the core). Every optimization phase depends on Phase 1 (the harness/baseline must exist to measure
gate (b)); P2-P6 are otherwise independent subsystems sequenced by payoff.

## Performance Metrics

**Velocity (v1.3):**

- Total plans completed: 82
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

- **Phase 5 / 05-02 (LOCKED):** all four indicators (SMA/EMA/MACD/RSI) are now hand-written O(1)
  stateful recurrences (`ta` DROPPED on the runtime path, P5-D11/D12). The SMA_MACD oracle re-baseline
  (P5-D02) was confirmed **BYTE-IDENTICAL** (134 / 46189.87730727451 unchanged) — numerically
  transparent because the indicators gate decisions via boolean primitives only and never enter the
  money arithmetic; cross-validated PASS (backtesting.py −0.35%, backtrader exact, 134 both); owner
  sign-off: tiziaco (tiziano.iaco@gmail.com), 2026-06-24, P5-D02. No golden re-freeze was required.
  RSI Pitfall-1 landmine: `ta` seeds `up[0]=dn[0]=0.0` at bar 0 (diff[0]=NaN → `.where` → 0.0), NOT
  bar-1 first-gain.

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
- [Phase 01]: 01-02 (TOOL-04): W1-BASELINE.json FROZEN from a single clean `make perf-baseline` run (247.5s / 167.3MB, 1578 fills / 659 closed; D-03 not best-of-N) with the D-01 schema — metric.{wall_clock_s,peak_mem_mb}, window 2026-04-23→2026-06-23, frozen_at 2026-06-23, oracle_provenance.final_equity STRING constant 46189.87730727451 (OQ-1/A1 provenance stamp, never W1-derived). Trackable (not gitignored; Pitfall 4), committed b56afdd. Soft regression guard PROVEN both arms: positive `make perf-w1` printed Δ +0.2% wall / +0.0% mem and exited 0 (within ±5% noise); negative path (committed baseline lowered ~20% to 198.0s) made the ~248-253s run read Δ +27.7%, printed `PERF REGRESSION ... gate (b) guard FAILED`, exited non-zero; restored via `git checkout` → `git diff --quiet` clean (T-01-03 mitigated, no tamper left). Gate (a) green at freeze AND after (134 / 46189.87730727451); NO itrader/ engine code touched. This is the locked reference every later v1.5 phase's gate (b) diffs against.
- [Phase 01]: 01-01 (TOOL-01/02): perf tooling surface built — make perf-w1/w2/baseline/profile (+ user-added perf-view) in the root Makefile; perf-w1 is PROFILER-FREE and perf-profile is the ONLY Scalene path (two-step run->view; user switched the viewer from --html to native `scalene view` local-server, approved deviation 4fa61d1/4d50996, TOOL-02 split intact). run_w1_benchmark.py gained --json/--check/--baseline-out (D-06 human-stdout default) + _to_baseline_schema/_write_baseline/_check_regression (soft guard fails ONLY on >+5% slowdown, no abs(), Pitfall 3); run_w2_sweep.py gained --json. D-07: _START_DATE default pinned 2025-12-24->2026-04-23 (env-overridable). final_equity stored as STRING constant 46189.87730727451 (OQ-1/A1 provenance, not W1-derived). Narrow .gitignore (scalene-profile.html + perf/results/scalene-*.json) keeps W1-BASELINE.json trackable (Pitfall 4). Gate (a) green 134/46189.87730727451; NO itrader/ engine code touched. Scalene hotspot confirmed: in_memory_storage 48% (P2), position_manager 17% (P3), indicators/catalog 18% (P5).
- [Phase ?]: [Phase 02]: 02-01 (PERF-01) — InMemoryOrderStorage gained derived active-by-portfolio + active-only by-status indexes (dict[oid,None]) over a _last_indexed_status shadow registry (D-03) atop the flat _by_id source of truth (D-20); shared _index_apply diff-on-write at all 5 write seams; active queries/scanners rerouted (None scan-fallback keeps GLOBAL order byte-identical, Pitfall 1); ABC UNCHANGED (D-05) + D-05a SQL-expressibility audit in-code; gate (a) PASSED (oracle 134/46189.87730727451, determinism 9/9, mypy strict 187). Gate (b) perf = Plan 02.
- [Phase 03]: 03-01 (PERF-02) — running Decimal realised-PnL accumulator on PositionManager (_realised_pnl_accumulator, seed Decimal('0.00'), no mid-sum quantize) replaces the per-bar dual open+closed re-sum in get_total_realized_pnl (now a bare `return self._realised_pnl_accumulator`, D-01/D-04 dead-loop collapse). Fed via apply_realised_increment from BOTH Portfolio settle arms — the SPOT arm (SMA_MACD oracle path) had NO explicit realised_increment today and was wired with pre/post capture (audit finding, 03-INVARIANT-AUDIT.md §5); MARGIN arm reuses the existing increment on the CLOSE branch only (D-02). Three-layer correctness lock: written single-funnel invariant audit (03-INVARIANT-AUDIT.md) + byte-exact oracle/determinism + dedicated equivalence regression test (accumulator == fresh full re-sum, D-03). Gate (a) byte-exact 134/46189.87730727451, mypy --strict clean (187 files), full suite 1241 passed, determinism double-run byte-identical. Gate (b) W1 wall-clock re-freeze = Plan 02.
- [Phase ?]: [Phase 06]: 06-03 (PERF-06 / D-13 denominator cleanup, PREP before the cursor) — removed the per-bar TIME EVENT debug block from EventHandler._dispatch (eager f-string every bar, discarded at INFO, ~22% W2 CPU) and de-timed run_w2_sweep._run_point into two passes (clean perf_counter wall-clock, NO tracemalloc in the timed region + separate fresh-wired tracemalloc peak-mem, same seed=42); _wire_system helper factored, return dict shape + 06-02 --check/--baseline-out flags unchanged. Behavior-neutral: gate (a) byte-exact 134/46189.87730727451, mypy --strict clean (187 files); re-baselines NOTHING numeric (cleaned baselines re-freeze 06-05). Commits 15834d7 + 43e5e72.
- [Phase 06]: 06-04 (PERF-06 / D-10 monotonic cursor) — BacktestBarFeed.window() resolves the cutoff via a per-(ticker,alias) forward int64 cursor over frame.index.asi8 (`iv_i8[pos] <= cutoff_i8`, `cutoff_i8 = pd.Timestamp(cutoff).value`) replacing the per-tick searchsorted (13.2% W2); byte-identical to searchsorted(side="right"). Cold key OR `cutoff_i8 < last_cut` → silent safe searchsorted rebuild (never leak a future bar, D-10 reset-safety). The `iloc[start:pos]` read-only view + D-06 empty short-circuit are KEPT cursor-only (D-11 cheaper-slice empirically infeasible — every candidate slower than iloc, D-07 forbids reconstruction; D-12 built on 06-01 9168cae, NOT reverted). D-16: cursor==searchsorted + no-future-bar proven in the EXTENDED D-08 test suite only, NO hot-loop runtime assert. Deviation (Rule 3): `cutoff.value` → `pd.Timestamp(cutoff).value` for mypy --strict (asof typed `datetime`, no `.value`). Gate (a) byte-exact 134/46189.87730727451, determinism double-run identical (SHA-256), mypy --strict clean (187 files), full suite 1262 passed. Commits d034ea3 + 00c5480. Gate (b) W2/W1 re-freeze deferred to 06-05 (cool machine, D-14).
- [Phase 05]: 05-01 (PERF-05, Plan A — shared recent-bars feed data layer, BYTE-EXACT plumbing) — `BarFeed` now owns the shared recent-bars API: (1) new pure `itrader/price_handler/feed/cache_registration.py::derive` — derive-once-at-wiring mirror of `universe/instruments.py::derive_instruments` (no class/state/queue/feed/store import, sorted/deduped/laddered), keys cache capacity off **RAW-BAR consumers NOT indicator min_period** (P5-D07/D22: indicators self-buffer under Model B); empty consumer set → newest-bar-only depth 1, deep multi-bar cache DEFERRED to the first raw-bar consumer (`.planning/todos/deep-shared-bar-history.md`). (2) G5 newest-bar unify (P5-D16a): the cache newest-row write rides the **EXISTING** `current_bars` per-symbol walk so `newest_bar(ticker)` IS `BarEvent.bars[ticker]` (one source of truth) — NO second loop (for-ticker count stays 2). (3) G1 (P5-D16b): module-level `assert_update_trigger` interface-only `base_timeframe <= min(timeframe)` causality guard; golden 1d==base collapses to "every tick"; multi-timeframe consolidator deferred. **A3 byte-exact held**: `window()` D-08/D-10 monotonic int64 cursor + 7-rule bar-timing contract byte-for-byte unchanged (git diff shows no window-body edits), SMA_MACD oracle byte-exact 134/46189.87730727451, mypy --strict clean (188 files), 61 price+integration tests green + 6 new Plan-A tests. Deviation (Rule 3): narrow `.gitignore` negations un-ignore the two `*cache*`-named tracked files (the broad `**cache**` rule matched them by filename; plan mandates the exact filenames). Plan B (stateful indicators, P5-D07 self-buffer, does NOT read this cache) unblocked structurally — still gated only on the G2 seeding decision P5-D04. Commits 5be5047 + 86ff5b2 + 484724f.

- [Phase 05]: 05-03 (PERF-05, Plan C — per-tick window slice CUT, pair migrated, BYTE-EXACT vs the Plan-02 re-baseline) — the per-tick `feed.window()` master-frame slice + the `len(data)<warmup` gate are removed ENTIRELY for BOTH the single-leg and pair paths (P5-D13/D14). The handler loop is now `strategy.update(ticker,bar)` -> `if not strategy.is_ready(ticker): continue` -> `generate_signal(ticker)`; the bar-is-None gap skip STAYS (= no-update, state frozen, P5-D10c). Per-symbol fan-out is a STATE-SWAP on the SINGLE registration handle-set (`_activate_ticker` + `IndicatorHandle.snapshot_state/load_state/fresh_state`) — the author-bound `self.short_sma` reflects the active ticker WITHOUT the base knowing the attr name (P5-D21); this FIXED a Plan-B design bug where separate per-ticker handle objects left `self.short_sma` reading an un-updated handle (read-before-warm crash). `self.now = bar.time` (a tz-aware Timestamp byte-identical to the legacy `window.index[-1]`), NOT the literal `event.time` (a plain datetime with no `.tz_convert` — would break ~12 e2e scenarios). The pair runs on β fit-once-frozen over the oldest 250 of a bounded `maxlen=280` per-leg buffer + z bounded-window over 30, fed by multi-input `update_pair(bar_A,bar_B)` (P5-D09); `_buffers_as_windows()` renders the bounded buffers as the `(win_A,win_B)` the PRESERVED window-based β/z helpers read — byte-identical to the removed `feed.window(280)` (β/z math, `_crosses_into/_inside` band logic, `_in_pair` flag, non-finite-z guard, β→`to_money` fence all UNTOUCHED). Count/date fixtures migrated off `self.bars` onto `bar_count`/`latest_bar` (firing preserved, P5-D13a); the indicator-free multi-bar strategies (limit_entry_crossval + perf a/b/c/d + run_w2_sweep) migrated onto a new `recent_closes(ticker)` seam (Rule-3, required for the full-suite gate). GATE (a) GREEN: SMA_MACD oracle byte-exact 134/46189.87730727451 (behavioral + numeric), pair flagship snapshot byte-for-byte, full suite 1287 passed, mypy --strict clean (188 files), determinism double-run BYTE-IDENTICAL (SHA-256). Commits 37f6a4e + 44222bb + 094a345.

### Pending Todos

- **[BEFORE Phase 4 gate (b)] Re-freeze W1-BASELINE.json on a cool machine (captured 2026-06-24).**
  Phase 3 (PERF-02) delivered a proven ~15% wall-clock win (same-machine A/B 317.5s→268.4s; Scalene
  CPU share `position_manager.py` 16.21%→0%; profiled elapsed −29.6%), but the re-freeze (Plan 03-02
  Task 2) was **deferred**: the box was thermally throttled on 2026-06-24 (old code itself read 317.5s
  vs the 199.4s frozen yesterday), so no run that day could produce a clean reference. `W1-BASELINE.json`
  still holds the **Phase-2 199.4s** number. **Action:** on a cool/quiet machine, in the main checkout,
  run `make perf-baseline` then commit — BEFORE Phase 4's gate (b) is measured, else Phase 4 diffs
  against a pre-Phase-3 baseline and over-credits its own win by ~15%. Evidence + hotspot map in
  `.planning/phases/03-running-pnl-accumulator/03-02-SUMMARY.md`.

- **[Phase 4 / PERF-03] Demote the W1 sub-minimum rejection log (captured 2026-06-23).** W1 runs emit
  frequent `error`-level `OrderHandler` "Quantity ... below minimum 0.001" logs — the `FractionOfCash`
  coverage strategies size to dust as portfolio cash depletes and the validator correctly refuses them
  (NOT a correctness defect; SMA_MACD oracle unaffected). The `error`-level volume costs CPU in the
  timed loop → a legitimate PERF-03 win (folds into Phase 4 criterion #1). **HOW is undecided — discuss
  at Phase 4 discuss/plan time** (demote vs level-gate vs sample vs drop; ensure clean gate-(b)
  attribution + re-freeze). Do NOT change `min_order_size` or coverage sizing to silence it (wrong
  lever, re-bakes the frozen baseline — decided Phase 1). Full note in ROADMAP §"Phase 4: Hot-Path
  Discipline".

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
| 260625-0qj | Re-froze v1.5 Gate (b) baselines on a verified-cool box (clears the carried thermal-defer todo) + attributed Phase 5. `pmset -g therm` clean; cool same-machine A/B (de2e19f vs HEAD via `make perf-w1`, identical 1578-fill workload, OLD bracketed between two HEAD runs → in-battery HEAD drift +0.9%, no throttle): **W1 −40.1%** (255.4→153.0 s), peak-mem flat. New frozen W1 153.7 s / 162.3 MB (was stale Phase-6 238.5 s) + W2 4.05 s @50 / 210.87 MB (was 13.61 s → **W2@50 −70.2%**). Gate (a) byte-exact 134/46189.87730727451 (3 passed). Owner sign-off tiziaco 2026-06-25. No engine code touched | 2026-06-25 | 7a630b2 | Verified | [260625-0qj-refreeze-w1-w2-baseline-cool](./quick/260625-0qj-refreeze-w1-w2-baseline-cool/) |
| 260623-h6i | Refine the over-close guard (spot + margin twin, portfolio.py) to compare the over-sell excess against the existing PositionManager.tolerance (1e-5) instead of strict `>`. Surfaced when the full W1 re-run fail-fast aborted on coverage instrument C (pyramiding): the "over-sell" was 1E-27 BTC — last-digit Decimal noise from independent per-add bracket-child quantization after partial closes, NOT a real over-sell (A/B completed with sane equity). Now sub-close-tolerance dust is absorbed as a clean full close; a GROSS over-sell (the 64-BTC phantom-equity case) still raises loudly at both sites. TDD; oracle byte-exact 134/46189.87730727451; e2e 72, full suite 1233 green; mypy --strict clean | 2026-06-23 | 09d49b1 | Verified | [260623-h6i-refine-over-close-guard-with-tolerance-a](./quick/260623-h6i-refine-over-close-guard-with-tolerance-a/) |
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
| v1.5 Phase 01 P01 | ~5 (hands-on) | 3 tasks (2 auto + 1 checkpoint) | 4 files |
| v1.5 Phase 01 P02 | ~18 (3× ~240s benchmark runs) | 2 tasks (both auto) | 1 file |
| Phase 02 P01 | 4 | 3 tasks | 2 files |
| Phase 03 P01 | 5 | 3 tasks | 4 files |
| Phase 06 P03 | 2 | 2 tasks | 2 files |
| Phase 06 P04 | 5 | 2 tasks | 2 files |
| v1.5 Phase 05 P01 | ~10 | 3 tasks | 5 files |
| v1.5 Phase 05 P03 | ~40 | 3 tasks | 16 files |

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

Last session: 2026-06-25T13:34:48.650Z
Stopped at: Phase 8 context gathered
Resume file: .planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-CONTEXT.md
Carried todo: none — the v1.5 Gate (b) cool re-freeze is done. v1.5 is ready for `/gsd-complete-milestone`.

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone

| 2026-06-25 | fast | Switch W1 on_tick to indexed get_active_orders (de-noise profile) | ✅ |
| 2026-06-25 | fast | Drop 4 hot-path eager-arg debug logs (bracket_manager x3, simulated x1) | ✅ |
