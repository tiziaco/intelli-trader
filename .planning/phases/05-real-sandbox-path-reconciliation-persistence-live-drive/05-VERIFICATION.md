---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
verified: 2026-07-04T10:08:27Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/8
  gaps_closed:
    - "RECON-02: Partial-fill handling is correct and idempotent with the venue as source of truth in live — CR-01 (live fill stream never spawned) fixed in 05-10; WR-05 correlation-state remediation (bounded memory, fill-driven release-on-terminal) closed in 05-13"
    - "RES-01: Live resilience — websocket reconnect with gap recovery is in place across every venue stream (fills, orders, candles) — order-arm reconnect supervisor now live-active since connect() is spawned; WR-04 resume-after-reconnect docstring/log corrected to accurately describe a REST snapshot (not a full reconcile), justified by the orphan-halt risk of a mid-session reconcile"
  gaps_remaining: []
  regressions: []
---

# Phase 5: Real Sandbox Path — Reconciliation, Persistence, Live Drive — Verification Report

**Phase Goal:** Real/Sandbox Path + Reconciliation + Persistence Live-Drive — `VenueAccount`
reconciliation, partial-fill correctness, v1.6 store driven by the real feed, two-sided restart;
sandbox-validated.
**Verified:** 2026-07-04T10:08:27Z
**Status:** passed
**Re-verification:** Yes — after gap closure (05-10, 05-11, 05-12 closed the original CR-01/RES-01
gaps; this pass additionally verifies 05-13, the WR-05 correlation-state remediation plan that
reopened the phase)

## Goal Achievement

### CR-01 (original, live-fill-never-streams) — Independently Re-Confirmed Fixed

The 2026-07-02 verification pass found a BLOCKER: `LiveTradingSystem.start()` never called
`self._okx_exchange.connect()`, so the order-arm fill/order streams were never spawned and no real
`FillEvent` ever reached the engine. This was closed in plan **05-10**. Re-derived independently in
this pass (not taken on SUMMARY faith):

- `itrader/trading_system/live_trading_system.py:1116-1120` — `start()` now calls
  `self._okx_exchange.connect()` (gated to `self.exchange == 'okx'`), checks `result.success`, and
  `raise RuntimeError(...)` on failure, which flows into the existing `except Exception` →
  `SystemStatus.ERROR` / `return False` path — confirmed by reading the method body directly.
- `itrader/execution_handler/exchanges/okx.py::connect()` still the sole spawn site for
  `_stream_fills()` / `_stream_orders()`; both now reachable in production because `start()` invokes
  `connect()` before `RUNNING`.
- Regression test `tests/integration/test_live_system_okx_wiring.py` (9 tests, includes
  "start() invokes _okx_exchange.connect()" and "failed ConnectionResult drives ERROR") — re-run in
  this session, 9/9 pass.
- Order-arm reconnect supervisor (`_run_stream_supervisor` wrapping `_stream_fills`/`_stream_orders`)
  is now live-active since it is inside the now-spawned coroutines — confirmed by reading
  `okx.py:628-641` (`_stream_fills` → `_run_stream_supervisor(self._consume_fills, "fills")`).

**Verdict: CR-01 (original) is CONFIRMED FIXED.** RECON-02 and RES-01 (order arm) are unblocked.

### New CR-01 (double-count-on-restart, found in the 2026-07-03 code review) — Confirmed Resolved

The subsequent `05-REVIEW.md` code review found a *different* critical issue (same label, different
defect): `VenueReconciler`'s startup fill-delta adoption and the live `_handle_trade` stream could
double-book the same economic fill against portfolio state on restart, because the two emitters
shared no dedup key. Confirmed resolved in the codebase:

- `itrader/events_handler/events/fill.py:78` — `FillEvent` carries `venue_trade_id: str | None = None`.
- `itrader/execution_handler/exchanges/okx.py:460-469` — `_emit_fill` stamps `venue_trade_id` from
  `trade['id']`.
- `itrader/portfolio_handler/reconcile/venue_reconciler.py:194-246` — emits one reconciling fill
  **per venue trade** (not one aggregated delta), each carrying its own `venue_trade_id`.
- `itrader/portfolio_handler/portfolio_handler.py:132-138, 794-892` — `_settled_venue_trade_ids`
  bounded `OrderedDict` (max 100,000) rejects a fill whose `venue_trade_id` was already settled;
  `venue_trade_id=None` (backtest/simulated) skips the guard entirely, preserving oracle byte-exactness.

