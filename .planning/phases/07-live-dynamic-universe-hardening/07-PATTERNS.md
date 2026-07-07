# Phase 7: Live Dynamic-Universe Hardening - Pattern Map

**Mapped:** 2026-07-06
**Files analyzed:** 13 (5 CREATE surfaces, 8 MODIFY files)
**Analogs found:** 13 / 13 (every new surface has an in-repo analog — this is a brownfield hardening, not a greenfield build)

> **Indentation hazard is per-file and load-bearing (CLAUDE.md + RESEARCH Pitfall 3).**
> Each entry below is tagged `[4-SPACE]` or `[TABS]`. A mixed-indentation diff in a TAB file breaks it.
> - `[4-SPACE]`: `core/`, `config/`, `universe/` (all of it), `price_handler/feed/`, `events_handler/events/`, `trading_system/live_trading_system.py` (verified: zero tab lines)
> - `[TABS]`: `strategy_handler/` (`strategies_handler.py`, `base.py`), `events_handler/full_event_handler.py`, `order_handler/` (incl. `admission/admission_manager.py`), `core/enums/order.py` (verified tab-indented despite the `core/` default)

---

## File Classification

| New/Modified file | Role | Data flow | Closest analog | Match | Indent |
|---|---|---|---|---|---|
| `core/instrument.py` → add `TrackedInstrument` (universe.py) | model / value-object | transform | `core/instrument.py::Instrument` (frozen) | role-match (mutable vs frozen) | `[4-SPACE]` |
| `core/enums/*` → add `Readiness` | model / enum | transform | `core/enums/event.py::Side` (plain 2-3 member Enum) | exact | `[4-SPACE]` |
| `events/*` → `BarsLoaded` / `BarsLoadFailed` | event | event-driven / transport | `events/market.py::UniverseUpdateEvent` | exact | `[4-SPACE]` |
| `events/*` → `StrategyCommandEvent` (+ factory classmethods) | event | event-driven / command | `events/market.py::UniverseUpdateEvent` (struct) + `events/fill.py::FillEvent.new_fill` (factory) | exact | `[4-SPACE]` |
| `core/enums/event.py` → `EventType` new members | model / enum | transform | `EventType.UNIVERSE_UPDATE` member | exact | `[4-SPACE]` |
| markets-map / precision resolver Protocol + wiring | protocol / service | request-response | `universe_handler.py::_SymbolValidator` Protocol + `set_symbol_validator` seam | exact | `[4-SPACE]` (handler) |
| `universe/universe.py` (MODIFY) | model / read-model | CRUD (membership state) | itself (Phase-6 baseline) | self | `[4-SPACE]` |
| `universe/universe_handler.py` (MODIFY) | handler | event-driven | itself (Phase-6 baseline) | self | `[4-SPACE]` |
| `universe/membership.py` (MODIFY) | service / selection | transform | itself (`StaticUniverseSelectionModel`) | self | `[4-SPACE]` |
| `price_handler/feed/live_bar_feed.py` (MODIFY) | feed | streaming / file-I/O(REST) | itself (`warmup`/`_deliver`) | self | `[4-SPACE]` |
| `strategy_handler/strategies_handler.py` (MODIFY) | handler | event-driven | itself (`calculate_signals`) | self | `[TABS]` |
| `trading_system/live_trading_system.py` (MODIFY) | composition-root | event-driven / lifecycle | itself (`_initialize_live_session`, `add_event`, `_run_poll_timer`) | self | `[4-SPACE]` |
| `events_handler/full_event_handler.py` (MODIFY) | dispatcher | event-driven | itself (`self.routes` literal) | self | `[TABS]` |

---

## Pattern Assignments (CREATE surfaces)

### `TrackedInstrument` mutable record + `Readiness` enum — home: `itrader/universe/universe.py` `[4-SPACE]`

