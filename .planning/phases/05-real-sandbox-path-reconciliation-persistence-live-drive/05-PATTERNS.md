# Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive - Pattern Map

**Mapped:** 2026-07-02
**Files analyzed:** 14 target files/seams (7 modify, ~7 new)
**Analogs found:** 13 / 14 (one genuinely-new algorithm: cached-venue drift-compare)

> Research finding drives this map: ~80% of Phase 5 is **wiring already-built seams**
> (`VenueAccount` constructor, `OkxExchange` streams, `CachedSql*`, `_publish_and_continue`,
> `get_status`) + porting ~4 small nautilus pure-functions. Every target below has a live
> in-repo analog EXCEPT the cached-venue+drift-compare body, which is ported from nautilus.
> **Indentation is per-file and load-bearing** — see each assignment's `Indent:` note.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `portfolio_handler/account/venue.py` (body) | model/account | streaming (cache) + request-response (REST) | `account/simulated.py::SimulatedCashAccount` + `execution_handler/exchanges/okx.py` streams | role-match (compute→cache is new) |
| `portfolio_handler/reconcile/drift.py` (NEW) | utility | transform | `core/money.py::quantize` (precision-keyed) | role-match (port nautilus fn) |
| `portfolio_handler/reconcile/reconcile_manager.py` (NEW) | service | event-driven (reconciling events) | `CachedSqlOrderStorage.rehydrate()` (store side) + `OkxExchange._handle_trade` (FillEvent mint) | partial (venue side new) |
| `execution_handler/exchanges/okx.py::_handle_trade` (modify) | controller/adapter | streaming | itself (`_handle_trade`) + `okx.py` `_correlation_lock` map | exact (extend in place) |
| `connectors/base.py` / `okx.py` (reuse as-is) | config/protocol | — | already `runtime_checkable` Protocol | exact (no change needed) |
| `{order,portfolio,strategy}/storage/cached_sql_storage.py` (drive live) | store | CRUD (store-first) | themselves — built + tested v1.6 | exact (wire, don't rebuild) |
| `trading_system/live_trading_system.py` (wire) | composition root | event-driven | itself (:295-328 okx arm, :372 error policy, :649 metrics) | exact (extend in place) |
| `price_handler/providers/okx_provider.py` (reconnect) | provider | streaming | `_stream_candles` (:191) + `okx.py::_stream_fills` | role-match (add supervisor) |
| `core/enums/system.py::SystemStatus` (add HALTED) | enum | — | `core/enums/severity.py::ErrorSeverity` | exact |
| `trading_system/alert_sink.py` (NEW) | provider/seam | request-response | `connectors/base.py::LiveConnector` (Protocol seam) | role-match |
| `events_handler/full_event_handler.py::_log_error_event` (modify) | consumer | event-driven | itself (:143) | exact (extend in place) |
| `portfolio_handler/portfolio_handler.py::on_fill` (drift hook) | handler | event-driven | itself (:620) + `_publish_error_event` (:119) | exact (extend in place) |

## Pattern Assignments

### `portfolio_handler/account/venue.py` — implement the body (D-14/D-15/RECON-01)

**Analogs:** `account/base.py::Account` (contract), `account/simulated.py::SimulatedCashAccount`
(sibling leaf, lines 133-162 for the property shape / 413-482 for reserve/release), and
`execution_handler/exchanges/okx.py` (`_stream_fills`/`_handle_trade` for the async cache-write
discipline). **Indent: 4 spaces** (matches `venue.py`/`base.py`/`simulated.py` today).

**Import discipline (inertness gate — DO NOT change):** `LiveConnector` stays `TYPE_CHECKING`-only,
sourced from the ccxt-free `itrader.connectors.base`, exactly as the current stub does (`venue.py:34-41`):
```python
from decimal import Decimal
from typing import TYPE_CHECKING
from itrader.core.ids import OrderId
from .base import Account
if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
```

**Constructor seam (already landed — extend, do not replace)** (`venue.py:54-66`):
```python
def __init__(self, connector: "LiveConnector") -> None:
    self._connector = connector
    # Phase 5 additions: RLock-guarded venue cache (async writes / engine reads).
```

**Cache + push pattern** — mirror the `SimulatedCashAccount` property shape (`simulated.py:133-162`)
but CACHE instead of COMPUTE (the anti-pattern to avoid: `VenueAccount` never recomputes balance —
Pitfall 10). The async writer follows `OkxExchange._stream_fills` discipline (`okx.py:274-286`):
cache-write ONLY on the connector loop thread, NEVER compare/halt (D-15). Decimal edge via
`to_money(str(x))` at every ccxt-float boundary (`okx.py:263,267-268` is the exact idiom):
```python
# async writer (spawned via connector.spawn, like OkxExchange.connect okx.py:310-312)
async def _stream_account(self) -> None:
    while True:                                    # + reconnect supervisor (RES-01, see okx_provider)
        update = await self._connector.client.watch_balance()
        with self._lock:
            self._venue_balance = to_money(str(update["total"]["USDT"]))   # Decimal edge
# REST snapshot for startup/restart/gap (D-14/D-19) — connector.call RPC, like
# okx_provider.fetch_ohlcv_backfill (okx_provider.py:278-282)
def snapshot(self) -> None:
    bal = self._connector.call(self._connector.client.fetch_balance())
    with self._lock:
        self._venue_balance = to_money(str(bal["total"]["USDT"]))
```

**balance/available READ (engine thread, D-15)** — surface never-snapshotted as a typed error,
never a silent 0 (contrast `SimulatedCashAccount.balance` `simulated.py:134-136` which returns
computed state directly):
```python
@property
def balance(self) -> Decimal:
    with self._lock:
        if self._venue_balance is None:
            raise StateError(...)   # not yet snapshotted — surfaces loud
        return self._venue_balance
```

**reserve/release (OPEN QUESTION 1 — plan-time decision):** the `Account` ABC requires both
(`base.py:79-113`). `SimulatedCashAccount.reserve` (`simulated.py:413-462`) tracks a local
reservation + raises `InsufficientFundsError`. Research recommends a **local pending-reservation
overlay** on top of cached venue-available for `VenueAccount` (venue owns the real reservation).
Copy the `reserve` validation/raise shape from `simulated.py:436-451`; the release-idempotency
no-op from `simulated.py:479-481`.

---

### `portfolio_handler/reconcile/drift.py` — precision-epsilon tolerance (NEW, D-01)

**Analog:** `core/money.py::quantize` (`money.py:76-92`) — it already reads
`instrument.price_precision` / `instrument.quantity_precision` and `_CASH_SCALES`. The drift
helper keys off the SAME precision. **Indent: 4 spaces** (matches `core/`, `money.py`).
Port nautilus `live/reconciliation.py:52` verbatim — DO NOT `import nautilus_trader`:
```python
from decimal import Decimal
def is_within_single_unit_tolerance(v1: Decimal, v2: Decimal, precision: int) -> bool:
    if precision == 0:
        return v1 == v2                    # integer quantities: exact
    tolerance = Decimal(10) ** -precision  # one least-significant-digit unit
    return abs(v1 - v2) <= tolerance
```
`precision` derives from the loaded OKX market (`client.markets[sym]['precision']['amount'|'price']`),
reconciled into the engine `Instrument` at connector init — NOT hardcoded. Existing scales that
anchor the illustration: `_DEFAULT_SCALES["quantity"]=1e-8` (8dp), `_CASH_SCALES["USD"]=0.01`
(`money.py:45-56`).

---

### `execution_handler/exchanges/okx.py::_handle_trade` — fill-ID dedup + fast-fill race (modify, D-12/D-13)

**Analog:** the method itself (`okx.py:226-272`) and the existing `_correlation_lock` +
`_orders_by_venue_id`/`_venue_id_by_order_id` maps (`okx.py:97-99`). **Indent: TABS** (this tree is
tab-indented — a mixed-indent diff breaks the file, per module docstring `okx.py:29`).

**The two documented latent gaps to close** (already flagged in-code at `okx.py:87-96` and `okx.py:237-239`):
1. **No fill-ID dedup** — `_handle_trade` emits one `FillEvent("EXECUTED")` per trade with no
   `trade['id']` idempotency key (a reconnect re-send double-counts).
2. **Fast-fill race** — a fill can arrive on `watch_my_trades` before `create_order` returns the
   venue id, so `order` resolves `None` at `okx.py:236-239` and is **silently dropped**.

**Existing correlation-resolve to extend** (`okx.py:234-239`):
```python
venue_id = trade.get("order") if isinstance(trade, dict) else None
with self._correlation_lock:  # WR-03: cross-thread read guard
    order = self._orders_by_venue_id.get(venue_id) if venue_id is not None else None
if order is None:
    self.logger.warning("Fill for unknown venue order %s — skipping", venue_id)  # <-- the drop = the race
    return
```

**Dedup layer to add** (nautilus `get_existing_fill_for_trade_id` analog — key by `trade['id']`):
```python
trade_id = trade.get("id")
with self._correlation_lock:
    if trade_id in self._seen_trade_ids:   # NEW: set[str]
        return                             # duplicate re-send — idempotent no-op
    self._seen_trade_ids.add(trade_id)
```

**Fast-fill-race fix:** register a pending correlation keyed by `clOrdId` in `_submit_order`
BEFORE the `connector.call(create_order(...))` RPC (`okx.py:196-203` is where the venue-id map is
written today — move/duplicate a `clOrdId`-keyed entry ahead of the RPC), and briefly buffer an
unmatched fill instead of dropping it at `okx.py:238`.

**Preserve the existing Decimal-edge + fee-guard** (`okx.py:261-270`) unchanged — `to_money(str(x))`,
`abs()` on commission, `_ms_to_dt` business-time stamp. `VALID_ORDER_TRANSITIONS`
(`core/enums/order.py:81-86`) already permits `PENDING→PARTIALLY_FILLED→{FILLED,CANCELLED}` — no
enum change for D-12. Terminalization is `OrderHandler.on_fill`'s job (the FillEvent carries the
increment).

