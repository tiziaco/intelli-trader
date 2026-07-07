---
phase: 02-okx-connector
fixed_at: 2026-07-01T13:10:00Z
review_path: .planning/phases/02-okx-connector/02-REVIEW.md
iteration: 2
findings_in_scope: 8
fixed: 6
skipped: 2
status: partial
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-07-01
**Source review:** .planning/phases/02-okx-connector/02-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 8 (0 critical + 4 warning + 4 info; fix_scope = all)
- Fixed: 6
- Skipped: 2

This is the iteration-2 re-review pass. The earlier iteration-1 CR/WR/IN findings
were already fixed and verified correct by the re-reviewer; this report covers the
8 residual/new findings surfaced by the re-review (0 critical, 4 warning, 4 info).

All fixes were applied in an isolated git worktree and verified per-finding: re-read +
`mypy --strict` on every strict-checked touched file, plus the relevant unit/integration
suites. Closing cumulative sweep across the OKX suite (execution, connectors, config,
portfolio wiring), the inertness gate, the live-wiring test, and the byte-exact SMA_MACD
oracle: **48 passed, 1 skipped** (the opt-in live smoke test — OKX demo credentials absent).
The backtest inertness gate (`test_okx_inertness.py`) and the byte-exact oracle
(`test_backtest_oracle.py`, 134 / 46189.87730727451) both stayed green; no
`ResourceWarning`/`RuntimeWarning` escaped the strict suite.

## Fixed Issues

### WR-01: OKX fill commission passed through unnormalized (negative fee violates portfolio invariant)

**Files modified:** `itrader/execution_handler/exchanges/okx.py`, `tests/unit/execution/test_okx_exchange.py`
**Commit:** bb2a41f0
**Applied fix:** Wrapped the ccxt `fee.cost` crossing in `abs()` —
`commission = abs(to_money(str(fee_cost))) if fee_cost is not None else Decimal("0")` — so the
commission is always the non-negative magnitude the portfolio transaction validator requires
(`validators.py` rejects `commission < 0`). Updated the unit test
`test_watch_my_trades_fill_becomes_fillevent_on_queue` to assert the positive magnitude
(`fill.commission == abs(to_money(str(raw["fee"])))` and `>= Decimal("0")`) instead of locking
in the raw negative `-0.084`. Money-policy preserved (string edge, never `Decimal(float)`).

### WR-02: `on_order` swallowed submit/cancel failures without emitting `FillEvent(REFUSED)`