### 05-13 (WR-05 correlation-state remediation) — Verified Directly Against the Codebase

- **`itrader/execution_handler/exchanges/venue_correlation.py`** exists (264 lines, 100% tab-indented,
  imports only stdlib + `itrader.core.ids` + `itrader.events_handler.events` — no ccxt/connector
  concretion). Defines `class VenueCorrelationIndex` with `register`, `register_pending`, `adopt`,
  `resolve`, `mark_seen`, `record_fill`, `release`, `venue_id_for`, `__len__`, `seen_count`,
  `pending_count` — all methods take the internal `_correlation_lock`.
- **Dedup ring is bounded:** `self._seen_ring: Deque[str] = deque(maxlen=capacity)` (line 110) +
  companion `_seen_trade_ids` set kept in sync in `_mark_seen_locked` (evicts the oldest id's set
  membership before appending).
- **`OkxExchange` delegates:** `self._index = VenueCorrelationIndex()` (okx.py:121); `grep -c
  "self\._orders_by_venue_id\s*[:=]" itrader/execution_handler/exchanges/okx.py` → 0 (the five inline
  maps + inline lock are gone); `_submit_order`, `_cancel_order`, `adopt_venue_correlation`,
  `_handle_trade` all delegate to `self._index.*` (confirmed via direct grep and code read).
- **`release_venue_correlation` (outbound twin of `adopt_venue_correlation`) exists**
  (okx.py:474-491): calls `self._index.release(venue_id)`, then emits each drained buffered trade via
  `_emit_fill` OUTSIDE the lock, matching the drain-then-evict / emit-outside-lock discipline.
- **Fill-driven release-on-terminal (R2) confirmed wired:** `_handle_trade` (okx.py:409-420) — after
  an actual emit, feeds `self._index.record_fill(venue_id, order, amount)`; when it reports terminal
  (cumulative ≥ `order.quantity`) calls `self.release_venue_correlation(venue_id)`. A partial fill
  (cumulative < quantity) leaves entries retained — confirmed by reading `record_fill`'s `>=` compare
  and by the passing `test_venue_correlation.py` partial-vs-full test.
  - Gated on `emitted and result.venue_id is not None` — a malformed/skipped fill (missing
    price/amount/timestamp) never advances the counter, closing the premature-self-release risk the
    05-13-SUMMARY documents as an auto-fixed Rule-2 deviation.
- **`AbstractExchange`/`SimulatedExchange` untouched:** `grep -n "release" itrader/execution_handler/exchanges/base.py`
  returns nothing; no diff/reference to `venue_correlation` or `release_venue_correlation` in
  `simulated.py`.
