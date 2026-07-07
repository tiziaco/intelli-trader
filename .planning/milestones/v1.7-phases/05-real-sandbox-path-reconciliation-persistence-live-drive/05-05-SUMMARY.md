---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 05
subsystem: reconciliation
tags: [okx, fill-stream, idempotency, dedup, fast-fill-race, partial-fill, reconcile, D-12, D-13, RECON-02]

# Dependency graph
requires:
  - phase: 05-02
    provides: "Teardown-safe FakeLiveConnector + ccxt-unified recon fixtures reusable from every Phase-5 test tree"
provides:
  - "Idempotent, race-safe OKX fill ingestion: fill-ID dedup + clOrdId pre-correlation + unmatched-fill buffer in OkxExchange._handle_trade (a reconnect re-send is a no-op; a fast fill is buffered-then-emitted, never dropped)"
  - "Partial-aware order-domain reconcile: cumulative-filled accumulation to PARTIALLY_FILLED then FILLED on completion, partial-then-cancel terminalizing CANCELLED with fills retained, no engine-imposed timeout on long-open partials"
affects: [reconciliation, order-mirror, VenueAccount, restart-rehydration, live-drive]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "add_fill-first probe in _apply_executed: the state inspection (is_active / remaining_quantity) runs ONLY on the add_fill-rejected path, so mirrors/fakes whose add_fill simply succeeds are untouched (existing reconcile suites stay green with no fake edits)"
    - "(applied, terminalized) return threading: a partial EXECUTED fill is applied but NOT terminalized, so on_fill holds the reservation and skips the terminal-only bracket post-processing"
    - "Fast-fill-race close-out via two mechanisms: a clOrdId pending correlation registered before the create_order RPC (primary) + an unmatched-fill buffer drained by _submit_order once the venue-id map lands (safety net)"

key-files:
  created:
    - tests/unit/execution/test_okx_fill_idempotency.py
    - tests/unit/order/test_partial_fill_terminalize.py
  modified:
    - itrader/execution_handler/exchanges/okx.py
    - itrader/order_handler/reconcile/reconcile_manager.py
    - tests/unit/execution/test_okx_exchange.py
    - tests/unit/order/test_order_manager.py

key-decisions:
  - "add_fill is tried FIRST in _apply_executed so the common full-fill path (and any fake whose add_fill returns True) never touches is_active/remaining_quantity — this kept all four existing reconcile-fake suites green without editing a single fake"
  - "WR-02 preserved by branching on order.is_active (not on the increment vs a possibly-mutated remaining): an EXECUTED fill for an ALREADY-TERMINAL mirror returns (applied=False, terminalized=True) so the uniform terminal release still runs (T-05-17), while a genuine partial on an ACTIVE order holds the reservation"
  - "clOrdId is passed in the create_order params (per plan) AND resolved off the echoed fill; the two existing okx param-equality assertions were updated to include it"
  - "Over-fill / non-positive increment on an ACTIVE order is HELD (mirror unchanged, reservation held), never terminalized on a bad fill — distinct from the already-terminal WR-02 release path"

requirements-completed: [RECON-02]

# Metrics
duration: 35min
completed: 2026-07-02
---

# Phase 5 Plan 05: Idempotent Fill Ingestion + Partial-Fill Reconcile Summary

