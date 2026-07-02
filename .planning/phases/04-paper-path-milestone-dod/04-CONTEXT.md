# Phase 4: Paper Path (milestone DoD) - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the **paper path** — the live-paper trading engine — and prove it produces the same
correct numbers as the trusted backtest. Concretely: **reuse `SimulatedExchange` as-is** as the
paper exchange (it already implements `AbstractExchange`), wired into `LiveTradingSystem` under the
`'simulated'` key and driven by `LiveBarFeed`; stand up a **runnable worker entrypoint** with
start/stop lifecycle; and prove the **paper-parity gate**: replaying the fixed golden dataset
through the live-paper path yields **the same trades/equity as a fresh backtest run on the same
data, exact equality**.

Reachable on Phases 1 + 3 (and, for the manual live smoke test only, the Phase-2 **data arm**
`OkxDataProvider`). No OKX order arm, no connector session, needed for the DoD gate. All live
machinery stays **inert on the backtest hot path** (oracle byte-exact, no W1/W2 regression).

**Requirements touched:** PAPER-01, PAPER-02, PAPER-03, PAPER-04, RUN-01, COV-01 — several
**revised** by this discussion (see the ⚠️ flags in Decisions; ROADMAP + REQUIREMENTS need updating).

</domain>

<decisions>
## Implementation Decisions

### Parity harness / the DoD gate (PAPER-03, PAPER-04)

- **D-01 — Parity anchor CHANGED: paper ≡ backtest on identical data, exact equality — NOT pinned
  to the frozen golden artifact.** The gate runs the live-paper path AND a fresh backtest run on
  the same fixed dataset in the same test, and asserts trades/equity are **exactly equal**
  (frame-equal, no tolerance). It is NOT asserted against the committed `tests/golden/` numbers
  directly. Rationale (user): pinning to the frozen `46189.87730727451` artifact breaks the moment
  the backtest loop is reworked (the deferred bar-direct-unify todo); "paper ≡ backtest, same data"
  is **invariant under changing the loop** — rework both, the test still holds, no re-freeze needed.
  **Transitive property preserved:** the oracle test independently still pins backtest to
  134 / `46189.87730727451` (the inert-backtest gate), so paper == backtest == `46189…` holds
  transitively today — but the parity test needs no edit when the oracle re-freezes.
  **⚠️ REVISES PAPER-04 / LX-11** (currently "byte-exact vs the oracle 134/`46189…`") → update
  ROADMAP + REQUIREMENTS to the new framing.

- **D-02 — Replay entry = a fake/replay provider that generates the same `BarEvent`s an
  `OkxDataProvider` would.** It pushes golden CSV rows as confirm-gated `ClosedBar` dicts through
  `set_bar_sink` → `LiveBarFeed.update()` → direct-BAR emission (the real Phase-3 live mechanism),
  NOT the backtest `TimeGenerator` pull path. This is what makes the gate meaningful: the exchange
  code is shared (D-04), so the gate is really proving that **`LiveBarFeed` + `LiveTradingSystem`
  wiring + runtime** reproduce the backtest on identical data — the actual risky new surface.

- **D-03 — Replay is driven SYNCHRONOUSLY in-thread** (a for-loop pushing bars), single process,
  no asyncio daemon thread. Deterministic, CI-runnable, offline, and still fully exercises the
  paper mechanism (`set_bar_sink → update → queue`). The connector's asyncio transport thread is a
  Phase-2/5 concern, not the paper path. (Driving through the real async loop is a Phase-5 live
  smoke concern, not this gate.)

### Paper exchange (PAPER-01, PAPER-02)

