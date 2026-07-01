---
phase: 02-okx-connector
reviewed: 2026-07-01T13:15:00Z
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
  warning: 0
  info: 6
  total: 6
status: clean
---

# Phase 2: Code Review Report

**Reviewed:** 2026-07-01
**Depth:** standard
**Files Reviewed:** 17
**Status:** clean

## Summary

Final re-review (iteration 3) of the OKX connector phase. This pass adversarially
re-traced the six iteration-2 fixes and the whole live-venue stack against the phase
invariants. **All prior BLOCKERs and WARNINGs are correctly and completely resolved** —
the fixes are real, not superficial, and each is pinned by a passing test:

- **WR-01 (abs-normalised commission + None-cost guard)** — `execution_handler/exchanges/okx.py:261-263`.
  `fee.get("cost")` is None-guarded *before* the Decimal edge, and `abs(to_money(str(...)))`
  normalises the ccxt sign-flip to the non-negative magnitude the portfolio validator
  requires. Covered by `test_none_fee_cost_coalesces_to_zero_commission` and the sign
  assertion in `test_watch_my_trades_fill_becomes_fillevent_on_queue`.
- **WR-02 (FillEvent(REFUSED) on submit/cancel failure)** — `okx.py:146-148`. The `on_order`
  boundary emits REFUSED with the order's own Decimal price/quantity so the mirror
  reconciles PENDING→REJECTED. Verified `OrderEvent.price` is a non-optional `Decimal`
  (never None), so `to_money(price)` inside `new_fill` cannot raise on this path. Covered
  by `test_submit_failure_emits_refused_fill` / `test_cancel_failure_emits_refused_fill`.
- **WR-03 (STOP/TRAILING refusal)** — `okx.py:167-170`. Non-MARKET/LIMIT types raise
  `NotImplementedError`, converted to REFUSED by the boundary rather than silently
  submitting `type="stop"` with a dropped trigger. Covered by the two refusal tests.
- **WR-04 (spot market-buy `createMarketBuyOrderRequiresPrice=False`)** — `okx.py:192-194`.
  Scoped to MARKET+BUY only; sells and limits carry empty params. Covered by four
  dedicated param tests.
- **IN-01 (LiveConnector sourced from ccxt-free `connectors.base`)** — confirmed in all
  three consumers: `execution_handler/exchanges/okx.py:38`, `portfolio_handler/account/venue.py:41`
  (TYPE_CHECKING), and `price_handler/providers/okx_provider.py:55`. Inertness preserved.
- **IN-02 (`spawn` TimeoutError instead of bare KeyError)** — product `connectors/okx.py:173-175`
  and the `FakeLiveConnector` double `conftest.py:104-106` both guard the unscheduled-loop case.

Gate evidence collected this pass:
- 45 OKX tests pass, 1 opt-in live smoke skipped (no demo creds).
- Import-inertness gate green: the backtest root pulls no `ccxt`/`ccxt.pro`/`connectors.okx`.
- Byte-exact SMA_MACD oracle green (3/3) — the OKX stack remains fully off the hot path.

Money discipline (`to_money(str(x))`, never `Decimal(float)`), business-time stamping
(venue ms → tz-aware UTC), SecretStr credential containment, `connectors/` domain-event
freedom, and async cancel-on-disconnect are all upheld. The `disconnect` teardown
correctly retains references on an unclean stop (WR-06) rather than orphaning a live loop.

No BLOCKERs or WARNINGs remain. The items below are the accepted phase deferrals plus one
cosmetic doc-drift nit — all Info.

## Structural Findings (fallow)

No structural-findings block was provided for this iteration.

## Narrative Findings (AI reviewer)

### IN-01: Stale docstring in data provider claims barrel import (contradicts the IN-01 fix)

**File:** `itrader/price_handler/providers/okx_provider.py:33`
**Issue:** The module docstring still states `LiveConnector` is "imported from the
`itrader.connectors` barrel", but the code (line 55) correctly imports from the ccxt-free
`itrader.connectors.base`. This is stale prose left behind when the IN-01 fix moved the
import to `base` (the sibling execution-arm docstring *was* updated to say `base`; this one
was missed). Code is correct; only the comment is wrong. No runtime impact — the provider
is lazy-imported off the hot path regardless.
**Fix:** Update the docstring to read "imported from the ccxt-free `itrader.connectors.base`
module (not the barrel)" to match `execution_handler/exchanges/okx.py`.

### IN-02: Native candle WS keepalive/reconnect (accepted deferral — WR-05)

**File:** `itrader/price_handler/providers/okx_provider.py:198-214`
**Issue:** `_stream_candles` opens the WS with `autoping=False` and no keepalive/reconnect
loop. **Deferred to Phase 3 stream-wiring per accepted deferral WR-05.** Recorded for
traceability only.
**Fix:** Deferred — Phase 3.

### IN-03: Native candle event/error-frame handling (accepted deferral)

**File:** `itrader/price_handler/providers/okx_provider.py:211-214`
**Issue:** Subscribe/error frames (`{"event": "error", ...}` — no `data` key) fall through
to `rows = []` and are silently ignored, so a failed subscription streams no bars with no
log. **Folded into Phase 3 with WR-05 per accepted deferral (prior IN-03).**
**Fix:** Deferred — Phase 3.

### IN-04: Unbounded correlation-map growth (accepted deferral — out of v1 perf scope)

**File:** `itrader/execution_handler/exchanges/okx.py:98-99`
**Issue:** `_orders_by_venue_id` / `_venue_id_by_order_id` are never pruned on terminal
order states. **Out of v1 performance scope per accepted deferral (prior IN-04).**
**Fix:** Deferred.

### IN-05: STOP/TRAILING live trigger translation (accepted deferral — Phase 4/5)

**File:** `itrader/execution_handler/exchanges/okx.py:167-170`
**Issue:** Full triggerPrice/stopLossPrice translation for STOP/TRAILING orders on the live
path is not wired. **Deferred to Phase 4/5.** The interim behavior is correct: the arm fails
loud with `FillEvent(REFUSED)` rather than mis-translating, so the order mirror reconciles.
**Fix:** Deferred — Phase 4/5.

### IN-06: Documented latent fast-fill correlation race + symbol-form assumption

**File:** `itrader/execution_handler/exchanges/okx.py:87-99, 106-109`
**Issue:** Two latent items already documented in-code and gated behind the not-yet-started
stream wiring: (1) the venue can push a fill before `create_order` returns the venue id, so
an early fill resolves to `order=None` and is dropped — the full fix (pending correlation
keyed by clOrdId / late-fill buffering) lands with `connect()` stream wiring; (2) the order
arm passes `event.ticker` through the pass-through `_to_symbol` to ccxt, which keys its
`markets` map by the unified `BTC/USDT` form while the data arm normalises to the `BTC-USDT`
instId form — a caller-form assumption that only bites once real orders submit. Both are
inert this phase (streams not started, no live submits). Recorded for the live-wiring phase.
**Fix:** Address with the `OkxExchange.connect()` stream-wiring work (Phase 4/5); no action
required this phase.

---

_Reviewed: 2026-07-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