---

### `connectors/base.py` + `okx.py` — reuse the LiveConnector Protocol as-is

**No new code.** `LiveConnector` is already a `@runtime_checkable Protocol` (`base.py:43-85`)
exposing `call`/`spawn`/`client`/`sandbox`/`connect`/`disconnect`. `VenueAccount` drives
`connector.client.watch_balance()` / `fetch_balance()` through the generic seam exactly as
`OkxExchange` uses `watch_my_trades` (`okx.py:277`) and `okx_provider` uses `fetch_ohlcv`
(`okx_provider.py:282`). **No connector method added** — the account stream reuses `spawn`
(`okx.py::OkxConnector.spawn`, `okx.py:151-176`) and `call`. The conftest `FakeLiveConnector`
(structural) is the test double for the offline fixture suite (D-09).

---

### `{order,portfolio,strategy}/storage/cached_sql_storage.py` — drive live (D-10/D-11, RECON-04)

**Analog: themselves — built + testcontainers-tested in v1.6.** The store-first write-through and
`rehydrate()` already exist; Phase 5 only WIRES them onto the real feed. **Indent: 4 spaces**
(matches the `*/storage` siblings, per `cached_sql_storage.py:29`).

**Store-first write pattern (sync-durable working set, D-10)** — persist-then-acknowledge; store
commit returns BEFORE cache mutation so a cache bug can never corrupt the store
(`order_handler/storage/cached_sql_storage.py:114-152`):
```python
def add_order(self, order: "Order") -> None:
    self._store.add_order(order)            # one txn (orders row + state_changes)
    with self._lock:
        self._cache.add_order(order)        # mirror into working set
def update_order(self, order: "Order") -> bool:
    ok = self._store.update_order(order)
    if not ok: return False
    with self._lock:
        self._cache.update_order(order)
        if self._can_evict(order): ...      # D-02 terminal-state purge gate
```