- **D-04 — REUSE `SimulatedExchange` AS-IS for the paper path; NO separate `PaperExchange`
  adapter.** Verified: `SimulatedExchange` already implements `AbstractExchange` (it IS the
  reference impl), has **zero backtest-only coupling** (no `TimeGenerator`/`BacktestBarFeed`
  import; only two "backtest" *comments*), clean DI (`__init__(global_queue, config?, rng?)`), and
  is **already half-wired** in `LiveTradingSystem` (`live_trading_system.py:198, 414-416` construct
  a `'simulated'` exchange). `ExecutionHandler` routes `on_order` by `event.exchange` key and fans
  `on_market_data` over `self.exchanges.items()` — feed-agnostic, so `LiveBarFeed`'s `BarEvent`s
  just work. A shared exchange makes parity (D-01) trivially hold on the exchange layer.
  **⚠️ REVISES LX-06 / PAPER-01** ("paper adapter implements `AbstractExchange`" is satisfied by
  reusing the reference impl; "reuse the pure `MatchingEngine`, not the whole `SimulatedExchange`
  class" is overturned) → update ROADMAP + REQUIREMENTS.

- **D-05 — `apply_costs` extraction DROPPED (PAPER-02 dissolves).** PAPER-02 existed to stop *two*
  fill-pricing implementations (`SimulatedExchange._emit_fill` + a paper adapter) from drifting.
  With one shared class (D-04) there is no second impl → nothing to extract, nothing to keep in
  sync. "No dual fill-pricing drift" is satisfied by construction. `SimulatedExchange._emit_fill`
  stays untouched (oracle-safe). **⚠️ REVISES PAPER-02** → mark satisfied-by-reuse / retire.

- **D-06 — The paper exchange is ACCOUNT-FREE (byte-identical to backtest).** `SimulatedExchange`
  holds no `Account` reference in backtest; fills flow to the `Portfolio` via
  `FillEvent → PortfolioHandler.on_fill`, and `SimulatedAccount` lives **portfolio-side**, wired at
  the composition root — not on the exchange. PAPER-01's "composing … + `SimulatedAccount`" describes
  the paper *path*, not the exchange class. Confirmed: no account on the exchange.

### Runtime topology (RUN-01, LX-15)

- **D-07 — RUN-01 target topology DECIDED (written): separate worker process** — ship option (b),
  architected as (c) with N=1 (1 account : 1 portfolio). Unchanged direction from the milestone.

- **D-08 — Phase 4 BUILDS a runnable worker entrypoint + start/stop lifecycle; DEFERS the channel +
  FastAPI.** Phase 4 delivers a standalone bootstrap (`scripts/run_live_paper.py`-style) that
  constructs `LiveTradingSystem` and runs the live-paper engine with clean start/stop/status
  lifecycle, composition root cleanly separable at a process boundary — runnable two ways: against
  the **replay provider** (offline gate) and against the real **`OkxDataProvider`** (manual live
  smoke test). It does NOT build the Postgres `LISTEN/NOTIFY` command/status channel or any FastAPI
  integration — those pair naturally with the Phase-5 store live-drive (RECON-03 / v1.6 D-01) and
  the later FastAPI wrapping effort. Mostly **additive** to Phase 5 (low rework risk).
  **⚠️ REVISES RUN-01** ("with Postgres `LISTEN/NOTIFY` as the default channel [in Phase 4]") →
  the channel moves to Phase 5; Phase 4 = decision + runnable worker + lifecycle only.
  **The parity DoD gate does NOT depend on the worker** — it runs in-test, synchronous, single
  process (D-03).

### Determinism seams (PAPER-03)

- **D-09 — Determinism reproduces the backtest by construction.** Bar `time` = venue/CSV bar-open
  stamp (Phase-3 `LiveBarFeed` already stamps bar-open, never wall-clock); the same seeded
  `random.Random` + injected `BacktestClock` are threaded through the live-paper wiring exactly as
  in backtest. Because the exchange + matching + cost code are shared (D-04) and the data is the
  same golden dataset (D-02), the replay is bit-reproducible → parity (D-01) holds. Exact
  seed/clock threading points in the live composition root are plan-time detail.

### Coverage (COV-01 / FL-13)

- **D-10 — FL-13 scope for Phase 4:** (1) the **parity gate** is the anchor coverage — full paper
  path E2E (live feed → strategy → order → fill → `SimulatedAccount`/`Portfolio`); (2)
  **lifecycle/command-surface tests** — `start` / `stop(timeout)` / `get_status()` (the ACCT-05
  thin command surface that survived Phase-1's `TradingInterface` deletion, D-08/D-09) — clean
  startup, graceful stop (thread joins, no dangling), status reporting; (3) **fixtures = the
  synthetic replay provider from the golden CSV** (that IS the "mock connector" for the paper
  path) — no recorded OKX socket fixtures.

- **D-11 — Real-connector coverage is manual/opt-in here, automated in Phase 5.** The real-OKX
  live smoke test (against `OkxDataProvider`) is network-gated, marked `slow`, and **NOT in the CI
  gate** so CI stays deterministic + offline. Automated real-connector coverage (OKX order arm,
  `VenueAccount` reconciliation) is Phase 5's. `filterwarnings=["error"]` stays green
  (pytest-asyncio already configured in Phase 2).

### Recurring milestone gate (held, unchanged)

- **D-12 — Backtest oracle stays byte-exact (134 / `46189.87730727451`, `check_exact=True`),
  determinism double-run identical, no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB).**
  All paper/worker/live machinery is inert on the backtest hot path. Note this is SEPARATE from the
  D-01 parity-anchor change: the *backtest* oracle test still hard-pins `46189…`; only the *paper*
  gate re-anchors to "== backtest, same data."

### Claude's Discretion (plan-time)
- Exact `Bar`/`ClosedBar` construction in the replay provider from golden CSV rows.
- Exact seed/clock threading points in the live composition root (D-09).
- Worker entrypoint file location/name and the precise start/stop/status shape (D-08).
- Whether the parity test reuses the `_oracle_harness` diff mechanic directly or a thin wrapper
  (both compare live-paper output vs a fresh backtest run — D-01).
- Whether the manual live smoke test is a `pytest -m slow` opt-in or a small script (D-11).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone design & requirements (note the revisions this phase makes)
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LOCKED LX-01..LX-15.
  Read §"Deploy target (LX-01)", the LX-06 revision note (paper adapter framing), §"5.
  Cross-cutting" (LX-15 runtime topology), §"6. Definition of done". **This phase REVISES
  LX-06 and LX-11** (see D-01, D-04, D-05).
- `.planning/ROADMAP.md` — v1.7 Phase 4 goal + success criteria (PAPER-01..04, RUN-01, COV-01) +
  the recurring milestone gate. **PAPER-01/02/04 and the RUN-01 channel framing are REVISED here —
  flag for roadmap update.**
- `.planning/REQUIREMENTS.md` — PAPER-01..04 (revised), RUN-01 (home Phase 4; channel → Phase 5),
  COV-01 (home Phase 4, FL-13). **Update PAPER-01/02/04 + RUN-01 per D-01/D-04/D-05/D-08.**

### The paper exchange (reuse target — D-04)
- `itrader/execution_handler/exchanges/simulated.py` — `SimulatedExchange`: `on_order`,
  `on_market_data`, `_emit_fill` (247-298, UNTOUCHED — D-05), `__init__(global_queue, config?,
  rng?)`. The class reused as-is for paper.
- `itrader/execution_handler/exchanges/base.py` — `AbstractExchange` Protocol (already satisfied).
- `itrader/execution_handler/matching_engine.py` — `MatchingEngine` (pure resting book; composed by
  `SimulatedExchange`, reused transitively).
- `itrader/execution_handler/execution_handler.py` — `on_order` (routes by `event.exchange`),
  `on_market_data` (fans over `self.exchanges.items()`) — the feed-agnostic routing D-04 relies on.

### The live runtime + feed (wire target — D-08, D-02)
- `itrader/trading_system/live_trading_system.py` — composition root; already constructs a
  `'simulated'` exchange (198, 414-416) + `LiveBarFeed` (143-144); command surface
  `start()` (528) / `stop()` (582) / `get_status()` (651). Phase 4 wires the paper path + worker
  entrypoint here.
- `itrader/price_handler/feed/live_bar_feed.py` — `LiveBarFeed.update(ClosedBar)` (Phase 3 D-01/02);
  the replay provider (D-02) pushes into `set_bar_sink` → `update` → direct BAR emission.
- `itrader/price_handler/providers/okx_provider.py` — `OkxDataProvider`: `set_bar_sink`, `ClosedBar`
  TypedDict (with `symbol`+`timeframe`, Phase-3 D-12), `fetch_ohlcv_backfill`. The replay provider
  mimics this seam; the real one drives the manual live smoke test (D-11).

### Parity harness reference (D-01, D-03)
- `tests/integration/test_backtest_oracle.py` + `tests/integration/_oracle_harness.py` — the
  frame-equal (no-tolerance) diff mechanic on `output/{trades,equity}.csv` + `summary.json`; the
  parity test reuses this to compare live-paper vs a fresh backtest run (D-01).
- `scripts/run_backtest.py::main` — the in-process backtest run the parity test diffs against.
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — the fixed golden dataset replayed through the paper path.

### Prior-phase decision context (build against these)
- `.planning/phases/03-livebarfeed/03-CONTEXT.md` — D-01 (`update(ClosedBar)`), D-02/D-03 (direct
  BAR emission, replaces `TimeGenerator`), D-04 (single-ticker payload), D-09..D-13 (capacity,
  warmup, `RawBarConsumer` sizing). The live feed contract Phase 4 drives.
- `.planning/phases/02-okx-connector/02-CONTEXT.md` — D-03 (arm/adapter split), D-04 (DI at
  composition root). The LX-06-revision framing (paper = `AbstractExchange`, no connector).
- `.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-CONTEXT.md` — D-08/D-09
  (`TradingInterface` deleted; the surviving thin engine command surface = the FL-13 target).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`SimulatedExchange`** — reused AS-IS as the paper exchange (D-04); already `AbstractExchange`,
  already half-wired in `LiveTradingSystem`. Zero new adapter class.
- **`MatchingEngine` + fee/slippage models** — reused transitively via `SimulatedExchange`; no
  `apply_costs` extraction (D-05).
- **`LiveBarFeed`** (Phase 3) — the live feed the paper path is driven by; `set_bar_sink`/`update`
  seam is the replay entry point (D-02).
- **`_oracle_harness` + `run_backtest.py::main`** — the parity test's comparison mechanic and the
  fresh-backtest baseline (D-01).
- **`LiveTradingSystem.start/stop/get_status`** — the lifecycle/command surface to cover (D-10) and
  extend into a worker entrypoint (D-08).

### Established Patterns
- **Queue-only cross-domain writes / `event.exchange` routing** — `LiveBarFeed`'s `BarEvent`s reach
  the shared `SimulatedExchange` through the existing `ExecutionHandler` fan-out; no direct calls.
- **DI at the composition root** — paper wiring + worker bootstrap live in `LiveTradingSystem.__init__`
  / a thin entrypoint, not scattered.
- **Determinism seam** — bar-open `time` (never wall-clock), one seeded RNG + injected clock,
  threaded through the live path exactly as backtest (D-09).
- **Backtest hot path stays inert** — no async/connector import on the backtest path (D-12).

### Integration Points
- Replay provider → `LiveBarFeed.update` via `set_bar_sink` (offline gate, D-02/D-03).
- Real `OkxDataProvider` → `LiveBarFeed.update` (manual live smoke test, D-11).
- `LiveBarFeed` → `global_queue` `BarEvent` → `ExecutionHandler` → `SimulatedExchange` (paper fills).
- `FillEvent` → `PortfolioHandler.on_fill` → `Portfolio` (+ `SimulatedAccount`, portfolio-side, D-06).
- Worker entrypoint → `LiveTradingSystem.start/stop/get_status` (D-08).

</code_context>

<specifics>
## Specific Ideas

- User's driving simplification: "can't I simply use the `SimulatedExchange` for the live paper as
  well? they have the same task in the end, to simulate what a real exchange would do." — verified
  correct; became D-04/D-05 and collapsed PAPER-01/02.
- User explicitly relaxed the byte-exact-vs-frozen-golden DoD: "byte parity is not important since
  I'll probably change the backtest loop as well" — refined to D-01 (drop pinning to the frozen
  artifact, keep exact paper≡backtest on same data), which survives a future backtest-loop rework.
