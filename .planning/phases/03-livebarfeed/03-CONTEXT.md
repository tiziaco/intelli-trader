# Phase 3: LiveBarFeed - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Build `LiveBarFeed` — a ring-buffer `BarFeed` implementation that consumes the Phase-2
`OkxDataProvider` data arm, emits a `BarEvent` **only on a completed bar** (`confirm == 1`)
with venue bar-open `time`, replays warmup/gap backfill **one-by-one through the identical
`update(bar)` path**, enforces **monotonic-forward-only** delivery, and replaces
`TimeGenerator`'s role on the live path. All live/streaming machinery is **inert on the
backtest hot path** (oracle byte-exact, no W1/W2 regression).

**Locked by requirements (NOT re-litigated here):** FEED-01 (ring = bounded `deque(maxlen)`
per `(symbol, timeframe)`, capacity from `cache_capacity()`); FEED-02 (emit only on
`confirm == 1`, bar `time` = venue bar-open stamp, 7-rule look-ahead contract holds); FEED-03
(warmup/backfill through the identical `update(bar)` path, no bulk `warmup_from()` fast-path);
FEED-04 (monotonic-forward-only: gap → backfill-replay; duplicate → drop; stale/out-of-order →
reject); FEED-05 (replaces `TimeGenerator`, preserving TIME-before-BAR route ordering
downstream). This discussion settled the **plan-time-flagged HOW** on top of those.

</domain>

<decisions>
## Implementation Decisions

### Provider→Feed seam (FEED-01/02/03)

- **D-01 — Ingestion entry point is `update(closed_bar: ClosedBar)`** (a dict). Phase-2's
  `OkxDataProvider.set_bar_sink(Callable[[ClosedBar], None])` push-callback already hands the
  feed a raw **confirm-gated** `ClosedBar` dict with **money already Decimal** (`to_money` at
  the provider edge). The **feed owns `Bar` construction** from that dict and appends to the
  ring — matching Phase-2 D-05's "the feed owns BarEvent construction and the ring buffer."
  Not `update(Bar)` (avoids deciding where dict→Bar happens) and not `update(symbol, tf, bar)`
  (the dict already carries the routing keys). Push, not pull; the provider gates `confirm`,
  the feed builds the `Bar`.

### Emission model / TimeGenerator replacement (FEED-05) — **Option B (bar-direct)**

- **D-02 — `update()` emits directly onto `global_queue`** (the bar's ARRIVAL is the event).
  `update(closed_bar)` validates monotonicity → constructs the `Bar` → appends to the ring →
  writes `newest_bar` → **puts a `BarEvent` straight on the queue**. The feed is the live
  event source, fully replacing `TimeGenerator`'s for-loop. Emission may physically fire from
  the connector's asyncio thread (`queue.Queue` is MPSC-safe; **D-19 single-writer preserved**
  — portfolio state still mutates only on the engine thread).

- **D-03 — Live emits `BarEvent` DIRECTLY to the BAR route (Option B), NOT via a
  `TimeEvent`→`generate_bar_event` pull (Option A rejected for live).** This is the
  framework-idiomatic model — Nautilus/LEAN/backtrader all deliver a bar straight to the bar
  handler; the *driver* differs (loop vs socket), the *handler* is shared. Numerically
  parity-safe for the milestone because the TIME route is a no-op today (`screen_markets`
  empty). **Deliberate, temporary asymmetry:** backtest keeps its `TimeEvent`→pull model
  (D-20) for now; unifying backtest is deferred (see Deferred → `unify-backtest-direct-bar-generation`).

- **D-04 — Single-ticker `BarEvent` payload, coalesce-seam reserved.** `update()` emits
  `BarEvent(time, bars={that_ticker: bar})` — **one event per arriving closed bar**. Live bars
  arrive per-symbol from the socket (a burst at the boundary, confirmed by the legacy
  `binance_stream.py` `_closed == 5` batching), never atomically aligned; coalescing would
  need an arbitrary debounce/quorum with a halt-symbol failure mode → rejected. Zero
  queue-overload risk (closed bars fire once per timeframe-period per symbol; forming
  `confirm==0` pushes are dropped at the provider and never queued). **Shape the `update`/emit
  seam so a burst-coalescing consolidator can slot in at Phase 6 (dynamic universe) WITHOUT
  changing the `BarEvent` contract.** SMA_MACD is single-symbol → this is exactly sufficient
  for the paper-parity gate.

