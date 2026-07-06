# Phase 6: Dynamic Universe Membership - Pattern Map

**Mapped:** 2026-07-06
**Files analyzed:** 13 source files (11 modified + 2 new) + Wave-0 tests
**Analogs found:** 13 / 13 (all in-repo; zero new external deps)

This phase is **pure in-repo wiring** — every new file has a strong existing analog in the same
subsystem. The dominant risk is NOT "what pattern do I copy" but **indentation discipline**
(tabs vs 4-space, per file — see the per-file `[INDENT]` tag) and **preserving `.members`
by-identity** (D-03 / Pitfall 4). No source is edited by this agent; excerpts below are copy-from
references for the planner.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `events_handler/events/market.py` (+`UniverseUpdateEvent`) | event/model | event-driven (frozen fact) | `ScreenerEvent` / `BarEvent` (same file) | exact | 4-space |
| `events_handler/events/__init__.py` (export) | barrel | — | existing `ScreenerEvent` export | exact | 4-space |
| `core/enums/event.py` (+`UNIVERSE_UPDATE`) | enum | discriminator | `SCREENER` member (same file) | exact | 4-space |
| `events_handler/full_event_handler.py` (+`_routes` entry) | router | event-driven fan-out | `EventType.BAR` / `FILL` route (same literal) | exact | **TABS** |
| `universe/universe.py` (+`apply()`/`UniverseDelta`) | model/service | transform (diff + in-place mutate) | `Universe.members` property (same file) | role-match | 4-space |
| `universe/membership.py` (lean `UniverseSelectionModel`) | service (pure selection) | transform (derive desired set) | `derive_membership` / `active_membership` (same file) | exact | 4-space |
| `screeners_handler/screeners_handler.py` (+`on_time` poll) | handler (poll host) | event-driven / request-response | `screen_markets` (cadence check, same file) | exact | **TABS** |
| `price_handler/providers/okx_provider.py` (+`subscribe`/`unsubscribe`+registry) | provider | streaming (WS subscribe lifecycle) | `start_stream` / `_stream_candles` (same file) | exact | 4-space |
| `connectors/okx.py` (per-symbol spawn/cancel — reuse) | connector | streaming (asyncio task lifecycle) | `spawn` / `_on_task_done` / `disconnect` (same file) | reuse-as-is | 4-space |
| `order_handler/admission/admission_manager.py` (+leaving-symbol gate) | service (admission gate) | request-response (validate) | `_enforce_direction_admission` (same file) | exact | **TABS** |
| `core/enums/order.py` (+`ADMISSION_LEAVING`) | enum | discriminator | `ADMISSION_DIRECTION` member (same file) | exact | **TABS** |
| `trading_system/live_trading_system.py` (un-hardcode `_OKX_STREAM_SYMBOL`; poll timer) | composition root | wiring / event source | existing `set_universe`/`feed.warmup`/daemon lifecycle | role-match | 4-space |
| **NEW** remove-policy consumer (`UniverseUpdateEvent` side-effect handler) | handler (event consumer) | event-driven | subscribe-consumer sibling + `PortfolioHandler.on_fill` flat-detect | role-match | match host |

---

## Pattern Assignments

### `UniverseUpdateEvent` in `events_handler/events/market.py` (event, event-driven) `[INDENT: 4-space]`

**Analog:** `ScreenerEvent` (`events/market.py:73-94`) — the naming/style precedent; keep it
DISTINCT (`ScreenerEvent`=propose, `UniverseUpdateEvent`=dispose). Base contract from
`events/base.py:21-49`.

**msgspec struct pattern to copy** (NOT a dataclass — `msgspec.Struct` subclass, `type` is a
`ClassVar`, never an init field). From `events/base.py:21` and `market.py:30-53`:
```python
# base.py:21 — the base every event subclasses
class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType]                 # discriminator, no base default
    time: datetime
    event_id: uuid.UUID = msgspec.field(default_factory=uuid_compat.uuid7)
    created_at: datetime | None = None
```
```python
# market.py:30 — BarEvent shows the ClassVar-type + payload-field shape to mirror
class BarEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.BAR
    bars: dict[str, Bar]
```

