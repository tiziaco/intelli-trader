# Phase 6: Dynamic Universe Membership - Context

**Gathered:** 2026-07-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a **lean universe-membership poll seam** for mid-run add/remove of symbols (NOT the full
production screener), plus the **live subscription plumbing it drives**. Reuses the Phase-3
backfill: warmup-on-add replays the new symbol's history through the identical `update(bar)`
path, and the open-position-on-remove policy is defined (configurable, default orphan-and-track).

The concrete headline for the live half: **un-hardcode the live OKX stream pair** (today
`_OKX_STREAM_SYMBOL = "BTC/USDC"`, explicitly earmarked in-code "the pair becomes configurable
via the universe subsystem in the next phase") — drive live subscriptions **dynamically from
universe membership** instead of a wiring-time constant.

**Locked by requirements (NOT re-litigated here):** UNIV-01 (lean poll seam for mid-run
add/remove, grows `universe/membership.py` per its D-20 `UniverseSelectionModel` target — NOT
the full production screener); UNIV-02 (warmup-on-add through the identical `update(bar)` path;
open-position-on-remove policy defined). This discussion settled the **HOW** on top of those.

**Recurring milestone gate (unchanged):** backtest oracle byte-exact (134 /
`46189.87730727451`); no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB). Phase 6 is
**oracle-dark by construction** — single-symbol SMA_MACD never changes membership, so the poll
returns an empty delta and the whole subsystem never fires on the golden path.

**In scope:** the lean selection/poll seam + `Universe` mutation + `UniverseUpdateEvent`
propagation + warmup-on-add + remove policy + **real live OKX dynamic subscribe/unsubscribe**
(data arm), bounded by the venue markets map.

**Out of scope (unchanged):** the full ranked production screener (volume-ranking engine, etc.)
— deferred to v2. Phase 6 ships the *lean* selection seam and the *full* dynamic-subscription
plumbing it drives, not a screening/ranking engine. Also: burst-coalescing multi-symbol
`BarEvent` (D-04 reserved seam — not needed; one `BarEvent` per arriving closed bar already
handles multi-symbol).

</domain>

<decisions>
## Implementation Decisions

### D-01 — Open-position-on-remove policy: configurable, DEFAULT orphan-and-track (Q1, UNIV-02)

On removal of a symbol that holds an open position:
- **Default (orphan-and-track):** the position stays open, its **WS subscription + ring stay
  alive** so its SLTP / exit signal can still fire normally; the engine **blocks new entries**
  for that symbol; the symbol **fully detaches only once the position is flat**.
- **Force-close (behind a policy flag):** emit a market exit for the open position at removal
  time, then detach.
- Rationale: never force a market exit at a possibly-bad price by default; the operator can
  opt into force-close per run. Orphaning implies "keep the stream running until flat" (else no
  bars arrive and the stop can never trigger).
- Plan-time: where the policy flag lives (poll-seam config vs run config), and the exact
  "block new entries for a leaving symbol" gate (likely an admission-side check against the
  leaving set). An optional force-close-after-N-bars backstop was discussed but NOT locked —
  leave to plan-time/discretion.

### D-02 — Poll trigger: clock-timer TIME route (Q2)

Wire the **dormant TIME route** (Phase-3 D-05 reserved it for exactly this): a real clock timer
fires `TimeEvent`s on a cadence **decoupled from bar delivery** (fires even on a quiet symbol;
cadence set independently of the bar timeframe). Framework-idiomatic (Nautilus clock timers /
LEAN scheduled universe selection). The TIME-route consumer is the **poll handler** — it runs
the selection, diffs, and emits (see D-04).
- Plan-time: the timer mechanism (a real clock timer on the connector/engine thread vs a
  cadence check), and the default poll cadence.

### D-03 — Seam shape: `Universe` owns mutation; the diff happens inside `Universe.apply()` (Q3)

