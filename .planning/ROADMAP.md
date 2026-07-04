# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- ✅ **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 + 5.1 (shipped 2026-06-22; numbering reset; promoted Backlog 999.4 / N+2)
- ✅ **v1.5 — Backtest Performance Optimization** — Phases 1-8 (shipped 2026-06-26; numbering reset; performance half of Backlog 999.2, split out from Persistence; Phases 7-8 added 2026-06-25 from post-phase re-profiles)
- ✅ **v1.6 — N+3b Persistence Foundation** — Phases 1-5 (shipped 2026-06-30; numbering reset; promoted the **persistence half** of Backlog 999.2)
- 🚧 **v1.7 — Live Trading Readiness (trimmed N+4 / Backlog 999.3)** — Phases 1-6 (in progress; numbering reset; promoted Backlog 999.3)

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
> Trailing Stops** (shipped 2026-06-22) promoted Backlog Phase 999.4 (N+2). **Backlog 999.2 was
> SPLIT:** its **performance half** shipped as **v1.5 — Backtest Performance Optimization**
> (2026-06-26); its **persistence half** shipped as **v1.6 — N+3b Persistence Foundation**
> (2026-06-30). **Backlog 999.3 (N+4 — Live) is promoted as the active milestone v1.7 — Live
> Trading Readiness** (started 2026-06-30; trimmed N+4 = the minimum surface to deploy live, paper-first).

## Active Milestone: 🚧 v1.7 — Live Trading Readiness (trimmed N+4 / Backlog 999.3)

**Milestone Goal:** Deploy and run the package **live on one crypto venue (OKX), paper-first**, with a
real correctness gate (**paper-parity vs the backtest oracle**) — **without disturbing the byte-exact
backtest oracle** (134 / `46189.87730727451`; v1.5 W1 baseline 15.7 s / 152.8 MB). Six phases, numbering
reset to Phase 1, refactor-phase-first (Phase 1 is an oracle-gated Account-abstraction extraction *before*
any live code depends on it). The trimmed N+4: the **minimum surface to deploy live**.

**Design source:** `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` (LOCKED,
LX-01..LX-15) + `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS,SUMMARY}.md` (2026-06-30).

### Milestone Gate (applies to EVERY phase)

The live machinery is **inert on the backtest hot path**. Each phase carries the recurring gate:

1. **Oracle byte-exact** — SMA_MACD on the golden BTCUSD CSV stays **134 trades /
   `final_equity 46189.87730727451`** (`check_exact=True`), determinism double-run identical.

2. **No W1/W2 perf regression** vs the v1.5 frozen baseline (15.7 s / 152.8 MB) — the backtest path
   imports no async/connector code.

**Held throughout, all phases:** Decimal money end-to-end (`to_money` at the connector edge — ccxt
returns floats); single UUIDv7; determinism (business `time`, never wall-clock); single seeded RNG +
injected clock; `mypy --strict` clean on new code; `filterwarnings=["error"]` green (`pytest-asyncio`
configured so the global filter is never relaxed); tabs/spaces indentation matched to the file.

### Phase Summary

- [x] **Phase 1: Account Abstraction + Portfolio/Handler Refactor** — Oracle-gated, behavior-preserving extraction of an `Account` truth surface; the universal gate before any live code. — completed 2026-06-30
- [x] **Phase 2: OKX Connector** — `OkxConnector` = shared authenticated **session/transport primitive**; data/order/account are **domain adapters** consuming it (`OkxDataProvider` + `OkxExchange` + `VenueAccount`), injected at the composition root; async bottled at the connector edge. (Revised 2026-07-01 — decomposition, revises LX-05; see `phases/02-okx-connector/02-CONTEXT.md`.) — completed 2026-07-04 (re-verified: CR-01/CR-02 gaps closed by Phases 3–5)
- [x] **Phase 3: LiveBarFeed** — Ring-buffer `BarFeed` impl; closed-bar emission off the confirm flag; warmup/backfill through the identical `update(bar)` path; monotonic-forward-only. — completed 2026-07-01
- [x] **Phase 4: Paper Path (milestone DoD)** — reuse `SimulatedExchange` as-is as the paper exchange (revised 2026-07-02); runnable worker + lifecycle; **paper-parity gate = paper ≡ a fresh backtest on the same data, exact frame-equality**. — completed 2026-07-02
- [x] **Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive** — `VenueAccount` reconciliation, partial-fill correctness, v1.6 store driven by the real feed, two-sided restart; sandbox-validated. — completed 2026-07-04
- [ ] **Phase 6: Dynamic Universe Membership** — Lean poll seam for mid-run add/remove; warmup-on-add reuses the Phase-3 backfill.

