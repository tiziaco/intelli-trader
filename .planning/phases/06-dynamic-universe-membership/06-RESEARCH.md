# Phase 6: Dynamic Universe Membership - Research

**Researched:** 2026-07-06
**Domain:** Live universe membership poll seam + OKX dynamic candle subscribe/unsubscribe (event-driven, queue-only)
**Confidence:** HIGH (all findings verified against the actual source files named in CONTEXT.md; no new external packages)

## Summary

This phase has **zero new external dependencies** — it is pure in-repo wiring across five
already-built subsystems: `Universe`/`derive_membership` (the membership owner), the msgspec
`Event`/`_routes` contract (the event seam), `LiveBarFeed.warmup` (the warmup-on-add machinery,
already built in Phase 3), `OkxDataProvider`/`OkxConnector` (the live candle socket + asyncio
loop), and `OkxExchange.validate_symbol` (the venue markets-map guard). Every deferred plan-time
gap in CONTEXT.md (D-01..D-06) maps to a concrete, code-grounded answer below.

The single hardest gap is **D-05's dynamic subscribe/unsubscribe coroutine lifecycle**: today
`OkxDataProvider` streams exactly one wiring-time symbol via one supervised coroutine
(`start_stream` → `_stream_candles` → `_run_stream_supervisor`), and the connector's `spawn`
tracks stream tasks in one flat `_stream_tasks` set with no per-symbol handle map. The provider
must grow a **subscription registry `{symbol: asyncio.Task}`** and a per-symbol supervisor spawn,
plus a `cancel`-based unsubscribe that reuses the connector's existing cooperative-cancellation
teardown. The OKX snapshot-on-subscribe quirk (WR-03) is already handled for the reconnect budget;
warmup-on-add must additionally gate against it so the snapshot candle does not double-count.