**Made live fill ingestion idempotent and race-safe (fill-ID dedup + clOrdId pre-correlation + unmatched-fill buffer in `OkxExchange._handle_trade`) and made the order-domain reconcile partial-aware (cumulative-filled accumulation to PARTIALLY_FILLED then FILLED, partial-then-cancel keeping the fills), with no engine-imposed timeout on long-open partials — closing the two documented latent gaps in the OKX fill stream (D-12/D-13, Pitfall 11, RECON-02).**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-02
- **Tasks:** 2
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- **Task 1 — fill-ID dedup + fast-fill-race fix (`okx.py`, TABS preserved).** Added a `_seen_trade_ids` set so a duplicate venue `trade['id']` (a ccxt.pro reconnect re-send) is an idempotent no-op; closed the fast-fill race by registering a `clOrdId` pending correlation (`_orders_by_clOrdId`) BEFORE the `create_order` RPC and buffering any unmatched fill (`_pending_fills_by_venue_id`) that `_submit_order` re-drains once the venue-id map lands — never the old silent drop. Extracted `_emit_fill` (Decimal edge `to_money(str(x))`, WR-01 `abs()` fee-guard + None-guard, `_ms_to_dt` business time all verbatim) and `_extract_client_order_id`.
- **Task 2 — partial-aware reconcile (`reconcile_manager.py`, TABS preserved).** `_apply_executed` now accumulates a shortfall increment to `PARTIALLY_FILLED` (order stays open, reservation HELD, no timeout — D-13) and terminalizes to `FILLED` only on the completing increment; `on_fill` threads `(applied, terminalized)` so the reservation release and the terminal-only bracket post-processing (bracket consume, fill-anchored children, OVERSELL flatten) run ONLY on a fully-filled EXECUTED. Partial-then-cancel terminalizes `CANCELLED` keeping the accrued fills.
- **WR-02 preserved:** an EXECUTED fill for an already-terminal mirror still releases the reservation (branch on `order.is_active`, not on a mutated `remaining`).
- **Two new suites** (13 tests) driving dedup / buffered-not-dropped / stream-resilience and two-partials→FILLED / partial→cancel / over-fill-rejected.
- **Byte-exact oracle unaffected** (134 / 46189.87730727451) — the simulated single-fill path routes through the untouched add_fill-first branch.

## Task Commits

Each task was committed atomically:

1. **Task 1: fill-ID dedup + fast-fill-race fix in OKX `_handle_trade` (D-12/D-13)** — `731898d6` (feat)
2. **Task 2: cumulative-filled accumulation + partial terminalization (D-12)** — `f35281b6` (feat)

## Files Created/Modified

- `itrader/execution_handler/exchanges/okx.py` — `_handle_trade` dedup + clOrdId-resolve + buffer; `_submit_order` clOrdId pre-correlation before the RPC + buffer drain after; new `_emit_fill` / `_extract_client_order_id` / `_client_order_id` helpers; refreshed the stale latent-gap comment. `_seen_trade_ids` appears 4×, `clOrdId` 17×.
- `itrader/order_handler/reconcile/reconcile_manager.py` — `_apply_executed` returns `(applied, terminalized)` with the add_fill-first probe + is_active/partial/over-fill branches; `on_fill` gates `should_release` and the EXECUTED bracket block on `terminalized`; the non-EXECUTED bracket-discard is now an explicit `elif`. `PARTIALLY_FILLED` appears 8×.
- `tests/unit/execution/test_okx_fill_idempotency.py` (NEW) — 7 asyncio tests: duplicate trade id → one FillEvent, distinct ids both emit, fast fill buffered-then-emitted, clOrdId resolve, submit registers pending correlation, malformed trade / raising trade do not kill the stream.
- `tests/unit/order/test_partial_fill_terminalize.py` (NEW) — 6 tests: two/three partials→FILLED, partial-then-cancel keeps fills, over-fill (fresh + after partial) rejected, single full fill still FILLED.
- `tests/unit/execution/test_okx_exchange.py` — two `params` equality assertions updated for the new `clOrdId` param (see Deviations).
- `tests/unit/order/test_order_manager.py` — `test_partial_quantity_fill_is_rejected_by_mirror` rewritten to `..._accumulates_partially_filled` for the superseded contract (see Deviations).

## Decisions Made

