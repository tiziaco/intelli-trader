# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- 🚧 **v1.5 — Backtest Performance Optimization** — Phases 1-6 (active; numbering reset; performance half of Backlog 999.2, split out from Persistence)
- 📋 **N+3b — Persistence** — Backlog (the persistence half of 999.2, split out; follows v1.5)
- 📋 **N+4 — Live Trading Readiness** — Backlog (planned)

Full milestone detail (phase goals, success criteria, per-plan breakdown) is archived per milestone:
v1.0 — [`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md) ·
[`v1.0-REQUIREMENTS.md`](./milestones/v1.0-REQUIREMENTS.md) ·
[`v1.0-MILESTONE-AUDIT.md`](./milestones/v1.0-MILESTONE-AUDIT.md);
v1.1 — [`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md) ·
[`v1.1-REQUIREMENTS.md`](./milestones/v1.1-REQUIREMENTS.md) ·
[`v1.1-MILESTONE-AUDIT.md`](./milestones/v1.1-MILESTONE-AUDIT.md);
v1.2 — [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md) ·
[`v1.2-REQUIREMENTS.md`](./milestones/v1.2-REQUIREMENTS.md) ·
[`v1.2-MILESTONE-AUDIT.md`](./milestones/v1.2-MILESTONE-AUDIT.md);
v1.3 — [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md) ·
[`v1.3-REQUIREMENTS.md`](./milestones/v1.3-REQUIREMENTS.md) ·
[`v1.3-MILESTONE-AUDIT.md`](./milestones/v1.3-MILESTONE-AUDIT.md);
v1.4 — [`milestones/v1.4-ROADMAP.md`](./milestones/v1.4-ROADMAP.md) ·
[`v1.4-REQUIREMENTS.md`](./milestones/v1.4-REQUIREMENTS.md) ·
[`v1.4-MILESTONE-AUDIT.md`](./milestones/v1.4-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`; v1.4 under `milestones/v1.4-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **v1.5 — Backtest
> Performance Optimization** (active) promotes the **performance half** of Backlog 999.2 — the
> profiler-guided, oracle-gated hot-path pass — and **splits Persistence out** into its own
> following milestone (N+3b). The remaining `999.x` entries are future milestones (Persistence,
> N+4 live).

## Phases

### 🚧 v1.5 — Backtest Performance Optimization (Phases 1-6) — ACTIVE

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3/v1.4). The performance analog of v1.2
Consolidation: a **behavior-preserving** milestone that cuts the frozen W1 baseline (240.8 s /
167.3 MB) via profiler-ranked, oracle-gated hot-path optimizations — **changing no numbers**. Every
optimization phase is gated on BOTH (a) the byte-exact SMA_MACD oracle staying green (134 trades /
`final_equity 46189.87730727451`, `tests/integration/test_backtest_oracle.py`) AND (b) a measurable,
locked W1 wall-clock and/or peak-memory improvement vs the frozen baseline, re-frozen after the
phase. Held throughout: `mypy --strict` clean; Decimal end-to-end (every fix is *less repeated work*,
never a float swap); single UUIDv7; determinism double-run byte-identical. Source: the v1.5 spike
[`perf/results/PERF-BASELINE-RESULTS.md`](../perf/results/PERF-BASELINE-RESULTS.md) (the spike IS the
research). Full detail in [`milestones/v1.5-ROADMAP.md`](./milestones/v1.5-ROADMAP.md).