- **D-05 — TIME route / `TimeEvent` / `screen_markets` preserved but DORMANT on the live path.**
  Phase 3 does not route bars through them. They are **reserved as the Phase-6 screening/poll
  cadence** — a real clock tick (fire on a cadence), decoupled from bar delivery (à la Nautilus
  clock timers / LEAN scheduled universe selection). Phase 3's obligation is only "don't break
  the seam"; Phase 6 wires the poll (`screen_markets` re-ranks off the ring, subscribes new
  symbols, warms them up via the identical `update()` path). Look-ahead safety holds
  (screener reads completed bars only; warmup-on-add precedes a new symbol's live bars).

### Gap, revision & reconnect policy (FEED-04)

- **D-06 — Full classification taxonomy is built into the monotonic guard** (this is part of
  FEED-04, required regardless of policy). For an incoming closed bar with last-delivered time
  `L` for `(symbol, timeframe)`:
  | Incoming `t` vs `L` | Case | Reaction |
  |---|---|---|
  | `t == L + tf` | in-sequence | deliver |
  | `t > L + tf` (hole) | **gap** | REST-backfill `[L+tf … t-tf]`, replay each via `update()`, then deliver `t` |
  | `t == L`, values identical | **duplicate** | drop (quiet/debug) |
  | `t == L`, values differ | **revision** | forward-only: WARN old/new, drop, NO state mutation |
  | `t < L` | **stale / out-of-order** | reject + log |
  Detecting a revision is cheap (one value-comparison riding the timestamp guard) and is
  needed to tell a revision from a plain duplicate.

- **D-07 — Bar-correction reaction = forward-only + log (re-warm REJECTED).** A revision to an
  already-delivered/closed period is dropped-and-warned; indicator state is never rewound.
  Matches Nautilus (`data/engine.pyx`: revisions honored only for the *latest* bar; historical
  revisions warn-and-drop; no re-warm) and LEAN. The `confirm==1` gate means we never deliver a
  *forming* bar to revise, so Nautilus's "replace latest bar in place" case essentially never
  arises. Account-level reconciliation (Phase 5) is the safety net for real divergence, not
  indicator rewind. Deterministic and simplest.

- **D-08 — Reconnect recovery = proactive backfill-on-reconnect, gated by a completed-bar
  BOUNDARY check** (not raw outage duration — a short outage can still straddle a bar close,
  e.g. a 30s drop across the 1d midnight boundary). On socket resume: if the most-recent
  completed-bar open-time `> L`, REST-backfill `[L+tf … latest completed]` and replay
  one-by-one through the same `update()` gap path (FEED-03); else do nothing. Chosen over pure
  passive gap-driven because on slow timeframes (1d) waiting for the next live bar could take a
  day. Composes safely with the resumed stream — a re-sent bar is dropped by the **duplicate**
  branch, so no double-delivery. Socket-level reconnect/backoff is the connector's job (Phase 2);
  RES-01 hardening is Phase 5's home.

### Capacity & warmup depth (FEED-01/03)

- **D-09 — Ring `maxlen` = `BarFeed.cache_capacity()`** — the same wiring-time derivation as
  backtest (P5-D16: purely derived from registered raw-bar consumers' `required_history_depth`,
  never hand-set). `LiveBarFeed` keys a `deque(maxlen=cache_capacity())` per `(symbol,
  timeframe)`. One source of truth for sizing → parity with backtest.

- **D-10 — Warmup depth `K = cache_capacity() + safety margin`.** Fetch enough to fill the ring
  so BOTH warmups (spec §10.D-2: cache hydration AND stateful-indicator readiness) are satisfied
  by the same one-by-one replay through `update()`. The margin absorbs REST boundary-bar dedup
  and ensures indicators are fully settled on the first live bar. (Plan-time: pick the exact
  margin — e.g. a small fixed +N or a modest multiplier.)

### Multi-timeframe handling (FEED-01) — **Option A (base-tf stream + pull-resample)**

- **D-11 — Live serves multiple timeframes by base-timeframe stream + pull-resample (backtest
  parity), NOT native tagged multi-tf.** Live subscribes the **finest needed** timeframe as the
  SINGLE `BarEvent` stream; higher timeframes are pulled via `feed.window(ticker, tf)`,
  resampled from the ring — **identical to backtest**. 5m and 15m are NOT separate events; if
  base is 5m, the strategy gets 5m BarEvents and calls `window(ticker, 15m)` for the higher tf.
  **No timeframe tag added to `Bar`/`BarEvent`** (neither carries one today) → no schema change,
  live≡backtest parity preserved, reuses existing `window()`/`_resampled_frame`. Multi-tf
  strategies (e.g. 5m signal + 1h filter) work exactly as in backtest. Native tagged multi-tf
  (Nautilus model) is architecturally superior but only coherent if backtest adopts it too
  (else higher-tf bars diverge and parity breaks) → **deferred** (see Deferred →
  `native-tagged-multi-timeframe`). Golden SMA_MACD (BTCUSD, 1d) is the N=1 case.

### Claude's Discretion (plan-time)
- Exact `Bar` construction path from the `ClosedBar` dict inside `update()`.
- Exact warmup safety-margin value (D-10).
- Exact thread-hand-off mechanism for the asyncio-thread `update()` → `queue.Queue` put
  (D-02/D-19) — the queue is MPSC-safe; pick the minimal safe form.
- Whether the per-`(symbol, timeframe)` ring dict and the monotonic-guard `L` tracking share
  one structure or two.

### Folded Todos
- **`live-backfill-through-update.md`** — the FEED-03 "replay through the identical `update()`
  path, no bulk fast-path" rule is this phase's core warmup mechanism (D-06/D-08/D-10 all route
  replay through `update()`). Directly in scope; this phase implements it.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone design & requirements
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LOCKED LX-07..LX-10,
  LX-12, LX-13, LX-15. Read §"3. The parity spine" (bar-close detection LX-08, backfill LX-09,
  monotonic LX-10) + LX-15 (runtime topology, the Phase 3→4 handoff item).
