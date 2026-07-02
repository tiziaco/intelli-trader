---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
verified: 2026-07-02T20:10:23Z
status: gaps_found
score: 5/8 must-haves verified (2 failed, 1 uncertain)
overrides_applied: 0
gaps:
  - truth: "RECON-02: Partial-fill handling is correct and idempotent with the venue as source of truth in live"
    status: failed
    reason: >
      CR-01 (code review, independently confirmed): OkxExchange.connect() is the ONLY spawn
      point for the live fill/order streams (connector.spawn(self._stream_fills())
      / _stream_orders() at okx.py:585-586). It is never invoked. ExecutionHandler.init_exchanges()
      only connects exchanges built at construction time (simulated/csv/ccxt); the 'okx' arm is
      registered into execution_handler.exchanges['okx'] AFTER construction
      (live_trading_system.py:375), so it is never in that connect loop. LiveTradingSystem.start()
      (~lines 984-1035) calls _okx_connector.connect(), _okx_data_provider.start_stream(), and
      _venue_account.start_streaming()/snapshot() — but never _okx_exchange.connect(). A repo-wide
      grep for "_okx_exchange.connect(" returns zero results. Net effect: on the real/sandbox path,
      orders rest/execute on the venue but no FillEvent ever streams back into the engine — the
      order mirror stays PENDING forever and the portfolio never updates positions/cash from real
      fills. The dedup/accumulation/terminalize logic itself (okx.py _handle_trade,
      reconcile_manager.py _apply_executed) is correctly implemented and unit-tested in isolation,
      but is unreachable in the live system as composed today.
    artifacts:
      - path: "itrader/trading_system/live_trading_system.py"
        issue: "start() (~lines 984-1035) never calls self._okx_exchange.connect() — the order-arm fill/order streams are never spawned"
      - path: "itrader/execution_handler/exchanges/okx.py"
        issue: "connect() (line 575) is the sole spawn site for _stream_fills/_stream_orders (lines 585-586); confirmed unreachable from the live composition root"
      - path: "itrader/execution_handler/execution_handler.py"
        issue: "init_exchanges() (lines 132-181) only connects construction-time exchanges; 'okx' is registered post-construction and is never in that loop"
    missing:
      - "In LiveTradingSystem.start(), call self._okx_exchange.connect() (and handle a failed ConnectionResult) alongside the existing _okx_connector.connect() / _okx_data_provider.start_stream() / _venue_account.start_streaming() calls, before status=RUNNING"
  - truth: "RES-01: Live resilience — websocket reconnect with gap recovery is in place across every venue stream (fills, orders, candles)"
    status: failed
    reason: >
      The reconnect supervisor + failure classification code for the order arm
      (_stream_fills/_stream_orders, wrapped via _run_stream_supervisor in okx.py) is correctly
      implemented and unit-tested (tests/unit/execution/test_reconnect_resilience.py, 12 passed),
      but per CR-01 it is never spawned in the live system (connect() is never called), so it never
      activates in production. Only the data-arm supervisor (OkxDataProvider._stream_candles,
      wrapped and reachable via _okx_data_provider.start_stream(), which IS called in start()) is
      live-active. Additionally WR-04 (confirmed): _maybe_resume_after_reconnect (live_trading_system.py:615-638)
      only calls self._venue_account.snapshot() on resume — it never re-runs the two-sided
      VenueReconciler.reconcile() that start() runs before RUNNING, even though the docstring says
      "a fresh REST snapshot + reconcile" and resume_submission() logs "REST reconcile complete".
      This is a direct violation of the 05-08 must-have "resumes only after reconnect + a fresh REST
      snapshot/reconcile."
    artifacts:
      - path: "itrader/execution_handler/exchanges/okx.py"
        issue: "Reconnect supervisor on _stream_fills/_stream_orders is correct but unreachable (never spawned) — same root cause as CR-01"
      - path: "itrader/trading_system/live_trading_system.py"
        issue: "_maybe_resume_after_reconnect (lines 615-638) only re-snapshots VenueAccount balances; never re-invokes VenueReconciler.reconcile()"
    missing:
      - "Fix CR-01 so the order-arm reconnect supervisor is actually live-active"
      - "Either invoke VenueReconciler.reconcile() inside _maybe_resume_after_reconnect before resume_submission(), or correct the docstring/log to state only a balance snapshot occurs"