- [x] **Phase 1: Perf Tooling & Baseline** — root-Makefile `perf-*` targets, two-mode benchmark/Scalene-profile runner, re-freeze the baseline to a committed `W1-BASELINE.json` + soft regression guard (gate (b) = ≥5% wall-clock) (TOOL-01, TOOL-02, TOOL-04 — TOOL-03 cross-val dropped 2026-06-23)
- [x] **Phase 2: Order-Storage Indexing** — derived secondary indexes over the flat `{id: order}` dict (D-20 source of truth), Postgres-extensible interface (PERF-01, ~37% CPU)
- [x] **Phase 3: Running PnL Accumulator** — maintain realised PnL on close, stop the per-bar re-sum; opportunistic in-file CONCERNS cleanups allowed (PERF-02, ~13% CPU)
- [x] **Phase 4: Hot-Path Discipline** — level-gate hot-loop logs + drop per-bar `debug()`; memoize `get_type_hints` in `Strategy.to_dict` (PERF-03 + PERF-04, ~8% W1 / ~36% W2)
- [ ] **Phase 5: Incremental Indicators (FRAGILE, oracle-gated, LAST)** — rolling/memoized SMA & MACD replacing the per-bar full-window `ta` rebuild, byte-exact (PERF-05, ~24% CPU)
- [ ] **Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able)** — reduce per-tick `iloc` frame copies, preserving the look-ahead bar-timing contract (PERF-06, ~4% W1 / ~22% W2)

## Phase Details

### Phase 1: Perf Tooling & Baseline
**Goal**: A repeatable measurement harness exists in the root Makefile so every later phase has an
honest, gated way to prove its W1 improvement — and the W1 baseline is re-frozen as the locked
reference before any optimization touches engine code.
**Depends on**: Nothing (first phase; the prerequisite for every optimization gate)
**Requirements**: TOOL-01, TOOL-02, TOOL-04 (TOOL-03 cross-validation **dropped** 2026-06-23 — see note below)
**Success Criteria** (what must be TRUE):
  1. The root Makefile exposes a `make perf-*` command surface (at least `perf-w1`, `perf-w2`,
     `perf-baseline`, `perf-profile`) that inherits `include .env` / `.EXPORT_ALL_VARIABLES`.
  2. The W1 runner has two clearly separated modes — a clean **benchmark** (profiler-free, the gated
     timing run that produces the frozen number) and a **separate** Scalene `--cpu-only --html
     --program-path` **profile** command that writes a gitignored HTML artifact; profiling never
     wraps the timed/gated run.
  3. The W1 baseline is re-frozen by a clean benchmark run after TOOL-01..02 land and BEFORE any
     optimization — recorded in a committed machine-readable `perf/results/W1-BASELINE.json` as the
     locked reference (≈ 240.8 s / 167.3 MB) every later phase is judged against. `perf-w1` prints
     the delta vs it with a soft regression guard; gate (b) "measurable" = ≥5% wall-clock improvement
     (single timed run; peak memory tracked alongside).
  4. The byte-exact SMA_MACD oracle is green (134 trades / `final_equity 46189.87730727451`); no
     engine code changed in this phase (tooling + measurement only).

> **TOOL-03 dropped (2026-06-23, owner decision, Phase 1 discussion):** the `backtesting.py` +
> `backtrader` cross-validation runners are removed from v1.5. v1.5 is behavior-preserving and gated
> on the byte-exact oracle — correctness is proven by *invariance*, not external *agreement*; the
> v1.0 `tests/golden/CROSS-VALIDATION.md` evidence stays valid since no numbers change. No
> `perf-crossval` target.
**Plans**: 2 plans
  - [x] 01-01-PLAN.md — perf-* Makefile targets + runner --json/--check/--baseline-out flags + D-07 window pin + Scalene .gitignore (TOOL-01, TOOL-02)
  - [x] 01-02-PLAN.md — re-freeze the committed W1-BASELINE.json + prove the soft regression guard (TOOL-04)

### Phase 2: Order-Storage Indexing
**Goal**: Order-storage queries stop linear-scanning the full flat `{id: order}` dict, removing the
single largest W1 hotspot (~37% CPU) — with the flat dict still the source of truth (D-20) and the
interface designed so a future Postgres backend satisfies the same contract.
**Depends on**: Phase 1 (the harness/baseline must exist to measure gate (b))
**Requirements**: PERF-01
**Success Criteria** (what must be TRUE):
  1. `get_orders_by_status`, by-portfolio, and active queries resolve via derived secondary indexes
     maintained over the flat dict — no O(all-orders-ever) rescan on the per-bar `on_tick` /
     admission / reconcile path.
  2. The flat `{id: order}` dict remains the source of truth (D-20 — all orders kept for audit); the
     indexes are caches kept consistent on every insert/transition/terminal write.
  3. The `OrderStorage` interface is designed for extension so a future Postgres backend satisfies
     the same contract (no in-memory-only assumptions leak into the seam).
  4. **Gate (a):** the byte-exact SMA_MACD oracle is green (134 / `46189.87730727451`); `mypy
     --strict` clean; determinism double-run byte-identical.
  5. **Gate (b):** the clean W1 benchmark shows a measurable wall-clock improvement vs the Phase 1
     re-frozen baseline, re-frozen as the new locked reference.
