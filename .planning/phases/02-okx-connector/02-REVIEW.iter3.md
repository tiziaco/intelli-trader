---
phase: 02-okx-connector
reviewed: 2026-07-01T12:34:51Z
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
  - tests/integration/test_live_system_okx_wiring.py
  - tests/unit/config/test_okx_settings.py
  - tests/unit/connectors/conftest.py
  - tests/unit/connectors/test_okx_connector.py
  - tests/unit/connectors/test_okx_data_provider.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/portfolio/test_venue_account_wiring.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-01T12:34:51Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Iteration-2 re-review of the OKX connector phase after a fixer pass. I verified every
prior fix by tracing the code, then re-ran the full OKX suite (38 tests) plus the
inertness gate — all green.

**Prior fixes verified correct (not superficial):**
- **CR-01 (session leak):** `stop()` now tears the connector down in a `finally`,
  unconditionally, independent of `_running`; `disconnect()` is a genuine no-op when the
  loop was never built (`_loop is None`). Correct.
- **CR-02 (constructor network I/O + unconditional creds):** the entire OKX stack is now
  gated behind `exchange == 'okx'`; `OkxSettings()` and the ccxt import are never touched
  for other venues, and the blocking `connect()`/`load_markets()` is deferred out of
  `__init__` into `start()`. Locked by `test_live_system_okx_wiring.py`. Correct.
- **WR-01 (None-fee crash):** the `fee.cost is None`/missing case is now coalesced to
  `Decimal("0")` *before* the `to_money` edge. Correct — but incomplete on the sign axis
  (see WR-01 below, a distinct residual defect).
- **WR-02/03/04/06 + IN-01/02/03:** per-trade swallow in the fill loop, the cross-thread
  correlation lock, the `spawn` timeout guard, the `disconnect` reference-retention on
  unclean stop, and the module-scope import cleanups are all present and correct.
- **WR-05 (native candle WS keepalive/reconnect):** correctly deferred to Phase 3.

**No BLOCKERs this iteration.** Nothing incorrect executes on any active path this phase:
the OKX order/fill/candle streams are not started (Phase 4/5 boundary), and the backtest
hot-path inertness gate is green. The findings below are latent defects in the shipped
translation logic that will produce incorrect behavior the moment the live path is
activated, plus test/robustness gaps. They should be fixed before the Phase 3/4/5 live
wiring lands.

## Warnings

### WR-01: OKX fill commission is passed through unnormalized — a negative `fee.cost` violates the portfolio non-negative-commission invariant

**File:** `itrader/execution_handler/exchanges/okx.py:215-217`
**Issue:** The WR-01 fix guarded the `None` case but not the *sign*. The portfolio
transaction validator hard-rejects a signed commission:
`itrader/portfolio_handler/validators.py:63-64` raises `InvalidTransactionError` when
`commission < 0`. `_handle_trade` forwards ccxt's `fee.cost` verbatim
(`commission = to_money(str(fee_cost))`) with no `abs()`/normalization. In today's ccxt,
`okx.parse_trade` sign-flips the raw OKX fee (`Precise.string_neg`) so the unified
`fee.cost` is positive and production happens to work — but the arm trusts that convention
entirely: any negative cost (a ccxt version change, a raw/non-unified payload, a different
channel) yields a negative commission that crashes the fill at the portfolio boundary and
drops it. Worse, the unit test `tests/unit/execution/test_okx_exchange.py:206-224` feeds
the *raw* OKX value `-0.084` as the "unified" `fee.cost` and asserts
`fill.commission == Decimal("-0.084")` — locking in an out-of-contract negative commission
and blocking the defensive fix.
**Fix:**
```python
# Commission is a magnitude; the portfolio validator rejects commission < 0.
fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
fee_cost = fee.get("cost")
commission = abs(to_money(str(fee_cost))) if fee_cost is not None else Decimal("0")
```
Also correct the test fixture to ccxt's positive-cost convention so the expectation no
longer contradicts the portfolio invariant.

### WR-02: `on_order` swallows submit/cancel failures without emitting `FillEvent(REFUSED)` — the order mirror never reconciles

**File:** `itrader/execution_handler/exchanges/okx.py:120-135`
**Issue:** The documented reconciliation contract (mirrored by `SimulatedExchange`, and
called out in the module docstring) is that a rejection flows back as `FillEvent(REFUSED)`
so `OrderHandler.on_fill` transitions the stored order mirror PENDING→REJECTED.
`OkxExchange.on_order` catches every exception, logs it, and emits nothing. A
failed/refused OKX submit therefore leaves the order mirror stuck at PENDING forever with
no reconciliation signal — a silent order-state divergence once the arm is live-wired.
**Fix:** On a caught submit/cancel exception, emit a `FillEvent(REFUSED)` for the
originating `event` onto `global_queue` (mirroring `SimulatedExchange.execute_order`'s
rejection path) rather than only logging, so the mirror reconciles to REJECTED.

### WR-03: only MARKET/LIMIT order types are translated — a STOP/TRAILING_STOP trigger price is silently dropped

