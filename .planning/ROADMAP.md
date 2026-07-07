# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- ✅ **v1.5 — Backtest Performance Optimization** — Phases 1-8 (shipped 2026-06-26; numbering reset; performance half of Backlog 999.2, split out from Persistence; Phases 7-8 added 2026-06-25 from post-phase re-profiles)
- ✅ **v1.6 — N+3b Persistence Foundation** — Phases 1-5 (shipped 2026-06-30; numbering reset; promoted the **persistence half** of Backlog 999.2)
- ✅ **v1.7 — Live Trading Readiness (trimmed N+4 / Backlog 999.3)** — Phases 1-7 + 05.1/05.2/05.3 (shipped 2026-07-07; numbering reset; promoted Backlog 999.3; three remediation waves inserted after Phase 5; Phase 7 added 2026-07-06 from the Phase 6 code review)

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
[`v1.6-MILESTONE-AUDIT.md`](./milestones/v1.6-MILESTONE-AUDIT.md);
v1.7 — [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md) ·
[`v1.7-REQUIREMENTS.md`](./milestones/v1.7-REQUIREMENTS.md) ·
[`v1.7-MILESTONE-AUDIT.md`](./milestones/v1.7-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`; v1.4 under `milestones/v1.4-phases/`; v1.5 under `milestones/v1.5-phases/`; v1.6 under `milestones/v1.6-phases/`; v1.7 under `milestones/v1.7-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **Backlog 999.2 was
> SPLIT:** its **performance half** shipped as **v1.5 — Backtest Performance Optimization**
> (2026-06-26); its **persistence half** shipped as **v1.6 — N+3b Persistence Foundation**
> (2026-06-30). **Backlog 999.3 (N+4 — Live) shipped as v1.7 — Live Trading Readiness**
> (2026-07-07; trimmed N+4 = the minimum surface to deploy live, paper-first). The whole 999.x backlog
> through N+4 is now consumed; the next milestone is not yet defined (`/gsd:new-milestone`).

## Phases (shipped — archived detail)

<details>
<summary>✅ v1.7 — Live Trading Readiness (Phases 1-7 + 05.1/05.2/05.3) — SHIPPED 2026-07-07</summary>

Phase numbering reset to Phase 1 (matching v1.1–v1.6). Promoted Backlog 999.3 (N+4, trimmed). The
engine's first **live operating mode — paper-first on OKX** — landed **without disturbing the byte-exact
backtest oracle** (134 / `46189.87730727451`): an `Account` abstraction (oracle-gated extraction), an
`OkxConnector` (one session + data/trading/account adapters), a streaming `LiveBarFeed`, the paper path
(the DoD, gated on **paper-parity vs a fresh backtest** — frame-exact), a reconciled real/sandbox path
**human-observed GREEN on the OKX demo venue** (a real fill settling into position + cash) with a durable
restart-real ledger and three remediation waves (05.1 settlement / 05.2 restart-real / 05.3 resilience),
and a poll-driven dynamic universe hardened with async warmup + per-symbol readiness gating. The
live/connector machinery is provably inert on the backtest hot path (import-quarantine subprocess probe).
All 32 requirements satisfied; audit `passed` (0 blockers; one owner-gated oracle-dark defect deferred —
margin-equity WR-01). `mypy --strict` clean (234 files), non-live suite 1981 passed. Full detail in
[`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md).

- [x] Phase 1: Account Abstraction + Portfolio/Handler Refactor (7/7 plans) — completed 2026-06-30
- [x] Phase 2: OKX Connector (5/5 plans) — completed 2026-07-04
- [x] Phase 3: LiveBarFeed (4/4 plans) — completed 2026-07-01
- [x] Phase 4: Paper Path (milestone DoD) (4/4 plans) — completed 2026-07-02
- [x] Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive (13/13 plans) — completed 2026-07-04
- [x] Phase 05.1: Live-Path Remediation — CONF-A + Wave 1 (INSERTED) (9/9 plans) — completed 2026-07-05
- [x] Phase 05.2: Live-Path Remediation — Wave 2 / Restart Real (INSERTED) (6/6 plans) — completed 2026-07-06
- [x] Phase 05.3: Live-Path Remediation — Wave 3 / Resilience Hardening (INSERTED) (12/12 plans) — completed 2026-07-06
- [x] Phase 6: Dynamic Universe Membership (5/5 plans) — completed 2026-07-06
- [x] Phase 7: Live Dynamic-Universe Hardening (10/10 plans) — completed 2026-07-07

</details>

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
blockers; live composition-root wiring deferred to N+4 per RETAIN-03/D-01 — now promoted into v1.7 Phase 5).
Full detail in [`milestones/v1.6-ROADMAP.md`](./milestones/v1.6-ROADMAP.md).

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

All milestones through v1.7 are shipped and archived under `milestones/`. **No active milestone** —
the whole 999.x backlog through N+4 is consumed. Start the next cycle with `/gsd:new-milestone`.

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
| v1.7 — Live Trading Readiness | 1-7 + 05.1/05.2/05.3 | 75 | ✅ Shipped | 2026-07-07 |

**Next:** `/gsd:new-milestone` to define the next milestone (owner's stated direction:
`live_trading_system.py` refactor + FastAPI control-plane).

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> Promote one at a time with `/gsd:review-backlog` (or start via `/gsd:new-milestone`); defer detailed
> planning until promotion so each milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **Backlog 999.2 is SPLIT and fully consumed** (performance half → v1.5 2026-06-26; persistence half →
> v1.6 2026-06-30). **Backlog 999.3 (N+4 — Live Trading Readiness) SHIPPED as v1.7** (2026-07-07,
> trimmed N+4). The historical 999.3 seed below is retained as the source intent (like 999.2 → v1.5/v1.6
> and 999.4 → v1.4). Do not re-plan from here — the shipped detail is in the **Phases (shipped — archived
> detail)** section above + [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md).

### Phase 999.3: N+4 — Live Trading Readiness (SHIPPED-AS-v1.7 — historical seed)

> **SHIPPED as v1.7 (2026-07-07).** This backlog entry shipped as the **v1.7 — Live Trading Readiness
> (trimmed N+4)** milestone — 10 phases, 32 requirements (full detail in
> [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md)). The trimmed scope = the minimum surface to deploy
> live, paper-first on OKX. The locked design (`docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md`,
> LX-01..LX-15) supersedes the broad seed below where they differ (e.g. Perp realism Phase B / full
> production screener / multi-venue are explicitly DEFERRED out of v1.7 to v2). The seed is retained as
> the historical record.

**Goal (original seed):** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence v1.6), and a streaming data engine.

Scope (intent only — see [`milestones/v1.7-ROADMAP.md`](./milestones/v1.7-ROADMAP.md) for the trimmed, shipped scope):

- **#6 real-time data engine** ready for live. → v1.7 Phase 3 (`LiveBarFeed`).
- **#2 live execution engine.** → v1.7 Phases 2/4/5 (`OkxConnector` session + `OkxExchange` / paper `AbstractExchange` adapter / real path).
- **#7 production-ready universe / screener.** → DEFERRED to v2 (v1.7 ships only the lean poll seam, Phase 6).
- **Dynamic universe membership** — lean `UniverseSelectionModel` poll seam for mid-run adds/removes;
  warmup-on-add + open-position-handling-on-remove. → v1.7 Phase 6.

- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage. → v1.7 COV-01 (Phase 4, extends to 5).
- **Perp realism — "Phase B" (FUND-01..04, deferred out of v1.4)** — funding-rate accrual, mark-price
  liquidation trigger, funding-data pipeline, `freqtrade` 4th cross-validation oracle. → DEFERRED to v2
  (out of v1.7 trimmed scope; its own future milestone).

- **Account abstraction (born here, with the connector)** — first-class `Account` as the reconciled
  local mirror of venue balance/margin truth; `CashAccount` vs `MarginAccount`; 1 account : 1 portfolio;
  `user_id` stripped from the engine (app-layer concern). → v1.7 Phase 1 (`Account` abstraction,
  `Simulated*`/`Venue*` leaves, `user_id` strip) + Phase 5 (`VenueAccount` reconciliation).

- **Live-start indicator backfill through the same `update(bar)` path** (deferred out of v1.5 Phase 5).
  → v1.7 Phase 3 (FEED-03, LX-09 — no bulk `warmup_from` fast-path).

- **Persistence live-drive + venue reconciliation** (v1.6 operational store built + testcontainers-tested,
  driven by a real live feed only in N+4). → v1.7 Phase 5 (RECON-04/05).

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