**New event to write** (from RESEARCH §5 / D-04; place next to `ScreenerEvent`, `tuple[str, ...]`
for frozen-immutable payload; `time`/`event_id`/`created_at` inherited):
```python
class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.UNIVERSE_UPDATE
    added: tuple[str, ...]      # +sym → subscribe + feed.warmup
    removed: tuple[str, ...]    # −sym → unsubscribe + remove-policy
```

**Barrel export** (`events_handler/events/__init__.py`): mirror the `ScreenerEvent` import (line 17)
and `__all__` entry (line 49) — add `UniverseUpdateEvent` in both the `from .market import (...)`
block and `__all__`.

---

### `EventType.UNIVERSE_UPDATE` in `core/enums/event.py` (enum) `[INDENT: 4-space]`

**Analog:** the `SCREENER` member (`core/enums/event.py:30`).

**Copy pattern** — add one string-valued member alongside `SCREENER`; the `_missing_`
case-insensitive parser (`:33-44`) already covers it, no change there:
```python
# event.py:23-31 — add UNIVERSE_UPDATE next to SCREENER
    SCREENER = "SCREENER"
    UNIVERSE_UPDATE = "UNIVERSE_UPDATE"   # new — the "dispose" notification (D-04)
    ERROR = "ERROR"
```

---

### `_routes` entry in `events_handler/full_event_handler.py` (router) `[INDENT: TABS — do not normalize]`

**Analog:** the `EventType.BAR` multi-consumer fan-out (`full_event_handler.py:93-97`) and the
explicit-empty `SCREENER`/`UPDATE` rows (`:105-106`).

**Copy the fan-out shape** (list order IS execution order — subscribe consumer FIRST so socket/warmup
is in flight, remove-policy consumer second):
```python
# full_event_handler.py:93 — BAR route = the N-consumer, ordered fan-out to mirror
			EventType.BAR: [
				self.portfolio_handler.update_portfolios_market_value,  # 1) mark-to-market
				self.execution_handler.on_market_data,                  # 2) resting-order matching
				self.strategies_handler.calculate_signals,              # 3) new signals
			],
```
New route to add (mirror shape; consumers are the two D-04 side-effect handlers):
```python
			EventType.UNIVERSE_UPDATE: [
				<subscribe_consumer>,      # 1) provider.subscribe + feed.warmup / unsubscribe
				<remove_policy_consumer>,  # 2) orphan-and-track / force-close (D-01)
			],
```

**Landmine (Pitfall 5, RESEARCH §Pattern-1):** `_dispatch` raises `NotImplementedError` on an
unrouted type (`:137-140`). Add the enum member and the route entry **in the same change**, or an
emitted event crashes the dispatcher (backtest fail-fast; live logs via `_publish_and_continue`).

**Poll-handler-on-TIME caveat (Pitfall 3 / §11):** the TIME route (`:89-92`) fires every backtest
tick. If `poll_handler.on_time` is added here it MUST early-return on one cheap guard
(`self._selection_source is None`) before any work; measure W1 after. Prefer a **live-only** route
mutation in `start()` if the guard is measurable — leave the backtest `_routes` literal untouched.

---

### `Universe.apply()` + `UniverseDelta` in `universe/universe.py` (model, transform) `[INDENT: 4-space]`

**Analog:** the `Universe.members` property (`universe.py:51-60`) — the by-identity contract this
method must NOT break. No mutation surface exists today; `apply()` is a deliberate role shift.

**By-identity contract to preserve** (Pitfall 4 — the feed binds this SAME list object at
`live_trading_system.py:1250` → `LiveBarFeed.bind` stores it at `live_bar_feed.py:140-141`):
```python
# universe.py:51 — .members is returned BY IDENTITY, never copied
    @property
    def members(self) -> list[str]:
        # "returned BY IDENTITY (not a defensive copy) ... DO NOT mutate it;
        #  a mutation rewrites the universe's internal membership in place."
        return self._members
```