**Plans**: 2 plans
  - [x] 02-01-PLAN.md — index implementation (active_by_portfolio + active-only by_status + shadow registry), 5-write-seam maintenance, active-query rerouting, D-09 equivalence test + gate (a) (PERF-01)
  - [x] 02-02-PLAN.md — gate (b): human-run make perf-w1 (≥ 5% wall-clock), re-freeze W1-BASELINE.json (PERF-01)

### Phase 3: Running PnL Accumulator
**Goal**: Realised PnL is maintained as a running accumulator updated on position close, eliminating
the per-bar re-summation over all open+closed positions (~13% CPU) — Decimal preserved (this is
*less re-summation*, never a float swap).
**Depends on**: Phase 1 (harness/baseline). Independent of Phase 2 (different subsystem) but
sequenced after it by payoff order.
**Requirements**: PERF-02
**Success Criteria** (what must be TRUE):
  1. `get_total_realized_pnl` returns a running accumulator updated on position close — no per-bar
     re-sum over all positions; the `+=` stays Decimal.
  2. Per-bar equity/metrics that consumed the re-sum produce identical values to the baseline (the
     accumulator is mathematically equal to the prior sum at every bar).
  3. Opportunistic zero-behavior in-file CONCERNS cleanups in `position_manager.py` / `portfolio.py`
     are allowed as separate atomic commits with the oracle staying green (per the milestone scope
     exception) — no behavior change.
  4. **Gate (a):** the byte-exact SMA_MACD oracle is green (134 / `46189.87730727451`); `mypy
     --strict` clean; determinism double-run byte-identical.
  5. **Gate (b):** the clean W1 benchmark shows a measurable improvement vs the prior re-frozen
     baseline, re-frozen as the new locked reference.
**Plans**: 2 plans
  - [x] 03-01-PLAN.md — D-02 invariant audit + accumulator field/apply method + wire both spot & margin close arms + collapse the dead dual-loop + D-03 equivalence test + gate (a) (PERF-02)
  - [x] 03-02-PLAN.md — gate (b): human-run make perf-w1 (>= 5% wall-clock vs 199.4 s), re-freeze W1-BASELINE.json (PERF-02)

### Phase 4: Hot-Path Discipline
**Goal**: The per-bar path stops paying structural waste on two behavior-only sinks — hot-loop
logging (~6% W1 / ~22% W2) and re-resolved type hints (~2% W1 / ~14% W2) — neither of which has a
numeric surface, so they bundle cleanly into one discipline phase.
**Depends on**: Phase 1 (harness/baseline)
**Requirements**: PERF-03, PERF-04
**Success Criteria** (what must be TRUE):
  1. Hot-loop log calls are level-gated (cached `isEnabledFor`/bool); per-bar admission-rejection
     warnings are demoted/sampled; `debug()` calls are removed from the per-bar path — no log call
     pays pipeline overhead when it would not emit.
  2. `get_type_hints` is memoized per class in `Strategy.to_dict` (resolved once per class, not
     per signal snapshot) — identical hint output, no per-signal re-walk of the MRO.
  3. No emitted-log content or signal-snapshot content changes on any path the oracle or e2e leaves
     observe (behavior-only; demotion/sampling affects volume, not correctness).
  4. **Gate (a):** the byte-exact SMA_MACD oracle is green (134 / `46189.87730727451`); `mypy
     --strict` clean; determinism double-run byte-identical.
  5. **Gate (b):** the clean W1 benchmark shows a measurable improvement vs the prior re-frozen
     baseline, re-frozen as the new locked reference.
