# Architecture Research — v1.7 Live Trading Readiness

> ## ⚠ Superseded framing — read `phases/02-okx-connector/02-CONTEXT.md` first
>
> The Phase-2 discussion (2026-07-01) revised the live architecture; this snapshot
> predates it and still describes the **two-arm `LiveConnector`** model (the §2
> `LiveConnector(Protocol)` code block, the §4 `PaperConnector` section, and the
> parity-spine table below all reflect the OLD shape). **Superseded framings**
> (everything else — reuse assets, matching-core reuse, pitfalls — remains valid):
> - Connector is a **session/transport primitive**, not a two-arm venue object; the data/order/account arms are **domain adapters** (`OkxDataProvider` in `price_handler/providers/` / `OkxExchange` in `execution_handler/exchanges/` impl `AbstractExchange` / `VenueAccount`), **injected** with the session, never cross-domain-imported.
> - The **`OkxExchange` adapter emits `FillEvent`** — the connector owns no operations and emits no domain events.
> - Paper needs **no connector**: the paper execution adapter implements **`AbstractExchange`** (not `LiveConnector`), composing `MatchingEngine` + `apply_costs` + `SimulatedAccount`.
> - `OkxSettings` reads **plain `OKX_API_*` (no env prefix)** — not `ITRADER_OKX_*`.
>
> See design-doc LX-05/LX-06 revision notes and `02-CONTEXT.md` D-01..D-10.

**Domain:** Live-trading integration onto an event-driven backtest engine (iTrader, paper-first OKX)
**Researched:** 2026-06-30
**Confidence:** HIGH (existing code mapped directly; locked design `2026-06-30-live-trading-milestone-design.md` LX-01..LX-15; one MEDIUM external grounding — OKX confirm-flag in ccxt.pro)

> Scope: how the NEW live components integrate WITHIN the locked decisions. The
> existing event core, handlers, BarFeed ABC, MatchingEngine, and v1.6 store are
> NOT re-researched — they are the integration surface. Every recommendation is
> grounded in a real file/class. "New" vs "modified" is called out per component.

---

## Standard Architecture

### Target system overview (paper path = the DoD)

```
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI app layer (future; user_id -> portfolio_id mapping)          │
│   reads STATUS/RESULTS from Postgres; writes COMMANDS to a channel    │
└───────────────┬──────────────────────────────────────────────────────┘
                │ Postgres LISTEN/NOTIFY (command + status channel)
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LiveTradingSystem worker process  (1 worker : 1 portfolio : 1 acct)  │
│                                                                        │
│   ┌────────────────────────┐      enqueue (thread-safe put)           │
│   │ Connector thread        │ ───────────────────────────────┐        │
│   │  (own asyncio loop)      │   BarEvent / FillEvent /        │        │
│   │  OkxConnector|Paper      │   balance+position updates      ▼        │
│   │  watch_ohlcv / fills     │                         ┌──────────────┐│
│   └────────────────────────┘                          │ global_queue ││
│                                                        │ (queue.Queue)││
│   ┌─────────────────────────────────────────┐         └──────┬───────┘│
│   │ ENGINE THREAD (single writer, D-19)      │ ◄──────────────┘        │
│   │  EventHandler._routes dispatch           │  get()+_dispatch        │
│   │   BAR -> LiveBarFeed.window / strategies │                         │
│   │        -> PaperConnector.on_bar (fills)  │                         │
│   │   SIGNAL -> OrderHandler                  │                         │
│   │   FILL  -> PortfolioHandler / OrderHandler│                        │
│   │  Portfolio -> Account (balance/margin)   │                         │
│   └─────────────────────────────────────────┘                         │
│                       │ write-through (v1.6 operational store)         │
└───────────────────────┼───────────────────────────────────────────────┘
                        ▼
              ┌────────────────────────┐
              │ Postgres (system of    │  orders / portfolio_state /
              │ record, v1.6)          │  signals + command/status
              └────────────────────────┘
```

The whole live machinery is **inert on the backtest hot path**: backtest keeps
`TimeGenerator` -> `BacktestBarFeed.generate_bar_event` -> `SimulatedExchange`,
and `Portfolio` -> `SimulatedAccount` computes the same numbers the oracle froze.