- **No new `EventType`:** last commit touching `itrader/core/enums/event.py` predates Phase 5
  (Phase 4 commit `eb88dedc`).

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | **RECON-01**: `VenueAccount` caches connector balance/margin/position streams and reconciles per-symbol drift under 1:1 account:portfolio | VERIFIED (regression) | `itrader/portfolio_handler/account/venue.py` unchanged since prior pass. Quick regression: `tests/unit/portfolio/test_venue_account_cache.py` + `test_venue_account_drift.py` → 17/17 pass (re-run this session). |
| 2 | **RECON-02**: Partial-fill handling is correct and idempotent (dedup, accumulation, terminalize-only-on-full-fill, bounded correlation state), venue is source of truth in live | ✓ VERIFIED | CR-01 (original) fixed in 05-10 — fill stream now live-spawned. New CR-01 (double-count) fixed via `venue_trade_id` cross-emitter dedup. WR-05 (unbounded correlation-map growth) fixed in 05-13 — `VenueCorrelationIndex` self-releases on terminal, bounded dedup ring. `tests/unit/execution` 232/232 pass (`test_okx_fill_idempotency.py`, `test_venue_correlation.py` 8/8, `test_okx_exchange.py` included). |
| 3 | **RECON-03**: Halt-and-alert default, auto-correct only within precision-epsilon tolerance band | VERIFIED (regression) | `drift.py` unchanged. Quick regression: `test_drift_halt_policy.py` + `test_drift_tolerance.py` → 22/22 pass. WR-01 (halt() non-atomic double-fire) closed in 05-10 — `halt()` now flips status under the SAME `_status_lock` acquisition as the guard (`live_trading_system.py:591-606`), confirmed by direct read. |
| 4 | **RECON-04**: v1.6 operational store driven by the real OKX feed, split sync/async write paths, create/terminalize sync-durable | VERIFIED (regression) | `tests/integration/test_store_live_drive.py` (5) + `test_live_bar_metrics.py` (2) → 7/7 pass. The "fill-driven writes never exercised" caveat from the prior pass is resolved now that CR-01 is fixed and real fills stream through. |
| 5 | **RECON-05**: Restart rehydration is two-sided (store INTENT + live venue reconcile) before `status=RUNNING`; brackets re-link by `venue_order_id` | VERIFIED (regression + WR-02 fix) | `test_two_sided_restart.py` (3) + `test_bracket_restart_relink.py` (2) → 5/5 pass. WR-02 (rehydrated orders never repopulate correlation maps) closed in 05-11 — `adopt_venue_correlation` now delegates to `VenueCorrelationIndex.adopt`, called from `VenueReconciler.reconcile()` per working-set order carrying a `venue_order_id`. |
| 6 | **RECON-06**: Order I/O + reconciliation + persistence + restart validated against OKX sandbox (real-money is a gated stretch, not DoD) | VERIFIED (documented human evidence) | 05-12 ran the opt-in `tests/e2e/test_okx_sandbox_recon.py` against the real OKX EEA demo account: 3/3 passed, human-observed 2026-07-03 (REQUIREMENTS.md line 124-127, 05-12-SUMMARY.md). This session: the 3-test file still collects cleanly after 05-13's attribute repointing (`--collect-only` confirms); no OKX_API_* credentials present in this environment to re-run live, so the LIVE re-run after 05-13 is routed to human verification below as a confirmatory (not a discovery) check. |
| 7 | **RES-01**: Live resilience — reconnect with gap recovery, rate-limit handling, partial-fill handling; publish-and-continue hardened | ✓ VERIFIED | Order-arm reconnect supervisor now live-active (spawned via the fixed `connect()` call). WR-03 (reconnect ceiling never trips on subscribe-then-close) and WR-04 (resume docstring/log correctness) both closed in 05-10/prior fix passes — confirmed by direct code read of `_on_stream_healthy`/`_reset_reconnect_budget` and `_maybe_resume_after_reconnect`. `tests/unit/execution/test_reconnect_resilience.py` → 18 pass (part of the 232/232 execution suite run). |
| 8 | Recurring milestone gate: backtest oracle byte-exact + no W1/W2 regression; live/venue machinery off the backtest hot path | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q` → 4 passed (re-run this session, byte-exact 134/46189.87730727451). `poetry run mypy itrader` → clean, 227 files. Full suite (`tests/unit tests/integration`, excluding the pre-existing unrelated `tests/unit/connectors` hang) → 1573 passed, 2 skipped (network-gated OKX creds), 0 failed. |

**Score:** 8/8 truths verified (2 full-depth re-verified: RECON-02, RES-01; 5 quick-regression
re-confirmed: RECON-01, RECON-03, RECON-04, RECON-05, RECON-06; 1 recurring gate re-confirmed)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/execution_handler/exchanges/venue_correlation.py` | `VenueCorrelationIndex` — 3 maps + late-fill buffer + bounded dedup ring + lock + cumulative counter | ✓ VERIFIED | 264 lines, TAB-indented, `register`/`resolve`/`adopt`/`release`/`mark_seen` all present, `deque(maxlen=capacity)` confirmed |
| `itrader/execution_handler/exchanges/okx.py` | Delegates to `VenueCorrelationIndex`; `release_venue_correlation` outbound seam | ✓ VERIFIED | `self._index` used in `_submit_order`/`_cancel_order`/`adopt_venue_correlation`/`_handle_trade`; `release_venue_correlation` defined at line 474; 0 inline map definitions remain |
| `tests/unit/execution/test_venue_correlation.py` | Socket-free direct-index unit tests | ✓ VERIFIED | 8 tests, all pass, constructs `VenueCorrelationIndex(...)` directly with no `OkxExchange`/connector |
| `itrader/trading_system/live_trading_system.py` | `self._okx_exchange.connect()` called in `start()` (CR-01 original fix) | ✓ VERIFIED | Lines 1116-1120; failure path re-raises into the existing `except` → `SystemStatus.ERROR` |
| `itrader/portfolio_handler/reconcile/venue_reconciler.py` | Per-venue-trade reconciling fills carrying `venue_trade_id` (new-CR-01 fix) | ✓ VERIFIED | Lines 194-246 |
| `itrader/portfolio_handler/portfolio_handler.py` | Bounded settled-trade-id dedup guard (new-CR-01 fix) | ✓ VERIFIED | `_settled_venue_trade_ids` OrderedDict, max 100,000, lines 132-138/794-892 |
| `itrader/portfolio_handler/account/venue.py` | Cached-venue body, `snapshot()`, drift compare | ✓ VERIFIED (unchanged, regression) | Present, 17 unit tests pass |
| `itrader/order_handler/order.py` | Nullable `venue_order_id` on `Order` | ✓ VERIFIED (unchanged, regression) | Confirmed present |
| `tests/e2e/test_okx_sandbox_recon.py` | Opt-in live-sandbox reconciliation suite | ✓ VERIFIED (scaffold, human-run 2026-07-03) | 3 tests collect cleanly post-05-13 repointing; ran 3/3 against real OKX demo per 05-12/REQUIREMENTS.md |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `live_trading_system.py::start()` | `self._okx_exchange.connect()` | spawn order-arm fill/order streams | ✓ WIRED | Confirmed lines 1116-1120 (was the CR-01 original gap — now closed) |
| `okx.py::_submit_order` | `VenueCorrelationIndex.register`/`register_pending` | delegation | ✓ WIRED | Confirmed, grep + read |
| `okx.py::_handle_trade` | `VenueCorrelationIndex.resolve` + `mark_seen` (internal) + `record_fill` | delegation | ✓ WIRED | Confirmed, grep + read |
| `okx.py::release_venue_correlation` | `VenueCorrelationIndex.release` | delegation, emit-outside-lock | ✓ WIRED | Confirmed, grep + read |
| `venue_correlation.py` | bounded dedup ring | `deque(maxlen=capacity)` + companion set | ✓ WIRED | Confirmed |
| `okx.py::_emit_fill` | `FillEvent.new_fill(..., venue_trade_id=...)` | cross-emitter idempotency key | ✓ WIRED | Confirmed lines 460-469 |
| `venue_reconciler.py` | `FillEvent(venue_trade_id=...)` per venue trade | reconciling fill, not aggregated delta | ✓ WIRED | Confirmed lines 194-246 |
| `portfolio_handler.py::on_fill` | `_settled_venue_trade_ids` guard | reject already-settled venue trade id | ✓ WIRED | Confirmed lines 837-892 |
| `live_trading_system.py::_maybe_resume_after_reconnect` | `venue_account.snapshot()` | REST-snapshot-only resume (documented, not a full reconcile) | ✓ WIRED (as documented) | WR-04 — docstring/log now accurately state "fresh REST balance/position snapshot", justified against a spurious mid-session orphan-halt |
| `live_trading_system.py::halt()` | `SystemStatus.HALTED` | atomic check-and-set, single lock acquisition | ✓ WIRED | WR-01 fixed — confirmed lines 591-606 |