- User wants to be able to **test the live mechanism** (real `OkxDataProvider`-shaped `BarEvent`s),
  which motivated the replay-provider entry (D-02) and the runnable worker + manual live smoke test
  (D-08/D-11).

</specifics>

<deferred>
## Deferred Ideas

- **Real `PaperExchange` subclass for venue realism** — partial fills, order rejection,
  OKX-specific fee schedule + lot/tick rounding. LX-13 deliberately deferred sub-bar realism to OKX
  sandbox, so NOT this milestone; subclass `SimulatedExchange` if/when wanted (post-v1.7).
- **Postgres `LISTEN/NOTIFY` command/status channel + FastAPI integration** — the worker's control
  plane; pairs with the Phase-5 store live-drive (RECON-03 / v1.6 D-01) and the later FastAPI
  wrapping effort. Phase 4 builds only the runnable worker + lifecycle (D-08).
- **Driving the parity replay through the real async connector loop** — a Phase-5 live smoke
  concern; the Phase-4 gate is synchronous/offline (D-03).
- **Unify the backtest loop to bar-direct** (`.planning/todos/unify-backtest-direct-bar-generation.md`)
  — the rework D-01 is designed to survive; post-v1.7, oracle-gated.

### Reviewed Todos (not folded)
- **`margin-equity-double-counts-notional-wr01.md`** — reviewed, NOT folded. A valuation defect;
  under the D-01 "paper ≡ backtest on identical data" anchor it is present in BOTH paths and cancels
  out, so it neither helps nor blocks the parity gate. Remains the known WR-01 margin-equity gap
  (deferred, was never externally cross-validated).
- **`single-pass-portfolio-valuation.md`** — reviewed, NOT folded. A valuation/perf concern, same
  reasoning (cancels across both paths); out of Phase-4 scope.

</deferred>

---

*Phase: 4-paper-path-milestone-dod*
*Context gathered: 2026-07-02*
