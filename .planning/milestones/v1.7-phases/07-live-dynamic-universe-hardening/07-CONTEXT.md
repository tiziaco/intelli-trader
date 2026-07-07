# Phase 7: Live Dynamic-Universe Hardening - Context

**Gathered:** 2026-07-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the Phase-6 dynamic-universe membership path against the five routed findings from the
Phase-6 code review (`06-REVIEW.md` + `06-REVIEW-DECISIONS.md`): **WR-01, WR-02, WR-04, WR-05,
WR-06**. Centerpiece is **WR-02** — replace the synchronous commit-then-effect warmup with an
**async warmup + per-symbol `isReady` readiness gate** (LEAN/Nautilus model: "activated &
data-ready", not merely "selected", is what the engine keys on).

**Additional in-scope seam surfaced this discussion (fits the same machinery):** an
**operator-driven `add_ticker`/`remove_ticker` on a live strategy**, propagating through the
identical readiness-gated warmup path — the *strategy-edit → universe* direction (the reverse of
*poll → universe*). This makes the Phase-6 `StaticUniverseSelectionModel` ("operator-driven")
docstring real. The UI/FastAPI transport that *calls* it stays deferred to the app-layer plan.

**Recurring milestone gate (unchanged):** backtest oracle byte-exact (134 / `46189.87730727451`);
no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB). Phase 7 is **oracle-inert by
construction** — the backtest path never polls, never mutates membership, and a backtest member is
always ready; every gate is a live-only no-op on the golden path.

**In scope:** the WR-02 readiness gate + async warmup redesign; WR-01 keep-until-flat invariant
(re-expressed on the new state model); WR-04 markets-map precision resolver seam; WR-05 HALT/pause
poll gating; WR-06 dedicated `UNIVERSE_POLL` route; the `StrategyCommandEvent` + `add_event`
allowlist-hardening + strategy-derived selection source.

**Out of scope (deferred):** the UI/FastAPI endpoint that calls `add_ticker` (app-layer plan);
full universe-driven strategy scope (LEAN `OnSecuritiesChanged` model — arrives with the screener,
a future phase); the mutable-`Instrument` refactor (todo captured).

</domain>

<decisions>
## Implementation Decisions

### WR-02 — Readiness gate: representation & enforcement (centerpiece)

- **D-01 — Explicit membership-layer gate.** Readiness is a first-class per-symbol fact the engine
  keys on (LEAN `IsReady` / Nautilus `initialized`), NOT a silent data-absence. Consumers that
  iterate membership check `universe.is_ready(sym)` explicitly. **Admission** is the primary gate
  consumer (a `pending` symbol cannot be traded via a bypassing external `OrderEvent`); the strategy
  loop carries a cheap defensive check. **`feed.window()` keeps RAISING `MissingPriceDataError`** as
  the loud backstop — softening it to return-empty would mask a real data gap as "warming"
  (silent-wrong-number, the trap WR-01 rejected the default-instrument fallback for).

- **D-02 — Readiness state lives on `Universe` as ONE record map (LEAN `Security` model).** Replace
  `Universe._instruments: dict[str, Instrument]` with `_entries: dict[str, TrackedInstrument]`.
  `TrackedInstrument` is a **mutable** (`@dataclass(slots=True)`, NOT frozen) record that wraps the
  **existing frozen `Instrument` by reference** and adds `readiness: Readiness`
  (`PENDING`/`READY`/`FAILED`) + `leaving: bool`. `is_ready(sym)` and `instrument(sym)` read the
  record. `_members` stays the identity-bound `list` (feed binds it by identity, Pitfall 4). ONE map
  to manage on every add/remove — no parallel instrument-vs-readiness sync. `Instrument` itself is
  **untouched** this phase. Name `TrackedInstrument` is a placeholder (see deferred todo).
  Rationale: LEAN keeps immutable `SymbolProperties` distinct from the mutable `Security` that
  carries `IsReady`; Nautilus keeps the immutable `Instrument` in the Cache separate from runtime
  readiness. A separate `_ready` map would be a second symbol-keyed structure to desync — the
  WR-01 bug class.

### WR-02 — Async warmup execution (single-writer safe)

