# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- ✅ **v1.5 — Backtest Performance Optimization** — Phases 1-8 (shipped 2026-06-26; numbering reset; performance half of Backlog 999.2, split out from Persistence; Phases 7-8 added 2026-06-25 from post-phase re-profiles)
- ✅ **v1.6 — N+3b Persistence Foundation** — Phases 1-5 (shipped 2026-06-30; numbering reset; promoted the **persistence half** of Backlog 999.2)
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
[`v1.4-MILESTONE-AUDIT.md`](./milestones/v1.4-MILESTONE-AUDIT.md);
v1.5 — [`milestones/v1.5-ROADMAP.md`](./milestones/v1.5-ROADMAP.md) ·
[`v1.5-REQUIREMENTS.md`](./milestones/v1.5-REQUIREMENTS.md) ·
[`v1.5-MILESTONE-AUDIT.md`](./milestones/v1.5-MILESTONE-AUDIT.md);
v1.6 — [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md) ·
[`v1.6-REQUIREMENTS.md`](./milestones/v1.6-REQUIREMENTS.md) ·
[`v1.6-MILESTONE-AUDIT.md`](./milestones/v1.6-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`; v1.4 under `milestones/v1.4-phases/`; v1.5 under `milestones/v1.5-phases/`; v1.6 under `milestones/v1.6-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **Backlog 999.2 is
> SPLIT:** its **performance half** shipped as **v1.5 — Backtest Performance Optimization**
> (2026-06-26); its **persistence half** is promoted as **v1.6 — N+3b Persistence Foundation**
> (active from 2026-06-27; Backlog 999.2 marked PROMOTED-TO-v1.6, design intent retained as the
> historical seed). The remaining `999.x` entry (999.3 = N+4 live) is a future milestone, left intact.

## Phases

<details>
<summary>✅ v1.6 — N+3b Persistence Foundation (Phases 1-5) — SHIPPED 2026-06-30</summary>

Phase numbering reset to Phase 1 (matching v1.1–v1.5). Promoted the **persistence half** of Backlog
999.2 (its performance half shipped as v1.5). A **DB-gated** milestone — NOT covered by the backtest
oracle alone — that built the durable-storage + caching foundation N+4 will inherit, **without
disturbing the backtest path**: a swappable SQL spine (SQLite research + Postgres operational,
Turso-ready, driver NOT added per Owner Decision) composed (not inherited) by all four storage concerns;
an all-SQL results store (#1); concrete Postgres backends for the three operational seams (#2); a
two-knob write-through + retention model with restart rehydration; and a classified cache (#3). Every
phase carried a two-part gate: (a) SMA_MACD oracle byte-exact (134 / `46189.87730727451`) with no W1/W2
regression vs the v1.5 baseline (15.7 s / 152.8 MB) — proven inert by an import-quarantine subprocess
test, W1 measured −2.8% — AND (b) the phase's own DB round-trip / rehydration / parity tests on the right
substrate (in-process SQLite for #1, testcontainers Postgres for #2). Held throughout: Decimal money on
the live path (Postgres-native `Numeric`), single UUIDv7, determinism, `mypy --strict` clean (210 files),
`filterwarnings=["error"]` green (suite 1463). All 20 requirements satisfied; audit `tech_debt` (no
blockers; live composition-root wiring deferred to N+4 per RETAIN-03/D-01). Full detail in
[`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md).

- [x] Phase 1: SQL Spine + Security Hardening (5/5 plans) — completed 2026-06-27
- [x] Phase 2: Results Store (#1) (4/4 plans) — completed 2026-06-29
- [x] Phase 3: Operational SQL Backends (#2) (5/5 plans) — completed 2026-06-29
- [x] Phase 4: Retention + Live Write-Through (#2 live path) (4/4 plans) — completed 2026-06-30
- [x] Phase 5: Cache Classification (#3) (3/3 plans) — completed 2026-06-30

</details>

<details>
<summary>✅ v1.5 — Backtest Performance Optimization (Phases 1-8) — SHIPPED 2026-06-26</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3/v1.4). The performance analog of v1.2
Consolidation: a **behavior-preserving** milestone that cut the W1 hot path via profiler-ranked,
oracle-gated optimizations — **changing no numbers**. The byte-exact SMA_MACD oracle held at 134
trades / `final_equity 46189.87730727451` across all 8 phases (Phase 5 carried a deliberate
re-baseline carve-out that proved unnecessary — the oracle stayed byte-exact). Every optimization
phase was gated on BOTH (a) the oracle staying green AND (b) a measured same-machine-A/B W1
wall-clock improvement, re-frozen after the phase. Held throughout: `mypy --strict` clean; Decimal
end-to-end (every fix is *less repeated work*, never a float swap); single UUIDv7; determinism
double-run byte-identical; full suite 1340/1340 green. Final W1 baseline re-frozen at **15.7 s /
152.8 MB** (absolute pre/post numbers are not directly comparable across the milestone because the
Phase-1 benchmark-probe quadratic bug was fixed mid-milestone; per-phase wins were attributed by
same-machine A/B, not the frozen-baseline diff). Phases 7-8 were added 2026-06-25 from post-phase
re-profiles (PERF-07/PERF-08; the originally-deferred items under those IDs were renumbered
PERF-09/PERF-10 at close). Source: the v1.5 spike
[`perf/results/PERF-BASELINE-RESULTS.md`](../perf/results/PERF-BASELINE-RESULTS.md). Full detail in
[`milestones/v1.5-ROADMAP.md`](./milestones/v1.5-ROADMAP.md).

- [x] Phase 1: Perf Tooling & Baseline (2/2 plans) — completed 2026-06-23
- [x] Phase 2: Order-Storage Indexing (2/2 plans) — completed 2026-06-23
- [x] Phase 3: Running PnL Accumulator (2/2 plans) — completed 2026-06-24
- [x] Phase 4: Hot-Path Discipline (3/3 plans) — completed 2026-06-24
- [x] Phase 5: Stateful Indicators + Shared Bar Cache (FRAGILE, LAST) (3/3 plans) — completed 2026-06-25
- [x] Phase 6: Bar-Feed Window Copies (OPTIONAL) (5/5 plans) — completed 2026-06-24
- [x] Phase 7: Per-Bar Metrics & Timestamp Polish (BYTE-EXACT) (3/3 plans) — completed 2026-06-25
- [x] Phase 8: Hot-Path Fusion, Bar Prebuild & msgspec (BYTE-EXACT) (6/6 plans) — completed 2026-06-26

</details>
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

**Shipped milestones** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |
| v1.4 — Margin, Leverage, Shorts & Trailing Stops | 1-6 + 5.1 | 35 | ✅ Shipped | 2026-06-22 |
| v1.5 — Backtest Performance Optimization | 1-8 | 26 | ✅ Shipped | 2026-06-26 |
| v1.6 — N+3b Persistence Foundation | 1-5 | 21 | ✅ Shipped | 2026-06-30 |

**No active milestone.**

**Next:** start the next milestone with `/gsd:new-milestone` (logical next: N+4 — Live Trading Readiness, Backlog 999.3).

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+4 (after v1.6)**
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
> SPLIT and fully consumed:** its performance half **shipped as v1.5 — Backtest Performance
> Optimization (2026-06-26)**; its persistence half **shipped as v1.6 — N+3b Persistence Foundation
> (2026-06-30).** The remaining `999.x` entry (999.3 = N+4 — Live Trading Readiness) is the next
> milestone seed.

### Phase 999.2: N+3b — Persistence (SHIPPED — both halves complete)

> **SHIPPED (2026-06-30).** This backlog entry is **fully consumed**: its **performance half**
> shipped as **v1.5** (2026-06-26) and its **persistence half** shipped as **v1.6 — N+3b Persistence
> Foundation** (5 phases, 20 requirements — see [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md)
> + [`milestones/v1.6-REQUIREMENTS.md`](./milestones/v1.6-REQUIREMENTS.md)). The design intent below is
> retained as the historical seed (like 999.4 → v1.4). Do not re-plan from here.

**Goal:** Durable PostgreSQL state — the infra prerequisite for live trading. The performance half
of this backlog entry was **split out and shipped as v1.5** (Backtest Performance Optimization,
2026-06-26); the **persistence half shipped as v1.6** (2026-06-30). Sequenced AFTER the
performance work so we are not persisting unvalidated behavior.
**Requirements:** Delivered as the v1.6 SPINE / RESULT / OPS / RETAIN / CACHE / MIG / SEC / GATE set
(20 reqs) — see [`milestones/v1.6-REQUIREMENTS.md`](./milestones/v1.6-REQUIREMENTS.md).
**Plans:** shipped in v1.6 (see [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md))

> **SPLIT (2026-06-23):** the **#5 profiler-guided performance pass** was promoted to **v1.5**
> (`perf/results/PERF-BASELINE-RESULTS.md` is the spike research; 10 reqs TOOL-01..04 + PERF-01..06).
> Persistence is a live-path, DB-gated concern not covered by the backtest oracle (a different North
> Star), so it follows v1.5 as its own milestone (**v1.6**, promoted 2026-06-27) rather than bundling
> with the perf gate.

Scope (intent only, persistence half — now realized in v1.6):

- **#4 permanent PostgreSQL storage** (orders, signals, fills, equity).
  `PostgreSQLOrderStorage` is currently a `NotImplementedError` placeholder. The v1.5
  order-storage indexing (PERF-01) designs its interface for extension so this backend satisfies
  the same contract. → **v1.6 OPS-01/02/03/04** (concrete SQL backends for all three operational seams).

- **#1 continued** — structural cleanup that the live-mode transition specifically demands.
  → **v1.6 SPINE-01/02/03** (the swappable SQL spine via composition).
- **FL-06** — SQL injection + hardcoded creds in `SqlHandler` (deferred out of v1.3; module
  is quarantined, belongs with persistence/SQL work). → **v1.6 SEC-01**.

Rationale: persistence is cross-cutting live-path infra; sequenced after v1.5 perf so the engine it
persists is both fast and validated.

### Phase 999.3: N+4 — Live Trading Readiness (capstone) (BACKLOG)

**Goal:** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence v1.6), and a streaming data engine.
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
- **Live-start indicator backfill through the same `update(bar)` path** (deferred out of v1.5
  Phase 5 — stateful indicators; surfaced 2026-06-24). When `LiveBarFeed` is built, historical
  warmup at live-start MUST replay bars through the **identical `update(bar)` path** the backtest
  uses (Nautilus `request_bars()` analog) — no separate bulk `warmup_from(series)` fast-path, which
  would be a second state-building path that diverges and re-opens the look-ahead/parity audit the
  single-code-path stateful design closes. See `.planning/todos/live-backfill-through-update.md` +
  `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` §10.D-3.
- **Persistence live-drive + venue reconciliation** (the v1.6 operational store is built + tested
  on testcontainers Postgres here, but only **driven by a real live feed in N+4**). Cache↔broker
  reconciliation on restart needs a live broker adapter (research SUMMARY: deferred to N+4); the
  async/buffered write-through path is keep-only-measured (build only if the live loop profiles a stall).

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