### Phase 1: Account Abstraction + Portfolio/Handler Refactor

**Goal**: Extract an `Account` abstraction owning balance/margin truth (`Simulated*` leaves;
`Venue*` interface-only), inject it into `Portfolio`, move margin/liquidation math out of
`PortfolioHandler` (the queue emission stays), strip `Portfolio.user_id`, evaluate/remove
`TradingInterface`, and shape the `LiveConnector` interface — all behind the existing
`PortfolioReadModel` seam with the backtest oracle held byte-exact. The universal gate: no live code
may merge against `Account` until the backtest is re-confirmed byte-exact.
**Depends on**: Nothing (first phase — gates all live work)
**Requirements**: ACCT-01, ACCT-02, ACCT-03, ACCT-04, ACCT-05, ACCT-06
**Success Criteria** (what must be TRUE):

  1. `Portfolio` delegates all balance/margin accounting to an injected `account` (`Portfolio.cash` →
     `account.balance`); `SimulatedCashAccount` (CashManager code-motion) and `SimulatedMarginAccount`
     own the truth, with margin/liquidation math (maintenance_margin, margin_ratio, liq price/penalty,
     liquidation *decision*) moved out of `PortfolioHandler` while the liquidation *emission*
     (`global_queue.put`) stays in the handler (queue-only rule preserved). (ACCT-01, ACCT-02)

  2. `Portfolio.user_id` is removed (app-layer concern, NOT relocated onto `Account`),
     `TradingInterface` is removed (or deliberately slimmed per LX-14) with the surviving engine
     command surface decided (scoping FL-13), and the `LiveConnector` interface + `VenueAccount` leaf
     are defined **interface-only** so Phases 2–5 implement against a stable contract. (ACCT-04, ACCT-05, ACCT-06)

  3. The backtest oracle re-confirms **byte-exact (134 / `46189.87730727451`)** after the extraction —
     determinism double-run identical, `mypy --strict` clean, no float-for-money. (ACCT-03)

  4. Recurring milestone gate: no W1/W2 perf regression vs the v1.5 baseline (15.7 s / 152.8 MB) — the
     refactor is pure code-motion behind the `PortfolioReadModel` seam (does not ripple into the order domain).
**Research flag**: SKIP — v1.2 MOD-01 OrderManager-decomposition playbook; `PortfolioReadModel` seam
already in place; code-motion only (plan-time research optional).
**Plans**: 7 plans

- [x] 01-01-PLAN.md — Interface scaffold: Account ABC + VenueAccount stub + LiveConnector Protocol + D-04 resolution (Wave 1)
- [x] 01-02-PLAN.md — SimulatedCashAccount + SimulatedMarginAccount byte-exact code-motion + CashOperation barrel (Wave 2)
- [x] 01-03-PLAN.md — Re-point Portfolio/PortfolioHandler to Account; strip user_id (production); re-point sql_storage CashOperation; delete CashManager (Wave 3)
- [x] 01-03b-PLAN.md — Migrate unit + integration test consumers (cash_manager→account, CashOperation home, user_id strip) (Wave 4)
- [x] 01-03c-PLAN.md — Migrate e2e test consumers + harness (cash_manager→account, user_id strip) (Wave 4)
- [x] 01-04-PLAN.md — Delete TradingInterface (LX-14) (Wave 1)
- [x] 01-05-PLAN.md — Oracle byte-exact + full-suite re-confirmation terminal gate (Wave 5)

### Phase 2: OKX Connector

> **Revised 2026-07-01** (Phase 2 discuss) — responsibility-based decomposition, revises LX-05 /
> D-10 / CONN-01/02/04. Details + rationale: `phases/02-okx-connector/02-CONTEXT.md` (D-01..D-10).