**Restart rehydration — the store side is DONE** (`order_handler/storage/cached_sql_storage.py:264-278`).
Phase 5 adds the VENUE side (see reconcile_manager below), not new store code:
```python
def rehydrate(self) -> None:
    with self._lock:
        for order in self._store.get_active_orders(None):    # open-only + bracket parents
            self._cache.add_order(order)
            parent_id = order.parent_order_id
            if parent_id is not None and self._cache.get_order_by_id(parent_id) is None:
                parent = self._store.get_order_by_id(parent_id)
                if parent is not None:
                    self._cache.add_order(parent)
```
Portfolio (`portfolio_handler/storage/cached_sql_storage.py:276`) and strategy
(`strategy_handler/storage/cached_sql_storage.py:98`) `rehydrate()` follow the same shape.

**Async/best-effort path (signals, D-11)** — `strategy_handler/storage/cached_sql_storage.py`
`add` is store-first-then-mirror (`:66`); the signal store is advisory (not the restart working
set), so it rides the async writer, NOT the sync-durable path. Replace the stale
`SignalStorageFactory.create('backtest')` (`live_trading_system.py:171`) with the live-driven
store via the factory (`strategy_handler/storage/storage_factory.py:36`).

---

### `trading_system/live_trading_system.py` — composition root wiring (multiple D-##)