### The parity spine (left column shared by paper)

| World | Time source | Account | Execution |
|---|---|---|---|
| Backtest | `TimeGenerator` (pinned grid) | `SimulatedAccount` (computes) | `SimulatedExchange` (`MatchingEngine`) |
| Paper (live feed) | closed-bar arrival | `SimulatedAccount` (computes) | `PaperConnector` (reuses `MatchingEngine`) |
| Live real | closed-bar arrival | `VenueAccount` (caches+reconciles) | `OkxConnector` |

Paper shares the backtest's **Account** computation — that is the mechanism that
makes the paper-parity gate (LX-11) hold.

---

## 1. Account abstraction extraction (Phase 1) — concrete layering

### Where balance/margin truth lives TODAY (the smell)

| Concern | Current home | File:symbol |
|---|---|---|
| Cash balance (`_balance`), reservations, locked margin | `CashManager` (owned by `Portfolio`) | `cash/cash_manager.py` |
| `Portfolio.cash` read | property -> `cash_manager.balance` | `portfolio.py:199` |
| Spot settlement cash effects | `Portfolio._process_transaction_spot` | `portfolio.py:308` |
| Margin lock-and-settle cash effects | `Portfolio._process_transaction_margin` | `portfolio.py:391` |
| Short borrow carry -> cash | `Portfolio._accrue_short_carry` | `portfolio.py:730` |
| `available_cash` / `reserve` / `release` | `PortfolioHandler` (delegating to CashManager) | `portfolio_handler.py:260/276/282` |
| `maintenance_margin` / `margin_ratio` | **`PortfolioHandler`** (mis-housed) | `portfolio_handler.py:339/374` |
| Isolated-liq math (`_isolated_liq_price`, `_is_breached`, `_liquidation_penalty`, `_liq_inputs`) | **`PortfolioHandler`** (mis-housed) | `portfolio_handler.py:399–460` |
| Liquidation engine (`_run_liquidation_pass`, `_collect_breaches_over_prices`, `_liquidate_position`) | **`PortfolioHandler`** (mixes truth + queue I/O) | `portfolio_handler.py:462–651` |

### Target layering

```
Account (ABC)                      owns BALANCE / MARGIN TRUTH + decisions
├── CashAccount    → SimulatedCashAccount    | VenueCashAccount   (interface-only P1)
└── MarginAccount  → SimulatedMarginAccount  | VenueMarginAccount (interface-only P1)
       (N+2 computed liq model)                (caches venue balance/margin)
```

- **`Account` (ABC)** — the truth surface that the `PortfolioReadModel` Protocol
  already names: `balance`/`available_cash`, `reserve`/`release`, `maintenance_margin`,
  `margin_ratio`. NEW abstraction, but the *Protocol contract already exists*
  (`core/portfolio_read_model.py`) — Phase 1 moves the implementation behind it,
  the seam stays. This is the single most important integration fact: **the order
  domain already reads through `PortfolioReadModel`, so re-homing the truth does
  not ripple into `OrderManager`/validator** (mypy-enforced structural conformance).
- **`SimulatedCashAccount`** ≈ today's `CashManager` verbatim (`_balance`,
  reservations, locked-margin, `apply_fill_cash_flow`, `assert_funds_invariant`,
  `assert_lock_fits_buying_power`, `reserve_cash`/`release_reservation`). The
  cash-vs-margin axis maps cleanly onto the existing
  `_process_transaction_spot` (CashAccount) vs `_process_transaction_margin`
  (MarginAccount) split — those two methods are the seam line.
- **`SimulatedMarginAccount`** = CashAccount + the lock-and-settle path
  (`lock_margin`/`release_margin`) + the **margin math** moved out of
  `PortfolioHandler` (`maintenance_margin`, `margin_ratio`, `_isolated_liq_price`,
  `_is_breached`, `_liquidation_penalty`, `_liq_inputs`).
- **`Venue*` leaves: interface-only in Phase 1.** They cache the connector's
  balance/margin/position streams (Phase 5 impl).

