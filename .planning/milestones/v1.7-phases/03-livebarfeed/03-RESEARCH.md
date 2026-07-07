# Phase 3: LiveBarFeed - Research

**Researched:** 2026-07-01
**Domain:** Live streaming market-data read-model (ring-buffer `BarFeed` impl) on an event-driven engine
**Confidence:** HIGH (all seam signatures verified by reading the actual code; two locked-decision wording gaps surfaced)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Ingestion entry point is `update(closed_bar: ClosedBar)`** (a dict). Phase-2's
  `OkxDataProvider.set_bar_sink(Callable[[ClosedBar], None])` push-callback hands the feed a raw
  confirm-gated `ClosedBar` dict with money already Decimal. The **feed owns `Bar` construction**
  from that dict and appends to the ring. Not `update(Bar)`, not `update(symbol, tf, bar)`. Push,
  not pull; the provider gates `confirm`, the feed builds the `Bar`.
- **D-02 — `update()` emits directly onto `global_queue`** (the bar's ARRIVAL is the event).
  Validate monotonicity → construct `Bar` → append to ring → write `newest_bar` → put a `BarEvent`
  on the queue. Emission may physically fire from the connector's asyncio thread (`queue.Queue`
  MPSC-safe; **D-19 single-writer preserved** — portfolio state mutates only on the engine thread).
- **D-03 — Live emits `BarEvent` DIRECTLY to the BAR route (Option B)**, NOT via a
  `TimeEvent`→`generate_bar_event` pull. Backtest keeps its `TimeEvent`→pull model (D-20);
  unifying backtest is deferred. Parity-safe because the TIME route is a no-op today.
- **D-04 — Single-ticker `BarEvent` payload, coalesce-seam reserved.** `update()` emits
  `BarEvent(time, bars={that_ticker: bar})` — one event per arriving closed bar. Shape the
  `update`/emit seam so a burst-coalescing consolidator can slot in at Phase 6 WITHOUT changing
  the `BarEvent` contract.
- **D-05 — TIME route / `TimeEvent` / `screen_markets` preserved but DORMANT on the live path.**
  Reserved as the Phase-6 screening/poll cadence. Phase 3's obligation: "don't break the seam."
- **D-06 — Full classification taxonomy built into the monotonic guard** (FEED-04). For incoming
  `t` vs last-delivered `L` per `(symbol, timeframe)`: `t == L+tf` deliver; `t > L+tf` gap →
  backfill `[L+tf … t-tf]` replay then deliver; `t == L` identical → drop; `t == L` differ →
  revision (forward-only WARN+drop, no state mutation); `t < L` stale → reject+log.
- **D-07 — Bar-correction reaction = forward-only + log (re-warm REJECTED).** Indicator state
  never rewound. The `confirm==1` gate means a forming bar is never delivered to revise.
- **D-08 — Reconnect recovery = proactive backfill-on-reconnect, gated by a completed-bar BOUNDARY
  check** (not raw outage duration). On resume: if most-recent completed-bar open-time `> L`,
  REST-backfill `[L+tf … latest completed]` and replay one-by-one through the same `update()` gap
  path; else nothing. A re-sent bar is dropped by the duplicate branch.
- **D-09 — Ring `maxlen` = `BarFeed.cache_capacity()`** — same wiring-time derivation as backtest
  (never hand-set). `deque(maxlen=cache_capacity())` per `(symbol, timeframe)`.
- **D-10 — Warmup depth `K = cache_capacity() + safety margin`.** Fetch enough to satisfy BOTH
  cache hydration AND stateful-indicator readiness via the same one-by-one replay through
  `update()`. (Plan-time: pick the exact margin.)
- **D-11 — Live serves multiple timeframes by base-timeframe stream + pull-resample (backtest
  parity), NOT native tagged multi-tf.** Subscribe the finest needed tf as the single `BarEvent`
  stream; higher tfs pulled via `feed.window(ticker, tf)`. No timeframe tag added to `Bar`/`BarEvent`.

### Claude's Discretion (plan-time)
- Exact `Bar` construction path from the `ClosedBar` dict inside `update()`.
- Exact warmup safety-margin value (D-10).
- Exact thread-hand-off mechanism for the asyncio-thread `update()` → `queue.Queue` put (D-02/D-19).
- Whether the per-`(symbol, timeframe)` ring dict and the monotonic-guard `L` tracking share one
  structure or two.

### Deferred Ideas (OUT OF SCOPE)
- Unify the backtest loop to direct bar generation (`unify-backtest-direct-bar-generation.md`).
- Native tagged multi-timeframe (`native-tagged-multi-timeframe.md`).
- Burst-coalescing multi-symbol `BarEvent` (Phase 6).
- Phase-6 screening/poll cadence wiring the dormant TIME route (Phase 6).
- RES-01 reconnect/backoff hardening (Phase 5 home; D-08 gap-driven recovery ships here).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FEED-01 | `LiveBarFeed` implements `BarFeed` ABC as bounded `deque(maxlen)` ring per `(symbol, timeframe)`, capacity from `cache_capacity()` | ABC contract (§Standard Stack); `cache_registration.derive`; **capacity-derivation gap surfaced** (§Open Questions Q1) |
| FEED-02 | `BarEvent` emitted only on `confirm==1`, bar `time` = venue bar-open stamp, 7-rule look-ahead holds | Provider already gates `confirm` (§Provider seam); `ts`→tz-aware datetime conversion (§Pitfall 2); 7-rule contract quoted (§Architecture) |
| FEED-03 | Warmup/gap replay one-by-one through identical `update(bar)` path, no bulk fast-path | `fetch_ohlcv_backfill` returns `list[ClosedBar]` (§Provider seam); replay loop pattern (§Code Examples) |
| FEED-04 | Monotonic-forward-only: gap→backfill-replay; duplicate→drop; stale→reject; reconnect→gap-fill | Monotonic guard design (§Architecture Pattern 2); D-06 taxonomy |
| FEED-05 | Replaces `TimeGenerator`'s role live, preserving TIME-before-BAR route ordering | `TimeGenerator` role analysis (§Component map); D-03 direct-to-BAR emission |
</phase_requirements>

## Summary