**`apply()` body to write** (RESEARCH §6 — slice-assign `self._members[:]`, NEVER rebind
`self._members = ...`; sorted to match `derive_membership` WR-05 order; empty-delta fast path is the
oracle-dark guarantee):
```python
def apply(self, desired: set[str]) -> UniverseDelta:
    current = set(self._members)
    added = tuple(sorted(desired - current))
    removed = tuple(sorted(current - desired))
    if not added and not removed:
        return UniverseDelta(added=(), removed=())   # oracle-dark fast path — no put
    self._members[:] = sorted((current - set(removed)) | set(added))  # in place (Pitfall 4)
    for sym in removed:
        self._instruments.pop(sym, None)
    # added-symbol Instrument resolution — see landmine below
    return UniverseDelta(added=added, removed=removed)
```

**`UniverseDelta` value object** (discretion — frozen dataclass, dependency-light internal return;
NOT a queue event — the event carries the same `tuple[str,...]` fields):
```python
@dataclass(frozen=True, slots=True)
class UniverseDelta:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    def is_empty(self) -> bool:
        return not self.added and not self.removed
```

**Landmine — Instrument resolution for an added symbol (Open Q1):** `derive_instruments`
(`instruments.py:170`) is wiring-time/strategy-driven and needs `price_data` — a dynamic add has
neither. Keep `Universe` connector-free (D-03): the **poll handler** resolves precision from the D-06
venue markets map and passes resolved `Instrument`s into `apply()` (or a sibling), with the
`instruments.py` `_DEFAULT_*` ladder as the paper fallback.

---

### Lean `UniverseSelectionModel` in `universe/membership.py` (service, transform) `[INDENT: 4-space]`

**Analog:** `derive_membership` (`membership.py:44-83`) and `active_membership` (`:146-170`) — pure,
queue-free, feed/store-free selection primitives. The module's D-20 header (`:11-20`) documents this
as THE growth target ("screeners propose, membership disposes").

