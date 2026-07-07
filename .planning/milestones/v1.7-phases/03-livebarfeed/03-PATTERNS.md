# Phase 3: LiveBarFeed - Pattern Map

**Mapped:** 2026-07-01
**Files analyzed:** 7 (2 new src, 2 modified src, 3 new/modified test)
**Analogs found:** 7 / 7 (all in-repo — this is a brownfield sibling build)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/price_handler/feed/live_bar_feed.py` (NEW) | feed / read-model | event-driven (push) + transform | `itrader/price_handler/feed/bar_feed.py` (`BacktestBarFeed`) | role-match (sibling of same ABC; data flow differs: push vs precompute) |
| `itrader/price_handler/providers/okx_provider.py` (MODIFY) | provider | streaming (D-12 `ClosedBar` co-shape) | itself (in-place TypedDict + `_process_row`/`fetch_ohlcv_backfill` edit) | exact (self) |
| `itrader/trading_system/live_trading_system.py` (MODIFY) | config / composition root | wiring (DI) | itself (lines 106, 195-203, 234-255, 376) + `compose.py` backtest wiring | exact (self) |
| `tests/unit/price/test_live_bar_feed.py` (NEW) | test (unit) | request-response (synthetic `ClosedBar` → assert `BarEvent`) | `tests/unit/price/test_bar_feed.py` | exact (same dir, same feed subject) |
| `tests/integration/test_live_bar_feed_warmup.py` (NEW) | test (integration) | batch replay | `tests/unit/price/test_bar_feed.py` (structure) + `tests/unit/connectors/test_okx_data_provider.py` (offline stub) | role-match |
| `tests/integration/test_live_bar_feed_route_order.py` (NEW) | test (integration) | event-driven | `tests/unit/price/test_bar_feed.py` | role-match |
| inertness probe (MODIFY or NEW `tests/integration/test_live_bar_feed_inertness.py`) | test (integration) | subprocess probe | `tests/integration/test_okx_inertness.py` | exact (extend `_FORBIDDEN`) |

**Indentation convention (VERIFIED, all analogs):** every analog file below uses **4-SPACE** indentation (`feed/`, `providers/`, `events/`, `trading_system/`, and the `tests/` tree). There is NO tab file in this phase's blast radius — do not introduce tabs. (Handler modules elsewhere use tabs, but none are touched here.)

---

## Pattern Assignments

### `itrader/price_handler/feed/live_bar_feed.py` (feed, event-driven push)

**Analog:** `itrader/price_handler/feed/bar_feed.py` (`BacktestBarFeed`) — the sibling `BarFeed` impl. Implement the SAME 4 abstract members; mirror `bind`, `newest_bar`, `window`/`_resampled_frame`, and the 7-rule contract; REPLACE the precompute/slice core with a push-driven ring + monotonic guard.

**ABC to implement** — `itrader/price_handler/feed/base.py:143-251`. Four `@abstractmethod`s (do NOT re-declare the inherited `register_raw_bar_consumer`/`cache_capacity`/`_raw_bar_consumers`):
```python
@abstractmethod
def newest_bar(self, ticker: str) -> Bar | None: ...
@abstractmethod
def current_bars(self, time: datetime) -> dict[str, Bar]: ...
@abstractmethod
def window(self, ticker: str, timeframe: timedelta, max_window: int, asof: datetime) -> pd.DataFrame: ...
@abstractmethod
def megaframe(self, asof: datetime, timeframe: timedelta, max_window: int) -> pd.DataFrame: ...
```

**Imports pattern** (copy from `bar_feed.py:57-78`; drop the store-specific ones, add `deque`/provider seam):
```python
import functools
import queue
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import pandas as pd

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.logger import get_itrader_logger
from .base import BarFeed
```
Add for the live build: `from collections import deque` and `from itrader.outils.time_parser import to_timedelta` (the tf-string → timedelta helper for `L + tf` gap math — RESEARCH Standard Stack).

**`bind` + queue-injection pattern** (copy `bar_feed.py:428-446` verbatim shape — `update()` needs `self.global_queue` to `put`):
```python
def bind(self, global_queue: "Optional[queue.Queue[Any]]", membership: list[str]) -> None:
    self.global_queue = global_queue
    self.membership = membership
