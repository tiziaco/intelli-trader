# Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive — Research

**Researched:** 2026-07-02
**Domain:** Live venue reconciliation (VenueAccount drift + partial-fill idempotency + two-sided restart + persistence live-drive + resilience) grafted onto an event-driven Decimal-exact deterministic engine, OKX-sandbox-validated
**Confidence:** HIGH on the code seams and the nautilus reference algorithm (read from installed source + our code directly); MEDIUM-HIGH on OKX/ccxt payload cadence (verified against nautilus's OKX adapter + ccxt behavior; firm up against sandbox at execution)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01..D-20 — research THESE, do not re-litigate)

**Drift-repair & halt (RECON-01/03):**
- **D-01** — Auto-correct within a **precision-based epsilon** (nautilus `is_within_single_unit_tolerance` style — one unit at the instrument's quantity/price precision, tied to `core/money.py` quantize scales). Unexplained drift beyond the band → **halt the WHOLE engine** (stop all new order submission; streaming/reconciling/persisting continue). REFINES RECON-03.
- **D-02** — On halt: **freeze venue state IN PLACE** (nautilus-style). Stop new submissions, alert (D-06), leave existing position + resting/working orders exactly as-is. Do NOT auto-flatten or auto-cancel.

**Restart & external-action (RECON-05):**
- **D-03** — Restart conflict = **venue-wins-within-band, halt-and-alert on the truly unexplained**. Authority split: **venue is truth for balances/positions/fills; the store is truth for INTENT** (orders we meant to place, strategy linkage, bracket structure). Reconstruct working set from store → reconcile against live venue → auto-adopt venue deltas that map to known intent or fall within tolerance (generate reconciling events, nautilus-style). Unexplained (venue position with NO stored intent) → halt-and-alert. "Adopt" is broader at restart than steady-state (D-01).
- **D-04** — Live external/manual actions: **adopt-and-continue (self-heal)**. External cancel (terminalize mirror) AND external fill / hand-closed position (set position/cash from venue) are adopted; engine keeps running. Only genuinely nonsensical drift trips the D-01 halt. An external fill is NOT unexplained drift — it is adopted.
- **D-05** — Brackets (parent/child OCO) on restart: **re-adopt from venue, per-bracket halt fallback**. Read resting orders from venue, re-link parent/child using stored `parent_order_id`/`child_order_ids`, resume OCO. If a leg cannot be **confidently** re-linked → escalate THAT bracket to halt-and-alert.

**Operator alerting (RES-01):**
- **D-06** — Alert egress = **CRITICAL `ErrorEvent` + marked structured log, behind a thin pluggable alert-sink seam**; external push (Telegram/webhook/email) DEFERRED. Reuse `ErrorEvent` → `EventHandler._log_error_event`; escalate halts to a distinct CRITICAL severity through a pluggable sink so an external channel drops in later without touching engine code.
- **D-07** — Distinct machine-readable **HALTED** status on `get_status()` with a reason (drift / reconciliation-unresolved / connector-fatal / paused-on-disconnect), separate from running/stopped.

**Scope & DoD (RECON-04/06):**
- **D-08** — **DEFER** the RUN-01 control plane (Postgres `LISTEN/NOTIFY` channel AND FastAPI wrapper) to the later FastAPI application-layer plan. Worker runs standalone; sandbox validation drives it directly. HALTED status lives on `get_status()` + persisted store.
- **D-09** — DoD evidence = **offline reconciliation gate (mocked/recorded OKX fixtures — deterministic, credential-free)** PLUS an **opt-in, network-gated, marked-`slow` live-sandbox suite** (`skipif-no-creds`, Phase-2 D-09 pattern) running the real order→fill→reconcile→restart loop against OKX demo, run locally. Real-money stays gated.

**Store durability (RECON-04):**
- **D-10** — **Split write paths.** Sync-durable working set = **order lifecycle (create/terminalize) + position/cash mutations (on fill)**. Everything else (per-bar equity curve, metrics, valuation) is derived/recomputable and rides the **async/best-effort** writer. Equity IS recorded per bar in live but off the critical path (Pitfall 9).
- **D-11** — **Signal store live-driven on the async/best-effort path** (today it's the in-memory backtest factory, `live_trading_system.py:171`). Signals are advisory audit records, NOT part of the restart working set.

**Partial-fill terminal (RECON-02):**
- **D-12** — Partial-then-cancel keeps the fills → **CANCELLED** (accumulated partials stand; remainder cancelled; terminalize as CANCELLED on `VALID_ORDER_TRANSITIONS`). NOT an error/halt.
- **D-13** — **No engine-imposed timeout** on long-open partials. Order stays open until fully filled, venue-reported closed, or explicitly cancelled by the strategy. Aging is a strategy concern. Resume-mid-partial on restart follows D-03 (venue fill history authoritative; store cumulative-filled is the cross-check).

**VenueAccount ingestion (RECON-01):**
- **D-14** — Ingestion = **push stream + REST pull for snapshot/gap**. `VenueAccount` subscribes to venue balance/margin/position private stream (thread-safe cache write on the connector's asyncio thread); REST pull for startup snapshot, restart reconcile (D-03), gap recovery on reconnect (D-19). Mirrors the bar feed + `OkxExchange` fill stream.
- **D-15** — **Drift COMPARE + halt DECISION runs on the ENGINE thread, on fill + on bar.** Async thread only writes the cache. Per-symbol drift comparison + halt decision execute on the engine thread — on `FillEvent` (immediate) and once per closed bar (periodic backstop). Preserves D-19 single-writer; avoids the phantom-drift race (Pitfall 8).

**Phase-4 carry-over:**
- **D-16** — WR-01: **BAR-keyed live metrics** — key metric recording on `EventType.BAR` (using `event.time`), the WR-01 fix, on the D-10 async/best-effort path (`live_trading_system.py:606-608` — was TIME-keyed; `LiveBarFeed` emits only BAR).
- **D-17** — WR-04: **split error policy** — the deterministic replay/parity driver runs **fail-fast** (matches the backtest it's diffed against); the **real live path keeps publish-and-continue**, hardened per RES-01.
- **D-18** — WR-02 structural half: **shared-parity-config cleanup** — construct the paper replay store window/symbol AND the backtest window from **one shared config literal**. Plus the **ROADMAP/REQUIREMENTS doc-sync** (stale RUN-01 channel-in-Phase-4; stale PAPER-01/02/04 byte-exact framing).

**Resilience (RES-01):**
- **D-19** — **Pause new order submission while any venue stream is disconnected**; resume after reconnect + REST reconcile. Surfaced via paused/HALTED status (D-07). A short debounce (sub-second blip → no pause) is a tuning detail.
- **D-20** — **Classify connector failures**; transient (network/rate-limit) → bounded-backoff retry, stay running; fatal (auth) or retries exhausted → HALTED + CRITICAL alert (D-06/D-07). Never spin forever silently.

### Claude's Discretion (this research sprint sets these)
- Exact drift thresholds / precision-epsilon per instrument (D-01); reconnect debounce window (D-19); reconnect retry ceiling + backoff (D-20).
- OKX partial-fill field cadence / fill-ID semantics (D-12/D-13); `watch_my_trades` vs `watch_orders` correlation.
- Write-through transaction boundary for the sync-durable working set (D-10) — **keep-only-measured** (async/buffered write-through built only if the live loop profiles a stall).
- Rate-limit bucket accounting across ccxt + native paths (RES-01, IP-connection-level / light).
- Exact bracket parent/child re-link mechanics on restart (D-05); store↔venue reconciling-event construction (D-03).
- `VenueAccount` cache data structures + connector→cache push mechanism (D-14) under `runtime_checkable` LiveConnector Protocol.

### Deferred Ideas (OUT OF SCOPE)
- Postgres `LISTEN/NOTIFY` command/status channel + FastAPI wrapper (D-08).
- External alert push (Telegram/webhook/email) — drop into the D-06 sink post-milestone.
- Real-money execution (gated stretch beyond DoD).
- Faster on-timer drift backstop (post-v1; v1 = on-fill + on-bar per D-15).
- Strategy-level partial-fill aging/timeout (D-13).
- Async/buffered write-through for the sync-durable working set (keep-only-measured, D-10).
- Perp funding realism (v2 FUND-01..04). Spot-only in v1.7; a perp funding line item → halt rather than silently absorb (Pitfall 12).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RECON-01 | `VenueAccount` caches connector balance/margin/position streams; reconciles per-symbol drift under 1 acct:1 portfolio; caches truth, does not compute | §Priority 1 (epsilon), §Priority 4 (cache + push mechanism, engine-thread compare) |
| RECON-02 | Partial-fill handling correct + idempotent (fill-ID dedup, accumulation, terminalize only on full fill / venue-closed); venue = truth | §Priority 3 (OKX fill cadence, dedup, terminalization onto `VALID_ORDER_TRANSITIONS`) |
| RECON-03 | Drift-repair policy = halt-and-alert by default, auto-correct only within a defined tolerance band | §Priority 1 (band), §Priority 6 (halt egress), D-01/D-02 |
| RECON-04 | v1.6 operational store (order/portfolio-state/signal) driven by real OKX feed; create/terminalize writes sync-durable | §Priority 5 (split write paths, `CachedSql*` wiring, transaction boundary) |
| RECON-05 | Restart rehydration two-sided — reconstruct from store AND reconcile against live venue | §Priority 2 (reconciling events, bracket re-link) |
| RECON-06 | Order I/O + reconciliation + persistence live-drive + restart validated against OKX sandbox | §Priority 8 (offline gate + opt-in sandbox suite), Validation Architecture |
| RES-01 | Live resilience: reconnect + gap recovery, rate-limit coordination, partial-fill, hardened publish-and-continue | §Priority 6 (reconnect debounce/backoff, failure classification, rate-limit accounting) |
</phase_requirements>

## Summary

This is the reconciliation cluster: the phase gives `VenueAccount` (today a `NotImplementedError` stub, `account/venue.py`) a caching+reconciling body, makes the `OkxExchange` fill stream idempotent/partial-aware, drives the v1.6 SQL stores off the real feed, and adds two-sided restart rehydration + resilience — all sandbox-validated, all inert on the backtest hot path.

The single most important finding: **nautilus-trader (installed in `.venv`) is a directly-usable reference for every deferred mechanic, and the pieces map cleanly onto seams we already built.** `is_within_single_unit_tolerance` (nautilus `live/reconciliation.py:52`) is a two-line function — `tolerance = Decimal(10) ** -precision; abs(v1-v2) <= tolerance` — that reads the instrument's `size_precision`/`price_precision`, exactly the `_INSTRUMENT_SCALES`/`Instrument.quantity_precision` our `core/money.py::quantize` already consumes. Nautilus's continuous reconciliation loop (`live/execution_engine.py`) is a **retry-then-resolve-then-give-up** state machine gated by a **local-activity threshold** (skip reconcile if a fill landed within `position_check_threshold_ms`, default 5000ms) — which is the *same phantom-drift-race defense* our D-15 "compare on the engine thread, not the async thread" chooses. The store side of two-sided restart already exists: `CachedSqlOrderStorage.rehydrate()` (`order_handler/storage/cached_sql_storage.py:264`) loads open orders + bracket parents; Phase 5 adds the **venue side** (REST snapshot → reconcile → reconciling events / halt).

**Second key finding:** the `OkxExchange` fill stream (`execution_handler/exchanges/okx.py`) has two documented latent gaps that Phase 5 must close: (1) `_handle_trade` emits `FillEvent("EXECUTED")` per venue trade with **no fill-ID dedup and no cumulative-filled/terminalization tracking** — the order mirror is only reconciled by `OrderHandler.on_fill` downstream; (2) a **fast-fill race** — a fill can arrive on `watch_my_trades` before `create_order` returns the venue id, so `_handle_trade` resolves `order=None` and silently drops it (documented at `okx.py:88-96`). The fix (register a pending correlation keyed by `clOrdId` before submit; buffer unmatched fills briefly) is a Phase-5 deliverable.

**Primary recommendation:** Port nautilus's reconciliation primitives conceptually (do NOT depend on `nautilus_trader` at runtime — it stays a dev/reference dependency), keyed to our `Instrument` precision and `VALID_ORDER_TRANSITIONS`. Structure Phase 5 as five task clusters: (A) `VenueAccount` cache + push + engine-thread drift compare/halt; (B) partial-fill idempotency + fast-fill-race fix in `OkxExchange`; (C) store live-drive wiring (`CachedSql*` on the sync path, signals/metrics on the async path) + D-16 BAR-keyed metrics; (D) two-sided restart (venue REST reconcile + reconciling events + bracket re-link); (E) resilience (reconnect debounce/backoff, failure classification, D-07 HALTED status, D-06 alert sink) + the doc-sync (D-18). Gate everything with the offline fixture suite; validate against sandbox with the opt-in `slow` suite.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Venue balance/margin/position cache | Connector asyncio thread (writes cache) | `VenueAccount` (holds cache) | D-14: push stream writes on the connector loop thread; VenueAccount owns the data structure |
| Drift COMPARE + halt DECISION | Engine thread (`PortfolioHandler.on_fill` + BAR route) | — | D-15: single-writer contract; avoids phantom-drift race (Pitfall 8) |
| Partial-fill accumulation + fill-ID dedup | Execution adapter (`OkxExchange._handle_trade`) | `OrderHandler.on_fill` (mirror reconcile) | Fill money crosses at the adapter edge; mirror state transitions downstream |
| Order-mirror terminalization (CANCELLED-with-fills) | `OrderHandler.on_fill` (engine thread) | `watch_orders` status stream (adapter) | Order lifecycle is order-domain; venue status stream is the truth signal |
| Sync-durable working-set persistence | `CachedSqlOrderStorage` / portfolio `CachedSql*` (store-first) | Postgres (system of record) | D-10: create/terminalize + position/cash must survive a crash |
| Equity curve / metrics / signals persistence | Async/best-effort writer (off engine thread) | Postgres | D-10/D-11: derived/advisory, must never stall the loop (Pitfall 9) |
| Restart working-set reconstruction | `CachedSql*.rehydrate()` (already built) | — | Store is truth for INTENT (D-03) |
| Restart venue reconciliation + reconciling events | Engine thread (startup, before RUNNING) | Connector REST (`fetch_balance`/`fetch_positions`/`fetch_open_orders`/`fetch_my_trades`) | Venue is truth for balances/positions/fills (D-03) |
| Reconnect / backoff / failure classification | Connector asyncio thread (stream loops) | `LiveTradingSystem` status (D-07) | Transport concern; bottled at the connector edge (Pitfall 9) |
| HALTED status + alert egress | `LiveTradingSystem.get_status()` + `ErrorEvent`→`_log_error_event` | Pluggable alert sink (D-06) | Engine-observable, infra-deliverable |

## Standard Stack

**No new third-party packages.** This phase is entirely composition/wiring over already-vetted dependencies. The stack is reuse-only:

### Core (all already installed + vetted in Phases 2/1.6)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ccxt` / `ccxt.pro` | 4.5.56 [CITED: pyproject.toml] | OKX REST + WS (balance/position/fills). `watch_my_trades`, `watch_orders`, `watch_balance`, `fetch_balance`, `fetch_positions`, `fetch_open_orders`, `fetch_my_trades` | Already the connector transport (Phase 2); no version bump needed (`02-RESEARCH.md` confirmed full surface) |
| `sqlalchemy` + `psycopg2-binary` | 2.0.50 / 2.9.12 [CITED: CLAUDE.md] | Postgres system-of-record (order/portfolio-state/signal) | v1.6 stores built + testcontainers-tested |
| `Decimal` (stdlib) | — | Money end-to-end via `to_money` | Locked money policy |
| `uuid-utils` | 0.16.0 | UUIDv7 event/order ids | Locked single-scheme |

### Reference-only (installed, NOT a runtime dependency)
| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `nautilus-trader` | 1.227.0 [CITED: CLAUDE.md] | **Reference algorithm** for reconciliation (`live/reconciliation.py`, `live/execution_engine.py`, `adapters/okx/`) | Non-gating oracle already in `.venv`; we PORT the concepts, never `import nautilus_trader` on the live path |

**Installation:** none. Do not add `nautilus_trader` to the live import path — it must stay a dev/reference dependency (importing it onto the live arm would risk the backtest-inertness gate and add a heavy Rust-backed dep to the runtime).

## Package Legitimacy Audit

**Not applicable — this phase installs no external packages.** All libraries in the Standard Stack are already present in `pyproject.toml` / `poetry.lock` and were legitimacy-vetted at their introduction (ccxt/uuid-utils in prior v1.7 phases; sqlalchemy/psycopg2 in v1.6; nautilus-trader/backtesting.py/backtrader as cross-validation oracles). No `npm`/`pip install` step is introduced. The `slopcheck`/registry gate is vacuously satisfied (zero new packages).

## Architecture Patterns

### System Architecture Diagram — the reconciliation cluster

```
                         OKX venue (sandbox: wspap.okx.com / REST demo)
                          │            │              │
             watch_my_trades   watch_orders   watch_balance / fetch_* (REST)
                          │            │              │
   ┌──────────────────────┼────────────┼──────────────┼──────────────────────┐
   │ CONNECTOR asyncio thread (OkxConnector loop-on-daemon-thread)            │
   │   OkxExchange._stream_fills ─┐   _stream_orders ─┐   VenueAccount stream ┐│
   │   (partial accumulate +      │   (status →       │   (D-14 push: write   ││
   │    fill-ID dedup, D-12)      │    terminalize    │    cache, NEVER        ││
   │                              │    signal)        │    compare/halt)       ││
   │           global_queue.put(FillEvent)  │  (cache write only)              ││
   └──────────────┬───────────────────────┼─────────────────────────────────┘│
                  │  MPSC-safe put         │  thread-safe cache write          │
                  ▼                        ▼                                    │
        ┌───────────────────┐    ┌──────────────────────┐                      │
        │   global_queue    │    │ VenueAccount._cache  │◄── async writes only │
        │   (queue.Queue)   │    │ (balances/positions) │                      │
        └─────────┬─────────┘    └──────────┬───────────┘                      │
                  │ get()                    │ READ on engine thread            │
                  ▼                          │ (D-15)                           │
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ ENGINE THREAD (single writer, D-19)                                        │
   │  FILL route: PortfolioHandler.on_fill → position/cash mutate               │
   │              → DRIFT COMPARE (engine cache vs VenueAccount cache,           │
   │                 is_within_single_unit_tolerance) → adopt | HALT (D-01/04)   │
   │              OrderHandler.on_fill → mirror reconcile (partial/terminal,D-12)│
   │  BAR route:  record_metrics(event.time) [D-16] + periodic drift sweep [D-15]│
   │  HALT:       freeze new submissions in place (D-02); status=HALTED (D-07);  │
   │              CRITICAL ErrorEvent → alert sink (D-06)                        │
   └───────┬───────────────────────────────────────────┬───────────────────────┘
           │ sync-durable (store-first)                 │ async/best-effort
           ▼ order create/terminalize + position/cash   ▼ equity curve/metrics/signals
   ┌───────────────────────┐                    ┌───────────────────────┐
   │ CachedSqlOrderStorage │  ── Postgres ──►    │ async writer (D-10/11)│
   │ CachedSql portfolio*  │  (system of record)│ signals live-drive    │
   └───────────────────────┘                    └───────────────────────┘

   RESTART (two-sided, D-03/D-05, runs before status=RUNNING):
     CachedSql*.rehydrate()  ──►  working set (INTENT truth)
     connector REST snapshot ──►  venue truth (balances/positions/open orders/fills)
     reconcile → reconciling FillEvents (adopt-in-band) | halt (unexplained)
     bracket re-link parent_order_id/child_order_ids | per-bracket halt (D-05)
```

### Pattern 1: Precision-epsilon tolerance (D-01) — port nautilus verbatim
**What:** One function, keyed to the instrument precision our `quantize` already uses.
**When:** Every drift comparison (on-fill, on-bar, restart).
```python
# Source: nautilus_trader/live/reconciliation.py:52 (ported — DO NOT import nautilus)
from decimal import Decimal

def is_within_single_unit_tolerance(v1: Decimal, v2: Decimal, precision: int) -> bool:
    if precision == 0:
        return v1 == v2                      # integer quantities: exact match
    tolerance = Decimal(10) ** -precision    # one least-significant-digit unit
    return abs(v1 - v2) <= tolerance
```
For a BTC-USDT-style instrument: `precision` = the instrument's `quantity_precision`/`size_precision`. Our `_DEFAULT_SCALES["quantity"] = Decimal("0.00000001")` (8dp) → `precision = 8` → **quantity epsilon = 1e-8 BTC**; `_DEFAULT_SCALES["price"] = 0.01` (2dp) → **price epsilon = 0.01**; `_CASH_SCALES["USD"] = 0.01` → **cash epsilon = 0.01 USD**. At runtime the epsilon derives from the **loaded OKX market precision** (`client.markets[symbol]['precision']['amount'|'price']`), NOT a hardcode — OKX BTC-USDT spot is `lotSz 0.00000001` / `tickSz ~0.1` [ASSUMED — read at runtime from `load_markets`]. Map `precision(amount)` → quantity epsilon, `precision(price)` → price epsilon, and reconcile the OKX market filters into the engine `Instrument` at connector init (Pitfall 7).

### Pattern 2: Retry-then-resolve-then-give-up, gated by local-activity threshold (D-15/Pitfall 8)
**What:** nautilus's continuous position reconciliation avoids the phantom-drift race by **skipping reconciliation when a local fill landed within a threshold window** — the fill hasn't propagated to the venue snapshot yet.
**When:** The on-bar periodic drift sweep (D-15).
```python
# Source: nautilus_trader/live/execution_engine.py:925-937 (concept ported)
# if last local activity for (instrument) is within position_check_threshold_ms → SKIP
#   (the venue snapshot lags our just-applied fill — comparing now is a false drift)
# else compare cached_qty vs venue_qty via is_within_single_unit_tolerance
#   within band → drift = False (adopt/no-op)
#   beyond band → query missing fills → replay idempotently → re-check
#     still discrepant after retries → nautilus LOGS+STOPS retrying;
#     OUR D-01 choice: HALT the whole engine (freeze in place, D-02)
```
Our D-15 realizes the same defense structurally: **the async thread only writes the cache; the compare runs on the engine thread after the FILL has drained** — so "local activity within threshold" is naturally satisfied (the fill is already applied before we compare). Keep the threshold concept as a belt-and-suspenders for the on-bar sweep only.

### Pattern 3: Reconciling-event generation on restart (D-03)
**What:** When the venue shows a fill/position the store's working set doesn't reflect (landed during downtime), **synthesize a reconciling `FillEvent`** and drive it through the *same* idempotent fill path — never mutate portfolio state directly.
```python
# Source: nautilus_trader/live/reconciliation.py:434 create_inferred_order_filled_event
#   inputs: order (from store working set) + venue OrderStatusReport (filled_qty, avg_px)
#   last_qty = report.filled_qty - order.filled_qty   ← the delta to apply
#   last_px  = incremental cost / last_qty            ← weighted for multi-fill
# OUR analog: build a FillEvent.new_fill("EXECUTED", order, price=..., quantity=delta,
#   commission=venue_fee, time=venue_ts) and global_queue.put it on the ENGINE thread
#   at startup, BEFORE status=RUNNING. Idempotency (fill-ID dedup) prevents double-apply.
```

### Anti-Patterns to Avoid
- **Comparing drift on the async thread** — reads engine-computed state mid-mutation → phantom drift (Pitfall 8). Compare only on the engine thread (D-15).
- **`VenueAccount` computing balance** — it caches venue truth, never recomputes (Pitfall 10, LX-03). `SimulatedAccount` computes; `VenueAccount` mirrors.
- **Recomputing fees** — ingest the venue's actual `fee.cost` per fill (Pitfall 12). Fee drift must be a named, explained reconciliation component, never noise.
- **Auto-flatten/auto-cancel on halt** — D-02: freeze in place; the engine just declared its own state untrustworthy, so it must not act on it.
- **Terminalizing an order on the first partial** — accumulate; terminalize only on cumulative-filled == qty or venue-reported closed (D-12, Pitfall 11).
- **Blocking the asyncio loop with the Postgres write** (Pitfall 9) — sync-durable writes run on the engine/storage side, never in the connector coroutine.
- **Importing `nautilus_trader` on the live path** — reference only; port the concepts.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Drift tolerance | A per-symbol threshold config table | `is_within_single_unit_tolerance(v1,v2,precision)` keyed to `Instrument` precision | Nautilus-proven; ties to existing `quantize` scales; one unit of dust, not a guessed %|
| Fill-ID dedup | A custom seen-set with ad-hoc keys | Key by the venue **trade id** (`trade['id']`); mirror nautilus `get_existing_fill_for_trade_id` (scan order's fill history) | The venue trade id is the idempotency key; re-sends on reconnect carry the same id |
| Restart working-set reconstruction | New rehydration code | `CachedSqlOrderStorage.rehydrate()` (already built, `cached_sql_storage.py:264`) + portfolio `CachedSql*` rehydrate | Store side is DONE — Phase 5 only adds the venue side |
| Store-first write-through | New durability wrapper | `CachedSql*` decorators (store-first, persist-then-acknowledge, already built + tested) | D-10 sync path is the existing wrapper; wire it, don't rebuild |
| Async→queue handoff | New thread bridge | `connector.spawn` / `global_queue.put` (MPSC-safe) — the existing seam | Phase 2 bottled the async boundary; VenueAccount reuses `spawn` for its stream |
| Reconnect/backoff | A bespoke supervisor | A bounded-retry loop wrapping the existing `_stream_*` consume-loops | ccxt keeps `enableRateLimit=True`; add classification + backoff, don't re-architect |
| Rate limiting | A token bucket | ccxt's built-in throttler (`enableRateLimit=True`, already ON, `okx.py:137`) | RES-01: IP-connection-level, light; ccxt owns it |

**Key insight:** ~80% of this phase is wiring already-built seams (`CachedSql*`, `VenueAccount` constructor, `OkxExchange` streams, `_publish_and_continue`, `get_status`) and porting ~4 small nautilus pure-functions. The genuinely new code is: the `VenueAccount` cache + drift-compare, the fill-ID dedup + fast-fill-race fix, the venue-side restart reconcile, and the resilience wrapper.

## Runtime State Inventory

> This phase drives live venue + Postgres state, so runtime state beyond the repo files is central.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (Postgres system-of-record) | Order lifecycle rows + state_changes, portfolio-state, signals — driven by the real OKX feed for the first time (v1.6 built them but only testcontainers-drove them). `CachedSql*.rehydrate()` reads open orders + bracket parents on restart. | Wire `CachedSql*` on the sync path (D-10); signals on async (D-11); verify rehydrate against a live-driven store (not just testcontainers) |
| Live service config (OKX venue, NOT in git) | The **OKX subaccount** state — balances, open orders, resting bracket legs, positions, fill history — lives on OKX, exclusively controlled by this worker (assumed). Restart must reconcile against it (D-03). Sandbox demo keys route via host `wspap.okx.com` + REST `x-simulated-trading`. | Two-sided restart: REST snapshot (`fetch_balance`/`fetch_positions`/`fetch_open_orders`/`fetch_my_trades`) → reconcile → reconciling events / halt |
| OS-registered state | None — the worker is a standalone process launched via `scripts/run_live_paper.py` (`--mode okx`); no Task Scheduler / launchd / pm2 registration in scope (D-08 defers the control plane). | None — verified: worker is launched directly, no OS registration |
| Secrets / env vars | `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` (plain, no prefix — CONN-06) via `OkxSettings(BaseSettings)`, `SecretStr`. `SYSTEM_DB_URL` gates Postgres-vs-in-memory order storage (`live_trading_system.py:183`). VenueAccount adds NO new secret — reuses the injected connector session. | None new; verify `SYSTEM_DB_URL` set for durable restart; keep `SecretStr` scrubbing (Pitfall 16) |
| Build artifacts | None — no compiled artifact carries state; the in-memory backtest signal-store factory (`live_trading_system.py:171`) is a stale wiring default to replace with the live-driven store (D-11). | Replace `SignalStorageFactory.create('backtest')` with the async-best-effort live store |

**The canonical question — after every repo file is updated, what runtime systems still hold state?** The **OKX subaccount** (positions/orders/fills — reconciled via REST on restart) and **Postgres** (working set — rehydrated via `CachedSql*.rehydrate()`). Two-sided restart (D-03) exists precisely because these two can disagree after downtime.

## Common Pitfalls

The 2026-06-30 `PITFALLS.md` is load-bearing; the Phase-5-owned ones (verified against code this session):

### Pitfall 8: Async→single-writer phantom-drift race (D-15)
**What goes wrong:** Comparing venue-cache vs engine-computed state from the async thread before the queue drained the fill → false "drift" → false halt.
**How to avoid:** Async thread writes the VenueAccount cache ONLY. Drift compare + halt decision run on the engine thread (`on_fill` + BAR route). Confirmed structurally sound: `OkxExchange._handle_trade` already only `global_queue.put`s from the connector loop (`okx.py:272`); VenueAccount's stream must follow the same discipline (cache write, never compare).
**Warning signs:** Any `is_within_single_unit_tolerance` call reachable from a `spawn`ed coroutine; a halt that fires then self-resolves next bar.

### Pitfall 9: Stalling the loop with the DB write (D-10)
**What goes wrong:** Sync Postgres write on the connector asyncio loop → missed heartbeats → reconnect storm.
**How to avoid:** Sync-durable working-set writes run on the engine/storage side (via `CachedSql*` store-first), never inside a connector coroutine. Equity/metrics/signals on the async/best-effort writer. Keep-only-measured: build async buffering only if profiled.

### Pitfall 11: Partial/duplicate/mis-sequenced fills (D-12)
**What goes wrong:** The order mirror (built for one clean simulated fill) double-counts a re-sent fill, marks FILLED on the first partial, or chokes on a fill-before-ack.
**How to avoid:** Key fills by venue trade id (dedup); accumulate against cumulative-filled; terminalize only on full/venue-closed; **fix the fast-fill race** (`okx.py:88-96`) by registering a pending correlation keyed by `clOrdId` before the submit RPC and briefly buffering unmatched fills. Currently `_handle_trade` drops an unknown-order fill (`okx.py:237-239`) — that drop is the race.

### Pitfall 12: Fee/funding drift (Pitfall 12)
**What goes wrong:** Recomputing fees instead of ingesting venue-charged fees → constant-looking drift that grows linearly.
**How to avoid:** Ingest `trade['fee']['cost']` per fill (already done, `okx.py:261-263`, with `abs()` + None-guard). Make fee drift a named component. Spot-only in v1.7; a perp funding line → halt (out of scope but named).

### Pitfall (new, code-verified): stream loops have NO reconnect today
**What goes wrong:** `OkxExchange._stream_fills`/`_stream_orders` (`okx.py:274-297`) and `OkxDataProvider._stream_candles` (`okx_provider.py:191`) loop on `while True: await watch_*()` / `async for msg in ws` — **if the socket drops, the coroutine exits and the task dies with no reconnect**. RES-01/D-19/D-20 must wrap these consume-loops in a bounded-retry reconnect supervisor and pause order submission during the gap.
**Warning signs:** A dead stream task after a network blip; no gap-fill after reconnect.

## Code Examples

### Fill-ID dedup + cumulative-filled + terminalization (D-12) — layered onto `_handle_trade`
```python
# Extends OkxExchange._handle_trade (execution_handler/exchanges/okx.py:226) — TAB-indented file.
# Per venue trade: dedup by trade id, accumulate against the order, terminalize correctly.
trade_id = trade.get("id")
with self._correlation_lock:
    seen = self._seen_trade_ids            # new: set[str] per exchange (or per order)
    if trade_id in seen:
        return                             # duplicate re-send (reconnect) — idempotent no-op
    seen.add(trade_id)
# ... existing Decimal-edge conversion (price/amount/fee) unchanged ...
# accumulate: cumulative_filled[order.order_id] += to_money(str(amount))
# terminalization is OrderHandler.on_fill's job (mirror); the FillEvent carries the increment.
# D-12 mapping onto VALID_ORDER_TRANSITIONS:
#   PENDING --partial--> PARTIALLY_FILLED --more--> ... --full--> FILLED
#   PARTIALLY_FILLED --venue CANCELLED (remainder)--> CANCELLED   (fills stand; NOT an error)
```
`VALID_ORDER_TRANSITIONS` (verified, `core/enums/order.py:81`) already permits `PENDING → PARTIALLY_FILLED → {FILLED, CANCELLED, EXPIRED}` and `PENDING → CANCELLED`, so D-12's partial-then-cancel→CANCELLED needs no enum change.

### VenueAccount cache + push (D-14) — implement the stub body
```python
# account/venue.py — 4-space file; LiveConnector stays TYPE_CHECKING-only (inertness gate).
class VenueAccount(Account):
    def __init__(self, connector: "LiveConnector") -> None:
        self._connector = connector
        self._lock = threading.RLock()          # cross-thread cache guard
        self._venue_balance: Decimal | None = None
        self._venue_available: Decimal | None = None
        self._venue_positions: dict[str, Decimal] = {}   # symbol -> signed qty
        self._stream_handle = None
    # D-14 push: started at connect(); writes cache ONLY (never compares/halts — D-15)
    async def _stream_account(self) -> None:
        while True:                                       # + reconnect wrapper (RES-01)
            update = await self._connector.client.watch_balance()
            with self._lock:
                self._venue_balance = to_money(str(update["total"]["USDT"]))  # Decimal edge
    # REST snapshot for startup / restart-reconcile / gap recovery (D-14/D-19)
    def snapshot(self) -> None:
        bal = self._connector.call(self._connector.client.fetch_balance())
        pos = self._connector.call(self._connector.client.fetch_positions())
        with self._lock:
            self._venue_balance = to_money(str(bal["total"]["USDT"]))
            # ... populate positions ...
    # balance/available READ on the engine thread (D-15 compare consumes these)
    @property
    def balance(self) -> Decimal:
        with self._lock:
            if self._venue_balance is None:
                raise StateError(...)   # not yet snapshotted — surfaces, never silently 0
            return self._venue_balance
```
Note: `VenueAccount` under LX-04 (1 acct : 1 portfolio) is the account for a single portfolio; it does NOT implement `reserve`/`release` as cash math (the venue owns reservations) — decide whether those raise or delegate to the venue's frozen/available balance at plan time (see Open Questions).

### D-16 BAR-keyed metrics fix (live daemon)
```python
# live_trading_system.py:649 (WR-01/D-16): TIME → BAR; LiveBarFeed emits only BarEvent.
if hasattr(event, 'type') and event.type == EventType.BAR:
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)   # async/best-effort path (D-10)
```

### D-07 HALTED status
```python
# core/enums/system.py:14 — add HALTED (+ optionally PAUSED). Current members:
#   STOPPED/STARTING/RUNNING/STOPPING/ERROR — no HALTED/PAUSED today.
class SystemStatus(Enum):
    ...
    HALTED = "halted"          # D-07: reason ∈ {drift, reconciliation-unresolved,
                               #                connector-fatal, paused-on-disconnect}
# get_status() (live_trading_system.py:797) returns self._status.value + a halt_reason field.
```

### D-06 alert sink — thin pluggable seam
```python
# Escalate a halt to CRITICAL ErrorEvent (events/error.py — severity=ErrorSeverity.CRITICAL
# already exists, enums/severity.py:24) and route through a pluggable AlertSink Protocol.
class AlertSink(Protocol):
    def alert(self, event: ErrorEvent) -> None: ...
class LogAlertSink:                              # the ONLY impl this milestone (D-06)
    def alert(self, event: ErrorEvent) -> None: ...   # marked structured log
# EventHandler._log_error_event stays the default consumer; the sink is an injected seam
# so Telegram/webhook drops in later WITHOUT touching engine code.
```

## State of the Art

| Old Approach (backtest/paper) | Current Approach (live real) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SimulatedAccount` computes balance/margin | `VenueAccount` caches venue truth, reconciles per-symbol drift | Phase 5 | Venue = source of truth in live (Pitfall 10, LX-03) |
| One clean terminal fill per order (`MatchingEngine`) | Partial/duplicate/mis-sequenced venue fills, idempotent handling | Phase 5 | Fill-ID dedup + cumulative accumulation (Pitfall 11) |
| Restart = store-only rehydrate (v1.6, testcontainers) | Two-sided: store working set + venue REST reconcile | Phase 5 | Broker-side gap closed (Pitfall 13) |
| Engine fee model | Venue-reported fee ingested per fill | Phase 5 (partly Phase 2 `okx.py:261`) | Fee drift named, not recomputed (Pitfall 12) |
| TIME-keyed metrics (`_event_processing_loop`) | BAR-keyed metrics (D-16) | Phase 5 | Live equity curve actually recorded (WR-01) |
| Fail-fast everywhere | Split: replay=fail-fast, live=publish-and-continue hardened | Phase 5 (D-17) | Parity gate can't false-green; live can't abort on one handler error |

**Deprecated/outdated:**
- `SignalStorageFactory.create('backtest')` on the live path (`live_trading_system.py:171`) — replace with the live-driven async-best-effort signal store (D-11).
- Stale ROADMAP/REQUIREMENTS text (RUN-01 "LISTEN/NOTIFY in Phase 4"; PAPER-01/02/04 "byte-exact vs 46189…") — doc-sync in Phase 5 (D-18).

## Priority Resolutions (the deferred plan-time mechanics)

**1. Drift precision-epsilon (D-01).** `tolerance = Decimal(10) ** -precision`; `precision` = the instrument's amount/price precision from OKX `load_markets` (`client.markets[sym]['precision']`), reconciled into the engine `Instrument` at connector init. BTC-USDT: quantity epsilon 1e-8 (8dp lotSz), price epsilon per tickSz, cash epsilon 0.01 USD. Within band → adopt to venue truth silently; beyond band AND unexplained → whole-engine halt. Seam: new `drift.py` helper (port `is_within_single_unit_tolerance`) called from `PortfolioHandler.on_fill` + BAR route. Ref: nautilus `live/reconciliation.py:52`, `execution_engine.py:1058/1086`.

**2. Two-sided restart (D-03/D-05).** Store side DONE (`CachedSqlOrderStorage.rehydrate()` + portfolio `CachedSql*`). Add venue side: on startup, before RUNNING — `fetch_balance`/`fetch_positions`/`fetch_open_orders`/`fetch_my_trades`; for each venue delta mapping to a stored order → synthesize a reconciling `FillEvent` (increment = `venue.filled_qty - order.filled_qty`, per nautilus `create_inferred_order_filled_event:481`); in-band → adopt; venue position with NO stored intent → halt-and-alert. Brackets: re-link `parent_order_id`/`child_order_ids` from the store's rehydrated parents against venue resting orders; a leg not confidently re-linked → per-bracket halt (D-05). Seam: new restart-reconcile step in `_initialize_live_session` / a `ReconcileManager`. Ref: nautilus `_process_cached_position_discrepancies:893`, `reconciliation.py:434`.

**3. OKX partial-fill cadence + idempotency (D-12/D-13).** `watch_my_trades` delivers **one trade per fill increment** (each carries its own `id`, `order` (venue order id), `amount` (this increment), `price`, `fee`, `timestamp`); `watch_orders` delivers order-status transitions (the terminalization signal — `closed`/`canceled` with cumulative `filled`). Correlation: resolve `trade['order']` → originating `OrderEvent` via the existing `_orders_by_venue_id` map (`okx.py:98`). Dedup by `trade['id']` (analog of `get_existing_fill_for_trade_id`). Accumulate increments against the order's cumulative-filled (the store working set is the cross-check, D-13). Terminalize (in `OrderHandler.on_fill`): FILLED when cumulative == qty; CANCELLED when `watch_orders` reports canceled with fills kept (D-12) — both valid on `VALID_ORDER_TRANSITIONS`. **Fix the fast-fill race** (`okx.py:88-96`): register a pending correlation keyed by the client order id (`clOrdId`) BEFORE the submit RPC, and briefly buffer an unmatched fill for late correlation instead of dropping it (`okx.py:237`).

**4. VenueAccount ingestion cache (D-14/D-15).** Cache = `RLock`-guarded fields (`_venue_balance`, `_venue_available`, `_venue_positions: dict[symbol,signed_qty]`) + optional margin fields. Push: a `spawn`ed `_stream_account` consuming `watch_balance`/`watch_positions`, writing the cache ONLY (Decimal edge via `to_money(str(...))`). REST `snapshot()` (via `connector.call`) for startup/restart/gap. Compare: on the engine thread — `PortfolioHandler.on_fill` reads `VenueAccount.balance`/positions and diffs against engine-computed via the D-01 helper; BAR route runs the periodic sweep. LiveConnector stays `TYPE_CHECKING`-only in `venue.py` (inertness). Note: `OkxConnector` currently exposes `client`/`call`/`spawn` but no account-specific methods — VenueAccount drives `connector.client.watch_balance()` through the generic seam (no connector change needed, mirrors how `OkxExchange` uses `watch_my_trades`).

**5. Store split write paths (D-10/D-11).** Sync-durable: wire `CachedSqlOrderStorage` (order create/terminalize) — already store-first (`cached_sql_storage.py:114/141`) — and the portfolio `CachedSql*` for position/cash on fill. Async/best-effort: equity curve + metrics + signals — a background writer (or the existing write-behind cache variant) off the engine thread. **Write-through transaction boundary = keep-only-measured**: per-write store-first is the boundary (within-method atomicity = the store's `engine.begin()`); do NOT build cross-method bracket transactions or async buffering unless the live loop profiles a stall (the wrapper docstring explicitly defers cross-method bracket atomicity to "N+4 reconciliation" = this phase's restart reconcile, handled by re-link+halt, not a DB transaction). D-16 BAR-keyed metrics is the WR-01 fix on the async path.

**6. Live resilience (RES-01/D-19/D-20).** Reconnect: wrap each `_stream_*` consume-loop in a bounded-retry supervisor (they have none today). Debounce: a short window (sub-second, ~250–500ms [ASSUMED]) before pausing on a blip (D-19). Backoff: exponential with a ceiling (e.g. 1s→2s→4s→…→cap ~30s, retry ceiling ~5–8 attempts [ASSUMED — mirror nautilus `open_check_missing_retries=5` / `position_check_retries=3`]) → then HALT (D-20). Classification: transient (network drop, ccxt `NetworkError`/`RequestTimeout`, rate-limit `DDoSProtection`) → retry+stay-running; fatal (`AuthenticationError`, `PermissionDenied`) or ceiling exhausted → HALTED + CRITICAL alert. Rate-limit: ccxt `enableRateLimit=True` already ON (`okx.py:137`) — IP-connection-level, light; no bucket accounting to build (RES-01, Phase-2 established). Pause-on-disconnect: quiesce order submission (surfaced as HALTED/paused, D-07), resume only after reconnect + fresh REST snapshot/reconcile (D-14).

**7. Backtest-inertness verification (milestone gate).** The existing `tests/integration/test_okx_inertness.py` subprocess/import-quarantine test proves the backtest import path pulls no async/connector/SQL. Extend it to cover the new VenueAccount body + reconcile module (all live-arm modules lazy-imported inside the `exchange=='okx'` branch; `LiveConnector` TYPE_CHECKING-only in `venue.py`). Gate: SMA_MACD oracle byte-exact (`134 / 46189.87730727451`, `check_exact=True`, determinism double-run) + no W1/W2 regression vs the v1.5 baseline (15.7s / 152.8MB — note CLAUDE.md/ROADMAP quote 152.8MB; the milestone gate figure is authoritative).

**8. DoD evidence shape (D-09).** (a) **Offline gate** — mocked/recorded OKX fixtures (a `FakeLiveConnector` returning canned `watch_my_trades`/`watch_orders`/`fetch_*` payloads) exercising: drift within/beyond band, partial→full→CANCELLED, duplicate-fill dedup, fast-fill-race, two-sided restart (store+venue), bracket re-link + per-bracket halt. Deterministic, credential-free, in CI, `filterwarnings=["error"]` green via `pytest-asyncio`. (b) **Opt-in sandbox suite** — marked `slow`, `skipif` no `OKX_API_*` creds, running the real order→fill→reconcile→restart loop against OKX demo, run locally (the Phase-2 D-09 pattern, `scripts/run_live_paper.py --mode okx`). Real-money stays gated.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OKX BTC-USDT spot precision (lotSz 1e-8, tickSz ~0.1) — used only as an illustrative epsilon; real value read at runtime from `load_markets` | Priority 1 | LOW — epsilon derives from loaded market precision, not the hardcode; the illustration just needs to be labeled |
| A2 | `watch_my_trades` delivers one trade per fill increment with a unique `id` and `order` (venue order id); `watch_orders` carries the terminalization signal | Priority 3 | MEDIUM — if OKX/ccxt batches or omits `id`, dedup key + accumulation logic change; verify against sandbox recordings before locking |
| A3 | Reconnect debounce ~250–500ms; backoff cap ~30s; retry ceiling ~5–8 | Priority 6 | LOW — tuning values; nautilus defaults (retries 3–5) are the anchor; adjust from sandbox behavior |
| A4 | ccxt `enableRateLimit` throttler is sufficient (no custom bucket) for the 1d-bar sandbox workload | Priority 6 | LOW — Phase 2 established IP-connection-level/light; low order rate on 1d bars |
| A5 | `watch_balance`/`watch_positions` exist and stream on OKX via ccxt.pro for the account push (D-14) | Priority 4 | MEDIUM — if a channel is REST-only, D-14 falls back to REST-poll for that stream (still satisfies snapshot+gap); verify the private-channel surface |
| A6 | VenueAccount `reserve`/`release` semantics under a venue-owned account (raise vs delegate to venue frozen/available) | Priority 4 / Open Q | MEDIUM — affects the order-admission cash-reservation gate on the live path; needs a decision |

## Open Questions

> **(RESOLVED / OUT OF SCOPE for the 05-10/05-11 gap-closure pass, 2026-07-02.)** All three open
> questions below were settled during the original 05-01..05-09 execution (VenueAccount reserve/release
> overlay, 1d on-bar drift-sweep backstop, and bracket-leg re-link by persisted `venue_order_id`), which
> shipped and passed their plan-level verification. None of them touch the confirmed gap-closure defects
> (CR-01, WR-01, WR-02, WR-03, WR-04). They are retained here as the original research record and require
> no further action for the gap-closure re-plan.

1. **VenueAccount.reserve/release semantics.**
   - What we know: the `Account` ABC requires `reserve(order_id, amount)`/`release(order_id)`; `SimulatedCashAccount` tracks reservations locally; the order-admission gate calls `reserve` before submit.
   - What's unclear: on a venue-owned account the venue enforces available balance — does `VenueAccount.reserve` (a) track a local pending-reservation overlay on top of the cached venue available, (b) delegate to the venue's frozen/available, or (c) raise (reservation is meaningless when the venue is truth)?
   - Recommendation: local pending-reservation overlay (cached venue available − sum of local pending) so the admission gate keeps working pre-fill, reconciled to venue truth on the next snapshot. Confirm with the user at plan/discuss time.

2. **Drift-halt granularity vs the on-bar sweep on 1d bars (D-15).**
   - What we know: on-fill compare is immediate; the on-bar backstop is up to a day on 1d bars (accepted, D-15).
   - What's unclear: whether slow-accrual fee/funding drift within a day needs any interim signal for the sandbox DoD.
   - Recommendation: accept the 1d backstop for v1 (faster on-timer backstop is explicitly deferred); make the on-fill compare cover the common case.

3. **What "confidently re-linked" means for a bracket leg (D-05).**
   - What we know: re-link uses stored `parent_order_id`/`child_order_ids` against venue resting orders.
   - What's unclear: the exact match predicate (venue order id correlation survives restart? or match by symbol+side+trigger price?).
   - Recommendation: match by the stored venue order id first (persist it in the working set — verify it's stored); fall back to symbol+side+price+qty; ambiguous → per-bracket halt. Confirm the venue order id is persisted on the order mirror.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `ccxt`/`ccxt.pro` | OKX REST+WS | ✓ | 4.5.56 | — |
| `sqlalchemy` + `psycopg2-binary` | Postgres system-of-record | ✓ | 2.0.50 / 2.9.12 | in-memory order storage if `SYSTEM_DB_URL` unset (but breaks durable restart) |
| PostgreSQL (localhost:5432) | Durable working set / two-sided restart | ✗ at research time (not probed; operator-provisioned) | — | in-memory (no restart durability) — blocks the RECON-04/05 durable-restart DoD |
| `nautilus-trader` | Reference algorithm (dev only) | ✓ | 1.227.0 | — (reference only, not runtime) |
| OKX demo credentials (`OKX_API_*`) | Opt-in sandbox suite (D-09) | ✗ (credential-free by design in CI) | — | offline fixture suite runs credential-free; sandbox suite `skipif`-skipped |
| `pytest-asyncio` | Async live-surface tests under strict suite | ✓ (Phase 2) | — | — |

**Missing dependencies with no fallback (blocking):**
- PostgreSQL running for the durable two-sided-restart DoD — the offline gate can mock the store, but the sandbox validation of RECON-04/05 needs a real Postgres. Planner must ensure it's provisioned (testcontainers for the offline gate is the v1.6 pattern; a real Postgres for the sandbox suite).

**Missing dependencies with fallback:**
- OKX demo creds — offline gate is credential-free; sandbox suite is opt-in (`skipif-no-creds`).

## Validation Architecture

> `nyquist_validation: true` (`.planning/config.json`) — this section derives VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 + pytest-asyncio (Phase 2) + pytest-cov |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; markers: `unit`, `integration`, `slow`, `e2e` |
| Quick run command | `poetry run pytest tests/unit/portfolio tests/unit/order tests/unit/execution -x` |
| Full suite command | `make test` (or `poetry run pytest tests` in worktrees — see memory: make test aborts on missing .env in worktrees) |
| Async gotcha | live tests must `await client.close()` in teardown (no `ResourceWarning`); scope any unavoidable third-party warning per-test, never relax the global filter (Pitfall 18) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RECON-01 | drift within band → adopt; beyond band → HALT (per-symbol, precision epsilon) | unit | `pytest tests/unit/portfolio/test_venue_account_drift.py -x` | ❌ Wave 0 |
| RECON-01 | VenueAccount caches venue stream (async write), reads on engine thread | unit (asyncio) | `pytest tests/unit/portfolio/test_venue_account_cache.py -x` | ❌ Wave 0 |
| RECON-02 | partial→full→FILLED; partial→cancel→CANCELLED (fills kept) | unit | `pytest tests/unit/order/test_partial_fill_terminalize.py -x` | ❌ Wave 0 |
| RECON-02 | duplicate fill (same trade id) deduped; fast-fill-race buffered not dropped | unit (asyncio) | `pytest tests/unit/execution/test_okx_fill_idempotency.py -x` | ❌ Wave 0 |
| RECON-03 | halt-and-alert default; CRITICAL ErrorEvent + HALTED status | unit | `pytest tests/unit/execution/test_drift_halt_policy.py -x` | ❌ Wave 0 |
| RECON-04 | order create/terminalize sync-durable (store-first); signals/metrics async | integration (testcontainers PG) | `pytest tests/integration/test_store_live_drive.py -x` | ❌ Wave 0 |
| RECON-04 | D-16 BAR-keyed live metrics record an equity curve | integration | `pytest tests/integration/test_live_bar_metrics.py -x` | ❌ Wave 0 |
| RECON-05 | two-sided restart: store rehydrate + venue REST reconcile → reconciling events | integration (testcontainers PG + FakeLiveConnector) | `pytest tests/integration/test_two_sided_restart.py -x` | ❌ Wave 0 |
| RECON-05 | bracket parent/child re-link from stored ids; unconfident leg → per-bracket halt | integration | `pytest tests/integration/test_bracket_restart_relink.py -x` | ❌ Wave 0 |
| RECON-06 | real order→fill→reconcile→restart loop against OKX demo | e2e (slow, skipif-no-creds) | `pytest tests/e2e/test_okx_sandbox_recon.py -m slow` | ❌ Wave 0 |
| RES-01 | reconnect+gap recovery; bounded retry→HALT on exhaustion; pause-on-disconnect | unit (asyncio) | `pytest tests/unit/execution/test_reconnect_resilience.py -x` | ❌ Wave 0 |
| gate | oracle byte-exact + inertness (no async/SQL leak on backtest path) | integration | `pytest tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py -x` | ✓ (extend) |

### Sampling Rate
- **Per task commit:** the touched cluster's quick run (e.g. `pytest tests/unit/execution -x`).
- **Per wave merge:** full offline suite + oracle + inertness gate.
- **Phase gate:** full suite green + oracle byte-exact + no W1/W2 regression before `/gsd:verify-work`; the opt-in sandbox suite run locally as the RECON-06 "validated" evidence.

### Wave 0 Gaps
- [ ] `tests/unit/portfolio/test_venue_account_drift.py`, `test_venue_account_cache.py` — RECON-01
- [ ] `tests/unit/order/test_partial_fill_terminalize.py` — RECON-02
- [ ] `tests/unit/execution/test_okx_fill_idempotency.py`, `test_drift_halt_policy.py`, `test_reconnect_resilience.py` — RECON-02/03, RES-01
- [ ] `tests/integration/test_store_live_drive.py`, `test_live_bar_metrics.py`, `test_two_sided_restart.py`, `test_bracket_restart_relink.py` — RECON-04/05
- [ ] `tests/e2e/test_okx_sandbox_recon.py` (marked `slow`, `skipif-no-creds`) — RECON-06
- [ ] Shared fixture: a `FakeLiveConnector` (extend the Phase-2 conftest fake) with canned `watch_my_trades`/`watch_orders`/`watch_balance`/`fetch_*` payloads + recorded OKX fixtures (credential-free)
- [ ] Extend `tests/integration/test_okx_inertness.py` to cover the new VenueAccount body + reconcile module
- [ ] Framework: `pytest-asyncio` already configured (Phase 2) — no install

## Security Domain

`security_enforcement` is not set in `.planning/config.json` (absent = enabled), but this is an internal engine phase with no new external attack surface. The applicable controls are narrow and largely inherited from Phase 2.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (inherited) | OKX auth via `OkxSettings(BaseSettings)` + `SecretStr` (Phase 2, CONN-06); no new secret in Phase 5 |
| V5 Input Validation | yes | Every venue payload (fills/balances/positions/order status) validated + skipped-and-logged, never indexed blindly (mirror `okx.py:244` / `okx_provider.py:228`); Decimal edge via `to_money(str(...))` |
| V6 Cryptography | yes (inherited) | `SecretStr` credentials; never hand-rolled; keys never in logs/`ErrorEvent`/store (Pitfall 16) — scrub connector exceptions before the D-06 alert emits |
| V4 Access Control | no | Single-worker, single-subaccount; the FastAPI/multi-tenant layer is deferred (D-08) |

### Known Threat Patterns for the live OKX path
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leakage via the new CRITICAL `ErrorEvent`/alert sink | Information Disclosure | Scrub auth/request context before emitting the alert (D-06); `SecretStr`; test no key material in emitted events (Pitfall 16) |
| Malformed venue payload crashing a stream (drops all subsequent fills) | Denial of Service | Per-item skip-and-log in every stream loop (already the `_stream_fills`/`_process_row` policy); reconnect supervisor keeps the loop alive |
| Sandbox/live split-brain (order to wrong book) | Tampering | Single `sandbox: bool` routes both paths (Phase 2, CONN-03); no new toggle in Phase 5; VenueAccount reuses the same session |
| Float-precision poisoning the reconciled ledger | Tampering | `to_money(str(x))` at every venue-float boundary; never `Decimal(float)` (Pitfall 6, money policy) |

## Sources

### Primary (HIGH confidence — read from installed source this session)
- `nautilus_trader/live/reconciliation.py` (`.venv`, v1.227.0) — `is_within_single_unit_tolerance:52`, `get_existing_fill_for_trade_id:85`, `create_inferred_order_filled_event:434`, `create_order_{canceled,filled}_event`
- `nautilus_trader/live/execution_engine.py` — `_handle_queue_exception:536` ("terminate immediately to prevent operation in degraded state":553), `_process_cached_position_discrepancies:893`, `_check_position_discrepancy:1041`, retry/threshold gating
- `nautilus_trader/live/config.py` — reconciliation knob defaults (`inflight_check_retries=5`, `position_check_retries=3`, `position_check_threshold_ms=5000`, `open_check_missing_retries=5`, `reconciliation_startup_delay_secs=10`, `filter_unclaimed_external_orders=False`, `generate_missing_orders=True`)
- iTrader source (read directly): `portfolio_handler/account/{venue,base}.py`, `connectors/{base,okx}.py`, `execution_handler/exchanges/okx.py`, `price_handler/providers/okx_provider.py`, `order_handler/storage/cached_sql_storage.py`, `trading_system/live_trading_system.py` (composition root, `_event_processing_loop`, `get_status`, `run_paper_replay`), `core/money.py`, `core/enums/{order,system,severity}.py`, `events_handler/events/error.py`
- `.planning/phases/05-.../05-CONTEXT.md` (D-01..D-20, authoritative), `.planning/research/PITFALLS.md`, `ARCHITECTURE.md`, `04-REVIEW.md`, `REQUIREMENTS.md`, `ROADMAP.md`

### Secondary (MEDIUM confidence)
- OKX v5 instrument spec (lotSz/tickSz/minSz) — [OKX API guide](https://www.okx.com/docs-v5/en/), [ccxt okx docs](https://docs.ccxt.com/exchanges/okx); [OKX NautilusTrader integration](https://nautilustrader.io/docs/latest/integrations/okx/) — BTC precision read at runtime from `load_markets`
- ccxt issues #21885 (confirm flag), #17710 (amount precision), #7415 (float precision) — via PITFALLS.md

## Metadata

**Confidence breakdown:**
- Reconciliation algorithm (epsilon, retry, reconciling events): HIGH — ported from installed nautilus source + mapped to our `Instrument`/`money.py`
- Code seams (VenueAccount, OkxExchange, CachedSql*, live system): HIGH — read directly this session
- OKX fill/account payload cadence: MEDIUM-HIGH — nautilus OKX adapter + ccxt behavior; firm up against sandbox recordings (A2/A5)
- Resilience tuning values (debounce/backoff/ceiling): MEDIUM — anchored to nautilus defaults, tune from sandbox (A3)

**Research date:** 2026-07-02
**Valid until:** ~2026-08-01 (stable — reuse-only over vetted deps; nautilus reference is version-pinned)