**Analog for `TrackedInstrument`:** `itrader/core/instrument.py::Instrument` (lines 40-98) — same `@dataclass` idiom, but **INVERT frozen** per D-02 (mutable, wraps `Instrument` by reference).

Frozen `Instrument` decorator to mirror-but-invert (`core/instrument.py:40-41`):
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Instrument:
    symbol: str
    price_precision: Decimal
    ...
```

**Target shape (RESEARCH OQ3, D-02) — mutable, NOT frozen, co-located in `universe.py`:**
```python
@dataclass(slots=True)              # mutable — NOT frozen (D-02); NO kw_only needed
class TrackedInstrument:
    instrument: Instrument          # the existing frozen Instrument, held BY REFERENCE (D-02)
    readiness: Readiness = Readiness.PENDING
    leaving: bool = False
```
Note: `universe.py` already imports `from dataclasses import dataclass` (line 24) and `from itrader.core.instrument import Instrument` (line 26) — no new import cost for the record itself.

**Analog for `Readiness` enum:** `itrader/core/enums/event.py::Side` (lines 48-68) — a plain small `Enum` with UPPER_CASE members. `Readiness` needs NO `_missing_` string-parse (no external string entry), so it is even simpler:
```python
class Readiness(Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"
```
**Home (RESEARCH OQ3):** new `itrader/core/enums/universe.py`, re-exported from `core/enums/__init__.py`. Follow the barrel pattern in `core/enums/__init__.py:29-32` + `:82-84` (import block + `__all__` entry) — mirror exactly how `EventType, Side` are wired:
```python
# Event enums
from .event import (EventType, Side)
...
'EventType', 'Side',
```

**Oracle-inertness (RESEARCH Pitfall 2, HIGHEST RISK):** backtest members must default **READY** (they carry store data), NOT `PENDING`, or the strategy gate zeros the oracle. Wire the backtest/paper `apply` path to mark added entries READY at construction.

---

### `BarsLoaded` / `BarsLoadFailed` events — home: `itrader/events_handler/events/` `[4-SPACE]`

**Analog (exact):** `itrader/events_handler/events/market.py::UniverseUpdateEvent` (lines 97-128) — frozen msgspec `Event`, `ClassVar type`, `tuple[...]` immutable payload, `__str__`/`__repr__`.

UniverseUpdateEvent template to copy (`market.py:97-128`):
```python
class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.UNIVERSE_UPDATE
    added: tuple[str, ...]
    removed: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)