### `Portfolio.cash` -> `Portfolio.account.cash` without disturbing the oracle

- `Portfolio` gains an injected `self.account` exactly as it injects four managers
  in `_init_managers` (`portfolio.py:83`). `Portfolio.cash` (`portfolio.py:199`)
  changes from `self.cash_manager.balance` to `self.account.balance`. The cash
  SETTER is already deleted (`portfolio.py:208`), so there is no write seam to chase.
- **Byte-exact discipline = pure code-motion** (the v1.2 MOD-01 OrderManager-
  decomposition playbook). `_process_transaction_spot` is the documented
  "byte-exact site #2" (`portfolio.py:309`) — operand-for-operand identical
  Decimal ops, in order. The extraction must preserve operand order and the
  `apply_fill_cash_flow` full-precision (no-quantize) contract. Gate: SMA_MACD
  `134 / 46189.87730727451`, determinism double-run, `mypy --strict`.

### The queue-vs-truth seam for liquidation (the one non-trivial split)

`_liquidate_position` (`portfolio_handler.py:462`) does TWO things: (1) computes
liq price/penalty (truth) and (2) **mints an `Order`, writes `order_storage`, and
`global_queue.put(FillEvent)`** (I/O). Convention forbids a manager/Account from
holding the queue. **Recommended split:**

- `SimulatedMarginAccount` owns the **decision**: "is this position breached, and
  at what liq price/penalty?" (`_isolated_liq_price`, `_is_breached`,
  `_liquidation_penalty`, `maintenance_margin`).
- `PortfolioHandler` keeps the **emission**: `_run_liquidation_pass` stays as the
  queue-owning orchestrator that asks the Account for breaches and mints the
  forced-close `FillEvent` + `order_storage` write.

This keeps the queue-only / no-queue-in-manager convention intact and is
oracle-dark (default-off: zero breaches on the spot golden path), so it moves
safely.

### Positions stay in Portfolio — seam confirmed

`PositionManager` stays on `Portfolio` (`portfolio.py:96`). `maintenance_margin`
needs positions + `Universe` + current price; under **LX-04 (1 account : 1
portfolio)** Account and Portfolio share scope, so `maintenance_margin` is a
**computed read-model that composes Account (locked margin) + Portfolio
(positions) + Universe** — no ownership conflict. Confirmed: do NOT relocate
positions in Phase 1.

### `Portfolio.user_id` strip (paired Phase-1 cleanup)

`user_id` is set in `Portfolio.__init__` (`portfolio.py:52`), passed by
`PortfolioHandler.add_portfolio(user_id, ...)` (`portfolio_handler.py:152`), and
surfaced in `to_dict` (`portfolio.py:851`). Multi-tenancy is app-layer (FastAPI
maps `user_id -> portfolio_id`); it must NOT relocate onto `Account`. This is a
constructor-signature ripple that touches golden-master wiring -> re-confirm
byte-exact.

---

## 2. LiveConnector interface (ours, over ccxt.pro — LX-05)

### Shape (NEW abstraction; shaped on OKX reality)

```python
class LiveConnector(Protocol):   # mirrors AbstractExchange's role for live
    # --- data arm (feeds Phase 3 LiveBarFeed) ---
    async def watch_ohlcv(self, symbol, timeframe) -> AsyncIterator[ClosedBar]: ...
    async def fetch_ohlcv(self, symbol, timeframe, limit) -> list[Bar]:  # REST backfill (LX-09)
    # --- order arm (exercised in Phase 5 sandbox) ---
    async def submit(self, order) -> Ack: ...
    async def cancel(self, order_id) -> Ack: ...
    async def watch_fills(self) -> AsyncIterator[Fill]: ...
    # --- account arm (feeds Phase 5 VenueAccount) ---
    async def fetch_balances(self) -> Balances: ...
    async def watch_balances(self) -> AsyncIterator[Balances]: ...
    async def fetch_positions(self) -> Positions: ...
```

- `OkxConnector` implements it with **ccxt.pro by default + a native OKX escape
  hatch** behind the interface (LX-05). A single `sandbox: bool` routes BOTH
  ccxt (`set_sandbox_mode`) and native calls (`x-simulated-trading` header) to
  OKX demo — no split-brain.