```
Declare the run-path bindings in `__init__` exactly as `bar_feed.py:334-335`:
```python
self.global_queue: "Optional[queue.Queue[Any]]" = None
self.membership: list[str] = []
```

**`newest_bar` pattern** (copy `bar_feed.py:519-528`) — a pure dict read of a `_newest_bars: dict[str, Bar]` the `update()` walk writes:
```python
def newest_bar(self, ticker: str) -> Bar | None:
    return self._newest_bars.get(ticker)
```

**Logger pattern** (copy `bar_feed.py:337`): `self.logger = get_itrader_logger().bind(component="LiveBarFeed")`. Levels per CLAUDE.md Logging: `info` init/subscribe, `warning` for revision/stale/duplicate-drop, `debug` for quiet duplicate.

**Bar construction from `ClosedBar` — DO NOT re-cast through float** (`ClosedBar` OHLCV are already `Decimal`; contrast with `Bar.from_row`'s `Decimal(str(...))` string path in `core/bar.py:52-68` which is for float rows). RESEARCH Code Example:
```python
def _build_bar(self, t: pd.Timestamp, cb: ClosedBar) -> Bar:
    return Bar(time=t, open=cb["open"], high=cb["high"], low=cb["low"],
               close=cb["close"], volume=cb["volume"])
```

**Core NEW pattern — the monotonic guard (`update`), no backtest analog** (design from RESEARCH Pattern 2; the D-06 taxonomy). tz-aware `pd.Timestamp(cb["ts"], unit="ms", tz="UTC")` is MANDATORY (RESEARCH Pitfall 2 — a tz-naive stamp breaks `window()`/`searchsorted`):
```python
def update(self, closed_bar: ClosedBar) -> None:
    sym, tf_str = closed_bar["symbol"], closed_bar["timeframe"]   # D-12 keys
    tf = to_timedelta(tf_str)
    t = pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")        # tz-aware (Pitfall 2)
    L = self._last_delivered.get((sym, tf_str))
    if L is not None:
        if t < L:   return self._reject_stale(sym, t, L)                       # D-06 stale
        if t == L:  return self._duplicate_or_revision(sym, t, closed_bar)     # D-06/D-07 value-compare
        if t > L + tf: self._backfill_gap(sym, tf_str, L + tf, t - tf)         # D-06 gap → replay via update()
    bar = self._build_bar(t, closed_bar)
    self._ring[(sym, tf_str)].append(bar)
    self._newest_bars[sym] = bar
    self._last_delivered[(sym, tf_str)] = t
    self.global_queue.put(BarEvent(time=t, bars={sym: bar}))       # D-02/D-03/D-04 direct-to-BAR, single-ticker
```

**Ring sizing pattern** (D-09): `deque(maxlen=self.cache_capacity())` per `(symbol, timeframe)` — `cache_capacity()` is INHERITED from the ABC (`base.py:118-125`) via `cache_registration.derive`. The live feed relies on the D-13 registration (see the composition-root file) to make `cache_capacity()` return 100, not 1.

**Warmup replay pattern (FEED-03, no bulk fast-path)** — drive the SAME `update()` path (RESEARCH Code Example):
```python
def warmup(self, symbol: str, timeframe: str, depth: int) -> None:
    bars = self._provider.fetch_ohlcv_backfill(symbol, timeframe, limit=depth)  # list[ClosedBar]
    for cb in bars:
        self.update(cb)   # each advances L by one tf → no spurious gap; recursion terminates
