# Phase 7: Live Dynamic-Universe Hardening — Research

**Researched:** 2026-07-06
**Domain:** Live event-driven dynamic-universe lifecycle (async warmup + per-symbol readiness gate), in-code grounding
**Confidence:** HIGH (all claims grounded in the actual source read this session; framework mappings confirm locked decisions)

## Summary

Phase 7 is already deeply designed: `07-CONTEXT.md` locks 16 decisions (D-01..D-16) that fold in
the LEAN `IsReady`/`WarmUpIndicator` and Nautilus `request_bars`/`on_historical_data` prior art.
This research does **not** re-litigate those. It (a) grounds every locked decision in the current
code so the planner writes accurate `read_first`/`action`/`acceptance_criteria`, and (b) closes the
8 genuinely-open plan-time questions with a concrete recommendation each.

The centerpiece (WR-02) is the swap of today's **synchronous commit-then-warmup** path
(`UniverseHandler.on_universe_update` → `feed.warmup(sym)` → `provider.subscribe(sym)`, no isolation,
naked remove branch) for an **async fetch → `BarsLoaded` event → engine-thread warm → `mark_ready` →
subscribe** pipeline with a first-class per-symbol readiness gate on `Universe`. The async substrate
already exists (`OkxDataProvider.spawn_gap_backfill` / `_fetch_ohlcv_backfill_async` / the supervised
done-callback at `okx_provider.py:649-692`) and is the exact template for the warmup fetch.

**Primary recommendation:** Build the readiness gate as a mutable `TrackedInstrument` record on
`Universe` (one map, `_entries`), drive warmup through a new async `spawn_warmup` that emits ONE
`BarsLoaded`/`BarsLoadFailed`, and **fan `BarsLoaded` into BOTH the strategy indicators AND the feed
ring** (silent, non-emitting) — the feed ring/`_last_delivered` L-stamp is a real consumer whose
continuity the documented warmup-before-subscribe contract (`okx_provider.py:243-248`) depends on.

**No new external packages.** This is an internal brownfield refactor of `itrader/universe/`,
`itrader/price_handler/feed/live_bar_feed.py`, `itrader/strategy_handler/`, and the live composition
root. Standard-Stack / Package-Legitimacy / Environment-Availability sections are therefore N/A.

---

## Locked Design (do not re-decide)

Copy of the binding decisions from `07-CONTEXT.md`. The planner MUST honor these verbatim; research
below only grounds and closes the open sub-questions.

### Locked Decisions (D-01..D-16)
- **D-01** Readiness is a first-class per-symbol fact (`universe.is_ready(sym)`); admission is the
  primary gate consumer, strategy loop carries a cheap defensive check; `feed.window()` KEEPS raising
  `MissingPriceDataError` (loud backstop, never softened to return-empty).
- **D-02** Readiness lives on `Universe` as ONE record map: `_instruments: dict[str,Instrument]` →
  `_entries: dict[str,TrackedInstrument]`. `TrackedInstrument` is mutable (`@dataclass(slots=True)`,
  NOT frozen), wraps the existing frozen `Instrument` by reference, adds `readiness: Readiness`
  (`PENDING`/`READY`/`FAILED`) + `leaving: bool`. `_members` stays the identity-bound list. `Instrument`
  untouched. Name is a placeholder.
- **D-03** Async fetch → single `BarsLoaded(symbol, timeframe, bars)` event → `StrategiesHandler`
  warms concerned strategies via `strategy.update(ticker, bar)` (NO `generate_signal`). Connector loop
  does ONLY the REST fetch; strategies stay pure event consumers (no provider handle).
- **D-03a** The per-bar warmup loop is intrinsic (O(1) recurrences) — bulk transport (one event),
  sequential apply (the loop). No bulk fast-path (LX-09 parity trap).
- **D-03b** Ready flip: `BarsLoaded` handler warms → `universe.mark_ready(sym)` → `provider.subscribe(sym)`
  in that deterministic engine-thread order. Warmup emits no tradeable `BarEvent`s.
- **D-03c** `K = cache_capacity() + _WARMUP_MARGIN` ≥ deepest declared indicator warmup; the two gates
  (`universe.is_ready` + `strategy.is_ready`) compose in the strategy loop.
- **D-04** Isolate + stay pending + retry next poll. On failure the async task emits
  `BarsLoadFailed(symbol, reason)` → `UniverseHandler` marks `FAILED`. NOT rollback-out-of-membership.
  Two distinct events so neither consumer branches on status.
- **D-05** Unbounded retry, re-filtered by `validate_symbol` (delisted drops from `desired` at source).
- **D-06** Dedicated `EventType.UNIVERSE_POLL` discriminator → single route → `UniverseHandler.on_poll`.
  Business `TIME` route left to screeners/bar-gen only.
- **D-07** Skip during freeze: early-return at top of `on_poll` when `is_halted or is_submission_paused`.
  Level-triggered → self-heals next tick. No replay/buffering.
- **D-08** `universe_poll_cadence_s` already `Field(gt=0.0)`, fail-loud (shipped in quick-task 260706-l48).
- **D-09** `StrategyCommandEvent` (command-in, strategy-subject), verbs `add_ticker`/`remove_ticker`,
  factory classmethods (`StrategyCommandEvent.add_ticker(name, sym)`). NO wrapper method on `LiveTradingSystem`.
