# Phase 2: OKX Connector - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement live OKX venue access against the Phase-1 seam. This phase delivers an
authenticated **OKX session** plus **domain adapters** that consume it — a market-data
provider (candle streaming with the native `confirm` closed-bar signal + REST backfill)
and an execution adapter (async order I/O: create/cancel + order/fill streams), with a
single `sandbox: bool` routing demo-vs-live, every ccxt float crossing the Decimal
boundary at the edge, and OKX secrets isolated. All live/async machinery is **inert on
the backtest hot path** (oracle byte-exact, no W1/W2 regression).

**IMPORTANT — this phase revises the milestone design.** Discussion reshaped the
architecture from the LOCKED `LiveConnector` "two-arm venue object" (LX-05 / D-10) into a
**responsibility-based decomposition**: the connector is a thin *session/transport
primitive*; the data arm, order arm, and account arm are **domain adapters living in their
home domains**, consuming the injected session. See D-01..D-04 below and the **Roadmap
Revisions** note. The success criteria of CONN-01..06 still hold; only their *home* and
*shape* change.

</domain>

<decisions>
## Implementation Decisions

### Architecture — responsibility-based decomposition (revises LX-05 / D-10)

- **D-01 — Split data from execution (not one venue object).** Market data and order
  execution are **independent axes of variation** (you may trade OKX but source candles
  from a 3rd-party vendor one day). They are separate clients with separate lifecycles —
  NOT a single `LiveConnector` with a data arm + order arm. **Validated against
  `nautilus-trader`** (a dependency in this repo): its OKX adapter ships
  `OKXDataClient(LiveMarketDataClient)` and `OKXExecutionClient(LiveExecutionClient)` as
  separate classes/modules/factories. OKX itself reinforces this — candles stream on a
  **third `business` WS endpoint** (`/ws/v5/business`), physically distinct from `/public`
  and `/private`. This **revises LX-05**.

- **D-02 — The connector is a shared authenticated *session/transport primitive*, not an
  operations owner.** `OkxConnector` (`itrader/connectors/okx.py`) owns exactly: auth
  (key/secret/passphrase), the single `sandbox: bool` routing (`set_sandbox_mode` **+** the
  native `x-simulated-trading` header — no split-brain), the one `ccxt.pro` client
  instance, the asyncio loop + daemon thread (async containment — CONN-04's real intent),
  the rate-limit/connection budget, and `connect`/`disconnect` lifecycle. It knows nothing
  about orders-vs-candles-vs-balances and **imports/constructs no domain events**. This
  **reshapes D-10**: `LiveConnector` (`connectors/base.py`) shrinks from a "thin two-arm
  marker" to a **session/transport contract**; the "arms" become the *existing domain
  seams*.

- **D-03 — Each arm is a domain adapter that owns its own venue I/O, in its home domain:**
  | Arm | Class | Home | Owns |
  |---|---|---|---|
  | Orders | `OkxExchange` (impl `AbstractExchange`, sibling of `SimulatedExchange`) | `execution_handler/exchanges/` | `create_order`/`cancel`/`watch_orders`/`watch_fills`, Decimal-edge + lot/tick rounding, raw→`FillEvent`, emits to `global_queue` |
  | Data | `OkxDataProvider` (impl a data-provider seam) | `price_handler/providers/` | native `business` candle subscription + `confirm`, REST `fetch_ohlcv` backfill, Decimal-edge, closed bars → `LiveBarFeed` |
  | Account | `VenueAccount` (Phase-1 `Account` leaf) | `portfolio_handler/account/` | balance/margin/position stream caching |

  The order I/O lives in the **exchange** because that is an exchange concern (matches
  nautilus: the execution client owns the order calls; the shared piece is transport).

- **D-04 — Injection, not cross-domain import.** The concrete `OkxConnector` is constructed
  **once at the composition root** (`LiveTradingSystem.__init__`) and **injected** into each
  adapter's constructor. Adapters type their param against the **`LiveConnector` session
  Protocol** (from the shared top-level `connectors/` package — dependency-safe, like
  importing `AbstractExchange`/`Account`), **never** the concretion. This preserves the
  codebase's DI-over-cross-domain-import rule, the D-07/D-10 swap-a-fake seam (a **fake
  session** drops in for tests), and means **only the connector authenticates** — the three
  arms share one authenticated session; credentials load once, arms never see keys
  (reinforces CONN-06). The three adapters schedule their coroutines onto the connector's
  single loop (async stays bottled) and call through its one client (rate-limit coordinates
  for free).

### Data arm — native `confirm` escape hatch (CONN-01)