Phase 3 builds `LiveBarFeed`, a second concrete `BarFeed` (the ABC already exists and is fully
specified in `price_handler/feed/base.py`). The entire external surface it consumes is **already
built and tested**: the Phase-2 `OkxDataProvider` exposes `set_bar_sink(Callable[[ClosedBar], None])`
(push seam), a `ClosedBar` TypedDict with Decimal OHLCV, and `fetch_ohlcv_backfill(...) -> list[ClosedBar]`
(the warmup/gap source). This is a **brownfield, mostly-stdlib phase** — no new external packages.
The build is `collections.deque`, `queue.Queue.put`, the existing `Bar` msgspec Struct, and a
monotonic guard. The genuinely novel logic (no backtest analog) is the FEED-04 monotonic taxonomy
and D-08 reconnect gap-fill.

Two locked decisions are **under-specified against the actual current code** and must be resolved
at plan time — these are the highest-value findings:

1. **`ClosedBar` does NOT carry `symbol`/`timeframe`** (verified: it has only `ts,open,high,low,close,volume`).
   D-01's rationale ("the dict already carries the routing keys") is false against today's code. The
   feed's `update(closed_bar)` cannot route the bar to a `(symbol, timeframe)` ring/guard without
   them. **Recommendation:** extend `ClosedBar` with `symbol: str` + `timeframe: str` (the provider
   knows both at construction — a small Phase-2-seam co-shape the provider docstring explicitly
   invites), so `update()` is self-routing per D-01's intent.

2. **`cache_capacity()` returns `1` today** (`NEWEST_BAR_ONLY`, empty raw-bar-consumer set — indicators
   self-buffer under Model B). So D-09's ring `maxlen=cache_capacity()=1` AND D-10's `K =
   cache_capacity() + margin = 1 + margin` would **fetch/replay only ~1 warmup bar**, leaving
   SMA_MACD's indicators (min_period=100) never ready → zero trades → oracle fails. This is the
   phase's single most likely correctness failure. **Recommendation:** at live wiring, register a
   `RawBarConsumer` whose `required_history_depth = max declared strategy warmup` (100 for SMA_MACD),
   so `cache_capacity()` derives to 100 — making D-09 (ring holds 100, D-11 pull-resample works) AND
   D-10 (`K = 100 + margin`) both literally correct and self-consistent. Register on the LIVE feed
   only (oracle-dark — backtest precomputes full frames and never reads `cache_capacity`).

**Primary recommendation:** Implement `LiveBarFeed(BarFeed)` with per-`(symbol,timeframe)`
`deque(maxlen=cache_capacity())` + `L`-tracking guard; all `update()` calls on ONE thread (the
connector asyncio thread) so the feed's ring/guard is single-writer and only the `queue.Queue.put`
crosses threads (D-19 preserved, no lock needed); resolve the two gaps above before coding.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Closed-bar ingestion (`confirm` gate) | Phase-2 data arm (`OkxDataProvider`) | — | Already built/tested; provider gates `confirm==1` and pushes `ClosedBar` |
| `Bar` construction from dict | `LiveBarFeed.update()` | — | D-01: feed owns `Bar` construction + ring |
| Monotonic guard / gap classify | `LiveBarFeed` | — | FEED-04 no backtest analog; feed is the single look-ahead enforcement point |
| Warmup / gap / reconnect backfill fetch | `OkxDataProvider.fetch_ohlcv_backfill` | `LiveBarFeed` (replay driver) | Provider owns REST; feed drives one-by-one replay through `update()` (FEED-03) |
| `BarEvent` emission | `LiveBarFeed.update()` → `global_queue` | — | D-02/D-03 direct-to-BAR; replaces `TimeGenerator` |
| Event draining/dispatch | `EventHandler` on engine thread | `LiveTradingSystem._event_processing_loop` | D-19 single-writer: portfolio mutates only here |
| Higher-timeframe windows | `LiveBarFeed.window()` (inherited pattern) | — | D-11 pull-resample from the ring, identical to backtest |
| Composition / sink wiring | `LiveTradingSystem.__init__` | — | DI root; swaps `BacktestBarFeed`→`LiveBarFeed`, wires `set_bar_sink(feed.update)` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `collections.deque` | stdlib (3.13) | Bounded ring buffer per `(symbol, timeframe)` | `maxlen` gives O(1) append + auto-evict; FEED-01 names it explicitly [CITED: FEED-01] |
| `queue.Queue` | stdlib (3.13) | Cross-thread `BarEvent` emission (asyncio thread → engine thread) | MPSC-safe `put()`; already the engine's `global_queue` [VERIFIED: full_event_handler.py] |
| `msgspec.Struct` (`Bar`) | msgspec (existing dep) | Immutable per-tick OHLCV fact | Already the `BarEvent.bars` value type [VERIFIED: core/bar.py] |
| `pandas.Timestamp` | pandas ^2.3.3 (existing) | tz-aware bar `time` stamp | `window()`/`searchsorted` require tz-aware; matches backtest [VERIFIED: bar_feed.py:616] |
| `itrader.outils.time_parser.to_timedelta` | internal | `"1d"` → `timedelta` for `L+tf` gap math | Existing helper, signature `to_timedelta(timeframe: str) -> timedelta` [VERIFIED: time_parser.py:46] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `functools.partial` | stdlib | Bind `(symbol,tf)` sink if NOT extending `ClosedBar` | Only the fallback path for Open Question Q2 |
| `threading.Lock` | stdlib | Defensive guard on `update()` | ONLY if the single-writer-thread invariant cannot be guaranteed (§Thread hand-off) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `deque(maxlen)` ring | pandas rolling frame | Rejected — pandas per-append is the v1.5 hot-path cost the whole feed was optimized away from; deque is O(1) |
| Extend `ClosedBar` | `functools.partial(feed.update, symbol, tf)` per-provider sink | Partial contradicts D-01 ("not `update(symbol, tf, bar)`"); extend-dict aligns with D-01 intent |

**Installation:** None — all stdlib or existing dependencies. No `npm/pip install` step.

## Package Legitimacy Audit