- **D-10** `add_event` inverted denylist→allowlist: `_EXTERNALLY_ADMISSIBLE = frozenset({SIGNAL, STRATEGY_COMMAND})`.
- **D-11** `StrategyCommandEvent` → `StrategiesHandler.on_strategy_command` (mutate `strategy.tickers`) →
  **emit `UNIVERSE_POLL`** (immediate off-cadence re-select). Emit-a-follow-on, not fan-out-to-Universe.
- **D-12** Strategy-derived selection source replaces the frozen `StaticUniverseSelectionModel(fixed_set)`;
  reads `get_strategies_universe()`/`derive_membership(strategies)` live each `select()`.
- **D-13** `apply()` stops popping removed symbols; teardown moves to `Universe.discard_instrument(sym)`
  = `_entries.pop(sym)` at the two `UniverseHandler` teardown points.
- **D-14** Add-branch clobber guard: `if sym not in _entries` fresh add (`PENDING`); else re-add of held
  (leaving) symbol clears `leaving=False`, KEEPS `readiness=READY`, NO re-warmup.
- **D-15** `_leaving` folds into `TrackedInstrument.leaving`; readiness ⟂ leaving (orthogonal).
- **D-16** Inject a markets-map/precision resolver into `UniverseHandler` (built at composition root
  from the OKX markets map, same source as `derive_instruments`). `Universe` stays connector-free.

### Requirement → finding map

| Req (routed finding) | Locked coverage | Primary code touch |
|---|---|---|
| **WR-01** keep-until-flat × TrackedInstrument | D-13/D-14/D-15 | `universe.py` apply/pop; `universe_handler.py` teardown points |
| **WR-02** async warmup + readiness gate (centerpiece) | D-01/D-02/D-03/D-03a-c/D-04/D-05 | `Universe`, `live_bar_feed.py`, `strategies_handler.py`, `okx_provider.py` |
| **WR-04** markets-map precision resolver | D-16 | `universe_handler.py`, composition root, `okx.py` markets source |
| **WR-05** HALT/pause poll gating | D-07 | `universe_handler.py::on_poll` early-return |
| **WR-06** dedicated `UNIVERSE_POLL` route | D-06 | `core/enums/event.py`, `full_event_handler.py`, `live_trading_system.py` timer |
| Operator strategy-ticker seam | D-09/D-10/D-11/D-12 | new `StrategyCommandEvent`, `add_event`, `strategies_handler.py`, `membership.py` |

*(CR-01 and WR-03 already fixed in quick-task 260706-l48 — out of scope.)*

---

## Open Question 1 — Ring-consumer fan-out (the flagged research question)

**RECOMMENDATION: Fan `BarsLoaded` into BOTH the strategy indicators AND the feed ring.** The ring is
a real consumer with continuity requirements; a strategy-only warmup leaves the feed read-model cold and
breaks a documented contract. The feed-ring fan-out must be a **silent (non-emitting) absorb** — it
populates `_ring` + `_last_delivered` (L) + `_newest_bars` but does NOT `_emit` a `BarEvent` (that is the
"no tradeable BarEvent during warmup" half of D-03b).

### Who consumes the ring today (grounded)
`LiveBarFeed._ring` (`live_bar_feed.py:97`) and its paired `_last_delivered` L-stamp (`:99`) are read by:
- **`window()`** (`:551`, via `_find_ring`/`_base_frame` `:586-611`) — the history read-model. Raises
  `MissingPriceDataError` if a ticker has no ring. Consumed by `megaframe()` (`:615`, screener path) and
  the pair/legacy `evaluate` path. NOT called per-tick on the single-leg live SMA path (P5-D13 replaced
  the per-tick `feed.window()` slice with `strategy.update`).
- **`_last_delivered` L** — the FEED-04 monotonic guard anchor in `update()` (`:181-230`): classifies each
  incoming bar as first / in-sequence / stale / duplicate / gap. This is the consumer that matters on the
  first live bar.
- **`newest_bar()`** (`:525`) — read by `run_paper_replay` (`live_trading_system.py:1429`) and the G5 cache.
- **`current_bars()`** (`:531`) — dormant TIME route.

### Why an unwarmed ring is a correctness gap (grounded)
The `provider.subscribe` docstring (`okx_provider.py:243-248`) documents the invariant explicitly:

> "the plan-05 consumer MUST run `feed.warmup(symbol, tf)` BEFORE `subscribe(symbol)` … so the feed's
> monotonic stamp **L** is set from REST history and the first live closed bar lands on the
> in-sequence/duplicate branch."

Today `feed.warmup()` (`:234`) satisfies this by replaying each fetched bar through `update()` → `_deliver`
(`:486`), which populates the ring AND sets L. If the new `BarsLoaded` path routes bars ONLY to
`strategy.update()`:
- L stays `None` → the first confirmed (`confirm='1'`) live bar is classified as a fresh first delivery
  (`update()` `last is None` branch, `:182-183`), so the **gap between the REST warmup tail and the first
  live bar can never be detected** and the ring going forward holds only post-subscribe bars.
- `window()`/`megaframe()` return a starved (near-empty) frame — breaks the screener path and any future
  admission/consumer that reads history.
- `newest_bar()` returns `None` until the first live bar.

The OKX `confirm='0'` in-progress snapshot pushed on every subscribe (see MEMORY: OKX
candle-snapshot-on-subscribe) is dropped at the `_process_row` confirm gate, so the duplicate-leak angle is
covered there — but the **L-continuity and ring-history angles above are not**, and they are real.