**Plans**: 3 plans
- [x] 04-01-PLAN.md — PERF-03 hot-loop logging: central level-gate (D-02) + admission demote (D-01) + ITRADER_DISABLE_LOGS (D-08) + curated debug deletes (D-04) + drift test/audit (D-06)
- [x] 04-02-PLAN.md — PERF-04: memoize get_type_hints via _declared_hints @cache (D-05) + equivalence/snapshot drift tests (D-07)
- [x] 04-03-PLAN.md — gate (b): same-machine A/B attribution + owner-signed re-freeze of W1-BASELINE.json

> **Note — captured during Phase 1 (2026-06-23), concrete instance of criterion #1:** the W1 timed run
> emits frequent `error`-level `OrderHandler` logs `Signal validation failed: Market validation failed -
> ['Quantity ... below minimum 0.001']`. Root cause: the `FractionOfCash` coverage strategies
> (A/B/C/D in `perf/strategies/`) size as `fraction × available_cash ÷ price`; as a portfolio's cash
> depletes (C pyramids uncapped to exhaustion; B shares one cash pool across 3 symbols), the computed
> quantity falls below the `0.001 BTC` venue minimum (`ExchangeLimits` fallback, BTCUSD
> `Instrument.min_order_size` undeclared per D-01a) and the market validator correctly refuses the dust
> order. **This is NOT a correctness defect** — the SMA_MACD oracle (134 / `46189.87730727451`) is a
> separate run and is unaffected — but the `error`-level log volume burns CPU inside the W1 timed loop,
> so demoting/sampling it is a legitimate PERF-03 win folded into criterion #1.
>
> **DISCUSS THE *HOW* AT PHASE 4 DISCUSS/PLAN TIME (do not pre-decide):** options include demote
> `error`→`debug`/`warning`, cached `isEnabledFor` level-gate, sample/rate-limit, or drop the per-signal
> rejection log entirely — and confirm clean measurement/attribution, since part of PERF-03's gate-(b)
> speedup would come from removing this spam (the post-phase re-freeze must account for it). **Decided in
> Phase 1 (do NOT revisit):** do NOT change `min_order_size` or the coverage-strategy sizing to silence
> it — that is the wrong lever and would re-bake the frozen W1 baseline.