- **D-03 — Async fetch → single `BarsLoaded` event → `StrategiesHandler` warms; single-writer
  preserved.** The connector loop does ONLY the REST fetch (I/O, no state). It hands **all** fetched
  bars back to the engine thread via ONE `BarsLoaded(symbol, timeframe, bars)` event (NOT K events —
  no flood). `StrategiesHandler.on_bars_loaded` loops them into the **concerned strategies** (those
  whose `.tickers` include the symbol) via the identical `strategy.update(ticker, bar)` path — **no
  `generate_signal`** during warmup. The provider stays feed-side; **strategies stay pure event
  consumers** (no provider handle — preserves the no-cross-domain-refs convention). Matches Nautilus
  `request_bars → on_historical_data` (bulk transport, sequential apply) and LEAN `History()` +
  `WarmUpIndicator` (bulk fetch, per-bar `indicator.Update`).

- **D-03a — The per-bar loop is intrinsic, NOT designed away.** Stateful indicators are O(1)
  recurrences (`ema_t` from `ema_{t-1}`); warming requires sequential in-order application. A
  bulk/vectorized load would be a *second computation path* that can drift from the incremental
  recurrence — the exact LX-09 "no bulk fast-path" divergence trap that re-opens the parity gate.
  So: bulk *transport* (one event), sequential *apply* (the loop).

- **D-03b — Ready flip is simple (no "first live bar" trick).** Because warmup emits **no** tradeable
  `BarEvent`s (direct `update()`, no signals), there is no stale-bar hazard. The `BarsLoaded`
  handler warms → `universe.mark_ready(sym)` → `provider.subscribe(sym)`, in that deterministic
  engine-thread order. By the time the first *live* `BarEvent` arrives, `is_ready` is already true.