**Analog: itself.** All seams already exist as extension points. **Indent: 4 spaces.**

**(a) VenueAccount → Portfolio wiring (D-14)** — the OKX arm already constructs it (`:295-317`):
```python
if self.exchange == 'okx':
    from itrader.portfolio_handler.account import VenueAccount    # lazy — inertness gate
    ...
    self._venue_account = VenueAccount(self._okx_connector)       # :317 — now LINK into Portfolio
```
Follow the same lazy-import-inside-the-`okx`-arm discipline (`:296-300`) for any new reconcile
module (inertness gate).

**(b) Signal store live-drive (D-11)** — replace `:171`:
```python
self._signal_store = SignalStorageFactory.create('backtest')   # <-- stale; drive live async
```

**(c) Order store live-drive (RECON-04)** — the Postgres-or-in-memory branch (`:183-208`) already
builds `SqlBackend` from `SYSTEM_DB_URL` and injects it; complete the `CachedSql*` wiring on top.

**(d) D-16 BAR-keyed metrics (WR-01 fix)** — `LiveBarFeed` emits ONLY `BarEvent` (no `TimeEvent`),
so the current TIME key means `record_metrics` never fires live. Change `:649-651`:
```python
if hasattr(event, 'type') and event.type == EventType.TIME:      # <-- WR-01: never true live
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)
# -> key on EventType.BAR (async/best-effort path, D-10)
```
Note the backtest-parity direct-record pattern already used in `run_paper_replay` (`:582-603`,
`portfolio.record_metrics(bar_time)`) is the reference for the bar-open stamp.

**(e) Error-policy split (D-17/WR-04)** — the live override is already installed (`:367`):
```python
self.event_handler._on_handler_error = self._publish_and_continue   # publish-and-continue (:372-)
```
D-17 keeps this for the REAL live path but makes the deterministic replay/parity driver
(`run_paper_replay`) run **fail-fast** (match the backtest it diffs against). The base seam is
`full_event_handler.py::_on_handler_error` (`:126-141`, `raise`).

**(f) HALTED status (D-07)** — `get_status()` (`:796-825`) returns `self._status.value`; add a
`halt_reason` field and the HALTED state (see SystemStatus below).

---

### `core/enums/system.py::SystemStatus` — add HALTED (D-07)