**No external packages are added by this phase.** `LiveBarFeed` is built entirely from the Python
standard library (`collections.deque`, `queue`, `threading`, `datetime`) plus already-installed,
already-audited project dependencies (`msgspec`, `pandas`, `aiohttp` via the Phase-2 provider). The
slopcheck / registry-verification gate is therefore **N/A** — there is nothing new to verify. Any
plan task that proposes a new third-party package should be treated as out-of-scope drift and must
run the full legitimacy gate before adoption.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────── connector asyncio thread ───────────────────┐
 OKX /business WS ──────► │ OkxDataProvider._stream_candles                                 │
 (candle rows, confirm)   │   └─ _process_row: gate confirm=="1", to_money() Decimal edge   │
                          │        └─ _hand_closed_bar(ClosedBar) ──► self._bar_sink(...)    │
                          │                                             │ (== feed.update)   │
                          │                                             ▼                    │
                          │  LiveBarFeed.update(closed_bar):                                 │
                          │    1. resolve (symbol, tf)  [needs Q1 fix]                       │
                          │    2. monotonic guard vs L[(sym,tf)]:                            │
                          │         t==L+tf  deliver ─┐                                      │
                          │         t> L+tf  GAP ─► fetch_ohlcv_backfill([L+tf..t-tf])       │
                          │                          └─ replay each ──► update() (recursion) │
                          │         t==L same duplicate→drop                                 │
                          │         t==L diff revision→WARN+drop (no mutation)               │
                          │         t< L   stale→reject+log                                  │
                          │    3. Bar(ts→tz-aware Timestamp, Decimal OHLCV)                  │
                          │    4. ring[(sym,tf)].append(bar); _newest_bars[sym]=bar          │
                          │    5. L[(sym,tf)] = t                                            │
                          │    6. global_queue.put(BarEvent(time=t, bars={sym: bar}))  ──────┼──┐
                          └─────────────────────────────────────────────────────────────────┘  │
                                                                                                │ queue.Queue
   ┌──────────────────── engine daemon thread (single writer of portfolio state, D-19) ────────┘  (MPSC-safe)
   │ LiveTradingSystem._event_processing_loop: get() ─► EventHandler._dispatch
   │   BAR route (order preserved, FEED-05):
   │     1. portfolio_handler.update_portfolios_market_value  (mark-to-market)
   │     2. execution_handler.on_market_data                  (resting-order match → FillEvent)
   │     3. strategies_handler.calculate_signals              (indicators self-buffer; → SignalEvent)
   │   TIME route: DORMANT on live path (D-05) — reserved for Phase-6 poll cadence
   └────────────────────────────────────────────────────────────────────────────────────────────

  Warmup (at start, BEFORE live subscription): fetch_ohlcv_backfill(K bars) ─► replay each via update()
  Higher-tf (D-11): strategy calls feed.window(ticker, tf) ─► resample from ring[(sym, base_tf)]
```

### The 7-rule bar-timing contract (`LiveBarFeed` MUST honor — quoted verbatim from `bar_feed.py`)

The look-ahead contract is the single written home of look-ahead safety and lives **in the feed
only** (never in strategies, M5-01). `LiveBarFeed.window()` must enforce the same rule 4 cutoff.

1. **Bars are stamped by open time** (D-04). Bar stamped `T` covers `[T, T+tf_base)`.
2. **Tick at `T` means "the bar stamped `T` just closed."** Wall-clock is `T+tf_base`, labeled `T`.
3. **Decision visibility at tick `T`:** all base bars stamped `<= T`.
4. **Resampled visibility at tick `T`:** bucket `B` (`label='left', closed='left'`) visible iff
   `B + TF <= T + tf_base`, i.e. `B <= T - TF + tf_base`. Forming bucket INVISIBLE.
5. **Fills land at the next open** (`FillEvent.time = T + tf_base`).
6. **Equity at tick `T`** = cash + positions at the close of the bar stamped `T`.
7. **Last-bar edge:** orders on the final tick never fill (no next bar).

For live: a closed bar with `confirm==1` stamped `ts` (open-time) IS "the bar stamped `T` just
closed" (rule 2). The `confirm` gate is exactly what makes rules 1–2 hold without wall-clock
inference (LX-08).

### Pattern 1: `LiveBarFeed(BarFeed)` — implement the 4 abstract members

The ABC (`price_handler/feed/base.py`) requires these abstract methods; `LiveBarFeed` must
implement all four (the ring provides the data):

```python
# Source: itrader/price_handler/feed/base.py (verified signatures)
@abstractmethod
def newest_bar(self, ticker: str) -> Bar | None: ...
@abstractmethod
def current_bars(self, time: datetime) -> dict[str, Bar]: ...
@abstractmethod
def window(self, ticker: str, timeframe: timedelta, max_window: int, asof: datetime) -> pd.DataFrame: ...
@abstractmethod
def megaframe(self, asof: datetime, timeframe: timedelta, max_window: int) -> pd.DataFrame: ...
```

Non-abstract inherited (do NOT re-declare): `register_raw_bar_consumer`, `cache_capacity`,
`_raw_bar_consumers` (ABC-shared lazy storage). `LiveBarFeed` gets `cache_capacity()` for free.

- `newest_bar(ticker)` → `self._newest_bars.get(ticker)` (written by `update()`, mirrors G5).
- `current_bars(time)` → dict of bars stamped exactly `time` from the ring (mostly for the
  dormant TIME/`generate_bar_event` path; live uses direct emission).
- `window(...)` → resample from the ring per D-11 (mirror `bar_feed.py::window` rule-4 cutoff).
  For golden SMA_MACD (1d==base, N=1) this is **not exercised** (indicators self-buffer, the
  per-tick `feed.window()` slice was removed in v1.5 — verified `strategies_handler.py:131,269`),
  so a correct-but-simple implementation suffices for the gate.

### Pattern 2: The monotonic guard (FEED-04, the core novel logic)

```python
# Design — drives the D-06 taxonomy off last-delivered L per (symbol, timeframe)
def update(self, closed_bar: ClosedBar) -> None:
    sym, tf_str = closed_bar["symbol"], closed_bar["timeframe"]   # requires Q1 fix
    tf = to_timedelta(tf_str)
    t = pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")        # tz-aware (Pitfall 2)
    L = self._last_delivered.get((sym, tf_str))
    if L is not None:
        if t < L:                          return self._reject_stale(sym, t, L)
        if t == L:
            return self._drop_duplicate_or_warn_revision(sym, t, closed_bar)  # value-compare
        if t > L + tf:                     self._backfill_gap(sym, tf_str, L + tf, t - tf)  # replay via update()
    bar = self._build_bar(t, closed_bar)   # Decimal already crossed at provider edge
    self._ring[(sym, tf_str)].append(bar)
    self._newest_bars[sym] = bar
    self._last_delivered[(sym, tf_str)] = t
    self.global_queue.put(BarEvent(time=t, bars={sym: bar}))       # D-02/D-04 single-ticker