**Purity pattern to copy** (no class-state required; a pure function OR a thin model with injected
data — mirror `active_membership`'s "compose over an injected map, return a set" shape):
```python
# membership.py:146 — the derived-selection precedent: pure, returns a set, no queue/feed
def active_membership(spans: dict[str, Span], asof: datetime) -> set[str]:
    return {t for t in spans if is_active(spans, t, asof)}
```
The lean selection source answers "what SHOULD the universe be?" as a pure/derived function; it holds
NO queue and NO feed (those live on the poll handler host). Sort/dedup discipline: match
`derive_membership`'s `sorted(set(...))` (WR-05, `:83`) so multi-symbol runs stay reproducible.

---

### Poll handler `on_time` on `screeners_handler/screeners_handler.py` (handler) `[INDENT: TABS]`

**Analog:** `ScreenersHandler.screen_markets` (`screeners_handler.py:55-92`) — already holds
`self.feed` (`:28`) + `self.global_queue` (`:27`), already cadence-gates via `check_timeframe`, and
is already on `_routes[TIME]` (`full_event_handler.py:90`). The natural low-friction host (RESEARCH §7).

**Cadence-check pattern to copy** (the `check_timeframe` early-`continue` guard):
```python
# screeners_handler.py:72 — cadence gate: skip when not a multiple of the frequency
		for screener in self.screeners:
			if not check_timeframe(event.time, screener.frequency):
				continue
```

**New `on_time(time_event)` to write** (RESEARCH §7 — source-guard FIRST for backtest-inertness,
then cadence, then D-06 filter, then `apply`, then emit-only-on-non-empty):
```python
	def on_time(self, event):
		if self._selection_source is None:      # backtest/paper wire none → oracle-dark, ~free
			return
		# cadence check (check_timeframe-style or wall-clock delta vs poll_cadence)
		desired = self._selection_source.select(...)                 # lean model (membership.py)
		desired = {s for s in desired if self._exchange.validate_symbol(s)}  # D-06 venue bound
		delta = self._universe.apply(desired)
		if not delta.is_empty():
			self.global_queue.put(UniverseUpdateEvent(
				time=event.time, added=delta.added, removed=delta.removed))
```

**Split (discretion):** selection ("what should it be") → pure model in `membership.py` (4-space);
poll ("cadence + apply + emit") → `ScreenersHandler` (TABS). Keep each edit matched to its file.

---

### `subscribe`/`unsubscribe` + registry on `price_handler/providers/okx_provider.py` (provider, streaming) `[INDENT: 4-space]`

**Analog:** `start_stream` (`okx_provider.py:208-219`) + `_stream_candles`
(`:221-234`) + `_connect_and_consume_candles` (`:236-293`). Today ONE wiring-time symbol, ONE
`self._stream_handle`.

**Spawn pattern to copy** (`start_stream:208`):
```python
# okx_provider.py:215 — compute channel, spawn on the connector loop, hold the handle
        symbol_okx = self._to_okx_symbol(self._symbol)
        channel = "candle" + self._okx_interval(self._timeframe)
        self._stream_handle = self._connector.spawn(
            self._stream_candles(symbol_okx, channel))
```

**New `subscribe`/`unsubscribe` to write** (RESEARCH §1 — grow a `{symbol: asyncio.Task}` registry,
idempotent; cancel reuses the connector's cooperative teardown, NO new teardown code):
```python
def subscribe(self, symbol: str) -> None:
    if symbol in self._streams:                 # idempotent
        return
    symbol_okx = self._to_okx_symbol(symbol)
    channel = "candle" + self._okx_interval(self._timeframe)
    self._streams[symbol] = self._connector.spawn(
        self._stream_candles(symbol_okx, channel))

def unsubscribe(self, symbol: str) -> None:
    task = self._streams.pop(symbol, None)
    if task is not None:
        task.cancel()   # async-with in _connect_and_consume_candles closes WS/session
```

**Connector reuse (do NOT hand-roll)** — `OkxConnector.spawn` (`connectors/okx.py:182-207`) is
engine-thread-safe (`call_soon_threadsafe` + `ready` Event); `_on_task_done` (`:209-231`) untracks a
cancelled task quietly; `disconnect` (`:233+`) already cancels all `_stream_tasks`. `Task.cancel()`
from the engine thread on a connector-loop task is safe.

**Landmine — per-symbol supervisor keys (Pitfall 2):** `_stream_candles` hard-codes the supervisor
key `"candles"` (`:234`) and `_connect_and_consume_candles` calls `_on_stream_healthy("candles")` /
`_reset_reconnect_budget("candles")` (`:261,290`). With N channels, key these **per-symbol/channel**
or one symbol's drop marks all down and one payload resets all budgets. Verify
`is_streaming_healthy()` (`:402`) compound semantics against `_all_venue_streams_healthy`
(`live_trading_system.py:974`).

**Snapshot-on-subscribe (WR-03 / §2):** the `confirm='0'` snapshot is ALREADY dropped by
`_process_row` (`:462-464`); warmup-BEFORE-subscribe sets `L` so the first live closed bar lands on
the in-sequence/duplicate branch. Add NO new dedup logic.

---

### Leaving-symbol admission gate on `order_handler/admission/admission_manager.py` (service) `[INDENT: TABS]`

**Analog:** `_enforce_direction_admission` (`admission_manager.py:483-556`) — the exact gate shape
(early skip for explicit-quantity, consult the injected snapshot, return an audited `OperationResult`
on violation else `None`). It runs as the FIRST gate in `process_signal`'s sequence (`:185-209`).

**Gate pattern to copy** (early-exit guards + audited-reject; note the guard-clause style the user
prefers):
```python
# admission_manager.py:511 — skip-guards then the audited reject
        if signal_event.quantity and signal_event.quantity > 0:
            return None                                   # explicit qty: gate n/a
        ...
        return self._reject_unsized_signal(
            signal_event,
            f"direction violation: ...for {signal_event.ticker}",
            triggered_by=OrderTriggerSource.ADMISSION_DIRECTION,
            operation_type=OrderOperationType.SIGNAL_ADMISSION,
            error_prefix="Signal rejected at admission",
        )
```

**New `_enforce_leaving_symbol_admission` to write** (RESEARCH §8 — add as the FIRST gate, before
direction; reject only a NEW entry for a leaving symbol; exits/reduces MUST pass so the position can
go flat):
```python
	def _enforce_leaving_symbol_admission(self, signal_event, snap):
		# read the "leaving set" via the already-injected Universe (set_universe at :68/:93)
		if signal_event.ticker not in self._universe.leaving_symbols():
			return None
		if <signal is an exit/reduce, not a new entry>:   # SLTP/stop must pass
			return None
		return self._reject_unsized_signal(
			signal_event,
			f"universe removal: new entries blocked for leaving symbol {signal_event.ticker}",
			triggered_by=OrderTriggerSource.ADMISSION_LEAVING,
			operation_type=OrderOperationType.SIGNAL_ADMISSION,
			error_prefix="Signal rejected at admission")
```
Wire it into the gate sequence in `process_signal` BEFORE `_enforce_direction_admission` (`:185`).

**Leaving-set home:** `AdmissionManager` already receives an injected `Universe`
(`set_universe`, `:68/:93`). Put the leaving-set on `Universe` (or a sibling read-model) — the
remove-policy consumer populates it on removal, clears it on flat. No new cross-domain dependency.

---

### `ADMISSION_LEAVING` in `core/enums/order.py` (enum) `[INDENT: TABS]`

**Analog:** `ADMISSION_DIRECTION` / `ADMISSION_INCREASE` members (`core/enums/order.py:194-197`).

**Copy pattern** — add one member next to the other `ADMISSION_*` reasons; `_missing_` (`:200`) covers it:
```python
# order.py:194 — add ADMISSION_LEAVING alongside the sibling admission reasons
	ADMISSION_MAX_POSITIONS = "admission_max_positions"
	ADMISSION_LEVERAGE = "admission_leverage"
	ADMISSION_LEAVING = "admission_leaving"   # new — D-01 block-new-entries-for-leaving-symbol
```

---

### Un-hardcode `_OKX_STREAM_SYMBOL` + poll timer in `trading_system/live_trading_system.py` (composition root) `[INDENT: 4-space]`

**Analog:** the existing composition wiring at `_initialize_live_session` — `feed.bind` (`:1250`),
`set_universe` broadcast (`:1232/1236/1241`), and the startup warmup→stream ordering (`:1532-1534`).

**Current hardcoded startup to replace** (`:1532`):
```python
# live_trading_system.py:1532 — single wiring-time symbol; source from universe.members instead
            if self.exchange == 'okx' and self._okx_data_provider is not None:
                self.feed.warmup(_OKX_STREAM_SYMBOL, _OKX_STREAM_TIMEFRAME)
                self._okx_data_provider.start_stream()
```
Replace with: for each `sym in universe.members`, `feed.warmup(sym, tf)` then
`provider.subscribe(sym)` (warmup BEFORE subscribe — Pitfall 6). Keep a single-symbol default path.

**Wiring assertion to generalize** (`:1261-1270`) — today asserts `_OKX_STREAM_SYMBOL in
universe.members`; must assert **every** subscribed symbol is a member (ring-key vs `window()`
ticker guard, RESEARCH §1 step 3).

**Live poll-timer thread (RESEARCH §4):** a small daemon timer owned by `LiveTradingSystem`, started
in `start()` (live daemon path only — NOT `run_paper_replay`, which is synchronous at `:1283`), doing
`global_queue.put(TimeEvent(time=datetime.now(UTC)))` every `poll_cadence`s until `_stop_event`.
**Analog:** the existing live daemon lifecycle + `_stop_event` discipline already in this file. Do NOT
reuse `core/clock.py::BacktestClock` (that is business-time). Default cadence 60s, config-driven
(A2). This keeps the subsystem oracle-dark: backtest/paper never start the timer.

---

### NEW remove-policy consumer (`UniverseUpdateEvent` side-effect handler) (handler, event-driven)

**No exact analog** — it is a new event consumer. Closest role-match: a `_routes` side-effect handler
that reads position truth and emits an order. Compose from two existing patterns:

1. **Flat-detection on FILL** — `PortfolioHandler.on_fill` / `OrderHandler.on_fill`
   (`full_event_handler.py:101-104`): on the leaving symbol reaching flat (`open_position_count`/net
   quantity == 0 via `PortfolioReadModel`), unsubscribe + clear the leaving-set + drop from `Universe`.
2. **Force-close order emission** — build a market-exit `OrderEvent` (Decimal money via
   `to_money(str(x))`) on the signal/order path; it hits the `_dispatch_live` gate
   (`live_trading_system.py:1030/1047`) and is suppressed under pause — acceptable (§Pattern-2).

**Policy branch (Pitfall 4):** the subscribe-consumer must NOT unconditionally `unsubscribe(removed)`.
Branch on policy + open-position state: force-close → unsubscribe now; orphan-and-track WITH open
position → keep WS/ring alive + mark leaving, detach on flat; orphan-and-track WITHOUT open position →
unsubscribe now. Policy flag lives in live/poll-seam config (default `"orphan-and-track"`), NOT
`SystemConfig.PerformanceSettings` (keeps the oracle untouched, §8).

---

## Shared Patterns

### The documented three-step "new event type" flow
**Sources:** `core/enums/event.py:30`, `events/market.py:73`, `full_event_handler.py:88-108`.
**Apply to:** `UniverseUpdateEvent`. Enum member + msgspec struct + `_routes` entry, all in one
change (else `NotImplementedError`, `:137`). The events package is import-light (msgspec, no pandas
at module scope) — does not disturb the `test_okx_inertness.py` gate.

### `.members` by-identity mutation (D-03 / Pitfall 4)
**Source:** `universe/universe.py:51-60`, consumed at `live_trading_system.py:1250` +
`live_bar_feed.py:140`.
**Apply to:** `Universe.apply()`. Slice-assign `self._members[:] = ...`; NEVER rebind. Warning sign:
feed `MissingPriceDataError` at first `window()` for an added symbol.

### Audited-reject admission gate
**Source:** `admission_manager.py:483-556` (`_enforce_direction_admission`) + `_reject_unsized_signal`.
**Apply to:** the new leaving-symbol gate. Guard-clause early exits (user preference), audited
`OperationResult` with a new `OrderTriggerSource`, `OrderOperationType.SIGNAL_ADMISSION`.

### Connector spawn/cancel task lifecycle (don't hand-roll)
**Source:** `connectors/okx.py:182-207` (`spawn`), `:209-231` (`_on_task_done`), `:233+`
(`disconnect`); supervisor `okx_provider.py:321` (`_run_stream_supervisor`).
**Apply to:** provider `subscribe`/`unsubscribe`. Reuse cooperative-cancel; only NEW code is the
`{symbol: task}` registry + per-symbol supervisor keys.

### Warmup-through-`update()` (reuse verbatim, no bulk fast-path)
**Source:** `live_bar_feed.py:234-260` (`LiveBarFeed.warmup`).
**Apply to:** warmup-on-add. Replays REST bars one-by-one through `update()` (FEED-03/LX-09). Warmup
BEFORE subscribe (Pitfall 6). Do NOT build a `warmup_from` fast-path — it re-opens the parity audit.

### Venue markets-map bound (D-06)
**Source:** `execution_handler/exchanges/okx.py:1016-1032` (`validate_symbol`) — reads
`connector.client.markets`, accepts-all when markets not a dict (paper path).
**Apply to:** the poll handler's `desired`-set filter, BEFORE `apply()`. Direct call (inject
`OkxExchange`), keeping `Universe` connector-free (D-03).

---

## No Analog Found

| File | Role | Data Flow | Reason / compose-from |
|------|------|-----------|-----------------------|
| Remove-policy consumer | handler (event consumer) | event-driven | No standalone `UniverseUpdateEvent` consumer exists yet; compose from `on_fill` flat-detect (`full_event_handler.py:101`) + Decimal `OrderEvent` emission |
| Live poll-timer thread | timer/event-source | pub-sub cadence | No live `TimeEvent` source exists today (`generate_bar_event` is a dormant no-op, `live_bar_feed.py:641`); new daemon on `LiveTradingSystem`, reuse `_stop_event` lifecycle |
| Multi-symbol replay fixture | test harness | batch replay | `ReplayDataProvider` is single-symbol today; needs a two-symbol driver (shared dep of the two integration tests, §10) |

**Test files (Wave 0, all new — mirror `test_<module>.py` in the type-grouped tree):**
`tests/unit/universe/test_universe_apply.py`, `tests/unit/events/test_universe_update_event.py`,
`tests/unit/screeners/test_universe_poll.py`, `tests/unit/price/test_okx_dynamic_subscribe.py`
(async, mocked connector), `tests/unit/price/test_warmup_on_add.py`,
`tests/integration/test_universe_remove_policy.py`, `tests/integration/test_universe_force_close.py`,
optional-gated `tests/e2e/test_okx_dynamic_universe.py`. Oracle/parity/inertness gates already exist.

## Metadata

**Analog search scope:** `itrader/events_handler/`, `itrader/core/enums/`, `itrader/universe/`,
`itrader/screeners_handler/`, `itrader/price_handler/providers/` + `feed/`, `itrader/connectors/`,
`itrader/execution_handler/exchanges/`, `itrader/order_handler/admission/`,
`itrader/trading_system/`.
**Files scanned:** 11 source analogs read in full/targeted + 2 enum/barrel confirmations.
**Pattern extraction date:** 2026-07-06

---

## PATTERN MAPPING COMPLETE

**Phase:** 6 - Dynamic Universe Membership
**Files classified:** 13 (11 modified + 2 new) + 8 Wave-0 test files
**Analogs found:** 13 / 13

### Coverage
- Files with exact analog: 8 (event, enum×2, route, selection model, poll handler, admission gate, provider subscribe)
- Files with role-match analog: 2 (`Universe.apply`, `live_trading_system` wiring)
- Files reuse-as-is: 1 (connector spawn/cancel)
- Files with no direct analog (compose-from): 3 (remove-policy consumer, live poll timer, multi-symbol replay fixture)

### Key Patterns Identified
- **Three-step new-event flow** — `EventType` member + msgspec `Event` subclass + `_routes` entry in one change; msgspec struct, `type` is a `ClassVar`, NOT a dataclass.
- **`.members` by-identity** — `Universe.apply()` slice-assigns `self._members[:]`, never rebinds (feed binds the same list object; Pitfall 4).
- **Reuse over rebuild** — warmup-through-`update()`, connector spawn/cancel, `validate_symbol`, snapshot `confirm`-gating are all already built; the genuinely new code is `apply`, the event+route, the provider registry, the poll+timer, and the remove-policy+admission gate.
- **Oracle-dark by construction** — single-symbol SMA_MACD → empty delta → no event; live-only timer never starts on backtest/paper.
- **Indentation split is load-bearing** — TABS: `full_event_handler.py`, `screeners_handler.py`, `admission_manager.py`, `core/enums/order.py`. 4-space: `events/`, `core/enums/event.py`, `universe/`, `okx_provider.py`, `live_trading_system.py`. Never normalize.

### File Created
`.planning/phases/06-dynamic-universe-membership/06-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can reference each analog file + line range directly in PLAN action steps.