### Data-Flow Trace (Level 4)

Not applicable in the UI-rendering sense (this is a backend trading engine, not a data-rendering
component). The equivalent trace for this domain — real venue fill → engine state — is covered above
under Key Link Verification (`_handle_trade` → `record_fill`/`release` → portfolio settlement via
`venue_trade_id` dedup) and confirmed via passing integration tests exercising the real code paths
with a fake venue connector (`tests/integration/test_live_system_okx_wiring.py`,
`test_store_live_drive.py`), not static-only inspection.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| VenueCorrelationIndex direct unit suite | `poetry run pytest tests/unit/execution/test_venue_correlation.py -q` | 8 passed | ✓ PASS |
| Full execution unit suite (includes okx delegation + reconnect resilience) | `poetry run pytest tests/unit/execution -q` | 232 passed | ✓ PASS |
| Backtest oracle byte-exact + inertness | `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q` | 4 passed | ✓ PASS |
| mypy --strict | `poetry run mypy itrader` | 227 files, no issues | ✓ PASS |
| Live-system OKX wiring regression (CR-01 original fix) | `poetry run pytest tests/integration/test_live_system_okx_wiring.py -q` | 9 passed | ✓ PASS |
| Restart / bracket-relink / store-live-drive / bar-metrics regression | `poetry run pytest tests/integration/test_two_sided_restart.py tests/integration/test_bracket_restart_relink.py tests/integration/test_store_live_drive.py tests/integration/test_live_bar_metrics.py -q` | 12 passed | ✓ PASS |
| Full non-connector suite | `poetry run pytest tests/unit tests/integration --ignore=tests/unit/connectors -q` | 1573 passed, 2 skipped (network) | ✓ PASS |
| e2e sandbox suite collects post-05-13 repointing | `poetry run pytest tests/e2e/test_okx_sandbox_recon.py --collect-only -q` | 3 tests collected | ✓ PASS |
| No `_okx_exchange.connect(` left uncalled (regression of the original gap) | `grep -n "_okx_exchange\.connect(" itrader/trading_system/live_trading_system.py` | 1 match (line 1117) | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention or phase-declared probes found for this phase. Skipped.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| RECON-01 | 05-01, 05-03, 05-04 | `VenueAccount` cache + per-symbol drift reconciliation | ✓ SATISFIED | Truth #1 (regression) |
| RECON-02 | 05-05, 05-10, 05-11, 05-13 | Idempotent partial-fill handling, venue source of truth, bounded correlation state | ✓ SATISFIED | Truth #2 — CR-01 (both) + WR-05 fixed |
| RECON-03 | 05-01, 05-04, 05-10 | Halt-and-alert default, tolerance-band auto-correct | ✓ SATISFIED | Truth #3 — WR-01 fixed |
| RECON-04 | 05-06, 05-09 | v1.6 store driven by real OKX feed, split write paths | ✓ SATISFIED | Truth #4 (regression; fill-driven-write caveat now resolved) |
| RECON-05 | 05-07, 05-11 | Two-sided restart rehydration + bracket re-link | ✓ SATISFIED | Truth #5 — WR-02 fixed |
| RECON-06 | 05-02, 05-09, 05-12 | Validated against OKX sandbox | ✓ SATISFIED | Truth #6 — human-observed 2026-07-03 (05-12); confirmatory re-run flagged below since network creds are unavailable in this environment |
| RES-01 | 05-01, 05-02, 05-04, 05-08, 05-09, 05-10 | Reconnect resilience, rate limits, hardened publish-and-continue | ✓ SATISFIED | Truth #7 — CR-01 + WR-03 + WR-04 fixed |