### Shape (for the planner, not over-specified)
Route `BARS_LOADED` to two consumers in list order (list order = execution order, `full_event_handler.py:88`):
```
EventType.BARS_LOADED: [
    strategies_handler.on_bars_loaded,   # 1) warm indicators: for each concerned strategy, for each bar: strategy.update(sym, bar)
    universe_handler.on_bars_loaded,     # 2) silent-absorb bars into feed ring (+L, no emit) -> universe.mark_ready(sym) -> provider.subscribe(sym)
]
```
The feed needs a NEW non-emitting absorb method (e.g. `absorb_warmup(sym, tf, bars)`) that reuses the exact
`_deliver` ring/L/newest-bar logic **minus `_emit`** — a controlled, single-line divergence from `_deliver`,
NOT a second state path (respects D-03a: the ring-append/L-advance logic is identical; only the terminal emit
is suppressed). `UniverseHandler` already holds `self._feed` and `self._provider`, so it owns absorb +
mark_ready + subscribe; `StrategiesHandler` owns indicator warm (it cannot be reached cross-domain by
`UniverseHandler`). Ordering (strategies warm → mark_ready) is guaranteed by route list order.

**Confidence:** HIGH — grounded in `live_bar_feed.py` + the `subscribe` contract docstring.

---

## Open Question 2 — `BarsLoaded` / `BarsLoadFailed` event field shapes

**RECOMMENDATION:** Two new frozen msgspec `Event` subclasses in a new
`itrader/events_handler/events/universe.py` module (or appended to `market.py`), following the
`UniverseUpdateEvent` template exactly (`market.py:97-128`). Use `ClassVar type`, business `time`, and a
`new_*` factory classmethod (house convention).

```python
class BarsLoaded(Event, frozen=True, kw_only=True, gc=False):
    """Warmup bars fetched for one added symbol (D-03). Bulk transport, sequential apply."""
    type: ClassVar[EventType] = EventType.BARS_LOADED
    symbol: str
    timeframe: str
    bars: tuple[Bar, ...]        # immutable payload on a frozen struct (mirror UniverseUpdateEvent's tuple fields)

class BarsLoadFailed(Event, frozen=True, kw_only=True, gc=False):
    """Warmup fetch failed for one symbol (D-04). Marks FAILED; retried next poll (D-05)."""
    type: ClassVar[EventType] = EventType.BARS_LOAD_FAILED
    symbol: str
    reason: str                  # scrubbed (exception TYPE / short message only — never str(exc)/secrets, per okx_provider T-05-27)
```

Grounding notes:
- `Event` base (`events/base.py:21-49`) auto-supplies `event_id` (UUIDv7) + `created_at` (defaults to `time`);
  every event carries a business `time` (never wall clock). `BarsLoaded.time` should be the fetch-completion
  business anchor — use the newest fetched bar's `bar.time` (venue-sourced) to stay off wall-clock, consistent
  with the poll-timer being the SOLE wall-clock event (`live_trading_system.py:1781`).
- `Bar` (`core/bar.py`) is already the queue-safe Decimal-edge struct used by `BarEvent.bars` (`market.py:47`);
  reuse it — never put a pandas frame on the queue (M5-02/D-14).
- `bars` as `tuple[Bar, ...]` matches the frozen-struct immutable-payload convention `UniverseUpdateEvent`
  uses for `added`/`removed` (`market.py:121-122`).
- A `new_*` factory (e.g. `BarsLoaded.new(symbol, timeframe, bars)`) mirrors the `FillEvent.new_fill` /
  `Order.new_order` convention (CONVENTIONS: factory `new_*` classmethods).

**Confidence:** HIGH.

---

## Open Question 3 — `TrackedInstrument` layout + `Readiness` enum home

**RECOMMENDATION:**
- **`TrackedInstrument`**: mutable `@dataclass(slots=True)` (NOT frozen) in `itrader/universe/universe.py`
  (co-located with `Universe`/`UniverseDelta` — it is universe-internal; `is_ready()` returns `bool`, so no
  cross-domain leak of the type). Wraps the frozen `Instrument` **by reference** (never copies/mutates it —
  `Instrument` untouched this phase, D-02):

```python
@dataclass(slots=True)              # mutable — NOT frozen (D-02)
class TrackedInstrument:
    instrument: Instrument          # the existing frozen Instrument, held BY REFERENCE (D-02)
    readiness: Readiness = Readiness.PENDING
    leaving: bool = False
```
  `Universe.instrument(sym)` returns `self._entries[sym].instrument`; `is_ready(sym)` returns
  `self._entries[sym].readiness is Readiness.READY`; `mark_ready`/`mark_failed`/`mark_leaving`/`clear_leaving`
  mutate the record; `discard_instrument(sym)` = `self._entries.pop(sym, None)` (D-13 atomic three-field teardown).

- **`Readiness` enum home**: `itrader/core/enums/` (a new `universe.py` enum module, re-exported from
  `core/enums/__init__.py`). This follows the documented convention that domain enums live in `core/enums`
  (the config-enum exception in CONVENTIONS.md is explicitly the ONLY carve-out, and `Readiness` is not a
  config-domain enum). `core/` depends on nothing inside `itrader`, so `Universe` importing it is a clean
  downward edge. Values: a plain `Enum` (no string-parse need) with `PENDING`/`READY`/`FAILED`.

  *Tradeoff:* co-locating `Readiness` in `universe.py` would also work (it never needs to be named outside
  the universe subsystem since `is_ready` exposes a bool), but `core/enums` matches the house pattern
  (`OrderStatus`, `EventType`, `Side` all live there) and future-proofs a consumer that wants the tri-state.
  Recommend `core/enums`.