**File:** `itrader/execution_handler/exchanges/okx.py:150-158`
**Issue:** `_submit_order` attaches `price` only when `event.order_type is OrderType.LIMIT`.
`OrderType` also defines `STOP` and `TRAILING_STOP` (this framework's brackets are
stop/limit children). A STOP order carries its trigger in `event.price`, but the code
sends `type="stop"` with `price=None` and no `stopPrice`/trigger param — the trigger is
dropped, and the venue either rejects the order or mis-submits it. There is no guard that
rejects unsupported types, so the failure is silent (swallowed by the WR-02 boundary).
**Fix:** Either translate STOP/TRAILING_STOP explicitly (map `event.price` to the ccxt
`triggerPrice`/`stopLossPrice` param) or fail loud with a `validate_order` rejection for
order types the arm does not yet support, rather than mis-submitting them.

### WR-04: OKX spot MARKET BUY submits with `price=None` and will raise `createMarketBuyOrderRequiresPrice`

**File:** `itrader/execution_handler/exchanges/okx.py:150-158`
**Issue:** For a MARKET order the arm passes `price=None`. ccxt's `okx` defaults to
`createMarketBuyOrderRequiresPrice = True`, under which a spot market **buy** requires a
price (to derive cost) or the explicit
`params={'createMarketBuyOrderRequiresPrice': False}` with `amount` as base quantity —
otherwise ccxt raises `InvalidOrder`. Combined with WR-02 (exception swallowed, no REFUSED
fill), a market buy on the default `BTC/USDT` spot symbol would silently never execute and
never reconcile. (Market sells and limit orders are unaffected.)
**Fix:** For market buys, either pass `params={'createMarketBuyOrderRequiresPrice': False}`
and submit the base `amount`, or set the client option once at connect time so `amount` is
unambiguously base quantity; add a test covering the market-buy path.

## Info

### IN-01: `connectors/__init__.py` now eagerly imports `OkxConnector`, coupling the ccxt-free Protocol to `ccxt.pro`

**File:** `itrader/connectors/__init__.py:11-14`
**Issue:** The barrel now does `from .okx import OkxConnector`, which imports `ccxt.pro`.
As a result `from itrader.connectors import LiveConnector` (the pure, ccxt-free Protocol in
`base.py`) transitively pulls `ccxt.pro`. The inertness gate stays green only because no
hot-path module performs a *runtime* barrel import (`venue.py` uses `TYPE_CHECKING`; the
two OKX arms are lazy-loaded). This is a latent fragility: any future hot-path code that
imports `LiveConnector` from the barrel would silently break inertness.
**Fix:** Import `LiveConnector` from `itrader.connectors.base` (not the barrel) in the OKX
arms and any potential hot-path consumer, keeping the ccxt-free Protocol import ccxt-free.

### IN-02: test double `FakeLiveConnector.spawn` still carries the pre-WR-04 `KeyError`-on-timeout bug

**File:** `tests/unit/connectors/conftest.py:99-101`
**Issue:** The real connector's `spawn` was fixed (WR-04) to raise `TimeoutError` when the
loop fails to schedule `_create`. The shared test double still does
`ready.wait(timeout=5.0)` and unconditionally `return holder["task"]` — on a scheduling
hang it raises a bare `KeyError` that masks the real cause. Test-double only (no product
impact), but it undermines diagnosability of a flaky-loop failure in the suite.
**Fix:** Mirror the product guard — check `ready.wait(...)` and raise an explicit
`TimeoutError` instead of falling through to `holder["task"]`.

### IN-03: native candle stream silently swallows OKX subscribe-error/event frames

**File:** `itrader/price_handler/providers/okx_provider.py:208-214`
**Issue:** The candle loop only reads `payload.get("data", [])`. OKX's first WS frame after
`subscribe` is an event frame (`{"event": "subscribe", ...}` on success or
`{"event": "error", "code": ..., "msg": ...}` on failure), neither of which carries
`"data"`. An error frame is therefore dropped with no log — a bad channel/instId/auth
failure looks identical to an idle-but-healthy stream. This robustness gap is adjacent to
the accepted WR-05 (WS keepalive/reconnect) Phase-3 deferral; noting it so it is picked up
with that hardening rather than lost.
**Fix (Phase 3, with WR-05):** inspect `payload.get("event")` and log/raise on `"error"`;
confirm the subscribe ack before entering the data loop.

### IN-04: OKX correlation maps grow unbounded (never pruned on fill/cancel)

**File:** `itrader/execution_handler/exchanges/okx.py:96-97, 162-164`
**Issue:** `_orders_by_venue_id` / `_venue_id_by_order_id` are written on every submit and
never pruned after a terminal fill or cancel, so a long-lived live session accumulates
entries indefinitely. Flagged as Info only — unbounded-growth/memory is out of the v1
review scope (performance) and has no correctness impact on the (offline) path this phase.
**Fix (later):** evict a venue-id correlation once its order reaches a terminal
(filled/cancelled/rejected) state.

---

_Reviewed: 2026-07-01T12:34:51Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