**Goal**: Deliver live OKX access as a **session + domain adapters**, not a two-arm venue object.
`OkxConnector` (`connectors/okx.py`) is a thin **authenticated session/transport primitive** (auth,
single `sandbox: bool`, one `ccxt.pro` client, own asyncio loop + daemon thread, rate-limit, lifecycle);
it owns no venue operations and emits no domain events. The **order arm** lives in `OkxExchange`
(`execution_handler/exchanges/`, impl `AbstractExchange`), the **data arm** in `OkxDataProvider`
(`price_handler/providers/`, native `business`-endpoint `confirm` read), the **account arm** in
`VenueAccount` — each **injected** with the connector session at the `LiveTradingSystem` composition
root (typed against the `LiveConnector` Protocol, never cross-domain-imported). Every ccxt float crosses
the Decimal boundary at the edge; async stays bottled at the connector.
**Depends on**: Phase 1 (the `LiveConnector` Protocol + `Account`/`VenueAccount` seams)
**Requirements**: CONN-01, CONN-02, CONN-03, CONN-04, CONN-05, CONN-06
**Success Criteria** (what must be TRUE):

  1. **Data arm** (`OkxDataProvider`): streams OKX candles via a native `business`-endpoint subscription
     carrying the **`confirm`** flag (ccxt's unified `watch_ohlcv` drops it), with REST `fetch_ohlcv`
     backfill; feeds closed bars to the Phase-3 `LiveBarFeed`. (CONN-01)

  2. **Order arm** (`OkxExchange`, impl `AbstractExchange`): async `create_order` + cancel +
     `watch_orders`/`watch_my_trades` implemented; **the exchange translates raw fills → `FillEvent` and
     emits them** (the connector emits nothing). A single `sandbox: bool` routes BOTH ccxt
     (`set_sandbox_mode`) and the native WS path (demo host `wss://wspap.okx.com` — the
     `x-simulated-trading` header is REST-only, corrected per 02-RESEARCH.md) to OKX demo and selects
     demo-vs-live keys — no split-brain. (CONN-02, CONN-03)

  3. **Session** (`OkxConnector`): runs its own asyncio loop on its own daemon thread, owns the one
     `ccxt.pro` client + rate-limit budget, and is **injected** into the three adapters (only the
     connector authenticates); the backtest path imports no async/connector code; every ccxt float
     crosses the Decimal boundary via `to_money` and outbound quantities round to OKX lot/tick via ccxt
     string-precision helpers (no `Decimal(float)`); D-19 single-writer preserved (`queue.Queue`
     MPSC-safe, portfolio state mutates only on the engine thread). (CONN-04, CONN-05)

  4. OKX secrets (apiKey + secret + **passphrase**) load via `OkxSettings(BaseSettings)` reading plain
     `OKX_API_*` (**no env prefix** — revised from `ITRADER_OKX_*`; a real secret manager is deferred
     post-milestone); never in code, logs, or fixtures; the backtest path stays credential-free. (CONN-06)

  5. Recurring milestone gate: oracle byte-exact + no W1/W2 regression (connector inert on the backtest
     hot path); `pytest-asyncio` configured (`asyncio_mode`, `asyncio_default_fixture_loop_scope`) so
     `filterwarnings=["error"]` stays green.
**Research flag**: RESOLVED 2026-07-01 (`02-RESEARCH.md`) — `confirm` = business-channel field index 8
(`"1"`=closed bar); ccxt 4.5.56 already ships the full surface (no version bump); WS demo is host-based
(`wspap.okx.com`), NOT the REST-only `x-simulated-trading` header; auth triple = apiKey+secret+passphrase,
demo selected by host. Design unblocked.
**Plans**: 5 plans (planned 2026-07-01)

- [x] 02-01-PLAN.md — Foundation: pytest-asyncio + async test infra, OkxSettings (CONN-06), LiveConnector Protocol reshape (Wave 1)
- [x] 02-02-PLAN.md — OkxConnector session/transport primitive: loop-on-daemon-thread, sandbox->wspap routing, call/spawn bridge (CONN-03/04) (Wave 2)
- [x] 02-03-PLAN.md — Order arm OkxExchange(AbstractExchange): create/cancel + watch_my_trades -> FillEvent, Decimal edge (CONN-02/05) (Wave 3)
- [x] 02-04-PLAN.md — Data arm OkxDataProvider: native /business confirm-gated candle socket + REST backfill (CONN-01/03/05) (Wave 3)
- [x] 02-05-PLAN.md — Composition-root wiring + VenueAccount seam + recurring milestone gate (CONN-04) (Wave 4)

**Cross-cutting**: RES-01 (rate-limit coordination across ccxt + native paths) begins here — home phase is Phase 5.

### Phase 3: LiveBarFeed

**Goal**: Build `LiveBarFeed` as a ring-buffer `BarFeed` impl that consumes the Phase-2 connector data
arm, emits a `BarEvent` **only on a completed bar** (`confirm == 1`) with venue bar-open `time`, replays
warmup/gap backfill **one-by-one through the identical `update(bar)` path**, enforces
monotonic-forward-only delivery, and replaces `TimeGenerator`'s role on the live path. Highest unique
live complexity (no backtest equivalent for reconnect gap-fill).
**Depends on**: Phase 2 (`OkxDataProvider` data arm + native `confirm` flag)
**Requirements**: FEED-01, FEED-02, FEED-03, FEED-04, FEED-05
**Success Criteria** (what must be TRUE):

  1. `LiveBarFeed` implements the existing `BarFeed` ABC as a bounded `deque(maxlen)` ring buffer per
     `(symbol, timeframe)` (capacity from the same wiring-time `cache_capacity()` derivation as
     backtest); strategies/screeners/execution consume it unchanged. (FEED-01)

  2. A `BarEvent` is emitted **only on a completed bar** (`confirm == 1`), bar `time` from the venue
     bar-open stamp (never wall-clock), the 7-rule look-ahead contract holds, and `LiveBarFeed` replaces
     `TimeGenerator`'s role preserving the TIME-before-BAR route ordering downstream. (FEED-02, FEED-05)

  3. Live-start and gap warmup replay REST-fetched bars **one-by-one through the identical `update(bar)`
     path** — there is no bulk `warmup_from()` fast-path (LX-09, parity audit). (FEED-03)

  4. Bar delivery is **monotonic-forward-only**: gap → REST-backfill-and-replay; duplicate → drop;
     stale/out-of-order → reject; reconnect → gap-fill the interim (stateful indicators never fed
     backward). (FEED-04)

  5. Recurring milestone gate: oracle byte-exact + no W1/W2 regression (LiveBarFeed off the backtest hot path).

**Research flag**: NEEDS PLAN-TIME RESEARCH — ring-buffer capacity across multiple timeframes/consumers;
reconnect debounce strategy; after-the-fact venue bar-correction policy (re-warm vs forward-only-and-log);
`TimeEvent`-on-bar-close vs moving metric recording to the BAR route.
**Plans**: 4 plans (planned 2026-07-01)

- [x] 03-01-PLAN.md — Provider D-12 ClosedBar co-shape (symbol+timeframe) + shared offline test fixtures (Wave 1)
- [x] 03-02-PLAN.md — LiveBarFeed core: ring + monotonic guard (D-06 taxonomy) + direct BarEvent emission (FEED-01/02/04) (Wave 2)
- [x] 03-03-PLAN.md — Warmup one-by-one replay (FEED-03) + reconnect boundary backfill (D-08) through the shared update() path (Wave 3)
- [x] 03-04-PLAN.md — Composition-root wiring: LiveBarFeed swap + D-13 raw-bar consumer + FEED-05 route order + recurring milestone gate (Wave 4)

**Cross-cutting**: RES-01 (websocket reconnect + gap recovery, FEED-04) builds here — home phase is Phase 5.
**Handoff**: the LX-15 runtime topology (RUN-01) must be DECIDED before Phase 4 wires the runtime — settle it in the Phase 3→4 planning handoff.

### Phase 4: Paper Path (milestone DoD)

> **Revised 2026-07-02** (Phase 4 discuss — `04-CONTEXT.md` D-01..D-12) — the paper exchange is the
> **reused `SimulatedExchange` as-is** (D-04: no new adapter, revises LX-06/PAPER-01); the `apply_costs`
> extraction is **dropped** (D-05: PAPER-02 satisfied-by-reuse); the parity gate re-anchors to **paper ≡
> a fresh backtest on the same data, exact frame-equality** (D-01: NOT pinned to the frozen `46189…`
> artifact, revises PAPER-04/LX-11); Phase 4 builds only the **runnable worker + lifecycle** — the
> Postgres `LISTEN/NOTIFY` channel + FastAPI move past Phase 5 to the FastAPI application-layer plan (D-08: revises RUN-01). The prior
> 2026-07-01 note (paper needs no connector/session, revises LX-06 framing) still holds.

**Goal**: Deliver the paper path by **reusing `SimulatedExchange` as-is** as the paper exchange (it
already implements `AbstractExchange`, is account-free, and is already half-wired in `LiveTradingSystem`
under the `'simulated'` key), driven by `LiveBarFeed`, plus a **runnable worker entrypoint** with
start/stop/status lifecycle — and prove the **paper-parity gate**: replaying the fixed golden dataset
through the live-paper path yields **the same trades/equity as a fresh backtest run on the same data,
exact frame-equality**. Reachable on Phases 1+3 (and, for the manual live smoke test only, the Phase-2
**data arm** `OkxDataProvider`). The LX-15 runtime topology is decided; the channel/FastAPI defer past Phase 5 to the app-layer plan (D-08).
**Depends on**: Phase 1 (`SimulatedAccount`, portfolio-side) + Phase 3 (`LiveBarFeed`) + Phase 2 **data arm only** (`OkxDataProvider`, manual smoke)
**Requirements**: PAPER-01, PAPER-02, PAPER-03, PAPER-04, RUN-01, COV-01
**Success Criteria** (what must be TRUE):

  1. The paper exchange is the **reused `SimulatedExchange`** (D-04, satisfies "impl `AbstractExchange`")
     with **bar-based fills only** and no OKX I/O; there is exactly ONE fill-pricing implementation
     (`_emit_fill`, UNTOUCHED — D-05), so "no dual fill-pricing drift" holds by construction. (PAPER-01, PAPER-02)

  2. `LiveTradingSystem` runs end-to-end on the paper path (live feed → strategy → order → paper fill →
     `SimulatedAccount`/`Portfolio`) with the determinism seams (seeded RNG + business-time stamping)
     threaded through; a **runnable worker entrypoint** with start/stop/status lifecycle exists (LX-15
     topology (b)-as-(c)-N=1 decided). (PAPER-03, RUN-01)

  3. **Paper-parity gate (DoD)**: replaying the fixed golden dataset through the live-paper path yields
     trades + equity **exactly equal to a fresh backtest run on the same data** (`check_exact=True`, no
     tolerance) — NOT pinned to the frozen `46189…` artifact so it survives a backtest-loop rework; the
     transitive lock (paper == backtest == `46189…`) is held by the separate, unchanged oracle test. (PAPER-04)

  4. The surviving live surface (`LiveTradingSystem` + the ACCT-05 engine command surface) has FL-13
     coverage: the parity gate (anchor E2E) + start/stop/status lifecycle tests + the synthetic replay
     provider as the fixture, `filterwarnings=["error"]` green; real-connector coverage is manual/opt-in
     here (network-gated, out of CI) and automated in Phase 5. (COV-01)

  5. Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression (paper machinery off the
     backtest hot path — the inertness gate forbids `replay_provider` on the backtest import path).
**Research flag**: RESOLVED 2026-07-02 (`04-CONTEXT.md` + `04-PATTERNS.md`) — parity harness = offline
synchronous replay of the golden CSV through `LiveBarFeed` vs a fresh in-test backtest (D-01/D-02/D-03);
LX-15 topology decided (D-07); channel/FastAPI deferred past Phase 5 to the app-layer plan (D-08). Two load-bearing traps mapped:
the `BTCUSD` symbol-form (not `BTC/USDT`) and the tz divergence (backtest `Europe/Paris` vs live-feed `UTC`
— parity test tz-normalizes to UTC before the exact diff).
**Plans**: 4 plans (planned 2026-07-02)

- [x] 04-01-PLAN.md — ReplayDataProvider over the golden CsvPriceStore + offline unit coverage (COV-01 fixture) (Wave 1)
- [x] 04-02-PLAN.md — Paper venue arm (reuse SimulatedExchange) + synchronous run_paper_replay() driver (PAPER-01/02/03) (Wave 2)
- [x] 04-03-PLAN.md — Runnable worker entrypoint (RUN-01) + start/stop/status lifecycle tests (COV-01) (Wave 3)
- [x] 04-04-PLAN.md — Paper-parity gate (PAPER-04, DoD) = paper ≡ fresh backtest exact + inertness/oracle gate (Wave 3)

**Cross-cutting**: RUN-01 (topology, LX-15) is decided here but architected for Phases 2–5; COV-01 (FL-13)
is primarily established here on the first end-to-end live surface and extends into Phase 5 for the real path.

### Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive

**Goal**: Bring up the real path against OKX sandbox — `VenueAccount` caching+reconciling venue
balance/margin/position streams under 1 account : 1 portfolio, idempotent partial-fill handling, a
halt-and-alert drift policy, the v1.6 operational store **driven by the real OKX feed** (completing the
deferred live composition-root wiring), and two-sided restart rehydration — all sandbox-validated, with
live resilience hardened. The heaviest phase by unique live complexity (the reconciliation cluster).
**Depends on**: Phase 2 **order arm** (`OkxExchange`) + connector session + Phase 1 `VenueAccount` interface + Phase 4 paper path proven + the v1.6 store
**Requirements**: RECON-01, RECON-02, RECON-03, RECON-04, RECON-05, RECON-06, RES-01
**Success Criteria** (what must be TRUE):

  1. `VenueAccount` caches the injected connector session's balance/margin/position streams and reconciles **per-symbol
     drift** under 1 account : 1 portfolio (it caches venue truth, it does not compute); the drift-repair
     policy is **halt-and-alert by default**, with auto-correct only within a defined tolerance band.
     (RECON-01, RECON-03)

  2. Partial-fill handling is correct and idempotent (fill-ID dedup, accumulation, terminalize only on
     full fill or venue-reported closed) with the venue as source of truth in live. (RECON-02)

  3. The v1.6 operational store (order / portfolio-state / signal) is **driven by the real OKX feed** —
     the live composition-root wiring is completed (resolves v1.6 D-01 / RETAIN-03) with create/terminalize
     writes sync-durable; restart rehydration is **two-sided** (reconstruct from the store AND reconcile
     against the live venue). (RECON-04, RECON-05)

  4. Order I/O + `VenueAccount` reconciliation + persistence live-drive + restart rehydration are
     **validated against OKX sandbox** (real-money a gated stretch, not the DoD); live resilience
     (websocket reconnect + gap recovery, rate-limit coordination across ccxt + native, partial-fill
     handling) is in place and `LiveTradingSystem`'s publish-and-continue error policy is hardened for
     live. (RECON-06, RES-01)

  5. Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression (live/venue machinery off
     the backtest hot path).
**Research flag**: RESOLVED 2026-07-02 (`05-RESEARCH.md` + `05-PATTERNS.md` + `05-VALIDATION.md`) —
drift policy = precision-epsilon auto-correct band else whole-engine halt (nautilus
`is_within_single_unit_tolerance`, D-01); ~80% is wiring already-built seams (`VenueAccount` constructor,
`OkxExchange` streams, `CachedSql*` rehydrate, `_publish_and_continue`, `get_status`) + porting ~4 small
nautilus pure-functions; venue order id persisted for bracket re-link; two-sided restart = store rehydrate

+ venue REST reconcile → reconciling events / halt. Design unblocked.

**Plans**: 9 plans (planned 2026-07-02)

- [x] 05-01-PLAN.md — Reconciliation primitives: drift epsilon (D-01) + SystemStatus.HALTED (D-07) + pluggable AlertSink egress (D-06) (Wave 1)
- [x] 05-02-PLAN.md — Offline test infra: shared FakeLiveConnector + recorded OKX recon fixtures + opt-in slow sandbox suite scaffold (D-09) (Wave 1)
- [x] 05-03-PLAN.md — VenueAccount cache body: push stream + REST snapshot + reserve/release overlay (D-14/D-15, RECON-01) (Wave 2)
- [x] 05-04-PLAN.md — Drift-compare (engine thread) + freeze-in-place halt + HALTED status/alert + VenueAccount→Portfolio wiring (D-01/D-02/D-04/D-15, RECON-03) (Wave 3)
- [x] 05-05-PLAN.md — Partial-fill idempotency: fill-ID dedup + fast-fill-race fix + partial→CANCELLED terminalization (D-12/D-13, RECON-02) (Wave 2)
- [x] 05-06-PLAN.md — Persistence live-drive: split write paths (CachedSql* sync / signal+metrics async) + BAR-keyed metrics (D-10/D-11/D-16, RECON-04) (Wave 4)
- [x] 05-07-PLAN.md — Two-sided restart: venue_order_id persistence + VenueReconciler reconciling events + bracket re-link (D-03/D-05, RECON-05) (Wave 5)
- [x] 05-08-PLAN.md — Live resilience: reconnect supervisor + failure classification + pause-on-disconnect (RES-01/D-19/D-20) (Wave 6)
- [x] 05-09-PLAN.md — Error-policy split (D-17) + shared-parity-config + doc-sync (D-18) + terminal milestone gate (oracle byte-exact + inertness + RECON-06 sandbox evidence) (Wave 7)
- [x] 05-10-PLAN.md — Gap-closure: CR-01 live-fill wiring (start() spawns OkxExchange.connect()) + honest resume snapshot (WR-04) + atomic halt (WR-01) (Wave 8)
- [x] 05-11-PLAN.md — Gap-closure: adopt_venue_correlation seam (WR-02, rehydrated-order fill reaches mirror) + validate-before-mutate partial fill (WR-03) (Wave 8)
- [x] 05-12-PLAN.md — Gap-closure: RECON-06 OKX-demo live e2e suite (order->fill->reconcile->restart loop, human-gated `3 passed` against real EEA demo venue) (Wave 8)

**Cross-cutting**: RES-01 home phase (resilience pieces also built in Phases 2 rate-limit / 3 reconnect+gap-recovery);
COV-01 real-path surface coverage completes here.

### Phase 05.1: Live-Path Remediation — CONF-A + Wave 1 (Settlement Possible) (INSERTED)

**Goal:** Make a real OKX demo fill actually settle into the portfolio (position + cash + transaction) and stop the engine from trading on state the reconciler declared untrustworthy. Fixes V17-01/14/04/03 per locked decisions ARCH-1/ARCH-2/ARCH-4-Layer-1 (CONTEXT D-01..D-05), preceded by the CONF-A A1..A8 RED-test spine (D-19) and gated by the CONF-B online sandbox run (D-20). The go/no-go gate — nothing downstream is observable until settlement works.
**Requirements**: Scope defined by CONTEXT.md decisions D-01..D-05, D-19, D-20 (ADR ingest of v17_arch_decisions.md).
**Depends on:** Phase 5
**Plans:** 9 plans

Plans:

- [x] 05.1-01-PLAN.md — CONF-A RED spine: AUD-7 spot fixture split + A1 (account conformance) + A4 (spot no-drift) RED tests (Wave 1)
- [x] 05.1-02-PLAN.md — CONF-A RED spine: A2 (venue_order_id) + A3 (halt latch) + A5 (redeliver dedup) RED tests (Wave 1)
- [x] 05.1-03-PLAN.md — CONF-A RED spine: A6 (supervisor catch-all) + A7 (submit timeout) + A8 (pause defer-replay) RED tests (Wave 1)
- [x] 05.1-04-PLAN.md — D-01: widen Account ABC (7-member surface) + Simulated rename + VenueAccount ledgered settlement -> A1 GREEN (Wave 2)
- [x] 05.1-05-PLAN.md — D-05: VALID_STATUS_TRANSITIONS latch + single-seam enforcement + start() halt-refusal + reset_halt -> A3 GREEN (Wave 2)
- [x] 05.1-06-PLAN.md — D-02: re-type Portfolio.account to ABC + isinstance-guard margin casts + mypy visibility + permanent conformance gate (Wave 3)
- [x] 05.1-07-PLAN.md — D-03: per-market-type venue-truth adapter (spot base-balance positions; parameterized quote) (Wave 3)
- [x] 05.1-08-PLAN.md — D-04 + D-03 wiring: thread real quote + post-reconcile baseline guard + spurious-halt drift band -> A4 GREEN (Wave 4)
- [ ] 05.1-09-PLAN.md — D-20: extend CONF-B sandbox e2e assertions + human-gated online run (Wave-1 GREEN exit gate + ARCH-3 finalization capture) (Wave 5)

### Phase 05.2: Live-Path Remediation — Wave 2 (Restart Real) (INSERTED)

**Goal:** Make restart real: persist the venue ack (ORDER-ACK event), wire the existing durable portfolio SQL ledger in live, rehydrate positions/cash + the settled-trade dedup ledger before reconcile, and add a durable halt record. Fixes V17-02/05/06/12/10 + ARCH-4 Layer 2 (CONTEXT D-06..D-10). **PROVISIONAL — pending Phase 05.1's CONF-B online run** (settles the four ARCH-3 finalization points); RED tests encode observable behavior, not storage shape.
**Requirements**: Scope defined by CONTEXT.md decisions D-06..D-10.
**Depends on:** Phase 05.1 (CONF-B online run finalizes the ARCH-3 storage posture before 05.2 detail freezes)
**Plans:** 0 plans (run /gsd:plan-phase 05.2 to break down, AFTER 05.1 CONF-B)

Plans:

- [ ] TBD (run /gsd:plan-phase 05.2 to break down)

### Phase 05.3: Live-Path Remediation — Wave 3 (Resilience Hardening) (INSERTED)

**Goal:** Resilience hardening: stream-death catch-all + supervised account/position streams, missed-fill catch-up on resume, submit-timeout in-flight semantics, defer protective orders during pause, drop overlay on ack, loop-native gap backfill, external-order admission + preflight, and the 05-13 carry-overs. Fixes V17-07/08/09/11/13/15/16 + 05-13 (CONTEXT D-11..D-18).
**Requirements**: Scope defined by CONTEXT.md decisions D-11..D-18.
**Depends on:** Phase 05.2 (D-15 drop-overlay needs the D-06 ORDER-ACK trigger; D-12 catch-up + D-16 mark-seen are only safe once D-08 dedup lands)
**Plans:** 0 plans (run /gsd:plan-phase 05.3 to break down, AFTER 05.2)

Plans:

- [ ] TBD (run /gsd:plan-phase 05.3 to break down)

### Phase 6: Dynamic Universe Membership

**Goal**: Add a lean universe-membership **poll seam** for mid-run add/remove of symbols (NOT the full
production screener), reusing the Phase-3 backfill: warmup-on-add replays the new symbol's history through
the same `update(bar)` path, and the open-position-handling-on-remove policy is defined.
**Depends on**: Phase 3 (the backfill-through-`update` seam)
**Requirements**: UNIV-01, UNIV-02
**Success Criteria** (what must be TRUE):

  1. A lean universe-membership poll seam supports mid-run add/remove of symbols (grows
     `universe/membership.py` per its D-20 target) — NOT the full production screener. (UNIV-01)

  2. Warmup-on-add replays the new symbol's history through the same `update(bar)` path (reuses the
     Phase-3 backfill machinery); the open-position-handling-on-remove policy is defined
     (force-close vs orphan-and-track). (UNIV-02)

  3. Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression.