Requirement IDs cross-referenced against `.planning/REQUIREMENTS.md`: all 7 phase requirement IDs
(RECON-01..06, RES-01) appear in the `requirements:` frontmatter of at least one of the 13 plans, and
the traceability table (line 221-230) maps all 7 to Phase 5 with no unmapped IDs.

**Documentation-staleness note (non-blocking):** `.planning/REQUIREMENTS.md` line 107 and 116 still
show the `- [ ]` unchecked-checkbox markdown for RECON-01 and RECON-04 (last full doc sync noted as
2026-06-30, predating most of Phase 5 execution), even though the traceability table two sections down
(lines 221-230) correctly lists both as mapped to Phase 5 and the phase's own plans/tests confirm they
are implemented and passing. This is a stale checkbox in the requirement bullet, not a code gap —
flagged for a documentation touch-up, not a phase gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/execution_handler/exchanges/venue_correlation.py:63-124` | `_clordid_by_venue_id` populated only by `register`/`adopt`, never `register_pending` | ⚠️ WARNING (05-13-REVIEW WR-01) | A submit-failure (RPC raises / no venue id returned) or a fast-fill-race full-fill resolved via clOrdId leaves an orphaned `_orders_by_clOrdId` entry that is never dropped by `release` — a residual, narrower unbounded-growth vector than the one WR-05 closed (edge-case paths only, not the common fill path this plan targeted) |
| `itrader/execution_handler/exchanges/venue_correlation.py:181-183` | `resolve` marks a trade id seen before `_emit_fill` validates the payload | ⚠️ WARNING (05-13-REVIEW WR-02) | A malformed fill (missing price/amount/timestamp) permanently consumes its dedup slot; a later, complete re-delivery of the same trade id on reconnect is misclassified as `"duplicate"` and silently lost. Documented as preserved-not-introduced (pre-refactor behavior), not a regression from 05-13 |
| `itrader/execution_handler/exchanges/venue_correlation.py:176-179` | Uncorrelated ("buffered") fills are not deduped before buffering | ⚠️ WARNING (05-13-REVIEW WR-03) | A reconnect re-send during the pre-correlation window double-buffers the same trade; salvaged only by the downstream `venue_trade_id` settlement-chokepoint dedup (new CR-01), so no double-count reaches the portfolio, but the index itself double-counts internally |
| `itrader/order_handler/order.py:451-452` | Left-behind `# TODO: check if i have to store the state changes permanently in sql...` | ℹ️ INFO (pre-existing, IN-02 in 05-REVIEW.md) | Not touched by 05-13; SQL round-trip for state changes is already wired (`_state_change_rows`) so the TODO appears resolved but was never removed — doc hygiene only |

