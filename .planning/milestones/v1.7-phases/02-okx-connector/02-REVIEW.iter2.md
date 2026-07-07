---
phase: 02-okx-connector
reviewed: 2026-07-01T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - itrader/config/okx_settings.py
  - itrader/connectors/__init__.py
  - itrader/connectors/base.py
  - itrader/connectors/okx.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/trading_system/live_trading_system.py
  - tests/integration/test_okx_inertness.py
  - tests/integration/test_okx_smoke.py
  - tests/unit/config/test_okx_settings.py
  - tests/unit/connectors/conftest.py
  - tests/unit/connectors/test_okx_connector.py
  - tests/unit/connectors/test_okx_data_provider.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/portfolio/test_venue_account_wiring.py
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-07-01
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

The OKX connector stack is well-documented and the credential/inertness/sandbox-routing
disciplines are largely sound: `SecretStr` end-to-end, `to_money(str(x))` at every venue
edge, host-based (not header-based) WS demo routing, and a subprocess-based backtest
inertness gate that actually proves lazy import. The unit tests are thorough on the happy
paths and the two highest-severity threats (sandbox misroute, Decimal(float) artifact).

The defects cluster in two areas the tests do **not** exercise: (1) the live composition
root in `LiveTradingSystem.__init__`, which now performs an unconditional, credential-gated
**network** connect to OKX in a constructor and then leaks that authenticated session on
the common teardown path; and (2) the streaming/async edges of the arms, where a
None-valued fee, a fast fill, a `spawn` timeout, or an idle WS silently crash or drop data.
No test constructs a `LiveTradingSystem`, so the two critical wiring defects are entirely
uncaught.

## Critical Issues

### CR-01: `stop()` leaks the authenticated OKX session when the system was never started

**File:** `itrader/trading_system/live_trading_system.py:226-227, 471-509`
**Issue:** The connector is connected inside `__init__` (`self._okx_connector.connect()`
spins a daemon thread + event loop and builds a live ccxt.pro client with an open REST
session). But the only call site that tears it down lives in `stop()` **after** an early
return:

```python
def stop(self, timeout=10.0):
    if not self._running:
        self.logger.warning('Live trading system is not running')
        return True          # <-- returns BEFORE connector.disconnect()
    ...
    connector = getattr(self, '_okx_connector', None)
    if connector is not None:
        connector.disconnect()
```

Any lifecycle that constructs the system but never calls `start()` (validation, a failed
`start()`, or simply inspecting status) and then calls `stop()` — or is garbage-collected —
leaves the daemon thread, the event loop, and the **authenticated** ccxt.pro session open.
Under the strict `filterwarnings=["error"]` suite this surfaces as a `ResourceWarning`; in
production it is a dangling live/demo venue connection per abandoned instance.
**Fix:** Disconnect the connector unconditionally, independent of `_running`:
```python
def stop(self, timeout=10.0):
    connector = getattr(self, '_okx_connector', None)
    try:
        if not self._running:
            self.logger.warning('Live trading system is not running')
            return True
        # ... existing thread-join shutdown ...
    finally:
        if connector is not None:
            try:
                connector.disconnect()
            except Exception as e:
                self.logger.error(f'Error disconnecting OKX connector: {e}')
```
Better still, do not `connect()` in `__init__` at all — move it into `start()` and pair it
with the `stop()` teardown (see CR-02).

### CR-02: Unconditional network connect + hard credential requirement in the constructor