`Universe` (`universe/universe.py`) grows a first-class mutation surface and is the **single
source of truth** for the membership set:
- `Universe.apply(desired: set[str]) -> UniverseDelta` computes `added = desired - current` and
  `removed = current - desired`, mutates `_members` **in place** (the feed reads `.members` by
  identity — Pitfall 4), updates the `instrument_map` for added/removed, and **returns the
  delta**.
- **`Universe` stays queue-free** — it computes the delta and mutates its own state; it performs
  NO subscribe/warmup/close side effects and holds NO `global_queue` reference. Side effects
  live in the event consumers (D-04). This preserves the "selection proposes / engine disposes"
  separation even though `Universe` owns the set mutation.
- Note: today `Universe` is a pure static wiring-time facade whose `.members` list is held by
  identity by the feed/exchange/order/portfolio. Giving it `apply()` is a deliberate role
  shift; it must keep `.members` byte-exact-by-identity for the feed bind.

### D-04 — Change propagation: push a `UniverseUpdateEvent` (the "hybrid" seam — Axis 1)

Membership changes reach the data provider by a **pushed event**, NOT a pull/read-model and NOT
a direct cross-domain call (respects the queue-only contract — the same reason `on_fill`
reconciles via `FillEvent`):

- New event **`UniverseUpdateEvent`** — a `msgspec.Struct` `Event` subclass (NOT a dataclass):
  ```python
  class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
      type: ClassVar[EventType] = EventType.UNIVERSE_UPDATE   # new EventType member
      added: tuple[str, ...]      # +sym → subscribe + feed.warmup
      removed: tuple[str, ...]    # −sym → unsubscribe + remove-policy
  ```
  `time` / `event_id` / `created_at` are inherited from the `Event` base. Carries the **delta**
  (added/removed), matching LEAN's `SecurityChanges.Added/Removed` — that is exactly what every
  consumer needs. `tuple[str, ...]` keeps the payload immutable on a frozen struct.
- Add `EventType.UNIVERSE_UPDATE` to `core/enums/event.py` and a route entry in
  `full_event_handler.py::_routes` (the documented three-step "new event type" flow). Route
  fans the one event to multiple consumers (list-order), like `BarEvent` does today.
- **Distinct from `ScreenerEvent`/`EventType.SCREENER`** (already exists) — that is the "propose"
  seam (screener *proposals*); `UniverseUpdateEvent` is the "dispose" notification (membership
  *actually changed*, with side effects). Keep them separate.
- **End-to-end flow:**
  1. Clock-timer TIME route fires (D-02) → poll handler runs on cadence.
  2. Poll handler asks the selection source for the desired set (bounded by D-06).
  3. `delta = universe.apply(desired)` → mutate + return `+added / −removed` (**the diff, D-03**).
  4. If delta non-empty → `global_queue.put(UniverseUpdateEvent(time, added, removed))`.
  5. Route dispatches to: (a) the **provider/feed handler** → `provider.subscribe(added)` +
     `feed.warmup(added)`; `provider.unsubscribe(removed)`; (b) the **remove-policy handler** →
     orphan-or-force-close removed symbols' open positions (D-01).

### D-05 — Add scope: FULL real live OKX dynamic subscribe/unsubscribe, sourced from the universe (Q4)

Build the **real** live plumbing, not a deferred stub:
- **Un-hardcode `_OKX_STREAM_SYMBOL`** — source the live subscription set from universe
  membership (config/universe-driven), replacing the wiring-time constant the code itself
  flagged for "the next phase."
- **`OkxDataProvider` gains dynamic `subscribe(symbol)` / `unsubscribe(symbol)`** — spawn a fresh
  `candle{tf}` coroutine on the running asyncio loop for an added symbol; cancel/`unsubscribe`
  the removed symbol's task. Today `start_stream()` subscribes exactly one wiring-time symbol and
  never changes.
- **Warmup-on-add** rides the existing `LiveBarFeed.warmup(symbol, timeframe, depth)` (already
  built in Phase 3 — replays REST history one-by-one through `update()`, no bulk fast-path).
- **The provider is a pure `UniverseUpdateEvent` consumer** — it never decides membership; it
  owns only a mechanical **subscription registry** (`{symbol: live_channel}`), which is socket
  state, not a second copy of membership. **Zero membership duplication.**