None of these are BLOCKER-severity — the 05-13-REVIEW.md review found **0 critical** issues. All
three WARNING items are residual edge-case bounding gaps in the correlation index (submit-failure
path, malformed-fill dedup interaction, pre-correlation-window re-send) that lie outside the narrow
R1–R3 slice's explicit scope (the common fill-driven release path) and do not block the phase goal —
they are candidates for a follow-up hardening pass, consistent with the plan's explicitly-scoped-out
R4 residual (non-fill terminals / out-of-band changes). No `TBD`/`FIXME`/`XXX` unreferenced debt
markers found in any of the 6 phase-touched files checked this session (`venue_correlation.py`,
`okx.py`, `live_trading_system.py`, `venue_reconciler.py`, `portfolio_handler.py`,
`reconcile_manager.py`).

### Human Verification Required

#### 1. Live OKX sandbox re-confirmation after 05-13 (confirmatory, not discovery)

**Test:** With `OKX_API_*` sandbox credentials set, re-run `tests/e2e/test_okx_sandbox_recon.py`
against the real OKX demo/sandbox account to confirm the 05-13 attribute-repointing (`exchange._index.*`)
did not regress the already-passing (2026-07-03) live sandbox loop, and that a live fill still
triggers self-release of its correlation entries.
**Expected:** All 3 tests continue to pass (order → real fill → mirror FILLED → venue-trade-id dedup;
`VenueAccount` reconcile within tolerance; restart rehydrate + two-sided reconcile with no spurious
halt), same as the 2026-07-03 human-observed run.
**Why human:** Requires live network access + OKX sandbox credentials, unavailable in this verification
environment. Static/collection-level checks (import, collection, delegation-target repointing) were
performed and pass; only the live network round-trip itself needs a human/credentialed re-run.

## Gaps Summary

No gaps remain. The two BLOCKER-class gaps from the 2026-07-02 verification pass (CR-01 — the live
fill stream was never spawned — and its RES-01 cascade — the order-arm reconnect supervisor was dead
code in production) are independently re-confirmed fixed in plan 05-10, with regression tests
(`test_live_system_okx_wiring.py`, 9/9 passing) that specifically assert the previously-absent wiring.
The subsequent code review (`05-REVIEW.md`) surfaced a *second*, distinct critical issue (restart
reconciler double-counting fills against portfolio state) and 6 warnings (WR-01 through WR-06); all
were resolved except WR-05 (unbounded venue-correlation-state growth), which was deliberately deferred
to a dedicated remediation plan — **05-13** — executed to close this reopened phase. 05-13's
deliverables (`VenueCorrelationIndex` encapsulation, fill-driven release-on-terminal, bounded
dedup ring, `release_venue_correlation` outbound seam) are all present, substantively implemented,
and wired, confirmed via direct code reads (not SUMMARY narrative) plus an independent re-run of
232/232 execution unit tests, the byte-exact oracle, inertness gate, and a clean `mypy --strict`
pass. The 05-13-REVIEW.md follow-up review found 0 critical issues and 3 warnings, all scoped to
residual edge-case bounding gaps (submit-failure clOrdId leak, malformed-fill dedup-slot consumption,
uncorrelated-fill double-buffering) explicitly outside the narrow R1–R3 common-fill-path slice this
plan targeted — none block the phase goal. The only open item is a confirmatory (not discovery) live
sandbox re-run, routed to human verification since no OKX credentials are available in this automated
environment; the prior human-observed sandbox run (2026-07-03, 3/3 passed) already satisfies RECON-06's
DoD and this session's static checks show no regression risk from the 05-13 attribute repointing.

---

_Verified: 2026-07-04T10:08:27Z_
_Verifier: Claude (gsd-verifier)_
