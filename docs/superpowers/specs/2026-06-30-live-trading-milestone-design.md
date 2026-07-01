# Live Trading Readiness — Milestone Design Sketch

- **Date:** 2026-06-30
- **Status:** DRAFT (intent-level sketch; seeds `/gsd:new-milestone`, not yet promoted)
- **Milestone:** the **trimmed** N+4 — Live Trading Readiness (Backlog 999.3). This sketch
  intentionally narrows the full N+4 seed to the **minimum surface to deploy live**.
- **Predecessor:** v1.6 — N+3b Persistence Foundation (the operational SQL store built + tested on
  testcontainers Postgres; only *driven by a real live feed* here).

> Decision tags below are written `LX-NN` (Live milestone) and are **proposed**, not locked — they
> firm up at per-phase `/gsd:plan-phase` time. They exist so the sketch is citable.

---

## 1. North Star & scope posture

**Core value:** the package can be **deployed and run live on one crypto venue (OKX)**, paper-first,
with a real correctness gate — *without* disturbing the byte-exact backtest oracle
(`134 trades / final_equity 46189.87730727451`; v1.5 W1 baseline 15.7 s / 152.8 MB).

**Deploy target (LX-01):** **paper-first.** Definition of done = a `SimulatedAccount` + local-paper
fill path trading a **live OKX streaming feed**, validated by **paper-parity vs the backtest oracle**
on the same data. The real-money/sandbox connector order arm is built and **sandbox-validated**, but
real-capital execution is a gated stretch, not the DoD.

**Milestone structure (LX-02):** **one milestone, refactor-phase-first.** Phase 1 is a
behavior-preserving, oracle-gated extraction of the Account abstraction (backtest stays byte-exact)
*before* any live code depends on it. This preserves the project's "refactor first, then build
features" discipline within a single milestone rather than splitting into two.

### In scope
- Live execution engine (the live trading path) — paper-first, sandbox-validated real path.
- Real-time data engine (`LiveBarFeed`, streaming).
- Account abstraction + `Portfolio`/`PortfolioHandler` refactor.
- OKX connector (`LiveConnector` interface + `OkxConnector`).
- Persistence **live-drive** + venue reconciliation (drives the v1.6 store with a real feed).
- Dynamic universe membership (lean poll seam — *not* the full production screener).
- FL-13 (`LiveTradingSystem`/`TradingInterface` test coverage), live resilience, secrets.

### Explicitly out of scope (deferred)
- **Perp realism "Phase B" (FUND-01..04)** — funding-rate accrual, mark-price liquidation trigger,
  funding-data pipeline, `freqtrade` 4th oracle. Additive on the v1.4 Phase A core; its own future
  milestone.
