---
phase: 02-okx-connector
fixed_at: 2026-07-01T00:00:00Z
review_path: .planning/phases/02-okx-connector/02-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 10
skipped: 1
status: partial
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-07-01
**Source review:** .planning/phases/02-okx-connector/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (2 critical + 6 warning + 3 info; fix_scope = all)
- Fixed: 10
- Skipped: 1

All fixes verified per-finding: re-read + `ast.parse` syntax check, `mypy --strict`
on every strict-checked touched file (execution `okx.py`, connector `okx.py`,
`okx_provider.py` — `live_trading_system.py` is mypy-deferred by design), and the
relevant unit/integration suites. Closing sweep: **34 passed, 1 skipped** — the
byte-exact SMA_MACD oracle (`test_backtest_oracle.py`) and the backtest inertness
gate (`test_okx_inertness.py`) both stayed green, and no `ResourceWarning`/
`RuntimeWarning` escaped the strict suite.

## Fixed Issues

### CR-01: `stop()` leaks the authenticated OKX session when the system was never started

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 8f11c821
**Applied fix:** Wrapped the `stop()` body in `try/finally` and moved the
`connector.disconnect()` teardown into the `finally`, so it runs on every return
path — including the early "not running" exit, the thread-join-timeout `return
False`, and the normal stop. `disconnect()` is a safe no-op when the connector was
never connected (its loop is `None`).

### CR-02: Unconditional network connect + hard credential requirement in the constructor

**Files modified:** `itrader/trading_system/live_trading_system.py`,
`tests/integration/test_live_system_okx_wiring.py`
**Commit:** 906dd9a4
**Applied fix:** Gated the entire OKX wiring block (imports, `OkxSettings()`,
connector, and the three arms) behind `if self.exchange == 'okx'`, initialising
`_okx_connector`/`_okx_exchange`/`_okx_data_provider`/`_venue_account` to `None`
otherwise. Removed the constructor `connect()` call and deferred it into `start()`
(after `_initialize_live_session()`), inside the existing `try` whose `except` sets
`SystemStatus.ERROR` and returns `False` — so construction performs no OKX network
I/O and needs no OKX credentials for a non-OKX venue, and a connect failure never
raises out of `__init__`. Added `test_live_system_okx_wiring.py`: constructs
`LiveTradingSystem(exchange='binance')` with the `OKX_API_*` env stripped, asserts
no raise, all OKX arms `None`, no `'okx'` execution arm, and that `stop()` before
`start()` is a clean no-op.

### WR-01: A None fee cost crashes the fill stream (`Decimal('None')` → `InvalidOperation`)

**Files modified:** `itrader/execution_handler/exchanges/okx.py`,
`tests/unit/execution/test_okx_exchange.py`
**Commit:** be92c342
**Applied fix:** Coalesced a missing/`None` fee cost to `Decimal("0")` before the
`to_money` edge (money policy: never Decimal-parse a non-numeric). Added a
regression test asserting a `fee: {"cost": None}` fill yields a zero commission
rather than raising `InvalidOperation`.

### WR-02: `_stream_fills` has no per-trade error handling — one bad trade kills the stream

**Files modified:** `itrader/execution_handler/exchanges/okx.py`
**Commit:** 5e8f76a0
**Applied fix:** Wrapped the per-trade `_handle_trade(trade)` call in a
swallow-and-log `try/except Exception`, matching the `on_order` boundary policy, so
a single malformed trade is logged and skipped instead of terminating the
forever-loop and silently dropping all subsequent fills.

### WR-03: Fill-order correlation is a cross-thread race — fast fills can be dropped

**Files modified:** `itrader/execution_handler/exchanges/okx.py`
**Commit:** 512f037c
**Status:** fixed: requires human verification
**Applied fix:** Added `self._correlation_lock = threading.Lock()` and guarded every
write (`_submit_order`) and read (`_cancel_order`, `_handle_trade`) of the two
correlation dicts, implementing the review's documented minimum (synchronise the
cross-thread dict access). The residual fast-fill race (venue pushes a fill before
`create_order` returns the venue id → fill resolves to `order=None` and is dropped)
is **not** closed by a lock alone; the full fix (pending correlation keyed by
`clOrdId` set before the submit RPC, and/or brief buffering of unmatched fills)
lands with `OkxExchange.connect()` stream wiring. Documented inline. Latent this
phase (streams are not started), so behaviour is preserved — human verification
recommended when the stream seam is wired.