**Analog:** `core/enums/severity.py::ErrorSeverity` (`severity.py:15-39`) — the house string-enum
pattern. **Indent: 4 spaces.** Current members are STOPPED/STARTING/RUNNING/STOPPING/ERROR
(`system.py:14-19`); add:
```python
class SystemStatus(Enum):
    ...
    HALTED = "halted"   # D-07: reason ∈ {drift, reconciliation-unresolved,
                        #                connector-fatal, paused-on-disconnect}
```

---

### `trading_system/alert_sink.py` — pluggable alert-sink seam (NEW, D-06)

**Analog:** `connectors/base.py::LiveConnector` (`base.py:43-85`) — the `runtime_checkable Protocol`
swap-a-fake seam pattern. **Indent: 4 spaces.** A thin Protocol + a single log impl this milestone
(external push deferred):
```python
class AlertSink(Protocol):
    def alert(self, event: ErrorEvent) -> None: ...
class LogAlertSink:                              # the ONLY impl this milestone
    def alert(self, event: ErrorEvent) -> None: ...   # marked structured log
```
`ErrorSeverity.CRITICAL` already exists (`severity.py:24`) — halts escalate to it.

---

### `events_handler/full_event_handler.py::_log_error_event` — alert-sink egress (modify, D-06)

**Analog: the method itself** (`full_event_handler.py:143-167`). **Indent: TABS.** It already maps
`event.severity` → logger method (`:151-154`, with `ErrorSeverity.CRITICAL → self.logger.critical`).
Extend to route CRITICAL through the injected `AlertSink` (default `LogAlertSink`) so an external
channel drops in later without touching this code:
```python
log_method = {
    ErrorSeverity.WARNING: self.logger.warning,
    ErrorSeverity.CRITICAL: self.logger.critical,
}.get(event.severity, self.logger.error)
# NEW: if event.severity is CRITICAL: self._alert_sink.alert(event)
```
Scrub secrets before emit (Pitfall 16) — the method already binds only declared `ErrorEvent`
fields (`:155-166`), never raw connector context.

---

### `portfolio_handler/portfolio_handler.py::on_fill` — drift-compare hook (modify, D-15)

**Analog: the method itself** (`portfolio_handler.py:620-`) + `_publish_error_event` (`:119-138`)
for the halt-alert emission. **Indent: 4 spaces.** The drift COMPARE runs HERE on the engine thread
(D-15, single-writer), AFTER the fill mutates portfolio state — never on the async thread (Pitfall
8). The non-EXECUTED early-return guard (`:634-640`) is the insertion reference; add the drift check
after the EXECUTED transaction applies (`:642-668`). Halt emission reuses the
`PortfolioErrorEvent` construction (`:129-138`) escalated to `ErrorSeverity.CRITICAL`. The account
read is `portfolio.account.balance` (`:324`), which for live is the `VenueAccount` cached read.

---

### `price_handler/providers/okx_provider.py` — reconnect supervisor (mirror, RES-01/D-19/D-20)

**Analog:** `_stream_candles` (`okx_provider.py:191-217`) and `okx.py::_stream_fills`
(`okx.py:274-286`). **Indent: 4 spaces** (`okx_provider.py`). **Code-verified gap:** the stream
loops today are bare `while True: await watch_*()` / `async for msg in ws` with **NO reconnect** —
a socket drop kills the task silently. Wrap each `_stream_*` consume-loop in a bounded-retry
supervisor (debounce ~250-500ms, exponential backoff cap ~30s, ceiling ~5-8 → HALT). Classify:
transient (`NetworkError`/`RequestTimeout`/`DDoSProtection`) → retry+stay-running; fatal
(`AuthenticationError`/`PermissionDenied`) or ceiling → HALTED + CRITICAL alert (D-20). The
per-item skip-and-log discipline already exists (`_process_row` try/except `:241-258`,
`_stream_fills` try/except `:282-286`) — the supervisor wraps the OUTER loop, preserving it.

## Shared Patterns