**File:** `itrader/trading_system/live_trading_system.py:220-240`
**Issue:** `__init__` unconditionally runs:
```python
self._okx_connector = OkxConnector(OkxSettings())   # requires OKX_API_* env
self._okx_connector.connect()                        # builds client + load_markets() = NETWORK
```
`OkxSettings()` raises `pydantic.ValidationError` if `OKX_API_KEY/SECRET/PASSPHRASE` are
absent, and `connect()` calls `_build_client()` → `await self._client.load_markets()`, a
live REST round-trip. This happens regardless of the `exchange` argument (which defaults to
`'binance'`), so **constructing a `LiveTradingSystem` for any venue now hard-requires OKX
credentials and network reachability**, and performs blocking network I/O inside a
constructor with no surrounding try/except. A construction-time failure (no creds, OKX
unreachable, rate limit) aborts the entire live system before it is usable. This also
directly contradicts the phase's inertness intent for the non-OKX case.
**Fix:** Gate the OKX wiring and defer the network step out of `__init__`:
```python
# In __init__: construct the arms, do NOT connect.
self._okx_connector = OkxConnector(OkxSettings()) if self.exchange == 'okx' else None
...
# In start(), after _initialize_live_session():
if self._okx_connector is not None:
    self._okx_connector.connect()
```
Wrap `connect()` so a failure sets `SystemStatus.ERROR` rather than raising out of a
constructor.

## Warnings

### WR-01: A None fee cost crashes the fill stream (`Decimal('None')` → `InvalidOperation`)

**File:** `itrader/execution_handler/exchanges/okx.py:192-200`
**Issue:**
```python
fee = trade.get("fee") or {}
fee_cost = fee.get("cost", 0) if isinstance(fee, dict) else 0
...
commission=to_money(str(fee_cost)),
```
ccxt frequently emits `fee: {"cost": None, ...}` (fee not yet known). `fee.get("cost", 0)`
returns `None` (the key is present), so `to_money(str(None))` becomes `Decimal("None")`,
which raises `decimal.InvalidOperation`. `_handle_trade` is called from `_stream_fills`'s
`while True` loop with **no per-trade guard**, so a single such fill kills the entire fill
stream task — silent loss of all subsequent fills (position/cash desync).
**Fix:** Coalesce a missing/None cost to zero before the Decimal edge:
```python
fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
fee_cost = fee.get("cost")
commission = to_money(str(fee_cost)) if fee_cost is not None else Decimal("0")
```

### WR-02: `_stream_fills` has no per-trade error handling — one bad trade kills the stream

**File:** `itrader/execution_handler/exchanges/okx.py:204-209`
**Issue:** `_stream_fills` awaits `watch_my_trades()` and calls `_handle_trade(trade)` in a
bare loop. Any exception from `_handle_trade` (WR-01, or a `FillEvent.new_fill`
`FillStatus`/enum failure, or a `queue.Full`) propagates out of the `while True`, ending the
spawned task. In live mode the fill stream just stops with no restart and no visible error
(the task exception is only retrieved when the connector cancels-and-gathers at disconnect).
**Fix:** Wrap the per-trade call so a malformed trade is logged and skipped, matching the
`on_order` boundary-swallow policy:
```python
for trade in trades:
    try:
        self._handle_trade(trade)
    except Exception:
        self.logger.error("OKX fill translation failed — skipping trade", exc_info=True)
```

### WR-03: Fill-order correlation is a cross-thread race — fast fills can be dropped

**File:** `itrader/execution_handler/exchanges/okx.py:145-148, 178-182`
**Issue:** `_submit_order` populates `self._orders_by_venue_id[venue_id]` on the **engine
thread**, only after `connector.call(create_order(...))` returns. `_handle_trade` reads that
map on the **connector loop thread**. For a market order that fills immediately, the venue
can push the fill on `watch_my_trades` before (or concurrently with) the `create_order`
acknowledgement that yields `venue_id`. The fill then resolves to `order is None` and is
dropped as "unknown venue order" — a lost fill and a permanent position/cash desync. The two
correlation dicts are also mutated/read across threads with no synchronization.
**Fix:** Register a pending correlation keyed by client order id (`clOrdId`) that is set
*before* the submit RPC, and/or buffer unmatched fills briefly for late correlation. At
minimum, guard the dict writes/reads with a lock and document the ordering assumption. (Note:
the streams are not started this phase, so this is latent — but it lands as soon as
`OkxExchange.connect()` is wired.)

### WR-04: `OkxConnector.spawn()` returns `holder["task"]` without checking the wait succeeded