```

**`window` / `_resampled_frame` pattern (D-11 pull-resample)** — mirror `bar_feed.py:396-424` (`_resampled_frame`, `label='left', closed='left'`, `_AGG`) and `bar_feed.py:554-665` (`window` rule-4 cutoff `asof - timeframe + base_timeframe`, tz-aware assert at `:616-619`, `_offset_alias` at `:92-136`). NOTE: for golden SMA_MACD (1d==base, N=1) `window()` is NOT exercised on the hot path (indicators self-buffer, RESEARCH §Pattern 1) — a correct-but-simple resample-from-ring implementation suffices for the gate. Reuse `_offset_alias` (NEVER the legacy `time_parser` string for resample rules — `bar_feed.py:93-101` docstring, Pitfall 4).

**`current_bars` pattern** (mostly dormant on live — direct emission is used; still implement for the reserved TIME/`generate_bar_event` path). Mirror `bar_feed.py:485-515` but read the ring instead of `_prebuilt`.

**Error handling** — raise `MissingPriceDataError(ticker, ...)` for unknown tickers in `window` (FR7, `base.py:220`). Stale/revision/duplicate are logged, NOT raised (they are legitimate venue events, D-06/D-07). Never `datetime.now()` — venue `ts` only.

---

### `itrader/price_handler/providers/okx_provider.py` (provider, D-12 co-shape) — MODIFY

**Analog:** itself. Three surgical edits; keep the 4-space indent and the `to_money(str(...))` Decimal edge.

**1. Extend the `ClosedBar` TypedDict** (`okx_provider.py:61-74`) with the two routing keys:
```python
class ClosedBar(TypedDict):
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    symbol: str        # D-12 (Phase-3 add) — routing key
    timeframe: str     # D-12 (Phase-3 add) — routing key
```

**2. Populate in `_process_row`** (`okx_provider.py:233-240`) — the provider knows both from `__init__` (`self._symbol`, `self._timeframe`):
```python
closed: ClosedBar = {
    "ts": int(row[0]),
    "open": to_money(str(row[1])),
    ...,
    "symbol": self._symbol,
    "timeframe": self._timeframe,
}
```

**3. Populate in `fetch_ohlcv_backfill`** (`okx_provider.py:274-283`) — use the method's `symbol`/`timeframe` params, mirroring edit #2.

The `set_bar_sink` seam (`okx_provider.py:158-164`) is UNCHANGED — the composition root passes `feed.update`.

---

### `itrader/trading_system/live_trading_system.py` (composition root) — MODIFY

**Analog:** itself + the backtest `compose.py` wiring shape (mirrored throughout this file already, e.g. `:191`, `:370-375`).

**Swap the feed placeholder** (`live_trading_system.py:106`) — LAZY-import `LiveBarFeed` (inertness gate, see below):
```python
# was: self.feed = BacktestBarFeed(self.store, to_timedelta('1d'))
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed   # LAZY (inertness)
self.feed = LiveBarFeed(...)   # provider handle + base_timeframe
```
Keep `self.feed.generate_bar_event` as a valid callable for the `EventHandler(...)` route literal (`:195-203`) — the TIME route stays DORMANT (D-05) but the literal expects a callable.

**D-13 register a raw-bar consumer on the LIVE feed** (the single most likely correctness failure — RESEARCH Pitfall 1 / Q1). Without it `cache_capacity()` returns 1 and SMA_MACD never warms up → oracle fails. Register at wiring, sized to `max(strategy.warmup)` (=100 for SMA_MACD, `SMA_MACD_strategy.py:34-36`). The `RawBarConsumer` Protocol is `cache_registration.py:45-62` (just needs a `required_history_depth: int` property ≥ 1):
```python
self.feed.register_raw_bar_consumer(_LiveWarmupConsumer(required_history_depth=100))
```

**Wire the provider sink** in the OKX arm (`live_trading_system.py:234-255`, after `self._okx_data_provider` is constructed) or in `_initialize_live_session`:
```python
self._okx_data_provider.set_bar_sink(self.feed.update)
```

**Bind the queue** in `_initialize_live_session` (`live_trading_system.py:376`) — same call the backtest feed uses:
```python
self.feed.bind(self.global_queue, universe.members)
```
Then run startup warmup (`self.feed.warmup(...)`, before `start_stream()` so `update()` stays single-threaded — RESEARCH Thread hand-off) and `self._okx_data_provider.start_stream()` in `start()`.

**Thread-safety (D-02/D-19):** keep ALL `update()` calls on the connector asyncio thread (warmup before `start_stream()`); only `global_queue.put(BarEvent)` crosses to the engine thread — `queue.Queue` is MPSC-safe, no lock needed. Portfolio state still mutates only on the engine thread (`_event_processing_loop`).

---

### `tests/unit/price/test_live_bar_feed.py` (test, unit) — NEW

**Analog:** `tests/unit/price/test_bar_feed.py` (SAME directory — new file goes here per RESEARCH §Validation, NOT `tests/unit/price_handler/`).

**Module-header + marker pattern** (copy `test_bar_feed.py:1-52`): docstring citing the FEED-01/02/04 requirements + `pytestmark = pytest.mark.unit`. Imports:
```python
import queue
from datetime import timedelta
from decimal import Decimal

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