- `.planning/ROADMAP.md` — v1.7 Phase 3 goal + success criteria (FEED-01..05), the recurring
  milestone gate (oracle byte-exact 134 / `46189.87730727451`; no W1/W2 regression vs 15.7s /
  152.8MB).
- `.planning/REQUIREMENTS.md` — FEED-01..05 full text; RES-01 (websocket reconnect + gap
  recovery, home Phase 5, builds here).

### Phase-2 seam (build against this — the data arm is done)
- `itrader/price_handler/providers/okx_provider.py` — `OkxDataProvider`: `set_bar_sink`,
  `ClosedBar` TypedDict (confirm-gated, Decimal), `fetch_ohlcv_backfill(...) -> list[ClosedBar]`
  (the warmup source), native `/business` `confirm==1` gate. **This is the exact provider→feed
  seam Phase 3 consumes.**
- `.planning/phases/02-okx-connector/02-CONTEXT.md` — D-01/D-03/D-04/D-05 (data arm shape, DI,
  the deferred provider→feed seam co-shape now resolved by D-01 above).

### The BarFeed contract Phase 3 implements
- `itrader/price_handler/feed/base.py` — `BarFeed` ABC: `current_bars`, `window`, `megaframe`,
  `newest_bar`, `register_raw_bar_consumer`, `cache_capacity` (D-09/D-10 sizing source).
- `itrader/price_handler/feed/bar_feed.py` — `BacktestBarFeed` reference: the 7-rule bar-timing
  contract (header), `generate_bar_event`, `current_bars` (G5 newest-bar unify), `window` /
  `_resampled_frame` (the D-11 pull-resample path). Match its look-ahead enforcement.
- `itrader/price_handler/feed/cache_registration.py` — `derive` (the `cache_capacity` backend).

### Event / route contract
- `itrader/events_handler/events/market.py` — `TimeEvent`, `BarEvent(time, bars: dict[str, Bar])`
  (NO timeframe field — the D-11 fact).
- `itrader/core/bar.py` — `Bar` (msgspec Struct, Decimal OHLCV, NO timeframe field).
- `itrader/events_handler/full_event_handler.py` — the `_routes` TIME/BAR literal (D-05 dormant
  TIME route; D-02/D-03 direct-to-BAR emission).
- `itrader/trading_system/simulation/time_generator.py` — `TimeGenerator` (the backtest source
  D-03 diverges from; FEED-05 replaces its role live).
- `itrader/trading_system/live_trading_system.py` — composition root; currently wires
  `BacktestBarFeed` as a placeholder (lines ~100-114, ~376) — Phase 3 swaps in `LiveBarFeed`.