Grounding: current `Universe._instruments` (`universe.py:73`) + `_leaving: set[str]` (`:78`) are the two
symbol-keyed structures the WR-01 bug class desyncs; D-02 collapses both into the single `_entries` record.

**Confidence:** HIGH.

---

## Open Question 4 — Per-symbol warmup fetch depth (shared symbol, differing warmups)

**RECOMMENDATION:** Keep the existing derivation `K = cache_capacity() + _WARMUP_MARGIN`
(`live_bar_feed.py:252-253`, `_WARMUP_MARGIN = 5` at `:65`) as the feed-side default, AND apply the
**max-across-concerned-strategies rule** at the fetch site (D-03c): when a symbol is shared by multiple
strategies with different declared warmups, fetch `K = max(cache_capacity(), max(strategy.warmup for
concerned strategies)) + _WARMUP_MARGIN`.

Grounding:
- `cache_capacity()` is 100 under the 03-04 D-13 registration (`live_bar_feed.py:252-253` docstring), and
  `strategy.warmup` is auto-derived to `max(handle.min_period())` in `_run_init` (`strategy_handler/base.py:444-448`)
  — for SMA_MACD that is 100 (`max(SMA50, SMA100, MACDHist15)`). So `cache_capacity()` already ≥ the deepest
  declared warmup on the golden path; the `max(...)` guard only bites if a future strategy declares a warmup
  deeper than the ring capacity.
- The feed already resolves `depth = cache_capacity() + _WARMUP_MARGIN` when `depth is None` (`:252-253`); the
  async warmup fetch should compute the max-across-concerned depth on the engine side (where strategy handles
  live) and pass it explicitly as the `limit` to the fetch (`fetch_ohlcv_backfill(symbol, tf, limit=K)`,
  `okx_provider.py:563-565`).
- "Concerned strategies" = those whose `.tickers` include the symbol (same predicate D-03 uses to pick warmup
  targets). `StrategiesHandler` owns the strategies, so the max-depth computation belongs there (or in a small
  helper it exposes) — not on the feed or `UniverseHandler`.

The `_WARMUP_MARGIN = 5` fixed additive (not a multiplier) absorbs the REST boundary-bar dedup slack
(`:63-65`) — keep it.

**Confidence:** HIGH.

---

## Open Question 5 — Markets-map / precision resolver interface (D-16)

**RECOMMENDATION:** Inject a small **precision-resolver callable/Protocol** into `UniverseHandler` (matching
the existing `set_symbol_validator`/`set_provider` seam pattern), built at the composition root from the SAME
markets source `validate_symbol` already reads — `okx._connector.client.markets` (`okx.py:1029`). Do NOT
reach into connector internals from `Universe` (keep it connector-free, D-03/D-16).