### Phase 5: Incremental Indicators (FRAGILE, oracle-gated, LAST)
**Goal**: SMA & MACD compute incrementally (rolling/memoized) instead of a full-window `ta` rebuild
every bar — the largest single CPU chunk (~24%, hotspots #2+#7) — reproducing `[BYTE-EXACT]` output,
isolated as the last and highest-care phase with the oracle as the lock.
**Depends on**: Phase 1 (harness/baseline). Sequenced LAST and isolated (the byte-exact constraint
makes any bundled change unattributable).
**Requirements**: PERF-05
**Success Criteria** (what must be TRUE):
  1. `_SMA.compute` and `_MACDHist.compute` produce values **bit-identical** to the full-window `ta`
     rebuild they replace (no fresh `ta` object / re-slice / `dropna` copy per bar).
  2. The incremental state is look-ahead-safe and deterministic (no future bars visible; same
     warmup/visibility semantics as the framework-derived `warmup == max_window`).
  3. **Gate (a):** the byte-exact SMA_MACD oracle is green (134 / `46189.87730727451`) — this is the
     lock for the entire phase; `mypy --strict` clean; determinism double-run byte-identical.
  4. **Gate (b):** the clean W1 benchmark shows a measurable improvement vs the prior re-frozen
     baseline, re-frozen as the new locked reference.
**Plans**: TBD

### Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able)
**Goal**: Per-tick bar-feed window `iloc` frame copies are reduced (reusable view / cached slice
bounds), preserving the look-ahead bar-timing contract — the #1 framework cost in symbol-dense runs
(~22% W2, ~4% W1). Optional and slip-able to a follow-on without blocking the shippable core.
**Depends on**: Phase 1 (harness/baseline). Independent of Phases 2-5; sequenced last as the optional
contract-gated item.
**Requirements**: PERF-06
**Success Criteria** (what must be TRUE):
  1. Per-tick window materialization reduces frame copies (reusable view / cached `searchsorted`
     bounds) on the `BacktestBarFeed.window` path.
  2. The look-ahead bar-timing contract is preserved — all 7 rules in `feed/bar_feed.py` hold; no
     future bar becomes visible and no window content changes.
  3. **Gate (a):** the byte-exact SMA_MACD oracle is green (134 / `46189.87730727451`); the e2e
     suite is green; `mypy --strict` clean; determinism double-run byte-identical.
  4. **Gate (b):** the clean W1 benchmark shows a measurable improvement vs the prior re-frozen
     baseline, re-frozen as the new locked reference (most visible in the W2 symbol sweep).
**Plans**: 4 active plans (post-pivot — 06-01 kept; 06-02 Task 1 harness reused, its freeze/verify absorbed into 06-05)
  - [x] 06-01-PLAN.md — view-returning window() + memoized _offset_alias + read-only master frames at build sites (D-01/D-06/D-07/D-09) + D-08 drift/equivalence test + Gate (a) (PERF-06)
  - [~] 06-02-PLAN.md — Task 1 (run_w2_sweep --check/--baseline-out harness + Makefile, f51d7c6) COMMITTED + reused as-is; Tasks 2/3 (cool-machine freeze + verify) SUPERSEDED by 06-05 post-pivot (PERF-06)
  - [x] 06-03-PLAN.md — D-13 denominator cleanup (prep): remove per-bar TIME EVENT debug log + de-time run_w2_sweep two-pass; Gate (a) held (PERF-06)
  - [ ] 06-04-PLAN.md — D-10 monotonic int64 cursor in window() (replaces per-tick searchsorted) + D-16 drift-test extension; D-11 recorded infeasible (iloc kept, cursor-only); D-12 builds on kept 06-01; Gate (a) byte-exact (PERF-06)
  - [ ] 06-05-PLAN.md — D-14/D-15 gate (b): re-freeze BOTH baselines on the cleaned engine (cool machine) + cursor-alone ≥10% W2 verdict (or D-15 ship-and-reframe); absorbs 06-02 Tasks 2/3 (PERF-06)

<details>
<summary>✅ v1.4 — Margin, Leverage, Shorts & Trailing Stops (Phases 1-6 + 5.1) — SHIPPED 2026-06-22</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3). The crypto-derivatives surface —
per-symbol instruments, reserved-margin leverage, first-class shorts + borrow carry, isolated-margin
liquidation, engine-native trailing stops, short scale-in, and a market-neutral pair flagship. An
**owner-gated, result-changing** milestone: the three result-changing re-baselines (accounting core
P4, trailing P5, scale-in P5.1) were each frozen ONLY under explicit owner sign-off (tiziaco) +
external cross-validation (`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123); the SMA_MACD spot oracle
held byte-exact (134 trades / `final_equity 46189.87730727451`) across all 7 phases; `mypy --strict`
clean, Decimal end-to-end, determinism double-run byte-identical. Full detail in
[`milestones/v1.4-ROADMAP.md`](./milestones/v1.4-ROADMAP.md).

- [x] Phase 1: Instrument Value Object (3/3 plans) — completed 2026-06-15
- [x] Phase 2: Margin Accounting & Leverage (9/9 plans) — completed 2026-06-15
- [x] Phase 3: Shorts & Borrow Carry (6/6 plans) — completed 2026-06-15
- [x] Phase 4: Liquidation & Cross-Validation Re-baseline (6/6 plans) — completed 2026-06-16
- [x] Phase 5: Engine-Native Trailing Stops (5/5 plans) — completed 2026-06-17
- [x] Phase 5.1: Short Position Scale-In (INSERTED) (2/2 plans) — completed 2026-06-17
- [x] Phase 6: Pair-Trading Flagship (4/4 plans) — completed 2026-06-22

</details>

<details>
<summary>✅ v1.3 — Engine Surface Completion (Phases 1-6) — SHIPPED 2026-06-14</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2). Completes the signal/order contracts, the
composition/config interface, and the declared-indicator + strategy-authoring surface — the
result-changing / new-framework items deferred out of v1.2 Consolidation (promoted Backlog 999.5).
Two re-baseline disciplines, both honored: byte-exact phases (1-4) held the v1.1 E2E golden suite +
BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) byte-for-byte; owner-gated phases
(5-6) re-baselined only under explicit owner sign-off (tiziaco, 2026-06-13) + external
cross-validation. Full detail in [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md).

- [x] Phase 1: Engine Hygiene (1/1 plan) — completed 2026-06-12
- [x] Phase 2: Strategy Authoring Surface (3/3 plans) — completed 2026-06-12
- [x] Phase 3: Declared-Indicator Framework (3/3 plans) — completed 2026-06-12
- [x] Phase 4: Composition & Config Interface (5/5 plans) — completed 2026-06-12
- [x] Phase 5: Signal Contract & Reconcile (FRAGILE) (4/4 plans) — completed 2026-06-13
- [x] Phase 6: Order Lifecycle & Time-in-Force (4/4 plans) — completed 2026-06-13

</details>

<details>
<summary>✅ v1.0 — Backtest-Correctness Refactor (Phases 1-8) — SHIPPED 2026-06-08</summary>

8 phases (M1 → M5c), 62 plans. `SMA_MACD` runs end-to-end producing correct, deterministic,
cross-validated numbers (134 trades / `final_equity 46189.87730727451`). Full detail in
[`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md).