**Primary recommendation:** Grow `Universe.apply(desired) -> UniverseDelta` as the sole membership
mutator (mutating `_members` in place to preserve the feed's by-identity bind), push a new
`UniverseUpdateEvent` (msgspec `Event`, `EventType.UNIVERSE_UPDATE`) whose `_routes` fan-out drives
two consumers (provider subscribe/warmup + remove-policy), host the cadence poll on
`ScreenersHandler` behind a live-only clock timer, and keep the whole subsystem **oracle-dark** by
construction (single-symbol SMA_MACD → `desired == current` → empty delta → no event, no side
effects). Exercise dynamic **data** subscription live on the OKX demo (BTC/USDC ↔ ETH/USDC);
exercise the **remove-policy + force-close order** deterministically on the paper/`ReplayDataProvider`
vehicle (EEA demo cannot settle those orders).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Membership set + diff | Universe subsystem (`universe/`) | — | D-03: `Universe` is the single source of truth; `apply()` owns the mutation + delta |
| Selection (desired set) | Universe/selection (`membership.py`) | ScreenersHandler (host) | D-04: "screeners propose, membership disposes"; lean `UniverseSelectionModel` grows in `membership.py` |
| Poll cadence trigger | Engine/live timer → EventHandler TIME route | ScreenersHandler | D-02: dormant TIME route; live-only clock timer emits `TimeEvent` |
| Change propagation | EventHandler `_routes` (queue) | — | D-04: queue-only; `UniverseUpdateEvent` fans to N consumers |
| WS subscribe/unsubscribe | Connector/provider (`OkxDataProvider` + `OkxConnector` loop) | — | D-05: socket state lives in the data arm's subscription registry |
| Warmup-on-add | `LiveBarFeed.warmup` (feed) | provider (`fetch_ohlcv_backfill`) | UNIV-02: Phase-3 machinery, reused verbatim |
| Remove-policy (orphan/force-close) | order/portfolio admission + a remove-policy consumer | — | D-01: "block new entries" is an admission-side gate; force-close emits an order |
| Venue bound (markets map) | `OkxExchange.validate_symbol` (execution) | selection guard | D-06: reuse the existing markets-map seam |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UNIV-01 | A lean universe-membership **poll seam** for mid-run add/remove (grows `universe/membership.py` per its D-20 target) — NOT the full production screener | §4 (poll cadence/timer), §5 (`UniverseUpdateEvent` seam), §6 (`Universe.apply`/`UniverseDelta`), §7 (poll-handler home) |
| UNIV-02 | Warmup-on-add replays new symbol's history through the same `update(bar)` path (reuses Phase-3 backfill); open-position-on-remove policy defined | §1–§3 (subscribe + warmup + snapshot gating), §8 (remove-policy gate), §10 (deterministic test vehicle) |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Open-position-on-remove policy: configurable, DEFAULT orphan-and-track.** On removal of a
  symbol holding an open position: default keeps the position open with its **WS subscription + ring
  alive** so SLTP/exit can fire; the engine **blocks new entries** for that symbol; it **fully
  detaches only once flat**. A **force-close** flag emits a market exit at removal then detaches.
  Never force a market exit by default. Plan-time: where the policy flag lives; the exact "block new
  entries" admission gate; optional force-close-after-N-bars backstop NOT locked (discretion).
- **D-02 — Poll trigger: clock-timer TIME route.** Wire the **dormant TIME route** (Phase-3 D-05
  reserved it): a real clock timer fires `TimeEvent`s on a cadence **decoupled from bar delivery**.
  The TIME-route consumer is the **poll handler** (runs selection, diffs, emits). Plan-time: timer
  mechanism + default cadence.
- **D-03 — Seam shape: `Universe` owns mutation; the diff happens inside `Universe.apply()`.**
  `Universe.apply(desired: set[str]) -> UniverseDelta` computes `added`/`removed`, mutates `_members`
  **in place** (feed reads `.members` by identity — Pitfall 4), updates `instrument_map`, and returns
  the delta. `Universe` stays **queue-free** — NO subscribe/warmup/close side effects, holds NO
  `global_queue`. Side effects live in the event consumers.
- **D-04 — Change propagation: push a `UniverseUpdateEvent` (queue-only).** New `msgspec.Struct`
  `Event` subclass carrying `added: tuple[str, ...]` / `removed: tuple[str, ...]`; add
  `EventType.UNIVERSE_UPDATE` + a `_routes` entry (three-step flow). Route fans one event to multiple
  consumers. Distinct from `ScreenerEvent`/`EventType.SCREENER` (the "propose" seam). Flow: timer TIME
  → poll handler → `universe.apply(desired)` → if non-empty `global_queue.put(UniverseUpdateEvent)` →
  route to (a) provider/feed (`subscribe`+`warmup` / `unsubscribe`) and (b) remove-policy handler.
- **D-05 — FULL real live OKX dynamic subscribe/unsubscribe, sourced from the universe.**
  Un-hardcode `_OKX_STREAM_SYMBOL`; `OkxDataProvider` gains `subscribe(symbol)`/`unsubscribe(symbol)`
  (spawn/cancel a `candle{tf}` coroutine on the running loop); warmup-on-add rides
  `LiveBarFeed.warmup`; the provider is a **pure `UniverseUpdateEvent` consumer** owning only a
  mechanical `{symbol: live_channel}` registry (**zero membership duplication**). Data subscription is
  live-testable on the demo; order settlement stays paper/replay. Plan-time: coroutine lifecycle
  (spawn/cancel, per-channel supervisor), snapshot-on-subscribe gating, rate-limit budget across N
  channels.
- **D-06 — Selection is bounded by the venue markets map.** Reuse `OkxExchange.validate_symbol()`
  (consults `connector.client.markets` from `load_markets()`); filter the poll's desired set before
  `universe.apply()`. Plan-time: direct call vs a small guard; backtest/paper behavior (no live
  markets map — accept, as `validate_symbol` already does).

### Claude's Discretion
- Class/method split of the selection source (lean `UniverseSelectionModel` in `membership.py`) vs the
  poll handler (D-03/D-04 lock the principle, not the file layout).
- `UniverseDelta` return-type shape and `added`/`removed` field types (`tuple[str, ...]` recommended).
- Timer mechanism + default poll cadence (D-02); policy-flag home + optional force-close backstop
  (D-01); coroutine lifecycle + snapshot-gating + rate-limit details (D-05).
- Whether the poll handler is a new thin handler or grows onto an existing one (e.g. `ScreenersHandler`).

### Deferred Ideas (OUT OF SCOPE)
- Full ranked production screener (volume/liquidity ranking, cross-sectional selection) — v2.
- Burst-coalescing multi-symbol `BarEvent` (D-04 reserved seam) — NOT needed.
- Live order-settlement of dynamically-added symbols / live force-close settlement — blocked by EEA
  demo; paper/replay-verified here, live follow-on when a flat/non-EEA account is available.
- Force-close-after-N-bars backstop — discussed, not locked; plan-time may add under the D-01 flag.
</user_constraints>

## Project Constraints (from CLAUDE.md)

- **Queue-only cross-domain writes.** Handlers never call across domains; they emit events. The
  provider learns membership changes via `UniverseUpdateEvent`, never a direct call or injected read.
  (D-04.)
- **New event type = frozen msgspec `Event` subclass + `EventType` member + `_routes` entry** (the
  documented three-step flow). Events are `msgspec.Struct` (NOT dataclasses); `type` is a
  `ClassVar[EventType]`. `_dispatch` raises `NotImplementedError` on an unrouted type.
- **Money is `Decimal` end-to-end**; `to_money(str(x))` only at the connector/serialization edge, never
  `Decimal(float)`. (Relevant to force-close order construction and any warmup pricing.)
- **Determinism:** one shared seeded `random.Random` injected at wiring; business `time` (venue/bar
  stamp), never wall-clock — *except* the D-02 poll timer, which is a control-plane cadence explicitly
  decoupled from bar delivery (wall-clock-derived cadence is acceptable there; it must not stamp bar
  `time`).
- **Indentation (per-file, never normalize):** `universe/`, `config/`, `core/`, `price_handler/feed/`,
  `events_handler/events/`, `price_handler/providers/` are **4-space**. `order_handler/`,
  `portfolio_handler/`, `execution_handler/`, `screeners_handler/`, `events_handler/full_event_handler.py`
  are **TABS**. `OkxExchange` (`execution_handler/exchanges/okx.py`) is TABS; `OkxDataProvider` and
  `ReplayDataProvider` (`price_handler/providers/`) are 4-space. **`live_trading_system.py` is 4-space.**
- **`mypy --strict`** applies to new code. Note `live_trading_system.py`, the OKX order arm, sql/live
  subsystems are `ignore_errors`-deferred in `pyproject.toml`; `okx_provider.py` and the `universe/`
  package are **strict** — new provider/universe code must be strict-clean.
- **`filterwarnings=["error"]` + `--strict-markers`.** Any unclosed aiohttp session / unawaited
  coroutine / ResourceWarning fails the suite. `pytest-asyncio` is configured (COV-01).
- **Import-side-effect inertness gate** (`tests/integration/test_okx_inertness.py`): the backtest import
  path must not pull ccxt/aiohttp/live code. All live imports stay LAZY inside
  `LiveTradingSystem.__init__` venue branches. New `UniverseUpdateEvent` lands in the events package
  (already import-light); the poll handler / timer must stay off the backtest hot path.

## Standard Stack

No new packages. Every capability is served by an in-repo module already on the live path.

### Core (reused, in-repo)
| Module | Purpose | Why standard |
|--------|---------|--------------|
| `itrader/universe/universe.py` (`Universe`) | Membership owner; grows `apply()` (D-03) | Already the by-identity `.members` source the feed binds |
| `itrader/universe/membership.py` (`derive_membership`, `active_membership`) | Selection primitives; lean `UniverseSelectionModel` grows here (D-20/D-04) | Pure, queue-free, documented growth target |
| `itrader/universe/instruments.py` (`derive_instruments`) | Symbol→`Instrument` map for added symbols | The instrument-map source `apply()` updates |
| `itrader/events_handler/events/base.py` (`Event`) + `market.py` | msgspec `Event` base + naming precedent for `UniverseUpdateEvent` | The three-step event contract |
| `itrader/core/enums/event.py` (`EventType`) | Add `UNIVERSE_UPDATE` member | Single discriminator home |
| `itrader/events_handler/full_event_handler.py` (`_routes`) | TIME-route wire + new `UNIVERSE_UPDATE` route | One reviewable dispatch literal |
| `itrader/price_handler/feed/live_bar_feed.py` (`LiveBarFeed.warmup`) | Warmup-on-add (FEED-03), reused verbatim | Replays REST history one-by-one through `update()` |
| `itrader/price_handler/providers/okx_provider.py` (`OkxDataProvider`) | Grows `subscribe`/`unsubscribe` + registry (D-05) | Owns the native candle socket + supervisor |
| `itrader/connectors/okx.py` (`OkxConnector`) | `spawn`/`call`/`load_markets`; the asyncio loop | The single loop the dynamic coroutines run on |
| `itrader/execution_handler/exchanges/okx.py` (`OkxExchange.validate_symbol`) | Venue markets-map bound (D-06) | Reuse, don't reimplement |
| `itrader/screeners_handler/screeners_handler.py` (`ScreenersHandler`) | Candidate poll-handler host (D-04 discretion) | Already holds the feed + cadence-screens |

**Installation:** none. `poetry install` already provides everything.

## Package Legitimacy Audit

**Not applicable** — this phase installs no external packages. All work is in-repo wiring. No
`slopcheck`/registry verification needed.

## Architecture Patterns

### System Architecture Diagram (Phase-6 flow)

```
[live-only clock timer thread]
        │  puts TimeEvent (cadence, wall-clock-derived, decoupled from bars)
        ▼
   global_queue ──► EventHandler._dispatch ──► _routes[EventType.TIME]
        ▲                                          │
        │                                          ▼
        │                            poll_handler.on_time (cadence + source guard)
        │                                          │  ask selection source for desired set
        │                                          ▼
        │                            desired = validate_against_markets(desired)   (D-06)
        │                                          │  filter via OkxExchange.validate_symbol
        │                                          ▼
        │                            delta = universe.apply(desired)   (D-03: mutate _members in place)
        │                                          │  UniverseDelta(added, removed)
        │                                          ▼
        │                            if delta non-empty:
        └──────────────── global_queue.put(UniverseUpdateEvent(time, added, removed))
                                                   │
                            _routes[EventType.UNIVERSE_UPDATE]  (list-order fan-out)
                                   ├──► (a) subscription consumer:
                                   │        provider.subscribe(sym) + feed.warmup(sym)   (added)
                                   │        provider.unsubscribe(sym)                     (removed)
                                   └──► (b) remove-policy consumer:
                                            orphan-and-track (default) → mark sym "leaving",
                                              keep WS+ring alive, block new entries until flat
                                            force-close (flag) → emit market-exit OrderEvent, detach

   provider.subscribe(sym): connector.spawn(supervised candle{tf} coroutine) →
        registry[sym] = task ; snapshot-on-subscribe gated against warmup (WR-03)
   provider.unsubscribe(sym): registry.pop(sym).cancel() → cooperative teardown (async-with closes WS)
```

File-to-implementation mapping is in the Component Responsibility table above; the diagram is data flow.

### Pattern 1: The documented three-step "new event type" flow (D-04)
**What:** Add an event without touching the dispatcher's branching.
**Steps (verified against source):**
1. `itrader/core/enums/event.py::EventType` — add `UNIVERSE_UPDATE = "UNIVERSE_UPDATE"` (line ~31,
   alongside `SCREENER`). String values, `_missing_` case-insensitive parse already present.
2. `itrader/events_handler/events/market.py` — add the struct next to `ScreenerEvent`:
   ```python
   # Source: events/base.py:21 (Event), events/market.py:73 (ScreenerEvent precedent)
   class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
       type: ClassVar[EventType] = EventType.UNIVERSE_UPDATE
       added: tuple[str, ...]      # +sym → subscribe + feed.warmup
       removed: tuple[str, ...]    # −sym → unsubscribe + remove-policy
   ```
   `time`/`event_id`/`created_at` inherited from `Event`. Export it from `events_handler/events/__init__.py`.
3. `itrader/events_handler/full_event_handler.py::EventHandler.routes` — add
   `EventType.UNIVERSE_UPDATE: [<subscribe_consumer>, <remove_policy_consumer>]` (list order IS
   execution order). Currently `SCREENER`/`UPDATE` are explicit-empty lists (lines 105-106) — mirror
   that shape. Note this file is **TABS**.
**Landmine:** `_dispatch` raises `NotImplementedError` on an unrouted type (line 138). If you add the
`EventType` member but forget the `_routes` entry, any emitted `UniverseUpdateEvent` **crashes the
dispatcher** — on live that routes through `_publish_and_continue` (logged, not fatal), on backtest it
is fail-fast. Add the route entry in the same change as the enum member.

### Pattern 2: `_routes` fan-out to multiple consumers (D-04)
**What:** One event, N ordered side-effect handlers — exactly like `EventType.BAR` today
(`full_event_handler.py:93-97`: mark-to-market → matching → signals) and `EventType.FILL`
(`:101-104`: portfolio → order-mirror). The `UNIVERSE_UPDATE` route lists the subscription consumer
first (so the socket/warmup is in flight) then the remove-policy consumer.
**Live gate note:** on the live path every dequeued event passes through `_dispatch_live`
(`live_trading_system.py:1030`), which gates only `SIGNAL`/`ORDER`. `UNIVERSE_UPDATE` (and `TIME`)
pass straight through — good: membership changes are not suppressed by a submission pause. But a
force-close **`OrderEvent`** emitted by the remove-policy consumer WILL hit the `_dispatch_live` gate
and, while paused/halted, be suppressed/deferred (`:1047`). That is correct (don't force-close blind),
but the plan must be aware the force-close is not guaranteed-immediate under a pause.

### Pattern 3: In-place membership mutation preserving by-identity bind (D-03, Pitfall 4)
**What:** `Universe._members` is held **by identity** by the live feed:
`live_trading_system.py:1250` does `self.feed.bind(self.global_queue, universe.members)`, and
`LiveBarFeed.bind` (`live_bar_feed.py:134`) stores `self.membership = membership` — the SAME list
object. `Universe.members` returns `self._members` by identity, NOT a copy (`universe.py:52-60`, the
docstring is explicit: "returned BY IDENTITY (not a defensive copy)... DO NOT mutate it; a mutation
rewrites the universe's internal membership in place").
**Therefore `apply()` must mutate the existing list in place** (`self._members[:] = sorted(...)` or
`.append`/`.remove`), never rebind `self._members = new_list` — a rebind would leave the feed pointing
at the stale list. See §6 for the recommended `apply()` body.

### Anti-Patterns to Avoid
- **Duplicating membership in the provider.** The provider's `{symbol: task}` registry is *socket
  state*, not a second membership copy. It is derived from `UniverseUpdateEvent`s; it never decides
  membership (D-05, the user's guiding constraint).
- **Rebinding `Universe._members`** (breaks the feed bind — Pitfall 4).
- **`Universe` doing side effects.** `apply()` computes + mutates only; NO subscribe/warmup/queue
  (D-03). Side effects belong to the `_routes` consumers.
- **Adding the poll handler to `_routes[TIME]` without a source/cadence guard** — would run selection
  every backtest TIME tick and risk a W1/W2 regression (see §11 / Pitfall 3).
- **Emitting a `UniverseUpdateEvent` for an empty delta** — floods the queue and defeats oracle-dark;
  gate on `delta` non-empty before `put` (D-04 step 4).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Warmup-on-add | A new bulk `warmup_from()` fast-path | `LiveBarFeed.warmup(sym, tf, depth)` (`live_bar_feed.py:234`) | FEED-03/LX-09: a second state-building path re-opens the parity audit; explicitly out-of-scope in REQUIREMENTS |
| Coroutine spawn/cancel/track | A second asyncio loop or a raw `create_task` off-thread | `OkxConnector.spawn` (`okx.py:182`) + its `_on_task_done`/`disconnect` teardown | ccxt.pro binds sockets to the creating loop; cross-thread use corrupts state (connector docstring Pitfall 3) |
| Venue symbol validation | A new markets fetch/allow-list | `OkxExchange.validate_symbol` (`exchanges/okx.py:1016`) | D-06: `connector.client.markets` is the loaded source of truth; already handles the no-markets (paper) accept |
| Snapshot-on-subscribe dedup | New de-dup logic | `LiveBarFeed.update` monotonic guard (duplicate/stale/off-grid branches, `live_bar_feed.py:156`) | The feed already drops a re-sent/duplicate bar; the snapshot lands on the duplicate/stale branch once warmup has set `L` |
| Reconnect/backoff for a new channel | New supervisor | `_run_stream_supervisor` (`okx_provider.py:321`) | Per-channel bounded-retry + HALT already built; the per-symbol coroutine reuses it |

**Key insight:** UNIV-02's warmup half and the whole reconnect/supervisor surface are *already built*
generically. The genuinely new code is (a) `Universe.apply`, (b) `UniverseUpdateEvent` + route, (c) the
provider's per-symbol registry + subscribe/unsubscribe, (d) the poll handler + live timer, (e) the
remove-policy consumer + admission gate.

## Deferred-Gap Answers (the 11 focus areas)

### §1 — OKX dynamic subscribe/unsubscribe coroutine lifecycle (D-05)

**Current state (verified):** `OkxDataProvider.start_stream()` (`okx_provider.py:208`) computes
`channel = "candle" + self._okx_interval(self._timeframe)` for the single `self._symbol`, calls
`self._connector.spawn(self._stream_candles(symbol_okx, channel))`, and stores ONE handle in
`self._stream_handle`. `_stream_candles` (`:221`) wraps `_connect_and_consume_candles` in
`_run_stream_supervisor`. `OkxConnector.spawn` (`okx.py:182`) creates the task on the loop via
`call_soon_threadsafe`, adds it to the flat `self._stream_tasks` set, attaches `_on_task_done`, and
returns the `asyncio.Task`. `disconnect` (`okx.py:233`) cancels **all** tracked tasks and
`gather(..., return_exceptions=True)`.

**Recommended shape:**
- Add a **subscription registry** on the provider: `self._streams: dict[str, asyncio.Task[Any]] = {}`
  keyed by the **universe-member symbol string** (the same form stamped into `ClosedBar["symbol"]`),
  plus the reconnect-supervisor state (`_reconnect_attempts`, `_streams_down`) which is already keyed
  by a `stream_name` string — **key those per-symbol** too (today they use the literal `"candles"`;
  with N channels the key must become the symbol/channel or the budgets collide).
- **`subscribe(symbol)`:** normalize via `_to_okx_symbol`, compute `candle{tf}`, and
  `task = self._connector.spawn(self._stream_candles(symbol_okx, channel))`; store
  `self._streams[symbol] = task`. Because `spawn` runs on the connector loop via
  `call_soon_threadsafe` and blocks on a `ready` Event (`okx.py:200-207`), `subscribe` is
  **engine-thread-safe** (the poll handler runs on the engine thread). Idempotent: if `symbol` already
  in `_streams`, no-op.
- **`unsubscribe(symbol)`:** `task = self._streams.pop(symbol, None); if task: task.cancel()`. The
  existing `_connect_and_consume_candles` uses `async with aiohttp.ClientSession()` /
  `session.ws_connect(...)` (`okx_provider.py:252-253`) — cancellation propagates
  `CancelledError`, the `async with` closes the socket/session (docstring Pitfall 4), and
  `_run_stream_supervisor` re-raises `CancelledError` untouched (`:347`). `_on_task_done` sees
  `task.cancelled()` and untracks quietly (`okx.py:222`). **No new teardown code needed** — reuse the
  connector's cooperative-cancel path. Note: `task.cancel()` from the engine thread on a task owned by
  the connector loop is safe (asyncio `Task.cancel` is thread-safe for scheduling the cancellation).
- **Per-symbol supervisor:** each symbol's coroutine already IS supervised by its own
  `_run_stream_supervisor` invocation — no shared supervisor. Just make the `stream_name`/budget keys
  per-symbol so one symbol's reconnect budget/`_streams_down` entry doesn't shadow another's.

**Must-do wiring steps:**
1. Un-hardcode `_OKX_STREAM_SYMBOL` (`live_trading_system.py:62`): source the initial subscription set
   from `universe.members` at `_initialize_live_session` and call `provider.subscribe(sym)` for each
   member instead of the single `start_stream()` at `:1534`. Keep a compatibility path for the current
   single-symbol default.
2. Update `_stream_handles`/`disconnect` interaction: today the connector cancels all `_stream_tasks`;
   per-symbol tasks are still in `_stream_tasks` (spawned via `spawn`), so `disconnect` already tears
   them all down. The provider's `_streams` map is an additional index, not a second lifecycle owner.
3. The wiring-time membership assertion (`live_trading_system.py:1261`, `_OKX_STREAM_SYMBOL not in
   universe.members`) must generalize: assert **every** subscribed symbol is a member (ring-key vs
   `window()` ticker mismatch guard).

**Landmines:** (a) The reconnect-budget/`_streams_down` maps are currently single-keyed `"candles"`;
N channels sharing that key means one symbol's drop marks *all* down and one symbol's payload resets
*all* budgets — must key per-symbol. (b) `is_streaming_healthy()` (`okx_provider.py:402`) returns
`not self._streams_down` (any-arm-down = unhealthy); with N symbols this becomes "all symbols healthy",
which is the correct compound-resume semantics but changes the meaning — verify against
`_all_venue_streams_healthy` (`live_trading_system.py:974`).

### §2 — OKX snapshot-on-subscribe quirk vs warmup-on-add (WR-03)

**The quirk (verified in-code):** `_connect_and_consume_candles` documents (`okx_provider.py:262-269`)
that OKX pushes an **in-progress-candle snapshot (`confirm='0'`) within ~30ms of EVERY subscribe.**
That snapshot is already handled for the **reconnect budget**: only a payload delivered *after* the
snapshot resets the budget (`payload_seen` gate, `:270,289-291`). But `_process_row` (`:449`)
**already drops `confirm != "1"`** (`:462-464`) — so the forming snapshot candle **never reaches the
feed** as a delivered bar. The snapshot is a *forming* bar; only *closed* bars (`confirm=="1"`) flow to
`feed.update`.

**Interaction with warmup-on-add:** warmup replays REST-fetched **closed** bars one-by-one through
`feed.update` (`live_bar_feed.py:254-260`), each advancing the monotonic stamp `L`. The subscribe's
snapshot is `confirm='0'` → dropped at the provider. The *first live closed bar* after subscribe will
have `confirm=="1"` and flow to `update`; the monotonic guard (`:156`) then classifies it against `L`:
- If it equals the last warmed bar's open → **duplicate branch** (dropped quietly if identical OHLCV,
  `:314-318`) or **revision** (dropped, no state mutation, `:319-323`).
- If it is `L + tf` → in-sequence deliver.
- If it is `> L + tf` → gap backfill-and-replay (the REST warmup already covered the interior, so the
  gap is small/none).

**Correct gating recommendation:** **Warmup BEFORE subscribe** for an added symbol (mirroring the
startup order at `live_trading_system.py:1532-1534`, where `feed.warmup(...)` precedes
`start_stream()`). This sets `L` from REST history so the first live closed bar lands cleanly on the
in-sequence or duplicate branch. Because the snapshot is `confirm='0'` and dropped at the provider,
there is **no double-count risk from the snapshot itself**; the only real risk is the *boundary bar*
(warmup's last REST bar vs the first live closed bar covering the same open) — which the feed's
duplicate branch already absorbs (the same Pitfall-5 boundary-dedup the reconnect path relies on,
`:271-276` of the feed). **Do not** add new snapshot-dedup logic — the confirm gate + monotonic guard
already cover it.

**Landmine — ordering under a running loop:** if `subscribe` is called from the engine thread (poll
handler) and `warmup` runs synchronously via `provider.fetch_ohlcv_backfill` (a blocking
`connector.call`, `okx_provider.py:493`), do warmup on the engine thread **before** spawning the
coroutine, so `L` is set before any live bar can arrive. The `_UniverseUpdateEvent` consumer runs on
the engine thread (it drains the queue), so this ordering is natural: consumer does
`feed.warmup(sym)` then `provider.subscribe(sym)`.

### §3 — Rate-limit budget across N dynamic channels (D-05)

**Findings:** OKX WS `subscribe` operations are subject to the connection/subscription limits, not the
REST token bucket. The connector keeps `enableRateLimit=True` for the ccxt REST client
(`okx.py:163`), which governs `fetch_ohlcv` warmup calls — those are the ones most likely to hit a
limit during a burst add. The native WS `subscribe` op is one JSON send per channel
(`okx_provider.py:250-254`). OKX allows many candle channels per business WS connection (documented
limits are generous — hundreds of channels per connection), and a request-rate limit applies to the
subscribe *messages* (OKX documents WS op limits on the order of a few requests per second per
connection). `[ASSUMED — training knowledge; verify against OKX docs before locking a cadence]`

**Recommendation (defensive, code-grounded):**
- This phase's realistic N is tiny (demo: BTC/USDC ↔ ETH/USDC — one add/remove at a time). **Do not
  build a rate-limit throttler** for the WS subscribe path in this phase; a single-symbol add/remove
  per poll is far under any OKX WS op limit.
- The **REST warmup** on add (`fetch_ohlcv_backfill`, paginated `while len(page)==limit`,
  `okx_provider.py:519`) is the real budget consumer. It already rides ccxt's `enableRateLimit` token
  bucket via `connector.call`, so a burst of adds is naturally paced by ccxt. Keep it there.
- If a future multi-add burst is a concern, pace subscribes by processing **one `added` symbol per
  `UniverseUpdateEvent` consumer iteration** (they arrive serialized on the engine-thread queue) — no
  explicit sleep needed; the poll cadence (§4) bounds the add rate.
- Flag as an **assumption to confirm**: the exact OKX business-WS subscribe op rate and max channels
  per connection (Assumptions Log A1).

### §4 — Timer mechanism + default poll cadence (D-02)

**Critical finding:** On the **live path there is no `TimeEvent` source today.** `LiveBarFeed` emits
`BarEvent` directly on bar arrival (`live_bar_feed.py:502-521`) and `generate_bar_event` is a
**dormant no-op** (`:641-650`); `TimeGenerator` is backtest-only. So the `_routes[EventType.TIME]`
list (`full_event_handler.py:89-92`: `[screen_markets, bar_event_source]`) **never fires on live**.
Wiring D-02 therefore requires a **new live-only timer that puts `TimeEvent` on `global_queue` on a
cadence**, plus adding the poll handler to the TIME route.

**Recommended mechanism:** a small **daemon timer thread** owned by `LiveTradingSystem`, started in
`start()` (live daemon path only, NOT `run_paper_replay`), that does
`global_queue.put(TimeEvent(time=datetime.now(UTC)))` every `poll_cadence` seconds until `_stop_event`
is set. Rationale:
- It runs only on the live daemon path → **oracle-dark and W1/W2-inert by construction** (backtest and
  `run_paper_replay` never start it; run_paper_replay is synchronous with no daemon, `:1283`).
- It reuses the existing `queue.Queue` MPSC-safe `put` (same discipline as the connector-loop bar
  emission); the engine thread drains it.
- A real clock timer decoupled from bars satisfies D-02 ("fires even on a quiet symbol; cadence set
  independently of the bar timeframe"). Framework-idiomatic (Nautilus clock timers / LEAN scheduled
  selection).
- Do **not** reuse `core/clock.py::BacktestClock` (that's the deterministic sim clock seam); a live
  cadence timer is wall-clock-derived control-plane, not business time.

**Alternative considered (cadence-check on bar delivery):** piggyback the poll on `EventType.BAR`. Rejected
because D-02 explicitly wants cadence *decoupled from bar delivery* (must fire on a quiet symbol) — a
bar-gated poll starves when no bars arrive, exactly the failure D-02 calls out.

**Default cadence recommendation:** for a 1d base timeframe, **poll every 60s** is a safe default
(control-plane responsiveness without hammering selection). Make it a config value
(`MonitoringSettings`/live config) so it is tunable. `[ASSUMED — no locked cadence; recommend 60s,
flag as A2 for confirmation.]`

**Route wiring:** add `poll_handler.on_time` to `_routes[EventType.TIME]`. **Guard it** so backtest
(where TIME fires every tick via TimeGenerator) pays near-zero: `on_time` early-returns when no dynamic
selection source is wired (backtest wires none) AND applies a cadence check. See §7/§11.

### §5 — `UniverseUpdateEvent` seam wiring (D-04)

Fully covered by Pattern 1 + Pattern 2 above. Confirmed three-step flow: `EventType.UNIVERSE_UPDATE`
(enum), `UniverseUpdateEvent` (msgspec struct in `events/market.py`, exported from the events barrel),
`_routes` entry (fan-out to subscribe-consumer + remove-policy-consumer). `tuple[str, ...]` keeps the
payload immutable on the frozen struct. Distinct from `ScreenerEvent`/`EventType.SCREENER` (keep the
"propose" seam separate). The events package is import-light (msgspec, no pandas at module scope) so
this does not disturb the inertness gate.

### §6 — `Universe.apply()` + `.members`-by-identity (D-03, Pitfall 4)

**Current `Universe` (verified):** a pure static facade holding `self._members: list[str]` and
`self._instruments: dict[str, Instrument]` (`universe.py:37-49`); `.members` returns `self._members`
by identity (`:52-60`); `.instrument(symbol)` looks up the map, `KeyError` on miss (`:62-80`). No
mutation surface today.

**Recommended `UniverseDelta` shape (discretion):** a frozen, immutable value object (4-space,
strict-clean):
```python
# Source: universe/universe.py (new); mirror LEAN SecurityChanges.Added/Removed
@dataclass(frozen=True, slots=True)
class UniverseDelta:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    def is_empty(self) -> bool:
        return not self.added and not self.removed
```
(A `msgspec.Struct` is also fine but `UniverseDelta` is an internal return value, not a queue event —
a frozen dataclass keeps it dependency-light. The event carries the same `tuple[str, ...]` fields.)

**Recommended `apply()` body:**
```python
def apply(self, desired: set[str]) -> UniverseDelta:
    current = set(self._members)
    added = tuple(sorted(desired - current))
    removed = tuple(sorted(current - desired))
    if not added and not removed:
        return UniverseDelta(added=(), removed=())   # oracle-dark fast path
    # Mutate the SAME list object in place (Pitfall 4 — feed holds it by identity).
    new_members = sorted((current - set(removed)) | set(added))
    self._members[:] = new_members          # slice-assign: same object, new contents
    for sym in removed:
        self._instruments.pop(sym, None)
    # For added symbols, resolve instruments (see landmine below) and insert.
    return UniverseDelta(added=added, removed=removed)
```
- **`self._members[:] = ...`** (slice assignment) mutates in place — the feed's `self.membership`
  reference stays valid (Pitfall 4). **Never** `self._members = new_members`.
- **Sorted** ordering matches `derive_membership`'s WR-05 sort (`membership.py:83`) — keeps multi-symbol
  reproducibility; single-symbol is its own sort so the oracle is unaffected.

**Landmine — instrument resolution for added symbols:** `derive_instruments` (`instruments.py:170`) is
a *wiring-time, strategy-driven* derive — it takes strategies + screener tickers, not an ad-hoc symbol
list, and needs `price_data` for precision inference. For a dynamically added symbol you must resolve
its `Instrument` at add time. Options: (a) resolve from the venue markets map
(`connector.client.markets[sym]` precision) — the live-correct source; (b) fall back to the
`_DEFAULT_*` ladder in `instruments.py` (2dp price / 8dp qty). **Recommendation:** add a small
`Instrument`-from-markets resolver (reuse the D-06 markets map you already consult for validation) so an
added symbol gets venue-correct precision; default-ladder fallback when markets absent (paper). This is
Claude's-discretion territory (D-06 plan-time) — the plan should decide whether the poll handler passes
resolved instruments into `apply()` or `Universe` resolves them itself. Keeping `Universe` queue-free
(D-03) argues for passing the resolver/instruments *into* `apply()` or a sibling method, not giving
`Universe` a connector reference.

**Who calls `apply()`:** the poll handler (engine thread), after D-06 filtering. `Universe` stays
queue-free; the poll handler puts the `UniverseUpdateEvent`.

### §7 — Poll-handler home (D-04 discretion)

**Evidence for `ScreenersHandler`:** it already holds `self.feed` (`screeners_handler.py:27`), already
cadence-screens (`screen_markets` with `check_timeframe`, `:55-92`), already exposes
`get_screeners_universe()` (`:142-150`), and is already constructed on the live path
(`live_trading_system.py:231`) and wired into `_routes[TIME]` (`full_event_handler.py:90`). It is the
natural, low-friction host.

**Recommendation:** **grow the poll onto `ScreenersHandler`** (or a thin `UniversePollHandler`
collaborator it owns) rather than a brand-new top-level handler. Add `on_time(time_event)` that:
1. Guard: `if self._selection_source is None: return` (backtest/paper wire no source → oracle-dark,
   near-zero cost).
2. Cadence check (reuse `check_timeframe`-style or a wall-clock delta against `poll_cadence`).
3. `desired = self._selection_source.select(...)` (the lean `UniverseSelectionModel` in `membership.py`).
4. `desired = {s for s in desired if exchange.validate_symbol(s)}` (D-06).
5. `delta = self._universe.apply(desired)`; `if not delta.is_empty(): self.global_queue.put(
   UniverseUpdateEvent(time=time_event.time, added=delta.added, removed=delta.removed))`.

**Caveat (tabs):** `ScreenersHandler` is TAB-indented. The lean selection model in `membership.py` is
4-space. Keep each edit matched to its file.

**Class/method split (discretion, D-04):** the *selection source* (pure "what should the universe be?")
belongs in `membership.py` as the lean `UniverseSelectionModel` (D-20 growth target, pure/derived, no
queue/feed); the *poll handler* (cadence + apply + emit) belongs on `ScreenersHandler` (has the queue +
feed). This preserves "selection proposes / engine disposes."

### §8 — Remove-policy gate (D-01)

**Policy-flag home (recommendation):** put the `remove_policy` flag in the **live/poll-seam config**,
not the byte-exact run config. Candidates: `PortfolioConfig.trading_rules` (already threaded into the
order domain, `live_trading_system.py:369`) or a new field on the live-session/universe config. Because
the flag only matters on the live/dynamic path and must not perturb the backtest oracle, keep it out of
`SystemConfig.PerformanceSettings`. Default `"orphan-and-track"`.

**The "block new entries for a leaving symbol" admission gate (verified plug-in point):**
`AdmissionManager.process_signal` (`admission/admission_manager.py:120`) runs a sequence of admission
gates BEFORE sizing (`:181-209`): `_enforce_direction_admission` → `_enforce_position_admission` →
`_enforce_leverage_admission`, each returning an audited-REJECTED `OperationResult` on failure. **Add a
new gate `_enforce_leaving_symbol_admission(signal_event)` as the FIRST gate** (before direction): if
`signal_event.ticker` is in the "leaving set" AND the signal opens/increases a position (a NEW entry —
not an exit/reduce), return an audited REJECTED result (new `OrderTriggerSource` reason, e.g.
`ADMISSION_LEAVING`). Exits/reduces (SLTP, the orphaned position's own stop) must still pass so the
position can go flat.
- **Where the "leaving set" lives:** a small set queried at admission time. Since `AdmissionManager`
  already receives an injected `Universe` (`admission_manager.py:68,93 set_universe`), the cleanest
  home is a **leaving-set on `Universe`** (or a sibling read-model) that the remove-policy consumer
  populates on removal and clears when the position goes flat. `AdmissionManager` reads it via the
  injected `Universe` — no new cross-domain dependency, consistent with the existing `_universe` seam.
- **"Keep WS + ring alive until flat" mechanism:** on `orphan-and-track` removal, the remove-policy
  consumer must **NOT** call `provider.unsubscribe(sym)` — it adds `sym` to the leaving set and leaves
  the WS/ring running so bars keep arriving and the stop can trigger. Detachment (unsubscribe + drop
  from leaving set + remove from `Universe`) happens **only when the position reaches flat** — detected
  on the FILL path (`PortfolioHandler.on_fill` / `OrderHandler.on_fill`, `full_event_handler.py:101-104`)
  when `open_position_count`/net-quantity for `sym` hits zero. **Landmine:** the `UniverseUpdateEvent`
  `removed` list normally drives `provider.unsubscribe`; under orphan-and-track the unsubscribe must be
  *deferred*, not immediate. So the subscribe-consumer must consult the policy: force-close → unsubscribe
  now; orphan-and-track with an open position → keep alive + mark leaving; orphan-and-track with no open
  position → unsubscribe now (nothing to keep alive).

**Force-close mechanism (flag):** the remove-policy consumer emits a market-exit `OrderEvent` (via the
signal/order path, Decimal money) for the open position, then detaches. This order hits `_dispatch_live`
(suppressed under pause/halt — acceptable) and, live, cannot settle on the EEA demo (non-flat/price-floor)
— so it is **exercised on paper/replay** (§10). Optional force-close-after-N-bars backstop is NOT locked
(discretion); if added, it lives behind the same policy flag and counts bars via the leaving symbol's
own arriving `BarEvent`s.

### §9 — Venue markets-map validation (D-06)

**Verified reuse path:** `OkxExchange.validate_symbol(symbol)` (`exchanges/okx.py:1016-1032`) reads
`getattr(self._connector.client, "markets", None)`; if it's a `dict`, returns
`self._to_symbol(symbol) in markets`; otherwise **returns `True` (accept)**. `load_markets()` runs in
`OkxConnector._build_client` (`okx.py:174`) at connect, so `markets` is populated on the live path.

**Recommendation:** the poll handler filters `desired` through `validate_symbol` before `apply()`
(D-06). Because the OKX arm is wired only for `exchange=='okx'`, the poll handler needs access to the
exchange — inject the `OkxExchange` (or a small `SymbolValidator` protocol wrapping it) into the poll
handler at the live composition root. On **backtest/paper** there is no live markets map (the paper
path has no `OkxExchange`); the guard should **accept all** — which `validate_symbol` already does when
`markets` is not a dict, and which is moot anyway since backtest/paper wire no selection source (poll is
inert). Keep the direct-call approach (poll handler → `validate_symbol`) rather than a `Universe`-side
guard, so `Universe` stays connector-free (D-03).

### §10 — Deterministic test vehicle

**Verified constants (`live_trading_system.py`):** `_OKX_STREAM_SYMBOL="BTC/USDC"` (`:62`),
`_OKX_STREAM_TIMEFRAME="1d"` (`:63`); paper constants `PAPER_PARITY_SYMBOL="BTCUSD"` (`:74`),
`_PAPER_STREAM_SYMBOL`/`_PAPER_STREAM_TIMEFRAME` (`:84-85`); `ReplayDataProvider`
(`price_handler/providers/replay_provider.py`) replays the golden CSV synchronously via
`iter_closed_bars`/`replay_bar` through `feed.update` (`:120-145`), the SAME seam OKX uses. The paper
driver `run_paper_replay` (`:1283`) is synchronous, no daemon, no timer.

**How remove-policy + force-close get exercised deterministically:**
- The `ReplayDataProvider` is single-symbol today (BTCUSD). To exercise add/remove **deterministically**
  you need a **multi-symbol replay**: either a second `ReplayDataProvider` for a synthetic second
  symbol, or a small multi-symbol replay harness that stamps two symbols and drives
  `UniverseUpdateEvent`s at scripted bar indices. Because `ReplayDataProvider` is a drop-in for
  `OkxDataProvider` on `set_bar_sink`/`fetch_ohlcv_backfill`, a paper `subscribe`/`unsubscribe` can be
  no-op stubs (there is no socket) while the feed ring + warmup + admission gate + force-close order all
  run through the real synchronous path.
- **Force-close order settlement** (which can't reach a fill on the EEA demo) settles through the reused
  `SimulatedExchange` on the paper path (bar-based fills, `FillEvent → PortfolioHandler.on_fill`) — so
  the orphan-goes-flat detach and the force-close-then-detach are both verifiable byte-deterministically
  offline, with no live venue.
- **Live demo coverage** is limited to **data subscription** (subscribe/unsubscribe a candle channel for
  ETH/USDC alongside BTC/USDC) — pure market data, not gated by the MiCA whitelist or price-floor
  (D-05). Verify sandbox=True first (memory: OKX demo creds).

**Recommendation:** add a paper/replay integration test that drives a two-symbol universe, emits a
scripted remove `UniverseUpdateEvent`, and asserts (a) orphan-and-track keeps the WS/ring alive + blocks
a new entry + detaches on flat, and (b) force-close emits a market exit and detaches. Keep a separate,
human-observed live-demo test for dynamic **data** subscribe/unsubscribe (like the existing
`tests/e2e/test_okx_sandbox_recon.py` pattern, RECON-06).

### §11 — Milestone gate impact (oracle-dark by construction)

**Why it's oracle-dark:** the single-symbol SMA_MACD golden run has `desired == current` on every poll
(the one declared symbol never changes) → `Universe.apply` returns an **empty delta** (fast path,
`is_empty()`) → **no `UniverseUpdateEvent` is emitted** → no subscribe/warmup/remove side effects fire.
Additionally, the D-02 poll timer runs **only on the live daemon path**, not backtest and not
`run_paper_replay` (synchronous, no daemon). So on the golden backtest path the subsystem is inert.

**What the plans MUST guarantee to keep the oracle byte-exact (134 / `46189.87730727451`) and W1/W2
non-regressed (15.7s / 152.8MB):**
1. **No new per-tick work on the backtest hot path.** If the poll handler is added to
   `_routes[EventType.TIME]` (which fires every backtest tick via TimeGenerator), `on_time` must
   early-return on a single cheap guard (`self._selection_source is None`) BEFORE any selection/derive
   work. Backtest wires no selection source → one attribute check per tick. **Measure W1** after wiring
   — even a cheap per-tick guard is a candidate regression; if measurable, prefer NOT adding the poll
   handler to the shared route and instead only wiring it live (e.g. a live-only route mutation in
   `start()`), keeping the backtest `_routes` literal untouched. (Recommended: measure first; the guard
   is expected to be free, but W1 is thermally sensitive — memory: v1.5 perf-gate thermal drift.)
2. **`Universe.apply` empty-delta fast path** must allocate nothing measurable and emit nothing (return
   the shared empty delta). No `put` on an empty delta.
3. **Inertness gate:** `UniverseUpdateEvent`/poll-handler/timer imports must not pull ccxt/aiohttp onto
   the backtest import path (`tests/integration/test_okx_inertness.py`). The event lives in the
   import-light events package; the timer/poll live on `LiveTradingSystem`/`ScreenersHandler` (already
   imported) — keep any provider/connector touch lazy inside the live branch.
4. **Determinism double-run** stays identical (no wall-clock leaks into business `time`; the poll
   timer's wall-clock cadence must never stamp a bar/fill `time`).
5. **Re-run the oracle + paper-parity gates** (`tests/integration/test_backtest_oracle.py`,
   `test_paper_parity.py`) unchanged and green after the change.

## Runtime State Inventory

This phase adds a subsystem; it does not rename/migrate stored state. The relevant *runtime* state to
manage (not persisted migration):

| Category | Items | Action Required |
|----------|-------|------------------|
| Stored data | None — no DB keys/collections renamed. Membership is derived at runtime; the operational store (orders/signals/portfolio) is unaffected. | None — verified: no schema/key touches. |
| Live service config | The subscription set (WS channels) — socket state, held in the provider's `{symbol: task}` registry. Not persisted (rebuilt from `universe.members` at start). | New: build initial subscriptions from `universe.members`; restart rebuilds from membership. |
| OS-registered state | None — no OS-level registrations. | None. |
| Secrets/env vars | None new. OKX creds already loaded via `OkxSettings` (`OKX_API_*`, no prefix). | None. |
| Build artifacts | None. | None. |

**New in-memory runtime state introduced:** (a) provider subscription registry `{symbol: asyncio.Task}`;
(b) per-symbol reconnect-budget/`_streams_down` keys (generalized from the single `"candles"` key);
(c) the "leaving set" for the remove-policy admission gate; (d) the live poll-timer thread. All are
rebuilt from membership on restart; none require persistence this phase.

## Common Pitfalls

### Pitfall 1: Rebinding `Universe._members` breaks the feed bind
**What goes wrong:** `apply()` does `self._members = new_list`; the live feed still points at the old
list (bound by identity at `live_trading_system.py:1250`), so `.members` and the feed disagree — added
symbols never enter the feed's membership, removed symbols linger.
**Root cause:** `.members` is returned by identity (`universe.py:52-60`), not copied.
**Avoid:** slice-assign `self._members[:] = ...` (mutate in place). **Warning sign:** feed
`MissingPriceDataError` at first `window()` for an added symbol, or a `feed.membership` that never
changes after `apply()`.

### Pitfall 2: Per-channel reconnect budgets collide on the shared `"candles"` key
**What goes wrong:** all dynamic channels share `_reconnect_attempts["candles"]` / `_streams_down` →
one symbol's drop pauses submission for all; one symbol's payload resets all budgets, defeating the D-20
HALT ceiling.
**Root cause:** `okx_provider.py` hard-codes `stream_name="candles"` (`:234`) for the single wiring-time
symbol.
**Avoid:** key the supervisor state per-symbol/channel. **Warning sign:** `is_streaming_healthy()`
flips on the wrong symbol; HALT ceiling never trips under a per-symbol subscribe-then-close storm.

### Pitfall 3: Poll handler regresses W1 on the backtest hot path
**What goes wrong:** adding `poll_handler.on_time` to `_routes[TIME]` runs selection/derive every
backtest tick (TimeGenerator fires TIME every bar), regressing W1/W2 even with an empty delta.
**Avoid:** guard `on_time` with a single `if self._selection_source is None: return` before any work;
measure W1 after; if measurable, wire the poll live-only (mutate the route in `start()`), leaving the
backtest `_routes` literal untouched. **Warning sign:** W1 > 15.7s baseline (adjust for thermal drift —
same-machine A/B, not frozen-baseline compare).

### Pitfall 4: Immediate unsubscribe on orphan-and-track kills the stop
**What goes wrong:** the subscribe-consumer unconditionally `provider.unsubscribe(sym)` on every
`removed` symbol; an orphaned open position then receives no bars, so its SLTP/stop never triggers and
it can never go flat.
**Root cause:** D-01 orphan-and-track requires "keep WS + ring alive until flat."
**Avoid:** the subscribe-consumer must branch on policy + open-position state — unsubscribe only when
force-close OR no open position; otherwise keep alive + mark leaving, detach on the flat-detected FILL.
**Warning sign:** an orphaned position stuck open forever with no arriving bars.

### Pitfall 5: `NotImplementedError` from a missing `_routes` entry
**What goes wrong:** `EventType.UNIVERSE_UPDATE` added but no `_routes` entry → `_dispatch` raises
`NotImplementedError` (`full_event_handler.py:138`). Backtest fail-fast aborts; live logs via
publish-and-continue.
**Avoid:** add the enum member and the route entry in the same change (Pattern 1).

### Pitfall 6: Warmup after subscribe → first live bar mis-ordered
**What goes wrong:** subscribing before warmup lets a live closed bar arrive before `L` is set from REST
history, risking a spurious gap-backfill or off-grid drop.
**Avoid:** warmup BEFORE subscribe for an added symbol (mirror `live_trading_system.py:1532-1534`
startup order). The `confirm='0'` snapshot is dropped at the provider regardless, so warmup-first makes
the first live closed bar land on the in-sequence/duplicate branch cleanly.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| OKX demo (data WS) | Live dynamic subscribe/unsubscribe test (§10) | ✓ (demo sub-account, verify `sandbox=True`) | wspap.okx.com | Paper/replay for logic; skip live-data test if creds absent |
| OKX EEA order settlement | Live force-close settlement | ✗ (MiCA whitelist, non-flat, price-floor) | — | Paper/replay `SimulatedExchange` (deterministic) |
| ccxt / aiohttp | Live path only (already installed) | ✓ | ccxt ^4.5.56 | — (lazy-imported; backtest stays free) |
| Golden CSV | Oracle + paper-parity gates | ✓ | `data/BTCUSD_1d_ohlcv_2018_2026.csv` | — |

**Missing with no fallback:** none. **Missing with fallback:** live order settlement of a dynamically
added symbol → paper/replay (accepted, Phase-5 posture inherited).

## Validation Architecture

nyquist_validation is enabled (`.planning/config.json`). Test root is `tests/` (NOT `test/`);
conftest auto-applies the type marker from folder; only `unit`/`integration`/`slow`/`e2e` markers are
registered; `filterwarnings=["error"]` + `--strict-markers`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (+ pytest-asyncio, configured `asyncio_mode` — COV-01) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run | `poetry run pytest tests/unit/universe tests/unit/events -q` (per-domain, fast) |
| Full suite | `make test` (note: aborts in worktrees on missing `.env`; use `poetry run pytest tests` in a worktree — memory) |
| Oracle gate | `poetry run pytest tests/integration/test_backtest_oracle.py` |
| Parity gate | `poetry run pytest tests/integration/test_paper_parity.py` |

### Phase Requirements → Test Map
| Req | Behavior | Test type | Automated command | Exists? |
|-----|----------|-----------|-------------------|---------|
| UNIV-01 | `Universe.apply(desired)` returns correct add/removed delta, mutates `_members` in place (identity preserved), empty-delta fast path | unit | `pytest tests/unit/universe/test_universe_apply.py -x` | ❌ Wave 0 |
| UNIV-01 | `UniverseUpdateEvent` construction (frozen, `tuple` fields) + `EventType.UNIVERSE_UPDATE` + `_routes` fan-out order | unit | `pytest tests/unit/events/test_universe_update_event.py -x` | ❌ Wave 0 |
| UNIV-01 | poll handler: source-guard early-return (backtest-inert), cadence gating, desired filtered by `validate_symbol` (D-06), emits only on non-empty delta | unit | `pytest tests/unit/screeners/test_universe_poll.py -x` | ❌ Wave 0 |
| UNIV-02 | provider `subscribe`/`unsubscribe`: registry insert/pop, spawn/cancel via connector loop, per-symbol supervisor keys | unit (async, mocked connector) | `pytest tests/unit/price/test_okx_dynamic_subscribe.py -x` | ❌ Wave 0 |
| UNIV-02 | warmup-before-subscribe ordering; snapshot (`confirm='0'`) dropped; first live closed bar lands on in-sequence/duplicate branch (no double-count) | unit | `pytest tests/unit/price/test_warmup_on_add.py -x` | ❌ Wave 0 |
| UNIV-02 | remove-policy orphan-and-track: WS/ring kept alive, new entry blocked (admission gate audited-REJECTED), detach on flat | integration (paper/replay, multi-symbol) | `pytest tests/integration/test_universe_remove_policy.py -x` | ❌ Wave 0 |
| UNIV-02 | remove-policy force-close: market exit emitted (Decimal), settles via SimulatedExchange, then detach | integration (paper/replay) | `pytest tests/integration/test_universe_force_close.py -x` | ❌ Wave 0 |
| Milestone | backtest oracle byte-exact after the change | integration | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| Milestone | paper-parity unchanged | integration | `pytest tests/integration/test_paper_parity.py -x` | ✅ exists |
| Milestone | import inertness (no ccxt/aiohttp on backtest import path) | integration | `pytest tests/integration/test_okx_inertness.py -x` | ✅ exists |
| Live (human-observed) | dynamic data subscribe/unsubscribe ETH/USDC on the demo | e2e (gated) | `pytest tests/e2e/test_okx_dynamic_universe.py -x` (verify `sandbox=True`) | ❌ Wave 0 (optional/gated) |

### Sampling Rate
- **Per task commit:** the relevant `tests/unit/...` quick command (< 5s each).
- **Per wave merge:** `poetry run pytest tests/unit tests/integration -q`.
- **Phase gate:** full suite green + oracle byte-exact + paper-parity + inertness, then `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/universe/test_universe_apply.py` — `apply()`/`UniverseDelta`/identity-preservation (UNIV-01)
- [ ] `tests/unit/events/test_universe_update_event.py` — event + enum + route (UNIV-01)
- [ ] `tests/unit/screeners/test_universe_poll.py` — poll handler cadence/guard/emit (UNIV-01)
- [ ] `tests/unit/price/test_okx_dynamic_subscribe.py` — subscribe/unsubscribe registry + spawn/cancel (UNIV-02; async, mocked connector)
- [ ] `tests/unit/price/test_warmup_on_add.py` — warmup-before-subscribe + snapshot gating (UNIV-02)
- [ ] `tests/integration/test_universe_remove_policy.py` — orphan-and-track + admission gate (UNIV-02; needs a multi-symbol replay harness/fixture)
- [ ] `tests/integration/test_universe_force_close.py` — force-close via SimulatedExchange (UNIV-02)
- [ ] Multi-symbol replay fixture/harness (a second `ReplayDataProvider` or a two-symbol driver) — shared dependency of the two integration tests
- [ ] (optional/gated) `tests/e2e/test_okx_dynamic_universe.py` — live demo data subscribe/unsubscribe
- [ ] New `OrderTriggerSource` reason (e.g. `ADMISSION_LEAVING`) — verify enum home + test the audited-REJECTED path

## Security Domain

`security_enforcement` is not explicitly `false` (treat as enabled). This phase adds no auth/session/crypto
surface; the relevant controls are input-validation and tampering on the new event/venue seams.

### Applicable ASVS Categories
| ASVS | Applies | Standard control |
|------|---------|------------------|
| V2 Authentication | no | No new auth; OKX creds already handled by `OkxSettings` |
| V3 Session | no | — |
| V4 Access Control | yes | `add_event` already refuses raw ORDER injection (`live_trading_system.py:1851`); the force-close order is engine-internal, not external |
| V5 Input Validation | yes | Desired-set filtered by `validate_symbol` (D-06); provider stamps routing keys from trusted config, not venue rows (`okx_provider.py:479`); the snapshot/malformed-row guards stay |
| V6 Cryptography | no | — |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| Non-listed / spoofed symbol proposed into the universe | Tampering | D-06 markets-map filter before `apply()`; venue reject as backstop |
| Unbounded WS subscribe storm | DoS | Poll cadence bounds add rate; per-symbol reconnect ceiling → HALT (D-20) |
| Malformed candle row on a new channel | Tampering | Existing `_process_row` length/confirm/numeric guards (`okx_provider.py:449-489`) apply per-channel |
| Force-close order injected/leaking secrets | Info disclosure | Order built from Decimal engine values; error scrub (type-only) already in the OKX arm |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | OKX business-WS allows many candle channels/connection and the subscribe op rate is well above a per-poll single add | §3 | If limits are tight, a multi-add burst could be throttled/rejected; would need explicit pacing. Low risk at this phase's N=1–2 |
| A2 | Default poll cadence 60s is appropriate for a 1d base timeframe | §4 | Wrong cadence just changes responsiveness; tunable via config — low risk |
| A3 | A single cheap `is None` source-guard per backtest TIME tick is W1-free | §11 / Pitfall 3 | If measurable, must wire the poll live-only; measure before locking |
| A4 | Dynamic **data** subscribe/unsubscribe is not gated by the MiCA whitelist / price-floor on the demo (CONTEXT D-05 asserts this; confirmed by the demo posture, not re-tested here) | §10 | If data subscribe is gated, live-data coverage falls back to paper/replay only |

## Open Questions (RESOLVED)

1. **Instrument resolution for a dynamically added symbol.** — RESOLVED: 06-01 Task 2 (default-ladder-fallback instrument resolution; the poll handler resolves precision from the venue markets map and passes it into `apply()`, keeping `Universe` connector-free).
   - Known: `derive_instruments` is wiring-time/strategy-driven and needs `price_data`; a dynamic add
     has neither.
   - Unclear: whether `apply()` receives pre-resolved `Instrument`s from the poll handler (keeping
     `Universe` connector-free, D-03) or a resolver is injected.
   - Recommendation: poll handler resolves precision from the venue markets map (reused D-06 seam) and
     passes it into `apply()`; default-ladder fallback when markets absent (paper).
2. **Flat-detection detach trigger for orphan-and-track.** — RESOLVED: 06-04 Task 2 (`on_fill` flat-detect detach via the `PortfolioReadModel` open-position count; poll-cadence re-check as backstop).
   - Known: detach must fire when the leaving symbol's position reaches flat; the FILL route is the
     natural detection point.
   - Unclear: whether the remove-policy consumer subscribes to FILL directly or the poll re-checks
     positions each cadence.
   - Recommendation: check on FILL (immediate) with a poll-cadence re-check as backstop; both read the
     `PortfolioReadModel` open-position count.
3. **Live-only vs shared TIME route for the poll handler** (Pitfall 3 / A3) — resolve by measuring W1. — RESOLVED: 06-05 Task 2 (live-only `_routes` mutation in the live-init path; the backtest `_routes` literal is left untouched — chosen over a per-tick source-guard on the shared route).

## Sources

### Primary (HIGH — read this session)
- `.planning/phases/06-dynamic-universe-membership/06-CONTEXT.md` — locked decisions D-01..D-06, canonical refs
- `.planning/REQUIREMENTS.md` — UNIV-01/UNIV-02 + milestone gate; `.planning/ROADMAP.md` Phase 6
- `itrader/universe/{universe,membership,instruments}.py` — membership owner + selection primitives
- `itrader/events_handler/events/{base,market}.py`, `itrader/core/enums/event.py`,
  `itrader/events_handler/full_event_handler.py` — event/route contract
- `itrader/price_handler/feed/live_bar_feed.py` — warmup/monotonic guard/snapshot handling
- `itrader/price_handler/providers/{okx_provider,replay_provider}.py`, `itrader/connectors/okx.py` —
  live candle socket + asyncio loop + supervisor
- `itrader/execution_handler/exchanges/okx.py` — `validate_symbol` (D-06)
- `itrader/trading_system/live_trading_system.py` — composition root, `_OKX_STREAM_SYMBOL`, paper/replay
  constants, start/initialize/processing loop/run_paper_replay
- `itrader/order_handler/admission/admission_manager.py` — admission gate plug-in point
- `.planning/config.json` — nyquist_validation enabled; CLAUDE.md — conventions

### Secondary (MEDIUM/ASSUMED)
- OKX WS subscribe rate/channel limits (A1), poll cadence default (A2) — training knowledge, flagged for
  confirmation
- External framework references (LEAN `UniverseSelectionModel`→`SecurityChanges`; Nautilus `DataEngine`
  subscription registry) — cited in CONTEXT.md as active reference; used as the no-duplication model

## Metadata

**Confidence breakdown:**
- Standard stack / seam wiring: HIGH — every module read directly; no external packages
- Coroutine lifecycle (D-05): HIGH on the spawn/cancel/registry shape (connector code verified); MEDIUM on
  rate-limit budget (A1)
- Poll timer/cadence (D-02): HIGH on the mechanism (live-only timer, no existing live TimeEvent source
  confirmed); MEDIUM on the cadence value (A2)
- Remove-policy admission gate (D-01): HIGH on the plug-in point (`process_signal` gate sequence
  verified); MEDIUM on the leaving-set/detach detail (discretion)
- Oracle-dark guarantee (§11): HIGH — empty-delta + live-only timer confirmed inert on the golden path

**Research date:** 2026-07-06
**Valid until:** ~2026-08-06 (stable in-repo; re-verify OKX WS limits if the rate-limit budget becomes load-bearing)

## RESEARCH COMPLETE

Phase 6 is pure in-repo wiring (no new packages): grow `Universe.apply→UniverseDelta` (mutate `_members`
in place), push a msgspec `UniverseUpdateEvent` (`EventType.UNIVERSE_UPDATE` + `_routes` fan-out) from a
`ScreenersHandler`-hosted poll behind a live-only clock timer, have the `OkxDataProvider` grow a
`{symbol: task}` registry with spawn/cancel subscribe/unsubscribe (warmup-before-subscribe, snapshot
already `confirm`-gated), bound selection by `OkxExchange.validate_symbol` (D-06), enforce orphan-and-track
via a new admission gate + deferred unsubscribe-until-flat — all oracle-dark by construction (single-symbol
→ empty delta → no event), with remove-policy/force-close exercised deterministically on paper/replay and
dynamic data subscription live on the OKX demo.