Interface shape (reuse the markets source, dedicated tiny Protocol — cleaner than overloading `validate_symbol`):
```python
class _PrecisionResolver(Protocol):
    def resolve(self, symbol: str) -> Instrument | None: ...   # None -> caller falls back to _DEFAULT_* ladder
```
Wiring point: the same `_initialize_live_session` block that already builds the universe seams
(`live_trading_system.py:1316-1337`), guarded `if self._okx_exchange is not None` exactly like the
`set_symbol_validator` guard (`:1331-1332`). On paper/replay (no live markets map) the resolver is absent →
`apply` falls through to the `_DEFAULT_*` ladder (paper-correct — identical posture to `validate_symbol`
returning `True` when `markets` isn't a dict, `okx.py:1030-1032`).

Grounding on the precision source: ccxt's loaded `markets[symbol]` dict carries `precision.price` /
`precision.amount`; the OKX exchange already uses `client.amount_to_precision` / `client.price_to_precision`
off exactly this loaded-markets precision (`okx.py:362-392`). The resolver converts those into an `Instrument`
with venue-correct `price_precision`/`quantity_precision` (Decimal scales via the D-04 string path
`to_money`/`Decimal("1e-n")`, never `Decimal(float)`), mirroring `derive_instruments`'s ladder
(`instruments.py:216-253`). The resolved `Instrument` is then passed into `Universe.apply(desired,
instruments={sym: resolved})` — replacing today's `apply(desired, None)` (`universe_handler.py:196`) which
forces every poll-added symbol onto the `_DEFAULT_*` 2dp/8dp ladder (the WR-04 bug).

*Where the resolve happens:* in `UniverseHandler.on_poll`, resolve the added symbols (those in
`desired - current`) via the injected resolver and build the `instruments` dict before calling `apply`.
`Universe.apply`'s `resolved.get(sym) or self._default_instrument(sym)` fallback (`universe.py:158-160`)
already handles a missing entry — so an unresolvable symbol still gets the default ladder, never a `KeyError`.

**Confidence:** HIGH.

---

## Open Question 6 — `UNIVERSE_POLL` cadence timer + default cadence

**RECOMMENDATION:** Reuse the existing `_run_poll_timer` daemon mechanism (`live_trading_system.py:1775-1793`)
UNCHANGED except swap the emitted event type: `TimeEvent(time=datetime.now(UTC))` (`:1792`) →
`UniversePollEvent(time=datetime.now(UTC))` (the new `UNIVERSE_POLL` discriminator, D-06). Keep the default
cadence `universe_poll_cadence_s: float = Field(default=60.0, gt=0.0)` (`config/system.py:71`) — already
bounded fail-loud (D-08/WR-03, shipped). 60 s is a sane default for a membership poll decoupled from bars.

Grounding on the timer mechanism (how time-based emits are scheduled today):
- A dedicated daemon thread (`_run_poll_timer`, started only on the live `start()` path at
  `live_trading_system.py:1760`, NEVER in `run_paper_replay` or backtest) loops
  `while not self._stop_event.is_set(): queue.put(<event>); self._stop_event.wait(cadence)`.
- `_stop_event.wait(cadence)` doubles as the interruptible sleep so `stop()` unblocks immediately
  (`:1785-1793`). Foreground `sleep` is not used.
- This is the SOLE wall-clock event on the live path (`:1781-1782`); it stamps ONLY the control-plane poll,
  never a bar/fill business time (determinism / Pitfall 3). `UniversePollEvent` inherits that property.

Because D-06 gives the poll its own discriminator, the timer no longer pollutes the shared TIME route
(which also fans to `screeners_handler.screen_markets` + `feed.generate_bar_event`, `full_event_handler.py:89-92`)
— that is exactly the WR-06 coupling being fixed. The live route wiring
(`live_trading_system.py:1348-1349`, currently `routes[EventType.TIME].append(on_time)`) becomes
`routes[EventType.UNIVERSE_POLL] = [self._universe_handler.on_poll]` (rename `on_time`→`on_poll`, D-06).

**Confidence:** HIGH.

---

## Open Question 7 — `add_event` allowlist audit (D-10)

**RECOMMENDATION:** Safe to invert denylist→allowlist. **There are ZERO internal production callers of
`LiveTradingSystem.add_event`** — it is purely the external/web ingress (D-18). The only callers in the tree
are two unit tests.

Audit (grounded, `grep -rn "\.add_event(" itrader/ tests/ scripts/`):
| Caller | File | Queues what | Under allowlist |
|---|---|---|---|
| `system.add_event(order)` | `tests/unit/trading_system/test_add_event_admission_guard.py:75` | an `OrderEvent` (expects REJECT) | still rejected ✓ (ORDER ∉ allowlist) |
| `system.add_event(non_order)` | `tests/unit/trading_system/test_add_event_admission_guard.py:101` | a non-ORDER event (expects ACCEPT) | **may now reject** ⚠ — depends on the event type used |

Action for the planner:
- Replace the narrow ORDER reject (`live_trading_system.py:1980-1985`) with
  `_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})` and reject anything not
  in it (fail-closed).
- **Update `test_add_event_admission_guard.py:101`**: the existing "non-ORDER accepted" assertion must be
  changed — under the allowlist a `non_order` that is not SIGNAL/STRATEGY_COMMAND (e.g. a `FillEvent` or
  `BarEvent`) is now correctly rejected. This is the intended behavior change (fail-open→fail-closed), not a
  regression; the test should assert SIGNAL + STRATEGY_COMMAND are admitted and each internal-fact type
  (`FILL`, `BAR`, `UNIVERSE_UPDATE`, `UNIVERSE_POLL`, `BARS_LOADED`, `BARS_LOAD_FAILED`, `TIME`, `UPDATE`,
  `ERROR`, `ORDER`) is rejected (the D-10 unit-test note).
- No production caller queues a now-rejected type. The internal order flow puts `OrderEvent`s on
  `global_queue` directly (`add_event` docstring `:1961-1962`), never through `add_event`, so it is unaffected.

**Confidence:** HIGH.

---

## Open Question 8 — Oracle-inertness proof surface

**RECOMMENDATION:** Every new code path must be a no-op on the backtest golden path. The planner writes
byte-exact + no-W1/W2-regression acceptance criteria against these exact inertness levers (all grounded):

| New path | Why inert on backtest | Proof lever |
|---|---|---|
| `UNIVERSE_POLL` route + `on_poll` | Backtest builds its OWN `EventHandler` with the untouched `_routes` literal (`full_event_handler.py:88-109`, empty `UNIVERSE_UPDATE`, no `UNIVERSE_POLL`); the live route mutation is in `_initialize_live_session` only (`live_trading_system.py:1339-1353`). Backtest never constructs `UniverseHandler` nor starts `_run_poll_timer`. | `tests/integration/test_okx_inertness.py`; assert no `UniverseHandler`/`live_bar_feed` import on the backtest path |
| `TrackedInstrument`/`Readiness`/`_entries` on `Universe` | `Universe` construction is shared, but the backtest `select()` never polls (no selection source drives a delta) and SMA_MACD's membership is construction-fixed. Every backtest member is added once at wiring → `PENDING`→`READY` transition must resolve to "always ready" when no live warmup gate runs. **Backtest members must default `READY`** (they carry real data from the store), so `is_ready` is unconditionally true and the strategy loop gate is a no-op. | Oracle byte-exact (`tests/integration/test_backtest_oracle.py`, 134 trades / `46189.87730727451`) |
| Readiness gate in `calculate_signals` | The defensive `universe.is_ready(sym)` check (D-01) must be a live-only branch OR always-true on backtest. The existing gate is `strategy.update → strategy.is_ready → generate_signal` (`strategies_handler.py:140-143`); the membership gate composes BEFORE it. On backtest, `is_ready` is always true (members READY at wiring), so the added gate never changes the firing tick. | Oracle byte-exact + W1 (per-tick hot path — the gate must be O(1), no allocation) |
| Async warmup / `BarsLoaded` / `BarsLoadFailed` | These only fire on the live add-branch (`on_universe_update`), which the backtest never reaches. The events never appear on the backtest queue. | `test_okx_inertness.py` |
| `StrategyCommandEvent` / `add_event` allowlist | External ingress only; backtest has no `add_event` caller and never constructs the event. | inertness test |
| `apply()` stop-popping (D-13) + `_default_instrument` change | `apply` is only called with a non-empty delta when a poll runs; backtest never polls, so `apply`'s removed-loop change is never exercised. The oracle-dark fast path (`universe.py:147-149`, empty delta → no mutation) is the backtest posture. | Oracle byte-exact |

**Key inertness invariant for the planner:** the backtest builds a SEPARATE `EventHandler` with the untouched
`_routes` literal (`live_trading_system.py:1301-1305` documents this), so ALL live-only routing lives behind
`_initialize_live_session`. As long as (a) the backtest never constructs `UniverseHandler`/starts the timer, and
(b) backtest members default `READY`, every Phase-7 addition is provably oracle-dark. W1/W2: the only shared
hot-path touch is the `is_ready` composition in `calculate_signals` — must be a single dict/enum read, no
allocation.

**Confidence:** HIGH.

---

## Architecture Patterns (grounded)

### Data flow (target, live path)
```
UNIVERSE_POLL (cadence timer OR StrategyCommandEvent follow-on)
  -> UniverseHandler.on_poll        [gate: skip if is_halted/is_submission_paused (D-07)]
       -> selection_source.select() [strategy-derived, D-12]
       -> validate_symbol filter (D-05 delisted drop)
       -> precision resolve for added (D-16)
       -> Universe.apply(desired, instruments)   [mutates _members only; _entries add PENDING]
       -> emit UniverseUpdateEvent(added, removed)
  -> UniverseHandler.on_universe_update
       add branch:  spawn async warmup fetch (connector loop) per added sym   [NO state, I/O only]
       remove branch: _on_symbol_removed (policy + mark_leaving/discard)       [D-13/D-15]
  --- connector loop: fetch K bars -> queue.put(BarsLoaded | BarsLoadFailed) ---   (MPSC-safe back to engine)
  -> BARS_LOADED route:
       [1] StrategiesHandler.on_bars_loaded  -> strategy.update(sym, bar) x K   [warm indicators, no signals]
       [2] UniverseHandler.on_bars_loaded    -> feed.absorb_warmup (ring+L, no emit) -> mark_ready -> subscribe
  -> BARS_LOAD_FAILED route:
       UniverseHandler.on_bars_load_failed   -> universe.mark_failed(sym)       [stays dark; retried next poll]
```

### The async substrate to reuse (D-03)
`OkxDataProvider` already has the exact template (`okx_provider.py:649-692`): `spawn_gap_backfill`
(`loop.create_task` + `add_done_callback` supervised) awaiting `_fetch_ohlcv_backfill_async` then invoking a
callback. The warmup analog: a `spawn_warmup(symbol, tf, limit, on_done)` that awaits the async fetch, then on
success `queue.put(BarsLoaded(...))` / on failure `queue.put(BarsLoadFailed(symbol, reason))` — the queue.put
is the MPSC-safe cross-thread hop back to the engine thread (`live_bar_feed.py:502-521` uses the same pattern).
**Note the thread seam:** warmup is *triggered* from the engine thread (`on_universe_update`), so it must
schedule onto the connector loop via `connector.spawn` (cross-thread `call_soon_threadsafe`, as
`subscribe` does at `okx_provider.py:256`), NOT `create_task` (loop-thread-only, used by `spawn_gap_backfill`
because that fires from inside the loop).

### The operator strategy-ticker mutation (D-11)
`StrategiesHandler.on_strategy_command` mutates `strategy.tickers` directly (append/remove) — this is safe:
`strategy.tickers` is a plain `list[str]` set in `_apply_params` (`strategy_handler/base.py:167`,
resolved list); the per-symbol indicator handle-set is minted **lazily** on the ticker's first `update`
(`base.py:450-477` `_activate_ticker`), so adding a ticker needs no re-warmup wiring — the readiness-gated
warmup path handles it. Preserve the non-empty-`list[str]` invariant (`base.py:282-288`) and idempotency on
remove. Then emit `UNIVERSE_POLL` (follow-on, D-11) — one selection path, two triggers.

### Anti-patterns to avoid
- **Softening `feed.window()` to return-empty** on a not-ready symbol — D-01 forbids it (masks a real data
  gap as "warming", the WR-01 silent-wrong-number trap). Keep it raising `MissingPriceDataError`
  (`live_bar_feed.py:564-566`); the readiness gate prevents the window from ever being opened on a pending symbol.
- **Bulk warmup fast-path** — D-03a/LX-09: apply bars sequentially through the same `update`/absorb path;
  no vectorized second computation path (re-opens the parity gate).
- **Fan `StrategyCommandEvent` out to `UniverseHandler` directly** — D-11: emit `UNIVERSE_POLL` instead
  (explicit causal ordering; `UniverseHandler` never sees `StrategyCommandEvent`).
- **A second symbol-keyed readiness map** — D-02: one `_entries` record (the WR-01 desync bug class).

## Common Pitfalls (grounded)

1. **Cold feed ring after warmup (OQ1).** Routing `BarsLoaded` to strategies only leaves `_last_delivered`
   L unset → first live bar misclassified, ring history starved. Fan into both (silent ring absorb).
2. **Backtest members not READY.** If `TrackedInstrument.readiness` defaults `PENDING` and no live warmup
   flips it, the backtest strategy loop gate suppresses every signal → oracle goes to zero trades. Backtest
   members must be `READY` at wiring (they carry store data). Highest-risk inertness trap.
3. **Indentation mismatch.** `universe/` package (`universe.py`, `universe_handler.py`, `instruments.py`,
   `membership.py`), `price_handler/feed/live_bar_feed.py`, and `trading_system/live_trading_system.py`
   (verified: zero tab lines) are **4-SPACE**; `strategy_handler/` (`strategies_handler.py`, `base.py`),
   `events_handler/full_event_handler.py`, `order_handler/admission/admission_manager.py`, and
   `core/enums/order.py` are **TABS**. Match the file (CONVENTIONS tab/space hazard).
   `events_handler/events/` is 4-space.
4. **`filterwarnings=["error"]` + `--strict-markers`.** Any unexpected warning fails the suite; new tests
   must use only `unit`/`integration`/`slow`/`e2e` markers (folder-derived).
5. **Wall-clock leak.** `BarsLoaded.time` / poll event `time` must be venue/business-sourced, never
   `datetime.now()` except the single control-plane poll-timer emit (determinism).
6. **Cross-thread scheduling.** Engine-thread-triggered warmup must use `connector.spawn` (threadsafe),
   not `create_task` — see the substrate note above.

## Project Constraints (from CLAUDE.md)
- Queue-only cross-domain writes; read-model seams for reads (no handler-to-handler calls across domains).
- New event type = frozen msgspec `Event` + `EventType` member + `_routes` entry (the 3-step flow).
- Money is `Decimal` end-to-end; `float()` only at serialization/analytics edge. Enter Decimal via
  `to_money`/string path, never `Decimal(float)`.
- Single UUIDv7 scheme (`idgen`); deterministic seeded RNG + injected clock.
- `mypy --strict` over `itrader` must stay clean (deferred subsystems have per-module overrides; new code
  should be strict-clean).
- `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`.
- Match per-file indentation (see Pitfall 3).
- Recurring milestone gate: backtest oracle byte-exact (134 / `46189.87730727451`); no W1/W2 regression vs
  v1.5 baseline (15.7 s / 152.8 MB).

## Validation Architecture (Nyquist)

### Test framework
| Property | Value |
|---|---|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, folder-derived type markers via `tests/conftest.py`) |
| Config | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, strict markers/config) |
| Quick run | `poetry run pytest tests/unit/universe tests/unit/events tests/unit/strategy -q` |
| Full suite | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY worktree .env abort) |
| Oracle gate | `poetry run pytest tests/integration/test_backtest_oracle.py` (134 / `46189.87730727451`) |
| Inertness gate | `poetry run pytest tests/integration/test_okx_inertness.py` |