**Research flag**: SKIP — reuses the Phase-3 backfill-through-`update` seam; standard patterns if Phase 3
is built generically (per-symbol, not start-only).
**Plans**: TBD

## Phases (shipped — archived detail)

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

**Execution Order (v1.7):** Phase 1 (gates all) → 2 → 3 → 4 (DoD) → 5 → 6.
Hard dependencies (design §7): Phase 1 gates everything (oracle-gated); Phase 2 data arm feeds Phase 3;
Phase 4 DoD needs 1 + 3 + connector **data arm only** (NOT the order arm); Phase 5 needs Phase 2's order
arm + Phase 1's `VenueAccount` + the v1.6 store; Phase 6 pairs with Phase 3's backfill. LX-15 topology
(RUN-01) decided in the Phase 3→4 handoff before Phase 4 wiring.

**Active milestone (v1.7 — Live Trading Readiness):**

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Account Abstraction + Portfolio/Handler Refactor | v1.7 | 7/7 | Complete   | 2026-06-30 |
| 2. OKX Connector | v1.7 | 5/5 | Complete   | 2026-07-01 |
| 3. LiveBarFeed | v1.7 | 4/4 | Complete   | 2026-07-01 |
| 4. Paper Path (DoD) | v1.7 | 4/4 | Complete   | 2026-07-02 |
| 5. Real/Sandbox Path + Reconciliation + Persistence Live-Drive | v1.7 | 13/13 | Complete   | 2026-07-04 |
| 6. Dynamic Universe Membership | v1.7 | 0/TBD | Not started | - |

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