```

**Base contract (`events/base.py:21-49`):** `Event` auto-supplies `event_id` (UUIDv7 `default_factory`) + `created_at` (defaults to `time` in `__post_init__`). Every event carries a business `time` (never wall clock). `BarsLoaded.time` = newest fetched bar's `bar.time` (venue-sourced — RESEARCH Pitfall 5).

**Target shapes (RESEARCH OQ2):**
```python
class BarsLoaded(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.BARS_LOADED
    symbol: str
    timeframe: str
    bars: tuple[Bar, ...]          # reuse core.bar.Bar (already on BarEvent); NEVER a pandas frame on the queue

class BarsLoadFailed(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.BARS_LOAD_FAILED
    symbol: str
    reason: str                    # scrubbed: exception TYPE / short message only (T-05-27, RESEARCH Security V5)
```
`Bar` import: `from itrader.core.bar import Bar` (already imported in `market.py:8`). RECOMMENDED new module `events/universe.py` (or append to `market.py`); wire the re-export in `events/__init__.py` mirroring the `UniverseUpdateEvent` entry (`events/__init__.py:14-20` import block + `:47-52` `__all__`).

**Factory (house convention):** add a `new`/`new_*` classmethod mirroring `FillEvent.new_fill` (see below) if construction needs a canonical entry.

---

### `StrategyCommandEvent` with `add_ticker`/`remove_ticker` factory classmethods — home: `events/` `[4-SPACE]`

**Struct analog:** `UniverseUpdateEvent` (above). **Factory-classmethod analog (exact):** `itrader/events_handler/events/fill.py::FillEvent.new_fill` (lines 93-179) — the canonical `@classmethod ... -> 'FillEvent'` construct-complete factory.

FillEvent factory pattern to copy (`fill.py:93-99, 156-169`):
```python
@classmethod
def new_fill(cls, status: str, order: OrderEvent, *,
             price: 'Decimal | float', ...) -> 'FillEvent':
    ...
    return cls(
        time=time if time is not None else order.time,
        status=fill_status,
        ticker=order.ticker,
        ...
    )
```

**Target shape (D-09):** verbs `add_ticker` / `remove_ticker` as factory classmethods; NO wrapper method on `LiveTradingSystem`:
```python
class StrategyCommandEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.STRATEGY_COMMAND
    strategy_name: str
    verb: str                      # "add_ticker" | "remove_ticker" (grows: enable/disable/reconfigure)
    symbol: str

    @classmethod
    def add_ticker(cls, name: str, sym: str, *, time: datetime) -> 'StrategyCommandEvent':
        return cls(time=time, strategy_name=name, verb="add_ticker", symbol=sym)

    @classmethod
    def remove_ticker(cls, name: str, sym: str, *, time: datetime) -> 'StrategyCommandEvent':
        return cls(time=time, strategy_name=name, verb="remove_ticker", symbol=sym)
```
Caller idiom (D-10): `engine.add_event(StrategyCommandEvent.add_ticker(name, sym, time=...))`.

---

### `EventType` new members — `itrader/core/enums/event.py` `[4-SPACE]`

**Analog (exact):** the existing `UNIVERSE_UPDATE` member (`event.py:31`). Add four string-valued members alongside it (D-06/D-09/D-03/D-04):
```python
    UNIVERSE_UPDATE = "UNIVERSE_UPDATE"
    UNIVERSE_POLL = "UNIVERSE_POLL"
    STRATEGY_COMMAND = "STRATEGY_COMMAND"
    BARS_LOADED = "BARS_LOADED"
    BARS_LOAD_FAILED = "BARS_LOAD_FAILED"
```
`EventType._missing_` (`event.py:34-45`) already handles case-insensitive string parse for all members — no change needed.

---

### Markets-map / precision resolver Protocol + composition-root wiring `[4-SPACE]` handler / `[TABS]` root

**Protocol analog (exact):** `universe_handler.py::_SymbolValidator` (lines 65-68) — a tiny local `Protocol` + a matching `set_*` seam. Copy the pattern verbatim:
```python
class _SymbolValidator(Protocol):
    """The D-06 venue bound: an object exposing ``validate_symbol`` (e.g. OkxExchange)."""
    def validate_symbol(self, symbol: str) -> bool: ...
```
**Seam analog:** `set_symbol_validator` (`universe_handler.py:147-149`) — a live-only setter defaulting the field to `None` for inertness (`self._symbol_validator: _SymbolValidator | None = None`, `:135`).

**Target (RESEARCH OQ5, D-16):**
```python
class _PrecisionResolver(Protocol):
    def resolve(self, symbol: str) -> Instrument | None: ...   # None -> caller falls to _DEFAULT_* ladder
```
Add `self._precision_resolver: _PrecisionResolver | None = None` + `set_precision_resolver(...)`. In `on_poll`, resolve `desired - current` and build the `instruments` dict passed to `apply` (replacing the `apply(desired, None)` at `universe_handler.py:196`). `Universe.apply`'s `resolved.get(sym) or self._default_instrument(sym)` fallback (`universe.py:158-160`) already handles a missing entry.

**Precision source (same as `derive_instruments`):** ccxt loaded `markets[symbol].precision.price/.amount` via `okx.py` `amount_to_precision`/`price_to_precision`; convert to Decimal scales via the string path (`to_money`/`Decimal("1e-n")`, NEVER `Decimal(float)`), mirroring the `instruments.py` ladder (`_DEFAULT_PRICE_SCALE = Decimal("0.01")`, `:49`; declared→inferred→default resolution `:216-225`).

**Wiring analog (exact):** the guarded `set_symbol_validator` block in `_initialize_live_session` (`live_trading_system.py:1329-1332`):
```python
if self._okx_exchange is not None:
    self._universe_handler.set_symbol_validator(self._okx_exchange)
```
Add a sibling `if self._okx_exchange is not None: self._universe_handler.set_precision_resolver(<resolver built from okx markets>)`. Paper/replay (no markets map) → resolver absent → default ladder (paper-correct).

---

## Pattern Assignments (MODIFY files)

### `itrader/universe/universe.py` `[4-SPACE]`

**Baseline read:** lines 62-191. Current state: `_instruments: dict[str, Instrument]` (`:74`), `_leaving: set[str]` (`:78`), `apply` pops removed from `_instruments` (`:155-156`), `mark_leaving`/`leaving_symbols`/`clear_leaving` (`:180-190`).

Changes (D-02/D-13/D-14/D-15):
- `_instruments` → `_entries: dict[str, TrackedInstrument]`. `instrument(sym)` returns `self._entries[sym].instrument` (was `self._instruments[symbol]`, `:109`); add `is_ready(sym)`, `mark_ready(sym)`, `mark_failed(sym)`.
- `apply` (`:144-162`): DELETE the `for sym in removed: self._instruments.pop(sym, None)` loop (`:155-156`) — D-13 stops popping; mutate `_members` only. Add branch: fresh `if sym not in _entries` → new record `PENDING`; `else` re-add-of-held clears `leaving=False`, keeps `READY`, NO re-warmup (D-14).
- `_leaving` set (`:78`) folds into `TrackedInstrument.leaving`; `mark_leaving`/`clear_leaving`/`leaving_symbols` (`:180-190`) operate on records.
- Add `discard_instrument(sym)` = `self._entries.pop(sym, None)` (D-13 atomic three-field teardown).
- **KEEP** `_members` a `list`, mutated in place via slice-assign (`:151-153` — Pitfall 4, feed binds by identity). Never rebind.
- Backtest inertness: added members default **READY** (Pitfall 2).

`_default_instrument` (`:164-178`) stays as the paper fallback.

---

### `itrader/universe/universe_handler.py` `[4-SPACE]`

**Baseline read:** full file (343 lines). `on_time` (`:168-209`) is the poll target; `on_universe_update` add/remove branches (`:213-231`); `_on_symbol_removed` teardown (`:235-265`); `on_fill` detach-on-flat (`:267-289`); `set_selection_source` (`:143-145`).

Changes (D-06/D-07/D-11/D-13/D-16):
- Rename `on_time` → `on_poll` (D-06 dedicated route); consumes a `UNIVERSE_POLL` event (type-swap `TimeEvent` → new `UniversePollEvent`). Add early-return gate at top: `if is_halted or is_submission_paused: return` (D-07) — read HALT/pause state via an injected seam.
- `apply(desired, None)` (`:196`) → `apply(desired, instruments=<resolved via _precision_resolver>)` (D-16).
- Add `on_bars_loaded` consumer (RESEARCH OQ1): silent ring-absorb (`feed.absorb_warmup`, no emit) → `universe.mark_ready(sym)` → `provider.subscribe(sym)`, in that route-order-guaranteed sequence (D-03b). Add `on_bars_load_failed` → `universe.mark_failed(sym)` (D-04).
- `_on_symbol_removed` no-holder branch (`:251-253`) + `on_fill` detach-on-flat (`:287-288`) → replace instrument teardown with `universe.discard_instrument(sym)` (D-13, the two final-teardown points).
- The add branch of `on_universe_update` (`:221-225`) currently does synchronous `feed.warmup` then `provider.subscribe` — D-03 splits this into async spawn-warmup (I/O only) that emits `BarsLoaded`/`BarsLoadFailed`; subscribe moves into `on_bars_loaded`.
- Add `set_precision_resolver` seam (mirror `set_symbol_validator`, `:147-149`).

Existing Protocols/seam pattern to extend: `_SupportsWarmup`/`_SymbolValidator`/`_SupportsSubscribe` (`:58-80`) + the `set_*` setters (`:143-164`).

---

### `itrader/universe/membership.py` `[4-SPACE]`

**Baseline read:** full file. `UniverseSelectionModel` Protocol (`:190-205`); `StaticUniverseSelectionModel` (`:208-240`); `derive_membership` (`:44-83`).

Changes (D-12): add a **strategy-derived** `UniverseSelectionModel` implementation whose `select(asof)` reads the live strategy set each call (`get_strategies_universe()` / `derive_membership(strategies)`), REPLACING the wiring-time frozen `StaticUniverseSelectionModel(fixed_set)`. Analog: `StaticUniverseSelectionModel.select` (`:229-236`) — same Protocol shape (`select(asof) -> set[str]`), but read-live instead of a held snapshot. `derive_membership` (`:44-83`) is the existing derivation to call live.

---

### `itrader/price_handler/feed/live_bar_feed.py` `[4-SPACE]`

**Baseline read:** `warmup` (`:234-260`), `_deliver` (`:486-500`), `_emit` (`:502-521`), `update` monotonic-guard region (`:220-230`), `backfill_on_resume` (`:262-294`).

Changes (D-03 / RESEARCH OQ1): add a NEW non-emitting `absorb_warmup(sym, tf, bars)` method that reuses the EXACT `_deliver` ring/L/newest-bar logic MINUS `_emit` (`:497-500` ring append + `_newest_bars` + `_last_delivered`, drop `_emit(sym, bar)` `:500`). This is the "silent absorb" — a single-line divergence from `_deliver`, NOT a second state path (respects D-03a/LX-09). The async REST fetch reuses `self._provider.fetch_ohlcv_backfill(symbol, tf, limit=K)` (`warmup:254-255`) but hands bars back via ONE `BarsLoaded` event instead of the per-bar `update()` replay loop (`:259-260`).

**Do NOT** soften `window()` to return-empty (D-01 — keep `MissingPriceDataError`). Warmup depth `K = max(cache_capacity(), max concerned-strategy warmup) + _WARMUP_MARGIN` (RESEARCH OQ4; `_WARMUP_MARGIN=5`, `cache_capacity()`=100).

---

### `itrader/strategy_handler/strategies_handler.py` `[TABS]`

**Baseline read:** `calculate_signals` (`:77-150`), the per-ticker gate (`:140-143`), `get_strategies_universe` (`:322-341`), `add_strategy` (`:344-401`), `update_config` (`:404`).

The existing per-tick gate composition to extend (`:140-143`):
```python
strategy.update(ticker, bar)
if not strategy.is_ready(ticker):
    continue
intent = strategy.generate_signal(ticker)
```

Changes (D-01/D-03/D-03c/D-11):
- Add `on_bars_loaded(event: BarsLoaded)`: for each **concerned** strategy (`.tickers` includes `event.symbol`), loop `strategy.update(sym, bar)` over `event.bars` — NO `generate_signal` (warmup only, D-03). Analog: the exact `strategy.update(ticker, bar)` call at `:140`.
- Add `on_strategy_command(event: StrategyCommandEvent)`: mutate `strategy.tickers` (append/remove — plain `list[str]`, RESEARCH §"operator mutation"), then EMIT `UNIVERSE_POLL` on the queue (D-11, follow-on; do NOT fan out to Universe). Preserve non-empty `list[str]` invariant + remove-idempotency.
- Compose the membership readiness gate BEFORE the existing `strategy.is_ready` gate (`:141`): `universe.is_ready(sym)` (D-01 defensive check) — must be O(1) dict/enum read, no allocation (W1 hot path, RESEARCH OQ8). On backtest always-true (members default READY).
- `get_strategies_universe` (`:322-341`) is the live source the D-12 selection model reads.

---

### `itrader/trading_system/live_trading_system.py` `[4-SPACE]`

**Baseline read:** `_initialize_live_session` route wiring (`:1310-1355`), `_run_poll_timer` (`:1775-1793`), `add_event` (`:1948-1992`).

Changes:
- **`add_event` (D-10):** invert the narrow ORDER denylist (`:1978-1985`) to an allowlist. Add module constant `_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})`; replace the `is EventType.ORDER` reject (`:1980`) with `if getattr(event, 'type', None) not in _EXTERNALLY_ADMISSIBLE: reject`. RESEARCH OQ7: ZERO internal production callers — only `tests/unit/trading_system/test_add_event_admission_guard.py` (`:75` still-rejected, `:101` MUST be updated to the fail-closed posture).
- **Poll timer (D-06, RESEARCH OQ6):** in `_run_poll_timer` (`:1790-1793`) swap the emitted `TimeEvent(time=datetime.now(UTC))` (`:1792`) → `UniversePollEvent(time=datetime.now(UTC))`. Keep the `_stop_event.wait(cadence)` interruptible-sleep mechanism (`:1793`) UNCHANGED. This stays the SOLE wall-clock event (Pitfall 5).
- **Route wiring (D-06):** in `_initialize_live_session` (`:1348-1349`) change `routes[EventType.TIME].append(self._universe_handler.on_time)` → `routes[EventType.UNIVERSE_POLL] = [self._universe_handler.on_poll]`. Add `routes[EventType.STRATEGY_COMMAND] = [strategies_handler.on_strategy_command]` and the two-consumer `routes[EventType.BARS_LOADED] = [strategies_handler.on_bars_loaded, universe_handler.on_bars_loaded]` (list order = execution order) + `routes[EventType.BARS_LOAD_FAILED] = [universe_handler.on_bars_load_failed]`. **LIVE-ONLY** — mutate THIS EventHandler's dict, never the backtest literal (`:1339-1341` documents this invariant).
- Swap the selection source (D-12): `set_selection_source(StaticUniverseSelectionModel(universe.members))` (`:1327-1328`) → the strategy-derived model.
- **Cross-thread note (RESEARCH Pitfall 6):** engine-thread-triggered warmup must schedule onto the connector loop via `connector.spawn` (threadsafe), NOT `create_task`.

---

### `itrader/events_handler/full_event_handler.py` `[TABS]`

**Baseline read:** the `self.routes` literal (`:88-109`).

The backtest literal to extend (`:88-109`) — add explicit-empty entries for the new types so the backtest builds them inert (live consumers wired in `_initialize_live_session`), mirroring `UNIVERSE_UPDATE: []` (`:107`):
```python
EventType.UNIVERSE_UPDATE: [],  # existing — explicit empty, live-only consumers
EventType.UNIVERSE_POLL: [],    # NEW — live-only (UniverseHandler.on_poll wired in _initialize_live_session)
EventType.STRATEGY_COMMAND: [], # NEW — live-only
EventType.BARS_LOADED: [],      # NEW — live-only
EventType.BARS_LOAD_FAILED: [], # NEW — live-only
```
`_dispatch` (`:128-146`) raises `NotImplementedError` on an unrouted type (`:139-141`) — so every new `EventType` member MUST have a routes entry here (the 3-step new-event flow) even if empty on backtest. This is the inertness guarantee (RESEARCH OQ8): backtest builds a SEPARATE EventHandler with this untouched literal.

---

## Shared Patterns

### New event type = 3-step flow
**Sources:** `events/market.py:97-128` (struct) + `core/enums/event.py:31` (member) + `full_event_handler.py:88-109` (route).
**Apply to:** `BarsLoaded`, `BarsLoadFailed`, `StrategyCommandEvent`, `UniversePollEvent`.
Every new event: (1) frozen msgspec `Event` subclass with `type: ClassVar[EventType] = ...`, `__str__`/`__repr__`; (2) `EventType` member in `event.py`; (3) `_routes` entry in `full_event_handler.py` (explicit-empty on backtest). `_dispatch` raising `NotImplementedError` on an unrouted type (`full_event_handler.py:139`) makes step 3 mandatory.

### Factory `new_*` classmethods
**Source:** `events/fill.py:93-179` (`FillEvent.new_fill`).
**Apply to:** `StrategyCommandEvent.add_ticker`/`remove_ticker`; optional `BarsLoaded.new`.
`@classmethod ... -> 'ClassName'` returning `cls(...)`; construct-complete (no post-mutation on the frozen struct).

### Live-only injected-Protocol seam (inert-by-default)
**Source:** `universe_handler.py:65-68` (`_SymbolValidator` Protocol) + `:135` (`= None` field) + `:147-149` (`set_symbol_validator`) + `live_trading_system.py:1331-1332` (guarded wiring).
**Apply to:** `_PrecisionResolver` (D-16), HALT/pause state seam (D-07). Field defaults `None` → unwired handler is inert (backtest never wires it → oracle-dark).

### Queue-only cross-domain writes (emit-a-follow-on, never fan-out)
**Source:** `universe_handler.py:202-206` (`on_time` puts `UniverseUpdateEvent`); `_emit` puts `BarEvent` (`live_bar_feed.py:521`).
**Apply to:** `on_strategy_command` emits `UNIVERSE_POLL` (D-11 — `StrategiesHandler` never calls `UniverseHandler`); `on_bars_loaded`/`on_bars_load_failed` route fan-out via list order, not direct calls.

### Money via string path
**Source:** `fill.py:163-164` (`to_money(price)`), `instrument.py:8-13` (D-04 string-entry doctrine).
**Apply to:** precision resolver Decimal scales — `Decimal("1e-n")`/`to_money`, NEVER `Decimal(float)`.

### Oracle-inertness invariant (RESEARCH OQ8, Pitfall 2)
**Apply to:** ALL Phase-7 additions. Two levers: (a) backtest builds a SEPARATE `EventHandler` with the untouched `_routes` literal — all live routing lives behind `_initialize_live_session`; (b) backtest members default **READY** so `is_ready` is unconditionally true and the strategy gate is a no-op. The only shared hot-path touch is the `is_ready` composition in `calculate_signals` — must be a single dict/enum read, no allocation (W1/W2).

---

## No Analog Found

None. Every Phase-7 surface has a concrete in-repo analog — this is a hardening of the Phase-6 dynamic-universe subsystem, so the closest analogs are frequently the Phase-6 files themselves.

Two shapes have NO direct precedent and lean on framework prior art already recapped in CONTEXT/RESEARCH (not re-decided here):
- **Async spawn-warmup that emits an event** — nearest substrate is `OkxDataProvider.spawn_gap_backfill`/`_fetch_ohlcv_backfill_async` + supervised done-callback (`okx_provider.py:649-692`), the exact template (RESEARCH §"async substrate"). Cross-thread caveat: use `connector.spawn` (threadsafe), not `create_task`.
- **Non-emitting `absorb_warmup`** — no existing non-emitting deliver path; derived by copying `_deliver` (`live_bar_feed.py:486-500`) minus `_emit`.

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/core/enums/`, `itrader/events_handler/events/`, `itrader/events_handler/full_event_handler.py`, `itrader/universe/`, `itrader/price_handler/feed/`, `itrader/strategy_handler/`, `itrader/trading_system/`.
**Files scanned (read):** 13 source files + 2 planning artifacts (07-CONTEXT.md, 07-RESEARCH.md).
**Pattern extraction date:** 2026-07-06