### Requirement → test map
| Req | Behavior | Test type | Command / target | Exists? |
|---|---|---|---|---|
| WR-02 gate | `Universe.is_ready` PENDING→READY→FAILED transitions; admission blocks pending | unit | `tests/unit/universe/test_universe_readiness.py::*` | ❌ Wave 0 |
| WR-02 async | `BarsLoaded` warms strategies + feed ring; `BarsLoadFailed` marks FAILED | unit/integration | new `test_bars_loaded.py`; extend `tests/unit/universe/test_universe_poll.py` (uses real `apply`→event→consume, closing the WR-01/WR-02 "hand-built event" test gap noted in 06-REVIEW) | ❌ Wave 0 |
| WR-02 OQ1 | first live bar in-sequence after warmup (ring/L continuity) | unit | extend `tests/integration/test_live_bar_feed_warmup.py` | ⚠ partial |
| WR-01 | removed-but-held keeps `TrackedInstrument`; teardown on flat; re-add-of-held keeps READY | integration | extend `tests/integration/test_universe_remove_policy.py`, `test_universe_force_close.py` | ⚠ partial |
| WR-04 | poll-added symbol gets venue precision via resolver; paper falls to default ladder | unit | new `test_precision_resolver.py` | ❌ Wave 0 |
| WR-05 | `on_poll` early-returns when halted/paused | unit | new `test_poll_halt_gate.py` (or extend `tests/integration/test_halt_latch.py`) | ❌ Wave 0 |
| WR-06 | `UNIVERSE_POLL` routes to `on_poll` only, not screener/bar-gen | unit | extend `tests/unit/universe/test_universe_poll.py` + a `_routes` assertion | ❌ Wave 0 |
| D-09/10 | `StrategyCommandEvent.add_ticker` mutates `.tickers` + emits `UNIVERSE_POLL`; `add_event` allowlist | unit | `test_strategy_command.py`; **update** `tests/unit/trading_system/test_add_event_admission_guard.py:101` | ⚠ update-required |
| Oracle-inertness | byte-exact + no live path on backtest import | integration | `test_backtest_oracle.py` + `test_okx_inertness.py` | ✅ exists |
| W1/W2 | no per-tick regression from the `is_ready` gate | perf | existing v1.5 benchmark harness (same-machine A/B; MEMORY thermal-drift caveat) | ✅ exists |