deferred: []
human_verification:
  - test: "Run the opt-in, network-gated live-sandbox suite (tests/e2e/test_okx_sandbox_recon.py) against a real OKX demo/sandbox account with OKX_API_* credentials set, after CR-01 is fixed"
    expected: "Order I/O + VenueAccount reconciliation + persistence live-drive + restart rehydration are validated end-to-end against the real OKX sandbox venue (RECON-06), including a real fill streaming back through the fixed connect() wiring"
    why_human: "Requires live network access and OKX_API_* sandbox credentials; the suite is deliberately skipif-no-creds and was not exercised in this verification pass. Also currently would not exercise fills at all until CR-01 is fixed."
---

# Phase 5: Real Sandbox Path — Reconciliation, Persistence, Live Drive — Verification Report

**Phase Goal:** Real sandbox path — reconciliation, persistence, live drive. Make the live OKX(-sandbox)
path correct: cached VenueAccount + drift-halt reconciliation, idempotent live fill ingestion, drive the
v1.6 operational store off the real feed, two-sided restart rehydration, and reconnect resilience.
**Verified:** 2026-07-02T20:10:23Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### CR-01 Independent Confirmation (BLOCKER)

The orchestrator's CR-01 finding was independently re-derived from the codebase, not taken on faith:

- `OkxExchange.connect()` (`itrader/execution_handler/exchanges/okx.py:575-594`) is the **only** call
  site that spawns `self._stream_fills()` / `self._stream_orders()` via `connector.spawn(...)`
  (lines 585-586). Both are `async def` coroutines; nothing else in the codebase awaits or spawns them
  (`grep -rn "_stream_fills\|_stream_orders" itrader/` shows only their definitions and the two spawn
  calls inside `connect()`).
- `grep -rn "_okx_exchange\.connect(" itrader/` returns **zero** matches anywhere in the repository.
- `ExecutionHandler.init_exchanges()` (`itrader/execution_handler/execution_handler.py:132-181`) only
  connects exchanges it builds at construction time (`simulated`/`csv`/`ccxt`); `'okx'` is registered
  into `execution_handler.exchanges['okx']` at `live_trading_system.py:375`, **after** construction —
  so it is never part of that connect loop.
- `LiveTradingSystem.start()` (`itrader/trading_system/live_trading_system.py:960-1035`) calls, in
  order: `self._okx_connector.connect()` (991), `self.feed.warmup(...)` + `self._okx_data_provider.start_stream()`
  (999-1000), and `self._venue_account.snapshot()` + `self._venue_account.start_streaming()` (1009-1011),
  followed by the two-sided `VenueReconciler.reconcile()` call (1017-1035). **`self._okx_exchange.connect()`
  is never called anywhere in this method or elsewhere in `start()`.**