- **Production-ready universe / screener (#7 full)** — only the lean membership poll seam lands here.
- **Multi-venue / multi-asset** — crypto-first (locked 2026-06-08); the connector interface is
  *shaped* for a 2nd venue but only OKX is implemented.
- **Cross-margin pooling** — a backtest-accounting driver, distinct from the live reconciliation
  driver; already deferred beyond N+2 Phase B and consistent with the **1 account : 1 portfolio**
  constraint below.
- **Tick-level local-paper fills** — explicitly rejected (see LX-13); sub-bar realism lives in OKX
  sandbox, not local paper.

---

## 2. Milestone-level locked decisions (this session)

| Tag | Decision | Rationale |
|-----|----------|-----------|
| LX-01 | Paper-first DoD; real path sandbox-validated, real-money gated | Paper-parity-vs-backtest is the closest thing live has to the golden-master oracle. |
| LX-02 | One milestone, refactor-phase-first | Keep the oracle-gated refactor isolated as Phase 1 without milestone-boundary overhead. |
| LX-03 | Account abstraction owns balance/margin truth; `Simulated*` vs `Venue*` leaves | Backtest+paper compute locally (`SimulatedAccount`); live caches venue (`VenueAccount`). Account-layer mirror of the `SimulatedExchange`/`MatchingEngine` reuse. |
| LX-04 | **1 account : 1 portfolio** | Dissolves venue-aggregate→per-portfolio *attribution* at the source; reconciliation reduces to per-symbol drift detection. |
| LX-05 | Connector abstraction is **ours**, not ccxt's | `LiveConnector` interface shaped on OKX reality; `OkxConnector` uses ccxt.pro by default + native escape hatch for proven gaps, hidden behind the interface. Keeps OKX fidelity *and* a cheap 2nd-venue path. |
| LX-06 | Local paper reuses the pure `MatchingEngine` (+ fee/slippage), **not** the whole `SimulatedExchange` class | `MatchingEngine` is already I/O-free (`submit`/`on_bar -> decisions`). A thin `PaperConnector` composes it; two adapters over one matching core. |
| LX-07 | `LiveBarFeed` = ring-buffer `BarFeed` implementation | Same `BarFeed` ABC the engine already consumes; only the backing store changes (precompute → stream). Strategies/screeners/execution unchanged. |

> **Revised 2026-07-01 (Phase 2 discuss — see `.planning/phases/02-okx-connector/02-CONTEXT.md` D-01..D-04).**
> The original rationale for LX-05/LX-06 stands, but their *shape* changed after discussion:
> - **LX-05 revised:** the connector is **not** a two-arm venue object. Data source and execution
>   venue are **independent axes of variation** (validated against `nautilus-trader`, which splits
>   `OKXDataClient` / `OKXExecutionClient`; and OKX itself streams candles on a separate `/ws/v5/business`
>   endpoint). `OkxConnector` is a thin **shared authenticated session/transport primitive** (auth,
>   single `sandbox: bool`, one `ccxt.pro` client, asyncio loop+thread, rate-limit, lifecycle). The
>   data / order / account "arms" are **domain adapters in their home domains** — `OkxDataProvider`
>   (`price_handler/providers/`), `OkxExchange` (`execution_handler/exchanges/`, impl `AbstractExchange`),
>   `VenueAccount` (`portfolio_handler/account/`) — each **injected** with the connector session (typed
>   against the `LiveConnector` Protocol) at the `LiveTradingSystem` composition root, never
>   cross-domain-imported. Only the connector authenticates. `LiveConnector` (D-10) shrinks to a
>   session/transport contract; the "arms" are the existing domain seams.
> - **LX-06 revised:** the paper execution adapter implements **`AbstractExchange`** (the execution seam),
>   **not `LiveConnector`** — paper has no venue session, so it needs no connector. Its composition
>   (reused `MatchingEngine` + shared byte-exact `apply_costs`) is unchanged.

---

## 3. The parity spine (why most of this is "fill the seam," not "invent")

v1.5 Phase 5 (stateful indicators + `BarFeed` ABC) was built *for* this. Above the feed, the engine
speaks one contract (`current_bars`, `window`, `newest_bar`, `megaframe`, raw-bar registration).
Backtest backs it with `BacktestBarFeed` (precompute + monotonic cursor); **live backs it with
`LiveBarFeed` (ring buffer)**. The same symmetry holds at the account and execution layers:

| World | Time source | Data | Account | Execution |
|---|---|---|---|---|
| Backtest | `TimeGenerator` (pinned grid) | `BacktestBarFeed` | `SimulatedAccount` (computes) | `SimulatedExchange` (`MatchingEngine`) |
| Paper (live feed) | closed-bar arrival | `LiveBarFeed` ← data provider | `SimulatedAccount` (computes) | paper `AbstractExchange` adapter (reuses `MatchingEngine`) — no connector |
| Live real | closed-bar arrival | `LiveBarFeed` ← `OkxDataProvider` | `VenueAccount` (caches + reconciles) | `OkxExchange` (impl `AbstractExchange`) |

Data, account, and execution vary independently; on the live real row all three adapters share one
injected `OkxConnector` **session** (auth/transport), but each is its own domain adapter.

Paper sits in the middle column and shares the **left** column's computation — which is exactly what
preserves the paper-parity gate.

---

## 4. Phase breakdown (proposed)

### Phase 1 — Account abstraction + `Portfolio`/`PortfolioHandler` refactor (oracle-gated)
**Behavior-preserving. Backtest stays byte-exact (`134 / 46189.87730727451`).**

- Extract an `Account` abstraction owning the **balance/margin truth**:
  - From `Portfolio`: `cash` + `cash/` manager, `_process_transaction_spot`/`_process_transaction_margin`
    (cash/balance effects), `_accrue_short_carry`, `available_cash`.
  - From **`PortfolioHandler`** (the smell this refactor resolves): `maintenance_margin`, `margin_ratio`,
    `_isolated_liq_price`, `_liquidation_penalty`, `_run_liquidation_pass`, `_liquidate_position`,
    `reserve`/`release`. Margin/liq are *account* concepts mis-housed in the handler.
- Two orthogonal axes — **simulated vs venue** and **cash vs margin**:
  ```
  Account (ABC)
  ├── CashAccount    → SimulatedCashAccount   | VenueCashAccount
  └── MarginAccount  → SimulatedMarginAccount  | VenueMarginAccount
                        (N+2 computed liq model)  (caches venue values)
  ```
- **Phase 1 builds the `Simulated*` side only** (verbatim today's spot/margin math); `Venue*` leaves
  are **interface-only**. `Portfolio` delegates accounting to its `Account` (same pattern as its four
  managers): `Portfolio.cash` → `Portfolio.account.cash`.
- **Positions stay in `Portfolio`** for Phase 1 (smallest oracle-gated change; LX-04's 1:1 makes
  "who owns positions" moot — Account and Portfolio share scope).
- **`Portfolio.user_id` strip** — multi-tenancy is app-layer (FastAPI maps `user_id → portfolio_id`);
  must NOT relocate onto `Account`. Constructor-signature ripple (`add_portfolio(user_id, ...)`).
  Touches golden-master wiring → do deliberately, re-confirm byte-exact.
- **Evaluate `TradingInterface` necessity (LX-14) — likely remove.** It exists as the *pre-FastAPI*
  bridge between an external/web API and `LiveTradingSystem` (order creation, validation, status).
  With the FastAPI wrap owning the app layer (`user_id → portfolio/account` mapping), it is probably
  a redundant middle layer. Evaluate: (a) delete it and have FastAPI call a thin engine command
  surface directly, or (b) keep/slim it as the deliberate boundary FastAPI calls (so the web layer
  never reaches into `LiveTradingSystem` internals). Pairs with the `user_id` strip — both are
  "engine vs. app layer" cleanups — and it scopes FL-13 (test the surface that survives). See the
  `.planning` FastAPI application-layer plan.
- Shape the `LiveConnector` interface (interface-only) so Phases 2–5 implement against it.

**Gate:** SMA_MACD oracle byte-exact; `mypy --strict` clean; `filterwarnings=["error"]` green.

**Open items:** final cash-vs-margin leaf split mirroring `_process_transaction_*`; whether
`reserve`/`release` is an Account or Portfolio responsibility under 1:1; `TradingInterface`
keep-slim vs delete (LX-14).

---

### Phase 2 — OKX connector (session/transport primitive + domain adapters)
> Revised 2026-07-01 per the LX-05 revision above — decomposition, not a two-arm venue object.

- **`OkxConnector` = the OKX session** (`itrader/connectors/okx.py`): auth (key/secret/passphrase),
  **single `sandbox: bool`** routing *both* ccxt (`set_sandbox_mode`) **and** native calls
  (`x-simulated-trading` header) — no split-brain; one `ccxt.pro` client; its own asyncio loop in its
  own daemon thread; rate-limit/connection budget; `connect`/`disconnect`. It owns **no venue
  operations** and constructs **no domain events**. `LiveConnector` (`connectors/base.py`) is reshaped
  to this session/transport contract.
- **Order arm → `OkxExchange`** (`execution_handler/exchanges/`, impl `AbstractExchange`, sibling of
  `SimulatedExchange`): async `create_order`/cancel + `watch_orders`/`watch_fills`, Decimal-at-edge +
  lot/tick rounding, raw fill → frozen `FillEvent` → `global_queue`. **The exchange emits the fill, not
  the connector.** Fully implemented here; exercised against sandbox in Phase 5.
- **Data arm → `OkxDataProvider`** (`price_handler/providers/`): a native OKX `business`-endpoint
  candle subscription carrying the **`confirm`** flag (ccxt's unified `watch_ohlcv` drops it), plus REST
  `fetch_ohlcv` backfill; Decimal-at-edge. Feeds closed bars to Phase-3 `LiveBarFeed` (which builds the
  `BarEvent`).
- **Account arm → `VenueAccount`** (`portfolio_handler/account/`, Phase-1 `Account` leaf): caches the
  balance/margin/position stream (reconciliation logic lands in Phase 5).
- **Injection, not import:** the concrete `OkxConnector` is built once at the `LiveTradingSystem`
  composition root and injected into the three adapters, each typed against the `LiveConnector`
  Protocol. Only the connector authenticates; the async boundary stays bottled at the connector edge;
  the engine stays synchronous. Reuse plumbing from `ccxt_provider.py` / `binance_stream.py` where it fits.

**Open items:** exact native-vs-ccxt gap list for OKX (research at plan time — kline confirm-flag
reliability, stream channels, order-status fidelity); shared rate-limit accounting across ccxt +
native paths (OKX buckets public/business vs order separately — RES-01 is IP-connection-level, light).

---

### Phase 3 — `LiveBarFeed` (real-time data engine)
- Ring-buffer `BarFeed` impl: bounded deque per `(symbol, timeframe)` sized by the **same wiring-time
  `cache_capacity()` derivation** as backtest (`max(lookback)` over registered consumers). On each
  closed bar: append, advance cursor, update `newest_bar`, emit `BarEvent`. `window()` serves the
  trailing N from the ring.
- **Bar-close detection (LX-08):** emit a `BarEvent` only on a **completed** bar (7-rule contract:
  completed bars only, no forming bucket). Drive "closed" off OKX's kline **confirm flag** — surfaced by
  the Phase-2 `OkxDataProvider` (native `business`-channel read), which `LiveBarFeed` consumes — never
  wall-clock inference.
- **Bar source (LX-12): klines-now, trades-capable-later.** Trust OKX `watch_ohlcv`; shape the
  ingestion seam so a trade-aggregation source could slot in behind the same bar-close interface.
  Justified by **future optionality** (slippage research, future tick-backtester), **not** by paper
  fills (LX-13).
- **Backfill / warmup through the *identical* `update(bar)` path (LX-09):** at live-start, REST
  `fetch_ohlcv` the last K bars, then replay them **one-by-one through the same per-bar update path**
  live streaming uses. **No bulk `warmup_from(series)` fast-path** — a second state-building path
  diverges and re-opens the parity audit (`live-backfill-through-update.md`; stateful-indicator spec
  §10.D-3). Two warmups (§10.D-2): cache hydration + indicator readiness, both via the same entry.
- **Monotonic-forward-only delivery (LX-10)** — stateful indicators have **no rewind**:
  - Gap → REST-backfill and replay through the same `update(bar)` path.
  - Duplicate → drop. Out-of-order/stale → reject (never feed state backward).
  - Reconnect → gap-fill the interim.
  - Correction-after-the-fact → no in-place fix; **re-warm from the ring buffer** (or forward-only +
    log; decide at plan time).
- **`LiveBarFeed` + bar-close detection replaces `TimeGenerator`'s role** — the live time source is
  event-driven (closed-bar arrival), not iteration-driven. Downstream cycle unchanged.

**Open items:** honor venue corrections vs forward-only-and-log; native vs subscribed multi-timeframe
(subscribe OKX native intervals vs resample base live).

---

### Phase 4 — Paper path (the milestone DoD)
> Revised 2026-07-01 per the LX-06 revision above — paper needs **no connector** (no venue session).

- A **paper execution adapter satisfying `AbstractExchange`** (the execution seam — **not**
  `LiveConnector`), composing the **reused `MatchingEngine` + shared byte-exact `apply_costs`** (LX-06),
  driven by `LiveBarFeed`'s **closed** bars (bar-based fills only — LX-13). No OKX I/O, no session.
- `SimulatedAccount` (from Phase 1) provides account math → **same computation as backtest**.
- Wire `LiveTradingSystem` end-to-end: live feed → strategy (stateful indicators) → order →
  paper fill → `SimulatedAccount`/`Portfolio`. (Reachable on Phases 1+3 + the Phase-2 data provider;
  the order arm / connector session is not needed for paper.)
- **Correctness gate (LX-11): paper-parity vs the backtest oracle** on the same data — local paper is
  deterministic and bar-based precisely so this holds.

**Open items:** the exact parity harness (replay a fixed dataset through the live path offline vs a
recorded live session); how the live thread/clock interacts with determinism seams.

---

### Phase 5 — Live real path: reconciliation + persistence live-drive (sandbox-validated)
- `VenueAccount` (Phase 1 interface → impl): mirrors the **injected `OkxConnector` session's**
  balance/margin/position streams; reconciles. (Order I/O lives in `OkxExchange` from Phase 2; this
  phase adds the account-arm reconciliation logic.) Under **1:1 (LX-04)** this is **per-symbol drift
  detection** (partial fills, fees, funding, liquidations), not attribution. Assumes the portfolio has
  **exclusive** control of its venue (sub)account (one OKX subaccount per strategy-portfolio).
- **Persistence live-drive:** drive the v1.6 operational store (orders / portfolio state / signals)
  with the **real OKX feed** — the store was built + tested on testcontainers Postgres in v1.6 but
  only *driven by a live feed here*.
- **Cache↔broker reconciliation on restart:** restart rehydration reconstructs the working set from
  the store *and* reconciles against the live venue (the v1.6 rehydration tests were store-only;
  the broker side needs the live adapter). Async/buffered write-through stays **keep-only-measured**
  (build only if the live loop profiles a stall).
- Real-money execution path validated against **OKX sandbox**; real-capital run is a **gated stretch**.

**Open items:** reconciliation repair policy (auto-correct vs halt-and-alert on drift); transaction
boundary for live write-through (create/terminalize sync vs append-heavy — v1.6 research flag carried
forward).

---

### Phase 6 — Dynamic universe membership (lean poll seam)
- A `UniverseSelectionModel` poll seam for mid-run add/remove (grows `universe/membership.py` per
  its D-20 growth target). **Not** the full production screener.
- Engine integration edges: **warmup-on-add** (new symbol replays history through the same
  `update(bar)` path — reuses Phase 3's backfill machinery) and **open-position-handling-on-remove**.

**Open items:** remove-with-open-position policy (force-close vs orphan-and-track); poll cadence /
trigger.

---

## 5. Cross-cutting (woven through Phases 2–5, not a standalone phase)
- **Runtime & deployment topology (LX-15) — decide early; shapes how Phases 4–5 wire the runtime.**
  Today the live engine drains the queue on a **background daemon thread**. For deployment under
  FastAPI, evaluate running the live engine as a **separate process/worker** rather than in-process
  with the web app:
  - (a) *In-process* — engine on a background thread/task inside the FastAPI process. Simplest, but
    couples engine + web lifecycles, mixes FastAPI's async loop + the connector's asyncio thread +
    the engine's sync thread in one process, and one crash takes down both.
  - (b) *Separate worker process* — the live engine runs as its own service; FastAPI controls
    lifecycle (spin up/down) and communicates via the **Postgres system-of-record (v1.6)** for state
    + a command/status channel (Postgres `LISTEN/NOTIFY`, Redis, or a broker). Crash isolation,
    independent scaling, FastAPI stays thin. **This is precisely what v1.6's durable store + restart
    rehydration were built to enable** — the store is the shared truth a separate process reads while
    the worker writes.
  - (c) *Process-per-portfolio* — under **1 account : 1 portfolio (LX-04)** with one OKX subaccount
    per portfolio, each live portfolio could be its own engine process (strong isolation, natural
    fit), with a **shared price-feed service** so streams aren't duplicated across processes.
  - **Lean: (b) or (c).** The async connector bridge, v1.6 store-as-truth, and the 1:1 constraint all
    point away from in-process. Decide before Phase 4 wires the live runtime.
- **Resilience:** websocket reconnect, partial-fill handling, rate-limit handling, stream-gap recovery
  (Phase 3 owns feed gaps; connector owns transport reconnect). `LiveTradingSystem` already has a
  publish-and-continue error policy — harden it for live.
- **Secrets:** real OKX API-key/secret management (FL-06/SEC was infra; live adds real creds). Keys
  never in code; sandbox vs live key separation tied to the single `sandbox` flag (LX-05).
- **FL-13:** `LiveTradingSystem` / `TradingInterface` test coverage (deferred out of v1.3 — the live
  surface; scope depends on the LX-14 `TradingInterface` decision). Build coverage as each live phase
  lands, not as an afterthought.

---

## 6. Definition of done
1. **Paper-first:** SMA_MACD runs live-paper on a streaming OKX feed; **paper-parity vs the backtest
   oracle** holds on a fixed dataset (LX-11).
2. **Backtest untouched:** oracle byte-exact `134 / 46189.87730727451`, no W1/W2 regression vs v1.5
   (15.7 s / 152.8 MB) — the live machinery is inert on the backtest hot path.
3. **Real path sandbox-validated:** order I/O + `VenueAccount` reconciliation + persistence live-drive
   + restart rehydration proven against **OKX sandbox** (real-money is a gated stretch).
4. `mypy --strict` clean on new in-scope code; `filterwarnings=["error"]` green; FL-13 coverage on
   the live surface.

---

## 7. Dependencies & sequencing
- **Phase 1** gates everything (oracle-gated refactor first).
- **Phase 2 (connector)** feeds **Phase 3 (LiveBarFeed)** via its data arm.
- **Phase 4 (paper DoD)** needs Phases 1+3 (and the connector's *data* arm), **not** the order arm.
- **Phase 5 (real path)** needs Phase 2's order arm + Phase 1's `VenueAccount` + the v1.6 store.
- **Phase 6** pairs with Phase 3 (reuses backfill-through-update).
- Inherits v1.6 (operational store), v1.5 (stateful indicators / `BarFeed` ABC / perf), v1.4 (margin
  model), v1.1 (multi-scenario behavior).

---

## 8. Carried-forward research flags
- OKX kline confirm-flag reliability + native-vs-ccxt gap list (Phase 2/3 plan-time research).
- Live write-through transaction-boundary design (v1.6 research flag — Phase 5).
- `LiveTradingSystem` single-daemon-thread vs `TradingInterface` API-thread interaction under live
  (v1.6 PITFALLS 7/8 — Phases 4/5).
- Live runtime process model + FastAPI integration channel (LX-15 — decide before Phase 4 wiring).
- `TradingInterface` keep-slim vs delete, and the engine command surface FastAPI calls (LX-14 —
  Phase 1, intersects the FastAPI application-layer plan).