### Sampling rate
- **Per task commit:** quick run (universe + events + strategy unit subset).
- **Per wave merge:** full `make test` (or worktree `poetry run pytest tests`).
- **Phase gate:** oracle byte-exact + inertness green + no W1/W2 regression before `/gsd:verify-work`.

### Wave 0 gaps
- [ ] `tests/unit/universe/test_universe_readiness.py` — `TrackedInstrument`/`Readiness` transitions (WR-02)
- [ ] `tests/unit/universe/` `BarsLoaded`/`BarsLoadFailed` warm + fan-to-ring coverage (WR-02, OQ1)
- [ ] `tests/unit/universe/test_precision_resolver.py` — D-16 resolver + paper fallback (WR-04)
- [ ] poll HALT-gate test (WR-05)
- [ ] `StrategyCommandEvent` + `add_event` allowlist test; **update** existing add_event guard test (D-09/D-10)
- [ ] extend `test_universe_poll.py` to exercise the REAL `apply`→event→consume ordering (closes the untested
      coupling the 06-REVIEW flagged for WR-01/WR-02)

### Security Domain
- **V5 Input Validation:** `add_event` allowlist inversion (D-10) is the ASVS V4/V5 boundary the docstring
  already cites (`live_trading_system.py:1952`). Default-deny (fail-closed) is the correct posture. Test that
  every internal-fact type is rejected.