**Next:** `/gsd:plan-phase 1` to decompose Phase 1 (Account Abstraction) into executable plans.

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
> v1.6 2026-06-30). **Backlog 999.3 (N+4 — Live Trading Readiness) is PROMOTED as the active milestone
> v1.7** (started 2026-06-30, trimmed N+4). The historical 999.3 seed below is retained as the source
> intent (like 999.2 → v1.5/v1.6 and 999.4 → v1.4). Do not re-plan from here — see the v1.7 active
> milestone section above + [`.planning/REQUIREMENTS.md`](./REQUIREMENTS.md).

### Phase 999.3: N+4 — Live Trading Readiness (PROMOTED-TO-v1.7 — historical seed)

> **PROMOTED (2026-06-30).** This backlog entry is now the active milestone **v1.7 — Live Trading
> Readiness (trimmed N+4)** — 6 phases, 31+ requirements (see the v1.7 active section above +
> [`.planning/REQUIREMENTS.md`](./REQUIREMENTS.md)). The trimmed scope = the minimum surface to deploy
> live, paper-first on OKX. The locked design (`docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md`,
> LX-01..LX-15) supersedes the broad seed below where they differ (e.g. Perp realism Phase B / full
> production screener / multi-venue are explicitly DEFERRED out of v1.7 to v2). The seed is retained as
> the historical record.

**Goal (original seed):** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3 perf v1.5 + N+3b persistence v1.6), and a streaming data engine.

Scope (intent only — see the v1.7 active milestone for the trimmed, locked scope):

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