- Reuse plumbing from existing `price_handler/providers/ccxt_provider.py` and
  `binance_stream.py` (those are read-only providers; the connector is the
  live-feed + order arm).

### Async loop -> synchronous `global_queue` (the determinism boundary)

This boundary already exists and is documented:

- `SimulatedExchange` docstring: *"queue.Queue is the thread boundary — other
  threads only put events"* (D-19, `simulated.py:44`). `Portfolio`/`PortfolioHandler`
  carry the same single-writer contract.
- `LiveTradingSystem._event_processing_loop` already drains on a daemon thread and
  dispatches via `event_handler._dispatch(event)` (`live_trading_system.py:365`).

**Integration rule:** the connector runs its **own asyncio loop in its own
thread**; on every venue message it translates to a frozen domain event and calls
`global_queue.put(...)` — a thread-safe handoff. It NEVER mutates engine state
directly. All state mutation stays on the single engine thread (the existing D-19
single-writer contract). Therefore:

- **Determinism of the backtest path is untouched** — the async bridge does not
  exist on the backtest path at all (inert).
- Live runs are inherently wall-clock-nondeterministic, but the engine-thread
  *processing* is still a serialized FIFO drain, so per-event handler logic stays
  reproducible given the same event sequence. The async boundary is "bottled at
  the connector edge" (sketch §4 Phase 2).
- **Event `time` must be the venue bar/fill business time, never wall clock**
  (the bar-timing contract + the determinism convention). The connector stamps
  domain events from venue timestamps.

---

## 3. LiveBarFeed as a BarFeed impl (Phase 3, LX-07)

### NEW concrete class; same ABC the engine already consumes

`LiveBarFeed(BarFeed)` implements the four abstract methods (`feed/base.py:75`):
`current_bars`, `window`, `megaframe`, `newest_bar`. The engine above the feed is
unchanged — strategies, screeners, execution all speak the same contract.

| Concern | BacktestBarFeed (existing) | LiveBarFeed (new) |
|---|---|---|
| Backing store | whole frame precomputed; monotonic int64 cursor | **bounded `deque(maxlen=cap)` per `(symbol, timeframe)`** |
| Capacity | holds full history | `cap = cache_capacity()` — the SAME `cache_registration.derive` over registered consumers (`feed/base.py:118`), i.e. `max(lookback)` (warmup=100 for SMA_MACD) |
| `window(asof, max_window)` | `iloc` slice of cached frame | trailing N from the ring |
| `newest_bar` | last `current_bars` walk writes `_newest_bars` | set on each `update(bar)` |
| Time source | `TimeGenerator` pinned grid | **closed-bar arrival** |

### Replacing TimeGenerator's role

- Backtest: `TimeGenerator` yields `TimeEvent`s; the TIME route calls
  `feed.generate_bar_event(time_event)` -> `BarEvent` (`bar_feed.py:448`).
- Live: there is no pinned grid. The connector's closed bar drives
  `LiveBarFeed.update(bar)` which appends to the ring and **emits the `BarEvent`
  directly**. Downstream BAR-route cycle (portfolio mark -> matching -> strategies)
  is unchanged.
- **Integration gap to flag:** `LiveTradingSystem` records portfolio metrics on
  `EventType.TIME` (`live_trading_system.py:374`). Live has no `TimeEvent` unless
  the feed/connector synthesizes one per closed bar. Decide at plan time: emit a
  paired `TimeEvent` on bar close (cleanest — keeps the TIME route semantics), or
  move metric recording to the BAR route. Recommend: synthesize a `TimeEvent` on
  closed-bar arrival so the existing `_routes` ordering (TIME before BAR) holds.

### Bar-close detection (LX-08) — the native escape hatch earns its keep