- **V5 (data integrity):** `BarsLoadFailed.reason` and any warmup-failure log must scrub — exception TYPE /
  short message only, never `str(exc)` or connector context (the `okx_provider` T-05-27 secret-scrub discipline).
- No new auth/crypto/session surface — this is an internal engine seam; the UI/FastAPI transport that would
  add V2/V3 concerns is explicitly deferred to the app-layer plan.

## Sources
### Primary (HIGH — read this session)
- `itrader/universe/{universe,universe_handler,membership,instruments}.py`
- `itrader/price_handler/feed/live_bar_feed.py`; `itrader/price_handler/providers/okx_provider.py`
- `itrader/strategy_handler/{strategies_handler,base}.py`
- `itrader/trading_system/live_trading_system.py`; `itrader/events_handler/{full_event_handler,events/base,events/market}.py`
- `itrader/core/enums/event.py`; `itrader/config/system.py`; `itrader/execution_handler/exchanges/okx.py`
- `07-CONTEXT.md`, `06-REVIEW.md`, `06-REVIEW-DECISIONS.md`
### Framework mappings (confirm locked D-02/D-03/D-04/D-06/D-11 only — not re-decided)
- LEAN `SymbolProperties`(immutable) vs `Security`(mutable `IsReady`); `History()`+`WarmUpIndicator`;
  `OnSecuritiesChanged` per-security isolation; `Schedule.On`; `AddCrypto→OnSecuritiesChanged`.
- Nautilus immutable `Instrument`-in-Cache vs `indicator.initialized`; `request_bars→on_historical_data`;
  isolated failed request; `subscribe_bars` emits a `Subscribe` command.

## Metadata
**Confidence breakdown:** Code grounding HIGH (all files read); open-question recommendations HIGH (each
tied to a specific grounded consumer/line); framework mappings confirmatory-only.
**Research date:** 2026-07-06 · **Valid until:** ~2026-08-05 (stable internal code; re-verify if the live
feed/provider or event routing changes before planning).

## RESEARCH COMPLETE

**Phase:** 7 — Live Dynamic-Universe Hardening
**Confidence:** HIGH

### Key findings
- OQ1 (flagged): **fan `BarsLoaded` into BOTH strategy indicators AND the feed ring (silent, non-emitting)** —
  the ring/`_last_delivered` L-stamp is a real consumer whose continuity the documented warmup-before-subscribe
  contract (`okx_provider.py:243-248`) depends on; strategy-only warmup breaks it.
- The async warmup substrate already exists (`spawn_gap_backfill`/`_fetch_ohlcv_backfill_async` +
  supervised done-callback) and is the exact template — but warmup fires from the engine thread, so schedule
  via `connector.spawn` (threadsafe), not `create_task`.
- `add_event` allowlist inversion (D-10) is safe: **zero internal production callers**; only two unit tests,
  one of which (`test_add_event_admission_guard.py:101`) must be updated for the new fail-closed posture.
- Highest oracle-inertness risk: backtest `TrackedInstrument` must default **READY** (not PENDING) or the
  strategy gate zeroes the oracle. The backtest builds a SEPARATE `EventHandler` with the untouched `_routes`,
  so all live routing stays behind `_initialize_live_session`.
- `TrackedInstrument` = mutable `@dataclass(slots=True)` in `universe.py` wrapping frozen `Instrument` by
  reference; `Readiness` enum in `core/enums/` (house convention). Precision resolver reuses
  `okx._connector.client.markets` (same source as `validate_symbol` + ccxt `*_to_precision`).

### File created
`.planning/phases/07-live-dynamic-universe-hardening/07-RESEARCH.md`

### Ready for planning
Research complete. All 8 open questions closed with grounded recommendations; locked D-01..D-16 recapped
verbatim; validation + oracle-inertness surface enumerated for acceptance criteria.