```

**When to use:** every incoming closed bar AND every replayed warmup/backfill bar (FEED-03 — one
path). The gap branch calls `fetch_ohlcv_backfill` then replays each returned `ClosedBar` through
`update()` recursively; the recursion terminates because each replayed bar advances `L` by exactly
one `tf` (no further gap on the replay).

### Pattern 3: Warmup at startup (FEED-03, no bulk fast-path)

Fetch `K` bars via `fetch_ohlcv_backfill`, replay each through `update()` **before** the live
subscription starts, so all `update()` calls are single-threaded and the indicators are settled on
the first live bar. `K` must be `≥ max strategy warmup` (see Open Question Q1).

### Anti-Patterns to Avoid
- **Bulk `warmup_from(series)` fast-path** — explicitly out of scope (LX-09, REQUIREMENTS "Out of
  Scope"): a second state-building path diverges and re-opens the parity audit. Replay one-by-one.
- **Wall-clock bar `time`** — use the venue `ts` only (LX-08, determinism). Never `datetime.now()`.
- **`Decimal(float)`** — the provider already crossed the Decimal edge via `to_money(str(...))`;
  `ClosedBar` fields are already `Decimal`. Do NOT re-cast through float.
- **Concurrent `update()` from two threads** — keep all `update()` on the connector asyncio thread
  (see Thread hand-off); a two-writer ring/guard races.
- **Re-warming indicators on a revision** (D-07 rejects it) — forward-only WARN+drop.
- **Importing `LiveBarFeed`/connector code on the backtest hot path** — breaks the inertness gate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bounded ring | Custom list + manual eviction | `collections.deque(maxlen=n)` | O(1) append + auto-evict, FEED-01 mandates it |
| Cache capacity sizing | Hand-set ring size | `cache_capacity()` / `cache_registration.derive` | D-09 "never hand-set"; single source of truth vs backtest |
| Cross-thread emission | Locks + condition vars | `queue.Queue.put` (existing `global_queue`) | MPSC-safe already; adding locks reintroduces D-19 risk |
| `Bar` construction | New dataclass | `itrader.core.bar.Bar` (msgspec Struct) | Already the `BarEvent.bars` type; Decimal string path |
| tf string → duration | Regex parsing | `outils.time_parser.to_timedelta` | Existing, tested helper |
| Confirm gating | Re-check `confirm` in feed | Provider already gates `confirm=="1"` | Phase-2 done; feed receives only closed bars |
| REST pagination for backfill | Loop over `fetch_ohlcv` | `provider.fetch_ohlcv_backfill(...)` | Already paginates + Decimal-crosses [VERIFIED: okx_provider.py:245] |

**Key insight:** almost every hard part (confirm gate, Decimal edge, REST pagination, the ABC, the
7-rule contract, the `Bar` type, capacity derivation) is already built. Phase 3's genuine new code
is the ~80-line monotonic guard + the wiring swap. Resist rebuilding the provider's work.

## Provider→Feed Seam (verified signatures — build against these)

From `itrader/price_handler/providers/okx_provider.py`:

```python
# ClosedBar — NOTE: NO symbol/timeframe fields (Open Question Q1)
class ClosedBar(TypedDict):
    ts: int          # venue bar-OPEN timestamp, milliseconds (business time, verbatim)
    open: Decimal    # already crossed Decimal edge via to_money(str(...))
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

def set_bar_sink(self, sink: Callable[[ClosedBar], None]) -> None: ...   # register feed.update
def fetch_ohlcv_backfill(self, symbol: str, timeframe: str,
                         since: int | None = None, limit: int = 1000) -> list[ClosedBar]: ...