OKX's native WS kline channel carries a `confirm` field (`"0"` forming, `"1"`
closed). **ccxt.pro `watchOHLCV` does not reliably surface a closed/confirm flag**
across exchanges (it is exchange-specific and not part of the unified return)
([ccxt #21885](https://github.com/ccxt/ccxt/issues/21885)). This is exactly the
LX-05 native-escape-hatch case: drive "closed" off OKX's confirm flag via the
native path, never wall-clock inference. Emit a `BarEvent` only on a completed bar
(7-rule contract: completed bars only, no forming bucket).

### Warmup/backfill through the IDENTICAL update path (LX-09)

At live-start: REST `fetch_ohlcv` the last K bars, then **replay them one-by-one
through the same `update(bar)` path** live streaming uses. **No bulk
`warmup_from(series)` fast-path** — a second state-building path diverges and
re-opens the parity audit. Stateful indicators (v1.5) self-buffer through the same
per-bar push, so this is what keeps paper-parity intact.

### Monotonic-forward-only delivery (LX-10)

Both feeds are monotonic by construction (the BacktestBarFeed cursor is
forward-only with a safe-rebuild on a non-monotonic cutoff, `bar_feed.py:639`).
LiveBarFeed enforces: gap -> REST-backfill and replay through `update`; duplicate
-> drop; out-of-order/stale -> reject (stateful indicators have no rewind);
reconnect -> gap-fill the interim.

---

## 4. PaperConnector (Phase 4 — the DoD)

### NEW class composing the pure matching core (LX-06), NOT the whole exchange

`SimulatedExchange` (`simulated.py:36`) composes `MatchingEngine` +
`fee_model`/`slippage_model` and adds I/O (`_emit_fill`, `_emit_rejection`,
admission, connection telemetry). `PaperConnector` composes the **same pure
pieces** and satisfies `LiveConnector`:

```
PaperConnector(LiveConnector)
├── MatchingEngine            (reused verbatim — pure, I/O-free: submit / on_bar -> decisions)
├── fee_model + slippage_model (reused)
└── SimulatedAccount          (Phase 1 — provides balances/positions = backtest math)
```

- `submit`/`cancel` -> `matching_engine.submit`/`cancel`.
- On each `LiveBarFeed` **closed** bar -> `matching_engine.on_bar(bar)` -> apply
  fee/slippage -> emit `FillEvent` (bar-based fills only, LX-13).
- `fetch_balances`/`fetch_positions` -> read `SimulatedAccount` locally.

### Two-adapter-over-one-matching-core symmetry + a refactor to enable it

The fee/slippage application logic lives **only** in `SimulatedExchange._emit_fill`
(`simulated.py:247`) — maker/taker classification, the D-03 limit-no-slippage
gate, `to_money` normalization. To avoid two divergent fill-pricing paths (a
parity hazard), **extract a pure helper** (e.g. `apply_costs(decision, fee_model,
slippage_model) -> (executed_price, commission)`) that BOTH `SimulatedExchange`
and `PaperConnector` call. This is the "two adapters over one matching core"
made real: one matching core (`MatchingEngine`) AND one cost core. Modified:
`simulated.py` (extract helper, keep behavior byte-exact); New: the helper +
`PaperConnector`.

### Correctness gate (LX-11)

Paper-parity vs the backtest oracle on the same data: local paper is deterministic
+ bar-based precisely so this holds. The shared `SimulatedAccount` (column 1) and
shared `MatchingEngine`/cost-core are the mechanism.

---

## 5. Runtime / deployment topology (LX-15)

| Option | Integration points | Verdict |
|---|---|---|
| **(a) in-process** — engine thread inside FastAPI | none new; FastAPI calls `LiveTradingSystem` directly | **Reject.** Couples engine+web lifecycles; mixes FastAPI's async loop + connector asyncio thread + engine sync thread in one process; one crash kills both. |
| **(b) separate worker** — FastAPI controls lifecycle; Postgres system-of-record + command/status channel | v1.6 store (shared truth); Postgres `LISTEN/NOTIFY` (or commands table) for control; worker write-through | **Recommended baseline.** This is *precisely what v1.6's durable store + restart rehydration were built to enable* — store is the shared truth a separate process reads while the worker writes. Crash isolation; FastAPI stays thin. |
| **(c) process-per-portfolio** — 1 worker : 1 portfolio + shared price-feed service | per-OKX-subaccount isolation; shared feed avoids duplicate streams/rate-limits | **Target end-state under LX-04.** Natural fit for 1 account : 1 portfolio + one OKX subaccount per portfolio. |

### Recommendation (rationale-backed)

**Ship (b) now, architected as (c) with N=1.** Build the worker as a
**single-portfolio process** (effectively (c) with one portfolio), with the
price-feed living inside it for v1.7 but behind a seam that can be extracted to a
shared price-feed service later. Rationale, grounded in three locked facts:

1. **v1.6 store-as-truth** — the operational store + restart rehydration only pay
   off if a *separate* reader (FastAPI) and writer (worker) share Postgres. (b)
   activates the v1.6 investment; (a) wastes it.
2. **The async bridge** — keeping the connector's asyncio thread + the engine's
   sync thread in their own OS process (not co-resident with FastAPI's event loop)
   is the cleanest isolation of the three concurrency models.
3. **LX-04 1:1 constraint** — one portfolio : one OKX subaccount makes
   per-portfolio process isolation natural; designing the worker as
   per-portfolio from day one means scaling to (c) is "run N workers + extract the
   feed," not a re-architecture.

For the v1.7 DoD (one portfolio, paper) a single worker IS (c) with N=1 — so (b)
and the (c) end-state converge on the same build now. The FastAPI app itself is
out of v1.7 scope (deferred), but the command/status channel + write-through
contract must be designed in Phase 4–5 wiring.

---

## 6. TradingInterface (LX-14) — DELETE, replace with a thin engine command surface

### What depends on it today

Grep result: **no production consumer.** Only the barrel export
(`trading_system/__init__.py:6/12`), the class itself, and one *comment* in a test
(`test_admission_rules.py:267`) + a golden-doc note. `LiveTradingSystem` likewise
has no production wiring (live composition root deferred per RETAIN-03/D-01). The
FastAPI app does not exist yet.

### Why delete

`TradingInterface` (`trading_interface.py`) is the *pre-FastAPI* bridge. It is
also stale: it builds `OrderEvent`s with **float** price/quantity and naive
`datetime.now()` (`trading_interface.py:79/129`), and **bypasses the order domain's
sizing/validation** (`SizingResolver`/`EnhancedOrderValidator`) by constructing
sized orders directly. Under topology (b)/(c), the web layer talks to the worker
via the Postgres command channel — it never calls `LiveTradingSystem` methods
in-process — so an in-process bridge is redundant.

**Recommendation:** delete `TradingInterface`; introduce a thin, typed **engine
command surface** the worker consumes from the command channel (submit-signal /
cancel / status), routing through the *real* order domain (signal -> sizing ->
validation -> order), Decimal + UUIDv7 + tz-aware time. This pairs with the
`user_id` strip (both are "engine vs app layer" cleanups) and **scopes FL-13** —
test the surface that survives (the command surface + `LiveTradingSystem`
lifecycle), not the deleted bridge.

---

## 7. Suggested build order (honors §7 locked dependencies)

```
Phase 1  Account abstraction extraction        [GATES EVERYTHING — oracle-gated]
  └─ + user_id strip + TradingInterface delete + LiveConnector interface (interface-only)
         │
         ├──────────────► Phase 2  OkxConnector (data arm + order arm)
         │                   └─ data arm ─────► Phase 3  LiveBarFeed (ring buffer)
         │                                          │
         ▼                                          ▼
   (SimulatedAccount ready)                  Phase 4  PaperConnector  ◄── PaperConnector needs
         └──────────────────────────────────►  = milestone DoD          1 + 3 + connector DATA arm
                                                  (NOT the order arm)     (paper-parity gate, LX-11)
                                                       │
   Phase 2 order arm + Phase 1 VenueAccount + v1.6 store
                                                       ▼
                                            Phase 5  Real/sandbox path
                                              (VenueAccount reconcile + persistence live-drive)
                                                       
   Phase 6  Dynamic universe membership  (pairs with Phase 3 — reuses backfill-through-update)
```

**Hard dependencies (from sketch §7, verified against code):**

1. **Phase 1 first, oracle-gated.** Account extraction is behavior-preserving;
   the `PortfolioReadModel` seam means it does not ripple into the order domain.
   Everything else implements against the Phase-1 `LiveConnector`/`Account`
   interfaces.
2. **Phase 2 data arm before Phase 3.** `LiveBarFeed` consumes the connector's
   `watch_ohlcv`/`fetch_ohlcv`. The bar-close confirm flag (LX-08) depends on the
   Phase-2 native escape hatch.
3. **Phase 4 (DoD) needs 1 + 3 + connector DATA arm only — NOT the order arm.**
   `PaperConnector` does its own matching (reused `MatchingEngine`); it never
   submits to OKX. This is the critical sequencing insight: the paper DoD is
   reachable without any live order I/O.
4. **Phase 5 needs Phase 2 order arm + Phase 1 `VenueAccount` impl + the v1.6
   store.** Reconciliation = per-symbol drift detection under LX-04.
5. **Phase 6 pairs with Phase 3** (warmup-on-add reuses backfill-through-update).
6. **Topology (LX-15) decided before Phase 4 wires the runtime** (cross-cutting,
   not a phase).

---

## New vs Modified (explicit ledger for the roadmap)

| Component | Status | File / location |
|---|---|---|
| `Account` ABC + `CashAccount`/`MarginAccount` + `Simulated*`/`Venue*` leaves | **NEW** | new `portfolio_handler/account/` |
| `Portfolio` — inject `self.account`; `cash` -> `account.balance` | **MODIFIED** | `portfolio.py` |
| `CashManager` math/state -> `SimulatedCashAccount` | **MOVED** (code-motion, byte-exact) | `cash/cash_manager.py` -> account leaf |
| `PortfolioHandler` margin/liq math -> `SimulatedMarginAccount` | **MOVED** | `portfolio_handler.py:339–460` |
| `PortfolioHandler._run_liquidation_pass` queue emission | **KEPT** (asks Account for breaches) | `portfolio_handler.py:557` |
| `PortfolioReadModel` Protocol | **UNCHANGED** (seam preserved) | `core/portfolio_read_model.py` |
| `Portfolio.user_id` | **REMOVED** (app-layer) | `portfolio.py:52` |
| `TradingInterface` | **DELETED** + replaced by engine command surface | `trading_interface.py` |
| `LiveConnector` Protocol | **NEW** (interface-only in P1) | new |
| `OkxConnector` (ccxt.pro + native escape hatch) | **NEW** | new `execution_handler/connectors/` (or `price_handler/providers/`) |
| `LiveBarFeed(BarFeed)` ring buffer | **NEW** | new `price_handler/feed/live_bar_feed.py` |
| `apply_costs` fee/slippage helper (extract from `_emit_fill`) | **NEW** (refactor) | `execution_handler/` |
| `SimulatedExchange._emit_fill` -> call shared helper | **MODIFIED** (byte-exact) | `simulated.py:247` |
| `PaperConnector` (MatchingEngine + costs + SimulatedAccount) | **NEW** | new |
| `VenueAccount` impl (reconcile) | **NEW** (P5; interface in P1) | account leaf |
| `LiveTradingSystem` — real feed/connector wiring, TimeEvent-on-bar-close, command channel | **MODIFIED** | `live_trading_system.py` |
| Worker process + Postgres command/status channel | **NEW** | new |

---

## Anti-Patterns (domain-specific, to flag in the roadmap)

### A1: A second state-building path for warmup
Bulk `warmup_from(series)` alongside the per-bar `update`. Diverges from the live
path and re-opens the parity audit. **Instead:** replay backfill one-by-one
through the identical `update(bar)` (LX-09).

### A2: Mutating engine state from the connector thread
Any direct call from the asyncio thread into `Portfolio`/`Account`/handlers breaks
the D-19 single-writer contract and determinism. **Instead:** connector thread
ONLY `global_queue.put(...)`; all mutation on the engine thread.

### A3: Duplicating fill pricing in PaperConnector
Re-implementing maker/taker + slippage gating instead of reusing the matching core
+ a shared cost helper. Two pricing paths drift -> paper-parity fails silently.
**Instead:** one `MatchingEngine`, one `apply_costs` helper, two adapters.

### A4: Wall-clock bar-close inference
Inferring "bar closed" from local time instead of OKX's confirm flag. Drops/double-
counts bars on latency. **Instead:** drive closed off the native confirm flag
(LX-08), via the native escape hatch (ccxt.pro does not surface it reliably).

### A5: Re-homing `user_id` onto Account
Multi-tenancy belongs to the FastAPI app layer (`user_id -> portfolio_id`).
Putting it on Account couples the engine to tenancy. **Instead:** strip it; map
in the app layer.

### A6: Liquidation math left in PortfolioHandler
Leaving `_isolated_liq_price`/`maintenance_margin` in the handler perpetuates the
exact smell Phase 1 exists to fix and fights the future `VenueAccount` mirror.
**Instead:** truth/decision in `SimulatedMarginAccount`, queue emission stays in
the handler.

---

## Integration Points

### External services

| Service | Integration pattern | Notes / gotchas |
|---|---|---|
| OKX (data) | ccxt.pro `watch_ohlcv` + native WS for confirm flag | ccxt.pro does not surface a unified closed/confirm flag — native escape hatch required (LX-05/LX-08) |
| OKX (orders/account) | ccxt.pro submit/cancel/watch + native, single `sandbox` flag | `set_sandbox_mode` (ccxt) AND `x-simulated-trading` header (native) — route both or split-brain |
| Postgres (v1.6) | system-of-record + command/status channel (`LISTEN/NOTIFY`) | worker writes; FastAPI reads — the (b) topology enabler |

### Internal boundaries

| Boundary | Communication | Notes |
|---|---|---|
| connector thread ↔ engine thread | `global_queue.put` only | D-19 single-writer; determinism boundary bottled here |
| order domain ↔ portfolio truth | `PortfolioReadModel` Protocol | unchanged in P1 — Account moves behind it |
| `Portfolio` ↔ `Account` | direct (injected, same-process, 1:1) | mirrors the 4-manager delegation; not queue-mediated |
| feed ↔ engine | `BarFeed` ABC (`current_bars`/`window`/`megaframe`/`newest_bar`) | LiveBarFeed swaps the backing store only |
| paper execution ↔ matching | `MatchingEngine.submit`/`on_bar` (pure) | reused by both SimulatedExchange and PaperConnector |

---

## Confidence & gaps

- **HIGH** — Account layering, the `PortfolioReadModel` seam, the async->queue
  boundary, BarFeed ABC reuse, MatchingEngine reuse, TradingInterface deletion
  (grep-confirmed no consumers): all read directly from the code.
- **MEDIUM** — OKX confirm-flag exposure in ccxt.pro (web-sourced; verify the
  exact native channel + confirm semantics at Phase 2/3 plan time — carried
  research flag).
- **Gaps for plan-time research:** (1) live `TimeEvent`-on-bar-close vs moving
  metric recording to the BAR route; (2) ring-buffer capacity when multiple
  timeframes/consumers register (extend `cache_registration.derive`); (3)
  reconciliation repair policy (auto-correct vs halt-and-alert); (4) write-through
  transaction boundary (v1.6 carried flag); (5) exact native-vs-ccxt OKX gap list.

## Sources

- Existing code (HIGH): `portfolio.py`, `portfolio_handler.py`, `cash/cash_manager.py`,
  `core/portfolio_read_model.py`, `price_handler/feed/{base,bar_feed}.py`,
  `execution_handler/{matching_engine.py,exchanges/simulated.py}`,
  `trading_system/{live_trading_system,trading_interface}.py`.
- Locked design: `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` (LX-01..LX-15).
- [ccxt #21885 — closed/confirm flag for websocket candles](https://github.com/ccxt/ccxt/issues/21885)
- [ccxt OKX exchange docs](https://docs.ccxt.com/docs/exchanges/okx)
- [ccxt.pro manual](https://docs.ccxt.com/docs/pro-manual)

---
*Architecture research for: v1.7 Live Trading Readiness (paper-first OKX)*
*Researched: 2026-06-30*