### WR-04: `OkxConnector.spawn()` returns `holder["task"]` without checking the wait succeeded

**Files modified:** `itrader/connectors/okx.py`
**Commit:** 096d9435
**Applied fix:** Replaced the unchecked `ready.wait(...)` + `return holder["task"]`
with `if not ready.wait(timeout=_CALL_TIMEOUT): raise TimeoutError(...)`, so a
loop-scheduling timeout surfaces as an explicit `TimeoutError` instead of a bare
`KeyError` that masks the real failure.

### WR-06: `disconnect()` orphans a still-running loop on join timeout

**Files modified:** `itrader/connectors/okx.py`
**Commit:** 8c84eed4
**Status:** fixed: requires human verification
**Applied fix:** In the `finally`, only close the loop and null the
loop/thread/client/stream-task references after a **confirmed** clean stop
(`not thread.is_alive()` and `not loop.is_running()`). On an unclean stop (join
timeout), log a warning and retain the references so a subsequent `disconnect()`
can retry, instead of orphaning a still-running daemon loop with no handle. The
unclean-stop branch is lifecycle/state logic not exercised by the existing suite —
human verification of the timeout path recommended.

### IN-01: `validate_symbol` checks the raw symbol, not the OKX-normalised symbol

**Files modified:** `itrader/execution_handler/exchanges/okx.py`
**Commit:** f5f76075
**Applied fix:** Routed the `markets` membership check through the same
`_to_symbol` helper the submit path uses (`self._to_symbol(symbol) in markets`) and
documented the ccxt-unified caller-form contract. `_to_symbol` is pass-through
today, so this is behaviour-preserving while keeping validate and submit on one
normalisation as the helper grows.

### IN-02: Redundant `and page` in the backfill pagination condition

**Files modified:** `itrader/price_handler/providers/okx_provider.py`
**Commit:** 04e4c680
**Applied fix:** Dropped the dead `and page` clause (`len(page) == limit` with
`limit > 0` already implies `page` is truthy) — `while len(page) == limit:`.

### IN-03: `_submit_order` narrows Decimal quantity/price to float before venue rounding

**Files modified:** `itrader/execution_handler/exchanges/okx.py`,
`tests/unit/execution/test_okx_exchange.py`
**Commit:** ed6bcbd8
**Applied fix:** Passed the Decimal's string form (`str(event.quantity)` /
`str(event.price)`) to `amount_to_precision` / `price_to_precision` instead of
`float(...)`, keeping the outbound value out of binary float entirely (ccxt
re-rounds and returns the authoritative string either way). Updated the two
`assert_called_once_with(..., float(...))` assertions to `str(...)`.

## Skipped Issues

### WR-05: Native candle WS has no keepalive/ping and no reconnect (`autoping=False`)

**File:** `itrader/price_handler/providers/okx_provider.py:198-214`
**Reason:** skipped: fix would change phase behavior. The correct fix is a design
change co-owned by Phase 3 (a reconnect loop that re-subscribes on close, plus
OKX's app-level `"ping"`/`"pong"` text-frame keepalive — OKX's business channel
expects app-level ping, not aiohttp WS control-frame `heartbeat`/`autoping`). There
is no test exercising the candle stream, the stream is not started this phase, and a
partial `autoping`/`heartbeat` toggle risks masking the idle-disconnect without
proving a fix. Deferred to the Phase-3 stream-wiring seam that co-owns this code,
where it can be built and tested end-to-end.
**Original issue:** `session.ws_connect(url, autoping=False)` disables aiohttp's
PONG-on-PING and the loop never sends OKX's app-level ping nor handles server pings;
OKX closes idle sockets after ~30s, so a low-frequency channel (e.g. `1d` candles)
dies between bars and the `async for msg in ws` ends, terminating the stream task
with no reconnect — the live candle stream silently stops.

---

_Fixed: 2026-07-01_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