</details>

<details>
<summary>✅ v1.1 — Backtest Trustworthiness: Breadth (Phases 1-9) — SHIPPED 2026-06-10</summary>

Phase numbering reset to Phase 1 for v1.1. Spine: codebase map → data → universe → E2E
framework → interface hardening → scenario waves. LONG-ONLY throughout; behavior-preserving
(v1.0 golden numbers NOT re-baselined). Full detail in
[`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md).

- [x] Phase 1: Codebase Map & Clarity Baseline (2/2 plans) — completed 2026-06-09
- [x] Phase 2: Data Ingestion (1/1 plan) — completed 2026-06-09
- [x] Phase 3: Minimal Real Universe (3/3 plans) — completed 2026-06-09
- [x] Phase 4: E2E Harness & Framework (3/3 plans) — completed 2026-06-09
- [x] Phase 5: Strategy Interface Hardening & Signal Storage (3/3 plans) — completed 2026-06-09
- [x] Phase 6: Order Matching Scenarios (5/5 plans) — completed 2026-06-09
- [x] Phase 7: Cost, Sizing & SLTP Scenarios (4/4 plans) — completed 2026-06-10
- [x] Phase 8: Admission, Position Management & Cash Edges (3/3 plans) — completed 2026-06-10
- [x] Phase 9: Multi-Entity, Robustness & Metrics Edges (4/4 plans) — completed 2026-06-10

</details>

<details>
<summary>✅ v1.2 — Consolidation (Phases 1-6) — SHIPPED 2026-06-12</summary>

Behavior-preserving cleanup milestone — cleared the v1.1 cleanup-review backlog
(`V1.2-CLEANUP-REVIEW.md`, 46 findings) + the `CONCERNS.md` dead/fragile/tangled debt, byte-exact
against the golden master (134 trades / `final_equity 46189.87730727451`); re-baselined nothing.
Headline: `order_manager.py` decomposed 1279 → 210-line coordinator as pure code-motion. Full detail
in [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md).

- [x] Phase 1: Dead Code & Doc Hygiene (2/2 plans) — completed 2026-06-11
- [x] Phase 2: Locked-Decision Conformance (3/3 plans) — completed 2026-06-11
- [x] Phase 3: Hot-Path Performance (4/4 plans) — completed 2026-06-11
- [x] Phase 4: Type Modeling (5/5 plans) — completed 2026-06-11
- [x] Phase 5: Naming & Encapsulation (4/4 plans) — completed 2026-06-11
- [x] Phase 6: Order-Manager Decomposition (5/5 plans) — completed 2026-06-11

</details>

## Progress

**Active milestone — v1.5 Backtest Performance Optimization:**

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Perf Tooling & Baseline | 2/2 | Complete   | 2026-06-23 |
| 2. Order-Storage Indexing | 2/2 | Complete   | 2026-06-23 |
| 3. Running PnL Accumulator | 2/2 | Complete   | 2026-06-24 |
| 4. Hot-Path Discipline | 3/3 | Complete   | 2026-06-24 |
| 5. Incremental Indicators (FRAGILE) | 0/TBD | Not started | - |
| 6. Bar-Feed Window Copies (OPTIONAL) | 3/5 | In Progress|  |

**Shipped milestones** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |
| v1.4 — Margin, Leverage, Shorts & Trailing Stops | 1-6 + 5.1 | 35 | ✅ Shipped | 2026-06-22 |

**Next:** v1.5 active — plan Phase 1 with `/gsd:plan-phase 1`. After v1.5 ships, N+3b
(Persistence — the split-out half of 999.2) and N+4 (Live Trading Readiness) remain in the Backlog.

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+3b Persistence (after v1.5) → N+4**
> (the `N+x` labels carry the dependency order; the `999.x` decimals are just stable IDs
> and need not match the order). Promote one at a time with `/gsd:review-backlog` (or
> start it via `/gsd:new-milestone`); defer detailed planning until promotion so each
> milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) shipped as v1.1 (2026-06-10).** **v1.2 —
> Consolidation** (cleanup, Phases 1-6) shipped 2026-06-12. Engine Surface Completion (former
> Backlog Phase 999.5) shipped as **v1.3** (2026-06-14). **N+2 — Margin, Leverage, Shorts &
> Trailing Stops (former Backlog Phase 999.4) shipped as v1.4 (2026-06-22).** **Backlog 999.2 is
> SPLIT:** its performance half is **active as v1.5 — Backtest Performance Optimization**; its
> persistence half (below) is split out into its own following milestone. The remaining `999.x`
> entries are future milestones (Persistence, N+4 live).

### Phase 999.2: N+3b — Persistence (BACKLOG — performance half promoted to v1.5)

**Goal:** Durable PostgreSQL state — the infra prerequisite for live trading. The performance half
of this backlog entry was **split out and promoted to v1.5** (Backtest Performance Optimization,
active); **persistence remains here** as its own following milestone. Sequenced AFTER the
performance work so we are not persisting unvalidated behavior.
**Requirements:** TBD (PERSIST-01..03 seeded in v1.5 `REQUIREMENTS.md` v2 section)
**Plans:** 0 plans

> **SPLIT (2026-06-23):** the **#5 profiler-guided performance pass** was promoted to **v1.5**
> (`perf/results/PERF-BASELINE-RESULTS.md` is the spike research; 10 reqs TOOL-01..04 + PERF-01..06).
> Persistence is a live-path, DB-gated concern not covered by the backtest oracle (a different North
> Star), so it follows v1.5 as its own milestone rather than bundling with the perf gate.

Scope (intent only, persistence half):

- **#4 permanent PostgreSQL storage** (orders, signals, fills, equity).
  `PostgreSQLOrderStorage` is currently a `NotImplementedError` placeholder. The v1.5
  order-storage indexing (PERF-01) designs its interface for extension so this backend satisfies
  the same contract.

- **#1 continued** — structural cleanup that the live-mode transition specifically demands.
- **FL-06** — SQL injection + hardcoded creds in `SqlHandler` (deferred out of v1.3; module
  is quarantined, belongs with persistence/SQL work).

Rationale: persistence is cross-cutting live-path infra; sequenced after v1.5 perf so the engine it
persists is both fast and validated.

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.3: N+4 — Live Trading Readiness (capstone) (BACKLOG)

**Goal:** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence), and a streaming data engine.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):

- **#6 real-time data engine** ready for live.
- **#2 live execution engine.**
- **#7 production-ready universe / screener.**
- **Dynamic universe membership** — a lean `UniverseSelectionModel` poll seam for mid-run
  adds/removes (distinct from, and a prerequisite step toward, the full production screener
  above; grows in `universe/membership.py` per its documented D-20 growth target). Engine
  integration edges: warmup-on-add and open-position-handling-on-remove. Orthogonal to N+2
  (its pair-trading validation uses a fixed pair); sequenced here because it pairs with the
  real-time data engine (#6).
- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage (deferred out of v1.3; the
  live surface, not the backtest engine surface).
- **Perp realism — "Phase B" (FUND-01..04, deferred out of v1.4)** — funding-rate accrual at
  funding-timestamp boundaries, mark-price liquidation trigger (resolves phantom-wick risk),
  funding-data pipeline (ccxt `fetchFundingRateHistory` → per-symbol CSV; per-symbol interval, no
  hardcoded 8h), and `freqtrade` as a fourth cross-validation oracle. Purely additive on the v1.4
  Phase A core — only the carry model + liquidation trigger-price change. May land as its own
  milestone or fold into N+3/N+4 data work (see `notes/margin-leverage-shorts-999.4.md` §8).
- **Account abstraction (born here, with the connector)** — introduce a first-class `Account`
  domain object as the **reconciled local mirror of the venue's balance/margin state**. The
  **connector is the exchange adapter** (API keys, order I/O, fill/balance/funding streams — the
  `AbstractExchange`/provider boundary); the adapter *writes into* the `Account`, the `Account`
  does NOT talk to the venue. It is born here, not earlier, because in live the **source of truth
  flips**: backtest computes cash/positions locally (Portfolio = account), but live treats the
  **venue as truth**, so the engine needs a mirror to **reconcile** against (detect/repair drift
  from partial fills, fees, funding, liquidations, manual/other-bot trades). Reconciliation has
  no backtest analogue — which is exactly why the Account is a live concern, not an N+2 one.
  - **Shape:** `CashAccount` vs `MarginAccount` typing (nautilus pattern); one `Account` per
    `(venue, login)`; **Binance spot vs futures = two separate accounts** (cash vs margin);
    **IBKR subaccounts = N accounts under one connection**. Leverage/maintenance-margin/liq-price
    are **venue-controlled** live (set on the venue, cached in the `Account`) — distinct from the
    N+2 backtest model that *computes* them.
  - **Distinct driver from cross-margin.** Cross-margin (deferred beyond N+2 Phase B) needs an
    account *collateral pool* for account-wide liquidation math — a **backtest-accounting** driver.
    The live `Account` here is a **reconciliation** driver. Related, separately motivated; do not
    conflate.
  - **`user_id` is app-layer, strip from the engine.** Multi-tenancy ownership does NOT belong in
    the trading-domain `Portfolio` (current smell: `Portfolio.user_id`) and must NOT be relocated
    onto `Account`. The FastAPI-wrap layer owns the `user_id → portfolio_id/account_id` mapping
    externally; the engine stays owner-agnostic, keyed by its own domain IDs. Removing
    `Portfolio.user_id` is an independent cleanup (constructor-signature ripple) — kept OUT of v1.4
    to avoid muddying that milestone's golden-master re-baseline.

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

> **Deferred: multi-asset (forex / equities / ETF).** Crypto-first (locked 2026-06-08)
> removes the near-term need. When revisited, this is itself ≥1 milestone and splits into:
> (a) an instrument/contract-spec abstraction (partly folded into N+1 config typing);
> (b) multi-currency accounting (quote→`base_currency` conversion) — needed for forex;
> (c) trading calendars/sessions + corporate actions (splits/dividends) — needed for
> equities/ETF, and a data-engine concern that pairs with N+4's #6.
>
> **Cross-cutting tooling note:** do NOT add third-party graphify / Understand-Anything
> tools — use the native `gsd-map-codebase` + `gsd-graphify`, which write artifacts into
> `.planning/` that integrate with the workflow and that Claude can read directly.