- **D-05 — `OkxDataProvider` owns a native `business`-endpoint candle subscription** for the
  closed-bar `confirm` flag, rather than subclassing ccxt.pro's internals. **Verified:**
  ccxt routes candles to `/ws/v5/business` and its `parse_ohlcv` normalizes to the standard
  `[ts,o,h,l,c,v]` 6-tuple, **dropping OKX's `confirm`** (9th field). Since the data
  provider is its own independent client (D-01), a raw subscription to `candle{tf}` on
  `/business` yields the full payload with `confirm` directly — no fighting ccxt's parse
  layer. ccxt.pro still serves the **order** arm. (`BarEvent` construction itself is Phase 3
  `LiveBarFeed` — the provider hands it closed bars.)

### Order arm — build depth & event ownership (CONN-02, CONN-04)

- **D-06 — Order arm fully implemented in Phase 2** (`create_order`/cancel/`watch_orders`/
  `watch_fills` + Decimal-edge + lot/tick rounding via ccxt string-precision helpers),
  verified with **mocked-ccxt** unit tests. Real **sandbox** exercise of the order path
  (reconciliation, partial fills, restart) stays **Phase 5** — Phase 5 focuses on
  reconciliation, not connector-building.
- **D-07 — The *exchange* emits `FillEvent`, not the connector (revises CONN-04).** The
  connector owns no venue *operations* and emits nothing domain-shaped. `OkxExchange`
  translates raw fills → frozen `FillEvent` and puts them on `global_queue`. The `put()` may
  physically fire from the connector's asyncio thread via the exchange's fill-handler
  (thread-safe `queue.Queue`; **D-19 single-writer preserved** — portfolio state still
  mutates only on the engine thread via `on_fill`).

### Testing (COV / FL-13, CONN-06 secret hygiene)

- **D-08 — Offline-first, deterministic.** Primary = **mocked `ccxt.pro` objects** (async
  mocks over `watch_ohlcv`/`create_order`/`watch_orders`/`watch_fills`) + a small **recorded
  OKX-demo payload fixture** to pin `confirm`-flag realism on the native path. `pytest-asyncio`
  is configured (`asyncio_mode`, `asyncio_default_fixture_loop_scope`) so
  `filterwarnings=["error"]` stays green. **`pytest-asyncio` is not yet a dependency — the
  plan must add + configure it.**
- **D-09 — Sandbox demo account used, bounded.** The user's OKX demo keys (in `.env`) are
  used for **(1) fixture capture** — run once to record real business-channel candle
  payloads (with `confirm`) + a full order→ack→fill lifecycle, sanitize + commit as the
  fixtures the offline tests replay; and **(2) an opt-in `skipif(no creds)` live smoke test**
  (connect demo, subscribe a candle, tiny create/cancel) that **auto-skips** in CI / without
  `.env`, so the gating suite stays deterministic and credential-free. Formal sandbox
  *validation* stays Phase 5.

### Secrets (CONN-06 — revised)