def start_stream(self) -> Any: ...   # spawns candle loop on connector.spawn
```

Provider is constructed **per `(symbol, timeframe)`**: `OkxDataProvider(connector, symbol='BTC/USDT',
timeframe='1d')` (verified `live_trading_system.py:253`). It knows its symbol+tf but does **not**
stamp them into `ClosedBar`.

## Component / Wiring Map (composition root)

`itrader/trading_system/live_trading_system.py` — the swap-in points:
- **Line 106:** `self.feed = BacktestBarFeed(self.store, to_timedelta('1d'))` — the placeholder to
  replace with `LiveBarFeed`.
- **Lines 178–203:** `feed` injected into `StrategiesHandler`, `ScreenersHandler`, and
  `EventHandler(..., self.feed.generate_bar_event, ...)`. Under D-03 live emits directly, so the
  `generate_bar_event` TIME-route source becomes dormant (D-05) but must still be a valid callable
  (the route literal expects a callable; keep a no-op-safe binding or the inherited method).
- **Lines 234–255 (`if self.exchange == 'okx'`):** where `self._okx_data_provider` is constructed.
  The plan adds `self._okx_data_provider.set_bar_sink(self.feed.update)` here (or in
  `_initialize_live_session`), and runs startup warmup, then `start_stream()` in `start()`.
- **Line 376 (`_initialize_live_session`):** `self.feed.bind(self.global_queue, universe.members)` —
  `LiveBarFeed` needs a compatible `bind`/queue-injection so `update()` can `global_queue.put`.

`TimeGenerator` (`simulation/time_generator.py`): a `SimulationEngine` that `__iter__`s
`TimeEvent`s over a pinned date grid. In backtest, `backtest_runner._run_backtest` loops
`for time_event in engine.time_generator: global_queue.put(time_event)`. **FEED-05 replaces exactly
this driver loop**: live has no date grid; the socket's closed-bar arrival is the driver, and
`update()` puts `BarEvent`s directly. The live `_event_processing_loop` already drains the queue on
a daemon thread — no `TimeGenerator` is wired live (it was never instantiated in
`LiveTradingSystem`).

## Thread hand-off (D-02 / D-19) — minimal safe form

**Verified topology:** `OkxConnector` runs its own asyncio loop on a daemon thread
(`run_coroutine_threadsafe` / `call_soon_threadsafe`, verified `connectors/okx.py:103–169`). The
candle stream (`_stream_candles`) runs on that loop; `_process_row` → `_hand_closed_bar` →
`self._bar_sink(closed)` calls **synchronously on the asyncio thread**. So `feed.update()` executes
on the connector asyncio thread. The engine drains `global_queue` on a **separate** daemon thread
(`_event_processing_loop`).

**Recommendation (no extra locking needed):**
- Keep ALL `update()` invocations on the single connector asyncio thread: (a) startup warmup replay
  runs before `start_stream()` activates the socket, or is scheduled onto the same loop; (b) D-08
  reconnect backfill is triggered inside the stream loop on resume (same thread). Then the feed's
  ring + `L`-guard + `_newest_bars` have exactly **one writer** → no `threading.Lock` required.
- The only cross-thread handoff is `global_queue.put(BarEvent)`, which is `queue.Queue`-safe (MPSC).
- **D-19 preserved:** portfolio state mutates only on the engine thread (via `on_fill` / BAR-route
  handlers dispatched from `_event_processing_loop`); the asyncio thread only enqueues.
- **Fallback:** if warmup must run on the engine/main thread while the socket is already live, wrap
  `update()`'s guard+ring mutation in a `threading.Lock`. Prefer the single-thread invariant — it is
  simpler and lock-free. `[ASSUMED]` — verify at plan time that startup ordering (warmup → then
  subscribe) is achievable given `start()` / `start_stream()` sequencing.

## Runtime State Inventory

> This is a greenfield feature (new `LiveBarFeed` class), not a rename/refactor — but it introduces
> live runtime state worth cataloguing for Phases 4–5.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the ring is in-memory, ephemeral per run. `_newest_bars`, `_ring`, `_last_delivered` are process-local. | None |
| Live service config | OKX `(symbol, timeframe)` subscription is wiring config (`live_trading_system.py:253` defaults `BTC/USDT`/`1d`) — lives in code, not a UI. | Plan: make subscription config explicit (finest-tf per D-11) |
| OS-registered state | None — no OS scheduler/service registration. | None |
| Secrets/env vars | None new — OKX creds are the Phase-2 connector's concern (`OKX_API_*`). Feed reads no secrets. | None |
| Build artifacts | None — no package rename, no egg-info impact. | None |

## Common Pitfalls

### Pitfall 1: Ring sized to `cache_capacity()==1` starves indicator warmup
**What goes wrong:** `deque(maxlen=1)` + fetching `K=1+margin` warmup bars → SMA_MACD indicators
(min_period=100) never reach `is_ready` → `calculate_signals` short-circuits → zero trades → oracle
NOT byte-exact (or would require 100 live days to warm).
**Why it happens:** `cache_capacity()` returns `NEWEST_BAR_ONLY=1` because no `RawBarConsumer` is
registered (indicators self-buffer under Model B, so they never register). [VERIFIED: cache_registration.py:42,137; base.py:118-125]
**How to avoid:** register a raw-bar consumer with `required_history_depth = max strategy warmup`
(=100) on the live feed at wiring, so `cache_capacity()` derives to 100. Then ring `maxlen=100`
(D-09) and warmup `K=100+margin` (D-10) are both correct. See Open Question Q1.
**Warning signs:** live-paper run produces 0 signals; `is_ready(ticker)` stays False after warmup.

### Pitfall 2: tz-naive bar `time` breaks `window()` / `searchsorted`
**What goes wrong:** `window()` raises `ValueError("asof must be tz-aware")` or silently returns the
wrong slice; comparisons against the tz-aware index throw under `filterwarnings=["error"]`.
**Why it happens:** `ClosedBar["ts"]` is an int ms; naïve `datetime.fromtimestamp(ts/1000)` is
tz-naive. The backtest index and `window()` cutoff are tz-aware (verified `bar_feed.py:616`).
**How to avoid:** `pd.Timestamp(ts, unit="ms", tz="UTC")` for both `Bar.time` and `BarEvent.time`.
Match the tz-aware `pd.Timestamp` type the backtest carries.
**Warning signs:** `TypeError: Cannot compare tz-naive and tz-aware`; `ValueError` from `window()`.

### Pitfall 3: `ClosedBar` has no `symbol`/`timeframe` → `update()` can't route
**What goes wrong:** `update(closed_bar)` cannot key the ring/guard by `(symbol, timeframe)`; a
multi-symbol future (Phase 6) mis-routes bars silently.
**Why it happens:** the TypedDict carries only OHLCV+ts (verified). D-01 assumes routing keys are
present — they are not.
**How to avoid:** extend `ClosedBar` with `symbol` + `timeframe` in the provider (co-shape the
Phase-2 seam). See Open Question Q1.
**Warning signs:** `KeyError`/`TypeError` in `update()`; single-symbol works but design can't extend.

### Pitfall 4: `filterwarnings=["error"]` + async teardown
**What goes wrong:** an unclosed aiohttp session or un-cancelled task raises `ResourceWarning` →
strict-suite failure. Also any pandas resample `FutureWarning` fails.
**Why it happens:** the global filter promotes every warning to an error; the provider tests already
manage this (finite message sequence, teardown-safe fake).
**How to avoid:** unit-test `LiveBarFeed` **without a real socket** — drive `update()` with synthetic
`ClosedBar` dicts and a stub queue (no aiohttp). Use `_offset_alias`'s canonical aliases (`'D'`,
`'min'`, `'h'`) in `window()` — never the legacy `time_parser` string that produces month-end.
**Warning signs:** `ResourceWarning`, `FutureWarning` surfacing as test errors.

### Pitfall 5: Backfill boundary-bar duplication
**What goes wrong:** REST backfill re-returns the boundary bar already delivered → double-delivery.
**Why it happens:** `fetch_ohlcv` windows overlap at boundaries.
**How to avoid:** the monotonic guard's **duplicate** branch (D-06) drops it; `fetch_ohlcv_backfill`
already advances `since` past the last bar (verified `okx_provider.py:269`). The D-10 safety margin
also absorbs boundary dedup. Compose backfill+resume so a re-sent bar hits the duplicate branch.
**Warning signs:** two `BarEvent`s with identical `time`.

## Code Examples

### Building a `Bar` from a `ClosedBar` (Decimal already crossed)
```python
# Source: itrader/core/bar.py (Bar is a frozen msgspec.Struct, Decimal OHLCV)
from itrader.core.bar import Bar
import pandas as pd