### Legacy reference (informative, not a build target)
- `itrader/price_handler/providers/binance_stream.py` — quarantined legacy streamer;
  confirms per-symbol burst arrival at the boundary + the `_closed == 5` coalescing hack
  (informs D-04). NOT imported on any run path.

### External framework references (verified this discussion)
- nautilus-trader `common/actor.pyx::handle_bar` (bar-direct → `on_bar`), `data/engine.pyx`
  (revision policy: latest-bar-only replace, historical revision warn-and-drop — informs D-07),
  `model/data.pyx` (`BarType`/`Bar` tagged identity — the deferred D-11 alternative).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OkxDataProvider` (Phase 2) — `set_bar_sink` push seam + `ClosedBar` + `fetch_ohlcv_backfill`
  give Phase 3 both the live stream and the warmup/gap source, pre-Decimal'd.
- `BarFeed` ABC + `BacktestBarFeed` — `LiveBarFeed` implements the same ABC; `cache_capacity()`
  (D-09/D-10) and `window()`/`_resampled_frame` (D-11 pull-resample) are inherited/mirrored.
- `cache_registration.derive` — the capacity derivation (never hand-set).
- `queue.Queue` (MPSC-safe) — direct emission from the asyncio thread (D-02, D-19 preserved).

### Established Patterns
- **Look-ahead contract lives in the feed only** (7-rule, `bar_feed.py`) — `LiveBarFeed` must
  enforce it in its window slice, never in strategies (M5-01).
- **Bar-open `time`, never wall-clock** (D-04 / determinism) — bar `time` from the venue stamp.
- **Push producers, single-writer state** (D-19) — many queue producers OK; portfolio mutates
  only on the engine thread via `on_fill`/route handlers.
- **DI at the composition root** — `LiveTradingSystem.__init__` swaps `BacktestBarFeed` →
  `LiveBarFeed`, wires the provider sink to `feed.update`.

### Integration Points
- `OkxDataProvider.set_bar_sink(feed.update)` — the provider→feed wire (composition root).
- `LiveBarFeed` → `global_queue` — emits `BarEvent` directly (D-02/D-03).
- `LiveTradingSystem` — replaces the placeholder `BacktestBarFeed`; TIME route left dormant (D-05).
- `feed.window(ticker, tf)` — strategies pull higher timeframes (D-11), unchanged consumers.

</code_context>

<specifics>
## Specific Ideas

- Frameworks were used as active reference this discussion: **Nautilus** for bar-direct emission
  (D-03), revision policy (D-07), and the tagged-multi-tf target (D-11 deferred); the user's own
  **legacy `binance_stream.py`** for the per-symbol burst-arrival reality (D-04).
- User's stated architectural view: native tagged multi-tf (D-11 Option B) is "more correct /
  more robust" and worth doing eventually — captured as a deferred todo, not forced into Phase 3.
- User explicitly wants the backtest event loop eventually unified to the same bar-direct model
  (D-03) — captured as a deferred todo.

</specifics>

<deferred>
## Deferred Ideas

- **Unify the backtest loop to direct bar generation** (bar-direct, drop `TimeEvent`→pull) —
  `.planning/todos/unify-backtest-direct-bar-generation.md`. Resolves the deliberate D-03
  backtest/live asymmetry; a post-v1.7 oracle-gated refactor.
- **Native tagged multi-timeframe** (timeframe as part of `Bar` identity, native per-tf events,
  unified across backtest+live) — `.planning/todos/native-tagged-multi-timeframe.md`. The
  architecturally-superior D-11 alternative; the live half of the multi-tf-consolidator todo.
- **Burst-coalescing multi-symbol `BarEvent`** — enabled by the D-04 reserved seam; lands with
  Phase 6 dynamic universe (cross-sectional screening).
- **Phase-6 screening/poll cadence** wiring the dormant TIME route (D-05) — Phase 6.
- **RES-01 reconnect/backoff hardening** — Phase 5 (D-08 ships the gap-driven recovery here).

These are all the milestone's own downstream phases / captured todos — not scope creep.

### Reviewed Todos (not folded)
- **`multi-timeframe-consolidator.md`** — reviewed; NOT folded. It's the backtest/aggregation
  half of multi-tf support (spec §10.G); the live half is captured in the new
  `native-tagged-multi-timeframe.md` todo. Both deferred together, out of Phase-3 scope.

</deferred>

---

*Phase: 3-livebarfeed*
*Context gathered: 2026-07-01*