**Verdict: CR-01 is CONFIRMED.** On the real/sandbox path as currently composed, orders submitted through
`on_order` rest or execute on the venue, but no `FillEvent` ever streams back to the engine. `OrderHandler.on_fill`
/ `PortfolioHandler.on_fill` never fire from real venue activity; the order mirror stays `PENDING` forever
and the portfolio never updates positions/cash from a real fill. This breaks the phase's core live
deliverable (RECON-02) and cascades into RES-01 (the order-arm reconnect supervisor built in 05-08 is
correctly implemented but never live-active, since it lives inside the never-spawned `_stream_fills`/
`_stream_orders` coroutines). No test in the repository exercises `LiveTradingSystem.start()` with the
OKX exchange wired end-to-end and asserts the fill stream is spawned — all 57 unit tests + 12 integration
tests that pass for Phase 5 test the reconciliation/idempotency/persistence *logic* in isolation via a
fake connector, never the actual composition-root wiring, which is exactly why this gap was not caught
by the test suite.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | **RECON-01**: `VenueAccount` caches connector balance/margin/position streams and reconciles per-symbol drift under 1:1 account:portfolio (cache, never compute) | VERIFIED | `itrader/portfolio_handler/account/venue.py` (323 lines) — `snapshot()`, `_stream_account`, RLock cache, `to_money(str(x))` at every float boundary, `StateError` on unsnapshotted read. `PortfolioHandler._compare_symbol_drift` (portfolio_handler.py:698-757) runs the compare on the engine thread via `on_fill` + periodic BAR sweep. Composition-root wiring confirmed at `live_trading_system.py:1009-1013` (`venue_account.snapshot()`/`start_streaming()`, portfolio.account link). 57 unit tests pass (`test_venue_account_cache.py`, `test_venue_account_drift.py`). |
| 2 | **RECON-02**: Partial-fill handling is correct and idempotent (dedup, accumulation, terminalize-only-on-full-fill), venue is source of truth in live | ✗ FAILED | CR-01 (above). Logic is correct and unit-tested in isolation (`okx.py::_handle_trade` `_seen_trade_ids` dedup, `reconcile_manager.py::_apply_executed` accumulation) but is **unreachable in the live system** — the stream that would deliver real fills is never started. |
| 3 | **RECON-03**: Halt-and-alert default, auto-correct only within precision-epsilon tolerance band | VERIFIED (with WARNING) | `itrader/portfolio_handler/reconcile/drift.py::is_within_single_unit_tolerance` + `_compare_symbol_drift` correctly implement within-band-silent / beyond-band-unexplained-halt / beyond-band-adopted branches; 15 tests pass (`test_drift_halt_policy.py`). **WR-01 confirmed** (see below): `halt()`'s idempotency guard is non-atomic across two lock acquisitions, so concurrent halt callers from different threads can double-fire the CRITICAL alert and clobber `halt_reason`. This does not invalidate the halt decision logic itself, but undermines the documented "idempotent — first halt wins" contract. |
| 4 | **RECON-04**: v1.6 operational store (order/portfolio-state/signal) driven by the real OKX feed, split sync/async write paths, create/terminalize sync-durable | VERIFIED (mechanism) | `CachedSqlOrderStorage` (sync, store-first) + `CachedSqlSignalStorage` (async/best-effort) wired at the composition root; BAR-keyed `_record_bar_metrics` confirmed keying on `EventType.BAR`/`event.time`. Proven via `test_store_live_drive.py` (4 passed) and `test_live_bar_metrics.py` (2 passed) using a fake connector that directly drives events. **Caveat**: the *terminalize-on-real-fill* half of this write path is never exercised in production today because of CR-01 — order create (from `SignalEvent`/`OrderEvent`) and BAR-driven signal/metrics writes work off the real feed independent of CR-01, but a real fill never reaches the store live. |
| 5 | **RECON-05**: Restart rehydration is two-sided (store INTENT + live venue reconcile) before `status=RUNNING`; brackets re-link by `venue_order_id` | VERIFIED (mechanism, with WARNING) | `VenueReconciler.reconcile()` (`itrader/portfolio_handler/reconcile/venue_reconciler.py`) is invoked in `start()` (lines 1017-1035) **independent of CR-01** — it is gated only on `hasattr(self._order_storage, 'rehydrate')`, not on the OKX exchange connect. Confirmed via `test_two_sided_restart.py` (agree / downtime-fill / orphan-position scenarios, 3 passed) and `test_bracket_restart_relink.py` (2 passed) against a real testcontainers Postgres. `venue_order_id` persisted on `Order` + migration `p05_venue_order_id` confirmed. **WR-02 confirmed**: rehydrated orders never repopulate `OkxExchange`'s in-memory correlation maps (`_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId` — all populated only by `_submit_order`, which never runs for a pre-restart order). A fill for a rehydrated resting order after restart is buffered under `_pending_fills_by_venue_id` and never drained; a cancel of a rehydrated order is a silent no-op. No `adopt_venue_correlation`-style seam exists (`grep` confirms). Compounded by CR-01 today since no live fill streams at all yet. |
| 6 | **RECON-06**: Order I/O + reconciliation + persistence + restart validated against OKX sandbox (real-money is a gated stretch, not DoD) | ? UNCERTAIN | Offline reconciliation gate is deterministic, credential-free, and green (all 69 unit+integration tests pass under `filterwarnings=["error"]`). The opt-in, network-gated live-sandbox suite (`tests/e2e/test_okx_sandbox_recon.py`) exists with `skipif`-no-creds scaffolding but was not run against a live sandbox account in this verification (requires `OKX_API_*` credentials + network). Routed to human verification below. |
| 7 | **RES-01**: Live resilience — reconnect with gap recovery, rate-limit handling, partial-fill handling; publish-and-continue hardened | ✗ FAILED | Data-arm reconnect supervisor (`okx_provider.py::_run_stream_supervisor`, exponential backoff, debounce, `_on_stream_healthy`) IS live-active (`start_stream()` is called from `start()`). Order-arm supervisor exists in `okx.py` with identical machinery and passes 12 unit tests (`test_reconnect_resilience.py`) but is **never live-active** — same root cause as CR-01 (never spawned). **WR-04 confirmed**: `_maybe_resume_after_reconnect` only re-snapshots `VenueAccount` balances; it never re-runs `VenueReconciler.reconcile()`, directly contradicting the 05-08 must-have "resumes only after reconnect + a fresh REST snapshot/reconcile" and its own docstring/log ("REST reconcile complete"). |
| 8 | Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression; live/venue machinery off the backtest hot path | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (byte-exact 134/46189.87730727451, determinism-identical, confirmed independently in this session). Extended inertness probe (`test_okx_inertness.py`) passes, including the 05-09 addition forbidding `venue_reconciler` on the backtest import path. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any of the 15 phase-modified source files. |