def _build_bar(self, t: pd.Timestamp, cb: ClosedBar) -> Bar:
    # cb OHLCV are ALREADY Decimal (provider crossed via to_money) — do NOT re-cast through float
    return Bar(time=t, open=cb["open"], high=cb["high"], low=cb["low"],
               close=cb["close"], volume=cb["volume"])
```

### Warmup replay (FEED-03 one-by-one, no bulk fast-path)
```python
# Source: pattern derived from okx_provider.fetch_ohlcv_backfill + D-06 replay rule
def warmup(self, symbol: str, timeframe: str, depth: int) -> None:
    bars = self._provider.fetch_ohlcv_backfill(symbol, timeframe, limit=depth)  # list[ClosedBar]
    for cb in bars:                 # replay THROUGH the same update() path (LX-09)
        self.update(cb)             # each advances L by one tf → no spurious gap
```

### Inertness gate (recurring milestone gate — mirror the Phase-2 test)
```python
# Source: tests/integration/test_okx_inertness.py (subprocess clean-interpreter probe)
_PROBE = r"""
import sys
import itrader.trading_system.backtest_trading_system  # the hot path
_FORBIDDEN = ("itrader.price_handler.feed.live_bar_feed", "itrader.connectors.okx", "ccxt.pro", "ccxt")
leaked = [n for n in _FORBIDDEN if n in sys.modules]
assert not leaked, f"backtest path leaked live modules: {leaked}"
"""
# subprocess.run([sys.executable, "-c", _PROBE]) — LiveBarFeed must be lazy-imported in
# LiveTradingSystem.__init__ only, never on the backtest import graph.
```

## Warmup safety-margin survey (D-10 discretion)

How production frameworks size warmup beyond raw indicator lookback:

- **Nautilus Trader:** requests exactly the indicator's declared warmup length via
  `request_bars(... limit=N)`; robustness comes from `indicator.initialized` gating, not a fixed
  over-fetch. `[ASSUMED]` (training knowledge; not re-verified this session).
- **LEAN (QuantConnect):** `SetWarmUp(period)` / `WarmUpIndicator` — the engine feeds history until
  every indicator `IsReady`; users commonly add a small buffer (a few bars) for safety. `[ASSUMED]`
- **backtrader:** auto-computes `minperiod` from indicators and adds no fixed margin; the
  "prenext/next" mechanism gates until minperiod is reached. `[ASSUMED]`

**Recommendation for D-10:** a small **fixed additive margin** (`K = required_warmup + 5`) rather
than a multiplier. Rationale: (a) the driver is a *readiness threshold* (indicators become ready at
exactly `min_period` bars), not a variance-sensitive quantity, so a multiplier over-fetches with no
benefit; (b) +5 covers REST boundary-bar dedup (Pitfall 5) and one-off off-by-one gaps; (c) it is
deterministic and cheap on a 1d timeframe. `required_warmup` = `max(strategy.warmup for strategy in
strategies)` = 100 for SMA_MACD (verified: `max(SMA→100, MACDHist→15)`, `SMA_MACD_strategy.py:34-36`).
Confidence: MEDIUM (the +5 value is a judgment call; the *additive-not-multiplier* shape is
well-grounded).

## LX-15 Runtime Topology (RUN-01) — Phase 3→4 Handoff flag

**This is a Phase-4 decision, NOT Phase-3 build scope** — surfaced here per the CONTEXT Handoff
note. REQUIREMENTS RUN-01 already records the locked intent: **ship option (b) — a separate worker
process — architected as (c) with N=1, using Postgres `LISTEN/NOTIFY` as the default command/status
channel** (zero new dependency, reuses the v1.6 store). The spec (LX-15) frames the options:

| Option | Shape | Verdict |
|--------|-------|---------|
| (a) In-process | Engine on a thread inside FastAPI | Rejected — couples web+connector+engine lifecycles; one crash kills both |
| (b) Separate worker | Engine as its own service; FastAPI controls lifecycle via Postgres store + `LISTEN/NOTIFY` | **Ship this** (RUN-01) — crash isolation, thin FastAPI, reuses v1.6 durable store |
| (c) Process-per-portfolio | One engine process per portfolio (1 acct:1 pf) + shared price-feed service | Architect toward (with N=1) |

**Phase-3 obligation:** none beyond keeping the feed cleanly separable — `LiveBarFeed` emits onto
`global_queue` and holds only in-memory state, so it slots into a worker process unchanged. Do NOT
build the topology in Phase 3. Confidence: HIGH (decision is already locked in REQUIREMENTS RUN-01).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `TimeGenerator` for-loop drives ticks (backtest) | Socket closed-bar arrival drives ticks (live, D-03) | This phase (FEED-05) | Live is event-sourced, not clock-iterated |
| ccxt unified `watch_ohlcv` (drops `confirm`) | OKX native `/business` channel (carries `confirm`) | Phase 2 | Bar-close is venue-driven, not wall-clock inferred (LX-08) |
| Per-tick `feed.window()` slice in strategies | Model B stateful indicators self-buffer | v1.5 Phase 5 | Golden SMA_MACD never calls `window()` on the hot path → ring depth-1 suffices for the gate |

**Deprecated/outdated:**
- `binance_stream.py` — quarantined legacy streamer (informative only for the `_closed==5` burst
  reality behind D-04; NOT on any run path, do not import).
- Bulk `warmup_from(series)` — explicitly out of scope (LX-09).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Startup warmup can run before `start_stream()` activates the socket, keeping `update()` single-threaded | Thread hand-off | If not, need a `threading.Lock` on `update()` (still safe, slightly slower) |
| A2 | Nautilus/LEAN/backtrader warmup-margin conventions (additive, readiness-gated) | Warmup survey | Low — only informs the margin *shape*; +5 is conservative regardless |
| A3 | Registering a `RawBarConsumer(depth=max_warmup)` on the LIVE feed is oracle-dark (backtest precomputes full frames, never reads `cache_capacity`) | Pitfall 1 / Q1 | If backtest shared the same feed instance it'd change nothing (backtest ignores capacity), but verify wiring is live-only |
| A4 | Golden SMA_MACD is single-symbol 1d, so `window()`/D-11 pull-resample is not exercised by the gate | Pattern 1 | If a multi-tf golden is added later, `window()` correctness becomes gate-critical |

## Open Questions (RESOLVED)

1. **Where does the warmup/ring depth come from, given `cache_capacity()==1`?** (HIGHEST PRIORITY)
   > **RESOLVED — D-13:** register a `RawBarConsumer(required_history_depth = max(strategy.warmup))`
   > on the LIVE feed at wiring (03-04 Task 1), so `cache_capacity()` derives to 100. Recommendation (a) adopted.
   - What we know: `cache_capacity()` returns `NEWEST_BAR_ONLY=1` (no raw-bar consumers; indicators
     self-buffer). SMA_MACD needs `warmup=100` bars replayed to be ready. D-09 ties ring `maxlen` to
     `cache_capacity()`; D-10 ties `K` to `cache_capacity()+margin`. Literal reading → fetch ~1 bar
     → zero trades.
   - What's unclear: whether to (a) register a `RawBarConsumer(required_history_depth=max_warmup)`
     on the live feed so `cache_capacity()` derives to 100 (makes D-09+D-10 self-consistent), or
     (b) source `K` from `max(strategy.warmup)` independently while keeping ring depth-1 (indicators
     stream through — depth-1 works for warmup since they self-buffer; but D-11 higher-tf pull-
     resample would then fail for a future multi-tf strategy).
   - Recommendation: **(a)** — register a raw-bar consumer sized to `max(strategy.warmup)` on the
     LIVE feed at wiring. It reconciles D-09 and D-10 with their literal wording, sizes the ring for
     D-11 pull-resample, and is oracle-dark (A3). The +5 margin (D-10) rides on top.

2. **Extend `ClosedBar` with `symbol`/`timeframe`, or bind a per-provider sink?**
   > **RESOLVED — D-12:** extend `ClosedBar` with `symbol: str` + `timeframe: str` routing keys
   > (03-01); `LiveBarFeed.update()` keys the ring/guard off them. Recommendation adopted.
   - What we know: `ClosedBar` has no routing keys; the provider is per-`(symbol,tf)`; D-01 rejects
     `update(symbol, tf, bar)`.
   - What's unclear: whether Phase-2's `ClosedBar` may be edited (it is a Phase-2 artifact, but the
     provider docstring explicitly says "Phase 3 co-shapes this seam").
   - Recommendation: **extend `ClosedBar`** with `symbol: str` + `timeframe: str` (stamp in
     `_process_row` and `fetch_ohlcv_backfill` — the provider knows both). Aligns with D-01 intent;
     a 3-line provider edit. Confirm with the user that touching the Phase-2 TypedDict is acceptable.

3. **What binding does `LiveBarFeed` need for `global_queue`?**
   > **RESOLVED — 03-02 `<interfaces>`:** mirror `BacktestBarFeed.bind(queue, membership)` (sets
   > `self.global_queue`); `update()` puts onto it. Pinned in the 03-02 interfaces block.

   `BacktestBarFeed.bind(queue,
   membership)` sets `self.global_queue`. `LiveBarFeed.update()` needs the queue to `put`. Mirror
   `bind` (or take the queue in `__init__`). Minor — plan-time detail.

## Environment Availability

> The Phase-3 build and its gate run entirely offline (synthetic `ClosedBar` sequences + the golden
> CSV). A live OKX socket is NOT required to complete or verify Phase 3.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | all | ✓ | 3.13.1 | — |
| `collections.deque`, `queue`, `threading` | ring/emit/guard | ✓ | stdlib | — |
| `pandas` | tz-aware `Timestamp`, `window()` resample | ✓ | ^2.3.3 | — |
| `msgspec` (`Bar`) | bar value object | ✓ | existing dep | — |
| `pytest-asyncio` | provider/async test infra (if any) | ✓ | ^1.4.0 (`asyncio_mode="auto"`) | — |
| OKX live socket | live-paper *end-to-end* (Phase 4, not Phase 3) | ✗ (creds not needed for gate) | — | Synthetic `ClosedBar` unit tests + golden-CSV replay |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** live OKX socket — Phase 3 is fully testable via synthetic
`ClosedBar` sequences; the real socket is exercised only in Phases 4–5.

## Validation Architecture

> `workflow.nyquist_validation` is not disabled — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (+ pytest-asyncio ^1.4.0, `asyncio_mode="auto"`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/price/test_live_bar_feed.py -x` (new file) |
| Full suite command | `make test` (main checkout) / `poetry run pytest tests` (worktree — see memory: make test aborts in worktrees on missing `.env`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FEED-01 | ring is `deque(maxlen=cache_capacity())` per `(sym,tf)`; oldest evicts | unit | `pytest tests/unit/price/test_live_bar_feed.py -k ring -x` | ❌ Wave 0 |
| FEED-02 | `BarEvent` emitted with tz-aware venue-open `time`; only on delivered bar | unit | `pytest ... -k emit_time -x` | ❌ Wave 0 |
| FEED-02 | 7-rule `window()` cutoff — completed-bars-only visibility | unit | `pytest ... -k window_lookahead -x` | ❌ Wave 0 |
| FEED-03 | warmup replays K bars one-by-one via `update()`, indicators ready | integration | `pytest tests/integration/... -k warmup_replay -x` | ❌ Wave 0 |
| FEED-04 | in-sequence deliver | unit | `pytest ... -k in_sequence -x` | ❌ Wave 0 |
| FEED-04 | gap → backfill-and-replay (stub `fetch_ohlcv_backfill`), then deliver `t` | unit | `pytest ... -k gap_backfill -x` | ❌ Wave 0 |
| FEED-04 | duplicate (`t==L`, same values) → dropped, no emit | unit | `pytest ... -k duplicate_drop -x` | ❌ Wave 0 |
| FEED-04 | revision (`t==L`, diff values) → WARN + drop, no state mutation | unit | `pytest ... -k revision_forward_only -x` | ❌ Wave 0 |
| FEED-04 | stale (`t<L`) → reject + log, no emit | unit | `pytest ... -k stale_reject -x` | ❌ Wave 0 |
| FEED-04 | reconnect boundary → proactive backfill; re-sent bar hits duplicate branch | unit | `pytest ... -k reconnect_boundary -x` | ❌ Wave 0 |
| FEED-05 | direct BAR emission replaces TimeGenerator; TIME-before-BAR ordering preserved downstream | integration | `pytest tests/integration/... -k live_bar_route_order -x` | ❌ Wave 0 |
| GATE | oracle byte-exact (134 / `46189.87730727451`) after LiveBarFeed lands | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| GATE | LiveBarFeed inert on backtest import path (no W1/W2 regression) | integration | `poetry run pytest tests/integration/test_*inertness* -x` (add LiveBarFeed to `_FORBIDDEN`) | ✅ pattern exists |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/price/test_live_bar_feed.py -x`
- **Per wave merge:** `poetry run pytest tests` (or `make test` in main checkout)
- **Phase gate:** full suite green + oracle byte-exact + inertness probe green before `/gsd:verify-work`

### How to test deterministically without a live socket
Drive `update()` directly with synthetic `ClosedBar` dicts and a fake/real `queue.Queue`; assert on
the emitted `BarEvent` sequence. For the gap branch, inject a stub provider whose
`fetch_ohlcv_backfill` returns a fixed `list[ClosedBar]`. No aiohttp, no asyncio loop, no wall-clock
— every `ts` is a fixed epoch-ms literal, so runs are byte-reproducible. This mirrors the Phase-2
provider test's offline discipline (`tests/unit/connectors/test_okx_data_provider.py`).

### Proving the recurring milestone gate
1. **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` must stay 134 /
   `46189.87730727451` — LiveBarFeed must not touch the backtest path.
2. **Inertness:** extend the subprocess `_FORBIDDEN` probe (pattern in
   `tests/integration/test_okx_inertness.py`) to assert the `live_bar_feed` module is NOT pulled by
   `import itrader.trading_system.backtest_trading_system`. Keep `LiveBarFeed` lazy-imported inside
   `LiveTradingSystem.__init__` (like the OKX stack).
3. **W1/W2:** unchanged by construction (no new module on the hot path). No new benchmark needed;
   the inertness probe is the proxy.

### Wave 0 Gaps
- [ ] `tests/unit/price/test_live_bar_feed.py` — the FEED-01/02/04 unit matrix (synthetic `ClosedBar`)
- [ ] `tests/integration/test_live_bar_feed_warmup.py` — FEED-03 warmup replay + indicator readiness
- [ ] `tests/integration/test_live_bar_feed_route_order.py` — FEED-05 BAR-route ordering
- [ ] Extend an inertness probe to include the `live_bar_feed` module
- [ ] Shared fixture: a `_StubProvider` with programmable `fetch_ohlcv_backfill` + a captured queue

## Security Domain

> `security_enforcement` not disabled — section included, but scope is minimal for this phase.

`LiveBarFeed` handles no credentials, no user input, no network directly (the socket + auth live in
the Phase-2 connector/provider). The security surface is **data-integrity**, not
auth/crypto/injection.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | OKX auth is the connector's concern (Phase 2) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Malformed-row rejection is the provider's (`_MIN_ROW_FIELDS`); the feed validates monotonicity (D-06 taxonomy) — treat every incoming `ClosedBar` as untrusted venue data |
| V6 Cryptography | no | never hand-roll — none here |

### Known Threat Patterns for the live feed
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Forming-bar leak (delivering `confirm==0`) | Tampering / Info-disclosure (look-ahead) | Provider gates `confirm=="1"`; feed only ever sees closed bars (LX-08) |
| Out-of-order / replayed bar corrupts indicator state | Tampering | Monotonic guard: stale reject, duplicate drop, revision forward-only (D-06/D-07) |
| Wall-clock bar time (non-deterministic) | Tampering (determinism) | Use venue `ts` only; never `datetime.now()` (LX-08) |
| Silent bar drop (unrouted event) | Repudiation | `EventHandler._dispatch` raises `NotImplementedError` on unrouted types; feed logs stale/revision |
| Live-vs-demo host misroute (upstream) | Info-disclosure | Provider hosts off the single `sandbox` bool (Phase-2 CONN-03) — not a Phase-3 concern but preserved |

## Sources

### Primary (HIGH confidence — read this session)
- `itrader/price_handler/providers/okx_provider.py` — `ClosedBar`, `set_bar_sink`, `fetch_ohlcv_backfill`
- `itrader/price_handler/feed/base.py` — `BarFeed` ABC (all abstract members, `cache_capacity`, `register_raw_bar_consumer`)
- `itrader/price_handler/feed/bar_feed.py` — `BacktestBarFeed`: 7-rule contract, `window`, `current_bars`, `newest_bar`, `generate_bar_event`
- `itrader/price_handler/feed/cache_registration.py` — `derive`, `NEWEST_BAR_ONLY=1`, `RawBarConsumer`
- `itrader/events_handler/events/market.py` — `TimeEvent`, `BarEvent(time, bars: dict[str,Bar])` (no tf field)
- `itrader/core/bar.py` — `Bar` msgspec Struct (Decimal OHLCV, no tf field)
- `itrader/events_handler/full_event_handler.py` — `_routes` TIME/BAR literal (D-02/D-05 ordering)
- `itrader/trading_system/live_trading_system.py` — composition root (feed placeholder line 106; OKX wiring 234-255; bind line 376)
- `itrader/trading_system/simulation/time_generator.py` + `backtest_runner.py`/`compose.py` — `TimeGenerator` role (FEED-05)
- `itrader/connectors/base.py` + `connectors/okx.py` — `LiveConnector` Protocol, asyncio-thread `call`/`spawn`
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` + `base.py` — warmup=100 derivation (min_period)
- `tests/integration/test_okx_inertness.py`, `tests/unit/connectors/test_okx_data_provider.py` — gate + offline-test patterns
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LX-15 topology
- `.planning/{ROADMAP,REQUIREMENTS}.md`, `03-CONTEXT.md`

### Secondary (MEDIUM confidence)
- Warmup-margin shape (additive vs multiplier) — reasoned from readiness-threshold semantics

### Tertiary (LOW confidence — flagged `[ASSUMED]`)
- Nautilus/LEAN/backtrader specific warmup-margin conventions (training knowledge, not re-verified)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib/existing; every seam signature read this session
- Architecture: HIGH — 7-rule contract quoted from source; monotonic guard grounded in D-06 + real types
- Pitfalls: HIGH — Pitfalls 1 & 3 are verified code-vs-decision gaps, not speculation
- Warmup margin (D-10 exact value): MEDIUM — shape grounded, exact +5 is a judgment call
- Framework warmup conventions: LOW — `[ASSUMED]`

**Research date:** 2026-07-01
**Valid until:** 2026-07-31 (stable internal code; the two open questions should be resolved at plan time)
```