**Files modified:** `itrader/execution_handler/exchanges/okx.py`, `tests/unit/execution/test_okx_exchange.py`
**Commit:** c907acb7
**Applied fix:** The `on_order` boundary `except` now emits a `FillEvent(REFUSED)` for the
originating order (order's own Decimal price/quantity, `commission=Decimal("0")`, no `time=` so
it inherits the order's decision time) in addition to logging — mirroring
`SimulatedExchange._emit_rejection`. This satisfies the reconciliation contract so
`OrderHandler.on_fill` can transition the stored order mirror PENDING→REJECTED instead of it
being stuck PENDING forever. Added two tests covering failed submit and failed cancel.

### WR-03: STOP/TRAILING_STOP trigger price silently dropped (only MARKET/LIMIT translated)

**Files modified:** `itrader/execution_handler/exchanges/okx.py`, `tests/unit/execution/test_okx_exchange.py`
**Commit:** 95c8b41e
**Applied fix:** Added a fail-loud guard at the top of `_submit_order` that raises
`NotImplementedError` for any order type other than MARKET/LIMIT. Combined with the WR-02
boundary, an unsupported STOP/TRAILING_STOP order now surfaces as a `FillEvent(REFUSED)` (mirror
reconciles) rather than being mis-submitted as `type="stop"` with `price=None` (dropped trigger).
Full trigger-price translation (ccxt `triggerPrice`/`stopLossPrice`) is documented as deferred to
the live order path (Phase 4/5) — the defensive guard is the correct interim behaviour per the
review guidance. Added tests asserting STOP and TRAILING_STOP are REFUSED and `create_order` is
not called.

### WR-04: OKX spot MARKET BUY submitted with `price=None` (raises `createMarketBuyOrderRequiresPrice`)

**Files modified:** `itrader/execution_handler/exchanges/okx.py`, `tests/unit/execution/test_okx_exchange.py`
**Commit:** 9e9b6e3e
**Applied fix:** For a MARKET BUY the arm now passes
`params={"createMarketBuyOrderRequiresPrice": False}` (submitting `amount` as base quantity, which
the arm already does), so ccxt's okx does not require a price and does not raise `InvalidOrder`.
Market sells and limit orders pass an empty `params` and are unaffected. `params` is passed as a
keyword arg to `create_order` so the existing positional-arg tests are unaffected. Added
`Side` to the enum import. Added three tests: market-buy sets the override, market-sell does not,
limit passes empty params.

### IN-01: `connectors/__init__.py` barrel eagerly imports `OkxConnector`, coupling the ccxt-free Protocol to `ccxt.pro`

**Files modified:** `itrader/execution_handler/exchanges/okx.py`, `itrader/price_handler/providers/okx_provider.py`, `itrader/portfolio_handler/account/venue.py`
**Commit:** 3651151c
**Applied fix:** Changed all three `LiveConnector` consumers to import from the ccxt-free
`itrader.connectors.base` module instead of the `itrader.connectors` barrel (the barrel eagerly
imports `OkxConnector`/`ccxt.pro`). This includes the hot-path `venue.py` (still `TYPE_CHECKING`,
now sourced from `base` for defence in depth), the lazy-loaded order arm `execution/okx.py`, and
the lazy-loaded data arm `okx_provider.py`. Updated the relevant module docstrings. Verified the
backtest inertness gate and the byte-exact oracle stay green — inertness is not broken by this
change (it is strengthened).

### IN-02: test double `FakeLiveConnector.spawn` carried the pre-fix `KeyError`-on-timeout bug

**Files modified:** `tests/unit/connectors/conftest.py`
**Commit:** 0583fcbb
**Applied fix:** Mirrored the product guard (`OkxConnector.spawn`) in the shared test double —
`spawn` now checks `ready.wait(...)` and raises an explicit `TimeoutError` on a scheduling hang
instead of falling through to `holder["task"]` (a bare `KeyError` that masks the real cause).
Test-double only; all connectors tests remain green.

## Skipped Issues

### IN-03: native candle stream silently swallows OKX subscribe-error/event frames

**File:** `itrader/price_handler/providers/okx_provider.py:208-214`
**Reason:** deferred by design — the review itself classifies this as **"Fix (Phase 3, with
WR-05)"**. It is adjacent to the accepted WR-05 (WS keepalive/reconnect) Phase-3 deferral and is
best implemented together with that hardening (inspect `payload.get("event")`, confirm the
subscribe ack before entering the data loop). No correctness impact this phase — the native candle
stream is not started (Phase 3/5 boundary). Not fixed here to avoid a half-done WS robustness
change that would need reworking when WS keepalive/reconnect lands.
**Original issue:** The candle loop only reads `payload.get("data", [])`; an OKX
`{"event": "error", ...}` frame (bad channel/instId/auth) carries no `"data"` and is dropped with
no log, looking identical to an idle-but-healthy stream.

### IN-04: OKX correlation maps grow unbounded (never pruned on fill/cancel)

**File:** `itrader/execution_handler/exchanges/okx.py:96-97, 162-164`
**Reason:** deferred by design — the review classifies this as **Info / "Fix (later)"**, explicitly
noting unbounded-growth/memory is **out of the v1 review scope (performance)** with **no
correctness impact** on the offline path this phase. The streams are not started this phase, so the
maps do not actually grow. The correct fix (evict a venue-id correlation once its order reaches a
terminal filled/cancelled/rejected state) belongs with the live-wiring stream lifecycle, not this
translation-hardening pass.
**Original issue:** `_orders_by_venue_id` / `_venue_id_by_order_id` are written on every submit and
never pruned after a terminal fill/cancel, so a long-lived live session accumulates entries
indefinitely.

---

_Fixed: 2026-07-01T13:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