pytestmark = pytest.mark.unit
```

**Offline-test discipline (RESEARCH Pitfall 4 / §How to test):** drive `update()` directly with synthetic `ClosedBar` dicts + a real `queue.Queue`; assert on the drained `BarEvent` sequence. NO aiohttp/asyncio/socket. Every `ts` a fixed epoch-ms literal → byte-reproducible. Mirror the Phase-2 offline fake in `tests/unit/connectors/test_okx_data_provider.py`.

**Stub provider fixture** (RESEARCH Wave-0 gap): a `_StubProvider` with a programmable `fetch_ohlcv_backfill(...) -> list[ClosedBar]` + a captured queue — for the gap/backfill and warmup branches.

**Test matrix (one test per D-06 branch)** — RESEARCH Test Map: `ring` (maxlen evicts), `emit_time` (tz-aware venue-open), `window_lookahead` (rule-4 cutoff), `in_sequence`, `gap_backfill`, `duplicate_drop` (no emit), `revision_forward_only` (WARN+drop, no state mutation), `stale_reject` (no emit), `reconnect_boundary` (re-sent bar hits duplicate branch). Use tz-aware stamps like `test_bar_feed.py::ts` (`pd.Timestamp(stamp, tz=TIMEZONE)`).

---

### `tests/integration/test_live_bar_feed_warmup.py` (test, integration) — NEW

**Analog:** `test_bar_feed.py` structure + stub-provider fixture. FEED-03: assert `warmup()` replays K bars one-by-one through `update()` and SMA_MACD indicators reach `is_ready` (guards Pitfall 1). Folder-derived `integration` marker (conftest.py auto-applies).

### `tests/integration/test_live_bar_feed_route_order.py` (test, integration) — NEW

FEED-05: assert direct `BarEvent` emission replaces `TimeGenerator` and TIME-before-BAR route ordering is preserved downstream. Reference `full_event_handler.py` `_routes` literal for the expected BAR-route order.

### Inertness probe — MODIFY (or NEW `tests/integration/test_live_bar_feed_inertness.py`)

**Analog:** `tests/integration/test_okx_inertness.py` (subprocess clean-interpreter probe). Extend `_FORBIDDEN` (`test_okx_inertness.py:38`) to include `"itrader.price_handler.feed.live_bar_feed"`:
```python
_FORBIDDEN = ("itrader.price_handler.feed.live_bar_feed",
              "itrader.connectors.okx", "ccxt.pro", "ccxt")