- **add_fill-first probe.** Trying `order.add_fill(...)` before any state inspection means the state checks (`is_active`, `remaining_quantity`) only execute when add_fill rejects. All four existing reconcile-fake suites (whose `_FakeOrder.add_fill` returns True) therefore never touch the new attributes and stayed green with zero fake edits.
- **Branch on `is_active`, not on `remaining`.** In the already-terminal WR-02 case, `add_fill` mutates `filled_quantity` before its transition fails, so a remaining-based test would misfire. Branching on `order.is_active` cleanly separates the terminal-release path (release) from a genuine active-order partial (hold).
- **clOrdId passed in params AND resolved off the fill.** Faithful to the plan ("register a pending correlation keyed by clOrdId, passed in params"). The buffer is the secondary safety net for fills lacking an echoed clOrdId.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated two existing okx `params`-equality assertions for the new `clOrdId`**
- **Found during:** Task 1
- **Issue:** `test_market_buy_disables_requires_price_param` and `test_limit_order_submits_empty_params` asserted the exact `create_order` `params` dict; injecting the `clOrdId` pre-correlation param (required by the plan) broke both equalities.
- **Fix:** Extended both expected dicts to include `"clOrdId": OkxExchange._client_order_id(order)` (computed via the same helper, so the assertion is robust to the token format).
- **Files modified:** tests/unit/execution/test_okx_exchange.py
- **Committed in:** `731898d6`

**2. [Rule 3 - Blocking] Rewrote the superseded full-quantity-reject test to assert partial accumulation**
- **Found during:** Task 2
- **Issue:** `test_partial_quantity_fill_is_rejected_by_mirror` (test_order_manager.py) encoded the OLD full-quantity contract (a partial fill leaves the mirror PENDING with filled 0) — the exact behavior RECON-02/D-12 deliberately supersedes.
- **Fix:** Renamed to `test_partial_quantity_fill_accumulates_partially_filled` and asserted `PARTIALLY_FILLED` + `filled_quantity == 0.4`. The sibling `test_rejected_add_fill_still_releases_reservation` (WR-02) needed NO edit — the corrected `is_active` branch keeps its terminal-order release intact.
- **Files modified:** tests/unit/order/test_order_manager.py
- **Committed in:** `f35281b6`

**Total deviations:** 2 auto-fixed (both Rule 3 — existing tests updated to match a plan-mandated behavior change). No architectural changes; the simulated/backtest path and the oracle are byte-unchanged.

## Behavioral note (non-deviation)

`test_fill_for_unknown_order_is_skipped` (existing) still passes: a fill for an untracked venue order now BUFFERS (for late correlation) instead of dropping, but the queue stays empty, so the assertion holds. A truly-never-submitted venue id leaves a buffered entry — acceptable for this offline phase (the plan specifies "briefly buffer"; no eviction policy is mandated and streams are not started this phase).

## Verification Results

- `poetry run pytest tests/unit/execution/test_okx_fill_idempotency.py tests/unit/order/test_partial_fill_terminalize.py -x` → 13 passed
- `poetry run pytest tests/unit/order tests/unit/execution -q` → 452 passed (no regressions)
- `poetry run mypy --strict itrader/execution_handler/exchanges/okx.py itrader/order_handler/reconcile/reconcile_manager.py` → clean
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed (byte-exact: 134 / 46189.87730727451)
- `poetry run pytest tests/integration/test_okx_inertness.py -x` → 1 passed
- `grep -c '_seen_trade_ids' okx.py` = 4 (>=2); `grep -c 'clOrdId' okx.py` = 17 (>=1); no leading-4-space indentation in okx.py; `grep -c 'PARTIALLY_FILLED' reconcile_manager.py` = 8 (>=1)

## Known Stubs

None — no hardcoded/placeholder values introduced.

## Next Phase Readiness

- Live fills are now deduped, race-safe, and partial-aware — the order mirror is ready for the two-sided restart/reconcile plans to build on.
- The OKX stream wiring (`connect()` spawning `_stream_fills`/`_stream_orders`) is unchanged; the fill-translation seam it drives is now hardened.
- No blockers. Backtest inertness + oracle unaffected (all new behavior is on the live/venue path, oracle-dark).

## Self-Check

- `tests/unit/execution/test_okx_fill_idempotency.py` — FOUND
- `tests/unit/order/test_partial_fill_terminalize.py` — FOUND
- `itrader/execution_handler/exchanges/okx.py` — FOUND (modified)
- `itrader/order_handler/reconcile/reconcile_manager.py` — FOUND (modified)
- Commit `731898d6` — FOUND
- Commit `f35281b6` — FOUND

## Self-Check: PASSED

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