- **Data vs order settlement — the honest demo split:** subscribing/unsubscribing a candle
  channel is **pure market-data**, works on the OKX demo for any listed symbol, and is NOT gated
  by the MiCA trading whitelist or the non-flat / price-floor constraints → **dynamic live data
  subscription is genuinely testable live on the demo** (BTC/USDC ↔ ETH/USDC). **Order
  settlement** of a dynamically-added symbol (and the remove-policy force-close, an order) still
  hits the known EEA demo limits (accounts pre-seeded non-flat, sells price-floor-blocked,
  settlement e2e can't reach a fill) → that half stays exercised **deterministically on
  paper/replay**, the same posture Phase 5 already accepted for live order settlement.
- Plan-time: exact `subscribe`/`unsubscribe` coroutine lifecycle on the loop (spawn/cancel,
  per-channel supervisor), handling the **OKX snapshot-on-subscribe** quirk (OKX pushes an
  in-progress candle on every subscribe — gate it so warmup + the snapshot don't double-count or
  mis-order), and rate-limit budget across N dynamic channels.

### D-06 — Selection is bounded by the venue markets map (Q4b)

Universe selection may only propose symbols the venue actually lists. Reuse the **existing**
seam: `OkxExchange.validate_symbol()` consults `connector.client.markets` (populated by
`load_markets()` at connect — "a loaded markets map is the source of truth"). The poll's desired
set is filtered/validated against this before `universe.apply()` so a non-listed symbol is
rejected up front rather than surfacing as a venue reject at submit time.
- Plan-time: whether the poll handler calls `validate_symbol` directly or a small
  `Universe`/selection-side guard wraps it; behavior on the backtest/paper path (no live markets
  map — accept, as `validate_symbol` already does when `markets` is not a dict).

### Claude's Discretion (plan-time)
- The exact class/method split of the selection source (the lean `UniverseSelectionModel` shape
  in `membership.py`) vs the poll handler — D-03/D-04 lock the principle (pure/derived selection,
  `Universe` owns set mutation, engine does side effects) but not the file layout.
- The `UniverseDelta` return type shape and exact `added`/`removed` field types on the event
  (`tuple[str, ...]` recommended for frozen-immutability).
- Timer mechanism + default poll cadence (D-02); policy-flag home + optional force-close backstop
  (D-01); coroutine lifecycle + snapshot-gating + rate-limit details (D-05).
- Whether the poll handler is a new thin handler or grows onto an existing one (e.g.
  `ScreenersHandler`, which already holds the feed and screens on a cadence).

### Folded Todos
- **Phase-6 screening/poll cadence wiring the dormant TIME route** (Phase-3 D-05 deferral) — this
  phase's D-02 implements it.
- **Un-hardcode the live OKX pair via the universe subsystem** (in-code TODO at
  `live_trading_system.py::_OKX_STREAM_SYMBOL`) — this phase's D-05 implements it.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone design & requirements
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — the LOCKED sketch
  (LX-01..LX-15). Phase 6 = the lean poll seam; the full production screener is explicitly
  DEFERRED to v2 here.
- `.planning/ROADMAP.md` — v1.7 Phase 6 goal + success criteria (UNIV-01, UNIV-02); the recurring
  milestone gate (oracle byte-exact 134 / `46189.87730727451`; no W1/W2 regression vs 15.7 s /
  152.8 MB).
- `.planning/REQUIREMENTS.md` — UNIV-01 / UNIV-02 full text.

### Universe subsystem (the D-20 growth target — grows HERE)
- `itrader/universe/membership.py` — pure `derive_membership` / `is_active` / `active_membership`;
  the D-20 header documents the `UniverseSelectionModel` growth target ("screeners propose,
  membership disposes"). The lean selection seam grows here.
- `itrader/universe/universe.py` — `Universe` facade (`.members` held **by identity**,
  `instrument(symbol)`). D-03 adds `apply(desired) -> UniverseDelta`; MUST preserve
  `.members`-by-identity for the feed bind (Pitfall 4 / IN-02 note in the file).
- `itrader/universe/instruments.py` — `derive_instruments` (the instrument-map source for
  added symbols).

### Phase-3 warmup + feed seam (reuse — already built)
- `itrader/price_handler/feed/live_bar_feed.py` — `LiveBarFeed.warmup(symbol, timeframe, depth)`
  (the FEED-03 warmup-on-add driver, replays via `update()`), `backfill_on_resume`,
  the monotonic guard, `set_provider`/`bind`.
- `.planning/phases/03-livebarfeed/03-CONTEXT.md` — D-04 (single-ticker `BarEvent`, coalesce seam
  reserved for Phase 6 — NOT needed), **D-05 (dormant TIME route reserved as THIS poll cadence)**,
  FEED-03 warmup-through-`update()`.

### OKX connector / provider / exchange (the live subscription surface)
- `itrader/price_handler/providers/okx_provider.py` — `OkxDataProvider`: `start_stream()`,
  `_stream_candles` / `_connect_and_consume_candles` (subscribe `candle{tf}` for `instId`),
  `set_bar_sink`. D-05 adds dynamic `subscribe`/`unsubscribe` here. Note the
  **snapshot-on-subscribe** WR-03 comment (OKX pushes an in-progress candle on every subscribe).
- `itrader/connectors/okx.py` — `OkxConnector`: owns the asyncio loop + `spawn()`/`call()`,
  `load_markets()` at connect (`client.markets` = the venue allowed-tickers source of truth, D-06).
- `itrader/execution_handler/exchanges/okx.py` — `OkxExchange.validate_symbol()` (D-06 venue
  markets-map guard — REUSE, don't reimplement).
- `itrader/trading_system/live_trading_system.py` — the composition root; **`_OKX_STREAM_SYMBOL`
  hardcoded constant with the "configurable via the universe subsystem in the next phase" TODO
  (D-05 un-hardcodes it)**; `initialize()` derives membership + wires `feed.bind(universe.members)`,
  `set_universe(...)` on exchange/order/portfolio; the `PAPER_*` / `_PAPER_STREAM_*` replay
  constants (the deterministic remove/force-close test vehicle).

### Event / route contract
- `itrader/events_handler/events/base.py` — `Event(msgspec.Struct, frozen=True, kw_only=True,
  gc=False)`; `type` is a `ClassVar[EventType]`, NOT an init field (the pattern
  `UniverseUpdateEvent` follows — msgspec, not dataclass).
- `itrader/events_handler/events/market.py` — `TimeEvent`, `BarEvent`, `PortfolioUpdateEvent`,
  `ScreenerEvent` (the naming/style precedent; `ScreenerEvent` = the "propose" seam D-04 keeps
  distinct).
- `itrader/core/enums/event.py` — `EventType` (add `UNIVERSE_UPDATE`).
- `itrader/events_handler/full_event_handler.py` — `_routes` literal (dormant `EventType.SCREENER`
  / `EventType.UPDATE` empty routes; the TIME route D-02 wires; add the new UNIVERSE_UPDATE route).

### Screener handler (candidate poll-handler home)
- `itrader/screeners_handler/screeners_handler.py` — `ScreenersHandler` already holds the feed and
  `screen_markets(event)` on a cadence (`check_timeframe`) + `get_screeners_universe()`. Plausible
  home for the poll handler (Claude's-discretion, D-04/discretion).

### External framework references (used this discussion)
- LEAN `UniverseSelectionModel` → `SecurityChanges (Added/Removed)` → subscription manager (the
  D-04 delta-event model + D-03 propose/dispose split).
- Nautilus `DataEngine` subscription registry + subscribe/unsubscribe commands on the message bus
  (the provider-owns-a-subscription-registry, no-duplication model).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LiveBarFeed.warmup(symbol, tf, depth)` — the warmup-on-add machinery is **already built**
  (Phase 3, FEED-03). UNIV-02's warmup half is largely wiring, not new mechanism.
- `OkxExchange.validate_symbol()` + `connector.client.markets` — the venue allowed-tickers guard
  (D-06) already exists; reuse it.
- `Universe` facade + `derive_instruments` — the membership/instrument seam; D-03 extends it with
  `apply()` rather than building a new owner.
- `ScreenersHandler` (holds feed, cadence-screens) — candidate poll-handler host.
- `ReplayDataProvider` / `PAPER_PARITY_*` constants — the deterministic multi-symbol test vehicle
  for remove-policy + force-close (which can't settle live on the demo).

### Established Patterns
- **Queue-only cross-domain writes** — the provider learns of membership changes via
  `UniverseUpdateEvent`, never a direct call or an injected-Universe read (D-04).
- **`.members` held by identity** by the feed — `Universe.apply()` must mutate in place / keep the
  same list object (Pitfall 4).
- **Warmup/backfill through the identical `update()` path** (FEED-03, no bulk fast-path) — the
  added symbol's history replays one-by-one.
- **Data-vs-order demo asymmetry** — market-data subscription is live-testable on the demo; order
  settlement is not (Phase 5 posture inherited).
- **New event type = frozen msgspec `Event` subclass + `EventType` member + `_routes` entry**
  (the documented three-step flow).

### Integration Points
- Clock-timer TIME route → poll handler (`ScreenersHandler` or new) → `universe.apply()` →
  `global_queue.put(UniverseUpdateEvent)`.
- `UniverseUpdateEvent` consumers: provider/feed handler (`subscribe`+`warmup` / `unsubscribe`) +
  remove-policy handler (orphan/force-close).
- `OkxDataProvider.subscribe/unsubscribe` (new) ↔ `OkxConnector.spawn`/loop.
- `live_trading_system.py` composition root — un-hardcode `_OKX_STREAM_SYMBOL`; source live
  subscriptions from universe membership.

</code_context>

<specifics>
## Specific Ideas

- The live half's concrete headline is the user's own framing: **"we hardcode the BTC/USDC pair
  for the live system, but we should allow it to be dynamic"** — and the code's own TODO
  (`_OKX_STREAM_SYMBOL` "configurable via the universe subsystem in the next phase") pins this to
  Phase 6.
- The demo account provides a **second tradeable pair** (ETH/USDC alongside BTC/USDC under the
  MiCA whitelist) — the user wants dynamic add/remove proven against it live (data subscription;
  order settlement stays paper/replay-verified per the demo constraints).
- Frameworks used as active reference: **LEAN** (`UniverseSelectionModel` → `SecurityChanges`
  delta event) and **Nautilus** (`DataEngine` subscription registry + subscribe/unsubscribe
  commands) — both confirm the no-duplication model: one membership owner, a diff, and a
  data-layer subscription registry that follows it.
- User's guiding constraint throughout: **avoid duplicating the membership logic in two places** —
  resolved by D-03/D-04 (Universe = truth + diff; provider = derived socket registry, event-driven).

</specifics>

<deferred>
## Deferred Ideas

- **Full ranked production screener** (volume/liquidity ranking engine, cross-sectional
  selection) — v2. Phase 6 ships only the lean selection seam + the dynamic-subscription plumbing.
- **Burst-coalescing multi-symbol `BarEvent`** (D-04 reserved seam) — NOT needed; one `BarEvent`
  per arriving closed bar already handles multi-symbol. Lands only if/when cross-sectional
  screening arrives.
- **Live order-settlement of dynamically-added symbols on OKX** (and live force-close settlement)
  — blocked by the EEA demo constraints (non-flat accounts, price-floor); verified on paper/replay
  in Phase 6, live-settlement follow-on when a flat/non-EEA account is available.
- **Force-close-after-N-bars backstop** for orphaned positions — discussed, not locked; plan-time
  may add it under the D-01 policy flag.

### Reviewed Todos (not folded)
None — discussion stayed within phase scope.

</deferred>

---

*Phase: 6-dynamic-universe-membership*
*Context gathered: 2026-07-06*