**File:** `itrader/connectors/okx.py:157-171`
**Issue:**
```python
self._loop.call_soon_threadsafe(_create)
ready.wait(timeout=_CALL_TIMEOUT)
return holder["task"]
```
If `ready.wait(...)` times out (loop congested/not running), `_create` never ran and
`holder["task"]` raises a bare `KeyError`, masking the real "loop not scheduling" failure
behind a confusing traceback.
**Fix:**
```python
if not ready.wait(timeout=_CALL_TIMEOUT):
    raise TimeoutError("OKX connector loop did not schedule the spawned task in time")
return holder["task"]
```

### WR-05: Native candle WS has no keepalive/ping and no reconnect (`autoping=False`)

**File:** `itrader/price_handler/providers/okx_provider.py:198-214`
**Issue:** `session.ws_connect(url, autoping=False)` disables aiohttp's automatic
PONG-on-PING, and the loop never sends OKX's app-level `"ping"` text nor handles a server
ping. OKX closes idle sockets after ~30s; for a low-frequency channel (e.g. `1d` candles)
the socket dies between bars and `async for msg in ws` simply ends, terminating the stream
task with no reconnect. There is also no handling for OKX subscription-error frames or a
non-`data` payload. Result: the live candle stream silently stops.
**Fix:** Enable keepalive (`autoping=True` plus `heartbeat=...`), or send OKX's `"ping"`
text on an interval and treat `"pong"`/error frames explicitly; wrap the stream in a
reconnect loop that re-subscribes on close. (Phase-3 co-owns this seam, but the current body
will not survive an idle interval.)

### WR-06: `disconnect()` orphans a still-running loop on join timeout

**File:** `itrader/connectors/okx.py:196-208`
**Issue:** After `call_soon_threadsafe(self._loop.stop)` and `self._thread.join(timeout=...)`,
the `finally` block only closes the loop `if not self._loop.is_running()`, then
unconditionally sets `self._loop = None` / `self._thread = None`. If the join times out (a
stream task swallowing `CancelledError`, or a hung `client.close()`), the loop is still
running, is never closed, and its reference is dropped — an orphaned daemon thread + event
loop with no handle to recover or close it.
**Fix:** On join timeout, log a warning and retain the references (or force a second stop)
rather than nulling them; only null after a confirmed clean stop.

## Info

### IN-01: `validate_symbol` checks the raw symbol, not the OKX-normalised symbol

**File:** `itrader/execution_handler/exchanges/okx.py:292-302`
**Issue:** `validate_symbol` does `symbol in markets` against the loaded ccxt markets, but
`_submit_order`/`_to_symbol` may hand a different form than the `markets` keys (ccxt keys are
unified `BTC/USDT`, while the OKX data arm normalises to `BTC-USDT`). A valid symbol in one
form can be rejected/accepted inconsistently.
**Fix:** Normalise through the same helper the submit path uses before the membership check,
or document that callers pass the ccxt-unified form.

### IN-02: Redundant `and page` in the backfill pagination condition

**File:** `itrader/price_handler/providers/okx_provider.py:265`
**Issue:** `while len(page) == limit and page:` — `len(page) == limit` (with `limit=1000 > 0`)
already implies `page` is truthy, so `and page` is dead.
**Fix:** Drop the redundant clause: `while len(page) == limit:`.

### IN-03: `_submit_order` narrows Decimal quantity/price to float before venue rounding

**File:** `itrader/execution_handler/exchanges/okx.py:135, 140`
**Issue:** `client.amount_to_precision(symbol, float(event.quantity))` and the price analog
cast the Decimal to `float` before ccxt re-rounds to lot/tick and returns a string. This is
the documented ccxt contract (the string is authoritative), so it is not a money-policy
violation, but the intermediate `float()` is an avoidable narrowing on the outbound edge.
**Fix:** Pass the Decimal's string form where the ccxt helper accepts it
(`amount_to_precision(symbol, str(event.quantity))`) to keep the value out of binary float
entirely.

---

_Reviewed: 2026-07-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