- **D-03c — Membership-ready ⇒ indicator-ready by construction.** Warmup depth
  `K = cache_capacity() + _WARMUP_MARGIN` is derived ≥ the deepest declared indicator warmup, so
  after `BarsLoaded` the concerned strategies' indicators are warm. The two gates
  (`universe.is_ready` + `strategy.is_ready`) compose in the strategy loop:
  `update()` always → `universe.is_ready` (warm-but-don't-trade while pending) → `strategy.is_ready`
  (indicator warmth) → `generate_signal`.

### WR-02 — Warmup failure recovery

- **D-04 — Isolate + stay pending + retry next poll.** Per-symbol isolation (one failure never
  aborts the batch or the remove branch — fixes the naked-remove-branch bug). On failure the async
  task emits **`BarsLoadFailed(symbol, reason)`** → `UniverseHandler` marks `FAILED` (readiness gate
  keeps it dark — no `MissingPriceDataError` window ever opens). NOT rollback-out-of-membership
  (the 06-REVIEW stopgap predates the gate; with the gate, rollback is redundant churn). Two
  distinct events (`BarsLoaded` success / `BarsLoadFailed` failure) so neither consumer branches on
  status.

- **D-05 — Unbounded retry, re-filtered by `validate_symbol`.** Retry every poll with no cap; kept
  cheap because the D-06 venue markets-map guard (`validate_symbol`) filters the desired set BEFORE
  `apply`, so a truly delisted symbol drops out of `desired` at the source and stops being retried.
  Each failed attempt logs a warning. Cap/backoff deferred unless REST budget proves a problem.

### WR-05 + WR-06 — Poll routing & HALT gating (settled jointly)

- **D-06 — Dedicated `EventType.UNIVERSE_POLL` discriminator (WR-06 option A).** New enum member +
  single-handler route → `UniverseHandler.on_poll` (the documented 3-step new-event flow, same as
  Phase 6's `UNIVERSE_UPDATE`). The business `TIME` route is left to screeners/bar-gen only. NOT
  option B (timer→handler direct call — reintroduces the forbidden cross-domain call). Matches
  Nautilus clock-timer typed events + LEAN `Schedule.On` separate-from-`OnData`.

- **D-07 — Skip during freeze (WR-05).** Membership is **level-triggered** (`apply(desired)` diffs
  desired vs current), so a poll skipped during HALT/pause **self-heals** on the next tick after
  unfreeze. The gate is an early-return at the top of `on_poll` when `is_halted or
  is_submission_paused`. NO replay/buffering (edge-triggered thinking on a level-triggered signal;
  contradicts freeze-in-place). Because the route is dedicated (D-06), WR-05's "where to gate"
  collapses into gating `on_poll`.

- **D-08 — Bound the cadence (WR-03 fold-in).** `universe_poll_cadence_s` gets `Field(gt=0.0)`,
  **fail-loud at config load** (not silent clamp).

### Operator strategy-ticker seam (new — strategy-edit → universe)

- **D-09 — `StrategyCommandEvent` (command-in, strategy-subject).** Verbs `add_ticker` /
  `remove_ticker` now; designed to grow `enable`/`disable`/`reconfigure` (subsumes the
  `update_config` D-11 surface later). Construction via **factory classmethods**
  (`StrategyCommandEvent.add_ticker(name, sym)`) per the codebase `new_*` convention — NO wrapper
  method on `LiveTradingSystem`.

- **D-10 — Single external ingress, allowlist-hardened (`add_event`, D-18 inversion).** The existing
  `LiveTradingSystem.add_event` (the D-18 external/web surface) is **inverted from denylist to
  allowlist (fail-open → fail-closed)**. Today it rejects `EventType.ORDER` and admits everything
  else (any new internal-fact type is admitted by default). Replace with a module constant
  `_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})` — admit ONLY
  sanctioned commands, reject everything else by default (`FillEvent`, `BarEvent`,
  `UniverseUpdateEvent`, `UNIVERSE_POLL`, `BarsLoaded/Failed`, `TimeEvent`, `PortfolioUpdateEvent`,
  `ErrorEvent` — all internal-only). Default-deny is the correct posture for the ASVS V4/V5 boundary
  the docstring already cites. `add_ticker`/`remove_ticker` are NOT methods anywhere — callers do
  `engine.add_event(StrategyCommandEvent.add_ticker(...))`. Plan-time: audit existing `add_event`
  callers so the allowlist doesn't break a legitimate one; a unit test asserts each internal-fact
  type is rejected.

- **D-11 — Handling by route fan-out → emit, don't fan-out to Universe.** `StrategyCommandEvent` →
  `StrategiesHandler.on_strategy_command` (mutate `strategy.tickers` — the command's domain meaning
  lives in the strategy handler, NOT `LiveTradingSystem`). It then **emits `UNIVERSE_POLL`** (an
  immediate off-cadence re-select). `UniverseHandler.on_poll` runs the strategy-derived selection
  (now reflecting the edit) → `apply` → `UniverseUpdateEvent` → readiness-gated subscribe/warmup.
  Emit-a-follow-on-event beats a two-consumer fan-out: explicit causal ordering (mutate
  happens-before re-select, not route-order-dependent) + decoupling (`UniverseHandler` never sees
  `StrategyCommandEvent`). Matches Nautilus (`subscribe_bars` emits a `Subscribe` command the
  DataEngine reacts to) + LEAN (`AddCrypto` → `OnSecuritiesChanged` notification). **Cadence timer
  and strategy commands both emit `UNIVERSE_POLL`** — one selection path, two triggers (inherits
  WR-05 gating for free). No loop; `apply()` idempotent (level-triggered).

- **D-12 — Strategy-derived selection source (replaces the frozen snapshot).** Swap the wiring-time
  `StaticUniverseSelectionModel(fixed_set)` for a source that reads `get_strategies_universe()` /
  `derive_membership(strategies)` **live** each `select()`, so ticker edits propagate. Oracle-safe:
  backtest never polls; SMA_MACD's tickers are construction-fixed and never mutated (the swap is
  inert on the golden path). Removals flow through the existing D-01 orphan/force-close remove policy.

### WR-01 — Keep-until-flat invariant × TrackedInstrument (re-expressed on the new model)

- **D-13 — `apply()` stops popping removed symbols; teardown moves to detach-on-flat.** The old
  `for sym in removed: _instruments.pop()` loop is deleted — a removed-but-held symbol keeps its
  whole `TrackedInstrument` record. `apply()` mutates only `_members`. Instrument teardown = a
  single `Universe.discard_instrument(sym)` = `_entries.pop(sym)` at the two final-teardown points in
  `UniverseHandler` (`_on_symbol_removed` no-holder branch + `on_fill` detach-on-flat). Because
  instrument + readiness + `leaving` live on ONE record, the pop tears all three down **atomically**
  — the WR-01 desync bug class is eliminated by construction (the single-record model IMPROVES on the
  original separate-map WR-01 decision).

- **D-14 — Add-branch clobber guard, with the re-add-of-held property.** `if sym not in _entries:`
  fresh add → new record `readiness=PENDING` (warmup). `else:` a re-add of a still-held (leaving)
  symbol clears `leaving=False`, **keeps `readiness=READY`, NO re-warmup** — under orphan-and-track
  its stream stayed alive so data never lapsed. A fully-detached (record-discarded) symbol re-adds as
  a fresh `PENDING`.

- **D-15 — `_leaving` folds into the record; readiness ⟂ leaving (orthogonal).** The old `_leaving`
  set becomes `TrackedInstrument.leaving`; `mark_leaving`/`clear_leaving`/`leaving_symbols()` operate
  on records. `readiness` = "has data" (so an orphaned position's exit/SLTP still fires); `leaving` =
  "no new entries, winding down." Admission reads `leaving`; the strategy/window path reads
  `readiness`. (Force-close tears the stream down at removal, so its record's readiness may go stale
  during wind-down — inert: exit already emitted, `leaving` blocks entries, detach-on-flat discards
  the record shortly after.)

### WR-04 — Markets-map precision resolver (leaning confirmed)

- **D-16 — Inject a markets-map/precision resolver into `UniverseHandler` (WR-06-review option A).**
  Poll-added symbols resolve venue-correct precision via an injected resolver (built at the
  composition root from the OKX markets map, same source as `derive_instruments`), so `apply` gets a
  real `instruments`/precision dict instead of the `_DEFAULT_*` 2dp/8dp ladder. `Universe` stays
  connector-free (D-03 — it still just receives resolved data). Backtest/paper path: no live markets
  map → default ladder (paper-correct), same as `validate_symbol` today. Roadmap SC3 states this as
  the direction.

### Claude's Discretion (plan-time)
- Exact `TrackedInstrument` field/method layout and the `Readiness` enum home.
- The `BarsLoaded` / `BarsLoadFailed` event field shapes; whether `BarsLoaded` also fans out to the
  feed ring (contingent on the ring-consumer research flag below).
- Whether the strategy-ticker edit rides the existing `update_config` D-11 between-cycle mechanism vs
  the new `StrategyCommandEvent` (default: new event; D-11 is the reuse candidate to check).
- Per-symbol warmup fetch depth when multiple strategies with different declared warmups share a
  symbol (max across concerned strategies).
- The markets-map resolver's exact interface (reuse `OkxExchange.validate_symbol`'s markets source
  vs a dedicated `MarketsMap` protocol) and composition-root wiring.
- Timer mechanism for the `UNIVERSE_POLL` cadence + default cadence value.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-6 review — the source of every finding (READ FIRST)
- `.planning/phases/06-dynamic-universe-membership/06-REVIEW.md` — the five findings' full text.
- `.planning/phases/06-dynamic-universe-membership/06-REVIEW-DECISIONS.md` — WR-01 decided
  (keep-until-flat option A); WR-02 escalated to async warmup + `isReady` (centerpiece); WR-04/05/06
  leanings that this CONTEXT finalizes.
- `.planning/phases/06-dynamic-universe-membership/06-CONTEXT.md` — Phase-6 D-01..D-06 (remove
  policy, poll trigger, `Universe.apply`, `UniverseUpdateEvent`, dynamic subscribe, markets-map
  bound) that Phase 7 hardens.

### Milestone gate & requirements
- `.planning/ROADMAP.md` — v1.7 Phase 7 goal + 6 success criteria; recurring gate (oracle byte-exact
  134 / `46189.87730727451`; no W1/W2 regression vs 15.7 s / 152.8 MB).
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LOCKED sketch (LX-09
  warmup-through-identical-`update()`-path, no bulk fast-path — load-bearing for D-03/D-03a).

### Universe subsystem (grows HERE)
- `itrader/universe/universe.py` — `Universe`: `_members` (identity-bound list, Pitfall 4),
  `_instruments`→`_entries` (D-02 TrackedInstrument), `apply()` (D-13 stop-popping), `_leaving`
  (D-15 fold-in), `mark_leaving`/`clear_leaving`/`leaving_symbols`.
- `itrader/universe/universe_handler.py` — `on_poll` (D-06 renamed target), `on_universe_update`
  (add/remove branches), `_on_symbol_removed` (D-13 teardown point), `on_fill` detach-on-flat (D-13
  teardown point), `set_selection_source` (D-12 swap).
- `itrader/universe/membership.py` — `derive_membership` (D-12 strategy-derived source),
  `UniverseSelectionModel` Protocol, `StaticUniverseSelectionModel` (the frozen source D-12 replaces).
- `itrader/universe/instruments.py` — `derive_instruments` (WR-04 D-16 precision source).
- `itrader/core/instrument.py` — the frozen `Instrument` (UNTOUCHED this phase; D-02 wraps it).

### Warmup / feed seam
- `itrader/price_handler/feed/live_bar_feed.py` — `warmup()` (D-03 async fetch source),
  `update()`/`_deliver()`/`_emit()` (emits `BarEvent` per bar — the flood D-03 replaces with direct
  `strategy.update()`), the ring (`_ring` deque; D-03 ring-consumer research flag).

### Strategy handler
- `itrader/strategy_handler/strategies_handler.py` — `calculate_signals` (line ~106 the `.tickers`
  loop + the `is_ready` gate composition, D-01/D-03c), `get_strategies_universe` (D-12 source),
  `update_config` (D-09/D-11 reuse candidate), `add_strategy`.
- `itrader/strategy_handler/base.py` — `Strategy.tickers`, `strategy.update`, `strategy.is_ready`
  (D-03c indicator-warmth gate — distinct from membership readiness).

### Command ingress / event contract
- `itrader/trading_system/live_trading_system.py` — `add_event` (line ~1948, D-10 allowlist
  inversion — the D-18 external surface); `_dispatch_live` HALT/pause gate (D-07); the
  `UNIVERSE_POLL` timer emit site.
- `itrader/events_handler/events/` — `Event` base (msgspec, `ClassVar` type); the pattern
  `StrategyCommandEvent` / `BarsLoaded` / `BarsLoadFailed` follow.
- `itrader/core/enums/event.py` — `EventType` (add `UNIVERSE_POLL`, `STRATEGY_COMMAND`, `BARS_LOADED`
  / `BARS_LOAD_FAILED`).
- `itrader/events_handler/full_event_handler.py` — `_routes` (add the new routes; D-06/D-11).

### Framework references (used this discussion)
- **QuantConnect LEAN** — `SymbolProperties`(immutable) vs `Security`(mutable, carries `IsReady`)
  split (D-02); `History()` + `WarmUpIndicator` bulk-fetch-sequential-apply (D-03/D-03a);
  `OnSecuritiesChanged` per-security isolation (D-04); `Schedule.On` separate from `OnData` (D-06);
  `AddCrypto → OnSecuritiesChanged` cascade (D-11).
- **Nautilus Trader** — immutable `Instrument` in Cache vs runtime `indicator.initialized` (D-02);
  `request_bars → on_historical_data` per-bar apply (D-03); isolated failed request (D-04);
  `subscribe_bars` emits a `Subscribe` command the DataEngine reacts to (D-11).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LiveTradingSystem.add_event` — already the D-18 external ingress; D-10 inverts its denylist to an
  allowlist (strengthen in place, do NOT add a parallel `queue_event`).
- `LiveBarFeed.warmup()` + `provider.fetch_ohlcv_backfill()` — the async REST fetch machinery exists;
  D-03 splits fetch (async) from warm (engine-thread `strategy.update` via `BarsLoaded`).
- `Universe.apply()` / `mark_leaving` / `clear_leaving` / `on_fill` detach-on-flat — the remove-policy
  + leaving lifecycle is built (Phase 6); D-13/D-15 re-express it on `TrackedInstrument`.
- `StrategiesHandler.get_strategies_universe()` + `derive_membership` — the strategy→membership
  derivation exists; D-12 makes the selection source read it live.
- `OkxExchange.validate_symbol()` + `connector.client.markets` — the venue markets-map source (D-05
  delisted-filter + D-16 precision resolver).

### Established Patterns
- **Queue-only cross-domain writes** — `StrategiesHandler` emits `UNIVERSE_POLL`; it never calls
  `UniverseHandler` (D-11).
- **`.members` held by identity** by the feed — `_members` stays a `list`; only `_instruments`
  becomes `_entries` (D-02, Pitfall 4).
- **Warmup through the identical `update()` path, no bulk fast-path** (LX-09) — extended from the
  feed ring to the strategy indicators; the loop is intrinsic (D-03a).
- **New event type = frozen msgspec `Event` + `EventType` member + `_routes` entry** — the 3-step
  flow for `UNIVERSE_POLL` / `STRATEGY_COMMAND` / `BARS_LOADED` / `BARS_LOAD_FAILED`.
- **Factory `new_*` classmethods** for event construction (`StrategyCommandEvent.add_ticker`, D-09).

### Integration Points
- `UNIVERSE_POLL` (cadence timer + `StrategyCommandEvent`) → `UniverseHandler.on_poll` → `apply` →
  `UniverseUpdateEvent`.
- `UniverseUpdateEvent` add-branch → async fetch → `BarsLoaded`/`BarsLoadFailed` →
  `StrategiesHandler.on_bars_loaded` (warm) + `Universe.mark_ready`/`mark_failed` → subscribe.
- `add_event` allowlist → `StrategyCommandEvent` → `StrategiesHandler.on_strategy_command` (mutate
  `.tickers`, emit `UNIVERSE_POLL`).
- `Universe.is_ready` read by admission (`order_handler`) + the strategy loop; `Universe.instrument`
  precision read by exchange/order/portfolio (unchanged reach-through).

</code_context>

<specifics>
## Specific Ideas

- The operator use case in the owner's words: *"an SMA_MACD strategy online trading one ticker — I
  want to add or remove a ticker manually from the UI, and that should reflect in the universe."*
  Direction is **strategy-edit → universe** (D-09..D-12), reusing the WR-02 readiness-gated warmup.
- Owner will grow `StrategyCommandEvent` into enable/disable/modify-parameters verbs later (D-09).
- Owner explicitly wants to keep the **static, manually-modifiable per-strategy ticker set** as the
  model for now; full universe-driven strategy scope (LEAN `OnSecuritiesChanged`) waits for the
  screener (a future phase).
- Owner preference honored: NO per-command wrapper methods on `LiveTradingSystem` — construction via
  event factories, handling in the domain handlers (D-09/D-11).
- The `TrackedInstrument` name is a deliberate placeholder — owner will rename it when the
  mutable-`Instrument` refactor lands (todo captured).

</specifics>

<deferred>
## Deferred Ideas

- **UI / FastAPI endpoint that calls `add_ticker`/`remove_ticker`** — the transport layer that drives
  `StrategyCommandEvent` from the web. App-layer plan (deferred past Phase 5 per Phase-4 D-08). Phase
  7 ships only the engine-side seam (event + allowlist ingress + selection source).
- **Full universe-driven strategy scope (LEAN model)** — strategies trading whatever the universe
  selects (via `OnSecuritiesChanged`-style binding) instead of a static `.tickers` set. Arrives with
  the ranked production screener; its own discuss+plan (oracle-hot-path change).
- **Mutable-`Instrument` refactor + `TrackedInstrument` rename** — move the conceptually
  time-varying fields (`borrow_rate` [self-admitted static approximation], `maintenance_margin_rate`
  + `max_leverage` [tiered/venue-revised], `liquidation_fee_rate`) off the frozen `Instrument` into a
  mutable per-symbol market-data object, fed by a live venue funding/borrow/risk-tier stream. Captured
  in `.planning/todos/mutable-instrument-refactor.md`. Live-margin / future milestone.
- **Warmup-failure retry cap / backoff** — D-05 chose unbounded retry (validate_symbol filters
  delisted). Add a cap only if REST budget proves a problem.

### Reviewed Todos (not folded)
None — discussion stayed within phase scope (the strategy-command seam is a natural completion of
the Phase-6 operator-driven poll, not new scope).

</deferred>

---

*Phase: 7-live-dynamic-universe-hardening*
*Context gathered: 2026-07-06*