**Score:** 5/8 truths verified (2 FAILED — CR-01-rooted; 1 UNCERTAIN — needs live sandbox credentials)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/reconcile/drift.py` | `is_within_single_unit_tolerance` (D-01) | ✓ VERIFIED | Present, unit-tested |
| `itrader/core/enums/system.py` | `SystemStatus.HALTED` (D-07) | ✓ VERIFIED | Present |
| `itrader/trading_system/alert_sink.py` | `AlertSink` Protocol + `LogAlertSink` (D-06) | ✓ VERIFIED | Present, wired into `EventHandler._log_error_event` |
| `itrader/portfolio_handler/account/venue.py` | Cached-venue body, `snapshot()`, reserve/release overlay | ✓ VERIFIED | 323 lines, all must-have contents present |
| `itrader/execution_handler/exchanges/okx.py` | Fill-ID dedup + fast-fill-race buffer; reconnect supervisor | ✓ VERIFIED (code) / ⚠️ ORPHANED (runtime) | Code correct and unit-tested; `connect()` (the spawn site) is never invoked from the live composition root — the artifact is functionally orphaned in production (CR-01) |
| `itrader/order_handler/reconcile/reconcile_manager.py` | Cumulative-filled accumulation + terminalization | ✓ VERIFIED (code) | Correct logic; unreachable live per CR-01. WR-03: mutates `filled_quantity` before validating the state transition (dormant bug — `allow_same_status=True` currently never fails) |
| `itrader/trading_system/live_trading_system.py` | `CachedSql*` wiring, `EventType.BAR` metrics, halt state machine, VenueAccount wiring | ✓ VERIFIED | All present; the ONE missing call is `self._okx_exchange.connect()` in `start()` |
| `itrader/portfolio_handler/reconcile/venue_reconciler.py` | Two-sided restart reconcile → reconciling FillEvents / halt + bracket re-link | ✓ VERIFIED | `def reconcile` present, >60 lines, tested against a real Postgres testcontainer |
| `itrader/order_handler/order.py` | Nullable `venue_order_id` on `Order` | ✓ VERIFIED | Confirmed + migration `p05_venue_order_id` |
| `tests/e2e/test_okx_sandbox_recon.py` | Opt-in slow sandbox reconciliation suite scaffold | ✓ VERIFIED (scaffold) | `skipif` present; not run against live credentials in this pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `full_event_handler.py::_log_error_event` | `AlertSink.alert` | injected sink on CRITICAL | ✓ WIRED | Confirmed |
| `venue.py::_stream_account` | `connector.client.watch_balance` | spawned async cache-write | ✓ WIRED | `start_streaming()` called from `live_trading_system.py:1011` |
| `portfolio_handler.py::on_fill` | `drift.is_within_single_unit_tolerance` | engine-thread compare | ✓ WIRED | Confirmed |
| `live_trading_system.py::get_status` | `SystemStatus.HALTED` | halt_reason surfaced | ✓ WIRED | Confirmed |
| `okx.py::_handle_trade` | `self._seen_trade_ids` | dedup by trade id | ✓ WIRED (unit-level) | Confirmed in code; not live-reachable (CR-01) |
| `reconcile_manager.py` | `VALID_ORDER_TRANSITIONS` | PENDING→PARTIALLY_FILLED→{FILLED,CANCELLED} | ✓ WIRED | Confirmed |
| `live_trading_system.py` | `SignalStorageFactory.create('live')` | async best-effort signal store | ✓ WIRED | Confirmed |
| `live_trading_system.py` | `portfolio.record_metrics(event.time)` | keyed on `EventType.BAR` | ✓ WIRED | Confirmed |
| `venue_reconciler.py` | `global_queue.put(FillEvent ...)` | reconciling event pre-RUNNING | ✓ WIRED | Confirmed, tested |
| `live_trading_system.py` | `venue_reconciler.reconcile` | invoked before `status=RUNNING` | ✓ WIRED | Confirmed at lines 1017-1035 |
| **`live_trading_system.py::start()`** | **`self._okx_exchange.connect()`** | **spawn order-arm fill/order streams** | **✗ NOT WIRED** | **CR-01 — this is the missing link. Grep-confirmed zero call sites.** |
| `okx.py` reconnect supervisor | `live_trading_system` halt/pause entrypoint | fatal/exhausted → HALTED; disconnect → pause | ⚠️ ORPHANED | Correct wiring exists inside `_stream_fills`/`_stream_orders`, but those coroutines are never spawned live |
| `run_paper_replay` | base fail-fast `_on_handler_error` | replay vs live error-policy split | ✓ WIRED | Confirmed, D-17 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All Phase-5 unit tests green | `poetry run pytest tests/unit/execution/test_reconnect_resilience.py tests/unit/execution/test_okx_fill_idempotency.py tests/unit/order/test_partial_fill_terminalize.py tests/unit/portfolio/test_venue_account_cache.py tests/unit/portfolio/test_venue_account_drift.py tests/unit/execution/test_drift_halt_policy.py -q` | 57 passed | ✓ PASS |
| All Phase-5 integration tests green | `poetry run pytest tests/integration/test_store_live_drive.py tests/integration/test_live_bar_metrics.py tests/integration/test_two_sided_restart.py tests/integration/test_bracket_restart_relink.py tests/integration/test_okx_inertness.py -q` | 12 passed | ✓ PASS |
| No test exercises full live `start()` + asserts fill-stream spawn | `grep` for `_okx_exchange.connect(` across `tests/` and `itrader/` | 0 matches anywhere | ✗ FAIL (confirms CR-01 gap was never caught by the test suite) |
| Backtest oracle byte-exact (recurring milestone gate) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| Debt markers in phase-touched files | `grep -n -E "TBD\|FIXME\|XXX\|TODO\|HACK\|PLACEHOLDER"` across all 15 reviewed files | 0 matches | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention or phase-declared probes found for this phase. Skipped.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| RECON-01 | 05-01, 05-03, 05-04 | `VenueAccount` cache + per-symbol drift reconciliation | ✓ SATISFIED | Truth #1 |
| RECON-02 | 05-05 | Idempotent partial-fill handling, venue source of truth | ✗ BLOCKED | Truth #2 — CR-01 |
| RECON-03 | 05-01, 05-04 | Halt-and-alert default, tolerance-band auto-correct | ✓ SATISFIED (warning: WR-01) | Truth #3 |
| RECON-04 | 05-06, 05-09 | v1.6 store driven by real OKX feed, split write paths | ✓ SATISFIED (mechanism; caveat on fill-driven writes) | Truth #4 |
| RECON-05 | 05-07 | Two-sided restart rehydration + bracket re-link | ✓ SATISFIED (warning: WR-02) | Truth #5 |
| RECON-06 | 05-02, 05-09 | Validated against OKX sandbox | ? NEEDS HUMAN | Truth #6 |
| RES-01 | 05-01, 05-02, 05-04, 05-08, 05-09 | Reconnect resilience, rate limits, hardened publish-and-continue | ✗ BLOCKED | Truth #7 — CR-01 + WR-04 |

No orphaned requirements: all 7 phase requirement IDs (RECON-01..06, RES-01) appear in the `requirements:` frontmatter of at least one of the 9 plans, and REQUIREMENTS.md's traceability table maps all 7 to Phase 5 with no unmapped IDs.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/trading_system/live_trading_system.py` | `start()` ~984-1035 | Missing call: `self._okx_exchange.connect()` never invoked | 🛑 BLOCKER | CR-01 — live fills never arrive (RECON-02, RES-01 order arm) |
| `itrader/trading_system/live_trading_system.py` | 529-546 (`halt()`) | Non-atomic check-and-set across two lock acquisitions | ⚠️ WARNING | WR-01 — concurrent halt callers can double-alert / clobber reason |
| `itrader/execution_handler/exchanges/okx.py` | 108-127, 287-349 | No correlation-map repopulation seam for rehydrated orders | ⚠️ WARNING | WR-02 — post-restart fills/cancels for rehydrated orders silently lost/no-op |
| `itrader/order_handler/reconcile/reconcile_manager.py` | 177-200 | `filled_quantity` mutated before `add_state_change` validates | ℹ️ INFO | WR-03 — currently dormant (transition never rejected today); latent trap for future validation changes |
| `itrader/trading_system/live_trading_system.py` | 615-638 (`_maybe_resume_after_reconnect`) | Only re-snapshots balances; never re-runs `VenueReconciler.reconcile()` | ⚠️ WARNING | WR-04 — contradicts documented/logged "REST reconcile complete" behavior; direct must-have violation for 05-08 |
| `itrader/portfolio_handler/portfolio_handler.py` | 733-743 (`_compare_symbol_drift`) | Adopt-and-continue branch logs without correcting engine state | ℹ️ INFO | WR-05 — dormant this phase (`_drift_reconciler` defaults `None`); documented extension point, no functional impact today |

No `TBD`/`FIXME`/`XXX`/unreferenced debt markers found in any of the 15 phase-touched files.

### Human Verification Required

#### 1. Live OKX sandbox end-to-end validation (after CR-01 is fixed)

**Test:** With `OKX_API_*` sandbox credentials set, run the opt-in slow suite (`tests/e2e/test_okx_sandbox_recon.py`) and/or a manual live-sandbox session, submitting a real order and confirming a real fill streams back and updates the portfolio/order-mirror/store.
**Expected:** A fill streams back via `watch_my_trades`, `OrderHandler.on_fill`/`PortfolioHandler.on_fill` fire, the order mirror terminalizes, and the position/cash update in the store.
**Why human:** Requires live network access + OKX sandbox credentials; cannot be verified by static analysis. Currently would fail immediately since CR-01 is unfixed (no fill stream is spawned at all).

## Gaps Summary

One BLOCKER (CR-01) and one cascading BLOCKER-class gap (RES-01's order-arm resilience, plus the
directly-contradicting WR-04 resume behavior) prevent the phase goal from being achieved as delivered.
`OkxExchange.connect()` — the sole spawn point for the live fill/order streams — is never called from
`LiveTradingSystem.start()`. This is a single, well-isolated omission (one missing method call plus error
handling), but its effect is total for the live path: no real fill ever reaches the engine, so
RECON-02 (the phase's core partial-fill/idempotency deliverable) cannot function, and the RES-01
reconnect-supervisor built for the order arm in 05-08 is dead code in production. RECON-01, RECON-03
(with a WR-01 caveat), RECON-04 (mechanism, with a fill-driven-write caveat), and RECON-05 (mechanism,
with a WR-02 caveat) are otherwise well-implemented and test-covered in isolation — the reconciliation,
persistence, and restart-rehydration *logic* is sound; it is the live wiring that is incomplete.
RECON-06 (sandbox validation) is UNCERTAIN pending human/network verification and would not currently
demonstrate live fills regardless, given CR-01.

**Recommended fix path:** land the CR-01 fix (call `self._okx_exchange.connect()` in `start()`,
propagating a `ConnectionResult` failure to `SystemStatus.ERROR` the way `_okx_connector.connect()`
already does), then re-verify RECON-02/RES-01 truths and re-run this report. WR-01, WR-02, and WR-04 are
independent, real defects worth fixing in the same or a follow-up pass — WR-03 and WR-05 are currently
dormant and lower priority.

---

_Verified: 2026-07-02T20:10:23Z_
_Verifier: Claude (gsd-verifier)_