```
This proves `LiveBarFeed` is lazy-imported inside `LiveTradingSystem.__init__` only and never on the backtest hot path (the recurring milestone inertness gate).

---

## Shared Patterns

### Queue-injection / `bind` seam
**Source:** `itrader/price_handler/feed/bar_feed.py:334-335, 428-446`
**Apply to:** `live_bar_feed.py` (`bind` + `self.global_queue`/`self.membership` attrs), wired at `live_trading_system.py:376`.
```python
self.global_queue: "Optional[queue.Queue[Any]]" = None
self.membership: list[str] = []
def bind(self, global_queue, membership) -> None:
    self.global_queue = global_queue
    self.membership = membership
```

### tz-aware `pd.Timestamp` for all bar time
**Source:** `bar_feed.py:616-619` (window tz-aware assert); RESEARCH Pitfall 2.
**Apply to:** every `Bar.time` and `BarEvent.time` in `live_bar_feed.py` — `pd.Timestamp(ts, unit="ms", tz="UTC")`. Never tz-naive; never wall-clock.

### Decimal edge already crossed — never re-cast
**Source:** `okx_provider.py:233-240` (`to_money(str(...))` at the provider edge); `core/bar.py:1-21` (D-14 money policy).
**Apply to:** `live_bar_feed._build_bar` — pass `ClosedBar` Decimals straight into `Bar(...)`. Do NOT route through `Decimal(float)` or `Bar.from_row`'s string path.

### Lazy-import for hot-path inertness
**Source:** `live_trading_system.py:210-238` (OKX stack lazy-imported inside `__init__`); `test_okx_inertness.py`.
**Apply to:** the `LiveBarFeed` import in `live_trading_system.py:106` and the extended `_FORBIDDEN` probe.

### Bound-logger context
**Source:** `bar_feed.py:337`, CLAUDE.md Logging.
**Apply to:** `live_bar_feed.py` — `get_itrader_logger().bind(component="LiveBarFeed")`; `info` init/subscribe, `warning` revision/stale.

### Capacity derivation — never hand-set
**Source:** `cache_registration.py:106-137` (`derive`), `base.py:97-125` (`register_raw_bar_consumer`/`cache_capacity`).
**Apply to:** `live_bar_feed.py` ring `maxlen` (D-09) reads `self.cache_capacity()`; `live_trading_system.py` registers the D-13 consumer so it derives to 100.

---

## No Analog Found

Files/logic with no close in-repo analog (planner: use RESEARCH.md patterns, no copy source):

| Logic | Role | Data Flow | Reason |
|-------|------|-----------|--------|
| The FEED-04 monotonic guard taxonomy (`update` stale/dup/revision/gap classify) | feed | event-driven | No backtest analog — the backtest feed is precompute+slice, never ingests a live stream. Build from RESEARCH Pattern 2 + D-06 table. |
| D-08 reconnect proactive backfill (boundary check → replay) | feed | event-driven | Novel live-only logic; no in-repo precedent. RESEARCH §D-08. |
| The one-by-one warmup replay driver | feed | batch | Backtest has NO warmup path (it precomputes full frames). Build from RESEARCH Code Example; explicitly NO bulk `warmup_from` fast-path (LX-09). |

---

## Metadata

**Analog search scope:** `itrader/price_handler/feed/`, `itrader/price_handler/providers/`, `itrader/events_handler/events/`, `itrader/core/`, `itrader/trading_system/`, `tests/unit/price/`, `tests/unit/price_handler/`, `tests/integration/`.
**Files scanned (read in full or targeted):** `feed/base.py`, `feed/bar_feed.py`, `feed/cache_registration.py`, `core/bar.py`, `providers/okx_provider.py`, `events/market.py`, `live_trading_system.py` (§80-276, §360-388), `tests/unit/price/test_bar_feed.py` (§1-75), `tests/integration/test_okx_inertness.py`.
**Pattern extraction date:** 2026-07-01