### Decimal edge (money policy — apply to every venue-float boundary)
**Source:** `execution_handler/exchanges/okx.py:263,267-268`; `core/money.py::to_money`
**Apply to:** `venue.py` cache writes, `_handle_trade`, reconcile_manager reconciling events
```python
commission = abs(to_money(str(fee_cost))) if fee_cost is not None else Decimal("0")
price=to_money(str(price)), quantity=to_money(str(amount))
```
NEVER `Decimal(<venue float>)`. Guard `None`/missing BEFORE the Decimal edge (`okx.py:249-263`).

### Async→engine handoff (D-19 single-writer, MPSC-safe)
**Source:** `okx.py:271-272` (`self.global_queue.put(fill)` from connector loop thread);
`OkxConnector.spawn` (`okx.py:151-176`)
**Apply to:** VenueAccount stream (cache-write only), reconcile events
Cache writes / `queue.Queue.put` may fire from the connector asyncio thread (safe); the drift
COMPARE + portfolio mutation run ONLY on the engine thread (D-15).

### Business-time stamping (never wall-clock)
**Source:** `okx.py::_ms_to_dt` (`okx.py:111-118`), `FillEvent.time` from venue timestamp (`okx.py:270`)
**Apply to:** reconciling FillEvents (stamp from venue trade ts), metric recording (`event.time`)
Wall-clock carve-out is ONLY for admission-audit / error paths (`portfolio_handler.py:126-130`,
`simulated.py:461`), which never fire on the green oracle run.

### Backtest-inertness (lazy imports, TYPE_CHECKING-only Protocols)
**Source:** `venue.py:40-41` (`LiveConnector` under `TYPE_CHECKING` from ccxt-free `connectors.base`);
`live_trading_system.py:296-300` (all live-arm imports lazy inside the `exchange=='okx'` branch)
**Apply to:** every new live-arm module (reconcile_manager, VenueAccount body). NO
async/connector/SQLAlchemy import on the backtest import path. Gate:
`tests/integration/test_okx_inertness.py` (extend to cover the new modules).

### Reconciling-event generation (D-03 restart) — port nautilus, drive through the idempotent fill path
**Source:** nautilus `live/reconciliation.py:434 create_inferred_order_filled_event` (port, don't import);
mint via `FillEvent.new_fill` exactly like `okx.py:265-272`
**Apply to:** reconcile_manager venue-side restart. `last_qty = venue.filled_qty - order.filled_qty`;
`global_queue.put` on the engine thread at startup BEFORE `status=RUNNING`. Fill-ID dedup prevents
double-apply. NEVER mutate portfolio state directly.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| the cached-venue **drift-compare + halt-decision** body of `VenueAccount` | account | streaming+transform | No in-repo account CACHES venue truth then compares per-symbol drift — `Simulated*` all COMPUTE. Ported from nautilus `live/execution_engine.py` `_check_position_discrepancy:1041` + `reconciliation.py:52`. The cache/stream/REST scaffolding HAS analogs (above); the compare-then-halt state machine is the genuinely-new ~20%. |

## Metadata

**Analog search scope:** `portfolio_handler/account/`, `portfolio_handler/storage/`,
`connectors/`, `execution_handler/exchanges/`, `order_handler/storage/`,
`strategy_handler/storage/`, `price_handler/providers/`, `trading_system/`,
`events_handler/`, `core/enums/`, `core/money.py`
**Files scanned:** 14 analog files read (venue, base account, simulated account, connectors base+okx,
okx exchange, order/portfolio/strategy cached_sql_storage, live_trading_system, okx_provider,
error event, full_event_handler, system+severity enums, money, order enums, portfolio_handler)
**Reference (non-runtime):** nautilus-trader 1.227.0 in `.venv` — `live/reconciliation.py`,
`live/execution_engine.py`, `adapters/okx/`
**Pattern extraction date:** 2026-07-02

## PATTERN MAPPING COMPLETE