- **D-10 — `OkxSettings(BaseSettings)` reads plain `OKX_API_KEY` / `OKX_API_SECRET` /
  `OKX_API_PASSPHRASE` with NO env prefix** (revises CONN-06's `ITRADER_OKX_*`). Passphrase
  is required for OKX auth and is now present in `.env` / `.env.example`. Secrets never in
  code, logs, commits, or fixtures; the backtest path stays credential-free. A real **secret
  manager is deferred to after this milestone** (user's call).

### Claude's Discretion
- Exact coroutine-scheduling mechanism between adapters and the connector loop
  (`run_coroutine_threadsafe` vs a spawn-task API on the session Protocol) — plan-time.
- Exact shape of the new **data-provider seam** in `price_handler` that `LiveBarFeed`
  consumes — plan-time (Phase 3 co-shapes it).
- Whether `OkxDataProvider`'s business-candle socket is fully separate vs multiplexed on the
  connector's loop — plan-time; ownership model (D-03) is fixed.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone design & requirements (authoritative; note the revisions above)
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LOCKED LX-01..LX-15.
  **This phase revises LX-05** (venue-object → data/exec split). Read §"Phase 2" + LX-05..LX-08.
- `.planning/ROADMAP.md` — v1.7 milestone, Phase 2 goal + success criteria (CONN-01..06),
  recurring milestone gate (oracle byte-exact / no W1/W2 regression). **CONN-01/02/04/06 are
  revised per D-01..D-10 — flag for roadmap update.**
- `.planning/REQUIREMENTS.md` — CONN-01..06 full text; RES-01 (rate-limit, home Phase 5, begins here).
- `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS,SUMMARY}.md` (2026-06-30) — milestone research.

### Phase 1 seam (build against this)
- `itrader/connectors/base.py` — `LiveConnector` Protocol (**reshape to session/transport
  contract per D-02**; currently a two-arm marker).
- `itrader/connectors/__init__.py` — connectors package barrel (D-13).
- `itrader/portfolio_handler/account/base.py` + `venue.py` — `Account` ABC + `VenueAccount`
  interface-only leaf (Phase-1 D-11).
- `.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-CONTEXT.md` —
  D-07/D-10/D-11/D-13 rationale (swap-a-fake seam, connector-package home).

### Existing patterns to mirror / reuse
- `itrader/execution_handler/exchanges/base.py` (`AbstractExchange`) + `simulated.py`
  (`SimulatedExchange`) — `OkxExchange` is the live sibling.
- `itrader/price_handler/providers/ccxt_provider.py`, `binance_stream.py` — existing live/REST
  ccxt + websocket plumbing to reuse for `OkxDataProvider`.
- `itrader/core/money.py` (`to_money`, `quantize`) — Decimal boundary (CONN-05).
- `itrader/config/settings.py` — `Settings(BaseSettings)` pattern for `OkxSettings`.

### External verification (plan-time research should re-confirm)
- ccxt.pro OKX: candles on `/ws/v5/business`; `parse_ohlcv` drops `confirm` (verified in
  installed `ccxt/pro/okx.py` + `ccxt/okx.py`).
- nautilus-trader OKX adapter: `adapters/okx/data.py` + `execution.py` (separate clients) —
  reference for the D-01 split.
- OKX rate limits: separate market-data vs order buckets; shared **3 conn/sec per IP** +
  480 sub/unsub per hour per connection; REST+WS order mgmt share one bucket (RES-01 is
  IP-connection-level, light). Sources: OKX API v5 docs, OKX WS URL-change notice.
- **Plan-time research flag (from ROADMAP):** OKX `confirm` exact behavior + field cadence;
  ccxt.pro native-vs-unified gap list; `set_sandbox_mode` WS-header verification; demo-key
  requirements. Block Phase 2 design until resolved.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SimulatedExchange` / `AbstractExchange` (`execution_handler/exchanges/`) — `OkxExchange`
  implements the same seam; `ExecutionHandler.on_order` already routes to it. `on_market_data`
  becomes a no-op for live (the venue matches, not us).
- `ccxt_provider.py` / `binance_stream.py` (`price_handler/providers/`) — websocket + ccxt
  plumbing patterns for `OkxDataProvider`.
- `Account` ABC + `VenueAccount` stub (Phase 1) — the account arm's stable contract already exists.
- `to_money` / `quantize` (`core/money.py`) — the Decimal edge (CONN-05).

### Established Patterns
- **DI over cross-domain imports** — inject the session Protocol; construct concretion only at
  the `LiveTradingSystem` composition root (D-04).
- **Queue-only cross-domain writes** — adapters emit domain events onto `global_queue`; the
  connector is a read/transport seam (like `BarFeed`/`PortfolioReadModel`), not a write path.
- **`runtime_checkable Protocol` swap-a-fake seam** — `LiveConnector` (D-07/D-10) enables the
  fake-session test strategy (D-08).
- **D-19 single-writer** — multiple queue producers are fine (`queue.Queue` is MPSC-safe);
  portfolio state still mutates only on the engine thread.

### Integration Points
- `LiveTradingSystem.__init__` — composition root: builds `OkxConnector` + injects into
  `OkxExchange`, `OkxDataProvider`, `VenueAccount`.
- `ExecutionHandler` → `OkxExchange` (order arm). `LiveBarFeed` (Phase 3) → `OkxDataProvider`
  (data arm). `Portfolio` → `VenueAccount` (account arm, wired Phase 5).
- `global_queue` — `OkxExchange` emits `FillEvent`; connector emits nothing.

</code_context>

<specifics>
## Specific Ideas

- User's demo OKX account (keys in `.env`) is available now — use it for fixture capture +
  opt-in smoke test (D-09), not for the gating suite.
- No env prefix on OKX keys — plain `OKX_API_*` (D-10). Secret manager is a post-milestone item.
- Model the design on **nautilus-trader's** OKX data/exec client split (it's an installed
  dependency — inspect `adapters/okx/`).

</specifics>

<deferred>
## Deferred Ideas

- **Formal sandbox validation** of the order path (reconciliation, partial-fill correctness,
  restart rehydration) — Phase 5 (RECON-*), as designed.
- **3rd-party market-data provider** (non-OKX candles) — enabled by the D-01 split (swap the
  `DataProvider` impl), but no such provider is built now.
- **Real secret manager** — after this milestone (user's call); Phase 2 uses `OkxSettings` +
  `.env`.
- **`LiveBarFeed` + `BarEvent` construction, ring buffer, monotonic delivery** — Phase 3.
- **`VenueAccount` reconciliation logic** — Phase 5 (the account arm is wired here, truth-caching
  logic lands there).

None of these are scope creep — they are the milestone's own downstream phases.

</deferred>

---

*Phase: 2-okx-connector*
*Context gathered: 2026-07-01*
